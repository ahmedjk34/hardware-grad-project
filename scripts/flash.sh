#!/usr/bin/env bash
#
# Compile and upload the rig firmware, reading the port and board from
# config/rig.json so those numbers live in exactly one place.
#
#   ./scripts/flash.sh            compile, then upload
#   ./scripts/flash.sh compile    compile only  (this is the syntax check)
#   ./scripts/flash.sh upload     upload only
#   ./scripts/flash.sh boards     list what arduino-cli can see on USB
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/config/rig.json"
ACTION="${1:-both}"

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

FQBN="$(read_cfg board fqbn)"
SKETCH="$ROOT/$(read_cfg board sketch)"
PORT="$(read_cfg serial port)"

if [ "$ACTION" = "boards" ]; then
  arduino-cli board list
  exit 0
fi

if [ "$ACTION" = "compile" ] || [ "$ACTION" = "both" ]; then
  echo ">> compiling $SKETCH for $FQBN"
  arduino-cli compile --fqbn "$FQBN" "$SKETCH"
  echo ">> compile OK"
fi

if [ "$ACTION" = "upload" ] || [ "$ACTION" = "both" ]; then
  if [ ! -e "$PORT" ]; then
    echo "!! $PORT does not exist." >&2
    echo "   Plug the board in, then run: ./scripts/flash.sh boards" >&2
    echo "   A CH340 clone shows up as /dev/ttyUSB0 — put that in config/rig.json." >&2
    exit 1
  fi
  echo ">> uploading to $PORT"
  # An upload fails if anything else holds the port. That is almost always a
  # serial monitor or a still-running rig_console.py; close it and retry.
  arduino-cli upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"
  echo ">> upload OK — the rig has rebooted and printed its banner"
fi
