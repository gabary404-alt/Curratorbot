import pytest

from currator.usb_check import MAX_FRAME_BYTES, Frames, decode_frame

VALID = (
    b'{"front_cm":80,"left_cm":90,"right_cm":100,'
    b'"bumper_pressed":false,"emergency_stop":true}'
)


def test_serial_frames_reassemble_and_recover_after_overflow():
    frames = Frames()
    assert list(frames.feed(VALID[:20])) == []
    assert list(frames.feed(VALID[20:] + b"\r\n")) == [VALID + b"\r"]
    overlong = b"x" * MAX_FRAME_BYTES + VALID
    assert list(frames.feed(overlong + b"\n" + VALID + b"\n")) == [VALID]


@pytest.mark.parametrize("frame", [
    b"boot message", b"[]", b'{"cmd":"stop","status":"ok"}',
    VALID.replace(b',"emergency_stop":true', b''),
    VALID.replace(b'80', b'NaN'),
    VALID.replace(b'false', b'"false"'),
])
def test_rejects_invalid_telemetry(frame):
    assert decode_frame(frame) is None


def test_decodes_explicit_hardware_stop():
    telemetry = decode_frame(VALID)
    assert telemetry is not None
    assert telemetry.emergency_stop is True
    assert telemetry.front_cm == 80
