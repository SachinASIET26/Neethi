"""Role-specific response generators and action suggestion sets.

Provides empathetic first-turn responses, clarification formatting, and
action suggestion definitions tailored to each user role.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Action suggestion definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActionSuggestion:
    id: str
    label: str
    icon: str
    description: str


# Per-role action sets
CITIZEN_ACTIONS: list[ActionSuggestion] = [
    ActionSuggestion("step_by_step", "Step-by-step legal guidance", "directions", "Get a simplified walkthrough of what to do next"),
    ActionSuggestion("legal_sections", "Show relevant legal sections", "menu_book", "View the actual law provisions that apply"),
    ActionSuggestion("find_lawyer", "Find a lawyer near me", "person_search", "Search for legal professionals in your area"),
    ActionSuggestion("draft_complaint", "Draft a complaint", "edit_document", "Generate a complaint letter draft"),
]

LAWYER_ACTIONS: list[ActionSuggestion] = [
    ActionSuggestion("irac_analysis", "Full IRAC analysis", "analytics", "Detailed Issue-Rule-Application-Conclusion analysis"),
    ActionSuggestion("section_deep_dive", "Section deep dive", "menu_book", "Explore relevant statutory provisions in depth"),
    ActionSuggestion("precedent_search", "Search precedents", "search", "Find relevant Supreme Court and High Court judgments"),
    ActionSuggestion("counter_arguments", "Counter arguments", "swap_horiz", "Explore potential counter-arguments and defenses"),
]

POLICE_ACTIONS: list[ActionSuggestion] = [
    ActionSuggestion("sop_reference", "SOP reference", "checklist", "Standard Operating Procedure for this situation"),
    ActionSuggestion("fir_template", "FIR template", "edit_document", "Generate an FIR draft with applicable sections"),
    ActionSuggestion("bnss_procedure", "BNSS procedure", "gavel", "Procedural steps under Bharatiya Nagarik Suraksha Sanhita"),
    ActionSuggestion("arrest_checklist", "Arrest checklist", "fact_check", "Pre-arrest and post-arrest compliance checklist"),
]

LEGAL_ADVISOR_ACTIONS: list[ActionSuggestion] = [
    ActionSuggestion("compliance_checklist", "Compliance checklist", "checklist", "Regulatory compliance requirements"),
    ActionSuggestion("draft_notice", "Draft legal notice", "edit_document", "Generate a legal notice draft"),
    ActionSuggestion("risk_assessment", "Risk assessment", "warning", "Evaluate legal risks and exposure"),
    ActionSuggestion("case_strategy", "Case strategy", "strategy", "Strategic options and recommended approach"),
]

ROLE_ACTIONS: dict[str, list[ActionSuggestion]] = {
    "citizen": CITIZEN_ACTIONS,
    "lawyer": LAWYER_ACTIONS,
    "police": POLICE_ACTIONS,
    "legal_advisor": LEGAL_ADVISOR_ACTIONS,
}


def get_actions_for_role(role: str) -> list[ActionSuggestion]:
    """Return the action suggestion set for a given user role."""
    return ROLE_ACTIONS.get(role, CITIZEN_ACTIONS)


def get_action_by_id(action_id: str, role: str) -> ActionSuggestion | None:
    """Find a specific action by ID within a role's action set."""
    for action in get_actions_for_role(role):
        if action.id == action_id:
            return action
    return None


# ---------------------------------------------------------------------------
# Turn 1 response templates (empathy + context gathering)
# ---------------------------------------------------------------------------

_CITIZEN_NEW_SCENARIO = """\
I understand you're dealing with a legal situation, and I'm here to help you navigate it.

To give you the most accurate guidance, I need to understand a few things:

{questions}

Take your time — there's no rush. Your answers will help me find the right legal provisions and steps for your situation."""

_LAWYER_NEW_SCENARIO = """\
Noted. Let me gather the key details to provide a thorough analysis.

{questions}

Once I have these details, I'll run a full statutory analysis with relevant provisions and precedents."""

