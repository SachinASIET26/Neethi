"""Conversation routes — stateful multi-turn legal assistant.

Provides a conversational loop where most turns respond in <10 seconds,
and heavy agents only fire when context is complete.
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
from backend.api.schemas.query import CitationResult
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
    """Convert ActionSuggestion dataclass instances to Pydantic schema."""
    return [
        ActionSuggestionSchema(id=s.id, label=s.label, icon=s.icon, description=s.description)
        for s in suggestions
    ]


async def _get_or_create_session(
    session_id: str | None,
    user: User,
    db: AsyncSession,
) -> ConversationSession:
    """Load an existing session or create a new one."""
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

    # Create new session
    new_session = ConversationSession(
        user_id=user.id,
        session_id=session_id or uuid.uuid4().hex,
        context={},
        intent_history=[],
        turn_count=0,
        status="active",
    )
    db.add(new_session)
    await db.flush()
    return new_session


async def _translate_if_needed(query: str, language: str) -> str:
    """Translate query to English if needed (reuses query route helper)."""
    if not language or language.lower().startswith("en"):
        return query
    try:
        from backend.api.routes.query import _translate_to_english
        return await _translate_to_english(query, language)
    except Exception:
        return query


# ---------------------------------------------------------------------------
# Turn processing core
# ---------------------------------------------------------------------------

async def _process_turn(
    message: str,
    action_id: str | None,
    session: ConversationSession,
    user: User,
    cache: ResponseCache,
) -> TurnResponse:
    """Process a single conversation turn and return the response."""
    from backend.agents.intent_classifier import classify_intent
    from backend.agents.response_templates import (
        format_new_scenario_response,
        get_actions_for_role,
        get_greeting_response,
        is_context_complete,
        merge_clarification_into_context,
    )

    start = time.time()
    context = session.context or {}

    # If action_id is provided, treat as followup_action
    if action_id:
        intent_label = "followup_action"
        entities = {}
        needs_clarification = False
        clarifying_questions: list[str] = []
        emotional_tone = "neutral"
        suggested_actions: list[str] = []
        confidence = 0.9
    else:
        # Run intent classifier
        intent_result = await classify_intent(message, user.role, context)
        intent_label = intent_result.intent
        entities = intent_result.entities
        needs_clarification = intent_result.needs_clarification
        clarifying_questions = intent_result.clarifying_questions
        emotional_tone = intent_result.emotional_tone
        suggested_actions = intent_result.suggested_actions
        confidence = intent_result.confidence

    # Update session
    session.turn_count += 1
    history = list(session.intent_history or [])
    history.append(intent_label)
    session.intent_history = history

    elapsed_ms = lambda: int((time.time() - start) * 1000)
    role_actions = get_actions_for_role(user.role)

    # ── Route by intent ──────────────────────────────────────────────

    if intent_label == "greeting":
        response_text = get_greeting_response(user.role)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            intent=intent_label,
            response=response_text,
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    if intent_label == "section_lookup":
        # Delegate to Tier 1 resolver
        response_text = await _handle_section_lookup(message, user.role, cache)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            intent=intent_label,
            response=response_text,
            suggestions=_suggestions_to_schema(role_actions[:2]),
            processing_time_ms=elapsed_ms(),
        )

    if intent_label == "new_scenario":
        # Store scenario in context
        context["scenario"] = message
        context["emotional_tone"] = emotional_tone
        context["entities"] = entities
        session.context = context

        if needs_clarification and clarifying_questions:
            response_text = format_new_scenario_response(
                user.role, clarifying_questions, emotional_tone,
            )
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                intent=intent_label,
                response=response_text,
                needs_clarification=True,
                suggestions=_suggestions_to_schema(role_actions),
                processing_time_ms=elapsed_ms(),
            )
        else:
            # Context seems complete already — fire pipeline
            return await _fire_full_pipeline(message, user, session, cache, start)

    if intent_label == "clarification_answer":
        context = merge_clarification_into_context(context, message, entities)
        session.context = context

        if is_context_complete(context):
            # Build combined query from context
            combined_query = _build_combined_query(context)
            return await _fire_full_pipeline(combined_query, user, session, cache, start)
        else:
            # Still incomplete — ask more
            if clarifying_questions:
                q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(clarifying_questions))
                response_text = f"Thank you for that information. I still need a few more details:\n\n{q_text}"
            else:
                response_text = "Thank you. Could you provide any additional details that might be relevant?"
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                intent=intent_label,
                response=response_text,
                needs_clarification=True,
                processing_time_ms=elapsed_ms(),
            )

    if intent_label == "followup_action":
        return await _handle_followup_action(
            action_id or "", message, user, session, cache, start,
        )

    if intent_label == "new_question":
        # Reset context, treat as new scenario
        session.context = {}
        context = {}
        context["scenario"] = message
        context["entities"] = entities
        session.context = context

        if needs_clarification and clarifying_questions:
            response_text = format_new_scenario_response(
                user.role, clarifying_questions, emotional_tone,
            )
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                intent=intent_label,
                response=response_text,
                needs_clarification=True,
                suggestions=_suggestions_to_schema(role_actions),
                processing_time_ms=elapsed_ms(),
            )
        else:
            return await _fire_full_pipeline(message, user, session, cache, start)

    # Fallback
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        intent=intent_label,
        response="I'm not sure how to help with that. Could you rephrase your legal question?",
        suggestions=_suggestions_to_schema(role_actions),
        processing_time_ms=elapsed_ms(),
    )


def _build_combined_query(context: dict) -> str:
    """Build a comprehensive query from accumulated session context."""
    parts = []
    if context.get("scenario"):
        parts.append(context["scenario"])
    answers = context.get("answers", {})
    if answers:
        parts.append("Additional details: " + " ".join(answers.values()))
    entities = context.get("entities", {})
    if entities:
        entity_str = ", ".join(f"{k}: {v}" for k, v in entities.items() if v)
        if entity_str:
            parts.append(f"Relevant entities: {entity_str}")
    return " ".join(parts)


async def _handle_section_lookup(
    message: str,
    user_role: str,
    cache: ResponseCache,
) -> str:
    """Handle direct section lookup via Tier 1 resolver."""
    try:
        from backend.agents.query_router import handle_query
        from backend.agents.crew_config import get_crew_for_role
        return await handle_query(
            query=message,
            user_role=user_role,
            crew_factory=get_crew_for_role,
        )
    except Exception as exc:
        logger.error("Section lookup failed: %s", exc)
        return f"I couldn't look up that section right now. Please try again. (Error: {exc})"


async def _handle_followup_action(
    action_id: str,
    message: str,
    user: User,
    session: ConversationSession,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    """Route a followup action to the appropriate handler."""
    from backend.agents.response_templates import get_actions_for_role

    context = session.context or {}
    scenario = context.get("scenario", message or "")
    role_actions = get_actions_for_role(user.role)
    elapsed_ms = lambda: int((time.time() - start) * 1000)

    # Actions that trigger full crew pipeline
    crew_actions = {
        "step_by_step", "legal_sections", "irac_analysis",
        "section_deep_dive", "precedent_search", "counter_arguments",
        "sop_reference", "bnss_procedure", "arrest_checklist",
        "compliance_checklist", "risk_assessment", "case_strategy",
    }

    if action_id in crew_actions:
        # Prefix the query with the action context for better results
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

    # Document drafting actions
    draft_actions = {"draft_complaint", "fir_template", "draft_notice"}
    if action_id in draft_actions:
        response_text = (
            "To draft this document, I'll need a few details. "
            "Please go to the **Documents** section where you can fill in the required fields "
            "and I'll generate a complete draft for you.\n\n"
            "Alternatively, describe what you need and I'll help you prepare the information."
        )
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            intent="followup_action",
            response=response_text,
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    # Find lawyer action
    if action_id == "find_lawyer":
        response_text = (
            "To find a lawyer near you, please visit the **Legal Resources** section "
            "where you can search by location and specialization.\n\n"
            "You can also call the free legal aid helpline: **15100** (NALSA)."
        )
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            intent="followup_action",
            response=response_text,
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    # Unknown action
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        intent="followup_action",
        response="I'm not sure how to handle that action. Could you describe what you need?",
        suggestions=_suggestions_to_schema(role_actions),
        processing_time_ms=elapsed_ms(),
    )


async def _fire_full_pipeline(
    query: str,
    user: User,
    session: ConversationSession,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    """Execute the full CrewAI pipeline and return a TurnResponse."""
    from backend.agents.crew_config import get_crew_for_role
    from backend.agents.query_router import handle_query
    from backend.agents.response_templates import get_actions_for_role
    from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status

    # Check cache
    cached = await cache.get(query, user.role)
    if cached:
        citations = _parse_citations(cached)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
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
            intent="full_pipeline",
            response=f"I encountered an error processing your query. Please try again. (Error: {exc})",
            processing_time_ms=int((time.time() - start) * 1000),
        )

    elapsed_ms = int((time.time() - start) * 1000)

    # Cache result
    await cache.set(query, user.role, response_text, tier="full")

    citations = _parse_citations(response_text)
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
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
    """Submit a conversation turn and receive a response."""
    await check_rate_limit(current_user, db)

    session = await _get_or_create_session(request.session_id, current_user, db)

    # Translate if needed
    english_message = await _translate_if_needed(request.message, request.language)

    result = await _process_turn(
        message=english_message,
        action_id=request.action_id,
        session=session,
        user=current_user,
        cache=cache,
    )

    # Persist session changes
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
    """Stream a conversation turn response using Server-Sent Events."""
    await check_rate_limit(current_user, db)

    session = await _get_or_create_session(request.session_id, current_user, db)
    english_message = await _translate_if_needed(request.message, request.language)

    async def _event_generator() -> AsyncIterator[str]:
        from backend.agents.intent_classifier import classify_intent
        from backend.agents.response_templates import (
            format_new_scenario_response,
            get_actions_for_role,
            get_greeting_response,
            is_context_complete,
            merge_clarification_into_context,
        )
        from backend.agents.crew_config import get_crew_for_role
        from backend.agents.query_router import handle_query
        from backend.api.routes.query import (
            _parse_citations,
            _parse_confidence,
            _parse_verification_status,
        )

        start = time.time()
        context = session.context or {}
        role_actions = get_actions_for_role(current_user.role)

        # Determine intent
        if request.action_id:
            intent_label = "followup_action"
            entities = {}
            needs_clarification = False
            clarifying_questions: list[str] = []
            emotional_tone = "neutral"
            conf = 0.9
        else:
            intent_result = await classify_intent(english_message, current_user.role, context)
            intent_label = intent_result.intent
            entities = intent_result.entities
            needs_clarification = intent_result.needs_clarification
            clarifying_questions = intent_result.clarifying_questions
            emotional_tone = intent_result.emotional_tone
            conf = intent_result.confidence

        # Emit intent event
        yield _event("intent", {"intent": intent_label, "confidence": conf})

        session.turn_count += 1
        history = list(session.intent_history or [])
        history.append(intent_label)
        session.intent_history = history

        # ── Fast paths (no pipeline) ──────────────────────────────

        # Check if this is a fast path (no full pipeline needed)
        needs_pipeline = False
        response_text = ""

        if intent_label == "greeting":
            response_text = get_greeting_response(current_user.role)

        elif intent_label == "new_scenario":
            context["scenario"] = english_message
            context["emotional_tone"] = emotional_tone
            context["entities"] = entities
            session.context = context

            if needs_clarification and clarifying_questions:
                response_text = format_new_scenario_response(
                    current_user.role, clarifying_questions, emotional_tone,
                )
                yield _event("clarification", {"questions": clarifying_questions})
            else:
                needs_pipeline = True

        elif intent_label == "clarification_answer":
            context = merge_clarification_into_context(context, english_message, entities)
            session.context = context

            if is_context_complete(context):
                needs_pipeline = True
            else:
                if clarifying_questions:
                    yield _event("clarification", {"questions": clarifying_questions})
                    q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(clarifying_questions))
                    response_text = f"Thank you. I still need a few more details:\n\n{q_text}"
                else:
                    response_text = "Thank you. Could you provide any additional details?"

        elif intent_label == "section_lookup":
            needs_pipeline = True

        elif intent_label == "followup_action":
            # Check if action requires pipeline
            crew_actions = {
                "step_by_step", "legal_sections", "irac_analysis",
                "section_deep_dive", "precedent_search", "counter_arguments",
                "sop_reference", "bnss_procedure", "arrest_checklist",
                "compliance_checklist", "risk_assessment", "case_strategy",
            }
            if request.action_id in crew_actions:
                needs_pipeline = True
            else:
                result = await _handle_followup_action(
                    request.action_id or "", english_message, current_user,
                    session, cache, start,
                )
                response_text = result.response

        elif intent_label == "new_question":
            session.context = {"scenario": english_message, "entities": entities}
            if needs_clarification and clarifying_questions:
                response_text = format_new_scenario_response(
                    current_user.role, clarifying_questions, emotional_tone,
                )
                yield _event("clarification", {"questions": clarifying_questions})
            else:
                needs_pipeline = True

        else:
            response_text = "I'm not sure how to help with that. Could you rephrase?"

        # ── Fast response (no pipeline) ───────────────────────────
        if not needs_pipeline and response_text:
            # Stream the response text
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
                "intent": intent_label,
                "needs_clarification": needs_clarification,
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": False,
            })
            yield "event: end\ndata: {}\n\n"

            await db.flush()
            return

        # ── Full pipeline path ────────────────────────────────────
        # Build query for pipeline
        if intent_label == "clarification_answer":
            pipeline_query = _build_combined_query(session.context or {})
        elif intent_label == "followup_action" and request.action_id:
            scenario = (session.context or {}).get("scenario", english_message)
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
            pipeline_query = action_prefix.get(request.action_id, "") + scenario
        else:
            pipeline_query = english_message

        # Emit agent progress events
        pipeline_agents = {
            "citizen": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
            "lawyer": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "legal_advisor": ["QueryAnalyst", "RetrievalSpecialist", "LegalReasoner", "CitationChecker", "ResponseFormatter"],
            "police": ["QueryAnalyst", "RetrievalSpecialist", "CitationChecker", "ResponseFormatter"],
        }
        agents = pipeline_agents.get(current_user.role, pipeline_agents["citizen"])

        for agent in agents[:-1]:
            yield _event("agent_start", {"agent": agent, "message": f"{agent} is working..."})

        # Check cache
        cached_resp = await cache.get(pipeline_query, current_user.role)
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

        # Run full pipeline with keepalive
        yield _event("agent_start", {"agent": "ResponseFormatter", "message": "Formatting response..."})

        _pipeline_done = asyncio.Event()
        _pipeline_result: list[str] = []
        _pipeline_error: list[Exception] = []

        async def _run_pipeline() -> None:
            try:
                r = await handle_query(
                    query=pipeline_query,
                    user_role=current_user.role,
                    crew_factory=get_crew_for_role,
                )
                _pipeline_result.append(r)
            except Exception as exc:
                _pipeline_error.append(exc)
            finally:
                _pipeline_done.set()

        asyncio.create_task(_run_pipeline())

        while not _pipeline_done.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(_pipeline_done.wait()),
                    timeout=15,
                )
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
        await cache.set(pipeline_query, current_user.role, result_text, tier="full")

        # Stream result
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
        context=session.context or {},
        intent_history=session.intent_history or [],
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )
