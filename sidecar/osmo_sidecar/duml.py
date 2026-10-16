"""DUML packet codec used by Osmo Mobile over BLE."""

from __future__ import annotations

from dataclasses import dataclass

from osmo_sidecar.crc import crc16, crc8

MAGIC = 0x55
VERSION = 1
SENDER_APP = 0x02
RECEIVER_GIMBAL = 0x04
CMDSET_GIMBAL = 0x04
CMDSET_GENERAL = 0x00
CMDSET_CAMERA = 0x01

CMD_GIMBAL_PWM = 0x01
CMD_GIMBAL_GET_POS = 0x02
CMD_GIMBAL_PUSH_POS = 0x05
CMD_GIMBAL_ANGLE = 0x0A
CMD_GIMBAL_SPEED = 0x0C
CMD_GIMBAL_ABS_ANGLE = 0x14
CMD_GIMBAL_MOVE = 0x15
CMD_GIMBAL_SET_MODE = 0x4C
CMD_BATTERY = 0x06

CMDSET_BATTERY = 0x05

PWM_CENTER = 1024
PWM_MIN = 363
PWM_MAX = 1685

TELEMETRY_CMDS = frozenset(
    {
        (CMDSET_GIMBAL, CMD_GIMBAL_PUSH_POS),
        (CMDSET_GIMBAL, 0x27),  # keepalive seen on Pocket/Osmo traces
        (CMDSET_BATTERY, CMD_BATTERY),
    }
)


@dataclass(frozen=True)
class DumlPacket:
    length: int
    sender: int
    receiver: int
    seq: int
    attributes: int
    cmd_set: int
    cmd: int
    payload: bytes
    raw: bytes

    @property
    def is_telemetry(self) -> bool:
        return (self.cmd_set, self.cmd) in TELEMETRY_CMDS

    @property
    def crc_ok(self) -> bool:
        return packet_crc_ok(self.raw)

    def summary(self) -> str:
        return (
            f"len={self.length} {self.sender:#04x}->{self.receiver:#04x} "
            f"seq={self.seq} set=0x{self.cmd_set:02x} cmd=0x{self.cmd:02x} "
            f"payload={self.payload.hex(' ') or '-'}"
        )

    def as_row(self) -> dict[str, object]:
        return {
            "cmd_set": self.cmd_set,
            "cmd": self.cmd,
            "sender": self.sender,
            "receiver": self.receiver,
            "seq": self.seq,
            "payload": self.payload.hex(),
            "raw": self.raw.hex(),
            "telemetry": self.is_telemetry,
            "crc_ok": self.crc_ok,
            "summary": self.summary(),
            "label": f"0x{self.cmd_set:02x}/0x{self.cmd:02x}",
        }


def packet_crc_ok(raw: bytes) -> bool:
    if len(raw) < 13:
        return False
    if crc8(raw[:3]) != raw[3]:
        return False
    body = raw[4:-2]
    return crc16(body).to_bytes(2, "little") == raw[-2:]


class DumlParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[DumlPacket]:
        self._buffer.extend(data)
        packets: list[DumlPacket] = []
        while True:
            packet = self._pop_packet()
            if packet is None:
                break
            packets.append(packet)
        return packets

    def _pop_packet(self) -> DumlPacket | None:
        buf = self._buffer
        if not buf:
            return None
        if buf[0] != MAGIC:
            idx = bytes(buf).find(bytes([MAGIC]))
            if idx == -1:
                self._buffer.clear()
                return None
            del buf[:idx]
        if len(buf) < 4:
            return None
        length_raw = int.from_bytes(buf[1:3], "little")
        length = length_raw & 0x3FF
        if length < 13:
            del buf[0]
            return None
        if len(buf) < length:
            return None
        raw = bytes(buf[:length])
        del buf[:length]
        return DumlPacket(
            length=length,
            sender=raw[4],
            receiver=raw[5],
            seq=int.from_bytes(raw[6:8], "little"),
            attributes=raw[8],
            cmd_set=raw[9],
            cmd=raw[10],
            payload=raw[11 : length - 2],
            raw=raw,
        )


