import os
import subprocess
import sys
import sysconfig
import textwrap
import unittest


@unittest.skipUnless(
    sysconfig.get_config_var("Py_EXPERIMENTAL_TRACING_GC"),
    "requires --with-experimental-gc=tracing",
)
class ExperimentalTracingGCTests(unittest.TestCase):
    def run_python(self, source, *, args=(), env_vars=None, skip_exit_code=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        if env_vars is not None:
            env.update(env_vars)
        proc = subprocess.run(
            [sys.executable, "-S", *args, "-c", textwrap.dedent(source)],
            env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=60,
        )
        if skip_exit_code is not None and proc.returncode == skip_exit_code:
            self.skipTest(proc.stderr.strip())
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_progress_callback_allows_collection(self):
        for phase in ('start', 'stop'):
            for threaded in (False, True):
                with self.subTest(phase=phase, threaded=threaded):
                    self.run_python(f"""
                        import gc, sys, threading, weakref

                        gc.disable()
                        events = []
                        errors = []
                        sys.unraisablehook = lambda event: errors.append(event.exc_value)
                        reclaimed = []
                        class Node:
                            pass
                        def make():
                            refs = []
                            for _ in range(2000):
                                node = Node()
                                node.link = node
                                node.payload = [1.25, {{'value': 'alive'}}]
                                refs.append(weakref.ref(node))
                            return refs
                        def collect():
                            try:
                                refs = make()
                                count = sum(gc.collect() for _ in range(3))
                                assert count > 1000, count
                                assert sum(ref() is not None for ref in refs) < 10
                                reclaimed.append(count)
                            except BaseException as exc:
                                errors.append(exc)
                        def observe(current_phase, info):
                            events.append((current_phase, info.copy()))
                            if current_phase == {phase!r}:
                                if {threaded!r}:
                                    worker = threading.Thread(target=collect)
                                    worker.start()
                                    worker.join(10)
                                    assert not worker.is_alive()
                                else:
                                    collect()
                        def check_info(current_phase, info):
                            # Keep the C dispatcher's phase/info alive across
                            # the preceding callback's nested collections.
                            assert (current_phase, info) == events[-1]
                        gc.callbacks[:] = [observe, check_info]
                        for _ in range(2):
                            gc.collect()
                        gc.callbacks.clear()
                        assert not errors, errors
                        assert len(reclaimed) == 2, reclaimed
                        assert [phase for phase, info in events] == [
                            'start', 'stop', 'start', 'stop'], events
                    """)

    def test_progress_callback_satisfies_heap_trigger(self):
        self.run_python("""
            import gc, sys

            gc.disable()
            gc.collect()
            gc.set_threshold(1000)
            stops = []
            errors = []
            sys.unraisablehook = lambda event: errors.append(event.exc_value)
            def observe(phase, info):
                if phase == 'start':
                    gc.collect()
                else:
                    stops.append(info.copy())
            gc.callbacks.append(observe)
            gc.enable()
            for i in range(100000):
                obj = [i, (i, None), {'value': i}]
            gc.disable()
            gc.callbacks.clear()
            assert not errors, errors
            assert stops
            # The callback's explicit collection already consumed the heap
            # trigger. Do not perform a second, unnecessary automatic sweep.
            assert all(info['duration'] == 0.0 and info['candidates'] == 0
                       for info in stops), stops
        """)

    def test_progress_callback_races_with_collector(self):
        self.run_python("""
            import gc, threading

            gc.disable()
            entered = threading.Event()
            release = threading.Event()
            errors = []
            events = []
            workers = []
            class Node:
                def __del__(self):
                    if not entered.is_set():
                        entered.set()
                        if not release.wait(10):
                            errors.append('finalizer timed out')
            def make():
                for _ in range(200):
                    obj = Node()
                    obj.link = obj
            def collect():
                try:
                    make()
                    gc.collect()
                except BaseException as exc:
                    errors.append(exc)
            def observe(phase, info):
                events.append((phase, info.copy()))
                if phase == 'start':
                    worker = threading.Thread(target=collect)
                    workers.append(worker)
                    worker.start()
                    if not entered.wait(10):
                        errors.append('collector did not enter finalizer')
                else:
                    # The other collector cannot finish until this callback
                    # returns. The initiating collection must not wait for it.
                    release.set()
            gc.callbacks.append(observe)
            result = gc.collect()
            gc.callbacks.remove(observe)
            for worker in workers:
                worker.join(10)
                assert not worker.is_alive()
            assert not errors, errors
            assert result == 0, result
            assert [phase for phase, info in events] == ['start', 'stop']
            assert events[-1][1] == dict(generation=2, collected=0,
                uncollectable=0, candidates=0, duration=0.0), events
            # Neither completion may leave a stale collection/notification gate.
            make()
            assert gc.collect() > 0
        """)

    def test_progress_callback_errors_and_mutation(self):
        self.run_python("""
            import gc, sys

            gc.disable()
            errors = []
            phases = []
            sys.unraisablehook = lambda event: errors.append(event.exc_type)
            def failing(phase, info):
                gc.collect()
                raise ValueError('notification error')
            def observe(phase, info):
                phases.append((phase, info.copy()))
                if phase == 'stop' and failing in gc.callbacks:
                    gc.callbacks.remove(failing)
                gc.collect()
                assert (phase, info) == phases[-1]
            gc.callbacks[:] = [failing, observe]
            for _ in range(2):
                gc.collect()
            gc.callbacks.clear()
            assert errors == [ValueError, ValueError], errors
            assert [phase for phase, info in phases] == [
                'start', 'stop', 'start', 'stop'], phases
        """)

    def test_wide_pending_chains(self):
        self.run_python("""
            import gc

            gc.disable()
            # Each list traversal queues many children on the same allocator
            # page, with links beyond the range of a one-byte slot index.
            roots = [[i, 'payload-%d' % i] for i in range(8192)]
            for value in roots:
                value.append(value)
            for _ in range(3):
                gc.collect()
                for i, value in enumerate(roots):
                    assert value[:2] == [i, 'payload-%d' % i]
                    assert value[2] is value
            roots = roots[::2]
            for _ in range(3):
                gc.collect()
                for i, value in enumerate(roots):
                    assert value[:2] == [i * 2, 'payload-%d' % (i * 2)]
                    assert value[2] is value
        """)

    def test_collection_near_c_stack_limit(self):
        self.run_python("""
            import gc
            import sys
            import weakref
            from _testcapi import pyobject_vectorcall
            from _testinternalcapi import get_c_recursion_remaining

            sys.setrecursionlimit(100000)
            gc.disable()
            def make():
                refs = []
                class Meta(type):
                    pass
                for i in range(200):
                    cls = Meta('temporary-%d' % i, (), {})
                    obj = cls()
                    obj.link = obj
                    cls.instance = obj
                    obj.payload = ['payload-%d' % i, i + 0.125]
                    refs.append(weakref.ref(cls))
                return refs

            def deep():
                # Cross a native call frame each time; ordinary Python
                # recursion alone does not approach the C stack limit.
                if get_c_recursion_remaining() <= 50:
                    return gc.collect()
                return pyobject_vectorcall(deep, (), None)

            for _ in range(3):
                refs = make()
                assert deep() > 0
                # A later shallow collection used to drain a trashcan whose
                # instances' types and scalar children had already been freed.
                gc.collect()
                assert sum(ref() is not None for ref in refs) < 10
        """)

    def test_dictionary_destruction_watcher_resurrection(self):
        self.run_python("""
            import gc, _testcapi

            gc.disable()
            class WatchedDict(dict):
                pass
            # This watcher stores the dictionary itself on each destruction
            # attempt; the event list is also visited as a C module root.
            watcher = _testcapi.add_dict_watcher(3)
            events = _testcapi.get_dict_watcher_events()
            def make():
                for i in range(64):
                    dictionary = (dict if i % 2 else WatchedDict)(
                        number=i, payload=['alive', i])
                    dictionary['cycle'] = dictionary
                    _testcapi.watch_dict(watcher, dictionary)
            def check(dictionaries):
                for dictionary in dictionaries:
                    number = dictionary['number']
                    assert dictionary['payload'] == ['alive', number]
                    assert dictionary['cycle'] is dictionary
                    dictionary['reused'] = ['still alive', number]
            try:
                make()
                for _ in range(3):
                    gc.collect()
                assert len(events) >= 60, len(events)
                saved = events[:]
                known = {id(dictionary) for dictionary in saved}
                events.clear()
                check(saved)
                gc.collect()
                assert not any(id(dictionary) in known for dictionary in events)
                events.clear()
                saved.clear()
                for _ in range(3):
                    gc.collect()
                # Destruction watchers run again after a rescued dictionary
                # becomes unreachable; they are not once-only __del__ hooks.
                assert len(events) >= len(known) - 4, len(events)
                check(events)
                for dictionary in events:
                    _testcapi.unwatch_dict(watcher, dictionary)
                events.clear()
                for _ in range(3):
                    gc.collect()
                assert not events
            finally:
                _testcapi.clear_dict_watcher(watcher)
        """)

    def test_private_and_shared_dict_storage_reuse(self):
        self.run_python("""
            import gc, threading

            class Record:
                pass
            records = [Record() for _ in range(128)]
            for i, record in enumerate(records):
                record.number = i
                record.payload = ['shared', i]
            # Copies of split dictionaries share their keys table, unlike
            # the combined dictionaries created and destroyed below.
            copies = [record.__dict__.copy() for record in records]
            frozen_copies = [frozendict(record.__dict__) for record in records]
            errors = []
            def churn():
                try:
                    for i in range(10000):
                        unicode_keys = {'number': i, 'payload': ['unicode', i]}
                        general_keys = {i: ['general', i], (i, None): i + 1}
                        unicode_keys['cycle'] = unicode_keys
                        general_keys['cycle'] = general_keys
                        frozen_keys = frozendict(unicode_keys)
                        empty = {}
                        temporary = Record()
                        temporary.number = i
                        temporary.payload = ['temporary', i]
                except BaseException as exc:
                    errors.append(exc)
            for epoch in range(3):
                workers = [threading.Thread(target=churn) for _ in range(4)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
                for _ in range(3):
                    gc.collect()
                    for i, (record, copied) in enumerate(zip(records, copies)):
                        assert record.number == copied['number'] == i
                        assert record.payload == copied['payload'] == ['shared', i]
                        assert frozen_copies[i] == copied
                assert not errors, errors
        """)

    def test_mixed_mark_maps_and_slot_reuse(self):
        self.run_python("""
            import gc
            from _testinternalcapi import make_tracing_gc_boxed_float

            gc.disable()
            def make(index, epoch):
                row = [index, epoch, make_tracing_gc_boxed_float(index + 0.25),
                       bytes([index % 251]) * (17 + index % 97)]
                row.append({'owner': row, 'values': tuple(range(index % 23))})
                return row
            roots = [make(i, 0) for i in range(8193)]
            for epoch in range(1, 4):
                for _ in range(3):
                    gc.collect()
                    for i, row in enumerate(roots):
                        assert row[0] == i
                        assert row[2] == i + 0.25
                        assert row[3] == bytes([i % 251]) * (17 + i % 97)
                        assert row[4]['owner'] is row
                        assert row[4]['values'] == tuple(range(i % 23))
                # Leave holes in both byte and halfword maps, then reuse
                # their slots with another wide set of pending graph edges.
                for i in range(epoch % 2, len(roots), 2):
                    roots[i] = None
                for _ in range(3):
                    gc.collect()
                for i in range(epoch % 2, len(roots), 2):
                    roots[i] = make(i, epoch)
            gc.collect()
            assert all(row[4]['owner'] is row for row in roots)
        """)

    def run_soft_dirty(self, source, *, args=(), env_vars=None):
        if sys.platform != "linux":
            self.skipTest("soft-dirty tracking requires Linux")
        prelude = textwrap.dedent("""
            import gc
            import os
            import sys
            from _testinternalcapi import (
                get_tracing_gc_state, make_tracing_gc_boxed_float)

            events = []
            def record_collection(phase, info):
                if phase == 'stop':
                    events.append(get_tracing_gc_state()['minors'])
            gc.callbacks.append(record_collection)

            def prepare():
                try:
                    fd = os.open('/proc/self/pagemap', os.O_RDONLY)
                    os.close(fd)
                except OSError as exc:
                    print('pagemap unavailable:', exc, file=sys.stderr)
                    sys.exit(77)
                gc.collect()
                state = get_tracing_gc_state()
                assert state['enabled'] == 1, state
                if state['pid'] == 0:
                    print('soft-dirty tracking unavailable', file=sys.stderr)
                    sys.exit(77)
                gc.set_threshold(64)
                gc.enable()
                events.clear()

            def allocate_until(predicate):
                for batch in range(256):
                    for i in range(4096):
                        # Both arithmetic and the loop counter may now be
                        # immediate. Explicitly allocate a heap scalar.
                        value = make_tracing_gc_boxed_float(i + 0.25)
                    if predicate():
                        return
                raise AssertionError(('no expected collection', events))
        """)
        env = {"PYTHON_TRACING_GC_SOFT_DIRTY": "1"}
        if env_vars:
            env.update(env_vars)
        self.run_python(prelude + textwrap.dedent(source), args=args,
                        env_vars=env, skip_exit_code=77)

    def check_clean_leaf_pages(self, containers, *, abandoned=False):
        source = """
            import threading
            from _testinternalcapi import get_tracing_gc_skipped_leaf_pages
            roots = []
            def make_roots():
                roots.extend(bytes([i % 256]) * 8192 for i in range(256))
            if ABANDONED:
                thread = threading.Thread(target=make_roots)
                thread.start()
                thread.join()
            else:
                make_roots()
            # The first list read records a sticky alias bit in each header.
            # Do that before establishing the unchanged-page baseline; later
            # payload checks should not themselves invalidate that baseline.
            for value in roots:
                assert len(value) == 8192
            del value
            prepare()
            def trigger():
                target = len(events) + 1
                for _ in range(256):
                    for i in range(4096):
                        value = ([i, i + 0.25] if CONTAINERS else
                                 make_tracing_gc_boxed_float(i + 0.25))
                    if len(events) >= target:
                        return
                raise AssertionError(('no collection', events))
            for batch in range(3):
                # Newly written areas must still be traced alongside clean
                # old areas of the same size class, including recycled slots.
                fresh = [bytes([(i + batch + 7) % 256]) * 8192
                         for i in range(32)]
                trigger()
                assert events[-1] > 0, events
                state = get_tracing_gc_state()
                skipped = get_tracing_gc_skipped_leaf_pages() * os.sysconf('SC_PAGESIZE')
                assert skipped > 1024 * 1024, state
                assert all(value == bytes([i % 256]) * 8192
                           for i, value in enumerate(roots))
                assert all(value == bytes([(i + batch + 7) % 256]) * 8192
                           for i, value in enumerate(fresh))
            # A full collection must discard the partial-collection shortcut.
            gc.collect()
            assert get_tracing_gc_skipped_leaf_pages() == 0
            assert len(roots) == 256 and len(fresh) == 32
        """.replace("CONTAINERS", repr(containers)).replace("ABANDONED", repr(abandoned))
        env = {"PYTHON_TRACING_GC_YOUNG_CONTAINERS": str(int(containers))}
        args = ()
        if abandoned:
            args = ("-X", "gil=0", "-X", "tlbc=1")
            env["PYTHON_JIT"] = "0"
        self.run_soft_dirty(source, args=args, env_vars=env)

    def test_soft_dirty_clean_leaf_pages(self):
        self.check_clean_leaf_pages(False)

    def test_young_containers_clean_leaf_pages(self):
        self.check_clean_leaf_pages(True)

    def test_clean_leaf_pages_in_abandoned_heap(self):
        self.check_clean_leaf_pages(True, abandoned=True)

    def check_clean_old_container_pages(self, abandoned=False, reset=False,
                                        raw=False, fallback=False):
        self.run_soft_dirty(f"""
            import threading
            from _testcapi import list_set_item
            from _testinternalcapi import (
                get_tracing_gc_old_pages, get_long_lived_total)
            gc.disable()
            roots = []
            candidates = []
            def record_candidates(phase, info):
                if phase == 'stop':
                    candidates.append(info['candidates'])
            gc.callbacks.append(record_candidates)
            class Node:
                pass
            def allocate_containers_until(predicate):
                for batch in range(256):
                    for i in range(4096):
                        value = [i, (i, None), {{'value': i}}]
                    if predicate():
                        return
                raise AssertionError(('no container collection', events))
            def make_roots():
                roots.extend([[None] for _ in range(30000)])
                # Reading these references must not first change alias bits
                # after establishing the dirty-page baseline.
                for row in roots:
                    assert row[0] is None
            if {abandoned!r}:
                worker = threading.Thread(target=make_roots)
                worker.start()
                worker.join()
            else:
                make_roots()
            prepare()
            allocate_containers_until(lambda: bool(events))
            gc.disable()
            assert events[-1] > 0, events
            assert get_tracing_gc_old_pages()['cached'] > 0
            for epoch in range(3):
                # Ordinary assignment dirties the header's mutex, so mutate
                # only some pages. The raw C API updates item arrays without
                # a header write; no other thread accesses these test lists.
                limit = len(roots) if {raw!r} else 1024
                for i in range(0, limit, 97):
                    value = [epoch, i]
                    value.append(value)
                    if {raw!r}:
                        list_set_item(roots[i], 0, value)
                    else:
                        roots[i][0] = value
                del value
                if {reset!r} and epoch == 1:
                    with open('/proc/self/clear_refs', 'w') as stream:
                        stream.write('4')
                target = len(events) + 1
                gc.enable()
                allocate_containers_until(lambda: len(events) >= target)
                gc.disable()
                state = get_tracing_gc_old_pages()
                assert candidates[-1] >= len(roots), candidates[-1]
                assert get_long_lived_total() >= len(roots)
                if {reset!r} and epoch == 1:
                    assert events[-1] == 0, events
                    assert state == {{'cached': 0, 'skipped': 0}}, state
                else:
                    assert events[-1] > 0, events
                    if not {reset!r}:
                        assert state['skipped'] > 0, state
                for i in range(0, limit, 97):
                    value = roots[i][0]
                    assert value[:2] == [epoch, i]
                    assert value[2] is value
                del value
            if {fallback!r}:
                # Force an early full-snapshot fallback after cached old
                # container pages have already been omitted from the attempt.
                nodes = [Node() for _ in range(30000)]
                for node in nodes:
                    node.link = node
                del node, nodes
                target = len(events) + 1
                gc.enable()
                allocate_containers_until(lambda: len(events) >= target)
                gc.disable()
                assert events[-1] == 0, events
                assert get_tracing_gc_old_pages() == {{'cached': 0, 'skipped': 0}}
                for i in range(0, limit, 97):
                    value = roots[i][0]
                    assert value[:2] == [epoch, i] and value[2] is value
                del value
            gc.collect()
            assert get_tracing_gc_old_pages() == {{'cached': 0, 'skipped': 0}}
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_clean_old_container_pages(self):
        self.check_clean_old_container_pages()

    def test_clean_old_container_pages_in_abandoned_heap(self):
        self.check_clean_old_container_pages(abandoned=True)

    def test_clean_old_container_pages_external_reset(self):
        self.check_clean_old_container_pages(reset=True)

    def test_clean_old_container_pages_external_storage(self):
        self.check_clean_old_container_pages(raw=True)

    def test_clean_old_container_pages_full_fallback(self):
        self.check_clean_old_container_pages(fallback=True)

    def check_dirty_reads_with_mixed_area_sizes(self, containers):
        self.run_soft_dirty("""
            gc.disable()
            roots = [[None] * size for size in (8, 4096, 65536, 524288)]
            prepare()
            for epoch in range(3):
                gc.disable()
                for row in roots:
                    for index in (0, len(row) // 2, len(row) - 1):
                        row[index] = make_tracing_gc_boxed_float(
                            epoch * 1000000 + index + 0.25)
                del row
                target = len(events) + 1
                gc.enable()
                allocate_until(lambda: len(events) >= target)
                gc.disable()
                assert events[-1] > 0, events
                for row in roots:
                    for index in (0, len(row) // 2, len(row) - 1):
                        assert row[index] == epoch * 1000000 + index + 0.25
                del row
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": str(int(containers))})

    def test_soft_dirty_mixed_area_sizes(self):
        self.check_dirty_reads_with_mixed_area_sizes(False)

    def test_young_containers_mixed_area_sizes(self):
        self.check_dirty_reads_with_mixed_area_sizes(True)

    def test_dirty_reads_across_large_old_storage(self):
        self.run_soft_dirty("""
            # The pointer arrays span many OS pages and allocator areas.
            # Mutations in successive nursery epochs must all be observed.
            rows = [[None] * 2048 for _ in range(512)]
            for row in rows:
                assert row[0] is None
            del row
            prepare()
            for epoch in range(3):
                gc.disable()
                for i in range(0, len(rows), 13):
                    value = [epoch, i]
                    value.append(value)
                    rows[i][(epoch * 683 + i) % 2048] = {'value': value}
                target = len(events) + 1
                gc.enable()
                allocate_until(lambda: len(events) >= target)
                gc.disable()
                assert events[-1] > 0, events
                for previous in range(epoch + 1):
                    for i in range(0, len(rows), 13):
                        value = rows[i][(previous * 683 + i) % 2048]['value']
                        assert value[:2] == [previous, i]
                        assert value[2] is value
                assert rows[1][0] is None
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_cycles_are_reclaimed(self):
        self.run_soft_dirty("""
            marker = object()
            def make():
                for i in range(10000):
                    value = [marker, i]
                    mapping = {'value': value}
                    value.append((mapping, value))
            prepare()
            gc.disable()
            make()
            gc.enable()
            allocate_until(lambda: bool(events))
            assert events[0] > 0, events
            remaining = sum(type(obj) is list and len(obj) == 3 and
                            obj[0] is marker for obj in gc.get_objects())
            assert remaining < 50, remaining
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_sweep_accounting(self):
        self.run_soft_dirty("""
            marker = object()
            reports = []
            def record(phase, info):
                if phase == 'stop':
                    reports.append((info.copy(),
                                    gc.get_stats()[info['generation']]))
            def make():
                for i in range(10000):
                    row = [marker, i]
                    row.append(({'row': row}, row))
            prepare()
            gc.disable()
            make()
            before = gc.get_stats()
            gc.callbacks.append(record)
            gc.enable()
            allocate_until(lambda: bool(reports))
            gc.disable()
            assert events[0] > 0, events
            info, stats = reports[0]
            previous = before[info['generation']]
            assert info['collected'] >= 29000, info
            assert info['candidates'] >= info['collected'], info
            assert info['uncollectable'] == 0, info
            for key in ('collected', 'candidates', 'uncollectable'):
                assert stats[key] - previous[key] == info[key], (
                    key, previous, info, stats)
            assert stats['collections'] == previous['collections'] + 1
            remaining = sum(type(obj) is list and len(obj) == 3 and
                            obj[0] is marker for obj in gc.get_objects())
            assert remaining < 50, remaining
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_container_clear_preserves_shared_children(self):
        self.run_python("""
            import gc
            import weakref
            from _testinternalcapi import get_tracing_gc_refstate
            class Payload:
                pass
            value = Payload()
            value.text = 'retained-' * 100
            ref = weakref.ref(value)
            sequence = [value] * 100000
            mapping = {str(i): value for i in range(10000)}
            shared = tuple(sequence)
            before = get_tracing_gc_refstate(value)
            sequence.clear()
            mapping.clear()
            assert sequence == [] and mapping == {}
            assert get_tracing_gc_refstate(value) == before
            gc.collect()
            assert len(shared) == 100000
            assert shared[0] is shared[-1] is value is ref()
            assert value.text == 'retained-' * 100
            del shared, value
            for _ in range(5):
                gc.collect()
            assert ref() is None
        """)

    def test_young_container_sweep_releases_shared_storage(self):
        self.run_soft_dirty("""
            class Holder:
                pass
            holder = Holder()
            holder.payload = ['retained']
            retained = holder.__dict__
            marker = object()
            def churn():
                for i in range(10000):
                    # Copies share the keys table but own their value arrays.
                    copied = retained.copy()
                    sequence = [marker] * (i % 100 + 1)
                    copied['payload'] = sequence
                    sequence.append((copied, sequence))
            prepare()
            for _ in range(4):
                churn()
                assert holder.payload == retained['payload'] == ['retained']
            assert any(events), events
            for _ in range(3):
                gc.collect()
            remaining = sum(type(obj) is list and bool(obj) and
                            obj[0] is marker for obj in gc.get_objects())
            assert remaining < 50, remaining
            holder.payload.append('still alive')
            assert retained == {'payload': ['retained', 'still alive']}
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_sweep_reuses_freed_slots(self):
        self.run_soft_dirty("""
            import sys
            def churn():
                for i in range(10000):
                    sequence = [i, i + 0.25, 'value-%d' % i]
                    mapping = {(i,): sequence, 'self': None}
                    mapping['self'] = mapping
                    sequence.append((mapping, sequence))
            prepare()
            churn()
            gc.collect()
            before = sys.getallocatedblocks()
            for _ in range(10):
                churn()
                gc.collect()
            after = sys.getallocatedblocks()
            assert any(events), events
            assert after - before < 2000, (before, after)
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_sweep_with_reference_tracer(self):
        self.run_soft_dirty("""
            import _testcapi
            def churn():
                for i in range(10000):
                    value = [i, i + 0.25, 'value-%d' % i]
                    value.append(value)
            prepare()
            gc.disable()
            _testcapi.start_counting_list_destroys()
            try:
                churn()
                gc.enable()
                allocate_until(lambda: bool(events))
                assert events[0] == 0, events
            finally:
                destroys = _testcapi.stop_counting_list_destroys()
            assert destroys > 9500, destroys
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_sweep_retracks_new_objects(self):
        self.run_soft_dirty("""
            prepare()
            for batch in range(4):
                # Cross multiple automatic collection budgets before the
                # explicit full GC, exercising nursery reclamation as well.
                for i in range(20000):
                    sequence = []
                    pair = (i, sequence)
                    mapping = {'value': pair}
                    sequence.append(mapping)
                    if i % 128 == 0:
                        assert gc.is_tracked(sequence)
                        assert gc.is_tracked(pair)
                        assert gc.is_tracked(mapping)
                gc.collect()
                assert mapping['value'] is pair
                assert pair == (19999, sequence)
                assert sequence[0] is mapping
                assert gc.is_tracked(sequence)
                assert gc.is_tracked(pair)
                assert gc.is_tracked(mapping)
            assert any(events), events
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def check_nursery_sweep_stop(self, *, reftracer=False, tracemalloc=False,
                                full=False, opaque=False):
        source = """
            import _testcapi
            import tracemalloc
            from _testinternalcapi import test_tracing_gc_sweep
            if TRACE_MALLOC:
                tracemalloc.start()
            if OPAQUE:
                class Holder:
                    pass
                def make_opaque():
                    for _ in range(32):
                        obj = Holder()
                        obj.link = obj
            def collect():
                if FULL_GC:
                    if OPAQUE:
                        make_opaque()
                    gc.collect()
                else:
                    gc.enable()
                    for i in range(100000):
                        value = [i, (i, None), {'value': i}]
                        if events:
                            break
                gc.disable()
                assert events, events
            prepare()
            gc.disable()
            if FULL_GC:
                # Drain import-time garbage and objects retained by its
                # callbacks before constructing the controlled dead graph.
                for _ in range(3):
                    gc.collect()
                events.clear()
            if REFTRACER:
                _testcapi.start_counting_list_destroys()
            try:
                freed, stopped = test_tracing_gc_sweep(collect)
            finally:
                if REFTRACER:
                    _testcapi.stop_counting_list_destroys()
                if TRACE_MALLOC:
                    tracemalloc.stop()
            # Allow conservative stack roots and the list freelist to retain
            # some targets. Every observed free must use the expected phase.
            assert freed > 100, (freed, stopped, events)
            # tracemalloc installs its own reference tracer too.
            if REFTRACER or TRACE_MALLOC or FULL_GC:
                assert events[0] == 0, events
            else:
                assert events[0] > 0, events
            if REFTRACER or TRACE_MALLOC or OPAQUE:
                assert stopped == 0, (freed, stopped)
            else:
                assert stopped == freed, (freed, stopped)
        """
        source = source.replace("REFTRACER", repr(reftracer))
        source = source.replace("TRACE_MALLOC", repr(tracemalloc))
        source = source.replace("FULL_GC", repr(full))
        source = source.replace("OPAQUE", repr(opaque))
        self.run_soft_dirty(source,
            env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_container_sweep_keeps_world_stopped(self):
        self.check_nursery_sweep_stop()

    def test_young_container_tracemalloc_fallback_restarts_world(self):
        self.check_nursery_sweep_stop(tracemalloc=True)

    def test_young_container_reftracer_fallback_restarts_world(self):
        self.check_nursery_sweep_stop(reftracer=True)

    def test_full_container_sweep_keeps_world_stopped(self):
        self.check_nursery_sweep_stop(full=True)

    def test_full_opaque_sweep_restarts_world(self):
        # No tp_finalize is present, but an arbitrary tp_clear/tp_dealloc
        # still needs the ordinary, running-world destruction path.
        self.check_nursery_sweep_stop(full=True, opaque=True)

    def test_young_containers_old_storage_roots(self):
        self.run_soft_dirty("""
            from _testcapi import GCExternalBuffer
            class Holder:
                pass
            holder = Holder()
            holder.value = None
            mapping = holder.__dict__
            sequence = [None]
            dictionary = {'value': None}
            external = GCExternalBuffer()
            def install(n):
                value = [n, 'young-%d' % n]
                value.append({'cycle': (value,)})
                sequence[0] = value
                dictionary['value'] = value
                mapping['value'] = value
                external.value = value
            def churn():
                for i in range(10000):
                    value = [i, {'payload': ('value-%d' % i,)}]
            prepare()
            for n in range(3):
                install(n)
                target = len(events) + 1
                for _ in range(256):
                    churn()
                    if len(events) >= target:
                        break
                else:
                    raise AssertionError(('no collection', events))
                value = sequence[0]
                assert dictionary['value'] is value
                assert holder.value is value and external.value is value
                assert value[:2] == [n, 'young-%d' % n]
                assert value[2]['cycle'][0] is value
            assert any(events), events
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_mixed_buffer_owners(self):
        self.run_soft_dirty("""
            from _testcapi import list_set_item

            # Keep old item arrays while allocating equally sized young
            # arrays. A page can contain both independent dirty roots and
            # buffers that must be traced only through their young owners.
            roots = [[None] * 128 for _ in range(256)]
            def install(epoch):
                for i, root in enumerate(roots):
                    value = [None] * 128
                    value[:2] = [epoch, i]
                    value[-1] = value
                    # No other thread uses these lists. Only the item array
                    # is written, not the old object's header or its mutex.
                    list_set_item(root, 0, value)
                for _ in range(1024):
                    value = [None] * 128
                    value[0] = 'mixed-buffer-garbage'
                    value[-1] = value
            def churn():
                for i in range(1000):
                    value = [i, {'payload': (i, None)}]
            for epoch in range(3):
                # Start a fresh epoch so gc.get_objects() from the previous
                # check cannot itself force a full-collection fallback.
                prepare()
                gc.disable()
                install(epoch)
                target = len(events) + 1
                gc.enable()
                for _ in range(256):
                    churn()
                    if len(events) >= target:
                        break
                else:
                    raise AssertionError(('no collection', events))
                gc.disable()
                assert events[-1] > 0, events
                for i, root in enumerate(roots):
                    value = root[0]
                    assert value[:2] == [epoch, i]
                    assert value[-1] is value
                del value, root
                leftovers = sum(
                    type(obj) is list and len(obj) == 128 and
                    obj[0] == 'mixed-buffer-garbage' and obj[-1] is obj
                    for obj in gc.get_objects())
                assert leftovers < 20, leftovers
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_abandoned_old_storage_roots(self):
        self.run_soft_dirty("""
            import threading
            from _testcapi import GCExternalBuffer
            class Holder:
                pass
            roots = []
            def make_roots():
                for _ in range(512):
                    holder = Holder()
                    holder.value = None
                    roots.append(([None] * 128, {'value': None}, holder,
                                  GCExternalBuffer()))
            worker = threading.Thread(target=make_roots)
            worker.start()
            worker.join()
            assert len(roots) == 512
            prepare()
            for epoch in range(3):
                gc.disable()
                for i, (sequence, mapping, holder, external) in enumerate(roots):
                    # Each storage kind is the only root of its own cycle.
                    for kind in range(4):
                        value = [epoch, i, kind]
                        value.append(value)
                        if kind == 0:
                            sequence[0] = value
                        elif kind == 1:
                            mapping['value'] = value
                        elif kind == 2:
                            holder.value = value
                        else:
                            external.value = value
                del value, sequence, mapping, holder, external
                target = len(events) + 1
                gc.enable()
                allocate_until(lambda: len(events) >= target)
                gc.disable()
                assert events[-1] > 0, events
                for i, (sequence, mapping, holder, external) in enumerate(roots):
                    for kind, value in enumerate((sequence[0], mapping['value'],
                                                   holder.value, external.value)):
                        assert value[:3] == [epoch, i, kind]
                        assert value[3] is value
                del value, sequence, mapping, holder, external
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_defer_finalizers_to_full_gc(self):
        self.run_soft_dirty("""
            import weakref
            calls = []
            class Finalizer:
                def __del__(self):
                    assert self.value[0] is self
                    calls.append(self.number)
            def make():
                refs = []
                for i in range(100):
                    obj = Finalizer()
                    obj.number = i
                    obj.value = [obj]
                    refs.append(weakref.ref(obj))
                return refs
            def churn():
                for i in range(10000):
                    value = [i, {'payload': i}]
            prepare()
            gc.disable()
            refs = make()
            churn()
            gc.enable()
            allocate_until(lambda: bool(events))
            assert events[0] > 0, events
            assert not calls, calls
            assert all(ref() is not None for ref in refs)
            for _ in range(3):
                gc.collect()
            assert len(calls) > 95, len(calls)
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_snapshot_maps_with_sparse_mixed_pages(self):
        self.run_python("""
            import gc, sys

            gc.disable()
            retained = []
            def make_batch(epoch):
                rows = []
                for i in range(20000):
                    payload = bytes([i % 251]) * (17 + i % 97)
                    row = [i, payload, {'value': (epoch, i)}]
                    row.append(row)
                    rows.append(row)
                return rows

            for epoch in range(3):
                rows = make_batch(epoch)
                # Mix many small object maps with leaf maps for large blocks.
                # Retaining a sparse subset leaves free slots in many pages.
                large = [bytes([i]) * (40000 + i) for i in range(17)]
                survivors = rows[::257]
                del rows
                for _ in range(3):
                    gc.collect()
                for row in survivors:
                    i = row[0]
                    assert row[1] == bytes([i % 251]) * (17 + i % 97)
                    assert row[2] == {'value': (epoch, i)}
                    assert row[3] is row
                assert large == [bytes([i]) * (40000 + i)
                                 for i in range(17)]
                # Repeated snapshots must not read stale or uninitialized
                # marks after their temporary buffers have been recycled.
                for _ in range(3):
                    gc.collect()
                assert all(row[3] is row for row in survivors)
                retained.append(sys.getallocatedblocks())
            assert max(retained) - min(retained) < 5000, retained
        """)

    def test_snapshot_headers_across_small_and_huge_pages(self):
        self.run_python("""
            import gc, threading, weakref

            class Marker:
                pass
            gc.disable()
            retained = []
            refs = []
            errors = []
            widths = (0, 1, 15, 16, 17, 255, 4096, 32768)
            def allocate(epoch):
                try:
                    for width in widths:
                        for index in range(24):
                            marker = Marker()
                            marker.key = epoch, width, index
                            row = [marker, (None,) * width]
                            row.append(row)
                            refs.append(weakref.ref(marker))
                            if index in (0, 12, 23):
                                retained.append(row)
                except BaseException as exc:
                    errors.append(exc)

            for epoch in range(3):
                worker = threading.Thread(target=allocate, args=(epoch,))
                worker.start()
                worker.join()
                assert not errors, errors
                # Huge tuple pages can have fewer slots than a lookahead
                # window. Small pages have holes after the first collection.
                for _ in range(3):
                    gc.collect()
                assert sum(ref() is not None for ref in refs) == len(retained)
                for marker, items, link in retained:
                    assert marker.key[2] in (0, 12, 23)
                    assert len(items) == marker.key[1]
                    assert all(item is None for item in items)
                    assert link[0] is marker and link[2] is link
        """)

    def test_full_gc_retires_idle_worker_pages(self):
        self.run_python("""
            import gc, threading
            from _testinternalcapi import get_tracing_gc_heap_stats

            gc.disable()
            ready = threading.Barrier(5, timeout=30)
            release = threading.Event()
            errors = []
            results = [None] * 4
            def allocate():
                for i in range(20000):
                    value = [i, (i, None), {'value': i}]
                return value
            def worker(index):
                try:
                    results[index] = allocate()
                    ready.wait()
                    release.wait(30)
                except BaseException as exc:
                    errors.append(exc)
                    ready.abort()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            try:
                ready.wait()
                gc.collect()
                empty_before = sum(s['empty_committed']
                                   for s in get_tracing_gc_heap_stats())
                assert empty_before > 4 * 1024 * 1024, empty_before
                # Advance GC/QSBR epochs without asking idle owners to run
                # allocations or terminate. Their empty pages must retire.
                for _ in range(4):
                    gc.collect()
                empty_after = sum(s['empty_committed']
                                  for s in get_tracing_gc_heap_stats())
                assert empty_after < empty_before // 2, (empty_before, empty_after)
                assert results == [[19999, (19999, None), {'value': 19999}]] * 4
                assert all(thread.is_alive() for thread in threads)
            finally:
                release.set()
                for thread in threads:
                    thread.join()
            assert not errors, errors
        """)

    def test_full_gc_preserves_idle_worker_buffers(self):
        self.run_python("""
            import gc, threading

            gc.disable()
            gate = threading.Barrier(5, timeout=30)
            results = [None] * 4
            errors = []
            def allocate(epoch):
                for i in range(20000):
                    value = [i, (epoch, i), {'value': i}]
                return value
            def worker(index):
                try:
                    # Keep an occupied buffer in the same owner's segments
                    # while surrounding pages become free and are reused.
                    live = bytearray([65 + index]) * 65536
                    for epoch in range(3):
                        results[index] = live, allocate(epoch)
                        gate.wait()
                        gate.wait()
                except BaseException as exc:
                    errors.append(exc)
                    gate.abort()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            try:
                for epoch in range(3):
                    gate.wait()
                    for _ in range(3):
                        gc.collect()
                        for index, (live, last) in enumerate(results):
                            assert live == bytearray([65 + index]) * 65536
                            assert last == [19999, (epoch, 19999), {'value': 19999}]
                        assert all(thread.is_alive() for thread in threads)
                    gate.wait()
            except BaseException:
                gate.abort()
                raise
            finally:
                for thread in threads:
                    thread.join(30)
            assert not errors, errors
            assert all(not thread.is_alive() for thread in threads)
        """, env_vars={"MIMALLOC_PURGE_DELAY": "600000"})

    def test_failed_set_operations_are_reclaimed(self):
        for kind in ('set', 'frozenset'):
            for operation in ('union', 'intersection', 'difference',
                              'symmetric_difference'):
                for failure in ('iteration', 'hash'):
                    with self.subTest(kind=kind, operation=operation,
                                      failure=failure):
                        self.run_python(f"""
                            import gc
                            import threading
                            from _testinternalcapi import get_tracing_gc_heap_stats

                            class Payload:
                                pass
                            class BadHash:
                                def __hash__(self):
                                    raise ValueError('hash failed')
                            def failing(payload):
                                yield payload
                                if {failure!r} == 'hash':
                                    yield BadHash()
                                raise RuntimeError('iteration failed')
                            def memory():
                                return sum(row['allocated'] for row in
                                           get_tracing_gc_heap_stats())
                            errors = []
                            completed = []
                            def worker():
                                try:
                                    expected = (ValueError if {failure!r} == 'hash'
                                                else RuntimeError)
                                    for _ in range(256):
                                        payload = Payload()
                                        source = {kind}((payload, None))
                                        method = getattr(source, {operation!r})
                                        try:
                                            # Also cover a later argument's
                                            # failure in the multi-difference
                                            # wrapper, after a successful copy.
                                            if {operation!r} == 'difference':
                                                method((), failing(payload))
                                            else:
                                                method(failing(payload))
                                        except expected:
                                            pass
                                        else:
                                            raise AssertionError('no exception')
                                    completed.append(True)
                                except BaseException as exc:
                                    errors.append(exc)

                            gc.disable()
                            memory()
                            for _ in range(3):
                                gc.collect()
                            before = memory()
                            thread = threading.Thread(target=worker)
                            thread.start()
                            thread.join()
                            assert not errors, errors
                            assert completed == [True], completed
                            # Exiting the worker removes stale native stack
                            # roots. Abandoned untracked set bodies must not
                            # remain allocated after their elements are freed.
                            for _ in range(4):
                                gc.collect()
                            after = memory()
                            assert after - before < 32 * 1024, (before, after)
                        """)

    def test_failed_frozenset_subclass_is_reclaimed(self):
        self.run_python("""
            import gc, threading, weakref

            class Payload:
                pass
            def fail(iterator_error):
                class Frozen(frozenset):
                    pass
                value = Payload()
                value.data = bytes(65537)
                refs = weakref.ref(Frozen), weakref.ref(value)
                def source():
                    yield value
                    if iterator_error:
                        raise RuntimeError('iterator failed')
                    yield []
                try:
                    Frozen(source())
                except (TypeError, RuntimeError) as exc:
                    expected = RuntimeError if iterator_error else TypeError
                    assert type(exc) is expected, exc
                else:
                    raise AssertionError('constructor unexpectedly succeeded')
                return refs

            for iterator_error in (False, True):
                refs = []
                def make():
                    refs.extend(fail(iterator_error) for _ in range(32))
                # Drop the constructing thread's native stack as well as its
                # Python references before testing weakref reclamation. The
                # conservative scanner can otherwise retain old C temporaries.
                worker = threading.Thread(target=make)
                worker.start()
                worker.join()
                assert len(refs) == 32
                for _ in range(4):
                    gc.collect()
                assert sum(ref() is not None for pair in refs for ref in pair) < 4, (
                    iterator_error,
                    [i for i, pair in enumerate(refs) if pair[0]() is not None],
                    [i for i, pair in enumerate(refs) if pair[1]() is not None])
        """)

    def test_heap_stats_include_abandoned_storage(self):
        self.run_python("""
            import gc, threading
            from _testinternalcapi import get_tracing_gc_heap_stats

            gc.disable()
            roots = []
            errors = []
            def allocate():
                try:
                    roots.extend(bytes([i]) * 4097 for i in range(128))
                except BaseException as exc:
                    errors.append(exc)
            worker = threading.Thread(target=allocate)
            worker.start()
            worker.join()
            assert not errors, errors
            stats = get_tracing_gc_heap_stats()
            assert len(stats) == 10
            assert {(s['abandoned'], s['tag']) for s in stats} == {
                (abandoned, tag) for abandoned in range(2) for tag in range(5)}
            for row in stats:
                assert 0 <= row['allocated'] <= row['committed']
                assert 0 <= row['empty_committed'] <= row['committed']
                assert row['blocks'] >= 0 and row['areas'] >= 0
            abandoned = sum(row['allocated'] for row in stats if row['abandoned'])
            assert abandoned >= 128 * 4097, stats
            for _ in range(3):
                gc.collect()
                get_tracing_gc_heap_stats()
                assert roots == [bytes([i]) * 4097 for i in range(128)]
        """)

    def test_snapshot_sparse_abandoned_pages(self):
        self.run_python("""
            import gc, threading

            gc.disable()
            roots = []
            errors = []
            def allocate(epoch):
                try:
                    batch = []
                    for width in range(1, 33):
                        for i in range(512):
                            payload = bytes([width]) * (width * 16 + i % 16)
                            row = [epoch, width, i, payload, (None,) * width]
                            row.append(row)
                            batch.append(row)
                    roots.append(batch)
                except BaseException as exc:
                    errors.append(exc)

            for epoch in range(3):
                thread = threading.Thread(target=allocate, args=(epoch,))
                thread.start()
                thread.join()
                assert not errors, errors
                # Leave holes across differently sized abandoned pages.
                # Their free lists have unequal lengths, including empty
                # lists; later allocations may also reclaim these pages.
                survivors = roots.pop()[::113]
                for _ in range(3):
                    gc.collect()
                for row in survivors:
                    saved_epoch, width, i, payload, items, link = row
                    assert saved_epoch == epoch
                    assert payload == bytes([width]) * (width * 16 + i % 16)
                    assert items == (None,) * width
                    assert link is row
                del row, link, survivors
        """)

    def test_snapshot_allocation_failure_preserves_roots(self):
        self.run_python("""
            import _testcapi, gc, sys

            gc.disable()
            roots = [[i, {'payload': bytes([i % 251]) * (31 + i % 97)}]
                     for i in range(20000)]
            failures = []
            sys.unraisablehook = lambda event: failures.append(event.exc_type)
            for start in range(32):
                # Fail one allocation at successive positions, covering
                # partially built page tables and multiple mark chunks.
                _testcapi.set_nomemory(start, start + 1)
                try:
                    gc.collect()
                except MemoryError:
                    failures.append(MemoryError)
                finally:
                    _testcapi.remove_mem_hooks()
                gc.collect()
                for i, row in enumerate(roots):
                    assert row == [i, {'payload':
                                      bytes([i % 251]) * (31 + i % 97)}]
            assert failures and all(exc is MemoryError for exc in failures)
        """)

    def test_stopped_world_remote_pages_are_reused(self):
        self.run_soft_dirty("""
            import sys, threading

            gate = threading.Barrier(5, timeout=30)
            roots = [None] * 4
            errors = []
            retained = []
            def worker(seed):
                try:
                    for epoch in range(8):
                        gate.wait()
                        width = 7 if epoch % 2 else 31
                        for i in range(10000):
                            value = [seed, (i, None),
                                     {'value': i, 'payload': [i] * width},
                                     'payload-%d-%d' % (seed, i)]
                            value.append(value)
                        roots[seed] = value
                        gate.wait()
                except BaseException as exc:
                    errors.append(exc)
                    gate.abort()
            threads = [threading.Thread(target=worker, args=(seed,))
                       for seed in range(4)]
            prepare()
            for thread in threads:
                thread.start()
            try:
                for epoch in range(8):
                    gate.wait()
                    gate.wait()
                    # Reclaim pages while their owners are parked, then let
                    # those owners allocate from them in a different size mix.
                    for _ in range(3):
                        gc.collect()
                    retained.append(sys.getallocatedblocks())
                    for seed, value in enumerate(roots):
                        assert value[0] == seed and value[1] == (9999, None)
                        assert value[2] == {
                            'value': 9999,
                            'payload': [9999] * (7 if epoch % 2 else 31)}
                        assert value[3] == 'payload-%d-9999' % seed
                        assert value[4] is value
            except BaseException:
                gate.abort()
                raise
            finally:
                for thread in threads:
                    thread.join()
            assert not errors, errors
            assert any(events), events
            assert max(retained) - min(retained) < 10000, retained
            # Exited owners abandon their heaps. Later collections must use
            # the ordinary abandoned-page path, and preserve surviving roots.
            for _ in range(3):
                gc.collect()
            assert all(value[4] is value for value in roots)
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_with_threads(self):
        self.run_soft_dirty("""
            import threading
            ready = threading.Barrier(5)
            errors = []
            def worker(seed):
                try:
                    ready.wait()
                    for i in range(15000):
                        value = [seed, {'value': i, 'text': 'value-%d' % i}]
                        value.append((value,))
                        assert value[0] == seed and value[1]['value'] == i
                        assert value[2][0] is value
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(seed,))
                       for seed in range(4)]
            prepare()
            for thread in threads:
                thread.start()
            ready.wait()
            for thread in threads:
                thread.join()
            assert not errors, errors
            assert any(events), events
            gc.collect()
        """, args=("-X", "gil=0", "-X", "tlbc=1"), env_vars={
            "PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1", "PYTHON_JIT": "0"})

    def test_young_containers_periodic_full_gc(self):
        self.run_soft_dirty("""
            def churn():
                for i in range(20000):
                    value = [i, i + 0.25, 'payload-%d' % i]
            prepare()
            for _ in range(20):
                churn()
                if 0 in events:
                    break
            assert any(events) and 0 in events, events
            assert max(events) <= 7, events
            assert events.index(0) <= 7, events
            gc.collect()
            assert get_tracing_gc_state()['minors'] == 0
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_deferred_objects_force_full_gc(self):
        self.run_soft_dirty("""
            import weakref
            class Holder:
                __slots__ = tuple('slot_%d' % i for i in range(128)) + ('__weakref__',)
            def make():
                return [weakref.ref(Holder()) for _ in range(500)]
            prepare()
            gc.disable()
            refs = make()
            gc.enable()
            allocate_until(lambda: bool(events))
            assert events[0] == 0, events
            assert sum(ref() is not None for ref in refs) < 5
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def check_deferred_descendants(self, *, reachable=False, shared=None,
                                   resurrected=False, abandoned=False):
        source = """
            import threading
            import weakref
            roots, refs, saved, calls = [], [], [], []
            class Holder:
                __slots__ = ('payload', 'link', 'number', '__weakref__')
                if RESURRECTED:
                    def __del__(self):
                        calls.append(self.number)
                        if self.number < 3:
                            saved.append(self)
            def make():
                # Leave room for allocator size-class rounding as well as
                # headers: a 512 KiB payload occupies almost 1 MiB here.
                private_child = bytes([42]) * (256 << 10) if SHARED == 'private' else None
                for i in range(32):
                    obj = Holder()
                    obj.number = i
                    if SHARED in ('old', 'new'):
                        child = shared_children[i]
                    elif SHARED == 'private':
                        child = private_child
                    else:
                        child = bytes([i]) * (128 << 10)
                    obj.payload = [child]
                    obj.link = obj
                    refs.append(weakref.ref(obj))
                    if REACHABLE:
                        roots.append(obj)
            gc.disable()
            shared_children = ([bytes([i]) * (128 << 10) for i in range(32)]
                               if SHARED == 'old' else None)
            prepare()
            gc.disable()
            gc.set_threshold(2000)
            if SHARED == 'new':
                shared_children = [bytes([i]) * (128 << 10) for i in range(32)]
            if ABANDONED:
                thread = threading.Thread(target=make)
                thread.start()
                thread.join()
            else:
                make()
            gc.enable()
            for i in range(1000000):
                value = [i, {'value': i}]
                if events:
                    break
            gc.disable()
            assert events, events
            if REACHABLE or SHARED:
                # Neither truly live children nor shared old data should be
                # charged to the nursery's deferred-garbage budget.
                assert events[0] > 0, events
                assert all(ref() is not None for ref in refs)
                for i, ref in enumerate(refs):
                    payload = ref().payload[0]
                    if SHARED == 'private':
                        # Thirty-two edges to one unreachable child must not
                        # charge its storage thirty-two times.
                        assert len(payload) == 256 << 10
                        assert payload[0] == payload[-1] == 42
                    else:
                        assert len(payload) == 128 << 10
                        assert payload[0] == payload[-1] == i
            else:
                # The tiny instance bodies fit the budget, but the 4 MiB of
                # children they would retain do not. Use full GC immediately.
                assert events[0] == 0, events
                assert get_tracing_gc_state()['pid'] == 0
                assert sum(ref() is not None for ref in refs) < 5
                if RESURRECTED:
                    assert len(calls) > 27, calls
                    assert sorted(obj.number for obj in saved) == [0, 1, 2]
                    for obj in saved:
                        assert obj.link is obj
                        payload = obj.payload[0]
                        assert len(payload) == 128 << 10
                        assert payload[0] == payload[-1] == obj.number
        """
        for name, value in {"REACHABLE": reachable, "SHARED": shared,
                            "RESURRECTED": resurrected,
                            "ABANDONED": abandoned}.items():
            source = source.replace(name, repr(value))
        self.run_soft_dirty(source,
            args=("-X", "gil=0", "-X", "tlbc=1") if abandoned else (),
            env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1",
                      **({"PYTHON_JIT": "0"} if abandoned else {})})

    def test_young_containers_deferred_descendants_force_full_gc(self):
        self.check_deferred_descendants()

    def test_young_containers_reachable_descendants_allow_minor_gc(self):
        self.check_deferred_descendants(reachable=True)

    def test_young_containers_shared_old_descendants_allow_minor_gc(self):
        self.check_deferred_descendants(shared='old')

    def test_young_containers_shared_new_descendants_allow_minor_gc(self):
        self.check_deferred_descendants(shared='new')

    def test_young_containers_deferred_descendants_counted_once(self):
        self.check_deferred_descendants(shared='private')

    def test_young_containers_deferred_descendants_resurrection(self):
        self.check_deferred_descendants(resurrected=True)

    def test_young_containers_deferred_descendants_in_abandoned_heap(self):
        self.check_deferred_descendants(abandoned=True)

    def check_young_container_backoff(self, manual):
        self.run_soft_dirty("""
            import weakref
            class Holder:
                __slots__ = tuple('slot_%d' % i for i in range(128)) + ('__weakref__',)
            def make():
                return [weakref.ref(Holder()) for _ in range(500)]
            def next_collection():
                previous = len(events)
                for i in range(1000000):
                    value = [i, i + 0.25, 'payload-%d' % i]
                    if len(events) != previous:
                        assert len(events) == previous + 1, events
                        return
                raise AssertionError(('no collection', events))
            prepare()
            gc.disable()
            refs = make()
            gc.enable()
            next_collection()
            assert events == [0], events
            assert sum(ref() is not None for ref in refs) < 5
            # Do not immediately write-protect the heap and attempt another
            # nursery traversal after unsupported-young pressure forced full GC.
            assert get_tracing_gc_state()['pid'] == 0
            if MANUAL:
                gc.collect()
                assert get_tracing_gc_state()['pid'] != 0
            else:
                # A supported-container phase must eventually get a new epoch
                # and nursery collections, without an explicit full collection.
                for _ in range(2):
                    next_collection()
                    assert events[-1] == 0, events
                    assert get_tracing_gc_state()['pid'] == 0
                next_collection()
                assert events[-1] == 0, events
                assert get_tracing_gc_state()['pid'] != 0
            next_collection()
            assert events[-1] > 0, events
        """.replace("MANUAL", repr(manual)),
            env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_backoff_and_retry(self):
        self.check_young_container_backoff(False)

    def test_young_containers_manual_collection_ends_backoff(self):
        self.check_young_container_backoff(True)

    def test_young_containers_old_opaque_objects_allow_minor_gc(self):
        self.run_soft_dirty("""
            class Holder:
                __slots__ = tuple('slot_%d' % i for i in range(128))
            roots = [Holder() for _ in range(500)]
            for i, obj in enumerate(roots):
                obj.slot_0 = ['live', i]
            prepare()
            for _ in range(64):
                for i in range(10000):
                    value = [i, {'payload': i}]
                if events:
                    break
            assert events and events[0] > 0, events
            assert all(obj.slot_0 == ['live', i] for i, obj in enumerate(roots))
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def check_old_opaque_age(self, *, resurrected=False, abandoned=False):
        self.run_soft_dirty("""
            import threading
            import weakref
            roots, refs, calls = [], [], []
            class Holder:
                __slots__ = tuple('slot_%d' % i for i in range(128)) + ('__weakref__',)
                if RESURRECTED:
                    def __del__(self):
                        calls.append(self.slot_0[1])
                        roots.append(self)
            def make():
                for i in range(500):
                    obj = Holder()
                    obj.slot_0 = ['live', i]
                    refs.append(weakref.ref(obj))
                    if not RESURRECTED:
                        roots.append(obj)
            gc.disable()
            if ABANDONED:
                thread = threading.Thread(target=make)
                thread.start()
                thread.join()
            else:
                make()
            prepare()
            gc.disable()
            if not RESURRECTED:
                # Startup finalizers can cause a second root traversal and
                # accidentally restore age bits cleared by the fast full GC.
                # A subsequent full collection must preserve that age too.
                gc.collect()
            assert len(roots) > 495, len(roots)
            if RESURRECTED:
                assert len(calls) == len(roots)
            # Old opaque objects must still trace newly assigned children.
            # Do not keep another reference to these lists across the minor.
            for obj in roots:
                obj.slot_0 = ['new', obj.slot_0[1]]
            del obj
            events.clear()
            gc.enable()
            for _ in range(64):
                for i in range(10000):
                    value = [i, {'payload': i}]
                if events:
                    break
            gc.disable()
            assert events and events[0] > 0, events
            for i, ref in enumerate(refs):
                obj = ref()
                assert obj is not None
                if obj in roots:
                    assert obj.slot_0 == ['new', i]
            del obj
            # Promotion is not immortality: a full collection must ignore
            # the previous live marks once the strong roots are removed.
            roots.clear()
            for _ in range(3):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 5
            assert len(calls) == len(set(calls))
        """.replace("RESURRECTED", repr(resurrected))
           .replace("ABANDONED", repr(abandoned)),
            args=("-X", "gil=0", "-X", "tlbc=1") if abandoned else (),
            env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1",
                      **({"PYTHON_JIT": "0"} if abandoned else {})})

    def test_young_containers_old_opaque_age_after_full_gc(self):
        self.check_old_opaque_age()

    def test_young_containers_resurrected_opaque_age(self):
        self.check_old_opaque_age(resurrected=True)

    def test_young_containers_old_opaque_age_in_abandoned_heap(self):
        self.check_old_opaque_age(abandoned=True)

    def test_young_containers_deferred_objects_in_abandoned_heap(self):
        self.run_soft_dirty("""
            import threading, weakref
            class Holder:
                __slots__ = tuple('slot_%d' % i for i in range(128)) + ('__weakref__',)
            refs = []
            def worker():
                for _ in range(1000):
                    refs.append(weakref.ref(Holder()))
            prepare()
            gc.disable()
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            gc.enable()
            allocate_until(lambda: bool(events))
            assert events[0] == 0, events
            assert sum(ref() is not None for ref in refs) < 5
        """, args=("-X", "gil=0", "-X", "tlbc=1"), env_vars={
            "PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1", "PYTHON_JIT": "0"})

    def test_young_containers_fallback_with_resurrection(self):
        self.run_soft_dirty("""
            import weakref
            calls, saved = [], []
            roots = [None] * 64
            class Holder:
                __slots__ = (tuple('slot_%d' % i for i in range(128)) +
                             ('number', 'payload', '__weakref__'))
                def __del__(self):
                    calls.append(self.number)
                    if self.number < 3:
                        # These references do not exist in the allocation
                        # snapshot that triggered the full-GC fallback.
                        self.payload = [{'number': self.number},
                                        'resurrected-%d' % self.number]
                        saved.append(self)
            def make():
                refs = []
                for i in range(500):
                    obj = Holder()
                    obj.number = i
                    obj.payload = ['original', i]
                    refs.append(weakref.ref(obj))
                return refs
            prepare()
            gc.disable()
            # These private list/dict buffers are classified before an early
            # nursery fallback. Full tracing must restore their unmarked state
            # and follow their contents from the retained owner, even though
            # the owner list itself belongs to the preceding full-GC epoch.
            for i in range(len(roots)):
                row = ['retained-%d' % i, {'values': list(range(17 + i))}]
                row.append(row)
                roots[i] = row
            refs = make()
            gc.enable()
            allocate_until(lambda: bool(events))
            assert events[0] == 0, events
            assert len(calls) > 495, len(calls)
            assert sorted(obj.number for obj in saved) == [0, 1, 2]
            for _ in range(3):
                gc.collect()
                for i, row in enumerate(roots):
                    assert row[0] == 'retained-%d' % i
                    assert row[1] == {'values': list(range(17 + i))}
                    assert row[2] is row
                for obj in saved:
                    assert obj.payload == [{'number': obj.number},
                                           'resurrected-%d' % obj.number]
            assert sum(ref() is not None for ref in refs) < 5
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_external_and_watched_roots(self):
        self.run_soft_dirty("""
            import _testcapi
            external = _testcapi.GCExternalBuffer()
            watcher = _testcapi.add_dict_watcher(0)
            def make():
                external.value = ['external', {'payload': list(range(100))}]
                value = {'payload': ['watched', list(range(100))]}
                _testcapi.watch_dict(watcher, value)
            def churn():
                for i in range(10000):
                    value = [i, {'payload': i}]
            try:
                prepare()
                gc.disable()
                make()
                churn()
                gc.enable()
                allocate_until(lambda: bool(events))
                assert events[0] > 0, events
                # The only owner is in a C-allocated buffer, outside mimalloc.
                assert external.value == [
                    'external', {'payload': list(range(100))}]
                assert not _testcapi.get_dict_watcher_events()
                for _ in range(3):
                    gc.collect()
                assert 'dealloc' in _testcapi.get_dict_watcher_events()
            finally:
                _testcapi.clear_dict_watcher(watcher)
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_split_and_large_storage(self):
        self.run_soft_dirty("""
            class Node:
                pass
            nodes = [Node() for _ in range(32)]
            for node in nodes:
                node.payload = None
            roots = []
            def install():
                for i, node in enumerate(nodes):
                    node.payload = ['young-%d' % i, {'value': i}]
                    original = node.__dict__
                    copied = original.copy()
                    node.__dict__ = {}
                    roots.append((original, copied))
                roots.append([['large-%d' % i] for i in range(20000)])
            def churn():
                for i in range(10000):
                    value = [i, {'payload': i}]
            prepare()
            install()
            for _ in range(64):
                churn()
                if any(events):
                    break
            assert any(events), events
            for i, (original, copied) in enumerate(roots[:-1]):
                assert original['payload'] == ['young-%d' % i, {'value': i}]
                assert copied['payload'] is original['payload']
            assert roots[-1] == [['large-%d' % i] for i in range(20000)]
            gc.collect()
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_external_reset(self):
        self.run_soft_dirty("""
            def churn():
                for i in range(10000):
                    value = [i, {'payload': i}]
            prepare()
            with open('/proc/self/clear_refs', 'w') as stream:
                stream.write('4')
            for _ in range(64):
                churn()
                if events:
                    break
            assert events and events[0] == 0, events
            assert get_tracing_gc_state()['pid'] == os.getpid()
            events.clear()
            for _ in range(64):
                churn()
                if any(events):
                    break
            assert any(events), events
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_young_containers_saveall_uses_full_gc(self):
        self.run_soft_dirty("""
            marker = object()
            def make():
                for i in range(10000):
                    value = [marker, {'number': i}]
                    value.append(value)
            prepare()
            gc.set_debug(gc.DEBUG_SAVEALL)
            try:
                for _ in range(64):
                    make()
                    if events:
                        break
                assert events and not any(events), events
                retained = [obj for obj in gc.garbage
                            if type(obj) is list and len(obj) == 3 and
                            obj[0] is marker]
                assert len(retained) > 1000, len(retained)
                assert all(obj[2] is obj for obj in retained)
            finally:
                gc.set_debug(0)
                gc.garbage.clear()
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_soft_dirty_old_containers_keep_young_leaves(self):
        self.run_soft_dirty("""
            class Holder:
                pass
            holder = Holder()
            holder.value = None
            sequence = [None]
            mapping = {'value': None}
            members = set()
            def install(n):
                sequence[0] = n + 0.125
                mapping['value'] = (1 << 100) + n
                holder.value = 'young-leaf-%d' % n
                members.add(b'young-bytes-%d' % n)
            prepare()
            for n in range(3):
                install(n)
                target = len(events) + 1
                allocate_until(lambda: len(events) >= target)
                assert events[-1] > 0, events
                assert sequence[0] == n + 0.125
                assert mapping['value'] == (1 << 100) + n
                assert holder.value == 'young-leaf-%d' % n
                assert b'young-bytes-%d' % n in members
            # Previously promoted leaves still live in these old containers.
            assert members == {b'young-bytes-%d' % n for n in range(3)}
            gc.collect()
            assert get_tracing_gc_state()['minors'] == 0
        """)

    def test_soft_dirty_external_traversal(self):
        self.run_soft_dirty("""
            from _testcapi import GCExternalBuffer
            holders = [GCExternalBuffer() for _ in range(128)]
            def install():
                for n, holder in enumerate(holders):
                    holder.value = 'external-young-%d' % n
            prepare()
            install()
            allocate_until(lambda: bool(events))
            assert events[-1] > 0, events
            target = len(events) + 1
            allocate_until(lambda: len(events) >= target)
            assert [holder.value for holder in holders] == [
                'external-young-%d' % n for n in range(128)]
        """)

    def test_soft_dirty_external_reset_forces_full_collection(self):
        self.run_soft_dirty("""
            holder = [None]
            prepare()
            allocate_until(lambda: bool(events))
            assert events[-1] > 0, events
            holder[0] = 'written-before-reset-%d' % 12345
            fd = os.open('/proc/self/clear_refs', os.O_WRONLY)
            try:
                assert os.write(fd, b'4') == 1
            finally:
                os.close(fd)
            target = len(events) + 1
            allocate_until(lambda: len(events) >= target)
            assert events[-1] == 0, events
            assert holder[0] == 'written-before-reset-12345'
        """)

    def test_soft_dirty_new_mappings_do_not_hide_reset(self):
        self.run_soft_dirty("""
            import mmap
            holder = [None]
            prepare()
            gc.disable()
            holder[0] = 'written-before-mapping-%d' % 12345
            fd = os.open('/proc/self/clear_refs', os.O_WRONLY)
            try:
                assert os.write(fd, b'4') == 1
            finally:
                os.close(fd)
            # A fresh mapping can merge with a neighboring anonymous VMA
            # and make it soft-dirty without any write to its old pages.
            mappings = [mmap.mmap(-1, mmap.PAGESIZE,
                         flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
                        for _ in range(16)]
            try:
                gc.enable()
                allocate_until(lambda: bool(events))
                assert events[0] == 0, events
                assert holder[0] == 'written-before-mapping-12345'
            finally:
                for mapping in mappings:
                    mapping.close()
        """, env_vars={"PYTHON_JIT": "0"})

    def test_soft_dirty_periodic_full_collection(self):
        self.run_soft_dirty("""
            import weakref
            class Node:
                def __init__(self):
                    self.cycle = self
            old = [Node() for _ in range(1000)]
            refs = [weakref.ref(node) for node in old]
            prepare()
            old.clear()
            allocate_until(lambda: any(events))
            assert all(ref() is not None for ref in refs)
            allocate_until(lambda: 0 in events)
            assert 0 < max(events) <= 7, events
            assert events.index(0) <= 7, events
            assert sum(ref() is None for ref in refs) > 950
            # New epochs must continue collecting, not retain every promoted
            # leaf forever. Explicit collection must always end the epoch.
            events.clear()
            allocate_until(lambda: any(events))
            gc.collect()
            assert get_tracing_gc_state()['minors'] == 0
        """)

    def test_soft_dirty_nonleaf_pressure_forces_full_collection(self):
        self.run_soft_dirty("""
            prepare()
            for batch in range(64):
                values = [[None] * 1024 for _ in range(32)]
                if events:
                    break
            assert events and events[0] == 0, events
            assert get_tracing_gc_state()['pid'] == 0
            assert all(len(value) == 1024 for value in values)
        """)

    def test_soft_dirty_mixed_allocation_avoids_nursery(self):
        self.run_soft_dirty("""
            prepare()
            for batch in range(64):
                for i in range(4096):
                    value = [i, i + 0.25, 'payload-%d' % i]
                if events:
                    break
            assert events and not any(events), events
            assert get_tracing_gc_state()['pid'] == 0
            # A later scalar-only phase can establish a new baseline.
            events.clear()
            allocate_until(lambda: any(events))
        """)

    def test_soft_dirty_subinterpreters_use_full_collection(self):
        self.run_soft_dirty("""
            import _interpreters
            prepare()
            other = _interpreters.create()
            try:
                gc.collect()
                assert get_tracing_gc_state()['pid'] == 0
                events.clear()
                allocate_until(lambda: bool(events))
                assert not any(events), events
                error = _interpreters.run_string(other,
                    "import gc, _testinternalcapi; gc.collect(); "
                    "assert _testinternalcapi.get_tracing_gc_state()['pid'] == 0")
                assert error is None, error
            finally:
                _interpreters.destroy(other)
            prepare()
            allocate_until(lambda: any(events))
        """, env_vars={"PYTHON_JIT": "0"})

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_soft_dirty_fork_starts_new_epoch(self):
        self.run_soft_dirty("""
            prepare()
            allocate_until(lambda: any(events))
            pid = os.fork()
            if pid == 0:
                try:
                    events.clear()
                    allocate_until(lambda: bool(events))
                    assert events[0] == 0, events
                    assert get_tracing_gc_state()['pid'] == os.getpid()
                    allocate_until(lambda: any(events))
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    os._exit(1)
                os._exit(0)
            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0, status
        """, env_vars={"PYTHON_JIT": "0"})

    def test_soft_dirty_free_threaded_stack_root(self):
        self.run_soft_dirty("""
            import threading
            assert not sys._is_gil_enabled()
            begin = threading.Event()
            ready = threading.Event()
            finish = threading.Event()
            errors = []
            def worker():
                try:
                    begin.wait()
                    value = float('12345.125')
                    ready.set()
                    finish.wait()
                    assert value == 12345.125
                except BaseException as exc:
                    errors.append(exc)
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                prepare()
                begin.set()
                assert ready.wait(10)
                allocate_until(lambda: any(events))
            finally:
                begin.set()
                finish.set()
                thread.join()
            assert not errors, errors
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_live_python_stack_root(self):
        self.run_python("""
            import gc
            root = [[1, 2, 3]]
            for _ in range(20):
                gc.collect()
                assert root == [[1, 2, 3]]
        """)

    def test_container_reads_do_not_update_refcounts(self):
        self.run_python("""
            import gc
            from _testinternalcapi import get_tracing_gc_refstate
            class Holder:
                __slots__ = ('value',)
            value = float('12345.125')
            sequence = [value]
            mapping = {'value': value}
            holder = Holder()
            holder.value = value
            def make_reader(value):
                return lambda: value
            reader = make_reader(value)
            gc.disable()
            before = get_tracing_gc_refstate(value)
            for _ in range(10000):
                assert sequence[0] is value
                assert mapping['value'] is value
                assert holder.value is value
                assert reader() is value
            after = get_tracing_gc_refstate(value)
            assert after == before, (before, after)
        """)

    def test_optimistic_reads_preserve_alias_information(self):
        self.run_python("""
            from _testinternalcapi import test_tracing_gc_tryref_alias
            test_tracing_gc_tryref_alias()
        """)

    def test_cross_thread_reads_do_not_update_refcounts(self):
        self.run_python("""
            import gc
            import threading
            from _testinternalcapi import get_tracing_gc_refstate
            ready = threading.Event()
            finish = threading.Event()
            roots = []
            def owner():
                value = float('12345.125')
                roots.append(value)
                ready.set()
                finish.wait()
                assert value == 12345.125
            gc.disable()
            thread = threading.Thread(target=owner)
            thread.start()
            try:
                assert ready.wait(10)
                value = roots[0]
                mapping = {'value': value}
                before = get_tracing_gc_refstate(value)
                for _ in range(10000):
                    assert roots[0] is value
                    assert mapping['value'] is value
                after = get_tracing_gc_refstate(value)
                assert after == before, (before, after)
            finally:
                finish.set()
                thread.join()
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_optimistic_reads_during_replacement_and_gc(self):
        self.run_python("""
            import gc
            import threading
            class Holder:
                __slots__ = ('value',)
            holder = Holder()
            holder.value = float('0.25')
            sequence = [holder.value]
            mapping = {'value': holder.value}
            ready = threading.Barrier(5)
            errors = []
            def writer():
                try:
                    ready.wait()
                    for i in range(20000):
                        value = i + 0.25
                        holder.value = value
                        sequence[:] = [value]
                        mapping['value'] = value
                        if i % 17 == 0:
                            sequence.clear()
                            mapping.clear()
                except BaseException as exc:
                    errors.append(exc)
            def reader():
                try:
                    ready.wait()
                    for i in range(10000):
                        try:
                            a = sequence[0]
                            b = mapping['value']
                        except (IndexError, KeyError):
                            continue
                        c = holder.value
                        for value in (a, b, c):
                            assert type(value) is float
                            assert 0.25 <= value <= 19999.25
                            before = value.hex()
                            changed = (value + 1.0) * 2.0
                            assert value.hex() == before
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=writer)] + [
                threading.Thread(target=reader) for _ in range(3)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(30):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_deferred_decrefs_do_not_zero_live_headers(self):
        self.run_python("""
            import enum
            import gc
            # Enum construction replaces temporary descriptors through the
            # delayed decref queue. A conservative edge may retain one.
            for _ in range(10):
                gc.collect()
            assert enum.IntEnum.__name__ == 'IntEnum'
        """)

    def test_float_temporary_allocation(self):
        self.run_python("""
            import gc
            import sys
            def calculate(n):
                for i in range(n):
                    value = ((i + 0.25) * 0.5 - 0.125) + 0.25
                return value
            calculate(100)
            gc.disable()
            gc.collect()
            before = sys.getallocatedblocks()
            assert calculate(20000) == 9999.75
            allocated = sys.getallocatedblocks() - before
            # One integer and one float per iteration, plus small overhead.
            # Without reuse, the three subsequent float ops allocate too.
            assert allocated < 60000, allocated
        """, env_vars={"PYTHON_JIT": "0"})

    def test_float_reuse_preserves_borrowed_locals(self):
        self.run_python("""
            import gc
            def calculate():
                # Fresh, singly-owned objects, but the operand stack borrows
                # them from locals. They must not be mutated by arithmetic.
                x = float('3.25')
                y = float('-1.5')
                values = (x + y, x - y, x * y, x / y)
                chained = ((x + 0.25) * 2.0) - 0.5
                right = 10.0 - (y * 2.0)
                assert x == 3.25 and y == -1.5
                assert values == (1.75, 4.75, -4.875, -13.0 / 6.0)
                assert chained == 6.5 and right == 13.0
            def exercise():
                for i in range(10000):
                    calculate()
                    if i % 1000 == 0:
                        gc.collect()
            exercise()
        """)

    def test_float_reuse_preserves_shared_values(self):
        self.run_python("""
            import gc
            import threading
            shared = (float('3.25'), float('-1.5'))
            errors = []
            def worker():
                try:
                    for i in range(5000):
                        x, y = shared
                        assert (x + y) * 2.0 == 3.5
                        assert 10.0 - (x * y) == 14.875
                        assert shared == (3.25, -1.5)
                        if i % 1000 == 0:
                            gc.collect()
                except BaseException as exc:
                    errors.append(exc)
            def exercise():
                threads = [threading.Thread(target=worker) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                assert not errors, errors
                assert shared == (3.25, -1.5)
            exercise()
        """)

    def test_get_count_reports_byte_debt(self):
        self.run_python("""
            import gc
            gc.disable()
            gc.collect()
            before = gc.get_count()[0]
            payload = bytes(1 << 20)
            after = gc.get_count()[0]
            # A single scalar allocation contributes its size, not one
            # tracked object. Allow a little call/tuple/debug overhead.
            assert 256 <= after - before < 264, (before, after)
            assert len(payload) == 1 << 20
            gc.collect()
            assert gc.get_count()[0] < 8
            assert len(payload) == 1 << 20
        """)

    def test_get_count_includes_local_byte_debt(self):
        self.run_python("""
            import gc
            gc.disable()
            gc.collect()
            before = gc.get_count()[0]
            # This is below the allocator's 256 KiB publication batch.
            payload = bytes(64 << 10)
            after = gc.get_count()[0]
            assert 16 <= after - before < 24, (before, after)
            assert len(payload) == 64 << 10
        """)

    def test_get_count_includes_exited_thread_byte_debt(self):
        self.run_python("""
            import gc
            import threading
            roots = []
            def allocate():
                roots.append(bytes(64 << 10))
            gc.disable()
            gc.collect()
            before = gc.get_count()[0]
            for _ in range(8):
                thread = threading.Thread(target=allocate)
                thread.start()
                thread.join()
            after = gc.get_count()[0]
            assert after - before >= 128, (before, after)
            assert len(roots) == 8
            assert all(len(payload) == 64 << 10 for payload in roots)
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_short_lived_threads_preserve_allocation_debt(self):
        self.run_python("""
            import gc
            import sys
            import threading
            from _testinternalcapi import make_tracing_gc_boxed_float
            def allocate():
                # Each thread allocates less than the 256 KiB local batch,
                # but together they must exceed the automatic-GC budget.
                # Force real heap allocation even with immediate floats.
                for i in range(1000):
                    make_tracing_gc_boxed_float(i)
            gc.disable()
            gc.collect()
            gc.set_threshold(1024)
            before = sum(s['collections'] for s in gc.get_stats())
            for _ in range(128):
                thread = threading.Thread(target=allocate)
                thread.start()
                thread.join()
            allocated = sys.getallocatedblocks()
            assert sum(s['collections'] for s in gc.get_stats()) == before
            gc.enable()
            # Flush a main-thread batch, without independently reaching the
            # 4 MiB budget. Debt from the exited threads must trigger GC.
            for i in range(8000):
                make_tracing_gc_boxed_float(i)
            assert sum(s['collections'] for s in gc.get_stats()) > before
            remaining = sys.getallocatedblocks()
            assert allocated - remaining > 100000, (allocated, remaining)
        """, env_vars={"PYTHON_JIT": "0"})

    def test_exiting_thread_schedules_gc_for_survivor(self):
        self.run_python("""
            import gc
            import threading
            from _testinternalcapi import make_tracing_gc_boxed_float
            def allocate():
                for i in range(1000):
                    make_tracing_gc_boxed_float(i)
            gc.disable()
            gc.collect()
            gc.set_threshold(1024)
            before = sum(s['collections'] for s in gc.get_stats())
            for _ in range(128):
                thread = threading.Thread(target=allocate)
                thread.start()
                thread.join()
            assert sum(s['collections'] for s in gc.get_stats()) == before
            gc.enable()
            # The next thread exits with debt already above the budget. The
            # surviving main thread must collect without allocating a batch.
            thread = threading.Thread(target=allocate)
            thread.start()
            thread.join()
            assert sum(s['collections'] for s in gc.get_stats()) > before
        """, env_vars={"PYTHON_JIT": "0"})

    def test_native_c_roots(self):
        from test.support import import_helper
        import_helper.import_module("_testcapi")
        self.run_python("""
            import gc
            from _testcapi import test_tracing_gc_c_roots
            test_tracing_gc_c_roots(gc.collect)
            def churn():
                for i in range(500000):
                    str(i)
            gc.set_threshold(256)
            before = gc.get_stats()[0]['collections']
            test_tracing_gc_c_roots(churn)
            assert gc.get_stats()[0]['collections'] > before
        """)

    def test_automatic_leaf_reclamation(self):
        self.run_python("""
            import gc
            import sys
            gc.set_threshold(512)
            keep = [str(i) for i in range(1000000, 1000100)]
            before = gc.get_stats()[0]['collections']
            initial_blocks = sys.getallocatedblocks()
            for batch in range(30):
                for i in range(20000):
                    i + 1000000
                    i + 0.25
                    str(i)
                    b'%d' % i
                    complex(i, 0.25)
                assert keep == [str(i) for i in range(1000000, 1000100)]
            assert gc.get_stats()[0]['collections'] > before + 5
            assert sys.getallocatedblocks() - initial_blocks < 100000
        """)

    def test_disabling_automatic_collection(self):
        self.run_python("""
            import gc
            import sys
            gc.disable()
            gc.set_threshold(256)
            before = gc.get_stats()[0]['collections']
            blocks = sys.getallocatedblocks()
            for i in range(200000):
                str(i)
            assert gc.get_stats()[0]['collections'] == before
            assert sys.getallocatedblocks() - blocks > 150000
            gc.enable()
            for i in range(200000):
                str(i)
            assert gc.get_stats()[0]['collections'] > before
            assert sys.getallocatedblocks() - blocks < 100000
        """)

    def test_automatic_cycles_are_reclaimed(self):
        self.run_python("""
            import gc
            import weakref
            gc.set_threshold(512)
            class Node:
                pass
            def make():
                refs = []
                for i in range(10000):
                    node = Node()
                    node.cycle = iter({node})
                    refs.append(weakref.ref(node))
                return refs
            refs = make()
            for i in range(500000):
                str(i)
            # Conservative C roots can delay individual objects, but must
            # not retain the collection of independent cycles indefinitely.
            assert sum(ref() is None for ref in refs) > 9500
        """)

    def test_automatic_collection_with_threads(self):
        self.run_python("""
            import gc
            import threading
            gc.set_threshold(512)
            before = gc.get_stats()[0]['collections']
            errors = []
            ready = threading.Barrier(4)
            def worker(seed):
                try:
                    keep = ['root-%d-%d' % (seed, i) for i in range(100)]
                    ready.wait()
                    for batch in range(20):
                        for i in range(10000):
                            str(i + 1000000)
                        assert keep == ['root-%d-%d' % (seed, i)
                                        for i in range(100)]
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert not errors, errors
            assert gc.get_stats()[0]['collections'] > before
        """)

    def test_collect_cycle(self):
        self.run_python("""
            import gc
            import weakref
            class Node:
                pass
            def make_cycle():
                node = Node()
                node.link = node
                return weakref.ref(node)
            refs = [make_cycle() for _ in range(100)]
            for _ in range(10):
                tuple(range(1000))
                gc.collect()
                if any(ref() is None for ref in refs):
                    break
            assert any(ref() is None for ref in refs)
        """)

    def test_static_argument_parser_root(self):
        self.run_python("""
            import gc
            # Initialize min()'s lazily cached _PyArg_Parser keyword tuple.
            assert min([2, 1], default=0) == 1
            for _ in range(20):
                tuple(range(1000))
                gc.collect()
                assert min([], default=42) == 42
        """)

    def test_finalizer_resurrection(self):
        self.run_python("""
            import gc
            saved = []
            finalized = []
            class Node:
                def __del__(self):
                    finalized.append(self.number)
                    saved.append(self)
            def make_cycles():
                for number in range(100):
                    node = Node()
                    node.number = number
                    node.child = [number]
                    node.link = node
            make_cycles()
            for _ in range(5):
                gc.collect()
            assert saved
            assert len(finalized) == len(set(finalized))
            for node in saved:
                assert node.link is node
                assert node.child == [node.number]
            saved.clear()
            for _ in range(5):
                gc.collect()
            assert len(finalized) == len(set(finalized))
        """)

    def test_lru_cache_after_reference_inspection(self):
        self.run_python("""
            import functools, gc
            for size in (None, 0, 4):
                @functools.lru_cache(maxsize=size)
                def cached(n):
                    return n * n
                cached(42)
                gc.get_referents(cached)
                for _ in range(3):
                    for n in range(30):
                        assert cached(n) == n * n
                    gc.collect()
                    cached.cache_clear()
                    assert cached.cache_info().currsize == 0
        """)

    def test_lru_cache_inspection_with_threads(self):
        self.run_python("""
            import functools, gc, threading
            @functools.lru_cache(maxsize=4)
            def cached(n):
                return n * n
            cached(42)
            gc.get_referents(cached)
            ready = threading.Barrier(5)
            errors = []
            def worker(seed):
                try:
                    ready.wait()
                    for i in range(1000):
                        n = (i + seed) % 20
                        assert cached(n) == n * n
                        if i % 50 == 0:
                            cached.cache_clear()
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(seed,))
                       for seed in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(10):
                gc.get_referents(cached)
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
            assert cached.cache_info().currsize <= 4
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_static_extension_type_roots(self):
        from test.support import import_helper
        import_helper.import_module('xxsubtype')
        self.run_python("""
            import gc, xxsubtype
            for _ in range(5):
                gc.collect()
                cls = xxsubtype.spamlist
                assert cls.classmeth(1, x=2) == (cls, (1,), {'x': 2})
                assert cls.__mro__ == (cls, list, object)
                value = cls([1, 2])
                value.append(3)
                assert value == [1, 2, 3]
                assert value.getstate() == 0
                value.setstate(42)
                assert value.getstate() == 42
                mapping = xxsubtype.spamdict(answer=42)
                assert mapping['answer'] == 42
                assert mapping.getstate() == 0
        """)

    def test_managed_static_extension_type_roots(self):
        self.run_python("""
            import _datetime as dt
            import gc
            for _ in range(5):
                gc.collect()
                assert dt.datetime.__mro__ == (dt.datetime, dt.date, object)
                assert dt.timedelta.__mro__ == (dt.timedelta, object)
                assert dt.date.fromisoformat('2026-09-06').isoformat() == '2026-09-06'
                value = dt.datetime(2026, 9, 6, tzinfo=dt.timezone.utc)
                assert value.isoformat() == '2026-09-06T00:00:00+00:00'
                assert dt.timedelta.resolution.total_seconds() == 0.000001
        """)

    def test_static_type_c_only_roots(self):
        self.run_python("""
            import gc
            from _testcapi import (get_tracing_gc_static_type as get_type,
                                  set_tracing_gc_static_type_payload as install)
            # Neither the module nor Python locals retain the type or its
            # dictionary. Native code can still reuse it after collection.
            install(['native-root-%d' % i for i in range(100)])
            for _ in range(5):
                gc.collect()
            cls = get_type()
            assert cls.__mro__ == (cls, list, object)
            assert cls.payload == ['native-root-%d' % i for i in range(100)]
            assert cls([1, 2]) == [1, 2]
        """)

    def test_static_type_replaced_payload_is_reclaimed(self):
        self.run_python("""
            import gc, weakref
            from _testcapi import (get_tracing_gc_static_type as get_type,
                                  set_tracing_gc_static_type_payload as install)
            class Payload:
                pass
            def replace():
                refs = []
                for i in range(1000):
                    value = Payload()
                    value.link = value
                    value.number = i
                    install(value)
                    refs.append(weakref.ref(value))
                return refs
            refs = replace()
            for _ in range(5):
                gc.collect()
            assert get_type().payload.number == 999
            assert sum(ref() is not None for ref in refs) < 5
            install(None)
            for _ in range(5):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 5
        """)

    def test_static_type_subclasses_are_reclaimed(self):
        self.run_python("""
            import gc, weakref
            from _testcapi import get_tracing_gc_static_type
            base = get_tracing_gc_static_type()
            def make():
                refs = []
                for i in range(1000):
                    cls = type('temporary-%d' % i, (base,), {})
                    value = cls([i])
                    value.append(value)
                    cls.instance = value
                    refs.append(weakref.ref(cls))
                return refs
            refs = make()
            for _ in range(5):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 5
            assert len(base.__subclasses__()) < 5
            assert base([42]) == [42]
        """)

    def test_soft_dirty_static_type_roots(self):
        self.run_soft_dirty("""
            from _testcapi import (get_tracing_gc_static_type as get_type,
                                  set_tracing_gc_static_type_payload as install)
            install(None)
            prepare()
            for n in range(3):
                install(['static-young-%d' % n, (1 << 100) + n])
                target = len(events) + 1
                allocate_until(lambda: len(events) >= target)
                assert events[-1] > 0, events
                assert get_type().payload == ['static-young-%d' % n,
                                              (1 << 100) + n]
            gc.collect()
            assert get_type().payload == ['static-young-2', (1 << 100) + 2]
        """)

    def test_dynamic_types_are_reclaimed(self):
        self.run_python("""
            import gc, sys, weakref
            gc.disable()
            def make_types():
                refs = []
                for i in range(1000):
                    cls = type('temporary-%d' % i, (), {})
                    obj = cls()
                    obj.payload = [i, 'payload-%d' % i]
                    obj.link = obj
                    cls.instance = obj
                    refs.append(weakref.ref(cls))
                return refs
            gc.collect()
            before = sys.getallocatedblocks()
            for _ in range(4):
                refs = make_types()
                for _ in range(3):
                    gc.collect()
                alive = sum(ref() is not None for ref in refs)
                assert alive < 5, alive
                assert sys.getallocatedblocks() - before < 5000
        """)

    def check_type_storage_garbage(self, kind):
        self.run_python(f"""
            import gc, weakref
            from _testinternalcapi import set_tracing_gc_type_storage_garbage
            gc.disable()
            class Payload:
                pass
            def make():
                types, refs = [], []
                for i in range(100):
                    cls = type('Storage-%d' % i, (), {{'__doc__': 'owned documentation'}})
                    value = Payload()
                    value.data = [i]
                    set_tracing_gc_type_storage_garbage(cls, value, {kind!r})
                    types.append(cls)
                    refs.append(weakref.ref(value))
                return types, refs
            types, refs = make()
            for _ in range(5):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 5
            for cls in types:
                assert cls.__doc__ == 'owned documentation'
                obj = cls()
                obj.payload = 'live'
                gc.collect()
                assert obj.payload == 'live'
        """)

    def test_type_shared_keys_ignore_unused_storage(self):
        self.check_type_storage_garbage('keys')

    def test_type_doc_ignores_unused_storage(self):
        self.check_type_storage_garbage('doc')

    def test_regex_code_is_not_a_reference(self):
        self.run_python("""
            import _sre, gc, sys, weakref
            from re._constants import INFO, IN, CHARSET, FAILURE, SUCCESS
            gc.disable()
            class Payload:
                pass
            def make():
                patterns, refs = [], []
                for i in range(100):
                    value = Payload()
                    bits = id(value)
                    words = [bits & 0xffffffff, bits >> 32]
                    if sys.byteorder == 'big':
                        words.reverse()
                    # A valid character bitmap whose data happens to equal
                    # an object pointer. INFO aligns the pair to a word.
                    code = [INFO, 4, 0, 1, 1, IN, 11, CHARSET,
                            *words, 0, 0, 0, 0, 0, 0, FAILURE, SUCCESS]
                    pattern = _sre.compile('', 0, code, 0, {}, ())
                    bitmap = words[0] | (words[1] << 32)
                    char = chr((bitmap & -bitmap).bit_length() - 1)
                    assert pattern.fullmatch(char)
                    patterns.append((pattern, char))
                    refs.append(weakref.ref(value))
                return patterns, refs
            patterns, refs = make()
            for _ in range(5):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 5
            assert all(pattern.fullmatch(char) for pattern, char in patterns)
        """)

    def test_instances_keep_type_hierarchies_alive(self):
        self.run_python("""
            import gc, weakref
            def make(i):
                class Meta(type):
                    pass
                class Base(metaclass=Meta):
                    __slots__ = ('left',)
                    def total(self):
                        return self.left + self.right
                class Child(Base):
                    __slots__ = ('right', '__dict__', '__weakref__')
                obj = Child()
                obj.left = i
                obj.right = i + 1
                obj.extra = ['retained', i]
                return obj, [weakref.ref(cls) for cls in (Meta, Base, Child)]
            pairs = [make(i) for i in range(100)]
            for _ in range(3):
                gc.collect()
            refs = []
            for i, (obj, type_refs) in enumerate(pairs):
                assert obj.total() == 2 * i + 1
                assert obj.extra == ['retained', i]
                assert all(ref() is not None for ref in type_refs)
                assert type(obj) is type_refs[-1]()
                refs.extend(type_refs)
            del obj, type_refs
            pairs.clear()
            for _ in range(5):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 10
        """)

    def test_soft_dirty_regex_owned_references(self):
        self.run_soft_dirty("""
            import re
            prepare()
            patterns = [re.compile('prefix-%d-(?P<value>[a-z]+)' % i)
                        for i in range(30)]
            allocate_until(lambda: any(event > 0 for event in events))
            for i, pattern in enumerate(patterns):
                assert pattern.pattern == 'prefix-%d-(?P<value>[a-z]+)' % i
                assert pattern.groupindex == {'value': 1}
                match = pattern.fullmatch('prefix-%d-payload' % i)
                assert match.group('value') == 'payload'
            gc.collect()
            assert all(pattern.fullmatch('prefix-%d-tail' % i).group(1) == 'tail'
                       for i, pattern in enumerate(patterns))
        """)

    def test_type_reclamation_with_threads(self):
        self.run_python("""
            import gc, threading, weakref
            roots = [None] * 4
            refs = [[] for _ in roots]
            errors = []
            ready = threading.Barrier(5)
            def worker(index):
                try:
                    ready.wait()
                    for i in range(1000):
                        cls = type('Transient', (), {
                            'value': i, 'read': lambda self: self.value})
                        roots[index] = cls()
                        assert roots[index].read() == i
                        refs[index].append(weakref.ref(cls))
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(20):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
            for _ in range(3):
                gc.collect()
            assert all(obj.read() == 999 for obj in roots)
            assert sum(ref() is not None for group in refs for ref in group) < 10
            roots.clear()
            for _ in range(3):
                gc.collect()
            assert sum(ref() is not None for group in refs for ref in group) < 5
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_type_saveall_preserves_metadata(self):
        self.run_python("""
            import gc, weakref
            gc.disable()
            def make():
                class Base:
                    value = 42
                class Child(Base):
                    pass
                return weakref.ref(Child)
            gc.collect()
            gc.set_debug(gc.DEBUG_SAVEALL)
            ref = make()
            gc.collect()
            types = [obj for obj in gc.garbage
                     if isinstance(obj, type) and obj.__name__ == 'Child']
            assert len(types) == 1
            assert types[0]().value == 42
            assert types[0].__bases__[0].__name__ == 'Base'
            assert len(types[0].__mro__) == 3
            ref = weakref.ref(types[0])
            types.clear()
            gc.set_debug(0)
            gc.garbage.clear()
            for _ in range(3):
                gc.collect()
            assert ref() is None
        """)

    def test_type_watcher_resurrection(self):
        self.run_python("""
            import _testcapi, gc, weakref
            watcher = _testcapi.add_type_watcher(0)
            events = _testcapi.get_type_modified_events()
            def make():
                cls = type('Watched', (), {'payload': ['retained', 42]})
                _testcapi.watch_type(watcher, cls)
                return weakref.ref(cls)
            ref = make()
            for _ in range(3):
                gc.collect()
            assert len(events) == 1, events
            assert ref() is events[0]
            assert events[0]().payload == ['retained', 42]
            events.clear()
            for _ in range(3):
                gc.collect()
            assert len(events) == 1, events
            assert ref() is events[0]
            assert events[0]().payload == ['retained', 42]
            _testcapi.unwatch_type(watcher, events[0])
            events.clear()
            for _ in range(3):
                gc.collect()
            assert ref() is None
            _testcapi.clear_type_watcher(watcher)
        """)

    def test_metaclass_finalizer_resurrection(self):
        self.run_python("""
            import gc, weakref
            saved = []
            finalized = []
            class Meta(type):
                def __del__(cls):
                    finalized.append(cls.__name__)
                    saved.append(cls)
            def make():
                class Child(metaclass=Meta):
                    value = ['intact', 42]
                return weakref.ref(Child)
            ref = make()
            for _ in range(3):
                gc.collect()
            assert finalized == ['Child'], finalized
            assert ref() is saved[0]
            assert saved[0]().value == ['intact', 42]
            saved.clear()
            for _ in range(3):
                gc.collect()
            assert ref() is None
            assert finalized == ['Child'], finalized
        """)

    def test_python_modules_are_reclaimed(self):
        self.run_python("""
            import gc
            import sys
            import types
            import weakref
            gc.disable()
            def make_modules():
                refs = []
                for i in range(1000):
                    module = types.ModuleType('temporary-%d' % i)
                    module.link = module
                    module.payload = ['payload-%d' % i, i + 0.125]
                    exec('def read(): return payload', module.__dict__)
                    refs.append(weakref.ref(module))
                return refs
            keep = types.ModuleType('reachable')
            keep.payload = ['kept', 42.25]
            keep.link = keep
            exec('def read(): return payload', keep.__dict__)
            gc.collect()
            before = sys.getallocatedblocks()
            for _ in range(4):
                refs = make_modules()
                for _ in range(3):
                    gc.collect()
                assert sum(ref() is not None for ref in refs) < 5
                assert keep.link is keep
                assert keep.read() == ['kept', 42.25]
                assert sys.getallocatedblocks() - before < 5000
            def make_function():
                module = types.ModuleType('function-globals')
                module.payload = ['globals-kept', 84.5]
                exec('def read(): return payload', module.__dict__)
                return module.read, weakref.ref(module)
            function, ref = make_function()
            for _ in range(3):
                gc.collect()
            assert ref() is None
            assert function() == ['globals-kept', 84.5]
        """)

    def test_native_modules_remain_pinned(self):
        self.run_python("""
            import _testcapi
            import gc
            import types
            import weakref
            spec = types.SimpleNamespace(name='native-module')
            def make_modules():
                factories = (
                    _testcapi.module_from_slots_size,
                    _testcapi.module_from_slots_gc,
                    _testcapi.module_from_slots_token,
                    _testcapi.module_from_slots_exec,
                )
                return [weakref.ref(factory(spec)) for factory in factories]
            refs = make_modules()
            for _ in range(3):
                gc.collect()
            assert all(ref() is not None for ref in refs)
            assert _testcapi.pymodule_get_state_size(refs[0]()) == 123
            assert _testcapi.pymodule_get_token(refs[2]()) == (
                _testcapi.module_test_token)
            assert refs[3]().a_number == 456
        """)

    def test_module_subclass_resurrection(self):
        self.run_python("""
            import gc
            import types
            import weakref
            saved = []
            finalized = []
            callbacks = []
            class Module(types.ModuleType):
                def __del__(self):
                    finalized.append(self.__name__)
                    saved.append(self)
            def make():
                module = Module('resurrected-module')
                module.link = module
                module.payload = ['retained', 42.25]
                exec('def read(): return payload', module.__dict__)
                return (weakref.ref(module),
                        weakref.ref(module, lambda ref: callbacks.append(ref())))
            ref, callback_ref = make()
            for _ in range(3):
                gc.collect()
            assert finalized == ['resurrected-module'], finalized
            assert len(saved) == 1
            assert saved[0].link is saved[0]
            assert saved[0].read() == ['retained', 42.25]
            # Callback references clear before finalization; references
            # without callbacks survive resurrection, as in the FT collector.
            assert callback_ref() is None
            assert callbacks == [None]
            assert ref() is saved[0]
            saved.clear()
            for _ in range(3):
                gc.collect()
            assert ref() is None
            assert finalized == ['resurrected-module']
            assert callbacks == [None]
        """)

    def test_weakref_callbacks(self):
        self.run_python("""
            import gc
            import weakref
            called = []
            class Node:
                pass
            def make_cycle():
                node = Node()
                node.link = node
                return weakref.ref(node, lambda ref: called.append(ref()))
            refs = [make_cycle() for _ in range(100)]
            for _ in range(5):
                gc.collect()
            assert called and all(value is None for value in called)
            assert len(called) == sum(ref() is None for ref in refs)
        """)

    def test_saveall_then_collect(self):
        self.run_python("""
            import gc
            import weakref
            class Node:
                pass
            def make_cycle():
                node = Node()
                node.link = node
                node.payload = str(id(node))
                return weakref.ref(node)
            refs = [make_cycle() for _ in range(100)]
            gc.set_debug(gc.DEBUG_SAVEALL)
            gc.collect()
            assert any(type(obj) is Node for obj in gc.garbage)
            assert all(obj.payload == str(id(obj)) for obj in gc.garbage
                       if type(obj) is Node)
            gc.set_debug(0)
            gc.garbage.clear()
            for _ in range(5):
                gc.collect()
            assert any(ref() is None for ref in refs)
        """)

    def test_legacy_finalizer_leaf_children(self):
        from test.support import import_helper
        import_helper.import_module("_testcapi")
        self.run_python("""
            import gc
            from _testcapi import with_tp_del
            @with_tp_del
            class Node:
                def __tp_del__(self):
                    pass
            def make():
                for i in range(100):
                    node = Node()
                    node.link = node
                    node.number = 1000000 + i
                    node.text = 'leaf-%d' % node.number
                    node.value = i + 0.25
            make()
            for _ in range(3):
                gc.collect()
            nodes = [obj for obj in gc.garbage if type(obj) is Node]
            assert nodes
            assert all(node.text == 'leaf-%d' % node.number for node in nodes)
            assert all(node.value == node.number - 1000000 + 0.25 for node in nodes)
        """)

    def test_new_child_of_reachable_function(self):
        self.run_python("""
            import gc
            def function():
                pass
            for index in range(20):
                function.root = [[index]]
                gc.collect()
                assert function.root == [[index]]
        """)

    def test_acyclic_tuples_are_reclaimed(self):
        self.run_python("""
            import gc
            import sys
            gc.disable()  # Measure the effect of the explicit collection.
            def churn():
                for _ in range(20000):
                    tuple([None, None])
            root = tuple([None, None])
            assert gc.is_tracked(root)
            gc.collect()
            before = sys.getallocatedblocks()
            churn()
            allocated = sys.getallocatedblocks()
            gc.collect()
            after = sys.getallocatedblocks()
            assert allocated - before > 15000
            assert allocated - after > 15000, (before, allocated, after)
            assert root == (None, None)
            assert gc.is_tracked(root)
        """)

    def test_prefetch_live_graph(self):
        self.run_python("""
            import gc
            root = [[None] for _ in range(210000)]
            # The first pass updates long_lived_total; later passes use the
            # prefetch queue. Check descendants after switching disciplines.
            for _ in range(3):
                gc.collect()
                assert len(root) == 210000
                assert all(item == [None] for item in root)
        """)

    def test_leaf_objects_are_reclaimed(self):
        self.run_python("""
            import gc
            import sys
            from _testinternalcapi import (
                make_tracing_gc_boxed_int, make_tracing_gc_boxed_float)
            gc.disable()  # Automatic GC may reclaim the batch before sampling.
            factories = [
                lambda i: make_tracing_gc_boxed_int(i + 1000000),
                lambda i: make_tracing_gc_boxed_float(i + 0.25),
                lambda i: 'value-%d' % i,
                lambda i: b'value-%d' % i,
                lambda i: complex(i, 0.25),
            ]
            for factory in factories:
                keep = [factory(i) for i in range(100)]
                gc.collect()
                before = sys.getallocatedblocks()
                for i in range(20000):
                    factory(i)
                allocated = sys.getallocatedblocks()
                gc.collect()
                after = sys.getallocatedblocks()
                assert allocated - before > 15000, (before, allocated)
                assert allocated - after > 15000, (before, allocated, after)
                assert keep == [factory(i) for i in range(100)]
        """)

    def test_resurrected_leaf_children(self):
        self.run_python("""
            import gc
            saved = []
            class Node:
                def __del__(self):
                    saved.append(self)
            def make():
                for i in range(100):
                    node = Node()
                    node.link = node
                    node.number = 1000000 + i
                    node.text = 'leaf-%d' % node.number
                    node.values = [node.number + 0.25, complex(node.number)]
            make()
            for _ in range(5):
                gc.collect()
            assert saved
            for node in saved:
                assert node.text == 'leaf-%d' % node.number
                assert node.values == [node.number + 0.25, complex(node.number)]
        """)

    def check_resurrected_leaves_in_nursery(self, containers):
        self.run_soft_dirty("""
            saved = [None] * 4096
            class Revive:
                def __del__(self):
                    saved[self.index] = self.payload
            def make():
                for i in range(4):
                    obj = Revive()
                    obj.index = i
                    # Large leaves occupy full allocator areas. Keeping a
                    # clean area cannot mask a lost promotion bit here.
                    obj.payload = bytes([i + 1]) * (2 << 20)
            prepare()
            gc.disable()
            make()
            gc.collect()
            events.clear()
            gc.enable()
            for batch in range(256):
                for i in range(4096):
                    value = ([i, i + 0.25] if CONTAINERS else
                             make_tracing_gc_boxed_float(i + 0.25))
                if events:
                    break
            gc.disable()
            assert events and events[0] > 0, events
            # Do not read saved entries between establishing the full-GC
            # baseline and the minor: their only roots are in the old buffer.
            for i in range(4):
                value = saved[i]
                assert len(value) == 2 << 20
                assert value[0] == value[-1] == i + 1
        """.replace("CONTAINERS", repr(containers)), env_vars={
            "PYTHON_TRACING_GC_YOUNG_CONTAINERS": str(int(containers))})

    def test_resurrected_leaves_in_scalar_nursery(self):
        self.check_resurrected_leaves_in_nursery(False)

    def test_resurrected_leaves_in_container_nursery(self):
        self.check_resurrected_leaves_in_nursery(True)

    def test_resurrected_containers_in_clean_old_buffer(self):
        self.run_soft_dirty("""
            saved = [None] * 4096
            class Revive:
                def __del__(self):
                    saved[self.index] = self.payload
            def make():
                for i in range(4):
                    obj = Revive()
                    obj.index = i
                    obj.payload = [i, bytes([i + 1]) * (2 << 20)]
            prepare()
            gc.disable()
            make()
            gc.collect()
            events.clear()
            gc.enable()
            for batch in range(256):
                for i in range(4096):
                    value = [i, i + 0.25]
                if events:
                    break
            gc.disable()
            assert events and events[0] > 0, events
            # The full-GC baseline includes the finalizers' stores. With no
            # later reads or writes, this old buffer need not be scanned by
            # the nursery. Resurrected containers must therefore be old too.
            for i in range(4):
                value = saved[i]
                assert len(value) == 2
                assert value[0] == i
                payload = value[1]
                assert len(payload) == 2 << 20
                assert payload[0] == payload[-1] == i + 1
        """, env_vars={"PYTHON_TRACING_GC_YOUNG_CONTAINERS": "1"})

    def test_sparse_leaf_pages_are_reused(self):
        self.run_python("""
            import gc
            import sys
            from _testinternalcapi import (
                make_tracing_gc_boxed_int, make_tracing_gc_boxed_float)
            gc.disable()
            factories = [
                lambda i: make_tracing_gc_boxed_int(i + 1000000),
                lambda i: make_tracing_gc_boxed_float(i + 0.25),
                lambda i: 'sparse-%d' % i,
                lambda i: b'sparse-%d' % i,
                lambda i: complex(i, 0.25),
            ]
            for factory in factories:
                for _ in range(3):
                    values = [factory(i) for i in range(16000)]
                    gc.collect()  # Mark every slot before making holes.
                    keep = values[::17]
                    del values
                    allocated = sys.getallocatedblocks()
                    gc.collect()
                    after = sys.getallocatedblocks()
                    assert allocated - after > 12000, (allocated, after)
                    assert keep == [factory(i) for i in range(0, 16000, 17)]
        """)

    def test_leaf_marks_across_finalization(self):
        self.run_python("""
            import gc
            gc.disable()
            saved = []
            class Node:
                def __del__(self):
                    # These allocations did not exist in the initial mark
                    # pass and must not join its sweep candidates.
                    saved.append([str(i) for i in range(10000)])
            def make_cycles():
                for _ in range(10):
                    node = Node()
                    node.link = node
            values = ['old-%d' % i for i in range(30000)]
            gc.collect()
            del values
            make_cycles()
            before = gc.get_stats()[2]['collected']
            gc.collect()
            # A prior collection's live marks must not resurrect the old
            # strings when finalizers force another root traversal.
            assert gc.get_stats()[2]['collected'] - before > 25000
            assert saved
            for values in saved:
                assert values == [str(i) for i in range(10000)]
        """)

    def test_leaf_sweep_alternates_finalizer_path(self):
        self.run_python("""
            import gc
            import sys
            from _testinternalcapi import make_tracing_gc_boxed_float
            gc.disable()
            saved = []
            class Node:
                def __del__(self):
                    # Allocation after the first snapshot must not be swept
                    # with that snapshot's dead slots.
                    saved.append(['new-%d' % i for i in range(3000)])
            def allocate(with_finalizer):
                for i in range(10000):
                    values = (i + 1000000,
                              make_tracing_gc_boxed_float(i + 0.25),
                              'dead-%d' % i, b'dead-%d' % i,
                              complex(i, 0.25))
                if with_finalizer:
                    node = Node()
                    node.link = node
            gc.collect()
            for round in range(6):
                saved.clear()
                gc.collect()
                before = sys.getallocatedblocks()
                allocate(round % 2)
                allocated = sys.getallocatedblocks()
                assert allocated - before > 45000, (before, allocated)
                for _ in range(3):
                    gc.collect()
                after = sys.getallocatedblocks()
                assert allocated - after > 40000, (allocated, after)
                if round % 2:
                    assert len(saved) == 1, len(saved)
                    assert saved[0] == ['new-%d' % i for i in range(3000)]
                else:
                    assert not saved
        """)

    def test_unicode_sweep_storage_and_subclasses(self):
        from test.support import import_helper
        import_helper.import_module("_testcapi")
        self.run_python("""
            import gc
            import sys
            from _testcapi import unicode_asutf8
            gc.disable()
            interned = [sys.intern('sweep-interned-%d' % i) for i in range(100)]
            def allocate(prefix):
                values = [prefix + str(i) for i in range(10000)]
                for value in values:
                    # Non-ASCII strings now own a separate UTF-8 cache;
                    # they must retain the normal Unicode destruction path.
                    unicode_asutf8(value, 0)
                return values[::137]
            for prefix in ('ascii-', '\\u00e9-', '\\u6f22-', '\\U0001f600-'):
                gc.collect()
                before = sys.getallocatedblocks()
                keep = allocate(prefix)
                for _ in range(3):
                    gc.collect()
                after = sys.getallocatedblocks()
                assert after - before < 1000, (prefix, before, after)
                assert keep == [prefix + str(i) for i in range(0, 10000, 137)]
            seen = []
            class Text(str):
                def __del__(self):
                    seen.append(self.label)
            def make_subclasses():
                for i in range(100):
                    value = Text('subclass-%d' % i)
                    value.label = i
            make_subclasses()
            for _ in range(3):
                gc.collect()
            assert sorted(seen) == list(range(100)), seen
            assert interned == ['sweep-interned-%d' % i for i in range(100)]
        """)

    def test_large_leaf_pages(self):
        self.run_python("""
            import gc
            # Exercise single-block pages, including huge allocations that
            # the allocator stores differently from ordinary small pages.
            for size in (65536, 1048576, 33 * 1048576):
                root = b'x' * size
                gc.collect()
                assert len(root) == size and root[:4] == root[-4:] == b'xxxx'
                del root
                gc.collect()
                root = 'y' * size
                gc.collect()
                assert len(root) == size and root[:4] == root[-4:] == 'yyyy'
                del root
                gc.collect()
                root = 1 << (size * 8)
                gc.collect()
                assert root.bit_length() == size * 8 + 1
                del root
                gc.collect()
        """)

    def test_leaf_references_in_auxiliary_storage(self):
        self.run_python("""
            import gc
            mapping = {'key-%d' % i: i + 1000000 for i in range(1000)}
            ranges = [range(1000000 + i, 1000010 + i) for i in range(100)]
            for _ in range(10):
                gc.collect()
                assert mapping == {'key-%d' % i: i + 1000000
                                   for i in range(1000)}
                assert all(list(value) == list(range(1000000 + i, 1000010 + i))
                           for i, value in enumerate(ranges))
        """)

    def test_precise_dictionary_storage(self):
        self.run_python("""
            import gc
            # Exact string keys are omitted by cyclic GC's dict visitor.
            strings = {'dynamic-key-%d' % i: 'value-%d' % i
                       for i in range(1000)}
            general = {(i + 1000000,): [str(i)] for i in range(1000)}
            frozen = frozendict(strings)
            for i in range(0, 1000, 2):
                del strings['dynamic-key-%d' % i]
                del general[(i + 1000000,)]
            for _ in range(10):
                gc.collect()
                assert strings == {'dynamic-key-%d' % i: 'value-%d' % i
                                   for i in range(1, 1000, 2)}
                assert general == {(i + 1000000,): [str(i)]
                                   for i in range(1, 1000, 2)}
                assert frozen == {'dynamic-key-%d' % i: 'value-%d' % i
                                  for i in range(1000)}
        """)

    def test_precise_split_dictionary_storage(self):
        self.run_python("""
            import gc
            class Node:
                pass
            def make():
                nodes = [Node() for _ in range(100)]
                for i, node in enumerate(nodes):
                    node.first = 'first-%d' % i
                    node.second = [str(i)]
                mappings = [node.__dict__ for node in nodes]
                copies = [mapping.copy() for mapping in mappings]
                for i, node in enumerate(nodes):
                    del node.first
                    node.third = 'third-%d' % i
                # Detach some dictionaries from their inline storage.
                for node in nodes[::2]:
                    node.__dict__ = {}
                return nodes, mappings, copies
            nodes, mappings, copies = make()
            for _ in range(10):
                gc.collect()
                for i, (mapping, copied) in enumerate(zip(mappings, copies)):
                    assert mapping == {'second': [str(i)],
                                       'third': 'third-%d' % i}
                    assert copied == {'first': 'first-%d' % i,
                                      'second': [str(i)]}
                    assert nodes[i].__dict__ == (mapping if i % 2 else {})
        """)

    def test_set_bulk_release(self):
        self.run_python("""
            import gc, sys, threading, weakref

            gc.disable()
            finalized = []
            errors = []
            class Member:
                def __init__(self, index):
                    self.index = index
                    self.finalized = finalized
                def __hash__(self):
                    return self.index
                def __del__(self):
                    self.finalized.append(self.index)
            class SetSubclass(set):
                pass
            class FrozenSubclass(frozenset):
                pass

            for kind in (set, frozenset, SetSubclass, FrozenSubclass):
                for clear in (False, True):
                    if clear and issubclass(kind, frozenset):
                        continue
                    for size in (0, 3, 2048):
                        for sparse in (False, True):
                            finalized = []
                            result = []
                            def worker():
                                try:
                                    members = [Member(i) for i in range(size)]
                                    container = kind(members)
                                    refs = [weakref.ref(member)
                                            for member in members]
                                    survivor = members[-1] if members else None
                                    if sparse and isinstance(container, set):
                                        for member in members[:-1]:
                                            container.remove(member)
                                    container_ref = weakref.ref(container)
                                    if clear:
                                        container.clear()
                                        assert not container
                                        assert sys.getsizeof(container) == sys.getsizeof(kind())
                                        # Exercise the reset inline table and
                                        # subsequent growth, including dummies.
                                        container.update(range(32))
                                        container.difference_update(range(0, 32, 2))
                                        assert container == set(range(1, 32, 2))
                                        container.clear()
                                        container.clear()
                                        result.append(container)
                                    result.extend((refs, survivor, container_ref))
                                except BaseException as exc:
                                    errors.append(exc)
                            # An exited worker avoids retaining abandoned
                            # members through conservative C-stack words.
                            thread = threading.Thread(target=worker)
                            thread.start()
                            thread.join()
                            assert not errors, errors
                            refs, survivor, container_ref = result[-3:]
                            for _ in range(4):
                                gc.collect()
                            assert sorted(finalized) == list(range(max(size - 1, 0))), finalized
                            assert all(ref() is None for ref in refs[:-1])
                            if size:
                                assert refs[-1]() is survivor
                                assert survivor.index == size - 1
                            if clear:
                                assert container_ref() is result[0]
                                assert not result[0]
                            else:
                                assert container_ref() is None
        """)

    def test_released_buffers_do_not_force_collection(self):
        self.run_python("""
            import gc

            template = (None,) * 131072
            holder = []
            gc.set_threshold(2000)
            gc.collect()
            before = sum(row['collections'] for row in gc.get_stats())
            gc.enable()
            # Allocate and promptly release 128 MiB of auxiliary storage,
            # while keeping the live heap and the ordinary GC budget small.
            for _ in range(128):
                holder.extend(template)
                assert len(holder) == len(template)
                holder.clear()
            after = sum(row['collections'] for row in gc.get_stats())
            assert after == before, (before, after)
            assert not holder and template[0] is template[-1] is None
            # Explicit collection must not be suppressed by the pressure gate.
            gc.collect()
            assert sum(row['collections'] for row in gc.get_stats()) == after + 1
        """)

    def test_heap_pressure_checks_keep_a_fixed_live_baseline(self):
        self.run_python("""
            import gc, weakref

            class Node:
                __slots__ = ('payload', 'link', '__weakref__')
            template = (None,) * 131072
            holder = []
            refs = []
            gc.set_threshold(2000)
            gc.collect()
            before = sum(row['collections'] for row in gc.get_stats())
            gc.enable()
            # Most allocations are released immediately. A small amount of
            # garbage accumulates between pressure checks. Rebasing the live
            # heap on each check would let that garbage grow without limit.
            for i in range(512):
                holder.extend(template)
                holder.clear()
                node = Node()
                node.payload = bytes([i % 251]) * 32768
                node.link = node
                refs.append(weakref.ref(node))
            after = sum(row['collections'] for row in gc.get_stats())
            assert after > before, (before, after)
            assert sum(ref() is None for ref in refs) >= 128
        """)

    def test_heap_pressure_includes_abandoned_allocations(self):
        self.run_python("""
            import gc, threading, weakref

            class Node:
                __slots__ = ('payload', 'link', '__weakref__')
            refs = []
            errors = []
            template = (None,) * 131072
            holder = []
            gc.set_threshold(2000)
            gc.collect()
            gc.disable()
            def worker():
                try:
                    for i in range(2048):
                        node = Node()
                        node.payload = bytes([i % 251]) * 8192
                        node.link = node
                        refs.append(weakref.ref(node))
                except BaseException as exc:
                    errors.append(exc)
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            assert not errors and len(refs) == 2048, errors
            before = sum(row['collections'] for row in gc.get_stats())
            gc.enable()
            for _ in range(64):
                holder.extend(template)
                holder.clear()
            after = sum(row['collections'] for row in gc.get_stats())
            # Looking only at active owners would miss the abandoned garbage
            # and repeatedly dismiss this otherwise justified heap trigger.
            assert after > before, (before, after)
            assert sum(ref() is not None for ref in refs) < 16
        """)

    def test_acyclic_frozensets_are_reclaimed(self):
        self.run_python("""
            import gc, marshal, weakref

            gc.disable()
            def make():
                refs = []
                for i in range(2000):
                    members = frozenset(('member-%d' % i, i + 0.25))
                    assert gc.is_tracked(members)
                    restored = marshal.loads(marshal.dumps(members))
                    assert gc.is_tracked(restored)
                    assert restored == members
                    refs.extend((weakref.ref(members), weakref.ref(restored)))
                return refs
            refs = make()
            for _ in range(3):
                gc.collect()
            assert sum(ref() is not None for ref in refs) < 10
        """)

    def test_precise_set_storage(self):
        self.run_python("""
            import gc
            small = {'small-%d' % i for i in range(3)}
            large = {'large-%d' % i for i in range(1000)}
            frozen = frozenset(large)
            for i in range(0, 1000, 2):
                large.remove('large-%d' % i)
            for _ in range(10):
                gc.collect()
                assert small == {'small-%d' % i for i in range(3)}
                assert large == {'large-%d' % i for i in range(1, 1000, 2)}
                assert frozen == {'large-%d' % i for i in range(1000)}
                small.pop()
                small.add('replacement')
                small.clear()
                small.update('small-%d' % i for i in range(3))
        """)

    def test_container_hashes_are_not_strong_references(self):
        self.run_python("""
            import gc
            import weakref
            class Node:
                pass
            class Key:
                __slots__ = ('number',)
                def __init__(self, number):
                    self.number = number
                def __hash__(self):
                    return self.number
            def make():
                mapping = {}
                members = set()
                refs = []
                for _ in range(1000):
                    node = Node()
                    node.payload = ['payload'] * 100
                    key = Key(id(node))
                    mapping[key] = True
                    members.add(key)
                    refs.append(weakref.ref(node))
                return mapping, members, refs
            mapping, members, refs = make()
            for _ in range(5):
                gc.collect()
            # Cached hashes are integers, even when their bits happen to be
            # an allocated address. Neither table owns the hashed object.
            assert sum(ref() is None for ref in refs) > 950
            assert len(mapping) == len(members) == 1000
            assert all(mapping[key] for key in members)
        """)

    def test_precise_container_subclasses(self):
        self.run_python("""
            import gc
            class Dict(dict):
                pass
            class Set(set):
                pass
            class Tuple(tuple):
                pass
            class List(list):
                pass
            values = [Dict(key='value'), Set(['item']), Tuple(['item']),
                      List(['item'])]
            for i, value in enumerate(values):
                value.extra = ['extra-%d' % i]
            for _ in range(10):
                gc.collect()
                assert values == [{'key': 'value'}, {'item'},
                                  ('item',), ['item']]
                for i, value in enumerate(values):
                    assert value.extra == ['extra-%d' % i]
        """)

    def test_shared_containers_during_collection(self):
        self.run_python("""
            import gc
            import threading
            mapping = {}
            members = set()
            errors = []
            ready = threading.Barrier(5)
            def worker(seed):
                try:
                    ready.wait()
                    for i in range(1000):
                        key = seed * 10000 + i
                        payload = 'payload-%d-%d' % (seed, i)
                        mapping[key] = [payload]
                        members.add(key)
                        if i >= 16:
                            del mapping[key - 16]
                            members.remove(key - 16)
                        if i % 50 == 0:
                            gc.collect()
                        assert mapping[key] == [payload]
                        assert key in members
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(20):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
            expected = {seed * 10000 + i: ['payload-%d-%d' % (seed, i)]
                        for seed in range(4) for i in range(984, 1000)}
            assert mapping == expected
            assert members == set(expected)
        """)

    def test_sparse_container_pages_are_reused(self):
        self.run_python("""
            import gc
            import weakref
            class Node:
                pass
            def make():
                keep = []
                refs = []
                for i in range(4000):
                    node = Node()
                    node.number = i
                    node.data = ([str(i)] * (i % 31),
                                 {'key-%d' % i: tuple(range(i % 127))})
                    node.cycle = node
                    refs.append(weakref.ref(node))
                    if i % 17 == 0:
                        keep.append(node)
                return keep, refs
            for _ in range(5):
                keep, refs = make()
                for _ in range(3):
                    gc.collect()
                assert sum(ref() is None for ref in refs) > 3600
                for node in keep:
                    i = node.number
                    assert node.cycle is node
                    assert node.data == ([str(i)] * (i % 31),
                                         {'key-%d' % i: tuple(range(i % 127))})
        """)

    def test_large_container_pages(self):
        self.run_python("""
            import gc
            for size in (7, 31, 127, 1023, 16383, 131073):
                root = tuple('entry-%d' % i for i in range(size))
                for _ in range(3):
                    gc.collect()
                    assert len(root) == size
                    assert all(value == 'entry-%d' % i
                               for i, value in enumerate(root))
                del root
                gc.collect()
        """)

    def test_leaf_reclamation_after_thread_exit(self):
        self.run_python("""
            import gc
            import sys
            import threading
            gc.disable()  # Leave abandoned allocations for the explicit GC.
            keep = []
            def worker():
                keep.extend(str(i) for i in range(1000000, 1000100))
                for i in range(30000):
                    str(i)
            gc.collect()
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            allocated = sys.getallocatedblocks()
            gc.collect()
            after = sys.getallocatedblocks()
            assert allocated - after > 25000, (allocated, after)
            assert keep == [str(i) for i in range(1000000, 1000100)]
        """)

    def test_frozen_container_leaf_children(self):
        self.run_python("""
            import gc
            keep = [str(i) for i in range(1000, 2000)]
            gc.freeze()
            for _ in range(3):
                gc.collect()
                assert keep == [str(i) for i in range(1000, 2000)]
            gc.unfreeze()
        """)

    def test_cached_code_attributes(self):
        self.run_python("""
            import gc
            def outer(value):
                def inner(argument):
                    return value + argument
                return inner
            function = outer(42)
            expected = (('value',), ('argument',), ('value',))
            # Populate caches without retaining the returned tuples here.
            assert outer.__code__.co_cellvars == expected[0]
            assert function.__code__.co_varnames == expected[1]
            assert function.__code__.co_freevars == expected[2]
            for _ in range(10):
                gc.collect()
                assert outer.__code__.co_cellvars == expected[0]
                assert function.__code__.co_varnames == expected[1]
                assert function.__code__.co_freevars == expected[2]
                assert function(1) == 43
        """)

    def test_failed_inline_dict_materialization(self):
        self.run_python("""
            import gc
            gc.disable()
            class Node:
                pass
            class Name(str):
                pass
            keep = []
            for i in range(100):
                node = Node()
                node.item = i
                # A non-exact string forces creation of a temporary dict.
                # Failed deletion leaves it unpublished and unreachable.
                try:
                    delattr(node, Name('missing'))
                except AttributeError:
                    pass
                else:
                    raise AssertionError('deletion should have failed')
                keep.append(node)
            gc.collect()
            assert all(node.item == i for i, node in enumerate(keep))
            for node in keep:
                assert node.__dict__ == {'item': node.item}
            keep.clear()
            del node
            for _ in range(3):
                gc.collect()
        """)

    def test_functions_and_code_are_reclaimed(self):
        self.run_python("""
            import gc
            import weakref
            gc.disable()
            def make():
                functions = []
                codes = []
                for i in range(1000):
                    payload = [str(j) for j in range(100)]
                    function = lambda payload=payload: payload
                    functions.append(weakref.ref(function))
                    code = compile('result = 42', '<tracing-gc>', 'exec')
                    codes.append(weakref.ref(code))
                return functions, codes
            functions, codes = make()
            for _ in range(5):
                gc.collect()
            assert sum(ref() is None for ref in functions) > 950
            assert sum(ref() is None for ref in codes) > 950
        """)

    def test_symbol_table_entries_are_reclaimed(self):
        self.run_python("""
            import _symtable
            import gc
            gc.disable()
            keep = _symtable.symtable('def f(x): return x', '<gc>', 'exec')
            entry_type = type(keep)
            def count():
                return sum(type(obj) is entry_type for obj in gc.get_objects())
            gc.collect()
            before = count()
            for _ in range(3000):
                _symtable.symtable('def f(x): return x', '<gc>', 'exec')
            assert count() - before > 5000
            for _ in range(3):
                gc.collect()
            assert count() - before < 100
            assert keep.name == 'top'
            # Annotation scopes also appear in children before the function.
            functions = [child for child in keep.children if child.name == 'f']
            assert len(functions) == 1
            assert functions[0].varnames == ['x']
        """)

    def test_unbound_executing_function_root(self):
        self.run_python("""
            import gc
            def make():
                def function():
                    for _ in range(5):
                        gc.collect()
                    return 42
                return function
            for _ in range(100):
                assert make()() == 42
            namespace = {'gc': gc, 'root': [42]}
            exec('gc.collect(); assert root == [42]', {}, namespace)
        """)

    def test_suspended_function_and_code_roots(self):
        self.run_python("""
            import gc
            import weakref
            def make():
                def generator():
                    yield [42]
                    gc.collect()
                    yield [43]
                return generator(), weakref.ref(generator)
            generators = [make() for _ in range(100)]
            for generator, ref in generators:
                assert next(generator) == [42]
            for _ in range(5):
                gc.collect()
            for generator, ref in generators:
                assert ref() is not None
                assert next(generator) == [43]
        """)

    def test_function_destruction_watchers(self):
        from test.support import import_helper
        import_helper.import_module('_testcapi')
        self.run_python("""
            import gc
            import _testcapi
            gc.disable()
            destroyed = set()
            def watcher(event, function_or_id, value):
                if event == _testcapi.PYFUNC_EVENT_DESTROY:
                    destroyed.add(function_or_id)
            watcher_id = _testcapi.add_func_watcher(watcher)
            try:
                def make():
                    ids = []
                    for _ in range(1000):
                        function = lambda: 42
                        ids.append(id(function))
                    return ids
                ids = make()
                for _ in range(5):
                    gc.collect()
                assert sum(value in destroyed for value in ids) > 950
            finally:
                _testcapi.clear_func_watcher(watcher_id)
        """)

    def test_untracked_audit_hook_list(self):
        self.run_python("""
            import gc
            import sys
            calls = []
            sys.addaudithook(lambda event, args: calls.append(event))
            for _ in range(10):
                gc.collect()
                sys.audit('tracing_gc.test')
            assert calls.count('tracing_gc.test') == 10
        """)

    def test_compilation_and_collection_with_threads(self):
        self.run_python("""
            import gc
            import threading
            gc.set_threshold(256)
            ready = threading.Barrier(5)
            errors = []
            def worker(seed):
                try:
                    namespace = {'seed': seed}
                    ready.wait()
                    for i in range(300):
                        code = compile('def f(x): return x + seed', '<gc>', 'exec')
                        exec(code, namespace)
                        function = namespace['f']
                        function.data = [str(i)]
                        if i % 10 == 0:
                            gc.collect()
                        assert function(i) == i + seed
                        assert function.data == [str(i)]
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(10):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
        """)

    def test_function_and_code_watcher_resurrection(self):
        from test.support import import_helper
        import_helper.import_module('_testcapi')
        self.run_python("""
            import gc
            from _testcapi import test_tracing_gc_watcher_resurrection
            functions, codes = test_tracing_gc_watcher_resurrection()
            assert len(functions) > 90, len(functions)
            assert len(codes) > 90, len(codes)
            for _ in range(3):
                gc.collect()
                assert all(function() == 42 for function in functions)
                assert all(eval(code) == 42 for code in codes)
        """)

    def test_memoryview_clear_before_deallocation(self):
        self.run_python("""
            import gc
            def churn():
                for _ in range(2000):
                    view = memoryview(bytearray(128))
                    view[1:][1:]
            keep = memoryview(bytearray(b'abc'))
            for _ in range(5):
                churn()
                gc.collect()
                assert keep.tobytes() == b'abc'
        """)

    def test_stop_the_world_with_threads(self):
        self.run_python("""
            import gc
            import threading
            stop = threading.Event()
            ready = threading.Barrier(5)
            errors = []
            def worker(seed):
                try:
                    keep = []
                    value = seed
                    for _ in range(1000):
                        value = [value, seed]
                        keep.append(value)
                        if len(keep) > 100:
                            del keep[:50]
                    ready.wait()
                    stop.wait()
                    assert len(keep) == 100
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for thread in threads:
                thread.start()
            try:
                ready.wait()
                for _ in range(5):
                    gc.collect()
            finally:
                stop.set()
                for thread in threads:
                    thread.join()
            assert not errors, errors
        """)

    def test_collect_while_threads_allocate(self):
        self.run_python("""
            import gc
            import threading
            ready = threading.Barrier(5)
            stop = threading.Event()
            errors = []
            def worker(seed):
                try:
                    ready.wait()
                    while not stop.is_set():
                        root = [[seed] for _ in range(100)]
                        pairs = [tuple(item) for item in root]
                        assert all(item == [seed] for item in root)
                        assert all(item == (seed,) for item in pairs)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(seed,))
                       for seed in range(4)]
            for thread in threads:
                thread.start()
            try:
                ready.wait()
                for _ in range(10):
                    gc.collect()
            finally:
                stop.set()
                for thread in threads:
                    thread.join()
            assert not errors, errors
        """)

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_float_local_reuse_allocation(self):
        self.run_python("""
            import _opcode
            import gc
            import sys
            def calculate(n):
                x = float('1.25')
                y = float('0.5')
                for _ in range(n):
                    added = x + y
                    subtracted = x - y
                    multiplied = x * y
                    divided = x / y
                return added, subtracted, multiplied, divided
            def exercise():
                expected = (1.75, 0.75, 0.625, 2.5)
                for _ in range(5):
                    assert calculate(2000) == expected
                gc.disable()
                gc.collect()
                before = sys.getallocatedblocks()
                assert calculate(20000) == expected
                allocated = sys.getallocatedblocks() - before
                # Allow a boxed range index per iteration plus overhead, but
                # not four new float objects on every iteration.
                assert allocated < 25000, allocated
                opnames = set()
                for offset in range(0, len(calculate.__code__.co_code), 2):
                    try:
                        executor = _opcode.get_executor(calculate.__code__, offset)
                    except ValueError:
                        continue
                    opnames.update(op[0] for op in executor)
                for operation in ('ADD', 'SUBTRACT', 'MULTIPLY', 'TRUEDIV'):
                    name = '_BINARY_OP_' + operation + '_FLOAT_REUSE_LOCAL'
                    assert name in opnames, (name, opnames)
            exercise()
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_float_local_reuse_preserves_aliases(self):
        self.run_python("""
            import gc
            def calculate(n):
                value = float('1.25')
                history = []
                for _ in range(n):
                    history.append(value)
                    value = value + 0.5
                return value, history
            def borrowed(n):
                value = float('1.25')
                for _ in range(n):
                    result = value + (value := value + 0.5)
                return value, result
            def assigned(n):
                value = float('1.25')
                for _ in range(n):
                    previous, value = value, value + 0.5
                return previous, value
            def update_argument(value):
                value = value + 0.5
                return value
            def caller(n):
                value = float('1.25')
                for _ in range(n):
                    result = value + update_argument(value)
                assert value == 1.25
                return result
            for _ in range(5):
                value, history = calculate(2000)
                assert value == 1001.25
                assert history == [1.25 + i * 0.5 for i in range(2000)]
                assert borrowed(2000) == (1001.25, 2002.0)
                assert assigned(2000) == (1000.75, 1001.25)
                assert caller(2000) == 3.0
                gc.collect()
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_float_local_reuse_type_changes(self):
        self.run_python("""
            class Number(float):
                def __add__(self, other):
                    return 'overridden'
            def calculate(values):
                result = object()
                for value in values:
                    result = value + 0.5
                return result
            for _ in range(5):
                assert calculate([1.25] * 2000) == 1.75
                assert calculate([1.25] * 2000 + [Number(3.0)]) == 'overridden'
                assert calculate([Number(3.0)] + [1.25] * 2000) == 1.75
                assert calculate([1.25] * 2000 + [2]) == 2.5
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_float_local_reuse_errors_and_special_values(self):
        self.run_python("""
            import math
            def calculate(divisors):
                value = float('3.25')
                try:
                    for divisor in divisors:
                        value = 1.0 / divisor
                except ZeroDivisionError:
                    return value, True
                return value, False
            def multiply(values):
                value = float('3.25')
                for item in values:
                    value = item * 2.0
                return value
            for _ in range(10):
                assert calculate([2.0] * 2000) == (0.5, False)
                assert calculate([2.0] * 2000 + [0.0]) == (0.5, True)
                assert calculate([4.0] * 2000 + [-0.0]) == (0.25, True)
                assert multiply([1.0] * 2000) == 2.0
            negative_zero = multiply([1.0] * 2000 + [-0.0])
            assert math.copysign(1.0, negative_zero) == -1.0
            assert multiply([1.0] * 2000 + [float('inf')]) == float('inf')
            assert math.isnan(multiply([1.0] * 2000 + [float('nan')]))
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_stack_root(self):
        from test.support import import_helper
        import_helper.import_module("_testinternalcapi")
        self.run_python("""
            import _opcode
            import _testinternalcapi
            import gc
            import sys
            assert sys._is_gil_enabled()
            assert sys._jit.is_enabled()
            def hot_loop(collect):
                root = {"value": [1, 2, 3]}
                total = 0
                active = False
                for value in range(1000):
                    active |= sys._jit.is_active()
                    total += value
                    if collect and value % 100 == 0:
                        gc.collect()
                    assert root["value"] == [1, 2, 3]
                return total + root["value"][0], active
            def exercise():
                # Keep harness variables local: writes to the globals dict
                # legitimately invalidate hot_loop's optimized global loads.
                for _ in range(10):
                    assert hot_loop(False)[0] == 499501
                executors = []
                for offset in range(0, len(hot_loop.__code__.co_code), 2):
                    try:
                        executors.append(_opcode.get_executor(hot_loop.__code__, offset))
                    except ValueError:
                        pass
                assert executors, "no trace was compiled"
                if _testinternalcapi.get_jit_backend() == "jit":
                    assert any(ex.get_jit_code() for ex in executors)
                observed = False
                for _ in range(10):
                    result, active = hot_loop(True)
                    assert result == 499501
                    observed |= active
                assert observed, "compiled traces were never executed"
            exercise()
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_code_reclamation(self):
        from test.support import import_helper
        import_helper.import_module("_testinternalcapi")
        self.run_python("""
            import _opcode
            import _testinternalcapi
            import gc
            import types
            import weakref
            gc.disable()
            def template():
                total = 0
                for i in range(5000):
                    total += i
                return total
            def count_executors():
                return sum(type(obj).__name__ == "uop_executor"
                           for obj in gc.get_objects())
            def make_code(invalidate):
                func = types.FunctionType(template.__code__.replace(), globals())
                assert func() == 12497500
                for offset in range(0, len(func.__code__.co_code), 2):
                    try:
                        executor = _opcode.get_executor(func.__code__, offset)
                        break
                    except ValueError:
                        pass
                else:
                    raise AssertionError("no trace was compiled")
                if invalidate:
                    _testinternalcapi.invalidate_executors(func.__code__)
                    assert not executor.is_valid()
                    assert gc.is_tracked(executor)
                return weakref.ref(func.__code__)
            before = count_executors()
            refs = [make_code(i % 2) for i in range(32)]
            for _ in range(5):
                gc.collect()
            # Conservative native roots may retain a few recent objects,
            # but the borrowed executor registry must not pin every code.
            assert sum(ref() is None for ref in refs) >= 24
            assert count_executors() <= before + 8
        """, args=("-X", "gil=1", "-X", "tlbc=0"),
            env_vars={"PYTHON_JIT": "1"})

    @unittest.skipUnless(sys._jit.is_available(), "requires a JIT build")
    def test_jit_requires_permanent_gil_and_shared_bytecode(self):
        for gil, tlbc in (("0", "0"), ("0", "1"), ("1", "1")):
            with self.subTest(gil=gil, tlbc=tlbc):
                env = os.environ.copy()
                env["PYTHON_JIT"] = "1"
                proc = subprocess.run(
                    [sys.executable, "-S", "-X", f"gil={gil}",
                     "-X", f"tlbc={tlbc}", "-c", "pass"],
                    env=env, capture_output=True, text=True, timeout=60,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("tracing GC JIT requires", proc.stderr)


if __name__ == "__main__":
    unittest.main()
