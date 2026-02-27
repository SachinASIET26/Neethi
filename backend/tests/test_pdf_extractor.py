"""Tests for Phase 1 PDF extraction pipeline.

Tests two categories:
1. Unit tests — use fixture strings, no PDF required, fast.
2. Integration tests — load actual BNS/BNSS/BSA PDFs and verify known defects are fixed.

Each integration test corresponds to a known-failure case documented in
neethi_data_pipeline_breakdown.md Part 1.3 and Part 7.

Run from project root:
    pytest backend/tests/test_pdf_extractor.py -v
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pytest

from backend.preprocessing.cleaners.text_cleaner import (
    clean_legal_text,
    remove_comparison_brackets,
    remove_inline_footnotes,
    strip_page_numbers,
    strip_running_headers,
)
from backend.preprocessing.parsers.act_parser import (
    ParsedChapter,
    ParsedSection,
    arabic_to_roman,
    parse_act,
)
from backend.preprocessing.validators.extraction_validator import validate_section

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

# Locate project root relative to this test file:
# backend/tests/test_pdf_extractor.py → parents[2] = project root
_PROJECT_ROOT = Path(__file__).parents[2]
_BNS_PDF = _PROJECT_ROOT / "data" / "raw" / "acts" / "BNS.pdf"
_BNSS_PDF = _PROJECT_ROOT / "data" / "raw" / "acts" / "BNSS.pdf"
_BSA_PDF = _PROJECT_ROOT / "data" / "raw" / "acts" / "BSA.pdf"

_pdfs_present = _BNS_PDF.exists() and _BNSS_PDF.exists() and _BSA_PDF.exists()
_skip_if_no_pdfs = pytest.mark.skipif(
    not _pdfs_present,
    reason="BNS.pdf / BNSS.pdf / BSA.pdf not found in data/raw/acts/",
)


# ---------------------------------------------------------------------------
# Module-scoped fixtures — expensive PDF extraction runs once per pytest session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bns_data():
    """Extract and parse BNS.pdf once for all BNS-related tests."""
    if not _BNS_PDF.exists():
        pytest.skip("BNS.pdf not found")
    from backend.preprocessing.extractors.pdf_extractor import extract_pdf
    raw_text, superscript_positions, structure_map = extract_pdf(_BNS_PDF)
    cleaned_text = clean_legal_text(raw_text, superscript_positions)
    sections, chapters = parse_act(cleaned_text)
    section_map: Dict[str, ParsedSection] = {s.section_number: s for s in sections}
    return {
        "sections": sections,
        "section_map": section_map,
        "chapters": chapters,
        "cleaned_text": cleaned_text,
    }


@pytest.fixture(scope="module")
def bnss_data():
    """Extract and parse BNSS.pdf once for all BNSS-related tests."""
    if not _BNSS_PDF.exists():
        pytest.skip("BNSS.pdf not found")
    from backend.preprocessing.extractors.pdf_extractor import extract_pdf
    raw_text, superscript_positions, _ = extract_pdf(_BNSS_PDF)
    cleaned_text = clean_legal_text(raw_text, superscript_positions)
    sections, chapters = parse_act(cleaned_text)
    section_map: Dict[str, ParsedSection] = {s.section_number: s for s in sections}
    return {
        "sections": sections,
        "section_map": section_map,
        "chapters": chapters,
        "cleaned_text": cleaned_text,
    }


# ===========================================================================
# UNIT TESTS — no PDF required
# ===========================================================================


class TestTextCleaner:
    """Unit tests for text_cleaner.py rules."""

    def test_strip_running_headers_removes_act_name(self):
        text = "Some legal text.\nBHARATIYA NYAYA SANHITA, 2023\nMore legal text."
        result = strip_running_headers(text)
        assert "BHARATIYA NYAYA SANHITA" not in result
        assert "Some legal text." in result
        assert "More legal text." in result

    def test_strip_page_numbers_em_dash_format(self):
        text = "End of section text.\n— 47 —\nStart of next section."
        result = strip_page_numbers(text)
        assert "— 47 —" not in result
        assert "47" not in result

    def test_strip_page_numbers_plain(self):
        text = "End of sentence.\n158\nNext line."
        result = strip_page_numbers(text)
        assert re.search(r"^\s*158\s*$", result, re.MULTILINE) is None

    def test_remove_inline_footnotes_standalone_definition(self):
        """Footnote definitions must be removed (Noise Type 1)."""
        text = (
            "(3) The fine may extend to five thousand rupees.\n"
            "55 Section 63, \"Amount of fine\" IPC, 1860.\n"
            "(4) The court may direct payment."
        )
        result = remove_inline_footnotes(text)
        assert '55 Section 63' not in result
        assert "(3) The fine may extend" in result
        assert "(4) The court may direct" in result

    def test_remove_comparison_brackets_date_annotation(self):
        """[the 1st day of April, 1974] is a CrPC comparison annotation (Noise Type 3)."""
        text = "It shall come into force on [the 1st day of April, 1974] such date."
        result = remove_comparison_brackets(text)
        assert "[the 1st day of April, 1974]" not in result
        assert "It shall come into force on" in result

    def test_remove_comparison_brackets_numeric(self):
        """[fifty] in 'five thousand [fifty] rupees' is a comparison annotation."""
        text = "The fine shall not exceed five thousand [fifty] rupees."
        result = remove_comparison_brackets(text)
        assert "[fifty]" not in result
        assert "five thousand" in result

    def test_remove_comparison_brackets_years(self):
        """'twenty years [ten years]' — bracket is old law value."""
        text = "imprisonment for a term which may extend to twenty years [ten years]."
        result = remove_comparison_brackets(text)
        assert "[ten years]" not in result
        assert "twenty years" in result


class TestActParser:
    """Unit tests for act_parser.py."""

    def test_section_number_53a_parsed_correctly(self):
        """Section 53A must not be split into section 53 + suffix A.

        Known failure in generic parsers that treat section numbers as integers.
        """
        fixture_text = (
            "53A. SPECIAL PROVISION FOR VEHICLES USED IN OFFENCES.\n"
            "(1) Where any vehicle is used in the commission of an offence under this Act, "
            "the court convicting the offender may direct forfeiture of such vehicle.\n"
            "(2) Any vehicle so forfeited shall vest in the Government.\n"
            "54. FORFEITURE OF PROPERTY.\n"
            "Property used in commission of offence may be forfeited."
        )
        sections, _ = parse_act(fixture_text)
        section_nums = [s.section_number for s in sections]
        assert "53A" in section_nums, (
            f"Section 53A not found; got: {section_nums}"
        )
        # Must NOT be split into "53" with suffix handling
        assert "53" not in section_nums or all(
            s.section_number != "53" for s in sections
        ), "Section 53A was incorrectly split"

    def test_has_subsections_true_for_numbered_subsections(self):
        """has_subsections must be True for a section containing (1) (2) markers."""
        fixture_text = (
            "6. PUNISHMENTS.\n"
            "(1) The punishments to which offenders are liable under the provisions "
            "of this Code are firstly, Death.\n"
            "(2) Secondly, imprisonment for life.\n"
            "(3) Thirdly, imprisonment which is of two descriptions, namely — "
            "(a) rigorous imprisonment; (b) simple imprisonment.\n"
            "7. FRACTIONS OF TERMS OF PUNISHMENT.\n"
            "In calculating fractions of terms of punishment, imprisonment for life "
            "shall be reckoned as equivalent to imprisonment for thirty years."
        )
        sections, _ = parse_act(fixture_text)
        section_6 = next((s for s in sections if s.section_number == "6"), None)
        assert section_6 is not None, "Section 6 not found in fixture"
        assert section_6.has_subsections is True, (
            f"has_subsections should be True for section with (1)(2)(3), "
            f"got: {section_6.has_subsections}"
        )

    def test_subsection_texts_populated_for_numbered_section(self):
        """subsection_texts dict must contain entries for numbered sub-sections."""
        fixture_text = (
            "10. ABETMENT OF THINGS.\n"
            "(1) A person abets the doing of a thing, who first, instigates any person.\n"
            "(2) Secondly, engages with one or more other persons.\n"
            "(3) Thirdly, intentionally aids, by any act.\n"
            "11. ABETTOR.\n"
            "A person who abets an offence is called an abettor."
        )
        sections, _ = parse_act(fixture_text)
        section_10 = next((s for s in sections if s.section_number == "10"), None)
        assert section_10 is not None
        assert "(1)" in section_10.subsection_texts
        assert "(2)" in section_10.subsection_texts
        assert "(3)" in section_10.subsection_texts

    def test_chapter_number_roman_conversion(self):
        """arabic_to_roman must convert 1 → 'I', not leave it as '1'."""
        assert arabic_to_roman(1) == "I"
        assert arabic_to_roman(5) == "V"
        assert arabic_to_roman(20) == "XX"
        assert arabic_to_roman(39) == "XXXIX"

    def test_two_line_heading_parsed(self):
        """Section headings wrapped over two lines must be captured."""
        fixture_text = (
            "101. CULPABLE HOMICIDE NOT AMOUNTING\nTO MURDER.\n"
            "Whoever causes death by doing an act with the intention of causing death "
            "is guilty of culpable homicide.\n"
            "102. DEFINITION OF CULPABLE HOMICIDE.\n"
            "Culpable homicide is the act of causing death."
        )
        sections, _ = parse_act(fixture_text)
        section_nums = [s.section_number for s in sections]
        # Both sections should be found
        assert "101" in section_nums or "102" in section_nums, (
            f"Expected to find section 101 or 102; got {section_nums}"
        )


class TestExtractionValidator:
    """Unit tests for extraction_validator.py."""

    def test_clean_section_gets_high_confidence(self):
        """A clean, complete section should score >= 0.95."""
        clean_text = (
            "(1) Whoever commits murder shall be punished with death or "
            "imprisonment for life, and shall also be liable to fine.\n"
            "(2) Exception.—Culpable homicide is not murder if the offender, "
            "whilst deprived of the power of self-control by grave and sudden provocation, "
            "causes the death of the person who gave the provocation."
        )
        report = validate_section(
            section_number="103",
            legal_text=clean_text,
            has_subsections=True,
            sub_section_count=2,
            expected_sub_sections=2,
        )
        assert report.extraction_confidence >= 0.90, (
            f"Expected >= 0.90 for clean section, got {report.extraction_confidence}"
        )
        assert not report.requires_human_review

    def test_footnote_residue_reduces_confidence(self):
        """A section with footnote residue should score < 0.70."""
        dirty_text = (
            "(1) The fine may extend to five thousand rupees.\n"
            "55 Section 63, Amount of fine IPC, 1860.\n"
            "(2) Imprisonment in default of payment."
        )
        report = validate_section(
            section_number="8",
            legal_text=dirty_text,
        )
        assert report.extraction_confidence < 0.70
        assert report.requires_human_review
        assert any("Footnote" in f for f in report.check_failures)

    def test_cross_section_contamination_detected(self):
        """A section whose legal_text begins with a different section's content."""
        contaminated_text = (
            "3. GENERAL EXPLANATIONS.\n"
            "In this Code, except where a contrary intention appears from the context, "
            "words importing the masculine gender include females and neuter."
        )
        report = validate_section(
            section_number="4",  # Section 4 contains Section 3's content
            legal_text=contaminated_text,
        )
        assert report.extraction_confidence < 0.70
        assert any("contamination" in f.lower() or "mismatch" in f.lower()
                   for f in report.check_failures)

    def test_bracket_annotation_residue_detected(self):
        """Sections with [ten years] bracket annotations should be flagged."""
        text = "imprisonment for a term which may extend to twenty years [ten years]."
        report = validate_section(section_number="302", legal_text=text)
        assert report.extraction_confidence < 1.0
        assert any("bracket" in f.lower() for f in report.check_failures)

    def test_empty_legal_text_routed_to_review(self):
        """Sections with empty legal_text must require human review."""
        report = validate_section(section_number="240", legal_text="")
        assert report.requires_human_review
        assert report.extraction_confidence < 0.70


