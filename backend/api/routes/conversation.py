"""Conversation routes — direct CrewAI pipeline.

Each user message immediately triggers the full multi-agent CrewAI pipeline:
  QueryAnalyst → RetrievalSpecialist → [LegalReasoner] → CitationChecker → ResponseFormatter

No staged conversation, no clarifying questions, no confirmation steps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import check_rate_limit, get_cache, get_current_user
from backend.api.schemas.conversation import (
    ActionSuggestionSchema,
    SessionResponse,
    TurnRequest,
    TurnResponse,
)
from backend.db.database import get_db
from backend.db.models.user import ConversationSession, User
from backend.services.cache import ResponseCache

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _suggestions_to_schema(suggestions: list) -> list[ActionSuggestionSchema]:
    return [
        ActionSuggestionSchema(id=s.id, label=s.label, icon=s.icon, description=s.description)
        for s in suggestions
    ]


async def _get_or_create_session(
    session_id: str | None,
    user: User,
    db: AsyncSession,
) -> ConversationSession:
    if session_id:
        result = await db.execute(
            select(ConversationSession).where(
                ConversationSession.session_id == session_id,
                ConversationSession.user_id == user.id,
            )
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    new_session = ConversationSession(
        user_id=user.id,
        session_id=session_id or uuid.uuid4().hex,
        context={},
        intent_history=[],
        turn_count=0,
        status="active",
        stage="responding",
        clarification_round=0,
    )
    db.add(new_session)
    await db.flush()
    return new_session


async def _translate_if_needed(query: str, language: str) -> str:
    if not language or language.lower().startswith("en"):
        return query
    try:
        from backend.api.routes.query import _translate_to_english
        return await _translate_to_english(query, language)
    except Exception:
        return query


# ---------------------------------------------------------------------------
# Action handling (crew-based post-response actions)
# ---------------------------------------------------------------------------

async def _handle_action(
    action_id: str,
    message: str,
    session: ConversationSession,
    user: User,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    from backend.agents.response_templates import get_actions_for_role

    role_actions = get_actions_for_role(user.role)
    elapsed_ms = lambda: int((time.time() - start) * 1000)

    crew_actions = {
        "step_by_step", "legal_sections", "irac_analysis",
        "section_deep_dive", "precedent_search", "counter_arguments",
        "sop_reference", "bnss_procedure", "arrest_checklist",
        "compliance_checklist", "risk_assessment", "case_strategy",
    }
    if action_id in crew_actions:
        session.turn_count += 1
        session.stage = "responding"
        scenario = (session.context or {}).get("scenario", message or "")
        action_prefix = {
            "step_by_step": "Provide step-by-step legal guidance for: ",
            "legal_sections": "List all relevant legal sections for: ",
            "irac_analysis": "Provide a full IRAC analysis for: ",
            "section_deep_dive": "Provide detailed analysis of relevant sections for: ",
            "precedent_search": "Find relevant case law precedents for: ",
            "counter_arguments": "Analyze potential counter-arguments for: ",
            "sop_reference": "Provide standard operating procedure for: ",
            "bnss_procedure": "Detail the BNSS procedural steps for: ",
            "arrest_checklist": "Provide arrest compliance checklist for: ",
            "compliance_checklist": "Provide compliance checklist for: ",
            "risk_assessment": "Assess legal risks for: ",
            "case_strategy": "Recommend case strategy for: ",
        }
        prefixed_query = action_prefix.get(action_id, "") + scenario
        return await _fire_full_pipeline(prefixed_query, user, session, cache, start)

    draft_actions = {"draft_complaint", "fir_template", "draft_notice"}
    if action_id in draft_actions:
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="responding",
            intent="followup_action",
            response=(
                "To draft this document, please go to the **Documents** section "
                "where you can fill in the required fields and I'll generate a complete draft.\n\n"
                "Alternatively, describe what you need and I'll help you prepare the information."
            ),
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    if action_id == "find_lawyer":
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="responding",
            intent="followup_action",
            response=(
                "To find a lawyer near you, please visit the **Legal Resources** section "
                "where you can search by location and specialization.\n\n"
                "You can also call the free legal aid helpline: **15100** (NALSA)."
            ),
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    session.turn_count += 1
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage="responding",
        intent="followup_action",
        response="I'm not sure how to handle that action. Could you describe what you need?",
        suggestions=_suggestions_to_schema(role_actions),
        processing_time_ms=elapsed_ms(),
    )


# ---------------------------------------------------------------------------
# Full CrewAI pipeline
# ---------------------------------------------------------------------------

async def _fire_full_pipeline(
    query: str,
    user: User,
    session: ConversationSession,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    from backend.agents.crew_config import get_crew_for_role
    from backend.agents.query_router import handle_query
    from backend.agents.response_templates import get_actions_for_role
    from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status

    cached = await cache.get(query, user.role)
    if cached:
        citations = _parse_citations(cached)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="responding",
            intent="full_pipeline",
            response=cached,
            verification_status=_parse_verification_status(cached),
            confidence=_parse_confidence(cached),
            citations=citations,
            suggestions=_suggestions_to_schema(get_actions_for_role(user.role)),
            processing_time_ms=int((time.time() - start) * 1000),
            cached=True,
        )

    try:
        response_text = await handle_query(
            query=query,
            user_role=user.role,
            crew_factory=get_crew_for_role,
        )
    except Exception as exc:
        logger.error("Full pipeline failed: %s", exc)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="responding",
            intent="full_pipeline",
            response="I encountered an error processing your query. Please try again.",
            processing_time_ms=int((time.time() - start) * 1000),
        )

    elapsed_ms = int((time.time() - start) * 1000)
    await cache.set(query, user.role, response_text, tier="full")

    citations = _parse_citations(response_text)
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage="responding",
        intent="full_pipeline",
        response=response_text,
        verification_status=_parse_verification_status(response_text),
        confidence=_parse_confidence(response_text),
        citations=citations,
        suggestions=_suggestions_to_schema(get_actions_for_role(user.role)),
        processing_time_ms=elapsed_ms,
        cached=False,
    )


# ---------------------------------------------------------------------------
# POST /conversation/turn (sync)
# ---------------------------------------------------------------------------

@router.post("/turn", response_model=TurnResponse)
async def conversation_turn(
    request: TurnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: ResponseCache = Depends(get_cache),
):
    """Submit a legal query and receive a fully verified response via the CrewAI pipeline."""
    await check_rate_limit(current_user, db)

    session = await _get_or_create_session(request.session_id, current_user, db)
    english_message = await _translate_if_needed(request.message or "", request.language)

    start = time.time()
    session.turn_count += 1
    session.context = session.context or {}
    if english_message:
        session.context["scenario"] = english_message

    # Handle action button clicks
    if request.action_id:
        result = await _handle_action(
            request.action_id, english_message, session, current_user, cache, start,
        )
        await db.flush()
        return result

    # Handle greetings without running the full pipeline
    _greetings = {"hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye"}
    if english_message.strip().lower() in _greetings:
        from backend.agents.response_templates import get_actions_for_role, get_greeting_response
        await db.flush()
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="responding",
            intent="greeting",
            response=get_greeting_response(current_user.role),
            suggestions=_suggestions_to_schema(get_actions_for_role(current_user.role)),
            processing_time_ms=int((time.time() - start) * 1000),
        )

    # Direct CrewAI pipeline for all legal queries
    result = await _fire_full_pipeline(english_message, current_user, session, cache, start)
    await db.flush()
    return result


# ---------------------------------------------------------------------------
# POST /conversation/turn/stream (SSE)
# ---------------------------------------------------------------------------

@router.post("/turn/stream")
async def conversation_turn_stream(
    request: TurnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: ResponseCache = Depends(get_cache),
):
    """Stream a legal query response via CrewAI pipeline using Server-Sent Events."""
    await check_rate_limit(current_user, db)

    session = await _get_or_create_session(request.session_id, current_user, db)
    english_message = await _translate_if_needed(request.message or "", request.language)

    async def _event_generator() -> AsyncIterator[str]:
        from backend.agents.crew_config import get_crew_for_role
        from backend.agents.query_router import handle_query
        from backend.agents.response_templates import get_actions_for_role, get_greeting_response
        from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status

        start = time.time()
        session.turn_count += 1
        session.context = session.context or {}
        if english_message:
            session.context["scenario"] = english_message

        role_actions = get_actions_for_role(current_user.role)

        # Handle action button clicks
        if request.action_id:
            result = await _handle_action(
                request.action_id, english_message, session, current_user, cache, start,
            )
            yield _event("intent", {"intent": result.intent, "confidence": 1.0})
            chunk_size = 80
            for i in range(0, len(result.response), chunk_size):
                yield _event("token", {"text": result.response[i:i + chunk_size]})
            suggestions_data = [s.model_dump() for s in result.suggestions]
            if suggestions_data:
                yield _event("action_suggestions", {"suggestions": suggestions_data})
            yield _event("complete", {
                "session_id": session.session_id,
                "turn_number": result.turn_number,
                "stage": result.stage,
                "intent": result.intent,
                "verification_status": result.verification_status,
                "confidence": result.confidence,
                "citations": [c.model_dump() for c in result.citations] if result.citations else [],
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": result.cached,
            })
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        # Handle greetings
        _greetings = {"hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye"}
        if not english_message or english_message.strip().lower() in _greetings:
            response_text = get_greeting_response(current_user.role)
            yield _event("intent", {"intent": "greeting", "confidence": 1.0})
            chunk_size = 80
            for i in range(0, len(response_text), chunk_size):
                yield _event("token", {"text": response_text[i:i + chunk_size]})
            suggestions_data = [
                {"id": s.id, "label": s.label, "icon": s.icon, "description": s.description}
                for s in role_actions
            ]
            yield _event("action_suggestions", {"suggestions": suggestions_data})
            yield _event("complete", {
                "session_id": session.session_id,
                "turn_number": session.turn_count,
                "stage": "responding",
                "intent": "greeting",
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": False,
            })
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        # Direct CrewAI pipeline for all legal queries
        pipeline_agents = {
            "citizen": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
            "lawyer": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "legal_advisor": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "police": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
        }
        agents = pipeline_agents.get(current_user.role, pipeline_agents["citizen"])

        yield _event("intent", {"intent": "query", "confidence": 1.0})

        for agent in agents[:-1]:
            yield _event("agent_start", {"agent": agent, "message": f"{agent} is working..."})

        # Check cache
        cached_resp = await cache.get(english_message, current_user.role)
        if cached_resp:
            yield _event("agent_start", {"agent": "ResponseFormatter", "message": "Formatting..."})
            chunk_size = 80
            for i in range(0, len(cached_resp), chunk_size):
                yield _event("token", {"text": cached_resp[i:i + chunk_size]})
            citations = _parse_citations(cached_resp)
            suggestions_data = [
                {"id": s.id, "label": s.label, "icon": s.icon, "description": s.description}
                for s in role_actions
            ]
            yield _event("action_suggestions", {"suggestions": suggestions_data})
            yield _event("complete", {
                "session_id": session.session_id,
                "turn_number": session.turn_count,
                "stage": "responding",
                "intent": "full_pipeline",
                "verification_status": _parse_verification_status(cached_resp),
                "confidence": _parse_confidence(cached_resp),
                "citations": [c.model_dump() for c in citations],
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": True,
            })
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        # Run full pipeline with keepalive comments to prevent proxy timeouts
        yield _event("agent_start", {"agent": "ResponseFormatter", "message": "Formatting response..."})

        _pipeline_done = asyncio.Event()
        _pipeline_result: list[str] = []
        _pipeline_error: list[Exception] = []

        async def _run_pipeline() -> None:
            try:
                r = await handle_query(
                    query=english_message,
                    user_role=current_user.role,
                    crew_factory=get_crew_for_role,
                )
                _pipeline_result.append(r)
            except Exception as exc:  # noqa: BLE001
                _pipeline_error.append(exc)
            finally:
                _pipeline_done.set()

        asyncio.create_task(_run_pipeline())

        while not _pipeline_done.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(_pipeline_done.wait()), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        elapsed_ms = int((time.time() - start) * 1000)

        if _pipeline_error:
            exc = _pipeline_error[0]
            logger.error("Conversation pipeline error: %s", exc)
            yield _event("error", {"code": "PIPELINE_ERROR", "detail": str(exc)})
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        result_text = _pipeline_result[0]
        await cache.set(english_message, current_user.role, result_text, tier="full")
        session.stage = "responding"

        chunk_size = 80
        for i in range(0, len(result_text), chunk_size):
            yield _event("token", {"text": result_text[i:i + chunk_size]})

        citations = _parse_citations(result_text)
        suggestions_data = [
            {"id": s.id, "label": s.label, "icon": s.icon, "description": s.description}
            for s in role_actions
        ]
        yield _event("action_suggestions", {"suggestions": suggestions_data})
        yield _event("complete", {
            "session_id": session.session_id,
            "turn_number": session.turn_count,
            "stage": "responding",
            "intent": "full_pipeline",
            "verification_status": _parse_verification_status(result_text),
            "confidence": _parse_confidence(result_text),
            "citations": [c.model_dump() for c in citations],
            "processing_time_ms": elapsed_ms,
            "cached": False,
        })
        yield "event: end\ndata: {}\n\n"
        await db.flush()

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
# GET /conversation/session/{session_id}
# ---------------------------------------------------------------------------

@router.get("/session/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation session details."""
    result = await db.execute(
        select(ConversationSession).where(
            ConversationSession.session_id == session_id,
            ConversationSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, detail="Session not found.")

    return SessionResponse(
        session_id=session.session_id,
        user_id=str(session.user_id),
        turn_count=session.turn_count,
        status=session.status,
        stage=session.stage or "responding",
        context=session.context or {},
        intent_history=session.intent_history or [],
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )
