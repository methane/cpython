# JIT: main / candidate

candidate/mainの実行時間比。各workerの全測定値の平均を等重みで集計し、
各ブロックの比を幾何平均する。校正・warmupは集計対象外。
固定ビルドでの比較であり、再ビルド・別CPUへの一般化はしていない。

Python条件: GIL有効、JIT要求、-O3、PGO/full LTOあり。選択: `all`。
計測後の同一性検証: True。

| Specification / result | candidate/main | 時間短縮 | ブロック比 |
|---|---:|---:|---|
| 2to3 / 2to3 | 1.0087 | -0.87% | 1.0094, 1.0079 |
| argparse / many_optionals | 1.0172 | -1.72% | 1.0208, 1.0136 |
| argparse_subparsers / subparsers | 1.0033 | -0.33% | 0.9911, 1.0157 |
| async_generators / async_generators | 0.9710 | 2.90% | 0.9716, 0.9703 |
| async_tree / async_tree_none | 1.0335 | -3.35% | 1.0285, 1.0384 |
| async_tree_cpu_io_mixed / async_tree_cpu_io_mixed | 0.9562 | 4.38% | 0.9546, 0.9579 |
| async_tree_cpu_io_mixed_tg / async_tree_cpu_io_mixed_tg | 0.9700 | 3.00% | 0.9691, 0.9709 |
| async_tree_eager / async_tree_eager | 1.0020 | -0.20% | 0.9993, 1.0047 |
| async_tree_eager_cpu_io_mixed / async_tree_eager_cpu_io_mixed | 0.9657 | 3.43% | 0.9698, 0.9616 |
| async_tree_eager_cpu_io_mixed_tg / async_tree_eager_cpu_io_mixed_tg | 0.9672 | 3.28% | 0.9672, 0.9671 |
| async_tree_eager_io / async_tree_eager_io | 1.0224 | -2.24% | 1.0102, 1.0348 |
| async_tree_eager_io_tg / async_tree_eager_io_tg | 1.0122 | -1.22% | 1.0119, 1.0126 |
| async_tree_eager_memoization / async_tree_eager_memoization | 0.9907 | 0.93% | 0.9917, 0.9896 |
| async_tree_eager_memoization_tg / async_tree_eager_memoization_tg | 1.0125 | -1.25% | 1.0308, 0.9946 |
| async_tree_eager_tg / async_tree_eager_tg | 0.9821 | 1.79% | 0.9821, 0.9820 |
| async_tree_io / async_tree_io | 0.9763 | 2.37% | 0.9836, 0.9690 |
| async_tree_io_tg / async_tree_io_tg | 0.9895 | 1.05% | 0.9842, 0.9947 |
| async_tree_memoization / async_tree_memoization | 0.9791 | 2.09% | 0.9750, 0.9833 |
| async_tree_memoization_tg / async_tree_memoization_tg | 0.9974 | 0.26% | 0.9990, 0.9959 |
| async_tree_tg / async_tree_none_tg | 0.9924 | 0.76% | 0.9862, 0.9986 |
| asyncio_tcp / asyncio_tcp | 0.9721 | 2.79% | 0.9711, 0.9731 |
| asyncio_tcp_ssl / asyncio_tcp_ssl | 1.0264 | -2.64% | 1.0323, 1.0205 |
| asyncio_websockets / asyncio_websockets | 1.0042 | -0.42% | 1.0057, 1.0027 |
| base64 / ascii85_large | 0.7965 | 20.35% | 0.7963, 0.7967 |
| base64 / ascii85_small | 0.9316 | 6.84% | 0.9305, 0.9327 |
| base64 / base16_large | 0.8236 | 17.64% | 0.8289, 0.8184 |
| base64 / base16_small | 0.8857 | 11.43% | 0.8852, 0.8861 |
| base64 / base32_large | 1.0063 | -0.63% | 1.0055, 1.0071 |
| base64 / base32_small | 1.1011 | -10.11% | 1.1021, 1.1000 |
| base64 / base64_large | 0.9860 | 1.40% | 0.9858, 0.9862 |
| base64 / base64_small | 1.0465 | -4.65% | 1.0464, 1.0467 |
| base64 / base85_large | 0.9945 | 0.55% | 0.9935, 0.9954 |
| base64 / base85_small | 1.0419 | -4.19% | 1.0423, 1.0416 |
| base64 / urlsafe_base64_small | 0.9711 | 2.89% | 0.9705, 0.9717 |
| bpe_tokeniser / bpe_tokeniser | 0.8509 | 14.91% | 0.8501, 0.8517 |
| chameleon / chameleon | 0.9603 | 3.97% | 0.9582, 0.9623 |
| chaos / chaos | 0.9342 | 6.58% | 0.9374, 0.9311 |
| comprehensions / comprehensions | 1.0368 | -3.68% | 1.0471, 1.0267 |
| concurrent_imap / bench_mp_pool | 0.3680 | 63.20% | 0.3434, 0.3943 |
| concurrent_imap / bench_thread_pool | 0.8483 | 15.17% | 0.8656, 0.8314 |
| coroutines / coroutines | 1.0127 | -1.27% | 1.0141, 1.0113 |
| coverage / coverage | 1.0235 | -2.35% | 1.0250, 1.0221 |
| crypto_pyaes / crypto_pyaes | 0.9398 | 6.02% | 0.9675, 0.9128 |
| dask / dask | 1.0094 | -0.94% | 1.0031, 1.0158 |
| deepcopy / deepcopy | 1.0466 | -4.66% | 1.0482, 1.0449 |
| deepcopy / deepcopy_memo | 1.0711 | -7.11% | 1.1090, 1.0344 |
| deepcopy / deepcopy_reduce | 1.0124 | -1.24% | 1.0145, 1.0103 |
| deltablue / deltablue | 1.0051 | -0.51% | 1.0044, 1.0058 |
| django_template / django_template | 0.9668 | 3.32% | 0.9721, 0.9616 |
| docutils / docutils | 0.9872 | 1.28% | 0.9844, 0.9900 |
| dulwich_log / dulwich_log | 1.0850 | -8.50% | 1.0774, 1.0926 |
| fannkuch / fannkuch | 0.9167 | 8.33% | 0.9186, 0.9149 |
| float / float | 1.0384 | -3.84% | 1.0389, 1.0380 |
| gc_collect / create_gc_cycles | 0.9928 | 0.72% | 0.9812, 1.0046 |
| gc_traversal / gc_traversal | 0.9895 | 1.05% | 0.9924, 0.9867 |
| generators / generators | 0.9513 | 4.87% | 0.9527, 0.9499 |
| genshi / genshi_text | 1.0434 | -4.34% | 1.0469, 1.0400 |
| genshi / genshi_xml | 1.0772 | -7.72% | 1.0994, 1.0555 |
| go / go | 0.8660 | 13.40% | 0.8733, 0.8587 |
| hexiom / hexiom | 0.7771 | 22.29% | 0.7757, 0.7786 |
| html5lib / html5lib | 0.9660 | 3.40% | 0.9629, 0.9691 |
| json_dumps / json_dumps | 1.0677 | -6.77% | 1.0668, 1.0686 |
| json_loads / json_loads | 1.0036 | -0.36% | 1.0053, 1.0020 |
| logging / logging_format | 1.0883 | -8.83% | 1.0885, 1.0881 |
| logging / logging_silent | 1.0040 | -0.40% | 1.0036, 1.0044 |
| logging / logging_simple | 1.0492 | -4.92% | 1.0465, 1.0520 |
| mako / mako | 1.0117 | -1.17% | 1.0119, 1.0115 |
| mdp / mdp | 0.9586 | 4.14% | 0.9584, 0.9588 |
| meteor_contest / meteor_contest | 1.0098 | -0.98% | 1.0103, 1.0093 |
| nbody / nbody | 0.9174 | 8.26% | 0.9088, 0.9261 |
| networkx / shortest_path | 1.1492 | -14.92% | 1.0997, 1.2009 |
| networkx_connected_components / connected_components | 0.9988 | 0.12% | 1.0000, 0.9977 |
| nqueens / nqueens | 1.0785 | -7.85% | 1.0795, 1.0776 |
| pathlib / pathlib | 1.0145 | -1.45% | 1.0089, 1.0201 |
| pickle / pickle | 1.0364 | -3.64% | 1.0326, 1.0402 |
| pickle_dict / pickle_dict | 0.9647 | 3.53% | 0.9659, 0.9634 |
| pickle_list / pickle_list | 0.9977 | 0.23% | 0.9970, 0.9985 |
| pickle_pure_python / pickle_pure_python | 1.0352 | -3.52% | 1.0334, 1.0371 |
| pidigits / pidigits | 0.9999 | 0.01% | 0.9997, 1.0002 |
| pprint / pprint_pformat | 1.0662 | -6.62% | 1.0553, 1.0772 |
| pprint / pprint_safe_repr | 0.9948 | 0.52% | 1.0085, 0.9813 |
| pyflate / pyflate | 0.9865 | 1.35% | 0.9830, 0.9899 |
| python_startup / python_startup | 1.0007 | -0.07% | 0.9993, 1.0021 |
| python_startup_no_site / python_startup_no_site | 0.9997 | 0.03% | 1.0009, 0.9985 |
| raytrace / raytrace | 0.9712 | 2.88% | 0.9738, 0.9686 |
| regex_compile / regex_compile | 1.0073 | -0.73% | 1.0005, 1.0141 |
| regex_dna / regex_dna | 0.9655 | 3.45% | 0.9668, 0.9643 |
| regex_effbot / regex_effbot | 1.0362 | -3.62% | 1.0379, 1.0345 |
| regex_v8 / regex_v8 | 1.0121 | -1.21% | 1.0146, 1.0096 |
| richards / richards | 0.9082 | 9.18% | 0.9088, 0.9076 |
| richards_super / richards_super | 0.9979 | 0.21% | 1.0097, 0.9863 |
| scimark / scimark_fft | 0.9543 | 4.57% | 0.9548, 0.9538 |
| scimark / scimark_lu | 0.7538 | 24.62% | 0.7535, 0.7542 |
| scimark / scimark_monte_carlo | 0.9126 | 8.74% | 0.9114, 0.9138 |
| scimark / scimark_sor | 1.0679 | -6.79% | 1.0686, 1.0672 |
| scimark / scimark_sparse_mat_mult | 0.9557 | 4.43% | 0.9634, 0.9480 |
| spectral_norm / spectral_norm | 0.5641 | 43.59% | 0.5646, 0.5635 |
| sphinx / sphinx | 1.0029 | -0.29% | 1.0025, 1.0034 |
| sqlalchemy_declarative / sqlalchemy_declarative | 0.9355 | 6.45% | 0.9375, 0.9336 |
| sqlalchemy_imperative / sqlalchemy_imperative | 1.0482 | -4.82% | 1.0421, 1.0544 |
| sqlglot_v2 / sqlglot_v2_normalize | 1.0628 | -6.28% | 1.0695, 1.0561 |
| sqlglot_v2_optimize / sqlglot_v2_optimize | 1.0480 | -4.80% | 1.0489, 1.0471 |
| sqlglot_v2_parse / sqlglot_v2_parse | 1.0260 | -2.60% | 1.0252, 1.0269 |
| sqlglot_v2_transpile / sqlglot_v2_transpile | 1.0339 | -3.39% | 1.0306, 1.0372 |
| sqlite_synth / sqlite_synth | 0.9982 | 0.18% | 0.9917, 1.0048 |
| sympy / sympy_expand | 1.1480 | -14.80% | 1.1489, 1.1472 |
| sympy / sympy_integrate | 0.9660 | 3.40% | 0.9595, 0.9725 |
| sympy / sympy_str | 1.0192 | -1.92% | 1.0159, 1.0224 |
| sympy / sympy_sum | 0.9765 | 2.35% | 0.9816, 0.9714 |
| telco / telco | 1.0150 | -1.50% | 1.0143, 1.0157 |
| tomli_loads / tomli_loads | 0.9589 | 4.11% | 0.9382, 0.9800 |
| tornado_http / tornado_http | 0.9756 | 2.44% | 0.9814, 0.9698 |
| typing_runtime_protocols / typing_runtime_protocols | 1.0550 | -5.50% | 1.0587, 1.0512 |
| unpack_sequence / unpack_sequence | 0.5278 | 47.22% | 0.5309, 0.5247 |
| unpickle / unpickle | 0.9874 | 1.26% | 0.9859, 0.9889 |
| unpickle_list / unpickle_list | 0.9117 | 8.83% | 0.9103, 0.9131 |
| unpickle_pure_python / unpickle_pure_python | 0.9888 | 1.12% | 0.9896, 0.9880 |
| xdsl / xdsl_constant_fold | 0.9734 | 2.66% | 0.9719, 0.9749 |
| xml_etree / xml_etree_generate | 0.9042 | 9.58% | 0.9050, 0.9033 |
| xml_etree / xml_etree_iterparse | 1.0013 | -0.13% | 1.0006, 1.0021 |
| xml_etree / xml_etree_parse | 0.9881 | 1.19% | 0.9903, 0.9859 |
| xml_etree / xml_etree_process | 0.9762 | 2.38% | 0.9596, 0.9931 |

選択したspecification: 97、両側全ブロック完了: 95、比較result: 122。
完了resultのみの幾何平均: 0.9705。欠落項目を含むsuite全体の性能値ではない。

## 失敗・未対応

- fastapi: dependency preparation failed (see /home/methane/work/python/cpython-gc/jit-artifacts/pyperformance-gil-pgo-lto-20260917/dependencies/525b32a851ea2b56/wheel.log)
- networkx_k_core: block=0 main rc=124; block=0 candidate rc=124; block=1 main rc=124; block=1 candidate rc=124
- Pythonバージョン制約で対象外: なし
