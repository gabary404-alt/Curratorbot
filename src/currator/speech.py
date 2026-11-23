"""Pindo Kinyarwanda + Gemini English adapters; no secret logging."""
from __future__ import annotations

import asyncio
import base64
import io
import re
import wave
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel

from .config import Settings
from .kinyarwanda import LISTENING_GUIDANCE

PINDO_ROOT = "https://api.pindo.io/ai"
ALLOWED_MEDIA_HOSTS = {
    "api.pindo.io",
    "pindo-ai-api-generated.s3.af-south-1.amazonaws.com",
}


class UpstreamFailure(RuntimeError):
    pass


class DetectedSpeech(BaseModel):
    text: str
    language: Literal["rw", "mixed", "other"]
    unclear: bool


async def transcribe_automatic(
    raw: bytes, mime: str, gemini_mime: str, settings: Settings, client: httpx.AsyncClient,
) -> tuple[str, bool]:
    result = await transcribe_english_gemini(raw, gemini_mime, settings, client, automatic=True)
    try:
        detected = DetectedSpeech.model_validate_json(result)
    except ValueError as exc:
        raise UpstreamFailure("Speech detection couldn't verify the recording. Try again.") from exc
    original = detected.text.strip()
    if not original or detected.language != "rw":
        return original, detected.unclear
    try:
        specialist = await asyncio.wait_for(PindoSpeech(settings, client).transcribe(raw, mime), 7)
    except (TimeoutError, UpstreamFailure):
        return original, detected.unclear
    if not specialist:
        return original, detected.unclear
    a = re.findall(r"\w+", original.casefold())
    b = re.findall(r"\w+", specialist.casefold())
    differs = a != b
    return specialist, detected.unclear or differs


async def casual_english_audio(text: str, settings: Settings, client: httpx.AsyncClient) -> str | None:
    """Use the existing Gemini key for an expressive English voice, with a short timeout."""
    try:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash-preview-tts:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": (
                    "Read only the quoted passage. Sound like a relaxed, upbeat teammate "
                    "speaking to one visitor, with light warmth and natural pauses.\n"
                    f"Passage:\n{text}"
                )}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": "Zubenelgenubi"},
                    }},
                },
            },
            timeout=8,
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        raw = next(part["inlineData"]["data"] for part in parts if "inlineData" in part)
        if len(raw) > 3_200_000:
            return None
        pcm = base64.b64decode(raw, validate=True)
        if not pcm or len(pcm) % 2:
            return None
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        return "data:audio/wav;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (httpx.HTTPError, KeyError, IndexError, StopIteration, TypeError, ValueError):
        return None


def _read_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise UpstreamFailure("Unexpected Pindo response format")
    if payload.get("status") == "error" or payload.get("error"):
        raise UpstreamFailure("Pindo returned an error")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise UpstreamFailure("Unexpected Pindo response format")
    return data


def safe_audio_url(value: str | None, base_url: str) -> str | None:
    """Only expose validated HTTPS media locations; reject private/unknown hosts."""
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    try:
        reference = urlsplit(value)
        if reference.scheme:
            url = value
        elif reference.netloc or value.startswith("//") or not base_url:
            return None
        else:
            url = urljoin(base_url.rstrip("/") + "/", value.lstrip("/"))
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or parts.hostname not in ALLOWED_MEDIA_HOSTS
        ):
            return None
    except ValueError:
        return None
    return url


class PindoSpeech:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def endpoint(self, kind: str, lang: str) -> str:
        suffix = "" if self.settings.pindo_token else "/public"
        return f"{PINDO_ROOT}/{kind}/{lang}{suffix}"

    @property
    def headers(self) -> dict[str, str]:
        return (
            {"Authorization": f"Bearer {self.settings.pindo_token}"}
            if self.settings.pindo_token
            else {}
        )

    async def transcribe(self, raw: bytes, mime: str) -> str:
        suffix = {"audio/wav": "wav", "audio/x-wav": "wav",
                  "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg",
                  "audio/flac": "flac", "audio/mp4": "mp4",
                  "audio/m4a": "m4a", "audio/x-m4a": "m4a"}.get(mime, "webm")
        try:
            resp = await self.client.post(
                self.endpoint("stt", "rw"),
                headers=self.headers,
                files={"audio": (f"recording.{suffix}", raw, mime)},
                timeout=30,
            )
            resp.raise_for_status()
            transcript = _read_data(resp.json()).get("text")
            return transcript.strip() if isinstance(transcript, str) else ""
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise UpstreamFailure("Pindo rate limit reached. Try again shortly.") from exc
            raise UpstreamFailure("Pindo service unavailable") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise UpstreamFailure("Kinyarwanda speech recognition unavailable") from exc

    async def speak(self, text: str) -> str | None:
        body: dict[str, str | float] = {"text": text[:800], "speech_rate": 1.0}
        if self.settings.pindo_token:
            body["lang"] = "rw"
        try:
            for attempt in range(2):
                resp = await self.client.post(
                    self.endpoint("tts", "rw"), headers=self.headers, json=body, timeout=20,
                )
                if resp.status_code not in {500, 502, 503, 504} or attempt == 1:
                    break
                await asyncio.sleep(0.5)
            resp.raise_for_status()
            raw_url = _read_data(resp.json()).get("generated_audio_url")
            return safe_audio_url(raw_url, self.settings.pindo_media_base_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise UpstreamFailure("Pindo rate limit reached. Try again shortly.") from exc
            raise UpstreamFailure("Pindo service unavailable") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise UpstreamFailure("Kinyarwanda speech generation unavailable") from exc


async def transcribe_english_gemini(
    raw: bytes, mime: str, settings: Settings, client: httpx.AsyncClient, *, automatic: bool = False,
) -> str:
    """English ASR with Gemini's audio input; validated independently in live mode."""
    if not settings.gemini_api_key:
        raise UpstreamFailure("GEMINI_API_KEY not set")
    audio = base64.b64encode(raw).decode("ascii")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body = {
        "contents": [{"parts": [
            {"text": (
                LISTENING_GUIDANCE
                if automatic else "Transcribe this English speech verbatim. Return ONLY the transcript."
            )},
            {"inline_data": {"mime_type": mime, "data": audio}},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 350},
    }
    if automatic:
        body["generationConfig"].update(
            responseMimeType="application/json",
            responseJsonSchema=DetectedSpeech.model_json_schema(),
        )
    try:
        resp = await client.post(
            endpoint, json=body, headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=35,
        )
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        parts = candidates[0]["content"]["parts"] if candidates else []
        return " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise UpstreamFailure("Speech recognition unavailable") from exc
