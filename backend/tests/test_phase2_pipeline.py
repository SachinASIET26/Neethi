"""Phase 2 unit tests: JSON enricher, offence classifier, transition type logic.

These tests cover:
- json_enricher: Roman numeral normalisation, notes dedup, type mapping
- offence_classifier: is_offence detection, punishment extraction, Schedule I lookup
- pipeline: split detection logic, section number parsing, sub-section type mapping

Tests do NOT require a database connection — they test the pre-DB logic only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# json_enricher tests
# ---------------------------------------------------------------------------

class TestJsonEnricher:
    """Tests for backend.preprocessing.enrichers.json_enricher."""

    def test_bns_enrichment_loads_358_sections(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        assert len(m) == 358, f"Expected 358 BNS sections, got {len(m)}"

    def test_bnss_enrichment_loads_531_sections(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bnss_complete.json"), "BNSS_2023")
        assert len(m) == 531, f"Expected 531 BNSS sections, got {len(m)}"

    def test_bsa_enrichment_loads_170_sections(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bsa_complete.json"), "BSA_2023")
        assert len(m) == 170, f"Expected 170 BSA sections, got {len(m)}"

    def test_bns_chapter_number_is_roman(self):
        """BNS uses Roman numerals already — must remain Roman."""
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        s1 = m["1"]
        assert s1.chapter_number == "I", f"Expected 'I', got {s1.chapter_number!r}"

    def test_bnss_chapter_number_converted_to_roman(self):
        """BNSS uses Arabic chapter numbers — must be converted to Roman."""
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bnss_complete.json"), "BNSS_2023")
        s1 = m["1"]
        assert s1.chapter_number == "I", (
            f"BNSS chapter_number should be Roman 'I', got {s1.chapter_number!r}"
        )

    def test_bsa_chapter_number_converted_to_roman(self):
        """BSA uses Arabic chapter numbers — must be converted to Roman."""
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bsa_complete.json"), "BSA_2023")
        s1 = m["1"]
        assert s1.chapter_number == "I", (
            f"BSA chapter_number should be Roman 'I', got {s1.chapter_number!r}"
        )

    def test_notes_deduped_when_identical_to_change_summary(self):
        """notes field is None when it equals change_summary (deduplication rule)."""
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        # At least 46 BNS sections have notes == change_summary (known from analysis)
        deduped_count = sum(1 for v in m.values() if v.notes is None)
        assert deduped_count >= 46, (
            f"Expected >=46 notes deduped, got {deduped_count}"
        )

    def test_type_same_maps_to_equivalent(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        # BNS Section 1 has type='same' in JSON
        assert m["1"].transition_type_hint == "equivalent"

    def test_type_modified_preserved(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        # Find a 'modified' section
        modified_sections = [k for k, v in m.items() if v.transition_type_hint == "modified"]
        assert len(modified_sections) > 0, "Expected some 'modified' sections in BNS"

    def test_old_act_code_is_ipc_for_bns(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        # All BNS sections should reference IPC_1860
        ipc_sections = [k for k, v in m.items() if v.old_act_code == "IPC_1860"]
        assert len(ipc_sections) > 300, f"Expected >300 IPC references, got {len(ipc_sections)}"

    def test_legal_text_not_in_enrichment(self):
        """Verify that SectionEnrichment has no legal_text attribute."""
        from backend.preprocessing.enrichers.json_enricher import SectionEnrichment
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(SectionEnrichment)}
        assert "legal_text" not in field_names, "SectionEnrichment must NOT have a legal_text field"

    def test_rag_keywords_not_in_enrichment(self):
        """Verify that SectionEnrichment has no rag_keywords attribute."""
        from backend.preprocessing.enrichers.json_enricher import SectionEnrichment
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(SectionEnrichment)}
        assert "rag_keywords" not in field_names, "SectionEnrichment must NOT have a rag_keywords field"

    def test_unknown_act_code_raises_key_error(self):
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        with pytest.raises(KeyError):
            load_enrichment(Path("bns_complete.json"), "UNKNOWN_ACT")

    def test_build_catalog_returns_all_three_acts(self):
        from backend.preprocessing.enrichers.json_enricher import build_catalog
        catalog = build_catalog(
            bns_path=Path("bns_complete.json"),
            bnss_path=Path("bnss_complete.json"),
            bsa_path=Path("bsa_complete.json"),
        )
        assert "BNS_2023" in catalog
        assert "BNSS_2023" in catalog
        assert "BSA_2023" in catalog
        assert len(catalog["BNS_2023"]) == 358
        assert len(catalog["BNSS_2023"]) == 531
        assert len(catalog["BSA_2023"]) == 170

    # --- False-friend & data-quality regression tests ---

    def test_ipc_302_maps_only_to_bns_103_not_bns_95(self):
        """REGRESSION: BNS 95 must NOT reference IPC 302 (Murder false friend).

        BNS 95 = 'Hiring a Child to Commit an Offence'. Its replaces_ipc list
        in the raw JSON includes '302' as noise. The _BLOCKED_OLD_SECTIONS fix
        must remove it so IPC 302 maps exclusively to BNS 103.
        """
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")

        sections_referencing_ipc302 = [
            sec for sec, e in m.items() if "302" in e.replaces_old_sections
        ]
        assert "103" in sections_referencing_ipc302, (
            "BNS 103 must reference IPC 302 (Murder)"
        )
        assert "95" not in sections_referencing_ipc302, (
            "BNS 95 must NOT reference IPC 302 — JSON noise blocked by "
            "_BLOCKED_OLD_SECTIONS in json_enricher.py"
        )

    def test_ipc_124a_manually_seeded_in_bns_152(self):
        """REGRESSION: IPC 124A (Sedition) must be seeded into BNS 152's mapping.

        BNS 152 has replaces_ipc=[] in the raw JSON (type='new'), but the notes
        field explicitly states it replaces IPC 124A. The _MANUAL_OLD_SECTIONS
        fix must inject '124A' into BNS 152's replaces_old_sections.
        """
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")

        assert "152" in m, "BNS 152 must exist in enrichment map"
        assert "124A" in m["152"].replaces_old_sections, (
            "BNS 152 must contain '124A' in replaces_old_sections "
            "(manually seeded via _MANUAL_OLD_SECTIONS)"
        )

    def test_376_subsection_refs_normalised_to_plain_376(self):
        """REGRESSION: '376(1)' and '376(2)' must normalise to '376'.

        BNS 64 has replaces_ipc=['376(1)'] and BNS 65 has replaces_ipc=['376(2)'].
        After _normalize_old_section both become '376'. This ensures:
        - lookup_transition('IPC_1860', '376') returns rows (not zero)
        - split detection correctly identifies IPC 376 → [BNS 64, BNS 65]
        """
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")

        assert "64" in m, "BNS 64 must exist in enrichment map"
        assert "65" in m, "BNS 65 must exist in enrichment map"

        assert "376" in m["64"].replaces_old_sections, (
            "BNS 64: '376(1)' should be normalised to '376'"
        )
        assert "376" in m["65"].replaces_old_sections, (
            "BNS 65: '376(2)' should be normalised to '376'"
        )
        # Original parenthetical forms must not be present after normalisation
        assert "376(1)" not in m["64"].replaces_old_sections, (
            "BNS 64: raw '376(1)' must not remain after normalisation"
        )
        assert "376(2)" not in m["65"].replaces_old_sections, (
            "BNS 65: raw '376(2)' must not remain after normalisation"
        )
        # Deduplication: only one '376' entry per section (not ['376', '376'])
        assert m["64"].replaces_old_sections.count("376") == 1, (
            "BNS 64 should have exactly one '376' entry (no duplicates after dedup)"
        )
        assert m["65"].replaces_old_sections.count("376") == 1, (
            "BNS 65 should have exactly one '376' entry (no duplicates after dedup)"
        )


# ---------------------------------------------------------------------------
# offence_classifier tests
# ---------------------------------------------------------------------------

class TestOffenceClassifier:
    """Tests for backend.preprocessing.classifiers.offence_classifier."""

    def test_murder_section_is_offence(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = (
            "103. MURDER.\n"
            "Whoever commits murder shall be punished with death or with "
            "imprisonment for life, and shall also be liable to fine."
        )
        clf = classify_offence("103", text, "BNS_2023")
        assert clf.is_offence is True

    def test_murder_has_death_and_life_punishment(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = (
            "Whoever commits murder shall be punished with death or with "
            "imprisonment for life, and shall also be liable to fine."
        )
        clf = classify_offence("103", text, "BNS_2023")
        assert "death" in (clf.punishment_type or "")
        assert "life_imprisonment" in (clf.punishment_type or "")
        assert clf.punishment_max_years == 99999

    def test_life_imprisonment_sentinel_is_99999(self):
        from backend.preprocessing.classifiers.offence_classifier import LIFE_IMPRISONMENT
        assert LIFE_IMPRISONMENT == 99999

    def test_definition_section_is_not_offence(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = "1. SHORT TITLE, COMMENCEMENT AND APPLICATION.\nThis Act may be called the BNS."
        clf = classify_offence("1", text, "BNS_2023")
        assert clf.is_offence is False

    def test_fixed_term_imprisonment_extracted(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = "Whoever does X shall be punished with imprisonment for 7 years and fine."
        clf = classify_offence("200", text, "BNS_2023")
        assert clf.is_offence is True
        assert clf.punishment_max_years == 7.0

    def test_fine_extracted_from_rupees(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = "Whoever does X shall be punished with imprisonment for 3 years and fine which may extend to rupees 50000."
        clf = classify_offence("200", text, "BNS_2023")
        assert clf.punishment_fine_max == 50000

    def test_schedule_i_lookup_for_murder(self):
        """Murder (BNS 103) should be cognizable and non-bailable from Schedule I."""
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = "Whoever commits murder shall be punished with death or with imprisonment for life."
        clf = classify_offence("103", text, "BNS_2023")
        assert clf.is_cognizable is True
        assert clf.is_bailable is False
        assert clf.triable_by == "Court of Sessions"

    def test_empty_text_returns_not_offence(self):
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        clf = classify_offence("99", "", "BNS_2023")
        assert clf.is_offence is False

    def test_punishment_type_comma_separated(self):
        """punishment_type uses comma-separated vocabulary."""
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = (
            "shall be punished with death or with imprisonment for life "
            "and shall also be liable to fine which may extend to rupees 100000."
        )
        clf = classify_offence("103", text, "BNS_2023")
        types = set((clf.punishment_type or "").split(","))
        assert "death" in types
        assert "life_imprisonment" in types
        assert "fine" in types

    def test_section_not_in_schedule_i_returns_none_for_procedural_fields(self):
        """A section not in Schedule I leaves is_cognizable/bailable/triable_by as None."""
        from backend.preprocessing.classifiers.offence_classifier import classify_offence
        text = "Whoever does XYZ shall be punished with imprisonment for 2 years."
        # Use a section number not in the seed file
        clf = classify_offence("999", text, "BNS_2023")
        assert clf.is_offence is True  # Has punishment text
        assert clf.is_cognizable is None
        assert clf.is_bailable is None
        assert clf.triable_by is None


# ---------------------------------------------------------------------------
# pipeline utility tests (no DB required)
# ---------------------------------------------------------------------------

class TestPipelineUtils:
    """Tests for utility functions in backend.preprocessing.pipeline."""

    def test_split_detection_marks_both_new_sections_as_split_into(self):
        from backend.preprocessing.pipeline import _compute_transition_types
        from backend.preprocessing.enrichers.json_enricher import SectionEnrichment

        # IPC 38 → BNS 2 AND BNS 3 (split case)
        enrichment_map = {
            "2": SectionEnrichment("I", "Ch1", "d", ["38"], "IPC_1860", "", "equivalent"),
            "3": SectionEnrichment("I", "Ch1", "d", ["38"], "IPC_1860", "", "equivalent"),
        }
        overrides = _compute_transition_types(enrichment_map)
        assert overrides.get("38", {}).get("2") == "split_into"
        assert overrides.get("38", {}).get("3") == "split_into"

    def test_single_mapping_not_marked_as_split(self):
        from backend.preprocessing.pipeline import _compute_transition_types
        from backend.preprocessing.enrichers.json_enricher import SectionEnrichment

        # IPC 302 → BNS 103 only (no split)
        enrichment_map = {
            "103": SectionEnrichment("VI", "Ch6", "d", ["302"], "IPC_1860", "", "equivalent"),
        }
        overrides = _compute_transition_types(enrichment_map)
        assert overrides.get("302", {}).get("103") == "equivalent"

    def test_parse_section_number_numeric(self):
        from backend.preprocessing.pipeline import _parse_section_number
        int_part, suffix = _parse_section_number("103")
        assert int_part == 103
        assert suffix is None

    def test_parse_section_number_alphanumeric(self):
        from backend.preprocessing.pipeline import _parse_section_number
        int_part, suffix = _parse_section_number("53A")
        assert int_part == 53
        assert suffix == "A"

    def test_parse_section_number_non_numeric_returns_none(self):
        from backend.preprocessing.pipeline import _parse_section_number
        int_part, suffix = _parse_section_number("abc")
        assert int_part is None

    def test_label_to_type_numbered(self):
        from backend.preprocessing.pipeline import _label_to_type
        assert _label_to_type("(1)") == "numbered"
        assert _label_to_type("(2)") == "numbered"

    def test_label_to_type_lettered(self):
        from backend.preprocessing.pipeline import _label_to_type
        assert _label_to_type("(a)") == "lettered"
        assert _label_to_type("(z)") == "lettered"

    def test_label_to_type_structural(self):
        from backend.preprocessing.pipeline import _label_to_type
        assert _label_to_type("Explanation") == "explanation"
        assert _label_to_type("Proviso") == "proviso"
        assert _label_to_type("Illustration_A") == "illustration"

    def test_ipc_murder_to_bns_mapping_correct_act_code(self):
        """Verify that BNS_2023 enrichment references IPC_1860, not BNS_2023."""
        from backend.preprocessing.enrichers.json_enricher import load_enrichment
        m = load_enrichment(Path("bns_complete.json"), "BNS_2023")
        # Every section that replaces something should reference IPC_1860
        for sec_num, enrichment in m.items():
            if enrichment.replaces_old_sections:
                assert enrichment.old_act_code == "IPC_1860", (
                    f"BNS section {sec_num} should reference IPC_1860, "
                    f"got {enrichment.old_act_code!r}"
                )
