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

## 決定済み: 失敗を返せない取得経路の暫定処理

参照実装の差分を抑えるため、通常のエラー処理で返せない例外的なケースは、
可能な範囲で C stderr に診断を書いて abort する方針です。ユーザーの指示に
基づく暫定処理で、該当箇所に `//TODO(pep805)` を残します。追加の回復機構は
作りません。通常の例外返却が可能な取得経路では、引き続き
`IllegalThreadAccessException` を返します。

`PyErr_Fetch()` と `PyErr_GetExcInfo()` は戻り値が void で、出力引数に
参照を返します。自分の例外が別グループの LOCAL な traceback を保持する
ケースを再現しました。両 API は例外・型・traceback の取得を検査し、拒否時は
API 名と `IllegalThreadAccessException` を C stderr に書いて abort します。
Python の例外表示や `sys.stderr` は使いません。Main の正常系と、
Python の stderr がなくても subprocess が SIGABRT で終了することを検証します。

`PyDict_Next()` の出力参照と、真偽値を返す `PyErr_GivenExceptionMatches()`
の tuple 要素にも、通常の失敗返却が定義されていないという問題があります。
両 API にも同じ診断と abort を追加しました。要求されない辞書の出力参照と、
例外の照合が完了して読まれない後続要素は取得検査の対象にしません。
内部のコピー処理は既存の `_PyDict_Next()` を使い、ヒープ参照のコピーと
新しいスレッド参照の取得を区別します。

`PyTuple_GET_ITEM` / `PyList_GET_ITEM` などの未チェックマクロには、
opaque なヒープ参照のコピーにも使われるという違いがあります。マクロ自体を
一律に検査するか、取得側に明示的な検査を要求するかは、残る監査項目です。
PEP の戻り値検査の規定は、既に取得済みの引数すべてを再検査する要求とは
区別します。
[C API functions / Extension API](https://peps.python.org/pep-0805/#c-api-functions)

## PEP に明記済み: 別の拡張の関数やスロットの直接呼び出し

2026-09-26 に確認した PEP は、CPython と関数呼び出しだけでやり取りする
拡張と、別の拡張の明示的 API や `PyTypeObject` 内の関数ポインターを
呼ぶ拡張を区別しています。後者には明示的なアクセス検査を追加する必要が
あると書かれています。この点は追加の設計確認から外します。
[Backwards Compatibility / C extensions](https://peps.python.org/pep-0805/#c-extensions)

たとえば `Py_TYPE(iter)->tp_iternext(iter)` は `PyIter_Next()` の戻り値検査を
経由しません。CPython 本体の `all` / `any` / `filter` の同種の呼び出しには、
既に結果を使用する前の検査を追加しています。上記のマクロや出力引数の
失敗契約は、この直接呼び出しの規定とは別の確認事項です。

## 決定済み: 所有グループの終了後の回収と Python コールバック

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

その後、Mark から `__del__` と weakref callback は呼ばなくてよいと回答を
得ました。これを受け、別グループで回収する際にアクセスできない Python
コールバックは実行せず、stderr にスキップしたことを記録する方針にしました。
関数・クラス・globals をまとめて移譲する必要はありません。この点について
追加の設計確認は不要です。

`__del__` は、対象またはそのクラスを取得できなければメソッドを探索せず、
取得できない `__del__` メソッドも呼び出しません。weakref callback は、関数と
引数の weakref の両方を取得できる場合に呼び出します。参照カウントによる
破棄と GC の両方にこの判定を適用します。所有グループに待機中のスレッドが
残っていても、取得できない Python オブジェクトへのアクセスは許可しません。

ログは固定文字列を C の stderr に書き込み、取得できないオブジェクトの
`repr()`、Python の `sys.stderr.write()`、`sys.unraisablehook` を呼びません。
同じグループ内での通常のコールバック実行と、そのコールバックが発生させる
例外の既存の報告経路は維持します。回収前から存在する例外も保持します。

回帰テストは `Lib/test/test_threadgroup_ownership.py` の
`test_foreign_finalization_callbacks`、ネイティブの準備・回収処理は
`Modules/_testinternalcapi/threadgroups.c` の `threadgroup_finalization_probe`
にあります。Main の対照ケース、参照カウント・GC、終了済み・待機中の所有者、
共有可能な callback と取得できない weakref、共有可能なクラスと LOCAL な
`__del__` 関数を検証しています。専用 cleanup スレッドや実行中のスレッドの
所属変更は使いません。

この決定は Python のコールバックに関するもので、拡張型の `tp_dealloc` /
`tp_clear` の所有権・寿命の監査や、C API の未チェック取得の契約の確認を
完了したという意味ではありません。

所有グループが空の GC 対象については、ネイティブ `tp_finalize` と
`tp_clear` の前にも単体の移譲を行うようにしました。従来の `_Py_Dealloc()`
での移譲だけでは、循環参照の解消や finalizer の実行に間に合わないためです。
回帰テストは `test_orphan_cycle_reclamation` です。

## 決定済み: 所有グループが存命の場合のネイティブ解放

ユーザーから、所有グループにスレッドが残っていても stderr に記録し、
その場でネイティブの解放処理を続行する指示を受けました。これは Mark からの
Python コールバックに関する回答とは別に決まった実装方針です。

この判断の前に、LOCAL な拡張型の LOCAL インスタンスを
immutable tuple に格納し、別グループから tuple の最後の参照を解放しました。
同じ interpreter 内に所有者の thread state を残した診断では、次の結果です。

| 条件 | 観測 |
| --- | --- |
| Main 内での回収 | ネイティブ処理の対象はアクセス可能 |
| 未合算の LOCAL、所有者は待機中 | BRC キューに残り、所有グループの再開後に回収 |
| 合算済みの LOCAL、所有者は待機中 | 別グループで `tp_dealloc` が呼ばれ、対象はアクセス不可 |
| 同条件の自己参照サイクルを GC | `tp_clear` と `tp_dealloc` が別グループで呼ばれ、対象はアクセス不可 |

この診断は同じ OS スレッドで thread state を切り替えて実行し、C スロットの
入口で `PyObject_IsAccessible()` を記録しています。並行したデータ競合そのものを
計測したものではありません。診断用 C 拡張は
`/tmp/pep805-base/native_reclaim_probe.c`、実行スクリプトは同ディレクトリの
`native_reclaim_probe.py`、結果は `native-reclaim-after.log` にあります。

`_Py_Dealloc()` は `_PyThreadGroup_TryAdopt()` が失敗してもネイティブの
deallocator を呼びます。GC の native finalizer と clearing も、所有者が
存命なら移譲できません。PEP は C 拡張を既定で LOCAL とするため、その
ネイティブ処理が所有グループ内の共有状態に触れる可能性を排除できません。

今回の方針では、所有者の再開を待つ仕組みは追加しません。移譲後も対象が
アクセス不可なら、`tp_dealloc` および GC の `tp_clear` / `tp_finalize` の
呼び出しを固定文字列で C stderr に記録してから続行します。Python の
`__del__` と weakref callback のスキップは維持します。ログ自体は Python を
実行せず、既存の例外も変更しません。回帰テストは
`test_native_reclamation_with_live_owner` です。

これは既存の LOCAL 拡張のすべてのネイティブ処理について競合がないことを
示すものではありません。参照実装の実行方針として記録し、未回答の設計質問
からは外します。
