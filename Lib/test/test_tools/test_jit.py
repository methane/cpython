import tempfile
from pathlib import Path
import re
import unittest
from unittest import mock

from test.test_tools import imports_under_tool


with imports_under_tool("jit"):
    import _optimizers
    import _stencils
    import _targets


class JITOperandFieldTests(unittest.TestCase):
    def test_operand_fields_and_addends(self):
        for operand in (0, 1):
            for shift, width in ((0, 3), (0, 8), (8, 16), (10, 10), (20, 10),
                                 (24, 32), (56, 1), (58, 4), (32, 32),
                                 (39, 16), (58, 6)):
                with self.subTest(operand=operand, shift=shift, width=width):
                    name = f"_JIT_OPERAND{operand}_FIELD_{shift}_{width}"
                    value, symbol = _stencils.symbol_to_value(name)
                    self.assertEqual(
                        value, _stencils.HoleValue[f"OPERAND{operand}_FIELD"])
                    hole = _stencils.Hole(8, "R_X86_64_64", value, symbol, -4)
                    self.assertEqual(hole.as_c("code"),
                        f"patch_64(code + 0x8, ((instruction->operand{operand} >> {shift})"
                        f" & UINT64_C({(1 << width) - 1:#x})) + -0x4);")

    def test_invalid_operand_fields(self):
        for suffix in ("0_0", "0_33", "64_1", "63_2", "-1_8", "8", "8_16_extra"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    _stencils.symbol_to_value("_JIT_OPERAND0_FIELD_" + suffix)

    def test_operand_field_through_got(self):
        group = _stencils.StencilGroup()
        group.code.body.extend(bytes(8))
        group.code.holes.append(_stencils.Hole(
            0, "R_X86_64_GOTPCRELX", _stencils.HoleValue.GOT,
            "_JIT_OPERAND1_FIELD_24_32", -4))
        external_symbols = {}
        group.process_relocations(external_symbols)
        self.assertEqual(external_symbols, {})
        self.assertEqual(group.code.holes[0].value, _stencils.HoleValue.DATA)
        self.assertEqual(len(group.data.holes), 1)
        self.assertEqual(group.data.holes[0].as_c("data"),
            "patch_64(data + 0x0, ((instruction->operand1 >> 24) & UINT64_C(0xffffffff)));")

    def test_narrow_operand_field_relocation(self):
        value, symbol = _stencils.symbol_to_value("_JIT_OPERAND0_FIELD_32_32")
        hole = _stencils.Hole(1, "R_X86_64_32", value, symbol, 0)
        self.assertEqual(hole.as_c("code"),
            "patch_32(code + 0x1, ((instruction->operand0 >> 32) & UINT64_C(0xffffffff)));")



class JITTargetTests(unittest.TestCase):
    def test_runtime_headers_change_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools_jit = root / "Tools" / "jit"
            tools_jit.mkdir(parents=True)
            (tools_jit / "template.c").write_text("template\n")
            executor_cases = root / "executor_cases.c.h"
            executor_cases.write_text("executor cases\n")
            headers = {
                "PYCORE_OPTIMIZER_H": root / "pycore_optimizer.h",
                "PYCORE_JIT_CALL_H": root / "pycore_jit_call.h",
                "PYCORE_ENUMOBJECT_H": root / "pycore_enumobject.h",
                "PYTHON_CEVAL_MACROS_H": root / "ceval_macros.h",
            }
            for header in headers.values():
                header.write_text("initial header\n")
            (root / "pyconfig.h").write_text("configuration\n")

            target = _targets.get_target("x86_64-unknown-linux-gnu")
            target.pyconfig_dir = root
            with (
                mock.patch.object(
                    _targets, "PYTHON_EXECUTOR_CASES_C_H", executor_cases
                ),
                mock.patch.multiple(_targets, **headers),
                mock.patch.object(_targets, "TOOLS_JIT", tools_jit),
            ):
                first = target._compute_digest()
                self.assertEqual(target._compute_digest(), first)
                for name, header in headers.items():
                    with self.subTest(header=name):
                        header.write_text("changed header\n")
                        changed = target._compute_digest()
                        self.assertNotEqual(changed, first)
                        first = changed


class JITOptimizerTests(unittest.TestCase):
    def test_narrow_operand_field_constants(self):
        source = """
            .text
            .globl _JIT_ENTRY
        _JIT_ENTRY:
            movabsq $_JIT_OPERAND0_FIELD_24_32, %rax
            movabsq $_JIT_OPERAND1_FIELD_8_16, %r10
            movabsq $_JIT_OPERAND0_FIELD_0_8, %rdi # local
            movabsq $_JIT_OPARG_16, %r8
            movabsq $_JIT_OPERAND0_16, %r9
            movabsq $_JIT_OPERAND1_32, %r11
            movabsq $_JIT_TARGET, %rdx
            movabsq $_JIT_OPERAND0_FIELD_24_32+1, %rcx
            movabsq $_JIT_OPERAND0_FIELD_0_64, %rdx
            movabsq $_JIT_OPERAND0, %rsi
            movabsq $PyLong_Type, %rbx
            jmp _JIT_CONTINUE
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.s"
            path.write_text(source)
            _optimizers.OptimizerX86ELF(
                path, label_prefix=".L", symbol_prefix="",
                re_global=re.compile(r"\s*\.globl\s+(?P<label>\w+)"),
                frame_pointers=False,
            ).run()
            optimized = path.read_text()
        self.assertIn("movl $_JIT_OPERAND0_FIELD_24_32, %eax", optimized)
        self.assertIn("movl $_JIT_OPERAND1_FIELD_8_16, %r10d", optimized)
        self.assertIn("movl $_JIT_OPERAND0_FIELD_0_8, %edi # local", optimized)
        self.assertIn("movabsq $_JIT_OPARG_16, %r8", optimized)
        self.assertIn("movabsq $_JIT_OPERAND0_16, %r9", optimized)
        self.assertIn("movabsq $_JIT_OPERAND1_32, %r11", optimized)
        self.assertIn("movabsq $_JIT_TARGET, %rdx", optimized)
        for unchanged in ("$_JIT_OPERAND0_FIELD_24_32+1, %rcx",
                          "$_JIT_OPERAND0_FIELD_0_64, %rdx",
                          "$_JIT_OPERAND0, %rsi", "$PyLong_Type, %rbx"):
            self.assertIn("movabsq " + unchanged, optimized)

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
