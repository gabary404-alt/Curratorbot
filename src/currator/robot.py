"""Robot control interface. Firmware owns safety, not LLMs."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

from .config import Settings
from .models import RobotCommand, SensorTelemetry


@dataclass
class Telemetry:
    value: SensorTelemetry | None = None
    received_at: float = 0


def safe_auto_step(t: SensorTelemetry) -> dict:
    """Conservative supervised reactive step; NOT full autonomous navigation."""
    if t.emergency_stop or t.bumper_pressed:
        return {"cmd": "stop"}
    if t.front_cm < 45:
        if t.left_cm < 40 and t.right_cm < 40:
            return {"cmd": "stop"}
        angular = 0.4 if t.left_cm > t.right_cm else -0.4
        return {"cmd": "turn", "angular": angular, "duration_ms": 350}
    if min(t.left_cm, t.right_cm) < 20:
        return {"cmd": "stop"}
    return {"cmd": "drive", "linear": 0.08, "duration_ms": 350}


class RobotBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.telemetry = Telemetry()
        self._lock = asyncio.Lock()
        self.log: list[dict] = []

    def update_telemetry(self, value: SensorTelemetry):
        self.telemetry = Telemetry(value=value, received_at=time.monotonic())

    async def send(self, command: RobotCommand):
        async with self._lock:
            payload = self._command_payload(command)
            if self.settings.robot_transport == "serial":
                await asyncio.to_thread(self._serial_write, payload)
            self.log.append(payload)
            self.log[:] = self.log[-50:]
        return payload

    def _command_payload(self, command: RobotCommand) -> dict:
        if command.action == "stop":
            return {"cmd": "stop"}
        if not self.settings.enable_motion:
            raise PermissionError("Movement disabled; set ENABLE_MOTION only after safety tests")
        sensors = self.telemetry.value
        if not sensors or time.monotonic() - self.telemetry.received_at > 1.5:
            raise PermissionError("Sensor telemetry missing or older than 1.5 seconds")
        if sensors.emergency_stop or sensors.bumper_pressed:
            raise PermissionError("Hardware emergency stop/bumper is active")
        if command.action == "auto_step":
            return safe_auto_step(sensors)
        if command.action == "drive":
            if min(sensors.front_cm, sensors.left_cm, sensors.right_cm) < 45:
                raise PermissionError("Obstacle too close for movement")
            return {
                "cmd": "drive", "linear": min(command.speed, 0.15),
                "duration_ms": command.duration_ms,
            }
        if min(sensors.front_cm, sensors.left_cm, sensors.right_cm) < 30:
            raise PermissionError("Obstacle too close for turning")
        return {"cmd": "turn", "angular": 0.35, "duration_ms": command.duration_ms}

    def _serial_write(self, payload: dict):
        # pyserial is optional and serial protocol requires the firmware team to implement it.
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install currator-bot[serial] for serial hardware") from exc
        with serial.Serial(self.settings.robot_serial_port,
                           self.settings.robot_serial_baud, timeout=1,
                           write_timeout=1) as port:
            port.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
            port.flush()
