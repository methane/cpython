import tempfile
from pathlib import Path
import re
import unittest
from unittest import mock

from test.test_tools import imports_under_tool


with imports_under_tool("jit"):
    import _optimizers
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


class JITOptimizerTests(unittest.TestCase):
    def test_local_data_references_keep_labels_live(self):
        source = """
            .section .rodata
        .LCPI0_0:
            .quad 1
            .text
            .globl _JIT_ENTRY
        _JIT_ENTRY:
            movdqa .LCPI0_0(%rip), %xmm0
            cmpq $2, %rax
            ja .Ldefault
            jmpq *.LJTI0_0(,%rax,8)
        .Lcase0:
            addq $1, %rax
            jmp .L_JIT_CONTINUE
        .Lcase1:
            addq $2, %rax
            jmp .L_JIT_CONTINUE
        .Lcase2:
            addq $3, %rax
            jmp .L_JIT_CONTINUE
        .Ldefault:
            addq $4, %rax
            jmp .L_JIT_CONTINUE
            .section .rodata
        .LJTI0_0:
            .quad .Lcase0
            .quad .Lcase1
            .quad .Lcase2
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.s"
            path.write_text(source)
            _optimizers.OptimizerX86(
                path,
                label_prefix=".L",
                symbol_prefix="",
                re_global=re.compile(
                    r'\s*\.globl\s+(?P<label>[\w."$?@]+)(\s+.*)?'
                ),
                frame_pointers=False,
            ).run()
            optimized = path.read_text()

        for label in (".LCPI0_0", ".Lcase0", ".Lcase1", ".Lcase2", ".LJTI0_0"):
            with self.subTest(label=label):
                self.assertIn(f"{label}:", optimized)


if __name__ == "__main__":
    unittest.main()
