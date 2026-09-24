"""Native extension imports and module registration across ThreadGroups."""

import textwrap
import unittest

from test.support import import_helper, threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ExtensionImportAccessTests(unittest.TestCase):
    PRELUDE = '''
import sys
import threading
from test.support import threading_helper

results = threading.Channel()
errors = SynchronizedList()

def run(*actions):
    def worker(action):
        try:
            action()
        except BaseException as exc:
            errors.append((type(exc).__name__, str(exc)))
    threads = [threading.Thread(target=worker, args=(action,),
                                group=threading.ThreadGroup())
               for action in actions]
    with threading_helper.start_threads(threads):
        pass
    assert not errors, list(errors)
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_multiphase_import_in_worker(self):
        import_helper.import_module('_testmultiphase')
        self.run_script('''
            assert '_testmultiphase' not in sys.modules
            def action():
                import _testmultiphase as module
                assert module.foo(40, 2) == 42
                assert module.Example().demo('worker') == 'worker'
                assert isinstance(module.error(), Exception)
                assert module.__shareable__ is threading.Shareable.LOCAL
                assert module.Example.__shareable__ is threading.Shareable.LOCAL
                assert __import__('_testmultiphase') is module
            run(action)
            try:
                sys.modules['_testmultiphase']
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('worker module implicitly shared')
        ''')

    def test_singlephase_import_in_worker(self):
        import_helper.import_module('_testsinglephase')
        self.run_script('''
            assert '_testsinglephase' not in sys.modules
            def action():
                import _testsinglephase as module
                assert module.sum(40, 2) == 42
                assert module.look_up_self() is module
                assert module.__shareable__ is threading.Shareable.LOCAL
                assert isinstance(module.error(), Exception)
                assert __import__('_testsinglephase') is module
                # Exercise the legacy cache without changing ownership.
                del sys.modules['_testsinglephase']
                reloaded = __import__('_testsinglephase')
                assert reloaded.int_const == module.int_const
                assert reloaded.sum(40, 2) == 42
                assert reloaded.__shareable__ is threading.Shareable.LOCAL
            run(action)
            try:
                sys.modules['_testsinglephase']
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('legacy module implicitly shared')
        ''')

    def test_parallel_extension_imports(self):
        for name in ('_csv', '_json', '_struct'):
            import_helper.import_module(name)
        self.run_script('''
            def csv_action():
                import _csv
                assert next(_csv.reader(['a,b'])) == ['a', 'b']
                results.put(_csv.__name__)
            def json_action():
                import _json
                assert _json.encode_basestring('worker') == '"worker"'
                results.put(_json.__name__)
            def struct_action():
                import _struct
                assert _struct.unpack('i', _struct.pack('i', 42)) == (42,)
                results.put(_struct.__name__)
            for name in ('_csv', '_json', '_struct'):
                assert name not in sys.modules, name
            run(csv_action, json_action, struct_action)
            assert {results.get() for _ in range(3)} == {'_csv', '_json', '_struct'}
        ''')

    def test_parallel_creation_from_one_definition(self):
        import_helper.import_module('_testmultiphase')
        self.run_script('''
            import _imp
            from importlib.machinery import ModuleSpec, PathFinder
            path = PathFinder.find_spec('_testmultiphase').origin
            assert '_testmultiphase' not in sys.modules
            ready = threading.Barrier(4, timeout=10)
            def action():
                ready.wait()
                for _ in range(25):
                    spec = ModuleSpec('_testmultiphase', None, origin=path)
                    module = _imp.create_dynamic(spec)
                    assert module.__name__ == '_testmultiphase'
                    assert module.__module__ is module
                    assert module.__shareable__ is threading.Shareable.LOCAL
                results.put('created')
            run(action, action, action, action)
            assert [results.get() for _ in range(4)] == ['created'] * 4
        ''')

    def test_native_module_registry(self):
        import_helper.import_module('_testcapi')
        import_helper.import_module('_testinternalcapi')
        self.run_script('''
            import _testcapi
            import _testinternalcapi
            register = _testcapi.module_state_register
            find = _testcapi.module_state_find
            remove = _testcapi.module_state_remove
            for function in (register, find, remove):
                _testinternalcapi.object_declare_synchronized(function)

            assert not find()
            main_module = register()
            try:
                assert find()
                def action():
                    try:
                        find()
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign registry result acquired')
                    local_module = register()
                    assert find()
                    assert local_module.__shareable__ is threading.Shareable.LOCAL
                run(action)
                try:
                    find()
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('worker registry result acquired')
                assert main_module.__shareable__ is threading.Shareable.LOCAL
            finally:
                remove()
            assert not find()
        ''')


if __name__ == '__main__':
    unittest.main()
