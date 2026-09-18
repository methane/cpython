# JIT版のpyperformance比較

## 4種類の既存ビルドをまとめて比較する場合

最新のmethod-jitを含むGILなし2種類とGIL/PGO/full LTOあり2種類の実行には
[`run_pyperformance_four_way.sh`](run_pyperformance_four_way.sh) を使う。
手順・使用バイナリ・SQLAlchemyのgreenlet省略については
[`pyperformance_four_way.md`](pyperformance_four_way.md) を参照。

## GILあり・PGO/full LTOあり

今回の設定用の入口は `run_pyperformance_gil_pgo_lto.sh`。
通常のGILビルドを使い、main・candidateともJITを有効にする。

```sh
./benchmarks/run_pyperformance_gil_pgo_lto.sh --prepare-only \
  jit-artifacts/pyperformance-gil-pgo-lto-20260917

./benchmarks/run_pyperformance_gil_pgo_lto.sh --run-only \
  jit-artifacts/pyperformance-gil-pgo-lto-20260917
```

configureは `--enable-gil --enable-experimental-jit=yes --enable-optimizations
--with-lto=full --without-pydebug`。GCC、`-O3`、frame pointerあり。
PGOとLTOの実効フラグ、および実際のworkerのGIL/JIT状態を検証する。
GCCのfull LTOを使い、LLVM 21はJITの生成に使う。

PGOは両側で標準の `-m test --pgo --timeout=1200 --randseed=0` を実行し、
学習時はJITを無効化する。`-B` と各ビルド専用の空のpycache prefixにより、
既存の `.pyc` を読まない条件にそろえる。学習ログと `*-pgo.json` に
学習コマンド・テストソースSHA・生成したGCCプロファイルのSHAを保存する。
学習用バイナリのビルド時に生成されたプロファイルや失敗した学習のプロファイルは
別ディレクトリに保存し、成功した学習へ混ぜない。
各側を独立に学習した固定バイナリ1本ずつの比較であり、PGO学習や再ビルドの
ばらつきを評価する実験ではない。

計測条件は下記のFT版と共通で、実行環境のみ `PYTHON_GIL=1` に変更する。
依存wheelは今回のGIL ABIで準備し、FT版のnative拡張は流用しない。
外部拡張は共通のframe pointer付きフラグでビルドし、同じwheelを両側に導入する。
外部依存自体へのPGO学習は行わない。

前回のstartup集計不備を修正し、`bench_command` の実行ファイルも検証する。
ただし、この場合のhookが検査するのはコマンド計測用Pythonであり、
起動される各子Pythonの内部状態まで直接観測してはいない。
2to3の同梱lib2to3と、旧依存のdistutils互換用setuptoolsを計測前に導入する。
lib2to3の文法キャッシュも事前生成し、計測時の依存ファイル変更を避ける。
Python 3.16に未対応の依存は失敗として残し、暗黙に別バージョンへ置き換えない。

## Free-threaded・PGO/LTOなし

`run_pyperformance_compare.sh` はローカルの `main` と `HEAD` のコミットを固定し、
別々のソース・ビルドディレクトリで比較する。作業中の未コミット変更はビルドに含めない。
checkout、fetch、push、コミット、CPUのシステム設定変更は行わない。

```sh
# 準備だけ: Python 2本のビルドと依存パッケージの準備。ネットワーク接続が必要。
./benchmarks/run_pyperformance_compare.sh --prepare-only jit-artifacts/pyperformance-ft-new

# 実際の計測。準備済みファイルを使い、ビルドやpip installを行わない。
./benchmarks/run_pyperformance_compare.sh --run-only jit-artifacts/pyperformance-ft-new
```

オプションなしなら準備から計測まで続ける。新しいコミット・設定でやり直す場合は、
新しい出力ディレクトリを指定する。既存ディレクトリでは最初のコミットを保持する。
途中終了後は同じコマンドで再開できるが、記録済みの失敗を成功するまで再試行しない。
ログに残る未記録のpartial JSONがあれば上書きせず停止する。

## 比較条件

- 両側とも `--disable-gil --enable-experimental-jit=yes --disable-optimizations
  --without-lto --without-pydebug`、GCC、`-O3`、frame pointerあり。
  `--disable-optimizations` はCPythonのPGOビルドを無効化するオプション。
  通常のコンパイラ最適化は `-O3` で有効。LLVM 21は `/usr/bin` のversion付きツールを検出する。
  JIT生成には、このPCで子プロセス回収を確認済みの `/usr/bin/python3.12` を使う。
