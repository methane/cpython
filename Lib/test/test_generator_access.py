"""Generator C API access checks for references acquired by native code."""

import threading
import unittest

from test.support import SHORT_TIMEOUT, import_helper, threading_helper


_testcapi = import_helper.import_module('_testcapi')
threading_helper.requires_working_threading(module=True)


def make_generator(results):
    def generate():
        yield None

    results.put((generate(),))


def rebind_generator_cell(channel, ready, change, changed):
    value = 42

    def generate():
        yield value
        yield value

    cell = generate.__closure__[0]
    channel.put(generate)
    ready.set()
    change.wait()
    cell.cell_contents = 43
    changed.set()


def rebind_class_cell(channel, ready, change, changed):
    value = 42

    def build_class(change, changed):
        class Captured:
            change.set()
            if not changed.wait(SHORT_TIMEOUT):
                raise AssertionError("cell owner did not rebind")
            captured = value
        return Captured

    cell = build_class.__closure__[0]
    channel.put(build_class)
    ready.set()
    change.wait()
    cell.cell_contents = 43
    changed.set()


class GeneratorAccessTests(unittest.TestCase):
    def test_rebound_foreign_closure(self):
        channel = threading.Channel()
        change = threading.Event()
        changed = threading.Event()
        ready = threading.Event()
        thread = threading.Thread(target=rebind_generator_cell,
                                  args=(channel, ready, change, changed),
                                  group=threading.ThreadGroup())
        thread.start()
        generators = []
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            generate = channel.get()
            generators = [generate(), generate()]
            self.assertEqual(next(generators[0]), 42)
            change.set()
            self.assertTrue(changed.wait(SHORT_TIMEOUT))
            for state, generator in zip(('suspended', 'unstarted'), generators):
                frame = generator.gi_frame
                for operation in ('native', 'native_string', 'getitem',
                                  'contains', 'len', 'keys', 'values', 'items'):
                    with self.subTest(state=state, operation=operation):
                        with self.assertRaises(IllegalThreadAccessException):
                            if operation == 'native':
                                _testcapi.frame_getvar(frame, 'value')
                            elif operation == 'native_string':
                                _testcapi.frame_getvarstring(frame, b'value')
                            elif operation == 'getitem':
                                frame.f_locals['value']
                            elif operation == 'contains':
                                'value' in frame.f_locals
                            elif operation == 'len':
                                len(frame.f_locals)
                            else:
                                getattr(frame.f_locals, operation)()
                with self.subTest(state=state):
                    with self.assertRaises(IllegalThreadAccessException):
                        next(generator)
        finally:
            change.set()
            thread.join(SHORT_TIMEOUT)
            for generator in generators:
                generator.close()
        self.assertFalse(thread.is_alive())

    def test_rebound_foreign_class_closure(self):
        channel = threading.Channel()
        ready = threading.Event()
        change = threading.Event()
        changed = threading.Event()
        thread = threading.Thread(target=rebind_class_cell,
                                  args=(channel, ready, change, changed),
                                  group=threading.ThreadGroup())
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            build_class = channel.get()
            try:
                build_class(change, changed)
            except IllegalThreadAccessException as exc:
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                self.assertEqual(tb.tb_frame.f_code.co_name, 'Captured')
            else:
                self.fail("class body read a foreign mutable cell")
        finally:
            change.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())

    def test_foreign_receiver(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_generator, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        holder = results.get()
        with self.assertRaises(IllegalThreadAccessException):
            _testcapi.gen_get_code_from_tuple(holder)

    def test_local_receiver(self):
        def generate():
            yield None

        generator = generate()
        try:
            self.assertIs(_testcapi.gen_get_code_from_tuple((generator,)),
                          generate.__code__)
            next(generator)
            self.assertIs(_testcapi.gen_get_code_from_tuple((generator,)),
                          generate.__code__)
            with self.assertRaises(StopIteration):
                next(generator)
            self.assertIs(_testcapi.gen_get_code_from_tuple((generator,)),
                          generate.__code__)
        finally:
            generator.close()


if __name__ == '__main__':
    unittest.main()
