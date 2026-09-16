# Method JIT: 比較条件の統一、コスト分析、最適化

更新日: 2026-09-16。開始点は `15c0e6113c1`、mainの基点は `d95f29589e0`。
今回依頼された1〜4について、対照ビルド、動的計測、実装、正しさと性能の検証を行った。

## 比較条件

LLVM 21 / GCC、PGO・LTOなし、CPU 2。mainは基点から新しくビルドし、ビルドに必要な
`Tools/jit/_optimizers.py` のlocal label到達性修正だけを適用した。
以前の9月13日main binaryに依存する比較ではない。

同じ修正済みruntime上で、method frontendを無効化したtrace版、以前のprototype版、
今回の開始時点の版も作った。Goはtrace版も約84 msで、開始時点のmethod版とほぼ同じだった。
新しいmainは約63.5 ms。JIT無効時はmain約69.6 ms、このブランチ約71〜73 msだった。
したがって、Goの差全体をmethod frontendのmerge/inliningに帰属させることはできない。
最終版のglobal miss cacheを含むtrace-only対照も追加したところ、Goは67.3〜68.1 ms、
method版は70.8〜71.3 ms、mainは63.4〜63.7 msだった。最終method版には同じruntimeの
trace版に対してなお約5%の追加時間があり、shared runtime側にもmainとの差が残る。

各変更を個別に追加したbinaryを保存し、Goを3プロセスブロックで順序を回転して測定した。
各プロセスは5 warmup、20測定値。平均値をプロセス単位として比の幾何平均を取る。
広い比較では、24のpyperformance workloadを事前に固定し、main / 開始時点 / 最終版を
順序を反転した2ブロックで実行した。各プロセスは3 warmup、5測定値で、mainで校正した
同じloop数を使用する。NetworkXのプロセス群は15秒、その他は45秒で打ち切る。
この24件はpyperformance全体ではなく、独立した未探索のholdoutでもない。

binary・stencil・拡張・共通site-packagesのhash、実行コマンド、失敗も含む生データは
[jit-artifacts/method-perf-20260916](jit-artifacts/method-perf-20260916/README.md) に保存した。
開始時点のoptimizerは最終版と同じ内部headerで再リンクし、拡張との構造体配置を合わせた。

## 見つかったコストと実装

### global依存関係の走査

変更前のGoのnative perfでは、`invalidate_dependencies` が10.78%、
`_Py_Executors_InvalidateGlobalDependency` が3.64%のsampleを占めた。
以前導入したname単位のglobal watcherは、無関係なvalue変更でもwatchを維持するため、
変更のたびに全executorを走査していた。これはtrace版とmethod版に共通するコストだった。
最終版の同じ55 operationのnative perfでは、この2関数はそれぞれ0.2%未満と0.57%になった。
このsample比の変化も、個別binary比較で見られたcacheの効果と一致する。

辞書のaddressとnameのhashをキーに、依存executorが存在しなかった結果を4件保持する。
executorの追加、既存executorの依存関係の追加で全件clearする。構造変更はcacheを使わず
走査する。executor削除は新しい依存関係を作らない。辞書pointerは比較にしか使わず、
参照保持やdereferenceはしない。hash衝突時は従来のBloom filterと同じく保守的に扱う。
最初のdirect-mapped実験に続き、少数の頻繁に更新される名前同士がslotを奪い合わない
4-entry associative方式にした。

### validityチェックとIP保存

basic block内で、escapeを挟まない重複 `_CHECK_VALIDITY` を削除する。
`_SET_IP` はerror・escape・frame変更に必要なものを残す。
rootとinlined calleeの分岐先、return後のcaller継続点をすべて境界として扱い、
そこで情報をresetする。既存の直線trace用cleanupをCFG全体へそのまま適用してはいない。

### 小さい分岐calleeのinline

既存の128 code unit制限を維持し、`CALL_PY_EXACT_ARGS` のcalleeについて前向き分岐と
複数returnを扱う。callee自身のCFGを解析・mergeし、ローカルblock番号をuop位置へ変換する。
各returnはframeを戻した後、callerの同じ継続点へ進む。
functionのcode変更によるinvalidationと、callee内の例外・side exitを維持する。
loop、再帰、入れ子のPython call、exception table、generatorは引き続き対象外。

### 隣接する単一先行edge

直後のblockへの無条件jumpで、対象の先行edgeが一つだけならjumpを削除する。
既存のstack allocatorがそのままcached valueを持ち越せる。
複数の先行edgeがあるjoinや離れたbranch targetのstack-cache ABIは変更していない。
一般的なjoinを含むcache signature伝播は今後の課題である。

## 動的な実行回数

別のnative診断ビルドでmethod executorに印を付け、uopごとの実行回数を数えた。
診断コードは作業ツリーの実装に含めず、その実行時間を性能比較には使っていない。
以下は5回のwarmup後のGo 5 operationの合計。

