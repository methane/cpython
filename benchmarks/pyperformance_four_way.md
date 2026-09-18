# 既存の4ビルドでpyperformanceを比較する

リポジトリのルートから実行する。

```bash
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-fixed --run-only
```

準備済みの環境を使う場合は `--run-only` を付けてもよい。同じコマンドの再実行は
記録済みの測定を飛ばす。失敗した測定も保存し、自動再試行しない。
バイナリ、依存、測定条件を変えた場合は新しい出力ディレクトリを指定する。

| 構成 | ブランチ | 使用する実行ファイル |
|---|---|---|
| GILなし、PGO/LTOなし | main | `jit-artifacts/pyperformance-ft-20260917/main-build/python` |
| GILなし、PGO/LTOなし | method-jit | `build-method-ft-jit/python` |
| GILあり、PGO/full LTOあり | main | `jit-artifacts/pyperformance-gil-pgo-lto-20260917/main-build/python` |
| GILあり、PGO/full LTOあり | method-jit | `jit-artifacts/pyperformance-fixes-20260917/committed-final-pgo-build/python` |

全4構成で `PYTHON_JIT=1` を指定する。ただし、このmainのFTビルドは
`_PyOptimizer_Optimize()` が常に0を返すため、JITの有効フラグが立っても
executorを生成しない。FTの比較は実質的にmainのインタプリタ対method JITである。
全ビルドは `-O3`、frame pointerあり、非debug。
mainは `d95f29589e0` にLLVM 21のビルド互換パッチを適用したもの。
method-jitは今回コミットした失敗・リグレッション修正（採用版V26）を含む。
正確なcommitとソースのSHA-256は `jit-artifacts/pyperformance-fixes-20260917/` の
`committed-final-{ft,pgo}-build.json` に保存する。未コミット差分が空でもソースの
同一性を検証できるよう、両構成のruntime・標準ライブラリ・ビルド入力を照合する。
FT・PGO双方のビルド記録で元ソースが一致することと、実行ファイル・標準拡張・
構成ファイルのSHA-256を確認する。最終ビルド記録が未作成の場合は準備を拒否する。
各実行ファイルのSHA-256と実効設定、両ビルドの元ソース情報を `preparation.json`
に保存する。今回のスクリプトはPythonの再ビルド、PGO再学習、ダウンロードを行わない。

両構成の依存環境を準備してから、FT、GIL/PGO/LTOの順に測定する。
構成ごとにmainとmethod-jitをベンチマーク単位で隣接させ、2ブロック目では順序を反転する。
FT側でベンチマークが失敗してもGIL側まで続行する。準備・同一性検証が失敗した場合は
測定を始めず終了する。GIL対FT自体の測定順は交互でないため、小差の直接比較には使わない。

既定値は2ブロック、各6 worker、5 warmup、5 value、最小測定時間0.1秒。
各workerがループ回数を校正し、pyperfが1回あたりの時間に正規化する。
単一CPUのベンチマークはCPU 2、並列ベンチマークは許可されたCPU集合を使う。
`--cpu` と `--parallel-cpus` で変更できる。測定中の再ビルドや他の重い処理は避ける。
workerのタイムアウトは通常60秒、networkxは15秒。
1 specification・1構成・1ブロックの上限は通常600秒、networkxは180秒で、
超過したプロセスと子プロセスを終了して次へ進む。

pyperformance 1.14.0、pyperf 2.10.0の既存キャッシュを使う。
4構成で同じベンチマークスクリプトとpure Python wheelを使用し、native wheelは
GIL/FTそれぞれのmain向けに準備済みのものを、その構成のmain/method-jitで共用する。
従来のFT実験で欠けていた `setuptools` とvendored `lib2to3` も用意する。
過去の測定環境には書き込まず、今回用のvenvを作る。

`sqlalchemy_declarative` と `sqlalchemy_imperative` はユーザー指定により
`greenlet==3.2.4` を省略し、キャッシュ済みの `SQLAlchemy==1.4.19` を
`pip --no-deps` でインストールする。同期SQLite処理のスクリプトと入力は変更しない。
greenletの不在、SQLAlchemyのバージョン、C拡張のimportを準備時に確認し、
依存定義からの変更を `preparation.json` / `suite.json` に明記する。
これはupstreamの依存定義をそのままインストールした環境ではない。
FastAPIはキャッシュ作成時の `pydantic-core` / PyO3のビルド失敗を未対応として残す。

失敗の調査後、新規環境には以下の互換パッチを適用する。既存のキャッシュ・結果は
変更しないため、以前の測定ディレクトリをこの版のハーネスで再開することはできない。
新しい出力先を指定する。変更前後のSHA-256を `preparation.json` に保存する。

- cloudpickle: Python 3.16で削除された `DELETE_GLOBAL` を任意のopcodeとして扱う。
- Genshi: 必須フィールドをASTのコンストラクタに渡す。
- WebSocket: OSが割り当てるIPv4 loopbackの空きポートを使う。データ量・通信回数は同じ。

FTのJITは複数スレッドが存在する間、Tier 1へfallbackする現在の制約がある。
並列処理、Tornado、WebSocketに限り、この状態を測定エラーにせず、開始・終了時の
実際のJIT状態と停止の観測をJSONへ記録する。レポートにも該当項目を列挙する。
常時JIT有効や並列JIT対応を意味しない。その他の項目の予期しない停止と、GILあり
ビルドのJIT停止は引き続きエラーになる。

出力先の `compare.md` から、以下の構成別レポートへ進める。

- `ft/compare.md`: GILなしのmethod-jit/main比較。
- `gil-pgo-lto/compare.md`: GIL/PGO/full LTOありのmethod-jit/main比較。
- 各構成の `results/`: 生のJSONとログ。
- 各構成の `state.json`: 実行条件、順序、成否、時間、結果SHA。
- 各構成の `identities.json`: バイナリ、標準拡張、標準ライブラリ、依存、workload、runnerの同一性。
- 各構成の `main.json` / `candidate.json`: 両側で全ブロック成功した項目の集約。

終了コード0は全選択項目の成功、1は失敗・未対応項目あり。未対応のFastAPIを含む
既定の `all` では1になるが、他の結果は保存される。致命的な準備エラーは2。
集計は各workerの平均を等重みで扱い、ブロックごとのcandidate/main時間比を幾何平均する。
未完了項目を含めたsuite全体の性能とは扱わない。

```bash
# 準備だけ（測定なし）
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-fixed --prepare-only

# 保存済みの結果からレポートを再生成
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-current --report-only
```

短い動作確認を行う場合は別の出力先を使う。

```bash
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-smoke-new \
  --benchmarks richards_super,python_startup,2to3,sqlalchemy_declarative,sqlalchemy_imperative \
  --blocks 1 --processes 1 --values 1 --warmups 1
```

短い確認の測定値は性能評価に使わない。
