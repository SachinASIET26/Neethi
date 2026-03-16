#!/usr/bin/env python3
"""
Integration test to verify the successful population of old act texts
in the `law_transition_mappings` table.

Runs automatically after the population script in CI/CD or local dev
to guarantee data integrity, quality, and idempotency.

Usage:
    python scripts/verify_old_act_ingestion.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, func
from backend.db.models.legal_foundation import LawTransitionMapping

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]  %(message)s",
)
logger = logging.getLogger("verify_ingestion")


async def run_tests() -> bool:
    """Run all verification tests. Returns True if all pass."""
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable not set.")
        return False

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    all_passed = True

    async with SessionFactory() as session:
        # ── Test A: Data Integrity (Minimum Row Counts) ──────────────────────
        logger.info("=" * 55)
        logger.info("Test A — Data Integrity (Minimum Row Counts)")
        logger.info("=" * 55)

        expected_minimums = {
            "IPC_1860": 480,   # Expected >= 480 out of 511
            "CrPC_1973": 450,  # Expected >= 450
            "IEA_1872": 140,   # Expected >= 140
        }

        for act_code, min_count in expected_minimums.items():
            result = await session.execute(
                select(func.count(LawTransitionMapping.id)).where(
                    LawTransitionMapping.old_act == act_code,
                    LawTransitionMapping.old_legal_text.is_not(None),
                )
            )
            count = result.scalar_one()

            if count >= min_count:
                logger.info(
                    "  ✅ PASS  %s: %d rows with old_legal_text (expected >= %d)",
                    act_code, count, min_count,
                )
            else:
                logger.error(
                    "  ❌ FAIL  %s: only %d rows with old_legal_text (expected >= %d)",
                    act_code, count, min_count,
                )
                all_passed = False

        # ── Test B: Data Quality ────────────────────────────────────────────
        logger.info("=" * 55)
        logger.info("Test B — Data Quality (IPC 302 content check)")
        logger.info("=" * 55)

        result = await session.execute(
            select(LawTransitionMapping.old_legal_text).where(
                LawTransitionMapping.old_act == "IPC_1860",
                LawTransitionMapping.old_section == "302",
            ).limit(1)
        )
        row = result.scalar_one_or_none()

        if row is None:
            logger.error("  ❌ FAIL  IPC 302 row not found in law_transition_mappings.")
            all_passed = False
        elif "death" in row.lower() or "imprisonment for life" in row.lower():
            logger.info("  ✅ PASS  IPC 302 text contains expected legal language.")
            logger.info("  Preview: %s", row[:120])
        else:
            logger.error(
                "  ❌ FAIL  IPC 302 text does not contain 'death' or "
                "'imprisonment for life'.\n  Got: %s",
                row[:200],
            )
            all_passed = False

        # ── Test C: Idempotency / No Empty Strings ──────────────────────────
        logger.info("=" * 55)
        logger.info("Test C — Idempotency (no empty string values)")
        logger.info("=" * 55)

        result = await session.execute(
            select(func.count(LawTransitionMapping.id)).where(
                LawTransitionMapping.old_legal_text == ""
            )
        )
        empty_count = result.scalar_one()

        if empty_count == 0:
            logger.info("  ✅ PASS  No rows have old_legal_text = '' (empty string).")
        else:
            logger.error(
                "  ❌ FAIL  %d rows have old_legal_text = '' (empty string). "
                "Safety guard in populate script may not have fired correctly.",
                empty_count,
            )
            all_passed = False

    await engine.dispose()
    return all_passed


if __name__ == "__main__":
    logger.info("Starting old act ingestion verification...")
    passed = asyncio.run(run_tests())
    logger.info("=" * 55)
    if passed:
        logger.info("✅ ALL TESTS PASSED — ingestion verified.")
        sys.exit(0)
    else:
        logger.error("❌ ONE OR MORE TESTS FAILED — check output above.")
        sys.exit(1)
