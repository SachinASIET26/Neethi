"""Legal Reasoner Agent — Phase 5.

Third agent — activated ONLY for lawyer and legal_advisor roles.
Performs structured IRAC analysis on the retrieved legal sections.

Model: DeepSeek-R1 — strong chain-of-thought reasoning required for IRAC.
Falls back to DeepSeek-Chat if R1 is unavailable.

NOT activated for citizen or police roles — they get direct formatted responses
without the IRAC layer (it would be too complex and unnecessary for their needs).
"""

from __future__ import annotations

from crewai import Agent

from backend.agents.tools import IRACAnalyzerTool
from backend.config.llm_config import get_reasoning_llm


def make_legal_reasoner() -> Agent:
    """Return a configured Legal Reasoner agent instance."""
    return Agent(
        role="Legal Reasoning and Analysis Expert",
        goal=(
            "Analyze retrieved legal documents using the IRAC methodology "
            "(Issue, Rule, Application, Conclusion) to produce structured legal analysis. "
            "Only cite sections that were actually retrieved — never invent section numbers. "
            "Flag when retrieved sections are insufficient to answer with confidence."
        ),
        backstory=(
            "You are a senior legal analyst specializing in Indian law with 20+ years of experience "
            "in both the old codes (IPC, CrPC, IEA) and the new Bharatiya Sanhitas. "
            "You follow IRAC methodology rigorously: identify the precise legal Issue, state the Rule "
            "from the retrieved sections, Apply the rule to the specific facts, and state a Conclusion. "
            "You never hallucinate section numbers — if a section is not in the retrieved text, "
            "you explicitly state that the database does not contain sufficient information. "
            "You are aware that post-July 2024, the operative law for new offences is BNS/BNSS/BSA, "
            "not IPC/CrPC/IEA — and you clearly distinguish which era applies to the query."
        ),
        tools=[
            IRACAnalyzerTool(),
        ],
        llm=get_reasoning_llm(),
        verbose=True,
        max_iter=3,
        max_retry_limit=2,
    )
