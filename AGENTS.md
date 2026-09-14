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

The repository preflight automates that complete-prefix check and persists the
selection.  Run it after checking out the task revision; pass `--install` only
when no complete cached prefix exists and installing signed apt packages is
permitted:

```sh
Tools/jit/ensure_llvm21.sh
# If the preflight reports that every candidate is incomplete:
Tools/jit/ensure_llvm21.sh --install
. ./.llvm21-env
```

The preflight executes every required tool and accepts only LLVM 21 version
output.  An explicitly supplied `LLVM_TOOLS_INSTALL_DIR` is authoritative: an
invalid explicit prefix fails rather than silently selecting a different
installation.  `.llvm21-env` is replaced atomically only after all four tools
pass validation.  Its subprocess fixtures can be run without network access:

```sh
python -m test test_tools.test_ensure_llvm21 -v
```

Dependency setup may run before a task branch (and therefore this script) is
checked out.  In that case use the self-contained probe/install recipe below
during setup, then run the script after checkout to validate and persist the
selected prefix.  A successful dependency preflight does not validate cached
stencils or executables; always rebuild source-dependent artifacts for the
selected revision.

Select one complete prefix and persist it for later agent shells:

```sh
for prefix in "${LLVM_TOOLS_INSTALL_DIR:-}" /opt/llvm-21.1.8 /usr/lib/llvm-21; do
    test -n "$prefix" || continue
    test -x "$prefix/bin/clang" && test -x "$prefix/bin/llvm-readobj" && \
        test -x "$prefix/bin/llvm-objdump" && \
        test -x "$prefix/bin/llvm-dwarfdump" || continue
    printf 'export LLVM_TOOLS_INSTALL_DIR=%q\n' "$prefix" >.llvm21-env
    break
done
test -s .llvm21-env && . ./.llvm21-env
```

The environment file is repository-local and untracked. Source it explicitly
in later setup/agent phases; exports made by a setup script do not persist into
an agent's shell.

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

If the package repository remains blocked, the official LLVM 21.1.8 x86-64
release archive is a complete fallback. Downloading it is large (about 2 GB):

```sh
prefix=/opt/llvm-21.1.8
mkdir -p "$prefix"
curl -fL --retry 4 --retry-delay 3 \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/LLVM-21.1.8-Linux-X64.tar.xz \
  | tar -xJ --strip-components=1 -C "$prefix"
for tool in clang llvm-readobj llvm-objdump llvm-dwarfdump; do
    "$prefix/bin/$tool" --version | head -1
done
export LLVM_TOOLS_INSTALL_DIR="$prefix"
```

Use this recipe only after probing existing installations as above.

A proxy can transiently return HTTP 403; retry rather than changing LLVM
versions. Configure and build native JIT from a separate build directory:

An existing in-source build must be cleaned before an out-of-tree build can
pass `check-clean-src`.
Run `make distclean` before starting any builds nested under the checkout:
its recursive cleanup also removes their object files and shared libraries.
An independent source snapshot is another way to preserve an existing build.

```sh
repo=$(git rev-parse --show-toplevel)
mkdir -p "$repo/build-jit" && cd "$repo/build-jit"
test -n "${LLVM_TOOLS_INSTALL_DIR:-}" || . "$repo/.llvm21-env"
LLVM_TOOLS_INSTALL_DIR="$LLVM_TOOLS_INSTALL_DIR" "$repo/configure" \
    --enable-experimental-jit=yes
LLVM_TOOLS_INSTALL_DIR="$LLVM_TOOLS_INSTALL_DIR" make -j"$(nproc)"
```

LLVM 21.1.8 currently needs vectorization disabled when generating the
`_GUARD_TOS_SLICE_r11` stencil (otherwise a temporary constant-pool symbol is
unsupported). From the native build directory run:

