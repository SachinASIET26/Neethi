"""StatuteNormalizationTool data access layer.

This repository is the ONLY data access layer the StatuteNormalizationTool will use.
It is deterministic — no fuzzy matching, no semantic search, no LLM calls.

The safety guarantee: IPC 302 → BNS 103 (Murder) — never BNS 302 (Religious Offences).
This is enforced by querying law_transition_mappings WHERE is_active = TRUE, which
requires prior human approval of each mapping.

Until Phase 2C (human review activation), all lookup_transition() calls return
empty lists (is_active = FALSE by default). This is by design — the system is
conservative: no wrong answer is better than a wrong answer.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.legal_foundation import LawTransitionMapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TransitionResult:
    """Represents a single row from law_transition_mappings."""

    mapping_id: _uuid_mod.UUID
    old_act: str
    old_section: str
    old_section_title: Optional[str]
    new_act: Optional[str]
    new_section: Optional[str]
    new_section_title: Optional[str]
    transition_type: str
    transition_note: Optional[str]
    scope_change: Optional[str]
    confidence_score: float
    is_active: bool


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class TransitionRepository:
    """Data access layer for law transition lookups.

    All lookup methods operate only on is_active = TRUE rows to ensure that
    only human-verified mappings are surfaced to the agent layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Forward lookup: old section → all matching new sections
    # ------------------------------------------------------------------

    async def lookup_transition(
        self,
        old_act: str,
        old_section: str,
    ) -> List[TransitionResult]:
        """Find all active transition mappings for an old section.

        The split case (IPC 376 → BNS 63, 64, 65...) returns multiple rows.
        The caller (StatuteNormalizationTool) receives all rows and decides which
        new section(s) are relevant to the query.

        Args:
            old_act:     canonical old act code, e.g. "IPC_1860".
            old_section: old section number string, e.g. "302", "376".

        Returns:
            List of TransitionResult (may be empty if no active mapping exists).
        """
        stmt = select(LawTransitionMapping).where(
            LawTransitionMapping.old_act == old_act,
            LawTransitionMapping.old_section == old_section,
            LawTransitionMapping.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_result(r) for r in rows]

    # ------------------------------------------------------------------
    # Reverse lookup: new section → what old section it replaces
    # ------------------------------------------------------------------

    async def lookup_reverse(
        self,
        new_act: str,
        new_section: str,
    ) -> Optional[TransitionResult]:
        """Find the primary old section that the given new section replaces.

        For split cases (many new sections from one old), returns the most
        recent active row (highest confidence_score, then created_at).
        Returns None if no active mapping found.

        Args:
            new_act:     canonical new act code, e.g. "BNS_2023".
            new_section: new section number string, e.g. "103".
        """
        stmt = (
            select(LawTransitionMapping)
            .where(
                LawTransitionMapping.new_act == new_act,
                LawTransitionMapping.new_section == new_section,
                LawTransitionMapping.is_active.is_(True),
            )
            .order_by(
                LawTransitionMapping.confidence_score.desc(),
                LawTransitionMapping.created_at.desc(),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_result(row) if row else None

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    async def get_pending_review_count(self) -> int:
        """Return the count of transition mappings that have not yet been activated.

        Pending = is_active = FALSE (all freshly ingested mappings start this way).
        """
        stmt = select(func.count(LawTransitionMapping.id)).where(
            LawTransitionMapping.is_active.is_(False)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() or 0

    async def get_active_count(self) -> int:
        """Return the count of activated (human-verified) transition mappings."""
        stmt = select(func.count(LawTransitionMapping.id)).where(
            LawTransitionMapping.is_active.is_(True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() or 0

    # ------------------------------------------------------------------
    # Activation (Phase 2C — human review step)
    # ------------------------------------------------------------------

    async def approve_mapping(
        self,
        mapping_id: _uuid_mod.UUID,
        reviewer_id: str,
    ) -> None:
        """Activate a single transition mapping after human verification.

        Sets is_active = TRUE, approved_by, approved_at.
        Only mappings that pass this step are surfaced to the agent layer.

        Args:
            mapping_id:  UUID of the law_transition_mappings row.
            reviewer_id: Legal reviewer's identifier (name, email, etc.).
        """
        stmt = (
            update(LawTransitionMapping)
            .where(LawTransitionMapping.id == mapping_id)
            .values(
                is_active=True,
                approved_by=reviewer_id,
                approved_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)
        logger.info("approve_mapping: mapping_id=%s approved_by=%s", mapping_id, reviewer_id)

    # ------------------------------------------------------------------
    # User voting (community accuracy feedback)
    # ------------------------------------------------------------------

    async def record_user_vote(
        self,
        mapping_id: _uuid_mod.UUID,
        vote: str,
    ) -> None:
        """Record a user vote on a transition mapping.

        Args:
            mapping_id: UUID of the mapping row.
            vote:       "correct" or "wrong".

        If user_wrong_votes reaches 3, the mapping is auto-demoted:
        is_active is set to FALSE and confidence_score drops to 0.3.
        This is a conservative safety rule — wrong votes from users
        signal a potentially dangerous mapping.
        """
        if vote not in ("correct", "wrong"):
            raise ValueError(f"vote must be 'correct' or 'wrong', got {vote!r}")

        # Fetch current state
        stmt = select(LawTransitionMapping).where(LawTransitionMapping.id == mapping_id)
        result = await self._session.execute(stmt)
        mapping = result.scalar_one_or_none()
        if mapping is None:
            logger.warning("record_user_vote: mapping_id=%s not found", mapping_id)
            return

        if vote == "correct":
            mapping.user_correct_votes += 1
        else:
            mapping.user_wrong_votes += 1

        # Auto-demotion rule: 3 wrong votes → deactivate
        if mapping.user_wrong_votes >= 3 and not mapping.auto_demoted:
            mapping.auto_demoted = True
            mapping.is_active = False
            mapping.confidence_score = 0.3
            logger.warning(
                "record_user_vote: AUTO-DEMOTED mapping_id=%s after %d wrong votes. "
                "old_act=%s old_section=%s new_act=%s new_section=%s",
                mapping_id,
                mapping.user_wrong_votes,
                mapping.old_act,
                mapping.old_section,
                mapping.new_act,
                mapping.new_section,
            )

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    @staticmethod
    def _to_result(row: LawTransitionMapping) -> TransitionResult:
        return TransitionResult(
            mapping_id=row.id,
            old_act=row.old_act,
            old_section=row.old_section,
            old_section_title=row.old_section_title,
            new_act=row.new_act,
            new_section=row.new_section,
            new_section_title=row.new_section_title,
            transition_type=row.transition_type,
            transition_note=row.transition_note,
            scope_change=row.scope_change,
            confidence_score=row.confidence_score,
            is_active=row.is_active,
        )
