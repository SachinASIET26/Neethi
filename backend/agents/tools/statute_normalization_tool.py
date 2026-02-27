"""StatuteNormalizationTool — Phase 4 Safety Gate #1.

Must be called before every HybridSearcher.search() invocation.

Prevents the most dangerous error class in this system: confusing IPC 302 (Murder)
with BNS 302 (Religious Offences). Uses TransitionRepository.lookup_transition()
for deterministic, database-backed statute mapping.

Critical safety guarantee:
    IPC 302 → BNS 103 (Murder), NOT BNS 302 (Religious Offences)
    CrPC 438 → BNSS 482 (Anticipatory Bail), NOT BNSS 438 (Revision Powers)
"""

from __future__ import annotations

import logging
import re
from typing import List

from crewai.tools import BaseTool
from pydantic import BaseModel

from backend.db.repositories.transition_repository import TransitionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Act code alias normalization
# ---------------------------------------------------------------------------

_ACT_ALIASES: dict[str, str] = {
    # IPC
    "IPC": "IPC_1860",
    "IPC1860": "IPC_1860",
    "IPC_1860": "IPC_1860",
    # CrPC
    "CRPC": "CrPC_1973",
    "CrPC": "CrPC_1973",
    "CRPC_1973": "CrPC_1973",
    "CrPC_1973": "CrPC_1973",
    # IEA
    "IEA": "IEA_1872",
    "IEA1872": "IEA_1872",
    "IEA_1872": "IEA_1872",
    # New sanhitas (pass-through — already canonical)
    "BNS": "BNS_2023",
    "BNS_2023": "BNS_2023",
    "BNSS": "BNSS_2023",
    "BNSS_2023": "BNSS_2023",
    "BSA": "BSA_2023",
    "BSA_2023": "BSA_2023",
}

# ---------------------------------------------------------------------------
# Collision warnings — surfaced when the naive new-section number is dangerous
# ---------------------------------------------------------------------------

_COLLISION_WARNINGS: dict[tuple[str, str], str] = {
    ("IPC_1860", "302"): (
        "CRITICAL: BNS 302 = Religious Offences (Blasphemy etc.). "
        "Use BNS 103 for Murder — a completely different offence."
    ),
    ("CrPC_1973", "438"): (
        "CRITICAL: BNSS 438 = Revision Powers (not bail). "
        "Use BNSS 482 for Anticipatory Bail."
    ),
}


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class StatuteNormalizationInput(BaseModel):
    """Input for the StatuteNormalizationTool."""

    old_act: str
    """Old act code: 'IPC', 'IPC_1860', 'CrPC', 'CrPC_1973', 'IEA', 'IEA_1872'."""

    old_section: str
    """Old section number string: '302', '376', '376(1)', '53A', '124A'."""


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class StatuteNormalizationTool(BaseTool):
    """Normalize old statute references (IPC/CrPC/IEA) to new equivalents (BNS/BNSS/BSA).

    Must be called before every Qdrant search. Prevents dangerous false-friend
    confusions such as IPC 302 (Murder) being mapped to BNS 302 (Religious Offences).

    Usage::

        tool = StatuteNormalizationTool()
        result = tool.run({"old_act": "IPC", "old_section": "302"})
        # Returns: BNS 103 + collision warning about BNS 302
    """

    name: str = "StatuteNormalizationTool"
    description: str = (
        "Converts old Indian statute references (IPC, CrPC, IEA) to their new equivalents "
        "(BNS, BNSS, BSA). Must be called before any Qdrant search query. "
        "Input: {old_act: str, old_section: str}. "
        "Output: normalized section(s) with collision warnings where applicable."
    )
    args_schema: type[BaseModel] = StatuteNormalizationInput

    def _run(self, old_act: str | dict, old_section: str = "") -> str:  # type: ignore[override]
        """Normalize old statute references to new equivalents.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        The async DB lookup (_lookup) is executed in a dedicated thread with its
        own event loop via _run_async(), avoiding the 'asyncio.run() cannot be
        called from a running event loop' error that arises when async def _run
        is used from within uvicorn's event loop.

        Handles both CrewAI agent invocations (kwargs unpacked from schema) and
        direct dict calls: tool.run({"old_act": "IPC", "old_section": "302"}).

        Args:
            old_act:     Act code string ('IPC', 'CrPC') OR a dict with both fields.
            old_section: Section number, e.g. '302', '376(1)'. Unused when old_act is dict.

        Returns:
            Formatted string with normalization results and any collision warnings.
        """
        # Handle dict input (CrewAI passes the raw dict as first positional arg)
        if isinstance(old_act, dict):
            old_section = old_act.get("old_section", "")
            old_act = old_act.get("old_act", "")

        # --- Normalize inputs ---
        canonical_act = _normalize_act_code(old_act)
        canonical_section = _normalize_section_number(old_section)

        logger.info(
            "statute_normalization: input=%s s.%s → canonical=%s s.%s",
            old_act, old_section, canonical_act, canonical_section,
        )

        # --- DB lookup (sync — no threads, no event loop needed) ---
        try:
            results: List[TransitionResult] = _lookup_sync(canonical_act, canonical_section)
        except Exception as exc:
            logger.exception("statute_normalization: DB lookup failed: %s", exc)
            return (
                f"STATUTE NORMALIZATION: {canonical_act} s.{canonical_section}\n"
                f"Status: ERROR — database lookup failed: {exc}\n"
                "Proceed with caution. Use original reference but verify manually."
            )

        # --- Format output ---
        return _format_output(canonical_act, canonical_section, results)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_act_code(raw: str) -> str:
    """Map act aliases to canonical codes.

    'IPC' → 'IPC_1860', 'CrPC' → 'CrPC_1973', etc.
    Unknown codes are returned uppercased (pass-through).
    """
    key = raw.strip().upper().replace("-", "_").replace(" ", "_")
    # Try direct lookup (handles mixed case like 'CrPC')
    for alias, canonical in _ACT_ALIASES.items():
        if alias.upper() == key:
            return canonical
    return raw.strip()


