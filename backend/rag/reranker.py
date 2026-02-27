"""Cross-encoder re-ranker for final precision after RRF fusion.

Uses 'cross-encoder/ms-marco-MiniLM-L-6-v2' from sentence-transformers.
Applied to the top-K RRF results to produce the final ranked list.

Design rules:
- Only re-ranks what was passed in — never expands the result set.
- Graceful fallback: if the cross-encoder fails to load or times out,
  returns the original RRF-ranked results unchanged.
- Singleton pattern: load once, reuse across requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ---------------------------------------------------------------------------
# RetrievalResult dataclass (shared with hybrid_search.py)
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    """A single result from hybrid search + optional re-ranking."""

    point_id: str
    score: float              # RRF score (or cross-encoder score after re-ranking)
    dense_score: float
    sparse_score: float
    act_code: str
    section_number: str
    section_title: str
    era: str
    text: str                 # The embedded legal text chunk
    payload: dict             # Full Qdrant payload for this point


# ---------------------------------------------------------------------------
# CrossEncoderReranker
# ---------------------------------------------------------------------------

class CrossEncoderReranker:
    """Re-ranks retrieval results using a cross-encoder.

    The cross-encoder evaluates (query, text) pairs jointly, producing
    better relevance scores than dot-product similarity. It is applied
    only to the small top-K set returned by RRF — typically 10–30 results.

    Usage:
        reranker = CrossEncoderReranker()
        reranked = reranker.rerank(query, results, top_k=5)
    """

    def __init__(self, model_name: str = CROSS_ENCODER_MODEL) -> None:
        """Load the cross-encoder model.

        Args:
            model_name: HuggingFace model ID. Defaults to ms-marco-MiniLM-L-6-v2.

        On load failure, _model is set to None and rerank() returns input unchanged.
        """
        self._model = None
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._model = CrossEncoder(model_name)
            logger.info("cross_encoder_loaded: model=%s", model_name)
        except Exception as exc:
            logger.error(
                "cross_encoder_load_failed: model=%s error=%s — "
                "reranker will return RRF-ranked results unchanged",
                model_name,
                exc,
            )

    def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """Re-rank retrieval results using cross-encoder scores.

        Args:
            query:   The user's legal query string.
            results: List of RetrievalResult from hybrid search (RRF-ranked).
            top_k:   Number of results to return. Must be <= len(results).

        Returns:
            Results re-sorted by cross-encoder score, truncated to top_k.
            If the cross-encoder fails for any reason, returns original
            results (truncated to top_k) unchanged.
        """
        if not results:
            return results

        if self._model is None:
            logger.warning("reranker_unavailable: returning RRF-ranked results (top_k=%d)", top_k)
            return results[:top_k]

        try:
            pairs = [(query, r.text) for r in results]
            scores = self._model.predict(pairs)

            # Attach cross-encoder scores and re-sort
            scored = list(zip(scores, results))
            scored.sort(key=lambda x: x[0], reverse=True)

            reranked = []
            for ce_score, result in scored[:top_k]:
                # Replace the .score field with the cross-encoder score
                reranked.append(
                    RetrievalResult(
                        point_id=result.point_id,
                        score=float(ce_score),
                        dense_score=result.dense_score,
                        sparse_score=result.sparse_score,
                        act_code=result.act_code,
                        section_number=result.section_number,
                        section_title=result.section_title,
                        era=result.era,
                        text=result.text,
                        payload=result.payload,
                    )
                )

            return reranked

        except Exception as exc:
            logger.error(
                "reranker_inference_failed: error=%s — returning RRF-ranked results",
                exc,
            )
            return results[:top_k]


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-loaded)
# ---------------------------------------------------------------------------

_reranker_instance: Optional[CrossEncoderReranker] = None


def get_reranker() -> CrossEncoderReranker:
    """Return the module-level reranker singleton (loaded on first call)."""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = CrossEncoderReranker()
    return _reranker_instance
