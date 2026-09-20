# C decimal対応と3%以上の回帰の調査（2026-09-19）

**作業中。全97仕様での3%以上の回帰の解消は、まだ未確認。**
作業ツリーはR34b（近接JIT mappingとテスト後始末）の統合候補。
同一ソースのR36 FT/GIL debug・release検証に成功した。
最新R36/mainのFT選択screenは13結果全て3%未満、失敗0。
最大はregex_v8の1.0179（95% CI 1.0107–1.0279）、docutilsは0.9996、sympy_sumは0.9914。
GIL PGO/full LTOのR36/main選択screenは24結果成功。ただしdulwich_log 1.0931、regex_v8 1.0691、pickle_pure_python 1.0339が残り、追加確認中。全97仕様は未実施。
以下は試作・却下案を含む経過記録であり、各表の候補名と基準を区別する。

## 比較条件とC decimal

mainは `d95f29589e03603aa13d8ca9d4f817dce77d357c` と既存LLVM 21対応patch。
候補の起点は `14defe7e06ef37956989e46c74710293d33df41e`。
各候補は新しいソース・ビルドdirectoryへ固定し、約3,943ソースのSHA、差分、python、
標準拡張、Makefile、pyconfig、compiler/linker設定、PGO profileを保存する。
証拠は `jit-artifacts/regressions-20260919/` のbuild manifest、state、analysis、logにある。

- FT: `--disable-gil`、PGO/LTOなし。
- GIL: PGO/full LTOあり。開発中の単独因子比較はPGO/LTOなしとして明示する。
- GCC 13.3、LLVM 21、`-O3 -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer`。
- 時間比はcandidate/mainまたは明記した因子間の比。1.03は実行時間3%増。
- CPU 2、seed 0、5 warmup、5 value、3 worker、min-time 0.1秒。
  同じ仕様でA/BとB/Aを続けて測り、worker平均を等重みに平均した2ブロック比の幾何平均。
- 95% CIは4,000回のworker bootstrap（seed 20260919）。固定binaryの測定不確実性で、
  ビルド配置・別CPUや多重比較を含む保証ではない。低速workerと失敗も保持する。
- 重いビルドと性能測定は逐次実行。CPU/電源/ASLR等のシステム設定は変更しない。

FT mainはJIT有効と報告するがexecutorを生成せず、実際はTier 1の基準となる。
FT候補は他のPython threadがある間JITを停止する既存方針を維持し、実効状態をmetadataへ記録する。
全体測定ではDask等の並列負荷に元のCPU集合を使い、単一CPUに縮小しない。

公式mpdecimal 4.0.1の配布物SHA-256は
`96d33abb4bb0070c7be0fed4246cd38416188325f820468214471938545b1ac8`。
専用prefixへFPあり・PGO/LTOなしでビルドした同じstatic libraryを全構成へリンクし、
公式・追加テストに成功。通常のimportで `decimal.Decimal is _decimal.Decimal` を確認した。
比較ハーネスもC backend必須にし、telco workerで拡張パスとlibmpdec版を記録する。

C decimalを含むPGO学習はJIT無効、seed固定、専用cold pycache、bootstrap profile分離。
初期main/candidateとも43ファイル10,623テスト成功。R9以後はC関連テストの追加により
10,628テスト等となり、件数差も記録する。再学習によって消えた差をJIT修正の効果とはしない。

## 作業ツリーの採用候補

| 変更 | 理由・確認できた効果 | 残る確認 |
|---|---|---|
| regex_compileの再解析抑止 | 閉じたcaller loopを理由にmethodを拒否した選択とbackoffを保持 | 最終統合版 |
| R2: 汎用unpackのexact tuple経路 | iterator生成を省く。R9/mainのGenshi text/XMLは0.9868/0.9934 | 最終統合版 |
| R3: 小さいunpackのstack cache維持 | traceの2/3要素は通常経路、methodと4要素以上は融合を維持 | 最終統合版 |
| R5: C hexの2文字復号 | R9/mainのbase16 small/largeは0.8195/0.7779。エラー優先度を維持 | 最終PGO配置 |
| R6+R12: C regex BRANCHの先頭判定 | capture保存前に不一致候補を除く。helperを必ずinlineしR12/R9 PGOのregex_v8は0.8976 | 最終main比較 |
| R11: strの予約型version | mainにもある未設定を修正。型version cacheからの解決と直接callを確認（M-15）、統合debug成功 | 最終release |
| R15: C ASCII85の5文字復号 | R15/R9開発版のsmall/largeは0.9426/0.9068。新旧134,928ケースで値・例外一致、統合FT/GIL debug成功 | 最終PGO |
| R16: tuple展開後の非escaping解放 | FTのunpack_sequence0.9814、SymPy sum0.9894。GIL開発版5項目0.9918–1.0005 | 最終統合版 |

C hex・ASCII85・regexはC処理の改善であり、JITによる効果と区別する。
R16は各要素が独立参照を得た後のexact tupleだけを対象とし、共有可変listは変更しない。
R16のFT debugで参照リーク3:3検査と関連7ファイル1,264テストが成功。
上表の利益は異なる基準・構成の値を混ぜて積算しない。

## 個別評価中・不採用の試作

