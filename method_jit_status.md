# Method JIT と free-threaded 対応の現状

更新日: 2026-09-16

## 今回の更新（比較・分析・最適化の1〜4）

main対照を同じLLVM設定で作り直し、trace / prototype / 開始時点との比較、nativeの
動的uop計測とperfを実施した。global依存関係のnegative cache、block内のvalidity/IP
cleanup、小さい分岐calleeのinline、隣接する単一先行edgeの削除を実装した。

24ワークロードの幾何平均実行時間はmain比1.0076、開始時点比0.9984で、20%目標は未達。
Goは開始時点比0.8375へ短縮したがmain比1.1240。methodからTier 1への未対応bytecode
復帰は44.1%残り、今回のinline拡張ではGoの復帰回数は変わらなかった。

詳細な設計・検証・測定条件と個別結果は
[method_jit_performance.md](method_jit_performance.md) を参照。
以下は前回までの記録である。

## 前回の更新（milestones 1〜6）

block単位の型・定数状態、保守的merge、loop fixed pointを実装した。
returnは `_RETURN_VALUE` と `_METHOD_EXIT` でframeを破棄してTier 1のcallerへ戻す。
straight-line methodと、小さい直線的な `CALL_PY_EXACT_ARGS` calleeのinliningに対応した。
inlined calleeのcode変更によるinvalidation、NetworkXで見つかった完了済みcall後の
periodic side-exit復帰先も検証・修正した。Tier 2 callerへの直接native returnは未実装である。

GIL/free-threadedそれぞれのdebug interpreter JITとnative JITで
`test_capi.test_opt` 332件が成功した（GILは4件、free-threadedは3件skip）。
generator/optimizer関連テストと、生成物12ファイルの2回の再生成比較も成功した。

前回の測定はRichards 0.9936、NetworkX 0.9932、Go 1.3418だった。ただし比較先は
9月13日の旧main `a60343ed` の保存済みbinaryで、現在の基点・JITビルド設定とは異なる。
Goの差全体を今回の変更に帰属させることはできない。次は同条件のcontrolを用意し、
実行時のside exit、call/return、spill、validity checkのコストを切り分ける。