| 項目 | 開始時点 | 最終版 |
|---|---:|---:|
| method進入 | 2,367,446 | 2,367,446 |
| 未対応bytecodeからTier 1へ復帰 | 1,043,586 | 1,043,586 |
| root method return | 1,323,860 | 1,323,860 |
| inlined returnを含むRETURN_VALUE | 1,547,366 | 1,547,366 |
| validity check | 41,462,069 | 23,170,322 |
| IP保存 | 40,418,483 | 17,218,663 |
| method jump | 2,286,412 | 626,499 |
| spill/reload | 21,923,473 | 21,923,473 |
| method uop合計 | 220,118,007 | 176,966,527 |

この区間ではmethodからのguard/periodic exitは0だった。進入の44.1%が未対応bytecodeで
Tier 1へ戻る。今回の分岐inlineはGoのこの復帰回数を減らしておらず、spill回数も変わらない。
静的なuop削減を、そのまま実行時間短縮と同一視してはいけない。

5 warmup中のmethod compilationは12件成功し、合計約0.77 msから1.12 msへ増えた。
その後の5 operationでは15件の失敗したcompile試行が約0.31/0.26 msかかった。
少なくともこのworkloadではcompile時間は主要コストではない。

## 検証

GIL / free-threaded、それぞれのdebugとreleaseでoptimizer suite 338件を検証した。
追加テストは、分岐calleeの複数return、型の異なるjoin、int overflow、callbackによる
invalidation、例外tracebackのinstruction位置、negative cache後の依存追加を扱う。
既存のthread開始時の停止・invalidation・single-threadへ戻った後の再compileも含む。

GIL debugで数値・generator・tracing・monitoring・threadingが成功。
`concurrent.futures` はsandboxのsocket制限による失敗を記録した後、sandbox外で成功した
（optimizerを含む10ファイル、746 tests、26 skipped）。FTのthreading/monitoringも成功。
定数がimmortal化される読み込み方では `_POP_TOP_NOP` が正しいため、既存のint/float
specializationテスト2件は実際の定数のimmortalityに基づく期待値へ修正した。
修正後の2件は4構成すべてで個別再検証した。optimizer/generator/JIT-toolの追加110 testsと
`git diff --check` も成功。現在のGIL executableは `build-method-jit/python`、
free-threaded executableは `build-method-ft-jit/python`。`PYTHON_JIT=1` で実行できる。
今回の実装・検証結果をローカルコミットにまとめた。GitHubへの投稿・push・PR変更は行っていない。

## 性能結果

全件の表とプロセス間の幅は
[cohort-summary.md](jit-artifacts/method-perf-20260916/cohort-summary.md) を参照。
24/24件が全比較に成功し、timeoutはなかった。実行時間比は小さいほど速い。

| 対象 | 最終版 / main | 最終版 / 開始時点 |
|---|---:|---:|
| 24件の幾何平均 | 1.0076 | 0.9984 |
| Go | 1.1240 | 0.8375 |
| Richards | 1.0286 | 1.0016 |
| NetworkX connected components | 1.1297 | 1.1266 |

Goは開始時点より16.25%短縮したが、mainより12.4%遅い。
24件の幾何平均はほぼ横ばいで、**20%高速化は未達成**。
NetworkXのmain比は2ブロックで0.991〜1.288、Chaosは0.984〜1.135と大きく揺れた。
これらの平均を安定した回帰量とは扱わない。Raytrace、regex_dnaも含めて追加3ブロックを
測定した。一次集計から遅い試行を削除・置換はしていない。

追加分を含む全5プロセスずつの集計は次の通り。

| 対象 | 最終版 / main | 最終版 / 開始時点 |
|---|---:|---:|
| chaos | 1.0404 | 1.0123 |
| raytrace | 1.0160 | 1.0096 |
| regex_dna | 0.9520 | 0.9535 |
| networkx_connected_components | 1.0513 | 0.9984 |

NetworkXでは約399 msの遅い状態が最終版だけでなく開始時点の版にも出た。
その他の試行は主に約307〜314 msで、プロセスごとの大きな差は残る。
Raytraceの当初の約2.6%の変更前比回帰は、追加3ブロックでは再現しなかった。
regex_dnaの約4.7%の短縮は追加測定でも再現したが、JIT変更が原因かCコードの命令配置など
別の原因かは未特定である。原因未特定の改善をmethod frontendの効果とは数えない。

これは一組のビルドを同一PCで比較したscreenであり、独立再ビルド間や別CPUまで含む
再現性・信頼区間を主張するものではない。Go以外の改善を今回のJIT変更へ帰属させるには、
C側の命令配置やプロセスごとのexecutor構成の影響もさらに切り分ける必要がある。

## 次の作業

Goでは、残る未対応callの種類別に動的な復帰回数を細分化し、default argument・bound
method・keyword callのうち頻度の高いものを優先する。小さい前向きCFGだけのinline拡張で
復帰回数が減らなかった事実を基準にする。その後、joinを含むstack-cache signature伝播を
独立して測る。幅広いworkloadで改善が出るまでは20%目標を達成したとは扱わない。
