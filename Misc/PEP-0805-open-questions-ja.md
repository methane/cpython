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

## 未チェックの C API マクロと直接スロット呼び出しの契約

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

`Py_TYPE(iter)->tp_iternext(iter)` のように、拡張側がネイティブのスロットを
直接呼ぶ場合も同じ確認が必要です。`PyIter_Next()` を経由しないため、その
戻り値検査は働きません。ネイティブ iterator が未検査の LOCAL 要素を返すと、
CPython 本体でも `all` / `any` が真偽値を読み、`filter` は後から例外に
なっても、その前に要素の真偽値コールバックを実行していました。本体の
該当箇所には結果を使用する前の検査を追加しました。第三者の拡張が行う
直接呼び出しも VM が検査する対象なのか、拡張側に検査済み API の利用を
要求するのかは、PEP の「拡張を変更しなくてよい」の範囲と併せて確認したいです。

関数形式でも、`PyDict_Next` のようにオブジェクトを出力引数で返し、
終了を0で表す API には同様の確認が必要です。既存の呼び出し側は
アクセス拒否を想定していないため、拒否時の戻り値と例外確認の契約を
定める必要があります。runtime の marshal 内部では、この契約変更と
独立して、取り出した参照を使用する前に検査しています。

既に取得済みの引数すべてを再検査する方針にはしていません。関数版の
getter、VM のヒープロード、`*args` / `**kwargs` の展開など、明確に
新しいスレッド参照を作る箇所の修正は、この確認と独立して進めています。

## 所有グループの全スレッド終了後の解放

Mark から「所有 ThreadGroup にスレッドがなければ競合しないので、decref
するグループがオブジェクトの所有権を原子的に引き継げる」と回答を得ました。
この単体の移譲は実装しました。待機中・開始前の thread state も所属数に
含め、新規参加と同じ mutex でゼロ判定と参照カウントの合算を保護し、
owner ID を compare/exchange で更新します。合算後は共有カウンターを使います。
スレッドの所属変更や専用 cleanup スレッドは使いません。

これにより、所有グループが空なら、別グループで tuple を破棄した際に LOCAL
要素をその場で回収できます。合算済みの参照カウントがゼロになる経路も対象です。
GC が空の所有グループの BRC キューを処理する場合は、世界を再開してから
参照を解放します。従来の「30グループで90参照残る」弱参照の再現例は、
変更後には増加ゼロになりました。Main の対照ケースにも比例した増加はありません。
`/tmp/pep805-base/orphan-leak-final.log` に結果を記録しています。

残る確認点は、Python の `__del__` が取得する別オブジェクトの扱いです。
要素だけを移譲しても、`__del__` 関数・クラス・globals は元グループの LOCAL
です。A で作ったインスタンスを含む tuple を A の終了後に Main で破棄する
再現例では、`__del__` が呼ばれませんでした。ネイティブの検証は
`/tmp/pep805-base/orphan_finalizer_probe.c`、結果は
`/tmp/pep805-base/orphan-finalizer-evidence.log`（呼び出し回数0）です。

取得するオブジェクトも空のグループから順に移譲する案には、さらに次の問題が
あります。A の同じクラスのインスタンスを B と C が別々に破棄すると、先に B が
取得したクラス・関数・globals は B の LOCAL になります。その後の C の解放では、
B にスレッドが残っているため同じ規則で移譲できません。この二度目のケースを
どう扱うか確認したいです。一般のアクセス検査を無条件に緩めたり、オブジェクト
グラフ全体を暗黙に移譲したりはしていません。

所有グループにスレッドが残る場合の合算済み LOCAL の解放、GC の `tp_finalize` /
`tp_clear`、LOCAL な弱参照コールバックにも実行場所の問題が残ります。
今回の回答を、これらがすべて解決したという意味には解釈していません。
