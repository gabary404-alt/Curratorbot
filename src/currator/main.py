"""Currator Bot web, audio, knowledge and isolated hardware API."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from .brain import GeminiBrain, mock_reply
from .config import HOSTED, Settings
from .english import LocalEnglishSpeech
from .knowledge import look_up, needs_current_info, needs_wikipedia, news_lookup
from .models import (ChatRequest, ChatResponse, Language, RobotCommand, RobotResult,
                     SensorTelemetry, TranscriptionResponse)
from .rehearsal import REPLIES, quick_reply, rehearsal_reply
from .robot import RobotBridge
from .speech import (
    PindoSpeech, UpstreamFailure, currator_voice, transcribe_automatic, transcribe_english_gemini,
)

settings = Settings()
settings.validate()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        app.state.client = client
        app.state.robot = RobotBridge(settings)
        app.state.sessions = {}
        app.state.greeting_audio = {}
        app.state.english = (
            await asyncio.to_thread(LocalEnglishSpeech, settings.vosk_model_path)
            if settings.vosk_model_path and settings.mode != "mock"
            else None
        )
        receiver = (
            asyncio.create_task(app.state.robot.receive_serial())
            if settings.robot_transport == "serial" else None
        )
        try:
            yield
        finally:
            if receiver is not None:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)


def require_demo_access(credentials: HTTPBasicCredentials | None = Depends(HTTPBasic(auto_error=False))):
    if not HOSTED or settings.mode != "live":
        return
    if credentials is None or not secrets.compare_digest(
        credentials.password.encode(), settings.demo_password.encode()
    ):
        raise HTTPException(
            status_code=401, detail="Demo password required",
            headers={"WWW-Authenticate": 'Basic realm="Currator Bot"'},
        )


app = FastAPI(title="Currator Bot API", version="0.1.0", lifespan=lifespan,
              dependencies=[Depends(require_demo_access)])


def speech_input_languages() -> list[str]:
    if settings.mode == "mock":
        return []
    return ["auto", "rw", "en"] if settings.mode == "live" else (
        ["rw", "en"] if app.state.english else ["rw"]
    )


@app.get("/api/status")
async def status():
    return {
        "name": "Nshuti", "project": "Currator Bot", "mode": settings.mode, "languages": ["rw", "en"],
        "voice_live": settings.mode != "mock",
        "speech_input": speech_input_languages(),
        "speech_output": ["rw", "en"] if settings.mode != "mock" and settings.gemini_api_key else [],
        "motion_enabled": settings.enable_motion, "hosted": HOSTED,
        "robot_transport": settings.robot_transport,
        "note": "Health report shows configuration, not verified upstream availability",
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, accept: str = Header(default="")):
    if "application/x-ndjson" not in accept:
        return await prepare_chat(request)

    async def events():
        messages = asyncio.Queue()

        async def run():
            try:
                reply = await prepare_chat(
                    request, lambda phase: messages.put_nowait({"phase": phase}),
                )
                messages.put_nowait({"reply": reply.model_dump()})
            except HTTPException as exc:
                messages.put_nowait({"error": exc.detail})
            finally:
                messages.put_nowait(None)

        task = asyncio.create_task(run())
        try:
            while (message := await messages.get()) is not None:
                yield json.dumps(message, ensure_ascii=False) + "\n"
            await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


async def prepare_chat(request: ChatRequest, progress=None):
    started = time.monotonic()
    budget = request.latency_budget_ms / 1000 if request.latency_budget_ms else None
    try:
        reply = await asyncio.wait_for(
            answer_chat(request, progress), timeout=min(11, budget) if budget else None,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="This question took too long. Try a shorter question or ask again.",
        ) from exc
    if (not request.include_audio or not settings.gemini_api_key
            or settings.mode == "mock" or reply.language not in {"rw", "en"}):
        return reply
    # These six fixed replies contain no visitor content and have stable pronunciations.
    cacheable = reply.reply in {REPLIES[reply.language][intent] for intent in ("hello", "name", "thanks")}
    if cacheable and reply.reply in app.state.greeting_audio:
        reply.audio_url = app.state.greeting_audio[reply.reply]
        return reply
    if progress is not None:
        progress("preparing")
    try:
        # Keep synthesized audio in the same response and release text if voice is slow.
        remaining = min(4.5, budget - (time.monotonic() - started)) if budget else 8
        if remaining <= 0:
            raise TimeoutError
        reply.audio_url = await asyncio.wait_for(
            currator_voice(reply.reply[:800], settings, app.state.client), timeout=remaining,
        )
        if cacheable and reply.audio_url and len(reply.audio_url) <= 500_000:
            app.state.greeting_audio[reply.reply] = reply.audio_url
    except (TimeoutError, UpstreamFailure):
        reply.audio_error = "Voice is taking longer than usual. Tap Play reply to try again."
    return reply


async def answer_chat(request: ChatRequest, progress=None):
    def report(phase):
        if progress is not None:
            progress(phase)

    report("thinking")
    language = "rw" if request.language == "auto" else request.language
    if settings.mode == "mock":
        return ChatResponse(reply=mock_reply(request.text, language),
                            language=language, simulated=True)
    if settings.mode == "rehearsal":
        if request.retrieval == "on":
            report("researching")
            current = needs_current_info(request.text)
            if current:
                evidence, sources = await news_lookup(request.text, app.state.client)
            else:
                evidence, sources = await look_up(
                    request.text, language, app.state.client, settings.wikimedia_user_agent,
                )
            return ChatResponse(
                reply=(
                    "Reba amasoko akurikira." if language == "rw" else
                    "I found these sources. Live AI can use them to answer your question."
                ) if evidence else (
                    "Sinabonye isoko kuri iki kibazo." if language == "rw" else
                    "I couldn't find a source for that. Try a shorter topic such as Kigali."
                ),
                language=language, sources=sources,
                source_mode="news" if current else "wikipedia",
            )
        return ChatResponse(
            reply=rehearsal_reply(request.text, language),
            language=language, source_mode="rehearsal", simulated=True,
        )
    # In-memory recent history for MVP; no personal recordings stored.
    sessions: dict = app.state.sessions
    history = (
        [turn.model_dump() for turn in request.history]
        if request.history is not None else ([] if HOSTED else sessions.get(request.session_id, []))
    )
    uses_search = request.retrieval != "off" and needs_current_info(request.text)
    wikipedia = not uses_search and (
        request.retrieval == "on"
        or (request.retrieval == "auto" and needs_wikipedia(request.text))
    )
    brain = GeminiBrain(settings, app.state.client)
    query = request.text
    direct_reply = ""
    quick = quick_reply(request.text, request.language) if request.retrieval != "on" else None
    if quick:
        direct_reply, language = quick
        uses_search = wikipedia = False
    elif request.language == "auto":
        try:
            plan = await brain.plan(request.text, history, request.retrieval)
        except UpstreamFailure as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        language = plan.language
        query = plan.query.strip() or request.text
        uses_search = request.retrieval != "off" and plan.route == "news"
        wikipedia = not uses_search and (
            request.retrieval == "on"
            or (request.retrieval == "auto" and plan.route == "reference")
        )
        if plan.route == "answer" and not (uses_search or wikipedia):
            direct_reply = plan.reply.strip()
    extra_info, sources = "", []
    if uses_search or wikipedia:
        report("researching")
    if uses_search and not settings.google_search_grounding:
        extra_info, sources = await news_lookup(query, app.state.client)
    elif wikipedia:
        extra_info, sources = await look_up(
            query, language, app.state.client,
            settings.wikimedia_user_agent,
        )
    if (request.retrieval == "on" or request.language == "auto") and wikipedia and not sources and not settings.google_search_grounding:
        reply = (
            "Sinabonye isoko ryizewe kuri iki kibazo."
            if language == "rw" else "I couldn't find a source for that."
        )
        return ChatResponse(reply=reply, language=language, source_mode="source_unavailable")
    try:
        use_google = settings.google_search_grounding and (uses_search or (wikipedia and not sources))
        if uses_search and not (use_google or sources):
            raise UpstreamFailure("No current sources available")
        if not use_google and not direct_reply:
            report("thinking")
        reply, search_sources = (direct_reply, []) if direct_reply else await brain.answer(
            request.text, language, history, extra_info, use_google=use_google
        )
        if use_google and not search_sources:
            raise UpstreamFailure("Gemini returned no grounded sources")
    except UpstreamFailure as exc:
        # Do not silently fall back to an ungrounded answer for a live-info question.
        if uses_search:
            reply = ("Sinshoboye kubona amakuru agezweho ubu. Ongera ugerageze."
                     if language == "rw" else
                     "I can't verify live information right now. Please try again.")
            return ChatResponse(reply=reply, language=language,
                                source_mode="live_unavailable")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Store bounded session history without permanent persistence.
    if request.history is None and not HOSTED:
        sessions[request.session_id] = (
            history + [{"role": "user", "text": request.text},
                       {"role": "model", "text": reply}]
        )[-8:]
        if len(sessions) > 100:
            sessions.pop(next(iter(sessions)))
    all_sources = (search_sources or sources)[:4]
    return ChatResponse(reply=reply, language=language,
                        source_mode="google" if search_sources else
                        ("news" if uses_search else "wikipedia") if sources else "none",
                        sources=all_sources)


ALLOWED_MIMES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/webm",
    "audio/ogg", "audio/flac", "audio/mp4", "audio/x-m4a", "audio/m4a",
}
MAX_AUDIO_SIZE = (4 if HOSTED else 9) * 1024 * 1024


@app.post("/api/speech/transcribe", response_model=TranscriptionResponse)
async def transcribe(language: str = "rw", language_hint: Language | None = None,
                     audio: UploadFile = File(...)):
    try:
        if language not in {"auto", "rw", "en"}:
            raise HTTPException(status_code=422, detail="Use auto, rw or en")
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
        confirmation = False
        detected_language = None
        if language == "rw":
            transcript = await PindoSpeech(settings, app.state.client).transcribe(raw, content_type)
        elif language == "en" and app.state.english:
            transcript = await app.state.english.transcribe(raw)
        else:
            gemini_mime = {
                "audio/mp4": "audio/m4a", "audio/x-m4a": "audio/m4a", "audio/x-wav": "audio/wav",
            }.get(content_type, content_type)
            if language == "auto":
                transcript, confirmation, detected_language = await transcribe_automatic(
                    raw, content_type, gemini_mime, settings, app.state.client,
                    prefer_rw=language_hint == "rw",
                )
            else:
                transcript = await transcribe_english_gemini(
                    raw, gemini_mime, settings, app.state.client,
                )
        if not transcript:
            raise HTTPException(status_code=422, detail="No speech recognized")
        return TranscriptionResponse(text=transcript, language=language,
                                     needs_confirmation=confirmation,
                                     detected_language=detected_language)
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
    if not settings.gemini_api_key:
        return {"audio_url": None, "provider": "unavailable", "simulated": False}
    try:
        audio = await currator_voice(request.text, settings, app.state.client)
        return {"audio_url": audio, "provider": "currator", "simulated": False}
    except UpstreamFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def require_operator(x_operator_token: str = Header(default="")):
    if HOSTED or not settings.robot_operator_token or not secrets.compare_digest(
        x_operator_token.encode(), settings.robot_operator_token.encode()
    ):
        raise HTTPException(status_code=401, detail="Operator token required")


@app.get("/api/robot/status", dependencies=[Depends(require_operator)])
async def robot_status():
    robot = app.state.robot
    telemetry = robot.telemetry
    age = time.monotonic() - telemetry.received_at if telemetry.value else None
    return {
        "transport": settings.robot_transport,
        "motion_enabled": settings.enable_motion,
        "usb_connected": robot.port is not None,
        "telemetry_fresh": age is not None and age <= 1.5,
        "telemetry": telemetry.value,
        "stop_confirmation_required": robot.motion_uncertain,
    }


@app.post("/api/robot/telemetry", dependencies=[Depends(require_operator)])
async def robot_telemetry(telemetry: SensorTelemetry):
    if settings.robot_transport == "serial":
        raise HTTPException(status_code=409, detail="Serial mode accepts controller telemetry only")
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
                           reason="Controller acknowledged command" if settings.robot_transport == "serial"
                           else "Simulated command dispatched")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Robot transport unavailable") from exc


ROOT = Path(__file__).with_name("static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "index.html")


app.mount("/static", StaticFiles(directory=ROOT), name="static")