_POLICE_NEW_SCENARIO = """\
Understood. To provide the correct procedural guidance and applicable sections:

{questions}

This will help me identify the exact BNSS/BNS provisions and SOPs that apply."""

_LEGAL_ADVISOR_NEW_SCENARIO = """\
I'll help assess the legal position here. To provide a comprehensive risk analysis:

{questions}

With these details, I can identify applicable compliance requirements and recommend a strategy."""

_ROLE_TEMPLATES: dict[str, str] = {
    "citizen": _CITIZEN_NEW_SCENARIO,
    "lawyer": _LAWYER_NEW_SCENARIO,
    "police": _POLICE_NEW_SCENARIO,
    "legal_advisor": _LEGAL_ADVISOR_NEW_SCENARIO,
}


def format_new_scenario_response(
    role: str,
    questions: list[str],
    emotional_tone: str = "neutral",
) -> str:
    """Generate the Turn 1 response for a new scenario.

    Includes empathy acknowledgment (stronger for distressed users) and
    numbered clarifying questions.
    """
    template = _ROLE_TEMPLATES.get(role, _CITIZEN_NEW_SCENARIO)

    # Format questions as numbered list
    formatted_questions = "\n".join(
        f"{i + 1}. {q}" for i, q in enumerate(questions)
    )

    response = template.format(questions=formatted_questions)

    # Prepend empathy for distressed users
    if emotional_tone == "distressed" and role == "citizen":
        response = (
            "I can see this is a difficult situation, and I want you to know "
            "that there are legal protections available to help you.\n\n" + response
        )
    elif emotional_tone == "urgent":
        response = (
            "I understand this is urgent. Let me help you as quickly as possible.\n\n"
            + response
        )

    return response


# ---------------------------------------------------------------------------
# Greeting responses
# ---------------------------------------------------------------------------

_GREETING_RESPONSES: dict[str, str] = {
    "citizen": (
        "Hello! I'm Neethi AI, your legal assistant. I can help you understand your legal rights, "
        "find relevant laws, draft complaints, and locate lawyers near you.\n\n"
        "How can I help you today?"
    ),
    "lawyer": (
        "Hello, Counsel. Neethi AI is ready to assist with statutory analysis, IRAC methodology, "
        "precedent research, and document drafting.\n\n"
        "What matter are you working on?"
    ),
    "police": (
        "Hello, Officer. I can assist with BNS/BNSS procedural guidance, FIR drafting, "
        "SOPs, and arrest/investigation checklists.\n\n"
        "What do you need help with?"
    ),
    "legal_advisor": (
        "Hello. I'm ready to assist with compliance analysis, risk assessment, "
        "legal notice drafting, and case strategy.\n\n"
        "What would you like to work on?"
    ),
}


def get_greeting_response(role: str) -> str:
    """Return a role-appropriate greeting response."""
    return _GREETING_RESPONSES.get(role, _GREETING_RESPONSES["citizen"])


# ---------------------------------------------------------------------------
# Context completion check
# ---------------------------------------------------------------------------

def is_context_complete(context: dict) -> bool:
    """Check if accumulated session context has enough info to fire the full pipeline.

    Requires at minimum: a scenario description and at least one answered question.
    """
    return bool(
        context.get("scenario")
        and context.get("answers")
        and len(context.get("answers", {})) >= 1
    )


def merge_clarification_into_context(
    context: dict,
    message: str,
    entities: dict,
) -> dict:
    """Merge a clarification answer into the session context."""
    updated = {**context}

    # Track answers
    answers = updated.get("answers", {})
    answer_idx = len(answers)
    answers[f"answer_{answer_idx}"] = message
    updated["answers"] = answers

    # Merge new entities
    existing_entities = updated.get("entities", {})
    existing_entities.update(entities)
    updated["entities"] = existing_entities

    return updated