| 試作 | 状態・判定 |
|---|---|
| R1: method入口index保持 | Genshi/argparseで明確な利益なし。不採用 |
| R4/R8: complete methodの退出監視 | Goの約14%後退を回復できず不採用 |
| R10/R13: 組み込みdescriptor直接call拡張 | GIL/FTで回帰を消す利益がなく不採用。独立のR11バグ修正は保持 |
| R14: 大きいmethodの入口guard退出監視 | GILでargparse1.0150、Genshi XML1.0187。対象methodの退出率は約39%で既存閾値50%に届かなかった。不採用 |
| R17: FT cellのowner/immortal参照取得 | 7結果でdocutils0.9943、SymPy sum1.0078等。明確な利益がなく不採用。rootから除去 |
| R18b: 分岐のある大きいacyclic methodの境界緩和 | GIL9結果・FT7結果で明確な利益なし。不採用 |
| R19: inline上限をcache抜きの実命令数で判断 | GIL/FT各4,546テスト成功。GIL開発版のSQL transpile0.9892、optimize0.9887。他7項目0.9985–1.0092。FT7結果は0.9942–1.0095、Go約0.47%後退。統合候補へ適用し最終main比較で再判断 |
| R20: GIL returnのframe解放を共有C helperへ | 19ファイル4,545テスト成功。stencil233→44 byte。開発版R9比でsuper0.9210、argparse0.9610、SQL transpile0.9768、pure pickle0.9914。9結果で最大1.0052。統合候補へ採用しroot適用済み |
| R21: methodの到達不能コード除去 | 通常・guard・例外edgeを確定後に圧縮。各4,547テスト成功。GIL6結果0.9937–1.0081、FT7結果0.9972–1.0145。回帰を消す利益がなく不採用、root未適用 |
| R22: 共有frame解放helperのFT経路 | 通常frameの所有権・解放順・stack予約期間を維持する試作。FT frame/cprofile/monitoringを含む22ファイル4,574テスト成功。12結果でsum0.9748、super0.9555、Go0.9816、argparse0.9811、最大1.0014。統合候補へ採用しroot適用済み |

R12のPGO比較はregexを改善した一方、base16 small1.0329/large1.0946、urlsafe base64
small1.0271等の別ビルド差も観測した。base16はR9/mainに十分な余裕があったが、
最終main比で再確認する。良い配置だけを選ぶ再ビルドはしない。

R21の静的診断ではSQLの358/5,748、FT docutilsの704/29,636、SymPyの1,087/13,840 uopが
到達不能だった。生成imageにはdata/paddingもあるため、imageサイズを純粋な機械語量と扱わない。
縮小だけで性能改善を証明したとはしない。

## 正しさ・測定の留保

初回のR15 fixtureはC APIのignorechars既定値を誤認して失敗し、明示指定へ修正して
同じbinaryで再検証した。R18初案は長い直線calleeまで境界を外して既存テストに失敗。
既存期待を緩めず、直線bodyとloopの境界を維持した別build R18bで全テストに成功した。
R21の初回fixtureのimport/C関数callは変換可能で退出を作らず、未対応のPython *args callへ
修正して対象問題を再現した。旧fixture・失敗ログをすべて保持する。

新テストを含むtest_optでTestUopsが順序依存の21失敗・1エラーになり、旧R9にも再現した。
外側TestSuite.runがC経由の内側suiteを実行中もtracerを保持し、新しいtraceを開始できない
ことをFT release・PYTHON_GIL=0の内部状態で確認。TestUopsクラスを既存subprocess隔離機構で
実行し、全テストを残したまま新旧とも成功した。R16の最初の参照リーク検査はexecutorの
遅延解放が残り、既存のcleanupを追加後に成功した。

最終snapshot R23cのFT debugは29ファイル4,906テスト（59 skip）と、tuple/inline/
保存frame/finalizer再入の4件の3:3リーク検査に成功。GIL debugも24ファイル4,863テスト
（46 skip）と同じ4件のリーク検査に成功し、両構成の3,943ソース一致を確認した。既存のmaterialized frameとfinalizer reentryのリーク検査は
旧R16/new統合版の双方で同じ失敗となり、既存パターンのexecutor遅延解放cleanupを
両テストへ追加して新旧とも成功。最終snapshot r23cへ含める。

C decimal→test_optの同一プロセス検査は以前mainでも順序依存で失敗しており、
通常のregrtestの成功と区別する。この特定順序はまだ再検証していない。
perfのexecutor保持mapはGC/寿命を変える診断で、通常の時間比には使わない。

過去の全体測定にはFT候補Daskのf_code参照中SIGSEGV、GIL main/candidateのGC付近の
SIGSEGV、SSL通信エラーやnetworkxのtimeoutが残る。fastapiは実行前の依存wheel準備に
失敗しており、PyO3がこのPython 3.16を未対応として拒否した。現時点で原因特定・修正済みとはしない。
次の全体測定で失敗を隠さず確認し、必要なら別途再現・修正する。

## 次の作業

R27のFT属性cleanup、R28bの大きなacyclic関数の入口trace選択、R29のhot receiver
型guardからの入口trace選択を独立に評価中。R26は効果がなく撤回した。
採用する変更を固定し、debugの寿命・例外・frame検証後、同じソースのFTとGIL PGO/full LTO
でmain比較を行う。以前の成功仕様と失敗仕様を含む全97仕様の比較も必要。
C decimal、全binary/拡張/source/依存/workloadの前後identityを検査し、3%付近はworker数を
増やした事前設定の確認測定で判定する。networkxのworker上限15秒は維持する。

新しいcommit、GitHubへの投稿、push、PR変更は行っていない。
試行ごとの経緯はplan.mdと `report-history-before-status-summary.md` に残した。

## C版ありの初期screen（r0）

両構成とも失敗0、測定前後のidentity一致。以下は3%以上残った結果。
選択した仕様のscreenであり、全ベンチマークの回帰一覧とはまだ呼ばない。

