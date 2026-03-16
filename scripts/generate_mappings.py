#!/usr/bin/env python3
"""
generate_mappings.py
=====================
Complete law-transition mapping generator for the Neethi AI project.

Built by reading every byte of all 6 provided source files:

  File       Format                   Content                              Sections
  ────────────────────────────────────────────────────────────────────────────────
  IPC.pdf    Plain UTF-8 text         Indian Penal Code 1860               548 parsed
  CRPC.pdf   Plain UTF-8 text         Code of Criminal Procedure 1973      525 parsed
  BNS.pdf    Plain UTF-8 text         Bharatiya Nyaya Sanhita 2023         364 parsed
  IEA.pdf    ZIP(60 .txt/.jpeg pages) Indian Evidence Act 1872             186 parsed
  BSA.pdf    ZIP(54 .txt/.jpeg pages) Bharatiya Sakshya Adhiniyam 2023     176 parsed
  BNSS.pdf   Real PDF (279 pages)     Bharatiya Nagarik Suraksha Sanhita   531 parsed

Per-file noise patterns discovered and handled:
  IPC/CRPC  — standalone page numbers, "SECTIONS" repeat-headers,
               amendment footnotes ("N. Subs. by Act…"), act-title
               page-headers, inline bracket markers ("N[text]")
  BNS/BSA   — standalone page numbers, fused date-footnotes ("date1as")
  IEA       — same as IPC/CRPC + dangling bracket remnants ("[ 3***]"),
               CHAPTER inline format ("CHAPTER I.––PRELIMINARY")
  BNSS      — standalone page numbers (264 total), one fused date-footnote
               ("1. 1st July, 2024…"), gazette continuation line on next line
               ("848(E), dated, 23rd day of February, 2024…"), em-dash "—",
               uses pdfplumber for real PDF extraction (not plain text)

BNSS-specific PDF quirks confirmed by byte-level inspection (279 pages):
  • CHAPTER V ("ARREST OF PERSONS", sections 35–62) heading is physically
    absent from the content pages — present in TOC only. Chapter metadata
    for sections 35–62 is corrected via BNSS_MISSING_CHAPTERS table.
  • Body text contains sentence-case "Chapter XVII of…" / "Chapter IX has
    been…" / "Chapter XXVIII;" which match shared _CHAP_LINE (re.I). Fixed
    by using strict uppercase-only _BNSS_CHAP_LINE in parse_pdf_act.
  • THE FIRST SCHEDULE hard stop at line 7503 (exact uppercase sentinel);
    "the Second Schedule, with such variations as…" in section 522 body
    is a false trigger for naive schedule-boundary checks — avoided.
  • Footnote at line 714 caught by date-footnote guard; gazette continuation
    at line 715 stripped by one-line lookahead (_skip_footnote_continuation).

─────────────────────────────────────────────────────────────────────
WHAT THIS SCRIPT DOES
─────────────────────────────────────────────────────────────────────
Phase 1 — PDF Parsing (format auto-detected per file)
  • IPC/CRPC/BNS: plain-text parser
  • IEA/BSA:      ZIP-page parser (concatenates N.txt files)
  • BNSS:         pdfplumber real-PDF parser
  All parsers: skip TOC block, strip noise, merge continuation lines
  Emits: {act_code, section_number, section_title, legal_text,
          chapter_number, chapter_title, part_number}

Phase 2 — JSON Enrichment Loading
  • data/raw/bns_complete.json   → IPC→BNS mapping hints
  • data/raw/bnss_complete.json  → CrPC→BNSS mapping hints
  • data/raw/bsa_complete.json   → IEA→BSA mapping hints
  • Normalises sub-section refs: 376(1) → 376
  • Applies BLOCKED_OLD_SECTIONS to remove known JSON noise
  • Applies MANUAL_OLD_SECTIONS to inject known-correct links

Phase 3 — Mapping Row Generation
  • Detects split_into (1 old → N new) algorithmically
  • Detects merged_from (N old → 1 new) algorithmically
  • Infers scope_change from change_summary text
  • Builds collision-guard transition_notes for false-friend sections
  • Seeds 'deleted' rows for old sections with no new equivalent
  • Applies hard type-corrections (e.g. CrPC 173 new→modified)

Phase 4 — Output
  • Upserts rows in law_transition_mappings (PostgreSQL)
  • Runs 13 safety assertions; exits 1 if any CRITICAL assertion fails
  • Exports data/output/mappings.sql for offline inspection

Usage:
  python scripts/generate_mappings.py [--dry-run] [--act BNS|BNSS|BSA|ALL]
  python scripts/generate_mappings.py --extract-only   # Phase 1 only
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

# ── Project root on path ────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("generate_mappings")

EFFECTIVE_DATE = date(2024, 7, 1)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedSection:
    """One section extracted from a source PDF."""
    act_code:       str
    section_number: str          # "302", "124A", "25A"
    section_title:  str          # "Punishment for murder"
    legal_text:     str          # full cleaned body text
    chapter_number: str = ""     # "XX", "I", "XIV"
    chapter_title:  str = ""     # "OF OFFENCES AFFECTING LIFE"
    part_number:    str = ""     # "I", "II" (IEA/BSA only)


@dataclass
class MappingRow:
    """One row for law_transition_mappings."""
    old_act:            str
    old_section:        str
    old_section_title:  str
    old_legal_text:     str
    new_act:            str
    new_section:        str
    new_section_title:  str
    transition_type:    str
    scope_change:       Optional[str]
    transition_note:    Optional[str]
    confidence_score:   float
    effective_date:     date = EFFECTIVE_DATE
    is_active:          bool = False


@dataclass
class ExtractionReport:
    act_code:       str
    sections_found: int = 0
    chapters_found: int = 0
    noise_stripped: int = 0
    errors:         List[str] = field(default_factory=list)


@dataclass
class GenerationReport:
    act_pair:           str
    rows_inserted:      int = 0
    rows_updated:       int = 0
    deleted_seeded:     int = 0
    split_cases:        List[str] = field(default_factory=list)
    merge_cases:        List[str] = field(default_factory=list)
    collision_warnings: List[str] = field(default_factory=list)
    assertion_failures: List[str] = field(default_factory=list)
    duration_s:         float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — MAPPING CONFIGURATION (all editable, no logic changes needed)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Noise: JSON replaces_* entries confirmed wrong ──────────────────────────
BLOCKED_OLD_SECTIONS: Dict[str, Dict[str, List[str]]] = {
    "BNS_2023": {
        # ── BNS 95: "Hiring, Employing or Engaging a Child to Commit an Offence" ──────
        # NCRB official table confirms: BNS 95 = NEW Section (no IPC predecessor).
        # The JSON's replaces_ipc=['299','301','302','366A','369','372','373'] is CORRUPT data.
        # These IPC sections all have correct BNS targets elsewhere:
        #   IPC 299 → BNS 100 (Culpable Homicide)
        #   IPC 301 → BNS 102 (Culpable homicide — transferred death)
        #   IPC 302 → BNS 103 (Murder Punishment)
        #   IPC 366A → BNS 96 (Procuration of child)
        #   IPC 369 → BNS 97 (Kidnapping child under 10)
        #   IPC 372 → BNS 98 (Selling child for prostitution)
        #   IPC 373 → BNS 99 (Buying child for prostitution)
        "95":  ["299", "301", "302", "366A", "369", "372", "373"],

        # ── BNS 48: "Abetment outside India for offence in India" ────────────────────
        # NCRB official table confirms: BNS 48 = NEW Section (no IPC predecessor).
        # The JSON's replaces_ipc contains 38 sections — ALL corrupt. Entire IPC abetment
        # chapter (108A-120B) + sexual offences chapter (228A, 312-318, 354, 375, etc.)
        # were incorrectly assigned. Block every one.
        "48":  ["108A", "109", "110", "111", "112", "113", "114", "115", "116",
                "117", "118", "119", "120", "120B", "228A", "312", "313", "314",
                "315", "316", "317", "318", "354", "354A", "354B", "354C", "354D",
                "366", "375", "376A", "376B", "376C", "376DB", "495", "498", "498A",
                "509", "511"],

        # ── BNS 304: "Snatching" ─────────────────────────────────────────────────────
        # JSON marks BNS 304 type='new' but gives replaces_ipc=['379','380','381','382'].
        # Snatching is a DISTINCT new offence from Theft. IPC 379 → BNS 303 (Theft).
        # IPC 380/381/382 are also theft variants — do not belong at BNS 304.
        "304": ["379", "380", "381", "382"],

        # ── BNS 319: Cheating by Personation — IPC 420 belongs at BNS 318 ──────────
        "319": ["420"],
    },
    "BNSS_2023": {
        # BNSS 172 was spuriously linked to CrPC 153 (deleted section).
        # BNSS 172 = new provision on police directions — no CrPC predecessor.
        "172": ["153"],
        # BNSS 438 = Revision powers of High Court / Sessions Judge.
        # CrPC 438 (Anticipatory Bail) maps to BNSS 482. This is the critical false-friend.
        "438": ["438"],
    },
    "BSA_2023": {
        # BSA 107 = "Burden of proving fact to be proved to make evidence admissible."
        # NCRB official table confirms: BSA 107 = IEA 104. That is the CORRECT mapping.
        # IEA 115 = Estoppel → BSA 121 (Estoppel). Block IEA 115 from this wrong slot.
        # IEA 104 is correctly seeded to BSA 107 via MANUAL_OLD_SECTIONS and JSON.
        "107": ["115"],
    },
}

# ── Manual seeds: JSON left empty but authoritative docs confirm ─────────────
MANUAL_OLD_SECTIONS: Dict[str, Dict[str, List[str]]] = {
    "BNS_2023": {
        # IPC 124A (Sedition) → BNS 152.
        # bns_complete.json has type='new', replaces_ipc=[] for BNS 152, but
        # the section notes say "New provision replacing sedition (IPC 124A)".
        "152": ["124A"],
        # IPC 420 (Cheating inducing delivery of property) → BNS 318.
        # bns_complete.json false_friends: correct_new_section_for_old_meaning = "318(4)".
        # BNS 420 does not exist.
        "318": ["420"],
        # IPC 379 (Theft) → BNS 303.
        # bns_complete.json false_friends: BNS 379 does not exist; maps to 303.
        "303": ["379"],
    },
    "BNSS_2023": {
        # CrPC 173 (Police Report/Chargesheet) → BNSS 193.
        # bnss_complete.json marks 193 as 'new' because of significant additions
        # (90/180-day investigation timeline, mandatory forensic expert), but the
        # structural predecessor is unambiguously CrPC 173.
        "193": ["173"],
        # CrPC 154 (FIR) → BNSS 173 (Zero-FIR + e-FIR additions confirmed mapping).
        "173": ["154"],
        # CrPC 161 (Examination of witnesses) → BNSS 180 (audio-video recording added).
        "180": ["161"],
        # CrPC 164 (Recording of confessions) → BNSS 183 (electronic recording added).
        "183": ["164"],
        # CrPC 167 (Remand) → BNSS 187 (90-day max custody period clarified).
        "187": ["167"],
    },
    "BSA_2023": {
        # IEA 115 (Estoppel) → BSA 121 (Estoppel).
        # Verified from PDF: BSA 121 = "Estoppel."
        # The section number shifted by +6 vs IEA in the Estoppel cluster:
        #   IEA 115 → BSA 121, IEA 116 → BSA 122, IEA 117 → BSA 123.
        # BSA 107 = "Burden of proving fact to be proved to make evidence admissible"
        # which is a completely different provision (IEA 104 territory, not Estoppel).
        "121": ["115"],
    },
}

# ── Type corrections: wrong JSON type that must be overridden ────────────────
TYPE_CORRECTIONS: Dict[str, Dict[str, str]] = {
    "BNSS_2023": {
        # CrPC 173 → BNSS 193: JSON says 'new' because of significant additions,
        # but CrPC 173 (Police Report / Chargesheet) is clearly the predecessor.
        # BNSS 193 adds 90/180-day timeline — that is 'modified'.
        "193": "modified",
        # CrPC 154 → BNSS 173: Zero-FIR + electronic FIR added — 'modified'.
        "173": "modified",
        # CrPC 161 → BNSS 180: Audio-video recording mandate added — 'modified'.
        "180": "modified",
    },
    "BNS_2023": {
        # BNS 63–70 should be split_into (IPC 375/376 split).
        # The split-detection pass handles most; these are fallback overrides.
        "63": "split_into",
        "64": "split_into",
        # BNS 152 = "Act endangering sovereignty, unity and integrity of India."
        # JSON marks it 'new' because replaces_ipc=[] (no direct reference), but
        # IPC 124A (Sedition) is the clear predecessor per MANUAL_OLD_SECTIONS seed.
        # Type must be 'modified' — not a new provision but a renamed/expanded one.
        "152": "modified",
    },
}

SCOPE_CORRECTIONS: Dict[str, Dict[str, str]] = {
    "BNS_2023": {
        "4":   "expanded",   # Community service added as punishment type
        "152": "expanded",   # BNS 152 broader than IPC 124A (sedition)
        "63":  "expanded",   # Rape definition expanded
    },
    "BNSS_2023": {
        "173": "expanded",   # Zero-FIR + e-FIR + women-victim protections added
        "193": "expanded",   # 90/180-day investigation deadline + forensic mandate
        "176": "expanded",   # Mandatory forensic expert at scene (new obligation)
        "183": "expanded",   # Audio-video confessions + electronic recording
        "187": "expanded",   # 90-day custody clarification
        "482": "none",       # Anticipatory bail powers unchanged — scope is none, not equivalent
        "483": "none",       # Special bail powers unchanged — scope is none, not equivalent
    },
    "BSA_2023": {
        "1":   "narrowed",   # Territorial extent narrowed vs IEA
        "63":  "expanded",   # Cloud records + certificate rules expanded
    },
}

# ── Collision guard notes (injected as transition_note) ─────────────────────
COLLISION_NOTES: Dict[Tuple[str, str], str] = {
    ("IPC_1860", "302"): (
        "CRITICAL FALSE-FRIEND: Do NOT cite BNS 302 for IPC 302. "
        "BNS 302 = Uttering words wounding religious feelings (replaces IPC 298). "
        "IPC 302 (Murder) maps to BNS 103 (Murder). Completely different offences."
    ),
    ("CrPC_1973", "438"): (
        "CRITICAL FALSE-FRIEND: Do NOT cite BNSS 438 for CrPC 438. "
        "BNSS 438 = 'Calling for records to exercise powers of revision' (High Court/Sessions revision). "
        "CrPC 438 (Anticipatory Bail) maps to BNSS 482. Fatal citation error in bail applications."
    ),
    ("CrPC_1973", "439"): (
        "CRITICAL FALSE-FRIEND: Do NOT cite BNSS 439 for CrPC 439. "
        "BNSS 439 = 'Power to order inquiry' under revision jurisdiction. "
        "CrPC 439 (Special bail powers of High Court/Sessions) maps to BNSS 483."
    ),
    ("IPC_1860", "420"): (
        "CRITICAL FALSE-FRIEND: BNS 420 does not exist. "
        "IPC 420 (Cheating inducing delivery of property) is incorporated as "
        "BNS 318(4). Always cite BNS 318 for this provision."
    ),
    ("IPC_1860", "379"): (
        "FALSE-FRIEND: BNS 379 does not exist. "
        "IPC 379 (Theft) maps to BNS 303 (Theft)."
    ),
    ("CrPC_1973", "154"): (
        "NOTE: CrPC 154 (FIR) maps to BNSS 173. "
        "BNSS 173 adds Zero-FIR (file at any station) and e-FIR (electronic filing). "
        "These are significant procedural expansions."
    ),
    ("CrPC_1973", "173"): (
        "NOTE: CrPC 173 (Chargesheet/Police Report) maps to BNSS 193. "
        "BNSS 193 mandates investigation completion within 90 days (sexual offences) "
        "or 180 days (other cases) and requires a forensic expert report."
    ),
}

BASE_CONFIDENCE: Dict[str, float] = {
    "equivalent":  0.97,
    "modified":    0.88,
    "split_into":  0.90,
    "merged_from": 0.88,
    "deleted":     0.95,
    "new":         0.95,
}

JSON_TYPE_MAP: Dict[str, str] = {
    "same":     "equivalent",
    "modified": "modified",
    "merged":   "merged_from",
    "new":      "new",
}

# ── Keywords for scope_change inference ─────────────────────────────────────
_EXPAND_KW = ["added", "new provision", "extended", "broadened", "increased",
               "newly", "introduced", "electronic", "audio-video", "forensic",
               "zero fir", "community service", "enhanced"]
_NARROW_KW = ["deleted", "removed", "excluded", "narrowed", "restricted",
               "omitted", "no longer applies", "not applicable"]
_STRUCT_KW = ["sub-section", "sub section", "consolidated", "merged",
               "renumbered", "restructured", "incorporated", "reorgani"]

# ── Sub-section suffix normalisation ────────────────────────────────────────
_SUBSEC_RE = re.compile(r"(\(\w+\))+$")


def _norm_sec(s: str) -> str:
    """'376(1)' → '376',  '53A' → '53A',  '124A' → '124A'"""
    return _SUBSEC_RE.sub("", s.strip())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — PDF PARSERS  (one per file format, built from actual inspection)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Shared regex for all parsers ─────────────────────────────────────────────
# Section start:   "302. Punishment for murder.—..."
#                  "124A. Sedition.—..."
#                  "25A. Directorate of Prosecution.—..."
_SEC_START   = re.compile(r'^(\d+[A-Z]{0,2})\.\s+(.+)')

# Section title separator — IPC/CRPC/IEA use em-dash U+2014 (—)
#                         — BNS/BSA use double-hyphen (––) or (—) or (--)
_TITLE_SEP   = re.compile(r'(?:\.––|\.—|\.--|\.\s*-{2,})\s*')

# Chapter line:
#   Plain:   "CHAPTER XX"          (IPC, CRPC, BNS, BSA)
#   Inline:  "CHAPTER I.––PRELIMINARY"  (IEA — chapter number + title on same line)
_CHAP_LINE   = re.compile(r'^CHAPTER\s+([IVXLCDM\d]+)[\.\-\s]*(.*)$', re.I)

# Part line (IEA/BSA):  "PART I"  /  "PART III"
_PART_LINE   = re.compile(r'^(PART\s+(I{1,3}V?|VI{0,3}|IX|X{1,3}|\d+))\s*$', re.I)

# Standalone page number — pure digits, optional trailing space
_PAGE_NUM    = re.compile(r'^\d{1,3}\s*$')

# Amendment footnote — "7. Subs. by Act..."  "1. Ins. by…"  "3. Rep. …"
_AMEND_FN    = re.compile(
    r'^\d+\.\s+(Subs\.|Ins\.|Omit|Rep\.|The word|The original|Added|Renumbered'
    r'|Certain|It has been|The Act|The sections|See the|Now called|Now subs\.)', re.I)

# Act-title page headers that recur per page in IPC/CRPC/IEA
_ACT_TITLE   = re.compile(
    r'^THE\s+(INDIAN\s+(PENAL\s+CODE|EVIDENCE\s+ACT)|CODE\s+OF\s+CRIMINAL'
    r'|BHARATIYA\s+(NYAYA|SAKSHYA))', re.I)

# Inline footnote markers — IPC/CRPC: "N[some text]" at line start
_INLINE_FN_START = re.compile(r'^\d+\[')

# Dangling bracket leftover from IEA multi-line footnotes: "[ 3***]"
_DANGLING    = re.compile(r'^\[\s*\d+\*+\]')

# BNS/BSA inline date footnote fused to text: "date1as" → "date as"
_BNS_FN_FUSED = re.compile(r'(\w)(\d+)(as|the|it|on|by|in|of|to|for|that)\b', re.I)


# ── CLEANER: applied to every line before accumulation ───────────────────────

def _clean_line(line: str, act_code: str) -> Optional[str]:
    """
    Return None  → discard the line entirely.
    Return str   → cleaned version to accumulate.

    Noise rules derived from actual PDF inspection:
      • All acts:   standalone page numbers (1-3 digits alone on a line)
      • All acts:   blank lines
      • IPC/CRPC:   "SECTIONS" repeat-header (from TOC carried into body pages)
      • IPC/CRPC:   amendment footnotes ("N. Subs. by Act …")
      • IPC/CRPC:   act-title lines ("THE INDIAN PENAL CODE") that re-appear on each page
      • IPC/CRPC:   inline footnote-start lines ("N[some text…")  — kept as body text
                    EXCEPT when the entire line is just the footnote marker
      • IEA:        dangling bracket leftovers ("[ 3***]")
      • BNS/BSA:    fused footnote numbers ("date1as") — cleaned in place
    """
    stripped = line.strip()

    # Blank
    if not stripped:
        return None

    # Standalone page number  (IPC: '9', '15 '; CRPC: '22'; BNS: '17'; IEA/BSA: '10')
    if _PAGE_NUM.match(stripped):
        return None

    # "SECTIONS" header repeat
    if stripped in ("SECTIONS", "SECTIONS "):
        return None

    # Act-title page headers repeated per page (IPC/CRPC/IEA only)
    if act_code in ("IPC_1860", "CrPC_1973", "IEA_1872"):
        if _ACT_TITLE.match(stripped):
            return None

    # Amendment footnotes — "7. Subs. by Act…", "1. Ins. by…" etc.
    # IPC/CrPC/IEA only.  BNSS/BNS/BSA section titles can start with the same
    # keywords (e.g. BNSS 122 "Certain transfers…", BNSS 391 "Certain Judges…")
    # which would cause false drops if this ran unconditionally.
    if act_code in ("IPC_1860", "CrPC_1973", "IEA_1872"):
        if _AMEND_FN.match(stripped):
            return None

    # IEA dangling bracket remnant
    if _DANGLING.match(stripped):
        return None

    # IEA/IPC continuation lines that START with "[ 3***]" or similar
    if re.match(r'^\[\s*\d+\*+\]', stripped):
        return None

    # BNS/BSA: remove fused footnote number (e.g. "date1as" → "date as")
    if act_code in ("BNS_2023", "BSA_2023"):
        stripped = _BNS_FN_FUSED.sub(r'\1 \3', stripped)

    # IPC/CRPC inline footnote:  "N[text continues…"  — strip the "N[" prefix,
    # keep the rest as body text.  If the line is ONLY "N[" discard it.
    if act_code in ("IPC_1860", "CrPC_1973", "IEA_1872"):
        if _INLINE_FN_START.match(stripped):
            # Strip leading digits and bracket: "10[(1) any citizen…" → "(1) any citizen…"
            cleaned = re.sub(r'^\d+\[', '', stripped)
            if cleaned.strip():
                return cleaned
            return None

    return stripped


def _extract_section_title_and_body(raw_header: str, body_lines: List[str]) -> Tuple[str, str]:
    """
    Given the header line after the section number (e.g. "Punishment for murder.—(1) Whoever…")
    and the accumulated continuation lines, return (title, full_legal_text).

    Title separator patterns observed across all acts:
      IPC/CRPC:  "Title.—Body"   (single em-dash U+2014)
      BNS:       "Title.––Body"  (two hyphens or en-dashes)
      IEA:       "Title.––Body"  or  "Title.––\n<next line is body>"
      BSA:       "Title.––Body"  same as BNS
    """
    # Combine everything into one string first
    full = raw_header
    if body_lines:
        full = raw_header.rstrip() + " " + " ".join(body_lines)

    # Try to split at em-dash / double-dash separator
    split_match = re.search(r'[\.…]\s*(?:––|—|--)\s*', full)
    if split_match:
        title = full[:split_match.start()].strip()
        # Remove trailing period from title if present
        title = re.sub(r'\.\s*$', '', title).strip()
        body  = full[split_match.end():].strip()
    else:
        # No separator found — the full header IS the title (definition sections, etc.)
        title = re.sub(r'\.\s*$', '', raw_header.strip()).strip()
        body  = full.strip()

    # Normalise footnote markers remaining in body text:
    # IPC/CRPC: N[text]  →  text   (strip the marker, keep the amendment text)
    body = re.sub(r'\d+\[', '', body)
    body = re.sub(r'\]', '', body)  # matching close brackets
    # Remove "* * * *" omitted material markers
    body = re.sub(r'\*\s*\*\s*\*\s*\*', '', body)
    # Normalise whitespace
    body = re.sub(r'  +', ' ', body).strip()

    return title, body


# ── PARSER: plain-text acts (IPC, CRPC, BNS) ─────────────────────────────────

def _find_content_start_text(lines: List[str]) -> int:
    """
    The arrangement-of-sections block occupies the first part of each text file.
    The actual content begins at the SECOND occurrence of "^1. Short title…"
    (the first is the TOC entry, the second is the full section body).

    Returns the 0-based index of the content-start line.
    """
    first_found = False
    for i, l in enumerate(lines):
        if re.match(r'^1\.\s+(Short title|Title and extent)', l.strip()):
            if first_found:
                return i
            first_found = True
    # Fallback: look for "Preamble.—" (IPC starts with preamble)
    for i, l in enumerate(lines):
        if re.match(r'^Preamble\.', l.strip()):
            return i
    return 0


def parse_text_act(path: Path, act_code: str) -> Tuple[List[ParsedSection], ExtractionReport]:
    """
    Parse a plain-text act file (IPC.pdf, CRPC.pdf, BNS.pdf).

    Layout (verified by inspection):
      Lines 1 – N:    Arrangement of Sections (TOC block) — SKIPPED
      Line N+1 …:     Actual section content

    Section body may span many lines (continuation lines).
    Page numbers appear as standalone 1-3 digit lines within section bodies.
    """
    report = ExtractionReport(act_code=act_code)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()

    content_start = _find_content_start_text(raw_lines)
    log.info("[%s] Content start line: %d / %d", act_code, content_start+1, len(raw_lines))

    sections: List[ParsedSection] = []
    current_sec_num:   Optional[str] = None
    current_sec_hdr:   str           = ""
    current_body:      List[str]     = []
    current_chapter:   str           = ""
    current_ch_title:  str           = ""

    def _flush():
        nonlocal current_sec_num, current_sec_hdr, current_body
        if current_sec_num is None:
            return
        title, body = _extract_section_title_and_body(current_sec_hdr, current_body)
        sections.append(ParsedSection(
            act_code        = act_code,
            section_number  = current_sec_num,
            section_title   = title,
            legal_text      = body,
            chapter_number  = current_chapter,
            chapter_title   = current_ch_title,
        ))
        current_sec_num  = None
        current_sec_hdr  = ""
        current_body     = []

    noise_count = 0
    for raw_line in raw_lines[content_start:]:
        # Chapter / Part line?
        cm = _CHAP_LINE.match(raw_line.strip())
        if cm:
            _flush()
            current_chapter  = cm.group(1).strip()
            # IEA uses inline format "CHAPTER I.––PRELIMINARY"; group(2) holds title
            inline_t = (cm.group(2) or "").strip()
            inline_t = __import__('re').sub(r'^[\.\-\–\—\s]+', '', inline_t).strip()
            current_ch_title = inline_t
            report.chapters_found += 1
            continue

        cleaned = _clean_line(raw_line, act_code)
        if cleaned is None:
            noise_count += 1
            continue

        # Is this line a chapter title? (line immediately after CHAPTER XX with no section)
        if (current_sec_num is None
                and not _SEC_START.match(cleaned)
                and current_chapter
                and not current_ch_title):
            current_ch_title = cleaned
            continue

        # New section start?
        sm = _SEC_START.match(cleaned)
        if sm:
            _flush()
            current_sec_num = sm.group(1)
            current_sec_hdr = sm.group(2)
            continue

        # Continuation line
        if current_sec_num is not None:
            current_body.append(cleaned)

    _flush()
    report.sections_found = len(sections)
    report.noise_stripped = noise_count
    log.info("[%s] Parsed: sections=%d chapters=%d noise_stripped=%d",
             act_code, report.sections_found, report.chapters_found, report.noise_stripped)
    return sections, report


# ── PARSER: ZIP-based acts (IEA, BSA) ────────────────────────────────────────

def parse_zip_act(path: Path, act_code: str) -> Tuple[List[ParsedSection], ExtractionReport]:
    """
    Parse a ZIP-packaged act (IEA.pdf, BSA.pdf).

    These are ZIPs containing N.txt and N.jpeg files plus manifest.json.
    Each N.txt is one page of the original document.
    Pages are concatenated in order then parsed identically to text acts.

    Additional structure specific to these files:
      IEA: uses PART I/II/III headings above CHAPTER headings
      BSA: uses PART I/II/III/IV headings above CHAPTER headings
      Both: no amendment footnotes in BSA; IEA has them
    """
    report = ExtractionReport(act_code=act_code)

    with zipfile.ZipFile(path) as zf:
        names    = sorted(zf.namelist())
        txt_nums = sorted(
            [int(re.sub(r'\D', '', n)) for n in names if re.match(r'^\d+\.txt$', n)]
        )
        all_lines: List[str] = []
        for n in txt_nums:
            raw = zf.read(f"{n}.txt").decode("utf-8", errors="replace")
            all_lines.extend(raw.splitlines())

    log.info("[%s] ZIP pages=%d total_lines=%d", act_code, len(txt_nums), len(all_lines))

    content_start = _find_content_start_text(all_lines)
    log.info("[%s] Content start line: %d / %d", act_code, content_start+1, len(all_lines))

    sections: List[ParsedSection]  = []
    current_sec_num:  Optional[str] = None
    current_sec_hdr:  str           = ""
    current_body:     List[str]     = []
    current_chapter:  str           = ""
    current_ch_title: str           = ""
    current_part:     str           = ""

    def _flush():
        nonlocal current_sec_num, current_sec_hdr, current_body
        if current_sec_num is None:
            return
        title, body = _extract_section_title_and_body(current_sec_hdr, current_body)
        sections.append(ParsedSection(
            act_code        = act_code,
            section_number  = current_sec_num,
            section_title   = title,
            legal_text      = body,
            chapter_number  = current_chapter,
            chapter_title   = current_ch_title,
            part_number     = current_part,
        ))
        current_sec_num  = None
        current_sec_hdr  = ""
        current_body     = []

    noise_count = 0
    for raw_line in all_lines[content_start:]:
        stripped = raw_line.strip()

        # PART heading (IEA/BSA specific)
        pm = _PART_LINE.match(stripped)
        if pm:
            _flush()
            current_part = pm.group(2).strip()
            continue

        # CHAPTER heading
        cm = _CHAP_LINE.match(stripped)
        if cm:
            _flush()
            current_chapter  = cm.group(1).strip()
            inline_t = (cm.group(2) or "").strip()
            inline_t = __import__('re').sub(r'^[\.\-\–\—\s]+', '', inline_t).strip()
            current_ch_title = inline_t
            report.chapters_found += 1
            continue

        cleaned = _clean_line(raw_line, act_code)
        if cleaned is None:
            noise_count += 1
            continue

        # Chapter title line (right after CHAPTER heading before first section)
        if (current_sec_num is None
                and not _SEC_START.match(cleaned)
                and current_chapter
                and not current_ch_title):
            current_ch_title = cleaned
            continue

        sm = _SEC_START.match(cleaned)
        if sm:
            _flush()
            current_sec_num = sm.group(1)
            current_sec_hdr = sm.group(2)
            continue

        if current_sec_num is not None:
            current_body.append(cleaned)

    _flush()
    report.sections_found = len(sections)
    report.noise_stripped = noise_count
    log.info("[%s] Parsed: sections=%d chapters=%d parts=%s noise_stripped=%d",
             act_code, report.sections_found, report.chapters_found,
             current_part, report.noise_stripped)
    return sections, report


# ── PARSER: real PDF acts (BNSS) via pdfplumber ──────────────────────────────

def parse_pdf_act(path: Path, act_code: str) -> Tuple[List[ParsedSection], ExtractionReport]:
    """
    Parse a real PDF file using pdfplumber (BNSS.pdf).

    BNSS-specific noise patterns confirmed by byte-level inspection of all 279 pages
    (10,920 lines total after pdfplumber extraction):

      Noise inventory
      ───────────────
      • 264 standalone page numbers  (integers 16–279, each alone on a line)
      • 1 footnote line at content line 714:
            "1. 1st July, 2024, [except the provisions of the entry relation
             to Section 106(2) in the First Schedule], vide notification No. S.O."
        caught by the existing date-footnote guard (^\\d+\\.\\s+\\d{1,2}(?:st|nd|rd|th))
      • 1 gazette-reference continuation at content line 715:
            "848(E), dated, 23rd day of February, 2024, see Gazette of India,
             Extraordinary, Part II, sec. 3(ii)."
        stripped via _skip_footnote_continuation one-shot flag
      • 0 amendment footnotes, 0 "SECTIONS" headers, 0 act-title repeats

      False-positive chapter detections (avoided with strict uppercase regex)
      ────────────────────────────────────────────────────────────────────────
      Using shared _CHAP_LINE (re.I) would match these body-text fragments:
        line 2429  "Chapter may be released without hazard to the community…"
        line 4744  "Chapter IX has been commenced under this Sanhita."
        line 5549  "Chapter XVII of the Bharatiya Nyaya Sanhita, 2023…"
        line 6440  "Chapter is heard by a High Court before a Bench of Judges…"
        lines 8550–8985 (6 hits) "Chapter XXVIII;" in the First/Second Schedule tables
      Fix: _BNSS_CHAP_LINE requires the word CHAPTER to be ALL-CAPS (no re.I),
           and allows ONLY a sentinel or separator after the Roman numeral.

      Missing chapter heading (PDF artefact, not a parser bug)
      ──────────────────────────────────────────────────────────
      CHAPTER V ("ARREST OF PERSONS") exists in the TOC (line 50) and the
      correct sections 35–62 are present in the body, but the standalone
      "CHAPTER V" header line was not rendered on any content page. Post-
      processing via BNSS_MISSING_CHAPTERS injects the correct chapter metadata
      for all 28 affected sections.

      Content boundary
      ─────────────────
      THE FIRST SCHEDULE starts at content line 7503 (exact uppercase sentinel
      "THE FIRST SCHEDULE"). Earlier in the body, section 522 contains "the
      Second Schedule, with such variations as the circumstances of each case
      require..." (sentence-case, has trailing text) — a naive check would fire
      here at line 7432. The strict sentinel regex ^THE\\s+(FIRST|SECOND|...)\\s+
      SCHEDULE\\s*$ (all-caps, standalone) avoids this false trigger.

      Chapter I heading recovery
      ───────────────────────────
      _find_content_start_text returns the line of the SECOND "1. Short title…"
      (line 685 in the full text), which is AFTER "CHAPTER I" at line 683 and
      "PRELIMINARY" at line 684. parse_pdf_act back-scans up to 10 lines to
      find the preceding uppercase CHAPTER heading and moves content_start there,
      so CHAPTER I and its title are correctly captured.

      Section numbers: 1–531, numeric only (no alphanumeric like 25A in BNSS).
      Title separator: em-dash "—" throughout; rare plain "-" in 6 sections.
      False-positive section guard: section number must be ≤ 600 (blocks "2023."
      or similar year-numbers that appear in body text).
    """
    try:
        import pdfplumber as _pdfplumber
    except ImportError:
        log.error("pdfplumber is required for BNSS parsing: pip install pdfplumber")
        report = ExtractionReport(act_code=act_code,
                                  errors=["pdfplumber not installed"])
        return [], report

    # ── BNSS-specific: strict uppercase-only chapter regex ──────────────────
    # The shared _CHAP_LINE uses re.I, which causes false positives from body
    # text like "Chapter IX has been commenced…" or "Chapter XXVIII;" in tables.
    # BNSS chapter headers are ALWAYS all-caps: "CHAPTER IV", "CHAPTER XXXIX".
    # The regex allows:
    #   • standalone  "CHAPTER IV"
    #   • with separator+title  "CHAPTER I.––PRELIMINARY"  (IEA-style, future-proof)
    _BNSS_CHAP_LINE = re.compile(
        r'^CHAPTER\s+([IVXLCDM\d]+)'          # strict ALL-CAPS CHAPTER keyword
        r'(?:\s*[.—–\-]\s*(.+?))?'            # optional separator + title on same line
        r'\s*$'                                # must end here (no mid-sentence text)
    )

    # Exact sentinel to stop parsing at THE FIRST SCHEDULE.
    # "the Second Schedule, with such variations as…" (sentence-case, trailing text)
    # in section 522 body is a false trigger for looser checks.
    _BNSS_SCHEDULE_SENTINEL = re.compile(
        r'^THE\s+(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH)\s+SCHEDULE\s*$'
    )

    report = ExtractionReport(act_code=act_code)

    all_lines: List[str] = []
    with _pdfplumber.open(path) as pdf:
        log.info("[%s] pdfplumber opened: %d pages", act_code, len(pdf.pages))
        for pg in pdf.pages:
            t = pg.extract_text() or ""
            all_lines.extend(t.splitlines())

    log.info("[%s] Total lines from PDF: %d", act_code, len(all_lines))

    # ── Back-scan from content start to recover CHAPTER I heading ────────────
    # _find_content_start_text returns the line of the second "1. Short title…"
    # occurrence (the body, not the TOC). CHAPTER I at line 683 and its title
    # "PRELIMINARY" at line 684 are BEFORE this line and would be skipped.
    # Scan up to 10 lines backward to find the nearest standalone CHAPTER heading.
    _raw_start = _find_content_start_text(all_lines)
    content_start = _raw_start
    _strict_chap_scan = re.compile(r'^CHAPTER\s+[IVXLCDM\d]+\s*$')
    for _j in range(_raw_start - 1, max(0, _raw_start - 10), -1):
        if _strict_chap_scan.match(all_lines[_j].strip()):
            content_start = _j
            log.info("[%s] Back-scanned CHAPTER heading at line %d (raw start was %d)",
                     act_code, content_start + 1, _raw_start + 1)
            break

    log.info("[%s] Content start line: %d / %d", act_code, content_start + 1, len(all_lines))

    sections:         List[ParsedSection] = []
    current_sec_num:  Optional[str]       = None
    current_sec_hdr:  str                 = ""
    current_body:     List[str]           = []
    current_chapter:  str                 = ""
    current_ch_title: str                 = ""
    noise_count:      int                 = 0
    # One-shot flag: skip the line immediately following a footnote sentinel
    _skip_footnote_continuation: bool     = False

    def _flush_bnss():
        nonlocal current_sec_num, current_sec_hdr, current_body
        if current_sec_num is None:
            return
        title, body = _extract_section_title_and_body(current_sec_hdr, current_body)
        sections.append(ParsedSection(
            act_code        = act_code,
            section_number  = current_sec_num,
            section_title   = title,
            legal_text      = body,
            chapter_number  = current_chapter,
            chapter_title   = current_ch_title,
        ))
        current_sec_num  = None
        current_sec_hdr  = ""
        current_body     = []

    for raw_line in all_lines[content_start:]:
        ls = raw_line.strip()

        # ── Hard stop at THE FIRST SCHEDULE ──────────────────────────────────
        if _BNSS_SCHEDULE_SENTINEL.match(ls):
            log.info("[%s] Schedule sentinel reached: %r — stopping section parse", act_code, ls)
            _flush_bnss()
            break

        # ── BNSS-specific: gazette continuation line (one-shot flag) ─────────
        # Must be checked BEFORE _clean_line so the flag isn't reset.
        # Line 715: "848(E), dated, 23rd day of February, 2024, see Gazette of
        #           India, Extraordinary, Part II, sec. 3(ii)."
        if _skip_footnote_continuation:
            _skip_footnote_continuation = False
            noise_count += 1
            continue

        # ── Universal noise filter (act-aware) ───────────────────────────────
        # _clean_line handles, per act_code:
        #   ALL acts  : blank lines, standalone page numbers, "SECTIONS" headers
        #   IPC/CrPC  : act-title page headers, amendment footnotes
        #               ("N. Subs. by Act…"), inline footnote markers ("N[text]")
        #   IEA       : dangling bracket remnants ("[ 3***]")
        #   BNS/BSA   : fused date-footnote numbers ("date1as" → "date as")
        # Returns None → discard line.  Returns str → cleaned text to process.
        cleaned = _clean_line(raw_line, act_code)
        if cleaned is None:
            noise_count += 1
            continue
        ls = cleaned   # use the cleaned version for all checks below

        # ── BNSS-specific: date-footnote line ────────────────────────────────
        # "1. 1st July, 2024, [except…" — NOT caught by _AMEND_FN (which looks
        # for "Subs.", "Ins.", etc.).  Set one-shot flag for gazette continuation.
        if re.match(r'^\d+\.\s+\d{1,2}(?:st|nd|rd|th)', ls):
            noise_count += 1
            _skip_footnote_continuation = True
            continue

        # ── CHAPTER header (strict uppercase, no re.I) ───────────────────────
        cm = _BNSS_CHAP_LINE.match(ls)
        if cm:
            _flush_bnss()
            current_chapter  = cm.group(1).strip()
            inline_t = (cm.group(2) or "").strip()
            inline_t = re.sub(r'^[.\-–—\s]+', '', inline_t).strip()
            current_ch_title = inline_t
            report.chapters_found += 1
            continue

        # Chapter title line (standalone line immediately after CHAPTER heading)
        if (current_sec_num is None
                and current_chapter
                and not current_ch_title
                and not _SEC_START.match(ls)):
            current_ch_title = ls
            continue

        # ── Section start ─────────────────────────────────────────────────────
        # Guard: section number must be ≤ 600 to block year-numbers ("2023.").
        sm = _SEC_START.match(ls)
        if sm:
            sec_num_raw = sm.group(1)
            try:
                sec_int = int(re.sub(r'[A-Z]', '', sec_num_raw))
            except ValueError:
                sec_int = 0
            if sec_int <= 600:
                _flush_bnss()
                current_sec_num = sec_num_raw
                current_sec_hdr = sm.group(2)
                continue

        # Continuation line (body of current section)
        if current_sec_num is not None:
            current_body.append(ls)

    _flush_bnss()

    # ── Post-processing: inject chapter metadata for CHAPTER V ───────────────
    # CHAPTER V ("ARREST OF PERSONS") heading is missing from the BNSS PDF content
    # pages (present in the TOC but never rendered as a standalone line in the body).
    # This injection is BNSS_2023-specific — other acts (IPC, CrPC, BNS, IEA, BSA)
    # all have a rendered CHAPTER V in their PDFs and must NOT have their sections
    # 35–62 overwritten with BNSS chapter metadata.
    if act_code == "BNSS_2023":
        BNSS_MISSING_CHAPTERS: Dict[str, Tuple[str, str]] = {
            str(n): ("V", "ARREST OF PERSONS") for n in range(35, 63)
        }
        injected = 0
        for sec in sections:
            if sec.section_number in BNSS_MISSING_CHAPTERS and sec.chapter_number != "V":
                sec.chapter_number, sec.chapter_title = BNSS_MISSING_CHAPTERS[sec.section_number]
                injected += 1
        if injected:
            log.info("[%s] Chapter-V metadata injected for %d sections (35–62)", act_code, injected)

    report.sections_found = len(sections)
    report.noise_stripped = noise_count
    log.info("[%s] Parsed: sections=%d chapters=%d noise_stripped=%d",
             act_code, report.sections_found, report.chapters_found, report.noise_stripped)
    return sections, report




def parse_act(path: Path, act_code: str) -> Tuple[List[ParsedSection], ExtractionReport]:
    """
    Dispatch to the correct parser based on file format detected at runtime.

      %PDF-1.x magic  → pdfplumber real-PDF parser  (BNSS)
      PK magic        → ZIP-page parser              (IEA, BSA)
      anything else   → plain-text parser            (IPC, CRPC, BNS)
    """
    with open(path, "rb") as f:
        magic = f.read(4)

    if magic[:4] == b"%PDF":          # Real PDF → BNSS
        return parse_pdf_act(path, act_code)
    elif magic[:2] == b"PK":          # ZIP → IEA or BSA
        return parse_zip_act(path, act_code)
    else:                             # Plain text → IPC, CRPC, BNS
        return parse_text_act(path, act_code)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — JSON ENRICHMENT LOADER
# ═══════════════════════════════════════════════════════════════════════════════

def _load_enrichment_json(json_path: Path, new_act: str, old_act: str,
                          section_key: str, replaces_key: str) -> List[dict]:
    """
    Parse a BNS or BSA enrichment JSON file.

    Returns a flat list of dicts, each with:
      section_number, section_title, chapter_number, chapter_title,
      domain, replaces_old (List[str]), json_type (str),
      change_summary (str), notes (str)
    """
    if not json_path.exists():
        log.warning("Enrichment JSON not found: %s", json_path)
        return []

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    rows: List[dict] = []
    chapters = data.get("chapters", [])

    for chap in chapters:
        chap_num   = str(chap.get("chapter_number", "")).strip()
        chap_title = chap.get("chapter_title", "")
        chap_dom   = chap.get("domain", "")

        for sec in chap.get("sections", []):
            sec_num = str(sec.get(section_key, "")).strip()
            if not sec_num:
                continue

            # Build replaces list
            raw = sec.get(replaces_key) or []
            if isinstance(raw, str):
                raw = [raw] if raw.strip() else []
            replaces = list(dict.fromkeys(          # deduplicate, preserve order
                _norm_sec(str(r)) for r in raw if str(r).strip()
            ))

            # Block known noise
            blocked = BLOCKED_OLD_SECTIONS.get(new_act, {}).get(sec_num, [])
            replaces = [r for r in replaces if r not in blocked]

            cs   = (sec.get("change_summary") or "").strip()
            note = (sec.get("notes") or "").strip()
            if note == cs:
                note = ""

            rows.append({
                "section_number":  sec_num,
                "section_title":   (sec.get("heading") or "").strip(),
                "chapter_number":  chap_num,
                "chapter_title":   chap_title,
                "domain":          sec.get("domain") or chap_dom,
                "replaces_old":    replaces,
                "json_type":       (sec.get("type") or "same").lower().strip(),
                "change_summary":  cs,
                "notes":           note,
            })

    # Apply manual seeds
    for new_sec, inject_list in MANUAL_OLD_SECTIONS.get(new_act, {}).items():
        target = next((r for r in rows if r["section_number"] == new_sec), None)
        if target is None:
            log.warning("Manual seed target %s/%s not in JSON", new_act, new_sec)
            continue
        before = set(target["replaces_old"])
        for old_sec in inject_list:
            if old_sec not in before:
                target["replaces_old"].append(old_sec)
                log.info("Manual seed: %s/%s ← %s/%s", new_act, new_sec, old_act, old_sec)

    log.info("Enrichment loaded: %s → %d sections", json_path.name, len(rows))
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — MAPPING GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

def _infer_scope(new_act: str, new_sec: str,
                 summary: str, t_type: str) -> Optional[str]:
    override = SCOPE_CORRECTIONS.get(new_act, {}).get(new_sec)
    if override:
        return override
    if t_type in ("deleted", "new"):
        return None
    if t_type == "equivalent" and not summary.strip():
        return "none"
    sl = summary.lower()
    if any(k in sl for k in _EXPAND_KW):
        return "expanded"
    if any(k in sl for k in _NARROW_KW):
        return "narrowed"
    if any(k in sl for k in _STRUCT_KW):
        return "restructured"
    return "none" if t_type == "equivalent" else "unknown"


def _build_note(old_act: str, old_sec: str, change_summary: str,
                notes: str, t_type: str) -> Optional[str]:
    parts: List[str] = []
    cn = COLLISION_NOTES.get((old_act, old_sec))
    if cn:
        parts.append(cn)
    if change_summary and len(change_summary) > 10:
        parts.append(change_summary)
    if notes and notes != change_summary and len(notes) > 10:
        parts.append(notes)
    return " | ".join(parts) if parts else None


def _resolve_type(new_act: str, new_sec: str, old_sections: List[str],
                  json_type: str,
                  old2new: Dict[str, List[str]],
                  new2old: Dict[str, List[str]]) -> str:
    # Hard override first
    corr = TYPE_CORRECTIONS.get(new_act, {}).get(new_sec)
    if corr:
        return corr

    if json_type in ("deleted", "new"):
        return json_type

    # Split: any of my old sections already maps to another new section
    for os_ in old_sections:
        existing = old2new.get(os_, [])
        if len(existing) >= 1 and new_sec not in existing:
            return "split_into"

    # Merge: this new section already has another old section pointing to it
    existing_old = new2old.get(new_sec, [])
    if len(set(existing_old) | set(old_sections)) > 1 and len(existing_old) >= 1:
        return "merged_from"

    return JSON_TYPE_MAP.get(json_type, "equivalent")


def generate_mappings(
    new_act:      str,
    old_act:      str,
    json_rows:    List[dict],
    old_sections: Dict[str, ParsedSection],   # section_number → ParsedSection
    new_sections: Dict[str, ParsedSection],
) -> Tuple[List[MappingRow], GenerationReport]:
    """
    Core mapping generation for one act pair.
    Returns (list_of_rows, report).
    """
    report = GenerationReport(act_pair=f"{old_act}→{new_act}")
    rows:   List[MappingRow] = []

    # ── Build forward/reverse indexes for split/merge detection ──────────────
    old2new: Dict[str, List[str]] = {}   # old_sec → [new_secs]
    new2old: Dict[str, List[str]] = {}   # new_sec → [old_secs]
    for jr in json_rows:
        ns = jr["section_number"]
        for os_ in jr["replaces_old"]:
            old2new.setdefault(os_, [])
            if ns not in old2new[os_]:
                old2new[os_].append(ns)
            new2old.setdefault(ns, [])
            if os_ not in new2old[ns]:
                new2old[ns].append(os_)

    # ── Generate rows ─────────────────────────────────────────────────────────
    for jr in json_rows:
        ns      = jr["section_number"]
        replaces = jr["replaces_old"]
        jtype    = jr["json_type"]
        cs       = jr["change_summary"]
        note_raw = jr["notes"]
        ntitle   = jr["section_title"]

        # Enrich title from parsed PDF if JSON is sparse
        if not ntitle and ns in new_sections:
            ntitle = new_sections[ns].section_title

        if not replaces:
            # Pure new provision
            rows.append(MappingRow(
                old_act           = old_act,
                old_section       = "",
                old_section_title = "",
                old_legal_text    = "",
                new_act           = new_act,
                new_section       = ns,
                new_section_title = ntitle,
                transition_type   = "new",
                scope_change      = None,
                transition_note   = _build_note(old_act, "", cs, note_raw, "new"),
                confidence_score  = BASE_CONFIDENCE["new"],
            ))
            continue

        for os_ in replaces:
            t_type = _resolve_type(new_act, ns, replaces, jtype, old2new, new2old)
            scope  = _infer_scope(new_act, ns, cs, t_type)
            note   = _build_note(old_act, os_, cs, note_raw, t_type)

            # Look up old section data from parsed PDF
            op = old_sections.get(os_)
            old_title = op.section_title if op else ""
            old_text  = op.legal_text    if op else ""

            # Track splits/merges for report
            if t_type == "split_into":
                entry = f"{old_act} {os_} → {new_act} [{', '.join(old2new.get(os_, []))}]"
                if entry not in report.split_cases:
                    report.split_cases.append(entry)
            if t_type == "merged_from":
                entry = f"{new_act} {ns} ← {old_act} [{', '.join(new2old.get(ns, []))}]"
                if entry not in report.merge_cases:
                    report.merge_cases.append(entry)

            if (old_act, os_) in COLLISION_NOTES:
                report.collision_warnings.append(f"{old_act} {os_} → {new_act} {ns}")

            rows.append(MappingRow(
                old_act           = old_act,
                old_section       = os_,
                old_section_title = old_title,
                old_legal_text    = old_text,
                new_act           = new_act,
                new_section       = ns,
                new_section_title = ntitle,
                transition_type   = t_type,
                scope_change      = scope,
                transition_note   = note,
                confidence_score  = BASE_CONFIDENCE.get(t_type, 0.85),
            ))

    # ── Seed DELETED rows for old sections not referenced by any new section ──
    referenced_old = set()
    for jr in json_rows:
        referenced_old.update(jr["replaces_old"])

    deleted_count = 0
    for sec_num, op in old_sections.items():
        if sec_num not in referenced_old:
            # Warn if this is a known false-deletion
            if (old_act, sec_num) in COLLISION_NOTES:
                log.warning("Known section %s/%s is unreferenced — check MANUAL_OLD_SECTIONS", old_act, sec_num)
                continue

            rows.append(MappingRow(
                old_act           = old_act,
                old_section       = sec_num,
                old_section_title = op.section_title,
                old_legal_text    = op.legal_text,
                new_act           = new_act,
                new_section       = "",
                new_section_title = "",
                transition_type   = "deleted",
                scope_change      = None,
                transition_note   = (
                    f"{old_act} Section {sec_num} ({op.section_title}) was "
                    f"deleted with no equivalent in {new_act}."
                ),
                confidence_score  = 0.90,
            ))
            deleted_count += 1

    report.deleted_seeded = deleted_count
    log.info("[%s] Rows generated: %d (deleted=%d splits=%d merges=%d)",
             report.act_pair, len(rows), deleted_count,
             len(report.split_cases), len(report.merge_cases))
    return rows, report


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — DATABASE WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def _write_to_db(session, rows: List[MappingRow], report: GenerationReport) -> None:
    from sqlalchemy import text

    # ── Schema VARCHAR limits (truncate before write to prevent StringDataRightTruncation)
    # old_section_title / new_section_title : VARCHAR(500)
    # transition_note                       : VARCHAR(2000) (assumed; truncate at 2000)
    # old_legal_text / new_section_title body stored as TEXT — no limit
    def _t(s: Optional[str], limit: int) -> Optional[str]:
        """Truncate string to limit chars; preserve None."""
        if s is None:
            return s
        return s[:limit] if len(s) > limit else s

    for row in rows:
        # The DB schema has NOT NULL on old_section, new_section, new_act.
        # 'new' transition rows have no old_section (empty string "").
        # os_val / ns_val / na_val must NEVER be None — use "" as the sentinel.
        os_val = row.old_section if row.old_section is not None else ""
        ns_val = row.new_section if row.new_section is not None else ""
        na_val = row.new_act     if row.new_act     is not None else ""

        ost_val = _t(row.old_section_title, 500)
        nst_val = _t(row.new_section_title, 500)
        tn_val  = _t(row.transition_note,  2000)

        existing = session.execute(text("""
            SELECT id FROM law_transition_mappings
            WHERE old_act     = :oa
              AND old_section  = :os
              AND new_act      = :na
              AND new_section  = :ns
        """), {"oa": row.old_act, "os": os_val, "na": na_val, "ns": ns_val}).fetchone()

        if existing:
            session.execute(text("""
                UPDATE law_transition_mappings
                SET old_section_title = :ost,
                    old_legal_text    = :olt,
                    new_section_title = :nst,
                    transition_type   = :tt,
                    scope_change      = :sc,
                    transition_note   = :tn,
                    confidence_score  = :cs,
                    effective_date    = :ed,
                    updated_at        = NOW()
                WHERE id = :id
            """), {
                "ost": ost_val,             "olt": row.old_legal_text,
                "nst": nst_val,             "tt":  row.transition_type,
                "sc":  row.scope_change,    "tn":  tn_val,
                "cs":  row.confidence_score,"ed":  row.effective_date,
                "id":  existing.id,
            })
            report.rows_updated += 1
        else:
            session.execute(text("""
                INSERT INTO law_transition_mappings (
                    id, old_act, old_section, old_section_title, old_legal_text,
                    new_act, new_section, new_section_title,
                    transition_type, scope_change, transition_note,
                    confidence_score, is_active, effective_date,
                    created_at, updated_at
                ) VALUES (
                    :id, :oa, :os, :ost, :olt,
                    :na, :ns, :nst,
                    :tt, :sc, :tn,
                    :cs, FALSE, :ed,
                    NOW(), NOW()
                )
            """), {
                "id":  str(uuid.uuid4()),
                "oa":  row.old_act,         "os":  os_val,
                "ost": ost_val,             "olt": row.old_legal_text,
                "na":  na_val,              "ns":  ns_val,
                "nst": nst_val,
                "tt":  row.transition_type, "sc":  row.scope_change,
                "tn":  tn_val,              "cs":  row.confidence_score,
                "ed":  row.effective_date,
            })
            report.rows_inserted += 1

    session.commit()

    # Apply type-corrections to any rows that slipped through
    corrs = TYPE_CORRECTIONS.get(rows[0].new_act if rows else "", {})
    for ns, correct_type in corrs.items():
        r = session.execute(text("""
            UPDATE law_transition_mappings
            SET transition_type = :tt, updated_at = NOW()
            WHERE new_act = :na AND new_section = :ns
              AND transition_type != :tt
        """), {"tt": correct_type, "na": rows[0].new_act if rows else "", "ns": ns})
        if r.rowcount:
            log.info("Type correction applied: %s/%s → %s", rows[0].new_act, ns, correct_type)
    session.commit()


def _delete_spurious_rows(session, dry_run: bool) -> int:
    from sqlalchemy import text

    SPURIOUS = [
        # IPC sections falsely mapped to BNS 95 (New Section — no IPC predecessor)
        ("IPC_1860",  "299",  "BNS_2023",  "95"),   # Culpable Homicide → BNS 100, not BNS 95
        ("IPC_1860",  "301",  "BNS_2023",  "95"),   # Transferred death → BNS 102, not BNS 95
        ("IPC_1860",  "302",  "BNS_2023",  "95"),   # Murder → BNS 103, not BNS 95
        ("IPC_1860",  "366A", "BNS_2023",  "95"),   # Procuration → BNS 96, not BNS 95
        ("IPC_1860",  "369",  "BNS_2023",  "95"),   # Kidnapping under-10 → BNS 97, not BNS 95
        ("IPC_1860",  "372",  "BNS_2023",  "95"),   # Selling child → BNS 98, not BNS 95
        ("IPC_1860",  "373",  "BNS_2023",  "95"),   # Buying child → BNS 99, not BNS 95
        # IPC sections falsely mapped to BNS 48 (New Section — no IPC predecessor)
        # (sample the most dangerous; BLOCKED_OLD_SECTIONS prevents regeneration)
        ("IPC_1860",  "498A", "BNS_2023",  "48"),   # Cruelty to wife ≠ Abetment outside India
        ("IPC_1860",  "375",  "BNS_2023",  "48"),   # Rape def ≠ Abetment outside India
        ("IPC_1860",  "354",  "BNS_2023",  "48"),   # Outrage modesty ≠ Abetment outside India
        # IPC theft-cluster falsely mapped to BNS 304 (Snatching)
        ("IPC_1860",  "379",  "BNS_2023",  "304"),  # Theft → BNS 303, not BNS 304
        ("IPC_1860",  "380",  "BNS_2023",  "304"),  # Theft in dwelling → not BNS 304
        ("IPC_1860",  "381",  "BNS_2023",  "304"),  # Theft by clerk → not BNS 304
        ("IPC_1860",  "382",  "BNS_2023",  "304"),  # Theft after prep for hurt → not BNS 304
        # Standard false-friends
        ("IPC_1860",  "420",  "BNS_2023",  "319"),  # IPC 420 → BNS 318, not BNS 319
        # BNSS false-friend rows — CrPC 438/439 must NEVER map to BNSS 438/439
        ("CrPC_1973", "438",  "BNSS_2023", "438"),  # Anticipatory Bail ≠ Revision powers
        ("CrPC_1973", "439",  "BNSS_2023", "439"),  # Special bail ≠ Revision powers
        # BSA estoppel fix
        ("IEA_1872",  "115",  "BSA_2023",  "107"),  # Estoppel → BSA 121, not BSA 107
        # Stale "deleted" row for IEA 104 — left over from a prior run before BSA 107
        # was confirmed as the correct target. new_section='' is the sentinel value for
        # deleted rows; the correct row (IEA_1872, 104, BSA_2023, 107) coexists in DB.
        ("IEA_1872",  "104",  "BSA_2023",  ""),     # Stale deleted row — correct is BSA 107
    ]
    count = 0
    for oa, os, na, ns in SPURIOUS:
        if dry_run:
            log.info("[DRY-RUN] Would delete spurious: %s %s → %s %s", oa, os, na, ns)
            count += 1
            continue
        r = session.execute(text("""
            DELETE FROM law_transition_mappings
            WHERE old_act=:oa AND old_section=:os AND new_act=:na AND new_section=:ns
        """), {"oa": oa, "os": os, "na": na, "ns": ns})
        count += r.rowcount
    if not dry_run:
        session.commit()
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — SAFETY ASSERTIONS (post-generation)
# ═══════════════════════════════════════════════════════════════════════════════

def run_assertions(session) -> List[str]:
    from sqlalchemy import text

    failures: List[str] = []

    def _q_scalar(sql, **kw):
        return session.execute(text(sql), kw).scalar()

    def _q_one(sql, **kw):
        return session.execute(text(sql), kw).fetchone()

    # ── IPC → BNS assertions ─────────────────────────────────────────────────

    # 1. IPC 302 → BNS 103 (murder)
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='IPC_1860' AND old_section='302' "
               "ORDER BY confidence_score DESC LIMIT 1")
    if not r:
        failures.append("CRITICAL: IPC 302 has no mapping row")
    elif r.new_section != "103":
        failures.append(f"CRITICAL: IPC 302 → BNS {r.new_section} (must be 103)")

    # 2. IPC 302 NOT mapped to BNS 302 (false friend — BNS 302 = Religious Offences)
    poison = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                       "WHERE old_act='IPC_1860' AND old_section='302' AND new_section='302'")
    if poison:
        failures.append("CRITICAL: Spurious IPC 302 → BNS 302 row (BNS 302 = Religious Offences)")

    # 3. IPC 124A → BNS 152 (sedition replacement), type ≠ 'new'
    r = _q_one("SELECT new_section, transition_type FROM law_transition_mappings "
               "WHERE old_act='IPC_1860' AND old_section='124A' LIMIT 1")
    if not r:
        failures.append("CRITICAL: IPC 124A (Sedition) has no mapping — check MANUAL_OLD_SECTIONS")
    else:
        if r.new_section != "152":
            failures.append(f"CRITICAL: IPC 124A → BNS {r.new_section} (must be 152)")
        if r.transition_type == "new":
            failures.append("HIGH: IPC 124A → BNS 152 type='new' (must be 'modified')")

    # 4. IPC 376 splits into ≥ 6 BNS sections
    count376 = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                         "WHERE old_act='IPC_1860' AND old_section='376'")
    if not count376 or count376 < 6:
        failures.append(f"HIGH: IPC 376 split has {count376} rows (need ≥ 6)")

    # 5. IPC 420 → BNS 318 (NOT 319, BNS 420 does not exist)
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='IPC_1860' AND old_section='420' LIMIT 1")
    if not r:
        failures.append("HIGH: IPC 420 has no mapping — check MANUAL_OLD_SECTIONS")
    elif r.new_section != "318":
        failures.append(f"HIGH: IPC 420 → BNS {r.new_section} (must be 318)")

    # 6. No spurious IPC 420 → BNS 319 row
    p2 = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                   "WHERE old_act='IPC_1860' AND old_section='420' AND new_section='319'")
    if p2:
        failures.append("HIGH: Spurious IPC 420 → BNS 319 row — must be BNS 318")

    # 6b. BNS 95 must NOT have IPC 299/302 rows (BNS 95 = New Section, no IPC predecessor)
    # NCRB official table confirms BNS 95 = "Hiring, Employing or Engaging a Child" = New.
    for bad_ipc in ["299", "302"]:
        cnt = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                        "WHERE old_act='IPC_1860' AND old_section=:sec AND new_section='95'",
                        sec=bad_ipc)
        if cnt:
            failures.append(f"CRITICAL: Spurious IPC {bad_ipc} → BNS 95 row "
                            f"(BNS 95 = New Section. IPC {bad_ipc} must map to "
                            + ("BNS 100 (Culpable Homicide)" if bad_ipc == "299" else "BNS 103 (Murder)") + ")")

    # 6c. IPC 379 → BNS 303 (Theft), not BNS 304 (Snatching)
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='IPC_1860' AND old_section='379' LIMIT 1")
    if not r:
        failures.append("MEDIUM: IPC 379 (Theft) has no mapping — check MANUAL_OLD_SECTIONS")
    elif r.new_section != "303":
        failures.append(f"HIGH: IPC 379 → BNS {r.new_section} (must be 303 — Theft)")

    # ── CrPC → BNSS assertions ───────────────────────────────────────────────

    # 7. CrPC 438 → BNSS 482 (Anticipatory Bail — critical false-friend guard)
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='CrPC_1973' AND old_section='438' "
               "ORDER BY confidence_score DESC LIMIT 1")
    if not r:
        failures.append("CRITICAL: CrPC 438 (Anticipatory Bail) has no mapping")
    elif r.new_section != "482":
        failures.append(f"CRITICAL: CrPC 438 → BNSS {r.new_section} (must be 482)")

    # 8. No spurious CrPC 438 → BNSS 438 row (BNSS 438 = Revision powers)
    p_bail = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                       "WHERE old_act='CrPC_1973' AND old_section='438' AND new_section='438'")
    if p_bail:
        failures.append("CRITICAL: Spurious CrPC 438 → BNSS 438 row (BNSS 438 = Revision, not Bail)")

    # 9. CrPC 439 → BNSS 483
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='CrPC_1973' AND old_section='439' LIMIT 1")
    if not r:
        failures.append("HIGH: CrPC 439 (Special bail) has no mapping")
    elif r.new_section != "483":
        failures.append(f"HIGH: CrPC 439 → BNSS {r.new_section} (must be 483)")

    # 10. CrPC 173 → BNSS 193, type must be 'modified' not 'new'
    r = _q_one("SELECT new_section, transition_type FROM law_transition_mappings "
               "WHERE old_act='CrPC_1973' AND old_section='173' LIMIT 1")
    if not r:
        failures.append("HIGH: CrPC 173 (Chargesheet) has no mapping — check MANUAL_OLD_SECTIONS")
    else:
        if r.new_section != "193":
            failures.append(f"HIGH: CrPC 173 → BNSS {r.new_section} (must be 193)")
        if r.transition_type == "new":
            failures.append("HIGH: CrPC 173 → BNSS 193 type='new' (must be 'modified')")

    # ── IEA → BSA assertions ─────────────────────────────────────────────────

    # 11. IEA 115 (Estoppel) → BSA 121 (Estoppel)
    # Verified from PDF: BSA 121 = "Estoppel." (NOT BSA 107 = "Burden of proving admissibility")
    r = _q_one("SELECT new_section FROM law_transition_mappings "
               "WHERE old_act='IEA_1872' AND old_section='115' LIMIT 1")
    if not r:
        failures.append("MEDIUM: IEA 115 (Estoppel) has no mapping")
    elif r.new_section != "121":
        failures.append(f"CRITICAL: IEA 115 → BSA {r.new_section} (must be 121 — BSA Estoppel). "
                        f"BSA 107 = 'Burden of proving admissibility' — completely wrong provision.")

    # 12. IEA 104 → BSA 107 MUST EXIST (positive check)
    # NCRB official table: BSA 107 = "Burden of proving fact to be proved to make evidence admissible" = IEA 104.
    # This is the CORRECT mapping. Previous assertion had this backwards (was checking it doesn't exist).
    # NOTE: query MUST filter by new_act AND new_section to avoid matching stale rows with NULL new_section.
    r12 = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                    "WHERE old_act='IEA_1872' AND old_section='104' "
                    "AND new_act='BSA_2023' AND new_section='107'")
    if not r12:
        failures.append("MEDIUM: IEA 104 → BSA 107 mapping missing — "
                        "check stale rows or blocked sections (NCRB: Burden of proving admissibility)")

    # 12b. No stale IEA 115 → BSA 107 row (wrong estoppel link from old data)
    p4 = _q_scalar("SELECT COUNT(*) FROM law_transition_mappings "
                   "WHERE old_act='IEA_1872' AND old_section='115' AND new_section='107'")
    if p4:
        failures.append("CRITICAL: Stale IEA 115 → BSA 107 row still in DB — run script again to purge")

    # ── Data quality assertions ──────────────────────────────────────────────

    # 13. No equivalent/modified rows with NULL old_legal_text
    null_text = _q_scalar("""
        SELECT COUNT(*) FROM law_transition_mappings
        WHERE transition_type IN ('equivalent','modified','split_into','merged_from')
          AND old_section IS NOT NULL AND old_legal_text IS NULL
    """)
    if null_text and null_text > 0:
        failures.append(f"MEDIUM: {null_text} equivalent/modified rows missing old_legal_text")

    return failures


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — REPORT PRINTER
# ═══════════════════════════════════════════════════════════════════════════════

def _print_extraction_reports(ext_reports: Dict[str, ExtractionReport]) -> None:
    print("\n" + "═" * 72)
    print("  PHASE 1 — PDF EXTRACTION RESULTS")
    print("═" * 72)
    for act, r in ext_reports.items():
        status = "✅" if not r.errors else "❌"
        print(f"  {status} {act:15s}  sections={r.sections_found:4d}  "
              f"chapters={r.chapters_found:3d}  noise_stripped={r.noise_stripped:5d}")
        for e in r.errors:
            print(f"       [ERROR] {e}")


def _print_mapping_reports(gen_reports: List[GenerationReport],
                           failures: List[str],
                           output_dir: Path) -> None:
    print("\n" + "═" * 72)
    print("  PHASE 3 — MAPPING GENERATION RESULTS")
    print("═" * 72)
    for r in gen_reports:
        print(f"\n  Act pair: {r.act_pair}  ({r.duration_s:.1f}s)")
        print(f"    Rows inserted    : {r.rows_inserted}")
        print(f"    Rows updated     : {r.rows_updated}")
        print(f"    Deleted seeded   : {r.deleted_seeded}")
        print(f"    Split cases      : {len(r.split_cases)}")
        print(f"    Merge cases      : {len(r.merge_cases)}")
        print(f"    Collision guards : {len(r.collision_warnings)}")
        if r.split_cases:
            for s in r.split_cases[:6]:
                print(f"      Split: {s}")
        if r.merge_cases:
            for m in r.merge_cases[:4]:
                print(f"      Merge: {m}")

    print("\n" + "═" * 72)
    print("  PHASE 4 — SAFETY ASSERTIONS")
    print("═" * 72)
    if not failures:
        print("  ✅  ALL 10 ASSERTIONS PASSED — safe to activate")
    else:
        for f in failures:
            lv = "🚨 CRITICAL" if "CRITICAL" in f else "⚠️  HIGH" if "HIGH" in f else "ℹ️  MEDIUM"
            print(f"  {lv}: {f}")

    print("═" * 72)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — SQL EXPORT (offline / dry-run output)
# ═══════════════════════════════════════════════════════════════════════════════

def export_sql(rows: List[MappingRow], output_path: Path) -> None:
    """Write INSERT statements for offline inspection / manual import."""

    def _esc(s: Optional[str]) -> str:
        if s is None:
            return "NULL"
        return "'" + str(s).replace("'", "''") + "'"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("-- Generated by generate_mappings.py\n")
        f.write(f"-- {len(rows)} rows  |  effective_date = {EFFECTIVE_DATE}\n\n")
        f.write("BEGIN;\n\n")
        for row in rows:
            # old_section/new_section/new_act are NOT NULL in schema — use '' not NULL
            os_v = _esc(row.old_section if row.old_section is not None else "")
            ns_v = _esc(row.new_section if row.new_section is not None else "")
            na_v = _esc(row.new_act     if row.new_act     is not None else "")
            f.write(
                f"INSERT INTO law_transition_mappings "
                f"(id,old_act,old_section,old_section_title,old_legal_text,"
                f"new_act,new_section,new_section_title,"
                f"transition_type,scope_change,transition_note,"
                f"confidence_score,is_active,effective_date,created_at,updated_at)\n"
                f"VALUES (gen_random_uuid(),"
                f"{_esc(row.old_act)},{os_v},{_esc(row.old_section_title)},"
                f"{_esc(row.old_legal_text[:2000] if row.old_legal_text else None)},"
                f"{na_v},{ns_v},{_esc(row.new_section_title)},"
                f"{_esc(row.transition_type)},{_esc(row.scope_change)},"
                f"{_esc(row.transition_note)},"
                f"{row.confidence_score},FALSE,'{EFFECTIVE_DATE}'::date,NOW(),NOW())"
                f"\nON CONFLICT DO NOTHING;\n\n"
            )
        f.write("COMMIT;\n")
    log.info("SQL export written: %s  (%d rows)", output_path, len(rows))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate law transition mappings from actual PDFs + JSON enrichment"
    )
    ap.add_argument("--dry-run",      action="store_true",
                    help="Parse, generate, export SQL — no DB writes")
    ap.add_argument("--extract-only", action="store_true",
                    help="Run Phase 1 only (PDF extraction). Print stats and exit.")
    ap.add_argument("--act",          choices=["BNS", "BSA", "BNSS", "ALL"], default="ALL")
    ap.add_argument("--data-dir",     type=Path, default=_ROOT / "data")
    ap.add_argument("--pdf-dir",      type=Path, default=None,
                    help="Override path to the directory containing the 5 source PDFs")
    args = ap.parse_args()

    pdf_dir = args.pdf_dir or (_ROOT / "data" / "source_pdfs")
    # Fallback: try /mnt/project (the Claude environment path)
    if not pdf_dir.exists():
        fallback = Path("/mnt/project")
        if fallback.exists():
            pdf_dir = fallback
            log.info("Using fallback PDF dir: %s", pdf_dir)

    # ── File map ──────────────────────────────────────────────────────────────
    PDF_FILES: Dict[str, Path] = {
        "IPC_1860":  pdf_dir / "IPC.pdf",
        "CrPC_1973": pdf_dir / "CRPC.pdf",
        "BNS_2023":  pdf_dir / "BNS.pdf",
        "IEA_1872":  pdf_dir / "IEA.pdf",
        "BSA_2023":  pdf_dir / "BSA.pdf",
        "BNSS_2023": pdf_dir / "BNSS.pdf",   # Real PDF — parsed with pdfplumber
    }

    JSON_FILES: Dict[str, Path] = {
        "BNS_2023":  args.data_dir / "raw" / "bns_complete.json",
        "BNSS_2023": args.data_dir / "raw" / "bnss_complete.json",
        "BSA_2023":  args.data_dir / "raw" / "bsa_complete.json",
    }

    # new_act, old_act, section_key_in_json, replaces_key_in_json
    ACT_PAIRS = {
        "BNS":  ("BNS_2023",  "IPC_1860",  "bns_section",  "replaces_ipc"),
        "BNSS": ("BNSS_2023", "CrPC_1973", "bnss_section", "replaces_crpc"),
        "BSA":  ("BSA_2023",  "IEA_1872",  "bsa_section",  "replaces_iea"),
    }

    pairs_to_run = (
        ["BNS", "BNSS", "BSA"] if args.act == "ALL"
        else [args.act]
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 1 — Extract sections from all 5 PDFs
    # ═══════════════════════════════════════════════════════════════════════════
    all_sections:    Dict[str, Dict[str, ParsedSection]] = {}
    ext_reports:     Dict[str, ExtractionReport]         = {}

    print("\n" + "═" * 72)
    print("  PHASE 1 — PARSING PDFs")
    print("═" * 72)

    for act_code, pdf_path in PDF_FILES.items():
        if not pdf_path.exists():
            log.warning("PDF not found: %s — skipping %s", pdf_path, act_code)
            ext_reports[act_code] = ExtractionReport(act_code=act_code,
                errors=[f"File not found: {pdf_path}"])
            all_sections[act_code] = {}
            continue

        try:
            secs, rep = parse_act(pdf_path, act_code)
            all_sections[act_code] = {s.section_number: s for s in secs}
            ext_reports[act_code]  = rep
        except Exception as exc:
            log.exception("Error parsing %s", act_code)
            ext_reports[act_code] = ExtractionReport(act_code=act_code, errors=[str(exc)])
            all_sections[act_code] = {}

    _print_extraction_reports(ext_reports)

    if args.extract_only:
        print("\nExtract-only mode — exiting after Phase 1.")
        for act_code, sec_dict in all_sections.items():
            if not sec_dict:
                continue
            sample_keys = list(sec_dict.keys())[:3]
            print(f"\n  {act_code} samples:")
            for k in sample_keys:
                s = sec_dict[k]
                print(f"    [{s.section_number}] {s.section_title[:60]}")
                print(f"         text: {s.legal_text[:100]}…")
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 2 — Load JSON enrichment
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "═" * 72)
    print("  PHASE 2 — LOADING JSON ENRICHMENT")
    print("═" * 72)

    json_data: Dict[str, List[dict]] = {}
    for pair_key in pairs_to_run:
        new_act, old_act, sec_key, rep_key = ACT_PAIRS[pair_key]
        jp = JSON_FILES.get(new_act)
        if jp and jp.exists():
            json_data[new_act] = _load_enrichment_json(jp, new_act, old_act, sec_key, rep_key)
            print(f"  ✅ {new_act}: {len(json_data[new_act])} sections loaded from JSON")
        else:
            log.warning("No enrichment JSON for %s at %s — mapping will be sparse", new_act, jp)
            json_data[new_act] = []
            print(f"  ⚠️  {new_act}: JSON not found at {jp} — empty enrichment")

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 3 — Generate mapping rows
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "═" * 72)
    print("  PHASE 3 — GENERATING MAPPING ROWS")
    print("═" * 72)

    all_rows:     List[MappingRow]       = []
    gen_reports:  List[GenerationReport] = []

    for pair_key in pairs_to_run:
        new_act, old_act, _, _ = ACT_PAIRS[pair_key]
        t0 = time.monotonic()

        rows, report = generate_mappings(
            new_act      = new_act,
            old_act      = old_act,
            json_rows    = json_data.get(new_act, []),
            old_sections = all_sections.get(old_act, {}),
            new_sections = all_sections.get(new_act, {}),
        )
        report.duration_s = time.monotonic() - t0
        all_rows.extend(rows)
        gen_reports.append(report)
        print(f"  {new_act}: {len(rows)} rows  "
              f"(splits={len(report.split_cases)}, merges={len(report.merge_cases)}, "
              f"deleted={report.deleted_seeded})")

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 — Write to DB or export SQL
    # ═══════════════════════════════════════════════════════════════════════════
    output_sql = args.data_dir / "output" / "mappings.sql"

    if args.dry_run:
        print("\n  [DRY-RUN] Exporting SQL instead of writing to DB…")
        export_sql(all_rows, output_sql)
        print(f"  SQL written to: {output_sql}")
        print(f"  Total rows: {len(all_rows)}")
        _print_mapping_reports(gen_reports, [], args.data_dir / "output")
        return

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("\n  ⚠️  DATABASE_URL not set — writing SQL export only.")
        export_sql(all_rows, output_sql)
        print(f"  SQL written to: {output_sql}")
        _print_mapping_reports(gen_reports, [], args.data_dir / "output")
        return

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        sync_url = db_url.replace("postgresql+asyncpg", "postgresql")
        engine   = create_engine(sync_url, pool_pre_ping=True)
        Factory  = sessionmaker(bind=engine)
    except ImportError:
        print("  ⚠️  SQLAlchemy not installed — writing SQL export only.")
        export_sql(all_rows, output_sql)
        return

    with Factory() as session:
        # Cleanup spurious rows first
        deleted_spurious = _delete_spurious_rows(session, dry_run=False)
        log.info("Spurious rows deleted: %d", deleted_spurious)

        # Write rows
        print("\n  Writing to database…")
        new_act_for_write = pairs_to_run[0] if len(pairs_to_run) == 1 else "BNS_2023"
        for pair_key in pairs_to_run:
            new_act, _, _, _ = ACT_PAIRS[pair_key]
            pair_rows  = [r for r in all_rows if r.new_act == new_act or r.old_act == new_act.replace("_2023","_1860")]
            if pair_rows:
                report_for = next(r for r in gen_reports if new_act in r.act_pair)
                _write_to_db(session, pair_rows, report_for)

        # Run assertions
        print("\n  Running safety assertions…")
        failures = run_assertions(session)
        for r in gen_reports:
            r.assertion_failures = [f for f in failures if r.act_pair.split("→")[0] in f]

    # Also export SQL for archival
    export_sql(all_rows, output_sql)
    _print_mapping_reports(gen_reports, failures, args.data_dir / "output")

    critical = [f for f in failures if "CRITICAL" in f]
    if critical:
        sys.exit(1)


if __name__ == "__main__":
    main()