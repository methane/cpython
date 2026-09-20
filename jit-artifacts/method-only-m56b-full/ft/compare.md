# JIT: main / candidate

candidate/mainの実行時間比。各workerの全測定値の平均を等重みで集計し、
各ブロックの比を幾何平均する。校正・warmupは集計対象外。
固定ビルドでの比較であり、再ビルド・別CPUへの一般化はしていない。

Python条件: GIL無効、JIT要求、-O3、PGO/LTOなし。選択: `all`。
計測後の同一性検証: True。

| Specification / result | candidate/main | 時間短縮 | ブロック比 |
|---|---:|---:|---|
| 2to3 / 2to3 | 1.0190 | -1.90% | 1.0181, 1.0200 |
| argparse / many_optionals | 0.9383 | 6.17% | 0.9401, 0.9365 |
| argparse_subparsers / subparsers | 0.9265 | 7.35% | 0.9279, 0.9250 |
| async_generators / async_generators | 0.9387 | 6.13% | 0.9402, 0.9372 |
| async_tree / async_tree_none | 0.9281 | 7.19% | 0.9342, 0.9221 |
| async_tree_cpu_io_mixed / async_tree_cpu_io_mixed | 1.0018 | -0.18% | 1.0006, 1.0031 |
| async_tree_cpu_io_mixed_tg / async_tree_cpu_io_mixed_tg | 1.0038 | -0.38% | 1.0030, 1.0045 |
| async_tree_eager / async_tree_eager | 0.9530 | 4.70% | 0.9485, 0.9575 |
| async_tree_eager_cpu_io_mixed / async_tree_eager_cpu_io_mixed | 1.0341 | -3.41% | 1.0333, 1.0350 |
| async_tree_eager_cpu_io_mixed_tg / async_tree_eager_cpu_io_mixed_tg | 1.0113 | -1.13% | 1.0211, 1.0017 |
| async_tree_eager_io / async_tree_eager_io | 0.9504 | 4.96% | 0.9513, 0.9495 |
| async_tree_eager_io_tg / async_tree_eager_io_tg | 0.9495 | 5.05% | 0.9512, 0.9479 |
| async_tree_eager_memoization / async_tree_eager_memoization | 0.9572 | 4.28% | 0.9560, 0.9584 |
| async_tree_eager_memoization_tg / async_tree_eager_memoization_tg | 0.9668 | 3.32% | 0.9681, 0.9655 |
| async_tree_eager_tg / async_tree_eager_tg | 0.9761 | 2.39% | 0.9591, 0.9934 |
| async_tree_io / async_tree_io | 0.9230 | 7.70% | 0.9264, 0.9196 |
| async_tree_io_tg / async_tree_io_tg | 0.9359 | 6.41% | 0.9382, 0.9336 |
| async_tree_memoization / async_tree_memoization | 0.9259 | 7.41% | 0.9273, 0.9246 |
| async_tree_memoization_tg / async_tree_memoization_tg | 0.9370 | 6.30% | 0.9325, 0.9414 |
| async_tree_tg / async_tree_none_tg | 0.9517 | 4.83% | 0.9411, 0.9625 |
| asyncio_tcp / asyncio_tcp | 0.9894 | 1.06% | 0.9657, 1.0137 |
| asyncio_tcp_ssl / asyncio_tcp_ssl | 0.9939 | 0.61% | 0.9935, 0.9942 |
| asyncio_websockets / asyncio_websockets | 1.0013 | -0.13% | 1.0019, 1.0007 |
| base64 / ascii85_large | 0.9021 | 9.79% | 0.9006, 0.9037 |
| base64 / ascii85_small | 0.9907 | 0.93% | 0.9912, 0.9902 |
| base64 / base16_large | 0.8277 | 17.23% | 0.8412, 0.8144 |
| base64 / base16_small | 0.8871 | 11.29% | 0.8859, 0.8883 |
| base64 / base32_large | 0.9986 | 0.14% | 0.9990, 0.9981 |
| base64 / base32_small | 0.9405 | 5.95% | 0.9407, 0.9402 |
| base64 / base64_large | 0.9994 | 0.06% | 0.9991, 0.9996 |
| base64 / base64_small | 0.9824 | 1.76% | 0.9831, 0.9817 |
| base64 / base85_large | 0.9676 | 3.24% | 0.9685, 0.9667 |
| base64 / base85_small | 0.9726 | 2.74% | 0.9708, 0.9745 |
| base64 / urlsafe_base64_small | 0.9501 | 4.99% | 0.9501, 0.9502 |
| bpe_tokeniser / bpe_tokeniser | 0.8026 | 19.74% | 0.8036, 0.8017 |
| chameleon / chameleon | 0.9085 | 9.15% | 0.9083, 0.9087 |
| chaos / chaos | 0.8425 | 15.75% | 0.8453, 0.8397 |
| comprehensions / comprehensions | 0.9174 | 8.26% | 0.9182, 0.9167 |
| concurrent_imap / bench_mp_pool | 1.0022 | -0.22% | 1.0099, 0.9946 |
| concurrent_imap / bench_thread_pool | 1.0039 | -0.39% | 1.0151, 0.9928 |
| coroutines / coroutines | 0.9523 | 4.77% | 0.9455, 0.9590 |
| coverage / coverage | 1.0171 | -1.71% | 1.0168, 1.0173 |
| crypto_pyaes / crypto_pyaes | 0.8921 | 10.79% | 0.8934, 0.8909 |
| deepcopy / deepcopy | 0.9621 | 3.79% | 0.9613, 0.9630 |
| deepcopy / deepcopy_memo | 0.8348 | 16.52% | 0.8358, 0.8338 |
| deepcopy / deepcopy_reduce | 0.9517 | 4.83% | 0.9512, 0.9521 |
| deltablue / deltablue | 0.8793 | 12.07% | 0.8716, 0.8871 |
| django_template / django_template | 0.9454 | 5.46% | 0.9451, 0.9456 |
| docutils / docutils | 1.0026 | -0.26% | 0.9991, 1.0061 |
| dulwich_log / dulwich_log | 0.7849 | 21.51% | 0.7876, 0.7822 |
| fannkuch / fannkuch | 0.8238 | 17.62% | 0.8278, 0.8197 |
| float / float | 0.8178 | 18.22% | 0.8171, 0.8185 |
| gc_collect / create_gc_cycles | 1.0025 | -0.25% | 1.0009, 1.0042 |
| gc_traversal / gc_traversal | 1.0065 | -0.65% | 1.0065, 1.0065 |
| generators / generators | 0.9959 | 0.41% | 0.9924, 0.9994 |
| genshi / genshi_text | 0.9229 | 7.71% | 0.9229, 0.9229 |
| genshi / genshi_xml | 0.9875 | 1.25% | 0.9935, 0.9816 |
| go / go | 0.8145 | 18.55% | 0.8151, 0.8138 |
| hexiom / hexiom | 0.8556 | 14.44% | 0.8546, 0.8566 |
| html5lib / html5lib | 0.8420 | 15.80% | 0.8428, 0.8412 |
| json_dumps / json_dumps | 0.9743 | 2.57% | 0.9783, 0.9702 |
| json_loads / json_loads | 1.0037 | -0.37% | 1.0035, 1.0038 |
| logging / logging_format | 0.9543 | 4.57% | 0.9469, 0.9617 |
| logging / logging_silent | 1.0477 | -4.77% | 1.0461, 1.0492 |
| logging / logging_simple | 0.9520 | 4.80% | 0.9561, 0.9480 |
| mako / mako | 0.8717 | 12.83% | 0.8704, 0.8731 |
| mdp / mdp | 0.9595 | 4.05% | 0.9604, 0.9586 |
| meteor_contest / meteor_contest | 0.9477 | 5.23% | 0.9475, 0.9478 |
| nbody / nbody | 0.5605 | 43.95% | 0.5585, 0.5625 |
| networkx / shortest_path | 0.9812 | 1.88% | 0.9836, 0.9789 |
| networkx_connected_components / connected_components | 0.9717 | 2.83% | 0.9706, 0.9728 |
| nqueens / nqueens | 0.9318 | 6.82% | 0.9292, 0.9344 |
| pathlib / pathlib | 0.9987 | 0.13% | 0.9907, 1.0068 |
| pickle / pickle | 0.9915 | 0.85% | 0.9877, 0.9954 |
| pickle_dict / pickle_dict | 1.0246 | -2.46% | 1.0213, 1.0279 |
| pickle_list / pickle_list | 0.9710 | 2.90% | 0.9707, 0.9713 |
| pickle_pure_python / pickle_pure_python | 0.8437 | 15.63% | 0.8446, 0.8429 |
| pidigits / pidigits | 1.0048 | -0.48% | 1.0039, 1.0057 |
| pprint / pprint_pformat | 0.9488 | 5.12% | 0.9506, 0.9470 |
| pprint / pprint_safe_repr | 0.9478 | 5.22% | 0.9466, 0.9490 |
| pyflate / pyflate | 0.8358 | 16.42% | 0.8370, 0.8345 |
| python_startup / python_startup | 1.0045 | -0.45% | 1.0038, 1.0052 |
| python_startup_no_site / python_startup_no_site | 1.0040 | -0.40% | 1.0021, 1.0059 |
| raytrace / raytrace | 0.9149 | 8.51% | 0.9107, 0.9191 |
| regex_compile / regex_compile | 0.8433 | 15.67% | 0.8446, 0.8419 |
| regex_dna / regex_dna | 0.9586 | 4.14% | 0.9580, 0.9592 |
| regex_effbot / regex_effbot | 1.0390 | -3.90% | 1.0407, 1.0374 |
| regex_v8 / regex_v8 | 0.9932 | 0.68% | 0.9928, 0.9936 |
| richards / richards | 0.7713 | 22.87% | 0.7702, 0.7724 |
| richards_super / richards_super | 0.7989 | 20.11% | 0.7997, 0.7982 |
| scimark / scimark_fft | 0.8669 | 13.31% | 0.8655, 0.8683 |
| scimark / scimark_lu | 0.8568 | 14.32% | 0.8583, 0.8553 |
| scimark / scimark_monte_carlo | 0.8354 | 16.46% | 0.8344, 0.8364 |
| scimark / scimark_sor | 0.8432 | 15.68% | 0.8427, 0.8437 |
| scimark / scimark_sparse_mat_mult | 0.8481 | 15.19% | 0.8469, 0.8492 |
| spectral_norm / spectral_norm | 0.4009 | 59.91% | 0.4012, 0.4005 |
| sphinx / sphinx | 0.9982 | 0.18% | 0.9943, 1.0021 |
| sqlalchemy_declarative / sqlalchemy_declarative | 1.0171 | -1.71% | 1.0108, 1.0234 |
| sqlalchemy_imperative / sqlalchemy_imperative | 0.8701 | 12.99% | 0.8691, 0.8712 |
| sqlglot_v2 / sqlglot_v2_normalize | 0.9723 | 2.77% | 0.9724, 0.9723 |
| sqlglot_v2_optimize / sqlglot_v2_optimize | 0.9737 | 2.63% | 0.9751, 0.9723 |
| sqlglot_v2_parse / sqlglot_v2_parse | 0.8886 | 11.14% | 0.8891, 0.8880 |
| sqlglot_v2_transpile / sqlglot_v2_transpile | 0.9275 | 7.25% | 0.9262, 0.9288 |
| sqlite_synth / sqlite_synth | 0.9755 | 2.45% | 0.9755, 0.9755 |
| sympy / sympy_expand | 0.8996 | 10.04% | 0.8988, 0.9005 |
| sympy / sympy_integrate | 0.9809 | 1.91% | 0.9812, 0.9806 |
| sympy / sympy_str | 0.9025 | 9.75% | 0.9027, 0.9023 |
| sympy / sympy_sum | 0.9945 | 0.55% | 0.9956, 0.9933 |
| telco / telco | 0.9593 | 4.07% | 0.9679, 0.9508 |
| tomli_loads / tomli_loads | 0.8814 | 11.86% | 0.8762, 0.8867 |
| tornado_http / tornado_http | 0.9942 | 0.58% | 0.9981, 0.9902 |
| typing_runtime_protocols / typing_runtime_protocols | 0.9335 | 6.65% | 0.9315, 0.9355 |
| unpack_sequence / unpack_sequence | 1.0013 | -0.13% | 0.9956, 1.0070 |
| unpickle / unpickle | 0.9963 | 0.37% | 0.9993, 0.9933 |
| unpickle_list / unpickle_list | 1.0192 | -1.92% | 1.0191, 1.0192 |
| unpickle_pure_python / unpickle_pure_python | 0.8106 | 18.94% | 0.8102, 0.8110 |
| xdsl / xdsl_constant_fold | 0.8873 | 11.27% | 0.8877, 0.8869 |
| xml_etree / xml_etree_generate | 0.9424 | 5.76% | 0.9435, 0.9414 |
| xml_etree / xml_etree_iterparse | 0.9551 | 4.49% | 0.9562, 0.9539 |
| xml_etree / xml_etree_parse | 0.9973 | 0.27% | 0.9994, 0.9953 |
| xml_etree / xml_etree_process | 0.9226 | 7.74% | 0.9233, 0.9218 |

FTのスレッド共存中のJIT停止を観測した項目（Tier 1へのfallbackを含む）:
- concurrent_imap/bench_thread_pool (candidate)
- tornado_http/tornado_http (candidate)

これらはJITを要求した設定での性能であり、常時JIT有効・並列JIT実行の測定ではない。
開始・終了時の検査なので、測定中すべての状態遷移を観測したものではない。

選択したspecification: 97、両側全ブロック完了: 94、比較result: 121。
完了resultのみの幾何平均: 0.9271。欠落項目を含むsuite全体の性能値ではない。

## 失敗・未対応

- dask: block=0 main rc=1
- fastapi: dependency preparation failed (see /home/methane/work/python/cpython-gc/jit-artifacts/pyperformance-gil-pgo-lto-20260917/dependencies/525b32a851ea2b56/wheel.log)
- networkx_k_core: block=0 main rc=124; block=0 candidate rc=124; block=1 main rc=124; block=1 candidate rc=124
- Pythonバージョン制約で対象外: なし
