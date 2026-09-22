"""Native synchronized list construction and shared list operations."""

import copy
import pickle
import threading
import unittest
import weakref

from test.support import SHORT_TIMEOUT, gc_collect, nomemtest, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class SynchronizedListTests(unittest.TestCase):
    def test_keyword_arguments_rejected(self):
        with self.assertRaises(TypeError):
            SynchronizedList(iterable=[1, 2])
        sequence = SynchronizedList([3])
        with self.assertRaises(TypeError):
            sequence.__init__(iterable=[1, 2])
        self.assertEqual(sequence, [3])

    def test_synchronize(self):
        payload = []
        for source in ([], [payload], list(range(100))):
            expected = source.copy()
            alias = source
            iterator = iter(source)
            result = source.synchronize()
            self.assertIs(type(result), SynchronizedList)
            self.assertIs(result.__shareable__, threading.Shareable.SYNCHRONIZED)
            self.assertEqual(result, expected)
            self.assertEqual(alias, [])
            self.assertIs(type(source), list)
            self.assertEqual(list(iterator), [])
            source.append('new')
            self.assertNotIn('new', result)
            if expected == [payload]:
                self.assertIs(result[0], payload)
        source = []
        source.append(source)
        result = source.synchronize()
        self.assertIs(result[0], source)
        self.assertEqual(source, [])

    def test_synchronize_rejected_states(self):
        internal = import_module('_testinternalcapi')
        class Subclass(list):
            pass
        for source in (Subclass([1]), SynchronizedList([1])):
            with self.assertRaises(TypeError):
                source.synchronize()
            self.assertEqual(source, [1])
        for declare in (internal.object_declare_immutable,
                        internal.object_declare_synchronized):
            source = [1]
            declare(source)
            with self.assertRaises(TypeError):
                source.synchronize()
            self.assertEqual(source, [1])

    def test_synchronize_during_sort(self):
        source = [3, 1, 2]
        def key(value):
            return source.synchronize()
        with self.assertRaisesRegex(ValueError, 'during sort'):
            source.sort(key=key)
        self.assertCountEqual(source, [3, 1, 2])

    @nomemtest
    def test_synchronize_allocation_failure(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import gc
            import _testcapi
            failures = 0
            for start in range(10):
                source = [1, 2, 3]
                method = source.synchronize
                gc.collect()
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
                    assert source == [1, 2, 3]
                else:
                    assert source == []
                    assert type(result) is SynchronizedList
                    assert result == [1, 2, 3]
            assert failures > 0
        ''')

    @threading_helper.requires_working_threading()
    def test_synchronize_foreign_source(self):
        source = [1]
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
        self.assertEqual(source, [1])

    def test_state_and_construction(self):
        internal = import_module('_testinternalcapi')
        value = SynchronizedList(range(5))
        self.assertEqual(value, [0, 1, 2, 3, 4])
        self.assertIsInstance(value, list)
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertEqual(internal.object_owner_id(value), 0)
        self.assertIs(internal.object_check_access(value), value)
        self.assertIs(threading.TransferBox(value).claim(), value)
        self.assertEqual(SynchronizedList(), [])
        self.assertEqual(SynchronizedList('abc'), ['a', 'b', 'c'])
        with self.assertRaises(TypeError):
            SynchronizedList(1)
        with self.assertRaises(TypeError):
            SynchronizedList([], [])
        with self.assertRaises(TypeError):
            class Subclass(SynchronizedList):
                pass
        with self.assertRaises(TypeError):
            list.__new__(SynchronizedList)

    def test_capi(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        value = capi.synchronizedlist_new(3)
        self.assertIs(type(value), SynchronizedList)
        self.assertEqual(value, [None, None, None])
        self.assertTrue(limited.list_check(value))
        self.assertFalse(limited.list_check_exact(value))
        limited.list_setitem(value, 1, 42)
        self.assertEqual(limited.list_getitem(value, 1), 42)
        self.assertEqual(capi.list_get_size(value), 3)
        capi.list_extend(value, [7, 8])
        self.assertEqual(value, [None, 42, None, 7, 8])
        capi.list_clear(value)
        self.assertEqual(value, [])
        with self.assertRaises(SystemError):
            capi.synchronizedlist_new(-1)

    def test_list_operations(self):
        value = SynchronizedList([3, 1, 2])
        value.sort()
        value.append(4)
        value.extend([5, 6])
        value.insert(0, 0)
        self.assertEqual(value, list(range(7)))
        self.assertEqual(value.pop(), 6)
        value.remove(3)
        value[1:3] = [7, 8]
        self.assertEqual(value, [0, 7, 8, 4, 5])
        del value[::2]
        self.assertEqual(value, [7, 4])
        value += [9]
        value *= 2
        self.assertEqual(value, [7, 4, 9, 7, 4, 9])
        value.reverse()
        self.assertEqual(value, [9, 4, 7, 9, 4, 7])
        self.assertEqual(value.count(9), 2)
        self.assertEqual(value.index(7), 2)
        self.assertEqual(value[::-1], [7, 4, 9, 7, 4, 9])
        value.extend(value)
        self.assertEqual(len(value), 12)
        value.__init__([42])
        self.assertEqual(value, [42])
        value.clear()
        self.assertEqual(value, [])
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)

    def test_shallow_construction(self):
        payload = []
        value = SynchronizedList([payload])
        self.assertIs(value[0], payload)
        self.assertIs(payload.__shareable__, threading.Shareable.LOCAL)

    def test_copy_and_pickle(self):
        value = SynchronizedList([[1, 2]])
        shallow = copy.copy(value)
        self.assertIs(type(shallow), SynchronizedList)
        self.assertIs(shallow[0], value[0])
        self.assertIs(shallow.__shareable__, threading.Shareable.SYNCHRONIZED)
        value.append(value)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                restored = pickle.loads(pickle.dumps(value, protocol))
                self.assertIs(type(restored), SynchronizedList)
                self.assertEqual(restored[0], [1, 2])
                self.assertIs(restored[1], restored)
                self.assertIs(restored.__shareable__, threading.Shareable.SYNCHRONIZED)

    def test_cycle_collection(self):
        class Payload:
            pass
        payload = Payload()
        ref = weakref.ref(payload)
        value = SynchronizedList([payload])
        value.append(value)
        del payload, value
        gc_collect()
        self.assertIsNone(ref())

    @threading_helper.requires_working_threading()
    def test_parallel_mutation(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        value = SynchronizedList()
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            shared = check_access(value)
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(500):
                shared.append(number * 500 + index)
            results.put(number)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sorted(results.get() for _ in threads), list(range(4)))
        self.assertEqual(sorted(value), list(range(2000)))


if __name__ == '__main__':
    unittest.main()
