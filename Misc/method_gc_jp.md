# tracing JITの最適化とmethod JITの比較

2026-09-20。比較対象は **`codex/tracing-jit` と現在のmethod JIT**。
ファイル名は依頼どおり `method_gc.md` とするが、tracing GCは対象に含めない。
既存の実装・保存済み測定結果を調査したレポートであり、新たな性能測定は行っていない。

## 1. 判断の要点

広いベンチマークで既に得られた利益は、GIL構成では両者ともmain比で
実行時間約3%短縮である。tracing JIT最適化は117結果で **0.97238**、
method JITは122結果で **0.97051**。ただしmainの版、PGO/LTO、対象集合、
測定手順が違うため、この差からmethod JITの方が速いとは言えない。
今回のmethod比較のmainは通常のupstream tracing JITであり、
**最適化済み `codex/tracing-jit` との直接対決ではない**。

実装労力についても、tracing側が小さな変更で済んだわけではない。
手書きruntimeコードの追加・削除はtracing側約11,700行、method側約12,800行。
tracing側は既存のコンパイラに多数の限定的な変換を追加し、method側は
コンパイラ入口・制御フロー解析・呼び出し・実行状態の管理を作り直している。
どちらも大きな実装と検証を要した。人時の記録はなく、行数を開発時間に換算できない。

現時点の評価は次のとおり。

- **特定のPython計算を大きく速くする実績はtracing側が強い。**
  Spectral Norm、Hexiom、Goなどに大きな利益があり、対象外への波及は小さい。
  ベンチマーク名を判定する実装ではなく、コードの形とguardを使う変換だが、
  利益が出るコードの範囲は狭い。
- **method側は、汎用的な最適化を積み重ねる基盤に投資した段階。**
  分岐の両側、merge、OSR、一般的なPython callなどを扱えるようになった。
  広いGIL suiteで20%短縮を実現した段階ではなく、古いtracing側の強い変換を
  全て置き換えたわけでもない。
- **FTではmethod側が一歩進んだが、並列JITは未完成。**
  FT interpreterに対して121結果で7.29%短縮した一方、2つ目のthread stateで
  JITを無効化する。tracing側の追加region最適化はFTを明示的に対象外としており、
  その性能結果もない。両者の「真の並列JIT対応工数」はまだ未払いである。

## 2. mainからの大まかな変更点

### 最適化済みtracing JIT

対象refは `codex/tracing-jit` の `26c62af79da3a0587e068692d35ae025ed4b9cc9`。
mainとの分岐点は `a60343ed17785ebbcd43de9080cadd8e2541db6f`。
`Tools/jit/optimization_report.md`、`Tools/jit/regions.md`、同branchの
`plan.md` §§21–23を主な記録として使用した。

既存のtrace recording、symbolic optimizer、side exit、stack cache、
copy-and-patchを維持し、その上に以下を追加している。

| 変更 | 狙いと実装上の負担 |
|---|---|
| checked i64・bounded整数region | 連続した算術・比較で中間PyLongを省略。overflow、任意精度への復帰、borrowed referenceの保持、元の例外位置を検証する |
| float融合・range reduction | 積和の中間表現、反復中のbox/unboxを削減。丸め順序、NaN、例外フラグ、alias、fallbackを個別に証明する |
| `len`とconsumer、文字列method、tuple/list比較、range/enumerate | builtin呼び出しの入口だけでなく戻り値の消費まで融合。exact type、mutation、iterator exhaustionなどを守る |
| 特定形状のcall・loopの置換 | 属性を返すleaf、属性list検索・削除、generator集約、float dot、Goの再帰的root探索など。callee全体の形を照合し、descriptor/default/instance overrideをguardする |
| globals依存とexecutor lifecycle | dictionary identityとversionを区別し、名前別依存で不要な失効を減らす。短いloopの再記録やexecutorの寿命も修正する |
| 生成・build基盤 | uop IDの並び、stencil入力、LLVM 21対応などを修正する |

性能測定は `PYTHON_JIT=1`、resident policy、6つの実験オプションを全て有効にしたもの。
追加regionは既定で無効であり、この結果を通常設定での利益として扱わない。
主要実装は `Python/optimizer_analysis.c`、`Python/bytecodes.c`、
`Python/optimizer.c`、`Python/optimizer_*region*.h` 等にある。

### 現在のmethod JIT

