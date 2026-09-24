"""Access checks when native typing objects acquire stored references."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class TypingAccessTests(unittest.TestCase):
    PRELUDE = '''
import threading
from types import GenericAlias
from typing import Union, TypeVar, ParamSpec, TypeVarTuple, TypeAliasType
from test.support import SuppressCrashReport

class Value:
    def __repr__(self): return 'value'
    def __hash__(self): return 42
    def __eq__(self, other): return isinstance(other, Value)

lock = threading.Lock()
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_union_protected_argument(self):
        for hashable in (False, True):
            for expression in ('repr(union)', 'union == peer', 'union | str'):
                with self.subTest(hashable=hashable, expression=expression):
                    self.run_script(f'''
                        if not {hashable!r}:
                            Value.__hash__ = None
                        with lock:
                            value = lock.protect(Value())
                            union = Union[value, int]
                            # Distinct values force comparison of the arguments,
                            # rather than an internal identity-only fast path.
                            peer = Union[lock.protect(Value()), int]
                            {expression}
                        with SuppressCrashReport():
                            try:
                                {expression}
                            except UnprotectedAccessException:
                                pass
                            else:
                                raise AssertionError('unprotected union argument acquired')
                        with lock:
                            {expression}
                    ''')

    def test_union_hash_preserves_access_error(self):
        for expression in ('alias | int', 'Union[alias, int]'):
            with self.subTest(expression=expression):
                self.run_script(f'''
                    with lock:
                        value = lock.protect(Value())
                        alias = GenericAlias(value, ())
                        {expression}
                    try:
                        {expression}
                    except UnprotectedAccessException:
                        pass
                    else:
                        raise AssertionError('union suppressed access error from hashing')
                    with lock:
                        {expression}
                ''')

    def test_union_retains_ordinary_unhashable_values(self):
        self.run_script('''
            class Unhashable:
                def __hash__(self):
                    raise ValueError('unhashable')
            value = Unhashable()
            union = Union[value, int]
            assert union.__args__ == (value, int)
            assert union == Union[value, int]
            try:
                hash(union)
            except ValueError as exc:
                assert str(exc) == 'unhashable'
            else:
                raise AssertionError('unhashable union accepted')
        ''')

    def test_constant_evaluator_protected_value(self):
        for factory in (
            "TypeVar('T', bound=value).evaluate_bound",
            "TypeVar('T', default=value).evaluate_default",
            "ParamSpec('P', default=value).evaluate_default",
            "TypeVarTuple('Ts', default=value).evaluate_default",
            "TypeAliasType('A', value).evaluate_value",
        ):
            for expression in ('evaluator(4)', 'evaluator(1)', 'repr(evaluator)'):
                with self.subTest(factory=factory, expression=expression):
                    self.run_script(f'''
                        with lock:
                            value = lock.protect(Value())
                            evaluator = {factory}
                            assert evaluator(4) == 'value'
                            assert evaluator(1) is value
                        with SuppressCrashReport():
                            try:
                                {expression}
                            except UnprotectedAccessException:
                                pass
                            else:
                                raise AssertionError('unprotected constant acquired')
                        with lock:
                            assert evaluator(4) == 'value'
                            assert evaluator(1) is value
                    ''')

    def test_constant_evaluator_tuple_elements(self):
        self.run_script('''
            with lock:
                value = lock.protect(Value())
                parameter = TypeVar('T', value, int)
                evaluator = parameter.evaluate_constraints
                constraints = parameter.__constraints__
                assert evaluator(4) == '(value, int)'
            # An accessible tuple can retain inaccessible elements.
            assert evaluator(1) is constraints
            with SuppressCrashReport():
                try:
                    evaluator(4)
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected tuple element acquired')
            with lock:
                assert evaluator(4) == '(value, int)'
        ''')

    def test_generic_alias_protected_default(self):
        self.run_script('''
            with lock:
                value = lock.protect(Value())
                parameter = TypeVar('T', default=value)
                alias = GenericAlias(list, (parameter,))
                assert alias[()].__args__ == (value,)
            with SuppressCrashReport():
                try:
                    alias[()]
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected default acquired')
            with lock:
                assert alias[()].__args__ == (value,)
        ''')

    @threading_helper.requires_working_threading()
    def test_union_hash_preserves_foreign_access_error(self):
        self.run_script('''
            args = (Value(),)
            results = SynchronizedList()
            def worker():
                try:
                    alias = GenericAlias(list, args)
                    for operation in (lambda: alias | int,
                                      lambda: Union[alias, int],
                                      lambda: Union[args]):
                        try:
                            operation()
                        except IllegalThreadAccessException:
                            results.append('denied')
                        else:
                            results.append('foreign argument accepted')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
            thread = threading.Thread(target=worker, group=threading.ThreadGroup())
            thread.start()
            thread.join()
            assert list(results) == ['denied'] * 3, list(results)
        ''')

    @threading_helper.requires_working_threading()
    def test_type_alias_foreign_type_parameters(self):
        for factory in ("TypeVar('T')", "ParamSpec('P')", "TypeVarTuple('Ts')"):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    params = ({factory},)
                    results = SynchronizedList()
                    def worker():
                        try:
                            TypeAliasType('A', int, type_params=params)
                        except IllegalThreadAccessException:
                            results.append('denied')
                        except BaseException as exc:
                            results.append((type(exc).__name__, str(exc)))
                        else:
                            results.append('foreign parameter accepted')
                    thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                    thread.start()
                    thread.join()
                    assert list(results) == ['denied'], list(results)
                ''')

    @threading_helper.requires_working_threading()
    def test_transferred_paramspec_attribute(self):
        self.run_script('''
            parameter = ParamSpec('P')
            boxes = (threading.TransferBox(parameter.args),
                     threading.TransferBox(parameter.kwargs))
            results = SynchronizedList()
            def worker():
                try:
                    for box in boxes:
                        attribute = box.claim()
                        try:
                            repr(attribute)
                        except IllegalThreadAccessException:
                            results.append('denied')
                        else:
                            results.append('foreign parameter represented')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
            with SuppressCrashReport():
                thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                thread.start()
                thread.join()
            assert list(results) == ['denied', 'denied'], list(results)
        ''')


if __name__ == '__main__':
    unittest.main()
