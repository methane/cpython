# regex_compileの回帰修正（2026-09-19）

夜間比較のレポートと計画を `14defe7e06e` にコミットした後、`regex_compile` の
不要なJITコンパイル再試行を修正した。FTではmain比16.79%短縮、
GIL・PGO/full LTOではmainとほぼ同じ水準（平均1.87%短縮）へ回復した。
今回の修正とこのレポートは未コミット。

## 最終結果

比は実行時間の比で、小さいほど速い。全72呼び出しが成功し、測定前後の
実行物・依存・workloadの同一性検証も全4測定群で成功した。

| 構成 | main | 修正前 | 修正後 | 修正前/main | 修正後/main | 修正前からの時間短縮 |
|---|---:|---:|---:|---:|---:|---:|
| FT・PGO/LTOなし | 117.563 ms | 205.128 ms | 97.825 ms | 1.7448 | 0.8321 | 52.31% |
| GIL・PGO/full LTO | 75.435 ms | 242.760 ms | 74.026 ms | 3.2182 | 0.9813 | 69.51% |

| 構成 | 修正後/mainの95%区間 | 第1/第2ブロック比 | 修正後/修正前の95%区間 |
|---|---:|---:|---:|
| FT・PGO/LTOなし | 0.8269–0.8381 | 0.8350 / 0.8292 | 0.4734–0.4807 |
| GIL・PGO/full LTO | 0.9609–0.9961 | 0.9857 / 0.9770 | 0.3041–0.3060 |

区間の定義・限界は後述。worker中央値を使う感度分析でも修正後/mainはFT 0.8290、
GIL 0.9919。GILのmainとの差は小さいが、修正前の約3.2倍という悪化は解消した。

### 他の5項目への影響

修正前との時間変化率は正が悪化、負が短縮。元の主測定をそのまま掲載する。

| 構成 | 項目 | 修正前/main | 修正後/main | 修正前からの時間変化 | 修正後/修正前の95%区間 |
|---|---|---:|---:|---:|---:|
| FT・PGO/LTOなし | go | 0.8576 | 0.8634 | +0.68% | 0.9985–1.0161 |
| FT・PGO/LTOなし | regex_effbot | 1.0542 | 0.9890 | -6.19% | 0.9350–0.9415 |
| FT・PGO/LTOなし | regex_v8 | 1.0458 | 1.0382 | -0.73% | 0.9912–0.9945 |
| FT・PGO/LTOなし | richards_super | 0.3877 | 0.3893 | +0.41% | 0.9980–1.0094 |
| FT・PGO/LTOなし | unpack_sequence | 0.7004 | 0.6997 | -0.09% | 0.9946–1.0031 |
| GIL・PGO/full LTO | go | 0.9331 | 0.9602 | +2.90% | 0.9989–1.0804 |
| GIL・PGO/full LTO | regex_effbot | 1.0567 | 1.0331 | -2.23% | 0.9706–0.9842 |
| GIL・PGO/full LTO | regex_v8 | 0.9924 | 0.9993 | +0.70% | 1.0055–1.0081 |
| GIL・PGO/full LTO | richards_super | 1.0313 | 1.0209 | -1.01% | 0.9802–0.9980 |
| GIL・PGO/full LTO | unpack_sequence | 0.4502 | 0.4474 | -0.62% | 0.9914–0.9967 |

GIL Goは初回6 worker中1つが64.94msで、他の5つの55–56msより継続的に遅かった。
そのworkerの5 valuesを全て含めた比は1.0290、95%区間は0.9989–1.0804。
ブロック比も1.0015 / 1.0572と異なり、単一の安定した効果量とは判断しない。

同じ固定バイナリで、追加の各8 worker×逆順2ブロック（各側16 worker）を事前に定めて確認した。
追加分の修正後/修正前は **0.9994**、95%区間 **0.9955–1.0035**、
修正後/mainは **0.9322**。修正後16 workerの平均は55.23–56.53msで低速群は再発しなかった。
最初の遅いworkerは除外せず、追加分と混ぜて主結果を置き換えてもいない。
再現性のあるGoの回帰は確認できなかったが、この低速workerの原因は未特定である。

