"""Query routes — ask, stream, history, feedback."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import (
    check_rate_limit,
    get_cache,
    get_current_user,
)
from backend.api.schemas.query import (
    CitationResult,
    FeedbackRequest,
    FeedbackResponse,
    QueryHistoryItem,
    QueryHistoryResponse,
    QueryRequest,
    QueryResponse,
)
from backend.db.database import get_db
from backend.db.models.user import QueryFeedback, QueryLog, User
from backend.services.cache import ResponseCache

router = APIRouter()

_DISCLAIMER = (
    "This is AI-assisted legal information. "
    "Consult a qualified legal professional for advice specific to your situation."
)

# ---------------------------------------------------------------------------
# Response text parsers (extract metadata from agent output)
# ---------------------------------------------------------------------------

def _parse_verification_status(text: str) -> str:
    if re.search(r"VERIFIED", text, re.IGNORECASE):
        if re.search(r"PARTIALLY_VERIFIED|PARTIALLY VERIFIED", text, re.IGNORECASE):
            return "PARTIALLY_VERIFIED"
        if re.search(r"\bUNVERIFIED\b", text, re.IGNORECASE):
            return "UNVERIFIED"
        return "VERIFIED"
    return "UNVERIFIED"


def _parse_confidence(text: str) -> str:
    m = re.search(r"CONFIDENCE[:\s]+([Hh]igh|[Mm]edium|[Ll]ow)", text)
    if m:
        return m.group(1).lower()
    return "medium"


def _parse_citations(text: str) -> list[CitationResult]:
    """Extract BNS/BNSS/BSA section citations mentioned in the response."""
    citations: list[CitationResult] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"(BNS_2023|BNSS_2023|BSA_2023|IPC_1860|CrPC_1973|IEA_1872)"
        r"[\s/Ss\.]+([0-9]{1,4}[A-Za-z]?)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        key = f"{m.group(1).upper()}/{m.group(2)}"
        if key not in seen:
            seen.add(key)
            citations.append(
                CitationResult(
                    act_code=m.group(1).upper(),
                    section_number=m.group(2),
                    verification="VERIFIED",
                )
            )
    return citations[:10]  # cap at 10 to avoid noise


# ---------------------------------------------------------------------------
# POST /query/ask
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=QueryResponse)
async def ask(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: ResponseCache = Depends(get_cache),
):
    """Submit a legal query and receive a fully verified response."""
    await check_rate_limit(current_user, db)

    # --- Cache check ---
    cached_response = await cache.get(request.query, current_user.role)
    query_id = str(uuid.uuid4())

    if cached_response:
        return QueryResponse(
            query_id=query_id,
            query=request.query,
            response=cached_response,
            verification_status=_parse_verification_status(cached_response),
            confidence=_parse_confidence(cached_response),
            citations=_parse_citations(cached_response),
            user_role=current_user.role,
            processing_time_ms=0,
            cached=True,
            disclaimer=_DISCLAIMER,
        )

    # --- Full pipeline ---
    start = time.time()
    try:
        from backend.agents.crew_config import get_crew_for_role
        from backend.agents.query_router import handle_query

        response_text = await handle_query(
            query=request.query,
            user_role=current_user.role,
            crew_factory=get_crew_for_role,
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Agent pipeline error: {exc}") from exc

    elapsed_ms = int((time.time() - start) * 1000)

    # --- Cache the result ---
    await cache.set(request.query, current_user.role, response_text, tier="full")

    # --- Persist to DB ---
    citations = _parse_citations(response_text)
    log = QueryLog(
        id=uuid.UUID(query_id),
        user_id=current_user.id,
        query_text=request.query,
        response_text=response_text,
        verification_status=_parse_verification_status(response_text),
        confidence=_parse_confidence(response_text),
        citations=[c.model_dump() for c in citations],
        user_role=current_user.role,
        processing_time_ms=elapsed_ms,
        cached=False,
    )
    db.add(log)
    await db.commit()

    return QueryResponse(
        query_id=query_id,
        query=request.query,
        response=response_text,
        verification_status=_parse_verification_status(response_text),
        confidence=_parse_confidence(response_text),
        citations=citations,
        user_role=current_user.role,
        processing_time_ms=elapsed_ms,
        cached=False,
        disclaimer=_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# POST /query/ask/stream  — SSE
# ---------------------------------------------------------------------------

@router.post("/ask/stream")
async def ask_stream(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: ResponseCache = Depends(get_cache),
):
    """Stream the legal query response using Server-Sent Events (SSE)."""
    await check_rate_limit(current_user, db)

    async def _event_generator() -> AsyncIterator[str]:
        def _event(name: str, data: dict) -> str:
            return f"event: {name}\ndata: {json.dumps(data)}\n\n"

        # Agent progress events
        pipeline = {
            "citizen": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
            "lawyer": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "legal_advisor": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "police": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
        }
        agents = pipeline.get(current_user.role, pipeline["citizen"])

        for agent in agents[:-1]:  # all except formatter — emit upfront
            yield _event("agent_start", {"agent": agent, "message": f"{agent} is working..."})

        # Check cache first
        cached = await cache.get(request.query, current_user.role)
        if cached:
            yield _event("agent_start", {"agent": "ResponseFormatter", "message": "Formatting..."})
            # Stream the cached response in chunks
            chunk_size = 80
            for i in range(0, len(cached), chunk_size):
                yield _event("token", {"text": cached[i : i + chunk_size]})
            yield _event("complete", {
                "verification_status": _parse_verification_status(cached),
                "confidence": _parse_confidence(cached),
                "citations": [c.model_dump() for c in _parse_citations(cached)],
                "cached": True,
            })
            yield "event: end\ndata: {}\n\n"
            return

        # Full pipeline
        try:
            from backend.agents.crew_config import get_crew_for_role
            from backend.agents.query_router import handle_query

            start = time.time()
            yield _event("agent_start", {"agent": "ResponseFormatter", "message": "Formatting response..."})
            response_text = await handle_query(
                query=request.query,
                user_role=current_user.role,
                crew_factory=get_crew_for_role,
            )
            elapsed_ms = int((time.time() - start) * 1000)
        except Exception as exc:
            yield _event("error", {"code": "PIPELINE_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            return

        await cache.set(request.query, current_user.role, response_text, tier="full")

        # Stream response in chunks
        chunk_size = 80
        for i in range(0, len(response_text), chunk_size):
            yield _event("token", {"text": response_text[i : i + chunk_size]})

        citations = _parse_citations(response_text)
        yield _event("complete", {
            "verification_status": _parse_verification_status(response_text),
            "confidence": _parse_confidence(response_text),
            "citations": [c.model_dump() for c in citations],
            "processing_time_ms": elapsed_ms,
            "cached": False,
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


# ---------------------------------------------------------------------------
# GET /query/history
# ---------------------------------------------------------------------------

@router.get("/history", response_model=QueryHistoryResponse)
async def get_history(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's recent query history."""
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).where(QueryLog.user_id == current_user.id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(QueryLog)
        .where(QueryLog.user_id == current_user.id)
        .order_by(QueryLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()

    return QueryHistoryResponse(
        total=total,
        queries=[
            QueryHistoryItem(
                query_id=str(log.id),
                query_text=log.query_text,
                verification_status=log.verification_status,
                confidence=log.confidence,
                created_at=log.created_at,
            )
            for log in logs
        ],
    )


# ---------------------------------------------------------------------------
# GET /query/{query_id}
# ---------------------------------------------------------------------------

@router.get("/{query_id}", response_model=QueryResponse)
async def get_query(
    query_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously submitted query and its full response."""
    try:
        uid = uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(404, detail="Query not found.")

    result = await db.execute(
        select(QueryLog).where(
            QueryLog.user_id == current_user.id,
            QueryLog.id == uid,
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(404, detail="Query not found.")

    return QueryResponse(
        query_id=str(log.id),
        query=log.query_text,
        response=log.response_text or "",
        verification_status=log.verification_status or "UNVERIFIED",
        confidence=log.confidence or "medium",
        citations=[CitationResult(**c) for c in (log.citations or [])],
        user_role=log.user_role,
        processing_time_ms=log.processing_time_ms or 0,
        cached=log.cached,
        disclaimer=_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# POST /query/feedback
# ---------------------------------------------------------------------------

@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback on a legal response."""
    feedback = QueryFeedback(
        user_id=current_user.id,
        rating=request.rating,
        feedback_type=request.feedback_type,
        comment=request.comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        feedback_id=str(feedback.id),
        message="Feedback recorded. Thank you.",
    )
