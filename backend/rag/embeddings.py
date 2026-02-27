"""BGE-M3 embedding wrapper for Neethi AI legal text indexing.

BGE-M3 (BAAI/bge-m3) is the non-negotiable embedding model for this system.
It produces both dense (1024-dim) and sparse vectors in a single forward pass,
enabling hybrid (dense + sparse) retrieval via Qdrant.

IMPORTANT — asymmetric embedding:
- Document texts at INDEX TIME: prepend the retrieval instruction prefix.
- Query texts at SEARCH TIME: do NOT prepend the prefix.
This asymmetry is specific to BGE-M3 and improves retrieval quality significantly.

Document prefix:
    "Represent this Indian legal provision for retrieval: " + legal_text

This module requires FlagEmbedding to be installed:
    pip install FlagEmbedding

FlagEmbedding is expected to be installed on the GPU machine (Lightning AI).
The module will raise ImportError with a clear message if it is not available.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instruction prefix (asymmetric embedding — documents only, never queries)
# ---------------------------------------------------------------------------

DOCUMENT_PREFIX = "Represent this Indian legal provision for retrieval: "


# ---------------------------------------------------------------------------
# BGEM3Embedder
# ---------------------------------------------------------------------------

class BGEM3Embedder:
    """Wrapper around BAAI/bge-m3 using FlagEmbedding.

    Usage:
        embedder = BGEM3Embedder()
        dense_vecs, sparse_vecs = embedder.encode_batch(texts)

    The embedder should be instantiated ONCE and reused. Loading BGE-M3 takes
    several seconds and allocates significant GPU/CPU memory.

    Sparse vector format returned by encode_sparse / encode_batch:
        List[Dict[int, float]] — token_id -> weight mapping.
        Call sparse_dict_to_qdrant(sparse) to convert for Qdrant upload.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        use_fp16: bool = True,
    ) -> None:
        """Load the BGE-M3 model.

        Args:
            model_path: HuggingFace model ID or local path.
                        Defaults to BGE_M3_MODEL_PATH env var or 'BAAI/bge-m3'.
            use_fp16:   Use FP16 for faster GPU inference. Falls back to FP32
                        on CPU automatically.

        Raises:
            ImportError: If FlagEmbedding is not installed.
        """
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "FlagEmbedding is not installed. "
                "Install it on the GPU machine: pip install FlagEmbedding\n"
                "BGE-M3 is non-negotiable for this system — do not substitute."
            ) from exc

        resolved_path = model_path or os.getenv("BGE_M3_MODEL_PATH", "BAAI/bge-m3")
        logger.info("bgem3_loading: model=%s use_fp16=%s", resolved_path, use_fp16)

        t0 = time.monotonic()
        self._model = BGEM3FlagModel(resolved_path, use_fp16=use_fp16)
        elapsed = time.monotonic() - t0

        logger.info("bgem3_loaded: model=%s elapsed_s=%.2f", resolved_path, elapsed)
        self._model_path = resolved_path

    # ------------------------------------------------------------------
    # Public encoding methods
    # ------------------------------------------------------------------

    def encode_dense(self, texts: List[str]) -> List[List[float]]:
        """Encode texts to 1024-dimensional dense vectors.

        Args:
            texts: List of text strings. Apply DOCUMENT_PREFIX if indexing;
                   do NOT apply for query texts.

        Returns:
            List of 1024-dimensional float vectors (one per input text).
        """
        t0 = time.monotonic()
        output = self._model.encode(
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        elapsed = time.monotonic() - t0
        dense = output["dense_vecs"].tolist()
        logger.debug(
            "bgem3_encode_dense: n=%d elapsed_s=%.3f", len(texts), elapsed
        )
        return dense

    def encode_sparse(self, texts: List[str]) -> List[Dict[int, float]]:
        """Encode texts to sparse lexical weight vectors.

        Args:
            texts: List of text strings. Apply DOCUMENT_PREFIX if indexing.

        Returns:
            List of dicts mapping token_id (int) -> weight (float).
            Use sparse_dict_to_qdrant() to convert for Qdrant PointStruct.
        """
        t0 = time.monotonic()
        output = self._model.encode(
            texts,
            return_dense=False,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        elapsed = time.monotonic() - t0
        sparse = output["lexical_weights"]
        logger.debug(
            "bgem3_encode_sparse: n=%d elapsed_s=%.3f", len(texts), elapsed
        )
        return [dict(s) for s in sparse]

    def encode_batch(
        self,
        texts: List[str],
        batch_size: int = 32,
    ) -> Tuple[List[List[float]], List[Dict[int, float]]]:
        """Encode dense and sparse in a single forward pass per batch.

        This is the preferred method for indexing — BGE-M3 computes both
        dense and sparse vectors simultaneously, avoiding redundant computation.

        Args:
            texts:      List of text strings (with DOCUMENT_PREFIX if indexing).
            batch_size: Number of texts per forward pass. Reduce if OOM on GPU.

        Returns:
            Tuple of (dense_vectors, sparse_vectors).
            dense_vectors: List[List[float]] — 1024-dim per text.
            sparse_vectors: List[Dict[int, float]] — token_id->weight per text.
        """
        all_dense: List[List[float]] = []
        all_sparse: List[Dict[int, float]] = []

        total = len(texts)
        for start in range(0, total, batch_size):
            batch = texts[start : start + batch_size]
            t0 = time.monotonic()

            output = self._model.encode(
                batch,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )

            elapsed = time.monotonic() - t0
            batch_dense = output["dense_vecs"].tolist()
            batch_sparse = [dict(s) for s in output["lexical_weights"]]

            all_dense.extend(batch_dense)
            all_sparse.extend(batch_sparse)

            logger.info(
                "bgem3_encode_batch: batch=%d/%d size=%d elapsed_s=%.3f",
                start + len(batch),
                total,
                len(batch),
                elapsed,
            )

        return all_dense, all_sparse


# ---------------------------------------------------------------------------
# Sparse vector format conversion
# ---------------------------------------------------------------------------

def sparse_dict_to_qdrant(sparse: Dict[int, float]) -> dict:
    """Convert a BGE-M3 sparse dict to Qdrant SparseVector format.

    BGE-M3 returns: {token_id: weight, ...}
    Qdrant requires: SparseVector(indices=[...], values=[...])

    Args:
        sparse: Token ID to weight mapping from BGE-M3.

    Returns:
        Dict with "indices" and "values" lists, ready to construct
        qdrant_client.models.SparseVector(**result).
    """
    if not sparse:
        return {"indices": [], "values": []}
    indices, values = zip(*sorted(sparse.items()))
    return {"indices": list(indices), "values": list(values)}


def apply_document_prefix(texts: List[str]) -> List[str]:
    """Apply the BGE-M3 asymmetric instruction prefix to document texts.

    ONLY call this when preparing texts for INDEX TIME embedding.
    Do NOT call this for query texts at search time.

    Args:
        texts: List of legal text strings to be indexed.

    Returns:
        List of prefixed strings: [DOCUMENT_PREFIX + t for t in texts]
    """
    return [DOCUMENT_PREFIX + t for t in texts]
