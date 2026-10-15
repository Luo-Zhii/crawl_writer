"""Text-to-Speech API endpoints for chapter audio."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.tts.capcut import tts_service

router = APIRouter(prefix="/tts", tags=["tts"])


class SynthesizeRequest(BaseModel):
    """Request to synthesize text to audio."""

    text: str = Field(..., min_length=1, max_length=5000, description="Text to speak")
    lang: str = Field("vi", description="Language: 'vi' or 'zh'")
    voice_id: str = Field("BV421_vivn_streaming", description="CapCut voice ID")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")


class VoiceInfo(BaseModel):
    """Information about a TTS voice."""

    id: str
    name: str
    gender: str


@router.get("/status", tags=["tts"])
async def tts_status():
    """Check if TTS service is available."""
    return {
        "available": tts_service.is_available(),
        "service": "capcut",
    }


@router.get("/voices", tags=["tts"])
async def list_voices(lang: str = Query("vi")):
    """
    List available voices for a language.
    
    Supported languages: vi (Vietnamese), zh (Chinese), en (English), ja (Japanese),
    th (Thai), es (Spanish), de (German), fr (French), pt (Portuguese), id (Indonesian)
    """
    voices = tts_service.list_voices(lang)
    return {"lang": lang, "count": len(voices), "voices": voices}


@router.post("/synthesize", tags=["tts"])
async def synthesize(request: SynthesizeRequest):
    """
    Synthesize text to speech and return audio file.

    Returns audio file with content-type: audio/wav
    """
    if not tts_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="TTS service not configured. Set up CapCut API credentials.",
        )

    # Validate language and get voices
    if request.lang not in ["vi", "zh", "en", "ja", "th", "es", "de", "fr", "pt", "id"]:
        raise HTTPException(
            status_code=400,
            detail=f"Language '{request.lang}' not supported",
        )
    
    voices = tts_service.list_voices(request.lang)
    if not voices:
        raise HTTPException(
            status_code=400,
            detail=f"No voices available for language '{request.lang}'",
        )

    # Check if voice exists
    if not any(v["id"] == request.voice_id for v in voices):
        raise HTTPException(
            status_code=400,
            detail=f"Voice '{request.voice_id}' not found for language '{request.lang}'",
        )

    # Synthesize
    audio_bytes = await tts_service.synthesize(
        text=request.text,
        lang=request.lang,
        voice_id=request.voice_id,
        speed=request.speed,
    )

    if not audio_bytes:
        raise HTTPException(
            status_code=500,
            detail="Audio synthesis failed",
        )

    return {
        "audio": audio_bytes.hex(),  # Return as hex string (can be converted back to bytes)
        "lang": request.lang,
        "voice_id": request.voice_id,
        "speed": request.speed,
        "text_length": len(request.text),
    }
