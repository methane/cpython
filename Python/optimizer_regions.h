/* Bounded arithmetic within one basic block. No frame changes, callbacks,
 * branches or side exits are allowed while native values are live. */

static int
region_opcode(const _PyUOpInstruction *inst)
{
    int op = inst->opcode;
    if (op >= _LOAD_FAST_0 && op <= _LOAD_FAST_7) {
        return _LOAD_FAST;
    }
    if (op >= _LOAD_FAST_BORROW_0 && op <= _LOAD_FAST_BORROW_7) {
        return _LOAD_FAST_BORROW;
    }
    return op;
}

static int
region_skip(const _PyUOpInstruction *buffer, int pc, int end)
{
    while (pc < end && (buffer[pc].opcode == _NOP ||
                       buffer[pc].opcode == _SET_IP ||
                       buffer[pc].opcode == _CHECK_VALIDITY)) {
        pc++;
    }
    return pc;
}

static int
region_arithmetic(int opcode)
{
    switch (opcode) {
        case _BINARY_OP_ADD_INT: return 0;
        case _BINARY_OP_SUBTRACT_INT: return 1;
        case _BINARY_OP_MULTIPLY_INT: return 2;
        default: return -1;
    }
}

/* Match one specialized operation, including its two guards and cleanup.
 * The caller has not yet established any compact-int facts. */
static int
region_int_operation(const _PyUOpInstruction *buffer, int pc, int end,
                     bool compare, int *operation)
{
    pc = region_skip(buffer, pc, end);
    while (pc < end && (buffer[pc].opcode == _GUARD_TOS_INT ||
                       buffer[pc].opcode == _GUARD_NOS_INT ||
                       buffer[pc].opcode == _GUARD_TOS_OVERFLOWED ||
                       buffer[pc].opcode == _GUARD_NOS_OVERFLOWED)) {
        pc = region_skip(buffer, pc + 1, end);
    }
    if (pc + 2 >= end ||
        (buffer[pc + 1].opcode != _POP_TOP_INT &&
         buffer[pc + 1].opcode != _POP_TOP_NOP) ||
        (buffer[pc + 2].opcode != _POP_TOP_INT &&
         buffer[pc + 2].opcode != _POP_TOP_NOP)) {
        return -1;
    }
    int op = compare ? (buffer[pc].opcode == _COMPARE_OP_INT
                        ? buffer[pc].oparg & 15 : -1)
                     : region_arithmetic(buffer[pc].opcode);
    if (op < 0) {
        return -1;
    }
    *operation = op;
    return pc + 3;
}

static int
region_local(const _PyUOpInstruction *buffer, int pc, int end, int *local)
{
    pc = region_skip(buffer, pc, end);
    if (pc >= end) {
        return -1;
    }
    int op = region_opcode(&buffer[pc]);
    if (op != _LOAD_FAST && op != _LOAD_FAST_BORROW) {
        return -1;
    }
    *local = buffer[pc].oparg;
    return pc + 1;
}

static int
region_previous_local(const _PyUOpInstruction *buffer, int *pc)
{
    while (*pc >= 0 && (buffer[*pc].opcode == _NOP ||
                       buffer[*pc].opcode == _SET_IP ||
                       buffer[*pc].opcode == _CHECK_VALIDITY)) {
        (*pc)--;
    }
    if (*pc < 0) {
        return -1;
    }
    int opcode = region_opcode(&buffer[*pc]);
    if (opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) {
        return -1;
    }
    return buffer[(*pc)--].oparg;
}

/* The bounded path keeps tagged native integers on the existing operand
 * stack. Prove every intermediate fits before emitting it: there can be no
 * exit, allocation, callback, or frame transition between START and BOX.
 * This also lets floor division by a known nonzero integer stay unboxed.
 * The separate checked-i64 path below still handles larger live-ins. */
#include "optimizer_region_bounds.h"
#define REGION_MAX_OPS 8
#define REGION_MAX_STACK 4
#define REGION_MAX_TRACE 128


