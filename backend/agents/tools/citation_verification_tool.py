"""CitationVerificationTool — Phase 4 Safety Gate #2.

Must be called before every response delivery to users.

Verifies that every section cited in the agent's response actually exists in the
indexed database AND that the returned data meets minimum quality requirements.

Two-level verification:
    1. Existence check  — does this act_code + section_number exist?
    2. Data validation  — is the returned payload complete and self-consistent?

Possible outcomes:
    VERIFIED            — exists, data complete, echo check passed
    VERIFIED_INCOMPLETE — exists, but missing section_title or legal text
    NOT_VERIFIED        — not found in Qdrant or PostgreSQL

If a citation cannot be verified → it must be removed from the response.
This is the final safety gate before content reaches users.
"""

from __future__ import annotations

import logging
from typing import Optional

from crewai.tools import BaseTool
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from backend.rag.qdrant_setup import COLLECTION_LEGAL_SECTIONS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payload validation config
# ---------------------------------------------------------------------------

# Fields that MUST be present and non-empty for a VERIFIED result.
# Missing any of these → VERIFIED_INCOMPLETE.
_REQUIRED_FIELDS = ("section_title", "text")

# Fields sourced from alternate keys in Qdrant payloads.
# _get_text() and _get_title() handle these aliases.
_TEXT_KEYS  = ("text", "section_text", "full_text")
_TITLE_KEYS = ("section_title", "title")


# ---------------------------------------------------------------------------
# Lazy sync QdrantClient singleton (used by tool _run — no event loop needed)
# ---------------------------------------------------------------------------

_sync_qdrant_client = None


