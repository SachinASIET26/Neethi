"""Extraction validation pipeline: 7 checks per section, confidence score.

Each section extracted from a BPR&D PDF passes through these checks before
being considered for PostgreSQL insertion and Qdrant indexing.

The extraction_confidence score drives routing decisions:
  >= 0.90 — high quality, index normally
  0.70 to 0.90 — acceptable, index with needs_review = True
  < 0.70 — route to human_review_queue, do NOT index to Qdrant

Defined in neethi_data_pipeline_breakdown.md Part 6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExtractionReport:
    section_id: str                       # section_number (e.g., "103", "53A")
    checks_run: int                        # total checks executed
    checks_passed: int                     # checks with no failure
    check_failures: List[str] = field(default_factory=list)   # human-readable messages
    extraction_confidence: float = 1.0    # 0.0 to 1.0
    requires_human_review: bool = False   # True if confidence < 0.70


# ---------------------------------------------------------------------------
# Detection patterns (mirrors text_cleaner.py — validators check AFTER cleaning)
# ---------------------------------------------------------------------------

# Check 1 — Footnote residue: digit(s) + "Section" + digit(s) at line start
_FOOTNOTE_RESIDUE_RE = re.compile(
    r"^\d{1,3}\s+Section\s+\d+",
    re.MULTILINE | re.IGNORECASE,
)

# Check 2 — Commentary residue: editorial trigger phrases survived cleaning
_COMMENTARY_RESIDUE_RE = re.compile(
    r"COMPARISON\s+WITH"
    r"|Modification\s*[&]\s*Addition"
    r"|Consolidation\s+and\s+Modifications"
    r"|COMPARISON\s+SUMMARY",
    re.IGNORECASE,
)

# Check 3 — Section boundary: a proper section heading (with em-dash/FFFD separator)
# appearing in legal_text must have a number matching this section.
# Requires the separator to avoid false-positives on numbered list items inside
# section bodies (e.g. "1. When one person..." inside Section 3 of ICA).
# Mirrors the separator logic in act_parser._SECTION_SEP.
_SECTION_HEADING_IN_TEXT_RE = re.compile(
    r"^(\d+[A-Z]?)\.\s+[A-Za-z][^\n\ufffd\u2014\u2013]*\.\s*[\ufffd\u2014\u2013]",
    re.MULTILINE,
)

# Check 4 — Bracket annotation residue: [number] or [date] or [text amount] patterns
_BRACKET_RESIDUE_RE = re.compile(
    r"\[\s*(?:"
    # Numeric amounts: [10 years], [50 rupees]
    r"\d[\d,\s]*(?:\s*(?:years?|months?|rupees?|days?))?"
    # Date annotations: [the 1st day of April, 1974]
    r"|the\s+\d+(?:st|nd|rd|th)?\s+day\s+of\s+[A-Za-z]+"
    # Text amounts: [ten years], [six months], [fifty rupees]
    r"|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
    r"|thousand|lakh|crore)(?:\s+\w+)*\s*(?:years?|months?|rupees?|days?)"
    r")\s*\]",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_section(
    section_number: str,
    legal_text: str,
    has_subsections: bool = False,
    sub_section_count: int = 0,
    expected_sub_sections: int = 0,
    is_offence: Optional[bool] = None,
    is_cognizable: Optional[bool] = None,
    is_bailable: Optional[bool] = None,
    triable_by: Optional[str] = None,
) -> ExtractionReport:
    """Run all 7 validation checks for a single extracted section.

    Args:
        section_number: e.g. "103", "53A".
        legal_text: the cleaned legal text for this section.
        has_subsections: True if parser detected (1), (2) etc.
        sub_section_count: actual sub-section rows extracted.
        expected_sub_sections: estimated from counting (N) patterns (0 = auto-count).
        is_offence: from offence_classifier (None = not yet classified).
        is_cognizable, is_bailable, triable_by: offence classification fields.

    Returns:
        ExtractionReport with confidence score, failure list, review flag.
    """
    failures: List[str] = []
    confidence = 1.0
    checks_run = 0
    checks_passed = 0

    # ------------------------------------------------------------------
    # Check 1 — Footnote residue
    # ------------------------------------------------------------------
    checks_run += 1
    if _FOOTNOTE_RESIDUE_RE.search(legal_text):
        failures.append(
            f"[{section_number}] Check 1 FAIL: Footnote residue found "
            f"(line starting with digit + 'Section' + digit). "
            f"Run remove_inline_footnotes again or re-extract from PDF."
        )
        confidence -= 0.31   # 0.31 ensures 1.0 - 0.31 = 0.69 < 0.70 → triggers review
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Check 2 — Comparison commentary residue
    # ------------------------------------------------------------------
    checks_run += 1
    if _COMMENTARY_RESIDUE_RE.search(legal_text):
        failures.append(
            f"[{section_number}] Check 2 FAIL: Editorial comparison commentary found "
            f"in legal_text (trigger phrase survived cleaning). "
            f"This section requires re-extraction."
        )
        confidence -= 0.40
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Check 3 — Section boundary integrity
    # ------------------------------------------------------------------
    checks_run += 1
    first_heading = _SECTION_HEADING_IN_TEXT_RE.search(legal_text)
    if first_heading:
        found_num = first_heading.group(1)
        if found_num != section_number:
            failures.append(
                f"[{section_number}] Check 3 FAIL: Cross-section contamination — "
                f"legal_text begins with section {found_num}'s content "
                f"(expected section {section_number}). "
                f"Discard legal_text and re-extract from PDF."
            )
            confidence -= 0.40
        else:
            checks_passed += 1
    else:
        checks_passed += 1  # No section heading in body is normal

    # ------------------------------------------------------------------
    # Check 4 — Bracket annotation residue
    # ------------------------------------------------------------------
    checks_run += 1
    if _BRACKET_RESIDUE_RE.search(legal_text):
        failures.append(
            f"[{section_number}] Check 4 FAIL: Comparison bracket annotation found "
            f"(e.g., '[ten years]' or '[the 1st day of April, 1974]'). "
            f"Run remove_comparison_brackets again."
        )
        confidence -= 0.20
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Check 5 — Legal text completeness
    # ------------------------------------------------------------------
    checks_run += 1
    text_len = len(legal_text.strip()) if legal_text else 0
    if text_len == 0:
        failures.append(
            f"[{section_number}] Check 5 FAIL: legal_text is empty. "
            f"Extraction failed entirely — extract directly from PDF."
        )
        confidence -= 0.50
    elif text_len < 20:
        failures.append(
            f"[{section_number}] Check 5 WARN: legal_text is suspiciously short "
            f"({text_len} characters). Verify against source PDF."
        )
        confidence -= 0.30
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Check 6 — Sub-section count consistency
    # ------------------------------------------------------------------
    checks_run += 1
    if has_subsections:
        # Auto-count expected sub-sections if not provided
        if expected_sub_sections == 0:
            expected_sub_sections = len(
                re.findall(r"^\(\d+\)", legal_text, re.MULTILINE)
            )

        if expected_sub_sections > 0 and sub_section_count == 0:
            failures.append(
                f"[{section_number}] Check 6 FAIL: has_subsections=True "
                f"but no sub-sections were extracted "
                f"(expected ~{expected_sub_sections})."
            )
            confidence -= 0.15
        elif expected_sub_sections > 0:
            discrepancy = (
                abs(expected_sub_sections - sub_section_count) / expected_sub_sections
            )
            if discrepancy > 0.20:
                failures.append(
                    f"[{section_number}] Check 6 WARN: Sub-section count discrepancy "
                    f"(expected ~{expected_sub_sections}, extracted {sub_section_count}, "
                    f"discrepancy={discrepancy:.0%})."
                )
                confidence -= 0.15
            else:
                checks_passed += 1
        else:
            checks_passed += 1
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Check 7 — Punishment field consistency (offence sections only)
    # ------------------------------------------------------------------
    checks_run += 1
    if is_offence is True:
        missing = []
        if is_cognizable is None:
            missing.append("is_cognizable")
        if is_bailable is None:
            missing.append("is_bailable")
        if triable_by is None:
            missing.append("triable_by")
        if missing:
            failures.append(
                f"[{section_number}] Check 7 WARN: Offence section missing "
                f"classification fields: {', '.join(missing)}. "
                f"Populate from BNSS Schedule I lookup table."
            )
            confidence -= 0.05 * len(missing)
        else:
            checks_passed += 1
    else:
        checks_passed += 1

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------
    confidence = max(0.0, min(1.0, confidence))

    return ExtractionReport(
        section_id=section_number,
        checks_run=checks_run,
        checks_passed=checks_passed,
        check_failures=failures,
        extraction_confidence=confidence,
        requires_human_review=(confidence < 0.70),
    )


# ---------------------------------------------------------------------------
# Batch validation helper
# ---------------------------------------------------------------------------

def validate_all_sections(
    sections: list,  # List[ParsedSection] from act_parser
) -> List[ExtractionReport]:
    """Run validate_section for every section in a parsed act.

    Args:
        sections: list of ParsedSection from act_parser.parse_act().

    Returns:
        List of ExtractionReport, one per section, in document order.
    """
    reports: List[ExtractionReport] = []
    for sec in sections:
        sub_count = len(sec.subsection_texts) if hasattr(sec, "subsection_texts") else 0
        report = validate_section(
            section_number=sec.section_number,
            legal_text=sec.raw_body_text,
            has_subsections=sec.has_subsections,
            sub_section_count=sub_count,
        )
        reports.append(report)
    return reports
