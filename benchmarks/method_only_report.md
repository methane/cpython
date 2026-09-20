# Method JIT単独への移行と性能検証

この作業の条件は、候補からtracing frontend・記録dispatch・side trace生成を削除し、
mainと比較すること。2026-09-20のユーザー指示で性能条件を変更し、
個別の10%超過を許容して、全体の実行時間比の幾何平均が1.00以下を目標とする。
Pythonのsys.settraceとmonitoringは維持する。PEP 836のようにuop IR、共通最適化、
copy-and-patch backendとexecutorの寿命管理は再利用する。
既存のC実装修正も候補に含まれるため、時間比はブランチ全体の差を示す。

**完了。M56bは更新後の幾何平均の条件を満たした。**

GIL PGO/full-LTOは122結果の幾何平均0.97051（実行時間2.95%短縮、
95%区間0.96825–0.97310）、FT O3・PGO/LTOなしは121結果で0.92705
（7.29%短縮、区間0.92648–0.92763）。元のlocal 8も全64 run・checksum・
同一性検証に成功した。コンパイル対象のruntimeソースと生成コードは測定した
固定スナップショットと一致する。測定後に生成器2ファイルから未使用の旧tracing用
ハンドラを整理したが、再生成による出力変更はなく、生成器84テストも成功した。
GILにはshortest_path 1.14919、sympy_expand 1.14804、base32_small 1.10108が
残るが、全結果を含む幾何平均で判定した。FastAPI・networkx_k_core、FT mainの
Daskクラッシュによる欠測を成功例として数えていない。

全件の数値・区間・失敗・実行物・検証条件は
[最終レポート](method_only_m56b_results.md)を参照。
以下は以前の判定条件と中間候補を含む作業履歴。

M56bのGILなし全体比較が完了した。384 runを試み、比較可能な121結果の
逆順2 blockの幾何平均は0.92705223（main比7.29%の実行時間短縮）。
実行物・依存・workloadの同一性検証も成功し、個別の点推定にも10%超過はない。
FastAPIの依存、networkx_k_coreのtimeout、Daskのmain block 0のSIGSEGVが
欠測となる。Daskのほかの3 runは成功したが、失敗を捨てず仕様全体を集計から除いた。
GIL PGO/full-LTOの全体比較を開始した。区間推定、local 8、最終レポートはこれから。

GILあり・なしを別々に集計し、全結果と未完了項目を報告する。
未検証のtuple-isinstance最適化は実験差分として保存し、候補から取り除いた。
runtimeのソースは検証済みのM56bに一致する。境界確認の結果を再利用して、
全4構成のpyperformanceと元のlocal 8を順次実行する。以下の10%判定は、
条件変更前の履歴であり、遅い結果もそのまま保持する。

M56bのFT screenも全28 run・10結果で成功し、identity一致、全区間上端が
1.10未満だった。一度だけ予定した境界確認は、base32_small 1.10183
（1.10063–1.10309）、deepcopy_memo 1.09651（1.05581–1.13812）、
Genshi XML 1.09106（1.08586–1.09588）。全workerを保持している。
base32の10%超過を確認したため、全suiteへ進むgateが停止した。
runnerの更新・全suite・local 8はまだ実行していない。元のbase32 workerと
固定バイナリでmain/candidate × JIT 0/1の独立したperf診断を行い、修正する。
deepcopy_memoは点推定が条件内でも、プロセス間の二つの速度帯と不確実性が残る。

M55のFT最終screenは7仕様・10結果・全28 run成功、identity一致。
すべて95%区間上端も1.10未満だった。GIL側はSQLGlot normalizeの
1.10958が残る。独立したnative perfの4 runとdebug executor dumpを採取し、
SQLGlotのdfs/flattenの型判定で標準__instancecheck__の探索が残ることを確認。
M56ではその探索を静的に解決し、実行時のメタクラスversionをガードする。
__class__属性の独自実装・例外、__instancecheck__変更、メタクラスの
差し替えをテストする。新規2件はM55で最適化不足のassertionに失敗。
M56bでJITテンプレートの内部宣言を補い、debug関連1,366件と
新規2件の-R 3:3が成功。固定nativeでも関連1,366件が成功した。
全20 run成功・identity一致のM56b/M55開発比較では、SQLGlot normalizeが
0.95275（95%区間0.94545–0.95954）。Genshi text 0.99799、XML 1.00057、
nqueens 1.00410、dulwich 1.00575、unpack_sequence 1.00332だった。
最終FT debug、GIL PGO/full-LTOとFT releaseのbuild・検証・main比較へ進む。
これは同じmethod JIT間の開発比較で、mainの10%条件の達成はまだ未確認。

M56bの最終GIL screenは17仕様・36結果・全68 run成功、identity一致。
全点推定が1.10以下で、SQLGlot normalizeは1.06207（1.05111–1.07168）。
deepcopy_memo 1.09595、base32_small 1.09437、Genshi XML 1.08795は
95%区間が1.10をまたぐ。FT screen後、この3項目だけを同じバイナリ・
元のworkerスクリプト・固定ループ数・各側6 worker・逆順2 blockで
一度追加確認する。全workerを保持し、screenと確認結果を分けて報告する。
全suiteとlocal 8はまだ実行前で、全体の達成は未確定。

以下は固定M55と以前の候補の検証記録。
M55を固定して最終構成の検証を開始した。関連1,364件のdebug/native検証、
新規6件の-R 3:3、比較全20 runが成功し、identityも一致した。
M41（同じmethod JIT、非PGO/LTO）との比較は次のとおり。

- dulwich_log: 0.98596 [0.97749, 0.99602]
- genshi_text: 0.90435 [0.89866, 0.90960]
- genshi_xml: 0.97478 [0.96870, 0.98028]
- nqueens: 0.97285 [0.96857, 0.97648]
- sqlglot_v2_normalize: 0.99175 [0.98877, 0.99446]
- unpack_sequence: 0.77574 [0.77378, 0.77809]

FT debugの576件（42 skip）、関連788件（1 skip）、新規6件の-R 3:3も成功。
GIL PGO/full-LTOとFT O3（PGO/LTOなし）のbuild・検証が完了し、
mainとの最終構成の比較を実行中。C _decimalを使用している。
GILのSQLGlot normalizeは両順序とも約1.11で、10%条件をまだ満たさない。
Genshi XML・nqueens・dulwichの点推定は1.10を下回った。
両構成の測定後、独立したperf診断とexecutorの検査でSQLGlotを調べる。
全suite・元のlocal 8の再実行はこれからで、全体のmain比+10%条件は未達。
GIL最終screenは17仕様・36結果・全68 run成功、identity一致で完了。
SQLGlot normalizeだけが点推定で超過し、1.10958（95%区間1.10165–1.11812）。
Genshi XMLは1.09599（1.09001–1.10199）、deepcopy_memoは1.07616
（1.02740–1.12958）で、区間はまだ10%をまたぐ。
GILなしのscreenと、測定後に分離したSQLGlotのperf／executor診断へ進む。

以下は各中間工程の記録。

M55では、nqueensの診断で、実質SET_ADD/LIST_APPENDの1命令
だけの小さいexecutorが各yieldで出入りしていた。継続入口では実質的な処理が
2命令以上ある場合だけ生成し、単一命令はTier 1に残す。benchmark名には依存しない。
list/set双方のテストは修正前で失敗。M55のdebug関連1,364件と新規6件の
-R 3:3が成功し、固定nativeビルド・検証・比較へ進んでいる。

M54は関連1,363件、5件の-R 3:3、比較全20 runに成功しidentity一致。
以下はM41に対する非PGO比較であり、mainとの最終比較ではない。

- dulwich_log: 0.99249 [0.98396, 1.00195]
- genshi_text: 0.91854 [0.91499, 0.92238]
- genshi_xml: 0.97707 [0.96794, 0.98658]
- nqueens: 1.03737 [1.03492, 1.04002]
- sqlglot_v2_normalize: 0.98688 [0.97897, 0.99423]
- unpack_sequence: 0.77525 [0.77216, 0.77864]

M54では、M53eの診断で、Genshiのtuple型検査は通る一方、
融合したアンパック・代入の古いローカル値の解放検査で入口へ戻ると分かった。
継続入口では、解放がPythonを呼ばないと既に証明できる場合だけ融合し、
それ以外は通常の代入でfinalizerを実行してnative処理を続ける。
finalizerから見える代入順序のテストを追加し、診断用出力を除去して検証中。
unpack_sequenceも比較対象に追加する。以下は直前のM53の検証記録。

M53eでは、generatorを進める処理をTier 1に残し、その値を受け取る
ループ本体の位置へstatic method executorを置く方式を実装した。熱いbackedge
からbytecode上の継続位置・stack effectを決め、両分岐を静的に解析する。
実行経路の記録やside traceは導入しない。通常命令の入口にはadaptive counterが
ないため、executor破棄時のcounter更新をRESUME/backedgeに限定する。
入口の生成、global変更、iteratorと本体の例外、破棄後のbytecodeをテストする。
最初の試行では従来の空のloop executorが先に生成され、継続位置に至らなかった。
generator loopでは継続位置を先に選ぶよう修正した。関連1,361件と
新規3件の-R 3:3は成功。反復検査ではテストの再利用コードを初期化し、
前回のbackoff状態を引き継がないようにした。M53dの固定ビルドとnative
1,361件は成功したが、Genshiのcandidateがタイムアウトしたため比較を停止。
この不完全な比較は性能評価に使わない。入口のUNPACK_SEQUENCEでtupleの
ガードに失敗すると、同じENTER_EXECUTORへ戻り続ける問題を小さいテストで再現。
M53eはその場合に元の命令をTier 1で一度実行し、進行を保証する。
新規テストとGenshi再現は成功し、関連1,362件と新規4件の-R 3:3も成功。
固定nativeビルドの関連1,362件と全16 runも成功、identity一致。
M53e/M41はtext 0.99310、XML 1.03840、nqueens 1.03720、dulwich 0.99847、
SQLGlot normalize 0.99280。XML/nqueensが悪化しており、高速化としては未採用。
別の診断用debugビルドで入口のガードから戻る原因を確認する。

M52bは関連1,359件のdebug/native検証と-R 3:3、比較全16 runに成功。
M41比はtext 0.97977、XML 1.00906、nqueens 0.98325、dulwich 0.99787、
SQLGlot normalize 0.98723。空の入口の拒否にbackoffを付けることでM52の
Genshi +16〜18%の悪化は解消したが、XMLは従来版とほぼ同速。
main比10%以内という条件は未達で、最終PGO/FTビルドはまだ始めていない。

M51bは関連1,358件のdebug/native検証と新規2件の-R 3:3に成功。
全16 runが成功しidentityも一致。M41比はGenshi text 0.98413、XML 1.00812、
nqueens 0.98542、dulwich 1.00402、SQLGlot normalize 0.99367。
identity比較の参照数操作削減だけではXMLに大きな改善はなかった。
M49のnative generator接続削除、M45の通常generator RESUME対応、
M47/M50のEXTENDED_ARG修正は維持する。最終PGO/LTOとFT、全suiteの再検証は未完了。

以下の全suite結果は固定済みM40cのもので、最新版の結果ではない。

M46のgenerator間native接続は性能結果により不採用。M46bではGenshiがTypeErrorとなり、
その計測は無効として保存した。M46c/dでFOR_ITERの保存位置をEXTENDED_ARG
ではなく命令本体へ修正。M47では既設executorがprefixを置き換えた場合の
CFG復元順序も直した。いずれも単独の回帰テストを追加し、修正前で失敗、
修正後で成功した。M47の関連1,357件も成功した。

正しさの修正後も、非PGO比較は次のとおり悪化を残す。時間比の基準は
**同じmethod JITのM41**であり、main比較ではない。全worker・両順序を保持し、
両比較とも全16 run成功、identity一致。

| 結果 | M46d/M41 | M47/M41 |
|---|---:|---:|
| genshi_text | 1.04408 | 1.03085 |
| genshi_xml | 1.04799 | 1.05856 |
| nqueens | 1.04052 | 1.04178 |
| dulwich_log | 1.00090 | 0.99293 |
| sqlglot_v2_normalize | 0.99241 | 0.99885 |

別途M41/M46dのnative perfを4 run採取。nqueensはEvalFrameの割合が
19.39%から6.99%へ下がる一方、yieldごとのnative呼び出しが増えた。
JIT内で動く割合だけでは高速化とは判定できない。

M48は安定した可変global objectの読み出しを型未知のbindingとして埋め込む。
辞書watcherで置換・削除を検知し、__class__変更と独自の__bool__も維持する。
FTの埋め込みはimmortal限定のまま。効果を確認後、generator接続を再評価し、
FT・最終PGO/LTO構成・全suiteとlocal 8の検証へ進む。