static void
lower_bounded_int_regions(_PyUOpInstruction *buffer, int length)
{
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    const RegionBounds input = {-_PY_INT_REGION_INPUT_MAX, _PY_INT_REGION_INPUT_MAX};
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _GUARD_TOS_INT) {
            continue;
        }
        int end = Py_MIN(length, start + REGION_MAX_TRACE);
        int previous = start - 1;
        int right_local = region_previous_local(buffer, &previous);
        int left_local = right_local < 0 ? -1 : region_previous_local(buffer, &previous);
        _PyUOpInstruction rewrite[REGION_MAX_TRACE];
        memcpy(rewrite, buffer + start, (end - start) * sizeof(*rewrite));
        RegionBounds stack[REGION_MAX_STACK] = {input, input};
        int depth = 2;
        int locals[4];
        int nlocals = 0;
        int operations = 0;
        int entry_operation = -1;
        int stop = -1;
        int final_nlocals = 0;
        int pc = start;
        while (pc < end && operations < REGION_MAX_OPS) {
            int next = region_skip(buffer, pc, end);
            if (next >= end) {
                break;
            }
            for (int i = pc; i < next; i++) {
                rewrite[i - start].opcode = _NOP;
            }
            pc = next;
            int opcode = region_opcode(&buffer[pc]);
            if (operations == 1 && depth == 1 && left_local >= 0) {
                int left, right, operation;
                int duplicate = region_local(buffer, pc, end, &left);
                if (duplicate >= 0 && left == left_local &&
                    (duplicate = region_local(buffer, duplicate, end, &right)) >= 0 &&
                    right == right_local &&
                    (duplicate = region_int_operation(buffer, duplicate, end,
                                                      false, &operation)) >= 0 &&
                    operation == entry_operation) {
                    /* The first result is still on top, and the same two
                     * unchanged locals are used again in the same order. */
                    for (int i = pc; i < duplicate; i++) {
                        rewrite[i - start].opcode = _NOP;
                    }
                    rewrite[pc - start].opcode = _INT_REGION_DUP;
                    stack[1] = stack[0];
                    depth = 2;
                    operations++;
                    pc = duplicate;
                    continue;
                }
            }
            if (opcode == _LOAD_FAST || opcode == _LOAD_FAST_BORROW ||
                opcode == _LOAD_SMALL_INT) {
                if (depth == REGION_MAX_STACK) {
                    break;
                }
                int arg = buffer[pc].oparg;
                if (opcode == _LOAD_SMALL_INT) {
                    stack[depth++] = (RegionBounds){arg, arg};
                    rewrite[pc - start].opcode = _INT_REGION_CONST;
                }
                else {
                    int i;
                    for (i = 0; i < nlocals; i++) {
                        if (locals[i] == arg) {
                            break;
                        }
                    }
                    if (arg == UINT16_MAX || (i == nlocals && nlocals == 4)) {
                        break;
                    }
                    if (i == nlocals) {
                        locals[nlocals++] = arg;
                    }
                    stack[depth++] = input;
                    rewrite[pc - start].opcode = _INT_REGION_LOCAL;
                }
                pc++;
                continue;
            }
            if (depth < 2) {
                break;
            }
            int operation;
            next = region_int_operation(buffer, pc, end, false, &operation);
            if (next < 0) {
                /* Generic // is safe here only because both operands are
                 * our own native integers and the divisor is constant. */
                int arith = pc;
                while (arith < end &&
                       (buffer[arith].opcode == _RECORD_TOS_TYPE ||
                        buffer[arith].opcode == _RECORD_NOS_TYPE)) {
                    arith++;
                }
                if (arith + 2 >= end || buffer[arith].opcode != _BINARY_OP ||
                    (buffer[arith].oparg != NB_FLOOR_DIVIDE &&
                     buffer[arith].oparg != NB_INPLACE_FLOOR_DIVIDE) ||
                    buffer[arith + 1].opcode != _POP_TOP ||
                    buffer[arith + 2].opcode != _POP_TOP) {
                    break;
                }
                operation = 3;
                next = arith + 3;
            }
            RegionBounds value;
            if (!region_bounds(stack[depth - 2], stack[depth - 1],
                               operation, &value)) {
                break;
            }
            if (operations == 0) {
                entry_operation = operation;
            }
            /* Keep START at the original first operation's exit boundary.
             * Its two outputs replace borrowed inputs with native values. */
            int emit = pc == start ? pc + 2 : pc;
            for (int i = pc; i < next; i++) {
                rewrite[i - start].opcode = _NOP;
            }
            rewrite[emit - start].opcode = _INT_REGION_BINARY;
            rewrite[emit - start].oparg = operation;
            if (operation == 3) {
                int64_t divisor = stack[depth - 1].low;
                /* Positive powers of two use a floor-preserving shift. */
                if (divisor > 0 && (divisor & (divisor - 1)) == 0) {
                    int shift = 0;
                    while ((INT64_C(1) << shift) != divisor) {
                        shift++;
                    }
                    rewrite[emit - start].opcode = _INT_REGION_RSHIFT;
                    rewrite[emit - start].oparg = shift;
                }
            }
            depth--;
            stack[depth - 1] = value;
            operations++;
            pc = next;
            if (depth == 1 && operations >= 3) {
                stop = pc;
                final_nlocals = nlocals;
            }
        }
        if (stop < 0) {
            continue;
        }
        /* Two adjacent local loads identify the entry operands. Those
         * locals cannot change in this region and are checked by START
         * already, so do not check them again as additional live-ins. */
        int checks = 0;
        uint64_t config = 0;
        for (int i = 0; i < final_nlocals; i++) {
            if (locals[i] != left_local && locals[i] != right_local) {
                config |= (uint64_t)locals[i] << (16 * checks++);
            }
        }
        int first = 0;
        int division = region_skip(buffer, stop, end);
        if (division < end && buffer[division].opcode == _GUARD_BINARY_OP_EXTEND) {
            division++;
        }
        else {
            while (division < end &&
                   (buffer[division].opcode == _RECORD_TOS_TYPE ||
                    buffer[division].opcode == _RECORD_NOS_TYPE)) {
                division++;
            }
        }
        int box = stop - start - 1;
        if (division + 2 < end &&
            (buffer[division].opcode == _BINARY_OP_EXTEND ||
             buffer[division].opcode == _BINARY_OP) &&
            (buffer[division].oparg == NB_TRUE_DIVIDE ||
             buffer[division].oparg == NB_INPLACE_TRUE_DIVIDE) &&
            buffer[division + 1].opcode == _POP_TOP &&
            buffer[division + 2].opcode == _POP_TOP) {
            /* The numerator sits below the two entry integers. Guard it
             * before replacing either operand with a tagged native value. */
            rewrite[0] = buffer[start];
            rewrite[0].opcode = _INT_REGION_GUARD_FLOAT;
            first = 1;
            for (int i = stop; i < division + 3; i++) {
                rewrite[i - start] = buffer[i];
                if (buffer[i].opcode != _SET_IP) {
                    rewrite[i - start].opcode = _NOP;
                }
            }
            rewrite[division - start].opcode = _INT_REGION_DIVIDE;
            box = division - start;
            stop = division + 3;
        }
        else {
            rewrite[box] = buffer[start];
            rewrite[box].opcode = _INT_REGION_BOX;
            rewrite[box].oparg = 0;
        }
        rewrite[first] = buffer[start];
        rewrite[first].opcode = _INT_REGION_START;
        rewrite[first].oparg = checks;
        rewrite[first].operand0 = config;
        /* A removed cleanup slot materializes the sole live-out. All native
         * values have been consumed before any allocation can escape. */
        for (int i = first + 1; i < box; i++) {
            assert(!(_PyUop_Flags[rewrite[i].opcode] &
                     (HAS_EXIT_FLAG | HAS_ERROR_FLAG | HAS_ESCAPES_FLAG)));
        }
        memcpy(buffer + start, rewrite, (stop - start) * sizeof(*rewrite));
        start = stop - 1;
    }
}