GIL regex_v8の修正前比約0.70%増加は両ブロックで観測した。
またFT regex_v8、GIL regex_effbot/richards_superなど、mainより遅い項目は残る。
「他項目の性能が完全に不変」「全ての回帰を解消」とは結論しない。

### 修正後の実行物

| 構成 | パス | SHA-256 |
|---|---|---|
| FT | `jit-artifacts/regex-compile-20260919/ft-build/python` | `bcc72a085c56e98aa9bb83103e80b9c91b10627f967be81db67b76dabb1e06f7` |
| GIL・PGO/full LTO | `jit-artifacts/regex-compile-20260919/pgo-build/python` | `c4f7559ec0b596dc7f4d82be4f11616cecd32de74e38aeed64ef38af0da69d84` |

元の夜間用4バイナリはSHAが不変。今回の作業ツリーとPGO用隔離ソースの対象3,943ファイルも
最終時点でSHA一致を確認した。ビルド記録・各比較のstate.jsonに依存と実行物のSHAを保存した。


## 原因と修正

夜間比較ではcandidate/mainの実行時間比がFT 1.745、GIL・PGO/full LTO 3.228だった。
同じ4バイナリを使い、JIT有無・逆順2ブロックで診断すると、採取される正規表現は
全条件で4,267件、入力SHAも同一だった。JIT無効ではmainと候補の時間はほぼ同じ。
したがって、入力の増加やJIT以外の一律な低速化では説明できなかった。

固定仕事量のperf診断では、遅い候補のcycles sampleの22.33%が
`method_merge_block`、8.57%が `method_decode_cfg` にあった。
debugログでも `_parse` のmethod却下が1,317回発生した。
この件数は正規表現採取と1 warmup・1 valueを含む診断であり、本測定全体の件数ではない。

問題は二つあった。

1. 既存のインライン化ループを優先してmethod化を却下しても、その選択を保存していなかった。
   入口traceの再作成時に重いCFG解析を繰り返していた。
   `Python/optimizer.c` で既存の `co_executors->prefer_trace` を保存するようにした。
   頻繁にfallbackするpartial methodと同じ仕組みを使う。
2. `TRACE_RECORD` が、その関数のRESUMEやJUMP_BACKWARDの待ち回数も
   specialization用の強制ゼロで上書きしていた。
   `Python/bytecodes.c` で、トレース優先と判断済みの関数については再試行のcountdownを保持する。
   これにより、他のtraceへ記録されるたびに入口・ループが即座にhotへ戻ることを防ぐ。

関数名・モジュール名・正規表現の内容による特別扱いはない。
既存のインライン化ループと依存関係の無効化を維持し、将来の実行はtrace側で適応する。
新規の関数のwarmupや、ready counterが8191へwrapすることを防ぐ既存処理も維持している。

## 段階的な確認

最初の修正だけでは `_parse` のmethod却下は1回へ減ったが、元のpyperf条件で
FTはmain約117.7msに対して約126.0msとなり、約7%の悪化が残った。
この結果を保存し、二つ目の修正へ進んだ。

二つの修正後の短い診断ではFT約98–100ms、GIL・PGO/LTOなし約85msとなった。
これらは本測定とは別の診断値であり、GIL・PGO/full LTOの結果の代用にはしない。

本測定後、FTで一つ目の修正だけの固定バイナリと最終版を同じ仕事量でperf記録した。
トレース翻訳・最適化のself sample比率は4.78%・2.66%から、それぞれ表示下限の
0.1%未満へ減少した。総cyclesの推定値も約197.4億から157.3億へ減少した。
これはimport・5 warmup・30反復を含む各1回の診断で、通常の性能測定とは別。
両方ともlost sampleは0だった。

## 正しさの検証

`test_partial_method_keeps_existing_inlined_loop` を拡張し、次を確認する。

- 依存する関数の `__code__` を差し替えると、元のループは無効になり、戻り値が変化する。
- 無効化後に空ループで入口を再warmupしても、却下済みのmethodを再作成しない。
- 別のcallerがこの関数をtraceへ記録しても、再試行のcountdownをゼロへ上書きしない。
- 空ループ・通常のループ・別の分岐で正しい戻り値を維持する。

