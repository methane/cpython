# main / method-JIT: 4構成のpyperformance実測結果

GILなしでは広い改善があるが、リグレッションも残る。GIL・PGO・full LTOありでは、
一部の大きな改善と、多数の悪化が同時に見られる。「リグレッションなし」とは言えない。
特にFTの `unpack_sequence`、GILありのpprint・logging・deepcopyと、候補側だけで
失敗した並列処理を優先して調査する必要がある。

入力は `jit-artifacts/pyperformance-four-way-current/`。
mainは `d95f29589e03603aa13d8ca9d4f817dce77d357c` とLLVM 21互換パッチ、
method-JITは `15d10bd6f03` にコミットした実装を含む既存ビルド。
今回の解析では再ビルド、ベンチマークの追加実行、ランタイムや測定ハーネスの変更はしていない。

9月18日の実装調査による補足: このmainのFTビルドは
`_PyOptimizer_Optimize()` が常に0を返し、executorを生成しない。
`PYTHON_JIT=1` / `sys._jit.is_enabled()` だけではJIT実行を意味しない。
FTの数値はmainのインタプリタ対method JITの比較として読む。元の測定値は変更していない。

## 全体

| 条件 | 両側・両ブロック完了specification | 比較result数 | 時間比の幾何平均 | 実行時間の変化 | 2%以上短縮 | ±2%未満 | 2%以上増加 |
|---|---:|---:|---:|---:|---:|---:|---:|
| GILなし、PGO/LTOなし | 90 / 97 | 115 | 0.924020 | **7.60%短縮** | 70 | 35 | 10 |
| GILあり、PGO/full LTOあり | 91 / 97 | 116 | 1.010458 | **1.05%増加** | 20 | 50 | 46 |

時間比はmethod-JIT/main。以下の変化率は負が短縮、正が増加。
2%は整理用の効果量の区切りで、統計的な有意差や同等性の判定ではない。
欠落したspecificationの性能は平均に含まれず、全97件を完走したsuiteの値ではない。
複数resultを出すbase64、SciMarkなどはresultごとに1項目として数える。

2構成に共通する115 resultにそろえても、FTは0.924020、GILありは1.010309で結論は変わらない。
補助的にspecificationを等重みにすると0.918847 / 1.005322。
result比の中央値は0.969603 / 1.007840。
最大の改善を示す `spectral_norm` を除く感度分析でも0.931870 / 1.015811となる。
FTの改善はその1件だけではない。一方、GILありの平均は大きな改善で多数の悪化が相殺されている。

## 改善した主なベンチマーク

| Result | GILなし | GIL・PGO・LTOあり |
|---|---:|---:|
| spectral_norm | -64.78% | -44.96% |
| richards_super | -61.67% | -0.42% |
| richards | -61.01% | -6.57% |
| nbody | -40.87% | +2.54% |
| scimark_lu | -29.14% | +4.16% |
| float | -23.44% | -1.45% |
| unpickle_pure_python | -22.49% | -8.83% |
| pyflate | -19.79% | -2.66% |
| sqlalchemy_imperative | -18.86% | -10.04% |
| deltablue | -18.58% | -10.11% |
| bpe_tokeniser | -16.72% | -13.09% |
| dulwich_log | -16.07% | +6.15% |
| regex_compile | -15.71% | -2.97% |
| html5lib | -15.02% | -1.16% |
| go | -14.98% | -8.22% |
| comprehensions | -14.15% | -1.56% |
| hexiom | -12.47% | -13.00% |
| raytrace | -12.23% | -10.77% |
| tomli_loads | -13.37% | -4.45% |
| logging_silent | -11.96% | -6.71% |
| xml_etree_generate | -3.22% | -8.52% |
| sqlalchemy_declarative | +2.83% | -8.40% |

FTでは数値計算、オブジェクト操作、パーサー、テンプレートなどに改善が見られる。
GILありでもspectral_norm、BPE、Hexiom、raytrace、DeltaBlue、Go、SQLAlchemyなどは改善する。
ただし、FTで速くなる項目がGILありでも速くなるとは限らない。
たとえばnbodyはFTで40.87%短縮する一方、GILありでは2.54%増加している。

