# pyperformanceの失敗・リグレッション修正（採用版V26）

元データは `jit-artifacts/pyperformance-four-way-current/`、今回の実験は
`jit-artifacts/pyperformance-fixes-20260917/`。開始日は9月17日、作業継続日は9月18日。
元の測定JSONとPGOバイナリは保存している。採用版をローカルにコミットし、
そのcommitから夜間比較用のビルドを作る。push・GitHub操作は行わない。

比較条件の訂正（9月18日）: 凍結したmainのFTソースでは
`_PyOptimizer_Optimize()` が `Py_GIL_DISABLED` 時に常に0を返す。
`sys._jit.is_enabled()` が真でもコンパイルは行われず、docutils・SymPyの
診断でもexecutorは0件だった。従ってFTはmainのインタプリタとmethod JITの比較である。
mainのフラグ・バイナリ・元の測定値は変更しない。

v16のGIL PGO/full-LTOとFTビルドは同一ソースで作成・検証済み。各2,178テストを通過した。
FT・GILの対象比較は完了した。以下のv6のPGO結果はv16の性能を表さない。
回帰が残っており、全体の解消はまだ達成していない。
最新のmain比較はv24。PGO/LTOなしの4構成で各902テストを通過し、
mainと同じ条件のGIL PGO/full-LTOビルドも作成した。
v17/v21を取り下げ、v18/v19とv22の所有権の最適化、v23/v24の入口処理の改善を含む。
v24のmain比較は両構成で完了した。2%以上の悪化はFTで7項目、GIL PGOで23項目に残る。
合計272回の測定は全て成功した。以下のv16のPGO結果は最新候補の結果ではない。
開発版はv25のgenerator改善とv26の部分method/既存ループ保持を採用した。
v26は4構成で各1,104テストを通過し、chaosの時間をFTで約6.8%、GILで約5.2%短縮した。
v27のCFG展開範囲拡大はtelco、argparse、B-tree等を悪化させたため戻した。
v28のcold block削減もGoをFTで約32%、GILで約40%悪化させたため不採用。
v29もGoをFTで約2.1%、GILで約5.8%悪化させたため不採用。
最終runtimeを検証済みv26へ戻し、全差分が保存済みv26とバイト単位で一致することを確認した。
これらの開発結果はv24のmain比と区別する。


## 失敗の調査と修正

| 項目 | 原因と対応 | 検証状況 |
|---|---|---|
| asyncio_websockets | 固定ポート8001の競合。新しいworkloadコピーでIPv4 loopbackの空きポートを割り当てる | 4ビルドのsmoke完了 |
| dask | cloudpickleが削除済みDELETE_GLOBALを必須として参照。存在しないopcodeを許容 | 関数のpickle往復、4ビルドのsmoke完了 |
| genshi | 必須フィールドなしでASTを生成。cloneと_newを修正 | XML/text出力検証、4ビルドのsmoke完了 |
| FT concurrent_imap / tornado_http | 複数スレッド時の意図的なJIT停止をフックがエラー扱い | 対象を限定して実状態を記録。4ビルドのsmoke完了 |
| GIL concurrent_imap | 短いI/Oを繰り返すスレッドがGILを再取得すると、他の取得待ちスレッドのタイムアウトが毎回リセットされる | 待機期限を保持する修正でdebug 100 Pools×3回、native/PGO+LTOの元の6 worker測定を完了 |
| FastAPI | cached pydantic-core/PyO3がPython 3.16を未対応としてビルドを拒否 | ABI確認を迂回せず未対応として残す |
| NetworkX k-core | 大規模Amazon graphの処理が指定の短い予算内に終わらない | 入力と15秒worker制限を維持 |

FTで停止を許容するのは指定したスレッド使用項目だけ。
`jit_enabled_at_start`、終了時の`jit_enabled`、`jit_suspension_observed`を保存し、
fallbackを観測した項目をレポートに列挙する。常時JIT有効・並列JIT実行を意味しない。
開始・終了時の検査なので途中の全状態遷移を捉えるものでもない。

Pool停止の調査では、glibcの条件変数内部で待つスタックも採取した。
しかし同じバイナリをローカルに展開したglibc 2.41で実行してもABBAの両試行が停止し、
glibc単独の不具合という仮説は棄却した。OSのライブラリとシステム設定は変更していない。
GIL修正は `take_gil()` の競合時だけを変更し、スレッドが実際に切り替わるまで
同じ待機期限を使う。引き渡し要求を送った後は通常間隔で再試行し、
保持側がCコード内にいる間の過剰な再試行を避ける。詳細は `bugs_report.md` のM-14に記録する。

smokeは5 specification、7 resultを4ビルドで実行した短い動作確認であり、性能評価ではない。
`compat-v4/{ft,gil-pgo-lto}/compare.md` に生データへの対応がある。
GIL nativeのPool本測定は元と同じ6 worker・5 warmup・5 value・60秒worker制限で、
両resultに6 workerがあることと、各workerのJIT/GIL状態を検証した。
PGO/LTOなしの修正ビルドなので、元のPGO測定との速度比にはしない。

## 性能の切り分け

同じ元バイナリのJIT有効／無効を逆順2ブロックで測定した。
各2 worker、3 warmup、3 value、CPU 2、pyperfの独立校正を使う。
これは環境変数を明示的にworkerへ継承した診断測定で、JIT状態フックは付けていない。

| Result | 候補/main（JITあり） | mainのJITあり/なし | 候補のJITあり/なし |
|---|---:|---:|---:|
| pprint_pformat | 1.216 | 0.841 | 1.020 |
| pprint_safe_repr | 1.163 | 0.872 | 1.020 |
| deepcopy_memo | 1.129 | 0.851 | 1.019 |
| logging_format | 1.161 | 0.866 | 1.022 |
| logging_simple | 1.185 | 0.861 | 1.046 |
| base64_small | 1.111 | 0.872 | 1.010 |
| telco | 1.142 | 0.807 | 0.941 |

時間比は小さいほど速い。pprintのJIT無効時はmainと候補がほぼ同じで、
mainのtrace JITによる改善を候補が失っている。大きな関数に不完全なmethodを作った場合も、
短い経路のtrace内展開を抑止していたため、抑止対象を完全なmethodに限定した。
修正後の通常ビルドでの比較と、最終PGO/LTO検証は進行中。

FT unpackは元の36%悪化に対し、同一バイナリの今回の測定では約20%悪化を再現した。
JIT無効でも約7%の差が残るため、すべてを生成コードの問題とはしない。
多数のlocal storeの退避・復元をまとめる最初の実装は、約35.6 nsから43.4 nsへ悪化した。
この結果も保持し、採用済みの高速化とは扱わない。小さい固定個数の専用命令化を検証する。

## 正しさの検証

- ハーネス: 19テスト。
- GIL native: 865テスト、8 skip。
- FT debug / native: それぞれ583テスト、12 skip。
- GIL debug: JIT関連583テスト。GIL修正後はthreadingを含む829テストとthread primitive 36テスト。
- 追加した内容: 複数代入のファイナライザ順序、重複代入先、部分methodの短い経路の展開、I/O競合下でのGIL取得進行。

GIL debugの一回のコマンドは存在しない`test_lock`も指定したため終了コードは失敗だった。
存在する5ファイルは完了し、指定を`test_thread`に訂正した追加実行も完了した。

## 途中の実験で分かったこと

PGO/LTOなしの開発ビルドで、main・修正前・修正後を逆順の2ブロック、
各2 worker・3 warmup・3 value・CPU 2・独立校正で比較した。
`compare_development.py`、`v3-*-state.json`、`v3-*-analysis.json` に
コマンド、ソース差分、バイナリ・依存SHA、workerの実効JIT/GIL状態、全測定値を保存した。
以下は **v3** の結果であり、追加開発中の候補や最終PGOビルドの結果ではない。

| GIL result | 修正前/main | v3/main |
|---|---:|---:|
| pprint_pformat | 1.156 | 1.007 |
| pprint_safe_repr | 1.179 | 1.017 |
| pickle_pure_python | 1.088 | 1.016 |
| deepcopy | 1.053 | 1.013 |
| deepcopy_memo | 1.159 | 1.051 |
| logging_format | 1.204 | 1.173 |
| logging_simple | 1.126 | 1.157 |
| telco | 1.066 | 1.079 |
| spectral_norm | 0.499 | 0.498 |
| richards | 0.941 | 0.943 |
| richards_super | 0.989 | 0.985 |

pprint等の改善は、不完全な大きいmethodが短い実行経路のtrace展開を阻害しない変更による。
不完全なmethodの継続先をside traceとして生成する変更も入れたが、それだけでは
loggingの差は解消しなかった。全体の回帰解消を達成したとは判定していない。

同一バイナリでmethodコンパイルだけを停止する診断では、trace JITを有効のまま維持し、
logging_formatが14.8%、logging_simpleが19.0%、deepcopy_memoが8.8%、telcoが5.2%改善した。
logging_silentは変わらなかった。診断スイッチは製品ソースから除去済みで、
専用バイナリ `build-method-jit/python-method-probe` と差分・SHAを保存している。
この結果を受け、頻繁に不完全な経路から脱出するmethodだけをentry traceへ切り替える
適応処理をv4で実装し、効果を測定する。まれな脱出はmethodとside traceを維持する。

