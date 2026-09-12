import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from test import support


SCRIPT = Path(support.REPO_ROOT) / "Tools" / "jit" / "tier3_bench.py"
spec = importlib.util.spec_from_file_location("tier3_bench", SCRIPT)
tier3_bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tier3_bench)


class FakeExecutor:
    def __init__(self, progress=1, code=b"code"):
        self.progress = progress
        self.calls = 0
        self.code = code

    def get_tier3_stats(self):
        self.calls += 1
        return {"resident_iterations": self.progress * self.calls}

    def get_jit_code(self):
        return self.code

    def is_valid(self):
        return True


class Tier3BenchTests(unittest.TestCase):
    def measure(self, lookups, executor=None):
        iterator = iter(lookups)
        function = lambda n, initial: initial + sum(range(n))
        return tier3_bench.measure_sample(
            function, 4, 3, 9, 1, lambda unused: next(iterator)
        )

    def test_executor_disappears(self):
        executor = FakeExecutor()
        result = self.measure([(4, executor), None])
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["tier3_delta"])
        self.assertEqual(result["native_code_bytes"], 0)

    def test_executor_is_replaced(self):
        result = self.measure([(4, FakeExecutor()), (4, FakeExecutor())])
        self.assertEqual(result["status"], "executor replaced")
        self.assertIsNone(result["executor_identity"])

    def test_executor_unavailable(self):
        result = self.measure([None, None])
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["tier3_delta"])

    def test_stable_executor_with_zero_progress(self):
        executor = FakeExecutor(progress=0)
        result = self.measure([(4, executor), (4, executor)])
        self.assertEqual(result["status"], "stable")
        self.assertEqual(result["tier3_delta"]["resident_iterations"], 0)
        self.assertEqual(result["native_code_bytes"], 4)

    def test_executor_becomes_invalid(self):
        executor = FakeExecutor()
        executor.is_valid = mock.Mock(side_effect=(True, False))
        result = self.measure([(4, executor), (4, executor)])
        self.assertEqual(result["status"], "executor invalidated")
        self.assertIsNone(result["tier3_delta"])
        self.assertEqual(result["native_code_bytes"], 0)

    def test_configuration_checks_index_and_worktree(self):
        completed = mock.Mock(returncode=1)
        with mock.patch.object(
            tier3_bench.subprocess,
            "check_output",
            side_effect=("commit\n", "tree\n"),
        ), mock.patch.object(tier3_bench.subprocess, "run", return_value=completed) as run:
            config = tier3_bench.configuration()
        self.assertTrue(config["tracked_dirty"])
        self.assertEqual(run.call_args.args[0], ["git", "diff", "--quiet", "HEAD", "--"])

    def test_checks_each_result(self):
        calls = 0
        def wrong_after_first(n, initial):
            nonlocal calls
            calls += 1
            return 9 if calls == 1 else 10
        with self.assertRaises(AssertionError):
            tier3_bench.measure_sample(wrong_after_first, 4, 3, 9, 2)


if __name__ == "__main__":
    unittest.main()