ここからは以前の実験記録であり、各時点の計測と判断を保存している。

M40cは全開発検証・非PGOの15結果比較・最終buildの検証が成功し、
最終GILの10仕様26結果は**すべて95%区間上端も1.10未満**となった。
nqueens 1.0842 [1.0807, 1.0875]、logging_simple 1.0473 [1.0283, 1.0655]、
logging_format 1.0784 [1.0642, 1.0946]。全40 run成功、identity一致。
rangeのsmall-int cache利用と、Tier 1が変更済みの算術特殊化を再コンパイルする
修正を採用した。単発のguard missではmethodを無効化しない。

全97仕様・4構成の比較は `jit-artifacts/method-only-m40c-full` に保存し、
両構成とも95仕様122結果が成功、測定後のidentityも一致した。
fastapiの依存準備失敗とnetworkx_k_coreの短いtimeoutは未完了として残す。
時間比の幾何平均はFT 0.9281、GIL 0.9792。FTの点推定はすべて1.10未満だが、
GILではfloat 1.1181、genshi_xml 1.1118、deepcopy_memo 1.1094、
sqlglot_v2_normalize 1.1093、dulwich_log 1.1070、regex_v8 1.1009の6結果が超過。
genshi_textとlogging_format、両構成のconnected_componentsは区間が1.10をまたぐ。
元のlocal 8（SQLAlchemy含む）も両構成で完了し、すべて1.10未満、
checksum・identityも一致した。FTの比は0.3442–1.0063、GILは0.5233–0.9925。
[M40cの全結果・区間・失敗記録](method_only_m40c_results.md)を保存した。
**全体の10%条件は未達**であり、残る6結果とloggingについて、
JIT無効の順序を入れ替えた比較を完了した。28 run・12結果成功、identity一致。
JIT無効時はfloat 1.0034、genshi_xml 0.9539、deepcopy_memo 0.9816、
sqlglot_v2_normalize 1.0108、dulwich_log 0.9838、regex_v8 1.0320、
logging_format 1.0078。多くの遅延はJIT経路にある。
floatのprofileではconstructorのfunction version cache衝突により、
method側だけが初期化処理をTier 1へ戻していた。既知のinitializerを
inline候補へ渡すM41修正と回帰テストを追加した。修正前で失敗、修正後で成功。
debug/nativeのtest_opt 562件、関連589件、constructor 5件の-R 3:3検査が成功。
複数test fileを同じプロセスに置くと35件のuop期待値に失敗するが、同一順序の
M40cでも35件失敗した。これは別のtest隔離問題としてログを残している。
非PGO/LTOの直接比較ではfloatがM40c比0.9292 [0.9240, 0.9348]となり、
約7.1%短縮した。mainとの13仕様32結果も完了し、すべて95%区間上端が1.10未満。
最大はgenshi_text 1.0865 [1.0797, 1.0949]、genshi_xml 1.0769、
sqlglot_v2_normalize 1.0748、nqueens 1.0666、deepcopy_memo 1.0482。
これは非PGO/LTOの値である。M41の最終GIL PGO/full-LTO buildと4グループの
native検証も成功し、16仕様64 run・35結果の比較も完了、identity一致。
floatは1.0275 [1.0251, 1.0295]まで改善したが、genshi_xml 1.1356、
dulwich_log 1.1114、nqueens 1.1040が10%を超える。
M42では引数設定済みフレームからgeneratorを作成し、compiled callerへ戻す
経路を追加した。回帰テストはM41で期待通り失敗、修正後で成功。
COPY_FREE_VARSだけを持つprefixにも対応し、MAKE_CELLはTier 1へ戻す。
生成は最初の監視対象命令より前なので、監視version差による不要なfallbackを除き、
初回RESUMEのPY_STARTイベントはテストで確認した。debugの組み合わせ1,155件、
coroutine/async generator 199件が成功。新規テストのexecutor後始末を加え、
5件の-R 3:3も成功した。新規GIL/FTビルドの検証も成功。
ただしM42g/M41の16 run・5結果比較ではgenshi_xml 1.02435、nqueens 1.01005、
SQLGlot normalize 1.01083と遅くなり、この形は高速化として採用しない。
_METHOD_CALLの機械語が761から1,247 bytesへ増えたため、M43は生成処理を
共通C関数へ移した。機械語は880 bytesへ減ったが、Genshi XML 0.99939と
改善は確認できず、nqueensは1.00834で遅い。生成経路の変更は両案とも戻した。
M44ではFOR_ITER_GENを既存のiterator呼び出しで扱い、消費側の本体をcompiled
loopに保つ変更を検証中。例外状態とfinally、消費側のnative継続をテストする。
M44b/M41はgenshi_text 1.24771、genshi_xml 1.29424、nqueens 1.13686と
悪化し、この変更と専用テストは戻した。直接のフレーム遷移は維持する。
M45bは通常generatorの初回・yield後のRESUMEをmethodコンパイル対象に追加する。
再開時のstack深さを用い、localsを未知として解析し、suspensionをまたぐ仮定はしない。
closeはexecutorで置換されたRESUMEの元の引数を読み、finally等の判定を維持する。
新規2件は修正前で失敗、修正後で成功。debug test_opt 564件も成功。
関連検証・非PGOビルドも成功。M45b/M41はnqueens 0.98394、dulwich 0.99160、
Genshi text 0.98810、SQLGlot 0.98858だが、Genshi XMLは1.02337で悪化。
M46bではFOR_ITER_GENの直接フレーム遷移を保ち、calleeのコンパイル済みRESUMEと
compiled consumerを専用命令で接続する。通常のMETHOD_CALLは変更しない。
native復帰・例外状態・callbackのローカル変更/無効化/GCの3件と-R 3:3が成功。
全関連検証・新規ビルド・M45b/M41それぞれとの比較を順次実行する。
FTと最終構成の検証、および全体10%条件はまだ未完了。
最終構成の全suiteと、FT connected_componentsの不確かさ確認は引き続き未完了。

GILの全体比較1巡目で `deepcopy_memo` が1.1752となったため、追加調査が必要。
mainのworker平均は11.854/11.898/11.826 µs、候補は14.417/12.941/14.452 µs。
通常のdeepcopyは1.0280、deepcopy_reduceは1.0039。両順序を完了してから
profilingと修正判断を行い、遅いworkerも含めて記録を保持する。
GILの1巡目全体は95仕様122結果、時間比の幾何平均0.9814。
10%超はdeepcopy_memo 1.1752、regex_v8 1.1729、float 1.1322、
genshi_xml 1.1138、dulwich_log 1.1096、sqlglot_v2_normalize 1.1086の6結果。
逆順の2巡目とlocal 8が終わったら、JIT有効・無効の比較とperfで原因を調べる。
現時点で全体の目標は達成していない。

以前に最終構成で比較したM34は、10仕様26結果すべて実行成功・identity一致だが、
**logging_format 1.1339、nqueens 1.1152が10%条件を超えた**。
残る24結果は1.10以下で、Go 0.8726、Richards 0.9228、scimark_lu 0.7598。
後続M35bは非PGO/LTOの15結果すべて1.10以下（95%区間上端も1.10未満）となった。
nqueens 1.0836、logging_format 1.0540。ただしこれはPGO構成の合否には流用しない。
M35bの最終計測はmodule subclassバグ確認後、開始前に中止した。
M36の全suite、local 8は未完了。両側でC `_decimal` を使用する。
誤結果の出たM33の計測と、短い診断が重なった最初のM34先行計測も中止・保存した。

| 保持しているmain baseline | SHA-256 |
|---|---|
| GIL PGO/fullLTO | 29f98fde43417b99bad02a6710ad55e55f343a574f8fff306932d1e75b010044 |
| FT O3/noPGO/noLTO | 44c9f1615910b76898e1eb6cd478a36c151f21cf5bc99ea95aa6ac115c85fefb |

mainのFT buildはJIT要求を有効にしてもexecutorを作らず、Tier 1で実行する。
直接のtracing/method JIT比較はGIL構成である。FT構成はmainのTier 1と
method JITの比較で、複数スレッド共存時にはmethod側もTier 1へ戻る。

初期候補M22bの全97仕様screenでは、89仕様・115結果で比較できた。
成功結果の時間比の幾何平均は **0.9850**。各項目の10%条件は未達である。
全結果・区間・失敗・固定入力は[全体screenのレポート](method_only_m22b_screen.md)を参照。

10%を超えた時間比はrichards_super 1.3603、richards 1.2519、scimark_lu 1.2477、
logging_format 1.1265、nqueens 1.1067、shortest_path 1.1010。
base32_small 1.0987、logging_simple 1.0969も境界付近なので追加比較する。
8仕様に失敗があり、sandbox制限6仕様、依存未準備fastapi、15秒でtimeoutしたnetworkx_k_coreに分かれる。

このM22bの表は最新候補の結果ではない。後続の固定比較ではRichards・loggingを
改善し、M28でLUが約0.72となった。M29cのgenerator呼び出し方法でnqueensが悪化したが、
その変更を外したM29dでは1.0609。M31でGoも0.8100へ改善し、M32で型変更を修正し、M33eでは呼び出し境界を改善した。
詳細な実験・検証履歴は末尾に記載し、全suiteの再測定は未完了として区別する。

M19cの追加比較ではdeltablueが両blockでAttributeErrorとなった。
定数化したクラス属性と後段のstore融合の間で、guard失敗時のstack契約が壊れていた。
M20bで属性置換を一つのuopに保つ修正を加え、最小再現テストと元deltablue1,000回が成功。
M19cの他の値はRichards 1.3560、fannkuch 1.1293、regex_compile 1.0604。
正しさを満たさない候補の値であり、修正後M20bの性能値として扱わない。

M20bでは冷たい分岐の汎用演算が初期adaptive counterのまま固定される問題も修正。
未学習の算術・比較・真偽判定をTier 1へ戻し、特殊化してから静的CFGを再構築する。
元fannkuchで特殊化が進むことを確認済み。GIL関連297件は295成功・2skip、
追加のGIL広域19ファイル1,628件（15skip）は成功。固定releaseでの4仕様比較も成功。

## 先行14仕様の測定と検証履歴

M22bを同じmain baseline、CPU 2、順序を逆にした2block、各2workerで測定した。
時間比が小さいほど速い。既知14仕様の比較であり、全suiteの結果ではない。
区間は全workerを用いるbootstrap 95% CI。ビルド一組での不確かさを示す。

| Benchmark | M22b method/main | 95% CI |
|---|---:|---:|
| richards_super | 1.3603 | 1.3558–1.3649 |
| float | 1.0592 | 1.0533–1.0651 |
| go | 1.0510 | 1.0411–1.0612 |
| regex_compile | 1.0460 | 1.0428–1.0492 |
| deltablue | 1.0196 | 1.0099–1.0296 |
| dulwich_log | 1.0083 | 0.9955–1.0214 |
| telco | 0.9943 | 0.9776–1.0113 |
| pickle_pure_python | 0.9729 | 0.9709–0.9749 |
| hexiom | 0.9638 | 0.9530–0.9750 |
| raytrace | 0.9275 | 0.9105–0.9454 |
| chaos | 0.9242 | 0.9009–0.9492 |
| fannkuch | 0.9081 | 0.9032–0.9131 |
| nbody | 0.9038 | 0.9021–0.9056 |
| spectral_norm | 0.6661 | 0.6571–0.6751 |

Richardsは10%条件を満たしていない。他の13仕様はこのscreenでは1.10未満。
M21の2段inline、M22の共有setterの型family維持は生成uopに反映されたが、
Richardsの測定値はM20b（1.3577）から改善していない。
M22b binary SHA-256:
`85131c6be05bbfee337737f74247df56ad55f8ac0480480dccebb92c4c55b943`。
生データは`jit-artifacts/regressions-20260919/m22b-gil-all-screen-state.json`。
14仕様56runすべて成功し、測定前後のidentityが一致した。

続く2to3のmain実行は成功したが、command benchmarkではpython_executableではなく
command metadataに実行ファイルが入るため、harnessがKeyErrorで停止した。
完了14仕様を保存・監査後、その検証だけを修正して残る83仕様を
`m22b-gil-rest-screen-state.json`へ再開した。未記録だった2to3のJSON/logも保存する。
2区間は同じbinary・workload・設定を使うが、metadata検証部分のharness revisionは異なる。

