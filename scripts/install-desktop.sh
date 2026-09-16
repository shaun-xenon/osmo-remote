#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${HOME}/.local/share/applications"
mkdir -p "${TARGET}" "${HOME}/.local/share/icons"

sed -e "s|@ROOT@|${ROOT}|g" "${ROOT}/packaging/osmo-remote.desktop.in" \
  > "${TARGET}/osmo-remote.desktop"
chmod +x "${ROOT}/scripts/run-app.sh"
echo "Installed ${TARGET}/osmo-remote.desktop"
echo "Launcher points at ${ROOT}"