`decimal-build-audit.json` によれば、比較対象5ビルドはいずれも `_decimal` を持たない。
従って今回のtelcoはpure Pythonのdecimalの測定であり、libmpdecの性能比較ではない。

unpackの試作は複数回失敗している。一般的なstoreの一括化はFTで35.6→43.4 ns、
固定個数への展開でも約43 ns、sequenceからlocalへの直接転送でも38.7 nsだった。
これらの不利な結果も保存している。現在は既存localと全要素が同一で、既存参照を
保持しても所有権が変わらない場合に限り、不要な代入と参照カウント更新を省く候補を検証中。
複数localが同じ旧オブジェクトの最後の参照を持つ可能性があるため、一括処理の安全性に
単純な `refcount > 1` は使わない。

v4のGIL debug/nativeでは各1,094テストが成功し、監視機能・フレーム・GC・threadingも含む。
FTと性能比較の結果は確認後に追記する。

## v4/v5で追加した改善と残る差

v4では、不完全なmethodが繰り返し脱出する場合に、そのコードのentryをtraceへ切り替える。
256 entryの窓で最低32回・半数以上がfallbackした場合に無効化し、コードにtrace優先を記録する。
まれなfallbackは従来のmethodとhot continuationを維持する。
通常のRESUMEによる再ウォームアップ・監視機能の検査は省略しない。
また、tuple/listの連続localへのunpackを直接転送し、既に同じ要素を所有している場合は
参照カウントを増減させるだけの代入を省く。借用中のmortal objectはこの省略の対象外。

| 対象比較のresult | FT v4/main | GIL・PGOなし v4/main |
|---|---:|---:|
| unpack_sequence | 0.7300 | 0.4960 |
| logging_format | 0.8934 | 1.0138 |
| logging_simple | 0.8673 | 1.0014 |
| logging_silent | 0.8995 | 0.9071 |
| deepcopy | 0.9674 | 1.0074 |
| deepcopy_memo | 0.8103 | 1.0399 |
| deepcopy_reduce | 1.0038 | 0.9856 |
| telco | 未測定 | 1.0257 |
| spectral_norm | 未測定 | 0.4959 |
| richards | 未測定 | 0.9336 |
| richards_super | 未測定 | 0.9723 |

元のFT回帰項目へ広げた別の比較では、deepcopy_reduceは0.9603になった一方、
docutils 1.0406、regex_dna 1.0391、regex_v8 1.0446、generators 1.0337、
gc_traversal 1.0576、asyncio_tcp 1.0267、SQLAlchemy declarative 1.0207が残った。
SymPyの補助ランナーは当初PYTHONPATHだけを使い、setuptoolsの`.pth`を処理しなかったため
`distutils`を見つけられなかった。元のvenvと同様にsiteを処理した再測定では
expand 0.8991、integrate 0.9909、str 0.9764、sum 1.0327。初回の失敗ログも残している。
この補助ランナーの問題を、CPythonや元のユーザー測定の失敗とは数えない。

v5では、本体の処理に到達せず複数のgeneratorへの委譲だけで終わるtraceを採用しない。
実際のgeneratorsのtraceにはSEND_GENのframe入場が6段あり、その先の処理に入る前に
Tier 1へ脱出していた。結果を処理するtrace、ループを完結するtraceは維持する。
FTのv5の短い比較ではgeneratorsはmain比約1.027で、これだけでは差を取り切れていない。

## 正規表現の配置による差

FTのv4とmainの`_sre`オブジェクトの`.text`はバイト単位で一致する。
SHA-256は `93df642a9598567a83f6d3eb7a96435d5cbc07e27eb71ecc2e401ef4f72c71af`。
同じバイナリのJITあり／なしの比較でも、mainとの差はregex_dnaで約3.8%／3.7%、
regex_v8で約4.3%／4.2%残る。従ってこの差をJITの生成コードだけに帰せない。

v5の全く同じオブジェクトファイルを、`.text`の開始位置だけ0/16/32/48バイトずらして
再リンクし、全4条件を順序反転して測定した。JITは無効、実効状態をworkerで検証。
これは実行環境のASLR設定を変えるものではなく、4条件の全データを保持する診断である。

| .textの移動量 | regex_dna / main | regex_v8 / main |
|---|---:|---:|
| 0 byte | 1.0000 | 1.0037 |
| 16 bytes | 1.0409 | 1.0433 |
| 32 bytes | 1.0224 | 1.0541 |
| 48 bytes | 0.9893 | 1.0292 |

ソース・機械語の命令列を変えずに元の約4%の差を再現できた。
ここで変えているのはnative `.text`全体の配置なので、個別のSRE関数だけの影響とは断定しない。
最速の配置を選ぶパッチは入れていない。通常手順でビルドした候補を使い、GIL待機修正を加えたv6で最終比較する。
この結果から、再ビルドによる数%の変化をそのままJIT最適化の効果と呼ぶことも避ける。

v5の正しさ検証は4構成それぞれ579件。追加の3テストはdebugの3:3リーク検査も成功した。
GCを止めるテストではexecutorの遅延解放待ちが残るため、既存の後片付けAPIを使う。
測定ハーネスの19テストも再度成功している。PGO/full LTOによる最終検証は進行中。

## v6のPGO+LTO構成での検証（中間候補）

GIL競合修正でhandoffを要求した後、次の待機期限を更新する。これにより、
GIL保持側がC内で処理を続けている場合の1µsごとの再試行を防ぐ。
v6のGIL debug/nativeはそれぞれthread/threadingの282テストに成功した。

新しいGIL・PGO・full LTOビルドは `after-pgo-build.json` に記録した。
バイナリSHA-256は `876561f96fb3213f9a535684278db15dee93f5ee8d679313738b712741bb86d5`。
mainと同じGCC、frame pointer、JIT無効・固定seedでの標準PGO学習を使う。
途中で止めたv5のプロファイルと、sandboxのsocket制約により失敗したv6の学習結果は
別ディレクトリに退避し、成功した全43ファイル・10,468テストのプロファイルを使用した。
PGO最終ビルドのJIT・generator・threading・monitoring・frame・GC検証は
1,088テスト成功、18 skip。ハーネスは既存controllerで19テスト成功。

元の回帰対象10 FT仕様、40 GIL仕様と10 GIL改善対象を同じCPUで逐次比較する。
2順序ブロック、各2 worker、3 warmup、3 valueの短い検証であり、元の全件6 worker
測定とは規模が異なる。性能値は完了後の `v6-*-analysis.json` を使う。

v6 FTの全10仕様・15 resultは両ブロックを完了し、前後のバイナリSHAも一致した。
以下は実行時間比で、1未満がmainより速い。区間は固定したバイナリ・ブロック内での
worker再標本化による95%区間であり、ビルド配置の変動や多重比較を補正していない。

| FT result | v6/main | 条件付き95%区間 |
|---|---:|---:|
| unpack_sequence | 0.7301 | 0.7295–0.7308 |
| deepcopy | 0.9765 | 0.9704–0.9826 |
| deepcopy_reduce | 0.9675 | 0.9620–0.9731 |
| deepcopy_memo | 0.8127 | 0.8097–0.8157 |
| regex_dna | 0.9947 | 0.9885–1.0013 |
| regex_v8 | 0.9975 | 0.9948–1.0003 |
| asyncio_tcp | 0.9763 | 0.9443–1.0114 |
| gc_traversal | 1.0181 | 0.9790–1.0634 |
| generators | 1.0168 | 1.0133–1.0203 |
| docutils | 1.0519 | 1.0477–1.0560 |
| sqlalchemy_declarative | 1.0245 | 1.0197–1.0293 |
| sympy_sum | 1.0335 | 1.0291–1.0380 |

SymPyの同じ仕様が出力するexpand/integrate/strも含めて保存し、それぞれ
0.9017/1.0058/0.9919。GC traversalはブロック別1.0455/0.9915と方向が異なり、
回帰解消を確定したとは扱わない。docutils、SQLAlchemy、SymPy sumの残差は
JIT有効／無効比較による追加調査の対象。

GIL PGO/full LTOでも `concurrent_imap` の元の6 worker・5 warmup・5 value・
60秒worker制限で両resultが33秒で完了した。測定12 workerのJIT/GIL状態と
前後のバイナリSHAを検証済み。これは停止修正の検証であり、mainとの性能比ではない。

## v6のGIL比較と追加診断

全50仕様・75 resultの比較が完了し、失敗は0件、前後のバイナリSHAは一致した。
全表は `jit-artifacts/pyperformance-fixes-20260917/v6-validation-summary.md`、
生データと区間は `v6-gil-pgo-analysis.json` に保存している。
元の46 resultの2%以上の回帰のうち、この短い比較でも2%以上残るものは22件。
別にxml_etree_iterparseが2%以上遅く、回帰をすべて解消した状態ではない。

logging・deepcopy・SORは元と同じ6 worker・5 warmup・5 valueで追加検証した。
logging_formatは1.0072、deepcopy_memoは1.0022であり、短い検証で見えた大きな差を
安定した効果量とは扱わない。遅いworkerを削除せず全データを保持している。

