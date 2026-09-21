# sympy_expandのリグレッション調査

2026-09-21。main `d95f29589e0`（LLVM 21ビルド対応のみ追加）と
method JIT `e3fb6e8edee`、および今回の未コミット差分を比較する。
対象はGILあり、O3、PGO、full LTO、JIT有効。開発時はPGO/LTOなしを使用した。
この調査で変更したランタイムコードは `Python/optimizer.c` の再試行判定だけである。

## 原因と変更

元の全体測定では `sympy_expand` のmethod JIT/main実行時間比は1.1448。
前回の別ビルドでも1.1480で、安定して残っていたリグレッションである。

固定回数の展開を行う診断用ドライバでは、JIT無効時のcurrent/main比は
0.9956、有効時は1.0827だった。import、warmup、実行経路がpyperformanceと
異なるので、後者を元の1.1448の代わりには使わない。JIT経路に原因を絞る
補助証拠である。元のPGO版のCPUプロファイルでは、candidateの
`method_merge_block` がcyclesの3.75%を占めた。

大きな `Mul.flatten` はpartial methodとしてコンパイルされるが、頻繁に
Tier 1へ戻ってexecutorが退役する。再試行を遅らせるfingerprintに
inline cacheの型・関数バージョンが含まれていたため、多態的な呼び出しで
キャッシュが変化すると待機期間が解除された。結果として、役立つnative
領域が増えないままコンパイル・退役を繰り返していた。

変更後は特殊化opcodeとoperandを比較し、inline cacheの内容は比較しない。
opcodeが変わった場合は早期再試行を続ける。同じopcodeのままcalleeや型が
変わった場合にも、既存の定期的な再試行で再評価する。このfingerprintは
コンパイルを延期するためだけに使い、native codeの有効性確認には使わない。
実行結果、属性変更の可視性、executor無効化の仕組みは変更しない。
トレードオフは、同じopcodeで新たに最適化可能になったcalleeの発見が
定期再試行まで遅れる場合があることである。

同じdebugドライバ（5 warmups、5 expansions、起動部分を含む）の
`Mul.flatten` コンパイル数/退役数は35/32から12/9に減った。
PGO/LTOなしの元のpyperformance expandスクリプトでは、反転順序の2 blocks、
各3 workers、5 warmups、5 values、loops=1で、修正後/修正前は0.9629
（実行時間3.71%短縮）。native codeへ名前を付けた別の診断プロファイルでも
`method_merge_block` の比率は2.93%から0.3%未満へ減少した。
その診断はexecutorを保持して名前を解決するため、時間測定とは分けて扱う。

## 最終PGO/LTO比較

最終PGO/LTO比較では `sympy_expand` の修正後/修正前は **0.9592**
（95%区間0.9562–0.9622）、**実行時間4.08%短縮**だった。
同時に測ったmainとの差は、修正前 **+13.27%** から修正後 **+8.65%**
（修正後/mainの95%区間1.0697–1.0994）に縮小した。
**部分的な修正であり、リグレッションの全解消ではない。**

SymPy 4結果の比較（比が小さいほど速い）:

| 結果 | 修正前/main | 修正後/main | 修正後/修正前 [95% CI] |
|---|---:|---:|---:|
| `sympy_expand` | 1.1327 | 1.0865 | 0.9592 [0.9562, 0.9622] |
| `sympy_integrate` | 0.9692 | 0.9708 | 1.0017 [0.9977, 1.0055] |
| `sympy_sum` | 0.9765 | 0.9662 | 0.9895 [0.9832, 0.9952] |
| `sympy_str` | 0.9991 | 0.9964 | 0.9973 [0.9921, 1.0027] |

`sympy_expand` の平均時間はmain 232.29 ms、修正前263.11 ms、
修正後252.36 ms。修正後/前のblock比は0.9588、0.9596、0.9590。
mainの9 workers中1件は247.83 msで、ほかは227.56–234.16 msだった。
遅いworkerも含めたため、mainに対する平均と区間にはこの変動を反映している。
過去の1.1448と今回の1.1327を修正の効果として数えない。

関連項目の修正後/修正前（mainとの再比較ではない）:

| 結果 | 時間比 [95% CI] |
|---|---:|
| `deepcopy` | 1.0011 [0.9945, 1.0076] |
| `deepcopy_memo` | 1.0133 [0.9936, 1.0482] |
| `deepcopy_reduce` | 1.0081 [1.0052, 1.0108] |
| `genshi_text` | 1.0026 [1.0000, 1.0053] |
| `genshi_xml` | 0.9765 [0.9698, 0.9823] |
| `go` | 1.0137 [1.0126, 1.0147] |
| `regex_compile` | 0.9962 [0.9938, 0.9990] |
| `richards_super` | 0.9925 [0.9906, 0.9943] |
| `sqlalchemy_declarative` | 1.0026 [0.9952, 1.0100] |

Genshi XMLは2.35%短縮。一方Goは1.37%、deepcopy_reduceは0.81%遅延した。
小さい差も含めて不利な結果を保持した。Goの遅延が再試行延期に由来するか、
PGO/コード配置の差に由来するかは未特定であり、今回は独立した同一ソースの
PGO再ビルド対照を測っていない。全項目で改善したとは結論しない。
`deepcopy_memo` はblock比が1.0349と0.9921で、区間も0.9936–1.0482。
安定した改善/悪化とは判断できず、「全関連項目で3%以内」とも保証しない。

全33実行が成功し、失敗・timeout・事後のサンプル除外はなかった。
測定前後のソース、バイナリ、共有拡張、依存、workload、harnessのSHA照合も成功した。