| 構成 | 結果 | 候補/main | 95% CI |
|---|---|---:|---:|
| gil | many_optionals | 1.1264 | 1.1078–1.1456 |
| gil | genshi_xml | 1.0923 | 1.0844–1.0997 |
| gil | genshi_text | 1.0785 | 1.0709–1.0856 |
| gil | dulwich_log | 1.0608 | 1.0206–1.1087 |
| gil | base16_small | 1.0577 | 1.0528–1.0623 |
| gil | nbody | 1.0562 | 1.0483–1.0642 |
| gil | sqlglot_v2_optimize | 1.0407 | 1.0349–1.0461 |
| gil | sqlglot_v2_transpile | 1.0401 | 1.0282–1.0508 |
| gil | pickle_pure_python | 1.0340 | 1.0255–1.0432 |
| ft | docutils | 1.0382 | 1.0298–1.0459 |
| ft | regex_v8 | 1.0361 | 1.0316–1.0393 |
| ft | sympy_sum | 1.0345 | 1.0273–1.0423 |

C版telcoはGIL 1.0111、FT 0.9922。元の5,000件の入力について、C/Python両backend・
全4実行物で同じ出力SHA `0abe923a18fc0268f442198542abcba203623a1e31136bd9e97a7a50343c5617` を確認。
pickle_listのGIL比は1.0020、pickle_dictは0.9926。regex_compileはGIL 0.9949、FT 0.8398。


## 統合R9のGIL PGO+LTO screen

11仕様22結果、失敗0、前後identity一致。全体suiteではない。

| 結果 | R9/main | 95% CI |
|---|---:|---:|
| many_optionals | 1.1065 | 1.1003–1.1131 |
| regex_v8 | 1.1005 | 1.0990–1.1022 |
| sqlglot_v2_transpile | 1.0623 | 1.0527–1.0729 |
| pickle_pure_python | 1.0502 | 1.0358–1.0651 |
| ascii85_large | 1.0485 | 1.0481–1.0490 |
| richards_super | 1.0384 | 1.0343–1.0430 |
| sqlglot_v2_optimize | 1.0288 | 1.0216–1.0348 |
| base32_small | 1.0237 | 1.0060–1.0559 |
| nbody | 1.0204 | 1.0169–1.0238 |
| dulwich_log | 1.0153 | 0.9895–1.0412 |
| base32_large | 1.0129 | 1.0060–1.0178 |
| base85_small | 1.0069 | 1.0027–1.0115 |
| base85_large | 0.9964 | 0.9960–0.9969 |
| genshi_xml | 0.9934 | 0.9782–1.0063 |
| ascii85_small | 0.9928 | 0.9922–0.9934 |
| base64_small | 0.9901 | 0.9891–0.9910 |
| genshi_text | 0.9868 | 0.9768–0.9977 |
| urlsafe_base64_small | 0.9843 | 0.9824–0.9863 |
| base64_large | 0.9812 | 0.9798–0.9833 |
| go | 0.9460 | 0.9360–0.9556 |
| base16_small | 0.8195 | 0.8186–0.8203 |
| base16_large | 0.7779 | 0.7739–0.7814 |


## 統合R9のFT screen

5仕様8結果、失敗0、前後identity一致。

| 結果 | R9/main | 95% CI |
|---|---:|---:|
| sympy_sum | 1.0506 | 1.0417–1.0591 |
| docutils | 1.0506 | 1.0407–1.0594 |
| regex_v8 | 1.0234 | 1.0224–1.0246 |
| sympy_integrate | 1.0168 | 1.0009–1.0389 |
| sympy_str | 0.9505 | 0.9478–0.9531 |
| sympy_expand | 0.8948 | 0.8918–0.8976 |
| go | 0.8588 | 0.8526–0.8659 |
| richards_super | 0.3853 | 0.3842–0.3862 |



## R23cのビルドと正しさ

FT releaseは29ファイル4,906テスト（61 skip）、GIL PGO/full LTOは24ファイル4,863テスト
（48 skip）成功。debugは上記のとおり両構成・4件のリーク検査に成功。
同一3,943ソースと同じlibmpdec.aでビルドし、全4構成のC backendを確認した。

- FT: `r23c-ft-release-build/python`、SHA-256 `283bd9d4f7927e3c4a5efa1ff58d7e040413e59a025de95840e1a1672339762c`
- GIL PGO/full LTO: `r23c-gil-release-build/python`、SHA-256 `897f9daf8195577eff39e69eab705cc0da5bc11fe1214cb404aa46f172657e8e`

パスは `jit-artifacts/regressions-20260919/` 以下。最初のmain比較はFT 9仕様、GIL 13仕様。
PGO学習は43ファイル10,632テスト（265 skip）で、追加テストのためmainより9件多い。

## 統合R23c/main FT screen

9仕様13結果、失敗0、前後identity一致。全体suiteではない。

| 結果 | 候補/main | 95% CI |
|---|---:|---:|
| docutils | 1.0341 | 1.0247–1.0440 |
| sympy_sum | 1.0264 | 1.0224–1.0303 |
| regex_v8 | 1.0141 | 1.0115–1.0171 |
| many_optionals | 1.0084 | 0.9975–1.0228 |
| sympy_integrate | 0.9968 | 0.9904–1.0023 |
| telco | 0.9550 | 0.9429–0.9685 |
| sympy_str | 0.9444 | 0.9391–0.9496 |
| genshi_xml | 0.9272 | 0.9161–0.9382 |
| sympy_expand | 0.8811 | 0.8792–0.8836 |
| genshi_text | 0.8705 | 0.8682–0.8728 |
| pickle_pure_python | 0.8556 | 0.8536–0.8576 |
| go | 0.8403 | 0.8345–0.8465 |
| richards_super | 0.3715 | 0.3685–0.3765 |

docutilsに3.4%の回帰が残る。sympy_sumは点推定2.6%だが区間上端は3.03%。
GILの比較結果も確認してから、残る回帰へ対応する。

## 統合R23c/main GIL PGO/full LTO screen

13仕様24結果、失敗0、前後identity一致。全体suiteではない。