| 残る対象 | JITあり candidate/main | JITなし candidate/main |
|---|---:|---:|
| base16_small | 1.0836 | 0.9814 |
| scimark_sor | 1.0473 | 0.9976 |
| telco | 1.0578 | 1.0082 |
| dulwich_log | 1.0568 | 0.9998 |
| docutils | 1.0275 | 0.9998 |
| pickle_dict | 1.0492 | 1.0588 |

前5項目はJIT側の調査を続ける。pickle_dictにはJITを無効にしても残る差があり、
native runtime・ビルド側の寄与を切り分ける必要がある。全構成で_decimal拡張がなく、
telcoはPython実装のdecimalを使っていることも監査済み。

SORではmainがsetter内の添字計算をtraceへ展開するのに対し、候補はMETHOD_CALLを残す。
今回追加したUNPACK_TO_FASTはこの箇所で使われておらず、回帰原因には数えない。
base16のライブラリ実装もmainと一致しており、merge漏れではない。

## v7–v9の追加修正（開発ビルド）

v7は部分methodからの通常の型ガード脱出も退避判定へ数える。従来は未対応命令と
METHOD_CALLの失敗だけを数え、短い経路で型が変わった場合にmethodが残っていた。
修正前に失敗する専用テストを追加した。ただしFTのdocutils・SymPyの回帰は
この修正だけでは解消せず、その結果も `v7-ft-development-analysis.json` に残した。

v8は同じtraceフレームでbuiltins辞書のidentityガードを共有する。最初の確認は残し、
新しいフレームでは確認済みの状態をリセットする。カスタムbuiltinsのテストを含め、
追加テストはガードが4個の修正前には失敗し、1個にした後に成功した。
PGOなしGILのbase16_smallはmain比1.0536から1.0304、telcoは1.0164から0.9908。
ASCII85_smallは1.0030から1.0226へ悪化しており、全項目の改善を示す結果ではない。

v9は、小さなcalleeの冷たい未対応分岐だけをbytecodeへ戻し、対応済みの経路を
呼び出し元へインライン化する。元のサイズ制限、再帰展開制限、例外テーブル制限を
維持し、少なくとも1本のコンパイル済みreturnがある場合に限る。例外のtracebackが
calleeを指すこと、引数型の変化、calleeコードの変更による無効化を検証した。
4構成で各582テスト成功。以下はGIL・PGO/LTOなしの比較であり、最終PGO結果ではない。

| result | v8/main | v9/main |
|---|---:|---:|
| scimark_sor | 1.0087 | 0.9775 |
| deepcopy | 0.9685 | 0.9805 |
| deepcopy_reduce | 0.9724 | 0.9723 |
| deepcopy_memo | 1.0376 | 1.0376 |
| richards | 0.9677 | 0.9700 |
| richards_super | 1.0025 | 1.0060 |
| spectral_norm | 0.4977 | 0.4980 |
| go | 0.8974 | 0.8945 |

SORとdeepcopyは各ブロック6 worker・5 warmup・5 value、他は2 worker・3 warmup・
3 value。全項目を順序反転して測定し、失敗は0件、バイナリ・共有拡張の前後SHAを確認。
SORの両ブロックはmainより約2%速い。deepcopy_memoはなお約3.8%遅い。

## 採用しない候補: 完全methodの呼び出し失敗による退避（v10）

部分methodの退避判定を、METHOD_CALLを含む完全methodにも適用する候補を試した。
正しさの583テストは4構成で通ったが、固定v9/v10バイナリの順序反転比較で、
GILのGoが両ブロックとも約23%悪化した（実行時間比1.2312）。
GDBで退避時点を記録すると、`EmptySet.random_choice`、`Board.random_move`、
`Board.move`がそれぞれ32 entry / 32 missで無効化されていた。
呼び出しが完了しない場合でも、それ以前に実行するcompiled処理に効果があり得る。
単純な失敗率による適用拡大は採用せず、部分methodだけを判定するv9の実装へ戻した。

この候補のdocutils改善はFTで約0.9%、GILで約1.4%に留まり、Goの悪化を正当化しない。
`v10-{ft,gil}-pair-analysis.json`、全生データ、`v10-go-adaptation.log`、バイナリ
`python-v10`を保存した。v10は最終候補ではなく、速くなった項目だけを採用結果に混ぜない。

v11はv9にFTのCOPY_FREE_VARS入口処理を追加した候補として検証中。
通常のFT bytecodeと同じセル参照取得を使い、再帰・instrumentation・TLBCの確認後に
初期化する。クロージャ呼び出し後もJITで継続することを、従来GIL限定だったテストで
FTにも要求する。この確認はv10のFTバイナリでは失敗する。

## v12以降の検証中の変更

v12は既にインライン化された閉じたループを、呼び出し境界が残るmethodで
置き換えない。v11との開発ビルド比較ではGILのdeepcopy_memoが約9.2%、
FTが約4.4%短縮した。GoはGIL約2.1%、FT約1.0%増加しており、その試行も残す。
v13/v14の完全methodへのfallback学習拡張は、FTのRichards superが
それぞれ約4.5%/3.8%遅くなったため不採用とした。

v15は小さなcalleeの例外処理を理由とした一律のインライン化禁止を外した。
通常経路のみをコンパイルし、元のcalleeフレーム・例外処理位置を保持する。
捕捉・伝播・finally・tracebackを含む584件が4構成で成功した。
v12との順序反転比較ではFTの対象6件は概ね同等。GILではdulwich約1.7%短縮、
deepcopy約0.9%短縮、memo約1.2%増加。全てPGOなしで、最終構成の証明ではない。

v16はmethodの同一基本ブロック・同一フレーム内で、foldしたglobals/builtinsの
重複identity guardを省く。最初のguardと、callback後のexecutor validity検査を維持する。
異なるbuiltinsを使う同じcode、callbackによるglobal rebinding、呼び出し元のlocals
参照を追加検証し、4構成それぞれ585件が成功した。性能比較は進行中。

## 残存FT差のハードウェアカウンタ

固定v12とmainをCPU 2で順序反転し、imports/warmup後の同じ処理をperfで測った。
カウンタ区間はpyperfの内側タイマーとは異なり、ファイル入力やcache clearも含む。
従って以下の比をpyperformanceの時間比と同一視しない。

| カウンタのv12/main比 | docutils | SymPy sum |
|---|---:|---:|
| 命令数 | 0.950 | 0.927 |
| cycles | 1.028 | 1.072 |
| frontend uops not delivered | 1.182 | 1.204 |
| frontend-retired L1I-miss event | 1.452 | 1.141 |
| branch misses（別の順序反転run） | 0.988 | 1.075 |

命令数を減らす一方、命令供給の停滞が増えた。コード量・配置の影響と整合するが、
単一の変更が原因だと確定したものではない。各イベントは100%の期間で計測できた。
`residual-ft-{stat-v12-b,branches-v12,frontend-v12}-*` に全runを残す。
名前付きperf記録はexecutorを保持しており、GCへの影響が対称ではないため補助診断に限る。

## native pickleの小さな改善

memoのpointer hashを、単純な3bit右シフトから標準の`_Py_HashPointerRaw()`に変更した。
同じcore・JIT無効で差し替えたprivate extensionの比較では、GILのpickle_dictが
約0.9%、pickle_listが約2.2%短縮。FTの同2件はほぼ同等だった。
機械語は同じ長さで、9箇所のシフトが回転に変わる計18byteだけが異なり、
他の`.text`と配置は一致した。双方の構成で1,084 pickleテスト（57skip）が成功した。
元のPGOにおける約5%差をすべて解消した結果ではない。

## v16のmain相対比較（FT）

`final-ft-state.json`、`final-ft-analysis.json` に全試行と前後のidentity確認を保存。
18 specification / 23 result、2逆順ブロック、各2 worker、5 warmup、5 value、
最短0.1秒、CPU 2。元の全件測定の6 workerとは異なる対象限定比較である。
全呼び出し成功。時間比の幾何平均はブロック単位で計算した。

| Result | v16/main | 判定 |
|---|---:|---|
| asyncio_tcp | 1.0279 | 回帰が残る |
| deepcopy | 0.9295 | 改善 |
| deepcopy_reduce | 0.9646 | 改善 |
| deepcopy_memo | 0.7748 | 改善 |
| deltablue | 0.7952 | 改善 |
| docutils | 1.0462 | 回帰が残る |
| gc_traversal | 1.0326 | 回帰が残る |
| generators | 1.0288 | 回帰が残る |
| go | 0.8810 | 改善 |
| hexiom | 0.8599 | 改善 |
| raytrace | 0.8514 | 改善 |
| regex_dna | 0.9917 | 差は小さい |
| regex_v8 | 1.0093 | 差は小さい |
| richards | 0.3976 | 改善 |
| richards_super | 0.3859 | 改善 |
| spectral_norm | 0.3521 | 改善 |
| sqlalchemy_declarative | 1.0276 | 回帰が残る |
| sqlalchemy_imperative | 0.7910 | 改善 |
| sympy_expand | 0.9042 | 改善 |
| sympy_integrate | 1.0057 | 差は小さい |
| sympy_sum | 1.0515 | 回帰が残る |
| sympy_str | 0.9627 | 改善 |
| unpack_sequence | 0.7011 | 改善 |

