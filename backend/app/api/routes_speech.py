"""Optional server-side speech endpoints (Whisper STT / ElevenLabs TTS)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from ..core.config import get_settings
from ..core.schemas import SpeakRequest
from ..core.security import require_auth
from ..services import speech

router = APIRouter(
    prefix="/api/speech", tags=["speech"], dependencies=[Depends(require_auth)]
)

MAX_AUDIO_BYTES = 25 * 1024 * 1024


@router.get("/config")
def speech_config() -> dict:
    settings = get_settings()
    return {
        "stt_provider": settings.stt_provider,
        "tts_provider": settings.tts_provider,
        "openai_ready": bool(settings.openai_api_key),
        "whisper_ready": bool(settings.openai_api_key),
        "openai_tts_ready": bool(settings.openai_api_key),
        "openai_tts_model": settings.openai_tts_model,
        "elevenlabs_ready": bool(settings.elevenlabs_api_key),
    }


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (25 MB max)")
    try:
        text = await speech.transcribe(audio, file.filename or "audio.webm")
    except speech.SpeechError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"text": text}


@router.post("/speak", response_class=Response)
async def speak(payload: SpeakRequest) -> Response:
    try:
        audio = await speech.synthesize(payload.text)
    except speech.SpeechError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=audio,
        media_type="audio/mpeg",
        status_code=status.HTTP_200_OK,
        headers={"Cache-Control": "no-store"},
    )