`richards_super` はFTで61.67%短縮、GILありで0.42%短縮。
GILありの両ブロック比は0.9967 / 0.9949で、今回もmainをわずかに上回るが、差は小さい。
以前の少数対象の測定値と今回の自動校正による測定値は同じ実験として合算しない。
`btree` は今回選択した97 specificationに含まれていないため、今回の結果からは判定できない。

greenletを省いたSQLAlchemy 1.4.19は両方のベンチマークで4構成とも完了した。
imperativeはFT/GILありの両方で改善し、declarativeはFTで2.83%悪化、GILありで8.40%改善した。
upstreamの依存指定からgreenletを省いたことは全構成で共通であり、ベンチマーク本体と入力は同一。

## GILなしのリグレッション

2%以上増加した10 resultをすべて示す。各ブロックはmain/candidateの順序が逆。

| Result | 時間増加 | ブロック1 | ブロック2 |
|---|---:|---:|---:|
| unpack_sequence | +36.22% | +36.36% | +36.08% |
| deepcopy_reduce | +5.43% | +5.13% | +5.73% |
| asyncio_tcp | +4.69% | +2.74% | +6.68% |
| sympy_sum | +4.48% | +3.98% | +4.98% |
| regex_dna | +4.06% | +4.15% | +3.96% |
| generators | +3.65% | +3.45% | +3.84% |
| regex_v8 | +3.61% | +3.79% | +3.42% |
| docutils | +3.44% | +3.06% | +3.82% |
| sqlalchemy_declarative | +2.83% | +2.75% | +2.91% |
| gc_traversal | +2.53% | +2.18% | +2.88% |

`unpack_sequence` の36.22%増加は特に大きく、以前のFT比較でも約36%の悪化が報告されていた。
今回も両ブロックで再現しており、未解消の課題である。ベンチマークは10要素のアンパックを
多数繰り返すマイクロベンチマークだが、どの実行経路が原因かは今回の結果だけでは未特定。

## GIL・PGO・full LTOありのリグレッション

5%以上増加した項目を示す。2%以上の46 resultすべては末尾の一覧とCSVに含める。

| Result | 時間増加 | ブロック1 | ブロック2 |
|---|---:|---:|---:|
| pprint_pformat | +18.37% | +18.90% | +17.85% |
| pprint_safe_repr | +18.00% | +18.11% | +17.88% |
| logging_format | +16.85% | +15.26% | +18.47% |
| deepcopy_memo | +16.80% | +17.07% | +16.54% |
| pickle_pure_python | +14.65% | +14.83% | +14.47% |
| telco | +14.15% | +16.48% | +11.87% |
| logging_simple | +13.83% | +15.30% | +12.38% |
| async_tree_io | +12.85% | +12.95% | +12.75% |
| pickle_dict | +12.52% | +12.92% | +12.11% |
| async_tree_eager_io_tg | +12.31% | +9.92% | +14.74% |
| base64_small | +11.32% | +11.37% | +11.27% |
| async_tree_io_tg | +11.20% | +11.15% | +11.25% |
| async_tree_eager_io | +11.05% | +10.73% | +11.37% |
| many_optionals | +8.86% | +6.51% | +11.26% |
| typing_runtime_protocols | +8.46% | +8.54% | +8.37% |
| deepcopy | +7.52% | +8.79% | +6.27% |
| async_tree_none | +6.62% | +7.17% | +6.07% |
| base16_small | +6.34% | +6.21% | +6.46% |
| deepcopy_reduce | +6.16% | +6.18% | +6.13% |
| dulwich_log | +6.15% | +4.96% | +7.35% |
| chaos | +6.01% | +4.95% | +7.07% |
| pickle_list | +5.86% | +6.11% | +5.62% |
| scimark_sor | +5.32% | +2.92% | +7.78% |
| async_tree_memoization | +5.08% | +5.32% | +4.84% |

pprint、logging、deepcopy、pickleなど、日常的なオブジェクト操作にも10%以上の悪化がある。
async_treeのI/O系にも11～13%程度の悪化がまとまっている。
FT/GILとも、2%以上悪化した項目は両ブロックで悪化方向だった。
各workerの平均を使う主集計からworker中央値による感度分析へ変えても、これらの悪化方向は変わらない。

