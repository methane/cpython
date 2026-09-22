"""Native warnings must check and retain references acquired from storage."""

import threading
import unittest
import warnings
import weakref

from test.support import SHORT_TIMEOUT, script_helper, threading_helper


threading_helper.requires_working_threading(module=True)


def make_foreign_filters(kind, results, calls):
    class Action(str):
        pass

    class Line(int):
        pass

    class Entry(tuple):
        pass

    class Matcher:
        def match(self, value, *, calls=calls):
            calls.put('match')
            return True

    class Meta(type):
        def __subclasscheck__(self, value, *, calls=calls):
            calls.put('subclass')
            return True

    class Category(metaclass=Meta):
        pass

    action, message, category, module, line = 'ignore', None, UserWarning, None, 0
    if kind == 'action':
        action = Action(action)
    elif kind == 'message':
        message = Matcher()
    elif kind == 'category':
        category = Category
    elif kind == 'module':
        module = Matcher()
    elif kind == 'line':
        line = Line(line)
    entry = (action, message, category, module, line)
    if kind == 'entry':
        entry = Entry(entry)
    results.put(SynchronizedList((entry,)))


def install_filters(filters):
    if warnings._use_context:
        warnings._get_context()._filters = filters
    else:
        warnings.filters = filters
    warnings._filters_mutated()


def make_foreign_prefix(results):
    class Prefix(str):
        pass

    results.put((Prefix(''),))


def make_foreign_filename_function(results):
    class Filename(str):
        pass

    def emit(warn, level):
        warn('message', stacklevel=level)

    try:
        code = emit.__code__.replace(co_filename=Filename('foreign.py'))
        namespace = SynchronizedDict(__name__='warning_frame_worker')
        results.put(type(emit)(code, namespace))
    except Exception as exc:
        results.put(str(exc))


