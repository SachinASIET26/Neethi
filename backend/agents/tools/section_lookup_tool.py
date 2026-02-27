"""SectionLookupTool — exact statutory section retrieval via Qdrant payload filter.

Use this tool when the user asks directly about a specific section number:
    "What does BNS section 103 say?"
    "Text of BNSS section 482"
    "Define section 73 of ICA"

Unlike QdrantHybridSearchTool (which runs full embedding + RRF), this tool
performs a direct Qdrant payload filter:
    act_code = <act_code> AND section_number = <section_number>

Result: 100% precision for section-number queries, no embedding overhead, ~50ms latency.

IMPORTANT: This tool is for exact section number lookups only.
For conceptual queries ("explain tenancy rights") use QdrantHybridSearchTool.
For cross-act section chaining, use CrossReferenceExpansionTool after this tool.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy Qdrant client singleton
# ---------------------------------------------------------------------------

_qdrant_client = None


def _get_qdrant() -> Optional[object]:
    """Return a sync QdrantClient singleton."""
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY") or None
        _qdrant_client = QdrantClient(url=url, api_key=api_key)
        logger.info("section_lookup_tool: QdrantClient initialized at %s", url)
        return _qdrant_client
    except Exception as exc:
        logger.error("section_lookup_tool: QdrantClient init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Act code normalisation map
# ---------------------------------------------------------------------------

# Accept common agent shorthand and normalize to canonical act codes in Qdrant
_ACT_CODE_ALIASES: dict[str, str] = {
    # New sanhitas
    "BNS": "BNS_2023",
    "BNSS": "BNSS_2023",
    "BSA": "BSA_2023",
    # Civil statutes
    "ICA": "ICA_1872",
    "TPA": "TPA_1882",
    "CPC": "CPC_1908",
    "HMA": "HMA_1955",
    "HSA": "HSA_1956",
    "SRA": "SRA_1963",
    "LA": "LA_1963",
    "ACA": "ACA_1996",
    # Old criminal (repealed — text may not be indexed)
    "IPC": "IPC_1860",
    "CRPC": "CrPC_1973",
    "IEA": "IEA_1872",
}

# Known collections that hold statutory sections
_STATUTORY_COLLECTIONS = ["legal_sections", "legal_sub_sections"]


def _normalise_act_code(act_code: str) -> str:
    """Normalise agent-provided act code to canonical form stored in Qdrant."""
    s = act_code.strip().upper().replace(" ", "_")
    return _ACT_CODE_ALIASES.get(s, act_code.strip())


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class SectionLookupInput(BaseModel):
    """Input for SectionLookupTool."""

    act_code: str = Field(
        ...,
        description=(
            "The act code. Accepted: 'BNS_2023', 'BNSS_2023', 'BSA_2023', "
            "'ICA_1872', 'TPA_1882', 'HMA_1955', 'HSA_1956', 'SRA_1963', "
            "'LA_1963', 'ACA_1996', 'IPC_1860', 'CrPC_1973', 'IEA_1872'. "
            "Short forms also accepted: 'BNS', 'BNSS', 'ICA', 'TPA', etc."
        ),
    )
    section_number: str = Field(
        ...,
        description=(
            "Section number as a string. Examples: '103', '482', '73', '2'. "
            "Do NOT include 's.' prefix — just the number (and sub-section if needed: '2(a)')."
        ),
    )
    include_sub_sections: bool = Field(
        False,
        description=(
            "If True, also search legal_sub_sections collection for granular clauses "
            "of this section. Useful for complex sections with many sub-clauses."
        ),
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class SectionLookupTool(BaseTool):
    """Retrieve a specific Indian law section by exact act code + section number.

    Executes a Qdrant payload filter — no embedding, no RRF. Returns the full
    section text with all metadata. Use for direct section number lookups only.

    Two collections searched:
        legal_sections     — primary statutory text (always searched)
        legal_sub_sections — granular sub-clauses (when include_sub_sections=True)

    Usage::

        tool = SectionLookupTool()
        result = tool.run({
            "act_code": "BNS_2023",
            "section_number": "103",
        })
        # Returns full text of BNS section 103 (Murder)
    """

    name: str = "SectionLookupTool"
    description: str = (
        "Retrieve a specific Indian law section by exact act code and section number. "
        "Use ONLY for direct section number queries: 'what does BNS 103 say', 'text of BNSS 482'. "
        "Input: {act_code: str, section_number: str, include_sub_sections: bool}. "
        "Output: full section text with metadata (title, era, is_offence, punishment). "
        "For conceptual queries use QdrantHybridSearchTool instead. "
        "For cross-referenced sections, use CrossReferenceExpansionTool after this tool."
    )
    args_schema: type[BaseModel] = SectionLookupInput

    def _run(  # type: ignore[override]
        self,
        act_code: str | dict,
        section_number: str = "",
        include_sub_sections: bool = False,
    ) -> str:
        """Execute exact payload filter lookup on Qdrant.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        Uses sync QdrantClient.scroll() with a payload filter.
        """
        # Handle dict input
        if isinstance(act_code, dict):
            section_number = act_code.get("section_number", "")
            include_sub_sections = bool(act_code.get("include_sub_sections", False))
            act_code = act_code.get("act_code", "")

        act_code = _normalise_act_code(act_code)
        section_number = section_number.strip()

        if not act_code or not section_number:
            return "LOOKUP ERROR: Both act_code and section_number are required."

        logger.info(
            "section_lookup: act=%s section=%s sub_sections=%s",
            act_code, section_number, include_sub_sections,
        )

        client = _get_qdrant()
        if client is None:
            return "LOOKUP UNAVAILABLE: Qdrant client could not be initialised."

        collections_to_search = ["legal_sections"]
        if include_sub_sections:
            collections_to_search.append("legal_sub_sections")

        all_points: list = []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            for col in collections_to_search:
                scroll_filter = Filter(
                    must=[
                        FieldCondition(key="act_code", match=MatchValue(value=act_code)),
                        FieldCondition(key="section_number", match=MatchValue(value=section_number)),
                    ]
                )
                results, _ = client.scroll(
                    collection_name=col,
                    scroll_filter=scroll_filter,
                    limit=10,  # Should be 1–3 in practice; 10 handles duplicate ingestions
                    with_payload=True,
                    with_vectors=False,
                )
                for point in results:
                    all_points.append((col, point))

        except Exception as exc:
            logger.exception("section_lookup: Qdrant query failed: %s", exc)
            return f"LOOKUP ERROR: Qdrant query failed — {exc}"

        if not all_points:
            return (
                f"SECTION NOT FOUND: {act_code} s.{section_number} is not indexed in Qdrant.\n"
                f"Possible reasons:\n"
                f"  1. The act is not yet ingested (check docs/indian_legal_data_sources.md).\n"
                f"  2. The section number format differs — try without sub-section: "
                f"e.g. '2' instead of '2(a)'.\n"
                f"  3. Act code mismatch — verify: BNS_2023, BNSS_2023, BSA_2023, "
                f"ICA_1872, TPA_1882, HMA_1955, SRA_1963, LA_1963, ACA_1996.\n"
                "Tip: Use QdrantHybridSearchTool with broader query for related sections."
            )

        # Format results
        lines = [
            f"SECTION LOOKUP: {act_code} s.{section_number}",
            f"Found {len(all_points)} result(s)\n",
        ]

        seen_texts: set[str] = set()
        for col, point in all_points:
            payload = point.payload or {}
            text = (payload.get("text") or "").strip()

            # Deduplicate by text content (sections sometimes indexed twice)
            text_key = text[:200]
            if text_key in seen_texts and text_key:
                continue
            seen_texts.add(text_key)

            act = payload.get("act_code", act_code)
            sec = payload.get("section_number", section_number)
            title = payload.get("section_title", "")
            era = payload.get("era", "")
            chapter = payload.get("chapter_title", "") or payload.get("chapter", "")
            is_offence = payload.get("is_offence")
            is_bailable = payload.get("is_bailable")
            triable_by = payload.get("triable_by", "")
            punishment = payload.get("punishment", "")
            confidence = payload.get("extraction_confidence")

            header = f"--- {act} s.{sec}"
            if title:
                header += f": {title}"
            header += f" [{col}] ---"
            lines.append(header)

            if chapter:
                lines.append(f"Chapter: {chapter}")
            if era:
                lines.append(f"Era: {era}")

            # Offence metadata
            meta_parts = []
            if is_offence is not None:
                meta_parts.append(f"Offence: {is_offence}")
            if is_bailable is not None:
                meta_parts.append(f"Bailable: {is_bailable}")
            if triable_by:
                meta_parts.append(f"Triable by: {triable_by}")
            if confidence is not None:
                meta_parts.append(f"Extraction confidence: {float(confidence):.2f}")
            if meta_parts:
                lines.append(" | ".join(meta_parts))

            lines.append("")

            # Full section text
            if text:
                lines.append(text)
            else:
                lines.append("(No text available in payload)")

            # Punishment info if separate field
            if punishment and punishment not in text:
                lines.append(f"\nPunishment: {punishment}")

            lines.append("")

        return "\n".join(lines)
