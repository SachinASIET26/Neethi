"""Voice routes — Speech-to-Text (STT), Text-to-Speech (TTS), Voice Ask pipeline.

Powered by Sarvam AI.

STT endpoint:  POST /voice/speech-to-text
               Accepts audio file (wav/mp3/ogg/webm), returns transcript.

TTS endpoint:  POST /voice/text-to-speech
               Accepts JSON text + voice settings, returns audio/wav stream.

Voice Ask:     POST /voice/ask
               Full pipeline: audio in → STT → legal query → TTS → audio out.
               Returns both text answer and audio in a single response.
"""

from __future__ import annotations

import base64
import os

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.api.dependencies import check_rate_limit, get_current_user, get_db
from backend.api.schemas.voice import STTResponse, TTSRequest, VoiceAskResponse
from backend.db.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends as FADepends

router = APIRouter()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_BASE_URL = "https://api.sarvam.ai"

# Sarvam language codes: short → BCP-47
_LANG_MAP = {
    "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
    "ml": "ml-IN", "bn": "bn-IN", "mr": "mr-IN", "gu": "gu-IN",
    "pa": "pa-IN", "ur": "ur-IN", "or": "or-IN", "en": "en-IN",
}

_AUDIO_MIME = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
}


def _sarvam_headers() -> dict:
    if not SARVAM_API_KEY:
        raise HTTPException(503, detail="Voice service not configured (SARVAM_API_KEY missing).")
    return {"api-subscription-key": SARVAM_API_KEY}


def _lang_code(code: str) -> str:
    return _LANG_MAP.get(code.lower(), code if "-" in code else f"{code}-IN")


# ---------------------------------------------------------------------------
# POST /voice/speech-to-text
# ---------------------------------------------------------------------------

