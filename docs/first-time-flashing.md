# First-time flashing

The production controller is an Arduino Mega 2560 running
`arduino/build_test_v1/build_test_v1.ino`. The Raspberry Pi communicates with
that one board over USB serial.

## 1. Install Arduino CLI and the AVR core

Install `arduino-cli`, then run:

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr
```

## 2. Identify and configure the Mega

Plug in the Mega and list boards:

```bash
./scripts/flash.sh boards
```

Put its stable `/dev/serial/by-id/...` path in `config/rig.json` at
`serial.port`. Keep the board and sketch in the same file under `board.fqbn`
and `board.sketch`; the flash script reads all three values rather than using a
literal port.

## 3. Compile, then upload

```bash
./scripts/flash.sh compile
./scripts/flash.sh upload
```

With no argument, `./scripts/flash.sh` compiles and uploads. Compilation is
safe to run without hardware; uploading requires the configured board and may
reset it.

The Mega and `config/rig.json` must agree on serial baud and paired grid
geometry. Run `python3 python/tests/test_grid.py` after a firmware/config edit.

## 4. Start the service

Start the FastAPI service only after closing Arduino Serial Monitor and other
tools that own the port. Production startup requires the Mega and camera; mock
mode simulates both without moving hardware. A build still requires the
operator to stage one block at `[0,0]`, confirm staging, and complete the
firmware-gated `M` then `C` pickup handshake.

