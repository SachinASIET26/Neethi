"""Qdrant indexing pipeline for Neethi AI legal sections.

Reads clean section data from PostgreSQL, embeds with BGE-M3, and upserts
to the Qdrant legal_sections and legal_sub_sections collections.

Source of truth: PostgreSQL sections table.
Do NOT re-read from JSON files. Do NOT re-extract from PDFs.

Chunking scenarios (Part 5.5):
    A: tokens <= 400        → 1 point in legal_sections (no sub-section indexing)
    B: 400 < tokens <= 1200 → 1 point in legal_sections + sub-sections indexed
    C: tokens > 1200        → overlapping chunks in legal_sections + sub-sections indexed
    D: Definitions section  → forced sub-section granular (regardless of length)

Token count approximation: len(text.split()) * 1.3
This avoids a tokenizer dependency and is sufficient for the chunking decision.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.repositories.section_repository import SectionRepository
from backend.rag.embeddings import BGEM3Embedder, apply_document_prefix, sparse_dict_to_qdrant
from backend.rag.qdrant_setup import (
    COLLECTION_LEGAL_SECTIONS,
    COLLECTION_LEGAL_SUB_SECTIONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_APPROX_FACTOR = 1.3      # len(text.split()) * this ≈ token count
SCENARIO_A_MAX = 400           # tokens
SCENARIO_B_MAX = 1200          # tokens
CHUNK_MAX_TOKENS = 600         # max tokens per chunk in Scenario C
CHUNK_OVERLAP_TOKENS = 75      # "overlap" context (section header in every chunk)

# Definitions section numbers (forced to Scenario D)
DEFINITIONS_SECTIONS = {"2"}   # BNS s.2, BNSS s.2, BSA s.1 (BSA uses 1)
BSA_DEFINITIONS_SECTION = "1"

# BGE-M3 asymmetric embedding prefix (documents only, never queries)
DOCUMENT_PREFIX = "Represent this Indian legal provision for retrieval: "


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class IndexingReport:
    """Summary returned by index_act() after indexing completes."""

    act_code: str
    sections_eligible: int = 0
    sections_indexed: int = 0
    section_points_created: int = 0
    sub_sections_indexed: int = 0
    errors: int = 0
    error_details: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def summary(self) -> str:
        return (
            f"act={self.act_code} "
            f"eligible={self.sections_eligible} "
            f"indexed={self.sections_indexed} "
            f"section_points={self.section_points_created} "
            f"sub_sections={self.sub_sections_indexed} "
            f"errors={self.errors} "
            f"duration={self.duration_seconds:.1f}s"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _token_count(text: str) -> float:
    """Approximate token count. Do not use a real tokenizer — approximation suffices."""
    return len(text.split()) * TOKEN_APPROX_FACTOR


def _is_definitions_section(act_code: str, section_number: str) -> bool:
    """Return True if this section is the Definitions section (Scenario D)."""
    if act_code == "BSA_2023":
        return section_number == BSA_DEFINITIONS_SECTION
    return section_number in DEFINITIONS_SECTIONS


def _date_to_str(d: Any) -> Optional[str]:
    """Convert date/datetime to ISO string for Qdrant payload."""
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _build_section_payload(
    section: Dict[str, Any],
    chapter: Optional[Dict[str, Any]],
    transitions: List[Dict[str, Any]],
    chunk_type: str = "full_section",
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> Dict[str, Any]:
    """Build the Qdrant payload dict for a legal_sections point."""

    # Transition data: denormalize first active mapping
    supersedes_act = None
    supersedes_section = None
    transition_type = None
    if transitions:
        t = transitions[0]
        supersedes_act = t.get("old_act")
        supersedes_section = t.get("old_section")
        transition_type = t.get("transition_type")

    return {
        # Act metadata
        "act_code": section["act_code"],
        "section_number": section["section_number"],
        "section_title": section.get("section_title") or "",
        # Chapter metadata (may be None for uncategorized sections)
        "chapter_number": chapter["chapter_number"] if chapter else None,
        "chapter_number_int": chapter["chapter_number_int"] if chapter else None,
        "chapter_title": chapter["chapter_title"] if chapter else None,
        "legal_domain": (chapter["domain"] if chapter else None) or _infer_domain(section["act_code"]),
        "sub_domain": None,  # not in current schema; populated in future phase
        # Temporal
        "era": section["era"],
        "status": section["status"],
        "applicable_from": _date_to_str(section.get("applicable_from")),
        "applicable_until": _date_to_str(section.get("applicable_until")),
        # Offence classification
        "is_offence": bool(section.get("is_offence", False)),
        "is_cognizable": section.get("is_cognizable"),
        "is_bailable": section.get("is_bailable"),
        "triable_by": section.get("triable_by"),
        "punishment_type": section.get("punishment_type"),
        "punishment_max_years": section.get("punishment_max_years"),
        # Structure flags
        "has_subsections": bool(section.get("has_subsections", False)),
        "has_illustrations": bool(section.get("has_illustrations", False)),
        "has_explanations": bool(section.get("has_explanations", False)),
        "has_provisos": bool(section.get("has_provisos", False)),
        # Transition mapping (denormalized)
        "supersedes_act": supersedes_act,
        "supersedes_section": supersedes_section,
        "transition_type": transition_type,
        # Chunking metadata
        "chunk_type": chunk_type,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        # Quality
        "extraction_confidence": section.get("extraction_confidence", 1.0),
        "needs_review": False,
        "ingestion_timestamp": datetime.utcnow().isoformat(),
    }


def _build_sub_section_payload(
    sub_section: Dict[str, Any],
    parent_section: Dict[str, Any],
    chapter: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the Qdrant payload dict for a legal_sub_sections point."""
    label = sub_section["sub_section_label"]
    ss_type = sub_section["sub_section_type"]

    return {
        # Identity
        "act_code": sub_section["act_code"],
        "section_number": sub_section["parent_section_number"],
        "sub_section_label": label,
        "sub_section_type": ss_type,
        "position_order": sub_section["position_order"],
        # Parent context
        "parent_section_id": str(parent_section["id"]),
        "parent_section_title": parent_section.get("section_title") or "",
        "parent_chapter_title": chapter["chapter_title"] if chapter else None,
        # Temporal
        "era": parent_section["era"],
        "status": parent_section["status"],
        "applicable_from": _date_to_str(parent_section.get("applicable_from")),
        "applicable_until": _date_to_str(parent_section.get("applicable_until")),
        # Domain
        "legal_domain": (chapter["domain"] if chapter else None) or _infer_domain(sub_section["act_code"]),
        "sub_domain": None,
        # Sub-section type booleans
        "is_exception": ss_type == "exception",
        "is_definition": ss_type in ("numbered", "lettered") and parent_section.get("section_number") in DEFINITIONS_SECTIONS,
        "is_illustration": ss_type == "illustration",
        "is_proviso": ss_type == "proviso",
        # Chunk type
        "chunk_type": "sub_section",
    }


