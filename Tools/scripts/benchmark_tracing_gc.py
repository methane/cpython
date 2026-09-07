#!/usr/bin/env python3
"""Compare reference operations or explicit collection across two builds.

The refcounts suite disables cyclic GC, but does not disable immediate
reference-counted destruction. In a tracing build it may retain all garbage;
use the collections suite for explicit reclamation, or the automatic suite
to measure the reference workloads with automatic GC enabled. The numeric
suite measures temporary float allocation with automatic GC enabled.
The mixed suite measures container and scalar churn, including young cycles
and churn beside a long-lived heap, with automatic GC enabled.
"""

import argparse
import json
import statistics
import subprocess
import textwrap


WORKLOADS = {
    "dict_refs": """
        values = (object(), object())
        holder = {"value": values[0]}
        def bench():
            for index in range(5_000_000):
                holder["value"] = values[index & 1]
            return holder["value"] is values[1]
    """,
    "stack_refs": """
        value = object()
        def bench():
            total = 0
            for _ in range(5_000_000):
                item = value
                total += item is value
            return total
    """,
    "container_refs": """
        values = list(range(100))
        def bench():
            total = 0
            for _ in range(500_000):
                copied = list(values)
                total += len(copied)
            return total
    """,
    "call_refs": """
        value = object()
        def identity(item):
            return item
        def bench():
            total = 0
            for _ in range(3_000_000):
                total += identity(value) is value
            return total
    """,
}

MIXED_WORKLOADS = {
    "wide_list_clear": """
        def bench():
            for _ in range(2000):
                value = [None] * 10000
                value.clear()
            return value
    """,
    "mixed_containers": """
        def bench():
            for i in range(500000):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value
    """,
    "mixed_cycles": """
        def bench():
            for i in range(200000):
                value = [i, {'payload': 'payload-%d' % i}]
                value.append((value,))
            return value[0], value[1]['payload'], value[2][0] is value
    """,
    "mixed_with_old_scalars": """
        roots = [str(i) for i in range(500000)]
        def bench():
            for i in range(500000):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value, len(roots), roots[0], roots[-1]
    """,
    "mixed_with_old_lists": """
        roots = [[None] for _ in range(100000)]
        # Establish alias bits before the full-GC baseline and keep the
        # old headers unchanged while allocating new containers.
        for row in roots:
            assert row[0] is None
        del row
        def hot(n):
            for i in range(n):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value, len(roots), roots[0][0], roots[-1][0]
        def bench():
            return hot(500000)
    """,
    "mixed_with_old_dicts": """
        roots = [{'value': None} for _ in range(50000)]
        for row in roots:
            assert row['value'] is None
        del row
        def hot(n):
            for i in range(n):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value, len(roots), roots[0]['value'], roots[-1]['value']
        def bench():
            return hot(500000)
    """,
    "mixed_with_old_instances": """
        class Node:
            __slots__ = tuple('slot_%d' % i for i in range(128))
        roots = [Node() for _ in range(500)]
        for i, obj in enumerate(roots):
            obj.slot_0 = ['live', i]
        def hot(n):
            for i in range(n):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value, len(roots), roots[-1].slot_0
        def bench():
            return hot(500000)
    """,
    "deferred_payload_churn": """
        class Node:
            __slots__ = ('payload', 'link')
        def hot(n):
            for batch in range(n):
                for i in range(32):
                    obj = Node()
                    obj.payload = [bytes([i]) * (128 << 10)]
                    obj.link = obj
                for i in range(20000):
                    value = [i, {'value': i}]
            return value, len(obj.payload[0]), obj.link is obj
        def bench():
            return hot(16)
    """,
    "instance_container_phases": """
        class Node:
            __slots__ = ('payload', 'link')
        def make_instances(n):
            for i in range(n):
                obj = Node()
                obj.payload = [i, 'payload-%d' % i, i + 0.125]
                obj.link = obj
            return obj.payload, obj.link is obj
        def make_containers(n):
            for i in range(n):
                value = [i, i + 0.25, 'payload-%d' % i]
            return value
        def bench():
            for _ in range(4):
                instance = make_instances(50000)
                container = make_containers(125000)
            return instance, container
    """,
}


READ_WORKLOADS = {
    "list_reads": """
        from itertools import repeat
        items = [float('12345.125')]
        def hot(n):
            for _ in repeat(None, n):
                value = items[0]
            return value is items[0]
        def bench():
            return hot(2000000)
    """,
    "dict_reads": """
        from itertools import repeat
        mapping = {'value': float('12345.125')}
        def hot(n):
            for _ in repeat(None, n):
                value = mapping['value']
            return value is mapping['value']
        def bench():
            return hot(2000000)
    """,
    "slot_reads": """
        from itertools import repeat
        class Holder:
            __slots__ = ('value',)
        holder = Holder()
        holder.value = float('12345.125')
        def hot(n):
            for _ in repeat(None, n):
                value = holder.value
            return value is holder.value
        def bench():
            return hot(2000000)
    """,
    "shared_list_reads": """
        from itertools import repeat
        import threading
        items = [float('12345.125')]
        def hot(n):
            for _ in repeat(None, n):
                value = items[0]
            return value is items[0]
        def bench():
            ready = threading.Barrier(5)
            errors = []
            def worker():
                try:
                    ready.wait()
                    assert hot(500000)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for thread in threads:
                thread.join()
            assert not errors, errors
            return True
    """,
}


