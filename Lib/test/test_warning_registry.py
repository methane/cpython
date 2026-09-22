"""Warning bookkeeping must not acquire the emitting worker's ownership."""

import contextvars
import threading
import unittest
import warnings

from test.support import SHORT_TIMEOUT, threading_helper
from test.support import import_helper


threading_helper.requires_working_threading(module=True)


class WarningRegistryTests(unittest.TestCase):
    def make_emitter(self):
        namespace = SynchronizedDict(__name__='warning_registry_test')
        exec('''def emit():
    def target(value=1):
        return value
    target.__defaults__ = (2,)
    return target()
''', namespace)
        return namespace, namespace['emit']

    def emit_in_worker(self, emit):
        results = threading.Channel()

        def worker(emit, results):
            try:
                emit()
            except IllegalThreadAccessException:
                # Filters, inherited warning contexts and hooks still have
                # their own access rules. A denied lookup must not poison
                # the per-module registry that was created before it.
                results.put('denied')
            else:
                results.put('ok')

        thread = threading.Thread(target=worker, args=(emit, results),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        return results.get()

    def test_worker_created_registry_is_accessible_in_main(self):
        namespace, emit = self.make_emitter()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            self.assertIn(self.emit_in_worker(emit), ('ok', 'denied'))
            registry = namespace['__warningregistry__']
            self.assertIs(type(registry), SynchronizedDict)
            self.assertIs(registry.__shareable__, threading.Shareable.SYNCHRONIZED)
            self.assertEqual(emit(), 2)
            self.assertIs(namespace['__warningregistry__'], registry)

    def test_user_registry_is_not_promoted(self):
        namespace, emit = self.make_emitter()
        registry = {}
        namespace['__warningregistry__'] = registry
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            self.assertEqual(self.emit_in_worker(emit), 'denied')
            self.assertIs(namespace['__warningregistry__'], registry)
            self.assertIs(type(registry), dict)
            self.assertIs(registry.__shareable__, threading.Shareable.LOCAL)
            self.assertEqual(emit(), 2)

    def test_python_implementation_registries(self):
        def check():
            pure = import_helper.import_fresh_module(
                'warnings', fresh=['_py_warnings'], blocked=['_warnings'])
            namespace = {'__name__': 'python_warning_registry_test',
                         'warn': pure.warn}
            exec("def emit(): warn('message', UserWarning)", namespace)
            with pure.catch_warnings(record=True, module=pure) as recorded:
                pure.simplefilter('always')
                namespace['emit']()
            self.assertEqual(len(recorded), 1)
            self.assertIs(type(namespace['__warningregistry__']), SynchronizedDict)
            self.assertIs(type(pure.onceregistry), SynchronizedDict)

        # Each fresh warnings module creates a new ContextVar. Confine its
        # restored default value instead of retaining it in the test runner.
        contextvars.Context().run(check)

    def test_default_once_registry_is_synchronized(self):
        self.assertIs(type(warnings.onceregistry), SynchronizedDict)
        self.assertIs(warnings.onceregistry.__shareable__,
                      threading.Shareable.SYNCHRONIZED)


if __name__ == '__main__':
    unittest.main()