上表の判定は2%を目安とする効果量の記述。信頼区間・各ブロック値はanalysis JSONにあり、
同一ビルド内のworker再抽出による条件付き区間で、ビルド・CPUをまたぐ再現性は表さない。
FT mainはJITコンパイルを実行しない。SymPyの別resultには改善があっても、sumの回帰を相殺して
解消済みとは扱わない。docutilsのGC診断と、GIL PGO/full-LTOの対象比較を続ける。

## v16のmain相対比較（GIL、PGO+LTO）

`final-gil-pgo-{state,analysis}.json` に全試行とidentity確認を保存。
50 specification / 75 result、2逆順ブロック、各2 worker、5 warmup、5 value、
最短0.1秒、CPU 2。200回の呼び出しはすべて成功。全suiteの再測定ではない。
PGOはmainと同じJIT無効・固定seedの学習タスクを使用した。

| Result | v16/main |
|---|---:|
| many_optionals | 1.1037 |
| async_generators | 1.0294 |
| async_tree_none | 0.9726 |
| async_tree_cpu_io_mixed | 0.9929 |
| async_tree_cpu_io_mixed_tg | 0.9869 |
| async_tree_eager_io | 1.0901 |
| async_tree_eager_io_tg | 1.0396 |
| async_tree_eager_memoization_tg | 1.0005 |
| async_tree_eager_tg | 1.0002 |
| async_tree_io | 1.0790 |
| async_tree_io_tg | 1.0652 |
| async_tree_memoization | 0.9953 |
| async_tree_none_tg | 0.9945 |
| base64_small | 0.9983 |
| base64_large | 0.9893 |
| urlsafe_base64_small | 1.0380 |
| base32_small | 0.9963 |
| base32_large | 0.9846 |
| base16_small | 1.0411 |
| base16_large | 0.9739 |
| ascii85_small | 0.9764 |
| ascii85_large | 1.0006 |
| base85_small | 1.0082 |
| base85_large | 0.9986 |
| chaos | 1.0882 |
| coverage | 1.0300 |
| deepcopy | 1.0136 |
| deepcopy_reduce | 0.9537 |
| deepcopy_memo | 0.9934 |
| deltablue | 0.9153 |
| django_template | 0.9493 |
| docutils | 1.0397 |
| dulwich_log | 1.0429 |
| fannkuch | 1.0138 |
| gc_traversal | 1.0162 |
| go | 0.9276 |
| hexiom | 0.8749 |
| logging_format | 1.0188 |
| logging_silent | 0.9263 |
| logging_simple | 1.0321 |
| meteor_contest | 1.0401 |
| nbody | 1.0292 |
| pickle_dict | 0.9721 |
| pickle_list | 0.9758 |
| pickle_pure_python | 1.0361 |
| pprint_safe_repr | 1.0219 |
| pprint_pformat | 1.0233 |
| raytrace | 0.9270 |
| regex_v8 | 1.0118 |
| richards | 0.9816 |
| richards_super | 1.0261 |
| scimark_fft | 1.0013 |
| scimark_lu | 0.9857 |
| scimark_monte_carlo | 0.9859 |
| scimark_sor | 0.9983 |
| scimark_sparse_mat_mult | 0.9915 |
| spectral_norm | 0.5524 |
| sqlalchemy_declarative | 0.9426 |
| sqlalchemy_imperative | 0.8879 |
| sqlglot_v2_normalize | 1.0393 |
| sqlglot_v2_parse | 1.0096 |
| sqlglot_v2_transpile | 1.0538 |
| sympy_expand | 1.0198 |
| sympy_integrate | 1.0095 |
| sympy_sum | 1.0395 |
| sympy_str | 0.9981 |
| telco | 1.0939 |
| tornado_http | 1.0060 |
| typing_runtime_protocols | 1.0057 |
| unpack_sequence | 0.4460 |
| xdsl_constant_fold | 0.9812 |
| xml_etree_parse | 0.9866 |
| xml_etree_iterparse | 1.0053 |
| xml_etree_generate | 0.8802 |
| xml_etree_process | 1.0220 |

2%以上の回帰は対象75結果中24件に残る。FT同様、比率はブロックごとの
時間比の幾何平均で、統計的不確実性はanalysis JSONに保存した。元の回帰項目と
改善確認用の項目を選んだ集合なので、この集合の平均をsuite全体の改善率にはしない。

`chaos`は候補worker間で約30.4〜33.9msに分かれ、mainは約28.8〜29.4msだった。
各worker内は安定しており、ウォームアップ不足やASLRの単独原因とは断定しない。
遅い試行も含めて集計した。`pickle_dict`の差は今回のビルドでは解消したが、
PGO・配置も異なるため、差の全量をハッシュ変更の効果とはしない。

次の試作は文字列キー辞書の直接コピーと、完成済みcaller loopを任意のmethod置換で
破棄しない選択である。採用前にそれぞれ独立した比較と正しさの検証を行う。

## v17: 辞書コピーの融合

`{**local_dict}` / `call(**local_dict)` の空辞書生成・local load・merge・cleanupを
まとめる。exact dictのうち、Pythonのコールバックを実行しないと証明できる場合だけ
コピーし、それ以外は元の空辞書生成より前に戻る。空辞書、Unicodeキーの辞書、
元のdict mergeがそのままcloneする密な一般キー辞書を対象とする。
`PyDict_Copy()`とmergeでは穴のある一般キー辞書の経路が異なるため、コピー可否を
単純に流用しない。衝突するキーで削除0/1/6件、split dict、任意mapping、
重複keyword、非文字列keywordなどを検証した。

FTのv17/v16比較は3 worker ×5 warmup ×5 value、最低0.1秒、CPU 2、逆順2ブロック。
全24呼び出しが成功し、前後のバイナリ・拡張モジュールのhashが一致した。
main比ではない。固定した1組のビルドについての結果であり、PGOへの外挿はしない。

| Result | v17/v16の時間比 |
|---|---:|
| docutils | 0.9944 |
| sympy_sum | 0.9917 |
| sqlalchemy_declarative | 0.9963 |
| go | 0.9931 |
| richards_super | 1.0034 |
| spectral_norm | 1.0104 |

生データとworkerごとの区間は `v17-ft-pair-{state,analysis}.json` に保存する。
改善は小さく、v16に残ったmain比の回帰を解消したとはいえない。

v17のGIL比較も完了した（13 specification /25 result、52呼び出し、失敗0、
前後のhash一致）。条件はFTと同じで、PGO/LTOなし。docutils1.0022、
SymPy sum1.0088、Go1.0072で、対象とした処理で明確な改善は確認できない。
urlsafe_base64_smallは1.0222（両ブロックで約+2.2%）、telcoは1.0199
（+3.7%と+0.3%）だった。後者のブロック差も保持する。
辞書融合の使用箇所だけでは説明できないビルド・配置の影響もあり得るため、
この差を辞書コピー処理の実行コストと断定しない。採用済みの広い改善には数えず、
この実験は最終候補から外す方向で検証する。

| GIL Result | v17/v16の時間比 |
|---|---:|
| docutils | 1.0022 |
| sympy_sum | 1.0088 |
| sqlalchemy_declarative | 1.0023 |
| go | 1.0072 |
| richards_super | 0.9963 |
| spectral_norm | 1.0022 |
| many_optionals | 1.0022 |
| chaos | 1.0016 |
| telco | 1.0199 |
| dulwich_log | 0.9931 |
| base64_small | 1.0080 |
| base64_large | 0.9992 |
| urlsafe_base64_small | 1.0222 |
| base32_small | 1.0145 |
| base32_large | 0.9996 |
| base16_small | 0.9928 |
| base16_large | 1.0011 |
| ascii85_small | 1.0164 |
| ascii85_large | 1.0011 |
| base85_small | 1.0073 |
| base85_large | 1.0014 |
| scimark_sor | 1.0072 |
| deepcopy | 1.0127 |
| deepcopy_reduce | 0.9997 |
| deepcopy_memo | 1.0040 |

生データ・区間は `v17-gil-pair-{state,analysis}.json`。

## v18: 融合命令によるサイドトレースの増殖

GILのasync_tree_ioを診断専用のexecutor一覧取得拡張で調べると、
`TimerHandle.cancel`のexit18から同じ属性書き込みで失敗するサイドトレースが54個
連なっていた。mapped領域は221,184 bytes（全548,864 bytesの約40%）。
perfの丸めたself sampleの合計で7.78%を占める。
executorの参照を保持した診断なので、この割合を速度改善率とはみなさない。

原因は、定数load・local load・属性storeの融合が、元の定数loadより前に
old valueの破棄可否ガードを移動したこと。tracerは4段ごとに先頭bytecodeの
実行を保証するが、後段の融合がそれを取り消していた。ガードに失敗する同じ
トレースを繰り返し生成・接続し、先頭に付いたexecutorもまたdetachされた。
mainにない融合処理の問題なので、mainのバグ一覧には追加しない。

