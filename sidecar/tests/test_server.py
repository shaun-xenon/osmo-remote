import asyncio
import io

from bleak.exc import BleakError

from osmo_sidecar.gimbal import InspectResult
from osmo_sidecar.server import SidecarServer


class FakeGimbal:
    def __init__(self) -> None:
        self.connected = False
        self.state = type(
            "State",
            (),
            {
                "address": None,
                "name": None,
                "battery": None,
                "charging": None,
                "wheel_supported": False,
                "wheel_reason": "not mapped",
                "last_error": None,
            },
        )()
        self.calls: list[tuple] = []

    async def scan(self, timeout: float = 8.0):
        self.calls.append(("scan", timeout))
        return []

    async def joystick(
        self,
        yaw: float,
        pitch: float,
        *,
        max_speed: int = 1200,
        method: str = "speed",
        invert_yaw: bool = False,
        invert_pitch: bool = False,
    ):
        self.calls.append(("joystick", yaw, pitch, max_speed, method, invert_yaw, invert_pitch))

    async def stop(self):
        self.calls.append(("stop",))

    async def recenter(self):
        self.calls.append(("recenter",))

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def wheel(self, delta: float):
        raise RuntimeError(self.state.wheel_reason)

    async def send_raw(self, payload_hex: str):
        self.calls.append(("send_raw", payload_hex))
        return {"bytes": 4, "rewrote_seq": False, "hex": payload_hex}

    async def apply_setting(self, name: str):
        self.calls.append(("apply_setting", name))
        return {"id": name, "kind": "recenter"}

    async def apply_profile(self, names=None):
        self.calls.append(("apply_profile", names))
        return {"applied": names or ["mode_follow"], "skipped": []}

    def list_settings(self):
        return [{"id": "recenter", "ready": True, "layer": "ble"}]


def test_unknown_command() -> None:
    server = SidecarServer(gimbal=FakeGimbal())  # type: ignore[arg-type]
    response = asyncio.run(server.handle_request({"cmd": "nope"}))
    assert response["ok"] is False
    assert "unknown" in response["error"]


def test_joystick_and_stop() -> None:
    fake = FakeGimbal()
    server = SidecarServer(gimbal=fake)  # type: ignore[arg-type]
    moved = asyncio.run(server.handle_request({"cmd": "joystick", "yaw": 0.5, "pitch": -0.2}))
    assert moved["ok"] is True
    stopped = asyncio.run(server.handle_request({"cmd": "stop"}))
    assert stopped["ok"] is True
    assert fake.calls[0][0] == "joystick"
    assert fake.calls[1] == ("stop",)


def test_wheel_refused_until_mapped() -> None:
    server = SidecarServer(gimbal=FakeGimbal())  # type: ignore[arg-type]
    response = asyncio.run(server.handle_request({"cmd": "wheel", "delta": 1}))
    assert response["ok"] is False
    assert "not mapped" in response["error"]


def test_shutdown_disconnects() -> None:
    fake = FakeGimbal()
    server = SidecarServer(gimbal=fake)  # type: ignore[arg-type]
    response = asyncio.run(server.handle_request({"cmd": "shutdown"}))
    assert response["ok"] is True
    assert fake.calls[-1] == ("disconnect",)
    assert server._running is False


def test_ping() -> None:
    server = SidecarServer(gimbal=FakeGimbal())  # type: ignore[arg-type]
    response = asyncio.run(server.handle_request({"cmd": "ping"}))
    assert response == {"ok": True, "result": {"pong": True}}


def test_send_raw_and_apply() -> None:
    fake = FakeGimbal()
    server = SidecarServer(gimbal=fake)  # type: ignore[arg-type]
    sent = asyncio.run(server.handle_request({"cmd": "send_raw", "hex": "5501"}))
    assert sent["ok"] is True
    assert fake.calls[-1] == ("send_raw", "5501")
    applied = asyncio.run(server.handle_request({"cmd": "apply_setting", "id": "recenter"}))
    assert applied["ok"] is True
    listed = asyncio.run(server.handle_request({"cmd": "settings"}))
    assert listed["ok"] is True
    assert "shooting" in listed["result"]


def test_connect_survives_apply_profile_bleak_error() -> None:
    class ProfileFailGimbal(FakeGimbal):
        async def connect(self, address, timeout=20.0, name=None):
            self.connected = True
            self.state.address = address
            self.state.name = name or address
            self.calls.append(("connect", address))
            return InspectResult(
                address=address,
                name=name or address,
                services=[],
                has_fff0=True,
                has_fff4=True,
                has_fff5=True,
                mtu=23,
            )

        async def apply_profile(self, names=None):
            self.calls.append(("apply_profile", names))
            raise BleakError("fff5 write failed")

    fake = ProfileFailGimbal()
    server = SidecarServer(gimbal=fake)  # type: ignore[arg-type]
    server._stdout = io.StringIO()
    response = asyncio.run(server.handle_request({"cmd": "connect", "address": "AA:BB:CC:DD:EE:FF"}))
    assert response["ok"] is True
    assert fake.connected is True
    assert "disconnect" not in [call[0] for call in fake.calls]
    assert response["result"]["profile"]["applied"] == []
    assert response["result"]["profile"]["skipped"][0]["error"] == "fff5 write failed"
