"""Qdrant collection setup for Neethi AI.

Creates all four collections with the correct vector configuration, quantization,
and payload indexes. Run this once before any embedding or indexing operations.

Usage:
    from backend.rag.qdrant_setup import create_all_collections, get_qdrant_client
    client = get_qdrant_client()
    create_all_collections(client)

Collections:
    legal_sections       — Primary statute retrieval (BNS, BNSS, BSA, IPC, CrPC, IEA)
    legal_sub_sections   — Granular clause/proviso/explanation retrieval
    case_law             — SC/HC judgments (created now, populated in future phase)
    law_transition_context — IPC→BNS transition explanations (Phase 3B)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
    PayloadSchemaType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DENSE_DIM = 1024                      # BGE-M3 dense vector dimension
DENSE_DISTANCE = Distance.COSINE

# Collection names — canonical strings used throughout the codebase
COLLECTION_LEGAL_SECTIONS = "legal_sections"
COLLECTION_LEGAL_SUB_SECTIONS = "legal_sub_sections"
COLLECTION_CASE_LAW = "case_law"
COLLECTION_TRANSITION_CONTEXT = "law_transition_context"
COLLECTION_SC_JUDGMENTS = "sc_judgments"

ALL_COLLECTIONS = [
    COLLECTION_LEGAL_SECTIONS,
    COLLECTION_LEGAL_SUB_SECTIONS,
    COLLECTION_CASE_LAW,
    COLLECTION_TRANSITION_CONTEXT,
    COLLECTION_SC_JUDGMENTS,
]


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_qdrant_client(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> QdrantClient:
    """Return a synchronous QdrantClient using environment variables.

    Args:
        url:     Override QDRANT_URL env var. Defaults to http://localhost:6333.
        api_key: Override QDRANT_API_KEY env var. Pass None for local instances.
    """
    resolved_url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
    resolved_key = api_key or os.getenv("QDRANT_API_KEY") or None
    client = QdrantClient(url=resolved_url, api_key=resolved_key)
    logger.info("qdrant_client: connected to %s", resolved_url)
    return client


def get_async_qdrant_client(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> "AsyncQdrantClient":
    """Return an AsyncQdrantClient using environment variables.

    Drop-in async equivalent of get_qdrant_client(). Same env vars, same defaults.
    The caller must be in an async context to use the returned client.

    Args:
        url:     Override QDRANT_URL env var. Defaults to http://localhost:6333.
        api_key: Override QDRANT_API_KEY env var. Pass None for local instances.
    """
    from qdrant_client import AsyncQdrantClient

    resolved_url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
    resolved_key = api_key or os.getenv("QDRANT_API_KEY") or None
    client = AsyncQdrantClient(url=resolved_url, api_key=resolved_key)
    logger.info("async_qdrant_client: connected to %s", resolved_url)
    return client


# ---------------------------------------------------------------------------
# Collection creation helpers
# ---------------------------------------------------------------------------

def _base_vectors_config(quantile: float = 0.99) -> dict:
    """Return the standard named-vector + quantization config."""
    return dict(
        vectors_config={
            "dense": VectorParams(size=DENSE_DIM, distance=DENSE_DISTANCE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
            ),
        },
        quantization_config=ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                quantile=quantile,
                always_ram=True,
            )
        ),
        on_disk_payload=False,
    )


def _create_collection_safe(client: QdrantClient, name: str, **kwargs: object) -> None:
    """Create a collection if it does not already exist."""
    if client.collection_exists(name):
        logger.info("collection_exists: %s — skipping creation", name)
        return
    client.create_collection(collection_name=name, **kwargs)
    logger.info("created_collection: %s", name)


# ---------------------------------------------------------------------------
# Per-collection setup
# ---------------------------------------------------------------------------

def _setup_legal_sections(client: QdrantClient) -> None:
    """Create legal_sections collection and all its payload indexes."""
    _create_collection_safe(
        client,
        COLLECTION_LEGAL_SECTIONS,
        **_base_vectors_config(quantile=0.99),
    )

    # Keyword indexes
    keyword_fields = [
        "act_code", "era", "status", "legal_domain", "sub_domain",
        "section_number", "chunk_type", "triable_by",
        "supersedes_act", "supersedes_section", "transition_type",
        "punishment_type",
    ]
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    # Integer indexes
    for field in ("chapter_number_int", "punishment_max_years", "chunk_index"):
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            field_name=field,
            field_schema=PayloadSchemaType.INTEGER,
        )

    # Boolean indexes
    for field in ("is_offence", "is_cognizable", "is_bailable", "needs_review"):
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            field_name=field,
            field_schema="bool",
        )

    # Datetime indexes (use string literal — safer across qdrant-client patch versions)
    for field in ("applicable_from", "applicable_until"):
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            field_name=field,
            field_schema="datetime",
        )

    logger.info("payload_indexes_created: %s", COLLECTION_LEGAL_SECTIONS)


def _setup_legal_sub_sections(client: QdrantClient) -> None:
    """Create legal_sub_sections collection and its payload indexes."""
    # Sub-section texts are shorter — less variance → smaller quantile
    _create_collection_safe(
        client,
        COLLECTION_LEGAL_SUB_SECTIONS,
        **_base_vectors_config(quantile=0.95),
    )

    # Keyword indexes
    keyword_fields = [
        "act_code", "era", "status", "legal_domain",
        "section_number", "sub_section_label", "sub_section_type", "chunk_type",
        "parent_section_title",
    ]
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SUB_SECTIONS,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    # Integer indexes
    client.create_payload_index(
        collection_name=COLLECTION_LEGAL_SUB_SECTIONS,
        field_name="position_order",
        field_schema=PayloadSchemaType.INTEGER,
    )

    # Boolean indexes
    for field in ("is_exception", "is_definition", "is_illustration", "is_proviso"):
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SUB_SECTIONS,
            field_name=field,
            field_schema="bool",
        )

    # Datetime indexes
    for field in ("applicable_from", "applicable_until"):
        client.create_payload_index(
            collection_name=COLLECTION_LEGAL_SUB_SECTIONS,
            field_name=field,
            field_schema="datetime",
        )

    logger.info("payload_indexes_created: %s", COLLECTION_LEGAL_SUB_SECTIONS)


def _setup_case_law(client: QdrantClient) -> None:
    """Create case_law collection (not populated until future phase).

    This collection holds SC/HC judgments — narrative text longer than statute
    provisions, requiring different chunking strategy (implemented in Phase 4+).
    """
    _create_collection_safe(
        client,
        COLLECTION_CASE_LAW,
        **_base_vectors_config(quantile=0.99),
    )

    for field in ("act_code", "court", "legal_domain", "case_citation", "judgment_year"):
        client.create_payload_index(
            collection_name=COLLECTION_CASE_LAW,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    logger.info("collection_created (empty): %s", COLLECTION_CASE_LAW)


def _setup_transition_context(client: QdrantClient) -> None:
    """Create law_transition_context collection (populated in Phase 3B)."""
    _create_collection_safe(
        client,
        COLLECTION_TRANSITION_CONTEXT,
        **_base_vectors_config(quantile=0.99),
    )

    for field in ("old_act", "new_act", "old_section", "new_section", "transition_type"):
        client.create_payload_index(
            collection_name=COLLECTION_TRANSITION_CONTEXT,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    logger.info("payload_indexes_created: %s", COLLECTION_TRANSITION_CONTEXT)


def _setup_sc_judgments(client: QdrantClient) -> None:
    """Create sc_judgments collection for Supreme Court judgment chunks (2010–2025).

    Configuration rationale from architecture report (docs/neethi_architecture_report.md):

    - on_disk=True for dense vectors: protects the 1GB Qdrant Cloud free tier RAM limit.
      At ~200,000 points × 1024 floats × 4 bytes = ~800MB of raw dense vectors, keeping
      them on disk is mandatory. The INT8 quantized index (always_ram=True) stays in RAM
      for fast approximate search.

    - HnswConfigDiff(m=8): default m=16 uses ~40% more disk. m=8 is adequate for legal
      retrieval where recall@10 is more important than exhaustive nearest-neighbor accuracy.

    - ef_construct=100: lower than default 200. Adequate precision for paragraph-level
      legal chunks where semantic meaning is coarse-grained.

    - INT8 scalar quantization (4× compression): float32 1024-dim → int8 1024-dim.
      ~200,000 points × 1024 bytes = ~200MB in RAM vs ~800MB without quantization.

    Payload schema per chunk:
        text           — embedded chunk text (400–500 tokens of judgment reasoning)
        chunk_index    — position within this judgment (0-indexed)
        total_chunks   — total chunks for this judgment
        section_type   — "background" (first 2), "analysis" (middle), "conclusion" (last 2)
        case_name      — "Petitioner v. Respondent"
        case_no        — eCourts formal case number
        diary_no       — primary deduplication key (matches ingested_judgments.diary_no)
        disposal_nature — "Dismissed", "Allowed", "Bail Granted" etc.
        year           — integer year of judgment
        decision_date  — ISO date string (after century-bug correction)
        legal_domain   — "civil", "criminal", "constitutional" etc.
        ik_url         — Indian Kanoon URL (empty string until enrichment pass)
        language       — "en" (English only for initial ingestion)
    """
    if client.collection_exists(COLLECTION_SC_JUDGMENTS):
        logger.info("collection_exists: %s — skipping creation", COLLECTION_SC_JUDGMENTS)
    else:
        client.create_collection(
            collection_name=COLLECTION_SC_JUDGMENTS,
            vectors_config={
                # on_disk=True: dense float32 vectors live on disk, not RAM
                "dense": VectorParams(
                    size=DENSE_DIM,
                    distance=DENSE_DISTANCE,
                    on_disk=True,
                ),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                ),
            },
            quantization_config=ScalarQuantization(
                scalar=ScalarQuantizationConfig(
                    type=ScalarType.INT8,
                    quantile=0.99,
                    always_ram=True,  # quantized index stays in RAM for speed
                )
            ),
            hnsw_config=HnswConfigDiff(
                m=8,              # half of default 16 → ~40% disk saving
                ef_construct=100, # lower than default 200 — adequate for legal paragraphs
                on_disk=True,     # HNSW graph on disk, not RAM
            ),
            on_disk_payload=False,  # payload stays in RAM (small per-point size)
        )
        logger.info("created_collection: %s", COLLECTION_SC_JUDGMENTS)

    # Keyword indexes for persona-based payload filtering
    keyword_fields = [
        "disposal_nature",  # "Dismissed", "Allowed", "Bail Granted" etc.
        "section_type",     # "background", "analysis", "conclusion"
        "legal_domain",     # "civil", "criminal", "constitutional"
        "language",         # "en" (future: "hi", "ta" etc. via Sarvam)
        "diary_no",         # exact lookup for citation verification
    ]
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=COLLECTION_SC_JUDGMENTS,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    # Integer index for year-based filtering (e.g. advisor crew: year >= 2015)
    client.create_payload_index(
        collection_name=COLLECTION_SC_JUDGMENTS,
        field_name="year",
        field_schema=PayloadSchemaType.INTEGER,
    )

    # Integer index for chunk position — enables re-assembly of judgment in order
    client.create_payload_index(
        collection_name=COLLECTION_SC_JUDGMENTS,
        field_name="chunk_index",
        field_schema=PayloadSchemaType.INTEGER,
    )

    logger.info("payload_indexes_created: %s", COLLECTION_SC_JUDGMENTS)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def create_all_collections(client: QdrantClient) -> None:
    """Create all four Qdrant collections with indexes.

    Idempotent: skips collections that already exist.
    Payload indexes are created unconditionally (Qdrant silently ignores duplicates).

    Args:
        client: Connected QdrantClient instance.
    """
    _setup_legal_sections(client)
    _setup_legal_sub_sections(client)
    _setup_case_law(client)
    _setup_transition_context(client)
    _setup_sc_judgments(client)
    logger.info("all_collections_ready: %s", ALL_COLLECTIONS)


def verify_collections(client: QdrantClient) -> dict:
    """Return a summary of collection status for health checks.

    Returns:
        Dict mapping collection_name -> {"exists": bool, "vectors_count": int}
    """
    result = {}
    for name in ALL_COLLECTIONS:
        if client.collection_exists(name):
            info = client.get_collection(name)
            result[name] = {
                "exists": True,
                "vectors_count": info.vectors_count or 0,
                "points_count": info.points_count or 0,
            }
        else:
            result[name] = {"exists": False, "vectors_count": 0, "points_count": 0}
    return result
