"""Sharing state of dictionary views/proxies and container iterators."""

import copy
import pickle
import threading
from types import MappingProxyType
from operator import length_hint
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


def setUpModule():
    internal = import_module('_testinternalcapi')
    internal.object_declare_synchronized(length_hint)


class DerivedSharingTests(unittest.TestCase):
    def test_dictionary_views_and_proxies(self):
        internal = import_module('_testinternalcapi')
        for mapping in ({'a': 1}, SynchronizedDict(a=1), frozendict(a=1)):
            expected = (threading.Shareable.SYNCHRONIZED
                        if type(mapping) is SynchronizedDict
                        else threading.Shareable.LOCAL)
            owner = (0 if expected is threading.Shareable.SYNCHRONIZED
                     else internal.object_owner_id([]))
            views = [mapping.keys(), mapping.values(), mapping.items(),
                     MappingProxyType(mapping), mapping.keys().mapping]
            for view in views:
                with self.subTest(mapping=type(mapping), view=type(view)):
                    self.assertIs(view.__shareable__, expected)
                    self.assertEqual(internal.object_owner_id(view), owner)
                    self.assertIs(internal.object_check_access(view), view)
                    self.assertEqual(len(view), 1)
                    if expected is threading.Shareable.SYNCHRONIZED:
                        self.assertIs(threading.TransferBox(view).claim(), view)

    def test_list_iterators(self):
        internal = import_module('_testinternalcapi')
        for sequence in ([1, 2], SynchronizedList([1, 2])):
            for factory in (iter, reversed):
                with self.subTest(sequence=type(sequence), factory=factory):
                    iterator = factory(sequence)
                    self.assertIs(iterator.__shareable__, sequence.__shareable__)
                    self.assertEqual(internal.object_owner_id(iterator),
                                     internal.object_owner_id(sequence))
                    self.assertEqual(list(iterator),
                                     [1, 2] if factory is iter else [2, 1])
                    self.assertIs(iterator.__shareable__, sequence.__shareable__)

    def test_set_iterators(self):
        internal = import_module('_testinternalcapi')
        for source in (set(range(5)), SynchronizedSet(range(5)),
                       frozenset(range(5))):
            with self.subTest(source=type(source)):
                iterator = iter(source)
                expected = (threading.Shareable.SYNCHRONIZED
                            if type(source) is SynchronizedSet
                            else threading.Shareable.LOCAL)
                self.assertIs(iterator.__shareable__, expected)
                owner = (0 if type(source) is SynchronizedSet
                         else internal.object_owner_id([]))
                self.assertEqual(internal.object_owner_id(iterator), owner)
                first = next(iterator)
                remaining = set(source) - {first}
                self.assertEqual(set(copy.copy(iterator)), remaining)
                for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                    restored = pickle.loads(pickle.dumps(iterator, protocol))
                    self.assertEqual(set(restored), remaining)
                self.assertEqual(length_hint(iterator), 4)
                self.assertEqual(set(iterator), remaining)
                self.assertEqual(length_hint(iterator), 0)
                self.assertEqual(list(copy.copy(iterator)), [])
                self.assertIs(iterator.__shareable__, expected)

    def test_shared_set_iterator_size_change_is_sticky(self):
        source = SynchronizedSet(range(5))
        iterator = iter(source)
        source.add(10)
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, 'Set changed size'):
                next(iterator)
        source.remove(10)
        with self.assertRaisesRegex(RuntimeError, 'Set changed size'):
            next(iterator)
        with self.assertRaisesRegex(RuntimeError, 'Set changed size'):
            copy.copy(iterator)
        self.assertEqual(length_hint(iterator), 0)

    @threading_helper.requires_working_threading()
    def test_shared_set_iterator_snapshot(self):
        iterator = iter(SynchronizedSet(range(2000)))
        barrier = threading.Barrier(2)
        results = threading.Channel()
        def consume():
            barrier.wait(timeout=SHORT_TIMEOUT)
            values = tuple(iterator)
            results.put(values)
        def snapshot():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(100):
                values = list(copy.copy(iterator))
                assert len(values) == len(set(values))
                assert all(0 <= value < 2000 for value in values)
                assert 0 <= length_hint(iterator) <= 2000
            results.put(True)
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (consume, snapshot)]
        with threading_helper.start_threads(threads):
            pass
        outcomes = [results.get(), results.get()]
        self.assertIn(True, outcomes)
        values = next(value for value in outcomes if type(value) is tuple)
        self.assertEqual(sorted(values), list(range(2000)))

    def test_iterator_copy_pickle_and_state(self):
        for factory in (iter, reversed):
            with self.subTest(factory=factory):
                iterator = factory(SynchronizedList(range(5)))
                next(iterator)
                expected = [1, 2, 3, 4] if factory is iter else [3, 2, 1, 0]
                clone = copy.copy(iterator)
                self.assertIs(clone.__shareable__, threading.Shareable.SYNCHRONIZED)
                self.assertEqual(list(clone), expected)
                for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                    restored = pickle.loads(pickle.dumps(iterator, protocol))
                    self.assertIs(restored.__shareable__, threading.Shareable.SYNCHRONIZED)
                    self.assertEqual(list(restored), expected)
                iterator.__setstate__(2)
                self.assertEqual(length_hint(iterator), 3)
                self.assertEqual(next(iterator), 2)
                iterator.__setstate__(-1)
                self.assertEqual(list(iterator), [])

    @threading_helper.requires_working_threading()
    def test_frozen_mapping_views_are_local_to_creator(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        owner_id = internal.object_owner_id
        internal.object_declare_synchronized(check_access)
        internal.object_declare_synchronized(owner_id)
        mapping = frozendict(a=1)
        results = threading.Channel()
        def worker():
            owner = owner_id([])
            for view in (mapping.keys(), mapping.values(), mapping.items(),
                         MappingProxyType(mapping)):
                assert view.__shareable__ is threading.Shareable.LOCAL
                assert owner_id(view) == owner
                assert check_access(view) is view
            results.put(owner)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertNotEqual(results.get(), owner_id([]))

    @threading_helper.requires_working_threading()
    def test_parallel_shared_iterator(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        for factory, container in ((iter, SynchronizedList),
                                   (reversed, SynchronizedList),
                                   (iter, SynchronizedSet)):
            with self.subTest(factory=factory, container=container):
                self.check_parallel_shared_iterator(factory, container, check_access)

    def check_parallel_shared_iterator(self, factory, container, check_access):
        iterator = factory(container(range(2000)))
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            shared = check_access(iterator)
            barrier.wait(timeout=SHORT_TIMEOUT)
            if number % 2:
                values = tuple(shared)
            else:
                values = []
                for value in shared:
                    values.append(value)
                values = tuple(values)
            results.put(values)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        values = [value for _ in threads for value in results.get()]
        self.assertEqual(sorted(values), list(range(2000)))
        self.assertEqual(list(iterator), [])

    @threading_helper.requires_working_threading()
    def test_shared_iterator_concurrent_state(self):
        for factory in (iter, reversed):
            with self.subTest(factory=factory):
                self.check_shared_iterator_concurrent_state(factory)

    def check_shared_iterator_concurrent_state(self, factory):
        iterator = factory(SynchronizedList(range(10)))
        barrier = threading.Barrier(2)
        results = threading.Channel()
        def reset():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(1000):
                iterator.__setstate__(index % 10)
            results.put(True)
        def consume():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(1000):
                value = next(iterator, None)
                assert value is None or 0 <= value < 10
                assert 0 <= length_hint(iterator) <= 10
            results.put(True)
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (reset, consume)]
        with threading_helper.start_threads(threads):
            pass
        self.assertTrue(results.get())
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_shared_views_observe_updates(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        mapping = SynchronizedDict(a=1)
        keys, values, items = mapping.keys(), mapping.values(), mapping.items()
        proxy = keys.mapping
        results = threading.Channel()
        def worker():
            for view in (keys, values, items, proxy):
                check_access(view)
            assert set(keys) == {'a'}
            assert list(values) == [1]
            assert set(items) == {('a', 1)}
            assert proxy['a'] == 1
            mapping['b'] = 2
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertEqual(set(keys), {'a', 'b'})
        self.assertEqual(set(values), {1, 2})
        self.assertEqual(set(items), {('a', 1), ('b', 2)})
        self.assertEqual(proxy['b'], 2)


class DictionaryIteratorSharingTests(unittest.TestCase):
    factories = (iter, reversed,
                 lambda d: iter(d.keys()), lambda d: reversed(d.keys()),
                 lambda d: iter(d.values()), lambda d: reversed(d.values()),
                 lambda d: iter(d.items()), lambda d: reversed(d.items()))

    def test_metadata_copy_and_pickle(self):
        internal = import_module('_testinternalcapi')
        for container in (dict, SynchronizedDict, frozendict):
            mapping = container((i, i + 10) for i in range(5))
            for factory in self.factories:
                with self.subTest(container=container, factory=factory):
                    iterator = factory(mapping)
                    expected_state = (threading.Shareable.SYNCHRONIZED
                                      if container is SynchronizedDict
                                      else threading.Shareable.LOCAL)
                    self.assertIs(iterator.__shareable__, expected_state)
                    owner = (0 if container is SynchronizedDict
                             else internal.object_owner_id([]))
                    self.assertEqual(internal.object_owner_id(iterator), owner)
                    expected = list(factory(mapping))[1:]
                    next(iterator)
                    self.assertEqual(length_hint(iterator), 4)
                    self.assertEqual(list(copy.copy(iterator)), expected)
                    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                        restored = pickle.loads(pickle.dumps(iterator, protocol))
                        self.assertEqual(list(restored), expected)
                    self.assertEqual(list(iterator), expected)
                    self.assertEqual(list(copy.copy(iterator)), [])
                    self.assertEqual(length_hint(iterator), 0)
                    self.assertIs(iterator.__shareable__, expected_state)

    def test_sticky_size_change(self):
        for factory in self.factories:
            with self.subTest(factory=factory):
                mapping = SynchronizedDict(a=1, b=2)
                iterator = factory(mapping)
                mapping['c'] = 3
                with self.assertRaisesRegex(RuntimeError, 'changed size'):
                    next(iterator)
                del mapping['c']
                with self.assertRaisesRegex(RuntimeError, 'changed size'):
                    next(iterator)
                with self.assertRaisesRegex(RuntimeError, 'changed size'):
                    copy.copy(iterator)
                self.assertEqual(length_hint(iterator), 0)

    def test_keys_changed_without_size_change(self):
        for factory in (iter, lambda d: iter(d.values()), lambda d: iter(d.items())):
            mapping = SynchronizedDict(a=1, b=2)
            iterator = factory(mapping)
            next(iterator)
            del mapping['a']
            mapping['c'] = 3
            next(iterator)
            with self.assertRaisesRegex(RuntimeError, 'keys changed'):
                next(iterator)
            self.assertEqual(list(iterator), [])

    def test_split_table_and_deleted_entries(self):
        internal = import_module('_testinternalcapi')
        class Record:
            pass
        record = Record()
        record.a, record.b, record.c = 1, 2, 3
        split = record.__dict__
        internal.object_declare_synchronized(split)
        general = SynchronizedDict((i, i + 10) for i in range(5))
        unicode = SynchronizedDict(a=1, b=2, c=3)
        del general[1]
        del unicode['b']
        for mapping in (split, general, unicode):
            for factory in self.factories:
                with self.subTest(mapping=mapping, factory=factory):
                    expected = list(factory(dict(mapping)))
                    iterator = factory(mapping)
                    self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
                    self.assertEqual(list(copy.copy(iterator)), expected)
                    self.assertEqual(list(iterator), expected)

    @threading_helper.requires_working_threading()
    def test_parallel_consumers(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        for factory in self.factories:
            with self.subTest(factory=factory):
                self.check_parallel_consumers(factory, check_access)

    def check_parallel_consumers(self, factory, check_access):
        mapping = SynchronizedDict((i, i + 10) for i in range(1000))
        expected = sorted(factory(mapping))
        iterator = factory(mapping)
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            shared = check_access(iterator)
            barrier.wait(timeout=SHORT_TIMEOUT)
            if number % 2:
                values = tuple(shared)
            else:
                values = tuple(value for value in shared)
            results.put(values)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        actual = [value for _ in threads for value in results.get()]
        self.assertEqual(sorted(actual), expected)
        self.assertEqual(list(iterator), [])

    @threading_helper.requires_working_threading()
    def test_parallel_snapshot(self):
        for factory in self.factories:
            with self.subTest(factory=factory):
                self.check_parallel_snapshot(factory)

    def check_parallel_snapshot(self, factory):
        mapping = SynchronizedDict((i, i + 10) for i in range(1000))
        expected = tuple(factory(mapping))
        iterator = factory(mapping)
        barrier = threading.Barrier(2)
        results = threading.Channel()
        def consume():
            barrier.wait(timeout=SHORT_TIMEOUT)
            results.put(tuple(iterator))
        def snapshot():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(30):
                values = tuple(copy.copy(iterator))
                assert values == expected[len(expected) - len(values):]
                assert 0 <= length_hint(iterator) <= len(expected)
            results.put(True)
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (consume, snapshot)]
        with threading_helper.start_threads(threads):
            pass
        outcomes = [results.get(), results.get()]
        self.assertIn(True, outcomes)
        actual = next(value for value in outcomes if type(value) is tuple)
        self.assertEqual(actual, expected)

    @threading_helper.requires_working_threading()
    def test_concurrent_dictionary_changes(self):
        mapping = SynchronizedDict((i, -i) for i in range(32))
        barrier = threading.Barrier(2)
        results = threading.Channel()
        def mutate():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for key in range(32, 2032):
                mapping[key] = -key
                del mapping[key - 32]
            results.put(True)
        def consume():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(100):
                for factory in (iter, reversed):
                    iterator = factory(mapping.items())
                    try:
                        for key, value in iterator:
                            assert value == -key
                    except RuntimeError as error:
                        assert 'changed' in str(error)
            results.put(True)
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (mutate, consume)]
        with threading_helper.start_threads(threads):
            pass
        self.assertTrue(results.get())
        self.assertTrue(results.get())


if __name__ == '__main__':
    unittest.main()
