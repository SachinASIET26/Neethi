"""Rule-based offence classifier for BNS sections.

This is NOT an LLM call. It is a deterministic classifier that reads the
legal_text of each BNS section and determines offence classification fields
using pattern matching and a BNSS Schedule I lookup table.

CRITICAL: punishment_max_years = 99999 means life imprisonment (sentinel integer).

Classification logic:
1. is_offence: TRUE if the section defines/describes a criminal offence
   (detected by punishment keyword patterns in legal_text).
2. punishment_type/max_years/min_years: extracted by regex from legal_text.
3. is_cognizable, is_bailable, triable_by: from BNSS Schedule I lookup.
   If no Schedule I entry exists, fields are left NULL — never guessed.

Schedule I data lives in backend/db/seed_data/bnss_schedule_1.json.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Offence detection patterns
# ---------------------------------------------------------------------------

# Primary offence indicators — section describes a criminal offence
_OFFENCE_PATTERNS = [
    re.compile(r"\bshall\s+be\s+punished\b", re.IGNORECASE),
    re.compile(r"\bshall\s+be\s+liable\b", re.IGNORECASE),
    re.compile(r"\bimprisonment.*?fine\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bpunishable\s+with\b", re.IGNORECASE),
    re.compile(r"\bimprisonment\s+(?:for|which\s+may\s+extend)\b", re.IGNORECASE),
]

# NOT an offence: definition, procedural, punishment-type definitions
_NOT_OFFENCE_HINTS = [
    re.compile(r"^\d+\.\s+(?:DEFINITIONS?|SHORT\s+TITLE|APPLICATION)\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bfor\s+the\s+purposes?\s+of\s+this\s+(?:section|act|chapter)\b", re.IGNORECASE),
    re.compile(r"\bmeans\s+and\s+includes?\b", re.IGNORECASE),
]

# "imprisonment for life" sentinel
_LIFE_IMPRISONMENT_RE = re.compile(r"\bimprisonment\s+for\s+life\b", re.IGNORECASE)

# "death" penalty
_DEATH_PENALTY_RE = re.compile(r"\bpunished\s+with\s+death\b|\bdeath\s+penalty\b", re.IGNORECASE)

# Imprisonment duration patterns
_YEARS_RE = re.compile(
    r"imprisonment\s+(?:for|which\s+may\s+extend\s+to)\s+(\d+(?:\.\d+)?)\s+years?",
    re.IGNORECASE,
)
_MONTHS_RE = re.compile(
    r"imprisonment\s+(?:for|which\s+may\s+extend\s+to)\s+(\d+(?:\.\d+)?)\s+months?",
    re.IGNORECASE,
)
_MIN_YEARS_RE = re.compile(
    r"imprisonment\s+(?:of|for)\s+not\s+less\s+than\s+(\d+(?:\.\d+)?)\s+years?",
    re.IGNORECASE,
)

# Fine patterns
_FINE_RUPEES_RE = re.compile(
    r"fine\s+(?:which\s+may\s+extend\s+to|of)\s+(?:rupees\s+)?(\d[\d,]*)",
    re.IGNORECASE,
)
_FINE_LAKH_RE = re.compile(
    r"fine\s+(?:which\s+may\s+extend\s+to|of)\s+(?:rupees\s+)?(\d[\d,]*)\s+lakh",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Punishment type constants
# ---------------------------------------------------------------------------

LIFE_IMPRISONMENT = 99999   # sentinel — matches schema documentation


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

@dataclass
class OffenceClassification:
    """Offence classification fields for a single section."""

    is_offence: bool = False
    punishment_type: Optional[str] = None       # e.g. "death,life_imprisonment,fine"
    punishment_min_years: Optional[float] = None
    punishment_max_years: Optional[float] = None  # 99999 = life imprisonment
    punishment_fine_max: Optional[int] = None
    is_cognizable: Optional[bool] = None         # from BNSS Schedule I; None = not classified
    is_bailable: Optional[bool] = None
    triable_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Schedule I lookup
# ---------------------------------------------------------------------------

_SCHEDULE_I_CACHE: Optional[Dict[str, Dict[str, dict]]] = None
_SCHEDULE_I_PATH = (
    Path(__file__).parents[2] / "db" / "seed_data" / "bnss_schedule_1.json"
)


def _load_schedule_i() -> Dict[str, Dict[str, dict]]:
    """Load BNSS Schedule I data from seed file (cached in-process)."""
    global _SCHEDULE_I_CACHE
    if _SCHEDULE_I_CACHE is not None:
        return _SCHEDULE_I_CACHE

    if not _SCHEDULE_I_PATH.exists():
        logger.warning(
            "BNSS Schedule I file not found at %s — is_cognizable/is_bailable/triable_by "
            "will be NULL for all sections. Populate this file to enable full classification.",
            _SCHEDULE_I_PATH,
        )
        _SCHEDULE_I_CACHE = {}
        return _SCHEDULE_I_CACHE

    with open(_SCHEDULE_I_PATH, encoding="utf-8") as f:
        data = json.load(f)

    _SCHEDULE_I_CACHE = data
    total = sum(len(v) for v in data.values())
    logger.info("_load_schedule_i: loaded %d entries from %s", total, _SCHEDULE_I_PATH.name)
    return _SCHEDULE_I_CACHE


def _lookup_schedule_i(
    act_code: str, section_number: str
) -> Optional[dict]:
    """Return Schedule I entry for (act_code, section_number), or None."""
    schedule = _load_schedule_i()
    return schedule.get(act_code, {}).get(section_number)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_punishment_type(legal_text: str) -> Tuple[List[str], Optional[float], Optional[float], Optional[int]]:
    """Extract punishment components from legal_text.

    Returns:
        (punishment_types, min_years, max_years, fine_max_rupees)
    """
    types: List[str] = []
    max_years: Optional[float] = None
    min_years: Optional[float] = None
    fine_max: Optional[int] = None

    # Death penalty
    if _DEATH_PENALTY_RE.search(legal_text):
        types.append("death")

    # Life imprisonment
    if _LIFE_IMPRISONMENT_RE.search(legal_text):
        types.append("life_imprisonment")
        max_years = float(LIFE_IMPRISONMENT)

    # N years — find maximum
    years_matches = _YEARS_RE.findall(legal_text)
    if years_matches:
        numeric_years = [float(y) for y in years_matches]
        candidate_max = max(numeric_years)
        # Only use if not already set to life
        if max_years is None or candidate_max > max_years:
            max_years = candidate_max
        if "imprisonment" not in types:
            types.append("imprisonment")

    # N months — convert to years
    months_matches = _MONTHS_RE.findall(legal_text)
    if months_matches:
        numeric_months = [float(m) / 12 for m in months_matches]
        candidate_max = max(numeric_months)
        if max_years is None or (max_years < LIFE_IMPRISONMENT and candidate_max > max_years):
            max_years = candidate_max
        if "imprisonment" not in types:
            types.append("imprisonment")

    # Minimum imprisonment
    min_matches = _MIN_YEARS_RE.findall(legal_text)
    if min_matches:
        min_years = min(float(m) for m in min_matches)

    # Fine — check for lakh first, then plain rupees
    lakh_matches = _FINE_LAKH_RE.findall(legal_text)
    rupees_matches = _FINE_RUPEES_RE.findall(legal_text)

    if lakh_matches:
        # "rupees 5 lakh" — the N in the regex is already extracted
        raw = lakh_matches[0].replace(",", "")
        try:
            fine_max = int(float(raw) * 100_000)
            types.append("fine")
        except ValueError:
            pass
    elif rupees_matches:
        raw = rupees_matches[0].replace(",", "")
        try:
            fine_max = int(raw)
            types.append("fine")
        except ValueError:
            pass

    return types, min_years, max_years, fine_max


def _is_offence_section(legal_text: str) -> bool:
    """Determine if a section defines a criminal offence.

    Returns False for definition sections, procedural sections, and
    punishment-type-only sections (which define penalties but don't
    themselves create offences).
    """
    if not legal_text or len(legal_text.strip()) < 20:
        return False

    # Check for explicit offence pattern
    has_offence_pattern = any(p.search(legal_text) for p in _OFFENCE_PATTERNS)
    if not has_offence_pattern:
        return False

    # Exclude definitions/procedural — these have offence-like language in context
    # but are NOT offence-defining sections themselves
    has_not_offence = any(p.search(legal_text) for p in _NOT_OFFENCE_HINTS)
    # Only exclude if it looks like a pure definition section (very strong signal)
    first_line = legal_text.strip().split("\n")[0]
    is_definition_heading = bool(re.match(
        r"^\d+\.\s+(?:DEFINITIONS?|SHORT\s+TITLE|APPLICATION|GENERAL\s+EXPLANATIONS?)\.",
        first_line,
        re.IGNORECASE,
    ))
    if is_definition_heading:
        return False

    return True


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_offence(
    section_number: str,
    legal_text: str,
    act_code: str = "BNS_2023",
) -> OffenceClassification:
    """Run offence classification for a single section.

    Args:
        section_number: e.g. "103", "64".
        legal_text:     cleaned legal text from PDF extractor.
        act_code:       canonical act code (default "BNS_2023").

    Returns:
        OffenceClassification with all fields populated where determinable.
        Fields that cannot be determined are left as None (never guessed).
    """
    result = OffenceClassification()

    if not legal_text or not legal_text.strip():
        return result

    # Step 1: is_offence
    result.is_offence = _is_offence_section(legal_text)

    if not result.is_offence:
        return result

    # Step 2: punishment fields from legal_text
    types, min_years, max_years, fine_max = _extract_punishment_type(legal_text)

    if types:
        result.punishment_type = ",".join(types)
    result.punishment_min_years = min_years
    result.punishment_max_years = max_years
    result.punishment_fine_max = fine_max

    # Step 3: cognizable/bailable/triable_by from BNSS Schedule I
    schedule_entry = _lookup_schedule_i(act_code, section_number)
    if schedule_entry:
        result.is_cognizable = schedule_entry.get("is_cognizable")
        result.is_bailable = schedule_entry.get("is_bailable")
        result.triable_by = schedule_entry.get("triable_by")
    # If no Schedule I entry: leave as None — do NOT guess

    return result


def classify_act_sections(
    sections: list,  # List[ParsedSection]
    act_code: str = "BNS_2023",
) -> Dict[str, OffenceClassification]:
    """Run classify_offence for every section in a parsed act.

    Args:
        sections: list of ParsedSection objects from act_parser.parse_act().
        act_code: canonical act code.

    Returns:
        Dict mapping section_number → OffenceClassification.
    """
    results: Dict[str, OffenceClassification] = {}
    offence_count = 0
    for sec in sections:
        clf = classify_offence(
            section_number=sec.section_number,
            legal_text=sec.raw_body_text,
            act_code=act_code,
        )
        results[sec.section_number] = clf
        if clf.is_offence:
            offence_count += 1

    logger.info(
        "classify_act_sections: act=%s total=%d offences=%d",
        act_code, len(sections), offence_count,
    )
    return results
