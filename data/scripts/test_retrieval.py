"""Test plain-English query scenarios against the PostgreSQL layer.

Shows the full pipeline:
  User plain-English query
  -> Entity extraction (simulated)
  -> SQL query
  -> Formatted result

Run:
    python data/scripts/test_retrieval.py
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from backend.db.database import AsyncSessionLocal
from sqlalchemy import text

SEP  = "=" * 72
SEP2 = "-" * 72


def wrap(txt: str | None, width: int = 65, indent: str = "    ") -> str:
    if not txt:
        return "    (none)"
    lines = []
    for para in txt.split("\n"):
        stripped = para.strip()
        if stripped:
            lines.extend(textwrap.wrap(stripped, width,
                                       initial_indent=indent,
                                       subsequent_indent=indent))
    return "\n".join(lines[:8]) + ("\n    ..." if len(lines) > 8 else "")


async def run() -> None:
    async with AsyncSessionLocal() as s:

        # ------------------------------------------------------------------ #
        # QUERY 1: Direct section lookup by number
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 1 — Direct section lookup")
        print('User says : "What does BNS Section 103 say?"')
        print("Extracted : act=BNS_2023, section_number=103")

        r = await s.execute(
            text("""
                SELECT s.section_number, s.section_title, s.legal_text,
                       s.is_cognizable, s.is_bailable,
                       s.punishment_type, s.punishment_max_years, s.triable_by,
                       c.chapter_title
                FROM sections s
                LEFT JOIN chapters c ON c.id = s.chapter_id
                WHERE s.act_code = :act AND s.section_number = :sec
            """),
            {"act": "BNS_2023", "sec": "103"},
        )
        row = r.mappings().fetchone()
        print(SEP2)
        if row:
            print(f"  Section   : BNS {row['section_number']} — {row['section_title']}")
            print(f"  Chapter   : {row['chapter_title']}")
            print(f"  Cognizable: {row['is_cognizable']}  |  Bailable: {row['is_bailable']}")
            print(f"  Punishment: {row['punishment_type']} "
                  f"(max={'life' if row['punishment_max_years'] == 99999 else str(row['punishment_max_years']) + ' yrs'})")
            print(f"  Triable by: {row['triable_by']}")
            print("  Legal text:")
            print(wrap(row["legal_text"]))
        print()

        # ------------------------------------------------------------------ #
        # QUERY 2: Old-to-new transition lookup (IPC -> BNS)
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 2 — Transition lookup (IPC -> BNS)")
        print('User says : "My client is charged under IPC 302. What is the equivalent BNS section?"')
        print("Extracted : old_act=IPC_1860, old_section=302")

        r = await s.execute(
            text("""
                SELECT m.old_section, m.old_section_title,
                       m.new_act, m.new_section, m.new_section_title,
                       m.transition_type, m.scope_change, m.confidence_score,
                       s.legal_text, s.punishment_type, s.punishment_max_years
                FROM law_transition_mappings m
                LEFT JOIN sections s
                       ON s.act_code = m.new_act AND s.section_number = m.new_section
                WHERE m.old_act = :old AND m.old_section = :sec AND m.is_active = TRUE
            """),
            {"old": "IPC_1860", "sec": "302"},
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        for row in rows:
            max_yr = "life" if row["punishment_max_years"] == 99999 else f"{row['punishment_max_years']} yrs"
            print(f"  IPC {row['old_section']} ({row['old_section_title']})")
            print(f"  -> {row['new_act']} {row['new_section']} ({row['new_section_title']})")
            print(f"     type={row['transition_type']}, scope={row['scope_change']}, "
                  f"confidence={row['confidence_score']:.2f}")
            print(f"     punishment={row['punishment_type']} (max={max_yr})")
            print("     Legal text:")
            print(wrap(row["legal_text"]))
        print()

        # ------------------------------------------------------------------ #
        # QUERY 3: Split provision — IPC 376 -> multiple BNS sections
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 3 — Split provision (IPC 376 -> multiple BNS sections)")
        print('User says : "What happened to Section 376 (Rape) under the new BNS?"')
        print("Extracted : old_act=IPC_1860, old_section=376")

        r = await s.execute(
            text("""
                SELECT m.new_section, m.new_section_title,
                       m.transition_type, m.transition_note,
                       s.punishment_type, s.punishment_max_years, s.legal_text
                FROM law_transition_mappings m
                LEFT JOIN sections s
                       ON s.act_code = m.new_act AND s.section_number = m.new_section
                WHERE m.old_act = :old AND m.old_section = :sec AND m.is_active = TRUE
                ORDER BY m.new_section::int
            """),
            {"old": "IPC_1860", "sec": "376"},
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        print(f"  IPC 376 splits into {len(rows)} BNS provision(s):")
        for row in rows:
            max_yr = "life" if row["punishment_max_years"] == 99999 else f"{row['punishment_max_years']} yrs"
            print(f"  -> BNS {row['new_section']} — {row['new_section_title']}")
            print(f"     type={row['transition_type']}, punishment={row['punishment_type']} max={max_yr}")
            print(f"     Note: {row['transition_note']}")
            print("     Text:")
            print(wrap(row["legal_text"]))
            print()

        # ------------------------------------------------------------------ #
        # QUERY 4: Keyword search across section titles + legal text
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 4 — Keyword search (cheating / fraud / dishonest)")
        print('User says : "What are the laws about cheating and fraud?"')
        print("Keywords  : cheating, fraud, dishonest")

        r = await s.execute(
            text("""
                SELECT act_code, section_number, section_title,
                       is_offence, punishment_type, punishment_max_years
                FROM sections
                WHERE (
                    section_title ILIKE :kw1
                    OR section_title ILIKE :kw2
                    OR legal_text   ILIKE :kw3
                )
                AND status = 'active'
                ORDER BY act_code, section_number_int
                LIMIT 10
            """),
            {"kw1": "%cheat%", "kw2": "%fraud%", "kw3": "%dishonest%"},
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        for row in rows:
            max_yr = "life" if row["punishment_max_years"] == 99999 else (
                f"{row['punishment_max_years']} yrs" if row["punishment_max_years"] else "—"
            )
            print(f"  {row['act_code']:12} s.{row['section_number']:>5}  "
                  f"{row['section_title']:<45}  offence={row['is_offence']}  max={max_yr}")
        print()

        # ------------------------------------------------------------------ #
        # QUERY 5: Bail eligibility filter
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 5 — Non-bailable offences triable by Sessions Court (BNS)")
        print('User says : "Which BNS offences are non-bailable and tried by Sessions Court?"')

        r = await s.execute(
            text("""
                SELECT section_number, section_title,
                       punishment_type, punishment_max_years
                FROM sections
                WHERE act_code    = 'BNS_2023'
                  AND is_offence  = TRUE
                  AND is_bailable = FALSE
                  AND triable_by ILIKE '%Sessions%'
                ORDER BY section_number_int
                LIMIT 12
            """),
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        print("  Non-bailable BNS offences triable by Sessions Court (first 12):")
        for row in rows:
            max_yr = "(life)" if row["punishment_max_years"] == 99999 else f"{row['punishment_max_years']} yrs"
            print(f"  s.{row['section_number']:>5}  {row['section_title']:<50}  {max_yr}")
        print()

        # ------------------------------------------------------------------ #
        # QUERY 6: Chapter-level structural overview
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 6 — Act structure overview (BNS chapters)")
        print('User says : "Give me an overview of how the BNS is organized."')

        r = await s.execute(
            text("""
                SELECT c.chapter_number, c.chapter_title,
                       COUNT(s.id) AS section_count,
                       SUM(CASE WHEN s.is_offence THEN 1 ELSE 0 END) AS offence_count
                FROM chapters c
                LEFT JOIN sections s
                       ON s.chapter_id = c.id AND s.status = 'active'
                WHERE c.act_code = 'BNS_2023'
                GROUP BY c.id, c.chapter_number, c.chapter_title, c.chapter_number_int
                ORDER BY c.chapter_number_int
            """),
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        for row in rows:
            print(f"  Ch.{row['chapter_number']:>4}  "
                  f"{row['chapter_title']:<52}  "
                  f"{row['section_count']:>3} sec  ({row['offence_count']} offences)")
        print()

        # ------------------------------------------------------------------ #
        # QUERY 7: Cross-act comparison — How did a provision change?
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 7 — Cross-act side-by-side comparison")
        print('User says : "How did the sedition law change from IPC to BNS?"')
        print("Extracted : old_act=IPC_1860, old_section=124A")

        # Fetch old section text
        r_old = await s.execute(
            text("SELECT section_number, section_title, legal_text FROM sections "
                 "WHERE act_code = 'IPC_1860' AND section_number = '124A'"),
        )
        old = r_old.mappings().fetchone()

        # Fetch mapping + new section
        r_map = await s.execute(
            text("""
                SELECT m.transition_type, m.scope_change, m.transition_note,
                       s.section_number, s.section_title, s.legal_text
                FROM law_transition_mappings m
                JOIN sections s ON s.act_code = m.new_act AND s.section_number = m.new_section
                WHERE m.old_act = 'IPC_1860' AND m.old_section = '124A'
                  AND m.is_active = TRUE
            """),
        )
        new = r_map.mappings().fetchone()

        print(SEP2)
        if old:
            print(f"  [IPC_1860] s.{old['section_number']} — {old['section_title']}")
            print("  Text (OLD):")
            print(wrap(old["legal_text"]))
        print()
        if new:
            print(f"  [BNS_2023] s.{new['section_number']} — {new['section_title']}")
            print(f"  Transition: {new['transition_type']}  |  scope_change: {new['scope_change']}")
            print(f"  Note: {new['transition_note']}")
            print("  Text (NEW):")
            print(wrap(new["legal_text"]))
        print()

        # ------------------------------------------------------------------ #
        # QUERY 8: Punishment range query (sentencing context)
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 8 — Punishment range query")
        print('User says : "What BNS offences carry 7 to 10 years imprisonment?"')
        print("Extracted : act=BNS_2023, min_years>=7, max_years<=10, is_offence=TRUE")

        r = await s.execute(
            text("""
                SELECT section_number, section_title,
                       punishment_min_years, punishment_max_years, punishment_type
                FROM sections
                WHERE act_code = 'BNS_2023'
                  AND is_offence = TRUE
                  AND punishment_max_years BETWEEN 7 AND 10
                ORDER BY punishment_max_years, section_number_int
                LIMIT 10
            """),
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        for row in rows:
            rng = (f"{row['punishment_min_years'] or 0}–{row['punishment_max_years']} yrs")
            print(f"  s.{row['section_number']:>5}  {row['section_title']:<48}  {rng}")
        if not rows:
            print("  (no results — check punishment_max_years data completeness)")
        print()

        # ------------------------------------------------------------------ #
        # QUERY 9: Sub-sections drill-down
        # ------------------------------------------------------------------ #
        print(SEP)
        print("QUERY 9 — Sub-section drill-down")
        print('User says : "Show me all sub-sections of BNS 64."')

        r = await s.execute(
            text("""
                SELECT ss.sub_section_label, ss.sub_section_type, ss.legal_text,
                       s.section_title
                FROM sub_sections ss
                JOIN sections s ON s.id = ss.section_id
                WHERE ss.act_code = 'BNS_2023' AND ss.parent_section_number = '64'
                ORDER BY ss.position_order
            """),
        )
        rows = r.mappings().fetchall()
        print(SEP2)
        if rows:
            print(f"  BNS 64 — {rows[0]['section_title']}")
            for row in rows:
                print(f"  [{row['sub_section_label']}] ({row['sub_section_type']})")
                print(wrap(row["legal_text"], width=60))
        print()

        # ------------------------------------------------------------------ #
        # Summary stats
        # ------------------------------------------------------------------ #
        print(SEP)
        print("DATABASE SUMMARY")
        print(SEP2)
        for tbl, label in [("sections","Sections"), ("sub_sections","Sub-sections"),
                           ("chapters","Chapters"), ("law_transition_mappings","Transition mappings")]:
            r = await s.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            total = r.scalar_one()
            if tbl == "law_transition_mappings":
                r2 = await s.execute(text("SELECT COUNT(*) FROM law_transition_mappings WHERE is_active=TRUE"))
                active = r2.scalar_one()
                print(f"  {label:<30}: {total} total, {active} is_active=TRUE")
            else:
                print(f"  {label:<30}: {total}")
        print(SEP)


if __name__ == "__main__":
    asyncio.run(run())
