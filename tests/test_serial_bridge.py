import asyncio
import json

import pytest

from currator.config import Settings
from currator.models import RobotCommand, SensorTelemetry
from currator.robot import RobotBridge


class FakeController:
    def __init__(self, bridge):
        self.bridge = bridge
        self.loop = asyncio.get_running_loop()
        self.writes = []
        self.acknowledge = True

    def write(self, wire):
        command = json.loads(wire)
        self.writes.append(command)
        if self.acknowledge:
            acknowledgement = {
                "type": "ack", "id": command["id"], "cmd": command["cmd"], "accepted": True,
            }
            self.loop.call_soon_threadsafe(
                self.bridge._receive_frame, json.dumps(acknowledgement).encode(),
            )
        return len(wire)


@pytest.mark.asyncio
async def test_serial_motion_requires_fresh_telemetry_and_matching_acknowledgement():
    bridge = RobotBridge(Settings(enable_motion=True, robot_transport="serial"))
    controller = FakeController(bridge)
    bridge.port = controller
    drive = RobotCommand(action="drive")
    with pytest.raises(PermissionError, match="telemetry"):
        await bridge.send(drive)
    assert not controller.writes

    telemetry = SensorTelemetry(front_cm=120, left_cm=100, right_cm=100)
    bridge._receive_frame(telemetry.model_dump_json().encode())
    assert (await bridge.send(drive))["cmd"] == "drive"

    controller.acknowledge = False
    with pytest.raises(TimeoutError):
        await bridge.send(drive)
    with pytest.raises(PermissionError, match="confirmation"):
        await bridge.send(drive)

    controller.acknowledge = True
    assert (await bridge.send(RobotCommand(action="stop")))["cmd"] == "stop"
    assert not bridge.motion_uncertain


@pytest.mark.asyncio
async def test_usb_loss_requires_acknowledged_stop_on_reconnect(monkeypatch):
    import sys
    from types import SimpleNamespace

    disconnected = asyncio.Event()
    class LostPort:
        def read(self, size):
            raise OSError("USB unplugged")
        def close(self):
            disconnected.set()

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=lambda *a, **kw: LostPort()))
    bridge = RobotBridge(Settings(enable_motion=True, robot_transport="serial"))
    receiver = asyncio.create_task(bridge.receive_serial())
    try:
        await asyncio.wait_for(disconnected.wait(), 1)
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
    assert bridge.port is None and bridge.motion_uncertain
    bridge.port = FakeController(bridge)
    bridge.update_telemetry(SensorTelemetry(front_cm=100, left_cm=100, right_cm=100))
    with pytest.raises(PermissionError, match="confirmation"):
        await bridge.send(RobotCommand(action="drive"))
    await bridge.send(RobotCommand(action="stop"))
    assert (await bridge.send(RobotCommand(action="drive")))["cmd"] == "drive"