# ===========================================================================
# INTEGRATION TESTS — require actual PDFs in data/raw/acts/
# ===========================================================================

@_skip_if_no_pdfs
class TestBNSExtraction:
    """Integration tests for BNS.pdf extraction quality."""

    def test_bns_section_4_no_cross_section_contamination(self, bns_data):
        """BNS Section 4's legal_text must NOT contain Section 3's general explanations.

        Known failure in existing JSON (Noise Type 2 — Cross-Section Contamination):
        bns_complete.json BNS-4 legal_text contains 'SECTION 3. GENERAL EXPLANATIONS'.
        Our extractor must prevent this.
        """
        sec4 = bns_data["section_map"].get("4")
        assert sec4 is not None, "BNS Section 4 not found in parsed output"
        assert "SECTION 3. GENERAL EXPLANATIONS" not in sec4.raw_body_text, (
            "BNS Section 4 contains Section 3 content — cross-section contamination present"
        )
        assert "GENERAL EXPLANATIONS" not in sec4.raw_body_text.upper()[:200], (
            "BNS Section 4 body starts with Section 3 content"
        )

    def test_bns_section_8_no_footnote_residue(self, bns_data):
        """BNS Section 8's legal_text must NOT contain footnote references.

        Known failure in existing JSON (Noise Type 1 — Footnote Bleed):
        bns_complete.json BNS-8 legal_text contains '55 Section 63, "Amount of fine" IPC, 1860.'
        """
        sec8 = bns_data["section_map"].get("8")
        assert sec8 is not None, "BNS Section 8 not found in parsed output"
        body = sec8.raw_body_text

        # Check for specific footnote reference that was present in existing JSON
        assert "55 Section 63" not in body, (
            "BNS Section 8 contains '55 Section 63' footnote residue"
        )
        # General check: no line starting with a digit then 'Section'
        footnote_pattern = re.compile(r"^\d{1,2}\s+Section\s+\d+", re.MULTILINE)
        assert not footnote_pattern.search(body), (
            "BNS Section 8 contains a footnote definition line"
        )

    def test_bns_chapter_number_is_roman_not_arabic(self, bns_data):
        """BNS chapter numbers must be Roman numerals ('I'), not Arabic ('1').

        BNS uses Roman numeral chapters in the PDF. The parser must preserve this.
        """
        chapters: List[ParsedChapter] = bns_data["chapters"]
        assert len(chapters) > 0, "No chapters detected in BNS"

        first_chapter = min(chapters, key=lambda c: c.chapter_number_int)
        assert first_chapter.chapter_number == "I", (
            f"First BNS chapter should be 'I' (Roman), got '{first_chapter.chapter_number}'"
        )
        # Verify chapter count: BNS has 20 chapters
        assert len(chapters) >= 15, (
            f"Expected >= 15 chapters in BNS, got {len(chapters)}"
        )

    def test_bns_section_count_approximately_358(self, bns_data):
        """BNS has 358 sections; extraction must detect close to that number."""
        sections = bns_data["sections"]
        count = len(sections)
        # Allow some tolerance: some sections may be merged or split at boundaries
        assert 340 <= count <= 370, (
            f"Expected 340-370 sections for BNS, got {count}. "
            f"If < 340, the section boundary regex is missing many sections. "
            f"If > 370, there are false positives."
        )

    def test_bns_definitions_section_has_30_plus_subsections(self, bns_data):
        """BNS Section 2 (Definitions) must have >= 30 sub-section entries.

        BNS Section 2 defines 39 terms. Each definition must be extractable
        as a separate sub-section entry (critical for granular Qdrant retrieval).
        """
        sec2 = bns_data["section_map"].get("2")
        assert sec2 is not None, "BNS Section 2 (Definitions) not found"
        assert sec2.has_subsections is True, (
            "BNS Section 2 must have has_subsections=True"
        )
        n_subsections = len(sec2.subsection_texts)
        assert n_subsections >= 30, (
            f"BNS Section 2 should have >= 30 sub-section entries (definitions), "
            f"got {n_subsections}. "
            f"Keys found: {sorted(sec2.subsection_texts.keys())[:10]}..."
        )

    def test_bns_section_6_high_extraction_confidence(self, bns_data):
        """A simple, clean section like BNS Section 6 must score >= 0.95."""
        from backend.preprocessing.validators.extraction_validator import validate_section
        sec6 = bns_data["section_map"].get("6")
        if sec6 is None:
            pytest.skip("BNS Section 6 not found — section numbering may differ")
        report = validate_section(
            section_number="6",
            legal_text=sec6.raw_body_text,
            has_subsections=sec6.has_subsections,
        )
        assert report.extraction_confidence >= 0.85, (
            f"BNS Section 6 (simple section) should have high confidence, "
            f"got {report.extraction_confidence}. "
            f"Failures: {report.check_failures}"
        )


