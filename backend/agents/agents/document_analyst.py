"""DocumentAnalyst CrewAI agent stub.

Designed to work with PageIndex for deep document understanding.
Currently a stub — ready to activate when PageIndex API key is available.
"""

from __future__ import annotations

from crewai import Agent

from backend.config.llm_config import get_standard_llm


def make_document_analyst() -> Agent:
    """Create the DocumentAnalyst agent.

    This agent analyzes uploaded legal documents using PageIndex
    for structure extraction and LLM for legal interpretation.
    """
    return Agent(
        role="Document Analyst",
        goal=(
            "Analyze uploaded legal documents to extract key provisions, "
            "obligations, rights, deadlines, and risk areas. Provide structured "
            "analysis with references to specific clauses and sections."
        ),
        backstory=(
            "You are a meticulous legal document analyst with expertise in "
            "Indian contract law, statutory instruments, and regulatory filings. "
            "You use PageIndex AI to extract document structure and then apply "
            "legal reasoning to identify critical provisions and potential issues."
        ),
        llm=get_standard_llm(),
        verbose=False,
        allow_delegation=False,
        # Tools will be added when PageIndex is activated:
        # tools=[PageIndexAnalyzeTool(), SectionVerifierTool()],
        tools=[],
    )
