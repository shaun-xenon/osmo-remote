"""Decode DUML from Android HCI snoop logs, sniff JSON, hex dumps, or raw bytes."""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

Blob = bytes | tuple[int | None, bytes]

from osmo_sidecar.duml import DumlPacket, DumlParser, packet_crc_ok

BTSNOOP_MAGIC = b"btsnoop\x00"
HEX_RE = re.compile(r"[^0-9a-fA-F]+")


def decode_capture(source: Path | bytes | str) -> dict[str, Any]:
    """Return labeled DUML frames found in a capture file or blob."""
    kind, blobs = _load_blobs(source)
    packets = extract_duml(list(blobs))
    rows = [packet.as_row() for packet in packets]
    counts: dict[str, int] = {}
    interesting: list[dict[str, Any]] = []
    for row in rows:
        key = str(row["label"])
        counts[key] = counts.get(key, 0) + 1
        if not row["telemetry"]:
            interesting.append(row)
    return {
        "kind": kind,
        "total": len(rows),
        "crc_ok": sum(1 for row in rows if row["crc_ok"]),
        "counts": counts,
        "packets": rows,
        "interesting": interesting,
    }


def extract_duml(blobs: Sequence[Blob]) -> list[DumlPacket]:
    """Reassemble DUML across HCI/ACL records. Opposite directions stay separate."""
    parsers: dict[object, DumlParser] = {}
    found: list[DumlPacket] = []
    seen: set[bytes] = set()
    for item in blobs:
        if isinstance(item, tuple):
            flags, blob = item
            direction: object = flags & 1 if isinstance(flags, int) else "stream"
        else:
            blob = item
            direction = "stream"
        parser = parsers.setdefault(direction, DumlParser())
        for packet in parser.feed(blob):
            if packet.raw in seen:
                continue
            if not packet_crc_ok(packet.raw):
                continue
            seen.add(packet.raw)
            found.append(packet)
    return found


def diff_captures(before: Path | bytes | str, after: Path | bytes | str) -> dict[str, Any]:
    """Non-telemetry frames that appear in after but not before (one-toggle HCI sessions)."""
    before_rows = {str(row["raw"]): row for row in decode_capture(before)["interesting"]}
    after_decoded = decode_capture(after)
    added = [row for row in after_decoded["interesting"] if str(row["raw"]) not in before_rows]
    return {
        "added": added,
        "added_count": len(added),
        "after_kind": after_decoded["kind"],
    }


def parse_hex_blob(text: str) -> bytes:
    cleaned = HEX_RE.sub("", text)
    if not cleaned:
        return b""
    if len(cleaned) % 2:
        raise ValueError("odd-length hex")
    return bytes.fromhex(cleaned)


def _load_blobs(source: Path | bytes | str) -> tuple[str, list[Blob]]:
    if isinstance(source, bytes):
        return _blobs_from_bytes(source, hint="bytes")
    if isinstance(source, str) and not Path(source).exists():
        return ("hex", [parse_hex_blob(source)])
    path = Path(source)
    data = path.read_bytes()
    return _blobs_from_bytes(data, hint=path.name)


def _blobs_from_bytes(data: bytes, *, hint: str) -> tuple[str, list[Blob]]:
    if data.startswith(BTSNOOP_MAGIC):
        return ("btsnoop", list(_iter_btsnoop_payloads(data)))
    stripped = data.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        blobs = _blobs_from_json(stripped.decode("utf-8", errors="replace"))
        return ("json", blobs)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ("raw", [data])
    if HEX_RE.sub("", text) and all(ch in "0123456789abcdefABCDEF \n\r\t" for ch in text.strip()[:80]):
        try:
            return ("hex", [parse_hex_blob(text)])
        except ValueError:
            pass
    return (hint, [data])


def _blobs_from_json(text: str) -> list[bytes]:
    payload = json.loads(text)
    blobs: list[bytes] = []
    for row in _json_packet_rows(payload):
        raw_hex = str(row.get("raw") or "")
        if raw_hex:
            blobs.append(parse_hex_blob(raw_hex))
            continue
        payload_hex = str(row.get("payload") or "")
        if payload_hex:
            blobs.append(parse_hex_blob(payload_hex))
    if not blobs:
        blobs.append(text.encode("utf-8"))
    return blobs


def _json_packet_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        packets = payload.get("packets")
        if isinstance(packets, list):
            return [row for row in packets if isinstance(row, dict)]
        if "raw" in payload or "payload" in payload:
            return [payload]
    return []


def _iter_btsnoop_payloads(data: bytes) -> Iterator[tuple[int, bytes]]:
    offset = 16
    while offset + 24 <= len(data):
        _orig, included, flags, _drops = struct.unpack_from(">IIII", data, offset)
        offset += 16
        offset += 8
        if included < 0 or offset + included > len(data):
            break
        yield flags, data[offset : offset + included]
        offset += included
