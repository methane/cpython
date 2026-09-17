# RichardsのJIT回帰の調査と修正

2026-09-17。`richards_super`の実行時間を修正前比28.0%短縮した。
mainとの差は49%から7.3%まで縮小したが、別の`btree`では6.0%の低下がある。
対象は `20c964a7486c7c668fac1bf38d0ab7250e3ad7c2` からの本コミットの変更。
mainは `d95f29589e03603aa13d8ca9d4f817dce77d357c`。

## 原因の切り分け

元のGILあり・PGO/full LTOありのpyperformance比較では、`richards_super`の
実行時間がmain比49.3%増加した。固定した実行ファイルを残し、変更していない
pyperformanceの実装を呼ぶ固定仕事量のdriverでも回帰を再現した。

- PGO/LTOなしでもmain約13.5ms、修正前約18.7ms。PGO固有の問題ではない。
- PGO/LTOあり・JIT無効の対照ではmain約29.8ms、修正前約28.7ms。
  この条件での大きな回帰はJIT経路にある。
- CPU 2で300回の同じ仕事量を`perf record`したところ、修正前は属性・型・
  `super()`検索のコストが増えていた。JITの匿名コードは関数別に分類できていない。
  Cヘルパーの比率だけで回帰全体を説明したとはしない。

生成されたuopを比較すると、mainは`Task.runTask`からサブクラスの`fn`へ
トレースを伸ばせるが、修正前の候補ではcallerのトレースがmethod入口で止まる。
method側はCFG全体をコンパイルする一方、mainのトレースで使われる
`super()`検索の定数化などを同じ範囲では実行できていなかった。

直接の問題は、methodをまたいでトレースしてよいかを**キャッシュ領域込みの
bytecodeサイズ**で判定していたこと。上限128に対して、実際の命令数は次の通り。
`COPY_FREE_VARS`の入口前処理と`EXTENDED_ARG`は命令数から除いている。

| 関数 | キャッシュ込みcode units | 実命令数 |
|---|---:|---:|
| `Task.runTask` | 130 | 36 |
| `DeviceTask.fn` | 159 | 55 |
| `HandlerTask.fn` | 297 | 96 |
| `IdleTask.fn` | 224 | 69 |
| `WorkTask.fn` | 240 | 82 |

`HandlerTask.fn`のmethod executorは観測した修正前のdumpにはないため、この表だけで
すべての関数が実際に境界になったとは判断しない。

境界による打ち切りと既存callerトレースの無効化を外す切り分け用の試作では、
約18.7msから約15.0msへ短縮した。判定方式が回帰の大きな部分に寄与している。
この試作そのものは最終修正として採用していない。

## 実装

methodのCFGをデコードした際の命令数から、callerのトレースを止める必要があるか
決める。上限は128命令。結果をexecutorに記録してからbytecodeへ挿入し、
`ENTER_EXECUTOR`と既存callerトレースの無効化で同じ判定を使う。
キャッシュ領域によって短いmethodが大きく見える問題を避ける。

CFGコンパイラ自身の再帰的インライン化予算は変更していない。長いmethodの途中だけを
トレースしてコンパイル済みの後半を使えなくするケースには、従来の境界を残す。
method自体も引き続きコンパイルする。ベンチマーク名やクラス名に依存する判定はない。

主な変更箇所は`Include/internal/pycore_optimizer.h`、`Python/optimizer.c`、
`Python/bytecodes.c`と生成済みの`Python/generated_cases.c.h`。

## 正しさの検証

`Lib/test/test_capi/test_opt.py`に属性キャッシュの大きな短いcalleeを追加した。
methodコンパイル前のcallerトレースが維持され、コンパイル後に新しく作るトレースも
calleeをインライン化すること、値の変更とTypeErrorを検証する。
このテストは修正前の実行ファイルでは、既存callerトレースが無効になるため失敗する。
既存の40回加算する長いcalleeの境界・無効化テストもそのまま成功する。

GIL native、GIL debug、free-threaded native、free-threaded debugの4構成で、
以下の1,346件が成功した。GIL構成は5件、FT構成は6件の想定されたskipを含む。
最終のGIL + PGO/LTO版でも同じ1,346件が成功し、Richardsの出力カウンタも確認した。

```
test_capi.test_opt test_monitoring test_sys_settrace
test_generators test_coroutines test_call
```

## 性能検証

GILあり、JITあり、GCC 13.3、`-O3`、PGO/full LTO、frame pointerあり。
Core i5-12450HのCPU 2に固定し、元のpyperformance 1.14.0 / pyperf 2.10.0の
ベンチマークを変更せず実行した。main・修正前・修正後の順序を3ブロックで回転し、
各条件4 worker、5 warmup、5測定値、8ループ。合計72 workerのGIL/JIT状態、
実行パス、CPU affinity、反復数を確認した。ビルド・テスト・profilerとは同時実行していない。

| ベンチマーク | main | 修正前 | 修正後 | 修正前比の時間短縮 | 修正後/main |
|---|---:|---:|---:|---:|---:|
| richards_super | 13.028ms | 19.399ms | 13.977ms | 28.0% | 1.0728 |
| richards | 11.672ms | 16.896ms | 12.225ms | 27.6% | 1.0474 |