static int
lower_len_left_compare(_PyUOpInstruction *buffer, int pc, int end)
{
    int comparison;
    int operation = 0;
    int offset = 0;
    int stop = region_int_operation(buffer, pc + 3, end, true, &comparison);
    if (stop < 0) {
        int load = region_skip(buffer, pc + 3, end);
        if (load >= end || buffer[load].opcode != _LOAD_SMALL_INT) {
            return -1;
        }
        offset = buffer[load].oparg;
        int next = region_int_operation(buffer, load + 1, end, false, &operation);
        if (next < 0 || operation == 2) {
            return -1;
        }
        stop = region_int_operation(buffer, next, end, true, &comparison);
        if (stop < 0) {
            return -1;
        }
    }
    buffer[pc].opcode = _CALL_LEN_LEFT_COMPARE;
    buffer[pc].oparg = (comparison << 1) | operation;
    buffer[pc].operand0 = offset;
    for (int i = pc + 1; i < stop - 3; i++) {
        buffer[i].opcode = _NOP;
    }
    /* Keep the original callable, receiver, then left-int cleanup order. */
    for (int i = stop - 3; i < stop; i++) {
        buffer[i].opcode = _POP_TOP;
    }
#ifndef Py_GIL_DISABLED
    buffer[pc].opcode = _CALL_LEN_LEFT_COMPARE_CLEAN;
    for (int i = stop - 3; i < stop; i++) {
        buffer[i].opcode = _NOP;
    }
#endif
    return stop;
}

static void
lower_len_regions(_PyUOpInstruction *buffer, int length)
{
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int pc = 0; pc + 2 < length; pc++) {
        if (buffer[pc].opcode != _CALL_LEN ||
            buffer[pc + 1].opcode != _POP_TOP ||
            buffer[pc + 2].opcode != _POP_TOP) {
            continue;
        }
        int end = Py_MIN(length, pc + 32);
        int left_compare = lower_len_left_compare(buffer, pc, end);
        if (left_compare >= 0) {
            pc = left_compare - 1;
            continue;
        }
        int local, op;
        bool constant = false;
        int next = region_local(buffer, pc + 3, end, &local);
        if (next < 0) {
            int load = region_skip(buffer, pc + 3, end);
            if (load >= end || buffer[load].opcode != _LOAD_SMALL_INT) {
                continue;
            }
            local = buffer[load].oparg;
            constant = true;
            next = load + 1;
        }
        int stop = region_int_operation(buffer, next, end, true, &op);
        if (stop >= 0) {
            op |= 16;
        }
        else {
            stop = region_int_operation(buffer, next, end, false, &op);
            if (stop < 0 || op == 2) {
                continue;
            }
        }
        buffer[pc].opcode = _CALL_LEN_CONSUMER;
        buffer[pc].oparg = op | (constant ? 32 : 0);
        buffer[pc].operand0 = local;
        for (int i = pc + 1; i < stop - 2; i++) {
            buffer[i].opcode = _NOP;
        }
        /* Preserve the call's original arg/callable cleanup, not the
         * removed integer consumer's operands. */
        buffer[stop - 2].opcode = _POP_TOP;
        buffer[stop - 1].opcode = _POP_TOP;
        pc = stop - 1;
    }
}

