# Tier-3 range-kernel results

## Dataflow verifier and two-recurrence native follow-up

The native executable used the tracked sources at local implementation commit
`85df248cd897d84702e91b5ba0218fb2b76c0eee`, tree
`9d5a6cd6344ff055489ec008e00d255be4ee0d90`. The build was an out-of-source,
GCC 13.3.0 `-DNDEBUG -O3` build configured with
`--enable-experimental-jit=yes`. Stencils used apt.llvm.org's complete Ubuntu
LLVM 21.1.8 prefix at `/usr/lib/llvm-21` and
`-fno-vectorize -fno-slp-vectorize`. The initial ordinary stencil generation
reproduced `Undefined temporary symbol .LCPI0_0`; regeneration with those
documented flags succeeded. The local `.llvm21-env`, build directories, and
logs were not committed. The benchmark JSON records the executable's version,
configure arguments, callable, executor identity, every sample and counter
delta, result, and nonempty 4,096-byte native-code size.

All timings below are medians of five samples pinned to permitted CPU 0, with
500 warmups and no `PYTHON_JIT_STRESS`. Samples used 2,000 calls at `n=1000`
and 20 calls at `n=100000`. “Off” is the same native build with the feature
unset; “resident” is `PYTHON_TIER3_JIT=resident`.

| workload | n | initial | off ns | resident ns | matched speedup |
|---|---:|---:|---:|---:|---:|
| sum | 1,000 | 0 | 11,412.5 | 944.7 | 12.08x |
| sum | 1,000 | 2**40 | 27,587.7 | 991.5 | 27.82x |
| sum | 100,000 | 0 | 2,575,237.4 | 82,210.8 | 31.32x |
| sum | 100,000 | 2**40 | 3,328,197.8 | 82,532.8 | 40.33x |
| squares | 1,000 | 0 | 15,316.1 | 1,195.3 | 12.81x |
| squares | 1,000 | 2**40 | 35,244.8 | 1,198.2 | 29.41x |
| squares | 100,000 | 0 | 5,293,688.8 | 103,549.9 | 51.12x |
| squares | 100,000 | 2**40 | 5,008,392.2 | 103,429.2 | 48.42x |

Every resident short-loop row recorded 10,000 entries, 9,980,000 iterations
and polls, and 10,000 normal materializations. Every long-loop row recorded
100 entries, 9,999,800 iterations and polls, and 100 materializations. All
pending, deopt, and overflow counters were zero in the timed matrix. Off rows
explicitly report “not entered” and zero Tier-3 deltas rather than treating
absence as Tier-3 execution. Results matched the separately calculated Python
answers in every row. Raw results and the graph/assembly artifacts are under
`tier3_data/native_followup/`.

The real squares graph binds accumulator node 2 and induction node 1, then
selects result node 4 through checked-multiply node 3. Its compact facts show
which values are established by retained guards and which by checked
operations. The native hot backedge is:

```asm
2b4: lea    (%rcx,%r14,1),%r12
2b8: imul   %r12,%r12
2bc: jo     0x344
2c2: add    %r9,%r12
2c5: jo     0x344
2d5: mov    0x18(%r9),%r9       # per-logical-backedge eval-breaker poll
2d9: inc    %r14
2dc: cmp    %r10,%r9            # instrumentation version
2e3: jne    0x2f6
2e5: mov    %r11,%r13
2e8: inc    %r11
2eb: inc    %rax
2ee: mov    %r12,%r9            # accumulator register move for reconstruction
2f1: test   %dil,%dil           # executor validity
2f4: jne    0x2b4
```

There is no call, PyLong allocation, node interpretation, budget lookup, or
statistics write on that loop backedge. Entry conversion, exit allocation,
and counter publication remain outside it. Materialization OOM is still not
runtime-verified: transactional writes and distinct exits do not prove that
the exception location and reconstructed Python snapshot agree, so this
experiment is not production-ready on that basis.