msは全worker平均。時間比と短縮率は各ブロックの平均時間比の幾何平均から求めた。
修正後/修正前の95%区間は、`richards_super`が0.7044–0.7370、
`richards`が0.6677–0.7848。修正後/mainはそれぞれ1.0637–1.0820、
1.0372–1.0577。3個のブロック対数比のt区間であり、独立再ビルドや別CPUの
不確実性を含まない。

18結果中9結果にpyperfの安定性警告がある。修正前`richards`はworker平均の
変動係数が6.84%で、16.18–20.00msに散らばる。遅いworkerを除外していない。
`richards_super`の変動係数はmain 1.23%、修正前0.82%、修正後0.31%。
全18 JSONのSHAと72 workerの平均を生データから再計算し、集計との一致を確認した。

先行するPGO/LTOなしの2ブロックのscreenでも、`richards_super`は
18.85/19.00msから14.60/14.64ms、`richards`は16.75/16.76msから
12.83/12.82msへ短縮した。このdriverとpyperformance本体のmsは別の測定として扱う。

### 既存8本への影響

PGO/LTOなしで、凍結した修正前と修正後を2ブロックの逆順、3 warmup、5測定値で
比較した。全32プロセスの出力と実行ファイル・標準拡張・依存・workloadのSHAを確認した。
ここでの基準は**修正前のブランチ**であり、mainではない。

| ベンチマーク | 修正後/修正前 |
|---|---:|
| bpe_tokeniser | 1.0029 |
| btree | 1.0598 |
| deltablue | 0.9990 |
| go | 1.0022 |
| hexiom | 1.0014 |
| raytrace | 0.9996 |
| spectral_norm | 0.9988 |
| sqlalchemy_declarative | 0.9947 |

`btree`は両ブロックで低下した（1.0613 / 1.0582）。このトレードオフは未解消。
短いcalleeを通過できることでRichardsは改善するが、トレース化がmethodのCFG実行より
常に有利とは限らない。btreeの具体的なcallee・ループについては追加の分析が必要。
残り7本の点推定は0.6%以内だが、2ブロックで同等性を証明したとはしない。
pyperformance全体の再実行や全8本のmain比10%短縮の再認定は行っていない。

### 修正後のプロファイル

同じ固定仕事量driverで300回測定、10回warmupを実行し、同じ`cpu_core/cycles/u`、
sampling period 100003、frame-pointer call graphで再取得した。samples lostは0。
総cyclesは修正前11.424 billionから修正後9.058 billionへ20.7%減った。
`_PyType_LookupStackRefAndVersion`のself比率は4.47%→2.39%、
`_PyObject_TryGetInstanceAttribute`は2.49%→1.13%、
`_PySuper_Lookup`は2.21%→約0.01%。トレースをまたぐ既存の最適化が使えるように
なったという説明と一致する。これは上のpyperformance時間計測とは別の診断測定。

## 再現用の証拠

この調査の生データ、ビルドログ、ソース差分、実行ファイルのSHA、テストログは
[`jit-artifacts/richards-super-20260917/`](../jit-artifacts/richards-super-20260917/)に保存する。
元のpyperformance比較のソース・ビルド・結果は変更していない。

- `driver.py`、`initial-screen.json`、`jit-off.json`: 固定仕事量とJIT無効の対照。
- `main.data`、`before.data`、各`*-perf-flat.txt`: 同じ仕事量のnativeプロファイル。
- `*-uops.log`、`instruction-counts.json`: executorとbytecodeの構造。
- `boundary-screen.json`: 境界を外した切り分け用試作。
- `instruction-bound-screen.json`: 採用候補のPGO/LTOなしscreen。
- `build_pgo.py`、`after-source.diff`、`after-pgo-build.json`: PGO構成の再ビルド。
- `finish_pgo.py`: sandboxのローカルソケット制限で失敗した学習の復旧。
  失敗時のプロファイルとpycacheを分離し、標準43ファイル・10,468件の学習を
  JIT無効・seed 0・cold private pycacheで再実行した。成功した学習だけを使用。
- `compare_pgo.py`、`pgo-comparison.json`: Richards 2本の実行器・集計・実行物のSHA。
- `after.data`、`after-perf-all-symbols.txt`: 修正後の同じ固定仕事量のprofile。
- [既存8本の生データ・SHA・集計](../jit-artifacts/all-benchmarks-10pct-20260916/richards-instructions-screen-state.json)。

検証した修正後の実行ファイル:

- PGO/LTOなし: `build-method-jit/python-richards-instructions`
- PGO/full LTO: `jit-artifacts/richards-super-20260917/after-pgo-build/python`
  （SHA-256 `cf8599235cf221e63aa750218f6daf07a1d7a0ddb7f3dc3128dbaac1fa6ed6a1`）

固定バイナリ・CPUでの改善と、再ビルドや別CPUでも成立する保証は区別する。
残るmainとの差については、methodコンパイラの属性・`super()`の最適化範囲や
多態的な呼び出し時のexitを次に調べる必要がある。
