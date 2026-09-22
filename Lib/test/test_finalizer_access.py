"""Finalizers must be able to access the local state they are cleaning up."""

import gc
import signal
import sys
import threading
import unittest

from test.support import Py_GIL_DISABLED, SHORT_TIMEOUT, script_helper, threading_helper


threading_helper.requires_working_threading(module=True)


class FinalizerAccessTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(signal, 'SIGUSR1') and
                         hasattr(signal, 'pthread_kill'),
                         'requires SIGUSR1 and pthread_kill')
    def test_cleanup_waits_after_join_interrupt(self):
        for kind in ('weakref', 'finalizer'):
            for cyclic in (False, True):
                for signals in (1, 3):
                    with self.subTest(kind=kind, cyclic=cyclic, signals=signals):
                        script_helper.assert_python_ok('-c', f"""
import gc
import signal
import sys
import threading
from weakref import ref as make_ref
from test.support import SHORT_TIMEOUT
import faulthandler

faulthandler.dump_traceback_later(SHORT_TIMEOUT + 5, exit=True)
gc.disable()
main_ident = threading.get_ident()
objects = threading.Channel()
references = threading.Channel()
started = threading.Event()
interrupted = threading.Event()
release = threading.Event()
later = threading.Event()
returned = threading.Event()
observed = SynchronizedList()
errors = SynchronizedList()
class CallbackInterrupt(Exception):
    pass
interrupt_refs = []

def on_signal(signum, frame):
    interrupted.set()
    error = CallbackInterrupt(len(interrupt_refs))
    interrupt_refs.append(make_ref(error))
    raise error
signal.signal(signal.SIGUSR1, on_signal)
sys.unraisablehook = lambda exc: errors.append(
    (exc.exc_type.__name__, exc.exc_value.args))

def create():
    def first(ref):
        started.set()
        assert release.wait(SHORT_TIMEOUT)
        observed.append('first')
    def second(ref):
        observed.append('second')
        later.set()
    if {kind!r} == 'weakref':
        class Payload:
            pass
    else:
        class Payload:
            def __del__(self):
                first(None)
    value = Payload()
    if {cyclic!r}:
        value.cycle = value
    if {kind!r} == 'weakref':
        references.put((make_ref(value, second), make_ref(value, first)))
    objects.put((value,))
producer = threading.Thread(target=create, group=threading.ThreadGroup())
producer.start()
producer.join(SHORT_TIMEOUT)
assert not producer.is_alive()
del producer
# Merge biased references before testing ordinary refcount destruction.
gc.collect()

def interrupt():
    assert started.wait(SHORT_TIMEOUT)
    for _ in range({signals!r}):
        interrupted.clear()
        signal.pthread_kill(main_ident, signal.SIGUSR1)
        assert interrupted.wait(SHORT_TIMEOUT)
    event = later if {kind!r} == 'weakref' else returned
    observed.append(('overlap', event.wait(0.2)))
    release.set()
monitor = threading.Thread(target=interrupt)
monitor.start()
objects.get()
gc.collect()
returned.set()
monitor.join(SHORT_TIMEOUT)
assert not monitor.is_alive()
expected = [('overlap', False), 'first']
if {kind!r} == 'weakref':
    expected.append('second')
assert list(observed) == expected, list(observed)
assert list(errors) == [('CallbackInterrupt', (0,))], list(errors)
gc.collect()
assert len(interrupt_refs) == {signals!r}
assert all(ref() is None for ref in interrupt_refs)
if {kind!r} == 'weakref':
    references.get()
faulthandler.cancel_dump_traceback_later()
""")

    def test_weakref_callback_owner_lifetime(self):
        from weakref import ref as make_ref

        objects = threading.Channel()
        refs = threading.Channel()
        observed = threading.Channel()

        def create():
            class Payload:
                pass
            local = []
            def callback(ref):
                local.append(ref() is None)
                observed.put(tuple(local))
            value = Payload()
            refs.put((make_ref(value, callback),))
            objects.put((value,))

        thread = threading.Thread(target=create, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        del thread
        objects.get()
        gc.collect()
        self.assertEqual(observed.get(), (True,))
        refs.get()
        gc.collect()
        with self.assertRaises(IndexError):
            observed.get()

    def test_weakref_callback_registration_group(self):
        for cyclic in (False, True):
            for synchronized in (False, True):
                with self.subTest(cyclic=cyclic, synchronized=synchronized):
                    script_helper.assert_python_ok('-c', f"""
import gc
import sys
import threading
from weakref import ref as make_ref
import _testinternalcapi as internal
from test.support import SHORT_TIMEOUT

gc.disable()
objects = threading.Channel()
refs = threading.Channel()
observed = SynchronizedList()
errors = SynchronizedList()
sys.unraisablehook = lambda exc: errors.append(exc.exc_type.__name__)
# Only this native test helper is shared; callbacks retain local closure state.
declare = internal.object_declare_synchronized
declare(declare)

@freeze
class Payload:
    pass

def create():
    local = []
    def make_callback(index):
        def callback(ref):
            assert ref() is None
            local.append(index)
            observed.append(tuple(local))
            if index == 3:
                raise ValueError('callback failure must not skip later callbacks')
        return callback
    value = Payload()
    if {cyclic!r}:
        value.cycle = value
    if {synchronized!r}:
        declare(value)
    references = tuple(make_ref(value, make_callback(i)) for i in range(4))
    refs.put(references)
    objects.put((value,))

thread = threading.Thread(target=create,
                          group=threading.ThreadGroup('weakref-owner'))
thread.start()
thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
del thread
# Drop the last external reference in Main, after the registration thread exits.
objects.get()
gc.collect()
assert list(errors) == ['ValueError'], list(errors)
assert list(observed) == [(3,), (3, 2), (3, 2, 1), (3, 2, 1, 0)], list(observed)
gc.collect()
assert len(observed) == 4
# The references must remain alive until after collection, without acquiring
# LOCAL weakrefs in Main.
refs.get()
""")

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_finalizer_deferred_until_world_restarts(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                script_helper.assert_python_ok('-c', f"""
import gc
import sys
import threading
import _testinternalcapi as internal
from test.support import SHORT_TIMEOUT

gc.disable()
observed = SynchronizedList()
world_is_stopped = internal.world_is_stopped
# This read-only test helper is safe to invoke from the owner group.
internal.object_declare_synchronized(world_is_stopped)
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.value = []
    def __del__(self):
        self.value.append(42)
        observed.append((world_is_stopped(), self.value[0]))

results = threading.Channel()
def create():
    results.put((Payload(),))
def take():
    return results.get()
if {foreign!r}:
    thread = threading.Thread(target=create, group=threading.ThreadGroup())
    thread.start()
    thread.join(SHORT_TIMEOUT)
    assert not thread.is_alive()
    del thread
else:
    create()
gc.collect()
internal.drop_while_world_stopped(take)
assert list(observed) == [(False, 42)], list(observed)
gc.collect()
assert list(observed) == [(False, 42)], list(observed)
""")

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_finalizers_in_process(self):
        import _testinternalcapi as internal
        observed = SynchronizedList()
        @freeze
        class Payload:
            def __del__(self):
                observed.append(internal.world_is_stopped())
        def create():
            # Exceed the bounded pending-call queue's capacity. These records
            # must survive independently until its safe execution checkpoint.
            return tuple(Payload() for _ in range(1000))
        internal.drop_many_while_world_stopped(create)
        self.assertEqual(list(observed), [False] * 1000)
        gc.collect()
        self.assertEqual(len(observed), 1000)

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_weakref_callback(self):
        import weakref
        import _testinternalcapi as internal
        observed = []
        refs = []
        class Payload:
            pass
        def callback(ref):
            observed.append((internal.world_is_stopped(), ref() is None))
        def create():
            value = Payload()
            refs.append(weakref.ref(value, callback))
            return value
        internal.drop_while_world_stopped(create)
        self.assertEqual(observed, [(False, True)])
        self.assertIsNone(refs[0]())
        gc.collect()
        self.assertEqual(observed, [(False, True)])

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_native_destructor(self):
        import _testinternalcapi as internal
        observed = []
        def callback():
            observed.append(internal.world_is_stopped())
        def create():
            capsule = internal.make_callback_capsule(callback)
            self.assertFalse(gc.is_tracked(capsule))
            return capsule
        internal.drop_while_world_stopped(create)
        self.assertEqual(observed, [False])
        gc.collect()
        self.assertEqual(observed, [False])

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_explicit_finalizer(self):
        import _testinternalcapi as internal
        observed = []
        class Payload:
            def __del__(self):
                observed.append(internal.world_is_stopped())
        value = Payload()
        internal.finalize_while_world_stopped(value)
        self.assertEqual(observed, [False])
        self.assertTrue(gc.is_finalized(value))
        internal.finalize_while_world_stopped(value)
        del value
        gc.collect()
        self.assertEqual(observed, [False])

    @unittest.skipUnless(hasattr(sys, 'getobjects'), 'requires trace-refs build')
    def test_deferred_trace_refs_tracking(self):
        _, _, err = script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
class Payload:
    def __del__(self):
        observed.append(sum(obj is self for obj in sys.getobjects(0, Payload)))
with sys.monitoring.StopTheWorld:
    value = internal.finalize_deferred_deallocation(Payload)
    assert observed == [1], observed
    assert sys.getobjects(0, Payload) == [value]
ref = weakref.ref(value)
del value
gc.collect()
assert ref() is None
assert sys.getobjects(0, Payload) == []
assert observed == [1], observed

observed.clear()
types = []
def callback(value):
    kind = type(value)
    types.append(weakref.ref(kind))
    observed.append(sum(obj is value for obj in sys.getobjects(0, kind)))
def create():
    return internal.make_nongc_finalizer(callback)
with sys.monitoring.StopTheWorld:
    internal.drop_while_world_stopped(create)
assert observed == [1], observed
gc.collect()
assert types[0]() is None
""")
        self.assertEqual(err, b'')

    def test_deferred_nongc_explicit_finalizer(self):
        for debugger in ((False, True) if Py_GIL_DISABLED else (True,)):
            for no_memory in (False, True):
                with self.subTest(debugger=debugger, no_memory=no_memory):
                    _, _, err = script_helper.assert_python_ok('-c', f"""
import contextlib
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
def callback(value):
    observed.append(internal.world_is_stopped())
value = internal.make_nongc_finalizer(callback)
type_ref = weakref.ref(type(value))
assert not gc.is_tracked(value)
# HAVE_GC must be absent; merely untracking a GC type does not test this API.
assert not type(value).__flags__ & (1 << 14)
with sys.monitoring.StopTheWorld if {debugger!r} else contextlib.nullcontext():
    internal.finalize_many_while_world_stopped(value, 1000, {no_memory!r})
    assert observed == [{debugger!r}] * 1000, len(observed)
    assert not gc.is_finalized(value)
# Non-GC finalizers are not deduplicated, including during final deallocation.
del value
gc.collect()
assert observed == [{debugger!r}] * 1000 + [False], len(observed)
assert type_ref() is None
""")
                    self.assertEqual(err, b'')

    def test_deferred_gc_explicit_finalizer_many(self):
        _, _, err = script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
class Payload:
    def __del__(self):
        observed.append(internal.world_is_stopped())
value = Payload()
ref = weakref.ref(value)
with sys.monitoring.StopTheWorld:
    internal.finalize_many_while_world_stopped(value, 1000, True)
    assert observed == [True], observed
    assert gc.is_finalized(value)
del value
gc.collect()
assert observed == [True], observed
assert ref() is None
""")
        self.assertEqual(err, b'')

    def test_deferred_nongc_finalizer_resurrection(self):
        _, _, err = script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
rescued = []
def callback(value):
    observed.append(internal.world_is_stopped())
    if len(observed) == 1:
        rescued.append(value)
def create():
    return internal.make_nongc_finalizer(callback)
with sys.monitoring.StopTheWorld:
    internal.drop_while_world_stopped(create)
    value = rescued.pop()
    assert observed == [True], observed
    assert not gc.is_finalized(value)
    internal.finalize_many_while_world_stopped(value, 2, True)
    assert observed == [True] * 3, observed
type_ref = weakref.ref(type(value))
del value
gc.collect()
assert observed == [True] * 3 + [False], observed
assert type_ref() is None
""")
        self.assertEqual(err, b'')

    def test_deferred_deallocation_explicit_finalizer(self):
        script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
class Payload:
    def __del__(self):
        observed.append(internal.world_is_stopped())
with sys.monitoring.StopTheWorld:
    value = internal.finalize_deferred_deallocation(Payload)
    # The extra reference keeps value alive: releasing a queue reference alone
    # would not execute its explicitly requested finalizer.
    assert observed == [True], observed
    assert gc.is_finalized(value)
ref = weakref.ref(value)
del value
gc.collect()
assert ref() is None
assert observed == [True], observed
""")

    def test_deferred_explicit_finalizer_in_detached_batch(self):
        _, _, err = script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
