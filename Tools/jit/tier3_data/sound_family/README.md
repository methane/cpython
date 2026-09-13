# Sound parameterized-family acceptance

This focused rerun validates the shared residency skeleton after the verifier
soundness fixes.  Every microbenchmark used `n=100000`, `initial=2**40`,
same-input training, 300 warmup calls, 1,000 calls per sample, three samples,
and included result validation in the timed interval.

| Workload | feature off | resident | ratio | resident coverage |
|---|---:|---:|---:|---:|
| sum | 3.023 ms | 90.601 us | 33.37x | 99.998% |
| squares | 4.880 ms | 87.938 us | 55.49x | 99.998% |
| constant | 2.968 ms | 93.482 us | 31.75x | 99.998% |
| affine (`scale=-3`, `bias=11`) | 4.021 ms | 92.332 us | 43.55x | 99.998% |

All resident samples retained the same executor, returned the independently
checked result, exposed nonempty 4,096-byte native code, and reported exactly
299,994,000 resident iterations across the three samples.  The generated
stencils expand `_Py_TIER3_RESIDENT_LOOP` at compile time; no expression switch
or helper call is executed on an arithmetic backedge.

## Established-workload coverage

`richards` and `nbody` from pyperformance 1.14.0 were run directly with the
target interpreter because automatic virtual-environment setup could not fetch
`setuptools` from PyPI.  This is a nonstandard launch, recorded in the manifest.
The fast results were 17.9/17.5 ms for Richards and 50.0/50.4 ms for nbody
(feature-off/resident); nbody's difference was not significant.  A separate
stress-enabled diagnostic run emitted zero `tier3-region` dumps for both
benchmarks.  Accordingly, these measurements show no reduction-family
coverage, and the small timing differences must not be attributed to this
optimization.  A useful next target must come from their actual hot trace
shapes rather than another synthetic polynomial recurrence.
