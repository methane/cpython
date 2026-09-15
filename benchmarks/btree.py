#!/usr/bin/env python3
"""Update and query a pure-Python B-tree of application-like records.

Exercises recursive calls, slots, generators/yield from, subscription
protocols and list mutation. Compared with the original workload, this
uses 20000 rather than 200000 records, precomputes random inputs and
omits explicit gc.collect(). Normal automatic GC remains enabled.

Standalone, standard-library-only adaptation of
pyperformance/data-files/benchmarks/bm_btree/run_benchmark.py.
Run with --help for the spectral_norm.py-compatible timing options.

Original module description and attribution:
Benchmark for b-tree workload.  This is intended to exercise the cyclic
garbage collector by presenting it with a large and interconnected
object graph.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import statistics
import sys
import time

BENCHMARK = "btree"
NUM_NODES = 20_000
RECREATE_FRACTION = 0.2
RANDOM_SEED = 0
WORKLOAD = "20000 records: insert, delete/reinsert 20%, traverse and look up"


class BNode:
    """
    Instance attributes:
      items: list
      nodes: [BNode]
    """

    __slots__ = ["items", "nodes"]

    minimum_degree = 16  # a.k.a. t

    def __init__(self):
        self.items = []
        self.nodes = None

    def is_leaf(self):
        return self.nodes is None

    def __iter__(self):
        if self.is_leaf():
            yield from self.items
        else:
            for position, item in enumerate(self.items):
                yield from self.nodes[position]
                yield item
            yield from self.nodes[-1]

    def is_full(self):
        return len(self.items) == 2 * self.minimum_degree - 1

    def get_position(self, key):
        for position, item in enumerate(self.items):
            if item[0] >= key:
                return position
        return len(self.items)

    def search(self, key):
        """(key:anything) -> None | (key:anything, value:anything)
        Return the matching pair, or None.
        """
        position = self.get_position(key)
        if position < len(self.items) and self.items[position][0] == key:
            return self.items[position]
        elif self.is_leaf():
            return None
        else:
            return self.nodes[position].search(key)

    def insert_item(self, item):
        """(item:(key:anything, value:anything))"""
        assert not self.is_full()
        key = item[0]
        position = self.get_position(key)
        if position < len(self.items) and self.items[position][0] == key:
            self.items[position] = item
        elif self.is_leaf():
            self.items.insert(position, item)
        else:
            child = self.nodes[position]
            if child.is_full():
                self.split_child(position, child)
                if key == self.items[position][0]:
                    self.items[position] = item
                else:
                    if key > self.items[position][0]:
                        position += 1
                    self.nodes[position].insert_item(item)
            else:
                self.nodes[position].insert_item(item)

    def split_child(self, position, child):
        """(position:int, child:BNode)"""
        assert not self.is_full()
        assert not self.is_leaf()
        assert self.nodes[position] is child
        assert child.is_full()
        bigger = self.__class__()
        middle = self.minimum_degree - 1
        splitting_key = child.items[middle]
        bigger.items = child.items[middle + 1 :]
        child.items = child.items[:middle]
        assert len(bigger.items) == len(child.items)
        if not child.is_leaf():
            bigger.nodes = child.nodes[middle + 1 :]
            child.nodes = child.nodes[: middle + 1]
            assert len(bigger.nodes) == len(child.nodes)
        self.items.insert(position, splitting_key)
        self.nodes.insert(position + 1, bigger)

    def get_count(self):
        """() -> int
        How many items are stored in this node and descendants?
        """
        result = len(self.items)
        for node in self.nodes or []:
            result += node.get_count()
        return result

    def get_level(self):
        """() -> int
        How many levels of nodes are there between this node
        and descendant leaf nodes?
        """
        if self.is_leaf():
            return 0
        else:
            return 1 + self.nodes[0].get_level()

    def get_min_item(self):
        """() -> (key:anything, value:anything)
        Return the item with the minimal key.
        """
        if self.is_leaf():
            return self.items[0]
        else:
            return self.nodes[0].get_min_item()

    def get_max_item(self):
        """() -> (key:anything, value:anything)
        Return the item with the maximal key.
        """
        if self.is_leaf():
            return self.items[-1]
        else:
            return self.nodes[-1].get_max_item()

    def delete(self, key):
        """(key:anything)
        Delete the item with this key.
        This is intended to follow the description in 19.3 of
        'Introduction to Algorithms' by Cormen, Lieserson, and Rivest.
        """

        def is_big(node):
            # Precondition for recursively calling node.delete(key).
            return node and len(node.items) >= node.minimum_degree

        p = self.get_position(key)
        matches = p < len(self.items) and self.items[p][0] == key
        if self.is_leaf():
            if matches:
                # Case 1.
                del self.items[p]
            else:
                raise KeyError(key)
        else:
            node = self.nodes[p]
            lower_sibling = p > 0 and self.nodes[p - 1]
            upper_sibling = p < len(self.nodes) - 1 and self.nodes[p + 1]
            if matches:
                # Case 2.
                if is_big(node):
                    # Case 2a.
                    extreme = node.get_max_item()
                    node.delete(extreme[0])
                    self.items[p] = extreme
                elif is_big(upper_sibling):
                    # Case 2b.
                    extreme = upper_sibling.get_min_item()
                    upper_sibling.delete(extreme[0])
                    self.items[p] = extreme
                else:
                    # Case 2c.
                    extreme = upper_sibling.get_min_item()
                    upper_sibling.delete(extreme[0])
                    node.items = node.items + [extreme] + upper_sibling.items
                    if not node.is_leaf():
                        node.nodes = node.nodes + upper_sibling.nodes
                    del self.items[p]
                    del self.nodes[p + 1]
            else:
                if not is_big(node):
                    if is_big(lower_sibling):
                        # Case 3a1: Shift an item from lower_sibling.
                        node.items.insert(0, self.items[p - 1])
                        self.items[p - 1] = lower_sibling.items[-1]
                        del lower_sibling.items[-1]
                        if not node.is_leaf():
                            node.nodes.insert(0, lower_sibling.nodes[-1])
                            del lower_sibling.nodes[-1]
                    elif is_big(upper_sibling):
                        # Case 3a2: Shift an item from upper_sibling.
                        node.items.append(self.items[p])
                        self.items[p] = upper_sibling.items[0]
                        del upper_sibling.items[0]
                        if not node.is_leaf():
                            node.nodes.append(upper_sibling.nodes[0])
                            del upper_sibling.nodes[0]
                    elif lower_sibling:
                        # Case 3b1: Merge with lower_sibling
                        node.items = (
                            lower_sibling.items + [self.items[p - 1]] + node.items
                        )
                        if not node.is_leaf():
                            node.nodes = lower_sibling.nodes + node.nodes
                        del self.items[p - 1]
                        del self.nodes[p - 1]
                    else:
                        # Case 3b2: Merge with upper_sibling
                        node.items = node.items + [self.items[p]] + upper_sibling.items
                        if not node.is_leaf():
                            node.nodes = node.nodes + upper_sibling.nodes
                        del self.items[p]
                        del self.nodes[p + 1]
                assert is_big(node)
                node.delete(key)
            if not self.items:
                # This can happen when self is the root node.
                self.items = self.nodes[0].items
                self.nodes = self.nodes[0].nodes


class BTree:
    """
    Instance attributes:
      root: BNode
    """

    __slots__ = ["root"]

    def __init__(self):
        self.root = BNode()

    def __bool__(self):
        return bool(self.root.items)

    def iteritems(self):
        yield from self.root

    def iterkeys(self):
        for item in self.root:
            yield item[0]

    def __iter__(self):
        yield from self.iterkeys()

    def __contains__(self, key):
        return self.root.search(key) is not None

    def __setitem__(self, key, value):
        self.add(key, value)

    def __getitem__(self, key):
        item = self.root.search(key)
        if item is None:
            raise KeyError(key)
        return item[1]

    def __delitem__(self, key):
        self.root.delete(key)

    def get(self, key, default=None):
        """(key:anything, default:anything=None) -> anything"""
        try:
            return self[key]
        except KeyError:
            return default

    def add(self, key, value=True):
        """(key:anything, value:anything=True)
        Make self[key] == val.
        """
        if self.root.is_full():
            # replace and split.
            node = self.root.__class__()
            node.nodes = [self.root]
            node.split_child(0, node.nodes[0])
            self.root = node
        self.root.insert_item((key, value))

    def __len__(self):
        """() -> int
        Compute and return the total number of items."""
        return self.root.get_count()


class Record:
    def __init__(self, a, b, c, d, e, f):
        self.a = a
        self.b = b
        self.c = c
        self.d = d
        self.e = e
        self.f = f


def make_records(num_nodes):
    rnd = random.Random(RANDOM_SEED)
    for node_id in range(num_nodes):
        a = node_id
        b = f"node {node_id}"
        c = rnd.randbytes(node_id % 100)
        d = rnd.random()
        e = sys.intern(str(rnd.randint(0, 30)))
        f = rnd.choice([None, True, False])
        yield Record(a, b, c, d, e, f)


def prepare_inputs():
    # Deterministic setup, outside all timed regions. Keep input objects alive
    # between operations, but create a fresh BTree for every operation.
    records = tuple(make_records(NUM_NODES))
    ids = list(range(NUM_NODES))
    random.Random(RANDOM_SEED).shuffle(ids)
    rnd = random.Random(RANDOM_SEED)
    lookups = tuple(rnd.randint(0, NUM_NODES) for _ in range(max(200, NUM_NODES // 20)))
    # Always exercise a missing-key lookup as well.
    return records, tuple(ids), lookups + (NUM_NODES,)


RECORDS, INSERT_IDS, LOOKUP_IDS = prepare_inputs()
EXPECTED_TOTAL = sum(record.d for record in RECORDS)
EXPECTED_LOOKUP_TOTAL = sum(RECORDS[key].d for key in LOOKUP_IDS if key < NUM_NODES)


def benchmark():
    tree = BTree()
    for node_id in INSERT_IDS:
        tree[node_id] = RECORDS[node_id]

    remake_ids = range(int(NUM_NODES * RECREATE_FRACTION))
    for node_id in remake_ids:
        del tree[node_id]
    for node_id in remake_ids:
        tree[node_id] = RECORDS[node_id]

    total = 0.0
    for key in tree:
        node = tree[key]
        total += node.d

    lookup_total = 0.0
    for node_id in LOOKUP_IDS:
        node = tree.get(node_id)
        if node is not None:
            lookup_total += node.d
    return tree, total, lookup_total


def check_result(result):
    tree, total, lookup_total = result
    if len(tree) != NUM_NODES:
        raise RuntimeError(f"BTree size is invalid: {len(tree)}")
    for expected_key, (key, record) in enumerate(tree.iteritems()):
        if key != expected_key or record is not RECORDS[expected_key]:
            raise RuntimeError(f"BTree record is invalid at key {expected_key}")
    if not math.isclose(total, EXPECTED_TOTAL, rel_tol=1e-12):
        raise RuntimeError(f"BTree traversal total is invalid: {total}")
    if not math.isclose(lookup_total, EXPECTED_LOOKUP_TOTAL, rel_tol=1e-12):
        raise RuntimeError(f"BTree lookup total is invalid: {lookup_total}")
    return {"records": NUM_NODES, "total": total, "lookup_total": lookup_total}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--loops",
        type=int,
        default=1,
        help="operations per measured value (default: 1)",
    )
    parser.add_argument(
        "--warmups", type=int, default=3, help="unmeasured warmup values (default: 3)"
    )
    parser.add_argument(
        "--values", type=int, default=10, help="measured values (default: 10)"
    )
    parser.add_argument(
        "--json", action="store_true", help="write machine-readable output"
    )
    args = parser.parse_args()
    if args.loops < 1:
        parser.error("--loops must be positive")
    if args.warmups < 0:
        parser.error("--warmups must be non-negative")
    if args.values < 1:
        parser.error("--values must be positive")
    return args


def run_loops(loops: int):
    result = None
    for _ in range(loops):
        result = benchmark()
    return result


def format_duration(seconds: float) -> str:
    if seconds >= 1.0:
        return f"{seconds:.6f} sec"
    return f"{seconds * 1_000:.3f} ms"


def main() -> None:
    args = parse_args()
    for _ in range(args.warmups):
        check_result(run_loops(args.loops))

    samples = []
    checksum = None
    for _ in range(args.values):
        start = time.perf_counter()
        result = run_loops(args.loops)
        elapsed = time.perf_counter() - start
        checksum = check_result(result)
        samples.append(elapsed / args.loops)

    jit = getattr(sys, "_jit", None)
    output = {
        "benchmark": BENCHMARK,
        "runtime": f"Python {platform.python_version()} "
        f"({platform.python_implementation()})",
        "executable": sys.executable,
        "python_version": sys.version,
        "jit_enabled": jit.is_enabled() if jit is not None else None,
        "workload": WORKLOAD,
        "loops": args.loops,
        "warmups": args.warmups,
        "values": args.values,
        "median_seconds": statistics.median(samples),
        "minimum_seconds": min(samples),
        "samples_seconds": samples,
        "checksum": checksum,
    }
    if args.json:
        print(json.dumps(output, indent=2))
        return

    print(output["runtime"])
    print(f"{BENCHMARK}: {WORKLOAD}")
    print(f"median: {format_duration(output['median_seconds'])}")
    print(f"minimum: {format_duration(output['minimum_seconds'])}")
    print("values: " + ", ".join(format_duration(value) for value in samples))


if __name__ == "__main__":
    main()
