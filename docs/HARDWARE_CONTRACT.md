# Hardware ↔ Software Contract · v0.1 (Proposed, NOT confirmed by firmware team)

**Needed from hardware team by Day 2:** board/OS, camera/mic/speaker/display models, wheelbase and caster or balancing plan, motor controller, motor-driver ratings, obstacle sensor types/placement, battery and regulator specs, proposed serial or ROS transport, and who owns obstacle avoidance.

## Recommended responsibilities

- Raspberry Pi 5 / Ubuntu 24.04 ARM64: touchscreen kiosk, audio, FastAPI, cloud APIs, logs.
- ESP32 with dedicated motor driver: motor PWM, odometry (if fitted), bumper/obstacle sensors, physical emergency-stop interlock, watchdog, power management.
- The Pi cannot be treated as a real-time safety controller. A reboot, network loss or API timeout **must not cause uncontrolled motion**.

## Proposed protocol: newline-delimited JSON over USB serial (115200 baud)

Pi → ESP32 examples (the robot module uses exactly this transport if enabled):

```json
{"cmd":"stop","id":"142edb2787d3c96f"}
{"cmd":"drive","linear":0.08,"duration_ms":350,"id":"806f692fad6592da"}
{"cmd":"turn","angular":0.4,"duration_ms":350,"id":"c24810cfdb3d5693"}
```

- `linear` is **meters per second**, magnitude capped in software at 0.15 m/s.
- `angular` is **radians per second**, positive = left by convention, magnitude capped at 0.4.
- `duration_ms` max 750 ms. Firmware MUST validate all three fields, clamp independently, and stop at command expiration.
- Firmware echoes the command ID and action, with an explicit boolean acceptance field. For example, `{"type":"ack","id":"142edb2787d3c96f","cmd":"stop","accepted":true}`.
- Acknowledgements report controller acceptance. The app waits up to 500 ms and requires an acknowledged stop after a write failure or missing confirmation. Firmware must reject malformed JSON and enforce its own watchdog and stop behavior.

ESP32 → Pi obstacle telemetry (proposed payload):

```json
{"front_cm":120.0,"left_cm":90.0,"right_cm":110.0,"bumper_pressed":false,"emergency_stop":false}
```

In serial mode, the app accepts telemetry from the USB controller. Send at least five sensor
frames per second. The app refuses movement if a valid frame is older than 1.5 seconds.
The HTTP telemetry endpoint is for mock transport. Onboard sensors and E-stop always win.
After a USB disconnect, the bridge requires a fresh stop acknowledgement before accepting movement again.

## Physical acceptance gates before enabling motion

1. Stable three-point contact (or verified balance), no tipping at commanded accelerations.
2. Hardware E-stop interrupts motor power without Pi/network assistance.
3. Low-voltage cutoff, fusing and battery management verified by hardware team.
4. Collision bumper / obstacle detection stop tested directly on ESP32.
5. Firmware watchdog stops motors if there is no command/heartbeat within 1 second.
6. Wheel free-spin and tethered motion tested in a safe area, then slow floor test with a supervisor.
7. Stop on stale sensor data, no movement during power-up, disconnect, reboot or Wi-Fi loss.
8. Firmware schema and units tested against software's protocol, with documented ACK.

Only then set `ENABLE_MOTION=true` **and** a random `ROBOT_OPERATOR_TOKEN` (>=24 characters) and configure `ROBOT_TRANSPORT=serial`. The current code is not a certified safety system.

## ROS 2 decision

ROS 2 Jazzy on Ubuntu 24.04 ARM64 is appropriate if the hardware team already has a ROS 2 sensor/drive stack. **Do not add ROS 2 solely for the demo**; direct USB serial is simpler and leaves more time for test and rehearsal.

## First USB bench check

With the motor drive disconnected and the controller firmware publishing telemetry, install the
serial extra with `python -m pip install -e '.[serial]'`. Connect the USB data cable, find the
port with `python -m serial.tools.list_ports`, then run `python -m currator.usb_check COM3`.
Replace `COM3` with the port shown on your machine. Close other serial monitors first.

The check listens for three valid sensor frames. It sends no motion commands. Its result confirms
the computer can read sensor messages. Emergency-stop behavior and command acknowledgements
require separate firmware and bench verification.
