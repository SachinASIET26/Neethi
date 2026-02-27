"""Reciprocal Rank Fusion (RRF) for hybrid dense + sparse retrieval.

RRF merges two ranked lists (dense results, sparse results) into a single
ranked list without requiring score normalization. It is robust to score
scale differences between dense cosine similarity and sparse BM25-style scores.

Standard formula (unweighted):
    RRF_score(d) = sum(1 / (k + rank_i(d)) for each ranked list i)

Weighted formula (used when query_type is known):
    RRF_score(d) = dense_weight / (k + dense_rank)
                 + sparse_weight / (k + sparse_rank)

where k=60 is the standard RRF constant (empirically optimal, widely used).
Weights are tuned per query type — see QUERY_TYPE_WEIGHTS in hybrid_search.py.

Reference: Cormack, Clarke & Buettcher (SIGIR 2009), "Reciprocal Rank Fusion
outperforms Condorcet and individual Rank Learning Methods."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# Standard RRF constant. Changing this affects how much low-ranked results
# contribute. k=60 is the empirically validated default.
RRF_K = 60


@dataclass
class RRFCandidate:
    """Intermediate container for computing RRF scores across ranked lists."""

    point_id: str
    dense_rank: Optional[int] = None     # 1-based rank in dense list; None if absent
    sparse_rank: Optional[int] = None    # 1-based rank in sparse list; None if absent
    dense_score: float = 0.0             # original dense similarity score
    sparse_score: float = 0.0           # original sparse similarity score
    rrf_score: float = field(default=0.0, init=False)
    payload: dict = field(default_factory=dict)

    def compute_rrf(
        self,
        k: int = RRF_K,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ) -> None:
        """Compute and store the (optionally weighted) RRF score.

        Args:
            k:             RRF smoothing constant. Default 60.
            dense_weight:  Multiplier for the dense rank contribution.
                           Use > 1.0 to favour semantic (conceptual) queries.
            sparse_weight: Multiplier for the sparse rank contribution.
                           Use > 1.0 to favour keyword-exact queries
                           (e.g. direct section lookups like "BNS 103").
        """
        score = 0.0
        if self.dense_rank is not None:
            score += dense_weight / (k + self.dense_rank)
        if self.sparse_rank is not None:
            score += sparse_weight / (k + self.sparse_rank)
        self.rrf_score = score


def reciprocal_rank_fusion(
    dense_results: List[dict],
    sparse_results: List[dict],
    k: int = RRF_K,
    top_k: int = 10,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> List[dict]:
    """Merge dense and sparse ranked lists using (weighted) Reciprocal Rank Fusion.

    Args:
        dense_results:  Ranked list of dicts from dense vector search.
                        Each dict must have "point_id", "score", "payload".
        sparse_results: Ranked list of dicts from sparse vector search.
                        Same schema as dense_results.
        k:              RRF constant. Default 60.
        top_k:          Number of results to return after fusion.
        dense_weight:   Weight for dense component. Default 1.0 (equal weights).
                        Use 3.0 for conceptual civil queries, 1.0 for section lookups.
        sparse_weight:  Weight for sparse (BM25) component. Default 1.0.
                        Use 4.0 for direct section lookups, 1.0 for conceptual.

    Returns:
        List of merged result dicts, sorted by RRF score descending.
        Each result dict contains:
            point_id, rrf_score, dense_score, sparse_score,
            dense_rank (or None), sparse_rank (or None), payload.
    """
    candidates: Dict[str, RRFCandidate] = {}

    # Process dense results
    for rank, result in enumerate(dense_results, start=1):
        pid = result["point_id"]
        if pid not in candidates:
            candidates[pid] = RRFCandidate(
                point_id=pid,
                payload=result.get("payload", {}),
            )
        candidates[pid].dense_rank = rank
        candidates[pid].dense_score = result.get("score", 0.0)
        # Prefer payload from dense results (usually more complete)
        if result.get("payload"):
            candidates[pid].payload = result["payload"]

    # Process sparse results
    for rank, result in enumerate(sparse_results, start=1):
        pid = result["point_id"]
        if pid not in candidates:
            candidates[pid] = RRFCandidate(
                point_id=pid,
                payload=result.get("payload", {}),
            )
        candidates[pid].sparse_rank = rank
        candidates[pid].sparse_score = result.get("score", 0.0)
        # Merge payload — sparse results may have same payload
        if result.get("payload") and not candidates[pid].payload:
            candidates[pid].payload = result["payload"]

    # Compute RRF scores with optional weights
    for candidate in candidates.values():
        candidate.compute_rrf(k=k, dense_weight=dense_weight, sparse_weight=sparse_weight)

    # Sort by RRF score descending
    sorted_candidates = sorted(
        candidates.values(),
        key=lambda c: c.rrf_score,
        reverse=True,
    )[:top_k]

    return [
        {
            "point_id": c.point_id,
            "rrf_score": c.rrf_score,
            "dense_score": c.dense_score,
            "sparse_score": c.sparse_score,
            "dense_rank": c.dense_rank,
            "sparse_rank": c.sparse_rank,
            "payload": c.payload,
        }
        for c in sorted_candidates
    ]
