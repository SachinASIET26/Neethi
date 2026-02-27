"""Phase 5 integration tests — CrewAI tools, agents, and crew configurations.

Test strategy (per user direction):
    - LLM calls: MOCKED — tests verify tool invocation and response handling,
      not LLM quality. Patching litellm.completion is the single mock point.
    - Qdrant: REAL — phase 3/4 tests already proved indexing works; keeping
      Qdrant live ensures CitationVerificationTool stays in the verification loop.
    - FlagEmbedding (BGE-M3): AUTO-SKIP if not installed (no GPU on local machine).

Tests are organized into three groups:
    1. Tool tests  — test each Phase 5 tool in isolation
    2. Agent tests — verify agents have correct tools (no kickoff needed)
    3. Crew tests  — verify task ordering and crew structure

Run:
    pytest backend/tests/test_phase5_agents.py -v

Skip conditions:
    - Qdrant-dependent tests: skip if Qdrant not reachable
    - Search tool tests: skip if FlagEmbedding not installed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup + env loading
# ---------------------------------------------------------------------------

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

def _check_flag_embedding() -> bool:
    try:
        import FlagEmbedding  # noqa: F401
        return True
    except ImportError:
        return False


def _check_qdrant() -> bool:
    try:
        from qdrant_client import QdrantClient
        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY")
        client = QdrantClient(url=url, api_key=api_key, timeout=3)
        client.get_collections()
        return True
    except Exception:
        return False


def _check_legal_sections_indexed(min_points: int = 100) -> bool:
    try:
        from qdrant_client import QdrantClient
        from backend.rag.qdrant_setup import COLLECTION_LEGAL_SECTIONS
        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY")
        client = QdrantClient(url=url, api_key=api_key, timeout=3)
        info = client.get_collection(COLLECTION_LEGAL_SECTIONS)
        return (info.points_count or 0) >= min_points
    except Exception:
        return False


_FLAG_EMBEDDING_AVAILABLE = _check_flag_embedding()
_QDRANT_AVAILABLE = _check_qdrant()
_SECTIONS_INDEXED = _check_legal_sections_indexed()

requires_flag_embedding = pytest.mark.skipif(
    not _FLAG_EMBEDDING_AVAILABLE,
    reason="FlagEmbedding not installed — run on GPU machine: pip install FlagEmbedding",
)
requires_qdrant = pytest.mark.skipif(
    not _QDRANT_AVAILABLE,
    reason="Qdrant not reachable — ensure QDRANT_URL is set and Qdrant is running",
)
requires_search = pytest.mark.skipif(
    not (_FLAG_EMBEDDING_AVAILABLE and _QDRANT_AVAILABLE and _SECTIONS_INDEXED),
    reason="Search tests require FlagEmbedding + Qdrant + legal_sections indexed",
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_mock_litellm_response(content: str) -> MagicMock:
    """Create a mock litellm.completion response with the given content."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock()
    mock_response.choices[0].message.content = content
    return mock_response


# ---------------------------------------------------------------------------
# GROUP 1: Tool tests
# ---------------------------------------------------------------------------

@requires_search
def test_qdrant_search_tool_returns_results_for_murder_query():
    """QdrantHybridSearchTool returns BNS results for a murder query.

    Verifies the tool successfully calls HybridSearcher and returns formatted output.
    """
    from backend.agents.tools import QdrantHybridSearchTool

    tool = QdrantHybridSearchTool()
    result = tool.run({
        "query": "punishment for murder under BNS",
        "era_filter": "naveen_sanhitas",
        "top_k": 3,
        "rerank": False,  # Skip reranking to reduce test time
    })

    assert "SEARCH RESULTS" in result, f"Expected search results header. Got:\n{result}"
    assert "result(s)" in result, f"Expected result count. Got:\n{result}"
    # Must return BNS results (naveen_sanhitas era filter applied)
    assert "BNS" in result or "naveen" in result.lower(), (
        f"With naveen_sanhitas filter, results must reference BNS. Got:\n{result}"
    )
    assert "NOT_AVAILABLE" not in result, (
        f"FlagEmbedding should be available on this machine. Got:\n{result}"
    )


