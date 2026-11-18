# 15-day implementation plan · 17 Nov – 1 Dec 2026

Time budget: 3 developers × 3–4 hours/day × 14 days = **126–168 developer-hours**, not elapsed hours. Hardware expected ~Day 10. Only Days 11–14 remain for physical integration.

| Day | Dev A · Voice | Dev B · Backend/Integration | Dev C · Knowledge/Robotics | Gate |
|---|---|---|---|---|
| 1 | Document Pindo contract, audio sample spec | API skeleton, mock mode, tests | Firmware contract, safety gate | Mock chat/test suite |
| 2 | Pindo live STT/Kinyarwanda TTS smoke | Gemini live chat + retry limits | Wikimedia retrieval | Two live API smoke tests |
| 3 | English ASR + TTS pilot | Conversational behavior, latency | Sensor mock simulator | Bilingual text demo |
| 4 | Microphone push-to-talk reliability | End-to-end voice pipeline | Lookup quality cases | Bilingual audio demo |
| 5 | Noise and accent recording set | Source accuracy, no hallucinated facts | Grounding/web lookup routing | 10 Kinyarwanda questions |
| 6 | Audio echo, stop/retry | History & error handling | Hardware protocol simulator | Repeatable demo |
| 7 | Voice speed tuning | CI + smoke dashboard | Failsafe command validation | Software milestone freeze |
| 8 | Continue quality work | Integration documentation | Simulated robot telemetry | Software demo w/o robot |
| 9 | Final audio tests | Integration scripts | Firmware handshake with team | Protocol confirmed |
| 10 | Record fallback clips | Release candidate | Hardware arrival inspection | Hardware handover |
| 11 | Real microphone and speaker | Kiosk deployment | ESP32/serial read-write | Physical talking robot |
| 12 | Environmental noise | Stability/performance | Safe manual movement first | Physical controlled motion |
| 13 | Voice rehearsal | Answer/source verification | Supervised avoidance tests | Demo rehearsal |
| 14 | Freeze audio settings | Freeze release, documentation | Freeze hardware settings | No new features |
| 15 | Test & log | Final acceptance | Full safety/dress rehearsal | Go/no-go decision |

**Critical path:** Pindo Kinyarwanda STT/TTS usable → Gemini key free tier working → microphone/speaker hardware recognized → serial protocol confirmed → safe motion verified → full dress rehearsal.

**Scope cut rules:** If Day 4 audio fails, first demo uses text + prerecorded clearly labeled samples while speech is fixed. If Day 10 robot hardware isn't ready, present working software on a laptop. If motor fails safety gates, motors stay disabled in public and robot presents stationary; never sacrifice safety to meet schedule. No full SLAM or personal voice cloning in V1.
