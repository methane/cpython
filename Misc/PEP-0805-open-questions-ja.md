# 最初の5段階に関する設計確認

## 静的な拡張型と複数 interpreter

PEP 805 は、C 拡張のモジュール・クラス・インスタンスを既定で LOCAL
としています。
[該当箇所](https://peps.python.org/pep-0805/#c-extensions-and-the-c-api)

現在の CPython では、`datetime.date` などの管理対象の静的な拡張型は、
複数の interpreter が同じ `PyTypeObject` を使います。その一方で、型の
辞書や弱参照などの状態には interpreter ごとの領域があります。
この実装で各 interpreter に別の Main を作ると、単一のヘッダー内の
owner ID だけでは、各 interpreter の Main に属する LOCAL 型として
扱えません。

通常ビルドで次の現象を確認しています。最初の interpreter では成功し、
2つ目では `IllegalThreadAccessException` が返ります。

```python
import datetime
import _interpreters

print(datetime.date(2000, 1, 1))
interp = _interpreters.create()
try:
    print(_interpreters.run_string(
        interp, 'import datetime; datetime.date(2000, 1, 1)'))
finally:
    _interpreters.destroy(interp)
```

検討したい方針は次の2つです。

1. 管理対象の静的拡張型については、既存の interpreter ごとの型状態に
   LOCAL の所有者を記録する。同じ C の型アドレスでも、interpreter ごとの
   型状態をそれぞれの所有対象と解釈する。
2. Main の ThreadGroup を interpreter 間で共有する。ただし、interpreter
   ごとの並列性やグループの寿命・識別にも影響する。

`_Py_TPFLAGS_STATIC_BUILTIN` は管理対象の拡張型にも使われているので、この
フラグを根拠として拡張型を一律 IMMUTABLE にするのは、既定を LOCAL とする
規定と合いません。組み込み型だけを、その初期化経路で明示的に IMMUTABLE
とする処理は実装済みです。

なお、以前の interpreter が終了した後の `Py_Finalize()` / `Py_Initialize()`
では、存命の所有者がないことを確認して静的オブジェクトを新しい Main に
結び直しています。既存の `test_embed.test_datetime_reset_strptime` で確認済み
です。この再初期化の問題と、上記の複数 interpreter の同時利用は別の問題です。
