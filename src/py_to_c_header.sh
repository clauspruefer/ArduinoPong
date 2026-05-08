#!/bin/bash
# py_to_c_header.sh
# ------------------
# Converts src/main-plain.py into a C header file
# src/arduino-main-plain-ccode.h, embedding the Python source as a C
# string literal that can be included in a MicroPython embedded build.
#
# Usage (run from the repository root):
#   bash src/py_to_c_header.sh
#
# Output: src/arduino-main-plain-ccode.h
#
# The generated header defines a single symbol:
#   static const char *arduino_pong_code = "...\n" "...\n" ... ;
# Each line of the Python source becomes one quoted string fragment,
# with backslashes and double-quotes escaped and a literal \n appended.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCRIPT_DIR}/main-plain.py"
DST="${SCRIPT_DIR}/arduino-main-plain-ccode.h"

python3 - "$SRC" "$DST" << 'PYEOF'
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]

with open(src_path) as fh:
    lines = fh.read().splitlines()

guard = "ARDUINO_MAIN_PLAIN_CCODE_H"

out = []
out.append(f"#ifndef {guard}")
out.append(f"#define {guard}")
out.append("")
out.append("static const char *arduino_pong_code =")

for i, line in enumerate(lines):
    escaped = line.replace("\\", "\\\\").replace('"', '\\"')
    suffix = ";" if i == len(lines) - 1 else ""
    out.append(f'    "{escaped}\\n"{suffix}')
out.append("")
out.append(f"#endif")

with open(dst_path, "w") as fh:
    fh.write("\n".join(out) + "\n")

print(f"[py_to_c_header] {src_path} → {dst_path}  ({len(lines)} lines)")
PYEOF
