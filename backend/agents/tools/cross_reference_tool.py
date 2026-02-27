"""CrossReferenceExpansionTool — expand retrieved sections with their statutory cross-references.

Use in the lawyer and legal_advisor crews AFTER QdrantHybridSearchTool.
Do NOT use in layman or police crews — adds complexity without benefit for those roles.

Problem this solves:
    BNS s.103 (Murder) says "except in cases covered under Section 105".
    Without this tool, the LegalReasoner reasons about murder without seeing s.105
    (Culpable Homicide Not Amounting to Murder) — missing a critical legal distinction.

How it works:
    1. Accepts a JSON list of (act_code, section_number) pairs already retrieved.
    2. Queries the PostgreSQL cross_references table for:
           exception_reference — "except as in s.X" (defences, carve-outs)
           subject_to          — "subject to provisions of s.X" (conditional rules)
           definition_import   — "as defined in s.X" (imported legal definitions)
           punishment_table    — "punishment as per s.X" (sentencing context)
    3. Fetches the full text of each referenced section from the sections table.
    4. Returns expanded context with both retrieved AND referenced sections.

Reference types NOT followed (would add too much noise):
    cross_act_reference — often pulls in entire acts
    procedure_link      — procedural only, irrelevant for substantive queries
    general_reference   — too broad
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Reference types that represent legally critical dependencies
_FOLLOWED_REFERENCE_TYPES = (
    "exception_reference",
    "subject_to",
    "definition_import",
    "punishment_table",
)

# Maximum cross-referenced sections to add (avoid context bloat)
_MAX_EXPANDED_SECTIONS = 6


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class CrossReferenceInput(BaseModel):
    """Input for CrossReferenceExpansionTool."""

    sections_json: str = Field(
        ...,
        description=(
            'JSON list of retrieved sections to expand. '
            'Format: [{"act_code": "BNS_2023", "section_number": "103"}, ...]. '
            'Pass the act_code and section_number from QdrantHybridSearchTool results. '
            'Maximum 10 sections per call.'
        ),
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class CrossReferenceExpansionTool(BaseTool):
    """Expand retrieved statutory sections with their legally critical cross-references.

    For LAWYER and LEGAL_ADVISOR crews only. Queries the cross_references
    PostgreSQL table to find exception_reference, subject_to, definition_import,
    and punishment_table links from the initially retrieved sections, then fetches
    the full text of each referenced section.

    This ensures the LegalReasoner has a COMPLETE statutory picture for IRAC
    analysis, not just the most-similar retrieved sections.

    Usage::

        tool = CrossReferenceExpansionTool()
        result = tool.run({
            "sections_json": '[{"act_code": "BNS_2023", "section_number": "103"}]'
        })
        # Returns BNS s.103 expanded with s.105 (culpable homicide exception)
    """

    name: str = "CrossReferenceExpansionTool"
    description: str = (
        "Expand retrieved sections with their legally critical cross-references from PostgreSQL. "
        "Use AFTER QdrantHybridSearchTool in lawyer/legal_advisor crews. "
        "Input: {sections_json: str} — JSON list of {act_code, section_number} dicts. "
        "Output: referenced sections (exception_reference, subject_to, definition_import, "
        "punishment_table) with full statutory text. "
        "Example: BNS 103 → expands to include BNS 105 (culpable homicide exception). "
        "Do NOT use for layman or police crew — use QdrantHybridSearchTool directly."
    )
    args_schema: type[BaseModel] = CrossReferenceInput

    def _run(  # type: ignore[override]
        self,
        sections_json: str | dict,
    ) -> str:
        """Expand sections with cross-references from PostgreSQL.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        Uses sync SQLAlchemy (psycopg2) to query cross_references and sections tables.
        """
        # Handle dict input
        if isinstance(sections_json, dict):
            sections_json = sections_json.get("sections_json", "[]")

        # Parse input
        try:
            sections = json.loads(sections_json)
            if not isinstance(sections, list):
                return "CROSS_REF ERROR: sections_json must be a JSON array."
            sections = sections[:10]  # Safety cap
        except (json.JSONDecodeError, TypeError) as e:
            return f"CROSS_REF ERROR: Invalid JSON — {e}. Expected: [{{'act_code': 'BNS_2023', 'section_number': '103'}}]"

        if not sections:
            return "CROSS_REF: No sections provided — nothing to expand."

        logger.info(
            "cross_reference: expanding %d sections: %s",
            len(sections),
            [(s.get("act_code"), s.get("section_number")) for s in sections[:5]],
        )

        # Database connection
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.orm import sessionmaker

            async_url = os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
            )
            sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
            engine = create_engine(sync_url, echo=False, pool_size=2, pool_pre_ping=True)
            Session = sessionmaker(bind=engine)
        except Exception as exc:
            logger.error("cross_reference: DB connection failed: %s", exc)
            return f"CROSS_REF UNAVAILABLE: Database connection failed — {exc}"

        expanded: list[dict] = []
        seen_refs: set[tuple[str, str]] = set()

        # Pre-populate seen_refs with the source sections (don't re-fetch them)
        for sec in sections:
            act = sec.get("act_code", "").strip()
            num = sec.get("section_number", "").strip()
            if act and num:
                seen_refs.add((act, num))

        try:
            with Session() as session:
                for sec in sections:
                    source_act = sec.get("act_code", "").strip()
                    source_section = sec.get("section_number", "").strip()
                    if not source_act or not source_section:
                        continue

                    # ── Step 1: Find cross-references ─────────────────────────
                    ref_rows = session.execute(text("""
                        SELECT target_act, target_section, reference_type, reference_text
                        FROM cross_references
                        WHERE source_act = :act
                          AND source_section = :section
                          AND reference_type = ANY(:ref_types)
                        ORDER BY reference_type
                        LIMIT 10
                    """), {
                        "act": source_act,
                        "section": source_section,
                        "ref_types": list(_FOLLOWED_REFERENCE_TYPES),
                    }).fetchall()

                    for ref in ref_rows:
                        target_key = (ref.target_act, ref.target_section)
                        if target_key in seen_refs:
                            continue
                        if len(expanded) >= _MAX_EXPANDED_SECTIONS:
                            break
                        seen_refs.add(target_key)

                        # ── Step 2: Fetch referenced section text ─────────────
                        section_row = session.execute(text("""
                            SELECT act_code, section_number, section_title,
                                   legal_text, chapter_title, extraction_confidence
                            FROM sections
                            WHERE act_code = :act AND section_number = :section
                            LIMIT 1
                        """), {
                            "act": ref.target_act,
                            "section": ref.target_section,
                        }).fetchone()

                        if section_row:
                            expanded.append({
                                "source_act": source_act,
                                "source_section": source_section,
                                "reference_type": ref.reference_type,
                                "reference_text": ref.reference_text or "",
                                "target_act": section_row.act_code,
                                "target_section": section_row.section_number,
                                "target_title": section_row.section_title or "",
                                "target_text": section_row.legal_text or "",
                                "chapter_title": section_row.chapter_title or "",
                                "confidence": float(section_row.extraction_confidence or 1.0),
                            })
                        else:
                            # Referenced section exists in cross_references but not in sections
                            # (possible if the target act is not yet ingested)
                            expanded.append({
                                "source_act": source_act,
                                "source_section": source_section,
                                "reference_type": ref.reference_type,
                                "reference_text": ref.reference_text or "",
                                "target_act": ref.target_act,
                                "target_section": ref.target_section,
                                "target_title": "",
                                "target_text": "(Section text not indexed — act may not be ingested yet)",
                                "chapter_title": "",
                                "confidence": 0.0,
                            })

                    if len(expanded) >= _MAX_EXPANDED_SECTIONS:
                        break

        except Exception as exc:
            logger.exception("cross_reference: DB query failed: %s", exc)
            return f"CROSS_REF ERROR: Database query failed — {exc}"
        finally:
            engine.dispose()

        if not expanded:
            return (
                "CROSS_REFERENCE EXPANSION: No cross-references found for the provided sections.\n"
                "This is normal when:\n"
                "  - Sections are self-contained (no 'subject to', 'except', 'as defined' references)\n"
                "  - The cross_references table has not been populated for these acts yet\n"
                "Proceed with the originally retrieved sections for IRAC analysis."
            )

        # Format output
        lines = [
            f"CROSS-REFERENCE EXPANSION: {len(expanded)} additional section(s) found\n",
            "These sections are legally referenced by the initially retrieved sections.",
            "Include them in your IRAC analysis for complete statutory context.\n",
        ]

        for exp in expanded:
            ref_label = exp["reference_type"].replace("_", " ").upper()
            src_label = f"{exp['source_act']} s.{exp['source_section']}"
            tgt_label = f"{exp['target_act']} s.{exp['target_section']}"

            lines.append(f"=== [{ref_label}] {src_label} → {tgt_label} ===")

            if exp.get("reference_text"):
                lines.append(f"Reference context: \"{exp['reference_text']}\"")

            title = exp.get("target_title", "")
            if title:
                lines.append(f"Section title: {title}")

            chapter = exp.get("chapter_title", "")
            if chapter:
                lines.append(f"Chapter: {chapter}")

            confidence = exp.get("confidence", 1.0)
            if confidence < 0.7:
                lines.append(f"⚠ Extraction confidence: {confidence:.2f} — verify this section text")

            lines.append("")
            target_text = exp.get("target_text", "").strip()
            lines.append(target_text if target_text else "(No text available)")
            lines.append("")

        lines.append(
            "NOTE: Cross-referenced sections are supplemental context. "
            "Always cite the primary retrieved sections first in your legal analysis."
        )

        return "\n".join(lines)
