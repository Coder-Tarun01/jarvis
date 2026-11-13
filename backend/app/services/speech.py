"""Optional server-side speech: Whisper transcription and OpenAI/ElevenLabs synthesis.

The browser is the default for both (free, zero setup). These endpoints exist so
STT_PROVIDER=whisper, TTS_PROVIDER=openai or TTS_PROVIDER=elevenlabs can be
flipped on from .env. Whisper and OpenAI TTS reuse OPENAI_API_KEY — the same key
that drives the LLM.
"""

from __future__ import annotations

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import JarvisError
from ..core.logging import get_logger
from ..core.utils import retry_async

log = get_logger("speech")

OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class SpeechError(JarvisError):
    """Speech provider is misconfigured or failed."""


async def transcribe(audio: bytes, filename: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.openai_api_key:
        raise SpeechError(
            "STT_PROVIDER=whisper needs OPENAI_API_KEY. Set it, or use STT_PROVIDER=browser."
        )
    if not audio:
        raise SpeechError("empty audio upload")

    files = {
        "file": (filename or "audio.webm", audio, "application/octet-stream"),
    }
    data = {"model": settings.openai_stt_model or "whisper-1"}
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post(OPENAI_STT_URL, headers=headers, data=data, files=files)

    response = await retry_async(
        call, attempts=3, label="whisper", retry_on=(httpx.HTTPError,)
    )
    if response.status_code >= 400:
        raise SpeechError(f"Whisper failed (HTTP {response.status_code}): {response.text[:200]}")
    return (response.json().get("text") or "").strip()


async def synthesize(text: str, settings: Settings | None = None) -> bytes:
    """Dispatch to the configured server-side TTS provider."""
    settings = settings or get_settings()
    provider = (settings.tts_provider or "browser").strip().lower()

    if provider == "openai":
        return await synthesize_openai(text, settings)
    if provider == "elevenlabs":
        return await synthesize_elevenlabs(text, settings)
    raise SpeechError(
        "TTS_PROVIDER=browser means the browser speaks the reply, so there is "
        "nothing to synthesize here. Set TTS_PROVIDER=openai or elevenlabs."
    )


async def synthesize_openai(text: str, settings: Settings | None = None) -> bytes:
    """Neural TTS through the OpenAI audio endpoint (reuses OPENAI_API_KEY)."""
    settings = settings or get_settings()
    if not settings.openai_api_key:
        raise SpeechError(
            "TTS_PROVIDER=openai needs OPENAI_API_KEY. Set it, or use TTS_PROVIDER=browser."
        )
    text = (text or "").strip()
    if not text:
        raise SpeechError("nothing to say")

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openai_tts_model or "gpt-4o-mini-tts",
        "voice": settings.openai_tts_voice or "alloy",
        "input": text[:4000],
        "response_format": "mp3",
    }

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post(OPENAI_TTS_URL, headers=headers, json=payload)

    response = await retry_async(
        call, attempts=3, label="openai.tts", retry_on=(httpx.HTTPError,)
    )
    if response.status_code >= 400:
        raise SpeechError(
            f"OpenAI TTS failed (HTTP {response.status_code}): {response.text[:200]}"
        )
    return response.content


async def synthesize_elevenlabs(text: str, settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    if not settings.elevenlabs_api_key:
        raise SpeechError(
            "TTS_PROVIDER=elevenlabs needs ELEVENLABS_API_KEY. "
            "Set it, or use TTS_PROVIDER=browser."
        )
    text = (text or "").strip()
    if not text:
        raise SpeechError("nothing to say")

    url = ELEVENLABS_URL.format(voice_id=settings.elevenlabs_voice_id)
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text[:2500],
        "model_id": settings.elevenlabs_model or "eleven_turbo_v2_5",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
    }

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post(url, headers=headers, json=payload)

    response = await retry_async(
        call, attempts=3, label="elevenlabs", retry_on=(httpx.HTTPError,)
    )
    if response.status_code >= 400:
        raise SpeechError(
            f"ElevenLabs failed (HTTP {response.status_code}): {response.text[:200]}"
        )
    return response.content