static void
lower_tuple_comparisons(_PyUOpInstruction *buffer, int length)
{
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int pc = 0; pc < length; pc++) {
        if (buffer[pc].opcode != _BUILD_TUPLE || buffer[pc].oparg != 2) {
            continue;
        }
        int end = Py_MIN(length, pc + 16);
        int local;
        int next = region_local(buffer, pc + 1, end, &local);
        if (next < 0) {
            continue;
        }
        int compare = region_skip(buffer, next, end);
        if (compare >= end || buffer[compare].opcode != _COMPARE_OP) {
            continue;
        }
        int operation = buffer[compare].oparg >> 5;
        if (operation != Py_EQ && operation != Py_NE) {
            continue;
        }
        buffer[pc].opcode = _COMPARE_TUPLE_PAIR;
        buffer[pc].oparg = operation == Py_NE;
        buffer[pc].operand0 = local;
        for (int i = pc + 1; i < compare - 1; i++) {
            buffer[i].opcode = _NOP;
        }
        /* The two immutable elements are closed in tuple-deallocation order. */
        buffer[compare - 1].opcode = _POP_TOP;
        buffer[compare].opcode = _POP_TOP;
        pc = compare;
    }
}

static int
region_skip_recorded(const _PyUOpInstruction *buffer, int pc, int end)
{
    while (pc < end) {
        pc = region_skip(buffer, pc, end);
        if (pc == end ||
            !(_PyUop_Flags[buffer[pc].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            break;
        }
        pc++;
    }
    return pc;
}

/* Run after the higher-level region matchers. Keeping borrowed inputs as
 * explicit outputs until POP_TOP_NOP unnecessarily increases cache depth. */
static void
fuse_borrowed_input_cleanup(_PyUOpInstruction *buffer, int length)
{
#ifdef Py_GIL_DISABLED
    return;
#endif
    for (int pc = 0; pc + 1 < length; pc++) {
        int opcode = buffer[pc].opcode;
        if (buffer[pc + 1].opcode != _POP_TOP_NOP) {
            continue;
        }
        if (opcode == _LOAD_ATTR_INSTANCE_VALUE || opcode == _LOAD_ATTR_SLOT) {
            buffer[pc].opcode = _LOAD_ATTR_BORROWED_OWNER;
            buffer[pc + 1].opcode = _NOP;
        }
        else if ((opcode == _BINARY_OP_SUBSCR_LIST_INT ||
                  opcode == _BINARY_OP_SUBSCR_TUPLE_INT) &&
                 pc + 2 < length && buffer[pc + 2].opcode == _POP_TOP_NOP)
        {
            buffer[pc].opcode = _BINARY_OP_SUBSCR_BORROWED;
            buffer[pc].oparg = opcode == _BINARY_OP_SUBSCR_TUPLE_INT;
            buffer[pc + 1].opcode = buffer[pc + 2].opcode = _NOP;
        }
    }
}

static void
fuse_list_pair_comparisons(_PyUOpInstruction *buffer, int length)
{
    for (int start = 0; start < length; start++) {
        if (region_opcode(&buffer[start]) != _LOAD_FAST_BORROW) {
            continue;
        }
        int list_local = buffer[start].oparg;
        int end = Py_MIN(start + 64, length);
        int pc = start + 1;
#define PAIR_NEXT() (pc = region_skip_recorded(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : -1)
#define PAIR_EXPECT(OP) do { \
    if (PAIR_NEXT() != (OP)) goto next_pair; \
    pc++; \
} while (0)
#define PAIR_GUARDS() do { \
    int op; \
    while ((op = PAIR_NEXT()) == _GUARD_TOS_INT || \
           op == _GUARD_NOS_INT || op == _GUARD_NOS_LIST) { pc++; } \
} while (0)
        if (PAIR_NEXT() != _LOAD_FAST_BORROW) {
            continue;
        }
        int index_local = buffer[pc++].oparg;
        PAIR_GUARDS();
        int first = pc;
        PAIR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        if (PAIR_NEXT() != _POP_TOP_NOP) {
            continue;
        }
        int index_cleanup = pc++;
        if (PAIR_NEXT() != _POP_TOP_NOP) {
            continue;
        }
        int list_cleanup = pc++;
        if (PAIR_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != list_local ||
            PAIR_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != index_local) {
            continue;
        }
        int constant = PAIR_NEXT();
        if (constant == _LOAD_SMALL_INT && buffer[pc].oparg == 1) {
            pc++;
        }
        else if (constant == _LOAD_CONST_INLINE_BORROW &&
                 (PyObject *)buffer[pc].operand0 == _PyLong_GetOne()) {
            pc++;
        }
        else {
            continue;
        }
        PAIR_GUARDS();
        PAIR_EXPECT(_BINARY_OP_ADD_INT);
        PAIR_EXPECT(_POP_TOP_NOP);
        PAIR_EXPECT(_POP_TOP_NOP);
        PAIR_GUARDS();
        PAIR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        int cleanup = PAIR_NEXT();
        if (cleanup != _POP_TOP_INT && cleanup != _POP_TOP_NOP) {
            continue;
        }
        pc++;
        PAIR_EXPECT(_POP_TOP_NOP);
        int compare = PAIR_NEXT();
        if (compare != _COMPARE_TUPLE_PAIR && compare != _COMPARE_TUPLE_PAIR_0 &&
            compare != _COMPARE_TUPLE_PAIR_1) {
            continue;
        }
        int operation = buffer[pc].oparg;
        uint64_t tuple_local = buffer[pc++].operand0;
        for (int i = 0; i < 2; i++) {
            int pop = PAIR_NEXT();
            if (pop != _POP_TOP && pop != _POP_TOP_NOP && pop != _POP_TOP_SHARED) {
                goto next_pair;
            }
            pc++;
        }
        /* Both list/index reads remain borrowed locals. No effects or stores
         * occur between the first subscript and the final tuple cleanup. The
         * replacement checks both indices before comparison, including when
         * the first elements differ, and exits at the original first lookup. */
        buffer[first].opcode = _COMPARE_LIST_PAIR;
        buffer[first].oparg = operation;
        buffer[first].operand0 = tuple_local;
        for (int i = first + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[index_cleanup].opcode = _POP_TOP_NOP;
        buffer[list_cleanup].opcode = _POP_TOP_NOP;
        start = pc - 1;
next_pair:
        ;
#undef PAIR_GUARDS
#undef PAIR_EXPECT
#undef PAIR_NEXT
    }
}

static void
fuse_list_length_predicates(_PyUOpInstruction *buffer, int length)
{
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _BINARY_OP_SUBSCR_LIST_INT) {
            continue;
        }
        int end = Py_MIN(length, start + 32);
        int pc = start + 1;
        for (int i = 0; i < 2; i++) {
            pc = region_skip_recorded(buffer, pc, end);
            if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                              buffer[pc].opcode != _POP_TOP_SHARED &&
                              buffer[pc].opcode != _POP_TOP_NOP)) {
                goto next_list_length;
            }
            pc++;
        }
        pc = region_skip_recorded(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _CALL_LEN_CONSUMER ||
            !(buffer[pc].oparg & 16)) {
            continue;
        }
        int comparison = buffer[pc].oparg;
        uint64_t right = buffer[pc++].operand0;
        for (int i = 0; i < 2; i++) {
            pc = region_skip_recorded(buffer, pc, end);
            if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                              buffer[pc].opcode != _POP_TOP_SHARED &&
                              buffer[pc].opcode != _POP_TOP_NOP)) {
                goto next_list_length;
            }
            pc++;
        }
        buffer[start].opcode = _LEN_SUBSCR_LIST;
        buffer[start].oparg = comparison;
        buffer[start].operand0 = right;
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_list_length:
        ;
    }
}

