"""JSON-lines sidecar protocol over stdin/stdout."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, TextIO

from osmo_sidecar.duml import DumlPacket
from osmo_sidecar.gimbal import Gimbal, inspect_to_dict


class SidecarServer:
    def __init__(self, gimbal: Gimbal | None = None) -> None:
        self.gimbal = gimbal or Gimbal(on_packet=self._on_packet)
        self._out_lock = asyncio.Lock()
        self._running = True

    async def run(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        reader = asyncio.StreamReader()
        loop = asyncio.get_running_loop()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, stdin or sys.stdin)
        self._stdout = stdout or sys.stdout
        await self._emit({"event": "ready", "message": "osmo-sidecar listening"})
        try:
            while self._running:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except json.JSONDecodeError as exc:
                    await self._emit({"ok": False, "error": f"invalid json: {exc}"})
                    continue
                await self._handle(request)
                if not self._running:
                    break
        finally:
            await self.gimbal.disconnect()

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Pure request handler used by tests and the stdio loop."""
        cmd = request.get("cmd")
        if not isinstance(cmd, str):
            return {"ok": False, "error": "missing cmd"}
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        try:
            result = await handler(request)
            return {"ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def _handle(self, request: dict[str, Any]) -> None:
        req_id = request.get("id")
        response = await self.handle_request(request)
        if req_id is not None:
            response["id"] = req_id
        await self._emit(response)

    async def _cmd_scan(self, request: dict[str, Any]) -> dict[str, Any]:
        timeout = float(request.get("timeout", 8))
        devices = await self.gimbal.scan(timeout=timeout)
        rows = [
            {"address": d.address, "name": d.name, "rssi": d.rssi, "likely": d.likely}
            for d in devices
        ]
        return {"devices": rows}

    async def _cmd_connect(self, request: dict[str, Any]) -> dict[str, Any]:
        address = request.get("address")
        if not address:
            raise ValueError("address required")
        inspect = await self.gimbal.connect(
            str(address),
            timeout=float(request.get("timeout", 20)),
            name=request.get("name"),
        )
        await self._emit_status()
        return inspect_to_dict(inspect)

    async def _cmd_disconnect(self, _request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.disconnect()
        await self._emit_status()
        return {"connected": False}

    async def _cmd_inspect(self, _request: dict[str, Any]) -> dict[str, Any]:
        return inspect_to_dict(await self.gimbal.inspect())

    async def _cmd_joystick(self, request: dict[str, Any]) -> dict[str, Any]:
        yaw = float(request.get("yaw", 0))
        pitch = float(request.get("pitch", 0))
        max_speed = int(request.get("max_speed", 1200))
        method = str(request.get("method", "speed"))
        await self.gimbal.joystick(yaw, pitch, max_speed=max_speed, method=method)
        return {"yaw": yaw, "pitch": pitch}

    async def _cmd_stop(self, _request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.stop()
        return {}

    async def _cmd_recenter(self, _request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.recenter()
        return {}

    async def _cmd_set_mode(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = str(request.get("mode", "follow"))
        await self.gimbal.set_mode(mode)
        return {"mode": mode}

    async def _cmd_pulse(self, request: dict[str, Any]) -> dict[str, Any]:
        yaw = int(request.get("yaw", 800))
        seconds = float(request.get("seconds", 0.8))
        await self.gimbal.pulse(yaw=yaw, seconds=seconds)
        return {"yaw": yaw}

    async def _cmd_pair_probe(self, _request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.pair_probe()
        return {"wrote": "fff4 01 00"}

    async def _cmd_sniff_start(self, _request: dict[str, Any]) -> dict[str, Any]:
        self.gimbal.start_sniff()
        return {"sniffing": True}

    async def _cmd_sniff_stop(self, _request: dict[str, Any]) -> dict[str, Any]:
        packets = self.gimbal.stop_sniff()
        analysis = self.gimbal.analyze_sniff(packets)
        return {"packets": packets, "analysis": analysis}

    async def _cmd_wheel(self, request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.wheel(float(request.get("delta", 0)))
        return {}

    async def _cmd_status(self, _request: dict[str, Any]) -> dict[str, Any]:
        return self._status_payload()

    async def _cmd_ping(self, _request: dict[str, Any]) -> dict[str, Any]:
        return {"pong": True}

    async def _cmd_shutdown(self, _request: dict[str, Any]) -> dict[str, Any]:
        await self.gimbal.disconnect()
        self._running = False
        return {"shutdown": True}

    def _status_payload(self) -> dict[str, Any]:
        state = self.gimbal.state
        return {
            "connected": self.gimbal.connected,
            "address": state.address,
            "name": state.name,
            "battery": state.battery,
            "charging": state.charging,
            "wheel_supported": state.wheel_supported,
            "wheel_reason": state.wheel_reason,
            "last_error": state.last_error,
        }

    async def _on_packet(self, packet: DumlPacket) -> None:
        if packet.is_telemetry:
            await self._emit_status()
            return
        await self._emit(
            {
                "event": "packet",
                "cmd_set": packet.cmd_set,
                "cmd": packet.cmd,
                "summary": packet.summary(),
                "payload": packet.payload.hex(),
            }
        )

    async def _emit_status(self) -> None:
        await self._emit({"event": "status", **self._status_payload()})

    async def _emit(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"))
        async with self._out_lock:
            out = getattr(self, "_stdout", sys.stdout)
            out.write(line + "\n")
            out.flush()
