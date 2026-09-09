import pathlib
import re
import tempfile
import textwrap
import unittest
from unittest import mock

from test.test_tools import imports_under_tool, skip_if_missing


skip_if_missing('jit')
with imports_under_tool('jit'):
    import _optimizers
    import _stencils
    import _targets


class JITOptimizerTests(unittest.TestCase):
    def test_headers_invalidate_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'Include' / 'internal').mkdir(parents=True)
            (root / 'Python').mkdir()
            tools_jit = root / 'Tools' / 'jit'
            tools_jit.mkdir(parents=True)
            cases = root / 'Python' / 'executor_cases.c.h'
            cases.write_text('/* executor */')
            (root / 'pyconfig.h').write_text('/* config */')
            target = _targets.get_target('x86_64-unknown-linux-gnu')
            target.pyconfig_dir = root
            with mock.patch.multiple(_targets, CPYTHON=root,
                                     TOOLS_JIT=tools_jit,
                                     PYTHON_EXECUTOR_CASES_C_H=cases):
                for name in ('Include/internal/pycore_tstate.h',
                             'Python/ceval_macros.h'):
                    with self.subTest(header=name):
                        header = root / name
                        header.write_text('/* before */')
                        before = target._compute_digest()
                        header.write_text('/* after */')
                        after = target._compute_digest()
                        self.assertNotEqual(before, after)
                        self.assertEqual(after, target._compute_digest())

    def test_constant_pool_before_entry(self):
        source = textwrap.dedent('''\
            .section .rodata.cst16,"aM",@progbits,16
            .p2align 4
        .LCPI0_0:
            .quad 0x8000000000000000
            .quad 0x8000000000000000
            .text
            .globl _JIT_ENTRY
        _JIT_ENTRY:
            xorps .LCPI0_0(%rip), %xmm0
            jmp _JIT_CONTINUE
        .Ldead:
            ud2
        ''')
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'test.s'
            path.write_text(source)
            _optimizers.OptimizerX86(
                path, label_prefix='.L', symbol_prefix='',
                re_global=re.compile(r'\s*\.globl\s+(?P<label>\w+)'),
                frame_pointers=False,
            ).run()
            # The optimizer also emits the original assembly in comments.
            lines = [line.strip() for line in path.read_text().splitlines()
                     if not line.startswith('#')]
        self.assertIn('.LCPI0_0:', lines)
        self.assertEqual(lines.count('.quad 0x8000000000000000'), 2)
        self.assertIn('.text', lines)
        self.assertIn('.globl _JIT_ENTRY', lines)
        self.assertLess(lines.index('.LCPI0_0:'), lines.index('.text'))
        self.assertLess(lines.index('.text'), lines.index('_JIT_ENTRY:'))
        self.assertNotIn('ud2', lines)

    def test_rip_relative_constant_pool(self):
        group = _stencils.StencilGroup()
        group.code.body.extend(bytes(8))
        group.data.body.extend(bytes(32))
        # llvm-readobj reports the -4 addend as an unsigned 64-bit value.
        hole = _stencils.Hole(4, 'R_X86_64_PC32', _stencils.HoleValue.ZERO,
                              '.LCPI0_0', (1 << 64) - 4)
        group.code.holes.append(hole)
        group.symbols['.LCPI0_0'] = _stencils.HoleValue.DATA, 16
        group.process_relocations({})
        self.assertEqual(hole.func, 'patch_32r')
        self.assertIsNone(hole.symbol)
        self.assertEqual(hole.value, _stencils.HoleValue.DATA)
        self.assertEqual(hole.as_c('code'),
                         'patch_32r(code + 0x4, (uintptr_t)data + 0xc);')

    def test_rip_relative_external_requires_got(self):
        group = _stencils.StencilGroup()
        group.code.body.extend(bytes(8))
        group.code.holes.append(_stencils.Hole(
            4, 'R_X86_64_PC32', _stencils.HoleValue.ZERO, 'external_data', -4))
        with self.assertRaisesRegex(ValueError, 'PyAPI_DATA'):
            group.process_relocations({})


if __name__ == '__main__':
    unittest.main()
