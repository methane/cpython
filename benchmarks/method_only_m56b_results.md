# M56b: method JIT単独とmainの比較

候補はtracing frontend・記録dispatch・side trace生成を削除し、静的method JITとTier 1 fallbackだけを使う。時間比はcandidate / mainで、小さいほど速い。ユーザーの更新後の条件は、全体の幾何平均が1.00以下であること。個別の10%超過は許容し、隠さず報告する。

GILはtracing JITとmethod JITの比較。固定mainのFT buildはJITを要求してもexecutorを生成しないため、FTはTier 1とmethod JITの比較になる。FT候補も複数のthread stateが共存するとJITを無効化する。

候補にはC実装と共通optimizerの変更も含まれる。ブランチ全体の比較であり、frontend変更だけの因果効果ではない。両側ともC `_decimal`を使用する。

## 全体結果

| 構成 | 比較できた結果 | 未完了の仕様 | 時間比の幾何平均 [95% CI] | 1.10超 |
|---|---:|---:|---:|---:|
| ft | 121 | 3 | 0.9271 [0.9265, 0.9276] | 0 |
| gil-pgo-lto | 122 | 2 | 0.9705 [0.9683, 0.9731] | 3 |

ft: 点推定で条件を満たす。全結果の幾何平均で実行時間がmainより7.29%短い。順序別の幾何平均は 0.9268, 0.9273。
点推定がmainより速い結果は99件、95%区間の上端が1未満の結果は96件。
gil-pgo-lto: 点推定で条件を満たす。全結果の幾何平均で実行時間がmainより2.95%短い。順序別の幾何平均は 0.9702, 0.9708。
点推定がmainより速い結果は67件、95%区間の上端が1未満の結果は57件。

候補にはGIL handoffなどC側の修正も含まれる。改善の大きい`bench_mp_pool`と`bench_thread_pool`の2結果を除いたGILの参考集計は0.9795。これは主集計の置き換えではなく、その参考値もfrontend変更だけの因果効果を示すものではない。

各workerの平均を同じ重みで集計し、blockごとの比を幾何平均する。全体集計では結果1件を1票とし、複数の結果を出す仕様にはその件数の重みがある。95%区間はblock内のworkerを再標本化するbootstrap（4,000回）。校正・warmupを除き、全測定workerを保持した。失敗・未完了の仕様は幾何平均に含めない。この区間は固定したworkload集合・buildの実行時変動を表し、別build・CPUや未測定のアプリケーションへの一般化を保証しない。

## 全benchmark結果

