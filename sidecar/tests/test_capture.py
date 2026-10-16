import json
import struct

from osmo_sidecar.capture import decode_capture, diff_captures, extract_duml
from osmo_sidecar.duml import build_set_mode, build_speed_rotate
from osmo_sidecar.gimbal import rewrite_seq


def test_decode_hex_and_rewrite_seq() -> None:
    raw = build_speed_rotate(1500, 0, seq=1)
    decoded = decode_capture(raw.hex())
    assert decoded["total"] == 1
    assert decoded["interesting"][0]["cmd"] == 0x0C
    rewritten = rewrite_seq(raw, 9)
    assert rewritten != raw
    from osmo_sidecar.duml import DumlParser

    assert DumlParser().feed(rewritten)[0].seq == 9


def test_decode_btsnoop_extracts_duml(tmp_path) -> None:
    frame = build_set_mode(1, seq=4)
    blob = b"\x02\x00\x00" + frame
    header = b"btsnoop\x00" + (1).to_bytes(4, "big") + (1002).to_bytes(4, "big")
    record = struct.pack(">IIII", len(blob), len(blob), 0, 0) + (0).to_bytes(8, "big") + blob
    path = tmp_path / "btsnoop_hci.log"
    path.write_bytes(header + record)
    decoded = decode_capture(path)
    assert decoded["kind"] == "btsnoop"
    assert decoded["total"] == 1
    assert decoded["interesting"][0]["cmd"] == 0x4C


def test_decode_sniff_json(tmp_path) -> None:
    raw = build_speed_rotate(-200, 50, seq=2)
    path = tmp_path / "sniff.json"
    path.write_text(json.dumps({"packets": [{"raw": raw.hex(), "telemetry": False}]}))
    decoded = decode_capture(path)
    assert decoded["kind"] == "json"
    assert decoded["total"] == 1
    assert decoded["crc_ok"] == 1


def test_diff_captures_reports_new_frame() -> None:
    before = build_speed_rotate(100, 0, seq=1)
    after = before + build_set_mode(1, seq=2)
    diff = diff_captures(before.hex(), after.hex())
    assert diff["added_count"] == 1
    assert diff["added"][0]["cmd"] == 0x4C


def test_extract_duml_joins_same_direction_fragments() -> None:
    frame = build_set_mode(1, seq=4)
    mid = len(frame) // 2
    packets = extract_duml([frame[:mid], frame[mid:]])
    assert len(packets) == 1
    assert packets[0].cmd == 0x4C


def test_extract_duml_does_not_join_opposite_hci_directions() -> None:
    frame = build_set_mode(1, seq=4)
    mid = len(frame) // 2
    packets = extract_duml([(0, frame[:mid]), (1, frame[mid:])])
    assert packets == []
