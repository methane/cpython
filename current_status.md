# Experimental tracing GC: 引き継ぎ状況

更新日: 2026-09-08 UTC。ブランチ: `experimental-tracing-gc`。
今回の最適化の親コミットは `4fc52958937`。

## 最初に読むこと

辞書 watcher の修正と回帰テストは `901122c50b0` にコミット済み。
チェックポイントで失敗していた復活テストは解決し、Debug 全 173 tests と
native FT/JIT の対象テストに成功した。main との pyperformance 比較も完了した。
その後、typed object の mark 経路分離と initial full mark の header clear 省略を
追加した。詳細は下記の各節を参照。

性能・互換性の実験であり、ある程度の互換性破壊は許容されている。ただし、
クラッシュやリークを成功扱いしたり、テストを弱めて通したりしてはいけない。
必要なのは次の二構成であり、free threading と JIT の同時使用は不要。

| 構成 | 実行時設定 |
| --- | --- |
| Free threading + tracing GC | `PYTHON_GIL=0 PYTHON_TLBC=1 PYTHON_JIT=0` |
| JIT + tracing GC | `PYTHON_GIL=1 PYTHON_TLBC=0 PYTHON_JIT=1` |

LLVM 21 はインストール済み。実用的な速度・メモリ使用量という全体目標は未達。
日本語レポートはユーザーが保存済みとして削除を許可したため、復元しない。
英語の成果レポートは `experimental_tracing_gc.md` にある。

## 今回保存する主な変更

- **SETCLEANUP** (`Objects/setobject.c`): set 演算のエラー経路で捨てられる
  GC 未追跡の一時オブジェクトを、tracing モードでは追跡対象に戻す。
  参照カウント減算が回収しないために起きる未回収と子・型の寿命不整合への対処。
- **HEAPGATE V2** (`Objects/obmalloc.c`, `Include/internal/pycore_mimalloc.h`,
  `Python/gc_free_threading.c`): 累積割り当て量による自動 GC 要求を受けたら、
  world を止めて実際に残っている割り当て量を再確認する。既に解放した補助
  バッファの再利用だけで不要な全走査を起こすのを減らす。
  基準は `live + max(live, threshold * 4096) / 2`。スキップ時に live 基準を
  前進させず、手動 collect や dirty epoch の意味は維持する。
- **BUFFERFUSION** (`Python/gc_tracing.c.h`): 若いコンテナの専有バッファの
  分類を最初のヘッダー走査に統合。MEM/OBJECT ページのソート済み prefix を
  用い、ページ表の再配置・再ソートでキャッシュを消す。
  fallback では untyped ページのマークも全 GC 用に戻す。
- **HALFMARKS** (同ファイル): 非 leaf の一時マークを 32 bit から 16 bit に。
  ページ内 index のリンクと予約値が収まることを静的・実行時に検査する。
  leaf は従来どおり 1 byte。ポインタは短縮しない。全ヒープが半分になる
  わけではない。これが直近の採用済み性能最適化。
- 上記と不採用実験から得た回帰テスト、補助バッファ再利用などの独自
  ベンチマーク、configure 文書、英語レポートの追記。
- **DICTWATCH（解決済み）**: 辞書 subclass の finalizer、破棄 watcher、復活判定の
  順序を保つ二段階 root 再走査と、内容保持・再通知・unwatch 順序の回帰テスト。
- **TYPEDMARK** (`Python/gc_tracing.c.h`): `tp_traverse` が渡す正確な
  `PyObject *` では typed page 専用の mark 経路を使う。auxiliary allocation 用の
  young-buffer 判定と byte accounting を別関数へ分離し、conservative root と
  untyped allocation は従来の汎用経路で扱う。

元の tracing GC、NaN-boxing、即値整数、JIT 対応は先行コミット
`1b990379c85` に含まれる。設計の説明は英語レポートの前半を参照。

## 信頼できる直近の計測と限界

