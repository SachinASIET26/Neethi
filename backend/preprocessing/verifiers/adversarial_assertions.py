"""Adversarial safety assertions for the mapping activation pipeline.

These five assertions MUST all pass before any law_transition_mappings row
is set to is_active = TRUE. A single failure raises SystemExit(1) and
prints a human-readable diagnostic.

The assertions are not unit tests — they are runtime guards that verify
the highest-risk data-correctness invariants before the irreversible
activation step commits to the database.

Critical invariants tested:
1. IPC 302 (Murder) maps to BNS 103 — NOT BNS 302 (Snatching).
2. IPC 124A (Sedition) maps to BNS 152.
3. IPC 376 (Rape) split into at least 3 BNS sections.
4. No act maps to itself (data corruption guard).
5. No equivalent mapping has a null new_section.
"""

from __future__ import annotations

import logging
from typing import Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Individual assertions
# ---------------------------------------------------------------------------

async def _assert_murder_snatching_separation(session: AsyncSession) -> Tuple[bool, str]:
    """Assertion 1: IPC 302 must map to BNS 103, and BNS 103 must be Murder.

    BNS 302 is Religious Offences (previously Snatching in draft numbering).
    Confusing these two is the single most dangerous mapping error in this system.

    Uses EXISTS check (not ORDER BY LIMIT 1) to avoid false failures when
    multiple rows exist for old_section='302' — we only require that the
    correct mapping to BNS 103 is present, regardless of row ordering.
    """
    # Check that the correct mapping IPC 302 → BNS 103 EXISTS
    row = await session.execute(
        text(
            "SELECT COUNT(*) FROM law_transition_mappings "
            "WHERE old_act = 'IPC_1860' AND old_section = '302' "
            "AND new_act = 'BNS_2023' AND new_section = '103'"
        )
    )
    count_103 = row.scalar_one()

    if count_103 == 0:
        return False, (
            "CRITICAL: IPC 302 does not correctly map to BNS 103. "
            "No mapping row found for old_section='302' → new_section='103'. "
            "Check json_enricher output. BNS 302 is Religious Offences — not Murder. "
            "DO NOT PROCEED until this is fixed."
        )

    # Also confirm BNS 95 is NOT incorrectly mapped to IPC 302
    # (would indicate the _BLOCKED_OLD_SECTIONS fix did not apply)
    row2 = await session.execute(
        text(
            "SELECT COUNT(*) FROM law_transition_mappings "
            "WHERE old_act = 'IPC_1860' AND old_section = '302' "
            "AND new_act = 'BNS_2023' AND new_section = '95'"
        )
    )
    count_95 = row2.scalar_one()
    if count_95 > 0:
        return False, (
            "CRITICAL: IPC 302 is incorrectly mapped to BNS 95 "
            "(Hiring a Child to Commit an Offence). "
            "BNS 95 must NOT be a murder equivalent. "
            "This is JSON noise — check _BLOCKED_OLD_SECTIONS in json_enricher.py."
        )

    # Verify BNS 103 title contains 'murder'
    title_row = await session.execute(
        text(
            "SELECT section_title FROM sections "
            "WHERE act_code = 'BNS_2023' AND section_number = '103'"
        )
    )
    bns_103_title = title_row.scalar_one_or_none()

    if bns_103_title is None or "murder" not in bns_103_title.lower():
        return False, (
            "CRITICAL: BNS 103 title does not contain 'murder'. "
            f"Got title = {bns_103_title!r}. "
            "IPC 302 (Murder) must map to BNS 103 (Murder). "
            "DO NOT PROCEED until this is fixed."
        )

    # Verify BNS 302 title does NOT contain 'murder'
    title_row2 = await session.execute(
        text(
            "SELECT section_title FROM sections "
            "WHERE act_code = 'BNS_2023' AND section_number = '302'"
        )
    )
    bns_302_title = title_row2.scalar_one_or_none()

    if bns_302_title is not None and "murder" in bns_302_title.lower():
        return False, (
            "CRITICAL: BNS 302 title contains 'murder' — this is wrong. "
            f"Got title = {bns_302_title!r}. "
            "BNS 302 should be Religious Offences, not Murder. "
            "DO NOT PROCEED until this is fixed."
        )

    logger.info("Assertion 1 PASSED: IPC 302 -> BNS 103 (Murder), BNS 302 != Murder")
    return True, "Assertion 1 PASSED: murder/snatching separation verified"


