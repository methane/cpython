#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"

cpu=${CPU:-2}
timeout=${PYPERFORMANCE_TIMEOUT:-60}
stamp=$(date -u +%Y%m%d-%H%M%S)
output=${1:-"jit-artifacts/pyperformance-rerun-$stamp"}

experiment="$repo/jit-artifacts/pyperformance-20260915"
main_python="$experiment/venv-main/bin/python"
candidate_python="$experiment/venv-candidate/bin/python"
controller_python="$experiment/controller-venv316/bin/python"
pyperf="$experiment/controller-venv316/bin/pyperf"
runner="$experiment/run_groups.py"
group_a="$experiment/benchmarks-group-a.txt"
group_b="$experiment/benchmarks-group-b.txt"

expected_main=8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407
expected_candidate=ebb86d4a70b9dda5c4f70d4d49196cc5a87986c41ced14951f73dd0eef2fb457
expected_freeze=84a767bb3e0a262b273702318c607187eea291d8c9dff075d1883fd5a87a8cbf
expected_group_a=10c4a17bfbd5e83eb6e2aaa16e871c8b4d2955a102f03ee4ab51eac13225392f
expected_group_b=24f3b21f6c271a4d9ff0d7e24c895180c1eab720570b380371cc4c3fc92c23f2
expected_runner=2b1c3671d26a79e33b5a6ab9c1cb1f0d1ff918f240f00a27a77e787c9026b11e

hash_file() {
    sha256sum "$1" | awk '{print $1}'
}

check_hash() {
    local path=$1
    local expected=$2
    local actual
    actual=$(hash_file "$path")
    if [[ $actual != "$expected" ]]; then
        echo "hash mismatch: $path" >&2
        echo "expected: $expected" >&2
        echo "actual:   $actual" >&2
        exit 2
    fi
}

freeze_hash() {
    "$1" -m pip freeze --all 2>/dev/null |
        LC_ALL=C sort |
        sha256sum |
        awk '{print $1}'
}

for path in \
    "$main_python" \
    "$candidate_python" \
    "$controller_python" \
    "$pyperf" \
    "$runner" \
    "$group_a" \
    "$group_b"
do
    if [[ ! -e $path ]]; then
        echo "missing prerequisite: $path" >&2
        exit 2
    fi
done

check_hash "$main_python" "$expected_main"
check_hash "$candidate_python" "$expected_candidate"
check_hash "$group_a" "$expected_group_a"
check_hash "$group_b" "$expected_group_b"
check_hash "$runner" "$expected_runner"

main_freeze=$(freeze_hash "$main_python")
candidate_freeze=$(freeze_hash "$candidate_python")
if [[ $main_freeze != "$expected_freeze" ||
      $candidate_freeze != "$expected_freeze" ]]; then
    echo "main/candidate benchmark dependencies do not match the prepared set" >&2
    echo "main:      $main_freeze" >&2
    echo "candidate: $candidate_freeze" >&2
    exit 2
fi

if ! taskset -c "$cpu" true; then
    echo "CPU $cpu is not available for affinity pinning" >&2
    exit 2
fi

jit_environment=(
    PYTHON_JIT=1
    PYTHON_TIER3_JIT=resident
    PYTHON_TIER2_INT_REGIONS=1
    PYTHON_TIER2_BOUNDED_INT_REGIONS=1
    PYTHON_TIER2_BUILTIN_REGIONS=1
    PYTHON_TIER2_FLOAT_FUSION=1
    PYTHON_TIER2_CALL_REGIONS=1
    PYTHON_TIER2_FLOAT_RANGE=1
)

for python in "$main_python" "$candidate_python"; do
    env "${jit_environment[@]}" "$python" -c \
        'import sys; assert sys._jit.is_available() and sys._jit.is_enabled()'
done

echo "main SHA-256:      $expected_main"
echo "candidate SHA-256: $expected_candidate"
echo "CPU:               $cpu"
echo "worker timeout:    ${timeout}s"
echo "output:            $output"
echo

if [[ ${PYPERFORMANCE_PREFLIGHT_ONLY:-0} == 1 ]]; then
    echo "preflight complete; benchmark execution was skipped"
    exit 0
fi

set +e
"$controller_python" "$runner" \
    --group-a "$group_a" \
    --group-b "$group_b" \
    --main "$main_python" \
    --candidate "$candidate_python" \
    --output-dir "$output" \
    --cpu "$cpu" \
    --timeout-seconds "$timeout" \
    --expected-main-sha256 "$expected_main" \
    --expected-candidate-sha256 "$expected_candidate"
runner_status=$?
set -e

printf '%s\n' "$runner_status" > "$output/runner-returncode.txt"

required_results=(
    "$output/a-main.json"
    "$output/a-candidate.json"
    "$output/b-main.json"
    "$output/b-candidate.json"
)
for result in "${required_results[@]}"; do
    if [[ ! -f $result ]]; then
        echo "missing result: $result" >&2
        echo "inspect $output/state.json and the four *.log files" >&2
        exit 1
    fi
done

rm -f "$output/main.json" "$output/candidate.json"
"$pyperf" convert "$output/a-main.json" \
    --add "$output/b-main.json" \
    -o "$output/main.json"
"$pyperf" convert "$output/a-candidate.json" \
    --add "$output/b-candidate.json" \
    -o "$output/candidate.json"

"$pyperf" compare_to \
    "$output/main.json" \
    "$output/candidate.json" \
    --table --table-format md > "$output/compare.md"

"$pyperf" check "$output/main.json" > "$output/check-main.txt" || true
"$pyperf" check "$output/candidate.json" \
    > "$output/check-candidate.txt" || true

echo
echo "comparison written to $output/compare.md"
echo "runner return code: $runner_status"
if (( runner_status != 0 )); then
    echo "Some benchmark specifications failed or timed out; see $output/*.log."
fi