## Native helper/direct-stencil comparison

Tested commit: `d9399c9e96bbeb0398fff4dc4adacb6a6a8df942` (x86-64
Linux).  This commit contains the direct-stencil implementation and evaluates
the runtime budget once per chunk.  Raw per-sample JSON is consolidated in
`tier3_data/native_direct_matrix_d9399c9.json`.

### LLVM 21 build

The official 21.1.0 release archive was downloaded successfully, but that
particular `LLVM-21.1.0-Linux-X64.tar.xz` contains libraries and headers without
a `bin/` directory.  The documented apt installer rejected Ubuntu noble because
apt.llvm.org does not publish a noble LLVM 21 repository.  Installing the
complete LLVM 21.1.8 tool set from apt.llvm.org's jammy repository provided
`clang`, `llvm-readobj`, `llvm-objdump`, and `llvm-dwarfdump`:

```sh
curl -fsSL https://apt.llvm.org/llvm.sh -o /tmp/llvm.sh
/tmp/llvm.sh 21  # rejected noble: distribution not supported
# Add apt.llvm.org/jammy llvm-toolchain-jammy-21, then:
apt-get update
apt-get install -y clang-21 llvm-21 llvm-21-tools
mkdir /workspace/build-jit21 && cd /workspace/build-jit21
LLVM_TOOLS_INSTALL_DIR=/usr/lib/llvm-21 \
    /workspace/cpython/configure --enable-experimental-jit=yes
```

LLVM 21.1.8 emits a local constant-pool reference that the stencil assembly
optimizer drops for `_GUARD_TOS_SLICE_r11`.  Building stencils with vectorization
disabled avoids that unrelated LLVM-version difference; the interpreter remains
a normal `-DNDEBUG -O3` build:

```sh
python3.14 /workspace/cpython/Tools/jit/build.py x86_64-pc-linux-gnu \
  -o . -p . -f --cflags='-fno-vectorize -fno-slp-vectorize' \
  --llvm-tools-install-dir=/usr/lib/llvm-21
make -j8
```

`sys._jit.is_available()` and `sys._jit.is_enabled()` both returned `True`, and
all three modes' selected executors returned 4096 bytes from `get_jit_code()`.
No timed run used `PYTHON_JIT_STRESS`.  Every run was pinned to CPU 0, used
1,000 warmups and seven samples, and used 5,000 calls/sample for `n=1000` or 50
calls/sample for `n=100000`.

### Decisive budget sweep (initial zero)

Times are median nanoseconds per Python call.  `off/helper` and `off/direct` are
speedups over the current native JIT; `helper/direct` greater than one means the
direct stencil is faster.  Helper and direct counter deltas had identical
coverage at every matched point.

| n | budget | off ns | helper ns | direct ns | off/helper | off/direct | helper/direct | coverage |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 1 | 11,336.6 | 14,446.9 | 15,046.1 | 0.78x | 0.75x | 0.960x | 49.90% |
| 1,000 | 8 | 11,336.6 | 3,604.9 | 3,645.8 | 3.14x | 3.11x | 0.989x | 88.80% |
| 1,000 | 64 | 11,336.6 | 1,071.5 | 961.5 | 10.58x | 11.79x | 1.114x | 98.30% |
| 1,000 | 512 | 11,336.6 | 706.6 | 608.5 | 16.04x | 18.63x | 1.161x | 99.70% |
| 1,000 | 4,096 | 11,336.6 | 667.4 | 561.6 | 16.99x | 20.19x | 1.188x | 99.80% |
| 100,000 | 1 | 2,575,754.0 | 2,563,439.7 | 2,675,255.6 | 1.00x | 0.96x | 0.958x | 50.00% |
| 100,000 | 8 | 2,575,754.0 | 619,053.1 | 636,010.1 | 4.16x | 4.05x | 0.973x | 88.89% |
| 100,000 | 64 | 2,575,754.0 | 130,715.6 | 119,598.7 | 19.71x | 21.54x | 1.093x | 98.46% |
| 100,000 | 512 | 2,575,754.0 | 67,060.3 | 56,995.8 | 38.41x | 45.19x | 1.177x | 99.80% |
| 100,000 | 4,096 | 2,575,754.0 | 57,036.6 | 48,853.5 | 45.16x | 52.72x | 1.168x | 99.97% |

