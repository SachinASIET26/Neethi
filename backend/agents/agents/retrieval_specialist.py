"""Retrieval Specialist Agent — Phase 5.

Second agent in every crew pipeline. Executes hybrid search against the
Qdrant legal database using the parameters determined by the Query Analyst.

MANDATORY WORKFLOW:
1. If query contains old statute references → call StatuteNormalizationTool first
2. Use normalized section references (BNS/BNSS/BSA) in all Qdrant queries
3. Never search for "IPC 302" directly — search for "BNS 103" after normalization

Model: DeepSeek-Chat — accurate, cost-effective for tool orchestration.
"""

from __future__ import annotations

from crewai import Agent

from backend.agents.tools import (
    QdrantHybridSearchTool,
    StatuteNormalizationTool,
)
from backend.config.llm_config import get_light_llm


def make_retrieval_specialist() -> Agent:
    """Return a configured Retrieval Specialist agent instance."""
    return Agent(
        role="Legal Document Retrieval Specialist",
        goal=(
            "Retrieve the most relevant Indian legal sections from the Qdrant database. "
            "Return only what the search tool actually returns — never add, invent, or infer "
            "legal sections that were not in the tool output. "
            "If the search tool returns 0 results, output exactly: 'NO_RELEVANT_DOCUMENTS_FOUND'."
        ),
        backstory=(
            "You are a legal database retrieval specialist. Your job is to call search tools "
            "and return their output — nothing more. "
            "CRITICAL RULE: You NEVER fabricate, invent, or guess legal section numbers, act "
            "names, or section text. If QdrantHybridSearchTool returns 0 results after your "
            "search attempts, you output exactly 'NO_RELEVANT_DOCUMENTS_FOUND' and stop. "
            "You do not fill gaps with your own legal knowledge — the citation verifier downstream "
            "will reject any section not in the database, so fabrication only wastes pipeline steps. "
            "You are acutely aware of dangerous IPC→BNS false-friends: "
            "IPC 302 (Murder) → BNS 103 (NOT BNS 302 which is Religious Offences). "
            "CrPC 438 (Anticipatory Bail) → BNSS 482 (NOT BNSS 438). "
            "You ALWAYS call StatuteNormalizationTool before searching when old statutes appear."
        ),
        tools=[
            StatuteNormalizationTool(),
            QdrantHybridSearchTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        max_iter=4,  # 2 tool calls (legal_sections + sc_judgments) + 1 retry slot + Final Answer
        max_retry_limit=1,
    )