M22bの正しさの検証: GIL method関連300件（298成功・2skip）、GIL広域1,628件
（15skip）、FT method関連300件（290成功・10skip）、FT関連8ファイル66件が成功。
追加5テストの参照リーク検査（-R 3:3）と元deltablue1,000回も成功した。
2段inline後のCFG伸長で未解決return sentinelをoffsetとして加算するバグを修正済み。
旧最適化309件は94failure・2error・3skipであり、全test_opt成功ではない。
属性uopを原子的に維持する変更に伴う2errorはM22cのテスト修正で個別に成功した。
このテスト修正は固定M22b binaryを変更しない。残る94failureには旧tracingの期待と
method frontendへ未移植の最適化があり、引き続き調査する。

M11cではpickle_pure_pythonが1.0237、floatが1.0847。
M12bの改善は、兄弟クラスの同じ属性offsetや継承methodを守る型version群のguardと、
closureの静的inline化を含む。Richardsは初期の2.19倍から改善したが上限を超える。
M15で異なるクラスが上書きしたmethod呼出しにも対応した。Richardsの別perf診断では
Tier 1自己時間14.23%、frame cleanup 9.17%で、小さいframeのcleanupをM17で最適化した。

Regexの別perf診断ではCFG merge 4.19%、uop配置1.18%、stack解析1.13%を占める。
debugで40反復するとunsupported経路の頻発によるmethod破棄が1,266回あった。
再コンパイルのbackoff cacheと、OSR入口に静的に推論した型guardを置く変更をM17bまでに導入した。
これらの診断実行の経過時間を性能比較には使っていない。

M15 binary SHA-256:
`7344398f237ad15c52029cf4b4cdfaff97a21b09c86e42de62cc7834e62a98e4`。
生データは`jit-artifacts/regressions-20260919/m15-gil-dev-screen-state.json`。
4仕様すべて成功し、測定前後のidentityが一致した。
M11cのGIL広域テストは19ファイル1,858件（15skip）成功、FT debugの関連284件は
280成功・4skip。M12bのmethod関連280件は278成功・2skip。
M15ではGIL関連289件が287成功・2skip、FTは282成功・7skip、GIL広域1,858件も成功。
M17bのGIL関連292件は290成功・2skip。FT関連292件は285成功・7skip、GIL広域1,858件も成功。
M18b GIL関連294件は292成功・2skip、GIL広域1,858件も成功。
旧最適化テスト309件にはM18b時点で93failure・3skipが残る。tracing固有の期待と
methodへの未移植の最適化を含み、失敗を隠すための一括skipはしていない。

mainのFTビルドはJIT有効フラグを持つがexecutorを生成しないことを確認済みで、
FT比較は実際にはmainのTier 1とmethod JITの比較になる。tracing対methodの直接比較は
GILありで行う必要がある。

## 現在の実行ファイルと進行中の変更

リポジトリrootから、次のGIL/noPGO/noLTO実行物を再buildせず使える。

```sh
PYTHON_JIT=1 jit-artifacts/regressions-20260919/method-main-gil-dev-build/python your_script.py
PYTHON_JIT=1 jit-artifacts/regressions-20260919/m22b-gil-release-build/python your_script.py
```

前者はmainのtracing JIT、後者は固定済みM22bのmethod JIT。両方C `_decimal`を使用する。
M23のGIL releaseは `jit-artifacts/regressions-20260919/m23-gil-release-build/python`。
SHA-256は `58af103caacbaf2c95d1ffb506900e49bb9f0bbaa631f94a0885ea00d9a4b318`。
M23の10仕様26結果の比較は40run成功・identity一致。
Richards Super 1.2984 [1.2945,1.3017]、Richards 1.1894 [1.1650,1.2043]へ改善したが、
scimark_lu 1.2493、logging_format 1.1207、nqueens 1.1116も含め5項目が10%超。
shortest_pathは0.9881 [0.9181,1.0333]で前screenの10%超が再現せず、変動が大きい。
ワークツリーにはさらにM24のcache衝突対策があり、まだ検証中である。

M23では同じreceiverの同じ型version集合を再検査しない静的な最適化を準備している。
集合をCFG内でinternし、抽象値にIDを保持する。Pythonへescapeする操作で証明を破棄し、
単一型とは仮定しない。dict/slot、class/property変更、callback、異なる集合の検査を追加。
旧tracingのテストも、入口で未知な引数・namespace監視・generatorのTier 1 fallbackを
検証する形へ移行中である。M23の新しいfamily guardテストは変更前でdict/slotとも失敗し、変更後の
TestMethodFrontend 179件（1skip）は成功。移行後の旧最適化310件は70failure・3skipであり、
全test_opt成功とは扱わない。追加のexecutor/TestUops 34件（1skip）と広域15ファイル2,239件（24skip）も成功。
固定releaseによる10仕様の生データは `m23-gil-regression-screen-state.json`、
集計は `m23-gil-regression-screen-analysis.json` に保存した。

当初M24と呼んだ未適用の設計案は保留した。dynamic methodのcalleeがTier 1へ戻るとcallerのnative実行も
終わる現状に対し、calleeをEvalFrame境界で呼び、callerを維持する案を保存した。
C呼び出しの費用も増えるため、改善するかは測定で判断する。
ただしM22b実workerのperf診断では85.77%がteardown時点のmethod uopへ対応し、
型family guard 13.09%、method call 12.52%、managed values check 5.17%、stack check 4.03%。
calleeのTier 1 fallbackを主因と決めつけず、重複guardと小さいcalleeのinline機会を先に調べる。
mapは実行終了時点に残るexecutorに基づくため、早期に破棄されたcodeへの対応は完全ではない。
この診断の所要時間は性能比較へ使わない。

実装中のM24は、function version cacheの衝突によるinline機会の損失を修正する。
実workerではversion 845の生きた関数に対応するslotが4941へ置換されていた。
cacheは4096枠で、pyperf起動中にnext_versionが5565まで進んでいた。
強制再compileだけでは生成codeは変わらなかった。
静的に分かるglobal関数と同じmethod descriptorを抽象値に保持し、CALL cacheのversionと
一致する関数を直接使う。キャッシュ容量やworkloadは変更しない。新テストはcacheを空にした
後のinlineとcallee.__code__変更を検査する。まだbuild・検証・性能測定前である。


全体screenのasyncio_tcp、asyncio_tcp_ssl、asyncio_websocketsは両側でsocket生成/bindに失敗。
sandboxの最小socket生成でもEPERMを確認した。性能比を算出せず、screen完了後に
sandbox外で両側を再測定する予定。現時点で全suite成功とは扱わない。

## 実装した範囲

- runtimeのtracer状態、開始・bytecode記録・終了、recording dispatch table、
  TRACE_RECORD、録画関数の生成器と生成物、trace optimizerへの入口を削除。
- methodのguard失敗・未対応命令はTier 1へ復帰し、side traceは作らない。
  cold executor、executor間のexit links、chain depth、温度管理も削除。
- RESUMEだけでなくループbackedgeからも静的CFGを作るOSRを実装。
  OSRのlive stackは未知の値として解析し、両方の分岐先をコンパイルする。
  M13では全CFGから推論できるlocalのbuiltin型を入口で検証してから伝播する。
- コンパイル成功時はその呼び出しから直ちにmethodコードを実行する。
- block内の隣接list比較とlist要素のlen比較の融合をmethodにも適用。

`_EXIT_TRACE`などの共通IR名は現段階で残るが、直接Tier 1へ復帰する命令である。
M9以降で未使用のrecord pseudouop定義・生成器の処理・記録型symbolを削除した。
共通uop最適化器は各静的blockのframe遷移までの範囲に適用し、calleeのCFGでも使う。

## M5測定条件

- main: `d95f29589e03603aa13d8ca9d4f817dce77d357c`＋LLVM 21用build patch。
- candidate: `14defe7e06ef37956989e46c74710293d33df41e`＋
  `jit-artifacts/regressions-20260919/m5-method-only-v2.patch`。
- GCC 13.3、O3、frame pointerとleaf frame pointer、GILあり、PGO/LTOなし。
- 両方ともnative JIT有効。C `_decimal`を通常importし、telcoでも使用を検査。
- main binary SHA-256:
  `cafdcfa052a142b456095b69ec8f99c7a0fcac701403055bfaae587e0de770ea`。
- candidate binary SHA-256:
  `776fc7083db32d64c76fa3db66b1a03751fcfd5a7364914aa36abfdae1233071`。
- i5-12450H、CPU 2固定、hash seed 0。
- 各仕様でmain→candidate、candidate→mainの2block。各3worker、5warmup、
  5value、min-time 0.1秒。独立calibrationで正規化した値を使用。
- 実行中に重いbuild/testを並行させない。binary、設定、拡張、依存、workload、
  harnessのSHAを前後で照合。14仕様すべて成功しidentity一致。
- 実行時間比は各blockのworker平均の比の幾何平均。CIはblock内でworkerを
  resampleしたbootstrap 4,000回の95%区間。同一CPU・固定build一組内の区間であり、
  再buildや他のCPUでの再現性を保証しない。遅いworkerも削除しない。

| Benchmark | method/main時間比 | 95% CI | 10%条件 |
|---|---:|---:|---|
| richards_super | 2.1919 | 2.1833–2.1993 | 超過 |
| pickle_pure_python | 1.2191 | 1.1876–1.2494 | 超過 |
| fannkuch | 1.1878 | 1.1797–1.1954 | 超過 |
| regex_compile | 1.1218 | 1.1132–1.1335 | 超過 |
| deltablue | 1.1209 | 1.1171–1.1243 | 超過 |
| float | 1.0822 | 1.0785–1.0857 | 点推定では範囲内 |
| nbody | 1.0530 | 1.0456–1.0607 | 点推定では範囲内 |
| dulwich_log | 1.0505 | 1.0373–1.0641 | 点推定では範囲内 |
| raytrace | 1.0375 | 1.0243–1.0499 | 点推定では範囲内 |
| telco | 1.0327 | 1.0108–1.0486 | 点推定では範囲内 |
| hexiom | 1.0177 | 1.0133–1.0224 | 点推定では範囲内 |
| chaos | 0.9817 | 0.9650–0.9993 | 点推定では範囲内 |
| go | 0.8999 | 0.8842–0.9093 | 点推定では範囲内 |
| spectral_norm | 0.6976 | 0.6955–0.6999 | 点推定では範囲内 |

元workloadの入力・出力検証を変更していない。全suiteの幾何平均としては集計しない。
選択14仕様の結果なので、未測定仕様に回帰がないとは言えない。

生データ、実行順、全worker値、失敗ログ、SHAは
`jit-artifacts/regressions-20260919/m5-gil-dev-screen-state.json`、
同`-analysis.json`、同prefixの個別JSON/logに保存。
build manifestは`method-main-gil-dev-build.json`と`m5-gil-release-build.json`。
初回controllerはpython3.12からpyperfをimportできず、測定前に停止。
既存の固定依存をPYTHONPATHに指定したv2で測定した。初回ログも保持する。

## M5時点の検証記録

M5のmethod/生成器245テストは244成功・1skip。
新規テストはOSRの両分岐、nested iterator/live stack、float/大整数への型変更、
ZeroDivisionErrorのtraceback、recording opcode/APIの除去を含む。
旧tracing構造だけを要求するテストは新しいCFG契約に直し、値・例外・finalizer・
コード差し替え後の動作検査を維持する。

旧uop最適化テスト全体には多数の失敗が残る。単なるIR形状の変更と、型伝播・
builtinの簡略化等の不足を区別している。M6初回debugでは型guardの解析に
record pseudouopを要求するassertを検出した。まだ全テスト成功とは扱わない。

Richardsの元workloadを40回実行した別の非計時診断では、M5のscheduleと
HandlerTask.fnにexecutorが残っていなかった。原因を断定せず、partial methodの
復帰頻度・再コンパイル・コード量を次に調べる。診断は
`m5-gil-release-richards-frontends.json`と`method-main-gil-dev-richards-frontends.json`。

M5時点での次工程はM6のdebug検証、10%超過5仕様の原因別修正、FT検証、固定buildの
全suite比較だった。最新の状況は冒頭の表を参照。mainのFTはJIT enabledでもexecutorを作らないため、
FT結果はmain Tier 1対methodとして明記する。旧R36のhybrid成績は転用しない。

この作業は未コミット。GitHubへの投稿・push・PR変更は行っていない。

## M8の検証進捗

静的blockの共通symbolic最適化、CALL_EX_PY、executor slot再利用を追加。
method/OSR・無効化・基本uop・生成器281テストは279成功・2skip。
静的len guard除去、localの型変更、260回の無効化/再コンパイルも成功。
型guardの記録値依存などM6の2つのassert停止を修正し、失敗ログは保持。
全uop最適化・広い動作検証と、M8の性能測定はまだ完了していない。

このbranchには以前のC実装の修正・最適化も含まれるため、mainとの差すべてを
frontend置換だけの効果と解釈しない。ここでの直接比較はmain実行物と候補実行物。