`Lib/base64.py`、`Lib/pprint.py`、`Lib/copy.py`、`Lib/logging/__init__.py` は
今回使った4ソースツリーでそれぞれ同一内容だった。
したがって、これらの差はそのPythonファイルの内容の違いでは説明できない。
ただし、JIT、他のランタイム変更、PGO、機械語配置などの寄与はこの測定だけでは分離できない。
JIT offの対照も測っていないため、結果はmethod-JITブランチ全体の差として扱う。

## 未完了項目と候補側だけの失敗

| Specification | 観測 | 評価 |
|---|---|---|
| concurrent_imap / FT | mainは両ブロック成功。候補は両方でthread-pool部分の後に `worker has disabled the JIT` | JITを有効に維持する今回の条件を満たさない。完全な性能比較は成立しない |
| concurrent_imap / GILあり | mainは両ブロック成功。候補は両方でworkerの60秒タイムアウト | 候補固有の要調査項目。原因や停止箇所、実行時間比は未確定 |
| tornado_http / FT | mainは両ブロック成功。候補は両方で `worker has disabled the JIT` | 同上のJIT状態の制約。GILありでは両側成功し、候補が2.78%遅い |
| asyncio_websockets | 全4構成でポート8001の `Address already in use` | 実行環境のポート競合。JITの性能差として判定できない |
| dask | 全4構成でcloudpickleの `KeyError: 'DELETE_GLOBAL'` | 依存パッケージとPythonの互換性問題 |
| genshi | 全4構成で `ast.Expression.__init__ missing ... 'body'` | 依存パッケージとPythonの互換性問題 |
| networkx_k_core | 全4構成で15秒workerタイムアウト | 指定した短い上限を維持。比較不能 |
| fastapi | pydantic-core / PyO3の依存ビルド失敗により未実行 | 性能比較対象にできない |

FT候補の `Python/pystate.c:add_threadstate()` には、2本目のスレッドが加わる前に
JITを無効化してexecutorをinvalidateする安全策がある。FTの上記2件の失敗はこの制約と整合する。
ただし個々のスレッド状態の遷移は今回記録していない。例外はベンチマーク後の測定hookが
JIT無効を検出して発生したもので、Python本体のクラッシュと同一視しない。
この安全策を避けて数字を採るために、hookを外したり、失敗を成功扱いにしたりしていない。
GILありのタイムアウトは別件として調べる必要がある。

FTの `concurrent_imap` には一部の途中結果JSONも残るが、元の規約どおりspecification全体が
両側・両ブロックで完了していないため主集計から除外した。

## 測定と監査の範囲

- 全4ビルドでJIT有効。CPUはIntel Core i5-12450H、通常のaffinityはCPU 2。
  並列対象はCPU 0–11を使用した。
- 2ブロック、各側・各resultに6 worker/ブロック、各workerに5測定値、5 warmup。
  ループ数は独立に自動校正され、pyperfにより1回あたりへ正規化される。
  校正とwarmupは主集計に含めず、worker平均を等重みにし、ブロックごとの比を幾何平均する。
- 順序を反転した測定を保持し、遅いworkerや都合の悪いブロックを削除していない。
- 732個の生JSONのSHA-256を再検証した。成功した730 invocationについて、
  raw JSONから再集計した平均とstate.jsonの平均が一致し、全測定workerのGIL/JIT/実行パス、
  worker数、value数も検証した。失敗したFT invocationの途中JSON2個はハッシュ確認のみ。
- 測定前後の同一性検証は両構成とも成功。今回の解析時にも準備済み環境の再検証を行い、
  バイナリ、標準拡張、stdlib、外部依存、workload、ハーネスの一致を確認した。
- 主な悪化はブロック方向と中央値による感度分析でも残る。一方、1%未満の差を
  別CPUや再ビルドまで一般化しない。pyperfの安定性警告も元のcheckログに保持する。
- CSV/JSONには各ブロック・各側のworkerを独立に再抽出した95%区間も保存した。
  10,000反復、固定seed 20260917から項目別seedを導出する。この区間は観測済みの2ブロックと
  固定ビルドに条件づけられ、ブロック間変動、再ビルド、他ホスト、多重比較をカバーしない。
  `connected_components` のFT改善2.31%はブロック比0.9998 / 0.9545で、条件付き区間も1をまたぐ。
  このような項目まで一律に確定した改善とは扱わない。