At budget 64, initial `-7` gave helper/direct ratios of 1.076x (`n=1000`)
and 1.085x (`n=100000`); initial `2**40` gave 1.055x and 1.082x.  Direct is
therefore not materially better at the diagnostic budgets 1 and 8, and is only
about 8--19% better once boundary costs are amortized.  The large-budget direct
result is the measured floor for this Python integration; no standalone C-loop
number is claimed because eliminating Python call/result handling would make it
an unmatched workload.

For the `n=100000`, budget-64 timed interval each mode recorded 538,650 chunk
entries, 34,461,000 chunk iterations, 538,650 budget exits, and zero overflow
exits.  At budget 4096 those deltas were 8,750 entries, 34,990,900 iterations,
8,750 budget exits, and zero overflow exits.  These are measurement-only deltas,
not cumulative warmup counters.

### Generated direct machine code

The direct chunk occupies approximately offsets `0xf5..0x486` (913 bytes),
including guards, conversion, frame publication, materialization, reference
updates, counters, and all exits.  `_PyTier3_GetBudget()` is an actual indirect
runtime call once per chunk entry (at `0x234`); storing it in a local prevents
`Py_MIN` from evaluating the call twice.  Entry publishes the stack pointer and
calls `PyLong_AsLongLongAndOverflow`; a rare ambiguous `-1` result calls
`PyErr_Occurred`.  Successful exit calls `PyLong_FromLongLong` and
`PyLong_FromLong`, followed only by conditional deallocation calls.

The checked loop itself is about 20 bytes:

```text
2d7: cmp  %rcx,%r8             # completed limit
2da: je   326                  # materialize successful chunk
2dc: lea  (%r11,%rdx),%rdi     # current range value
2e0: dec  %rcx                 # completed count (negative)
2e3: inc  %rdx                 # next-offset
2e6: add  %rdi,%rax            # total += current
2e9: jno  2d2                  # loop; overflow exits at 2eb
```

`total` remains in `%rax`, the range base/current calculation uses `%r11` and
`%rdi`, the next offset uses `%rdx`, the completed count uses `%rcx`, and the
limit uses `%r8`.  There are no calls or reloads in this loop.  There is one
store of the running total to `0x68(%rsp)` on the taken backedge, so allocation
exit can recover it; other exit values (`next`, `remaining`, and last induction)
are computed around the loop and stored on the native stack.  Thus allocation
is good but not wholly spill-free, and boundary code is much larger than the
integer loop.

### Materialization-failure boundary

Both modes allocate the new accumulator and induction objects before changing
locals or the range iterator.  Failure of either allocation therefore restores
the exact chunk-entry iterator and locals; no logical iteration is committed.
The uop stack effect is unchanged (`iter, index -- iter, index`) and generated
error handling flushes that same pre-`_ITER_NEXT_RANGE` stack state.  The target
is the matched addition's bytecode location so exception-table selection and
traceback attribution correspond to the protected loop body.  A handler or
`finally` observes the pre-chunk induction local and iterator, consistently with
transactional zero progress, rather than a partially completed chunk.

This pairing remains source-reviewed, not runtime-verified.  CPython's available
allocation-failure support is process/global and cannot deterministically target
either of these two allocations after executor entry without failing unrelated
JIT/interpreter allocations.  Adding a production hook solely for this
experiment would be disproportionate.  The limitation applies equally to
helper and direct modes and must be resolved before treating either mode as
production-ready.

### Cost interpretation and next experiment

