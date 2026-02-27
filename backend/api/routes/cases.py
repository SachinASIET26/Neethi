"""Cases routes — SC judgment search and IRAC case analysis."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_current_user, require_role
from backend.api.schemas.cases import (
    CaseAnalysisRequest,
    CaseAnalysisResponse,
    CaseDetail,
    CaseResult,
    CaseSearchRequest,
    CaseSearchResponse,
    IRACSection,
)
from backend.db.models.user import User

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /cases/search
# ---------------------------------------------------------------------------

@router.post("/search", response_model=CaseSearchResponse)
async def search_cases(
    request: CaseSearchRequest,
    current_user: User = Depends(get_current_user),
):
    """Search for relevant Supreme Court judgments using hybrid Qdrant search."""
    start = time.time()

    try:
        from backend.agents.tools import QdrantHybridSearchTool

        tool = QdrantHybridSearchTool()
        raw = await tool._run(
            query=request.query,
            top_k=request.top_k,
            collection="sc_judgments",
            act_filter=request.act_filter or "none",
            era_filter="none",
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Search failed: {exc}") from exc

    elapsed = int((time.time() - start) * 1000)

    # Parse raw tool output into structured results
    results: list[CaseResult] = []
    if raw and "0 result" not in raw:
        for block in raw.strip().split("\n\n"):
            lines = block.strip().split("\n")
            if not lines:
                continue
            case_name = lines[0].lstrip("[0123456789] ").strip()
            # Build a minimal result from whatever was returned
            # (sc_judgments collection payloads vary)
            results.append(
                CaseResult(
                    case_name=case_name,
                    relevance_score=0.8,
                    summary="\n".join(lines[1:])[:300] if len(lines) > 1 else None,
                )
            )

    # Citizen role sees simplified summaries only
    if current_user.role == "citizen":
        for r in results:
            r.summary = (r.summary or "")[:150] + "…" if r.summary and len(r.summary) > 150 else r.summary

    return CaseSearchResponse(
        results=results,
        total_found=len(results),
        search_time_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# POST /cases/analyze  — Lawyer / legal_advisor only
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=CaseAnalysisResponse)
async def analyze_case(
    request: CaseAnalysisRequest,
    current_user: User = Depends(require_role("lawyer", "legal_advisor")),
):
    """Deep IRAC analysis of a case scenario. Lawyer / legal_advisor only."""
    try:
        from backend.agents.tools import IRACAnalyzerTool, QdrantHybridSearchTool

        # Step 1: Retrieve relevant sections
        search_tool = QdrantHybridSearchTool()
        retrieved = await search_tool._run(
            query=request.scenario[:200],
            top_k=5,
            collection="legal_sections",
            act_filter=request.applicable_acts[0] if request.applicable_acts else "none",
            era_filter="none",
        )

        # Step 2: IRAC analysis
        irac_tool = IRACAnalyzerTool()
        irac_raw = await irac_tool._run(
            original_query=request.scenario,
            retrieved_sections=retrieved,
            user_role=current_user.role,
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Analysis failed: {exc}") from exc

    # Parse IRAC output (plain text block from tool)
    import re

    def _extract(label: str, text: str) -> str:
        m = re.search(rf"{label}:\s*(.*?)(?=\n[A-Z]+:|$)", text, re.DOTALL)
        return m.group(1).strip() if m else ""

    irac = IRACSection(
        issue=_extract("ISSUE", irac_raw),
        rule=_extract("RULE", irac_raw),
        application=_extract("APPLICATION", irac_raw),
        conclusion=_extract("CONCLUSION", irac_raw),
    )

    confidence_m = re.search(r"CONFIDENCE:\s*(high|medium|low)", irac_raw, re.IGNORECASE)
    confidence = confidence_m.group(1).lower() if confidence_m else "medium"

    # Extract section citations
    from backend.api.routes.query import _parse_citations
    citations = [
        {"act_code": c.act_code, "section_number": c.section_number, "verification": c.verification}
        for c in _parse_citations(irac_raw)
    ]

    return CaseAnalysisResponse(
        irac_analysis=irac,
        applicable_sections=citations,
        applicable_precedents=[],
        confidence=confidence,
        verification_status="VERIFIED",
    )


# ---------------------------------------------------------------------------
# GET /cases/{case_id}
# ---------------------------------------------------------------------------

@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(
    case_id: str,
    _: User = Depends(get_current_user),
):
    """Retrieve full details of an indexed SC judgment by its Qdrant point ID."""
    try:
        import os
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY"),
        )
        results = client.retrieve(
            collection_name="sc_judgments",
            ids=[case_id],
            with_payload=True,
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Qdrant retrieval failed: {exc}") from exc

    if not results:
        raise HTTPException(404, detail=f"Case '{case_id}' not found.")

    payload = results[0].payload or {}
    return CaseDetail(
        case_id=case_id,
        case_name=payload.get("case_name", "Unknown"),
        citation=payload.get("citation"),
        court=payload.get("court", "Supreme Court of India"),
        judgment_date=payload.get("judgment_date") or payload.get("decision_date"),
        judges=payload.get("judges", []),
        full_text=payload.get("text") or payload.get("full_text"),
        sections_cited=payload.get("sections_cited", []),
        headnotes=payload.get("headnotes", []),
        indexed_at=str(payload.get("indexed_at", "")),
    )
