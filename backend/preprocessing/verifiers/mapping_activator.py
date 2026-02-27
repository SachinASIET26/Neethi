"""Zero-cost mapping activation pipeline for Neethi AI.

Uses the BPR&D official source classification (the `type` field in the
*_complete.json files) as the primary activation authority. No LLM API
calls. No human review gate. Total cost: zero.

WHY THIS IS SOUND:
  The JSON files were built from two official Government of India documents
  published by the Bureau of Police Research and Development (BPR&D) under
  the Ministry of Home Affairs:
    - BPR&D Handbook: BNS Book_After Correction.pdf
    - BPR&D Comparison: COMPARISON SUMMARY BNS to IPC.pdf

  The `transition_type` field in law_transition_mappings is a direct
  mapping from the BPR&D's official classification. Using this as the
  activation authority is MORE defensible than LLM review.

ACTIVATION TIERS:
  Tier 1 — equivalent/same   → confidence 0.92, approved_by bprd_official_comparative_table
  Tier 2 — modified/merged   → confidence 0.80, approved_by bprd_official_comparative_table_modified
  Tier 3 — new               → confidence 0.85, approved_by bprd_new_provision
  Tier 4 — deleted           → confidence 0.88, approved_by bprd_deleted_provision
  Tier 5 — split_into        → confidence 0.82, approved_by bprd_split_provision

BGE-M3 SIMILARITY STEP:
  Runs after activation. Flags (does NOT gate) mappings with unusual
  semantic similarity. Requires BGE-M3 to be loaded; skipped otherwise.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.preprocessing.verifiers.adversarial_assertions import run_all_assertions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parents[3]
_AUDIT_DIR = _PROJECT_ROOT / "data" / "audit"
_ACTIVATION_REPORT_PATH = _AUDIT_DIR / "activation_report.json"
_SIMILARITY_FLAGS_PATH = _AUDIT_DIR / "similarity_flags.json"

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

_TIER_CONFIG = {
    # transition_type → (confidence, approved_by)
    "equivalent":  (0.92, "bprd_official_comparative_table"),
    "same":        (0.92, "bprd_official_comparative_table"),
    "modified":    (0.80, "bprd_official_comparative_table_modified"),
    "merged_from": (0.80, "bprd_official_comparative_table_modified"),
    "new":         (0.85, "bprd_new_provision"),
    "deleted":     (0.88, "bprd_deleted_provision"),
    "split_into":  (0.82, "bprd_split_provision"),
}

# Tier 2 types get a note appended to transition_note
_TIER_2_TYPES = {"modified", "merged_from"}

# Similarity thresholds (BGE-M3 step)
_LOW_SIMILARITY_EQUIVALENT = 0.40   # Flag if equivalent similarity < this
_HIGH_SIMILARITY_MODIFIED  = 0.95   # Flag if modified similarity > this


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ActivationReport:
    """Summary of one activation pipeline run."""

    run_timestamp: str = ""
    assertions_passed: int = 0
    total_mappings_processed: int = 0
    tier_1_activated: int = 0    # equivalent / same
    tier_2_activated: int = 0    # modified / merged_from
    tier_3_activated: int = 0    # new
    tier_4_activated: int = 0    # deleted
    tier_5_activated: int = 0    # split_into
    skipped_unknown_type: int = 0
    similarity_flags: int = 0
    total_active: int = 0
    approved_by_distribution: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class SimilarityFlag:
    """A mapping flagged by the BGE-M3 similarity step for spot-check."""

    old_act: str
    old_section: str
    old_section_title: str
    new_section: str
    new_section_title: str
    transition_type: str
    similarity_score: float
    flag_reason: str
    old_text_preview: str
    new_text_preview: str


# ---------------------------------------------------------------------------
# Cosine similarity helper
# ---------------------------------------------------------------------------

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity (no numpy required for this step)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# MappingActivator
# ---------------------------------------------------------------------------

class MappingActivator:
    """Activates law_transition_mappings using BPR&D authority tiers.

    Usage:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                activator = MappingActivator(session)
                report = await activator.run_activation_pipeline()
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._report = ActivationReport()

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def run_activation_pipeline(self) -> ActivationReport:
        """Run all 5 steps: assertions → tier activation → similarity → report.

        Returns:
            ActivationReport with full statistics.

        Raises:
            ValueError if adversarial assertions fail.
            SystemExit(1) from adversarial_assertions.run_all_assertions on failure.
        """
        self._report.run_timestamp = datetime.now(timezone.utc).isoformat()
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)

        # Step 1 — Adversarial safety assertions
        print("Running adversarial safety assertions...")
        try:
            await run_all_assertions(self._session)
        except SystemExit:
            raise ValueError(
                "Adversarial assertions failed — activation aborted. "
                "See output above for the specific failure."
            )
        self._report.assertions_passed = 5
        print("  All 5 assertions PASSED\n")

        # Step 2 — Tier-based activation
        await self._run_tier_activation()

        # Step 3 — BGE-M3 similarity validation (skipped if not available)
        similarity_flags = await self._run_similarity_validation()
        self._report.similarity_flags = len(similarity_flags)

        if similarity_flags:
            self._write_similarity_flags(similarity_flags)

        # Step 4 — Count final active total and write report
        count_row = await self._session.execute(
            text("SELECT COUNT(*) FROM law_transition_mappings WHERE is_active = TRUE")
        )
        self._report.total_active = count_row.scalar_one()

        self._write_activation_report()
        return self._report

    # -----------------------------------------------------------------------
    # Step 2: Tier-based activation
    # -----------------------------------------------------------------------

    async def _run_tier_activation(self) -> None:
        """Fetch all inactive mappings and activate by tier."""

        rows = await self._session.execute(
            text(
                "SELECT id, transition_type, transition_note "
                "FROM law_transition_mappings "
                "WHERE is_active = FALSE "
                "ORDER BY transition_type, id"
            )
        )
        all_rows = rows.fetchall()
        self._report.total_mappings_processed = len(all_rows)

        approved_by_dist: Dict[str, int] = {}
        tier1 = tier2 = tier3 = tier4 = tier5 = skipped = 0

        for row_id, transition_type, transition_note in all_rows:
            config = _TIER_CONFIG.get(transition_type)
            if config is None:
                logger.warning(
                    "Unknown transition_type '%s' for mapping id=%s — skipping",
                    transition_type, row_id,
                )
                skipped += 1
                continue

            confidence, approved_by = config

            # Build the note suffix for Tier 2 types
            new_note = transition_note or ""
            if transition_type in _TIER_2_TYPES:
                suffix = "[Substance modified \u2014 see change_summary for details]"
                if suffix not in new_note:
                    new_note = (new_note + " " + suffix).strip() if new_note else suffix

            await self._session.execute(
                text(
                    "UPDATE law_transition_mappings "
                    "SET is_active = TRUE, "
                    "    confidence_score = :conf, "
                    "    approved_by = :approved_by, "
                    "    approved_at = NOW(), "
                    "    transition_note = :note "
                    "WHERE id = :row_id"
                ),
                {
                    "conf": confidence,
                    "approved_by": approved_by,
                    "note": new_note if new_note else None,
                    "row_id": row_id,
                },
            )

            # Tally by tier
            if transition_type in ("equivalent", "same"):
                tier1 += 1
            elif transition_type in ("modified", "merged_from"):
                tier2 += 1
            elif transition_type == "new":
                tier3 += 1
            elif transition_type == "deleted":
                tier4 += 1
            elif transition_type == "split_into":
                tier5 += 1

            approved_by_dist[approved_by] = approved_by_dist.get(approved_by, 0) + 1

        self._report.tier_1_activated = tier1
        self._report.tier_2_activated = tier2
        self._report.tier_3_activated = tier3
        self._report.tier_4_activated = tier4
        self._report.tier_5_activated = tier5
        self._report.skipped_unknown_type = skipped
        self._report.approved_by_distribution = approved_by_dist

        # Terminal progress lines
        print(f"  Activating Tier 1 (equivalent/same, BPR&D authority).......... {tier1} mappings")
        print(f"  Activating Tier 2 (modified/merged, BPR&D authority).......... {tier2} mappings")
        print(f"  Activating Tier 3 (new provisions)............................. {tier3} mappings")
        print(f"  Activating Tier 4 (deleted provisions)......................... {tier4} mappings")
        print(f"  Activating Tier 5 (split cases)................................ {tier5} mappings")
        if skipped:
            print(f"  Skipped (unknown type)......................................... {skipped} mappings")
        print()

    # -----------------------------------------------------------------------
    # Step 3: BGE-M3 similarity validation
    # -----------------------------------------------------------------------

    async def _run_similarity_validation(self) -> List[SimilarityFlag]:
        """Run BGE-M3 semantic similarity on equivalent/modified active mappings.

        Returns list of SimilarityFlag objects. Returns empty list if BGE-M3
        is not available (graceful skip).
        """
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore
        except ImportError:
            print(
                "  BGE-M3 similarity validation: skipped — FlagEmbedding not installed. "
                "Run validate_similarities.py after Phase 3 embeddings are set up."
            )
            logger.info(
                "Similarity validation skipped — FlagEmbedding not installed. "
                "Run validate_similarities.py after Phase 3 embeddings are set up."
            )
            return []

        # Load BGE-M3 model
        model_name = os.environ.get("BGE_M3_MODEL_PATH", "BAAI/bge-m3")
        print(f"  Loading BGE-M3 ({model_name}) for similarity validation...")
        try:
            model = BGEM3FlagModel(model_name, use_fp16=True)
        except Exception as exc:
            logger.warning("Failed to load BGE-M3: %s — similarity validation skipped", exc)
            print(f"  BGE-M3 load failed ({exc}) — similarity validation skipped.")
            return []

        # Fetch equivalent and modified active mappings that have legal_text in both sides
        rows = await self._session.execute(
            text(
                """
                SELECT
                    m.old_act,
                    m.old_section,
                    s_old.section_title AS old_title,
                    s_old.legal_text    AS old_text,
                    m.new_section,
                    s_new.section_title AS new_title,
                    s_new.legal_text    AS new_text,
                    m.transition_type
                FROM law_transition_mappings m
                JOIN sections s_old
                  ON s_old.act_code = m.old_act
                 AND s_old.section_number = m.old_section
                JOIN sections s_new
                  ON s_new.act_code = m.new_act
                 AND s_new.section_number = m.new_section
                WHERE m.is_active = TRUE
                  AND m.transition_type IN ('equivalent', 'modified')
                  AND s_old.legal_text IS NOT NULL
                  AND s_new.legal_text IS NOT NULL
                  AND m.new_section IS NOT NULL
                ORDER BY m.old_section
                """
            )
        )
        mapping_rows = rows.fetchall()

        if not mapping_rows:
            print("  BGE-M3 similarity validation: 0 eligible mappings found.")
            return []

        flags: List[SimilarityFlag] = []
        batch_size = 32

        for batch_start in range(0, len(mapping_rows), batch_size):
            batch = mapping_rows[batch_start : batch_start + batch_size]
            old_texts = [r[3][:2000] for r in batch]   # cap at 2000 chars for speed
            new_texts = [r[6][:2000] for r in batch]

            old_embeddings = model.encode(
                old_texts, return_dense=True, return_sparse=False, return_colbert_vecs=False
            )["dense_vecs"]
            new_embeddings = model.encode(
                new_texts, return_dense=True, return_sparse=False, return_colbert_vecs=False
            )["dense_vecs"]

            for i, row in enumerate(batch):
                old_act, old_sec, old_title, old_text, new_sec, new_title, new_text, t_type = row
                sim = _cosine_similarity(
                    list(old_embeddings[i]), list(new_embeddings[i])
                )

                flag_reason: Optional[str] = None
                if t_type == "equivalent" and sim < _LOW_SIMILARITY_EQUIVALENT:
                    flag_reason = f"similarity {sim:.4f} < {_LOW_SIMILARITY_EQUIVALENT} for equivalent mapping"
                elif t_type == "modified" and sim > _HIGH_SIMILARITY_MODIFIED:
                    flag_reason = f"similarity {sim:.4f} > {_HIGH_SIMILARITY_MODIFIED} for modified mapping"

                if flag_reason:
                    flags.append(SimilarityFlag(
                        old_act=old_act,
                        old_section=old_sec,
                        old_section_title=old_title or "",
                        new_section=new_sec,
                        new_section_title=new_title or "",
                        transition_type=t_type,
                        similarity_score=round(sim, 6),
                        flag_reason=flag_reason,
                        old_text_preview=(old_text or "")[:100],
                        new_text_preview=(new_text or "")[:100],
                    ))

        print(
            f"  BGE-M3 similarity validation: {len(flags)} flags written to "
            f"data/audit/similarity_flags.json"
        )
        logger.info("Similarity validation complete: %d flags", len(flags))
        return flags

    # -----------------------------------------------------------------------
    # Step 4: Write reports
    # -----------------------------------------------------------------------

    def _write_activation_report(self) -> None:
        """Write activation_report.json to data/audit/."""
        report_dict = asdict(self._report)
        # Remove internal field not in spec
        report_dict.pop("skipped_unknown_type", None)
        report_dict.pop("errors", None)

        with open(_ACTIVATION_REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

        logger.info("Activation report written to %s", _ACTIVATION_REPORT_PATH)

    def _write_similarity_flags(self, flags: List[SimilarityFlag]) -> None:
        """Write similarity_flags.json to data/audit/."""
        flags_data = [asdict(f) for f in flags]
        with open(_SIMILARITY_FLAGS_PATH, "w", encoding="utf-8") as f:
            json.dump(flags_data, f, indent=2, ensure_ascii=False)

        logger.info(
            "Similarity flags written to %s (%d entries)",
            _SIMILARITY_FLAGS_PATH, len(flags)
        )
