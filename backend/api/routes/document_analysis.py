"""Document analysis routes — PageIndex-powered vectorless RAG + LLM synthesis.

Flow (SSE streaming):
  status   → "Submitting document to PageIndex…"
  status   → "Building document tree…"
  status   → "Running retrieval query…"
  status   → "Synthesizing answer…"
  complete → {doc_id, query, retrieved_nodes, synthesized_answer, filename, processing_time_ms}
  end      → {}

Returns 503 when PAGEINDEX_API_KEY is not configured.
Synthesis uses Groq (Llama 3.3 70B) → DeepSeek-Chat fallback; degrades gracefully if neither key is set.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_current_user
from backend.db.models.user import User
from backend.services.pageindex import pageindex_service
from backend.services.synthesis import synthesize_answer

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB hard cap
_MAX_PAGES = 50                    # PageIndex free-tier limit


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _check_pdf(file_bytes: bytes) -> None:
    """Raise HTTPException if the PDF exceeds the PageIndex plan page limit."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        doc.close()
    except Exception:
        raise HTTPException(400, detail="Could not read PDF. The file may be corrupted.")
    if page_count > _MAX_PAGES:
        raise HTTPException(
            413,
            detail=(
                f"This PDF has {page_count} pages. "
                f"The PageIndex free tier supports up to {_MAX_PAGES} pages per document. "
                "Please upload a shorter document or upgrade your PageIndex plan."
            ),
        )


# ---------------------------------------------------------------------------
# POST /documents/analyze  (non-streaming fallback)
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    query: str = Form("Analyze this legal document"),
    current_user: User = Depends(get_current_user),
):
    """Upload a PDF and analyze it using PageIndex (blocking response)."""
    if not pageindex_service.is_available():
        raise HTTPException(
            503,
            detail="Document analysis service is not configured. "
                   "Set PAGEINDEX_API_KEY to enable this feature.",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, detail="Only PDF files are supported.")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(413, detail="File too large. Maximum size is 20 MB.")
    _check_pdf(file_bytes)

    start = time.time()
    try:
        result = await pageindex_service.analyze_document(
            file_bytes, query, filename=file.filename or "document.pdf"
        )
    except TimeoutError as exc:
        raise HTTPException(504, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("PageIndex analysis failed: %s", exc)
        raise HTTPException(500, detail=f"Document analysis failed: {exc}") from exc

    try:
        synthesized = await synthesize_answer(query, result.get("retrieved_nodes", []))
    except Exception as exc:
        logger.warning("Synthesis failed for non-streaming endpoint: %s", exc)
        synthesized = result.get("summary", "")

    return {
        **result,
        "synthesized_answer": synthesized,
        "filename": file.filename,
        "processing_time_ms": int((time.time() - start) * 1000),
    }


# ---------------------------------------------------------------------------
# POST /documents/analyze/stream  (SSE — recommended)
# ---------------------------------------------------------------------------

@router.post("/analyze/stream")
async def analyze_document_stream(
    file: UploadFile = File(...),
    query: str = Form("Analyze this legal document"),
    current_user: User = Depends(get_current_user),
):
    """Stream document analysis progress using Server-Sent Events.

    SSE events emitted:
      status   {"message": str}                  — progress updates
      complete {"doc_id", "query", "retrieved_nodes", "synthesized_answer",
                "filename", "processing_time_ms"}
      error    {"code": str, "detail": str}
      end      {}
    """
    if not pageindex_service.is_available():
        raise HTTPException(
            503,
            detail="Document analysis service is not configured. "
                   "Set PAGEINDEX_API_KEY to enable this feature.",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, detail="Only PDF files are supported.")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(413, detail="File too large. Maximum size is 20 MB.")
    _check_pdf(file_bytes)

    filename = file.filename or "document.pdf"

    async def _generate() -> AsyncIterator[str]:
        start = time.time()

        # Phase 1 — submit
        yield _sse("status", {"message": "Submitting document to PageIndex…"})
        try:
            doc_id = await pageindex_service.submit_document(file_bytes, filename)
        except Exception as exc:
            yield _sse("error", {"code": "SUBMIT_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return

        # Phase 2 — poll until tree is ready
        # Note: yielding inside a nested async callback isn't possible, so we
        # emit one status event before the blocking poll loop.
        try:
            yield _sse("status", {"message": "Building document tree…"})
            await pageindex_service.wait_for_ready(doc_id)
        except TimeoutError as exc:
            yield _sse("error", {"code": "TIMEOUT", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return
        except Exception as exc:
            yield _sse("error", {"code": "POLL_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return

        # Phase 3 — retrieval
        yield _sse("status", {"message": "Running retrieval query…"})
        try:
            retrieval = await pageindex_service.retrieve(doc_id, query)
        except Exception as exc:
            yield _sse("error", {"code": "RETRIEVAL_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return

        retrieved_nodes = retrieval.get("retrieved_nodes", [])

        # Phase 4 — LLM synthesis (Groq Llama 3.3 70B → DeepSeek-Chat fallback)
        yield _sse("status", {"message": "Synthesizing answer…"})
        try:
            synthesized_answer = await synthesize_answer(query, retrieved_nodes)
        except Exception as exc:
            logger.warning("Synthesis failed, falling back to raw excerpts: %s", exc)
            synthesized_answer = "\n\n".join(
                rc.get("relevant_content", "").strip()
                for node in retrieved_nodes
                for rc_group in node.get("relevant_contents", [])
                for rc in (rc_group if isinstance(rc_group, list) else [rc_group])
                if rc.get("relevant_content", "").strip()
            ) or "No relevant content retrieved."

        yield _sse("complete", {
            "doc_id": doc_id,
            "query": query,
            "retrieved_nodes": retrieved_nodes,
            "synthesized_answer": synthesized_answer,
            "filename": filename,
            "processing_time_ms": int((time.time() - start) * 1000),
        })
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