mainは `d95f29589e03603aa13d8ca9d4f817dce77d357c`。
測定時点のHEADは `14defe7e06ef37956989e46c74710293d33df41e` であり、
測定した実装には当時未コミットだったM56b差分も含まれる。今回、実装と本書を
一緒にローカルのcheckpointへ保存する。元の測定snapshotは末尾のpatch hashで特定できる。
[設計文書](../InternalDocs/jit.md)と
[最終結果](../benchmarks/method_only_m56b_results.md)を参照。

| 変更 | 狙いと実装上の負担 |
|---|---|
| 静的method frontend | recording dispatch・recorded value・side trace生成を削除。bytecodeからbasic block、stack depth、CFGを作り、条件分岐の両側を変換する |
| CFG上の値解析 | mergeでは全流入経路に成立する型・定数・所有権の事実だけを残す。Pythonへ再入する操作で失効し得る事実を捨てる |
| OSRと部分コンパイル | hot `RESUME`、backedge、generator loop bodyから入る。入口の生きた値を未確定として扱い、非対応部分はTier 1へ戻す。無益なentryや再コンパイルを抑制する |
| Python call最適化 | 実frameを維持したbounded inline、callee executorへの呼び出し、constructor、`__getitem__`等を扱う。再帰、defaults、関数の置換、例外・監視を維持する |
| 共通算術・参照・属性最適化 | int/float region、guard・参照操作の削減、型・関数version、名前別global依存、module属性、default metaclassの`isinstance`等を利用する |
| generator境界 | 通常generatorのresume/yieldとconsumer bodyを扱う。native generator間接続は測定で不利だったため撤回。coroutine/async generator等にはTier 1経路が残る |
| FTの限定対応 | FT用の所有権・定数制約、thread state公開前のexecutor失効、JIT停止を実装。workerで実際のGIL/JIT状態を記録する |
| JIT外の修正 | C側のcodec・regex等の改善、GIL handoff関連の修正を含む。全体の利益をmethod frontendだけに帰属できない |

uop IR、symbolic optimizer、stack cache、copy-and-patchは再利用している。
tracingを廃止しても、guard、deoptimization、依存関係、native codeの寿命管理は必要である。
また、先行tracing実験の限定的なrange/call変換が全てmethod側へ移植されたわけではない。

## 3. 広いベンチマークで実現した性能

時間比は各候補の実行時間 / **それぞれの固定main**。小さいほど速い。

| 比較 | 成功した主集計 | 幾何平均 [95%区間] | 実行時間短縮 | 点推定で改善 |
|---|---:|---:|---:|---:|
| tracing最適化、GIL、PGO/LTOなし | 117 | 0.97238 [0.97100, 0.97375] | 2.76% | 76 / 117 |
| method、GIL、PGO/full-LTO | 122 | 0.97051 [0.96825, 0.97310] | 2.95% | 67 / 122 |
| method、FT、PGO/LTOなし | 121 | 0.92705 [0.92648, 0.92763] | 7.29% | 99 / 121 |

tracing側はpyperfの既定検定で51改善・33回帰・33有意差なし。
method側はworker bootstrap区間の上端が1未満の結果がGIL 57件、FT 96件。
**検定方法が異なるため、これらの件数の差を有意な改善の広さの差としては扱わない。**
いずれの区間も固定buildでの実行時変動を扱い、独立再ビルドや他CPUへの再現性は含まない。

### 比較条件と欠測

両時期とも同じIntel Core i5-12450H、通常の単一workerはCPU 2、GCC 13.3、
LLVM 21を使用したが、同一実験ではない。

- tracing側は2026-09-15のGIL・O3・PGO/LTOなし。96仕様を要求し、
  93仕様から119結果を得た。`deepcopy_memo` / `deepcopy_reduce`のloop数不一致を
  除いて117結果を主集計にした。119結果を含む参考値は0.97232。
  FastAPIは事前除外。websocketsのport競合、Dask/cloudpickle、Genshiの互換性で欠測した。
- tracing側のA/Bは**異なる仕様集合**で、Aはmain先行、Bは候補先行。
  各結果で双方6測定processを使用したが、同じ結果を両順序で測った設計ではない。
  bootstrapは20,000回。A/B各集合の幾何平均0.96106 / 0.98034を、
  同一workloadの順序効果として解釈してはいけない。
- method側は2026-09-20の全体比較。各仕様でmain先行・候補先行の2 block、
  各側3 worker/block、5 warmup・5 value、独立校正。bootstrapは4,000回。
  FastAPI依存とNetworkX k-coreの15秒worker timeoutが両構成で欠測し、
  FTはさらにmainのDask SIGSEGVで不完全な組を除外した。失敗runは保持している。
