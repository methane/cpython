# CPython Tier 2：Linux上で行う2〜3日間の実装計画

**現在の目標（2026-09-14）**：全6ベンチマークのmain比の**算術平均0.5以下**。
開始時の480値は **0.7944918**。最新240値のscreenは **0.7299191**で、この新目標は未達。
各blockの各scriptで10値の平均時間からcandidate/main比を求め、4 blocksと6 scriptを
等重みの算術平均で集計する。入力・CLI・warmups=3・values=10・loops=1、固定main、
PGO/LTOなしの比較条件を維持し、末尾の新工程を進める。

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

## 17. 継続目標：6本のmain比の算術平均を0.5以下へ（2026-09-14）

- 新しいgoalと「JITの高速化を続けて」という指示に従い、前回の幾何平均の達成を新指標の
  達成とは扱わない。前turnは英文ドキュメントの完成と数値監査で進捗あり。新工程は
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
