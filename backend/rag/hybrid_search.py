"""Hybrid dense + sparse retrieval with Reciprocal Rank Fusion.

The RetrievalSpecialist agent uses this module to query Qdrant.
IMPORTANT: The StatuteNormalizationTool MUST have already run before calling
search() — this module does not normalize statute references.

Search pipeline:
    1. Embed query (dense only — BGE-M3, no instruction prefix for queries)
    2. Build Qdrant filter from non-None filter parameters
    3. Prefetch dense results  (top_k * prefetch_multiplier candidates)
    4. Prefetch sparse results (top_k * prefetch_multiplier candidates)
    5. Apply Weighted Reciprocal Rank Fusion (weights from QUERY_TYPE_WEIGHTS)
    6. Apply client-side Score Boosting (era recency, extraction confidence,
       offence classification)
    7. Apply Maximal Marginal Relevance (MMR) diversity if mmr_diversity > 0
    8. Return top_k results as List[RetrievalResult]
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from backend.rag.embeddings import BGEM3Embedder, sparse_dict_to_qdrant
from backend.rag.reranker import RetrievalResult
from backend.rag.rrf import reciprocal_rank_fusion
from backend.rag.qdrant_setup import (
    COLLECTION_LEGAL_SECTIONS,
    COLLECTION_LEGAL_SUB_SECTIONS,
    COLLECTION_SC_JUDGMENTS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weighted RRF configuration
# ---------------------------------------------------------------------------

# (dense_weight, sparse_weight) per query type.
# dense  > sparse  → favour semantic / conceptual understanding
# sparse > dense   → favour keyword-exact matches (section lookups, old acts)
QUERY_TYPE_WEIGHTS: dict[str, tuple[float, float]] = {
    "section_lookup":   (1.0, 4.0),   # e.g. "BNS 103", "what does s.73 say"
    "criminal_offence": (2.0, 1.5),   # offence lookup, balanced with slight semantic lean
    "civil_conceptual": (3.0, 1.0),   # conceptual civil/property/family queries
    "procedural":       (2.0, 1.0),   # "how to file FIR", bail procedure
    "old_statute":      (1.0, 3.0),   # IPC/CrPC references after normalization
    "default":          (2.0, 1.0),   # fallback
}


# ---------------------------------------------------------------------------
# Score Boosting helpers (client-side, applied after RRF)
# ---------------------------------------------------------------------------

def _apply_score_boost(
    fused: list[dict],
    era_filter: str | None,
    query_type: str,
) -> list[dict]:
    """Apply metadata-driven score boosts to RRF results.

    Three boosts, applied in sequence:
      1. Era recency boost (+0.15): naveen_sanhitas sections outrank colonial_codes
         when the query targets current Indian law (era_filter == 'naveen_sanhitas').
      2. Extraction confidence weighting (×[0.85–1.0]): higher-confidence sections
         rank above OCR-uncertain sections when semantically equivalent.
      3. Offence classification boost (+0.10): for criminal offence queries,
         sections tagged is_offence=True rank above procedural/definitional sections.

    All boosts are small and additive — they cannot override large RRF score gaps,
    only break ties between closely-ranked candidates.

    Args:
        fused:       RRF result list (each item has 'rrf_score', 'payload').
        era_filter:  The era_filter passed to search() — drives era boost logic.
        query_type:  The query_type string from QueryClassifierTool output.

    Returns:
        The same list with 'boosted_score' added; sorted by boosted_score desc.
    """
    prefer_naveen = (era_filter == "naveen_sanhitas")
    is_criminal = (query_type == "criminal_offence")

    for item in fused:
        payload = item.get("payload", {})
        era = payload.get("era", "")
        # extraction_confidence may be null in older ingested sections; default 1.0
        confidence = float(payload.get("extraction_confidence") or 1.0)
        is_offence = bool(payload.get("is_offence", False))

        score = item["rrf_score"]

        # 1. Era recency boost
        if prefer_naveen and era == "naveen_sanhitas":
            score += 0.15

        # 2. Extraction confidence weighting: maps confidence [0, 1] → factor [0.7, 1.0]
        score *= (0.7 + confidence * 0.3)

        # 3. Offence precision boost
        if is_criminal and is_offence:
            score += 0.10

        item["boosted_score"] = score

    return sorted(fused, key=lambda x: x.get("boosted_score", x["rrf_score"]), reverse=True)


# ---------------------------------------------------------------------------
# MMR diversity helper (client-side greedy selection)
# ---------------------------------------------------------------------------

def _apply_mmr_diversity(
    candidates: list[dict],
    mmr_diversity: float,
    top_k: int,
) -> list[dict]:
    """Greedy Maximal Marginal Relevance selection using act_code proximity.

    Standard MMR:
        MMR = argmax[ λ·sim(d, q) - (1-λ)·max_sim(d, selected) ]

    Inter-result similarity is approximated using act_code:
        same act_code → similarity = 1.0 (highly similar statutory context)
        different act_code → similarity = 0.2 (different statutory domain)

    This avoids needing to fetch dense vectors (100KB overhead per query) while
    still achieving structural diversity — ensuring results come from multiple
    acts rather than all from one act with equal semantic relevance.

    Args:
        candidates:    Score-sorted RRF result list (with 'boosted_score').
        mmr_diversity: λ complement. 0.0 = pure relevance, 1.0 = pure diversity.
                       Recommended: 0.3 for layman/advisor civil queries.
        top_k:         Number of results to select.

    Returns:
        Greedy-selected list of length min(top_k, len(candidates)).
    """
    if mmr_diversity <= 0.0 or not candidates:
        return candidates[:top_k]

    lam = 1.0 - mmr_diversity  # weight on relevance; (1-lam) on diversity

    selected: list[dict] = []
    remaining = list(candidates)

    while remaining and len(selected) < top_k:
        best_idx = 0
        best_mmr = float("-inf")

        for i, cand in enumerate(remaining):
            relevance = cand.get("boosted_score", cand.get("rrf_score", 0.0))
            cand_act = (cand.get("payload") or {}).get("act_code", "_UNKNOWN_")

            if selected:
                # Max similarity to already-selected results (act_code proximity)
                max_sim = max(
                    1.0 if cand_act == (s.get("payload") or {}).get("act_code", "")
                    else 0.2
                    for s in selected
                )
            else:
                max_sim = 0.0

            mmr_score = lam * relevance - (1.0 - lam) * max_sim
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected


# ---------------------------------------------------------------------------
# HybridSearcher
# ---------------------------------------------------------------------------

class HybridSearcher:
    """Executes hybrid dense + sparse search with RRF fusion.

    Usage:
        searcher = HybridSearcher(qdrant_client, embedder)
        results = await searcher.search("punishment for murder under BNS", top_k=10)
    """

    def __init__(
        self,
        qdrant_client: Any,
        embedder: BGEM3Embedder,
        prefetch_multiplier: int = 5,
    ) -> None:
        """
        Args:
            qdrant_client:       Connected QdrantClient (sync or async).
            embedder:            Loaded BGEM3Embedder instance.
            prefetch_multiplier: Multiplier for candidate count before RRF.
                                 top_k * this = candidates fetched from each vector type.
                                 Increased from 3→5 to improve recall for short sections.
        """
        self._qdrant = qdrant_client
        self._embedder = embedder
        self._prefetch_k = prefetch_multiplier
        self._async_qdrant: Any = None  # lazy-initialized AsyncQdrantClient

    def search(
        self,
        query: str,
        act_filter: Optional[str] = None,
        era_filter: Optional[str] = None,
        legal_domain_filter: Optional[str] = None,
        is_offence_filter: Optional[bool] = None,
        collection: str = COLLECTION_LEGAL_SECTIONS,
        top_k: int = 10,
        query_type: str = "default",
        mmr_diversity: float = 0.0,
    ) -> List[RetrievalResult]:
        """Execute hybrid search with weighted RRF, score boosting, and optional MMR.

        Args:
            query:               Natural language legal query.
            act_filter:          Restrict to act_code (e.g. "BNS_2023").
            era_filter:          Restrict to era ("naveen_sanhitas" or "colonial_codes").
            legal_domain_filter: Restrict to legal_domain (e.g. "criminal_substantive").
            is_offence_filter:   Restrict to offence/non-offence sections (bool).
            collection:          Qdrant collection name. Default: legal_sections.
            top_k:               Number of results to return after all post-processing.
            query_type:          Query type from QueryClassifierTool. Controls RRF
                                 weights: 'section_lookup', 'criminal_offence',
                                 'civil_conceptual', 'procedural', 'old_statute',
                                 'default'. See QUERY_TYPE_WEIGHTS.
            mmr_diversity:       MMR diversity parameter [0.0–1.0].
                                 0.0 = pure relevance (default, no MMR).
                                 0.3 = recommended for layman/advisor civil queries
                                       (forces results from multiple acts).
                                 1.0 = pure diversity (not useful for legal retrieval).

        Returns:
            List[RetrievalResult] sorted by score descending (boosted RRF or MMR).
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue, NamedSparseVector, SparseVector

        candidates = top_k * self._prefetch_k

        # ----------------------------------------------------------------
        # Step 1: Embed query — dense only, NO instruction prefix
        # ----------------------------------------------------------------
        dense_query = self._embedder.encode_dense([query])[0]

        # ----------------------------------------------------------------
        # Step 2: Build Qdrant filter
        # ----------------------------------------------------------------
        filter_conditions = []
        # act_code and era are statute-only fields — sc_judgments collection
        # does not have these indexes, so skip them for that collection.
        is_judgment_collection = collection == COLLECTION_SC_JUDGMENTS
        if act_filter and act_filter != "none" and not is_judgment_collection:
            filter_conditions.append(
                FieldCondition(key="act_code", match=MatchValue(value=act_filter))
            )
        if era_filter and era_filter != "none" and not is_judgment_collection:
            filter_conditions.append(
                FieldCondition(key="era", match=MatchValue(value=era_filter))
            )
        if legal_domain_filter and legal_domain_filter != "none":
            filter_conditions.append(
                FieldCondition(key="legal_domain", match=MatchValue(value=legal_domain_filter))
            )
        if is_offence_filter is not None:
            filter_conditions.append(
                FieldCondition(key="is_offence", match=MatchValue(value=is_offence_filter))
            )

        qdrant_filter = Filter(must=filter_conditions) if filter_conditions else None

        # ----------------------------------------------------------------
        # Step 3: Prefetch dense results
        # ----------------------------------------------------------------
        dense_hits = self._qdrant.search(
            collection_name=collection,
            query_vector=("dense", dense_query),
            query_filter=qdrant_filter,
            limit=candidates,
            with_payload=True,
        )
        dense_results = [
            {
                "point_id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in dense_hits
        ]

        # ----------------------------------------------------------------
        # Step 4: Prefetch sparse results
        # ----------------------------------------------------------------
        sparse_query_dict = self._embedder.encode_sparse([query])[0]
        sv = sparse_dict_to_qdrant(sparse_query_dict)

        sparse_hits = self._qdrant.search(
            collection_name=collection,
            query_vector=NamedSparseVector(name="sparse", vector=SparseVector(**sv)),
            query_filter=qdrant_filter,
            limit=candidates,
            with_payload=True,
        )
        sparse_results = [
            {
                "point_id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in sparse_hits
        ]

        # ----------------------------------------------------------------
        # Step 5: Weighted Reciprocal Rank Fusion
        # ----------------------------------------------------------------
        dense_w, sparse_w = QUERY_TYPE_WEIGHTS.get(query_type, QUERY_TYPE_WEIGHTS["default"])
        fused = reciprocal_rank_fusion(
            dense_results=dense_results,
            sparse_results=sparse_results,
            top_k=top_k * 2,  # Keep 2× top_k for boosting + MMR to select from
            dense_weight=dense_w,
            sparse_weight=sparse_w,
        )

        # ----------------------------------------------------------------
        # Step 6: Client-side Score Boosting
        # (era recency, extraction confidence, offence classification)
        # Skip for sc_judgments — those payloads lack statutory metadata.
        # ----------------------------------------------------------------
        if not is_judgment_collection:
            fused = _apply_score_boost(fused, era_filter=era_filter, query_type=query_type)

        # ----------------------------------------------------------------
        # Step 7: MMR diversity selection (optional)
        # ----------------------------------------------------------------
        if mmr_diversity > 0.0 and not is_judgment_collection:
            fused = _apply_mmr_diversity(fused, mmr_diversity=mmr_diversity, top_k=top_k)
        else:
            fused = fused[:top_k]

        # ----------------------------------------------------------------
        # Step 8: Build RetrievalResult list with deduplication
        # For statute sections: deduplicate by (act_code, section_number) —
        # a section may be indexed more than once; keep highest-scoring copy.
        #
        # For SC judgment chunks: act_code and section_number are both empty
        # strings (""). Using ("", "") as a dedup key would collapse ALL chunks
        # to a single result. Instead, use point_id (each chunk is distinct).
        # Detection: act_code is empty for judgment payloads.
        # ----------------------------------------------------------------
        seen_keys: set = set()
        results: List[RetrievalResult] = []
        for f in fused:
            payload = f["payload"]
            act_code = payload.get("act_code", "")
            section_number = payload.get("section_number", "")
            if act_code:
                # Statutory section — deduplicate by (act, section) pair
                dedup_key: object = (act_code, section_number)
            else:
                # Judgment chunk (or unknown) — each point is individually distinct
                dedup_key = f["point_id"]
            if dedup_key in seen_keys:
                continue  # Skip duplicate — fused list is already score-sorted
            seen_keys.add(dedup_key)

            # Use boosted_score as primary score when available
            final_score = f.get("boosted_score", f["rrf_score"])
            text = payload.get("text") or self._extract_text_from_payload(payload)
            results.append(
                RetrievalResult(
                    point_id=f["point_id"],
                    score=final_score,
                    dense_score=f["dense_score"],
                    sparse_score=f["sparse_score"],
                    act_code=act_code,
                    section_number=section_number,
                    section_title=payload.get("section_title", ""),
                    era=payload.get("era", ""),
                    text=text,
                    payload=payload,
                )
            )

        logger.info(
            "hybrid_search: query=%r act=%s era=%s query_type=%s mmr=%.1f top_k=%d results=%d",
            query[:60], act_filter, era_filter, query_type, mmr_diversity, top_k, len(results),
        )
        return results

    async def _get_async_qdrant(self) -> Any:
        """Lazily create and return an AsyncQdrantClient.

        Shares QDRANT_URL / QDRANT_API_KEY with the sync client but
        uses the async client for I/O-bound Qdrant queries in search_async().
        """
        if self._async_qdrant is None:
            from backend.rag.qdrant_setup import get_async_qdrant_client
            self._async_qdrant = get_async_qdrant_client()
        return self._async_qdrant

    async def search_async(
        self,
        query: str,
        act_filter: Optional[str] = None,
        era_filter: Optional[str] = None,
        legal_domain_filter: Optional[str] = None,
        is_offence_filter: Optional[bool] = None,
        collection: str = COLLECTION_LEGAL_SECTIONS,
        top_k: int = 10,
        query_type: str = "default",
        mmr_diversity: float = 0.0,
    ) -> List[RetrievalResult]:
        """Async equivalent of search() — uses AsyncQdrantClient and asyncio.to_thread for embeddings.

        Embedding generation (BGE-M3) is CPU-bound, so it is offloaded to a thread via
        asyncio.to_thread(). Qdrant queries are I/O-bound and run natively async.

        The retrieval pipeline mirrors search(): weighted RRF, score boosting, MMR.

        Args:
            query, act_filter, era_filter, legal_domain_filter, is_offence_filter,
            collection, top_k, query_type, mmr_diversity: identical semantics to search().

        Returns:
            List[RetrievalResult] sorted by score descending (boosted or MMR-selected).
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue, NamedSparseVector, SparseVector

        candidates = top_k * self._prefetch_k

        # ----------------------------------------------------------------
        # Step 1: Embed query — CPU-bound, run in thread to yield event loop
        # ----------------------------------------------------------------
        dense_batch = await asyncio.to_thread(self._embedder.encode_dense, [query])
        dense_query = dense_batch[0]

        # ----------------------------------------------------------------
        # Step 2: Build Qdrant filter (same logic as sync search())
        # ----------------------------------------------------------------
        filter_conditions = []
        is_judgment_collection = collection == COLLECTION_SC_JUDGMENTS
        if act_filter and act_filter != "none" and not is_judgment_collection:
            filter_conditions.append(
                FieldCondition(key="act_code", match=MatchValue(value=act_filter))
            )
        if era_filter and era_filter != "none" and not is_judgment_collection:
            filter_conditions.append(
                FieldCondition(key="era", match=MatchValue(value=era_filter))
            )
        if legal_domain_filter and legal_domain_filter != "none":
            filter_conditions.append(
                FieldCondition(key="legal_domain", match=MatchValue(value=legal_domain_filter))
            )
        if is_offence_filter is not None:
            filter_conditions.append(
                FieldCondition(key="is_offence", match=MatchValue(value=is_offence_filter))
            )

        qdrant_filter = Filter(must=filter_conditions) if filter_conditions else None

        # ----------------------------------------------------------------
        # Step 3: Async dense search (I/O-bound)
        # ----------------------------------------------------------------
        async_qdrant = await self._get_async_qdrant()
        dense_hits = await async_qdrant.search(
            collection_name=collection,
            query_vector=("dense", dense_query),
            query_filter=qdrant_filter,
            limit=candidates,
            with_payload=True,
        )
        dense_results = [
            {
                "point_id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in dense_hits
        ]

        # ----------------------------------------------------------------
        # Step 4: Encode sparse in thread (CPU-bound), then async sparse search
        # ----------------------------------------------------------------
        sparse_batch = await asyncio.to_thread(self._embedder.encode_sparse, [query])
        sparse_query_dict = sparse_batch[0]
        sv = sparse_dict_to_qdrant(sparse_query_dict)

        sparse_hits = await async_qdrant.search(
            collection_name=collection,
            query_vector=NamedSparseVector(name="sparse", vector=SparseVector(**sv)),
            query_filter=qdrant_filter,
            limit=candidates,
            with_payload=True,
        )
        sparse_results = [
            {
                "point_id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
            }
            for hit in sparse_hits
        ]

        # ----------------------------------------------------------------
        # Step 5: Weighted RRF fusion
        # ----------------------------------------------------------------
        dense_w, sparse_w = QUERY_TYPE_WEIGHTS.get(query_type, QUERY_TYPE_WEIGHTS["default"])
        fused = reciprocal_rank_fusion(
            dense_results=dense_results,
            sparse_results=sparse_results,
            top_k=top_k * 2,
            dense_weight=dense_w,
            sparse_weight=sparse_w,
        )

        # ----------------------------------------------------------------
        # Step 6: Score boosting (skipped for sc_judgments)
        # ----------------------------------------------------------------
        if not is_judgment_collection:
            fused = _apply_score_boost(fused, era_filter=era_filter, query_type=query_type)

        # ----------------------------------------------------------------
        # Step 7: MMR diversity selection (optional)
        # ----------------------------------------------------------------
        if mmr_diversity > 0.0 and not is_judgment_collection:
            fused = _apply_mmr_diversity(fused, mmr_diversity=mmr_diversity, top_k=top_k)
        else:
            fused = fused[:top_k]

        # ----------------------------------------------------------------
        # Step 8: Build RetrievalResult list with deduplication (same as sync)
        # ----------------------------------------------------------------
        seen_keys: set = set()
        results: List[RetrievalResult] = []
        for f in fused:
            payload = f["payload"]
            act_code = payload.get("act_code", "")
            section_number = payload.get("section_number", "")
            if act_code:
                dedup_key: object = (act_code, section_number)
            else:
                dedup_key = f["point_id"]
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            final_score = f.get("boosted_score", f["rrf_score"])
            text = payload.get("text") or self._extract_text_from_payload(payload)
            results.append(
                RetrievalResult(
                    point_id=f["point_id"],
                    score=final_score,
                    dense_score=f["dense_score"],
                    sparse_score=f["sparse_score"],
                    act_code=act_code,
                    section_number=section_number,
                    section_title=payload.get("section_title", ""),
                    era=payload.get("era", ""),
                    text=text,
                    payload=payload,
                )
            )

        logger.info(
            "hybrid_search_async: query=%r act=%s era=%s query_type=%s mmr=%.1f top_k=%d results=%d",
            query[:60], act_filter, era_filter, query_type, mmr_diversity, top_k, len(results),
        )
        return results

    @staticmethod
    def _extract_text_from_payload(payload: dict) -> str:
        """Fallback: reconstruct displayable text from section payload fields."""
        number = payload.get("section_number", "")
        title = payload.get("section_title", "")
        if number and title:
            return f"{number}. {title}"
        return ""


# ---------------------------------------------------------------------------
# Sub-section search convenience method
# ---------------------------------------------------------------------------

class SubSectionSearcher(HybridSearcher):
    """Searches legal_sub_sections collection for granular clause retrieval."""

    def search_sub_sections(
        self,
        query: str,
        act_filter: Optional[str] = None,
        era_filter: Optional[str] = None,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """Search the sub-sections collection directly."""
        return self.search(
            query=query,
            act_filter=act_filter,
            era_filter=era_filter,
            collection=COLLECTION_LEGAL_SUB_SECTIONS,
            top_k=top_k,
        )