def _get_sync_qdrant_client():
    """Return a lazy-initialized sync QdrantClient for citation scroll queries."""
    global _sync_qdrant_client
    if _sync_qdrant_client is None:
        from backend.rag.qdrant_setup import get_qdrant_client
        _sync_qdrant_client = get_qdrant_client()
    return _sync_qdrant_client


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class CitationVerificationInput(BaseModel):
    """Input for the CitationVerificationTool."""

    act_code: str
    """Canonical act code: 'BNS_2023', 'BNSS_2023', 'BSA_2023', 'IPC_1860', etc."""

    section_number: str
    """Section number string: '103', '2', '482', '53A'."""


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class CitationVerificationTool(BaseTool):
    """Verify that a cited statute section exists in the indexed database AND
    that the returned data is complete and self-consistent.

    Verification is two-level:
      1. Existence  — Qdrant scroll (primary) → PostgreSQL (fallback)
      2. Data check — echo validation + required field check

    Outcomes:
        VERIFIED            — section found, title + text present, echo passed
        VERIFIED_INCOMPLETE — section found, but title or text is missing
        NOT_VERIFIED        — not found in any source

    Usage::

        tool = CitationVerificationTool()
        result = tool.run({"act_code": "BNS_2023", "section_number": "103"})
        # → VERIFIED with section title, text preview, procedural metadata

        result = tool.run({"act_code": "BNS_2023", "section_number": "302"})
        # → VERIFIED as Religious Offences (NOT Murder — that is BNS_2023 s.103)
    """

    name: str = "CitationVerificationTool"
    description: str = (
        "Verifies that a cited statute section exists in the Neethi AI indexed database "
        "and that the returned payload is complete. "
        "Input: {act_code: str, section_number: str}. "
        "Output: VERIFIED / VERIFIED_INCOMPLETE / NOT_VERIFIED."
    )
    args_schema: type[BaseModel] = CitationVerificationInput

    def _run(self, act_code: str | dict, section_number: str = "") -> str:  # type: ignore[override]
        """Verify a cited statute section exists in the indexed database.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        Async DB operations (Qdrant scroll, PostgreSQL fallback) are executed
        in a dedicated thread with its own event loop via _run_async(), which
        avoids the 'asyncio.run() cannot be called from a running event loop'
        error that occurs when async def _run is used from within uvicorn's loop.

        Handles both CrewAI agent invocations (kwargs unpacked from schema) and
        direct dict calls: tool.run({"act_code": "BNS_2023", "section_number": "103"}).

        Returns:
            Formatted verification result string (VERIFIED / VERIFIED_INCOMPLETE / NOT_VERIFIED).
        """
        # Handle dict input (CrewAI passes the raw dict as first positional arg)
        if isinstance(act_code, dict):
            section_number = act_code.get("section_number", "")
            act_code = act_code.get("act_code", "")

        act_code = act_code.strip()
        section_number = section_number.strip()

        # Normalize short act codes → canonical form (e.g. "BNS" → "BNS_2023").
        # Agents (especially on Mistral fallback) sometimes pass the short form.
        # Qdrant filter uses exact string matching — must match indexed payload value.
        _ACT_CODE_ALIASES = {
            # New criminal codes (in force from 1 July 2024)
            "BNS":   "BNS_2023",
            "BNSS":  "BNSS_2023",
            "BSA":   "BSA_2023",
            # Old criminal codes
            "IPC":   "IPC_1860",
            "CRPC":  "CrPC_1973",
            "IEA":   "IEA_1872",
            # Civil / property / procedural acts (indexed)
            "SRA":   "SRA_1963",    # Specific Relief Act, 1963
            "TPA":   "TPA_1882",    # Transfer of Property Act, 1882
            "CPA":   "CPA_2019",    # Consumer Protection Act, 2019
            "CPC":   "CPC_1908",    # Code of Civil Procedure, 1908
            "LA":    "LA_1963",     # Limitation Act, 1963
        }
        act_code = _ACT_CODE_ALIASES.get(act_code.upper().replace(" ", "").replace("-", ""), act_code)

        logger.info("citation_verification: checking %s s.%s", act_code, section_number)

        # ── Level 1: Existence check ──────────────────────────────────────
        # Primary: sync Qdrant scroll (no embedder, no event loop needed)
        payload = _scroll_qdrant_sync(act_code, section_number)
        source = "Qdrant indexed"

        if payload is None:
            # Fallback: PostgreSQL direct query
            logger.info(
                "citation_verification: not in Qdrant, checking PostgreSQL for %s s.%s",
                act_code, section_number,
            )
            try:
                payload = _query_postgres_sync(act_code, section_number)
                source = "PostgreSQL (not yet indexed)"
            except Exception as exc:
                logger.exception("citation_verification: PostgreSQL fallback failed: %s", exc)
                payload = None

        if payload is None:
            return _format_not_found(act_code, section_number)

        # ── Level 2: Data validation ──────────────────────────────────────
        issues = _validate_payload(payload, act_code, section_number)

        if issues:
            return _format_verified_incomplete(act_code, section_number, payload, source, issues)

        return _format_verified(act_code, section_number, payload, source)


# ---------------------------------------------------------------------------
# Level 2: Payload validation
# ---------------------------------------------------------------------------

def _validate_payload(payload: dict, queried_act: str, queried_section: str) -> list[str]:
    """Validate the returned payload for completeness and self-consistency.

    Checks:
        1. Payload is non-empty (empty dict from Qdrant = corrupted point)
        2. Echo check — act_code and section_number in payload match the query
        3. Required fields — section_title and text must be present and non-empty

    Returns:
        List of issue strings. Empty list means data is clean (VERIFIED).
    """
    issues: list[str] = []

    # ── Check 1: Non-empty payload ────────────────────────────────────────
    if not payload:
        issues.append("payload is empty — Qdrant point exists but has no data")
        return issues  # No point checking further fields on an empty dict

    # ── Check 2: Echo validation ──────────────────────────────────────────
    # Confirm the payload's own act_code and section_number match what was queried.
    # A mismatch would indicate a corrupted or mis-indexed document.
    payload_act = payload.get("act_code", "")
    payload_sec = payload.get("section_number", "")

    if payload_act and payload_act != queried_act:
        issues.append(
            f"echo mismatch: queried act_code='{queried_act}' "
            f"but payload contains act_code='{payload_act}'"
        )
    if payload_sec and payload_sec != queried_section:
        issues.append(
            f"echo mismatch: queried section_number='{queried_section}' "
            f"but payload contains section_number='{payload_sec}'"
        )

    # ── Check 3: Required fields ──────────────────────────────────────────
    # section_title — the agent needs to know *what* section this is
    title = _get_title(payload)
    if not title:
        issues.append("section_title is missing or empty")

    # text — the agent needs actual legal text to confirm context
    text = _get_text(payload)
    if not text:
        issues.append("legal text (text / section_text / full_text) is missing or empty")

    return issues


