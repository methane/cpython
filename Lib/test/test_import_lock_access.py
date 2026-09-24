"""Import lock ownership and deadlock detection across ThreadGroups."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ImportLockAccessTests(unittest.TestCase):
    PRELUDE = '''
import gc
import threading
import weakref
from test.support import SHORT_TIMEOUT, threading_helper
from test.test_importlib.util import import_importlib

bootstrap = import_importlib('importlib')[KIND]._bootstrap
get_lock = bootstrap._get_module_lock
Lock = bootstrap._ModuleLock
DeadlockError = bootstrap._DeadlockError
module_locks = bootstrap._module_locks
blocking_on = bootstrap._blocking_on
results = threading.Channel()
errors = SynchronizedList()

def worker(action):
    try:
        action()
    except BaseException as exc:
        errors.append((type(exc).__name__, str(exc)))

def run(*actions):
    threads = [threading.Thread(target=worker, args=(action,),
                                group=threading.ThreadGroup())
               for action in actions]
    with threading_helper.start_threads(threads):
        pass
    assert not errors, list(errors)
'''

    def run_script(self, script):
        for kind in ('Frozen', 'Source'):
            with self.subTest(kind=kind):
                assert_python_ok('-c', f'KIND = {kind!r}\n' + self.PRELUDE
                                 + textwrap.dedent(script))

    def test_lock_created_in_another_group(self):
        self.run_script('''
            lock = Lock('shared')
            def action():
                assert lock.acquire()
                assert lock.acquire()
                assert lock.locked()
                lock.release()
                assert lock.locked()
                lock.release()
                assert not lock.locked()
                results.put(repr(lock))
            run(action)
            assert results.get().startswith("_ModuleLock('shared')")
            assert not lock.locked()
        ''')

    def test_registry_reuses_lock_across_groups(self):
        self.run_script('''
            lock = get_lock('pep805_shared_lock')
            barrier = threading.Barrier(4, timeout=SHORT_TIMEOUT)
            count = SynchronizedList([0])
            def action():
                candidate = get_lock('pep805_shared_lock')
                assert candidate is lock
                barrier.wait()
                for _ in range(20):
                    candidate.acquire()
                    count[0] += 1
                    candidate.release()
            run(action, action, action, action)
            assert count[0] == 80
            assert not lock.locked()
        ''')

    def test_subclass_storage_remains_local(self):
        self.run_script('''
            class CustomLock(Lock):
                pass
            lock = CustomLock('custom')
            lock.extra = []
            assert lock.__shareable__ is threading.Shareable.LOCAL
            lock.acquire()
            lock.release()
            def action():
                try:
                    lock.acquire()
                except IllegalThreadAccessException:
                    results.put('denied')
                else:
                    raise AssertionError('subclass was implicitly shared')
            run(action)
            assert results.get() == 'denied'
        ''')

    def test_worker_created_lock_and_weak_lifetime(self):
        self.run_script('''
            def action():
                results.put(get_lock('pep805_worker_lock'))
            run(action)
            lock = results.get()
            assert get_lock('pep805_worker_lock') is lock
            lock.acquire()
            lock.release()
            ref = weakref.ref(lock)
            del lock
            gc.collect()
            assert ref() is None
            assert 'pep805_worker_lock' not in module_locks
        ''')

    def test_cross_group_deadlock_detection(self):
        self.run_script('''
            a = Lock('a')
            b = Lock('b')
            barrier = threading.Barrier(2, timeout=SHORT_TIMEOUT)
            def take_pair(first, second):
                first.acquire()
                try:
                    barrier.wait()
                    try:
                        second.acquire()
                    except DeadlockError:
                        results.put('deadlock')
                    else:
                        second.release()
                        results.put('acquired')
                finally:
                    first.release()
            def one():
                take_pair(a, b)
            def two():
                take_pair(b, a)
            run(one, two)
            outcomes = [results.get(), results.get()]
            assert 'deadlock' in outcomes, outcomes
            assert not a.locked() and not b.locked()
            gc.collect()
            assert not blocking_on.data
        ''')

    def test_foreign_local_registry_value_rejected(self):
        self.run_script('''
            class LocalCallback:
                def __call__(self):
                    raise AssertionError('foreign callback called')
            module_locks['pep805_foreign_lock'] = LocalCallback()
            def action():
                try:
                    get_lock('pep805_foreign_lock')
                except IllegalThreadAccessException:
                    results.put('denied')
                else:
                    raise AssertionError('foreign callback accepted')
            try:
                run(action)
                assert results.get() == 'denied'
            finally:
                del module_locks['pep805_foreign_lock']
        ''')


if __name__ == '__main__':
    unittest.main()
