# Tier-3 range-kernel results

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