def build_packet(
    cmd_set: int,
    cmd: int,
    payload: bytes = b"",
    *,
    seq: int = 1,
    sender: int = SENDER_APP,
    receiver: int = RECEIVER_GIMBAL,
    attributes: int = 0x00,
) -> bytes:
    body = bytes(
        [
            sender,
            receiver,
            seq & 0xFF,
            (seq >> 8) & 0xFF,
            attributes,
            cmd_set,
            cmd,
        ]
    ) + payload
    length = 4 + len(body) + 2
    length_raw = (length & 0x3FF) | (VERSION << 10)
    header = bytes([MAGIC, length_raw & 0xFF, (length_raw >> 8) & 0xFF])
    return header + bytes([crc8(header)]) + body + crc16(body).to_bytes(2, "little")


def build_speed_rotate(
    yaw: int,
    pitch: int,
    roll: int = 0,
    *,
    time: int = 10,
    seq: int = 1,
) -> bytes:
    """OM2–OM4 SPEED rotate (cmd 0x0C, mode 0x80). Values are tenths of a degree/s-ish."""
    payload = (
        yaw.to_bytes(2, "little", signed=True)
        + roll.to_bytes(2, "little", signed=True)
        + pitch.to_bytes(2, "little", signed=True)
        + bytes([0x80, time & 0xFF])
    )
    return build_packet(CMDSET_GIMBAL, CMD_GIMBAL_SPEED, payload, seq=seq)


def build_absolute_rotate(
    yaw: int,
    pitch: int,
    roll: int = 0,
    *,
    time: int = 20,
    seq: int = 1,
) -> bytes:
    payload = (
        yaw.to_bytes(2, "little", signed=True)
        + roll.to_bytes(2, "little", signed=True)
        + pitch.to_bytes(2, "little", signed=True)
        + bytes([0x05, time & 0xFF])
    )
    return build_packet(CMDSET_GIMBAL, CMD_GIMBAL_ABS_ANGLE, payload, seq=seq)


def clamp_pwm(value: int) -> int:
    return max(PWM_MIN, min(PWM_MAX, value))


def build_pwm(yaw: int, pitch: int, roll: int = PWM_CENTER, *, seq: int = 1) -> bytes:
    payload = (
        clamp_pwm(yaw).to_bytes(2, "little")
        + clamp_pwm(roll).to_bytes(2, "little")
        + clamp_pwm(pitch).to_bytes(2, "little")
    )
    return build_packet(CMDSET_GIMBAL, CMD_GIMBAL_PWM, payload, seq=seq)


def build_set_mode(mode: int, *, seq: int = 1) -> bytes:
    """0=lock, 1=follow, 2=FPV."""
    return build_packet(CMDSET_GIMBAL, CMD_GIMBAL_SET_MODE, bytes([mode & 0xFF, 0x00]), seq=seq)


def map_stick(
    yaw: float,
    pitch: float,
    *,
    invert_yaw: bool = False,
    invert_pitch: bool = False,
) -> tuple[float, float]:
    """Clamp stick axes. Positive Y (up/forward) is a nose-down pitch unless invert_pitch."""
    mapped_yaw = max(-1.0, min(1.0, yaw))
    mapped_pitch = max(-1.0, min(1.0, -pitch))
    if invert_yaw:
        mapped_yaw = -mapped_yaw
    if invert_pitch:
        mapped_pitch = -mapped_pitch
    return (mapped_yaw, mapped_pitch)


def stick_to_speed(axis: float, max_speed: int) -> int:
    clamped = max(-1.0, min(1.0, axis))
    if abs(clamped) < 0.04:
        return 0
    return int(round(clamped * max_speed))


def stick_to_pwm(axis: float) -> int:
    clamped = max(-1.0, min(1.0, axis))
    if abs(clamped) < 0.04:
        return PWM_CENTER
    span = PWM_MAX - PWM_CENTER if clamped > 0 else PWM_CENTER - PWM_MIN
    return clamp_pwm(PWM_CENTER + int(round(clamped * span)))
