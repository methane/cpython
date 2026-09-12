# Tier-3 range-kernel results

These are diagnostic measurements, not native-JIT claims.  The tested source is
based on review checkpoint `df7179cf3dcae8f2d0c9e9defae1e35122b05312` plus
this iteration.  Raw JSON, including full configure arguments, compiler,
architecture, JIT state, workload, samples, and counter snapshots, is in
`tier3_data/`.

The debug interpreter was configured and built with:

```sh
mkdir build-tier2 && cd build-tier2
../configure --with-pydebug --enable-experimental-jit=interpreter
make -j4
```

Measurements used `PYTHON_JIT_STRESS=1`, five samples, and matched inputs.  The
on rows additionally used `PYTHON_TIER3_JIT=1 PYTHON_TIER3_BUDGET=64`.  These
numbers include debug instrumentation and are recorded only as integration
and coverage evidence; they are not suitable for release-performance claims.

| n | initial | feature | median ns/call | kernel iterations | fraction |
|---:|---:|:---:|---:|---:|---:|
| 1,000 | 0 | off | 234,664.6 | 0 | 0% |
| 1,000 | 0 | on | 7,607.1 | 4,915,000 | 98.3% |
| 1,000 | -7 | off | 230,073.8 | 0 | 0% |
| 1,000 | -7 | on | 7,670.0 | 4,915,000 | 98.3% |
| 1,000 | 2**40 | off | 325,689.2 | 0 | 0% |
| 1,000 | 2**40 | on | 313,492.0 | 0 | 0% (rejected) |
| 100,000 | 0 | off | 36,166,889.2 | 0 | 0% |
| 100,000 | 0 | on | 24,347,655.0 | 11,408,000 | 45.6%* |
| 100,000 | -7 | off | 36,960,955.0 | 0 | 0% |
| 100,000 | -7 | on | 24,658,796.1 | 2,737,920 | 45.6%* |
| 100,000 | 2**40 | off | 34,114,046.6 | 0 | 0% |
| 100,000 | 2**40 | on | 33,862,561.5 | 0 | 0% (rejected) |

`*` The long diagnostic run replaced its executor during measurement.  The raw
older run therefore records only the original executor's partial counters; the
updated benchmark reports `executor replaced` and suppresses a misleading
fraction instead.  No speedup or geometric mean is claimed from unavailable,
rejected, debug, or executor-replaced cases.  The `2**40` rows demonstrate the
intentional compact-integer entry restriction.

Focused correctness was run with feature-off and feature-on subprocesses and
budgets 1, 2, 7, and 64:

```sh
build-tier2/python -m test test_tier3 -v
```
