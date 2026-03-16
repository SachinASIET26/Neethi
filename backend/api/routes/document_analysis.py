"""Document analysis routes — PageIndex-powered PDF analysis.

Returns 503 when PageIndex is not configured.
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_current_user
from backend.db.models.user import User
from backend.services.pageindex import pageindex_service

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# POST /documents/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    query: str = Form("Analyze this legal document"),
    current_user: User = Depends(get_current_user),
):
    """Upload a PDF and analyze it using PageIndex.

    Returns 503 if PageIndex is not configured.
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

    start = time.time()
    try:
        result = await pageindex_service.analyze_document(file_bytes, query)
    except Exception as exc:
        logger.error("PageIndex analysis failed: %s", exc)
        raise HTTPException(500, detail=f"Document analysis failed: {exc}") from exc

    return {
        "analysis": result,
        "filename": file.filename,
        "processing_time_ms": int((time.time() - start) * 1000),
    }


# ---------------------------------------------------------------------------
# POST /documents/analyze/stream
# ---------------------------------------------------------------------------

@router.post("/analyze/stream")
async def analyze_document_stream(
    file: UploadFile = File(...),
    query: str = Form("Analyze this legal document"),
    current_user: User = Depends(get_current_user),
):
    """Stream document analysis results using SSE."""
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

    async def _event_generator() -> AsyncIterator[str]:
        start = time.time()

        yield _event("status", {"message": "Uploading document to PageIndex..."})

        try:
            result = await pageindex_service.analyze_document(file_bytes, query)
        except Exception as exc:
            yield _event("error", {"code": "ANALYSIS_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return

        yield _event("status", {"message": "Analysis complete."})

        # Stream summary
        summary = result.get("summary", "")
        if summary:
            yield _event("token", {"text": summary})

        yield _event("complete", {
            "analysis": result,
            "processing_time_ms": int((time.time() - start) * 1000),
        })
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