COLLECTION_WORKLOADS = {
    "empty_collect": """
        def bench():
            gc.collect()
            return True
    """,
    "cycles_collect": """
        def bench():
            for _ in range(10000):
                cycle = []
                cycle.append(cycle)
            del cycle
            gc.collect()
            return True
    """,
    "tuples_collect": """
        def bench():
            for _ in range(20000):
                tuple([None, None])
            gc.collect()
            return True
    """,
    "live_graph_collect": """
        root = [[None] for _ in range(210000)]
        def bench():
            gc.collect()
            return len(root)
    """,
    "live_dicts_collect": """
        root = [{('key-%d' % j): ('value-%d-%d' % (i, j))
                 for j in range(4)} for i in range(20000)]
        def bench():
            gc.collect()
            assert root[-1]['key-3'] == 'value-19999-3'
            return len(root)
    """,
    "live_functions_collect": """
        root = [lambda value=('value-%d' % i): value for i in range(20000)]
        def bench():
            gc.collect()
            assert root[-1]() == 'value-19999'
            return len(root)
    """,
}

LEAF_WORKLOADS = {
    "leaf_churn_collect": """
        def bench():
            for batch in range(10):
                for i in range(10000):
                    i + 1000000
                    i + 0.25
                    'value-%d' % i
                    b'value-%d' % i
                    complex(i, 0.25)
                gc.collect()
            return True
    """,
    "numeric_loop_collect": """
        def bench():
            value = 0.0
            for batch in range(10):
                for i in range(10000):
                    value = (value + i * 0.001) * 0.999
                gc.collect()
            return value
    """,
}

DYNAMIC_WORKLOADS = {
    "instance_cycles": """
        class Node:
            __slots__ = ('payload', 'link')

        def bench():
            for i in range(200000):
                obj = Node()
                obj.payload = [i, 'payload-%d' % i, i + 0.125]
                obj.link = obj
            return obj.payload, obj.link is obj
    """,
    "short_lived_functions": """
        def bench():
            for _ in range(2000):
                def function(payload='x' * 16384):
                    return len(payload)
                assert function() == 16384
            return True
    """,
    "short_lived_code": """
        def bench():
            for _ in range(5000):
                code = compile('result = 42', '<gc-benchmark>', 'exec')
                assert code.co_name == '<module>'
            return True
    """,
    "dynamic_type_cycles": """
        import weakref

        def make_types(n):
            refs = []
            for i in range(n):
                cls = type('temporary-%d' % i, (), {})
                obj = cls()
                obj.payload = ['payload-%d' % i, i + 0.125]
                obj.link = obj
                cls.instance = obj
                refs.append(weakref.ref(cls))
            return refs

        def bench():
            for _ in range(8):
                refs = make_types(2000)
                gc.collect()
            return len(refs)
    """,
}

NUMERIC_WORKLOADS = {
    "integer_local_updates": """
        from itertools import repeat
        def hot(n):
            value = 10000
            for _ in repeat(None, n):
                value += 1
            return value
        def bench():
            return hot(500000)
    """,
    "integer_list": """
        root = None
        def hot(n):
            global root
            root = [i + 10000 for i in range(n)]
            return len(root), root[0], root[-1], sum(root)
        def bench():
            return hot(1000000)
    """,
    "large_integer_updates": """
        def hot(n):
            value = (1 << 90) + 12345
            mask = (1 << 96) - 1
            for i in range(n):
                value = (value * 65537 + i) & mask
            return value
        def bench():
            return hot(200000)
    """,
    "float_local_updates": """
        def bench():
            x = float('1.25')
            y = float('0.5')
            for _ in range(500000):
                added = x + y
                subtracted = x - y
                multiplied = x * y
                divided = x / y
            return added, subtracted, multiplied, divided
    """,
    "float_chain": """
        def bench():
            for i in range(500000):
                value = ((i + 0.25) * 0.5 - 0.125) + 0.25
            return value
    """,
    "float_right_temporary": """
        def bench():
            for i in range(500000):
                value = 10.0 - ((i + 0.25) * 0.5)
            return value
    """,
    "float_borrowed_locals": """
        def bench():
            x = float('3.25')
            y = float('-1.5')
            for _ in range(500000):
                value = (x + y) * (x - y)
            assert x == 3.25 and y == -1.5
            return value
    """,
}