| 結果 | 候補/main | 95% CI |
|---|---:|---:|
| pickle_pure_python | 1.0842 | 1.0773–1.0912 |
| many_optionals | 1.0674 | 1.0560–1.0784 |
| richards_super | 1.0571 | 1.0347–1.0760 |
| base85_small | 1.0523 | 1.0447–1.0596 |
| regex_compile | 1.0400 | 1.0309–1.0511 |
| nbody | 1.0389 | 1.0348–1.0437 |
| dulwich_log | 1.0367 | 1.0279–1.0466 |
| sqlglot_v2_transpile | 1.0332 | 1.0297–1.0368 |
| genshi_xml | 1.0324 | 1.0027–1.0809 |
| genshi_text | 1.0308 | 1.0208–1.0404 |
| sqlglot_v2_optimize | 1.0304 | 1.0199–1.0398 |
| base32_small | 1.0241 | 1.0222–1.0259 |
| go | 1.0120 | 0.9931–1.0418 |
| telco | 1.0114 | 1.0092–1.0137 |
| base32_large | 1.0102 | 1.0090–1.0115 |
| urlsafe_base64_small | 0.9997 | 0.9926–1.0042 |
| base85_large | 0.9960 | 0.9953–0.9968 |
| base64_small | 0.9924 | 0.9899–0.9941 |
| base64_large | 0.9899 | 0.9891–0.9905 |
| regex_v8 | 0.9756 | 0.9742–0.9770 |
| ascii85_small | 0.9364 | 0.9349–0.9380 |
| base16_small | 0.8615 | 0.8603–0.8629 |
| ascii85_large | 0.7958 | 0.7952–0.7964 |
| base16_large | 0.7954 | 0.7928–0.7984 |

11結果に3%以上の回帰が残る。共有frame helperのPGO版は179 byteで、参照を閉じる度に
`PyStackRef_CLOSE`をcallする一方、開発版はdecrefをinlineしていた。これは機械語の観測で、
全差の原因確定ではない。次に、通常のframe解放との共通化でこの経路をPGO学習させるR24を検証する。

## R24: 通常のframe解放と高速経路を共通化（検証中）

JIT専用helperを除去し、通常の `_PyEval_FrameClearAndPop` が同じ高速経路を使うよう変更。
これによりJIT無効の標準PGO学習でもその経路を実行し、Tier 1からも多段callを省ける設計とした。
参照の解放順、frameのunlink、stack領域を保持する期間、特殊frameのfallbackは維持する。
通常の経路も変わるため、profile/cprofile/sys_settraceを加えたFT 32/GIL 27ファイル、
4件の参照リーク検査、最終PGO/main比較を実施する。まだ性能改善を確認したとはしない。

R24 FT debugは32ファイル計5,388テスト（60 skip）と4件の3:3リーク検査に成功。
最初は古いテスト名test_cprofileの指定でその1ファイルをimportできず、既に通過した31
ファイルの結果を保持し、実際の `test_profiling.test_tracing_profiler` を同じ固定buildで実行した。
実装変更やテストの省略ではない。GIL debug以降は正しい名前を使う。

R24 GIL debugも27ファイル5,345テスト（47 skip）と4件の3:3リーク検査に成功。
両構成の3,943ソース一致と実行物・標準拡張・ソースの前後SHAを確認し、release検証へ進んだ。

R24 FT releaseも32ファイル5,388テスト（62 skip）に成功し、前後の固定identityを確認した。


## R24/main FT 選択screen

9仕様13結果、失敗0、前後identity一致。

| 結果 | 時間比 | 95% CI |
|---|---:|---:|
| sympy_sum | 1.0380 | 1.0289–1.0470 |
| docutils | 1.0321 | 1.0242–1.0393 |
| regex_v8 | 1.0202 | 1.0175–1.0223 |
| many_optionals | 1.0056 | 0.9999–1.0107 |
| sympy_integrate | 0.9931 | 0.9917–0.9943 |
| telco | 0.9550 | 0.9453–0.9638 |
| sympy_str | 0.9524 | 0.9486–0.9563 |
| genshi_xml | 0.9076 | 0.9038–0.9117 |
| sympy_expand | 0.8838 | 0.8823–0.8854 |
| genshi_text | 0.8828 | 0.8659–0.9005 |
| pickle_pure_python | 0.8446 | 0.8290–0.8545 |
| go | 0.8400 | 0.8356–0.8446 |
| richards_super | 0.3712 | 0.3700–0.3724 |

docutilsとsympy_sumが3%以上で未解消。GILを測定中。


## R24/main GIL PGO/full LTO 選択screen

13仕様24結果、失敗0、前後identity一致。

| 結果 | 時間比 | 95% CI |
|---|---:|---:|
| nbody | 1.0436 | 1.0417–1.0455 |
| many_optionals | 1.0366 | 1.0324–1.0404 |
| pickle_pure_python | 1.0243 | 1.0134–1.0353 |
| telco | 1.0241 | 1.0189–1.0293 |
| dulwich_log | 1.0177 | 1.0042–1.0314 |
| sqlglot_v2_optimize | 1.0115 | 1.0053–1.0173 |
| urlsafe_base64_small | 1.0111 | 1.0075–1.0139 |
| base32_large | 1.0089 | 1.0075–1.0101 |
| sqlglot_v2_transpile | 1.0072 | 1.0043–1.0104 |
| base85_large | 0.9963 | 0.9957–0.9969 |
| genshi_text | 0.9944 | 0.9776–1.0121 |
| regex_compile | 0.9918 | 0.9860–0.9981 |
| base64_large | 0.9895 | 0.9889–0.9901 |
| base85_small | 0.9894 | 0.9843–0.9936 |
| genshi_xml | 0.9873 | 0.9575–1.0131 |
| regex_v8 | 0.9839 | 0.9795–0.9893 |
| base32_small | 0.9752 | 0.9739–0.9762 |
| richards_super | 0.9414 | 0.9314–0.9486 |
| base64_small | 0.9378 | 0.9282–0.9433 |
| go | 0.9353 | 0.9334–0.9371 |
| ascii85_small | 0.8860 | 0.8841–0.8876 |
| base16_small | 0.8423 | 0.8412–0.8434 |
| base16_large | 0.8400 | 0.8372–0.8432 |
| ascii85_large | 0.7972 | 0.7966–0.7977 |