def _normalize_section_number(raw: str) -> str:
    """Strip parentheticals and whitespace from a section number.

    '376(1)' → '376', ' 302 ' → '302', '53A' → '53A'
    """
    return re.sub(r"\([^)]*\)", "", raw).strip()


async def _lookup(act: str, section: str) -> List[TransitionResult]:
    """Async DB lookup via TransitionRepository.

    Creates a fresh engine per call to avoid asyncpg pool cleanup errors.
    Called directly with await from async _run() — no thread wrapper needed.
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from backend.db.database import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
    try:
        SessionLocal = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            repo = TransitionRepository(session)
            return await repo.lookup_transition(act, section)
    finally:
        await engine.dispose()


def _lookup_sync(act: str, section: str) -> List[TransitionResult]:
    """Sync DB lookup via TransitionRepository — no event loop required.

    Used by the synchronous tool _run() so CrewAI can call it without
    threading or event loop gymnastics. Uses psycopg2 (sync driver) via
    a short-lived SQLAlchemy engine created and disposed per call.

    The per-call engine overhead is negligible: this function is only called
    once per agent step (statute normalization is a single point-lookup, not
    a hot path), and the connection is returned to the pool immediately.
    """
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    async_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
    )
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    engine = create_engine(sync_url, echo=False, pool_size=1, max_overflow=0)
    try:
        SyncSession = sessionmaker(bind=engine, expire_on_commit=False)
        with SyncSession() as session:
            from sqlalchemy import select as sa_select
            from backend.db.models.legal_foundation import LawTransitionMapping

            rows = session.execute(
                sa_select(LawTransitionMapping).where(
                    LawTransitionMapping.old_act == act,
                    LawTransitionMapping.old_section == section,
                    LawTransitionMapping.is_active == True,
                )
            ).scalars().all()

            return [
                TransitionResult(
                    mapping_id=row.id,
                    old_act=row.old_act,
                    old_section=row.old_section,
                    old_section_title=row.old_section_title,
                    new_act=row.new_act,
                    new_section=row.new_section,
                    new_section_title=row.new_section_title,
                    transition_type=row.transition_type,
                    confidence_score=float(row.confidence_score or 1.0),
                    transition_note=row.transition_note,
                    scope_change=row.scope_change,
                    is_active=row.is_active,
                )
                for row in rows
            ]
    finally:
        engine.dispose()


def _format_output(
    act: str,
    section: str,
    results: List[TransitionResult],
) -> str:
    """Format the normalization results as a human-readable string for the agent."""
    header = f"STATUTE NORMALIZATION: {act} s.{section}"

    if not results:
        lines = [
            header,
            "Status: NOT_FOUND — no active mapping exists.",
            "Proceed with direct search using original reference if applicable.",
        ]
        return "\n".join(lines)

    lines = [
        header,
        f"Status: FOUND — {len(results)} mapping(s)",
        "",
    ]

    for i, r in enumerate(results, start=1):
        new_ref = f"{r.new_act} s.{r.new_section}" if r.new_act and r.new_section else "N/A"
        title = f' "{r.new_section_title}"' if r.new_section_title else ""
        lines.append(f"[{i}] {new_ref}{title}")
        lines.append(f"    Type: {r.transition_type} | Confidence: {r.confidence_score:.2f}")
        if r.transition_note:
            lines.append(f"    Note: {r.transition_note}")
        if r.scope_change:
            lines.append(f"    Scope change: {r.scope_change}")

        # Inject collision warning if applicable
        collision = _COLLISION_WARNINGS.get((act, section))
        if collision:
            lines.append(f"    CRITICAL WARNING: {collision}")

    lines.append("")

    # Recommend which section(s) to use in Qdrant
    if len(results) == 1:
        r = results[0]
        lines.append(f"Use {r.new_act} s.{r.new_section} in all Qdrant queries.")
    else:
        refs = ", ".join(
            f"{r.new_act} s.{r.new_section}"
            for r in results
            if r.new_act and r.new_section
        )
        lines.append(f"Use all mapped sections in Qdrant queries: {refs}")

    return "\n".join(lines)
