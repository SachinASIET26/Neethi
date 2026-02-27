"""Section-boundary-aware parser for Indian legal act text.

Takes the cleaned full-document text (output of text_cleaner.clean_legal_text)
and produces a list of ParsedSection dataclasses — one per section detected.

Also detects chapter headings and returns ParsedChapter objects so that
chapter_number can be resolved to a Roman numeral at parse time.

Design constraints (from neethi_data_pipeline_breakdown.md):
- No NLP libraries: structure detection is regex + positional, not linguistic.
- No LLM calls: this layer is purely deterministic.
- Preserves sub-section, illustration, explanation, and proviso boundaries.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedSection:
    section_number: str              # "103", "53A"
    section_title: str               # Title Case normalised heading
    raw_body_text: str               # Full body text (after heading, before next section)
    has_subsections: bool
    has_illustrations: bool
    has_explanations: bool
    has_provisos: bool
    subsection_texts: Dict[str, str] = field(default_factory=dict)
    # label → text for each structural unit (numbered, lettered, Explanation, Proviso, Illustration_A …)
    chapter_number: Optional[str] = None     # Roman numeral, e.g. "I", "II" — filled by parser
    chapter_title: Optional[str] = None


@dataclass
class ParsedChapter:
    chapter_number: str      # Roman numeral string: "I", "II", "XX"
    chapter_number_int: int  # Arabic integer: 1, 2, 20
    chapter_title: str       # Human-readable title


# ---------------------------------------------------------------------------
# Roman numeral utilities
# ---------------------------------------------------------------------------

# Full algorithmic Roman numeral parser — handles I through MMMCMXCIX (3999).
# This replaces the old limited lookup table (which only went to XXXIX=39).
# CPC First Schedule goes up to ORDER LI (51), so XL–LI must be supported.
_ROMAN_VALS: Dict[str, int] = {
    "M": 1000, "CM": 900, "D": 500, "CD": 400,
    "C": 100,  "XC": 90,  "L": 50,  "XL": 40,
    "X": 10,   "IX": 9,   "V": 5,   "IV": 4,  "I": 1,
}
_ROMAN_CHARS = frozenset("IVXLCDM")

# Pre-built int→Roman table for arabic_to_roman (Arabic chapters up to ~100)
_INT_TO_ROMAN_TABLE: List[Tuple[int, str]] = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"),  (90, "XC"), (50, "L"),  (40, "XL"),
    (10, "X"),   (9, "IX"),  (5, "V"),   (4, "IV"),  (1, "I"),
]


def _parse_roman(s: str) -> Optional[int]:
    """Parse a Roman numeral string; returns int or None if not a valid Roman."""
    s = s.strip().upper()
    if not s or not all(c in _ROMAN_CHARS for c in s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        val = _ROMAN_VALS.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total if total > 0 else None


def arabic_to_roman(n: int) -> str:
    """Convert a positive integer to a Roman numeral string."""
    if n <= 0:
        return str(n)
    result = []
    remaining = n
    for value, numeral in _INT_TO_ROMAN_TABLE:
        while remaining >= value:
            result.append(numeral)
            remaining -= value
    return "".join(result)


def roman_to_int(s: str) -> Optional[int]:
    """Convert a Roman numeral string to an integer. Returns None on failure."""
    return _parse_roman(s)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# BPR&D PDF section heading format (after PyMuPDF extraction):
#   "4. Punishments. \ufffdThe punishments..."     (space before separator)
#   "5. Commutation of sentence.\ufffdThe..."      (no space)
#   "7. Sentence may be (in certain cases) wholly or partly rigorous.\ufffdIn every..."
#
# The separator between heading and body text is U+FFFD (Unicode replacement character)
# produced by PyMuPDF when the em-dash byte(s) can't be decoded from the PDF font.
# Also handle actual U+2014 (—) and U+2013 (–) in case a PDF decodes properly.
#
# IMPORTANT: The table of contents contains identical "4. Punishments.\n" entries
# WITHOUT a body separator — these must NOT match. The separator is the discriminator.
_SECTION_SEP = r"[\ufffd\u2014\u2013\u2015]"  # FFFD | em-dash | en-dash | horizontal bar (U+2015, used in HSA/India Code civil PDFs)

_SECTION_HEADING_RE = re.compile(
    # group 1: section number (digits + optional capital letter)
    # group 2: heading text (title case)
    #   - Primary: chars on one line (no newline allowed)
    #   - Optional: ONE newline + continuation on second line
    #   This handles headings like:
    #     "10. Punishment of person ... doubtful \nof which.\ufffd..."
    #   The optional second line matches only when the full heading ends with
    #   ".\s*<separator>" — so TOC entries (no separator) are never matched.
    # group 3: separator character
    #   BNS/BNSS/BSA PDFs (BPR&D): U+FFFD (PyMuPDF replacement for em-dash)
    #   HSA/civil India Code PDFs:  U+2015 (HORIZONTAL BAR ―)
    #   IPC/CrPC PDFs:              U+2014 (em-dash —) or U+2013 (en-dash –)
    # The period before the separator is made optional (\.?) because some
    # India Code civil PDFs omit it.
    r"^(\d+[A-Z]?)\.\s+([A-Za-z][^\n\ufffd\u2014\u2013\u2015]*"
    r"(?:\n[^\n\ufffd\u2014\u2013\u2015]*)?)\.?\s*(" + _SECTION_SEP + r")",
    re.MULTILINE,
)

# CPC 1908 and similar India Code PDFs use a plain ASCII hyphen as separator:
#   "1. Short title, commencement and extent- (1) This Act may be cited..."
# No period before the hyphen. Lookahead (?=[A-Z\(\[]) ensures the hyphen is
# the section/body separator (body always starts with capital letter, "(" or
# "["), not a mid-word hyphen (e.g. "court-fee" → next char is lowercase).
_SECTION_HEADING_HYPHEN_SEP_RE = re.compile(
    r"^(\d+[A-Z]?)\.\s+([A-Za-z][^\n]*?)-\s+(?=[A-Z\(\[])",
    re.MULTILINE,
)

# CPC First Schedule structure detection patterns.
# CPC has two distinct structural layers:
#   Main body  — Sections 1–158 (jurisdiction, procedure, appeals, etc.)
#   First Schedule — Orders I–LI, each with Rules numbered from 1
# Rules are stored with compound section_number "I.1", "XXXIX.1" etc. to
# ensure uniqueness (every Order restarts Rule numbering from 1).
#
# NOTE: India Code PDFs center-align structural headings (FIRST SCHEDULE,
# ORDER I, etc.). PyMuPDF extracts centered text with a leading space, and
# normalize_unicode collapses multi-spaces to a single space — so the heading
# lands as " ORDER I" not "ORDER I" in the cleaned text. The ^\s* prefix
# allows leading whitespace so these headings are reliably detected.
_FIRST_SCHEDULE_RE = re.compile(
    r"^\s*(?:THE\s+)?FIRST\s+SCHEDULE\b",
    re.MULTILINE | re.IGNORECASE,
)
_SCHEDULE_ORDER_RE = re.compile(
    r"^\s*ORDER\s+((?:[IVXLCDM]+|\d+))\b",
    re.MULTILINE | re.IGNORECASE,
)

# Kept for backward-compat with fixture-text tests that use ALL-CAPS headings
_SECTION_HEADING_ALLCAPS_RE = re.compile(
    r"^(\d+[A-Z]?)\.\s+([A-Z][A-Z\s,\(\)\-\/\.]+?)\.\s*$",
    re.MULTILINE,
)

# Two-line heading continuation (ALL-CAPS legacy format)
_SECTION_HEADING_LINE1_RE = re.compile(
    r"^(\d+[A-Z]?)\.\s+([A-Z][A-Z\s,\(\)\-\/]+)\s*$",
    re.MULTILINE,
)

# Chapter heading: "CHAPTER I", "CHAPTER XIV", "CHAPTER 1" (BNSS uses Arabic)
_CHAPTER_HEADING_RE = re.compile(
    r"^CHAPTER\s+((?:[IVXLCDM]+|\d+))\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Chapter title line: follows the chapter number line
_CHAPTER_TITLE_RE = re.compile(
    r"^CHAPTER\s+((?:[IVXLCDM]+|\d+))\s*\n\s*([A-Z][A-Z\s,\-\']+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Sub-section patterns within a section body
_SUBSEC_NUMBERED_RE = re.compile(r"^\((\d+)\)\s+", re.MULTILINE)
_SUBSEC_LETTERED_RE = re.compile(r"^\(([a-z])\)\s+", re.MULTILINE)
_EXPLANATION_RE = re.compile(r"^Explanation\.[-–—]+\s*", re.MULTILINE)
_PROVISO_RE = re.compile(r"^Provided\s+that\b", re.MULTILINE)
_ILLUSTRATION_RE = re.compile(r"^Illustrations?\b", re.MULTILINE)

# Words to keep lowercase in title-case normalisation
_LOWER_WORDS = frozenset({
    "of", "and", "or", "the", "in", "to", "for", "a", "an",
    "by", "with", "on", "at", "from", "into", "under", "upon",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_title_case(heading: str) -> str:
    """Normalise an ALL-CAPS heading to Title Case.

    Preserves the first word as capitalised. Keeps LOWER_WORDS lowercase
    unless they are the first word.
    """
    words = heading.strip().split()
    if not words:
        return heading
    result = []
    for i, word in enumerate(words):
        if i == 0:
            result.append(word.capitalize())
        elif word.lower() in _LOWER_WORDS:
            result.append(word.lower())
        else:
            result.append(word.capitalize())
    return " ".join(result)


def _extract_subsections(body_text: str) -> Dict[str, str]:
    """Parse all structural units from a section body.

    Returns:
        Dict mapping label → text, e.g.:
        {"(1)": "...", "(2)": "...", "Explanation": "...", "Illustration_A": "..."}
    """
    boundaries: List[Tuple[int, str, str]] = []  # (position, label, type)

    for m in _SUBSEC_NUMBERED_RE.finditer(body_text):
        boundaries.append((m.start(), f"({m.group(1)})", "numbered"))

    for m in _SUBSEC_LETTERED_RE.finditer(body_text):
        boundaries.append((m.start(), f"({m.group(1)})", "lettered"))

    for m in _EXPLANATION_RE.finditer(body_text):
        boundaries.append((m.start(), "Explanation", "explanation"))

    for m in _PROVISO_RE.finditer(body_text):
        boundaries.append((m.start(), "Proviso", "proviso"))

    illus_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    illus_count = 0
    for m in _ILLUSTRATION_RE.finditer(body_text):
        label = f"Illustration_{illus_labels[illus_count % 26]}"
        boundaries.append((m.start(), label, "illustration"))
        illus_count += 1

    if not boundaries:
        return {}

    boundaries.sort(key=lambda x: x[0])

    result: Dict[str, str] = {}
    for i, (pos, label, _stype) in enumerate(boundaries):
        next_pos = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(body_text)
        sub_text = body_text[pos:next_pos].strip()
        if sub_text:
            result[label] = sub_text

    return result


def _parse_chapters(cleaned_text: str) -> List[ParsedChapter]:
    """Extract chapter headings from the document text.

    Handles both Roman numeral chapters (BNS, BSA) and Arabic numeral chapters (BNSS).
    Normalises all chapter numbers to Roman numerals.
    """
    chapters: List[ParsedChapter] = []
    seen: set = set()

    # Try to get both chapter number and title from two-line pattern
    for m in _CHAPTER_TITLE_RE.finditer(cleaned_text):
        num_raw = m.group(1).strip()
        title_raw = m.group(2).strip()

        # Normalise to Roman numeral
        roman, arabic = _normalise_chapter_num(num_raw)
        if roman and arabic and roman not in seen:
            seen.add(roman)
            chapters.append(ParsedChapter(
                chapter_number=roman,
                chapter_number_int=arabic,
                chapter_title=_to_title_case(title_raw),
            ))

    # Fall back: single-line chapter headings with no title on same match
    if not chapters:
        for m in _CHAPTER_HEADING_RE.finditer(cleaned_text):
            num_raw = m.group(1).strip()
            roman, arabic = _normalise_chapter_num(num_raw)
            if roman and arabic and roman not in seen:
                seen.add(roman)
                chapters.append(ParsedChapter(
                    chapter_number=roman,
                    chapter_number_int=arabic,
                    chapter_title="",
                ))

    chapters.sort(key=lambda c: c.chapter_number_int)
    return chapters


def _normalise_chapter_num(raw: str) -> Tuple[Optional[str], Optional[int]]:
    """Convert raw chapter number string to (roman_str, arabic_int) pair."""
    raw = raw.strip().upper()
    # Try as Roman numeral first
    arabic = roman_to_int(raw)
    if arabic is not None:
        return raw, arabic
    # Try as Arabic integer
    if raw.isdigit():
        n = int(raw)
        roman = arabic_to_roman(n)
        return roman, n
    return None, None


def _assign_chapters_to_sections(
    sections: List[ParsedSection],
    chapters: List[ParsedChapter],
    cleaned_text: str,
) -> None:
    """Assign chapter_number and chapter_title to each ParsedSection in place.

    Strategy: for each chapter heading found in the text, all sections
    that appear after it (until the next chapter heading) belong to it.
    """
    if not chapters:
        return

    # Build a list of (text_position_of_chapter_heading, chapter) pairs
    chapter_positions: List[Tuple[int, ParsedChapter]] = []
    for ch in chapters:
        # Find the position of "CHAPTER {number}" in the text
        pattern = re.compile(
            r"CHAPTER\s+" + re.escape(ch.chapter_number) + r"\b",
            re.IGNORECASE,
        )
        m = pattern.search(cleaned_text)
        if m:
            chapter_positions.append((m.start(), ch))
        else:
            # Also try Arabic form in case the text has Arabic numbers
            pattern_arabic = re.compile(
                r"CHAPTER\s+" + str(ch.chapter_number_int) + r"\b",
                re.IGNORECASE,
            )
            m2 = pattern_arabic.search(cleaned_text)
            if m2:
                chapter_positions.append((m2.start(), ch))

    if not chapter_positions:
        return

    chapter_positions.sort(key=lambda x: x[0])

    # Build section positions (approximate, using section number as anchor)
    for section in sections:
        # Find where this section heading appears in the text
        sec_pattern = re.compile(
            r"^" + re.escape(section.section_number) + r"\.\s+",
            re.MULTILINE,
        )
        m = sec_pattern.search(cleaned_text)
        if not m:
            continue
        sec_pos = m.start()

        # Find which chapter this section falls under
        assigned_chapter: Optional[ParsedChapter] = None
        for ch_pos, ch in chapter_positions:
            if ch_pos <= sec_pos:
                assigned_chapter = ch
            else:
                break

        if assigned_chapter:
            section.chapter_number = assigned_chapter.chapter_number
            section.chapter_title = assigned_chapter.chapter_title


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_act(cleaned_text: str) -> Tuple[List[ParsedSection], List[ParsedChapter]]:
    """Parse cleaned document text into structured section and chapter records.

    Args:
        cleaned_text: Output of clean_legal_text() — full document as one string.

    Returns:
        (sections, chapters):
            sections: List[ParsedSection], one per detected section.
            chapters: List[ParsedChapter], one per detected chapter heading.

    Notes:
        - chapter_number on each ParsedSection is always a Roman numeral string.
        - section_number is a string (handles "53A", "124A").
        - subsection_texts is only populated for sections that have structural units.
    """
    sections = _parse_sections(cleaned_text)
    chapters = _parse_chapters(cleaned_text)
    _assign_chapters_to_sections(sections, chapters, cleaned_text)
    return sections, chapters


def _parse_sections(cleaned_text: str) -> List[ParsedSection]:
    """Detect section boundaries and extract ParsedSection for each.

    Strategy:
    1. Primary: match BPR&D PDF format with U+FFFD/em-dash separator
       "4. Punishments.\ufffdThe punishments..."
    2. Fallback: match fixture-text ALL-CAPS format "4. PUNISHMENTS."
       (used in unit tests and for BSA/any PDF with different format)
    3. Deduplicate by start position.
    4. body_text starts AFTER the separator character (m.end()),
       ensuring the heading text is never included in the body.
    """
    # Tuples: (start_pos, body_start_pos, section_number, heading_title)
    all_matches: List[Tuple[int, int, str, str]] = []
    seen_positions: set = set()

    # Primary: BPR&D format with separator (excludes TOC entries)
    for m in _SECTION_HEADING_RE.finditer(cleaned_text):
        pos = m.start()
        if pos not in seen_positions:
            # Clean internal line breaks from two-line headings
            title = m.group(2).replace("\n", " ").strip()
            # body starts AFTER the separator character (group 3, the \ufffd or —)
            all_matches.append((pos, m.end(), m.group(1), title))
            seen_positions.add(pos)

    # Fallback: ALL-CAPS format (fixture texts, possibly BSA format)
    for m in _SECTION_HEADING_ALLCAPS_RE.finditer(cleaned_text):
        pos = m.start()
        if pos not in seen_positions:
            all_matches.append((pos, m.end(), m.group(1), m.group(2)))
            seen_positions.add(pos)

        # Handle two-line continuations for ALL-CAPS format
        # (skip if already seen)

    # Two-line ALL-CAPS headings not caught above
    for m in _SECTION_HEADING_LINE1_RE.finditer(cleaned_text):
        pos = m.start()
        if pos in seen_positions:
            continue
        rest = cleaned_text[m.end():]
        continuation = re.match(r"\n([A-Z\s,\(\)\-\/]+)\.\s*\n", rest)
        if continuation:
            full_title = m.group(2).strip() + " " + continuation.group(1).strip()
            combined_end = m.end() + continuation.end()
            all_matches.append((pos, combined_end, m.group(1), full_title))
            seen_positions.add(pos)

    # Plain hyphen separator (CPC 1908 and similar India Code civil PDFs).
    # ALWAYS runs — adds positions not already found by earlier patterns.
    # The `if pos not in seen_positions:` guard prevents double-matching,
    # so this is safe even when the primary em-dash/FFFD pattern found some
    # sections (e.g. due to encoding artifacts in India Code PDFs that put
    # a stray U+2015 horizontal bar on some footnote lines, causing the
    # primary pattern to fire on a handful of entries and incorrectly block
    # the entire hyphen fallback when `if not all_matches:` was the gate).
    #
    # CPC First Schedule awareness: when "FIRST SCHEDULE" and "ORDER [Roman]"
    # headings are present, Rules inside each Order are assigned compound section
    # numbers ("I.1", "XXXIX.1") to prevent collision — every Order restarts Rule
    # numbering from 1, so plain numbering would overwrite earlier Rules in the DB.

    _log.info(
        "pattern_counts: primary=%d allcaps=%d (before hyphen fallback)",
        sum(1 for t in all_matches),
        0,  # placeholder — all_matches already merged above
    )

    # Detect First Schedule boundary (CPC-specific)
    schedule_m = _FIRST_SCHEDULE_RE.search(cleaned_text)
    schedule_start = schedule_m.start() if schedule_m else len(cleaned_text)

    # Build ordered list of (position_after_heading, order_roman) for lookup
    order_map: List[Tuple[int, str]] = []
    for om in _SCHEDULE_ORDER_RE.finditer(cleaned_text, schedule_start):
        raw = om.group(1).strip().upper()
        roman, _ = _normalise_chapter_num(raw)
        if roman:
            order_map.append((om.end(), roman))

    _log.info(
        "hyphen_fallback: pre_existing=%d schedule_start=%s order_map_entries=%d first5=%s",
        len(all_matches),
        schedule_m.start() if schedule_m else "NOT_FOUND",
        len(order_map),
        order_map[:5],
    )

    def _order_at(pos: int) -> Optional[str]:
        """Return the current Order roman numeral for a position in the text."""
        current: Optional[str] = None
        for order_end, roman in order_map:
            if order_end <= pos:
                current = roman
            else:
                break
        return current

    hyphen_added = 0
    for m in _SECTION_HEADING_HYPHEN_SEP_RE.finditer(cleaned_text):
        pos = m.start()
        if pos not in seen_positions:
            title = m.group(2).strip()
            rule_num = m.group(1).strip()

            # Inside First Schedule → compound number ("XXXIX.1")
            # Outside First Schedule → plain number ("1", "9", "158")
            if pos >= schedule_start:
                order_roman = _order_at(pos)
                sec_num = f"{order_roman}.{rule_num}" if order_roman else rule_num
            else:
                sec_num = rule_num

            all_matches.append((pos, m.end(), sec_num, title))
            seen_positions.add(pos)
            hyphen_added += 1

    _log.info("hyphen_fallback: added %d sections via hyphen separator", hyphen_added)

    # Safety net: de-duplicate any remaining duplicate section numbers.
    # This handles: (a) ORDER detection gaps, (b) mixed PDF formats where
    # primary pattern found some sections and hyphen found overlapping numbers.
    # Duplicates are renamed by appending an occurrence counter ("1_1", "1_2").
    seen_nums: Dict[str, int] = {}
    deduped: List[Tuple[int, int, str, str]] = []
    for tup in sorted(all_matches, key=lambda x: x[0]):
        pos, body_start, sec_num, title = tup
        if sec_num in seen_nums:
            seen_nums[sec_num] += 1
            sec_num = f"{sec_num}_{seen_nums[sec_num]}"
        else:
            seen_nums[sec_num] = 0
        deduped.append((pos, body_start, sec_num, title))
    all_matches = deduped

    all_matches.sort(key=lambda x: x[0])

    if not all_matches:
        return []

    sections: List[ParsedSection] = []

    for i, (start, body_start, sec_num, title_raw) in enumerate(all_matches):
        # Body ends at the start of the next section heading
        next_start = all_matches[i + 1][0] if i + 1 < len(all_matches) else len(cleaned_text)
        body_text = cleaned_text[body_start:next_start].strip()

        has_subsections = bool(_SUBSEC_NUMBERED_RE.search(body_text))
        has_illustrations = bool(_ILLUSTRATION_RE.search(body_text))
        has_explanations = bool(_EXPLANATION_RE.search(body_text))
        has_provisos = bool(_PROVISO_RE.search(body_text))

        subsection_texts: Dict[str, str] = {}
        if has_subsections or has_explanations or has_provisos or has_illustrations:
            subsection_texts = _extract_subsections(body_text)

        sections.append(ParsedSection(
            section_number=sec_num.strip(),
            section_title=_to_title_case(title_raw.strip()),
            raw_body_text=body_text,
            has_subsections=has_subsections,
            has_illustrations=has_illustrations,
            has_explanations=has_explanations,
            has_provisos=has_provisos,
            subsection_texts=subsection_texts,
        ))

    return sections
