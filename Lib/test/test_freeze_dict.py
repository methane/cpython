"""In-place dictionary freezing, aliases, and reentrant mutation."""

import gc
import threading
import unittest
import weakref

from test import support
from test.support import threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


_testinternalcapi = import_module('_testinternalcapi')
freeze_dict = freeze


class FreezeDictTests(unittest.TestCase):
    def test_protocol(self):
        value = {'a': 1}
        method = value.__freeze__
        self.assertIs(method(), value)
        self.assertIs(type(value), frozendict)
        self.assertIs(method(), value)
        self.assertIs(freeze(value), value)

    def test_shallow_values(self):
        child = []
        value = {'child': child}
        freeze(value)
        child.append(1)
        self.assertIs(value['child'], child)
        self.assertEqual(value['child'], [1])
        with self.assertRaises(TypeError):
            hash(value)

    def test_saved_read_methods(self):
        value = {'a': 1, 'b': 2}
        get, copy = value.get, value.copy
        keys, values, items = value.keys, value.values, value.items
        reverse = value.__reversed__
        freeze(value)
        self.assertEqual(get('a'), 1)
        self.assertEqual(list(keys()), ['a', 'b'])
        self.assertEqual(list(values()), [1, 2])
        self.assertEqual(list(items()), [('a', 1), ('b', 2)])
        self.assertEqual(list(reverse()), ['b', 'a'])
        result = copy()
        self.assertIs(type(result), dict)
        self.assertEqual(result, value)

    def test_fromkeys_iteration_freezes_destination(self):
        for stage in ('iter', 'next'):
            for empty in (False, True):
                with self.subTest(stage=stage, empty=empty):
                    value = {'a': 1}

                    class C(dict):
                        def __new__(cls):
                            return value

                    class Source:
                        def __iter__(self):
                            if stage == 'iter':
                                freeze(value)
                            return self.generate()

                        def generate(self):
                            if stage == 'next':
                                freeze(value)
                            if not empty:
                                yield 'b'

                    with self.assertRaises(TypeError):
                        C.fromkeys(Source(), 2)
                    self.assertEqual(value, {'a': 1})

    def test_fromkeys_watcher_freezes_destination(self):
        capi = import_module('_testcapi')
        watcher = capi.add_dict_watcher(3)
        try:
            for source in ({'b': None}, frozendict(b=None), {'b'}, frozenset({'b'})):
                with self.subTest(source=source):
                    value = {'a': 1}

                    class C(dict):
                        def __new__(cls):
                            return value

                    capi.watch_dict(watcher, value)
                    try:
                        with self.assertRaises(TypeError):
                            C.fromkeys(source, 2)
                        self.assertEqual(value, {'a': 1})
                    finally:
                        capi.unwatch_dict(watcher, value)
        finally:
            capi.clear_dict_watcher(watcher)

    def test_identity_and_readers(self):
        for value in ({}, {'a': 1, 'b': 2}, {1: 2, 3: 4}):
            with self.subTest(value=value):
                expected = frozendict(value)
                alias = value
                iterator = iter(value)
                view = value.items()
                self.assertIs(freeze_dict(value), value)
                self.assertIs(type(alias), frozendict)
                self.assertEqual(value, expected)
                self.assertEqual(list(iterator), list(expected))
                self.assertEqual(list(view), list(expected.items()))
                self.assertEqual(hash(value), hash(expected))
                self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
                self.assertIs(freeze_dict(value), value)

    def test_split_dictionary(self):
        class C:
            pass

        first, second = C(), C()
        first.a = 1
        first.b = 2
        second.b = 3
        second.a = 4
        value = second.__dict__
        iterator = iter(value)
        self.assertEqual(next(iterator), 'b')
        freeze_dict(value)
        self.assertIs(second.__dict__, value)
        self.assertEqual(list(iterator), ['a'])
        self.assertEqual(list(value.items()), [('b', 3), ('a', 4)])
        first.c = 5
        self.assertEqual(value, {'b': 3, 'a': 4})
        with self.assertRaises(TypeError):
            second.a = 10
        with self.assertRaises(TypeError):
            second.c = 10

    def test_split_copy(self):
        class C:
            pass

        owner = C()
        owner.a = 1
        value = owner.__dict__.copy()
        freeze_dict(value)
        owner.a = 2
        owner.b = 3
        self.assertEqual(value, {'a': 1})
        self.assertEqual(owner.__dict__, {'a': 2, 'b': 3})

    @threading_helper.requires_working_threading()
    def test_foreign_group_rejected(self):
        value = {'a': 1}
        results = threading.Channel()

        def worker():
            try:
                freeze_dict(value)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(type(value), dict)

    def test_watched_dictionary(self):
        capi = import_module('_testcapi')
        value = {'a': 1}
        watcher = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(watcher, value)
            self.assertIs(freeze_dict(value), value)
            self.assertEqual(capi.get_dict_watcher_events(), ['freeze'])
            freeze_dict(value)
            self.assertEqual(capi.get_dict_watcher_events(), ['freeze'])
            self.assertIs(type(value), frozendict)
        finally:
            capi.unwatch_dict(watcher, value)
            capi.clear_dict_watcher(watcher)
        self.assertEqual(value, {'a': 1})

    def test_watcher_freezes_during_mutation(self):
        capi = import_module('_testcapi')
        operations = (
            ('__setitem__', ('a', 2)), ('__setitem__', ('b', 2)),
            ('__delitem__', ('a',)), ('pop', ('a',)), ('popitem', ()),
            ('clear', ()), ('setdefault', ('b', 2)),
            ('update', ({'b': 2},)),
        )
        watcher = capi.add_dict_watcher(3)
        try:
            for name, args in operations:
                for split in (False, True):
                    with self.subTest(name=name, split=split):
                        class C:
                            pass
                        owner = C()
                        owner.a = 1
                        value = owner.__dict__ if split else {'a': 1}
                        capi.watch_dict(watcher, value)
                        try:
                            with self.assertRaises(TypeError):
                                getattr(value, name)(*args)
                            self.assertIs(type(value), frozendict)
                            self.assertEqual(value, {'a': 1})
                            self.assertEqual(hash(value), hash(frozendict(a=1)))
                        finally:
                            capi.unwatch_dict(watcher, value)
            for source in ({'a': 1}, [('a', 1)]):
                value = {}
                capi.watch_dict(watcher, value)
                try:
                    with self.assertRaises(TypeError):
                        value.update(source)
                    self.assertEqual(value, {})
                finally:
                    capi.unwatch_dict(watcher, value)
        finally:
            capi.clear_dict_watcher(watcher)

    def test_freeze_watcher_error(self):
        capi = import_module('_testcapi')
        value = {'a': 1}
        watcher = capi.add_dict_watcher(1)
        try:
            capi.watch_dict(watcher, value)
            with support.catch_unraisable_exception() as caught:
                self.assertIs(freeze_dict(value), value)
                self.assertIs(caught.unraisable.exc_type, RuntimeError)
                self.assertIn('PyDict_EVENT_FROZEN', caught.unraisable.err_msg)
            self.assertIs(type(value), frozendict)
            self.assertEqual(value, {'a': 1})
        finally:
            capi.unwatch_dict(watcher, value)
            capi.clear_dict_watcher(watcher)

    def test_frozen_watcher_lifetime(self):
        capi = import_module('_testcapi')
        watcher = capi.add_dict_watcher(0)
        try:
            value = {}
            value['self'] = value
            capi.watch_dict(watcher, value)
            freeze_dict(value)
            del value
            support.gc_collect()
            events = capi.get_dict_watcher_events()
            self.assertEqual(events[0], 'freeze')
            self.assertEqual(events[-1], 'dealloc')
            self.assertIn('clear', events)
            self.assertEqual(events.count('freeze'), 1)
        finally:
            capi.clear_dict_watcher(watcher)

    def test_watcher_freezes_attribute_dictionary(self):
        capi = import_module('_testcapi')
        class C:
            pass

        def store(owner, value):
            owner.a = value

        for combined in (False, True):
            owner = C()
            owner.a = 1
            if combined:
                owner.__dict__ = {"a": 1}
            value = owner.__dict__
            for _ in range(100):
                store(owner, 1)
            watcher = capi.add_dict_watcher(3)
            try:
                capi.watch_dict(watcher, value)
                with self.assertRaises(TypeError):
                    store(owner, 2)
                self.assertEqual(owner.a, 1)
                self.assertIs(type(value), frozendict)
            finally:
                capi.unwatch_dict(watcher, value)
                capi.clear_dict_watcher(watcher)

    def test_module_globals(self):
        import types
        module = types.ModuleType('frozen_globals_test')
        namespace = module.__dict__
        exec('def read(): return answer\n'
             'def write():\n global answer\n answer = 43\n'
             'def outer():\n def inner(): return answer\n return inner\n'
             'answer = 42\n', namespace)
        read, write, outer = module.read, module.write, module.outer
        for _ in range(200):
            self.assertEqual(read(), 42)
        freeze_dict(namespace)
        self.assertEqual(read(), 42)
        self.assertEqual(outer()(), 42)
        with self.assertRaises(TypeError):
            write()
        for _ in range(200):
            self.assertIs(module.__dict__, namespace)
            self.assertEqual(module.answer, 42)

    def test_frozen_builtins_reference_counts(self):
        import types
        module = types.ModuleType('frozen_builtins_test')
        module.len = len
        namespace = {'__builtins__': module.__dict__}
        exec('def read(): return len(())', namespace)
        read = namespace['read']
        for _ in range(200):
            self.assertEqual(read(), 0)
        freeze_dict(module.__dict__)
        self.assertEqual(read(), 0)
        exec('def read_after(): return len(())', namespace)
        self.assertEqual(namespace['read_after'](), 0)
        ref = weakref.ref(module)
        del read, namespace, module
        support.gc_collect()
        self.assertIsNone(ref())

    def test_saved_assignment(self):
        value = {'a': 1}
        method = value.__setitem__
        freeze_dict(value)
        for key in ('a', 'b'):
            with self.assertRaises(TypeError):
                method(key, 2)
        self.assertEqual(value, {'a': 1})

    def test_saved_bulk_mutators(self):
        for initial in ({}, {'a': 1}):
            for name, args in (('update', ()), ('update', ({},)),
                               ('update', ({'b': 2},)), ('__init__', ()),
                               ('__init__', ({'b': 2},)), ('__ior__', ({},)),
                               ('__ior__', ({'b': 2},)), ('clear', ())):
                with self.subTest(initial=initial, name=name, args=args):
                    value = initial.copy()
                    method = getattr(value, name)
                    freeze_dict(value)
                    with self.assertRaises(TypeError):
                        method(*args)
                    self.assertEqual(value, initial)

    def test_bulk_iterator_callback(self):
        for name in ('update', '__init__', '__ior__'):
            for empty in (False, True):
                for fail in (False, True):
                    with self.subTest(name=name, empty=empty, fail=fail):
                        value = {'a': 1}

                        def source():
                            freeze_dict(value)
                            if fail:
                                raise ValueError('iteration failed')
                            if not empty:
                                yield ('b', 2)

                        with self.assertRaises(ValueError if fail else TypeError):
                            getattr(value, name)(source())
                        self.assertEqual(value, {'a': 1})

    def test_bulk_mapping_callback(self):
        for stage in ('keys', 'getitem'):
            for fail in (False, True):
                with self.subTest(stage=stage, fail=fail):
                    value = {'a': 1}

                    def callback():
                        freeze_dict(value)
                        if fail:
                            raise ValueError('mapping failed')

                    class Mapping:
                        def keys(self):
                            if stage == 'keys':
                                callback()
                                return []
                            return ['b']

                        def __getitem__(self, key):
                            callback()
                            return 2

                    with self.assertRaises(ValueError if fail else TypeError):
                        value.update(Mapping())
                    self.assertEqual(value, {'a': 1})

    def test_bulk_stops_after_finalizer(self):
        class Value:
            def __del__(self):
                freeze_dict(value)

        value = {'a': Value()}
        with self.assertRaises(TypeError):
            value.update({'a': 1, 'b': 2})
        self.assertEqual(value, {'a': 1})

    def test_merge_existing_key_callback(self):
        capi = import_module('_testlimitedcapi')
        for mapping in (False, True):
            with self.subTest(mapping=mapping):
                class Key:
                    def __hash__(self):
                        return 42

                    def __eq__(self, other):
                        freeze_dict(value)
                        return True

                key = Key()
                value = {key: 1}
                other = {Key(): 2}
                if mapping:
                    from collections import UserDict
                    other = UserDict(other)
                with self.assertRaises(TypeError):
                    capi.dict_merge(value, other, 0)
                self.assertEqual(len(value), 1)
                self.assertEqual(value[key], 1)

    def test_saved_deletion(self):
        for initial in ({}, {'a': 1}):
            for name, args in (('__delitem__', ('a',)), ('pop', ('a',)),
                               ('pop', ('missing', None)), ('popitem', ())):
                with self.subTest(initial=initial, name=name, args=args):
                    value = initial.copy()
                    method = getattr(value, name)
                    freeze_dict(value)
                    with self.assertRaises(TypeError):
                        method(*args)
                    self.assertEqual(value, initial)

    def test_deletion_hash_callback(self):
        for name in ('__delitem__', 'pop'):
            for initial in ({42: 1}, {'a': 1}):
                with self.subTest(name=name, initial=initial):
                    value = initial.copy()

                    class Key:
                        def __hash__(self):
                            freeze_dict(value)
                            hash(value)
                            return 42

                    with self.assertRaises(TypeError):
                        getattr(value, name)(Key())
                    self.assertEqual(value, initial)
                    self.assertEqual(hash(value), hash(frozendict(initial)))

    def test_deletion_equality_callback(self):
        for name in ('__delitem__', 'pop'):
            for outcome in (False, True, ValueError):
                with self.subTest(name=name, outcome=outcome):
                    class Key:
                        def __hash__(self):
                            return 42

                        def __eq__(self, other):
                            freeze_dict(value)
                            hash(value)
                            if outcome is ValueError:
                                raise ValueError('comparison failed')
                            return outcome

                    key = Key()
                    value = {key: 1}
                    error = ValueError if outcome is ValueError else TypeError
                    with self.assertRaises(error):
                        getattr(value, name)(Key())
                    self.assertEqual(len(value), 1)
                    self.assertIs(next(iter(value)), key)
                    self.assertEqual(value[key], 1)
                    self.assertEqual(hash(value), hash(frozendict({key: 1})))

    def test_deletion_predicate_callback(self):
        for outcome in (False, True, ValueError):
            with self.subTest(outcome=outcome):
                value = {'a': 1}

                def predicate(item):
                    self.assertEqual(item, 1)
                    freeze_dict(value)
                    if outcome is ValueError:
                        raise ValueError('predicate failed')
                    return outcome

                error = ValueError if outcome is ValueError else TypeError
                with self.assertRaises(error):
                    _testinternalcapi.dict_delitemif(value, 'a', predicate)
                self.assertEqual(value, {'a': 1})

    def test_capi_deletion_callbacks(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        for operation in (limited.dict_delitem, capi.dict_pop,
                          capi.dict_pop_null):
            for callback in ('hash', 'equality'):
                with self.subTest(operation=operation, callback=callback):
                    armed = False

                    class Key:
                        def __hash__(self):
                            if armed and callback == 'hash':
                                freeze_dict(value)
                            return 42

                        def __eq__(self, other):
                            freeze_dict(value)
                            return True

                    key = Key()
                    value = {key: 1}
                    armed = True
                    with self.assertRaises(TypeError):
                        operation(value, Key())
                    self.assertEqual(len(value), 1)
                    self.assertIs(next(iter(value)), key)
                    self.assertEqual(value[key], 1)

    def test_hash_callback(self):
        for initial in ({}, {'a': 1}):
            for method_name in ('__setitem__', 'setdefault'):
                with self.subTest(initial=initial, method=method_name):
                    value = initial.copy()

                    class Key:
                        def __hash__(self):
                            freeze_dict(value)
                            hash(value)
                            return 42

                    with self.assertRaises(TypeError):
                        getattr(value, method_name)(Key(), 2)
                    self.assertEqual(value, initial)
                    self.assertEqual(hash(value), hash(frozendict(initial)))

    def test_equality_callback(self):
        for equal in (False, True):
            for method_name in ('__setitem__', 'setdefault'):
                with self.subTest(equal=equal, method=method_name):
                    class Key:
                        def __hash__(self):
                            return 42

                        def __eq__(self, other):
                            freeze_dict(value)
                            hash(value)
                            return equal

                    key = Key()
                    value = {key: 1}
                    with self.assertRaises(TypeError):
                        getattr(value, method_name)(Key(), 2)
                    self.assertEqual(len(value), 1)
                    self.assertIs(next(iter(value)), key)
                    self.assertEqual(value[key], 1)
                    self.assertEqual(hash(value), hash(frozendict({key: 1})))

    def test_callback_exception(self):
        for method_name in ('__setitem__', 'setdefault'):
            with self.subTest(method=method_name):
                class Key:
                    def __hash__(self):
                        return 42

                    def __eq__(self, other):
                        freeze_dict(value)
                        raise ValueError('comparison failed')

                key = Key()
                value = {key: 1}
                with self.assertRaisesRegex(ValueError, 'comparison failed'):
                    getattr(value, method_name)(Key(), 2)
                self.assertEqual(value[key], 1)

    def test_cycle(self):
        class Payload:
            pass

        payload = Payload()
        ref = weakref.ref(payload)
        value = {'payload': payload}
        value['self'] = value
        freeze_dict(value)
        object_id = id(value)
        del value, payload
        support.gc_collect()
        self.assertIsNone(ref())
        self.assertFalse(any(id(obj) == object_id for obj in gc.get_objects()))

    @support.nomemtest
    def test_split_allocation_failure(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            dict_freeze = freeze

            class C:
                pass

            failures = 0
            for start in range(10):
                owner = C()
                owner.a = 1
                value = owner.__dict__
                failed = False
                _testcapi.set_nomemory(start, start + 1)
                try:
                    dict_freeze(value)
                except MemoryError:
                    failed = True
                finally:
                    _testcapi.remove_mem_hooks()
                assert owner.__dict__ is value
                assert value == {'a': 1}
                if failed:
                    failures += 1
                    assert type(value) is dict
                    owner.a = 2
                    assert value == {'a': 2}
                else:
                    assert type(value) is frozendict
            assert failures > 0
        ''')


if __name__ == '__main__':
    unittest.main()
