# 夜間pyperformance比較レポート（2026-09-19）

FTでは完了121 resultの実行時間が幾何平均で **8.99%短縮**、GIL・PGO・full LTOありでは
完了105 resultで **1.69%短縮**した。しかし、**リグレッション解消・安定性確保は未達成**。
`regex_compile` はFTで1.745倍、GILで3.228倍に悪化した。FT Daskのsegfaultは再発し、
GIL側にはmain・candidate双方のクラッシュもある。平均が改善したことと、個別の回帰や
失敗が解消したことは区別する。

入力は `jit-artifacts/pyperformance-four-way-overnight/`。
今回行ったのは既存JSON・ログの解析、同一性検証、スタックのアドレス解決とレポート作成。
追加のベンチマーク実行・再ビルド・runtime/測定ハーネスの変更は行っていない。
旧結果と[前回レポート](pyperformance_four_way_report.md)は保存している。

## 完了状況と全体の傾向

時間比は **candidate/main**。以下の変化率は負が実行時間短縮、正が増加。
速度倍率の百分率ではない。2%は整理用の効果量の区切りで、有意差・同等性の判定ではない。

| 構成 | 完了仕様/選択仕様 | 比較result | 時間比の幾何平均 | 時間変化 | 2%以上短縮 | ±2%未満 | 2%以上増加 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FT・PGO/LTOなし | 94/97 | 121 | 0.910105 | -8.99% | 82 | 28 | 11 |
| GIL・PGO/full LTO | 78/97 | 105 | 0.983138 | -1.69% | 32 | 50 | 23 |

集計対象はmain/candidateの両ブロックが成功した仕様のみ。失敗した仕様について、成功した
ブロックや一部workerだけを主集計に採用しない。base64やSciMarkなどの複数resultはそれぞれ
等重みなので、仕様数とresult数は異なる。欠落を含めた全97仕様の総合性能ではない。

FTの呼び出しは384回中379回成功、GILは384回中353回成功。両方とも最後まで実行され、
測定終了時と今回の再検証で入力の同一性が確認できた。終了コード1は失敗・未対応項目が
あるためで、ランナー全体が途中で止まったわけではない。

| 補助集計 | FT | GIL・PGO/full LTO |
|---|---:|---:|
| result比の中央値 | 0.940874 | 0.997525 |
| 仕様ごとに等重みの幾何平均 | 0.907314 | 0.984989 |
| 両構成で共通の104 resultの幾何平均 | 0.901929 | 0.982952 |
| regex_compileを除く感度分析 | 0.905180 | 0.971962 |
| spectral_normを除く感度分析 | 0.917300 | 0.988526 |
| spectral_norm・unpack_sequence・bench_mp_poolを除く感度分析 | 0.918532 | 1.004947 |

感度分析は主集計の置き換えではない。FTの改善は1件だけには依存しない。
GILでは最大級の改善3件を除くと平均は約0.49%悪化し、result比の中央値もほぼ1。
一部の大きな改善に加え、広い範囲の小差と23件の2%以上の悪化が共存している。

## 改善と、以前の修正の到達点

代表的な項目を示す。括弧内は時間比。

| Result | FT | GIL・PGO/full LTO |
|---|---:|---:|
| spectral_norm | -64.62% (0.3538) | -44.31% (0.5569) |
| unpack_sequence | -29.92% (0.7008) | -55.51% (0.4449) |
| richards_super | -61.20% (0.3880) | +2.30% (1.0230) |
| richards | -60.21% (0.3979) | -2.66% (0.9734) |
| nbody | -39.36% (0.6064) | +3.99% (1.0399) |
| scimark_lu | -28.92% (0.7108) | -1.32% (0.9868) |
| float | -23.46% (0.7654) | -2.39% (0.9761) |
| bench_mp_pool | +2.49% (1.0249) | -59.09% (0.4091) |
| bench_thread_pool | +2.07% (1.0207) | -12.40% (0.8760) |
| deepcopy | -5.91% (0.9409) | -2.00% (0.9800) |
| deepcopy_memo | -22.98% (0.7702) | -3.57% (0.9643) |
| deepcopy_reduce | -2.65% (0.9735) | -3.78% (0.9622) |
| pprint_pformat | -16.54% (0.8346) | +0.70% (1.0070) |
| logging_format | -15.28% (0.8472) | +2.28% (1.0228) |
| base64_small | -14.50% (0.8550) | -2.77% (0.9723) |
| chaos | -16.58% (0.8342) | -2.81% (0.9719) |
| go | -14.02% (0.8598) | -6.73% (0.9327) |
| hexiom | -14.56% (0.8544) | -13.46% (0.8654) |
| raytrace | -14.66% (0.8534) | -8.10% (0.9190) |
| bpe_tokeniser | -16.17% (0.8383) | -12.70% (0.8730) |
| sqlalchemy_declarative | +2.19% (1.0219) | -5.61% (0.9439) |
| sqlalchemy_imperative | -20.92% (0.7908) | -14.88% (0.8512) |
| generators | +0.30% (1.0030) | -0.36% (0.9964) |

