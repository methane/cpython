# 並行method JIT導入後のpyperformance比較

候補は `e3fb6e8edee`、mainは `d95f29589e0`（LLVM 21ビルド対応のみ追加）。時間比はcandidate/mainで、小さいほど速い。今回の測定対象はGIL・O3・PGO/full LTOありの２つのみ。両側でJITを要求し、C `_decimal`を使用した。

mainのtracing JITと候補のmethod JITを比較する。結果はブランチ全体の比較であり、今回の並行実行変更だけの因果効果ではない。FTは今回測定していない。

| 構成 | 完了した結果数 | 未完了の仕様数 | 時間比の幾何平均 [95% CI] | 10%超の遅延 |
|---|---:|---:|---:|---:|
| gil-pgo-lto | 122 | 2 | 0.9772 [0.9753, 0.9791] | 1 |

各workerの測定値の平均を等重みで集計し、blockごとの比を幾何平均した。全体は結果１件を等重みとし、失敗した仕様は除外した。95%区間はblock内のworkerを再標本化する4,000回bootstrap。校正・warmup以外の全サンプルを保持している。区間は固定build・完了したworkload集合の実行変動を表し、再ビルドや別マシンへの一般化を保証しない。

## 改善とリグレッション

gil-pgo-lto: 幾何平均で実行時間がmainより2.28%短い。順序別の幾何平均は 0.9779, 0.9764。

改善の大きい結果: `unpack_sequence` 0.5497, `spectral_norm` 0.5823, `bench_mp_pool` 0.6670, `scimark_lu` 0.7531, `hexiom` 0.7720, `ascii85_large` 0.7978, `base16_large` 0.8037, `bpe_tokeniser` 0.8501


3%以上遅い結果: `sympy_expand` 1.1448, `sqlglot_v2_normalize` 1.0784, `logging_format` 1.0765, `genshi_xml` 1.0754, `pprint_safe_repr` 1.0746, `json_dumps` 1.0721, `sqlglot_v2_transpile` 1.0692, `nqueens` 1.0679, `pprint_pformat` 1.0613, `base32_small` 1.0599, `dulwich_log` 1.0595, `deepcopy_memo` 1.0584, `typing_runtime_protocols` 1.0567, `coverage` 1.0550, `scimark_sor` 1.0549, `base64_small` 1.0437, `sqlglot_v2_optimize` 1.0408, `pickle_list` 1.0390, `subparsers` 1.0361, `async_tree_none` 1.0330

## 前回M56bとの比較と変動

前回と共通の122結果で比較する。前回と今回は別時点・別候補ビルドであり、旧候補と新候補を同時に交互実行した比較ではない。並行JIT変更だけの因果効果や、再ビルド一般の差としては扱わない。

| 集計・項目 | 前回M56b / main | 今回 / main |
|---|---:|---:|
| 全122結果の幾何平均 | 0.9705 | 0.9772 |
| pool２結果を除く参考集計 | 0.9795 | 0.9800 |
| `bench_mp_pool` | 0.3680 | 0.6670 |
| `bench_thread_pool` | 0.8483 | 1.0055 |
| `shortest_path` | 1.1492 | 1.0017 |
| `sympy_expand` | 1.1480 | 1.1448 |
| `base32_small` | 1.1011 | 1.0599 |
| `regex_compile` | 1.0073 | 1.0113 |
| `richards_super` | 0.9979 | 1.0271 |
| `go` | 0.8660 | 0.8600 |
| `sqlalchemy_declarative` | 0.9355 | 0.9328 |

全体の改善幅は前回2.95%から今回2.28%となった。pool２結果を除く参考値は前回0.9795・今回0.9800と近い。poolは待機・スケジューリングも含み、今回のprocess poolの95%区間も0.5484–0.8235と広い。主集計から都合の悪い値を除外せず、全workerを保持した上で参考集計を併記している。

`sympy_expand`は両blockで約1.148・1.142であり、14.5%遅延が再現する。点推定で10%を超えたのはこの１結果。ただし`deepcopy_memo`は1.0584でも95%区間が1.0025–1.1187、block比が1.1176・1.0024で、個別に10%以内とは断定できない。

`shortest_path`は今回1.0017で、前回の遅い速度帯は再現しなかった。今回candidateの６workerは331–337ms。原因は特定しておらず、今回の実装が前回の二峰性を修正したとは判断しない。`spectral_norm`はcandidateの６worker中５件が約19.4ms、１件が約23.1msで、遅いworkerも平均と区間に含めた。