```sh
python3.14 "$repo/Tools/jit/build.py" x86_64-pc-linux-gnu -o . -p . -f \
  --cflags='-fno-vectorize -fno-slp-vectorize' \
  --llvm-tools-install-dir="$LLVM_TOOLS_INSTALL_DIR"
LLVM_TOOLS_INSTALL_DIR="$LLVM_TOOLS_INSTALL_DIR" make -j"$(nproc)"
```

Retry without this workaround after LLVM or the stencil changes, and remove it
once ordinary generation succeeds. Reusing a cached LLVM prefix is safe, but
rebuild source-dependent stencils and executables after checking out a new PR
revision. Never update `.jit-stamp` unless stencil generation completed
successfully and its prefix and flags were recorded.

For cheap correctness and invariant work, use a distinct debug Tier-2
interpreter build; never describe its timings as native-JIT results:

```sh
mkdir -p "$repo/build-tier2-debug" && cd "$repo/build-tier2-debug"
"$repo/configure" --with-pydebug --enable-experimental-jit=interpreter
make -j"$(nproc)"
```

A completed Tier-2 interpreter can also run the stencil generator. If the
configured bootstrap Python stalls in LLVM subprocess handling, the verified
local alternative is `make PYTHON_FOR_REGEN="$repo/build-tier2-debug/python"`.
Keep that executable fixed while it is being used as a build tool.

### Regeneration, tests, and measurements

After uop changes regenerate from sources, rather than editing generated files:

```sh
python3 Tools/cases_generator/tier2_generator.py
python3 Tools/cases_generator/uop_id_generator.py
python3 Tools/cases_generator/uop_metadata_generator.py
```

