"""JSON enrichment loader for BNS, BNSS, and BSA complete JSON files.

Reads bns_complete.json, bnss_complete.json, bsa_complete.json and builds
a per-act lookup: Dict[section_number, SectionEnrichment].

CRITICAL rules enforced here:
- legal_text from JSON is IGNORED (it is corrupted — see Part 1.3 of pipeline breakdown)
- rag_keywords from JSON is IGNORED (incorrectly stemmed, would degrade retrieval)
- notes field is set to None if identical to change_summary (deduplication)
- chapter_number is ALWAYS normalised to Roman numeral string (resolves BNS/BNSS inconsistency)

The "source of truth" split:
- legal_text comes from the PDF extractor (clean)
- Everything in SectionEnrichment comes from here (correct metadata, enrichment)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roman numeral conversion (needed for BNSS/BSA which use Arabic chapter numbers)
# ---------------------------------------------------------------------------

_INT_TO_ROMAN: Dict[int, str] = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
    11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV",
    16: "XVI", 17: "XVII", 18: "XVIII", 19: "XIX", 20: "XX",
    21: "XXI", 22: "XXII", 23: "XXIII", 24: "XXIV", 25: "XXV",
    26: "XXVI", 27: "XXVII", 28: "XXVIII", 29: "XXIX", 30: "XXX",
    31: "XXXI", 32: "XXXII", 33: "XXXIII", 34: "XXXIV", 35: "XXXV",
    36: "XXXVI", 37: "XXXVII", 38: "XXXVIII", 39: "XXXIX",
}

_ROMAN_TO_INT: Dict[str, int] = {v: k for k, v in _INT_TO_ROMAN.items()}


def _to_roman(chapter_str: str) -> str:
    """Normalise chapter_number to Roman numeral string.

    Accepts: Roman strings ('I', 'X'), Arabic strings ('1', '10'),
    or Arabic integers passed as strings. Returns the Roman form.
    Falls back to the input string if conversion is not possible.
    """
    s = str(chapter_str).strip().upper()
    # Already Roman?
    if s in _ROMAN_TO_INT:
        return s
    # Arabic integer string?
    try:
        n = int(s)
        return _INT_TO_ROMAN.get(n, s)
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Act configuration table
# ---------------------------------------------------------------------------

_ACT_CONFIG: Dict[str, dict] = {
    "BNS_2023": {
        "section_key": "bns_section",
        "chapter_key": "bns_chapter",
        "replaces_key": "replaces_ipc",
        "old_act_code": "IPC_1860",
        "chapter_number_is_roman": True,   # BNS JSON already uses Roman numerals
    },
    "BNSS_2023": {
        "section_key": "bnss_section",
        "chapter_key": "bnss_chapter",
        "replaces_key": "replaces_crpc",
        "old_act_code": "CrPC_1973",
        "chapter_number_is_roman": False,  # BNSS JSON uses Arabic chapter numbers
    },
    "BSA_2023": {
        "section_key": "bsa_section",
        "chapter_key": "bsa_chapter",
        "replaces_key": "replaces_iea",
        "old_act_code": "IEA_1872",
        "chapter_number_is_roman": False,  # BSA JSON uses Arabic chapter numbers
    },
}

_TYPE_MAP: Dict[str, str] = {
    "same": "equivalent",
    "modified": "modified",
    "merged": "merged_from",
    "new": "new",
    # Explicit split — note: JSON uses "same"/"modified" but split is detected by
    # multiple new sections referencing the same old section (handled in pipeline.py)
}

# ---------------------------------------------------------------------------
# Old-section normalization
# ---------------------------------------------------------------------------

# Regex to strip sub-section parenthetical suffix from IPC/CrPC/IEA section refs.
# Examples: '376(1)' → '376', '376(2)' → '376', '53A' → '53A' (unchanged)
# Rationale: BNS 64 has replaces_ipc=['376(1)'] and BNS 65 has ['376(2)'].
# Both refer to sub-sections of the same IPC section 376. Storing old_section as
# '376(1)' breaks lookup_transition('IPC_1860', '376') — normalise to the base
# section number so split detection and DB lookups work correctly.
_SUBSEC_SUFFIX_RE = re.compile(r"\(\d+\)$")


def _normalize_old_section(s: str) -> str:
    """Strip sub-section parenthetical suffix: '376(1)' -> '376', '53A' -> '53A'."""
    return _SUBSEC_SUFFIX_RE.sub("", s).strip()


# ---------------------------------------------------------------------------
# Data-quality corrections for known JSON noise
# ---------------------------------------------------------------------------

# Sections where the JSON replaces_ipc/crpc/iea list contains provably incorrect
# old-section references. These are confirmed noise from the BPR&D JSON conversion
# process — NOT valid transition mappings.
#
# BNS 95 = "Hiring, Employing or Engaging a Child to Commit an Offence".
# Its replaces_ipc list includes '302' (Murder). This is JSON noise. IPC 302
# (Murder) maps ONLY to BNS 103, as confirmed by the false_friends block in
# bns_complete.json (correct_new_section_for_old_meaning = '103').
# Keeping '302' in BNS 95 would: (a) trigger false split detection for IPC 302,
# marking BNS 103 as split_into instead of modified; (b) break adversarial
# assertion 1; (c) surface BNS 95 as a murder equivalent to users.
_BLOCKED_OLD_SECTIONS: Dict[str, Dict[str, List[str]]] = {
    "BNS_2023": {
        "95": ["302"],   # BNS 95 is child-offence abetment, NOT a Murder replacement
    },
}

# Sections whose old-section refs were intentionally left empty in the JSON
# (type='new') but whose authoritative mapping is documented in the notes field
# or the BPR&D comparative document. These are seeded manually here.
#
# IPC 124A (Sedition) → BNS 152: BNS 152 has replaces_ipc=[] and type='new',
# but its notes explicitly state "New provision replacing sedition (IPC 124A)".
# Without this seed, no transition_mapping row is ever created for IPC 124A,
# and adversarial assertion 2 will fail.
_MANUAL_OLD_SECTIONS: Dict[str, Dict[str, List[str]]] = {
    "BNS_2023": {
        "152": ["124A"],  # IPC 124A (Sedition) → BNS 152 (per section notes + BPR&D)
    },
}


# ---------------------------------------------------------------------------
# SectionEnrichment dataclass
# ---------------------------------------------------------------------------

@dataclass
class SectionEnrichment:
    """Metadata fields extracted from the JSON enrichment files.

    These fields supplement the PDF-extracted legal_text.
    legal_text itself is NEVER sourced from here.
    """

    chapter_number: str                          # Roman numeral: "I", "II"
    chapter_title: str
    domain: str                                  # "Preliminary & Definitions", etc.
    replaces_old_sections: List[str] = field(default_factory=list)
    # e.g. ["302"] or ["376(1)", "376(2)"] for split cases
    old_act_code: str = ""                       # "IPC_1860", "CrPC_1973", "IEA_1872"
    change_summary: str = ""                     # Editorial change note (safe metadata)
    transition_type_hint: str = "equivalent"     # Mapped from "type" field
    notes: Optional[str] = None                  # None if duplicate of change_summary


# Convenience alias for the per-act dict
SectionEnrichmentMap = Dict[str, SectionEnrichment]
# Full catalog: act_code → section_number → enrichment
EnrichmentCatalog = Dict[str, SectionEnrichmentMap]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_enrichment(json_path: Path, act_code: str) -> SectionEnrichmentMap:
    """Load enrichment data for a single act from its JSON file.

    Args:
        json_path: Absolute path to the JSON file (e.g. bns_complete.json).
        act_code:  Canonical act code, e.g. "BNS_2023".

    Returns:
        Dict mapping section_number (str) → SectionEnrichment.

    Raises:
        KeyError: If act_code is not in the configuration table.
        FileNotFoundError: If json_path does not exist.
    """
    if act_code not in _ACT_CONFIG:
        # Civil statutes (ICA, SRA, TPA, etc.) have no transition mappings — return
        # an empty enrichment map. Domain and era are inferred from act_code in the
        # indexer (_infer_domain) and pipeline (_ACT_ERA). This is intentional.
        logger.info(
            "load_enrichment: act_code=%r not in transition config — returning empty map "
            "(civil/standalone act, no IPC/CrPC replacement mappings needed)",
            act_code,
        )
        return {}

    cfg = _ACT_CONFIG[act_code]
    section_key = cfg["section_key"]
    replaces_key = cfg["replaces_key"]
    old_act_code = cfg["old_act_code"]

    with open(json_path, encoding="utf-8") as f:
        data: dict = json.load(f)

    enrichment_map: SectionEnrichmentMap = {}

    chapters: List[dict] = data.get("chapters", [])
    if not chapters:
        logger.warning("load_enrichment: no 'chapters' key found in %s", json_path)
        return enrichment_map

    for chapter in chapters:
        raw_chapter_num = chapter.get("chapter_number", "")
        chapter_number = _to_roman(str(raw_chapter_num))
        chapter_title = chapter.get("chapter_title", "")
        chapter_domain = chapter.get("domain", "")

        sections: List[dict] = chapter.get("sections", [])
        for sec in sections:
            section_num = str(sec.get(section_key, "")).strip()
            if not section_num:
                continue

            # Ignored fields: legal_text, rag_keywords
            change_summary = sec.get("change_summary") or ""
            notes_raw = sec.get("notes") or ""
            # Deduplication: discard notes if identical to change_summary
            notes: Optional[str] = notes_raw if notes_raw != change_summary else None

            # Section-level domain (falls back to chapter domain)
            domain = sec.get("domain") or chapter_domain

            # replaces_old_sections: normalise to List[str], skip empty values
            raw_replaces = sec.get(replaces_key) or []
            if isinstance(raw_replaces, str):
                raw_replaces = [raw_replaces] if raw_replaces.strip() else []
            replaces_old_sections = [str(r).strip() for r in raw_replaces if str(r).strip()]

            # FIX 1 — Normalise sub-section parenthetical suffixes.
            # '376(1)' and '376(2)' both become '376' so split detection works
            # correctly and lookup_transition('IPC_1860', '376') returns rows.
            replaces_old_sections = [_normalize_old_section(r) for r in replaces_old_sections]

            # Deduplicate while preserving order (normalisation may collapse
            # '376(1)' and '376(2)' into two copies of '376').
            replaces_old_sections = list(dict.fromkeys(replaces_old_sections))

            # FIX 2 — Remove known JSON noise references.
            # E.g. BNS 95 incorrectly lists IPC 302 (Murder) in its replaces_ipc.
            blocked = _BLOCKED_OLD_SECTIONS.get(act_code, {}).get(section_num, [])
            if blocked:
                before = len(replaces_old_sections)
                replaces_old_sections = [r for r in replaces_old_sections if r not in blocked]
                removed = before - len(replaces_old_sections)
                if removed:
                    logger.info(
                        "Blocked %d noisy old-section ref(s) from %s/%s: %s",
                        removed, act_code, section_num, blocked,
                    )

            # Type mapping
            raw_type = (sec.get("type") or "").lower().strip()
            transition_type_hint = _TYPE_MAP.get(raw_type, "equivalent")

            enrichment_map[section_num] = SectionEnrichment(
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                domain=domain,
                replaces_old_sections=replaces_old_sections,
                old_act_code=old_act_code,
                change_summary=change_summary,
                transition_type_hint=transition_type_hint,
                notes=notes,
            )

    # FIX 3 — Inject manual old-section seeds for sections whose replaces_* list
    # was empty in the JSON but whose mapping is documented in notes/BPR&D docs.
    # Applied after the loop so we don't conflict with per-section processing above.
    for manual_sec, manual_old_list in _MANUAL_OLD_SECTIONS.get(act_code, {}).items():
        if manual_sec not in enrichment_map:
            logger.warning(
                "Manual seed target %s/%s not found in enrichment_map — skipping",
                act_code, manual_sec,
            )
            continue
        existing = enrichment_map[manual_sec].replaces_old_sections
        added = []
        for old_sec in manual_old_list:
            if old_sec not in existing:
                existing.append(old_sec)
                added.append(old_sec)
        if added:
            logger.info(
                "Manual old-section seed applied: %s/%s added %s",
                act_code, manual_sec, added,
            )

    logger.info(
        "load_enrichment: act=%s sections_loaded=%d path=%s",
        act_code, len(enrichment_map), json_path.name,
    )
    return enrichment_map


def build_catalog(
    bns_path: Path,
    bnss_path: Path,
    bsa_path: Path,
) -> EnrichmentCatalog:
    """Load enrichment data for all three acts.

    Args:
        bns_path:  Path to bns_complete.json.
        bnss_path: Path to bnss_complete.json.
        bsa_path:  Path to bsa_complete.json.

    Returns:
        EnrichmentCatalog: {act_code: {section_number: SectionEnrichment}}
    """
    catalog: EnrichmentCatalog = {}
    for act_code, json_path in [
        ("BNS_2023", bns_path),
        ("BNSS_2023", bnss_path),
        ("BSA_2023", bsa_path),
    ]:
        catalog[act_code] = load_enrichment(json_path, act_code)

    total = sum(len(v) for v in catalog.values())
    logger.info("build_catalog: total_sections_enriched=%d", total)
    return catalog