以下は **DICTWATCH より前の HALFMARKS** の独自ワークロードであり、
pyperformance の総合結果ではない。4 worker のコンテナ割り当て・回収負荷を、
独立した 7 process/configuration で再計測した中央値。
比較元は BUFFERFUSION、比較先は HALFMARKS。

| モード | 秒: 変更前 → 変更後 | Peak RSS MiB: 変更前 → 変更後 |
| --- | ---: | ---: |
| FT | 3.010239 → 2.957861 | 81.383 → 76.684 |
| JIT-enabled | 4.383792 → 4.327875 | 66.914 → 62.434 |

時間は約 1.7% / 1.3%、RSS は約 5.8% / 6.7% 改善。先行する 5 process の
計測でも同方向の改善があった。一方、FT の整数ループは別の 9 process 計測で
約 0.5% 遅く、範囲は重なり、計測中の GC はゼロ。原因は確定していない。
普遍的な高速化とは言わない。

同じ主ワークロードの RC FT は 0.425462 秒 / 16.125 MiB、通常の GIL 付き
RC JIT は 1.189588 秒 / 15.125 MiB。tracing は依然約 7.0 倍 / 3.6 倍の時間、
4–5 倍の peak RSS。RC JIT は古い保存ビルドであり、GC 単体の差を分離した
比較でもない。この倍率を Python 一般の性能差へ外挿しない。

計測は fresh process、構成を交互に実行、warmup を除外、hash seed 0、
default allocator。単一コアは CPU 2、4 P-core は CPU 0,2,4,6 に固定した。
ビルド・テスト・profile と計測を重ねていない。nursery は両方 ON:
`PYTHON_TRACING_GC_SOFT_DIRTY=1 PYTHON_TRACING_GC_YOUNG_CONTAINERS=1`。

HALFMARKS 時点の検証は Debug focus 291 件成功、NaN-boxing OFF Debug
291 件中 16 skip、native FT/JIT 各 807 件中 9 skip で成功。
反復テストは各 55 件成功。広めの stdlib テストは 2912 件で 32 failure、
69 skip。失敗名は比較元と一致したが、**全テスト成功ではない**。
これらを現在の DICTWATCH 修正案の検証結果として扱わない。

## 解決済み: 辞書 watcher による復活

### 確認できている不具合

tracing の `_PyObject_ResurrectEnd()` は collector の事前通知・root 再走査に
依存する。一方、辞書 watcher は root 再走査後の実際の `dict_dealloc()` で
通知されていた。破棄通知から辞書を Python の list に保存すると、解放済みの
辞書が残る。HALFMARKS Debug の ctypes 再現コードで SIGSEGV、GDB で
`PyType_IsSubtype(a=0xdddddddddddddddd, ...)` を確認した。
同じ再現コードは RC FT で 32 個の辞書を保持して終了した。
PRIVATEKEYS 実験が原因という証拠はなく、採用済み baseline に存在する不具合。

### 最終修正

チェックポイント案は `finalize_garbage()` 内で watcher を通知していたため、通常の
`subtype_dealloc()` と逆に辞書 subclass の `__del__` より先に通知していた。また、
二度目の通知がない失敗は、テストを実行した Python thread の終了済み data stack に
古いポインタ値が残り、conservative root として辞書を保持したことが原因だった。

最終実装は次の順序にした。

1. watched dict を full finalization path に含める。
2. 通常どおり finalizer を実行した後、world を止めて最初の root 再走査を行う。
   `__del__` が復活または unwatch した辞書はここで反映される。
3. まだ死んでいる watched dict がある場合だけ world を再開し、DEALLOCATED を通知。
4. 再び world を止めて root を走査し、watcher が公開した辞書を救出する。なお死んだ
   辞書だけ watcher bits を消し、実際の `dict_dealloc()` での二重通知を防ぐ。

回帰テストは、割り当て・参照解放を worker thread の終了境界に置いて偽の
conservative root を除き、辞書内容の保持と再利用、二度目の破棄通知、unwatch 後の
無通知に加えて、subclass の `__del__` による unwatch が通知より先に効くことを検査する。
DEALLOCATED で辞書自身を既存の C event list に保存する kind 3 helper は
チェックポイントの `Modules/_testcapi/watchers.c` にある。

