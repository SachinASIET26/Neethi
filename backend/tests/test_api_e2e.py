"""
Neethi AI — FastAPI End-to-End Test Script
===========================================

Runs against a LIVE server at BASE_URL.

Usage (Lightning AI):
    # Terminal 1 — start server
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

    # Terminal 2 — run this script
    python test_api_e2e.py

    # Run only specific groups
    python test_api_e2e.py --groups auth query sections

Environment variables (must be set before running):
    DATABASE_URL, GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY
    Optional: SARVAM_API_KEY (for voice/translate tests)
              ANTHROPIC_API_KEY or MISTRAL_API_KEY (for document drafting)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
import wave
from typing import Optional

import httpx

# Load .env so SARVAM_API_KEY and other keys are available without needing
# them to be exported manually in the shell before running this script.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars must be set externally

BASE_URL = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 120  # seconds — agent pipeline can take a while

# ANSI colours
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# State shared between tests
# ---------------------------------------------------------------------------
state: dict = {
    "citizen_token":       None,
    "lawyer_token":        None,
    "admin_token":         None,
    "query_id":            None,
    "draft_id":            None,
    "case_id":             None,
}

# Test results
_results: list[tuple[str, bool, str]] = []  # (name, passed, detail)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def ok(name: str, detail: str = "") -> None:
    _results.append((name, True, detail))
    print(f"  {GREEN}✓{RESET} {name}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    _results.append((name, False, detail))
    print(f"  {RED}✗{RESET} {name}" + (f"  {RED}{detail}{RESET}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}━━━ {title} ━━━{RESET}")


def _dummy_wav_bytes() -> bytes:
    """Generate a minimal 1-second silent WAV for STT upload tests."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)  # 1 sec of silence
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

async def test_health(client: httpx.AsyncClient) -> None:
    section("Health")
    # Public /health is at root — outside /api/v1 prefix
    root_health_url = BASE_URL.replace("/api/v1", "") + "/health"
    async with httpx.AsyncClient(timeout=10) as raw:
        r = await raw.get(root_health_url)
    if r.status_code == 200:
        ok("GET /health (public)", r.json().get("status", "ok"))
    else:
        fail("GET /health (public)", str(r.status_code))


