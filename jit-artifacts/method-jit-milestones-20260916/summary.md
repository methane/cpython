# Method-JIT milestones 1--6 benchmark summary

Date: 2026-09-16

All native builds used LLVM 21 without PGO or LTO.  Lower ratios are better.
The main and GIL candidate executables had SHA-256 hashes
`8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`
and
`09ea0b2ed0658fbd439f619ea67fe9bf9d5176093f9ad15b491179127fe75a5b`.

The archived build manifest identifies this main binary as commit
`a60343ed17785ebbcd43de9080cadd8e2541db6f`, built on September 13 with
`-fno-vectorize -fno-slp-vectorize` for JIT stencils. The candidate is based on
the newer `d95f29589e03603aa13d8ca9d4f817dce77d357c` and uses ordinary stencil
flags. These are historical-binary comparisons, not an isolated measurement
of this changeset. Rebuild a matching control before attributing the delta.

## Fixed-workload ABBA results

| Benchmark | Main A | Candidate A | Main B | Candidate B | Candidate/main geometric mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Richards | 12.510 ms | 12.392 ms | 12.485 ms | 12.445 ms | 0.9936 |
| NetworkX connected_components | 310.371 ms | 307.569 ms | 309.393 ms | 307.973 ms | 0.9932 |
| Go | 62.888 ms | 84.216 ms | 63.069 ms | 84.792 ms | 1.3418 |

Richards used 32 loops per value, eight warmups, and seven measured values.
NetworkX used one loop, one warmup, three measured values, a separate bytecode
cache per executable, and a 15-second hard timeout for each process.  Go used
three warmups and seven measured values.  Every Go checksum matched the
expected move and global counter deltas.

Richards and NetworkX are effectively neutral at about 0.6--0.7% faster in
this short screen.  Go is a repeatable 34.2% regression.  A 20-value `perf
stat` diagnostic found that the candidate executed 48.1% more instructions,
40.5% more branches, and 32.7% more cycles than main.  Branch misses rose only
6.3%, so the primary cost is extra executed work rather than branch
prediction.

The executor inventory suggests sources of extra work. The current frontend spills
the stack-cache convention at every CFG edge and only inlines small
straight-line exact Python callees.  Go is dominated by branch-heavy methods
and Python method-call chains, so method executors repeatedly execute CFG
bookkeeping or leave to Tier 1 at calls that the path recorder can inline.
Cross-block stack-cache signatures, redundant validity/IP operations, and
inlining of branching callees are candidates for improvement. Their individual
contributions have not been measured. Aggregate perf counters include startup,
compilation and warmup; controlled feature comparisons and hot-path profiles
are needed before assigning the regression to a particular mechanism.

## Correctness finding during the screen

The first NetworkX candidate run exposed a completed-call side-exit bug.  An
`_TIER2_RESUME_CHECK` emitted after a call retained the call bytecode as its
deoptimization target.  When the periodic counter fired, Tier 1 executed the
call again with its result stack, producing `TypeError: 'str' object is not
callable` in `Graph.add_edges_from`.  The method frontend now mirrors the
trace frontend and resumes at the next bytecode after a completed call.
NetworkX then loaded its full graph successfully and all four timed runs
completed within nine seconds each.

Raw samples, `perf stat` CSV files, executor inventories, and binary identities
are stored beside this file.
