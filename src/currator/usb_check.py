"""Check controller telemetry over USB before enabling movement."""
from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator


from .models import SensorTelemetry

MAX_FRAME_BYTES = 512


class Frames:
    """Decode bounded newline-delimited records across serial read boundaries."""

    def __init__(self):
        self.pending = bytearray()
        self.discarding = False

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        for byte in chunk:
            if byte == 10:
                if self.pending and not self.discarding:
                    yield bytes(self.pending)
                self.pending.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.pending) == MAX_FRAME_BYTES:
                    self.pending.clear()
                    self.discarding = True
                else:
                    self.pending.append(byte)


def decode_frame(frame: bytes) -> SensorTelemetry | None:
    try:
        payload = json.loads(frame)
        if not isinstance(payload, dict):
            return None
        # Require explicit flags on the wire even though the HTTP model has defaults.
        if not all(type(payload.get(name)) is bool for name in ("bumper_pressed", "emergency_stop")):
            return None
        return SensorTelemetry.model_validate(payload, strict=True)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Serial port such as COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    try:
        import serial
    except ImportError:
        parser.exit(2, "Install currator-bot[serial] to check the USB connection.\n")

    frames = Frames()
    count = 0
    try:
        with serial.Serial(args.port, args.baud, timeout=0.2) as port:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and count < 3:
                for frame in frames.feed(port.read(256)):
                    telemetry = decode_frame(frame)
                    if telemetry is not None:
                        print(telemetry.model_dump_json(), flush=True)
                        count += 1
                        if count == 3:
                            break
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Could not read controller port: {exc}\n")
    if count < 3:
        parser.exit(1, f"Received {count}/3 valid telemetry frames. Check the port and firmware.\n")
    print("PASS: received three valid telemetry frames over USB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
