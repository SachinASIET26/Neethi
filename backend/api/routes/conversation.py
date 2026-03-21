"""Conversation routes — staged, conversational legal assistant pipeline.

Instead of firing the full CrewAI pipeline in one go (~2 min), the conversation
progresses through discrete stages, each producing a user-facing response:

  intake → clarifying → confirming → retrieving → responding → follow_up

Each stage responds in 2-30 seconds. The user interacts between stages via
suggestion buttons, confirmation cards, and free text.
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
    ClarifyingQuestionSchema,
    FormulatedQuerySchema,
    RetrievedSectionSchema,
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

MAX_CLARIFICATION_ROUNDS = 3


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

    new_session = ConversationSession(
        user_id=user.id,
        session_id=session_id or uuid.uuid4().hex,
        context={},
        intent_history=[],
        turn_count=0,
        status="active",
        stage="intake",
        clarification_round=0,
    )
    db.add(new_session)
    await db.flush()
    return new_session


async def _translate_if_needed(query: str, language: str) -> str:
    """Translate query to English if needed."""
    if not language or language.lower().startswith("en"):
        return query
    try:
        from backend.api.routes.query import _translate_to_english
        return await _translate_to_english(query, language)
    except Exception:
        return query


# ---------------------------------------------------------------------------
# Query Formulation (Stage 2) — single LLM call, no CrewAI
# ---------------------------------------------------------------------------

_FORMULATION_PROMPT = """\
You are a legal query formulation specialist for Indian law.

Based on the user's scenario and their clarification answers, formulate a precise
legal search query using proper Indian legal terminology.

USER SCENARIO: {scenario}
CLARIFICATION ANSWERS: {answers}
DETECTED ENTITIES: {entities}
USER ROLE: {user_role}

