"""PEP 805 shallow ownership transfer through a native TransferBox."""

import threading
import types
import unittest
import weakref

from test.support import gc_collect, threading_helper
from test.support.import_helper import import_module


capi = import_module('_testinternalcapi')
TransferBox = threading.TransferBox


class TransferBoxTests(unittest.TestCase):
    def test_generic_alias(self):
        alias = TransferBox[int]
        self.assertIsInstance(alias, types.GenericAlias)
        self.assertIs(alias.__origin__, TransferBox)
        self.assertEqual(alias.__args__, (int,))
        self.assertEqual(alias(42).claim(), 42)

    def test_shallow_copy(self):
        child = []
        original = [child]
        box = TransferBox(original)
        original.append(1)
        value = box.claim()
        self.assertIsNot(value, original)
        self.assertEqual(value, [child])
        self.assertIs(value[0], child)
        self.assertIs(capi.object_check_access(value), value)
        with self.assertRaisesRegex(ValueError, 'already been claimed'):
            box.claim()

    def test_mapping_and_set_copy(self):
        for original in ({'x': 1}, {1, 2}):
            with self.subTest(type=type(original)):
                value = TransferBox(original).claim()
                self.assertEqual(value, original)
                self.assertIsNot(value, original)

    def test_tuple_subclass_copy(self):
        class Tuple(tuple):
            pass

        original = Tuple((1, 2))
        original.x = 3
        value = TransferBox(original).claim()
        self.assertIs(type(value), Tuple)
        self.assertIsNot(value, original)
        self.assertEqual(value, (1, 2))
        self.assertEqual(value.x, 3)

    def test_shareable_identity(self):
        shared = object()
        capi.object_declare_synchronized(shared)
        for value in (None, 42, ([],), frozendict(x=[]),
                      threading.ThreadGroup(), shared):
            with self.subTest(type=type(value)):
                self.assertIs(TransferBox(value).claim(), value)

    def test_box_is_synchronized(self):
        box = TransferBox([])
        self.assertIs(box.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertIs(TransferBox.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(TransferBox(box).claim(), box)
        self.assertEqual(box.claim(), [])

    def test_sink(self):
        group = threading.current_thread().group
        box = TransferBox([1], sink=group)
        self.assertIs(box.sink, group)
        with self.assertRaises(TypeError):
            box.sink = object()
        self.assertIs(box.sink, group)
        box.sink = threading.ThreadGroup()
        with self.assertRaises(ValueError):
            box.claim()
        box.sink = None
        self.assertIsNone(box.sink)
        self.assertEqual(box.claim(), [1])

    def test_argument_validation(self):
        with self.assertRaises(TypeError):
            TransferBox()
        with self.assertRaises(TypeError):
            TransferBox(1, None, 2)
        with self.assertRaises(TypeError):
            TransferBox(1, sink=object())
        with self.assertRaises(TypeError):
            TransferBox(1, unknown=True)
        self.assertIsNone(TransferBox(obj=1).sink)

    def test_copy_exception(self):
        class C:
            def __copy__(self):
                raise RuntimeError('cannot copy')

        with self.assertRaisesRegex(RuntimeError, 'cannot copy'):
            TransferBox(C())

    def test_copy_cannot_return_original(self):
        class C:
            def __copy__(self):
                return self

        original = C()
        with self.assertRaisesRegex(TypeError, 'unaliased'):
            TransferBox(original)
        self.assertIs(capi.object_check_access(original), original)

    def test_copy_cannot_return_aliased_local(self):
        alias = []

        class C:
            def __copy__(self):
                return alias

        with self.assertRaisesRegex(TypeError, 'unaliased'):
            TransferBox(C())
        self.assertIs(capi.object_check_access(alias), alias)

    @threading_helper.requires_working_threading()
    def test_cross_group_claim(self):
        check_access = capi.object_check_access
        capi.object_declare_synchronized(check_access)
        owner_id = capi.object_owner_id
        capi.object_declare_synchronized(owner_id)
        original = [1]
        group = threading.ThreadGroup()
        box = TransferBox(original, sink=group)
        results = SynchronizedList()
        with self.assertRaisesRegex(ValueError, 'another ThreadGroup'):
            box.claim()

        def work():
            value = box.claim()
            results.append(value == [1])
            results.append(check_access(value) is value)
            results.append(owner_id(value) ==
                           owner_id(object()))
            try:
                check_access(original)
            except IllegalThreadAccessException:
                results.append('original remains foreign')

        worker = threading.Thread(group=group, target=work)
        with threading_helper.start_threads([worker]):
            pass
        self.assertEqual(results, [True, True, True, 'original remains foreign'])

    @threading_helper.requires_working_threading()
    def test_foreign_source_rejected_before_copy(self):
        calls = []

        class C:
            def __copy__(self):
                calls.append('copied')
                return C()

        original = C()
        errors = SynchronizedList()

        def work():
            try:
                TransferBox(original)
            except IllegalThreadAccessException:
                errors.append('denied')

        worker = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([worker]):
            pass
        self.assertEqual(errors, ['denied'])
        self.assertEqual(calls, [])

    @threading_helper.requires_working_threading()
    def test_claim_race_has_one_winner(self):
        check_access = capi.object_check_access
        capi.object_declare_synchronized(check_access)
        box = TransferBox([1])
        start = threading.Barrier(8)
        winners, losers = SynchronizedList(), SynchronizedList()

        def work():
            start.wait()
            try:
                value = box.claim()
            except ValueError:
                losers.append(True)
            else:
                winners.append(check_access(value) is value)

        workers = [threading.Thread(group=threading.ThreadGroup(), target=work)
                   for _ in range(8)]
        with threading_helper.start_threads(workers):
            pass
        self.assertEqual(winners, [True])
        self.assertEqual(len(losers), 7)

    def test_abandoned_copy_is_collected(self):
        finalized = []

        class C:
            def __copy__(self):
                other = C()
                other.is_copy = True
                return other

            def __del__(self):
                if getattr(self, 'is_copy', False):
                    finalized.append(True)

        original = C()
        box = TransferBox(original)
        del box
        gc_collect()
        self.assertEqual(finalized, [True])

    def test_box_cycle_is_collected(self):
        class Child:
            pass

        child = Child()
        original = {'child': child}
        box = TransferBox(original)
        child.box = box
        ref = weakref.ref(child)
        del original, child, box
        gc_collect()
        self.assertIsNone(ref())


if __name__ == '__main__':
    unittest.main()
