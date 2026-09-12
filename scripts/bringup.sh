#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/sidecar/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "Run npm run sidecar:setup first." >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/sidecar"

echo "== BLE scan (8s). Power the 7P, close Mimo, unpair in KDE. =="
"${PYTHON}" -m osmo_sidecar scan --timeout 8

ADDRESS="${1:-}"
if [[ -z "${ADDRESS}" ]]; then
  echo
  echo "Re-run with the gimbal address to inspect GATT and send a yaw pulse:"
  echo "  $0 AA:BB:CC:DD:EE:FF"
  exit 0
fi

echo
echo "== Inspect ${ADDRESS} =="
"${PYTHON}" -m osmo_sidecar inspect "${ADDRESS}"

echo
echo "== SPEED yaw pulse =="
"${PYTHON}" -m osmo_sidecar pulse "${ADDRESS}" --yaw 800 --seconds 0.8

echo
echo "== Sniff 12s — turn the physical zoom/focus wheel now =="
"${PYTHON}" -m osmo_sidecar sniff "${ADDRESS}" --seconds 12 --out "${ROOT}/sidecar/sniff-latest.json"
echo "Wrote sidecar/sniff-latest.json"