点推定でmainより速い結果は60件。95%区間全体が1未満の結果は55件、1より大きい結果は46件。これらは項目ごとの区間で、多重比較補正はしていない。

FTの並行実行性能・スケーリングは、今回のGIL有効での測定からは判断できない。

## 全結果

| Benchmark | GIL PGO/LTO時間比 [95% CI] |
|---|---:|
| `2to3` | 1.0168 [1.0131, 1.0205] |
| `ascii85_large` | 0.7978 [0.7960, 0.8001] |
| `ascii85_small` | 0.9255 [0.9239, 0.9271] |
| `async_generators` | 0.9649 [0.9623, 0.9677] |
| `async_tree_cpu_io_mixed` | 0.9886 [0.9828, 0.9944] |
| `async_tree_cpu_io_mixed_tg` | 1.0093 [1.0086, 1.0100] |
| `async_tree_eager` | 0.9936 [0.9896, 0.9973] |
| `async_tree_eager_cpu_io_mixed` | 1.0028 [1.0001, 1.0055] |
| `async_tree_eager_cpu_io_mixed_tg` | 1.0004 [0.9981, 1.0033] |
| `async_tree_eager_io` | 1.0149 [1.0005, 1.0331] |
| `async_tree_eager_io_tg` | 1.0094 [0.9998, 1.0236] |
| `async_tree_eager_memoization` | 0.9851 [0.9772, 0.9916] |
| `async_tree_eager_memoization_tg` | 0.9982 [0.9889, 1.0115] |
| `async_tree_eager_tg` | 0.9863 [0.9832, 0.9892] |
| `async_tree_io` | 0.9770 [0.9586, 0.9972] |
| `async_tree_io_tg` | 0.9966 [0.9808, 1.0064] |
| `async_tree_memoization` | 0.9844 [0.9807, 0.9881] |
| `async_tree_memoization_tg` | 1.0050 [1.0036, 1.0064] |
| `async_tree_none` | 1.0330 [1.0249, 1.0449] |
| `async_tree_none_tg` | 0.9915 [0.9865, 0.9959] |
| `asyncio_tcp` | 1.0218 [1.0196, 1.0244] |
| `asyncio_tcp_ssl` | 1.0102 [1.0061, 1.0139] |
| `asyncio_websockets` | 1.0024 [0.9982, 1.0067] |
| `base16_large` | 0.8037 [0.8014, 0.8058] |
| `base16_small` | 0.8824 [0.8801, 0.8848] |
| `base32_large` | 1.0098 [1.0065, 1.0126] |
| `base32_small` | 1.0599 [1.0582, 1.0618] |
| `base64_large` | 0.9881 [0.9878, 0.9885] |
| `base64_small` | 1.0437 [1.0430, 1.0444] |
| `base85_large` | 0.9962 [0.9959, 0.9965] |
| `base85_small` | 1.0033 [0.9735, 1.0208] |
| `bench_mp_pool` | 0.6670 [0.5484, 0.8235] |
| `bench_thread_pool` | 1.0055 [0.9667, 1.0513] |
| `bpe_tokeniser` | 0.8501 [0.8471, 0.8530] |
| `chameleon` | 0.9408 [0.9365, 0.9454] |
| `chaos` | 0.9380 [0.9352, 0.9408] |
| `comprehensions` | 1.0282 [1.0255, 1.0309] |
| `connected_components` | 0.9921 [0.9847, 0.9979] |
| `coroutines` | 1.0234 [1.0194, 1.0272] |
| `coverage` | 1.0550 [1.0514, 1.0585] |
| `create_gc_cycles` | 1.0023 [0.9925, 1.0131] |
| `crypto_pyaes` | 0.9682 [0.9639, 0.9720] |
| `dask` | 1.0084 [0.9870, 1.0337] |
| `deepcopy` | 1.0278 [1.0182, 1.0389] |
| `deepcopy_memo` | 1.0584 [1.0025, 1.1187] |
| `deepcopy_reduce` | 0.9871 [0.9730, 0.9999] |
| `deltablue` | 0.9839 [0.9761, 0.9915] |
| `django_template` | 0.9702 [0.9635, 0.9767] |
| `docutils` | 0.9845 [0.9801, 0.9891] |
| `dulwich_log` | 1.0595 [1.0286, 1.0832] |
| `fannkuch` | 0.9156 [0.9098, 0.9218] |
| `float` | 1.0299 [1.0263, 1.0337] |
| `gc_traversal` | 1.0083 [0.9998, 1.0181] |
| `generators` | 0.9750 [0.9730, 0.9774] |
| `genshi_text` | 1.0185 [1.0052, 1.0391] |
| `genshi_xml` | 1.0754 [1.0481, 1.0984] |
| `go` | 0.8600 [0.8567, 0.8628] |
| `hexiom` | 0.7720 [0.7670, 0.7754] |
| `html5lib` | 0.9777 [0.9703, 0.9855] |
| `json_dumps` | 1.0721 [1.0701, 1.0741] |
| `json_loads` | 0.9913 [0.9859, 0.9971] |
| `logging_format` | 1.0765 [1.0628, 1.0921] |
| `logging_silent` | 0.9864 [0.9811, 0.9913] |
| `logging_simple` | 1.0266 [1.0099, 1.0435] |
| `mako` | 1.0089 [1.0073, 1.0105] |
| `many_optionals` | 1.0216 [1.0116, 1.0304] |
| `mdp` | 0.9695 [0.9617, 0.9774] |
| `meteor_contest` | 1.0128 [1.0113, 1.0141] |
| `nbody` | 0.9036 [0.8985, 0.9076] |
| `nqueens` | 1.0679 [1.0652, 1.0702] |
| `pathlib` | 1.0056 [0.9922, 1.0198] |
| `pickle` | 1.0229 [1.0173, 1.0278] |
| `pickle_dict` | 0.9995 [0.9930, 1.0068] |
| `pickle_list` | 1.0390 [1.0333, 1.0450] |
| `pickle_pure_python` | 1.0257 [1.0222, 1.0296] |
| `pidigits` | 1.0051 [1.0047, 1.0056] |
| `pprint_pformat` | 1.0613 [1.0392, 1.0822] |
| `pprint_safe_repr` | 1.0746 [1.0722, 1.0774] |
| `pyflate` | 0.9911 [0.9852, 0.9964] |
| `python_startup` | 1.0002 [0.9987, 1.0016] |
| `python_startup_no_site` | 1.0020 [1.0008, 1.0030] |
| `raytrace` | 0.9717 [0.9626, 0.9827] |
| `regex_compile` | 1.0113 [1.0075, 1.0148] |
| `regex_dna` | 0.9768 [0.9724, 0.9808] |
| `regex_effbot` | 0.9975 [0.9924, 1.0030] |
| `regex_v8` | 1.0134 [1.0124, 1.0144] |
| `richards` | 0.9029 [0.8890, 0.9142] |
| `richards_super` | 1.0271 [1.0207, 1.0322] |
| `scimark_fft` | 0.9418 [0.9363, 0.9501] |
| `scimark_lu` | 0.7531 [0.7519, 0.7543] |
| `scimark_monte_carlo` | 0.9213 [0.9178, 0.9250] |
| `scimark_sor` | 1.0549 [1.0516, 1.0580] |
| `scimark_sparse_mat_mult` | 0.8895 [0.8844, 0.8943] |
| `shortest_path` | 1.0017 [0.9972, 1.0057] |
| `spectral_norm` | 0.5823 [0.5647, 0.6154] |
| `sphinx` | 1.0155 [1.0045, 1.0265] |
| `sqlalchemy_declarative` | 0.9328 [0.9259, 0.9398] |
| `sqlalchemy_imperative` | 1.0211 [0.9923, 1.0493] |
| `sqlglot_v2_normalize` | 1.0784 [1.0692, 1.0870] |
| `sqlglot_v2_optimize` | 1.0408 [1.0352, 1.0496] |
| `sqlglot_v2_parse` | 1.0152 [0.9987, 1.0305] |
| `sqlglot_v2_transpile` | 1.0692 [1.0602, 1.0766] |
| `sqlite_synth` | 0.9953 [0.9923, 0.9985] |
| `subparsers` | 1.0361 [1.0283, 1.0432] |
| `sympy_expand` | 1.1448 [1.1421, 1.1475] |
| `sympy_integrate` | 0.9794 [0.9763, 0.9823] |
| `sympy_str` | 1.0082 [0.9997, 1.0164] |
| `sympy_sum` | 0.9663 [0.9587, 0.9736] |
| `telco` | 1.0012 [0.9931, 1.0085] |
| `tomli_loads` | 0.9705 [0.9602, 0.9799] |
| `tornado_http` | 1.0144 [1.0020, 1.0278] |
| `typing_runtime_protocols` | 1.0567 [1.0518, 1.0616] |
| `unpack_sequence` | 0.5497 [0.5468, 0.5526] |
| `unpickle` | 1.0119 [0.9943, 1.0320] |
| `unpickle_list` | 0.9675 [0.9638, 0.9714] |
| `unpickle_pure_python` | 0.9978 [0.9957, 0.9998] |
| `urlsafe_base64_small` | 0.9967 [0.9932, 1.0009] |
| `xdsl_constant_fold` | 0.9700 [0.9630, 0.9766] |
| `xml_etree_generate` | 0.8913 [0.8892, 0.8935] |
| `xml_etree_iterparse` | 0.9762 [0.9698, 0.9823] |
| `xml_etree_parse` | 0.9754 [0.9738, 0.9773] |
| `xml_etree_process` | 0.9863 [0.9816, 0.9912] |

