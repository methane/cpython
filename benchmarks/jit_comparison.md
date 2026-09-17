# JIT最適化と全8ベンチマークの比較

更新: 2026-09-17。

固定した実行ファイル・CPUで、全8本の実行時間比の95%区間上限が0.90以下になった。

目標は各項目のcandidate/main実行時間比≤0.90。項目間の幾何平均では判定しない。SQLAlchemyも100人・100住所・100回読み出しの負荷で含め、既存の8本の入力・処理・出力検証を変更していない。

## 結果

12ブロックの独立したプロセス比較。各ブロックでmain/candidateの順序を交互にし、各プロセスで3 warmup、7測定値。全サンプルのプロセス平均からブロック比を求め、項目ごとに幾何平均した。95%区間は12個の対数比のStudent t区間。遅い値を取り除かず、実行途中の結果で打ち切っていない。

| ベンチマーク | 実行時間比 | 時間短縮 | 95%区間 | 上限≤0.90 |
|---|---:|---:|---:|---|
| bpe_tokeniser | 0.8731 | 12.7% | 0.8693–0.8769 | yes |
| btree | 0.7917 | 20.8% | 0.7899–0.7936 | yes |
| deltablue | 0.8847 | 11.5% | 0.8825–0.8869 | yes |
| go | 0.8806 | 11.9% | 0.8742–0.8872 | yes |
| hexiom | 0.8377 | 16.2% | 0.8273–0.8483 | yes |
| raytrace | 0.8555 | 14.4% | 0.8503–0.8607 | yes |
| spectral_norm | 0.3919 | 60.8% | 0.3910–0.3928 | yes |
| sqlalchemy_declarative | 0.8920 | 10.8% | 0.8873–0.8968 | yes |

この区間は固定バイナリ・CPUでの実行時の揺れを表す。再ビルドや別CPUへの再現性、8項目同時の95%保証、Python全般での10%短縮を示すものではない。これらは最適化中に繰り返し調べた対象であり、未探索の評価用データではない。

## 比較条件と証拠

- main: d95f29589e03603aa13d8ca9d4f817dce77d357c。LLVM 21で必要なローカルラベル到達性のビルド修正のみ適用。
- candidate: 2fa7dae77b97d8ab5abf877f6895c3fef48b1869からのローカル変更（本コミットに収録）。計測時点では未コミット。
- Linux x86-64、CPU 2、LLVM 21/GCC、frame pointerあり、PGO/LTOなし、両側PYTHON_JIT=1。
- SQLAlchemy 1.4.19、greenlet 3.2.4の共通依存tree、両側SQLite 3.45.1。
- 実行ファイル・各ビルドの標準拡張・依存tree・8スクリプトのSHAを計測前後に照合。全プロセスで出力チェックサムと依存バージョンを確認。
- 計測中にビルド、テスト、profilerを並行実行していない。

main: `/home/methane/work/python/cpython-gc/jit-artifacts/method-perf-20260916/main-build/python`

SHA-256: `a245f5d91e4e5007af841be2296e55634aa8a29605b03af70fb3f772a6e7370b`

candidate: `/home/methane/work/python/cpython-gc/build-method-jit/python-goal-framebind`

SHA-256: `b434803ae2dc3ba8347d5eb7f9a39cdc9d9abea8574beeeb3767f68681a719ac`

[構成・実行順・環境記録](../jit-artifacts/all-benchmarks-10pct-20260916/framebind-confirm12-20260917-state.json)、[区間とブロック範囲](../jit-artifacts/all-benchmarks-10pct-20260916/framebind-confirm12-20260917-confirmation.md)、[生データと検証ログの案内](../jit-artifacts/all-benchmarks-10pct-20260916/README.md)、[ソースSHA](../jit-artifacts/all-benchmarks-10pct-20260916/framebind-source-manifest.json)。追加ヘッダーを含むcandidateソースは本コミットに収録し、上記の基点との差分をGitで確認できる。

## 主な実装

method JITの制御フロー・呼び出し処理に加え、整数領域、整数ビット演算、浮動小数点式、len・比較・添字アクセス、属性アクセスと更新、global依存関係、組み込みメソッドと反復処理を改善した。個々の変更の経緯、失敗例、採用しなかった実験は[plan.md](../plan.md)に残している。

SQLAlchemy追加後は、インライン辞書と非data descriptorを持つ属性の読み書き、安全に破棄できる値の更新、ガードの再利用、空dict/set作成を拡張した。属性型や辞書、descriptorが変わる場合、finalizerが呼ばれる場合はガードから通常実行へ戻る。

最後の変更はCからPythonへの呼び出しコストを減らす。コンパイル済みの単純な引数・定数・属性・属性内のtuple/list要素の返却は、ガードのもとでフレームを省く。それ以外のコンパイル済み関数でも、位置引数が完全一致する場合は実フレームを保ちながら一時引数配列と汎用binderを省く。クロージャ、監視、再帰、例外は通常の実行入口を使う。これらのC呼び出し短縮はGILあり・DTraceなしの構成に限定している。

SQLAlchemyのBaseRow._get_by_int_implでは、GDBのentry/finish breakpointで500回の実際の高速経路returnを確認した。これは利用確認であり、時間短縮率の因果分解ではない。

## 正しさの検証

GIL debug/native、free-threaded debug/nativeの各構成で、JIT・monitoring・tracing・generator・coroutine・callの1,352件と、dict・watcher・GC・descriptor・setの1,075件が成功。想定されたskip/expected failureを含む。生成器102件も成功し、後続変更はCとテストのみ。free-threaded構成の正しさを検証したが、この性能表はGILありの比較である。

今回追加した回帰テストには、callbackによる辞書置換、descriptor変更、例外の元フレーム、引数と戻り値の寿命、local monitoring、9個以上の引数、closure cellの変更、再帰上限、使用中のexecutorがcold回収されないことと未使用executorの回収を含む。

GitHub投稿、push、PR変更は行っていない。

## 再実行

リポジトリのルートから実行する。`--tag` は未使用の名前を選ぶ。

```sh
python3 jit-artifacts/all-benchmarks-10pct-20260916/run_suite.py \
  --candidate build-method-jit/python-goal-framebind \
  --tag framebind-local-repeat --blocks 12
python3 jit-artifacts/all-benchmarks-10pct-20260916/confirm_comparison.py framebind-local-repeat
```

このコマンドは既存のローカルビルドと共有依存treeを使う。別のcheckoutではそれらの準備が必要で、実行ファイルと依存パッケージはコミットに含めていない。runnerは共有依存treeの参照先、CPU affinity、JIT環境変数、タイムアウト、SHA照合を設定する。計測中は他のビルド・テスト・profilerを止める。
