#!/usr/bin/env python3
"""
Regenerate IPC / CrPC / IEA JSON files from PDFs using the ingestion pipeline.

This uses the existing PyMuPDF + Tesseract + act_parser pipeline — the same
cleaning logic that produced BNS/BNSS/BSA JSONs. Outputs to data/raw/.

Usage:
    python -m data.scripts.regenerate_old_act_jsons

Prerequisites:
    Place PDFs at:
        data/raw/acts/ipc_1860.pdf
        data/raw/acts/crpc_1973.pdf
        data/raw/acts/iea_1872.pdf
    Download from: https://www.indiacode.nic.in
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from backend.preprocessing.pipeline import LegalIngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("regenerate_old_act_jsons")

# ── Act configuration ────────────────────────────────────────────────────────

OLD_ACTS = [
    {
        "act_code":        "IPC_1860",
        "pdf_paths":       [
            _PROJECT_ROOT / "data/raw/acts/ipc_1860.pdf",
            _PROJECT_ROOT / "data/raw/acts/IPC.pdf",
            _PROJECT_ROOT / "data/raw/acts/ipc.pdf",
            _PROJECT_ROOT / "data/raw/acts/IPC_1860.pdf"
        ],
        "export_json":     _PROJECT_ROOT / "data/raw/ipc_complete.json",
        "expected_min":    480,   # IPC has 511 sections — expect most to extract
    },
    {
        "act_code":        "CrPC_1973",
        "pdf_paths":       [
            _PROJECT_ROOT / "data/raw/acts/crpc_1973.pdf",
            _PROJECT_ROOT / "data/raw/acts/CRPC.pdf",
            _PROJECT_ROOT / "data/raw/acts/crpc.pdf",
            _PROJECT_ROOT / "data/raw/acts/CRPC_1973.pdf"
        ],
        "export_json":     _PROJECT_ROOT / "data/raw/crpc_complete.json",
        "expected_min":    450,
    },
    {
        "act_code":        "IEA_1872",
        "pdf_paths":       [
            _PROJECT_ROOT / "data/raw/acts/iea_1872.pdf",
            _PROJECT_ROOT / "data/raw/acts/IEA.pdf",
            _PROJECT_ROOT / "data/raw/acts/iea.pdf",
            _PROJECT_ROOT / "data/raw/acts/IEA_1872.pdf"
        ],
        "export_json":     _PROJECT_ROOT / "data/raw/iea_complete.json",
        "expected_min":    155,
    },
]


async def regenerate_all() -> bool:
    """Run dry-run extraction for all three old acts. Returns True if all succeed."""
    all_passed = True

    # Dry-run does not need a DB session — pass a null session
    # Pipeline exits before any DB call when dry_run=True
    pipeline = LegalIngestionPipeline(session=None)  # type: ignore[arg-type]

    for cfg in OLD_ACTS:
        act_code    = cfg["act_code"]
        pdf_paths   = cfg["pdf_paths"]
        export_json = cfg["export_json"]
        expected    = cfg["expected_min"]
        
        # Find the first existing PDF path
        pdf_path = next((p for p in pdf_paths if p.exists()), None)

        logger.info("=" * 60)
        logger.info("Processing %s", act_code)
        
        if not pdf_path:
            logger.error(
                "PDF NOT FOUND among candidate paths: %s\n"
                "  → Upload the PDF to the acts directory and try again.",
                ", ".join(p.name for p in pdf_paths)
            )
            all_passed = False
            continue

        logger.info("  PDF  : %s", pdf_path)
        logger.info("  JSON : %s", export_json)

        try:
            report = await pipeline.ingest_act(
                act_code=act_code,
                pdf_path=pdf_path,
                json_path=None,           # no enrichment JSON for old acts
                export_json_path=export_json,
                dry_run=True,
            )

            extracted = report.total_sections_found
            logger.info(
                "%s: extracted %d sections → %s",
                act_code, extracted, export_json.name,
            )

            if extracted < expected:
                logger.warning(
                    "%s: extracted only %d sections (expected >= %d). "
                    "OCR quality may be low — check PDF.",
                    act_code, extracted, expected,
                )
                # Don't fail — partial extraction is still useful
            else:
                logger.info("%s: ✅ section count OK (%d >= %d)", act_code, extracted, expected)

        except Exception as exc:
            logger.exception("%s: FAILED — %s", act_code, exc)
            all_passed = False

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(regenerate_all())
    if not success:
        logger.error("One or more acts failed. Check output above.")
        sys.exit(1)
    logger.info("All acts extracted successfully. Run populate_old_act_texts.py next.")
    sys.exit(0)
