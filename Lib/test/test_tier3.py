import textwrap
import unittest
import _opcode

from test import support
from test.support import script_helper


@unittest.skipUnless(hasattr(_opcode, "get_executor"), "requires tier 2")
class Tier3RangeTests(unittest.TestCase):
    SCRIPT = textwrap.dedent("""
        import _opcode

        def executor(function):
            for offset in range(0, len(function.__code__.co_code), 2):
                try:
                    candidate = _opcode.get_executor(function.__code__, offset)
                except ValueError:
                    continue
                if candidate.get_tier3_stats()["entries"]:
                    return candidate
            raise AssertionError("the integrated Tier-3 path was not entered")

        def renamed(count, initial=0):
            accumulator = initial
            for current in range(count):
                accumulator += current
            return accumulator

        alias = renamed
        for _ in range(2000):
            alias(40, 10)
        assert alias(100, 2**63 - 10) == 2**63 - 10 + sum(range(100))
        assert alias(-1, True) is True
        assert alias(0, 12345678901234567890) == 12345678901234567890
        assert alias(count=23, initial=17) == 17 + sum(range(23))
        stats = executor(renamed).get_tier3_stats()
        assert stats["entries"] > 0, stats
        assert stats["iterations"] >= stats["entries"], stats
        if int(__import__('os').environ['PYTHON_TIER3_BUDGET']) < 39:
            assert stats["budget_exits"] > 0, stats

        def sum_and_last(n, initial):
            total = initial
            item = -1
            for item in range(n):
                total += item
            return total, item

        for _ in range(2000):
            assert sum_and_last(40, 3) == (3 + sum(range(40)), 39)
        assert sum_and_last(0, 3) == (3, -1)
        assert sum_and_last(17, 9) == (9 + sum(range(17)), 16)
        assert executor(sum_and_last).get_tier3_stats()["entries"] > 0
    """)

    def test_range_osr_and_materialization(self):
        for budget in (1, 2, 7, 64):
            with self.subTest(budget=budget):
                script_helper.assert_python_ok(
                    "-c", self.SCRIPT,
                    PYTHON_TIER3_JIT="1",
                    PYTHON_TIER3_BUDGET=str(budget),
                    PYTHON_JIT_STRESS="1",
                )

    def test_disabled_by_default(self):
        script_helper.assert_python_ok(
            "-c",
            "import os; assert os.getenv('PYTHON_TIER3_JIT') is None",
        )


if __name__ == "__main__":
    unittest.main()
