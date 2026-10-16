"""Load the Mimo-free feature catalog (gimbal BLE vs phone vs module)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parents[1] / "feature_catalog.json"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or CATALOG_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "features" not in data:
        raise ValueError("feature catalog is missing features")
    return data


def features_by_id(path: Path | None = None) -> dict[str, dict[str, Any]]:
    catalog = load_catalog(path)
    rows = catalog["features"]
    return {str(row["id"]): row for row in rows if isinstance(row, dict) and "id" in row}


def summarize_layers(path: Path | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in load_catalog(path)["features"]:
        layer = str(row.get("layer", "unknown"))
        counts[layer] = counts.get(layer, 0) + 1
    return counts


def build_inventory(path: Path | None = None) -> dict[str, Any]:
    """Screenshot dump + mapping status. HCI hex is filled later via decode-capture."""
    from osmo_sidecar.profile import list_commands

    catalog = load_catalog(path)
    commands = {row["id"]: row for row in list_commands()}
    tabs: dict[str, list[dict[str, Any]]] = {"gimbal": [], "activetrack": [], "general": []}
    for feature in catalog["features"]:
        tab = str(feature.get("tab") or "gimbal")
        cmd = commands.get(str(feature["id"]), {})
        tabs.setdefault(tab, []).append(
            {
                "id": feature["id"],
                "mimo_label": feature.get("mimo_label"),
                "observed": feature.get("observed"),
                "layer": feature.get("layer"),
                "status": cmd.get("status") or feature.get("status"),
                "ready": bool(cmd.get("ready")),
                "decision": feature.get("decision"),
                "summary": feature.get("summary"),
            }
        )
    return {
        "source": catalog.get("source"),
        "screenshots": catalog.get("screenshots") or [],
        "hci_snoop": catalog.get("hci_snoop"),
        "later": catalog.get("later"),
        "tabs": tabs,
    }