/* Both frontends attach these descriptors before redundant layout guards
 * are removed. No region may cross a basic-block boundary. */
static int
float_region_attribute(const _PyUOpInstruction *buffer, int pc, int end,
                       uint64_t *descriptor)
{
    int local;
    pc = region_local(buffer, pc, end, &local);
    if (pc < 0 || local > UINT8_MAX) {
        return -1;
    }
    pc = region_skip(buffer, pc, end);
    if (pc < end && buffer[pc].opcode == _GUARD_TYPE_VERSION) {
        pc = region_skip(buffer, pc + 1, end);
    }
    if (pc < end && buffer[pc].opcode == _CHECK_MANAGED_OBJECT_HAS_VALUES) {
        pc = region_skip(buffer, pc + 1, end);
    }
    if (pc >= end || (buffer[pc].opcode != _LOAD_ATTR_SLOT &&
                     buffer[pc].opcode != _LOAD_ATTR_INSTANCE_VALUE) ||
        (buffer[pc].oparg & 1) || !(buffer[pc].operand1 & UINT32_MAX) ||
        buffer[pc].operand0 > UINT16_MAX)
    {
        return -1;
    }
    *descriptor = local | (buffer[pc].operand0 << 8) |
                  (buffer[pc].operand1 << 24);
    pc = region_skip(buffer, pc + 1, end);
    if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                      buffer[pc].opcode != _POP_TOP_NOP))
    {
        return -1;
    }
    pc = region_skip(buffer, pc + 1, end);
    if (pc < end && buffer[pc].opcode == _PUSH_NULL_CONDITIONAL &&
        !(buffer[pc].oparg & 1))
    {
        pc++;
    }
    return pc;
}

