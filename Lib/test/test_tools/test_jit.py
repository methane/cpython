import tempfile
from pathlib import Path
import unittest
from unittest import mock

from test.test_tools import imports_under_tool


with imports_under_tool("jit"):
    import _targets


class JITTargetTests(unittest.TestCase):
    def test_optimizer_header_changes_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools_jit = root / "Tools" / "jit"
            tools_jit.mkdir(parents=True)
            (tools_jit / "template.c").write_text("template\n")
            executor_cases = root / "executor_cases.c.h"
            executor_cases.write_text("executor cases\n")
            optimizer_header = root / "pycore_optimizer.h"
            optimizer_header.write_text("optimizer layout 1\n")
            (root / "pyconfig.h").write_text("configuration\n")

            target = _targets.get_target("x86_64-unknown-linux-gnu")
            target.pyconfig_dir = root
            with (
                mock.patch.object(
                    _targets, "PYTHON_EXECUTOR_CASES_C_H", executor_cases
                ),
                mock.patch.object(
                    _targets, "PYCORE_OPTIMIZER_H", optimizer_header
                ),
                mock.patch.object(_targets, "TOOLS_JIT", tools_jit),
            ):
                first = target._compute_digest()
                self.assertEqual(target._compute_digest(), first)
                optimizer_header.write_text("optimizer layout 2\n")
                self.assertNotEqual(target._compute_digest(), first)


if __name__ == "__main__":
    unittest.main()