Output ONLY valid JSON:
{{
  "legal_query": "precise legal query with correct terminology for retrieval",
  "domain": "criminal | civil | property | family | corporate | constitutional | labour | consumer | environmental",
  "sub_domains": ["list", "of", "sub-areas"],
  "summary": "plain language summary of what the user is asking, written for the user to confirm"
}}"""


async def _formulate_query(context: dict, user_role: str) -> FormulatedQuerySchema:
    """Formulate a precise legal query from accumulated context. Single LLM call."""
    import litellm

    from backend.agents.intent_classifier import _get_litellm_model

    model_id, api_key = _get_litellm_model()

    scenario = context.get("scenario", "")
    answers = context.get("answers", {})
    entities = context.get("entities", {})

    prompt = _FORMULATION_PROMPT.format(
        scenario=scenario,
        answers=json.dumps(answers, default=str),
        entities=json.dumps(entities, default=str),
        user_role=user_role,
    )

    try:
        response = await litellm.acompletion(
            model=model_id,
            api_key=api_key,
            messages=[
                {"role": "system", "content": "You are a legal query formulation expert for Indian law. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return FormulatedQuerySchema(
            legal_query=parsed.get("legal_query", scenario),
            domain=parsed.get("domain", "civil"),
            sub_domains=parsed.get("sub_domains", []),
            summary=parsed.get("summary", scenario),
        )
    except Exception as exc:
        logger.warning("Query formulation failed, using raw scenario: %s", exc)
        return FormulatedQuerySchema(
            legal_query=scenario,
            domain="general",
            sub_domains=[],
            summary=scenario,
        )


# ---------------------------------------------------------------------------
# Turn processing — stage-based routing
# ---------------------------------------------------------------------------

async def _process_turn(
    message: str,
    action_id: str | None,
    session: ConversationSession,
    user: User,
    cache: ResponseCache,
) -> TurnResponse:
    """Process a single conversation turn using staged pipeline."""
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
    elapsed_ms = lambda: int((time.time() - start) * 1000)
    role_actions = get_actions_for_role(user.role)
    stage = session.stage or "intake"

    # ── Handle action_id clicks ──────────────────────────────────────
    if action_id:
        return await _handle_action(action_id, message, session, user, cache, start)

    # ── Run intent classifier ────────────────────────────────────────
    intent_result = await classify_intent(message, user.role, context)
    intent_label = intent_result.intent
    entities = intent_result.entities
    needs_clarification = intent_result.needs_clarification
    clarifying_questions = intent_result.clarifying_questions
    emotional_tone = intent_result.emotional_tone

    # Update session
    session.turn_count += 1
    history = list(session.intent_history or [])
    history.append(intent_label)
    session.intent_history = history

    # ── Route by intent ──────────────────────────────────────────────

    if intent_label == "greeting":
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage=stage,
            intent=intent_label,
            response=get_greeting_response(user.role),
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    if intent_label == "section_lookup":
        # Section lookups go through formulation → confirmation too
        context["scenario"] = message
        context["entities"] = entities
        session.context = context
        return await _transition_to_confirming(session, user, start)

    # ── STAGE: intake / new_scenario ─────────────────────────────────
    if intent_label in ("new_scenario", "new_question"):
        if intent_label == "new_question":
            # Reset session for new topic
            session.context = {}
            session.formulated_query = None
            session.classified_domain = None
            session.retrieved_sections_cache = None
            session.clarification_round = 0
            context = {}

        context["scenario"] = message
        context["emotional_tone"] = emotional_tone
        context["entities"] = entities
        session.context = context

        if needs_clarification and clarifying_questions:
            session.stage = "clarifying"
            response_text = format_new_scenario_response(
                user.role, clarifying_questions, emotional_tone,
            )
            # Convert questions to structured format with options
            structured_questions = _structure_clarifying_questions(clarifying_questions)
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                stage="clarifying",
                intent=intent_label,
                response=response_text,
                needs_clarification=True,
                clarifying_questions=structured_questions,
                suggestions=_suggestions_to_schema(role_actions),
                processing_time_ms=elapsed_ms(),
            )
        else:
            # Context seems complete — go to formulation
            return await _transition_to_confirming(session, user, start)

    # ── STAGE: clarifying / clarification_answer ─────────────────────
    if intent_label == "clarification_answer":
        context = merge_clarification_into_context(context, message, entities)
        session.context = context
        session.clarification_round = (session.clarification_round or 0) + 1

        if is_context_complete(context) or session.clarification_round >= MAX_CLARIFICATION_ROUNDS:
            # Enough context — formulate query and ask for confirmation
            return await _transition_to_confirming(session, user, start)
        else:
            # Still need more info
            session.stage = "clarifying"
            if clarifying_questions:
                structured_questions = _structure_clarifying_questions(clarifying_questions)
                q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(clarifying_questions))
                response_text = f"Thank you for that information. I still need a few more details:\n\n{q_text}"
            else:
                structured_questions = None
                response_text = "Thank you. Could you provide any additional details that might be relevant?"
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                stage="clarifying",
                intent=intent_label,
                response=response_text,
                needs_clarification=True,
                clarifying_questions=structured_questions,
                processing_time_ms=elapsed_ms(),
            )

    # ── Fallback ─────────────────────────────────────────────────────
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage=stage,
        intent=intent_label,
        response="I'm not sure how to help with that. Could you rephrase your legal question?",
        suggestions=_suggestions_to_schema(role_actions),
        processing_time_ms=elapsed_ms(),
    )


# ---------------------------------------------------------------------------
# Stage transition helpers
# ---------------------------------------------------------------------------

def _structure_clarifying_questions(questions: list[str]) -> list[ClarifyingQuestionSchema]:
    """Convert raw question strings into structured questions with options where possible."""
    structured = []
    for i, q in enumerate(questions):
        q_lower = q.lower()
        options = None
        # Detect yes/no questions
        if any(q_lower.startswith(w) for w in ("did ", "was ", "were ", "is ", "has ", "have ", "are ", "do ")):
            options = ["Yes", "No", "Not sure"]
        # Detect timeline questions
        elif "how long" in q_lower or "when did" in q_lower or "how many" in q_lower:
            if "month" in q_lower or "long" in q_lower:
                options = ["Less than 1 month", "1-3 months", "3-6 months", "More than 6 months"]
        structured.append(ClarifyingQuestionSchema(
            id=f"q{i}",
            text=q,
            options=options,
        ))
    return structured


async def _transition_to_confirming(
    session: ConversationSession,
    user: User,
    start: float,
) -> TurnResponse:
    """Formulate the legal query and present it for user confirmation."""
    from backend.agents.response_templates import get_actions_for_role

    context = session.context or {}
    formulated = await _formulate_query(context, user.role)

    # Store in session
    session.formulated_query = formulated.legal_query
    session.classified_domain = formulated.domain
    session.stage = "confirming"

    domain_labels = {
        "criminal": "Criminal Law",
        "civil": "Civil Law",
        "property": "Property / Tenancy",
        "family": "Family Law",
        "corporate": "Corporate / Commercial",
        "constitutional": "Constitutional Law",
        "labour": "Labour / Employment",
        "consumer": "Consumer Protection",
        "environmental": "Environmental Law",
    }
    domain_label = domain_labels.get(formulated.domain, formulated.domain.title())

    response_text = (
        f"Here's what I understand from your situation:\n\n"
        f"> {formulated.summary}\n\n"
        f"**Legal Domain:** {domain_label}\n"
    )
    if formulated.sub_domains:
        response_text += f"**Areas:** {', '.join(formulated.sub_domains)}\n"
    response_text += "\nIs this correct? I'll search for the applicable legal provisions once you confirm."

    confirm_actions = [
        ActionSuggestionSchema(id="confirm_query", label="Yes, looks correct", icon="check_circle", description="Confirm and proceed to search applicable laws"),
        ActionSuggestionSchema(id="edit_query", label="Make changes", icon="edit", description="Correct or add more details"),
    ]

    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage="confirming",
        intent="query_formulation",
        response=response_text,
        formulated_query=formulated,
        suggestions=confirm_actions,
        processing_time_ms=int((time.time() - start) * 1000),
    )


async def _transition_to_retrieving(
    session: ConversationSession,
    user: User,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    """Run direct retrieval + citation verification (NO CrewAI overhead).

    Calls QdrantHybridSearchTool and CitationVerificationTool directly,
    then formats with a single LLM call. Each step takes 2-10 seconds.
    """
    query = session.formulated_query or _build_combined_query(session.context or {})
    domain = session.classified_domain or "general"
    session.stage = "retrieving"

    # Check cache first
    cached_resp = await cache.get(query, user.role)
    if cached_resp:
        from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status
        citations = _parse_citations(cached_resp)
        sections = _citations_to_sections(citations, cached_resp)
        session.retrieved_sections_cache = {
            "response_text": cached_resp,
            "citations": [c.model_dump() for c in citations],
        }
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="retrieving",
            intent="retrieval",
            response="I found these applicable legal provisions:",
            retrieved_sections=sections,
            verification_status=_parse_verification_status(cached_resp),
            confidence=_parse_confidence(cached_resp),
            citations=citations,
            suggestions=_retrieval_suggestions(),
            processing_time_ms=int((time.time() - start) * 1000),
            cached=True,
        )

    # ── Step 1: Direct Qdrant search (no CrewAI) ──────────────────────
    try:
        search_results, sections, citations = await _direct_retrieve_and_verify(
            query, domain, user.role,
        )
    except Exception as exc:
        logger.error("Direct retrieval failed: %s", exc)
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="retrieving",
            intent="retrieval",
            response=f"I encountered an error searching for applicable laws. Please try again.",
            processing_time_ms=int((time.time() - start) * 1000),
        )

    # ── Step 2: Format response via single LLM call ──────────────────
    try:
        response_text = await _format_response_llm(query, search_results, user.role, domain)
    except Exception as exc:
        logger.warning("Response formatting failed, using raw results: %s", exc)
        response_text = search_results

    # Cache result
    await cache.set(query, user.role, response_text, tier="full")

    # Cache in session for followup actions
    session.retrieved_sections_cache = {
        "response_text": response_text,
        "citations": [c.model_dump() for c in citations],
    }

    verification_status = "VERIFIED" if any(
        c.verification == "VERIFIED" for c in citations
    ) else "PARTIALLY_VERIFIED"
    confidence = "high" if len([c for c in citations if c.verification == "VERIFIED"]) >= 2 else "medium"

    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage="responding",
        intent="retrieval",
        response=response_text,
        retrieved_sections=sections,
        verification_status=verification_status,
        confidence=confidence,
        citations=citations,
        suggestions=_retrieval_suggestions(),
        processing_time_ms=int((time.time() - start) * 1000),
        cached=False,
    )


def _retrieval_suggestions() -> list[ActionSuggestionSchema]:
    return [
        ActionSuggestionSchema(id="precedent_search", label="Similar case judgments", icon="search", description="Search for relevant Supreme Court precedents"),
        ActionSuggestionSchema(id="find_lawyer", label="Connect with legal resources", icon="person_search", description="Find nearby lawyers and legal aid"),
    ]


async def _direct_retrieve_and_verify(
    query: str, domain: str, user_role: str,
) -> tuple[str, list[RetrievedSectionSchema], list[CitationResult]]:
    """Run Qdrant search + citation verification using direct tool calls.

    Returns (raw_search_text, sections, citations).
    Typical latency: 3-8 seconds.
    """
    loop = asyncio.get_event_loop()

    # Determine filters from domain
    domain_to_act = {
        "criminal": "BNS_2023",
        "criminal_procedural": "BNSS_2023",
    }
    domain_to_era = {
        "criminal": "naveen_sanhitas",
        "criminal_procedural": "naveen_sanhitas",
    }
    domain_to_qtype = {
        "criminal": "criminal_offence",
        "criminal_procedural": "procedural",
        "civil": "civil_conceptual",
        "property": "civil_conceptual",
        "family": "civil_conceptual",
        "corporate": "civil_conceptual",
        "labour": "civil_conceptual",
        "consumer": "civil_conceptual",
    }
    act_filter = domain_to_act.get(domain, "none")
    era_filter = domain_to_era.get(domain, "none")
    query_type = domain_to_qtype.get(domain, "default")

    # ── Qdrant hybrid search (sync tool, run in executor) ─────────
    from backend.agents.tools.qdrant_search_tool import QdrantHybridSearchTool
    search_tool = QdrantHybridSearchTool()
    search_results = await loop.run_in_executor(
        None,
        lambda: search_tool._run(
            query=query,
            act_filter=act_filter,
            era_filter=era_filter,
            top_k=5,
            rerank=True,
            collection="legal_sections",
            query_type=query_type,
        ),
    )

    # ── Parse and verify each retrieved section ───────────────────
    from backend.agents.tools.citation_verification_tool import CitationVerificationTool
    verify_tool = CitationVerificationTool()

    import re
    # Extract (act_code, section_number) pairs from search results
    section_pattern = re.compile(
        r"\[?\d+\]?\s*(\w+_\d{4})\s+s\.(\d{1,4}[A-Za-z]?)\s*[—–-]",
    )
    found_pairs = section_pattern.findall(search_results)

    sections: list[RetrievedSectionSchema] = []
    citations: list[CitationResult] = []

    for act_code, sec_num in found_pairs:
        verify_result = await loop.run_in_executor(
            None,
            lambda ac=act_code, sn=sec_num: verify_tool._run(act_code=ac, section_number=sn),
        )
        is_verified = "VERIFIED" in verify_result and "NOT_VERIFIED" not in verify_result

        # Extract section title from verification result
        title_match = re.search(r"[—–-]\s*(.+?)(?:\n|$)", verify_result)
        section_title = title_match.group(1).strip() if title_match else ""

        status = "VERIFIED" if is_verified else "NOT_FOUND"

        sections.append(RetrievedSectionSchema(
            act_code=act_code,
            section_number=sec_num,
            section_title=section_title,
            reason_applicable=f"Retrieved for: {query[:80]}",
            verification_status=status,
            relevance="RELEVANT",
        ))
        citations.append(CitationResult(
            act_code=act_code,
            section_number=sec_num,
            section_title=section_title,
            verification=status,
        ))

    return search_results, sections, citations


# ---------------------------------------------------------------------------
# Response formatting — single LLM call (no CrewAI)
# ---------------------------------------------------------------------------

_RESPONSE_FORMAT_PROMPT = """\
You are a legal response formatter for Neethi AI, an Indian legal assistance system.

