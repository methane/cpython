# Experimental tracing GC: 引き継ぎ状況

更新日: 2026-09-08 UTC。ブランチ: `experimental-tracing-gc`。
今回のチェックポイントの親コミットは `4ebd5dcf047`。

## 最初に読むこと

現在の作業ツリーはチェックポイント `aa8e0f7f82f` の上に、辞書 watcher の
修正と回帰テストを含む。チェックポイントで失敗していた
辞書 watcher の復活テストは解決し、Debug 全 173 tests と native FT/JIT の
対象テストに成功した。main との pyperformance 比較も完了した。詳細は下記の
「解決済み: 辞書 watcher」と「pyperformance: main との比較」を参照。

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

main は `c8da735f4f05`、tracing は `aa8e0f7f82f` と現在の runtime/test 差分。
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
3. 同一 source revision で collector だけを切り替えた比較を追加し、今回の
   end-to-end 差から GC 単体の寄与を分離する。
4. 幾何平均 2.0--2.6x と大きい差を、allocation、root scan、sweep、branch 固有の
   object representation/JIT 差に分解する。

pyperformance checkout は `/home/methane/work/python/pyperformance`。
以前利用した site-packages は
`/tmp/pyperformance-run/venv/cpython3.16-8707a636499f-compat-31b33d68c68a/lib/python3.16t/site-packages`。
runner の現行 help と依存関係を確認してから使用すること。

## 保存済みビルドと証拠

以下はこのマシンのローカルパスで、Git に含まれない。`/tmp` が消えると失われる。
現在のコードとテストはコミットに保存するが、古い実験のバイナリ・raw data は
これらの場所を参照する。古い checkpoint は追記形式なので、末尾の判断を優先。
DICTWATCH の古い checkpoint にある RUNNING 表記は、この文書の結果で更新される。

| 用途 | パス |
| --- | --- |
| 今回の DICTWATCH fixed native | `/tmp/cpython-gc-dictwatch-fixed-native.3PYuSt` |
| 今回の DICTWATCH fixed Debug | `/tmp/cpython-gc-dictwatch-fixed-debug.tR5Set` |
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
