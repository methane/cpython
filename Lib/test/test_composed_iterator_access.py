"""Access to references retained inside builtin iterator wrappers."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class ComposedIteratorAccessTests(unittest.TestCase):
    PRELUDE = '''
import itertools
import threading
from test.support import SHORT_TIMEOUT, SuppressCrashReport

class Sequence:
    def __len__(self): return 3
    def __getitem__(self, index):
        if index >= 3: raise IndexError
        return index + 10

class Callable:
    def __call__(self, *args): return 42
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    @threading_helper.requires_working_threading()
    def test_transferred_sequence_iterator(self):
        cases = (
            ('iter', 'next(iterator)'),
            ('iter', 'iterator.__length_hint__()'),
            ('reversed', 'next(iterator)'),
            ('reversed', 'iterator.__length_hint__()'),
            ('reversed', 'iterator.__setstate__(0)'),
        )
        for factory, operation in cases:
            with self.subTest(factory=factory, operation=operation):
                self.run_script(f'''
                    box = threading.TransferBox({factory}(Sequence()))
                    results = SynchronizedList()
                    def worker():
                        try:
                            iterator = box.claim()
                            {operation}
                        except IllegalThreadAccessException:
                            results.append('denied')
                        except BaseException as exc:
                            results.append((type(exc).__name__, str(exc)))
                        else:
                            results.append('foreign sequence accessed')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                        thread.start()
                        thread.join()
                    assert list(results) == ['denied'], list(results)
                ''')

    @threading_helper.requires_working_threading()
    def test_transferred_wrapper_native_iterator(self):
        for expression in (
            'enumerate(source)', 'filter(None, source)', 'map(int, source)',
            'zip(source)', 'map(int, source, strict=True)',
            'zip(source, strict=True)',
            'map(int, iter(SynchronizedList()), source, strict=True)',
            'zip(iter(SynchronizedList()), source, strict=True)',
        ):
            with self.subTest(expression=expression):
                self.run_script(f'''
                    source = itertools.count(10)
                    box = threading.TransferBox({expression})
                    results = SynchronizedList()
                    def worker():
                        try:
                            iterator = box.claim()
                            next(iterator)
                        except IllegalThreadAccessException:
                            results.append('denied')
                        except BaseException as exc:
                            results.append((type(exc).__name__, str(exc)))
                        else:
                            results.append('foreign iterator advanced')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                        thread.start()
                        thread.join()
                    assert list(results) == ['denied'], list(results)
                    assert next(source) == 10
                ''')

    @threading_helper.requires_working_threading()
    def test_zip_fresh_result_checks_iterator(self):
        self.run_script('''
            source = itertools.count(10)
            box = threading.TransferBox(zip(source))
            results = SynchronizedList()
            def worker():
                iterator = box.claim()
                with __import__('sys').monitoring.StopTheWorld:
                    retained = next(iterator)
                assert retained == (10,)
                try:
                    next(iterator)
                except IllegalThreadAccessException:
                    results.append('denied')
                else:
                    results.append('foreign iterator advanced')
            thread = threading.Thread(target=worker, group=threading.ThreadGroup())
            thread.start()
            thread.join()
            assert list(results) == ['denied'], list(results)
            assert next(source) == 11
        ''')

    @threading_helper.requires_working_threading()
    def test_transferred_wrapper_callable(self):
        for expression in (
            'filter(Callable(), SynchronizedList((10, 11)))',
            'map(Callable(), SynchronizedList((10, 11)))',
            'iter(Callable(), None)',
        ):
            with self.subTest(expression=expression):
                self.run_script(f'''
                    box = threading.TransferBox({expression})
                    results = SynchronizedList()
                    def worker():
                        try:
                            iterator = box.claim()
                            next(iterator)
                        except IllegalThreadAccessException:
                            results.append('denied')
                        except BaseException as exc:
                            results.append((type(exc).__name__, str(exc)))
                        else:
                            results.append('foreign callable invoked')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                        thread.start()
                        thread.join()
                    assert list(results) == ['denied'], list(results)
                ''')

    def test_protected_reverse_sequence_can_resume(self):
        for operation in ('next(iterator)', 'iterator.__length_hint__()',
                          'iterator.__setstate__(0)'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    lock = threading.Lock()
                    with lock:
                        source = lock.protect(Sequence())
                        iterator = reversed(source)
                    with SuppressCrashReport():
                        try:
                            {operation}
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected sequence accessed')
                    with lock:
                        assert next(iterator) == 12
                        assert list(iterator) == [11, 10]
                ''')

    @threading_helper.requires_working_threading()
    def test_rejected_reduce_releases_builtin(self):
        for expression in ('iter(Sequence())', 'iter(Callable(), None)'):
            with self.subTest(expression=expression):
                self.run_script(f'''
                    import sys
                    boxes = tuple(threading.TransferBox({expression})
                                  for _ in range(50))
                    results = SynchronizedList()
                    def worker():
                        for box in boxes:
                            try:
                                box.claim().__reduce__()
                            except IllegalThreadAccessException:
                                results.append('denied')
                            except BaseException as exc:
                                results.append((type(exc).__name__, str(exc)))
                            else:
                                results.append('foreign reference acquired')
                    thread = threading.Thread(target=worker, group=threading.ThreadGroup())
                    before = sys.getrefcount(iter)
                    thread.start()
                    thread.join()
                    after = sys.getrefcount(iter)
                    assert list(results) == ['denied'] * 50, list(results)
                    assert before == after, (before, after)
                ''')

    def test_callable_iterator_state_published_before_cleanup(self):
        self.run_script('''
            observed = []
            class Sentinel:
                def __del__(self):
                    observed.append(iterator.__reduce__()[2])
            def callback(): return 1
            iterator = iter(callback, Sentinel(), stop_exception=ValueError)
            iterator.__setstate__(((2,), KeyError))
            assert observed == [((2,), KeyError)], observed
            assert next(iterator) == 1
        ''')

    @threading_helper.requires_working_threading()
    def test_callable_iterator_parallel_state(self):
        self.run_script('''
            def callback(): return 1
            iterator = iter(callback, 0, stop_exception=ValueError)
            barrier = threading.Barrier(2)
            results = SynchronizedList()
            def reset():
                try:
                    barrier.wait(timeout=SHORT_TIMEOUT)
                    for _ in range(1000):
                        iterator.__setstate__(((2,), KeyError))
                        iterator.__setstate__(((0,), ValueError))
                    results.append('reset')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
            def consume():
                try:
                    barrier.wait(timeout=SHORT_TIMEOUT)
                    for _ in range(1000):
                        assert next(iterator) == 1
                        state = iterator.__reduce__()[2]
                        assert state in (((2,), KeyError), ((0,), ValueError)), state
                    results.append('consumed')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
            threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                       for target in (reset, consume)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            assert sorted(results) == ['consumed', 'reset'], list(results)
        ''')

    @threading_helper.requires_working_threading()
    def test_callable_iterator_parallel_exhaustion(self):
        self.run_script('''
            barrier = threading.Barrier(2)
            results = SynchronizedList()
            def callback():
                barrier.wait(timeout=SHORT_TIMEOUT)
                return 1
            iterator = iter(callback, 1)
            def worker():
                try:
                    results.append(next(iterator, 'exhausted'))
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))
            threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                       for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            assert list(results) == ['exhausted', 'exhausted'], list(results)
            assert next(iterator, 'still exhausted') == 'still exhausted'
        ''')


if __name__ == '__main__':
    unittest.main()