進行を保証する必要があるtraceでは、抽象最適化の前後とも先頭bytecodeを融合の
対象から外す。小さなslot消去ループで、修正前の同じ融合を含むtrace数は
20K反復で5個、100K反復で26個、修正後は4個、0個になった。
最終化が一度ずつ実行されることと、定数load位置に進行するtraceが残ることを
回帰テストに追加した。凍結したv17では失敗し、v18では成功する。

GIL/FT × debug/nativeの4構成で各730テストが成功（GIL4 skip、FT13 skip）。
証拠は `v18-build-tests.json`、`v18-runtime-source.diff`、
`v18-before-test-c.log`、`v18-debug-focused-c.log`、
`v18-{before-progress-probe-c,native-progress-probe}.jsonl`。
GILの逆順比較は完了した。FTと最終main比の解消判定は継続中。

v18/v17のGIL比較は8仕様、32呼び出しがすべて成功し、前後のhashを検証した。
PGO/LTOなし、CPU 2、3 worker ×5 warmup ×5 value、逆順2ブロック。

| Result | v18/v17 | ブロックごとの比 |
|---|---:|---|
| async_tree_io | 0.9181 | 0.9101, 0.9261 |
| async_tree_io_tg | 0.9311 | 0.9358, 0.9264 |
| chaos | 1.0018 | 1.0104, 0.9932 |
| telco | 0.9906 | 0.9879, 0.9933 |
| many_optionals | 1.0137 | 1.0251, 1.0024 |
| richards_super | 1.0005 | 0.9967, 1.0043 |
| go | 0.9953 | 0.9859, 1.0048 |
| spectral_norm | 1.0006 | 1.0003, 1.0009 |

IOは8.2%、TaskGroup版は6.9%短縮し、両順序で再現した。固定ビルドの
worker bootstrap区間はそれぞれ0.9026–0.9290、0.9248–0.9376。
それ以外は小差またはブロック・workerによるばらつきがあり、改善と断定しない。
特にargparseの平均+1.37%も保持し、無視しない。
この比を古いPGOのmain比に掛けて解消済みとは判定せず、最終ビルドで再比較する。
生データは `v18-gil-pair-{state,analysis}.json`。

FTのv18/v17比較も24呼び出しすべて成功し、hashを検証した。
docutils1.0066、SymPy sum1.0004、generators0.9957、GC traversal0.9985、
Go1.0025、Richards super1.0047。いずれも1%以内で、GILで見られた大きな改善はない。
FTのmain比の回帰解消を意味する結果ではない。
生データと区間は `v18-ft-pair-{state,analysis}.json`。

## v19: 既存の閉じたループを任意の再コンパイルから保護

メソッドをコンパイルした際、既存のcaller traceを置き換える性能上の判断に限り、
すでに閉じたループを維持する。関数・型・globalsの変更による必要な無効化には
適用しない。4構成で各731テストが成功し、関数のcode差し替え時の無効化も検証した。

GILのv19/v18比較は32呼び出しすべて成功、前後hash一致。V17の辞書融合は両側に
含めて、この変更だけを比較した。FT比較も32呼び出しが成功した。

| Result | v19/v18 |
|---|---:|
| many_optionals | 1.0047 |
| telco | 1.0021 |
| chaos | 0.9985 |
| richards_super | 1.0105 |
| go | 1.0013 |
| docutils | 1.0035 |
| sympy_sum | 0.9976 |
| async_tree_io | 1.0012 |

この段階で広い改善は確認できず、Richards superの約1%悪化も保持する。
ループが記録される前にmethod entryが置かれるケースは、この保持処理だけでは
変わらない。生データ・条件付き区間は `v19-gil-pair-{state,analysis}.json`。

FTのv19/v18比はdocutils 0.9976、SymPy sum 0.9983、generators 0.9875、
GC traversal 1.0016、Go 1.0023、Richards super 0.9913、SQLAlchemy declarative
1.0041、asyncio TCP 0.9989。前後のhashは一致。広い改善とは判定しない。
生データは `v19-ft-pair-{state,analysis}.json`。

v20では効果の乏しいv17の辞書融合を削除した。4構成で各729テストが成功。
削除時に残った旧命令への期待値2件を元のテストに戻した再試行も記録している。
今後のフロントエンド選択実験の基準とし、削除だけの高速化効果は主張しない。

## v21の開発検証: 入口でのコンパイル方式の選択

凍結したPGO版のプロファイルではtelcoのmainに閉じたループが5件あり、
method JIT側にはなかった。関数入口を先にmethodとしてコンパイルすると、
その関数から呼び出し元へ戻って閉じるループを記録できない。そこで入口を
一度記録し、フレーム深さが元に戻るループならtrace、それ以外ならmethodを
選ぶ方式を試している。再帰呼び出しはmethodを選ぶ。

初期版はC経由のPythonコールバック中のループ記録を妨げ、既存テストの
多数のexecutor検査が失敗した。C呼び出しに入る前に入口探索を終了するよう
修正し、483件のJITテストが成功した。関数のcode差し替え、独立したmethod、
呼び出し元のループ、コールバック内のループを追加テストで検証する。
コールバック修正の最初の生成処理はDSL構文エラーで失敗したため、その後の
旧生成コードを使った検証は無効として記録した。修正後に再生成を確認している。
GIL debug/nativeの各899テスト（監視・フレーム検査を含む）は成功。FTを検証中。
この時点では性能改善の主張はしない。

v21は4構成で各899テストが成功した（GIL 12 skip、FT 21 skip）。
GILの逆順比較32呼び出しは全て成功し、前後のhashは一致した。

| Result | v21/v20 |
|---|---:|
| many_optionals | 0.9963 |
| telco | 1.0439 |
| chaos | 0.9977 |
| richards_super | 1.0262 |
| go | 1.0111 |
| docutils | 1.0043 |
| sympy_sum | 1.0087 |
| async_tree_io | 1.0030 |

両順序でtelcoとRichards superが悪化し、Goも平均約1%悪化した。
入口探索方式のGILへの採用は見送る。FT比較は継続中。
生データ・条件付き区間は `v21-gil-pair-{state,analysis}.json`。

FT比較も32呼び出しが成功し、前後hashが一致した。

| Result | v21/v20 |
|---|---:|
| docutils | 0.9981 |
| sympy_sum | 0.9885 |
| generators | 0.9871 |
| gc_traversal | 0.9812 |
| go | 0.9957 |
| richards_super | 1.0282 |
| sqlalchemy_declarative | 0.9942 |
| asyncio_tcp | 1.0251 |

小さな改善はあるが、Richards superとasyncio TCPの悪化を伴う。後者は
ブロック間の差も大きい。v21の入口選択方式はGIL/FTとも取り下げ、v20へ戻した。
測定データとバイナリは保持する。次のv22では独立した参照処理の改善を検証する。

## v22: 借用参照と不変定数の後処理

v20を基準に、算術・比較の入力の所有権情報を保持し、借用参照とimmortal定数への
不要な参照カウント更新を省く。短絡論理式のCOPYで生じたスタック上の同一値も追跡し、
真偽値と分かった後のPOPで、後続の属性の型情報を失わないようにした。
型・所有権が証明できない経路は従来の処理を維持する。

初期実装はローカル変数の出所と値の同一性を混同し、再代入前の値がスタックに残る
有効なバイトコードで誤った参照破棄を生成した。独立したCOPYグループ番号へ修正し、
再代入・外部呼び出し・制御フローの合流では破棄する。回帰テストは修正前バイナリで
assertion failureを再現し、v20と修正版で成功する。この不具合は開発途中のv22のみ。

GILあり・なしのdebug/nativeの4構成で各899テストが成功した。追加4テストは
両debug構成で3:3の参照リーク検査も通過した。テスト内のPythonジェネレータが
ローカルなクラスを保持する問題はv20でも再現したため、値の生成だけをCのstarmapに
変更し、修正前候補で実際のassertion failureが引き続き起きることを確認した。

短絡論理式から属性を読む診断では、GILのuop数38→33、FT38→34、型チェック2→1。
これは速度の測定値ではない。v20との逆順2ブロック、各3 worker・5 warmup・5 valueの
比較を実行中。PGO/LTOなしの開発版であり、v16のmain比較とは分けて評価する。

GILの32呼び出しは全て成功し、前後の実行物・標準拡張hashは一致した。

| Result | v22/v20 | 逆順2ブロック |
|---|---:|---|
| many_optionals | 0.9971 | 0.9960, 0.9983 |
| telco | 0.9834 | 0.9675, 0.9995 |
| chaos | 0.9966 | 1.0030, 0.9902 |
| richards_super | 1.0025 | 1.0043, 1.0008 |
| go | 0.9980 | 0.9959, 1.0001 |
| docutils | 1.0061 | 1.0102, 1.0020 |
| sympy_sum | 0.9855 | 0.9865, 0.9844 |
| async_tree_io | 0.9968 | 1.0049, 0.9887 |

telcoとSymPy sumの平均は短縮したが、docutilsは約0.6%増加した。全測定値を保持する。
mainとの比較ではなく、FTの結果も確認してから採否を判断する。

