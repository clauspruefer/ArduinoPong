#!/bin/bash
# strip_docstrings.sh
# --------------------
# Generates src/main-plain.py from src/main.py by removing:
#   - The module-level docstring
#   - All function / method / class docstrings
#   - All comment lines (standalone and inline)
#   - Excess blank lines (collapses to at most one consecutive blank line)
#
# Usage (run from the repository root):
#   bash src/strip_docstrings.sh
#
# Output: src/main-plain.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCRIPT_DIR}/main.py"
DST="${SCRIPT_DIR}/main-plain.py"

python3 - "$SRC" "$DST" << 'PYEOF'
import ast
import io
import sys
import tokenize

src_path, dst_path = sys.argv[1], sys.argv[2]

with open(src_path) as fh:
    source = fh.read()

# ── 1. Identify every line that belongs to a docstring ────────────────────────
tree = ast.parse(source)
docstring_lines: set[int] = set()

for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            ds = node.body[0]
            docstring_lines.update(range(ds.lineno, ds.end_lineno + 1))

# ── 2. Locate every comment token (line → column where '#' starts) ────────────
comment_col: dict[int, int] = {}
for tok in tokenize.generate_tokens(io.StringIO(source).readline):
    if tok.type == tokenize.COMMENT:
        comment_col[tok.start[0]] = tok.start[1]

# ── 3. Process line by line ───────────────────────────────────────────────────
raw_lines = source.splitlines(keepends=True)
out: list[str] = []

for lineno, text in enumerate(raw_lines, start=1):
    if lineno in docstring_lines:
        continue                            # drop docstring line

    if lineno in comment_col:
        col = comment_col[lineno]
        code_part = text[:col].rstrip()
        if code_part:                       # inline comment → keep code only
            out.append(code_part + "\n")
        # else: comment-only line → drop entirely
    else:
        out.append(text)

# ── 4. Collapse consecutive blank lines to at most one ────────────────────────
result: list[str] = []
prev_blank = False
for line in out:
    blank = line.strip() == ""
    if blank:
        if not prev_blank:
            result.append(line)
        prev_blank = True
    else:
        result.append(line)
        prev_blank = False

# strip leading blank lines
first = next((i for i, ln in enumerate(result) if ln.strip()), len(result))
result = result[first:]

# normalise to single trailing newline
last = next((i for i, ln in enumerate(reversed(result)) if ln.strip()), 0)
result = result[:len(result) - last] if last else result
result.append("\n")

with open(dst_path, "w") as fh:
    fh.writelines(result)

print(f"[strip_docstrings] {src_path} → {dst_path}  "
      f"({len(raw_lines)} lines → {len(result)} lines)")
PYEOF