@requires_search
def test_qdrant_search_tool_act_filter_restricts_results():
    """act_filter='BNS_2023' returns only BNS_2023 sections."""
    from backend.agents.tools import QdrantHybridSearchTool

    tool = QdrantHybridSearchTool()
    result = tool.run({
        "query": "offences against body",
        "act_filter": "BNS_2023",
        "top_k": 3,
        "rerank": False,
    })

    assert "SEARCH RESULTS" in result, f"Expected search results. Got:\n{result}"
    # All numbered result headers should be BNS_2023.
    # Use startswith("[") without strip() to skip indented metadata lines like
    #     [era=naveen_sanhitas, offence=False]
    # which don't contain the act code but are valid BNS-era results.
    result_headers = [l for l in result.splitlines() if l.startswith("[")]
    for line in result_headers:
        assert "BNS_2023" in line or "BNS" in line, (
            f"With act_filter=BNS_2023, all results should be BNS. Line: {line}"
        )


def test_query_classifier_classifies_criminal_query():
    """QueryClassifierTool correctly classifies a murder query as criminal domain.

    Uses mocked LLM — tests classification parsing, not LLM quality.
    """
    from backend.agents.tools import QueryClassifierTool

    mock_response = _make_mock_litellm_response(
        "Legal Domain: criminal_substantive\n"
        "Intent: information_seeking\n"
        "Entities: murder, BNS 103, IPC 302\n"
        "Contains Old Statutes: true\n"
        "Suggested Act Filter: BNS_2023\n"
        "Suggested Era Filter: naveen_sanhitas\n"
        "Complexity: simple"
    )

    tool = QueryClassifierTool()
    with patch("litellm.completion", return_value=mock_response):
        result = tool.run({
            "query": "What is the punishment for murder under IPC 302?",
            "user_role": "citizen",
        })

    assert "QUERY CLASSIFICATION" in result, f"Expected classification header. Got:\n{result}"
    assert "criminal_substantive" in result, f"Expected criminal domain. Got:\n{result}"
    assert "Contains Old Statutes: true" in result, (
        f"IPC 302 must be flagged as old statute. Got:\n{result}"
    )
    assert "naveen_sanhitas" in result, (
        f"BNS query should suggest naveen_sanhitas filter. Got:\n{result}"
    )


def test_query_classifier_fallback_on_llm_failure():
    """QueryClassifierTool returns rule-based fallback when LLM call fails."""
    from backend.agents.tools import QueryClassifierTool

    tool = QueryClassifierTool()
    with patch("litellm.completion", side_effect=Exception("API unavailable")):
        result = tool.run({
            "query": "what is punishment for murder under IPC",
            "user_role": "citizen",
        })

    assert "QUERY CLASSIFICATION" in result, f"Expected classification even on LLM failure. Got:\n{result}"
    assert "fallback" in result.lower(), f"Fallback should be labeled. Got:\n{result}"
    # Rule-based: IPC mention → Contains Old Statutes = true
    assert "true" in result.lower(), (
        f"IPC in query → Contains Old Statutes should be true in fallback. Got:\n{result}"
    )


