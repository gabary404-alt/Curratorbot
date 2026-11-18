"""Currator Bot web, audio, knowledge and isolated hardware API."""
from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from .brain import GeminiBrain, mock_reply
from .config import Settings
from .english import LocalEnglishSpeech
from .knowledge import look_up, needs_current_info, needs_wikipedia
from .models import (ChatRequest, ChatResponse, Language, RobotCommand, RobotResult,
                     SensorTelemetry, TranscriptionResponse)
from .rehearsal import REPLIES, rehearsal_reply
from .robot import RobotBridge
from .speech import PindoSpeech, UpstreamFailure, transcribe_english_gemini

settings = Settings()
settings.validate()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        app.state.client = client
        app.state.robot = RobotBridge(settings)
        app.state.sessions = {}
        app.state.speech_cache = OrderedDict()
        app.state.english = (
            await asyncio.to_thread(LocalEnglishSpeech, settings.vosk_model_path)
            if settings.vosk_model_path and settings.mode != "mock"
            else None
        )
        yield


app = FastAPI(title="Currator Bot API", version="0.1.0", lifespan=lifespan)


def speech_input_languages() -> list[Language]:
    if settings.mode == "mock":
        return []
    return ["rw", "en"] if settings.mode == "live" or app.state.english else ["rw"]


@app.get("/api/status")
async def status():
    return {
        "name": "Currator Bot", "mode": settings.mode, "languages": ["rw", "en"],
        "voice_live": settings.mode != "mock",
        "speech_input": speech_input_languages(),
        "speech_output": [] if settings.mode == "mock" else ["rw", "en"],
        "motion_enabled": settings.enable_motion,
        "robot_transport": settings.robot_transport,
        "note": "Health report shows configuration, not verified upstream availability",
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if settings.mode == "mock":
        return ChatResponse(reply=mock_reply(request.text, request.language),
                            language=request.language, simulated=True)
    if settings.mode == "rehearsal":
        return ChatResponse(
            reply=rehearsal_reply(request.text, request.language),
            language=request.language, source_mode="rehearsal", simulated=True,
        )
    # In-memory recent history for MVP; no personal recordings stored.
    sessions: dict = app.state.sessions
    history = sessions.get(request.session_id, [])
    uses_search = request.retrieval != "off" and needs_current_info(request.text)
    wikipedia = not uses_search and (
        request.retrieval == "on"
        or (request.retrieval == "auto" and needs_wikipedia(request.text))
    )
    extra_info, sources = "", []
    if wikipedia:
        extra_info, sources = await look_up(
            request.text, request.language, app.state.client,
            settings.wikimedia_user_agent,
        )
    if request.retrieval == "on" and wikipedia and not sources:
        reply = (
            "Sinabonye isoko ryizewe kuri iki kibazo."
            if request.language == "rw" else "I couldn't find a source for that."
        )
        return ChatResponse(reply=reply, language=request.language, source_mode="source_unavailable")
    brain = GeminiBrain(settings, app.state.client)
    try:
        if uses_search and not settings.google_search_grounding:
            raise UpstreamFailure("Google Search grounding is disabled")
        reply, search_sources = await brain.answer(
            request.text, request.language, history, extra_info, use_google=uses_search
        )
        if uses_search and not search_sources:
            raise UpstreamFailure("Gemini returned no grounded sources")
    except UpstreamFailure as exc:
        # Do not silently fall back to an ungrounded answer for a live-info question.
        if uses_search:
            reply = ("Sinshoboye kubona amakuru agezweho ubu. Ongera ugerageze."
                     if request.language == "rw" else
                     "I can't verify live information right now. Please try again.")
            return ChatResponse(reply=reply, language=request.language,
                                source_mode="live_unavailable")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Store bounded session history without permanent persistence.
    sessions[request.session_id] = (
        history + [{"role": "user", "text": request.text},
                   {"role": "model", "text": reply}]
    )[-8:]
    if len(sessions) > 100:
        sessions.pop(next(iter(sessions)))
    all_sources = (search_sources or sources)[:4]
    return ChatResponse(reply=reply, language=request.language,
                        source_mode="google" if search_sources else
                        "wikipedia" if sources else "none",
                        sources=all_sources)


ALLOWED_MIMES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/webm",
    "audio/ogg", "audio/flac", "audio/mp4", "audio/x-m4a", "audio/m4a",
}
MAX_AUDIO_SIZE = 9 * 1024 * 1024