static void
lower_float_attribute_products(_PyUOpInstruction *buffer, int length)
{
#ifdef Py_GIL_DISABLED
    return;
#endif
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int op = region_opcode(&buffer[start]);
        if (op != _LOAD_FAST && op != _LOAD_FAST_BORROW) {
            continue;
        }
        int end = Py_MIN(length, start + 128);
        int pc = start, stop = -1, products = 0;
        uint64_t fields = 0, common = 0, final_fields = 0;
        unsigned int owners[2] = {0, 0};
        uint32_t final_target = 0;
#define FLOAT_NEXT() (pc = region_skip(buffer, pc, end), \
                      pc < end ? buffer[pc].opcode : 0)
        for (int product = 0; product < 3; product++) {
            for (int side = 0; side < 2; side++) {
                uint64_t descriptor;
                pc = float_region_attribute(buffer, pc, end, &descriptor);
                if (pc < 0) {
                    goto finish_float_region;
                }
                uint64_t offset = (descriptor >> 8) & UINT16_MAX;
                if ((descriptor & UINT8_MAX) > 7 || offset % sizeof(PyObject *) ||
                    offset / sizeof(PyObject *) > UINT8_MAX)
                {
                    goto finish_float_region;
                }
                if (product == 0) {
                    owners[side] = descriptor & UINT8_MAX;
                    if (side == 0) {
                        common = descriptor >> 24;
                    }
                }
                if ((descriptor >> 24) != common ||
                    (descriptor & UINT8_MAX) != owners[side])
                {
                    goto finish_float_region;
                }
                fields |= (offset / sizeof(PyObject *)) << (8 * (2 * product + side));
            }
            while ((op = FLOAT_NEXT()) == _GUARD_TOS_FLOAT ||
                    op == _GUARD_NOS_FLOAT || op == _GUARD_BINARY_OP_EXTEND) {
                pc++;
            }
            op = FLOAT_NEXT();
            if (op != _BINARY_OP_MULTIPLY_FLOAT &&
                !((op == _BINARY_OP_EXTEND || op == _BINARY_OP) &&
                  buffer[pc].oparg == NB_MULTIPLY))
            {
                break;
            }
            pc++;
            for (int i = 0; i < 2; i++) {
                op = FLOAT_NEXT();
                if (op != _POP_TOP_FLOAT && op != _POP_TOP_NOP && op != _POP_TOP) {
                    goto finish_float_region;
                }
                pc++;
            }
            if (product == 0) {
                continue;
            }
            while ((op = FLOAT_NEXT()) == _GUARD_TOS_FLOAT ||
                    op == _GUARD_NOS_FLOAT || op == _GUARD_BINARY_OP_EXTEND) {
                pc++;
            }
            op = FLOAT_NEXT();
            if (op != _BINARY_OP_ADD_FLOAT &&
                op != _BINARY_OP_ADD_FLOAT_INPLACE &&
                op != _BINARY_OP_ADD_FLOAT_INPLACE_RIGHT &&
                !((op == _BINARY_OP_EXTEND || op == _BINARY_OP) &&
                  buffer[pc].oparg == NB_ADD))
            {
                break;
            }
            uint32_t target = buffer[pc++].target;
            for (int i = 0; i < 2; i++) {
                op = FLOAT_NEXT();
                if (op != _POP_TOP_FLOAT && op != _POP_TOP_NOP && op != _POP_TOP) {
                    goto finish_float_region;
                }
                pc++;
            }
            if (target > UINT16_MAX) {
                break;
            }
            stop = pc;
            products = product + 1;
            final_fields = fields;
            final_target = target;
        }
finish_float_region:
        if (stop >= 0) {
            buffer[start].opcode = _FLOAT_ATTRIBUTE_SUM_PRODUCTS;
            buffer[start].oparg = products - 2;
            buffer[start].operand0 = final_fields;
            buffer[start].operand1 = owners[0] | ((uint64_t)owners[1] << 3) |
                (common << 6) | ((uint64_t)final_target << 39);
            for (int i = start + 1; i < stop; i++) {
                buffer[i].opcode = _NOP;
            }
            start = stop - 1;
        }
#undef FLOAT_NEXT
    }
}

static int
region_int_input(const _PyUOpInstruction *buffer, int pc, int end,
                 uint64_t *descriptor)
{
    pc = region_skip(buffer, pc, end);
    if (pc == end) {
        return -1;
    }
    if (buffer[pc].opcode == _LOAD_SMALL_INT) {
        *descriptor = (UINT64_C(1) << 62) | buffer[pc].oparg;
        return pc + 1;
    }
    if (buffer[pc].opcode == _LOAD_COMMON_CONSTANT &&
        buffer[pc].oparg == CONSTANT_MINUS_ONE)
    {
        *descriptor = (UINT64_C(1) << 62) | UINT32_MAX;
        return pc + 1;
    }
    if (buffer[pc].opcode == _LOAD_CONST_INLINE_BORROW) {
        PyObject *value = (PyObject *)(uintptr_t)buffer[pc].operand0;
        if (PyLong_CheckExact(value) && _PyLong_IsCompact((PyLongObject *)value)) {
            *descriptor = (UINT64_C(1) << 62) |
                (uint32_t)_PyLong_CompactValue((PyLongObject *)value);
            return pc + 1;
        }
    }
    int next = float_region_attribute(buffer, pc, end, descriptor);
    if (next >= 0) {
        return next;
    }
    int local;
    next = region_local(buffer, pc, end, &local);
    if (next < 0 || local > UINT8_MAX) {
        return -1;
    }
    *descriptor = (UINT64_C(1) << 63) | local;
    return next;
}

/* Direct local/attribute reads own the compared integers throughout the
 * callback-free comparison. Keep the original path for non-compact integers,
 * descriptors, missing attributes and all user-defined comparison methods. */