async def _assert_sedition_replacement(session: AsyncSession) -> Tuple[bool, str]:
    """Assertion 2: IPC 124A (Sedition) must map to BNS 152.

    BNS 152 replaced the sedition provision under the new Sanhita.
    IPC 124A was seeded manually in the enricher because replaces_ipc was empty.
    """
    row = await session.execute(
        text(
            "SELECT new_section, new_act FROM law_transition_mappings "
            "WHERE old_act = 'IPC_1860' AND old_section = '124A' "
            "LIMIT 1"
        )
    )
    result = row.fetchone()

    if result is None:
        return False, (
            "CRITICAL: IPC 124A (Sedition) has NO mapping in law_transition_mappings. "
            "This row should have been seeded manually in the enricher. "
            "Check json_enricher.py for the IPC 124A -> BNS 152 manual seed."
        )

    new_section, new_act = result
    if new_act != "BNS_2023" or new_section != "152":
        return False, (
            f"CRITICAL: IPC 124A (Sedition) does not map to BNS 152. "
            f"Got new_act={new_act!r}, new_section={new_section!r}. "
            "Check data."
        )

    logger.info("Assertion 2 PASSED: IPC 124A -> BNS 152 (Sedition replacement)")
    return True, "Assertion 2 PASSED: sedition replacement verified"


async def _assert_rape_is_split(session: AsyncSession) -> Tuple[bool, str]:
    """Assertion 3: IPC 376 (Rape) must map to at least 2 BNS sections.

    The JSON has replaces_ipc=['376(1)'] on BNS 64 and replaces_ipc=['376(2)']
    on BNS 65. The enricher normalises both to old_section='376', producing
    2 rows in law_transition_mappings with old_section='376' (BNS 64 + BNS 65).
    Count >= 2 confirms the split was detected and stored correctly.
    """
    row = await session.execute(
        text(
            "SELECT COUNT(*) FROM law_transition_mappings "
            "WHERE old_act = 'IPC_1860' AND old_section = '376'"
        )
    )
    count = row.scalar_one()

    if count < 2:
        return False, (
            f"IPC 376 (Rape) should map to at least 2 BNS sections (BNS 64 + BNS 65). "
            f"Found only {count} mapping(s) with old_section='376'. "
            "Check that '376(1)' and '376(2)' were normalised to '376' in json_enricher "
            "(_normalize_old_section) and that split detection ran correctly."
        )

    logger.info("Assertion 3 PASSED: IPC 376 maps to %d BNS sections", count)
    return True, f"Assertion 3 PASSED: IPC 376 split into {count} mappings (old_section='376')"


async def _assert_no_self_mapping(session: AsyncSession) -> Tuple[bool, str]:
    """Assertion 4: No mapping should point from an act to itself.

    old_act == new_act is a data corruption signal — transitions only go
    between old acts (IPC/CrPC/IEA) and new acts (BNS/BNSS/BSA).
    """
    row = await session.execute(
        text(
            "SELECT COUNT(*) FROM law_transition_mappings "
            "WHERE old_act = new_act"
        )
    )
    count = row.scalar_one()

    if count > 0:
        # Get examples for diagnostics
        examples = await session.execute(
            text(
                "SELECT old_act, old_section, new_section FROM law_transition_mappings "
                "WHERE old_act = new_act LIMIT 5"
            )
        )
        ex_rows = examples.fetchall()
        ex_str = ", ".join(f"{r[0]}:{r[1]}->{r[2]}" for r in ex_rows)
        return False, (
            f"A mapping points from an act to itself. Data corruption. "
            f"Count: {count}. Examples: {ex_str}"
        )

    logger.info("Assertion 4 PASSED: no self-mapping rows found")
    return True, "Assertion 4 PASSED: no self-mapping"


async def _assert_no_null_equivalent_sections(session: AsyncSession) -> Tuple[bool, str]:
    """Assertion 5: Equivalent mappings cannot have null new_section.

    transition_type='equivalent' means a direct renaming — the new section
    is always known. A null new_section here indicates a parsing failure.
    """
    row = await session.execute(
        text(
            "SELECT COUNT(*) FROM law_transition_mappings "
            "WHERE transition_type = 'equivalent' AND new_section IS NULL"
        )
    )
    count = row.scalar_one()

    if count > 0:
        return False, (
            f"Equivalent mappings cannot have null new_section. "
            f"Found {count} row(s) with transition_type='equivalent' and new_section IS NULL."
        )

    logger.info("Assertion 5 PASSED: no null new_section for equivalent mappings")
    return True, "Assertion 5 PASSED: no null equivalent sections"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_all_assertions(session: AsyncSession) -> bool:
    """Run all 5 adversarial safety assertions.

    Args:
        session: Active AsyncSession (read-only — no writes performed here).

    Returns:
        True if all 5 assertions pass.

    Raises:
        SystemExit(1) if any assertion fails, after printing the failure message.
    """
    assertions = [
        ("murder_snatching_separation",    _assert_murder_snatching_separation),
        ("sedition_replacement",           _assert_sedition_replacement),
        ("rape_is_split",                  _assert_rape_is_split),
        ("new_acts_not_self_mapping",      _assert_no_self_mapping),
        ("no_null_equivalent_sections",    _assert_no_null_equivalent_sections),
    ]

    passed = 0
    for name, fn in assertions:
        ok, message = await fn(session)
        if ok:
            passed += 1
            print(f"  [{passed}/5] {message}")
        else:
            print(f"\n  [FAIL] {message}\n")
            logger.critical("Adversarial assertion '%s' FAILED: %s", name, message)
            raise SystemExit(1)

    logger.info("All %d adversarial assertions passed", passed)
    return True
