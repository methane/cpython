"""ThreadGroup scheduling foundations from PEP 805."""

import gc
import sys
import threading
import unittest
import weakref

from test import support
from test.support import import_helper, os_helper, script_helper, threading_helper


threading_helper.requires_working_threading(module=True)


class ThreadGroupTests(unittest.TestCase):
    def test_main_group_lifetime(self):
        script_helper.assert_python_ok('-c', '''
import _testinternalcapi
_testinternalcapi.check_main_group_lifetime()
''')

    def test_group_biased_refcount(self):
        owner = threading.ThreadGroup("bias owner")
        foreign = threading.ThreadGroup("foreign bias")
        internal = import_helper.import_module("_testinternalcapi")
        self.assertTrue(internal.threadgroup_refcount_probe(owner, foreign))

    def test_local_refcount_overflow(self):
        internal = import_helper.import_module("_testinternalcapi")
        internal.test_threadgroup_refcount_overflow()

    @support.refcount_test
    @unittest.skipUnless(hasattr(sys, 'gettotalrefcount'), 'requires Py_REF_DEBUG')
    def test_thread_reference_totals(self):
        script_helper.assert_python_ok('-c', '''
import gc
import sys
import threading
import _testinternalcapi as internal

gc.disable()
for group in (sys.main_thread_group, threading.ThreadGroup('reference totals')):
    for clear_elsewhere in (False, True):
        internal.threadgroup_reftotal_probe(group, clear_elsewhere)
''')

    @support.refcount_test
    @unittest.skipUnless(hasattr(sys, 'gettotalrefcount'), 'requires Py_REF_DEBUG')
    @unittest.skipUnless(support.has_fork_support, 'requires fork')
    def test_thread_reference_totals_after_fork(self):
        script_helper.assert_python_ok('-c', '''
import gc
import os
import _testinternalcapi as internal

gc.disable()
pid = internal.threadgroup_reftotal_fork_probe(os.fork)
if pid == 0:
    os._exit(0)
_, status = os.waitpid(pid, 0)
assert os.waitstatus_to_exitcode(status) == 0, status
''')

    def test_thread_local_freelists(self):
        internal = import_helper.import_module('_testinternalcapi')
        for group in (sys.main_thread_group, threading.ThreadGroup('allocation')):
            for clear_elsewhere in (False, True):
                with self.subTest(group=group, clear_elsewhere=clear_elsewhere):
                    internal.threadgroup_freelist_probe(group, clear_elsewhere)

    def test_qsbr_reclamation(self):
        internal = import_helper.import_module('_testinternalcapi')
        def probe():
            return None

        modes = ('quiescent', 'detach', 'eval breaker', 'gc', 'thread exit',
                 'detached producer', 'allocation failure', 'code extra growth')
        for group in (sys.main_thread_group, threading.ThreadGroup('QSBR')):
            for mode, name in enumerate(modes):
                with self.subTest(group=group, mode=name):
                    internal.threadgroup_qsbr_probe(group, mode, probe.__code__)

    def test_qsbr_thread_state_lifetime(self):
        internal = import_helper.import_module('_testinternalcapi')
        internal.test_qsbr_thread_states()

    @unittest.skipUnless(support.with_mimalloc(), 'requires mimalloc')
    def test_thread_local_allocation_heaps(self):
        for allocator in ('mimalloc', 'mimalloc_debug'):
            with self.subTest(allocator=allocator):
                script_helper.assert_python_ok('-c', '''
import gc
import sys
import threading
import _testinternalcapi as internal
from test import support

gc.disable()
internal.test_reentrant_allocation_heap()
for group in (sys.main_thread_group, threading.ThreadGroup('allocation heap')):
    before, live, abandoned, freed = internal.threadgroup_allocation_probe(
        group, sys.getallocatedblocks)
    # Include allocations in another native thread, and keep counting them
    # after that thread exits while their owning tuple is still alive.
    if support.with_pymalloc():
        assert live - before >= 4096, (before, live)
        assert abandoned - before >= 4096, (before, abandoned)
        assert freed - before < 128, (before, freed)
    else:
        # Allocation accounting is unavailable in --without-pymalloc builds.
        # The native probe still validates contents and cross-thread freeing.
        assert (before, live, abandoned, freed) == (0, 0, 0, 0)
''', PYTHONMALLOC=allocator)

    def test_internal_world_stop(self):
        internal = import_helper.import_module('_testinternalcapi')
        for group in (sys.main_thread_group, threading.ThreadGroup('world stop')):
            for create_during_stop in (False, True):
                with self.subTest(group=group, create_during_stop=create_during_stop):
                    internal.threadgroup_world_stop_probe(group, create_during_stop)

    def test_gc_world_stop_phases(self):
        internal = import_helper.import_module('_testinternalcapi')
        internal.test_gc_world_stop()
        observed = []
        debug_refs = []

        def record(phase):
            observed.append((phase, internal.threadgroup_world_is_stopped()))
            # These APIs acquire the GC state lock and allocate their results.
            # Callbacks, finalizers and debug output must run without that lock.
            gc.set_threshold(*gc.get_threshold())
            gc.get_count()
            gc.get_stats()
            gc.isenabled()

        class Cycle:
            def __del__(self):
                record('finalizer')

        def callback(phase, info):
            record(phase)

        class DebugOutput:
            def write(self, text):
                record('debug')
                debug_refs.append((ref() is None,
                                   any(phase == 'weakref' for phase, _ in observed)))

        value = Cycle()
        value.cycle = value
        ref = weakref.ref(value, lambda ref: record('weakref'))
        debug = gc.get_debug()
        stderr = sys.stderr
        gc.callbacks.append(callback)
        try:
            sys.stderr = DebugOutput()
            gc.set_debug(gc.DEBUG_COLLECTABLE)
            del value
            gc.collect()
        finally:
            gc.set_debug(debug)
            sys.stderr = stderr
            gc.callbacks.remove(callback)
        self.assertIsNone(ref())
        self.assertEqual({phase for phase, stopped in observed},
                         {'start', 'stop', 'weakref', 'finalizer', 'debug'})
        self.assertFalse(any(stopped for phase, stopped in observed), observed)
        # Debug output can execute Python too. By then the callback-bearing
        # weakref must be dead, but its callback must still be pending.
        self.assertTrue(debug_refs)
        self.assertEqual(set(debug_refs), {(True, False)})

    def test_gc_introspection_world_stop(self):
        internal = import_helper.import_module('_testinternalcapi')
        for callback in (gc.get_referrers, gc.get_referents):
            with self.subTest(callback=callback):
                internal.gc_traversal_world_stop_probe(callback)
        internal.test_gc_visit_world_stop()
        with support.disable_gc():
            internal.test_gc_visit_world_stop()

    @support.nomemtest
    def test_gc_introspection_memory_error(self):
        script_helper.assert_python_ok('-c', '''
import gc
import _testcapi
import _testinternalcapi as internal

gc.disable()
target = []
referrers = [[target] for _ in range(256)]
for query, args in ((gc.get_objects, ()), (gc.get_referrers, (target,))):
    failures = 0
    for start in range(32):
        result = None
        _testcapi.set_nomemory(start, start + 1)
        try:
            result = query(*args)
        except MemoryError:
            failures += 1
        finally:
            _testcapi.remove_mem_hooks()
        assert not internal.threadgroup_world_is_stopped()
        del result
    # Exercise failure both in creating the result and in growing it.
    assert failures >= 2, (query, failures)
''')

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