static void
lower_int_attribute_comparisons(_PyUOpInstruction *buffer, int length)
{
#ifdef Py_GIL_DISABLED
    return;
#endif
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int op = region_opcode(&buffer[start]);
        if (op != _LOAD_FAST && op != _LOAD_FAST_BORROW &&
            op != _LOAD_SMALL_INT && op != _LOAD_COMMON_CONSTANT &&
            op != _LOAD_CONST_INLINE_BORROW)
        {
            continue;
        }
        int end = Py_MIN(length, start + 64);
        uint64_t left, right;
        int pc = region_int_input(buffer, start, end, &left);
        if (pc < 0) {
            continue;
        }
        pc = region_int_input(buffer, pc, end, &right);
        if (pc < 0 || ((left >> 62) && (right >> 62))) {
            continue;
        }
        int mask;
        int stop = region_int_operation(buffer, pc, end, true, &mask);
        if (stop < 0) {
            continue;
        }
        buffer[start].opcode = _COMPARE_INT_INPUTS;
        int left_kind = left >> 63 ? 1 : (left >> 62 ? 2 : 0);
        int right_kind = right >> 63 ? 1 : (right >> 62 ? 2 : 0);
        buffer[start].oparg = left_kind ? left_kind + 2 : right_kind;
        buffer[start].operand0 = left | ((uint64_t)mask << 58);
        buffer[start].operand1 = right;
        for (int i = start + 1; i < stop; i++) {
            buffer[i].opcode = _NOP;
        }
        start = stop - 1;
    }
}

static void
lower_int_attribute_updates(_PyUOpInstruction *buffer, int length)
{
#ifdef Py_GIL_DISABLED
    return;
#endif
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int local = 0;
        int end = Py_MIN(length, start + 64);
        bool stack_owner = buffer[start].opcode == _COPY && buffer[start].oparg == 1;
        int pc = stack_owner ? start : region_local(buffer, start, end, &local);
        if (pc < 0 || local > 255) {
            continue;
        }
        pc = region_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _COPY || buffer[pc].oparg != 1) {
            continue;
        }
        pc = region_skip(buffer, pc + 1, end);
        if (pc < end && buffer[pc].opcode == _GUARD_TYPE_VERSION) {
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc < end && buffer[pc].opcode == _CHECK_MANAGED_OBJECT_HAS_VALUES) {
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc >= end || (buffer[pc].opcode != _LOAD_ATTR_SLOT &&
                         buffer[pc].opcode != _LOAD_ATTR_INSTANCE_VALUE) ||
            (buffer[pc].oparg & 1) || buffer[pc].operand0 > UINT16_MAX)
        {
            continue;
        }
        uint32_t version = buffer[pc].operand1;
        if (version == 0) {
            continue;
        }
        bool managed = buffer[pc].opcode == _LOAD_ATTR_INSTANCE_VALUE;
        uint64_t offset = buffer[pc].operand0;
        pc = region_skip(buffer, pc + 1, end);
        if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                         buffer[pc].opcode != _POP_TOP_SHARED &&
                         buffer[pc].opcode != _POP_TOP_NOP)) {
            continue;
        }
        pc = region_skip(buffer, pc + 1, end);
        if (pc < end && buffer[pc].opcode == _PUSH_NULL_CONDITIONAL && !(buffer[pc].oparg & 1)) {
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc >= end) {
            continue;
        }
        int constant;
        if (buffer[pc].opcode == _LOAD_SMALL_INT && buffer[pc].oparg <= 63) {
            constant = buffer[pc].oparg;
        }
        else if (buffer[pc].opcode == _LOAD_CONST_INLINE_BORROW) {
            PyObject *value = (PyObject *)(uintptr_t)buffer[pc].operand0;
            if (!PyLong_CheckExact(value) || !_PyLong_IsCompact((PyLongObject *)value)) {
                continue;
            }
            Py_ssize_t number = _PyLong_CompactValue((PyLongObject *)value);
            if (number < 0 || number > 63) {
                continue;
            }
            constant = (int)number;
        }
        else {
            continue;
        }
        int operation;
        int arithmetic_start = pc + 1;
        pc = region_int_operation(buffer, arithmetic_start, end, false, &operation);
        if (pc < 0 || operation > 1) {
            continue;
        }
        int arithmetic_end = pc;
        pc = region_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _SWAP || buffer[pc].oparg != 2) {
            continue;
        }
        pc = region_skip(buffer, pc + 1, end);
        if (pc < end && buffer[pc].opcode == _LOCK_OBJECT) {
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc < end && (buffer[pc].opcode == _GUARD_TYPE_VERSION ||
                        buffer[pc].opcode == _GUARD_TYPE_VERSION_LOCKED))
        {
            if (buffer[pc].operand0 != version) {
                continue;
            }
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc < end && buffer[pc].opcode == _GUARD_DORV_NO_DICT) {
            pc = region_skip(buffer, pc + 1, end);
        }
        int store_op = managed ? _STORE_ATTR_INSTANCE_VALUE : _STORE_ATTR_SLOT;
        int safe_store_op = managed ? _STORE_ATTR_INSTANCE_VALUE_NOESCAPE
                                    : _STORE_ATTR_SLOT_NOESCAPE;
        // The fused update proves an exact integer old value, satisfying
        // the non-escaping store's destruction guard as well.
        if (pc >= end || (buffer[pc].opcode != store_op &&
                          buffer[pc].opcode != safe_store_op) ||
            buffer[pc].operand0 != offset)
        {
            continue;
        }
        pc = region_skip(buffer, pc + 1, end);
        if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                         buffer[pc].opcode != _POP_TOP_SHARED &&
                         buffer[pc].opcode != _POP_TOP_NOP)) {
            continue;
        }
        uintptr_t arithmetic_ip = buffer[arithmetic_end - 3].operand1;
        if (arithmetic_ip == 0) {
            for (int i = start; i < arithmetic_end; i++) {
                if (buffer[i].opcode == _SET_IP) {
                    arithmetic_ip = buffer[i].operand0;
                }
            }
        }
        if (arithmetic_ip == 0 ||
            _PyOpcode_Deopt[((_Py_CODEUNIT *)arithmetic_ip)->op.code] != BINARY_OP)
        {
            continue;
        }
        buffer[start].opcode = stack_owner ? _UPDATE_INT_ATTRIBUTE_STACK
                                          : _UPDATE_INT_ATTRIBUTE;
        buffer[start].oparg = 0;
        buffer[start].operand0 = (uint64_t)local | (offset << 8) |
            ((uint64_t)version << 24) | ((uint64_t)managed << 56) |
            ((uint64_t)operation << 57) | ((uint64_t)constant << 58);
        buffer[start].operand1 = arithmetic_ip;
        /* A stack receiver remains live through the update and is closed
         * in its original position, after the store has completed. */
        for (int i = start + 1; i < pc + !stack_owner; i++) {
            buffer[i].opcode = _NOP;
        }
        start = pc;
    }
}

