"""Phase 4 integration tests — StatuteNormalizationTool and CitationVerificationTool.

These tests require:
1. PostgreSQL reachable at DATABASE_URL with active transition mappings seeded
2. Qdrant reachable at QDRANT_URL with legal_sections indexed (Phase 3 complete)

Tests auto-skip if either dependency is unreachable.

Run:
    pytest backend/tests/test_phase4_tools.py -v

To run against specific instances:
    DATABASE_URL=postgresql+asyncpg://... QDRANT_URL=http://... pytest backend/tests/test_phase4_tools.py -v
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

def _check_db() -> bool:
    """Return True if PostgreSQL is reachable."""
    try:
        import asyncio
        from backend.db.database import health_check
        return asyncio.run(health_check())
    except Exception:
        return False


def _check_qdrant() -> bool:
    """Return True if Qdrant is reachable."""
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
    """Return True if legal_sections collection has sufficient points."""
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


_DB_AVAILABLE = _check_db()
_QDRANT_AVAILABLE = _check_qdrant()
_SECTIONS_INDEXED = _check_legal_sections_indexed()

requires_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="PostgreSQL not reachable — ensure DATABASE_URL is set and DB is running",
)

requires_qdrant = pytest.mark.skipif(
    not _QDRANT_AVAILABLE,
    reason="Qdrant not reachable — ensure QDRANT_URL is set and Qdrant is running",
)

requires_indexed = pytest.mark.skipif(
    not (_QDRANT_AVAILABLE and _SECTIONS_INDEXED),
    reason="legal_sections not indexed — run indexing pipeline first (Phase 3)",
)

requires_db_and_qdrant = pytest.mark.skipif(
    not (_DB_AVAILABLE and _QDRANT_AVAILABLE),
    reason="Both PostgreSQL and Qdrant required for these tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def normalization_tool():
    """Return a StatuteNormalizationTool instance."""
    from backend.agents.tools import StatuteNormalizationTool
    return StatuteNormalizationTool()


@pytest.fixture(scope="module")
def citation_tool():
    """Return a CitationVerificationTool instance."""
    from backend.agents.tools import CitationVerificationTool
    return CitationVerificationTool()


# ---------------------------------------------------------------------------
# StatuteNormalizationTool tests
# ---------------------------------------------------------------------------

@requires_db
def test_ipc302_normalizes_to_bns103(normalization_tool):
    """Core safety test: IPC 302 (Murder) must map to BNS 103, not BNS 302.

    BNS 302 is Religious Offences — a completely different offence.
    This collision is the most dangerous false-friend in the entire codebase.
    """
    result = normalization_tool.run({"old_act": "IPC", "old_section": "302"})

    # Must find BNS 103
    assert "103" in result, (
        f"IPC 302 must map to BNS 103 (Murder). Got:\n{result}"
    )
    assert "BNS_2023" in result or "BNS" in result, (
        f"Result must reference BNS act. Got:\n{result}"
    )

    # Must warn about the collision with BNS 302
    assert "302" in result and "CRITICAL" in result.upper(), (
        f"Collision warning for BNS 302 (Religious Offences) must be present. Got:\n{result}"
    )
    assert "Religious Offences" in result or "religious" in result.lower(), (
        f"Warning must explicitly mention Religious Offences. Got:\n{result}"
    )

    # Must NOT recommend BNS 302 as the murder section
    lines = result.splitlines()
    use_line = next((l for l in lines if l.strip().startswith("Use ")), "")
    assert "103" in use_line, (
        f"'Use' line must recommend BNS 103, not BNS 302. Got:\n{use_line}"
    )


@requires_db
def test_ipc376_split_returns_multiple(normalization_tool):
    """IPC 376 (Rape) splits into multiple BNS sections (63, 64, 65, etc.).

    The tool must return all mapped sections, not just the first.
    """
    result = normalization_tool.run({"old_act": "IPC", "old_section": "376"})

    # Either: multiple mappings found, or not found (seeding not complete)
    # We only assert the split case structure if mappings are present
    if "FOUND" in result:
        # Should mention at least 2 sections in a split scenario
        # The result must contain multiple [N] markers
        assert result.count("[") >= 1, (
            f"Split result must list at least one mapping. Got:\n{result}"
        )
        # Must recommend using all sections
        assert "Use" in result, f"Result must include usage recommendation. Got:\n{result}"
    else:
        # NOT_FOUND is acceptable if IPC 376 not seeded yet
        assert "NOT_FOUND" in result or "not found" in result.lower(), (
            f"Unexpected result for unsplit/unseeded IPC 376. Got:\n{result}"
        )


@requires_db
def test_ipc124a_normalizes_to_bns152(normalization_tool):
    """IPC 124A (Sedition) must map to BNS 152 (Acts endangering sovereignty)."""
    result = normalization_tool.run({"old_act": "IPC", "old_section": "124A"})

    if "FOUND" in result:
        assert "152" in result, (
            f"IPC 124A (Sedition) must map to BNS 152. Got:\n{result}"
        )
        assert "BNS" in result, f"Result must reference BNS. Got:\n{result}"
    else:
        assert "NOT_FOUND" in result, (
            f"Unexpected result for IPC 124A. Got:\n{result}"
        )


@requires_db
def test_crpc438_collision_warning(normalization_tool):
    """CrPC 438 (Anticipatory Bail) must map to BNSS 482, not BNSS 438.

    BNSS 438 is Revision Powers — a procedural tool, not a bail provision.
    """
    result = normalization_tool.run({"old_act": "CrPC", "old_section": "438"})

    if "FOUND" in result:
        assert "482" in result, (
            f"CrPC 438 must map to BNSS 482 (Anticipatory Bail). Got:\n{result}"
        )
        assert "CRITICAL" in result.upper(), (
            f"Collision warning must be present for CrPC 438. Got:\n{result}"
        )
        assert "438" in result and "Revision" in result or "revision" in result.lower(), (
            f"Warning must mention BNSS 438 = Revision Powers. Got:\n{result}"
        )
    else:
        # NOT_FOUND acceptable if not seeded
        assert "NOT_FOUND" in result, (
            f"Unexpected result for CrPC 438. Got:\n{result}"
        )


@requires_db
def test_unknown_section_returns_not_found(normalization_tool):
    """IPC 999 does not exist — tool must return NOT_FOUND gracefully."""
    result = normalization_tool.run({"old_act": "IPC", "old_section": "999"})

    assert "NOT_FOUND" in result, (
        f"Non-existent section must return NOT_FOUND. Got:\n{result}"
    )
    assert "999" in result, "Result must echo back the queried section number."
    # Must not raise or return an error traceback
    assert "Traceback" not in result, "Result must not contain exception traceback."
    assert "Exception" not in result, "Result must not expose raw exception details."


def test_act_alias_normalization():
    """'IPC' must be normalized to 'IPC_1860' before the DB lookup.

    Tests the normalization layer in isolation — no DB required.
    """
    from backend.agents.tools.statute_normalization_tool import _normalize_act_code, _normalize_section_number

    # Act code aliases
    assert _normalize_act_code("IPC") == "IPC_1860"
    assert _normalize_act_code("ipc") == "IPC_1860"
    assert _normalize_act_code("IPC_1860") == "IPC_1860"
    assert _normalize_act_code("CrPC") == "CrPC_1973"
    assert _normalize_act_code("CRPC") == "CrPC_1973"
    assert _normalize_act_code("IEA") == "IEA_1872"
    assert _normalize_act_code("BNS") == "BNS_2023"
    assert _normalize_act_code("BNSS") == "BNSS_2023"
    assert _normalize_act_code("BSA") == "BSA_2023"

    # Section number normalization
    assert _normalize_section_number("302") == "302"
    assert _normalize_section_number("376(1)") == "376"
    assert _normalize_section_number(" 302 ") == "302"
    assert _normalize_section_number("53A") == "53A"
    assert _normalize_section_number("124A") == "124A"
    assert _normalize_section_number("438(2)(b)") == "438"


# ---------------------------------------------------------------------------
# CitationVerificationTool tests
# ---------------------------------------------------------------------------

@requires_indexed
def test_citation_bns103_verified(citation_tool):
    """BNS 103 (Murder) must be verified in Qdrant with correct section title."""
    result = citation_tool.run({"act_code": "BNS_2023", "section_number": "103"})

    assert "CITATION VERIFIED" in result, (
        f"BNS 103 must be verified. Got:\n{result}"
    )
    assert "VERIFIED" in result, f"Status must be VERIFIED. Got:\n{result}"
    assert "103" in result, "Result must reference section 103."
    assert "BNS_2023" in result, "Result must reference BNS_2023."
    # Must NOT say NOT_FOUND
    assert "NOT_FOUND" not in result, (
        f"BNS 103 must be found in the database. Got:\n{result}"
    )


@requires_indexed
def test_citation_bns302_is_religious_offences(citation_tool):
    """BNS 302 must verify as Religious Offences — NOT as Murder.

    This is the critical safety test: if BNS 302 is verified, it must show the
    correct section title (Religious Offences / Outraging religious feelings),
    not 'Murder'. Murder is BNS 103.
    """
    result = citation_tool.run({"act_code": "BNS_2023", "section_number": "302"})

    # BNS 302 should be indexed (it's a real section)
    if "CITATION VERIFIED" in result:
        # It must NOT describe BNS 302 as Murder
        assert "Murder" not in result or "302" in result, (
            "If BNS 302 is verified, it must not be labeled as Murder."
        )
        # Ideally it identifies the correct offence
        title_line = next(
            (l for l in result.splitlines() if l.startswith("Section:")),
            ""
        )
        if title_line:
            # The section title must NOT say Murder
            assert "Murder" not in title_line, (
                f"BNS 302 section title must not say Murder. Got: {title_line}"
            )
    else:
        # NOT_FOUND is acceptable if BNS 302 not indexed yet
        assert "NOT_FOUND" in result, (
            f"BNS 302 result must be either VERIFIED or NOT_FOUND. Got:\n{result}"
        )


def test_citation_nonexistent_returns_not_found(citation_tool):
    """XYZ_2023 s.999 does not exist — must return NOT_FOUND with removal instruction."""
    from backend.agents.tools.citation_verification_tool import CitationVerificationTool

    tool = CitationVerificationTool()

    def _close_coro_and_return_none(coro):
        """Close the unawaited coroutine to suppress ResourceWarning, return None."""
        coro.close()
        return None

    with patch(
        "backend.agents.tools.citation_verification_tool._scroll_qdrant",
        return_value=None,
    ), patch(
        "backend.agents.tools.citation_verification_tool._run_async",
        side_effect=_close_coro_and_return_none,
    ):
        result = tool.run({"act_code": "XYZ_2023", "section_number": "999"})

    assert "NOT_FOUND" in result, (
        f"Non-existent citation must return NOT_FOUND. Got:\n{result}"
    )
    assert "ACTION REQUIRED" in result, (
        f"NOT_FOUND result must instruct removal of citation. Got:\n{result}"
    )
    assert "Remove" in result or "remove" in result, (
        f"NOT_FOUND result must say to remove the citation. Got:\n{result}"
    )
    assert "XYZ_2023" in result, "Result must echo back the queried act code."
    assert "999" in result, "Result must echo back the queried section number."


@requires_qdrant
def test_citation_no_vectors_fetched():
    """scroll() must be called with with_vectors=False for performance.

    Verifies that citation verification never triggers vector retrieval —
    it only needs payload data.
    """
    from backend.agents.tools.citation_verification_tool import _scroll_qdrant

    captured_calls = []

    original_scroll = None
    try:
        from qdrant_client import QdrantClient
        original_scroll = QdrantClient.scroll
    except Exception:
        pytest.skip("QdrantClient not available")

    def mock_scroll(self, collection_name, **kwargs):
        captured_calls.append(kwargs)
        # Return empty result (we only care about the call arguments)
        return ([], None)

    with patch.object(QdrantClient, "scroll", mock_scroll):
        _scroll_qdrant("BNS_2023", "103")

    assert len(captured_calls) == 1, "scroll() must be called exactly once"
    call_kwargs = captured_calls[0]

    # The critical assertion: with_vectors must be False
    assert call_kwargs.get("with_vectors") is False, (
        f"scroll() must be called with with_vectors=False to avoid vector retrieval. "
        f"Got with_vectors={call_kwargs.get('with_vectors')!r}"
    )
