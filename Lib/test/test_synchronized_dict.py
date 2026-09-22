"""Native synchronized dictionary construction and shared operations."""

import copy
import gc
import pickle
import threading
import unittest
import weakref

from test import mapping_tests
from test.support import SHORT_TIMEOUT, gc_collect, nomemtest, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class MappingTests(mapping_tests.BasicTestMappingProtocol):
    type2test = SynchronizedDict


class SynchronizedDictTests(unittest.TestCase):
    def test_synchronize(self):
        payload = []
        for source in ({}, {'a': payload}, {i: i for i in range(100)}):
            with self.subTest(size=len(source)):
                expected = source.copy()
                alias = source
                keys = source.keys()
                result = source.synchronize()
                self.assertIs(type(result), SynchronizedDict)
                self.assertIs(result.__shareable__, threading.Shareable.SYNCHRONIZED)
                self.assertEqual(result, expected)
                self.assertIs(type(source), dict)
                self.assertEqual(alias, {})
                self.assertEqual(list(keys), [])
                source['new'] = 1
                self.assertNotIn('new', result)
                if 'a' in result:
                    self.assertIs(result['a'], payload)

    def test_synchronize_instance_namespace(self):
        class Instance:
            pass
        instance = Instance()
        instance.a = []
        namespace = instance.__dict__
        payload = instance.a
        def read():
            return instance.a
        for _ in range(100):
            self.assertIs(read(), payload)
        result = namespace.synchronize()
        self.assertIs(instance.__dict__, namespace)
        self.assertEqual(namespace, {})
        self.assertFalse(hasattr(instance, 'a'))
        with self.assertRaises(AttributeError):
            read()
        self.assertIs(result['a'], payload)
        instance.b = 42
        self.assertEqual(namespace, {'b': 42})
        self.assertNotIn('b', result)

    def test_synchronize_global_cache(self):
        namespace = {'answer': 42}
        exec('def read(): return answer', namespace)
        read = namespace['read']
        for _ in range(100):
            self.assertEqual(read(), 42)
        result = namespace.synchronize()
        with self.assertRaises(NameError):
            read()
        result['answer'] = 100
        with self.assertRaises(NameError):
            read()
        namespace['answer'] = 7
        self.assertEqual(read(), 7)

    def test_synchronize_self_reference(self):
        source = {}
        source['self'] = source
        result = source.synchronize()
        self.assertIs(result['self'], source)
        self.assertEqual(source, {})

    def test_synchronize_does_not_rehash(self):
        class Key:
            fail = False

            def __hash__(self):
                if self.fail:
                    raise AssertionError('hash called during synchronization')
                return 42

        key = Key()
        source = {key: []}
        key.fail = True
        result = source.synchronize()
        self.assertEqual(source, {})
        self.assertIs(next(iter(result)), key)

    @nomemtest
    def test_synchronize_allocation_failure(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi

            class Instance:
                pass

            failures = 0
            for start in range(10):
                owner = Instance()
                owner.a = 1
                source = owner.__dict__
                method = source.synchronize
                failed = False
                _testcapi.set_nomemory(start, start + 1)
                try:
                    result = method()
                except MemoryError:
                    failed = True
                finally:
                    _testcapi.remove_mem_hooks()
                assert owner.__dict__ is source
                assert type(source) is dict
                if failed:
                    failures += 1
                    assert source == {'a': 1}
                    owner.a = 2
                    assert source == {'a': 2}
                else:
                    assert type(result) is SynchronizedDict
                    assert result == {'a': 1}
                    assert source == {}
            assert failures > 0
        ''')

    def test_synchronize_rejected_states(self):
        class Subclass(dict):
            pass
        for source in (SynchronizedDict(a=1), Subclass(a=1)):
            with self.subTest(type=type(source)):
                with self.assertRaises(TypeError):
                    source.synchronize()
                self.assertEqual(source, {'a': 1})
        source = {'a': 1}
        method = source.synchronize
        freeze(source)
        with self.assertRaises(TypeError):
            method()
        self.assertEqual(source, {'a': 1})

    def test_synchronize_watcher_freezes_source(self):
        capi = import_module('_testcapi')
        source = {'a': 1}
        watcher = capi.add_dict_watcher(3)
        try:
            capi.watch_dict(watcher, source)
            with self.assertRaises(TypeError):
                source.synchronize()
            self.assertIs(type(source), frozendict)
            self.assertEqual(source, {'a': 1})
        finally:
            capi.unwatch_dict(watcher, source)
            capi.clear_dict_watcher(watcher)

    def test_synchronize_watcher_stays_with_source(self):
        capi = import_module('_testcapi')
        source = {'a': 1}
        watcher = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(watcher, source)
            result = source.synchronize()
            self.assertEqual(capi.get_dict_watcher_events(), ['clear'])
            result['b'] = 2
            self.assertEqual(capi.get_dict_watcher_events(), ['clear'])
            source['c'] = 3
            self.assertEqual(capi.get_dict_watcher_events(),
                             ['clear', 'new:c:3'])
        finally:
            capi.unwatch_dict(watcher, source)
            capi.clear_dict_watcher(watcher)

    @threading_helper.requires_working_threading()
    def test_synchronize_foreign_source(self):
        source = {'a': 1}
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
        self.assertEqual(source, {'a': 1})

    def test_state_and_identity(self):
        internal = import_module('_testinternalcapi')
        value = SynchronizedDict(a=1)
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertEqual(internal.object_owner_id(value), 0)
        self.assertIs(internal.object_check_access(value), value)
        self.assertIs(threading.TransferBox(value).claim(), value)
        self.assertIsInstance(value, dict)
        with self.assertRaises(TypeError):
            class Subclass(SynchronizedDict):
                pass

    def test_construction_and_capi(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        value = capi.synchronizeddict_new()
        self.assertIs(type(value), SynchronizedDict)
        self.assertTrue(limited.dict_check(value))
        self.assertFalse(limited.dict_checkexact(value))
        limited.dict_setitem(value, 'answer', 42)
        self.assertEqual(limited.dict_getitem(value, 'answer'), 42)
        self.assertEqual(capi.dict_getitemref(value, 'answer'), 42)
        limited.dict_delitem(value, 'answer')
        self.assertEqual(value, {})
        self.assertEqual(SynchronizedDict([('x', 1)], y=2), {'x': 1, 'y': 2})

    def test_fromkeys(self):
        value = SynchronizedDict.fromkeys(['a', 'b'], [])
        self.assertIs(type(value), SynchronizedDict)
        self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertIs(value['a'], value['b'])

    def test_copy_and_pickle(self):
        value = SynchronizedDict(a=[1, 2])
        shallow = copy.copy(value)
        self.assertIs(type(shallow), SynchronizedDict)
        self.assertIs(shallow['a'], value['a'])
        self.assertIs(shallow.__shareable__, threading.Shareable.SYNCHRONIZED)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                restored = pickle.loads(pickle.dumps(value, protocol))
                self.assertIs(type(restored), SynchronizedDict)
                self.assertEqual(restored, value)
                self.assertIs(restored.__shareable__,
                              threading.Shareable.SYNCHRONIZED)

        value['self'] = value
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(recursive=True, protocol=protocol):
                restored = pickle.loads(pickle.dumps(value, protocol))
                self.assertIs(restored['self'], restored)
                self.assertEqual(restored['a'], [1, 2])

    def test_cycle_collection(self):
        class Payload:
            pass
        payload = Payload()
        ref = weakref.ref(payload)
        value = SynchronizedDict(payload=payload)
        value['self'] = value
        identity = id(value)
        del payload, value
        gc_collect()
        self.assertIsNone(ref())
        self.assertFalse(any(id(obj) == identity for obj in gc.get_objects()))

    def test_freeze(self):
        value = SynchronizedDict(a=1)
        alias = value
        keys = value.keys()
        clear = value.clear
        self.assertIs(freeze(value), value)
        self.assertIs(type(alias), frozendict)
        self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertEqual(value, {'a': 1})
        self.assertEqual(list(keys), ['a'])
        self.assertEqual(hash(value), hash(frozendict(a=1)))
        self.assertIs(freeze(value), value)
        with self.assertRaises(TypeError):
            clear()
        self.assertEqual(value, {'a': 1})

    @threading_helper.requires_working_threading()
    def test_freeze_from_another_group(self):
        value = SynchronizedDict(a=1)
        results = threading.Channel()

        def worker():
            results.put(freeze(value))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertIs(results.get(), value)
        self.assertIs(type(value), frozendict)
        self.assertEqual(value, {'a': 1})

    @threading_helper.requires_working_threading()
    def test_parallel_mutation(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        value = SynchronizedDict()
        barrier = threading.Barrier(4)
        results = threading.Channel()

        def worker(number):
            shared = check_access(value)
            barrier.wait(timeout=SHORT_TIMEOUT)
            winner = shared.setdefault('winner', number)
            for index in range(500):
                key = (number, index)
                shared[key] = index
                assert shared.pop(key) == index
                shared[key] = index + 1
            results.put(winner)

        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        winners = [results.get() for _ in threads]
        self.assertEqual(winners, [value['winner']] * 4)
        self.assertEqual(len(value), 2001)
        for number in range(4):
            for index in range(500):
                self.assertEqual(value[number, index], index + 1)


if __name__ == '__main__':
    unittest.main()
