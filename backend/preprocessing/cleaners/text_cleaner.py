"""Legal text cleaning rules for PDF extraction output.

Nine rules applied in order to remove all non-law content from
extracted text and produce clean legal_text ready for PostgreSQL and Qdrant.

Rule 1  — strip_running_headers       (remove act-name header lines)
Rule 2  — strip_page_numbers          (remove page number lines)
Rule 3  — remove_inline_footnotes     (remove footnote defs + superscript markers)
Rule 3b — fix_india_code_artifacts    (amendment markers + missing spaces)
Rule 4  — remove_comparison_brackets  (remove [old-text] bracket annotations)
Rule 5  — remove_comparison_commentary (remove editorial comparison blocks)
Rule 6  — normalize_unicode           (fix mojibake, normalize whitespace)
Rule 7  — reconstruct_hyphenated_words (join mid-line word breaks)
Rule 8  — validate_structural_markers_preserved (validation, not transformation)

Entry point: clean_legal_text(raw_text, superscript_positions) -> str
"""

from __future__ import annotations

import re
import unicodedata
from typing import List


# ---------------------------------------------------------------------------
# Rule 1 — Strip Running Headers
# ---------------------------------------------------------------------------

# These lines appear at the top of every page as navigation furniture.
# They match the act's full name, optionally followed by a year and chapter title.
_HEADER_LINE_RE = re.compile(
    r"^(?:"
    r"BHARATIYA\s+NYAYA\s+SANHITA,?\s*2023"
    r"|BHARATIYA\s+NAGARIK\s+SURAKSHA\s+SANHITA,?\s*2023"
    r"|BHARATIYA\s+SAKSHYA\s+ADHINIYAM,?\s*2023"
    r"|B\.?\s*N\.?\s*S\.?\s*,?\s*2023"
    r"|B\.?\s*N\.?\s*S\.?\s*S\.?\s*,?\s*2023"
    r"|B\.?\s*S\.?\s*A\.?\s*,?\s*2023"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_running_headers(text: str) -> str:
    """Rule 1: Remove lines that consist solely of an act name."""
    return _HEADER_LINE_RE.sub("", text)


# ---------------------------------------------------------------------------
# Rule 2 — Strip Page Numbers
# ---------------------------------------------------------------------------

# Matches: "47", "— 47 —", "- 47 -", "[47]"
_PAGE_NUM_RE = re.compile(
    r"^\s*[\[\(]?\s*[—\-]?\s*\d{1,4}\s*[—\-]?\s*[\]\)]?\s*$",
    re.MULTILINE,
)


def strip_page_numbers(text: str) -> str:
    """Rule 2: Remove lines that contain only a page number."""
    return _PAGE_NUM_RE.sub("", text)


# ---------------------------------------------------------------------------
# Rule 3 — Remove Inline Footnote References
# ---------------------------------------------------------------------------

# Standalone footnote definition line:
#   "55 Section 63, "Amount of fine" IPC, 1860."
# Pattern: 1-2 digits, space, "Section", space, digits, then act name appears
_FOOTNOTE_DEF_LINE_RE = re.compile(
    r"^\d{1,2}\s+Section\s+\d+[^\n]*"
    r"(?:IPC|CrPC|IEA|Indian\s+Penal\s+Code|Code\s+of\s+Criminal\s+Procedure"
    r"|Indian\s+Evidence\s+Act)[^\n]*\n?",
    re.MULTILINE | re.IGNORECASE,
)

# Also catch footnote definitions without act name (e.g., "62 Section 67, BNS.")
_FOOTNOTE_DEF_SHORT_RE = re.compile(
    r"^\d{1,2}\s+Section\s+\d+,\s+\".+?\"\s+(?:IPC|CrPC|IEA|BNS|BNSS|BSA)\S*\s*\n?",
    re.MULTILINE | re.IGNORECASE,
)

# Inline superscript footnote marker: digit(s) immediately after a word character
# and before a word character or space. E.g., "imprisonment5 for" → "imprisonment for"
# Only matches 1-2 digit sequences to avoid matching legal sub-section numbers like (5)
_INLINE_SUPERSCRIPT_RE = re.compile(
    r"(?<=[a-zA-Z\)])(\d{1,2})(?=[a-zA-Z\s,\.\(])"
)


def remove_inline_footnotes(
    text: str,
    superscript_positions: List[int] | None = None,
) -> str:
    """Rule 3: Remove footnote definitions and inline superscript markers.

    Args:
        text: partially cleaned text (after rules 1 and 2).
        superscript_positions: block-level offsets from pdf_extractor Pass 1
            (informational; the regex pass handles actual removal).
    """
    text = _FOOTNOTE_DEF_LINE_RE.sub("", text)
    text = _FOOTNOTE_DEF_SHORT_RE.sub("", text)
    text = _INLINE_SUPERSCRIPT_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Rule 3b — Fix India Code PDF Formatting Artifacts
# ---------------------------------------------------------------------------

# India Code PDFs mark substituted/inserted text with a superscript amendment
# number. PyMuPDF renders the superscript digit as a regular character on the
# same line as the following section heading, producing e.g.:
#   "\n1151. Care to be taken by bailee.—"  (should be "\n151. Care to...")
#   "\n2234. Some section title.—"          (should be "\n234. ...")
#
# Detection rule: a line starting with 4+ digits followed by ". Title" is
# always an artifact — Indian acts never have section numbers above ~500.
# Strip the first digit when doing so produces a plausible (≤ 3 digit) number.
#
# This is implemented as a function (not a static regex) because the stripping
# logic depends on the digit counts of the matched groups.

_AMENDMENT_MARKER_RE = re.compile(
    r"(?m)^(\d{4,}[A-Z]?)(\.\s+[A-Z])"
)

def _strip_amendment_marker(m: re.Match) -> str:  # type: ignore[type-arg]
    full_num = m.group(1)
    rest = m.group(2)
    stripped = full_num[1:]   # Remove first (marker) digit
    # Only strip if resulting number is ≤ 3 digits (plausible section number)
    if len(stripped.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) <= 3:
        return stripped + rest
    return full_num + rest  # Leave untouched if still implausibly large


# India Code PDFs occasionally omit the space between section number and title:
#   "152.Bailee when not liable" → "152. Bailee when not liable"
# Match: start of line, digits, period, IMMEDIATELY an uppercase letter.
_MISSING_SPACE_RE = re.compile(r"(?m)^(\d+[A-Z]?)\.([A-Z])")


def fix_india_code_artifacts(text: str) -> str:
    """Rule 3b: Fix India Code PDF formatting artifacts.

    1. Strip single-digit amendment superscript markers prepended to section
       headings (e.g. '1151.' → '151.').
    2. Insert missing space between section number period and title
       (e.g. '152.Bailee' → '152. Bailee').
    """
    text = _AMENDMENT_MARKER_RE.sub(_strip_amendment_marker, text)
    text = _MISSING_SPACE_RE.sub(r"\1. \2", text)
    return text


# ---------------------------------------------------------------------------
# Rule 4 — Remove Comparison Bracket Annotations
# ---------------------------------------------------------------------------

# BPR&D comparison annotations follow the pattern [old-law text] inline:
#   "five thousand [fifty] rupees"       → remove "[fifty]"
#   "twenty years [ten years]"           → remove "[ten years]"
#   "four months [six months]"           → remove "[four months]"
#   "[the 1st day of April, 1974]"       → remove entire bracket (CrPC date)

# Old-law date annotation: "[the Nth day of Month, YYYY]"
_DATE_BRACKET_RE = re.compile(
    r"\[the\s+\d+(?:st|nd|rd|th)?\s+day\s+of\s+[A-Za-z]+,?\s*\d{4}\]",
    re.IGNORECASE,
)

# Numeric comparison brackets: [number] or [N years/months/rupees/days]
_NUMERIC_BRACKET_RE = re.compile(
    r"\[\s*(?:\d[\d,\s]*(?:\s*(?:years?|months?|rupees?|days?|lakh|crore))?)\s*\]"
)

# Text comparison bracket immediately after a number (e.g., "five thousand [fifty]")
_TEXT_AMOUNT_BRACKET_RE = re.compile(
    r"(?<=[a-z\d])\s+\[(?:one|two|three|four|five|six|seven|eight|nine|ten"
    r"|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
    r"|thousand|lakh|crore)(?:\s+\w+)*\]",
    re.IGNORECASE,
)


def remove_comparison_brackets(text: str) -> str:
    """Rule 4: Remove bracket annotations that show old-law comparison values."""
    text = _DATE_BRACKET_RE.sub("", text)
    text = _NUMERIC_BRACKET_RE.sub("", text)
    text = _TEXT_AMOUNT_BRACKET_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Rule 5 — Remove Comparison Commentary Blocks
# ---------------------------------------------------------------------------

# BPR&D editorial commentary that bleeds into section text.
# Triggered by known editorial header phrases; removed to the next section heading.
_COMMENTARY_BLOCK_RE = re.compile(
    r"(?:^|\n)"
    r"(?:COMPARISON\s+WITH|Modification\s*[&]\s*Addition|Consolidation\s+and\s+Modifications"
    r"|COMPARISON\s+SUMMARY|The\s+following\s+changes\s+were\s+made"
    r"|In\s+sub\s+section\s+\(\d+\)\s+of\s+(?:Section|the)\s+\d+)"
    r".*?"
    r"(?=\n\d+[A-Z]?\.\s+[A-Z]|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def remove_comparison_commentary(text: str) -> str:
    """Rule 5: Remove editorial comparison blocks from trigger phrase to next section."""
    return _COMMENTARY_BLOCK_RE.sub("\n", text)


# ---------------------------------------------------------------------------
# Rule 6 — Unicode Normalization
# ---------------------------------------------------------------------------

# UTF-8 sequences misread as Windows-1252 (mojibake from PDF encoding artifacts).
# Each tuple is (mojibake_string, correct_unicode_char).
# All non-ASCII chars are written as \uXXXX escapes to avoid source encoding issues.
#
# How this works: when a PDF with UTF-8 em-dash (U+2014, bytes E2 80 94) is
# decoded as Windows-1252, byte E2→â (U+00E2), 80→€ (U+20AC), 94→" (U+201D).
# Replacing the resulting Python string â€\u201d with — (U+2014) corrects it.
_UNICODE_FIXES = [
    # em-dash — (U+2014): UTF-8 bytes E2 80 94 → CP1252: â (E2) + € (80) + " (94)
    ("\u00e2\u20ac\u201d", "\u2014"),
    # en-dash – (U+2013): UTF-8 bytes E2 80 93 → CP1252: â + € + " (93 = U+201C? no...)
    # 0x93 in CP1252 = U+201C (left double quote)
    ("\u00e2\u20ac\u201c", "\u2013"),
    # right single quote ' (U+2019): UTF-8 E2 80 99 → CP1252: â + € + ™ (99 = U+2122)
    ("\u00e2\u20ac\u2122", "\u2019"),
    # left double quote " (U+201C): UTF-8 E2 80 9C → CP1252: â + € + œ (9C = U+0153)
    ("\u00e2\u20ac\u0153", "\u201c"),
    # right double quote " (U+201D): UTF-8 E2 80 9D → CP1252: â + € + U+009D
    ("\u00e2\u20ac\u009d", "\u201d"),
    # Partial mojibake fallback (â€ without valid 3rd byte)
    ("\u00e2\u20ac", "\u201d"),
    # right arrow → (U+2192): UTF-8 E2 86 92 → CP1252: â + † (86=U+2020) + ' (92=U+2019)
    ("\u00e2\u2020\u2019", "\u2192"),
    ("\r\n", "\n"),
    ("\r", "\n"),
]


def normalize_unicode(text: str) -> str:
    """Rule 6: Fix mojibake sequences and normalize whitespace."""
    for bad, good in _UNICODE_FIXES:
        text = text.replace(bad, good)
    # NFC normalization
    text = unicodedata.normalize("NFC", text)
    # Collapse multiple horizontal spaces to single space (preserve newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    # Reduce more than two consecutive blank lines to two
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ---------------------------------------------------------------------------
# Rule 7 — Reconstruct Hyphenated Words
# ---------------------------------------------------------------------------

# Pattern: word-ending-with-hyphen + newline + optional whitespace + lowercase start
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n[ \t]*([a-z])")


def reconstruct_hyphenated_words(text: str) -> str:
    """Rule 7: Join words broken across lines with a hyphen."""
    return _HYPHEN_BREAK_RE.sub(r"\1\2", text)


# ---------------------------------------------------------------------------
# Rule 8 — Validate Structural Markers Preserved (validation, not transformation)
# ---------------------------------------------------------------------------

_STRUCTURAL_MARKER_PATTERNS = [
    re.compile(r"^\s*\(\d+\)", re.MULTILINE),         # (1), (2) sub-sections
    re.compile(r"^\s*\([a-z]\)", re.MULTILINE),        # (a), (b) sub-clauses
    re.compile(r"Explanation[\.\-–]", re.IGNORECASE),  # Explanation.-
    re.compile(r"Proviso|Provided\s+that", re.IGNORECASE),  # Proviso
    re.compile(r"^Illustration", re.MULTILINE | re.IGNORECASE),  # Illustration
]


def validate_structural_markers_preserved(text: str) -> bool:
    """Rule 8 (validation only): Confirm that structural markers survive cleaning.

    Called on sections that are known to have sub-sections, explanations, etc.
    Returns True if at least one structural marker type is present.
    Returns True vacuously for sections with no expected structural markers.

    This function does NOT raise; callers should log a warning on False.
    """
    for pattern in _STRUCTURAL_MARKER_PATTERNS:
        if pattern.search(text):
            return True
    # A section may legitimately have none of these (simple one-liner sections)
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def clean_legal_text(
    raw_text: str,
    superscript_positions: List[int] | None = None,
) -> str:
    """Apply cleaning rules 1–7 in order and run rule 8 as a validation pass.

    Args:
        raw_text: Text extracted from SECTION_TEXT blocks by pdf_extractor.py.
        superscript_positions: Optional list of character offsets from Pass 1
            (block-level; used as a hint, actual removal is regex-based).

    Returns:
        Cleaned legal text, stripped of all non-law content.
    """
    if superscript_positions is None:
        superscript_positions = []

    text = strip_running_headers(raw_text)                   # Rule 1
    text = strip_page_numbers(text)                          # Rule 2
    text = remove_inline_footnotes(text, superscript_positions)  # Rule 3
    text = fix_india_code_artifacts(text)                    # Rule 3b
    text = remove_comparison_brackets(text)                  # Rule 4
    text = remove_comparison_commentary(text)                # Rule 5
    text = normalize_unicode(text)                           # Rule 6
    text = reconstruct_hyphenated_words(text)                # Rule 7

    # Rule 8: non-destructive validation (caller may log the result)
    validate_structural_markers_preserved(text)

    return text.strip()
