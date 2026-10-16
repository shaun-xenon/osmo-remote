"""BLE driver for Osmo Mobile gimbals (GATT service fff0)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from osmo_sidecar.bluez import reclaim_osmo_sessions
from osmo_sidecar.duml import (
    CMDSET_BATTERY,
    CMD_BATTERY,
    DumlPacket,
    DumlParser,
    PWM_CENTER,
    build_absolute_rotate,
    build_packet,
    build_pwm,
    build_set_mode,
    build_speed_rotate,
    map_stick,
    packet_crc_ok,
    stick_to_pwm,
    stick_to_speed,
)
from osmo_sidecar.profile import (
    BUILTIN_COMMANDS,
    hex_for,
    list_commands,
    load_settings_map,
)

log = logging.getLogger("osmo.gimbal")

SERVICE_FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"
CHAR_FFF5 = "0000fff5-0000-1000-8000-00805f9b34fb"

LIKELY_NAME_PREFIXES = ("OM", "Osmo", "OSMO", "DJI", "om")
WHEEL_MAP_PATH = Path(__file__).resolve().parents[1] / "wheel_map.json"

PacketHandler = Callable[[DumlPacket], Awaitable[None] | None]


@dataclass
class AdvertisedDevice:
    address: str
    name: str
    rssi: int | None
    likely: bool


@dataclass
class InspectResult:
    address: str
    name: str | None
    services: list[dict[str, Any]]
    has_fff0: bool
    has_fff4: bool
    has_fff5: bool
    mtu: int | None


@dataclass
class GimbalState:
    connected: bool = False
    address: str | None = None
    name: str | None = None
    battery: int | None = None
    charging: bool | None = None
    last_error: str | None = None
    wheel_supported: bool = False
    wheel_reason: str = (
        "Zoom/focus is not mapped. Sniff the physical wheel while this app owns BLE, "
        "then copy hex into sidecar/wheel_map.json."
    )


class Gimbal:
    def __init__(self, on_packet: PacketHandler | None = None) -> None:
        self._client: BleakClient | None = None
        self._parser = DumlParser()
        self._seq = 1
        self._on_packet = on_packet
        self._sniff: list[dict[str, Any]] = []
        self._sniffing = False
        self.state = GimbalState()
        self._lock = asyncio.Lock()
        self.captured_packets: list[DumlPacket] = []
        mapping = load_wheel_map()
        if mapping:
            self.state.wheel_supported = True
            self.state.wheel_reason = mapping.get(
                "note",
                "Using sidecar/wheel_map.json. Zoom/focus is still experimental on OM7P.",
            )

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def scan(self, timeout: float = 8.0) -> list[AdvertisedDevice]:
        reclaimed = await reclaim_osmo_sessions()
        if reclaimed:
            log.info("reclaimed BlueZ sessions: %s", ", ".join(reclaimed))
        found: dict[str, AdvertisedDevice] = {}

        def _detected(device: Any, adv: Any) -> None:
            name = device.name or getattr(adv, "local_name", None) or ""
            rssi = getattr(adv, "rssi", None)
            uuids = [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]
            has_fff0 = SERVICE_FFF0 in uuids or any(u.endswith("fff0") for u in uuids)
            likely = _is_likely_osmo(name) or has_fff0
            label = name or ("Osmo service" if has_fff0 else "(no name)")
            previous = found.get(device.address)
            if previous is None or (name and previous.name in {"(no name)", "Osmo service"}):
                found[device.address] = AdvertisedDevice(
                    address=device.address,
                    name=label,
                    rssi=rssi,
                    likely=likely,
                )

        scanner = BleakScanner(detection_callback=_detected)
        try:
            await scanner.start()
        except BleakError as exc:
            raise RuntimeError(
                "Bluetooth is not available. Unblock the adapter (`rfkill unblock bluetooth`), "
                "enable it in KDE, and make sure bluetoothd is running."
            ) from exc
        try:
            await asyncio.sleep(timeout)
        finally:
            await scanner.stop()

        devices = sorted(
            found.values(),
            key=lambda item: (not item.likely, item.name.lower(), item.address),
        )
        return devices

    async def connect(self, address: str, timeout: float = 20.0, name: str | None = None) -> InspectResult:
        await self.disconnect()
        last_error: Exception | None = None
        await reclaim_osmo_sessions()
        for attempt in range(1, 5):
            await drop_stale_connection(address)
            client = BleakClient(address, timeout=timeout, disconnected_callback=self._on_disconnected)
            try:
                await client.connect()
                self._client = client
                self._parser = DumlParser()
                self.state.connected = True
                self.state.address = address
                self.state.name = name or address
                inspect = await self.inspect()
                self.state.name = name or inspect.name or address
                if inspect.has_fff4:
                    await self._subscribe(CHAR_FFF4)
                if inspect.has_fff5:
                    try:
                        await self._subscribe(CHAR_FFF5)
                    except BleakError:
                        log.info("fff5 notify not available; writes only")
                await self._acquire_mtu()
                return inspect
            except BleakError as exc:
                last_error = exc
                log.warning("connect attempt %s failed: %s", attempt, exc)
                self._client = None
                self.state.connected = False
                try:
                    if client.is_connected:
                        await client.disconnect()
                except BleakError:
                    pass
                await asyncio.sleep(0.8 * attempt)
        raise RuntimeError(
            f"Connect failed: {last_error}. On the phone, unpair only the Osmo gimbal "
            "(leave Bluetooth on for mics). Then Scan again. "
            "This app now untrusts the gimbal in BlueZ so KDE should not auto-connect "
            "(that is not Forget — you should not need to remove it every time)."
        ) from last_error

    async def disconnect(self) -> None:
        client = self._client
        self._client = None
        self.state.connected = False
        if client is None:
            return
        try:
            if client.is_connected:
                try:
                    await client.stop_notify(CHAR_FFF4)
                except BleakError:
                    pass
                try:
                    await client.stop_notify(CHAR_FFF5)
                except BleakError:
                    pass
                await client.disconnect()
        except BleakError as exc:
            log.warning("disconnect: %s", exc)

    def _on_disconnected(self, _client: BleakClient) -> None:
        self.state.connected = False
        self.state.last_error = "Gimbal disconnected"

    async def inspect(self) -> InspectResult:
        client = self._require_client()
        services: list[dict[str, Any]] = []
        has_fff0 = has_fff4 = has_fff5 = False
        for service in client.services:
            chars: list[dict[str, Any]] = []
            uuid = service.uuid.lower()
            if uuid == SERVICE_FFF0:
                has_fff0 = True
            for char in service.characteristics:
                cuuid = char.uuid.lower()
                if cuuid == CHAR_FFF4:
                    has_fff4 = True
                if cuuid == CHAR_FFF5:
                    has_fff5 = True
                chars.append(
                    {
                        "uuid": char.uuid,
                        "properties": list(char.properties),
                        "handle": char.handle,
                    }
                )
            services.append({"uuid": service.uuid, "characteristics": chars})
        name = self.state.name
        mtu = getattr(client, "mtu_size", None)
        return InspectResult(
            address=client.address,
            name=name,
            services=services,
            has_fff0=has_fff0,
            has_fff4=has_fff4,
            has_fff5=has_fff5,
            mtu=mtu,
        )

    async def pair_probe(self) -> None:
        """Pocket-3 style pairing poke; may be ignored on Osmo Mobile."""
        client = self._require_client()
        await client.write_gatt_char(CHAR_FFF4, bytes([0x01, 0x00]), response=True)

    async def joystick(
        self,
        yaw: float,
        pitch: float,
        *,
        max_speed: int = 1200,
        method: str = "speed",
        invert_yaw: bool = False,
        invert_pitch: bool = False,
    ) -> None:
        yaw_axis, pitch_axis = map_stick(
            yaw,
            pitch,
            invert_yaw=invert_yaw,
            invert_pitch=invert_pitch,
        )
        if method == "pwm":
            packet = build_pwm(
                stick_to_pwm(yaw_axis),
                stick_to_pwm(pitch_axis),
                PWM_CENTER,
                seq=self._next_seq(),
            )
        else:
            packet = build_speed_rotate(
                stick_to_speed(yaw_axis, max_speed),
                stick_to_speed(pitch_axis, max_speed),
                0,
                time=10,
                seq=self._next_seq(),
            )
        await self._write(packet)

    async def stop(self) -> None:
        await self._write(build_speed_rotate(0, 0, 0, time=10, seq=self._next_seq()))
        await self._write(build_pwm(PWM_CENTER, PWM_CENTER, PWM_CENTER, seq=self._next_seq()))

    async def recenter(self) -> None:
        await self.stop()
        await self._write(build_absolute_rotate(0, 0, 0, time=20, seq=self._next_seq()))

    async def set_mode(self, mode: str) -> None:
        mapping = {"lock": 0, "follow": 1, "ptf": 1, "fpv": 2}
        if mode not in mapping:
            raise ValueError(f"Unknown mode: {mode}")
        await self._write(build_set_mode(mapping[mode], seq=self._next_seq()))

    async def pulse(self, yaw: int = 800, seconds: float = 0.8) -> None:
        await self._write(build_speed_rotate(yaw, 0, 0, time=10, seq=self._next_seq()))
        await asyncio.sleep(seconds)
        await self.stop()

    def start_sniff(self) -> None:
        self._sniff = []
        self._sniffing = True

    def stop_sniff(self) -> list[dict[str, Any]]:
        self._sniffing = False
        return list(self._sniff)

    def analyze_sniff(self, packets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = packets if packets is not None else self._sniff
        counts: dict[str, int] = {}
        interesting: list[dict[str, Any]] = []
        for row in rows:
            key = f"0x{row['cmd_set']:02x}/0x{row['cmd']:02x}"
            counts[key] = counts.get(key, 0) + 1
            if not row.get("telemetry"):
                interesting.append(row)
        mapping = load_wheel_map()
        if mapping:
            wheel_supported = True
            reason = mapping.get(
                "note",
                "Using sidecar/wheel_map.json. Zoom/focus is still experimental on OM7P.",
            )
        elif interesting:
            wheel_supported = False
            reason = (
                f"Sniff captured {len(interesting)} non-telemetry packet(s). "
                "Copy confirmed zoom_in/zoom_out hex into sidecar/wheel_map.json to enable the wheel."
            )
        else:
            wheel_supported = False
            reason = GimbalState().wheel_reason
        self.state.wheel_supported = wheel_supported
        self.state.wheel_reason = reason
        return {
            "total": len(rows),
            "counts": counts,
            "interesting": interesting[:50],
            "wheel_supported": wheel_supported,
            "wheel_reason": reason,
        }

    async def wheel(self, delta: float) -> None:
        mapping = load_wheel_map()
        if not mapping:
            raise RuntimeError(self.state.wheel_reason)
        key = "zoom_in" if delta > 0 else "zoom_out"
        payload_hex = mapping.get(key)
        if not payload_hex:
            raise RuntimeError(f"sidecar/wheel_map.json is missing '{key}'")
        await self._write(bytes.fromhex(str(payload_hex).replace(" ", "")))

    async def send_raw(self, payload_hex: str) -> dict[str, Any]:
        raw = bytes.fromhex(payload_hex.replace(" ", ""))
        if not raw:
            raise ValueError("hex payload is empty")
        rewritten = rewrite_seq(raw, self._next_seq())
        await self._write(rewritten)
        return {
            "bytes": len(rewritten),
            "rewrote_seq": rewritten != raw,
            "hex": rewritten.hex(),
        }

    async def apply_setting(self, name: str) -> dict[str, Any]:
        builtin = BUILTIN_COMMANDS.get(name)
        if builtin:
            kind = builtin["kind"]
            if kind == "recenter":
                await self.recenter()
            elif kind == "stop":
                await self.stop()
            elif kind == "set_mode":
                await self.set_mode(str(builtin["mode"]))
            elif kind == "joystick":
                return {"id": name, "kind": kind}
            else:
                raise ValueError(f"Unsupported builtin: {name}")
            return {"id": name, "kind": kind}
        mapped = hex_for(name)
        if not mapped:
            raise RuntimeError(
                f"Setting '{name}' is not mapped. Capture DUML (HCI snoop or sniff), "
                "put hex in sidecar/settings_map.json, then replay."
            )
        sent = await self.send_raw(mapped)
        return {"id": name, "kind": "hex", **sent}

    async def apply_profile(self, names: list[str] | None = None) -> dict[str, Any]:
        mapping = load_settings_map()
        selected = names if names is not None else mapping["apply_on_connect"]
        applied: list[str] = []
        skipped: list[dict[str, str]] = []
        for name in selected:
            try:
                await self.apply_setting(name)
                applied.append(name)
            except (RuntimeError, ValueError, BleakError) as exc:
                skipped.append({"id": name, "error": str(exc)})
        return {"applied": applied, "skipped": skipped}

    def list_settings(self) -> list[dict[str, Any]]:
        return list_commands()

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        if self._seq == 0:
            self._seq = 1
        return seq

    def _require_client(self) -> BleakClient:
        client = self._client
        if client is None or not client.is_connected:
            raise RuntimeError("Not connected")
        return client

    async def _subscribe(self, uuid: str) -> None:
        client = self._require_client()
        await client.start_notify(uuid, self._on_notify)

    async def _acquire_mtu(self) -> None:
        client = self._require_client()
        backend = getattr(client, "_backend", None)
        acquire = getattr(backend, "_acquire_mtu", None)
        if callable(acquire):
            try:
                await acquire()
            except Exception as exc:  # noqa: BLE001
                log.info("MTU acquire skipped: %s", exc)

    async def _write(self, packet: bytes) -> None:
        client = self._require_client()
        mtu = getattr(client, "mtu_size", 23) or 23
        chunk_size = max(20, mtu - 3)
        async with self._lock:
            for offset in range(0, len(packet), chunk_size):
                chunk = packet[offset : offset + chunk_size]
                await client.write_gatt_char(CHAR_FFF5, chunk, response=False)

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        packets = self._parser.feed(bytes(data))
        for packet in packets:
            self._handle_packet(packet)

    def _handle_packet(self, packet: DumlPacket) -> None:
        if packet.cmd_set == CMDSET_BATTERY and packet.cmd == CMD_BATTERY and packet.payload:
            self.state.battery = packet.payload[0]
            if len(packet.payload) >= 2:
                self.state.charging = packet.payload[-1] == 1
        row = {
            "ts": time.time(),
            "cmd_set": packet.cmd_set,
            "cmd": packet.cmd,
            "sender": packet.sender,
            "receiver": packet.receiver,
            "seq": packet.seq,
            "payload": packet.payload.hex(),
            "raw": packet.raw.hex(),
            "telemetry": packet.is_telemetry,
            "summary": packet.summary(),
        }
        if self._sniffing:
            self._sniff.append(row)
        if self._on_packet:
            result = self._on_packet(packet)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)


async def drop_stale_connection(address: str) -> None:
    """Drop a leftover BlueZ GATT session so Bleak can connect again."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            "disconnect",
            address,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=6)
    except (TimeoutError, FileNotFoundError, OSError) as exc:
        log.info("bluetoothctl disconnect skipped: %s", exc)
    await asyncio.sleep(0.4)


def load_wheel_map() -> dict[str, Any] | None:
    if not WHEEL_MAP_PATH.exists():
        return None
    try:
        data = json.loads(WHEEL_MAP_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_likely_osmo(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(prefix.upper()) for prefix in LIKELY_NAME_PREFIXES)


def rewrite_seq(raw: bytes, seq: int) -> bytes:
    """Rebuild a valid DUML frame with a fresh sequence number for replay."""
    if not packet_crc_ok(raw):
        return raw
    packets = DumlParser().feed(raw)
    if len(packets) != 1 or packets[0].raw != raw:
        return raw
    packet = packets[0]
    return build_packet(
        packet.cmd_set,
        packet.cmd,
        packet.payload,
        seq=seq,
        sender=packet.sender,
        receiver=packet.receiver,
        attributes=packet.attributes,
    )


def inspect_to_dict(info: InspectResult) -> dict[str, Any]:
    return {
        "address": info.address,
        "name": info.name,
        "services": info.services,
        "has_fff0": info.has_fff0,
        "has_fff4": info.has_fff4,
        "has_fff5": info.has_fff5,
        "mtu": info.mtu,
    }