3%以上はnbodyとargparse。FTの2結果とともにJIT有効/無効の固定仕事量診断を行う。
pickle、telco、dulwichも最終確認に含める。選択screenの結果を全97仕様へ一般化しない。


## R24 残存4項目の固定仕事量診断


R24固定仕事量のJIT切り分け（各1組のperf stat。pyperfの代用ではない）:
ft docutils JIT=0: cycles 1.0195, instructions 0.9960。
ft docutils JIT=1: cycles 1.0372, instructions 0.9346。
ft sympy JIT=0: cycles 0.9881, instructions 0.9861。
ft sympy JIT=1: cycles 1.0601, instructions 0.9128。
gil argparse JIT=0: cycles 0.9925, instructions 0.9986。
gil argparse JIT=1: cycles 1.0020, instructions 0.9634。
gil nbody JIT=0: cycles 1.0031, instructions 0.9992。
gil nbody JIT=1: cycles 1.0425, instructions 1.0046。
FT SymPy/nbodyはJIT経路に差が残る。docutilsにはJIT無効時の差もある。
argparseの固定仕事量では差が小さく、実際のpyperf worker（512loops/5warmups/5values）
をprofileする。warmup長さ・呼び出し方・importでのspecialization等を区別し、
差が小さい診断値を通常pyperfの3.7%回帰の解消として扱わない。
FT docutils/sympy、GIL argparse/nbodyのJIT map付き診断も逐次実行する。
mapはexecutor保持がGC/寿命を変えるため、通常時間比に使わない。


## R25c: 定数list添字の試作

R24 nbodyはmain/candidateともトレースがhotで、`advance@600` はuop数415→394だが
image（data/padding込み）は16→20KiBだった。候補の借用入力の融合も含め、
0/1/2の定数添字を毎回Python整数から復号することを確認した。

exact compactな非負定数の添字を32-bit operandへ埋める専用uopを追加。
元の入力・退出・cleanup規約、FTのlist参照取得を維持する。負数や動的添字は既存経路。
list pair比較/len融合も、新uopで妨げないよう対応matcherを調整した。

要素差替え、list縮小・空listのIndexError、subclassへの切替を検査する新テストは
旧R24で未実装を検出した。GIL開発版では新テストが成功し、既存slice型伝播テストの
旧命令名の期待1件を更新後、同じ固定binaryでtest_opt 494件が成功した。
18ファイル1,691テストの元の失敗結果も保持する。期待を変えたのは命令名だけで、
型ガード1個という既存の検査と実行結果の検査は維持する。

R24 GIL non-PGO controlとFT候補をビルド後、GIL 6仕様・FT 5仕様を逐次比較する。
これは開発版の単独因子比較であり、最終PGO/mainや全97仕様の確認ではない。


## R25: 定数list添字の専用uop

exact compactな非負整数と判明したlist添字をoperandへ埋め込み、整数の符号・桁の取得と
負数補正を省く。入力のcleanupと退出先は維持し、現在のlist長さを毎回確認する。
要素の差替え、縮小・空listのIndexError、list subclassへの切替を検証した。
FT uop interpreterは既存のGetItemRefを使用する。native JITは既存の単一Python thread
制約に基づくtemplateを使い、スレッド開始時のJIT停止条件は変更しない。

GILはPGO/LTOなしのR24 controlとR25b（R25cとの差は既存テストの命令名期待のみ）、
FTはR24 releaseとR25cを比較。これはmainとの最終比較ではない。

| 構成 | ベンチマーク | R25/R24 時間比 | 95% CI |
|---|---|---:|---:|
| gil | genshi_text | 0.9969 | 0.9767–1.0173 |
| gil | genshi_xml | 0.9997 | 0.9907–1.0088 |
| gil | go | 1.0046 | 0.9957–1.0149 |
| gil | many_optionals | 0.9973 | 0.9915–1.0027 |
| gil | nbody | 0.9496 | 0.9446–0.9560 |
| gil | pickle_pure_python | 0.9966 | 0.9813–1.0119 |
| gil | richards_super | 0.9937 | 0.9904–0.9973 |
| ft | docutils | 0.9996 | 0.9925–1.0078 |
| ft | go | 0.9964 | 0.9943–0.9982 |
| ft | nbody | 0.9878 | 0.9817–0.9937 |
| ft | richards_super | 1.0004 | 0.9982–1.0025 |
| ft | sympy_expand | 1.0047 | 0.9954–1.0132 |
| ft | sympy_integrate | 1.0008 | 0.9967–1.0049 |
| ft | sympy_str | 0.9999 | 0.9931–1.0065 |
| ft | sympy_sum | 0.9867 | 0.9735–1.0000 |

GIL 7結果・FT 8結果は失敗0、前後のidentity一致。nbodyのGIL開発版は約5%改善。
FT SymPy sumはblock間差があり、回帰解消の判定は保留。docutilsの改善は確認できない。
R25c FTは21ファイル1,723テスト成功。R25b GILは旧sliceテストの命令名期待が1件失敗し、
期待名修正後、同じbinaryでtest_optの494件が成功した。失敗ログと修正fixtureも保存した。


## R26–R29の追加試作（最終main比較前）

R26は未inlineのPython callがあるacyclic methodのcaller tracingを許したが、
GIL argparse1.0068、FT docutils1.0048/SymPy sum0.9975で利益を確認できず撤回した。
GIL 3,658件・FT 3,690件の正しさ検証は成功。全測定を保存した。

