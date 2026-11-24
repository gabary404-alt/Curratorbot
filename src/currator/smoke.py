"""Check Currator speech or Wikimedia lookup from the demo computer."""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import mimetypes
import sys
import time
import wave
from pathlib import Path

import httpx

from .config import Settings
from .knowledge import look_up

SAMPLE_TEXT = "Muraho neza!"
MAX_WAVE_BYTES = 9 * 1024 * 1024


def decode_wave(value: object) -> bytes:
    prefix = "data:audio/wav;base64,"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("Currator voice unavailable. Check the Gemini API key.")
    raw = base64.b64decode(value[len(prefix):], validate=True)
    with wave.open(io.BytesIO(raw)) as audio:
        if not audio.getnframes():
            raise ValueError("Currator WAV contains no audio")
    return raw


def run(args: argparse.Namespace) -> None:
    base = args.base_url.rstrip("/")
    stage_start = time.perf_counter()

    def stage(name: str, detail: str) -> None:
        nonlocal stage_start
        now = time.perf_counter()
        print(f"{name} ({now - stage_start:.2f}s) — {detail}", flush=True)
        stage_start = now

    with httpx.Client(timeout=60, follow_redirects=False) as client:
        status = client.get(base + "/api/status")
        status.raise_for_status()
        config = status.json()
        if args.language not in config["speech_input"]:
            raise ValueError(f"{args.language} speech input is unavailable in {config['mode']} mode")
        stage("Server", config["mode"])

        def synthesize(text: str) -> bytes:
            response = client.post(base + "/api/speech/synthesize", json={
                "text": text[:800], "language": args.language,
            })
            response.raise_for_status()
            raw = decode_wave(response.json().get("audio_url"))
            stage("Currator voice", f"{len(raw)} bytes")
            return raw

        if args.audio:
            if args.audio.stat().st_size > MAX_WAVE_BYTES:
                raise ValueError("Recording is too large")
            mime = mimetypes.guess_type(args.audio.name)[0] or "audio/wav"
            mime = {"video/webm": "audio/webm", "video/mp4": "audio/mp4"}.get(mime, mime)
            recording = (args.audio.name, args.audio.read_bytes(), mime)
        elif args.language == "rw":
            recording = ("generated.wav", synthesize(SAMPLE_TEXT), "audio/wav")
        else:
            raise ValueError("Provide an English recording with --audio")

        response = client.post(base + "/api/speech/transcribe", params={"language": args.language},
                               files={"audio": recording})
        response.raise_for_status()
        transcript = response.json()["text"]
        stage("Transcription", transcript)
        expected = args.expect if args.audio else args.expect or "muraho"
        if expected and expected.casefold() not in transcript.casefold():
            raise ValueError(f"Transcript was missing expected text: {expected}")

        response = client.post(base + "/api/chat", json={
            "text": transcript, "language": args.language, "retrieval": "off",
            "session_id": "speech-smoke",
        })
        response.raise_for_status()
        reply = response.json()
        stage("Chat (prepared)" if reply["simulated"] else "Chat (Gemini)", reply["reply"])

        if args.language in config["speech_output"]:
            audio = synthesize(reply["reply"])
            if args.output:
                with args.output.open("xb") as output:
                    output.write(audio)
                print(f"Saved spoken reply to {args.output}")
        else:
            print("Add a Gemini key to check Currator’s spoken output.")


async def check_sources(query: str, language: str, expected: str | None) -> None:
    started = time.perf_counter()
    async with httpx.AsyncClient() as client:
        evidence, sources = await look_up(query, language, client, Settings().wikimedia_user_agent)
    print(f"Wikimedia lookup ({time.perf_counter() - started:.2f}s)")
    for source in sources:
        print(f"{source.label} — {source.url}")
    if not evidence or not sources:
        raise ValueError("No Wikimedia evidence was returned")
    if expected and expected.casefold() not in evidence.casefold():
        raise ValueError(f"Source excerpts did not include {expected!r}")
    print(evidence)


def main() -> int:
    # Windows terminals can have a legacy encoding that cannot display article text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--language", choices=["rw", "en"], default="rw")
    parser.add_argument("--audio", type=Path, help="Use a local recording instead of a generated clip")
    parser.add_argument("--expect", help="Require this text in the transcript (case-insensitive)")
    parser.add_argument("--output", type=Path, help="Save the Kinyarwanda WAV reply to a new file")
    parser.add_argument("--source-query", help="Look up Wikimedia sources without starting the server")
    args = parser.parse_args()
    if args.source_query:
        try:
            asyncio.run(check_sources(args.source_query, args.language, args.expect))
        except (ValueError, httpx.HTTPError, ImportError) as error:
            parser.exit(1, f"Source check failed: {error}\n")
        return 0
    try:
        run(args)
    except (ValueError, OSError, EOFError, wave.Error, httpx.HTTPError) as error:
        if isinstance(error, httpx.HTTPStatusError):
            try:
                detail = error.response.json().get("detail", "Check the provider or server logs.")
            except ValueError:
                detail = "Check the provider or server logs."
            parser.exit(1, f"Speech check failed (HTTP {error.response.status_code}): {detail}\n")
        parser.exit(1, f"Speech check failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