class WarningFilterAccessTests(unittest.TestCase):
    def test_foreign_frame_filename(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_foreign_filename_function,
                                  args=(results,), group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        emit = results.get()
        self.assertTrue(callable(emit), emit)

        def wrapper(message, *, stacklevel):
            warnings.warn(message, stacklevel=stacklevel)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            for level in (0, 1, 2):
                with self.subTest(path='current', level=level):
                    with self.assertRaises(IllegalThreadAccessException):
                        emit(warnings.warn, level)
            for level in (2, 3):
                with self.subTest(path='caller', level=level):
                    with self.assertRaises(IllegalThreadAccessException):
                        emit(wrapper, level)

    def test_foreign_skip_file_prefix(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_foreign_prefix, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        prefixes = results.get()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with self.assertRaises(IllegalThreadAccessException):
                warnings.warn('message', skip_file_prefixes=prefixes)

    def test_empty_prefix_tuple_reference(self):
        # A tuple subclass is mortal, unlike the built-in empty tuple.
        script_helper.assert_python_ok('-c', '''
import sys
import warnings

class Prefixes(tuple):
    pass

prefixes = Prefixes()
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    before = sys.getrefcount(prefixes)
    warnings.warn('message', skip_file_prefixes=prefixes)
    assert sys.getrefcount(prefixes) == before
''')

    def test_default_action_survives_registry_callback(self):
        class Action(str):
            pass

        class Message(str):
            def __hash__(message):
                warnings.defaultaction = 'ignore'
                warnings.warn_explicit('nested', UserWarning, 'example.py', 1)
                self.assertIsNotNone(reference())
                return str.__hash__(message)

        previous = warnings.defaultaction
        try:
            with warnings.catch_warnings(record=True) as recorded:
                install_filters([])
                warnings.defaultaction = Action('default')
                reference = weakref.ref(warnings.defaultaction)
                warnings.warn_explicit(Message('outer'), UserWarning,
                                       'example.py', 1, registry={})
                self.assertEqual(len(recorded), 1)
                self.assertIsNone(reference())
        finally:
            warnings.defaultaction = previous
            # Restoring the module attribute alone leaves the native cache
            # changed, which affects subsequent fresh imports of _warnings.
            with warnings.catch_warnings(record=True):
                install_filters([])
                try:
                    warnings.warn_explicit('restore default action', UserWarning,
                                           'example.py', 1)
                except UserWarning:
                    pass  # The previous default action may be 'error'.

    def test_once_registry_survives_hash_callback(self):
        class Registry(dict):
            pass

        class Message(str):
            def __hash__(message):
                warnings.onceregistry = {}
                warnings.warn_explicit('nested', UserWarning, 'example.py', 1)
                self.assertIsNotNone(reference())
                return str.__hash__(message)

        previous = warnings.onceregistry
        try:
            with warnings.catch_warnings(record=True) as recorded:
                install_filters([('once', None, UserWarning, None, 0)])
                warnings.onceregistry = Registry()
                reference = weakref.ref(warnings.onceregistry)
                warnings.warn_explicit(Message('outer'), UserWarning,
                                       'example.py', 1)
                self.assertEqual(len(recorded), 2)
                self.assertIsNone(reference())
        finally:
            warnings.onceregistry = previous
            saved = previous.copy()
            try:
                with warnings.catch_warnings(record=True):
                    install_filters([('once', None, UserWarning, None, 0)])
                    warnings.warn_explicit('restore once registry', UserWarning,
                                           'example.py', 1)
            finally:
                previous.clear()
                previous.update(saved)

    def test_matcher_releases_protection(self):
        lock = threading.Lock()
        calls = []

        class Matcher:
            def match(self, value):
                calls.append(value)
                return True

        class Releaser:
            def match(self, value):
                lock.__exit__(None, None, None)
                return True

        denied = False
        with warnings.catch_warnings():
            with self.assertRaises(RuntimeError):
                with lock:
                    module = lock.protect(Matcher())
                    install_filters([('ignore', Releaser(), UserWarning,
                                      module, 0)])
                    try:
                        warnings.warn_explicit('message', UserWarning,
                                               'example.py', 1, registry={})
                    except UnprotectedAccessException:
                        denied = True
        self.assertTrue(denied)
        self.assertEqual(calls, [])

    def test_reentrant_filter_replacement(self):
        script_helper.assert_python_ok('-X', 'context_aware_warnings=0', '-c', '''
import warnings
import weakref

class Filters(list):
    pass

class Matcher:
    def match(self, value):
        warnings.filters = [('ignore', None, UserWarning, None, 0)]
        warnings._filters_mutated()
        warnings.warn_explicit('nested', UserWarning, 'example.py', 1)
        assert reference() is not None
        return True

with warnings.catch_warnings():
    warnings.filters = Filters([('ignore', Matcher(), UserWarning, None, 0)])
    reference = weakref.ref(warnings.filters)
    warnings._filters_mutated()
    warnings.warn_explicit('outer', UserWarning, 'example.py', 1)
    assert reference() is None
''')

    def test_matcher_releases_filter_list_protection(self):
        lock = threading.Lock()

        class Releaser:
            def match(self, value):
                lock.__exit__(None, None, None)
                return False

        denied = False
        with warnings.catch_warnings():
            with self.assertRaises(RuntimeError):
                with lock:
                    filters = lock.protect([
                        ('ignore', Releaser(), UserWarning, None, 0)])
                    install_filters(filters)
                    try:
                        warnings.warn_explicit('message', UserWarning,
                                               'example.py', 1, registry={})
                    except UnprotectedAccessException:
                        denied = True
        self.assertTrue(denied)

    def test_foreign_filter_references(self):
        for kind in ('entry', 'action', 'message', 'category', 'module', 'line'):
            with self.subTest(kind=kind):
                results = threading.Channel()
                calls = threading.Channel()
                thread = threading.Thread(target=make_foreign_filters,
                                          args=(kind, results, calls),
                                          group=threading.ThreadGroup())
                thread.start()
                thread.join(SHORT_TIMEOUT)
                self.assertFalse(thread.is_alive())
                filters = results.get()
                with warnings.catch_warnings():
                    install_filters(filters)
                    with self.assertRaises(IllegalThreadAccessException):
                        warnings.warn_explicit('message', UserWarning,
                                               'example.py', 1, registry={})
                with self.assertRaises(IndexError):
                    calls.get()


if __name__ == '__main__':
    unittest.main()
