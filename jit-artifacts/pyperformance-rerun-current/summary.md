# Current native-JIT pyperformance comparison

Ratios are candidate elapsed time divided by fixed-main elapsed time; smaller is faster.

- Primary loop-matched results: **117** of 119
- Equal-weight geometric mean: **0.972383** (**2.76% less time**, **1.028x speed**)
- 95% process-bootstrap interval: **[0.970999, 0.973748]**
- Group A / B ratios: **0.961057 / 0.980341**
- Nominally faster / slower: **76 / 41**
- pyperf-significant faster / slower / not significant: **51 / 33 / 33**
- Unstable warnings, main / candidate: **56 / 48**

Including the two loop-mismatched deepcopy subresults gives a sensitivity ratio of **0.972324** across all 119 results. They are excluded from the primary result because main used 1,024 loops while candidate used 65,536 (`deepcopy_reduce`) or 8,192 (`deepcopy_memo`).

Across the 108 loop-matched results also present in the previous analysis, the old/current ratios are **0.968231 / 0.971144**.

Focused JIT-off diagnosis shows that the Base16 regression remains with identical `base64.py` source and predates the Go work. It is sensitive to executable layout and the immediate release of multi-megabyte temporary bytes; see `base16-diagnosis/summary.md`. Removing its two results as a post-hoc sensitivity calculation gives **0.970367** across 115 results. The primary result is unchanged.

Of the 96 requested specifications, 93 completed on both sides and produced 119 result names. The nine result names newly covered relative to the earlier sandbox run are: `2to3`, `asyncio_tcp`, `asyncio_tcp_ssl`, `bench_mp_pool`, `bench_thread_pool`, `connected_components`, `k_core`, `shortest_path`, `tornado_http`.

All three NetworkX specifications completed with the 60-second worker timeout. `shortest_path` was 1.0179, `k_core` was 0.8518, and `connected_components` was 1.0160 candidate/main. The main-side `k_core` result has 9.6% standard deviation, so its large improvement is less precise than most entries.

Three specifications failed symmetrically: `asyncio_websockets` could not bind TCP port 8001 because it was already in use; `dask` failed because cloudpickle expects `DELETE_GLOBAL`; and `genshi` failed on the Python 3.16 `ast.Expression` constructor.

## Largest improvements

| Benchmark | Main | Candidate | Candidate/main | Time change | Significant |
|---|---:|---:|---:|---:|:---:|
| spectral_norm | 42.1 ms | 20.3 ms | 0.4835 | -51.7% | yes |
| hexiom | 3.41 ms | 1.97 ms | 0.5794 | -42.1% | yes |
| raytrace | 160 ms | 117 ms | 0.7296 | -27.0% | yes |
| go | 63.3 ms | 49.2 ms | 0.7776 | -22.2% | yes |
| bpe_tokeniser | 3.01 sec | 2.41 sec | 0.8013 | -19.9% | yes |
| k_core | 1.92 sec | 1.64 sec | 0.8518 | -14.8% | yes |
| logging_silent | 57.1 ns | 49.4 ns | 0.8653 | -13.5% | yes |
| sqlalchemy_imperative | 8.81 ms | 7.77 ms | 0.8826 | -11.7% | yes |
| html5lib | 34.9 ms | 31.5 ms | 0.9039 | -9.6% | yes |
| chaos | 33.3 ms | 30.4 ms | 0.9124 | -8.8% | yes |
| django_template | 23.9 ms | 22.0 ms | 0.9169 | -8.3% | yes |
| unpickle_pure_python | 122 us | 112 us | 0.9174 | -8.3% | yes |
| comprehensions | 9.78 us | 9.18 us | 0.9392 | -6.1% | yes |
| async_tree_eager_cpu_io_mixed | 360 ms | 340 ms | 0.9430 | -5.7% | yes |
| chameleon | 9.29 ms | 8.77 ms | 0.9444 | -5.6% | yes |

## Largest regressions

| Benchmark | Main | Candidate | Candidate/main | Time change | Significant |
|---|---:|---:|---:|---:|:---:|
| base16_large | 3.87 ms | 4.35 ms | 1.1240 | +12.4% | yes |
| base16_small | 236 us | 252 us | 1.0680 | +6.8% | yes |
| base32_small | 174 us | 183 us | 1.0539 | +5.4% | yes |
| regex_v8 | 13.5 ms | 14.2 ms | 1.0530 | +5.3% | yes |
| telco | 85.2 ms | 89.5 ms | 1.0505 | +5.0% | yes |
| regex_dna | 113 ms | 118 ms | 1.0461 | +4.6% | yes |
| base85_small | 168 us | 175 us | 1.0449 | +4.5% | yes |
| urlsafe_base64_small | 230 us | 239 us | 1.0385 | +3.9% | yes |
| async_generators | 255 ms | 265 ms | 1.0384 | +3.8% | yes |
| pickle_dict | 20.4 us | 21.1 us | 1.0377 | +3.8% | yes |
| meteor_contest | 71.3 ms | 73.7 ms | 1.0344 | +3.4% | yes |
| base64_small | 189 us | 193 us | 1.0241 | +2.4% | yes |
| typing_runtime_protocols | 81.0 us | 82.9 us | 1.0225 | +2.3% | yes |
| unpickle_list | 3.11 us | 3.18 us | 1.0222 | +2.2% | yes |
| sqlglot_v2_optimize | 35.5 ms | 36.2 ms | 1.0180 | +1.8% | yes |