FTの32呼び出しも全て成功し、前後hashは一致した。

| Result | v22/v20 | 逆順2ブロック |
|---|---:|---|
| docutils | 1.0054 | 0.9955, 1.0153 |
| sympy_sum | 1.0023 | 0.9987, 1.0058 |
| generators | 1.0010 | 0.9971, 1.0049 |
| gc_traversal | 1.0116 | 1.0041, 1.0192 |
| go | 0.9937 | 0.9943, 0.9930 |
| richards_super | 1.0007 | 1.0116, 0.9900 |
| sqlalchemy_declarative | 0.9913 | 0.9892, 0.9935 |
| asyncio_tcp | 1.0080 | 1.0065, 1.0094 |

FTのGoとSQLAlchemyには小さい短縮がある一方、GC traversalは約1.2%、TCPは約0.8%増加した。
GILのtelcoのworker区間も約0.963–1.000で、平均の短縮だけから確実な改善とは断定しない。
v22は暫定採用し、入口の不要チェックを削減する次の候補でmainとの差を再評価する。

## v23/v24: methodの有効性チェックと未加熱の入口

v23は、`_START_EXECUTOR`で確認済みの有効性をmethodの制御フロー解析に伝える。
`_TIER2_RESUME_CHECK`は保留処理があればTier 2から退出するため、通常経路では
その直後の有効性チェックも不要になる。実際にPythonコールバックを実行し得る操作、
フレーム遷移、保留処理を実行して戻るループの検査の後は、必要なチェックを維持する。
これは既存のtrace側の扱いと一致する。

v23は4構成で各901テストを通過し、追加2テストは両debug構成で3:3のリーク検査も成功。
折り畳んだglobalの変更を、methodに入る前とlenのコールバック内の両方で検証した。
旧v22は新しい重複チェック削除の期待値だけに失敗し、無効化の検査には成功した。

v24は入口・backedgeのhotnessを先に検査し、まだ温まっていなければJIT有効フラグを
読まずにカウンタを進める。FTで別スレッドがいる間も温めるが、JITの停止は守る。
準備完了のカウンタを巻き戻さず、別スレッドの終了後にコンパイルできることを検証する。
新規テストの最初のrawカウンタ検査はbackoffの3bitを誤って含めていたため、countdown
だけの検査に訂正した。訂正版でも旧v23は8190のままで失敗する。
FTの最初のリーク検査では少数のmemory blockが残ったため、他のJITテストと同じ
executor削除リストのcleanupを追加し、再検証している。

性能比較はv24/v22で行い、この2変更の合計の効果として記録する。v23のバイナリも
保存しているので、悪化が見つかれば分離して調査できる。まだmainとの差の解消を
主張する段階ではなく、PGO/LTO版の更新も未実施。

v24は4構成で各902テストが成功し、FTの新規テストの3:3検査も通過した。
GILの比較32呼び出しは全て成功、前後hash一致。

| Result | v24/v22 | 逆順2ブロック |
|---|---:|---|
| many_optionals | 0.9911 | 0.9959, 0.9863 |
| telco | 1.0062 | 0.9978, 1.0146 |
| chaos | 1.0020 | 1.0033, 1.0007 |
| richards_super | 0.9999 | 0.9983, 1.0014 |
| go | 0.9974 | 0.9983, 0.9964 |
| docutils | 1.0007 | 1.0054, 0.9960 |
| sympy_sum | 1.0003 | 1.0042, 0.9965 |
| async_tree_io | 0.9837 | 0.9858, 0.9815 |

async_tree_ioの約1.6%短縮は両順序で観測した。telcoの約0.6%増加も保持する。
この表は入口処理2変更の合計であり、それぞれ単独の効果ではない。

FTの32呼び出しも全て成功し、前後hashは一致した。

| Result | v24/v22 | 逆順2ブロック |
|---|---:|---|
| docutils | 1.0006 | 1.0025, 0.9987 |
| sympy_sum | 0.9951 | 0.9935, 0.9967 |
| generators | 1.0084 | 1.0127, 1.0042 |
| gc_traversal | 1.0029 | 1.0079, 0.9980 |
| go | 0.9923 | 0.9916, 0.9929 |
| richards_super | 1.0018 | 1.0036, 1.0000 |
| sqlalchemy_declarative | 1.0055 | 1.0008, 1.0102 |
| asyncio_tcp | 0.9909 | 0.9790, 1.0029 |

FTの平均差はいずれも1%未満。generators約0.84%、SQLAlchemy約0.55%の増加も残す。
v23/v24を維持して、元と同じPGO/full-LTO条件のGIL版を作成し、mainと再比較する。

別の診断で、v24の大きなmethodのbranch cacheを採取した。通常の制御フローと、
cacheが一方向に揃った分岐だけを辿った場合の到達可能なbytecode数は、
Decimal._fixで313/54、__mul__で177/94、quantizeで226/123だった。
一方、argparseの_ActionsContainer.__init__は134/134で、この関数自身の
冷たい分岐を省く案では小さくならない。executorのuop数は順に732、849、916、1147。
これは実行回数の測定でも、実際の生成コード削減量でもない。例外ハンドラをrootにせず、
保持したexecutorを調べる診断であり、性能比較とは分離している。

冷たい経路を省くなら、飽和した分岐履歴を理由にループの正常終了経路まで省かない設計が
必要になる。今回はこの案を実装せず、v24のmain比較を先に完了させる。

v24のPGO/full-LTOビルドは完了した。最初の学習はsandboxがforkserverの
Unix socketを拒否したため失敗した。その351個のprofileを隔離し、ローカルソケットを
許可して同じ学習を最初から実行した。43ファイル・10,468テスト、460 skipで成功。
テストの省略や条件変更はしていない。最終バイナリのSHA-256は
`bd1cea28f945b03f5ac30bff3107a0a5be901c013b24634ba259eb394e11c159`。
追加検証は両構成とも2,187テストで成功した（GIL 76 skip、FT 91 skip）。
concurrent_imapも元の6 worker条件で両resultが成功し、JIT/GIL状態を確認した。
最終4ビルドの互換性smokeは20呼び出し全て成功した。ハーネス20テストと
ソース・実行ファイル・標準拡張の同一性検証も成功している。
runnerをv24のビルド記録へ更新し、mainとの比較を開始する。v16の記録は維持する。

## v24の最終FT比較（9月18日）

同じ18 specification・23 result、逆順2ブロックの72呼び出しが全て成功。
実行前後でバイナリ・構成・標準拡張のhashは一致した。時間比はv24/main。

| Result | 時間比 | 逆順2ブロック |
|---|---:|---|
| asyncio_tcp | 1.0278 | 1.0360, 1.0196 |
| deepcopy | 0.9265 | 0.9233, 0.9297 |
| deepcopy_reduce | 0.9667 | 0.9676, 0.9659 |
| deepcopy_memo | 0.7685 | 0.7705, 0.7665 |
| deltablue | 0.7922 | 0.7983, 0.7862 |
| docutils | 1.0468 | 1.0513, 1.0423 |
| gc_traversal | 1.0228 | 1.0188, 1.0269 |
| generators | 1.0320 | 1.0334, 1.0306 |
| go | 0.8587 | 0.8627, 0.8547 |
| hexiom | 0.8529 | 0.8524, 0.8533 |
| raytrace | 0.8500 | 0.8525, 0.8475 |
| regex_dna | 1.0181 | 1.0139, 1.0223 |
| regex_v8 | 1.0490 | 1.0488, 1.0492 |
| richards | 0.3987 | 0.3976, 0.3998 |
| richards_super | 0.3900 | 0.3903, 0.3898 |
| spectral_norm | 0.3542 | 0.3549, 0.3536 |
| sqlalchemy_declarative | 1.0253 | 1.0274, 1.0233 |
| sqlalchemy_imperative | 0.8003 | 0.8102, 0.7905 |
| sympy_expand | 0.8941 | 0.8988, 0.8894 |
| sympy_integrate | 0.9980 | 0.9981, 0.9979 |
| sympy_sum | 1.0396 | 1.0286, 1.0508 |
| sympy_str | 0.9501 | 0.9505, 0.9497 |
| unpack_sequence | 0.6988 | 0.6970, 0.7007 |

Go等の改善を維持する一方、2%以上の悪化が7項目に残った。regex_v8の約4.9%の
悪化はv16の約0.9%から大きくなっており、調査対象に追加する。regex_dnaの約1.8%も
悪化として残す。これらを同等と丸めず、原因を切り分ける。
対象を選んだ比較であり、全suiteの性能値ではない。各workerを保持した条件付き
95%区間は`v24-final-ft-analysis.json`に保存した。ビルド・配置の変動や
多重比較を含む区間ではない。GIL PGO/full-LTO比較は続行中。

FTで残る差の次の切り分けは以下の通り。原因の確定を意味しない。

