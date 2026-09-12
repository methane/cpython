# Tier-3 prototype result

These are local measurements from an optimized CPython 3.16.0a0 x86-64 Linux
build on 2026-09-12.  The command was:

```sh
./python Tools/jit/tier3_bench.py \
    --n 1000 --loops 2000 --warmup 3000 --runs 5
```

No CPU affinity or frequency controls were available, so these results only
establish the order of magnitude and must not be treated as release-quality
numbers.

| benchmark | interpreter | current JIT | Tier 3 | vs current JIT |
| --- | ---: | ---: | ---: | ---: |
| `sum_range` | 15,183 ns | 38,323 ns | 910 ns | 42.1x |
| `sum_squares` | 25,395 ns | 47,345 ns | 998 ns | 47.5x |

Tier-3 compilation (including Python adapter and executable mapping) took 84 us
and 66 us respectively.  The measured break-even points against the current JIT
were 2.3 and 1.4 calls.  Code sizes were 26 and 33 bytes.  The unexpectedly
poor current-JIT result needs a controlled follow-up; it may reflect this build
or short trace behavior, and is not a claim about normal CPython JIT speed.

The result nevertheless validates the narrow hypothesis: once iterator use,
boxed arithmetic, allocation, reference counting, dispatch, and repeated guards
are removed, these loops become tens of times faster.  The remaining work is to
move the sidecar's entry guard and fallback into executor/deoptimization
machinery before drawing conclusions for general workloads.
