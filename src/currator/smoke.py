"""Run a timed speech check through a running Currator server."""
from __future__ import annotations

import argparse
import io
import mimetypes
import time
import wave
from pathlib import Path

import httpx

from .speech import safe_audio_url

SAMPLE_TEXT = "Muraho neza!"
MAX_WAVE_BYTES = 9 * 1024 * 1024


def fetch_wave(client: httpx.Client, value: object) -> bytes:
    url = safe_audio_url(value if isinstance(value, str) else None, "")
    if not url:
        raise ValueError("No supported Pindo audio URL was returned")
    raw = bytearray()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_WAVE_BYTES:
                raise ValueError("Pindo audio is too large")
    with wave.open(io.BytesIO(raw)) as audio:
        if audio.getnframes() == 0:
            raise ValueError("Pindo WAV contains no audio")
        print(f"Downloaded {audio.getnframes() / audio.getframerate():.2f}s of WAV audio")
    return bytes(raw)


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
                "text": text[:800], "language": "rw",
            })
            response.raise_for_status()
            stage("Pindo TTS", "Generated a media URL")
            raw = fetch_wave(client, response.json().get("audio_url"))
            stage("Pindo media", f"{len(raw)} bytes")
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

        if args.language == "rw":
            audio = synthesize(reply["reply"])
            if args.output:
                with args.output.open("xb") as output:
                    output.write(audio)
                print(f"Saved spoken reply to {args.output}")
        else:
            print("English playback can be checked on the browser's speaker.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--language", choices=["rw", "en"], default="rw")
    parser.add_argument("--audio", type=Path, help="Use a local recording instead of a generated clip")
    parser.add_argument("--expect", help="Require this text in the transcript (case-insensitive)")
    parser.add_argument("--output", type=Path, help="Save the Kinyarwanda WAV reply to a new file")
    args = parser.parse_args()
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
