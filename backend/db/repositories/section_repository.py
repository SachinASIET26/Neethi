"""Async repository for all section-related database operations.

This module is the ONLY layer that writes to:
- sections table
- sub_sections table
- extraction_audit table
- human_review_queue table

All operations use INSERT ... ON CONFLICT ... DO UPDATE (upsert) to ensure
idempotency across re-runs of the ingestion pipeline.

The get_sections_for_qdrant_indexing method is the gate: only sections
with extraction_confidence >= 0.7 and no pending human review row pass through.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, exists, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.legal_foundation import (
    Chapter,
    ExtractionAudit,
    HumanReviewQueue,
    Section,
    SubSection,
    LawTransitionMapping,
)

logger = logging.getLogger(__name__)


class SectionRepository:
    """All section-related database writes and reads for the ingestion pipeline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Section upsert
    # ------------------------------------------------------------------

    async def upsert_section(self, section_data: Dict[str, Any]) -> _uuid_mod.UUID:
        """Insert or update a section row.

        Uses INSERT ... ON CONFLICT (act_code, section_number) DO UPDATE.
        Returns the UUID of the inserted or existing section row.

        Args:
            section_data: dict matching the sections table columns.
        """
        stmt = (
            pg_insert(Section)
            .values(**section_data)
            .on_conflict_do_update(
                constraint="uq_sections_act_num",
                set_={
                    "section_title": section_data.get("section_title"),
                    "legal_text": section_data.get("legal_text"),
                    "chapter_id": section_data.get("chapter_id"),
                    "status": section_data.get("status", "active"),
                    "applicable_from": section_data.get("applicable_from"),
                    "era": section_data.get("era"),
                    "has_subsections": section_data.get("has_subsections", False),
                    "has_illustrations": section_data.get("has_illustrations", False),
                    "has_explanations": section_data.get("has_explanations", False),
                    "has_provisos": section_data.get("has_provisos", False),
                    "extraction_confidence": section_data.get("extraction_confidence", 1.0),
                    "is_offence": section_data.get("is_offence", False),
                    "section_number_int": section_data.get("section_number_int"),
                    "section_number_suffix": section_data.get("section_number_suffix"),
                },
            )
            .returning(Section.id)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        section_id: _uuid_mod.UUID = row[0]
        logger.debug(
            "upsert_section: act=%s section=%s id=%s",
            section_data.get("act_code"),
            section_data.get("section_number"),
            section_id,
        )
        return section_id

    # ------------------------------------------------------------------
    # SubSection upsert
    # ------------------------------------------------------------------

    async def upsert_sub_section(self, sub_section_data: Dict[str, Any]) -> _uuid_mod.UUID:
        """Insert or update a sub_section row.

        Uses INSERT ... ON CONFLICT (section_id, sub_section_label) DO UPDATE.
        Returns the UUID of the inserted or existing sub_section row.
        """
        stmt = (
            pg_insert(SubSection)
            .values(**sub_section_data)
            .on_conflict_do_update(
                constraint="uq_sub_sections_section_label",
                set_={
                    "legal_text": sub_section_data.get("legal_text"),
                    "sub_section_type": sub_section_data.get("sub_section_type"),
                    "position_order": sub_section_data.get("position_order"),
                },
            )
            .returning(SubSection.id)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Transition mapping upsert
    # ------------------------------------------------------------------

    async def upsert_transition_mapping(
        self, mapping_data: Dict[str, Any]
    ) -> _uuid_mod.UUID:
        """Insert or update a law_transition_mappings row.

        Uses INSERT ... ON CONFLICT (old_act, old_section, new_act, new_section) DO UPDATE.
        Note: is_active is NOT updated on conflict — it must be set by a human reviewer.
        Returns the UUID of the inserted or existing mapping row.
        """
        stmt = (
            pg_insert(LawTransitionMapping)
            .values(**mapping_data)
            .on_conflict_do_update(
                index_elements=["old_act", "old_section", "new_act", "new_section"],
                set_={
                    "transition_type": mapping_data.get("transition_type"),
                    "transition_note": mapping_data.get("transition_note"),
                    "confidence_score": mapping_data.get("confidence_score", 0.75),
                    # is_active deliberately NOT updated — requires human approval
                },
            )
            .returning(LawTransitionMapping.id)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Extraction audit write
    # ------------------------------------------------------------------

    async def write_extraction_audit(self, audit_data: Dict[str, Any]) -> None:
        """Insert an extraction_audit record.

        Audit records are append-only — not upserted.
        Each pipeline run creates new audit rows (pipeline_version tracks reruns).
        """
        stmt = pg_insert(ExtractionAudit).values(**audit_data)
        await self._session.execute(stmt)
        logger.debug(
            "write_extraction_audit: act=%s section=%s confidence=%.2f",
            audit_data.get("act_code"),
            audit_data.get("section_number"),
            audit_data.get("extraction_confidence", 1.0),
        )

    # ------------------------------------------------------------------
    # Human review queue
    # ------------------------------------------------------------------

    async def add_to_review_queue(
        self,
        act_code: str,
        section_number: str,
        reason: str,
        raw_text: str,
        cleaned_text: str,
        extraction_confidence: float,
        section_id: Optional[_uuid_mod.UUID] = None,
    ) -> None:
        """Add a section to the human_review_queue.

        Args:
            act_code: canonical act code, e.g. "BNS_2023".
            section_number: e.g. "103".
            reason: human-readable explanation of why review is needed.
            raw_text: raw text from PDF extractor (before cleaning).
            cleaned_text: text after cleaning rules applied.
            extraction_confidence: the computed confidence score (0.0 to 1.0).
            section_id: UUID of the sections row if it was inserted; None otherwise.
        """
        entry = HumanReviewQueue(
            section_id=section_id,
            act_code=act_code,
            section_number=section_number,
            reason=reason,
            raw_text=raw_text[:10000] if raw_text else None,   # cap to avoid huge blobs
            cleaned_text=cleaned_text[:10000] if cleaned_text else None,
            extraction_confidence=extraction_confidence,
            status="pending",
        )
        self._session.add(entry)
        logger.warning(
            "add_to_review_queue: act=%s section=%s confidence=%.2f reason=%s",
            act_code, section_number, extraction_confidence, reason[:100],
        )

    # ------------------------------------------------------------------
    # Chapter upsert
    # ------------------------------------------------------------------

    async def upsert_chapter(self, chapter_data: Dict[str, Any]) -> _uuid_mod.UUID:
        """Insert or update a chapter row.

        Uses INSERT ... ON CONFLICT (act_code, chapter_number) DO UPDATE.
        Returns the UUID of the inserted or existing chapter row.
        """
        stmt = (
            pg_insert(Chapter)
            .values(**chapter_data)
            .on_conflict_do_update(
                constraint="uq_chapters_act_number",
                set_={
                    "chapter_title": chapter_data["chapter_title"],
                    "domain": chapter_data.get("domain"),
                    "section_count": chapter_data.get("section_count"),
                },
            )
            .returning(Chapter.id)
        )
        result = await self._session.execute(stmt)
        chapter_id: _uuid_mod.UUID = result.scalar_one()
        logger.debug(
            "upsert_chapter: act=%s chapter=%s id=%s",
            chapter_data["act_code"], chapter_data["chapter_number"], chapter_id,
        )
        return chapter_id

    # ------------------------------------------------------------------
    # Chapter ID lookup helper
    # ------------------------------------------------------------------

    async def get_chapter_id(
        self, act_code: str, chapter_number: str
    ) -> Optional[_uuid_mod.UUID]:
        """Look up the UUID of a chapter by (act_code, chapter_number).

        Returns None if the chapter row does not exist (pipeline can still proceed
        without a chapter FK — the section will have chapter_id = NULL).
        """
        stmt = select(Chapter.id).where(
            Chapter.act_code == act_code,
            Chapter.chapter_number == chapter_number,
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Qdrant indexing gate
    # ------------------------------------------------------------------

    async def get_sections_for_qdrant_indexing(
        self, act_code: str
    ) -> List[Dict[str, Any]]:
        """Return sections eligible for Qdrant indexing.

        Criteria:
        - act_code matches
        - extraction_confidence >= 0.7
        - section_id NOT IN (SELECT section_id FROM human_review_queue WHERE status = 'pending')

        Returns:
            List of dicts with all column values from the sections table.
        """
        # NOT EXISTS avoids the SQL NOT IN + NULL trap:
        # NOT IN (subquery) returns NULL (not TRUE) for every row when the subquery
        # contains any NULL value — causing all sections to be excluded.
        # NOT EXISTS with a correlated subquery is NULL-safe.
        pending_exists = (
            select(HumanReviewQueue.id)
            .where(
                HumanReviewQueue.section_id == Section.id,
                HumanReviewQueue.status == "pending",
            )
            .correlate(Section)
            .exists()
        )

        stmt = (
            select(Section)
            .where(
                Section.act_code == act_code,
                Section.extraction_confidence >= 0.7,
                ~pending_exists,
            )
            .order_by(Section.section_number_int.asc().nullsfirst())
        )

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        sections_list = []
        for s in rows:
            sections_list.append({
                "id": s.id,
                "act_code": s.act_code,
                "chapter_id": s.chapter_id,
                "section_number": s.section_number,
                "section_number_int": s.section_number_int,
                "section_title": s.section_title,
                "legal_text": s.legal_text,
                "status": s.status,
                "applicable_from": s.applicable_from,
                "era": s.era,
                "is_offence": s.is_offence,
                "is_cognizable": s.is_cognizable,
                "is_bailable": s.is_bailable,
                "triable_by": s.triable_by,
                "punishment_type": s.punishment_type,
                "punishment_max_years": s.punishment_max_years,
                "has_subsections": s.has_subsections,
                "has_illustrations": s.has_illustrations,
                "has_explanations": s.has_explanations,
                "has_provisos": s.has_provisos,
                "extraction_confidence": s.extraction_confidence,
                "qdrant_indexed": s.qdrant_indexed,
                "applicable_until": s.applicable_until,
            })

        logger.info(
            "get_sections_for_qdrant_indexing: act=%s eligible=%d",
            act_code, len(sections_list),
        )
        return sections_list

    # ------------------------------------------------------------------
    # Indexer support: chapters, sub-sections, transitions
    # ------------------------------------------------------------------

    async def get_chapters_for_act(
        self, act_code: str
    ) -> Dict[str, Dict[str, Any]]:
        """Return all chapters for an act keyed by str(chapter_id).

        Used by the indexer to enrich Qdrant payloads with chapter metadata
        without N+1 database queries.

        Returns:
            Dict mapping str(chapter_uuid) -> {chapter_number, chapter_number_int,
            chapter_title, domain}
        """
        stmt = select(Chapter).where(Chapter.act_code == act_code)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return {
            str(ch.id): {
                "chapter_number": ch.chapter_number,
                "chapter_number_int": ch.chapter_number_int,
                "chapter_title": ch.chapter_title,
                "domain": ch.domain,
            }
            for ch in rows
        }

    async def get_sub_sections_for_act(
        self, act_code: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return all sub-sections for an act keyed by str(section_id).

        Used by the indexer for scenarios B, C, D (sections with sub-sections).

        Returns:
            Dict mapping str(section_uuid) -> list of sub-section dicts,
            ordered by position_order ascending.
        """
        stmt = (
            select(SubSection)
            .where(SubSection.act_code == act_code)
            .order_by(SubSection.section_id, SubSection.position_order)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for ss in rows:
            key = str(ss.section_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append({
                "id": ss.id,
                "section_id": ss.section_id,
                "act_code": ss.act_code,
                "parent_section_number": ss.parent_section_number,
                "sub_section_label": ss.sub_section_label,
                "sub_section_type": ss.sub_section_type,
                "legal_text": ss.legal_text,
                "position_order": ss.position_order,
            })
        return grouped

    async def get_active_transitions_for_act(
        self, act_code: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return active transition mappings for a new act, keyed by new_section.

        Used by the indexer to denormalize supersedes_act / supersedes_section
        into Qdrant payloads, avoiding PostgreSQL round-trips during retrieval.

        Returns:
            Dict mapping section_number -> list of transition dicts.
            Most sections have one mapping; split cases have multiple.
        """
        stmt = select(LawTransitionMapping).where(
            LawTransitionMapping.new_act == act_code,
            LawTransitionMapping.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for m in rows:
            if m.new_section not in grouped:
                grouped[m.new_section] = []
            grouped[m.new_section].append({
                "old_act": m.old_act,
                "old_section": m.old_section,
                "old_section_title": m.old_section_title,
                "transition_type": m.transition_type,
                "confidence_score": m.confidence_score,
            })
        return grouped

    async def mark_qdrant_indexed_batch(
        self, section_ids: List[_uuid_mod.UUID]
    ) -> None:
        """Set qdrant_indexed = TRUE for a batch of sections.

        Called by the indexer after successfully upserting points to Qdrant.

        Args:
            section_ids: List of UUID values from the sections table.
        """
        if not section_ids:
            return
        stmt = (
            update(Section)
            .where(Section.id.in_(section_ids))
            .values(qdrant_indexed=True)
        )
        await self._session.execute(stmt)
        logger.info(
            "mark_qdrant_indexed_batch: marked %d sections as indexed",
            len(section_ids),
        )
