"""Access checks at the public attribute acquisition boundaries."""

import sys
import threading
import unittest
import weakref
from types import ModuleType

from test.support import gc_collect, threading_helper
from test.support.import_helper import import_module


def make_carriers(value):
    class Instance:
        pass
    instance = Instance()
    instance.value = value
    class Slot:
        __slots__ = ('value',)
    slot = Slot()
    slot.value = value
    class Property:
        @property
        def value(self):
            return self.stored
    prop = Property()
    prop.stored = value
    class Getattribute:
        def __getattribute__(self, name):
            return object.__getattribute__(self, 'stored')
    custom = Getattribute()
    custom.stored = value
    class Getattr:
        def __getattr__(self, name):
            return self.stored
    fallback = Getattr()
    fallback.stored = value
    module = ModuleType('attribute_access_fixture')
    module.value = value
    Instance.value = value
    return (instance, slot, prop, custom, fallback, module, Instance)


def make_foreign_carriers(holder):
    # Only setup bypasses access checks; all reads run after resuming the world.
    with sys.monitoring.StopTheWorld:
        return make_carriers(holder[0])


@threading_helper.requires_working_threading()
class AttributeAccessTests(unittest.TestCase):
    def test_legacy_getattr(self):
        (invoke,) = self.helpers('call_cfunction_raw_return_in_tuple')
        (make,) = self.helpers('make_legacy_getattr')
        getters = self.helpers('object_getattr', 'object_getattrstring',
                               'object_getoptionalattr',
                               'object_getoptionalattrstring')
        results = threading.Channel()
        def worker(holder):
            with sys.monitoring.StopTheWorld:
                carrier = make(holder[0])
            denied = 0
            for getter in getters:
                for _ in range(100):
                    try:
                        invoke(getter, (carrier, 'value'))
                    except IllegalThreadAccessException:
                        denied += 1
                assert getter(make(42), 'value') == 42
            for getter in getters[:2]:
                try:
                    getter(carrier, 'missing')
                except AttributeError:
                    pass
                else:
                    raise AssertionError('missing attribute found')
            for getter in getters[2:]:
                assert getter(carrier, 'missing') is AttributeError
            results.put(denied)
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 400)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    def test_import_bookkeeping_does_not_expose_spec(self):
        results = threading.Channel()
        def worker():
            assert __import__('threading') is threading
            assert (threading.current_thread().__shareable__
                    is threading.Shareable.SYNCHRONIZED)
            try:
                getattr(threading, '__spec__')
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    def helpers(self, *names):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        getters = []
        for name in names:
            getter = getattr(capi, name, None)
            if getter is None:
                getter = getattr(limited, name)
            internal.object_declare_synchronized(getter)
            getters.append(getter)
        return tuple(getters)

    def test_foreign_attribute_results(self):
        (invoke,) = self.helpers('call_cfunction_raw_return_in_tuple')
        getters = self.helpers('object_getattr', 'object_getattrstring',
                               'object_getoptionalattr',
                               'object_getoptionalattrstring')
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        def worker(holder):
            denied = 0
            for getter in getters + (getattr,):
                for carrier in make_foreign_carriers(holder):
                    for _ in range(20):
                        try:
                            invoke(getter, (carrier, 'value'))
                        except IllegalThreadAccessException:
                            denied += 1
                for carrier in make_carriers(42):
                    assert getter(carrier, 'value') == 42
                local = []
                for carrier in make_carriers(local):
                    assert getter(carrier, 'value') is local
            results.put(denied)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 5 * 7 * 20)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    def test_hasattr_error_contracts(self):
        (invoke,) = self.helpers('call_cfunction_raw_return_in_tuple')
        checked = self.helpers('object_hasattrwitherror',
                               'object_hasattrstringwitherror')
        suppressed = self.helpers('object_hasattr', 'object_hasattrstring')
        results = threading.Channel()
        def worker(holder):
            denied = 0
            for getter in checked + (hasattr,):
                for carrier in make_foreign_carriers(holder):
                    try:
                        invoke(getter, (carrier, 'value'))
                    except IllegalThreadAccessException:
                        denied += 1
            reported = []
            def hook(event):
                reported.append(event.exc_type is IllegalThreadAccessException)
            previous = sys.unraisablehook
            sys.unraisablehook = hook
            try:
                for getter in suppressed:
                    for carrier in make_foreign_carriers(holder):
                        assert invoke(getter, (carrier, 'value')) == (0,)
            finally:
                sys.unraisablehook = previous
            results.put(denied)
            results.put(len(reported) == 14 and all(reported))
        thread = threading.Thread(target=worker, args=(([],),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 21)
        self.assertTrue(results.get())


if __name__ == '__main__':
    unittest.main()
