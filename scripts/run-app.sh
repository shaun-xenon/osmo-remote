#!/usr/bin/env bash
set -euo pipefail

# KDE .desktop launches are not login shells, so nvm/fnm/asdf are often missing.
set +u
if [[ -f "${HOME}/.profile" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.profile"
fi
if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.nvm/nvm.sh"
fi
if command -v fnm >/dev/null 2>&1; then
  eval "$(fnm env)"
fi
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not on PATH. Install Node or run from a terminal: cd '${ROOT}' && npm start" >&2
  exit 1
fi

exec npm start
