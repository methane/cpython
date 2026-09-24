"""Access checks for references retained by itertools objects."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class ItertoolsAccessTests(unittest.TestCase):
    PRELUDE = '''
import itertools
import threading
from test.support import SuppressCrashReport

class Callable:
    def __call__(self, *args): return 1

class Number:
    def __init__(self, value): self.value = value
    def __int__(self): return self.value
    def __add__(self, other): return self.value
    def __radd__(self, other): return self.value

lock = threading.Lock()
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_stored_callbacks(self):
        for factory in (
            'itertools.dropwhile(callback, (1, 2))',
            'itertools.takewhile(callback, (1, 2))',
            'itertools.filterfalse(callback, (1, 2))',
            'itertools.starmap(callback, ((1,), (2,)))',
            'itertools.groupby((1, 2), callback)',
            'itertools.accumulate((1, 2), callback, initial=0)',
        ):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    with lock:
                        callback = lock.protect(Callable())
                        iterator = {factory}
                        if isinstance(iterator, itertools.accumulate):
                            assert next(iterator) == 0
                    with SuppressCrashReport():
                        try:
                            next(iterator)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected callback invoked')
                ''')

    def test_stored_iterator_apis(self):
        for factory in (
            'itertools.groupby(source)',
            'itertools.cycle(source)',
            'itertools.chain.from_iterable(source)',
            'itertools.tee(source)[0]',
            'itertools.zip_longest(source)',
        ):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    with lock:
                        source = iter(lock.protect([(1,), (2,)]))
                        iterator = {factory}
                    with SuppressCrashReport():
                        try:
                            next(iterator)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected iterator advanced')
                ''')

    def test_accumulate_stored_total(self):
        for operation in ('', ', lambda left, right: 0'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    with lock:
                        value = lock.protect(Number(3))
                        iterator = itertools.accumulate((value, 1){operation})
                        assert next(iterator) is value
                    with SuppressCrashReport():
                        try:
                            next(iterator)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected total used')
                ''')

    def test_count_stored_numbers(self):
        for factory, operation in (
            ('itertools.count(value, 1.5)', 'next(iterator)'),
            ('itertools.count(0.0, value)', 'next(iterator)'),
            ('itertools.count(0.0, value)', 'repr(iterator)'),
        ):
            with self.subTest(factory=factory, operation=operation):
                self.run_script(f'''
                    with lock:
                        value = lock.protect(Number(3))
                        iterator = {factory}
                    with SuppressCrashReport():
                        try:
                            {operation}
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected number used')
                ''')

    def test_groupby_stored_keys(self):
        for operation in ('next(iterator)', 'next(group)'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    with lock:
                        key = lock.protect(Number(3))
                        iterator = itertools.groupby((key, key))
                        _, group = next(iterator)
                    with SuppressCrashReport():
                        try:
                            {operation}
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected group key compared')
                ''')

    def test_denied_acquisitions_release_references(self):
        self.run_script("""
            import sys
            with lock:
                value = lock.protect(Number(3))
                counter = itertools.count(value)
                step_counter = itertools.count(1.5, value)
                totals = itertools.accumulate(itertools.repeat(1), initial=value)
                assert next(totals) is value
                before = sys.getrefcount(value)
            with SuppressCrashReport():
                for _ in range(50):
                    for iterator in (counter, step_counter, totals):
                        try:
                            next(iterator)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected value accessed')
            with lock:
                assert sys.getrefcount(value) == before
        """)

    def test_count_reentrant_add_retains_result(self):
        self.run_script("""
            import weakref
            class ReentrantNumber:
                entered = False
                def __int__(self): return 0
                def __add__(self, other):
                    if not self.entered:
                        self.entered = True
                        next(counter)
                    return 1000
            original = ReentrantNumber()
            reference = weakref.ref(original)
            counter = itertools.count(original)
            del original
            with SuppressCrashReport():
                result = next(counter)
                assert reference() is result
                assert isinstance(result, ReentrantNumber)
                del result
                assert reference() is None
                assert next(counter) == 1000
        """)

    def test_zip_longest_fresh_result(self):
        self.run_script("""
            with lock:
                source = iter(lock.protect([1, 2]))
                iterator = itertools.zip_longest(source)
                retained = next(iterator)
                assert retained == (1,)
            with SuppressCrashReport():
                try:
                    next(iterator)
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected iterator advanced')
        """)

    @threading_helper.requires_working_threading()
    def test_grouper_foreign_parent(self):
        self.run_script("""
            import sys
            from test.support import threading_helper
            parent = itertools.groupby((1, 1))
            _, first = next(parent)
            results = SynchronizedList()
            def worker():
                try:
                    # Debugger access can create a local wrapper retaining a
                    # foreign parent. Ordinary access must validate that field.
                    with sys.monitoring.StopTheWorld:
                        group = itertools._grouper(parent, 1)
                    next(group)
                except IllegalThreadAccessException:
                    results.append('denied')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
                else:
                    results.append('foreign parent accessed')
            with SuppressCrashReport():
                thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
            assert list(results) == ['denied'], list(results)
            assert next(itertools._grouper(parent, 1)) == 1
        """)

    def test_cycle_cached_item(self):
        self.run_script("""
            with lock:
                value = lock.protect([])
                iterator = itertools.cycle((value,))
                assert next(iterator) is value
            with SuppressCrashReport():
                try:
                    next(iterator)
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('unprotected cached item returned')
            with lock:
                assert next(iterator) is value
        """)

    @threading_helper.requires_working_threading()
    def test_transferred_tee_buffer(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                self.run_script(f'''
                    from test.support import threading_helper
                    first, second = itertools.tee((1, 2, 3))
                    if {cached}:
                        assert next(first) == 1
                    box = threading.TransferBox(second)
                    results = SynchronizedList()
                    def worker():
                        try:
                            next(box.claim())
                        except IllegalThreadAccessException:
                            results.append('denied')
                        except BaseException as exc:
                            results.append((type(exc).__name__, str(exc)))
                        else:
                            results.append('foreign buffer accessed')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                        with threading_helper.start_threads([thread]):
                            pass
                    assert list(results) == ['denied'], list(results)
                    assert next(second) == 1
                ''')


if __name__ == '__main__':
    unittest.main()
