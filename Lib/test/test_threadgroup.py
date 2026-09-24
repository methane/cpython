"""Tests for the PEP 805 ThreadGroup scheduler."""

import gc
import sys
import threading
import unittest

from test import support
from test.support import SHORT_TIMEOUT, os_helper, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ThreadGroupTests(unittest.TestCase):
    def test_default_context_compatibility(self):
        assert_python_ok('-c', '''
import contextvars
import sys
import threading
from test.support import threading_helper

assert sys.flags.thread_inherit_context == 0
assert sys.flags.context_aware_warnings == 0
value = contextvars.ContextVar('value', default=None)
value.set('parent')
results = []
def worker():
    results.append(value.get())
thread = threading.Thread(target=worker)
with threading_helper.start_threads([thread]):
    pass
assert results == [None], results
assert value.get() == 'parent'
''')

    def test_collect_foreign_extension_state(self):
        # GC visitors need the module state even when the collecting group
        # cannot acquire the module itself.
        internal = import_module('_testinternalcapi')
        self.assertIs(internal.__shareable__, threading.Shareable.LOCAL)
        import_module('_locale')
        class Payload:
            __slots__ = ('value',)
        payload = Payload()
        payload.value = 42
        collect = gc.collect
        internal.object_declare_synchronized(collect)
        results = threading.Channel()

        def worker():
            collect()
            results.put(True)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertEqual(payload.value, 42)

    def test_owner_wrapper_identity(self):
        internal = import_module('_testinternalcapi')
        owner_id = internal.object_owner_id
        resolve = internal.threadgroup_from_owner_id
        for helper in (owner_id, resolve):
            internal.object_declare_synchronized(helper)
        self.assertIs(resolve(owner_id([])), sys.main_thread_group)
        results = threading.Channel()
        group = threading.ThreadGroup('owner')

        def worker():
            owner = owner_id([])
            results.put(resolve(owner) is group)
            results.put(owner)

        thread = threading.Thread(target=worker, group=group)
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(resolve(results.get()), group)

    def test_owner_wrapper_reconstruction(self):
        internal = import_module('_testinternalcapi')
        owner_id = internal.object_owner_id
        internal.object_declare_synchronized(owner_id)
        for name in (None, '', 'retired\0\ud800\U0001f40d'):
            with self.subTest(name=name):
                results = threading.Channel()
                def create(results=results):
                    value = []
                    results.put((value, owner_id(value)))
                thread = threading.Thread(target=create,
                                          group=threading.ThreadGroup(name))
                with threading_helper.start_threads([thread]):
                    pass
                del thread
                gc.collect()
                holder = results.get()
                owner = holder[1]
                group = internal.threadgroup_from_owner_id(owner)
                self.assertEqual(group.name, name)
                self.assertIs(group.__shareable__, threading.Shareable.IMMUTABLE)
                self.assertIs(internal.threadgroup_from_owner_id(owner), group)

                def consume(holder, results):
                    holder[0].append(42)
                    results.put(holder[0][0])
                    results.put(threading.current_thread().group)
                thread = threading.Thread(target=consume, args=(holder, results),
                                          group=group)
                with threading_helper.start_threads([thread]):
                    pass
                self.assertEqual(results.get(), 42)
                self.assertIs(results.get(), group)
                with self.assertRaises(IllegalThreadAccessException):
                    holder[0]

    def test_owner_wrapper_concurrent_reconstruction(self):
        internal = import_module('_testinternalcapi')
        owner_id = internal.object_owner_id
        resolve = internal.threadgroup_from_owner_id
        for helper in (owner_id, resolve):
            internal.object_declare_synchronized(helper)
        results = threading.Channel()
        def create():
            results.put(owner_id([]))
        thread = threading.Thread(target=create,
                                  group=threading.ThreadGroup('retired'))
        with threading_helper.start_threads([thread]):
            pass
        del thread
        gc.collect()
        owner = results.get()
        barrier = threading.Barrier(4, timeout=SHORT_TIMEOUT)
        def lookup():
            barrier.wait()
            results.put(resolve(owner))
        threads = [threading.Thread(target=lookup, group=threading.ThreadGroup())
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        group = results.get()
        self.assertEqual(group.name, 'retired')
        for _ in range(3):
            self.assertIs(results.get(), group)

    def test_owner_lookup_after_thread_and_wrapper_exit(self):
        internal = import_module('_testinternalcapi')
        owner_id = internal.object_owner_id
        internal.object_declare_synchronized(owner_id)
        results = threading.Channel()

        def create():
            value = []
            results.put((value, owner_id(value)))

        thread = threading.Thread(target=create, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        del thread
        gc.collect()
        holder = results.get()
        owner = holder[1]
        self.assertNotEqual(owner, owner_id([]))
        self.assertTrue(internal.threadgroup_owner_exists(owner))
        # Finding the owner must not grant this group access to its objects.
        with self.assertRaises(IllegalThreadAccessException):
            holder[0]

    def test_owner_lookup_excludes_mutex_ids(self):
        internal = import_module('_testinternalcapi')
        self.assertTrue(internal.threadgroup_owner_exists(
            internal.object_owner_id([])))
        self.assertFalse(internal.threadgroup_owner_exists(0))
        lock = threading.Lock()
        with lock:
            value = lock.protect([])
            owner = internal.object_owner_id(value)
            self.assertFalse(internal.threadgroup_owner_exists(owner))

    def test_owner_lookup_is_interpreter_local(self):
        interpreters = import_module('_interpreters')
        internal = import_module('_testinternalcapi')
        owner = internal.object_owner_id([])
        interp = interpreters.create()
        try:
            result = interpreters.run_string(interp, f'''
import _testinternalcapi as internal
assert not internal.threadgroup_owner_exists({owner})
assert internal.threadgroup_owner_exists(internal.object_owner_id([]))
''')
            self.assertIsNone(result, result)
        finally:
            interpreters.destroy(interp)
        self.assertTrue(internal.threadgroup_owner_exists(owner))

    def test_sleep_across_groups(self):
        from time import sleep
        results = threading.Channel()
        def worker():
            try:
                sleep(0)
                sleep(0.001)
                try:
                    sleep(-1)
                except ValueError:
                    pass
                else:
                    raise AssertionError('negative timeout accepted')
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put('ok')
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'ok')
        self.assertIs(sleep.__shareable__, threading.Shareable.SYNCHRONIZED)

    def test_names_across_groups(self):
        results = threading.Channel()
        def worker():
            for _ in range(100):
                results.put(threading._newname('parallel-%d'))
        threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        names = [results.get() for _ in range(400)]
        self.assertEqual(len(set(names)), 400)
        self.assertTrue(all(name.startswith('parallel-') for name in names))

    def test_native_thread_handle_state(self):
        import _thread
        internal = import_module('_testinternalcapi')
        handles = [_thread._ThreadHandle(),
                   _thread._make_thread_handle(_thread.get_ident()),
                   threading.current_thread()._os_thread_handle]
        try:
            for handle in handles:
                self.assertIs(handle.__shareable__, threading.Shareable.SYNCHRONIZED)
                self.assertEqual(internal.object_owner_id(handle), 0)
                self.assertIs(internal.object_check_access(handle), handle)
                self.assertIs(threading.TransferBox(handle).claim(), handle)
            with self.assertRaises(TypeError):
                class Subclass(_thread._ThreadHandle):
                    pass
        finally:
            handles[1]._set_done()

    def test_native_thread_handle_parallel_join(self):
        import _thread
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        ready = threading.Event()
        release = threading.Event()
        results = threading.Channel()
        def target():
            ready.set()
            release.wait(timeout=SHORT_TIMEOUT)
        with threading_helper.wait_threads_exit():
            handle = _thread.start_joinable_thread(target, group=threading.ThreadGroup())
            self.assertTrue(ready.wait(timeout=SHORT_TIMEOUT))
            self.assertIs(handle.__shareable__, threading.Shareable.SYNCHRONIZED)
            barrier = threading.Barrier(4)
            def joiner():
                shared = check_access(handle)
                assert shared.ident != 0
                assert '_ThreadHandle' in repr(shared)
                assert not shared.is_done()
                shared.join(0)
                barrier.wait(timeout=SHORT_TIMEOUT)
                release.set()
                shared.join(SHORT_TIMEOUT)
                assert shared.is_done()
                shared.join(0)
                results.put(True)
            threads = [threading.Thread(target=joiner, group=threading.ThreadGroup())
                       for _ in range(4)]
            try:
                with threading_helper.start_threads(threads):
                    pass
            finally:
                release.set()
                handle.join(SHORT_TIMEOUT)
            for _ in threads:
                self.assertTrue(results.get())

    def test_name(self):
        group = threading.ThreadGroup('workers')
        self.assertEqual(group.name, 'workers')
        self.assertEqual(repr(group), "<ThreadGroup 'workers'>")
        self.assertIsNone(threading.ThreadGroup().name)
        with self.assertRaises(AttributeError):
            group.name = 'new name'
        with self.assertRaises(TypeError):
            threading.ThreadGroup(42)

    def test_main_group(self):
        import types
        import _thread
        self.assertIs(type(sys), type(_thread))
        self.assertIsInstance(_thread, types.ModuleType)
        group = sys.main_thread_group
        self.assertIs(threading.main_thread().group, group)
        self.assertEqual(group.name, 'Main')
        with self.assertRaises(AttributeError):
            sys.main_thread_group = threading.ThreadGroup()
        with self.assertRaises(AttributeError):
            del sys.main_thread_group
        try:
            # Access must keep returning the interpreter's group even if a
            # module dictionary is edited directly, including after warmup.
            for _ in range(100):
                self.assertIs(sys.main_thread_group, group)
            sys.__dict__['main_thread_group'] = None
            for _ in range(100):
                self.assertIs(sys.main_thread_group, group)
        finally:
            sys.__dict__['main_thread_group'] = group
        with os_helper.EnvironmentVarGuard() as env:
            env.unset('PYTHON_PARALLEL')
            self.assertIs(threading.Thread().group, group)

    def test_group_argument(self):
        group = threading.ThreadGroup()
        thread = threading.Thread(group=group)
        self.assertIs(thread.group, group)
        with self.assertRaises(AttributeError):
            thread.group = threading.ThreadGroup()
        with self.assertRaises(AttributeError):
            del thread.group
        for invalid in (1, 'group', object()):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    threading.Thread(group=invalid)

    def test_current_group(self):
        import _thread
        group = threading.ThreadGroup('worker')
        results = SynchronizedList()

        def work():
            results.append((threading.current_thread().group,
                            _thread._current_thread_group()))

        thread = threading.Thread(group=group, target=work)
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results, [(group, group)])

    def test_flags_snapshots_across_groups(self):
        before = sys.flags
        before_limit = before.int_max_str_digits
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        results = threading.Channel()

        def worker():
            try:
                snapshot = sys.flags
                assert snapshot.ignore_environment in (0, 1)
                sys.set_int_max_str_digits(0)
                results.put(('ok', snapshot, sys.flags))
            except BaseException as exc:
                results.put(('error', str(exc)))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        result = results.get()
        self.assertEqual(result[0], 'ok', result)
        _, snapshot, updated = result
        self.assertIs(snapshot, before)
        self.assertIs(updated, sys.flags)
        self.assertIsNot(updated, before)
        self.assertEqual(before.int_max_str_digits, before_limit)
        self.assertEqual(updated.int_max_str_digits, 0)
        for flags in (before, updated):
            self.assertIs(flags.__shareable__, threading.Shareable.IMMUTABLE)
            with self.assertRaises(AttributeError):
                flags.ignore_environment = 1

    def test_default_group_is_not_inherited(self):
        results = SynchronizedList()

        def work():
            results.append(threading.Thread().group)

        with os_helper.EnvironmentVarGuard() as env:
            env.unset('PYTHON_PARALLEL')
            thread = threading.Thread(group=threading.ThreadGroup(), target=work)
            with threading_helper.start_threads([thread]):
                pass
        self.assertEqual(results, [sys.main_thread_group])

    def test_default_group_observes_environment_changes(self):
        barrier = threading.Barrier(2, timeout=SHORT_TIMEOUT)
        results = threading.Channel()
        parent_group = threading.ThreadGroup()
        def worker():
            for _ in range(4):
                barrier.wait()
                results.put(threading.Thread().group)
                barrier.wait()
        with os_helper.EnvironmentVarGuard() as env:
            thread = threading.Thread(target=worker, group=parent_group)
            with threading_helper.start_threads([thread]):
                for value in ('', '0', '1', 'enabled'):
                    env['PYTHON_PARALLEL'] = value
                    barrier.wait()
                    barrier.wait()
            groups = [results.get() for _ in range(4)]
        self.assertIs(groups[0], sys.main_thread_group)
        self.assertIs(groups[1], sys.main_thread_group)
        if sys.flags.ignore_environment:
            self.assertTrue(all(group is sys.main_thread_group for group in groups))
            return
        for group in groups[2:]:
            self.assertIsNot(group, sys.main_thread_group)
            self.assertIsNot(group, parent_group)
        self.assertIsNot(groups[2], groups[3])

    def test_default_group_uses_current_environment_mapping(self):
        import os
        original = os.environ
        results = threading.Channel()
        def worker():
            results.put(threading.Thread().group)
        try:
            os.environ = SynchronizedDict(PYTHON_PARALLEL='1')
            thread = threading.Thread(target=worker, group=threading.ThreadGroup())
            with threading_helper.start_threads([thread]):
                pass
            group = results.get()
        finally:
            os.environ = original
        if sys.flags.ignore_environment:
            self.assertIs(group, sys.main_thread_group)
        else:
            self.assertIsNot(group, sys.main_thread_group)

    def test_environment_storage_is_shared(self):
        import os
        self.assertIs(type(os.__dict__), SynchronizedDict)
        self.assertIs(os.environ.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertIs(type(os.environ._data), SynchronizedDict)
        if os.supports_bytes_environ:
            self.assertIs(os.environb._data, os.environ._data)
            self.assertIs(os.environb.__shareable__, threading.Shareable.SYNCHRONIZED)

    @support.requires_subprocess()
    def test_environment_module_reload(self):
        assert_python_ok('-c', '''
import importlib
import os
import threading
namespace = os.__dict__
importlib.reload(os)
assert os.__dict__ is namespace
assert type(namespace) is SynchronizedDict
assert os.environ.__shareable__ is threading.Shareable.SYNCHRONIZED
assert type(os.environ._data) is SynchronizedDict
''')

    def test_low_level_group_validation(self):
        import _thread
        with self.assertRaises(TypeError):
            _thread.start_joinable_thread(lambda: None, group=object())

    def test_main_group_in_subinterpreter(self):
        _interpreters = import_module('_interpreters')
        interp = _interpreters.create()
        self.addCleanup(_interpreters.destroy, interp)
        result = _interpreters.run_string(interp, f'''
import sys
import threading
assert sys.main_thread_group is threading.current_thread().group
assert sys.main_thread_group.name == 'Main'
assert id(sys.main_thread_group) != {id(sys.main_thread_group)}
t = threading.Thread()
assert t.group is sys.main_thread_group
t.start()
t.join()
''')
        self.assertIsNone(result)

    def test_exception_releases_group(self):
        import types

        group = threading.ThreadGroup()
        reported = threading.Channel()

        def hook_template(args):
            reports.put(args.exc_type is ValueError)

        # The callback crosses groups; report an immutable result through a
        # shared namespace instead of installing a Main-owned bound method.
        hook = types.FunctionType(hook_template.__code__,
                                  SynchronizedDict(reports=reported))

        def fail():
            raise ValueError('test error')

        previous_hook = threading.excepthook
        threading.excepthook = hook
        try:
            thread = threading.Thread(group=group, target=fail)
            with threading_helper.start_threads([thread]):
                pass
            self.assertTrue(reported.get())
        finally:
            threading.excepthook = previous_hook
        results = SynchronizedList()
        thread = threading.Thread(group=group, target=lambda: results.append(1))
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results, [1])

    @support.requires_fork()
    @support.requires_subprocess()
    def test_group_after_fork(self):
        assert_python_ok('-c', '''
import os
import threading
import warnings
from test import support
from test.support import SHORT_TIMEOUT
group = threading.ThreadGroup('workers')
done = threading.Event()
thread = threading.Thread(group=group, target=done.wait)
thread.start()
try:
    with warnings.catch_warnings(action='ignore', category=DeprecationWarning):
        pid = os.fork()
    if pid == 0:
        thread = threading.Thread(group=group)
        thread.start()
        thread.join(SHORT_TIMEOUT)
        os._exit(int(thread.is_alive()))
    support.wait_process(pid, exitcode=0)
finally:
    done.set()
    thread.join()
''')

    def test_same_group_serializes(self):
        group = threading.ThreadGroup()
        barrier = threading.Barrier(4, timeout=SHORT_TIMEOUT)
        counter = SynchronizedList([0])

        def work():
            barrier.wait()
            for _ in range(10000):
                # Primitive arithmetic and list indexing have no scheduling
                # points. The back edge does, allowing the workers to switch.
                counter[0] += 1

        threads = [threading.Thread(group=group, target=work)
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(counter[0], 40000)

    @unittest.skipIf(support.Py_GIL_DISABLED is False, 'requires free threading')
    def test_extension_import_preserves_parallel_groups(self):
        import_module('_testmultiphase')
        import_module('_testinternalcapi')
        for name in (
            '_testsinglephase_no_gil_slot',
            '_testmultiphase_null_slots',
            '_test_from_modexport_gil_used',
            '_test_from_modexport_minimal_slots',
            '_test_from_modexport_create_nonmodule_gil_used',
        ):
            with self.subTest(name=name):
                assert_python_ok('-c', f'''
import importlib.machinery
import importlib.util
import sys
import threading
import types
import _testinternalcapi as internal
import _testmultiphase
from test.support import SHORT_TIMEOUT, threading_helper

assert not sys._is_gil_enabled()
name = {name!r}
loader = importlib.machinery.ExtensionFileLoader(name, _testmultiphase.__file__)
spec = importlib.util.spec_from_loader(name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
assert not sys._is_gil_enabled(), name
if name == '_testsinglephase_no_gil_slot':
    assert not module.gil_enabled_on_init
is_module = isinstance(module, types.ModuleType)
if is_module:
    assert module.__shareable__ is threading.Shareable.LOCAL

flags = bytearray(2)
wait_at_c_barrier = internal.wait_at_c_barrier
internal.object_declare_synchronized(flags)
internal.object_declare_synchronized(wait_at_c_barrier)
results = SynchronizedList([None, None])
def worker(index):
    if is_module:
        try:
            module.__name__
        except IllegalThreadAccessException:
            pass
        else:
            raise AssertionError('extension module became shareable')
    results[index] = wait_at_c_barrier(flags, index, SHORT_TIMEOUT)
threads = [threading.Thread(group=threading.ThreadGroup(),
                            target=worker, args=(index,))
           for index in range(2)]
with threading_helper.start_threads(threads):
    pass
assert results == [True, True], results
''')

    @unittest.skipIf(support.Py_GIL_DISABLED is False, 'requires free threading')
    def test_different_groups_execute_in_parallel(self):
        if sys._is_gil_enabled():
            self.skipTest('requires a disabled GIL')
        _testinternalcapi = import_module('_testinternalcapi')
        flags = bytearray(2)
        wait_at_c_barrier = _testinternalcapi.wait_at_c_barrier
        # Only the native helper accesses these bytes, using atomic operations;
        # the exported buffer keeps their storage stable for both callers.
        _testinternalcapi.object_declare_synchronized(flags)
        _testinternalcapi.object_declare_synchronized(wait_at_c_barrier)
        results = SynchronizedList([None, None])

        def work(index):
            results[index] = wait_at_c_barrier(
                flags, index, SHORT_TIMEOUT)

        threads = [threading.Thread(group=threading.ThreadGroup(),
                                    target=work, args=(index,))
                   for index in range(2)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(results, [True, True])

    def test_wait_releases_group(self):
        group = threading.ThreadGroup()
        ready = threading.Event()
        done = threading.Event()
        results = SynchronizedList()

        def waiter():
            ready.set()
            results.append(done.wait(SHORT_TIMEOUT))

        def notifier():
            if ready.wait(SHORT_TIMEOUT):
                done.set()

        threads = [threading.Thread(group=group, target=target)
                   for target in (waiter, notifier)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(results, [True])

    def test_collect_while_other_group_waits(self):
        group = threading.ThreadGroup()
        ready = threading.Barrier(3, timeout=SHORT_TIMEOUT)
        done = threading.Event()

        def work():
            ready.wait()
            done.wait(SHORT_TIMEOUT)

        threads = [threading.Thread(group=group, target=work)
                   for _ in range(2)]
        with threading_helper.start_threads(threads, unlock=done.set):
            ready.wait()
            gc.collect()

    def test_group_survives_thread_shutdown(self):
        group = threading.ThreadGroup()
        for _ in range(3):
            thread = threading.Thread(group=group, target=gc.collect)
            with threading_helper.start_threads([thread]):
                pass
            del thread
            gc.collect()

    @support.requires_subprocess()
    def test_parallel_environment(self):
        code = '''
import sys
import threading
assert threading.main_thread().group is sys.main_thread_group
a = threading.Thread()
b = threading.Thread()
assert a.group is not b.group
assert a.group is not sys.main_thread_group
'''
        assert_python_ok('-c', code, PYTHON_PARALLEL='1')
        code = '''
import sys
import threading
assert threading.Thread().group is sys.main_thread_group
'''
        assert_python_ok('-c', code, PYTHON_PARALLEL='0')
        assert_python_ok('-E', '-c', code, PYTHON_PARALLEL='1')


if __name__ == '__main__':
    unittest.main()
