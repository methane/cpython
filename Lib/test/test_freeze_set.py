"""In-place set freezing, including aliases and reentrant mutation."""

import threading
import unittest
import weakref

from test.support import gc_collect, threading_helper
from test.support.import_helper import import_module


class FreezeSetTests(unittest.TestCase):
    def test_identity_aliases_and_hash(self):
        value = {1, 2}
        alias = value
        ref = weakref.ref(value)
        iterator = iter(value)
        self.assertIs(freeze(value), value)
        self.assertIs(type(alias), frozenset)
        self.assertIs(ref(), value)
        self.assertEqual(set(iterator), {1, 2})
        self.assertEqual(hash(value), hash(frozenset({1, 2})))
        self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(freeze(value), value)

    def test_saved_mutators(self):
        operations = (
            ('add', (3,)), ('clear', ()), ('discard', (1,)),
            ('remove', (1,)), ('pop', ()), ('update', ([3],)),
            ('update', ()), ('difference_update', ([1],)),
            ('difference_update', ()), ('intersection_update', ([1],)),
            ('intersection_update', ()), ('symmetric_difference_update', ({3},)),
            ('__init__', ([3],)), ('__init__', ()),
            ('__ior__', ({3},)), ('__iand__', ({1},)),
            ('__isub__', ({1},)), ('__ixor__', ({3},)),
        )
        for name, args in operations:
            with self.subTest(name=name, args=args):
                value = {1, 2}
                method = getattr(value, name)
                freeze(value)
                original_hash = hash(value)
                with self.assertRaises(TypeError):
                    method(*args)
                self.assertEqual(value, {1, 2})
                self.assertEqual(hash(value), original_hash)

    def test_saved_freeze_is_idempotent(self):
        value = {1}
        method = value.__freeze__
        self.assertIs(method(), value)
        self.assertIs(method(), value)

    def test_reentrant_hash(self):
        for method_name in ('add', 'discard', 'remove'):
            with self.subTest(method=method_name):
                value = {1, 2}

                class Key:
                    def __hash__(self):
                        freeze(value)
                        hash(value)
                        return 3

                with self.assertRaises(TypeError):
                    getattr(value, method_name)(Key())
                self.assertEqual(value, {1, 2})
                self.assertEqual(hash(value), hash(frozenset({1, 2})))

    def test_reentrant_equality(self):
        for method_name in ('add', 'discard', 'remove', 'update',
                            'difference_update', 'intersection_update',
                            'symmetric_difference_update', '__iand__'):
            with self.subTest(method=method_name):
                class Key:
                    def __hash__(self):
                        return 42

                    def __eq__(self, other):
                        freeze(value)
                        hash(value)
                        return method_name != 'add'

                key = Key()
                value = {key}
                argument = Key()
                if method_name not in ('add', 'discard', 'remove'):
                    argument = {argument}
                with self.assertRaises(TypeError):
                    getattr(value, method_name)(argument)
                self.assertEqual(len(value), 1)
                self.assertIs(next(iter(value)), key)
                self.assertEqual(hash(value), hash(frozenset([key])))

    def test_reentrant_iteration(self):
        for method_name in ('update', 'difference_update',
                            'intersection_update', 'symmetric_difference_update'):
            with self.subTest(method=method_name):
                value = {1, 2}

                def iterable():
                    freeze(value)
                    hash(value)
                    yield 3

                with self.assertRaises(TypeError):
                    getattr(value, method_name)(iterable())
                self.assertEqual(value, {1, 2})
                self.assertEqual(hash(value), hash(frozenset({1, 2})))

    def test_callback_exception_is_preserved(self):
        for method_name in ('add', 'discard', 'remove'):
            with self.subTest(method=method_name):
                class Key:
                    def __hash__(self):
                        return 42

                    def __eq__(self, other):
                        freeze(value)
                        raise ValueError('comparison failed')

                key = Key()
                value = {key}
                with self.assertRaisesRegex(ValueError, 'comparison failed'):
                    getattr(value, method_name)(Key())
                self.assertIs(type(value), frozenset)
                self.assertEqual(len(value), 1)
                self.assertIs(next(iter(value)), key)

    def test_reinitialization_finalizer(self):
        hashes = []

        class Key:
            def __del__(self):
                freeze(value)
                hashes.append(hash(value))

        value = {Key()}
        with self.assertRaises(TypeError):
            value.__init__([3])
        self.assertIs(type(value), frozenset)
        self.assertEqual(value, frozenset())
        self.assertEqual(hashes, [hash(value)])

    def test_cycle_is_collected(self):
        class Key:
            pass

        key = Key()
        value = {key}
        key.value = value
        ref = weakref.ref(key)
        freeze(value)
        del value, key
        gc_collect()
        self.assertIsNone(ref())

    def test_capi_mutation_rejected(self):
        capi = import_module('_testlimitedcapi')
        value = freeze({1, 2})
        for method, args in ((capi.set_add, (3,)),
                             (capi.set_clear, ()),
                             (capi.set_discard, (1,)),
                             (capi.set_pop, ())):
            with self.subTest(method=method):
                with self.assertRaises((TypeError, SystemError)):
                    method(value, *args)
                self.assertEqual(value, {1, 2})

    def test_capi_unique_reference_cannot_mutate(self):
        capi = import_module('_testlimitedcapi')
        capi.test_frozen_set_add_in_capi()

    @threading_helper.requires_working_threading()
    def test_foreign_freeze_rejected(self):
        value = {1, 2}
        results = threading.Channel()

        def work():
            try:
                freeze(value)
            except IllegalThreadAccessException:
                results.put('denied')

        worker = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([worker]):
            pass
        self.assertEqual(results.get(), 'denied')
        self.assertIs(type(value), set)


if __name__ == '__main__':
    unittest.main()
