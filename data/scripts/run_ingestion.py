#!/usr/bin/env python3
"""CLI runner for the Neethi AI legal ingestion pipeline.

Triggers ingestion for one act at a time.

Usage examples:
    python data/scripts/run_ingestion.py --act BNS
    python data/scripts/run_ingestion.py --act BNS --pdf data/raw/acts/BNS.pdf --json bns_complete.json
    python data/scripts/run_ingestion.py --act BNSS --act-code BNSS_2023
    python data/scripts/run_ingestion.py --act ALL   # ingest all three acts

Output: structured ingestion report printed to stdout.

Environment variables required:
    DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env BEFORE any backend imports — DATABASE_URL is read at module import time
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(_PROJECT_ROOT / ".env")

from backend.db.database import AsyncSessionLocal
from backend.preprocessing.pipeline import IngestionReport, LegalIngestionPipeline

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_ingestion")


# ---------------------------------------------------------------------------
# Act configuration
# ---------------------------------------------------------------------------

_ACT_CONFIG = {
    # --- Naveen Sanhitas (2023 criminal codes) ---
    "BNS": {
        "act_code": "BNS_2023",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "BNS.pdf",
        "default_json": _PROJECT_ROOT / "bns_complete.json",
    },
    "BNSS": {
        "act_code": "BNSS_2023",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "BNSS.pdf",
        "default_json": _PROJECT_ROOT / "bnss_complete.json",
    },
    "BSA": {
        "act_code": "BSA_2023",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "BSA.pdf",
        "default_json": _PROJECT_ROOT / "bsa_complete.json",
    },
    # --- Civil statutes (India Code PDFs) ---
    "ICA": {
        "act_code": "ICA_1872",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "ICA1872.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "ICA.json",
    },
    "SRA": {
        "act_code": "SRA_1963",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "SRA1963.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "SRA.json",
    },
    "TPA": {
        "act_code": "TPA_1882",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "TPA1882.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "TPA.json",
    },
    "LA": {
        "act_code": "LA_1963",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "LA 1963.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "LA.json",
    },
    "ACA": {
        "act_code": "ACA_1996",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "ACA 1996.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "ACA.json",
    },
    "CPA": {
        "act_code": "CPA_2019",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "CPA2019.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "CPA.json",
    },
    "HMA": {
        "act_code": "HMA_1955",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "HMA1955.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "HMA.json",
    },
    "HSA": {
        "act_code": "HSA_1956",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "HSA1956.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "HSA.json",
    },
    "CPC": {
        "act_code": "CPC_1908",
        "default_pdf": _PROJECT_ROOT / "data" / "raw" / "acts" / "CPC1908.pdf",
        "default_json": _PROJECT_ROOT / "data" / "raw" / "acts" / "CPC.json",
    },
}


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _print_report(report: IngestionReport) -> None:
    """Print a human-readable ingestion report."""
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  INGESTION REPORT — {report.act_code}")
    print(sep)
    print(f"  Duration             : {report.duration_seconds:.1f}s")
    print(f"  Sections found (PDF) : {report.total_sections_found}")
    print(f"  Sections inserted    : {report.sections_inserted}")
    print(f"  Sub-sections inserted: {report.sub_sections_inserted}")
    print(f"  Transition mappings  : {report.transition_mappings_created}")
    print(f"  Audit records        : {report.audit_records_written}")
    print(f"  --- Quality Gate ---")
    print(f"  Skipped (conf < 0.5) : {report.sections_skipped_low_confidence}")
    print(f"  Queued for review    : {report.review_queue_entries}")
    print(f"    (0.5 <= conf < 0.7): {report.sections_queued_for_review}")
    print(f"  --- Errors ---")
    if report.errors:
        for e in report.errors:
            print(f"  [ERROR] {e}")
    else:
        print("  None")
    if report.low_confidence_sections:
        print(f"\n  Low-confidence sections (conf < 0.5) skipped:")
        for s in report.low_confidence_sections:
            print(f"    - {report.act_code} Section {s}")
    print(sep)

    # Exit code signal
    if report.errors:
        print("\n  ⚠  Pipeline completed with errors — check logs above.")
    else:
        print("\n  ✓  Pipeline completed successfully.")
    print()


# ---------------------------------------------------------------------------
# Core async runner
# ---------------------------------------------------------------------------

async def run_ingestion(
    act_short: str,
    pdf_path: Path,
    json_path: Path,
    act_code: str,
) -> IngestionReport:
    """Run the ingestion pipeline for a single act, inside an async context."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    logger.info("Starting ingestion: act=%s pdf=%s json=%s", act_code, pdf_path, json_path)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            pipeline = LegalIngestionPipeline(session)
            report = await pipeline.ingest_act(
                act_code=act_code,
                pdf_path=pdf_path,
                json_path=json_path,
            )
    return report


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_ingestion",
        description="Neethi AI legal ingestion pipeline CLI runner.",
    )
    parser.add_argument(
        "--act",
        required=True,
        choices=["BNS", "BNSS", "BSA", "ICA", "SRA", "TPA", "LA", "ACA", "CPA", "HMA", "HSA", "CPC", "ALL"],
        help="Which act to ingest. Use ALL to ingest all acts.",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Path to the PDF file. Defaults to data/raw/acts/{ACT}.pdf.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Path to the JSON enrichment file. Defaults to {act}_complete.json in project root.",
    )
    parser.add_argument(
        "--act-code",
        default=None,
        dest="act_code_override",
        help="Override the canonical act code (e.g. BNS_2023). Normally inferred from --act.",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point. Returns exit code (0 = success, 1 = error)."""
    parser = build_parser()
    args = parser.parse_args()

    # Determine which acts to run
    if args.act == "ALL":
        acts_to_run = ["BNS", "BNSS", "BSA", "ICA", "SRA", "TPA", "LA", "ACA", "CPA", "HMA", "HSA", "CPC"]
    else:
        acts_to_run = [args.act]

    overall_success = True

    for act_short in acts_to_run:
        cfg = _ACT_CONFIG[act_short]
        act_code = args.act_code_override or cfg["act_code"]

        pdf_path: Path = args.pdf if args.pdf and len(acts_to_run) == 1 else cfg["default_pdf"]
        json_path: Path = args.json if args.json and len(acts_to_run) == 1 else cfg["default_json"]

        print(f"\nIngesting {act_short} ({act_code})")
        print(f"  PDF : {pdf_path}")
        print(f"  JSON: {json_path}")

        try:
            report = asyncio.run(
                run_ingestion(
                    act_short=act_short,
                    pdf_path=pdf_path,
                    json_path=json_path,
                    act_code=act_code,
                )
            )
        except FileNotFoundError as exc:
            logger.error("File not found: %s", exc)
            print(f"\n[ERROR] {exc}")
            overall_success = False
            continue
        except Exception as exc:
            logger.exception("Unexpected error during ingestion: %s", exc)
            print(f"\n[ERROR] Unexpected error: {exc}")
            overall_success = False
            continue

        _print_report(report)

        if report.errors:
            overall_success = False

    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