- method GILだけがPGO/full-LTOなので、旧tracing側との比率の差にはbuild条件が入る。
  method FTのmainはexecutorを生成しない。FTの7.29%は**FT interpreterに対する利益**であり、
  tracing JITに対する利益でも、並列threadのscaling結果でもない。
- method側は全4 buildでC `_decimal`を検証した。旧tracingレポートには
  `_decimal`がない時点の記録があり、旧全体比較には現在と同じbackend検証がない。
  同じresult名だけでDecimal等の実行経路が同じとは保証できない。

### 同名結果に揃えた参考比較と利益の集中

旧117結果とmethod GIL/FTの両方にある名前は116件。旧集合の `k_core` が欠ける。
この集合で再集計すると、tracing側 **0.97349**、method GIL **0.96724**、
method FT **0.92660**。名前の偏りを減らす参考値であり、main・入力・依存・buildの
同一性を新たに証明した比較ではない。比率同士を割ってmethod/tracingの速度比とはしない。

先行開発で直接最適化していた6結果
（`bpe_tokeniser`, `deltablue`, `go`, `hexiom`, `raytrace`, `spectral_norm`）と
その他を分けると以下となる。**事後的な説明用集計であり、その他も未探索のholdoutではない。**

| 同名集合内の区分 | 件数 | tracing / 旧main | method GIL / 新main | method FT / FT main |
|---|---:|---:|---:|---:|
| 直接最適化した6結果 | 6 | 0.70277 | 0.82501 | 0.75167 |
| 残り | 110 | 0.99095 | 0.97567 | 0.93723 |

tracing側は対象6結果で約29.7%短縮、残り110結果では約0.9%短縮だった。
効果が完全に対象だけに閉じているわけではないが、全体平均への寄与は偏っている。
method側はこの集計では対象外にも利益が見えるが、C修正やbuild条件を含むため、
「method frontendによって波及した」とはまだ分離できない。
特にmethod GILの `bench_mp_pool` / `bench_thread_pool` を除く全体の参考値は
0.97948であり、主結果の2.95%全てをPythonコード生成の効果として扱えない。

以下も各時期のmain比を横に置いたもの。行間の差は直接測定した候補間比ではない。

| 結果 | tracing GIL | method GIL | method FT |
|---|---:|---:|---:|
| `bpe_tokeniser` | 0.8013 | 0.8509 | 0.8026 |
| `deltablue` | 0.9462 | 1.0051 | 0.8793 |
| `go` | 0.7776 | 0.8660 | 0.8145 |
| `hexiom` | 0.5794 | 0.7771 | 0.8556 |
| `raytrace` | 0.7296 | 0.9712 | 0.9149 |
| `spectral_norm` | 0.4835 | 0.5641 | 0.4009 |
| `richards` | 1.0054 | 0.9082 | 0.7713 |
| `richards_super` | 1.0136 | 0.9979 | 0.7989 |
| `django_template` | 0.9169 | 0.9668 | 0.9454 |
| `chameleon` | 0.9444 | 0.9603 | 0.9085 |
| `unpickle_pure_python` | 0.9174 | 0.9888 | 0.8106 |
| `sqlglot_v2_normalize` | 1.0074 | 1.0628 | 0.9723 |
| `sqlalchemy_imperative` | 0.8826 | 1.0482 | 0.8701 |
| `base16_large` | 1.1240 | 0.8236 | 0.8277 |
| `base32_small` | 1.0539 | 1.1011 | 0.9405 |
| `regex_compile` | 1.0109 | 1.0073 | 0.8433 |
| `shortest_path` | 1.0179 | 1.1492 | 0.9812 |
| `sympy_expand` | 0.9665 | 1.1480 | 0.8996 |
| `bench_mp_pool` | 1.0073 | 0.3680 | 1.0022 |

method GILには10%超の回帰3件が残る。`shortest_path`は候補processが二つの速度群に
分かれ、原因未特定。旧tracingのBase16差もJIT無効で再現し、build/layoutや大きい
一時bytesの解放に敏感だった。いずれもfrontend方式だけの優劣の根拠にはしない。

旧standalone 6本の0.37909という大きな改善は、広いpyperformanceの0.97238と分ける。
そのstandalone集計ではSpectral Normが0.01866、残り5本は0.69232だった。
pyperformance版のSpectral Normは0.4835であり、同名でも仕事量と適用範囲が違う。
現在のlocal 8本のGIL 0.82743 / FT 0.74136も、全体suiteとは別の指標である。

## 4. 実装労力と保守・検証負担

