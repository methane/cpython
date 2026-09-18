#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec /usr/bin/python3.12 "$repo/Tools/benchmarks/pyperformance_four_way.py" "$@"