FTでは数値計算だけでなく、テンプレート、パーサー、logging/pprint、deepcopyにも改善がある。
GILでは `unpack_sequence`、`spectral_norm`、SQLAlchemy、Hexiom、BPE、Goなどが改善した。
`concurrent_imap` の改善にはGIL取得待ちの修正が含まれるため、生成JITコードだけの効果とは扱わない。
また、pyperfの6 workerと、benchmark内部のPool/ThreadPoolの並列度2は別の設定である。
GILのbench_thread_poolは両ブロックで改善したが、時間比は0.9696 / 0.7915と差が大きい。
平均12.40%短縮という効果量の再現性は、追加の反復で確認する必要がある。

`richards_super` はFTで61.20%短縮する一方、GILでは2.30%悪化した。Goは両構成でmainより速い。
`btree` はこのpyperformanceの97仕様に含まれていないため、今回の結果からは評価できない。
greenletを省いたSQLAlchemy 1.4.19の両仕様は4構成すべて完了したが、declarativeのFTは
2.19%悪化が残る。

### 修正前との比較

前回の `pyperformance-four-way-current` と今回の、それぞれのcandidate/main比を示す。
同じmainバイナリを使用し、共通仕様のbenchmarkスクリプトと過去の結果SHAも照合した。
候補は再ビルドされ、今回はfaulthandlerも有効なため、変更1件だけの因果効果を表す実験ではない。

| Result | FT 前回 → 今回 | GIL 前回 → 今回 |
|---|---:|---:|
| unpack_sequence | 1.3622 → 0.7008 | 0.9998 → 0.4449 |
| deepcopy | 0.9969 → 0.9409 | 1.0752 → 0.9800 |
| deepcopy_memo | 0.8932 → 0.7702 | 1.1680 → 0.9643 |
| deepcopy_reduce | 1.0543 → 0.9735 | 1.0616 → 0.9622 |
| pprint_pformat | 0.9714 → 0.8346 | 1.1837 → 1.0070 |
| pprint_safe_repr | 0.9683 → 0.8377 | 1.1800 → 1.0115 |
| logging_format | 0.9962 → 0.8472 | 1.1685 → 1.0228 |
| logging_simple | 0.9721 → 0.8462 | 1.1383 → 1.0076 |
| base64_small | 0.9445 → 0.8550 | 1.1132 → 0.9723 |
| chaos | 0.9143 → 0.8342 | 1.0601 → 0.9719 |
| generators | 1.0365 → 1.0030 | 0.9978 → 0.9964 |
| telco | 0.9352 → 0.8916 | 1.1415 → 1.1105 |
| regex_compile | 0.8429 → 1.7453 | 0.9703 → 3.2283 |
| regex_effbot | 0.9956 → 1.0521 | 1.0188 → 1.0671 |
| richards_super | 0.3833 → 0.3880 | 0.9958 → 1.0230 |
| go | 0.8502 → 0.8598 | 0.9178 → 0.9327 |
| pickle_dict | 1.0128 → 0.9999 | 1.1252 → 1.0768 |
| pickle_list | 0.9892 → 0.9689 | 1.0586 → 1.0963 |

FT・PGO/LTOなしの前回と今回の共通115 resultでは、幾何平均は0.924020 → 0.905601。

GIL・PGO/full LTOの前回と今回の共通99 resultでは、幾何平均は1.006663 → 0.990662。

以前の `unpack_sequence`、deepcopy、pprint、loggingの大きな悪化は縮小または反転した。
ただし、regex_compileは新たな大幅悪化であり、GILのpickle_listとrichards_superも前回より悪化している。

## 残っているリグレッション

全生データから、各workerの5 valuesの平均を求め、ブロック内で6 workerを等重みで集計した。
ブロックごとのcandidate/main比の幾何平均が主推定値。95%区間は各ブロック・各側のworkerを
独立に再抽出する4,000回のpercentile bootstrap（seed 20260919）。架空のworker間ペアは作らない。
区間はこの固定ビルド・固定ブロック内のばらつきだけを表し、再ビルド・別CPU・時間帯の影響、
多数項目を比較した選択効果を含まない。多重比較補正も行っていない。

