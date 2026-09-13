/* Bounded, opt-in straight-line lowering before abstract interpretation.
 * All exits retain the entry stack. Only local reads and the explicitly
 * recognized arithmetic/call cleanup may be removed. No stores, calls,
 * periodic checks, or frame transitions may occur inside a region. */

static bool
region_enabled(const char *name)
{
#if (defined(__GNUC__) || defined(__clang__)) && \
    !defined(Py_GIL_DISABLED) && SIZEOF_VOID_P == 8
    const char *value = Py_GETENV(name);
    return value != NULL && strcmp(value, "1") == 0;
#else
    return false;
#endif
}

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
    if (pc + 4 >= end || buffer[pc].opcode != _GUARD_TOS_INT ||
        buffer[pc + 1].opcode != _GUARD_NOS_INT ||
        buffer[pc + 3].opcode != _POP_TOP_INT ||
        buffer[pc + 4].opcode != _POP_TOP_INT) {
        return -1;
    }
    int op = compare ? (buffer[pc + 2].opcode == _COMPARE_OP_INT
                        ? buffer[pc + 2].oparg & 15 : -1)
                     : region_arithmetic(buffer[pc + 2].opcode);
    if (op < 0) {
        return -1;
    }
    *operation = op;
    return pc + 5;
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
#define REGION_VALUE_MAX (INT64_MAX >> Py_TAGGED_SHIFT)
#define REGION_VALUE_MIN (-REGION_VALUE_MAX - 1)
#define REGION_MAX_OPS 8
#define REGION_MAX_STACK 4
#define REGION_MAX_TRACE 128

typedef struct {
    int64_t low;
    int64_t high;
} RegionBounds;

static bool
region_bounds(RegionBounds a, RegionBounds b, int operation, RegionBounds *out)
{
#if defined(__GNUC__) || defined(__clang__)
    int64_t values[4];
    if (operation == 0) {
        if (__builtin_add_overflow(a.low, b.low, &out->low) ||
            __builtin_add_overflow(a.high, b.high, &out->high)) {
            return false;
        }
    }
    else if (operation == 1) {
        if (__builtin_sub_overflow(a.low, b.high, &out->low) ||
            __builtin_sub_overflow(a.high, b.low, &out->high)) {
            return false;
        }
    }
    else if (operation == 2) {
        if (__builtin_mul_overflow(a.low, b.low, &values[0]) ||
            __builtin_mul_overflow(a.low, b.high, &values[1]) ||
            __builtin_mul_overflow(a.high, b.low, &values[2]) ||
            __builtin_mul_overflow(a.high, b.high, &values[3])) {
            return false;
        }
        out->low = out->high = values[0];
        for (int i = 1; i < 4; i++) {
            out->low = Py_MIN(out->low, values[i]);
            out->high = Py_MAX(out->high, values[i]);
        }
    }
    else {
        assert(operation == 3);
        if (b.low != b.high || b.low == 0) {
            return false;
        }
        int64_t divisor = b.low;
        int64_t low = divisor > 0 ? a.low : a.high;
        int64_t high = divisor > 0 ? a.high : a.low;
        /* Inputs are strictly inside int64, including for divisor -1. */
        out->low = low / divisor - ((low % divisor != 0) &&
                                    ((low < 0) != (divisor < 0)));
        out->high = high / divisor - ((high % divisor != 0) &&
                                      ((high < 0) != (divisor < 0)));
    }
    return out->low >= REGION_VALUE_MIN && out->high <= REGION_VALUE_MAX;
#else
    return false;
#endif
}

static void
lower_bounded_int_regions(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BOUNDED_INT_REGIONS")) {
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

static void
lower_int_regions(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_INT_REGIONS")) {
        return;
    }
    const char *range_mode = Py_GETENV("PYTHON_TIER3_JIT");
    if (range_mode != NULL &&
        (strcmp(range_mode, "1") == 0 || strcmp(range_mode, "2") == 0 ||
         strcmp(range_mode, "3") == 0 || strcmp(range_mode, "native") == 0 ||
         strcmp(range_mode, "resident") == 0)) {
        /* The optional whole-range pass runs after abstract interpretation.
         * Preserve its input when both experiments are requested. */
        for (int i = 0; i < length; i++) {
            if (buffer[i].opcode == _ITER_CHECK_RANGE) {
                return;
            }
        }
    }
    for (int pc = 0; pc < length; pc++) {
        if (buffer[pc].opcode != _GUARD_TOS_INT) {
            continue;
        }
        /* Two arithmetic operations, at most four live-ins, one live-out.
         * Bound scanning too, independently of the overall trace limit. */
        int end = Py_MIN(length, pc + 32);
        int first, second, local, limit, comparison;
        int next = region_int_operation(buffer, pc, end, false, &first);
        if (next < 0 ||
            (next = region_local(buffer, next, end, &local)) < 0 ||
            (next = region_int_operation(buffer, next, end, false, &second)) < 0) {
            continue;
        }
        int opcode = _INT_REGION;
        uint64_t config = local;
        int compare = region_local(buffer, next, end, &limit);
        if (compare >= 0 &&
            (compare = region_int_operation(buffer, compare, end, true,
                                            &comparison)) >= 0) {
            opcode = _INT_REGION_COMPARE;
            config |= (uint64_t)limit << 16 | (uint64_t)comparison << 32;
            next = compare;
        }
        buffer[pc].opcode = opcode;
        buffer[pc].oparg = first + second * 3;
        buffer[pc].operand0 = config;
        for (int i = pc + 1; i < next - 2; i++) {
            buffer[i].opcode = _NOP;
        }
        /* The two original live-in refs are closed after the fused result.
         * Local live-ins are read in place, never pushed or transferred. */
        pc = next - 1;
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
    return stop;
}

static void
lower_len_regions(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
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
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
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
