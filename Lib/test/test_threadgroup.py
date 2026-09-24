"""ThreadGroup scheduling foundations from PEP 805."""

import gc
import sys
import threading
import unittest

from test import support
from test.support import import_helper, os_helper, script_helper, threading_helper


threading_helper.requires_working_threading(module=True)


class ThreadGroupTests(unittest.TestCase):
    def test_group_biased_refcount(self):
        owner = threading.ThreadGroup("bias owner")
        foreign = threading.ThreadGroup("foreign bias")
        internal = import_helper.import_module("_testinternalcapi")
        self.assertTrue(internal.threadgroup_refcount_probe(owner, foreign))

    def test_local_refcount_overflow(self):
        internal = import_helper.import_module("_testinternalcapi")
        internal.test_threadgroup_refcount_overflow()

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
        internal = import_helper.import_module('_testinternalcapi')
        group = threading.ThreadGroup('worker')
        self.assertEqual(internal.threadgroup_probe(
            (group, sys.main_thread_group), 0, support.SHORT_TIMEOUT),
            (True, True))

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

    def test_different_groups_execute_in_parallel(self):
        if sys._is_gil_enabled():
            self.skipTest('parallel substrate not enabled')
        internal = import_helper.import_module('_testinternalcapi')
        groups = (threading.ThreadGroup(), threading.ThreadGroup())
        self.assertEqual(internal.threadgroup_probe(
            groups, 1, support.SHORT_TIMEOUT), (True, True))

    def test_same_group_cannot_execute_in_parallel(self):
        internal = import_helper.import_module('_testinternalcapi')
        group = threading.ThreadGroup()
        result = internal.threadgroup_probe((group, group), 1, 0.01)
        self.assertEqual(sorted(result), [False, True])

    def test_wait_releases_group(self):
        internal = import_helper.import_module('_testinternalcapi')
        group = threading.ThreadGroup()
        self.assertEqual(internal.threadgroup_probe(
            (group, group), 2, support.SHORT_TIMEOUT), (True, True))

    def test_group_reuse(self):
        internal = import_helper.import_module('_testinternalcapi')
        group = threading.ThreadGroup()
        for _ in range(4):
            self.assertEqual(internal.threadgroup_probe(
                (group, group), 0, support.SHORT_TIMEOUT), (True, True))
            gc.collect()

    def test_native_probe_rejects_invalid_group(self):
        internal = import_helper.import_module('_testinternalcapi')
        with self.assertRaises(TypeError):
            internal.threadgroup_probe(
                (sys.main_thread_group, None), 0, support.SHORT_TIMEOUT)

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
import _testinternalcapi as internal
group = threading.ThreadGroup('child')
pid = os.fork()
if pid == 0:
    result = internal.threadgroup_probe(
        (group, group), 0, support.SHORT_TIMEOUT)
    os._exit(0 if result == (True, True) else 1)
support.wait_process(pid, exitcode=0)
''')


if __name__ == '__main__':
    unittest.main()