THREAD_WORKLOADS = {
    "parallel_container_reclaim": """
        import gc
        import sys
        import threading
        def hot(n):
            for i in range(n):
                value = [i, (i, None), {'value': i}]
            return value
        def run(workers=4, batches=4, iterations=1000000):
            assert iterations % workers == 0
            gate = threading.Barrier(workers + 1, timeout=60)
            errors = []
            results = [None] * workers
            live_blocks = []
            def worker(index):
                try:
                    for _ in range(batches):
                        gate.wait()
                        results[index] = hot(iterations // workers)
                        gate.wait()
                except BaseException as exc:
                    errors.append(exc)
                    gate.abort()
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(workers)]
            for thread in threads:
                thread.start()
            try:
                for _ in range(batches):
                    gate.wait()
                    gate.wait()
                    # Include deferred reclamation in the measured work.
                    # Workers remain parked until the next batch starts.
                    for _ in range(3):
                        gc.collect()
                    live_blocks.append(sys.getallocatedblocks())
            except BaseException:
                gate.abort()
                raise
            finally:
                for thread in threads:
                    thread.join()
            for _ in range(3):
                gc.collect()
            assert not errors, errors
            last = iterations // workers - 1
            assert results == [[last, (last, None), {'value': last}]] * workers
            # Retained interpreter/JIT metadata may settle after the first
            # batch, but the dead container graph must not accumulate.
            assert max(live_blocks) - min(live_blocks) < 10000, live_blocks
            run.last_blocks = live_blocks
            return workers, batches, iterations
        def bench():
            return run()
    """,
    "parallel_container_churn": """
        import threading
        def hot(n):
            for i in range(n):
                value = [i, (i, None), {'value': i}]
            return value
        def run(workers):
            ready = threading.Barrier(workers + 1)
            results = [None] * workers
            errors = []
            def worker(index):
                try:
                    ready.wait()
                    results[index] = hot(1000000 // workers)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(workers)]
            for thread in threads:
                thread.start()
            ready.wait()
            for thread in threads:
                thread.join()
            assert not errors, errors
            expected = 1000000 // workers - 1
            assert all(value == [expected, (expected, None), {'value': expected}]
                       for value in results)
            return results
        def bench():
            return run(4)
    """,
    "short_lived_threads": """
        import threading
        def worker():
            for i in range(1000):
                i + 0.25
        def bench():
            for _ in range(128):
                thread = threading.Thread(target=worker)
                thread.start()
                thread.join()
            for i in range(8000):
                i + 0.25
            return True
    """,
}


def measure(executable, workload, repetitions, workloads, *, automatic=False):
    source = textwrap.dedent(workloads[workload]) + textwrap.dedent(f"""
        import gc
        import json
        import sys
        import time
        if {automatic!r}:
            gc.enable()
        else:
            gc.disable()
        if {workloads is not WORKLOADS!r}:
            gc.collect()
        samples = []
        for _ in range({repetitions}):
            start = time.perf_counter()
            result = bench()
            samples.append(time.perf_counter() - start)
        report = {{"result": result, "samples": samples,
                  "allocated_blocks": sys.getallocatedblocks(),
                  "gc_collections": sum(s['collections'] for s in gc.get_stats())}}
        try:
            import resource
        except ImportError:
            pass
        else:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report["peak_rss_bytes"] = rss if sys.platform == "darwin" else rss * 1024
        print(json.dumps(report))
    """)
    output = subprocess.check_output(
        [executable, "-S", "-c", source], text=True
    )
    data = json.loads(output)
    data["median"] = statistics.median(data["samples"])
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", help="baseline Python executable")
    parser.add_argument("candidate", help="tracing-GC Python executable")
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument(
        "--suite",
        choices=("refcounts", "collections", "leaf", "automatic", "dynamic",
                 "numeric", "threads", "reads", "mixed"),
        default="refcounts",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")

    report = {}
    workloads = {"refcounts": WORKLOADS, "collections": COLLECTION_WORKLOADS,
                 "leaf": LEAF_WORKLOADS, "automatic": WORKLOADS,
                 "dynamic": DYNAMIC_WORKLOADS,
                 "numeric": NUMERIC_WORKLOADS,
                 "threads": THREAD_WORKLOADS,
                 "reads": READ_WORKLOADS,
                 "mixed": MIXED_WORKLOADS}[args.suite]
    automatic = args.suite in ("automatic", "dynamic", "numeric", "threads",
                              "reads", "mixed")
    for name in workloads:
        baseline = measure(args.baseline, name, args.repetitions, workloads,
                           automatic=automatic)
        candidate = measure(args.candidate, name, args.repetitions, workloads,
                            automatic=automatic)
        report[name] = {
            "baseline": baseline,
            "candidate": candidate,
            "speedup": baseline["median"] / candidate["median"],
        }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
