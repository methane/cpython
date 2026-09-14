"""Exercise opt-in regions through real executors, including their exits."""

import builtins
import collections
import gc
import math
import operator
import os
import random
import struct
import sys
import sysconfig
import types
import unittest
import weakref
from unittest import mock

from test import support
from test.test_capi.test_opt import get_all_executors, get_opnames
from _testinternalcapi import TIER2_THRESHOLD


SETTINGS = {
    "PYTHON_TIER2_INT_REGIONS": "1",
    "PYTHON_TIER2_BUILTIN_REGIONS": "1",
    "PYTHON_TIER2_FLOAT_FUSION": "1",
}

requires_call_regions = unittest.skipIf(
    sysconfig.get_config_var("WITH_DTRACE") or sys.platform == "emscripten",
    "call regions are disabled with DTrace or Emscripten",
)


def arithmetic(expression):
    namespace = {}
    exec(
        "def run(a, b, c, limit, n):\n"
        "    result = None\n"
        "    for _ in range(n):\n"
        f"        result = {expression}\n"
        "    return result\n",
        namespace,
    )
    return namespace["run"]


@support.requires_specialization
@support.requires_jit_enabled
@unittest.skipIf(support.Py_GIL_DISABLED, "regions require the GIL")
@unittest.skipIf(sys.maxsize <= 2**32, "regions require 64-bit operands")
@unittest.skipIf(os.getenv("PYTHON_UOPS_OPTIMIZE") == "0", "requires optimizer")
class TestRegions(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, SETTINGS))

    def warm_class_attributes(self, nargs=3, order=None):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        if order is None:
            order = list(range(nargs))
        names = [f"a{i}" for i in range(nargs)]
        signature = ", ".join(names)
        namespace = {}
        exec(
            f"class Record:\n"
            f"    def __init__(self, {signature}):\n"
            + "".join(f"        self.{names[i]} = {names[i]}\n" for i in order)
            + f"def run(cls, {signature}, n):\n"
            "    result = None\n"
            "    for _ in range(n):\n"
            f"        result = cls({signature})\n"
            "    return result\n",
            namespace,
        )
        cls, run = namespace["Record"], namespace["run"]
        args = [object() for _ in names]
        run(cls, *args, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_CLASS_ATTRIBUTES")
        return cls, run, args, ex

    def warm_list_call(self, expression="self.cells[index]", slots=False):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        namespace = {"__builtins__": vars(builtins)}
        exec(
            "class Receiver:\n"
            + ("    __slots__ = ('cells',)\n" if slots else "")
            + "    def get(self, index):\n"
            f"        return {expression}\n"
            "def run(receiver, index, n):\n"
            "    result = None\n"
            "    for _ in range(n):\n"
            "        result = receiver.get(index)\n"
            "    return result\n",
            namespace,
        )
        receiver = namespace["Receiver"]()
        receiver.cells = [[object()], [], [object(), object()]]
        run = namespace["run"]
        run(receiver, 0, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_LIST")
        return namespace, receiver, run, ex

    def warm_len_subscript(self, comparison="==", constant=False):
        namespace = {}
        right = "1" if constant else "limit"
        exec("def run(container, index, limit, n):\n"
             "    result = None\n"
             "    for _ in range(n):\n"
             f"        result = len(container[index]) {comparison} {right}\n"
             "    return result\n", namespace)
        run = namespace["run"]
        run([[object()]], 0, 1, TIER2_THRESHOLD)
        return run, self.executor(run, "_LEN_SUBSCR_LIST")

    def warm_dict_update(self, cls=collections.Counter, addend=1):
        namespace = {}
        exec("def run(mapping, key, n):\n"
             "    for _ in range(n):\n"
             f"        mapping[key] += {addend}\n", namespace)
        run = namespace["run"]
        key = (b"first", b"second")
        mapping = cls({key: 1000})
        run(mapping, key, TIER2_THRESHOLD)
        ex = self.executor(run, "_DICT_PAIR_INCREMENT")
        return run, mapping, key, ex

    def warm_attribute_length(self, operation="==", folded=True, slots=True):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        ns = {"__builtins__": vars(builtins)}
        expression = "2 * self.degree - 1" if folded else "31"
        exec("class Receiver:\n"
             + ("    __slots__ = ('cells',)\n" if slots else "") +
             "    degree = 16\n"
             "    def ready(self):\n"
             f"        return len(self.cells) {operation} ({expression})\n"
             "def run(receiver, n):\n"
             "    result = None\n"
             "    for _ in range(n):\n"
             "        result = receiver.ready()\n"
             "    return result\n", ns)
        receiver = ns["Receiver"]()
        receiver.cells = [None] * 31
        run = ns["run"]
        run(receiver, TIER2_THRESHOLD)
        if folded and not slots:
            self.assertFalse(any("_CALL_PY_LIST" in get_opnames(ex)
                                 for ex in get_all_executors(run)))
            return receiver, run, None
        return receiver, run, self.executor(run, "_CALL_PY_LIST")

    def test_attribute_length_predicate(self):
        for operation, compare in (("==", operator.eq), ("!=", operator.ne),
                                   ("<", operator.lt), ("<=", operator.le),
                                   (">", operator.gt), (">=", operator.ge)):
            for slots in (False, True):
                for folded in (False, True):
                    with self.subTest(operation=operation, slots=slots, folded=folded):
                        receiver, run, ex = self.warm_attribute_length(operation, folded, slots)
                        for size in (0, 1, 30, 31, 32, 1024, 1100):
                            receiver.cells = [None] * size
                            if ex is None:
                                result = run(receiver, 8)
                            else:
                                result = self.executed(ex, "call_list_entries", run, receiver, 8)
                            self.assertEqual(result, compare(size, 31))

    def test_attribute_length_instance_shadow(self):
        receiver, run, _ = self.warm_attribute_length(slots=False)
        self.assertTrue(run(receiver, 8))
        receiver.degree = 17
        self.assertFalse(run(receiver, 8))
        del receiver.degree
        self.assertTrue(run(receiver, 8))

    def test_attribute_length_call_option_only(self):
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_INT_REGIONS": "0",
                                          "PYTHON_TIER2_BUILTIN_REGIONS": "0"}):
            receiver, run, ex = self.warm_attribute_length()
            self.assertTrue(self.executed(ex, "call_list_entries", run, receiver, 8))

    def test_attribute_length_argument_counts(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        for method in (False, True):
            for nargs in range(0 if method else 1, 5):
                with self.subTest(method=method, nargs=nargs):
                    names = [f"a{i}" for i in range(nargs)]
                    signature = ", ".join((["self"] if method else []) + names)
                    owner = "self" if method else names[-1]
                    arguments = ", ".join(["value"] * (nargs if method else nargs - 1)
                                          + ([] if method else ["receiver"]))
                    ns = {"__builtins__": vars(builtins)}
                    exec("class Receiver:\n"
                         "    __slots__ = ('cells',)\n"
                         "    pass\n"
                         f"def ready({signature}):\n"
                         f"    return len({owner}.cells) == 31\n"
                         + ("Receiver.ready = ready\n" if method else "") +
                         "def run(receiver, value, n):\n"
                         "    result = None\n"
                         "    for _ in range(n):\n"
                         f"        result = {'receiver.ready' if method else 'ready'}({arguments})\n"
                         "    return result\n", ns)
                    receiver, run = ns["Receiver"](), ns["run"]
                    receiver.cells = [None] * 31
                    value = object()
                    refs = sys.getrefcount(value), sys.getrefcount(receiver)
                    self.assertTrue(run(receiver, value, TIER2_THRESHOLD))
                    ex = self.executor(run, "_CALL_PY_LIST")
                    self.assertTrue(self.executed(ex, "call_list_entries", run,
                                                  receiver, value, 100))
                    receiver.cells.clear()
                    self.assertFalse(run(receiver, value, 8))
                    self.assertEqual((sys.getrefcount(value), sys.getrefcount(receiver)), refs)

    def test_attribute_length_class_change(self):
        receiver, run, _ = self.warm_attribute_length()
        cls = type(receiver)
        for degree in (4, 16, 1024, 2**40, -10):
            cls.degree = degree
            self.assertEqual(run(receiver, 8), len(receiver.cells) == 2 * degree - 1)
        cls.degree = 16
        self.assertTrue(run(receiver, 8))
        cls.ready = lambda self: "changed"
        self.assertEqual(run(receiver, 8), "changed")

    def test_attribute_length_callback_order(self):
        receiver, run, _ = self.warm_attribute_length()
        cls = type(receiver)
        events = []

        class Cells(list):
            def __len__(self):
                events.append(sys._getframe(1).f_code.co_name)
                cls.degree = 5
                return 7

        receiver.cells = Cells()
        cls.degree = 4
        # The comparison must use the degree after __len__ has changed it.
        self.assertFalse(run(receiver, 8))
        self.assertEqual(events, ["ready"] * 8)

        class LengthError(Exception):
            pass

        class Failing(list):
            def __len__(self):
                raise LengthError

        receiver.cells = Failing()
        try:
            run(receiver, 8)
        except LengthError as error:
            self.assertEqual(error.__traceback__.tb_next.tb_next.tb_frame.f_code.co_name,
                             "ready")
        else:
            self.fail("__len__ did not raise")

    def test_attribute_length_replaced_builtins(self):
        receiver, run, _ = self.warm_attribute_length()
        method = type(receiver).ready
        events = []

        def length(value):
            events.append(value)
            return 30

        custom = vars(builtins).copy()
        custom["len"] = length
        type(receiver).ready = types.FunctionType(method.__code__, {"__builtins__": custom})
        self.assertFalse(run(receiver, 8))
        self.assertEqual(events, [receiver.cells] * 8)

        # Builtin mutations permanently consume the interpreter's folding
        # budget, even after restoring len. Keep this check out of later tests.
        from test.support.script_helper import assert_python_ok

        assert_python_ok("-c", """
import builtins
import sys
from test.test_capi.test_opt_regions import TestRegions

case = TestRegions()
case.setUp()
receiver, run, ex = case.warm_attribute_length()
case.assertTrue(case.executed(ex, "call_list_entries", run, receiver, 8))
events = []
original_len = builtins.len

def replaced_len(value):
    if value is receiver.cells:
        events.append(sys._getframe(1).f_code.co_name)
        return 30
    return original_len(value)

try:
    builtins.len = replaced_len
    result = run(receiver, 8)
finally:
    builtins.len = original_len
case.assertFalse(result)
case.assertEqual(events, ["ready"] * 8)
case.doCleanups()
""", PYTHON_JIT="1")

    def warm_zip_list_pairs(self):
        namespace = {}
        exec("def run(iterator):\n"
             "    last = None\n"
             "    for pair in iterator:\n"
             "        last = pair\n"
             "    return last\n", namespace)
        run = namespace["run"]
        run(zip([b"left"] * TIER2_THRESHOLD, [b"right"] * TIER2_THRESHOLD))
        return run, self.executor(run, "_ITER_NEXT_ZIP_LIST_PAIR")

    def test_zip_list_pairs(self):
        run, ex = self.warm_zip_list_pairs()
        for strict in (False, True):
            first = [bytes([i]) for i in range(16)]
            second = [bytes([i + 16]) for i in range(16)]
            iterator = zip(first, second, strict=strict)
            self.assertEqual(self.executed(ex, "zip_entries", run, iterator),
                             (first[-1], second[-1]))
            self.assertEqual(list(iterator), [])

    def test_zip_list_pairs_reuse_and_hash(self):
        run, ex = self.warm_zip_list_pairs()
        first = [bytes([i]) for i in range(16)]
        second = [bytes([i + 16]) for i in range(16)]
        iterator = zip(first, second)
        cached = next(iterator)
        hash(cached)
        del cached
        result = self.executed(ex, "zip_reused_entries", run, iterator)
        self.assertEqual(result, (first[-1], second[-1]))
        self.assertEqual(hash(result), hash((first[-1], second[-1])))
        iterator = zip(first, second)
        cached = next(iterator)
        cached_hash = hash(cached)
        references = [sys.getrefcount(item) for item in first + second]
        result = self.executed(ex, "zip_entries", run, iterator)
        self.assertEqual(cached, (first[0], second[0]))
        self.assertEqual(hash(cached), cached_hash)
        del result
        self.assertEqual([sys.getrefcount(item) for item in first + second], references)

    def test_zip_list_pairs_retained_results(self):
        namespace = {}
        exec("def run(iterator):\n"
             "    result = []\n"
             "    for pair in iterator:\n"
             "        result.append(pair)\n"
             "    return result\n", namespace)
        run = namespace["run"]
        run(zip([b"left"] * TIER2_THRESHOLD, [b"right"] * TIER2_THRESHOLD))
        ex = self.executor(run, "_ITER_NEXT_ZIP_LIST_PAIR")
        first = [object() for _ in range(16)]
        second = [object() for _ in range(16)]
        before = ex.get_region_stats()["zip_reused_entries"]
        result = self.executed(ex, "zip_entries", run, zip(first, second))
        self.assertEqual(result, list(zip(first, second)))
        self.assertEqual(len({id(pair) for pair in result}), 16)
        self.assertEqual(ex.get_region_stats()["zip_reused_entries"], before)

    def test_zip_list_pairs_exhaustion(self):
        run, ex = self.warm_zip_list_pairs()
        for strict in (False, True):
            for sizes in ((5, 5), (5, 8), (8, 5)):
                with self.subTest(strict=strict, sizes=sizes):
                    left, right = map(lambda n: iter(list(range(n))), sizes)
                    iterator = zip(left, right, strict=strict)
                    before = ex.get_region_stats()["zip_fallbacks"]
                    if strict and sizes[0] != sizes[1]:
                        with self.assertRaises(ValueError):
                            run(iterator)
                    else:
                        self.assertEqual(run(iterator), (4, 4))
                    self.assertGreater(ex.get_region_stats()["zip_fallbacks"], before)
                    self.assertEqual(list(left), list(range(6, sizes[0])))
                    self.assertEqual(list(right), list(range(6 if strict else 5, sizes[1])))

    def test_zip_list_pairs_aliased_iterators(self):
        run, ex = self.warm_zip_list_pairs()
        for strict in (False, True):
            shared = iter(list(range(16)))
            before = ex.get_region_stats()["zip_entries"]
            self.assertEqual(self.executed(ex, "zip_fallbacks", run,
                                           zip(shared, shared, strict=strict)), (14, 15))
            self.assertEqual(ex.get_region_stats()["zip_entries"], before)
        shared = [bytes([i]) for i in range(16)]
        self.assertEqual(self.executed(ex, "zip_entries", run, zip(shared, shared)),
                         (shared[-1], shared[-1]))

    def test_zip_list_pairs_other_arities(self):
        run, ex = self.warm_zip_list_pairs()
        self.assertIsNone(run(zip()))
        for count in (1, 3, 4):
            before = ex.get_region_stats()["zip_entries"]
            inputs = [list(range(8)) for _ in range(count)]
            self.assertEqual(self.executed(ex, "zip_fallbacks", run, zip(*inputs)),
                             (7,) * count)
            self.assertEqual(ex.get_region_stats()["zip_entries"], before)

    def test_zip_list_pairs_monitoring(self):
        run, ex = self.warm_zip_list_pairs()
        code = run.__code__
        monitoring = sys.monitoring
        tool = 4
        monitoring.use_tool_id(tool, "zip list pairs")
        events = []
        before = ex.get_region_stats()["zip_entries"]
        try:
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION,
                                         lambda code, offset: events.append(offset))
            monitoring.set_local_events(tool, code, monitoring.events.INSTRUCTION)
            self.assertEqual(run(zip(list(range(8)), list(range(8)))), (7, 7))
            self.assertTrue(events)
            self.assertEqual(ex.get_region_stats()["zip_entries"], before)
        finally:
            monitoring.set_local_events(tool, code, 0)
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION, None)
            monitoring.free_tool_id(tool)

    def test_zip_list_pairs_generic_iterators(self):
        run, ex = self.warm_zip_list_pairs()
        events = []

        class Iterator:
            def __init__(self, name):
                self.name = name
                self.values = iter(range(8))

            def __iter__(self):
                return self

            def __next__(self):
                events.append((self.name, sys._getframe(1).f_code))
                return next(self.values)

        self.assertEqual(self.executed(ex, "zip_fallbacks", run,
                                       zip(Iterator("left"), Iterator("right"))), (7, 7))
        self.assertEqual(events, [(name, run.__code__) for name in
                                 ["left", "right"] * 8 + ["left"]])

    def test_zip_list_pairs_callback_error(self):
        import dis

        run, ex = self.warm_zip_list_pairs()
        events = []

        class Iterator:
            def __iter__(self):
                return self

            def __next__(self):
                events.append(sys._getframe(1).f_code)
                if len(events) == 4:
                    raise MemoryError("zip callback")
                return len(events) - 1

        left = iter(list(range(8)))
        before = ex.get_region_stats()["zip_fallbacks"]
        try:
            run(zip(left, Iterator()))
        except MemoryError as error:
            traceback = error.__traceback__.tb_next
            self.assertIs(traceback.tb_frame.f_code, run.__code__)
            position = next(i.offset for i in dis.get_instructions(run) if i.opname == "FOR_ITER")
            self.assertEqual(traceback.tb_lasti, position)
        else:
            self.fail("MemoryError was lost")
        self.assertGreater(ex.get_region_stats()["zip_fallbacks"], before)
        self.assertEqual(events, [run.__code__] * 4)
        self.assertEqual(next(left), 4)

    def test_zip_list_pairs_old_element_finalizer(self):
        namespace = {}
        exec("def run(iterator, source):\n"
             "    result = []\n"
             "    for pair in iterator:\n"
             "        result.append((type(pair[0]).__name__, pair[1]))\n"
             "        source[0] = None\n"
             "        pair = None\n"
             "    return result\n", namespace)
        run = namespace["run"]
        source = [b"left"] * TIER2_THRESHOLD
        run(zip(source, [b"right"] * TIER2_THRESHOLD), source)
        ex = self.executor(run, "_ITER_NEXT_ZIP_LIST_PAIR")
        events = []
        right_source = [bytes([i]) for i in range(8)]

        class Payload:
            def __del__(self):
                events.append((sys._getframe(1).f_code, next(left)))
                right_source.clear()

        source = [Payload(), b"one", b"two", b"three"]
        left = iter(source)
        result = self.executed(ex, "zip_fallbacks", run,
                               zip(left, iter(right_source)), source)
        self.assertEqual(result, [("Payload", bytes([0]))])
        self.assertEqual(events, [(run.__code__, b"two")])
        self.assertEqual(next(left), b"three")

    @unittest.skipUnless(support.Py_DEBUG, "uses debug allocation injection")
    def test_zip_list_pairs_allocation_error(self):
        import dis

        run, ex = self.warm_zip_list_pairs()
        first = [bytes([i]) for i in range(16)]
        second = [bytes([i + 16]) for i in range(16)]
        iterator = zip(first, second)
        cached = next(iterator)  # Pin zip's cached tuple: subsequent results allocate.
        position = next(i.offset for i in dis.get_instructions(run) if i.opname == "FOR_ITER")
        before = ex.get_region_stats()["allocation_errors"]
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "zip"}):
            try:
                run(iterator)
            except MemoryError as error:
                traceback = error.__traceback__
                while traceback.tb_next is not None:
                    traceback = traceback.tb_next
                self.assertIs(traceback.tb_frame.f_code, run.__code__)
                self.assertEqual(traceback.tb_lasti, position)
                self.assertEqual(traceback.tb_frame.f_locals["last"], (first[1], second[1]))
            else:
                self.fail("MemoryError was lost")
        self.assertGreater(ex.get_region_stats()["allocation_errors"], before)
        self.assertEqual(next(iterator), (first[2], second[2]))
        self.assertEqual(cached, (first[0], second[0]))

    def warm_float_attributes(self, slots=False, expression=None):
        if expression is None:
            expression = "self.x * other.x + self.y * other.y + self.z * other.z"
        namespace = {}
        exec("class Vector:\n"
             + ("    __slots__ = ('x', 'y', 'z')\n" if slots else "") +
             "    def dot(self, other):\n"
             f"        return {expression}\n"
             "def run(left, right, n):\n"
             "    for _ in range(n):\n"
             "        result = left.dot(right)\n"
             "    return result\n", namespace)
        cls = namespace["Vector"]
        left, right = cls(), cls()
        left.x, left.y, left.z = map(float, (2, 3, 4))
        right.x, right.y, right.z = map(float, (5, 6, 7))
        run = namespace["run"]
        run(left, right, TIER2_THRESHOLD)
        candidates = (run, cls.dot)
        for function in candidates:
            if any("_FLOAT_ATTRIBUTE_SUM_PRODUCTS" in get_opnames(ex)
                   for ex in get_all_executors(function)):
                return run, left, right, self.executor(function, "_FLOAT_ATTRIBUTE_SUM_PRODUCTS")
        self.fail([get_opnames(ex) for f in candidates for ex in get_all_executors(f)])

    def test_float_attribute_products(self):
        for slots in (False, True):
            with self.subTest(slots=slots):
                run, left, right, ex = self.warm_float_attributes(slots)
                self.assertEqual(self.executed(ex, "float_attribute_entries", run,
                                               left, right, 8), 56.0)
                self.assertEqual(self.executed(ex, "float_attribute_entries", run,
                                               left, left, 8), 29.0)

    def test_float_attribute_offsets_and_aliases(self):
        for slots in (False, True):
            for expression, expected in (
                ("self.z * other.y + self.x * other.z + self.y * other.x", 53.0),
                ("self.x * self.y + self.z * self.x + self.y * self.z", 26.0),
            ):
                with self.subTest(slots=slots, expression=expression):
                    run, left, right, ex = self.warm_float_attributes(slots, expression)
                    self.assertEqual(self.executed(ex, "float_attribute_entries", run,
                                                   left, right, 8), expected)

    def test_float_attribute_rounding(self):
        cases = [
            (-1.0, 1.0, 1.0 + 2**-27, 1.0 - 2**-27, 0.0, 1.0),
            (1e308, 2.0, -1e308, 2.0, 1.0, 1.0),
            (2**-1022, 2**-53, 2**-1022, 2**-53, -0.0, 1.0),
            (math.inf, 0.0, 1.0, 1.0, 1.0, 1.0),
        ]
        for a in (0.0, -0.0):
            for b in (0.0, -0.0):
                for c in (0.0, -0.0):
                    cases.append((a, 1.0, b, 1.0, c, 1.0))
        rng = random.Random(7721)
        for _ in range(128):
            cases.append(tuple(struct.unpack("d", rng.randbytes(8))[0] for _ in range(6)))
        for slots in (False, True):
            run, left, right, ex = self.warm_float_attributes(slots)
            for values in cases:
                left.x, right.x, left.y, right.y, left.z, right.z = values
                a, b, c, d, e, f = values
                expected = a * b + c * d + e * f
                actual = self.executed(ex, "float_attribute_entries", run, left, right, 8)
                if math.isnan(expected):
                    self.assertTrue(math.isnan(actual))
                else:
                    self.assertEqual(struct.pack("d", actual), struct.pack("d", expected))

    def test_float_attribute_references(self):
        for slots in (False, True):
            run, left, right, ex = self.warm_float_attributes(slots)
            values = (left.x, left.y, left.z, right.x, right.y, right.z, left, right)
            references = [sys.getrefcount(value) for value in values]
            first = self.executed(ex, "float_attribute_entries", run, left, right, 8)
            second = self.executed(ex, "float_attribute_entries", run, left, right, 1000)
            self.assertIsNot(first, second)
            self.assertEqual(first, second)
            self.assertEqual([sys.getrefcount(value) for value in values], references)
            self.assertEqual(values[:6], (2.0, 3.0, 4.0, 5.0, 6.0, 7.0))

    def test_float_attribute_numeric_callback(self):
        for slots in (False, True):
            run, left, right, ex = self.warm_float_attributes(slots)
            events = []

            class Number(float):
                def __rmul__(self, value):
                    frame = sys._getframe(1)
                    events.append((frame.f_code, frame.f_locals["self"], value))
                    left.z = 101.0
                    return value * float(self)

            right.y = Number(6.0)
            self.assertEqual(self.executed(ex, "float_guard_exits", run,
                                           left, right, 8), 735.0)
            self.assertEqual(events, [(type(left).dot.__code__, left, 3.0)] * 8)

    def test_float_attribute_layout_changes(self):
        for slots in (False, True):
            for change in ("missing", "class", "accessor", "dict"):
                if slots and change == "dict":
                    continue
                with self.subTest(slots=slots, change=change):
                    run, left, right, ex = self.warm_float_attributes(slots)
                    if change == "missing":
                        namespace = {}
                        exec("def run(left, others):\n"
                             "    for other in others:\n"
                             "        result = left.dot(other)\n"
                             "    return result\n", namespace)
                        run = namespace["run"]
                        run(left, [right] * TIER2_THRESHOLD)
                        ex = self.executor(run, "_FLOAT_ATTRIBUTE_SUM_PRODUCTS")
                        missing = type(right)()
                        missing.x, missing.y = 5.0, 6.0
                        before = ex.get_region_stats()["float_guard_exits"]
                        with self.assertRaises(AttributeError):
                            # The first iteration runs before the loop executor.
                            run(left, [right, missing])
                        self.assertGreater(ex.get_region_stats()["float_guard_exits"], before)
                    elif change == "dict":
                        # Mutate the argument, whose managed-values guard is
                        # inside the new region, beyond the method lookup.
                        right.__dict__ = dict(x=5.0, y=6.0, z=10.0)
                        self.assertEqual(self.executed(ex, "float_guard_exits", run,
                                                       left, right, 8), 68.0)
                        left.__dict__ = dict(x=2.0, y=3.0, z=10.0)
                        self.assertEqual(run(left, right, 8), 128.0)
                    elif change == "class":
                        class Other(type(left)):
                            pass

                        other = Other()
                        other.x, other.y, other.z = 5.0, 6.0, 10.0
                        self.assertEqual(self.executed(ex, "float_guard_exits", run,
                                                       left, other, 8), 68.0)
                    else:
                        events = []

                        def getattribute(self, name):
                            if name in ("x", "y", "z"):
                                events.append((name, sys._getframe(1).f_code))
                            return object.__getattribute__(self, name)

                        type(left).__getattribute__ = getattribute
                        self.assertEqual(run(left, right, 8), 56.0)
                        code = type(left).dot.__code__
                        self.assertEqual(events, [(name, code) for name in
                                                 ("x", "x", "y", "y", "z", "z")] * 8)

    def test_float_attributes_without_call_regions(self):
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_CALL_REGIONS": "0",
                                           "PYTHON_TIER2_INT_REGIONS": "0",
                                           "PYTHON_TIER2_BUILTIN_REGIONS": "0"}):
            for slots in (False, True):
                run, left, right, ex = self.warm_float_attributes(slots)
                self.assertEqual(self.executed(ex, "float_attribute_entries", run,
                                               left, right, 8), 56.0)

    def test_float_attribute_owner_local_indices(self):
        for slots in (False, True):
            _, left, right, _ = self.warm_float_attributes(slots)
            for count in (6, 7):
                namespace = {}
                args = ", ".join(f"p{i}" for i in range(count))
                exec(f"def run({args}, left, right, n):\n"
                     "    for _ in range(n):\n"
                     "        result = left.x * right.x + left.y * right.y + left.z * right.z\n"
                     "    return result\n", namespace)
                run = namespace["run"]
                values = (None,) * count + (left, right)
                run(*values, TIER2_THRESHOLD)
                if count == 6:
                    ex = self.executor(run, "_FLOAT_ATTRIBUTE_SUM_PRODUCTS")
                    self.assertEqual(self.executed(ex, "float_attribute_entries", run,
                                                   *values, 8), 56.0)
                else:
                    self.assertFalse(any("_FLOAT_ATTRIBUTE_SUM_PRODUCTS" in get_opnames(ex)
                                         for ex in get_all_executors(run)))
                    self.assertEqual(run(*values, 8), 56.0)

    def test_float_attribute_intervening_effects(self):
        for body in (
            "return self.x * other.x + self.y * convert(other.y) + self.z * other.z",
            "return self.x * other.x + (product := self.y * other.y) + self.z * other.z",
        ):
            _, left, right, _ = self.warm_float_attributes()
            events = []

            def convert(value):
                events.append(sys._getframe(1).f_code)
                left.z = 10.0
                return value

            namespace = {"convert": convert}
            exec("def dot(self, other):\n" + f"    {body}\n"
                 "def run(left, right, n):\n"
                 "    for _ in range(n):\n"
                 "        result = left.dot(right)\n"
                 "    return result\n", namespace)
            type(left).dot = namespace["dot"]
            run = namespace["run"]
            run(left, right, TIER2_THRESHOLD)
            events.clear()
            self.assertFalse(any("_FLOAT_ATTRIBUTE_SUM_PRODUCTS" in get_opnames(ex)
                                 for f in (run, type(left).dot) for ex in get_all_executors(f)))
            self.assertEqual(run(left, right, 8), 98.0 if "convert" in body else 56.0)
            self.assertEqual(events, [type(left).dot.__code__] * 8 if "convert" in body else [])

    @unittest.skipUnless(support.Py_DEBUG, "uses debug allocation injection")
    def test_float_attribute_allocation_error(self):
        import dis

        for slots in (False, True):
            run, left, right, ex = self.warm_float_attributes(slots)
            code = type(left).dot.__code__
            add = max(instruction.offset for instruction in dis.get_instructions(code)
                      if instruction.opname == "BINARY_OP" and instruction.argrepr == "+")
            before = ex.get_region_stats()["allocation_errors"]
            with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "float_attributes"}):
                try:
                    run(left, right, 8)
                except MemoryError as exc:
                    traceback = exc.__traceback__
                    while traceback.tb_next is not None:
                        traceback = traceback.tb_next
                    self.assertIs(traceback.tb_frame.f_code, code)
                    self.assertEqual(traceback.tb_lasti, add)
                    self.assertIs(traceback.tb_frame.f_locals["self"], left)
                    self.assertIs(traceback.tb_frame.f_locals["other"], right)
                else:
                    self.fail("MemoryError was lost")
            self.assertGreater(ex.get_region_stats()["allocation_errors"], before)
            self.assertEqual(run(left, right, 8), 56.0)

    def test_float_attribute_monitoring(self):
        run, left, right, ex = self.warm_float_attributes()
        code = type(left).dot.__code__
        monitoring = sys.monitoring
        tool = 4
        monitoring.use_tool_id(tool, "float attributes")
        events = []
        before = ex.get_region_stats()["float_attribute_entries"]

        def on_instruction(code, offset):
            events.append(offset)
            left.z = 10.0

        try:
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION, on_instruction)
            monitoring.set_local_events(tool, code, monitoring.events.INSTRUCTION)
            self.assertEqual(run(left, right, 8), 98.0)
            self.assertTrue(events)
            self.assertEqual(ex.get_region_stats()["float_attribute_entries"], before)
        finally:
            monitoring.set_local_events(tool, code, 0)
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION, None)
            monitoring.free_tool_id(tool)

    @unittest.skipUnless(support.Py_DEBUG, "uses debug allocation injection")
    def test_float_attribute_allocation_handler(self):
        import dis

        _, left, right, _ = self.warm_float_attributes()
        namespace = {}
        exec("def dot(self, other):\n"
             "    marker = self\n"
             "    try:\n"
             "        return 7.0 + (self.x * other.x + self.y * other.y + self.z * other.z)\n"
             "    except MemoryError as error:\n"
             "        return marker, other, error\n"
             "def run(left, right, n):\n"
             "    for _ in range(n):\n"
             "        result = left.dot(right)\n"
             "    return result\n", namespace)
        type(left).dot = namespace["dot"]
        run = namespace["run"]
        run(left, right, TIER2_THRESHOLD)
        ex = self.executor(run, "_FLOAT_ATTRIBUTE_SUM_PRODUCTS")
        code = type(left).dot.__code__
        adds = [instruction.offset for instruction in dis.get_instructions(code)
                if instruction.opname == "BINARY_OP" and instruction.argrepr == "+"]
        self.assertEqual(len(adds), 3)
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "float_attributes"}):
            marker, other, error = self.executed(ex, "allocation_errors", run, left, right, 8)
        self.assertIs(marker, left)
        self.assertIs(other, right)
        self.assertIsInstance(error, MemoryError)
        self.assertIs(error.__traceback__.tb_frame.f_code, code)
        self.assertEqual(error.__traceback__.tb_lasti, adds[1])
        self.assertEqual(run(left, right, 8), 63.0)

    def warm_float_owned(self, symbol="+", fields=(True, True)):
        class Holder:
            pass

        holder = Holder()
        holder.left, holder.right = float("3.0"), float("2.0")
        left = "holder.left" if fields[0] else "b"
        right = "holder.right" if fields[1] else "c"
        namespace = {}
        exec("def run(a, b, c, holder, n):\n"
             "    for _ in range(n):\n"
             f"        result = a * 1.0 {symbol} {left} * {right}\n"
             "    return result\n", namespace)
        run = namespace["run"]
        run(7.0, 3.0, 2.0, holder, TIER2_THRESHOLD)
        operation = "ADD" if symbol == "+" else "SUBTRACT"
        ex = self.executor(run, f"_BINARY_OP_MULTIPLY_{operation}_FLOAT_OWNED")
        return run, holder, ex

    def test_dict_update_existing_values(self):
        for addend in (0, 1, 7, 255):
            with self.subTest(addend=addend):
                run, mapping, key, ex = self.warm_dict_update(addend=addend)
                for value in (-1000, -1, 0, 255, 1000, 2**30 - 10000):
                    mapping[key] = value
                    self.executed(ex, "dict_update_entries", run, mapping, key, 8)
                    self.assertEqual(mapping[key], value + addend * 8)
                # Equal freshly created keys need not be identical to the stored key.
                same_key = tuple(bytes(bytearray(item)) for item in key)
                before = mapping[key]
                self.executed(ex, "dict_update_entries", run, mapping, same_key, 8)
                self.assertEqual(mapping[key], before + addend * 8)

    def test_dict_update_colliding_callback(self):
        run, mapping, key, ex = self.warm_dict_update()
        events = []

        class Collision:
            def __hash__(self):
                return hash(key)

            def __eq__(self, other):
                events.append(other)
                return False

        mapping.clear()
        mapping[Collision()] = 2000
        mapping[key] = 1000
        events.clear()
        # The probe sequence can visit a colliding entry more than once.
        # Compare against ordinary read/add/write under this hash seed.
        for _ in range(8):
            mapping[key] += 1
        self.assertEqual(mapping[key], 1008)
        expected = events.copy()
        mapping[key] = 1000
        events.clear()
        before = ex.get_region_stats()["dict_update_guard_exits"]
        run(mapping, key, 8)
        self.assertEqual(mapping[key], 1008)
        # The final assertion's lookup also compares the colliding key.
        self.assertEqual(events, expected)
        self.assertGreater(ex.get_region_stats()["dict_update_guard_exits"], before)

    def test_dict_update_missing_and_noncompact(self):
        events = []

        class Counter(collections.Counter):
            def __missing__(self, key):
                events.append(key)
                return 100

        run, mapping, key, ex = self.warm_dict_update(Counter)
        del mapping[key]
        run(mapping, key, 8)
        self.assertEqual(mapping[key], 108)
        self.assertEqual(events, [key])
        for value in (2**100, 1.5):
            mapping[key] = value
            before = ex.get_region_stats()["dict_update_guard_exits"]
            run(mapping, key, 8)
            self.assertEqual(mapping[key], value + 8)
            self.assertGreater(ex.get_region_stats()["dict_update_guard_exits"], before)

    def test_dict_update_watcher(self):
        import _testcapi

        run, mapping, key, ex = self.warm_dict_update()
        mapping[key] = 1000
        watcher = _testcapi.add_dict_watcher(0)
        try:
            _testcapi.watch_dict(watcher, mapping)
            before = ex.get_region_stats()["dict_update_guard_exits"]
            run(mapping, key, 8)
            events = _testcapi.get_dict_watcher_events()
            self.assertEqual(events, [f"mod:{key}:{value}" for value in range(1001, 1009)])
            self.assertGreater(ex.get_region_stats()["dict_update_guard_exits"], before)
        finally:
            _testcapi.unwatch_dict(watcher, mapping)
            _testcapi.clear_dict_watcher(watcher)

    def test_dict_update_second_iteration_missing(self):
        events = []

        class Counter(collections.Counter):
            def __missing__(self, key):
                events.append(key)
                return 100

        def run(mapping, keys):
            for key in keys:
                mapping[key] += 1

        key = (b"first", b"second")
        mapping = Counter({key: 1000})
        run(mapping, [key] * TIER2_THRESHOLD)
        ex = self.executor(run, "_DICT_PAIR_INCREMENT")
        missing = (b"new", b"pair")
        before = ex.get_region_stats()["dict_update_guard_exits"]
        run(mapping, [key, missing])
        self.assertEqual(mapping[missing], 101)
        self.assertEqual(events, [missing])
        self.assertGreater(ex.get_region_stats()["dict_update_guard_exits"], before)

    def test_dict_update_method_change(self):
        class Counter(collections.Counter):
            pass

        run, mapping, key, ex = self.warm_dict_update(Counter)
        self.executed(ex, "dict_update_entries", run, mapping, key, 8)
        events = []

        def setter(self, key, value):
            events.append(value)
            dict.__setitem__(self, key, value)

        Counter.__setitem__ = setter
        before = mapping[key]
        run(mapping, key, 8)
        self.assertEqual(events, list(range(before + 1, before + 9)))
        self.assertEqual(mapping[key], before + 8)

    def test_dict_update_missing_side_trace(self):
        events = []

        class Counter(collections.Counter):
            def __missing__(self, key):
                events.append(key)
                return 100

        def run(mapping, keys):
            for key in keys:
                mapping[key] += 1

        key = (b"first", b"second")
        mapping = Counter({key: 1000})
        run(mapping, [key] * TIER2_THRESHOLD)
        root = self.executor(run, "_DICT_PAIR_INCREMENT")
        keys = [(b"new", str(i).encode()) for i in range(TIER2_THRESHOLD)]
        for _ in range(4):
            mapping.clear()
            mapping[key] = 1000
            run(mapping, [key, *keys])
        self.assertEqual(events, keys * 4)
        self.assertEqual(mapping[key], 1001)
        self.assertTrue(all(mapping[item] == 101 for item in keys))
        pending = [root]
        seen = set()
        direct_stores = 0
        while pending:
            ex = pending.pop()
            if id(ex) in seen:
                continue
            seen.add(id(ex))
            direct_stores += ex.get_region_stats()["dict_store_entries"]
            pending.extend(obj for obj in gc.get_referents(ex)
                           if type(obj) is type(root))
        self.assertGreater(direct_stores, 0)

    def test_dict_update_reference_ownership(self):
        run, mapping, key, ex = self.warm_dict_update()
        reference = weakref.ref(mapping)
        references = sys.getrefcount(key)
        self.executed(ex, "dict_update_entries", run, mapping, key, 1000)
        self.assertEqual(sys.getrefcount(key), references)
        del mapping
        self.assertIsNone(reference())

    @unittest.skipUnless(support.Py_DEBUG, "uses debug allocation injection")
    def test_dict_update_allocation_error_location(self):
        import dis

        run, mapping, key, ex = self.warm_dict_update()
        mapping[key] = 1000
        add = next(instruction.offset for instruction in dis.get_instructions(run)
                   if instruction.opname == "BINARY_OP" and instruction.argrepr == "+=")
        before = ex.get_region_stats()["allocation_errors"]
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "dict_update"}):
            try:
                run(mapping, key, 8)
            except MemoryError as exc:
                traceback = exc.__traceback__
                while traceback.tb_next is not None:
                    traceback = traceback.tb_next
                self.assertIs(traceback.tb_frame.f_code, run.__code__)
                self.assertEqual(traceback.tb_lasti, add)
            else:
                self.fail("MemoryError was lost")
        self.assertEqual(mapping[key], 1001)
        self.assertGreater(ex.get_region_stats()["allocation_errors"], before)

    def test_len_subscript_comparisons(self):
        values = [[], [1], (1, 2), "abc", b"x", {1: 2}]
        for constant in (False, True):
            for comparison, compare in (("==", operator.eq), ("!=", operator.ne),
                                         ("<", operator.lt), ("<=", operator.le),
                                         (">", operator.gt), (">=", operator.ge)):
                with self.subTest(constant=constant, comparison=comparison):
                    run, ex = self.warm_len_subscript(comparison, constant)
                    for index in range(-len(values), len(values)):
                        expected = compare(len(values[index]), 1)
                        self.assertIs(self.executed(ex, "len_subscript_entries", run,
                                                    values, index, 1, 8), expected)

    def test_len_subscript_user_length(self):
        run, ex = self.warm_len_subscript()
        events = []

        class Sized:
            def __len__(self):
                events.append("len")
                return 1

        self.assertTrue(self.executed(ex, "len_guard_exits", run, [Sized()], 0, 1, 8))
        self.assertEqual(events, ["len"] * 8)

    def test_len_subscript_unique_list_finalizer_order(self):
        def run(factory, n):
            result = None
            for _ in range(n):
                result = len(factory()[0]) == 1
            return result

        held = [[]]
        pool = [held] * TIER2_THRESHOLD
        pop = pool.pop
        run(pop, TIER2_THRESHOLD)
        ex = self.executor(run, "_LEN_SUBSCR_LIST")
        events = []

        class Trigger:
            def __init__(self, selected):
                self.selected = selected

            def __del__(self):
                self.selected.append(1)
                events.append("deleted")

        selected = [[] for _ in range(8)]
        pool.extend([value, Trigger(value)] for value in selected)

        # The other list element is destroyed after indexing, before len().
        # Measuring length before that finalizer would incorrectly return False.
        before = ex.get_region_stats()["len_guard_exits"]
        self.assertTrue(run(pop, 8))
        self.assertEqual(events, ["deleted"] * 8)
        self.assertGreater(ex.get_region_stats()["len_guard_exits"], before)

    @requires_call_regions
    def test_list_call_item_and_length(self):
        for slots in (False, True):
            for expression in ("self.cells[index]", "len(self.cells[index]) == 1",
                               "len(self.cells[index]) != 2", "len(self.cells[index]) < 2"):
                with self.subTest(slots=slots, expression=expression):
                    _, receiver, run, ex = self.warm_list_call(expression, slots)
                    for index in (0, 1, 2, -1, -2, -3):
                        expected = receiver.get(index)
                        self.assertIs(self.executed(ex, "call_list_entries", run,
                                                    receiver, index, 8), expected)

    @requires_call_regions
    def test_list_call_index_and_list_callbacks(self):
        _, receiver, run, ex = self.warm_list_call()
        events = []

        class Index:
            def __index__(self):
                events.append("index")
                return 1

        self.assertIs(self.executed(ex, "call_guard_exits", run,
                                   receiver, Index(), 8), receiver.cells[1])
        self.assertEqual(events, ["index"] * 8)
        events.clear()

        class Values(list):
            def __getitem__(self, index):
                events.append(index)
                return "override"

        receiver.cells = Values(receiver.cells)
        self.assertEqual(run(receiver, 0, 8), "override")
        self.assertEqual(events, [0] * 8)

    @requires_call_regions
    def test_list_call_length_callback(self):
        _, receiver, run, ex = self.warm_list_call("len(self.cells[index]) == 1")
        events = []

        class Sized:
            def __len__(self):
                events.append("len")
                return 1

        receiver.cells[0] = Sized()
        self.assertTrue(self.executed(ex, "call_guard_exits", run, receiver, 0, 8))
        self.assertEqual(events, ["len"] * 8)

    @requires_call_regions
    def test_list_call_len_binding(self):
        namespace, receiver, run, ex = self.warm_list_call("len(self.cells[index]) == 1")
        self.executed(ex, "call_list_entries", run, receiver, 0, 8)
        events = []

        def replacement(value):
            events.append(value)
            return 42

        namespace["len"] = replacement
        self.assertFalse(run(receiver, 0, 8))
        self.assertEqual(events, [receiver.cells[0]] * 8)

    @requires_call_regions
    def test_list_call_second_iteration_exception(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Receiver:
            def get(self, index):
                return len(self.cells[index]) == 1

        def run(receiver, indices, n):
            result = None
            for i in range(n):
                result = receiver.get(indices[i != 0])
            return result

        receiver = Receiver()
        receiver.cells = [[object()]]
        run(receiver, (0, 0), TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_LIST")
        before = ex.get_region_stats()["call_guard_exits"]
        try:
            run(receiver, (0, 1), 8)
        except IndexError as exc:
            traceback = exc.__traceback__
            while traceback.tb_next is not None:
                traceback = traceback.tb_next
            self.assertIs(traceback.tb_frame.f_code, Receiver.get.__code__)
            self.assertEqual(traceback.tb_frame.f_locals["index"], 1)
        else:
            self.fail("IndexError was lost")
        self.assertGreater(ex.get_region_stats()["call_guard_exits"], before)

    @requires_call_regions
    def test_list_call_monitoring(self):
        _, receiver, run, ex = self.warm_list_call("len(self.cells[index]) == 1")
        self.executed(ex, "call_list_entries", run, receiver, 0, 8)
        monitoring = sys.monitoring
        tool = 4
        code = type(receiver).get.__code__
        events = []
        monitoring.use_tool_id(tool, "list call")
        try:
            monitoring.register_callback(tool, monitoring.events.PY_START,
                                         lambda *args: events.append("start"))
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda *args: events.append("return"))
            monitoring.set_local_events(tool, code,
                                        monitoring.events.PY_START | monitoring.events.PY_RETURN)
            self.assertTrue(run(receiver, 0, 8))
            self.assertEqual(events, ["start", "return"] * 8)
        finally:
            monitoring.set_local_events(tool, code, 0)
            monitoring.register_callback(tool, monitoring.events.PY_START, None)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_list_call_same_version_custom_builtins(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        def make_get():
            def get(receiver, index):
                return len(receiver.cells[index]) == 1
            return get

        def run(functions, receiver, index):
            result = None
            for function in functions:
                result = function(receiver, index)
            return result

        class Receiver:
            pass

        receiver = Receiver()
        receiver.cells = [[object()]]
        get = make_get()
        run([get] * TIER2_THRESHOLD, receiver, 0)
        ex = self.executor(run, "_CALL_PY_LIST")
        self.assertTrue(self.executed(ex, "call_list_entries", run,
                                      [get] * 8, receiver, 0))
        custom_builtins = vars(builtins).copy()
        custom_builtins["len"] = lambda value: 42
        custom_get = types.FunctionType(make_get.__code__, {"__builtins__": custom_builtins})()
        self.assertFalse(run([get, custom_get], receiver, 0))

    @requires_call_regions
    def test_list_call_return_lifetime(self):
        _, receiver, run, ex = self.warm_list_call()
        events = []

        class Value:
            def __del__(self):
                events.append("deleted")

        receiver.cells = [Value()]
        ref = weakref.ref(receiver.cells[0])
        result = self.executed(ex, "call_list_entries", run, receiver, 0, 8)
        receiver.cells.clear()
        self.assertIs(result, ref())
        self.assertFalse(events)
        del result
        self.assertIsNone(ref())
        self.assertEqual(events, ["deleted"])

    @requires_call_regions
    def test_class_attributes_identity_and_order(self):
        for nargs in range(1, 5):
            with self.subTest(nargs=nargs):
                order = list(reversed(range(nargs)))
                cls, run, args, ex = self.warm_class_attributes(nargs, order)
                retained = [self.executed(ex, "class_entries", run, cls, *args, 8)
                            for _ in range(4)]
                self.assertEqual(len({id(obj) for obj in retained}), 4)
                for obj in retained:
                    self.assertIs(type(obj), cls)
                    self.assertEqual(list(vars(obj)), [f"a{i}" for i in order])
                    for i, value in enumerate(args):
                        self.assertIs(getattr(obj, f"a{i}"), value)

    @requires_call_regions
    def test_class_attributes_initializer_code_change(self):
        cls, run, args, ex = self.warm_class_attributes()
        self.executed(ex, "class_entries", run, cls, *args, 8)

        def replacement(self, a0, a1, a2):
            self.changed = (a2, a1, a0)

        cls.__init__.__code__ = replacement.__code__
        obj = run(cls, *args, 8)
        self.assertEqual(vars(obj), {"changed": tuple(reversed(args))})

    @requires_call_regions
    @unittest.skipUnless(support.Py_DEBUG, "uses debug allocation injection")
    def test_class_attributes_allocation_error(self):
        cls, run, args, ex = self.warm_class_attributes()
        before = ex.get_region_stats()["allocation_errors"]
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "class_call"}):
            with self.assertRaises(MemoryError) as caught:
                run(cls, *args, 8)
        self.assertGreater(ex.get_region_stats()["allocation_errors"], before)
        self.assertIsNone(caught.exception.__context__)

    @requires_call_regions
    def test_class_attributes_gc_materialization(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Record:
            def __init__(self, value):
                self.value = value

        def run(cls, value, n):
            result = []
            for _ in range(n):
                result.append(cls(value))
            return result

        value = object()
        run(Record, value, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_CLASS_ATTRIBUTES")
        seen = []

        def callback(phase, info):
            if phase == "start":
                frame = sys._getframe(1)
                if frame.f_code is Record.__init__.__code__:
                    local = frame.f_locals
                    seen.append((local["value"] is value,
                                 list(vars(local["self"]))))

        old_threshold = gc.get_threshold()
        was_enabled = gc.isenabled()
        try:
            gc.collect()
            gc.enable()
            gc.callbacks.append(callback)
            gc.set_threshold(32, 10, 10)
            before = ex.get_region_stats()["class_materializations"]
            result = run(Record, value, 1024)
            after = ex.get_region_stats()["class_materializations"]
        finally:
            gc.callbacks.remove(callback)
            gc.set_threshold(*old_threshold)
            if not was_enabled:
                gc.disable()
        self.assertGreater(after, before)
        self.assertTrue(seen)
        self.assertTrue(all(correct and not attrs for correct, attrs in seen), seen)
        self.assertTrue(all(obj.value is value for obj in result))

    @requires_call_regions
    def test_class_attributes_setattr_override(self):
        cls, run, args, ex = self.warm_class_attributes()
        self.executed(ex, "class_entries", run, cls, *args, 8)
        seen = []

        def setter(self, name, value):
            seen.append((name, value))
            object.__setattr__(self, name, value)

        cls.__setattr__ = setter
        result = run(cls, *args, 8)
        self.assertEqual(seen, list(zip(("a0", "a1", "a2"), args)) * 8)
        self.assertEqual(vars(result), dict(zip(("a0", "a1", "a2"), args)))

    @requires_call_regions
    def test_class_attributes_nested_returns(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Vector:
            def __init__(self, x, y, z):
                self.x = x
                self.y = y
                self.z = z

            def scale(self, factor):
                return Vector(factor * self.x, factor * self.y, factor * self.z)

            def normalize(self):
                return self.scale(0.5)

        def run(vector, n):
            result = None
            for _ in range(n):
                result = vector.normalize()
            return result

        vector = Vector(1.0, 2.0, 3.0)
        run(vector, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_CLASS_ATTRIBUTES")
        result = self.executed(ex, "class_entries", run, vector, 8)
        self.assertEqual((result.x, result.y, result.z), (0.5, 1.0, 1.5))

    @requires_call_regions
    def test_class_attributes_monitoring(self):
        cls, run, args, ex = self.warm_class_attributes()
        self.executed(ex, "class_entries", run, cls, *args, 8)
        monitoring = sys.monitoring
        tool = 4
        monitoring.use_tool_id(tool, "class attributes")
        events = []
        try:
            monitoring.register_callback(tool, monitoring.events.PY_START,
                                         lambda *args: events.append("start"))
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda *args: events.append("return"))
            monitoring.set_local_events(tool, cls.__init__.__code__,
                                        monitoring.events.PY_START | monitoring.events.PY_RETURN)
            result = run(cls, *args, 8)
            self.assertEqual(events, ["start", "return"] * 8)
            self.assertIs(result.a0, args[0])
        finally:
            monitoring.set_local_events(tool, cls.__init__.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_START, None)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_class_attributes_dynamic_return(self):
        from itertools import repeat

        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Record:
            def __init__(self, value):
                self.value = value

        def make(value):
            return Record(value)

        value = object()
        list(map(make, repeat(value, TIER2_THRESHOLD * 4)))
        ex = self.executor(make, "_CALL_CLASS_ATTRIBUTES")
        self.assertIn("_DYNAMIC_EXIT", get_opnames(ex))
        result = self.executed(ex, "class_entries", make, value)
        self.assertIs(result.value, value)
        # Return to another caller without reusing the warmup caller's offset.
        def other_caller():
            return ("before", make(value), "after")
        result = self.executed(ex, "class_entries", other_caller)
        self.assertEqual((result[0], result[2]), ("before", "after"))
        self.assertIs(result[1].value, value)

    @requires_call_regions
    def test_class_attributes_owned_arguments(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Record:
            def __init__(self, a, b):
                self.a = a
                self.b = b

        def run(values, n):
            result = None
            for _ in range(n):
                result = Record(values.pop(), values.pop())
            return result

        run([object() for _ in range(TIER2_THRESHOLD * 2)], TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_CLASS_ATTRIBUTES")
        deleted = []

        class Value:
            def __del__(self):
                deleted.append(id(self))

        values = [Value() for _ in range(16)]
        refs = [weakref.ref(value) for value in values]
        result = self.executed(ex, "class_entries", run, values, 8)
        self.assertFalse(values)
        self.assertEqual(len(deleted), 14)
        self.assertTrue(all(ref() is None for ref in refs[2:]))
        self.assertIs(result.a, refs[1]())
        self.assertIs(result.b, refs[0]())
        del result
        self.assertEqual(len(deleted), 16)
        self.assertTrue(all(ref() is None for ref in refs))

    def executor(self, func, opcode):
        matches = [ex for ex in get_all_executors(func)
                   if any(name == opcode or
                          (name.startswith(opcode + "_") and
                           name[len(opcode) + 1:].isdigit())
                          for name in get_opnames(ex))]
        self.assertTrue(matches, (opcode, [get_opnames(ex)
                                         for ex in get_all_executors(func)]))
        return matches[0]

    def executed(self, ex, counter, func, *args):
        before = ex.get_region_stats()
        result = func(*args)
        after = ex.get_region_stats()
        self.assertGreater(after[counter], before[counter], (before, after))
        if counter.endswith("_entries"):
            family = counter.split("_")[0]
            for key in (family + "_guard_exits", family + "_overflow_exits",
                        "allocation_errors"):
                if key in before:
                    self.assertEqual(after[key], before[key], (before, after))
        return result

    def warm_int(self, expression, compare=False):
        func = arithmetic(expression)
        func(31, 17, 9, 1000, TIER2_THRESHOLD)
        ex = self.executor(func, "_INT_REGION_COMPARE" if compare else "_INT_REGION")
        return func, ex

    def warm_enumerate(self, run):
        for _ in range(TIER2_THRESHOLD // 64 + 8):
            run(enumerate([None] * 64))
        return self.executor(run, "_ITER_NEXT_ENUM_LIST")

    def warm_enumerate_scan(self, comparison=">=", field=0):
        namespace = {}
        exec(
            "def run(iterator, key):\n"
            "    position = -1\n"
            "    item = None\n"
            "    for position, item in iterator:\n"
            f"        if item[{field}] {comparison} key:\n"
            "            break\n"
            "    return position, item\n",
            namespace,
        )
        run = namespace["run"]
        values = [(i, i) for i in range(128)]
        key = 1000 if comparison in (">", ">=", "==") else -1
        if comparison == "!=":
            values = [(0, 0)] * 128
            key = 0
        for _ in range(TIER2_THRESHOLD // 128 + 8):
            run(enumerate(values), key)
        return run, self.executor(run, "_ENUM_LIST_INT_SCAN")

    def warm_list_contains(self, invert=False):
        run = arithmetic("a not in b" if invert else "a in b")
        run(99, list(range(128)), 0, 0, TIER2_THRESHOLD)
        return run, self.executor(run, "_CONTAINS_OP_LIST_INT")

    def warm_dict_store(self, mapping_type=collections.Counter):
        def run(mapping, key, n):
            for _ in range(n):
                previous = mapping[key]
                mapping[key] = previous + 1
            return mapping

        run.__code__ = run.__code__.replace()
        run(mapping_type(), "key", TIER2_THRESHOLD)
        return run, self.executor(run, "_STORE_SUBSCR_DICT_INHERITED")

    def test_dict_store_inherited_values(self):
        run, ex = self.warm_dict_store()
        for key in ("key", 10000, (b"a", b"b")):
            for value in (0, -10000, 2**100):
                with self.subTest(key=key, value=value):
                    mapping = collections.Counter({key: value})
                    if value == 2**100:
                        # The preceding compact-int addition exits first.
                        self.assertIs(run(mapping, key, 64), mapping)
                    else:
                        self.assertIs(self.executed(ex, "dict_store_entries",
                                                   run, mapping, key, 64), mapping)
                    self.assertEqual(mapping[key], value + 64)

    def test_dict_store_recorded_receiver(self):
        def run(mapping, key, value, n):
            for _ in range(n):
                mapping[key] = value

        mapping = collections.Counter()
        value = object()
        run(mapping, 0, value, TIER2_THRESHOLD)
        ex = self.executor(run, "_STORE_SUBSCR_DICT_INHERITED")
        self.executed(ex, "dict_store_entries", run, mapping, 0, value, 8)
        self.assertIs(mapping[0], value)

        events = []

        class Other(dict):
            def __setitem__(self, key, value):
                events.append((key, value))

        self.executed(ex, "dict_store_fallbacks", run, Other(), 0, value, 8)
        self.assertEqual(events, [(0, value)] * 8)
        values = [None]
        self.executed(ex, "dict_store_fallbacks", run, values, 0, value, 8)
        self.assertIs(values[0], value)

    def test_dict_store_inherited_delete_and_receiver(self):
        calls = []
        class Mapping(collections.Counter):
            def __delitem__(self, key):
                calls.append(key)
                super().__delitem__(key)

        run, ex = self.warm_dict_store(Mapping)
        mapping = Mapping(key=0)
        self.executed(ex, "dict_store_entries", run, mapping, "key", 8)
        self.assertEqual(mapping["key"], 8)
        self.assertEqual(calls, [])
        del mapping["key"]
        self.assertEqual(calls, ["key"])
        # An unrelated receiver must keep its assignment implementation.
        class Other(dict):
            def __setitem__(self, key, value):
                calls.append(value)
                super().__setitem__(key, value)
        self.assertEqual(run(Other(key=0), "key", 8), {"key": 8})
        self.assertEqual(calls[1:], list(range(1, 9)))
        self.assertEqual(run([0], 0, 8), [8])

    def test_dict_store_inherited_type_invalidation(self):
        for change_base in (False, True):
            with self.subTest(change_base=change_base):
                class Base(collections.Counter):
                    pass
                class Mapping(Base):
                    pass
                run, ex = self.warm_dict_store(Mapping)
                calls = []
                def setitem(self, key, value):
                    calls.append(value)
                    dict.__setitem__(self, key, value)
                owner = Base if change_base else Mapping
                owner.__setitem__ = setitem
                self.assertFalse(ex.is_valid())
                self.assertEqual(run(Mapping(key=0), "key", 8), {"key": 8})
                self.assertEqual(calls, list(range(1, 9)))
                del owner.__setitem__
                run, ex = self.warm_dict_store(Mapping)
                self.executed(ex, "dict_store_entries", run, Mapping(key=0), "key", 8)
                self.assertEqual(calls, list(range(1, 9)))

    def test_dict_store_inherited_hash_error(self):
        run, ex = self.warm_dict_store()
        calls = []
        class Key:
            def __hash__(self):
                calls.append(len(calls) + 1)
                if len(calls) == 4:
                    raise RuntimeError("store hash")
                return 42
        key = Key()
        mapping = collections.Counter({key: 0})
        calls.clear()
        before = ex.get_region_stats()["dict_store_entries"]
        try:
            run(mapping, key, 8)
        except RuntimeError as error:
            self.assertEqual(str(error), "store hash")
            tb = error.__traceback__
            while tb.tb_frame.f_code is not run.__code__:
                tb = tb.tb_next
            self.assertEqual(tb.tb_lineno, run.__code__.co_firstlineno + 3)
            self.assertEqual(tb.tb_frame.f_locals["previous"], 1)
        else:
            self.fail("store hash error was skipped")
        self.assertEqual(calls, [1, 2, 3, 4])
        self.assertEqual(mapping[key], 1)
        self.assertGreater(ex.get_region_stats()["dict_store_entries"], before)

    def test_dict_store_inherited_hash_changes_method(self):
        class Mapping(collections.Counter):
            pass
        run, ex = self.warm_dict_store(Mapping)
        hashes = []
        stores = []
        def setitem(self, key, value):
            stores.append(value)
            dict.__setitem__(self, key, value)
        class Key:
            def __hash__(self):
                hashes.append(len(hashes) + 1)
                if len(hashes) == 4:
                    Mapping.__setitem__ = setitem
                return 42
        key = Key()
        mapping = Mapping({key: 0})
        hashes.clear()
        before = ex.get_region_stats()["dict_store_entries"]
        run(mapping, key, 4)
        self.assertEqual(hashes, list(range(1, 9)))
        # The second store already selected dict's method before hashing.
        self.assertEqual(stores, [3, 4])
        self.assertFalse(ex.is_valid())
        self.assertEqual(mapping[key], 4)
        self.assertGreater(ex.get_region_stats()["dict_store_entries"], before)

    def test_list_contains_int_values(self):
        for invert in (False, True):
            run, ex = self.warm_list_contains(invert)
            for values in ([], [1], list(range(128)),
                           [-(2**30-1), 2**30-1, 10000, -10000]):
                for value in (-2**30+1, -10000, -1, 0, 1, 64, 127, 128, 10000, 2**30-1):
                    with self.subTest(invert=invert, values=values[:3], value=value):
                        self.assertEqual(
                            self.executed(ex, "contains_entries", run, value, values, 0, 0, 8),
                            (value in values) ^ invert)
            before = ex.get_region_stats()["contains_iterations"]
            self.assertEqual(run(10000, [int("10000")], 0, 0, 8), not invert)
            self.assertGreater(ex.get_region_stats()["contains_iterations"], before)

    def test_list_contains_int_fallback(self):
        run, ex = self.warm_list_contains()
        for value, container in [(True, [0, 1]), (1, [True]),
                                 (2**100, [0, 2**100]), (1, [2**100, 1]),
                                 ("a", ["b", "a"]), (1, (0, 1)),
                                 (1, {1, 2}), (1, {1: None})]:
            with self.subTest(value=value, container=container):
                self.assertEqual(run(value, container, 0, 0, 8), value in container)
        with self.assertRaises(TypeError):
            run(1, None, 0, 0, 1)

        calls = []
        class Values(list):
            def __contains__(self, value):
                calls.append(value)
                return False
        self.assertFalse(run(1, Values([1]), 0, 0, 1))
        self.assertEqual(calls, [1])
        self.assertGreater(ex.get_region_stats()["contains_fallbacks"], 0)

    def test_list_contains_int_mutation_and_error(self):
        run, ex = self.warm_list_contains()
        calls = []
        values = list(range(64))
        class Value:
            def __eq__(self, other):
                calls.append(other)
                # The first iteration precedes the loop executor. Mutate on
                # its next iteration, inside the optimized operation's fallback.
                if len(calls) == 2:
                    values.clear()
                return False
        values.extend([Value(), 1000])
        before = ex.get_region_stats()["contains_iterations"]
        self.assertFalse(run(1000, values, 0, 0, 8))
        self.assertEqual(calls, [1000, 1000])
        self.assertEqual(values, [])
        self.assertGreater(ex.get_region_stats()["contains_iterations"], before)

        calls.clear()
        class Broken(int):
            def __eq__(self, other):
                calls.append(other)
                if len(calls) == 2:
                    raise RuntimeError("membership comparison")
                return False
        before = ex.get_region_stats()["contains_fallbacks"]
        try:
            run(1000, [0, 1, Broken(2), 1000], 0, 0, 8)
        except RuntimeError as error:
            self.assertEqual(str(error), "membership comparison")
            tb = error.__traceback__
            while tb.tb_frame.f_code is not run.__code__:
                tb = tb.tb_next
            self.assertEqual(tb.tb_lineno, 4)
        else:
            self.fail("membership comparison error was skipped")
        self.assertEqual(calls, [1000, 1000])
        self.assertGreater(ex.get_region_stats()["contains_fallbacks"], before)

    def test_enumerate_int_scan_comparisons(self):
        comparisons = {"<": operator.lt, "<=": operator.le,
                       "==": operator.eq, "!=": operator.ne,
                       ">": operator.gt, ">=": operator.ge}
        for field in (0, 1):
            for comparison, compare in comparisons.items():
                with self.subTest(field=field, comparison=comparison):
                    run, ex = self.warm_enumerate_scan(comparison, field)
                    values = [(i, 255-i) for i in range(256)]
                    for key in (-1, 0, 1, 64, 127, 255, 256):
                        expected = (-1, None)
                        consumed = 0
                        for position, item in enumerate(values):
                            expected = position, item
                            consumed += 1
                            if compare(item[field], key):
                                break
                        iterator = enumerate(values)
                        self.assertEqual(run(iterator, key), expected)
                        self.assertEqual(list(iterator), list(enumerate(values))[consumed:])
                    before = ex.get_region_stats()["enum_scan_iterations"]
                    same = [(0, 0)] * 200
                    key = 1000 if comparison in (">", ">=", "==") else -1
                    if comparison == "!=":
                        key = 0
                    self.assertEqual(run(enumerate(same), key), (199, (0, 0)))
                    self.assertGreater(ex.get_region_stats()["enum_scan_iterations"], before)

    def test_enumerate_int_scan_cache_and_alias(self):
        run, ex = self.warm_enumerate_scan()
        values = [(i,) for i in range(200)]
        for start in (-10, -5, 0, 1000, 1024, 1025, 2**100):
            for size in (0, 1, 2, 63, 64, 65, 128, 200):
                with self.subTest(start=start, size=size):
                    iterator = enumerate(values[:size], start)
                    expected = (start + size - 1, values[size-1]) if size else (-1, None)
                    self.assertEqual(run(iterator, 1000), expected)
                    self.assertEqual(list(iterator), [])
        iterator = enumerate(values)
        cached = next(iterator)
        before = ex.get_region_stats()["enum_scan_iterations"]
        self.assertEqual(run(iterator, 1000), (199, values[-1]))
        self.assertEqual(cached, (0, values[0]))
        self.assertEqual(ex.get_region_stats()["enum_scan_iterations"], before)
        self.assertEqual(run(iter(enumerate(values)), 80), (80, values[80]))
        self.assertEqual(run(iter(list(enumerate(values))), 80), (80, values[80]))

    def test_enumerate_int_scan_error_and_callback(self):
        run, ex = self.warm_enumerate_scan()
        values = [(i,) for i in range(200)]
        values[80] = ()
        iterator = enumerate(values)
        before = ex.get_region_stats()["enum_scan_iterations"]
        try:
            run(iterator, 1000)
        except IndexError as error:
            tb = error.__traceback__
            while tb.tb_frame.f_code is not run.__code__:
                tb = tb.tb_next
            self.assertEqual(tb.tb_lineno, 5)
            self.assertEqual(tb.tb_frame.f_locals["position"], 80)
            self.assertIs(tb.tb_frame.f_locals["item"], values[80])
        else:
            self.fail("tuple subscript error was skipped")
        self.assertGreater(ex.get_region_stats()["enum_scan_iterations"], before)
        self.assertEqual(next(iterator), (81, values[81]))

        calls = []
        class Value(int):
            def __ge__(self, other):
                calls.append((int(self), other))
                values[81] = (2000,)
                return False
        values = [(i,) for i in range(200)]
        values[80] = (Value(80),)
        self.assertEqual(run(enumerate(values), 1000), (81, (2000,)))
        self.assertEqual(calls, [(80, 1000)])
        for item in ((True,), (2**100,), [2000]):
            values[80] = item
            expected = next(((i, x) for i, x in enumerate(values) if x[0] >= 1000),
                            (199, values[-1]))
            self.assertEqual(run(enumerate(values), 1000), expected)

    def test_enumerate_int_scan_finalizer_order(self):
        run, ex = self.warm_enumerate_scan()
        calls = []
        values = [(i,) for i in range(200)]

        class Payload:
            def __del__(self):
                calls.append("finalize")
                values[82] = (2000,)

        class Value(int):
            def __ge__(self, other):
                calls.append("compare")
                # The next chunk must not delay releasing this item: the
                # cached tuple and frame will hold its last two references.
                values[80] = (80,)
                return False

        values[80] = (Value(80), Payload())
        before = ex.get_region_stats()["enum_scan_iterations"]
        self.assertEqual(run(enumerate(values), 1000), (82, (2000,)))
        self.assertEqual(calls, ["compare", "finalize"])
        self.assertGreater(ex.get_region_stats()["enum_scan_iterations"], before)

    def test_enumerate_int_scan_monitoring(self):
        run, ex = self.warm_enumerate_scan()
        values = [(i,) for i in range(128)]
        positions = []
        monitoring = sys.monitoring
        tool = 4
        monitoring.use_tool_id(tool, "test_enumerate_int_scan")

        def on_line(code, line):
            if line == 5:
                positions.append(sys._getframe(1).f_locals["position"])
                if positions[-1] == 64:
                    values[65] = (2000,)

        before = ex.get_region_stats()["enum_scan_iterations"]
        try:
            monitoring.register_callback(tool, monitoring.events.LINE, on_line)
            monitoring.set_local_events(tool, run.__code__, monitoring.events.LINE)
            self.assertEqual(run(enumerate(values), 1000), (65, (2000,)))
            self.assertEqual(positions, list(range(66)))
            self.assertEqual(ex.get_region_stats()["enum_scan_iterations"], before)
        finally:
            monitoring.set_local_events(tool, run.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.LINE, None)
            monitoring.free_tool_id(tool)

    def warm_named_globals(self, unrelated="unrelated"):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        ns = {}
        exec("class Box:\n    pass\n"
             f"stable = Box()\nstable.value = 7\n{unrelated} = 0\n"
             "def read(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n"
             "        total += stable.value\n"
             "    return total\n", ns)
        run = ns["read"]
        self.assertEqual(run(TIER2_THRESHOLD), 7 * TIER2_THRESHOLD)
        ex = next(iter(get_all_executors(run)))
        self.assertTrue(ex.is_valid())
        return run, ex, ns

    def test_named_globals_unrelated_replacements(self):
        # Bloom collisions may invalidate unrelated entries. Require retention
        # for at least one of several namespaces/keys, while checking results
        # and required invalidation in every case.
        retained = False
        for attempt in range(8):
            name = f"unrelated_{attempt}"
            run, ex, ns = self.warm_named_globals(name)
            for value in range(1, 17):
                ns[name] = value
                self.assertEqual(run(8), 56)
            retained |= ex.is_valid()
            # The used value must invalidate before its old reference dies,
            # even after many updates to unrelated entries.
            old = weakref.ref(ns["stable"])
            replacement = ns["Box"]()
            replacement.value = 11
            ns["stable"] = replacement
            self.assertFalse(ex.is_valid())
            self.assertIsNone(old())
            self.assertEqual(run(8), 88)
        self.assertTrue(retained)

    def test_named_globals_recompile_after_mutations(self):
        run, ex, ns = self.warm_named_globals()
        for value in range(16):
            replacement = ns["Box"]()
            replacement.value = value
            ns["stable"] = replacement
            self.assertFalse(ex.is_valid())
            self.assertEqual(run(TIER2_THRESHOLD), value * TIER2_THRESHOLD)
            ex = next(iter(get_all_executors(run)))
            self.assertTrue(ex.is_valid())
        # Named folding still works past the old dictionary mutation limit.
        self.assertIn("_GUARD_GLOBALS_VERSION_AND_IDENTITY",
                      [uop[0] for uop in ex])
        ns["unrelated"] = 99
        self.assertEqual(run(8), 120)

    def test_named_globals_legacy_dependency(self):
        run, unused, ns = self.warm_named_globals()
        exec("def legacy(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n        total += stable.value\n"
             "    return total\n", ns)
        run(TIER2_THRESHOLD)
        named = next(iter(get_all_executors(run)))
        legacy = ns["legacy"]
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_CALL_REGIONS": "0"}):
            self.assertEqual(legacy(TIER2_THRESHOLD), 7 * TIER2_THRESHOLD)
        old = next(iter(get_all_executors(legacy)))
        self.assertTrue(old.is_valid())
        ns["unrelated"] = 4
        self.assertFalse(old.is_valid())
        replacement = ns["Box"]()
        replacement.value = 11
        ns["stable"] = replacement
        self.assertFalse(named.is_valid())
        self.assertEqual(run(8), 88)
        self.assertEqual(legacy(8), 88)

    @support.nomemtest
    def test_named_globals_invalidation_allocation_failure(self):
        from test.support.import_helper import import_module

        capi = import_module("_testcapi")
        run, ex, ns = self.warm_named_globals()
        old = weakref.ref(ns["stable"])
        replacement = ns["Box"]()
        replacement.value = 11
        set_nomemory, clear = capi.set_nomemory, capi.remove_mem_hooks
        set_nomemory(0, 1)
        try:
            # Collecting dependent executors needs an allocation. Failure
            # must invalidate all executors without leaking MemoryError.
            ns["stable"] = replacement
        finally:
            clear()
        self.assertFalse(ex.is_valid())
        self.assertIsNone(old())
        self.assertEqual(run(8), 88)

    def test_named_globals_finalizer_reentry(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        ns = {}
        exec("events = []\nunrelated = 0\n"
             "class Box:\n"
             "    def __init__(self, value):\n        self.value = value\n"
             "    def __del__(self):\n"
             "        global unrelated\n"
             "        if self.value == 7:\n"
             "            unrelated = 13\n"
             "            events.append(read(8))\n"
             "stable = Box(7)\n"
             "def read(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n        total += stable.value\n"
             "    return total\n"
             "def read_other(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n        total += unrelated\n"
             "    return total\n", ns)
        run, other = ns["read"], ns["read_other"]
        run(TIER2_THRESHOLD)
        other(TIER2_THRESHOLD)
        first = next(iter(get_all_executors(run)))
        second = next(iter(get_all_executors(other)))
        old = weakref.ref(ns["stable"])
        ns["stable"] = ns["Box"](11)
        self.assertIsNone(old())
        self.assertFalse(first.is_valid())
        self.assertFalse(second.is_valid())
        self.assertEqual(ns["events"], [88])
        self.assertEqual(other(8), 104)

    def test_named_globals_general_key(self):
        run, ex, ns = self.warm_named_globals()
        class Key:
            def __hash__(self):
                return hash("stable")
            def __eq__(self, other):
                return other == "stable"
        replacement = ns["Box"]()
        replacement.value = 23
        ns[Key()] = replacement
        self.assertFalse(ex.is_valid())
        self.assertEqual(run(8), 184)

    def test_named_globals_builtin_shadowing(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        retained = False
        for attempt in range(8):
            name = f"unrelated_{attempt}"
            ns = {name: 0}
            exec("def read(n):\n"
                 "    total = 0\n"
                 "    for _ in range(n):\n        total += len(())\n"
                 "    return total\n", ns)
            run = ns["read"]
            self.assertEqual(run(TIER2_THRESHOLD), 0)
            ex = next(iter(get_all_executors(run)))
            ns[name] = 17
            retained |= ex.is_valid()
            ns["len"] = lambda value: 3
            self.assertFalse(ex.is_valid())
            self.assertEqual(run(8), 24)
        self.assertTrue(retained)

    def test_global_guard_structure_and_lifetime(self):
        for mutation in ("add", "delete", "clear", "replace"):
            with self.subTest(mutation=mutation):
                run, ex, ns = self.warm_named_globals()
                old = weakref.ref(ns["stable"])
                if mutation == "add":
                    ns["new_name"] = None
                elif mutation == "delete":
                    del ns["stable"]
                elif mutation == "clear":
                    ns.clear()
                else:
                    replacement = ns["Box"]()
                    replacement.value = 11
                    ns["stable"] = replacement
                self.assertFalse(ex.is_valid())
                if mutation != "add":
                    self.assertIsNone(old())
                if mutation in ("delete", "clear"):
                    with self.assertRaises(NameError):
                        run(8)
                else:
                    self.assertEqual(run(8), 56 if mutation == "add" else 88)

    def test_global_guard_copied_namespace(self):
        run, ex, ns = self.warm_named_globals()
        other = ns.copy()
        other["stable"] = ns["Box"]()
        other["stable"].value = 19
        alias = types.FunctionType(run.__code__, other)
        self.assertEqual(alias(8), 152)
        self.assertEqual(run(8), 56)

    def test_global_guard_namespace_lifetime(self):
        run, ex, ns = self.warm_named_globals()
        old = weakref.ref(ns["stable"])
        other = ns.copy()
        del other["read"]
        other["stable"] = ns["Box"]()
        other["stable"].value = 19
        alias = types.FunctionType(run.__code__, other)
        # The identity guard borrows its mapping pointer. Its dependency must
        # invalidate before the original namespace can be freed and reused.
        del run, ns
        gc.collect()
        self.assertIsNone(old())
        self.assertFalse(ex.is_valid())
        self.assertEqual(alias(8), 152)

    def warm_list_remove(self, slots=False, bound=True):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        ns = {}
        layout = "    __slots__ = ('cells',)\n" if slots else ""
        call = "owner.discard(index, value)" if bound else "discard(owner, index, value)"
        exec("class Holder:\n" + layout + "    pass\n"
             "def discard(owner, index, value):\n"
             "    if value in owner.cells[index]:\n"
             "        owner.cells[index].remove(value)\n"
             "        return True\n"
             "    else:\n"
             "        return False\n"
             "Holder.discard = discard\n"
             "def run(owner, index, value, n):\n"
             "    hits = 0\n"
             "    for _ in range(n):\n"
             f"        hits += {call}\n"
             "    return hits\n", ns)
        owner = ns["Holder"]()
        owner.cells = [list(range(32))]
        run = ns["run"]
        self.assertEqual(run(owner, 0, 99, TIER2_THRESHOLD), 0)
        ex = self.executor(run, "_CALL_PY_LIST_REMOVE")
        self.assertIn(f"_CALL_PY_LIST_REMOVE_{int(not bound)}", get_opnames(ex))
        self.assertEqual(self.executed(ex, "call_remove_entries", run, owner, 0, 99, 8), 0)
        return owner, run, ex, ns

    def warm_local_list_remove(self, slots=False):
        owner, _, _, ns = self.warm_list_remove(slots=slots, bound=False)
        exec("def run_local(owner, index, value, n):\n"
             "    return sum(map(discard, [owner] * n, [index] * n, [value] * n))\n", ns)
        run = ns["run_local"]
        self.assertEqual(run(owner, 0, 99, 3 * TIER2_THRESHOLD), 0)
        ex = self.executor(ns["discard"], "_LIST_REMOVE_LOCAL")
        self.assertEqual(self.executed(ex, "call_remove_entries", run, owner, 0, 99, 8), 0)
        return owner, run, ex, ns

    @requires_call_regions
    def test_local_list_remove_matrix(self):
        for slots in (False, True):
            with self.subTest(slots=slots):
                owner, run, ex, ns = self.warm_local_list_remove(slots)
                for length in (0, 1, 2, 31, 64, 65):
                    for index in (0, -1):
                        values = [i % 5 for i in range(length)]
                        owner.cells = [values]
                        expected = min(8, values.count(3))
                        reference = values.copy()
                        for _ in range(expected):
                            reference.remove(3)
                        self.assertEqual(run(owner, index, 3, 8), expected)
                        self.assertEqual(values, reference)
                owner.cells = [[300] * 16 + [None]]
                self.assertEqual(self.executed(ex, "call_remove_hits", run,
                                               owner, 0, 300, 8), 8)
                self.assertEqual(owner.cells, [[300] * 8 + [None]])
                frames = []
                class Equal:
                    def __eq__(self, other):
                        frames.append(sys._getframe(1).f_code)
                        return True
                owner.cells = [[Equal()]]
                self.assertEqual(run(owner, 0, 300, 8), 1)
                self.assertEqual(frames, [ns["discard"].__code__] * 2)

    @requires_call_regions
    def test_local_list_remove_monitoring(self):
        owner, run, ex, ns = self.warm_local_list_remove()
        monitoring = sys.monitoring
        tool = monitoring.PROFILER_ID
        monitoring.use_tool_id(tool, "local list remove test")
        frames = []
        def on_return(code, offset, value):
            frames.append((sys._getframe(1).f_code, value))
        before = ex.get_region_stats()["call_remove_entries"]
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, on_return)
            monitoring.set_local_events(tool, ns["discard"].__code__, monitoring.events.PY_RETURN)
            owner.cells = [[300] * 3]
            self.assertEqual(run(owner, 0, 300, 8), 3)
            self.assertEqual(frames, [(ns["discard"].__code__, i < 3) for i in range(8)])
            self.assertEqual(ex.get_region_stats()["call_remove_entries"], before)
        finally:
            monitoring.set_local_events(tool, ns["discard"].__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_list_remove_matrix(self):
        for slots in (False, True):
            for bound in (False, True):
                with self.subTest(slots=slots, bound=bound):
                    owner, run, ex, _ = self.warm_list_remove(slots, bound)
                    for length in (0, 1, 2, 31, 64, 65):
                        for index in (0, -1):
                            for needle in (-1, 0, 3, 64):
                                values = [i % 5 for i in range(length)]
                                owner.cells = [values]
                                alias = values
                                expected = min(8, values.count(needle))
                                reference = values.copy()
                                for _ in range(expected):
                                    reference.remove(needle)
                                self.assertEqual(run(owner, index, needle, 8), expected)
                                self.assertIs(owner.cells[0], alias)
                                self.assertEqual(values, reference)
                    # Exercise successful native deletion, including duplicates
                    # and an unsupported tail that must not be inspected.
                    owner.cells = [[300] * 16 + [None]]
                    self.assertEqual(self.executed(ex, "call_remove_hits", run,
                                                   owner, 0, 300, 8), 8)
                    self.assertEqual(owner.cells, [[300] * 8 + [None]])

    @requires_call_regions
    def test_list_remove_fallbacks(self):
        owner, run, _, _ = self.warm_list_remove()
        class Int(int):
            pass
        class List(list):
            pass
        for values, needle in (([True, 1], 1), ([Int(2), 2], 2),
                               ([2**100, 2**100], 2**100),
                               (List([3, 3]), 3), ([1, 1], Int(1))):
            owner.cells = [values]
            self.assertEqual(run(owner, 0, needle, 8), 2)
            self.assertEqual(values, [])
        owner.cells = List([[2, 2]])
        self.assertEqual(run(owner, Int(-1), 2, 8), 2)
        for index, error in ((10, IndexError), (-2, IndexError), (1.5, TypeError)):
            owner.cells = [[1]]
            try:
                run(owner, index, 1, 8)
            except error as caught:
                tb = caught.__traceback__
                names = []
                while tb is not None:
                    names.append(tb.tb_frame.f_code.co_name)
                    tb = tb.tb_next
                self.assertIn("discard", names)
            else:
                self.fail(f"expected {error.__name__}")

    @requires_call_regions
    def test_list_remove_comparison_callback(self):
        owner, run, _, _ = self.warm_list_remove()
        calls = []
        class Equal:
            def __eq__(self, other):
                calls.append(sys._getframe(1).f_code.co_name)
                if len(calls) == 1:
                    owner.cells[0].append(77)
                return True
        owner.cells = [[Equal()]]
        self.assertEqual(run(owner, 0, 77, 8), 2)
        self.assertEqual(calls, ["discard", "discard"])
        self.assertEqual(owner.cells, [[]])

    @requires_call_regions
    def test_list_remove_descriptor_and_code_changes(self):
        owner, run, _, ns = self.warm_list_remove()
        calls = []
        values = [5] * 16
        def cells(self):
            calls.append(sys._getframe(1).f_code.co_name)
            return [values]
        ns["Holder"].cells = property(cells)
        self.assertEqual(run(owner, 0, 5, 8), 8)
        self.assertEqual(calls, ["discard"] * 16)
        owner, run, _, ns = self.warm_list_remove(bound=False)
        exec("def replacement(owner, index, value):\n    return False\n", ns)
        ns["discard"].__code__ = ns["replacement"].__code__
        owner.cells = [[5] * 16]
        self.assertEqual(run(owner, 0, 5, 8), 0)
        self.assertEqual(owner.cells, [[5] * 16])

    @requires_call_regions
    def test_list_remove_monitoring(self):
        owner, run, ex, ns = self.warm_list_remove()
        monitoring = sys.monitoring
        tool = monitoring.PROFILER_ID
        monitoring.use_tool_id(tool, "list remove test")
        lines = []
        def on_line(code, line):
            lines.append(sys._getframe(1).f_code.co_name)
        before = ex.get_region_stats()["call_remove_entries"]
        try:
            monitoring.register_callback(tool, monitoring.events.LINE, on_line)
            monitoring.set_local_events(tool, ns["discard"].__code__, monitoring.events.LINE)
            owner.cells = [[1] * 16]
            self.assertEqual(run(owner, 0, 1, 8), 8)
            self.assertTrue(lines)
            self.assertEqual(set(lines), {"discard"})
            self.assertEqual(ex.get_region_stats()["call_remove_entries"], before)
        finally:
            monitoring.set_local_events(tool, ns["discard"].__code__, 0)
            monitoring.register_callback(tool, monitoring.events.LINE, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_list_remove_profile(self):
        for warm in (self.warm_list_remove, self.warm_local_list_remove):
            with self.subTest(warm=warm.__name__):
                owner, run, ex, ns = warm()
                events = []
                def profile(frame, event, arg):
                    if (frame.f_code is ns["discard"].__code__
                            and event in ("c_call", "c_return")
                            and getattr(arg, "__name__", None) == "remove"):
                        events.append(event)
                owner.cells = [[300] * 16]
                before = ex.get_region_stats()["call_remove_entries"]
                old_profile = sys.getprofile()
                try:
                    sys.setprofile(profile)
                    self.assertEqual(run(owner, 0, 300, 8), 8)
                finally:
                    sys.setprofile(old_profile)
                self.assertEqual(events, ["c_call", "c_return"] * 8)
                self.assertEqual(ex.get_region_stats()["call_remove_entries"], before)

    @requires_call_regions
    def test_list_remove_owned_receiver(self):
        owner, _, _, ns = self.warm_list_remove(bound=False)
        events = []
        inspect_frame = [False]
        cls = type(owner)
        def finalize(obj):
            if inspect_frame[0]:
                events.append((sys._getframe(1).f_code.co_name, len(obj.cells[0])))
        cls.__del__ = finalize
        ns["cells"] = owner.cells
        refs = sys.getrefcount(owner.cells)
        exec("def initialize(obj):\n"
             "    obj.cells = cells\n"
             "Holder.__init__ = initialize\n"
             "def run_owned(n):\n"
             "    hits = 0\n"
             "    for _ in range(n):\n"
             "        hits += discard(Holder(), 0, 77)\n"
             "    return hits\n", ns)
        run = ns["run_owned"]
        self.assertEqual(run(8 * TIER2_THRESHOLD), 0)
        ex = self.executor(run, "_CALL_PY_LIST_REMOVE")
        owner.cells[0] = [77] * 16
        inspect_frame[0] = True
        try:
            self.assertEqual(self.executed(ex, "call_remove_hits", run, 8), 8)
            self.assertEqual(events, [("run_owned", size) for size in range(15, 7, -1)])
            self.assertEqual(sys.getrefcount(owner.cells), refs)
        finally:
            del cls.__del__

    @requires_call_regions
    def test_list_remove_extra_effects(self):
        owner, run, _, ns = self.warm_list_remove(bound=False)
        events = []
        ns["events"] = events
        exec("def discard(owner, index, value):\n"
             "    if value in owner.cells[index]:\n"
             "        owner.cells[index].remove(value)\n"
             "        events.append(value)\n"
             "        return True\n"
             "    else:\n"
             "        return False\n", ns)
        owner.cells = [[2] * 16]
        self.assertEqual(run(owner, 0, 2, 8), 8)
        self.assertEqual(events, [2] * 8)

    def warm_attribute_search(self, symbol=">=", slots=False, bound=True, field=0):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        ns = {"walk": enumerate, "size": len}
        layout = "    __slots__ = ('cells',)\n" if slots else ""
        call = "owner.search(key)" if bound else "search(owner, key)"
        exec("class Holder:\n" + layout + "    pass\n"
             "def search(owner, key):\n"
             "    for position, item in walk(owner.cells):\n"
             f"        if item[{field}] {symbol} key:\n"
             "            return position\n"
             "    return size(owner.cells)\n"
             "Holder.search = search\n"
             "def run(owner, key, n):\n"
             "    result = None\n"
             "    for _ in range(n):\n"
             f"        result = {call}\n"
             "    return result\n", ns)
        owner = ns["Holder"]()
        owner.cells = [(None,) * field + (i,) for i in range(31)]
        run = ns["run"]
        run(owner, 17, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE_SEARCH")
        comparison = ("<", "<=", "==", "!=", ">", ">=").index(symbol)
        self.assertIn(f"_CALL_PY_ATTRIBUTE_SEARCH_{6 * (not bound) + comparison}",
                      get_opnames(ex))
        self.executed(ex, "call_search_entries", run, owner, 17, 8)
        return owner, run, ex, ns

    @requires_call_regions
    def test_attribute_search_matrix(self):
        for slots in (False, True):
            for bound in (False, True):
                for symbol, compare in (("<", operator.lt), ("<=", operator.le),
                                        ("==", operator.eq), ("!=", operator.ne),
                                        (">", operator.gt), (">=", operator.ge)):
                    with self.subTest(slots=slots, bound=bound, symbol=symbol):
                        owner, run, ex, ns = self.warm_attribute_search(symbol, slots, bound)
                        for length in (0, 1, 31, 64):
                            owner.cells = [(i - 16,) for i in range(length)]
                            random.Random(length).shuffle(owner.cells)
                            for key in (-31, 0, 17, 65):
                                expected = next((i for i, item in enumerate(owner.cells)
                                                 if compare(item[0], key)), length)
                                self.assertEqual(self.executed(ex, "call_search_entries", run,
                                                               owner, key, 8), expected)
                        owner.cells = [(i,) for i in range(65)]
                        self.assertEqual(run(owner, 17, 8), ns["search"](owner, 17))
        for field in (1, 31):
            with self.subTest(field=field):
                owner, run, ex, ns = self.warm_attribute_search(field=field)
                self.assertEqual(run(owner, 17, 8), 17)

    @requires_call_regions
    def test_attribute_search_fallbacks(self):
        owner, run, ex, ns = self.warm_attribute_search()
        class Int(int):
            pass
        class Tuple(tuple):
            pass
        class List(list):
            pass
        for cells, key in (([(False,), (True,)], True),
                           ([(2**100,), (2**101,)], 2**100 + 1),
                           ([(Int(1),), (Int(2),)], Int(2)),
                           ([Tuple((1,)), Tuple((2,))], 2),
                           (List([(1,), (2,)]), 2),
                           (([1], [2]), 2)):
            with self.subTest(cells=cells, key=key):
                owner.cells = cells
                self.assertEqual(run(owner, key, 8), ns["search"](owner, key))
        for cells, exception in (([()], IndexError), ([object()], TypeError)):
            owner.cells = cells
            with self.assertRaises(exception):
                run(owner, 17, 8)
            # assertRaises clears the traceback; capture it in the next call.
            try:
                run(owner, 17, 8)
            except exception as error:
                tb = error.__traceback__
                while tb.tb_next:
                    tb = tb.tb_next
                self.assertIs(tb.tb_frame.f_code, ns["search"].__code__)

    @requires_call_regions
    def test_attribute_search_comparison_callback(self):
        owner, run, ex, ns = self.warm_attribute_search()
        events = []
        class Key:
            def __ge__(self, other):
                events.append(sys._getframe(1).f_code)
                owner.cells.append((100,))
                return False
        for _ in range(8):
            owner.cells = [(0,), (Key(),)]
            self.assertEqual(run(owner, 17, 1), 2)
        self.assertEqual(events, [ns["search"].__code__] * 8)

    @requires_call_regions
    def test_attribute_search_global_changes(self):
        owner, run, ex, ns = self.warm_attribute_search()
        events = []
        def replacement_walk(items):
            events.append(sys._getframe(1).f_code)
            return enumerate(items, 100)
        ns["walk"] = replacement_walk
        self.assertEqual(run(owner, 17, 8), 117)
        self.assertEqual(events, [ns["search"].__code__] * 8)
        ns["walk"] = enumerate
        ns["size"] = lambda items: 1000
        self.assertEqual(run(owner, 100, 8), 1000)
        ns["size"] = len
        original = ns["search"]
        original.__code__ = (lambda owner, key: "changed").__code__
        self.assertEqual(run(owner, 17, 8), "changed")

    @requires_call_regions
    def test_attribute_search_callee_namespace(self):
        owner, run, _, ns = self.warm_attribute_search()
        callee_globals = {"walk": enumerate, "size": len,
                          "__builtins__": dict(vars(builtins))}
        exec("def search(owner, key):\n"
             "    for position, item in walk(owner.cells):\n"
             "        if item[0] >= key:\n"
             "            return position\n"
             "    return size(owner.cells)\n", callee_globals)
        type(owner).search = callee_globals["search"]
        # These names belong to the caller and must not guard the callee.
        ns["walk"] = ns["size"] = lambda items: "caller"
        exec("def run_separate(owner, key, n):\n"
             "    for _ in range(n):\n"
             "        result = owner.search(key)\n"
             "    return result\n", ns)
        run = ns["run_separate"]
        self.assertEqual(run(owner, 17, TIER2_THRESHOLD), 17)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE_SEARCH")
        self.assertEqual(self.executed(ex, "call_search_entries", run, owner, 17, 8), 17)
        callee_globals["size"] = lambda items: 2000
        self.assertEqual(run(owner, 100, 8), 2000)
        del callee_globals["size"]
        callee_globals["__builtins__"]["size"] = lambda items: 3000
        self.assertEqual(run(owner, 100, 8), 3000)

    @requires_call_regions
    def test_attribute_search_descriptor_change(self):
        owner, run, ex, ns = self.warm_attribute_search()
        events = []
        def getter(owner):
            events.append(sys._getframe(1).f_code)
            return [(100,)]
        type(owner).cells = property(getter)
        self.assertEqual(run(owner, 17, 8), 0)
        self.assertEqual(events, [ns["search"].__code__] * 8)

    @requires_call_regions
    def test_attribute_search_monitoring(self):
        owner, run, ex, ns = self.warm_attribute_search()
        monitoring = sys.monitoring
        tool = monitoring.OPTIMIZER_ID
        code = ns["search"].__code__
        events = []
        monitoring.use_tool_id(tool, "attribute search")
        try:
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION,
                                         lambda code, offset: events.append(code))
            monitoring.set_local_events(tool, code, monitoring.events.INSTRUCTION)
            self.assertEqual(run(owner, 17, 8), 17)
            self.assertIn(code, events)
        finally:
            monitoring.set_local_events(tool, code, 0)
            monitoring.register_callback(tool, monitoring.events.INSTRUCTION, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_attribute_search_owned_receiver(self):
        owner, _, _, ns = self.warm_attribute_search(bound=False)
        events = []
        cls = type(owner)
        inspect_frame = [False]
        def finalize(obj):
            if inspect_frame[0]:
                events.append(sys._getframe(1).f_code.co_name)
        cls.__del__ = finalize
        ns["cells"] = owner.cells
        refs = sys.getrefcount(owner.cells)
        exec("def initialize(obj):\n"
             "    obj.cells = cells\n"
             "Holder.__init__ = initialize\n"
             "def run_owned(n):\n"
             "    result = None\n"
             "    for _ in range(n):\n"
             "        result = search(Holder(), 17)\n"
             "    return result\n", ns)
        run = ns["run_owned"]
        self.assertEqual(run(8 * TIER2_THRESHOLD), 17)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE_SEARCH")
        events.clear()
        inspect_frame[0] = True
        self.assertEqual(self.executed(ex, "call_search_entries", run, 8), 17)
        self.assertEqual(events, ["run_owned"] * 8)
        self.assertEqual(sys.getrefcount(owner.cells), refs)
        # Keep the helper's original receiver out of the finalizer assertions.
        del cls.__del__

    @requires_call_regions
    def test_attribute_search_general_key_globals(self):
        owner, run, ex, ns = self.warm_attribute_search()
        events = []
        class Collision:
            def __hash__(self):
                return hash("walk")
            def __eq__(self, other):
                events.append((other, sys._getframe(1).f_code))
                return False
        del ns["walk"]
        ns[Collision()] = None
        ns["walk"] = enumerate
        events.clear()
        self.assertEqual(run(owner, 17, 8), 17)
        self.assertTrue(events)
        self.assertTrue(all(name == "walk" and code is ns["search"].__code__
                            for name, code in events))

    @requires_call_regions
    def test_attribute_search_extra_effects(self):
        owner, run, ex, ns = self.warm_attribute_search()
        events = []
        ns["observe"] = events.append
        exec("def replacement(owner, key):\n"
             "    for position, item in walk(owner.cells):\n"
             "        if item[0] >= key:\n"
             "            observe(position)\n"
             "            return position\n"
             "    return size(owner.cells)\n", ns)
        ns["search"].__code__ = ns["replacement"].__code__
        self.assertEqual(run(owner, 17, TIER2_THRESHOLD), 17)
        events.clear()
        self.assertEqual(run(owner, 17, 8), 17)
        self.assertEqual(events, [17] * 8)

    def warm_attribute_call(self, expression, slots):
        self.enterContext(mock.patch.dict(os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        namespace = {}
        layout = "    __slots__ = ('value',)\n" if slots else ""
        exec("class Holder:\n" + layout +
             "    def method(self, other):\n"
             f"        return {expression}\n"
             "def run(left, right, n):\n"
             "    result = None\n"
             "    for _ in range(n):\n"
             "        result = left.method(right)\n"
             "    return result\n", namespace)
        cls = namespace["Holder"]
        left, right = cls(), cls()
        left.value, right.value = 17, 31
        run = namespace["run"]
        run(left, right, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE")
        before = ex.get_region_stats()["call_attr_entries"]
        run(left, right, 8)
        self.assertGreater(ex.get_region_stats()["call_attr_entries"], before)
        return run, ex, left, right

    @requires_call_regions
    def test_attribute_call_argument_counts(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        for slots in (False, True):
            for bound in (False, True):
                for count in range(0 if bound else 1, 5):
                    names = [f"p{i}" for i in range(count)]
                    owner = names[-1] if names else "self"
                    other = "self" if bound else names[0]
                    expressions = (f"{owner}.value",
                                   f"{owner}.value is None",
                                   f"{owner}.value is not None",
                                   f"{owner}.value < {other}.value")
                    for mode, expression in enumerate(expressions):
                        with self.subTest(slots=slots, bound=bound,
                                          count=count, mode=mode):
                            namespace = {}
                            layout = "    __slots__ = ('value',)\n" if slots else ""
                            if bound:
                                signature = ", ".join(["self"] + names)
                                body = (f"    def leaf({signature}):\n"
                                        f"        return {expression}\n")
                            else:
                                signature = ", ".join(names)
                                body = (f"def leaf({signature}):\n"
                                        f"    return {expression}\n")
                            exec("class Holder:\n" + layout + "    pass\n" + body,
                                 namespace)
                            cls = namespace["Holder"]
                            obj = cls()
                            obj.value = 31
                            values = [cls() for _ in names]
                            for index, value in enumerate(values):
                                value.value = index + 1
                            leaf = obj.leaf if bound else namespace["leaf"]
                            args = ", ".join(f"values[{i}]" for i in range(count))
                            callable_name = "obj.leaf" if bound else "leaf"
                            exec("def run(obj, leaf, values, n):\n"
                                 "    result = None\n"
                                 "    for _ in range(n):\n"
                                 f"        result = {callable_name}({args})\n"
                                 "    return result\n", namespace)
                            run = namespace["run"]
                            expected = leaf(*values)
                            self.assertIs(run(obj, leaf, values, TIER2_THRESHOLD),
                                          expected)
                            ex = self.executor(run, "_CALL_PY_ATTRIBUTE")
                            self.assertIn(f"_CALL_PY_ATTRIBUTE_{count}",
                                          get_opnames(ex))
                            self.assertIs(self.executed(ex, "call_attr_entries", run,
                                                       obj, leaf, values, 8), expected)

    @requires_call_regions
    def test_attribute_call_getters(self):
        for slots in (False, True):
            for expression, expected in (("self.value", lambda x: x),
                                         ("self.value is None", lambda x: x is None),
                                         ("self.value is not None", lambda x: x is not None)):
                with self.subTest(slots=slots, expression=expression):
                    run, ex, left, right = self.warm_attribute_call(expression, slots)
                    for value in (None, object(), 2**100, 1.25):
                        left.value = value
                        result = run(left, right, 8)
                        self.assertIs(result, expected(value))
                    del left.value
                    try:
                        run(left, right, 8)
                    except AttributeError as error:
                        tb = error.__traceback__
                        while tb.tb_next is not None:
                            tb = tb.tb_next
                        self.assertIs(tb.tb_frame.f_code, type(left).method.__code__)
                    else:
                        self.fail("missing attribute did not raise")

    @requires_call_regions
    def test_attribute_call_comparisons(self):
        for slots in (False, True):
            for symbol, operation in (("<", operator.lt), ("<=", operator.le),
                                       ("==", operator.eq), ("!=", operator.ne),
                                       (">", operator.gt), (">=", operator.ge)):
                with self.subTest(slots=slots, symbol=symbol):
                    run, ex, left, right = self.warm_attribute_call(
                        f"self.value {symbol} other.value", slots)
                    for a, b in ((-31, 17), (17, 17), (31, -17),
                                 (True, False), (2**100, 2**100 + 1)):
                        left.value, right.value = a, b
                        self.assertIs(run(left, right, 8), operation(a, b))

    @requires_call_regions
    def test_attribute_call_descriptor_and_dispatch(self):
        run, ex, left, right = self.warm_attribute_call("self.value", False)
        calls = []
        def getter(owner):
            self.assertIs(sys._getframe(1).f_code, type(left).method.__code__)
            calls.append(owner)
            return "descriptor"
        type(left).value = property(getter)
        self.assertEqual(run(left, right, 8), "descriptor")
        self.assertEqual(calls, [left] * 8)

        run, ex, left, right = self.warm_attribute_call("self.value < other.value", True)
        marker = object()
        class Number(int):
            def __lt__(self, other):
                calls.append(other)
                return marker
        calls.clear()
        left.value = Number(17)
        before = ex.get_region_stats()["call_guard_exits"]
        self.assertIs(run(left, right, 8), marker)
        self.assertEqual(calls, [right.value] * 8)
        self.assertGreater(ex.get_region_stats()["call_guard_exits"], before)

    @requires_call_regions
    def test_attribute_call_owned_receiver(self):
        self.enterContext(mock.patch.dict(os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        events = []
        class Payload:
            pass
        class Holder:
            __slots__ = ("value",)
            def __init__(self):
                self.value = Payload()
            def method(self):
                return self.value
            def __del__(self):
                events.append(sys.getrefcount(self.value))
        def run(n):
            result = None
            for _ in range(n):
                result = Holder().method()
            return result
        run(TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE")
        events.clear()
        before = ex.get_region_stats()["call_attr_entries"]
        result = run(2)
        self.assertIsInstance(result, Payload)
        self.assertEqual(events, [3, 3])
        self.assertGreater(ex.get_region_stats()["call_attr_entries"], before)

    @requires_call_regions
    def test_attribute_call_classmethod(self):
        self.enterContext(mock.patch.dict(os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        class Left:
            __slots__ = ("value",)
        class Right:
            pass
        class Compare:
            @classmethod
            def method(cls, left, right):
                return left.value < right.value
        def run(left, right, n):
            result = None
            for _ in range(n):
                result = Compare.method(left, right)
            return result
        left, right = Left(), Right()
        left.value, right.value = -17, 31
        run(left, right, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_ATTRIBUTE")
        before = ex.get_region_stats()["call_attr_entries"]
        self.assertIs(run(left, right, 8), True)
        self.assertGreater(ex.get_region_stats()["call_attr_entries"], before)

    def warm_range_call(self):
        def make(stop, n):
            result = None
            for _ in range(n):
                result = range(stop)
            return result
        support.reset_code(make)
        self.addCleanup(support.reset_code, make)
        make(17, TIER2_THRESHOLD)
        return make, self.executor(make, "_CALL_RANGE_COMPACT")

    def test_range_compact_constructor(self):
        make, ex = self.warm_range_call()
        for stop in (-10000, -1, 0, 1, 1024, 10000, 2**29 - 1):
            with self.subTest(stop=stop):
                before = ex.get_region_stats()["range_call_entries"]
                result = make(stop, 8)
                self.assertIs(type(result), range)
                self.assertIs(result.stop, stop)
                self.assertEqual(result, range(stop))
                self.assertEqual((result.start, result.step, len(result)), (0, 1, max(stop, 0)))
                self.assertGreater(ex.get_region_stats()["range_call_entries"], before)
        stop = int("10000")
        refs = sys.getrefcount(stop)
        result = make(stop, 8)
        # The range owns stop once; its private length is a distinct int.
        self.assertEqual(sys.getrefcount(stop), refs + 1)
        del result
        self.assertEqual(sys.getrefcount(stop), refs)

    def test_range_constructor_fallback(self):
        make, ex = self.warm_range_call()
        for stop in (True, False, 2**100, -(2**100)):
            before = ex.get_region_stats()["range_call_entries"]
            self.assertEqual(make(stop, 8), range(stop))
            self.assertEqual(ex.get_region_stats()["range_call_entries"], before)
        events = []
        class Index:
            def __index__(self):
                events.append(sys._getframe(1).f_code)
                return 7
        self.assertEqual(make(Index(), 8), range(7))
        self.assertEqual(events, [make.__code__] * 8)
        for stop in (None, 1.5, object()):
            try:
                make(stop, 8)
            except TypeError as error:
                tb = error.__traceback__
                while tb.tb_next:
                    tb = tb.tb_next
                self.assertIs(tb.tb_frame.f_code, make.__code__)
                self.assertEqual(tb.tb_lineno, make.__code__.co_firstlineno + 3)
            else:
                self.fail("invalid range argument did not raise")

    def warm_range_iter(self):
        def take(value, n):
            result = []
            for _ in range(n):
                for item in value:
                    result.append(item)
                    break
            return result
        support.reset_code(take)
        self.addCleanup(support.reset_code, take)
        take(range(7, 10), TIER2_THRESHOLD)
        return take, self.executor(take, "_GET_ITER_RANGE")

    def test_range_compact_iterator(self):
        for value in (range(1), range(7, 20, 3), range(20, -3, -4),
                      range(-10, 100, 7), range(0), range(-10)):
            with self.subTest(value=value):
                take, ex = self.warm_range_iter()
                before = ex.get_region_stats()["range_iter_entries"]
                self.assertEqual(take(value, 8), list(value[:1]) * 8)
                # The empty inner loop can leave this trace before GET_ITER.
                if value:
                    self.assertGreater(ex.get_region_stats()["range_iter_entries"], before)
        for value in (range(2**100), range(2**100, 2**100 + 3),
                      range(0, 2**100, -1), range(0, 1, 2**100)):
            with self.subTest(value=value):
                take, ex = self.warm_range_iter()
                before = ex.get_region_stats()["range_iter_entries"]
                self.assertEqual(take(value, 8), list(value[:1]) * 8)
                self.assertEqual(ex.get_region_stats()["range_iter_entries"], before)

    @unittest.skipUnless(support.Py_DEBUG, "debug allocation probe")
    def test_range_allocation_error(self):
        make, call_ex = self.warm_range_call()
        take, iter_ex = self.warm_range_iter()
        for kind, run, ex, argument, line in (
            ("range_call", make, call_ex, 10000, 3),
            ("range_iter", take, iter_ex, range(7, 10), 3),
        ):
            before = ex.get_region_stats()["allocation_errors"]
            with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": kind}):
                try:
                    run(argument, 8)
                except MemoryError as error:
                    tb = error.__traceback__
                    while tb.tb_next:
                        tb = tb.tb_next
                    self.assertIs(tb.tb_frame.f_code, run.__code__)
                    self.assertEqual(tb.tb_lineno, run.__code__.co_firstlineno + line)
                else:
                    self.fail("range allocation error was lost")
            self.assertGreater(ex.get_region_stats()["allocation_errors"], before)
            run(argument, 8)

    @unittest.skipUnless(support.Py_DEBUG, "debug allocation probe")
    def test_range_allocation_handler_and_cleanup(self):
        def run(stop, n):
            for _ in range(n):
                try:
                    for item in range(stop):
                        break
                except MemoryError as error:
                    return error.__traceback__.tb_lineno
            return None
        stop = int("10000")
        self.assertIsNone(run(stop, TIER2_THRESHOLD))
        self.executor(run, "_CALL_RANGE_COMPACT")
        self.executor(run, "_GET_ITER_RANGE")
        refs = sys.getrefcount(stop)
        for kind in ("range_call", "range_iter"):
            with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": kind}):
                self.assertEqual(run(stop, 8), run.__code__.co_firstlineno + 3)
            self.assertEqual(sys.getrefcount(stop), refs)
        self.assertIsNone(run(stop, 8))

    def test_enumerate_list_and_fallbacks(self):
        def consume(iterator):
            out = []
            for index, item in iterator:
                out.append((index, item))
            return out
        ex = self.warm_enumerate(consume)
        before = ex.get_region_stats()["enum_entries"]
        values = [object() for _ in range(64)]
        self.assertEqual(consume(enumerate(values)), list(zip(range(64), values)))
        self.assertGreater(ex.get_region_stats()["enum_entries"], before)
        for start in (-6, 1020, 2**100):
            self.assertEqual(consume(enumerate(values, start)),
                             list(zip(range(start, start + 64), values)))
        self.assertEqual(consume(enumerate(tuple(values))), list(zip(range(64), values)))
        self.assertEqual(consume(iter([(1, "x"), (2, "y")])), [(1, "x"), (2, "y")])

    def test_enumerate_tuple_alias(self):
        def consume(iterator):
            result = []
            for i, item in iterator:
                result.append((i, item))
            return result
        ex = self.warm_enumerate(consume)
        iterator = enumerate(list(range(64)))
        first = next(iterator)
        before = ex.get_region_stats()
        self.assertEqual(consume(iterator), [(i, i) for i in range(1, 64)])
        self.assertEqual(first, (0, 0))
        after = ex.get_region_stats()
        self.assertEqual(after["enum_entries"], before["enum_entries"])
        self.assertGreater(after["enum_fallbacks"], before["enum_fallbacks"])
        self.assertEqual(after["enum_guard_exits"], before["enum_guard_exits"])

    def test_enumerate_inner_iterator_fallback(self):
        def consume(iterator):
            out = []
            for index, item in iterator:
                out.append((index, item))
            return out
        ex = self.warm_enumerate(consume)
        before = ex.get_region_stats()
        self.assertEqual(consume(enumerate(zip(range(64), range(64)))),
                         [(i, (i, i)) for i in range(64)])
        after = ex.get_region_stats()
        self.assertEqual(after["enum_entries"], before["enum_entries"])
        self.assertGreater(after["enum_fallbacks"], before["enum_fallbacks"])
        self.assertEqual(after["enum_guard_exits"], before["enum_guard_exits"])

    def test_enumerate_inner_iterator_error(self):
        def consume(iterator):
            out = []
            for index, item in iterator:
                out.append((index, item))
            return out
        ex = self.warm_enumerate(consume)
        class Inner:
            def __init__(self, error):
                self.index = 0
                self.error = error
            def __iter__(self):
                return self
            def __next__(self):
                self.index += 1
                if self.index == 5:
                    raise self.error("inner failure")
                return self.index
        before = ex.get_region_stats()["enum_fallbacks"]
        self.assertEqual(consume(enumerate(Inner(StopIteration))), list(enumerate(range(1, 5))))
        try:
            consume(enumerate(Inner(ValueError)))
        except ValueError as error:
            self.assertEqual(str(error), "inner failure")
            frames = []
            tb = error.__traceback__
            while tb is not None:
                frames.append((tb.tb_frame.f_code, tb.tb_lineno))
                tb = tb.tb_next
            self.assertIn((consume.__code__, consume.__code__.co_firstlineno + 2), frames)
            self.assertIs(frames[-1][0], Inner.__next__.__code__)
        else:
            self.fail("iterator error was lost")
        self.assertGreater(ex.get_region_stats()["enum_fallbacks"], before)

    def test_enumerate_tuple_hash(self):
        def consume(iterator):
            result = []
            for pair in iterator:
                result.append(hash(pair))
                del pair
            return result
        ex = self.warm_enumerate(consume)
        before = ex.get_region_stats()["enum_entries"]
        self.assertEqual(consume(enumerate(list(range(64)))),
                         [hash((i, i)) for i in range(64)])
        self.assertGreater(ex.get_region_stats()["enum_entries"], before)

    def test_enumerate_finalizer_reentry(self):
        def consume(iterator, values, events):
            for i, item in iterator:
                events.append(("body", i, type(item).__name__))
                if i == 0:
                    values.pop(0)
                del item
        for _ in range(TIER2_THRESHOLD // 64 + 8):
            values = [None] * 64
            consume(enumerate(values), values, [])
        ex = self.executor(consume, "_ITER_NEXT_ENUM_LIST")
        events = []
        class Victim:
            def __del__(self):
                events.append(("finalizer", next(iterator)))
        values = [Victim(), "skip", "next", "tail"]
        iterator = enumerate(values)
        before = ex.get_region_stats()["enum_entries"]
        consume(iterator, values, events)
        self.assertEqual(events, [("body", 0, "Victim"),
                                  ("finalizer", (2, "tail")),
                                  ("body", 1, "str")])
        self.assertGreater(ex.get_region_stats()["enum_entries"], before)

    def warm_float_range(self, expression, numerator="1.0"):
        self.enterContext(mock.patch.dict(os.environ, {
            "PYTHON_TIER2_BOUNDED_INT_REGIONS": "1",
            "PYTHON_TIER2_FLOAT_RANGE": "1",
        }))
        namespace = {}
        exec(
            "def term(a, j):\n"
            f"    return {numerator} / ({expression})\n"
            "def run(a, start, stop, initial=0.0):\n"
            "    total = initial + 0.0\n"
            "    for j in range(start, stop):\n"
            "        total += term(a, j)\n"
            "    return total, j\n",
            namespace,
        )
        run = namespace["run"]
        for _ in range(TIER2_THRESHOLD // 119 + 8):
            run(31, 1, 120)
        return namespace, self.executor(run, "_FLOAT_RANGE_REDUCE")

    @requires_call_regions
    def test_float_range_polynomials(self):
        for expression in (
            "(a + j) * (a + j + 1) // 2 + a + 1",
            "(a * j + a) + j + 20",
            "(a + a) + a + 1",
            "(a - j) * (a - j) + a + 1",
        ):
            with self.subTest(expression=expression):
                ns, ex = self.warm_float_range(expression)
                run, term = ns["run"], ns["term"]
                for a, start, stop in ((7, 1, 80), (31, 120, 200), (9, -4, 12),
                                        (7, 1, 2), (7, 1, 3), (7, 1, 4)):
                    expected = 0.0
                    for j in range(start, stop):
                        expected = operator.add(expected, term(a, j))
                    before = ex.get_region_stats()
                    result, last = run(a, start, stop)
                    after = ex.get_region_stats()
                    self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                    self.assertEqual(last, stop - 1)
                    # This monotone interval must execute a real chunk.
                    if start == 120:
                        self.assertGreater(after["range_iterations"], before["range_iterations"])

    @requires_call_regions
    def test_float_range_pair_order(self):
        # Adding adjacent terms together first would change these results.
        # Exercise both the final pair and the odd trailing scalar term.
        for numerator, initial in (("1.0", 2.0**53), ("-1.0", -2.0**53)):
            ns, ex = self.warm_float_range("(a + a) + a + 1", numerator)
            for count in (*range(1, 9), 126, 127, 128, 129, 130, 131):
                with self.subTest(numerator=numerator, count=count):
                    expected = initial
                    for _ in range(count):
                        expected = operator.add(expected, float(numerator))
                    before = ex.get_region_stats()
                    result, last = ns["run"](0, 1, count + 1, initial)
                    after = ex.get_region_stats()
                    self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                    self.assertEqual(last, count)
                    if count >= 3:
                        self.assertGreater(after["range_iterations"], before["range_iterations"])
                        self.assertEqual(after["range_guard_exits"], before["range_guard_exits"])

    @requires_call_regions
    def test_float_range_int32_boundaries(self):
        for expression, cases in (
            ("(a * j + a) + j + 20", (
                (2**28 - 4, 1, 8, True), (2**28 - 4, 1, 9, False),
                (-(2**28 - 4), 1, 8, True), (-(2**28 - 4), 1, 9, False),
            )),
            # Twice the first difference exceeds int32 here. Packed
            # recurrence updates must wrap without changing any used value.
            ("((a * j) * 8 + a) + 1", (
                (200_000_000, -1, 2, True), (-200_000_000, -1, 2, True),
            )),
        ):
            ns, ex = self.warm_float_range(expression)
            narrow_available = ex.get_region_stats()["range_int32_iterations"] > 0
            for a, start, stop, narrow in cases:
                with self.subTest(expression=expression, a=a, stop=stop):
                    expected = 0.0
                    for j in range(start, stop):
                        expected = operator.add(expected, ns["term"](a, j))
                    before = ex.get_region_stats()
                    result, last = ns["run"](a, start, stop)
                    after = ex.get_region_stats()
                    self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                    self.assertEqual(last, stop - 1)
                    self.assertGreater(after["range_iterations"], before["range_iterations"])
                    if narrow and narrow_available:
                        self.assertGreater(after["range_int32_iterations"], before["range_int32_iterations"])
                    else:
                        self.assertEqual(after["range_int32_iterations"], before["range_int32_iterations"])
                    self.assertEqual(after["range_guard_exits"], before["range_guard_exits"])

    @requires_call_regions
    def test_float_range_scalar_coefficients(self):
        ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        names = [uop[0] for uop in ex]
        self.assertTrue(any(name.startswith("_POLY_STORE") for name in names), names)
        self.assertFalse(any(name.startswith("_POLY_BINARY") for name in names), names)
        self.assertIn("_FLOAT_RANGE_PREPARE_1", names)
        for a in (-100, -1, 0, 1, 100, 2**28 - 1):
            expected = 0.0
            for j in range(120, 200):
                expected = operator.add(expected, ns["term"](a, j))
            result, last = ns["run"](a, 120, 200)
            self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
            self.assertEqual(last, 199)

    @requires_call_regions
    def test_float_range_scalar_divisibility(self):
        # A nonconstant coefficient requires a runtime divisibility check.
        # Even multiplication by zero must not discard that required check.
        for divisor in (3, 4):
            for suffix in ("+ a + 1", "* 0 + a + 1"):
                with self.subTest(divisor=divisor, suffix=suffix):
                    ns, ex = self.warm_float_range(f"((a * j + 1) // {divisor}) {suffix}")
                    names = [uop[0] for uop in ex]
                    self.assertTrue(any(name.startswith("_POLY_STORE") for name in names), names)
                    for a in (divisor * 10, divisor * 10 + 1):
                        expected = 0.0
                        for j in range(1, 120):
                            expected = operator.add(expected, ns["term"](a, j))
                        before = ex.get_region_stats()
                        result, last = ns["run"](a, 1, 120)
                        after = ex.get_region_stats()
                        self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                        self.assertEqual(last, 119)
                        if a % divisor:
                            self.assertGreater(after["range_guard_exits"], before["range_guard_exits"])
                            self.assertEqual(after["range_iterations"], before["range_iterations"])
                        else:
                            self.assertGreater(after["range_iterations"], before["range_iterations"])

    @requires_call_regions
    def test_float_range_fallback_and_alias(self):
        for a, start, stop in ((2**29, 1, 80), (2**28 - 1, 1, 80),
                               (31, 1018, 1040), (31, -10, 80)):
            ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
            run, term = ns["run"], ns["term"]
            expected = 0.0
            for j in range(start, stop):
                expected = operator.add(expected, term(a, j))
            before = ex.get_region_stats()
            result, last = run(a, start, stop)
            self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
            self.assertEqual(last, stop - 1)
            self.assertGreater(ex.get_region_stats()["range_guard_exits"],
                               before["range_guard_exits"])
        initial = float("1.23456789012345")
        original = struct.pack("d", initial)
        result, last = run(31, 1, 120, initial)
        self.assertEqual(struct.pack("d", initial), original)
        self.assertGreater(result, initial)
        self.assertEqual(last, 119)

    @requires_call_regions
    def test_float_range_fractional_coefficients(self):
        for divisor in (3, 4):
            with self.subTest(divisor=divisor):
                ns, ex = self.warm_float_range(
                    f"(a + j) * (a + j + 1) // {divisor} + a + 1")
                before = ex.get_region_stats()
                expected = 0.0
                for j in range(1, 120):
                    expected = operator.add(expected, ns["term"](31, j))
                result, last = ns["run"](31, 1, 120)
                self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                self.assertEqual(last, 119)
                after = ex.get_region_stats()
                self.assertGreater(after["range_guard_exits"], before["range_guard_exits"])
                self.assertEqual(after["range_iterations"], before["range_iterations"])

    @requires_call_regions
    def test_float_range_negative_coefficients(self):
        ns, ex = self.warm_float_range("(a - j) * (j - a + 1) // 2 + a + 1")
        expected = 0.0
        for j in range(120, 200):
            expected = operator.add(expected, ns["term"](31, j))
        before = ex.get_region_stats()["range_iterations"]
        result, last = ns["run"](31, 120, 200)
        self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
        self.assertEqual(last, 199)
        self.assertGreater(ex.get_region_stats()["range_iterations"], before)

    @requires_call_regions
    def test_float_range_zero_and_subclass(self):
        ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        before = ex.get_region_stats()["range_guard_exits"]
        try:
            ns["run"](-1, -5, 12)
        except ZeroDivisionError as error:
            self.assertEqual(str(error), "division by zero")
            tb = error.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            self.assertIs(tb.tb_frame.f_code, ns["term"].__code__)
            self.assertEqual(tb.tb_lineno, 2)
            self.assertEqual(tb.tb_frame.f_locals["j"], 0)
        else:
            self.fail("division by zero was skipped")
        self.assertGreater(ex.get_region_stats()["range_guard_exits"], before)

        ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        calls = []
        class Number(int):
            def __add__(self, other):
                calls.append(other)
                return int(self) + other
        before = ex.get_region_stats()["range_guard_exits"]
        ns["run"](Number(31), 1, 80)
        self.assertEqual(calls, [item for j in range(1, 80) for item in (j, j)])
        self.assertGreater(ex.get_region_stats()["range_guard_exits"], before)

    @requires_call_regions
    def test_float_range_nan_payload(self):
        for numerator in ("1.0", "(1e309 - 1e309)"):
            ns, ex = self.warm_float_range(
                "(a + j) * (a + j + 1) // 2 + a + 1", numerator)
            # Compare the same warmed bytecode with the feature disabled.
            # The existing debug Tier 2 float-add path can select a different
            # NaN payload from operator.add, independently of this region.
            controls = []
            with mock.patch.dict(os.environ, {"PYTHON_TIER2_FLOAT_RANGE": "0"}):
                control = types.FunctionType(ns["run"].__code__.replace(), ns,
                                             argdefs=ns["run"].__defaults__)
                for _ in range(TIER2_THRESHOLD // 119 + 8):
                    control(31, 1, 120)
                for payload in ("7ff8000000000011", "fff8000000000022", "7ff0000000000033"):
                    initial = struct.unpack(">d", bytes.fromhex(payload))[0]
                    expected, _ = control(31, 120, 200, initial)
                    controls.append((payload, initial, expected))
            for payload, initial, expected in controls:
                with self.subTest(numerator=numerator, payload=payload):
                    before = ex.get_region_stats()
                    result, last = ns["run"](31, 120, 200, initial)
                    after = ex.get_region_stats()
                    self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
                    self.assertEqual(last, 199)
                    self.assertGreater(after["range_guard_exits"], before["range_guard_exits"])
                    self.assertEqual(after["range_iterations"], before["range_iterations"])

    @requires_call_regions
    def test_float_range_last_term_error(self):
        ns, ex = self.warm_float_range("(a - j) + a + 200")
        before = ex.get_region_stats()["range_guard_exits"]
        expected = 0.0
        for j in range(120, 200):
            expected = operator.add(expected, ns["term"](0, j))
        try:
            ns["run"](0, 120, 201)
        except ZeroDivisionError as error:
            tb = error.__traceback__
            while tb.tb_next is not None:
                if tb.tb_frame.f_code is ns["run"].__code__:
                    self.assertEqual(tb.tb_frame.f_locals["j"], 200)
                    self.assertEqual(struct.pack("d", tb.tb_frame.f_locals["total"]),
                                     struct.pack("d", expected))
                tb = tb.tb_next
            self.assertIs(tb.tb_frame.f_code, ns["term"].__code__)
            self.assertEqual(tb.tb_frame.f_locals["j"], 200)
        else:
            self.fail("last denominator is zero")
        self.assertGreater(ex.get_region_stats()["range_guard_exits"], before)

    @requires_call_regions
    def test_float_range_iterator_exhaustion(self):
        ns, _ = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        exec("def consume(a, iterator):\n"
             "    total = 0.0\n"
             "    for j in iterator:\n"
             "        total += term(a, j)\n"
             "    return total, j\n", ns)
        consume = ns["consume"]
        for _ in range(TIER2_THRESHOLD // 119 + 8):
            consume(31, iter(range(1, 120)))
        ex = self.executor(consume, "_FLOAT_RANGE_REDUCE")
        expected = 0.0
        for j in range(120, 200):
            expected = operator.add(expected, ns["term"](31, j))
        iterator = iter(range(120, 200))
        before = ex.get_region_stats()["range_iterations"]
        result, last = consume(31, iterator)
        self.assertEqual(struct.pack("d", result), struct.pack("d", expected))
        self.assertEqual(last, 199)
        self.assertEqual(iterator.__length_hint__(), 0)
        self.assertIs(next(iterator, None), None)
        self.assertEqual(ex.get_region_stats()["range_iterations"] - before, 79)

    @requires_call_regions
    def test_float_range_copied_namespace(self):
        ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        run = ns["run"]
        other = ns.copy()
        def replacement(a, j):
            return 2.0
        other["term"] = replacement
        alias = types.FunctionType(run.__code__, other, argdefs=run.__defaults__)
        before = ex.get_region_stats()["range_iterations"]
        self.assertEqual(alias(31, 1, 80), (158.0, 79))
        self.assertEqual(ex.get_region_stats()["range_iterations"], before)

    @requires_call_regions
    def test_float_range_code_and_monitoring(self):
        ns, ex = self.warm_float_range("(a + j) * (a + j + 1) // 2 + a + 1")
        run, term = ns["run"], ns["term"]
        calls = []
        tool = sys.monitoring.PROFILER_ID
        sys.monitoring.use_tool_id(tool, "float range test")
        try:
            sys.monitoring.register_callback(tool, sys.monitoring.events.PY_START,
                                            lambda code, offset: calls.append(code))
            sys.monitoring.set_local_events(tool, term.__code__, sys.monitoring.events.PY_START)
            run(31, 1, 80)
            self.assertEqual(calls.count(term.__code__), 79)
        finally:
            sys.monitoring.set_events(tool, 0)
            sys.monitoring.set_local_events(tool, term.__code__, 0)
            sys.monitoring.register_callback(tool, sys.monitoring.events.PY_START, None)
            sys.monitoring.free_tool_id(tool)
        def replacement(a, j):
            return 2.0
        term.__code__ = replacement.__code__
        self.assertEqual(run(31, 1, 80), (158.0, 79))

    def warm_bounded(self, expression, limit=1000):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_BOUNDED_INT_REGIONS": "1"}))
        func = arithmetic(expression)
        func(31, 17, 9, limit, TIER2_THRESHOLD)
        return func, self.executor(func, "_INT_REGION_START")

    def test_bounded_expression_trees(self):
        expressions = [
            ("(a + b) * (c + 1)",
             lambda a, b, c: operator.mul(operator.add(a, b), operator.add(c, 1))),
            ("(a - b) * (c + 1) + a",
             lambda a, b, c: operator.add(operator.mul(operator.sub(a, b),
                                                      operator.add(c, 1)), a)),
            ("(a + b) * (a + b + 1) // 2 + a + 1",
             lambda a, b, c: operator.add(operator.add(operator.floordiv(
                 operator.mul(operator.add(a, b), operator.add(operator.add(a, b), 1)),
                 2), a), 1)),
            ("((a + b) * (c + 1)) // 3",
             lambda a, b, c: operator.floordiv(
                 operator.mul(operator.add(a, b), operator.add(c, 1)), 3)),
            ("(a - b) * (a - b + 1)",
             lambda a, b, c: operator.mul(operator.sub(a, b),
                                          operator.add(operator.sub(a, b), 1))),
            ("(a * b) + (a * b + 1)",
             lambda a, b, c: operator.add(operator.mul(a, b),
                                          operator.add(operator.mul(a, b), 1))),
        ]
        rng = random.Random(271828)
        bound = 2**28 - 1
        cases = [(a, b, c) for a in (-bound, -1, 0, 1, bound)
                 for b in (-bound, -1, 0, 1, bound)
                 for c in (-bound, 0, bound)]
        cases += [tuple(rng.randrange(-bound, bound + 1) for _ in range(3))
                  for _ in range(100)]
        for expression, oracle in expressions:
            with self.subTest(expression=expression):
                func, ex = self.warm_bounded(expression)
                if expression.startswith(("(a - b) * (a - b", "(a * b) + (a * b")):
                    self.executor(func, "_INT_REGION_DUP")
                for a, b, c in cases:
                    before = ex.get_region_stats()
                    value = self.executed(ex, "bounded_entries", func,
                                          a, b, c, 0, 8)
                    self.assertEqual(value, oracle(a, b, c))
                    after = ex.get_region_stats()
                    self.assertEqual(after["bounded_boxes"] - before["bounded_boxes"],
                                     after["bounded_entries"] - before["bounded_entries"])

    def test_bounded_guards_and_callbacks(self):
        events = []

        class Number(int):
            def __add__(self, other):
                events.append(("add", int(self), other))
                return int(self) + other

        for args in [(2**28, 1, 2), (-2**28, 1, 2), (1, 2**50, 3),
                     (1, 2, 2**50), (True, 2, 3), (1, 2, True),
                     (Number(11), 2, 3), (1, 2, Number(11))]:
            with self.subTest(args=args):
                func, ex = self.warm_bounded("(a + b) * (c + 1)")
                events.clear()
                actual = self.executed(ex, "bounded_guard_exits", func,
                                       *args, 0, 8)
                recorded = events.copy()
                events.clear()
                a, b, c = args
                expected = (a + b) * (c + 1)
                self.assertEqual(actual, expected)
                self.assertEqual(recorded, events * 8)
                self.assertEqual(func(31, 17, 9, 0, 32), 480)

    def test_bounded_four_additional_locals(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_BOUNDED_INT_REGIONS": "1"}))

        def run(f, d, b, e, c, a, n):
            for _ in range(n):
                result = (a + b) * (c + d) + (e + f)
            return result

        support.reset_code(run)
        self.addCleanup(support.reset_code, run)
        self.assertEqual(run(17, 11, 5, 13, 7, 3, TIER2_THRESHOLD), 174)
        ex = self.executor(run, "_INT_REGION_START_4")
        self.assertEqual(self.executed(ex, "bounded_entries", run,
                                       17, 11, 5, 13, 7, 3, 8), 174)
        self.assertEqual(self.executed(ex, "bounded_guard_exits", run,
                                       2**50, 11, 5, 13, 7, 3, 8), 2**50 + 157)

    def test_bounded_float_division(self):
        func, ex = self.warm_bounded("limit / ((a + b) * (c + 1))", limit=1.0)
        self.executor(func, "_INT_REGION_DIVIDE")
        cases = [(31, 17, 9), (-31, 17, 9), (31, 17, -9),
                 (2**27 + 1, 0, 2**27), (2**27 + 1, 2, 2**27),
                 (-2**27 - 1, 0, 2**27)]
        for a, b, c in cases:
            denominator = operator.mul(operator.add(a, b), operator.add(c, 1))
            for numerator in (1.0, -1.0, 0.0, -0.0, 1e308, 5e-324,
                              math.inf, -math.inf, math.nan, -math.nan):
                expected = operator.truediv(numerator, denominator)
                actual = self.executed(ex, "bounded_entries", func,
                                       a, b, c, numerator, 8)
                self.assertEqual(struct.pack("d", actual), struct.pack("d", expected))
        before = ex.get_region_stats()
        self.assertEqual(self.executed(ex, "bounded_divisions", func,
                                       31, 17, 9, 1.0, 8), 1.0 / 480)
        self.assertEqual(before["bounded_boxes"], ex.get_region_stats()["bounded_boxes"])
        with self.assertRaisesRegex(ZeroDivisionError, "division by zero"):
            func(1, -1, 9, 1.0, 8)
        self.assertEqual(func(31, 17, 9, 1.0, 8), 1.0 / 480)

        def zero(n, offset):
            for index in range(n):
                result = 1.0 / ((index + offset) * (index + 1))
            return result

        support.reset_code(zero)
        self.addCleanup(support.reset_code, zero)
        zero(TIER2_THRESHOLD, 1)
        ex = self.executor(zero, "_INT_REGION_DIVIDE")
        before = ex.get_region_stats()
        # First iteration succeeds in tier 1; the second raises in the JIT.
        with self.assertRaisesRegex(ZeroDivisionError, "division by zero"):
            zero(8, -1)
        after = ex.get_region_stats()
        self.assertGreater(after["bounded_entries"], before["bounded_entries"])
        self.assertEqual(after["bounded_guard_exits"], before["bounded_guard_exits"])

    def test_bounded_float_numerator_fallback(self):
        events = []

        class Number(float):
            def __truediv__(self, other):
                events.append(other)
                return ("division", other)

        for numerator in (1, True, Number(1.0)):
            func, ex = self.warm_bounded("limit / ((a + b) * (c + 1))", limit=1.0)
            events.clear()
            actual = self.executed(ex, "bounded_guard_exits", func,
                                   31, 17, 9, numerator, 8)
            self.assertEqual(actual, operator.truediv(numerator, 480))
            if isinstance(numerator, Number):
                self.assertEqual(events, [480] * 9)
        func, ex = self.warm_bounded("(limit + 0.5) / ((a + b) * (c + 1))", limit=1.0)
        self.assertEqual(self.executed(ex, "bounded_guard_exits", func,
                                       31, 17, 9, 1.0, 8), 1.5 / 480)

    def test_bounded_zero_division_and_unsafe_interval(self):
        # The unsafe division is after a materialized region. It must retain
        # its normal error edge, with no tagged values exposed to unwinding.
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_BOUNDED_INT_REGIONS": "1"}))
        func = arithmetic("((a + b) * (c + 1)) // limit")
        func(31, 17, 9, 3, TIER2_THRESHOLD)
        ex = self.executor(func, "_INT_REGION_START")
        with self.assertRaisesRegex(ZeroDivisionError, "division by zero"):
            func(31, 17, 9, 0, 8)
        self.assertEqual(self.executed(ex, "bounded_entries", func,
                                       31, 17, 9, 3, 8), 160)
        unsafe = arithmetic("a * b * c + 1")
        unsafe(31, 17, 9, 0, TIER2_THRESHOLD)
        self.assertFalse(any(name.startswith("_INT_REGION_START")
                             for ex in get_all_executors(unsafe)
                             for name in get_opnames(ex)))
        self.assertEqual(unsafe(2**28 - 1, 2**28 - 1, 2**28 - 1, 0, 8),
                         (2**28 - 1)**3 + 1)

    @unittest.skipUnless(support.Py_DEBUG, "debug allocation probe")
    def test_bounded_allocation_error_in_frame(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_BOUNDED_INT_REGIONS": "1"}))

        def run(a, b, c, n):
            try:
                for _ in range(n):
                    result = (a + b) * (c + 1)
                return result
            except MemoryError:
                return (a, b, c)

        support.reset_code(run)
        self.addCleanup(support.reset_code, run)
        self.assertEqual(run(31, 17, 9, TIER2_THRESHOLD), 480)
        ex = self.executor(run, "_INT_REGION_START")
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "bounded"}):
            self.assertEqual(self.executed(ex, "allocation_errors", run,
                                           31, 17, 9, 8), (31, 17, 9))
        self.assertEqual(run(31, 17, 9, 8), 480)

    @unittest.skipUnless(support.Py_DEBUG, "debug allocation probe")
    def test_bounded_float_allocation_error_in_frame(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_BOUNDED_INT_REGIONS": "1"}))

        def run(a, b, c, n):
            try:
                for _ in range(n):
                    result = 1.0 / ((a + b) * (c + 1))
                return result
            except MemoryError:
                return (a, b, c)

        support.reset_code(run)
        self.addCleanup(support.reset_code, run)
        self.assertEqual(run(31, 17, 9, TIER2_THRESHOLD), 1.0 / 480)
        ex = self.executor(run, "_INT_REGION_DIVIDE")
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "bounded_float"}):
            self.assertEqual(self.executed(ex, "allocation_errors", run,
                                           31, 17, 9, 8), (31, 17, 9))
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": "bounded_conversion"}):
            self.assertEqual(self.executed(ex, "allocation_errors", run,
                                           2**27 + 1, 0, 2**27, 8),
                             (2**27 + 1, 0, 2**27))
        self.assertEqual(run(31, 17, 9, 8), 1.0 / 480)

    def test_int_expressions_and_comparisons(self):
        rng = random.Random(481516)
        pairs = [("*", operator.mul), ("+", operator.add), ("-", operator.sub)]
        for first, first_op in pairs:
            for second, second_op in pairs:
                with self.subTest(first=first, second=second):
                    func, ex = self.warm_int(f"(a {first} b) {second} c")
                    for _ in range(100):
                        a, b, c = (rng.randrange(-100000, 100000) for _ in range(3))
                        expected = second_op(first_op(a, b), c)
                        actual = self.executed(ex, "int_entries", func, a, b, c, 0, 8)
                        self.assertEqual(actual, expected)
        for comparison, compare in [("<", operator.lt), ("<=", operator.le),
                                    ("==", operator.eq), ("!=", operator.ne),
                                    (">", operator.gt), (">=", operator.ge)]:
            with self.subTest(comparison=comparison):
                func, ex = self.warm_int(f"a * b + c {comparison} limit", True)
                for limit in (535, 536, 537, 2**40):
                    actual = self.executed(ex, "int_entries", func, 31, 17, 9, limit, 8)
                    self.assertIs(actual, compare(536, limit))
                self.assertEqual(ex.get_region_stats()["int_boxes"], 0)

    def test_int_i64_boundaries_and_fallback(self):
        cases = [
            (2**63 - 1, 1, 0, None),
            (-2**63, 1, 0, None),
            (2**40, -3, 2**42, None),
            (0, -2**63, -2**63, None),
            (2**62, 4, -1, "int_overflow_exits"),
            (2**63 - 1, 1, 1, "int_overflow_exits"),
            (-2**63, -1, 0, "int_overflow_exits"),
            (2**80, 0, 1, "int_guard_exits"),
            (True, 3, 4, "int_guard_exits"),
        ]
        for a, b, c, exit_counter in cases:
            with self.subTest(a=a, b=b, c=c):
                func, ex = self.warm_int("a * b + c")
                actual = self.executed(ex, exit_counter or "int_entries",
                                       func, a, b, c, 0, 8)
                self.assertEqual(actual, operator.add(operator.mul(a, b), c))
                self.assertEqual(func(31, 17, 9, 0, 32), 536)
        # Subtraction underflows only after the first operation succeeds.
        func, ex = self.warm_int("a + b - c")
        self.assertEqual(self.executed(ex, "int_overflow_exits", func,
                                       -2**63, 0, 1, 0, 8), -2**63 - 1)

    def test_int_subclass_order_and_alias(self):
        events = []

        class Number(int):
            def __mul__(self, other):
                events.append("mul")
                return Number(int(self) * int(other))

            def __add__(self, other):
                events.append("add")
                return Number(int(self) + int(other))

        func, ex = self.warm_int("a * b + c")
        value = Number(11)
        actual = self.executed(ex, "int_guard_exits", func, value, value, value, 0, 8)
        self.assertIs(type(actual), Number)
        self.assertEqual(events, ["mul", "add"] * 8)
        self.assertEqual(value, 11)
        self.assertEqual(func(11, 11, 11, 0, 32), 132)

    def test_int_inlined_functions_and_local_order(self):
        def offset(header, index, width):
            return index * width + header

        def fits(limit, a, b, c):
            return a * b + c < limit

        def run(n):
            result = None
            for _ in range(n):
                result = offset(917, 331, 173), fits(60000, 331, 173, 917)
            return result

        support.reset_code(run)
        self.addCleanup(support.reset_code, run)
        self.assertEqual(run(TIER2_THRESHOLD), (58180, True))
        ex = self.executor(run, "_INT_REGION")
        self.executor(run, "_INT_REGION_COMPARE")
        self.assertEqual(self.executed(ex, "int_entries", run, 8), (58180, True))

    def test_int_region_stops_at_call(self):
        events = []

        def observe(value):
            events.append(value)
            return value

        func = arithmetic("a * b + observe(c)")
        func.__globals__["observe"] = observe
        self.assertEqual(func(31, 17, 9, 0, TIER2_THRESHOLD), 536)
        self.assertFalse(any(name.startswith("_INT_REGION")
                             for ex in get_all_executors(func)
                             for name in get_opnames(ex)))
        events.clear()
        self.assertEqual(func(31, 17, 9, 0, 8), 536)
        self.assertEqual(events, [9] * 8)

    def test_len_consumers(self):
        for expression in ("len(a) >= b", "len(a) - b", "len(a) + b"):
            for value in ("x" * 400, b"x" * 400, tuple(range(400)),
                          list(range(400)), dict.fromkeys(range(400))):
                with self.subTest(expression=expression, receiver=type(value)):
                    func = arithmetic(expression)
                    func(value, 10, 0, 0, TIER2_THRESHOLD)
                    ex = self.executor(func, "_CALL_LEN_CONSUMER")
                    for right in (-2**40, 0, 399, 400, 401, 2**40):
                        actual = self.executed(ex, "len_entries", func,
                                               value, right, 0, 0, 8)
                        expected = eval(expression, {"a": value, "b": right})
                        self.assertEqual(actual, expected)

    def test_len_constant_consumers(self):
        for expression, oracle in (
            ("len(a) - 1", lambda a: operator.sub(len(a), 1)),
            ("len(a) + 7", lambda a: operator.add(len(a), 7)),
            ("len(a) == 1", lambda a: operator.eq(len(a), 1)),
            ("len(a) >= 16", lambda a: operator.ge(len(a), 16)),
        ):
            for make in (list, tuple, dict.fromkeys):
                with self.subTest(expression=expression, make=make):
                    func = arithmetic(expression)
                    func(make(range(400)), 0, 0, 0, TIER2_THRESHOLD)
                    ex = self.executor(func, "_CALL_LEN_CONSUMER")
                    for size in (0, 1, 2, 15, 16, 17, 400):
                        value = make(range(size))
                        actual = self.executed(ex, "len_entries", func,
                                               value, 0, 0, 0, 8)
                        self.assertEqual(actual, oracle(value))

    def test_len_mutation_and_owned_alias(self):
        class Holder:
            def __init__(self, value):
                self.value = value

        for value in ([1, 2, 3], dict.fromkeys(range(3))):
            # Attribute loads produce owned refs; Holder retains the receiver.
            func = arithmetic("len(a.value) - 1")
            holder = Holder(value)
            func(holder, 0, 0, 0, TIER2_THRESHOLD)
            ex = self.executor(func, "_CALL_LEN_CONSUMER")
            self.assertEqual(self.executed(ex, "len_entries", func,
                                           holder, 0, 0, 0, 8), 2)
            value.clear()
            self.assertEqual(self.executed(ex, "len_entries", func,
                                           holder, 0, 0, 0, 8), -1)

        def run(a, n):
            total = 0
            for i in range(n):
                total += len(a) - 1
                a.append(i)
            return total

        self.assertEqual(run([], TIER2_THRESHOLD),
                         TIER2_THRESHOLD * (TIER2_THRESHOLD - 3) // 2)
        ex = self.executor(run, "_CALL_LEN_CONSUMER")
        self.assertEqual(self.executed(ex, "len_entries", run, [], 8), 20)

    def test_len_left_comparison(self):
        for operator_text, compare in (("<", operator.lt), ("<=", operator.le),
                                       ("==", operator.eq), ("!=", operator.ne),
                                       (">", operator.gt), (">=", operator.ge)):
            for suffix, adjust in (("", 0), (" - 1", -1), (" + 7", 7)):
                expression = f"b {operator_text} len(a){suffix}"
                with self.subTest(expression=expression):
                    func = arithmetic(expression)
                    func([0] * 400, 10, 0, 0, TIER2_THRESHOLD)
                    ex = self.executor(func, "_CALL_LEN_LEFT_COMPARE")
                    for make in (list, tuple, dict.fromkeys):
                        for size in (0, 1, 400):
                            value = make(range(size))
                            for left in (-2**63, -1, 0, size + adjust,
                                         size + adjust + 1, 2**63 - 1):
                                actual = self.executed(ex, "len_entries", func,
                                                       value, left, 0, 0, 8)
                                self.assertIs(actual, compare(left, size + adjust))

    def test_len_left_comparison_fallback(self):
        events = []

        class Number(int):
            def __lt__(self, other):
                events.append(("compare", other))
                return False

        class Sized(list):
            def __len__(self):
                events.append("len")
                return 11

        func = arithmetic("b < len(a) - 1")
        func([0] * 400, 10, 0, 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_CALL_LEN_LEFT_COMPARE")
        self.assertFalse(self.executed(ex, "len_guard_exits", func,
                                       Sized(), Number(1), 0, 0, 8))
        self.assertEqual(events, ["len", ("compare", 10)] * 8)
        for left in (True, 2**100, -2**100):
            self.assertEqual(self.executed(ex, "len_guard_exits", func,
                                           [1, 2, 3], left, 0, 0, 8),
                             operator.lt(left, 2))

        func.__globals__["len"] = lambda value: 1
        self.assertFalse(func([0] * 400, 10, 0, 0, 8))

    def test_len_left_comparison_mutation(self):
        def run(a, n):
            matches = 0
            for i in range(n):
                matches += i == len(a) - 1
                a.append(i)
            return matches

        self.assertEqual(run([None], TIER2_THRESHOLD), TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_LEN_LEFT_COMPARE")
        self.assertEqual(self.executed(ex, "len_entries", run, [None], 8), 8)
        self.assertEqual(self.executed(ex, "len_entries", run, [], 8), 0)

    def test_len_override_and_user_receiver(self):
        events = []

        class Sized:
            def __len__(self):
                events.append("len")
                return 12

        class Text(str):
            def __len__(self):
                events.append("subclass")
                return 12

        for value, event in ((Sized(), "len"), (Text("x"), "subclass")):
            func = arithmetic("len(a) - b")
            func("x" * 400, 3, 0, 0, TIER2_THRESHOLD)
            ex = self.executor(func, "_CALL_LEN_CONSUMER")
            events.clear()
            self.assertEqual(self.executed(ex, "len_guard_exits", func,
                                           value, 3, 0, 0, 8), 9)
            self.assertEqual(events, [event] * 8)
        func = arithmetic("len(a) >= b")
        func("abc", 2, 0, 0, TIER2_THRESHOLD)
        self.executor(func, "_CALL_LEN_CONSUMER")
        func.__globals__["len"] = lambda value: 0
        self.assertIs(func("abc", 2, 0, 0, 8), False)

        func = arithmetic("len(a) >= b")
        func("abc", 2, 0, 0, TIER2_THRESHOLD)
        self.executor(func, "_CALL_LEN_CONSUMER")
        original = builtins.len
        try:
            builtins.len = lambda value: 0
            result = func("abc", 2, 0, 0, 8)
        finally:
            builtins.len = original
        self.assertIs(result, False)

    def test_len_owned_receiver_finalizer_and_mutation(self):
        # A freshly concatenated string exercises the owned-reference exit
        # without an exposed frame preventing executor entry beforehand.
        func = arithmetic("len(a + a) - b")
        func("x" * 200, 10, 0, 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_CALL_LEN_CONSUMER")
        self.assertEqual(self.executed(ex, "len_guard_exits", func,
                                       "x" * 200, 10, 0, 0, 8), 390)

        events = []
        frames = []

        class Finalizer:
            def __init__(self, frame):
                self.frame = frame

            def __del__(self):
                events.append("close")
                self.frame.f_locals["position"] = 100

        def temporary():
            return (Finalizer(frames[0]),) * 400

        def run(n):
            frames[:] = [sys._getframe()]
            result = 0
            for _ in range(n):
                position = 10
                result = len(temporary()) - position
            return result

        self.assertEqual(run(TIER2_THRESHOLD), 300)
        events.clear()
        # The exposed frame can deopt before CALL_LEN_CONSUMER. This checks
        # observable ordering; the counter assertion above checks the exit.
        self.assertEqual(run(8), 300)
        self.assertEqual(events, ["close"] * 8)

        func = arithmetic("len(a) - b")
        func("abc", 2, 0, 0, TIER2_THRESHOLD)
        self.executor(func, "_CALL_LEN_CONSUMER")
        value = [1, 2, 3]
        self.assertEqual(func(value, 1, 0, 0, 8), 2)
        value.append(4)
        self.assertEqual(func(value, 1, 0, 0, 8), 3)

    def pair_append_function(self, condition="i < len(word) - 1", matched="merge",
                             extra="", increment=1):
        ns = {"__builtins__": vars(builtins)}
        on_match = ("            output.append(b'merged')\n"
                    "            i += 2\n") if matched == "merge" else "            break\n"
        exec("def run(word, pair, output, start=0):\n"
             "    i = start\n"
             f"    while {condition}:\n"
             "        if (word[i], word[i + 1]) == pair:\n"
             + on_match +
             "        else:\n"
             "            output.append(word[i])\n"
             + (f"            {extra}\n" if extra else "") +
             f"            i += {increment}\n"
             "    if i == len(word) - 1:\n"
             "        output.append(word[i])\n"
             "    return output, i\n", ns)
        return ns["run"]

    def warm_pair_append(self, **kwargs):
        run = self.pair_append_function(**kwargs)
        word = [b"a"] * 96
        for _ in range(TIER2_THRESHOLD // 32 + 32):
            self.assertEqual(run(word, (b"x", b"y"), []), (word, 95))
        return run, self.executor(run, "_LIST_PAIR_APPEND_SCAN")

    def test_pair_append_scan_values_and_boundaries(self):
        run, ex = self.warm_pair_append()
        reference = self.pair_append_function()
        pair = (b"x", b"y")
        for size in (0, 1, 2, 3, 7, 16, 63, 64, 65, 96, 254, 255, 256, 300,
                     1023, 1024, 1025, 1026, 1100):
            for start in (0, 1, -1):
                with self.subTest(size=size, start=start):
                    word = [b"a"] * size
                    if size == 0 and start < 0:
                        continue
                    expected = reference(word, pair, [], start)
                    self.assertEqual(run(word, pair, [], start), expected)
        word = [b"a"] * 96
        for position in (0, 1, 3, 4, 31, 63, 64, 94):
            with self.subTest(position=position):
                data = word.copy()
                data[position:position + 2] = pair
                self.assertEqual(run(data, pair, []), reference(data, pair, []))
        before = ex.get_region_stats()["pair_scan_iterations"]
        self.assertEqual(run(word, pair, []), (word, 95))
        self.assertGreater(ex.get_region_stats()["pair_scan_iterations"], before)

    def test_pair_append_scan_reference_ownership(self):
        run, ex = self.warm_pair_append()
        item = bytes(bytearray(b"non-interned scan item"))
        word = [item] * 96
        before_refs = sys.getrefcount(item)
        before = ex.get_region_stats()["pair_scan_iterations"]
        for _ in range(1000):
            output, index = run(word, (b"x", b"y"), [])
            self.assertEqual(index, 95)
            self.assertTrue(all(value is item for value in output))
            del output
        self.assertGreater(ex.get_region_stats()["pair_scan_iterations"], before)
        self.assertEqual(sys.getrefcount(item), before_refs)

    def test_pair_append_scan_output_alias(self):
        run, ex = self.warm_pair_append(matched="break")
        word = [b"a"] * 8 + [b"x", b"y"]
        before = ex.get_region_stats()["pair_scan_iterations"]
        output, index = run(word, (b"x", b"y"), word)
        self.assertIs(output, word)
        self.assertEqual(index, 8)
        self.assertEqual(word, [b"a"] * 8 + [b"x", b"y"] + [b"a"] * 8)
        self.assertEqual(ex.get_region_stats()["pair_scan_iterations"], before)

    def test_pair_append_scan_callbacks(self):
        run, ex = self.warm_pair_append()
        events = []

        class Bytes(bytes):
            def __eq__(self, other):
                events.append((bytes(self), other))
                return False

        word = [b"a"] * 8 + [Bytes(b"callback")] + [b"a"] * 12
        reference = self.pair_append_function()
        expected = reference(word, (b"x", b"y"), [])
        expected_events = events.copy()
        events.clear()
        self.assertEqual(run(word, (b"x", b"y"), []), expected)
        self.assertEqual(events, expected_events)

        class Output(list):
            def append(self, item):
                events.append(item)
                super().append(item)

        events.clear()
        before = ex.get_region_stats()["pair_scan_iterations"]
        output, index = run([b"a"] * 96, (b"x", b"y"), Output())
        self.assertEqual(output, [b"a"] * 96)
        self.assertEqual(index, 95)
        self.assertEqual(events, output)
        self.assertEqual(ex.get_region_stats()["pair_scan_iterations"], before)

    def test_pair_append_scan_replaced_len(self):
        run, _ = self.warm_pair_append()
        events = []

        def length(word):
            events.append(len(word))
            return min(len(word), 12)

        run.__globals__["len"] = length
        self.assertEqual(run([b"a"] * 96, (b"x", b"y"), []), ([b"a"] * 12, 11))
        # Twelve header evaluations and one final check, each still a call.
        self.assertEqual(events, [96] * 13)
        del run.__globals__["len"]
        self.assertEqual(run([b"a"] * 96, (b"x", b"y"), []), ([b"a"] * 96, 95))
        custom = vars(builtins).copy()
        custom["len"] = length
        copied = types.FunctionType(run.__code__, {"__builtins__": custom},
                                    argdefs=run.__defaults__)
        events.clear()
        self.assertEqual(copied([b"a"] * 96, (b"x", b"y"), []), ([b"a"] * 12, 11))
        self.assertEqual(events, [96] * 13)

    def test_pair_append_scan_general_globals(self):
        run, _ = self.warm_pair_append()
        events = []

        class Collision:
            def __hash__(self):
                return hash("len")

            def __eq__(self, other):
                events.append(other)
                return False

        run.__globals__[Collision()] = None
        # Share the exact globals table and original code bytes, but use a
        # fresh code object without region lowering for the reference run.
        reference = types.FunctionType(run.__code__.replace(), run.__globals__,
                                       argdefs=run.__defaults__)
        with mock.patch.dict(os.environ, {"PYTHON_TIER2_BUILTIN_REGIONS": "0"}):
            expected = reference([b"a"] * 96, (b"x", b"y"), [])
        expected_events = events.copy()
        events.clear()
        self.assertEqual(run([b"a"] * 96, (b"x", b"y"), []), expected)
        self.assertEqual(events, expected_events)
        self.assertTrue(events)

    def test_pair_append_scan_rejects_other_loops(self):
        for options in ({"condition": "i < len(word) - 2"},
                        {"extra": "events.append(i)"}, {"increment": 2}):
            with self.subTest(options=options):
                run = self.pair_append_function(**options)
                run.__globals__["events"] = []
                for _ in range(TIER2_THRESHOLD // 32 + 32):
                    run([b"a"] * 96, (b"x", b"y"), [])
                self.assertFalse(any("_LIST_PAIR_APPEND_SCAN" in get_opnames(ex)
                                     for ex in get_all_executors(run)))

    def test_pair_append_scan_exception_after_progress(self):
        run, ex = self.warm_pair_append()

        class ComparisonError(Exception):
            pass

        class Bytes(bytes):
            def __eq__(self, other):
                raise ComparisonError

        output = []
        word = [b"a"] * 40 + [Bytes(b"callback")] + [b"a"] * 20
        before = ex.get_region_stats()["pair_scan_iterations"]
        try:
            run(word, (b"x", b"y"), output)
        except ComparisonError as error:
            tb = error.__traceback__.tb_next
            self.assertIs(tb.tb_frame.f_code, run.__code__)
            self.assertEqual(tb.tb_frame.f_locals["i"], 40)
            self.assertIs(tb.tb_frame.f_locals["output"], output)
        else:
            self.fail("comparison did not raise")
        self.assertEqual(output, [b"a"] * 40)
        self.assertGreater(ex.get_region_stats()["pair_scan_iterations"], before)

    @support.nomemtest
    def test_pair_append_scan_resize_failure(self):
        from opcode import opmap
        from test.support.import_helper import import_module

        capi = import_module("_testcapi")
        run, ex = self.warm_pair_append()
        word = [b"a"] * 96
        pair = (b"x", b"y")
        output = [b"prefix"] * 8
        del output[5:]  # Keep capacity eight, with three unused slots.
        before = ex.get_region_stats()["pair_scan_iterations"]
        set_nomemory, clear = capi.set_nomemory, capi.remove_mem_hooks
        failure = None
        set_nomemory(0, 1)
        try:
            run(word, pair, output)
        except MemoryError as error:
            clear()
            tb = error.__traceback__.tb_next
            failure = (tb.tb_frame.f_code, tb.tb_lasti, tb.tb_frame.f_locals["i"])
        finally:
            clear()
        self.assertIsNotNone(failure)
        code, offset, index = failure
        self.assertIs(code, run.__code__)
        self.assertEqual(code.co_code[offset], opmap["CALL"])
        self.assertEqual(index, 3)
        self.assertEqual(output, [b"prefix"] * 5 + [b"a"] * 3)
        self.assertGreater(ex.get_region_stats()["pair_scan_iterations"], before)

    def test_pair_append_scan_source_mutation(self):
        run, _ = self.warm_pair_append()
        events = []
        word = [b"a"] * 96

        class Output(list):
            def append(self, item):
                events.append(item)
                word.pop()
                super().append(item)

        output, index = run(word, (b"x", b"y"), Output())
        self.assertEqual(index, 48)
        self.assertEqual(output, [b"a"] * 48)
        self.assertEqual(word, [b"a"] * 48)
        self.assertEqual(events, output)

    def test_pair_append_scan_side_trace(self):
        run, root = self.warm_pair_append()
        word = [b"a"] * 96
        # Make the formerly cold matching branch hot, then revisit a long
        # nonmatching suffix. Follow outgoing links as well as code roots.
        word[:2] = (b"x", b"y")
        for _ in range(TIER2_THRESHOLD):
            self.assertEqual(run(word, (b"x", b"y"), []),
                             ([b"merged"] + word[2:], 95))
        selected = list(get_all_executors(run))
        seen = {id(ex) for ex in selected}
        for ex in selected:
            for child in gc.get_referents(ex):
                if type(child) is type(root) and id(child) not in seen:
                    selected.append(child)
                    seen.add(id(child))
        before = sum(ex.get_region_stats()["pair_scan_iterations"] for ex in selected)
        self.assertEqual(run(word, (b"x", b"y"), []), ([b"merged"] + word[2:], 95))
        after = sum(ex.get_region_stats()["pair_scan_iterations"] for ex in selected)
        self.assertGreater(after, before)

    def warm_list_pair(self, operation="=="):
        ns = {}
        exec("def compare(items, positions, pair, n):\n"
             "    result = None\n"
             "    for k in range(n):\n"
             "        i = positions[k & 1]\n"
             f"        result = (items[i], items[i + 1]) {operation} pair\n"
             "    return result\n", ns)
        compare = ns["compare"]
        compare([b"a", b"b", b"c"], (0, 0), (b"a", b"b"), TIER2_THRESHOLD)
        return compare, self.executor(compare, "_COMPARE_LIST_PAIR")

    def test_list_pair_comparison(self):
        nan = float("nan")
        for operation in ("==", "!="):
            compare, ex = self.warm_list_pair(operation)
            for items in ([b"a", b"b", b"c"], ["α", "β", "γ"],
                          [2**100, -2**100, 0], [nan, 0.0, -0.0]):
                for i in (0, 1, -1, -2, -3):
                    pair = (items[i], items[i + 1])
                    for target in (pair, pair[::-1]):
                        expected = operator.eq(pair, target) if operation == "==" else operator.ne(pair, target)
                        before = ex.get_region_stats()["tuple_list_entries"]
                        self.assertEqual(compare(items, (i, i), target, 2), expected)
                        self.assertGreater(ex.get_region_stats()["tuple_list_entries"], before)
            items = list(range(400))
            self.assertEqual(compare(items, (260, 260), (260, 261), 2), operation == "==")

    def test_list_pair_index_errors(self):
        for bad in (2, 3, -4, 2**100):
            compare, ex = self.warm_list_pair()
            before = ex.get_region_stats()["tuple_guard_exits"]
            # The first elements differ, but the second index must still be
            # evaluated and raise. Iteration zero establishes the entry stack.
            with self.assertRaises(IndexError) as caught:
                compare([b"a", b"b", b"c"], (0, bad), (b"x", b"y"), 2)
            self.assertIn("index", str(caught.exception))
            # Huge indices can leave at the original compact-int guard.
            if abs(bad) < 100:
                self.assertGreater(ex.get_region_stats()["tuple_guard_exits"], before)

    def test_pair_comparison_mixed_immutable_types(self):
        cases = [
            (b"prefix\0suffix", b"second\0value"),
            (b"a" * 1024, b"b" * 1024),
            (b"bytes", "unicode"),
            ("unicode", b"bytes"),
            (b"bytes", 2**100),
            (0.5, b"bytes"),
        ]
        for symbol, operation in (("==", operator.eq), ("!=", operator.ne)):
            direct = arithmetic(f"(a, b) {symbol} c")
            direct(b"a", b"b", (b"a", b"b"), 0, TIER2_THRESHOLD)
            direct_ex = self.executor(direct, "_COMPARE_TUPLE_PAIR")
            indexed, indexed_ex = self.warm_list_pair(symbol)
            for first, second in cases:
                # Equal bytes with separate identities exercise the data
                # comparison, including embedded zeros and long prefixes.
                pair = tuple(bytes(bytearray(value)) if isinstance(value, bytes)
                             else value for value in (first, second))
                for reverse in (False, True):
                    target = pair[::-1] if reverse else pair
                    with self.subTest(symbol=symbol, first=first, second=second,
                                      reversed=reverse):
                        expected = operation((first, second), target)
                        matched_types = type(first) is type(target[0]) and type(second) is type(target[1])
                        counter = "tuple_entries" if matched_types else "tuple_guard_exits"
                        self.assertIs(self.executed(direct_ex, counter, direct,
                                                    first, second, target, 0, 8), expected)
                        self.assertIs(indexed([first, second], (0, 0), target, 8), expected)
                self.assertIs(self.executed(indexed_ex, "tuple_list_entries", indexed,
                                            [first, second], (0, 0), pair, 8),
                              symbol == "==")

    def test_tuple_pair_distinct_large_integers(self):
        compare, ex = self.warm_list_pair()
        direct = arithmetic("(a, b) == c")
        direct(1, 2, (1, 2), 0, TIER2_THRESHOLD)
        direct_ex = self.executor(direct, "_COMPARE_TUPLE_PAIR")
        for a in (2**100, -(2**100), 2**100 + 1, 2**4096, -(2**4096)):
            for b in (a, a - 1, a + 1, -a, a << 30):
                with self.subTest(a_bits=a.bit_length(), b_bits=b.bit_length(), equal=a == b):
                    left, right = int(str(a)), int(str(b))
                    self.assertIsNot(left, right)
                    target = (right, 0)
                    before = ex.get_region_stats()["tuple_list_entries"]
                    self.assertIs(compare([left, 0], (0, 0), target, 2), a == b)
                    self.assertGreater(ex.get_region_stats()["tuple_list_entries"], before)
                    self.assertIs(self.executed(direct_ex, "tuple_entries", direct,
                                                 left, 0, target, 0, 2), a == b)

    def test_list_pair_mutation(self):
        ns = {}
        exec("def compare(items, positions, pair, values, n):\n"
             "    results = []\n"
             "    for k in range(n):\n"
             "        i = positions[k & 1]\n"
             "        results.append((items[i], items[i + 1]) == pair)\n"
             "        items[0] = values[k & 1]\n"
             "    return results\n", ns)
        compare = ns["compare"]
        compare([b"a", b"b"], (0, 0), (b"a", b"b"), (b"a", b"a"), TIER2_THRESHOLD)
        ex = self.executor(compare, "_COMPARE_LIST_PAIR")
        before = ex.get_region_stats()["tuple_list_entries"]
        self.assertEqual(compare([b"a", b"b"], (0, 0), (b"a", b"b"),
                                 (b"a", b"x"), 4), [True, True, False, True])
        self.assertGreater(ex.get_region_stats()["tuple_list_entries"], before)

    def test_list_pair_callbacks(self):
        compare, ex = self.warm_list_pair()
        events = []
        class Item:
            def __eq__(self, other):
                events.append(("eq", other))
                return False
        first = Item()
        before = ex.get_region_stats()["tuple_guard_exits"]
        self.assertFalse(compare([first, b"b"], (0, 0), (b"x", b"y"), 2))
        self.assertEqual(events, [("eq", b"x"), ("eq", b"x")])
        self.assertGreater(ex.get_region_stats()["tuple_guard_exits"], before)
        events.clear()
        class Index(int):
            def __add__(self, other):
                events.append(("add", other))
                return int(self) + other
        self.assertTrue(compare([b"a", b"b"], (0, Index(0)), (b"a", b"b"), 2))
        self.assertEqual(events, [("add", 1)])
        events.clear()
        class Items(list):
            def __getitem__(self, index):
                events.append(("get", index))
                return super().__getitem__(index)
        self.assertTrue(compare(Items([b"a", b"b"]), (0, 0), (b"a", b"b"), 2))
        self.assertEqual(events, [("get", 0), ("get", 1)] * 2)

    def test_list_pair_right_tuple_callback(self):
        compare, ex = self.warm_list_pair()
        events = []
        class Pair(tuple):
            def __eq__(self, other):
                events.append(other)
                return "result"
        target = Pair((b"a", b"b"))
        before = ex.get_region_stats()["tuple_guard_exits"]
        self.assertEqual(compare([b"a", b"b"], (0, 0), target, 2), "result")
        self.assertEqual(events, [(b"a", b"b")] * 2)
        self.assertGreater(ex.get_region_stats()["tuple_guard_exits"], before)

    def test_tuple_pair_comparison(self):
        nan = float("nan")
        cases = [
            (b"ab", b"cd", (b"ab", b"cd")),
            (b"ab", b"cd", (b"ac", b"cd")),
            ("é", "漢字", ("é", "漢字")),
            ("é", "漢字", ("é", "漢")),
            (17, -19, (17, -19)),
            (2**200, -(2**300), (int(str(2**200)), int(str(-(2**300))))),
            (2**200, 2**300, (2**200, 2**301)),
            (0.0, -0.0, (-0.0, 0.0)),
            (nan, nan, (nan, nan)),
            (nan, 1.0, (float("nan"), 1.0)),
            (float("inf"), 1.0, (float("inf"), 1.0)),
        ]
        for expression, compare in (("(a, b) == c", operator.eq),
                                    ("(a, b) != c", operator.ne)):
            func = arithmetic(expression)
            func(*cases[0], 0, TIER2_THRESHOLD)
            ex = self.executor(func, "_COMPARE_TUPLE_PAIR")
            for a, b, c in cases:
                with self.subTest(expression=expression, a=a, b=b, c=c):
                    expected = compare((a, b), c)
                    actual = self.executed(ex, "tuple_entries", func,
                                           a, b, c, 0, 8)
                    self.assertIs(actual, expected)

    def test_tuple_pair_fallback_and_callbacks(self):
        events = []

        class Element(int):
            def __eq__(self, other):
                events.append(int(self))
                return int(self) == other

        class Pair(tuple):
            def __eq__(self, other):
                events.append(type(other))
                return "overridden"

        func = arithmetic("(a, b) == c")
        func(1, 2, (1, 2), 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_COMPARE_TUPLE_PAIR")
        self.assertFalse(self.executed(ex, "tuple_guard_exits", func,
                                       Element(1), Element(2), (1, 3), 0, 8))
        self.assertEqual(events, [1, 2] * 8)
        events.clear()
        self.assertEqual(self.executed(ex, "tuple_guard_exits", func,
                                       1, 2, Pair((1, 2)), 0, 8), "overridden")
        self.assertEqual(events, [tuple] * 8)
        # Different lengths still compare the common prefix: do not shortcut
        # the user callback just because the lengths differ.
        events.clear()
        self.assertFalse(self.executed(ex, "tuple_guard_exits", func,
                                       Element(1), 2, (1,), 0, 8))
        self.assertEqual(events, [1] * 8)
        for a, b, c in ((1, 2, (1.0, 2.0)), (True, False, (1, 0)),
                        (1, 2, [1, 2]), (1, 2, ())):
            self.assertEqual(self.executed(ex, "tuple_guard_exits", func,
                                           a, b, c, 0, 8), operator.eq((a, b), c))

    def test_tuple_pair_owned_fallback(self):
        events = []

        class Element:
            def __init__(self, number):
                self.number = number

            def __eq__(self, other):
                events.append(("eq", self.number))
                return True

            def __del__(self):
                events.append(("del", self.number))

        func = arithmetic("(a(), b()) == c")
        store = [2, 1] * TIER2_THRESHOLD
        pop = store.pop
        func(pop, pop, (1, 2), 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_COMPARE_TUPLE_PAIR")
        for _ in range(8):
            store.extend((Element(2), Element(1)))
        self.assertTrue(self.executed(ex, "tuple_guard_exits", func,
                                      pop, pop, (1, 2), 0, 8))
        self.assertEqual(events, [("eq", 1), ("eq", 2),
                                  ("del", 2), ("del", 1)] * 8)

    def test_tuple_pair_bytes_warning(self):
        from test.support.script_helper import assert_python_ok

        assert_python_ok("-bb", "-c", """
from _testinternalcapi import TIER2_THRESHOLD
from test.test_capi.test_opt import get_all_executors, get_opnames

def check():
    def run(a, b, choices, n):
        for i in range(n):
            c = choices[i != 0]
            result = (a, b) == c
        return result

    pair = (b'x', b'y')
    run(b'x', b'y', (pair, pair), TIER2_THRESHOLD)
    ex = next(ex for ex in get_all_executors(run)
              if any(op.startswith('_COMPARE_TUPLE_PAIR') for op in get_opnames(ex)))
    before = ex.get_region_stats()['tuple_guard_exits']
    try:
        # The first iteration runs in Tier 1; raise only after entering JIT.
        run(b'x', b'y', (pair, ('x', 'y')), 8)
    except BytesWarning:
        pass
    else:
        raise AssertionError('BytesWarning was lost')
    assert ex.get_region_stats()['tuple_guard_exits'] > before

check()
""", PYTHON_TIER2_BUILTIN_REGIONS="1", PYTHON_JIT="1")

    @requires_call_regions
    def test_trivial_calls_arguments_and_constants(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        values = [object(), [], {}, object()]
        for count in range(5):
            parameters = [f"p{i}" for i in range(count)]
            returns = parameters + ["None", "True", "False", "17"]
            for returned in returns:
                with self.subTest(count=count, returned=returned):
                    namespace = {}
                    exec(f"def leaf({', '.join(parameters)}):\n"
                         f"    return {returned}\n", namespace)
                    leaf = namespace["leaf"]
                    caller_ns = {}
                    arguments = ", ".join(f"values[{i}]" for i in range(count))
                    exec("def run(leaf, values, n):\n"
                         "    result = None\n"
                         "    for _ in range(n):\n"
                         f"        result = leaf({arguments})\n"
                         "    return result\n", caller_ns)
                    run = caller_ns["run"]
                    expected = leaf(*values[:count])
                    self.assertIs(run(leaf, values, TIER2_THRESHOLD), expected)
                    ex = self.executor(run, "_CALL_PY_TRIVIAL")
                    self.assertIs(self.executed(ex, "call_entries", run,
                                               leaf, values, 8), expected)

    @requires_call_regions
    def test_trivial_method_and_code_replacement(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        class Receiver:
            def identity(self):
                return self

        obj = Receiver()
        func = arithmetic("a.identity()")
        func(obj, 0, 0, 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_CALL_PY_TRIVIAL")
        self.assertIs(self.executed(ex, "call_entries", func, obj, 0, 0, 0, 8), obj)

        def replacement(self):
            return 42

        Receiver.identity.__code__ = replacement.__code__
        self.assertEqual(func(obj, 0, 0, 0, 8), 42)

        class Override(Receiver):
            def identity(self):
                raise ValueError("overridden")

        with self.assertRaisesRegex(ValueError, "overridden"):
            func(Override(), 0, 0, 0, 8)

    @requires_call_regions
    def test_trivial_call_cleanup_and_reentry(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        events = []

        class Argument:
            def __init__(self, number):
                self.number = number

            def __del__(self):
                # Reenter Python while the outer call still owns other args.
                events.append((self.number, sum(range(50))))

        def leaf(first, second, third):
            return first

        def run(n):
            result = None
            for _ in range(n):
                result = leaf(Argument(1), Argument(2), Argument(3))
            return result

        warm = run(TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_TRIVIAL")
        del warm
        events.clear()
        result = self.executed(ex, "call_entries", run, 8)
        del result
        self.assertEqual([number for number, total in events],
                         [3, 2] + [3, 2, 1] * 7 + [1])
        self.assertTrue(all(total == 1225 for number, total in events))

    @requires_call_regions
    def test_trivial_call_monitoring(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))

        def leaf(arg):
            return arg

        func = arithmetic("a(b)")
        func(leaf, 17, 0, 0, TIER2_THRESHOLD)
        self.executor(func, "_CALL_PY_TRIVIAL")
        monitoring = sys.monitoring
        tool = 4
        monitoring.use_tool_id(tool, "test_trivial_call")
        events = []
        try:
            monitoring.register_callback(tool, monitoring.events.PY_START,
                                         lambda *args: events.append("start"))
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda *args: events.append("return"))
            monitoring.set_local_events(tool, leaf.__code__,
                                        monitoring.events.PY_START | monitoring.events.PY_RETURN)
            self.assertEqual(func(leaf, 17, 0, 0, 8), 17)
            self.assertEqual(events, ["start", "return"] * 8)
        finally:
            monitoring.set_local_events(tool, leaf.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_START, None)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @requires_call_regions
    def test_trivial_call_code_lifetime(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"PYTHON_TIER2_CALL_REGIONS": "1"}))
        events = []
        namespace = {}
        # The dynamically compiled code has no enclosing co_consts owner.
        exec("def leaf(arg):\n    return None\n", namespace)
        leaf = namespace.pop("leaf")
        old_code = weakref.ref(leaf.__code__, lambda _: events.append("code"))

        def replacement(arg):
            return 17

        class Finalizer:
            def __del__(self):
                events.append("before")
                leaf.__code__ = replacement.__code__
                events.append(("after", old_code() is not None))

        def run(leaf, pop, n):
            for _ in range(n):
                result = leaf(pop())
            return result

        store = [0] * TIER2_THRESHOLD
        run(leaf, store.pop, TIER2_THRESHOLD)
        ex = self.executor(run, "_CALL_PY_TRIVIAL")
        # Make the first Tier 1 iteration harmless; the second uses the JIT.
        store.extend((Finalizer(), 0))
        self.assertIsNone(self.executed(ex, "call_entries", run, leaf, store.pop, 2))
        self.assertEqual(events, ["before", ("after", True), "code"])
        self.assertIsNone(old_code())

    def test_methods_and_unicode(self):
        for method in ("startswith", "endswith"):
            func = arithmetic(f"a.{method}(b)")
            func("header: value", "head", 0, 0, TIER2_THRESHOLD)
            ex = self.executor(func, "_CALL_STR_TAILMATCH")
            for text, affix in [("", ""), ("", "x"), ("abc", ""),
                                ("éclair", "é"), ("漢字", "字"),
                                ("🐍python🐍", "🐍"), ("abc", "abcd")]:
                expected = getattr(str, method)(text, affix)
                actual = self.executed(ex, "method_entries", func, text, affix, 0, 0, 8)
                self.assertIs(actual, expected)
            self.assertIs(func("abc", ("a", "c"), 0, 0, 8), True)
            with self.assertRaises(TypeError):
                func("abc", 123, 0, 0, 8)

    def test_method_override_and_argument_order(self):
        events = []

        class Text(str):
            def startswith(self, prefix):
                events.append("override")
                return 42

        func = arithmetic("a.startswith(b)")
        func("abc", "a", 0, 0, TIER2_THRESHOLD)
        self.executor(func, "_CALL_STR_TAILMATCH")
        self.assertEqual(func(Text("abc"), "a", 0, 0, 8), 42)
        self.assertEqual(events, ["override"] * 8)

        def prefix():
            events.append("argument")
            return "a"

        def run(text, n):
            result = False
            for _ in range(n):
                result = text.startswith(prefix())
            return result

        support.reset_code(run)
        self.addCleanup(support.reset_code, run)
        run("abc", TIER2_THRESHOLD)
        self.executor(run, "_CALL_STR_TAILMATCH")
        events.clear()
        self.assertTrue(run("abc", 8))
        self.assertEqual(events, ["argument"] * 8)
        for expression in ("a.startswith(b, 1)", "a.endswith(b, 0, 2)"):
            func = arithmetic(expression)
            self.assertIsInstance(func("abc", "b", 0, 0, TIER2_THRESHOLD), bool)
            self.assertFalse(any("_CALL_STR_TAILMATCH" in get_opnames(ex)
                                 for ex in get_all_executors(func)))
        with self.assertRaises(TypeError):
            "abc".startswith(prefix="a")

    def test_float_owned_rounding(self):
        nan1 = struct.unpack("=d", struct.pack("=Q", 0x7ff8000000000001))[0]
        nan2 = struct.unpack("=d", struct.pack("=Q", 0xfff8000000000002))[0]
        cases = [
            (-1.0, 1.0 + 2**-27, 1.0 - 2**-27),
            (-0.0, 0.0, 1.0), (0.0, -0.0, 1.0),
            (float("inf"), -float("inf"), 1.0),
            (0.0, 2.0**-1022, 0.5), (0.0, 5e-324, 0.5),
            (1.0, 2.0**1023, 2.0), (1.25, 1.25, 1.25),
            (nan1, nan2, 1.0), (1.0, nan1, nan2),
        ]
        for fields in ((True, False), (False, True), (True, True)):
            for symbol, update in (("+", operator.add), ("-", operator.sub)):
                with self.subTest(fields=fields, symbol=symbol):
                    run, holder, ex = self.warm_float_owned(symbol, fields)
                    for a, b, c in cases:
                        holder.left, holder.right = b, c
                        inputs = [struct.pack("=d", x) for x in (a, b, c)]
                        expected = update(operator.mul(a, 1.0), operator.mul(b, c))
                        actual = self.executed(ex, "float_owned_entries", run,
                                               a, b, c, holder, 8)
                        if math.isnan(expected):
                            self.assertTrue(math.isnan(actual))
                        else:
                            self.assertEqual(struct.pack("=d", actual), struct.pack("=d", expected))
                        self.assertEqual([struct.pack("=d", x) for x in (a, b, c)], inputs)

    def test_float_owned_reference_ownership(self):
        for fields in ((True, False), (False, True), (True, True)):
            run, holder, ex = self.warm_float_owned(fields=fields)
            value = float("1.25")
            holder.left = holder.right = value
            references = sys.getrefcount(value)
            actual = self.executed(ex, "float_owned_entries", run,
                                   value, value, value, holder, 1000)
            self.assertEqual(actual, 2.8125)
            self.assertEqual(value, 1.25)
            self.assertIsNot(actual, value)
            self.assertEqual(sys.getrefcount(value), references)

    def test_float_owned_subclass_callback(self):
        run, holder, ex = self.warm_float_owned()
        events = []

        class Product(float):
            def __mul__(self, other):
                events.append(other)
                return 42.0

        holder.left = Product(3.0)
        self.assertEqual(run(7.0, 3.0, 2.0, holder, 8), 49.0)
        self.assertEqual(events, [2.0] * 8)
        holder.left = 3.0
        self.assertEqual(self.executed(ex, "float_owned_entries", run,
                                       7.0, 3.0, 2.0, holder, 8), 13.0)

    def test_float_rounding_and_ownership(self):
        cases = [
            (-1.0, 1.0 + 2**-27, 1.0 - 2**-27),
            (-0.0, 0.0, 1.0), (0.0, -0.0, 1.0),
            (1.0, float("nan"), 1.0),
            (float("inf"), -float("inf"), 1.0),
            (0.0, 2.0**-1022, 0.5), (0.0, 5e-324, 0.5),
            (1.0, 2.0**1023, 2.0), (1.25, 1.25, 1.25),
        ]
        for unique in (False, True):
            for symbol, update in (("+", operator.add), ("-", operator.sub)):
                expression = f"{'a * 1.0' if unique else 'a'} {symbol} b * c"
                func = arithmetic(expression)
                func(7.0, 3.0, 2.0, 0, TIER2_THRESHOLD)
                suffix = "INPLACE" if unique else "SHARED"
                opname = "ADD" if symbol == "+" else "SUBTRACT"
                ex = self.executor(func, f"_BINARY_OP_MULTIPLY_{opname}_FLOAT_{suffix}")
                counter = "float_unique_entries" if unique else "float_shared_entries"
                for a, b, c in cases:
                    before = struct.pack("=d", a)
                    expected = update(operator.mul(a, 1.0) if unique else a,
                                      operator.mul(b, c))
                    actual = self.executed(ex, counter, func, a, b, c, 0, 8)
                    if math.isnan(expected):
                        self.assertTrue(math.isnan(actual))
                    else:
                        self.assertEqual(struct.pack("=d", actual), struct.pack("=d", expected))
                    self.assertEqual(struct.pack("=d", a), before)

    def test_float_shared_guard_order(self):
        events = []

        class Accumulator(float):
            def __add__(self, product):
                events.append(("add", product))
                return 123.0

        func = arithmetic("a + b * c")
        func(7.0, 3.0, 2.0, 0, TIER2_THRESHOLD)
        ex = self.executor(func, "_BINARY_OP_MULTIPLY_ADD_FLOAT_SHARED")
        value = Accumulator(7.0)
        self.assertEqual(self.executed(ex, "float_guard_exits", func,
                                       value, 3.0, 2.0, 0, 8), 123.0)
        self.assertEqual(events, [("add", 6.0)] * 8)
        self.assertEqual(value, 7.0)
        self.assertEqual(func(7.0, 3.0, 2.0, 0, 32), 13.0)

    @unittest.skipUnless(support.Py_DEBUG, "requires targeted allocation failure probe")
    def test_allocation_failure_in_frame(self):
        for kind, expression, args, opcode in [
            ("int", "a * b + c", (31, 17, 9), "_INT_REGION"),
            ("float", "a + b * c", (7.0, 3.0, 2.0),
             "_BINARY_OP_MULTIPLY_ADD_FLOAT_SHARED"),
            ("len", "len(a) - b", ("x" * 400, 10, 0), "_CALL_LEN_CONSUMER"),
        ]:
            namespace = {}
            exec("def run(a, b, c, n):\n"
                 "    marker = 12345\n"
                 "    try:\n"
                 "        for _ in range(n):\n"
                 f"            result = {expression}\n"
                 "    except MemoryError:\n"
                 "        return marker, a, b, c\n"
                 "    return result\n", namespace)
            func = namespace["run"]
            func(*args, TIER2_THRESHOLD)
            ex = self.executor(func, opcode)
            with mock.patch.dict(os.environ, {"PYTHON_TIER2_REGION_FAIL_ALLOC": kind}):
                result = self.executed(ex, "allocation_errors", func, *args, 8)
            self.assertEqual(result, (12345, *args))
            self.assertIs(result[1], args[0])
            self.assertNotIsInstance(func(*args, 32), tuple)


if __name__ == "__main__":
    unittest.main()