Format the retrieved legal information into a clear, user-friendly response.

USER QUERY: {query}
USER ROLE: {user_role}
LEGAL DOMAIN: {domain}
RETRIEVED LEGAL SECTIONS:
{search_results}

FORMATTING RULES:
- For citizen: Use simple language (8th grade reading level). Lead with a direct answer.
  Number key points. Include "What this means for you" and "What to do next" sections.
- For lawyer: Use precise legal terminology. Include IRAC structure if appropriate.
- For police: Focus on procedural steps and compliance requirements.
- For legal_advisor: Focus on compliance and risk assessment.

CITATION RULES:
- Only cite sections that appear in the retrieved results above
- NEVER fabricate section numbers not in the search results
- Mark the primary applicable section clearly
- List related/contextual sections separately

Always end with: "This is AI-assisted legal information. Consult a qualified legal professional for advice specific to your situation."

Include verification status: ✅ VERIFIED if sections were found in the database."""


async def _format_response_llm(
    query: str, search_results: str, user_role: str, domain: str,
) -> str:
    """Format retrieved results into a user-friendly response via single LLM call.

    Typical latency: 3-8 seconds.
    """
    import litellm
    from backend.agents.intent_classifier import _get_litellm_model

    model_id, api_key = _get_litellm_model()

    prompt = _RESPONSE_FORMAT_PROMPT.format(
        query=query,
        user_role=user_role,
        domain=domain,
        search_results=search_results[:4000],  # Limit context
    )

    response = await litellm.acompletion(
        model=model_id,
        api_key=api_key,
        messages=[
            {"role": "system", "content": "You are a legal response formatter. Produce clear, accurate, well-structured legal information."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
    )

    return response.choices[0].message.content.strip()


def _citations_to_sections(citations: list[CitationResult], response_text: str) -> list[RetrievedSectionSchema]:
    """Convert citation results into retrieved section schemas with reason extraction."""
    sections = []
    for c in citations:
        if c.verification in ("VERIFIED", "VERIFIED_INCOMPLETE"):
            sections.append(RetrievedSectionSchema(
                act_code=c.act_code,
                section_number=c.section_number,
                section_title=c.section_title or "",
                reason_applicable=f"Applicable to your situation under {c.act_code.replace('_', ' ')}",
                verification_status=c.verification,
                relevance="RELEVANT",
            ))
    return sections


# ---------------------------------------------------------------------------
# Action handling
# ---------------------------------------------------------------------------

async def _handle_action(
    action_id: str,
    message: str,
    session: ConversationSession,
    user: User,
    cache: ResponseCache,
    start: float,
) -> TurnResponse:
    """Handle suggestion button clicks based on current stage."""
    from backend.agents.response_templates import get_actions_for_role

    role_actions = get_actions_for_role(user.role)
    elapsed_ms = lambda: int((time.time() - start) * 1000)

    # ── Confirmation actions ─────────────────────────────────────────
    if action_id == "confirm_query":
        # User confirmed the formulated query → proceed to retrieval
        session.turn_count += 1
        return await _transition_to_retrieving(session, user, cache, start)

    if action_id == "edit_query":
        # User wants to correct → go back to clarifying
        session.stage = "clarifying"
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="clarifying",
            intent="edit_query",
            response="What would you like to change or add? You can describe your situation again or provide additional details.",
            suggestions=[
                ActionSuggestionSchema(id="restart", label="Start over", icon="refresh", description="Describe your situation from the beginning"),
            ],
            processing_time_ms=elapsed_ms(),
        )

    if action_id == "restart":
        # Reset session
        session.stage = "intake"
        session.context = {}
        session.formulated_query = None
        session.classified_domain = None
        session.retrieved_sections_cache = None
        session.clarification_round = 0
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="intake",
            intent="restart",
            response="Let's start fresh. Please describe your legal situation or question.",
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    # ── Post-retrieval actions ───────────────────────────────────────
    if action_id == "detailed_analysis":
        session.turn_count += 1
        session.stage = "responding"
        # Use cached response if available
        cached_data = session.retrieved_sections_cache
        if cached_data and cached_data.get("response_text"):
            from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status
            response_text = cached_data["response_text"]
            citations = _parse_citations(response_text)
            return TurnResponse(
                session_id=session.session_id,
                turn_number=session.turn_count,
                stage="responding",
                intent="detailed_analysis",
                response=response_text,
                verification_status=_parse_verification_status(response_text),
                confidence=_parse_confidence(response_text),
                citations=citations,
                suggestions=_suggestions_to_schema(role_actions),
                processing_time_ms=elapsed_ms(),
            )
        # Fallback: re-run pipeline
        return await _fire_full_pipeline(
            session.formulated_query or _build_combined_query(session.context or {}),
            user, session, cache, start,
        )

    # ── Crew-based actions ───────────────────────────────────────────
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

    # ── Document drafting actions ────────────────────────────────────
    draft_actions = {"draft_complaint", "fir_template", "draft_notice"}
    if action_id in draft_actions:
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="follow_up",
            intent="followup_action",
            response=(
                "To draft this document, I'll need a few details. "
                "Please go to the **Documents** section where you can fill in the required fields "
                "and I'll generate a complete draft for you.\n\n"
                "Alternatively, describe what you need and I'll help you prepare the information."
            ),
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    # ── Find lawyer ──────────────────────────────────────────────────
    if action_id == "find_lawyer":
        session.turn_count += 1
        return TurnResponse(
            session_id=session.session_id,
            turn_number=session.turn_count,
            stage="follow_up",
            intent="followup_action",
            response=(
                "To find a lawyer near you, please visit the **Legal Resources** section "
                "where you can search by location and specialization.\n\n"
                "You can also call the free legal aid helpline: **15100** (NALSA)."
            ),
            suggestions=_suggestions_to_schema(role_actions),
            processing_time_ms=elapsed_ms(),
        )

    # ── Unknown action ───────────────────────────────────────────────
    session.turn_count += 1
    return TurnResponse(
        session_id=session.session_id,
        turn_number=session.turn_count,
        stage=session.stage or "intake",
        intent="followup_action",
        response="I'm not sure how to handle that action. Could you describe what you need?",
        suggestions=_suggestions_to_schema(role_actions),
        processing_time_ms=elapsed_ms(),
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
            response=f"I encountered an error processing your query. Please try again. (Error: {exc})",
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
    """Submit a conversation turn and receive a response."""
    await check_rate_limit(current_user, db)

    session = await _get_or_create_session(request.session_id, current_user, db)
    english_message = await _translate_if_needed(request.message, request.language)

    result = await _process_turn(
        message=english_message,
        action_id=request.action_id,
        session=session,
        user=current_user,
        cache=cache,
    )

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
        stage = session.stage or "intake"

        # ── Handle action_id clicks ──────────────────────────────────
        if request.action_id:
            result = await _handle_action(
                request.action_id, english_message, session, current_user, cache, start,
            )
            yield _event("intent", {"intent": result.intent, "confidence": 1.0})

            # Emit stage info
            yield _event("stage", {"stage": result.stage})

            # Stream response
            chunk_size = 80
            for i in range(0, len(result.response), chunk_size):
                yield _event("token", {"text": result.response[i:i + chunk_size]})

            # Emit structured data
            if result.clarifying_questions:
                yield _event("clarification", {
                    "questions": [q.model_dump() for q in result.clarifying_questions],
                })
            if result.formulated_query:
                yield _event("formulated_query", result.formulated_query.model_dump())
            if result.retrieved_sections:
                yield _event("retrieved_sections", {
                    "sections": [s.model_dump() for s in result.retrieved_sections],
                })

            suggestions_data = [s.model_dump() for s in result.suggestions]
            if suggestions_data:
                yield _event("action_suggestions", {"suggestions": suggestions_data})

            yield _event("complete", {
                "session_id": session.session_id,
                "turn_number": result.turn_number,
                "stage": result.stage,
                "intent": result.intent,
                "needs_clarification": result.needs_clarification,
                "verification_status": result.verification_status,
                "confidence": result.confidence,
                "citations": [c.model_dump() for c in result.citations] if result.citations else [],
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": result.cached,
            })
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        # ── Normal message processing ────────────────────────────────
        intent_result = await classify_intent(english_message, current_user.role, context)
        intent_label = intent_result.intent
        entities = intent_result.entities
        needs_clarification = intent_result.needs_clarification
        clarifying_questions = intent_result.clarifying_questions
        emotional_tone = intent_result.emotional_tone
        conf = intent_result.confidence

        yield _event("intent", {"intent": intent_label, "confidence": conf})

        session.turn_count += 1
        history = list(session.intent_history or [])
        history.append(intent_label)
        session.intent_history = history

        # ── Fast paths (no pipeline) ─────────────────────────────────
        needs_pipeline = False
        response_text = ""
        stage_result = stage
        result_clarifying_questions = None
        result_formulated_query = None
        result_retrieved_sections = None

        if intent_label == "greeting":
            response_text = get_greeting_response(current_user.role)

        elif intent_label == "new_scenario" or intent_label == "new_question":
            if intent_label == "new_question":
                session.context = {}
                session.formulated_query = None
                session.classified_domain = None
                session.retrieved_sections_cache = None
                session.clarification_round = 0
                context = {}

            context["scenario"] = english_message
            context["emotional_tone"] = emotional_tone
            context["entities"] = entities
            session.context = context

            if needs_clarification and clarifying_questions:
                session.stage = "clarifying"
                stage_result = "clarifying"
                response_text = format_new_scenario_response(
                    current_user.role, clarifying_questions, emotional_tone,
                )
                result_clarifying_questions = _structure_clarifying_questions(clarifying_questions)
                yield _event("clarification", {
                    "questions": [q.model_dump() for q in result_clarifying_questions],
                })
                yield _event("stage", {"stage": "clarifying"})
            else:
                # Go to formulation
                formulated = await _formulate_query(context, current_user.role)
                session.formulated_query = formulated.legal_query
                session.classified_domain = formulated.domain
                session.stage = "confirming"
                stage_result = "confirming"
                result_formulated_query = formulated

                domain_labels = {
                    "criminal": "Criminal Law", "civil": "Civil Law",
                    "property": "Property / Tenancy", "family": "Family Law",
                    "corporate": "Corporate / Commercial", "constitutional": "Constitutional Law",
                    "labour": "Labour / Employment", "consumer": "Consumer Protection",
                }
                domain_label = domain_labels.get(formulated.domain, formulated.domain.title())
                response_text = (
                    f"Here's what I understand from your situation:\n\n"
                    f"> {formulated.summary}\n\n"
                    f"**Legal Domain:** {domain_label}\n"
                )
                if formulated.sub_domains:
                    response_text += f"**Areas:** {', '.join(formulated.sub_domains)}\n"
                response_text += "\nIs this correct? I'll search for the applicable legal provisions once you confirm."

                yield _event("formulated_query", formulated.model_dump())
                yield _event("stage", {"stage": "confirming"})

        elif intent_label == "clarification_answer":
            context = merge_clarification_into_context(context, english_message, entities)
            session.context = context
            session.clarification_round = (session.clarification_round or 0) + 1

            if is_context_complete(context) or session.clarification_round >= MAX_CLARIFICATION_ROUNDS:
                # Formulate query
                formulated = await _formulate_query(context, current_user.role)
                session.formulated_query = formulated.legal_query
                session.classified_domain = formulated.domain
                session.stage = "confirming"
                stage_result = "confirming"
                result_formulated_query = formulated

                domain_labels = {
                    "criminal": "Criminal Law", "civil": "Civil Law",
                    "property": "Property / Tenancy", "family": "Family Law",
                    "corporate": "Corporate / Commercial", "constitutional": "Constitutional Law",
                    "labour": "Labour / Employment", "consumer": "Consumer Protection",
                }
                domain_label = domain_labels.get(formulated.domain, formulated.domain.title())
                response_text = (
                    f"Here's what I understand from your situation:\n\n"
                    f"> {formulated.summary}\n\n"
                    f"**Legal Domain:** {domain_label}\n"
                )
                if formulated.sub_domains:
                    response_text += f"**Areas:** {', '.join(formulated.sub_domains)}\n"
                response_text += "\nIs this correct? I'll search for the applicable legal provisions once you confirm."

                yield _event("formulated_query", formulated.model_dump())
                yield _event("stage", {"stage": "confirming"})
            else:
                session.stage = "clarifying"
                stage_result = "clarifying"
                if clarifying_questions:
                    result_clarifying_questions = _structure_clarifying_questions(clarifying_questions)
                    yield _event("clarification", {
                        "questions": [q.model_dump() for q in result_clarifying_questions],
                    })
                    q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(clarifying_questions))
                    response_text = f"Thank you. I still need a few more details:\n\n{q_text}"
                else:
                    response_text = "Thank you. Could you provide any additional details?"

        elif intent_label == "section_lookup":
            # Section lookups also go through formulation → confirmation
            context["scenario"] = english_message
            context["entities"] = entities
            session.context = context

            formulated = await _formulate_query(context, current_user.role)
            session.formulated_query = formulated.legal_query
            session.classified_domain = formulated.domain
            session.stage = "confirming"
            stage_result = "confirming"
            result_formulated_query = formulated

            domain_labels = {
                "criminal": "Criminal Law", "civil": "Civil Law",
                "property": "Property / Tenancy", "family": "Family Law",
                "corporate": "Corporate / Commercial", "constitutional": "Constitutional Law",
                "labour": "Labour / Employment", "consumer": "Consumer Protection",
            }
            domain_label = domain_labels.get(formulated.domain, formulated.domain.title())
            response_text = (
                f"Here's what I understand from your question:\n\n"
                f"> {formulated.summary}\n\n"
                f"**Legal Domain:** {domain_label}\n"
            )
            if formulated.sub_domains:
                response_text += f"**Areas:** {', '.join(formulated.sub_domains)}\n"
            response_text += "\nIs this correct? I'll search for the applicable legal provisions once you confirm."

            yield _event("formulated_query", formulated.model_dump())
            yield _event("stage", {"stage": "confirming"})

        else:
            response_text = "I'm not sure how to help with that. Could you rephrase?"

        # ── Fast response (no pipeline) ──────────────────────────────
        if not needs_pipeline and response_text:
            chunk_size = 80
            for i in range(0, len(response_text), chunk_size):
                yield _event("token", {"text": response_text[i:i + chunk_size]})

            # Determine suggestions based on stage
            if stage_result == "confirming":
                suggestions_data = [
                    {"id": "confirm_query", "label": "Yes, looks correct", "icon": "check_circle", "description": "Confirm and proceed"},
                    {"id": "edit_query", "label": "Make changes", "icon": "edit", "description": "Correct or add more details"},
                ]
            else:
                suggestions_data = [
                    {"id": s.id, "label": s.label, "icon": s.icon, "description": s.description}
                    for s in role_actions
                ]
            yield _event("action_suggestions", {"suggestions": suggestions_data})

            yield _event("complete", {
                "session_id": session.session_id,
                "turn_number": session.turn_count,
                "stage": stage_result,
                "intent": intent_label,
                "needs_clarification": needs_clarification and stage_result == "clarifying",
                "processing_time_ms": int((time.time() - start) * 1000),
                "cached": False,
            })
            yield "event: end\ndata: {}\n\n"
            await db.flush()
            return

        # ── Pipeline path (section lookup or full pipeline) ──────────
        if intent_label == "section_lookup":
            pipeline_query = english_message
        else:
            pipeline_query = english_message

        # Emit agent progress
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
        stage=session.stage or "intake",
        context=session.context or {},
        intent_history=session.intent_history or [],
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )
