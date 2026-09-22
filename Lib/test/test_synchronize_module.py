"""Module synchronization retains namespace identity and shallow ownership."""

import dis
import importlib
import pathlib
import sys
import tempfile
import threading
import types
import unittest
import weakref

from test.support import SHORT_TIMEOUT, gc_collect, requires_specialization, threading_helper
from test.support.import_helper import DirsOnSysPath, import_module


class ModuleSynchronizationTests(unittest.TestCase):
    @requires_specialization
    def test_specialized_globals_and_builtins(self):
        module = types.ModuleType('shared_globals')
        builtins = SynchronizedDict(len=len)
        module.__dict__['__builtins__'] = builtins
        exec('offset = 40\ndef read(value): return len(value) + offset\n',
             module.__dict__)
        module.synchronize()
        for _ in range(100):
            self.assertEqual(module.read([1, 2]), 42)
        opnames = {inst.opname for inst in
                   dis.get_instructions(module.read, adaptive=True)}
        self.assertIn('LOAD_GLOBAL_MODULE', opnames)
        self.assertIn('LOAD_GLOBAL_BUILTIN', opnames)
        module.offset = 100
        self.assertEqual(module.read([1, 2]), 102)
        builtins['len'] = lambda value: 7
        self.assertEqual(module.read([1, 2]), 107)

    def test_namespace_identity(self):
        internal = import_module('_testinternalcapi')
        module = types.ModuleType('shared')
        module.payload = []
        namespace = module.__dict__
        keys = namespace.keys()
        setter = namespace.__setitem__
        self.assertIs(module.synchronize(), module)
        self.assertIs(module.__dict__, namespace)
        self.assertIs(type(namespace), SynchronizedDict)
        for value in (module, namespace):
            self.assertIs(value.__shareable__, threading.Shareable.SYNCHRONIZED)
            self.assertEqual(internal.object_owner_id(value), 0)
            self.assertIs(internal.object_check_access(value), value)
            self.assertIs(threading.TransferBox(value).claim(), value)
        self.assertIs(module.payload.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(namespace['__module__'], module)
        setter('answer', 42)
        self.assertEqual(module.answer, 42)
        self.assertIn('answer', keys)
        module.answer = 7
        self.assertEqual(namespace['answer'], 7)
        del module.answer
        self.assertNotIn('answer', namespace)

    def test_cached_loads_and_stores(self):
        module = types.ModuleType('cached')
        exec('answer = 42\ndef read(): return answer\n'
             'def write(value):\n global answer\n answer = value\n',
             module.__dict__)
        def read_attribute():
            return module.answer
        for _ in range(100):
            self.assertEqual(module.read(), 42)
            self.assertEqual(read_attribute(), 42)
            module.write(42)
        module.synchronize()
        module.write(100)
        self.assertEqual(module.read(), 100)
        self.assertEqual(read_attribute(), 100)
        self.assertIs(module.read.__globals__, module.__dict__)

    def test_import(self):
        name = 'pep805_synchronized_module_test'
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, name + '.py').write_text(
                'answer = 42\n__module__.synchronize()\n', encoding='utf-8')
            with DirsOnSysPath(directory):
                try:
                    module = importlib.import_module(name)
                    self.assertIs(type(module.__dict__), SynchronizedDict)
                    self.assertEqual(module.answer, 42)
                    self.assertIs(module.__shareable__,
                                  threading.Shareable.SYNCHRONIZED)
                finally:
                    sys.modules.pop(name, None)

    def test_rejected_states(self):
        class Submodule(types.ModuleType):
            pass
        for module in (Submodule('sub'), sys):
            namespace = module.__dict__
            namespace_type = type(namespace)
            with self.assertRaises(TypeError):
                module.synchronize()
            self.assertIs(module.__dict__, namespace)
            self.assertIs(type(namespace), namespace_type)
        module = types.ModuleType('shared')
        module.synchronize()
        with self.assertRaises(TypeError):
            module.synchronize()
        freeze(module)
        with self.assertRaises(TypeError):
            module.synchronize()

    def test_frozen_namespace(self):
        module = types.ModuleType('frozen_namespace')
        namespace = module.__dict__
        freeze(namespace)
        with self.assertRaises(TypeError):
            module.synchronize()
        self.assertIs(module.__dict__, namespace)
        self.assertIs(module.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(type(namespace), frozendict)
        class Submodule(types.ModuleType):
            pass
        # Failure must release the temporary guard against class changes.
        module.__class__ = Submodule
        self.assertIs(type(module), Submodule)

    def test_freeze_after_synchronize(self):
        module = types.ModuleType('frozen')
        module.answer = 42
        namespace = module.__dict__
        module.synchronize()
        self.assertIs(freeze(module), module)
        self.assertIs(module.__dict__, namespace)
        self.assertIs(type(namespace), frozendict)
        self.assertIs(module.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertEqual(module.answer, 42)
        with self.assertRaises(TypeError):
            module.answer = 7

    def test_reinitialize(self):
        module = types.ModuleType('original')
        namespace = module.__dict__
        module.synchronize()
        module.__init__('renamed', 'new doc')
        self.assertIs(module.__dict__, namespace)
        self.assertIs(type(namespace), SynchronizedDict)
        self.assertEqual(module.__name__, 'renamed')
        self.assertEqual(module.__doc__, 'new doc')
        self.assertIs(module.__module__, module)

    def test_cycle_collection(self):
        module = types.ModuleType('cycle')
        module.synchronize()
        ref = weakref.ref(module)
        del module
        gc_collect()
        self.assertIsNone(ref())

    @threading_helper.requires_working_threading()
    def test_foreign_rejection(self):
        module = types.ModuleType('local')
        results = threading.Channel()
        def worker():
            try:
                module.synchronize()
            except Exception as exc:
                results.put(type(exc).__name__)
            else:
                results.put('allowed')
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'IllegalThreadAccessException')
        self.assertIs(type(module.__dict__), dict)
        self.assertIs(module.__shareable__, threading.Shareable.LOCAL)

    @threading_helper.requires_working_threading()
    def test_parallel_reinitialization(self):
        module = types.ModuleType('original')
        module.synchronize()
        namespace = module.__dict__
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(100):
                module.__init__(f'name_{number}', f'doc_{number}')
            results.put(number)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sorted(results.get() for _ in threads), list(range(4)))
        self.assertIs(module.__dict__, namespace)
        self.assertIs(module.__module__, module)
        self.assertIn(module.__name__, [f'name_{number}' for number in range(4)])
        self.assertIn(module.__doc__, [f'doc_{number}' for number in range(4)])

    @threading_helper.requires_working_threading()
    def test_parallel_namespace_updates(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        module = types.ModuleType('parallel')
        namespace = module.__dict__
        module.synchronize()
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            shared = check_access(module)
            check_access(namespace)
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(100):
                setattr(shared, f'value_{number}_{index}', index)
            results.put(number)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sorted(results.get() for _ in threads), list(range(4)))
        for number in range(4):
            for index in range(100):
                self.assertEqual(namespace[f'value_{number}_{index}'], index)


if __name__ == '__main__':
    unittest.main()
