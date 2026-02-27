"""Query Analyst Agent — Phase 5.

First agent in every crew pipeline. Classifies the user's legal query,
extracts entities, and determines whether statute normalization is needed
before the retrieval step.

Model: Groq (Llama 3.3 70B) — chosen for low latency. Classification is a
structured output task that does not require deep reasoning.
"""

from __future__ import annotations

from crewai import Agent

from backend.agents.tools import QueryClassifierTool, StatuteNormalizationTool
from backend.config.llm_config import get_fast_llm


def make_query_analyst() -> Agent:
    """Return a configured Query Analyst agent instance.

    Factory function (not module-level singleton) so LLM clients are
    created fresh per crew run, avoiding stale connection state.
    """
    return Agent(
        role="Legal Query Analyst",
        goal=(
            "Understand, classify, and decompose the user's legal query into actionable "
            "search parameters. Detect whether the query references old Indian statutes "
            "(IPC, CrPC, IEA) and normalize them to the new equivalents (BNS, BNSS, BSA) "
            "before the retrieval step."
        ),
        backstory=(
            "You are an expert legal query analyst who deeply understands both the old Indian "
            "statutes (IPC 1860, CrPC 1973, IEA 1872) and the new Bharatiya Sanhitas (BNS 2023, "
            "BNSS 2023, BSA 2023) that replaced them from July 1, 2024. "
            "You know the dangerous false-friends: IPC 302 = Murder maps to BNS 103, NOT BNS 302 "
            "(which is Religious Offences — a completely different crime). "
            "Your job is to classify queries, extract legal entities, and flag old-statute references "
            "so the retrieval step searches for the correct modern sections."
        ),
        tools=[
            QueryClassifierTool(),
            StatuteNormalizationTool(),
        ],
        llm=get_fast_llm(),
        verbose=True,
        max_iter=3,
        max_retry_limit=2,
    )
