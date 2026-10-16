"""Named gimbal commands: proven builtins plus hex from settings_map.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from osmo_sidecar.features import features_by_id

SETTINGS_MAP_PATH = Path(__file__).resolve().parents[1] / "settings_map.json"

BUILTIN_COMMANDS = {
    "recenter": {"kind": "recenter"},
    "mode_follow": {"kind": "set_mode", "mode": "follow"},
    "mode_lock": {"kind": "set_mode", "mode": "lock"},
    "mode_fpv": {"kind": "set_mode", "mode": "fpv"},
    "stop": {"kind": "stop"},
    "pc_stick": {"kind": "joystick"},
}


def load_settings_map(path: Path | None = None) -> dict[str, Any]:
    target = path or SETTINGS_MAP_PATH
    if not target.exists():
        return {"apply_on_connect": ["mode_follow"], "commands": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"apply_on_connect": [], "commands": {}}
    if not isinstance(data, dict):
        return {"apply_on_connect": [], "commands": {}}
    commands = data.get("commands") if isinstance(data.get("commands"), dict) else {}
    apply_on_connect = data.get("apply_on_connect")
    if not isinstance(apply_on_connect, list):
        apply_on_connect = []
    return {"apply_on_connect": [str(item) for item in apply_on_connect], "commands": commands}


def hex_for(name: str, mapping: dict[str, Any] | None = None) -> str | None:
    commands = (mapping or load_settings_map())["commands"]
    value = commands.get(name)
    if not isinstance(value, str):
        return None
    cleaned = value.replace(" ", "").strip()
    return cleaned or None


def list_commands(mapping: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    mapping = mapping or load_settings_map()
    catalog = features_by_id()
    names = list(dict.fromkeys([*catalog.keys(), *BUILTIN_COMMANDS.keys(), *mapping["commands"].keys()]))
    rows: list[dict[str, Any]] = []
    for name in names:
        feature = catalog.get(name, {})
        builtin = BUILTIN_COMMANDS.get(name)
        mapped = hex_for(name, mapping)
        ready = bool(builtin) or bool(mapped)
        layer = str(feature.get("layer") or ("ble" if builtin else "unknown"))
        status = "ready" if ready else str(feature.get("status") or "unmapped")
        if feature.get("status") == "out_of_scope":
            status = "out_of_scope"
            ready = False
        rows.append(
            {
                "id": name,
                "tab": feature.get("tab"),
                "layer": layer,
                "status": status,
                "ready": ready,
                "builtin": builtin["kind"] if builtin else None,
                "has_hex": bool(mapped),
                "summary": feature.get("summary"),
                "mimo_label": feature.get("mimo_label"),
                "observed": feature.get("observed"),
                "decision": feature.get("decision"),
            }
        )
    return rows


def partition_settings(commands: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Ready buttons are every mapped/proven command except the live stick."""
    ready = [row for row in commands if row.get("ready") and row.get("builtin") != "joystick"]
    pending = [row for row in commands if row.get("layer") == "ble" and not row.get("ready")]
    other = [row for row in commands if row.get("layer") != "ble"]
    return {"ready": ready, "pending": pending, "other": other}
