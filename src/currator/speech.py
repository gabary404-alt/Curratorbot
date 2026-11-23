"""Pindo and Gemini speech recognition, plus Currator's shared voice."""
from __future__ import annotations

import asyncio
import base64
import re
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel

from .config import Settings
from .gemini_http import failure_message, generate, logger
from .kinyarwanda import LISTENING_GUIDANCE, prepare_for_speech

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
) -> tuple[str, bool, str]:
    result = await transcribe_english_gemini(raw, gemini_mime, settings, client, automatic=True)
    try:
        detected = DetectedSpeech.model_validate_json(result)
    except ValueError as exc:
        raise UpstreamFailure("Speech detection couldn't verify the recording. Try again.") from exc
    original = detected.text.strip()
    if not original or detected.language != "rw":
        return original, detected.unclear, detected.language
    try:
        specialist = await asyncio.wait_for(PindoSpeech(settings, client).transcribe(raw, mime), 7)
    except (TimeoutError, UpstreamFailure):
        return original, detected.unclear, detected.language
    if not specialist:
        return original, detected.unclear, detected.language
    a = re.findall(r"\w+", original.casefold())
    b = re.findall(r"\w+", specialist.casefold())
    materially_different = SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.55
    def critical(tokens):
        return [word for word in tokens if (
            any(char.isdigit() for char in word) or word.startswith(("sin", "nti", "nta"))
        )]

    needs_review = detected.unclear or materially_different or critical(a) != critical(b)
    return specialist, needs_review, detected.language


async def currator_voice(text: str, settings: Settings, client: httpx.AsyncClient) -> str:
    """Speak the supplied text using the same Gemini voice in both languages."""
    try:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "model": "gemini-3.8-flash-lite-tts",
                "store": False,
                "input": [{"type": "user_input", "content": [{
                    "type": "text",
                    "text": prepare_for_speech(text),
                    "annotations": [{
                        "type": "speech_metadata",
                        "style": (
                            "A warm, relaxed conversation partner. Use the natural rhythm "
                            "of the language, breathe at punctuation, and pronounce Kinyarwanda "
                            "names and vowel sounds carefully. Read only the supplied words."
                        ),
                    }],
                }]}],
                "response_format": {"type": "audio"},
                "generation_config": {
                    "speech_config": [{"voice": "Zubenelgenubi"}],
                },
            },
            timeout=18,
        )
        response.raise_for_status()
        clips = [
            item["data"] for step in response.json()["steps"]
            if step["type"] == "model_output"
            for item in step["content"] if item["type"] == "audio"
        ]
        raw = clips[-1]
        if len(raw) > 3_200_000 or not base64.b64decode(raw, validate=True).startswith(b"RIFF"):
            raise ValueError("Invalid WAV")
        return "data:audio/wav;base64," + raw
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise UpstreamFailure("Nshuti's voice is unavailable. Try playing the reply again.") from exc


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
        body: dict[str, str | float] = {
            "text": prepare_for_speech(text)[:800],
            "speech_rate": 0.96 if self.settings.mode == "live" else 1.0,
        }
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
        resp = await generate(
            client, endpoint, body=body, key=settings.gemini_api_key,
            operation="speech recognition", timeout=14,
        )
        candidates = resp.json().get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    except httpx.HTTPError as exc:
        raise UpstreamFailure(failure_message(exc, "speech recognition")) from exc
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Gemini speech unreadable response error=%s", type(exc).__name__)
        raise UpstreamFailure("Gemini returned an unreadable transcript. Please try again.") from exc
