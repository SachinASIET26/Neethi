#!/usr/bin/env python3
"""
Populate old_legal_text and old_section_heading in law_transition_mappings.

Reads data/raw/ipc_complete.json, crpc_complete.json, iea_complete.json
and updates rows in law_transition_mappings where old_act matches.

Safety guarantees:
  - Skips sections where extracted text is empty (OCR failure guard)
  - Only updates rows that actually exist in the table
  - Idempotent — safe to re-run; will overwrite with same data

Usage:
    python -m data.scripts.populate_old_act_texts

Prerequisites:
    Run regenerate_old_act_jsons.py first to generate the JSON files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import update, select, func
from backend.db.models.legal_foundation import LawTransitionMapping
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("populate_old_act_texts")

SOURCE_FILES = {
    "IPC_1860":  _PROJECT_ROOT / "data/raw/ipc_complete.json",
    "CrPC_1973": _PROJECT_ROOT / "data/raw/crpc_complete.json",
    "IEA_1872":  _PROJECT_ROOT / "data/raw/iea_complete.json",
}


async def populate() -> bool:
    """Populate old_legal_text for all three old acts. Returns True if all succeed."""
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable not set.")
        return False

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    all_passed = True

    async with SessionFactory() as session:
        for act_code, filepath in SOURCE_FILES.items():
            if not filepath.exists():
                logger.error(
                    "JSON NOT FOUND: %s\n"
                    "  → Run regenerate_old_act_jsons.py first.",
                    filepath,
                )
                all_passed = False
                continue

            data = json.loads(filepath.read_text(encoding="utf-8"))
            raw_sections = data.get("sections", [])

            logger.info(
                "%s: loaded %d sections from %s",
                act_code, len(raw_sections), filepath.name,
            )

            updated = 0
            skipped_empty = 0
            skipped_no_match = 0

            for sec in raw_sections:
                section_number = str(sec.get("section_number", "")).strip()
                legal_text = (
                    sec.get("text")
                    or sec.get("legal_text")
                    or ""
                ).strip()
                title = (
                    sec.get("title")
                    or sec.get("section_title")
                    or ""
                ).strip()

                # Safety check: skip empty text (OCR failure)
                if not legal_text:
                    skipped_empty += 1
                    continue

                if not section_number:
                    continue

                result = await session.execute(
                    update(LawTransitionMapping)
                    .where(
                        LawTransitionMapping.old_act == act_code,
                        LawTransitionMapping.old_section == section_number,
                    )
                    .values(
                        old_legal_text=legal_text,
                        old_section_heading=title or None,
                    )
                )

                if result.rowcount > 0:
                    updated += result.rowcount
                else:
                    skipped_no_match += 1

            await session.commit()

            logger.info(
                "%s: ✅ updated=%d | skipped_empty=%d | no_mapping_match=%d",
                act_code, updated, skipped_empty, skipped_no_match,
            )

            if updated == 0:
                logger.warning(
                    "%s: 0 rows updated. "
                    "Check that the JSON section numbers match old_section values in DB.",
                    act_code,
                )
                all_passed = False

    await engine.dispose()
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(populate())
    if not success:
        logger.error("Population failed for one or more acts. Check output above.")
        sys.exit(1)
    logger.info("Population complete. Run verify_old_act_ingestion.py to confirm.")
    sys.exit(0)