### 検証結果

- Debug: `test.test_experimental_tracing_gc` は全 173 tests 成功（31.877 秒）。
- native FT: 新しい辞書 watcher 回帰テスト成功。
- native JIT: 同テストと `test_jit_stack_root` が成功。native JIT code の生成と
  `sys._jit.is_active()` の観測も検査済み。
- 元の ctypes UAF 再現コードは Debug/native FT の両方で 32 辞書を保持して正常終了。
- tracing を無効にした構成で `Python/gc_free_threading.o` のコンパイル成功。
- 各 full build は 116 modules checked、`_decimal` と `_tkinter` のみ optional
  missing、import failure 0。

広い既存 watcher suite は全成功ではない。tracing GC では即時 `del` 後の
dict/function/type watcher 通知を期待する既知の互換性 failure/error が残る。
今回の UAF と callback 順序の回帰テストは成功しているが、watcher 全般の互換性が
完成したという意味ではない。

## pyperformance: main との比較

main は `c8da735f4f05`、tracing は `901122c50b0` と同内容の測定用 worktree。
GCC `-O3`、PGO/LTO なし、CPU 2、hash seed 0、pyperformance 1.14.0 / pyperf
2.10.0、`--fast` で直列実行した。FT は両方 `--disable-gil` ビルドで
`PYTHON_GIL=0 PYTHON_TLBC=1 PYTHON_JIT=0`。JIT の main は通常 GIL ビルド、
tracing は free-threaded ビルドに GIL を戻し、両方 `PYTHON_JIT=1` とした。
main/tracing とも native JIT 実行を別テストで確認した。tracing の nursery 二設定は
有効。FT は 10 worker × 2 values、JIT は 3 worker × 6 values で、各 worker に
1 warmup、別に calibration run がある。

20 benchmark group を選び、複数結果を返す group を展開すると main は 28、
tracing は 26 サブベンチを計測できた。比率は各サブベンチの mean に対する
`tracing / main`、総合値は共通 26 件の比率の幾何平均。

| モード | 共通件数 | 幾何平均 | 遅い / 速い | tracing で未計測 |
| --- | ---: | ---: | ---: | --- |
| FT | 26 | **2.050x** | 24 / 2 | `create_gc_cycles`, `gc_traversal` |
| JIT | 26 | **2.559x** | 26 / 0 | 同上 |

FT の主な遅化は `pickle` 3.27x、`deepcopy` 3.14x、`deepcopy_reduce` 3.08x。
`float` は 0.936x、`nbody` は 0.915x と速かった。JIT は
`deepcopy_reduce` 4.18x、`deepcopy` 4.08x、`regex_compile` 3.97x、
`pickle` 3.52x、`pathlib` 3.43x で、全 26 件が遅かった。

`gc_collect` は回収数の下限、`gc_traversal` は回収数 0 を assertion する。
conservative tracing は stale root により対象 cycle を一時保持でき、同時に別の
garbage を回収できるため、両 benchmark は calibration 前に assertion failure となり
時間値がない。benchmark を書き換えて数値だけ得ることはしていない。

これは main と experimental branch の **end-to-end 構成比較**である。tracing 側は
GC に加えて NaN-boxing、即値整数、JIT 対応なども異なるため、個々の差や幾何平均を
tracing GC 単体のコストにはできない。`--fast` の結果には pyperf の安定性 warning
もある。raw JSON と compare CSV は `/tmp/pyperformance-gc-results.wgIXfy/` の
`{main,tracing}-{ft,jit}.json` と `compare-{ft,jit}.csv`。native JIT が動かなかった
最初の free-threaded main 試行は `main-jit-inactive.json` に隔離し、集計から除外した。

## 残る課題

1. 広い既存 watcher/stdlib suite の既知の tracing GC 互換性 failure を解消する。
2. `gc_collect` と `gc_traversal` に tracing GC の回収数 semantics を扱える upstream
   benchmark が用意できれば、GC 専用二項目も性能比較する。
