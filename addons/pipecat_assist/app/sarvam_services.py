"""Sarvam AI speech-to-text and text-to-speech services for the composed pipeline.

pipecat-ai has no built-in Sarvam integration, so these subclass pipecat's own
``SegmentedSTTService`` and ``TTSService`` base classes and talk to Sarvam's REST
API (https://api.sarvam.ai) directly, following the same shape as pipecat's own
file-upload STT services (e.g. ElevenLabs) and plain request/response TTS services
(e.g. Google's HTTP TTS service).
"""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator

import httpx
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from app.config import (
    DEFAULT_SARVAM_LANGUAGE,
    DEFAULT_SARVAM_STT_MODEL,
    DEFAULT_SARVAM_TTS_MODEL,
    DEFAULT_SARVAM_TTS_VOICE,
)

SARVAM_BASE_URL = "https://api.sarvam.ai"


class SarvamSTTService(SegmentedSTTService):
    """Speech-to-text using Sarvam AI's file-based speech-to-text API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_SARVAM_STT_MODEL,
        language_code: str | None = None,
        base_url: str = SARVAM_BASE_URL,
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._model = model
        self._language_code = (language_code or "").strip() or None
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

    def can_generate_metrics(self) -> bool:
        return True

    async def _transcribe_audio(self, audio_data: bytes) -> dict:
        headers = {"api-subscription-key": self._api_key}
        files = {"file": ("audio.wav", audio_data, "audio/wav")}
        data = {"model": self._model}
        if self._language_code:
            data["language_code"] = self._language_code

        response = await self._client.post(
            f"{self._base_url}/speech-to-text",
            headers=headers,
            data=data,
            files=files,
        )
        if response.status_code != 200:
            logger.error(f"Sarvam STT error: {response.status_code} {response.text}")
            raise RuntimeError(f"Sarvam STT failed with status {response.status_code}")
        return response.json()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        try:
            await self.start_processing_metrics()
            result = await self._transcribe_audio(audio)
            text = (result.get("transcript") or "").strip()
            if text:
                detected_language = result.get("language_code") or self._language_code or "en-IN"
                await self.stop_processing_metrics()
                yield TranscriptionFrame(
                    text,
                    self._user_id,
                    time_now_iso8601(),
                    detected_language,
                )
        except Exception as exc:
            logger.exception("Sarvam STT request failed")
            yield ErrorFrame(error=f"Sarvam STT error: {exc}")


class SarvamTTSService(TTSService):
    """Text-to-speech using Sarvam AI's text-to-speech API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_SARVAM_TTS_MODEL,
        voice: str = DEFAULT_SARVAM_TTS_VOICE,
        language_code: str = DEFAULT_SARVAM_LANGUAGE,
        speed: float = 1.0,
        base_url: str = SARVAM_BASE_URL,
        sample_rate: int | None = 24000,
        **kwargs,
    ):
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._language_code = language_code
        self._speed = speed
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=45.0)

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"{self}: Generating Sarvam TTS [{text}]")
        try:
            headers = {
                "api-subscription-key": self._api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text": text,
                "language_code": self._language_code,
                "model": self._model,
                "speaker": self._voice,
                "pace": self._speed,
                "speech_sample_rate": self.sample_rate,
                "output_audio_codec": "linear16",
            }

            response = await self._client.post(
                f"{self._base_url}/text-to-speech",
                headers=headers,
                json=payload,
            )
            if response.status_code != 200:
                logger.error(f"Sarvam TTS error: {response.status_code} {response.text}")
                raise RuntimeError(f"Sarvam TTS failed with status {response.status_code}")

            await self.start_tts_usage_metrics(text)

            data = response.json()
            audio = b"".join(base64.b64decode(chunk) for chunk in data.get("audios") or [])
            if not audio:
                raise RuntimeError("Sarvam TTS returned no audio")
            if audio.startswith(b"RIFF"):
                audio = audio[44:]

            chunk_size = self.chunk_size
            first_chunk = True
            for i in range(0, len(audio), chunk_size):
                chunk = audio[i : i + chunk_size]
                if not chunk:
                    break
                if first_chunk:
                    await self.stop_ttfb_metrics()
                    first_chunk = False
                yield TTSAudioRawFrame(chunk, self.sample_rate, 1, context_id=context_id)
        except Exception as exc:
            logger.exception("Sarvam TTS request failed")
            yield ErrorFrame(error=f"Sarvam TTS error: {exc}")
