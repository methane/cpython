"""ThreadGroup access checks when loading globals and builtins."""

import _thread
import dis
import sys
import threading
import types
import unittest
import weakref

from test.support import gc_collect, requires_specialization, threading_helper


class GlobalAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_annotation_global_access(self):
        self.check_annotation_access(False)

    @threading_helper.requires_working_threading()
    def test_annotation_builtin_access(self):
        self.check_annotation_access(True)

    def check_annotation_access(self, builtin):
        @freeze
        class Value:
            pass

        foreign = Value()
        reference = weakref.ref(foreign)
        values = SynchronizedDict(annotation_value=foreign)
        results = threading.Channel()
        source = 'class C:\n    x: annotation_value\n'

        def worker():
            try:
                # Copying the namespace preserves its values' ownership. The
                # new exact dict and annotation function belong to this group.
                namespace = values.copy()
                if builtin:
                    namespace['__build_class__'] = __build_class__
                    namespace = {'__builtins__': namespace}
                else:
                    namespace['__builtins__'] = {'__build_class__': __build_class__}
                namespace['__name__'] = 'annotation_access'
                exec(source, namespace)
                annotate = namespace['C'].__annotate__
                for _ in range(100):
                    try:
                        annotate(1)
                    except IllegalThreadAccessException:
                        pass
                    else:
                        results.put('foreign annotation value was exposed')
                        return
                target = namespace['__builtins__'] if builtin else namespace
                local = Value()
                target['annotation_value'] = local
                assert annotate(1)['x'] is local
                target['annotation_value'] = 42
                assert annotate(1)['x'] == 42
                del target['annotation_value']
                try:
                    annotate(1)
                except NameError:
                    pass
                else:
                    results.put('missing annotation name was accepted')
                    return
                results.put('ok')
            except BaseException as exc:
                results.put(str(exc))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'ok')
        values.clear()
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_runtime_namespaces(self):
        self.assertIs(type(sys.__dict__), SynchronizedDict)
        self.assertIs(type(_thread.__dict__), SynchronizedDict)
        for cls in (_thread.ThreadGroup, _thread.LockType, _thread.RLock,
                    _thread._ThreadHandle, _thread._ThreadBase, _thread._local):
            self.assertIs(cls.__shareable__, threading.Shareable.IMMUTABLE)
        results = threading.Channel()
        def worker():
            assert sys._getframe().f_code is code
            assert _thread.get_ident() == threading.get_ident()
            assert threading.current_thread().group is _thread._current_thread_group()
            results.put(True)
        code = worker.__code__
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_global_access(self):
        self.check_global_access(False, False)

    @threading_helper.requires_working_threading()
    def test_builtin_access(self):
        self.check_global_access(True, False)

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_global_access(self):
        self.check_global_access(False, True)

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_builtin_access(self):
        self.check_global_access(True, True)

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_global_call_access(self):
        self.check_global_access(False, True, call=True)

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_builtin_call_access(self):
        self.check_global_access(True, True, call=True)

    def check_global_access(self, builtin, specialize, call=False):
        @freeze
        class Value:
            calls = 0
            def __call__(self):
                self.calls += 1
                return self

        if call:
            def template():
                return global_value()
        else:
            def template():
                return global_value

        foreign = Value()
        reference = weakref.ref(foreign)
        values = SynchronizedDict(global_value=foreign)
        namespace = SynchronizedDict(__builtins__=values) if builtin else values
        f = types.FunctionType(template.__code__.replace(), namespace)
        for _ in range(100 if specialize else 1):
            self.assertIs(f(), foreign)
        if specialize:
            opcode = 'LOAD_GLOBAL_BUILTIN' if builtin else 'LOAD_GLOBAL_MODULE'
            self.assertIn(opcode, [i.opname for i in dis.get_instructions(f, adaptive=True)])

        results = threading.Channel()
        def worker():
            try:
                for _ in range(100):
                    try:
                        f()
                    except IllegalThreadAccessException:
                        pass
                    else:
                        results.put('foreign value was exposed')
                        return
                local = Value()
                values['global_value'] = local
                assert f() is local
                values['global_value'] = (lambda: 42) if call else 42
                assert f() == 42
                results.put('ok')
            except BaseException as exc:
                results.put(str(exc))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'ok')
        self.assertEqual(f(), 42)
        self.assertEqual(foreign.calls, (100 if specialize else 1) if call else 0)
        del foreign
        gc_collect()
        self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main()
