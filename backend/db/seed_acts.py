"""One-time seed script: inserts the six core Indian legal acts into the acts table.

Run once after applying the Alembic migration:

    python -m backend.db.seed_acts

Acts seeded:
    BNS_2023   — Bharatiya Nyaya Sanhita, 2023         (active, replaces IPC)
    BNSS_2023  — Bharatiya Nagarik Suraksha Sanhita, 2023 (active, replaces CrPC)
    BSA_2023   — Bharatiya Sakshya Adhiniyam, 2023     (active, replaces IEA)
    IPC_1860   — Indian Penal Code, 1860               (repealed 2024-06-30)
    CrPC_1973  — Code of Criminal Procedure, 1973      (repealed 2024-06-30)
    IEA_1872   — Indian Evidence Act, 1872             (repealed 2024-06-30)

All values here are sourced from official Government of India documents.
Do NOT alter act_code values — they are used as foreign keys throughout the system.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data — authoritative values from India Code / Government of India
# ---------------------------------------------------------------------------

ACTS_SEED: list[dict] = [
    # -----------------------------------------------------------------------
    # New Sanhitas (active as of July 1, 2024)
    # -----------------------------------------------------------------------
    {
        "act_code": "BNS_2023",
        "act_name": "Bharatiya Nyaya Sanhita, 2023",
        "act_name_hindi": "भारतीय न्याय संहिता, 2023",
        "short_name": "BNS",
        "act_number": 45,
        "year": 2023,
        "effective_date": date(2024, 7, 1),
        "repealed_date": None,
        "status": "active",
        "era": "naveen_sanhitas",
        "domain": "criminal_substantive",
        "replaces_act_code": "IPC_1860",
        "total_sections": 358,
        "total_chapters": 20,
        "gazette_reference": "Act No. 45 of 2023, Gazette of India Extraordinary",
        "source_url": "https://indiacode.nic.in/handle/123456789/20062",
    },
    {
        "act_code": "BNSS_2023",
        "act_name": "Bharatiya Nagarik Suraksha Sanhita, 2023",
        "act_name_hindi": "भारतीय नागरिक सुरक्षा संहिता, 2023",
        "short_name": "BNSS",
        "act_number": 46,
        "year": 2023,
        "effective_date": date(2024, 7, 1),
        "repealed_date": None,
        "status": "active",
        "era": "naveen_sanhitas",
        "domain": "criminal_procedure",
        "replaces_act_code": "CrPC_1973",
        "total_sections": 531,
        "total_chapters": 39,
        "gazette_reference": "Act No. 46 of 2023, Gazette of India Extraordinary",
        "source_url": "https://indiacode.nic.in/handle/123456789/20063",
    },
    {
        "act_code": "BSA_2023",
        "act_name": "Bharatiya Sakshya Adhiniyam, 2023",
        "act_name_hindi": "भारतीय साक्ष्य अधिनियम, 2023",
        "short_name": "BSA",
        "act_number": 47,
        "year": 2023,
        "effective_date": date(2024, 7, 1),
        "repealed_date": None,
        "status": "active",
        "era": "naveen_sanhitas",
        "domain": "evidence",
        "replaces_act_code": "IEA_1872",
        "total_sections": 170,
        "total_chapters": 12,
        "gazette_reference": "Act No. 47 of 2023, Gazette of India Extraordinary",
        "source_url": "https://indiacode.nic.in/handle/123456789/20064",
    },
    # -----------------------------------------------------------------------
    # Colonial codes (repealed July 1, 2024)
    # Must be inserted BEFORE the new Sanhitas to allow replaces_act_code FK.
    # The insert order in this list matters — old acts first.
    # -----------------------------------------------------------------------
    {
        "act_code": "IPC_1860",
        "act_name": "Indian Penal Code, 1860",
        "act_name_hindi": None,
        "short_name": "IPC",
        "act_number": None,
        "year": 1860,
        "effective_date": date(1860, 1, 6),
        "repealed_date": date(2024, 6, 30),
        "status": "repealed",
        "era": "colonial_codes",
        "domain": "criminal_substantive",
        "replaces_act_code": None,
        "total_sections": 511,
        "total_chapters": 23,
        "gazette_reference": "Act No. 45 of 1860",
        "source_url": "https://indiacode.nic.in/handle/123456789/2263",
    },
    {
        "act_code": "CrPC_1973",
        "act_name": "Code of Criminal Procedure, 1973",
        "act_name_hindi": None,
        "short_name": "CrPC",
        "act_number": None,
        "year": 1973,
        "effective_date": date(1974, 4, 1),
        "repealed_date": date(2024, 6, 30),
        "status": "repealed",
        "era": "colonial_codes",
        "domain": "criminal_procedure",
        "replaces_act_code": None,
        "total_sections": 484,
        "total_chapters": 37,
        "gazette_reference": "Act No. 2 of 1974",
        "source_url": "https://indiacode.nic.in/handle/123456789/1611",
    },
    {
        "act_code": "IEA_1872",
        "act_name": "Indian Evidence Act, 1872",
        "act_name_hindi": None,
        "short_name": "IEA",
        "act_number": None,
        "year": 1872,
        "effective_date": date(1872, 3, 15),
        "repealed_date": date(2024, 6, 30),
        "status": "repealed",
        "era": "colonial_codes",
        "domain": "evidence",
        "replaces_act_code": None,
        "total_sections": 167,
        "total_chapters": 11,
        "gazette_reference": "Act No. 1 of 1872",
        "source_url": "https://indiacode.nic.in/handle/123456789/1316",
    },
]

# Insertion order: old acts first (no self-referencing FK yet), then new acts
INSERT_ORDER = [
    "IPC_1860",
    "CrPC_1973",
    "IEA_1872",
    "BNS_2023",
    "BNSS_2023",
    "BSA_2023",
]


async def seed_acts() -> None:
    """Insert the six core acts into the database, skipping any that already exist."""
    acts_by_code = {a["act_code"]: a for a in ACTS_SEED}
    ordered = [acts_by_code[code] for code in INSERT_ORDER]

    async with AsyncSessionLocal() as session:
        inserted = 0
        skipped = 0

        for act_data in ordered:
            # Check if already exists to make this script idempotent
            from sqlalchemy import text as _text
            result = await session.execute(
                _text("SELECT 1 FROM acts WHERE act_code = :code").bindparams(code=act_data["act_code"])
            )
            exists = result.scalar()

            if exists:
                logger.info("Skipping %s — already present.", act_data["act_code"])
                skipped += 1
                continue

            stmt = (
                insert(__import__(
                    "backend.db.models.legal_foundation", fromlist=["Act"]
                ).Act.__table__)
                .values(**act_data)
                .on_conflict_do_nothing(index_elements=["act_code"])
            )
            await session.execute(stmt)
            inserted += 1
            logger.info("Inserted: %s", act_data["act_code"])

        await session.commit()
        logger.info(
            "Seed complete — inserted: %d, skipped (already existed): %d",
            inserted,
            skipped,
        )


async def verify_seed() -> bool:
    """Verify all six acts exist with correct values. Returns True if all pass."""
    from backend.db.models.legal_foundation import Act
    from sqlalchemy import select

    expected = {a["act_code"] for a in ACTS_SEED}
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Act.act_code, Act.status, Act.era))
        rows = result.all()
        found = {r.act_code for r in rows}

        missing = expected - found
        if missing:
            logger.error("Missing acts: %s", missing)
            return False

        for row in rows:
            if row.act_code in {"BNS_2023", "BNSS_2023", "BSA_2023"}:
                assert row.status == "active", f"{row.act_code} should be active"
                assert row.era == "naveen_sanhitas", f"{row.act_code} era wrong"
            else:
                assert row.status == "repealed", f"{row.act_code} should be repealed"
                assert row.era == "colonial_codes", f"{row.act_code} era wrong"

        logger.info("Verification passed — all 6 acts present with correct status/era.")
        return True


if __name__ == "__main__":
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    async def main() -> None:
        from backend.db.database import health_check

        if not await health_check():
            logger.error(
                "Database unreachable. Check DATABASE_URL in your .env file."
            )
            raise SystemExit(1)

        await seed_acts()
        ok = await verify_seed()
        if not ok:
            raise SystemExit(1)
        print("\n✓ All 6 acts seeded and verified successfully.")

    asyncio.run(main())
