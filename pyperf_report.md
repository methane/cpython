# pyperformance 成功結果ごとの JIT 高速化調査

## 目的と結論

この文書は、`jit-artifacts/pyperformance-rerun-current/` に保存した比較で実行に成功した **119 result（96 benchmark specification のうち成功した 93 specification）** を一つずつ調べ、現在の tracing JIT、将来の method JIT、JIT 以外のどこを速くする必要があるかを整理する。比較対象は固定済みの main binary（SHA-256 `8fb6c5b8...3407`）と candidate binary（`ebb86d4a...fb457`）で、CPU 2、pyperformance 1.14.0、pyperf 2.10.0、A/B で開始順を反転し、同じ loop 数を使った結果である。candidate は native JIT と resident policy に加えて、今回実装した六つの opt-in 最適化群を有効にしている。

loop 数が一致した117 resultの candidate/main 幾何平均は **0.9724、2.76%短縮**だった。これは現在の限定的な trace 変換が一部の workload を大幅に速くする一方、suite 全体を広く20%速くする実装にはなっていないことを示す。method JITで広い効果を得るには、次の機能を共通基盤として実装する必要がある。

1. method全体のCFGを保持し、loop backedgeからOSRできること。短いtraceごとの入口、guard、dispatcher復帰を減らす。
2. Python methodをguard付きでinline化し、callee frameの作成・初期化・破棄、`vectorcall`、引数bindを除くこと。関数versionだけでなくtype、method slot、globals identityと名前単位dependencyを検査する。
3. 属性を既知layoutのoffsetから読み書きし、int/floatをmethodとloopをまたいでunboxすること。int overflow、floatの演算ごとのbinary64丸め、例外、監視をside exitで保つ。
4. 短命なtuple、iterator、座標・vector・AST補助objectをvirtualizeし、scalar replacement、allocation除去、refcount sinkingを行うこと。
5. exact `list` / `dict` / `set` の反復、添字、membership、`append`、小整数更新をversion・bounds guard付きでloweringすること。
6. generator、coroutine、async generatorをresume点を持つ状態機械としてmethod単位でcompileし、yield/send/awaitごとのframe往復を減らすこと。

一方、process起動、socket/SSL、event loop、C版codec・JSON・pickle・正規表現、SQLite、GC、allocator、big-int、Decimalが支配するresultはmethod JITだけでは20%短縮できない。suite全体20%を目標にするなら、これらのruntime/C実装も別にprofileして改善する必要がある。