| Benchmark | FT時間比 [95% CI] | GIL PGO/LTO時間比 [95% CI] |
|---|---:|---:|
| `2to3` | 1.0190 [1.0174, 1.0207] | 1.0087 [1.0078, 1.0097] |
| `ascii85_large` | 0.9021 [0.9011, 0.9032] | 0.7965 [0.7953, 0.7976] |
| `ascii85_small` | 0.9907 [0.9893, 0.9921] | 0.9316 [0.9297, 0.9331] |
| `async_generators` | 0.9387 [0.9371, 0.9406] | 0.9710 [0.9682, 0.9739] |
| `async_tree_cpu_io_mixed` | 1.0018 [0.9980, 1.0053] | 0.9562 [0.9465, 0.9665] |
| `async_tree_cpu_io_mixed_tg` | 1.0038 [0.9983, 1.0085] | 0.9700 [0.9646, 0.9747] |
| `async_tree_eager` | 0.9530 [0.9441, 0.9611] | 1.0020 [0.9863, 1.0229] |
| `async_tree_eager_cpu_io_mixed` | 1.0341 [1.0302, 1.0380] | 0.9657 [0.9621, 0.9689] |
| `async_tree_eager_cpu_io_mixed_tg` | 1.0113 [0.9978, 1.0213] | 0.9672 [0.9651, 0.9691] |
| `async_tree_eager_io` | 0.9504 [0.9490, 0.9521] | 1.0224 [1.0104, 1.0437] |
| `async_tree_eager_io_tg` | 0.9495 [0.9444, 0.9547] | 1.0122 [0.9882, 1.0378] |
| `async_tree_eager_memoization` | 0.9572 [0.9484, 0.9657] | 0.9907 [0.9887, 0.9928] |
| `async_tree_eager_memoization_tg` | 0.9668 [0.9649, 0.9690] | 1.0125 [0.9991, 1.0211] |
| `async_tree_eager_tg` | 0.9761 [0.9597, 0.9850] | 0.9821 [0.9794, 0.9850] |
| `async_tree_io` | 0.9230 [0.9117, 0.9319] | 0.9763 [0.9634, 0.9858] |
| `async_tree_io_tg` | 0.9359 [0.9288, 0.9456] | 0.9895 [0.9833, 0.9950] |
| `async_tree_memoization` | 0.9259 [0.9241, 0.9278] | 0.9791 [0.9737, 0.9842] |
| `async_tree_memoization_tg` | 0.9370 [0.9320, 0.9439] | 0.9974 [0.9968, 0.9980] |
| `async_tree_none` | 0.9281 [0.9162, 0.9371] | 1.0335 [1.0220, 1.0458] |
| `async_tree_none_tg` | 0.9517 [0.9400, 0.9640] | 0.9924 [0.9855, 1.0038] |
| `asyncio_tcp` | 0.9894 [0.9521, 1.0161] | 0.9721 [0.9263, 1.0218] |
| `asyncio_tcp_ssl` | 0.9939 [0.9919, 0.9956] | 1.0264 [1.0152, 1.0410] |
| `asyncio_websockets` | 1.0013 [0.9990, 1.0037] | 1.0042 [0.9994, 1.0094] |
| `base16_large` | 0.8277 [0.8070, 0.8487] | 0.8236 [0.8173, 0.8328] |
| `base16_small` | 0.8871 [0.8843, 0.8896] | 0.8857 [0.8826, 0.8888] |
| `base32_large` | 0.9986 [0.9978, 0.9993] | 1.0063 [1.0044, 1.0084] |
| `base32_small` | 0.9405 [0.9390, 0.9421] | **1.1011 [1.0984, 1.1033]** |
| `base64_large` | 0.9994 [0.9990, 0.9997] | 0.9860 [0.9854, 0.9866] |
| `base64_small` | 0.9824 [0.9813, 0.9835] | 1.0465 [1.0457, 1.0473] |
| `base85_large` | 0.9676 [0.9619, 0.9733] | 0.9945 [0.9933, 0.9952] |
| `base85_small` | 0.9726 [0.9715, 0.9738] | 1.0419 [1.0406, 1.0432] |
| `bench_mp_pool` | 1.0022 [0.9797, 1.0258] | 0.3680 [0.2998, 0.4763] |
| `bench_thread_pool` | 1.0039 [0.9932, 1.0140] | 0.8483 [0.7830, 0.9266] |
| `bpe_tokeniser` | 0.8026 [0.8019, 0.8034] | 0.8509 [0.8496, 0.8521] |
| `chameleon` | 0.9085 [0.9065, 0.9105] | 0.9603 [0.9576, 0.9628] |
| `chaos` | 0.8425 [0.8397, 0.8452] | 0.9342 [0.9284, 0.9396] |
| `comprehensions` | 0.9174 [0.9165, 0.9184] | 1.0368 [1.0251, 1.0549] |
| `connected_components` | 0.9717 [0.9701, 0.9735] | 0.9988 [0.9939, 1.0043] |
| `coroutines` | 0.9523 [0.9489, 0.9555] | 1.0127 [1.0100, 1.0155] |
| `coverage` | 1.0171 [1.0133, 1.0207] | 1.0235 [1.0206, 1.0266] |
| `create_gc_cycles` | 1.0025 [0.9989, 1.0060] | 0.9928 [0.9779, 1.0057] |
| `crypto_pyaes` | 0.8921 [0.8905, 0.8937] | 0.9398 [0.8886, 0.9721] |
| `dask` | 未完了 | 1.0094 [0.9944, 1.0240] |
| `deepcopy` | 0.9621 [0.9594, 0.9646] | 1.0466 [1.0400, 1.0525] |
| `deepcopy_memo` | 0.8348 [0.8299, 0.8398] | 1.0711 [1.0275, 1.1153] |
| `deepcopy_reduce` | 0.9517 [0.9501, 0.9539] | 1.0124 [1.0027, 1.0229] |
| `deltablue` | 0.8793 [0.8694, 0.8854] | 1.0051 [1.0015, 1.0087] |
| `django_template` | 0.9454 [0.9435, 0.9473] | 0.9668 [0.9556, 0.9768] |
| `docutils` | 1.0026 [0.9988, 1.0080] | 0.9872 [0.9822, 0.9919] |
| `dulwich_log` | 0.7849 [0.7796, 0.7899] | 1.0850 [1.0722, 1.0969] |
| `fannkuch` | 0.8238 [0.8182, 0.8327] | 0.9167 [0.9121, 0.9218] |
| `float` | 0.8178 [0.8152, 0.8206] | 1.0384 [1.0359, 1.0412] |
| `gc_traversal` | 1.0065 [0.9999, 1.0134] | 0.9895 [0.9834, 0.9961] |
| `generators` | 0.9959 [0.9926, 0.9990] | 0.9513 [0.9456, 0.9572] |
| `genshi_text` | 0.9229 [0.9214, 0.9246] | 1.0434 [1.0353, 1.0520] |
| `genshi_xml` | 0.9875 [0.9844, 0.9903] | 1.0772 [1.0577, 1.0957] |
| `go` | 0.8145 [0.8127, 0.8158] | 0.8660 [0.8569, 0.8724] |
| `hexiom` | 0.8556 [0.8539, 0.8573] | 0.7771 [0.7743, 0.7792] |
| `html5lib` | 0.8420 [0.8399, 0.8439] | 0.9660 [0.9465, 0.9839] |
| `json_dumps` | 0.9743 [0.9700, 0.9774] | 1.0677 [1.0658, 1.0696] |
| `json_loads` | 1.0037 [1.0019, 1.0055] | 1.0036 [0.9960, 1.0102] |
| `logging_format` | 0.9543 [0.9497, 0.9585] | 1.0883 [1.0798, 1.0972] |
| `logging_silent` | 1.0477 [1.0427, 1.0525] | 1.0040 [1.0008, 1.0065] |
| `logging_simple` | 0.9520 [0.9489, 0.9551] | 1.0492 [1.0348, 1.0636] |
| `mako` | 0.8717 [0.8679, 0.8755] | 1.0117 [1.0108, 1.0127] |
| `many_optionals` | 0.9383 [0.9363, 0.9404] | 1.0172 [1.0114, 1.0228] |
| `mdp` | 0.9595 [0.9568, 0.9621] | 0.9586 [0.9556, 0.9617] |
| `meteor_contest` | 0.9477 [0.9467, 0.9486] | 1.0098 [1.0085, 1.0112] |
| `nbody` | 0.5605 [0.5563, 0.5639] | 0.9174 [0.9053, 0.9245] |
| `nqueens` | 0.9318 [0.9281, 0.9364] | 1.0785 [1.0760, 1.0811] |
| `pathlib` | 0.9987 [0.9920, 1.0054] | 1.0145 [1.0098, 1.0192] |
| `pickle` | 0.9915 [0.9872, 0.9974] | 1.0364 [1.0314, 1.0411] |
| `pickle_dict` | 1.0246 [1.0200, 1.0295] | 0.9647 [0.9563, 0.9758] |
| `pickle_list` | 0.9710 [0.9660, 0.9757] | 0.9977 [0.9914, 1.0038] |
| `pickle_pure_python` | 0.8437 [0.8423, 0.8453] | 1.0352 [1.0327, 1.0382] |
| `pidigits` | 1.0048 [1.0034, 1.0068] | 0.9999 [0.9996, 1.0002] |
| `pprint_pformat` | 0.9488 [0.9442, 0.9526] | 1.0662 [1.0410, 1.0870] |
| `pprint_safe_repr` | 0.9478 [0.9443, 0.9512] | 0.9948 [0.9328, 1.0638] |
| `pyflate` | 0.8358 [0.8335, 0.8386] | 0.9865 [0.9813, 0.9922] |
| `python_startup` | 1.0045 [1.0032, 1.0059] | 1.0007 [0.9995, 1.0018] |
| `python_startup_no_site` | 1.0040 [1.0031, 1.0049] | 0.9997 [0.9989, 1.0004] |
| `raytrace` | 0.9149 [0.9123, 0.9177] | 0.9712 [0.9614, 0.9807] |
| `regex_compile` | 0.8433 [0.8414, 0.8451] | 1.0073 [0.9987, 1.0130] |
| `regex_dna` | 0.9586 [0.9572, 0.9601] | 0.9655 [0.9639, 0.9673] |
| `regex_effbot` | 1.0390 [1.0357, 1.0430] | 1.0362 [1.0342, 1.0385] |
| `regex_v8` | 0.9932 [0.9923, 0.9940] | 1.0121 [1.0096, 1.0149] |
| `richards` | 0.7713 [0.7703, 0.7723] | 0.9082 [0.9002, 0.9158] |
| `richards_super` | 0.7989 [0.7983, 0.7995] | 0.9979 [0.9707, 1.0146] |
| `scimark_fft` | 0.8669 [0.8655, 0.8684] | 0.9543 [0.9534, 0.9554] |
| `scimark_lu` | 0.8568 [0.8551, 0.8587] | 0.7538 [0.7529, 0.7547] |
| `scimark_monte_carlo` | 0.8354 [0.8335, 0.8371] | 0.9126 [0.9105, 0.9146] |
| `scimark_sor` | 0.8432 [0.8401, 0.8460] | 1.0679 [1.0669, 1.0689] |
| `scimark_sparse_mat_mult` | 0.8481 [0.8449, 0.8512] | 0.9557 [0.9465, 0.9721] |
| `shortest_path` | 0.9812 [0.9789, 0.9834] | **1.1492 [1.0504, 1.2479]** |
| `spectral_norm` | 0.4009 [0.4001, 0.4015] | 0.5641 [0.5627, 0.5650] |
| `sphinx` | 0.9982 [0.9924, 1.0037] | 1.0029 [0.9923, 1.0137] |
| `sqlalchemy_declarative` | 1.0171 [1.0126, 1.0210] | 0.9355 [0.9323, 0.9388] |
| `sqlalchemy_imperative` | 0.8701 [0.8649, 0.8760] | 1.0482 [1.0260, 1.0709] |
| `sqlglot_v2_normalize` | 0.9723 [0.9714, 0.9732] | 1.0628 [1.0370, 1.0804] |
| `sqlglot_v2_optimize` | 0.9737 [0.9712, 0.9754] | 1.0480 [1.0439, 1.0525] |
| `sqlglot_v2_parse` | 0.8886 [0.8870, 0.8902] | 1.0260 [1.0225, 1.0296] |
| `sqlglot_v2_transpile` | 0.9275 [0.9266, 0.9285] | 1.0339 [1.0287, 1.0387] |
| `sqlite_synth` | 0.9755 [0.9601, 0.9925] | 0.9982 [0.9873, 1.0058] |
| `subparsers` | 0.9265 [0.9196, 0.9331] | 1.0033 [0.9859, 1.0166] |
| `sympy_expand` | 0.8996 [0.8971, 0.9018] | **1.1480 [1.1428, 1.1530]** |
| `sympy_integrate` | 0.9809 [0.9797, 0.9820] | 0.9660 [0.9597, 0.9726] |
| `sympy_str` | 0.9025 [0.9014, 0.9037] | 1.0192 [1.0143, 1.0240] |
| `sympy_sum` | 0.9945 [0.9899, 0.9987] | 0.9765 [0.9683, 0.9838] |
| `telco` | 0.9593 [0.9447, 0.9751] | 1.0150 [1.0066, 1.0234] |
| `tomli_loads` | 0.8814 [0.8773, 0.8849] | 0.9589 [0.9302, 0.9773] |
| `tornado_http` | 0.9942 [0.9912, 0.9970] | 0.9756 [0.9657, 0.9844] |
| `typing_runtime_protocols` | 0.9335 [0.9299, 0.9377] | 1.0550 [1.0527, 1.0573] |
| `unpack_sequence` | 1.0013 [0.9923, 1.0143] | 0.5278 [0.5247, 0.5311] |
| `unpickle` | 0.9963 [0.9940, 0.9989] | 0.9874 [0.9779, 0.9972] |
| `unpickle_list` | 1.0192 [1.0144, 1.0233] | 0.9117 [0.9055, 0.9182] |
| `unpickle_pure_python` | 0.8106 [0.8081, 0.8127] | 0.9888 [0.9872, 0.9905] |
| `urlsafe_base64_small` | 0.9501 [0.9488, 0.9516] | 0.9711 [0.9702, 0.9720] |
| `xdsl_constant_fold` | 0.8873 [0.8841, 0.8906] | 0.9734 [0.9632, 0.9828] |
| `xml_etree_generate` | 0.9424 [0.9403, 0.9452] | 0.9042 [0.9014, 0.9071] |
| `xml_etree_iterparse` | 0.9551 [0.9522, 0.9576] | 1.0013 [0.9986, 1.0040] |
| `xml_etree_parse` | 0.9973 [0.9949, 0.9999] | 0.9881 [0.9864, 0.9901] |
| `xml_etree_process` | 0.9226 [0.9208, 0.9240] | 0.9762 [0.9416, 0.9961] |