def _infer_domain(act_code: str) -> str:
    """Fallback domain inference from act_code when chapter.domain is None."""
    mapping = {
        # Criminal
        "BNS_2023": "criminal_substantive",
        "IPC_1860": "criminal_substantive",
        "BNSS_2023": "criminal_procedure",
        "CrPC_1973": "criminal_procedure",
        "BSA_2023": "evidence",
        "IEA_1872": "evidence",
        # Civil — contract & specific relief
        "ICA_1872": "civil_contract",
        "SRA_1963": "civil_contract",
        # Civil — property
        "TPA_1882": "civil_property",
        "RA_1882": "civil_property",
        # Civil — procedure & limitation
        "CPC_1908": "civil_procedure",
        "LA_1963": "civil_general",
        # Civil — arbitration
        "ACA_1996": "civil_arbitration",
        # Consumer
        "CPA_2019": "consumer",
        # Family
        "HMA_1955": "family",
        "HSA_1956": "family",
        "SMA_1954": "family",
        "MLA_1939": "family",
    }
    return mapping.get(act_code, "other")


def _chunk_sub_sections(
    sub_sections: List[Dict[str, Any]],
    section_header: str,
    max_tokens: int = CHUNK_MAX_TOKENS,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Split sub-sections into token-limited chunks, preserving sub-section boundaries.

    Args:
        sub_sections:  Ordered list of sub-section dicts.
        section_header: "N. Title — " prefix repeated in each chunk for context.
        max_tokens:    Maximum token count per chunk (default 600).

    Returns:
        List of (chunk_text, [sub_sections_in_chunk]) tuples.
    """
    header_tokens = _token_count(section_header)
    chunks: List[Tuple[str, List[Dict[str, Any]]]] = []

    current_texts: List[str] = [section_header]
    current_subs: List[Dict[str, Any]] = []
    current_tokens = header_tokens

    for ss in sub_sections:
        ss_text = f"{ss['sub_section_label']} {ss['legal_text']}"
        ss_tokens = _token_count(ss_text)

        # If this single sub-section overflows max, it becomes its own chunk
        if ss_tokens > max_tokens:
            # Flush current accumulation first
            if current_subs:
                chunks.append(("\n".join(current_texts), current_subs))
                current_texts = [section_header]
                current_subs = []
                current_tokens = header_tokens
            chunks.append((section_header + "\n" + ss_text, [ss]))
            continue

        # Would adding this sub-section overflow the current chunk?
        if current_tokens + ss_tokens > max_tokens and current_subs:
            chunks.append(("\n".join(current_texts), current_subs))
            current_texts = [section_header]
            current_subs = []
            current_tokens = header_tokens

        current_texts.append(ss_text)
        current_subs.append(ss)
        current_tokens += ss_tokens

    if current_subs:
        chunks.append(("\n".join(current_texts), current_subs))

    return chunks


# ---------------------------------------------------------------------------
# LegalIndexer
# ---------------------------------------------------------------------------

class LegalIndexer:
    """Qdrant indexing pipeline for legal sections.

    Usage:
        async with AsyncSession(engine) as session:
            repo = SectionRepository(session)
            indexer = LegalIndexer(qdrant_client, embedder, repo)
            report = await indexer.index_act("BNS_2023")
    """

    def __init__(
        self,
        qdrant_client: Any,
        embedder: BGEM3Embedder,
        repo: SectionRepository,
        batch_size: int = 32,
    ) -> None:
        self._qdrant = qdrant_client
        self._embedder = embedder
        self._repo = repo
        self._batch_size = batch_size

    async def index_act(self, act_code: str) -> IndexingReport:
        """Index all eligible sections for an act into Qdrant.

        Steps:
        1. Fetch all eligible sections + chapter + sub-section + transition data
        2. For each section, determine scenario (A/B/C/D)
        3. Build section point payloads (with chunking for scenario C)
        4. Embed all section texts in batches via BGE-M3
        5. Upsert section points to legal_sections
        6. Build + embed + upsert sub-section points to legal_sub_sections
        7. Mark sections as qdrant_indexed in PostgreSQL

        Args:
            act_code: Canonical act code, e.g. "BNS_2023".

        Returns:
            IndexingReport with counts and any error details.
        """
        import time
        t_start = time.monotonic()
        report = IndexingReport(act_code=act_code)

        # ----------------------------------------------------------------
        # Step 1: Fetch all data from PostgreSQL
        # ----------------------------------------------------------------
        sections = await self._repo.get_sections_for_qdrant_indexing(act_code)
        chapters_by_id = await self._repo.get_chapters_for_act(act_code)
        sub_sections_by_section = await self._repo.get_sub_sections_for_act(act_code)
        transitions_by_section = await self._repo.get_active_transitions_for_act(act_code)

        report.sections_eligible = len(sections)
        logger.info(
            "indexer_start: act=%s eligible=%d",
            act_code, len(sections),
        )

        if not sections:
            logger.warning("indexer_no_sections: act=%s — nothing to index", act_code)
            return report

        # ----------------------------------------------------------------
        # Step 2-4: Build section points and embed in batches
        # ----------------------------------------------------------------

        # Accumulate points to embed
        # Each entry: (point_id, text_for_embedding, payload, sub_sections, section_dict)
        section_point_specs: List[Dict[str, Any]] = []
        # Sub-section points built separately after section embedding
        sub_section_specs: List[Dict[str, Any]] = []

        successfully_indexed_section_ids: List[_uuid_mod.UUID] = []

        for section in sections:
            try:
                section_id = str(section["id"])
                chapter_id_str = str(section["chapter_id"]) if section.get("chapter_id") else None
                chapter = chapters_by_id.get(chapter_id_str) if chapter_id_str else None
                sub_secs = sub_sections_by_section.get(section_id, [])
                transitions = transitions_by_section.get(section["section_number"], [])

                legal_text = section["legal_text"]
                tokens = _token_count(legal_text)
                is_definitions = _is_definitions_section(act_code, section["section_number"])

                # Determine scenario
                if is_definitions:
                    scenario = "D"
                elif tokens <= SCENARIO_A_MAX:
                    scenario = "A"
                elif tokens <= SCENARIO_B_MAX:
                    scenario = "B"
                else:
                    scenario = "C"

                section_title = section.get("section_title") or ""
                section_header = f"{section['section_number']}. {section_title}"

                if scenario in ("A", "B"):
                    # Single point — full section text
                    payload = _build_section_payload(
                        section, chapter, transitions,
                        chunk_type="full_section", chunk_index=0, total_chunks=1,
                    )
                    section_point_specs.append({
                        "point_id": section_id,
                        "text": legal_text,
                        "payload": payload,
                        "section_uuid": section["id"],
                    })

                elif scenario == "C":
                    # Multi-chunk: split at sub-section boundaries
                    if sub_secs:
                        chunks = _chunk_sub_sections(sub_secs, section_header, CHUNK_MAX_TOKENS)
                        total_chunks = len(chunks)
                        for idx, (chunk_text, _chunk_subs) in enumerate(chunks):
                            # uuid5: deterministic UUID derived from section_id + chunk index
                            # — valid Qdrant point ID, idempotent on re-index
                            chunk_point_id = str(
                                _uuid_mod.uuid5(
                                    _uuid_mod.NAMESPACE_URL,
                                    f"{section_id}__chunk{idx}",
                                )
                            )
                            payload = _build_section_payload(
                                section, chapter, transitions,
                                chunk_type="chunk", chunk_index=idx, total_chunks=total_chunks,
                            )
                            section_point_specs.append({
                                "point_id": chunk_point_id,
                                "text": chunk_text,
                                "payload": payload,
                                "section_uuid": section["id"],
                            })
                    else:
                        # No sub-sections — fall back to single-point
                        payload = _build_section_payload(
                            section, chapter, transitions,
                            chunk_type="full_section", chunk_index=0, total_chunks=1,
                        )
                        section_point_specs.append({
                            "point_id": section_id,
                            "text": legal_text,
                            "payload": payload,
                            "section_uuid": section["id"],
                        })

                elif scenario == "D":
                    # Definitions: sub-section granularity only in legal_sub_sections
                    # Still create ONE full-section point in legal_sections for context retrieval
                    payload = _build_section_payload(
                        section, chapter, transitions,
                        chunk_type="definitions_section", chunk_index=0, total_chunks=1,
                    )
                    section_point_specs.append({
                        "point_id": section_id,
                        "text": legal_text,
                        "payload": payload,
                        "section_uuid": section["id"],
                    })

                # Collect sub-section specs for scenarios B, C, D
                if scenario in ("B", "C", "D") and sub_secs:
                    for ss in sub_secs:
                        ss_payload = _build_sub_section_payload(ss, section, chapter)
                        ss_text = f"{ss['sub_section_label']} {ss['legal_text']}"
                        sub_section_specs.append({
                            "point_id": str(ss["id"]),
                            "text": ss_text,
                            "payload": ss_payload,
                        })

            except Exception as exc:
                report.errors += 1
                detail = f"section={section.get('section_number', '?')} error={exc}"
                report.error_details.append(detail)
                logger.error("indexer_section_error: act=%s %s", act_code, detail, exc_info=True)

        # ----------------------------------------------------------------
        # Step 4: Embed section texts and upsert to Qdrant
        # ----------------------------------------------------------------
        if section_point_specs:
            texts = [DOCUMENT_PREFIX + sp["text"] for sp in section_point_specs]
            logger.info("indexer_embedding_sections: act=%s count=%d", act_code, len(texts))

            dense_vecs, sparse_vecs = self._embedder.encode_batch(
                texts, batch_size=self._batch_size
            )

            from qdrant_client.models import PointStruct, SparseVector

            points = []
            for i, spec in enumerate(section_point_specs):
                sv = sparse_dict_to_qdrant(sparse_vecs[i])
                # Store the embedded text in the payload so retrieval can return it
                spec["payload"]["text"] = spec["text"]
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
                # Track unique section UUIDs (not chunk point IDs)
                section_uuid = spec.get("section_uuid")
                if section_uuid and section_uuid not in successfully_indexed_section_ids:
                    successfully_indexed_section_ids.append(section_uuid)

            # Upsert in batches to avoid oversized requests
            for batch_start in range(0, len(points), self._batch_size):
                batch = points[batch_start : batch_start + self._batch_size]
                self._qdrant.upsert(
                    collection_name=COLLECTION_LEGAL_SECTIONS,
                    points=batch,
                    wait=True,
                )

            report.section_points_created = len(points)
            report.sections_indexed = len(successfully_indexed_section_ids)
            logger.info(
                "indexer_sections_upserted: act=%s points=%d sections=%d",
                act_code, len(points), report.sections_indexed,
            )

        # ----------------------------------------------------------------
        # Step 6: Embed and upsert sub-section points
        # ----------------------------------------------------------------
        if sub_section_specs:
            ss_texts = [DOCUMENT_PREFIX + sp["text"] for sp in sub_section_specs]
            logger.info(
                "indexer_embedding_sub_sections: act=%s count=%d",
                act_code, len(ss_texts),
            )

            ss_dense, ss_sparse = self._embedder.encode_batch(
                ss_texts, batch_size=self._batch_size
            )

            from qdrant_client.models import PointStruct, SparseVector

            ss_points = []
            for i, spec in enumerate(sub_section_specs):
                sv = sparse_dict_to_qdrant(ss_sparse[i])
                # Store the embedded text in the payload so retrieval can return it
                spec["payload"]["text"] = spec["text"]
                ss_points.append(
                    PointStruct(
                        id=spec["point_id"],
                        vector={
                            "dense": ss_dense[i],
                            "sparse": SparseVector(**sv),
                        },
                        payload=spec["payload"],
                    )
                )

            for batch_start in range(0, len(ss_points), self._batch_size):
                batch = ss_points[batch_start : batch_start + self._batch_size]
                self._qdrant.upsert(
                    collection_name=COLLECTION_LEGAL_SUB_SECTIONS,
                    points=batch,
                    wait=True,
                )

            report.sub_sections_indexed = len(ss_points)
            logger.info(
                "indexer_sub_sections_upserted: act=%s count=%d",
                act_code, len(ss_points),
            )

        # ----------------------------------------------------------------
        # Step 7: Mark sections as indexed in PostgreSQL
        # ----------------------------------------------------------------
        if successfully_indexed_section_ids:
            await self._repo.mark_qdrant_indexed_batch(successfully_indexed_section_ids)
            logger.info(
                "indexer_marked_indexed: act=%s count=%d",
                act_code, len(successfully_indexed_section_ids),
            )

        report.duration_seconds = time.monotonic() - t_start
        logger.info("indexer_complete: %s", report.summary())
        return report
