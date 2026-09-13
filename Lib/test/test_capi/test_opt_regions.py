"""Exercise opt-in regions through real executors, including their exits."""

import builtins
import math
import operator
import os
import random
import struct
import sys
import unittest
from unittest import mock

from test import support
from test.test_capi.test_opt import get_all_executors, get_opnames
from _testinternalcapi import TIER2_THRESHOLD


SETTINGS = {
    "PYTHON_TIER2_INT_REGIONS": "1",
    "PYTHON_TIER2_BUILTIN_REGIONS": "1",
    "PYTHON_TIER2_FLOAT_FUSION": "1",
}


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
            for value in ("x" * 400, b"x" * 400, tuple(range(400))):
                with self.subTest(expression=expression, receiver=type(value)):
                    func = arithmetic(expression)
                    func(value, 10, 0, 0, TIER2_THRESHOLD)
                    ex = self.executor(func, "_CALL_LEN_CONSUMER")
                    for right in (-2**40, 0, 399, 400, 401, 2**40):
                        actual = self.executed(ex, "len_entries", func,
                                               value, right, 0, 0, 8)
                        expected = eval(expression, {"a": value, "b": right})
                        self.assertEqual(actual, expected)

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
