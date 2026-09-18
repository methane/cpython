#!/usr/bin/env bash
# Prepare frozen free-threaded JIT builds, then run the full pyperformance suite.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$repo/Tools/benchmarks/pyperformance_compare.py" "$@"
