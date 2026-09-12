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
# fnm's binary is usually not on the desktop PATH.
if [[ -z "${FNM_DIR:-}" ]]; then
  if [[ -x "${HOME}/.local/share/fnm/fnm" ]]; then
    FNM_DIR="${HOME}/.local/share/fnm"
  elif [[ -x "${HOME}/.fnm/fnm" ]]; then
    FNM_DIR="${HOME}/.fnm"
  fi
fi
if [[ -n "${FNM_DIR:-}" && -x "${FNM_DIR}/fnm" ]]; then
  eval "$("${FNM_DIR}/fnm" env)"
elif command -v fnm >/dev/null 2>&1; then
  eval "$(fnm env)"
fi
if [[ -f "${HOME}/.asdf/asdf.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.asdf/asdf.sh"
fi
PATH="${HOME}/.local/bin:${PATH}"
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not on PATH. Install Node or run from a terminal: cd '${ROOT}' && npm start" >&2
  exit 1
fi

exec npm start