### FT・PGO/LTOなし

| Result | 時間増加 | 時間比 | 95%区間 | 第1/第2ブロック比 |
|---|---:|---:|---:|---:|
| regex_compile | +74.53% | 1.7453 | 1.7383–1.7528 | 1.7446 / 1.7460 |
| regex_effbot | +5.21% | 1.0521 | 1.0501–1.0542 | 1.0529 / 1.0514 |
| asyncio_tcp | +4.79% | 1.0479 | 1.0234–1.0809 | 1.0535 / 1.0424 |
| regex_v8 | +4.58% | 1.0458 | 1.0449–1.0466 | 1.0457 / 1.0459 |
| docutils | +4.19% | 1.0419 | 1.0352–1.0489 | 1.0450 / 1.0388 |
| sympy_sum | +3.80% | 1.0380 | 1.0336–1.0426 | 1.0398 / 1.0362 |
| bench_mp_pool | +2.49% | 1.0249 | 1.0036–1.0478 | 1.0249 / 1.0249 |
| sqlalchemy_declarative | +2.19% | 1.0219 | 1.0189–1.0251 | 1.0222 / 1.0217 |
| unpickle | +2.17% | 1.0217 | 0.9888–1.0785 | 1.0508 / 0.9935 |
| shortest_path | +2.08% | 1.0208 | 0.9770–1.0639 | 0.9760 / 1.0678 |
| bench_thread_pool | +2.07% | 1.0207 | 1.0075–1.0330 | 1.0234 / 1.0180 |

### GIL・PGO/full LTO

| Result | 時間増加 | 時間比 | 95%区間 | 第1/第2ブロック比 |
|---|---:|---:|---:|---:|
| regex_compile | +222.83% | 3.2283 | 3.1987–3.2548 | 3.2568 / 3.2000 |
| telco | +11.05% | 1.1105 | 1.0903–1.1348 | 1.1046 / 1.1165 |
| genshi_xml | +11.04% | 1.1104 | 1.1002–1.1213 | 1.1114 / 1.1094 |
| pickle_list | +9.63% | 1.0963 | 1.0890–1.1047 | 1.0995 / 1.0931 |
| many_optionals | +9.52% | 1.0952 | 1.0867–1.1058 | 1.1001 / 1.0903 |
| pickle_dict | +7.68% | 1.0768 | 1.0726–1.0810 | 1.0809 / 1.0727 |
| base16_small | +7.08% | 1.0708 | 1.0662–1.0750 | 1.0725 / 1.0690 |
| regex_effbot | +6.71% | 1.0671 | 1.0588–1.0749 | 1.0735 / 1.0607 |
| genshi_text | +6.62% | 1.0662 | 1.0551–1.0769 | 1.0647 / 1.0678 |
| urlsafe_base64_small | +5.78% | 1.0578 | 1.0385–1.0728 | 1.0579 / 1.0578 |
| sympy_sum | +5.30% | 1.0530 | 1.0414–1.0641 | 1.0496 / 1.0565 |
| gc_traversal | +5.01% | 1.0501 | 1.0435–1.0571 | 1.0556 / 1.0447 |
| dulwich_log | +4.67% | 1.0467 | 1.0299–1.0649 | 1.0417 / 1.0518 |
| sqlglot_v2_transpile | +4.57% | 1.0457 | 1.0405–1.0523 | 1.0433 / 1.0482 |
| nbody | +3.99% | 1.0399 | 1.0344–1.0458 | 1.0391 / 1.0406 |
| meteor_contest | +3.81% | 1.0381 | 1.0363–1.0400 | 1.0385 / 1.0377 |
| pickle_pure_python | +3.72% | 1.0372 | 1.0334–1.0421 | 1.0306 / 1.0439 |
| fannkuch | +3.41% | 1.0341 | 1.0321–1.0366 | 1.0338 / 1.0345 |
| sqlglot_v2_optimize | +3.25% | 1.0325 | 1.0260–1.0402 | 1.0343 / 1.0308 |
| async_generators | +2.68% | 1.0268 | 1.0244–1.0294 | 1.0262 / 1.0274 |
| richards_super | +2.30% | 1.0230 | 1.0197–1.0261 | 1.0227 / 1.0233 |
| logging_format | +2.28% | 1.0228 | 1.0159–1.0296 | 1.0204 / 1.0252 |
| sympy_expand | +2.08% | 1.0208 | 1.0095–1.0326 | 1.0157 / 1.0260 |