3. 後続の原因分析で判明した full collection の頻度・範囲と nursery fallback を
   優先して改善し、時間と RSS の両方で検証する。
4. NaN-boxing と JIT 固有の残差は collector scheduling から分けて調査する。

pyperformance checkout は `/home/methane/work/python/pyperformance`。
以前利用した site-packages は
`/tmp/pyperformance-run/venv/cpython3.16-8707a636499f-compat-31b33d68c68a/lib/python3.16t/site-packages`。
runner の現行 help と依存関係を確認してから使用すること。

## DICTWATCH 後の最適化: typed mark 経路

pyperformance で差が大きかった `deepcopy` 三種、`pickle`、`regex_compile` を
同じ benchmark 実装・loop 数で呼び、watcher 修正済み native build と TYPEDMARK を
比較した。CPU 2、hash seed 0、通常 allocator、nursery 無効。測定 driver が存在しない
`PYTHON_GC_NURSERY=1` を設定していたことを後続調査で発見した。したがって、この比較は
full tracing GC の mark 経路比較として有効だが、nursery 有効時の結果ではない。
各値は独立 process、
比較順を交互にした 5 process/configuration の中央値。8 values の自動 GC 測定で、
collection 数は全比較で一致した。

| モード | workload 5件の経過時間比の幾何平均 | 主な改善 | 小さな悪化 |
| --- | ---: | --- | --- |
| FT | **0.9926x** | `deepcopy_memo` 0.9728x、`pickle` 0.9922x | `deepcopy` 1.0012x、`deepcopy_reduce` 1.0020x |
| JIT | **0.9944x** | `deepcopy` 0.9887x、`pickle` 0.9924x | `regex_compile` 1.0032x |

JIT `regex_compile` も collector の報告時間は 0.9914x。別の明示的 full-GC 測定では
FT 5/5 が 0.9556--0.9945x、JIT は三件が改善し、二件が 1.0019x / 1.0192x だった。
小差を一般化しないが、自動 GC の両モードで総合改善し、変更は hot mark path に
限定されるため採用した。Debug は全 173 tests 成功。native FT/JIT はそれぞれ
173 件中、比較元でも同様に失敗する `test_set_bulk_release` 一件だけが失敗し、
残り 172 件は成功。native JIT の active trace も確認した。

事前 profile では callback なしの `deepcopy` full collection で
`tracing_mark_address` が self samples の約 6.6%、`tracing_visit` が約 3.3%だった。
今回不採用にした案は、2 の累乗 stride の page index を magic multiply から shift
へ分岐する案と、nursery 失敗後の fixed backoff を 4 から 16 full collection へ
延長する案。前者は明示的 full-GC の JIT 5/5 で 0.5--1.6%悪化、後者は自動 GC の
回数を変えず、FT `deepcopy_reduce` が 1.034x、他はほぼ横ばいだったため撤回した。
active free cursor、条件付き ALIVE clear、snapshot と heap classification の融合も
速度または保守性の採用条件を満たさず撤回済み。

測定 driver は `/tmp/gc-typedmark-benchmark.py`、候補 build は
`/tmp/cpython-gc-powerstride-native.zYdBNv`（古い directory 名に注意）。profile は
`/tmp/gc-deepcopy-perf.data`、元 workload は `/tmp/gc-pyperf-profile.py`。

## 参照カウントとの差の原因分析

`2a7c7a505dc` と同じ source revision から、通常の参照カウント、NaN-boxing なしの
tracing GC、現在の NaN-boxing あり tracing GC を作り直した。FT は全て
`--disable-gil` の同じ object layout なので collector の差を最もよく分離する。
JIT の RC だけは通常 GIL build であり、JIT 結果には layout と optimizer 条件の差も
残る。`deepcopy` 三種、`pickle`、`regex_compile` の標準 loop body を 8 values 実行し、
各構成 5 fresh processes、CPU 2、hash seed 0、通常 allocator、順序交互の中央値を
使った。表の総合値は workload 5 件の比率の幾何平均、GC 比率と「差のうち GC」は
5 件の中央値である。

