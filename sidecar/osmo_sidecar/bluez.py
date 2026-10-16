"""BlueZ helpers so KDE/Plasma does not steal the OM7P GATT session."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("osmo.bluez")

DEVICE_LINE = re.compile(r"Device\s+([0-9A-F:]{17})\s+(.*)", re.IGNORECASE)
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)
# Scan ranking may use DJI/OM/Osmo prefixes. Destructive reclaim must not.
LIKELY_NAME_PREFIXES = ("OM", "Osmo", "OSMO", "DJI", "om")
SERVICE_FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True)
class BluezDevice:
    address: str
    name: str


def parse_device_lines(text: str) -> list[BluezDevice]:
    found: list[BluezDevice] = []
    for line in text.splitlines():
        match = DEVICE_LINE.search(line.strip())
        if not match:
            continue
        found.append(BluezDevice(address=match.group(1).upper(), name=match.group(2).strip()))
    return found


def parse_uuids(text: str) -> list[str]:
    return [match.lower() for match in UUID_RE.findall(text or "")]


def is_osmo_device(device: BluezDevice) -> bool:
    """Prefix match for scan ranking (includes DJI mics and other accessories)."""
    if not device.name:
        return False
    upper = device.name.upper()
    return any(upper.startswith(prefix.upper()) for prefix in LIKELY_NAME_PREFIXES)


def is_osmo_gimbal(device: BluezDevice, uuids: list[str] | None = None) -> bool:
    """True only for the OM7P/gimbal — precise name or fff0 service UUID."""
    if uuids:
        lowered = [uuid.lower() for uuid in uuids]
        if SERVICE_FFF0 in lowered or any(uuid.endswith("fff0") for uuid in lowered):
            return True
    if not device.name:
        return False
    upper = device.name.strip().upper()
    if upper.startswith("OM") and len(upper) > 2 and upper[2].isdigit():
        return True
    if upper.startswith("OSMO"):
        return True
    if upper.startswith("DJI OSMO"):
        return True
    return False


async def bluetoothctl(*args: str, timeout: float = 8.0) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        log.info("bluetoothctl missing: %s", exc)
        return ""
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        log.info("bluetoothctl %s timed out", " ".join(args))
        return ""
    text = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if proc.returncode not in (0, None) and err:
        log.info("bluetoothctl %s: %s", " ".join(args), err.strip()[:200])
    return text


async def list_known_devices() -> list[BluezDevice]:
    connected = parse_device_lines(await bluetoothctl("devices", "Connected"))
    known = parse_device_lines(await bluetoothctl("devices"))
    by_addr = {item.address: item for item in known}
    for item in connected:
        by_addr[item.address] = item
    return list(by_addr.values())


async def reclaim_osmo_sessions() -> list[str]:
    """Disconnect Osmo gimbals and untrust them so Plasma will not auto-reconnect.

    Untrust is not Forget: the device stays paired, but KDE should stop grabbing GATT
    as soon as the gimbal appears. Leave the phone Bluetooth adapter on for mics.
    On the phone, unpair only the OM7P entry so Android does not GATT-connect to it.
    Prefix-matched accessories (DJI Mic Mini, etc.) are not reclaimed unless they
    advertise the gimbal fff0 service.
    """
    reclaimed: list[str] = []
    for device in await list_known_devices():
        if not is_osmo_gimbal(device):
            if not is_osmo_device(device):
                continue
            uuids = parse_uuids(await bluetoothctl("info", device.address))
            if not is_osmo_gimbal(device, uuids):
                continue
        await bluetoothctl("disconnect", device.address)
        await bluetoothctl("untrust", device.address)
        reclaimed.append(f"{device.address} {device.name}".strip())
    if reclaimed:
        await asyncio.sleep(0.6)
    return reclaimed
