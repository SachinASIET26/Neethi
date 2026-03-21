"""Fast intent classifier for conversational turns.

A single LLM call (via litellm.acompletion directly — no CrewAI overhead)
that classifies the user turn into one of the defined intents.

Typical latency: 1-2 seconds.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class IntentResult(BaseModel):
    intent: str = Field(
        ...,
        description="One of: new_scenario, clarification_answer, followup_action, new_question, greeting, section_lookup",
    )
    entities: dict = Field(default_factory=dict, description="Extracted legal entities (act, section, parties, etc.)")
    needs_clarification: bool = Field(False, description="Whether the agent needs more info from the user")
    clarifying_questions: list[str] = Field(default_factory=list, description="Questions to ask the user")
    emotional_tone: str = Field("neutral", description="Detected tone: distressed, urgent, neutral, formal")
    suggested_actions: list[str] = Field(default_factory=list, description="Action IDs to suggest")
    confidence: float = Field(0.0, description="Classification confidence 0-1")


# ---------------------------------------------------------------------------
# LLM config (reuses the same Mistral → Groq → DeepSeek fallback chain)
# ---------------------------------------------------------------------------

def _get_litellm_model() -> tuple[str, str]:
    """Return (model_id, api_key) for the first configured provider."""
    mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if mistral_key:
        return "mistral/mistral-large-latest", mistral_key

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return "groq/llama-3.3-70b-versatile", groq_key

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        return "deepseek/deepseek-chat", deepseek_key

    raise RuntimeError(
        "No LLM API key configured for intent classification. "
        "Set MISTRAL_API_KEY, GROQ_API_KEY, or DEEPSEEK_API_KEY."
    )


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a legal query intent classifier for Neethi AI, an Indian legal assistance system.

Given the user's message, their role, and conversation context, classify the intent.

INTENTS:
- new_scenario: Fresh legal problem or situation described for the first time
- clarification_answer: User answering a question the assistant previously asked
- followup_action: User requesting a specific action (like drafting, analysis, lookup)
- new_question: Completely unrelated new question (different from current session topic)
- greeting: Hello, thanks, goodbye, or pleasantries
- section_lookup: User is asking to read or explain a SPECIFIC numbered section (e.g., "What does BNS 103 say?", "Show me Section 420 IPC", "Read Section 302"). The user must reference a concrete section NUMBER — just mentioning an act name (e.g., "BNS 2023", "IPC") does NOT qualify.

RULES:
1. section_lookup requires a SPECIFIC SECTION NUMBER reference (e.g., "section 103", "s.420"). Mentioning an act name with a year (e.g., "BNS 2023", "IPC 1860") is NOT section_lookup — it is new_scenario. Questions like "What is the punishment for murder under BNS?" are new_scenario, not section_lookup.
2. If the conversation context has pending questions and the user's message answers them, classify as clarification_answer
3. For new_scenario, detect emotional tone (distressed, urgent, neutral, formal)
4. Extract legal entities: act names, section numbers, parties, locations, dates
5. Set needs_clarification=true and provide clarifying_questions when the scenario is vague or lacks specific details needed for a precise legal answer. For clear, specific questions (e.g., "What is the punishment for murder under BNS 2023?"), set needs_clarification=false.
6. Suggest appropriate actions based on user role

ROLE-SPECIFIC ACTIONS:
- citizen: step_by_step, legal_sections, find_lawyer, draft_complaint
- lawyer: irac_analysis, section_deep_dive, precedent_search, counter_arguments
- police: sop_reference, fir_template, bnss_procedure, arrest_checklist
- legal_advisor: compliance_checklist, draft_notice, risk_assessment, case_strategy

Respond with ONLY valid JSON matching this schema:
{
  "intent": "string",
  "entities": {},
  "needs_clarification": boolean,
  "clarifying_questions": [],
  "emotional_tone": "string",
  "suggested_actions": [],
  "confidence": number
}"""


def _build_user_prompt(message: str, user_role: str, context: dict) -> str:
    parts = [f"USER ROLE: {user_role}", f"MESSAGE: {message}"]
    if context:
        parts.append(f"SESSION CONTEXT: {json.dumps(context, default=str)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_intent(
    message: str,
    user_role: str,
    context: dict | None = None,
) -> IntentResult:
    """Classify a user turn's intent using a fast LLM call.

    Args:
        message: The user's message text.
        user_role: One of citizen, lawyer, legal_advisor, police.
        context: Current session context dict (accumulated from prior turns).

    Returns:
        IntentResult with classified intent and extracted metadata.
    """
    import litellm

    model_id, api_key = _get_litellm_model()
    user_prompt = _build_user_prompt(message, user_role, context or {})

    try:
        response = await litellm.acompletion(
            model=model_id,
            api_key=api_key,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return IntentResult(**parsed)

    except json.JSONDecodeError as exc:
        logger.warning("Intent classifier returned invalid JSON: %s", exc)
        return _fallback_classify(message, user_role)
    except Exception as exc:
        logger.error("Intent classification failed: %s", exc)
        return _fallback_classify(message, user_role)


def _fallback_classify(message: str, user_role: str) -> IntentResult:
    """Rule-based fallback when LLM is unavailable."""
    import re

    msg_lower = message.lower().strip()

    # Greeting detection
    greetings = {"hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye", "namaste"}
    if msg_lower in greetings or any(msg_lower.startswith(g) for g in greetings):
        return IntentResult(intent="greeting", confidence=0.8)

    # Section lookup detection — must reference a specific section number,
    # NOT a year (e.g., "BNS 103" is a section, "BNS 2023" is a year)
    section_pattern = re.compile(
        r"(?:section|sec\.?)\s*\.?\s*(\d{1,4}[A-Za-z]?)"
        r"|(?:BNS|BNSS|BSA|IPC|CrPC|IEA)\s*\.?\s*(\d{1,3}[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    match = section_pattern.search(message)
    if match:
        # Ensure we matched an actual section number, not a 4-digit year
        num = match.group(1) or match.group(2)
        if num and not re.match(r"^(19|20)\d{2}$", num):
            return IntentResult(intent="section_lookup", confidence=0.7)

    # Default: new scenario
    role_actions = {
        "citizen": ["step_by_step", "legal_sections", "find_lawyer"],
        "lawyer": ["irac_analysis", "section_deep_dive", "precedent_search"],
        "police": ["sop_reference", "fir_template", "bnss_procedure"],
        "legal_advisor": ["compliance_checklist", "draft_notice", "risk_assessment"],
    }

    return IntentResult(
        intent="new_scenario",
        needs_clarification=True,
        clarifying_questions=["Could you provide more details about your situation?"],
        suggested_actions=role_actions.get(user_role, role_actions["citizen"]),
        confidence=0.4,
    )
