"""ThreadGroup scheduling foundations from PEP 805."""

import gc
import sys
import threading
import unittest

from test import support
from test.support import import_helper, os_helper, script_helper, threading_helper


threading_helper.requires_working_threading(module=True)


class ThreadGroupTests(unittest.TestCase):
    def test_default_context_compatibility(self):
        script_helper.assert_python_ok('-c', '''
import contextvars
import sys
import threading
from test.support import threading_helper
assert sys.flags.thread_inherit_context == 0
assert sys.flags.context_aware_warnings == 0
value = contextvars.ContextVar('value', default=None)
value.set('parent')
results = []
with threading_helper.start_threads([
        threading.Thread(target=lambda: results.append(value.get()))]):
    pass
assert results == [None], results
assert value.get() == 'parent'
''')

    @unittest.skipUnless(support.Py_GIL_DISABLED, 'requires parallel runtime')
    def test_extension_import_preserves_scheduling(self):
        import_helper.import_module('_testmultiphase')
        for name in (
            '_testsinglephase_no_gil_slot',
            '_testmultiphase_null_slots',
            '_test_from_modexport_gil_used',
            '_test_from_modexport_minimal_slots',
            '_test_from_modexport_create_nonmodule_gil_used',
        ):
            with self.subTest(name=name):
                script_helper.assert_python_ok('-c', f'''
import importlib.machinery
import importlib.util
import sys
import _testmultiphase
assert not sys._is_gil_enabled()
name = {name!r}
loader = importlib.machinery.ExtensionFileLoader(name, _testmultiphase.__file__)
spec = importlib.util.spec_from_loader(name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
assert not sys._is_gil_enabled(), name
if name == '_testsinglephase_no_gil_slot':
    assert not module.gil_enabled_on_init
''')

    def test_main_group(self):
        main = sys.main_thread_group
        self.assertIsInstance(main, threading.ThreadGroup)
        self.assertEqual(main.name, 'Main')
        self.assertIs(threading.current_thread().group, main)
        self.assertIs(threading.Thread().group, main)
        with self.assertRaises(AttributeError):
            sys.main_thread_group = None
        with self.assertRaises(AttributeError):
            del sys.main_thread_group

    def test_group_metadata(self):
        group = threading.ThreadGroup('workers')
        self.assertEqual(group.name, 'workers')
        self.assertEqual(repr(group), "<ThreadGroup 'workers'>")
        self.assertEqual(repr(threading.ThreadGroup()), '<ThreadGroup>')
        with self.assertRaises(AttributeError):
            group.name = 'replacement'
        with self.assertRaises(TypeError):
            threading.ThreadGroup(1)
        with self.assertRaises(TypeError):
            threading.Thread(group=object())
        thread = threading.Thread(group=group)
        self.assertIs(thread.group, group)
        with self.assertRaises(AttributeError):
            thread.group = sys.main_thread_group

    def test_group_identity_in_worker(self):
        group = threading.ThreadGroup('worker')
        observed = []
        def worker():
            import _thread
            observed.append(threading.current_thread().group)
            observed.append(_thread._current_thread_group())
        thread = threading.Thread(group=group, target=worker)
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(observed, [group, group])

    def test_main_group_serializes(self):
        counter = [0]
        barrier = threading.Barrier(4, timeout=support.SHORT_TIMEOUT)
        def increment():
            barrier.wait()
            for _ in range(10000):
                counter[0] += 1
        threads = [threading.Thread(target=increment) for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(counter, [40000])

    @unittest.skipUnless(support.Py_GIL_DISABLED, 'requires parallel runtime')
    def test_different_groups_execute_in_parallel(self):
        if sys._is_gil_enabled():
            self.skipTest('requires a disabled global GIL')
        internal = import_helper.import_module('_testinternalcapi')
        flags = bytearray(2)
        results = [None, None]
        def worker(index):
            # This native barrier retains execution rights, so interleaving
            # Python bytecode in one group cannot satisfy it.
            results[index] = internal.wait_at_c_barrier(
                flags, index, support.SHORT_TIMEOUT)
        threads = [threading.Thread(group=threading.ThreadGroup(),
                                    target=worker, args=(i,)) for i in range(2)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(results, [True, True])

    def test_wait_releases_group(self):
        group = threading.ThreadGroup()
        ready = threading.Event()
        done = threading.Event()
        observed = []
        def first():
            ready.set()
            observed.append(done.wait(support.SHORT_TIMEOUT))
        def second():
            observed.append(ready.wait(support.SHORT_TIMEOUT))
            done.set()
        threads = [threading.Thread(group=group, target=target)
                   for target in (first, second)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(observed, [True, True])

    def test_group_reuse(self):
        group = threading.ThreadGroup()
        observed = []
        for _ in range(4):
            thread = threading.Thread(group=group, target=lambda: observed.append(1))
            with threading_helper.start_threads([thread]):
                pass
            del thread
            gc.collect()
        self.assertEqual(observed, [1] * 4)

    def test_parallel_environment(self):
        for value in ('0', '1', '-1'):
            with self.subTest(value=value):
                with os_helper.EnvironmentVarGuard() as env:
                    env['PYTHON_PARALLEL'] = value
                    first, second = threading.Thread(), threading.Thread()
                if value == '0':
                    self.assertIs(first.group, sys.main_thread_group)
                    self.assertIs(second.group, first.group)
                else:
                    self.assertIsNot(first.group, sys.main_thread_group)
                    self.assertIsNot(first.group, second.group)
        script_helper.assert_python_ok('-E', '-c',
            'import sys, threading; '
            'assert threading.Thread().group is sys.main_thread_group',
            PYTHON_PARALLEL='1')

    @support.requires_fork()
    def test_fork(self):
        script_helper.assert_python_ok('-c', '''
import os
import threading
from test import support
from test.support import threading_helper
group = threading.ThreadGroup('child')
pid = os.fork()
if pid == 0:
    observed = []
    thread = threading.Thread(group=group, target=lambda: observed.append(1))
    thread.start()
    thread.join(support.SHORT_TIMEOUT)
    os._exit(0 if observed == [1] and not thread.is_alive() else 1)
support.wait_process(pid, exitcode=0)
''')


if __name__ == '__main__':
    unittest.main()
