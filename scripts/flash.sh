#!/usr/bin/env bash
#
# Compile and upload either controller, reading both roles from config/rig.json.
#
#   ./scripts/flash.sh                    gantry: compile, then upload
#   ./scripts/flash.sh compile            gantry: compile only (back-compatible)
#   ./scripts/flash.sh feeder compile     feeder: compile only
#   ./scripts/flash.sh all compile        compile both firmware roles
#   ./scripts/flash.sh feeder upload      upload feeder to feeder.port
#   ./scripts/flash.sh boards             list what arduino-cli can see on USB
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/config/rig.json"
ROLE="gantry"
ACTION="both"
if [ "${1:-}" = "gantry" ] || [ "${1:-}" = "feeder" ] || [ "${1:-}" = "all" ]; then
  ROLE="$1"
  ACTION="${2:-both}"
elif [ -n "${1:-}" ]; then
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

flash_role() {  # flash_role <gantry|feeder>
  local role="$1" fqbn sketch port
  if [ "$role" = "gantry" ]; then
    fqbn="$(read_cfg board fqbn)"
    sketch="$ROOT/$(read_cfg board sketch)"
    port="$(read_cfg serial port)"
  else
    fqbn="$(read_cfg feeder fqbn)"
    sketch="$ROOT/$(read_cfg feeder sketch)"
    port="$(read_cfg feeder port)"
  fi

  if [ "$ACTION" = "compile" ] || [ "$ACTION" = "both" ]; then
    echo ">> compiling $role: $sketch for $fqbn"
    arduino-cli compile --fqbn "$fqbn" "$sketch"
    echo ">> $role compile OK"
  fi

  if [ "$ACTION" != "upload" ] && [ "$ACTION" != "both" ]; then
    return
  fi
  if [ -z "$port" ]; then
    echo "!! $role port is not configured in config/rig.json." >&2
    echo "   Run ./scripts/flash.sh boards, then set the role's stable /dev/serial/by-id path." >&2
    exit 1
  fi
  if [ ! -e "$port" ]; then
    echo "!! $port does not exist." >&2
    echo "   Plug the board in, then run: ./scripts/flash.sh boards" >&2
    echo "   Put its stable /dev/serial/by-id path in config/rig.json." >&2
    exit 1
  fi
  echo ">> uploading $role to $port"
  # An upload fails if anything else holds the port. That is almost always a
  # serial monitor or a still-running rig_console.py; close it and retry.
  arduino-cli upload -p "$port" --fqbn "$fqbn" "$sketch"
  echo ">> $role upload OK — the controller has rebooted and printed its banner"
}

if [ "$ROLE" = "all" ]; then
  flash_role gantry
  flash_role feeder
else
  flash_role "$ROLE"
fi
