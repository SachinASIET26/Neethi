"""Citation Checker Agent — Phase 5.

Mandatory safety gate — runs BEFORE ResponseFormatter in every crew pipeline.
Verifies every section cited in the prior agent's output actually exists in the
indexed Qdrant database.

Ordering rule (enforced at crew level):
    ... → CitationChecker → ResponseFormatter

NOT: ... → ResponseFormatter → CitationChecker
(If formatter runs first, it has already shaped unverified content for the user.)

Model: DeepSeek-Chat — accurate for structured verification tasks.
The citation verification itself is deterministic (Qdrant scroll) —
the LLM is only needed to parse the prior agent's output and call the tool.
"""

from __future__ import annotations

from crewai import Agent

from backend.agents.tools import CitationVerificationTool
from backend.config.llm_config import get_light_llm


def make_citation_checker() -> Agent:
    """Return a configured Citation Checker agent instance."""
    return Agent(
        role="Legal Citation and Accuracy Verifier",
        goal=(
            "Verify every section number and legal citation in the response before it reaches "
            "the user. For each section cited: call CitationVerificationTool with the act_code "
            "and section_number. If CitationVerificationTool returns NOT_FOUND, remove that "
            "citation from the response. Never deliver unverified legal information."
        ),
        backstory=(
            "You are a meticulous legal fact-checker. Your single purpose is zero hallucinations. "
            "Every section number must exist in the Neethi AI indexed database before it can be "
            "cited in a response. You know the most dangerous false-friend in this system: "
            "BNS 302 is Religious Offences — NOT murder (murder is BNS 103). "
            "If an agent upstream cited BNS 302 for murder, you catch it here and correct it. "
            "When CitationVerificationTool returns NOT_FOUND for a citation, you remove it and "
            "note the removal. You never guess, never infer, never assume a section exists — "
            "you verify each one individually via the tool. "
            "If confidence after verification is below threshold, you return a 'cannot verify' "
            "response rather than delivering potentially wrong legal information."
        ),
        tools=[
            CitationVerificationTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        max_iter=8,  # Year guard + 4 section verifications + case materialisation + cross-check + final answer
        max_retry_limit=2,
    )
