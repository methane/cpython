"""Access checks at the public sequence and subscription C API boundaries."""

import os
import sys
import textwrap
import threading
import types
import unittest
import weakref

from test.support import gc_collect, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


capi = import_module('_testlimitedcapi')


@freeze
class PythonSequence:
    def __init__(self, items):
        self.items = list(items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


class SequenceAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_container_foreign_comparison_operand(self):
        class ForeignFloat(float):
            pass
        value = ForeignFloat(42)
        self.assertIs(value.__shareable__, threading.Shareable.LOCAL)
        results = threading.Channel()
        def worker(payload):
            with sys.monitoring.StopTheWorld:
                items = [payload[0]]
                sequence = (payload[0],)
                mapping = {payload[0]: 1}
                values = {payload[0]}
            operations = (
                lambda: 42.0 in items,
                lambda: items.index(42.0),
                lambda: items.count(42.0),
                lambda: items == [42.0],
                lambda: 42.0 in sequence,
                lambda: sequence == (42.0,),
                lambda: 42.0 in values,
                lambda: mapping[42.0],
                lambda: items.remove(42.0),
            )
            for operation in operations:
                try:
                    operation()
                except IllegalThreadAccessException:
                    results.put(True)
                else:
                    results.put(False)
            results.put(len(items))
        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get() for _ in range(9)], [True] * 9)
        self.assertEqual(results.get(), 1)

    @threading_helper.requires_working_threading()
    def test_iterator_result_access(self):
        value = object()
        results = threading.Channel()

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                sequences = ([payload[0]], (payload[0],))
            denied = 0
            for sequence in sequences:
                for iterator in (iter(sequence), reversed(sequence)):
                    try:
                        next(iterator)
                    except IllegalThreadAccessException:
                        denied += 1
            results.put(denied)

        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 4)

    def test_native_comparison_result_access(self):
        native = import_module('_testcapi')
        for factory in (threading.Lock, threading.RLock):
            for as_bool in (False, True):
                with self.subTest(lock=factory, as_bool=as_bool):
                    api = (native.object_richcomparebool if as_bool
                           else native.object_richcompare_in_tuple)
                    lock = factory()
                    with lock:
                        value = lock.protect([42])
                        receiver = native.NativeRichCompareResult((value,))
                        result = api(receiver, None, 2)
                        if as_bool:
                            self.assertEqual(result, 1)
                        else:
                            self.assertIs(result[0], value)
                        del result
                    with self.assertRaises(UnprotectedAccessException):
                        api(receiver, None, 2)

    def test_comparison_notimplemented_lifetime(self):
        native = import_module('_testcapi')
        invoke = self.native_invoker()
        for factory in (threading.Lock, threading.RLock):
            for mode in ('left', 'subclass', 'right'):
                with self.subTest(lock=factory, mode=mode):
                    lock = factory()
                    calls = []
                    class Other:
                        def __eq__(self, other):
                            calls.append('eq')
                            lock.__exit__(None, None, None)
                            return NotImplemented
                    class Subclass(dict):
                        __eq__ = Other.__eq__
                    with lock:
                        value = lock.protect({1: 2})
                    lock.__enter__()
                    try:
                        if mode == 'left':
                            operands = (Other(), value, 2)
                        elif mode == 'subclass':
                            operands = (value, Subclass({1: 2}), 2)
                        else:
                            operands = (value, Other(), 2)
                        with self.assertRaises(UnprotectedAccessException):
                            invoke(native.object_richcompare, operands)
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, ['eq'])
                    with lock:
                        self.assertEqual(dict(value), {1: 2})

    def test_list_comparison_callback_lifetime(self):
        operations = ('contains', 'index', 'count', 'remove', 'equal', 'equal_right')
        for factory in (threading.Lock, threading.RLock):
            for operation in operations:
                for raises in (False, True):
                    with self.subTest(lock=factory, operation=operation, raises=raises):
                        lock = factory()
                        calls = []
                        class Element:
                            def __eq__(self, other):
                                calls.append('eq')
                                lock.__exit__(None, None, None)
                                if raises:
                                    raise LookupError('comparison failed')
                                return operation not in ('contains', 'index')
                        element = Element()
                        with lock:
                            values = lock.protect([element, 42])
                        lock.__enter__()
                        try:
                            error = LookupError if raises else UnprotectedAccessException
                            with self.assertRaises(error) as caught:
                                if operation == 'contains':
                                    99 in values
                                elif operation == 'equal':
                                    values == [99, 42]
                                elif operation == 'equal_right':
                                    [99, 42] == values
                                else:
                                    getattr(values, operation)(99)
                            if raises:
                                self.assertEqual(str(caught.exception), 'comparison failed')
                        finally:
                            if lock.locked():
                                lock.__exit__(None, None, None)
                        self.assertEqual(calls, ['eq'])
                        with lock:
                            self.assertEqual(len(values), 2)
                            self.assertIs(values[0], element)
                            self.assertEqual(values[1], 42)

    def test_list_comparison_finalizer_lifetime(self):
        operations = ('contains', 'index', 'count', 'remove', 'equal', 'equal_right')
        for factory in (threading.Lock, threading.RLock):
            for operation in operations:
                with self.subTest(lock=factory, operation=operation):
                    lock = factory()
                    calls = []
                    class Element:
                        def __eq__(self, other):
                            calls.append('eq')
                            values.clear()
                            return operation in ('equal', 'equal_right')
                        def __del__(self):
                            calls.append('del')
                            lock.__exit__(None, None, None)
                    with lock:
                        values = lock.protect([Element()])
                    lock.__enter__()
                    try:
                        with self.assertRaises(UnprotectedAccessException):
                            if operation == 'contains':
                                99 in values
                            elif operation == 'equal':
                                values == [99]
                            elif operation == 'equal_right':
                                [99] == values
                            else:
                                getattr(values, operation)(99)
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, ['eq', 'del'])
                    with lock:
                        self.assertEqual(len(values), 0)

    def test_list_index_bounds_callback_lifetime(self):
        for factory in (threading.Lock, threading.RLock):
            for stop in (False, True):
                with self.subTest(lock=factory, stop=stop):
                    lock = factory()
                    class Bound:
                        def __index__(self):
                            lock.__exit__(None, None, None)
                            return -1
                    with lock:
                        values = lock.protect([42])
                    lock.__enter__()
                    try:
                        with self.assertRaises(UnprotectedAccessException):
                            if stop:
                                values.index(99, 0, Bound())
                            else:
                                values.index(42, Bound())
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)

    def test_list_index_callback_lifetime(self):
        self.check_list_index_callback_lifetime('get')

    def test_list_setindex_callback_lifetime(self):
        self.check_list_index_callback_lifetime('set')

    def test_list_delindex_callback_lifetime(self):
        self.check_list_index_callback_lifetime('del')

    def check_list_index_callback_lifetime(self, operation):
        invoke = self.native_invoker()
        api = getattr(capi, 'object_' + operation + 'item')
        for factory in (threading.Lock, threading.RLock):
            for kind in ('index', 'negative', 'start', 'stop', 'step', 'extended'):
                with self.subTest(lock=factory, kind=kind):
                    lock = factory()
                    calls = []
                    class Index:
                        def __index__(self):
                            calls.append(kind)
                            lock.__exit__(None, None, None)
                            if kind == 'negative':
                                return -1
                            return 2 if kind == 'extended' else 1
                    index = Index()
                    if kind == 'start':
                        index = slice(index, None)
                    elif kind == 'stop':
                        index = slice(None, index)
                    elif kind in ('step', 'extended'):
                        index = slice(None, None, index)
                    with lock:
                        value = lock.protect([42, 43, 44])
                    lock.__enter__()
                    try:
                        # C wraps the result to avoid hiding a missing native
                        # lifetime check behind the interpreter's result check.
                        with self.assertRaises(UnprotectedAccessException):
                            args = (value, index)
                            if operation == 'set':
                                replacement = ([99, 100] if kind == 'extended'
                                               else [99])
                                if kind in ('index', 'negative'):
                                    replacement = 99
                                args += (replacement,)
                            invoke(api, args)
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, [kind])
                    with lock:
                        self.assertEqual(list(value), [42, 43, 44])

    def test_list_slice_iterable_callback_lifetime(self):
        invoke = self.native_invoker()
        for factory in (threading.Lock, threading.RLock):
            for step in (1, 2):
                with self.subTest(lock=factory, step=step):
                    lock = factory()
                    calls = []
                    class Values:
                        def __iter__(self):
                            calls.append('iter')
                            lock.__exit__(None, None, None)
                            return iter([99] * (3 if step == 1 else 2))
                    with lock:
                        value = lock.protect([42, 43, 44])
                    lock.__enter__()
                    try:
                        with self.assertRaises(UnprotectedAccessException):
                            invoke(capi.object_setitem,
                                   (value, slice(None, None, step), Values()))
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, ['iter'])
                    with lock:
                        self.assertEqual(list(value), [42, 43, 44])

    def test_list_binary_slice_callback_lifetime(self):
        def read(value, start, stop):
            return value[start:stop]
        for factory in (threading.Lock, threading.RLock):
            for at_start in (False, True):
                with self.subTest(lock=factory, at_start=at_start):
                    lock = factory()
                    class Index:
                        def __index__(self):
                            lock.__exit__(None, None, None)
                            return 1
                    with lock:
                        value = lock.protect([42, 43, 44])
                    lock.__enter__()
                    try:
                        start, stop = (Index(), 3) if at_start else (0, Index())
                        with self.assertRaises(UnprotectedAccessException):
                            read(value, start, stop)
                    finally:
                        if lock.locked():
                            lock.__exit__(None, None, None)

    def test_list_slice_source_callback_lifetime(self):
        invoke = self.native_invoker()
        for factory in (threading.Lock, threading.RLock):
            with self.subTest(lock=factory):
                destination_lock = factory()
                source_lock = factory()
                class Index:
                    def __index__(self):
                        source_lock.__exit__(None, None, None)
                        return 0
                with destination_lock, source_lock:
                    destination = destination_lock.protect([42, 43])
                    source = source_lock.protect([99, 100])
                with destination_lock:
                    source_lock.__enter__()
                    try:
                        with self.assertRaises(UnprotectedAccessException):
                            invoke(capi.object_setitem,
                                   (destination, slice(Index(), None), source))
                    finally:
                        if source_lock.locked():
                            source_lock.__exit__(None, None, None)
                    self.assertEqual(list(destination), [42, 43])

    # Foreign values travel inside immutable holders. Test setup may use
    # StopTheWorld, but the operations under test must run outside it.
    def shared_getter(self, name):
        # These wrappers call the public acquisition APIs under test and
        # have no mutable native state of their own.
        getter = getattr(capi, name)
        internal = import_module('_testinternalcapi')
        internal.object_declare_synchronized(getter)
        return getter

    def native_invoker(self):
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        import_module('_testinternalcapi').object_declare_synchronized(invoke)
        return invoke

    @threading_helper.requires_working_threading()
    def test_known_hash_dictionary_access(self):
        invoke = self.native_invoker()
        internal = import_module('_testinternalcapi')
        getter = internal.dict_getitem_knownhash
        internal.object_declare_synchronized(getter)
        class Payload:
            pass

        def worker(payload, factory, results):
            with sys.monitoring.StopTheWorld:
                mapping = factory(value=payload[0], shared=42)
            try:
                invoke(getter, (mapping, 'value', hash('value')))
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            results.put(getter(mapping, 'shared', hash('shared')))

        for factory in (dict, frozendict, SynchronizedDict):
            with self.subTest(factory=factory):
                value = Payload()
                reference = weakref.ref(value)
                mapping = factory(value=value, shared=42)
                self.assertIs(getter(
                    mapping, 'value', hash('value')), value)
                del value
                results = threading.Channel()

                thread = threading.Thread(
                    target=worker,
                    args=((mapping['value'],), factory, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                self.assertTrue(results.get())
                self.assertEqual(results.get(), 42)
                self.assertIsNotNone(reference())
                del mapping
                gc_collect()
                self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_counter_preserves_access_error(self):
        from collections import Counter, _count_elements
        internal = import_module('_testinternalcapi')
        internal.object_declare_synchronized(_count_elements)
        # Opt in the Python class namespace and stateless native helper;
        # each worker still constructs and owns its Counter instance.
        if Counter.__shareable__ is threading.Shareable.LOCAL:
            type.synchronize(Counter)
        class Count:
            def __add__(self, other):
                raise AssertionError('inaccessible count was used')

        foreign = Count()
        results = threading.Channel()
        def worker(payload):
            counts = Counter()
            with sys.monitoring.StopTheWorld:
                counts['value'] = payload[0]
            try:
                counts.update(['value'])
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            results.put(len(counts) == 1 and 'value' in counts)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_suppressed_dictionary_access_errors(self):
        invoke = self.native_invoker()
        class Payload:
            pass

        def worker(payload, factory, getter, key, results):
            with sys.monitoring.StopTheWorld:
                mapping = factory(value=payload[0])
            reported = []
            def hook(event):
                reported.append(event.exc_type is IllegalThreadAccessException)
            previous = sys.unraisablehook
            sys.unraisablehook = hook
            try:
                result = invoke(getter, (mapping, key))
                results.put(result == (KeyError,))
                results.put(reported == [True])
            finally:
                sys.unraisablehook = previous

        for factory in (dict, frozendict, SynchronizedDict):
            for getter, key in ((self.shared_getter('dict_getitem'), 'value'),
                                (self.shared_getter('dict_getitemstring'), b'value')):
                with self.subTest(factory=factory, getter=getter):
                    value = Payload()
                    reference = weakref.ref(value)
                    mapping = factory(value=value)
                    self.assertIs(getter(mapping, key), value)
                    del value
                    results = threading.Channel()

                    thread = threading.Thread(
                        target=worker,
                        args=((mapping['value'],), factory, getter, key, results),
                        group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    self.assertTrue(results.get())
                    self.assertTrue(results.get())
                    self.assertIsNotNone(reference())
                    del mapping
                    gc_collect()
                    self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_subscription_results_and_lifetime(self):
        invoke = self.native_invoker()
        class Payload:
            pass

        full_capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        getters = (capi.object_getitem, capi.mapping_getitemstring,
                   full_capi.mapping_getoptionalitem,
                   full_capi.mapping_getoptionalitemstring)
        def worker(payload, factory, getter, results):
            with sys.monitoring.StopTheWorld:
                mapping = factory({'value': payload[0], 'shared': 42})
            denied = 0
            for _ in range(20):
                try:
                    invoke(getter, (mapping, 'value'))
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)
            results.put(getter(mapping, 'shared'))

        for factory in (dict, frozendict, SynchronizedDict, types.MappingProxyType):
            factory_getters = getters
            if factory is not types.MappingProxyType:
                factory_getters += (full_capi.dict_getitemref,
                                    full_capi.dict_getitemstringref,
                                    capi.dict_getitemwitherror)
            for getter in factory_getters:
                internal.object_declare_synchronized(getter)
                with self.subTest(factory=factory, getter=getter):
                    value = Payload()
                    ref = weakref.ref(value)
                    mapping = factory({'value': value, 'shared': 42})
                    self.assertIs(getter(mapping, 'value'), value)
                    del value
                    results = threading.Channel()
                    thread = threading.Thread(
                        target=worker,
                        args=((mapping['value'],), factory, getter, results),
                        group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    self.assertEqual(results.get(), 20)
                    self.assertEqual(results.get(), 42)
                    self.assertIsNotNone(ref())
                    del mapping
                    gc_collect()
                    self.assertIsNone(ref())

    def test_optional_subscription_missing_and_errors(self):
        full_capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        class Missing:
            def __getitem__(self, key):
                raise KeyError(key)
        class Broken:
            def __getitem__(self, key):
                raise ValueError('lookup failed')
        for getter in (full_capi.mapping_getoptionalitem,
                       full_capi.mapping_getoptionalitemstring):
            for mapping in ({}, frozendict(), SynchronizedDict(), Missing()):
                self.assertIs(getter(mapping, 'missing'), KeyError)
            with self.assertRaisesRegex(ValueError, 'lookup failed'):
                getter(Broken(), 'key')

    @threading_helper.requires_working_threading()
    def test_module_dir_preserves_access_error(self):
        class Directory:
            def __call__(self):
                raise AssertionError('inaccessible __dir__ was called')

        module = types.ModuleType('borrowed_lookup_access')
        module.__dir__ = Directory()
        module.synchronize()
        results = threading.Channel()

        def worker():
            try:
                dir(module)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_sqlite_adapter_preserves_access_error(self):
        sqlite3 = import_module('sqlite3')
        connect = sqlite3.connect
        @freeze
        class Payload:
            pass
        class Adapter:
            def __call__(self, value):
                raise AssertionError('inaccessible adapter was called')

        sqlite3.register_adapter(Payload, Adapter())
        self.addCleanup(sqlite3.adapters.pop, (Payload, sqlite3.PrepareProtocol))
        results = threading.Channel()
        def worker():
            # The extension's connection factory is local to the importing
            # group. Set up a worker-owned connection while paused, then test
            # adapter access with normal ownership checks enabled.
            with sys.monitoring.StopTheWorld:
                connection = connect(':memory:')
            try:
                try:
                    connection.execute('SELECT ?', (Payload(),))
                except IllegalThreadAccessException:
                    results.put(True)
                else:
                    results.put(False)
            finally:
                connection.close()
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_custom_subscription_results(self):
        getitem = self.shared_getter('object_getitem')
        invoke = self.native_invoker()
        foreign = []
        results = threading.Channel()
        def worker(payload):
            class Subscription:
                def __getitem__(self, key):
                    if key == 'fresh':
                        return []
                    return self.value
            class ClassSubscription:
                @classmethod
                def __class_getitem__(cls, key):
                    if key == 'fresh':
                        return []
                    return cls.value

            obj = Subscription()
            with sys.monitoring.StopTheWorld:
                obj.value = payload[0]
                ClassSubscription.value = payload[0]
            for obj in (obj, ClassSubscription):
                try:
                    invoke(getitem, (obj, 'foreign'))
                except IllegalThreadAccessException:
                    results.put(True)
                else:
                    results.put(False)
                value = getitem(obj, 'fresh')
                results.put(value == [] and
                            value.__shareable__ is threading.Shareable.LOCAL)
        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get() for _ in range(4)], [True] * 4)

    def test_subscription_errors(self):
        class Subscription:
            def __getitem__(self, key):
                raise ValueError('subscription failure')
        class ClassSubscription:
            @classmethod
            def __class_getitem__(cls, key):
                raise ValueError('class subscription failure')
        for obj, message in ((Subscription(), '^subscription failure$'),
                             (ClassSubscription, '^class subscription failure$')):
            with self.assertRaisesRegex(ValueError, message):
                capi.object_getitem(obj, 0)
        with self.assertRaises(KeyError):
            capi.object_getitem({}, 'missing')

    @threading_helper.requires_working_threading()
    def test_c_import_preserves_access_error(self):
        import _testinternalcapi as internal

        class ImportHook:
            def __call__(self, *args):
                raise AssertionError('inaccessible import hook was called')

        importer = capi.PyImport_Import
        internal.object_declare_synchronized(importer)
        namespace = SynchronizedDict({
            '__builtins__': SynchronizedDict(__import__=ImportHook()),
            'native_import': importer,
        })
        exec("def import_module(): return native_import('sys')", namespace)
        import_module = namespace['import_module']
        results = threading.Channel()
        def worker():
            try:
                import_module()
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    def getters(self):
        list_getitem = self.shared_getter('list_getitem')
        list_get_item_ref = self.shared_getter('list_get_item_ref')
        tuple_getitem = self.shared_getter('tuple_getitem')
        sequence_getitem = self.shared_getter('sequence_getitem')
        return ((list, list_getitem), (list, list_get_item_ref),
                (tuple, tuple_getitem), (list, sequence_getitem),
                (tuple, sequence_getitem), (PythonSequence, sequence_getitem))

    def test_same_group_and_index_errors(self):
        value = []
        for factory, getter in self.getters():
            with self.subTest(getter=getter):
                container = factory([value])
                self.assertIs(getter(container, 0), value)
                if getter is capi.sequence_getitem:
                    self.assertIs(getter(container, -1), value)
                    # The generic API normalizes once; a Python __getitem__
                    # implementation may normalize again when delegating.
                    negative = -3
                else:
                    negative = -1
                for index in (negative, 1):
                    with self.assertRaises(IndexError):
                        getter(container, index)

    def test_list_c_api_protected_elements(self):
        for factory in (threading.Lock, threading.RLock):
            for replace in (False, True):
                with self.subTest(lock=factory, replace=replace):
                    lock = factory()
                    items = [None] if replace else []
                    with lock:
                        value = lock.protect([])
                        if replace:
                            capi.list_setitem(items, 0, value)
                        else:
                            capi.list_append(items, value)
                    # The local container remains accessible; acquiring its
                    # stored reference requires the protecting context.
                    self.assertEqual(capi.list_size(items), 1)
                    for getter in (capi.list_getitem, capi.list_get_item_ref):
                        with self.assertRaises(UnprotectedAccessException):
                            getter(items, 0)
                        with lock:
                            self.assertIs(getter(items, 0), value)

    def test_tuple_c_api_protected_elements(self):
        for factory in (threading.Lock, threading.RLock):
            for replace in (False, True):
                with self.subTest(lock=factory, replace=replace):
                    lock = factory()
                    with lock:
                        value = lock.protect([])
                        if replace:
                            items = capi.tuple_setitem((42,), 0, value)
                        else:
                            items = capi.tuple_pack(1, value)
                    self.assertEqual(capi.tuple_size(items), 1)
                    with self.assertRaises(UnprotectedAccessException):
                        capi.tuple_getitem(items, 0)
                    # The helper copies the input through PyTuple_GetItem;
                    # that acquisition error must survive its cleanup.
                    with self.assertRaises(UnprotectedAccessException):
                        capi.tuple_setitem(items, 0, 42)
                    with lock:
                        self.assertIs(capi.tuple_getitem(items, 0), value)

    @threading_helper.requires_working_threading()
    def test_foreign_elements_and_reference_lifetime(self):
        class Payload:
            pass

        invoke = self.native_invoker()
        def worker(payload, factory, getter, results):
            with sys.monitoring.StopTheWorld:
                container = factory([payload[0]])
            denied = 0
            for _ in range(20):
                try:
                    invoke(getter, (container, 0))
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        for factory, getter in self.getters():
            with self.subTest(getter=getter):
                value = Payload()
                ref = weakref.ref(value)
                container = factory([value])
                del value
                results = threading.Channel()
                thread = threading.Thread(
                    target=worker, args=((container[0],), factory, getter, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                self.assertEqual(results.get(), 20)
                self.assertIsNotNone(ref())
                del container
                gc_collect()
                # Borrowed failures must not steal; owned failures must release.
                self.assertIsNone(ref())

    @threading_helper.requires_working_threading()
    def test_foreign_list_and_tuple_containers(self):
        """Container APIs reject a foreign list or tuple before reading it."""
        invoke = self.native_invoker()
        internal = import_module('_testinternalcapi')
        list_apis = (
            (capi.list_size, ()),
            (capi.list_getitem, (0,)),
            (capi.list_get_item_ref, (0,)),
            (capi.list_getslice, (0, 1)),
            (capi.list_astuple, ()),
            (capi.list_sort, ()),
            (capi.list_reverse, ()),
        )
        tuple_apis = (
            (capi.tuple_size, ()),
            (capi.tuple_getitem, (0,)),
            (capi.tuple_getslice, (0, 1)),
        )
        for api, unused in list_apis + tuple_apis:
            internal.object_declare_synchronized(api)

        foreign_list = [1]
        class LocalTuple(tuple):
            pass
        foreign_tuple = LocalTuple((1,))
        results = threading.Channel()

        def worker(payload):
            # Build argument tuples while stopped so the foreign container can
            # be passed through the raw C-call test hook unchanged.
            with sys.monitoring.StopTheWorld:
                list_args = tuple((payload[0],) + extra
                                  for _, extra in list_apis)
                tuple_args = tuple((payload[1],) + extra
                                   for _, extra in tuple_apis)
            denied = 0
            missing = []
            for (api, _), args in zip(list_apis, list_args):
                try:
                    invoke(api, args)
                except IllegalThreadAccessException:
                    denied += 1
                else:
                    missing.append(api.__name__)
            for (api, _), args in zip(tuple_apis, tuple_args):
                try:
                    invoke(api, args)
                except IllegalThreadAccessException:
                    denied += 1
                else:
                    missing.append(api.__name__)
            results.put((denied, tuple(missing)))

        thread = threading.Thread(target=worker,
                                  args=((foreign_list, foreign_tuple),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        denied, missing = results.get()
        self.assertEqual((denied, missing),
                         (len(list_apis) + len(tuple_apis), ()))

    @threading_helper.requires_working_threading()
    def test_shared_elements(self):
        list_getitem = self.shared_getter('list_getitem')
        list_get_item_ref = self.shared_getter('list_get_item_ref')
        tuple_getitem = self.shared_getter('tuple_getitem')
        sequence_getitem = self.shared_getter('sequence_getitem')
        class Frozen:
            pass

        values = (42, 'text', ([],), freeze(Frozen()), threading.Channel())
        results = threading.Channel()
        def worker():
            # Exercise borrowed and owned reference APIs independently.
            items = list(values)
            tuple_items = tuple(values)
            sequence = PythonSequence(values)
            count = 0
            for index, value in enumerate(values):
                count += list_getitem(items, index) is value
                count += list_get_item_ref(items, index) is value
                count += tuple_getitem(tuple_items, index) is value
                count += sequence_getitem(items, index) is value
                count += sequence_getitem(tuple_items, index) is value
                count += sequence_getitem(sequence, index) is value
            results.put(count)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(values) * len(self.getters()))

    @threading_helper.requires_working_threading()
    def test_function_doc_constant_access_failure(self):
        def template():
            """A docstring sets CO_HAS_DOCSTRING."""
            return 42

        make_function = types.FunctionType
        payload = []
        code = template.__code__.replace(
            co_consts=(payload,) + template.__code__.co_consts[1:])
        results = threading.Channel()
        def worker():
            assert make_function(template.__code__, {})() == 42
            try:
                make_function(code, {})
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        func = types.FunctionType(code, {})
        self.assertIsNone(func.__doc__)
        self.assertEqual(func(), 42)

    def test_generic_callback_errors(self):
        class BadLength:
            def __len__(self):
                raise KeyError('length failure')
            def __getitem__(self, index):
                raise ValueError('item failure')

        with self.assertRaisesRegex(KeyError, 'length failure'):
            capi.sequence_getitem(BadLength(), -1)
        with self.assertRaisesRegex(ValueError, 'item failure'):
            capi.sequence_getitem(BadLength(), 0)
        with self.assertRaisesRegex(ValueError, 'item failure'):
            capi.sequence_getslice(BadLength(), 0, 1)

    @threading_helper.requires_working_threading()
    def test_generic_slice_result_access(self):
        getslice = self.shared_getter('sequence_getslice')
        invoke = self.native_invoker()
        getitem = self.shared_getter('list_get_item_ref')
        class Payload:
            pass
        value = Payload()
        ref = weakref.ref(value)
        results = threading.Channel()
        def worker(payload):
            class CustomSlice:
                def __getitem__(self, index):
                    return self.value
            denied = 0
            seq = CustomSlice()
            with sys.monitoring.StopTheWorld:
                seq.value = payload[0]
                items = [payload[0]]
            for _ in range(20):
                try:
                    invoke(getslice, (seq, 0, 1))
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)
            # A fresh list belongs to this group, even with foreign elements.
            sliced = getslice(items, 0, 1)
            results.put(sliced.__shareable__ is threading.Shareable.LOCAL)
            try:
                invoke(getitem, (sliced, 0))
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 20)
        self.assertTrue(results.get())
        self.assertTrue(results.get())
        self.assertIs(ref(), value)
        del value
        gc_collect()
        self.assertIsNone(ref())

    @threading_helper.requires_working_threading()
    def test_resource_preserves_access_errors(self):
        resource = import_module('resource')
        if not hasattr(resource, 'RLIMIT_NOFILE'):
            self.skipTest('requires RLIMIT_NOFILE')
        setlimits = resource.setrlimit
        limit = resource.RLIMIT_NOFILE
        internal = import_module('_testinternalcapi')
        internal.object_declare_synchronized(setlimits)
        class LocalInt(int):
            pass

        limits = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Prepare arguments in the owning group so the rejection is exercised
        # inside setrlimit(), rather than while retrieving a foreign element.
        foreign = tuple(tuple(LocalInt(value) if index == case else value
                              for index, value in enumerate(limits))
                        for case in range(2))
        results = threading.Channel()
        def worker():
            denied = 0
            for values in foreign:
                try:
                    setlimits(limit, values)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 2)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE), limits)

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires os.openpty')
    @threading_helper.requires_working_threading()
    def test_termios_foreign_module_state(self):
        import_module('termios')
        assert_python_ok('-c', textwrap.dedent('''
            import os
            import termios
            import threading
            import _testinternalcapi
            from test.support import SHORT_TIMEOUT

            getattrs, setattrs = termios.tcgetattr, termios.tcsetattr
            when = termios.TCSANOW
            for function in (getattrs, setattrs):
                _testinternalcapi.object_declare_synchronized(function)
            master, slave = os.openpty()
            try:
                original = getattrs(slave)
                results = threading.Channel()
                def worker():
                    # Even valid arguments must not cause a successful return
                    # with PyModule_GetState's access error still pending.
                    for function in (getattrs, setattrs):
                        try:
                            if function is getattrs:
                                function(slave)
                            else:
                                function(slave, when, [0] * 7)
                        except IllegalThreadAccessException:
                            results.put(True)
                        else:
                            results.put(False)
                thread = threading.Thread(target=worker,
                                          group=threading.ThreadGroup())
                thread.start()
                thread.join(SHORT_TIMEOUT)
                assert not thread.is_alive()
                assert [results.get(), results.get()] == [True, True]
                assert getattrs(slave) == original
            finally:
                os.close(master)
                os.close(slave)
        '''))

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires os.openpty')
    @threading_helper.requires_working_threading()
    def test_termios_preserves_access_errors(self):
        termios = import_module('termios')
        getattrs, setattrs = termios.tcgetattr, termios.tcsetattr
        when = termios.TCSANOW
        internal = import_module('_testinternalcapi')
        # Sharing entry points does not publish their module state.
        internal.object_declare_synchronized(termios)
        internal.object_declare_synchronized(getattrs)
        internal.object_declare_synchronized(setattrs)
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        class LocalInt(int):
            pass
        class LocalBytes(bytes):
            pass

        original = getattrs(slave)
        foreign_flag = LocalInt(original[0])
        foreign_cc = original[6]
        value = foreign_cc[0]
        foreign_char = LocalInt(value) if isinstance(value, int) else LocalBytes(value)
        results = threading.Channel()
        def worker(payload):
            denied = 0
            for case in range(3):
                attrs = getattrs(slave)
                with sys.monitoring.StopTheWorld:
                    if case == 0:
                        attrs[0] = payload[0]
                    elif case == 1:
                        attrs[6] = payload[1]
                    else:
                        attrs[6][0] = payload[2]
                try:
                    setattrs(slave, when, attrs)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(
            target=worker, args=((foreign_flag, foreign_cc, foreign_char),),
            group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 3)
        self.assertEqual(getattrs(slave), original)

    @threading_helper.requires_working_threading()
    def test_decimal_preserves_access_errors(self):
        decimal = import_module('_decimal')
        class LocalSignal(decimal.InvalidOperation):
            pass

        results = threading.Channel()
        def worker():
            try:
                decimal.Context(traps=[LocalSignal])
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())


if __name__ == '__main__':
    unittest.main()