Direct's clean register-resident arithmetic loop establishes that copy-and-patch
can emit the desired unboxed checked loop.  Nevertheless, direct and helper are
nearly identical at budgets 1 and 8, and direct improves only 8--19% at larger
budgets.  This separates the costs: `PyLong_AsLongLongAndOverflow`, the runtime
budget call, executor stack/frame synchronization, two PyLong materializations,
and the deliberately ordinary iteration remain on every boundary in both
modes; only the tiny checked loop moved across the helper-call boundary.

The next experiment should keep copy-and-patch stencil generation and enlarge
region recognition/lowering so unboxed accumulator and induction state remains
live across the loop backedge and multiple periodic-check-safe regions.  A small
value representation may feed stencils, but these measurements do not justify
replacing the stencil backend with a separate native backend.  Quantitatively,
the next design should target the remaining ~15,000 ns (budget 1) versus ~562 ns
(large-budget floor) for `n=1000`, and should require at least a 2x improvement
at budget 1/8 before broadening semantics.

## Historical helper-only native results

The native measurements below were made from implementation commit
`f895c84c1b514caea65fa25bde0b0d113497c552` on x86-64 Linux. This commit is
based on `73fd8fc22138a1a2f03d62835e80497a365d4a2d`, which recorded the earlier
debug Tier-2 diagnostics. Raw JSON, including every sample and its counter
delta, is in `tier3_data/native/`.

## Native-JIT build and verification

The apt.llvm.org installer was attempted first, as recommended by the JIT
README, but both `wget` and `curl` received HTTP errors. The supported official
LLVM 21.1.0 binary distribution was then installed and used as an explicit
prefix:

```sh
curl -L https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.0/LLVM-21.1.0-Linux-X64.tar.xz |
    tar -xJ --strip-components=1 -C /opt/llvm-21
mkdir /workspace/build-jit21 && cd /workspace/build-jit21
LLVM_TOOLS_INSTALL_DIR=/opt/llvm-21 \
    /workspace/cpython/configure --enable-experimental-jit=yes
LLVM_TOOLS_INSTALL_DIR=/opt/llvm-21 make -j8
```

The build used GCC 13.3.0 with `-DNDEBUG -O3`; all measurements pinned the
process to CPU 0 and set `PYTHON_JIT=1`. Both `sys._jit.is_available()` and
`sys._jit.is_enabled()` returned true. For both feature-off and feature-on
runs, the selected range-loop executor returned 4096 bytes from
`get_jit_code()`. No performance run used `PYTHON_JIT_STRESS`.

## Matched native-JIT comparison

Each row used 3,000 warmups and nine samples. The 1,000-element cases used
20,000 calls per sample and the 100,000-element cases used 200. Feature-on used
`PYTHON_TIER3_JIT=1 PYTHON_TIER3_BUDGET=64`; otherwise the environment and
workload were identical.

| n | initial | off ns/call | on ns/call | speedup | kernel fraction |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 0 | 11,458.8 | 1,078.2 | 10.63x | 98.30% |
| 1,000 | -7 | 11,314.4 | 1,109.0 | 10.20x | 98.30% |
| 1,000 | 2**40 | 27,866.9 | 1,449.0 | 19.23x | 98.30% |
| 100,000 | 0 | 2,565,170.8 | 132,515.0 | 19.36x | 98.46% |
| 100,000 | -7 | 2,585,611.4 | 133,551.3 | 19.36x | 98.46% |
| 100,000 | 2**40 | 3,308,079.3 | 148,580.6 | 22.26x | 98.46% |

For example, the `n=100000`, initial-zero timed interval recorded 2,770,200
helper entries, 177,228,000 kernel iterations, 2,770,200 budget exits, and no
overflow exits. Feature-off retained a native executor but recorded no Tier-3
entries. The large speedups therefore compare the normal native JIT directly
with the same native JIT plus the range chunk; they are not comparisons against
the debug Tier-2 interpreter.

