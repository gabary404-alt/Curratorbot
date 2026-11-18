# Acceptance criteria and test script

## First laptop rehearsal

1. Start rehearsal mode. Use the console at localhost and confirm the speaker works.
2. Ask **“Muraho! Witwa nde?”** in Kinyarwanda. Check the transcript, prepared reply, and Pindo audio. Repeat with **“Ukora iki?”** and **“Urakoze.”**
3. Switch to English. Ask **“What’s your name?”** using the microphone if Vosk is configured. Check that the reply plays through the browser’s English voice.
4. Interrupt a spoken reply with **Stop speech**, record a second question, and switch languages. If autoplay is blocked, use **Play reply**.
5. Run `python -m currator.smoke` on the event network and write down provider failures and timing. The generated clip checks connectivity. The three-speaker test below checks recognition quality.
6. Run `python -m currator.simulate` before wiring the hardware. It covers clear and blocked paths, bumper and E-stop states, old and missing telemetry, and the stop command.

## Software evidence

- [ ] Three native Kinyarwanda speakers each test 10 questions with varied speaking speeds in a normal room. Record actual word errors and intent accuracy; target ≥80% intent recognition, not guaranteed.
- [ ] 10 English questions through recorded audio and spoken answers, not just text.
- [ ] 10 verified Wikipedia/Wikidata questions with citations. Flag ambiguous facts.
- [ ] 10 current-info questions with explicit unavailable messages on the default free tier, or verified sources if a supported free grounding configuration is available.
- [ ] Latency measured start of user recording to start of spoken reply; aim median <10 seconds on event Wi-Fi. Measure rather than promise.
- [ ] Clearly admits when a question cannot be verified or when speech is misunderstood.
- [ ] No audio echoed back into the microphone as an unintended question; allow stop/interrupt.
- [ ] Test rate-limits, network disconnect, upstream 5xx, invalid audio and reconnection.
- [ ] No recording persistence by default; confirm privacy notice for public demonstration.

## Hardware evidence

- [ ] E-stop cuts motor power during active motion.
- [ ] Sensor/bumper directly stops motors even if Pi process hangs.
- [ ] Movement disabled by default and operator credentials required.
- [ ] After E-stop, reboot or broken serial cable, motors do not restart automatically.
- [ ] No movement beyond safe speed/duration and no tipped-over robot.
- [ ] Firmware watchdog works under severed USB/Pi failure.
- [ ] Obstacle avoidance floor-tested under supervision.

## Demo go/no-go

1. 10-minute warmup: power, voice, screen, sensors, network.
2. 15-minute mixed-language live Q&A and source verification.
3. 5-minute controlled movement only if safety tests passed.
4. Capture crash/errors, usability feedback and actual response delays.
5. Keep backup offline mock demo and a clearly labeled recorded clip; do not represent either as a live answer.
