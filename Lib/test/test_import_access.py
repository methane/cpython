"""Checked acquisition of callbacks stored in the interpreter's import state."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ImportAccessTests(unittest.TestCase):
    PRELUDE = '''
import _frozen_importlib as bootstrap
import sys
import threading
from types import ModuleType
from test.support import SHORT_TIMEOUT
from test.support import threading_helper

results = threading.Channel()
modules = sys.modules
assert bootstrap.__shareable__ is threading.Shareable.SYNCHRONIZED

def run(worker):
    thread = threading.Thread(target=worker, group=threading.ThreadGroup())
    with threading_helper.start_threads([thread]):
        pass
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_repr_worker_local_module(self):
        self.run_script('''
            def worker():
                module = ModuleType('worker_local')
                results.put(repr(module))
            run(worker)
            assert results.get() == "<module 'worker_local'>"
        ''')

    def test_missing_attribute_worker_local_module(self):
        self.run_script('''
            def worker():
                module = ModuleType('worker_local')
                try:
                    module.missing
                except AttributeError as exc:
                    results.put(str(exc))
                else:
                    raise AssertionError('missing attribute was found')
            run(worker)
            assert results.get() == (
                "module 'worker_local' has no attribute 'missing'")
        ''')

    def test_repr_shared_modules(self):
        self.run_script('''
            immutable = freeze(ModuleType('immutable'))
            synchronized = ModuleType('synchronized')
            synchronized.synchronize()
            local_module = ModuleType('local')
            local_module.callback = bootstrap._module_repr
            def worker():
                results.put(repr(immutable))
                results.put(repr(synchronized))
                try:
                    local_module.callback
                except IllegalThreadAccessException:
                    results.put('local module denied')
                else:
                    raise AssertionError('local module became accessible')
            run(worker)
            assert results.get() == "<module 'immutable'>"
            assert results.get() == "<module 'synchronized'>"
            assert results.get() == 'local module denied'
            assert local_module.__shareable__ is threading.Shareable.LOCAL
            assert bootstrap.__shareable__ is threading.Shareable.SYNCHRONIZED
        ''')

    def test_repr_local_callback_rejected(self):
        self.run_script('''
            calls = []
            class LocalCallback:
                def __call__(self, module):
                    calls.append(module)
                    return 'unexpected'
            original = bootstrap._module_repr
            module = freeze(ModuleType('shared'))
            def worker():
                try:
                    repr(module)
                except IllegalThreadAccessException:
                    results.put('denied')
            try:
                bootstrap._module_repr = LocalCallback()
                run(worker)
            finally:
                bootstrap._module_repr = original
            assert results.get() == 'denied'
            assert calls == []
        ''')

    def test_repr_protected_callback(self):
        self.run_script('''
            calls = threading.Channel()
            class Callback:
                def __call__(self, module):
                    calls.put(module.__name__)
                    return 'protected callback'
            lock = threading.Lock()
            module = freeze(ModuleType('shared'))
            original = bootstrap._module_repr
            def worker():
                try:
                    repr(module)
                except UnprotectedAccessException:
                    results.put('denied')
                with lock:
                    results.put(repr(module))
            try:
                with lock:
                    bootstrap._module_repr = lock.protect(Callback())
                run(worker)
            finally:
                bootstrap._module_repr = original
            assert results.get() == 'denied'
            assert results.get() == 'protected callback'
            assert calls.get() == 'shared'
            try:
                calls.get()
            except IndexError:
                pass
            else:
                raise AssertionError('inaccessible callback was called')
        ''')

    def test_find_and_load_shared_callback(self):
        self.run_script('''
            name = 'pep805_worker_import'
            original = bootstrap._find_and_load
            def find_and_load(fullname, import_):
                if fullname != name:
                    return original(fullname, import_)
                module = ModuleType(fullname)
                module.answer = 42
                modules[fullname] = module
                return module
            def worker():
                module = __import__(name)
                results.put(module.answer)
                results.put(freeze(module))
            try:
                bootstrap._find_and_load = find_and_load
                run(worker)
                assert results.get() == 42
                assert results.get() is modules[name]
            finally:
                bootstrap._find_and_load = original
                modules.pop(name, None)
        ''')

    def test_find_and_load_local_callback_rejected(self):
        self.run_script('''
            calls = []
            class LocalCallback:
                def __call__(self, name, import_):
                    calls.append(name)
                    return ModuleType(name)
            original = bootstrap._find_and_load
            def worker():
                try:
                    __import__('pep805_local_import_callback')
                except IllegalThreadAccessException:
                    results.put('denied')
            try:
                bootstrap._find_and_load = LocalCallback()
                run(worker)
            finally:
                bootstrap._find_and_load = original
            assert results.get() == 'denied'
            assert calls == []
        ''')

    def test_fromlist_shared_callback(self):
        self.run_script('''
            name = 'pep805_shared_package'
            module = ModuleType(name)
            module.__path__ = ()
            freeze(module)
            original = bootstrap._handle_fromlist
            calls = threading.Channel()
            def handle_fromlist(package, fromlist, import_):
                calls.put((package.__name__, fromlist))
                return package
            def worker():
                results.put(__import__(name, fromlist=('answer',)))
            try:
                modules[name] = module
                bootstrap._handle_fromlist = handle_fromlist
                run(worker)
                assert results.get() is module
                assert calls.get() == (name, ('answer',))
            finally:
                bootstrap._handle_fromlist = original
                modules.pop(name, None)
        ''')

    def test_missing_attribute_hook_in_owner(self):
        self.run_script('''
            original = bootstrap._module_repr
            calls = []
            def get_attribute(name):
                calls.append(name)
                if name == '_module_repr':
                    return lambda module: 'dynamic callback'
                raise AttributeError(name)
            try:
                del bootstrap._module_repr
                bootstrap.__getattr__ = get_attribute
                assert repr(ModuleType('dynamic')) == 'dynamic callback'
                assert calls == ['_module_repr']
            finally:
                bootstrap._module_repr = original
                del bootstrap.__getattr__
        ''')

    def test_module_subclass_attribute_lookup(self):
        self.run_script('''
            calls = []
            class Bootstrap(ModuleType):
                def __getattribute__(self, name):
                    if name == '_module_repr':
                        calls.append(name)
                        return lambda module: 'subclass callback'
                    return super().__getattribute__(name)
            try:
                bootstrap.__class__ = Bootstrap
                assert repr(ModuleType('dynamic')) == 'subclass callback'
                assert calls == ['_module_repr']
            finally:
                bootstrap.__class__ = ModuleType
        ''')

    def test_lazy_callback_attribute(self):
        self.run_script('''
            class CallableModule(ModuleType):
                def __call__(self, module):
                    return 'lazy callback'
            name = 'pep805_callable_repr'
            original = bootstrap._module_repr
            try:
                modules[name] = CallableModule(name)
                exec('lazy import pep805_callable_repr as _module_repr',
                     bootstrap.__dict__)
                assert repr(ModuleType('dynamic')) == 'lazy callback'
            finally:
                bootstrap._module_repr = original
                modules.pop(name, None)
                sys.lazy_modules.discard(name)
        ''')

    def test_attribute_hook_ends_debugger_access(self):
        self.run_script('''
            def producer():
                results.put((ModuleType('foreign'),))
            run(producer)
            holder = results.get()
            original = bootstrap._module_repr
            context = sys.monitoring.StopTheWorld
            entered = False
            calls = []
            def callback(module):
                calls.append('called')
                return 'unexpected'
            def get_attribute(name):
                global entered
                if name != '_module_repr':
                    raise AttributeError(name)
                context.__exit__(None, None, None)
                entered = False
                return callback
            try:
                del bootstrap._module_repr
                bootstrap.__getattr__ = get_attribute
                context.__enter__()
                entered = True
                try:
                    repr(holder[0])
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign receiver was used after resume')
                assert not entered
                assert calls == []
            finally:
                if entered:
                    context.__exit__(None, None, None)
                bootstrap._module_repr = original
                del bootstrap.__getattr__
        ''')

    def test_lazy_submodule_metadata_across_groups(self):
        self.run_script('''
            name = 'pep805_lazy_parent'
            fullname = name + '.child'
            module = ModuleType(name)
            module.synchronize()
            registry = sys.lazy_modules
            original = bootstrap._find_and_load_lazy_submodule
            calls = threading.Channel()
            def find_and_load_lazy_submodule(name, import_):
                calls.put(name)
                return freeze(ModuleType(name))
            def worker():
                results.put(fullname in registry)
                results.put(module.child.__name__)
                results.put(repr(module))
            try:
                exec('lazy import pep805_lazy_parent.child', {})
                modules[name] = module
                bootstrap._find_and_load_lazy_submodule = (
                    find_and_load_lazy_submodule)
                run(worker)
                assert results.get() is True
                assert results.get() == fullname
                assert results.get() == "<module 'pep805_lazy_parent'>"
                assert calls.get() == fullname
                assert module.child.__name__ == fullname
            finally:
                bootstrap._find_and_load_lazy_submodule = original
                modules.pop(name, None)
                registry.discard(fullname)
        ''')

    def test_concurrent_lazy_registration(self):
        self.run_script('''
            registry = sys.lazy_modules
            barrier = threading.Barrier(4, timeout=SHORT_TIMEOUT)
            def worker(index):
                barrier.wait()
                for offset in range(16):
                    name = f'pep805_registry_{index}_{offset}.child'
                    exec(f'lazy import {name}', {})
                    assert name in registry
                results.put(index)
            threads = [threading.Thread(target=worker, args=(index,),
                                         group=threading.ThreadGroup())
                       for index in range(4)]
            with threading_helper.start_threads(threads):
                pass
            assert {results.get() for _ in threads} == set(range(4))
            for index in range(4):
                for offset in range(16):
                    name = f'pep805_registry_{index}_{offset}.child'
                    assert name in registry
                    registry.remove(name)
        ''')


if __name__ == '__main__':
    unittest.main()
