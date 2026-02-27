"""Pydantic schemas for voice (TTS / STT) endpoints."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Language codes supported by Sarvam AI
# ---------------------------------------------------------------------------

SARVAM_LANGUAGE_CODES = Literal[
    "hi-IN",  # Hindi
    "ta-IN",  # Tamil
    "te-IN",  # Telugu
    "kn-IN",  # Kannada
    "ml-IN",  # Malayalam
    "bn-IN",  # Bengali
    "mr-IN",  # Marathi
    "gu-IN",  # Gujarati
    "pa-IN",  # Punjabi
    "ur-IN",  # Urdu
    "or-IN",  # Odia
    "en-IN",  # Indian English
]

# ---------------------------------------------------------------------------
# Speech-to-Text
# ---------------------------------------------------------------------------

class STTResponse(BaseModel):
    transcript: str
    language_code: str
    confidence: Optional[float] = None
    duration_seconds: Optional[float] = None
    word_timestamps: Optional[list] = None


# ---------------------------------------------------------------------------
# Text-to-Speech
# ---------------------------------------------------------------------------

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    target_language_code: SARVAM_LANGUAGE_CODES = "hi-IN"
    speaker: Literal[
        "anushka", "manisha", "vidya",         # female — bulbul:v2
        "arjun", "abhilash", "ishaan",          # male   — bulbul:v2
    ] = "anushka"
    pitch: float = Field(0.0, ge=-0.5, le=0.5)
    pace: float = Field(1.0, ge=0.5, le=2.0)
    loudness: float = Field(1.0, ge=0.5, le=2.0)
    speech_sample_rate: Literal[8000, 16000, 22050, 24000] = 16000
    enable_preprocessing: bool = False


# ---------------------------------------------------------------------------
# Voice Ask (STT → Legal Query → TTS pipeline)
# ---------------------------------------------------------------------------

class VoiceAskResponse(BaseModel):
    transcript: str                   # What the user said
    response_text: str                # Legal answer text
    verification_status: str
    confidence: str
    citations: list = []
    audio_base64: Optional[str] = None  # TTS audio, base64-encoded WAV
    language_code: str
    disclaimer: str = (
        "This is AI-assisted legal information. "
        "Consult a qualified legal professional for advice specific to your situation."
    )
