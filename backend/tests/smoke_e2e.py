"""End-to-end smoke test for all four Neethi AI crew types.

Runs each crew with a real Indian legal query against live Qdrant and live LLMs.
Prints the full CrewAI verbose output (every agent's thinking + tool calls + output)
so you can see exactly what each agent produces.

QUERY SELECTION RULE:
    All smoke queries must match the indexed Qdrant data (BNS/BNSS/BSA criminal law).
    Queries about property law, contract law, or other unindexed domains will return
    0 results, causing wasted retrieval iterations and unnecessary token burn.

RATE LIMIT / FALLBACK STRATEGY:
    Primary:  Groq llama-3.3-70b-versatile (12,000 TPM free tier)
    Fallback: Mistral mistral-small-latest  (no shared TPM window with Groq)

    On the first Groq 429, the script immediately switches ALL agents to Mistral
    (via set_mistral_fallback) and retries — no sleep needed since it is a
    different provider.  Max 2 retries per case (user-specified).  The fallback
    flag is always reset to False after each case so the next case starts on Groq.

    Between crew cases a 65s sleep is kept so that Groq's rolling TPM window
    resets before the next case begins its first (Groq) attempt.

Usage (from project root on Lightning AI):
    python backend/tests/smoke_e2e.py

Optional — run only one crew type:
    python backend/tests/smoke_e2e.py layman
    python backend/tests/smoke_e2e.py lawyer
    python backend/tests/smoke_e2e.py advisor
    python backend/tests/smoke_e2e.py police
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

# nest_asyncio patches Python's asyncio to allow nested event loops.
# Required because crewai's BaseTool.run() internally calls asyncio.run() to
# execute async _run() methods — which fails inside akickoff()'s running loop
# without this patch.
import nest_asyncio
nest_asyncio.apply()

# ---------------------------------------------------------------------------
# Silence litellm's noisy proxy/apscheduler import errors — these fire on
# every LLM call when litellm[proxy] extras are not installed. They are
# harmless (litellm still routes calls correctly) but clutter the output.
# ---------------------------------------------------------------------------
import logging as _logging
_logging.getLogger("LiteLLM").setLevel(_logging.CRITICAL)

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so `backend.*` imports resolve
# regardless of how the script is invoked.
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ---------------------------------------------------------------------------
# Load .env before any backend imports
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from backend.agents.crew_config import (
    make_advisor_crew,
    make_layman_crew,
    make_lawyer_crew,
    make_police_crew,
)
from backend.config.llm_config import set_mistral_fallback

# ---------------------------------------------------------------------------
# Test cases — one per crew type.
# All queries are in the BNS/BNSS/BSA criminal law domain (our indexed data).
# ---------------------------------------------------------------------------

SMOKE_CASES = [
    {
        "crew_type": "layman",
        "label": "Citizen — Physical Assault (BNS)",
        "factory": make_layman_crew,
        "inputs": {
            "query": (
                "Someone slapped me in public and threatened me. "
                "What is the law against physical assault in India? "
                "What can I do and what sections apply under BNS 2023?"
            ),
            "user_role": "citizen",
        },
    },
    {
        "crew_type": "lawyer",
        "label": "Lawyer — Murder vs Culpable Homicide: SC Precedents + BNS Analysis",
        "factory": make_lawyer_crew,
        "inputs": {
            "query": (
                "My client is accused of murder under BNS Section 103. The facts are: "
                "the deceased had verbally abused and slapped the accused minutes before "
                "the incident; the accused struck back with a wooden plank in the heat of "
                "the moment, causing fatal head injuries; there was no premeditation and "
                "no prior enmity. "
                "Defence counsel intends to argue for a reduction to culpable homicide not "
                "amounting to murder under BNS Section 105 on the ground of grave and "
                "sudden provocation. "
                "Provide a complete IRAC analysis covering: "
                "(1) The legal distinction between murder under BNS 103 and culpable "
                "homicide not amounting to murder under BNS 105, with reference to the "
                "relevant definitional provisions in BNS 100 and 101; "
                "(2) Whether grave and sudden provocation under BNS 2023 can reduce the "
                "charge from murder to culpable homicide — what are the conditions and "
                "limitations of this exception; "
                "(3) How the Supreme Court has applied this distinction in recent judgments "
                "— specifically cite any 2023 or 2024 SC decisions on provocation defence "
                "or the culpable homicide vs murder distinction; "
                "(4) The sentencing range and judicial discretion between death penalty and "
                "life imprisonment under BNS 103, and what sentencing principles the "
                "Supreme Court has laid down for exercising this discretion."
            ),
            "user_role": "lawyer",
        },
    },
    {
        "crew_type": "advisor",
        "label": "Legal Advisor — Cheating and Fraud under BNS",
        "factory": make_advisor_crew,
        "inputs": {
            "query": (
                "A company director committed cheating by misrepresentation "
                "causing Rs 10 lakh loss to investors. "
                "What are the applicable sections under BNS 2023 and what penalties apply?"
            ),
            "user_role": "legal_advisor",
        },
    },
    {
        "crew_type": "police",
        "label": "Police — Robbery FIR Procedure (BNS)",
        "factory": make_police_crew,
        "inputs": {
            "query": (
                "A robbery was committed at knifepoint. The accused snatched a mobile phone "
                "and Rs 2,000 cash. What sections apply under BNS 2023? "
                "Is it cognizable? What is the FIR and arrest procedure?"
            ),
            "user_role": "police",
        },
    },
]

# ---------------------------------------------------------------------------
# Runner constants
# ---------------------------------------------------------------------------

DIVIDER = "=" * 80
SECTION  = "-" * 80

# Max retries per case (user-specified: no more than 2).
# Attempt 0 → Groq; attempts 1-2 → Mistral fallback.
_MAX_RETRIES = 2

# Sleep between crew cases so Groq's 60s rolling TPM window fully resets
# before the next case starts its first (Groq) attempt.
_BETWEEN_CREW_WAIT_SECONDS = 65


# ---------------------------------------------------------------------------
# Runner with Mistral fallback on Groq rate-limit
# ---------------------------------------------------------------------------

async def run_case(case: dict) -> bool:
    """Run one crew case with Mistral fallback on Groq rate-limit errors.

    Attempt 0 uses Groq (primary).
    Attempts 1+ switch ALL agents to Mistral Small (no sleep — different provider).
    Maximum _MAX_RETRIES retries (2).
    The Mistral fallback flag is always reset to False in the finally block
    so the next case starts fresh on Groq.

    Returns True on success, False on unrecoverable error.
    """
    print(f"\n{DIVIDER}")
    print(f"  CREW TYPE : {case['label']}")
    print(f"  QUERY     : {case['inputs']['query'][:120]}...")
    print(f"  USER ROLE : {case['inputs']['user_role']}")
    print(DIVIDER)

    try:
        for attempt in range(_MAX_RETRIES + 1):
            # Attempt 0 → Groq (primary); attempt 1+ → Mistral (fallback)
            use_mistral = attempt > 0
            set_mistral_fallback(use_mistral)
            provider = "Mistral (fallback)" if use_mistral else "Groq (primary)"

            if attempt > 0:
                print(
                    f"\n[FALLBACK] Attempt {attempt + 1}/{_MAX_RETRIES + 1} — "
                    f"switching to {provider} (no wait needed)..."
                )

            try:
                crew = case["factory"]()
                t0 = time.time()
                result = await crew.akickoff(inputs=case["inputs"])
                elapsed = time.time() - t0

                print(f"\n{SECTION}")
                print(f"  FINAL RESPONSE  ({elapsed:.1f}s)  [{provider}]")
                print(SECTION)
                print(getattr(result, "raw", str(result)))
                print(SECTION)
                return True

            except Exception as exc:
                exc_str = str(exc)
                is_rate_limit = (
                    "429" in exc_str
                    or "rate_limit" in exc_str.lower()
                    or "RateLimitError" in type(exc).__name__
                )

                if is_rate_limit and attempt < _MAX_RETRIES:
                    print(
                        f"\n[RATE LIMIT] {provider} TPM limit hit on attempt "
                        f"{attempt + 1}/{_MAX_RETRIES + 1}. "
                        f"Switching to Mistral fallback..."
                    )
                    continue  # No sleep — switching to a different provider

                # Unrecoverable: not a rate limit, or retries exhausted
                print(f"\n[SMOKE ERROR] Crew '{case['crew_type']}' raised an exception:")
                traceback.print_exc()
                return False

    finally:
        # Always restore Groq so the next case starts on the primary provider
        set_mistral_fallback(False)

    return False  # exhausted retries


async def main() -> int:
    """Run the smoke test suite. Returns 0 on full pass, 1 if any crew failed."""
    # Allow filtering to a single crew type via CLI arg
    filter_type = sys.argv[1].lower() if len(sys.argv) > 1 else None

    cases = [c for c in SMOKE_CASES if filter_type is None or c["crew_type"] == filter_type]

    if not cases:
        print(f"Unknown crew type: {filter_type!r}")
        print(f"Valid types: {[c['crew_type'] for c in SMOKE_CASES]}")
        return 1

    print(f"\nNeethi AI — End-to-End Smoke Test")
    print(f"Running {len(cases)} crew(s): {[c['crew_type'] for c in cases]}")
    print(f"Strategy: Groq primary → Mistral fallback on 429 (max {_MAX_RETRIES} retries)")

    results = {}
    for i, case in enumerate(cases):
        results[case["crew_type"]] = await run_case(case)
        # Wait between crew runs so Groq's rolling TPM window resets before
        # the next case starts its first (Groq) attempt.
        if i < len(cases) - 1:
            print(f"\nWaiting {_BETWEEN_CREW_WAIT_SECONDS}s before next crew run "
                  f"(Groq TPM window reset)...")
            await asyncio.sleep(_BETWEEN_CREW_WAIT_SECONDS)

    # Summary
    print(f"\n{DIVIDER}")
    print("  SMOKE TEST SUMMARY")
    print(DIVIDER)
    all_passed = True
    for crew_type, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"  {crew_type:<15} {status}")
        if not passed:
            all_passed = False
    print(DIVIDER)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
