"""Phase 3B — Transition context indexing into Qdrant.

Indexes all ACTIVE law_transition_mappings into the law_transition_context
collection. Each point represents one IPC→BNS (or CrPC→BNSS or IEA→BSA)
mapping, embedded as a human-readable explanation that can be retrieved
when users ask how old law maps to new law.

CRITICAL: The transition note for IPC 302 → BNS 103 MUST include an explicit
warning that BNS 302 = Snatching (a completely different offence). This is
seeded into the transition_note field during Phase 2C activation.

Usage:
    python data/scripts/run_indexing.py --mode transition
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.models.legal_foundation import LawTransitionMapping
from backend.rag.embeddings import BGEM3Embedder, apply_document_prefix, sparse_dict_to_qdrant
from backend.rag.qdrant_setup import COLLECTION_TRANSITION_CONTEXT

logger = logging.getLogger(__name__)

# Act short names for human-readable text construction
_ACT_SHORT = {
    "IPC_1860": "IPC",
    "CrPC_1973": "CrPC",
    "IEA_1872": "IEA",
    "BNS_2023": "BNS",
    "BNSS_2023": "BNSS",
    "BSA_2023": "BSA",
}


@dataclass
class TransitionIndexingReport:
    mappings_found: int = 0
    mappings_indexed: int = 0
    errors: int = 0
    error_details: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def _build_transition_text(mapping: LawTransitionMapping) -> str:
    """Construct the embeddable human-readable transition explanation.

    Example for IPC 302 → BNS 103:
        "IPC Section 302 (Murder) was superseded by BNS Section 103 (Murder)
         effective 2024-07-01. Murder. Renumbered from IPC 302. Punishment
         unchanged: death or imprisonment for life and fine.
         IMPORTANT: BNS Section 302 refers to Snatching — a completely different offence."
    """
    old_short = _ACT_SHORT.get(mapping.old_act, mapping.old_act)
    new_short = _ACT_SHORT.get(mapping.new_act, mapping.new_act) if mapping.new_act else None

    old_title = f" ({mapping.old_section_title})" if mapping.old_section_title else ""
    new_title = f" ({mapping.new_section_title})" if mapping.new_section_title else ""
    new_section_part = (
        f"{new_short} Section {mapping.new_section}{new_title}"
        if mapping.new_section and new_short
        else "no direct replacement (deleted/split)"
    )

    # Effective date
    eff_date = "2024-07-01"  # All BNS/BNSS/BSA effective dates

    transition_verb = {
        "equivalent": "was directly replaced by",
        "modified": "was modified and replaced by",
        "merged_from": "was merged into",
        "split_into": "was split into",
        "deleted": "was deleted without replacement (effective {eff_date})",
        "new": "is a new provision with no prior equivalent",
    }.get(mapping.transition_type, "was superseded by")

    text = (
        f"{old_short} Section {mapping.old_section}{old_title} "
        f"{transition_verb} {new_section_part} effective {eff_date}."
    )

    if mapping.transition_note:
        text += f" {mapping.transition_note}"

    return text


def _build_transition_payload(mapping: LawTransitionMapping) -> Dict[str, Any]:
    """Build Qdrant payload for a transition context point."""
    return {
        "old_act": mapping.old_act,
        "old_section": mapping.old_section,
        "old_section_title": mapping.old_section_title,
        "new_act": mapping.new_act,
        "new_section": mapping.new_section,
        "new_section_title": mapping.new_section_title,
        "transition_type": mapping.transition_type,
        "scope_change": mapping.scope_change,
        "effective_date": "2024-07-01",
        "confidence_score": float(mapping.confidence_score),
    }


class TransitionIndexer:
    """Indexes active law_transition_mappings into law_transition_context."""

    def __init__(
        self,
        session: AsyncSession,
        qdrant_client: Any,
        embedder: BGEM3Embedder,
        batch_size: int = 32,
    ) -> None:
        self._session = session
        self._qdrant = qdrant_client
        self._embedder = embedder
        self._batch_size = batch_size

    async def index_all_active(self) -> TransitionIndexingReport:
        """Index all active transition mappings into law_transition_context.

        Returns:
            TransitionIndexingReport with counts and any errors.
        """
        import time
        t_start = time.monotonic()
        report = TransitionIndexingReport()

        # Fetch all active mappings
        stmt = select(LawTransitionMapping).where(
            LawTransitionMapping.is_active.is_(True)
        )
        result = await self._session.execute(stmt)
        mappings = result.scalars().all()
        report.mappings_found = len(mappings)

        if not mappings:
            logger.warning("transition_indexer: no active mappings found — nothing to index")
            return report

        logger.info("transition_indexer_start: active_mappings=%d", len(mappings))

        # Build texts and payloads
        specs = []
        for mapping in mappings:
            try:
                text = _build_transition_text(mapping)
                payload = _build_transition_payload(mapping)
                specs.append({
                    "point_id": str(mapping.id),
                    "text": text,
                    "payload": payload,
                })
            except Exception as exc:
                report.errors += 1
                detail = f"mapping={mapping.id} error={exc}"
                report.error_details.append(detail)
                logger.error("transition_indexer_build_error: %s", detail, exc_info=True)

        if not specs:
            return report

        # Embed with document prefix
        texts_prefixed = apply_document_prefix([s["text"] for s in specs])
        logger.info("transition_indexer_embedding: count=%d", len(texts_prefixed))

        dense_vecs, sparse_vecs = self._embedder.encode_batch(
            texts_prefixed, batch_size=self._batch_size
        )

        from qdrant_client.models import PointStruct, SparseVector

        points = []
        for i, spec in enumerate(specs):
            sv = sparse_dict_to_qdrant(sparse_vecs[i])
            points.append(
                PointStruct(
                    id=spec["point_id"],
                    vector={
                        "dense": dense_vecs[i],
                        "sparse": SparseVector(**sv),
                    },
                    payload=spec["payload"],
                )
            )

        # Upsert in batches
        for batch_start in range(0, len(points), self._batch_size):
            batch = points[batch_start : batch_start + self._batch_size]
            self._qdrant.upsert(
                collection_name=COLLECTION_TRANSITION_CONTEXT,
                points=batch,
                wait=True,
            )

        report.mappings_indexed = len(points)
        report.duration_seconds = time.monotonic() - t_start
        logger.info(
            "transition_indexer_complete: indexed=%d errors=%d duration=%.1fs",
            report.mappings_indexed, report.errors, report.duration_seconds,
        )
        return report
