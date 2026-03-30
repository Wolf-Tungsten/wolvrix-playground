#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

echo "[PY] Creating virtual environment at ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"

echo "[PY] Installing scikit-build-core into ${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install scikit-build-core

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    # Sourced: activate in the caller's current shell.
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    echo "[PY] Activated ${VENV_DIR} in the current shell"
else
    # Executed: activate in this process and hand off to a new interactive shell.
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    echo "[PY] Starting a new shell with ${VENV_DIR} activated"
    exec "${SHELL:-/bin/bash}" -i
fi
