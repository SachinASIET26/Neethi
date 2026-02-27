"""CLI runner for Phase 3 Qdrant indexing.

IMPORTANT: load_dotenv() MUST be called before any backend imports.
DATABASE_URL is read at module import time by SQLAlchemy — if dotenv is
loaded after the import, the connection will fail against localhost.

Usage:
    # Create collections (one-time setup)
    python data/scripts/run_indexing.py --mode setup

    # Index a single act
    python data/scripts/run_indexing.py --act BNS_2023
    python data/scripts/run_indexing.py --act BNSS_2023
    python data/scripts/run_indexing.py --act BSA_2023

    # Index all three acts
    python data/scripts/run_indexing.py --act ALL

    # Index transition context (Phase 3B)
    python data/scripts/run_indexing.py --mode transition

    # Combined: setup + all acts + transition
    python data/scripts/run_indexing.py --mode all
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Resolve project root and load .env BEFORE any backend imports
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# 2. Now safe to import backend modules
# ---------------------------------------------------------------------------
import structlog  # noqa: E402

from backend.db.database import AsyncSessionLocal  # noqa: E402
from backend.db.repositories.section_repository import SectionRepository  # noqa: E402
from backend.rag.qdrant_setup import (  # noqa: E402
    create_all_collections,
    get_qdrant_client,
    verify_collections,
)
from backend.rag.embeddings import BGEM3Embedder  # noqa: E402
from backend.rag.indexer import LegalIndexer  # noqa: E402
from backend.rag.transition_indexer import TransitionIndexer  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_ACTS = [
    # Criminal codes
    "BNS_2023", "BNSS_2023", "BSA_2023",
    # Civil statutes
    "ICA_1872", "SRA_1963", "TPA_1882", "LA_1963",
    "ACA_1996", "CPA_2019", "HMA_1955", "HSA_1956", "CPC_1908",
]
_AUDIT_DIR = _PROJECT_ROOT / "data" / "audit"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_report(report_dict: dict, filename: str) -> None:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _AUDIT_DIR / filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, default=str)
    logger.info("report_saved: %s", out_path)


def _run_setup(client) -> None:
    logger.info("=== PHASE 3: Collection Setup ===")
    create_all_collections(client)
    status = verify_collections(client)
    for name, info in status.items():
        logger.info(
            "  collection=%-30s exists=%-5s points=%d",
            name, info["exists"], info.get("points_count", 0),
        )
    logger.info("Setup complete.")


async def _run_index_act(act_code: str, client, embedder: BGEM3Embedder, batch_size: int = 32) -> dict:
    logger.info("=== Indexing act: %s ===", act_code)
    async with AsyncSessionLocal() as session:
        repo = SectionRepository(session)
        indexer = LegalIndexer(qdrant_client=client, embedder=embedder, repo=repo, batch_size=batch_size)
        report = await indexer.index_act(act_code)
        await session.commit()

    report_dict = {
        "act_code": report.act_code,
        "sections_eligible": report.sections_eligible,
        "sections_indexed": report.sections_indexed,
        "section_points_created": report.section_points_created,
        "sub_sections_indexed": report.sub_sections_indexed,
        "errors": report.errors,
        "error_details": report.error_details,
        "duration_seconds": round(report.duration_seconds, 2),
    }

    print("\n" + "=" * 60)
    print(f"  Act:                  {report.act_code}")
    print(f"  Sections eligible:    {report.sections_eligible}")
    print(f"  Sections indexed:     {report.sections_indexed}")
    print(f"  Section points (Qdrant): {report.section_points_created}")
    print(f"  Sub-sections indexed: {report.sub_sections_indexed}")
    print(f"  Errors:               {report.errors}")
    if report.error_details:
        print(f"  Error details:")
        for d in report.error_details:
            print(f"    - {d}")
    print(f"  Duration:             {report.duration_seconds:.1f}s")
    print("=" * 60 + "\n")

    return report_dict


async def _run_transition(client, embedder: BGEM3Embedder, batch_size: int = 32) -> dict:
    logger.info("=== Phase 3B: Transition Context Indexing ===")
    async with AsyncSessionLocal() as session:
        indexer = TransitionIndexer(
            session=session, qdrant_client=client, embedder=embedder, batch_size=batch_size
        )
        report = await indexer.index_all_active()

    report_dict = {
        "mappings_found": report.mappings_found,
        "mappings_indexed": report.mappings_indexed,
        "errors": report.errors,
        "error_details": report.error_details,
        "duration_seconds": round(report.duration_seconds, 2),
    }

    print("\n" + "=" * 60)
    print(f"  Mappings found:   {report.mappings_found}")
    print(f"  Mappings indexed: {report.mappings_indexed}")
    print(f"  Errors:           {report.errors}")
    print(f"  Duration:         {report.duration_seconds:.1f}s")
    print("=" * 60 + "\n")

    return report_dict


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run_all_async(
    acts_to_index: list,
    run_transition: bool,
    client,
    embedder: BGEM3Embedder,
    batch_size: int,
) -> dict:
    """Single async entry point for all embedding work.

    All act indexing and transition indexing happen inside ONE asyncio.run() call.
    This prevents the asyncpg pool from referencing a destroyed event loop, which
    is the cause of 'RuntimeError: Event loop is closed' when asyncio.run() is
    called multiple times in a loop.
    """
    all_reports = {}

    for act in acts_to_index:
        report = await _run_index_act(act, client, embedder, batch_size)
        all_reports[act] = report
        _save_report(report, f"indexing_report_{act}.json")

    if run_transition:
        t_report = await _run_transition(client, embedder, batch_size)
        all_reports["transition"] = t_report
        _save_report(t_report, "indexing_report_transition.json")

    return all_reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3 Qdrant indexing for Neethi AI"
    )
    parser.add_argument(
        "--act",
        choices=[
            "BNS_2023", "BNSS_2023", "BSA_2023",
            "ICA_1872", "SRA_1963", "TPA_1882", "LA_1963",
            "ACA_1996", "CPA_2019", "HMA_1955", "HSA_1956", "CPC_1908",
            "ALL",
        ],
        help="Act to index. Use ALL for all acts.",
    )
    parser.add_argument(
        "--mode",
        choices=["setup", "transition", "all"],
        help="setup=create collections, transition=Phase 3B, all=setup+acts+transition",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help=(
            "BGE-M3 encoding batch size. Default 32 works on T4 (16GB). "
            "Reduce to 16 if you get CUDA OOM errors."
        ),
    )
    args = parser.parse_args()

    if not args.act and not args.mode:
        parser.print_help()
        sys.exit(1)

    client = get_qdrant_client()

    # Setup (always safe to run multiple times)
    if args.mode in ("setup", "all") or args.act:
        _run_setup(client)

    # Load embedder (expensive — load once)
    embedder = None
    needs_embedding = args.act or args.mode in ("transition", "all")
    if needs_embedding:
        logger.info("Loading BGE-M3 embedder (this may take 30-60s on T4)...")
        embedder = BGEM3Embedder()
        batch_size = args.batch_size
        logger.info("Using batch_size=%d (reduce to 16 if CUDA OOM occurs)", batch_size)

    # Determine what to run
    acts_to_index = []
    if args.act:
        acts_to_index = ALL_ACTS if args.act == "ALL" else [args.act]
    run_transition = args.mode in ("transition", "all")

    all_reports = {}

    # Single asyncio.run() call covers all acts + transition in sequence.
    # Multiple asyncio.run() calls would destroy the event loop between calls,
    # causing asyncpg to raise 'RuntimeError: Event loop is closed' on the second act.
    if acts_to_index or run_transition:
        all_reports = asyncio.run(
            _run_all_async(acts_to_index, run_transition, client, embedder, batch_size)
        )

    if all_reports:
        _save_report(all_reports, "indexing_report_combined.json")

    # Final verification
    logger.info("=== Final Collection Status ===")
    status = verify_collections(client)
    for name, info in status.items():
        logger.info(
            "  %-35s exists=%-5s points=%d",
            name, info["exists"], info.get("points_count", 0),
        )

    logger.info("Indexing run complete.")


if __name__ == "__main__":
    main()