## 個別の10%境界と不確実性

ft: 95%区間の上端も全結果1.10以内。

gil-pgo-lto: `base32_small`, `deepcopy_memo`, `shortest_path`, `sympy_expand`

GILで点推定が10%を超えた3項目について、`sympy_expand`は両blockで約1.148となり、今回の固定buildでは一貫して遅い。`base32_small`も約1.101で、事前の独立した確認と整合する。

`shortest_path`はcandidateの6 workerが約335–336msの3件と約434–435msの3件に分かれる一方、mainの6件は約334–336msだった。1.149という平均と広い区間をそのまま報告し、遅いworkerを除外しない。元のAmazonグラフデータ・入力ノード・seed条件は同じで、二つの速度帯の原因は未特定。ASLRやJITの特定の処理が原因とは断定しない。

`deepcopy_memo`の全体比較は1.0711だが、95%区間は1.0275–1.1153で、個別に10%以内だと断定できない。これらは全体の幾何平均の達成と別の観測である。

## 未完了・失敗

実行できなかった項目を同等性能とみなさない。失敗・timeoutのログを保存した。

| 構成 | Specification | 記録された理由 |
|---|---|---|
| ft | `dask` | block 0 main: [SIGSEGV](../jit-artifacts/method-only-m56b-full/ft/results/0-dask-main.log) |
| ft | `fastapi` | dependency preparation failed |
| ft | `networkx_k_core` | block 0 main: [timeout](../jit-artifacts/method-only-m56b-full/ft/results/0-networkx_k_core-main.log); block 0 candidate: [timeout](../jit-artifacts/method-only-m56b-full/ft/results/0-networkx_k_core-candidate.log); block 1 main: [timeout](../jit-artifacts/method-only-m56b-full/ft/results/1-networkx_k_core-main.log); block 1 candidate: [timeout](../jit-artifacts/method-only-m56b-full/ft/results/1-networkx_k_core-candidate.log) |
| gil-pgo-lto | `fastapi` | dependency preparation failed |
| gil-pgo-lto | `networkx_k_core` | block 0 main: [timeout](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/results/0-networkx_k_core-main.log); block 0 candidate: [timeout](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/results/0-networkx_k_core-candidate.log); block 1 main: [timeout](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/results/1-networkx_k_core-main.log); block 1 candidate: [timeout](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/results/1-networkx_k_core-candidate.log) |

