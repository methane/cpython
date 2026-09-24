"""Zstandard constructors and their stored input references."""

import textwrap
import unittest

from test.support import import_helper, threading_helper
from test.support.script_helper import assert_python_ok


import_helper.import_module('_zstd')
threading_helper.requires_working_threading(module=True)


class ZstdAccessTests(unittest.TestCase):
    PRELUDE = '''
import _zstd
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

    def test_protected_option_error(self):
        self.run_script('''
            class Index:
                def __index__(self):
                    return 15
            lock = threading.Lock()
            for constructor, key in (
                (_zstd.ZstdCompressor, _zstd.ZSTD_c_windowLog),
                (_zstd.ZstdDecompressor, _zstd.ZSTD_d_windowLogMax),
            ):
                with lock:
                    value = lock.protect(Index())
                    options = {key: value}
                    constructor(options=options)
                try:
                    constructor(options=options)
                except UnprotectedAccessException:
                    pass
                else:
                    raise AssertionError('option access error was lost')
        ''')

    def test_local_dictionary_in_worker(self):
        self.run_script('''
            content = b'abcdefghijklmnopqrstuvwxyz' * 8
            data = b'abcdefghijklmnop' * 100
            dictionary = _zstd.ZstdDict(content, is_raw=True)
            frames = []
            for kind in (0, 1, 2):
                compressor = _zstd.ZstdCompressor(zstd_dict=(dictionary, kind))
                frames.append((kind, compressor.compress(data) + compressor.flush()))
            frames = tuple(frames)
            def action():
                local = _zstd.ZstdDict(content, is_raw=True)
                assert local.__shareable__ is threading.Shareable.LOCAL
                for kind, frame in frames:
                    stream = _zstd.ZstdDecompressor(zstd_dict=(local, kind))
                    assert stream.__shareable__ is threading.Shareable.LOCAL
                    assert stream.decompress(frame + b'extra') == data
                    assert stream.eof
                    assert stream.unused_data == b'extra'
                try:
                    _zstd.ZstdDecompressor().decompress(b'invalid compressed data')
                except _zstd.ZstdError as exc:
                    assert exc.__shareable__ is threading.Shareable.LOCAL
                else:
                    raise AssertionError('invalid stream accepted')
            run(action, action)
        ''')

    def test_foreign_dictionary_and_tag_rejected(self):
        import_helper.import_module('_testinternalcapi')
        self.run_script('''
            from _testinternalcapi import object_declare_synchronized
            dictionary = _zstd.ZstdDict(b'abcdefgh' * 8, is_raw=True)
            foreign_dictionary = dictionary.as_prefix
            class Tag(int):
                pass
            # Share this test dictionary explicitly so the second case
            # reaches the tag, beyond the first tuple element's access check.
            shared_dictionary = _zstd.ZstdDict(b'abcdefgh' * 8, is_raw=True)
            object_declare_synchronized(shared_dictionary)
            foreign_tag = (shared_dictionary, Tag(2))
            def action():
                for argument in (foreign_dictionary, foreign_tag):
                    try:
                        _zstd.ZstdDecompressor(zstd_dict=argument)
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign dictionary tuple member acquired')
            run(action)
        ''')

    def test_foreign_option_key_and_value_rejected(self):
        self.run_script('''
            class Key(int):
                pass
            class Index:
                def __index__(self):
                    return 15
            key = _zstd.ZSTD_d_windowLogMax
            options = (
                SynchronizedDict({Key(key): 15}),
                SynchronizedDict({key: Index()}),
            )
            def action():
                for mapping in options:
                    try:
                        _zstd.ZstdDecompressor(options=mapping)
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign option acquired')
                stream = _zstd.ZstdDecompressor(options={key: 15})
                assert stream.__shareable__ is threading.Shareable.LOCAL
            run(action)
        ''')

    def test_options_snapshot_before_index_callbacks(self):
        self.run_script('''
            class Index:
                def __index__(self):
                    options.clear()
                    return 15
            for constructor, key in (
                (_zstd.ZstdCompressor, _zstd.ZSTD_c_windowLog),
                (_zstd.ZstdDecompressor, _zstd.ZSTD_d_windowLogMax),
            ):
                invalid_key = 999999
                options = {key: Index(), invalid_key: 15}
                try:
                    constructor(options=options)
                except ValueError:
                    pass
                else:
                    raise AssertionError('callback removed an option before validation')
                assert options == {}
        ''')

    def test_concurrent_options_and_parameter_metadata(self):
        self.run_script('''
            key = _zstd.ZSTD_d_windowLogMax
            options = SynchronizedDict({key: 15})
            ready = threading.Barrier(3, timeout=10)
            def action():
                ready.wait()
                for _ in range(200):
                    stream = _zstd.ZstdDecompressor(options=options)
                    assert stream.__shareable__ is threading.Shareable.LOCAL
                results.put('done')
            controller = threading.Thread(target=run, args=(action, action))
            controller.start()
            try:
                ready.wait()
                for _ in range(200):
                    options.clear()
                    options[key] = 15
                    _zstd.set_parameter_types(type('CParameter', (int,), {}),
                                              type('DParameter', (int,), {}))
            finally:
                controller.join()
            assert not errors, list(errors)
            assert [results.get() for _ in range(2)] == ['done', 'done']
        ''')


if __name__ == '__main__':
    unittest.main()
