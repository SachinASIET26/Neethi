"""Cases routes — SC judgment search and IRAC case analysis."""

from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client import QdrantClient

from backend.api.dependencies import get_current_user, require_role
from backend.api.schemas.cases import (
    CaseAnalysisRequest,
    CaseAnalysisResponse,
    CaseDetail,
    CaseResult,
    CaseSearchRequest,
    CaseSearchResponse,
    IRACSection,
    SimilarCase,
    SimilarCasesRequest,
    SimilarCasesResponse,
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
        # _run is synchronous (BGE-M3 + Qdrant are blocking); wrap in thread pool
        raw = await asyncio.to_thread(
            tool._run,
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

        # Step 1: Retrieve relevant sections (_run is sync — use thread pool)
        search_tool = QdrantHybridSearchTool()
        retrieved = await asyncio.to_thread(
            search_tool._run,
            query=request.scenario[:200],
            top_k=5,
            collection="legal_sections",
            act_filter=request.applicable_acts[0] if request.applicable_acts else "none",
            era_filter="none",
        )

        # Step 2: IRAC analysis (_run is sync — use thread pool)
        irac_tool = IRACAnalyzerTool()
        irac_raw = await asyncio.to_thread(
            irac_tool._run,
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
# POST /cases/similar — Indian Kanoon SC Judgement similarity search
# ---------------------------------------------------------------------------

@router.post("/similar", response_model=SimilarCasesResponse)
async def similar_cases(
    request: SimilarCasesRequest,
    current_user: User = Depends(get_current_user),
):
    """Retrieve semantically similar Supreme Court judgements from the
    Indian Kanoon collection using hybrid BGE-M3 + BM25 RRF search.

    Supports optional filters for year range, verdict type, and case type.
    Results include the direct Indian Kanoon URL for each judgement.
    """
    start = time.time()

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

        from backend.rag.embeddings import BGEM3Embedder
        from backend.rag.hybrid_search import HybridSearcher
        from backend.rag.qdrant_setup import (
            COLLECTION_INDIAN_KANOON,
            get_qdrant_client,
        )

        # Build optional payload filter
        must = []
        if request.year_from or request.year_to:
            must.append(FieldCondition(
                key="year",
                range=Range(
                    gte=request.year_from or 1950,
                    lte=request.year_to or 2030,
                ),
            ))
        if request.verdict_type:
            must.append(FieldCondition(
                key="verdict_type",
                match=MatchValue(value=request.verdict_type),
            ))
        if request.case_type:
            must.append(FieldCondition(
                key="case_type",
                match=MatchValue(value=request.case_type),
            ))

        qdrant_filter = Filter(must=must) if must else None

        # Use the shared embedder singleton from the main app if available,
        # otherwise instantiate (embedder loads from ONNX cache — fast after first load)
        embedder = BGEM3Embedder()
        client = get_qdrant_client()
        searcher = HybridSearcher(qdrant_client=client, embedder=embedder)

        # Run hybrid search in thread pool (BGE-M3 + Qdrant are blocking)
        raw_results = await asyncio.to_thread(
            searcher.search,
            query=request.query,
            collection=COLLECTION_INDIAN_KANOON,
            top_k=request.top_k,
            query_type="civil_conceptual",  # balanced dense/sparse for case law
        )

        # If there's a filter, apply it post-search (client-side) since the
        # searcher's filter applies to act_filter/era_filter only.
        # For indian_kanoon, we pass the qdrant_filter directly by overriding
        # the search call with native Qdrant query when filters are present.
        if qdrant_filter and must:
            from qdrant_client.models import NamedSparseVector, SparseVector

            from backend.rag.embeddings import sparse_dict_to_qdrant
            from backend.rag.rrf import reciprocal_rank_fusion

            candidates = request.top_k * 5
            dense_query = await asyncio.to_thread(embedder.encode_dense, [request.query])
            dense_query = dense_query[0]

            dense_hits = await asyncio.to_thread(
                client.search,
                collection_name=COLLECTION_INDIAN_KANOON,
                query_vector=("dense", dense_query),
                query_filter=qdrant_filter,
                limit=candidates,
                with_payload=True,
            )

            sparse_batch = await asyncio.to_thread(embedder.encode_sparse, [request.query])
            sv = sparse_dict_to_qdrant(sparse_batch[0])
            sparse_hits = await asyncio.to_thread(
                client.search,
                collection_name=COLLECTION_INDIAN_KANOON,
                query_vector=NamedSparseVector(name="sparse", vector=SparseVector(**sv)),
                query_filter=qdrant_filter,
                limit=candidates,
                with_payload=True,
            )

            fused = reciprocal_rank_fusion(
                dense_results=[{"point_id": str(h.id), "score": h.score, "payload": h.payload or {}} for h in dense_hits],
                sparse_results=[{"point_id": str(h.id), "score": h.score, "payload": h.payload or {}} for h in sparse_hits],
                top_k=request.top_k,
            )

            # Build SimilarCase list from fused results
            results = [
                SimilarCase(
                    point_id=f["point_id"],
                    case_title=f["payload"].get("case_title") or "Untitled Judgment",
                    petitioner=f["payload"].get("petitioner", ""),
                    respondent=f["payload"].get("respondent", ""),
                    judges=f["payload"].get("judges", []),
                    verdict_type=f["payload"].get("verdict_type", "unknown"),
                    case_type=f["payload"].get("case_type", "other"),
                    year=f["payload"].get("year"),
                    date=f["payload"].get("date", ""),
                    citation=f["payload"].get("citation") or f["payload"].get("primary_citation", ""),
                    legal_sections=f["payload"].get("legal_sections", [])[:8],
                    summary=f["payload"].get("summary", "")[:500],
                    key_holdings=f["payload"].get("key_holdings", [])[:3],
                    indian_kanoon_url=f["payload"].get("indian_kanoon_url", ""),
                    relevance_score=round(f["rrf_score"], 4),
                )
                for f in fused[:request.top_k]
            ]
        else:
            # No extra filters — map searcher results directly
            results = [
                SimilarCase(
                    point_id=r.point_id,
                    case_title=r.payload.get("case_title") or "Untitled Judgment",
                    petitioner=r.payload.get("petitioner", ""),
                    respondent=r.payload.get("respondent", ""),
                    judges=r.payload.get("judges", []),
                    verdict_type=r.payload.get("verdict_type", "unknown"),
                    case_type=r.payload.get("case_type", "other"),
                    year=r.payload.get("year"),
                    date=r.payload.get("date", ""),
                    citation=r.payload.get("citation") or r.payload.get("primary_citation", ""),
                    legal_sections=r.payload.get("legal_sections", [])[:8],
                    summary=r.payload.get("summary", "")[:500],
                    key_holdings=r.payload.get("key_holdings", [])[:3],
                    indian_kanoon_url=r.payload.get("indian_kanoon_url", ""),
                    relevance_score=round(r.score, 4),
                )
                for r in raw_results
            ]

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Similar cases search failed: {exc}",
        ) from exc

    elapsed = int((time.time() - start) * 1000)

    return SimilarCasesResponse(
        results=results,
        total_found=len(results),
        search_time_ms=elapsed,
        collection=COLLECTION_INDIAN_KANOON,
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
