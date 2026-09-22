"""Native synchronized sets, shallow storage transfer, and freezing."""

import copy
import pickle
import threading
import unittest
import weakref

from test.support import SHORT_TIMEOUT, gc_collect, nomemtest, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class Payload:
    pass


class SynchronizedSetTests(unittest.TestCase):
    def test_construction_and_state(self):
        internal = import_module('_testinternalcapi')
        value = SynchronizedSet([1, 1, 2])
        self.assertEqual(value, {1, 2})
        self.assertIsInstance(value, set)
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertEqual(internal.object_owner_id(value), 0)
        self.assertIs(internal.object_check_access(value), value)
        self.assertIs(threading.TransferBox(value).claim(), value)
        self.assertEqual(SynchronizedSet(), set())
        with self.assertRaises(TypeError):
            SynchronizedSet([[]])
        with self.assertRaises(TypeError):
            class Subclass(SynchronizedSet):
                pass
        with self.assertRaises(TypeError):
            set.__new__(SynchronizedSet)

    def test_capi(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        value = capi.synchronizedset_new([1, 2])
        self.assertIs(type(value), SynchronizedSet)
        self.assertEqual(value, {1, 2})
        self.assertEqual(capi.synchronizedset_new(None), set())
        self.assertTrue(limited.set_check(value))
        self.assertFalse(limited.set_checkexact(value))
        limited.set_add(value, 3)
        self.assertEqual(capi.set_get_size(value), 3)
        limited.set_discard(value, 1)
        self.assertEqual(value, {2, 3})
        limited.set_clear(value)
        self.assertEqual(value, set())

    def test_set_operations(self):
        value = SynchronizedSet([1, 2, 3])
        self.assertEqual(value | {4}, {1, 2, 3, 4})
        self.assertEqual(value & {2, 4}, {2})
        self.assertEqual(value - {2}, {1, 3})
        self.assertEqual(value ^ {2, 4}, {1, 3, 4})
        value |= {4}
        value &= {2, 3, 4}
        value -= {3}
        value ^= {4, 5}
        self.assertEqual(value, {2, 5})
        value.update([6, 7])
        value.intersection_update([2, 6, 7])
        value.difference_update([7])
        value.symmetric_difference_update([6, 8])
        self.assertEqual(value, {2, 8})
        self.assertTrue(value.issubset({2, 8, 9}))
        self.assertTrue(value.issuperset({2}))
        self.assertTrue(value.isdisjoint({9}))
        value.add(9)
        value.remove(9)
        value.discard(100)
        self.assertIn(value.pop(), {2, 8})
        value.clear()
        value.__init__([42])
        self.assertEqual(value, {42})
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)

    def test_synchronize(self):
        for size in (0, 1, 5, 100):
            with self.subTest(size=size):
                source = set(range(size))
                alias = source
                ref = weakref.ref(source)
                result = source.synchronize()
                self.assertIs(type(result), SynchronizedSet)
                self.assertEqual(result, set(range(size)))
                self.assertEqual(alias, set())
                self.assertIs(ref(), source)
                self.assertIs(type(source), set)
                source.add(-1)
                self.assertNotIn(-1, result)
        source = {1}
        iterator = iter(source)
        source.synchronize()
        with self.assertRaises(RuntimeError):
            next(iterator)

    def test_shallow_transfer_without_rehash(self):
        class Key:
            fail = False
            def __hash__(self):
                if self.fail:
                    raise AssertionError('unexpected hash call')
                return 42
        key = Key()
        source = {key}
        key.source = source
        key.fail = True
        result = source.synchronize()
        self.assertIs(next(iter(result)), key)
        self.assertIs(key.source, source)
        self.assertEqual(source, set())
        self.assertIs(key.__shareable__, threading.Shareable.LOCAL)

    def test_rejected_states(self):
        internal = import_module('_testinternalcapi')
        class Subclass(set):
            pass
        for value in (Subclass([1]), SynchronizedSet([1])):
            with self.assertRaises(TypeError):
                value.synchronize()
            self.assertEqual(value, {1})
        for declare in (internal.object_declare_immutable,
                        internal.object_declare_synchronized):
            value = {1}
            declare(value)
            with self.assertRaises(TypeError):
                value.synchronize()
            self.assertEqual(value, {1})
        value = {1}
        method = value.synchronize
        freeze(value)
        with self.assertRaises(TypeError):
            method()

    def test_freeze(self):
        value = SynchronizedSet([1, 2])
        alias = value
        ref = weakref.ref(value)
        clear = value.clear
        self.assertIs(freeze(value), value)
        self.assertIs(type(alias), frozenset)
        self.assertIs(ref(), value)
        self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertEqual(hash(value), hash(frozenset([1, 2])))
        with self.assertRaises(TypeError):
            clear()
        self.assertEqual(value, {1, 2})

    def test_copy_pickle_and_cycles(self):
        payload = Payload()
        value = SynchronizedSet([payload])
        shallow = copy.copy(value)
        self.assertIs(type(shallow), SynchronizedSet)
        self.assertIs(next(iter(shallow)), payload)
        self.assertIs(shallow.__shareable__, threading.Shareable.SYNCHRONIZED)
        payload.parent = value
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                restored = pickle.loads(pickle.dumps(value, protocol))
                self.assertIs(type(restored), SynchronizedSet)
                self.assertIs(next(iter(restored)).parent, restored)
                self.assertIs(restored.__shareable__, threading.Shareable.SYNCHRONIZED)
        ref = weakref.ref(payload)
        del value, shallow, payload
        gc_collect()
        self.assertIsNone(ref())

    def test_freeze_in_hash_callback(self):
        value = SynchronizedSet([1])
        class Key:
            def __hash__(self):
                freeze(value)
                return 42
        with self.assertRaises(TypeError):
            value.add(Key())
        self.assertIs(type(value), frozenset)
        self.assertEqual(value, {1})

    @threading_helper.requires_working_threading()
    def test_foreign_freeze(self):
        value = SynchronizedSet([1])
        results = threading.Channel()
        def worker():
            results.put(freeze(value))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertIs(results.get(), value)
        self.assertIs(type(value), frozenset)
        self.assertEqual(value, {1})

    @nomemtest
    def test_allocation_failure(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            failures = 0
            for start in range(10):
                source = set(range(100))
                method = source.synchronize
                failed = False
                _testcapi.set_nomemory(start, start + 1)
                try:
                    result = method()
                except MemoryError:
                    failed = True
                finally:
                    _testcapi.remove_mem_hooks()
                if failed:
                    failures += 1
                    assert source == set(range(100))
                else:
                    assert source == set()
                    assert type(result) is SynchronizedSet
                    assert result == set(range(100))
            assert failures > 0
        ''')

    @threading_helper.requires_working_threading()
    def test_foreign_source(self):
        source = {1}
        results = threading.Channel()
        def worker():
            try:
                source.synchronize()
            except Exception as exc:
                results.put(type(exc).__name__)
            else:
                results.put('allowed')
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'IllegalThreadAccessException')
        self.assertEqual(source, {1})

    @threading_helper.requires_working_threading()
    def test_parallel_mutation(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        value = SynchronizedSet()
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            shared = check_access(value)
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(500):
                key = number * 500 + index
                shared.add(key)
                shared.remove(key)
                shared.add(key)
            results.put(number)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sorted(results.get() for _ in threads), list(range(4)))
        self.assertEqual(value, set(range(2000)))


if __name__ == '__main__':
    unittest.main()
