# CPython / JIT 向けの単体ベンチマーク

`spectral_norm.py` の次に、Python の異なる実行パターンを見るための5本。
各 `.py` にアルゴリズム・入力・計測コードを収めてあるので、そのファイルだけを
別のディレクトリにコピーして実行できる。外部パッケージ、`pyperf`、データファイル、
ネットワーク接続は不要。Python 3.10 以降の標準ライブラリだけを使う。

| スクリプト | 1 operation の処理 | CPython 側で見る対象 |
| --- | --- | --- |
| [bpe_tokeniser.py](bpe_tokeniser.py) | 元の Frankenstein 序文全体で語彙1024個を学習し、全文を符号化 | `bytes` をキーにした辞書、`Counter` 更新、タプル、スライス、内包表記、ネストしたループ |
| [btree.py](btree.py) | 20,000レコードを B-tree に挿入し、20%を削除・再挿入、全件走査と個別検索 | 再帰、`__slots__`、添字アクセス、`yield from`、リスト操作、属性アクセス |
| [deltablue.py](deltablue.py) | 長さ100の等値制約チェーンと100組のスケール・オフセット制約を構築・更新 | 継承、`super()`、多態的なメソッド呼び出し、属性の読み書き、オブジェクトグラフ |
| [hexiom.py](hexiom.py) | 元の level 25 を同じ探索順序で解く | 分岐の多い再帰探索、ネストしたリスト、可変状態の複製、辞書検索 |
| [raytrace.py](raytrace.py) | 元の球と市松模様のシーンを100×100画素で描画 | 演算子オーバーロード、短命オブジェクト、メソッド呼び出し、浮動小数点演算、再帰 |

文字列処理から始めるなら `bpe_tokeniser.py`、数値カーネルからオブジェクトを使う
数値処理へ進むなら `raytrace.py` が入口になる。`btree.py` と `hexiom.py` は
複雑な制御フローを、`deltablue.py` はクラス階層をまたぐ呼び出しを補う。

実アプリケーションで使う処理とデータ構造を選んでいるが、アプリ全体の負荷を
代表するものではない。特に DeltaBlue は合成ベンチマーク、BPE は簡易実装で、
実際の高速なトークナイザー製品と同じ実装ではない。
`re` による単語分割、`math.sqrt`、辞書やリストなど標準の C 実装も利用するが、
主要なアルゴリズムと反復処理はファイル内の Python コードで実行する。

## 実行

`spectral_norm.py` と同じオプション、同じデフォルト値を使う。

```sh
python3 bpe_tokeniser.py
python3 hexiom.py --loops 20 --warmups 5 --values 10
python3 raytrace.py --loops 1 --warmups 3 --values 10 --json > raytrace.json
```

- `--loops`: 1サンプル内の operation 数。デフォルト1、正の整数。
- `--warmups`: 計測前に実行するサンプル数。デフォルト3、0以上。
- `--values`: 記録するサンプル数。デフォルト10、正の整数。
- `--json`: 実行環境、負荷の説明、設定、中央値・最小値・各サンプルの秒数、
  検証済みチェックサムを JSON で出力する。

時間はすべて **1 operation あたり**。1サンプルの経過時間を `--loops` で割る。
各 operation で木・制約グラフ・探索状態・描画先・BPE 語彙を作り直す。
ファイル読み込みと import は計測に含めず、自動 GC の設定は変更しない。
各ウォームアップと各計測サンプルの最後の結果を検証し、検証失敗時は終了する。
チェックサム計算と追加の結果検証は計測外。元のアルゴリズム内の整合性チェックは
残してあり、DeltaBlue の途中の失敗も例外にする。

同じ JIT 対応 Python の有効・無効を比較する例:

```sh
PYTHON_JIT=0 /path/to/python deltablue.py --loops 20 --warmups 10 --values 20 --json > deltablue-off.json
PYTHON_JIT=1 /path/to/python deltablue.py --loops 20 --warmups 10 --values 20 --json > deltablue-on.json
```

JSON の `jit_enabled` は `sys._jit.is_enabled()` の値で、API がない Python では
`null`。これは有効化状態を記録するもので、計測対象が実際に JIT コードを実行した
証拠ではない。短い負荷では `--loops` を増やし、ウォームアップが十分かは各サンプルの
推移で確認する。比較時は同じ入力・引数・CPU affinity を使い、別プロセスでの実行も
繰り返す。`--json` の形式はこのスクリプト専用で、pyperf の JSON 形式ではない。

## 元の pyperformance からの変更

元コードは `pyperformance/data-files/benchmarks/bm_<名前>/run_benchmark.py`。
出典・著者・ライセンスに関する元のモジュール説明を各スクリプトに残した。
基本のアルゴリズムは保ち、pyperf の実行部分を各ファイル内の簡単な計測器に置き換えた。

- BPE: 元の31,206バイトの入力をそのまま埋め込み。学習と符号化の両方を計測する。
  全文の復号一致と、元コードで取得した10,335トークンの SHA-256 を検証する。
- B-tree: 元の200,000レコードを20,000に縮小。レコード生成・挿入順・検索キーの
  乱数生成を計測外に移動し、seed は0に固定。明示的な `gc.collect()` を除いた。
  全件走査後の合計を保持し、検索失敗も必ず含める。サイズ、キー順序、レコードの
  同一性、走査・検索の合計を検証する。元の GC 性能を見る負荷とは区別する。
- DeltaBlue: 元のサイズ100とアルゴリズムを保持。失敗時の `print` を例外に変更し、
  最終的な伝播値を戻して全件検証する。
- Hexiom: 入力を元のデフォルト level 25 に固定。探索結果の状態と、元コードにある
  期待解の全文を照合する。
- Raytrace: 元のシーンと100×100画素を保持。ファイル出力を行わず、元コードで取得した
  RGB 全30,000バイトの SHA-256 を検証する。

これらの計測値は独自の計測区間・設定によるもので、pyperformance の公式結果と
そのまま混ぜて比較するものではない。
