Benchmarks with tag 'apps':
===========================

| Benchmark      | main    | candidate             |
|----------------|:-------:|:---------------------:|
| 2to3           | 187 ms  | 188 ms: 1.01x slower  |
| html5lib       | 34.9 ms | 31.5 ms: 1.11x faster |
| chameleon      | 9.29 ms | 8.77 ms: 1.06x faster |
| Geometric mean | (ref)   | 1.03x faster          |

Benchmark hidden because not significant (3): docutils, tornado_http, sphinx

Benchmarks with tag 'asyncio':
==============================

| Benchmark                        | main     | candidate              |
|----------------------------------|:--------:|:----------------------:|
| async_tree_cpu_io_mixed_tg       | 435 ms   | 419 ms: 1.04x faster   |
| async_tree_eager_cpu_io_mixed    | 360 ms   | 340 ms: 1.06x faster   |
| async_tree_io_tg                 | 525 ms   | 513 ms: 1.02x faster   |
| async_generators                 | 255 ms   | 265 ms: 1.04x slower   |
| async_tree_cpu_io_mixed          | 434 ms   | 415 ms: 1.05x faster   |
| async_tree_eager_cpu_io_mixed_tg | 403 ms   | 383 ms: 1.05x faster   |
| async_tree_io                    | 549 ms   | 539 ms: 1.02x faster   |
| asyncio_tcp_ssl                  | 1.11 sec | 1.11 sec: 1.01x slower |
| coroutines                       | 13.5 ms  | 13.5 ms: 1.00x faster  |
| Geometric mean                   | (ref)    | 1.01x faster           |

Benchmark hidden because not significant (11): async_tree_none, async_tree_eager_io, async_tree_eager_memoization, async_tree_eager_tg, async_tree_memoization_tg, asyncio_tcp, async_tree_eager, async_tree_eager_io_tg, async_tree_eager_memoization_tg, async_tree_memoization, async_tree_none_tg

Benchmarks with tag 'math':
===========================

| Benchmark      | main    | candidate             |
|----------------|:-------:|:---------------------:|
| float          | 38.2 ms | 36.5 ms: 1.05x faster |
| pidigits       | 137 ms  | 135 ms: 1.02x faster  |
| Geometric mean | (ref)   | 1.02x faster          |

Benchmark hidden because not significant (1): nbody

Benchmarks with tag 'regex':
============================

| Benchmark      | main    | candidate             |
|----------------|:-------:|:---------------------:|
| regex_dna      | 113 ms  | 118 ms: 1.05x slower  |
| regex_v8       | 13.5 ms | 14.2 ms: 1.05x slower |
| regex_compile  | 86.5 ms | 87.4 ms: 1.01x slower |
| regex_effbot   | 1.72 ms | 1.63 ms: 1.05x faster |
| Geometric mean | (ref)   | 1.01x slower          |

Benchmarks with tag 'serialize':
================================

| Benchmark            | main     | candidate              |
|----------------------|:--------:|:----------------------:|
| json_loads           | 15.1 us  | 14.8 us: 1.02x faster  |
| pickle_dict          | 20.4 us  | 21.1 us: 1.04x slower  |
| pickle_pure_python   | 175 us   | 172 us: 1.01x faster   |
| unpickle_list        | 3.11 us  | 3.18 us: 1.02x slower  |
| base64_small         | 189 us   | 193 us: 1.02x slower   |
| urlsafe_base64_small | 230 us   | 239 us: 1.04x slower   |
| base32_small         | 174 us   | 183 us: 1.05x slower   |
| base16_small         | 236 us   | 252 us: 1.07x slower   |
| base16_large         | 3.87 ms  | 4.35 ms: 1.12x slower  |
| ascii85_small        | 420 us   | 422 us: 1.01x slower   |
| base85_small         | 168 us   | 175 us: 1.04x slower   |
| json_dumps           | 6.15 ms  | 6.22 ms: 1.01x slower  |
| pickle               | 8.52 us  | 8.59 us: 1.01x slower  |
| tomli_loads          | 1.06 sec | 1.00 sec: 1.06x faster |
| unpickle             | 10.0 us  | 9.69 us: 1.03x faster  |
| unpickle_pure_python | 122 us   | 112 us: 1.09x faster   |
| xml_etree_parse      | 97.9 ms  | 95.0 ms: 1.03x faster  |
| xml_etree_iterparse  | 62.1 ms  | 61.3 ms: 1.01x faster  |
| xml_etree_generate   | 60.8 ms  | 59.9 ms: 1.01x faster  |
| xml_etree_process    | 39.9 ms  | 39.3 ms: 1.02x faster  |
| Geometric mean       | (ref)    | 1.01x slower           |

