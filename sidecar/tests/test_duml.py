from osmo_sidecar.crc import crc8, crc16
from osmo_sidecar.duml import (
    PWM_CENTER,
    DumlParser,
    build_packet,
    build_pwm,
    build_set_mode,
    build_speed_rotate,
    map_stick,
    packet_crc_ok,
    stick_to_pwm,
    stick_to_speed,
)


def test_crc8_known_rotate_header() -> None:
    assert crc8(bytes([0x55, 0x15, 0x04])) == 0xA9


def test_build_speed_rotate_matches_om_research_frame() -> None:
    packet = build_speed_rotate(1500, 0, 0, time=10, seq=1)
    assert packet[0] == 0x55
    assert packet[1] == 0x15
    assert packet[2] == 0x04
    assert packet[3] == 0xA9
    assert packet[4:11] == bytes([0x02, 0x04, 0x01, 0x00, 0x00, 0x04, 0x0C])
    payload = packet[11:-2]
    assert payload[:2] == (1500).to_bytes(2, "little", signed=True)
    assert payload[6] == 0x80
    assert payload[7] == 10
    body = packet[4:-2]
    assert crc16(body).to_bytes(2, "little") == packet[-2:]
    assert len(packet) == 21


def test_parser_roundtrip() -> None:
    raw = build_speed_rotate(-400, 250, 0, time=12, seq=7)
    packets = DumlParser().feed(raw)
    assert len(packets) == 1
    parsed = packets[0]
    assert parsed.cmd_set == 0x04
    assert parsed.cmd == 0x0C
    assert parsed.seq == 7
    yaw = int.from_bytes(parsed.payload[0:2], "little", signed=True)
    pitch = int.from_bytes(parsed.payload[4:6], "little", signed=True)
    assert yaw == -400
    assert pitch == 250


def test_parser_resyncs_after_garbage() -> None:
    raw = build_pwm(PWM_CENTER, PWM_CENTER)
    packets = DumlParser().feed(b"\x00\xff" + raw)
    assert len(packets) == 1
    assert packets[0].cmd == 0x01


def test_map_stick_forward_is_nose_down() -> None:
    yaw, pitch = map_stick(0.5, 1.0)
    assert yaw == 0.5
    assert pitch == -1.0
    assert map_stick(0.0, -1.0)[1] == 1.0
    assert map_stick(0.5, 1.0, invert_pitch=True)[1] == 1.0
    assert map_stick(0.5, 0.0, invert_yaw=True)[0] == -0.5


def test_stick_scaling_deadzone() -> None:
    assert stick_to_speed(0.01, 1200) == 0
    assert stick_to_speed(1, 1200) == 1200
    assert stick_to_speed(-1, 1200) == -1200
    assert stick_to_pwm(0) == PWM_CENTER
    assert stick_to_pwm(1) == 1685
    assert stick_to_pwm(-1) == 363


def test_set_mode_payload() -> None:
    packet = build_set_mode(1, seq=2)
    parsed = DumlParser().feed(packet)[0]
    assert parsed.cmd == 0x4C
    assert parsed.payload == bytes([0x01, 0x00])


def test_build_packet_length_field() -> None:
    packet = build_packet(0x04, 0x01, b"\x00" * 6, seq=1)
    length = int.from_bytes(packet[1:3], "little") & 0x3FF
    assert length == len(packet)


def test_packet_crc_ok() -> None:
    packet = build_set_mode(1, seq=2)
    assert packet_crc_ok(packet)
    broken = bytearray(packet)
    broken[-1] ^= 0xFF
    assert packet_crc_ok(bytes(broken)) is False