## Budget cost model

These native runs used initial zero, 3,000 warmups, seven samples, and 10,000
calls/sample for `n=1000` or 100 calls/sample for `n=100000`.

| n | budget | ns/call | helper entries | kernel iterations | budget exits | overflow exits | fraction |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 1 | 14,084.5 | 34,930,000 | 34,930,000 | 34,930,000 | 0 | 49.90% |
| 1,000 | 8 | 3,602.7 | 7,770,000 | 62,160,000 | 7,770,000 | 0 | 88.80% |
| 1,000 | 64 | 1,073.3 | 1,120,000 | 68,810,000 | 1,120,000 | 0 | 98.30% |
| 1,000 | 512 | 720.7 | 140,000 | 69,790,000 | 140,000 | 0 | 99.70% |
| 1,000 | 4,096 | 678.2 | 70,000 | 69,860,000 | 70,000 | 0 | 99.80% |
| 100,000 | 1 | 2,618,368.8 | 34,999,300 | 34,999,300 | 34,999,300 | 0 | 50.00% |
| 100,000 | 8 | 620,744.6 | 7,777,700 | 62,221,600 | 7,777,700 | 0 | 88.89% |
| 100,000 | 64 | 131,811.0 | 1,077,300 | 68,922,000 | 1,077,300 | 0 | 98.46% |
| 100,000 | 512 | 67,050.0 | 136,500 | 69,862,800 | 136,500 | 0 | 99.80% |
| 100,000 | 4,096 | 56,845.0 | 17,500 | 69,981,800 | 17,500 | 0 | 99.97% |

Budget 1 is slightly slower than feature-off and processes only one kernel item
for each ordinary item. Performance improves sharply as helper entries and
state materializations are amortized. The main knee is between 64 and 512;
4096 remains measurably better on the large loop, but these data do not change
the default. The focused signal test separately confirms that budget 4096
returns through the normal periodic-check path promptly.

## Native executor inspection

The generated executor's indirect-call table entry at offset `0x598` resolved,
after accounting for ASLR, to the executable's `_PyTier3_RunRange` symbol. A
representative annotated excerpt is:

```text
  f5: sub    $0x18,%rsp          # save native-JIT temporaries
 101: mov    %r15,(%rsp)         # preserve cached stack pointer
 105: movabs $0x12,%r8           # packed sum/induction local indexes
 11a: mov    %rdi,(%r14)         # materialize iterator stack input
 122: mov    %rsi,0x8(%r14)      # materialize index/null input
 126: lea    0x10(%r14),%r15
 12a: mov    %r15,0x40(%r13)     # publish frame stack pointer
 12e: mov    %r12,%rdi           # executor
 131: mov    %r13,%rsi           # frame
 134: mov    %rbx,%rdx           # iterator stack reference
 137: call   *0x45b(%rip)        # table[0x598] = _PyTier3_RunRange
 13d: test   %eax,%eax           # error/fall-through handling
```

Thus every helper entry performs stack-cache materialization, publishes frame
state, makes a C call, and restores native temporaries. The counter sweep shows
approximately 16 helper entries per Python call at budget 64 for `n=1000`, and
1,539 for `n=100000`; this setup dominates small budgets.

## Overflow and responsiveness

The focused native-JIT tests call a function returning `(total, item)` with
`initial=2**63-10` and `n=100`. The observed result is exactly
`(2**63-10 + sum(range(100)), 99)`, while counter snapshots around the call
show both a positive kernel-iteration delta and a positive overflow-exit delta
for budgets that reach the boundary. This proves that a safe prefix is
committed once, the first unsupported addition falls back to arbitrary-
precision Python arithmetic, and no induction value is skipped or duplicated.
Negative overflow is not reachable with the intentionally supported positive
unit-step `range(n)` shape. The compact-int guards in the ordinary body remain
unchanged.

## Decision

