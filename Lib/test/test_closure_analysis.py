"""Classification of bindings modified by nested functions."""

import marshal
import threading
import types
import unittest


class ClosureAnalysisTests(unittest.TestCase):
    def assert_local(self, func):
        self.assertIs(func.__shareable__, threading.Shareable.LOCAL)

    def assert_shared(self, func):
        self.assertIs(func.__shareable__, threading.Shareable.SYNCHRONIZED)

    def test_nonlocal_write(self):
        def outer():
            value = 0
            def writer():
                nonlocal value
                value += 1
                return value
            return writer
        self.assert_local(outer)
        writer = outer()
        self.assert_local(writer)
        self.assertEqual([writer(), writer()], [1, 2])

    def test_transitive_write_and_frame_locals(self):
        def outer():
            value = 0
            def middle():
                def writer():
                    nonlocal value
                    value = 42
                    return locals()['value']
                return writer
            return middle
        self.assert_local(outer)
        middle = outer()
        self.assert_local(middle)
        self.assertEqual(middle()(), 42)

    def test_shadowed_binding(self):
        def outer():
            value = 42
            def reader():
                return value
            def inner():
                value = 0
                def writer():
                    nonlocal value
                    value += 1
                    return value
                return writer
            return reader, inner
        self.assert_shared(outer)
        reader, inner = outer()
        self.assert_local(inner)
        self.assertEqual(inner()(), 1)
        self.assertEqual(reader(), 42)

    def test_delete_nonlocal(self):
        def outer():
            value = 42
            def delete():
                nonlocal value
                del value
            def reader():
                return value
            return delete, reader
        self.assert_local(outer)
        delete, reader = outer()
        delete()
        with self.assertRaises(NameError):
            reader()

    def test_class_scope_propagation(self):
        def outer():
            value = 0
            class Writer:
                def write(self):
                    nonlocal value
                    value += 1
                    return value
            return Writer
        self.assert_local(outer)
        instance = outer()()
        self.assertEqual([instance.write(), instance.write()], [1, 2])

    def test_own_cell_assignment(self):
        def outer():
            value = 0
            def reader():
                return value
            value = 42
            return reader
        self.assert_shared(outer)
        self.assertEqual(outer()(), 42)

    def test_extended_argument(self):
        assignments = ''.join(f'        v{i} = {i}\n' for i in range(300))
        source = ('def outer():\n'
                  '    value = 0\n'
                  '    def writer():\n'
                  '        nonlocal value\n' + assignments +
                  '        value += 1\n'
                  '        return value\n'
                  '    return writer\n')
        namespace = {}
        exec(source, namespace)
        outer = namespace['outer']
        self.assert_local(outer)
        writer = outer()
        self.assertGreater(writer.__code__.co_nlocals, 255)
        self.assertEqual(writer(), 1)

    def test_reconstruction_and_code_mutation(self):
        def outer():
            value = 0
            def writer():
                nonlocal value
                value += 1
            return writer
        def readonly():
            value = 0
            def reader():
                return value
            return reader
        for code in (outer.__code__.replace(),
                     marshal.loads(marshal.dumps(outer.__code__))):
            self.assert_local(types.FunctionType(code, globals()))
        read_code = next(c for c in readonly.__code__.co_consts
                         if isinstance(c, types.CodeType))
        constants = tuple(read_code if isinstance(c, types.CodeType) else c
                          for c in outer.__code__.co_consts)
        rebuilt = outer.__code__.replace(co_consts=constants)
        self.assert_shared(types.FunctionType(rebuilt, globals()))
        self.assertEqual(types.FunctionType(rebuilt, globals())()(), 0)
        def plain():
            return 42
        original = plain.__code__
        with self.assertWarns(DeprecationWarning):
            plain.__code__ = outer.__code__
        self.assert_local(plain)
        with self.assertWarns(DeprecationWarning):
            plain.__code__ = original
        self.assert_shared(plain)


if __name__ == '__main__':
    unittest.main()