FT Daskのblock 0ではmainが校正中にSIGSEGVとなった。native stackは`PyFrame_GetCode`内の参照カウント処理、Python stackはDaskのprofiling処理だった。候補の対応runは成功したが、原因や候補が修正していることは未確定。[観測記録](../bugs_report.md#unresolved-observation-free-threaded-main-crashes-during-dask-profiling)に詳細を残した。

詳細は[FTログ](../jit-artifacts/method-only-m56b-full/ft/compare.md)と[GILログ](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/compare.md)。NetworkXのworker上限は15秒、specification上限は60秒。

## 事前の境界確認（全体集計とは別）

GIL screenの不確実な3項目について、全体比較の前に同じ固定buildで一度だけ追加確認した。元のworker・固定ループ数・各側6 worker・逆順2 block・5 warmup/5 valueで、全workerを保持した。この結果は全体比較の標本へ混ぜていない。

| Benchmark | 時間比 [95% CI] |
|---|---:|
| `base32_small` | 1.1018 [1.1006, 1.1031] |
| `deepcopy_memo` | 1.0965 [1.0558, 1.1381] |
| `genshi_xml` | 1.0911 [1.0859, 1.0959] |

base32_smallの10%超過を確認した後、ユーザーが判定条件を全体の幾何平均へ変更した。deepcopy_memoは二つのプロセス速度帯があり、平均付近の小差を断定できない。未検証の追加最適化を混ぜず、検証済みM56bで全体を測定した。

## benchmarks/の8本

元の入力・反復回数を使い、全runのchecksum、実行物、依存を検証した。SQLAlchemy declarativeを含む。逆順2 block、各側1 process/block、各3 warmup・7 value。従来のlocal比較手順どおりhash seedはblock 0で0、block 1で1とし、同じblockの両側でそろえる。pyperformanceとは別の標本・仕事量であり、全体の幾何平均に混ぜない。

| Benchmark | FT時間比（各block） | GIL時間比（各block） |
|---|---:|---:|
| `bpe_tokeniser` | 0.8016 (0.8018, 0.8013) | 0.8442 (0.8462, 0.8422) |
| `btree` | 0.7731 (0.7729, 0.7733) | 0.7952 (0.7976, 0.7928) |
| `deltablue` | 0.7801 (0.7791, 0.7811) | 0.9873 (0.9845, 0.9901) |
| `go` | 0.7614 (0.7653, 0.7576) | 0.8741 (0.8759, 0.8723) |
| `hexiom` | 0.8440 (0.8422, 0.8457) | 0.7868 (0.7876, 0.7860) |
| `raytrace` | 0.8814 (0.8859, 0.8770) | 0.9859 (1.0016, 0.9703) |
| `spectral_norm` | 0.3294 (0.3239, 0.3350) | 0.5228 (0.5216, 0.5240) |
| `sqlalchemy_declarative` | 1.0117 (1.0137, 1.0097) | 0.9352 (0.9338, 0.9367) |

## 固定build・検証・実行条件

mainは `d95f29589e03603aa13d8ca9d4f817dce77d357c` にLLVM 21 build対応を加えたもの。候補は `m56b-method-only.patch` の固定スナップショット。開発比較ではPGO/LTOなし。最終GILはPGO/full-LTO、FTはO3・PGO/LTOなし。GCC 13.3、LLVM 21、frame pointerを使用。

| Build | SHA-256 |
|---|---|
| r0-ft-main | `44c9f1615910b76898e1eb6cd478a36c151f21cf5bc99ea95aa6ac115c85fefb` |
| r0-gil-main | `29f98fde43417b99bad02a6710ad55e55f343a574f8fff306932d1e75b010044` |
| m56b-ft | `842f4ab84873e8132b08c82210199b5fd4702019acee4db49ebbc97184b48db0` |
| m56b-gil-pgo-lto | `9cb1ae62d6ae5a61f1bbbc56e7fbb9e9bdaae4128d2f516641b71e212c740e4b` |

測定後、生成器2ファイルの未使用の`TIER2_TO_TIER2`ハンドラを削除し、残すTier 1 exitハンドラの名前を整理した。全生成処理を再実行して出力変更がないことを確認し、生成器84テストが成功した。固定ソースとの3,869ファイルの比較では、この2ファイル以外に差はなく、コンパイル対象のruntimeソースと生成コードは測定物と同一。差分・同一性監査・テストログは `jit-artifacts/regressions-20260919/m56b-final-generator-cleanup.patch`、`m56b-postmeasurement-generator-audit.json`、`m56b-final-generator-tests.log` に保存した。

GIL debug/native関連1,366件と新規instancecheck 2件の-R 3:3が成功。最終両構成はoptimizer 578件、関連788件、C関連1,154件、JIT無効の属性キャッシュ97件を実行して成功。構成別skipとコマンドは `m56b-final-records.json` と各ログに保存した。旧tracing固有の期待はmethod CFGの検証へ移行しており、旧最適化がすべて移植されたことを意味しない。

Intel Core i5-12450HのCPU 2へ固定（SMT sibling 3）。通常ASLR・powersaveのまま、system tuningは行っていない。3 worker × 5 warmup × 5 value、最小測定時間0.1秒、独立校正。各仕様でmain→candidate、candidate→mainの両順序を使った。thread/process poolは指定の複数CPU集合を使用。FTとGILは順次測定し、build・test・perf診断を性能測定と重ねていない。

生データ・依存・workload・実行物の同一性記録: `jit-artifacts/method-only-m56b-full/`。local 8: `jit-artifacts/regressions-20260919/m56b-local-{ft,gil}-state.json`。開発比較・過去の失敗を含む経緯は[作業レポート](method_only_report.md)と[plan.md](../plan.md)を参照。