FTの11件のうち、unpickleとshortest_pathはブロック間で方向が逆転し、区間も1をまたぐ。
この2件は安定した悪化と断定しない。他の9件は両順序で悪化し、区間も1を上回る。
GILの23件はすべて両順序で悪化し、この条件付き区間も1を上回った。

### 最優先の性能問題: regex_compile

| 構成 | mainの平均時間 | candidateの平均時間 | 時間比 | 前回の時間比 |
|---|---:|---:|---:|---:|
| FT・PGO/LTOなし | 117.527 ms | 205.121 ms | 1.7453 | 0.8429 |
| GIL・PGO/full LTO | 74.590 ms | 240.801 ms | 3.2283 | 0.9703 |

両ブロックで再現し、worker中央値を使っても大幅悪化は残る。前回からのmainの平均時間変化は
FT約−0.02%、GIL約−0.64%で、main側の大きな時間変動ではこの差を説明できない。
この仕様は正規表現を採取し、各回 `re.purge()` して `re.compile()` を繰り返す。
regex_dna/regex_v8の検索処理と同じ負荷ではない。現在のログだけでは、採取された正規表現の数、
JITコンパイル頻度、生成コード、正規表現コンパイラのどこに差があるかまでは特定できない。

## 失敗・未対応とクラッシュの手掛かり

### FT Dask: 再発、f_code参照でsegfault

第1ブロックの両側と第2ブロックのmainは成功したが、第2ブロックのcandidateがSIGSEGV。
したがってFT Daskは主性能集計から除外した。準備時に見つかった単発失敗は解消していない。

今回のfaulthandlerログでは `distributed.worker.trigger_profile()` が `sys._current_frames()` で
取得した別スレッドのframeを調べ、`distributed/profile.py:62` の `frame.f_code` 参照中に落ちている。
固定バイナリのアドレスを解決すると `frame_code_get` → `PyFrame_GetCode` → `Py_INCREF` に対応する。
次の調査では他スレッドのframe/codeの寿命と、JIT無効化・frame参照の関係を確認する。
これは停止位置の特定であり、不正な参照が生じた根本原因の特定ではない。

[Dask失敗ログ](../jit-artifacts/pyperformance-four-way-overnight/ft/results/1-dask-candidate.log)

### GIL: 第2ブロックでmainにもクラッシュ

SIGSEGVはcandidate 11呼び出し、main 10呼び出しの計21回。18回にはGC中であることが記録され、
アドレス解決後のスタックにも `visit_decref`、`deduce_unreachable`、`gc_collect_main`、
container/Task/generatorのtraverse処理が現れる。async_tree群とdocutilsに集中し、すべて第2ブロック。
同じ仕様の第1ブロックは成功している。mainでも落ちているため、これをすべてmethod JIT固有の
回帰と決めつけることはできない。逆に、mainにもあることを理由にcandidateの不具合を否定もできない。

ほかにcandidateのasync_tree_memoizationで `module_globals must be a dict, not list` のTypeError、
asyncio_tcp_sslの両側で `DECRYPTION_FAILED_OR_BAD_RECORD_MAC` のSSLエラーが発生した。
GC停止位置は原因そのものとは限らず、所有権やメモリ状態などの切り分けが必要。
今回のログから共有原因・環境要因・JITの寄与を確定することはできない。

[mainのasync_treeログ](../jit-artifacts/pyperformance-four-way-overnight/gil-pgo-lto/results/1-async_tree_cpu_io_mixed-main.log)、
[candidateのasync_treeログ](../jit-artifacts/pyperformance-four-way-overnight/gil-pgo-lto/results/1-async_tree_cpu_io_mixed-candidate.log)、
[mainのdocutilsログ](../jit-artifacts/pyperformance-four-way-overnight/gil-pgo-lto/results/1-docutils-main.log)、
[candidateのdocutilsログ](../jit-artifacts/pyperformance-four-way-overnight/gil-pgo-lto/results/1-docutils-candidate.log)

### 未完了仕様の全一覧

各セルはmain / candidate。ブロック番号は1から数える（ファイル名の0/1に対応）。
T/Oはタイムアウト。失敗した呼び出しの詳細ログは各構成の `results/` に保存されている。

#### FT・PGO/LTOなし

| 仕様 | 第1ブロック main / candidate | 第2ブロック main / candidate |
|---|---|---|
| dask | 成功 / 成功 | 成功 / SIGSEGV |
| fastapi | 未準備 / 未準備 | 未準備 / 未準備 |
| networkx_k_core | T/O / T/O | T/O / T/O |