Feature-on exceeds the requested 2x threshold in every tested case. The budget
sweep nevertheless shows that the remaining overhead is chiefly helper entry,
stack/cache materialization, and the mandated ordinary iteration between
chunks, rather than the checked-int64 arithmetic itself.

Option A, more fused uops backed by C helpers, is useful for narrowly supported
operations but repeats this boundary protocol and makes broader semantics
increasingly difficult to prove. Option B, lowering a proven region to unboxed
value IR and generating the loop in native code, can retain accumulator and
induction values in registers and materialize only on exit. The native data
therefore supports option B as the next architectural experiment toward the
roughly 3x general objective. Neither option is implemented in this iteration.

## Historical debug Tier-2 diagnostics

The earlier `73fd8fc` artifacts in `tier3_data/debug_*.json` used a debug
`--enable-experimental-jit=interpreter` build and `PYTHON_JIT_STRESS=1`. They
remain diagnostic history, including 98.46% coverage at `n=100000`, and are not
used in any native-JIT speedup above. Targeted materialization OOM also remains
source-reviewed rather than runtime-verified because the available
process-global allocator hook cannot isolate the helper's two allocations.

## Resident-state experiment (`2a8f4455c0a2c4b2eb2344b6355488b6bb570f6a`)

Resident mode keeps the accumulator and range progress native across the full
range region and performs an eval-breaker/instrumentation-version and executor
validity load before every logical addition. It materializes only on normal
completion, overflow, or a pending/invalidation deoptimization. The checked-in
consolidated diagnostic sample is from the debug Tier-2 interpreter with stress
enabled solely to establish the executor; it is correctness/counter evidence,
not a native performance claim. For `n=100000`, it recorded 2,999,940 resident
iterations and polls, 30 entries and normal materializations, no pending polls,
and 99.998% processing coverage across the timed samples.

A complete native LLVM 21 measurement could not be produced in this task image.
The pre-existing `clang-21` command points into a removed Swift toolchain, and
the verified jammy LLVM 21 apt repository retry returned HTTP 403 while fetching
its signed `InRelease`. Consequently there is no new resident assembly or
native timing claim. The existing direct-mode assembly already establishes that
copy-and-patch emits the checked loop cleanly; subject to native confirmation of
this resident stencil, the next step remains a small value/region
representation with explicit exit materialization maps feeding the existing
stencil backend, not a second backend.

## Resident native follow-up (`362996d25a5037df98ad83cf60c20fc077b4f483`)

> **Provenance correction:** this section and
> `tier3_data/resident_native_362996d.json` are retained as historical
> diagnostics only.  The artifact records a different ephemeral Codex
> worktree hash and a `work-dirty` Python build; neither quoted full hash is a
> GitHub-resolvable pushed revision whose exact source tree can now be
> reconstructed.  The timings and assembly below must therefore not be used
> as immutable performance evidence or relabelled as measurements of the
> similarly prefixed commit.

The official LLVM 21.1.8 Linux x86-64 archive supplied all four required tools
and built the release (`-DNDEBUG -O3`) native JIT. Stencils were regenerated
with the documented `-fno-vectorize -fno-slp-vectorize` workaround. All timings
below are medians of five stable samples pinned to CPU 0, with 500 warmups and
no JIT stress. Each `n=1000` sample contains 2,000 calls and each `n=100000`
sample 30 calls. `sys._jit.is_available()` and `is_enabled()` were both true,
and the selected executors returned 4,096 bytes of native code. The complete
per-sample counters are in `tier3_data/resident_native_362996d.json`.