同じ分類規則で `git diff --numstat` を集計した。tracing側は上述の分岐点から
`26c62af79da`まで、method側は上述のmainから現在の作業ツリーまで。
これは**完成差分の規模**であり、不採用実験、診断、再ビルド、検証に使った時間を含まない。

| 追跡済みファイルの分類 | tracing: files / 追加 / 削除 | method: files / 追加 / 削除 |
|---|---:|---:|
| 手書きruntime（Include, Python, Objects, Modules。test・生成物を除外） | 27 / 11,549 / 122 | 43 / 9,854 / 2,931 |
| tests（Lib/testとModules/_test*。生成物を除外） | 7 / 8,056 / 1 | 10 / 9,959 / 1,057 |
| 生成物（下記の定義） | 15 / 34,354 / 13,352 | 13 / 24,736 / 13,530 |

生成物は `*_generated.h`、opcode/uopのID・metadata、`Lib/_opcode_metadata.py`、
`Python/{executor_cases,generated_cases,optimizer_cases,record_functions}.c.h`、
`Python/opcode_targets.h`、`Modules/_testinternalcapi/test_{cases.c,targets}.h`、
`configure`、`pyconfig.h.in`。文書、ログ、JSON、ベンチマーク、build/生成ツールは
手書きruntimeの表から除いた。未追跡ファイルも含めない。
uopのreplicationで生成物は大きく増えるため、総diff行数をそのまま手書き実装量としない。

tracing側の追加が多いのは、個々のcode shapeを認識して置換するpassとuopが多いため。
小さな変換でも、型・参照所有権・alias・丸め・default変更・監視・副作用後の復帰を
個別に検証する必要があり、形状を増やすほど対応するmatcherとfallbackも増える。
成功した変換を局所的に有効化できる利点はあるが、範囲を広げるたびに別の証明が要る。

method側はfrontendの再構築、mergeでの事実の弱化、calleeとの接続、実frameと例外状態、
wide jumpのIP、generator suspension、無益なexecutorの抑制に大きな固定費を払った。
tracing関連の削除は将来の保守対象を減らすが、CFG compilerを保守する費用へ置き換わる。
source上の構造が一般的であることと、広い実プログラムで利益が出ることは別に検証する必要がある。

検証記録も異なる。tracing側の最終Go段階ではdebug/nativeそれぞれregion 229件に加え
Tier 3・optimizerを検証し、先行float段階では4丸めmodeの576ケース等を検証した。
旧レポートにはall-options-onのopcode形状期待の不一致や既存のrefleak未解決の記録もあり、
全構成・全テスト成功とはしていない。
method M56bでは両最終構成でoptimizer 578件、関連788件、C関連1,154件、
JIT無効のopcache 97件を実行して成功し、debug・新規refleak検証と生成器84件も成功した。
構成別skipや重複を含むため、件数を足して品質や開発効率の倍率にはしない。

## 5. free-threading対応に必要な追加労力

### 実装済みの範囲

tracing側の `Python/optimizer_regions.h:region_enabled()` は
`!defined(Py_GIL_DISABLED)` を要求する。Goのroot探索などにも明示的なFT除外がある。
したがって「GILで有効な最適化をFTでも検証した」実績はなく、FT対応費用が少なく済んだ
とは評価できない。単にその範囲を今回の実装から外していた。

method側はFT buildでnative実行し、型・所有権・失効・fallbackを検証した。
ただし `Python/pystate.c:add_threadstate()` は2つ目のthread stateを公開する前に
JITを停止してexecutorを失効させ、thread終了後も自動再開しない。
mutable global等の最適化にもGIL構成より強い制約を置く。
これはFT ABIでの単一thread JITと、安全な並列Tier 1への切り替えを実現する設計である。

### 並列にJITを動かすための残作業（設計上の見積もり）

以下はsourceから判断した作業項目であり、実装済みの費用や完了時期の見積もりではない。

| 課題 | tracing最適化をFTへ移す場合 | methodを真の並列JITにする場合 |
|---|---|---|
| mutable objectへのguardとアクセス | list/dict/属性/再帰chainのguard後に他threadが変更できる。GIL前提の直接走査・書き込み・borrowを再設計する | CFG解析で既知でも実行時競合は残る。loadとguard、参照取得、callback前後の事実をFTのアクセス契約に合わせる |
| コンパイル入力 | 実行中のrecorded値、specialization cache、tracer stateの寿命と同期を扱う | recorded値を持たない分の管理対象は減るが、bytecode・cache・type/function versionを整合した状態で読む仕組みが要る |
| 依存と失効 | globals/type watcherとtrace/side-exit graphの更新・実行が競合する | watcherとexecutor公開・entry patch・失効が競合する。method化だけでは解決しない |
| native code・定数の寿命 | 実行中のtraceと接続先を、他threadの失効・解放から保護する | 実行中のmethod、inlined callee依存、定数、return先を保護する。安全な解放時点を定義する |
| TLBCと所有権 | thread別bytecodeとexecutorの対応、共有objectの参照取得を検証する | OSR/entry patchとthread別bytecodeの対応を明確化する。単一thread制約で回避していた経路を再検証する |
| 検証 | 同時mutation、class/default変更、finalizer再入、thread終了、無効化の競合を追加 | 同じ競合に加えcompile/publication/OSR/inline returnを並行して検証する |

