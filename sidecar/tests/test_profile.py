from pathlib import Path

from osmo_sidecar.features import build_inventory, load_catalog, summarize_layers
from osmo_sidecar.profile import list_commands, load_settings_map, partition_settings


def test_catalog_is_mimo_free() -> None:
    catalog = load_catalog()
    assert "Mimo is not used at shoot time" in catalog["shooting"]
    layers = summarize_layers()
    assert layers["ble"] >= 1
    assert layers["phone"] >= 1
    assert layers["module"] >= 1
    by_id = {row["id"]: row for row in catalog["features"]}
    assert by_id["photo_aspect"]["layer"] == "phone"
    assert by_id["active_track_fast_follow"]["status"] == "out_of_scope"
    assert by_id["photo_aspect"]["observed"] == "16:9"
    assert by_id["invert_joystick"]["observed"] == "Vertical"
    assert by_id["sleep"]["observed"] == "Disable"
    assert by_id["sound"]["layer"] == "ble"
    assert by_id["demo_mode"]["layer"] == "ble"
    assert by_id["show_more_modes"]["layer"] == "phone"
    assert by_id["gimbal_auto_cal"]["layer"] == "ble"
    inventory = build_inventory()
    assert inventory["hci_snoop"] == "pending"
    assert len(inventory["screenshots"]) == 5
    assert inventory["screenshots"][0]["tab"] == "gimbal"
    assert inventory["screenshots"][2]["tab"] == "activetrack"
    assert inventory["screenshots"][3]["tab"] == "general"
    assert inventory["later"]["activetrack"].startswith("Ignore")
    assert by_id["photo_aspect"]["decision"]


def test_builtins_are_ready_without_map() -> None:
    rows = {row["id"]: row for row in list_commands()}
    assert rows["recenter"]["ready"] is True
    assert rows["mode_follow"]["observed"] == "PTF"
    assert rows["pc_stick"]["ready"] is True
    assert rows["pc_stick"]["builtin"] == "joystick"
    assert rows["gimbal_auto_cal"]["ready"] is False
    assert rows["grid"]["status"] == "out_of_scope"
    assert rows["grid"]["ready"] is False


def test_settings_map_hex_marks_ready(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings_map.json"
    path.write_text('{"apply_on_connect": [], "commands": {"extend_tilt": "5515"}}')
    monkeypatch.setattr("osmo_sidecar.profile.SETTINGS_MAP_PATH", path)
    mapping = load_settings_map()
    rows = {row["id"]: row for row in list_commands(mapping)}
    assert rows["extend_tilt"]["has_hex"] is True
    assert rows["extend_tilt"]["ready"] is True


def test_settings_ready_includes_mapped_not_just_live_ids() -> None:
    commands = [
        {"id": "recenter", "ready": True, "layer": "ble", "builtin": "recenter"},
        {"id": "extend_tilt", "ready": True, "layer": "ble", "builtin": None},
        {"id": "pc_stick", "ready": True, "layer": "ble", "builtin": "joystick"},
        {"id": "sound", "ready": False, "layer": "ble"},
        {"id": "photo_aspect", "ready": False, "layer": "phone"},
    ]
    parts = partition_settings(commands)
    ready_ids = [row["id"] for row in parts["ready"]]
    pending_ids = [row["id"] for row in parts["pending"]]
    other_ids = [row["id"] for row in parts["other"]]
    assert ready_ids == ["recenter", "extend_tilt"]
    assert pending_ids == ["sound"]
    assert "pc_stick" not in pending_ids
    assert other_ids == ["photo_aspect"]


def test_settings_jsx_has_no_liveid_whitelist() -> None:
    src = Path(__file__).resolve().parents[2] / "renderer" / "src" / "Settings.jsx"
    text = src.read_text(encoding="utf-8")
    assert "liveIds" not in text
    assert "partitionSettings" in text