def _get_title(payload: dict) -> str:
    """Extract section title from payload, trying all known key aliases."""
    for key in _TITLE_KEYS:
        val = payload.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _get_text(payload: dict) -> str:
    """Extract legal text from payload, trying all known key aliases."""
    for key in _TEXT_KEYS:
        val = payload.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


# ---------------------------------------------------------------------------
# Qdrant scroll — primary path (sync, no embedder, no event loop)
# ---------------------------------------------------------------------------

def _scroll_qdrant_sync(act_code: str, section_number: str) -> Optional[dict]:
    """Sync scroll of Qdrant for an exact act_code + section_number match.

    Uses the sync QdrantClient — no event loop required, safe to call from
    any sync context including CrewAI tool _run() methods.

    Returns:
        Payload dict if a non-empty point was found.
        None if not found OR if the Qdrant scroll itself failed.
    """
    try:
        client = _get_sync_qdrant_client()
        hits, _ = client.scroll(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="act_code",       match=MatchValue(value=act_code)),
                    FieldCondition(key="section_number", match=MatchValue(value=section_number)),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,  # payload only — no vector retrieval needed
        )
        if not hits:
            return None

        payload = hits[0].payload
        if not payload:
            logger.warning(
                "citation_verification: Qdrant point found for %s s.%s but payload is empty — "
                "falling through to PostgreSQL",
                act_code, section_number,
            )
            return None

        return dict(payload)

    except Exception as exc:
        logger.warning("citation_verification: sync Qdrant scroll failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# PostgreSQL fallback — sync, via psycopg2 direct query
# ---------------------------------------------------------------------------

def _query_postgres_sync(act_code: str, section_number: str) -> Optional[dict]:
    """Query the sections table synchronously for sections not yet indexed in Qdrant.

    Uses a short-lived sync SQLAlchemy engine so the tool stays fully synchronous.
    This path is rarely hit (only when a section exists in Postgres but hasn't
    been indexed in Qdrant yet), so the engine-creation overhead is acceptable.
    """
    try:
        import os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from backend.db.models.legal_foundation import Section

        # Build sync URL from the async URL (strip the +asyncpg driver specifier)
        async_url: str = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
        )
        sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

        sync_engine = create_engine(sync_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
        try:
            with Session(sync_engine) as session:
                row = session.execute(
                    select(Section).where(
                        Section.act_code == act_code,
                        Section.section_number == section_number,
                    ).limit(1)
                ).scalar_one_or_none()
                if row is None:
                    return None
                return {
                    "act_code":        row.act_code,
                    "section_number":  row.section_number,
                    "section_title":   getattr(row, "section_title", None),
                    "chapter_title":   getattr(row, "chapter_title", None),
                    "era":             getattr(row, "era", None),
                    "applicable_from": str(getattr(row, "applicable_from", "") or ""),
                    "is_offence":      getattr(row, "is_offence", None),
                    "is_cognizable":   getattr(row, "is_cognizable", None),
                    "is_bailable":     getattr(row, "is_bailable", None),
                    "triable_by":      getattr(row, "triable_by", None),
                    "text":            getattr(row, "legal_text", None),
                }
        finally:
            sync_engine.dispose()

    except Exception as exc:
        logger.warning("citation_verification: PostgreSQL sync query failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _format_verified(
    act_code: str,
    section_number: str,
    payload: dict,
    source: str,
) -> str:
    """Format a fully verified result — all required fields present."""
    lines = [
        f"CITATION VERIFIED: {act_code} s.{section_number}",
        f"Status: VERIFIED (source: {source})",
        "",
    ]
    _append_metadata(lines, act_code, section_number, payload)
    return "\n".join(lines)


def _format_verified_incomplete(
    act_code: str,
    section_number: str,
    payload: dict,
    source: str,
    issues: list[str],
) -> str:
    """Format a result where the section exists but payload data is incomplete.

    The agent should treat VERIFIED_INCOMPLETE with caution:
    - The section number is real (it exists in the database)
    - But the data quality is insufficient for confident citation
    - Recommend the agent note the incomplete data to the user
    """
    lines = [
        f"CITATION VERIFIED_INCOMPLETE: {act_code} s.{section_number}",
        f"Status: VERIFIED_INCOMPLETE (source: {source})",
        "Warning: Section exists in database but payload has quality issues:",
    ]
    for issue in issues:
        lines.append(f"  - {issue}")
    lines.append(
        "Recommendation: Cite this section with a note that full details "
        "could not be confirmed. Do not rely on procedural metadata (cognizable/bailable)."
    )
    lines.append("")
    _append_metadata(lines, act_code, section_number, payload)
    return "\n".join(lines)


def _format_not_found(act_code: str, section_number: str) -> str:
    """Format a not-found verification result."""
    return (
        f"CITATION NOT VERIFIED: {act_code} s.{section_number}\n"
        "Status: NOT_FOUND — section does not exist in database.\n"
        "ACTION REQUIRED: Remove this citation from the response."
    )


def _append_metadata(lines: list, act_code: str, section_number: str, payload: dict) -> None:
    """Append available metadata fields to the output lines list (in-place)."""
    title = _get_title(payload)
    if title:
        lines.append(f"Section: {section_number} — {title}")

    act_name = payload.get("act_name") or _act_code_to_name(act_code)
    lines.append(f"Act: {act_name} ({act_code})")

    era = payload.get("era")
    applicable_from = payload.get("applicable_from")
    if era or applicable_from:
        meta_parts = []
        if era:
            meta_parts.append(f"Era: {era}")
        if applicable_from:
            meta_parts.append(f"Applicable from: {applicable_from}")
        lines.append(" | ".join(meta_parts))

    chapter = payload.get("chapter_title") or payload.get("chapter")
    if chapter:
        lines.append(f"Chapter: {chapter}")

    # Procedural classification
    proc_parts = []
    is_offence    = payload.get("is_offence")
    is_cognizable = payload.get("is_cognizable")
    is_bailable   = payload.get("is_bailable")
    triable_by    = payload.get("triable_by")
    if is_offence    is not None: proc_parts.append(f"Is Offence: {'Yes' if is_offence else 'No'}")
    if is_cognizable is not None: proc_parts.append(f"Cognizable: {'Yes' if is_cognizable else 'No'}")
    if is_bailable   is not None: proc_parts.append(f"Bailable: {'Yes' if is_bailable else 'No'}")
    if triable_by:                proc_parts.append(f"Court: {triable_by}")
    if proc_parts:
        lines.append(" | ".join(proc_parts))

    text = _get_text(payload)
    if text:
        preview = text[:200].replace("\n", " ").strip()
        if len(text) > 200:
            preview += "..."
        lines.append(f"Text (preview): {preview}")


def _act_code_to_name(act_code: str) -> str:
    """Return a human-readable act name for a canonical code."""
    _NAMES = {
        # New criminal codes
        "BNS_2023":  "Bharatiya Nyaya Sanhita, 2023",
        "BNSS_2023": "Bharatiya Nagarik Suraksha Sanhita, 2023",
        "BSA_2023":  "Bharatiya Sakshya Adhiniyam, 2023",
        # Old criminal codes
        "IPC_1860":  "Indian Penal Code, 1860",
        "CrPC_1973": "Code of Criminal Procedure, 1973",
        "IEA_1872":  "Indian Evidence Act, 1872",
        # Civil / property / procedural acts
        "SRA_1963":  "Specific Relief Act, 1963",
        "TPA_1882":  "Transfer of Property Act, 1882",
        "CPA_2019":  "Consumer Protection Act, 2019",
        "CPC_1908":  "Code of Civil Procedure, 1908",
        "LA_1963":   "Limitation Act, 1963",
    }
    return _NAMES.get(act_code, act_code)
