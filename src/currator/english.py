"""Optional offline English transcription with a locally installed Vosk model."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from .speech import UpstreamFailure

SAMPLE_RATE = 16000


class LocalEnglishSpeech:
    def __init__(self, model_path: str):
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError("Install currator-bot[english] to use VOSK_MODEL_PATH") from error
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise RuntimeError("Install FFmpeg and add it to PATH to use VOSK_MODEL_PATH")
        if not Path(model_path).is_dir():
            raise RuntimeError("VOSK_MODEL_PATH must point to the extracted Vosk model directory")
        try:
            self.model = Model(model_path)
        except Exception as error:
            raise RuntimeError("Vosk could not load the model at VOSK_MODEL_PATH") from error
        self.recognizer = KaldiRecognizer
        self._slot = asyncio.Lock()

    async def transcribe(self, raw: bytes) -> str:
        async with self._slot:
            return await asyncio.to_thread(self._transcribe, raw)

    def _transcribe(self, raw: bytes) -> str:
        try:
            result = subprocess.run(
                [
                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-protocol_whitelist", "pipe", "-i", "pipe:0", "-map", "0:a:0",
                    "-t", "16", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
                ],
                input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8,
                check=True,
            )
        except subprocess.CalledProcessError:
            return ""
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpstreamFailure("Local English audio conversion unavailable") from error
        if not result.stdout:
            return ""

        recognizer = self.recognizer(self.model, SAMPLE_RATE)
        segments = []
        for start in range(0, len(result.stdout), 8000):
            if recognizer.AcceptWaveform(result.stdout[start:start + 8000]):
                segments.append(json.loads(recognizer.Result()).get("text", ""))
        segments.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(segment for segment in segments if segment).strip()