@app.post("/api/speech/transcribe", response_model=TranscriptionResponse)
async def transcribe(language: str = "rw", audio: UploadFile = File(...)):
    try:
        if language not in {"rw", "en"}:
            raise HTTPException(status_code=422, detail="Use rw or en")
        if language not in speech_input_languages():
            raise HTTPException(status_code=503, detail="Speech recognition is unavailable in this mode")
        content_type = (audio.content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_MIMES:
            raise HTTPException(status_code=415, detail="Unsupported audio type")
        raw = await audio.read(MAX_AUDIO_SIZE + 1)
        if not raw:
            raise HTTPException(status_code=422, detail="Recording is empty")
        if len(raw) > MAX_AUDIO_SIZE:
            raise HTTPException(status_code=413, detail="Recording is too large")
        if language == "rw":
            transcript = await PindoSpeech(settings, app.state.client).transcribe(raw, content_type)
        elif app.state.english:
            transcript = await app.state.english.transcribe(raw)
        else:
            gemini_mime = {
                "audio/mp4": "audio/m4a", "audio/x-m4a": "audio/m4a", "audio/x-wav": "audio/wav",
            }.get(content_type, content_type)
            transcript = await transcribe_english_gemini(
                raw, gemini_mime, settings, app.state.client,
            )
        if not transcript:
            raise HTTPException(status_code=422, detail="No speech recognized")
        return TranscriptionResponse(text=transcript, language=language)
    except UpstreamFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        await audio.close()


class SpeakRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
    language: Language = "rw"


@app.post("/api/speech/synthesize")
async def synthesize(request: SpeakRequest):
    if settings.mode == "mock":
        return {"audio_url": None, "provider": "mock", "simulated": True}
    if request.language == "en":
        # English speech uses the browser's local speechSynthesis in prototype.
        return {"audio_url": None, "provider": "browser-english", "simulated": False}
    cache = app.state.speech_cache
    cached = cache.get(request.text)
    if cached and cached[1] > time.monotonic():
        cache.move_to_end(request.text)
        return {"audio_url": cached[0], "provider": "pindo", "simulated": False}
    try:
        link = await PindoSpeech(settings, app.state.client).speak(request.text)
        if not link:
            raise HTTPException(
                status_code=502,
                detail="Pindo returned a missing or unsupported audio URL",
            )
        # Only cache unsigned media URLs and keep the cache in memory.
        if settings.mode == "rehearsal" and request.text in REPLIES["rw"].values() and "?" not in link:
            cache[request.text] = (link, time.monotonic() + 300)
            cache.move_to_end(request.text)
            if len(cache) > 64:
                cache.popitem(last=False)
        return {"audio_url": link, "provider": "pindo", "simulated": False}
    except UpstreamFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def require_operator(x_operator_token: str = Header(default="")):
    if not settings.robot_operator_token or not secrets.compare_digest(
        x_operator_token, settings.robot_operator_token
    ):
        raise HTTPException(status_code=401, detail="Operator token required")


@app.post("/api/robot/telemetry", dependencies=[Depends(require_operator)])
async def robot_telemetry(telemetry: SensorTelemetry):
    app.state.robot.update_telemetry(telemetry)
    return {"accepted": True, "note": "Telemetry accepted; firmware must enforce safety"}


@app.post("/api/robot/command", response_model=RobotResult,
          dependencies=[Depends(require_operator)])
async def robot_command(command: RobotCommand):
    try:
        actual = await app.state.robot.send(command)
        return RobotResult(accepted=True, action=actual["cmd"],
                           transport=settings.robot_transport,
                           simulated=settings.robot_transport == "mock",
                           reason="Command dispatched, not proof of motor execution")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Robot transport unavailable") from exc


ROOT = Path(__file__).with_name("static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "index.html")


app.mount("/static", StaticFiles(directory=ROOT), name="static")