| モード | tracing 構成 | 経過時間 / RC | GC 時間を除いた比 | 総時間の GC 比率 | RC との差のうち GC | Peak RSS / RC |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| FT | NaN-boxing なし | **2.455x** | 1.178x | 55.2% | 88.4% | 1.803x |
| FT | NaN-boxing あり | **2.569x** | 1.300x | 52.9% | 81.3% | 1.806x |
| JIT | NaN-boxing なし | **2.924x** | 1.323x | 58.4% | 84.0% | 2.195x |
| JIT | NaN-boxing あり | **3.177x** | 1.556x | 52.1% | 73.3% | 2.152x |

主因は回収の scheduling と full-heap tracing である。RC は短命な acyclic object を
参照数 0 で直ちに破棄し、GC の allocation count も deallocation で減算するため、
5 workload の測定区間で cycle GC は全て 0 回だった。tracing は allocator で gross
allocation bytes を加算し、回収まで deallocation しない。同じ処理中に 24--92 回の
collection が起き、その大半が全 heap の snapshot、root mark、typed traversal、
dead-object 分類、clear/free を行った。GC の報告時間だけで RC との差の中央値
73--88%を説明する。

FT `deepcopy` の hardware counter では、RC に対し NaN-boxing なし tracing は
cycles 2.51x、instructions 1.63x、branch misses 5.85x、cache references 29.7x、
cache misses 62.0x、page faults 5.40x だった。IPC は 3.33 から 2.15 に低下した。
`perf` の self samples は `gc_collect_main_impl` 9.5%、snapshot 4.3%、address mark
4.2%、garbage deletion 3.9%、heap scan 3.5%、root mark 3.3%、typed traversal と
dict traversal がそれぞれ約 2.5%などに分散していた。単一の遅い関数ではなく、
全 heap を何度も読み書きする pipeline 全体が cache と分岐を増やしている。

正しい環境変数
`PYTHON_TRACING_GC_SOFT_DIRTY=1 PYTHON_TRACING_GC_YOUNG_CONTAINERS=1` でも
この workload 群は改善しなかった。nursery ON/OFF の経過時間比の幾何平均は、
NaN-boxing なしで FT 1.057x / JIT 1.107x、ありで FT 1.069x / JIT 1.093x と悪化した。
FT `deepcopy` の nursery ON は page faults が RC の 36.2x、tracing OFF の 6.70xに
なった。soft-dirty の page protection cost を払った後、対象外 object の圧力で
full GC に fallback するためである。

現在の container nursery が直接扱うのは exact `list`、exact `tuple`、watch されて
いない exact `dict` だけである。GC を止めて各 workload が新しく作った tracked
objects を概算すると、約 47--58%が対象外だった。`deepcopy` では frame、例外、
traceback、iterator、bound/builtin method、ユーザー instance、`pickle` では
`Pickler`、正規表現では method、generator、`SubPattern`、`Pattern` などが多い。
対象外の young body が full-GC budget の 1/8 を超えると、snapshot を途中で full 用に
切り替え、さらに 4 full collections の backoff に入る。instrumented `deepcopy` では
この limit を毎回わずかに超えて minor count 0 のまま fallback することを確認した。

GC を warmup 後に無効化し、1 value 分の garbage を意図的に保持させた補助測定では、
NaN-boxing なし tracing の経過時間 / RC は FT 1.465x、JIT 1.663x、Peak RSS は
3.93x / 4.68xだった。これは pure mutator cost ではなく、RC がその場で破棄・再利用
する storage を tracing が回収まで保持する影響を含む。自動 GC 測定で GC 時間を
差し引いた FT 1.178x と合わせると、二次要因は allocation accounting、遅延回収に
よる allocator/cache pressure、object representation と dispatch である。
NaN-boxing は中心原因ではないが、nursery OFF の同じ tracing 同士ではこの5件を
FT 1.046x、JIT 1.087x遅くした。

