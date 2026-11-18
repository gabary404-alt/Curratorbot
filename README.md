# Currator Bot

Kinyarwanda-first voice assistant for the Currator wheeled robot demo. The software runs on a laptop before the robot arrives.

| Mode | Replies | Kinyarwanda speech | English speech |
| --- | --- | --- | --- |
| `mock` | Prepared, offline | Disabled | Disabled |
| `rehearsal` | Prepared, labeled | Pindo microphone transcription and spoken replies | Browser voice. Microphone available with the optional local Vosk model |
| `live` | Gemini | Pindo microphone transcription and spoken replies | Gemini or local Vosk microphone transcription, plus browser voice |

## Run the voice rehearsal

Install Python 3.11+ and run these commands from the repository directory.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

Set `CURRATOR_MODE=rehearsal` in `.env`, then start the server.

```bash
python -m uvicorn currator.main:app --host 127.0.0.1 --port 8000
```

Open [the console](http://127.0.0.1:8000/) in a browser. Choose Kinyarwanda, tap the microphone, say **“Witwa nde?”**, and tap again. The page shows the transcript and plays the prepared reply in Pindo's voice. Try **“Muraho”**, **“Ukora iki?”**, or **“Urakoze”** next. For English, select English and type **“What's your name?”**. Check the browser's installed English voice and speaker volume.

Pindo's public endpoints require internet access and are rate-limited by IP. Rehearsal uses no API key. The robot's movement controls are separate from this screen.

## Optional offline English recognition

1. Install [FFmpeg](https://ffmpeg.org/download.html) and make it available on `PATH`.
2. Run `python -m pip install -e '.[english]'`.
3. Download and extract the [small US English Vosk model](https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip). Keep it outside the repo.
4. Set `VOSK_MODEL_PATH` to the extracted model directory in `.env` and restart. This takes precedence over Gemini for English transcription.

## Live AI setup

Create a free-tier [Google AI Studio API key](https://aistudio.google.com/apikey), keep billing disabled, and put it in the local `.env` as `GEMINI_API_KEY`. Set `CURRATOR_MODE=live` and restart. Keep `.env` private.

The default `gemini-3.1-flash-lite` supports [audio input](https://aistudio.google.com/docs/models/gemini-3.1-flash-lite) and has [free text and audio usage within quota](https://aistudio.google.com/docs/pricing#gemini-3.1-flash-lite). Google Search grounding is disabled for the demo configuration. For current questions, Currator reports when it cannot verify live information. Wikipedia and Wikidata can provide sources for general questions. Free public providers may retain or process requests under their own terms. Use rehearsed questions and avoid personal information in public demos.

## Verify before rehearsal

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m currator.simulate
python -m currator.smoke
```

The smoke check makes real Pindo requests. It times speech generation, audio download, transcription, reply selection, and reply audio. Use `--audio your-question.wav --expect "witwa nde"` for a human recording, or `--language en --audio english-question.wav` for English. Add `--output intro.wav` to save a Kinyarwanda spoken clip for the backup rehearsal. Label the clip prerecorded during the demo.

Set `CURRATOR_MODE=mock` for the offline text backup. See [demo acceptance](docs/ACCEPTANCE.md), [the proposed hardware contract](docs/HARDWARE_CONTRACT.md), and [the delivery plan](docs/PLAN_15_DAYS.md).

## Hardware integration

The simulator exercises the same command rules with mock sensors and transport. Keep `ENABLE_MOTION=false` on the demo machine until the hardware team confirms the interface and passes the physical acceptance checks. The starter serial writer is a prototype. See the [hardware contract](docs/HARDWARE_CONTRACT.md) for the settings and handoff checklist.

## How the complete robot fits together

The operator opens the console in a browser on the laptop or Raspberry Pi running Currator.
A connected robot display can show that same console. The screen offers a language selector,
microphone, transcript, replies, and source links. The local Python server handles the provider
requests. A public website and web hosting are unnecessary for this setup.

For a voice turn, the microphone sends a recording to the local server. Pindo transcribes
Kinyarwanda. English uses the configured local Vosk model or Gemini. Gemini prepares the
open-ended reply and the app can retrieve Wikimedia evidence for general factual questions.
The console displays the answer and plays Pindo's Kinyarwanda audio or the browser's English
voice. The live providers need internet access.

On the proposed hardware setup, one USB data cable connects the computer to the ESP32.
The operator's movement controls use a separate channel from conversation. The ESP32 runs the
motor and sensor firmware. Currator's USB bench check verifies incoming sensor messages.
Continuous sensor integration, firmware acknowledgements, and physical motion verification
are required before the hardware demo.

Check source access on the presentation network without a Gemini key or a running server.

```bash
python -m currator.smoke --source-query "Kigali" --language en --expect Rwanda
```