| 対象 | 確認済みの事実と次の検証 |
|---|---|
| docutils / SymPy sum | 以前の診断では命令数が減ってもcycleが増えた。呼び出し境界とコード量を調べ、partial methodのループ保持を単独で比較する |
| regex_v8 / regex_dna | v23/v24の固定FTバイナリを比較し、直近の入口カウンタ変更を切り分ける。regex_v8はJIT有無でもnative処理を観測する |
| generators | タイマーは木の作成後の反復だけ。記録を試みて破棄するtraceの費用が残っていないか、元の計測区間で調べる |
| gc_traversal | タイマーは2回目のgc.collectだけ。生成したループの実行時間では説明できない。JIT有無のheap状態とnative GCを調べる |
| asyncio_tcp | 両順序で悪化したが差の大きさが異なる。ループ保持の修正後にも再検証する |
| sqlalchemy_declarative | greenlet省略は両側で同じ条件。JITの呼び出しと生成コードの費用を調べ、改善を維持したいimperative側と併せて比較する |

GIL側の既存chaosプロファイルでは、partialな`Spline.__call__`が、既存の
インライン化済みループを迂回していた。現在の保護条件はcomplete methodだけなので、
partialにも広げる小さな変更と再現テストを準備した。まだ実装には適用していない。
別の静的調査では、`GVector.linear_combination`は実命令40個・153 code unitで、
キャッシュ込み128というCFGインライン化の制限を超える。実命令数を基準にする案も、
このループ保持の変更と分離して検証する。いずれも現時点で改善率は未測定。

## v24の最終GIL PGO/full-LTO比較（9月18日）

50 specification・75 result、200呼び出しが全て成功。バイナリ・構成・
標準拡張のhashは測定前後で一致した。2%以上の時間増加は23項目。

| Result | v24/main | 逆順2ブロック |
|---|---:|---|
| many_optionals | 1.1021 | 1.0964, 1.1079 |
| async_generators | 1.0310 | 1.0325, 1.0295 |
| async_tree_io | 1.0239 | 1.0371, 1.0108 |
| urlsafe_base64_small | 1.0519 | 1.0543, 1.0494 |
| base16_small | 1.0603 | 1.0606, 1.0599 |
| base16_large | 1.0477 | 1.0532, 1.0423 |
| base85_small | 1.0752 | 1.0254, 1.1274 |
| chaos | 1.0871 | 1.1440, 1.0331 |
| coverage | 1.0379 | 1.0367, 1.0392 |
| docutils | 1.0303 | 1.0280, 1.0326 |
| dulwich_log | 1.0606 | 1.0402, 1.0814 |
| fannkuch | 1.0441 | 1.0471, 1.0411 |
| gc_traversal | 1.0416 | 1.0471, 1.0360 |
| meteor_contest | 1.0299 | 1.0318, 1.0280 |
| nbody | 1.0262 | 1.0259, 1.0266 |
| pickle_pure_python | 1.0309 | 1.0369, 1.0248 |
| pprint_safe_repr | 1.0516 | 1.0057, 1.0995 |
| pprint_pformat | 1.0272 | 1.0214, 1.0331 |
| sqlglot_v2_parse | 1.0321 | 1.0184, 1.0460 |
| sqlglot_v2_transpile | 1.0536 | 1.0474, 1.0598 |
| sympy_sum | 1.0487 | 1.0460, 1.0513 |
| telco | 1.0836 | 1.0838, 1.0834 |
| tornado_http | 1.0263 | 1.0423, 1.0105 |

以前の悪化が縮小した主な項目と、改善を維持した項目:

| Result | v24/main |
|---|---:|
| async_tree_eager_io | 0.9920 |
| async_tree_eager_io_tg | 1.0057 |
| async_tree_io | 1.0239 |
| async_tree_io_tg | 1.0145 |
| logging_format | 0.9887 |
| logging_simple | 1.0143 |
| richards_super | 1.0150 |
| go | 0.9420 |
| spectral_norm | 0.5511 |
| unpack_sequence | 0.4467 |
| sqlalchemy_declarative | 0.9362 |
| sqlalchemy_imperative | 0.8363 |
| hexiom | 0.8645 |
| raytrace | 0.9300 |

chaosとbase85_smallはブロック間の差が大きい。全workerを保持し、
条件付き区間と各ブロックを併記した。Base16の大きい入力は両順序で悪化している。
これは固定バイナリ間の結果であり、v16からの変化全てを新しいJIT最適化の効果とは
断定できない。JITを無効にした場合とnative処理も調べる必要がある。
完全な表・区間・SHAは`jit-artifacts/pyperformance-fixes-20260917/v24-final-comparison.md`
に保存する。リグレッションの全解消は未達成。

## v24の追加切り分けとv25の試作（9月18日）

v24/v23のFT比較で、入口カウンタの変更だけを切り分けた。
逆順2ブロック、各3 workerで全12回が成功した。比はv24/v23で、
regex_v8 1.00303、regex_dna 1.00174、generators 1.00767。
generatorsの区間は1.00461–1.01083で、この変更には小さい悪化がある。
regex_v8のmain比4.9%の差を、この変更だけでは説明できない。

元の関数・入力サイズを保持し、元の内部タイマーでperfを開始・停止する
診断も行った。FTのmain/v24、それぞれJIT有効/無効を逆順で測り、
stat 24回、record 12回は全て成功し、ファイルの同一性も検証した。
タイマー境界のFIFO制御が加わるため、その時間はpyperfの性能値として使わない。

- regex_v8: JIT無効でもv24/mainのcyclesは1.0583/1.0573。
  `sre_ucs1_match`が大半を占め、同関数の2,920命令はアドレス差を正規化すると一致する。
  この関数内の命令列の変更が原因ではない。配置や他の関数の寄与の切り分けは残る。
  過去のv5の配置実験は上記に保存しており、最速の配置を選ぶ変更は採用していない。
- gc_traversal: 命令数はほぼ等しく、cyclesの差は順序間で変動した。
  今回の診断から新しいGC実装上の原因は確定していない。
- generators: v24には218 uopの消費側トレースが付く。
  9回のSEND、子ノードの属性読み取り、GET_ITERを含むが、YIELDにも閉じたループにも到達しない。
  純粋な委譲だけを弾く既存の条件では、この準備処理を見逃していた。
  v24のJIT有効時は同じバイナリのJIT無効時より命令数が約0.67%増える。
  mainの最初のJIT有効試行は遅いが、削除せず保存している。

v25では、既に委譲に入ったトレース内の子ノード読み取りと反復開始も
「準備だけの接頭部分」に含める。算術、yield、閉じたループは対象外。
再現テストは修正前のGILあり・なしで失敗し、修正後FTの904テストは成功した。
繰り返し実行時のテストのコード状態を初期化する修正を加え、参照漏れと残りの
構成を検証中。**v25の性能改善はまだ確認しておらず、採用判断は測定後とする。**

生データは `v24-counter-ft-*`、`v24-ft-residual-{stat,record}-*`、
`v24-regex-native-*`、`v25-build-tests.json` に保存している。

V25の4構成は各904テストで成功し、追加2テストの3:3検査も両debug構成で成功した。
性能比較はFT 36回、GIL 24回、全て成功して実行前後hashも一致した。

| Result | FT v25/v24 | GIL v25/v24 |
|---|---:|---:|
| generators | 0.9828 | 0.9871 |
| async_generators | 1.0002 | 0.9993 |
| docutils | 0.9932 | 0.9932 |
| sympy_sum | 0.9954 | 0.9899 |
| richards_super | 0.9995 | 0.9972 |
| regex_v8 | 0.9980 | 未選定 |
| regex_dna | 1.0022 | 未選定 |
| sqlalchemy_declarative | 1.0017 | 未選定 |
| gc_traversal | 1.0040 | 未選定 |
| go | 未選定 | 0.9966 |

generatorsの条件付き95%区間はFT 0.98044–0.98541、GIL 0.97916–0.99385。
両順序で改善し、対照項目に明確な悪化はなく、v25を採用する。
区間は固定ビルド・固定ブロック内のworker bootstrapで、多重比較補正や
再ビルド変動は含まない。元のmainとの回帰解消は次のmain比較で判定する。

元のgeneratorコードによる追加確認でも、GILの212 uop、FTの218 uopの
準備だけのexecutorがv25では消えた。修正後のtest fixtureも凍結v24で
失敗することを再確認した。生データは `v2{4,5}-generator-original-*.json`。

## v26: 部分methodによる既存ループの置き換え

chaosのSpline.__call__には部分methodと、calleeを展開した閉じたループが共存していた。
既存の閉じたループを優先する条件を、冷たい未対応経路を含むmethodにも広げた。
METHOD_DEOPTを見つけた後も走査を続け、後続のMETHOD_CALLを見落とさないようにする。
冷たい経路を省く案やinline上限の変更は、この比較には混ぜていない。

修正前の両debug構成で新しいテストの失敗を確認し、修正後の4構成で各1,104テストが成功した。
coroutine/async generatorの検査も追加した。calleeの__code__変更による必須の
無効化は維持し、追加テストは両debugで3:3参照漏れ検査も成功した。
v26/v25の性能比較を実行中で、性能上の採否は未判定。