詳細と次の作業順序は [plan.md](plan.md#next-work)、測定記録は
[benchmark summary](jit-artifacts/method-jit-milestones-20260916/summary.md) を参照。

以下はコミット `20269941716` 時点の初期prototypeの記録である。

## スナップショット

この変更は `codex/method-jit` ブランチ上で、CPython `main` の
`d95f29589e03603aa13d8ca9d4f817dce77d357c` を基点としている。PEP 836を
参考にしたmethod-entry frontend、`--disable-gil`で安全にJITを一時停止する
lifecycle、JIT実験中に見つかった既存不具合の修正を一つのローカル変更として
まとめた。GitHubへの投稿、push、PR変更は行っていない。

ビルドには `/usr/lib/llvm-21` と `/usr/bin/python3.12` を使用した。PGOとLTOは
使用していない。

## 実装した内容

### Method JIT frontend

- 関数入口の `RESUME` からcode object全体をdecodeし、basic blockと到達可能な
  control-flow graphをworklistで構築するfrontendを追加した。
- conditional branch、unconditional jump、iterator exhaustionにmethod専用uopを
  発行し、実行時に通らなかった分岐も同じexecutorへ含める。
- list、tuple、range、generic iteratorを含むloopをCFGとして変換する。
- CFG edgeの前でstack cacheをspillし、各block入口のvalue-stack表現を統一した。
  stack allocation後のoffset remappingもmethod edgeへ反映する。
- method executorは入口へ一つだけ取り付ける。既存のtrace frontendはbackedgeと
  未対応code objectのfallbackとして残す。
- returnは現在 `_METHOD_DEOPT` でTier 1へ戻して処理する。これによりinterpreter
  callerとTier 2 callerのどちらから入ってもframe teardownを壊さない。

### `--disable-gil` lifecycle

- free-threaded buildでもTier 2とnative JITを有効化した。ただし現段階では、対象
  interpreterのthread stateが一つの間だけJITを実行する。
- 二つ目のthread stateを公開する前にstop-the-worldを行い、JIT gateをatomicに
  無効化して全executorをinvalidateする。native executorのdetachとexit-table更新も
  既存threadが停止した状態で行う。
- interpreterが再び一つのthread stateになった時、設定と終了状態を確認してJITを
  再有効化する。hotness counterは停止期間中だけ休止し、その後の再compileを妨げない。
- executor validityとinterpreterのJIT gateをatomicにし、TLBC copyでは
  `ENTER_EXECUTOR` を元のopcodeへ戻す。
- function/typeのreverse cacheは既存lockの下で維持する。optimizerが読む時点では
  上記のsingle-thread policyが成立している。

### `main` 由来の不具合修正

`bugs_report.md` のM-1〜M-12とP-1〜P-2を調査し、修正が必要な項目を反映した。
主な変更は次の通りである。

- globals/builtinsのnamespace identityをguardし、copied dictやshared keysで誤った
  constant foldingが残らないようにした。
- global dependencyを辞書全体からname単位へ細分化し、構造変更とvalue変更を区別した。
- dict subclass receiverと互換subclassのmethod descriptorを正しくguardするようにした。
- float constantと参照所有権に関するoptimizerの誤りを修正した。
- retry counter、生成ファイル依存、replicated uop IDの並び、recorder出力先を修正した。
- LLVM 21が生成するconstant poolとjump tableのlocal labelをassembly optimizerが削除しない
  ようにした。

各項目の再現条件、main上の証拠、修正方針は `bugs_report.md` に記録している。

## 現在の対応範囲

method frontendは複数basic blockを持つ通常関数を対象とし、specialized bytecodeを既存の
specialized uopへ展開してcopy-and-patch backendへ渡す。branchとloopをmethod単位で
native codeへできることは確認済みである。

次の領域はまだmethod frontendの対象外、または意図的にTier 1へside exitする。

- generator、coroutine、async generator
- exception tableを持つcode object
- Python function callのinlining
- method CFGをまたぐmerge-aware symbolic optimization
- Tier 2 callerのcached stateを直接復元するnative return protocol
- uop上限を超える大きなmethod

straight-line functionは、return deoptによってsmall helperをまたぐspecializationを失うため、
現時点ではtrace frontendへ任せている。この制限のため、現在の実装はPEP 836の最終形では
なく、method frontendとfree-threaded lifecycleを検証する段階である。

## 検証結果

| 構成 | 検証 | 結果 |
|---|---|---|
| GIL debug, interpreter JIT | `test_capi.test_opt test_optimizer test_generated_cases test_tools.test_jit` | 435 tests、4 skipped、成功 |
| free-threaded debug, interpreter JIT | 同上 | 435 tests、3 skipped、成功 |
| free-threaded native LLVM 21 JIT | 同上 | 435 tests、3 skipped、成功 |
| free-threaded native LLVM 21 JIT | `test_threading` | 245 tests、5 skipped、成功 |
| free-threaded native LLVM 21 JIT | focused free-threading code/function/thread-state tests | 17 tests、成功 |
| native smoke | `test_builtin test_call test_iter test_generators` | 成功 |
| generated files | `make regen-cases`後に11ファイルのSHA-256を再比較 | 完全一致 |

native branch methodは4096 bytesのmachine codeを生成し、warmupで通らなかった分岐も
正しい結果を返した。native range methodは8192 bytesを生成し、二つ目のthreadが存在する
間にinvalidateされ、そのthread終了後に別の8192-byte executorとして再生成された。
このinvalidate/recompileを25 cycle繰り返すstress probeも成功した。

検証に使ったfree-threaded native executableは
`build-method-ft-jit/python` である。`sys._is_gil_enabled()` はfalse、
`sys._jit.is_available()` と `sys._jit.is_enabled()` はtrueを返す。
`git diff --check`も成功している。

## 関連文書

- `plan.md`: 実装手順、設計判断、検証履歴、次の作業
- `bugs_report.md`: main上で見つけた不具合の再現と修正根拠
- `pyperf_report.md`: pyperformanceの成功benchmarkごとのhot path分類とmethod JITへの示唆
- `large_functions.md`: 既存binaryの大きな関数とcode-size比較

## 次の作業

最初にmethod CFGへmerge-aware symbolic stateを導入し、分岐を越えて型とconstantの情報を
伝播させる。続いてTier 1とTier 2の両callerを扱えるmethod return protocolを追加する。
この二点を基盤としてstraight-line method、Python call inlining、exception region、
generator/coroutineへ対応範囲を広げる。その後、`pyperf_report.md` でPython支配と分類した
cohortを中心にcoverage、compile cost、実行時間を再測定する。