## 未完了の仕様

| 構成 | Specification | 理由とログ |
|---|---|---|
| gil-pgo-lto | `fastapi` | 固定依存pydantic-coreのPyO3がPython 3.16非対応。[依存ログ](../jit-artifacts/pyperformance-gil-pgo-lto-20260917/dependencies/525b32a851ea2b56/wheel.log) |
| gil-pgo-lto | `networkx_k_core` | block 0 main: [timeout](../jit-artifacts/method-jit-mt6-gil/gil-pgo-lto/results/0-networkx_k_core-main.log); block 0 candidate: [timeout](../jit-artifacts/method-jit-mt6-gil/gil-pgo-lto/results/0-networkx_k_core-candidate.log); block 1 main: [timeout](../jit-artifacts/method-jit-mt6-gil/gil-pgo-lto/results/1-networkx_k_core-main.log); block 1 candidate: [timeout](../jit-artifacts/method-jit-mt6-gil/gil-pgo-lto/results/1-networkx_k_core-candidate.log) |

## 再現条件

3 worker × 5 warmup × 5 value、2 block（main/candidate順を反転）、最小測定時間0.1秒、独立校正。通常項目はCPU 2、thread/process poolは利用可能な複数CPU。ビルドや検証テストを測定に重ねず、system tuningは行っていない。NetworkXはworker 15秒・仕様60秒、その他はworker 60秒・仕様600秒。依存wheelとworkloadを両側で固定し、SQLAlchemyは同期SQLiteを使うためgreenletを省略した。