最初の追加検査は未修正のGIL/FT debugで失敗し、一つ目の修正後に成功した。
countdown検査は一つ目の修正だけのビルドで失敗し、二つ目の修正後に成功した。
新しいテストの初稿では不要な閉ループ成立を仮定していたため、実際に必要な
calleeへの `PUSH_FRAME` の検査を残した。初稿と修正版の失敗ログを両方保存している。

関連テストは `test_capi.test_opt`、`test_optimizer`、`test_re`、`test_generators`、
`test_yield_from`、`test_coroutines`、`test_asyncgen`、`test_dict`、`test_monitoring`、
`test_frame`。通常・FTのrelease/debugで実行し、両debugでは追加ケースの3:3参照リーク検査も行う。
debugはTier 2インタプリタ構成、releaseはnative JIT構成である。
最初のsandbox内実行ではtest_reのforkserver用Unix socketが拒否された。
その失敗を保存し、ローカルソケットを許可した条件で同じテストを再実行した。

最終変更は上記4構成で各1,274テストに成功した（GIL release/debugは15/14 skip、
FT release/debugは23/22 skip）。両debugの3:3参照リーク検査も成功。
新規GIL PGO/full-LTO版も同じ1,274テスト（15 skip）に成功した。
PGO学習は43/43ファイル、10,468テスト（460 skip）成功、354個のprofileを記録した。

## 最終比較の条件

- mainは夜間測定と同じ `d95f29589e03603aa13d8ca9d4f817dce77d357c` ＋ LLVM 21互換パッチ。
- 修正前は夜間測定と同じ採用版V26、`718d2ff2ef9705a8cdbfa7b345038f5b484a7343` の実行物。
- 修正後は `14defe7e06e` に上記のruntime変更とテストを加えたビルド。
- FTはPGO/LTOなし。GILは新規にPGO学習したfull LTOビルド。
- GCC 13.3、LLVM 21 JIT、`-O3`、frame pointer・leaf frame pointerあり。
- GIL PGOは夜間と同じ43学習テスト、JIT無効、seed 0、cold private pycache。
  bootstrapのプロファイルを本学習と分離し、別ソースのプロファイルは流用しない。
- pyperformance 1.14.0の同じスクリプト・入力、pyperf 2.10.0、CPU 2、`PYTHONHASHSEED=0`、JIT有効。
  Go本体の `random.seed(1)` を含め、各workload固有の入力設定も保持した。
- main/修正前/修正後を仕様ごとに続けて測定し、第2ブロックでは逆順にする。
- regex_compileは各6 worker、比較対象のregex_effbot/regex_v8/Go/richards_super/unpack_sequenceは各3 worker。
  全て5 warmup・5 values、min-time 0.1秒。各側で独立校正し、pyperfが正規化した値を使用する。
- 各worker内の平均を等重みで集計し、2ブロックの時間比を幾何平均する。
  95%区間はブロック・各側ごとのworkerを独立に再抽出する4,000回のbootstrap（seed 20260919）。
  再ビルド・他CPUへの変動と、多重比較の選択効果は含まない。
- ビルドや他の重い作業を性能測定と競合させない。遅い試行は削除しない。

FTのmainはexecutorを生成しないため、Tier 1インタプリタ対method JITの比較である。
この6仕様の結果をpyperformance全体の改善とは扱わない。

## 証拠

生データ・診断・ビルド・テスト・集計の記録は
[`jit-artifacts/regex-compile-20260919/`](../jit-artifacts/regex-compile-20260919/) に保存する。

- `probe-state.json`、`probe-*.json`: 固定4バイナリのJIT有無と入力同一性。
- `initial-*-perf.*`、`initial-debug-rejections.log`: 修正前のコンパイル費用。
- `trial-builds.json`、`r1-ft-regex-state.json`、`r1-binaries.json`: 一つ目の修正だけの結果。
- `r2-builds.json`、`r2-correctness.json`、`pgo-build.json`: 最終変更と検証の記録。
- `r2-final-*-state.json`、`final-analysis.json`: 最終比較の生値・集計。
- `r2-go-followup-state.json`、`go-followup-analysis.json`: Goの追加比較。主集計と別に保存。
- `final-perf.json`、`final-perf-r1/r2.*`: 最終性能測定後のコンパイル費用の診断。

夜間測定の元データと4バイナリは保存している。
関連する過去の結果は[夜間レポート](pyperformance_overnight_report.md)を参照。
