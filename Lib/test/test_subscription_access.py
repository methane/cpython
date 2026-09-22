"""Ownership checks in specialized builtin subscription instructions."""

import dis
import sys
import threading
import unittest
import weakref

from test.support import gc_collect, requires_specialization, threading_helper
from test.support.import_helper import import_module


class SubscriptionAccessTests(unittest.TestCase):
    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_inlined_return_monitoring(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        foreign = []
        results = threading.Channel()
        @freeze
        class Indexable:
            def __init__(self, value):
                self.value = value
            def __getitem__(self, index):
                return self.value
        def read(obj):
            obj[0]
            return 42
        returned = SynchronizedList()
        def on_return(code, offset, value):
            returned.append(value)

        def worker(payload):
            obj = Indexable(42)
            for _ in range(100):
                assert read(obj) == 42
            bytecode = (get_tlbc(read) if get_tlbc is not None
                        else read.__code__._co_code_adaptive)
            results.put(bytecode)
            with sys.monitoring.StopTheWorld:
                obj.value = payload[0]
            try:
                read(obj)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            results.put(len(returned) == 100 and all(v == 42 for v in returned))

        # Configure monitoring in Main; its native control functions remain
        # Main-owned. The callback records values in a synchronized collector.
        monitoring = sys.monitoring
        tool = 2
        monitoring.use_tool_id(tool, 'subscription access test')
        code = Indexable.__getitem__.__code__
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         on_return)
            monitoring.set_local_events(tool, code, monitoring.events.PY_RETURN)
            thread = threading.Thread(target=worker, args=((foreign,),),
                                      group=threading.ThreadGroup())
            with threading_helper.start_threads([thread]):
                pass
        finally:
            monitoring.set_local_events(tool, code, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)
        self.assertIn(dis._all_opmap['BINARY_OP_SUBSCR_GETITEM'],
                      [op for _, _, op, _ in dis._unpack_opargs(results.get())])
        self.assertEqual([results.get() for _ in range(2)], [True] * 2)

    @requires_specialization
    def test_inlined_return_after_cleanup(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        lock = threading.Lock()
        release = [False]
        class Cleanup:
            def __del__(self):
                if release[0]:
                    lock.__exit__(None, None, None)
        @freeze
        class Indexable:
            def __getitem__(self, index):
                cleanup = Cleanup()
                return self
        def read(obj):
            # The caller discards the result, so its own return check cannot
            # hide a missing check after __getitem__ frame cleanup.
            obj[0]
            return 42

        lock.__enter__()
        try:
            obj = lock.protect(Indexable())
            for _ in range(100):
                self.assertEqual(read(obj), 42)
            code = (get_tlbc(read) if get_tlbc is not None
                    else read.__code__._co_code_adaptive)
            self.assertIn(dis._all_opmap['BINARY_OP_SUBSCR_GETITEM'],
                          [op for _, _, op, _ in dis._unpack_opargs(code)])
            release[0] = True
            with self.assertRaises(UnprotectedAccessException):
                read(obj)
            self.assertFalse(lock.locked())
        finally:
            if lock.locked():
                lock.__exit__(None, None, None)

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_foreign_results(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass

        class Indexable:
            def __init__(self, value):
                self.value = value
            def __getitem__(self, index):
                return self.value

        caught = SynchronizedList()
        class Delegating(Indexable):
            def read(self):
                return self.value
            def __getitem__(self, index):
                try:
                    return self.read()
                except IllegalThreadAccessException:
                    # Verify that the nested access already rejects the
                    # foreign value, before returning to the subscription.
                    caught.append(True)
                    raise

        freeze(Indexable)
        freeze(Delegating)
        foreign = Payload()
        reference = weakref.ref(foreign)
        cases = (
            (lambda value: [value], 'BINARY_OP_SUBSCR_LIST_INT'),
            (lambda value: (value,), 'BINARY_OP_SUBSCR_TUPLE_INT'),
            (lambda value: {0: value}, 'BINARY_OP_SUBSCR_DICT'),
            (lambda value: SynchronizedDict({0: value}), 'BINARY_OP_SUBSCR_DICT'),
            (lambda value: frozendict({0: value}), 'BINARY_OP_SUBSCR_DICT'),
            (Indexable, 'BINARY_OP_SUBSCR_GETITEM'),
            (Delegating, 'BINARY_OP_SUBSCR_GETITEM'),
        )
        def worker(payload, factory, get_tlbc, results):
            def read(container):
                # Discard the result to isolate acquisition from the outer
                # function's return-value check.
                container[0]
                return 42

            local = factory(42)
            for _ in range(100):
                assert read(local) == 42
            # Inspect this thread's bytecode copy in free-threaded builds.
            bytecode = (get_tlbc(read) if get_tlbc is not None
                        else read.__code__._co_code_adaptive)
            results.put(bytecode)
            with sys.monitoring.StopTheWorld:
                container = factory(payload[0])
            denied = 0
            for _ in range(100):
                try:
                    read(container)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)
            results.put(read(local))

        for factory, opname in cases:
            with self.subTest(opname=opname, factory=factory):
                opcode = dis._all_opmap[opname]
                results = threading.Channel()
                thread = threading.Thread(
                    target=worker, args=((foreign,), factory, get_tlbc, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                self.assertIn(opcode,
                              [op for _, _, op, _ in dis._unpack_opargs(results.get())])
                self.assertEqual(results.get(), 100)
                self.assertEqual(results.get(), 42)
                self.assertEqual(len(caught), 100 if factory is Delegating else 0)
                self.assertIs(reference(), foreign)
        foreign = None
        gc_collect()
        self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main()
