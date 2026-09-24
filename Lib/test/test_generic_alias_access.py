"""Access checks when GenericAlias acquires its stored objects."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class GenericAliasAccessTests(unittest.TestCase):
    PRELUDE = '''
import threading
from types import GenericAlias
from test.support import SuppressCrashReport

class Origin:
    answer = 42
    def __call__(self): return 42
    def __repr__(self): return 'origin'
    def __hash__(self): return 42

class Parameter:
    def __typing_subst__(self, arg): return arg

lock = threading.Lock()
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_protected_origin_operations(self):
        for expression in (
            'alias()', 'repr(alias)', 'hash(alias)', 'alias.answer',
            'alias.__mro_entries__(())', 'alias.__reduce__()',
            'next(iter(alias))', 'dir(alias)', 'alias == peer',
        ):
            with self.subTest(expression=expression):
                self.run_script(f'''
                    with lock:
                        origin = lock.protect(Origin())
                        alias = GenericAlias(origin, (int,))
                        peer = GenericAlias(origin, (str,))
                        {expression}
                    with SuppressCrashReport():
                        try:
                            {expression}
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected origin acquired')
                    with lock:
                        {expression}
                ''')

    def test_protected_argument_repr(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                self.run_script(f'''
                    with lock:
                        argument = lock.protect(Origin())
                        args = ([argument],) if {nested!r} else (argument,)
                        alias = GenericAlias(list, args)
                        repr(alias)
                    with SuppressCrashReport():
                        try:
                            repr(alias)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected argument acquired')
                    with lock:
                        repr(alias)
                ''')

    def test_protected_argument_list(self):
        self.run_script('''
            with lock:
                arguments = lock.protect([int])
                alias = GenericAlias(list, (arguments,))
                repr(alias)
            with SuppressCrashReport():
                try:
                    repr(alias)
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected argument list acquired')
        ''')

    def test_protected_parameters(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                self.run_script(f'''
                    with lock:
                        parameter = lock.protect(Parameter())
                        alias = GenericAlias(list, (parameter,))
                        if {cached!r}:
                            assert alias[str].__args__ == (str,)
                    with SuppressCrashReport():
                        try:
                            alias[str]
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected parameter acquired')
                    with lock:
                        assert alias[str].__args__ == (str,)
                ''')

    def test_prepared_substitution_contains_protected_value(self):
        self.run_script('''
            calls = []
            class PreparedParameter:
                def __typing_prepare_subst__(self, alias, item):
                    return self.prepared
                def __typing_subst__(self, item):
                    calls.append('called')
                    return item
            with lock:
                value = lock.protect(Origin())
                parameter = PreparedParameter()
                parameter.prepared = (value,)
                alias = GenericAlias(list, (parameter,))
                alias.__parameters__
            with SuppressCrashReport():
                try:
                    alias[int]
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected substitution value acquired')
            assert calls == []
            with lock:
                assert alias[int].__args__ == (value,)
            assert calls == ['called']
        ''')

    def test_shallow_argument_retention(self):
        self.run_script('''
            with lock:
                argument = lock.protect(Origin())
                args = (argument,)
                alias = GenericAlias(list, args)
            # The accessible argument tuple may retain inaccessible elements.
            # Returning or storing the tuple does not access those elements.
            assert alias.__args__ is args
            assert alias.__reduce__()[1][1] is args
            starred = next(iter(alias))
            assert starred.__args__ is args
        ''')

    def test_shareable_state_is_not_forwarded_to_origin(self):
        self.run_script('''
            alias = GenericAlias(list, (int,))
            assert list.__shareable__ is threading.Shareable.IMMUTABLE
            assert alias.__shareable__ is threading.Shareable.LOCAL
            assert '__shareable__' in dir(alias)
            with lock:
                origin = lock.protect(Origin())
                alias = GenericAlias(origin, ())
            assert alias.__shareable__ is threading.Shareable.LOCAL
            assert alias.__shareable__ is object.__getattribute__(alias, '__shareable__')
        ''')

    @threading_helper.requires_working_threading()
    def test_foreign_argument_in_worker_created_alias(self):
        self.run_script('''
            arguments = (Origin(),)
            results = SynchronizedList()
            def worker():
                try:
                    alias = GenericAlias(list, arguments)
                    assert alias.__args__ is arguments
                    for operation in (lambda: repr(alias),
                                      lambda: alias.__parameters__):
                        try:
                            operation()
                        except IllegalThreadAccessException:
                            results.append('denied')
                        else:
                            results.append('foreign argument acquired')
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
