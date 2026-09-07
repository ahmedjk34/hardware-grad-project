#!/usr/bin/env bash
# Stub-Arduino g++ syntax check for an .ino sketch.
#
# Proves the sketch PARSES and TYPE-CHECKS against a minimal Arduino-core stub.
# It does NOT build for AVR and does NOT prove behaviour — every path touching
# motion / limits / Z still has to be flashed and watched on the physical rig
# (AGENTS.md: "A clean compile is not a test").
#
# Usage:  arduino/tools/pcheck/check.sh arduino/build_test_v1/build_test_v1.ino
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
INO="${1:?usage: check.sh path/to/sketch.ino}"
[ -f "$INO" ] || { echo "no such file: $INO" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
UNIT="$WORK/unit.cpp"

# Arduino generates a forward prototype for every free function so definition
# order does not matter. g++ does not, so synthesise them: any line that starts
# in column 0 with `<type> <name>(...args...)` and whose parameter list closes
# on that same line, followed by `{` (optionally on the next line), is a
# definition — emit `<the same signature>;`.
python3 - "$INO" > "$WORK/protos.h" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
# strip block and line comments so a commented-out signature is not prototyped
text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
text = re.sub(r"//[^\n]*", "", text)
pat = re.compile(
    r"^((?:const\s+|static\s+|inline\s+|unsigned\s+|signed\s+)*"
    r"[A-Za-z_][\w:]*)"                # return type (last word)
    r"\s*(\**)\s*"                     # pointer stars, either side of the space
    r"([A-Za-z_]\w*)\s*"              # function name
    r"\(([^;{}]*)\)\s*\{",           # (args) {
    re.M)
seen = set()
out = []
for m in pat.finditer(text):
    ret, stars, name, args = (m.group(1).strip(), m.group(2),
                              m.group(3), m.group(4).strip())
    if name in ("if", "for", "while", "switch", "return", "sizeof", "do"):
        continue
    if name in seen:
        continue
    seen.add(name)
    out.append(f"{ret} {stars}{name}({args});")
print("\n".join(out))
PY

{
  echo '#include "Arduino.h"'
  echo '#include "Servo.h"'
  echo '#include "Stepper.h"'
  echo '#include "protos.h"'
  echo '#line 1 "'"$INO"'"'
  cat "$INO"
} > "$UNIT"

# -fpermissive: on a 64-bit host `(int)&ptr` in freeRam() loses precision;
# harmless for a syntax check (AVR int and pointers are both 16-bit).
g++ -std=gnu++17 -fsyntax-only -fpermissive -Wno-narrowing \
    -I"$HERE" -I"$WORK" "$UNIT"
echo "SYNTAX OK (stub Arduino) — $INO"
echo "UNFLASHED / UNVERIFIED ON HARDWARE. Flash and watch the rig before trusting motion."