## M8b比較（GIL、PGO/LTOなし）

C `_decimal`を使用。14仕様すべて成功し、比較前後のidentity一致を確認。
候補SHA: `7337b327059a22b91410a3510a00dc4d08777492f7455bc02d83a4f744bb2a0e`。
main、CPU、反復数、順序反転はM5と同じ。結果を選別せず以下に示す。

| benchmark | candidate/main | 95% worker-bootstrap CI |
|---|---:|---|
| richards_super | 2.2337 | [2.2265, 2.2410] |
| pickle_pure_python | 1.2130 | [1.2094, 1.2169] |
| fannkuch | 1.1351 | [1.1330, 1.1371] |
| regex_compile | 1.1305 | [1.1204, 1.1392] |
| deltablue | 1.1166 | [1.1062, 1.1264] |
| float | 1.0979 | [1.0892, 1.1087] |
| raytrace | 1.0518 | [1.0486, 1.0555] |
| dulwich_log | 1.0458 | [1.0346, 1.0557] |
| hexiom | 1.0205 | [1.0147, 1.0263] |
| telco | 1.0182 | [1.0006, 1.0383] |
| chaos | 0.9789 | [0.9768, 0.9809] |
| nbody | 0.9609 | [0.9571, 0.9643] |
| go | 0.8970 | [0.8903, 0.9031] |
| spectral_norm | 0.6885 | [0.6868, 0.6903] |

10%超過は5仕様。floatの区間上限も1.10を超えるため、条件達成とは判定しない。
生データ: `jit-artifacts/regressions-20260919/m8b-gil-dev-screen-*`。
この結果は全97仕様・FT・PGO/LTOあり構成の結果ではない。

M8の広い19ファイル検証は18成功、weakrefでクラッシュ。未知のsuper classを
定数扱いしていた部分をM8bで修正し、weakrefと専用再現テスト140件はすべて成功。
M8bのmethod関連282件は280成功・2skip。旧uop最適化310件はM8時点で
122failure・3skipを残しており、全テスト成功とは扱わない。

追加の実行失敗: `concurrent_imap` / `dask` はmain・候補ともEPERM。
`fastapi` は `httpx` のimport失敗で、元の依存準備が `pydantic-core` / PyO3の
Python 3.16未対応により失敗したgroupだった。未準備の仕様を成功数や性能比に含めない。
測定中の固定依存環境へは変更を加えていない。

## M24c: 既知calleeのversion cache衝突を回避

実pyperf workerでは、ベンチマーク関数が生きていても起動時のimportによって
4096枠のfunction version cacheが衝突し、静的inlineの候補から落ちていた。
静的CFGで分かるglobal関数・継承method descriptorを保持し、CALL cacheのversionと
照合して使う。型、descriptor、function versionのguardと無効化を維持する。

GIL/noPGO/noLTO・同じmain・3worker・逆順2blockの5仕様11結果が成功。
20runすべて成功、測定前後のidentity一致。時間比とbootstrap 95% CI:

| Benchmark | M24c method/main | 95% CI |
|---|---:|---:|
| richards | 0.8702 | 0.8679–0.8722 |
| richards_super | 1.0220 | 1.0202–1.0236 |
| logging_format | 1.0754 | 1.0664–1.0853 |
| logging_simple | 1.0651 | 1.0560–1.0741 |
| logging_silent | 0.9770 | 0.9700–0.9846 |
| nqueens | 1.0932 | 1.0752–1.1099 |
| scimark_lu | 1.2393 | 1.2318–1.2446 |

この再比較で10%超はscimark_luだけ。nqueensは区間が1.10をまたぐため追加確認が必要。
全suite・FT・PGO/LTOの10%条件を達成したという結果ではない。
GIL release SHA `50cec7b24f223690c9ffeda872f6eb999de94270816cf622a42ff1a3e0934638`、
実行ファイル `jit-artifacts/regressions-20260919/m24c-gil-release-build/python`。
生データ `jit-artifacts/regressions-20260919/m24c-gil-regression-screen-state.json`、
全11結果 `m24c-gil-regression-screen-analysis.json`。

正しさ: GIL/FT method関連214件ずつ（それぞれ2/14 skip）、FT8ファイル66件、
元deltablue1,000回成功。M24bで広域2,239件・新テストの参照リーク検査も成功。
旧最適化310件中70failureは未解消。M26でPython添字アクセスの静的inlineを実装中。

## M26c: Python添字アクセスの静的inlineと再帰上限修正

GIL/noPGO/noLTOの7仕様23結果28runが成功し、identity監査も一致した。
`scimark_lu` は **1.2616 [1.2581, 1.2651]** であり、添字inlineだけでは改善しない。
`richards` 0.8712、`richards_super` 1.0206、`logging_format` 1.0933、
`nqueens` 1.0910、`base85_small` 1.0893。`scimark_sor` は1.0573へ悪化した。
GIL release SHA `7326bfc1c4842439d1da1edecfab7798244f147ca2172c3b665a44cb439dfe32`。
生データは `m26c-gil-regression-screen-state.json` と同名 `-analysis.json`。