```sh
mkdir -p /opt/llvm-21.1.8
curl -fL --retry 4 --retry-delay 3 \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/LLVM-21.1.8-Linux-X64.tar.xz \
  | tar -xJ --strip-components=1 -C /opt/llvm-21.1.8
mkdir build-jit && cd build-jit
LLVM_TOOLS_INSTALL_DIR=/opt/llvm-21.1.8 ../configure \
  --enable-experimental-jit=yes
python3.14 ../Tools/jit/build.py x86_64-pc-linux-gnu -o . -p . -f \
  --cflags='-fno-vectorize -fno-slp-vectorize' \
  --llvm-tools-install-dir=/opt/llvm-21.1.8
touch .jit-stamp
LLVM_TOOLS_INSTALL_DIR=/opt/llvm-21.1.8 make -j8
```

| n | initial | off (ns) | helper 64 / 4096 | direct 64 / 4096 | resident (ns) | resident coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0 | 11,309 | 1,079 / 682 | 982 / 565 | 980 | 99.800% |
| 1,000 | -7 | 11,482 | 1,092 / 679 | 976 / 576 | 944 | 99.800% |
| 1,000 | 2**40 | 27,393 | 1,445 / 724 | 1,321 / 606 | 975 | 99.800% |
| 100,000 | 0 | 2,585,167 | 134,890 / 57,028 | 122,827 / 45,721 | 82,132 | 99.998% |
| 100,000 | -7 | 2,587,981 | 136,518 / 57,604 | 122,606 / 46,845 | 82,599 | 99.998% |
| 100,000 | 2**40 | 3,319,186 | 146,789 / 57,144 | 137,718 / 45,858 | 82,947 | 99.998% |

For the 15 million requested iterations in each long-loop resident row, the
counter deltas were 150 entries, 14,999,700 iterations, 14,999,700 fast polls,
zero pending polls/overflow exits, and 150 normal materializations. Thus the
resident mechanism removes normal boundary materialization, but its exact
per-backedge poll makes it 1.75--1.81x slower than direct mode at budget 4096.

The actual generated executor's resident loop is at offsets `0x2ab..0x2f0`:

```asm
2ab: lea    (%rcx,%r14,1),%r12
2af: add    %r9,%r12
2b2: mov    %r12,0x38(%rsp)       # reconstruction spill
2b7: seto   %r13b
2bb: jo     0x334                 # checked-int64 overflow exit
2bd: cmp    %r14,%rdx
2c0: je     0x34c                 # normal end
2cb: mov    0x18(%r9),%r9         # relaxed eval_breaker load
2cf: inc    %r14
2d2: cmp    0x40(%rsp),%r9        # instrumentation version
2d7: jne    0x2f0                 # pending/instrumentation exit
2dd: mov    %r11,%r10
2e0: inc    %r11
2e3: inc    %rax
2e6: mov    0x38(%rsp),%r9
2eb: test   %dil,%dil             # validity captured under the GIL
2ee: jne    0x2ab
```

There are no calls, `PyLong_*` operations, budget lookups, or executor-counter
writes on this backedge. The total is spilled/reloaded once per iteration for
exit reconstruction; progress and limit values remain in registers. Counter
publication begins at `0x380`, after the native loop. Entry conversion and the
two successful reconstruction allocations remain outside it.

The focused signal test runtime-verifies that pending work observes a coherent
prefix before the long range finishes. Enabling `sys.settrace()` after warmup
runtime-verifies the other reachable transition: instrumentation invalidates
or bypasses the resident executor, the call produces normal line events, and
the old executor's resident-iteration counter does not advance. Allocation
failure remains source-verified rather than injected. Preparation now gives
the resident uop separate periodic and reconstruction-error targets, and both
allocations precede any Python-visible state update.

### Decision

The assembly confirms that copy-and-patch expresses the poll and arithmetic
without hot-loop calls or statistics writes. Resident state does remove nearly
all normal materializations, but exact periodic polling plus its reconstruction
spill costs substantially more than the amortized 4096-item direct loop. The
next experiment should evolve the existing Tier-2 optimizer with a small value
or region representation and explicit materialization/deopt maps, still feeding
the stencil backend. A narrow second recurrence can test that representation;
this evidence does not justify a separate native backend.
