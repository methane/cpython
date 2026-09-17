#!/usr/bin/env python3
"""Solve an embedded Hexiom board with pure-Python backtracking.

Exercises branch-heavy recursive search, nested lists, cloning mutable
state and dict lookups. Retains the original level-25 input and search
strategy, including board parsing and in-memory solution formatting.

Standalone, standard-library-only adaptation of
pyperformance/data-files/benchmarks/bm_hexiom/run_benchmark.py.
Run with --help for the spectral_norm.py-compatible timing options.

Original module description and attribution:
Solver of Hexiom board game.

Benchmark from Laurent Vaucher.

Source: https://github.com/slowfrog/hexiom : hexiom2.py, level36.txt

(Main function tweaked by Armin Rigo.)
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import statistics
import sys
import time

BENCHMARK = "hexiom"
WORKLOAD = "solve Hexiom level 25 with the original first-cell/descending strategy"
BOARD = "3\n   4 . .\n  . . 2 .\n 4 3 2 . 4\n  2 2 3 .\n   4 2 4"
EXPECTED_SOLUTION = "  3 4 2\n 2 4 4 .\n. . . 4 2\n . 2 4 3\n  . 2 ."


##################################
class Dir(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y


DIRS = [Dir(1, 0), Dir(-1, 0), Dir(0, 1), Dir(0, -1), Dir(1, 1), Dir(-1, -1)]

EMPTY = 7

##################################


class Done(object):
    MIN_CHOICE_STRATEGY = 0
    MAX_CHOICE_STRATEGY = 1
    HIGHEST_VALUE_STRATEGY = 2
    FIRST_STRATEGY = 3
    MAX_NEIGHBORS_STRATEGY = 4
    MIN_NEIGHBORS_STRATEGY = 5

    def __init__(self, count, empty=False):
        self.count = count
        self.cells = (
            None if empty else [[0, 1, 2, 3, 4, 5, 6, EMPTY] for i in range(count)]
        )

    def clone(self):
        ret = Done(self.count, True)
        ret.cells = [self.cells[i][:] for i in range(self.count)]
        return ret

    def __getitem__(self, i):
        return self.cells[i]

    def set_done(self, i, v):
        self.cells[i] = [v]

    def already_done(self, i):
        return len(self.cells[i]) == 1

    def remove(self, i, v):
        if v in self.cells[i]:
            self.cells[i].remove(v)
            return True
        else:
            return False

    def remove_all(self, v):
        for i in range(self.count):
            self.remove(i, v)

    def remove_unfixed(self, v):
        changed = False
        for i in range(self.count):
            if not self.already_done(i):
                if self.remove(i, v):
                    changed = True
        return changed

    def filter_tiles(self, tiles):
        for v in range(8):
            if tiles[v] == 0:
                self.remove_all(v)

    def next_cell_min_choice(self):
        minlen = 10
        mini = -1
        for i in range(self.count):
            if 1 < len(self.cells[i]) < minlen:
                minlen = len(self.cells[i])
                mini = i
        return mini

    def next_cell_max_choice(self):
        maxlen = 1
        maxi = -1
        for i in range(self.count):
            if maxlen < len(self.cells[i]):
                maxlen = len(self.cells[i])
                maxi = i
        return maxi

    def next_cell_highest_value(self):
        maxval = -1
        maxi = -1
        for i in range(self.count):
            if not self.already_done(i):
                maxvali = max(k for k in self.cells[i] if k != EMPTY)
                if maxval < maxvali:
                    maxval = maxvali
                    maxi = i
        return maxi

    def next_cell_first(self):
        for i in range(self.count):
            if not self.already_done(i):
                return i
        return -1

    def next_cell_max_neighbors(self, pos):
        maxn = -1
        maxi = -1
        for i in range(self.count):
            if not self.already_done(i):
                cells_around = pos.hex.get_by_id(i).links
                n = sum(
                    1 if (self.already_done(nid) and (self[nid][0] != EMPTY)) else 0
                    for nid in cells_around
                )
                if n > maxn:
                    maxn = n
                    maxi = i
        return maxi

    def next_cell_min_neighbors(self, pos):
        minn = 7
        mini = -1
        for i in range(self.count):
            if not self.already_done(i):
                cells_around = pos.hex.get_by_id(i).links
                n = sum(
                    1 if (self.already_done(nid) and (self[nid][0] != EMPTY)) else 0
                    for nid in cells_around
                )
                if n < minn:
                    minn = n
                    mini = i
        return mini

    def next_cell(self, pos, strategy=HIGHEST_VALUE_STRATEGY):
        if strategy == Done.HIGHEST_VALUE_STRATEGY:
            return self.next_cell_highest_value()
        elif strategy == Done.MIN_CHOICE_STRATEGY:
            return self.next_cell_min_choice()
        elif strategy == Done.MAX_CHOICE_STRATEGY:
            return self.next_cell_max_choice()
        elif strategy == Done.FIRST_STRATEGY:
            return self.next_cell_first()
        elif strategy == Done.MAX_NEIGHBORS_STRATEGY:
            return self.next_cell_max_neighbors(pos)
        elif strategy == Done.MIN_NEIGHBORS_STRATEGY:
            return self.next_cell_min_neighbors(pos)
        else:
            raise Exception("Wrong strategy: %d" % strategy)


##################################


class Node(object):
    def __init__(self, pos, id, links):
        self.pos = pos
        self.id = id
        self.links = links


##################################


class Hex(object):
    def __init__(self, size):
        self.size = size
        self.count = 3 * size * (size - 1) + 1
        self.nodes_by_id = self.count * [None]
        self.nodes_by_pos = {}
        id = 0
        for y in range(size):
            for x in range(size + y):
                pos = (x, y)
                node = Node(pos, id, [])
                self.nodes_by_pos[pos] = node
                self.nodes_by_id[node.id] = node
                id += 1
        for y in range(1, size):
            for x in range(y, size * 2 - 1):
                ry = size + y - 1
                pos = (x, ry)
                node = Node(pos, id, [])
                self.nodes_by_pos[pos] = node
                self.nodes_by_id[node.id] = node
                id += 1

    def link_nodes(self):
        for node in self.nodes_by_id:
            (x, y) = node.pos
            for dir in DIRS:
                nx = x + dir.x
                ny = y + dir.y
                if self.contains_pos((nx, ny)):
                    node.links.append(self.nodes_by_pos[(nx, ny)].id)

    def contains_pos(self, pos):
        return pos in self.nodes_by_pos

    def get_by_pos(self, pos):
        return self.nodes_by_pos[pos]

    def get_by_id(self, id):
        return self.nodes_by_id[id]


##################################
class Pos(object):
    def __init__(self, hex, tiles, done=None):
        self.hex = hex
        self.tiles = tiles
        self.done = Done(hex.count) if done is None else done

    def clone(self):
        return Pos(self.hex, self.tiles, self.done.clone())


##################################


def constraint_pass(pos, last_move=None):
    changed = False
    left = pos.tiles[:]
    done = pos.done

    # Remove impossible values from free cells
    free_cells = (
        range(done.count) if last_move is None else pos.hex.get_by_id(last_move).links
    )
    for i in free_cells:
        if not done.already_done(i):
            vmax = 0
            vmin = 0
            cells_around = pos.hex.get_by_id(i).links
            for nid in cells_around:
                if done.already_done(nid):
                    if done[nid][0] != EMPTY:
                        vmin += 1
                        vmax += 1
                else:
                    vmax += 1

            for num in range(7):
                if (num < vmin) or (num > vmax):
                    if done.remove(i, num):
                        changed = True

    # Computes how many of each value is still free
    for cell in done.cells:
        if len(cell) == 1:
            left[cell[0]] -= 1

    for v in range(8):
        # If there is none, remove the possibility from all tiles
        if (pos.tiles[v] > 0) and (left[v] == 0):
            if done.remove_unfixed(v):
                changed = True
        else:
            possible = sum((1 if v in cell else 0) for cell in done.cells)
            # If the number of possible cells for a value is exactly the number of available tiles
            # put a tile in each cell
            if pos.tiles[v] == possible:
                for i in range(done.count):
                    cell = done.cells[i]
                    if (not done.already_done(i)) and (v in cell):
                        done.set_done(i, v)
                        changed = True

    # Force empty or non-empty around filled cells
    filled_cells = range(done.count) if last_move is None else [last_move]
    for i in filled_cells:
        if done.already_done(i):
            num = done[i][0]
            empties = 0
            filled = 0
            unknown = []
            cells_around = pos.hex.get_by_id(i).links
            for nid in cells_around:
                if done.already_done(nid):
                    if done[nid][0] == EMPTY:
                        empties += 1
                    else:
                        filled += 1
                else:
                    unknown.append(nid)
            if len(unknown) > 0:
                if num == filled:
                    for u in unknown:
                        if EMPTY in done[u]:
                            done.set_done(u, EMPTY)
                            changed = True
                        # else:
                        #    raise Exception("Houston, we've got a problem")
                elif num == filled + len(unknown):
                    for u in unknown:
                        if done.remove(u, EMPTY):
                            changed = True

    return changed


ASCENDING = 1
DESCENDING = -1


def find_moves(pos, strategy, order):
    done = pos.done
    cell_id = done.next_cell(pos, strategy)
    if cell_id < 0:
        return []

    if order == ASCENDING:
        return [(cell_id, v) for v in done[cell_id]]
    else:
        # Try higher values first and EMPTY last
        moves = list(reversed([(cell_id, v) for v in done[cell_id] if v != EMPTY]))
        if EMPTY in done[cell_id]:
            moves.append((cell_id, EMPTY))
        return moves


def play_move(pos, move):
    (cell_id, i) = move
    pos.done.set_done(cell_id, i)


def print_pos(pos, output):
    hex = pos.hex
    done = pos.done
    size = hex.size
    for y in range(size):
        print(" " * (size - y - 1), end="", file=output)
        for x in range(size + y):
            pos2 = (x, y)
            id = hex.get_by_pos(pos2).id
            if done.already_done(id):
                c = str(done[id][0]) if done[id][0] != EMPTY else "."
            else:
                c = "?"
            print("%s " % c, end="", file=output)
        print(end="\n", file=output)
    for y in range(1, size):
        print(" " * y, end="", file=output)
        for x in range(y, size * 2 - 1):
            ry = size + y - 1
            pos2 = (x, ry)
            id = hex.get_by_pos(pos2).id
            if done.already_done(id):
                c = str(done[id][0]) if done[id][0] != EMPTY else "."
            else:
                c = "?"
            print("%s " % c, end="", file=output)
        print(end="\n", file=output)


OPEN = 0
SOLVED = 1
IMPOSSIBLE = -1


def solved(pos, output, verbose=False):
    hex = pos.hex
    tiles = pos.tiles[:]
    done = pos.done
    exact = True
    all_done = True
    for i in range(hex.count):
        if len(done[i]) == 0:
            return IMPOSSIBLE
        elif done.already_done(i):
            num = done[i][0]
            tiles[num] -= 1
            if tiles[num] < 0:
                return IMPOSSIBLE
            vmax = 0
            vmin = 0
            if num != EMPTY:
                cells_around = hex.get_by_id(i).links
                for nid in cells_around:
                    if done.already_done(nid):
                        if done[nid][0] != EMPTY:
                            vmin += 1
                            vmax += 1
                    else:
                        vmax += 1

                if (num < vmin) or (num > vmax):
                    return IMPOSSIBLE
                if num != vmin:
                    exact = False
        else:
            all_done = False

    if (not all_done) or (not exact):
        return OPEN

    print_pos(pos, output)
    return SOLVED


def solve_step(prev, strategy, order, output, first=False):
    if first:
        pos = prev.clone()
        while constraint_pass(pos):
            pass
    else:
        pos = prev

    moves = find_moves(pos, strategy, order)
    if len(moves) == 0:
        return solved(pos, output)
    else:
        for move in moves:
            # print("Trying (%d, %d)" % (move[0], move[1]))
            ret = OPEN
            new_pos = pos.clone()
            play_move(new_pos, move)
            # print_pos(new_pos)
            while constraint_pass(new_pos, move[0]):
                pass
            cur_status = solved(new_pos, output)
            if cur_status != OPEN:
                ret = cur_status
            else:
                ret = solve_step(new_pos, strategy, order, output)
            if ret == SOLVED:
                return SOLVED
    return IMPOSSIBLE


def check_valid(pos):
    hex = pos.hex
    tiles = pos.tiles
    # fill missing entries in tiles
    tot = 0
    for i in range(8):
        if tiles[i] > 0:
            tot += tiles[i]
        else:
            tiles[i] = 0
    # check total
    if tot != hex.count:
        raise Exception("Invalid input. Expected %d tiles, got %d." % (hex.count, tot))


def solve(pos, strategy, order, output):
    check_valid(pos)
    return solve_step(pos, strategy, order, output, first=True)


# TODO Write an 'iterator' to go over all x,y positions


def read_file(file):
    lines = [line.strip("\r\n") for line in file.splitlines()]
    size = int(lines[0])
    hex = Hex(size)
    linei = 1
    tiles = 8 * [0]
    done = Done(hex.count)
    for y in range(size):
        line = lines[linei][size - y - 1 :]
        p = 0
        for x in range(size + y):
            tile = line[p : p + 2]
            p += 2
            if tile[1] == ".":
                inctile = EMPTY
            else:
                inctile = int(tile)
            tiles[inctile] += 1
            # Look for locked tiles
            if tile[0] == "+":
                # print("Adding locked tile: %d at pos %d, %d, id=%d" %
                #      (inctile, x, y, hex.get_by_pos((x, y)).id))
                done.set_done(hex.get_by_pos((x, y)).id, inctile)

        linei += 1
    for y in range(1, size):
        ry = size - 1 + y
        line = lines[linei][y:]
        p = 0
        for x in range(y, size * 2 - 1):
            tile = line[p : p + 2]
            p += 2
            if tile[1] == ".":
                inctile = EMPTY
            else:
                inctile = int(tile)
            tiles[inctile] += 1
            # Look for locked tiles
            if tile[0] == "+":
                # print("Adding locked tile: %d at pos %d, %d, id=%d" %
                #      (inctile, x, ry, hex.get_by_pos((x, ry)).id))
                done.set_done(hex.get_by_pos((x, ry)).id, inctile)
        linei += 1
    hex.link_nodes()
    done.filter_tiles(tiles)
    return Pos(hex, tiles, done)


def solve_file(file, strategy, order, output):
    pos = read_file(file)
    return solve(pos, strategy, order, output)


def benchmark():
    stream = io.StringIO()
    status = solve_file(BOARD, Done.FIRST_STRATEGY, DESCENDING, stream)
    return status, stream.getvalue()


def check_result(result):
    status, output = result
    solution = "\n".join(line.rstrip() for line in output.splitlines())
    if status != SOLVED or solution != EXPECTED_SOLUTION:
        raise RuntimeError(f"Hexiom returned an invalid solution: {result!r}")
    return solution


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
