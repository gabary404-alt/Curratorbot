"""Exercise the robot command bridge with simulated sensors and zero serial access."""
from __future__ import annotations

import asyncio
import json
import time

from .config import Settings
from .models import RobotCommand, SensorTelemetry
from .robot import RobotBridge

CLEAR = SensorTelemetry(front_cm=100, left_cm=90, right_cm=90)
SCENARIOS = [
    ("No telemetry", None, 0, "auto_step", "blocked"),
    ("Clear path", CLEAR, 0, "auto_step", "drive"),
    ("Obstacle ahead", CLEAR.model_copy(update={"front_cm": 20, "right_cm": 25}), 0,
     "auto_step", "turn"),
    ("Surrounded", SensorTelemetry(front_cm=20, left_cm=25, right_cm=25), 0, "auto_step", "stop"),
    ("Bumper pressed", CLEAR.model_copy(update={"bumper_pressed": True}), 0, "auto_step", "blocked"),
    ("Emergency stop", CLEAR.model_copy(update={"emergency_stop": True}), 0,
     "auto_step", "blocked"),
    ("Old telemetry", CLEAR, 2, "auto_step", "blocked"),
    ("Stop without telemetry", None, 0, "stop", "stop"),
]


async def run() -> bool:
    passed = True
    for label, sensors, age, action, expected in SCENARIOS:
        bridge = RobotBridge(Settings(
            enable_motion=True, robot_transport="mock", robot_serial_port="",
        ))
        if sensors is not None:
            bridge.update_telemetry(sensors)
            bridge.telemetry.received_at = time.monotonic() - age
        try:
            result = await bridge.send(RobotCommand(action=action))
            actual = result["cmd"]
        except PermissionError as error:
            actual = "blocked"
            result = {"reason": str(error)}
        ok = actual == expected
        passed &= ok
        print(f"{'PASS' if ok else 'FAIL'} {label}: {actual}, expected {expected}")
        print(f"  {json.dumps(result)}")
    return passed


if __name__ == "__main__":
    print("Motor command simulation")
    raise SystemExit(0 if asyncio.run(run()) else 1)
