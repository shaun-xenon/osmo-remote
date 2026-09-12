import asyncio

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

    async def joystick(self, yaw: float, pitch: float, *, max_speed: int = 1200, method: str = "speed"):
        self.calls.append(("joystick", yaw, pitch, max_speed, method))

    async def stop(self):
        self.calls.append(("stop",))

    async def recenter(self):
        self.calls.append(("recenter",))

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def wheel(self, delta: float):
        raise RuntimeError(self.state.wheel_reason)


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