次の最適化は full collection 内の小さな関数を個別に削るだけでは不足する。優先順位は、
common builtin とユーザー object を含む young heap を実際に minor 回収できる型情報・
write barrier/dirty tracking、回収実績と RSS を使って gross allocation trigger を
調整する scheduling、full snapshot/mark/sweep の memory traffic 削減である。
soft-dirty nursery は fallback 時に余分な fault と snapshot costを加えるため、対象外
比率を早く判定して試行を避けるか、対象型を広げるまではこの workload の解にならない。

## 原因分析後の最適化: initial full mark の header clear を省略

full snapshot は従来、全 non-leaf object の `ALIVE` を一度消し、到達した object で
再び立て、GC heap の分類時にもう一度消していた。最初の root mark が始まる時点では
staged `UNREACHABLE` object が存在しないため、world を止めている間だけ
`UNREACHABLE` を到達マークとして使う。既存の GC heap 分類 visit がそのマークを
読み、通常の reachable/unreachable 状態へ変換する。finalizer 後の resurrection pass
は従来どおり `ALIVE` を消してから再走査する。leaf object は header ではなく既存の
snapshot map で判定する。このため initial snapshot の全 object header write/read pass
を一つ省ける。

最初の試作は `ob_gc_bits` の bit 7 を新しい一時マークに使い、`memoryview` が参照する
生きた `bytes` を誤回収して `PyBuffer_Release()` で crash した。GDB の watchpoint で
`tracing_delete_leaf()` からその `bytes` が解放されることを確認した。bit 7 は既に
`_Py_TRACING_GC_SHARED_BIT` として複数所有の sticky state に使われていたためであり、
この案は破棄した。最終案は空いている header bit を仮定しない。

比較元は TYPEDMARK `2a7c7a505dc`、比較先はこの変更、nursery OFF、CPU 2、hash seed 0、
通常 allocator。`deepcopy` 三種、`pickle`、`regex_compile` を各 5 fresh processes、
8 values、順序交互で測定した。比率は変更後 / 変更前の幾何平均。

| モード | 自動 GC の経過時間 | 自動 GC の報告時間 | Peak RSS |
| --- | ---: | ---: | ---: |
| FT | **0.9843x** | **0.9591x** | 1.0291x |
| JIT | **0.9777x** | **0.9574x** | 1.0022x |

FT RSS は `deepcopy` が終端で 1 collection 少なく、49.8 MiB から 57.5 MiB になった
影響であり、他4件は同等だった。回収回数を各5回に固定した明示的 full-GC 測定では、
収集時間は FT **0.9466x**、JIT **0.9446x**、RSS は 1.0001x / 0.9905xだった。
4 worker・16 batch・100万 container の stress では、FT の時間 0.9716x、GC 0.9692x、
RSS 0.9717x、JIT は時間 0.9799x、GC 0.9752x、RSS 0.9991xだった。したがって短い
`deepcopy` の RSS は一般的な memory regression とは判断しなかった。

Debug focus は 173/173 tests 成功。native FT/JIT はそれぞれ、比較元でも失敗する
`test_set_bulk_release` だけが失敗して 172/173。JIT enabled/active を確認した。
tracing なしと NaN-boxing なしの object file も compile 成功し、Debug/native full build
はいずれも 116 modules checked、import failure 0だった。

併せて full-GC threshold 2000 を 4000 にする案を測った。5 workload の時間は FT
0.9488x、JIT 0.9604xになったが、4 worker stress の RSS は FT 193.98 MiB から
222.10 MiB、JIT 60.53 MiB から 101.75 MiBへ増えた。時間と memory の交換に過ぎず、
参照カウントとの差の中心である遅延回収を悪化させるため不採用。

## 保存済みビルドと証拠

以下はこのマシンのローカルパスで、Git に含まれない。`/tmp` が消えると失われる。
現在のコードとテストはコミットに保存するが、古い実験のバイナリ・raw data は
これらの場所を参照する。古い checkpoint は追記形式なので、末尾の判断を優先。
DICTWATCH の古い checkpoint にある RUNNING 表記は、この文書の結果で更新される。

