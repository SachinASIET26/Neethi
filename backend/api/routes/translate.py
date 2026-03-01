"""Translation routes — text and query translation via Sarvam AI."""

from __future__ import annotations

import logging
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

from backend.api.dependencies import get_current_user
from backend.api.schemas.translate import (
    TranslateQueryRequest,
    TranslateQueryResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)
from backend.db.models.user import User

router = APIRouter()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_BASE_URL = "https://api.sarvam.ai"

# Language code mapping: short codes → Sarvam BCP-47 codes
_LANG_MAP = {
    "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
    "ml": "ml-IN", "bn": "bn-IN", "mr": "mr-IN", "gu": "gu-IN",
    "pa": "pa-IN", "ur": "ur-IN", "or": "or-IN", "en": "en-IN",
}

# Legal terms to preserve (not translated)
_PRESERVE_PATTERNS = [
    r"BNS(?:_2023)?\s+[Ss](?:ection)?\s*\d+[A-Za-z]?",
    r"BNSS(?:_2023)?\s+[Ss](?:ection)?\s*\d+[A-Za-z]?",
    r"BSA(?:_2023)?\s+[Ss](?:ection)?\s*\d+[A-Za-z]?",
    r"IPC\s+[Ss](?:ection)?\s*\d+[A-Za-z]?",
    r"CrPC\s+[Ss](?:ection)?\s*\d+[A-Za-z]?",
    r"Article\s+\d+[A-Za-z]?",
]


def _extract_preserved_terms(text: str) -> list[str]:
    terms: list[str] = []
    for pat in _PRESERVE_PATTERNS:
        terms.extend(re.findall(pat, text, re.IGNORECASE))
    return list(set(terms))


def _normalize_lang_code(code: str) -> str:
    """Convert short code (hi) to BCP-47 (hi-IN)."""
    return _LANG_MAP.get(code.lower(), code if "-" in code else f"{code}-IN")


# ---------------------------------------------------------------------------
# POST /translate/text
# ---------------------------------------------------------------------------

@router.post("/text", response_model=TranslateTextResponse)
async def translate_text(
    request: TranslateTextRequest,
    _: User = Depends(get_current_user),
):
    """Translate a text string to a target Indian language via Sarvam AI."""
    if not SARVAM_API_KEY:
        raise HTTPException(503, detail="Translation service not configured (SARVAM_API_KEY missing).")

    target = _normalize_lang_code(request.target_language)
    source = _normalize_lang_code(request.source_language)
    preserved = _extract_preserved_terms(request.text)

    # Sarvam translate supports up to ~5000 chars but responses can exceed this;
    # truncate to 3000 chars to stay safely within limits
    input_text = request.text[:3000]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SARVAM_BASE_URL}/translate",
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "input": input_text,
                    "source_language_code": source,
                    "target_language_code": target,
                    "speaker_gender": "Female",
                    "mode": "formal",
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            if not resp.is_success:
                logger.error(
                    "Sarvam translate error %s — body: %s",
                    resp.status_code, resp.text[:500],
                )
                raise httpx.HTTPStatusError(
                    f"Sarvam returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = f"Sarvam AI translation error {exc.response.status_code}: {exc.response.text[:300]}"
        raise HTTPException(502, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"Translation service unavailable: {exc}") from exc

    translated = data.get("translated_text", "")

    return TranslateTextResponse(
        translated_text=translated,
        source_language=request.source_language,
        target_language=request.target_language,
        preserved_terms=preserved,
        provider="sarvam_ai",
    )


# ---------------------------------------------------------------------------
# POST /translate/query
# ---------------------------------------------------------------------------

@router.post("/query", response_model=TranslateQueryResponse)
async def translate_query(
    request: TranslateQueryRequest,
    _: User = Depends(get_current_user),
):
    """Translate a user query from an Indian language to English for pipeline processing."""
    if not SARVAM_API_KEY:
        raise HTTPException(503, detail="Translation service not configured (SARVAM_API_KEY missing).")

    source = _normalize_lang_code(request.source_language)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SARVAM_BASE_URL}/translate",
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "input": request.query[:1000],
                    "source_language_code": source,
                    "target_language_code": "en-IN",
                    "speaker_gender": "Female",
                    "mode": "formal",
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            if not resp.is_success:
                logger.error(
                    "Sarvam translate (query) error %s — body: %s",
                    resp.status_code, resp.text[:500],
                )
                raise httpx.HTTPStatusError(
                    f"Sarvam returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = f"Sarvam AI error {exc.response.status_code}: {exc.response.text[:300]}"
        raise HTTPException(502, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"Translation service unavailable: {exc}") from exc

    english_query = data.get("translated_text", request.query)

    return TranslateQueryResponse(
        original_query=request.query,
        english_query=english_query,
        source_language=request.source_language,
    )
