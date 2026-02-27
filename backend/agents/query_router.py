"""Query complexity router — pre-screens queries before any LLM is called.

Classifies every incoming query into a tier purely with regex. No I/O,
no LLM, no async — just string matching. Routes accordingly:

    Tier 1 — DIRECT  (~50–300 tokens, 0 LLM calls)
    ────────────────────────────────────────────────
    Pattern-matched queries resolved entirely from the database.

    a) Section lookup
       Pattern : "BNS 103", "BNSS s.482", "What is BSA section 23?"
       Handler : CitationVerificationTool (Qdrant scroll, no embedder)
       Saves   : ~11,700 tokens vs full crew

    b) Statute mapping
       Pattern : "IPC 302 in BNS", "CrPC 438 equivalent", "what is IPC 302 now?"
       Handler : StatuteNormalizationTool (DB lookup, no LLM)
       Saves   : ~11,700 tokens vs full crew

    c) Civil act section lookup
       Pattern : "CPC order 7", "SRA 10", "TPA 58", "LA 3"
       Handler : CitationVerificationTool (same Qdrant scroll)

    Tier 3 — FULL  (~12,000–20,000 tokens)
    ────────────────────────────────────────────────────────────────
    Everything else routes to the full crew via get_crew_for_role().

    (Tier 2 — lightweight 2-agent crew — is planned but not yet built.)

Response cache (Redis / Upstash)
─────────────────────────────────
    handle_query() checks the Redis cache before routing and stores the
    result after resolution.  Cache is transparent — if Redis is down,
    queries proceed normally without errors.

    TTLs:
        DIRECT → 24 h  (statutory text is stable)
        FULL   →  1 h  (new documents may be indexed at any time)

Integration
───────────
    # Preferred — single entry point with cache:
    from backend.agents.query_router import handle_query

    response = await handle_query(query, user_role, crew_factory=get_crew_for_role)

    # Low-level (cache bypassed):
    from backend.agents.query_router import classify_query, resolve_direct, QueryTier

    result = classify_query(query)
    if result.tier == QueryTier.DIRECT:
        response = await resolve_direct(result)
    else:
        crew = get_crew_for_role(user_role)
        output = await crew.akickoff(inputs={"query": query, "user_role": user_role})
        response = output.raw
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------

class QueryTier(str, Enum):
    DIRECT = "direct"   # Tier 1: resolved by tools only, 0 LLM calls
    FULL   = "full"     # Tier 3: full crew pipeline


# ---------------------------------------------------------------------------
# Router result
# ---------------------------------------------------------------------------

@dataclass
class RouterResult:
    """Output of classify_query(). Describes tier and extracted entities."""

    tier: QueryTier
    reason: str
    """Human-readable explanation of why this tier was chosen."""

    match_type: Optional[str] = None
    """'section_lookup' | 'statute_mapping' | None"""

    act_code: Optional[str] = None
    """Canonical act code for section_lookup, e.g. 'BNS_2023'."""

    section_number: Optional[str] = None
    """Extracted section number, e.g. '103' or '53A'."""

    old_act: Optional[str] = None
    """Short old act name for statute_mapping, e.g. 'IPC'."""

    old_section: Optional[str] = None
    """Old section number for statute_mapping, e.g. '302'."""


# ---------------------------------------------------------------------------
# Act code tables (kept in sync with CitationVerificationTool)
# ---------------------------------------------------------------------------

# New criminal codes → canonical form
_NEW_ACT_MAP: dict[str, str] = {
    "BNS":  "BNS_2023",
    "BNSS": "BNSS_2023",
    "BSA":  "BSA_2023",
}

# Old criminal codes → canonical form (used for statute_mapping path)
_OLD_CRIMINAL_MAP: dict[str, str] = {
    "IPC":  "IPC_1860",
    "CRPC": "CrPC_1973",
    "IEA":  "IEA_1872",
}

# Civil / procedural acts → canonical form (direct CitationVerificationTool lookup)
_CIVIL_ACT_MAP: dict[str, str] = {
    "SRA": "SRA_1963",
    "TPA": "TPA_1882",
    "CPA": "CPA_2019",
    "CPC": "CPC_1908",
    "LA":  "LA_1963",
}

_ALL_ACT_MAP: dict[str, str] = {**_NEW_ACT_MAP, **_OLD_CRIMINAL_MAP, **_CIVIL_ACT_MAP}


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Section number: digits optionally followed by a single letter (e.g. 53A, 2B).
# (?!\d) negative lookahead ensures the captured digits are NOT immediately
# followed by more digits.  Without it, "BNS 2023" backtracks (year suffix is
# optional), and the engine grabs "202" from "2023" as a 3-digit section number,
# routing "What sections apply under BNS 2023?" to the DIRECT tier as s.202.
# With (?!\d): "202" is followed by "3" → lookahead fails → no match → FULL crew.
_SEC_NUM = r"(\d{1,3}[A-Za-z]?)(?!\d)"

# Optional "s." or "section" or "sec" prefix before the number
_SEC_PREFIX = r"(?:s\.?\s*|sec(?:tion)?\s*)?"

# Optional year suffix attached to act name  (e.g. "BNS2023", "BNS_2023")
_YEAR_SUFFIX = r"(?:\s*[_\-]?\s*(?:20\d{2}|\d{4}))?"

# ── Pattern A: New act + section ─────────────────────────────────────────
# Matches: "BNS 103", "BNSS s.482", "BSA section 23", "BNS_2023 s.103"
# Also matches when query is just "What is BNS 103?" or "explain BNSS 482"
_NEW_ACT_RE = re.compile(
    r"\b(BNS|BNSS|BSA)" + _YEAR_SUFFIX + r"\s*" + _SEC_PREFIX + _SEC_NUM,
    re.IGNORECASE,
)

# ── Pattern B: "section N of BNS" / "sec N BNS" ─────────────────────────
_SEC_OF_NEW_ACT_RE = re.compile(
    r"\bsect?(?:ion)?\s+" + _SEC_NUM + r"\s+(?:of\s+)?(BNS|BNSS|BSA)\b",
    re.IGNORECASE,
)

# ── Pattern C: Old criminal act + section ────────────────────────────────
# Matches: "IPC 302", "CrPC s.438", "IEA 45"
_OLD_CRIMINAL_RE = re.compile(
    r"\b(IPC|CrPC|IEA)" + _YEAR_SUFFIX + r"\s*" + _SEC_PREFIX + _SEC_NUM,
    re.IGNORECASE,
)

# ── Pattern D: Civil act + section ───────────────────────────────────────
# Matches: "SRA 10", "TPA 58", "CPC Order 7", "LA section 3", "CPA 35"
# CPC has "Order" + "Rule" structure too, but section numbers work for lookup
_CIVIL_ACT_RE = re.compile(
    r"\b(SRA|TPA|CPA|CPC|LA)" + _YEAR_SUFFIX + r"\s*" + _SEC_PREFIX + _SEC_NUM,
    re.IGNORECASE,
)

# ── Pattern E: Statute mapping intent ────────────────────────────────────
# Indicates the user wants the IPC/CrPC/IEA → BNS/BNSS/BSA equivalent
_MAPPING_RE = re.compile(
    r"\b("
    r"equivalent|now|new\s+section|new\s+code|"
    r"in\s+BNS|in\s+BNSS|in\s+BSA|"
    r"under\s+new\s+law|replaced\s+by|corresponding\s+section|"
    r"after\s+july|from\s+2024|under\s+BNS"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Classifier  (pure, sync, zero I/O)
# ---------------------------------------------------------------------------

def classify_query(query: str) -> RouterResult:
    """Classify a raw query into a routing tier using regex only.

    Pure function — no I/O, no LLM, no async.  Safe to call synchronously
    at the very start of request handling.

    Args:
        query: Raw user query string.

    Returns:
        RouterResult with tier, match_type, and any extracted entities.
    """
    q = query.strip()

    # ── Check A: New act section lookup ──────────────────────────────────
    # "BNS 103", "What is BNSS 482?", "Explain BSA s.23"
    m = _NEW_ACT_RE.search(q) or _SEC_OF_NEW_ACT_RE.search(q)
    if m:
        if _NEW_ACT_RE.search(q):
            hit = _NEW_ACT_RE.search(q)
            raw_act  = hit.group(1).upper()
            section  = hit.group(2)
        else:
            hit = _SEC_OF_NEW_ACT_RE.search(q)
            section  = hit.group(1)
            raw_act  = hit.group(2).upper()
        act_code = _NEW_ACT_MAP.get(raw_act, raw_act)
        logger.debug("router: DIRECT/section_lookup  %s s.%s", act_code, section)
        return RouterResult(
            tier=QueryTier.DIRECT,
            reason=f"section reference detected: {raw_act} {section}",
            match_type="section_lookup",
            act_code=act_code,
            section_number=section,
        )

    # ── Check B: Old criminal act + mapping intent ────────────────────────
    # "IPC 302 in BNS", "What is CrPC 438 now?", "IPC 302 equivalent BNS"
    # Without mapping keywords, "IPC 302" alone falls through to full crew
    # because the user may want case law / context, not just the BNS number.
    old_m = _OLD_CRIMINAL_RE.search(q)
    if old_m and _MAPPING_RE.search(q):
        raw_act = old_m.group(1).upper()
        section = old_m.group(2)
        logger.debug("router: DIRECT/statute_mapping  %s s.%s", raw_act, section)
        return RouterResult(
            tier=QueryTier.DIRECT,
            reason=f"old statute + mapping intent: {raw_act} {section}",
            match_type="statute_mapping",
            old_act=raw_act,
            old_section=section,
        )

    # ── Check C: Civil act section lookup ─────────────────────────────────
    # "SRA 10", "TPA 58", "CPC Order 7 Rule 11", "LA section 3"
    civil_m = _CIVIL_ACT_RE.search(q)
    if civil_m:
        raw_act  = civil_m.group(1).upper()
        section  = civil_m.group(2)
        act_code = _CIVIL_ACT_MAP.get(raw_act, raw_act)
        logger.debug("router: DIRECT/section_lookup (civil)  %s s.%s", act_code, section)
        return RouterResult(
            tier=QueryTier.DIRECT,
            reason=f"civil act section reference: {raw_act} {section}",
            match_type="section_lookup",
            act_code=act_code,
            section_number=section,
        )

    # ── Default: full crew ────────────────────────────────────────────────
    logger.debug("router: FULL — no direct pattern matched")
    return RouterResult(
        tier=QueryTier.FULL,
        reason="no direct-lookup pattern matched — routing to full crew pipeline",
    )


# ---------------------------------------------------------------------------
# Tier 1 resolver  (async, calls tools directly)
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "\n\n---\n"
    "*Source: Neethi AI legal database (direct lookup) — "
    "no LLM reasoning applied. "
    "This is AI-assisted legal information. "
    "Consult a qualified lawyer for advice specific to your situation.*"
)


async def resolve_direct(result: RouterResult) -> str:
    """Execute a Tier 1 query using tools only — no crew, no LLM.

    Args:
        result: RouterResult with tier=DIRECT and extracted entities.

    Returns:
        Formatted response string ready for delivery to the user.

    Raises:
        ValueError: If result.tier is not DIRECT or match_type is unknown.
    """
    if result.tier != QueryTier.DIRECT:
        raise ValueError(f"resolve_direct() called with tier={result.tier!r} — must be DIRECT")

    if result.match_type == "section_lookup":
        from backend.agents.tools.citation_verification_tool import CitationVerificationTool
        tool = CitationVerificationTool()
        response = tool._run(result.act_code or "", result.section_number or "")
        return response + _DISCLAIMER

    if result.match_type == "statute_mapping":
        from backend.agents.tools.statute_normalization_tool import StatuteNormalizationTool
        tool = StatuteNormalizationTool()
        response = tool._run(result.old_act or "", result.old_section or "")
        return response + _DISCLAIMER

    raise ValueError(f"Unknown match_type: {result.match_type!r}")


# ---------------------------------------------------------------------------
# Unified entry point  (cache → classify → resolve)
# ---------------------------------------------------------------------------

async def handle_query(
    query: str,
    user_role: str,
    *,
    crew_factory,  # Callable[[str], Crew] — passed in to avoid circular imports
) -> str:
    """Main query handler: cache check → tier classification → resolution.

    This is the single entry point used by the API layer.  It wraps both
    Tier 1 (direct tool calls) and Tier 3 (full crew) with Redis caching so
    repeated queries never reach the LLM pipeline.

    Cache is transparent — if Redis is unavailable the function continues
    normally without raising.

    Args:
        query:        Raw user query string.
        user_role:    User's role ('citizen', 'lawyer', 'advisor', 'police').
        crew_factory: Callable that accepts a role string and returns a
                      configured CrewAI Crew.  Typically get_crew_for_role()
                      from crew_config.  Passed as a parameter to keep this
                      module free of circular imports.

    Returns:
        Response string ready for delivery to the user.
    """
    from backend.services.cache import get_cache  # lazy import — avoids startup cost

    cache = await get_cache()

    # ── 1. Cache check ────────────────────────────────────────────────────
    cached = await cache.get(query, user_role)
    if cached is not None:
        logger.info(
            "handle_query: CACHE HIT  role=%s query_prefix=%r",
            user_role, query[:60],
        )
        return cached

    # ── 2. Classify ───────────────────────────────────────────────────────
    result = classify_query(query)
    logger.info(
        "handle_query: tier=%s match=%s role=%s query_prefix=%r",
        result.tier.value, result.match_type, user_role, query[:60],
    )

    # ── 3. Resolve ────────────────────────────────────────────────────────
    if result.tier == QueryTier.DIRECT:
        response = await resolve_direct(result)
        await cache.set(query, user_role, response, tier="direct")
        return response

    # Tier 3 — full crew
    crew = crew_factory(user_role)
    output = await crew.akickoff(inputs={"query": query, "user_role": user_role})
    response: str = output.raw
    await cache.set(query, user_role, response, tier="full")
    return response
