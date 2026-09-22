"""Explicit synchronization of Python class namespaces."""

import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


class SynchronizeClassTests(unittest.TestCase):
    def test_namespace_identity(self):
        internal = import_module('_testinternalcapi')
        class C:
            value = 1
        namespace = internal.type_get_dict(C)
        proxy = C.__dict__
        for _ in range(100):
            self.assertEqual(C.value, 1)
        self.assertIs(C.synchronize(), C)
        self.assertIs(internal.type_get_dict(C), namespace)
        self.assertIs(type(namespace), SynchronizedDict)
        self.assertIs(C.__shareable__, threading.Shareable.SYNCHRONIZED)
        C.value = 2
        self.assertEqual(proxy['value'], 2)
        self.assertEqual(C.value, 2)
        del C.value
        self.assertNotIn('value', proxy)

    @threading_helper.requires_working_threading()
    def test_mutation_and_slots_in_worker(self):
        class C:
            def __len__(self):
                return 1
        C.synchronize()
        instance = C()
        for _ in range(100):
            self.assertEqual(len(instance), 1)
        results = threading.Channel()
        def worker():
            local = C()
            assert local.__shareable__ is threading.Shareable.LOCAL
            def length(self):
                return 2
            C.__len__ = length
            C.value = 42
            assert len(local) == 2
            assert C.value == 42
            assert C.__dict__.__shareable__ is threading.Shareable.SYNCHRONIZED
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertEqual(len(instance), 2)
        self.assertEqual(C.value, 42)

    def test_python_metaclass(self):
        class Meta(type):
            pass
        class C(metaclass=Meta):
            pass
        self.assertIs(type.synchronize(C), C)
        C.value = 42
        self.assertEqual(C.value, 42)
        self.assertIs(Meta.__shareable__, threading.Shareable.LOCAL)

    @threading_helper.requires_working_threading()
    def test_shallow_namespace(self):
        class C:
            payload = []
            shared = 42
        payload = C.payload
        C.synchronize()
        results = threading.Channel()
        def worker():
            assert C.__dict__['shared'] == 42
            try:
                C.__dict__['payload']
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(C.payload, payload)
        self.assertIs(payload.__shareable__, threading.Shareable.LOCAL)

    @threading_helper.requires_working_threading()
    def test_slot_updates_between_groups(self):
        class C:
            def __len__(self):
                return 0
        C.synchronize()
        ready = threading.Lock()
        acknowledged = threading.Lock()
        ready.acquire()
        acknowledged.acquire()
        results = threading.Channel()
        def writer():
            for value in range(1, 201):
                def length(self, value=value):
                    return value
                C.__len__ = length
                ready.release()
                assert acknowledged.acquire(timeout=SHORT_TIMEOUT)
        def reader():
            local = C()
            correct = True
            for value in range(1, 201):
                assert ready.acquire(timeout=SHORT_TIMEOUT)
                correct &= len(local) == value
                acknowledged.release()
            results.put(correct)
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (writer, reader)]
        with threading_helper.start_threads(threads):
            pass
        self.assertTrue(results.get())

    def test_freeze_synchronized_class(self):
        class C:
            value = 42
        C.synchronize()
        self.assertIs(freeze(C), C)
        self.assertIs(C.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(type(C.__dict__), frozendict)
        with self.assertRaises(TypeError):
            C.value = 43

    def test_invalid_transitions(self):
        class C:
            pass
        C.synchronize()
        with self.assertRaises(TypeError):
            C.synchronize()
        class Frozen:
            pass
        freeze(Frozen)
        with self.assertRaises(TypeError):
            Frozen.synchronize()
        with self.assertRaises(TypeError):
            int.synchronize()
        capi = import_module('_testcapi')
        with self.assertRaisesRegex(TypeError, 'native types'):
            capi.HeapCTypeWithDict.synchronize()

    @threading_helper.requires_working_threading()
    def test_foreign_transition_rejected(self):
        class C:
            pass
        results = threading.Channel()
        def worker():
            try:
                C.synchronize()
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(C.__shareable__, threading.Shareable.LOCAL)


if __name__ == '__main__':
    unittest.main()
