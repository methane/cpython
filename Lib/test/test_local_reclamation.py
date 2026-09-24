"""LOCAL objects lose their last reference synchronously within a ThreadGroup."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


@threading_helper.requires_working_threading()
class LocalReclamationTests(unittest.TestCase):
    def test_local_class_updates_with_parallel_lookup(self):
        assert_python_ok('-c', textwrap.dedent('''
            import threading
            from test.support import SHORT_TIMEOUT

            class Owner:
                pass
            class Value:
                pass

            instance = freeze(Owner())
            stop = threading.Event()
            started = threading.Event()
            errors = SynchronizedList()

            def read(instance):
                started.set()
                while not stop.is_set():
                    try:
                        instance.value
                    except (AttributeError, IllegalThreadAccessException):
                        pass
                    else:
                        errors.append('acquired a foreign LOCAL value')

            thread = threading.Thread(target=read, args=(instance,),
                                      group=threading.ThreadGroup())
            thread.start()
            try:
                assert started.wait(SHORT_TIMEOUT)
                for _ in range(200):
                    Owner.value = Value()
                    del Owner.value
            finally:
                stop.set()
                thread.join(SHORT_TIMEOUT)
            assert not thread.is_alive()
            assert not errors, list(errors)
        '''))

    def test_transferred_local_reclamation(self):
        assert_python_ok('-c', textwrap.dedent('''
            import gc
            import threading
            from test.support import SHORT_TIMEOUT

            gc.disable()
            events = SynchronizedList()

            @freeze
            class Value:
                def __init__(self, copied=False):
                    self.copied = copied
                def __copy__(self):
                    return Value(True)
                def __del__(self):
                    if self.copied:
                        events.append('finalized')

            original = Value()
            box = threading.TransferBox(original)

            def consume(box):
                value = box.claim()
                del value
                events.append('after del')

            consumer = threading.Thread(target=consume, args=(box,),
                                        group=threading.ThreadGroup())
            consumer.start()
            consumer.join(SHORT_TIMEOUT)
            assert not consumer.is_alive()
            assert list(events) == ['finalized', 'after del'], list(events)
        '''))

    def test_local_function_reclamation(self):
        for publication in ('none', 'class creation', 'class assignment'):
            with self.subTest(publication=publication):
                assert_python_ok('-c', textwrap.dedent(f'''
                    import gc
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
                    assert function.__shareable__ is threading.Shareable.LOCAL
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
                        assert method.__shareable__ is threading.Shareable.LOCAL
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
                            results.put(tuple(events))

                        expected = ['finalized'] if {finalize!r} else []
                        if {watch!r} and not {resurrect!r}:
                            expected.append('weakref')
                        expected.append('after del')
                        if {resurrect!r}:
                            if {watch!r}:
                                expected.append('weakref')
                            expected.append('after clear')
                        results = threading.Channel()
                        run_case(results)
                        observed = results.get()
                        assert observed == tuple(expected), (observed, expected)
                        creator = threading.Thread(
                            target=run_case, args=(results,),
                            group=threading.ThreadGroup())
                        creator.start()
                        creator.join(SHORT_TIMEOUT)
                        assert not creator.is_alive()
                        observed = results.get()
                        assert observed == tuple(expected), (observed, expected)
                    '''))


if __name__ == '__main__':
    unittest.main()
