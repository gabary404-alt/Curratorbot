# Build session — 18 November 2026

## Completed

- Imported the previous Python/FastAPI starter into the new Curratorbot repository.
- Added a voice rehearsal mode with prepared, labeled Kinyarwanda and English replies.
- Verified the Pindo public TTS payload. Including `lang` caused a provider HTTP 500 during testing. The public request now follows the official example, with `text` and `speech_rate`.
- Allowed the exact Pindo-generated audio host observed during a successful public request.
- Added one bounded retry after an explicit Pindo TTS 500/502/503/504 response. Rate limits are surfaced immediately.
- Added optional offline English transcription using Vosk and FFmpeg. The extracted model is installed separately.
- Fixed microphone lifecycle, recording language capture, the 15-second recording cap, and pending speech cancellation.
- Packaged HTML/CSS/JS inside the Python wheel so the installed application serves its console.
- Added a reusable timed voice smoke command and eight robot simulation scenarios.
- Rechecked sensor state after acquiring the robot command lock. This prevents a queued command from using the sensor state that existed before waiting.
- Updated Gemini's default to `gemini-3.1-flash-lite`. Disabled Google Search grounding by default after checking the current free-tier pricing.
- Added CI steps for Python tests, console state tests, and robot simulation.

## Verified locally

| Check | Result |
| --- | --- |
| Python tests | 39 passed |
| Console state tests | 5 passed using a Node DOM/media test harness |
| Robot command simulator | 8 scenarios passed with mock transport |
| Kinyarwanda TTS → STT | Pindo-generated “Muraho neza!” transcribed as “Muraho neza.” |
| App Kinyarwanda audio → reply → TTS | Passed with a generated input clip. Final output was a 3.22-second PCM WAV |
| App English audio → reply | Passed using a synthetic “What is your name?” recording and the local Vosk model |
| Python wheel | Built with all three console assets included |

The Kinyarwanda app check took approximately 11.94 seconds for transcription, 4.56 seconds for reply speech generation, and 10.56 seconds for media retrieval. These timings include the remote build environment's network. Event-network timing must be measured separately. Pindo also returned intermittent HTTP 500 errors during this session.

## Pending verification

- Human Kinyarwanda recordings with varied accents and room noise.
- Real microphone and speaker operation on the presentation computer.
- Browser visual checks. Chromium launch was blocked by the build environment. Console state and cancellation behavior were checked using the automated harness.
- Gemini live responses and English Gemini transcription. No Gemini key was available.
- Wikimedia source quality and current-question behavior on the presentation network.
- Physical wheels, firmware acknowledgements, sensor streaming, and emergency-stop behavior.

## Inputs needed for the next integration session

1. Put a free-tier Gemini API key in the presentation computer's local `.env`, then run live mode and the voice checks. Keep the key out of GitHub and chat.
2. Hardware team supplies the actual computer/OS, motor controller, serial interface, sensor types and placement, and firmware owner. The proposed hardware contract remains a proposal.
3. Run the three-speaker Kinyarwanda test in `ACCEPTANCE.md` and report the transcripts, errors, and timings.

## Context reviewed

Reviewed the starter archive, current README, hardware contract, delivery plan, archived voice/robot conversation text, and recovered context from the Currator Bot thread. Direct access to the complete original Currator Bot chat was blocked by the browser host policy. This session's decisions rely on the accessible records above.