| 用途 | パス |
| --- | --- |
| 今回の DICTWATCH fixed native | `/tmp/cpython-gc-dictwatch-fixed-native.3PYuSt` |
| 今回の DICTWATCH fixed Debug | `/tmp/cpython-gc-dictwatch-fixed-debug.tR5Set` |
| TYPEDMARK native | `/tmp/cpython-gc-powerstride-native.zYdBNv` |
| TYPEDMARK Debug | `/tmp/cpython-gc-dictwatch-fixed-debug.tR5Set`（incremental rebuild） |
| initial mark 最適化 native | `/tmp/cpython-gc-typedmark-native.3qHu5p` |
| initial mark 最適化 Debug | `/tmp/cpython-gc-dictwatch-fixed-debug.tR5Set`（incremental rebuild） |
| 原因分析 RC FT | `/tmp/cpython-gc-analysis-rc_ft.tSSbDh` |
| 原因分析 RC JIT | `/tmp/cpython-gc-analysis-rc_jit.X9zado` |
| 原因分析 tracing、NaN-boxing なし | `/tmp/cpython-gc-analysis-trace_nonan.CTuKgS` |
| 原因分析 tracing、NaN-boxing あり | `/tmp/cpython-gc-typedmark-native.3qHu5p` |
| 今回の non-tracing compile check | `/tmp/cpython-gc-dictwatch-fixed-rc-check.uOhNKc` |
| main FT build | `/tmp/cpython-main-bench.uI5G5U/build` |
| main conventional-GIL JIT build | `/tmp/cpython-main-jit-bench.E55QXp` |
| pyperformance raw/compare | `/tmp/pyperformance-gc-results.wgIXfy` |
| HALFMARKS source | `/tmp/cpython-gc-halfmarks-src.8gZQaf` |
| HALFMARKS native | `/tmp/cpython-gc-halfmarks-native.EFIc6c` |
| HALFMARKS Debug | `/tmp/cpython-gc-halfmarks-debug.X3WeKi` |
| HALFMARKS NaN-boxing OFF Debug | `/tmp/cpython-gc-halfmarks-off-debug.XbtiEz` |
| DICTWATCH source | `/tmp/cpython-gc-dictwatch-src.AtPxCU` |
| DICTWATCH native | `/tmp/cpython-gc-dictwatch-native.NzLPvX` |
| DICTWATCH Debug | `/tmp/cpython-gc-dictwatch-debug.IjVrXA` |
| Helper-only baseline source | `/tmp/cpython-gc-dictwatch-baseline-src.iPhGKQ` |
| Helper-only baseline Debug | `/tmp/cpython-gc-dictwatch-baseline-debug.zQtsYM` |
| RC FT comparator | `/tmp/cpython-gc-heapgate-v2-rc-ft.5e6oia/python` |
| 古い RC JIT comparator | `/tmp/cpython-gc-local-rcjit.HKqqSW/python` |

native は GCC、`-O3`、PGO/LTO なし、LLVM 21。
DICTWATCH native の configure 引数:

```text
--disable-gil --without-ensurepip --with-experimental-gc=tracing
--with-experimental-nanboxing --enable-experimental-jit=yes-off CC=gcc
```

Debug は JIT 指定を `--enable-experimental-jit=interpreter` に変更し、
`--with-pydebug` を追加。out-of-tree のビルドディレクトリで作業し、
`make -C <build-dir> -j4 PYTHON_FOR_REGEN=python3` を使う。root で make しない。
通常の focus テストでは global nursery 設定を unset し、fixture に任せる。
例（今回実行した Debug suite）:

```sh
cd /tmp/cpython-gc-dictwatch-fixed-debug.tR5Set
env -u PYTHON_TRACING_GC_SOFT_DIRTY -u PYTHON_TRACING_GC_YOUNG_CONTAINERS \
  PYTHONMALLOC=debug PYTHON_GIL=0 PYTHON_TLBC=1 PYTHON_JIT=0 \
  ./python -m unittest test.test_experimental_tracing_gc
```