GILとFTは順番に測定し、GIL有無と同時にPGO/LTOの条件も変えている。
この表は各構成内のmain対method-JITを比較するもので、FTとGILの差の原因を切り分けた実験ではない。

次は候補側だけの並列処理の失敗、FTのunpack_sequence、GILありのpprint/deepcopy/loggingを
優先して調べるのがよい。後者の改善を既存の大きな高速化と両立できるかを確認する必要がある。

## 証拠

- [解析データ](../jit-artifacts/pyperformance-four-way-current/analysis.json)
- [全比率CSV](../jit-artifacts/pyperformance-four-way-current/ratios.csv)
- [再集計・監査スクリプト](../jit-artifacts/pyperformance-four-way-current/analyze_results.py)
- [FTの元レポート](../jit-artifacts/pyperformance-four-way-current/ft/compare.md)
- [GIL/PGO/LTOの元レポート](../jit-artifacts/pyperformance-four-way-current/gil-pgo-lto/compare.md)
- 各構成の `state.json`、`identities.json`、`preparation.json`、`results/`、`check-*.log`。

使用した実行ファイルのSHA-256:

| ビルド | SHA-256 |
|---|---|
| FT main | `90c095bd8ba8a4e9476ba41b6143cb80f8264cab93241f927b11fc48121b67c9` |
| FT method-JIT | `5850d386d8e8b3ff01b8afa49f492911490a82c9ac5d69910cc62655cdf03772` |
| GIL/PGO/LTO main | `dd63a277fd879d2f0993655c0502ee26f98bf37656890ae30fdeedb734287c49` |
| GIL/PGO/LTO method-JIT | `babf6145453655e71b4abc068f5f4a232caed4e7069259cf3821a1039f54d861` |

## 全完了resultの一覧

主集計の実行時間変化率。負が改善、正が悪化。「—」は完全な比較結果がないことを示す。
小差と不安定な項目も含めて全件を残す。絶対時間、両ブロック比、条件付き区間はCSV/JSONを参照。

