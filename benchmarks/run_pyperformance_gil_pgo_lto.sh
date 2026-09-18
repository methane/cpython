#!/usr/bin/env bash
# Compare committed main and HEAD with the GIL, JIT, PGO and full LTO enabled.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec /usr/bin/python3.12 "$repo/Tools/benchmarks/pyperformance_compare.py" \
    --build-profile gil-pgo-lto "$@"