新テスト単独なら module 名の末尾に
`.ExperimentalTracingGCTests.test_dictionary_destruction_watcher_resurrection`
を付ける。native JIT 実行時は上の構成表の設定を使う。

主要な証拠ファイル:

- `/tmp/gc-dictwatch-handoff-{debug,ft,jit}-test1.log`: 今回の失敗ログ。
- `/tmp/gc-dictwatch-baseline-test1.log`: helper-only baseline の SIGSEGV。
- `/tmp/gc-dictwatch-{native,debug,baseline}-{configure1,build1}.log`: ビルド。
- `/tmp/gc-dictwatch-repro.py`, `/tmp/gc-dictwatch-baseline-repro1.log`,
  `/tmp/gc-dictwatch-rc-repro1.log`, `/tmp/gc-dictwatch-baseline-gdb2.log`:
  最初の UAF 証拠。`baseline-gdb1.log` は ptrace 拒否であり backtrace ではない。
- `/tmp/gc-halfmarks-{reclaim1,reclaim2,controls1,integer2,full1}.json`
  と同名 `.log`、`/tmp/gc-halfmarks-benchmark.py`: 採用済み最適化の計測。
- `/tmp/gc-typedmark-results.txt` と `/tmp/gc-typedmark-benchmark.py`:
  TYPEDMARK の自動 GC / 明示的 full-GC 比較。
- `/tmp/gc-rc-cause-results.json` と `/tmp/gc-rc-cause-results.log`:
  同一 revision の RC/tracing 原因分解。
- `/tmp/gc-no-gc-mutator-results.json`:
  GC 無効化による遅延回収 stress。純粋な mutator 比較ではない。
- `/tmp/gc-rc-cause-{rc-ft,trace-nonan-ft}-{stat.csv,report.txt}` と
  `/tmp/gc-rc-cause-trace-nonan-nursery-ft-stat.csv`:
  `deepcopy` の hardware counters と profile。nursery 構成は counter のみ。
- `/tmp/gc-nursery-diag.log` と `/tmp/gc-type-census.py`:
  nursery fallback と対象外型の診断。
- `/tmp/gc-tempmark-{final,explicit,stress}.log` と
  `/tmp/gc-tempmark-stress.json`: initial full mark 最適化の測定。
- `/tmp/gc-threshold-screen.json` と `/tmp/gc-threshold-stress.json`:
  不採用にした threshold 変更の時間・memory 測定。
- `/tmp/gc-{heapgate,bufferfusion,halfmarks,privatekeys,dictwatch,fullpurge}-progress.md`:
  詳細な実験記録。

## 不採用案を不用意に再投入しない

- **PRIVATEKEYS**: 専有 combined dict keys の解放で atomic RMW を省く試作。
  n=5 の中央値で FT 2.968715 → 2.995360 秒、JIT 4.414127 → 4.465339 秒。
  範囲は重なり、速度改善は示せず不採用。`Objects/dictobject.c` の試作は
  撤回済みで HALFMARKS と一致する。private/shared/frozendict の意味検証テスト
  だけ残した。証拠: `/tmp/gc-privatekeys-reclaim1.json` と `.log`。
- **FULLPURGE**: full GC で scheduled purge を完了させる試作。FT の RSS は
  減ったが時間は悪化。FT resurrection テストの 3 failure が未解明で、後続反復が
  通ったことを解決の証拠にしていない。runtime は撤回済み。
- bulk set release、header prefetch、root counts、sorted enumeration、page-map
  prefetch、scratch reuse、batch free publication、purge policy 変更にも不採用
  記録がある。新しい根拠なしに同じパラメータや code layout を調整し続けない。

変更時は root `AGENTS.md` と CPython の AI policy に従う。既存の変更・実験
snapshot・ログを消さない。性能測定はビルド・テスト・profile と重ねず、
複数 regrtest を使う場合はそれぞれ独立した一時ディレクトリを用意する。
