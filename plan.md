# CPython Tier 2：Linux上で行う2〜3日間の実装計画

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