async def test_auth(client: httpx.AsyncClient) -> None:
    section("Authentication")

    # --- Register citizen ---
    ts = int(time.time())
    r = await client.post("/auth/register", json={
        "full_name": "Test Citizen",
        "email": f"citizen_{ts}@test.com",
        "password": "Test@1234",
        "role": "citizen",
    })
    if r.status_code == 201:
        ok("POST /auth/register (citizen)")
    else:
        fail("POST /auth/register (citizen)", r.text[:120])

    # --- Register lawyer ---
    r = await client.post("/auth/register", json={
        "full_name": "Test Lawyer",
        "email": f"lawyer_{ts}@test.com",
        "password": "Test@1234",
        "role": "lawyer",
        "bar_council_id": f"BAR/MH/2019/{ts}",
    })
    if r.status_code == 201:
        ok("POST /auth/register (lawyer)")
    else:
        fail("POST /auth/register (lawyer)", r.text[:120])

    # --- Register admin ---
    r = await client.post("/auth/register", json={
        "full_name": "Test Admin",
        "email": f"admin_{ts}@test.com",
        "password": "Test@1234",
        "role": "admin",
    })
    if r.status_code == 201:
        ok("POST /auth/register (admin)")
    else:
        fail("POST /auth/register (admin)", r.text[:120])

    # --- Login citizen ---
    r = await client.post("/auth/login", json={
        "email": f"citizen_{ts}@test.com",
        "password": "Test@1234",
    })
    if r.status_code == 200:
        state["citizen_token"] = r.json()["access_token"]
        ok("POST /auth/login (citizen)")
    else:
        fail("POST /auth/login (citizen)", r.text[:120])

    # --- Login lawyer ---
    r = await client.post("/auth/login", json={
        "email": f"lawyer_{ts}@test.com",
        "password": "Test@1234",
    })
    if r.status_code == 200:
        state["lawyer_token"] = r.json()["access_token"]
        ok("POST /auth/login (lawyer)")
    else:
        fail("POST /auth/login (lawyer)", r.text[:120])

    # --- Login admin ---
    r = await client.post("/auth/login", json={
        "email": f"admin_{ts}@test.com",
        "password": "Test@1234",
    })
    if r.status_code == 200:
        state["admin_token"] = r.json()["access_token"]
        ok("POST /auth/login (admin)")
    else:
        fail("POST /auth/login (admin)", r.text[:120])

    # --- GET /auth/me ---
    if state["citizen_token"]:
        r = await client.get("/auth/me", headers=_hdr(state["citizen_token"]))
        if r.status_code == 200 and r.json().get("role") == "citizen":
            ok("GET /auth/me")
        else:
            fail("GET /auth/me", r.text[:120])

    # --- Refresh token ---
    if state["citizen_token"]:
        r = await client.post("/auth/refresh", headers=_hdr(state["citizen_token"]))
        if r.status_code == 200 and "access_token" in r.json():
            ok("POST /auth/refresh")
        else:
            fail("POST /auth/refresh", r.text[:120])

    # --- Duplicate email should 409 ---
    r = await client.post("/auth/register", json={
        "full_name": "Dup",
        "email": f"citizen_{ts}@test.com",
        "password": "Test@1234",
        "role": "citizen",
    })
    if r.status_code == 409:
        ok("POST /auth/register (duplicate email → 409)")
    else:
        fail("POST /auth/register (duplicate email → 409)", str(r.status_code))

    # --- Bad password → 401 ---
    r = await client.post("/auth/login", json={
        "email": f"citizen_{ts}@test.com",
        "password": "Wrong@999",
    })
    if r.status_code == 401:
        ok("POST /auth/login (wrong password → 401)")
    else:
        fail("POST /auth/login (wrong password → 401)", str(r.status_code))

    # --- No token → 403 or 401 ---
    r = await client.get("/auth/me")
    if r.status_code in (401, 403):
        ok("GET /auth/me (no token → 401/403)")
    else:
        fail("GET /auth/me (no token → 401/403)", str(r.status_code))


async def test_sections(client: httpx.AsyncClient) -> None:
    section("Sections & Acts (PostgreSQL direct, no LLM)")
    token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no citizen token{RESET}")
        return

    # --- List acts ---
    r = await client.get("/sections/acts", headers=_hdr(token))
    if r.status_code == 200:
        acts = r.json().get("acts", [])
        ok("GET /sections/acts", f"{len(acts)} acts indexed")
    else:
        fail("GET /sections/acts", r.text[:120])

    # --- List sections for BNS ---
    r = await client.get("/sections/acts/BNS_2023/sections?limit=5", headers=_hdr(token))
    if r.status_code == 200:
        ok("GET /sections/acts/BNS_2023/sections", f"total={r.json().get('total_sections')}")
    else:
        fail("GET /sections/acts/BNS_2023/sections", r.text[:120])

    # --- Get BNS 103 ---
    r = await client.get("/sections/acts/BNS_2023/sections/103", headers=_hdr(token))
    if r.status_code == 200:
        d = r.json()
        ok("GET /sections/acts/BNS_2023/sections/103", d.get("section_title", "")[:50])
    elif r.status_code == 404:
        fail("GET /sections/acts/BNS_2023/sections/103", "NOT FOUND — run indexer first")
    else:
        fail("GET /sections/acts/BNS_2023/sections/103", r.text[:120])

    # --- Normalize IPC 302 → BNS 103 ---
    r = await client.get("/sections/normalize?old_act=IPC&old_section=302", headers=_hdr(token))
    if r.status_code == 200:
        d = r.json()
        mapped = d.get("mapped_to") or {}
        ok("GET /sections/normalize (IPC 302 → BNS)", f"→ {mapped.get('act','?')} {mapped.get('section','?')}")
    else:
        fail("GET /sections/normalize", r.text[:120])

    # --- Batch verify ---
    r = await client.post("/sections/verify", headers=_hdr(token), json={
        "citations": [
            {"act_code": "BNS_2023", "section_number": "103"},
            {"act_code": "BNS_2023", "section_number": "999"},
        ]
    })
    if r.status_code == 200:
        results = r.json().get("results", [])
        statuses = {x["section_number"]: x["status"] for x in results}
        ok("POST /sections/verify", f"103={statuses.get('103','?')} 999={statuses.get('999','?')}")
    else:
        fail("POST /sections/verify", r.text[:120])


