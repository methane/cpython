# 最初の5段階に関する設計確認

## 決定済み: 静的な拡張型と複数 interpreter

各 subinterpreter が固有の Main ThreadGroup を持ち、現在の静的な拡張型は
将来すべて非 static な型へ移行する方針です。interpreter 間で Main を共有
する方法や、共有された静的型のヘッダーに対する所有権の特例は追加しません。
この点について追加の設計確認は不要です。以下は型の移行が済むまで残る
互換性上の制限です。

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

`_Py_TPFLAGS_STATIC_BUILTIN` は管理対象の拡張型にも使われているので、この
フラグを根拠として拡張型を一律 IMMUTABLE にするのは、既定を LOCAL とする
規定と合いません。組み込み型だけを、その初期化経路で明示的に IMMUTABLE
とする処理は実装済みです。

なお、以前の interpreter が終了した後の `Py_Finalize()` / `Py_Initialize()`
では、存命の所有者がないことを確認して静的オブジェクトを新しい Main に
結び直しています。既存の `test_embed.test_datetime_reset_strptime` で確認済み
です。この再初期化の問題と、上記の複数 interpreter の同時利用は別の問題です。

## 未チェックの C API マクロの契約

PEP は C API 関数の戻り値を検証し、拡張側のコールバックの戻り値も VM が
検証するとしています。
[C API functions / Extension API](https://peps.python.org/pep-0805/#c-api-functions)

一方、`PyTuple_GET_ITEM` は現在も配列要素を直接読むマクロです。
`PyTuple_GetItem` のような、失敗を返す関数とは契約が異なります。
たとえば、拡張がアクセス可能な immutable tuple を受け取り、次のように
その中のオブジェクトを使う場合があります。

```c
PyObject *value = PyTuple_GET_ITEM(tuple, 0);
return PyObject_CallNoArgs(value);
```

tuple は shallow immutable なので、要素が他の ThreadGroup の LOCAL である
ことはあり得ます。マクロを未チェックのままにすると、この取得には検査が
入りません。一方、マクロを `NULL` と例外を返す形に変えるだけでは、従来は
ここで失敗しないと考えていた拡張が `NULL` をそのまま使用する可能性があります。
これは公開ヘッダーと呼び出し経路から確認した契約上の問題で、上のコードを
安全な公開 API の使用例として推奨するものではありません。

確認したい点は、これらの未チェックのマクロにも取得検査を要求するのか、
それとも明示的な取得検査を行う責任を拡張側に残すのか、ということです。
後者なら、拡張を変更しなくてよいという記述の適用範囲も確認したいです。
`PyList_GET_ITEM` などにも同じ問題があります。

既に取得済みの引数すべてを再検査する方針にはしていません。関数版の
getter、VM のヒープロード、`*args` / `**kwargs` の展開など、明確に
新しいスレッド参照を作る箇所の修正は、この確認と独立して進めています。

## 他のグループから最後の参照がなくなる LOCAL オブジェクト

解放方式は Mark と確認してから決める方針です。専用 cleanup スレッドの
採用は保留し、この判断に依存しない参照取得・GC 基盤の修正を進めます。

PEP は LOCAL オブジェクトの即時回収を維持するとしています。一方、tuple
などの immutable なコンテナは shallow immutable なので、要素には LOCAL
オブジェクトを含められます。
[Deferred reclamation](https://peps.python.org/pep-0805/#deferred-reclamation)

たとえば、A グループで作った LOCAL オブジェクトを tuple に入れて共有し、
A 側の参照とスレッドがすべてなくなった後、B グループで最後の tuple 参照を
破棄する場合です。B はその LOCAL 要素を取得できなくても、tuple の破棄では
要素の参照カウントを減らす必要があります。

要素の `__del__` や弱参照コールバックは、A の LOCAL な関数・データに
アクセスする可能性があります。現在の通常ビルドは interpreter GIL により
参照カウントの合算を直列化していますが、解放を B で実行すると、この所有権
条件を満たしません。GC の finalizer や `tp_clear` にも同じ実行場所の問題が
あります。

確認したい点は、A に属する専用 cleanup スレッドによる非同期処理を許容し、
即時回収の保証を所有グループ内で最後の参照を失う場合に限定してよいかです。
既存スレッドの group を一時的に変更する方法では、読み取り専用の
`Thread.group` と実際の実行グループの整合性にも問題が出ます。
専用スレッド方式でも、終了処理・復活・メモリ不足時の動作を設計する必要が
あるため、この方式はまだ実装していません。

別案として、B が cleanup スレッドの完了を同期的に待てば、解放を呼び出した
操作が戻る前に回収できます。ただし、B のスレッドが保持する RLock を
`__del__` が取得する場合など、同じ OS スレッドでの解放とはロックの動作が
変わります。非同期処理が唯一の実装方法という意味ではなく、即時回収・
実行スレッド・所有グループのどの保証を与えるかを確認したい、という問題です。
