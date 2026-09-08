#!/usr/bin/env bash
#
# Compile and upload the Mega gantry, reading its settings from config/rig.json.
#
#   ./scripts/flash.sh                    compile, then upload
#   ./scripts/flash.sh compile            compile only
#   ./scripts/flash.sh upload             upload only
#   ./scripts/flash.sh boards             list what arduino-cli can see on USB
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/config/rig.json"
ACTION="both"
if [ -n "${1:-}" ]; then
  ACTION="$1"
fi

# Which interpreter: the venv's if it exists (always called `python` inside a
# venv, on every machine), otherwise whichever of python3/python this box has.
# The Pi and the dev desktop do not agree on that name.
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "!! No python interpreter found (tried .venv/bin/python, python3, python)." >&2
  exit 1
fi

read_cfg() {  # read_cfg <section> <key>
  "$PYTHON" -c "import json,sys; print(json.load(open('$CONFIG'))['$1']['$2'])"
}

if ! command -v arduino-cli >/dev/null 2>&1; then
  cat >&2 <<'MSG'
arduino-cli is not installed.

  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
  sudo mv bin/arduino-cli /usr/local/bin/
  arduino-cli config init
  arduino-cli core update-index
  arduino-cli core install arduino:avr
MSG
  exit 1
fi

if [ "$ACTION" = "boards" ]; then
  arduino-cli board list
  exit 0
fi

if [ "$ACTION" != "compile" ] && [ "$ACTION" != "upload" ] && [ "$ACTION" != "both" ]; then
  echo "!! action must be compile, upload, both, or boards" >&2
  exit 2
fi

flash_mega() {
  local fqbn sketch port
  fqbn="$(read_cfg board fqbn)"
  sketch="$ROOT/$(read_cfg board sketch)"
  port="$(read_cfg serial port)"

  if [ "$ACTION" = "compile" ] || [ "$ACTION" = "both" ]; then
    echo ">> compiling Mega gantry: $sketch for $fqbn"
    arduino-cli compile --fqbn "$fqbn" "$sketch"
    echo ">> Mega gantry compile OK"
  fi

  if [ "$ACTION" != "upload" ] && [ "$ACTION" != "both" ]; then
    return
  fi
  if [ -z "$port" ]; then
    echo "!! serial.port is not configured in config/rig.json." >&2
    echo "   Run ./scripts/flash.sh boards, then set its stable /dev/serial/by-id path." >&2
    exit 1
  fi
  if [ ! -e "$port" ]; then
    echo "!! $port does not exist." >&2
    echo "   Plug the board in, then run: ./scripts/flash.sh boards" >&2
    echo "   Put its stable /dev/serial/by-id path in config/rig.json." >&2
    exit 1
  fi
  echo ">> uploading Mega gantry to $port"
  # An upload fails if anything else holds the port. That is almost always a
  # serial monitor or a still-running rig_console.py; close it and retry.
  arduino-cli upload -p "$port" --fqbn "$fqbn" "$sketch"
  echo ">> Mega gantry upload OK — the controller has rebooted and printed its banner"
}

flash_mega