Benchmark hidden because not significant (5): base64_large, base32_large, ascii85_large, base85_large, pickle_list

Benchmarks with tag 'startup':
==============================

| Benchmark              | main    | candidate             |
|------------------------|:-------:|:---------------------:|
| python_startup         | 10.2 ms | 10.3 ms: 1.01x slower |
| python_startup_no_site | 5.87 ms | 5.89 ms: 1.00x slower |
| Geometric mean         | (ref)   | 1.00x slower          |

Benchmarks with tag 'template':
===============================

| Benchmark       | main    | candidate             |
|-----------------|:-------:|:---------------------:|
| mako            | 6.44 ms | 6.27 ms: 1.03x faster |
| django_template | 23.9 ms | 22.0 ms: 1.09x faster |
| Geometric mean  | (ref)   | 1.06x faster          |

All benchmarks:
===============

| Benchmark                        | main     | candidate              |
|----------------------------------|:--------:|:----------------------:|
| 2to3                             | 187 ms   | 188 ms: 1.01x slower   |
| subparsers                       | 6.11 ms  | 5.96 ms: 1.03x faster  |
| async_tree_cpu_io_mixed_tg       | 435 ms   | 419 ms: 1.04x faster   |
| async_tree_eager_cpu_io_mixed    | 360 ms   | 340 ms: 1.06x faster   |
| async_tree_io_tg                 | 525 ms   | 513 ms: 1.02x faster   |
| bpe_tokeniser                    | 3.01 sec | 2.41 sec: 1.25x faster |
| chaos                            | 33.3 ms  | 30.4 ms: 1.10x faster  |
| coverage                         | 72.5 ms  | 71.9 ms: 1.01x faster  |
| deltablue                        | 1.72 ms  | 1.62 ms: 1.06x faster  |
| fannkuch                         | 211 ms   | 213 ms: 1.01x slower   |
| generators                       | 18.5 ms  | 18.6 ms: 1.01x slower  |
| go                               | 63.3 ms  | 49.2 ms: 1.29x faster  |
| html5lib                         | 34.9 ms  | 31.5 ms: 1.11x faster  |
| json_loads                       | 15.1 us  | 14.8 us: 1.02x faster  |
| mako                             | 6.44 ms  | 6.27 ms: 1.03x faster  |
| meteor_contest                   | 71.3 ms  | 73.7 ms: 1.03x slower  |
| shortest_path                    | 336 ms   | 342 ms: 1.02x slower   |
| k_core                           | 1.92 sec | 1.64 sec: 1.17x faster |
| pathlib                          | 9.44 ms  | 9.39 ms: 1.01x faster  |
| pickle_dict                      | 20.4 us  | 21.1 us: 1.04x slower  |
| pickle_pure_python               | 175 us   | 172 us: 1.01x faster   |
| pprint_safe_repr                 | 467 ms   | 463 ms: 1.01x faster   |
| python_startup                   | 10.2 ms  | 10.3 ms: 1.01x slower  |
| raytrace                         | 160 ms   | 117 ms: 1.37x faster   |
| regex_dna                        | 113 ms   | 118 ms: 1.05x slower   |
| regex_v8                         | 13.5 ms  | 14.2 ms: 1.05x slower  |
| richards_super                   | 14.0 ms  | 14.2 ms: 1.01x slower  |
| spectral_norm                    | 42.1 ms  | 20.3 ms: 2.07x faster  |
| sqlite_synth                     | 1.58 us  | 1.57 us: 1.01x faster  |
| telco                            | 85.2 ms  | 89.5 ms: 1.05x slower  |
| unpickle_list                    | 3.11 us  | 3.18 us: 1.02x slower  |
| async_generators                 | 255 ms   | 265 ms: 1.04x slower   |
| async_tree_cpu_io_mixed          | 434 ms   | 415 ms: 1.05x faster   |
| async_tree_eager_cpu_io_mixed_tg | 403 ms   | 383 ms: 1.05x faster   |
| async_tree_io                    | 549 ms   | 539 ms: 1.02x faster   |
| asyncio_tcp_ssl                  | 1.11 sec | 1.11 sec: 1.01x slower |
| base64_small                     | 189 us   | 193 us: 1.02x slower   |
| urlsafe_base64_small             | 230 us   | 239 us: 1.04x slower   |
| base32_small                     | 174 us   | 183 us: 1.05x slower   |
| base16_small                     | 236 us   | 252 us: 1.07x slower   |
| base16_large                     | 3.87 ms  | 4.35 ms: 1.12x slower  |
| ascii85_small                    | 420 us   | 422 us: 1.01x slower   |
| base85_small                     | 168 us   | 175 us: 1.04x slower   |
| chameleon                        | 9.29 ms  | 8.77 ms: 1.06x faster  |
| comprehensions                   | 9.78 us  | 9.18 us: 1.06x faster  |
| coroutines                       | 13.5 ms  | 13.5 ms: 1.00x faster  |
| crypto_pyaes                     | 46.1 ms  | 45.6 ms: 1.01x faster  |
| deepcopy                         | 158 us   | 154 us: 1.02x faster   |
| deepcopy_reduce                  | 1.86 us  | 1.76 us: 1.06x faster  |
| deepcopy_memo                    | 12.6 us  | 12.6 us: 1.01x faster  |
| django_template                  | 23.9 ms  | 22.0 ms: 1.09x faster  |
| float                            | 38.2 ms  | 36.5 ms: 1.05x faster  |
| gc_traversal                     | 3.57 ms  | 3.39 ms: 1.05x faster  |
| hexiom                           | 3.41 ms  | 1.97 ms: 1.73x faster  |
| json_dumps                       | 6.15 ms  | 6.22 ms: 1.01x slower  |
| logging_format                   | 3.55 us  | 3.59 us: 1.01x slower  |
| logging_silent                   | 57.1 ns  | 49.4 ns: 1.16x faster  |
| logging_simple                   | 3.26 us  | 3.18 us: 1.02x faster  |
| mdp                              | 858 ms   | 812 ms: 1.06x faster   |
| connected_components             | 307 ms   | 312 ms: 1.02x slower   |
| nqueens                          | 49.4 ms  | 48.5 ms: 1.02x faster  |
| pickle                           | 8.52 us  | 8.59 us: 1.01x slower  |
| pidigits                         | 137 ms   | 135 ms: 1.02x faster   |
| pyflate                          | 232 ms   | 227 ms: 1.02x faster   |
| python_startup_no_site           | 5.87 ms  | 5.89 ms: 1.00x slower  |
| regex_compile                    | 86.5 ms  | 87.4 ms: 1.01x slower  |
| regex_effbot                     | 1.72 ms  | 1.63 ms: 1.05x faster  |
| richards                         | 12.4 ms  | 12.4 ms: 1.01x slower  |
| scimark_fft                      | 168 ms   | 161 ms: 1.04x faster   |
| scimark_monte_carlo              | 34.8 ms  | 34.3 ms: 1.01x faster  |
| scimark_sor                      | 55.7 ms  | 56.3 ms: 1.01x slower  |
| scimark_sparse_mat_mult          | 2.91 ms  | 2.94 ms: 1.01x slower  |
| sqlalchemy_imperative            | 8.81 ms  | 7.77 ms: 1.13x faster  |
| sqlglot_v2_optimize              | 35.5 ms  | 36.2 ms: 1.02x slower  |
| sqlglot_v2_transpile             | 940 us   | 955 us: 1.02x slower   |
| sympy_expand                     | 284 ms   | 274 ms: 1.03x faster   |
| sympy_integrate                  | 13.7 ms  | 13.4 ms: 1.02x faster  |
| sympy_sum                        | 98.1 ms  | 97.3 ms: 1.01x faster  |
| tomli_loads                      | 1.06 sec | 1.00 sec: 1.06x faster |
| typing_runtime_protocols         | 81.0 us  | 82.9 us: 1.02x slower  |
| unpickle                         | 10.0 us  | 9.69 us: 1.03x faster  |
| unpickle_pure_python             | 122 us   | 112 us: 1.09x faster   |
| xml_etree_parse                  | 97.9 ms  | 95.0 ms: 1.03x faster  |
| xml_etree_iterparse              | 62.1 ms  | 61.3 ms: 1.01x faster  |
| xml_etree_generate               | 60.8 ms  | 59.9 ms: 1.01x faster  |
| xml_etree_process                | 39.9 ms  | 39.3 ms: 1.02x faster  |
| Geometric mean                   | (ref)    | 1.03x faster           |

Benchmark hidden because not significant (33): async_tree_none, async_tree_eager_io, async_tree_eager_memoization, async_tree_eager_tg, async_tree_memoization_tg, asyncio_tcp, bench_mp_pool, bench_thread_pool, docutils, create_gc_cycles, pprint_pformat, sqlalchemy_declarative, sqlglot_v2_normalize, sqlglot_v2_parse, tornado_http, unpack_sequence, xdsl_constant_fold, many_optionals, async_tree_eager, async_tree_eager_io_tg, async_tree_eager_memoization_tg, async_tree_memoization, async_tree_none_tg, base64_large, base32_large, ascii85_large, base85_large, dulwich_log, nbody, pickle_list, scimark_lu, sphinx, sympy_str