v26/v25のFT 32回、GIL 32回は全て成功した。chaosはFT 0.93245
（条件付き95%区間0.91860–0.94311）、GIL 0.94848（0.93343–0.96482）。
FT Goは0.98906。Richards SuperはFT 1.00688、GIL 1.00734で、両区間は1を含む。
他の選定項目にも明確な悪化はなかったが、小さい増加も含め全workerを保持した。
全表は `v26-pair-{ft,gil}-analysis.json` と `plan.md` に残す。

元のchaosの入力を使った事後観測では、Spline.__call__のmethod entryがtraceへ変わり、
GILで727→508 uop、FTで769→557 uopとなった。GetIndexのentryも閉じたループへ変わった。
Richards Superは採取した25 executorのopcode/oparg/target列が両構成で前後一致した。
この単独の診断は各pyperf workerの状態を代表しない。約0.7%の時間差の原因は未特定で、
配置によるものとは断定しない。

既存の20,000件B-treeの対照は24プロセス全て成功した。元のCLI・入力・検算を使い、
1 loop・3 warmup・5 value、各3プロセス、逆順2ブロック、CPU 2で比較した。
FT v26/v25は1.00086（0.99416–1.00878）、GILは1.00145（0.99821–1.00448）。
実行前後の入力・実行物・標準拡張・stdlibのhashと実効JIT/GIL状態も確認した。
chaosの改善を確認したv26を採用し、main比は最終ビルドで再検証する。

## v27: inline cacheと実行命令数の上限を分離（不採用）

small CFGの展開を実行命令128個までとし、bytecode/cacheの疎な解析表には
別途1,024 code unitsの上限を置いた。1段だけの展開と既存のuop数制限は維持する。
これにより、属性用のcacheが多い短い関数も展開の候補になる。

短いcache-heavy calleeの展開、処理が多いcalleeの呼び出し境界、型・calleeコードの
変更、callee内の例外処理を検証した。既存のcaller寿命テストもinlineされるように
なったため、calleeを32回のlen加算（129実行命令）へ延ばし、METHOD_CALLの検査を
維持した。callee自身のMETHOD_EXITも検査する。更新した寿命テストは旧v26でも成功する。
最初のfixture失敗は記録を残した。

4構成で各1,106テストが成功し、追加・更新3テストは両debugで3:3検査を通過した。
PGO/LTOなしのv27/v26比較を実行中。性能上の採否は結果が揃ってから判断する。

V27は不採用。V27の事前指定した72回のpyperf呼び出し、24回のB-tree対照は全て成功した。
GILではGo 0.97485、telco 1.02786、many_optionals 1.01278、docutils 1.00418、
deepcopy 1.00770、memo 1.00928。telcoとargparseは両順序で悪化した。
FT telco 0.98672の改善もあるが、リグレッション解消の目的ではV27を採用しない。
全測定・4構成の実行物・失敗を含む検証ログを保存し、変更した3ファイルのみ
V26とバイト単位で同じ内容へ戻した。runtime全差分もv26-runtime-source.diffと一致。
次にcold CFG案を独立したV28として検証する。

V27のB-tree対照ではGIL 1.13130（95%区間1.10891–1.15072）、FT .99021だった。
このGIL約13%の悪化も不採用の根拠として残す。

V28はV26を基準に、128実行命令を超えるroot methodの分岐履歴が0/65535の
経路を探索し、cold blockを元bytecode位置へのMETHOD_DEOPTへ置き換える。
全CFGで解析した保守的な状態を維持し、後方辺の区間とFOR_ITERの両辺は残す。
4テストを追加。変更前は3件が「cold blockが省かれない」assertで両debug構成で
失敗し、通常のループ終了のテストは成功した。既存のcomplete methodのテストは
両分岐を交互に暖めて、完全なmethodと既存の閉じたcaller loopを検査する。
V27の展開上限変更は含めない。4構成での正しさ確認後にV28/V26を比較する。

V28の最終検証は4構成で各1,108テスト成功（GIL 13 skip、FT 21 skip）。
追加4件と調整した既存2件は両debug構成の3:3参照漏れ検査も成功した。
4実行物をpython-v28として保存し、v28-runtime-source.diffを固定した。
V28/V26はCPU 2、各3 worker、5 warmup、5 value、min-time .1秒、逆順2ブロック。
FT 10仕様、GIL 8仕様と既存20,000件B-treeを事前指定し、逐次測定を開始した。
main比の結果ではなく、性能上の採否は未決定。

## V28の比較結果（不採用）

V28は不採用。72回のpyperf呼び出しと24回のB-tree対照は全て成功し、hashも確認した。
ft chaos: 0.99637, CI 0.98952–1.00381, blocks 0.99399/0.99875.
ft many_optionals: 0.98747, CI 0.97676–0.99945, blocks 0.98128/0.99369.
ft telco: 0.99590, CI 0.98168–1.01108, blocks 0.99605/0.99575.
ft go: 1.32024, CI 1.31335–1.32699, blocks 1.31740/1.32308.
ft richards_super: 1.00448, CI 0.98617–1.02429, blocks 1.02184/0.98742.
ft docutils: 1.00249, CI 0.99626–1.00896, blocks 1.01203/0.99305.
ft sympy_sum: 1.00230, CI 0.99151–1.01181, blocks 1.01084/0.99383.
ft sqlalchemy_declarative: 0.99974, CI 0.99091–1.00811, blocks 0.99768/1.00181.
ft generators: 0.99994, CI 0.99565–1.00460, blocks 1.00364/0.99625.
ft unpack_sequence: 1.00052, CI 0.99713–1.00428, blocks 0.99990/1.00114.
gil chaos: 1.01216, CI 0.99938–1.02560, blocks 1.02880/0.99578.
gil telco: 0.99331, CI 0.98753–0.99974, blocks 0.99523/0.99139.
gil go: 1.39556, CI 1.37280–1.41611, blocks 1.40548/1.38571.
gil richards_super: 1.00355, CI 0.99889–1.00921, blocks 0.99931/1.00780.
gil many_optionals: 1.00505, CI 0.99186–1.01866, blocks 0.99408/1.01613.
gil docutils: 0.99998, CI 0.99612–1.00400, blocks 1.00047/0.99949.
gil sympy_sum: 1.00106, CI 0.99293–1.00951, blocks 1.00425/0.99788.
gil deepcopy: 1.00235, CI 0.99401–1.01010, blocks 1.01095/0.99382.
gil deepcopy_reduce: 1.00812, CI 1.00222–1.01421, blocks 1.00354/1.01272.
gil deepcopy_memo: 0.99991, CI 0.99571–1.00417, blocks 1.00421/0.99564.
区間は同じ2ビルド・2ブロック内のworker bootstrapで、多重比較補正や再ビルドの変動を含まない。
GoはFT 1.32024、GIL 1.39556。B-treeはFT 1.00461、GIL .98208（GIL区間 .94719–1.00513）。
全試行を残す。V29はGoとB-treeを先に比較し、Goが両順序で2%以上悪化してworker区間も1を上回る場合、広い比較には進まない。

V29も不採用。4構成の最終各1,109テストと両debugの関連7件3:3検査は成功した。
事前指定したGo/B-treeの対照で打ち切り条件に達したため、他のベンチマークは測らない。
Go ft: 1.02099, blocks [1.0198703232901423, 1.0221171076089346], CI [1.0171083687807192, 1.023759008276752].
Go gil: 1.05769, blocks [1.0672843105020497, 1.0481740121233092], CI [1.0470991065786714, 1.0692968215957648].
GIL Goは両順序で2%以上悪化し区間の下限も1を超えた。FTも平均約2.1%増加。
B-treeはFT .98888、GIL 1.00362。改善した試行だけを選ばずV26へ戻す。
ユーザーの追加指示に従い、採用済みの修正と検証レポートをコミットし、そのcommitの
FT（PGO/LTOなし）とGIL PGO/full-LTOを準備する。mainの同条件2本と合わせて
夜間に実行できる4構成の全件比較をprepare-onlyまで行う。全件測定はユーザーが実行する。

## 夜間比較への引き渡し

採用版はV26。V27–V29の実験・失敗ログ・バイナリも残しているが、最終ビルドには含めない。
最新のmain比較はV24であり、回帰の全解消は未達成。V25/V26の開発比較はPGO/LTOなしで、
これらの比率をV24のPGO結果へ掛けて最新性能とみなすことはできない。

コミット後の検証・ビルド記録は `jit-artifacts/pyperformance-fixes-20260917/` の
`committed-final-{ft,pgo}-build.json`、`committed-final-correctness.json` に保存する。
GIL PGOはmainと同じGCC・full LTO・JIT無効の43テスト学習・seed 0を使い、
bootstrap時のプロファイルは学習結果と混ぜない。FTはPGO/LTOなし。
両構成のcommit、runtime/stdlib/build入力、実行ファイルと標準拡張のhashを照合する。

全件用の新規出力先は `jit-artifacts/pyperformance-four-way-fixed/`。
互換性修正済みworkloadと依存環境を準備し、全件測定はユーザーが夜間に実行する。
コマンドと失敗時の扱いは `benchmarks/pyperformance_four_way.md` を参照。
FastAPIは未対応として残り、NetworkXの15秒worker制限も維持する。
今回の本番比較によって、採用版V26のmain比と残っている回帰を改めて判定する。
