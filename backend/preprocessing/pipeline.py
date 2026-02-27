"""Legal ingestion pipeline orchestrator.

Executes 11 steps per act:
  Step 1:  Load enrichment data from JSON (json_enricher.py)
  Step 2:  Run two-pass PDF extraction (pdf_extractor.py)
  Step 3:  Apply text cleaning (text_cleaner.py)
  Step 4:  Parse section boundaries (act_parser.py)
  Step 5:  Run validation on each section (extraction_validator.py)
  Step 5.5: Seed chapters table from enrichment map (must run before sections)
  Step 6:  Merge extracted sections with JSON enrichment
  Step 7:  Insert to PostgreSQL (sections and sub_sections tables)
  Step 8:  Route failed validations to human_review_queue
  Step 9:  Populate law_transition_mappings from enrichment data
  Step 10: Write extraction_audit record for every section processed

Data source rules (non-negotiable):
- legal_text comes ONLY from the PDF extractor
- Metadata (chapter, domain, transition hints) comes ONLY from JSON enrichment
- Sections with extraction_confidence < 0.5 are NOT inserted to sections table
  (they go to human_review_queue only — too unreliable for the legal database)
- Sections with 0.5 ≤ confidence < 0.7 are inserted but also queued for review

All ten steps run for every act, in order. No shortcuts.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.repositories.section_repository import SectionRepository
from backend.preprocessing.classifiers.offence_classifier import (
    OffenceClassification,
    classify_offence,
)
from backend.preprocessing.cleaners.text_cleaner import clean_legal_text
from backend.preprocessing.enrichers.json_enricher import (
    SectionEnrichment,
    SectionEnrichmentMap,
    _ROMAN_TO_INT,
    load_enrichment,
)
from backend.preprocessing.extractors.pdf_extractor import extract_pdf
from backend.preprocessing.parsers.act_parser import ParsedSection, parse_act
from backend.preprocessing.validators.extraction_validator import (
    ExtractionReport,
    validate_section,
)

logger = logging.getLogger(__name__)

# Pipeline version — bump when extraction logic changes (for audit tracking)
PIPELINE_VERSION = "2.0.0"

# Era lookup by act_code
_ACT_ERA: Dict[str, str] = {
    # Criminal — new codes (2024)
    "BNS_2023": "naveen_sanhitas",
    "BNSS_2023": "naveen_sanhitas",
    "BSA_2023": "naveen_sanhitas",
    # Criminal — colonial codes (still in force for pre-July 2024 cases)
    "IPC_1860": "colonial_codes",
    "CrPC_1973": "colonial_codes",
    "IEA_1872": "colonial_codes",
    # Civil statutes — colonial era
    "ICA_1872": "civil_statutes",
    "TPA_1882": "civil_statutes",
    "CPC_1908": "civil_statutes",
    "RA_1882": "civil_statutes",
    # Civil statutes — post-independence
    "SRA_1963": "civil_statutes",
    "LA_1963": "civil_statutes",
    "HMA_1955": "civil_statutes",
    "HSA_1956": "civil_statutes",
    "SMA_1954": "civil_statutes",
    # Civil statutes — modern
    "ACA_1996": "civil_statutes",
    "CPA_2019": "civil_statutes",
}

# Applicable dates by act_code
_ACT_APPLICABLE_FROM: Dict[str, datetime.date] = {
    "BNS_2023": datetime.date(2024, 7, 1),
    "BNSS_2023": datetime.date(2024, 7, 1),
    "BSA_2023": datetime.date(2024, 7, 1),
}

# JSON confidence: BPR&D sourced mappings
_JSON_CONFIDENCE = 0.75


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class IngestionReport:
    """Summary of one act ingestion run."""

    act_code: str
    total_sections_found: int = 0
    sections_inserted: int = 0
    sections_skipped_low_confidence: int = 0   # confidence < 0.5
    sections_queued_for_review: int = 0         # 0.5 <= confidence < 0.7
    sub_sections_inserted: int = 0
    transition_mappings_created: int = 0
    review_queue_entries: int = 0
    audit_records_written: int = 0
    errors: List[str] = field(default_factory=list)
    low_confidence_sections: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Helper: parse section number into (int_part, suffix)
# ---------------------------------------------------------------------------

_SECTION_NUM_RE = re.compile(r"^(\d+)([A-Za-z]*)$")


def _parse_section_number(s: str) -> Tuple[Optional[int], Optional[str]]:
    """Split '53A' → (53, 'A'), '103' → (103, None), 'other' → (None, None)."""
    m = _SECTION_NUM_RE.match(s.strip())
    if not m:
        return None, None
    int_part = int(m.group(1))
    suffix = m.group(2).upper() if m.group(2) else None
    return int_part, suffix


# ---------------------------------------------------------------------------
# Helper: determine transition_type with split detection
# ---------------------------------------------------------------------------

def _compute_transition_types(
    enrichment_map: SectionEnrichmentMap,
) -> Dict[str, Dict[str, str]]:
    """Build a lookup: old_section → new_section → effective_transition_type.

    Detects the split case: when one old section maps to multiple new sections,
    all corresponding rows get transition_type = 'split_into'.

    Returns:
        {old_section: {new_section: transition_type}}
    """
    # Build: old_section → [new_sections that replace it]
    old_to_new: Dict[str, List[str]] = defaultdict(list)
    for new_sec, enrichment in enrichment_map.items():
        for old_sec in enrichment.replaces_old_sections:
            old_to_new[old_sec].append(new_sec)

    # Now compute transition types
    result: Dict[str, Dict[str, str]] = {}
    for new_sec, enrichment in enrichment_map.items():
        for old_sec in enrichment.replaces_old_sections:
            if old_sec not in result:
                result[old_sec] = {}
            # Split if one old → multiple new
            if len(old_to_new[old_sec]) > 1:
                result[old_sec][new_sec] = "split_into"
            else:
                result[old_sec][new_sec] = enrichment.transition_type_hint

    return result


# ---------------------------------------------------------------------------
# Sub-section type mapping
# ---------------------------------------------------------------------------

_SUBSECTION_TYPE_MAP: Dict[str, str] = {
    # Labels starting with ( digit ) → numbered
    # Labels starting with ( letter ) → lettered
    # Exact matches for structural types
    "Explanation": "explanation",
    "Proviso": "proviso",
}


def _label_to_type(label: str) -> str:
    """Map a sub-section label to its sub_section_type string."""
    if label in _SUBSECTION_TYPE_MAP:
        return _SUBSECTION_TYPE_MAP[label]
    if label.startswith("Illustration"):
        return "illustration"
    if re.match(r"^\(\d+\)$", label):
        return "numbered"
    if re.match(r"^\([a-z]\)$", label):
        return "lettered"
    return "numbered"  # safe fallback


# ---------------------------------------------------------------------------
# Main pipeline class
# ---------------------------------------------------------------------------

class LegalIngestionPipeline:
    """Orchestrates all 10 ingestion steps for a single act.

    Usage:
        async with AsyncSessionLocal() as session:
            pipeline = LegalIngestionPipeline(session)
            report = await pipeline.ingest_act("BNS_2023", pdf_path, json_path)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SectionRepository(session)

    async def ingest_act(
        self,
        act_code: str,
        pdf_path: Path,
        json_path: Path,
    ) -> IngestionReport:
        """Run all 10 ingestion steps for a single act.

        Args:
            act_code:  Canonical act code, e.g. "BNS_2023".
            pdf_path:  Absolute path to the act's PDF file.
            json_path: Absolute path to the act's JSON enrichment file.

        Returns:
            IngestionReport with counts, errors, and duration.
        """
        report = IngestionReport(act_code=act_code)
        start_time = time.monotonic()

        logger.info("ingest_act START: act=%s pdf=%s json=%s", act_code, pdf_path.name, json_path.name)

        try:
            # ----------------------------------------------------------------
            # Step 1 — Load enrichment data from JSON
            # ----------------------------------------------------------------
            logger.info("[Step 1] Loading JSON enrichment: act=%s", act_code)
            enrichment_map: SectionEnrichmentMap = load_enrichment(json_path, act_code)
            logger.info("[Step 1] Enrichment loaded: %d entries", len(enrichment_map))

            # ----------------------------------------------------------------
            # Step 2 — Two-pass PDF extraction
            # ----------------------------------------------------------------
            logger.info("[Step 2] Running PDF extraction: %s", pdf_path.name)
            raw_text, superscript_positions, structure_map = extract_pdf(pdf_path)
            logger.info(
                "[Step 2] Extraction complete: chars=%d superscript_blocks=%d",
                len(raw_text), len(superscript_positions),
            )

            # ----------------------------------------------------------------
            # Step 3 — Text cleaning
            # ----------------------------------------------------------------
            logger.info("[Step 3] Applying cleaning rules")
            cleaned_text = clean_legal_text(raw_text, superscript_positions)
            logger.info(
                "[Step 3] Cleaning complete: raw_chars=%d clean_chars=%d",
                len(raw_text), len(cleaned_text),
            )

            # ----------------------------------------------------------------
            # Step 4 — Parse section boundaries
            # ----------------------------------------------------------------
            logger.info("[Step 4] Parsing section boundaries")
            sections, chapters = parse_act(cleaned_text)
            report.total_sections_found = len(sections)
            logger.info("[Step 4] Found %d sections, %d chapters", len(sections), len(chapters))

            # ----------------------------------------------------------------
            # Step 5 — Validate each section
            # ----------------------------------------------------------------
            logger.info("[Step 5] Running validation checks on %d sections", len(sections))
            validation_reports: Dict[str, ExtractionReport] = {}
            for sec in sections:
                sub_count = len(sec.subsection_texts) if sec.subsection_texts else 0
                report_ = validate_section(
                    section_number=sec.section_number,
                    legal_text=sec.raw_body_text,
                    has_subsections=sec.has_subsections,
                    sub_section_count=sub_count,
                )
                validation_reports[sec.section_number] = report_
            logger.info("[Step 5] Validation complete")

            # ----------------------------------------------------------------
            # Step 5.5 — Seed chapters table from enrichment map
            # Must run BEFORE the per-section loop so that get_chapter_id()
            # finds each chapter UUID when building section rows.
            # ----------------------------------------------------------------
            logger.info("[Step 5.5] Seeding chapters for act=%s", act_code)
            seeded_chapters: set[str] = set()
            for enrichment in enrichment_map.values():
                ch_num = enrichment.chapter_number  # Roman numeral string
                if not ch_num or ch_num in seeded_chapters:
                    continue
                ch_int = _ROMAN_TO_INT.get(ch_num, 0)
                await self._repo.upsert_chapter({
                    "act_code": act_code,
                    "chapter_number": ch_num,
                    "chapter_number_int": ch_int,
                    "chapter_title": enrichment.chapter_title or f"Chapter {ch_num}",
                    "domain": enrichment.domain or None,
                })
                seeded_chapters.add(ch_num)
            logger.info("[Step 5.5] Chapters seeded: %d", len(seeded_chapters))

            # Pre-compute transition type overrides for split detection
            transition_overrides = _compute_transition_types(enrichment_map)

            # ----------------------------------------------------------------
            # Steps 6–10 — Per-section processing
            # ----------------------------------------------------------------
            era = _ACT_ERA.get(act_code, "naveen_sanhitas")
            applicable_from = _ACT_APPLICABLE_FROM.get(act_code)

            for sec in sections:
                await self._process_section(
                    sec=sec,
                    act_code=act_code,
                    era=era,
                    applicable_from=applicable_from,
                    enrichment_map=enrichment_map,
                    validation_report=validation_reports[sec.section_number],
                    transition_overrides=transition_overrides,
                    report=report,
                )

            # Flush all accumulated changes to the DB
            await self._session.flush()

        except Exception as exc:  # noqa: BLE001
            logger.exception("ingest_act FAILED: act=%s error=%s", act_code, exc)
            report.errors.append(f"Pipeline error: {exc}")

        finally:
            report.duration_seconds = time.monotonic() - start_time
            logger.info(
                "ingest_act COMPLETE: act=%s sections_found=%d inserted=%d "
                "review=%d mappings=%d errors=%d duration=%.1fs",
                act_code,
                report.total_sections_found,
                report.sections_inserted,
                report.review_queue_entries,
                report.transition_mappings_created,
                len(report.errors),
                report.duration_seconds,
            )

        return report

    # ------------------------------------------------------------------
    # Per-section processor (Steps 6–10 inlined)
    # ------------------------------------------------------------------

    async def _process_section(
        self,
        sec: ParsedSection,
        act_code: str,
        era: str,
        applicable_from: Optional[datetime.date],
        enrichment_map: SectionEnrichmentMap,
        validation_report: ExtractionReport,
        transition_overrides: Dict[str, Dict[str, str]],
        report: IngestionReport,
    ) -> None:
        """Execute Steps 6–10 for a single section."""

        section_num = sec.section_number
        confidence = validation_report.extraction_confidence

        # ----------------------------------------------------------------
        # Step 6 — Merge extracted section with JSON enrichment
        # ----------------------------------------------------------------
        enrichment: Optional[SectionEnrichment] = enrichment_map.get(section_num)

        # legal_text is always from the PDF extractor — never from JSON
        legal_text = sec.raw_body_text.strip()

        # Chapter assignment from JSON enrichment (fallback to PDF parser detection)
        chapter_number: Optional[str] = None
        chapter_id = None
        if enrichment:
            chapter_number = enrichment.chapter_number or sec.chapter_number
        else:
            chapter_number = sec.chapter_number

        if chapter_number:
            chapter_id = await self._repo.get_chapter_id(act_code, chapter_number)

        # Offence classification (BNS only in Phase 2B)
        offence_clf: Optional[OffenceClassification] = None
        if act_code == "BNS_2023":
            offence_clf = classify_offence(
                section_number=section_num,
                legal_text=legal_text,
                act_code=act_code,
            )

        # Parse section number into int + suffix
        sec_num_int, sec_num_suffix = _parse_section_number(section_num)

        # ----------------------------------------------------------------
        # Step 7 — Insert to PostgreSQL (sections table)
        # If confidence < 0.5: skip sections table, only add to review queue
        # ----------------------------------------------------------------
        section_id: Optional[object] = None

        if confidence < 0.5:
            # Too unreliable — do NOT insert to sections table
            report.sections_skipped_low_confidence += 1
            report.low_confidence_sections.append(section_num)
            logger.warning(
                "SKIP section: act=%s section=%s confidence=%.2f (< 0.5)",
                act_code, section_num, confidence,
            )
        else:
            # Build section row dict
            section_data: Dict[str, Any] = {
                "act_code": act_code,
                "chapter_id": chapter_id,
                "section_number": section_num,
                "section_number_int": sec_num_int,
                "section_number_suffix": sec_num_suffix,
                "section_title": sec.section_title or (
                    enrichment.chapter_title if enrichment else None
                ),
                "legal_text": legal_text,
                "status": "active",
                "applicable_from": applicable_from,
                "era": era,
                "has_subsections": sec.has_subsections,
                "has_illustrations": sec.has_illustrations,
                "has_explanations": sec.has_explanations,
                "has_provisos": sec.has_provisos,
                "extraction_confidence": confidence,
                "is_offence": offence_clf.is_offence if offence_clf else False,
                "is_cognizable": offence_clf.is_cognizable if offence_clf else None,
                "is_bailable": offence_clf.is_bailable if offence_clf else None,
                "triable_by": offence_clf.triable_by if offence_clf else None,
                "punishment_type": offence_clf.punishment_type if offence_clf else None,
                "punishment_min_years": offence_clf.punishment_min_years if offence_clf else None,
                "punishment_max_years": offence_clf.punishment_max_years if offence_clf else None,
                "punishment_fine_max": offence_clf.punishment_fine_max if offence_clf else None,
                "qdrant_indexed": False,
            }

            try:
                section_id = await self._repo.upsert_section(section_data)
                report.sections_inserted += 1
            except Exception as exc:
                msg = f"upsert_section failed: {act_code}/{section_num}: {exc}"
                logger.error(msg)
                report.errors.append(msg)
                section_id = None

            # Insert sub_sections
            if section_id and sec.subsection_texts:
                ss_count = await self._insert_sub_sections(
                    section_id=section_id,
                    act_code=act_code,
                    section_num=section_num,
                    subsection_texts=sec.subsection_texts,
                )
                report.sub_sections_inserted += ss_count

        # ----------------------------------------------------------------
        # Step 8 — Route to human_review_queue if confidence < 0.7
        # ----------------------------------------------------------------
        if validation_report.requires_human_review or confidence < 0.7:
            reason = (
                "; ".join(validation_report.check_failures)
                if validation_report.check_failures
                else f"extraction_confidence={confidence:.2f} < 0.70"
            )
            await self._repo.add_to_review_queue(
                act_code=act_code,
                section_number=section_num,
                reason=reason,
                raw_text=sec.raw_body_text,
                cleaned_text=legal_text,
                extraction_confidence=confidence,
                section_id=section_id,
            )
            report.review_queue_entries += 1
            if confidence >= 0.5:
                report.sections_queued_for_review += 1

        # ----------------------------------------------------------------
        # Step 9 — Populate law_transition_mappings
        # ----------------------------------------------------------------
        if enrichment and enrichment.replaces_old_sections and section_id:
            mappings_created = await self._insert_transition_mappings(
                section_id=section_id,
                act_code=act_code,
                section_num=section_num,
                section_title=sec.section_title,
                enrichment=enrichment,
                transition_overrides=transition_overrides,
            )
            report.transition_mappings_created += mappings_created

        # ----------------------------------------------------------------
        # Step 10 — Write extraction_audit record
        # ----------------------------------------------------------------
        audit_data: Dict[str, Any] = {
            "section_id": section_id,
            "act_code": act_code,
            "section_number": section_num,
            "pipeline_version": PIPELINE_VERSION,
            "checks_run": validation_report.checks_run,
            "checks_passed": validation_report.checks_passed,
            "check_failures": validation_report.check_failures or [],
            "extraction_confidence": confidence,
            "noise_types_found": _detect_noise_types(validation_report),
            "raw_text_length": len(sec.raw_body_text) if sec.raw_body_text else 0,
            "cleaned_text_length": len(legal_text),
            "requires_human_review": validation_report.requires_human_review,
        }
        try:
            await self._repo.write_extraction_audit(audit_data)
            report.audit_records_written += 1
        except Exception as exc:
            logger.warning("write_extraction_audit failed: %s/%s: %s", act_code, section_num, exc)

    # ------------------------------------------------------------------
    # Sub-section inserter
    # ------------------------------------------------------------------

    async def _insert_sub_sections(
        self,
        section_id: object,
        act_code: str,
        section_num: str,
        subsection_texts: Dict[str, str],
    ) -> int:
        """Insert all sub-sections for a given section. Returns count inserted."""
        inserted = 0
        for position, (label, text) in enumerate(subsection_texts.items(), start=1):
            if not text or not text.strip():
                continue
            ss_data: Dict[str, Any] = {
                "section_id": section_id,
                "act_code": act_code,
                "parent_section_number": section_num,
                "sub_section_label": label,
                "sub_section_type": _label_to_type(label),
                "legal_text": text.strip(),
                "position_order": position,
            }
            try:
                await self._repo.upsert_sub_section(ss_data)
                inserted += 1
            except Exception as exc:
                logger.warning(
                    "_insert_sub_sections: act=%s section=%s label=%s error=%s",
                    act_code, section_num, label, exc,
                )
        return inserted

    # ------------------------------------------------------------------
    # Transition mapping inserter
    # ------------------------------------------------------------------

    async def _insert_transition_mappings(
        self,
        section_id: object,
        act_code: str,
        section_num: str,
        section_title: Optional[str],
        enrichment: SectionEnrichment,
        transition_overrides: Dict[str, Dict[str, str]],
    ) -> int:
        """Insert transition mapping rows for a section. Returns count inserted."""
        old_act = enrichment.old_act_code
        inserted = 0

        for old_section in enrichment.replaces_old_sections:
            if not old_section or not old_section.strip():
                continue

            # Determine transition_type: override (split detection) takes precedence
            override = transition_overrides.get(old_section, {}).get(section_num)
            transition_type = override or enrichment.transition_type_hint

            mapping_data: Dict[str, Any] = {
                "old_act": old_act,
                "old_section": old_section,
                "new_act": act_code,
                "new_section": section_num,
                "new_section_title": section_title,
                "transition_type": transition_type,
                "transition_note": enrichment.change_summary[:500] if enrichment.change_summary else None,
                "confidence_score": _JSON_CONFIDENCE,
                "effective_date": _ACT_APPLICABLE_FROM.get(act_code, datetime.date(2024, 7, 1)),
                "is_active": False,  # Requires human review before activation
            }

            try:
                await self._repo.upsert_transition_mapping(mapping_data)
                inserted += 1
            except Exception as exc:
                logger.warning(
                    "_insert_transition_mappings: act=%s section=%s old=%s/%s error=%s",
                    act_code, section_num, old_act, old_section, exc,
                )

        return inserted


# ---------------------------------------------------------------------------
# Utility: detect which noise types fired in a validation report
# ---------------------------------------------------------------------------

def _detect_noise_types(report: ExtractionReport) -> List[str]:
    """Convert check failure messages into a list of short noise type labels."""
    types = []
    for msg in report.check_failures:
        if "Check 1" in msg:
            types.append("footnote_residue")
        elif "Check 2" in msg:
            types.append("commentary_residue")
        elif "Check 3" in msg:
            types.append("cross_section_contamination")
        elif "Check 4" in msg:
            types.append("bracket_annotation")
        elif "Check 5" in msg:
            if "empty" in msg.lower():
                types.append("empty_text")
            else:
                types.append("short_text")
        elif "Check 6" in msg:
            types.append("subsection_count_mismatch")
        elif "Check 7" in msg:
            types.append("missing_offence_fields")
    return types
