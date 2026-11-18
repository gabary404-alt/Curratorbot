import pytest
from fastapi.testclient import TestClient

from currator import main
from currator.config import Settings
from currator.knowledge import needs_current_info, needs_wikipedia
from currator.models import RobotCommand, SensorTelemetry
from currator.robot import RobotBridge, safe_auto_step
from currator.speech import _read_data, safe_audio_url


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def test_health_check(client):
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json()['languages'] == ['rw', 'en']
    assert response.json()['mode'] == 'mock'


def test_web_app(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'Currator Bot' in response.text


def test_kinyarwanda_demo(client):
    result = client.post('/api/chat', json={'text': 'Muraho', 'language': 'rw'})
    assert result.status_code == 200
    assert 'Muraho' in result.json()['reply']
    assert result.json()['simulated'] is True


def test_english_demo(client):
    result = client.post('/api/chat', json={'text': 'Hello', 'language': 'en'})
    assert result.status_code == 200
    assert 'Hello' in result.json()['reply']


def test_chat_rejects_bad_language(client):
    r = client.post('/api/chat', json={'text': 'Bonjour', 'language': 'fr'})
    assert r.status_code == 422


def test_no_mock_transcription_faked(client):
    r = client.post('/api/speech/transcribe?language=rw', files={'audio': ('a.wav', b'not audio', 'audio/wav')})
    assert r.status_code == 503


def test_no_motion_without_operator_secret(client):
    r = client.post('/api/robot/command', json={'action': 'drive'})
    assert r.status_code == 401


def test_live_voice_not_faked_in_mock(client):
    r = client.post('/api/speech/synthesize', json={'text': 'Muraho', 'language': 'rw'})
    assert r.json()['simulated'] is True
    assert r.json()['audio_url'] is None


def test_source_triggers():
    assert needs_current_info('Ni nde Perezida w’u Rwanda ubu?')
    assert needs_current_info('Weather in Kigali today')
    assert needs_wikipedia('Tell me about volcanoes')
    assert not needs_current_info('Hello!')


def test_pindo_json_extract():
    assert _read_data({'status':'success', 'data': {'text':'Muraho'}})['text'] == 'Muraho'


def test_media_urls_allowlist():
    assert safe_audio_url('path/a.wav', '') is None
    assert safe_audio_url('path/a.wav','https://api.pindo.io/') == 'https://api.pindo.io/path/a.wav'
    assert safe_audio_url('http://127.0.0.1/evil.wav','https://api.pindo.io') is None
    assert safe_audio_url('https://example.com/a.wav','') is None


def test_auto_step_reactive_safety():
    assert safe_auto_step(SensorTelemetry(front_cm=80,left_cm=70,right_cm=70))['cmd'] == 'drive'
    assert safe_auto_step(SensorTelemetry(front_cm=20,left_cm=100,right_cm=45))['cmd'] == 'turn'
    assert safe_auto_step(SensorTelemetry(front_cm=100,left_cm=100,right_cm=100,emergency_stop=True))['cmd'] == 'stop'
    assert safe_auto_step(SensorTelemetry(front_cm=15,left_cm=10,right_cm=10))['cmd'] == 'stop'


@pytest.mark.asyncio
async def test_motion_off_even_with_fresh_telemetry():
    bridge = RobotBridge(Settings(enable_motion=False))
    bridge.update_telemetry(SensorTelemetry(front_cm=100,left_cm=100,right_cm=100))
    with pytest.raises(PermissionError):
        await bridge.send(RobotCommand(action='drive'))


@pytest.mark.asyncio
async def test_stop_safe_when_motion_disabled():
    bridge = RobotBridge(Settings(enable_motion=False))
    assert (await bridge.send(RobotCommand(action='stop')))['cmd'] == 'stop'


@pytest.mark.asyncio
async def test_motion_needs_recent_sensors():
    bridge = RobotBridge(Settings(enable_motion=True, robot_operator_token='x'*32))
    with pytest.raises(PermissionError, match='telemetry'):
        await bridge.send(RobotCommand(action='drive'))


@pytest.mark.asyncio
async def test_motion_mock_with_clear_sensors():
    bridge = RobotBridge(Settings(enable_motion=True, robot_operator_token='x'*32))
    bridge.update_telemetry(SensorTelemetry(front_cm=100,left_cm=100,right_cm=100))
    cmd = await bridge.send(RobotCommand(action='auto_step'))
    assert cmd['cmd'] == 'drive' and cmd['duration_ms'] <= 750


@pytest.mark.asyncio
async def test_queued_command_rechecks_sensor_state():
    import asyncio

    bridge = RobotBridge(Settings(enable_motion=True))
    bridge.update_telemetry(SensorTelemetry(front_cm=100, left_cm=100, right_cm=100))
    await bridge._lock.acquire()
    command = asyncio.create_task(bridge.send(RobotCommand(action="drive")))
    await asyncio.sleep(0)
    bridge.update_telemetry(SensorTelemetry(
        front_cm=100, left_cm=100, right_cm=100, emergency_stop=True,
    ))
    bridge._lock.release()
    with pytest.raises(PermissionError, match="emergency"):
        await command
    assert bridge.log == []
