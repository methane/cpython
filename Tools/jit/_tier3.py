"""A small, experimental value-IR laboratory for a future tier-3 JIT.

This module deliberately does not participate in the CPython build.  It lets us
measure transformations on traces without adding another source of Python
semantics: adapters are expected to consume uops produced from bytecodes.c.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable


Value = int


@dataclass(frozen=True, slots=True)
class Instruction:
    """One SSA instruction.

    ``effect`` prevents speculative operations from being removed or shared.
    Guards therefore survive DCE even when their result is otherwise unused.
    """

    op: str
    output: Value | None = None
    inputs: tuple[Value, ...] = ()
    immediate: int | None = None
    effect: bool = False
    loop: bool = False


@dataclass(frozen=True, slots=True)
class Allocation:
    value: Value
    register: int | None
    spill: int | None


def _resolve(value: Value, aliases: dict[Value, Value]) -> Value:
    while value in aliases:
        value = aliases[value]
    return value


def optimize(
    trace: Iterable[Instruction],
    *,
    constant_folding: bool = True,
    cse: bool = True,
    dce: bool = True,
    licm: bool = True,
) -> list[Instruction]:
    """Run constant folding, GVN/CSE, LICM, and DCE on a linear loop trace."""
    aliases: dict[Value, Value] = {}
    constants: dict[Value, int] = {}
    expressions: dict[tuple[str, tuple[Value, ...], int | None], Value] = {}
    folded: list[Instruction] = []

    for instruction in trace:
        inputs = tuple(_resolve(value, aliases) for value in instruction.inputs)
        instruction = replace(instruction, inputs=inputs)
        if instruction.op == "const":
            assert instruction.output is not None
            assert instruction.immediate is not None
            constants[instruction.output] = instruction.immediate
        elif constant_folding and instruction.op in {"add_int", "mul_int"} and all(
            value in constants for value in inputs
        ):
            assert instruction.output is not None
            left, right = (constants[value] for value in inputs)
            value = left + right if instruction.op == "add_int" else left * right
            instruction = Instruction("const", instruction.output, immediate=value)
            constants[instruction.output] = value

        if cse and instruction.output is not None and not instruction.effect:
            key = (instruction.op, instruction.inputs, instruction.immediate)
            previous = expressions.get(key)
            if previous is not None:
                aliases[instruction.output] = previous
                continue
            expressions[key] = instruction.output
        folded.append(instruction)

    # A linear trace marks instructions in its loop body.  Pure instructions
    # whose inputs are defined outside the body are loop invariant.
    loop_defs = {
        instruction.output
        for instruction in folded
        if instruction.loop and instruction.output is not None
    }
    first_loop = next(
        (i for i, instruction in enumerate(folded) if instruction.loop), len(folded)
    )
    before_loop: list[Instruction] = []
    hoisted: list[Instruction] = []
    body: list[Instruction] = []
    for position, instruction in enumerate(folded):
        if licm and (
            instruction.loop
            and not instruction.effect
            and instruction.op not in {"phi", "result"}
            and all(value not in loop_defs for value in instruction.inputs)
        ):
            instruction = replace(instruction, loop=False)
            hoisted.append(instruction)
        elif position < first_loop:
            before_loop.append(instruction)
        else:
            body.append(instruction)
    ordered = before_loop + hoisted + body

    if not dce:
        return ordered

    live: set[Value] = set()
    kept: list[Instruction] = []
    for instruction in reversed(ordered):
        required = instruction.effect or instruction.output is None
        required |= instruction.output in live
        if required:
            kept.append(instruction)
            if instruction.output is not None:
                live.discard(instruction.output)
            live.update(instruction.inputs)
    kept.reverse()
    return kept


def allocate_registers(
    trace: Iterable[Instruction], register_count: int
) -> list[Allocation]:
    """Allocate SSA live intervals with a deterministic linear scan."""
    if register_count < 0:
        raise ValueError("register_count must not be negative")
    instructions = list(trace)
    starts: dict[Value, int] = {}
    ends: dict[Value, int] = {}
    for position, instruction in enumerate(instructions):
        if instruction.output is not None:
            starts[instruction.output] = position
            ends[instruction.output] = position
        for value in instruction.inputs:
            ends[value] = position

    free = list(range(register_count))
    active: list[tuple[int, Value, int]] = []
    spill_count = 0
    allocations: list[Allocation] = []
    for value in sorted(starts, key=starts.__getitem__):
        start = starts[value]
        still_active = []
        for end, old_value, register in active:
            if end < start:
                free.append(register)
            else:
                still_active.append((end, old_value, register))
        active = still_active
        free.sort(reverse=True)
        if free:
            register = free.pop()
            active.append((ends[value], value, register))
            active.sort()
            allocations.append(Allocation(value, register, None))
        else:
            allocations.append(Allocation(value, None, spill_count))
            spill_count += 1
    return allocations