#### GIL・PGO/full LTO

| 仕様 | 第1ブロック main / candidate | 第2ブロック main / candidate |
|---|---|---|
| async_tree_cpu_io_mixed | 成功 / 成功 | SIGSEGV / SIGSEGV |
| async_tree_cpu_io_mixed_tg | 成功 / 成功 | SIGSEGV / SIGSEGV |
| async_tree_eager | 成功 / 成功 | 成功 / SIGSEGV |
| async_tree_eager_cpu_io_mixed | 成功 / 成功 | 成功 / SIGSEGV |
| async_tree_eager_cpu_io_mixed_tg | 成功 / 成功 | SIGSEGV / SIGSEGV |
| async_tree_eager_io | 成功 / 成功 | T/O / SIGSEGV |
| async_tree_eager_io_tg | 成功 / 成功 | SIGSEGV / 成功 |
| async_tree_eager_memoization | 成功 / 成功 | SIGSEGV / 成功 |
| async_tree_eager_memoization_tg | 成功 / 成功 | T/O / SIGSEGV |
| async_tree_eager_tg | 成功 / 成功 | 成功 / SIGSEGV |
| async_tree_io_tg | 成功 / 成功 | SIGSEGV / SIGSEGV |
| async_tree_memoization | 成功 / 成功 | SIGSEGV / TypeError |
| async_tree_memoization_tg | 成功 / 成功 | SIGSEGV / SIGSEGV |
| async_tree_tg | 成功 / 成功 | SIGSEGV / 成功 |
| asyncio_tcp_ssl | 成功 / 成功 | SSLエラー / SSLエラー |
| docutils | 成功 / 成功 | SIGSEGV / SIGSEGV |
| fastapi | 未準備 / 未準備 | 未準備 / 未準備 |
| networkx | 成功 / 成功 | 成功 / T/O |
| networkx_k_core | T/O / T/O | T/O / T/O |

FastAPIは従来と同じpydantic-core/PyO3のPython 3.16未対応で未準備。
NetworkX k-coreは4構成・両ブロックすべて約18秒で打ち切られ、15秒worker上限は機能している。
GILのshortest_pathは第2ブロックcandidateが180秒の仕様上限に到達した。
これらの時間制限と、今回のSIGSEGV・Python例外は区別している。

WebSocket、Genshi、concurrent_imap、同期SQLAlchemyは今回は両側・両ブロック完了。
cloudpickleの互換性問題によるimportエラーも再発しておらず、Daskの今回の失敗は別のものだった。

## 比較条件・検証・解釈の範囲

- main: `d95f29589e03603aa13d8ca9d4f817dce77d357c` ＋ LLVM 21互換パッチ。
- candidate runtime: `718d2ff2ef9705a8cdbfa7b345038f5b484a7343`（採用版V26）。
- 実行ハーネスと準備レポート: `08a1b60bdfc`。
- FTはGIL無効・PGO/LTOなし。GIL版はPGO/full LTOあり。GCC 13.3.0、`-O3`、frame pointerあり。
- GIL PGO学習はJIT無効・seed 0・cold private pycache・標準43テスト。bootstrap profileは分離済み。
- pyperformance 1.14.0、pyperf 2.10.0。各仕様2ブロック、各側6 worker、各worker5 warmup/5 values、min-time 0.1秒。
- loop数は各側で独立に校正し、pyperfが1 loop当たりへ正規化した値を比較。regex_compileはFTが両側1、GILはmain 2 / candidate 1。校正・warmupの値は主集計に含めない。
- CPUはIntel Core i5-12450H。通常CPU 2（物理core 1）、並列仕様はCPU 0–11。各仕様のmain/candidate順を第2ブロックで反転。
- worker記録はintel_pstate・powersave governor・turbo、ASLR有効。Linux 6.8.0-134、glibc 2.39。
- FTを先に、GILを後に測定している。GIL対FTそのものは交互に測った比較ではない。
- 全構成 `PYTHON_JIT=1`、`PYTHONHASHSEED=0`、`PYTHONFAULTHANDLER=1`。成功JSONのworkerで実際のFT/GIL/JIT要求・faulthandler状態を確認した。
- **mainのFTはJIT有効フラグが立ってもexecutorを生成しない。FTはmainのTier 1インタプリタ対method JITの比較である。**
- candidate FTのDask（成功ブロック）、ThreadPool、TornadoではJIT停止を観測した。開始・終了時だけの検査なので、途中の全状態遷移や常時JIT実行を保証しない。
- native依存wheelは各ABIのmain向けビルドを両側で共用。GILとFTでnative wheelは異なる。pure wheelとworkloadは共通。
- cloudpickle/Genshi/WebSocketには準備時の互換パッチを両側へ同じように適用。SQLAlchemy 1.4.19はユーザー指定でgreenletを省略。
- `_decimal` は比較する4ビルドで欠けており、telcoはPython版decimalの負荷。C版decimalを備えた通常のPythonへそのまま一般化しない。
- 遅いworkerや悪化した項目を削除していない。pyperfの安定性警告も残している。固定ビルド1組の結果であり、他CPUや再ビルドへの再現性は未評価。