R27はFTでもborrowed attribute receiverの不要なstack出力を削除する。
uop interpreterでは元と同じacquire load/TryIncrefCompareStackRefを保持する。
24ファイル3,705テスト成功。R28bは大きなacyclic bodyに未inlineのPython callが残るとき、
入口からtraceを選び、再解析を抑止する。19ファイル3,658テスト成功。

| 試作・基準 | 結果 | 時間比 | 95% CI |
|---|---|---:|---:|
| r27-vs-r25-ft | docutils | 1.0050 | 0.9978–1.0108 |
| r27-vs-r25-ft | go | 0.9910 | 0.9892–0.9931 |
| r27-vs-r25-ft | many_optionals | 1.0011 | 0.9897–1.0139 |
| r27-vs-r25-ft | richards_super | 0.9942 | 0.9897–0.9990 |
| r27-vs-r25-ft | sympy_expand | 0.9952 | 0.9845–1.0038 |
| r27-vs-r25-ft | sympy_integrate | 0.9966 | 0.9927–1.0004 |
| r27-vs-r25-ft | sympy_str | 1.0063 | 0.9954–1.0180 |
| r27-vs-r25-ft | sympy_sum | 1.0009 | 0.9853–1.0156 |
| r28b-vs-r25-gil | genshi_text | 1.0144 | 0.9996–1.0333 |
| r28b-vs-r25-gil | genshi_xml | 1.0068 | 0.9848–1.0295 |
| r28b-vs-r25-gil | go | 1.0075 | 1.0000–1.0169 |
| r28b-vs-r25-gil | many_optionals | 0.9873 | 0.9689–1.0061 |
| r28b-vs-r25-gil | nbody | 0.9990 | 0.9922–1.0070 |
| r28b-vs-r25-gil | pickle_pure_python | 0.9916 | 0.9811–1.0017 |
| r28b-vs-r25-gil | richards_super | 1.0062 | 1.0019–1.0106 |

R27はGo/superに小幅の利益があるがdocutils/SymPy sumを解消しない。
R28bはargparseの両blockが改善したが区間は1を跨ぐ。Go/superには約0.7/0.6%の後退。
最終PGO/mainでの判定はまだ行っていない。

初期R28には初回compileで未確保のco_executorsへprefer_traceを書き込む不具合があり、
test_optの新テストとtest_argparseでSIGSEGVとなった。性能測定には使っていない。
R28bは必要時に管理配列を確保してから記録するよう修正し、上記の全テストに成功。
旧試作・失敗ログ・差分は保持した。これは試作中の不具合でmainのバグではない。

R28b Genshiの元比較には0.003秒の単独テスト実行が重なったため、全workerを保持した上で、
同じbinaryの両blockを1回だけ再測定することを集計前に決めた。確認比較はtext1.0100
（CI0.9981–1.0287）、XML0.9700（0.9166–1.0069）。XMLの遅いmain workerも除外しない。
最終のGenshi判定は新しいmain比較で行う。

R29はcomplete methodの最初のself型guardからhot side traceが必要になった時、
methodをretireして入口traceへ移す試作。新しいper-callカウンタは追加しない。
tracerがexecutorを保持する既存寿命規約と、invalid時のfinalizationを使う。
旧FT版で新テストが失敗することを確認し、FT/GILの開発版検証へ進行中。
rootはR29b試作。R28bの入口trace選択はまだ統合していない。


## R29bの撤回・R30b/R31の試作

R29bのhot receiver guardでmethodをretireする案は、GIL/R25でargparse1.0253、
FT/R27でdocutils1.0140・SymPy sum1.0113となり撤回した。GIL7結果・FT8結果は
すべて失敗0、identity一致。strやsuperの改善も含め全結果を保存している。

R29b/main FTの固定仕事量カウンタでは、docutilsの命令数0.9332に対してcycles1.0377、
icache stalls1.5289・iTLB walks3.6566。SymPy sumは命令数0.9084、cycles1.0494、
stalls1.6434・walks2.7371。全5イベント稼働率100%。各1組の探索的診断で、
通常のpyperf時間比とも、特定の配置原因を確定する証拠とも区別する。

R30bは小さいclosure calleeにCOPY_FREE_VARSを一度だけ発行してinlineする案。
FT 4,183・GIL 4,135テストが成功し、別closure、cell変更/削除、例外tracebackを確認。
現在因子比較中で、main比の回帰解消とはまだ判定していない。
R31は既存padding内にJIT入口を分散する独立案。ページ数やstencil量を増やさず
命令cacheの競合を減らす仮説を検証する。未ビルド・未採用。

R30b最終因子結果はFT8結果・GIL7結果、失敗0・identity一致。FTのsumは0.9995
（block0.9774/1.0222）で改善が再現せず、docutils0.9983、Go1.0061。
GILもargparse1.0112、Genshi text1.0133、Go1.0053となり採用しない。
R31bは余白が丸1ページある場合でもentry offsetを1ページ未満に制限する。
fixtureのnative backend条件を含むr31c-integrated.patchでビルド開始。


## R31b: JIT入口配置の因子比較と低頻度の遅延

R31bは既存の末尾余白の範囲でentryを64-byte刻みに分散し、ページ数を増やさない案。
FT 4,006・GIL 3,965テスト成功。命令テンプレートの本文は各基準と完全一致した。
FT/R27ではdocutils0.9872（CI0.9812–0.9927）、super0.9711、SymPy str0.9840、
sum1.0024。GIL/R25ではnbody1.0304（CI0.9891–1.1001）となった。
候補1 workerがwarmupから約48.3ms（通常39ms）で安定して遅く、除外していない。
6worker×反転2blockの一度の追加確認ではnbody0.9945、Genshi text0.9988/XML0.9952。
元の遅いworkerを保持したまま、最終ビルドへの自動進行を停止した。

FTの固定仕事量カウンタを反転2blockで測ると、docutilsのcycles0.9861、命令数1.0001、
icache stalls0.9265、iTLB walks0.7513。SymPy sumはcycles0.9953、命令数1.0014、
stalls0.9497、walks0.7397。全イベント稼働率100%。通常pyperf測定とは別の診断である。

同じGIL binary内の私有配置カウンタを64初期値に変える別診断では、同じ主要uop列で
1プロセスが約54.3ms（通常39ms）に低下。ただし同じ初期値の2回の再実行では再現せず、
初期値だけを原因と断定できない。初期診断ツールのenum/ゼロ長stencil集計失敗も保持した。
R31dは1ページ以上のコードを従来配置に保ち、小さいbodyだけを分散する修正版。
FT 4,006・GIL 3,965テスト成功。GIL/R25はargparse0.9834、Go0.9919、nbody0.9987、他1.0021–1.0032。FT比較と追加診断を継続し、main比の回帰を解消済みとはまだ判定しない。

## R31d完了・R34近接mappingの試作


R31d FT/R27は9結果、失敗0・identity一致。
docutils: 0.9993（CI0.9888–1.0099）。
go: 0.9956（CI0.9915–0.9991）。
many_optionals: 0.9946（CI0.9909–0.9985）。
nbody: 0.9992（CI0.9930–1.0051）。
richards_super: 1.0030（CI1.0017–1.0044）。
sympy_expand: 1.0000（CI0.9855–1.0158）。
sympy_integrate: 0.9991（CI0.9929–1.0046）。
sympy_str: 0.9965（CI0.9923–1.0008）。
sympy_sum: 1.0058（CI0.9970–1.0144）。
docutils/sumは改善せず、配置だけでは残る回帰を解消できない。R31dの64条件診断も完了。
R31e method-only配置案は未実行のまま保留し、R34を独立評価する。
R34はR27を基点にPOSIX x86-64のmmap hintをインタプリタ付近に置く。
Linuxは既存patch_x86_64_32rxによるGOT間接call/loadの直接化、Darwinは既存trampoline省略
を期待する。MAP_FIXEDは使わず既存mappingを置換しない。hint無視・失敗時は従来の
遠距離relocation経路を維持。page数、W^X、allocation所有権は変更しない。
rootからR31dの配置変更を除いてR34へ置換し、FT/GIL開発版の正しさ・因子比較へ進む。

R31d配置診断64プロセスの平均時間範囲は38.95–40.46ms。
FT docutilsのfrontendカウンタ（R27比、反転2block）: cpu_core/cycles/u=0.9988, cpu_core/instructions/u=1.0001, cpu_core/branch-misses/u=1.0073, cpu_core/icache_data.stalls/u=1.0108, cpu_core/itlb_misses.walk_completed/u=1.3823。
FT sympyのfrontendカウンタ（R27比、反転2block）: cpu_core/cycles/u=1.0011, cpu_core/instructions/u=0.9993, cpu_core/branch-misses/u=1.0142, cpu_core/icache_data.stalls/u=0.9798, cpu_core/itlb_misses.walk_completed/u=1.0018。
全イベント稼働率100%。通常pyperf比較と診断を区別し、命令供給カウンタだけで原因を断定しない。

R34関連検証完了。FTは21ファイル4,006件（37 skip）、GIL開発版は17ファイル3,965件（21 skip）成功。
ft SHA: 4de62807fafabb2cdcce13e2ff3b054e70a32b508b9393463180c5ff7a1dbb7d。
gil-dev SHA: 10045f5d8dc69f8cd02915e13b8ca690961da659a00e8233f7d7470c328339d6。
両構成source/runtime identity一致。因子比較を継続し、成功時の同一patch最終検証R35を準備。
FT releaseはR34を再利用し、debug FT/GILとGIL PGO/full LTOを検証後mainと直接比較する。

R34/R25 GIL開発版の7結果・失敗0・identity一致で完了。
genshi_text: 0.9965（CI0.9910–1.0017）。
genshi_xml: 0.9807（CI0.9655–0.9939）。
go: 0.9804（CI0.9644–0.9899）。
many_optionals: 0.8739（CI0.8656–0.8813）。
nbody: 1.0003（CI0.9950–1.0059）。
pickle_pure_python: 1.0057（CI1.0025–1.0080）。
richards_super: 0.9933（CI0.9875–0.9991）。
argparseは両順序で約12–13%短縮。これは開発版同士の因子比較であり、PGO/mainの結果ではない。

R34/R27 FTの9結果・失敗0・identity一致で完了。
docutils: 0.9674（CI0.9612–0.9730）。
go: 0.9958（CI0.9941–0.9976）。
many_optionals: 0.9249（CI0.9223–0.9268）。
nbody: 0.9988（CI0.9957–1.0025）。
richards_super: 1.0013（CI0.9991–1.0036）。
sympy_expand: 0.9578（CI0.9501–0.9655）。
sympy_integrate: 0.9923（CI0.9870–0.9974）。
sympy_str: 0.9140（CI0.9083–0.9201）。
sympy_sum: 0.9575（CI0.9502–0.9643）。
単純なmethodの_RETURN_VALUEについて、FT/GILとも旧版はGOT間接call、R34は
_PyEval_FrameClearAndPopへの直接rel32 callと確認。生成コード・実アドレス・binary SHAを
r34-native-call-analysis.jsonに保存。これはnear mappingと既存relaxationが働く証拠であり、
各性能差の全てを単一要因に帰属するものではない。R35のdebug/最終release検証へ進む。

R34/R27 FT固定work診断（反転2block、イベント稼働率100%）:
docutils: cpu_core/cycles/u=0.9718, cpu_core/instructions/u=1.0013, cpu_core/branch-misses/u=0.8722, cpu_core/icache_data.stalls/u=0.9960, cpu_core/itlb_misses.walk_completed/u=0.7901。
sympy: cpu_core/cycles/u=0.9301, cpu_core/instructions/u=1.0006, cpu_core/branch-misses/u=0.6785, cpu_core/icache_data.stalls/u=1.0379, cpu_core/itlb_misses.walk_completed/u=0.8543。
通常pyperf比較とは別に保存し、計数範囲はimport/warmupを除く元benchmark関数全体。

