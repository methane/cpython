"""Exercise opt-in regions through real executors, including their exits."""

import builtins
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
        self.assertGreater(after["enum_guard_exits"], before["enum_guard_exits"])

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