| 構成 | 実行物SHA-256 |
|---|---|
| FT・PGO/LTOなし / main | `90c095bd8ba8a4e9476ba41b6143cb80f8264cab93241f927b11fc48121b67c9` |
| FT・PGO/LTOなし / candidate | `5483c5085c6a50e0891e864305261d0f7c82d5dad7619d5b5a403bb6947d8fb0` |
| GIL・PGO/full LTO / main | `dd63a277fd879d2f0993655c0502ee26f98bf37656890ae30fdeedb734287c49` |
| GIL・PGO/full LTO / candidate | `912a24825e847ef11d469fab72b566c45bb656d765e59cfb7bead6c2c962877c` |

FTのworker時刻は2026-09-18 15:45:04–18:38:01、GILは18:38:24–21:05:30（ローカル設定はUTC）。
各呼び出しの所要時間合計はFT約2.88時間、GIL約2.45時間。全体で約5時間20分の記録。

生JSONのSHAとstate内の各result平均を再計算して一致を確認し、ビルド・標準拡張・標準ライブラリ・
依存・workload・runnerの同一性も再検証した。候補のFT/PGOソース同一性は準備時の記録にある。
検証した範囲は、保存済みの入力・実行物・値の整合性であり、クラッシュ原因がないという保証ではない。

## 次に優先する調査

1. FT Daskの他スレッドframe参照と、GIL両側のGC中クラッシュを分けて再現・切り分ける。
   GIL側は同じ入力・回数でJIT無効の対照を取り、mainにも共通する問題を特定する。
2. regex_compileの採取入力と仕事量を確認し、JITコンパイル・無効化・生成コード・正規表現コンパイルの内訳を調べる。
   前回との差分を段階的に比較して、3.23倍の悪化を導入した変更を絞る。
3. GILのtelco、Genshi、argparse、pickle群、およびrichards_superの残る悪化を調べる。
   FTではregex群、asyncio_tcp、docutils、sympy_sum、SQLAlchemy declarativeを優先する。

このレポートでは調査候補までを示し、追加測定や修正は実行していない。

## 証拠と全result一覧

- [FTの元集計](../jit-artifacts/pyperformance-four-way-overnight/ft/compare.md)、[GILの元集計](../jit-artifacts/pyperformance-four-way-overnight/gil-pgo-lto/compare.md)
- [解析JSON](../jit-artifacts/pyperformance-overnight-analysis-20260919/analysis.json): 全result、区間、worker値、感度分析、前回比、入力SHA。
- [失敗スタックの整理](../jit-artifacts/pyperformance-overnight-analysis-20260919/failure-stacks.json)
- [再集計スクリプト](../jit-artifacts/pyperformance-overnight-analysis-20260919/analyze.py)
- [準備・修正の記録](pyperformance_fixes_report.md)

各欄は時間変化と時間比。「未完了」は主比較を成立させる4呼び出しがそろわない項目。

