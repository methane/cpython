import unittest
from unittest import mock

from test.test_tools import imports_under_tool, skip_if_missing


skip_if_missing("jit")
with imports_under_tool("jit"):
    from _tier3 import Instruction, allocate_registers, optimize
    from _tier3_native import (
        CompiledLoop,
        _SUM_RANGE_UOPS,
        _SUM_SQUARES_UOPS,
        compile,
    )


class Tier3Tests(unittest.TestCase):
    def test_optimization_pipeline(self):
        trace = [
            Instruction("parameter", 0),
            Instruction("guard_int", inputs=(0,), effect=True),
            Instruction("const", 1, immediate=2),
            Instruction("const", 2, immediate=3),
            Instruction("add_int", 3, (1, 2), loop=True),
            Instruction("mul_int", 4, (3, 3), loop=True),
            Instruction("add_int", 5, (0, 4), loop=True),
            Instruction("result", inputs=(5,), effect=True),
        ]
        optimized = optimize(trace)
        self.assertEqual(
            [instruction.op for instruction in optimized],
            ["parameter", "guard_int", "const", "add_int", "result"],
        )
        self.assertEqual(optimized[2].immediate, 25)
        self.assertFalse(optimized[2].loop)
        self.assertEqual(optimized[-2].inputs, (0, 4))

    @unittest.skipUnless(
        __import__("platform").system() == "Linux"
        and __import__("platform").machine() == "x86_64",
        "Linux x86-64 only",
    )
    def test_native_range_and_guard_fallback(self):
        def original(n):
            total = 0
            for i in range(n):
                total += i
            return total

        executor = [(name, 0, 0, 0) for name in _SUM_RANGE_UOPS]
        with mock.patch.dict("os.environ", {"PYTHON_TIER3_JIT": "1"}):
            compiled = compile(original, executor)
        self.assertIsInstance(compiled, CompiledLoop)
        for value in (-5, 0, 1, 10, 10_000):
            self.assertEqual(compiled(value), original(value))
        self.assertEqual(compiled(True), original(True))

        class IntSubclass(int):
            pass

        self.assertEqual(compiled(IntSubclass(10)), original(IntSubclass(10)))
        compiled.original = lambda n: n * (n - 1) // 2
        self.assertEqual(compiled(4_294_967_297), 9_223_372_039_002_259_456)

    @unittest.skipUnless(
        __import__("platform").system() == "Linux"
        and __import__("platform").machine() == "x86_64",
        "Linux x86-64 only",
    )
    def test_native_squares(self):
        def original(n):
            total = 0
            for i in range(n):
                total += i * i
            return total

        executor = [(name, 0, 0, 0) for name in _SUM_SQUARES_UOPS]
        with mock.patch.dict("os.environ", {"PYTHON_TIER3_JIT": "1"}):
            compiled = compile(original, executor)
        for value in (-1, 0, 1, 100, 10_000):
            self.assertEqual(compiled(value), original(value))

    def test_unsupported_shape_falls_back(self):
        def different(n):
            return n + 1

        executor = [(name, 0, 0, 0) for name in _SUM_RANGE_UOPS]
        with mock.patch.dict("os.environ", {"PYTHON_TIER3_JIT": "1"}):
            self.assertIs(compile(different, executor), different)

    def test_disabled_by_default(self):
        def original(n):
            return n

        executor = [(name, 0, 0, 0) for name in _SUM_RANGE_UOPS]
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIs(compile(original, executor), original)

    def test_effectful_unused_instruction_survives(self):
        trace = [Instruction("guard_int", inputs=(9,), effect=True)]
        self.assertEqual(optimize(trace), trace)

    def test_linear_scan_spills(self):
        trace = [
            Instruction("parameter", 0),
            Instruction("parameter", 1),
            Instruction("add_int", 2, (0, 1)),
            Instruction("result", inputs=(2,), effect=True),
        ]
        allocations = allocate_registers(trace, 1)
        self.assertEqual(sum(item.spill is not None for item in allocations), 2)

    def test_invalid_register_count(self):
        with self.assertRaises(ValueError):
            allocate_registers([], -1)


if __name__ == "__main__":
    unittest.main()