R35 FT debug通常38ファイル5,542件成功（63 skip）。追加3:3反復で
constant_list_index_checks_current_sizeに[1,1,2]ブロックの残留。
固定6:10診断はR24の同じ境界値テスト（旧opcode名だけ適合）も+21、R35も+19。
clear_executors(read)とclear_executor_deletion_listの後始末を加えると両方-1で成功。
この既存パターンをテストに適用。初回診断driverはregrtestのCLI引数をtests位置引数に
誤って渡したため停止し、v2の正しい4条件の結果を採用。初回ログも保持。
R34bはこのテストの2行だけ変更しruntimeはR34と同一。R36としてdebug/releaseを
新規検証し、同一ソースのFTとGIL PGOを直接mainと比較する。
R35は未完成の検証記録として保持し、完了とは扱わない。

R36 FT debugは38ファイル5,542件（63 skip）と7種類の3:3参照リーク検査が成功。
定数リスト添字の後始末修正後は[-1,0,1]ブロック、合計0。JIT allocation/view/releaseも成功。
R34とR36の凍結ソース全件照合で差はtest_opt.pyの2行のみ、runtimeソースは同一。
patch SHA: accd970d82f07fcf222bf55a8d109a56b2afcd43d5d80dbe3ba0f2578b91618e。

R36 debug全体が完了。FTは38ファイル5,542件（63 skip）、GILは30ファイル5,476件
（47 skip）。それぞれ7種類の3:3参照リーク検査も成功し、凍結source/runtime identity一致。
GIL debug SHA: b990e6984715965f892df7326c5219b6ed9022383df6cac72b8361ff8d972c21。
FT/GIL release検証へ進む。最終PGO以外はPGO/LTOを使わない。

R36 FT releaseも38ファイル5,542件（65 skip）成功、source/runtime identity一致。
SHA: f25d4ff55e7f2c48f18c50febe252d0537f70a96110a4da9abf2d2919ab9d22e。C decimalの通常import確認済み。
GIL PGO/full LTOの学習用ビルドを開始。

R36 release検証完了。FTは38ファイル5,542件（65 skip）、GIL PGO/full LTOは
30ファイル5,476件（49 skip）、全て成功。両構成の全3,943 source SHA一致。
GIL SHA: 9d78e3358068c5bc3075c0c243a9ee636ec397a6b6b611e636d8f2a4a3923800。
PGOはgenerate306.6秒、学習139.7秒（43ファイル10,632件・265 skip成功）、final203.8秒。
通常C decimalとruntime/source identity検証に成功。mainへの選択screenを開始。

R36/main FTの選択screenが13結果・失敗0・identity一致で完了。
regex_v8: 1.0179（CI1.0107–1.0279）。
docutils: 0.9996（CI0.9973–1.0019）。
sympy_sum: 0.9914（CI0.9849–0.9977）。
sympy_integrate: 0.9843（CI0.9807–0.9881）。
telco: 0.9573（CI0.9443–0.9731）。
many_optionals: 0.9250（CI0.9218–0.9280）。
genshi_xml: 0.9034（CI0.8992–0.9073）。
sympy_str: 0.8776（CI0.8752–0.8798）。
genshi_text: 0.8662（CI0.8643–0.8680）。
pickle_pure_python: 0.8584（CI0.8560–0.8607）。
sympy_expand: 0.8488（CI0.8469–0.8507）。
go: 0.8223（CI0.8205–0.8244）。
richards_super: 0.3677（CI0.3672–0.3681）。
3%以上の回帰数: 0。全97仕様はこれから。

R36/main GIL PGOの選択screenは24結果・失敗0・identity一致で完了。
dulwich_log: 1.0931（CI1.0848–1.1001）。
regex_v8: 1.0691（CI0.9746–1.2106）。
pickle_pure_python: 1.0339（CI1.0268–1.0422）。
richards_super: 1.0098（CI1.0024–1.0185）。
telco: 1.0075（CI1.0028–1.0125）。
base32_large: 1.0051（CI1.0040–1.0061）。
nbody: 1.0009（CI0.9966–1.0050）。
base32_small: 1.0002（CI0.9965–1.0047）。
sqlglot_v2_transpile: 0.9998（CI0.9966–1.0031）。
sqlglot_v2_optimize: 0.9977（CI0.9950–1.0003）。
base85_small: 0.9977（CI0.9956–0.9998）。
base85_large: 0.9953（CI0.9949–0.9956）。
genshi_xml: 0.9934（CI0.9888–0.9972）。
genshi_text: 0.9860（CI0.9777–0.9941）。
base64_large: 0.9860（CI0.9856–0.9864）。
urlsafe_base64_small: 0.9818（CI0.9811–0.9825）。
many_optionals: 0.9631（CI0.9466–0.9760）。
base64_small: 0.9531（CI0.9521–0.9541）。
go: 0.9305（CI0.9271–0.9337）。
regex_compile: 0.9244（CI0.9186–0.9298）。
ascii85_small: 0.8891（CI0.8869–0.8915）。
base16_small: 0.8308（CI0.8277–0.8343）。
ascii85_large: 0.7979（CI0.7964–0.7994）。
base16_large: 0.7976（CI0.7924–0.8026）。
dulwich_log・regex_v8・pickle_pure_pythonに3%以上が残り、全97仕様queueは条件不成立で実行前に停止。
これは自動承認拒否ではなく性能条件のチェック。2.5%以上の全3仕様を6worker×反転2blockで
1回追加確認する。最初のscreenと遅いworkerは削除しない。