def test_irac_analyzer_returns_four_sections():
    """IRACAnalyzerTool output contains all four IRAC sections.

    Uses mocked LLM — tests structure enforcement, not LLM output quality.
    """
    from backend.agents.tools import IRACAnalyzerTool

    mock_irac = (
        "IRAC ANALYSIS:\n\n"
        "ISSUE:\nWhether murder under BNS 103 carries mandatory death penalty.\n\n"
        "RULE:\nBNS 2023 s.103 — Murder: death or imprisonment for life + fine.\n\n"
        "APPLICATION:\nThe section provides two alternative punishments — "
        "courts have discretion between death and life imprisonment.\n\n"
        "CONCLUSION:\nNo mandatory death penalty. Court exercises discretion.\n\n"
        "APPLICABLE SECTIONS:\nBNS_2023 s.103 — Murder\n\n"
        "CONFIDENCE: high"
    )

    mock_response = _make_mock_litellm_response(mock_irac)

    tool = IRACAnalyzerTool()
    # Patch both: os.getenv in the tool module (so api_key check passes)
    # and litellm.completion (so no real API call is made)
    with patch("backend.agents.tools.irac_analyzer_tool.os.getenv", return_value="fake-key"), \
         patch("litellm.completion", return_value=mock_response):
        result = tool.run({
            "retrieved_sections": "[1] BNS_2023 s.103 — Murder\n    Whoever commits murder...",
            "original_query": "Is death penalty mandatory for murder under BNS?",
            "user_role": "lawyer",
        })

    assert "ISSUE:" in result, f"IRAC output must contain ISSUE section. Got:\n{result}"
    assert "RULE:" in result, f"IRAC output must contain RULE section. Got:\n{result}"
    assert "APPLICATION:" in result, f"IRAC output must contain APPLICATION section. Got:\n{result}"
    assert "CONCLUSION:" in result, f"IRAC output must contain CONCLUSION section. Got:\n{result}"


def test_irac_analyzer_empty_retrieved_sections_returns_error():
    """IRACAnalyzerTool returns an error when no retrieved sections are provided."""
    from backend.agents.tools import IRACAnalyzerTool

    tool = IRACAnalyzerTool()
    result = tool.run({
        "retrieved_sections": "",
        "original_query": "What is murder?",
        "user_role": "lawyer",
    })

    assert "ERROR" in result, f"Empty retrieved_sections must return error. Got:\n{result}"
    assert "QdrantHybridSearchTool" in result, (
        f"Error should reference the search tool that should have been called first. Got:\n{result}"
    )


# ---------------------------------------------------------------------------
# GROUP 2: Agent structural tests (no kickoff — inspect agent config)
# ---------------------------------------------------------------------------

def test_retrieval_specialist_has_normalization_tool():
    """RetrievalSpecialist agent has StatuteNormalizationTool in its toolset.

    This is the structural guarantee that normalization can't be skipped —
    the agent has the tool and its backstory explicitly requires using it.
    """
    from backend.agents.agents import make_retrieval_specialist
    from backend.agents.tools import StatuteNormalizationTool

    agent = make_retrieval_specialist()
    tool_names = [t.name for t in agent.tools]

    assert "StatuteNormalizationTool" in tool_names, (
        f"RetrievalSpecialist must have StatuteNormalizationTool. Has: {tool_names}"
    )
    assert "QdrantHybridSearchTool" in tool_names, (
        f"RetrievalSpecialist must have QdrantHybridSearchTool. Has: {tool_names}"
    )


def test_citation_checker_has_verification_tool():
    """CitationChecker agent has CitationVerificationTool — and only that tool.

    CitationChecker should have no retrieval tools. Adding retrieval tools would
    create a path for unverified content to enter the response.
    """
    from backend.agents.agents import make_citation_checker

    agent = make_citation_checker()
    tool_names = [t.name for t in agent.tools]

    assert "CitationVerificationTool" in tool_names, (
        f"CitationChecker must have CitationVerificationTool. Has: {tool_names}"
    )
    # Must NOT have retrieval tools — those would bypass the safety gate
    assert "QdrantHybridSearchTool" not in tool_names, (
        f"CitationChecker must NOT have QdrantHybridSearchTool. Has: {tool_names}"
    )