- mainには、LLVM 21の生成コードに必要なローカルラベル到達性修正のみを適用する。
  [パッチ](../Tools/benchmarks/main-llvm21.patch)と適用ログを出力先へ保存する。
  新しいmainでこのパッチが不要・適用不能になった場合は準備で停止する。
- 両側とも `PYTHON_GIL=0 PYTHON_JIT=1 PYTHONHASHSEED=0`。
  pyperf hookが実際の測定workerの実行前後でfree-threaded・GIL無効・JIT有効を確認し、
  JSONへ記録する。GIL非対応の外部拡張を含む項目は失敗・クラッシュする可能性がある。
  GILを有効化して結果に混ぜることはしない。
- pyperformance 1.14.0、pyperf 2.10.0を固定し、`all` の全specificationを選ぶ。
  Pythonバージョン制約による対象外と依存ビルド失敗は個別に記録する。
  実行スクリプト・入力データはpyperformanceに同梱されたものを変更せず使う。
- requirementsごとに依存を隔離し、両側に同じwheelを導入する。
  純Pythonのwheelは利用し、native拡張のwheelはソースから作成する。
  外部native拡張はmainのFT ABIとframe pointer付きフラグでビルドする。
  これは固定した外部依存を使ったcore比較であり、candidateのヘッダーで外部拡張を
  再コンパイルした比較ではない。標準拡張は各側のソースからビルドする。
- 2ブロック。各項目のmain/candidate順序を交互にし、第2ブロックで逆転させる。
  各側6 worker、5 warmup、5 values、最小測定時間0.1秒。
  ループ数は独立に自動校正し、pyperfの1 operationあたりの値を比較する。
- 単一スレッドの項目はCPU 2。並列・thread/process利用項目は実行プロセスに許可された
  CPU全体を両側共通で使う。`--cpu` と `--parallel-cpus` で変更できる。
  計測中は別のビルド・テスト・profilerを止める。
- worker timeoutは60秒、NetworkXは15秒。specification全体にも600秒、
  NetworkXは180秒の上限を設け、超過時は子プロセスも終了する。
  依存準備の上限はrequirementsごと600秒。

例（設定は再開時も同じものを指定する）:

```sh
./benchmarks/run_pyperformance_compare.sh --run-only \
  --cpu 2 --parallel-cpus 2,4,6,8,9,10,11 \
  jit-artifacts/pyperformance-ft-new
```

## 出力

- `build-plan.json`、`*-build/build-complete.json`: 固定コミット、フラグ、実行物の情報。
- `suite.json`: 全対象とPython制約による対象外、依存構成、準備失敗。
- `identities.json`: 実行ファイル・標準拡張・stdlib・依存・workload・runnerのSHA。
  計測前後に照合し、不一致なら比較を成功扱いにしない。
- `results/*.json`、`results/*.log`、`state.json`: 全試行、生データ、実行順、コマンド、失敗。
- `compare.md`: 各項目の比、ブロック間の差、失敗一覧。
  `main.json` / `candidate.json` は両側・全ブロックで完了した項目のpyperf形式の集計。
- `check-main.log` / `check-candidate.log`: pyperfによる測定の安定性チェック。

複数のresultを出すspecificationがあるため、対象数と結果の行数は異なる。
集計はworker平均を等重みで平均し、各項目のブロック比を幾何平均する。
失敗した項目を無視して「全体が成功」とは表示せず、終了コード1と失敗一覧を残す。
完了した項目の集計は保存される。再集計だけなら `--report-only` を使う。

この比較の反復は同じバイナリを使う。別ビルド・別CPUへの再現性を示すものではない。
以前のGILありの単体ベンチマーク8本の結果とは分けて評価する。

2026-09-17の準備済み環境では97 specification中94件が実行可能。
FastAPIは `pydantic-core` / PyO3のPythonバージョン制約、SQLAlchemyの2件は
`greenlet` のビルド失敗で未準備。
[準備・検証記録](../jit-artifacts/pyperformance-ft-20260917/preparation.md)に詳細を残した。
このFT比較は計測・解析済みで、[結果](../jit-artifacts/pyperformance-ft-20260917/summary.md)
を保存している。旧runnerのソースは同じ出力先の `frozen-runner/` に保存した。
runnerと依存準備が変わったため、新しい実験は新しい出力先を使う。
