"""Tag legal_domain for sc_judgments Qdrant collection.

Domain is inferred from the actual opening text of each judgment's first chunk
(chunk_index=0) already stored in Qdrant — no PDFs or external data needed.

Signal hierarchy (identical to sc_judgment_ingester._infer_domain_from_text):
    Criminal       — "CRIMINAL APPELLATE JURISDICTION", "CRIMINAL APPEAL NO", etc.
    Constitutional — "ORIGINAL JURISDICTION", "WRIT PETITION", "ARTICLE 32", etc.
    Civil (default)— everything else: property, service, family, commercial

Because some PDFs were ingested before the cleaner stripped jurisdictional
headers, the chunk_index=0 text may or may not contain those headers.
The function is robust to both cases.

Safe to run multiple times — skips rows that already have a non-null legal_domain.
Use --retag to force-retag everything (useful if the mapping logic changes).

Run on the Lightning AI server:
    cd /teamspace/studios/this_studio/Phase2
    python scripts/tag_sc_judgment_domains.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse the same inference logic from the ingester for consistency
from backend.preprocessing.sc_judgment_ingester import _infer_domain_from_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tag_domains")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(retag: bool = False) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

    # --- Connections ---
    async_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
    )
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    engine = create_engine(sync_url, echo=False, pool_size=2)
    Session = sessionmaker(bind=engine)

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    qdrant_key = os.environ.get("QDRANT_API_KEY") or None
    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key)

    with Session() as session:
        # Fetch diary_nos that need tagging
        if retag:
            rows = session.execute(text(
                "SELECT diary_no FROM ingested_judgments ORDER BY diary_no"
            )).fetchall()
            logger.info("--retag mode: processing all %d judgments", len(rows))
        else:
            rows = session.execute(text(
                "SELECT diary_no FROM ingested_judgments "
                "WHERE legal_domain IS NULL ORDER BY diary_no"
            )).fetchall()
            logger.info("Found %d judgments with NULL legal_domain", len(rows))

        if not rows:
            logger.info("Nothing to tag. Use --retag to force re-tag all.")
            return

        all_diary_nos = [r.diary_no for r in rows]

        # ---------------------------------------------------------------------------
        # Step 1: Fetch chunk_index=0 for each diary_no from Qdrant
        # We infer domain from the opening text of each judgment.
        # ---------------------------------------------------------------------------
        logger.info(
            "Fetching chunk_index=0 from Qdrant for %d diary_nos...", len(all_diary_nos)
        )

        domain_lookup: dict[str, str] = {}   # diary_no → domain
        domain_counts: dict[str, int] = {"civil": 0, "criminal": 0, "constitutional": 0}

        # Process in batches (Qdrant MatchAny supports up to ~1000 values)
        BATCH = 500
        for batch_start in range(0, len(all_diary_nos), BATCH):
            batch_diary_nos = all_diary_nos[batch_start: batch_start + BATCH]

            # Scroll chunk_index=0 points for this batch of diary_nos
            offset = None
            while True:
                results, offset = qdrant.scroll(
                    collection_name="sc_judgments",
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="chunk_index",
                                match=MatchValue(value=0),
                            ),
                            FieldCondition(
                                key="diary_no",
                                match=MatchAny(any=batch_diary_nos),
                            ),
                        ]
                    ),
                    limit=500,
                    offset=offset,
                    with_payload=["diary_no", "text"],
                    with_vectors=False,
                )

                for point in results:
                    payload = point.payload or {}
                    diary_no = payload.get("diary_no")
                    chunk_text = payload.get("text", "")
                    if diary_no and chunk_text:
                        domain = _infer_domain_from_text(chunk_text[:3000])
                        domain_lookup[diary_no] = domain
                        domain_counts[domain] += 1

                if offset is None:
                    break

        logger.info(
            "Domain inference complete: %d / %d diary_nos matched in Qdrant",
            len(domain_lookup), len(all_diary_nos),
        )

        # Diary_nos not found in Qdrant (chunk_index=0 missing) → default civil
        missing_in_qdrant = [d for d in all_diary_nos if d not in domain_lookup]
        if missing_in_qdrant:
            logger.warning(
                "%d diary_nos had no chunk_index=0 in Qdrant — defaulting to 'civil'",
                len(missing_in_qdrant),
            )
            for d in missing_in_qdrant:
                domain_lookup[d] = "civil"
                domain_counts["civil"] += 1

        print(f"\nDomain inference results (from chunk_index=0 opening text):")
        for d, cnt in sorted(domain_counts.items(), key=lambda x: -x[1]):
            pct = cnt / len(all_diary_nos) * 100
            print(f"  {d:<20} {cnt:>6,}  ({pct:.1f}%)")

        # Show a sample of each domain for sanity-check
        print("\nSample tagging (first 3 per domain):")
        shown: dict[str, int] = {"civil": 0, "criminal": 0, "constitutional": 0}
        for diary_no, domain in domain_lookup.items():
            if shown.get(domain, 0) < 3:
                print(f"  [{domain:<15}] diary_no={diary_no}")
                shown[domain] = shown.get(domain, 0) + 1
            if all(v >= 3 for v in shown.values()):
                break

        # ---------------------------------------------------------------------------
        # Step 2: Update PostgreSQL
        # ---------------------------------------------------------------------------
        logger.info("Updating PostgreSQL ingested_judgments.legal_domain...")
        updated_pg = 0
        for diary_no, domain in domain_lookup.items():
            session.execute(text("""
                UPDATE ingested_judgments
                SET legal_domain = :domain
                WHERE diary_no = :diary_no
            """), {"domain": domain, "diary_no": diary_no})
            updated_pg += 1
        session.commit()
        logger.info("PostgreSQL: updated %d rows", updated_pg)

        # ---------------------------------------------------------------------------
        # Step 3: Update ALL Qdrant chunks for tagged diary_nos
        # ---------------------------------------------------------------------------
        logger.info("Updating Qdrant sc_judgments payload legal_domain field...")
        SCROLL_LIMIT = 500
        total_qdrant_updated = 0
        offset = None

        while True:
            results, offset = qdrant.scroll(
                collection_name="sc_judgments",
                scroll_filter=None,
                limit=SCROLL_LIMIT,
                offset=offset,
                with_payload=["diary_no"],
                with_vectors=False,
            )

            if not results:
                break

            # Group point IDs by domain
            domain_point_ids: dict[str, list] = {
                "civil": [], "criminal": [], "constitutional": []
            }
            for point in results:
                diary_no = (point.payload or {}).get("diary_no")
                if diary_no and diary_no in domain_lookup:
                    domain = domain_lookup[diary_no]
                    domain_point_ids[domain].append(point.id)

            # Update Qdrant payloads in sub-batches of 100
            for domain, point_ids in domain_point_ids.items():
                for j in range(0, len(point_ids), 100):
                    sub_batch = point_ids[j: j + 100]
                    if not sub_batch:
                        continue
                    qdrant.set_payload(
                        collection_name="sc_judgments",
                        payload={"legal_domain": domain},
                        points=sub_batch,
                    )
                    total_qdrant_updated += len(sub_batch)

            logger.info(
                "Qdrant scroll progress: %d chunks updated so far", total_qdrant_updated
            )

            if offset is None:
                break

    print(f"\n{'='*60}")
    print("DOMAIN TAGGING COMPLETE")
    print(f"{'='*60}")
    print(f"  PostgreSQL rows updated: {updated_pg:,}")
    print(f"  Qdrant chunks updated:   {total_qdrant_updated:,}")
    print(f"  Domain breakdown:")
    for d, cnt in sorted(domain_counts.items(), key=lambda x: -x[1]):
        pct = cnt / len(all_diary_nos) * 100
        print(f"    {d:<20} {cnt:>6,}  ({pct:.1f}%)")
    print(f"\n  Source: chunk_index=0 opening text from Qdrant (actual PDF content)")

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Tag sc_judgments legal_domain from opening chunk text in Qdrant"
    )
    parser.add_argument(
        "--retag", action="store_true",
        help="Re-tag all judgments, not just NULL ones"
    )
    args = parser.parse_args()
    main(retag=args.retag)
