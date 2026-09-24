"""Import registries and finder entry points used by other ThreadGroups."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ImportFinderAccessTests(unittest.TestCase):
    PRELUDE = '''
import sys
import threading
from test.support import threading_helper

results = threading.Channel()
errors = SynchronizedList()

def run(action):
    def worker():
        try:
            action()
        except BaseException as exc:
            frames = []
            tb = exc.__traceback__
            while tb is not None:
                frames.append((tb.tb_frame.f_code.co_name, tb.tb_lineno))
                tb = tb.tb_next
            errors.append((type(exc).__name__, str(exc), tuple(frames)))
    thread = threading.Thread(target=worker, group=threading.ThreadGroup())
    with threading_helper.start_threads([thread]):
        pass
    assert not errors, list(errors)
'''
    CAPI = '''
import _testlimitedcapi
import _testinternalcapi
get_importer = _testlimitedcapi.PyImport_GetImporter
_testinternalcapi.object_declare_synchronized(get_importer)
'''

    def run_script(self, script, *, capi=False):
        assert_python_ok('-c', self.PRELUDE + (self.CAPI if capi else '')
                         + textwrap.dedent(script))

    def test_default_registries(self):
        self.run_script('''
            def action():
                assert type(sys.meta_path) is SynchronizedList
                assert type(sys.path_hooks) is SynchronizedList
                assert type(sys.path_importer_cache) is SynchronizedDict
                assert sys.meta_path and sys.path_hooks
            run(action)
        ''')

    def test_builtin_import_in_worker(self):
        self.run_script('''
            assert '_symtable' not in sys.modules
            def action():
                import _symtable
                table = _symtable.symtable('answer = 42', 'worker', 'exec')
                assert table.name == 'top'
                assert 'answer' in table.symbols
                class BadSource:
                    @property
                    def __class__(self):
                        raise RuntimeError('source class lookup failed')
                try:
                    _symtable.symtable(BadSource(), 'worker', 'exec')
                except RuntimeError as exc:
                    assert str(exc) == 'source class lookup failed'
                else:
                    raise AssertionError('class lookup exception suppressed')
                assert _symtable.__shareable__ is threading.Shareable.LOCAL
                assert __import__('_symtable') is _symtable
                results.put(_symtable.__name__)
            run(action)
            assert results.get() == '_symtable'
            try:
                sys.modules['_symtable']
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('worker module implicitly shared')
        ''')

    def test_compile_with_foreign_ast_metadata(self):
        self.run_script('''
            import _ast
            ast_type = _ast.AST
            assert ast_type.__shareable__ is threading.Shareable.LOCAL
            def action():
                for source in ('40 + 2', b'40 + 2', bytearray(b'40 + 2'),
                               memoryview(b'40 + 2')):
                    code = compile(source, 'worker', 'eval')
                    results.put(eval(code))
                try:
                    ast_type
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('AST type implicitly shared')
            run(action)
            assert [results.get() for _ in range(4)] == [42] * 4
            assert ast_type.__shareable__ is threading.Shareable.LOCAL
        ''')

    def test_frozen_import_in_worker(self):
        self.run_script('''
            import _imp
            _imp._override_frozen_modules_for_tests(1)
            assert '__hello__' not in sys.modules
            def action():
                info = _imp.find_frozen('__hello__', withdata=True)
                data, is_package, original = info
                assert not is_package
                assert data.readonly
                assert _imp.get_frozen_object('__hello__', data).co_name == '<module>'
                assert _imp.find_frozen('pep805_no_frozen_module') is None
                import __hello__
                assert __hello__.initialized
                assert __hello__.__shareable__ is threading.Shareable.LOCAL
                assert __import__('__hello__') is __hello__
                import __phello__.spam
                assert __phello__.spam.initialized
                results.put(__hello__.__spec__.origin)
            run(action)
            assert results.get() == 'frozen'
            for name in ('__hello__', '__phello__', '__phello__.spam'):
                try:
                    sys.modules[name]
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('frozen module implicitly shared')
        ''')

    def test_frozen_importer_methods_in_worker(self):
        self.run_script('''
            import _imp
            from test.test_importlib.util import import_importlib
            variants = import_importlib('importlib.machinery')
            importers = tuple(value.FrozenImporter for value in variants.values())
            _imp._override_frozen_modules_for_tests(1)
            def action():
                for importer in importers:
                    assert importer.get_code('__hello__').co_name == '<module>'
                    assert importer.get_source('__hello__') is None
                    assert not importer.is_package('__hello__')
                    assert importer.is_package('__phello__')
                    try:
                        importer.get_code('pep805_no_frozen_module')
                    except ImportError:
                        pass
                    else:
                        raise AssertionError('missing frozen module accepted')
            run(action)
        ''')

    def test_parallel_frozen_code_loading(self):
        self.run_script('''
            import _imp
            _imp._override_frozen_modules_for_tests(1)
            def worker():
                try:
                    for _ in range(25):
                        data, is_package, original = _imp.find_frozen(
                            '__hello__', withdata=True)
                        code = _imp.get_frozen_object('__hello__', data)
                        namespace = {}
                        exec(code, namespace)
                        assert namespace['initialized']
                        assert namespace['TestFrozenUtf8_1'].__doc__ == '\\u00b6'
                    results.put('loaded')
                except BaseException as exc:
                    errors.append((type(exc).__name__, str(exc)))
            threads = [threading.Thread(target=worker,
                                        group=threading.ThreadGroup())
                       for _ in range(4)]
            with threading_helper.start_threads(threads):
                pass
            assert not errors, list(errors)
            assert [results.get() for _ in threads] == ['loaded'] * 4
        ''')

    def test_implementation_namespace_in_worker(self):
        self.run_script('''
            implementation = sys.implementation
            assert implementation.__shareable__ is threading.Shareable.SYNCHRONIZED
            implementation._pep805_foreign = []
            def action():
                assert implementation.name == 'cpython'
                assert type(implementation.__dict__) is SynchronizedDict
                assert implementation.cache_tag.startswith('cpython-')
                implementation._pep805_answer = 42
                for read in (lambda: implementation._pep805_foreign,
                             lambda: implementation.__dict__['_pep805_foreign']):
                    try:
                        read()
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign namespace value exposed')
                assert type(implementation)().__shareable__ is threading.Shareable.LOCAL
            try:
                run(action)
                assert implementation._pep805_answer == 42
            finally:
                del implementation._pep805_foreign
                if hasattr(implementation, '_pep805_answer'):
                    del implementation._pep805_answer
        ''')

    def test_fresh_ast_module_shutdown(self):
        # Keep this process free of test.support imports, which initialize
        # AST metadata in Main before the worker can import it.
        assert_python_ok('-c', textwrap.dedent('''
            import sys
            import threading
            assert '_ast' not in sys.modules
            results = threading.Channel()
            def worker():
                import _ast
                results.put(_ast.__name__)
            thread = threading.Thread(target=worker,
                                      group=threading.ThreadGroup())
            thread.start()
            thread.join(30)
            assert not thread.is_alive()
            assert results.get() == '_ast'
        '''))

    def test_eval_exec_inherited_globals(self):
        self.run_script('''
            shared_constant = 40
            foreign_payload = []
            counter = 0
            def action():
                assert eval('shared_constant + 2') == 42
                namespace = {}
                exec('answer = shared_constant + 2', None, namespace)
                assert namespace['answer'] == 42
                for source in ('foreign_payload', 'globals()'):
                    try:
                        eval(source)
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign global exposed')
                try:
                    exec('global counter; counter = 1')
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign namespace mutated')
            run(action)
            assert counter == 0
        ''')

    def test_shutdown_reuses_foreign_metadata_weakref(self):
        self.run_script('''
            from types import ModuleType
            from weakref import ref
            def action():
                module = ModuleType('pep805_worker_module')
                module.payload = []
                sys.modules[module.__name__] = module
                results.put((module, ref(module)))
            run(action)
            # Retain both until shutdown so the private weak-list builder
            # encounters an existing weakref owned by the worker's group.
            holder = results.get()
            for index in range(2):
                try:
                    holder[index]
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign metadata exposed')
        ''')

    def test_shared_meta_path_finder(self):
        self.run_script('''
            from importlib.machinery import ModuleSpec
            name = 'pep805_custom_finder'
            @freeze
            class Loader:
                def create_module(self, spec):
                    return None
                def exec_module(self, module):
                    module.answer = 42
            @freeze
            class Finder:
                @staticmethod
                def find_spec(fullname, path=None, target=None):
                    if fullname == name:
                        return ModuleSpec(fullname, Loader())
            sys.meta_path.insert(0, Finder)
            def action():
                module = __import__(name)
                assert module.__shareable__ is threading.Shareable.LOCAL
                results.put(module.answer)
            try:
                run(action)
                assert results.get() == 42
            finally:
                sys.meta_path.remove(Finder)
                if name in sys.modules:
                    del sys.modules[name]
        ''')

    def test_foreign_meta_path_finder_rejected(self):
        self.run_script('''
            calls = []
            class Finder:
                def find_spec(self, *args):
                    calls.append(args)
            finder = Finder()
            sys.meta_path.insert(0, finder)
            def action():
                try:
                    __import__('pep805_inaccessible_finder')
                except IllegalThreadAccessException:
                    results.put('denied')
                else:
                    raise AssertionError('foreign finder used')
            try:
                run(action)
                assert results.get() == 'denied'
                assert calls == []
            finally:
                sys.meta_path.remove(finder)
        ''')

    def test_path_hook_cache_ownership(self):
        self.run_script('''
            path = '<pep805 path>'
            calls = threading.Channel()
            def hook(candidate):
                if candidate != path:
                    raise ImportError
                calls.put(candidate)
                return object()
            sys.path_hooks.insert(0, hook)
            def action():
                finder = get_importer(path)
                assert finder.__shareable__ is threading.Shareable.LOCAL
                assert get_importer(path) is finder
            try:
                run(action)
                assert calls.get() == path
                try:
                    get_importer(path)
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign cached finder used')
                try:
                    calls.get()
                except IndexError:
                    pass
                else:
                    raise AssertionError('cached hook called twice')
            finally:
                sys.path_hooks.remove(hook)
                if path in sys.path_importer_cache:
                    del sys.path_importer_cache[path]
        ''', capi=True)

    def test_path_hook_ends_debugger_access(self):
        self.run_script('''
            def producer():
                results.put((object(),))
            run(producer)
            holder = results.get()
            context = sys.monitoring.StopTheWorld
            entered = False
            def hook(path):
                global entered
                context.__exit__(None, None, None)
                entered = False
                return None
            original_hooks = sys.path_hooks
            original_cache = sys.path_importer_cache
            try:
                sys.path_hooks = SynchronizedList([hook])
                sys.path_importer_cache = SynchronizedDict()
                context.__enter__()
                entered = True
                try:
                    get_importer(holder[0])
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign path used after resuming')
            finally:
                if entered:
                    context.__exit__(None, None, None)
                sys.path_hooks = original_hooks
                sys.path_importer_cache = original_cache
        ''', capi=True)


if __name__ == '__main__':
    unittest.main()