SymPyの4結果をmain・修正前・修正後で3 blocks測定し、順序を
main/before/after、before/after/main、after/main/beforeと回す。
各blockで3 workers、5 warmups、5 values、min-time=0.1秒、CPU 2固定。
環境はIntel Core i5-12450H、Linux 6.8.0-134-generic、glibc 2.39、GCC 13.3.0。
関連項目はgo、richards_super、genshi、sqlalchemy_declarative、deepcopy、
regex_compileを修正前/後の反転順序2 blocksで測る。全体の再測定ではない。

worker内の値を算術平均し、workerを等重みでblock平均にする。
block内の比を幾何平均し、各block・各側のworkerを独立に再標本化する
4,000回bootstrapで95%区間を求める。遅いworkerも除外しない。
区間は固定ビルドの実行変動を表し、再ビルド・別CPUでの再現性は保証しない。
小さな差はPGOや最終コード配置の変動も含み得る。

## 正しさの検証

- 新規回帰テストは、元のdebugビルドでは余計なexecutorが生成されて失敗し、
  修正後は成功した。属性の置換結果が即時に反映されること、再試行が延期
  されること、定期再試行が有効なexecutorを再作成することを検査する。
- opcode変更時の早期再試行を検査する既存テストも成功。
- GIL debug: `test_capi.test_opt`、`test_monitoring`、`test_generators`、
  `test_threading` の982テストを実行、9 skipped、失敗なし。
- FT debug: 上記と `test_free_threading.test_method_jit` の990テストを実行、
  50 skipped、失敗なし。今回FTの性能は測定していない。
- GIL/FT両debugビルドで、cacheを毎回消した12回の
  `(1+x+y+z)**20` の展開結果を多項定理と比較し、全1,771項の整数係数が一致。
- 最終PGO/LTO版: optimizerの579テストを実行、5 skipped、失敗なし。
  同じ12回の展開結果の全係数検査も成功した。PGO学習は10,632テスト、
  265 skipped、43モジュールで失敗なし。

## 採用しなかった案と残る作業

`Basic.compare` などの多態的な属性アクセスもホットだったため、異なる
直近のbaseを持つ型でも同じslot descriptorを使えるようにする案を試した。
開発ビルドの反転順序比較でSX2/SX1は0.9994とほぼ不変だったので戻した。
最終候補にこの変更は含まれない。

残るホットパスにはTier 1実行、型キャッシュの検索、辞書・オブジェクトの
生成がある。再コンパイルの抑制だけでtracing JITとの差全体がなくなるとは
限らない。次に手を入れる場合は、多態的な属性アクセスと大きなpartial
methodからの退出を実際の有効なnative領域に結び付ける必要がある。

## 再現資料

全資料は `jit-artifacts/sympy-expand-20260922/` に保存した。
ディレクトリ名の日付は測定日の根拠には使用しない。

- `timings.json`、`timing-*.log`: JIT有効/無効の固定仕事量の診断。
- `perf-*.data`、`perf-*-report.txt`: 元のPGOビルドのCPUプロファイル。
- `debug-baseline-v2.log`、`debug-sx1.log`: コンパイル・退役のログ。
- `dev-records.json`、`dev-*.json`: PGO/LTOなしのSX1比較。
- `dev2-records.json`、`dev2-*.json`: 不採用のSX2比較。
- `mapped-*.data`、`mapped-*.executors.json`: native領域を対応付けた診断。
- `sx0-regression-test.log`、`sx1-backoff-tests.log`、`sx1-*-tests.log`、
  `algebra-*.log`: 正しさの検証。
- `sx1-final/inputs.json`: 比較の全build manifestと依存・workloadのSHA-256。
- `sx1-final/records.json`、各 `.json`/`.log`: 全コマンドとworkerの生データ。
- `sx1-final/finished.json`: 測定後のidentity照合と失敗一覧。
- `sx1-final/analysis.json`、`analyze_final.py`: 統計量と集計方法。

ビルド・依存・入力は測定前後で照合する。SymPy 1.8、mpmath 1.2.1、
pyperf 2.10.0の既存環境を3構成で共有し、ネイティブ拡張のwheelも固定する。
基準と候補はともに `-O3 -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer`。
FPはJIT・共有拡張の設定も変更していない。`PYTHONHASHSEED=0`、
`PYTHON_JIT=1`、`PYTHON_GIL=1`。元のベンチマークのGC無効化と
毎回のSymPy cache clearを維持する。最終ベンチマークはsandbox外で逐次実行し、
ビルドや他の計測と競合させない。

最終実行ファイルのSHA-256:

| 構成 | `jit-artifacts/regressions-20260919/` 内のパス | SHA-256 |
|---|---|---|
| main | `r0-gil-main-build/python` | `29f98fde43417b99bad02a6710ad55e55f343a574f8fff306932d1e75b010044` |
| 修正前 | `mt6-gil-pgo-lto-build/python` | `806cb588e29a8ce1288b1b4df01964cfa806d2ac18f803031ddf07b46e78fb83` |
| 修正後 | `sx1-gil-pgo-lto-build/python` | `1e3b63eaa19d68d7c832dd59550399c284037a9680ecc94ff79640a51fac38ae` |

本修正と測定レポートをユーザーの依頼でコミットする。既存の `benchmarks/go.py` の
ファイルモード変更はそのまま保持し、コミット対象に含めない。
今回の採用差分はfingerprintの変更とその回帰テスト。今後は残る約9%の差に対して、
多態的アクセス・partial methodの退出を調べる。Goの小さな悪化を厳密に切り分ける
場合は、同一ソースのPGO再ビルド対照とコンパイル/退出回数の比較を先に行う。