methodは記録経路やside traceの管理を消した分、並列化時の設計対象を減らせる可能性がある。
一方、tracing側にもmethod側にもborrowed reference、mutable container、watcher、
実行中コードの寿命という共通の難所がある。**methodへの移行そのものはthread safetyの証明ではない。**
今の7.29%を、これらの追加費用を払った後の多thread性能として予測することもできない。

## 6. 労力に対する利益と、次の投資判断

現時点の広いGIL性能だけを根拠に「methodへの大規模な移行費用が回収できた」とは言えない。
両者は異なる条件で約3%という同じ桁にあり、tracing側の方が大きく改善した対象も残る。
逆に、tracing側を単に過剰適応として全て捨てる根拠もない。
整数のbox除去、builtinとconsumerの融合、依存を細かくする技術は汎用的な部品であり、
形状依存の強い変換と分けてmethod側へ移せる。

次の開発では、既にあるmethod frontendを利用して、効果が確認できた中間表現の削減や
call/container操作を共通passとして移植する投資が妥当と考える。
一般的なCFG基盤と再利用可能な変換に利益が蓄積するかを測り、特定benchmarkのmatcherを
増やすだけの開発になっていないか、対象外を含むsuiteでも確認する。
C loop、allocation、I/O、startup支配の項目は、JIT以外の改善を別枠で評価する。

方式の優劣を直接判断する次の実験は、**同じmain、同じcompiler/PGO/LTO、同じ依存・
C backendで、upstream tracing / 最適化tracing / methodの3構成を比較すること**。
共通runtime修正を揃え、各workloadで測定順を反転し、最適化対象・その他・失敗を分けて報告する。
FTは「単一threadでJIT実行」と「複数threadでJIT停止」を区別し、並列JITの性能は実装後に測る。
このレポートでは、その新しいbuild・測定には着手していない。

## 7. 証拠と確認方法

- tracingの設計・歴史: `git show 26c62af79da:Tools/jit/optimization_report.md`、
  `git show 26c62af79da:Tools/jit/regions.md`、`git show 26c62af79da:plan.md`。
  文書前半の古いcheckpointの数字を、末尾の全体結果で置き換えずに混ぜない。
- tracing全体の生データ・解析:
  [summary.md](../jit-artifacts/pyperformance-rerun-current/summary.md)、
  [analysis.json](../jit-artifacts/pyperformance-rerun-current/analysis.json)、
  [ratios.csv](../jit-artifacts/pyperformance-rerun-current/ratios.csv)、同directoryの
  `a-{main,candidate}.json` / `b-{main,candidate}.json`。
  今回4 raw JSONのSHAを保存済みmanifestと照合し、各結果の6 process meanから
  119行の比率と117件の幾何平均0.9723832438を再計算して一致を確認した。
- tracing測定binary SHA-256:
  main `8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`、
  candidate `ebb86d4a70b9dda5c4f70d4d49196cc5a87986c41ced14951f73dd0eef2fb457`。
- methodの全結果・binary SHA・正当性検証:
  [M56b結果](../benchmarks/method_only_m56b_results.md)、
  [FT解析](../jit-artifacts/method-only-m56b-full/ft/worker-analysis.json)、
  [GIL解析](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/worker-analysis.json)。
  測定patchは `jit-artifacts/regressions-20260919/m56b-method-only.patch`、SHA-256
  `6c30ed6fec1151f4cd2354665dc95517779162b05fd0a31f496910af58fad573`。
  測定後の生成器2ファイルの整理は生成出力・コンパイル対象を変更していない。
- 本書の同名集合は旧CSVの `loop_matched=True` と両method解析の `rows` の積集合。
  各集合の集計は `exp(mean(log(candidate/main)))`。他の結果は事後に捨てていない。
  性能測定やruntime変更は追加せず、文書の数値・参照先・差分を検証した。
