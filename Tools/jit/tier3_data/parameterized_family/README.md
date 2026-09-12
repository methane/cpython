# Parameterized resident reduction native acceptance

This focused matrix uses one optimized native-JIT executable and fresh processes
for feature-off and resident runs.  Every resident sample used same-input-only
training, retained a valid executor, supplied 4,096 bytes of native code, and
reported 99.998% resident coverage (the exit strategy leaves boundary
iterations to ordinary Python).  Times include per-call result validation.
Each of the three resident samples lasts approximately 88--100 ms.

| expression | feature off | resident | ratio | resident iterations |
|---|---:|---:|---:|---:|
| `total += item` | 2.967 ms | 97.154 us | 30.54x | 299,994,000 |
| `total += item * item` | 4.802 ms | 87.760 us | 54.71x | 299,994,000 |
| `total += bias` | 2.993 ms | 100.179 us | 29.87x | 299,994,000 |
| `total += scale * item + bias` | 3.943 ms | 99.533 us | 39.62x | 299,994,000 |

These are narrow microbenchmarks, not whole-program speedups.  The raw JSON
retains all samples, executor identities, code validation, counters, and source
checkout metadata. `manifest.json` separately identifies the executable and the
clean implementation commit from which it was built. Representative `sum`,
`squares`, and `affine` disassemblies show checked arithmetic and polling in the
native loop; conversions and reconstruction remain outside its backedge.

The admitted domain is the C-`long` range iterator and exact signed-i64
accumulator/coefficient inputs. Invariant locals must occupy slots 0--14;
embedded literals are deliberately limited to signed 24-bit values by the
compact stencil descriptor. Other values retain the ordinary Python loop.
The four-iteration multiplication-overflow example near 3,037,000,500 still
records from function entry rather than the loop header, so it was not counted
as resident overflow evidence; long nonzero-start ranges and addition overflow
are covered by the integration suite.

The requested `richards` and `nbody` pyperformance smoke run was attempted, but
pyperformance could not create its target-interpreter environment because its
subprocess could not reach PyPI to install `setuptools`/`wheel`. No result or
coverage claim is made for those workloads.
