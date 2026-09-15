# CPython Tier 2：Linux上で行う2〜3日間の実装計画

**現在の目標（2026-09-14）**：全6ベンチマークのmain比の**算術平均0.5以下**。
開始時の480値は **0.7944918**。最新の条件付き属性返却screen（3 blocks、3 builds、540値）は
**0.6564989**（対応する直前版0.6620986）で、目標は未達。
DeltaBlue/Btreeは3 blockとも短縮、他4本は小さな回帰があり、前版比算術平均は0.9954716。
各blockの各scriptで10値の平均時間からcandidate/main比を求め、blocksと6 scriptを
等重みの算術平均で集計する。途中screenは3 blocks、最終goal判定は4 blocksとする。
入力・CLI・warmups=3・values=10・loops=1、固定main、PGO/LTOなしの比較条件を維持する。
最新の採否・検証・次の工程は末尾に記録する。

**前回結果（2026-09-13）**：必須のint/float/builtin最適化を実装・検証し、追加目標の
全6ベンチマークの計測区間の時間比は幾何平均 **0.49208（約2.03倍速）**となった。
LLVM 21・PGO/LTOなし・実験6オプションONの同条件比較。起動込みは0.62891。
最終条件・個別比・生データは末尾の「全6本の最終判定」に記録した。

参照HEAD：`2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127`  
現在のhead branch：`codex/run-native-measurement-for-recurrences`  
現在のbase branch：`codex/add-experimental-optimizing-jit-backend`

## 0. この計画の位置づけと権限

この文書を、ローカルのCodex CLIが継続的に更新する実装計画として使う。2〜3日は開発・検証のtimeboxであり、一つの対話ターンが必ずその間動き続けるという意味ではない。途中の小修正、調査、ビルド成功を最終成果にせず、以下の一貫した機能と検証まで進める。完成すれば日数を消化せず終了してよい。

GitHubへコメント、レビュー、push、PR作成・変更を行わない。Cloudタスクを起動しない。ローカルの編集、ビルド、テスト、計測、内容のまとまったcommitは行ってよい。既存の変更を破棄せず、remote/base branchを勝手に変更しない。システム設定の変更、未承認の権限昇格、ネットワーク制限の迂回は行わない。

開始時に実際のHEAD、dirty state、AGENTS.md、既存の計画ファイルを読む。参照HEADより新しい変更があれば差分を確認して取り込む。以前のPRコメントにある「小修正で止める」「rangeだけ」「floatだけ」という作業範囲は、この計画では継続しない。ただし既存の安全性条件は維持する。

## 1. 目的と最終ゴール

長期目標は、Python処理が支配的なプログラムを現在より大幅に高速化し、最終的に3倍という目標へ近づけることである。今回の2〜3日間に、全pyperformanceで3倍になることを約束・完了条件にはしない。

今回の主目標は次の状態を作ること。

> 既存Tier 2とcopy-and-patchを維持し、通常のhot trace内の小さいint/float算術領域と、選んだ組み込み呼び出し・そのconsumerを最適化する。中間box、汎用dispatch、冗長なguardを削減し、それが実プログラムで働くことを測定する。

必須の成果は四つ。

1. **float**：現在の積和・積差の所有権別経路を、実行確認・例外・丸め・nativeの証拠が揃った基準にする。これ以上のfloat専用opcode追加を単独の目的にしない。
2. **int**：rangeループ全体に限定されない、checked signed-i64の複数演算と比較を扱う再利用可能な経路を実装する。少なくとも二つの異なる式で同じ仕組みを使う。
3. **builtin**：`len`の結果とconsumerの融合、および少なくとも一種類の実際の組み込みメソッドを最適化する。第一候補は`str.startswith`/`endswith`の共通family。profileに根拠があれば`dict.get`等へ変更してよい。
4. **統合**：最適化前に固定したworkload群でbaseline/treatmentを測り、各最適化の実行回数、guard失敗、減った処理、コードサイズ、起動・warmup費用、回帰を説明する。

上の機能数を満たすために、効果のないコードや未検証の経路を有効化してはならない。成果を「実装済み」「機能検証済み」「native実行済み」「性能上有効」「未検証」に分ける。主張できる範囲を正直に残す。

## 2. 現在地：何を再利用し、何をまだ証明するか

参照HEADでは、整数のsum/squares/constant/affine range reductionと、floatのproduct-add/subtract融合がある。新しく追加されたshared float版は、外部aliasのあるaccumulatorを変更せず、最終結果を新しいPyFloatとして確保する。unique版は既存のuniqueなboxを結果として再利用する。

shared版は、もともとproductを一度確保して結果へ再利用していた経路に対し、allocation総数を減らさない場合がある。中間boxの保存・再読込やuopの受け渡しが減ることと、allocationが一つ減ることを混同しない。

作者報告では参照HEADのdebugテストは328件・3skip。最新shared版のnative比較は未実施。過去の約6%のnbody改善は以前の実装に対する結果であり、このHEADや今後のint/builtinの実測値として転記しない。本計画の作成者も、このHEADをローカルビルドしていない。

このtreeには既に以下がある。開始時のinventoryで詳細と適用条件を確認し、重複実装を避ける。

- `CALL_LEN` / `_CALL_LEN`。実行部には`PyObject_Length()`→`PyLong_FromSsize_t()`がある。
- `_CALL_LIST_APPEND`と`_PyList_AppendTakeRef()`を使う経路。
- method descriptorのO/NOARGS/FAST/FAST_WITH_KEYWORDS経路と、既知のC関数ポインタを埋め込む`*_INLINE`版。
- 型が分かる`isinstance`の定数化、既存float/int特殊化、in-place処理。
- 型・ownership解析、executor、side exit、stack cache、生成コードとstencil基盤。

`*_INLINE`という名前は、必ずしもC関数本体のインライン展開ではない。既存helper呼び出しやargument conversionまで確認する。

主要ファイル：

- `Python/optimizer_analysis.c`：最適化passの構成、float融合。
- `Python/optimizer_bytecodes.c`：abstract interpreter、型・unique情報、builtin/method callの解析。
- `Python/optimizer.c`：range regionの認識・lowering、executor準備。
- `Python/bytecodes.c`：実際のuop semantics。
- `Python/ceval_macros.h`：共有算術・range/exit helper。
- `Include/internal/pycore_stackref.h`：borrow/ownedの契約。
- `Tools/cases_generator/`：各生成器とescape/stack metadata。
- `Tools/jit/`：stencil生成・LLVM検査・既存測定ツール。
- `Objects/unicodeobject.c`、`Objects/dictobject.c`、`Objects/listobject.c`、対応するArgument Clinic出力：選んだbuiltinのsemantics。

## 3. 設計方針：小さい共通基盤、具体的なlowering

維持するpipelineは次のもの。

    既存のtrace recording
        → 型・所有権の解析
        → boundedなvalue/region解析とbuiltin semantics
        → guards / exit state / profitabilityの検証
        → 既存uop / fused uopへのlowering
        → copy-and-patch

新しい実行tier、runtime LLVM依存、別assembler backend、Python製の未接続IR実験、汎用CFGコンパイラを追加しない。既存の解析へ少量の補助情報を足す方が小さければそれを選ぶ。全てを新しいIRへ移植してから最初の機能を作る順序にはしない。

最初のregionは、straight-lineの小さい部分に限定する。目安は算術2〜8演算、live-in 4程度、live-out 1〜2。実際のtraceで調整してよいが、上限は検査し、超過時は普通の実行へ戻す。複雑なphi、一般的なloop-carried SSA、例外を跨ぐ大領域の融合は今回の必須範囲ではない。

最低限共有すべき情報：

- 値：Python object / i64 / f64 / native predicate、exact typeと値域、定数・既知のlive-in。
- 参照：owned / borrowed / unique、alias、最後の使用位置。
- 演算：add/sub/mul/compare、選んだbuiltin。元の順序、結果の使用先。
- effect：読み書きする状態、allocation、Pythonへの再入、例外、guard失敗。これらを一つの「pure」に潰さない。
- exit：対応するPython命令境界、元のoperand stack/locals、保持する参照、必要なmaterialization。

同じ原理を使うが、intとfloatのsemanticsは統合しすぎない。intのoverflowはPythonの任意精度演算へ、floatは元の順序とbinary64の丸めを維持する。mutating builtinは算術のpure領域とは別のeffect境界で扱う。

既存の小さいstencil familyや新しい少数の融合形式を使ってよい。式、定数、local slotの順列ごとに手書きの巨大uopを増やすことや、実行時のnode-dispatch interpreterは避ける。guard/exitの対応が複雑なら、最初はより小さい安全な領域に分割する。

## 4. int：range専用kernelの外へ広げる

最初の対象はexact intの加減乗算と比較。bool、int subclass、i64を超える入力はguardで既存経路へ戻す。compact PyLong、exact int、signed-i64に収まることは別々の事実である。

代表例：

    def arithmetic(a, b, c):
        return a * b + c

    def predicate(a, b, c, limit):
        return a * b + c < limit

    def offset(index, width, header):
        return index * width + header

これらを関数名で認識しない。同じuopの依存関係と契約で処理し、入力やlocal配置を変えても使えるようにする。まず一つの式を正しく動かし、二つ目と比較consumerへ広げる。

理想は、入力を一度unboxし、途中の積や和のPyLongを作らず、結果がobjectとして必要になる境界でのみbox化すること。比較のためだけに使われる和なら、和のbox自体を不要にできる。

各演算はPython順序でchecked arithmeticとする。積が成功して加算がoverflowしたケースを必ず試す。guard/overflow時に、元の入力を保持したregion入口から安全に普通の演算を実行できる範囲に限定する。既に副作用が起きたcallやstoreの前へ戻って再実行してはいけない。

最初からfloor division、modulo、任意幅shift、負数のビット演算全般、int/float混合を扱わない。定数maskや小さいshiftがprofile上重要なら3日目の候補だが、符号と任意精度のsemanticsを別に検証する。

既存range residentは回帰baselineとして維持する。これを新IRへ全面移植することは必須でない。小さいint領域が通常の関数や複雑なループの一部でも働くことを優先する。

## 5. builtin：call入口だけでなく戻り値のconsumerまで見る

組み込み呼び出しを速くする主な方法は、次の三つ。

1. callable/descriptorとreceiver型を証明して、汎用dispatchや不要な引数処理を省く。
2. 既存C実装へ直接つなぎ、Pythonとして必要なsemanticsを再実装しない。
3. 結果の型・値域・ownershipを後続へ伝え、直後にunboxするだけの戻り値やguardを省く。

全てのbuiltinを列挙するregistryを先に作らない。最初の二familyに必要な小さいsemantics記述を作る。それにはcallable identity、receiver guard、argc/kwargsの制約、結果表現、effect、error/fallbackを含める。実装は直接loweringしてよく、汎用plugin APIは不要。

### 5.1 必須候補A：len + consumer

初期対象はexact str/bytes/tuple。exact list/dictは、mutable stateの読み取りとして正しく扱える場合に拡張する。

    def long_enough(text, minimum):
        return len(text) >= minimum

    def remaining(text, position):
        return len(text) - position

builtinの`len`自体のidentityをguardし、global/builtinsの差し替えとユーザー定義`__len__`を誤って最適化しない。既存`CALL_LEN`を再発明せず、exact receiverの長さ取得と、必要なら直後の整数演算/比較へ接続する。

目標は`PyObject_Length`の汎用dispatchや、直後に分解するPyLong結果を不要にすること。小さい長さはキャッシュ済み整数なので、全件でheap allocationが一つ減るとは説明しない。実際のallocationと、削減したbox表現・refcount・dispatchを分けて計測する。

list/dictの長さは不変とは限らない。Python call、mutation、pending callback、その他のeffectを跨いでhoist/CSEしない。exact receiverでも最後の参照をcloseする処理は別のeffectとして保持する。

### 5.2 必須候補B：str.startswith / endswith

まずexact str receiver、exact strの単一prefix/suffix、既定のstart/endに限定する。型・descriptor identity・引数形をguardし、tuple prefix、subclass、独自`__index__`、未対応のkwargs等は元のcallへ戻す。receiverだけがstrという観測では不十分。

既存Unicode比較helperを使う。UTF-8/PEP 393、SIMD、新しい文字列検索アルゴリズムをこのタスクで再実装しない。返り値を条件分岐が直ちに消費する場合はnative predicateでつなげる。

    def has_prefix(text, prefix):
        return text.startswith(prefix)

    def classify(text, prefix):
        if text.startswith(prefix):
            return len(text)
        return 0

boolはもともとsingletonである。これを「bool allocation削除」と数えない。主な狙いはcall/Argument Clinic wrapperの処理、stack/referenceの受け渡し、戻り値に対する再チェックの削減である。

文字列処理自体が長い入力ではC本体の走査時間が支配的になる。短い文字列と長い文字列を分けて測り、call境界での改善を全入力へ外挿しない。

### 5.3 profileに応じた3日目の候補：dict.get

`mapping.get(key, default)`が実workloadで支配的なら、exact dictと特定のkey型・呼び出し形に限定した直接経路を検討する。defaultは呼び出し前に評価済みという順序を維持し、missingとerror、戻り値のidentity、owned referenceを正しく扱う。

重要：exact dict + exact strの検索キーだけでは「Python callbackなし」の証明にならない。dict内の他のキーやgeneral-key layoutでは比較がユーザーコードへ入ることがある。既存の安全なlookup helperとeffect情報を使うか、unicode-only layoutまで証明する。dictを跨いだ無効なキャッシュや、再入中のborrowed refを作らない。

これは長さ/文字列familyが成立した後の拡張候補である。高頻度だと仮定せず、選んだworkloadのcall数とCPU割合で決める。

### 5.4 今回の低優先度

`list.append`、`isinstance`、method-descriptor直接callは既存実装をまず調べる。既に速いcallを別名のuopで置き換えるだけでは成果としない。append後のNoneは既にsingletonであり、appendのmutationやallocation失敗を消せない。

`str.split/replace`、大きい`str.find`、正規表現、sortなどのC本体全体をJIT化するのは今回の範囲外。必要なら後で、短い呼び出しのwrapper費用、結果型伝播、consumerとの統合をprofileに基づいて選ぶ。

## 6. 2〜3日間の進め方

時刻は工程配分の目安であり、完成の保証や無制限な自動実行の許可ではない。途中で得た証拠に基づき配分を変更し、Decision Logへ理由を残す。

### Day 1前半：実行環境と基準を固定する

- 起動時のHEAD/dirty state、compiler、LLVM、CPU、利用可能なaffinityを記録する。
- 完全なLLVM prefixを一度用意する。既存の検査scriptを使い、clangだけで完了としない。過去のCloud専用repo workaroundをLinux boxへ盲目的に適用しない。
- release/native、debug Tier-2、必要なdebug nativeまたはsanitizer用buildを別directoryに置く。
- baseline用sourceと開発用sourceを独立させる。同じsource中の生成ファイルを並列で書き換えない。独立cloneでもよく、git worktreeを必須にしない。
- 現在のfloat/intの機能テストを実行し、実際に動くbaselineを確定する。意味論修正が必要なら先に修正し、その修正は全比較群へ共通して入れる。
- 8〜12のworkloadを最適化前に固定する。nbodyだけでなく整数演算、文字列/parse、dict/object、template等と回帰controlを含める。実際に利用できるsuiteの名前とversionを確認する。
- CPUサンプリングとuop/call診断で、top候補と既存特殊化をinventoryにする。単なるcall回数ではなく、削減可能なCPU時間とguard失敗率で順位を付ける。

この工程で環境構築だけを最終成果にしない。実native buildに問題がある場合は原因を保存し、独立して実装/debug検証を続けるが、最終成果をnative検証済みと偽らない。

### Day 1後半：共通契約とint領域を一本通す

- latest shared-float経路のownership、guard/error target、入力stack復元、実行counterを点検する。
- 必要なvalue/effect/exit情報だけを既存解析へ追加する。
- range外のint multiply-addまたはadd/sub chainを実装し、続いてcompare consumerを扱う。
- float/intのreference oracleと、実際のoptimized-path entryを別々に確認する。
- operandsのunique/borrowed情報と、元の例外・副作用境界を壊さないことを自己レビューする。

共通基盤を完成させるまでfeatureを作らない、という順序にしない。最初のint経路を実際に動かすことで設計を絞る。

### Day 2前半：lenと組み込みメソッドを接続する

- len→comparison/arithmeticを実装する。
- profileを再確認し、startswith/endswithまたはより有効な一種類のメソッドを実装する。
- callable identity、descriptor、exact receiver、argument shape、effectの検証を共通化する。
- callの結果を既存int/predicate領域へつなげる。個別callが速いだけでなく、少なくとも一つの合成ではない実処理または代表的なparseループで一緒に働くことを確認する。
- 対応メソッド数だけを増やすために全てのbuiltinを実装しない。

### Day 2後半：統合・ablation・利益判定

- 全機能ONとbaselineを比較し、float/int/builtin各群を単独で変えたablationを行う。
- 実workloadでその処理を通ったことをcounterで示す。遅くなった経路は、guard・deopt・allocation・code size・compile costのどれが原因か調べる。
- 正しさの反例を優先修正し、効果のない経路は無効化または削除する。
- cold/warm/steady-stateと短いスクリプトの回帰を分ける。
- ここで2日版の成果をまとめられる。必須機能に穴があれば成功扱いにせず、残項目を明示する。

### Day 3：適用率が伸びる一手＋仕上げ

まず、既に実装した領域が「型は合うのに入らない」「callの結果ですぐboxへ戻る」「短いtrace境界で切れる」箇所をprofileから選び、最小の一般化で解消する。

候補はdict.get、lenの追加receiver、int比較からbranchへの接続、既存の型guard/cleanupで切れた安全な領域の連結。この日を新しい巨大backendの開始やopcode増殖に使わない。

最終時間は全体テスト、独立review、native assembly、計測の再実行、結果と残課題の整理に確保する。十分な利益がある変更を安定化する方が、未検証の三つ目のfeatureを追加するより優先。

## 7. 共通する正しさの条件

- Python object identity、alias、borrowed referenceの生存期間を維持する。複数live-outが同じvirtual objectを指す場合は一度のmaterializationを共有する。まず一live-outへ絞ってよい。
- int subclass/bool/ユーザー定義演算/descriptor差し替え等は、適切な入口guardで元の順序へ戻る。
- overflowした演算の途中へ、必要なoperandがないstackでjumpしない。既にcommitしたstore/call/iterationを再実行しない。
- floatはPython順序とbinary64丸めを維持する。現在のvolatile helperを正しさのbaselineとしてよい。FMAや再結合を許すpragma試行を主作業にしない。最適化するなら使用compiler・stencilの実assemblyと打ち消し例で証明する。
- arbitrary calls、mutations、observable decrefs、monitoring/periodic checkを、理由なく領域内へ移動・削除しない。
- exact receiverのC builtinでも、call本体のeffectとoperand closeのeffectは別に検証する。
- bool/None/small-intはsingleton/cacheがある。実際に存在しなかったallocationを「削除した」と報告しない。
- 既存のsignal/pending処理の応答性を落として速度を稼がない。free-threadedは今回の必須対応外でよいが、明示的に無効化/skipし、対応したと主張しない。
- allocation失敗時は、選んだPython境界のhandler、locals、operand stackが整合する必要がある。全ての省略allocationの発生時刻を再現する必要はないが、単にエラーをclearして成功にしない。

## 8. テスト計画

機能テストは結果と経路の両方を確認する。融合命令を一度生成しただけでは、そのedge caseを実行した証明にならない。各対象入力のbefore/after counter、既存の直接executorテスト、または実行記録を使う。診断の書き込みはrelease timingから外す。

### int

i64の両端、積だけoverflow、和だけoverflow、負数、零、同一operand、非compactだがi64内、i64外、bool/subclass、alias、guard失敗後の再entryを検証する。任意精度の独立実装と固定seedで数百〜数千件比較する。一件ごとにprocessを起動しない。

### float

加減算の順序、キャンセルによるFMA検出、signed zero、NaN、infinity、subnormal、underflow/overflow、共有accumulator、unique accumulator、同一input、subclass callback列を確認する。有限値は必要に応じbit比較、NaNは適切な分類で比較する。新shared経路のallocation failureとin-frame handlerは、既存のprivate test機構で対象箇所を実行する。

### builtin

lenの差し替え、`__len__`、receiver subclass、method override、対応/非対応argc・kwargs、空文字列・空prefix・Unicode各kind、戻り値のidentity、call前のargument評価順序、mutable receiver変更、hash/equality callbackを検証する。

### 検出力

新しい最適化だけを一時的に無効にしてpositive-path assertionが落ちることを確認する。故意に間違った算術/結果を返す一時mutationで数値テストが落ちることも確認する。これらのmutationはcommitしない。

ケース生成の回帰、stackref/refcount、generator/call/monitoring、既存integer-familyのテストも実行する。最初はfocused、最後に関連suite全体を回す。過去の無関係な失敗は原ログを残して区別し、skipを追加して隠さない。

## 9. build・regeneration・計測

最初にAGENTS.mdとその時点のMakefileを確認する。以下は現在のtreeの例であり、成功した正確なコマンドを記録する。

    Tools/jit/ensure_llvm21.sh
    python3 Tools/cases_generator/optimizer_generator.py
    python3 Tools/cases_generator/tier2_generator.py
    python3 Tools/cases_generator/uop_id_generator.py
    python3 Tools/cases_generator/uop_metadata_generator.py

Tier 1 semanticsを変更した場合はtier1_generator等の対応する出力も再生成する。`tier2_generator.py`だけでは`optimizer_cases.c.h`を再生成しない。適切な`make regen-cases` / `regen-optimizer-cases`等を使ってもよい。再生成の二回目で差分が出ないことを確認する。

build directoryの例：

    build-tier2-debug/   --with-pydebug --enable-experimental-jit=interpreter
    build-jit/          --enable-experimental-jit=yes
    build-jit-debug/    --with-pydebug --enable-experimental-jit=yes（対応時）

native stencilのLLVM versionと有効なflagsを記録する。既存vectorization workaroundは必要な場合だけ使い、全comparison群へ同じものを適用する。`.jit-stamp`を触って古いstencilを使用しない。

focused testの例：

    build-tier2-debug/python -m test test_tier3 test_capi.test_opt -v
    build-jit/python -m test test_tier3 test_capi.test_opt -v

これに選択builtin、追加region、generator、既存toolのテストを加える。全てを一回の巨大コマンドにせず、失敗位置が分かる単位でログを残す。

測定条件：

- 同じCPU/affinity、同じcompiler・flags、source/build identityを揃える。baselineとtreatmentを交互またはランダム順で測る。
- タイミング中は同じCPU上でビルド/別benchmarkを実行しない。baselineとtreatmentを並列に測定しない。
- setup、first compile、warmup、steady-stateを区別する。same-input warmupを基本とし、小さいintによる隠れた事前学習を行わない。
- pyperfはworker環境を選別する。必要なJIT/実験設定だけを`--inherit-environ`へ明示し、worker内でmode/executable/JIT状態を確認する。秘密情報を含む全環境をコピーしない。
- sampling/diagnostic counterとtimingを分ける。既存pystats/perfを優先し、計測目的だけの汎用frameworkを作らない。
- 新しいfloat/int/builtin群をそれぞれ切り替えられるようにする。runtime hot loopで毎回設定を読むのではなく、設定は適切な開始/compile時点に読む。
- 基本comparisonはbaseline、floatのみ、intのみ、builtinのみ、全て。履歴にある危険な古いruntimeへ戻してbaselineにしない。
- 数値は固定した8〜12workloadの個別結果・geomean・最大回帰を出す。改善したものだけを後から選んでgeomeanを作らない。
- native codeが存在することと、対象領域が実行されたことは別に証明する。
- `objdump -d python`だけでなく、選択executorの`get_jit_code()`を取得し、実際の融合領域を逆アセンブルする。

必須の性能合格条件は、有意な回帰を隠さないこと、profile上の仕事が減ったこと、少なくとも非合成workloadで効果のある変更を識別できること。計画上は対象workloadで5〜15%程度以上、対象算術/call microbenchmarkで1.5倍以上を探索目標とするが、これは予測でも虚偽の成功を許すthresholdでもない。少ない利益でも保守性がよければ採用できる。効果がない大きい変更はgate/revertし、理由を残す。

## 10. 2〜3日後のdeliverables

1. 安全に比較できるローカルbaselineと、機能別にreviewできるcommit列。
2. int領域、floatの検証、len＋選んだ組み込みメソッドの実装とテスト。
3. 実workload上の該当経路の実行証拠とablation。
4. 一つの結果表、build manifest、主要assembly、成功/失敗ログへのローカルpath。
5. 性能・適用率・complexityから、採用する変更、実験のまま残す変更、捨てる変更の区別。
6. 次に3倍へ近づくためのtop bottleneck三つ。backend変更の主張は、具体的に生成できなかったコードやspill/copy制約を示す場合だけ行う。

大きなrawログや多数の古いassemblyをさらにsourceへ積み上げない。`jit-artifacts/<run-id>/`などのローカルartifact directoryに保存し、repositoryへ残すのは再現script、要約、必要なsmall fixtureを優先する。既存の歴史を勝手に削除する作業は不要。

## 11. CLIでの継続運用

この計画はユーザー指定の`plan.md`としてcheckout内に保存する。AGENTS.mdには、既存のCPython AIポリシーを維持したうえで、durableなbuild/testルールとこの計画を読む指示だけを短く置く。詳細な実験履歴を全てAGENTS.mdへ貼らない。

以下の四sectionを、実装と同時に更新する。

- Progress：完成/途中/未着手、検証したcommit、次の具体的command。
- Surprises & Discoveries：実trace、反例、性能の予想違い、適用されなかった理由。
- Decision Log：設計を選んだ理由、却下した代案、変更したscope。
- Outcomes & Retrospective：達成した効果、残る制約、gate/revertした内容。

sessionが切れたら、最後の会話だけではなくこの文書とHEAD・ログから再開する。`codex resume`で既存sessionを選べる。複数sessionを使う場合は対象sessionを明示し、別作業の「last」を誤って続けない。

agentを分ける場合、調査・テスト設計・read-only reviewは並行してよい。`bytecodes.c`、optimizer、生成ファイルへ同時に書くagentは一つにする。別実装を並行させるなら独立cloneとownershipを決め、主担当が統合する。性能測定は一つずつ行う。

普通の修正・失敗で毎回人間へ「次の指示」を要求しない。ただし実行権限不足、予算/利用枠、repository外への破壊的操作など、本当の境界では止める。終了/中断時は単に「done」ではなく、次回に必要なHEAD、build、failed command、進捗、次の一手を残す。

### 最初にCodexへ渡す指示

    JIT_PLAN.mdとAGENTS.mdを読み、Linux上でこの2〜3日間の実装計画を進めてください。
    計画の説明だけで終わらず、既存Tier 2上のfloat検証、rangeに限定しないint領域、
    lenと少なくとも一つの組み込みメソッドの最適化を、機能ごとのcommitで実装・検証してください。
    小さい中間工程が終わっても、未完了のmilestoneへ続けてください。
    profileで優先順位を調整してよいですが、理由と実行証拠を計画へ残してください。
    初回はnative baselineを確認し、依存関係・正しさ・計測を揃えてから改善を比較してください。
    GitHubへの投稿・push・PR変更は禁止です。既存のローカル変更を破棄しないでください。
    各milestoneと中断時にProgress / Surprises & Discoveries / Decision Log /
    Outcomes & Retrospectiveを更新し、次のsessionがこの文書だけから再開できるようにしてください。

## 12. 進捗記入欄

### Progress

- 着手記録（2026-09-13）：HEAD `2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127`、tree `5311e52667cb7ae929ea907bdf34647caf7b62bc`。開始時 tracked clean、未追跡は plan.md / large_functions.md / spectral_norm.py。全て保持。
- 環境：Intel i5-12450H、CPU affinity 0–11、LLVM 21.1.8 `/usr/lib/llvm-21`（4 tools 実行確認、`/usr/bin/*-21` も存在）。PGO/LTO は使わない。
- artifacts：`jit-artifacts/local-regions/`。baseline-src は `git archive HEAD`、dev-src はその独立コピー。元 checkout の既存 configure/build を保持し、変更ファイルを dev-src に同期して別 build directory からビルドした。ユーザーの追加許可により元 checkout を distclean したため、現在の debug/native 開発ビルドは元 checkout を直接参照する。
- 完了時のbuild：`build-tier2-debug/`（元checkout、debug interpreter）、`build-jit/`（元checkout、native release）、`build-baseline-jit/`（immutable baseline-src、native release）。baselineの参照HEADは変更していない。
- [x] M0：実際のHEAD/権限/環境を確認し、比較可能なbaselineを確定した。
- [x] M1：既存最適化と8〜12workloadのprofile inventoryを保存した。
- M2/M3 初回機能検証：`test_capi.test_opt_regions` 9 tests 全成功（debug Tier 2）。9種類の二演算式×100件、全6比較、非compact i64、overflowとsubclass、len/Unicode/method override、float bit比較、実行counter、3 family の in-frame allocation error を確認。`test_tier3 test_capi.test_opt` は328 tests・3 skipsで成功。
- [x] M2：floatを検証し、rangeに限定しないint領域・consumerを実装した。
- [x] M3：len＋少なくとも一種類の組み込みメソッドを実装した。
- [x] M4：正しさ、実行counter、ablation、native assemblyを確認した。
- [x] M5：利益/回帰に基づいて採用・gate・削除を決め、結果をまとめた。

### Surprises & Discoveries

- native baseline は328 tests・3 skips、native treatment は追加11 testsを含め339 tests・5 skipsで成功（`test-baseline-native.log`, `test-regions-and-existing-native.log`）。debug専用のallocation failureはdebugで別途確認。
- native 生成は既存 Python 3.13 の asyncio subprocess 待機で停止する。完成済み `build-tier2-debug/python` を `PYTHON_FOR_REGEN` に指定すると進む。LLVM 21 の `.LCPI0_0` エラーを両buildで再現したため `CFLAGS_JIT="-fno-vectorize -fno-slp-vectorize"` をconfigure時に指定して再生成・成功した。PGO/LTOなし、GCC 13.3、frame pointerあり。
- 全実験ONで既存range affine matcherがint融合に遮られたため、range modeを明示したrange traceでは先行int融合を抑止。既存range14 testsをint ONのまま再実行し成功。
- 全実験ONの旧opcode形状テストには5 failuresが残る（2 float・3 int）。期待する旧in-place opcodeが正しく融合opcodeへ置き換わるため。既存テストは変更/skipせず、既定設定で全て通ることと新融合テスト、全実験ONの意味論suiteを別に検証する。元ログ `test-all-enabled-debug.log` を保持。
- finalizerがframe.f_localsを書き換えるテストは、frame公開によって融合命令より手前でdeoptし、融合命令生成だけでは実行証拠にならなかった。ownedな新規文字列で同じ所有権guardのcounter増加を検証し、finalizerの順序は別oracleとして検証する。
- 関連suiteの初回実行では存在しない `test_tools.test_cases_generator` を指定してしまった（正しくは `test_generated_cases`）。同一debug buildを複数toolから同時にtestするとPID namespaceのPIDが一致しtempdir警告も出るため、以後は異なる `--tempdir` を指定する。

- 初回 out-of-tree make は `check-clean-src` で停止した。元 checkout の既存ビルドを消さず、独立ソースへ切り替える。失敗ログは `build-debug.log` / `build-native.log`。
- 既存 int guard は exact + compact を要求する。単純に guard を消すと後続の abstract type/compact 仮定を壊すため、int の拡張は abstract optimization より前で契約を確立する必要がある。
- float は opcode 生成と値の確認が既存テストにあるが、edge input ごとの実行証拠は不足している。

### Decision Log

- 測定 panel は `Tools/jit/region_bench.py` の10項目（int_chain/int_predicate/offset_checksum/float_shared/float_unique/parse_headers/parse_unicode/dict_control/json_control/template_control）。初回実装後・性能観測前の固定なので、事前固定holdoutとは主張しない。標準ライブラリと代表的header parseを使う独立panelで、pyperformance suiteとは区別する。n=65536、同一入力warmup=5、samples=9、5 modesの順序を回した独立processを3 blocks、CPU 2固定を予定。raw値は全て保持し、各process平均時間比のgeomeanと最大回帰を報告する。
- int/len はabstract interpretation前にlowering、methodは既存constant descriptor解析を利用。全てenvによるcompile時opt-inを維持し、free-threadedとchecked arithmetic非対応compilerは無効。

- 作業決定：int は straight-line 二演算＋任意の比較 consumer から始め、最初の Python 演算境界へ戻れる入力と local load に限定する。一般 CFG/実行時 node interpreter は追加しない。
- 初期決定：既存Tier 2/copy-and-patchを維持する。arith/len/methodをつなぐ小さい共通契約を作り、別backendを先に作らない。
- 初期決定：GitHubではなくローカル実装。検証結果はこのLinux boxを基準とし、過去のCloud timingを新しい変更の成果にしない。
- 初期決定：一般3倍は長期目標。今回は適用範囲の拡大と、実workloadへの効果を実装・計測する。

### Outcomes & Retrospective

- 実装済み・debug/native機能検証済み：int二演算9通り＋6比較、len comparison/add/sub、str.startswith/endswith、float unique/sharedのbit/alias/例外/counter。
- Native coverage：`native-coverage.json` と対応 `.bin/.asm`。float uniqueは別の `mulsd` / `addsd`（非FMA）を確認。int比較の中間/最終PyLong boxingなし、算術live-outは1回box化（small-int cacheではallocationを意味しない）。
- 性能評価・mutation検出力・最終関連suiteは完了。全機能は引き続き明示opt-in。反復memory-block検査には未変更baselineでも再現する既存問題が残る（下記）。

## 13. 出典と確認箇所

この文書は計画であり、ここに記した性能目標は新しい実測値ではない。参照HEADに関する事実は以下のソースを確認した。実装時はローカルcheckoutを正とする。

- PR metadata: https://github.com/methane/cpython/pull/128
- Latest shared-float change: https://github.com/methane/cpython/commit/2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127
- Runtime uops / builtin specializations: https://github.com/methane/cpython/blob/2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127/Python/bytecodes.c
- Abstract optimizer / method call lowering: https://github.com/methane/cpython/blob/2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127/Python/optimizer_bytecodes.c
- Float region matching: https://github.com/methane/cpython/blob/2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127/Python/optimizer_analysis.c
- Python call protocol: https://docs.python.org/3/c-api/call.html
- Unicode C helpers: https://docs.python.org/3/c-api/unicode.html
- Codex CLI: https://developers.openai.com/codex/cli/features
- AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Living execution plans: https://developers.openai.com/cookbook/articles/codex_exec_plans


## 14. ローカル実装・検証の最終記録（2026-09-13）

実装commit：`f9d6ff707beaffc13ddb5b27bfcec8dce24bb7b9`。int/builtinと共通counter・float検証を、一緒にビルド可能な単位として保存した。文書/benchmarkは別commitに分ける。native binaryはこの実装内容をcommit前にビルドして測定したため、sys.versionのHEADは元のdirty表記を保持する。`build-manifest.json`に実装tree、source/binary/拡張/stencilのSHA256と有効flagsを記録した。

### Progress

- 必須機能を実装し、debug Tier 2 と native copy-and-patch で実行確認した。int は9種類の二演算と6比較、最大4 live-ins / 1 live-out。range全体だけでなく、通常関数をinlineしたtraceと異なるlocal配置でも同じ経路が動く。
- `len` comparison/add/sub と `str.startswith/endswith` を実装。parserでは同じtraceで両方のcounterが増える。effectを跨ぐcase、owned receiver、ユーザーcallback、callable/descriptor identityを検査した。
- 最初のint実装にはruntimeの演算選択分岐が残り、boxed chainで約6%遅かった。既存 `replicate(9)` で二演算をstencil時に固定し、回帰をほぼ解消した。手書きの式/local別実装は追加していない。旧結果は `measurement-initial.log` に保持。
- Native機能テストの最終結果は `test-native-final.log`。追加13 tests、既存 test_capi.test_opt / test_tier3 を含む341 tests・5 skipsで成功。debugの13 testsも成功。全実験ONの関連14 suitesは1,191 tests・19 skipsで成功（`test-related-debug-final.log`）。generator/range/regionの追加実行は124 tests成功（追加2 testsの前）。
- 再生成のidempotence確認に成功（`regeneration-idempotence.log`）。`git diff --check`、PythonのF401/F811 lintも成功。利用可能なRuff 0.14ではtest設定のpy315を読めないため、同じ選択rulesをisolated modeで実行した。Black/prekはなく、PyPIへのDNS失敗で追加できなかった。全pre-commit hooks完走とは主張しない。
- 一時的に最適化をOFFにしたnegative checkは全4 familyのpositive-path assertionを失敗させた（26 failures）。checked addをsubtractへ一時変更したnumeric mutationも11 failuresで検出した。変異は復元済み、復元後のテストも成功（`mutation-disable.log`, `mutation-numeric.log`, `test-after-mutation-debug.log`）。

### 比較結果

すべて同じGCC 13.3、LLVM 21.1.8、PGO/LTOなし、frame pointerあり。
CPU 2（P-core、SMT sibling 3）、powersave governorのまま、システム設定変更なし。
10項目を性能観測前に固定した探索panelであり、pyperformance suiteやholdoutではない。
同一native binary内の全機能OFFをbaselineとし、各family単独・全ON・archive baselineを3 blocksで順序を回して測定。
各processでn=65536、same-input warmup=5、9 samples。全値を保持し、process平均の対応比を幾何平均した。
表は **treatment / baselineの時間比（小さいほど速い）**。

| Workload | floatのみ | intのみ | builtinのみ | 全ON | 全ONの3 process比の範囲 |
|---|---:|---:|---:|---:|---:|
| int_chain | 1.010 | 0.999 | 1.009 | 0.997 | 0.982–1.012 |
| int_predicate | 1.003 | 0.647 | 1.000 | 0.645 | 0.640–0.651 |
| offset_checksum | 0.993 | 0.993 | 1.000 | 1.000 | 0.981–1.016 |
| float_shared | 1.008 | 0.990 | 1.002 | 1.007 | 0.993–1.015 |
| float_unique | 0.751 | 1.023 | 1.084 | 0.757 | 0.755–0.759 |
| parse_headers | 0.999 | 0.995 | 0.713 | 0.717 | 0.710–0.722 |
| parse_unicode | 0.907 | 0.906 | 0.668 | 0.673 | 0.543–0.750 |
| dict_control | 1.007 | 0.980 | 1.011 | 1.021 | 0.993–1.045 |
| json_control | 0.995 | 1.022 | 1.004 | 1.007 | 0.999–1.023 |
| template_control | 1.002 | 1.000 | 0.997 | 1.001 | 0.999–1.002 |
| **10項目 geomean** | **0.964** | **0.948** | **0.938** | **0.868** | — |

- 主解析は全体で約13.2%短縮。最大の平均回帰はdict_controlの約2.1%（process比0.993–1.045）。回帰を除外して平均を作っていない。
- parse_unicodeのbaseline block 1は、最初の5 samplesが約2.81 ms、後半が約1.75 msという遷移を示した。原因は未特定で、全値を残した。従ってこの項目の33%短縮を一律の改善とは解釈しない。独立perf測定のcycle比は0.752で、他の2 timing blocksも約0.75だった。固定した1組のbuild・3 processesでの探索結果であり、別build/別CPUへの一般化は未検証。
- 空process起動（taskset/Python起動の合計、各mode 9回）はbaseline 9.856 ms、全ON 9.843 ms、archive 9.821 ms。first call / warmupは各JSONに保存した。first callにはn回の処理も入るため、純粋なcompile latencyとは呼ばない。template first callは全ONで約3.5%増、warmup約3.8%増という小さい回帰を保持。
- 短いprefixと8192文字のprefixは独立診断で測定した（panel平均には追加しない）。methodのみの時間比はshort 0.916、long 0.929。parserでの28%改善はlen consumerも併用した結果であり、単独startswithや全文字列処理へ外挿しない。

### Native / CPUの証拠

- `panel-final-0-all-*.bin/.asm` は実executorの `get_jit_code()`。整数のmultiply/add本体は、int_chainの0x3a8の `imul`、0x3acのoverflow branch、0x3aeの `add`、0x3b1のoverflow branch。演算選択のdispatchは消えている。PyLongの符号unboxにもimulがあるため、全imul数を演算数と混同しない。
- float_uniqueの0x2d1の `mulsd`、volatileのstore/load、0x2e1の `addsd` を確認。キャンセルwitness、signed zero、NaN、inf、subnormal/underflow/overflowのbit/classificationテストを同じnative経路で実行した。data/GOT領域をobjdumpが命令として表示する部分は評価対象外。
- rawコードの間接呼び出しは、生成stencilのrelocation注釈と対応付けた。intの非compact側は `PyLong_AsLongLongAndOverflow`、boxed live-outは `PyLong_FromLongLong`。methodは `PyUnicode_Tailmatch` へ直接つながる。
- 各sampleのcounter deltaをJSONに保持。成功テストではentry増加に加えてguard/overflow/error delta=0をassert。int compareのint_boxes=0。header parserではmethodとlenが同一executorで共に動く。get_jit_codeの確保サイズは各trace 4096 bytes（page padding込み）。mul/addのstencil本体585 bytes、compare版685 bytes、len consumer468 bytes。実行ファイルのtextは6,260,326→6,291,774 bytes（+31,448）、dataは+4,256 bytes。executor counter storageは+96 bytes。
- perf statは同一入力200 calls＋5 warmups＋setupを含む独立診断、2 repetitionsをAB/BA順。CPU coreの4 eventsをgroup化、全て100% running。命令数比はint_chain 0.950、int_predicate 0.696、float_shared 0.985、float_unique 0.803、parse_headers 0.718、parse_unicode 0.739、dict_control 0.998。header parserはbranch-missesが約17.6%増えたが、cyclesは0.724まで減った。
- samplingはbaseline 16,001 samples、全ON 15,095 samples、lost=0。baselineの `_PyCallMethodDescriptorFast_StackRef` はself 2.78%で、全ONでは0.5%表示閾値未満となった。割合だけを絶対CPU量と混同せず、上の命令数/cycle比と併せて判断する。

### 残る問題と採用判断

- **利益を確認**：checked intの比較consumer、len＋methodを組み合わせたparser、既存float unique融合。いずれもopt-inとして保持し、デフォルト有効化は行わない。
- **実験のまま保持**：boxed int chain/offsetと既存float shared融合。実行・正しさは確認したが、このpanelでは安定した速度利益は示していない。baseline int chainは既にADD_INT_INPLACEでproduct boxを再利用し、float sharedも既に一つのallocationで済むため、allocationが必ず減るとは説明しない。
- len比較ではPyLong表現を作らない。測定入力のlenはsmall-int cache外なのでallocationもなくなる。len arithmeticのbaseline traceは `_CALL_LEN`＋`_BINARY_OP_SUBTRACT_INT`（in-placeではない）で、融合はlenの中間boxを省いて最終結果だけbox化する。小さい長さはcache利用なので一般的なallocation削減率にはしない。
- 反復 `-R 3:3` は数値/経路テストを6回全て成功させたが、module全体で約61–62 memory blocks/iteration増加のため未合格。新規functionごとに約1 block増える同じ現象を、**未変更archive native / treatment OFF / treatment ON** の全てで完全一致して再現した（100 functions×6 batchesの累積差はいずれも101,205,307,409,511,613）。PYTHON_JIT=0では1,5,7,9,11,13。新規最適化固有の増加は検出していないが、既存JITの問題として未解決。`refleak-*.log`, `block-growth-*.log` を保持し、skipして隠していない。
- 旧opcode形状に固定した5 testsは、全実験ON時に期待opcodeが融合されるため不一致（以前のfloatだけでも2件）。元テストは変更せず、既定設定での成功と全ONの別の機能・経路テストを提示する。全実験ONの旧形状suiteが全成功したとは主張しない。
- free-threaded、32-bit、他compiler/architecture、ASan、full pyperformance、独立した人間reviewは未検証。引き続き公開/push/PR変更は一切していない。

### 次の作業

1. 既存JITの新規function当たり1 memory block増加を、`check-block-growth.py` とarchive baselineから調べる。今回のfeatureとは切り分けて最小再現を維持する。
2. 利益の薄いboxed算術では、int live-outのallocationと非compact conversion周辺のspillを削減する。nativeには3つのconversion slow pathと56-byte stack frameが見える。比較は先に十分速くなっており、別backendへ移行する根拠はまだない。
3. 全ON CPU sample上の残る大きい処理は、templateの `build_string`（13.09%）、allocation/freeとPyLong生成（`_PyObject_Malloc` 5.10%、`_PyObject_Free` 2.59%、`_PyLong_FromMedium` 2.94%）、dict/string lookup/hash（`unicodekeys_lookup_unicode` 3.31%ほか）。この順で、実program上の適用率とwrapper以外の費用を確認する。字面だけでdict.getを追加しない。

再実行：

```sh
# 既定設定の回帰と追加機能
build-jit/python -m test test_capi.test_opt_regions test_capi.test_opt test_tier3 -v
# ONの関連suite（別toolから同じbuildのtestsを並行しない）
PYTHON_TIER2_INT_REGIONS=1 PYTHON_TIER2_BUILTIN_REGIONS=1 PYTHON_TIER2_FLOAT_FUSION=1 \
  build-tier2-debug/python -m test test_long test_int test_float test_str test_bytes \
  test_tuple test_list test_dict test_generators test_monitoring test_capi.test_eval \
  test_capi.test_mem test_generated_cases test_tools.test_ensure_llvm21 -j4
# 固定panelを順序を回して再測定する。既存出力を保持する場合はprefixを変更する。
python3 jit-artifacts/local-regions/measure-final.py
```

主要artifactは `jit-artifacts/local-regions/`。`build-manifest.json`、`summary-final.json`、
`measurement-order-final.json`、`panel-final-*.json`、実assembly、`perf-*.stat`、
`sampling-*.txt/.data` と成功/失敗logを保存した。大きいartifactとsource snapshotはcommit対象にしない。

## 15. 継続目標：spectral_norm.py を main の半分の時間へ

前段のM0–M5完了は、この目標の達成を意味しない。前turnはint/builtin実装と
検証結果を保存した進捗であり、spectral_normの最終比較は未実施だった。

### Progress / 比較条件

- 開始HEAD `d4b913f159d`、tracked clean。対象のユーザー所有
  `spectral_norm.py` は変更しない。676,000回のeval_Aとchecksumを維持する。
- 比較基準はローカル `main` の `a60343ed17785ebbcd43de9080cadd8e2541db6f`。
  以前の `build-baseline-jit` は別の実験HEADであり、mainの代わりにしない。
  mainをarchiveし `build-main-jit` に同じGCC/FP/LLVM21/native JIT、PGO/LTOなしで
  ビルドする。remote取得・push・PR操作は行わない。
- 主判定は同一CPU 2、同じscript/入力/3 warmups/10 values、独立processを
  6 blocksで交互測定したprocess平均時間比のgeomeanが0.5以下。
  両方のJIT ONを主比較とし、JIT OFFとprocess全体時間も補助的に保存する。
  全samplesを保持し、除外やビルド中の測定で達成判定しない。
- artifactは `jit-artifacts/spectral-goal/`。現行版の初回screenは約33.8 ms。
  これはmain比や最終結果ではない。

### 発見 / 設計判断 / 次の作業

- 実executorではeval_Aがinlineされるが、既存int/float/builtin regionの
  counterは全て0。式木と定数を含む整数式は現在の二演算matcherの対象外。
  `// 2` は汎用 `_BINARY_OP`、最後のfloat/int除算はhelper呼び出しである。
- まずmain実測と現在のCPU profileを保存し、整数除算・中間box・型変換の
  費用を確認する。一般の算術へ適用できる変更から進め、関数名やchecksumに
  依存する専用置換、Pythonの演算順序の変更は行わない。

### Bounded expression の実装（継続中）

- main初回screenも約33.7 ms。現行版とほぼ同速で、半減は未達。
  CPU profileは `_PyCompactLong_Add` 14.36%、Multiply 7.54%、
  float/int除算helper 6.32%、generic floor divide関連5%以上。
- `PYTHON_TIER2_BOUNDED_INT_REGIONS=1` を追加。最大8演算・4追加locals・
  native stack深さ4・scan128 uopsの式木を、既存tagged整数stack/cacheと
  copy-and-patchの小さいuopへloweringする。演算nodeをruntimeで解釈しない。
- 入力をexact intの±(2**28−1)へ入口でguardし、全中間値がtagged整数の
  範囲に収まることをinterval計算で証明する。証明失敗は通常経路を維持。
  現在のchecked-i64二演算経路も保持する。定数の非ゼロ整数除算を扱い、
  正の2冪は負数のfloorを維持するshiftへloweringする。
- 最初の2 operandはborrowed/immortalに限定。入口guard失敗時は元のstack。
  内部はallocation/exit/callback/periodic check/frame変更なし。唯一のlive-outを
  box化する前に全tagged値をstackから除き、確保失敗は元の最初の算術位置へ
  帰属させる。生成器のescape metadataも検査する。
- debugの4追加testsで式木4種類×境界値/乱数、実counter、範囲外/subclass、
  ゼロ除算、unsafe interval、in-frame MemoryErrorを検証。最初の失敗1件は
  新テストがZeroDivisionErrorの旧メッセージを期待したためで、現行の
  `division by zero` に合わせて再検証した。
- spectralのdebug実traceで7演算全てが同一regionになり、約200万回のentryと
  box、guard exit=0、checksum一致を確認。これは速度達成の証拠ではない。
- 次はnative測定、残るfloat/int除算・frame費用の調査、必要な追加変更、
  意味論suite、最終main比較。目的は引き続きscript全体の時間比0.5以下。

### Native screen と float consumer

- 整数boxをlive-outにする最初のnative版は、main約33.74 msに対して
  約22.39 ms（時間比0.664）。同一入力の各sampleで675,960 entries、
  guard失敗0、同数boxes、checksum一致。未達なので次へ進めた。
  `bounded-v2.json` / `main-v2.json`、当時のpatch・binary hashを保存。
- この版のprofileはfloat/int除算helperが9.77%、整数box生成・破棄も残った。
  後続がfloat除算のときは入口でborrowed/immortal exact-float numeratorを
  guardし、整数結果を直接consumerへ渡す。±2**53内はexactなC変換、
  それ以上は一時PyLongと既存PyLong_AsDoubleでPythonの丸めを維持する。
- consumerでエラーを起こす前にtagged値を全て消費する。除算の元のSET_IPを
  保持し、ZeroDivisionErrorを正しい命令へ帰属させる。通常function呼び出しや
  returnのframe構築・破棄は変更していない。
- debugの追加7 testsが成功。numeric oracleはoperator APIを使い、同じ最適化を
  oracle側でも実行することを避けた。大きい整数、NaN/inf/±0/subnormal、
  型・所有権guard、実JIT内のゼロ除算とfloat/変換用intのallocation failureを確認。
  最初のゼロ除算テストは初回のTier1反復で例外を起こしていたため、2反復目に
  初めてゼロになる別関数とentry counterを使って経路を検証し直した。
- 次はconsumer版native比較と関連suite。半減はまだ確認できていない。

### 6 blocks の比較と全体時間の追加ゲート

- consumer版screenは18.45 ms / main33.63 ms。入口のlocal重複guardを、
  直前の2つのlocal loadとの対応に基づいて除去し、追加local数をstencilで固定。
  0追加localのspectral traceではguardのruntime loopがなくなった。
- この版を6 blocks・4 modes（main JIT / candidate / candidate OFF /
  main interpreter）でローテーション測定した。`final-*.json` と
  `final-order.json` / `final-summary.json` に全値・counter・hashを保存。
  定常probe比0.4711、元scriptのsample平均比0.4715、全process時間比0.5037。
  元scriptの6 process比は0.5025–0.5049であり、遅い値を捨てていない。
- 主指標は半減を満たしたが、**起動とwarmupも含む元script全体の時間比も
  0.5以下になることを追加ゲート**とした。0.5037を達成とは扱わず継続する。
- この時点のnativeは349 tests・7 skips成功、debugは447 tests・3 skipsに
  新しい4-localの1 testも追加成功。関連13 suitesの1,187 tests・19 skips成功。
  Linux x86の4 rounding modesそれぞれ48 bit comparisonsがdebug/nativeで成功し、
  processの元のrounding modeへ復元した。`rounding-*.json` に保存。
- 次の変更は、最初の算術結果がstackに残り、同じ2 localsを同じ順序・演算で
  再計算する場合の共通部分式除去。借用intのguardとeffect-free区間の証明を
  再利用し、値をtagged integerのまま複製する。加算以外の減算・乗算にも
  同じ仕組みを使う。native再比較は別prefixで保存する。

### 最終結果：目標達成（2026-09-13）

- [x] **変更していないspectral_norm.pyが、mainの半分以下の実行時間になる。**
  定常実行だけでなく、起動・3 warmups・10 values・出力を含む元script全体でも
  6組すべてで時間比0.5未満になった。実験フラグ有効時の、このPC上の結果。
- 実装commit：`9115e6ae0d2f10381472e9f67050f64cc947410c`、tree
  `730a9ff3fdd249c9abefe76d04b5dd4bd74a4fcb`。既存実装は保持し、GitHubへの
  投稿・push・PR変更は行っていない。PGO/LTOは両比較buildとも未使用。
- Source baselineはローカルmain `a60343ed17785ebbcd43de9080cadd8e2541db6f`。
  archiveの6,275 blobsを照合した。145のWindows用text filesは.gitattributes指定の
  CRLF変換だけであり、他の差異はない。対象scriptのSHA256は
  `3e888cd7061073f538d4df509c2d6bdf4c3f7baa4e6b3ad7f9540e0615b8580b`。
- 最終native binaryは実装commit前にビルドして固定した。sys.versionの旧dirty
  表記は保持する。`source-audit.json` と `build-manifest.json` に実装内容との一致、
  commit/tree、binary・読み込んだ拡張・生成stencil・configureのhashを保存。
  `jit_stencils.h` はwrapperなので、実体のtarget別headerもhashに含めた。

次の表は6 processesの算術平均。比の主解析は各blockで対応させたprocess平均比の
geomeanであり、全値を使う。CPU 2（P-core、sibling 3）、powersaveのまま。
システム設定は変更していない。main/candidateともnative JITをONにした比較が主結果。

| mode | 元scriptの定常時間 / operation | 元scriptのprocess全体時間 |
|---|---:|---:|
| main、JIT ON | 33.712 ms | 466.613 ms |
| candidate、bounded region ON | 14.794 ms | 220.534 ms |
| candidate、bounded region OFF | 33.548 ms | 465.477 ms |
| main、JIT OFF（補助比較） | 47.418 ms | 644.277 ms |

- 元scriptの定常比 **0.43884**（6組0.43530–0.44050）、process全体比
  **0.47263**（0.46945–0.47431）。counter付きprobeの定常比も0.43833。
  起動費用はtaskset/process起動とscriptの全処理を含み、純粋なJIT compile latency
  とは区別する。1組のbuild・1台のPCであり、他buildや他CPUへの一般化は未検証。
- `--json`も指定しない通常コマンドを、別の6組でAB/BA測定した。
  process全体比は **0.47191**（0.46827–0.47465）で、こちらも全組で半減。
  通常の標準出力と全測定順を `default-*.txt` / `default-command.json` に保存した。
- `complete-*.json`、`complete-order.json`、`complete-summary.json` が最終結果。
  全24 probe processesと24元script processes、各10 measured valuesを保存した。
  前の約0.5037のprocess比を含む全探索結果も保存し、sample除外は0。
- 各candidate sampleで675,960 bounded entries/divisions、guard failure=0、
  integer boxes=0、allocation errors=0。676,000 evaluations中、99.99%以上が
  この経路で動く。全実行のchecksumは `409.3151805348543` で一致した。
- 別実験のperf statは同じ230 kernel operations（warmup含む）をAB/BAで2反復。
  candidate/mainのcycles比0.43784、instructions比0.47216、branches比0.46019。
  branch-missesは0.9426/1.0847でgeomean1.0112とほぼ横ばい。4 eventsのrunningは
  99%で、時間結果とは混ぜていない。samplingのlostは両方0。
- 実native codeの0x532で最初の加算、0x539でその値の複製、0x567で乗算、
  0x592でfloorを保つshift、0x706でdivsd、0x812で後続のaddsdを確認した。
  0xc88以降などのdataをobjdumpが命令と表示する部分は数えない。
  正負unboxingにもimulがあるため、全imul数をPythonの乗算数とは解釈しない。
  stencilは0追加localのSTARTが222 bytes、DUPが3 bytes、DIVIDEが318 bytes。
  最もhotなexecutorの確保サイズは4,096 bytes（page padding込み）。
- executable textはmain6,256,502 bytes、candidate6,315,702 bytes。この差には
  以前の実験も含まれるので、今回のregion単独の増加とは説明しない。

### 最終検証・制約・次の作業

- native最終版は **349 tests・7 skips成功**（`test-duplicate-native.log`）。
  debugは追加region21 testsとgenerator99 testsの120件成功、bounded ONの
  test_tier3も14件成功。最終版で関連12 suitesを再実行し1,088件・19 skips成功
  （`test-related-complete-debug.log`）。generatorと合わせて関連1,187件を確認。
- 4 rounding modes ×48 casesのbit比較とmode復元はdebug/nativeで成功。
  最後のCSE版nativeでも同じ192 casesを再確認した。
  `git diff --check`、F401/F811 lint、4生成ファイルの再生成idempotenceも成功。
  Black/prek未導入・全hooks未実施、ASan/FT/32-bit/他compiler未検証という
  前段の制約は変えていない。既存JITのmemory-block増加問題も修正範囲外。
- bounded regionは明示opt-inを維持する。53 bitを超えるlive-outをfloatへ変換する
  caseでは一時PyLongを使う。今回のscriptではこのslow pathへ入っていない。
  改善率をfull pyperformanceやすべての整数処理の改善率とはしない。
- この目標に必要な作業は完了。次の性能課題を進めるなら、残ったframe生成・破棄、
  float box、range iteratorのint生成をprofileから調べる。既存のmemory-block増加の
  切り分けも別課題として維持する。今回の達成条件をその追加課題へ拡張しない。

再実行（計測中に他のbuild/testを走らせない）：

```sh
PYTHON_JIT=1 PYTHON_TIER2_BOUNDED_INT_REGIONS=1 build-jit/python spectral_norm.py
# 同じ6 blocksを別prefixへ保存し、元script全体時間も比較する
python3 jit-artifacts/spectral-goal/measure.py repeat
# correctness / counters / fallback
build-jit/python -m test test_capi.test_opt_regions test_capi.test_opt test_tier3 -j4
```

## 16. 継続目標の拡張：benchmarks/ 全スクリプトの時間比の幾何平均を半減

### 対象・権限・現在地

- ローカル `3405a44d68c` で6 scriptsと説明文が追加され、goal管理の現在のobjectiveも
  「benchmarks/ にあるベンチマークスクリプトすべての実行時間をmain比で半減する。」
  へ変わっていた。このcommitは実装9115e6と文書366b5d9の間に追加されている。
  ユーザーの変更を保持し、新しい範囲を継続対象にする。
- Section15のspectral単体の達成は有効だが、全6本の達成とはしない。
  goalの完了呼び出し時に範囲の変更を検出し、誤って広いgoalを完了扱いにした状態を
  即座に同じobjectiveのactive goalへ戻した。今後は完了直前にも最新のgoalを取得し、
  検証した対象と一致することを確認する。
- 対象は `spectral_norm.py`, `bpe_tokeniser.py`, `btree.py`, `deltablue.py`,
  `hexiom.py`, `raytrace.py`。`benchmarks/standalone_benchmarks.md` を読んだ。
  アルゴリズム・入力・仕事量・checksum・検証を変更しない。benchmark側の書換えや
  一部の平均による代用で達成にしない。
- benchmarks内のspectralはrootの同名scriptとSHA256が一致する。新しい5本は未達・
  性能未検証。GitHub操作禁止、LLVM21、PGO/LTOなし、mainの固定revisionとの
  同条件比較を維持する。

### 次の作業

1. `jit-artifacts/benchmark-suite/` に全6本のhash、固定したmain/candidateのbinary
   identity、cold pilotと同一warmupのscreenを保存する。計測は並行させない。
2. 既存機能ON/OFFの実行counterとprofileを取得し、残る5本の時間を支配する
   call/frame、属性、container操作、短命objectの費用を区別する。
3. 根拠のある共通最適化を実装・検証し、各scriptを同条件で追跡する。
   最終ゲートは、下記の更新されたユーザー目標に従う。

### 目標の更新とcold pilot

- ユーザーがobjectiveを「benchmarks/ にあるベンチマークスクリプトすべての
  実行時間の幾何平均をmain比で半減する。」へ明示的に更新した。以後は全6本を
  同じ重みで含む時間比の幾何平均を主指標にし、個別の比も全て報告する。
  各本の半減は必須ゲートから外す。入力・アルゴリズムは引き続き固定する。
- CPU 2、warmups=0、values=1のcold pilotが全12実行でchecksum検証成功。
  main / candidate全region ONの秒数はBPE 3.0055 / 2.9488、B-tree
  0.06572 / 0.06616、DeltaBlue 0.001940 / 0.001958、Hexiom 0.003874 /
  0.003950、Raytrace 0.15786 / 0.16215、Spectral 0.03424 / 0.01540。
  これは単発の探索値であり、性能達成の根拠とはしない。`pilot.json`に全値、
  process時間、実行コマンド、checksum、script/binary hashを保存した。
- 次はmatched warm screenと関数・native profile、executor coverageの採取。
  単一scriptの大きい改善だけで全体の達成を推定しない。

### 初期warm比較・coverageとlenの拡張

- 2 blocks、各3 warmups / 5 values、同じCPUとbinaryで順序を反転して比較した。
  個別の定常比はBPE 0.9931、B-tree 1.0142、DeltaBlue 1.0095、Hexiom
  1.0211、Raytrace 0.9976、Spectral 0.4378。全6本の幾何平均は **0.87649**、
  起動込みprocess比の幾何平均は0.89102。半減には未達。全値とchecksum照合は
  `initial-rows.json` / `initial-summary.json`、除外sampleは0。
- `initial-probe-*.json`に実executorとnative bytes、sample前後のcounter差を保存。
  BPE/B-tree/Hexiomでは既存regionのentryが全て0。DeltaBlueは短い設定では
  executorが1個で、warmup/trace形成自体の費用も今後区別する。Raytraceでは
  100,253 float融合と10,000 bounded int entriesがあり、失敗counter=0だが、
  それだけでscript全体の改善は見られない。Spectralの675,960 divisionsは維持。
- 別のperf sampling (`initial-perf-*`) は全てlost=0。BPEはdict lookup、tuple/list
  allocation・破棄・iteration、GCに費用が分散。B-treeはlistiter_next 10.10%、
  enum_next 4.72%。DeltaBlue/Raytraceはframe clear関連にそれぞれ約8%、
  Hexiomはrichcompare/list containsに約12%。sampling割合と時間比を混同しない。
- BPEの実traceにある`len(word) - 1`は定数operandのため旧loweringの対象外だった。
  既存CALL_LEN_CONSUMERをsmall-int定数に拡張し、exact list/dictも長さをその場で
  読む。owned receiverも他のstrong referenceがある場合はcloseでfinalizerが
  動かないため許可する（64-bit GIL gateは維持）。単独所有・subclassはfallback。
  call/store/periodic checkを跨いだ長さの再利用は行わない。
- 2 testsを追加し、既存のreceiver matrixもlist/dictへ拡張。定数の演算・比較、
  空container、attribute経由のowned alias、反復内のmutationを実経路で確認する。
  現在debug/nativeをビルド・検証中。次はnative効果を測り、call/frameや
  container操作の共通改善へ進む。

### len拡張の検証と次のcall実装

- debug 23 tests成功、nativeはregions/opt/tier3の351 tests・7 skips成功。
  同条件の2 blocks (`len-rows.json`) の全6本geomeanは0.86301。個別の比は
  BPE 0.9716、B-tree 1.0021、DeltaBlue 1.0001、Hexiom 0.9813、Raytrace
  0.9857、Spectral 0.4386。探索段階の小さい差であり、全体半減には未達。
- `len-probe-*`の1 operationでBPE 15,418,447、B-tree 7,495、Hexiom 34,602
  len entriesを確認し、全てguard failure=0 / allocation error=0。長さ融合が
  実programで動く状態になった。比較前のnative binaryを
  `build-jit/python-suite-initial`、len版を`python-suite-len`として固定保存した。
- 次に`PYTHON_TIER2_CALL_REGIONS=1`のopt-in経路を実装中。abstract interpreterが
  対応を確認済みのexact-args callについて、calleeが引数かimmortal定数を返すだけの
  場合にframeを省く。既存のfunction version・argument・recursion・stack checksを
  維持し、calleeのeval breakerに不一致があれば元CALLへ戻す。
- 返す引数を先にstrong reference化し、消費した引数をCの一時配列へ移してから、
  通常returnと同じ逆順でcloseする。finalizerの再入時にも他の引数が生存し、
  呼出側のoperand stackから消費済みrefsが見えないようにする。
  任意のcalleeや有効なDTrace/特殊platformへ範囲を広げない。
- 0〜4 arguments、各引数/定数return、methodのself return、code差し替え、
  override、finalizer順序と再入、monitoringの4 testsを追加してdebug検証中。
- 最初のcallテストは認識が働かず33 subcasesで失敗した。実行部の意味論不一致では
  なく、abstract pass後にも参照cleanup用の_RECORD_CODEが残ることをpatternが
  考慮していなかったため。recordを認識時だけ読み飛ばし、元のtracer cleanupに
  残すよう修正した。27 region testsは全て成功。現在native buildとcall/frame/
  monitoring等の関連10 suitesを検証中。
- nativeのregions/opt/tier3は355 tests・7 skips成功。debug関連10 suitesでは
  9 suitesが成功し、test_sysのみremote_execの11 casesがsandboxの
  PermissionErrorで失敗した。CALL_REGIONS=0のself-process caseでも同じエラーを
  再現。自分自身/テストが起動した子へのアクセスを行うtest_sysを承認済みの
  sandbox外実行で再確認し、101 tests・7 skips成功。関連10 suitesの全1,246件を
  通過したが、test_sysの実行環境は区別してログに残す。システム設定は未変更。
- 次はcall版の全6本比較、callee省略の実entry counter、生成native codeの確認。
- call版2 blocksの全6本geomeanは **0.85783**、起動込みは0.87568。
  個別の定常比はBPE 0.9800、B-tree 1.0002、DeltaBlue 1.0160、Hexiom
  0.9875、Raytrace 0.9240、Spectral 0.4385。`call-rows.json`に全値保存。
  Raytraceで1 operationあたり676,375 call entries、guard exits=0を確認し、
  同probeのexecutor確保bytes合計は647,168から634,880へ減った。page paddingと
  複数executorを含むサイズであり、純粋な命令サイズとは区別する。
  `_CALL_PY_TRIVIAL_0`のnative stencilは269 bytes。半減は引き続き未達。

### lenの比較consumerまでの接続

- BPEでは長さと`- 1`を融合しても、そのinteger結果を直後の比較が再びunboxして
  いた。`left CMP len(value)`および`left CMP (len(value) +/- small_constant)`を
  同じbounded matcherで認識し、boolへ直接接続する実装を追加中。
  元のleft/receiver/callableをguard時に保持し、失敗時は元CALLへ戻す。
  受理したreceiverとexact-int leftのcleanupにPythonへの再入はなく、長さの読みは
  effectを跨がない。加減算overflowは通常経路へ戻す。新しい実行tierは追加しない。
- 長さ取得・所有権guardを共通inline helperへまとめた。6種類の比較、長さ0/1/400、
  signed-i64両端、bool/huge-int/subclassのfallback、callback順序、反復内mutationを
  検証する3 testsを追加し、debug build中。次はnative検証と全6本比較を行う。
- debug region30 tests、generator99 tests成功。generatorを最初に旧名
  `test_tools.test_cases_generator`で起動した1回はModuleNotFoundErrorで、実際の
  `test_generated_cases`で再実行した。nativeは358 tests・7 skips成功。
- 2 blocksの全6本geomeanは0.85935、起動込み0.87428。前のcall版0.85783から
  全体の改善はまだ見られず、探索値を性能上の有効性とは扱わない。全値は
  `len-compare-rows.json`。元のcall版も保存し、後続の測定でON/OFFを切り分ける。

### 一時tupleの比較

- BPEのprofileにtuple生成・破棄が現れ、実traceにも`(word[i], word[i+1]) == pair`
  があるため、同じuop依存関係の2要素tupleのEQ/NEを次の対象にした。
  作ったtupleが即座にlocalのtupleとの比較で消費される場合だけを16 uops以内で
  認識し、一時tupleの生成と汎用tuple比較を省く。関数名や入力には依存しない。
- 右はexact tupleかつ長さ2、対応する各要素は同じexact bytes/str/int/float型に限定。
  NaN等を含むtuple比較のidentity shortcutを保つ。異種型、subclass、長さ違いは
  元BUILD_TUPLEへ戻す。特に長さ違いでもtupleは共通prefixの__eq__を呼ぶため、
  長さだけを見てfalseにはしない。BytesWarningがあり得る異種比較もfallback。
- 4 testsを追加し、builtin各型・任意精度int・NaN/±0、subclass dispatch、要素の
  callback順序、owned一時要素のfinalizer順序、`-bb`のBytesWarningを確認する。
  現在はlen比較版のcounter採取中で、完了後にtuple版をビルド・検証する。
- tuple版debugの34 region testsとgenerator99 testsが成功。最初の`-bb`テストは
  警告例外自体は正しかったが、初回のTier1反復で例外を出してguard counterを
  確認できなかった。初回だけ同型、2反復目で異種比較にする入力へ修正し、
  実regionのguard exitとBytesWarningの両方を確認した。
- len比較版probeではBPE 15,418,447 / B-tree 39,731 / Hexiom 34,602 len entries、
  全てguard失敗0。B-treeでも従来より多くの長さ比較が対象になった。
  現在tuple版native buildとcontainer/数値比較の関連8 suitesを実行中。
- tuple版native 362 tests・7 skips成功、debug関連8 suites 834 tests・15 skips成功。
  2 blocksの全6本geomeanは0.85217、起動込み0.87037。個別比はBPE 0.92068、
  B-tree 1.00461、DeltaBlue 1.01038、Hexiom 0.97850、Raytrace 0.95423、
  Spectral 0.43887。探索の全値を`tuple-rows.json`に保存。半減は未達。

### callの追加レビュー：code lifetimeの修正

- 追加レビューで、通常のframeがf_executableを保持する期間も再現する必要があると
  分かった。finalizerがcallee.__code__を差し替えると、旧コードのweakref callbackが
  finalizerの終了前に動いてしまう問題をdebug/native両方で実際に再現した。
  `call-lifetime-before-{debug,native}.log`とOFFの対照結果を保存した。
- frameを省いても、元のcodeをcall開始時にretainし、引数・callableのcleanupが
  完了してからreleaseするよう修正。新しい回帰テストは2反復目にfinalizerを渡し、
  call counter増分と、旧コードがfinalizer中は生存することを両方検査する。
  修正前はbefore→code解放→after(false)、修正後/OFFは
  before→after(true)→code解放になった。refcountもOFFと一致。
- debug35 region tests + generator99 testsの134件成功。現在nativeと関連call/frame/
  weakref suitesを再検証中。修正前の探索時間は最終性能の根拠には使わない。
- 修正後nativeは363 tests・7 skips成功。code lifetimeの単独probeもdebug/nativeで
  正しい順序と実call entryを確認した。debug関連call/frame/eval/weakrefの407件・
  12 skips成功。4生成ファイルの再生成はbyte単位で同一、F401/F811とdiff check成功。
- 次の比較からはblockごとにPYTHONHASHSEED=0,1,...をmain/candidate両方へ同じ値で
  渡し、dict配置のprocessごとの変動を対応させる。設定をraw metadataへ記録する。
  以前の探索値はそのまま保持し、設定変更を混ぜた差分は効果量として扱わない。
- 一連のlen/tuple consumerとtrivial-callの変更をローカルcommitにまとめ、修正後の
  全6本を通常の3 warmups / 10 valuesで比較する。目標はなおactiveで、0.5以下には
  未達。次の大きい課題は数値領域の周囲に残るframe・float box・loop bookkeeping。
  特にspectralのnative化余地と、Raytraceの属性からfloat算術への接続を調査する。
- ローカル実装commitは`8ce3bf60642d0d13b018c0d24b423f307d8af3cf`。
  `current-manifest.json`と`current-source-hashes.json`にcommit/tree、cleanな取得時点の
  全6,378 tracked files、binary、configure、実体stencil、全benchmarkのhashを保存。
  native binary SHA256は`33d5ee3c381584981acb43d7ab7c73b18875978a8c4a21d40166b21dd2c3c289`。
- 通常設定の再測定中、spectralのJSONにjit_enabledがないためcontrollerの追加検査が
  失敗した。他5本とspectralの実行・checksumは正常。保存済みの10行とspectralの
  全10 samplesを保持し、後者を`current-recovery.json`に記録して再開した。
  その1 processのwall timeだけは保存前に失われたためnullとし、推定で埋めない。
  全ての定常samplesを主解析に含め、process全体の比は欠測を明示する。
  元scriptのJIT確認は別のexecutor probeを併用する。
- 修正後の通常設定は全24 processes / 240定常samplesを保持して完了した。
  個別比はBPE 0.92569、B-tree 0.99535、DeltaBlue 0.99282、Hexiom 0.97475、
  Raytrace 0.95234、Spectral 0.43831、全6本の幾何平均0.84813。半減は未達。
  起動込み0.86165はSpectralの1 pairだけwall time欠測のため、同じ標本数の
  比較ではない。`current-summary.json`に各pairを残した。
- executor probeを`gc.get_referents(executor)`で到達可能なside traceまで辿るよう
  修正した。BPEのtuple entriesは5,515,130、len entriesは15,437,472、guard失敗0。
  以前のcode-attached executorのみのcounterはcoverageの下限だった。今回の
  `current-graph-bpe.json`はpinし忘れた診断なので時間の比較には使わない。
- 数値ループの費用を切り分けるC診断は、Spectralと同じ全演算・加算順序・checksumで
  約0.617ms/kernel。Pythonの測定結果や目標達成値には含めない。最初の診断は
  compilerが重複呼び出しを除去していたため無効と判定し、assemblyとともに
  `numeric-ceiling-elided.*`へ保存した。修正版は各呼び出しの結果をvolatile sinkへ
  書き、assemblyで100回のcallとscalar div/addを確認した。

### 次の実装：二次式の逆数を加算する短いrange領域

- 既存のbounded int traceから整数の二次多項式を構成し、有限差分の係数を通常の
  copy-and-patch uopで計算する方法を実装する。runtime node interpreterや入力名に
  依存するkernelは追加しない。定数・一次・二次の同じfamilyを扱う。
- 最初はstep=1、index全体が既存small-int cache内、exactかつuniqueなfloat
  accumulatorに限定する。これによりchunk内のframe生成・中間box・最終allocationを
  省ける。元の最後の1反復を残し、最大反復数もsmall-int cacheの範囲に制限する。
- 係数のoverflow、非定数係数が割り切れないfloor division、分母の符号変化、
  非exact型、alias、code変更、監視イベントでは元のFOR_ITERへ戻す。floatの除算と
  加算は反復ごとの順序を変えない。まずこの契約をdebugで確認し、効果が見えてから
  nativeと関連テストへ進む。現時点では未実装・未検証。
- `_FLOAT_RANGE_GUARD`、係数計算の4演算family、`_FLOAT_RANGE_REDUCE`を実装。
  現在のsmall-int cacheは-5..1024なので、chunkは最大1,029反復で周期的な確認へ戻る。
  guardはrange/unique float/各int入力/関数version/stack・再帰余地/監視versionを検査する。
  係数は整数値のbasis `1, j, j*(j-1)//2`で扱い、除算では非定数係数の整除を検査。
  単調かつ同符号で、分母が±2**53以内のchunkだけを実行する。
- 初案の3係数×4段をPython operand stackへ置く方法は、debugのstack上限検査で
  停止した。frameのco_stacksizeを超えるため不採用とし、executor内の4×3個の
  整数作業領域へ変更した。GIL保持中でPythonへのescapeがないsetup区間に限定し、
  同じexecutorへの再入・並行実行が起きない契約にする。runtime node dispatchはない。
  新headerをMakefileの明示依存にも追加した。
- テストの最初のwarmupは4002反復の閾値に不足していたため、閾値から回数を算出。
  fallbackの試験もcache上限を従来の256と誤認していたので1024の外へ修正した。
  型・大きいint・cache外・係数の非整除・分母0の元callee traceback・subclassの
  dispatch順序・monitoringイベント数・code変更を検査する40 region testsがdebug/nativeで
  成功。native関連367 tests・7 skips、debug region/generator138 testsが成功した後、
  追加の例外/subclassテストを両buildで再実行している。
- nativeの単独予備測定は約1.26ms、元benchmarkのchecksum一致。別のnative probeは
  5,200 range entries / 665,600 iterations、guard失敗0。残りの通常処理も含めて元の
  676,000 term evaluationsを保つ。code-attachedとside executorの合計は24,576 bytes。
  この時点ではmainとの対応測定ではなく予備値。全6本の2 blocks・通常10 values比較を
  開始した。完了後に丸めのbit比較と追加レビューを行う。半減目標は継続中。
- 最初のrange版の全6本geomeanは0.56486（起動込み0.66177）。個別比は
  BPE 0.92901、B-tree 0.98770、DeltaBlue 1.02093、Hexiom 0.97475、
  Raytrace 0.95249、Spectral 0.03735。全240定常samplesを残した。
  半減はなお未達。DeltaBlueの約2.1%悪化も含め、`float-range-rows.json`へ記録した。
- Linux/x86の4丸めモード、3式、6種類の分子、4種類の初期値を組み合わせた288件の
  bit比較がnativeで成功。各caseの実range counter増分と丸めモードの復元を確認した。
  数値は±0、負数、subnormal、overflowも含む。例外/subclass追加後はregion40 testsが
  debug/nativeで成功。初版binary、差分、新header、stencil hashを
  `float-range-initial-manifest.json`に対応付けて保持した。
- 次に、既知の2の累乗での係数除算をmaskと算術shiftに置き換える。
  元の整数regionが持つshift量を使い、非定数係数の整除を引き続き検査する。
  その除数だけの係数constantは不要になるため省く。setupがescapeしないことを
  metadataでもassertする。変更前binaryは`python-suite-float-range`へ保存済み。
- shift版はdebug region41 + generator99の140 tests、native関連369 tests・7 skips成功。
  数値/range/call/frame/weakref/trace/monitoringのdebug8 suitesは1,072 tests・14 skips成功。
  4丸めモードの288 bit比較も再度成功した。2の累乗で割り切れない係数と、負の係数に
  対する算術shiftのテストを追加した。4生成ファイルは再生成でbyte単位同一。
- Spectralの追加比較は3 blocksでmain→前版→shift版の順をrotateし、全90 valuesを保持。
  `float-range-shift-paired.json`にコマンド・env・binary hash・全値を保存した。
  追加効果は小さく、6本全体の半減にはまだ足りない。新しい領域をローカルcommitへ
  まとめ、次にprofileで費用が大きいenumerate(list)の反復を調べる。
- range領域のローカルcommitは`20570bef035`。shift版の前版比は3 blocksのgeomean
  0.99012で約1%の追加短縮だった。commit/tree、全tracked source、binary/configure/
  stencilは`float-range-manifest.json`と`float-range-source-hashes.json`へ保存した。

### enumerate(list)の反復処理

- B-treeのprofileにはlist iteratorのnext約10.1%、enum_next約4.7%があり、実traceも
  `_GUARD_TYPE_ITER`→`_ITER_NEXT_INLINE`→tuple unpackを通っていた。
  `PYTHON_TIER2_BUILTIN_REGIONS=1`の中で、exact enumerateの内部がexact list iterator、
  indexがsmall-int cache内、結果tupleがuniqueかつ次要素が存在する場合に限る経路を追加。
- guardは元のFOR_ITERへ戻す。元の`_ITER_NEXT_INLINE`のexitはEND_FORの後なので、
  未対応入力のfallbackに流用するとループを途中終了してしまう点を分けて扱う。
  enumobjectの構造体をinternal headerへ移し、tupleの更新、参照の解放順、GCへの再登録と
  hash cacheのresetはenum_nextと同じ順にする。共有tupleや枯渇時は通常処理へ戻す。
- debugの4テストが成功。list/tuple iterator、cache境界・巨大index、結果tupleの外部alias、
  hash計算後のtuple再利用、旧要素のfinalizerが同じenumerateへ再入する場合を確認した。
  現在native buildと関連検証へ進む。`enum_guard_exits`は通常のiterator枯渇も数える。
- debug region45 + generator99の144 tests、関連enumerate/iter/list/tuple/GCの341 tests・
  1 skip、native関連373 tests・7 skipsが成功。B-treeの3 blocks・各10 values比較では
  前版比0.97580、main比0.97229で、全値を`enum-btree-rows.json`へ保存した。
  単一build同士で約2.4%の追加短縮という範囲の結果として扱う。
- B-treeのnative probeはenum entries 1,455,829、guard exits 16,302（枯渇を含む）、
  len entries 110,877。side traceを含む45 executors・356,352 bytesを保存した。
  4生成ファイルの再生成はbyte単位で同一、F401/F811とdiff check成功。
  次はattribute getterと、属性同士の整数比較を行う短いcalleeへcall frame省略を広げる。
- enumerate実装のローカルcommitは`f6ce15da08e`。

### 属性を読む短いcallee

- 既存の`_CALL_PY_TRIVIAL`を、cached attributeの取得、`is None`/`is not None`、
  二つのcached attributeのcompact exact int比較へ拡張した。引数・定数の旧経路も保持。
  slotとmanaged inline valueを扱い、最大4 explicit args、最大64 uopsを検査する。
- abstract interpreterが冗長guardを消す前に、元のLOAD_ATTRに対応するtype versionを
  未使用operand1へ注記する。現在のtype versionを後から推定して古いoffsetと組み合わせる
  ことはしない。CALL入口でその記録済みversion、inline valuesの有効性、属性の存在、
  必要なら両方のexact compact intを検査する。失敗時は入力を消費せず元CALLへ戻す。
- 参照のcleanupとcode lifetimeは既存call経路を共有する。recorded referencesはnormal
  tracer cleanupまで保持する。callee bodyのtype recorderもskip/保持対象に含めた。
- debug region50 + generator99の149 testsが成功。slot/managedのgetter・None比較・
  6種類の整数比較、巨大int/bool、descriptor変更、subclassの非bool比較結果、owned receiverの
  finalizer時のrefcount、classmethodでの異なるlayoutの二つの引数を確認した。
- enumerateの生成コードを読んで、PyTuple_SET_ITEMと_PyTuple_Recycleが不要なescape扱いに
  なっていたことも修正した。前者は代入、後者はhash resetとGC link更新だけでPythonへ
  再入しない。要素のDECREFに必要なescapeは保持する。nativeと関連テストへ進む。
- native関連378 tests・7 skips、debug関連9 suitesの1,203 tests・14 skipsが成功。
  通常の3 warmups / 10 valuesで全6本を2 blocks比較し、実workloadでのcoverageも
  追加確認する。実装したgetterの機能検証と、ベンチマーク上の効果は分けて扱う。
- 属性callの初版は6本geomean 0.56124（起動込み0.66489）。個別比はBPE 0.92418、
  B-tree 0.96006、DeltaBlue 1.00660、Hexiom 0.97273、Raytrace 0.96729、
  Spectral 0.03719。半減は未達。B-treeは定常では改善する一方、起動込みでは1.00976。
- 引数/定数の既存call stencilへ属性の全分岐を加えたため、単純なcallにも大きいcodeを
  複製する構造になっていた。既存_CALL_PY_TRIVIALを元に戻し、属性用の
  _CALL_PY_ATTRIBUTEへ分離してコード量と影響を再確認する。初版binaryと差分は
  `python-suite-attr-call-initial`、`attr-call-initial-manifest.json`へ保存した。
- DeltaBlueのprobeでは、既定の3 warmups直後のexecutor集合が空で、4回目の実行中に
  3 executorsが現れた。従来probeは新規executorの増分を数えていなかったので、実行直後に
  新規分も取得し、check_resultを呼ぶ前に加算するよう修正した。過去の空counterを
  「JITが一度も動かなかった」という証拠にはしない。warmup軌跡の診断も追加する。
- 修正probeによるDeltaBlueは3 warmups後の実行で新規3 executors・属性call増分0、
  20 warmups後では24 executors・属性call増分1,301だった。Hexiomも15→43 executorsに
  増える。これらはdefault workloadのcoverageを説明する診断で、warmupを変更した時間を
  目標値へ混ぜない。debugテストと一部時間が重なったため、probeの時刻値も性能比較に
  使わない。分離版debug149 testsが通過し、nativeを再ビルド中。
- 分離版native378 tests・7 skipsが成功。Raytraceの3 blocks・各10 valuesはmain比
  0.98276、enumerate版比1.01482で改善とは判断しない。block間の比は0.971〜1.047と
  揺れており、全90値とbinary hashを`attr-call-split-raytrace-rows.json`へ保存した。
  4生成ファイルは再生成で同一、F401/F811とdiff checkも成功。
- 次はrange係数の式をコンパイル時に簡約する。既存の多項式uop列から定数畳み込みを行い、
  範囲証明したスカラー整数uopへ変換する。Python frameの余剰stack容量に収まることも
  確認し、証明や容量が不足すれば現在の係数計算を保持する。浮動小数点の除算・加算順と
  元traceのfallbackは保持する。全6本geomeanの最新値は初版の0.56124で半減未達。

### 係数計算のコンパイル時簡約

- 属性callはローカルcommit `dadeeb6d2b8`。B-treeのnative probeでは属性call 99,655回、
  call guard失敗0を確認した。commit/tree、全tracked sourceとbuild artifactのhashは
  `attr-call-manifest.json`、`attr-call-source-hashes.json`に記録し、比較用binaryも保存した。
- 多項式係数を最大96 nodesのコンパイル時式に変換し、0/1、同じ値の加算、定数の再結合、
  exact除算の因数分解を追加。62-bit interval proofは既存int領域と共通headerへ移した。
  証明できない除算の割り切れ条件は実行時に検査し、後続の`* 0`が値を消しても検査は残す。
- スカラー値は既存のtagged integer uopと最大96 uopsのprefixで計算する。発行時のstack
  最大深さを元codeのco_stacksizeとtrace開始stack深さから求めた余剰容量と比較する。
  条件を満たさない場合は既存scratchでの係数計算をそのまま使う。setup中のexit/escapeを
  metadataで検査し、最終3係数だけを従来のrange reductionへ渡す。
- debug buildが完了。簡約命令の実適用、3と4による係数のexact/nonexact除算、消去される
  値に付随する割り切れ検査のテストを追加し、region/generator testsを実行中。
- region52 testsとgenerator99 tests成功。最初はgeneratorのモジュール名を誤指定したため
  import失敗になったが、正しい`test_generated_cases`で再実行した。native関連380 tests・
  7 skipsと、4丸めモード・288 bit比較も成功し、元の丸めモードへ復元した。
- native assemblyの従来ループには、最終回だけ整数差分の更新を止めるための二つのcmovが
  毎反復入っていた。係数簡約単独の比較を先に保存し、その後、最後の除算・加算をloop外へ
  分離してこの分岐を除く。既存の終点と最終差分の証明範囲を超えた整数演算は行わない。
- 係数簡約単独はSpectralの3 blocksで前版比0.91072、main比0.03379。最後の項をloop外へ
  分けた追加変更は前版比0.97629、main比0.03291だった。各90値・checksum・binary hashは
  `scalar-poly-spectral-rows.json`、`scalar-peel-spectral-rows.json`へ保存した。
- 最後の項を分けた版はdebug281 tests・1 skip、native380 tests・7 skipsと丸め288件が成功。
  1/2/3要素のrangeも検査した。native probeはrange 5,200 chunks・665,600 iterations、
  guard失敗0、box0。assemblyの内側loopで2つのcmovが消え、divsd/addsdは別命令のまま。
- 次はbinary64の境界を保ちつつ、native側の各項のvolatile store/reloadを除けるか検証する。
  Clangの局所的なFP contraction禁止を明示するhelperを使い、GCC側は既存volatileを保持。
  assemblyと4丸めモードでのbit一致を条件に、別因子として比較する。
- `clang-21 -O3 -mfma -ffp-contract=fast`の小さなinline実験で、`contract(off)`だけでは
  multiply/addがFMAへ融合することを確認した。`__builtin_assoc_barrier`も未対応だった。
  `FENV_ACCESS ON`ではinline後もLLVM constrained FPが残り、対照だけがFMAとなった。
  この指定を局所helperに採用し、GCC側はvolatileを保持する。実験のC/IR/assemblyと失敗も
  `clang-{contract,assoc,fenv}-probe.*`へ保存した。native本体の検証へ進む。
- constrained FP版もdebug151 tests、native380 tests・7 skips、丸め288件が成功した。
  native assemblyはdivsd/addsdの別命令を保持し、項ごとのstore/reloadが消えた。
  前版比は3 blocksで0.98773、main比0.03244。追加効果は約1%に留まり、命令削減だけで
  大きく速くなったとは扱わない。全値は`scalar-fenv-spectral-rows.json`に記録した。
- ここまでをローカルcommitへまとめる。次は係数のcompile-time boundsから、rangeの
  初期値・終点検査も64-bitで安全に行える場合を証明し、現在の128-bit計算を減らす。
  簡約できない式には既存経路を残す。全6本の半減はまだ未達。

### range初期値・終点検査の整数幅

- 係数簡約版はローカルcommit `85d7ba42c49`。全tracked sourceとbuild artifactのhashを
  `scalar-source-hashes.json`、`scalar-manifest.json`へ記録した。
- scalar係数のintervalとsmall-int cache内のstart/countから、初期値・差分・終点・最終差分の
  全中間値を追加で証明する。除算前の積も検査し、相関による範囲縮小は仮定しない。
  成功時だけ64-bitの準備uopを使い、証明できなければ128-bitの準備uopを使う。
- 準備とfloat loopを分離し、成功時のscratch先頭二値を初期denominatorとdeltaへ置き換える。
  符号・単調性・2**53以内の検査と、失敗時に元FOR_ITERへ戻る処理は同じ。新規経路の
  実適用をテストで確認し、native buildと検証へ進む。
- debug151 tests、native380 tests・7 skips、丸め288件が成功。直列の3 blocks比較では
  前版比0.98864、main比0.03223。最初の`range64-spectral`比較は診断probeと短時間重ねて
  しまったため性能判定には使わず、生値を残して`range64-serial-spectral`として3 blocksを
  取り直した。速い/遅い値の選別ではなく、競合を避ける測定手順への違反による再実行。
- 次は残していた最後の通常iterationもchunkへ含める。成功後には元のrange exhaustion
  guardを複製し、その既存の出口へ戻す。元traceのcallee定数とfallbackは残すので、参照保持を
  新たな仕組みへ移さない。終点の証明は追加の1項まで広げ、index/local/iteratorを最後の状態へ
  更新する。元FOR_ITERへ戻る失敗経路と、END_FORの後へ進む成功経路を分けて扱う。
- 最後の項まで含む版はdebug153 tests、native382 tests・7 skips、4丸めモード288件が成功。
  最後の分母が0になる場合のcallee traceback、callerのjと部分和、外部aliasのあるrange
  iteratorの枯渇と最後のindexを追加検証した。native比較後、全6本を再測定する。
- 最後の通常iterationを省く追加効果は前版比0.88769、Spectralのmain比0.02864。
  rangeは5,200 chunks・670,800 iterationsでguard失敗0、通常のbounded divisionsが
  10,360→5,160へ減った。676,000項の計算自体は同じ。
- 全6本の2 blocks・各10値はgeomean **0.54025**（起動込み0.65688）。個別比は
  BPE 0.92598、B-tree 0.98050、DeltaBlue 1.01462、Hexiom 0.98130、Raytrace 0.95642、
  Spectral 0.02876。半減未達。B-treeはblocks間0.950〜1.012で、起動込みでは1.03167。
  全240値とchecksum/binary/script hashは`range-full-rows.json`に記録した。
- 追加の特殊値検証56件で、分子と初期値が異なるNaNの場合にpayload差を2件発見した。
  constrained FPでもoperand registerの選び方によりNaN payloadは変わり得るため、累積値が
  NaNなら元のPython経路へ戻すguardを追加した。quiet/signaling NaNの3 payloadについて
  修正前の失敗を回帰テストで確認済み。上の性能比較は修正前binaryの結果として保持する。
  `co_consts`差し替えによる最初の診断は借用constant条件を満たさずexecutor未生成だったので、
  コンパイラが畳み込むNaN式を使って実経路を検証した。修正後のnative検証へ進む。
- NaN修正後はnative383 tests・7 skips、4丸めモード288件と特殊値56件のbit比較が成功した。
  isnanは再入しない判定として生成器へ登録し、不要なescape処理を除いた最終native版でも
  通過した。一方debug154 testsにはNaN payloadの3失敗が残っており、前の成功記録は誤り。
  ログの失敗を見落としてローカルcommit `65c1465643c`へ進めてしまったため訂正する。
  debugの通常JIT経路とoperator.addの差か、実装の差かを最適化OFFの対照で切り分ける。
- `nan-control-{debug,native}.json`でOFF/ONを比較し、debugの3 payloadはOFFでも
  operator.addと異なる一方、ONとOFFはbit単位で一致すると確認した。nativeもON/OFF一致。
  ONではrange guard失敗79回・chunk iteration0なので通常処理へ戻っている。
  テストの対照を、同じbytecodeを新しいcode objectでwarmupしたfeature OFF版へ修正する。
  nativeで最初に発見した差は実装の問題でありNaN guardで修正済み、debugの残りの失敗は
  operator.addを対照にしたテストの問題だった。訂正後のdebug/native testsを再実行中。
- 次のBPE候補は、実traceの二つのlist subscriptと`i+1`から既存tuple比較までの処理を融合する。
  同じborrowed localのexact list/int、両indexの範囲、exact tupleと対応するimmutable要素型を
  最初のsubscriptで検査する。失敗時は最初の添字操作へ戻し、second-indexの例外やsubclassの
  callback順を保持する。まずこの契約を実装・テストし、実coverageとBPEの差を確認する。

### listの二つの添字操作とtuple比較

- NaNテストの訂正後はdebug154 testsとnative region55 tests・3 skipsが成功。
  ローカルcommitは`34be1000494`、実装直前のrange改善は`65c1465643c`。
  全tracked source/build artifactのhashを`range-final-*-hashes.json`と
  `range-final-manifest.json`へ保存し、比較用binary `python-suite-range-final`も保持した。
- post-abstractの最大64 uopsを検査し、同じborrowed list/index localからの
  二つのsubscriptと`i+1`、既存tuple比較を`_COMPARE_LIST_PAIR`へ融合した。
  一時要素の参照とindexのboxを省き、両indexと対応するimmutable型を最初に検査する。
  indexの負数補正は二つそれぞれに行い、`i=-1`の次が0になるPythonの意味を保持する。
- 成功数は`tuple_list_entries`に分けて記録する。guard失敗は既存tuple counterへ加算し、
  最初の添字操作でfallbackする。recorded referencesは通常のtracer cleanupまで保持。
- debug region59 + generator99の158 testsが成功。EQ/NE、bytes/str/big int/float/NaN、
  負のindex、cache外のindex、第一・第二indexの範囲外、要素・index・list・right tupleの
  subclass callbackと非boolの比較結果を確認した。native buildへ進む。
- listを同じloop内で書き換える検証も追加し、debug159 tests、native388 tests・7 skipsが成功。
  BPEのnative probeはtuple_list_entries 5,512,640、tuple guard失敗0。全tuple entries
  5,515,130の大半が新経路を使い、len entries 15,437,472も保持していた。
  3 blocks・各10値でmain/前版/新実装をrotateする比較を実行中。
- 同じprobeで`enumerate(zip(...))`に対するenum guard失敗が1,033,510回と判明した。
  list専用guardでunsupported iteratorも毎回traceから外しているため、次に通常のenum_nextを
  その場で呼ぶfallbackを検討する。先に現在のlist比較の効果を保存し、別変更として検証する。
- 共有のimmutable equality helperも確認した。非compact intだけ汎用richcompareを呼んで
  いたが、そのAPIはC再帰limitで例外を返し得るため「失敗しない」というassertと整合しない。
  list比較の測定完了後に、符号・digit数・digitsの直接比較へ置き換え、別objectの大整数を
  対象にした一致/不一致を追加検証する。
- list比較の3 blocksは前版比0.98062、main比0.91307。全90値・起動時間・identityを
  `list-pair-bpe-rows.json`へ保存した。約1.9%の追加短縮で、これ単独では全体の半減に足りない。
  比較時のbinaryと差分は`python-suite-list-pair-initial`、`list-pair-initial-manifest.json`へ保存。
- 共有helperの大整数比較を、符号・digit数・digitsの直接比較へ変更した。100-bit/4,096-bitの
  別objectについて、等値、隣接値、符号違い、digit数違いを両方のtuple経路で検証する。
  この修正を含む最終debug/native buildを実行中。
- 最終region/generatorはdebug160 tests、native389 tests・7 skipsが成功。一緒に走らせた
  別debug regrtestは同じworker名の一時directoryを共有し、片方の終了時にcwdが消えたため
  5 suitesが失敗した。並行tool実行のPID namespaceが同じworker PIDを使うためで、ログの
  FileExistsError/FileNotFoundErrorを保存した。専用tempdirでdebug8 suitesを直列に再実行する。
  今後の衝突を避ける手順をAGENTS.mdにも追記した。
- 専用tempdirでのdebug8 suitesは505 tests成功。元の失敗ログは保持し、この直列結果を
  関連検証の結果とする。4生成ファイルの再生成同一性、静的check、diff checkを済ませて
  ローカルcommitへまとめ、次にenumerateのunsupported内側iteratorのfallbackを改善する。

### enumerateの通常経路をtrace内で呼ぶfallback

- list比較のローカルcommitは`d992fb58dd7`。全tracked sourceとbuild artifactのhashを
  `list-pair-source-hashes.json`、`list-pair-manifest.json`へ保存した。
- enumerateの型guardと内側iteratorの選択を分けた。exact list iterator・cached index・
  unique tuple・次の要素が揃う場合は現在のinline処理を使い、それ以外は同じtraceから
  通常のenum_nextを呼ぶ。`enum_fallbacks`を新設し、`enum_guard_exits`はenumerate型自体の
  不一致によるexitを数える。共有tuple/巨大index/枯渇も通常のenum処理へ任せる。
- 正常な枯渇は元のEND_FOR後の出口を使い、例外は型guardから保存した元FOR_ITER位置へ
  戻す。resident rangeと同じく、prepare_for_executionで独立したerror targetを設定する。
  zip内側のcounter、共有cached tuple、StopIterationとValueError、callerのtraceback行を
  確認するテストを追加し、debugで検証中。
- debug region63 + generator99の162 tests、関連enum/iter/list/tuple/GC/monitoringの
  439 tests・1 skipが成功。related suiteは専用tempdirを使い、同じworker directoryの
  衝突を避けた。native build後、BPEのguard/fallback counterとB-treeの高速経路を確認する。
- native391 tests・7 skipsが成功。BPE probeはenum guard失敗0、通常fallback81,840回、
  executor38個・180,224 bytes（前版72個・348,160 bytes）。list比較5,512,640回と
  len15,437,472回は保持した。B-treeはinline enum1,455,829回、通常fallback16,302回、
  型guard失敗0で、list高速経路が使われている。
- 3 blocks・各10値・main/前版/新実装をrotateした比較は、BPEが前版比0.99540・main比
  0.90991、B-treeが前版比0.98742・main比0.94104。guard exit解消の時間への効果は小幅。
  全180値・起動時間・checksum/identityは`enum-fallback-{bpe,btree}-rows.json`へ保存した。
  次はこの版を保存し、Spectralのnative loopと周辺処理の残るコストを診断する。
  Cの数値kernelは診断用の対照に限り、Python benchmarkの目標達成値へ混ぜない。
- 4生成ファイルは再生成で同一、diff checkも成功。手元のruffはrepositoryの`py315`設定を
  解釈できないため通常起動は失敗した。`--isolated --select F401,F811`で同じ静的checkを
  実行し成功した。Spectralの100 loops診断はPython約0.959 ms、C対照約0.617 msで、
  同じchecksumだった。この差を次のnative profileで調べる。

### 隣接する除算のSIMD化と加算順序の保持

- enumerate fallbackはローカルcommit `0ee834acfb2`。全tracked source/build artifactの
  hashを`enum-fallback-{source-hashes,manifest}.json`、比較用binaryを
  `python-suite-enum-fallback`へ保存した。
- Spectralのnative profileはlost samples0で、約64%が除算・加算loopに集中していた。
  range生成とその整数変換、frame cleanupなども残る。診断用Cで隣接除算だけを二つの
  SIMD lanesへまとめ、加算は元の順序で一つずつ行うと、約0.617→0.328 msだった。
  同じ676,000項とchecksumを維持し、C結果はPythonの達成判定には使わない。
- SSE2・fast-mathなし・MXCSRの例外trapが全てmaskedの場合に、この二項処理をrange
  uopへ追加した。trap有効時と他architectureは従来のscalar処理を使う。両分母は既存の
  非zero・整数からdoubleへのexact変換の証明対象であり、各除算結果を元の加算順序で使う。
  最後の1/2項はloop外へ分離し、差分更新が証明した最後のindexを超えないようにした。
- `±2**53`に`±1`を一項ずつ加える回帰テストで、項を先に合算する誤変換を検出する。
  1〜8、126〜131項の偶奇と末尾を検証する。debug/native buildと丸め・特殊値検証へ進む。
- debug region64 tests、generator/float/math/rangeの271 tests・3 skips、native392 tests・
  7 skipsが成功。generator suiteの最初の指定を`test_tools.test_generated_cases`と誤り
  import失敗したため、実在する`test_generated_cases`で関連suiteと再実行した。
- 4丸めモード×trap masked/FE_DIVBYZERO enabledの576ケースで、native/debugとも
  result bitsと例外flagsが対照と一致した。debugでnative-code bytesも要求した最初の診断は
  RuntimeErrorだったため、明示的な`--interpreter`引数を追加して再実行した。失敗ログは
  `.initial.*`に残した。native特殊値56ケースもpayloadを含めて一致した。
- native assemblyはdivpdの各laneを二つのaddsdへ順番に渡し、chunk前にMXCSR maskを検査。
  probeは5,200 chunks・670,800 iterations、guard失敗0、box0を保持した。3 blocksの
  Spectral比較は前版比0.77176・main比0.022643（約0.763 ms）。全90値は
  `range-paired-spectral-rows.json`へ保存。前版の第2 blockには約1.034 msの値もあり、
  それを含む全値から比を計算した。全6本の半減はまだ判定していない。
- 次は分母・差分・二階差分の範囲を追加検査し、全分母がsigned 32-bitに収まる場合に
  隣接整数の更新とdoubleへの変換もSIMD化する。大きな値は現在の64-bit版を保持する。
- 二項除算版はローカルcommit `189ed7cb98c`。source/build hashを
  `range-paired-{source-hashes,manifest}.json`、binaryを`python-suite-range-paired`へ保存。
- 分母・差分・二階差分をint32へ制限してから、cached range長を使う安全なint64式で終点を
  検査する経路を追加した。既存の単調性証明と合わせ、全分母のint32表現を保証する。
  二本の整数列と差分はpacked modulo-2**32加算で更新し、各laneをdoubleへexact変換する。
  最後の未使用の更新はwrap可能だが、消費する分母は全て元の整数値と一致する。
- `range_int32_iterations`で実適用を計測し、正負のint32境界の内外、第一差分の2倍がint32を
  超える短いrangeを追加テストする。native/debug buildを実行中。
- 最初のwrapテスト式は`a*j*j`を含み、既存のbounded-input証明では中間値が62-bitを
  超えるためrange自体が生成されなかった。二つの書き方を試した失敗ログを保持し、
  証明対象に収まる一次式`a*j*8+a+1`へ修正した。最初の通常iterationと残る二項の
  符号が変わるrangeで、同符号のchunk内だけを最適化し、paired stepのwrapを確認する。
- 修正後はdebug336 tests・3 skips、native393 tests・7 skipsが成功。両buildの丸め・trap・
  flags診断576ケースとnative特殊値56ケースも一致した。native probeは670,800 chunk
  iterations全てがint32経路を通り、guard失敗0・box0を保持した。
- assemblyはcvtdq2pd一命令で二つの分母を変換し、divpdと順序を保つ二つのaddsd、二つの
  padddでloopを構成していた。Spectralの3 blocksは前版比0.93225・main比0.020958
  （約0.710 ms）。全90値とidentityは`range-int32-spectral-rows.json`へ保存した。
  この版の全6本比較へ進み、なお不足すればprofileに残るrange生成の処理を検討する。
- int32版はローカルcommit `64b4ca84f02`。source/build hashと比較用binaryを保存済み。
  全6本・2 blocks・各10値の幾何平均は **0.50868**（起動込み0.63716）。半減未達で、
  全体としてさらに約1.7%の短縮が必要。全240値は`range-int32-suite-rows.json`へ保存した。

### rangeの生成とiteratorへの変換

- range生成後のperiodic checkをまたいで一時rangeを省くと、入力stopの参照数や生存期間を
  変えるため採用しない。rangeとiteratorは通常どおり別々に生成し、exact compact intと
  分かる場合の繰り返す整数変換・長さ計算だけを省く。
- 既知の`range(stop)` callは型と引数を検査し、既存のallocation/freelistを共有するhelperへ
  変換する。stopの参照を通常どおり保持し、private lengthも別のPyLongとして作る。
  既知のrangeに対するGET_ITERは四つのinteger fieldsを検査し、同じrange iteratorを作る。
  各uopのallocation errorは元CALL/GET_ITERへ戻し、periodic checkとcleanupは保持する。
- 負値/0/compact上限、stopのidentityとrefcount、大整数・bool・`__index__`のfallback、
  正負step/空range/巨大range、debugでの両allocation errorの位置を追加検証する。
  native/debug buildを実行中。
- nativeの最初のbuildはjit.cに新helper宣言が見えず失敗した。`pycore_range.h`のincludeを
  追加してbuildは完了。debugでは空rangeの返り値は一致したが、GET_ITER以前にtraceを
  離れるため同じexecutorのentry増加を要求した二つのassertが失敗した。空rangeでwarmup
  してもGET_ITERより前でDEOPTするtraceだったため、空rangeは結果を検査し、非空rangeで
  新uopのcounterを検証する形へ修正した。各失敗ログは残し、修正後の検証を実行中。
- 修正後のdebug region69 testsとnative関連426 tests・8 skipsが成功。debug関連の
  generator/range/iter/GC/monitoringは先の同時runで成功済み。同じframe内で両MemoryErrorを
  捕捉し、一時rangeの解放後にstopの参照数が戻るテストも追加した。最終region70 testsは
  debug成功、native成功・5 skips。4生成ファイルの同一性、静的check、diff checkも成功。
- Spectralの3 blocksは前版比0.87883・main比0.018378（約0.621 ms）。native probeでは
  range call/iterator生成それぞれ5,160回、int32 chunk670,800 iterations、guard失敗0。
  全90値とidentityは`range-objects-spectral-rows.json`へ保存した。
- 丸め・trap・flagsの576ケースはnativeで成功。全6オプションを有効にした追加runでも
  同576ケースと特殊値56ケースのbit比較が成功した。
- この実装を保存し、全6本を4 blocks・各10値で測定する。benchmarkは入力・warmups・
  loopsを変えず、全480値を使って幾何平均を判定する。ビルドや診断probeを測定と重ねない。

### 全6本の最終判定（2026-09-13）

- 実装commitは **`a021ff543bc`**。固定mainは **`a60343ed17785ebbcd43de9080cadd8e2541db6f`**。
  `range-objects-manifest.json`と`range-objects-source-hashes.json`にsource/build identityを保存。
  candidateのSHA256は`7960ce4c778a1be09efbab4aaba4779f28ec2c9471967b6efb028937e7e5c393`、
  mainは`8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`。
- Linux x86_64・GIL・CPU 2、GCC 13.3.0 -O3・LLVM 21.1.8、PGO/LTOなし。
  mainとcandidateのbuild条件を一致させ、元のCLIをwarmups=3、values=10、loops=1で実行。
  4 blocksで起動順を交互にし、PYTHONHASHSEEDはblock番号を使った。
  candidateはBOUNDED_INT_REGIONS、INT_REGIONS、BUILTIN_REGIONS、FLOAT_FUSION、
  CALL_REGIONS、FLOAT_RANGEの6実験オプションを有効化した。既定値は引き続きOFF。
- 各block内の10個の`samples_seconds`の算術平均からcandidate/main比を求め、block間と
  全6 script間を同じ重みの幾何平均で集計した。48 process・480値を全て採用し、除外0。
  全scriptのchecksumがmainと一致し、入力・アルゴリズム・仕事量は変更していない。

| script | 計測区間のmain比 |
| --- | ---: |
| bpe_tokeniser.py | 0.90987 |
| btree.py | 0.93032 |
| deltablue.py | 1.00029 |
| hexiom.py | 0.96108 |
| raytrace.py | 0.94687 |
| spectral_norm.py | 0.01843 |
| **幾何平均** | **0.492077（約2.032倍速）** |

- block別の幾何平均は0.49388、0.49074、0.49137、0.49233。全4 blocksとも0.5未満。
  更新された「全6本の時間比の幾何平均を半減」という主指標を達成した。
  DeltaBlueはほぼ同等であり、各script個別の半減を達成したという意味ではない。
  起動・warmupを含むprocess時間の幾何平均は **0.62891**で、この別指標は半減していない。
- 生データ・各processのstdout/stderr・checksum/環境/コマンド/identityは
  `jit-artifacts/benchmark-suite/range-objects-suite-rows.json`、集計は同directoryの
  `range-objects-suite-summary.json`。再測定は新しいprefixを指定して以下を実行する。

  ```sh
  python3 jit-artifacts/benchmark-suite/screen-float-range.py manual-final-check 4 10
  ```

- int領域、len/consumer、startswith/endswith、float丸め・所有権・fallbackの必須実装と
  検証は完了。追加したcall/tuple/list/enumerate/rangeの検証とnative証拠も上記に記録した。
  最終追加のrangeはdebug region70 tests、native region70 tests・5 skipsが成功し、
  関連range/iter/GC/monitoring/generator、native opt/tier3の検証も成功済み。
  全オプションONで丸め/trap/flags576ケースと特殊値56ケースがbit一致した。
- このgoalに必要な未完了作業はない。検証範囲はこのLinux x86_64構成であり、他architecture、
  free-threaded、32-bitの性能や全pyperformanceへの一般化は主張しない。
  GitHub投稿・push・PR変更は行っていない。今後の既定値変更や公開は別の作業として扱う。

### Core developer向け英文ドキュメント（2026-09-14）

- 依頼に応じて`Tools/jit/optimization_report.md`を作成し、`regions.md`からリンクした。
  実装commit `a021ff543bc`までのint/float/builtin/call/range最適化について、pass順序、
  適用条件、所有権、fallback/error位置、binary64丸め、SIMDの条件を英語で説明する。
- 最終480値から個別平均・対応比・全体幾何平均を再計算した。Spectral以外の5本は
  幾何平均0.949200であり、全6本0.492077がSpectralの改善に強く依存する点も明記。
  起動込み0.628911、初期panelとのbaselineの違い、shape/refleakの未解決事項を残した。
- 実装とraw data/logに照合して記述し、未追跡artifactを必要とする再現手順と参照先を
  明示した。相対リンク32件、コード例のPython/shell構文、表の平均時間・対応比・幾何平均、
  例示した多項式の恒等式を検査し成功。全480値を再集計し、保存済みbuild/script/測定dataの
  SHA256も一致した。新文書を含む末尾空白検査と`git diff --check`も成功した。
- 文書作成は完了。コード・build・計測条件の変更はなく、再ビルド・runtime test・性能測定の
  再実行はしていない。次に公開や既定値変更を検討する際のレビュー課題を文書末尾へ記載。
  GitHub投稿・push・PR変更は行っていない。

## 17. 継続目標：6本のmain比を改善（主指標は幾何平均、2026-09-14）

- この工程は当初、算術平均0.5以下を主指標として開始した。その後ユーザーが主指標を幾何平均へ更新したため、
  以下の算術平均は当時の診断値として保持し、最終採否とgoal判定には6本同重みの幾何平均を使う。
  前turnは英文ドキュメントの完成と数値監査で進捗あり。新工程は
  `36846454143`（ユーザーのreport commit）から開始し、残る`regions.md`のリンク差分を保持。
- 最終480値を再計算すると、script別の算術平均比はBPE0.9098765、B-tree0.9303600、
  DeltaBlue1.0002993、Hexiom0.9610843、Raytrace0.9469058、Spectral0.0184252。
  全6本の算術平均は0.7944918、block別は0.7981124/0.7920051/0.7927031/0.7951468。
- LLVM preflightで既存`/usr/lib/llvm-21`の4 toolsを再確認。保存済みmain/candidate/debugの
  binary・config・stencil hashは全て一致した。新実装前の比較binaryを保持する。
- 次は現candidateの5本のnative profileを取り直し、guard/dispatch・call frame・allocation・
  loop内部の費用を調べる。初期profileは古い版なので、新たな変更の根拠には再検証が必要。
  benchmark自体のアルゴリズムや入力は変更せず、runtimeの再利用可能な最適化を進める。

### Enumerate上の整数キー検索をchunk化

- 現candidateの5本を固定仕事量のperf/native probeで再調査し、全profileでlost samples0。
  `arithmetic-start-{btree,raytrace,hexiom,deltablue,bpe_tokeniser}`へ保存した。
  B-treeのget_positionは約145万回/処理のenumerate/unpack/tuple参照/整数比較を残していた。
- `_ENUM_LIST_INT_SCAN`をbuiltinオプション配下へ追加。最大64項目のexact tuple内のcompact
  int比較が同じloop分岐を取る間だけ進め、次の分岐・未対応値・枯渇は元iterationに任せる。
  enumerate/result tuple/元list/localsの参照関係を検査し、途中のdecrefがfinalizerを呼べる
  場合はchunk化しない。cached resultの共有・index cache境界・例外位置も保持する。
- 6比較×2 field位置、cache境界/空/短いlist、共有tuple、途中のIndexError、subclass比較での
  mutation、最後のitem参照を閉じた際のfinalizerの順序を追加検証。debug関連503 tests・
  1 skip、native region/opt/tier3/enumerate507 tests・9 skipsが成功した。
- native probeでは1,334,848 iterationsを119,610 chunksへまとめた。通常enum処理は
  120,981回、fallback16,302回、type guard失敗0。B-tree全体の3 blocks・各10値比較は
  前版比0.81676、main比0.76111（約49.1 ms）。90値を`enum-scan-btree-rows.json`に保持。
  source/build hashと差分を`enum-scan-{manifest,source-hashes}.json`、`enum-scan.patch`へ保存。
- 算術平均専用runner `screen-arithmetic.py`を作り、保存済み480値から開始点0.7944918を
  再計算した。まだ全6本の新測定はしておらず、全体目標の達成は主張しない。
- 次はHexiomの現profileで合計約12%を占めるlist membership/richcompareの経路を調べる。
  exact compact int同士を直接比較できる部分をJIT内へ展開し、最初の未対応要素では
  元の比較順序・mutation・例外を維持する。既存enum-scan binaryは固定して残す。

### List membershipの整数比較

- `_CONTAINS_OP_LIST_INT`をbuiltinオプション配下へ追加。exact listとcompact exact intの
  検索を直接行い、未対応型・要素はtrace内で元の`PySequence_Contains`へ渡す。それまでの
  exact int比較を再実行してもcallbackやmutationは重複しない。元のerror/cleanupを保持。
- 最初のテストは1 iterationを指定し、loop executorへ入る前に終了する2箇所でcounterの
  増分assertが失敗。ログを保持し、複数iterationと2回目の比較で発生するmutation/errorで
  実際に新uopのfallbackを検証する形へ修正した。値やcallbackの期待値は緩めていない。
- 既存enum scan matcherのbool判定を明示的な0/1へ正規化し、True側のbitが立つ配置でも
  正しい比較を選べるようにした。line monitoringからlocalsを観測・listを変更するテストも
  追加し、monitoring有効時にchunkが反復を飛ばさないことを確認した。
- debug関連431 tests、native region/opt/tier3/list/tuple515 tests・9 skipsが成功。
  Hexiom probeはcontains35,299 calls、68,631 integer elements、fallback0。3 blocks・
  全90値の比較は前版比0.89791、main比0.86325。`contains-hexiom-{rows,summary}.json`、
  `contains-{manifest,source-hashes}.json`、差分と比較用binaryを保存した。
- enum scanのnative loopでは整数比較のmask生成・判定が残っていた。次は6種類の比較を
  `replicate(6)`でstencil生成時に固定し、loop内の判定とregister pressureを削減する。
  最終的には全6本を算術平均runnerで測り、改善と回帰を含めて新しい現在値を確認する。

### Enum scanの比較をstencil生成時に固定

- `replicate(6)`で6比較を固定した。テストで`!=`のunordered bitがmatcherに混入する
  問題を検出し、整数比較のmaskを`&14`へ修正。bytecode DSLは`switch`を扱えず、
  if/else版は汎用stencilのjump tableから参照するlabelがassembly最適化で消えるため、
  bool式をbit演算で結合した。6 replicaと汎用版を含む通常stencil生成が成功した。
- debug関連448 tests、native region/opt/tier3/list/tuple515 tests・9 skipsが成功。
  nativeのscan loopはmask計算から単一の`cmp`/`jl`になり、probeの処理回数は前版と一致。
  B-treeの3 blocks・90値は直前版比0.98510、main比0.74612。全blockで改善した。
  `enum-compare-btree-{rows,summary}.json`とnative raw bytes/assemblyへ保存した。
- 次は全6本を2 blocks・各10値でscreenし、新目標の現在値を求める。並行してBPEの
  Counter更新に残る汎用`STORE_SUBSCR`の型・slot・descriptor条件を調べる。
- 2 blocks・240値の全体screenが終了し、checksumは全て一致。main比の算術平均は
  **0.742812**（block別0.740632/0.744992）。BPE0.907423、B-tree0.743405、
  DeltaBlue1.003341、Hexiom0.847332、Raytrace0.936952、Spectral0.018420。
  起動込み算術平均は0.767662。開始点0.794492から改善したが、目標0.5は未達。
  `enum-contains-suite-{rows,summary}.json`へ全生データと集計を保存した。

### 継承したdict代入への直接呼び出し（実装・検証中）

- Counterは`__delitem__`のoverrideにより`mp_ass_subscript`が汎用slotとなる一方、
  `__setitem__`はdictのdescriptorを継承する。この条件を型・slot・descriptorで確認し、
  `_STORE_SUBSCR_DICT_INHERITED`でversion一致時に`PyDict_SetItem`を直接呼ぶ。
  不一致は同じuop内の通常dispatch、cleanup/errorは元の`STORE_SUBSCR`を保つ。
- C拡張の独自slotを誤って迂回しないよう、typeobject側の小さい内部predicateで
  `slot_mp_ass_subscript`そのものを確認する。最適化対象型も既存watcherで監視する。
  値、削除override、異なるreceiver、base/subclassのmethod変更、hash例外、
  storeのhash中にmethodを変更するケースのテストを追加。再生成後の両buildが進行中。
- 最初のdebug検証で14 failures。生成された代入uopのcounterが0のままで、直前の既存
  `_GUARD_NOS_DICT_SUBSCRIPT`の最適化が`_GUARD_TYPE`へ置換され、receiverでなくキーを
  検査していた。dict store側にも同じ位置の問題があった。両方を新しい`_GUARD_NOS_TYPE`
  へ修正した。この修正は実験optionの外にも適用する通常optimizerのguard修正である。
- キーがreceiverと同じhashable dict subclass型でも、異なるreceiverをdict用uopへ
  誤って通さないread/write回帰テストを`test_opt`へ追加。テストhelperはcodeを分離し、
  大整数加算で先にexitするケースは意味論を、compact値は実際の代入counterを検査する。
- 再生成・build後、debug関連807 tests・4 skips、native region/opt/tier3/dict/collections
  674 tests・10 skipsが成功。次にBPEのnative coverageと前段階/mainとの性能を確認する。
- BPEのnative probeでは直接代入3,344,210 calls、fallback0。3 blocks・90値の元CLI比較は
  直前版比0.920758、main比0.831823、全blockで改善。guard修正と直接代入の組み合わせの
  効果であり、両者個別の寄与はまだ分離していない。`dict-store-bpe-{rows,summary}.json`、
  native証拠、source/build manifest、差分、比較用binaryを保存した。

### Exact positional initializerの引数配置（検証済み・今回は不採用）

- Raytraceのtraceには、Vector/Point生成のたびに`_CREATE_INIT_FRAME`から汎用の
  `_PyEvalFramePushAndInit`を呼ぶ経路が残る。`_CREATE_INIT_FRAME_POSITIONAL`をcall
  オプション配下へ追加し、0〜4個の明示的な引数とselfを直接frame localsへ配置する。
- 実際のinitializerとcleanupの2 framesは保持。引数数・kwonly/varargs/optimized flags・
  残りstack spaceを実行時に確認し、不一致は元のbinderへ渡す。locals初期化、cell/free
  variables、traceback、monitoring、None以外の戻り値チェックを既存のframe処理に任せる。
- 0〜4引数、defaultsを使うfallback、initializer変更、frame locals/closure、2回目の
  initializerでの例外と非None returnを追加検証する。現在は再生成を終え、buildへ進む。
- debug関連541 tests・8 skips、native region/opt/tier3/call/frame673 tests・17 skipsが成功。
  Raytrace probeは直接引数配置545,321 calls、fallback0。最初の3 blocks・90値は
  直前版比0.99095、main比0.93430。ただしblock別の直前版比は1.00309/0.97896/0.99094と
  小さく混在し、主効果を断定できないため同条件でもう3 blocks測定する。
- DeltaBlueの既存traceでは、list subclassの継承メソッド`append`のCALL位置でtraceが
  終了していた。method descriptorのreceiver guardがexact typeに制限されていることを
  確認。次工程で通常のdescriptor呼び出しと同じsubtype条件を検討し、overrideや不正な
  receiverのdispatch/errorを保ちながらtraceを継続できるか調べる。
- 追加3 blocksは直前版比1.01726。6 blocksの対応比は平均でほぼ同等であり、1 processで
  約6.5%遅い値も出た。性能上の利益を確認できないため、追加uop/counter/test/docを
  dict-store段階へ戻した。`init-frame.patch`、source/build manifest、比較用binary、
  全180値とnative証拠を保存し、不採用の試行を最終実装の成果へ混ぜない。

### 組み込みmethod descriptorのsubclass receiver（実装・検証中）

- `METH_O`、`METH_NOARGS`、`METH_FASTCALL`、`METH_FASTCALL|METH_KEYWORDS`の4 guardを
  `Py_IS_TYPE`から`PyObject_TypeCheck`へ変更。`Objects/descrobject.c`の`descr_check`と
  同じreceiver条件を使う。list subclassの`append/copy/index/sort`などが対象となる。
  このguardの拡張はTier 1とTier 2に適用し、実験optionで切り替えるuopではない。
- callableのdescriptor型・引数形式・selfの有無のguard、既存call本体、cleanup・error・
  periodic checkは維持。abstract interpreterによるguard除去の条件は広げていない。
  `CALL_LIST_APPEND`は引き続きexact list専用で、subclassはdescriptorのcall本体を使う。
- bound/unbound呼び出しで4形式のuopまでtraceが続くこと、戻り値とreceiverの変更、
  method override、不正なreceiver、2 iteration目のIndexErrorを追加検証する。
  initializer試行の取り消しとともにTier 1/Tier 2/optimizerの生成物を再生成した。
- debug関連1,009 tests・28 skips、native region/opt/tier3/call/opcache/list/collections
  876 tests・34 skipsが成功。DeltaBlueの3 blocks・90値は直前dict-store版比0.955919、
  main比0.965710で、全block改善した。`descriptor-subclass-deltablue-{rows,summary}.json`
  に保存。この値にはTier 1でのguard miss解消も含まれ、native専用の利益とはしない。
- 元のCLIと同じ3 warmups・1 loopのprobeでは、DeltaBlueのexecutorは3つしかなく、
  計測callで3つが新しく観測され、call region counterは0だった。以前の1500 loopsの
  profileとはwarmup状態が異なる。長時間probeのcoverageを元CLIに帰属しない。
  次は全6本のscreenを更新し、短いworkloadの実際のJIT到達範囲を調べる。
- 2 blocks・240値の全体screenはmain比算術平均 **0.729919**、起動込み0.755748。
  BPE0.829947、B-tree0.754272、DeltaBlue0.965772、Hexiom0.861511、Raytrace0.949566、
  Spectral0.018446。checksumは全て一致。`descriptor-subclass-suite-{rows,summary}.json`
  を保存した。目標0.5には未達。Raytrace/B-treeの小さい変動は対応比較の主効果と分ける。
- 3 warmups・10 values・1 loopのDeltaBlue coverage probeでは、前半8 samplesのcall
  region counterは0、最後の2 samplesで48/99だった（計11 executors）。元CLIを変えずに
  既存JIT policy変数のloop/resume閾値を比較し、compile費用と実行範囲を別途診断する。
  `PYTHON_JIT_STRESS`は使わず、policy試行の値を現在の目標達成値へ混ぜない。
- loop/resume閾値を既存のpolicy変数で1008/4094、502/2046、250/1020へ変え、defaultと
  4 blocks・160値で比較した。default比の算術平均は1.01763/1.02147/0.99042、起動込みは
  0.98991/1.00938/1.01149で効果が安定しない。policyは変更しない。
  `jit-policy-deltablue-{rows,summary}.json`に全値を保存した。
- 現段階の採用対象はenum scanと比較replica、list integer membership、dict receiver
  guard修正、継承dict代入、method descriptorのsubtype guard。initializer binder短縮と
  閾値試行は採用しない。次はRaytraceのallocation/frameコストを減らす実装を調べる。
  constructorのbodyを省く場合も新しいobject identity、監視・例外・GC callbackの位置と
  引数所有権を保持する必要があり、単なるunique instanceの再利用は行わない。
- 採用した段階をまとめる前に、全6オプションONでfloatの丸め/trap/flags576ケースと
  特殊値56ケースを再検証し、全てbit一致した。5つの生成物も再生成してbyte一致を確認。
  差分空白検査と変更したPython testの設定相当のRuff検査（F401/F811）も成功した。
  GitHub投稿・push・PR変更は行っていない。現在値と未完了の目標を保持して次へ進む。

### 単純なconstructorのframe省略（実装・検証中）

- ローカルcheckpoint `e2fe92a4b59`（tree `acb110a08b10de80114cf15f14ca419073fd1c37`）
  に採用済みの変更を保存した。最新screenの算術平均0.729919を比較基準として保持する。
- `_CALL_CLASS_ATTRIBUTES`を試作。1〜4個の引数をそれぞれ異なるinline属性へ一度だけ
  代入しNoneを返すinitializerの全traceを対象に、毎回新しいobjectを確保して直接代入する。
  型・function version、引数形式、stack容量、instrumentation状態を確認する。
- allocation後にGCなどのpending workが生じた場合、元と同じinitializer/cleanupの
  2 framesを作り、属性代入前のinitializer入口へ戻す。単純なobject再利用は行わない。
  このfallbackが生成器の固定cache出口条件に合わず、条件付きTier 1退出のcache flushを
  分離した。loop中の引数所有権移動も明示的なlocal経由とし、全5生成物の再生成が成功。
- 両buildを開始し、identity・属性順序・code変更・allocation失敗の回帰テストを追加中。
  まだ新uopの動作や性能を検証していないため、採用済みの高速化には数えない。
- 基本テスト成功後のRaytraceでクラッシュを検出。call regionだけでも再現した。
  gdbと最適化後traceから、省略した`_CREATE_INIT_FRAME`が設定していたreturn offsetを
  fast pathが保存していないことを特定。直後のreturn guardが誤ったCALLへ戻っていた。
  fast pathでもoffsetを設定し、constructor→method→callerの入れ子returnを回帰テスト化。
- 修正後はdebug関連1,369 tests・13 skips、native関連1,283 tests・21 skipsが成功。
  GC thresholdを下げたテストで実際のframe復元counter増加、callbackから見える
  initializer引数・未初期化属性を確認。monitoring、code変更、setattr変更も検証した。
  debugの元Raytrace CLIとnative coverage probeも成功し、nativeで142,034直接生成、
  guard exit0・frame復元0を観測。次に直前版/mainとの元CLI対応比較で採否を判断する。
- 3 blocks・90値のRaytrace比較は直前版比0.967780、main比0.926102で全block改善。
  `class-attributes-raytrace-{rows,summary}.json`、差分・manifest・比較用binaryを保存した。
- 未最適化のclass traceの多くはcleanup trampolineの最終RETURN直前で終了していた。
  この終端を認識し、frameを省いた後は元のcallerのCALL直後へdynamic exitする拡張を追加。
  別のcallerへ戻るテストと、所有された引数のweakref/finalizerテストを追加して両build成功。
  function入口のtraceを確実に作るテストはCのmap経由でwarmupする（Python loopでは
  callerへinlineされ、対象function自体にexecutorが作られないため）。関連テストを再実行中。
- 拡張後はdebug関連1,371 tests・13 skips、native関連1,285 tests・21 skipsが成功。
  native直接生成は277,405 callsへ増え、guard exit0・frame復元0。3 blocks・90値の
  Raytrace比較は直前constructor版比0.979577、main比0.886277で全block改善した。
  `class-exit-raytrace-{rows,summary}.json`、native bytes/asm、差分・manifest・binaryを保存。
  whitespaceと変更Python testのRuff F401/F811も成功。全6本の2-block screenへ進む。
- 全6本・2 blocks・240値のscreenはmain比算術平均 **0.721664**
  （block別0.721441/0.721886）、起動込み0.749202。BPE0.833229、B-tree0.753662、
  DeltaBlue0.969658、Hexiom0.859987、Raytrace0.895014、Spectral約0.018441。
  checksumは全て一致。`class-exit-suite-{rows,summary}.json`に保存した。
  前screen0.729919から改善したが、算術平均0.5の目標は未達である。
- 次はHexiomに残る`self.cells[i]`や`len(self.cells[i]) == constant`の短いcalleeを調べる。
  exact list・compact index・属性type version・builtin lenのbindingを確認し、例外や
  callbackが必要な場合に元CALLへ戻せる範囲でframe省略を検討する。現在のconstructor
  実装を比較基準として保存してから着手し、未検証の候補を今回の性能値へ混ぜない。

### 属性listの短いcallee（実装・検証中）

- constructor段階をローカルcommit `186bc0325f5`（tree
  `cba3e2b770b234ffe876c24502662d3ca244a410`）へ保存した。新しい試行とは区別する。
- `_CALL_PY_LIST`を試作。cached attributeのexact listをcompact indexで読み、要素を
  返すか、その組み込みlengthを小さい定数と比較する全calleeを96 uops以内で認識する。
  関数・属性type version、index範囲、len binding、globals keys versionとinstrumentation
  を確認する。subclass・missing属性・範囲外・ユーザーlengthは元CALLへ戻して通常処理する。
- 結果を保有してから既存と同じ逆順で引数を解放し、code lifetimeとreturn offsetを保つ。
  全生成物を再生成し両buildを開始した。これから実際の適用、fallback、例外、binding変更、
  参照所有権をテストし、Hexiomのnative coverageと対応比較で採否を判断する。
- 最初の5 testsでは、copied builtinsの`len`変更だけが失敗した。切り分け用scriptは
  constructor checkpointと固定mainの両方でも失敗（1を42へ変更しても1を返す）。
  `_LOAD_GLOBAL_BUILTINS`の定数化が常に`interp->builtins`を参照・監視する一方、コピーは
  keys versionを共有でき、値の変更をそのwatcherが検知できないことを確認した。
- custom builtinsでは元のloadを保持し、定数化した標準builtinsにはidentity guardを追加。
  同じfunction/code versionを持つ別functionからの呼び出しにも実際のmappingを検査する。
  新しいlist callもcalleeのbuiltins identityを確認する。コピーの値変更と、同一versionで
  異なるbuiltinsのfunctionを渡す通常optimizer回帰テストを追加し、再build中。
  このguard修正は実験optionの外にも適用されるため、その性能効果と副作用も確認する。
- 修正後、debug関連1,538 tests・21 skips、native関連1,452 tests・29 skipsが成功。
  list callのindex/length callback、2 iteration目のIndexErrorとcallee traceback、slots、
  globalsのlen差し替え、monitoring、結果のweakref lifetime、同一versionでcustom builtinsへ
  差し替えるケースを確認した。native Hexiomで12,421 list calls、guard exit0を観測。
- 3 blocks・90値のHexiom比較はconstructor版比0.977255、main比0.845026で全block改善。
  builtin guard修正を含む段階全体の比較である。`call-list-hexiom-{rows,summary}.json`、
  native証拠、`call-list.patch`/manifest/比較用binaryを保存した。
- 関数入口から始まるtraceにはframe省略を適用できず、通常のlen consumerが22,181回
  残る。次はlist subscriptと直後のlen比較を直接融合し、関数frameを保ったまま中間参照と
  dispatchを減らせるか調べる。list解放でfinalizerが起きる場合は従来の順序を維持する。
- `_LEN_SUBSCR_LIST`を追加。list subscriptから定数/ローカルとのlen比較までを融合する。
  exact listとcompact index、builtin len、組み込みlength、右辺intを確認し、共有/borrowed
  listだけを直接処理する。唯一所有のlistは、indexing後のlist解放で他の要素のfinalizerが
  対象要素を変更できるため元subscriptへ戻す。関数frameを省く必要はない。
- 6比較演算子、定数/ローカル右辺、正負indexとlist/tuple/str/bytes/dict要素を検証。
  user length callbackと、list解放時のfinalizerが対象listへappendしてからlenが実行される
  ケースもfallback counter込みで成功した。両buildを終え、関連テストを再実行している。
- debug関連1,541 tests・21 skips、native関連1,455 tests・29 skipsが成功。
  native Hexiomで18,293 subscript/len融合、12,421 list calls、両guard exit0を観測。
  3 blocks・90値の比較は直前list-call版比0.988643、main比0.833381で全block改善。
  `len-subscript-hexiom-{rows,summary}.json`、native bytes/asm、差分/manifest/binaryへ保存。
  constructor後のbuiltin guardも含め、全6本の2-block screenで影響を確認する。
- 全6本・2 blocks・240値のscreenはmain比算術平均 **0.714387**
  （block別0.713392/0.715382）、起動込み0.744414。BPE0.829302、B-tree0.749773、
  DeltaBlue0.974704、Hexiom0.833954、Raytrace0.880046、Spectral0.018540。
  checksumは全て一致。`len-subscript-suite-{rows,summary}.json`へ保存した。
  前screen0.721664から改善したが、目標0.5は未達。Hexiom以外の小さい変動を
  list融合の個別効果とは主張せず、段階全体のscreen結果として扱う。
- 全6オプションONでfloatの丸め/trap/flags576ケースと特殊値56ケースも再確認し、
  mismatchは0。`len-subscript-fenv.json`と`len-subscript-specials.json`へ保存した。
  `Tools/jit/regions.md`にcallee/list/len融合とbuiltins guardの意味論・fallbackを追記した。
- 次はBPEの既存keyのread→整数加算→storeに残る二重lookupを調べる。単に要求keyが
  builtinというだけでは、衝突した他のkeyの`__eq__` callbackを省略できない。
  直接更新を試す場合は、lookupで実際に比較するkeyも検査し、不明な比較、missing、
  dict watcher、unsupported slotは元の処理へ戻す設計とする。allocation errorの位置、
  値・key・dictの参照解放順序も先に証明し、現在の検証済み段階を比較基準に保持する。

### 既存bytes-pair keyの整数更新（実装・検証中）

- 検証済み段階をローカルcommit `9e96c11b1ba`（tree
  `fc7a71de13576da55248f9e2c11d483f23bf5f85`）へ保存。新しいBPE profileはlost samples0、
  dict lookup6.66%、insertdict1.03%、tuple deallocation4.00%、tuple allocation2.58%。
  `len-subscript-bpe-profile.*`にnative coverageとperf結果を保存した（timing結果とは別）。
- `_DICT_PAIR_INCREMENT`を試作し、同じdict/keyのread、非負小定数のint add、継承した
  dict代入までを認識する。既存のslot/type version guardとruntimeのidentity検査を保つ。
- 内部lookupはexact tuple-of-two-exact-bytesに限定。hashが衝突したstored keyも同じ
  形式かを確認し、不明な比較なら元のGETへ戻す。missing、非compact値、split table、
  dict watcherもfallback。通常のtuple hash cacheとdictのprobe手順を使う。
- callback/GCのない区間で既存entryへ新しいintを置き、2回目のlookupを省く。
  int allocation失敗は元のADD、代入後のcleanupは元のSTOREの位置に帰属させる。
  全生成物の再生成が成功し両buildを開始した。これからcollision callback、missing、
  method変更、watcher、allocation error、参照所有権を検証する。まだ性能上の成果に含めない。
- 新規8 testsがdebugで成功し、関連7 test filesもdebug884 tests・4 skips、native
  798 tests・12 skipsで成功した。allocation時の共通error stubが命令位置を上書きするため、
  fused uopのerror targetにも元ADDのoffsetを設定した。tracebackの命令位置を検証済み。
- native BPEの1 sampleでは2,259,345回の直接更新と1,084,865回のguard exitを観測した。
  native codeを含むexecutorと全counterを`dict-update-bpe-native.*`へ保存した。
  guard exitが多いため、適用回数だけでは改善とは判断しない。固定main・直前版・試作版を
  順序交替で3 blocks・90値比較中。missing keyでTier 1へ戻る費用も採否に含める。
- 最初の3 blocksは直前版比0.999325/0.998396/0.992477、段階比較の幾何平均0.996728、
  main比0.831926。全block改善だが効果は小さい。全90値を`dict-update-bpe-*`、
  ソース差分・manifest・比較用binaryを`dict-update-deopt*`へ保存した。
- 次はguard失敗をDEOPTから通常のEXITへ変え、fallback先の元GET以降をside traceに
  できるか調べる。意味論のfallback位置・入力は同じ。missingを勝手に0へ置き換えず、
  元の`__missing__`・加算・代入を使う。guardが同じ融合へ循環する場合もcoverageで確認する。
- EXIT版もdebug884 tests・4 skips、native798 tests・12 skips成功。native executor 26は
  元GET・ADD・STOREのside traceだったが、入ってきたstackの型情報がないためSTOREは
  汎用処理のままだった。直接更新/guardの件数はDEOPT版と同じ。`dict-update-exit*`へ保存し
  3-block比較中。このcoverageを踏まえ、汎用STORE_SUBSCRにもreceiver型のrecordを追加する。
- side traceでも継承dict代入を選べるようにする一方、融合は同じtrace内にCOPY 2が2つ
  ある場合に限定する。失敗GETから始まるtraceが再び同じ融合guardへ戻る循環を防ぐ。
  元の型・slot version確認と通常setterへのfallbackは保ち、benchmark完了後に再buildする。
- EXIT版の3 blocks・90値はDEOPT版比0.997229/0.992173/0.996069、段階比較の幾何平均
  0.995155、main比0.831828。全block改善だが依然として小さい効果である。
  `dict-update-exit-bpe-{rows,summary}.json`へ保存。receiver記録を含む版の再生成へ進む。
- 初回の新規テストは失敗した。bytecode macroの変更にはuop metadataだけでなく
  `opcode_metadata_generator.py`によるtrace展開表の再生成も必要だった。
  C/Pythonのopcode metadataを再生成し、STORE_SUBSCRにrecordが含まれることを確認して
  再build中。衝突比較回数のテストも、hash次第でprobeが同じentryを複数回訪れるため、
  固定17回ではなく同条件の通常read/add/writeが発生させるcallback列と比較するように修正した。
- debugのrecord-slot assertionで、record consumerの表も更新が必要と判明した。
  `record_function_generator.py`はdefault出力名がbuildの入力名と異なるため、
  `-o Python/record_functions.c.h Python/bytecodes.c`を明示して再生成する。
  不完全な表で通ったnativeテストは検証済み結果に数えず、両buildを修正後に再検証する。
- `optimizer.c`がrecord表をincludeするのにMakefileの依存関係が欠けており、表の修正後も
  古いoptimizer.oが残って同じassertionになった。`Python/optimizer.o`の前提に
  `Python/record_functions.c.h`を追加し、incremental buildで確実に反映されるよう修正する。
- 正しいrecord表と依存関係で再build後、追加分を含むdict関連15 testsが両buildで成功。
  missing keyを4 batches繰り返し、callback列・値とside traceの直接store counterも確認した。
  関連9 filesはdebug1,041 tests・4 skips、native955 tests・12 skipsで成功。
  opcode/disassemblyのテストも含む。再生成手順の注意点は`AGENTS.md`に追記した。
  最終試作版のBPE native coverageと、融合導入前のlen-subscript版との対応比較へ進む。
- 最終版のnative BPEでは直接更新2,259,345回、side traceでの継承dict直接代入1,084,865回、
  通常setterへのfallback0を観測した。side traceは同じ融合を繰り返さず、元GETとADDを保持。
  native bytes/counters/環境・binary/extension hashは`dict-update-record-bpe-native.*`に保存。
- 全6オプションでfloatの丸め・trap・flags576ケースと特殊値56ケースを再確認し、
  mismatch0。8つの関連生成物もsourceからbyte単位で再現できた。
  `dict-update-{fenv,specials}.json`へ保存し、融合導入前の版との3-block比較を開始した。
- native asmのcall tableを、recordされた`PyZip_Type`と`zip_next`から求めた同一load biasと
  binary symbolsで解決した。成功経路は専用lookup1回と`PyLong_FromLong`1回の後、entryを
  直接書き換える（`dict-update-record-calls.json`、executor12のasm）。
- ただしgeneratorはcallback-freeなlookupをまだescaping callと扱い、前後でoperand stackを
  公開・再読込していた。このhelperをnon-escaping一覧へ追加し、旧exact intの解放には
  既存のspecialized closeを使う。dict自体の最終解放は引き続き通常のescaping cleanupを保つ。
  変更前版は`dict-update-record*`へ保存済み。対応比較完了後に再生成・再build・再検証する。
- receiver記録版の3 blocksは導入前比0.983848/1.003740/0.981164、段階比較の幾何平均
  0.989533、main比0.817631。1 blockで小さな逆転があり、安定した改善とはまだ判定しない。
- debug allocation probeもescapingと扱われていた。`PyErr_NoMemory`がpreallocated例外を
  設定する実装を確認し、既存raised exceptionがない契約をdebug assertにしてnon-escaping
  とする。これはint/float/lenの生成コードにも影響するため、dict単独の改善とは主張せず、
  全関連テスト・float flags/特殊値・全6本を再検証して採否を判断する。
- escape分類修正後もdebug1,041 tests・4 skips、native955 tests・12 skipsが成功。
  追加のfloat診断では、unique/shared積和・積差について、符号付きゼロ、infinity、異なる
  quiet/signaling NaN payloadを組み合わせた1,372ケースのbit列が通常JITおよびC演算と一致。
  `check-fusion-specials.py`と`dict-update-escape-fusion-specials.json`へ保存した。
- escape分類版のrange fenv576ケース・特殊値56ケースも一致し、8生成物のbyte単位の再現も
  成功。BPEの直接更新/side-storeの件数は維持できた。この検証済みbinaryとsource差分を
  `dict-update-escape*`へ保存し、融合導入前との対応比較を実行中。
- 最終の3 blocks・90値は導入前比0.976389/0.971948/0.981247、段階比較の幾何平均
  **0.976521**、main比**0.812703**。全block改善した。dict更新、side traceのreceiver記録、
  escape分類修正を合わせた効果として採用する。`dict-update-escape-bpe-{rows,summary}.json`
  に全値とchecksum一致を保存。全6本への影響は次のfloat拡張と段階を区別して確認する。

### 所有されたfloat operandの積和・積差（実装・検証済み、全体効果は小さい）

- 最新native Raytraceの`Vector.dot`にも、属性loadが所有するfloatの積のboxingが残る。
  既存のborrowed-factor融合では対応せず、通常のmultiplyとunique accumulatorへのaddが
  別uopになっていた。`dict-update-escape-raytrace-native.json`へ現状を保存した。
- unique-left accumulatorの場合に、片方または両方のfactorがownedでも融合するuopを追加。
  二つのfactor参照を出力として返し、元の`_POP_TOP_FLOAT`/`_POP_TOP_NOP`を同じ順序で残す。
  exact floatの解放はPythonを呼ばないため、積とupdateを先に計算してもcallback順序を
  変えない。公開されたfloatは再利用せず、既存のvolatile binary64境界も保つ。
- `float_owned_entries`を追加し既存unique counterにも含める。borrowed経路のuopは保持する。
  現在のBPE比較は保存した旧binaryで最後まで行い、終了後にこの拡張をbuild・検証する。
- 初回はnativeのfloat関連21 testsと、ownedの3形態×積和/積差の特殊値2,058ケース、
  fenv288ケースが成功した。debugは新規テストのNaN bit比較3つが失敗した。
- 切り分け診断で、debugの通常Tier 2自体にC演算と異なるNaN payloadが378ケースあり、
  新融合と通常Tier 2の間にも198ケースのpayload差があった。有限値・signed zeroと
  fenv flagsには差がない。nativeでは通常JIT/C/融合の全bit列が一致している。
- 計画の検証基準（「有限値は必要に応じbit比較、NaNは適切な分類で比較」）に合わせ、
  通常の回帰テストは既存floatテストと同じNaN分類比較に修正する。debugをbit完全一致と
  主張せず、payload差のraw rowsを`float-owned-specials-debug.json`に保持する。
  演算順序とvolatileの丸め境界を変更する根拠はなく、数値処理は変更しない。
- 関連9 filesはdebug1,044 tests・4 skips、native958 tests・12 skipsで成功。
  quiet/signaling NaNを含むfenv検証を432ケースへ広げ、両backendでflagsと値/NaN分類は一致。
  nativeは特殊値2,058ケース・fenv432ケースともbit一致。debugのpayload差は特殊値198ケース、
  fenv48ケースとして記録し、有限値やflagsの不一致とは区別している。
- native Raytraceではowned経路844,762回を確認し、unique融合総数は170,153→1,014,915回。
  executor4の0x65e/0x869にmulsd、volatile store/loadを挟んで0x66f/0x87aにaddsdがあり、
  FMAへ縮約されていない。`float-owned-raytrace-native.*`へnative codeとcounterを保存した。
- 3 blocks・90値のRaytrace比較は直前dict/escape版比0.974762/0.986479/0.969464、
  段階比較の幾何平均 **0.976876**。全block改善した。main比は0.833477だがmain自身の
  block間差が大きいため、個別効果の判断には直前版との対応比較を用いる。
  `float-owned-raytrace-{rows,summary}.json`に全値とchecksum一致を保存した。
- 次は固定main・dict/escape版・owned-float版の3種類を全6本で同時にscreenする。
  入力と元CLIの3 warmups・10 values・1 loopは同一、2 blocksで360値。元の2-build
  screenと分けて、段階ごとのmain比算術平均とowned拡張の追加効果を保存する。

- 全6本・2 blocks・360値の三者比較が完了し、全checksum一致、除外0。
  dict/escape版のmain比算術平均は **0.712614**、owned-float版は **0.712403**
  （block別0.714420/0.710387）。目標0.5は未達。
  owned-float版のscript別main比はBPE0.834298、Btree0.749783、DeltaBlue0.977292、
  Hexiom0.834151、Raytrace0.860312、Spectral0.018585。
- owned拡張の直前版比はRaytrace0.971263と両block改善する一方、BPEは
  1.036386/1.016247（平均1.026316）で両block回帰し、全体の効果はほぼ相殺された。
  BPEでの回帰原因は未特定。float uopの適用差、native code、perfを調べ、ソース変更の
  直接効果とbuild/layout差を区別する。都合の悪い値を除外したり、全体改善と主張しない。
  全結果は`float-owned-suite-{rows,summary}.json`に保持する。

### 隣接ペアを比較するリスト走査（設計・coverage調査）

- 次の候補は、`i < len(word)-1`のループで非一致の隣接ペアに対し
  `new_word.append(word[i]); i += 1`だけを実行する経路のbounded scan。
  既存のlist-pair融合でも比較以外のload/len/append/incrementが毎回残っている。
- 追加のallocationやerror位置変更を避けるため、exact listの既存allocated容量内、
  exact bytes同士の比較、small-int index、最大64回に限定する案を検討する。
  容量不足・一致・未対応値では元のiterationへ戻し、通常appendの再確保と例外を保持する。
  benchmarkのアルゴリズムや入力、オブジェクトの公開されたidentityは変更しない。
- まず元のbackedgeとheaderのlen/builtin guard、append receiverとindex localの対応を
  traceとbytecodeから証明できるか確認する。まだ実装済み・性能改善として数えない。

- 検証済みdict/owned-float段階をローカルcommit
  `00fcaf8462ddc60fc48586b65fb8ad5c271e95fa`、tree
  `72a3d4f54cfabfcc97347fe16aad795f4b905235`へ記録した。リモート操作はなし。
- BPEのowned-float段階の診断ではfloat適用0、主要counter・34 executors・2,020 uopsが
  直前版と一致。ABBAの4回perf stat（元CLI、起動/warmup込み）では全group稼働率99%、
  before cycles139.487/139.551G、after138.751/139.627G、instructionsは458.481～459.047G。
  約2.6%の回帰はこの診断では再現せず、原因は未特定のまま。生データは
  `float-owned-bpe-perf-*`。診断値で元の時間測定を置き換えない。
- `_LIST_PAIR_APPEND_SCAN`を実装した。元list guardを置換し、同一localのlist/index、
  exact bytes pair、異なるexact output list、cached small-int範囲、既存capacityを確認する。
  比較後に通常iterationを1回残すため、末尾の有効なペアはscanで消費しない。
- suffixがpair非一致→append(word[i])→i+=1→backedgeだけであることを確認する。
  side traceでもbackedgeの元bytecode（ENTER_EXECUTOR/EXTENDED_ARGを含む）から
  `i < global(word)-1`と同じbody開始位置を検証する。実行時にglobalがcanonical lenへ
  解決されることも確認する。general-key globals/builtinsは未対応とし、名前lookupが
  衝突keyのPython callbackを呼ぶ可能性を排除する。
- 両buildで新規6 testsが成功。空/短いlist、64/255境界、途中一致、負の開始位置、
  outputとsourceのalias、bytes/list subclass callback、len差し替え、参照数、類似する
  未対応ループを検証した。native BPEのcoverageを採取し、追加の例外/side-trace検証へ進む。

- 初期版のnative BPEで956,013 chunks・1,672,794 skipped iterationsを確認した。
  len/tuple比較の回数も正確に同数減り、dict更新とside-storeのcoverageは維持された。
  `pair-scan-initial-bpe-native.*`へ保存。短いchunkと2,883,833 missesの費用を含めて測る。
- 生成コードが`Py_MIN`/`Py_MAX`と`Py_SET_SIZE`をescapingと誤分類していた。
  これらはC式・field書き込みだけでPythonを呼ばないためnon-escapingへ追加した。
  新scanのHAS_ESCAPESと余分なstack公開がなくなった。既存enum scan等にも影響するので、
  builtin/optimizer/generator/list/dict関連を両buildで一括再検証する。
- 途中の比較例外に対するpartial outputとframeのindex、append callbackによる入力listの
  短縮、hot branchが変わった後のoutgoing executorを追加検証中。入力・CLIは変更していない。

- escape分類修正後、関連10 filesはdebug **1,124 tests・4 skips**、native
  **1,038 tests・12 skips**で成功。差分内の既存executor変更はenum scanの余分なstack公開の
  除去であり、float演算コードには変更がない。
- nativeのallocation failure診断で、capacity8・size5のoutputにscanで2反復進んだ後、
  元appendのCALL（offset202）でMemoryErrorを観測した。frameのi=3、output size8で
  prefix5個と成功した3個の追加が保持された。`check-pair-scan-oom.py`と
  `pair-scan-oom-native.json`へ保存した。
- 最終prototypeでも956,013 chunks・1,672,794 skipped iterationsを維持し、ホットなside
  executor28にもnative scanを確認した。34 executors、native code合計167,936 bytes。
  `pair-scan-bpe-native.*`と`pair-scan-{manifest.json,.patch}`に記録し、直前owned-float版との
  固定mainを含む3-block・90値比較を開始した。まだ性能採用の判断はしていない。

- native asmではscan内のbytes比較が汎用immutable比較helperへのcallになり、未使用の
  unicode/float/int分岐まで含んでいた。また末尾近くの不成立を、複数local・tuple・outputの
  guard後に判定していた。次の版では位置/残り長を先に判定し、exact bytes比較を明示的に
  inlineする。現在の3-block比較は保存済みの現行binaryで完了させ、再生成/buildはその後。
- 現在のsmall-int cache上限は`_PY_NSMALLPOSINTS=1025`。従来の256付近に加えて
  1023～1026と1100のlistでも検証するようテストを広げた。copied builtinsのlen差し替えと
  general-key globalsにある衝突callbackの列も追加検証する。

- 最初の3 blocks・90値は直前owned-float版比 **1.005453/0.996064/1.006680**、
  段階比較の幾何平均 **1.002721**、main比0.816504。全checksum一致、除外0。
  この版を高速化成功とは判定しない。`pair-scan-bpe-{rows,summary}.json`へ保存した。
- 予定していた早い不成立判定とbytes専用inline比較を含む版をこれから再生成・buildする。
  原因仮説は追加guardと汎用helperの費用。追加比較も事前に3 blocks・90値とし、
  引き続き導入前のowned-float版を対照にする。

- inline版の初回検証では、追加したFunctionTypeのfixture2つがデフォルト引数をコピーして
  おらずTypeErrorで失敗した。`argdefs=run.__defaults__`を指定して修正し、追加11 testsが
  両buildで成功した。allocation failureの診断もdebug/native両方で同じi=3・成功prefixを確認。
- 修正後にtest_opt_regions全127 testsを両buildで再実行し成功（native7 skips）。
  先の10-file実行で成功した残り9 filesと合わせ、現在の関連範囲はdebug1,126 tests・4 skips、
  native1,040 tests・12 skips。8生成物のbyte単位の再現、Ruff、diff --checkも成功した。
- inline版のnative coverageは前版と同数。executor28の0xe8/0xfcに位置の早期判定、
  0x371/0x381にbytesのidentity/長さ比較があり、scan中の汎用immutable helper呼び出しが
  消えた。bytesデータ比較のmemcmpは残る。native bytesとmanifestを`pair-scan-inline*`へ保存。
- 最終判断用の比較は全6本に広げ、固定main・導入前owned-float版・inline版の3種類、
  3 blocks・540値で実行中。BPEについて事前に定めた3 blocks・90値もこの中で取得する。
  重いbuild/test/probeはタイミング中に走らせない。

- 全6本・3 blocks・540値の比較が完了し、全checksum一致、除外0。
  直前owned-float版のmain比算術平均 **0.706593** に対し、今回版は **0.704639**
  （block別0.710845/0.701429/0.701643）。過去screenの0.712403との差を今回の効果とはしない。
  目標0.5は未達。
- 今回版のscript別main比はBPE0.813254、Btree0.740443、DeltaBlue0.969030、
  Hexiom0.834058、Raytrace0.852363、Spectral0.018683。
  直前版比はBPE0.993987（3 blocksとも改善）、Btree0.991347（3 blocksとも改善）、
  DeltaBlue0.997392、Hexiom0.993405、Raytrace1.009182、Spectral0.999399。
- Raytraceは1.026929/1.000491/1.000127と全blockで遅く、最初のblockの差が特に大きい。
  これも含めた全6本の直前版比算術平均は0.997452で、全体効果は小さい。
  BPEのscanと既存enumのescape分類修正を組み合わせた段階として記録し、特定の変更だけの
  効果とは主張しない。全値は`pair-scan-inline-suite-{rows,summary}.json`に保持する。
- 次はBtree等の短いメソッドのtraceを現在のbinaryで確認する。以前のBNode.is_fullの
  native traceでは、constant folding済みの値にもload/rotate/popが残り、lenのboxingと
  比較、callee frameを別々に処理していた。残っている仕事を確認してから次の対象を決める。

- BPE/Btreeの3 blocksすべての改善と、回帰を含めた全体の小さな改善を根拠に、
  scan/escape分類の段階を現状として保持する。Raytraceの回帰原因は未特定で、記録を残す。
  source/test/docをローカルの次のチェックポイントへ保存し、次の変更と分離する。


### 畳み込み後の定数とlen predicate（実装開始）

- scan段階をローカルcommit `5c3db9c7a3af5646922e57bd2076e8464cd16425`、tree
  `e3402aae7350d897430a1ae16980e6162770b792`へ保存した。リモート操作なし。
- 現在のBtree probeでもBNode.is_fullに、畳み込み済みの2/16/32/1/31のloadとrotate/pop、
  単独CALL_LEN、比較、callee frameが残る。`pair-scan-inline-btree-native.json`に保存した。
- まず参照の取得と解放の間に効果のないlocal load/pop、およびimmortal定数だけの
  folded operandsのrotate/popを除去する。新しい照合はCHECK_PERIODIC・CHECK_VALIDITY・
  任意callをまたがず、通常の不要uop除去により不要と判明したcheckだけを取り除く。
- その後、abstract interpretationで初めて定数になった比較値をCALL_LEN_CONSUMERへ
  融合する。条件が揃えば既存のCALL_PY_LISTを属性list自体のlen predicateにも広げ、
  元のfunc/type/builtins/recursion/instrumentation guardと逆順cleanupを保持する。

- 設計を限定した。任意のCALL_LENの後でcleanupを動かすと、finalizerによるclass属性変更や
  validity exit時のstack形に影響し得る。この段階では単独のCALL_LENを後から融合せず、
  owner引数が属性listを保持している短いcallee全体の融合に限定する。
- `remove_folded_constant_traffic`を追加し、short-local replicaの未使用load/popと、
  2つのimmortal operandを捨てるRROT_3/popを除去する。既存の不要check除去を間に挟むが、
  新しい照合自体はCHECK_VALIDITY/周期チェックをまたがない。
- CALL_PY_LISTの未使用argument selector7を属性list自体の長さ比較に割り当てた。
  既にCALL_LEN_CONSUMERになった場合と、定数fold後のCALL_LEN→constant→int比較に対応。
  新しいcounter fieldや新uop IDは増やさず、既存call_list_entriesに含める。
  比較6種類、slot/dict属性、class/function変更、__len__のcallback/例外、copied builtinsを
  回帰テストとして追加し、両buildを更新中。

- 初回の新規テストではliteralのlen predicateは融合したが、class属性から計算する版で
  executorの適用確認が失敗した。先に既存の不要check除去を行う順番へ修正すると、
  slotsのunused local load/popと2段のconstant fold cleanupを除去できた。
- instance dictを持つownerでは、class属性のshadowingを検出するmanaged-values guardが
  残る。このguardを無条件に消さず、folded-bound融合は現在のguard-freeなslots経路に
  限定する。literal-bound融合はslot/dict両方を対象とし、instance属性でclass値を
  上書きした場合に通常経路が正しい値を返すテストも追加した。
- 新規5 tests（比較6種×literal/folded×slot/dictのsubtestsを含む）が両buildで成功。
  class/function変更、__len__中のclass変更と例外のcallee frame、copied builtinsも成功した。
  関連10 filesの一括検証へ進む。

- 関連10 filesはdebug **1,131 tests・4 skips**、native **1,045 tests・12 skips**で成功。
  初回native probeではBtreeの直接属性len比較が **156,252 calls** 適用され、
  call_list_entriesが0から増えた。BPEのscan/dict countersは直前版と一致した。
  これらの診断時間を性能比較には使わない。
- CALL_REGIONS単独でもfold後の融合を使えるようcleanupのgateを揃え、単独オプションの
  回帰テストを追加した。最終build後に関連10 filesを再実行している。
  English design notesを`Tools/jit/regions.md`へ追記した。
- 次の比較は固定main、保存済みpair-scan-inline版、今回版の3種類、全6本・3 blocks・
  540値とする。設定は元CLIの3 warmups/10 values/1 loop、CPU2、block別hashseedを維持。
  最終binaryのnative coverageとidentityを記録してからタイミングを開始する。

- 最終10-file検証はdebug **1,132 tests・4 skips**、native **1,046 tests・12 skips**で成功。
  8生成物はbyte単位で再現し、Ruff F401/F811とdiff --checkも成功した。
- 最終native SHA256は`18c3a6ecfd4638cf3132aee24dc5209f69cc16afd3d4330a50efd1d6312dd033`。
  `build-jit/python-suite-folded-len`に保存（extensionsは現buildを共有）。
  `folded-len-final-manifest.json`、同patch、Btree/BPE native probeにdirty sourceと
  loaded extension identityを記録した。Btreeの156,252 direct len callsを再確認し、
  BPE countersは直前版と一致した。
- optimizer cleanupが他領域へ影響しないことも確認するため、native owned-floatの
  特殊値2,058ケースと丸め/例外フラグ432ケースを再実行し、bit・flagsとも通常経路と一致。
  `folded-len-final-owned-fenv-native.json`に保存。全6本の対応比較を実行中。

- 3 blocks・540値の比較は全checksum一致、除外0。main比算術平均は直前版0.706848、
  今回版 **0.704356**、block別0.702248/0.709039/0.701780。目標0.5は未達。
  Btreeの直前版比は0.951328/0.929428/0.958331、平均 **0.946362** で全block改善。
- 一方Hexiomは1.010567/1.022322/1.015285、平均 **1.016058** と全block悪化した。
  他の直前版比はBPE1.008936、DeltaBlue1.002394、Raytrace1.002828、Spectral0.996688。
  全値を`folded-len-final-suite-{rows,summary}.json`へ保持する。
- Hexiomの前後native probeは適用counterが一致（call_list12,421、len_subscript18,293）。
  ただしDone.__getitem__のexecutorは8,192から12,288 native bytesへ増えた。
  CALL_PY_LISTへ追加したdirect-lengthの分岐が、既存indexed経路にも入った影響を疑う。
  この原因はまだ仮説であり、現在段階を確定せず、direct/indexedをstencil生成時に
  分離して同じ比較条件で確認する。

- direct/indexedを10個のoparg replicasに分離した。0～4は従来のindexed経路、5～9は
  direct-length経路、引数数はoparg % 5とする。未使用selector7方式は撤回し、runtimeの
  追加分岐を各stencilの定数条件として消す。method/free functionの全対応arityと
  owner/valueの参照数を追加検証した。
- 最終関連10 filesはdebug **1,133 tests・4 skips**、native **1,047 tests・12 skips**で成功。
  8生成物のbyte再現と静的checkも成功。最終optimizer objectは明示的に再ビルドした。
  native SHA256 `f8ba3d3afa1566fde46c61a89f6f5b03648cfb38fbd773ce350a50086968a2cd` を
  `python-suite-folded-len-replicas`、`folded-len-replicas-manifest.json`、同patchに保存。
- Hexiomの適用counterは同じで、Done.__getitem__のnative bytesは8,192へ戻った。
  Btreeのdirect len calls156,252も保持し、全native bytesは278,528から258,048へ減った。
  Hexiomの分離前版との3-block・90値比較は0.986174/0.995044/0.992887、
  段階比較の幾何平均 **0.991361**、全checksum一致・除外0。
- 分離前への改善を確認したうえで、最終的な機能全体の効果を判定するため、固定mainと
  導入前pair-scan-inline版を対照にした全6本・3 blocks・540値の比較を再実行中。

- 最終3 blocks・540値は全checksum一致・除外0。導入前版のmain比算術平均0.711223に
  対し、今回版は **0.700686**（block別0.700237/0.701297/0.700522）。目標0.5は未達。
  Btreeの導入前比は0.951528/0.942432/0.922651、平均 **0.938870** と全block改善。
  Hexiomは0.998633/0.969079/0.999509、平均0.989074で、分離前の回帰は再現しなかった。
- script別main比はBPE0.814951、Btree0.707799、DeltaBlue0.966806、Hexiom0.833871、
  Raytrace0.862132、Spectral0.018556。導入前比の残りはBPE1.000152、DeltaBlue1.001997、
  Raytrace0.989117、Spectral1.002770。Btree以外の小さい/不均一な差をlen融合の直接効果と
  断定しない。今回版全体の導入前比算術平均は0.986997。
  `folded-len-replicas-suite-{rows,summary}.json`へ全値を保存した。
- canonical builtins dictのlen自体を差し替える追加ケースもdebug/nativeで成功し、
  callbackが本来のready frameから8回呼ばれた。先のcopied-builtinsケースに加えて確認。
  C sourceは最終測定時から変更なし。今回の定数cleanup/len融合/stencil分離を保持し、
  source/test/docをローカルcheckpointへまとめる。GitHub操作なし。
- 次はBPEの隣接ペア比較を調べる。現native codeでは、exact bytesの判定でも
  float/unicode/intの型分岐を先に通る箇所がある。対応する左右型を先に照合し、
  bytes二要素の組を短く判定する小さな変更案を準備した。まず通常の比較・callback順を
  保つこととnative codeの変化を確認し、BPEで効果がなければ採用しない。

### 隣接ペア比較の型判定（実装・検証中）

- len段階はローカルcommit `6674373eb60996dd9bfd33b96d264acc21534af7`、tree
  `f88e9b9401d2cb93ef31becf8e647d974f1d763b`へ保存した。測定時のC/H sourceとの一致も
  `folded-len-replicas-checkpoint.json`で確認。リモート操作なし。
- tuple/list pair比較の2箇所で、左右の対応する型の一致を先に判定し、両要素がexact bytes
  の場合は残るimmutable型の列挙を省く。bytesでない混合要素は既存の判定と比較へ進む。
  index範囲の検査、値比較、fallback先、callback順、counter契約は維持する。
- 別identityのbytes（NUL/長いprefixを含む）とbytes/str/int/floatの混合ペアを検証に追加。
  source差分は型guardの順番と短絡条件に限定し、入力・アルゴリズム・CLIは変更しない。

- 初回の一括検証で2つのfixture不備が出た。直前checkpointへ単独検証後に追加した
  canonical builtins.len変更は、restore後もinterpreterのbuiltin_dict rare-event counterを
  消費し、上限3に達した後のlen/range融合と後続test_optのcode-shape検査を失敗させた。
  値をrestoreするだけではテスト分離にならないため、canonical変更ケースを子processへ移した。
  先の「関連10 files成功」はこの追加ケースを含む一括実行の結果ではなかったので、
  この相互作用の修正後に関連範囲を改めて検証する。
- 新しい混合型ペアのreverseケースは対応する左右型が違い、正しくguard退出していたが、
  fixtureがguard退出0を要求して失敗した。guard_exit増加と通常の比較結果を要求する形に修正。
  指定したtest_unicodeもこのrevisionには存在せず、正しいtest_strへ変更して再実行する。
  初回debug58/native56 failuresとModuleNotFoundErrorのログは保持し、成功扱いにはしない。

- fixture修正後の6 filesはdebug **1,063 tests・17 skips**、native **977 tests・25 skips**で
  成功。8生成物のbyte再現、Ruff、diff --checkも成功した。nativeの適用counterは前版と
  一致し、34 executors・167,936 bytes。executor28の0x60f/0x618でbytes二要素の判定を
  確認した。`pair-type-guard-{manifest.json,.patch}`と保存binaryにidentityを記録した。
- BPEの3 blocks・90値比較は直前len版比 **0.996815/0.997139/1.001136**、段階比較の
  幾何平均 **0.998361**、main比0.814416。全checksum一致、除外0。
  効果が小さく全blockで揃わないため、Cの型判定変更は採用せず元へ戻す。
  混合ペアのテストとcanonical builtins変更のprocess分離は保持する。
- CPU profileは39K samples・lost0。dict lookup/tupleとlistのallocation・deallocation、GCも
  費用を占めている。`pair-type-guard-bpe-profile.*`に保存した。profile割合と時間比は区別する。
- 次は採用済みCへ戻したbuildでfixture修正を含む関連13 filesを検証し、その後Raytraceの
  float属性読み出しから複数の積和までのtraceを現binaryで確認する。call frameは残したまま
  中間operandの参照操作・box・重複guardをまとめる余地と、例外位置/丸めの条件を調べる。

- Cを戻した状態の関連13 filesはdebug **1,643 tests・18 skips**、native **1,557 tests・
  26 skips**で成功。`test-pair-type-restored-{debug,native}.log`へ保存した。
  canonical builtins変更の子process分離により、後続のlen/rangeとtest_optも成功している。
  型判定prototypeのC・生成物差分は残っていない。最新の全6本goal値は引き続き0.700686。

### float属性の3積和領域（実装・検証中）

- fixture修正をローカルcommit `28bdc7d101e01ae204dcc25fe4056328e173c173`、tree
  `44dee4e18a08490e7526cdfb9825a295fdfcde21`へ保存した。リモート操作なし。
- Raytraceの最新native traceではVector.dotに6属性のload/refcount/guard、最初の積のbox、
  owned積和2回が残る。frameを残し、この連続範囲だけを1 uopへまとめるprototypeを実装。
  同じ記録type version・配置のowner local 2つ（0～7）、exact float属性6つ、左結合の
  3乗算/2加算だけを認識する。pointer単位8-bit offset 6つをoperand0へ格納し、
  owner indices/type version/managed flag/final ADD offsetをoperand1へ格納する。
- guardは全て演算前、失敗時は元の最初のLOAD_FASTから通常実行。owner localsが属性を
  保持するため中間INCREF/DECREFは不要。任意call/store/periodic check/frame遷移は跨がない。
  最初の積と途中の和、および既存multiply-update helper内の積にC評価境界を置く。
- 最初のLOAD_FASTにはSET_IPが残る保証がないため、final ADDの位置はdeltaではなく
  絶対code-unit offset（16-bit範囲限定）を保存する。最終floatのallocation failureは
  実際のcallee frame・final ADD位置で報告する。新counterはfloat_attribute_entries。
- 導入前binary SHA256 `ee2d9bfa59be9607c8554e1dee2a2854acdf84c550047a42b212a638014a3e13`
  を `python-suite-float-attributes-before`へ保存し、manifestとRaytrace native probeを
  `float-attributes-before-*`へ保存した。現在は生成・形成テストを始める段階で、性能未検証。

- 初回形成テストはslots成功・managed不成立（13 failures）。managed側の冗長guard/NOPを
  含むspanが96を超えたため、探索上限を128 uopsへ修正した。次の1 failureはcalleeより
  前のmethod lookup guardで退出するowner.__dict__変更に新counterを要求したfixture不備。
  argument側のdictを変更して新region内のguardを実行するケースへ修正した。
  続くmissing属性2 failuresは最初の通常loop iterationで例外が出ていたため、valid値の
  次にmissing値をlist iterationで渡し、実際のregion退出をcounterで確認する形に修正。
  いずれも失敗ログを保持し、通過扱いにはしない。
- 追加11 testsはslots/managed、permuted offsets、同一owner、local6/7と8の境界、
  参照数・fresh結果identity、CALL_REGIONSなし、callbackによる後続属性変更、
  missing属性・型・__dict__・__getattribute__変更、call/storeで認識を停止すること、
  instruction monitoring、debug OOMのcallee frame/locals/final ADD位置を確認して成功。
- 関連14 filesはdebug **1,708 tests・19 skips**、native **1,622 tests・28 skips**で成功。
  8生成物のbyte再現、Ruff、diff --checkも成功。C/H実装は以後変更していない。
- `check-float-attributes.py`で2 layouts・特殊値 **5,488 cases** と、4丸めモード×
  divide-by-zero trap設定2種類×9入力×2 layoutsの **144 fenv cases**を確認した。
  nativeはbit/flagsとも全一致。debugはNaN payloadの差が特殊値1,152、fenv16件あるが、
  有限値・signed zero・NaN分類・例外flagsの不一致は0。全入力bits/結果/entry deltasを
  `float-attributes-{build-jit,build-tier2-debug}-fenv.json`へ保存した。
- native kernelの実際の演算範囲0x5b2～0x602に3 mulsd/2 addsdとC評価境界のstore/loadを
  確認し、FMAなし。`float-attributes-kernel-0-0.{bin,asm}`に保存。
  Raytraceの即時probeでは成功354,003、guard exits69,902、allocation errors0。
  owned updatesは844,762→136,756（2×354,003減）、他familyの適用回数は一致。
  recursive executor数57で、native bytes合計901,120→827,392。
- native SHA256 `6f73e80207ca4719da9d089f39c2a6737b63589cd267eaa652eeb28d37b6f0c6`
  を `python-suite-float-attributes`へ保存し、manifest/source patchを保存した。
  Raytraceの3 blocks・90値比較は導入前比 **0.960214/0.970180/0.997651**、段階比較の
  幾何平均 **0.975887**。main比0.840682、全checksum一致、除外0。
  全6本・3 blocks・540値の対応比較を続け、ほかのworkloadへの影響を確認する。

- 全6本・3 blocks・540値の比較は全checksum一致、除外0。同じ測定内の導入前版main比
  算術平均0.698207に対して、今回版は **0.694190**（block別0.690067/0.693863/0.698640）。
  算術平均0.5のgoalは未達。最新の測定値へ更新し、以前の0.700686とは測定blockも異なる
  ことを明記する。導入前への直接比較は今回の対応値を使う。
- script別main比はBPE0.813567、Btree0.702635、DeltaBlue0.966258、Hexiom0.831451、
  Raytrace0.832724、Spectral0.018505。Raytraceの導入前比は **0.971170/0.950799/0.983391**、
  平均 **0.968453** と全block改善。残る導入前比はBPE0.999759、Btree1.000706、
  DeltaBlue0.999931、Hexiom1.003555、Spectral0.998418。全体の導入前比算術平均0.995137、
  block別0.992935/0.991915/1.000562。3番目のblockでは全体比が僅かに悪化している。
  他workloadの小さな変動をfloat属性融合の直接効果と断定しない。
  `float-attributes-suite-{rows,summary}.json`に全値を保存した。
- 実際のnative stencil relocationも確認し、演算部分は3 mulsd/2 addsd、FMAなし、
  `PyFloat_FromDouble` call relocation 1個。`float-attributes-assembly.json`へ保存した。
- OOMをcallee自身のexceptで処理する追加テストでは、式の外側の7.0がoperand stackへ
  残る場合もhandler・元locals・内側のfinal ADD位置が正しく復元された。
  初回fixtureは既存runの無効化/backoffによりexecutorなしで失敗。新しいrunでwarmupし、
  実際のallocation_errors counterを確認して成功した。失敗ログも保持。
  この最後のケースを含めて関連14 filesを再実行し、source/test/docをcheckpointへまとめる。

- 最終fixtureを含む関連14 filesはdebug **1,709 tests・19 skips**、native **1,623 tests・
  29 skips**で成功（`float-attributes-*-checkpoint-tests.log`）。静的checkも再度成功。
  この段階を保持し、英語の設計文書 `Tools/jit/regions.md` と合わせてローカル保存する。
- 次の検討は新uopのnative guard code。現在のnullable-pointer helperは6結果を保持してから
  一括検査するため、CMOV/zeroing/再検査が残る。各属性を読んだ直後に同じguard退出を
  判定すれば、この交通整理を減らせる可能性がある。全guardがFP演算より前という条件を
  保ち、native code・fenv・Raytraceの対応比較で効果を確認してから採否を決める。

### float属性guardの逐次判定（実装・検証中）

- 属性融合のcheckpointはcommit `23101bb5b2186bdf50eca3a020a5b553276564e1`、tree
  `66981d01ca13e6a97d05b861c865a9df99e64619`。測定C/Hとの一致を別manifestで確認した。
- 新uopで各nullable-pointer helperの直後に同じguard退出を置く変更を実装した。
  従来の「6つのnullable結果を作成してから一括判定」を短絡化する。全6属性の成功を
  確認するまでdoubleを読まず、演算・allocation・退出先・counterの条件は維持する。
  生成物を再生成してdebug/native buildを進める。導入前実行ファイルは保存済み。

- 新native stencilは **683→583 bytes**、CMOVなし。実際のkernelも3 mulsd/2 addsdを保持。
  関連4 filesはdebug **620 tests・4 skips**、native **534 tests・14 skips**で成功。
  8生成物のbyte再現も成功。特殊値5,488・fenv144 casesは前段階と同じ結果で、nativeは
  bit/flags全一致、debugは同じNaN payload差のみ。結果とnative codeは別prefixへ保存した。
- Raytraceの57 executors、native bytes827,392、全counterは前段階と一致する。
  float_attribute_entries354,003、guard exits69,902、owned136,756。native SHA256
  `a7d45ec68eed986af21d8c50def06b21f623c8c1fe13c6b3fa9eb726c3df2e9a` を保存し、
  `float-attributes-early-*`へmanifest/patch/probeを記録した。直前の属性融合版との
  Raytrace 3-block対応比較を実行中。縮小自体を速度改善とは扱わない。

- Raytraceの3 blocks・90値比較は属性融合の初版比 **0.978222/0.983084/0.993939**、
  段階比較の幾何平均 **0.985060** と全block改善。全checksum一致、除外0。
  `float-attributes-early-raytrace-{rows,summary}.json`へ保存した。
  guard短絡化を含む最終版について、属性融合そのものの導入前版（ee2d...）と固定mainを
  対照に全6本・3 blocks・540値の比較を開始する。

- 最終全6本比較は全checksum一致・除外0で、同じ測定内の導入前版main比算術平均
  0.696745→最終版 **0.694141**（block別0.695088/0.697320/0.690013）。goal0.5は未達。
  Raytraceの導入前比は0.964519/0.974101/0.957412、平均0.965344。
  ほかの導入前比はBPE1.001541、Btree1.005208、DeltaBlue1.003422、Hexiom1.006420、
  Spectral1.000810。Btree/DeltaBlue/Hexiomの小さな増加が全blockにあるため記録し、
  逐次guardの変更だけを初版属性融合と比べる追加対照で確認する。
- 追加の対照実行ではBtreeのtoolがsessionを返した後にDeltaBlueを起動してしまい、
  2本が重なった。`float-attributes-early-control-{btree,deltablue}-*`はプロトコル違反の
  無効runとして全データを保持し、性能判定には使わない。初めに完了したHexiom対照と
  直前の全6本・540値は重なっていない。Btree/DeltaBlueは新prefixで順に再実行する。

- 逐次guardだけを初版属性融合と比べた有効な追加対照は、Hexiom
  1.002502/0.998886/1.001245（幾何平均1.000877）、Btree
  0.977809/1.005129/0.993490（0.992079）で、同方向の悪化は再現しなかった。
  全6本で観測した小さい悪化を消す扱いにはせず、別の測定として保持する。

- DeltaBlueの有効な逐次対照は1.007702/1.021253/1.013145（幾何平均1.014018）で悪化。
  原因を区別するため同じCLI設定でbefore/after/after/beforeを3 blocks実行した追加120値も、
  1.010550/1.005780/1.005381（算術平均 **1.007237**）となった。全checksum一致、除外0。
  `float-attributes-delta-abba-*`へ保存した。DeltaBlueの小さな回帰は確認できており、
  不成立扱いにしない。
- DeltaBlueの前後native probeはともに3 executors・16,384 bytes、region counter全0。
  hot rootの151 uopsのopcode/opargは一致し、差が出たcold-exitのopargはaddress由来。
  各sampleで新しい3 executorsが観測され、cold compilation/無効化の影響も残る。
  共通のEvalFrame/float/int/dict/allocatorのsymbol offsetsは一致し、JIT compiler/optimizer
  側はoffsetが変わる。回帰原因をこの情報だけで特定したとは扱わない。
- 全6本の直接比較では全blockの算術平均が改善し、Raytraceの初版との独立比較も全block
  改善したため、100-byte縮小を保持する。DeltaBlueで0.7～1.4%の回帰が出た対照を併記。
  最終版script別main比はBPE0.816257、Btree0.704836、DeltaBlue0.976304、Hexiom0.834020、
  Raytrace0.814920、Spectral0.018506。最新goal値は **0.694141**（未達）のまま。
- 次はBPEのzip/list iteratorを対象にする。zipはshared結果ならtupleを先にallocateし、
  unique結果なら各itemの置換後に古いitemをDECREFする。2つの異なるexact list iteratorsの
  両方に次要素があり、reused tupleの旧要素がcallback-freeな場合に限り、同じ生成・
  消費・参照操作の順序で間接iternext callsを省く候補を実装する。exhaustion、strict、
  同一iteratorの重複、古い要素のfinalizerは通常zip経路に任せる。iteration/tupleの
  virtualizationには広げず、まず形成・順序・例外・native適用とBPEの対応比較を行う。

### zipのlist iterator経路（実装・検証中）

- floatの最終checkpointはcommit `70a6d94ce34ec8fedf5c31dbd7a9f32a42ea721a`、tree
  `468b26ce65fc2b09d364f50fdd22d0a99ecc5ced`。測定C/Hとの一致を確認しmanifestへ記録した。
- `_ITER_NEXT_ZIP_LIST_PAIR` とC helper `_PyZip_NextListPair`を実装。既存exact-zip guardを
  残し、BUILTIN_REGIONSでのみgeneric nextを置換する。異なるexact list iterators2つの
  両方がin-boundsなら、listの要素取得とindex増加を直接行う。shared結果は通常zipと同じく
  tuple allocationを先に行い、unique結果は旧要素がexact bytes/Noneのときだけ通常と同じ
  順番で置換・DECREF・tuple recycleを行う。その他とexhaustionは元のzip_nextへ委譲する。
- callback可能なfallbackがあるため、このuop/helperはescapingとして扱う。正常exhaustionは
  END_FOR後、例外は元FOR_ITERへ分ける。zip_entries/reused_entries/fallbacksを追加した。
  共通debug allocation injectionをoptimizerのprivate headerへ移し、shared tupleの実際の
  allocationだけを `PYTHON_TIER2_REGION_FAIL_ALLOC=zip`で失敗させられるようにした。
- ここではC/uop/matcher/countersを実装した段階。まだ生成・ビルド・zipのテストは未実行。
  保存済み `python-suite-float-attributes-early`（a7d4...）を導入前対照にする。

- 初回native buildは新helperの宣言がPython/jit.cから見えず失敗。runtime relocation tableの
  利用箇所にもprivate iterator headerをincludeして解決した。debug/native buildが成功。
- 新しい11 testsは両buildで成功（nativeはallocation injection 1件skip）。shared tupleを
  保持した場合のidentity/参照数、unique tupleのhash reset、同じlistを別iteratorで読む場合、
  同一iteratorを2回渡す場合、zipの0/1/3/4 arities、strict時の余分な消費、custom iteratorの
  callback順/real frame/例外位置、旧要素のfinalizerが片方のiteratorを進めてもう片方の
  listをclearする場合、instruction monitoring、OOMで両iteratorが進まないことを確認した。
- 共通allocation probeの移動とiterator protocolを含め、関連17 filesをdebug/nativeで
  検証中。次は8生成物の再現性、BPEのnative適用counter/assemblyと対応測定を行う。

- 関連17 filesはdebug **2,082 tests・32 skips**、native **1,996 tests・43 skips**で成功。
  8生成物のbyte再現、Ruff、diff --checkも成功した。
- BPE native probeは34 executors・167,936 bytesで前段階と同じ。新経路は3,344,210 entries、
  うち846,111 reused、fallbacks2,183,853。ほかのregion countersは従来と一致し、allocation
  errors0。`zip-list-pairs-bpe-native.*`に保存した。C helperのdisassemblyでは成功経路の
  2つの間接iternext callsがなく、必要なPyTuple_New/DECREFと通常zip_nextへのfallbackを
  確認した（`zip-list-pairs-helper.asm`）。probeの秒数は性能比較には使わない。
- `python-suite-zip-list-pairs`、manifest/source patchへ実装identityを保存し、
  float最終版とのBPE 3 blocks・90値の対応比較を実行中。

- 初版BPEの3 blocks・90値は全checksum一致・除外0。前版比は
  **0.995692/0.994509/0.993747**、段階比較の幾何平均 **0.994649**。main比0.809550。
  改善は小さいが全blockで一致した。`zip-list-pairs-bpe-{rows,summary}.json`に保存。
- 初版native stencilは281 bytesで、C helperがstackへ返すdirect種別を読み戻し、JIT側で
  counterを選び直す分岐とspillが残った。counterをmode既知のC側で更新する変更を準備。
  成功/再利用/通常fallback/実際のallocation errorというcounter契約は保持し、fallback
  counterはcallbackの後に更新する。helperへの引数をint*からexecutor pointerへ変更し、
  uopは結果/例外/通常exhaustionを処理する。まだこの変更のbuild/test/性能は未検証。

- counter移動版は関連6 filesがdebug **939 tests・16 skips**、native **853 tests・27 skips**で成功。
  8生成物のbyte再現とRuff/diff checkも成功した。native stencilは **281→240 bytes**。
  BPE probeの全counterは初版と一致し、native executor 34個・167,936 bytesも同じ。
  成功3,344,210、再利用846,111、fallback2,183,853、allocation errors0。
  binary SHA256 `2dd4636163baf804ac3aa8c2231cf052ee66329476ed3de3468de0834817a48c` と
  source/stencil/拡張のidentityを `zip-list-pairs-counters-*` へ保存した。
  初版とのBPE 3 blocks・90値を逐次実行中。次に全6本で最終採否を判断する。

- counter移動版はBPE 3 blocksで初版比0.998757/1.003806/1.018921、幾何平均
  **1.007125**。全checksum一致・除外0だが改善が安定せず、採用しない。
  240-byte化だけを理由に保持せず、counterをuop側で更新する初版へsourceを戻した。
  初版manifestと全変更C/Hのhash一致を確認。再生成・再ビルドして全6本比較へ進む。

- 復元後の関連6 filesはdebug939/native853 testsで再び成功（16/27 skips）。
  再ビルド後native SHA256 `5dfd4c267883a8750b5d92c7ddb8dfb009be7b307c8abb5809ef731b490a7a1a`。
  BPEのcounter/34 executors/167,936 bytesは初版と一致した。
  `zip-list-pairs-final-*`へ復元source・build・test・probe identityを保存し、
  float最終版と固定mainに対する6本・3 blocks・540値の比較を逐次実行中。
- 次の候補をnative codeから検討した。Raytraceのdotには先行するmustBeVector呼び出しが
  あり、単なる「属性演算だけのcallee」としてframe全体を省略するmatcherは適用できない。
  検証呼び出しを省く実装には進めない。既存のtrivial/attribute call uopでは、optimizerが
  決めた戻り値種類・比較modeをnativeで再判定している。引数数とmodeをreplicaへ符号化し、
  同じguard・所有権・cleanup順を保って定数分岐を消す候補を次に実装・比較する。

- zip最終版の全6本・3 blocks・540値は全checksum一致、除外0。導入前のmain比算術平均
  **0.695013→0.689955**（今回版block別0.688948/0.689200/0.691718）。goal0.5は未達。
  script別main比はBPE0.809344、Btree0.706917、DeltaBlue0.961591、Hexiom0.828228、
  Raytrace0.815276、Spectral0.018376。`zip-list-pairs-final-suite-{rows,summary}.json`に保存。
- BPEの導入前比は0.990640/0.997890/0.989853（算術平均 **0.992794**）と全block改善。
  初版の独立比較も全block改善しており、zip初版を採用する。全6本の導入前比算術平均は
  0.993617、block別0.992311/0.994078/0.994463。その他の導入前比はBtree0.993222、
  DeltaBlue0.988360、Hexiom0.997187、Raytrace0.992761、Spectral0.997380。
  zip適用を確認したBPE以外の小さな変動を、zipの直接効果として一般化しない。
- 静的checkは成功。変更・11追加tests・英語のcontract・測定履歴をローカルcheckpointへ
  保存する。次のcall replica変更はartifact内のpatchとして準備済みで、まだCへ未適用。

### 単純callの戻り値modeをreplicaへ移す（実装・検証中）

- zipのcheckpointは `0ddb447533f`。測定sourceとcommitのC/H一致を別JSONに記録した。
- `_CALL_PY_TRIVIAL`はconstant/argument×引数0〜4の10 replicas、`_CALL_PY_ATTRIBUTE`は
  getter/is None/is not None/compact int比較×引数0〜4の20 replicasへ変更した。
  stack effectとcleanupの引数数はoparg%5、modeは商へ分離する。元のsource/config descriptor
  とguard・cleanup・code lifetimeは維持し、debug assertでmode encodingも検査する。
- 既存trivial-call行列にreplica確認を加え、attribute callにはslots/managed・bound/unbound・
  全引数数/4 modesの72ケースを追加した。まだbuild/test/測定は未実行。
  zip最終版を対照として、形成・意味論・native code size・Btree/Raytraceの差を確認する。

- 初回call検証は失敗。attribute行列で想定replica名が異なり、classmethodではdebugの
  `oparg == CURRENT_OPARG()` assert、nativeはsegfault。ログを保持し、性能測定は未実施。
  原因はuop ID generatorの辞書順で、20 replicasの_10.._19が_2より前に並び、optimizerの
  base+oparg+1による選択と不一致になったこと。replicates metadataで親をgroup化し、
  suffixを数値順にした。通常uop名は従来の名前順。12個・8:13範囲・似た名前の別uopを
  含む小さい生成テストを追加し、両namespaceで連続性を確認する。

- 数値順のID修正後はcall関連32 tests（追加72-case行列込み）が両buildで成功。
  関連10 filesはdebug **1,311 tests・37 skips**、native **1,224 tests・48 skips**で成功。
  8生成物のbyte再現、Ruff、diff --checkも成功した。0引数のnative stencilはtrivialの
  constant217/argument301 bytes（従来330）、属性getter366/None比較407/整数比較674
  bytes（従来726）。種類別の生成コードをartifactに保存した。
- Btree/Raytrace probeは全counterが前版と一致。Btreeはcall260,571/属性104,319、
  26 executors・258,048 bytesのまま。Raytraceはcall809,915/属性3,856、57 executorsで
  native bytes827,392→823,296。いずれもcall guard exits0。
  native SHA256 `347e3095a251cf0f85f7dacbd0728fa00b155776862ccf76911e2a7bf8af1995`、
  source/stencil/拡張identityを `call-mode-replicas-*` に保存した。Btreeの対応測定中。

- Btreeの3 blocks・90値は導入前比0.992941/0.991813/0.994570、幾何平均 **0.993107**。
  全checksum一致・除外0、全block改善。`call-mode-replicas-btree-*`へ保存した。
- sourceのmode抽出に明示的uint64_t castを追加し、無効化される32-bit buildでも
  uintptr_tの幅を超えるshiftを避けた。native optimizer_analysis.oの.textは変更前後で
  byte一致し、両buildのcall32 testsも再度成功。final binaryは
  `2ffe413e8224e811a314cf2c30c1f1d68a4e2c46b35a786165bd66fce69e15b2`。
- Raytraceの対応90値は1.000261/0.982557/0.999158、幾何平均 **0.993959**。
  全checksum一致・除外0だが、3 blocksに揃った改善とは扱わない。
  `call-mode-replicas-raytrace-*`へ保存。最終binaryのcounter再確認後、全6本のscreenへ進む。

- 全6本・3 blocks・540値では全checksum一致・除外0だが、導入前のmain比算術平均
  **0.691281→0.695589** と悪化。after/mainのblock別0.702104/0.691285/0.693377、
  after/beforeは1.011665/1.005494/0.998480、平均1.005213。
  BPE1.004569、Btree1.008091、DeltaBlue1.002680、Hexiom1.003491、Raytrace1.013572、
  Spectral0.998877。`call-mode-replicas-suite-*`へ保存し、この版の採用は未確定。
- 特にBtree/Raytraceは最初のblockで3.6/3.7%悪化し、単独比較と逆になった。
  明示cast前後のbinary全.textはbyte一致（SHA25634040cf0...）で、機械語変更による
  差ではない。同じ最終binaryでBtree/Raytraceを各3 blocksのABBA・120値により
  順に再確認する。これまでの測定を除外・置換せず、追加対照として残す。

- 追加ABBAは各3 blocks・120値、全checksum一致・除外0。Btreeは
  0.982858/0.993297/0.972860（算術平均 **0.983005**）、Raytraceは
  1.005324/0.999833/1.000131（**1.001762**）。全6本の悪化を消す扱いにはしない。
- Btreeでは属性callの成功104,319回があり、単独3 blocksとABBA3 blocksで改善した。
  一方Raytraceの約80万回のtrivial callには、分離による安定した利益を確認できない。
  次の試行は **属性callの20 replicasのみ** に絞り、trivial familyは元の5 replicasへ戻す。
  数値ID生成の修正と回帰test、72-case属性行列は保持。まだこの限定版は未build/未測定。

- 属性callだけの版は関連10 filesがdebug **1,311 tests・37 skips**、native **1,224 tests・
  48 skips**で成功。8生成物のbyte再現と静的checkも成功。Btree/Raytraceの全counterは
  zip最終版と一致した。Btreeは26 executors・258,048 bytes、Raytraceは57 executors。
  source/stencil/拡張・native codeは `attribute-mode-replicas-*` へ保存した。
  native SHA256 `f0a1e16e02e1b4b93a1df7775d199d450c9d99e778737e1c3a4dec6b5295b823`。
  zip最終版と固定mainに対し全6本・3 blocks・540値を比較する。

- 属性限定版の全6本・3 blocks・540値も全checksum一致・除外0だが、main比算術平均は
  **0.692053→0.694799**。after/beforeは0.997825/0.994346/1.016532、平均1.002901。
  Btreeは1.002700/0.983515/1.000205と揃わず、Hexiomの第3 blockは1.080839。
  この測定を除外せず保存し、限定版も採用しない。runtimeと英語contractをzip checkpointへ
  戻し、数値順uop ID生成の修正・生成回帰test・72-case属性testは保持した。
- 次は短い属性list内のtuple整数field検索。完全なcallee bytecodeを証明し、exact型・
  compact整数・list長上限・canonical enumerate/lenをguardする候補を実装する。
  任意の比較callbackや属性descriptorは元のCALLへ戻し、実callee frameで実行する。

- 検索uopの初版を両buildで作成。6 focused testsのうち5成功、比較行列の != 4ケースは
  regionが形成されず失敗した。元bytecodeの != maskにはunordered bitもあり7だが、
  matcherがcompact int用mask6を要求していた。完全body証明側を7へ修正した。
  debugの初回regrtestには残存tempdirの警告もあった。以後は新しい専用tempdirを使う。
  まだ性能測定は実施していない。

- 修正後の検索9 testsはdebug/native双方成功。owned receiverのfixtureは、callee検索loop
  のexecutorが先にでき、caller traceの形成には追加warmupを要した（元4002回では0本）。
  factoryと弱参照作成を省いた短いconstructor fixtureで8×閾値までwarmupし、実行counter・
  finalizerのcaller frame・参照数を確認した。失敗したfixtureログも保持している。
  !=を含む24組の比較/layout/call行列、長さ0/1/31/64/65、field1/31、型guard、
  callbackによるlist延長、例外frame、global/descriptor/code変更、general-key globals、
  monitoring、body内に追加effectがある場合のfallbackを確認。関連10 filesを両buildで実行中。
- 成功時は完全body証明に基づき、元traceのcallee部分を短い検索に置換してcallerのCALL直後
  へdynamic exitする。既存の関数version/引数/recursion/stack guardとcode lifetimeを保つ。
  上限64なのでpollを跨ぐ長いnative loopにはしない。全6本採用判断はまだ行っていない。

- 検索初版の関連10 filesはdebug **1,371 tests・36 skips**、native **1,284 tests・47 skips**
  で成功。Btree probeは20 executors、新検索成功177,958回・advance1,471,160回・
  call guard exits0。従来のenum scanは119,610→1回となり、既存の細かいloop処理の多くを
  置換したことを確認。counter採取のsecondsは速度比較に使っていない。
- Btreeの正式3 blocks・90値は前zip版比0.815275/0.817284/0.809248、幾何平均
  **0.813928**。main比は0.571241/0.583710/0.576020。全checksum一致・除外0。
  binary SHA256 `05ee4a95147d4cc952a6d22652b7bf18c0ba09ca63ee3581cb1e470d280d0d56`、
  `attribute-search-{manifest.json,btree-*,*.patch}`へ保存。全6本のscreenを逐次実行中。
- calleeとcallerの別globals・コピーbuiltinsを追加検証し、現在の検索10 testsは両buildで
  成功した。最初のfixtureはFunctionTypeで複製した関数のversionがUNSETとなりCALL自体が
  特殊化されず失敗。MAKE_FUNCTIONを通るexecで独立したcallee/callerを作って修正した。
  初回失敗・optimizer debugログも保存。callee globals/builtinsの変更に追従する。
- reviewで次の小修正を予定: full-body matcherのfunc_version検査を非0から
  _PyFunction_IsVersionValidへ厳格化し、共有されるCLEARED値1も明示的に除外する。
  現在の測定binary/source identityを保持し、測定完了後にbuildと再検証を行う。

- 次の調査対象はDeltaBlueの13呼び出し全体のcoverage。既存の--values 1 probeでは
  最初のtimed callでregion counterが0だったが、それだけでは正式CLIの10値すべてを
  代表しない。global plannerの更新がdict watcherでexecutorを無効化し、watch回数上限6に
  達する前後でcoverageが変わり得る。全6本測定の終了後に--values 10で前後counterを
  各sample直前・直後に採取し、どの段階で最適化が利用されているか確認する。
  この時点では原因や改善量を確定していない。

- 初版の全6本・3 blocks・540値は全checksum一致・除外0。main比算術平均
  **0.692659→0.671773**、after/main block別0.675454/0.667425/0.672440。
  BPE0.809331、Btree0.566232、DeltaBlue0.976129、Hexiom0.838080、Raytrace0.822231、
  Spectral0.018636。goal0.5は未達。`attribute-search-suite-{rows,summary}.json`へ保存。
- after/before全体は0.971865/0.967552/0.970900（平均0.970105）。Btreeは
  0.801587/0.806472/0.811687（平均 **0.806582**）で、単独比較と全block改善が一致した。
  一方Hexiomは1.010224/1.003247/1.006520（平均 **1.006664**）、Spectralも
  1.003266/1.003015/1.001064と小幅増加。DeltaBlue1.005420、Raytrace1.000928、
  BPE0.998591はblockで方向が混在。これらを除外せず、検索の直接利益とは区別する。
- 測定後にfunc_versionを_IsVersionValidで検査する一行修正を適用した。最終buildの
  focused/full検証とBtree対照、全6本の最終確認へ進む。native stencilは変更していない。

- 最終版は関連10 filesでdebug **1,372 tests・36 skips**、native **1,285 tests・47 skips**
  が成功。8生成物はbyte一致し、Ruff/diff checkも成功。Btreeの全counterは初版と一致し、
  native codeは20 executors・135,168 bytes（zip対照26本・258,048 bytes）。
  最終binary SHA256 `d7185a95fc22975fff8b6f36926347bb11c5b29d859e10a8fa305a87043133e7`。
  `attribute-search-final-*`へsource・binary・拡張identity、raw native code/assemblyを保存。
- 最終版のBtree 3 blocks・90値も0.805036/0.812130/0.814674、幾何平均 **0.810603**。
  main比0.560801/0.573306/0.582460、全checksum一致・除外0。全6本の最終比較を実行中。
- DeltaBlueの3 warmups＋10値probeはzip対照/最終版とも同じcoverage。最初8値の観測counterは
  0、9値目にcall/attribute48回、10値目に99回。最終11 executors。観測対象はsample前の
  executor群とsample後に発見した新executorであり、call途中に生成・破棄されたexecutorの
  counterまでは採取できない。0を「そのcall中に一切regionが動かなかった」と解釈しない。
- DeltaBlueの追加perfは本来の13 callsを維持し、各timed callのmonotonic開始/終了で
  sampleを絞った。cycles:u period20000、frame pointers、perf_jitは使わない。
  全3,400 samples中、測定窓内416 samples。leafはEvalFrame155、unknown61、
  visit_decref27、gc_collect_main22、Frame_ClearExceptCode17、FrameClearAndPop11。
  少数sampleの粗いprofileなので小さなC関数の順位は断定しない。10値のcounterは
  perfなしprobeと一致。`attribute-search-deltablue-windows-*`へ生データを保存した。
  profileのsecondsを性能改善の根拠には使わない。

- raw native executorを確認。長さguardはcmp $0x40、scan backedge内では毎要素に
  setge/setle/or/btで比較maskを評価している。次の候補は比較種類×引数数の12 replicasで
  この毎要素のmask処理を除くこと。既に修正した数値順ID生成を使い、同じ型guard・
  cleanup・上限・fallbackを保持する。準備patchだけをartifactに保存し、測定中のsource/
  binaryにはまだ適用しない。最終版の全6本結果とcheckpoint確定後に比較する。

- 最終全6本・3 blocks・540値も全checksum一致・除外0。main比算術平均
  **0.694339→0.670030**、after/main block別0.670924/0.669091/0.670074。
  BPE0.808582、Btree0.569790、DeltaBlue0.967519、Hexiom0.831643、Raytrace0.824048、
  Spectral0.018595。after/before全体0.967763/0.962884/0.966141、平均0.965596。
- Btreeは0.788183/0.808530/0.802595（平均 **0.799769**）。2回の単独比較と2回の全6本で
  全block改善し、約19〜20%短縮が再現したため検索最適化を採用する。目標0.5は未達。
  その他のafter/beforeはBPE0.997882、DeltaBlue1.001024、Hexiom0.999817、
  Raytrace0.997551、Spectral0.997532でblockの方向が混在する。初版Hexiomの全block悪化は
  この最終比較では再現しなかったが、先の測定を消さず残す。
- 英語reportに今回の完全body証明・guard/fallback・実行時間とvalidationの追記を行う。
  数値ID生成fixを独立したローカルcommit、検索実装/10追加tests/72-case属性回帰行列/
  docs/進捗を次のローカルcheckpointとして保存する。GitHub操作・push・PR変更は行わない。

- 数値順ID生成fixと生成回帰testをローカル `cbcf14f0e6e` に保存した。検索実装のC/Hは
  最終測定manifestと一致したまま。次のcommitで検索実装と今回の記録を保存する。


### 検索loopの比較をreplicaに分離（実装・検証中）

- 検索checkpointは `4bbe45fc2fb`。最終測定manifestとcommitの全C/Hが一致することを
  `attribute-search-final-checkpoint.json`へ保存した。固定main binaryもhash一致を確認。
- 比較6種類×explicit引数1/2の12 replicasを適用。stack effectは1+oparg/6、比較は
  oparg%6へ移し、毎要素のCOMPARISON_BIT生成を直接の整数比較に置き換えた。
  上限・型/関数/builtin guard・cleanup・dynamic exitは保持し、debugでdescriptorとの
  比較番号一致をassertする。既存の24-case行列には実際のreplica名の検査を加えた。
  まだこの版のbuild/test/速度確認は未実施。最終検索版を対照に採否を判断する。

- 比較分離版はdebugの検索10 tests成功。native生成は未定義.LBB0_33〜36で失敗した。
  13 stencilsを個別生成して元/処理後assemblyを保存したところ、12 replicasは全成功し、
  未使用のgeneric baseだけが失敗。6分岐がjump tableへ変換され、assembly optimizerが
  table経由の参照先を到達不能として除いていた。LLVMや全体のbuild flagsは変えない。
- 分岐をbitwise boolean式へ変更した。全比較が純粋なcompact整数比較なので追加の例外や
  副作用はなく、実replicaでは比較1個へ定数化される。generic baseにもjump tableを作らず
  生成できるか、個別stencilと両buildで再確認する。失敗artifactは保持した。

- boolean式への修正後はgenericを含む13 stencilsがすべて成功し、data sectionも0。
  実replicaは1 explicit argが947 bytes、2 argsが944 bytes。12 replicasそれぞれの.textは
  分岐版とbyte一致した（`search-comparison-boolean-text-check.json`）。変更は汎用baseの
  生成障害を避けるもので、実replicaの比較1個への定数化は保持する。両buildを再構築中。

- 比較分離版は関連10 filesでdebug1,372/native1,285 tests成功（36/47 skips）。
  8生成物のbyte再現と、CALL以外の5実験flagを0にしたnative形成・実行確認も成功した。
  Btreeの全counterは前版と一致し、20 executors・native135,168→131,072 bytes。
  raw assemblyでは検索loopがcmp/jgeに変わり、旧setge/setle/or/bt列がなくなった。
- binary SHA256 `c94079b27ee5b3851c19346d09545fb4064789ff1adcf3521733562831828297`。
  `search-comparison-*`にsource/build/拡張identity・native assembly・生成とtestログを保存。
  前版とのBtree 3 blocks・90値は0.981837/0.977562/0.975847、幾何平均 **0.978412**。
  全checksum一致・除外0。全6本を最終検索版d7185a...と固定mainに対して比較中。
- 汎用stencilのjump table問題とnumeric replica IDの検査を、再利用可能な生成上の注意
  としてAGENTS.mdへ追記した。追加のLLVMインストール、PGO/LTO、build flags変更は不要。

- 比較分離版の全6本・3 blocks・540値は全checksum一致・除外0。対応する前検索版の
  main比算術平均 **0.674354→0.670577**。今回after/main block別0.667642/0.671572/
  0.672519、after/beforeは0.993154/0.991067/0.998553（平均0.994258）。
  別時点の前版screen0.670030との単純差を改善量として扱わない。
- Btreeは0.984554/0.968711/0.984577（平均 **0.979281**）、単独比較と全block改善が
  一致したため採用する。main比はBPE0.807371、Btree0.561103、DeltaBlue0.981747、
  Hexiom0.834083、Raytrace0.820596、Spectral0.018564。目標0.5は引き続き未達。
  他のafter/beforeはBPE0.999849、DeltaBlue0.998792、Hexiom1.000098、Raytrace0.988731、
  Spectral0.998798で方向が混在する。`search-comparison-suite-*`へ全結果を保存した。
- 次の調査で、短いloopのexecutor作成後のcacheが8190へ戻ることを実機で確認した。
  初期loop閾値は4000、resume閾値が8190。FinalizeTracingが既にENTER_EXECUTORに
  置換された命令を直接JUMP_BACKWARD_JITと比較していることが原因候補。まず独立した
  回帰testと固定mainで確認し、無効化後の再試行が本来の閾値で行われるよう修正を検討する。
  まだこのcounterについてproduction Cは変更していない。


### 無効化後のloop再試行counter（再現・回帰test追加）

- 比較分離の採用checkpointは `8cf5d02d4e6`。測定sourceのC/H一致を別JSONへ記録した。
- 固定mainと現在版の両方で同じcounter問題を再現。短いloop（jump arg13）は成功後8190、
  期待4000。無効化後にTIER2_THRESHOLD回反復しても新executorができなかった。
  EXTENDED_ARG付きloop（arg335）は4000で再形成成功、関数RESUMEは期待どおり8190。
  `check-retry-counter.py`と`retry-counter-{main,candidate-before}.json`に保存した。
- loopの短/長両方でcounterと無効化後の再形成を検査するtest、およびCのmapから呼び出す
  RESUMEの対照testを追加した。これから修正前の失敗を確認し、元opcodeを参照して
  countdownの種類を選ぶ修正を行う。JIT_STRESSや閾値のチューニングは行わない。

- 修正前の回帰testは短いloopだけ8190 != 4000で失敗し、長いjumpとRESUMEの対照は成功。
  FinalizeTracingで_Py_GetBaseCodeUnitから元のopcodeを取得し、JUMP_BACKWARDならloopの
  設定値、RESUMEなら入口の設定値へ戻すよう変更した。閾値自体は一切変更していない。
- 両buildの修正後focused 2 testsは成功。短/長loopで無効化後に本来の反復数で新executorが
  形成されることも確認した。関連7 files（optimizer/regions/tier3/monitoring/trace/profile/
  call）をdebug/nativeで検証中。calleeのRESUME検証とMAKE_FUNCTIONによるcall fixtureの
  注意を、再利用可能な手順としてAGENTS.mdへ補足した。

- 関連7 filesはdebug/nativeとも1,268 tests成功（4/15 skips）。Ruff F401/F811と
  diff checkも成功。native stencilsは比較分離版とbyte一致、binaryは
  `0e5b3a081be0820afefd878e56a5dc5c8639832c132bf12f06db44105c17571e`。
- DeltaBlueの3 blocks・90値は前版比1.026249/0.996111/1.001195、幾何平均1.007766。
  10値の別coverage probeは前後とも最初の8値で観測counter0、9/10値のcall_attrが48/99。
  probeが捕捉できない、一回の呼出し内で生成・破棄されたexecutorの存在は否定できない。
  counter修正によるcoverage増加やDeltaBlue高速化は確認していない。
- 全6本・3 blocks・540値は全checksum一致・除外0。main比算術平均は
  **0.6686175→0.6691246**、after/before平均1.001705。DeltaBlueは今回だけ全block改善
  (0.998987/0.990873/0.993724)だが単独比較とは揃わない。Btreeは
  1.023341/1.002112/1.009008、Hexiomは1.000160/1.000333/1.005916と全block悪化した。
  速度改善としては主張せず、元opcodeによる正しい再試行counterの修正として保持する。
  `retry-counter-*`に全生データ・build/test/probe・修正前の失敗を保存した。
- 次はexact listの条件付き削除callを検討する。`if value in owner.cells[index]:
  owner.cells[index].remove(value); return True; else: return False`の全bytecodeを証明し、
  cached属性・exact list・compact intに限定して二重検索とcallee frameを省く。
  unsupported型/descriptor/比較callbackは元CALLへ戻し、mutation前に全guardを終える。
  単要素のlist slice削除は既存list実装が失敗しない契約を持つため、その経路を再利用し、
  capacity管理・要素移動を独自実装しない。まず回帰testとnative形成、Hexiom比較で評価する。

### 条件付きlist削除call（実装・検証中）

- `_CALL_PY_LIST_REMOVE`を追加。bound/freeの2 replicasで3引数の全bodyと2 returns、
  分岐先、繰り返される属性/index、`remove`の名前を証明する。元function versionと
  instrumentation、cached属性layout、outer/inner exact list、compact整数index/valueを
  mutation前に検査する。負indexに対応し、inner listは64要素以下に制限する。
- 一度の検索で最初の一致だけ削除し、未一致ならFalse。検索中のunsupported要素は
  副作用がない段階で元CALLへ戻す。一致後のtailは検査しない。削除は既存
  `PyList_SetSlice(list, position, position+1, NULL)`で、単要素削除が失敗しない契約を
  再利用する。削除対象はexact intなのでfinalizerはなく、残存要素の所有権も変えない。
- 成功後はreverse argument cleanupとcode lifetimeを保持してcallerのCALL直後へ戻る。
  entries/hits/iterationsを新counterへ記録。初回generatorはbrace必須のDSL構文で失敗し、
  後続makeも未生成IDで失敗した。構文を修正して8生成物の再生成が完了し、両buildを再構築中。
- 7 testsを追加し、layout/bound-free、長さ/負index/duplicates/alias/非compact型、比較callback、
  descriptor/code変更、monitoring、owned receiverのfinalizer、余分な副作用bodyを検査する。
  現段階は実装済みで、形成・性能はまだ未確認。タイミングとbuild/testを並行させない。

- call版の7 testsは両build成功。関連10 files（list/C API/generatorを含む）は両方
  1,467 tests成功（debug4/native15 skips）。Hexiomの新経路は339 entries/5 hits/
  771比較、全call guard退出0。15 executors/77,824 bytesは前版と同じ。
- call版binary `dccb92d9a9361f3229894479c84a50feea78dca4cf8d0f298e2cfa218d79ebb6`。
  `list-remove-call-*`にmanifest/patch/90値の対応比較を保存した。Hexiom前版比は
  0.998133/0.988743/0.995542、幾何平均0.994132（除外0）。まだ全6本の採否判定はしていない。
- 主要なDone.removeの入口executorを対象に、実frameを保持する`_LIST_REMOVE_LOCAL`も追加。
  tracerの開始code/offset/stack深さと同じ全body証明を使い、結果boolをstackへ積んで実際の
  true/false側RETURN_VALUEへTier 1で戻す。共通helperに全型guard・検索・削除をまとめた。
  helperは全経路でPythonを呼ばず例外も設定しないため、generatorのnon-escaping一覧へ登録。
  call版のframe省略と、local版のframe保持をcounter解釈でも区別する。
- local版のC呼び出しによる入口形成、duplicates/長さ/負index/unsupported callback、
  PY_RETURN monitoringの2 testsを追加し、両buildを再構築中。

- call/local計9 testsと関連10 filesは両build成功（各1,469 tests、debug4/native15 skips）。
  8生成物はbyte一致、Ruff F401/F811とdiff checkも成功。native binaryは
  `c8d787052e4eabcc53fdbf9f3fca1727fcd3e97d033d859bbfd56b2ca4e499ff`。
- Hexiomは合計2,675 entries/395 hits/6,630比較（call版339/5/771、実frameを保持する
  local版2,336/390/5,859）、guard退出0。15 executorsのnative codeは77,824→73,728 bytes。
  Done.removeは8,192→4,096 bytes。raw code/assemblyを`list-remove-local-hexiom-native.*`へ保存。
- local追加分だけの90値は1.001880/0.997847/0.993546、幾何平均0.997752で方向が混在。
  全体を導入前counter版と比べた90値は0.992870/0.991241/0.992094、幾何平均0.992068。
  全checksum一致・除外0。全6本を同じ導入前版と固定mainでscreen中。
  入口対応単独の性能効果はまだ断定せず、全体と分けて記録する。

- 全6本・3 blocks・540値は全checksum一致・除外0。main比算術平均は
  **0.6713321→0.6704071**、after/before平均0.999397。Hexiomは
  0.991602/0.983815/0.987804（平均0.987740）と全block改善。
  一方BPEは1.006544/1.005923/1.008560（平均1.007009）と全block悪化した。
  他は方向混在。`list-remove-final-suite-*`へ全データを保存。採否前にBPEのnative
  coverageを確認し、同じ固定binaryの3 blocks・90値で回帰を追加確認する。
- 次の候補としてglobals watcherを調査した。現callbackは変更keyを使わずdictionary
  全体へのdependencyを無効化し、unwatchする。単にruntimeの値guardへ置換すると、
  旧値の寿命とアドレス再利用、fold済みconstantの安全性を失う可能性がある。
  変更keyに対応するdependencyと構造変更へのdependencyを分ける案を検討するが、
  既存watcherの解除条件・mutation上限・module属性のconstant化も含む設計が必要。
  現段階は調査のみで、watcherや既定の閾値には変更していない。

- BPE追加90値は1.000629/1.001148/0.997738、幾何平均 **0.999837**、除外0。
  全体screenの0.7%悪化は再現せず、原因は未特定。前後probeは新削除counter0、既存全counter
  一致、34 executors/167,936 bytes。全体screenの悪化結果も残し、BPEの改善は主張しない。
- 最終10値のHexiom probeはentries2,675/2,716/2,717、その後2,717、hits395/436/436、
  その後436、全値guard退出0。1値probeだけの適用数を全10値へ外挿しない。
- C呼び出しprofileの回帰testを追加し、最終10 focused testsはdebug/nativeとも成功。
  他5実験flagを0にしたnative最終10 testsも成功した。関連10 filesの既存結果は1,469 tests
  （追加profile test前）であり、最新focused結果と件数を混同しない。
- raw native codeの間接call slotをPyList_Type/PyLong_Typeの一致するload biasとnmから
  解決し、削除経路が既存PyList_SetSliceを呼ぶことを確認（`list-remove-local-native-symbols.json`）。
- 条件付き削除全体はHexiomの単独/全体比較で全block改善したため採用する。入口対応単独の
  小差とBPEの不確実性は保持する。source変更・生成・両build・機能/native・比較の根拠を
  `list-remove-*`へ保存し、英語report/regions契約にも追記した。目標算術平均0.5は未達。
- 次はglobalsの名前単位dependencyを、元valueの寿命を伸ばさず変更通知で保護できるか
  独立testから進める。既存のdictionary全体dependencyも保護し、残るexecutorが必要な間は
  watcherを解除しない条件と、削除/clear/非unicode key/再入のfallbackを先に設計する。


### globals名前単位dependency（独立再現・test先行）

- 固定mainと採用版の両方で、既存の無関係なglobal entryの値を変えるだけでexecutorが
  invalidになることを再現した。実際に参照するstable entryの変更も正しくinvalidになる。
  `check-global-dependencies.py`と`global-dependencies-*-v2.json`へ保存した。
- 初版driverはmain側の既知8190 retry counterのため4002反復では再形成せず停止した。
  初版sourceと失敗理由を保持し、untimed再現の再warmupだけ両閾値の最大値を使った。
  ベンチマークのwarmup/sample設定やruntime閾値は変更していない。
- unrelated entryを16回変更してもexecutorが有効であること、used entry変更時は無効化と
  旧値の即時解放があること、add/delete/clear、共有codeと別globalsの3 testsを追加。
  現在のimplementationで先に失敗を確認してから、名前と構造へのdependencyを分ける。

- test先行で別の正しさの問題を発見。元globalsにvalue7、コピー側にvalue19を持たせ、
  同じcodeのfunctionをコピー側で8回反復すると期待152に対し68（19+7*7）になった。
  debug/current native/fixed mainで再現。`check-copied-globals.py`と
  `copied-globals-{native-before,main}.json`へ証拠を保存した。前のコピー検査はmutation上限後の
  非定数化経路だったため、この問題を検出していなかった。
- dictionaryのcopyはkeys versionを保持できるため、versionだけではconstantのnamespaceを
  特定できない。先にversionとglobalsのidentityを同時に検査するuopへ置換する修正を行う。
  元dictへのwatch dependencyは保持し、旧dictの寿命を延ばす新referenceは追加しない。
- 名前単位の性能testはartifactへ一旦保存し、現在の回帰testはcopied namespaceと
  add/delete/clear/replace後のvalue lifetimeの2 testsに分けた。正しさの修正を検証した後で
  無関係なentry変更でexecutorを保持する実装へ戻る。

- identity修正後、3 testsと独立native再現は成功し、152を返した。12 filesの初回検証で
  float rangeの形成testが20 subtests失敗した。range lowererが旧guard名だけを許可して
  いたため、新guardを同じくprefixへ保持するよう修正し、コピーしたnamespaceで別termを
  使う回帰testも追加した。guardを落として形成だけ復旧する変更はしていない。
- 同じ初回検証のtest_funcは存在しないmodule名によるimport失敗。実在する
  test_funcattrs/test_capi.test_functionを指定して再検証する。失敗ログは保持した。

- range prefix対応後は追加4 testsを含む関連13 filesが両buildで成功（各1,546 tests、
  debug4/native15 skips）。8生成物の再現性、Ruff、diff checkも成功した。
- 最終native `d4072ddeb417870a3f5f45c321cbae46047678e25d16f7358d7ae825c2bf949e`。
  Btreeの20 executors/131,072 bytes、Spectralの4 executors/24,576 bytesと全counterは
  前版と一致。namespace guardの追加でこれらの既存最適化が失われていないことを確認した。
  `globals-identity-*`にmanifest/patch/build/test/再現/probeを保存。正しさの修正として保持し、
  現在6本の対応比較を実行中。名前単位dependencyの性能変更はまだ実装していない。

- 全6本・3 blocks・540値は全checksum一致・除外0。main比算術平均は
  **0.6653419→0.6644558**、after/before0.9997148（block別1.003017/0.998421/0.997707）。
  BPE0.986170とBtree0.996398は全block短縮。一方DeltaBlue1.003498、Spectral1.006191は
  全block増加、Hexiom1.001991/Raytrace1.004041は方向混在した。BPEの第3 blockは
  before/main0.839009で他の0.817291/0.814351より遅いが除外していない。
- 新版main比はBPE0.812011、Btree0.553316、DeltaBlue0.964631、Hexiom0.824743、
  Raytrace0.813127、Spectral0.018906。別時点の前screen0.670407との単純差を改善としない。
  正しさの修正として採用し、性能はほぼ横ばい・個別回帰ありと記録する。
- `PYTHON_JIT=1`のみの独立native再現でもコピー側152/元56を確認。修正は実験flagに
  限定していない。C/H一致を監査してローカルcheckpointへ保存する。次は
  `jit-artifacts/benchmark-suite/named-globals-design.md`の名前/構造dependency案を実装する。


### globals名前単位dependency（prototype実装）

- legacy dictionary dependencyと衝突を区別するdomain hashで、名前valueと辞書構造の
  Bloom dependencyを追加した。CALL_REGIONSでglobalを定数化すると名前/構造を登録し、
  namespace identity guardも保持する。builtinのshadowing検査は構造dependencyで保護する。
  module属性のconstant化は初版ではlegacyのまま保守的に無効化する。
- MODIFIEDかつexact unicode keyだけは名前とlegacyを無効化し、他eventは構造とlegacyを
  無効化する。残る名前dependencyがあればwatchを維持し、mutation countは既存上限で
  飽和する。閾値の数値は変更せず、global valueへの追加referenceも持たない。
- invalidate helperは既存OOM時の全executor無効化を保持し、既存raw dependency APIも
  同じhelperを使う。無関係なentryの16更新とused entry変更のtestを復帰させた。
  現在prototypeで、生成/build/test/native/performanceはこれから検証する。

- 名前単位prototypeは重点9 testsと関連13 filesの1,551 testsが両buildで成功
  （debug4/native15 skips）。さらにdict/watchers関連3 filesの234 testsも両方成功した。
  8生成物はbyte一致、Ruff/diff check成功。nativeは
  `681e401eb5d4b312661e5a4514a22a680f06fd94a4b780d9c629bd8b5f4aaa2a`、
  stencil hashはidentity版と完全一致。manifest/patch/保存binaryを記録した。
- 独立再現でunrelated更新後も有効、used更新後は無効、繰り返し更新後も有効を確認。
  コピーしたglobalsも正しい結果を返す。DeltaBlueの10値probeではcall_attr_entriesが
  0/0/14/100/100/100/133/598/598/598（前版は最初8値0、その後48/99）。
  14 executors/155,648 bytes。観測中に作られ破棄されたexecutorは数えられない限界は同じ。
- DeltaBlue単独90値はafter/before0.967158/0.965862/0.956110、幾何平均0.963031、
  全checksum一致・除外0。現在同じbinaryと固定mainで6本全体を3 blocks screen中。
  named dependencyはmodule属性定数化には未適用であり、性能範囲を拡大解釈しない。

- 最終11重点testsは両build成功。後から追加した2 testsはlegacy/named依存の併用と
  無効化対象list確保のOOM fallbackを検証する。先の広域1,551件はこの2件追加前の結果。
  保持testは8種類のnamespace/keyで必要な無効化と結果を毎回検査し、少なくとも一つが
  保持されることを確認する。単一のBloom false positiveを機能不良とみなさない。
- 全6本・3 blocks・540値は全checksum一致・除外0。main比算術平均は
  **0.6672309→0.6607413**、after/before算術平均0.9934147。block別は
  0.990363/0.994911/0.994970。DeltaBlueは0.955686/0.973587/0.973046、
  平均0.967440で全block短縮。他5本は方向混在（BPE0.999160、Btree0.997842、
  Hexiom0.997842、Raytrace0.995609、Spectral1.002595）。全結果を保持する。
- named globals依存関係を採用する。全体の別時点の0.6644558との単純差は主張せず、
  対応するcontrol比を使う。英語reportとregions契約にも設計・検証・結果を反映する。
  次は`conditional-attribute-design.md`に整理した、整数属性の条件確認と属性返却を
  組み合わせるcallee経路を検証する。既存の関数version・型watch・namespace依存と
  元CALLへのfallbackを保持し、引数解放前に全guardを完了させる。


### 条件付き属性返却（prototype）

- named globalsの追加7 testsは両buildでhash seed 0/1/2/42でも成功し、ローカル
  checkpointに保存済み。次のcallee最適化として、cached整数属性とsigned-byteの
  immortal定数の比較、観測branch、cached属性返却を一つのuopへまとめる実装を追加。
- 元CALLのfunction version/stack/recursion guardを保持する。非zero function versionで
  同じfunctionのglobals associationが確定する場合だけ、定数化後のnamespace guardを
  省略する。cloneは別versionとなりfallbackする。既存のdict/type dependenciesは維持する。
- 全guardを引数解放前に実行し、分岐や型が合わなければ元CALLへ戻す。成功時は結果と
  元codeを保持して、既存call regionと同じ逆順cleanupを行う。新counterを追加し、
  両buildを再構築中。比較6種/両branch/slotsとmanaged/boundとfree、constant端、
  class/global/code/copy変更、callback/descriptorエラー、monitoringのtestを追加した。

- 初回重点testは形成した直後のexecutorで実行counterを検査し、57 subtestsが0で失敗した。
  形成後の8呼び出しで実行を確認するようfixtureを修正し、同じbinaryで全件成功。
  ベンチマークのwarmupは変更していない。失敗ログは保持する。
- owned receiverのfinalizerがcaller frameを見ること・即時解放と、profileのcall/returnを
  検査する2 testsを追加。関連13 filesは両buildで1,560 tests成功（debug4/native15 skips）。
  8生成物byte一致、Ruff/diff check成功。native binaryは
  `95a35e1c0ec0bc0ecb50a1e006b17e0a6fa433f40b2d9d750951316b1740a379`。
- DeltaBlueの10値で新counterは20,000/20,000/20,014/20,100/20,100/20,199/20,266/
  20,897/21,139/21,594、guard退出0。14 executors/147,456 bytes（前版155,648）。
  Plan.executeは167→97 uops、PUSH/RETURNは3組→1組、codeページ量は8,192 bytesのまま。
  native bytes/assemblyと両版probe/manifest/patchを保存した。
- 単独DeltaBlue90値はafter/before0.938143/0.929893/0.942139、幾何平均0.936711。
  対main0.875918、全checksum一致・除外0。6本全体の対応比較を3 blocksで実行中。

- 採用前のソース監査で初版のfunction version解釈を訂正。MAKE_FUNCTIONはco_versionを
  引き継ぐため、同じcodeの別functionが同じversionを持てる。FunctionType直接生成だけの
  testではUNSET versionとなり問題を見逃していた。MAKE_FUNCTIONで同じcode/versionと
  別globalsを作る回帰testは両buildで誤った属性を返して失敗した。
- 全体screenを中断し、初版の単独性能/partial rowsは不採用prototypeの証拠として保存。
  新`_GUARD_CALL_GLOBALS_IDENTITY`でcalleeの実globalsを元mappingと比較してから
  fused callへ進むよう修正。元dict dependencyがborrowed namespace pointerを保護する。
  フレームを作ってからGLOBALSを検査する代わりに、元CALLのstackを保って検査する。
  再build・全関連test・native probe・対応比較を改めて実施する。

- namespace guard修正版は共有code/version regressionと元namespace破棄のtestを含む
  1,562 testsが両build成功（debug4/native15 skips）。他5実験flagを無効にしたnativeの
  追加9 testsも成功。8生成物再現/Ruff/diff check成功。最終候補binaryは
  `4674c1047a65d9c3532a1c61be40b439583ac5068e424f0991ea756f35275f8a`。
- 修正版probeは新counterの10値すべて初版と同じ、guard退出0。14 executors/151,552 bytes。
  Plan.executeは101 uops/8,192 bytesで、各条件付きcallの前にcallee globals guardがある。
  PUSH/RETURNは3組→1組を維持する。初版147,456 bytesとの差も隠さず記録する。
- 修正版単独90値は0.947384/0.961084/0.953200、幾何平均0.953873（main比0.891576）、
  全checksum一致・除外0。新prefix `conditional-attribute-final-suite`で全6本比較を再開した。

- 修正版の全6本540値は全checksum一致・除外0だが、main比算術平均は
  **0.6587151→0.6586115**とほぼ横ばい。after/before平均1.0005464。
  DeltaBlueは0.951818/1.036294/0.954803（平均0.980972）で第2 blockが逆転。
  Hexiomは1.022736/1.001478/1.002155（平均1.008790）と全block悪化。
  BPE1.003627/Btree1.003433/Raytrace1.006016/Spectral1.000441は方向混在。
- 採用を保留する。単独DeltaBlueの改善だけで全体の効果を断定しない。第2 blockの
  DeltaBlueは一つの極端値だけでなく、多くの値が高かった。原因は未特定。
  追加検証は同じ固定binaryで、Hexiom/DeltaBlue native経路を先に確認し、各単独3 blocks
  (各90値)、続いて全体をもう3 blocks(540値)に事前固定する。build/閾値/入力は変えず、
  全データを保持し、良い結果が出るまで繰り返す運用にはしない。

- seed1の両版probeでもDeltaBlueの新counterは全10値で動作し、guard退出0。Hexiomは
  新counter0、28 executors/159,744 bytesと既存counterの全10値が前後一致した。
  これだけではタイミング差の原因を特定できない。追加単独90値はDeltaBlue
  0.947578/0.966250/0.942240（幾何平均0.951967）、Hexiom
  0.961678/1.014399/1.001977（0.992427、方向混在）。追加全体screenを継続中。
- ソース監査で新counterをstruct中段へ挿入したため、その後の既存counter/scratchの
  offsetまで8 bytes変わっていたことを確認した。不要な既存stencilへの波及なので、
  新fieldを末尾へ移すpatchをartifactに準備した（まだ未適用）。現在の固定binaryによる
  追加screenは最後まで保存し、その後この1要因を変えて再検証する。配置差が現在の
  回帰原因だとは断定せず、比較によって検証する。

- 保存raw native codeの静的逆アセンブルでも、既存counterのoffset変更を確認した。
  例: Hexiom Done.__getitem__のcall_list_entriesは0x218→0x220、
  Done.removeのremove_entriesは0x310→0x318。
  `conditional-attribute-hexiom-counter-offsets.json`へ前後を記録した。これは
  machine codeへの不要な波及の証拠であり、性能回帰の因果関係の証明ではない。
  struct末尾配置後は同じ対応を検査する。

- 追加全体540値も全checksum一致・除外0。main比算術平均0.6688699→0.6597483、
  after/before0.9907443。DeltaBlueは0.950038/0.900405/0.949521と全block短縮だが、
  第2 blockのcontrol/mainが1.028045と他より遅い。遅いcontrolも除外しない。
  BPE1.004604/Raytrace1.007969は全block悪化、Hexiom1.000414、Btree1.000441、
  Spectral0.997716は方向混在。前回のほぼ横ばい結果も保持する。
- 予定のcounter末尾配置だけを適用して両buildを再構築する。追加したarity testは
  0〜4 explicit args、bound/free、selectorとresultが異なるargumentのケースを検査する。
  既存counterのnative offsetが戻るかを確認し、配置変更単独のDeltaBlue/Hexiom各90値、
  続いてnamed-globals版をcontrolに全6本540値を測る。

- counter末尾配置のdebugは1,563 tests成功したが、nativeはregion testsで410 failures。
  原因調査で、MakeのJIT_DEPSとTools/jit/_targets.pyのdigestがpycore_optimizer.hを
  入力に含めず、headerだけの変更では古いstencilを再利用していたことを確認した。
  最初のnative binary 8dabd5cb...はstencil不整合のため性能比較に使用しない。
  probe/native-offset検査も失敗しており、そのログ/manifest/binaryを保持する。
- 固定bootstrap/LLVM21/同じno-vectorization flagsでbuild.py -fを実行してから
  nativeを再リンクする。通常の再build成功だけでstruct layoutとstencilの一致を
  認定できないことをAGENTSの再利用可能な手順にも記録する。

- 強制再生成・再リンク後はnativeも1,563 tests成功（15 skips）。有効な最終候補は
  `e6793865982e1098903b9fdba87aead913369ca73928bd8b7ca0953d2d5e9420`、
  `conditional-attribute-layout-*`へ識別情報を保存。mockによるdigest検査でも、
  pycore_optimizer.hの内容変更がdigestに反映されないことを確認した。
- 新probeではDeltaBlue新counter全10値を維持、14 executors/151,552 bytes。
  Hexiomは既存全counterが一致し、28 executors/159,744 bytes、既存counterの
  native offsetも完全に元へ戻った。末尾配置版と中段配置版の比較90値は、
  DeltaBlue0.995632/0.999433/0.995595（幾何平均0.996885）、
  Hexiom1.011276/1.001286/1.004359（1.005632）と全block悪化した。
  offset変更だけを回帰原因とはみなせない。全体比較はnamed-globals版をcontrolに実行中。

- 末尾counter最終候補の全6本540値は全checksum一致・除外0。main比算術平均は
  **0.6620986→0.6564989**、after/before0.9954716、block別0.994219/0.995407/0.996790。
  DeltaBlueは0.944521/0.937148/0.957567（平均0.946412）、Btree0.996526で全block短縮。
  一方、BPE1.007020、Hexiom1.004086、Raytrace1.011450、Spectral1.007335は
  すべてのblockで悪化した。これらの回帰を保ったまま、目標の算術平均での改善と
  繰り返し確認したDeltaBlueの改善から、条件付き属性返却を採用する。
- 最終main比: BPE0.815598、Btree0.551212、DeltaBlue0.887381、Hexiom0.830578、
  Raytrace0.835328、Spectral0.018896。別時点のscreenとの差分を改善とは主張しない。
  10追加testsを他5実験flag0のnativeでも検証成功。両buildの関連13 filesは各1,563 tests
  （debug4/native15 skips）。8生成物再現、native counters/offsets、Ruff/diff check成功。
  英語report/regionsと失敗prototypeを含む全artifactを更新し、C/H一致を確認して
  ローカルcheckpointへ保存する。GitHubへの操作は行っていない。
- 次の作業は、確認済みのstencil再生成漏れの最小修正。
  `stencil-header-dependency-next.patch`と設計メモを準備した。Make/Windowsの入力一覧と
  digestへpycore_optimizer.hを加え、header内容だけの変更でdigestが変わるoffline testを
  追加する。その後、BPE/Raytraceで残るコストと回帰を、固定入力のnative profileから
  改めて切り分ける。タプルのidentityや例外時stateを変える再利用は導入しない。
  目標算術平均0.5は未達で、goalは継続する。


### stencilヘッダー依存の修復

- `Include/internal/pycore_optimizer.h`をPOSIXの`JIT_DEPS`、Windowsの`_JITSources`、
  `Tools/jit/_targets.py`のdigestへ追加した。ヘッダーだけを書き換えた一時source treeで
  digestが安定して再現し、内容変更後に変わるoffline testも追加した。
- 修正前に生成された`build-jit/Makefile`から通常の`make -n .jit-stamp`を実行すると、
  Makefileを再構成した後に`Tools/jit/build.py`と`.jit-stamp`更新を自動で予定した。
  実際の通常buildでもheaderより新しいstencilを13:05 UTCに生成し、依存修正が
  強制再生成なしで働くことを確認した。最初のsystem Python 3.13による生成は約10分間
  生成物が更新されず停止したため中断し、記録済みの`build-tier2-debug/python`を
  `PYTHON_FOR_REGEN`に固定すると約36秒で完了した。
- 再生成時、`_GUARD_GLOBALS_VERSION_AND_IDENTITY`の64-bit cache operandが生成Cでは
  `PyObject *`として宣言され、32-bitのdict keys versionと直接比較される警告を発見した。
  cache幅とoperand配置は変えず、`uintptr_t`経由で`uint32_t expected_version`へ明示変換して
  比較するよう修正した。再生成された4 stack-cache replicasすべてに同じ変換が入り、
  対象警告は消えた。
- PGO/LTOなしでdebug Tier-2とnative JITを再構築。native binaryは
  `9647e7da986cd96a820f1c76c7d3a3e49d23a02fa0f8b5d21f2127904161afba`、
  `PYTHON_JIT=1`でavailable/enabledともtrue。debugの`test_tier3`、`test_capi.test_opt`、
  digest testは336 tests（3 skips）、regionは200 tests成功。native JIT有効は同じ
  4 filesで536 tests（14 skips）、無効経路は335 tests（4 skips）成功した。
  stale stencil時の410 failuresは再発せず、diff checkも成功した。
- この修復はbuild correctnessであり、最新の性能値0.6564989を更新しない。ローカル
  checkpointへ保存後、固定入力・固定CPUでBPEとRaytraceのnative profileを取り直す。
  まずexecutor coverage/counterとperf symbolsを対応させ、呼び出し境界、lookup、allocation、
  refcountのどれが残り時間を占めるかを決める。次の変更はprofileで支配的な一経路に限定し、
  機能test、native counter/code、対応するbefore/after測定の順に採否を判断する。
  目標算術平均0.5は未達のためgoalを継続する。


### BPEのzip/Counter連続更新

- 修復後nativeでBPEをCPU 2へ固定して再probeした。主要executorは
  `_ITER_NEXT_ZIP_LIST_PAIR`を20,062,134回通る一方、13,102,243回は共有された
  zip結果タプルのため通常経路へ戻り、`_DICT_PAIR_INCREMENT`は13,553,249回成功、
  6,508,885回guard退出した。`perf`のJIT有効プロファイルでもtupleの確保・解放、
  object allocator、GC、dict lookup、`_PyZip_NextListPair`が上位を占めた。
  最初に指定した`PYTHON_PERF_JIT_SUPPORT=1`はこのforkではJITを無効化したため、その
  profileは削除し、JIT available/enabledを確認した通常の`perf record`だけを根拠にした。
- 単純にループ変数が持つzip結果タプルの参照を外して再利用する案は不採用。
  `id(pair)`とperiodic checkからフレームを調べるsignal handlerに同一性の違いが見える。
  採用候補は、exact zipの異なる二つのexact list iterator、exact bytes要素、callback-freeな
  既存dict key、small-int範囲のCounter値という条件で、更新を偶数個ずつ先行処理する
  bounded scan。次の一反復は元のzip/store/dict uopへ必ず残す。これによりscan全体は
  奇数反復となり、zipのcached tupleとループlocalの同一性の交替を境界で維持し、枯渇、
  missing key、衝突、監視dict、subclass callbackは未消費のまま元処理へ渡す。
- workloadを変更せずCounterの各outer iteration後に値分布だけを集計した診断では、
  既存key更新3,712,720回のうち3,703,435回（99.75%）が更新後256以下だった。このtreeの
  small-int cacheは実際には0〜1024であり、この数値は保守的な下限だった。したがって
  初版は値boxを新規確保しないsmall-int cache内だけをscanし、allocation failure後の
  部分進行を扱う複雑さを入れない。最大62反復を先行し、既存の最大64反復scanと同程度に
  periodic checkの遅延を制限する。
- 同じ診断を実上限1024で再集計すると3,712,720/3,712,720回が範囲内だった。これは
  workloadの値分布であり一般入力の保証ではないため、helperは上限外で必ず元処理へ戻る。
- 次は二つのbytes pairをcallbackなしで検索・更新するdict helper、zip iteratorを進める
  helper、厳密なtrace matcherと専用counterを実装する。同一keyを二回更新する場合も
  最終値を正しく合成する。形成拒否、missing/collision、値境界、保持tupleのidentity、
  unequal/strict exhaustion、monitoring、実行counterをdebugで検証し、native再生成後に
  BPE単独の対応比較を先に行う。改善しなければ全6本screenへ進めず撤回する。

- prototypeを実装した。二つのpairを同じdict stateで検索し、同一keyならaddendを二回分
  合成する。異なるkeyも含め、最終値が0〜1024のsmall-int singletonならcallback・確保なしで
  置換する。zip helperは短い側に最低1 pairを残し、最大62 pairを偶数単位で進める。
  trace matcherはzip next直後の同じ`pair` local、closure cellのCounter、二つのCOPY、既存の
  `_DICT_PAIR_INCREMENT`、直後のloop backを全て要求する。bodyに`id(pair)`を記録する処理を
  足した形は形成されない。
- debug Tier-2の形成probeでは新uop、元zip next、元dict incrementが同じexecutorに入り、
  96要素の反復を正しいCounter値と最終localで実行した。固定seedで長さ0〜129、addend
  0/1/2/17、複数bytes pairを参照計算と比較した追加診断も成功した。正式に追加した7 testsは
  値/長さ境界、addendとsmall-int上限、missing・衝突・bytes subclass、strict unequal、
  pinned cached tupleの内容/hash/identity、Counter subclassのsetter、monitoring、matcher拒否を
  検証して全件成功した。
- debugでは領域test 207件（skip 10）、Tier 3/C API統合335件（skip 4）が成功した。
  LLVM 21で再生成したnativeでも新規7件と同じ統合335件が成功し、JIT available/enabledと
  `bpe_train` executor内の新uopを確認した。初版native SHA-256は`91fdf8dc1b4c...`、短い
  suffixをdict/cell検査前に除く版は`037c5985bbc0...`で、PGO/LTOは使用していない。
- resident probeでは1 sampleあたりscan 302,290回、795,262 pairを先行処理したが、空振りは
  4,430,511回だった。同じ入力を逐次再現すると、空振り3,449,524回中2,839,903回は残りが
  2 pair以下、490,337回は第一key missing、149,668回は第二key missingだった。値のcache
  上限による失敗はなく、短いsuffixを先に除く版も3-sample平均2.4699秒で初版2.4688秒と
  同等だった。診断は`zip-dict-scan{-short-reject}-bpe-native.*`へ保存した。
- 固定CPU 2、各process warmup 3・10 values、開始順を回転したBPE 3-block比較では、直前候補
  に対する比が1.003812、1.005625、1.003865、幾何平均1.004434となり、3 blockすべてで
  回帰した。main比は0.815667、0.818993、0.804307、幾何平均0.812965。全checksum一致、除外0で、
  `zip-dict-scan-bpe-{rows,summary}.json`に保存した。79.5万pair分のtuple/更新処理を省いても、
  仮想pairの重複lookupと短いpieceでのhelper呼び出しが上回るため、このprototypeとtests、
  counters、生成uopは撤回した。測定用binaryだけを
  `build-jit/python-zip-dict-scan-short-reject`に保存した。
- 次は採用済みsourceからnativeを戻し、BPE専用scanではなく全体比の大きいDeltaBlue、Hexiom、
  raytraceを最新候補で再profileする。executor coverageとself timeを照合し、複数workloadで
  再利用できる既存uop/call/attribute経路の一つを選ぶ。目標算術平均0.5は未達なので継続する。


### generator式を受けるsumのnative集約

- zip/Counter試作を撤回した採用sourceから、PGO/LTOなしのnative JITを再生成・再構築した。
  binary SHA-256は`a176f2fd72a356a71820afc59a63efb35b2915083bfe873da404b66d284852b1`、
  `PYTHON_JIT=1`でavailable/enabledともtrue、diff checkも成功した。source差分はこの
  `plan.md`だけで、却下したuop/tests/counters/生成物が残っていないことを確認した。
- 固定CPU 2、全採用flag、到達可能side traceを含むresident probeをDeltaBlue、Hexiom、
  raytraceへ実行した。1 workload当たりの主な成功counterは、DeltaBlueが条件付き短縮call
  20,014回、Hexiomがlist contains 33,588回・短縮call 14,336回・`len(subscript)` 17,577回、
  raytraceが短縮call 811,897回・float属性融合356,133回・class初期化278,913回だった。
  binary hash、環境、全executor/uop列、native bytes、sample窓を
  `latest-adopted-{deltablue,hexiom,raytrace}.json`へ保存した。
- 同じbinaryとflagで通常のJIT有効CLIを十分に反復し、`cycles:u`をprofileした。self timeの
  `_PyEval_EvalFrameDefault`はDeltaBlue 10.88%、Hexiom 15.39%、Raytrace 4.14%。DeltaBlueは
  list iterator 3.59%、method lookupとbound-method生成も残り、Raytraceはframe cleanup、
  float/object allocationと特殊メソッド呼び出しが残った。Hexiomではevaluatorの12.42%分が
  `builtin_sum -> PyIter_Next -> gen_iternext`配下で、さらに`gen_iternext`自体2.98%、
  `builtin_sum`0.77%だった。生data/reportは`latest-adopted-*-perf.{data,txt}`へ保存した。
- Hexiomを100回warmupすると78 executorsが形成され、offset 772/934のcaller traceに
  `_MAKE_FUNCTION`、`_RETURN_GENERATOR`、`_CALL_BUILTIN_FAST_WITH_KEYWORDS`が同居した。
  genexpr側にもoffset 54/60のnative executorがあるが、yieldごとにbuiltinからevaluatorへ
  往復するため、bodyのcontains融合だけでは上記コストを消せない。論理call countでも
  genexprは29,920回/workloadで、profileと一致する。
- 次は、`sum(1 if key in item else 0 for item in exact_list)`という完全なgenerator code形と、
  直前にその場で生成され外へ公開されていないことをoptimizerで同時に確認し、汎用builtin
  callを専用uopへ置換する。実行時はexact generator/code/frame、唯一参照、未開始状態、
  exact outer/inner lists、compact exact ints、最大64要素をすべて読むだけで検証する。
  失敗時はgeneratorのframe/index/refcountを変えず元CALLへdeoptする。成功時だけcallbackなしで
  membership数をsmall-intとして返す。形成拒否、共有/開始済みgenerator、list/int subclass、
  pending work、空/重複/negative値、monitoringとcounterをdebugで検証してからnative再生成し、
  Hexiomの対応比較で採否を決める。

- 初版の専用uopはdebug Tier-2で最初の実行時にsegfaultした。原因はデータ参照ではなく、
  `#ifdef Py_GIL_DISABLED`内の`DEOPT_IF(true)`をcase generatorが無条件終了と判定し、通常GIL
  buildにもcase末尾のstack-cache反映・`break`を生成しなかったことだった。`valid=false`を
  GIL無効側で設定し、共通の`DEOPT_IF(!valid)`へ流す形に変更した。生成Cにcase末尾が戻り、
  hot probeのクラッシュは解消した。結果のsmall intはnew referenceなのでstack refへstealし、
  誤ったtrace照合でもtagged int引数をobjectとして参照しないguardも追加した。
- optimizerはgenerator bodyの全命令、sumのcached callable、その場のMAKE/RETURN/CALLを照合し、
  runtimeは未開始・唯一参照・frame未公開のexact generator、code/instrumentation、exact list二層、
  compact exact int、各長さ64以下を検証する。成功probeは100集約、400比較、guard退出0を記録した。
  exact値/負値/compact境界/空・重複、参照数、list subclass callback、bool/巨大int/tuple/長さ上限の
  fallback、類似するbool generatorの形成拒否を3 testsへ追加した。新規3件とregion全203件は
  debug Tier-2で成功した。
- 次は採用済みnative binaryをbeforeとして固定保存し、LLVM 21/no-vectorization、PGO/LTOなしで
  stencilとnative executableを再生成する。JIT code内の専用uopとHexiomの成功counterを確認後、
  固定CPU 2・同じ入力・warmup/sample数・開始順回転の3-block対応比較を行う。改善しなければ
  全6本screenへ進めず、このprototype、tests、counter、生成物を撤回する。

- 初版nativeはLLVM 21、`-fno-vectorize -fno-slp-vectorize`、PGO/LTOなしで再生成し、
  専用uopを12/8 KiBのHexiom side trace内に確認した。resident policyで20 warmups後に測る
  steady-state比較はbefore比0.811551/0.830154/0.779148、3-block幾何平均
  **0.806674**で、generator往復を除く集約自体には約19.3%の効果があった。一方、既定policy、
  3 warmups・10 valuesの正式比較は1.001265/1.004276/0.999890、幾何平均
  **1.001809**で効果がなかった。全checksum一致、除外0で、両結果をartifactへ保存した。
- 既定policyを呼び出し単位で追跡すると、専用Tier-2 traceはworkload実行14回目に初めて形成され、
  実行1〜13回目は専用uop/counterとも0だった。正式測定は3 warmupsと10 valuesの計13回で
  終わるため、効果がない原因はnative集約の速度ではなく形成時期だった。この形のまま全6本へ
  進める判断を撤回し、同じ厳密なgenerator code/runtime条件をCALLのTier-1 specializationへ
  移した。
- `CALL_SUM_LIST_INT_CONTAINS`をCALL familyへ追加し、最初のadaptive specialization時に
  cached builtin `sum`、引数1個、その場のexact/unique/unstarted generator、code versionと
  generator body形を確認してcode versionをinline cacheへ保存する。実行時はbuiltin/self/code、
  instrumentation/pending work、frame、outer/inner list、compact exact int、各長さ64以下を再検証し、
  失敗時は未消費のgeneratorと元のstackを保って通常CALLへ戻す。成功時は同じopcodeがTier-1で
  直接集約し、後にTier-2へ変換された場合も同じuopを再利用する。opt-in flag無効、free-threaded、
  DTrace/Emscripten条件では通常経路を維持する。
- 生成物を更新したdebug buildはコンパイル成功。新opcodeはflag有効時の2回目の呼び出しで成立し、
  Tier-2閾値より前に実行された。exact/fallback/shape拒否に加え、adaptive disassemblyでの形成と
  flag無効時の非形成を検査する4 testsはすべて成功した。初回コンパイルで不足していた
  `FRAME_CREATED`の定義headerと、test中の旧uop名2か所も修正した。
- 次はregion全件とTier-3/C API統合をdebugで実行する。成功後にLLVM 21でstencilとnativeを
  強制再生成し、同じ統合test、JIT availability、adaptive opcodeとnative uopを確認する。
  その後、保存済みbefore binary `python-sum-gen-before`とのHexiom 3-block対応比較を既定policyの
  まま再実行する。全blockで意味のある改善が再現した場合だけ全6本screenへ進め、改善しなければ
  Tier-1を含む試作全体を撤回する。

- debugでは関連testを別々の一時directoryで順次実行し、Tier3 14件、C API opt 321件、region
  204件の計539件が成功した（skip 3）。3 test filesを同一workerで連続実行した診断だけは、
  warmup回数ちょうどでexecutor形成を要求する既存testが毎回異なる1件で形成されない順序依存を
  示したが、各fileと失敗testの単独再実行は成功した。専用4 tests、生成物再生成のbyte同一性、
  `git diff --check`も成功した。
- LLVM 21/no-vectorizationでstencilを強制再生成し、PGO/LTOなしのnative executableを構築した。
  SHA-256は`98e973075d7a8245c2bbf53b1f4ede778f04d716ed957b9ed807ff79c39bf12b`。
  JIT available/enabled、flag無効時の通常CALL、flag有効時の2回目でのTier-1 specializationを
  それぞれ確認した。nativeでもTier3 14件、C API opt 321件、region 204件が成功した
  （release固有skip計14）。専用region testは形成したnative executorのuopと成功counterも検査した。
- 既定policy、固定CPU 2、3 warmups・10 values、開始順回転のHexiom対応比較はbefore比
  **0.754466/0.749710/0.755896、幾何平均0.753353**で3 blockすべて短縮した。main比は
  0.627293/0.628162/0.624514、幾何平均0.626654。全checksum一致、除外0で、binary/script hashと
  全raw値を`sum-gen-tier1-hexiom-*`へ保存した。既定policyで約24.7%短縮したため、このTier-1候補を
  撤回せず全6本screenへ進める。
- 次は同じ三つの固定binary・全opt-in flag・固定CPU 2で、BPE/Btree/DeltaBlue/Hexiom/Raytrace/
  spectral-normを各3 blocks測る。候補/beforeだけでなくmain比も保持し、全checksumとbinary hashを
  検証する。Hexiom以外のopcode番号移動やCALL signature変更による回帰もここで判定し、目標の
  6本main比算術平均を更新する。採用判断後はmonitoring/pending-workと特殊call形の追加test、
  generated-file check、Ruff/format相当を仕上げる。

- 全6本・各3 blocks（540値）は全checksum一致、除外0、終了時binary/script hash再検証成功。
  候補/main算術平均は**0.6213384**で、block別0.621356/0.620076/0.622584と安定した。個別は
  BPE 0.812731、Btree 0.558171、DeltaBlue 0.891080、Hexiom 0.629840、Raytrace 0.817282、
  spectral-norm 0.018925。直前before/mainは0.6572716、候補/beforeは**0.9590923**だった。
  raw値、process時間、環境、hashを`sum-gen-tier1-full-*`へ保存した。
- 候補/beforeではHexiomが0.763138/0.755717/0.754421（平均0.757758）と全block短縮し、
  Raytraceも0.990964/0.953603/0.987319（平均0.977295）。BPE 1.002164、DeltaBlue 0.995298は
  方向混在、Btree 1.013977は第1 blockだけ遅く後半は同等、絶対時間約0.6 msのspectralは
  1.008062で方向混在だった。目的workloadの大幅改善、全体平均の改善、他5本に一貫した大回帰が
  ないため、Tier-1 sum集約を現時点の採用候補とする。
- 次は現候補binaryを固定保存し、DeltaBlue/Raytrace/BPEの最新profileと到達可能side traceを
  取り直す。既存counterで成功/guard退出比を確認し、evaluator内のCALL、iterator、allocation、
  lookupのself timeと照合する。次のprototypeは複数workloadへ波及する一経路、または最も比率の
  高いDeltaBlueの一つの支配経路に限定する。専用sumの追加monitoring/pending-work/call-shape testと
  lintは次のsource変更前にも実施可能なため並行して仕上げる。目標算術平均0.5は未達で継続する。

- 追加した監視回帰testにより、generator codeのinstrumentation versionが最新でもlocal
  instruction monitoringが有効な状態ではTier-1専用opcodeがgenerator本体を省略し、callbackが
  発火しない不具合を検出した。version比較は更新待ちの有無だけを示し、active monitorが空である
  ことを保証しない。実行時にgenerator codeの`active_monitors`を全イベント分検査し、monitoring
  data未割当時はinterpreterのglobal monitorsを検査して、一つでも有効なら通常CALLへ戻すよう
  修正した。testはlocalとglobalのinstruction callbackが入力を途中変更する場合の結果、イベント
  発火、専用counter不変に加え、builtin `sum`差し替え後の通常callを検証する。
- 次は生成物を更新してこのtestをdebug/native両方で先に通す。その後、関連3 test filesを順次
  再実行し、LLVM stencilと実行ファイルを作り直す。監視ガードによる通常時の性能影響をHexiomの
  対応比較で確認してから、最新profileに基づく次の支配経路へ進む。

- 固定bootstrap `build-tier2-debug/python`で全case生成物を更新し、debug Tier-2を再構築した。
  local/global monitoringとbuiltin差し替えを含む追加testは成功した。関連fileを共有workerの
  順序依存から分離して実行し、region 205件、Tier3 14件、C API opt 321件の計540件が成功した
  （skip 3）。監視中はcallbackが発火して途中変更後の結果2を返し、専用成功counterは増えない。
- 次は同じbootstrapで再生成してbyte同一性を確認する。続いてLLVM 21/no-vectorizationでnative
  stencilを強制更新し、PGO/LTOなしでnative実行ファイルを再リンクする。nativeでも追加testと
  540件を再検証し、通常時の専用counterおよびJIT codeを確認する。

- 2回目の全case再生成は対象12生成物のSHA-256がすべて一致した。LLVM 21.1.8、
  `-fno-vectorize -fno-slp-vectorize`でstencilを強制再生成し、PGO/LTOなしのnative buildを
  更新した。JIT available/enabledはともにtrue。nativeでも追加監視test、region 205件、Tier3
  14件、C API opt 321件の計540件が成功した（release固有skip計14）。修正後binaryのSHA-256は
  `fee258fedf9c8926fc9a7d6c64d14d18d05630de4c07fc45bc7e39cd97953532`。
- 監視ガード直前binaryとのHexiom既定policy比較は、固定CPU 2、3 warmups・10 values、開始順
  回転の3 blocksで0.999994/0.999913/0.994255、幾何平均**0.998050**だった。全checksum一致、
  除外0、開始/終了hash一致で、`sum-monitor-guard-*`へ保存した。通常実行の有意な回帰はなく、
  修正後binaryを`python-sum-gen-tier1`として固定し、旧版を
  `python-sum-gen-tier1-before-monitor-guard`へ保存した。
- 次は修正後binaryでDeltaBlueの到達可能side trace、専用counter、native perf self timeを再採取
  する。`Plan.execute`のexact-list iterationと`EqualityConstraint.execute`の高頻度callが支配的
  という以前の観測を検証し、genericな型・code・layout guardで安全に省略できる範囲を決める。
  prototypeはまず単一call fusionかbounded scanの小さい方を実装し、形成/callback/monitoring/
  invalidation testと単独対応測定で採否を決める。

- 修正後nativeのresident probeはDeltaBlueに14 executors、151,552 native bytesを形成した。
  `Plan.execute` traceは各workloadで約1万件の`EqualityConstraint.execute`をinlineし、その各回で
  `input`/`output`相当の条件付きcallを2回実行する。10 warmups後の3 samplesではcall fusionが
  1 sample当たり21,594〜22,192回成功した。2000 measured valuesの`cycles:u` profileはlost sample
  0で、evaluator 17.50%、frame clear/pop 5.53%、list iterator 3.07%、type/method lookup約4%、GC
  3.31%を示した。生probeとperf dataを`sum-guard-current-deltablue*`へ保存した。
- 単一callだけを専用化してもlist iterationと各constraintのframe境界が残るため、より小さな
  bounded scanを採る。`Plan.execute`で1件を通常どおり実行し、execute/input/outputのfunction
  version、型・属性layout、monitoring/pending checkが全て通った直後だけ、同じexact-list iterator
  の後続最大64件を処理する。各件は同じ型version・条件分岐・属性offsetを要求し、source/old
  destination valueがcompact exact intの場合だけ順番に参照コピーする。不一致の要素と最後の
  1件は未消費のまま通常loopへ残す。
- scan中に減る可能性がある参照はexact intだけで、allocation、Python callback、frame transitionを
  起こさない。iterator indexとloop localは最後に処理した要素へ更新するため、次のheader periodic
  checkから見える状態も通常反復と一致する。先行する通常1件のfunction/instrumentation guardsを
  再利用することで、raw function pointerを追加cacheへ保持せずcode差し替えにも対応する。次は
  このstrict trace matcher、packed layout、専用counterと値伝播/停止/監視/invalidation testsを
  debug Tier-2へ実装する。

- bounded equality scanの初版uopとtrace matcherを実装した。matcherはexact list iterator、同じ
  loop local、`execute`のtype/function guard、完全なcall frame、既存の二つの条件付き属性call、
  source value load、destination value store、None return、直後のloop backを全て要求する。
  cacheには二つのtype version、4属性offset、directionのint8定数と比較maskだけを保持し、関数や
  一時traceへのraw pointerは追加していない。runtimeは最後の1件と最初の不一致を未消費で残す。
- instanceごとの同名method差し替えはtype versionだけでは除外できないため、constraint型のinline
  shared keysに`execute`/`input`/`output`のいずれかが現れた時点でscan全体を停止する。各後続要素に
  materialized dictがある場合も停止する。通常の`v1`/`v2`/`direction`などのinline属性は許可する。
  source/destinationは観測済みtype/layoutを再検証してからdict pointerへ触れるようにし、NULLに
  なり得る終了済みlist iteratorのsequenceも先に検査する。
- 次はcase/global-object生成物を更新してdebug buildをコンパイルし、最小DeltaBlue型probeで
  matcher形成、値伝播、counter、長さ境界を確認する。形成しなければoptimizer各段階の実uop列と
  matcherの最初の不一致を調べて形を狭く修正する。形成後に正式なfallback/monitoring/invalidation
  testsを追加する。

- case生成時、結果Noneを捨てる`DEAD(result)`より前でstack outputを同期しようとしてgeneratorが
  live input errorを出したため、assert直後にresultをdeadとした。またmethod shadow helperをCの
  条件block内で呼ぶと生成されたstack pointerのbranch mergeが不整合になったため、安全な型を
  選んで単一の直線代入式から呼ぶ形にした。debug生成Cのstack cache遷移と実行assertを確認し、
  crashなく反復できる状態にした。
- DeltaBlueのPlanは`OrderedCollection(list)`を反復する。iteratorはexact `PyListIter_Type`であり、
  list subclassの内部配列を直接読むのは通常iteratorと同じ意味なので、underlying sequenceは
  `PyList_Check`まで許可した。変更後のdebug probeは新uopを形成し、5 workloadsで921 entries、
  44,656 iterationsをscanした（短い末尾によるmiss 461）。benchmarkの完全なresult検査も成功した。
- methodの`__name__`だけでは、別名のclass attributeに同じfunctionを置いた場合のshadow keyを証明
  できない。optimizerでconstraintのrecorded typeを取得し、generic getattroとMRO全dictを調べ、
  各functionが`execute`/`input`/`output`という唯一のkeyにだけ格納される場合に限定した。runtimeの
  shared-key検査が実際のlookup名を保護する。function aliasや追加effectのあるexecuteは形成拒否する。
- 4つの正式debug testsを追加し、list subclass・長さ0/1/2/3/64/65/66/129、130-link伝播、同一intの
  refcount安定、direction不一致、int subclass、old-value finalizer、3種類のinstance method shadow、
  `execute.__code__`差し替え、execute/input/outputのlocal monitoring、追加effectと別名functionの
  形成拒否を検証した。追加4件は全て成功した。
- `regen-global-objects`の通常make targetは、untracked artifact内の保存sourceまでArgument Clinicが
  走って既存の古いclinic記法で停止した。case生成自体は固定debug bootstrapで成功し、global object
  generatorを直接実行して`execute`/`output` IDを正しく更新した。次は診断文字列が残っていないことと
  2回目生成のbyte同一性を確認し、region file全体、Tier3、C API optを別tempdirで順次実行する。
  その後だけLLVM 21 native stencilを更新し、DeltaBlue単独の対応比較で採否を決める。

- bounded equality scanのcase/global-object生成を固定bootstrapで再実行し、対象16生成物のSHA-256が
  すべて一致した。診断出力はsourceに残っておらず、`git diff --check`も成功した。debug Tier-2では
  region 209件（追加4件を含む）、Tier3 14件、C API opt 321件の計544件が成功した（skip 3）。
  C API optは先の出力切り詰めで終了状態を判定できなかったため別tempdirで再実行し、321件全成功を
  明示的に確認した。
- 次は保存済み採用候補`build-jit/python-sum-gen-tier1`を比較基準として維持したまま、LLVM 21.1.8と
  `-fno-vectorize -fno-slp-vectorize`でnative stencilを強制再生成し、PGO/LTOなしで再リンクする。
  nativeでJIT availability、scan形成/counter、同じ544件を確認してから、DeltaBlueを固定CPU・開始順
  回転・複数blockで対応測定する。改善が測定ノイズを越えない場合はこのprototype全体を戻す。

- LLVM 21.1.8と指定のvectorize無効化だけでnative stencilを強制再生成し、PGO/LTOなしの`-O3`
  buildを更新した。新binaryのSHA-256は
  `3ff5d4ca8d8dc4148c3ac7caed093f9d5f27e98f7e638310cf26816416a49860`で、保存済み比較基準は
  `fee258fedf9c8926fc9a7d6c64d14d18d05630de4c07fc45bc7e39cd97953532`のまま保持している。
  `PYTHON_JIT=1`でavailable/enabledはいずれもtrueだった。
- DeltaBlueのresident native probeは14 executors、151,552 native bytesを確認した。1 sampleでscan
  200 entries・9,700 iterations・100 missesとなり、call entriesは従来probeの約21,500から2,792へ
  減った。checksum検査も成功しており、狙ったEqualityConstraint経路をnative codeで処理している。
  nativeでは追加4件、region全209件、Tier3 14件、C API opt 321件の計544件がすべて成功した
  （release構成のskip計14）。
- 次はDeltaBlueだけを比較基準と新binaryで対応測定する。CPU 2へ固定し、同一のresident/全実験flag、
  3 warmups・10 values、開始順を回転する3 blocksを使う。各blockのchecksum・binary/script hashと
  実験環境を保存し、after/before比の方向と分散から採否を決める。採用できれば全6本screenを再実行し、
  算術平均と幾何平均の両方を更新する。

- DeltaBlue単独のbefore/after対応測定は、固定CPU 2、resident、全実験flag、3 warmups・10 values、
  開始順回転の3 blocksでafter/beforeが0.871664/0.874839/0.873301、幾何平均**0.873267**だった。
  全checksum一致、除外sample 0、測定前後のbinary/script hash一致で、artifactは`equality-scan-*`へ
  保存した。3 blockの方向と大きさが揃っており、bounded scanはDeltaBlueを約12.7%改善するため
  採用候補として維持する。
- 次は同じ二つのbinaryと条件で6 workloadを3 blocks測定する。Equality scanが形成しない5本で
  matcher追加と大きなstencilによる回帰がないことを確認し、before比を保存済みmain比へ合成して
  新しい算術/幾何平均を求める。必要ならmainも同じblock内に加えて直接再測定する。

- main・直前候補・scan候補を同じblock内で直接比較する6-workload screenを完了した。固定CPU 2、
  3 warmups・10 values、3 blocks、3者の開始順回転で、scan候補のmain比はBPE 0.816590、Btree
  0.550218、DeltaBlue **0.765325**、Hexiom 0.621888、Raytrace 0.829096、spectral 0.018642。
  算術平均は**0.600293**（直前0.619313）、幾何平均は**0.385951**（直前0.395252）まで改善した。
- scan候補/直前候補はBPE 1.000102、Btree 0.998343、DeltaBlue **0.871802**、Hexiom 0.997822、
  Raytrace 1.000858、spectral 0.997275、全体算術平均0.977700だった。全checksum一致、除外sample 0、
  開始/終了hash一致で、artifactは`equality-scan-full-*`へ保存した。目的経路以外に一貫した回帰は
  なく、このprototypeを採用し、binaryを`build-jit/python-equality-scan`として固定した。
- 次は現在比率が最も高いRaytraceとBPEを優先してresident probeとnative `perf`を取り直す。
  既存のcall/float/int/iterator counterと到達可能side traceを照合し、複数workloadに効く残存経路、
  またはRaytraceの単一支配経路を一つ選ぶ。新prototypeもsource変更前binaryとの単独対応比較を先に
  行い、改善が確認できた場合だけ6本screenへ進む。目標算術平均0.5は未達のため継続する。

- 固定したscan版でRaytrace/BPEのresident coverageと`cycles:u` profileを再採取した。Raytraceは
  74 executors・1,093,632 bytes、1 sampleで短縮call 814,015、class初期化278,389、float属性融合
  357,438。lost sample 0のprofileはevaluator 4.27%、frame clear/pop約6.7%、managed-dict/object
  deallocation、float allocation、frame初期化を上位に示した。monitoringによる別診断では1 workloadに
  `Vector.dot` 509,871 calls、`mustBeVector` 520,539 calls、Vector初期化452,943 callsがあった。
- BPEは37 executors・192,512 bytesで、1 sampleにlen融合13,765,892、zip 3,344,210、tuple比較
  3,842,834、pair scan 1,672,794 iterationsを確認した。lost sample 0のprofile上位はdict lookup、
  tuple/list確保・破棄、GC、slice、zip/list iteratorであり、一つの安全な既存uop境界より複数allocationの
  合成だった。以前のzip/Counter scanは空振り費用で回帰しているため、同じ案は繰り返さない。
- 次のprototypeはRaytraceの`Vector.dot`型call境界を対象にする。完全なcallee code形
  `guard_method(); a.x*b.x + a.y*b.y + a.z*b.z`と、既に形成した6属性float融合を同時に要求し、
  callee frameとguard method frameを省く。runtimeはouter/inner function version、instrumentation/
  pending work、type version、instance method shadow、6属性layoutとexact floatを再検証する。演算は
  3 multiplyと2 addのbinary64境界を維持し、結果floatを1個だけ生成して元の逆順cleanupを行う。
  まずdebugで形成・code/method/shape変更・monitoring・丸め・allocation failureを検証し、nativeで
  約51万callへの適用とRaytrace単独比を確認してから採否を決める。

- `Vector.dot`型call fusionの初版を実装した。callee全bytecodeを走査し、引数2個、例外tableなし、
  `other.guard(); self.x*other.x+self.y*other.y+self.z*other.z`だけであること、guard側も引数をそのまま
  返す3命令だけであることを証明する。recorded trace側では通常のfunction/stack/recursion guard、
  inner trivial call、既存6属性float融合、RETURNまでを完全一致させる。slot-only型は対象外とした。
- 新uopのcacheは6個の属性offset、type/inner-function version、guard名index、caller復帰offset、
  最終加算offsetの整数だけで、関数・型pointerは保持しない。runtimeはouter/inner codeのpending workと
  active monitor、PEP 523、同一type/version、inline-values有効性、shared-key上のinstance method shadow、
  exact floatを演算前に検査する。確保失敗時だけ省略したcallee frameを再構築し、最終加算位置から
  Tier 1の例外処理へ渡す経路も追加した。
- 次はcase generatorを先に実行し、stack-effect解析とnative移行分岐が受理されるか確認する。生成または
  compile errorはその場でcache packing/ownershipを修正する。debug build後、最小guard付きdotで形成と
  counterを確認してから、正式なinvalidation/monitoring/rounding/allocation-failure testsを追加する。

- Tier-2 generatorのownership検査とdebug compileは成功した。最小guard付きdotは新しい
  `_CALL_PY_FLOAT_DOT`を形成し、入力8反復のうちtrace到達後7回を専用counterで確認して結果56.0を
  返した。既存float融合後には消去済みuop/recordが多数残るため、matcherの探索上限を80から192へ
  広げたが、callee全bytecodeとRETURNまでの完全証明条件は変えていない。
- 確保失敗の初回probeは、新frameを作った後のstackpointerがvalidな状態で`RELOAD_STACK`がinvalidを
  仮定するdebug assertionを検出した。通常の`_PUSH_FRAME`と同じくcallerを`SAVE_STACK`してからframeを
  切り替えるよう修正した。再probeではMemoryErrorの最内tracebackがdot codeの最終加算offset 216、
  localsのself/otherが元objectとなり、例外後の反復も56.0を返した。
- 正式testを5件追加し、形成・counter・参照数・同一object入力、operationごとのbinary64 rounding、
  instance guard shadow、guard/dotの`__code__`差し替え、float subclass、materialized dict、slot-only型と
  副作用付きguardの形成拒否、dot/guard双方のlocal instruction monitoring、debug allocation failureを
  検証した。5件はdebug Tier-2で全成功した。
- 次はglobal monitoring caseも同じtestへ加え、既存float test群とregion file全体を順次実行する。
  その後case生成をもう一度行ってbyte同一性と`git diff --check`を確認する。debug回帰がなければ、
  LLVM 21/no-vectorizationでnative stencilを更新し、native tests、Raytrace coverage、対応測定へ進む。

- `Vector.dot` call fusionにglobal instruction monitoringも追加し、outer/inner local monitoringと合わせて
  専用uopを使わず通常の監視イベントを出すことを確認した。region全214件、Tier3 14件、C API opt
  321件の計549件がdebug Tier-2で成功した（skip 3）。確保失敗時のcallee frame、最終加算offset、
  self/other localsの復元もfull region run内で成功している。
- full regionの初回実行では既存equality-scan 4 testが統計辞書の末尾key欠落を検出した。新しい
  float call counterを2個追加した際、`Py_BuildValue`のformatだけ66項目のままだったためで、formatを
  実際の68 key/value pairに合わせた。equality scanの実行・counter本体に異常はなく、修正後は同じ
  214件が全成功した。
- 次は固定したdebug executableでtier2/uop-id/uop-metadata生成を再実行し、全tracked変更の前後hashが
  一致することと`git diff --check`を確認する。続いてLLVM 21.1.8、vectorize無効化、PGO/LTOなしで
  native stencilとbinaryを更新し、同じ549 testとnative code形成を確認する。その後Raytrace単独の
  scan版/float-call版を固定CPU・開始順回転で測定し、改善が安定した場合だけ6本screenへ進む。

- 固定debug executableでtier2/uop-id/uop-metadata generatorを再実行した。tracked変更27ファイルの
  SHA-256は生成前後ですべて一致し、`git diff --check`も成功した。`FLOATDOT`等の一時診断文字列は
  残っておらず、stats formatとkeyはいずれも68項目で一致している。
- 次は保存済みscan版`build-jit/python-equality-scan`のhashを再確認して保持し、LLVM 21.1.8と
  `-fno-vectorize -fno-slp-vectorize`でnative stencilを強制再生成する。PGO/LTOなしの通常`-O3`
  link後にavailability/enabled、専用uopのnative code、同じ549 testを確認する。

- LLVM 21.1.8と指定のvectorize無効化でnative stencilを強制再生成し、PGO/LTOなしの`-O3` binaryを
  更新した。新binaryはSHA-256 `b04b2d4aee6a44b03461162279eea112b85c5c499c6136351e075c986f30d743`、
  保存済みscan版は`3ff5d4ca8d8dc4148c3ac7caed093f9d5f27e98f7e638310cf26816416a49860`
  のままである。`PYTHON_JIT=1`でavailable/enabledはいずれもtrueだった。
- native最小probeは`_CALL_PY_FLOAT_DOT`を含む43 uopsのexecutorを形成し、8反復で7 entries、結果
  56.0、`get_jit_code()` 4096 bytesを確認した。release nativeでもregion 214件、Tier3 14件、
  C API opt 321件の計549件がすべて成功した（構成依存skip 15）。
- 次はRaytrace一回分の前後で到達可能side traceを含むexecutor counterを集計し、専用call entries、
  generic call削減、native bytes、checksumを確認する。その後scan版とのRaytrace対応測定を行う。

- Raytrace native coverageでは専用uopが352,553 callsを処理し、generic call entriesを814,015から
  461,462へ同数削減した。exact-float条件を満たさない60,002 callsは安全にguard exitし、float属性
  fusionは357,438から4,885へ減った。到達可能executorは74から71、native bytesは1,093,632から
  1,032,192へ減り、checksumも一致した。
- しかしscan版との固定CPU 2・resident・3 warmups・10 values・開始順回転3 blocksのRaytrace対応
  測定はafter/before 1.055000/1.076744/1.082423、幾何平均**1.071323**で全block回帰した。
  checksum、binary/script hashは全て一致し、除外sampleは0。毎callのtype lookup、shared-key lookup、
  monitoring全event走査を含むruntime再検証が、frame省略の利益を上回ったため初版は不採用とした。
- 初版binaryとcoverage/perf/measurement artifactは`python-float-dot-call-rejected`および
  `float-dot-call-*`へ保存した。専用source/test/counterを削除して3 generatorを再実行し、識別子が
  source/generated filesから消え、stats format/keyが既存66項目へ戻り、`git diff --check`も成功した。
- 次は同じ完全body proofを使いつつ、既存optimizer dependencyとcall直前のfunction/type guardsを保持する
  軽量版を試す。実測probeではguard/dotの`__code__`変更、class method置換、instance shadow、local
  monitoringの全てが親executorを即時invalidateしている。したがって軽量uopは既存float属性uopと同じ
  type/layout/exact-float guards、eval breaker、合成frameのstack-space/recursion条件だけをruntimeで検査し、
  lookupとmonitor配列走査を行わない。まずdebug安全性を再検証し、Raytrace単独で初版より先に採否を決める。

- 軽量`_CALL_PY_FLOAT_DOT`を実装した。初版のtype lookup、shared-key lookup、全monitor event走査を除き、
  post-pass前にoptimizerが登録済みのtype/function/keys/monitoring dependenciesと、call直前に残るouter
  function guardを利用する。runtimeはdot codeのeval breaker、二重call相当のrecursion/stack space、
  元の`_FLOAT_ATTRIBUTE_SUM_PRODUCTS`と同じtype version・inline-values・6 exact floatsだけを検査する。
  cacheは6 offsets、inner identity frame size、元のlayout、caller return offsetのみでpointerを保持しない。
- 軽量版には形成/counter、参照所有、同一object、operation単位binary64丸め、instance method shadow、
  guard/dot code変更、float subclass、置換`__dict__`、slot-only/副作用body拒否、local/global monitoring、
  低recursion limitでの保守的deopt、debug allocation failureの6 testを追加した。region 215件、Tier3
  14件、C API opt 321件の計550件がdebug Tier-2で成功した（skip 3）。
- 次は3 generatorを再実行してbyte同一性とdiff/styleを確認する。問題がなければnative stencilを更新し、
  native550件とcoverageを確認後、Raytraceをscan版と3 blocks対応測定する。初版比ではなく保存済みscan版を
  採否基準とし、改善しない場合は軽量版も削除する。

- 軽量版のtier2/uop-id/uop-metadata generatorを固定debug executableで再実行し、tracked変更27ファイルの
  SHA-256は前後ですべて一致した。stats format/keyは68対68、臨時診断なし、`git diff --check`成功。
- 次はLLVM 21.1.8、vectorize無効化、PGO/LTOなしでnative stencilを強制再生成し、軽量版binaryのhash、
  JIT availability、専用native code、release nativeの550 testを確認する。

- LLVM 21.1.8と`-fno-vectorize -fno-slp-vectorize`でnative stencilを強制再生成し、PGO/LTOなしの
  release JITを更新した。軽量版binaryのSHA-256は
  `c3cecc642adb71b95585f8fabbc642db1db6a697ec96972f41d27fe39033f0ea`、比較用scan版は
  `3ff5d4ca8d8dc4148c3ac7caed093f9d5f27e98f7e638310cf26816416a49860`のままで、
  `PYTHON_JIT=1`でavailable/enabledはいずれもtrueだった。
- native最小probeは43 uopsのexecutor内に`_CALL_PY_FLOAT_DOT`を形成し、8反復で7 entries、結果56.0、
  `get_jit_code()` 4096 bytesを確認した。release JITでもregion 215件、Tier3 14件、C API opt 321件の
  計550件が成功した（構成依存skip 15）。
- 次は固定CPU 2・同一resident設定でRaytrace一回分の前後counter、到達可能side trace、native bytes、
  checksumを採取する。専用callが初版同等の対象を処理し、削除したlookup/monitor走査なしで安全に動くことを
  確認後、保存済みscan版との3 blocks対応測定で採否を決める。

- 軽量版のRaytrace native coverageは専用call 352,553 entries、exact-float等のguard exit 60,002で、
  初版と同じ対象を処理した。generic callは814,015から461,462、float属性融合は357,438から4,885へ減り、
  到達可能executorは74から71、native bytesは1,093,632から1,019,904へ減った。専用lookup/monitor走査を
  除いた状態でもchecksumは保存済みscan版と一致した。
- 固定CPU 2・resident・3 warmups・10 values・開始順回転3 blocksのscan版/軽量版Raytrace対応測定は、
  after/before 0.954337/0.958651/0.945995、幾何平均**0.952980**で全block改善した。binary/script hashは
  開始時と終了時で一致、pixel checksum一致、除外sample 0だった。軽量版を
  `build-jit/python-float-dot-light`（SHA-256
  `c3cecc642adb71b95585f8fabbc642db1db6a697ec96972f41d27fe39033f0ea`）として固定した。
- 次はmain・保存済みscan・軽量dotの3 binaryを6 benchmarkで同じCPU、warmup/value数、開始順回転により
  直接比較する。Raytrace改善が他workloadの形成探索やnative code layoutを悪化させず、6本のmain比幾何平均を
  改善することを確認してから採用を確定する。

- main・scan・軽量dotの6本直接比較を固定CPU 2、3 blocks、各3 warmups/10 values、開始順回転で完了した。
  軽量dot/mainはBPE 0.821280、Btree 0.555937、DeltaBlue 0.758677、Hexiom 0.628831、Raytrace
  **0.803884**、spectral 0.018583で、6本算術平均**0.597865**、幾何平均**0.384949**だった。
  scan/mainは同じrunで算術平均0.599305、幾何平均0.385389であり、軽量dotは両方を改善した。
- 軽量dot/scanはRaytrace 0.975258、他はBPE 1.004726、Btree 1.004678、DeltaBlue 1.000552、
  Hexiom 1.007879、spectral 1.000490、全体算術平均0.998930、幾何平均0.998870だった。全checksum一致、
  除外sample 0、binary/script hash不変。対象外5本の小幅なcode-layout回帰を含めても全体指標は改善するため、
  軽量dot fusionを採用する。
- 次は軽量dot版Raytraceの`cycles:u` profileと残存counterを採取する。dot frameを除いた後も多いVectorの
  class construction、他の算術method call、result allocation/cleanupのどれが支配的かを特定し、完全body proofを
  再利用できる単一経路を選ぶ。候補ごとに保存済み軽量dot binaryとのRaytrace対応測定を先に行う。

- 軽量dot版Raytraceの`cycles:u` profileはlost sample 0で、evaluator 7.23%、frame clear/pop約6%、
  object/managed-dict解放約5%、float確保2.74%、frame push/local初期化約4%が残った。Python call診断では
  1 workloadに`Point.__sub__`/`Point.isPoint`各277,865回、`Vector.scale`149,743回、
  `Vector.normalized`/`magnitude`各109,887回、`Ray.__init__`98,172回を確認した。
- `Point.__sub__`は同一exact heap type同士の減算が支配的で、通常のnumeric dispatchが毎回
  `slot_nb_subtract`、special-method lookup、Python vectorcallを経る。次のprototypeはoptimizerが観測した左右typeが
  同一で、type自身のgeneric `slot_nb_subtract`とexact Python `__sub__`を確認した場合だけ、type/function dependencyと
  一体の専用uopへ置換する。uopは両exact typeをguardして関数を直接vectorcallし、`NotImplemented`なら通常と同じ
  TypeErrorにするため、反射演算やsubclass優先順位を変えない。
- まずgeneric slot判定helper、末尾配置の専用counter、同一type/NotImplemented/method・code変更/monitoring/refcountの
  testsをdebug Tier-2で検証する。native化後はPoint減算の適用回数とRaytrace単独の保存済み軽量dot比で採否を決める。

- 同一exact typeのPython `__sub__`を直接vectorcallする`_BINARY_OP_PY_SUBTRACT_EXACT`を実装した。
  optimizerはCALL_REGIONS有効時の`NB_SUBTRACT`に限り、左右の観測type一致、非ゼロtype version、標準の
  `slot_nb_subtract`、type自身のdictにあるexact `PyFunctionObject`を要求する。継承method、staticmethod、
  異種type、C実装slotは通常経路に残す。
- cacheはfunction pointerとtype versionで、runtimeは左右のexact type一致とversionを関数pointerの参照前に
  guardする。呼び出し中にtype dictから旧functionが除かれても安全なよう一時INCREFし、同一typeで
  `NotImplemented`が返れば通常のbinary dispatchと同じTypeErrorを生成する。type pointerだけをcacheする案は、
  実行中のmethod変更後も同じtypeなら古い関数を呼べるため採用しなかった。
- 4 generatorのうち最初の3つは直ちに成功した。optimizer generatorは条件内のdict lookupが分岐片側だけ
  stackをmaterializeするため初回失敗したので、判定・type watch・function dependencyを
  `get_exact_python_subtract()`へまとめ、全経路で一度呼ぶ形にして成功した。debug Tier-2 buildも完了し、
  最小probeは1 executorに専用uopを形成、8反復中7 entries、guard exit 0、結果12を確認した。
- focused 5 testsは全成功した。形成/counter/refcount/同一object、異種typeから`__rsub__`へのdeopt、同一typeの
  `NotImplemented`で反射methodを呼ばないこと、method・`__code__`変更、呼び出し中のmethod置換、local instruction
  monitoringを検証した。継承method、staticmethod、int subclassのC/inherited slotには形成しないことも確認した。
- 次はregion file全体、Tier3、C API optをdebugで順次実行する。成功後に4 generatorを再実行してbyte同一性と
  `git diff --check`を確認し、LLVM 21・PGO/LTOなしのnative buildへ進む。

- 最終helper差分を反映したdebug Tier-2でregion **220件**、Tier3 14件、C API opt 321件が全成功した
  （C API optの既存skip 3）。method置換ではexecutorの即時invalidateまたはtype-version guard exitの
  どちらでも旧functionを呼ばないことをtestし、今回のbuildではguard exit経路も通った。
- tier2/uop-id/uop-metadata/optimizerの4 generatorを再実行し、tracked差分30ファイルの生成前後SHA-256は
  全て一致した。`git diff --check`成功、stats formatとkey/counterは70対70で一致している。
- 次はLLVM 21 preflightを再確認し、`-fno-vectorize -fno-slp-vectorize`でnative stencilを強制再生成する。
  PGO/LTOなしのrelease JITをlink後、専用uopのnative code、同じ555 test、Raytrace counterを確認する。

- `/usr/lib/llvm-21`（LLVM 21.1.8）をpreflightで再確認し、vectorization無効化でnative stencilを
  強制再生成した。PGO/LTOなし、`-O3`のrelease JITをlinkし、候補binaryのSHA-256は
  `9c155019d26288da7d08a276b58507925631161f34402bc1c00dd147700551b1`。比較対象の軽量dot版は
  `c3cecc642adb71b95585f8fabbc642db1db6a697ec96972f41d27fe39033f0ea`のままである。
- `PYTHON_JIT=1`でJIT available/enabledはいずれもtrue。native最小probeはexecutor内に
  `_BINARY_OP_PY_SUBTRACT_EXACT`を形成し、8反復で7 entries、guard exit 0、結果12、native code
  4096 bytesを確認した。release nativeでもregion **220件**（skip 11）、Tier3 14件（skip 1）、
  C API opt 321件（skip 3）の計**555件**が成功した。
- 次は固定CPU 2・resident設定でRaytrace一回の到達可能executorを前後追跡し、専用subtract entries、
  generic binary/call counter、guard exit、executor数、native bytes、checksumを軽量dot版と比較する。

- Raytraceの同時点coverage比較では、専用subtractが1 workloadで **277,784 entries**、guard exit 0を
  記録した。Python call profileの`Point.__sub__` 277,865回のほぼ全てを処理し、`check_result()`も成功した。
  uopは到達可能side traceを含む27 executorsに形成されるが、到達可能executor総数は前後とも71である。
- 他のregion counterは前後で一致した。native code総量は1,019,904から1,028,096 bytesへ8,192 bytes増加した。
  dispatch削減の利益と27 traceへのcode複製によるI-cacheコストはcoverageだけでは決められないため、
  保存済み軽量dot版と固定CPU 2、同一resident環境、3 warmups・10 values・開始順回転3 blocksで直接比較する。

- 軽量dot版とのRaytrace対応測定はcandidate/before **0.987373 / 0.978972 / 0.956414**、
  幾何平均 **0.974165**で3 blocks全て改善した。pixel checksum、開始・終了時のbinary/script hashは一致し、
  除外sampleは0。専用uopの約27.8万dispatch削減は8 KiBのcode増加を含めても実時間を改善した。
- 次はmain・軽量dot版・subtract候補の3 binaryを6 benchmarkで直接測定する。対象外workloadのcode layout変動を
  含む候補/軽量dot比と、同じrun内の候補/main比（各workloadおよび6本の算術・幾何平均）を確認して採否を決める。

- 6本の三者直接比較を固定CPU 2、3 blocks、各3 warmups/10 values、開始順回転で完了した。
  subtract候補/軽量dot版はBPE 1.005618、Btree 1.001924、DeltaBlue 0.998917、Hexiom 0.997244、
  Raytrace **0.970757**、spectral 0.997693。6本算術平均 **0.995359**、幾何平均 **0.995293**だった。
  Raytraceは0.971579/0.971372/0.969319と全block改善し、BPEの0.56%回帰を含めても全体指標は改善した。
- 同じrunの候補/mainはBPE 0.822950、Btree 0.551901、DeltaBlue 0.766383、Hexiom 0.625179、
  Raytrace **0.771098**、spectral 0.018617。6本算術平均 **0.592688**、幾何平均 **0.382339**。
  軽量dot/mainの0.596054/0.384151も同時に再測定しており、候補は両指標を改善した。全checksum一致、
  除外sample 0、binary/script hash不変のため、exact Python subtract直接呼び出しを採用する。
- 次はこの採用binaryを固定する。更新後のRaytrace profileとexecutorを調べ、残る`Point.isPoint`等のtrivial call、
  object生成、frame cleanupのうち、意味論を狭く証明できて反復回数の多い経路を次のprototypeに選ぶ。

- 採用版を`build-jit/python-python-subtract`へ固定した。SHA-256は候補と同じ
  `9c155019d26288da7d08a276b58507925631161f34402bc1c00dd147700551b1`である。
  更新後Raytraceの`cycles:u` profileはlost sample 0で、evaluator 5.98%、`_PyFrame_ClearExceptCode` 3.84%、
  `_PyEval_FrameClearAndPop` 2.66%、frame push/initと`initialize_locals`が各1.53%、`_PyEval_Vector` 0.97%だった。
  以前3.27%あった`slot_nb_subtract`支配経路は上位から消え、対応測定の改善と整合する。
- `Point.__sub__` 277,865回の座標typeを別診断したところ、全座標exact-floatの組はなく、int-float混在が
  109,005回、x/y float-floatかつz int-floatが93,526回、別の混在が60,000回などだった。このため
  exact-float 3項減算のbody融合は適用範囲がほぼなく、次候補にはしない。
- 次のprototypeは、既に限定したexact Python `__sub__`について、関数codeが通常の最適化済み2引数関数であることを
  optimizerで証明し、type/function versionとstack spaceをguardした上で`_PyFrame_PushUnchecked`へ引数を直接置く。
  汎用function vectorcallと`initialize_locals`のbindingを省く一方、実frameと通常evaluatorを使ってtraceback、
  recursion、monitoring、例外意味論を保つ。保存済み採用版とのRaytrace単独比較で小さな利益も再現しなければ戻す。
  その後、同じbinary二つを3 blocksの対応測定にかけ、安定した実時間改善がある場合だけ採用する。

- exact Python subtractのfast-frame prototypeを実装した。形成時に有効なfunction version、位置引数2、keyword-only 0、
  `CO_OPTIMIZED`を要求し、varargs/varkwargs/generator/coroutine/async-generatorは除外する。cacheにはtype versionと
  function versionを32 bitずつ格納し、runtimeで両方とdata-stack容量をguardしてから`_PyFrame_PushUnchecked`で
  `self`/`other`を直接localsへ置き、通常の`_PyEval_EvalFrame`で実行する。deopt時は従来のgeneric binary dispatchへ戻る。
- フレーム観測、`f_back`、`f_locals`、例外traceback、既存のmethod/code変更、monitoring、refcount、
  `NotImplemented`に加え、defaulted 3引数、varargs、keyword-only形の形成拒否を集中6 testで検証し全成功した。
  初回のtraceback test失敗は`assertRaisesRegex`が終了時に例外tracebackを消すtest側の問題で、`except`内検査へ修正した。
  `_PyEval_EvalFrame`はPEP 523 hook、再帰検査、current-frame接続、通常のframe cleanupをそのまま通り、stack不足だけを
  specialization前へdeoptする設計が既存のexact-call frame初期化と整合することもsource上で確認した。
- 次はdebug Tier-2でregion file全体、Tier3、C API optを逐次実行する。成功後に4 generatorの冪等性と
  `git diff --check`を確認し、LLVM 21・vectorization無効・PGO/LTOなしのnative buildとRaytrace対応測定へ進む。

- 全region初回実行でfast-frame testだけがgeneric `_BINARY_OP`に残った原因は、test内で
  `PYTHON_TIER2_CALL_REGIONS=1`を設定していなかったことだった。focused実行時の外部環境が欠落を隠していた。
  opt-inをtest自身へ移し、余分な動的code生成を使わず順序非依存にした後、region **221件**、Tier3 14件、
  C API opt 321件の計**556件**がdebug Tier-2で成功した（既存skip 3）。
- 固定debug executableでtier2/uop-id/uop-metadata/optimizerの4 generatorを再実行した。tracked差分30ファイルの
  SHA-256は生成前後ですべて一致し、`git diff --check`も成功した。
- 次は`/usr/lib/llvm-21`の完全prefixを再確認し、`-fno-vectorize -fno-slp-vectorize`でnative stencilを
  強制再生成する。PGO/LTOなしの通常`-O3` link後にJIT availability、専用native code、同じ556 testを確認する。

- LLVM 21.1.8 preflightは`/usr/lib/llvm-21`の4 toolsを全て確認した。system `python3.13`でのstencil生成は
  LLVM subprocess待機で進まない既知症状を再現したため中断し、AGENTS.md記載の固定
  `build-tier2-debug/python`へ切り替えると約34秒で正常完了した。vectorization無効化を維持し、成功後だけ
  `.jit-stamp`を更新した。PGO/LTOなし、通常`-O3`のrelease JIT linkも成功した。
- fast-frame候補binaryのSHA-256は
  `1503d9cf4f99d4dbe8fa90d44066b5c095a7a4724344b8b5ca52d50373157dd6`。`PYTHON_JIT=1`で
  available/enabledはいずれもtrue。native最小probeは34 uopsのexecutorに専用subtractを形成し、8反復で
  7 entries、guard exit 0、結果12、`get_jit_code()` 4096 bytesを確認した。
- release nativeでもregion **221件**（skip 11）、Tier3 14件（skip 1）、C API opt 321件（skip 3）の
  計**556件**が成功した。次はRaytrace一回の同時点counterと到達可能executorを保存済みdirect-subtract版と比較し、
  その後固定CPU 2・resident・3 warmups/10 values・開始順回転3 blocksの対応測定で採否を決める。

- Raytrace同時点coverageではfast-frame版と保存済みdirect-subtract版のregion counterが全項目一致し、専用subtractは
  **277,784 entries**、guard exit 0だった。到達可能executorは両方71、専用uopを含むexecutorは両方27で、
  native code総量だけが1,028,096から1,032,192 bytesへ4 KiB増えた。`check_result()`とscript hashも一致した。
- 固定CPU 2・resident・3 warmups/10 values・開始順回転3 blocksのRaytrace対応測定はcandidate/before
  **0.945876 / 0.975590 / 0.963437**、幾何平均 **0.961557**で全block改善した。checksum、開始・終了時の
  binary/script hashは一致し、除外sample 0。generic vectorcallと`initialize_locals`を省く変更だけで約3.8%改善した。
- 次はmain・保存済みdirect-subtract・fast-frameの3 binaryを6 benchmarkで同じprotocolにより直接比較する。
  Raytrace以外のcode-layout変動を含む全体幾何平均が改善した場合だけfast-frame版を採用する。

- 6本三者比較を固定CPU 2、3 blocks、各3 warmups/10 values、開始順回転で完了した。fast-frame/direct-subtractは
  BPE 0.993938、Btree 0.995356、DeltaBlue 0.997301、Hexiom 1.004323、Raytrace **0.959154**、
  spectral 0.997719。6本算術平均 **0.991299**、幾何平均 **0.991187**で全体を改善した。
- 同じrunのfast-frame/mainはBPE 0.819324、Btree 0.553119、DeltaBlue 0.762561、Hexiom 0.631762、
  Raytrace **0.749234**、spectral 0.018629。6本算術平均 **0.589105**、幾何平均 **0.380760**だった。
  direct-subtract/mainは0.595644/0.384177で、fast-frameは両指標を改善した。全checksum一致、除外sample 0、
  binary/script hash不変のためfast-frame版を採用した。
- 採用binaryを`build-jit/python-python-subtract-fast-frame`へ固定した。SHA-256は
  `1503d9cf4f99d4dbe8fa90d44066b5c095a7a4724344b8b5ca52d50373157dd6`。次はこの版のRaytrace
  `cycles:u` profileとPython call回数を再取得し、frame binding削減後の支配経路から次の限定的prototypeを選ぶ。

- 採用版Raytrace perfは6,449 samples、lost 0。`initialize_locals`はdirect-subtract版の1.53%から0.92%、
  `_PyEval_Vector`は0.97%から0.23%へ低下し、fast-frameの狙いと対応した。残る上位はevaluator 6.32%、
  frame clear 4.10%、float確保2.74%、object malloc/free各約2.3%である。
- Python callの型組を診断すると、同一exact typeの`Point - Point` 277,865回に続き、`Vector + Vector`が
  **20,000回**、`Vector - Vector`が5,333回、異種`Point + Vector`が5,333回だった。次のprototypeは同じ
  type/function-version/2引数frame証明をplain `NB_ADD`へ拡張する。異種型とin-place演算は反射・`__iadd__`
  規則が異なるため対象外に保つ。まずaddの形成・counter・反射guard・`NotImplemented`意味論をdebugで検証し、
  Raytrace coverageで実適用数を確認する。

- plain `NB_ADD`について、同一exact typeが標準`slot_nb_add`を持ち、type自身の`__add__`が有効なversionを持つ
  通常の2引数`PyFunctionObject`である場合だけ`_BINARY_OP_PY_ADD_EXACT`を形成するよう拡張した。
  subtractと同じtype/function versionおよびstack-space guardを使い、`self`/`other`を新しい実frameのlocalsへ
  直接置く。異種type、継承method、C slot、in-place addは従来dispatchに残り、同一typeで`NotImplemented`なら
  反射methodを再試行せず通常のTypeErrorを生成する。
- addの形成・entry counter・refcount・同一object結果と、異種typeの`__radd__`、`__code__`変更による無効化、
  同一typeの`NotImplemented`を集中2 testで確認した。test間で同じcode objectを再利用すると先に形成されたexecutorを
  引き継ぐため、add helperは毎回新しいcode objectを生成して順序依存を除いた。debug Tier-2ではfocused 2件、
  region **223件**、Tier3 14件、C API opt 321件（既存skip 3）がすべて成功した。
- 次は4 generatorを再実行してtracked生成物のSHA-256が変わらないことと`git diff --check`を確認する。その後
  LLVM 21・vectorization無効・PGO/LTOなしでnative stencilとrelease JITを再構築し、add専用uopのnative code、
  同じcorrectness suite、Raytraceでの実entry数を検証する。

- 固定した`build-tier2-debug/python`でtier2/uop-id/uop-metadata/optimizerの4 generatorを再実行した。
  tracked差分30ファイルのSHA-256は生成前後ですべて一致し、`git diff --check`も成功した。手書き定義と4系統の
  生成物は同期している。
- 次は`/usr/lib/llvm-21`の完全prefixをpreflightし、`-fno-vectorize -fno-slp-vectorize`を付けてnative stencilを
  強制再生成する。生成成功後だけ`.jit-stamp`を更新し、PGO/LTOなしの通常`-O3` binaryをlinkする。

- LLVM 21.1.8の4 toolsを`/usr/lib/llvm-21`で再確認し、固定debug executableによるnative stencil生成が
  約32秒で成功した。vectorization無効化を維持し、成功後だけ`.jit-stamp`を更新した。PGO/LTOなし、通常
  `-O3`のrelease JIT linkも成功し、候補binaryのSHA-256は
  `7522cfaf750982459ef83f0b117c361bcb28a5337bfbd2c7986de4ad8b715e77`である。
- 固定CPU 2、`PYTHON_JIT=1`、resident設定のnative最小probeは34 uopsのexecutorに
  `_BINARY_OP_PY_ADD_EXACT`を形成した。8反復中7 entries、guard exit 0、結果22、native code 4096 bytesで、
  JIT available/enabledはいずれもtrueだった。
- 次はrelease nativeでregion 223件、Tier3、C API optを逐次実行する。全成功後にRaytrace一回の同時点coverageを
  保存済みfast-frame subtract版と比較し、add entry数、guard exit、executor数、native code量を確認する。

- release nativeでもregion **223件**（skip 11）、Tier3 14件（skip 1）、C API opt 321件（skip 3）の
  計**558件**が成功した。最初にベンチ専用の`PYTHON_TIER3_JIT=resident`まで全region testへ渡すと、既存int領域
  27ケースが通常uop列のままで専用`_INT_REGION`を形成しなかった。これはaddの実行失敗ではなく形成期待の差であり、
  AGENTS.mdの検証条件どおり`PYTHON_JIT=1`だけで再実行して全成功を確認した。residentを使ったadd最小probe自体は
  native codeとcounterを検証済みである。
- 次は固定CPU 2、resident環境でRaytrace coverageを1 workload採取する。到達可能side traceを再帰的に含めて、
  add/subtract合計entry、add専用uopを含むexecutor数、guard exit、native code総量、checksumを保存済み
  fast-frame subtract版と比較する。

- Raytrace同時点coverageでadd拡張版は`binary_call_entries`が277,784から**297,584**へ19,800増え、
  guard exitは0のままだった。add専用uopは1 executor、既存subtract専用uopは両版とも27 executorsにあり、
  到達可能executor総数も両版71で一致した。他の全region counterとscript hashも一致している。
- native code総量は1,032,192から1,036,288 bytesへ4 KiB増えた。20,000回の論理`Vector + Vector`のうち
  warmup境界を除くほぼ全てに適用できているため、保存済みfast-frame subtract版と固定CPU 2、resident、
  3 warmups/10 values、開始順回転3 blocksの対応測定を行う。全blockでchecksumとbinary/script hashを検証する。

- 最初のRaytrace対応測定はcandidate/before **0.999516 / 1.019675 / 1.003120**、幾何平均
  **1.007399**で、安定した改善を示さなかった。checksum、開始・終了時のbinary/script hashは一致し、除外sampleは0。
  2番目のblockだけ約2%遅く、他2本は±0.3%内なので、20,000 dispatch削減の効果よりrun間変動が大きい可能性がある。
- この一組だけで採否を決めず、同じ固定CPU・環境・binaryを6 blocks（12 process）で再測定する。追加測定でも
  幾何平均改善が再現しなければ、4 KiBのcode増加に見合う実時間効果なしとしてadd拡張を戻す。

- 追加6 blocksはcandidate/before 0.982694、0.996248、1.018579、0.998399、0.975375、0.987910で、
  幾何平均0.993106だった。しかし最初の3 blocksと合わせた全9組では幾何平均 **0.997848**、中央値
  **0.998399**、改善6組・悪化3組、範囲0.975375〜1.019675で、推定利益0.22%はrun間変動より小さい。
  全checksum、binary/script hashは一致し、除外sampleは0である。
- addが観測されたのはRaytraceの約19,800 entriesだけなので、6本全体への期待値はさらに約1/6へ薄まる。
  新しい意味論経路と4 KiBのcode増加を採用する再現性がないため、このprototypeは不採用とする。候補binaryと
  coverage/対応測定artifactを保存してadd固有の手書き定義・testsを戻し、4 generatorと両buildを採用済み
  fast-frame subtract状態へ同期する。その後、残る高頻度経路をprofileから選ぶ。

- 不採用候補を`build-jit/python-python-add-fast-frame-rejected`へ保存した（SHA-256
  `7522cfaf750982459ef83f0b117c361bcb28a5337bfbd2c7986de4ad8b715e77`）。add固有のtype-slot helper、
  optimizer分岐、uop、集中2 testを除き、4 generatorを再実行した。tracked source/generated treeから
  `_BINARY_OP_PY_ADD_EXACT`と関連名が消え、`git diff --check`も成功した。
- 戻したdebug Tier-2でregion **221件**、Tier3 14件、C API opt 321件（既存skip 3）の計**556件**が
  全成功した。次はnative stencilを同じLLVM 21条件で再生成し、release JITをlinkして保存済み
  `python-python-subtract-fast-frame`とのbinary hashを照合する。

- LLVM 21でstencilを再生成してrelease JITをlinkした。全binary SHAはbuild timestamp/debug情報により
  `c424435a60ea33df7f060d1cb4c419f5cf8faddfb96e7274fb04cadb9d57a590`となったが、ELF `.text`は保存済み
  fast-frame subtract版とbyte-for-byte一致し、両方のSHA-256は
  `f4ca678828b1ee140b62d8c7412576fc16c30186c2270c3a523d0ca0b32c4e6e`だった。
- 現在のnative binaryでsubtract最小probeは専用uop、7 entries、guard exit 0、native code 4096 bytesを確認した。
  region 221件（skip 11）、Tier3 14件（skip 1）、C API opt 321件（skip 3）の計556件も全成功し、
  不採用add試作からの復元を完了した。
- 次は採用版の残り5 workloadを既存coverage/profile artifactと照合し、実行回数とCPU比率がともに大きい未融合経路を
  選ぶ。Raytraceの20,000回addのように測定ノイズ以下の候補は避け、複数workloadまたは数十万反復へ効く変更を優先する。

- 現在の採用版で5 workloadを再計測した。BPEではbytes-pair scanが956,013 entries、dict updateが
  2,259,345 entries、tuple構築が3,842,994 entries、zipが3,344,210 entriesに到達する一方、`cycles:u`
  profile（59,296 samples、lost 0）は評価器5.78%、dict lookup 4.14%、object free 4.08%、tuple dealloc
  3.98%、GC 3.47%、malloc 3.02%などへ分散していた。既存の限定uopをさらに細分化するより、残るPython callを
  調べる方が大きな削減余地を持つ。
- BPEの論理Python callを数えると、`most_common_pair = max(stats, key=lambda x: stats[x])`のlambdaが
  **1,815,343回**で突出し、`bpe_encode`自身は6,462回だった。現在のexecutorでは`max`を
  `_CALL_KW_NON_PY`で呼び、各候補についてlambda frameとgeneric dict subscriptを実行している。
- 次のprototypeはbuiltin `max(mapping, key=lambda key: mapping[key])`だけを認識する。形成時にbuiltin identity、
  keyword tuple、exact Python functionのcode/closure形、辞書のiteration/subscript slotを確認する。実行時には
  code version、monitoring/PEP 523、closure identity、dict layout、exact 2-tuple/exact bytes key、compact exact-int valueを
  全てguardし、辞書の挿入順を直接走査してstrict `>`だけで最初の最大keyを返す。空辞書・subclass・非compact値・
  callbackが必要な状態ではcall stackを変更する前にgeneric `CALL_KW`へ戻し、`max`の例外・tie・監視意味論を保つ。
- まずCALL_KWの既存3-word cacheにkey functionのcode versionを置く限定opcodeと、entry/iteration/guard-exit counter、
  形成・tie/identity・fallback・monitoring・builtin/code変更の集中testを実装する。debug Tier-2で通した後だけgenerator、
  native JIT、BPE coverage、保存済み採用版との対応測定へ進み、実時間改善が再現しなければprototypeを戻す。

- `CALL_KW_MAX_DICT_INT_KEY`を実装した。CALL_KWの3-word cache幅は変えずlambda code versionを保存し、runtimeで
  builtin identity、keyword、normal vectorcall、code/closure、caller/callee monitoring version、PEP 523、recursion、
  dict iteration/subscript slotを再確認する。全keyがexact bytes 2個のexact tuple、全valueがcompact exact intの場合だけ
  `PyDict_Next`の挿入順をstrict `>`で走査し、成功後にgeneric vectorcallと同じ順でstack refsを解放する。
  eval breakerは各要素で確認し、途中までの非公開走査を捨ててgeneric callへ戻せる。
- 新opcodeを含む全cases生成器は成功し、PGO/LTOなしのdebug Tier-2 buildも成功した。初回fallback testでcounterが
  増えなかったのは`n=1`ではloop backedge executorへ入らないためで、同じ処理を8反復して専用uopのguard exitを
  実際に通すよう修正した。集中5 testは全成功し、Counter subtypeでentry 8・iteration 768も確認した。
- 次はdebug buildでregion file全体、Tier3、C API optを別tempdir・逐次で実行する。成功後に全生成器の冪等性と
  `git diff --check`を確認し、LLVM 21 native stencilをvectorization無効、PGO/LTOなしで再生成する。

- debug全region初回では既存range形成4件が後半だけ失敗した。原因はbuiltin置換testがprocess全体の実builtins辞書を
  変更し、先行する既存test群と合わせてdict watcherの変更閾値を越えたことだった。max用関数へbuiltins辞書のcopyを
  渡し、そのcopyだけで置換を検証するようにしてglobal test stateを消した。またregion statsのformat項目数を
  `range_int32_iterations`を含む実73項目へ合わせ、末尾counter欠落を修正した。
- 修正後、debug Tier-2でregion **226件**、Tier3 14件、C API opt 321件の計**561件**が全成功した
  （既存skip 3）。max集中5件は全体順序内でも成功し、既存rangeの専用形成も復元した。
- 次は固定debug executableで`regen-cases`全体を再実行し、tracked生成物が冪等であることと`git diff --check`を
  確認する。その後LLVM 21の4 toolsをpreflightし、vectorization無効でnative stencilを強制再生成する。

- tracked差分30ファイルのSHA-256を固定して`regen-cases`全体を再実行し、全hashと対象ファイル集合が一致した。
  `git diff --check`も成功し、手書き定義とTier1/Tier2/optimizer生成物の同期を確認した。
- LLVM 21.1.8の4 toolsを`/usr/lib/llvm-21`で確認し、固定debug Pythonと
  `-fno-vectorize -fno-slp-vectorize`でnative stencilを強制再生成した。生成成功後だけ`.jit-stamp`を更新し、
  PGO/LTOなしの通常`-O3` release JITをlinkした。候補binaryのSHA-256は
  `e6a3174b48d4519d47b47ab9c3e87a52b32628ee919b830e9fbb382d8317b2a7`で、JIT available/enabledはいずれもtrue。
- 固定CPU 2・residentのnative最小probeは55 uopsのexecutorに`_CALL_KW_MAX_DICT_INT_KEY`を形成した。
  8呼び出し中7 entries、96要素ずつ計672 iterations、guard exit 0、結果identity維持、native code 4096 bytesを
  確認した。次はこのbinaryを固定保存し、release nativeでregion 226件、Tier3、C API optを逐次検証する。

- 候補binaryを`build-jit/python-max-dict-int-key-candidate`へ固定した。release nativeでもregion **226件**
  （skip 11）、Tier3 14件（skip 1）、C API opt 321件（skip 3）の計**561件**が全成功した。
  各regrtestはresident設定を外し別tempdirで逐次実行した。
- 次は固定CPU 2・residentでBPE一回のcoverageを採取し、保存済みfast-frame版の同時点artifactと、専用entry/
  iteration、guard exit、到達可能executor、native code量、checksumを照合する。実適用がlambda callの規模と
  対応した後にだけ、固定binary同士の対応timingへ進む。

- BPE native coverageで専用maxは**768 entries**、内部走査**1,815,343 iterations**、guard exit 0だった。
  これは事前profileのlambda call 1,815,343回と完全に一致する。ほかの主要counterは直前版と一致し、到達可能
  executorは37から36、native code総量は192,512から188,416 bytesへ4 KiB減った。`check_result()`も成功した。
- 固定CPU 2・resident・各process warmup 3/10 values・開始順反転のBPE 3-block対応測定は、候補/直前版
  **0.946426 / 0.960982 / 0.955712**、幾何平均 **0.954354**で全block改善した。checksumは全一致、
  除外sample 0、開始・終了時のbinary/script hashも一致し、約4.6%短縮を確認した。
- 次はmain・直前fast-frame版・max候補の固定3 binaryを全6 workloadで測る。既存の目標値と直接比較するため、
  fast-frame採用時と同一の3 blocks・3 warmups/10 values・固定CPU 2・開始順回転protocolを使い、全体幾何平均と
  非BPE workloadのcode-layout変動を含めて採否を決める。

- 全6本の3者screenではmax候補/直前版のBPE比が**0.955005 / 0.957254 / 0.960908**、平均
  **0.957722**で全block改善した。一方、非適用workloadはBtree 1.010803、DeltaBlue 1.000685、Hexiom
  1.000308、Raytrace 1.018176、Spectral 1.016241で、6本算術平均 **1.000656**、幾何平均 **1.000444**だった。
  checksum全一致、除外0、hash不変なので、BPEの直接利益は明確だがこの形の全体採用根拠はない。
- 同じrunの候補/mainはBPE 0.781056、Btree 0.560170、DeltaBlue 0.765081、Hexiom 0.636283、Raytrace
  0.756742、Spectral 0.019001、算術平均 **0.586389**、幾何平均 **0.381079**。直前版/mainの
  0.588830 / **0.380979**に対し算術平均は改善するが、ユーザー指定の幾何平均は僅かに悪化した。
- 専用経路が形成されないBtree/Raytraceで3 blockすべて同方向の変化があるため、まず追加したTier1 opcode/uopが
  後続IDとdispatch/native stencil配置を動かした範囲を調べる。既存`CALL_KW_NON_PY`を保持し、trace/optimizerでだけ
  限定uopへ置換できるなら、BPEの約4.2%利益を保ちながら非対象code layout変動を縮める。縮小案を実装・同じ
  correctness/coverage/BPE対応測定で検証し、全6本幾何平均が改善しない形は採用しない。

- 初版は`CALL_KW_NON_PY`以降の全specialized opcode IDを1ずつ動かし、release textを5,776 bytes増やしていた。
  縮小版ではTier1 specializationを元の`CALL_KW_NON_PY=155`のままにし、その既存Tier2 uop内でbuiltin max、2引数、
  opt-inを先に確認してから外部helperを呼ぶ。helperは現在のlambda body/closure、mapping slot、monitoring/PEP 523/
  recursion、全key/valueを毎回再検査し、成功時だけnew-ref結果を返す。失敗時は同じuopで元のvectorcallを実行する。
- 専用Tier1 opcode/uopとCALL_KW cache利用を除き、全casesを再生成した。`CALL_KW_MAX_DICT_INT_KEY`はsource/generated
  treeから消え、後続opcode IDも初版前へ戻った。縮小版debug Tier-2 buildは成功し、max集中5 testは全成功した。
  次はdebug region 226件、Tier3、C API optを逐次実行し、生成冪等性確認後にnative codeを再生成する。

- 縮小版debug Tier-2でregion **226件**、Tier3 14件、C API opt 321件の計**561件**が全成功した
  （既存skip 3）。direct成功、同一uop内generic fallback、monitoring、code/closure変更を含む集中5件も全体順序内で
  成功している。次はtracked生成差分のhashを固定して`regen-cases`を再実行し、冪等性と`git diff --check`を確認する。

- tracked差分30ファイルのSHA-256は`regen-cases`再実行前後で全一致し、`git diff --check`も成功した。最初のnative
  stencil生成は単独translation unitからhelper prototypeが見えず停止したため、実装のTier2限定は維持したまま宣言を
  既存JIT helperと同様に公開した。失敗時は`.jit-stamp`を更新せず、修正後の強制生成はLLVM 21で成功した。
- PGO/LTOなしの通常`-O3` release JIT linkも成功した。縮小候補binary
  `build-jit/python-max-dict-compact-candidate`のSHA-256は
  `6b5be38ebfc9cd01e0f29ca064debc33f8c1fc2e648a8f7377db0f617eae6bbe`。直前版比のtext増分は初版5,776 bytesから
  **3,392 bytes**へ縮み、JIT available/enabledはいずれもtrue。native最小probeは既存`_CALL_KW_NON_PY`を含む
  57 uops、7 direct entries、672 iterations、guard exit 0、native code 4096 bytesを確認した。
- 縮小版release nativeでもregion **226件**（skip 11）、Tier3 14件（skip 1）、C API opt 321件（skip 3）の
  計**561件**が全成功した。次にBPE coverageで1,815,343回の走査削減が維持されたことを確認し、初版と同じ固定CPU・
  resident対応測定を縮小候補/直前版で行う。

- 縮小版BPE coverageも専用max 768 entries、**1,815,343 iterations**、guard exit 0で初版と一致した。既存opcodeを
  使うためwarmup中のlambda executorは残り、到達可能executor 37・native code 192,512 bytesは直前版と同数だが、
  測定区間のlambda相当処理はdirect scanで全て覆っている。ほかの主要counterと`check_result()`も一致した。
- 固定CPU 2・residentのBPE 3-block対応測定は縮小候補/直前版
  **0.972621 / 0.969655 / 0.971683**、幾何平均 **0.971319**で全block改善した。初版の0.954354より利益は
  小さいが、約2.9%の短縮は安定している。checksum全一致、除外0、binary/script hashも不変。
- 次は縮小候補・直前版・mainの全6本screenを、初版と同一protocolで実行する。後続opcode IDを戻したことで
  非対象Btree/Raytraceの一方向回帰が消え、6本幾何平均が直前版より改善するかを採用条件とする。

- 縮小版の全6本screenでは候補/直前版がBPE **0.977017**、Btree 0.992311、DeltaBlue 0.991979、Hexiom
  0.981036、Raytrace 1.009687、Spectral 0.999813。6本算術平均 **0.991974**、幾何平均 **0.991913**で
  全体を約0.8%改善し、初版の1.000444から採否を反転できた。checksum全一致、除外0、hash不変。
- 同じrunの縮小版/mainはBPE 0.798325、Btree 0.555844、DeltaBlue 0.761954、Hexiom 0.625961、Raytrace
  0.751472、Spectral 0.018662、算術平均 **0.585370**、ユーザー指定の幾何平均 **0.379094**。対応する
  直前版/mainは0.591148 / 0.382238だった。縮小版を採用し、固定binaryとartifactを保持する。
- ただし専用maxが形成されないRaytraceだけは平均約1.0%悪化した。次に直前版と縮小版のRaytrace coverageで
  `_CALL_KW_NON_PY`のexecutor/実行形を比較する。Raytraceが既存uop内のmax判定を高頻度に通るなら、callable identity
  判定をtrace時に省ける配置安定な方法を探し、BPE利益と全体幾何平均をさらに改善する。

- Raytraceの対応coverageは直前版と縮小版で全region counterが一致し、到達可能executor **71**、native code
  **1,032,192 bytes**も一致した。両版とも`_CALL_KW_NON_PY`を含むexecutorは0で、新しいmax判定を実行していない。
  約1%差は専用経路の実コストではなくbinary layout/run変動なので、BPEの直接利益と6本幾何平均改善を優先して
  縮小版を採用する。採用binaryは`build-jit/python-max-dict-compact`に固定済み。
- 次はcore developer向け`Tools/jit/optimization_report.md`へ、exact Python subtract fast-frame化、max-dict scanの
  初版不採用と縮小設計、guard/意味論、coverage、最新の幾何平均を追記する。その後最終生成・test・diff整合性を
  再確認し、次のprofile対象を記録する。

- core developer向け英文`Tools/jit/optimization_report.md`を現在の採用sourceへ更新した。冒頭の主指標を
  最新の6本main比幾何平均**0.379094**へ改め、Tier-1 sum集約、bounded equality scan、軽量float-dot call、
  exact Python subtract fast-frame、compact max-dict scanのbody proof、runtime guard、所有権・例外・monitoring、
  coverageと対応測定を追記した。専用max opcode初版、重いfloat-dot初版、exact addを不採用にした根拠も残した。
- `Tools/jit/regions.md`の実装contractにも上記5経路のopt-in条件、fallback地点、counterを追加した。これで報告書が
  参照する短いcontractと実sourceの現状が一致する。次は固定debug bootstrapで全casesを再生成し、変更前後hash、
  Markdown内のlocal link、`git diff --check`を確認する。コードは最終561件が成功した後に変えていないため、同じ
  全suiteを重複実行せず、release/debugのmax集中testとJIT availability・採用binary hashを最終確認する。

- `build-tier2-debug/python`を固定bootstrapにして`make regen-cases`の全12生成targetを再実行した。生成前に固定した
  tracked差分32ファイルのSHA-256は文書とplanを含めて全件一致し、生成物の冪等性を再確認した。英文2文書の全local
  Markdown linkも解決し、`git diff --check`は成功した。
- max集中5件はdebug Tier-2と`PYTHON_JIT=1`のrelease nativeでそれぞれ全成功した。固定CPU 2・residentの最小probeは
  JIT available/enabledともtrue、既存`_CALL_KW_NON_PY`を含む57 uops、7 direct entries、672 iterations、guard exit 0、
  native code 4096 bytes、first-maximum identity一致を再確認した。
- 現在の`build-jit/python`と保存済み`build-jit/python-max-dict-compact`は同じSHA-256
  `6b5be38ebfc9cd01e0f29ca064debc33f8c1fc2e648a8f7377db0f617eae6bbe`。コード変更後の最終統合結果はdebug/nativeとも
  region 226件、Tier3 14件、C API opt 321件の計561件成功であり、文書変更後の集中再確認も完了した。
- 6本main比の主指標は幾何平均**0.379094**で0.5を下回り、今回の採用条件と更新後goalを達成した。次にさらに進める
  場合はcompact max適用後のBPEとRaytraceを同じ固定binaryで再profileし、BPEのdict lookup・tuple/list allocation・GC、
  Raytraceのframe clear/object allocationのうち10万回以上かつcallback-freeにまとめられる経路だけを候補にする。
  GitHub投稿、push、PR変更は行っていない。

## 18. pyperformanceによるfixed main/native JIT比較（2026-09-15）

- ユーザー指示により、保存済みfixed main `build-main-jit/python`と現在の採用版`build-jit/python`を
  pyperformanceで比較する。CPython AI利用方針（2026-07-21更新）と更新後AGENTS.md、
  `benchmark-stability`のmeasurement/CPython手順を再確認した。sourceやbuildは変更せず、固定binaryを測る。
- main SHA-256は`8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`、採用版は
  `6b5be38ebfc9cd01e0f29ca064debc33f8c1fc2e648a8f7377db0f617eae6bbe`。両buildともGCC 13.3.0、
  `-O3 -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer`、`--enable-experimental-jit=yes`で、PGO/LTOなし。
  `PYTHON_JIT=1`でavailable/enabledともtrueを確認した。
- 測定は従来と同じCPU 2へ固定し、main/candidate双方のworkerへ`PYTHON_JIT=1`、resident policy、全6 opt-in flagを
  同じallowlistで渡す。CPU 2は最大4.4GHzのperformance coreでCPU 3とSMT sibling、governorはpowersaveであり、
  system tuningは変更しない。完全suiteを二群へ固定分割し、片群をmain→candidate、他方をcandidate→mainの順で
  実行する。共通benchmark全件のcandidate/main時間比を同重み幾何平均し、失敗・欠落・pyperf警告を除外せず記録する。
- system Pythonにはpyperformance/pyperfが未導入だった。次はworkspace内の専用controller venvへ固定版を導入し、
  version/help/manifest、target venvの依存、実workerのJIT環境を短いprobeで確認する。probe成功後に通常presetの全suiteを
  実行し、結果JSON、stdout/stderr、binary/workload/dependency identityを`jit-artifacts/pyperformance-20260915/`へ保存する。

- 採用版Pythonでcontroller venvを作り、pyperformance 1.14.0、pyperf 2.10.0、psutil 7.2.2、packaging 26.3を
  導入した。default manifestは97 benchmark。全依存を作る初回試行は`fastapi`が要求するpydantic-core 2.46.5の
  PyO3 0.28.3がPython 3.16を最大対応3.14より新しいとしてwheel buildを拒否し停止した。
- `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`で未検証buildを強制せず、事前に`fastapi`だけをunsupportedとして除外する。
  残る96 benchmarkのtarget venvを両比較側で同じ固定requirementsから作り、freezeとimport backendを照合する。
  この除外は性能結果を見た後の選別ではなく依存構築不能によるmanifest-level欠落として全体結果に残す。

- pyperformance自身の`venv create -p`はcontroller Pythonで環境を作るため、比較対象を実行基盤にするよう各binaryの
  `-m venv`で`venv-main`と`venv-candidate`を作り直した。両方へmain側から固定した同一67 packageを導入し、
  `pip freeze`はbyte単位で一致（SHA-256
  `1a300b59650478e5092240511009dd1732e96f006dfbe209e4d96be2f21684fb`）。外部native extension 14個も対応する
  `.so`のSHA-256が全て一致した。これによりPython本体以外のsuite依存差を除いた。
- CPU 2固定・同一8環境変数・同じpyperf allowlistを通る中立worker probeを両環境で実行した。main/candidateとも
  `sys._jit.is_available()`/`is_enabled()`がtrueで、reachable executorから非空`get_jit_code()`を確認した。
  probe平均はmain 2.57 ms、candidate 260 usだったが、これは整数loopの動作確認値でありpyperformance総合指標には
  含めない。次は96件の名前と交互開始順を結果を見る前にartifactへ固定し、各benchmarkを通常presetで対応測定する。

- defaultから`fastapi`を除く実効96件を`benchmarks.txt`へ固定し、suiteのlist出力と完全一致を確認した。偶数位置48件を
  group A（main→candidate）、奇数位置48件をgroup B（candidate→main）とし、binary/manifest/dependency/list hash、
  CPU、環境、同重み幾何平均を`protocol.json`へ結果を見る前に記録した。各群の後発側は先発JSONの`--same-loops`を使う。
- 最初のsmokeはrunnerがvenv entry pointのsymlinkをbase binaryへ解決したためpackageを見失って即時失敗し、測定値を
  生成しなかった。起動pathを解決せず保持するよう修正した。その後、pyperformanceがさらにbinary ID別のworker venvを
  自動作成することを確認し、各binaryで構築済みの同一67-package環境を対応cacheへ独立コピーした。cache側の
  `sys._base_executable`はmain/candidateを正しく指し、`pip freeze --all` hashも双方一致した。
- 修正後のBPE、float、Richards、spectral normのdebug-single-value smokeは8 run全て成功した。metadataはCPU affinity 2、
  GCC 13.3.0、同じ`-O3` flagsを示し、ログ内の実worker commandにも全8 JIT変数のallowlistが渡っている。BPEの
  `--same-loops`も成立した。smoke値は本結果に混ぜない。次は96件を二群4 commandの通常presetで逐次実行する。

- 通常presetのgroup A/mainを開始した。27件目までにBPEは3.01 s +/- 0.01 sなど22件が値を返し、`2to3`、
  `asyncio_tcp`、`asyncio_websockets`、`concurrent_imap`、`dask`はworker終了で失敗した。28件目`networkx`は
  worker開始後に出力せず、事前固定した1800秒でpyperf timeout（exit 124）となった。手動介入やtimeout変更はせず、
  runnerが29件目へ継続した。次はmain群の残りを完了し、candidate側で同じ項目の完走可否とloop対応を確認する。

- group A/mainは2976.2秒で完了し、48 manifest項目中40件が成功、`pprint`の2出力を含む41 pyperf benchmarkを
  JSONへ保存した。失敗は上記5件と`networkx`に加えて`networkx_k_core`、`tornado_http`の計8件
  （worker終了7、timeout 1）。binary SHA-256は開始時と一致した。runnerは直ちにgroup A/candidateを開始し、
  main JSONに存在する全benchmarkへ`--same-loops`を適用している。次はcandidate側の成功集合、特にnetworkxの
  完走可否を確認し、A群の共通名を比較する。

- ユーザー指示により、以後の`networkx` timeoutを早める。group A/candidateは10件目の途中で中断したが、suite JSONは
  群完了時にだけ書かれるため性能結果は未生成で、確定済みmain JSONには影響しない。中断logは別名で保存した。
  runnerを300秒上限へ変更し、protocolへ「A/mainのみ1800秒、以後300秒」のamendmentと新runner hashを記録した。
  次はstateからA/mainをskipし、A/candidateを先頭から同じloops・CPU・環境で再実行する。B群は両側とも300秒で揃える。

- 300秒上限で再実行したgroup A/candidateは1532.2秒で完了し、mainと同じ41 pyperf benchmarkを保存した。失敗項目も
  同じ8件で、`networkx`は300秒timeout、`networkx_k_core`はcandidateでは300秒timeout（mainはworker終了）。
  pyperfの有意差表示でA群は約1.05x faster、主な値はBPE 3.01→2.42 s、DeltaBlue 1.72→1.18 ms、Raytrace
  156→118 ms、Spectral Norm 42.1→20.7 ms。Goだけは63.6→84.5 ms（1.33x slower）で大きな回帰候補となった。
- group B/candidateは1538.9秒で完了した。48 manifest項目中45件が成功し、Base64 11件、Deepcopy 3件、Logging
  3件、SciMark 5件、SymPy 4件、XML 4件などを含む69 pyperf benchmarkを保存した。失敗は`asyncio_tcp_ssl`、
  `genshi`のworker終了と`networkx_connected_components`の300秒timeoutの計3件。binary hashは不変。
  runnerはgroup B/mainを開始し、candidate JSONの全69名へ`--same-loops`を適用している。次はmain側の成功集合を
  確定し、A+B共通全名（現状最大110件）の同重み幾何平均、pyperf有意差、警告、失敗を集計する。

- group B/mainは1421.1秒で完了した。candidateと同じ69 pyperf benchmarkを保存し、失敗項目も
  `asyncio_tcp_ssl`、`genshi`、`networkx_connected_components`の3件で一致した。最後のnetworkx系もユーザー指定どおり
  300秒で打ち切った。A群41名、B群69名は重複せず、両binaryに共通する比較対象は計110名となった。
- 最終JSONのSHA-256はA/main `97a57d...6050`、A/candidate `970ec2...e2e`、B/main
  `7b9006...3f62`、B/candidate `4c59f5...744a`。main/candidate binaryも開始時の`8fb6c5...3407` /
  `6b5be3...6bbe`から不変だった。次は4 JSONのloop/metadata対応を機械確認してside別に統合し、110名を同重みとする
  candidate/main時間比の幾何平均とworkload-bootstrap区間、pyperf有意差、最大改善・回帰、unstable警告を出す。

- 110名の機械照合で、`deepcopy`が返す3結果のうち`deepcopy_reduce`と`deepcopy_memo`だけloop不一致を検出した。
  B群後発mainへ渡された`--same-loops=1024`が複数Runner全体へ適用され、先発candidateで個別校正された65536 / 8192を
  保持できないpyperformance側の制約である。ほか108名のloopsは一致した。
- 主解析へ不一致を残さないため、結果値を見る前にdeepcopy 3件を両側共通8192 loops、通常6 processes x 10 valuesで
  一度だけ補正測定する。長いB群とは逆のmain→candidate順、同じCPU 2、JIT/resident/全opt-in、300秒worker timeoutを使い、
  workload/binary hashを前後照合する。元JSONは変更せず保存し、補正3件だけを統合suiteで置き換える。

- deepcopy補正はmain/candidate各約95秒で完了し、3結果とも8192 loops、6 measured processes、60 valuesで一致した。
  main→candidateはdeepcopy 153→151 us、reduce 1.81→1.78 us、memo 12.6→13.3 us。両binaryと同一workload script
  SHA-256 `9e1550...078`は前後不変で、補正JSONを元の4 suite JSONと別に保存した。
- 補正後110結果の主指標candidate/main時間比は同重み幾何平均 **0.969162**（**3.08%短縮、1.032x**）。各側の
  6 measured process meanを独立再抽出した20,000回bootstrap（seed 20260915）の95%区間は
  **[0.968083, 0.970242]**、全value中央値による感度分析は0.968572だった。この区間は固定binary/host/CPU内だけで、
  rebuildやcode layout、別hostの変動は含まない。
- 名目上68件改善、42件回帰。pyperfの既定t-testでは48件改善、32件回帰、30件有意差なし。最大改善はSpectral Norm
  0.4918、Hexiom 0.5844、async-tree eager 0.6021、DeltaBlue 0.6890。最大回帰はbase16 large 1.4735、
  base16 small 1.3345、Go 1.3275で、いずれも各側の標準偏差は2.2%未満だった。
- この3回帰の順序ドリフトを調べるため、主集計は変えず各1 blockだけ逆順再測定する。base16はpyperformanceの未変更
  関数をsmall 512 / large 32 loopsでmain→candidate、Goは2 loopsでcandidate→main、全て通常6 x 10 values、CPU 2、
  同一JIT環境を使う。再現すれば回帰を実装またはbinary layout起因の未解決課題として明示する。

- 逆順blockでもbase16 small 1.3409、large 1.4979、Go 1.3308と主測定を再現した。各側60 values、標準偏差は
  1.8%以下、binary/workload hash不変なので、長時間suiteの順序ドリフトではない。
- candidateで全6 opt-in flagを外した診断では、Goはmain比 **1.0034**へ戻った一方、base16 small/largeは
  **1.3297 / 1.4855**のままだった。従ってGoはopt-in変換の実コスト、Base16は変換が形成されなくても残るcandidate
  binary/source/code-layout差である。次はGoを各flag単独有効で測って原因を特定し、Base16を両側JIT無効で測って
  native JIT固有かTier 1/core固有かを切り分ける。これらの診断値は110件の主集計を変更しない。

- Goを各flag単独で測ると、call-regionsだけmain比 **1.3302**で全ONの1.3308を再現し、ほか5 flagは
  1.0033–1.0063だった。call-regions有効/全flag無効coverageは時間0.08325/0.06359 s、到達executor **87/132**、
  native code **602,112/1,257,472 bytes**。専用region counterは全て0なのでfast pathの実行コストではない。
- sourceではcall-regions有効時に`_GUARD_GLOBALS_VERSION`と`_LOAD_GLOBAL_MODULE`がnamed dependencyを選び、通常の
  globals mutation上限を越えてwatchを継続する。Goは`TIMESTAMP`と`MOVES`を高頻度に書き換えるため、named dependencyの
  invalidationでexecutor coverageを失うことが観測と一致する。次の実装修正候補はnamed監視を実際にfoldした名前へ限定し、
  専用call regionを形成しないtraceでは既存mutation上限を維持すること。今回は比較依頼のためsource修正や再buildへ広げない。
- Base16は両側`PYTHON_JIT=0`でもsmall/large **1.3168 / 1.4586**で回帰した。固定mainの`Lib/base64.py`
  （SHA `4b0f87...64fb`）は`ignorechars`が空なら`bytes.translate`を省くが、candidate側（`93319e...978`）は常に呼ぶ。
  main版moduleだけcandidateへoverlayしたJIT-off測定はmain比 **1.0326 / 0.9836**へ戻り、回帰のほぼ全てがbranch間の
  標準ライブラリrevision差で、今回のJIT最適化ではないことを確認した。
- 既知のBase16 source差2結果を除く副次感度は108結果で0.962555、さらに診断済みGoを除くと107結果で0.959667。
  選別後の値なので主結論にはせず、事前定義した全110結果の **0.969162**を維持する。次はofficial `pyperf check`/
  `compare_to`出力、失敗分類、生JSON、補正・診断、解析scriptのhash manifestを固定し、最終整合性を確認する。

- official pyperf 2.10.0 `compare_to`も**1.03x faster**を表示し、独立計算と一致した。有意差なしは30件。
  `pyperf check`のunstable警告はmain 49、candidate 45件で、大半は「1%未満の変動を95%確度で得るにはsample不足」。
  警告項目も除外せず、各benchmark 6 measured processes / 60 valuesをprocess単位bootstrapへ使用した。
- default 97 manifest中、`fastapi`は事前のPython 3.16依存非互換で除外。残る96 specification中85が完了した。
  socket bind禁止4件、process権限1件、offline `2to3` vendor 1件、Python 3.16非互換2件、networkx系3件の計11件は
  比較値なし。networkx系は以後300秒で打ち切り、一般networkxは両側timeout、k-coreはmain signal 11/candidate timeout、
  connected-componentsは両側timeoutだった。これらについて速度結論は出さない。
- 最終英語reportは`jit-artifacts/pyperformance-20260915/analysis/summary.md`、全110比は`ratios.csv`、機械可読集計は
  `analysis.json`、official出力は`pyperf-compare.md`と`pyperf-check-*.txt`、診断は`diagnostics.json`に保存した。
  生の4 suite JSON/log、deepcopy補正、逆順再測定、flag/JIT/source診断も別ディレクトリに保持している。
- 315 evidence filesとmain/candidate binary、両`base64.py`を照合する`artifact-manifest.json`を生成し、manifest自身の
  SHA-256は`57f948c6001159acf56cdf37094d93255903401b106a311c1e9eea350e03ac59`。56 JSONのparse、全manifest hash、
  analysis/official pyperf整合性、全解析scriptの`py_compile`、`git diff --check`が成功した。最終binary hashも不変。
- 結論は固定build全体で**3.08%短縮**。次のJIT実装作業ではGoで判明したnamed-global dependencyの監視範囲を狭め、
  専用call regionが形成されない高頻度globals更新workloadのexecutor invalidationを防ぐ。その修正は別candidateとして
  correctness、Go逆順block、選択前の全suiteで再検証する。今回はGitHub投稿、push、PR変更を行っていない。

## 19. main統合とGo 0.8目標（2026-09-15）

- ユーザー指示によりlocal `main` `a60343ed17785ebbcd43de9080cadd8e2541db6f`を、作業HEAD
  `43061656d481a937e2c07500f457b7e81ff1c3bd`へマージした。追跡済みdirty差分は事前にstashし、完全patchを
  `/tmp/cpython-gc-pre-main-merge.patch`（SHA-256
  `4dd841cb3f39f4ed9a9054f5ffbe5ebc710f3a3d74a1c8f6c207a024c5396f11`）へ保存した。マージcommitは
  `9db7c47c5fb`、競合なし。stash適用後もunmerged pathと`git diff --check`エラーはなく、復元を確認してstashを削除した。
- merge後の`Lib/base64.py`は`main`との差が0で、空の`ignorechars`では不要な`translate()`を呼ばないmain側実装になった。
  以前のbase16回帰はこの標準ライブラリ差が原因と診断済みなので、次回比較からその差は入らない。
- pyperformance 1.14.0の`bm_go/run_benchmark.py`を`benchmarks/go.py`へ標準ライブラリだけで動く形に移植した。
  元の9×9盤面、200 games、seed 1、`versus_cpu()`の計測境界は変えず、各operationで選択手5、
  `TIMESTAMP`増分81,059、`MOVES`増分21,401を検証する。共通CLIとJSON出力を追加し、一覧文書も更新した。
- 元版の全9 function/classと移植版のASTが一致した。固定mainで2 loopsを実行し、選択手5、`TIMESTAMP` 162,118、
  `MOVES` 42,802を確認した。`py_compile`、JSON出力、`git diff --check`も成功し、移植工程を完了した。
- 次は移植版を元pyperformance関数と照合し、merged sourceからPGO/LTOなしのnative JITを再生成する。固定mainと
  CPU 2・resident・同じopt-in環境でbaselineを取り、まずnamed-global監視のmutation上限を保つ修正で既知の1.33倍回帰を
  除く。その後coverage/perfからGoのhot pathを選び、対応blockのcandidate/mainが**0.8以下**になるまで実装と検証を続ける。

- LLVM 21.1.8と固定debug bootstrapを使い、`-fno-vectorize -fno-slp-vectorize`でmerge後のnative stencilを強制再生成した。
  configure更新による全再コンパイル後もPGO/LTOなし、JIT available/enabledを確認した。成功した手動生成のprefix/flagsを
  ここへ記録してから`.jit-stamp`を更新し、merged baseline binary
  `build-jit/python-go-merged-baseline`（SHA-256 `ebc3a1d9...c34a1`）を固定した。
- CPU 2・resident・全6 opt-in・各process warmup 5/value 10の交互順3 blockで、merged baseline/mainは
  **1.342284 / 1.344402 / 1.354144**、幾何平均 **1.346933**。main統合後もcall-region起因の回帰を安定再現した。
- 最初の修正では、現在のcode object自身が`STORE_GLOBAL`する名前をbytecodeから検出し、その名前の
  `_LOAD_GLOBAL_MODULE`だけconstant foldingせず特殊化lookupを残した。名前別dependencyによるstable globalの最適化は維持する。
  新規self-invalidating counter testと既存named-global 3 testはnative JITで成功した。
- 修正版（SHA-256 `aa58ca12...3b29`）のmain比は3 block **1.293755 / 1.274421 / 1.277661**、幾何平均
  **1.281918**。改善したが目標未達で、別functionから`TIMESTAMP`を読むexecutorは依然として書換えのたびに無効化される。
  次はmutation上限へ達したmoduleで、頻繁に再束縛されるmortal exact-int globalをfoldしない限定heuristicを追加する。
  `stable` objectを差し替えて再形成する既存named-global contractは維持し、別writer関数のcounter testで区別を固定する。

- exact mortal-intだけを対象にした試作は3 block幾何平均 **1.317042**、書込対象名だけをmodule内functionから探す試作は
  **1.334103**で、別reader executorの再形成を十分に止められなかったため撤回した。どちらも最終sourceには残していない。
- 現在の実装は、同じglobalsを使うmodule functionまたは直下class methodに`STORE_GLOBAL`が一つでもある場合、named dependencyを
  選ばず既存のglobals mutation上限へ戻す。初期の少数回は従来どおりfoldし、その後は`_LOAD_GLOBAL_MODULE`を残すため、頻繁な
  module counter更新でもexecutorが安定する。外部からだけ変更されるstable globalsは従来の名前別dependencyとfoldを維持する。
- 自己書込、別function書込、無関係名の差替え、mutation後の再compile、legacy dependencyのfocused 5 testはnative JITで成功した。
  binary `build-jit/python-go-mutable-module-fix`（SHA-256 `9e019f1c...5929`）のmain比は3 block
  **0.979738 / 0.992641 / 1.018712**、幾何平均 **0.996899**。既知の1.35倍回帰は除いたが0.8目標には未達である。
- JITを外した1 operationの`cProfile`では`Square.find`が46.4万call（18.3万primitive）、`Board.useful` 5.97万、
  `EmptySet.random_choice` 2.18万、`Square.move` 2.14万。leafでは`EmptySet.set` 6.66万、`ZobristHash.update`
  6.82万、`ZobristHash.dupe` 3.15万が多い。次は現在binaryでexecutor/uop coverageとflag別寄与を取り直し、既存の
  generic call-region matcherへ安全に載せられるhot leafまたは`Square.find`を選ぶ。新しい変換はcode shape、type layout、
  globalsのguardで一般化し、Go固有のfunction名には依存させない。focused correctnessと交互順3 blockを各iterationで行う。

- `Square.find(update=False)`の正確なbytecode形を証明する再帰参照root変換を追加した。exact function/type/layout、
  compact exact-int position、instrumentation/eval breaker、recursion残量を全て副作用前にguardし、最大64 linkを直接たどる。
  最初の版はtype versionを16 bitへ切り詰めて全entryがguard exitしたため、operandへ32 bitを保持するよう修正した。
  次の版は再帰frameだけを省きながら記録済みtraceの後半へ進み、消したframeのlocalを後続uopが読むためGoの結果を壊した。
  採用版はcall以後を`_DYNAMIC_EXIT`へ置換し、実callerのreturn offsetへ戻すことでこの不変条件違反を解消した。
- debug Tier-2とnative JITで選択手5、`TIMESTAMP` 81,059、`MOVES` 21,401を再確認した。native 1 operationでは
  56,840 entry、133,595 link iterationを実行。固定CPU 2の交互順3 blockはmain比
  **0.972517 / 0.969855 / 0.967606**、幾何平均 **0.969991**だった。artifactは
  `jit-artifacts/go-goal-20260915/reference-root-v3/`。LLVM stencil生成は固定debug bootstrapへ
  `-X cpu_count=2`を渡すと並列clang crashを避けられ、成功後だけ`.jit-stamp`を更新した。
- 続いて、exact ownerの二つのinline-value属性がexact listで、compact exact-intの二引数を順に代入する短いmethodを
  一つの`_CALL_PY_LIST_SET_PAIR`へ置換した。対象bodyの全bytecode形、function/type version/layout、list/index、既存elementの
  exact型を副作用前にguardする。Pythonと同じ二つのstore順と参照数操作を保ち、call後は実callerへdynamic exitする。
  実Go traceは汎用fixtureと異なりstore直前が`_GUARD_TOS_INT`だったためmatcherへ追加し、checksumを保ったまま
  1 operationで26,095 callを融合できた。
- pair-store版binary SHA-256は`551cb7ec...f0dd`。同条件3 blockはmain比
  **0.982549 / 0.955621 / 0.955803**、幾何平均 **0.964576**で、reference-root版からさらに約0.56%短縮した。
  artifactは`jit-artifacts/go-goal-20260915/list-set-pair/`。目標0.8には未達なので、次は3.15万callの
  `ZobristHash.dupe`（exact set membership）または6.82万callの`ZobristHash.update`を一般的なguard付きleaf callへ融合する。
  まず副作用を持たないset membershipを実装・focused test・coverage確認し、効果が足りなければupdateと上位loopへ進む。

- `return self.key in self.values`という完全なbodyを、exact function/type/layout、exact-int key、exact setで証明する
  `_CALL_PY_SET_CONTAINS`を試した。set probeはCPython本体と同じperturb列をたどり、exact-int同士だけを直接比較し、hash collisionした
  non-int keyは`__eq__`を呼ぶ前にdeoptする。hit/miss、巨大int、custom collisionのfocused確認とGo checksumは成功し、1 operationで
  18,647 entryを観測した。しかしcallerへdynamic exitする版の3 block幾何平均は**0.966091**で、pair-store版
  **0.964576**から改善しなかった。
- 次に`Board.useful_fast`型の「bool属性を検査し、list属性中のobject属性がglobal intと一致するか」を一callへまとめる
  `_CALL_PY_LIST_ANY_ATTR`を試した。Goでは27,903 call / 28,246 list elementを処理しchecksumも一致したが、recorded traceがcalleeの
  loop内部で終わるため各call後のdynamic exitを避けられず、3 block幾何平均は**0.975291**へ悪化した。この変換は不採用とし、
  source、counter、optimizer pass、生成uopから完全に削除した。
- pair-storeとset-containsの実traceにはcalleeの`RETURN_VALUE`後にcaller uopが記録されていたため、matcherをreturnまで厳密に照合し、
  callee区間だけをNOP化してcaller traceを継続するよう変更した。debug Tier-2で選択手5、`TIMESTAMP` 81,059、`MOVES` 21,401を確認。
  pairは38,982 entry、setは18,647 entryへ到達し、全てのspecialized uop直後が`_DYNAMIC_EXIT`ではなくcaller側の
  `_CHECK_VALIDITY`等であることを機械確認した。set collision fixtureも成功した。次はLLVM stencilを強制再生成してnative buildを
  relinkし、同じ3 blockでこのtrace継続の効果を測る。0.8に届かなければnative profileを取り直して次のhot regionへ進む。

- LLVM 21で全stencilを強制再生成し、PGO/LTOなしのrelease native JITを全rebuildした。nativeでもJIT available/enabled、Go checksum、
  pair 38,982 entry、set 18,647 entry、caller trace継続、collision fallbackを再確認した。binary SHA-256は
  `c70419dd...86b6`。交互順3 blockのmain比は**0.945363 / 0.950447 / 0.953476**、幾何平均
  **0.949756**。dynamic exit削減はpair-store版から約1.5%改善したが、0.8目標にはまだ約15.8%必要である。
- 現binaryを`cpu-clock:u` 999 Hzで10 operation profileし637 sampleを取得した。self timeはTier 1 interpreter 19.6%、
  frame clear/init/pop/pushが合計約5%、long XOR本体1.7%に加えてそのallocationが約1.4%、method/type/instance lookupも数%を占める。
  次は68,206 call/operationの`ZobristHash.update`を対象に、二つの非負exact-int XORと同じ属性へのstoreを一つの
  callback-free leaf callへ融合する。中間long allocationとPython frameを除き、最終long、store順に関係する例外・参照寿命、
  type/function/layout/list/index guardをfocused testで固定する。効果が不足する場合は`Board.useful_fast`のlocal list scanへ進む。

- `self.value ^= item.values[item.index]; self.value ^= item.values[index]`という完全なmethod bodyを証明する
  `_CALL_PY_XOR_ATTR_LIST_PAIR`を追加した。exact function/type version、inline-value layout、exact list、compact index、
  非負uint64 exact-intを副作用前にguardし、二つのXORと中間store/allocationを一つのXOR・最終long/storeへまとめる。
  allocation失敗時は省略したcallee frameと第二XOR位置のtracebackを復元する。debug Tier-2の境界値、負/巨大int、bool index、
  reflected XOR、IndexError、targeted allocation failureで通常経路へのfallbackと例外伝播を確認した。
- native JITでも選択手5、`TIMESTAMP` 81,059、`MOVES` 21,401を維持し、1 operationでXOR uop 17,068 entryを観測した。
  binary SHA-256は`d9edb038...e1fb2`。CPU 2・resident・全opt-in・warmup 5/value 10の交互順3 blockはmain比
  **0.904158 / 0.894691 / 0.895889**、幾何平均 **0.898236**。caller継続版から約5.4%短縮したが0.8目標には
  さらに約10.9%必要である。artifactは`jit-artifacts/go-goal-20260915/xor-call/`へ保存した。
- 更新後の20-operation native profileではTier 1 interpreterがself 17.6%、frame clear/init/pop/pushが合計約8%、
  dict insert/lookup、method/type/instance lookup、compact-int加減算が次の費用である。次は約5.97万callの
  `Board.useful_fast`について、以前成功したcallback-free list scanへcalleeのreturnとcaller継続を加えて再実装する。
  checksum、early return、used case、属性/type/global変更のfallbackを固定してから同じ3 blockで採否を決める。

- 再帰参照rootについて、recorded trace内のnested `PUSH_FRAME`/`RETURN_VALUE`深さを追跡し、callee区間後もcallerを継続する
  試作を行った。単純な再帰fixtureでは成立したが、Goでは選択手51、`TIMESTAMP` 80,360、`MOVES` 21,165へ壊れた。
  inlined recursive frameをNOP化した後のstack/local所有権がrecorded caller mappingと一致しないためである。この案と診断用envは
  完全に撤回し、採用版の実caller return offsetへのdynamic exitを維持した。再帰callを越える継続は、frameを保持するlocal uopで
  bodyだけを融合する場合に限って再検討する。
- `Board.useful_fast`の完全なbodyを再証明し、`used`がfalseなら最大64件のexact-listを走査して各exact memberのinline属性を
  actual callee globals内のcompact exact-intと比較する`_CALL_PY_LIST_ANY_ATTR`を追加した。callee returnまで記録されたtraceだけを
  変換してcallerへ継続する。記録時のbool returnでcaller分岐が定数化されているため、runtime探索結果がそのrecorded pathと一致する
  guardも入れた。このguardがない試作はGo checksumを壊し、分岐結果のownershipをguardする必要性を実測で確認した。
- debug/nativeとも選択手5、`TIMESTAMP` 81,059、`MOVES` 21,401を維持した。native 1 operationで8,999 call、11,943 elementを
  専用uopが処理し、binary SHA-256は`a94f6e3f...6455c`。CPU 2・resident・全opt-in・warmup 5/value 10の交互順3 blockはmain比
  **0.895821 / 0.895876 / 0.892441**、幾何平均 **0.894711**。XOR版から約0.39%の再現性ある短縮なので採用し、artifactは
  `jit-artifacts/go-goal-20260915/any-attr-continuity/`へ保存した。
- 0.8目標にはさらに約10.6%必要である。次は68,206回のZobrist更新のうちcall融合で届いていない約5万回を対象に、callee frameを
  消さず二つのXOR bodyだけをlocal-frame uopへ置換する。これによりrecursive/callee-attached traceのlocal所有権を維持したまま、
  中間long allocationと属性lookup/storeを除ける可能性を検証する。body境界、例外位置、負値・巨大int・custom fallbackをdebugで
  固定し、native coverageと同じ3 blockで採否を決める。

- 関数先頭・空スタックから始まるcallee-attached executorだけに`_XOR_ATTR_LIST_PAIR_LOCAL`を追加した。実callee frameと
  `RETURN_VALUE`を維持し、全code shapeを証明した二つのXOR文だけを置換する。exact type/version、inline layout、exact list、
  compact index、非負uint64 exact-intを副作用前にguardし、一つの最終longだけを割り当てて属性へ格納する。
- debug fault injectionの初版は`JUMP_TO_ERROR()`がdeopt targetをerror targetにも使い、例外を保持したままexecutorへ再入した。
  `ERROR_NO_POP()`も一target形式では同じ問題になるため、現在frameのfirst-XOR offsetを設定して`GOTO_TIER_ONE(NULL)`へ直接戻す形に
  修正した。これでTier 1の通常error handlerが処理する。MemoryErrorのcallee traceback、属性未変更、負値・巨大int・範囲外indexの
  通常Python fallbackをdebugで確認した。一時診断assert/printは全て削除した。
- nativeでもGo checksumを維持し、local XOR **42,237 entry**、call XOR 17,767 entryで合計60,004 updateを融合した。binary
  SHA-256は`c4443a3e...3a4d`。最初の3 blockはmain側が63.2→65.6 msへドリフトして幾何平均0.879460だったため、同一binaryで
  直ちに3 blockを追加した。追加は**0.896379 / 0.889554 / 0.893086**、幾何平均 **0.893002**、6 block合成は
  **0.886205**。候補は全6 block 56.4–56.8 msで安定し、直前版56.4–57.2 msに対する実効差は約0.3%だった。
- 小さいが安定した短縮と42,237 entryの明確なcoverageがあるためlocal XORを採用する。単独の目標判定はrepeatの**0.893002**を
  重視し、0.8には約10.4%必要とみなす。次は現binaryをnative `perf`で再採取し、Tier 1、frame処理、dict/method lookupのうち
  Goの具体的な高頻度functionへ対応する費用を選ぶ。大きなleaf融合がなければ`Board.useful`本体のcallback-free prefixまたは
  `EmptySet.random_choice`を、frameを保持するlocal uopとして検討する。

- 20-operationの`cpu-clock:u` 999 Hz profileは1,168 samples、lost 0。selfはTier 1 20.91%、frame clear/pop/init/push
  合計7.58%、compact-long add/subtract 2.40%、dict lookup/insertとmethod/type/instance lookupが各0.3–1.5%だった。raw dataと
  reportは`jit-artifacts/go-goal-20260915/local-xor-profile/`へ保存した。code-attached `Square.find` executorは関数先頭から
  recursive callへ戻る55 uopで、専用root変換がなく、再帰frame削減の余地があると判断した。
- `Square.find`型の完全bodyに対して、実callee frameを保持した`_REFERENCE_ROOT_LOCAL`を追加した。`update` local、type/layout、
  compact position、各nodeのmethodが同一codeを持つexact Python functionであること、最大64 linkと再帰残量をguardし、root resultを
  元の`RETURN_VALUE`へ渡す。独立fixtureでread-only traversal、path compression、instance method overrideを確認した。
- 最初の`update=False`限定版は成功45,597回/124,978 linkに対して`update=True` call約12万回を全てguard exitし、main比
  **0.917029**、候補57.50–58.44 msへ明確に回帰した。そこで最大64件のnon-root nodeを一時保持し、元のrecursive unwindと同じ
  最深部からouterへの順でreferenceをrootへ更新・参照解放する`update=True`経路を追加した。書込前に全chain/methodを検証する。
- 完成版はdebug/nativeともGo checksumを維持し、1 operationで**105,904 entry / 245,539 link**、追加guard exit 0。binary
  SHA-256は`896198e0...1911`。固定CPU 2の3 blockはmain比**0.884650 / 0.887458 / 0.891312**、幾何平均
  **0.887803**、候補56.08–56.27 ms。local-XOR repeatから候補時間を約0.9%短縮したため採用する。artifactは
  `jit-artifacts/go-goal-20260915/local-root-update/`。
- 0.8にはさらに約9.9%必要である。次は`Board.useful_fast`でcallee loop内に終わるためcall-continuity版が届かないtraceを対象にする。
  call/PUSH_FRAMEは残し、callee localからcallback-free list scanを実行してtrue/falseの元`RETURN_VALUE`へ戻すlocal uopへ置換する。
  これにより以前回帰した「callee frameを消して毎call dynamic exit」と異なり、stack/local所有権を維持してloopだけを省ける。

- `Board.useful_fast`のcall traceがcallee loop内で終わる場合に、call setupと実callee frameを維持したままloop bodyを
  `_LIST_ANY_ATTR_LOCAL`へ置換する解析を追加した。完全なbytecode bodyからtrue/false両方の`RETURN_VALUE` offsetを取得し、
  runtimeではexact type/version、inline-value layout、bool、最大64件のexact list、compact exact-int、actual callee globalsをguardする。
  欠落したinline属性をNULLのまま型判定しないようcall/local両経路も修正した。
- debug/nativeともGo checksumを維持し、1 operationでlocal走査**1,784 entry / 1,407 element**を観測した。native JITの
  available/enabledも確認し、binary SHA-256は`66b9684d...d2e0`。固定CPU 2の3 blockはmain比
  **0.888795 / 0.891271 / 0.896617**、幾何平均**0.892222**だった。mainが直前測定より速い62.76–63.27 msへ移動した一方、
  candidate medianは55.92–56.07 msで直前版56.08–56.27 msよりわずかに短い。適用数と効果は小さいが候補を維持し、artifactは
  `jit-artifacts/go-goal-20260915/local-any/`へ保存した。
- 0.8目標には現在比でさらに約10.3%必要である。次は現binaryのnative sampleを採り直し、専用uop適用後に残るTier 1、frame、
  int/dict/method費用を実call siteへ対応付ける。大きい残存loopを一つ選び、実frameを保つlocal uopまたはcaller continuityで融合し、
  checksum・fallback・coverageをdebugで固定してから同じblock測定を繰り返す。

- local-any版を30 operation、`cpu-clock:u` 999 Hzで再profileした。1,738 sample、lost 0。Tier 1は20.51%、frame
  clear/init/pop/pushは合計6.57%、`unicodekeys_lookup_unicode` 2.13%、`_PyObject_GetMethod` 1.73%、
  `_PyTypeCache_Lookup` 1.44%だった。artifactは`jit-artifacts/go-goal-20260915/local-any-profile/`。
- 1 operation約6.7万callの`EmptySet.set`について、call融合に入らないcode-attached executorの二つのlist storeを
  `_LIST_SET_PAIR_LOCAL`へ置換した。exact type/layout/list/compact-int indexと既存exact-int要素を副作用前にguardし、元のstore・
  decref順を維持する。独立fixtureで負index、第一/第二index範囲外、属性削除、既存要素の`__del__`を確認し、debug/nativeの
  Go checksumと**11,252 local entry**を確認した。binary SHA-256は`7728c92b...31a4`。
- 固定CPU 2の3 blockはmain比**0.889638 / 0.855016 / 0.894652**、幾何平均**0.879591**。中央blockはmainだけ
  65.63 msへ遅く、candidateは全block 55.93–56.25 msでlocal-any版と同等だった。artifactは
  `jit-artifacts/go-goal-20260915/local-list-set/`。正しさとcoverageはあるが実効短縮はなく、次はlocal rootの各linkで行う
  method/type lookupを、class method一回の解決とinstance override検査へ分解して重複lookupを除く。

- call/local rootのrecursive method検証を、各linkの`_PyObject_GetMethod`から、uop入口でのclass descriptor一回の検証と
  各inline instanceのoverride不在検査へ変更した。debug/nativeとも全coverageとchecksumを維持し、instance override fixtureも成功。
  binary SHA-256は`2f7cfe02...bced`、3 blockは**0.888214 / 0.872541 / 0.887691**、幾何平均
  **0.882785**。candidateは55.84–56.09 msで小幅短縮に留まった。artifactは
  `jit-artifacts/go-goal-20260915/root-method-once/`。
- `Board.useful_fast`のcode-attached executorはFOR_ITERでなくbytecode backedge offset 57から記録され、entry stackにexact listと
  tagged indexを保持していた。完全body proofからbackedge、global名、両return offsetを取得し、現在indexからlist末尾までを
  `_LIST_ANY_ATTR_ITER_LOCAL`で走査して元のtrue/false `RETURN_VALUE`へ戻すようにした。一時offset診断は削除済み。
- debug/nativeでchecksumを維持し、1 operationでloop版**3,697 entry / 8,033 element**、三つのany-attr経路合計
  14,480 entryを観測した。false/early true/used、global差替え、属性削除、custom `__eq__`のfixtureも成功。binary SHA-256は
  `c56d62ac...359a`。固定CPU 2の3 blockはmain比**0.867511 / 0.881469 / 0.880922**、幾何平均
  **0.876610**。candidate後半2 blockは55.31/55.37 msで直前より約1.1%短いため採用する。artifactは
  `jit-artifacts/go-goal-20260915/useful-fast-loop/`。
- 0.8には現在candidateからさらに約8.8%必要。小さいleafの追加だけでは不足するため、perf trampolineを有効にしたfunction別
  sampleを採り、`Board.useful`、`Square.move/remove`、`EmptySet.random_choice`のどのframe/loop境界をまとめると最大のTier 1と
  frame費用を除けるか選ぶ。次の融合もcode shapeとruntime guardで一般化し、checksum/fallback/coverage後にblock測定する。

- CPythonのperf trampolineはexperimental JITと同時に有効化できず、`-X perf`/`-X perf_jit`はいずれもJITを停止することを
  実機で確認した。補助資料としてJITなし50 operationを`-X perf`で採取し、5,000 sample・lost 0を
  `jit-artifacts/go-goal-20260915/perf-trampoline-nojit/`へ保存した。`cProfile`でも5 operationを確認し、self time上位は
  `Square.find` 22.7%、`Board.useful` 18.3%、`EmptySet.random_choice` 9.5%、`Square.move` 8.1%だった。JIT有効時の判断は
  既存のnative C sample、executor coverage、実trace形を組み合わせる。
- call/local rootのinstance-method override確認で、各chain linkごとに同じUnicode keyをsplit keysから検索していた処理を除いた。
  class descriptor検証時にcached-key slotを一度だけ解決し、type versionとvalid inline-valuesで守られた各nodeではそのslotがNULLかを
  直接確認する。debug/nativeでread-only traversal、path compression、instance override、Go checksumと従来coverageを維持した。
  binary SHA-256は`ff750b2f...3808`。固定CPU 2の3 blockはmain比
  **0.873067 / 0.871578 / 0.875041**、幾何平均 **0.873227**で、直前の0.876610から約0.4%短縮した。
  artifactは`jit-artifacts/go-goal-20260915/root-method-slot/`。0.8にはさらに約8.4%必要なので、次はJIT有効時に残る
  `Board.useful`/`EmptySet.random_choice`のloop executor境界を特定し、frameを保つlocal loop融合でまとまったTier 1実行を除く。

- `Board.useful`の`neighbour.find()`は省略された`update=False`を補う`CALL_PY_GENERAL`であり、従来のcall-root変換は
  Python frameを生成した後の再帰部分しか融合できていなかった。calleeの完全なroot body、valid function version、exactな
  defaults tuple `(False,)`、type/layout/compact-int position、class descriptorとinstance override不在を証明する
  `_CALL_PY_REFERENCE_ROOT_DEFAULT`を追加した。呼出し入口から最大64 linkを直接走査し、実callerのreturn offsetへ戻って
  dynamic exitするため、callee frameを生成しない。defaults・method・layout変更時は副作用前に通常経路へdeoptする。
- debug Tier-2でGo checksumを維持し、1 operationで**47,746 call / 137,936 link**を新uopが処理した。LLVM 21 stencilを
  `-fno-vectorize -fno-slp-vectorize`と固定debug bootstrapで再生成し、PGO/LTOなしでnative JITを全rebuildした。nativeでも
  JIT enabled、選択手5、`TIMESTAMP` 81,059、`MOVES` 21,401を確認した。binary SHA-256は
  `bfe767bb5b5b1a818fe21583d711f5262099829b0bff9f121e088966439150e4`。
- CPU 2・resident・全6 opt-in・warmup 5/value 10の交互順3 blockはmain比
  **0.814678 / 0.808799 / 0.809721**、幾何平均 **0.811062**。root-method-slot版からcandidate時間を約7.1%短縮し、
  目標0.8まで残り約1.4%になった。artifactは`jit-artifacts/go-goal-20260915/root-default-call/`。
  次は新しいdefaults呼出しの変更・instance override・長いchain fallbackをfocused testへ固定する。同時に残存traceを調べ、
  `Board.useful`または`EmptySet.random_choice`の短いhot loopをframeを保つlocal uopへまとめ、同じblock測定で0.8以下を確認する。

- root三経路の各linkについて、同じobjectへの重複type/version検査を一回へまとめ、inline属性をoffsetから直接読む試作を行った。
  最初のinline helper版はTier-2 generatorがhelperをescape扱いしてloopごとにstack syncを挿入し、debugのstack bound検査が即座に
  検出した。helperを使わないatomic loadへ修正後はdebug/nativeのGo checksum、path compression、instance overrideを維持した。
- 修正版binary `eebd709c...f428a`のcandidate medianは51.43–51.69 msで直前版51.30–51.64 msから改善せず、main側の
  測定移動もあって3 blockは**0.811382 / 0.822354 / 0.820184**、幾何平均**0.817960**だった。artifactは
  `jit-artifacts/go-goal-20260915/root-direct-offset/`。効果がなくguard実装が複雑になるため試作をsourceから撤回した。
  次は47,746回のdefault root呼出し後のdynamic exitを減らす。callee frameを消したままcaller traceを安全に継続できる
  非再帰return pathを限定して照合するか、`Board.useful`の現在loop frameを保持したuopでfind後のcallback-free処理までまとめる。

- direct-call rootでは、recorded callableとselfのtype versionがclass descriptorを既に特定しているため、実行時の
  `_PyType_LookupRefAndVersion`をtype-version guardへ置き換えた。default変更、途中nodeのinstance override、class method差替え、
  64 link超過を含むfocused fixtureとdebug/nativeのGo checksumは成功した。binary `e30f69d3...de4da72`の3 blockは
  **0.805222 / 0.792947 / 0.824701**、幾何平均**0.807518**。候補前半は50.61/50.82 msまで下がったが、
  3 block目が51.85 msへ移動したため目標達成とは判定しなかった。artifactは
  `jit-artifacts/go-goal-20260915/root-call-type-guard/`。
- attribute traceの`_RECORD_TOS_TYPE`/`_RECORD_TOS`を後段matcherでも取得できるtype-aware parserを追加した。executor生成時に
  recorded type、type version、exact function、class descriptorを照合し、split-keyのmethod slotを0–254へ限定してuop operandへ
  符号化する。これによりcall/default/local rootの実行時class lookupとsplit-key lookupを全て除き、type versionと各nodeの
  inline instance slot NULL guardだけで変更を検知する。unbound callでclass methodが実行中functionと一致しない場合は変換しない。
- debug/nativeでdefault、read-only、path compression、instance/class override、defaults変更、長鎖fallbackとGo checksumを維持し、
  従来のroot coverageも維持した。PGO/LTOなしのnative binary SHA-256は
  `a9cf6d08d2c5571f2d3472f7b83d39a63dd911776cc0d302bd020eb9ab0cca00`。CPU 2・resident・全6 opt-in・
  warmup 5/value 10の交互順3 blockはcandidate **49.266 / 49.043 / 49.041 ms**、main
  **62.841 / 62.946 / 62.778 ms**、比 **0.785798 / 0.776873 / 0.783487**、幾何平均
  **0.782043**。全blockで0.8を下回り、Goの目標を達成した。artifactは
  `jit-artifacts/go-goal-20260915/root-method-slot-recorded/`。
- 次はdefault rootのfocused fixtureを`test_opt_regions`へ移し、debug/nativeの`test_tier3`と`test_capi.test_opt`を順次実行する。
  生成物、`git diff --check`、一時診断文字列、JIT docsとstandalone benchmark文書を確認し、最終結果をこの節へ追記する。

- default/local rootのfocused fixtureを`TestRegions.test_reference_root_default_and_local`として正式testへ移した。`def`を`exec`で
  生成して有効なfunction versionを持たせ、default call uopとlocal uopのcounter増加、read-only traversal、path compression、
  中間nodeのinstance method override、defaults変更、64 link超過fallback、class method差替えを一つのfixtureで検証する。
- 全region testの途中で、`get_region_stats()`へcounterを追加した際に`Py_BuildValue`のformatが77 pairのまま、実引数86 pairに
  増えていたため末尾9 counterが辞書から欠落する不具合を発見した。formatを10 pair単位の隣接文字列へ整形して86 pairへ修正し、
  format数と引数数が一致することを機械的に確認した。修正後、debug/nativeとも`test_capi.test_opt_regions` **229 tests**が成功した。
  nativeの`test_tier3 test_capi.test_opt`も**335 tests、4 skipped**で成功し、debugの`test_capi.test_opt`は
  **321 tests、3 skipped**、debug `test_tier3`は**14 tests**で成功している。全opt-inをprocess開始時から同時指定すると個別testが
  期待する変換順を変えるため、正式suiteはtest自身の`setUp`/個別contextが指定する環境で実行した。
- counter修正と全generator再実行でnative executable identityが変わったため、現binaryを同じCPU 2、resident、全6 opt-in、
  warmup 5/value 10、交互順3 blockで再測定した。最終再リンク後のcandidateは**49.394 / 49.115 / 49.098 ms**、mainは
  **62.991 / 63.570 / 62.811 ms**、比は**0.784139 / 0.772610 / 0.781677**、幾何平均
  **0.779460**。現binary SHA-256は`ebb86d4a...fb457`で、全blockが0.8未満のまま目標を達成している。artifactは
  `jit-artifacts/go-goal-20260915/final-validated/`。root body proof、default call frame省略、recorded typeからのmethod slot事前解決、
  guard/fallback、現測定値をcore developer向け英語文書`Tools/jit/regions.md`と`Tools/jit/optimization_report.md`へ反映した。
- 次はgenerated fileの再生成差分、standalone checksum/JIT状態、base64のmain差分、一時診断文字列、`git diff --check`とrepository hookを
  最終確認する。新しいGo専用変換は追加せず、達成済みの小さい実装をこの検証状態で固定する。

- 全case generatorを固定debug bootstrapで再実行したところ、`Python/optimizer_cases.c.h`だけに未反映の正当な差分があり、追加uopの
  symbolic stack effectと既存optimizer定義を生成し直した。他の15生成物は前後SHA-256一致。native stencilは既定makeの再生成を
  途中で止め、`/usr/lib/llvm-21`、`-fno-vectorize -fno-slp-vectorize`、固定debug bootstrapでforce生成を成功させてからstampを更新した。
  PGO/LTOは使用していない。再生成後にdebug/native双方でregion **229 tests**、Tier 3/C API optimizer **335 tests**を再実行して成功し、
  上記0.779460はこの完全再生成・最終再リンク後binaryの測定値である。
- 次はstandaloneのsyntax/checksum/JIT状態、base64差分、診断文字列、diffとhookだけを確認する。性能目標と実装・回帰検証は完了済み。

- standaloneは`py_compile`に成功し、nativeで`sys._jit.is_available()`/`is_enabled()`がともにtrue、move 5、timestamp差81,059、
  moves差21,401を再確認した。`Lib/base64.py`のmain差分は空、診断文字列は残存せず、`git diff --check`とoptimizer generatorの
  冪等性も成功した。`prek`はこのPCに未導入だったため、pushしない本作業ではnetwork installを行わずrepositoryの`patchcheck`を試したが、
  local branchにupstream PR情報がなく`base_branch=None`でコード検査前に停止した。これによるsource変更はない。必要な実装、性能、
  correctness、生成物、文書の確認は完了した。

## 20. pyperformance再比較のローカル実行準備（2026-09-15）

- ユーザーがsandbox外のterminalでpyperformanceを実行する方針になったため、この工程ではbenchmark本体を起動しない。比較対象は
  fixed main `build-main-jit/python` (`8fb6c5b...3407`) と完全再生成後candidate `build-jit/python`
  (`ebb86d4a...fb457`)。両target venvのpyperformance **1.14.0**、pyperf **2.10.0**、67 packageのfreeze SHA-256
  `84a767bb...8cbf`が一致し、JIT available/enabledも確認した。
- candidate再リンクでpyperformance worker cache IDが`cpython3.16-8a5d1efb5ad3-compat-31b33d68c68a`へ変わっていた。
  旧candidate cacheは同じ`build-jit/python`をbase executableとし同一依存を持つため、新IDへoffline複製した。
  `pyperformance venv show`がalready createdを返し、新cacheからpyperformance/pyperf/networkxのimport、base executable、
  freeze hash一致を確認した。main cacheもalready createdのまま。
- `benchmarks/run_pyperformance_compare.sh`を追加した。binary、group、runner、dependency hash、CPU affinity、両側JIT状態を実行時に
  preflightし、前回固定したfastapi除外後96 specificationをA: main→candidate、B: candidate→mainで逐次実行する。後発側には
  同群の`--same-loops`を渡す。簡潔なrunnerにするためworker timeoutは全項目60秒で、従来300秒だったnetworkx系を早く打ち切る。
  4 raw JSON/log/state/return codeを保存し、A+Bをside別にmergeしてofficial `pyperf compare_to`表とcheck結果も同じ出力先へ生成する。
  個別benchmarkの失敗やtimeoutでrunnerが1を返しても4 suite JSONがあれば比較生成まで進む。出力先を固定して再実行すれば、
  `run_groups.py`が完了済みstepをhash確認後skipする。
- 次はユーザーがsandbox外で
  `./benchmarks/run_pyperformance_compare.sh jit-artifacts/pyperformance-rerun-current`を実行する。完了後、`compare.md`、4 log、
  `state.json`、merged JSONを解析し、共通成功集合・loop一致・幾何平均・失敗分類を現candidateについて更新する。
- scriptへ`PYPERFORMANCE_PREFLIGHT_ONLY=1`を追加し、実行本体と同じbinary/group/runner/dependency hash、CPU 2、両JIT状態の
  preflightをbenchmarkなしで完走した。Bash構文と`git diff --check`も成功。script SHA-256は
  `93b7814e3598fc978f149d8fba5062fb4c4c07caa90ee0f24e21b01c1b86650c`。

## 21. 現candidateのpyperformance再比較結果（2026-09-15）

- ユーザーがsandbox外で`benchmarks/run_pyperformance_compare.sh`を完走した。固定main
  `8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`、candidate
  `ebb86d4a70b9dda5c4f70d4d49196cc5a87986c41ced14951f73dd0eef2fb457`、CPU 2、resident JITと全6 opt-in、
  pyperformance 1.14.0 / pyperf 2.10.0、worker timeout 60秒である。4 raw JSONのhashを固定し、A/Bともmainとcandidateの
  result名が一致すること、metadataのCPU/version、各resultの6 measured processを機械確認した。
- fastapiを事前除外した96 specification中、**93件**が両側で完了して**119 result名**を生成した。以前sandboxで失敗した
  `2to3`、`asyncio_tcp`、`asyncio_tcp_ssl`、`concurrent_imap`由来の2結果、`tornado_http`、NetworkXの3結果を新たに取得した。
  失敗は両側で同じ3件だけで、`asyncio_websockets`はTCP 8001の使用中、`dask`はcloudpickleの`DELETE_GLOBAL`依存、
  `genshi`はPython 3.16の`ast.Expression` constructor非互換だった。runner return code 1はこの対称な欠落を表し、4 suiteの
  比較生成自体は完了している。
- B群の`deepcopy_reduce`と`deepcopy_memo`だけ、先発candidateが個別校正した65,536 / 8,192 loopsを後発mainの
  `--same-loops`が保持できず、mainは両方1,024 loopsになった。主指標はこの2件を除く**117 loop一致result**の同重み幾何平均とした。
  candidate/mainは **0.972383**、すなわち**実行時間2.76%減、1.028倍**。各側の6 process meanを独立再抽出する20,000回
  bootstrap（seed 20260915）の95%区間は**[0.970999, 0.973748]**である。2件も含む119結果の感度値は0.972324、official
  `pyperf compare_to`の丸め表示も**1.03x faster**で整合した。
- 名目上は76改善/41回帰、pyperf既定t-testでは**51改善/33回帰/33有意差なし**。unstable warningはmain 56、candidate 48。
  A/B群の幾何平均は0.961057 / 0.980341。tag別はapps 0.9742、asyncio 0.9861、math 0.9777、template 0.9450に対し、
  regex 1.0139、serialize 1.0056、startup 1.0049だった。
- 最大改善はSpectral Norm **0.4835**、Hexiom **0.5794**、Raytrace **0.7296**、Go **0.7776**、BPE **0.8013**、
  `k_core` **0.8518**。Goはfull pyperformanceでも0.8目標を満たした。最大回帰は`base16_large` **1.1240**、
  `base16_small` **1.0680**、`base32_small` **1.0539**、`regex_v8` **1.0530**、Telco **1.0505**だった。
  main統合済みなので今回のBase16差は以前診断した`Lib/base64.py`のrevision差ではない。
- NetworkXは短い60秒timeoutでも3 specificationすべて完了した。`shortest_path` 1.0179、`k_core` 0.8518、
  `connected_components` 1.0160。ただしmainの`k_core`は標準偏差9.6%で、改善量の精度は他の上位結果より低い。
- 前回解析にも存在し今回loop一致した108結果に限定すると、旧candidate/main 0.968231、現candidate/main 0.971144で、
  現runは相対0.3%悪い。旧candidateはmain統合前、現candidateはmain統合とGo最適化後であり、main側sampleも別runなので、
  この差を個別JIT変更の効果とは断定しない。現在のsource整合性と広いcoverageを持つ0.972383を現candidateの代表値とする。
- 再現可能な解析を`jit-artifacts/pyperformance-rerun-current/analyze.py`へ保存した。固定input/binary hash、loop一致、幾何平均、
  process-bootstrap、pyperf有意差/warning、以前との共通集合を検査し、`analysis.json`、`ratios.csv`、`warnings.json`、
  `summary.md`を生成する。次に厳密な全119結果の値が必要ならdeepcopy 3結果だけを共通8,192 loopsで補正する。高速化を続ける場合は
  現在のBase16/regex回帰と、旧版から利益が減ったasync-treeをmerged baselineとの限定比較で切り分け、JIT変換に帰属できるものから直す。

- Base16はmain統合でsource差を除いたはずとの指摘を受け、両workerが読む`base64.py`を実path/hash付きで再確認した。mainは保存snapshot、
  candidateはcheckoutのファイルを読むが、ともにSHA-256 `4b0f8781...64fb`で内容は同一、benchmark driverも両側で同一である。
  現binary用の固定診断script `base16-diagnosis/diagnose_base16.py`を追加し、CPU 2、small 512 / large 32 loops、通常6 process x
  10 values、candidate→mainでJIT無効を再測定した。結果はsmall **1.08617**、large **1.13667** candidate/mainで、各側の
  標準偏差は1.2%以下、loopも一致した。したがって今回の回帰は`Lib/base64.py`差ではなく、candidate binaryに含まれるJIT外の
  runtime差またはbuild/code-layout差でも再現する。次はJIT有効・全opt-inなしを同じdriverで測り、native JITの寄与を分離する。

- JIT有効・全opt-inなしのfocused再測定はsmall **1.05954**、large **1.12894**で、full-suite値をほぼ再現した。JITはsmallの差を
  むしろ少し縮め、largeの差にはほぼ影響しない。さらにmain統合直後・Go修正前の保存binary
  `python-go-merged-baseline` (`ebc3a1d9...c34a1`)をJIT無効で測るとsmall **1.06240**、large **1.13531**だった。
  現candidateのGo向け変更より前から存在するため、それらはBase16回帰の原因ではない。`binascii` extensionの`.text` hashは
  main/candidateで同一。一方、実行ファイル内の`_Py_bytes_upper`は命令列が同一でもmainの0x10ce50からcandidateの0x112420へ移動し、
  merged baselineと現candidateは同じ配置だった。次はBase16のC処理を要素別に測り、bytes upperの配置差を原因として再現できるか確認する。

- JIT無効focused測定をmain→candidateへ反転してもsmall **1.08533**、large **1.13309**で再現し、二block幾何平均は
  **1.08575 / 1.13488**。実行順やCPU warmupではなかった。1 MiB入力を分解した反転2 blockの幾何平均は`hexlify` 1.05674、
  `bytes.upper` 1.05453、6回の不在membership scan 1.01771、`unhexlify` 1.00197、完全encode **1.34161**、完全decode
  **1.00946**。large回帰は主に、2 MiB級のencode戻り値をbenchmarkが即解放する経路にある。
- benchmarkと同じ即解放encodeを800回行うsequential `perf stat`では、両binaryのinstruction数とminor fault数（約816,000回）が
  ほぼ同じだった。kernel cycle/syscall回数も近い一方、candidateのuser cycleが多くIPCが低い。診断専用にglibcのmmap/trim/top-pad
  thresholdを8 MiBへ上げるとminor faultは約2,600回へ減り、task-clock差は約1.4から約1.06へ縮んだ。このallocator設定は
  suite測定や結論には使用しない。
- `binascii` extensionの`.text`と`_Py_bytes_upper`の命令列は両側で同一。ただしupperのhot loopはmainで32-byte block内のoffset 8、
  candidateでoffset 24から始まり後者だけblock境界をまたぐ。merged pre-Go binaryも現candidateと同じaddressである。source mergeは
  成功しており、残ったBase16差は大容量一時bytesのallocation/page faultで増幅される**rebuild/code-layout感度**と判断する。
  `Lib/base64.py`やopt-in JIT変換のsemantic regressionとして扱わない。詳細を`base16-diagnosis/summary.md`へ保存した。
- 事後感度としてBase16 2結果を外すと115結果の幾何平均は**0.970367**（主結果0.972383）。主結果は事前集合のまま変更しない。
  次のJIT高速化でbytes coreへ配置hackは追加せず、Base16はfixed binary identity付きのlayout confoundとして報告する。

## 22. `main`で発見した不具合の整理（2026-09-15）

- method JIT着手前の依頼により、ここまでの作業で`main`に対する再現またはsource-levelの根拠が得られた不具合を
  `bugs_report.md`へ英語で整理した。正しさ3件、JIT lifecycle/resource 2件、generator/build/LLVM 7件、確認済みの
  性能上の制約2件を分類し、各項目に影響、期待値と実測、原因、再現物、ローカル修正commitまたは未修正状態を記載した。
- 発見時の固定mainは`a60343ed17785ebbcd43de9080cadd8e2541db6f`、binary SHA-256は
  `8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`。現在のlocal main
  `2fcb0e27d959345151750b756af79054c3230531`までの差分が対象JIT/optimizer/generator fileを変更していないことも確認した。
- 固定main binaryに現在の回帰testを読ませ、copied builtinsが期待42に対して1、短いloop counterが期待4000に対して8190、
  dict receiver用guardの代わりにTOS guardを生成する失敗を再確認した。copied globalsの独立reproducerも期待152に対して68を返した。
  現candidateでは対応する5重点testがすべて成功した。
- report内の相対link 20件は全て実在し、`git diff --check`対象の末尾空白はない。Base16のbuild/layout感度、pyperformance timeout、
  実験uop固有の不具合などは`main`のbugとして混同せず除外理由を明記した。GitHub投稿、push、PR変更は行っていない。
- 次の作業は、保留しているPEP 836型method JITとpyperformance 20%目標について、現trace frontendから再利用するmiddle-end/backend、
  method CFG/SSA、type profiling、path splitting、generic unboxing・refcount除去・call最適化の段階的実装計画を確定すること。

## 23. pyperformance全成功resultのmethod JIT向け調査（2026-09-15）

- `jit-artifacts/pyperformance-rerun-current/`の成功93 specificationが生成した119 resultについて、benchmark driverの登録関数、
  main loop、import/call先を読み、`pyperf_report.md`へ日本語で一件ずつ記録した。各行にcandidate/main比、Python JITへの優先度、
  支配すると考えられる処理、method JITまたはJIT外で必要な高速化を対応付けた。失敗した`asyncio_websockets`、`dask`、`genshi`は
  成功集合と混同せず対象外とした。
- 比率は固定済み`ratios.csv`から照合した。表のresultは**119行・119 unique**で、CSVとの差集合と重複が空、丸めた比率の転記誤差も
  空であることをscriptで確認した。`deepcopy_memo`/`deepcopy_reduce`のloop不一致、標準偏差5%以上のresult、1%精度不足warningを明記し、
  3%未満の差をmethod JIT設計の一次根拠にしない方針とした。`git diff --check`も成功した。
- source調査から、method JITの共通優先機能を (1) method全体CFGとOSR、(2) type/function/globals dependency付きPython call inline、
  (3) layout既知の属性load/store、(4) method/loopをまたぐint/float unbox、(5) exact list/dict/set lowering、(6) iterator・短命objectの
  virtualization/scalar replacement、(7) generator/coroutine状態機械化、と判断した。`richards`、template、SQLGlot、NetworkX、
  pure-Python pickle、Pyflate、SciMark、async-treeを段階ごとの代表cohortに割り当てた。
- 既存native profileと専用counterがあるSpectral Norm **0.4835**、Hexiom **0.5794**、Raytrace **0.7296**、Go **0.7776**、
  BPE **0.8013**を詳細節で再評価した。DeltaBlueとpyperformance外のstandalone B-treeも、method inline、container loop、unboxへ
  一般化できる成功例として記録した。その他の見かけ上の改善は、対応counter/profileがない限り既存JIT変換へ帰属させない。
- startup/process、TCP/SSL/event loop、C codec/JSON/pickle/regex/XML、GC/allocator、big-int/Fraction/Decimal/SQLiteはJIT外の支配領域として
  分離した。suite全体20%をmethod JIT単独の最初の採否条件にはせず、まずPython bytecode支配cohortで20%を測り、その後all-suiteと
  JIT対象外cohortの幾何平均を併記してAmdahl上限とlayout影響を判断する。
- PEP 836本文を再確認し、method frontendは既存uop middle-end/Copy-and-Patch backendをほぼ再利用し、CFG、merge点のtype join、
  SSA的stack、region/worklistを追加する範囲であることをreportへ反映した。PEPの20%はfree-threaded JIT対free-threaded interpreterの
  Tier 1平均であり、今回のGIL build一台の0.972383を直接の合否値にしない。local比較はoptimizer/runtimeの優先順位と回帰検出に使う。
- 次の作業は第一段階のmethod JIT prototypeとして、monomorphic Python method inline、既知instance layoutのfield load/store、
  loop backedge OSRの最小IR/guard契約を既存Tier 2/Tier 3へ接続することである。最初は`richards`、`raytrace`、`deltablue`、`go`、
  template cohortでexecutor coverageとnative profileを取り、frame/dispatch/lookup/allocationの減少を確認してからnumeric/container/
  generator段階へ進む。