refs = []
rescued = []
class Payload:
    def __del__(self):
        observed.append(internal.world_is_stopped())
class Trigger:
    def __del__(self):
        value = refs[0]()
        assert value is not None
        rescued.append(value)
        internal.finalize_while_world_stopped(value)
def create():
    value = Payload()
    refs.append(weakref.ref(value))
    # Queue insertion is LIFO: Trigger runs while Payload remains in the
    # consumer's detached batch, outside the interpreter's queue head.
    return (value, Trigger())
with sys.monitoring.StopTheWorld:
    internal.drop_many_while_world_stopped(create)
    assert observed == [True], observed
    assert gc.is_finalized(rescued[0])
rescued.clear()
gc.collect()
assert refs[0]() is None
assert observed == [True], observed
""")
        self.assertEqual(err, b'')

    def test_deferred_explicit_finalizer_nomemory(self):
        script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
class Payload:
    def __del__(self):
        observed.append(internal.world_is_stopped())
value = Payload()
with sys.monitoring.StopTheWorld:
    internal.finalize_while_world_stopped_nomemory(value)
    assert observed == [True], observed
    assert gc.is_finalized(value)
    internal.finalize_while_world_stopped_nomemory(value)
ref = weakref.ref(value)
del value
gc.collect()
assert ref() is None
assert observed == [True], observed
""")

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_protected_finalizer(self):
        import _testinternalcapi as internal
        for factory in (threading.Lock, threading.RLock):
            with self.subTest(factory=factory):
                observed = SynchronizedList()
                @freeze
                class Payload:
                    def __init__(self):
                        self.answer = 42
                    def __del__(self):
                        if self.__shareable__ is threading.Shareable.PROTECTED:
                            observed.append((internal.world_is_stopped(),
                                             self.answer))
                def create():
                    lock = factory()
                    with lock:
                        return (lock.protect(Payload()),)
                # The wrapper is gone before the internal world stop begins.
                internal.drop_while_world_stopped(create)
                self.assertEqual(list(observed), [(False, 42)])

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_finalizers_add_calls_at_shutdown(self):
        _, out, err = script_helper.assert_python_ok('-c', """
import atexit
import gc
import _testinternalcapi as internal

gc.disable()
def completed():
    print('completed')
class Payload:
    def __init__(self, depth):
        self.depth = depth
    def __del__(self):
        if self.depth:
            internal.drop_while_world_stopped(lambda: Payload(self.depth - 1))
        else:
            internal.simple_pending_call(completed)
atexit.register(internal.drop_while_world_stopped, lambda: Payload(3))
""")
        self.assertEqual(out, b'completed\n')
        self.assertEqual(err, b'')

    @unittest.skipUnless(Py_GIL_DISABLED, 'internal world stop needs free threading')
    def test_deferred_finalizer_inside_debugger_stop(self):
        script_helper.assert_python_ok('-c', """
import sys
import _testinternalcapi as internal
observed = []
class Payload:
    def __del__(self):
        observed.append(internal.world_is_stopped())
with sys.monitoring.StopTheWorld:
    internal.drop_while_world_stopped(Payload)
    # The internal stop has ended; debugger-authorized execution remains.
    assert observed == [True], observed
assert observed == [True], observed
""")

    def test_deferred_callbacks_inside_debugger_stop(self):
        script_helper.assert_python_ok('-c', """
import gc
import sys
import weakref
import _testinternalcapi as internal
observed = []
refs = []
class Payload:
    pass
def callback(*args):
    observed.append(internal.world_is_stopped())
def weakref_factory():
    value = Payload()
    refs.append(weakref.ref(value, callback))
    return value
def capsule_factory():
    return internal.make_callback_capsule(callback)
with sys.monitoring.StopTheWorld:
    internal.drop_while_world_stopped(weakref_factory)
    internal.drop_while_world_stopped(capsule_factory)
    assert observed == [True, True], observed
assert refs[0]() is None
gc.collect()
assert observed == [True, True], observed
""")

    def test_protected_resurrection_and_retired_lock(self):
        for factory in ('Lock', 'RLock'):
            for cyclic in (False, True):
                for retired in (False, True):
                    with self.subTest(factory=factory, cyclic=cyclic,
                                      retired=retired):
                        script_helper.assert_python_ok('-c', f"""
import gc
import sys
import threading
import weakref
from threading import Shareable

gc.disable()
observed = SynchronizedList()
rescued = threading.Channel()
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.answer = 41
        self.cycle = None
    def __del__(self):
        if self.__shareable__ is Shareable.PROTECTED:
            self.answer += 1
            observed.append(self.answer)
            rescued.put((self,))

lock = threading.{factory}()
with lock:
    value = lock.protect(Payload())
    if {cyclic!r}:
        value.cycle = value
    holder = (value,)
    del value
ref = weakref.ref(lock)
if {retired!r}:
    del lock
    gc.collect()
    assert ref() is None
try:
    raise ValueError('active exception')
except ValueError as error:
    del holder
    gc.collect()
    assert sys.exception() is error
assert list(observed) == [42], list(observed)
if not {retired!r}:
    assert not lock.locked()
holder = rescued.get()
try:
    holder[0]
except UnprotectedAccessException:
    pass
else:
    raise AssertionError('finalizer leaked mutex ownership')
with sys.monitoring.StopTheWorld:
    assert gc.is_finalized(holder[0])
    assert holder[0].answer == 42
del holder
gc.collect()
assert list(observed) == [42], list(observed)
""")

    def test_protected_finalizer_changes_context(self):
        for factory in ('Lock', 'RLock'):
            for reacquire in (False, True):
                with self.subTest(factory=factory, reacquire=reacquire):
                    script_helper.assert_python_ok('-c', f"""
import gc
import sys
import threading
from threading import Shareable

lock = threading.{factory}()
observed = SynchronizedList()
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.answer = 42
    def __del__(self):
        if self.__shareable__ is Shareable.PROTECTED:
            observed.append(self.answer)
            lock.__exit__(None, None, None)
            if {reacquire!r}:
                lock.__enter__()
                observed.append(self.answer)

with lock:
    value = lock.protect(Payload())
del value
gc.collect()
assert list(observed) == ([42, 42] if {reacquire!r} else [42]), list(observed)
assert lock.locked() is {reacquire!r}
if {reacquire!r}:
    lock.__exit__(None, None, None)
assert not lock.locked()
""")

    def test_protected_finalizer_in_process(self):
        for factory in (threading.Lock, threading.RLock):
            for held in (False, True):
                with self.subTest(factory=factory, held=held):
                    observed = SynchronizedList()
                    @freeze
                    class Payload:
                        def __init__(self):
                            self.answer = 42
                        def __del__(self):
                            if self.__shareable__ is threading.Shareable.PROTECTED:
                                observed.append(self.answer)
                    lock = factory()
                    with lock:
                        value = lock.protect(Payload())
                        if held:
                            del value
                            gc.collect()
                            self.assertTrue(lock.locked())
                    if not held:
                        del value
                        gc.collect()
                    self.assertEqual(list(observed), [42])
                    self.assertFalse(lock.locked())

    def test_protected_finalizer_waits_for_mutex(self):
        for factory in ('Lock', 'RLock'):
            with self.subTest(factory=factory):
                script_helper.assert_python_ok('-c', f"""
import copy
import gc
import threading
from threading import Shareable
from test.support import SHORT_TIMEOUT

lock = threading.{factory}()
prepared = threading.Event()
trigger = threading.Event()
attempted = threading.Event()
completed = threading.Event()
observed = SynchronizedList()

@freeze
class Payload:
    def __init__(self):
        self.answer = 42
    def __del__(self):
        if self.__shareable__ is Shareable.PROTECTED:
            observed.append(self.answer)

def worker():
    with lock:
        value = lock.protect(Payload())
    prepared.set()
    assert trigger.wait(SHORT_TIMEOUT)
    attempted.set()
    # The last reference is owned by this thread; exercise refcount cleanup.
    del value
    completed.set()

thread = threading.Thread(target=worker, group=threading.ThreadGroup())
thread.start()
try:
    assert prepared.wait(SHORT_TIMEOUT)
    with lock:
        trigger.set()
        assert attempted.wait(SHORT_TIMEOUT)
        assert not completed.wait(0.05)
        assert list(observed) == [], list(observed)
    assert completed.wait(SHORT_TIMEOUT)
finally:
    trigger.set()
    thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
assert list(observed) == [42], list(observed)
assert not lock.locked()
""")

    def test_finalizer_in_process(self):
        observed = SynchronizedList()
        @freeze
        class Payload:
            def __init__(self):
                self.value = []
            def __del__(self):
                self.value.append(42)
                observed.append(self.value[0])
        results = threading.Channel()
        def create():
            results.put((Payload(),))
        thread = threading.Thread(target=create, group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        holder = results.get()
        del thread, holder
        gc.collect()
        self.assertEqual(list(observed), [42])

    def test_finalizer_with_live_owner_thread(self):
        script_helper.assert_python_ok('-c', '''
import gc
import sys
import threading
from test.support import SHORT_TIMEOUT

owner = threading.ThreadGroup('owner')
done = threading.Event()
# Deferred finalization may run inside done.wait() holding its condition lock.
# Use a distinct event so the finalizer does not re-enter that lock.
finalized = threading.Event()
ready = threading.Event()
results = threading.Channel()
observed = SynchronizedList()
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.value = []
    def __del__(self):
        self.value.append(42)
        observed.append(threading.current_thread().group is owner)
        finalized.set()

def create():
    results.put((Payload(),))
    ready.set()
    assert done.wait(SHORT_TIMEOUT)

thread = threading.Thread(target=create, group=owner)
thread.start()
try:
    assert ready.wait(SHORT_TIMEOUT)
    holder = results.get()
    del holder
    gc.collect()
    assert finalized.wait(SHORT_TIMEOUT)
    assert list(observed) == [True], list(observed)
finally:
    done.set()
    thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
''')

    def test_owner_group_resurrection_and_cycles(self):
        for cyclic in (False, True):
            with self.subTest(cyclic=cyclic):
                script_helper.assert_python_ok('-c', f'''
import gc
import sys
import threading
from test.support import SHORT_TIMEOUT

gc.disable()
observed = SynchronizedList()
rescued = threading.Channel()
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.value = []
        self.cycle = self if {cyclic!r} else None
    def __del__(self):
        self.value.append(42)
        observed.append((threading.current_thread().group.name, self.value[0]))
        rescued.put((self,))

results = threading.Channel()
def create():
    results.put((Payload(),))
thread = threading.Thread(target=create, group=threading.ThreadGroup('owner'))
thread.start()
thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
del thread
gc.collect()
holder = results.get()
try:
    raise ValueError('active exception')
except ValueError as error:
    del holder
    gc.collect()
    assert sys.exception() is error
assert threading.current_thread().group is sys.main_thread_group
assert list(observed) == [('owner', 42)], list(observed)
holder = rescued.get()
with sys.monitoring.StopTheWorld:
    assert gc.is_finalized(holder[0])
del holder
gc.collect()
assert list(observed) == [('owner', 42)], list(observed)
''')

    def test_finalizer_after_owner_thread_exits(self):
        script_helper.assert_python_ok('-c', '''
import gc
import sys
import threading
from test.support import SHORT_TIMEOUT

observed = SynchronizedList()
def unraisable(error):
    observed.append(error.exc_type.__name__)
sys.unraisablehook = unraisable

@freeze
class Payload:
    def __init__(self):
        self.value = []
    def __del__(self):
        observed.append('entered')
        self.value.append(42)
        observed.append('completed')

def create(results):
    results.put((Payload(),))

results = threading.Channel()
thread = threading.Thread(target=create, args=(results,),
                          group=threading.ThreadGroup())
thread.start()
thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
# The tuple carries a foreign object without acquiring it in this group.
holder = results.get()
del holder
gc.collect()
assert list(observed) == ['entered', 'completed'], list(observed)
''')


if __name__ == '__main__':
    unittest.main()
