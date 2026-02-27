"""Re-index sections that are in PostgreSQL but not yet in Qdrant.

Finds every act that has sections with qdrant_indexed=False and runs the
LegalIndexer for each. Safe to run multiple times — LegalIndexer upserts
(never duplicates) and only re-processes sections with qdrant_indexed=False.

Run on the Lightning AI server:
    cd /teamspace/studios/this_studio/Phase2
    python scripts/reindex_unindexed_sections.py

Expected output (based on current inspection data):
    ICA_1872:  ~18 sections to index
    TPA_1882:  ~13 sections to index
    HMA_1955:   ~7 sections to index
    SRA_1963:   ~4 sections to index
    LA_1963:    ~1 section  to index
    Total:     ~43 sections recovered
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Ensure project root is on sys.path so `backend.*` imports resolve
# regardless of which directory the script is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reindex")


async def main() -> None:
    # --- Imports (must run inside async context on Lightning AI) ---
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import text

    from backend.rag.embeddings import BGEM3Embedder
    from backend.rag.qdrant_setup import get_qdrant_client
    from backend.rag.indexer import LegalIndexer
    from backend.db.repositories.section_repository import SectionRepository

    # --- Connections ---
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
    )
    engine = create_async_engine(db_url, echo=False, pool_size=5)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    qdrant = get_qdrant_client()
    embedder = BGEM3Embedder()

    # --- Find acts with unindexed sections ---
    async with SessionLocal() as session:
        rows = await session.execute(text("""
            SELECT act_code, COUNT(*) AS unindexed_count
            FROM sections
            WHERE qdrant_indexed = FALSE
            GROUP BY act_code
            ORDER BY act_code
        """))
        pending = rows.fetchall()

    if not pending:
        logger.info("Nothing to do — all sections are already indexed in Qdrant.")
        return

    print("\nUnindexed sections found:")
    print(f"  {'Act Code':<15} {'Unindexed':>10}")
    print(f"  {'-'*15} {'-'*10}")
    total_pending = 0
    for row in pending:
        print(f"  {row.act_code:<15} {row.unindexed_count:>10,}")
        total_pending += row.unindexed_count
    print(f"  {'TOTAL':<15} {total_pending:>10,}\n")

    # --- Run LegalIndexer for each act ---
    results = []
    for row in pending:
        act_code = row.act_code
        logger.info("Indexing %s (%d unindexed sections)...", act_code, row.unindexed_count)

        async with SessionLocal() as session:
            repo = SectionRepository(session)
            indexer = LegalIndexer(
                qdrant_client=qdrant,
                embedder=embedder,
                repo=repo,
                batch_size=16,  # Conservative batch — won't OOM on free-tier Qdrant
            )
            report = await indexer.index_act(act_code)

        results.append(report)
        logger.info(report.summary())

    # --- Final summary ---
    print("\n" + "=" * 60)
    print("RE-INDEXING COMPLETE")
    print("=" * 60)
    print(f"  {'Act Code':<15} {'Eligible':>9}  {'Indexed':>8}  {'Points':>8}  {'Errors':>7}")
    print(f"  {'-'*15} {'-'*9}  {'-'*8}  {'-'*8}  {'-'*7}")
    for r in results:
        print(
            f"  {r.act_code:<15} {r.sections_eligible:>9,}  "
            f"{r.sections_indexed:>8,}  {r.section_points_created:>8,}  {r.errors:>7,}"
        )
        if r.error_details:
            for err in r.error_details[:5]:
                print(f"    ERROR: {err}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
