"""ZIP import caches and loaders used by different ThreadGroups."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ZipImportAccessTests(unittest.TestCase):
    PRELUDE = '''
import os
import sys
import tempfile
import threading
import zipimport
from importlib.machinery import PathFinder
from test.support import threading_helper
from zipfile import ZipFile

results = threading.Channel()
errors = SynchronizedList()

def run(*actions):
    def worker(action):
        try:
            action()
        except BaseException as exc:
            frames = []
            tb = exc.__traceback__
            while tb is not None:
                frames.append((tb.tb_frame.f_code.co_name, tb.tb_lineno))
                tb = tb.tb_next
            errors.append((type(exc).__name__, str(exc), tuple(frames)))
    threads = [threading.Thread(target=worker, args=(action,),
                                group=threading.ThreadGroup())
               for action in actions]
    with threading_helper.start_threads(threads):
        pass
    assert not errors, list(errors)
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_source_with_new_importer(self):
        self.check_source(warm_cache=False)

    def test_source_with_main_cached_importer(self):
        self.check_source(warm_cache=True)

    def check_source(self, *, warm_cache):
        self.run_script(f'''
            warm_cache = {warm_cache!r}
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'modules.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('pep805_zipped.py', 'answer = 42\\n')
                if warm_cache:
                    assert PathFinder.find_spec('pep805_zipped', [path])
                sys.path.insert(0, path)
                def action():
                    import pep805_zipped
                    assert pep805_zipped.answer == 42
                    assert pep805_zipped.__shareable__ is threading.Shareable.LOCAL
                    loader = pep805_zipped.__loader__
                    assert loader.__shareable__ is threading.Shareable.SYNCHRONIZED
                    assert loader.get_source('pep805_zipped') == 'answer = 42\\n'
                run(action)
                try:
                    sys.modules['pep805_zipped']
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('worker module implicitly shared')
                del sys.modules['pep805_zipped']
                run(action)
        ''')

    def test_packages_in_worker(self):
        self.run_script('''
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'packages.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('pep805_zip_package/__init__.py',
                                     'initialized = True\\n')
                    for name in ('pep805_zip_package', 'pep805_zip_namespace'):
                        archive.writestr(name + '/child.py', 'answer = 42\\n')
                sys.path.insert(0, path)
                def action():
                    import pep805_zip_package.child as regular
                    import pep805_zip_namespace.child as namespace
                    assert regular.answer == namespace.answer == 42
                    assert sys.modules['pep805_zip_package'].initialized
                run(action)
        ''')

    def test_bytecode_in_worker(self):
        self.run_script('''
            from importlib._bootstrap_external import (
                _code_to_hash_pyc, _code_to_timestamp_pyc)
            from importlib.util import source_hash
            import time
            source = b'answer = 42\\n'
            code = compile(source, 'zipped.py', 'exec')
            stamp = (2026, 1, 2, 3, 4, 6)
            mtime = int(time.mktime(stamp + (0, 0, -1)))
            from zipfile import ZipInfo
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'bytecode.zip')
                with ZipFile(path, 'w') as archive:
                    for name, pyc in (
                        ('pep805_zip_timestamp',
                         _code_to_timestamp_pyc(code, mtime, len(source))),
                        ('pep805_zip_hash',
                         _code_to_hash_pyc(code, source_hash(source), checked=True)),
                    ):
                        archive.writestr(ZipInfo(name + '.py', stamp), source)
                        archive.writestr(name + '.pyc', pyc)
                    archive.writestr('pep805_zip_sourceless.pyc',
                                     _code_to_timestamp_pyc(code))
                sys.path.insert(0, path)
                def action():
                    for name in ('pep805_zip_timestamp', 'pep805_zip_hash',
                                 'pep805_zip_sourceless'):
                        module = __import__(name)
                        assert module.answer == 42
                        assert module.__file__.endswith('.pyc')
                run(action)
        ''')

    def test_concurrent_cache_refresh(self):
        self.run_script('''
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'refresh.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('pep805_zip_refresh.py', 'answer = 42\\n')
                    archive.writestr('data.txt', b'worker data')
                finder = zipimport.zipimporter(path)
                ready = threading.Barrier(4, timeout=10)
                def action():
                    ready.wait()
                    for _ in range(20):
                        finder.invalidate_caches()
                        assert finder.find_spec('pep805_zip_refresh') is not None
                        namespace = {}
                        exec(finder.get_code('pep805_zip_refresh'), namespace)
                        assert namespace['answer'] == 42
                        assert finder.get_data('data.txt') == b'worker data'
                run(action, action, action, action)
        ''')

    def test_subclass_stays_local(self):
        self.run_script('''
            class CustomImporter(zipimport.zipimporter):
                pass
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'subclass.zip')
                with ZipFile(path, 'w'):
                    pass
                finder = CustomImporter(path)
                assert finder.__shareable__ is threading.Shareable.LOCAL
                def action():
                    try:
                        finder.find_spec('missing')
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('importer subclass implicitly shared')
                run(action)
        ''')

    def test_foreign_cache_entry_rejected(self):
        self.run_script('''
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'foreign.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('data.txt', b'data')
                finder = zipimport.zipimporter(path)
                cache = zipimport._zip_directory_cache
                entries = cache[path]
                original = entries['data.txt']
                def action():
                    try:
                        finder.get_data('data.txt')
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign directory entry acquired')
                entries['data.txt'] = list(original)
                run(action)
                entries['data.txt'] = original
                cache[path] = dict(entries)
                run(action)
        ''')

    def test_reinitialize_importer_and_reload_module(self):
        self.run_script('''
            from importlib import reload
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'reinitialize.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('data.txt', b'root')
                    archive.writestr('subdir/data.txt', b'child')
                finder = zipimport.zipimporter(path)
                finder.__init__(path + os.sep + 'subdir')
                assert finder.prefix == 'subdir' + os.sep
                def action():
                    assert finder.get_data('data.txt') == b'root'
                    assert finder.get_data('subdir/data.txt') == b'child'
                run(action)
                assert reload(zipimport) is zipimport
                def action():
                    reloaded = zipimport.zipimporter(path)
                    assert reloaded.get_data('data.txt') == b'root'
                run(action)
        ''')


if __name__ == '__main__':
    unittest.main()