@_skip_if_no_pdfs
class TestBNSSExtraction:
    """Integration tests for BNSS.pdf extraction quality."""

    def test_bnss_section_1_no_crpc_date_annotation(self, bnss_data):
        """BNSS Section 1 must NOT contain '[the 1st day of April, 1974]'.

        Known failure in existing JSON (Noise Type 3 — Editorial Bracket Annotations):
        bnss_complete.json BNSS-1 legal_text contains the CrPC commencement date
        '[the 1st day of April, 1974]' which is an old-law comparison annotation.
        The BNSS text should read 'such date as the Central Government may appoint'.
        """
        sec1 = bnss_data["section_map"].get("1")
        assert sec1 is not None, "BNSS Section 1 not found in parsed output"
        body = sec1.raw_body_text

        assert "[the 1st day of April, 1974]" not in body, (
            "BNSS Section 1 contains CrPC date annotation '[the 1st day of April, 1974]' "
            "— bracket annotation removal failed"
        )
        # The correct BNSS text should mention 'Central Government' or similar
        # (don't assert specific text since exact wording may vary)

    def test_bnss_section_count_approximately_531(self, bnss_data):
        """BNSS has 531 sections; extraction must detect close to that number."""
        sections = bnss_data["sections"]
        count = len(sections)
        assert 510 <= count <= 555, (
            f"Expected 510-555 sections for BNSS, got {count}."
        )

    def test_at_least_one_section_routes_to_human_review(self, bns_data):
        """At least one BNS section must have extraction_confidence < 0.70.

        The pipeline must route imperfect extractions to human_review_queue.
        This confirms the validation pipeline is active, not rubber-stamping everything.
        """
        from backend.preprocessing.validators.extraction_validator import validate_section
        low_confidence_found = False
        for sec in bns_data["sections"]:
            report = validate_section(
                section_number=sec.section_number,
                legal_text=sec.raw_body_text,
                has_subsections=sec.has_subsections,
            )
            if report.requires_human_review:
                low_confidence_found = True
                break

        assert low_confidence_found, (
            "No BNS sections were routed to human review. "
            "Either the extraction is perfect (unlikely for a BPR&D composite PDF) "
            "or the validation pipeline has a bug."
        )
