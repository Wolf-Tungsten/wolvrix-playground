#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    _SETUP_PYVENV_SOURCED=1
    _SETUP_PYVENV_RESTORE_OPTS="$(set +o)"
    set -uo pipefail
else
    _SETUP_PYVENV_SOURCED=0
    set -euo pipefail
fi

die() {
    local status="$1"
    if [[ "${_SETUP_PYVENV_SOURCED}" == "1" ]]; then
        eval "${_SETUP_PYVENV_RESTORE_OPTS}"
        unset _SETUP_PYVENV_RESTORE_OPTS
        return "${status}"
    fi
    exit "${status}"
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

echo "[PY] Creating virtual environment at ${VENV_DIR}"
python3 -m venv "${VENV_DIR}" || die $?

echo "[PY] Installing scikit-build-core into ${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install scikit-build-core || die $?

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    # Sourced: activate in the caller's current shell.
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate" || die $?
    eval "${_SETUP_PYVENV_RESTORE_OPTS}"
    unset _SETUP_PYVENV_RESTORE_OPTS
    echo "[PY] Activated ${VENV_DIR} in the current shell"
else
    # Executed: activate in this process and hand off to a new interactive shell.
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate" || die $?
    echo "[PY] Starting a new shell with ${VENV_DIR} activated"
    exec "${SHELL:-/bin/bash}" -i
fi