数値検証では、元LUの5サイズ×3seed×3反復の行列とpivotがmain/candidate・
JIT有効/無効の4通りで完全一致した。GIL/FTのmethod関連218件ずつ、
FTのJIT無効test_opcache 95件と並行実行66件も成功。
開発debugでは広域2,239件、新添字テストの参照リーク検査が成功した。
添字の再帰上限漏れはmainのTier 1にも存在し、[M-16](../bugs_report.md#m-16-specialized-python-indexing-omits-the-recursion-limit-check)に記録した。

実workerのLU_factorには測定終了時にexecutorがなく、debugではコード量の上限で
内側のループ末尾がTier 1に戻り、fallback頻度によってexecutorが破棄されていた。
M27で静的な引数型をcalleeへ渡す最適化を検証済み。M28ではOSR loopからの
block配置と、loopを進行したpartial methodの保持を検証している。
M27の旧最適化テストには67failureが残る。trace固有のuopやcountの期待だけでなく、
property/getattribute経由のinline、branch narrowing、calleeをまたぐ所有権推論等の
未対応部分を含む。失敗一覧を `m26b-legacy-failures.json` に保存し、一括skipはしない。

## M28: OSR loopの配置とpartial methodの保持

コード量の上限を変えず、OSR backedgeの対象loopを先に配置する。
partial methodでは入口ごとにnative backedgeを最大8まで数え、loopを進行した後の
Tier 1復帰を破棄理由としない。進行しないentryは従来のmiss閾値で破棄する。
complete methodには進行計測を追加しない。全体の静的CFGと両分岐は維持し、
実行経路の記録やside traceは導入しない。

変更前に有用loopの保持と、大きな外側bodyに囲まれたOSRの2テストが失敗し、
変更後には3テストすべて成功。GIL method関連224件、広域2,239件、
10ケースの参照リーク検査、元deltablueとLU数値検証が成功。
直接診断ではLU_factorのfrequent fallbackによる破棄が消えた。
固定releaseの性能値とFT検証は進行中で、10%条件の達成とはまだ報告しない。

M28固定比較完了: 6仕様12結果24runすべて成功、実行前後のidentity一致。
GIL release SHA 44e2f2ca28440e03c1c5ad2609e095056dd9156098b46dfe27a12893646436f8、
FT debug SHA 4d700e4a7991c05381f75976a9191f4c3a68ec6709de58497546566f371b3ae5。
固定GIL/FTのmethod224件ずつ、FT JIT無効opcache95件、並行実行66件成功。
LU 0.7211 [0.7194,0.7228]まで改善。Richards Super 1.0224、regex_compile 1.0202、
SOR 1.0290。一方go 1.1312 [1.1208,1.1404]、nqueens 1.1073 [1.1032,1.1112]で
10%超過。logging_format 1.0965 [1.0862,1.1070]も境界を追跡する。
次はgo/nqueensの元workerのexecutorをM26cとM28で比較し、最終PGO/FT構成へ進む。

M29初期buildでjson.dumpが終了しない問題を発見。生成したFOR_ITER_GENの
exhaustion edgeにtarget blockを設定し忘れていた。GDBのC/Python stackを保存し、
該当build childだけを停止。設定を追加したM29bはbuild成功・新5テスト成功。
旧methodテスト229件中5failureはgenerator/consumerにexecutorがないという期待。
OSR入口・native iterator呼び出し・非native yieldの検査へ更新した。
-R3:3の初回失敗は参照数判定ではなく2巡目のexecutor存在assert。入力型を変える
前の実行のcompile backoffが同じcodeへ残るため、各fixtureでreset_codeする。
修正後7関連テスト成功。M29cを固定してGIL release/FT debugの新規build、
新テストの参照リーク・広域テスト・旧最適化テストを実行中。性能はまだ未測定。

M29c固定比較完了: 6仕様12結果24run成功・identity一致。
nqueens 1.2269 [1.2228,1.2310]へ悪化、Go 1.1337 [1.1188,1.1437]。
LU 0.7198、Richards Super 1.0211、regex_compile 1.0229、logging_format 1.0941。
M29d実験を作成: M29cからFOR_ITER_GENのC呼び出しloweringだけを取り除き、
generator OSRの効果と分離する。rootは別のM30候補で、M29dは独立固定ソース。
M30新globalテスト2件は変更前に両方executorなしで失敗。M30 debug build中。

M29dの分離比較完了: nqueens 1.0609 [1.0239,1.0862]、Go 1.1341 [1.1285,1.1394]。
両block・全8run成功、identity一致。C経由のFOR_ITER_GEN loweringが大きな悪化を
起こしており、取り除く。generator本体のOSRとTier 1 suspensionは残す。
M30 global対策は新2件、method231件、7ケース-R3:3、広域2,239件成功。
旧最適化67failureは継続。M30は独立したrelease性能を測定していない。
M31はM30のglobal対策とM29dのgenerator境界を統合した候補。
非対応consumerのretirementテスト3件を元の期待へ戻し、GIL/FT buildと検証中。


M31固定比較完了: 9仕様25結果36run成功、実行前後のidentity一致。
Go 0.8100 [0.7992,0.8179]、LU 0.7235 [0.7223,0.7247]、Richards 0.8678、
Richards Super 1.0225、nqueens 1.0899、regex_compile 1.0171。
10%を超える点推定はbase85_small 1.1019 [1.1001,1.1038]のみ。
logging_format 1.0966 [1.0871,1.1055]も境界として追跡する。
これらはGIL/noPGO/noLTOの部分比較であり、最終2構成・全suite・local8は未確認。
生データ: `jit-artifacts/regressions-20260919/m31-gil-regression-screen-state.json`、
集計: 同名 `-analysis.json`。全worker・逆順両blockを保持した。

M32: M27の引数型伝播で、immutableなModuleTypeを持つinstanceは型も変わらないと
誤って仮定する不具合を発見。moduleは__class__を変更できるため、calleesとOSR入口に
渡す安定型からmoduleを除外した。__class__を差し替えた後のisinstanceの結果が
誤る新テストはM31で失敗し、修正後成功。これは候補で発見した不具合であり、mainの
バグと確認したものではない。関連・参照リーク・広域検査を継続中。


M32dのGIL全test_opt 542件成功（5skip）。旧tracing前提のテストを、methodの
直接return/attribute-return、全CFGの両分岐、callee境界の所有権、Tier 1で行う
property/特殊メソッドへ移行。定数推論・所有権推論の未移植部分を実装済みとせず、
通常/未訪問分岐、コード差し替え、参照数、例外・副作用を検査する。
FT全test_optでは35件の最適化期待が失敗。mutable globalの保持やGIL専用call
短縮との違いを確認し、FTのguarded load/frame呼び出しと意味論を検査する移行中。
これらのrootテスト変更は固定M32の性能比較用ソースとは別に記録している。

M32 FT release完成: c853b66f696991c54cbde4c915c2532396b96c26b335a5c389df1035b47905c8。
FT debugのmethod232件（21skip）・関連12件-R3:3・core635件（9skip）・
並行実行66件・JIT無効opcache95件成功。FT release method232件成功。
FTのC系1,154件とGIL PGO学習はtest_reのforkserver socket.bindがsandboxの
EPERMで失敗。ログと失敗PGOの.gcdaを保存し、空のprofileから同じseed/taskで
sandbox外の学習をやり直した。再学習は成功、最終PGO/LTOリンクと検査を継続中。
性能値はまだ測定しておらず、全構成10%条件の達成は未確認。


M32fの全test_optはGIL/FTとも542件成功（5/30skip）。新規の一括skipは追加していない。
FTはmutable globalを一般loadで読むためGIL専用定数化/call短縮の期待を分け、
値の置換・namespace寿命・構造変更・コード置換後の意味論を両構成で検査した。
構造変更/namespace解放時はFTでもexecutorを失効させることを確認して期待を維持。
テストの固定コピー/ハッシュと使用binaryは `m32f-test-provenance.json` に保存。
rootのLibをPYTHONPATHに指定した正しさの検査であり、性能測定にはこのoverlayを使わない。
旧branch narrowing、calleeをまたぐ所有権・戻り値の定数推論は未移植のまま。
現行method CFG/短縮命令と両分岐・参照数・副作用のテストに移行したのであって、
旧最適化をすべて実装したという意味ではない。

PGOのsandbox外再学習43ファイルは成功（同じrandseed/profile task）。
FT C系1,154件と元deltablue1,000回もsandbox外で成功。
最終PGO/fullLTOリンク完了後の検査と、両profileの全suite/local8比較が次の作業。


M32最終GIL PGO/fullLTOの10仕様26結果40runが完了。全run成功・identity一致。
10%超の点推定はbase32_small 1.1494 [1.1273,1.1903]、logging_format 1.1071
[1.1003,1.1138]、nqueens 1.1046 [1.0959,1.1120]。Go 0.8665、LU 0.7557、
Richards 0.9201、Richards Super 1.0332、C telco 0.9840。
base85_smallは1.0457 [0.9498,1.1115]で、block比0.9877/1.1072と変動が大きい。
初期blockだけを改善の根拠にせず、全worker・両blockを保持する。
結果: `m32-gil-final-screen-state.json` / `m32-gil-final-screen-analysis.json`。
FTの同じ10仕様を継続測定中。終了後に元logging/base32 workerをJIT有効/無効で
別途profileし、呼び出し処理とC処理の寄与を分離する。診断値を比較結果へ混ぜない。
property再初期化時のcache保持についてもソース上の懸念があり、測定後に再現を確認する。
現段階では新たなmainのバグとして確定/報告していない。


### M32: 最終 FT 確認と呼び出しの診断（2026-09-20）

FT 最終ビルドの 10 specification / 26 結果は、全 40 run が成功し、
実行ファイル・入力の同一性検証も成功した。全結果の点推定が main 比 1.10 以下。
最大は logging_silent 1.0627 [1.0577, 1.0680]。
shortest_path は 1.0233 [0.9755, 1.1079] と幅があり、全体の達成はまだ主張しない。
GIL 側の base32_small 1.1494、logging_format 1.1071、nqueens 1.1046 は未解決。
全 suite と local 8 の現在の候補による検証も残っている。

元の logging/base32 workload を JIT 有効・無効で perf 採取した。
JIT 無効では main と候補の時間は近く、有効時の Python 呼び出しが次の調査対象。
診断 hook 初版はゼロ長 stencil の名前を解決できず失敗したため、ゼロ長も登録して
新しい出力先で全 8 run を再実行し成功した。失敗記録を保持し、この計測を
通常の性能比較には混ぜない。次は一般呼び出しの引数型伝播と inlining を調べる。

property 再初期化後の古い getter 呼び出しを main/candidate × GIL/FT × JIT on/off
の全 8 通りで確認した。main 由来の未修正バグとして bugs_report.md の M-17 に記録。
重複していた番号は Python indexing の項目を M-16 に整理した。


### M33: 呼び出し境界の改善（実装・検証中）

- `CALL_PY_GENERAL` の NULL self slot が静的に証明できる場合、明示された位置引数の
  不変組み込み型を callee CFG に渡す。位置・keyword-only default は未知のまま。
  LOAD_ATTR の展開が必ず NULL を積む場合も、この事実を CFG に残す。
  新規 2 テストは M32 で失敗、M33a の全 test_opt 544 テストは成功（skip 5）。
- property と独自 `__getattribute__` は `_LOAD_ATTR` の通常呼び出しへ展開して
  native continuation へ戻す。キャッシュされた getter の埋め込みは行わない。
  呼び出し後の receiver guard は破棄する。再初期化・例外・呼び出し回数を検証。
  M33b の全テストでは旧 Tier 1 fallback 前提の 3 箇所だけが失敗したため、
  property の期待を新しい通常呼び出しへ更新し、retirement のテストは引き続き
  未対応命令を使うよう変更した。
- 実際の base32 worker で module 経由の関数が weak function-version cache から
  消え、全呼び出しが `_METHOD_CALL` になることを確認した。
  GIL build で静的名前空間の binding hint を保持してコンパイル対象を回復する。
  hint は実行時の identity/type の証明には使わず、関数バージョンのガードを残す。
  cache eviction の再現テストは M33b で失敗。M33c で検証中。

性能への効果はまだ測定していない。次は正当性テスト後に凍結した非 PGO ビルドで
独立比較し、有効なら最終 4 構成比較へ進む。


M33c の全 546 test_opt は、retirement fixture の 1 件を除き成功した。
generator iteration に置き換えた fixture では保持した executor の破棄条件を
満たせなかったため、`raise ValueError(total)` で未対応 continuation へ戻る形に
変更した。長い native loop を保持する場合・短い loop を破棄する場合の両方が成功。
失敗した fixture の記録は m33c-retirement.log に保存した。
M33d は runtime を変えずこの fixture だけ修正し、全体を再検証中。
M33 の固定 patch から GIL release（非 PGO/LTO）と FT debug を作成している。


M33 正当性検証完了: GIL debug 全 546（skip 5）と境界関連 1,202（skip 5）、
FT debug 全 546（skip 31）と境界・並行関連 1,231（skip 5）、
GIL/FT 新規テスト `-R 3:3`、GIL release method frontend 202（skip 1）が成功した。
FT の追加 skip 1 は、生の namespace binding hint を使う GIL 専用最適化のテスト。
新規テストを一括 skip する変更はない。

固定 GIL 非 PGO/LTO 実行ファイル SHA-256:
`473df2ec1bad758c2ef233bc8a3199a7d183bb3d885a179edc87e2a8e350cb87`。
固定 FT debug SHA-256:
`8c1b06d8ab471affdbd1024ad433c6ed6ede9f450c9e3fc867902b847ef43315`。
全ビルド・正当性テスト終了後、M33 GIL 非 PGO/LTO の 3 specification の
両順序比較を開始した。結果確定前なので性能改善の達成はまだ主張しない。


### M33 非 PGO/LTO screen 結果と namespace lookup の修正

3 specification / 15 結果、両順序の全 12 run が成功し、入力・実行ファイルの
同一性確認も成功。main 比: base32_small 1.0527 [1.0505, 1.0551]、
logging_format 1.0647 [1.0379, 1.0862]、nqueens 1.0883 [1.0788, 1.0968]。
全点推定は 1.10 以下だが、base64_small は 1.0950 [1.0492, 1.1793] で
block 間にも差（1.1413 / 1.0506）がある。全 worker を保持し、最終ビルドで確認する。
これは非 PGO/LTO の screen であり、M32 PGO/LTO との差を単独変更の効果とはしない。

レビューで namespace hint の通常辞書検索が任意キーの `__eq__` を実行し得ると
分かった。M33e の新規テストでは、実行しない分岐のコンパイル中に equality が
4 回呼ばれることを修正前バイナリで確認した（m33e-binding-before.log）。
これは今回追加した候補側の不具合で、main の不具合とは分類しない。
修正は unicode-key 辞書とキャッシュの keys version/index を検証して直接値を読む。
コンパイル中の Python 呼び出しを避け、関数の実行時ガードもそのまま保持する。
併せて符号の違う整数比較の警告 2 箇所を整理した。固定 M33 screen のソース・
バイナリは変更していない。M33e の再検証後に最終ビルドへ進む。


M33e の namespace 修正後は GIL debug test_opt 全 547（skip 5）と新規 5 テストの
`-R 3:3` が成功した。four-way runner の 8 テストも成功。
worker 単位の集計処理は既存の両構成の完全な比較データで検証し、元の結果を変更せず
一時ディレクトリへ再集計して成功した。

最終候補は `m33e-method-only.patch` で固定。FT release は完成し SHA-256 は
`1042e1f4a1cc1ed9319c0f4995b95b693a57c40ed0f395c9e0f17010af3be1fd`。
GIL PGO/full-LTO は学習用ビルド成功後、sandbox 外で seed 0・JIT 無効の同じ
PGO 学習 task を実行中。最終リンク後、GIL/FT の JIT・属性・C 関連テストを実施する。
その完了を待つ four-way controller を起動済み。3 worker、2 block、5 warmup、
5 value、CPU 2、worker timeout 60 秒（networkx は 15 秒、specification 上限 60 秒）。
両構成を準備してから FT と GIL を順番に計測する。並行するビルド・テストは行わない。
出力予定: `jit-artifacts/method-only-m33-full/`。local 8 と独立した確認比較はその後。


M33e 最終 GIL PGO/fullLTO が完成。SHA-256:
`b0d6fefaccd4f69a2c01785cc10e90309dfe08c67af1ebcb4cfe3c80d75dd50c`。
PGO 学習は一度で成功（139.3 秒）。失敗した profile の再利用はない。
FT/GIL の最終 native build ともに test_opt 547（skip 32 / 5）、
属性・呼び出し・monitoring 486（skip 3）、C decimal/binascii/re 1,154（skip 28）が成功。
実行ファイルの検証前後の SHA も一致した。four-way 全 suite の依存準備を開始した。
録画frontend・side traceの旧entry/exit名がソース・ビルド定義に残らないことも再確認。
共通uop backendやPythonのtraceback/tracemallocは別の機能として維持する。


全 suite は両構成とも 97 specification、23 dependency group を準備した。
既存の固定 fastapi group は Python 3.16 非対応の依存により準備できず、失敗を保持。
残る 96 specification の計測を FT から開始した。各仕様は同じ block 内で
main/candidate を続けて実行し、全仕様を一巡した後の次 block で順序を逆転する。
開発用 compare.py の「各仕様で両 block を続けて測る」順序とは区別する。
最終判定は両 block 完了後の全 worker と測定後 identity 検証に基づく。


M33 全体比較の FT 第1 block: asyncio_tcp / asyncio_tcp_ssl / asyncio_websockets が
main・candidate ともに成功した。以前の sandbox 制限による失敗はこの実行条件では
再発していない。ここまで 46 run に実行失敗なし。まだ逆順 block の前なので
この段階の値は最終比較として扱わない。


FT 第1 block の networkx と connected_components は両者成功。
networkx_k_core は main/candidate とも worker の15秒上限で timeout（rc 124）。
候補側の全体打ち切りは18.9秒で、ログに `Timed out after 15 seconds` を確認。
上限を延長せず比較不成立として残し、他の仕様の計測を継続した。


### M34: rangeのcompactness誤認を修正し、M33比較を中止

静的frontendがFOR_ITER_RANGEの返すC longをcompact intと仮定していた。
ブロック境界を越えて比較のcompactness guardが消え、`value < 5` が
`range(1 << 30, (1 << 30) + 20000)` の先頭5個を誤ってtrueとした。
GIL/FTのM33 release・JIT有効で期待値0に対し5。mainと候補のJIT無効は正常。
mainに由来する不具合ではなく、このmethod frontendの不具合である。
別の加算probeはdebug assertionを再現するがreleaseでは正しいため、
誤結果の根拠は比較probe（m33-range-comparison-results.json）と区別する。

M34はrangeの要素についてexact intだけを伝播し、compactnessを仮定しない。
新規テストは大小・正負の境界ごとにcodeを初期化して再compileし、先行guard missで
後続ケースが隠れないようにした。GIL debug全548（skip 5）と新規テストの
`-R 3:3`が成功（m34b-opt-full.log / m34b-range-refleak.log）。
修正前FT debugでも同じテストのassertion failureを確認済み。

M33のFT controllerを停止し、実行中worker終了後にcontrollerを終了した。
計測workerと再現テストは重ねていない。FT第1blockの188 runを保持し、
GIL・逆順block・local 8は未実施。中止理由・時刻はm33-boundary-pause.json。
この不完全な旧候補の測定を最終比較として集計しない。
次は同一M34 patchのFT debugと最終FT/GILビルドを検証し、別出力先
`jit-artifacts/method-only-m34-full/`で比較を最初から実施する。


M33中止後のFT/GIL identity再検証はともに成功。旧runnerも保存してから、
通常のfour-way runnerをM34の固定buildへ向けた。M34では最終buildの正当性検証後、
既知のGIL回帰10仕様を3 worker・両順序で先に確認する。点推定1.10超または失敗なら
そこで止めて調査し、通過後に全97仕様・local 8へ進む。判定前に測定回数を固定し、
遅いworkerを削除しない。PGOは最終GIL比較だけに使用する。


M34のFT debug/releaseビルドが成功（239.2秒 / 218.6秒）。
FT release SHA-256: `d3c547119584aaa1fb272ff8e36d16186c5f1278538db25591784866bccb3935`。
GILの新規PGO学習は139.4秒で成功した。同じ標準task、seed 0、JIT無効を維持し、
前候補のprofileは混ぜていない。最終リンク後に3構成の正当性検証へ進む。


M34最終GIL PGO/fullLTO SHA-256:
`44ca073ed4bca19fd04de31abd553c730ac799bf1a5debb3bc66fcfe05bb22d9`。
3構成でtest_opt全548、属性・呼び出し・monitoring 486、C関連1,154が成功。
skip数はFT debug 32/1/27、FT release 32/3/28、GIL release 5/3/28。
rangeの比較probeは3構成×JIT有効/無効の全6条件で正解し、FT debugの新規テスト
`-R 3:3`も成功。GIL debugの同テストも既に成功している。

最初のM34先行計測は無効とする。03:03:31 UTCに追加の短い正当性probeを実行し、
自動開始済みの計測と重なったため。遅い値を理由に除外するものではない。
controllerを停止し、実行中workerの終了を15.1秒待ってから終了した。
理由・時刻はm34-screen-protocol-violation.json、生データはm34-gil-final-screen-*に保持。
ソース・バイナリ・入力を変えず、同じ3 worker×2 block・10仕様すべてを
`m34b-gil-final-screen-*`へ取り直す。M34bは測定の識別名であり、runtime変更はない。
以後は計測終了を確認するまで追加の実行診断も行わない。


M34b先行比較は29/40 runまで実行失敗なし。両順序が終わった項目では、
Goは約0.87、Richardsは約0.92、Richards superは約1.04。
nqueensは約1.115、logging_formatは約1.134で10%超が見えている。
全runと測定後identity検証・worker単位の区間計算はまだ完了していない。

次の診断候補はgeneratorのsuspension境界とloggingのproperty/callee境界。
ソース上、現在のgenerator OSRはYIELD_VALUEの直前でTier 1へ戻る。
propertyは汎用属性取得を通すためgetterを静的inlineしない。
これらは時間差の原因とまだ確定していない。先行比較終了後、同じ固定buildで
main/candidate×JIT有効/無効のperfと実際のworkerのexecutorを調べる。
診断用の拡張・driverは準備だけとし、計測が終わるまでビルド・実行しない。


### M34b GIL PGO/fullLTO 先行比較の確定結果

10仕様・26結果、全40 run成功。測定前後のidentityが一致した。3 worker、両順序、全workerを等しく集計した結果。

| Benchmark | candidate/main | worker bootstrap 95% CI |
|---|---:|---:|
| logging_format | 1.1339 | [1.1244, 1.1443] |
| nqueens | 1.1152 | [1.1078, 1.1236] |
| logging_simple | 1.0917 | [1.0849, 1.0990] |
| base32_small | 1.0850 | [1.0837, 1.0863] |
| scimark_sor | 1.0649 | [1.0617, 1.0688] |
| base85_small | 1.0619 | [1.0563, 1.0667] |
| base64_small | 1.0591 | [1.0577, 1.0604] |
| regex_compile | 1.0439 | [1.0301, 1.0556] |
| richards_super | 1.0373 | [1.0356, 1.0390] |
| logging_silent | 1.0141 | [1.0107, 1.0176] |
| base32_large | 1.0088 | [1.0075, 1.0099] |
| shortest_path | 0.9999 | [0.9966, 1.0035] |
| telco | 0.9978 | [0.9946, 1.0009] |
| base85_large | 0.9953 | [0.9943, 0.9962] |
| base64_large | 0.9884 | [0.9871, 0.9897] |
| urlsafe_base64_small | 0.9816 | [0.9806, 0.9825] |
| scimark_fft | 0.9620 | [0.9559, 0.9702] |
| scimark_sparse_mat_mult | 0.9412 | [0.9327, 0.9547] |
| ascii85_small | 0.9343 | [0.9322, 0.9363] |
| richards | 0.9228 | [0.9131, 0.9296] |
| scimark_monte_carlo | 0.8865 | [0.8847, 0.8885] |
| base16_small | 0.8740 | [0.8720, 0.8760] |
| go | 0.8726 | [0.8643, 0.8781] |
| base16_large | 0.8046 | [0.7064, 0.8523] |
| ascii85_large | 0.7986 | [0.7973, 0.7997] |
| scimark_lu | 0.7598 | [0.7585, 0.7610] |

logging_formatとnqueensは区間の下端も1.10超。全suite・local 8を開始せず、修正に戻る。
logging_simpleは1.0917で境界に近い。base16_largeはblock間の差が大きいが全workerを保持した。
生データ: `jit-artifacts/regressions-20260919/m34b-gil-final-screen-*`。
未修正mainのFTはTier 1であり、今の表はGILのtracing/method比較だけを表す。
測定終了を確認してから、ABIを合わせた診断拡張をビルドし、perfの別実験を開始した。


### M35: generator yieldとmodule属性ロードを改善（実装・検証中）

M34のperf診断12 run（3仕様×両者×JIT有効/無効）が完了し、すべて成功した。
これは比較本番とは別の固定仕事量の診断。loggingは1,048,576 loop、nqueensは64 loop、
base32_smallは32,768 loop。loggingの各loop内部の反復も含むため、1 runは約1分になる。
全記録はm34-profiling.jsonとm34-perf-*。perfの時間を先行比較へ混ぜない。
nqueens候補のEvalFrameDefault selfは22.49%（coldは別に1.79%）。
ソース行ではFOR_ITER_GEN、YIELD_VALUE、POP_TOP、JUMP_BACKWARD_JIT、RESUME_CHECKが上位。
実際のexecutorではmainがgenerator間のframe遷移とyieldを含み、候補はyield直前でdeoptする。

M35は既存の_YIELD_VALUEを静的CFGの終端として使い、callerへTier 1で復帰する。
普通のreturn_offsetはiteratorの「終了先」なので、yieldではSEND/FOR_ITERのcache直後へ
戻る専用exitを設けた。suspensionを越える型推論やrecordingは追加しない。
frame遷移としてIP保存を保持し、callbackでmonitoring等が変わった場合のvalidity検査も入れる。

logging候補では、0.3%以上の行だけでも_LOAD_ATTR_MODULEが計4.18%を占めた。
M35では静的namespace hintから安定した属性を解決し、named dictionary dependencyと
実行時のexact-module/dictionary-identity検査を組み合わせる。
module自体を定数型として扱わず、__class__変更後も検査を残す。
属性値は型が不変なものに限定し、module値は除く。guardと結果ロードを一つのuopに保ち、
owner消費後のguard失敗でstack契約が壊れる既知パターンを避ける。FTではこの定数化をしない。

generatorのC/Python/yield-from callerと例外状態、moduleのbinding/dictionary/class変更・
unrelated値更新・値の寿命を含む5テストを追加。旧M34での失敗は新規native経路の不在であり、
旧候補の意味論の不具合を示すものではない。初回の生成器はFT条件分岐内のDEAD(owner)に対し
所有権の不一致を検出したため、FTの即時exit後に共通の所有権処理を置く形へ修正した。
生成器再実行後、非PGO/LTOのdebug buildで検証する。性能への効果はまだ未測定。

### M35b: 新規module命令のコード生成を修正（検証中）

M35の生成器は、専用yield exitのcache depthを0へ固定した後に成功し、
非PGO/LTO debug buildも成功した。しかし新規テストはnative codeでabortした。
gdb、最終uop列、stencilの機械語オフセットを照合し、原因はyieldではなく
_LOAD_ATTR_MODULE_CONSTと確定した。生成器は#ifdef内のEXIT_IF(true)を終端と解釈し、
後続のmodule guard/loadを削除していた。GIL専用frontendだけがこの命令を発行するため、
不要な条件付き無条件exitを除去した。11生成物を再生成して再ビルド中。
monitoringがcallback内で有効になるケースを加え、新規テストは計6件。
この6件、test_opt全体、refleak、generator/monitoring、生成器/JIT toolを順に検証する。
失敗したM35のログ・バックトレース・stencil照合結果は保持し、性能測定には使わない。

M35bの修正後、新規6件は成功。test_opt全554件は旧yield非対応を期待する2件だけ失敗し、
双方をnative yieldと専用exitの存在検査へ更新した。refleak用にgenerator codeを毎回
resetする。callback自体のreset_codeはfunction versionを恒久的にclearedへ変えるため、
通常の新規callbackを事前warmupして使う。M35c/dのテスト調整失敗も保存した。
runtimeはM35bのまま、最終テスト定義でM35e検証を進める。

M35eのGIL debug検証はすべて成功。test_opt 554件（5skip）、新規6件R3:3、
generator/genexp/yield-from/monitoring 201件、生成器/JITツール91件。
実行済みruntimeはM35bで、M35eはテスト定義調整後の検証ラベル。
独立source snapshotからFT debugとGIL release（非PGO/LTO）をビルドし、両者の
JIT全体・generator・C decimal等を検証してから、nqueens/logging/base64を
同条件main非PGO/LTOと逆順2block×3workerで測る。ビルド/検証中に測定しない。

### M35b: 独立ビルドの検証と非PGO先行比較が完了

FT debug: test_opt 554件（35skip）、generator/monitoring 201件、新規yield3件R3:3に成功。
C検証1154件ではtest_reのforkserver socketがsandboxに拒否されたが、通常環境で
そのファイルを再実行して成功。GIL releaseもtest_opt・generator・C検証に成功。
GIL非PGO/LTO先行比較は3仕様15結果、全12 run成功、identity一致。
main非PGO/LTOとの比較であり、PGO/fullLTOの合否には流用しない。

| Result | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0836 | 1.0681–1.0942 |
| logging_format | 1.0540 | 1.0414–1.0639 |
| base32_small | 1.0368 | 1.0330–1.0415 |
| base64_small | 1.0354 | 1.0337–1.0371 |
| logging_simple | 1.0309 | 1.0214–1.0390 |
| base85_small | 1.0192 | 1.0174–1.0210 |
| base64_large | 1.0074 | 1.0064–1.0085 |
| base32_large | 1.0036 | 1.0024–1.0050 |
| base85_large | 1.0010 | 1.0004–1.0017 |
| logging_silent | 0.9846 | 0.9796–0.9903 |
| ascii85_small | 0.9666 | 0.9651–0.9681 |
| base16_small | 0.9610 | 0.9569–0.9654 |
| urlsafe_base64_small | 0.9537 | 0.9520–0.9554 |
| ascii85_large | 0.9064 | 0.9061–0.9067 |
| base16_large | 0.8896 | 0.8871–0.8921 |

同じsource snapshotで最終GIL PGO/fullLTOとFT releaseをビルドする。
検証後に10仕様screenを行い、合格してから全suiteとlocal8へ進む。

### M36: mainにもあるmodule subclass属性の誤結果を修正

module.__class__をdata descriptor付きsubclassへ変更すると、直接参照は2000を
返すが、特殊化済み関数は辞書に残る1000を返す。main/M35b×GIL/FT×JIT0/1の
8構成すべてで再現した。最初からsubclassでも特殊化後に誤結果となる。
_LOAD_ATTR_MODULEとspecializerがtp_getattroの同一性だけでmodule属性アクセスを
選んでいたため、継承getterを持つsubclassのdata descriptorを無視していた。
両者をexact moduleに限定し、subclassは通常の属性探索へ戻す。
Tier1の2テストとnative method内callback越しの1テストを追加し、修正前の失敗を確認。
詳細はbugs_report.md M-18。M35bの最終比較・全suite待機プロセスを停止し、
最終計測は未開始であることをm35b-final-measurements-cancelled.jsonに記録した。
M35b最終ビルドは参照用に完了させるが、合格候補にはせず、M36を非PGO debugで検証する。

M36 GIL debug検証完了: JIT無効test_opcache 97件、JIT有効test_opt 555件（5skip）、
property/descriptor/monitoring/generatorと生成器/JIT toolを合わせて491件（1skip）が成功。
新規native1件とTier1の2件のR3:3も成功した。
mainへの新規テスト適用は、最初のLib overlayではdisのopcode metadataが候補側になったため、
そのログを意味論の根拠には使わない。frozen mainのLib/disを保ってテストファイルのみ
読み込む再実行で、両件とも1000 != 2000という誤結果を確認した
（m36-main-opcache-before-matched-lib.log）。8構成の独立probeも各binary固有Libを使用した。
修正済みsnapshotからFT debug/releaseとGIL PGO/fullLTOを作成中。

### M36: 最終ビルドの正しさ検証が完了、先行比較中

FT debug/releaseとGIL PGO/fullLTOの全12検証groupが成功。
各構成でtest_opt 555件、call/property/descriptor/monitoring/generator 589件、
C decimal/binascii/re 1154件、JIT無効test_opcache 97件を実行した。
M18の独立probeは3構成×JIT0/1の全6回が成功。FTのnative1件・Tier1の2件のR3:3も成功。
最終GIL build SHA-256: 9443d6899ff5ab7dcc116442fd0a82dac61ff06c65d7b1b3dac4b7f689ba55f5。
同一ソースの2 releaseを固定し、10仕様のGIL先行比較を開始した。
計測中にビルド・テスト・profilingは実行しない。途中の遅い値も含め、全40 runを保持する。

### M36: 最終先行比較は3項目で10%を超過

GIL PGO/fullLTOの10仕様26結果、全40 runが成功し、前後のidentityも一致。
logging_format 1.1173（95% CI 1.1015–1.1324）、logging_simple 1.1065
（1.0860–1.1288）、nqueens 1.1007（1.0991–1.1025）が基準を超えた。
残る23結果は1.10以下。Go 0.8538、Richards 0.9162、LU 0.7576、
regex_compile 1.0610、C decimal使用telco 1.0054。全suite/local8は未開始。
全workerを保持し、判定gateで後続測定を停止した。

測定終了後、固定work量のperf診断12回（3仕様×main/candidate×JIT0/1）を実施、
全回成功。候補nqueensのEvalFrameは19.37%+cold1.83%、mainは0.50%。
permutationsの生成器作成CALLは_METHOD_CALLとなり、RETURN_GENERATOR非対応の
calleeへ入った後、callerのnative継続を失う。生成器本体のnative yieldは既に存在する。
logging候補のnative _LOAD_ATTR_MODULEが1.94%、_LOAD_GLOBAL_MODULEが1.78%。
プロファイルは原因調査用で、上記時間比には混ぜない。

次は、生成器作成を通常vectorcallで完了してnative callerへ戻す経路と、
型を定数と仮定しないmodule bindingロードを実装・検証する。
既存一般vectorcall helperはPython callableにも対応し、実際のcallableを毎回呼ぶ。
moduleのbinding監視とruntime属性guardを維持し、__class__変更を型定数化で消さない。

M37 GIL debug検証は全4group成功。新規4件、test_opt 559件（5skip）、
新規4件のR3:3、call/property/descriptor/monitoring/generator/生成器/JIT toolの
680件（1skip）が通った。codeの種類を変える代入には既存のDeprecationWarningを
明示的に検査する。凍結patchにもこのテスト定義を含めた。
FT debugとGIL非PGO/LTO releaseを独立にビルド中。両者のテスト後、
同設定mainとのnqueens/logging/base64先行比較を2順序×3workerで行う。

### M36最終GIL先行比較の全26結果

時間比はmethod/main。95%区間は2順序×3workerを残したbootstrap。
全40 run成功、identity一致。下表はM37の結果ではない。

| Benchmark | 時間比 | 95% CI |
|---|---:|---:|
| logging_format | 1.1173 | 1.1015–1.1324 |
| logging_simple | 1.1065 | 1.0860–1.1288 |
| nqueens | 1.1007 | 1.0991–1.1025 |
| base32_small | 1.0861 | 1.0845–1.0877 |
| scimark_sor | 1.0684 | 1.0672–1.0697 |
| base64_small | 1.0649 | 1.0639–1.0660 |
| regex_compile | 1.0610 | 1.0563–1.0652 |
| base85_small | 1.0297 | 1.0258–1.0333 |
| richards_super | 1.0184 | 1.0145–1.0217 |
| base32_large | 1.0138 | 1.0127–1.0147 |
| shortest_path | 1.0103 | 1.0078–1.0124 |
| telco | 1.0054 | 1.0029–1.0077 |
| base85_large | 0.9949 | 0.9921–0.9967 |
| urlsafe_base64_small | 0.9874 | 0.9866–0.9883 |
| base64_large | 0.9860 | 0.9844–0.9879 |
| logging_silent | 0.9729 | 0.9622–0.9814 |
| scimark_sparse_mat_mult | 0.9468 | 0.9395–0.9597 |
| scimark_fft | 0.9396 | 0.9386–0.9405 |
| ascii85_small | 0.9357 | 0.9345–0.9367 |
| richards | 0.9162 | 0.9147–0.9177 |
| scimark_monte_carlo | 0.9037 | 0.9011–0.9063 |
| base16_small | 0.8913 | 0.8894–0.8933 |
| go | 0.8538 | 0.8498–0.8571 |
| base16_large | 0.8402 | 0.8371–0.8431 |
| ascii85_large | 0.7951 | 0.7945–0.7957 |
| scimark_lu | 0.7576 | 0.7551–0.7598 |

M37独立ビルドの検証も成功。FT debug/GIL releaseともtest_opt 559件
（FT 37skip、GIL 5skip）、関連589件、C decimal/binascii/re 1154件が成功。
FTの生成器作成2件R3:3も成功した。GIL release SHA-256は
 d4223de840fbe04fca3e96f665dd753d124d0fdfedb65f91ec1534d9245ca9d2。
非PGO/LTOの3仕様15結果を計測開始。計測中の追加ビルド・テスト・profilingは行わない。
後続の最終ビルド、最終検証、10仕様screen、全97仕様×4構成、local8は
順次のgateで接続した。先行比較が10%を超えれば後続へ進まない。

### M37: 非PGO先行比較で生成器作成の変更を棄却

全12 run・15結果が成功し、identity一致。Nqueensは両順序で悪化し、
最終ビルドgateで停止した。PGO/FT releaseと全suite/local8は未実行。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.1609 | 1.1575–1.1638 |
| logging_format | 1.0284 | 1.0231–1.0346 |
| base32_small | 1.0150 | 1.0138–1.0160 |
| base85_small | 1.0085 | 1.0067–1.0104 |
| base64_small | 1.0041 | 1.0026–1.0057 |
| logging_simple | 1.0035 | 0.9976–1.0093 |
| base64_large | 1.0020 | 1.0017–1.0022 |
| base85_large | 1.0005 | 0.9999–1.0011 |
| base32_large | 0.9977 | 0.9953–0.9998 |
| logging_silent | 0.9763 | 0.9699–0.9829 |
| base16_small | 0.9591 | 0.9423–0.9867 |
| urlsafe_base64_small | 0.9385 | 0.9127–0.9600 |
| ascii85_small | 0.9363 | 0.9349–0.9376 |
| ascii85_large | 0.9037 | 0.9007–0.9056 |
| base16_large | 0.8690 | 0.8660–0.8723 |

生成器作成に汎用C vectorcallを挟む変更を外す。native継続を保つだけでは
追加の呼出し境界を取り戻せなかった。module bindingの改善は残す。
これは非PGO比較であり、最終PGO構成の性能値にはしない。

### M38: rangeの検査を取り出し地点へ集約（検証中）

_ITER_NEXT_RANGE_COMPACTを追加。現在のC long値が1 Python digit内であることを
反復子のstart/len更新前に検査し、成功した後続CFGでのみcompact intとする。
大きい値では同じ未消費の要素をTier1へ渡す。yieldを越えて事実を保持しない。
従来のM34大整数テストに加え、正負のdigit境界を両方向にまたぐrangeと、
yield中のiterator.__setstate__変更を検査する2テストを追加。旧M37は新命令の
不在によりこの2テストで失敗した。11生成物の再生成は成功しdebug build中。
M38のソース編集は固定M37の終盤に行ったが、M37のfrozen source/binaryは
変更せず、前後identity一致を確認。再生成とビルドは全計測完了後に開始した。

M38新規検証の初回は5件中、setstateの期待値1件だけ失敗。
iterator.__setstate__は元のrangeではなく残りのrangeから位置を進めるため、
すでに1個消費したテスト側のoffsetが1大きかった。mainと候補のJIT0でも
同じ挙動を確認し、Objects/rangeobject.cの実装に合わせてテストを修正した。
正負の境界4方向、M34大整数、module2件は成功していた。
runtimeを変更せず、修正したテストでM38b検証を行う。失敗ログは保持する。

M38bの修正後テストは全group成功。新規range2件・M34大整数・module2件の5件、
test_opt 559件（5skip）、同5件のR3:3、関連680件（1skip）。
新range命令のguard失敗は値を消費せず、yield後に変化したiteratorも再検査できた。
同runtimeと修正済みテストを凍結してFT debug/GIL非PGO releaseをビルド中。

M38b独立ビルド検証は全7group成功。両構成でtest_opt 559件
（FT 38skip/GIL 5skip）、関連589件、C関連1154件が成功。
FTのrange検査R3:3も成功し、非PGOの3仕様比較を開始した。
FTで新規setstateテストをskipするのは、外部と共有されたrange iteratorが
既存のunique-reference guardでTier1へ戻るため。通常の境界テストは両構成で実行した。

### M38b: 非PGO先行比較は15結果すべて10%以内

全12 run成功、前後identity一致。全workerを保持し、全15結果で95%区間上端も1.10未満。
同じmain非PGO/LTOとの比較であり、PGO設定の合否には流用しない。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0730 | 1.0687–1.0779 |
| logging_format | 1.0323 | 1.0200–1.0458 |
| base32_small | 1.0223 | 1.0215–1.0232 |
| base85_small | 1.0176 | 1.0079–1.0336 |
| base85_large | 1.0023 | 1.0004–1.0048 |
| base64_large | 1.0021 | 1.0016–1.0026 |
| base64_small | 0.9999 | 0.9982–1.0018 |
| base32_large | 0.9996 | 0.9992–1.0000 |
| logging_simple | 0.9927 | 0.9680–1.0103 |
| logging_silent | 0.9916 | 0.9883–0.9956 |
| urlsafe_base64_small | 0.9686 | 0.9647–0.9722 |
| ascii85_small | 0.9427 | 0.9332–0.9596 |
| base16_small | 0.9356 | 0.9331–0.9380 |
| ascii85_large | 0.9051 | 0.9047–0.9055 |
| base16_large | 0.8698 | 0.8616–0.8782 |

生成器作成のC呼出しを外し、range guardを集約した候補を採用する。
最終比較用FT releaseとGIL PGO/fullLTOのビルドを開始。開発比較は引き続き
非PGO/LTOで行い、PGOは最終構成の比較にだけ用いる。最終検証後は10仕様screen、
合格後に4構成の全suiteとlocal8へ進む。

M38bの大きなstepとC long端点の補助検証も成功。5ケースをmain/candidate×GIL/FT×
JIT0/1の8構成で比較し、全結果が一致。両candidateのJIT1で新compact guardを確認した。
probe_m38b_range_steps.py と m38b-range-steps.json に入力・結果を保存。
FT最終releaseのビルドは成功（SHA-256:
4ae870d62a4e22e0eeabb62f90b7f827cfc4c472141a49a6dec8f962c83719e1）。
GILはPGO計装ビルド中。これらのビルド・補助検証は先行計測完了後に実行した。

M38bの生成コードを固定入力の補助診断でも確認。元のnqueens(8)を16回実行し、
毎回92解であることを検査した後、2つのgenexprのexecutorを取得した。
M36では各bodyに_ITER_NEXT_RANGEと_GUARD_TOS_OVERFLOWEDが2個あった。
M38bは_ITER_NEXT_RANGE_COMPACTの取り出し時検査で、後続2個を除去できていた。
タプルのindex boundsと取り出した値の検査は別に行う。
診断はM36最終GILとM38b開発GILのコード構造比較であり、実行時間は比較していない。
バイナリ・workload hash、warmup回数、解数、全uopをm38b-nqueens-ir-*.jsonに保存。
実施時は最終PGO学習中で、性能計測との重複はない。

### M39: small-int range経路を準備（未検証）

最終M38bのNqueensは両順序で約1.10となり、境界に近い。既知screenの95%区間が
1.10をまたぐ場合は全matrixの前に解決するgateを追加した。全測定は保持する。
次候補では、compact rangeのうち既存small-int cache内の値を直接borrowし、
PyLong_FromLongへのC呼出しを省く。それ以外は既存の通常割当てを使う。
負側・正側のsmall-int cache境界を既存テストに追加。runtime/テストのソース編集のみで、
M38bの固定binary/sourceは変更していない。再生成・ビルドは最終screenと
後続gateが停止したことを確認してから実行する。性能効果は未測定。

M38b最終GIL buildも成功。SHA-256:
eee1d260681749005121575d52af384e1146f6959be6fd7123ee4d624eac55dd。
PGO計装368.1秒、標準43テストの学習139.0秒、最終ビルド203.4秒。
FT/GILの全8検証group（JIT559件、関連589件、C関連1154件、JIT0 opcache97件）が成功。
M18 probeはFT debug/release/GIL×JIT0/1の6回も成功した。最終GIL screenを継続中。
M39は同screenを最後まで保持し、既知結果が未解決で後続gateが停止した後にだけ再生成・
ビルド・テストを行う。先行比較・全suite・local8は異なる候補の値を混ぜない。

### M38b: 最終GIL先行比較は全平均が1.10以下、2結果は区間が境界をまたぐ

10仕様26結果、全40 run成功、identity一致。全workerを保持した。
nqueens 1.0996 [1.0970, 1.1023]、logging_simple 1.0847 [1.0481, 1.1169]。
他の24結果は95%区間の上端も1.10以下。全suite/local8は未開始。
平均のgateは通過したが、既知結果の不確かさを解決するgateで後続を停止した。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0996 | 1.0970–1.1023 |
| base32_small | 1.0869 | 1.0858–1.0880 |
| logging_simple | 1.0847 | 1.0481–1.1169 |
| scimark_sor | 1.0792 | 1.0784–1.0801 |
| logging_format | 1.0604 | 1.0455–1.0739 |
| regex_compile | 1.0458 | 1.0354–1.0545 |
| base64_small | 1.0457 | 1.0449–1.0466 |
| base85_small | 1.0347 | 1.0333–1.0360 |
| richards_super | 1.0137 | 0.9854–1.0297 |
| shortest_path | 1.0075 | 1.0034–1.0140 |
| base32_large | 1.0051 | 1.0044–1.0058 |
| telco | 1.0008 | 1.0000–1.0016 |
| base85_large | 0.9974 | 0.9964–0.9983 |
| logging_silent | 0.9875 | 0.9722–0.9980 |
| base64_large | 0.9847 | 0.9827–0.9861 |
| urlsafe_base64_small | 0.9701 | 0.9688–0.9713 |
| scimark_fft | 0.9583 | 0.9575–0.9591 |
| scimark_sparse_mat_mult | 0.9540 | 0.9435–0.9681 |
| ascii85_small | 0.9266 | 0.9242–0.9301 |
| richards | 0.9226 | 0.9171–0.9276 |
| scimark_monte_carlo | 0.9220 | 0.9190–0.9242 |
| go | 0.8612 | 0.8584–0.8637 |
| base16_small | 0.8513 | 0.8501–0.8527 |
| base16_large | 0.8077 | 0.8062–0.8095 |
| ascii85_large | 0.7962 | 0.7956–0.7968 |
| scimark_lu | 0.7816 | 0.7805–0.7827 |

logging_simpleのcandidate worker平均は約2.928–3.230µsと幅があり、
中央値での時間比も1.0990。速いworkerを除外したり、平均だけで合格とはしない。
M39の非PGO比較完了後、最終PGO buildの前に、固定M38b/mainで追加の診断を行う。

### M39: debug検証完了

small-int cacheを直接borrowする変更は、新規/境界5件、test_opt559件（5skip）、
同5件R3:3、関連680件（1skip）が成功。small-int cacheの正負境界と、
cache外・compact範囲外の既存ケースを実行した。FT debug/GIL非PGO releaseを
独立snapshotからビルド中。性能は未測定。M38bの全計測と後続gate停止後に
再生成・ビルドを開始した。

M39独立ビルドの全検証も成功。GIL/FTともJIT559件、関連589件、C関連1154件、
FT境界R3:3を通過し、非PGOの15結果比較を開始した。
PGOの追加ビルドはまだ開始しない。M39の計測完了後、固定M38b/mainでloggingの
診断を2逆順group×各6worker（合計各12worker）実行する。workloadは元のlogging3項目。
診断hookは計測後にPIDとexecutor列を保存し、workerの速さと生成コードを対応づける。
診断の時間を性能目標の判断用データへ混ぜない。診断中はビルド/別測定を行わない。

### M39: 非PGO比較は全15結果で95%区間上端も1.10未満

全12 run成功、identity一致。追加のsmall-int cache経路を採用する。
nqueensは1.0642 [1.0605, 1.0672]。最終PGOでの効果はまだ測っていない。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0642 | 1.0605–1.0672 |
| logging_format | 1.0299 | 1.0202–1.0414 |
| base32_small | 1.0216 | 1.0147–1.0307 |
| base85_small | 1.0110 | 1.0075–1.0142 |
| logging_simple | 1.0108 | 1.0056–1.0171 |
| base64_large | 1.0034 | 1.0031–1.0038 |
| base85_large | 1.0021 | 1.0003–1.0047 |
| base32_large | 0.9994 | 0.9989–1.0001 |
| base64_small | 0.9959 | 0.9805–1.0049 |
| logging_silent | 0.9759 | 0.9707–0.9810 |
| urlsafe_base64_small | 0.9621 | 0.9605–0.9639 |
| ascii85_small | 0.9376 | 0.9362–0.9389 |
| base16_small | 0.9327 | 0.9057–0.9495 |
| ascii85_large | 0.9064 | 0.9055–0.9078 |
| base16_large | 0.8632 | 0.8599–0.8664 |

logging診断の初回はhook名をcheck_runtimeと誤記し、argparse段階で停止。
測定は未開始で、失敗ログを保持。登録済みft_jitへ修正し、workerへ必要な環境変数を
明示的に継承してdiagnostic2として再実行する。ABIを一致させたmain/candidateの
診断helperを用意済み。M39最終PGOのビルドは診断終了・評価まで開始しない。

M40初回ビルドは新規exit uopのdescriptorが生成器でPyObject*型となり、helperの
uint64_t引数へ暗黙変換できず失敗。明示的なuintptr_t経由の変換を追加してM40bとして
再生成・再ビルドした。初回失敗ログを保存し、後続検証は新しいlabelへ分離。

### M40c: stale guardの直接・inline回帰テストが成功

M40b runtimeで小→大int probeを再実行し、旧executorが無効化され、
新executorに汎用_BINARY_OPが含まれることを確認した。単発miss時は旧executorが有効。
inlineテストは新しい関数にreset_codeをかけてしまい、関数変更によるinlining対象外の
条件を作っていた。独立namespaceで毎回新規作成する関数をそのまま使用する形へ修正。
直接/inline両テストが成功。runtimeはM40bと同じで、テスト修正を含むsnapshotをM40c
として保存する。初回失敗を含む全ログを保持し、広域debug検証からやり直す。

実際のLogRecord.__init__にも決定的probeを追加した。time_nsをmutable値を返す
関数に固定し、_startTimeとの差を1000ns→2**32nsへ変更する。M39では除算guardと
同一executorが残り、M40cでは旧executorが無効化され除算guardが消える。
両方のrelativeCreatedは4294.967296msで一致。構造・正しさの検証であり性能値ではない。

opcodeをBINARY_OP_EXTENDのまま保ち、descriptorだけ変わるint+float→float+intの
probeも成功。旧methodは無効化され、異なるdescriptorの新methodへ移行した。
最終FT/GIL検証にもこのprobeとlogging phase probeを加える。
M40cのGIL debugは新規/境界7件、JIT561件（5skip）、新規7件R3:3、
関連680件（1skip）がすべて成功。固定FT-debug/GIL非PGO buildに進んだ。

M40c通常環境での再開後、全7group（成功済み2groupを含む）の検証が完了。
FT/GILともJIT561件、関連589件、C関連1154件に成功し、FT新規/境界5件の
R3:3も成功した。追加7件のGIL debug R3:3は先に成功済み。
非PGO比較15結果を開始し、最終ビルドはその完了と合否確認まで待機する。

### M40c: 非PGO比較の全15結果で95%区間上端も1.10未満

全12 run成功、identity一致。遅いworkerを含めてすべて保持した。
この構成ではnqueens 1.0735、logging_format 1.0299、logging_simple 1.0140。
最終PGO構成でのloggingのばらつき解消はまだ未確認。GIL PGO/fullLTOと
FT O3/noPGO/noLTOの最終buildを開始する。全suite/local8はまだ未開始。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0735 | 1.0706–1.0766 |
| logging_format | 1.0299 | 1.0233–1.0371 |
| base32_small | 1.0198 | 1.0181–1.0213 |
| base64_small | 1.0169 | 1.0015–1.0449 |
| logging_simple | 1.0140 | 1.0052–1.0236 |
| base85_small | 1.0071 | 1.0059–1.0084 |
| base64_large | 1.0019 | 0.9998–1.0033 |
| base32_large | 0.9995 | 0.9985–1.0002 |
| base85_large | 0.9991 | 0.9964–1.0006 |
| logging_silent | 0.9857 | 0.9836–0.9877 |
| urlsafe_base64_small | 0.9608 | 0.9588–0.9627 |
| base16_small | 0.9494 | 0.9481–0.9507 |
| ascii85_small | 0.9377 | 0.9360–0.9394 |
| ascii85_large | 0.9050 | 0.9045–0.9055 |
| base16_large | 0.8616 | 0.8585–0.8646 |

### M40c: 最終buildと全8検証groupが成功

GIL最終PGO/fullLTO buildは203.6秒、SHA-256: 70920f0a2bf782feab44bd448cd709ff433ac44ef66835c911ab4beda6d969b8。
FT/GILともJIT561件、関連589件、C関連1154件、JIT0 opcache97件が成功。
M18 module-class probeはFT debug/release/GIL×JIT0/1の全6回成功。
M40 descriptor変更・logging phaseのprobeもFT debug/release/GILの全6回成功し、
いずれも旧executorが無効化されることを確認した。
最終GIL10仕様26結果の先行比較を開始。全suite/local8はその合否確認後。

### M40c: 最終GIL screenの全26結果で95%区間上端も1.10未満

10仕様・全40 run成功、実行ファイル/入力のidentity一致、失敗なし。全workerを保持。
既知のnqueensとlogging_simpleの閾値不確かさを解消し、全suiteへのgateを通過した。
logging_simpleの候補worker平均は今回2.988–3.152µs（前の診断では最大3.287µs）。
ばらつきがゼロになったという意味ではない。成功経路のsmall-int cache利用と、
Tier 1が変更済みの算術特殊化から再コンパイルする処理を維持する。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0842 | 1.0807–1.0875 |
| logging_format | 1.0784 | 1.0642–1.0946 |
| base32_small | 1.0668 | 1.0658–1.0676 |
| scimark_sor | 1.0587 | 1.0576–1.0597 |
| base64_small | 1.0519 | 1.0511–1.0528 |
| logging_simple | 1.0473 | 1.0283–1.0655 |
| regex_compile | 1.0286 | 1.0145–1.0436 |
| base85_small | 1.0270 | 1.0263–1.0277 |
| richards_super | 1.0231 | 1.0148–1.0290 |
| shortest_path | 1.0094 | 1.0078–1.0109 |
| base32_large | 1.0070 | 1.0046–1.0101 |
| telco | 0.9993 | 0.9944–1.0046 |
| logging_silent | 0.9966 | 0.9919–1.0023 |
| base85_large | 0.9952 | 0.9934–0.9964 |
| urlsafe_base64_small | 0.9847 | 0.9831–0.9862 |
| base64_large | 0.9846 | 0.9835–0.9857 |
| scimark_fft | 0.9706 | 0.9659–0.9783 |
| scimark_sparse_mat_mult | 0.9698 | 0.9605–0.9850 |
| ascii85_small | 0.9335 | 0.9330–0.9340 |
| scimark_monte_carlo | 0.9167 | 0.9155–0.9179 |
| richards | 0.9155 | 0.9077–0.9217 |
| base16_small | 0.8884 | 0.8860–0.8909 |
| go | 0.8779 | 0.8751–0.8809 |
| base16_large | 0.8051 | 0.8038–0.8064 |
| ascii85_large | 0.7970 | 0.7961–0.7979 |
| scimark_lu | 0.7506 | 0.7489–0.7525 |

public four-way runnerの候補をM40cへ固定し、harnessの8テストも成功。
出力先 jit-artifacts/method-only-m40c-full で全97仕様の準備・実行を開始した。
FTを先に、次にGILを順次測る。各構成2逆順block、3worker×5warmup×5value。
fastapiは既知の依存準備失敗が残り、未完了として記録される。
全suite後にbenchmarks/の元の8本（SQLAlchemy含む）を比較する。全体の10%達成は未確認。

### M40c: FT全suiteの第1block完了、95仕様で両者が成功

95仕様・122結果が比較でき、片順序の全時間比が1.10以下。最大は
gc_traversal 1.0657、connected_components 1.0641、logging_silent 1.0515。
参考の幾何平均は0.9283。これはまだ単独blockの暫定値で、
FT mainはTier 1、候補はmethod JIT（複数threadstate時はTier 1）である。
fastapiの依存失敗とnetworkx_k_coreの両者timeoutは未完了として保持。
順序を反転したFT第2blockを開始した。最終identity検証・区間評価は両block完了後。
GILの全suiteとlocal 8はまだ未実施。
