"""Two-pass PDF extractor for BPR&D composite legal PDFs (BNS, BNSS, BSA).

Pass 1 (StructureMapper): Spatial classification — every text block on every page
is labelled HEADER | FOOTER | PAGE_NUMBER | SECTION_TEXT | FOOTNOTE | COMPARISON_BLOCK
using bounding-box coordinates and trigger-phrase patterns.

Pass 2 (TextExtractor): Content extraction — pulls text ONLY from SECTION_TEXT
blocks, in reading order (top→bottom, left→right), reconstructing cross-page
hyphenated words.

These two classes are kept separate so each can be independently tested and
so the structural map can be inspected during debugging.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Block classification enum
# ---------------------------------------------------------------------------

class BlockType(str, Enum):
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    PAGE_NUMBER = "PAGE_NUMBER"
    SECTION_TEXT = "SECTION_TEXT"
    FOOTNOTE = "FOOTNOTE"
    COMPARISON_BLOCK = "COMPARISON_BLOCK"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedBlock:
    block_type: BlockType
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_sizes: List[float] = field(default_factory=list)
    page_number: int = 0


# StructureMap: page_number (1-based) → list of classified blocks
StructureMap = Dict[int, List[ClassifiedBlock]]


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

# Act name patterns used for header detection
_ACT_NAME_RE = re.compile(
    r"BHARATIYA\s+NYAYA\s+SANHITA"
    r"|BHARATIYA\s+NAGARIK\s+SURAKSHA\s+SANHITA"
    r"|BHARATIYA\s+SAKSHYA\s+ADHINIYAM",
    re.IGNORECASE,
)

# Pure page-number line: optional em-dashes or hyphens around a number
_PAGE_NUMBER_RE = re.compile(r"^\s*[—\-]?\s*\d{1,4}\s*[—\-]?\s*$")

# Footnote definition: "55 Section 63, ..." — appears as standalone line
_FOOTNOTE_DEF_RE = re.compile(
    r"^\d{1,2}\s+Section\s+\d+",
    re.IGNORECASE,
)

# Comparison block trigger phrases from the BPR&D editorial layer
_COMPARISON_TRIGGERS_RE = re.compile(
    r"^COMPARISON\s+WITH"
    r"|^Modification\s*[&]\s*Addition"
    r"|^Consolidation\s+and\s+Modifications"
    r"|^COMPARISON\s+SUMMARY"
    r"|^In\s+sub\s*[\-\s]?section",
    re.IGNORECASE,
)

# Thresholds (fraction of page height)
_HEADER_ZONE = 0.08
_FOOTER_ZONE = 0.92


# ---------------------------------------------------------------------------
# Pass 1 — StructureMapper
# ---------------------------------------------------------------------------

class StructureMapper:
    """Classifies every text block on every page by its structural role.

    Uses bounding-box coordinates as the primary classifier, falling back to
    text-pattern heuristics. Operates spatially — NOT linguistically.
    """

    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path

    def build(self, doc: fitz.Document) -> StructureMap:
        """Run Pass 1 over the entire document.

        Returns:
            StructureMap mapping page_number → List[ClassifiedBlock].
        """
        structure_map: StructureMap = {}

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_number = page_idx + 1
            page_height = page.rect.height
            page_width = page.rect.width

            rule_ys = self._find_horizontal_rules(page, page_height)
            raw_blocks = page.get_text("dict")["blocks"]

            classified: List[ClassifiedBlock] = []
            for block in raw_blocks:
                if block.get("type") != 0:
                    continue  # skip image blocks

                bbox = block["bbox"]
                x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                block_text = self._extract_block_text(block)
                font_sizes = self._extract_font_sizes(block)

                if not block_text.strip():
                    continue

                block_type = self._classify_block(
                    block_text, x0, y0, x1, y1,
                    page_height, page_width, rule_ys,
                )
                classified.append(ClassifiedBlock(
                    block_type=block_type,
                    text=block_text,
                    x0=x0, y0=y0, x1=x1, y1=y1,
                    font_sizes=font_sizes,
                    page_number=page_number,
                ))

            structure_map[page_number] = classified

        total_blocks = sum(len(v) for v in structure_map.values())
        section_blocks = sum(
            1 for blocks in structure_map.values()
            for b in blocks if b.block_type == BlockType.SECTION_TEXT
        )
        logger.info(
            "StructureMapper complete — pdf=%s pages=%d total_blocks=%d section_blocks=%d",
            self.pdf_path.name, len(doc), total_blocks, section_blocks,
        )
        return structure_map

    # ------------------------------------------------------------------

    def _find_horizontal_rules(self, page: fitz.Page, page_height: float) -> List[float]:
        """Return y-coordinates of thin wide rectangles (horizontal separator rules).

        These lines separate footnotes from the main body in BPR&D PDFs.
        Only rules in the lower half of the page are considered.
        """
        rules: List[float] = []
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is None:
                continue
            r = fitz.Rect(rect)
            # A horizontal rule: very thin, wide, in lower half of page
            if (r.width > page_height * 0.30
                    and r.height < 3.0
                    and r.y0 > page_height * 0.50):
                rules.append(r.y0)
        return sorted(rules)

    def _extract_block_text(self, block: dict) -> str:
        """Reconstruct plain text from a 'dict' format block."""
        lines = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans)
            lines.append(line_text)
        return "\n".join(lines)

    def _extract_font_sizes(self, block: dict) -> List[float]:
        """Collect all font sizes used in this block (for superscript detection)."""
        sizes: List[float] = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sz = span.get("size", 0.0)
                if sz > 0:
                    sizes.append(sz)
        return sizes

    def _classify_block(
        self,
        text: str,
        x0: float, y0: float, x1: float, y1: float,
        page_height: float,
        page_width: float,
        rule_ys: List[float],
    ) -> BlockType:
        """Apply classification rules in priority order."""
        stripped = text.strip()
        first_line = stripped.split("\n")[0].strip() if stripped else ""

        # P1 — Header zone: top 8% of page with act name or all-caps chapter title
        if y0 < page_height * _HEADER_ZONE:
            if _ACT_NAME_RE.search(first_line):
                return BlockType.HEADER
            if first_line.isupper() and len(first_line) > 5:
                return BlockType.HEADER

        # P2 — Footer zone: bottom 8% of page
        if y1 > page_height * _FOOTER_ZONE:
            return BlockType.FOOTER

        # P3 — Pure page number (anywhere on page)
        if _PAGE_NUMBER_RE.match(stripped):
            return BlockType.PAGE_NUMBER

        # P4 — Footnote: below the lowest horizontal rule on the page
        if rule_ys and y0 > rule_ys[-1]:
            return BlockType.FOOTNOTE

        # P5 — Footnote definition by text pattern (even if above the rule)
        if _FOOTNOTE_DEF_RE.match(first_line):
            return BlockType.FOOTNOTE

        # P6 — Comparison block by BPR&D editorial trigger phrase
        if _COMPARISON_TRIGGERS_RE.match(first_line):
            return BlockType.COMPARISON_BLOCK

        return BlockType.SECTION_TEXT


# ---------------------------------------------------------------------------
# Pass 2 — TextExtractor
# ---------------------------------------------------------------------------

class TextExtractor:
    """Extracts and assembles text from SECTION_TEXT blocks only.

    Takes a StructureMap from Pass 1 and returns the document's law text
    in reading order, with cross-page hyphenated words reconstructed.
    """

    def extract(self, structure_map: StructureMap) -> Tuple[str, List[int]]:
        """Extract text from all SECTION_TEXT blocks.

        Returns:
            raw_section_text: concatenated law text for the full document.
            superscript_positions: character offsets where small-font (superscript)
                blocks were detected — consumed by text_cleaner.py Rule 3.
        """
        page_texts: Dict[int, str] = {}
        superscript_offsets: List[int] = []
        running_offset = 0

        for page_number in sorted(structure_map.keys()):
            blocks = structure_map[page_number]

            # Keep only SECTION_TEXT; sort by reading order (y0 rounded, then x0)
            section_blocks = sorted(
                [b for b in blocks if b.block_type == BlockType.SECTION_TEXT],
                key=lambda b: (round(b.y0), b.x0),
            )

            # Compute median font size for this page (for superscript detection)
            all_sizes = [sz for b in section_blocks for sz in b.font_sizes if sz > 0]
            median_size = statistics.median(all_sizes) if all_sizes else 0.0
            threshold = median_size * 0.70 if median_size > 0 else 0.0

            page_parts: List[str] = []
            for block in section_blocks:
                block_start = running_offset
                page_parts.append(block.text)
                running_offset += len(block.text) + 1  # +1 for joining newline

                # Flag blocks that contain small-font (superscript) content
                if threshold > 0 and block.font_sizes:
                    if any(sz < threshold for sz in block.font_sizes):
                        superscript_offsets.append(block_start)

            page_texts[page_number] = "\n".join(page_parts)

        full_text = self._join_pages(page_texts)
        return full_text, superscript_offsets

    def _join_pages(self, page_texts: Dict[int, str]) -> str:
        """Join per-page texts, reconstructing hyphenated word breaks at page edges."""
        result_parts: List[str] = []

        for page_number in sorted(page_texts.keys()):
            page_text = page_texts[page_number]
            if not result_parts:
                result_parts.append(page_text)
                continue

            prev = result_parts[-1]
            prev_stripped = prev.rstrip()

            # If previous page ends with a hyphen, check whether the first word
            # of the next page starts with a lowercase letter (genuine line-break hyphen)
            if prev_stripped.endswith("-"):
                next_words = page_text.lstrip().split(None, 1)
                if next_words and next_words[0] and next_words[0][0].islower():
                    # Remove trailing hyphen, join directly (no space)
                    result_parts[-1] = prev_stripped[:-1] + page_text.lstrip()
                    continue

            result_parts.append(page_text)

        return "\n".join(result_parts)


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: Path) -> Tuple[str, List[int], StructureMap]:
    """Run both passes on a PDF file and return the extracted law text.

    Args:
        pdf_path: Absolute path to the PDF (BNS.pdf, BNSS.pdf, or BSA.pdf).

    Returns:
        raw_section_text: SECTION_TEXT content only, in document order.
        superscript_positions: character offsets of small-font blocks.
        structure_map: full StructureMap for debugging / inspection.
    """
    doc = fitz.open(str(pdf_path))
    try:
        mapper = StructureMapper(pdf_path)
        structure_map = mapper.build(doc)

        extractor = TextExtractor()
        raw_text, superscript_positions = extractor.extract(structure_map)

        logger.info(
            "extract_pdf complete — file=%s chars=%d superscript_blocks=%d",
            pdf_path.name, len(raw_text), len(superscript_positions),
        )
        return raw_text, superscript_positions, structure_map
    finally:
        doc.close()
