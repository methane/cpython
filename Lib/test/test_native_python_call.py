"""Native calls must validate Python arguments and returned objects."""

import importlib.machinery
import importlib.util
import sys
import threading
import unittest

from test.support import (SHORT_TIMEOUT, import_helper, is_apple_mobile,
                          threading_helper)


_testcapi = import_helper.import_module('_testcapi')
threading_helper.requires_working_threading(module=True)


def make_foreign_inputs(results):
    def factory():
        value = 0
        def mutate(flag=False):
            nonlocal value
            if flag:
                value += 1
            return 42
        return mutate
    results.put(([], factory()))


class NativePythonCallTests(unittest.TestCase):
    def test_synchronized_bound_method(self):
        class Worker(threading.Thread):
            def answer(self):
                return 42

        receiver = Worker()
        method = receiver.answer
        self.assertIs(method.__shareable__, threading.Shareable.SYNCHRONIZED)
        results = threading.Channel()
        def invoke(method, results):
            results.put(method())
        thread = threading.Thread(target=invoke, args=(method, results),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results.get(), 42)

        class Local:
            def answer(self):
                return 42
        self.assertIs(Local().answer.__shareable__, threading.Shareable.LOCAL)

    def test_foreign_native_callable_before_entry(self):
        invoke = _testcapi.pyobject_vectorcall
        target = _testcapi.return_tuple_item_unchecked
        self.assertIs(target.__shareable__, threading.Shareable.LOCAL)
        internal = import_helper.import_module('_testinternalcapi')
        internal.object_declare_synchronized(invoke)
        cases = (
            (_testcapi.pyobject_vectorcall, (target, ((42,),), None)),
            (_testcapi.pyobject_fastcalldict, (target, ((42,),), None)),
            (_testcapi.pyvectorcall_call, (target, ((42,),))),
            (_testcapi.call_cfunction_return_in_tuple, (target, ((42,),))),
            (_testcapi.call_cfunction_raw_return_in_tuple, (target, ((42,),))),
        )
        def worker(invoke, caller, args, results):
            try:
                invoke(caller, args, None)
            except IllegalThreadAccessException:
                results.put('denied')
            else:
                results.put('entered')
        for caller, args in cases:
            internal.object_declare_synchronized(caller)
            with self.subTest(caller=caller.__name__):
                results = threading.Channel()
                thread = threading.Thread(target=worker,
                                          args=(invoke, caller, args, results),
                                          group=threading.ThreadGroup())
                thread.start()
                thread.join(SHORT_TIMEOUT)
                self.assertFalse(thread.is_alive())
                self.assertEqual(results.get(), 'denied')

    def test_native_result_before_caller_consumes_it(self):
        foreign = self.foreign_inputs()
        lock = threading.Lock()
        with lock:
            protected = (lock.protect([]),)
        invoke = _testcapi.call_cfunction_return_in_tuple
        return_item = _testcapi.return_tuple_item_unchecked
        for holder, error in ((foreign, IllegalThreadAccessException),
                              (protected, UnprotectedAccessException)):
            with self.subTest(error=error):
                with self.assertRaises(error):
                    invoke(return_item, (holder,))
        with lock:
            self.assertIs(invoke(return_item, (protected,))[0], protected[0])
        local = []
        self.assertIs(invoke(return_item, ((local,),))[0], local)

    def foreign_inputs(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_foreign_inputs, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        return results.get()

    def test_raw_native_result_is_not_validated(self):
        # A checked call would mask missing access checks in the API under
        # test. The raw helper must wrap even an inaccessible native result.
        invoke = _testcapi.call_cfunction_raw_return_in_tuple
        return_item = _testcapi.return_tuple_item_unchecked
        foreign = self.foreign_inputs()
        result = invoke(return_item, (foreign,))
        self.assertEqual(len(result), 1)
        with self.assertRaises(IllegalThreadAccessException):
            result[0]
        with sys.monitoring.StopTheWorld:
            self.assertIs(result[0], foreign[0])

        for lock_type in (threading.Lock, threading.RLock):
            with self.subTest(lock_type=lock_type):
                lock = lock_type()
                with lock:
                    protected = (lock.protect([]),)
                result = invoke(return_item, (protected,))
                self.assertEqual(len(result), 1)
                with self.assertRaises(UnprotectedAccessException):
                    result[0]
                with lock:
                    self.assertIs(result[0], protected[0])

    def test_raw_native_calling_conventions(self):
        invoke = _testcapi.call_cfunction_raw_return_in_tuple
        for obj in (_testcapi, _testcapi.MethInstance(),
                    _testcapi.MethClass, _testcapi.MethClass(),
                    _testcapi.MethStatic):
            for name, args in (
                ('meth_varargs', ()), ('meth_varargs', (1, 2)),
                ('meth_varargs_keywords', ()),
                ('meth_varargs_keywords', (1, 2)),
                ('meth_fastcall', ()), ('meth_fastcall', (1, 2)),
                ('meth_fastcall_keywords', ()),
                ('meth_fastcall_keywords', (1, 2)),
                ('meth_noargs', ()), ('meth_o', (123,)),
            ):
                with self.subTest(obj=obj, name=name, args=args):
                    method = getattr(obj, name)
                    self.assertEqual(invoke(method, args), (method(*args),))
            for name, args in (('meth_noargs', (1,)), ('meth_o', ()),
                               ('meth_o', (1, 2))):
                with self.subTest(obj=obj, name=name, args=args):
                    with self.assertRaisesRegex(TypeError, 'argument count'):
                        invoke(getattr(obj, name), args)
        with self.assertRaisesRegex(TypeError, 'native callable'):
            invoke(lambda: None, ())
        with self.assertRaises(TypeError):
            invoke(_testcapi.meth_noargs, [])
        with self.assertRaisesRegex(TypeError, 'nonempty tuple'):
            invoke(_testcapi.return_tuple_item_unchecked, ((),))

    def test_raw_native_defining_class(self):
        extension = import_helper.import_module('_testmultiphase')
        name = '_testmultiphase_meth_state_access'
        loader_type = (importlib.machinery.AppleFrameworkLoader
                       if is_apple_mobile
                       else importlib.machinery.ExtensionFileLoader)
        loader = loader_type(name, extension.__spec__.origin)
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        class Derived(module.StateAccessType):
            pass

        invoke = _testcapi.call_cfunction_raw_return_in_tuple
        for cls in (module.StateAccessType, Derived):
            with self.subTest(cls=cls):
                instance = cls()
                self.assertIs(invoke(instance.get_defining_module, ())[0],
                              module)
                before = instance.get_count()
                self.assertEqual(
                    invoke(instance.increment_count_noclinic, (3,)), (None,))
                self.assertEqual(instance.get_count(), before + 3)

                # METH_METHOD calls must check even keyword
                # values that the native implementation does not inspect.
                holder = self.foreign_inputs()
                for bound in (False, True):
                    method = (instance.increment_count_noclinic if bound else
                              module.StateAccessType.increment_count_noclinic)
                    with sys.monitoring.StopTheWorld:
                        args = ((holder[0],) if bound else (instance, holder[0]))
                    before = instance.get_count()
                    with self.assertRaises(IllegalThreadAccessException):
                        _testcapi.pyobject_vectorcall(method, args, ('twice',))
                    self.assertEqual(instance.get_count(), before)
                    with sys.monitoring.StopTheWorld:
                        _testcapi.pyobject_vectorcall(method, args, ('twice',))
                    self.assertEqual(instance.get_count(), before + 2)

    def test_foreign_argument_before_entry(self):
        holder = self.foreign_inputs()
        entered = []
        def consume(value, unused):
            entered.append(True)
            return 42
        for kwnames in (None, ('value', 'unused')):
            with self.subTest(kwnames=kwnames):
                with self.assertRaises(IllegalThreadAccessException):
                    _testcapi.pyobject_vectorcall(consume, holder, kwnames)
                self.assertEqual(entered, [])

    def test_foreign_callable_before_entry(self):
        holder = self.foreign_inputs()
        with sys.monitoring.StopTheWorld:
            self.assertIs(holder[1].__shareable__, threading.Shareable.LOCAL)
            arguments = (holder[1], (), None)
        # Two native wrappers keep Python from acquiring the foreign callable
        # before the function vectorcall entry point under test.
        invoke = _testcapi.pyobject_vectorcall
        with self.assertRaises(IllegalThreadAccessException):
            invoke(invoke, arguments, None)

    def test_unprotected_argument_before_entry(self):
        lock = threading.Lock()
        with lock:
            holder = (lock.protect([]),)
        entered = []
        def consume(value):
            entered.append(True)
            return 42
        for kwnames in (None, ('value',)):
            with self.subTest(kwnames=kwnames):
                with self.assertRaises(UnprotectedAccessException):
                    _testcapi.pyobject_vectorcall(consume, holder, kwnames)
                self.assertEqual(entered, [])
                with lock:
                    self.assertEqual(
                        _testcapi.pyobject_vectorcall(consume, holder, kwnames), 42)
                entered.clear()

    def test_foreign_argument_before_custom_vectorcall(self):
        vectorcall_type = _testcapi.make_vectorcall_class()
        callable = vectorcall_type()
        callable.set_vectorcall(vectorcall_type)
        lock = threading.Lock()
        with lock:
            protected = lock.protect([])

        invocations = (
            lambda: _testcapi.pyobject_vectorcall(
                callable, (protected,), None),
            lambda: _testcapi.pyobject_vectorcall(
                callable, (protected,), ('value',)),
            lambda: _testcapi.pyobject_fastcalldict(
                callable, (), {'value': protected}),
            lambda: _testcapi.pyvectorcall_call(
                callable, (), {'value': protected}),
        )
        for invoke in invocations:
            with self.subTest(invoke=invoke):
                with self.assertRaises(UnprotectedAccessException):
                    invoke()

        with lock:
            self.assertEqual(
                _testcapi.pyobject_vectorcall(callable, (protected,), None),
                'vectorcall')


if __name__ == '__main__':
    unittest.main()
