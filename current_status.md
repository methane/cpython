# Experimental tracing GC: 引き継ぎ状況

更新日: 2026-09-08 UTC。ブランチ: `experimental-tracing-gc`。
今回のチェックポイントの親コミットは `4ebd5dcf047`。

## 最初に読むこと

今回のコミットは、採用済みの最適化と、**テストがまだ失敗する辞書 watcher
修正案を含む作業途中のチェックポイント**である。完成版ではない。
直前の依頼は「pyperformance を使っていろいろなテストで RC と tracing GC を
比較すること」。その比較を開始する前に、コミットと引き継ぎ文書の作成を
依頼されたため、最新実装での広範な pyperformance 比較は未着手。

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
- **DICTWATCH（未完了）**: 下記の辞書破棄 watcher 修正案・C テスト helper・
  失敗する回帰テストを、そのまま保存する。

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

## 未完了: 辞書 watcher による復活

### 確認できている不具合

tracing の `_PyObject_ResurrectEnd()` は collector の事前通知・root 再走査に
依存する。一方、辞書 watcher は root 再走査後の実際の `dict_dealloc()` で
通知されていた。破棄通知から辞書を Python の list に保存すると、解放済みの
辞書が残る。HALFMARKS Debug の ctypes 再現コードで SIGSEGV、GDB で
`PyType_IsSubtype(a=0xdddddddddddddddd, ...)` を確認した。
同じ再現コードは RC FT で 32 個の辞書を保持して終了した。
PRIVATEKEYS 実験が原因という証拠はなく、採用済み baseline に存在する不具合。

### 保存した修正案

`Python/gc_free_threading.c` の三箇所を変更している。

1. watched dict を `needs_finalization` に含める。
2. `finalize_garbage()` で、内容を clear する前に DEALLOCATED を通知する。
3. root 再走査後も死んだままの辞書だけ watcher bits を消し、最後の復活判定後に
   callback が辞書を公開することを防ぐ。生き返った辞書の watcher は残す意図。

`Modules/_testcapi/watchers.c` は watcher kind 3 を追加した。DEALLOCATED で
既存の `g_dict_watch_events` に辞書自体を保存する。新しい C global はない。
`test_dictionary_destruction_watcher_resurrection` は cyclic dict/subclass の
内容保持、復活後の再利用、二度目の破棄通知、unwatch 後の挙動を検査する。

### 引き継ぎ時に実行した結果（重要）

native / Debug / helper-only baseline Debug のビルドは完了。
各 116 modules checked、`_decimal` と `_tkinter` が optional missing、
import failure は 0。baseline 側のビルド＋テスト job の終了コード 1 は、
ビルド失敗ではなく新しい回帰テストの失敗による。

- helper-only baseline: 新テストの subprocess が `-11` (SIGSEGV) で失敗。
- 修正案 native FT: 新テストは **失敗**。
- 修正案 native JIT-enabled: 同じ箇所で **失敗**。
- 修正案 Debug FT: `test.test_experimental_tracing_gc` 全 173 tests を実行し、
  172 成功・同じ新テスト 1 failure（31.863 秒）。これは上記 291 件の
  複数ファイル focus suite とは別の実行。

修正案の失敗は、二度目の破棄を期待する
`assert len(events) >= len(known) - 4, len(events)` で `events` が空になること。
その前の内容チェックまでは通るが、修正完了やリーク解消はまだ証明できない。
再通知されない原因は未調査。テストの到達性・保守的 root の保持と collector の
復活処理を調べ、仕様も確認すること。単に assertion を削除してはいけない。
早期通知と最後の watcher bits 消去による callback 順序の互換性も要レビュー。

引き継ぎ前にコードを追加修正していない。新修正案の OFF ビルド、RC helper の
検証、広い watcher/stdlib テスト、反復テスト、性能測定は未実施。
元の ctypes 再現コードも修正案ではまだ再実行していない。
この文書の作成時点で、今回起動・引き継いだビルドとテスト job は全て終了済み。

## 次に行うこと

1. DICTWATCH の失敗を調査し、修正案を検証する。上記の未検証範囲を埋める。
   現在のバイナリを検証済み版としてベンチマークしない。
2. ユーザー依頼の広範な **pyperformance** 比較を行う。
   RC FT 対 tracing FT、RC JIT 対 tracing JIT を分ける。可能なら同じ source
   revision と compiler/optimization 条件で RC comparator を新規作成する。
3. 数値、コンテナ、文字列、JSON、アプリケーション系など複数分野を選び、
   実行不能・失敗・skip を記録する。raw JSON、実行コマンド、環境、warmup、
   sample 数を保存する。独自 benchmark script を pyperformance の代用にしない。
4. FT/JIT/NaN-boxing/build layout も異なる end-to-end 比較と、GC だけを
   変えた比較を区別する。JIT enabled と native code 実行確認も区別する。
5. 英語レポートは現在 section 14 HALFMARKS まで。PRIVATEKEYS の不採用と
   DICTWATCH の最終結果、および pyperformance 結果を必要に応じて追記する。

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
cd /tmp/cpython-gc-dictwatch-debug.IjVrXA
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