| Result | FT | GIL・PGO/full LTO |
|---|---:|---:|
| 2to3 | +0.87% (1.0087) | +0.51% (1.0051) |
| ascii85_large | +1.03% (1.0103) | -0.05% (0.9995) |
| ascii85_small | -3.89% (0.9611) | -1.79% (0.9821) |
| async_generators | -1.25% (0.9875) | +2.68% (1.0268) |
| async_tree_cpu_io_mixed | -4.14% (0.9586) | 未完了 |
| async_tree_cpu_io_mixed_tg | -1.38% (0.9862) | 未完了 |
| async_tree_eager | -7.84% (0.9216) | 未完了 |
| async_tree_eager_cpu_io_mixed | -2.99% (0.9701) | 未完了 |
| async_tree_eager_cpu_io_mixed_tg | -2.28% (0.9772) | 未完了 |
| async_tree_eager_io | -6.97% (0.9303) | 未完了 |
| async_tree_eager_io_tg | -5.46% (0.9454) | 未完了 |
| async_tree_eager_memoization | -5.12% (0.9488) | 未完了 |
| async_tree_eager_memoization_tg | -7.51% (0.9249) | 未完了 |
| async_tree_eager_tg | -6.69% (0.9331) | 未完了 |
| async_tree_io | -8.30% (0.9170) | -0.56% (0.9944) |
| async_tree_io_tg | -6.27% (0.9373) | 未完了 |
| async_tree_memoization | -8.72% (0.9128) | 未完了 |
| async_tree_memoization_tg | -2.86% (0.9714) | 未完了 |
| async_tree_none | -11.02% (0.8898) | -2.86% (0.9714) |
| async_tree_none_tg | -1.81% (0.9819) | 未完了 |
| asyncio_tcp | +4.79% (1.0479) | +0.62% (1.0062) |
| asyncio_tcp_ssl | -0.16% (0.9984) | 未完了 |
| asyncio_websockets | +0.07% (1.0007) | -0.22% (0.9978) |
| base16_large | -6.50% (0.9350) | -1.18% (0.9882) |
| base16_small | -11.68% (0.8832) | +7.08% (1.0708) |
| base32_large | -0.53% (0.9947) | +0.08% (1.0008) |
| base32_small | -11.27% (0.8873) | -1.80% (0.9820) |
| base64_large | -0.03% (0.9997) | -1.00% (0.9900) |
| base64_small | -14.50% (0.8550) | -2.77% (0.9723) |
| base85_large | -2.06% (0.9794) | +0.02% (1.0002) |
| base85_small | -3.40% (0.9660) | -0.04% (0.9996) |
| bench_mp_pool | +2.49% (1.0249) | -59.09% (0.4091) |
| bench_thread_pool | +2.07% (1.0207) | -12.40% (0.8760) |
| bpe_tokeniser | -16.17% (0.8383) | -12.70% (0.8730) |
| chameleon | -12.34% (0.8766) | -4.93% (0.9507) |
| chaos | -16.58% (0.8342) | -2.81% (0.9719) |
| comprehensions | -15.93% (0.8407) | -6.21% (0.9379) |
| connected_components | -4.58% (0.9542) | +1.71% (1.0171) |
| coroutines | -4.45% (0.9555) | -1.20% (0.9880) |
| coverage | +1.07% (1.0107) | -0.59% (0.9941) |
| create_gc_cycles | -0.50% (0.9950) | +1.29% (1.0129) |
| crypto_pyaes | -8.56% (0.9144) | -1.74% (0.9826) |
| dask | 未完了 | +0.27% (1.0027) |
| deepcopy | -5.91% (0.9409) | -2.00% (0.9800) |
| deepcopy_memo | -22.98% (0.7702) | -3.57% (0.9643) |
| deepcopy_reduce | -2.65% (0.9735) | -3.78% (0.9622) |
| deltablue | -20.71% (0.7929) | -7.64% (0.9236) |
| django_template | -10.00% (0.9000) | -5.04% (0.9496) |
| docutils | +4.19% (1.0419) | 未完了 |
| dulwich_log | -17.34% (0.8266) | +4.67% (1.0467) |
| fannkuch | -13.43% (0.8657) | +3.41% (1.0341) |
| float | -23.46% (0.7654) | -2.39% (0.9761) |
| gc_traversal | +1.22% (1.0122) | +5.01% (1.0501) |
| generators | +0.30% (1.0030) | -0.36% (0.9964) |
| genshi_text | -4.07% (0.9593) | +6.62% (1.0662) |
| genshi_xml | -0.02% (0.9998) | +11.04% (1.1104) |
| go | -14.02% (0.8598) | -6.73% (0.9327) |
| hexiom | -14.56% (0.8544) | -13.46% (0.8654) |
| html5lib | -18.24% (0.8176) | -3.11% (0.9689) |
| json_dumps | -6.90% (0.9310) | -1.60% (0.9840) |
| json_loads | -0.00% (1.0000) | -0.50% (0.9950) |
| logging_format | -15.28% (0.8472) | +2.28% (1.0228) |
| logging_silent | -9.99% (0.9001) | -8.33% (0.9167) |
| logging_simple | -15.38% (0.8462) | +0.76% (1.0076) |
| mako | -11.33% (0.8867) | -0.91% (0.9909) |
| many_optionals | +0.42% (1.0042) | +9.52% (1.0952) |
| mdp | -3.40% (0.9660) | -4.09% (0.9591) |
| meteor_contest | -1.01% (0.9899) | +3.81% (1.0381) |
| nbody | -39.36% (0.6064) | +3.99% (1.0399) |
| nqueens | -10.82% (0.8918) | +0.30% (1.0030) |
| pathlib | -3.41% (0.9659) | +0.83% (1.0083) |
| pickle | +0.32% (1.0032) | -3.82% (0.9618) |
| pickle_dict | -0.01% (0.9999) | +7.68% (1.0768) |
| pickle_list | -3.11% (0.9689) | +9.63% (1.0963) |
| pickle_pure_python | -13.12% (0.8688) | +3.72% (1.0372) |
| pidigits | -0.10% (0.9990) | -0.03% (0.9997) |
| pprint_pformat | -16.54% (0.8346) | +0.70% (1.0070) |
| pprint_safe_repr | -16.23% (0.8377) | +1.15% (1.0115) |
| pyflate | -18.58% (0.8142) | -1.30% (0.9870) |
| python_startup | +0.57% (1.0057) | +0.71% (1.0071) |
| python_startup_no_site | +0.37% (1.0037) | +1.32% (1.0132) |
| raytrace | -14.66% (0.8534) | -8.10% (0.9190) |
| regex_compile | +74.53% (1.7453) | +222.83% (3.2283) |
| regex_dna | +1.92% (1.0192) | +0.77% (1.0077) |
| regex_effbot | +5.21% (1.0521) | +6.71% (1.0671) |
| regex_v8 | +4.58% (1.0458) | +1.02% (1.0102) |
| richards | -60.21% (0.3979) | -2.66% (0.9734) |
| richards_super | -61.20% (0.3880) | +2.30% (1.0230) |
| scimark_fft | -11.66% (0.8834) | -0.71% (0.9929) |
| scimark_lu | -28.92% (0.7108) | -1.32% (0.9868) |
| scimark_monte_carlo | -14.64% (0.8536) | -2.08% (0.9792) |
| scimark_sor | -16.89% (0.8311) | +0.29% (1.0029) |
| scimark_sparse_mat_mult | -14.23% (0.8577) | -5.56% (0.9444) |
| shortest_path | +2.08% (1.0208) | 未完了 |
| spectral_norm | -64.62% (0.3538) | -44.31% (0.5569) |
| sphinx | +1.27% (1.0127) | +1.08% (1.0108) |
| sqlalchemy_declarative | +2.19% (1.0219) | -5.61% (0.9439) |
| sqlalchemy_imperative | -20.92% (0.7908) | -14.88% (0.8512) |
| sqlglot_v2_normalize | -6.52% (0.9348) | +1.25% (1.0125) |
| sqlglot_v2_optimize | -3.72% (0.9628) | +3.25% (1.0325) |
| sqlglot_v2_parse | -10.42% (0.8958) | +1.21% (1.0121) |
| sqlglot_v2_transpile | -4.93% (0.9507) | +4.57% (1.0457) |
| sqlite_synth | -5.34% (0.9466) | -0.54% (0.9946) |
| subparsers | -7.91% (0.9209) | -3.96% (0.9604) |
| sympy_expand | -10.38% (0.8962) | +2.08% (1.0208) |
| sympy_integrate | -0.12% (0.9988) | -0.48% (0.9952) |
| sympy_str | -4.88% (0.9512) | -1.36% (0.9864) |
| sympy_sum | +3.80% (1.0380) | +5.30% (1.0530) |
| telco | -10.84% (0.8916) | +11.05% (1.1105) |
| tomli_loads | -14.68% (0.8532) | -4.28% (0.9572) |
| tornado_http | +0.14% (1.0014) | +0.44% (1.0044) |
| typing_runtime_protocols | -9.02% (0.9098) | -1.00% (0.9900) |
| unpack_sequence | -29.92% (0.7008) | -55.51% (0.4449) |
| unpickle | +2.17% (1.0217) | +1.83% (1.0183) |
| unpickle_list | +0.71% (1.0071) | +0.72% (1.0072) |
| unpickle_pure_python | -22.68% (0.7732) | -8.52% (0.9148) |
| urlsafe_base64_small | -6.96% (0.9304) | +5.78% (1.0578) |
| xdsl_constant_fold | -8.70% (0.9130) | -0.83% (0.9917) |
| xml_etree_generate | -6.27% (0.9373) | -11.78% (0.8822) |
| xml_etree_iterparse | -2.33% (0.9767) | +1.80% (1.0180) |
| xml_etree_parse | +0.24% (1.0024) | -0.25% (0.9975) |
| xml_etree_process | -6.82% (0.9318) | -0.17% (0.9983) |