/* Combine an immortal constant and local receiver with a guarded field store.
 * The local keeps the receiver alive, and all guards precede mutation. */
static void
lower_constant_attribute_stores(_PyUOpInstruction *buffer, int length)
{
#ifdef Py_GIL_DISABLED
    return;
#endif
    if (SIZEOF_VOID_P != 8) {
        return;
    }
    for (int start = 0; start < length; start++) {
        PyObject *constant = NULL;
        if (buffer[start].opcode == _LOAD_CONST_INLINE_BORROW) {
            constant = (PyObject *)(uintptr_t)buffer[start].operand0;
        }
        else if (buffer[start].opcode == _LOAD_COMMON_CONSTANT &&
                 buffer[start].oparg < NUM_COMMON_CONSTANTS)
        {
            constant = PyStackRef_AsPyObjectBorrow(
                _PyInterpreterState_GET()->common_consts[buffer[start].oparg]);
        }
        else if (buffer[start].opcode == _LOAD_SMALL_INT &&
                 buffer[start].oparg < _PY_NSMALLPOSINTS)
        {
            constant = (PyObject *)&_PyLong_SMALL_INTS[
                _PY_NSMALLNEGINTS + buffer[start].oparg];
        }
        if (constant == NULL || !_Py_IsImmortal(constant)) {
            continue;
        }
        int end = Py_MIN(length, start + 16);
        int local;
        int pc = region_local(buffer, start + 1, end, &local);
        if (pc < 0 || local > 255) {
            continue;
        }
        pc = region_skip(buffer, pc, end);
        if (pc < end && buffer[pc].opcode == _LOCK_OBJECT) {
            pc = region_skip(buffer, pc + 1, end);
        }
        unsigned guards = 0;
        if (pc < end && (buffer[pc].opcode == _GUARD_TYPE_VERSION ||
                        buffer[pc].opcode == _GUARD_TYPE_VERSION_LOCKED))
        {
            guards |= 1;
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc < end && buffer[pc].opcode == _GUARD_DORV_NO_DICT) {
            guards |= 2;
            pc = region_skip(buffer, pc + 1, end);
        }
        if (pc >= end || (buffer[pc].opcode != _STORE_ATTR_INSTANCE_VALUE_NOESCAPE &&
                          buffer[pc].opcode != _STORE_ATTR_SLOT_NOESCAPE) ||
            buffer[pc].operand0 > UINT16_MAX || buffer[pc].operand1 == 0 ||
            buffer[pc].operand1 > UINT32_MAX)
        {
            continue;
        }
        bool managed = buffer[pc].opcode == _STORE_ATTR_INSTANCE_VALUE_NOESCAPE;
        uint64_t layout = local | (buffer[pc].operand0 << 8) |
            (buffer[pc].operand1 << 24) | ((uint64_t)managed << 56);
        pc = region_skip(buffer, pc + 1, end);
        if (pc >= end || (buffer[pc].opcode != _POP_TOP_NOP &&
                         buffer[pc].opcode != _POP_TOP &&
                         buffer[pc].opcode != _POP_TOP_SHARED))
        {
            continue;
        }
        buffer[start].opcode = _STORE_CONST_ATTRIBUTE;
        buffer[start].oparg = guards;
        buffer[start].operand0 = layout;
        buffer[start].operand1 = (uintptr_t)constant;
        for (int i = start + 1; i <= pc; i++) {
            buffer[i].opcode = _NOP;
        }
        start = pc;
    }
}
