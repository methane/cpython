# Tier-3 range-kernel results

The runtime-verified implementation commit is
`864c1392d965b5871bc0deb6fe81cb70ca97acc0`. Raw JSON includes the complete
configuration, workload, samples, result checks, executor counter snapshots,
and measurement deltas in `tier3_data/`.

## Debug Tier-2 interpreter diagnostics

The diagnostic build and focused test commands were:

```sh
mkdir /workspace/build-tier2 && cd /workspace/build-tier2
/workspace/cpython/configure --with-pydebug --enable-experimental-jit=interpreter
make -j4
./python -m test test_tier3 test_capi.test_opt -v
```

Measurements used `PYTHON_JIT_STRESS=1`, five samples, and matched inputs. The
on rows additionally used `PYTHON_TIER3_JIT=1 PYTHON_TIER3_BUDGET=64`. The
1,000-element rows used 1,000 calls/sample; the 100,000-element rows used 10.
These debug numbers are integration and coverage evidence, not a release
performance claim.

| n | initial | feature | median ns/call | kernel iterations | fraction |
|---:|---:|:---:|---:|---:|---:|
| 1,000 | 0 | off | 237,824.3 | 0 | 0% |
| 1,000 | 0 | on | 6,983.7 | 4,915,000 | 98.30% |
| 1,000 | -7 | off | 235,459.4 | 0 | 0% |
| 1,000 | -7 | on | 6,996.8 | 4,915,000 | 98.30% |
| 1,000 | 2**40 | off | 653,592.6 | 0 | 0% |
| 1,000 | 2**40 | on | 23,446.4 | 4,915,000 | 98.30% |
| 100,000 | 0 | off | 54,999,355.3 | 0 | 0% |
| 100,000 | 0 | on | 2,049,783.6 | 4,923,000 | 98.46% |
| 100,000 | -7 | off | 55,588,696.1 | 0 | 0% |
| 100,000 | -7 | on | 2,079,827.9 | 4,923,000 | 98.46% |
| 100,000 | 2**40 | off | 130,163,294.8 | 0 | 0% |
| 100,000 | 2**40 | on | 2,218,984.7 | 4,923,000 | 98.46% |

The 98.46% `n=100000` fraction is a measured counter delta and passes the >90%
arithmetic milestone; it no longer stops at the former compact-int boundary.
The benchmark first records the supported trace with a compact accumulator, as
an executor cannot be constructed from an initially failing compact-int trace,
and then measures entry with the requested initial value.

## Limitations and verification boundary

The supported unit-step `range(n)` starts at zero and cannot drive the sum toward
`INT64_MIN`; only positive overflow is runtime-tested. Materialization remains
transactional by source review. `_testcapi.set_nomemory()` is process-global and
fails all allocator-domain requests by ordinal, including unrelated interpreter
and exception-handling allocations, so it does not provide a reliable hook for
targeting the helper's `new_sum` and `new_induction` allocations independently;
this iteration does not claim runtime-verified OOM targeting.

The first native-JIT build attempt used the default LLVM 21 requirement and
failed exactly because `clang-21` was unavailable. A second build was configured
with `LLVM_VERSION=17`, matching the installed clang; its outcome and native
measurements are recorded below.

The LLVM 17 attempt reached stencil generation but failed because
`llvm-objdump` was unavailable. Retrying the supported LLVM 21 build with the
installed Swift 6.3.1 LLVM binaries reached unwind extraction and failed with
`RuntimeError: Can't find llvm-dwarfdump-21!`. Consequently no native executor
was produced, `get_jit_code()` could not be runtime-checked in that build, and
no native-JIT timing is claimed. This is an exact tooling blocker, not a
substitution of Tier-2 interpreter data for native data.
