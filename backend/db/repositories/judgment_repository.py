"""JudgmentRepository — data access for ingested_judgments table.

Provides lookup and upsert operations for the SC judgment ingestion pipeline.
All write operations are called from the synchronous sc_judgment_ingester.py
script, so this repository uses a sync engine for simplicity.

For async FastAPI endpoints (future), a separate async path can be added.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async repository (for CitationChecker verification in future)
# ---------------------------------------------------------------------------

async def diary_no_exists(diary_no: str) -> bool:
    """Return True if a judgment with this diary_no is in ingested_judgments.

    Used by CitationChecker to verify SC judgment citations. Queries Supabase
    via a fresh async engine to avoid asyncpg pool conflicts in sync context.

    Args:
        diary_no: The eCourts internal filing number (e.g. "10169-2001").

    Returns:
        True if the diary_no is present in ingested_judgments, False otherwise.
    """
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import select
    from backend.db.models.legal_foundation import IngestedJudgment

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("judgment_repository: DATABASE_URL not set")
        return False

    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(
                select(IngestedJudgment.diary_no).where(
                    IngestedJudgment.diary_no == diary_no
                ).limit(1)
            )
            return result.scalar_one_or_none() is not None
    except Exception as exc:
        logger.error("judgment_repository.diary_no_exists: %s", exc)
        return False
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Sync repository (for ingestion pipeline)
# ---------------------------------------------------------------------------

def is_already_ingested(diary_no: str, sync_session) -> bool:
    """Check if a diary_no already exists in ingested_judgments.

    Called by sc_judgment_ingester.py to skip already-processed judgments.

    Args:
        diary_no:     eCourts filing number to check.
        sync_session: Active SQLAlchemy sync Session.

    Returns:
        True if already ingested (skip this judgment).
    """
    from sqlalchemy import select
    from backend.db.models.legal_foundation import IngestedJudgment

    result = sync_session.execute(
        select(IngestedJudgment.diary_no).where(
            IngestedJudgment.diary_no == diary_no
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def upsert_judgment_record(
    diary_no: str,
    case_no: Optional[str],
    case_name: Optional[str],
    year: int,
    decision_date,
    disposal_nature: Optional[str],
    legal_domain: Optional[str],
    qdrant_point_ids: list,
    chunk_count: int,
    pdf_hash: Optional[str],
    ocr_required: bool,
    sync_session,
) -> None:
    """Insert or update a judgment record in ingested_judgments.

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE (upsert) so the pipeline
    is fully idempotent — re-running for the same year updates existing records
    with fresh chunk counts and point IDs without creating duplicates.

    Args:
        diary_no:          Primary deduplication key.
        case_no:           Formal case number.
        case_name:         Petitioner v. Respondent.
        year:              Year partition key.
        decision_date:     date object after century-bug correction.
        disposal_nature:   Disposal category from Vanga Parquet.
        legal_domain:      Inferred domain from case_no prefix.
        qdrant_point_ids:  List of str UUIDs for all Qdrant chunks.
        chunk_count:       Total number of chunks upserted.
        pdf_hash:          SHA-256 hex digest of the source PDF.
        ocr_required:      True if Tesseract OCR was used.
        sync_session:      Active SQLAlchemy sync Session.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.db.models.legal_foundation import IngestedJudgment

    stmt = pg_insert(IngestedJudgment).values(
        diary_no=diary_no,
        case_no=case_no,
        case_name=case_name,
        year=year,
        decision_date=decision_date,
        disposal_nature=disposal_nature,
        legal_domain=legal_domain,
        qdrant_point_ids=qdrant_point_ids,
        chunk_count=chunk_count,
        ik_url="",
        pdf_hash=pdf_hash,
        ocr_required=ocr_required,
    ).on_conflict_do_update(
        index_elements=["diary_no"],
        set_={
            "case_no": case_no,
            "case_name": case_name,
            "year": year,
            "decision_date": decision_date,
            "disposal_nature": disposal_nature,
            "legal_domain": legal_domain,
            "qdrant_point_ids": qdrant_point_ids,
            "chunk_count": chunk_count,
            "pdf_hash": pdf_hash,
            "ocr_required": ocr_required,
        },
    )
    sync_session.execute(stmt)
    sync_session.commit()
    logger.debug("judgment_repository.upsert: diary_no=%s chunks=%d", diary_no, chunk_count)