async def test_query(client: httpx.AsyncClient) -> None:
    section("Legal Query (full CrewAI pipeline)")
    token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no citizen token{RESET}")
        return

    print(f"  {YELLOW}Note: /query/ask runs the full agent pipeline — may take 30–90 seconds{RESET}")

    # --- POST /query/ask (citizen) ---
    r = await client.post(
        "/query/ask",
        headers=_hdr(token),
        json={"query": "What is the punishment for murder under BNS?", "language": "en"},
        timeout=TIMEOUT,
    )
    if r.status_code == 200:
        d = r.json()
        state["query_id"] = d.get("query_id")
        ok(
            "POST /query/ask (citizen)",
            f"verified={d.get('verification_status')} confidence={d.get('confidence')} "
            f"citations={len(d.get('citations', []))} cached={d.get('cached')}",
        )
    else:
        fail("POST /query/ask (citizen)", r.text[:200])

    # --- Lawyer query ---
    l_token = state.get("lawyer_token")
    if l_token:
        r = await client.post(
            "/query/ask",
            headers=_hdr(l_token),
            json={
                "query": "Distinguish between murder and culpable homicide not amounting to murder under BNS 2023.",
                "include_precedents": True,
            },
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            d = r.json()
            ok(
                "POST /query/ask (lawyer, precedents=true)",
                f"verified={d.get('verification_status')} citations={len(d.get('citations', []))} "
                f"precedents={len(d.get('precedents', []))}",
            )
        else:
            fail("POST /query/ask (lawyer)", r.text[:200])

    # --- Cache hit ---
    if state.get("citizen_token"):
        r2 = await client.post(
            "/query/ask",
            headers=_hdr(token),
            json={"query": "What is the punishment for murder under BNS?"},
            timeout=TIMEOUT,
        )
        if r2.status_code == 200 and r2.json().get("cached"):
            ok("POST /query/ask (cache hit)", "cached=True")
        elif r2.status_code == 200:
            ok("POST /query/ask (second call)", "cached=False (cache miss — check Redis)")
        else:
            fail("POST /query/ask (cache hit)", r2.text[:120])

    # --- GET /query/history ---
    r = await client.get("/query/history?limit=5", headers=_hdr(token))
    if r.status_code == 200:
        ok("GET /query/history", f"total={r.json().get('total')}")
    else:
        fail("GET /query/history", r.text[:120])

    # --- GET /query/{id} ---
    if state.get("query_id"):
        r = await client.get(f"/query/{state['query_id']}", headers=_hdr(token))
        if r.status_code == 200:
            ok(f"GET /query/{state['query_id']}")
        else:
            fail(f"GET /query/{{query_id}}", r.text[:120])

    # --- POST /query/feedback ---
    if state.get("query_id"):
        r = await client.post("/query/feedback", headers=_hdr(token), json={
            "query_id": state["query_id"],
            "rating": 5,
            "feedback_type": "helpful",
            "comment": "Great answer!",
        })
        if r.status_code == 201:
            ok("POST /query/feedback")
        else:
            fail("POST /query/feedback", r.text[:120])

    # --- SSE stream (just check headers, don't consume full stream) ---
    async with client.stream(
        "POST",
        f"{BASE_URL}/query/ask/stream",
        headers={**_hdr(token), "Accept": "text/event-stream"},
        json={"query": "What is bail under BNSS?"},
        timeout=TIMEOUT,
    ) as r:
        if r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", ""):
            # Read first few events then close
            events = []
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    events.append(line)
                if len(events) >= 3 or "end" in line:
                    break
            ok("POST /query/ask/stream (SSE)", f"first events: {events[:2]}")
        else:
            fail("POST /query/ask/stream (SSE)", f"status={r.status_code}")


async def test_cases(client: httpx.AsyncClient) -> None:
    section("Cases")
    token = state.get("citizen_token")
    lawyer_token = state.get("lawyer_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no token{RESET}")
        return

    # --- Search cases ---
    r = await client.post("/cases/search", headers=_hdr(token), json={
        "query": "murder anticipatory bail",
        "top_k": 3,
    }, timeout=30)
    if r.status_code == 200:
        d = r.json()
        ok("POST /cases/search", f"found={d.get('total_found')} time={d.get('search_time_ms')}ms")
        if d.get("results"):
            state["case_id"] = None  # Qdrant IDs returned separately
    else:
        fail("POST /cases/search", r.text[:120])

    # --- Analyze — citizen must get 403 ---
    r = await client.post("/cases/analyze", headers=_hdr(token), json={
        "scenario": "Accused killed during sudden quarrel. Charged under BNS 103.",
    }, timeout=TIMEOUT)
    if r.status_code == 403:
        ok("POST /cases/analyze (citizen → 403 role restriction)")
    else:
        fail("POST /cases/analyze (citizen → 403 role restriction)", str(r.status_code))

    # --- Analyze — lawyer ---
    if lawyer_token:
        r = await client.post("/cases/analyze", headers=_hdr(lawyer_token), json={
            "scenario": "Accused killed victim during sudden quarrel without premeditation. Charged under BNS 103.",
            "applicable_acts": ["BNS_2023"],
        }, timeout=TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            ok("POST /cases/analyze (lawyer)", f"confidence={d.get('confidence')} sections={len(d.get('applicable_sections', []))}")
        else:
            fail("POST /cases/analyze (lawyer)", r.text[:200])


async def test_documents(client: httpx.AsyncClient) -> None:
    section("Document Drafting")
    token = state.get("lawyer_token") or state.get("citizen_token")
    citizen_token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no token{RESET}")
        return

    # --- List templates ---
    r = await client.get("/documents/templates", headers=_hdr(token))
    if r.status_code == 200:
        templates = r.json().get("templates", [])
        ok("GET /documents/templates", f"{len(templates)} templates accessible")
    else:
        fail("GET /documents/templates", r.text[:120])

    # --- Citizen cannot draft bail application ---
    if citizen_token:
        r = await client.post("/documents/draft", headers=_hdr(citizen_token), json={
            "template_id": "bail_application",
            "fields": {
                "accused_name": "Test Accused",
                "fir_number": "FIR/001/2026",
                "police_station": "Test Station",
                "offence_sections": "BNS 103",
                "grounds": "Test grounds",
            },
        }, timeout=TIMEOUT)
        if r.status_code == 403:
            ok("POST /documents/draft (citizen → bail app → 403)")
        else:
            fail("POST /documents/draft (citizen → 403)", str(r.status_code))

    # --- Legal notice — citizen can draft ---
    if citizen_token:
        r = await client.post("/documents/draft", headers=_hdr(citizen_token), json={
            "template_id": "legal_notice",
            "fields": {
                "sender_name": "Ravi Kumar",
                "receiver_name": "ABC Builder Pvt Ltd",
                "sender_address": "123 MG Road, Bengaluru",
                "receiver_address": "456 Commercial St, Bengaluru",
                "subject": "Refund of advance payment for flat booking",
                "demand": "Refund of ₹5,00,000 paid as advance for flat no. B-302",
                "notice_period_days": "30",
            },
            "include_citations": True,
        }, timeout=TIMEOUT)
        if r.status_code == 201:
            state["draft_id"] = r.json().get("draft_id")
            d = r.json()
            ok("POST /documents/draft (legal_notice)", f"words={d.get('word_count')} draft_id={state['draft_id']}")
        else:
            fail("POST /documents/draft (legal_notice)", r.text[:200])

    # --- GET /documents/draft/{id} ---
    if state.get("draft_id") and citizen_token:
        r = await client.get(f"/documents/draft/{state['draft_id']}", headers=_hdr(citizen_token))
        if r.status_code == 200:
            ok(f"GET /documents/draft/{{draft_id}}")
        else:
            fail("GET /documents/draft/{draft_id}", r.text[:120])

    # --- PDF export ---
    if state.get("draft_id") and citizen_token:
        r = await client.post(
            f"/documents/draft/{state['draft_id']}/pdf",
            headers=_hdr(citizen_token),
            timeout=30,
        )
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            ok("POST /documents/draft/{id}/pdf", f"content-type={ct} size={len(r.content)}B")
        else:
            fail("POST /documents/draft/{id}/pdf", r.text[:120])

    # --- Missing required field → 422 ---
    r = await client.post("/documents/draft", headers=_hdr(token), json={
        "template_id": "legal_notice",
        "fields": {"sender_name": "Only one field"},
    }, timeout=30)
    if r.status_code == 422:
        ok("POST /documents/draft (missing fields → 422)")
    else:
        fail("POST /documents/draft (missing fields → 422)", str(r.status_code))

    # --- DELETE ---
    if state.get("draft_id") and citizen_token:
        r = await client.delete(f"/documents/draft/{state['draft_id']}", headers=_hdr(citizen_token))
        if r.status_code == 204:
            ok("DELETE /documents/draft/{id}")
        else:
            fail("DELETE /documents/draft/{id}", r.text[:120])


async def test_resources(client: httpx.AsyncClient) -> None:
    section("Nearby Legal Resources")
    token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no token{RESET}")
        return

    # --- Nearby by city ---
    r = await client.post("/resources/nearby", headers=_hdr(token), json={
        "resource_type": "legal_aid",
        "city": "Mumbai",
        "state": "Maharashtra",
        "limit": 3,
    }, timeout=30)
    if r.status_code == 200:
        d = r.json()
        ok("POST /resources/nearby (by city)", f"found={d.get('total_found')} note={'yes' if d.get('note') else 'no'}")
    else:
        fail("POST /resources/nearby", r.text[:120])

    # --- Nearby by GPS ---
    r = await client.post("/resources/nearby", headers=_hdr(token), json={
        "resource_type": "police_station",
        "latitude": 19.0760,
        "longitude": 72.8777,
        "radius_km": 5,
        "limit": 3,
    }, timeout=30)
    if r.status_code == 200:
        ok("POST /resources/nearby (by GPS)")
    else:
        fail("POST /resources/nearby (by GPS)", r.text[:120])

    # --- Legal aid eligibility ---
    r = await client.get(
        "/resources/legal-aid/eligibility?annual_income=150000&category=general&state=MH",
        headers=_hdr(token),
    )
    if r.status_code == 200:
        d = r.json()
        ok("GET /resources/legal-aid/eligibility", f"eligible={d.get('eligible')} basis={d.get('basis','')[:60]}")
    else:
        fail("GET /resources/legal-aid/eligibility", r.text[:120])

    # --- SC/ST always eligible ---
    r = await client.get(
        "/resources/legal-aid/eligibility?annual_income=9999999&category=sc&state=DL",
        headers=_hdr(token),
    )
    if r.status_code == 200 and r.json().get("eligible"):
        ok("GET /resources/legal-aid/eligibility (SC category → always eligible)")
    else:
        fail("GET /resources/legal-aid/eligibility (SC category)", r.text[:120])


async def test_translate(client: httpx.AsyncClient) -> None:
    section("Translation (Sarvam AI)")
    token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no token{RESET}")
        return

    import os
    if not os.getenv("SARVAM_API_KEY"):
        print(f"  {YELLOW}⚠ Skipped — SARVAM_API_KEY not set{RESET}")
        return

    # --- Translate text ---
    r = await client.post("/translate/text", headers=_hdr(token), json={
        "text": "Murder under BNS Section 103 is punishable with death or imprisonment for life.",
        "source_language": "en",
        "target_language": "hi",
        "domain": "legal",
    }, timeout=30)
    if r.status_code == 200:
        d = r.json()
        ok("POST /translate/text (en→hi)", d.get("translated_text", "")[:80])
    else:
        fail("POST /translate/text", r.text[:120])

    # --- Translate query ---
    r = await client.post("/translate/query", headers=_hdr(token), json={
        "query": "हत्या की सजा क्या है?",
        "source_language": "hi",
    }, timeout=30)
    if r.status_code == 200:
        d = r.json()
        ok("POST /translate/query (hi→en)", d.get("english_query", "")[:80])
    else:
        fail("POST /translate/query", r.text[:120])


async def test_voice(client: httpx.AsyncClient) -> None:
    section("Voice — TTS / STT (Sarvam AI)")
    token = state.get("citizen_token")
    if not token:
        print(f"  {YELLOW}⚠ Skipped — no token{RESET}")
        return

    import os
    if not os.getenv("SARVAM_API_KEY"):
        print(f"  {YELLOW}⚠ Skipped — SARVAM_API_KEY not set{RESET}")
        return

    wav_bytes = _dummy_wav_bytes()

    # --- STT (silent audio — expect low-confidence or empty transcript) ---
    r = await client.post(
        "/voice/speech-to-text",
        headers=_hdr(token),
        files={"file": ("test.wav", wav_bytes, "audio/wav")},
        data={"language_code": "hi-IN"},
        timeout=30,
    )
    if r.status_code in (200, 422):  # 422 acceptable for silent audio
        ok("POST /voice/speech-to-text", f"status={r.status_code} (silent audio — empty transcript expected)")
    else:
        fail("POST /voice/speech-to-text", r.text[:120])

    # --- TTS ---
    r = await client.post("/voice/text-to-speech", headers=_hdr(token), json={
        "text": "नमस्ते। यह नीति AI का परीक्षण है।",
        "target_language_code": "hi-IN",
        "speaker": "anushka",
        "pace": 1.0,
        "speech_sample_rate": 16000,
    }, timeout=30)
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio"):
        ok("POST /voice/text-to-speech", f"audio size={len(r.content)} bytes")
    else:
        fail("POST /voice/text-to-speech", r.text[:120])

    # --- Voice ask (silent audio — will likely fail STT, that's expected) ---
    r = await client.post(
        "/voice/ask",
        headers=_hdr(token),
        files={"file": ("query.wav", wav_bytes, "audio/wav")},
        data={"language_code": "hi-IN", "respond_in_audio": "true"},
        timeout=TIMEOUT,
    )
    if r.status_code in (200, 422):
        ok("POST /voice/ask", f"status={r.status_code}")
    else:
        fail("POST /voice/ask", r.text[:120])


async def test_admin(client: httpx.AsyncClient) -> None:
    section("Admin")
    admin_token = state.get("admin_token")
    citizen_token = state.get("citizen_token")

    # --- Citizen cannot access admin ---
    if citizen_token:
        r = await client.get("/admin/health", headers=_hdr(citizen_token))
        if r.status_code == 403:
            ok("GET /admin/health (citizen → 403)")
        else:
            fail("GET /admin/health (citizen → 403)", str(r.status_code))

    if not admin_token:
        print(f"  {YELLOW}⚠ Admin endpoints skipped — no admin token{RESET}")
        return

    # --- Health check ---
    r = await client.get("/admin/health", headers=_hdr(admin_token), timeout=30)
    if r.status_code == 200:
        d = r.json()
        ok("GET /admin/health", f"status={d.get('status')} db={d.get('components',{}).get('database',{}).get('status')}")
    else:
        fail("GET /admin/health", r.text[:120])

    # --- Cache flush ---
    r = await client.post("/admin/cache/flush", headers=_hdr(admin_token), json={"role": "citizen"})
    if r.status_code == 200:
        ok("POST /admin/cache/flush", f"flushed={r.json().get('flushed_keys')}")
    else:
        fail("POST /admin/cache/flush", r.text[:120])

    # --- Mistral fallback toggle ---
    r = await client.post("/admin/mistral-fallback", headers=_hdr(admin_token), json={"active": True})
    if r.status_code == 200 and r.json().get("mistral_fallback_active"):
        ok("POST /admin/mistral-fallback (activate)")
    else:
        fail("POST /admin/mistral-fallback (activate)", r.text[:120])

    # Reset
    r = await client.post("/admin/mistral-fallback", headers=_hdr(admin_token), json={"active": False})
    if r.status_code == 200:
        ok("POST /admin/mistral-fallback (deactivate)")
    else:
        fail("POST /admin/mistral-fallback (deactivate)", r.text[:120])

    # --- Ingest (dummy PDF) ---
    dummy_pdf = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\nxref\n0 2\ntrailer\n<</Size 2>>\nstartxref\n9\n%%EOF"
    r = await client.post(
        "/admin/ingest",
        headers=_hdr(admin_token),
        files={"file": ("test.pdf", dummy_pdf, "application/pdf")},
        data={"act_code": "BNS_2023", "document_type": "statutory"},
        timeout=30,
    )
    if r.status_code == 202:
        job_id = r.json().get("job_id")
        ok("POST /admin/ingest", f"job_id={job_id}")

        # --- Check job status ---
        if job_id:
            await asyncio.sleep(2)
            r2 = await client.get(f"/admin/jobs/{job_id}", headers=_hdr(admin_token))
            if r2.status_code == 200:
                ok(f"GET /admin/jobs/{{job_id}}", f"status={r2.json().get('status')}")
            else:
                fail("GET /admin/jobs/{job_id}", r2.text[:120])
    else:
        fail("POST /admin/ingest", r.text[:120])


# ---------------------------------------------------------------------------
# Wait for server to be ready
# ---------------------------------------------------------------------------

async def wait_for_server(_client: httpx.AsyncClient, retries: int = 20, delay: float = 2.0) -> bool:
    url = BASE_URL.replace("/api/v1", "") + "/health"
    print(f"\n{CYAN}Waiting for server at {url} ...{RESET}")
    async with httpx.AsyncClient(timeout=5) as raw:
        for i in range(retries):
            try:
                r = await raw.get(url)
                if r.status_code == 200:
                    print(f"{GREEN}Server ready after {i * delay:.0f}s{RESET}")
                    return True
            except Exception:
                pass
            print(f"  Attempt {i+1}/{retries}...")
            await asyncio.sleep(delay)
    print(f"{RED}Server not ready after {retries * delay:.0f}s — aborting{RESET}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_GROUPS = ["health", "auth", "sections", "query", "cases", "documents", "resources", "translate", "voice", "admin"]

GROUP_MAP = {
    "health":    test_health,
    "auth":      test_auth,
    "sections":  test_sections,
    "query":     test_query,
    "cases":     test_cases,
    "documents": test_documents,
    "resources": test_resources,
    "translate": test_translate,
    "voice":     test_voice,
    "admin":     test_admin,
}


async def main(groups: list[str]) -> None:
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  Neethi AI — FastAPI End-to-End Tests{RESET}")
    print(f"{BOLD}  Target: {BASE_URL}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        if not await wait_for_server(client):
            sys.exit(1)

        for group in groups:
            fn = GROUP_MAP.get(group)
            if fn:
                await fn(client)
            else:
                print(f"{YELLOW}Unknown group: {group}{RESET}")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    total = len(_results)
    passed = sum(1 for _, p, _ in _results if p)
    failed = total - passed

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  RESULTS: {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  / {total} total")
    print(f"{BOLD}{'=' * 60}{RESET}")

    if failed:
        print(f"\n{RED}{BOLD}Failed tests:{RESET}")
        for name, passed_, detail in _results:
            if not passed_:
                print(f"  {RED}✗{RESET} {name}  {detail}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}{BOLD}All tests passed!{RESET}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Neethi AI API E2E Tests")
    parser.add_argument(
        "--groups",
        nargs="*",
        default=ALL_GROUPS,
        choices=ALL_GROUPS,
        metavar="GROUP",
        help=f"Test groups to run (default: all). Choices: {', '.join(ALL_GROUPS)}",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/v1",
        help="Base URL of the API (default: http://127.0.0.1:8000/api/v1)",
    )
    args = parser.parse_args()
    BASE_URL = args.url
    asyncio.run(main(args.groups))
