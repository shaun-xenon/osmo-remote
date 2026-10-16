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

# ATT opcodes that carry a GATT value after opcode + 16-bit handle:
# 0x52 write command, 0x1B handle-value notification, 0x1D indication.
ATT_VALUE_OPCODES = frozenset({0x52, 0x1B, 0x1D})
ATT_CID = 0x0004
H4_ACL = 0x02


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
    """Reassemble DUML across HCI/ACL records. Opposite directions stay separate.

    GATT writes/notifications carry ATT framing (opcode + handle) before the
    DUML bytes. When a DUML frame spans two records, a second record's ATT
    header would otherwise be spliced into the unfinished frame and the CRC
    check would silently drop it, so ATT values are unwrapped first.
    """
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
        for chunk in _att_values(blob):
            for packet in parser.feed(chunk):
                if packet.raw in seen:
                    continue
                if not packet_crc_ok(packet.raw):
                    continue
                seen.add(packet.raw)
                found.append(packet)
    return found


def _att_values(blob: bytes) -> list[bytes]:
    """GATT value bytes inside an HCI ACL record; [blob] unchanged when not HCI."""
    for offset in _acl_offsets(blob):
        values = _att_values_at(blob, offset)
        if values is not None:
            return values
    return [blob]


def _acl_offsets(blob: bytes) -> tuple[int, ...]:
    """Candidate starts of the HCI ACL header (with/without the H4 type byte)."""
    if blob and blob[0] == H4_ACL:
        return (1, 0)
    return (0,)


def _att_values_at(blob: bytes, offset: int) -> list[bytes] | None:
    if len(blob) < offset + 9:
        return None
    acl_len = int.from_bytes(blob[offset + 2 : offset + 4], "little")
    if acl_len != len(blob) - offset - 4:
        return None
    l2cap_len = int.from_bytes(blob[offset + 4 : offset + 6], "little")
    cid = int.from_bytes(blob[offset + 6 : offset + 8], "little")
    if cid != ATT_CID or l2cap_len < 3:
        return []
    att = blob[offset + 8 : offset + 8 + l2cap_len]
    if len(att) < l2cap_len:
        return None
    if att[0] not in ATT_VALUE_OPCODES:
        return []
    return [att[3:]]


def diff_captures(before: Path | bytes | str, after: Path | bytes | str) -> dict[str, Any]:
    """Non-telemetry frames that appear in after but not before (one-toggle HCI sessions).

    Commands are compared by content (senders, cmd set/cmd, payload) without the
    sequence number or CRC, so a re-sent command with a fresh sequence number is
    not reported as new. Rows keep the full raw hex for replay.
    """
    before_keys = {
        _command_key(row) for row in decode_capture(before)["interesting"]
    }
    after_decoded = decode_capture(after)
    added: list[dict[str, Any]] = []
    added_keys: set[str] = set()
    for row in after_decoded["interesting"]:
        key = _command_key(row)
        if key in before_keys or key in added_keys:
            continue
        added_keys.add(key)
        added.append(row)
    return {
        "added": added,
        "added_count": len(added),
        "after_kind": after_decoded["kind"],
    }


def _command_key(row: dict[str, Any]) -> str:
    """Content identity of a DUML command, ignoring seq/checksum."""
    return (
        f"{int(row['sender']):02x}->{int(row['receiver']):02x}"
        f" {int(row['cmd_set']):02x}/{int(row['cmd']):02x} {row['payload']}"
    )


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