[PEP 836](https://peps.python.org/pep-0836/) は、method frontendが「何をcompileするか」をtraceから一つ以上のmethodへ変更し、既存のuop IR、middle-end/optimizer、Copy-and-Patch backendをほぼ再利用する案である。必要な新基盤はCFG、merge点のtype join、stackのSSA的性質、loop/generator/coroutineなどのregion表現とworklistであり、将来のtype profile、path splitting、cold-code eliminationも挙げている。PEPの20%目標は **JIT付きfree-threaded build対JITなしfree-threaded buildをTier 1 platform間で平均する** もので、今回のGIL build一台の2.76%とは直接比較できない。Year 1の最小frontendは一時的に遅くなる可能性も認められている。このreportはmethod frontend単体の合否ではなく、そのfrontend上で20%へ進むためのoptimizer/runtime課題を選ぶ資料である。

## 読み方と調査方法

`比率` は candidate/main で、小さいほど速い。括弧内は実行時間の変化である。3%未満は、pyperfが統計的有意と表示しても、method JITの設計根拠としては原則「ほぼ同等」と扱う。`†` は少なくとも片側の標準偏差が5%以上、`‡` はloop数不一致であり、改善量の一次根拠にしない。`優先度` はmethod JITへの期待を表し、`高` はPython bytecodeが中心、`中` はPythonとC/runtimeが混在、`低` は主にJIT外である。これは各benchmark driverと呼び出し先の実装を読んだ静的分類であり、既存のnative profileと専用counterがある対象だけを実測済みhot pathとして扱う。

実行に失敗した `asyncio_websockets`、`dask`、`genshi` は今回の119 resultに含めない。各benchmarkのraw値、標準偏差、significanceは `jit-artifacts/pyperformance-rerun-current/ratios.csv`、公式比較は同ディレクトリの `compare.md` にある。

## 1. 起動、process、thread、filesystem、network

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `2to3` | 1.009（+0.9%） | 低〜中 | 新processの起動、import、`lib2to3`のtokenize/parse、filesystem走査の混合。method JITはparserのPython loopには効くが、短命processではcompile費を回収しにくい。startup/import cacheとparser/runtime側が先。 |
| `bench_mp_pool` | 1.007（+0.7%） | 低 | `multiprocessing.Pool.imap`のprocess間通信、pickle、pipe、schedulerが中心。worker内の小仕事をJIT化するよりIPCとbatchingを改善する。 |
| `bench_thread_pool` | 0.997（−0.3%） | 低 | `ThreadPoolExecutor`のqueue、lock、future、thread schedulingが中心。JITよりexecutor/queueのC fast pathとallocation削減が必要。 |
| `pathlib` | 0.994（−0.6%） | 中 | `Path` object生成、path文字列処理と`stat`/directory syscallの混合。method JITはpure-Python path操作と小methodをinline化できるが、filesystem待ちは残る。 |
| `python_startup` | 1.007（+0.7%） | 低 | process生成、runtime初期化、site/import。hot methodができる前に終了するためJIT対象ではない。frozen import、marshal、allocator、relocationを改善する。 |
| `python_startup_no_site` | 1.003（+0.3%） | 低 | siteを除いたruntime初期化そのもの。JIT code生成を起動pathへ入れず、interpreter初期化とimport machineryを改善する。 |
| `asyncio_tcp` | 0.997（−0.3%） | 低〜中 | loopback socket、selector、stream read/write、task scheduling。protocol callbackのmethod inline化余地はあるが、syscallとevent loopのC/Python境界が中心。 |
| `asyncio_tcp_ssl` | 1.007（+0.7%） | 低 | 上記にOpenSSL record処理と暗号化を加えたもの。method JITよりSSL buffer、BIO、socket/event-loop境界をprofileする。 |
| `tornado_http` | 0.995（−0.5%） | 中 | loopback HTTP、IOLoop、Future、header parseの混合。handler/parserのPython methodはinline候補だが、socket、selector、buffer copyはJIT外。 |

## 2. asyncio、generator、coroutine

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `async_generators` | 1.038（+3.8%） | 高 | 再帰的async generatorの`__aiter__`、`__anext__`、yield/resume、frame状態保存。method JITはasync generatorを状態機械化し、resume dispatchとframe/refcount操作を除く必要がある。 |
| `coroutines` | 0.997（−0.2%） | 高 | generator-based coroutineの`.send()`とFibonacci生成。calleeのbodyだけでなくsend/yield境界をcompileし、suspended frameへの値の受渡しを直接化する。 |
| `generators` | 1.006（+0.6%） | 高 | recursive generator、`yield from`相当の反復、list化。generator frameとiterator objectをvirtualizeし、producer/consumer fusionを行う。 |
| `async_tree_none` | 0.979（−2.1%）† | 高 | coroutine treeの作成、再帰call、task/gather scheduling。leaf仕事が空なのでscheduler/frame費が露出する。method JITはcoroutine callとawait continuationをinline化する。 |
| `async_tree_none_tg` | 0.981（−1.9%）† | 中〜高 | `TaskGroup`版の空tree。coroutine最適化に加え、Task/TaskGroup生成、callback list、exception bookkeepingのruntime fast pathが必要。 |
| `async_tree_eager` | 0.987（−1.3%）† | 高 | eager taskでscheduler往復を減らした空tree。残る再帰coroutine frame、await、result伝播をmethod単位で融合する。 |
| `async_tree_eager_tg` | 1.004（+0.4%）† | 中〜高 | eager taskとTaskGroup管理が混在。method JITは小coroutineをinline化し、runtime側はTaskGroup bookkeepingを減らす。 |
| `async_tree_io` | 0.983（−1.7%） | 中 | leafが`asyncio.sleep`するためtimer heap、event loop wakeupが中心。coroutine frame最適化だけで20%は難しく、timer/scheduler側も必要。 |
| `async_tree_io_tg` | 0.977（−2.4%）† | 中 | sleep、TaskGroup、exception/result収集が中心。JITはcallback methodを減らし、event loopとTaskGroupのC/runtime fast pathを併用する。 |
| `async_tree_eager_io` | 0.994（−0.6%）† | 中 | eager開始後すぐsleepでsuspendする。method JITで最初の同期区間をinline化できるが、timer待ちとresume queueが残る。 |
| `async_tree_eager_io_tg` | 0.999（−0.1%）† | 中 | eager、sleep、TaskGroupの混合。ほぼ同等であり、method JIT候補はawait前後のcontinuation、JIT外候補はtask/timer管理。 |
| `async_tree_memoization` | 0.989（−1.1%）† | 高 | coroutine treeにdict memoizationを追加。call/await融合に加え、exact dict lookup・insertとtuple/int keyのvirtualizationが必要。 |
| `async_tree_memoization_tg` | 1.004（+0.4%）† | 高 | memoizationとTaskGroup。method JITでdict操作とcoroutine bodyを同じmethod CFGに置き、TaskGroup管理はruntime側で短縮する。 |
| `async_tree_eager_memoization` | 0.983（−1.7%）† | 高 | eager taskで同期実行されるdict lookup/updateが増える。method JITのdict fast path、recursive inline、短命task回避が主候補。 |
| `async_tree_eager_memoization_tg` | 0.992（−0.8%）† | 高 | 上記にTaskGroupを加えたもの。JITは同期完了するchildをtask objectなしで処理できるproofが必要。 |
| `async_tree_cpu_io_mixed` | 0.957（−4.3%） | 高 | pure-Python CPU leafとsleepの混合。CPU loopのint演算・call・container操作をcompileし、awaitをside exit/continuationとして接続する。 |
| `async_tree_cpu_io_mixed_tg` | 0.963（−3.7%） | 高 | CPU leafのJIT余地は同じで、TaskGroup費も含む。現在の改善は有望だが、専用counterなしなので原因は未確定。 |
| `async_tree_eager_cpu_io_mixed` | 0.943（−5.7%） | 高 | eager区間でCPU leafが連続実行される。method JITのOSR、int unbox、recursive inlineを検証する良い代表。 |
| `async_tree_eager_cpu_io_mixed_tg` | 0.952（−4.8%） | 高 | eager CPU区間とTaskGroupの両方を含む。CPU methodをcompileし、同期完了childのtask bookkeepingを消すと広く効く。 |

## 3. codec、serialization、regex、XML

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `base16_large` | 1.124（+12.4%） | 低 | `binascii.hexlify`等のC loopと約81.6万minor faultを伴う大きなbytes allocation。JIT無効でも同方向に悪化したためmethod JIT課題ではない。allocator、page fault、code/data layoutを分離して調べる。 |
| `base16_small` | 1.068（+6.8%） | 低 | 短いC codec call、bytes allocation、call境界。Python wrapper inline化の上限は小さく、`binascii`とsmall-bytes allocationを改善する。 |
| `base32_large` | 1.000（+0.0%） | 低〜中 | base32のblock処理とbytes/string操作。大入力はalgorithm本体が中心で、Python loopをJIT化できる部分とC helper/allocatorをprofileで分離する。 |
| `base32_small` | 1.054（+5.4%） | 中 | Python-level validation/table lookup/loopとsmall bytes allocationの固定費が相対的に大きい。method JITはloop、添字、int bit操作をloweringし、allocator側も必要。 |
| `base64_large` | 1.000（−0.0%） | 低 | C `binascii`のbulk encode/decodeと大bytes allocationが中心。method JITではほぼ動かない。 |
| `base64_small` | 1.024（+2.4%） | 低 | C helperを呼ぶ短いPython wrapperとsmall allocation。call inlineだけではC処理とallocationが残る。 |
| `urlsafe_base64_small` | 1.039（+3.9%） | 低〜中 | base64 C helperに`altchars`のtranslate/validationを加えた経路。wrapperのbranchはJIT化できるが、bytes translateとallocationの改善が主。 |
| `ascii85_large` | 1.000（−0.0%） | 中 | base85のPython/C混合block処理。大入力loopのint bit操作、table lookupをunboxできるかprofileし、bytes builderのcopyも減らす。 |
| `ascii85_small` | 1.006（+0.6%） | 中 | 固定call・validation・allocationの比率が高い。method JITはbranch/loopをinline化できるが、small-bytes生成も支配する。 |
| `base85_large` | 1.001（+0.0%） | 中 | blockごとのint変換、table lookup、bytes組立て。method JITでPython loopをunboxし、C/allocator側のcopyを別に減らす。 |
| `base85_small` | 1.045（+4.5%） | 中 | 短いPython loopとallocation。small-input専用fast pathまたはmethod JITのbit演算・bounds除去が必要。 |
| `json_dumps` | 1.013（+1.2%） | 低 | defaultのC `_json` encoder、Unicode/bytes builder、dict/list traversalが中心。JITよりC encoder、allocation、string builderを改善する。 |
| `json_loads` | 0.976（−2.4%） | 低 | C scannerとobject生成が中心。Python wrapperを消しても上限が小さく、scanner、Unicode/number変換、container allocationが対象。 |
| `pickle` | 1.007（+0.7%） | 低 | C `_pickle.Pickler`とmemo/object traversal。JITよりC dispatch、memo table、output bufferを改善する。 |
| `pickle_dict` | 1.038（+3.8%） | 低 | C picklerによる大量dict traversal。dict iterationはC内部なのでmethod JITではなく `_pickle` とallocationをprofileする。 |
| `pickle_list` | 0.999（−0.1%） | 低 | C picklerのlist batch処理。JIT効果はほぼなく、C loopとbuffer growthが対象。 |
| `pickle_pure_python` | 0.988（−1.2%） | 高 | Python `_Pickler`のopcode dispatch、type dispatch table、memo dict、recursive `save` method。method inline、PIC、dict/list fast path、buffer appendが効く。 |
| `unpickle` | 0.967（−3.3%） | 低 | C `_Unpickler`のopcode loopとobject allocation。method JIT外でC dispatchとallocationを改善する。 |
| `unpickle_list` | 1.022（+2.2%） | 低 | C opcode loopとlist construction。JITではなく `_pickle` のbatch append、preallocation、memo処理が対象。 |
| `unpickle_pure_python` | 0.917（−8.3%） | 高 | Python `_Unpickler`のbyte opcode dispatchと多数の小さい`load_*` method call。method JITのdispatch-loop compilation、method inline、stack list操作が直接効く。 |
| `regex_compile` | 1.011（+1.1%） | 中 | Python parser/compiler/cacheとC regex object生成の混合。method JITはtoken parser、recursive compile、list appendを速くできるが、C compiler/cacheも残る。 |
| `regex_dna` | 1.046（+4.6%） | 低 | 既にcompile済みpatternのC `_sre` search/subが中心。JIT外のregex engine、Unicode/bytes走査、結果allocationを改善する。 |
| `regex_effbot` | 0.949（−5.1%） | 低 | 多数の短いC regex call。現改善はcode layout等も疑い、method JIT成果としない。`_sre` call/setupとmatch object allocationをprofileする。 |
| `regex_v8` | 1.053（+5.3%） | 低 | C regex engineによるsearch/matchが中心。method JITではなくengineのprefix/search loopとmatch allocationが必要。 |
| `xml_etree_generate` | 0.986（−1.4%） | 中 | Python loopからC `_elementtree`のElement/SubElementを大量生成しserializeする。loop/call inlineと、C node allocation/string builderの両方が必要。 |
| `xml_etree_iterparse` | 0.987（−1.3%） | 低〜中 | Expat/C element builder、iterator callback、file parse。method JITはevent consumerだけで、parserとtree allocationが主。 |
| `xml_etree_parse` | 0.970（−3.0%） | 低 | ExpatとC `_elementtree`のtree構築。JIT外のparser callback、node allocation、Unicode処理を改善する。 |
| `xml_etree_process` | 0.983（−1.7%） | 中 | 既存treeをPythonで反復し属性/textを読む処理とC Element access。method JITのiterator/attribute/list loopに余地がある。 |
| `telco` | 1.050（+5.0%） | 低 | C `_decimal`演算、`struct`、binary I/O/formattingが中心。method JITよりDecimal context/quantize、conversion、output bufferを調べる。 |

## 4. 数値計算、探索、graph、pure-Python algorithm

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `bpe_tokeniser` | **0.801（−19.9%）** | 高・実績あり | regex分割後のbytes pair生成、`Counter`/dict更新、`max(stats, key=lambda...)`がhot。既存のzip pair、dict小整数更新、max直接走査が効いた。method JITではiterator/tupleをvirtualizeし、dict loopとlambdaをinline化して一般化する。 |
| `chaos` | 0.912（−8.8%）† | 高 | `GVector`、Spline、Chaosgameの小method、float演算、短命vector、`sqrt`/random。method inline、属性offset、float unbox、scalar replacementが主で、libm/random callは残る。 |
| `comprehensions` | 0.939（−6.1%） | 高 | list comprehension、generator/`any`、dataclass/enum属性、dict `get`、sort。comprehension bodyとconsumerのfusion、call/PIC、短命iterator/listのallocation削減が必要。 |
| `crypto_pyaes` | 0.989（−1.1%） | 高 | pure-Python AESのround loop、table lookup、list添字、XOR/shift。compact intのunbox、bounds check除去、list/tableのhoist、round method inlineが必要。 |
| `deltablue` | 0.946（−5.4%） | 高・実績あり | OO constraint solverの多数の小method、属性、list走査。既存のbounded equality scanとcall短縮が効く。method JITではconstraint method群をinlineし、field load/storeとlist loopを一つのCFGへ一般化する。 |
| `fannkuch` | 1.007（+0.7%） | 高 | permutation loopのsmall int、list添字、slice、`pop`/`insert`、branch。loop全体のint unbox、bounds elimination、list mutation loweringが必要。局所patternだけではほぼ同等だった。 |
| `float` | 0.954（−4.6%）† | 高 | Point objectのnormalize/maximize、属性float、`sin`/`cos`/`sqrt`。method inline、float SSA、Pointのscalar replacementが必要で、libm callはJIT外に残る。 |
| `go` | **0.778（−22.2%）** | 高・実績あり | Board/Squareのroot探索、path compression、method call、list/set、random。既存の64-link root body、default-call frame省略、method slot事前解決が効いた。method JITでは`find`とcaller loopを再帰/loop CFGとしてinlineする。 |
| `hexiom` | **0.579（−42.1%）** | 高・実績あり | solverのsmall int/list、membership、generatorを受ける`sum`、条件付きremove、多数の小method。既存の専用集約・list fast pathが効いた。method JITではgenerator-consumer fusionとsolver method inlineへ一般化する。 |
| `mdp` | 0.946（−5.4%） | 中〜高 | namedtuple、dict/defaultdict、topological traversalと`Fraction`/big-int演算。method JITはtree/collection操作を速くできるが、Fraction/big-intのC object演算とallocationも支配する。 |
| `meteor_contest` | 1.034（+3.4%） | 高 | exact-cover探索のset/frozenset、bisect、list、branch、recursive search。method JITにはset operation、iterator、recursive inline、allocation削減が必要。現candidateの回帰は優先profile対象。 |
| `nbody` | 0.995（−0.5%） | 高 | body listを回る二重float loopと属性/tuple更新。既存の局所float融合ではほぼ動かず、method全体のfloat unbox、loop-invariant hoist、body objectのscalar replacementが必要。 |
| `nqueens` | 0.983（−1.7%） | 高 | permutations generator、tuple/set生成、diagonal check。generator fusion、small int unbox、短命tuple/setのvirtualizationが必要。 |
| `pidigits` | 0.985（−1.5%） | 中 | generator/`itertools`のglueと任意精度整数演算。method JITはiterator/callを減らせるが、桁数増加時はbig-int multiply/divideが支配するためlongobject側も必要。 |
| `pyflate` | 0.976（−2.4%） | 高 | pure-Python bit reader、Huffman decode、list/dict、shift/maskの密なloop。method inline、int unbox、bounds elimination、bit-bufferをregisterに保持する必要がある。 |
| `raytrace` | **0.730（−27.0%）**† | 高・実績あり | Point/Vector/Rayの小methodとfloat geometry、短命object。既存のdot融合、exact Python `__sub__` fast frame、constructor/call短縮が効いた。method JITではcall graph inline、float SSA、vector/pointのscalar replacementへ一般化する。 |
| `richards` | 1.005（+0.5%） | 高 | scheduler simulationの多数の小さいvirtual method、属性load/store、Packet/Task objectとlist。PIC付きinline、field offset、escape analysis、refcount sinkingが必要。 |
| `richards_super` | 1.014（+1.4%） | 高 | 上記に`super()`を使うmethod dispatchが加わる。zero-argument `super`、MRO lookup、bound method生成をguard付きでinlineする必要がある。 |
| `scimark_fft` | 0.961（−3.9%） | 高 | array/list上のFFT butterfly float loop、`sin`/`cos`。nested loopをOSRし、float unbox、bounds elimination、complex pairのscalar化を行う。 |
| `scimark_lu` | 1.001（+0.1%） | 高 | matrix list/arrayのLU分解、pivot探索、float loop。2次元添字guardをhoistし、row pointerとfloatをregisterに保持するmethod JITが必要。 |
| `scimark_monte_carlo` | 0.987（−1.3%） | 中〜高 | random number生成とfloat/int集計。loop JITに加えてRNG call/状態更新のC境界が大きく、RNG fast pathも必要。 |
| `scimark_sor` | 1.010（+1.0%） | 高 | 2次元gridのstencil float loop。row/list boundsを外へhoistし、隣接値load、float計算、storeを一つのnative loopにする。 |
| `scimark_sparse_mat_mult` | 1.013（+1.3%） | 高 | sparse index/value arrayを回るindirect float loop。int indexとfloatのunbox、bounds/version guard hoist、indirect load/store loweringが必要。 |
| `spectral_norm` | **0.484（−51.7%）** | 高・実績あり | tight range loopの整数indexと有理式、float divide/add。既存のbounded range kernel、係数簡約、隣接divide処理が大幅に効いた。method JITでは一般的なloop SSA、range elimination、int→float変換、丸め順序を保つvectorizationへ置き換える。 |
| `connected_components` | 1.016（+1.6%） | 高 | NetworkXのadjacency dict/set、DFS/BFS iterator、set update。Graph method/Python iteratorをinlineし、dict/set traversalとnode membershipをloweringする必要がある。 |
| `k_core` | 0.852（−14.8%）† | 高 | degree dict、bin sort、neighbor traversal、dict/set更新。method JIT候補は強いがmain標準偏差約9.6%なので改善量は未確定。container loopをnative化して再測定する。 |
| `shortest_path` | 1.018（+1.8%） | 高 | NetworkX BFS/Dijkstra系のdeque、adjacency dict、set、tuple反復とfunction dispatch。Graph APIを越えてloopをinlineし、deque/dict/set fast pathを持つ必要がある。 |

## 5. template、parser、framework、symbolic workload

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `chameleon` | 0.944（−5.6%） | 高 | templateから生成されたPython function、global/attribute lookup、escape/format call、Unicode join。生成methodを大きくcompileし、call/PICとstring builderを最適化する。 |
| `django_template` | 0.917（−8.3%） | 高 | Node render method、Context dict、variable resolution、filter call、string連結。method graph inline、dict/attribute PIC、短命SafeString/listのallocation削減が必要。 |
| `mako` | 0.974（−2.6%） | 高 | 生成Python render function、context lookup、多数のwrite call。render methodをinlineし、writer callをbuffer appendへfoldし、Unicode builderを改善する。 |
| `html5lib` | 0.904（−9.6%）† | 高 | Python tokenizer/parserの大きなstate machine、method dispatch、dict/list/string処理。method全体CFG、state dispatch simplification、attribute/PIC、container fast pathが適する。高分散なので再確認する。 |
| `docutils` | 0.998（−0.3%） | 中〜高 | reStructuredText parser、visitor method、regex、巨大object graph、Unicode生成。method JITはvisitor/parser callsに効くが、regex/string/allocationも同時に改善する必要がある。 |
| `dulwich_log` | 0.992（−0.8%） | 中〜高 | PythonでのGit object traversal/parseとzlib/hash C helper。method JITはobject method、dict/list、decode loopを速くし、decompression/hashはJIT外。 |
| `sphinx` | 1.000（−0.0%）† | 中〜高 | docutils、Jinja、extension dispatch、filesystem、regex、巨大object graphを含む総合app。単一fusionでは動かず、method inline/PIC/allocationを広く実装した後の受入試験にする。 |
| `sqlalchemy_declarative` | 1.004（+0.4%） | 中〜高 | ORM mapping、descriptor/instrumentation、unit-of-work、SQL constructionとSQLite C call。method inline/PICは効くが、DB/row/object allocationが残る。 |
| `sqlalchemy_imperative` | 0.883（−11.7%）† | 中〜高 | Core式構築、compiler visitor、parameter dict、SQLite。Python SQL expression/visitorのinline候補は強いがcandidate側標準偏差約11%なので再profileが必要。 |
| `sqlglot_v2_parse` | 0.999（−0.1%） | 高 | Python tokenizer/parser、token list、enum、recursive expression生成。method CFG、PIC、list bounds、short-lived Token/ASTのscalar replacementが必要。 |
| `sqlglot_v2_transpile` | 1.016（+1.6%） | 高 | parseに加えてAST generator visitorとstring builder。recursive method inline、node attribute PIC、Unicode buffer appendを最適化する。 |
| `sqlglot_v2_normalize` | 1.007（+0.7%） | 高 | AST walk/rewrite、identifier normalization、dict/set、recursive calls。node type PIC、tree method inline、short-lived replacement objectのescape analysisが必要。 |
| `sqlglot_v2_optimize` | 1.018（+1.8%） | 高 | 多数のoptimizer ruleとAST traversal、set/dict、copy/rewrite。rule call graphをmethod単位でcompileし、polymorphic node dispatchとallocationを減らす。 |
| `sympy_expand` | 0.966（−3.3%） | 中〜高 | expression DAGのrecursive dispatch、cache、hash、tuple、big-int/rational。method inline/PICは効くが、canonicalizationとnumber C kernels、allocationも支配する。 |
| `sympy_integrate` | 0.976（−2.4%） | 中〜高 | rule dispatch、recursive expression matching、assumption query。method graph inlineとdict/cache fast pathに加え、symbolic object/hash allocationを減らす。 |
| `sympy_str` | 0.992（−0.8%） | 高 | printer visitorの多数のsmall method、type dispatch、string join。method/PIC inlineとUnicode builderが主な候補。 |
| `sympy_sum` | 0.991（−0.9%） | 中〜高 | symbolic summation rule、polynomial/big-int/rational演算、expression construction。JITはdispatchを減らし、数値kernelとobject allocationはruntime側で改善する。 |
| `tomli_loads` | 0.947（−5.3%） | 高 | pure-Python TOMLのstring scan、branch、dict/list構築、number/date conversion。method CFG、character access、bounds、dict insertをloweringし、Unicode/object allocationを減らす。 |
| `xdsl_constant_fold` | 0.999（−0.1%）† | 高 | IR clone、visitor/pass method、SSA use-def object、dict/list/type dispatch。method inline/PIC/escape analysisの良い対象だが両側標準偏差約14%で、現比率は判断不能。 |

## 6. runtime serviceと標準ライブラリのPython glue

| result | 比率 | 優先度 | 支配する処理と必要な高速化 |
|---|---:|:---:|---|
| `many_optionals` | 0.993（−0.7%） | 高 | argparseで多数のoption actionを登録・解析し、dict/list/stringを操作する。`ArgumentParser`/Action method inline、option lookup、短命Namespace allocationの削減が必要。 |
| `subparsers` | 0.976（−2.5%） | 高 | argparseのsubparser選択、action dispatch、Namespace更新。method/PIC inlineとdict lookupを一つのparse CFGにまとめる。 |
| `coverage` | 0.991（−0.9%） | 低〜中 | tracing callbackを有効にした再帰Fibonacci。monitoring callbackとline eventが支配し、通常JITのhot pathとは異なる。JIT codeでの正確な監視と低費用event deliveryが必要。 |
| `create_gc_cycles` | 1.000（−0.0%） | 低 | cycle objectのallocation、refcount、GC世代listへの登録が中心。JITは作成loopだけで、allocator/GC tracking fast pathが必要。 |
| `gc_traversal` | 0.951（−4.9%） | 低 | `gc.collect()`がobject graphを`tp_traverse`しmark/sweepする時間が中心。JIT外のGC traversal、generation policy、cache localityを改善する。 |
| `deepcopy` | 0.977（−2.3%） | 中〜高 | `copy.deepcopy`のPython dispatch dict、memo dict、recursive call、list/dict/object allocation。method inline、type/PIC dispatch、memo fast pathとallocation削減が必要。 |
| `deepcopy_memo` | 0.993（−0.7%）‡ | 中 | memo hit経路のdict lookupとreference handling。loop数不一致なので比率は使わず、exact dict lookupとcall overheadを個別に測る。 |
| `deepcopy_reduce` | 0.945（−5.5%）‡ | 中〜高 | `__reduce__`、reconstructor call、state/list/dict復元とallocation。method inline/PICの候補だがloop数不一致のため改善量は未確定。 |
| `logging_silent` | 0.865（−13.5%） | 高 | disabled level check、`Logger.isEnabledFor`、effective level取得という短いmethod chain。method/PIC inlineとlevel/cache guardでcallを消せば大きく効く。現在の改善原因は専用counterで未確認。 |
| `logging_simple` | 0.976（−2.4%） | 中 | enabled loggingのLogRecord生成、stack/time取得、lock、handler、StringIO。method inlineは一部に効くが、record allocationとruntime serviceが中心。 |
| `logging_format` | 1.011（+1.1%） | 中 | 上記にFormatterの`%`/time/exception field処理が加わる。JITはmethod dispatchを減らし、string formatting/builderとLogRecord allocationは別に改善する。 |
| `pprint_pformat` | 0.996（−0.4%） | 高 | recursive pretty-printer、type dispatch、set/dict/list traversal、string piece生成。visitor method inline、container fast path、Unicode builderが必要。 |
| `pprint_safe_repr` | 0.993（−0.7%） | 高 | recursive `_safe_repr`、recursion memo、container iteration、repr call。method inline/PIC、dict/set/list iteration、temporary string削減が必要。 |
| `sqlite_synth` | 0.988（−1.2%） | 中 | SQLite VMからPython scalar/aggregate callbackへ出入りし、`math.cos`やstep/finalizeを呼ぶ。callback methodのJIT化に加え、SQLite↔Python変換/vectorcall境界を短縮する。 |
| `typing_runtime_protocols` | 1.023（+2.3%） | 低〜中 | runtime-checkable Protocolの`isinstance`、MRO/attribute introspection、typing cache。method JITよりtypeobject/typing側のcacheとattribute probe削減が主。 |
| `unpack_sequence` | 0.998（−0.3%）† | 中 | tuple/list unpackの特殊化bytecode、refcount、stack move。既にTier 1 fast pathがあるため、method JITではproducerとのfusionと短命tuple virtualizationが必要。 |

## 現在の最適化に成功したbenchmarkから得られる設計上の教訓

### `spectral_norm`

pyperformanceでは **0.4835**、約2.07倍になった。standaloneの固定入力では、range生成、indexの整数演算、係数計算、float divide/addを一つのbounded regionへまとめ、さらに隣接する除算を処理することで一段大きい改善も確認している。native profileでは最適化前の残り時間の約64%がdivide/add loopに集まっていた。これは「Python methodをcompileする」だけでは足りず、method内のloopをSSA化し、range iteratorを消し、intをunboxしたまま添字式を計算し、float演算へ接続する必要があることを示す。

専用range kernelをmethod JITへそのまま移植するのではなく、loop induction variable、overflow side exit、loop-invariant expression、float conversion、複数accumulatorを一般的なIRで表すべきである。float contractionはPythonの演算ごとのbinary64丸めを変え得るため、既存のcancellation回帰testとassembly検査も維持する。

### `hexiom`

pyperformanceでは **0.5794**、約1.73倍になった。実装済みの主な成功経路は、exact list内のcompact int membership、listを扱う短いcallee、`len`とsubscriptの接続、条件付きlist remove、`sum(1 if key in item else 0 for item in iterable)`のgenerator集約である。特にTier 1で早期specializeするsum集約は、実測で直前candidate比およそ0.753だった。

共通点は、Python source上では複数method、generator frame、builtin callに分断された一つのsolver loopだということにある。method JITではgenerator bodyと`sum` consumer、list iterator、membership predicateをinline IRへ展開し、loop fusionで同じ効果を得る必要がある。専用のHexiom形を増やし続けるより、escapeしないgenerator/iteratorのvirtualizationとexact-container loweringを先に実装する価値が高い。

### `raytrace`

pyperformanceでは **0.7296**、約1.37倍になった。native profileとPython call計測では、Point/Vectorの小method、frame clear/pop、managed-dict/object解放、float allocationが広く費用を占めていた。既存実装はfloat dot callの融合、同じexact heap typeのPython `__sub__` fast frame、単純constructorとcallee frameの省略を行い、専用counterで数十万回の適用を確認した。

method JITの本命は、`Ray`、`Point`、`Vector`のcall graphをmonomorphic type guardの下でinlineし、座標をunboxed float SSA値として保持することである。Point/Vectorが外へescapeしない区間ではobject本体、managed dict、各float objectの確保をscalar replacementで消せる。現在の局所call省略はこの設計が有効であることを小さく実証している。

### `go`

pyperformanceでは **0.7776**、約1.29倍となり、standaloneのmain比0.8目標も最終binaryで **0.7795** として達成した。成功した処理は、`Square.find()`の最大64 linkのroot traversalとpath compression、default引数を持つcallのframe省略、recorded typeからのmethod slot事前解決である。guardはinstance override、defaults変更、class method差替え、link上限を検査し、失敗時は通常callへ戻る。

method JITではunion-findだけの専用uopではなく、自己再帰またはloop化できる小methodをcallerへinlineし、同一layoutの`parent` fieldを直接load/storeする。list/setの周辺loopとroot探索を同じmethod CFGに置けば、現在残るTier 1 dispatchとframe操作も減らせる。

### `bpe_tokeniser`

pyperformanceでは **0.8013**、約1.25倍になった。既存profileではdict lookup、tuple/list allocation、GC、mallocが分散し、`max(stats, key=lambda x: stats[x])`のlambda callだけで1 workload当たり **1,815,343回**あった。実装済みのzip-list pair、bytes-pairのdict小整数更新、compact max-dict scanは、tuple/frame/dict subscriptの一部を直接処理する。max scan単体は直前candidate比約2.9%短縮し、全scan iterationを専用counterで確認した。

method JITではzip iterator、pair tuple、lambda frameをvirtualizeし、`Counter`/dictのlookup-updateと最大値探索をloop IRへinlineする。dictの挿入順、mutation version、exact key/value、例外、eval breakerをguard/side exitで保つ必要がある。BPEはcontainer最適化、escape analysis、builtin/lambda inlineを同時に評価できる代表benchmarkである。

### `deltablue` と standalone `btree`

`deltablue`はpyperformanceで **0.9462**に留まるが、固定standalone screenではbounded equality scanなどを含む版がmain比およそ0.76まで改善した実績がある。差は入力、warmup、適用coverageを分けて再profileすべきで、standalone比をpyperformance結果へ外挿しない。成功経路は、constraintの`execute`/`input`/`output`、方向判定、source/destination属性を一反復のbody proofとして最大64件処理するものだった。method JITではmonomorphic method群のinline、field offset、list iterator loopとして一般化できる。

`btree`は今回のpyperformance 119 resultには含まれないが、過去の六つのstandalone screenではmain比およそ0.56まで改善した。enumerate/list iterator、整数key比較、隣接subscript/tuple比較をまとめた結果である。これはmethod JITのcontainer loop、iterator virtualization、int unboxの設計資料として残すが、suite全体の幾何平均には数えない。

`chaos`、`comprehensions`、`django_template`、`html5lib`、`sqlalchemy_imperative`、`logging_silent`などにも5〜14%の改善が見える。ただしこれらには個別変換の成功counterと対応native profileがないか、測定分散が大きい。method JITによる一般化の候補ではあるが、「既存変換がこのPython経路を速くした」とはまだ断定しない。

## Method JITの実装順

第一段階は、`richards`、`raytrace`、`deltablue`、`go`、template三種を対象に、monomorphic Python method inlineと既知instance layoutの属性load/storeを実装する。function versionだけではnamespaceの正しさを保証できないため、callee globals identity、名前単位dependency、type version、descriptor/method slotをguardする。frameを作らない成功経路でもmonitoring、PEP 523、recursion、eval breaker、例外tracebackを保つ。

第二段階は、`nbody`、SciMark、`float`、`spectral_norm`、`crypto_pyaes`を対象に、methodとloopをまたぐint/float SSA、range elimination、bounds guard hoistを実装する。int overflowはboxed pathへside exitし、floatは演算順と丸めを守る。これで現在の一つの式専用regionを通常のnumeric Pythonへ広げる。

第三段階は、`bpe_tokeniser`、NetworkX、`hexiom`、`pyflate`、SQLGlotを対象に、exact list/dict/set iteratorと更新、tuple/iterator virtualization、短命objectのescape analysisを加える。container versionやmutationをguardし、iteration orderとcallbackの有無を証明できない場合は通常処理へ戻す。

第四段階は、async-tree、`async_generators`、`generators`、`coroutines`、pure-Python pickleを対象に、generator/coroutine frameを状態機械へloweringし、producer/consumerをfusionする。通常functionだけをmethod JIT化してもこの群は速くならないため、20%目標には独立の必須機能である。

各段階で、対象microbenchmarkだけでなく未対象cohortも同じ固定binaryで測る。最低限、次を採否条件にする。

- 専用counterまたはIR dumpで、意図したmethod、side trace、OSR entryが実際に使われたこと。
- `perf`でframe、dispatcher、lookup、allocationなど狙ったcost centerが減ったこと。
- main/candidateのbinary hash、tree hash、CPU、loop、warmup、environmentを固定し、開始順反転の対応測定で改善が再現すること。
- JIT対象外benchmarkの幾何平均を別に出し、code layout、allocator、page faultによる見かけの変化を区別すること。

## JIT以外で必要な作業

method JITだけで広いsuiteを20%短縮できない最大の理由は、実行時間の一部がPython bytecodeではないことである。次のcohortは別のprofileと実装計画を持つべきである。

| 領域 | 対象result | 主な作業 |
|---|---|---|
| startup/import | `python_startup*`, `2to3` | frozen/import cache、marshal、runtime初期化、relocation、allocator。JITのcompile閾値とcode cacheで短命processを悪化させない。 |
| C codec/serialization | base16/32/64/85、C版pickle、JSON | bulk loop、small/big bytes allocation、buffer growth、object construction。 |
| regex/XML | regex search群、ElementTree parse群 | `_sre` engine、Expat callback、tree/match allocation、Unicode処理。 |
| concurrency/I/O | TCP/SSL、Tornado、pool、async IO variants | selector、socket、OpenSSL、Task/Future/queue/lock、IPC、timer heap。 |
| memory management | GC、deepcopy、object-heavy apps | pymalloc、GC tracking/traversal、refcount batching、managed dict、Unicode/list/tuple allocation。JITのescape analysisもここへ接続する。 |
| numeric C runtime | `pidigits`, `mdp`, SymPy, `telco`, SQLite | big-int、Fraction/Decimal、hash/canonicalization、SQLite↔Python callbackとvalue conversion。 |

method JITの20%目標は、まず `richards`、template、SQLGlot、NetworkX、pure-Python pickle、`pyflate`、numeric Python、generator/asyncの **Python支配cohort** で判定する。その後all-suite幾何平均を評価し、C/I/O支配cohortの上限をAmdahl則で確認する。all-suiteだけを最初の採否指標にすると、JITが実行されないbenchmarkの重みでmethod JITの設計判断を誤る。

## 制約と次の検証

今回のA/B測定は全resultで各side 6 processだが、多くのresultにpyperfの「1%未満の差を95%確度で判定するにはsample不足」という警告がある。`html5lib`、`sqlalchemy_imperative`、`k_core`、`xdsl_constant_fold`などは分散が特に大きい。`deepcopy_memo`と`deepcopy_reduce`はloop数が一致しない。このため、小幅な比率をhot pathの証拠には使わない。

各driverを読んだ分類は「どこをprofileすべきか」を決めるためのものなので、method JIT prototype後は全Python支配resultでexecutor coverageとnative samplingを取り直す。C/I/O支配と判定したresultも、Python self timeが20%以上あると判明した場合は分類を更新する。raw JSONと現在のreportを固定し、同じrunnerで再比較する。

## 根拠の所在

- 比較条件、全比率、loop、標準偏差: `jit-artifacts/pyperformance-rerun-current/analysis.json`、`ratios.csv`、`compare.md`
- 119 resultのdriver source: `jit-artifacts/pyperformance-20260915/venv-candidate/lib/python3.16/site-packages/pyperformance/data-files/benchmarks/`
- 専用uopのbody proof、guard、counter、対応測定: `Tools/jit/optimization_report.md` と `plan.md` の section 15〜21
- Goのstandalone移植と実行条件: `benchmarks/go.py`、`benchmarks/standalone_benchmarks.md`
- Base16のJIT無効、反転順、分解測定、`perf stat`: `jit-artifacts/pyperformance-rerun-current/base16-diagnosis/summary.md`
- method frontendの範囲と公式目標: [PEP 836](https://peps.python.org/pep-0836/)
