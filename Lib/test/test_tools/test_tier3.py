import unittest

from test.test_tools import imports_under_tool, skip_if_missing


skip_if_missing("jit")
with imports_under_tool("jit"):
    from _tier3 import Instruction, allocate_registers, optimize
    import tier3_bench


class Tier3Tests(unittest.TestCase):
    def test_optimization_pipeline(self):
        optimized = optimize(tier3_bench.sample_trace())
        self.assertEqual(
            [instruction.op for instruction in optimized],
            ["parameter", "guard_int", "const", "add_int", "result"],
        )
        self.assertEqual(optimized[2].immediate, 25)
        self.assertFalse(optimized[2].loop)
        self.assertEqual(optimized[-2].inputs, (0, 5))

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