Changes to optimizer definitions in `Python/optimizer_bytecodes.c` use a
separate generated output.  Regenerate it with
`python3 Tools/cases_generator/optimizer_generator.py` (or the configured
build's `regen-optimizer-cases` target); `tier2_generator.py` only regenerates
executor cases.

When changing a bytecode macro's uop sequence, also regenerate the opcode
expansion metadata and trace recorder tables:

```sh
python3 Tools/cases_generator/opcode_metadata_generator.py
python3 Tools/cases_generator/py_metadata_generator.py
python3 Tools/cases_generator/record_function_generator.py \
    -o Python/record_functions.c.h Python/bytecodes.c
```

Use the explicit recorder output path above: the generator's default filename
differs from the header included by the build. Keep the opcode expansion and
record consumer slot maps in sync, and rebuild `Python/optimizer.o` after
recorder changes. The configured `regen-record-functions` target also supplies
the correct output path.

Replicated uops need contiguous, numerically ordered IDs, including suffixes
above nine. Check the generic base stencil as well as the replicas: stencil
generation compiles both. With LLVM 21 on x86-64, a runtime selector in the
base can become a jump table whose targets the assembly optimizer drops,
leaving undefined `.LBB` symbols at assembly time. For pure integer comparison
selectors, bitwise boolean composition avoids that table while constant
replicas still fold to one comparison. Preserve the original and processed
assembly to diagnose this case, and validate every stencil before rebuilding.

Fused floating-point uops must preserve Python's operation-by-operation
binary64 rounding even when an embedding compiler enables contraction.  Use an
explicit C evaluation boundary at the fused arithmetic and inspect the
generated executor/native assembly for separate multiply and update instructions;
the cancellation case `-1.0 + (1.0 + 2**-27) * (1.0 - 2**-27)` is a reusable
regression witness.

A header-only change used by stencils (for example, moving fields in
`Include/internal/pycore_optimizer.h`) can be missed by both `JIT_DEPS` and
the stencil input digest when `Python/executor_cases.c.h` is unchanged.
After such a change, run the configured `Tools/jit/build.py` command with
`--force`, keeping its target triple, output/config directories, LLVM prefix,
and C flags, then relink the native build. Check native counters/offsets as
well as Python results: a successful ordinary build can still contain stale
struct offsets. Do not manually advance `.jit-stamp` to bypass regeneration.

Separate regrtest invocations sharing a build directory must run sequentially
or use distinct `--tempdir` directories. Execution tools can use separate PID
namespaces with the same worker PID while sharing the filesystem; the default
worker directory can then collide and be removed by another test process.

For call-region fixtures that must specialize, create functions through `def`
or `exec` so `MAKE_FUNCTION` assigns a usable function version. Functions
created directly with `types.FunctionType` currently retain an unset version
and do not specialize CALL. To test a callee's RESUME countdown, call it from
C, for example through `map`: a hot Python caller can inline the callee and
avoid executing its Tier 1 RESUME counter.

A function version is not a function or globals identity: `MAKE_FUNCTION`
copies the code version, so different functions sharing a code object can
share a valid version. For namespace-sensitive call transformations, also
check the actual callee globals. Regression fixtures can execute a compiled
`def` whose nested code constant is replaced with the warmed callee's code
in a second namespace. This exercises version sharing; a direct
`types.FunctionType` clone alone does not.

Run focused checks from each relevant build, including:

```sh
./python -m test test_tier3 -v
./python -m test test_tier3 test_capi.test_opt -v
PYTHON_JIT=1 ./python -m test test_tier3 test_capi.test_opt -v
```

Pin benchmarks to one CPU when available (choose one from
`taskset -pc $$`, rather than assuming CPU 0 is allowed). Compare matched
optimized builds and identical warmup/sample/input settings. Before timing,
verify `sys._jit.is_available()` and `sys._jit.is_enabled()`, and verify the
selected executor returns nonempty `get_jit_code()`. Use `PYTHON_JIT_STRESS`
only to establish or debug executors, never in timed runs. Capture executor
counter deltas immediately around every timed sample. Keep debug/interpreter
measurements separate from native-JIT claims.

Pyperf filters worker environments by default. Pass only the experiment
variables required by the run, and verify them through the same worker launch
path before interpreting workload coverage:

```sh
PYTHONPATH=Tools/jit:$PYTHONPATH PYTHON_JIT=1 PYTHON_TIER3_JIT=resident \
  build-jit/python Tools/jit/pyperf_tier3_worker_probe.py \
  --inherit-environ=PYTHON_JIT,PYTHON_TIER3_JIT --fast --min-time=0.1
```

Use that same `--inherit-environ` allowlist for benchmark entrypoints. Add dump
or stress variables only to separate diagnostic runs, never timings.

To inspect generated code, obtain `executor.get_jit_code()` and write those raw
bytes to a file. LLVM's objdump rejects a headerless raw binary, so disassemble
it with `objdump -D -b binary -m i386:x86-64`; use `llvm-objdump-21` for object
files produced during stencil generation. Locate the experimental uop
using its distinctive checked-loop sequence, then resolve indirect call-table
slots against JIT relocations and symbols with `llvm-readobj-21`/`nm` (and
`llvm-dwarfdump-21` for unwind/debug records). Do not infer register allocation
from generated C.

Code-attached executors alone can miss hot side traces. For coverage probes,
follow executor objects returned by `gc.get_referents(executor)` recursively,
deduplicating by identity. Their traversal visits outgoing executor links;
do not assign a side trace's Python function from the root used to reach it.
Capture the same executor set immediately before and after each measured call.

Before pushing every iteration run `prek run --all-files` (or all equivalent
configured hooks). In particular, Black reformats `Tools/jit/tier3_bench.py`;
run the hook locally rather than spending a CI cycle on that formatting-only
failure.

If `prek` is absent, the verified repository-local setup method is
`python3 -m pip install --user prek`; invoke `$HOME/.local/bin/prek` directly
when the user-site binary directory is not on `PATH`.

Native evidence may be collected from a clean local implementation commit
before it is published. Record both `git rev-parse HEAD` and
`git rev-parse HEAD^{tree}` (plus tracked dirty state); the full source-tree
hash is the practical identity used to reconcile that build with a later
publication commit. A remote or pre-measurement push is not required.

Update this section whenever a future task verifies a reusable environment,
build, generation, or debugging workaround. Do not record branch-specific
SHAs, transient benchmark values, or speculative advice here.
