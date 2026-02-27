#!/usr/bin/env python3
"""CLI runner for Phase 2C — Zero-Cost Mapping Activation Pipeline.

Activates law_transition_mappings rows using BPR&D official authority tiers.
Must be run AFTER Phase 2 ingestion completes (all three acts in PostgreSQL).

Usage:
    python data/scripts/run_activation.py

Environment variables required:
    DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

What this script does:
  1. Runs 5 adversarial safety assertions (aborts on any failure).
  2. Sets is_active = TRUE on all inactive mappings, tiered by transition_type.
  3. Optionally runs BGE-M3 semantic similarity validation (skipped if not installed).
  4. Writes data/audit/activation_report.json.
  5. Writes data/audit/similarity_flags.json (if similarity step ran).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env BEFORE any backend imports — DATABASE_URL is read at module import time
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(_PROJECT_ROOT / ".env")

from backend.db.database import AsyncSessionLocal
from backend.preprocessing.verifiers.mapping_activator import ActivationReport, MappingActivator

# ---------------------------------------------------------------------------
# Logging — info level to stdout
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_activation")


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _print_report(report: ActivationReport) -> None:
    """Print a human-readable activation summary."""
    sep = "=" * 72
    total_activated = (
        report.tier_1_activated
        + report.tier_2_activated
        + report.tier_3_activated
        + report.tier_4_activated
        + report.tier_5_activated
    )

    print(f"\n{sep}")
    print("  ACTIVATION REPORT")
    print(sep)
    print(f"  Run timestamp        : {report.run_timestamp}")
    print(f"  Assertions passed    : {report.assertions_passed}/5")
    print(f"  Total processed      : {report.total_mappings_processed}")
    print(f"  --- Activated by Tier ---")
    print(f"  Tier 1 (equiv/same)  : {report.tier_1_activated}")
    print(f"  Tier 2 (mod/merged)  : {report.tier_2_activated}")
    print(f"  Tier 3 (new)         : {report.tier_3_activated}")
    print(f"  Tier 4 (deleted)     : {report.tier_4_activated}")
    print(f"  Tier 5 (split)       : {report.tier_5_activated}")
    print(f"  --- Results ---")
    print(f"  TOTAL ACTIVATED      : {total_activated} / {report.total_mappings_processed}")
    print(f"  Total active (DB)    : {report.total_active}")
    if report.similarity_flags > 0:
        print(f"  Similarity flags     : {report.similarity_flags} (see data/audit/similarity_flags.json)")
    else:
        print(f"  Similarity flags     : {report.similarity_flags}")
    print(f"  --- Approved By ---")
    for source, count in sorted(report.approved_by_distribution.items()):
        print(f"  {source:<40}: {count}")
    if report.errors:
        print(f"\n  --- Errors ---")
        for e in report.errors:
            print(f"  [ERROR] {e}")
    print(sep)
    print()
    print(f"  Report written to: data/audit/activation_report.json")
    if report.similarity_flags > 0:
        print(f"  Flags written to : data/audit/similarity_flags.json")
    print()

    if report.errors:
        print("  [!] Activation completed with errors.")
    else:
        print("  [OK] Activation completed successfully.")
    print()


# ---------------------------------------------------------------------------
# Async runner
# ---------------------------------------------------------------------------

async def run_activation() -> ActivationReport:
    """Run the activation pipeline inside a single async transaction."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            activator = MappingActivator(session)
            report = await activator.run_activation_pipeline()
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point. Returns 0 on success, 1 on error."""
    print("\nNeethi AI — Phase 2C Mapping Activation")
    print("Authority: BPR&D Official Comparative Document (MHA, Government of India)")
    print()

    try:
        report = asyncio.run(run_activation())
    except SystemExit:
        # Raised by adversarial assertions on failure — message already printed
        return 1
    except ValueError as exc:
        print(f"\n[ABORTED] {exc}\n")
        logger.error("Activation aborted: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error during activation: %s", exc)
        print(f"\n[ERROR] Unexpected error: {exc}\n")
        return 1

    _print_report(report)
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