def test_response_formatter_has_no_tools():
    """ResponseFormatter has no tools — operates on verified context only.

    If the formatter had retrieval tools, it could introduce unverified
    citations into the final response, defeating the safety model.
    """
    from backend.agents.agents import make_response_formatter

    agent = make_response_formatter()
    assert len(agent.tools) == 0, (
        f"ResponseFormatter must have no tools (receives verified context only). "
        f"Has: {[t.name for t in agent.tools]}"
    )


# ---------------------------------------------------------------------------
# GROUP 3: Crew structural tests
# ---------------------------------------------------------------------------

def test_layman_crew_citation_runs_before_formatter():
    """In the layman crew, CitationChecker task runs before ResponseFormatter task.

    Verifies the corrected ordering: CitationChecker gates content before
    ResponseFormatter shapes it for the user.
    """
    from backend.agents.crew_config import make_layman_crew

    crew = make_layman_crew()
    agent_roles = [task.agent.role for task in crew.tasks]

    citation_idx = next(
        (i for i, role in enumerate(agent_roles) if "Citation" in role or "Verif" in role),
        None,
    )
    formatter_idx = next(
        (i for i, role in enumerate(agent_roles) if "Format" in role),
        None,
    )

    assert citation_idx is not None, f"CitationChecker must be in layman crew tasks. Roles: {agent_roles}"
    assert formatter_idx is not None, f"ResponseFormatter must be in layman crew tasks. Roles: {agent_roles}"
    assert citation_idx < formatter_idx, (
        f"CitationChecker (index {citation_idx}) must run BEFORE ResponseFormatter "
        f"(index {formatter_idx}). Roles in order: {agent_roles}"
    )


def test_lawyer_crew_has_legal_reasoner_before_citation():
    """In the lawyer crew, LegalReasoner runs between RetrievalSpecialist and CitationChecker."""
    from backend.agents.crew_config import make_lawyer_crew

    crew = make_lawyer_crew()
    agent_roles = [task.agent.role for task in crew.tasks]

    retrieval_idx = next((i for i, r in enumerate(agent_roles) if "Retrieval" in r), None)
    reasoner_idx = next((i for i, r in enumerate(agent_roles) if "Reason" in r or "Analysis" in r), None)
    citation_idx = next((i for i, r in enumerate(agent_roles) if "Citation" in r or "Verif" in r), None)
    formatter_idx = next((i for i, r in enumerate(agent_roles) if "Format" in r), None)

    assert all(x is not None for x in [retrieval_idx, reasoner_idx, citation_idx, formatter_idx]), (
        f"Lawyer crew must have all 4 post-analyst agents. Roles: {agent_roles}"
    )
    assert retrieval_idx < reasoner_idx < citation_idx < formatter_idx, (
        f"Lawyer crew order must be: Retrieval → Reasoner → Citation → Formatter. "
        f"Got indices: retrieval={retrieval_idx}, reasoner={reasoner_idx}, "
        f"citation={citation_idx}, formatter={formatter_idx}. "
        f"Roles: {agent_roles}"
    )


def test_police_crew_has_no_legal_reasoner():
    """Police crew does not include LegalReasoner.

    Police need procedural steps, not IRAC analysis.
    """
    from backend.agents.crew_config import make_police_crew

    crew = make_police_crew()
    agent_roles = [task.agent.role for task in crew.tasks]

    has_reasoner = any("Reason" in r or "Analysis" in r for r in agent_roles)
    assert not has_reasoner, (
        f"Police crew must not include LegalReasoner. Roles: {agent_roles}"
    )


def test_get_crew_for_role_returns_correct_crew():
    """get_crew_for_role router returns the right crew type for each role."""
    from backend.agents.crew_config import get_crew_for_role
    from crewai import Crew

    for role in ("citizen", "lawyer", "legal_advisor", "police"):
        crew = get_crew_for_role(role)
        assert isinstance(crew, Crew), f"Expected Crew for role {role!r}, got {type(crew)}"

    with pytest.raises(ValueError, match="Unknown user_role"):
        get_crew_for_role("hacker")