| 構成 | 側 | 実行ファイルSHA-256 |
|---|---|---|
| gil-pgo-lto | candidate | `806cb588e29a8ce1288b1b4df01964cfa806d2ac18f803031ddf07b46e78fb83` |
| gil-pgo-lto | main | `29f98fde43417b99bad02a6710ad55e55f343a574f8fff306932d1e75b010044` |

生データ・失敗ログ・依存・測定前後の同一性記録: `jit-artifacts/method-jit-mt6-gil/`。build manifestとcontroller: `jit-artifacts/regressions-20260919/mt6*`。

測定前後のソース・実行物・依存・workloadの同一性検証は成功。97仕様中95仕様が両側・両blockで完了し、122結果を比較した。384回の実行のうち380回成功、4回はNetworkX k-coreの15秒timeout。FastAPIの依存失敗は実行前から記録されている。測定コマンドの所要時間合計は約87.4分。controllerの終了値1はこれら未完了仕様によるもので、集計処理は成功している。

コミット済みソースからfresh buildした。PGO学習の最初の試行はsandboxでsocket作成を拒否されたため、そのプロファイルを別保存して学習全体を通常環境で再実行した。最終PGOには成功した学習のみを使用。学習43モジュール・10,632テスト、最終GILバイナリのJIT関連578テストが成功した。

再集計: `python3 jit-artifacts/regressions-20260919/analyze_mt6_gil.py jit-artifacts/method-jit-mt6-gil`、続いて `python3 jit-artifacts/regressions-20260919/report_mt6_full.py`。測定を再試行して標本を選び直していない。
