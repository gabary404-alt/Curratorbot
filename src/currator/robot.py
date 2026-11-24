"""Robot control interface. Firmware owns safety, not LLMs."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass

from .config import Settings
from .models import RobotCommand, SensorTelemetry
from .usb_check import Frames, decode_frame


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
        self.port = None
        self.pending: dict[str, tuple[str, asyncio.Future]] = {}
        self.motion_uncertain = False

    async def receive_serial(self):
        """Maintain one connection and trust only frames received from the controller."""
        try:
            import serial
        except ImportError:
            return
        while True:
            try:
                self.port = serial.Serial(
                    self.settings.robot_serial_port, self.settings.robot_serial_baud,
                    timeout=0.05, write_timeout=0.25,
                )
                frames = Frames()
                while True:
                    chunk = await asyncio.to_thread(self.port.read, 256)
                    for frame in frames.feed(chunk):
                        self._receive_frame(frame)
            except (OSError, ValueError):
                pass
            finally:
                self.telemetry = Telemetry()
                if self.port is not None:
                    self.motion_uncertain = True
                    try:
                        self.port.close()
                    except OSError:
                        pass
                    self.port = None
                for _, waiter in self.pending.values():
                    if not waiter.done():
                        waiter.set_result(None)
            await asyncio.sleep(1)

    def _receive_frame(self, frame: bytes):
        try:
            payload = json.loads(frame)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("type") == "ack":
            command_id = payload.get("id")
            accepted = payload.get("accepted")
            if isinstance(command_id, str) and type(accepted) is bool:
                action, waiter = self.pending.get(command_id, (None, None))
                if waiter is not None and not waiter.done() and payload.get("cmd") == action:
                    waiter.set_result(accepted)
            return
        telemetry = decode_frame(frame)
        if telemetry is not None:
            self.update_telemetry(telemetry)

    def update_telemetry(self, value: SensorTelemetry):
        self.telemetry = Telemetry(value=value, received_at=time.monotonic())

    async def send(self, command: RobotCommand):
        if self.settings.robot_transport == "serial":
            return await self._send_serial(command)
        async with self._lock:
            payload = self._command_payload(command)
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

    async def _send_serial(self, command: RobotCommand):
        command_id = secrets.token_hex(8)
        waiter = asyncio.get_running_loop().create_future()
        action = None
        try:
            async with self._lock:
                payload = self._command_payload(command)
                action = payload["cmd"]
                if self.port is None:
                    raise RuntimeError("USB controller disconnected")
                if action != "stop" and (self.pending or self.motion_uncertain):
                    raise PermissionError("Wait for command confirmation or send Stop to reset")
                if len(self.pending) >= 2:
                    raise PermissionError("Stop confirmation already pending")
                self.pending[command_id] = action, waiter
                wire = (json.dumps({**payload, "id": command_id}) + "\n").encode()
                if await asyncio.to_thread(self.port.write, wire) != len(wire):
                    raise OSError("Incomplete serial write")
            accepted = await asyncio.wait_for(waiter, timeout=0.5)
            if accepted is None:
                raise RuntimeError("USB controller disconnected before acknowledgement")
            if not accepted:
                raise PermissionError("Controller rejected command")
            if action == "stop":
                self.motion_uncertain = False
            return payload
        except (RuntimeError, OSError, asyncio.CancelledError):
            if action and command_id in self.pending:
                self.motion_uncertain = True
            raise
        finally:
            self.pending.pop(command_id, None)
