# Richards Super and B-tree: continued JIT optimization

This follow-up starts at `c2def12a37e` (`Allow tracing through cache-heavy
method entries`), which commits the preceding Richards fix and its report.
The main baseline remains `d95f29589e03603aa13d8ca9d4f817dce77d357c`, with the
same LLVM 21 build compatibility patch. No GitHub operations are involved.
The current task is to make both workloads faster than that main build.

## Workloads and scope

Richards Super uses the original installed pyperformance workload without
editing its algorithm, inputs or result checks. B-tree is the existing
`benchmarks/btree.py`: 20,000 records, normal automatic GC, and its original
traversal/lookup checks. It must not be confused with pyperformance's larger
200,000-record B-tree workload. The previous B-tree regression was relative to
an older candidate; a direct initial PGO comparison still puts c2def about 13%
ahead of main on the standalone workload.

Ordinary implementation iterations use GIL builds without PGO or LTO. The
primary comparison uses GIL, PGO and full LTO, matching the configuration that
exposed the Richards regression. Free-threaded builds receive correctness
validation; their performance is not inferred from GIL results.

## Accepted implementation

- Emit method periodic checks on backward jumps, matching normal bytecode
  semantics. Forward CFG edges do not need an additional loop check. Retain
  method-entry checks and the existing no-interrupt backward-jump behavior.
  The effective correction is in root method lowering; the inline CFG already
  excluded forward jumps.
- Specialize None tests when their input reference is borrowed. Both tracing
  guards and method branches can then discard the reference without a
  potential destructor call, stack synchronization or a following validity
  check. Owned temporaries keep the original closing operation.
- In GIL tracing, retain successful inline-value layout checks for an object
  symbol until an emitted operation can call Python. A no-dict store check
  also proves the weaker read check. Do not apply this cache in FT builds.
- Close a stack reference without an escaping destructor path when another
  owned local, or a retained embedded executor constant, proves another owner
  exists. Keep the reference decrement. Borrowed aliases do not establish
  ownership, and an unexpected final release fails loudly. This optimization
  is GIL-only.
- Extend the existing guarded integer attribute-update region to a receiver
  already on the stack. This includes globals and temporary call results.
  Preserve the receiver and its final cleanup after the store. Prefer the
  arithmetic instruction's recorded IP over an earlier saved attribute IP.
- Reuse the integer held by an attribute only when it is an exact compact
  integer with a unique reference and the new value remains a non-cached
  compact integer. Other references, small integers, large integers and
  non-integer arithmetic retain allocation or the ordinary fallback. The
  integer sign/digit setter is correctly classified as non-escaping.

- Fuse an immortal constant and a local receiver into an attribute store. Keep
  any type/layout guards that remain after analysis. Check that replacing the
  old field cannot invoke Python before mutation; otherwise exit to the
  original store. Preserve insertion order for previously empty inline fields,
  and avoid refcount traffic when the field already contains the constant.
- Record the first explicit argument type for CALL specializations. For
  `isinstance(value, cls)`, when the observed exact type is the known constant
  class with ordinary `type` metaclass, guard exact type identity and fold the
  result to true. Other types exit before consuming arguments. In particular,
  an unrelated object's `__class__` property must still run and may raise.
  CALL family recording also runs for other arities, so the recorder checks
  for the presence of an argument before reading it.
- Use the existing guarded GIL cell-load operation in tracing as well as the
  method frontend. Empty cells exit to tier one for the original error; values
  are read anew each time. FT retains its original getter. The isolated short
  screen did not resolve a timing improvement from this last change.

These changes are selected by runtime ownership, type, layout and control-flow
facts. They do not depend on benchmark names, field names or workload sizes.

## Correctness and rejected experiments

Tests exercise forward and backward edges; both None-guard exits; the timing
of an owned temporary's finalizer; dictionary replacement between reads;
mutation through the same callback after warmup; retained local aliases;
reference counts; global replacement; integer boundaries and aliases; and a
temporary receiver whose destructor observes the completed attribute update.
Existing monitoring, tracing, generator, coroutine, call and generated-code
checks are included in the configuration matrix.

A borrowed-owner store-fusion experiment passed correctness checks but made
the Richards screen slower, so it was removed. Its source stages, binaries,
failed expectations, corrected tests and timing records remain in the artifact
directory. No unfavorable timing process is discarded. The main binary showed
substantial process variation in several short screens, so those screens do
not establish that the target has been achieved.

## Measurement protocol and validation

The primary protocol has six blocks, all permutations of main, c2def-before
and after, with four processes per build/workload/block. Richards uses eight
fixed loops, five warmups and five values. B-tree retains one loop, three
warmups and five values. CPU affinity is 2. Ratios use the geometric mean of
block ratios; intervals are Student-t intervals on six block log ratios.
These characterize fixed builds on this machine, not independent rebuilds,
other hardware or the whole benchmark suite.

The first completed PGO/full-LTO round (the `reuse2` source, before constant
stores and isinstance specialization) passed 1,458 tests in each of native GIL,
debug GIL, native FT and debug FT configurations. Its standard PGO task passed
43 files / 10,468 tests. Its 36 result files / 144 worker processes and all
binary, extension, workload and dependency identities were independently
verified:

| Workload | main | c2def-before | phase one | phase one / main |
| --- | ---: | ---: | ---: | ---: |
| Richards Super | 12.998 ms | 13.980 ms | 13.379 ms | 1.0294 |
| Standalone B-tree | 56.815 ms | 49.481 ms | 48.923 ms | 0.8611 |

Richards still missed the target, which is why work continued. Do not attribute
this round's results to the later source. Phase-two native and debug configurations, with and without the GIL, pass
1,462 related tests each (five GIL skips, thirteen FT skips). Debug builds use
the tier-two interpreter. The final PGO/full-LTO build passes the same 1,462
JIT-enabled tests. Its standard training task passes all 43 files / 10,468 tests
(460 skips). All 14 changed runtime/test files match the frozen build manifest.

The final comparison and independent audit verify all 36 raw result files /
144 worker processes, their result checks, and identities before and after:

| Workload | main | c2def-before | final candidate | candidate / main | 95% block interval |
| --- | ---: | ---: | ---: | ---: | ---: |
| Richards Super | 12.991 ms | 14.014 ms | 12.902 ms | 0.993224 | 0.989157–0.997309 |
| Standalone B-tree | 56.944 ms | 49.620 ms | 48.539 ms | 0.852399 | 0.850716–0.854084 |

Both workloads are faster than main in all six blocks. Execution time is
reduced by **0.68% for Richards Super** and **14.76% for B-tree**. Relative to
the committed c2def-before candidate, the reductions are 7.93% and 2.18%.
The Richards margin over main is small; these results establish the requested
comparison for these fixed GIL/PGO/full-LTO builds on this machine, not a general
speedup guarantee. No FT performance claim follows from the correctness matrix.

Across 24 process means per variant, Richards CV is 0.81% for main, 1.30% for
before, and 0.32% for the candidate. B-tree CV is 0.58%, 0.98%, and 0.38%.
All processes, including slower before processes, remain in the results.

The final executable is
`jit-artifacts/richards-btree-20260917-v2/after-pgo-build/python`, SHA-256
`babf6145453655e71b4abc068f5f4a232caed4e7069259cf3821a1039f54d861`.
The main executable SHA-256 is
`dd63a277fd879d2f0993655c0502ee26f98bf37656890ae30fdeedb734287c49`;
the c2def-before executable SHA-256 is
`cf8599235cf221e63aa750218f6daf07a1d7a0ddb7f3dc3128dbaac1fa6ed6a1`.
The main source commit is the one stated above. All use GCC 13.3, LLVM 21
stencils, `-O3`, frame pointers, standard PGO training and full LTO.

The additional two-block, reversed-order regression screen completes all eight
standalone workloads (32 processes), with matching result checks and verified
identities. This compares the final candidate with **c2def-before**, not main:

| Standalone workload | candidate / c2def-before |
| --- | ---: |
| bpe_tokeniser | 0.9922 |
| btree | 0.9695 |
| deltablue | 0.9858 |
| go | 0.9856 |
| hexiom | 0.9867 |
| raytrace | 1.0062 |
| spectral_norm | 0.9962 |
| sqlalchemy_declarative | 1.0005 |

This small screen suggests no large regression; it is not a significance test.
Raytrace's point estimate is 0.62% slower and SQLAlchemy is effectively flat.
Use the larger primary comparison above for the B-tree conclusion. The raw
screen is in
`jit-artifacts/all-benchmarks-10pct-20260916/richards-btree-v2-pgo-regression-state.json`.

## Experiments retained as negative evidence

The borrowed-owner store fusion regressed; separate self/absent-self argument
binding, combined frame entry, and constant inline-value-offset guards did not
show useful improvement. They are removed. Short screens include occasional
large process outliers in both main and candidate variants; all are retained.
Six additional argument-binding processes did not reproduce its initial slow
process or establish a gain. No favorable subset was selected for the final
comparison.

A mapping-guard-elision experiment failed existing globals/builtins semantic
tests. A symbolic function constant learned from a function-version guard does
not prove exact function identity: different functions sharing code can have
different mappings. All such guard removal was reverted. The first argument
recorder prototype also exposed the shared CALL-family recording rule during
bootstrap and was replaced by the arity-safe version described above.

A warmed-up-only perf recording of the constant-store prototype maps all 59
live executor ranges,
including side traces, with no lost samples. Its largest named ranges are
`schedule@332` (15.48%), `Packet.append_to@26` (10.02%) and `schedule@180`
(9.84%). The latter ranges contain inlined callees and returns, so these are
not exclusive source-function costs. Initial profiles that included symbol
discovery must not be interpreted as workload compilation costs.

Artifacts for exploration and phase one are under
`jit-artifacts/richards-btree-20260917/`; the final source snapshot, build and
measurements are isolated under `jit-artifacts/richards-btree-20260917-v2/`.
Manifests retain source diffs, compiler/configuration flags, executable and
extension hashes, PGO profiles, commands and worker results. PGO uses the
original standard task with JIT disabled; failed or partial training profiles
are never mixed into accepted builds.
