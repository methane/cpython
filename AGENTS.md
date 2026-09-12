# AI agent guidance

CPython has a [policy on the use of AI tools](https://devguide.python.org/getting-started/ai-tools/).
All use of AI tools and agents when working on or interacting with CPython
must follow it.

> [!important]
> **Primary directive**: Read the policy before making or proposing any changes.

When acting on this repository, apply the policy's core principles:

- Consider whether the change is necessary.
- Make minimal, focused changes.
- Follow existing coding style and patterns.
- Write tests that exercise the change.
- Keep backwards compatibility with prior releases in mind.

## Local JIT experiment workflow (methane/cpython fork)

These notes apply to the opt-in range-kernel experiments under `Tools/jit/`.
They do not replace the CPython contribution guidance above.  Set the checkout
root dynamically, for example `repo=$(git rev-parse --show-toplevel)`; Codex
Cloud commonly checks it out as `/workspace/cpython`, but do not depend on that
path.

### LLVM 21 and native builds

Probe before installing anything, and reuse a complete existing prefix/build:

```sh
command -v clang-21 llvm-readobj-21 llvm-objdump-21 llvm-dwarfdump-21
for tool in clang llvm-readobj llvm-objdump llvm-dwarfdump; do
    test -x /usr/lib/llvm-21/bin/$tool && /usr/lib/llvm-21/bin/$tool --version | head -1
done
```

apt.llvm.org has no LLVM 21 repository for Ubuntu 24.04 (noble).  The complete
jammy packages work on the Codex Cloud noble image.  These are the commands used
(the key may already be present as `/etc/apt/trusted.gpg.d/apt.llvm.org.asc`):

```sh
curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
    -o /usr/share/keyrings/apt.llvm.org.asc
printf '%s\n' \
  'deb [signed-by=/usr/share/keyrings/apt.llvm.org.asc] https://apt.llvm.org/jammy/ llvm-toolchain-jammy-21 main' \
  >/etc/apt/sources.list.d/llvm21-jammy.list
apt-get update
apt-get install -y clang-21 llvm-21 llvm-21-tools
```

A proxy can transiently return HTTP 403; retry rather than changing LLVM
versions. Configure and build native JIT from a separate build directory:

```sh
repo=$(git rev-parse --show-toplevel)
mkdir -p "$repo/build-jit" && cd "$repo/build-jit"
LLVM_TOOLS_INSTALL_DIR=/usr/lib/llvm-21 "$repo/configure" \
    --enable-experimental-jit=yes
LLVM_TOOLS_INSTALL_DIR=/usr/lib/llvm-21 make -j"$(nproc)"
```

LLVM 21.1.8 currently needs vectorization disabled when generating the
`_GUARD_TOS_SLICE_r11` stencil (otherwise a temporary constant-pool symbol is
unsupported). From the native build directory run:

```sh
python3.14 "$repo/Tools/jit/build.py" x86_64-pc-linux-gnu -o . -p . -f \
  --cflags='-fno-vectorize -fno-slp-vectorize' \
  --llvm-tools-install-dir=/usr/lib/llvm-21
```

Retry without this workaround after LLVM or the stencil changes, and remove it
once ordinary generation succeeds.

For cheap correctness and invariant work, use a distinct debug Tier-2
interpreter build; never describe its timings as native-JIT results:

```sh
mkdir -p "$repo/build-tier2-debug" && cd "$repo/build-tier2-debug"
"$repo/configure" --with-pydebug --enable-experimental-jit=interpreter
make -j"$(nproc)"
```

### Regeneration, tests, and measurements

After uop changes regenerate from sources, rather than editing generated files:

```sh
python3 Tools/cases_generator/tier2_generator.py
python3 Tools/cases_generator/uop_id_generator.py
python3 Tools/cases_generator/uop_metadata_generator.py
```

Run focused checks from each relevant build, including:

```sh
./python -m test test_tier3 -v
./python -m test test_tier3 test_capi.test_opt -v
PYTHON_JIT=1 ./python -m test test_tier3 test_capi.test_opt -v
```

Pin benchmarks to one CPU when available (`taskset -c 0`). Compare matched
optimized builds and identical warmup/sample/input settings. Before timing,
verify `sys._jit.is_available()` and `sys._jit.is_enabled()`, and verify the
selected executor returns nonempty `get_jit_code()`. Use `PYTHON_JIT_STRESS`
only to establish or debug executors, never in timed runs. Capture executor
counter deltas immediately around every timed sample. Keep debug/interpreter
measurements separate from native-JIT claims.

To inspect generated code, obtain `executor.get_jit_code()`, write those bytes
to a file, and disassemble with
`llvm-objdump-21 -D --triple=x86_64-pc-linux-gnu`. Locate the experimental uop
using its distinctive checked-loop sequence, then resolve indirect call-table
slots against JIT relocations and symbols with `llvm-readobj-21`/`nm` (and
`llvm-dwarfdump-21` for unwind/debug records). Do not infer register allocation
from generated C.

Before pushing every iteration run `prek run --all-files` (or all equivalent
configured hooks). In particular, Black reformats `Tools/jit/tier3_bench.py`;
run the hook locally rather than spending a CI cycle on that formatting-only
failure.

Update this section whenever a future task verifies a reusable environment,
build, generation, or debugging workaround. Do not record branch-specific
SHAs, transient benchmark values, or speculative advice here.
