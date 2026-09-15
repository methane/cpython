# Corrected-worker float-chain evidence

The prior `sound_family` pyperf commands did not inherit the Tier-3 environment
into workers.  These results preserve that history and use pyperf 2.10.0's
explicit `--inherit-environ=PYTHON_JIT,PYTHON_TIER3_JIT,PYTHONPATH` allowlist.
The worker probe completed first and required JIT availability/enabled state and
positive resident-control counter progress inside calibration and measurement
workers.

The bounded implementation change promotes observed exact-float operands for
ordered add, subtract, and multiply uops using exact-type guards.  This lets the
existing Tier-2 ownership analysis reuse unique intermediate float objects for
straight-line chains; it is dependency-driven and not tied to benchmark names.
The generic operations remain as deoptimization targets for subclasses and
changed types.

An ordinary-hotness nbody diagnostic contains 120 specialized float multiply,
64 add, and 48 subtract uops in its optimized-trace output.  In-place variants
show that intermediate allocation reuse occurs in the established workload.
Richards remains a nonnumeric control.  Debug Tier-2 pyperf means were 979 ms
for nbody and 341 ms for Richards (18 values each); these are integration and
worker-configuration evidence, **not native-JIT performance claims**.  No
before/after speedup is claimed because LLVM 21 installation was blocked by an
HTTP 403 and no source-matched native executable could be built.

Commands:

```
PYTHONPATH=Tools/jit:$PYP PYTHON_JIT=1 PYTHON_TIER3_JIT=resident \
  build-tier2-debug/python Tools/jit/pyperf_tier3_worker_probe.py \
  --inherit-environ=PYTHON_JIT,PYTHON_TIER3_JIT,PYTHONPATH \
  --fast --min-time=0.01 --processes=1 --values=1 --warmups=1

PYTHONPATH=$PYP PYTHON_JIT=1 PYTHON_TIER3_JIT=resident \
  build-tier2-debug/python $PYP/pyperformance/data-files/benchmarks/bm_nbody/run_benchmark.py \
  --inherit-environ=PYTHON_JIT,PYTHON_TIER3_JIT,PYTHONPATH \
  --fast --min-time=0.05 --processes=2
```
