"""LOCAL objects lose their last reference synchronously within a ThreadGroup."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


@threading_helper.requires_working_threading()
class LocalReclamationTests(unittest.TestCase):
    def test_reclamation_after_local_count_overflow(self):
        import weakref

        finalized = []

        class Value:
            def __del__(self):
                finalized.append(True)

        value = Value()
        reference = weakref.ref(value)
        references = [value] * 1024
        del value
        self.assertIsNotNone(reference())
        del references
        self.assertIsNone(reference())
        self.assertEqual(finalized, [True])

    def test_local_function_reclamation(self):
        for publication in ('none', 'class creation', 'class assignment'):
            with self.subTest(publication=publication):
                assert_python_ok('-c', textwrap.dedent(f'''
                    import gc
                    import _testinternalcapi
                    import threading
                    import weakref

                    gc.disable()
                    def template():
                        value = 0
                        def update():
                            nonlocal value
                            value += 1
                        return update

                    # Unlike a definition in its own globals dict, this
                    # function has no cycle through that dict.
                    function = type(template)(template.__code__, {{}})
                    assert not _testinternalcapi.has_deferred_refcount(function)
                    if {publication!r} == 'class creation':
                        owner = type('Owner', (), {{'method': function}})
                        del owner.method
                    elif {publication!r} == 'class assignment':
                        class Owner:
                            pass
                        Owner.method = function
                        del Owner.method
                    reference = weakref.ref(function)
                    del function
                    assert reference() is None
                '''))

    def test_local_method_wrapper_reclamation(self):
        for wrapper in ('classmethod', 'staticmethod', 'implicit staticmethod',
                        'property', 'custom descriptor'):
            for publication in ('none', 'class creation', 'class assignment'):
                with self.subTest(wrapper=wrapper, publication=publication):
                    assert_python_ok('-c', textwrap.dedent(f'''
                        import gc
                        import _testinternalcapi
                        import threading
                        import weakref

                        gc.disable()
                        class Value:
                            pass

                        if {wrapper!r} == 'implicit staticmethod':
                            class Factory:
                                def __new__(cls):
                                    return None
                            method = Factory.__dict__['__new__']
                            del Factory.__new__
                        elif {wrapper!r} == 'property':
                            class Property(property):
                                pass
                            method = Property(lambda self: None)
                        elif {wrapper!r} == 'custom descriptor':
                            class Descriptor:
                                def __get__(self, instance, owner):
                                    return None
                            method = Descriptor()
                        else:
                            import builtins
                            method = getattr(builtins, {wrapper!r})(lambda: None)
                        assert not _testinternalcapi.has_deferred_refcount(method)
                        # Exact method wrappers do not support weakrefs. The
                        # local payload must be released with its only owner.
                        method.payload = Value()
                        reference = weakref.ref(method.payload)
                        if {publication!r} == 'class creation':
                            owner = type('Owner', (), {{'method': method}})
                            del owner.method
                        elif {publication!r} == 'class assignment':
                            class Owner:
                                pass
                            Owner.method = method
                            del Owner.method
                        del method
                        assert reference() is None
                    '''))

    def test_last_reference_from_another_thread_in_group(self):
        for finalize, watch in ((False, True), (True, False), (True, True)):
            for resurrect in ((False, True) if finalize else (False,)):
                with self.subTest(finalizer=finalize, weakref=watch,
                                  resurrect=resurrect):
                    assert_python_ok('-c', textwrap.dedent(f'''
                        import gc
                        import _testinternalcapi
                        import threading
                        from weakref import ref as make_ref
                        from test.support import SHORT_TIMEOUT

                        gc.disable()

                        def run_case(results):
                            events = []
                            values = []

                            class Value:
                                if {finalize!r}:
                                    def __del__(self):
                                        events.append('finalized')
                                        if {resurrect!r}:
                                            values.append(self)

                            value = Value()
                            if {watch!r}:
                                reference = make_ref(
                                    value, lambda ref: events.append('weakref'))
                            values.append(value)
                            del value

                            def consume():
                                value = values.pop()
                                del value
                                events.append('after del')
                                if {resurrect!r}:
                                    values.clear()
                                    events.append('after clear')

                            # The allocating thread stays alive but cannot
                            # drain its BRC queue while the consumer runs.
                            consumer = threading.Thread(
                                target=consume,
                                group=threading.current_thread().group)
                            consumer.start()
                            consumer.join(SHORT_TIMEOUT)
                            assert not consumer.is_alive()
                            if {watch!r}:
                                assert reference() is None
                            results.append(tuple(events))

                        expected = ['finalized'] if {finalize!r} else []
                        if {watch!r} and not {resurrect!r}:
                            expected.append('weakref')
                        expected.append('after del')
                        if {resurrect!r}:
                            if {watch!r}:
                                expected.append('weakref')
                            expected.append('after clear')
                        results = []
                        run_case(results)
                        observed = results.pop(0)
                        assert observed == tuple(expected), (observed, expected)
                        creator = threading.Thread(
                            target=run_case, args=(results,))
                        creator.start()
                        creator.join(SHORT_TIMEOUT)
                        assert not creator.is_alive()
                        observed = results.pop(0)
                        assert observed == tuple(expected), (observed, expected)
                    '''))


if __name__ == '__main__':
    unittest.main()