| Result | GILなし | GIL・PGO・LTOあり |
|---|---:|---:|
| 2to3 | +0.12% | -2.11% |
| ascii85_large | +1.21% | +0.00% |
| ascii85_small | -3.86% | -1.84% |
| async_generators | -2.42% | +3.76% |
| async_tree_cpu_io_mixed | -1.05% | +4.79% |
| async_tree_cpu_io_mixed_tg | -1.26% | +2.04% |
| async_tree_eager | -5.37% | -2.49% |
| async_tree_eager_cpu_io_mixed | -1.69% | -0.45% |
| async_tree_eager_cpu_io_mixed_tg | -0.16% | +1.46% |
| async_tree_eager_io | -3.25% | +11.05% |
| async_tree_eager_io_tg | -1.69% | +12.31% |
| async_tree_eager_memoization | -2.27% | -1.09% |
| async_tree_eager_memoization_tg | -2.92% | +2.00% |
| async_tree_eager_tg | -2.46% | +3.31% |
| async_tree_io | -0.13% | +12.85% |
| async_tree_io_tg | -0.23% | +11.20% |
| async_tree_memoization | -1.86% | +5.08% |
| async_tree_memoization_tg | -0.74% | +0.87% |
| async_tree_none | -4.20% | +6.62% |
| async_tree_none_tg | -2.14% | +3.20% |
| asyncio_tcp | +4.69% | +0.60% |
| asyncio_tcp_ssl | +0.20% | -0.55% |
| base16_large | -2.75% | -1.32% |
| base16_small | -11.74% | +6.34% |
| base32_large | -0.16% | -0.11% |
| base32_small | -8.71% | +1.06% |
| base64_large | -0.23% | -1.08% |
| base64_small | -5.55% | +11.32% |
| base85_large | -2.21% | +0.02% |
| base85_small | -3.41% | +0.32% |
| bpe_tokeniser | -16.72% | -13.09% |
| chameleon | -9.68% | -1.78% |
| chaos | -8.57% | +6.01% |
| comprehensions | -14.15% | -1.56% |
| connected_components | -2.31% | +1.69% |
| coroutines | -3.49% | -0.67% |
| coverage | +1.02% | +2.15% |
| create_gc_cycles | -0.42% | +1.05% |
| crypto_pyaes | -9.59% | -0.68% |
| deepcopy | -0.31% | +7.52% |
| deepcopy_memo | -10.68% | +16.80% |
| deepcopy_reduce | +5.43% | +6.16% |
| deltablue | -18.58% | -10.11% |
| django_template | -3.62% | +3.92% |
| docutils | +3.44% | +3.06% |
| dulwich_log | -16.07% | +6.15% |
| fannkuch | -13.83% | +3.20% |
| float | -23.44% | -1.45% |
| gc_traversal | +2.53% | +3.89% |
| generators | +3.65% | -0.22% |
| go | -14.98% | -8.22% |
| hexiom | -12.47% | -13.00% |
| html5lib | -15.02% | -1.16% |
| json_dumps | -6.98% | +0.59% |
| json_loads | +0.07% | -0.08% |
| logging_format | -0.38% | +16.85% |
| logging_silent | -11.96% | -6.71% |
| logging_simple | -2.79% | +13.83% |
| mako | -11.43% | -0.10% |
| many_optionals | +1.28% | +8.86% |
| mdp | -1.89% | -3.16% |
| meteor_contest | -1.99% | +2.89% |
| nbody | -40.87% | +2.54% |
| nqueens | -10.60% | -1.18% |
| pathlib | -3.04% | +0.50% |
| pickle | -1.22% | -2.45% |
| pickle_dict | +1.28% | +12.52% |
| pickle_list | -1.08% | +5.86% |
| pickle_pure_python | -4.34% | +14.65% |
| pidigits | -0.26% | +0.29% |
| pprint_pformat | -2.86% | +18.37% |
| pprint_safe_repr | -3.17% | +18.00% |
| pyflate | -19.79% | -2.66% |
| python_startup | +0.63% | +0.59% |
| python_startup_no_site | +0.35% | +0.69% |
| raytrace | -12.23% | -10.77% |
| regex_compile | -15.71% | -2.97% |
| regex_dna | +4.06% | +0.18% |
| regex_effbot | -0.44% | +1.88% |
| regex_v8 | +3.61% | +2.11% |
| richards | -61.01% | -6.57% |
| richards_super | -61.67% | -0.42% |
| scimark_fft | -11.81% | +1.48% |
| scimark_lu | -29.14% | +4.16% |
| scimark_monte_carlo | -15.58% | +0.11% |
| scimark_sor | -15.45% | +5.32% |
| scimark_sparse_mat_mult | -14.18% | +0.23% |
| shortest_path | +0.43% | +1.48% |
| spectral_norm | -64.78% | -44.96% |
| sphinx | +0.81% | +0.13% |
| sqlalchemy_declarative | +2.83% | -8.40% |
| sqlalchemy_imperative | -18.86% | -10.04% |
| sqlglot_v2_normalize | -4.71% | +3.22% |
| sqlglot_v2_optimize | -3.92% | +0.18% |
| sqlglot_v2_parse | -9.73% | +4.12% |
| sqlglot_v2_transpile | -6.32% | +2.24% |
| sqlite_synth | -4.63% | -0.75% |
| subparsers | -3.63% | +0.97% |
| sympy_expand | -7.01% | +1.37% |
| sympy_integrate | +1.42% | -0.51% |
| sympy_str | -2.16% | +1.24% |
| sympy_sum | +4.48% | +3.49% |
| telco | -6.48% | +14.15% |
| tomli_loads | -13.37% | -4.45% |
| tornado_http | — | +2.78% |
| typing_runtime_protocols | -3.57% | +8.46% |
| unpack_sequence | +36.22% | -0.02% |
| unpickle | -1.13% | +0.46% |
| unpickle_list | +1.45% | -2.62% |
| unpickle_pure_python | -22.49% | -8.83% |
| urlsafe_base64_small | -6.02% | -1.40% |
| xdsl_constant_fold | -3.94% | +3.21% |
| xml_etree_generate | -3.22% | -8.52% |
| xml_etree_iterparse | -2.68% | +1.65% |
| xml_etree_parse | -1.59% | +0.65% |
| xml_etree_process | -3.70% | +3.75% |