@router.post("/speech-to-text", response_model=STTResponse)
async def speech_to_text(
    file: UploadFile = File(..., description="Audio file: wav, mp3, ogg, webm, m4a"),
    language_code: str = Form("hi-IN", description="Language of the audio, e.g. hi-IN"),
    _: User = Depends(get_current_user),
):
    """Convert uploaded audio to text using Sarvam AI Saarika STT model.

    Supported formats: wav, mp3, ogg, webm, m4a
    Max file size: 25 MB
    Max duration: ~5 minutes
    """
    audio_bytes = await file.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, detail="Audio file too large. Maximum size is 25 MB.")

    ext = (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()
    mime = _AUDIO_MIME.get(ext, "audio/wav")
    lang = _lang_code(language_code)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{SARVAM_BASE_URL}/speech-to-text",
                headers=_sarvam_headers(),
                files={"file": (file.filename or "audio.wav", audio_bytes, mime)},
                data={
                    "model": "saarika:v2.5",
                    "language_code": lang,
                    "with_timestamps": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, detail=f"Sarvam STT error {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"STT service unavailable: {exc}") from exc

    transcript = data.get("transcript", "")
    if not transcript:
        raise HTTPException(422, detail="Could not transcribe audio. Please speak clearly and retry.")

    return STTResponse(
        transcript=transcript,
        language_code=lang,
    )


# ---------------------------------------------------------------------------
# POST /voice/text-to-speech
# ---------------------------------------------------------------------------

@router.post("/text-to-speech")
async def text_to_speech(
    request: TTSRequest,
    _: User = Depends(get_current_user),
):
    """Convert text to speech using Sarvam AI Bulbul TTS model.

    Returns audio/wav binary stream.
    Recommended for playing legal responses in regional languages.
    """
    lang = _lang_code(request.target_language_code)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{SARVAM_BASE_URL}/text-to-speech",
                headers={**_sarvam_headers(), "Content-Type": "application/json"},
                json={
                    "inputs": [request.text],
                    "target_language_code": lang,
                    "speaker": request.speaker,
                    "pitch": request.pitch,
                    "pace": request.pace,
                    "loudness": request.loudness,
                    "speech_sample_rate": request.speech_sample_rate,
                    "enable_preprocessing": request.enable_preprocessing,
                    "model": "bulbul:v2",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, detail=f"Sarvam TTS error {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"TTS service unavailable: {exc}") from exc

    # Sarvam returns base64-encoded audio in "audios" list
    audios = data.get("audios", [])
    if not audios:
        raise HTTPException(502, detail="TTS returned empty audio.")

    audio_bytes = base64.b64decode(audios[0])
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="response.wav"'},
    )


# ---------------------------------------------------------------------------
# POST /voice/ask  — Full voice pipeline
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=VoiceAskResponse)
async def voice_ask(
    file: UploadFile = File(..., description="Audio query file"),
    language_code: str = Form("hi-IN", description="Language spoken in the audio"),
    respond_in_audio: bool = Form(True, description="Return TTS audio in response"),
    speaker: str = Form("anushka", description="TTS voice speaker"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = FADepends(get_db),
):
    """Voice-to-voice legal query pipeline.

    1. Transcribe the audio query (Sarvam STT)
    2. If language is not English, translate query to English
    3. Run through legal query pipeline (CrewAI)
    4. If respond_in_audio=True, convert response to speech (Sarvam TTS)
    5. Return text + audio together

    This endpoint makes it possible for non-literate or regional-language users
    to interact with the legal AI using only voice.
    """
    await check_rate_limit(current_user, db)

    lang = _lang_code(language_code)
    headers = _sarvam_headers()

    # --- Step 1: STT ---
    audio_bytes = await file.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, detail="Audio file too large (max 25 MB).")

    ext = (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()
    mime = _AUDIO_MIME.get(ext, "audio/wav")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            stt_resp = await client.post(
                f"{SARVAM_BASE_URL}/speech-to-text",
                headers=headers,
                files={"file": (file.filename or "audio.wav", audio_bytes, mime)},
                data={"model": "saarika:v2.5", "language_code": lang, "with_timestamps": "false"},
            )
            stt_resp.raise_for_status()
            transcript = stt_resp.json().get("transcript", "")
    except Exception as exc:
        raise HTTPException(502, detail=f"STT failed: {exc}") from exc

    if not transcript:
        raise HTTPException(422, detail="Could not transcribe audio.")

    # --- Step 2: Translate to English if needed ---
    english_query = transcript
    if not language_code.lower().startswith("en"):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                tr_resp = await client.post(
                    f"{SARVAM_BASE_URL}/translate",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "input": transcript,
                        "source_language_code": lang,
                        "target_language_code": "en-IN",
                        "mode": "formal",
                        "model": "mayura:v1",
                    },
                )
                tr_resp.raise_for_status()
                english_query = tr_resp.json().get("translated_text", transcript)
        except Exception:
            english_query = transcript  # fallback: use transcript as-is

    # --- Step 3: Legal query pipeline ---
    try:
        from backend.agents.crew_config import get_crew_for_role
        from backend.agents.query_router import handle_query

        response_text = await handle_query(
            query=english_query,
            user_role=current_user.role,
            crew_factory=get_crew_for_role,
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Legal query pipeline failed: {exc}") from exc

    # --- Step 4: Translate response back if language != English ---
    response_in_lang = response_text
    if not language_code.lower().startswith("en") and SARVAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                tr_resp = await client.post(
                    f"{SARVAM_BASE_URL}/translate",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "input": response_text[:2000],  # TTS has length limits
                        "source_language_code": "en-IN",
                        "target_language_code": lang,
                        "mode": "formal",
                        "model": "mayura:v1",
                    },
                )
                tr_resp.raise_for_status()
                response_in_lang = tr_resp.json().get("translated_text", response_text)
        except Exception:
            response_in_lang = response_text  # fallback: return English

    # --- Step 5: TTS (optional) ---
    audio_base64: str | None = None
    if respond_in_audio and SARVAM_API_KEY:
        tts_input = response_in_lang[:1000]  # cap at 1000 chars to keep audio short
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                tts_resp = await client.post(
                    f"{SARVAM_BASE_URL}/text-to-speech",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "inputs": [tts_input],
                        "target_language_code": lang,
                        "speaker": speaker,
                        "pace": 1.0,
                        "loudness": 1.5,
                        "speech_sample_rate": 16000,
                        "enable_preprocessing": False,
                        "model": "bulbul:v2",
                    },
                )
                tts_resp.raise_for_status()
                audios = tts_resp.json().get("audios", [])
                if audios:
                    audio_base64 = audios[0]  # already base64
        except Exception:
            pass  # TTS failure is non-fatal — still return text

    # Parse metadata from response
    from backend.api.routes.query import _parse_citations, _parse_confidence, _parse_verification_status

    return VoiceAskResponse(
        transcript=transcript,
        response_text=response_text,
        verification_status=_parse_verification_status(response_text),
        confidence=_parse_confidence(response_text),
        citations=[c.model_dump() for c in _parse_citations(response_text)],
        audio_base64=audio_base64,
        language_code=lang,
    )
