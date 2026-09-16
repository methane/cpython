#include "Python.h"

#ifdef _Py_TIER2

#include "opcode.h"
#include "pycore_interp.h"
#include "pycore_backoff.h"
#include "pycore_bitutils.h"        // _Py_popcount32()
#include "pycore_ceval.h"       // _Py_set_eval_breaker_bit
#include "pycore_code.h"            // _Py_GetBaseCodeUnit
#include "pycore_function.h"        // _PyFunction_Vectorcall()
#include "pycore_interpframe.h"
#include "pycore_object.h"          // _PyObject_GC_UNTRACK()
#include "pycore_opcode_metadata.h" // _PyOpcode_OpName[]
#include "pycore_opcode_utils.h"  // MAX_REAL_OPCODE
#include "pycore_optimizer.h"     // _Py_uop_analyze_and_optimize()
#include "pycore_pystate.h"       // _PyInterpreterState_GET()
#include "pycore_tuple.h"         // _PyTuple_FromArraySteal
#include "pycore_unicodeobject.h" // _PyUnicode_FromASCII
#include "pycore_uop_ids.h"
#include "pycore_jit.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#define NEED_OPCODE_METADATA
#include "pycore_uop_metadata.h" // Uop tables
#undef NEED_OPCODE_METADATA

#define MAX_EXECUTORS_SIZE 256
#define METHOD_INLINE_MAX_CODE_SIZE 128

// Trace too short, no progress:
// _START_EXECUTOR
// _MAKE_WARM
// _CHECK_VALIDITY
// _SET_IP
// is 4-5 instructions.
#define CODE_SIZE_NO_PROGRESS 5
// We start with _START_EXECUTOR, _MAKE_WARM
#define CODE_SIZE_EMPTY 2

#define _PyExecutorObject_CAST(op)  ((_PyExecutorObject *)(op))

int
_PyJit_IsOnlyStrongReferenceBesidesTracer(PyThreadState *tstate, PyObject *obj)
{
#ifdef Py_GIL_DISABLED
    _PyJitTracerState *tracer =
        ((_PyThreadStateImpl *)tstate)->jit_tracer_state;
    if (tracer == NULL || !tracer->is_tracing ||
        !_Py_IsOwnedByCurrentThread(obj) ||
        _Py_atomic_load_ssize_relaxed(&obj->ob_ref_shared) != 0)
    {
        return 0;
    }

    Py_ssize_t tracer_refs = 0;
    for (int i = 0; i < tracer->prev_state.recorded_count; i++) {
        tracer_refs += tracer->prev_state.recorded_values[i] == obj;
    }
    for (_PyUOpInstruction *inst = tracer->code_buffer.start;
         inst < tracer->code_buffer.next;
         inst++)
    {
        if ((_PyUop_Flags[inst->opcode] & HAS_RECORDS_VALUE_FLAG) &&
            (PyObject *)(uintptr_t)inst->operand0 == obj)
        {
            tracer_refs++;
        }
    }
    return tracer_refs > 0 &&
        _Py_atomic_load_uint32_relaxed(&obj->ob_ref_local) == tracer_refs + 1;
#else
    return 0;
#endif
}

static bool
has_space_for_executor(PyCodeObject *code, _Py_CODEUNIT *instr)
{
    if (code == (PyCodeObject *)&_Py_InitCleanup) {
        return false;
    }
    if (instr->op.code == ENTER_EXECUTOR) {
        return true;
    }
    if (code->co_executors == NULL) {
        return true;
    }
    return code->co_executors->size < MAX_EXECUTORS_SIZE;
}

static int32_t
get_index_for_executor(PyCodeObject *code, _Py_CODEUNIT *instr)
{
    if (instr->op.code == ENTER_EXECUTOR) {
        return instr->op.arg;
    }
    _PyExecutorArray *old = code->co_executors;
    int size = 0;
    int capacity = 0;
    if (old != NULL) {
        size = old->size;
        capacity = old->capacity;
        assert(size < MAX_EXECUTORS_SIZE);
    }
    assert(size <= capacity);
    if (size == capacity) {
        /* Array is full. Grow array */
        int new_capacity = capacity ? capacity * 2 : 4;
        _PyExecutorArray *new = PyMem_Realloc(
            old,
            offsetof(_PyExecutorArray, executors) +
            new_capacity * sizeof(_PyExecutorObject *));
        if (new == NULL) {
            return -1;
        }
        new->capacity = new_capacity;
        new->size = size;
        code->co_executors = new;
    }
    assert(size < code->co_executors->capacity);
    return size;
}

static void
insert_executor(PyCodeObject *code, _Py_CODEUNIT *instr, int index, _PyExecutorObject *executor)
{
    Py_INCREF(executor);
    if (instr->op.code == ENTER_EXECUTOR) {
        assert(index == instr->op.arg);
        _Py_ExecutorDetach(code->co_executors->executors[index]);
    }
    else {
        assert(code->co_executors->size == index);
        assert(code->co_executors->capacity > index);
        code->co_executors->size++;
    }
    executor->vm_data.opcode = instr->op.code;
    executor->vm_data.oparg = instr->op.arg;
    executor->vm_data.code = code;
    executor->vm_data.index = (int)(instr - _PyCode_CODE(code));
    code->co_executors->executors[index] = executor;
    assert(index < MAX_EXECUTORS_SIZE);
    instr->op.code = ENTER_EXECUTOR;
    instr->op.arg = index;
}
static _PyExecutorObject *
make_executor_from_uops(
    PyInterpreterState *interp,
    _PyUOpInstruction *buffer,
    int length,
    const _PyBloomFilter *dependencies,
    int chain_depth,
    bool is_method);

static int
uop_optimize(_PyInterpreterFrame *frame, PyThreadState *tstate,
             _PyExecutorObject **exec_ptr,
             bool progress_needed);

/* Returns 1 if optimized, 0 if not optimized, and -1 for an error.
 * If optimized, *executor_ptr contains a new reference to the executor
 */
// gh-137573: inlining this function causes stack overflows
Py_NO_INLINE int
_PyOptimizer_Optimize(
    _PyInterpreterFrame *frame, PyThreadState *tstate)
{
    _PyThreadStateImpl *_tstate = (_PyThreadStateImpl *)tstate;
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (!FT_ATOMIC_LOAD_UINT8(interp->jit)) {
        // gh-140936: It is possible that interp->jit will become false during
        // interpreter finalization. However, the specialized JUMP_BACKWARD_JIT
        // instruction may still be present. In this case, we should
        // return immediately without optimization.
        return 0;
    }
    _PyExecutorObject *prev_executor = _tstate->jit_tracer_state->initial_state.executor;
    if (prev_executor != NULL &&
        !FT_ATOMIC_LOAD_UINT8(prev_executor->vm_data.valid))
    {
        // gh-143604: If we are a side exit executor and the original executor is no
        // longer valid, don't compile to prevent a reference leak.
        return 0;
    }
    assert(!interp->compiling);
    assert(_tstate->jit_tracer_state->initial_state.stack_depth >= 0);
    assert(_tstate->jit_tracer_state->initial_state.func != NULL);
    interp->compiling = true;
    // The first executor in a chain and the MAX_CHAIN_DEPTH'th executor *must*
    // make progress in order to avoid infinite loops or excessively-long
    // side-exit chains. We can only insert the executor into the bytecode if
    // this is true, since a deopt won't infinitely re-enter the executor:
    int chain_depth = _tstate->jit_tracer_state->initial_state.chain_depth;
    chain_depth %= MAX_CHAIN_DEPTH;
    bool progress_needed = chain_depth == 0;
    PyCodeObject *code = (PyCodeObject *)_tstate->jit_tracer_state->initial_state.code;
    _Py_CODEUNIT *start = _tstate->jit_tracer_state->initial_state.start_instr;
    if (progress_needed && !has_space_for_executor(code, start)) {
        interp->compiling = false;
        return 0;
    }
    _PyExecutorObject *executor;
    int err = uop_optimize(frame, tstate, &executor, progress_needed);
    if (err <= 0) {
        interp->compiling = false;
        return err;
    }
    assert(executor != NULL);
    if (progress_needed) {
        int index = get_index_for_executor(code, start);
        if (index < 0) {
            /* Out of memory. Don't raise and assume that the
             * error will show up elsewhere.
             *
             * If an optimizer has already produced an executor,
             * it might get confused by the executor disappearing,
             * but there is not much we can do about that here. */
            Py_DECREF(executor);
            interp->compiling = false;
            return 0;
        }
        insert_executor(code, start, index, executor);
    }
    executor->vm_data.chain_depth = chain_depth;
    assert(FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid));
    _PyExitData *exit = _tstate->jit_tracer_state->initial_state.exit;
    if (exit != NULL && !progress_needed) {
        exit->executor = executor;
    }
    else {
        // An executor inserted into the code object now has a strong reference
        // to it from the code object. Thus, we don't need this reference anymore.
        Py_DECREF(executor);
    }
    interp->compiling = false;
    return 1;
}

static _PyExecutorObject *
get_executor_lock_held(PyCodeObject *code, int offset)
{
    int code_len = (int)Py_SIZE(code);
    for (int i = 0 ; i < code_len;) {
        if (_PyCode_CODE(code)[i].op.code == ENTER_EXECUTOR && i*2 == offset) {
            int oparg = _PyCode_CODE(code)[i].op.arg;
            _PyExecutorObject *res = code->co_executors->executors[oparg];
            Py_INCREF(res);
            return res;
        }
        i += _PyInstruction_GetLength(code, i);
    }
    PyErr_SetString(PyExc_ValueError, "no executor at given byte offset");
    return NULL;
}

_PyExecutorObject *
_Py_GetExecutor(PyCodeObject *code, int offset)
{
    _PyExecutorObject *executor;
    Py_BEGIN_CRITICAL_SECTION(code);
    executor = get_executor_lock_held(code, offset);
    Py_END_CRITICAL_SECTION();
    return executor;
}

static PyObject *
is_valid(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    return PyBool_FromLong(FT_ATOMIC_LOAD_UINT8(
        ((_PyExecutorObject *)self)->vm_data.valid));
}

static PyObject *
get_opcode(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    return PyLong_FromUnsignedLong(((_PyExecutorObject *)self)->vm_data.opcode);
}

static PyObject *
get_oparg(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    return PyLong_FromUnsignedLong(((_PyExecutorObject *)self)->vm_data.oparg);
}

///////////////////// Experimental UOp Optimizer /////////////////////

static int executor_clear(PyObject *executor);

void
_PyExecutor_Free(_PyExecutorObject *self)
{
#ifdef _Py_JIT
    _PyJIT_Free(self);
#endif
    PyObject_GC_Del(self);
}

static void executor_invalidate(PyObject *op);

static void
executor_clear_exits(_PyExecutorObject *executor)
{
    _PyExecutorObject *cold = _PyExecutor_GetColdExecutor();
    _PyExecutorObject *cold_dynamic = _PyExecutor_GetColdDynamicExecutor();
    for (uint32_t i = 0; i < executor->exit_count; i++) {
        _PyExitData *exit = &executor->exits[i];
        exit->temperature = initial_unreachable_backoff_counter();
        _PyExecutorObject *old = executor->exits[i].executor;
        exit->executor = exit->is_dynamic ? cold_dynamic : cold;
        Py_DECREF(old);
    }
}


void
_Py_ClearExecutorDeletionList(PyInterpreterState *interp)
{
    if (interp->executor_deletion_list_head == NULL) {
        return;
    }
    _PyRuntimeState *runtime = &_PyRuntime;
    HEAD_LOCK(runtime);
    PyThreadState* ts = PyInterpreterState_ThreadHead(interp);
    while (ts) {
        _PyExecutorObject *current = (_PyExecutorObject *)ts->current_executor;
        Py_XINCREF(current);
        ts = ts->next;
    }
    HEAD_UNLOCK(runtime);
    _PyExecutorObject *keep_list = NULL;
    do {
        _PyExecutorObject *exec = interp->executor_deletion_list_head;
        interp->executor_deletion_list_head = exec->vm_data.links.next;
        if (Py_REFCNT(exec) == 0) {
            _PyExecutor_Free(exec);
        } else {
            exec->vm_data.links.next = keep_list;
            keep_list = exec;
        }
    } while (interp->executor_deletion_list_head != NULL);
    interp->executor_deletion_list_head = keep_list;
    HEAD_LOCK(runtime);
    ts = PyInterpreterState_ThreadHead(interp);
    while (ts) {
        _PyExecutorObject *current = (_PyExecutorObject *)ts->current_executor;
        if (current != NULL) {
            Py_DECREF((PyObject *)current);
        }
        ts = ts->next;
    }
    HEAD_UNLOCK(runtime);
}

static void
add_to_pending_deletion_list(_PyExecutorObject *self)
{
    if (self->vm_data.pending_deletion) {
        return;
    }
    self->vm_data.pending_deletion = 1;
    PyInterpreterState *interp = PyInterpreterState_Get();
    self->vm_data.links.previous = NULL;
    self->vm_data.links.next = interp->executor_deletion_list_head;
    interp->executor_deletion_list_head = self;
}

static void
uop_dealloc(PyObject *op) {
    _PyExecutorObject *self = _PyExecutorObject_CAST(op);
    executor_invalidate(op);
    assert(self->vm_data.code == NULL);
    add_to_pending_deletion_list(self);
}

const char *
_PyUOpName(int index)
{
    if (index < 0 || index > MAX_UOP_REGS_ID) {
        return NULL;
    }
    return _PyOpcode_uop_name[index];
}

#ifdef Py_DEBUG
void
_PyUOpPrint(const _PyUOpInstruction *uop)
{
    const char *name = _PyUOpName(uop->opcode);
    if (name == NULL) {
        printf("<uop %d>", uop->opcode);
    }
    else {
        printf("%s", name);
    }
    switch(uop->format) {
        case UOP_FORMAT_TARGET:
            printf(" (%d, target=%d, operand0=%#" PRIx64 ", operand1=%#" PRIx64,
                uop->oparg,
                uop->target,
                (uint64_t)uop->operand0,
                (uint64_t)uop->operand1);
            break;
        case UOP_FORMAT_JUMP:
            printf(" (%d, jump_target=%d, operand0=%#" PRIx64 ", operand1=%#" PRIx64,
                uop->oparg,
                uop->jump_target,
                (uint64_t)uop->operand0,
                (uint64_t)uop->operand1);
            break;
        default:
            printf(" (%d, Unknown format)", uop->oparg);
    }
    if (_PyUop_Flags[_PyUop_Uncached[uop->opcode]] & HAS_ERROR_FLAG) {
        printf(", error_target=%d", uop->error_target);
    }

    printf(")");
}
#endif

static Py_ssize_t
uop_len(PyObject *op)
{
    _PyExecutorObject *self = _PyExecutorObject_CAST(op);
    return self->code_size;
}

static PyObject *
uop_item(PyObject *op, Py_ssize_t index)
{
    _PyExecutorObject *self = _PyExecutorObject_CAST(op);
    Py_ssize_t len = uop_len(op);
    if (index < 0 || index >= len) {
        PyErr_SetNone(PyExc_IndexError);
        return NULL;
    }
    int opcode = self->trace[index].opcode;
    int base_opcode = _PyUop_Uncached[opcode];
    const char *name = _PyUOpName(base_opcode);
    if (name == NULL) {
        name = "<nil>";
    }
    PyObject *oname = _PyUnicode_FromASCII(name, strlen(name));
    if (oname == NULL) {
        return NULL;
    }
    PyObject *oparg = PyLong_FromUnsignedLong(self->trace[index].oparg);
    if (oparg == NULL) {
        Py_DECREF(oname);
        return NULL;
    }
    PyObject *target = PyLong_FromUnsignedLong(self->trace[index].target);
    if (target == NULL) {
        Py_DECREF(oparg);
        Py_DECREF(oname);
        return NULL;
    }
    PyObject *operand = PyLong_FromUnsignedLongLong(self->trace[index].operand0);
    if (operand == NULL) {
        Py_DECREF(target);
        Py_DECREF(oparg);
        Py_DECREF(oname);
        return NULL;
    }
    PyObject *args[4] = { oname, oparg, target, operand };
    return _PyTuple_FromArraySteal(args, 4);
}

PySequenceMethods uop_as_sequence = {
    .sq_length = uop_len,
    .sq_item = uop_item,
};

static int
executor_traverse(PyObject *o, visitproc visit, void *arg)
{
    _PyExecutorObject *executor = _PyExecutorObject_CAST(o);
    for (uint32_t i = 0; i < executor->exit_count; i++) {
        Py_VISIT(executor->exits[i].executor);
    }
    return 0;
}

static PyObject *
get_jit_code(PyObject *self, PyObject *Py_UNUSED(ignored))
{
#ifndef _Py_JIT
    PyErr_SetString(PyExc_RuntimeError, "JIT support not enabled.");
    return NULL;
#else
    _PyExecutorObject *executor = _PyExecutorObject_CAST(self);
    if (executor->jit_code == NULL || executor->jit_size == 0) {
        Py_RETURN_NONE;
    }
    return PyBytes_FromStringAndSize(executor->jit_code, executor->jit_size);
#endif
}

static PyMethodDef uop_executor_methods[] = {
    { "is_valid", is_valid, METH_NOARGS, NULL },
    { "get_jit_code", get_jit_code, METH_NOARGS, NULL},
    { "get_opcode", get_opcode, METH_NOARGS, NULL },
    { "get_oparg", get_oparg, METH_NOARGS, NULL },
    { NULL, NULL },
};

static int
executor_is_gc(PyObject *o)
{
#ifdef Py_GIL_DISABLED
    return 1;
#else
    return !_Py_IsImmortal(o);
#endif
}

PyTypeObject _PyUOpExecutor_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    .tp_name = "uop_executor",
    .tp_basicsize = offsetof(_PyExecutorObject, exits),
    .tp_itemsize = 1,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION | Py_TPFLAGS_HAVE_GC,
    .tp_dealloc = uop_dealloc,
    .tp_as_sequence = &uop_as_sequence,
    .tp_methods = uop_executor_methods,
    .tp_traverse = executor_traverse,
    .tp_clear = executor_clear,
    .tp_is_gc = executor_is_gc,
};

/* TO DO -- Generate these tables */
static const uint16_t
_PyUOp_Replacements[MAX_UOP_ID + 1] = {
    [_ITER_JUMP_RANGE] = _GUARD_NOT_EXHAUSTED_RANGE,
    [_ITER_JUMP_LIST] = _GUARD_NOT_EXHAUSTED_LIST,
    [_ITER_JUMP_TUPLE] = _GUARD_NOT_EXHAUSTED_TUPLE,
    [_FOR_ITER] = _FOR_ITER_TIER_TWO,
    [_FOR_ITER_VIRTUAL] = _FOR_ITER_VIRTUAL_TIER_TWO,
    [_ITER_NEXT_LIST] = _ITER_NEXT_LIST_TIER_TWO,
    [_CHECK_PERIODIC_AT_END] = _TIER2_RESUME_CHECK,
    [_LOAD_BYTECODE] = _NOP,
    [_SEND_VIRTUAL] = _SEND_VIRTUAL_TIER_TWO,
    [_SEND_ASYNC_GEN] = _SEND_ASYNC_GEN_TIER_TWO,
};

static const uint8_t
is_for_iter_test[MAX_UOP_ID + 1] = {
    [_GUARD_NOT_EXHAUSTED_RANGE] = 1,
    [_GUARD_NOT_EXHAUSTED_LIST] = 1,
    [_GUARD_NOT_EXHAUSTED_TUPLE] = 1,
    [_FOR_ITER_TIER_TWO] = 1,
    [_ITER_NEXT_INLINE] = 1,
};

static const uint16_t
BRANCH_TO_GUARD[4][2] = {
    [POP_JUMP_IF_FALSE - POP_JUMP_IF_FALSE][0] = _GUARD_IS_TRUE_POP,
    [POP_JUMP_IF_FALSE - POP_JUMP_IF_FALSE][1] = _GUARD_IS_FALSE_POP,
    [POP_JUMP_IF_TRUE - POP_JUMP_IF_FALSE][0] = _GUARD_IS_FALSE_POP,
    [POP_JUMP_IF_TRUE - POP_JUMP_IF_FALSE][1] = _GUARD_IS_TRUE_POP,
    [POP_JUMP_IF_NONE - POP_JUMP_IF_FALSE][0] = _GUARD_IS_NOT_NONE_POP,
    [POP_JUMP_IF_NONE - POP_JUMP_IF_FALSE][1] = _GUARD_IS_NONE_POP,
    [POP_JUMP_IF_NOT_NONE - POP_JUMP_IF_FALSE][0] = _GUARD_IS_NONE_POP,
    [POP_JUMP_IF_NOT_NONE - POP_JUMP_IF_FALSE][1] = _GUARD_IS_NOT_NONE_POP,
};

static const uint16_t
guard_ip_uop[MAX_UOP_ID + 1] = {
    [_PUSH_FRAME] = _GUARD_IP__PUSH_FRAME,
    [_RETURN_GENERATOR] = _GUARD_IP_RETURN_GENERATOR,
    [_RETURN_VALUE] = _GUARD_IP_RETURN_VALUE,
    [_YIELD_VALUE] = _GUARD_IP_YIELD_VALUE,
};

static const uint16_t
guard_code_version_uop[MAX_UOP_ID + 1] = {
    [_PUSH_FRAME] = _GUARD_CODE_VERSION__PUSH_FRAME,
    [_RETURN_GENERATOR] = _GUARD_CODE_VERSION_RETURN_GENERATOR,
    [_RETURN_VALUE] = _GUARD_CODE_VERSION_RETURN_VALUE,
    [_YIELD_VALUE] = _GUARD_CODE_VERSION_YIELD_VALUE,
};

static const uint16_t
dynamic_exit_uop[MAX_UOP_ID + 1] = {
    [_GUARD_IP__PUSH_FRAME] = 1,
    [_GUARD_IP_RETURN_GENERATOR] = 1,
    [_GUARD_IP_RETURN_VALUE] = 1,
    [_GUARD_IP_YIELD_VALUE] = 1,
    [_GUARD_CODE_VERSION__PUSH_FRAME] = 1,
    [_GUARD_CODE_VERSION_RETURN_GENERATOR] = 1,
    [_GUARD_CODE_VERSION_RETURN_VALUE] = 1,
    [_GUARD_CODE_VERSION_YIELD_VALUE] = 1,
};



#ifdef Py_DEBUG
#define DPRINTF(level, ...) \
    if (lltrace >= (level)) { printf(__VA_ARGS__); }
#else
#define DPRINTF(level, ...)
#endif


static inline void
add_to_trace(
    _PyJitTracerState *tracer,
    uint16_t opcode,
    uint16_t oparg,
    uint64_t operand,
    uint32_t target)
{
    _PyJitUopBuffer *trace = &tracer->code_buffer;
    _PyUOpInstruction *inst = trace->next;
    inst->opcode = opcode;
    inst->format = UOP_FORMAT_TARGET;
    inst->target = target;
    inst->oparg = oparg;
    inst->operand0 = operand;
#ifdef Py_STATS
    inst->execution_count = 0;
    inst->fitness = tracer->translator_state.fitness;
#endif
    trace->next++;
}


#ifdef Py_DEBUG
#define ADD_TO_TRACE(OPCODE, OPARG, OPERAND, TARGET) \
    add_to_trace(tracer, (OPCODE), (OPARG), (OPERAND), (TARGET)); \
    if (lltrace >= 2) { \
        printf("%4d ADD_TO_TRACE: ", uop_buffer_length(trace)); \
        _PyUOpPrint(uop_buffer_last(trace)); \
        printf("\n"); \
    }
#else
#define ADD_TO_TRACE(OPCODE, OPARG, OPERAND, TARGET) \
    add_to_trace(tracer, (OPCODE), (OPARG), (OPERAND), (TARGET))
#endif

#define INSTR_IP(INSTR, CODE) \
    ((uint32_t)((INSTR) - ((_Py_CODEUNIT *)(CODE)->co_code_adaptive)))


/* Branch penalty: 0 for a fully biased branch and FITNESS_BRANCH_BALANCED for
 * a balanced or fully off-trace branch. This keeps any single branch from
 * consuming more than one balanced-branch cost.
 */
static inline int
compute_branch_penalty(uint16_t history)
{
    bool branch_taken = history & 1;
    int taken_count = _Py_popcount32((uint32_t)history);
    int on_trace_count = branch_taken ? taken_count : 16 - taken_count;
    int off_trace = 16 - on_trace_count;
    int penalty = off_trace * FITNESS_BRANCH_BALANCED / 8;
    if (penalty > FITNESS_BRANCH_BALANCED) {
        penalty = FITNESS_BRANCH_BALANCED;
    }
    return penalty;
}

/* Compute exit quality for the current trace position.
 * Higher values mean better places to stop the trace. */
static inline int32_t
compute_exit_quality(_Py_CODEUNIT *target_instr, int opcode,
                     const _PyJitTracerState *tracer)
{
    if (target_instr == tracer->initial_state.close_loop_instr) {
        return EXIT_QUALITY_CLOSE_LOOP;
    }
    else if (target_instr->op.code == ENTER_EXECUTOR) {
        return EXIT_QUALITY_ENTER_EXECUTOR;
    }
    else if (opcode == JUMP_BACKWARD_JIT ||
        opcode == JUMP_BACKWARD ||
        opcode == JUMP_BACKWARD_NO_INTERRUPT) {
        return EXIT_QUALITY_BACKWARD_EDGE;
    }
    else if (_PyOpcode_Caches[_PyOpcode_Deopt[opcode]] > 0) {
        return EXIT_QUALITY_SPECIALIZABLE;
    }
    return EXIT_QUALITY_DEFAULT;
}

/* Frame penalty: (MAX_ABSTRACT_FRAME_DEPTH-1) pushes exhaust fitness. */
static inline int32_t
compute_frame_penalty(uint16_t fitness_initial)
{
    return (int32_t)fitness_initial / (MAX_ABSTRACT_FRAME_DEPTH - 1) + 1;
}

static int
is_terminator(const _PyUOpInstruction *uop)
{
    int opcode = _PyUop_Uncached[uop->opcode];
    return (
        opcode == _EXIT_TRACE ||
        opcode == _DEOPT ||
        opcode == _JUMP_TO_TOP ||
        opcode == _DYNAMIC_EXIT
    );
}

/* Returns 1 on success (added to trace), 0 on trace end.
 */
// gh-142543: inlining this function causes stack overflows
Py_NO_INLINE int
_PyJit_translate_single_bytecode_to_trace(
    PyThreadState *tstate,
    _PyInterpreterFrame *frame,
    _Py_CODEUNIT *next_instr,
    int stop_tracing_opcode)
{

#ifdef Py_DEBUG
    char *python_lltrace = Py_GETENV("PYTHON_LLTRACE");
    int lltrace = 0;
    if (python_lltrace != NULL && *python_lltrace >= '0') {
        lltrace = *python_lltrace - '0';  // TODO: Parse an int and all that
    }
#endif
    _PyThreadStateImpl *_tstate = (_PyThreadStateImpl *)tstate;
    _PyJitTracerState *tracer = _tstate->jit_tracer_state;
    PyCodeObject *old_code = tracer->prev_state.instr_code;
    bool progress_needed = (tracer->initial_state.chain_depth % MAX_CHAIN_DEPTH) == 0;
    _PyJitUopBuffer *trace = &tracer->code_buffer;

    _Py_CODEUNIT *this_instr =  tracer->prev_state.instr;
    _Py_CODEUNIT *target_instr = this_instr;
    uint32_t target = 0;

    target = Py_IsNone((PyObject *)old_code)
        ? (uint32_t)(target_instr - _Py_INTERPRETER_TRAMPOLINE_INSTRUCTIONS_PTR)
        : INSTR_IP(target_instr, old_code);

    // Rewind EXTENDED_ARG so that we see the whole thing.
    // We must point to the first EXTENDED_ARG when deopting.
    int oparg = tracer->prev_state.instr_oparg;
    int opcode = this_instr->op.code;
    int rewind_oparg = oparg;
    while (rewind_oparg > 255) {
        rewind_oparg >>= 8;
        target--;
    }

    if (opcode == ENTER_EXECUTOR) {
        _PyExecutorObject *executor = old_code->co_executors->executors[oparg & 255];
        opcode = executor->vm_data.opcode;
        oparg = (oparg & ~255) | executor->vm_data.oparg;
    }

    if (_PyOpcode_Caches[_PyOpcode_Deopt[opcode]] > 0) {
        uint16_t backoff = (this_instr + 1)->counter.value_and_backoff;
        // adaptive_counter_cooldown is a fresh specialization.
        // trigger_backoff_counter is what we set during tracing.
        // All tracing backoffs should be freshly specialized or untouched.
        // If not, that indicates a deopt during tracing, and
        // thus the "actual" instruction executed is not the one that is
        // in the instruction stream, but rather the deopt.
        // It's important we check for this, as some specializations might make
        // no progress (they can immediately deopt after specializing).
        // We do this to improve performance, as otherwise a compiled trace
        // will just deopt immediately.
        if (backoff != adaptive_counter_cooldown().value_and_backoff &&
            backoff != trigger_backoff_counter().value_and_backoff) {
            OPT_STAT_INC(trace_immediately_deopts);
            opcode = _PyOpcode_Deopt[opcode];
        }
    }

    // Strange control-flow
    bool has_dynamic_jump_taken = OPCODE_HAS_UNPREDICTABLE_JUMP(opcode) &&
        (next_instr != this_instr + 1 + _PyOpcode_Caches[_PyOpcode_Deopt[opcode]]);

    /* Special case the first instruction,
    * so that we can guarantee forward progress */
    if (progress_needed && uop_buffer_length(&tracer->code_buffer) < CODE_SIZE_NO_PROGRESS) {
        if (OPCODE_HAS_EXIT(opcode) || OPCODE_HAS_DEOPT(opcode)) {
            opcode = _PyOpcode_Deopt[opcode];
        }
        assert(!OPCODE_HAS_EXIT(opcode));
        assert(!OPCODE_HAS_DEOPT(opcode));
    }

    bool needs_guard_ip = OPCODE_HAS_NEEDS_GUARD_IP(opcode);
    if (has_dynamic_jump_taken && !needs_guard_ip) {
        DPRINTF(2, "Unsupported: dynamic jump taken %s\n", _PyOpcode_OpName[opcode]);
        goto unsupported;
    }

    int is_sys_tracing = (tstate->c_tracefunc != NULL) || (tstate->c_profilefunc != NULL);
    if (is_sys_tracing) {
        goto done;
    }

    if (stop_tracing_opcode == _DEOPT) {
        // gh-143183: It's important we rewind to the last known proper target.
        // The current target might be garbage as stop tracing usually indicates
        // we are in something that we can't trace.
        DPRINTF(2, "Told to stop tracing\n");
        goto unsupported;
    }
    else if (stop_tracing_opcode != 0) {
        assert(stop_tracing_opcode == _EXIT_TRACE);
        ADD_TO_TRACE(stop_tracing_opcode, 0, 0, target);
        goto done;
    }

    DPRINTF(2, "%p %d: %s(%d) %d\n", old_code, target, _PyOpcode_OpName[opcode], oparg, needs_guard_ip);

#ifdef Py_DEBUG
    if (oparg > 255) {
        assert(_Py_GetBaseCodeUnit(old_code, target).op.code == EXTENDED_ARG);
    }
#endif

    // This happens when a recursive call happens that we can't trace. Such as Python -> C -> Python calls
    // If we haven't guarded the IP, then it's untraceable.
    if (frame != tracer->prev_state.instr_frame && !needs_guard_ip) {
        DPRINTF(2, "Unsupported: unguardable jump taken\n");
        goto unsupported;
    }

    if (oparg > 0xFFFF) {
        DPRINTF(2, "Unsupported: oparg too large\n");
        unsupported:
        {
            _PyUOpInstruction *curr = uop_buffer_last(trace);
            while (curr->opcode != _SET_IP && uop_buffer_length(trace) > 2) {
                trace->next--;
                curr = uop_buffer_last(trace);
            }
            if (curr->opcode == _SET_IP) {
                int32_t old_target = (int32_t)uop_get_target(curr);
                curr->opcode = _DEOPT;
                curr->format = UOP_FORMAT_TARGET;
                curr->target = old_target;
            }
            goto done;
        }
    }

    if (opcode == NOP) {
        return 1;
    }

    if (opcode == JUMP_FORWARD) {
        return 1;
    }

    if (opcode == EXTENDED_ARG) {
        return 1;
    }

    // Stop the trace if fitness has dropped below the exit quality threshold.
    _PyJitTracerTranslatorState *ts = &tracer->translator_state;
    int32_t eq = compute_exit_quality(target_instr, opcode, tracer);
    DPRINTF(3, "Fitness check: %s(%d) fitness=%d, exit_quality=%d, depth=%d\n",
            _PyOpcode_OpName[opcode], oparg, ts->fitness, eq, ts->frame_depth);

    if (ts->fitness < eq) {
        // Heuristic exit: leave operand1=0 so the side exit increments chain_depth.
        ADD_TO_TRACE(_EXIT_TRACE, 0, 0, target);
        OPT_STAT_INC(fitness_terminated_traces);
        DPRINTF(2, "Fitness terminated: %s(%d) fitness=%d < exit_quality=%d\n",
                _PyOpcode_OpName[opcode], oparg, ts->fitness, eq);
        goto done;
    }

    // Snapshot remaining space so the later fitness charge reflects all buffer
    // space this bytecode consumed, including reserved tail slots.
    int32_t remaining_before = uop_buffer_remaining_space(trace);

    // One for possible _DEOPT, one because _CHECK_VALIDITY itself might _DEOPT
    trace->end -= 2;

    const _PyOpcodeRecordSlotMap *record_slot_map = &_PyOpcode_RecordSlotMaps[opcode];

    assert(opcode != ENTER_EXECUTOR && opcode != EXTENDED_ARG);
    assert(!_PyErr_Occurred(tstate));


    if (OPCODE_HAS_EXIT(opcode)) {
        // Make space for side exit
        trace->end--;
    }
    if (OPCODE_HAS_ERROR(opcode)) {
        // Make space for error stub
        trace->end--;
    }
    if (OPCODE_HAS_DEOPT(opcode)) {
        // Make space for side exit
        trace->end--;
    }

    // _GUARD_IP leads to an exit.
    trace->end -= needs_guard_ip;

#if Py_DEBUG
    const struct opcode_macro_expansion *expansion = &_PyOpcode_macro_expansion[opcode];
    int space_needed = expansion->nuops + needs_guard_ip + 2 + (!OPCODE_HAS_NO_SAVE_IP(opcode));
    assert(uop_buffer_remaining_space(trace) > space_needed);
#endif

    ADD_TO_TRACE(_CHECK_VALIDITY, 0, 0, target);

    if (!OPCODE_HAS_NO_SAVE_IP(opcode)) {
        ADD_TO_TRACE(_SET_IP, 0, (uintptr_t)target_instr, target);
    }

    switch (opcode) {
        case POP_JUMP_IF_NONE:
        case POP_JUMP_IF_NOT_NONE:
        case POP_JUMP_IF_FALSE:
        case POP_JUMP_IF_TRUE:
        {
            _Py_CODEUNIT *computed_next_instr_without_modifiers = target_instr + 1 + _PyOpcode_Caches[_PyOpcode_Deopt[opcode]];
            _Py_CODEUNIT *computed_next_instr = computed_next_instr_without_modifiers + (computed_next_instr_without_modifiers->op.code == NOT_TAKEN);
            _Py_CODEUNIT *computed_jump_instr = computed_next_instr_without_modifiers + oparg;
            assert(next_instr == computed_next_instr || next_instr == computed_jump_instr);
            int jump_happened = target_instr[1].cache & 1;
            assert(jump_happened ? (next_instr == computed_jump_instr) : (next_instr == computed_next_instr));
            uint32_t uopcode = BRANCH_TO_GUARD[opcode - POP_JUMP_IF_FALSE][jump_happened];
            ADD_TO_TRACE(uopcode, 0, 0, INSTR_IP(jump_happened ? computed_next_instr : computed_jump_instr, old_code));
            int bp = compute_branch_penalty(target_instr[1].cache);
            tracer->translator_state.fitness -= bp;
            DPRINTF(3, "  branch penalty: -%d (history=0x%04x, taken=%d) -> fitness=%d\n",
                    bp, target_instr[1].cache, jump_happened,
                    tracer->translator_state.fitness);

            break;
        }
        case JUMP_BACKWARD_JIT:
            // This is possible as the JIT might have re-activated after it was disabled
        case JUMP_BACKWARD_NO_JIT:
        case JUMP_BACKWARD:
            ADD_TO_TRACE(_CHECK_PERIODIC, 0, 0, target);
            break;
        case JUMP_BACKWARD_NO_INTERRUPT:
            break;

        case RESUME:
        case RESUME_CHECK:
        case RESUME_CHECK_JIT:
            /* Use a special tier 2 version of RESUME_CHECK to allow traces to
             *  start with RESUME_CHECK */
            ADD_TO_TRACE(_TIER2_RESUME_CHECK, 0, 0, target);
            break;
        default:
        {
            const struct opcode_macro_expansion *expansion = &_PyOpcode_macro_expansion[opcode];
            // Reserve space for nuops (+ _SET_IP + _EXIT_TRACE)
            int nuops = expansion->nuops;
            if (nuops == 0) {
                DPRINTF(2, "Unsupported opcode %s\n", _PyOpcode_OpName[opcode]);
                goto unsupported;
            }
            assert(nuops > 0);
            uint32_t orig_oparg = oparg;  // For OPARG_TOP/BOTTOM
            uint32_t orig_target = target;
            int record_idx = 0;
            for (int i = 0; i < nuops; i++) {
                oparg = orig_oparg;
                target = orig_target;
                uint32_t uop = expansion->uops[i].uop;
                uint64_t operand = 0;
                // Add one to account for the actual opcode/oparg pair:
                int offset = expansion->uops[i].offset + 1;
                switch (expansion->uops[i].size) {
                    case OPARG_SIMPLE:
                        assert(opcode != _JUMP_BACKWARD_NO_INTERRUPT && opcode != JUMP_BACKWARD);
                        break;
                    case OPARG_CACHE_1:
                        operand = read_u16(&this_instr[offset].cache);
                        break;
                    case OPARG_CACHE_2:
                        operand = read_u32(&this_instr[offset].cache);
                        break;
                    case OPARG_CACHE_4:
                        operand = read_u64(&this_instr[offset].cache);
                        break;
                    case OPARG_TOP:  // First half of super-instr
                        assert(orig_oparg <= 255);
                        oparg = orig_oparg >> 4;
                        break;
                    case OPARG_BOTTOM:  // Second half of super-instr
                        assert(orig_oparg <= 255);
                        oparg = orig_oparg & 0xF;
                        break;
                    case OPARG_SAVE_RETURN_OFFSET:  // op=_SAVE_RETURN_OFFSET; oparg=return_offset
                        oparg = offset;
                        assert(uop == _SAVE_RETURN_OFFSET);
                        break;
                    case OPARG_REPLACED:
                        uop = _PyUOp_Replacements[uop];
                        assert(uop != 0);
                        uint32_t next_inst = target + 1 + _PyOpcode_Caches[_PyOpcode_Deopt[opcode]];
                        if (uop == _TIER2_RESUME_CHECK) {
                            if (this_instr[-1].op.code == LOAD_SPECIAL) {
                                // Don't check eval breaker immediately after LOAD_SPECIAL
                                uop = _NOP;
                            }
                            else {
                                target = next_inst;
                            }
                        }
                        else {
                            int extended_arg = orig_oparg > 255;
                            uint32_t jump_target = next_inst + orig_oparg + extended_arg;
                            /* Jump must be to an "END" either END_FOR or END_SEND */
                            assert((
                                    _Py_GetBaseCodeUnit(old_code, jump_target).op.code == END_FOR &&
                                    _Py_GetBaseCodeUnit(old_code, jump_target+1).op.code == POP_ITER
                                )
                                ||
                                _Py_GetBaseCodeUnit(old_code, jump_target).op.code == END_SEND
                            );
                            if (is_for_iter_test[uop]) {
                                target = jump_target + 1;
                            }
                        }
                        break;
                    case OPERAND1_1:
                        assert(uop_buffer_last(trace)->opcode == uop);
                        operand = read_u16(&this_instr[offset].cache);
                        uop_buffer_last(trace)->operand1 = operand;
                        continue;
                    case OPERAND1_2:
                        assert(uop_buffer_last(trace)->opcode == uop);
                        operand = read_u32(&this_instr[offset].cache);
                        uop_buffer_last(trace)->operand1 = operand;
                        continue;
                    case OPERAND1_4:
                        assert(uop_buffer_last(trace)->opcode == uop);
                        operand = read_u64(&this_instr[offset].cache);
                        uop_buffer_last(trace)->operand1 = operand;
                        continue;
                    default:
                        fprintf(stderr,
                                "opcode=%d, oparg=%d; nuops=%d, i=%d; size=%d, offset=%d\n",
                                opcode, oparg, nuops, i,
                                expansion->uops[i].size,
                                expansion->uops[i].offset);
                        Py_FatalError("garbled expansion");
                }
                if (uop == _BINARY_OP_INPLACE_ADD_UNICODE) {
                    assert(i + 1 == nuops);
                    _Py_CODEUNIT *next = target_instr + 1 + _PyOpcode_Caches[_PyOpcode_Deopt[opcode]];
                    assert(next->op.code == STORE_FAST);
                    operand = next->op.arg;
                }
                else if (uop == _PUSH_FRAME) {
                    _PyJitTracerTranslatorState *ts_depth = &tracer->translator_state;
                    ts_depth->frame_depth++;
                    assert(ts_depth->frame_depth < MAX_ABSTRACT_FRAME_DEPTH);
                    int32_t frame_penalty = compute_frame_penalty(tstate->interp->opt_config.fitness_initial);
                    ts_depth->fitness -= frame_penalty;
                    DPRINTF(3, "  _PUSH_FRAME: depth=%d, penalty=-%d -> fitness=%d\n",
                            ts_depth->frame_depth, frame_penalty,
                            ts_depth->fitness);
                }
                else if (uop == _RETURN_VALUE || uop == _RETURN_GENERATOR || uop == _YIELD_VALUE) {
                    _PyJitTracerTranslatorState *ts_depth = &tracer->translator_state;
                    int32_t frame_penalty = compute_frame_penalty(tstate->interp->opt_config.fitness_initial);
                    if (ts_depth->frame_depth <= 0) {
                        // Returning past the traced root is normal for guarded
                        // caller continuation. Charge a small penalty so these
                        // paths still terminate.
                        int32_t underflow_penalty = frame_penalty / 4;
                        ts_depth->fitness -= underflow_penalty;
                        DPRINTF(3, "  %s: underflow penalty=-%d -> fitness=%d\n",
                                _PyOpcode_uop_name[uop], underflow_penalty,
                                ts_depth->fitness);
                    }
                    else {
                        // Symmetric with push: net-zero frame impact.
                        ts_depth->fitness += frame_penalty;
                        ts_depth->frame_depth--;
                        DPRINTF(3, "  %s: return reward=+%d, depth=%d -> fitness=%d\n",
                                _PyOpcode_uop_name[uop], frame_penalty,
                                ts_depth->frame_depth,
                                ts_depth->fitness);
                    }
                }
                else if (_PyUop_Flags[uop] & HAS_RECORDS_VALUE_FLAG) {
                    assert(record_idx < record_slot_map->count);
                    uint8_t record_slot = record_slot_map->slots[record_idx];
                    assert(record_slot < tracer->prev_state.recorded_count);
                    PyObject *recorded_value = tracer->prev_state.recorded_values[record_slot];
                    tracer->prev_state.recorded_values[record_slot] = NULL;
                    if ((record_slot_map->transform_mask & (1u << record_idx)) &&
                        recorded_value != NULL) {
                        recorded_value = _PyOpcode_RecordTransformValue(uop, recorded_value);
                    }
                    record_idx++;
                    operand = (uintptr_t)recorded_value;
                }
                // All other instructions
                ADD_TO_TRACE(uop, oparg, operand, target);
            }
            break;
        }  // End default

    }  // End switch (opcode)

    if (needs_guard_ip) {
        int last_opcode = uop_buffer_last(trace)->opcode;
        uint16_t guard_ip = guard_ip_uop[last_opcode];
        if (guard_ip == 0) {
            DPRINTF(1, "Unknown uop needing guard ip %s\n", _PyOpcode_uop_name[last_opcode]);
            Py_UNREACHABLE();
        }
        PyObject *code = PyStackRef_AsPyObjectBorrow(frame->f_executable);
        Py_INCREF(code);
        ADD_TO_TRACE(_RECORD_CODE, 0, (uintptr_t)code, 0);
        ADD_TO_TRACE(guard_ip, 0, (uintptr_t)next_instr, 0);
        if (PyCode_Check(code)) {
            /* Record stack depth, in operand1 */
            int stack_depth = (int)(frame->stackpointer - _PyFrame_Stackbase(frame));
            uop_buffer_last(trace)->operand1 = stack_depth;
            ADD_TO_TRACE(guard_code_version_uop[last_opcode], 0, ((PyCodeObject *)code)->co_version, 0);
        }
    }
    // Loop back to the start
    int is_first_instr = tracer->initial_state.close_loop_instr == next_instr ||
        tracer->initial_state.start_instr == next_instr;
    if (is_first_instr && uop_buffer_length(trace) > CODE_SIZE_NO_PROGRESS) {
        if (needs_guard_ip) {
            ADD_TO_TRACE(_SET_IP, 0, (uintptr_t)next_instr, 0);
        }
        ADD_TO_TRACE(_JUMP_TO_TOP, 0, 0, 0);
        goto done;
    }
    // Charge fitness by trace-buffer capacity consumed for this bytecode,
    // including both emitted uops and tail reservations.
    {
        int32_t slots_used = remaining_before - uop_buffer_remaining_space(trace);
        tracer->translator_state.fitness -= slots_used;
        DPRINTF(3, "  per-insn cost: -%d -> fitness=%d\n", slots_used,
                tracer->translator_state.fitness);
    }
    DPRINTF(2, "Trace continuing (fitness=%d)\n", tracer->translator_state.fitness);
    return 1;
done:
    DPRINTF(2, "Trace done\n");
    if (!is_terminator(uop_buffer_last(trace))) {
        ADD_TO_TRACE(_EXIT_TRACE, 0, 0, target);
    }
    return 0;
}

// Returns 0 for do not enter tracing, 1 on enter tracing.
// gh-142543: inlining this function causes stack overflows
Py_NO_INLINE int
_PyJit_TryInitializeTracing(
    PyThreadState *tstate, _PyInterpreterFrame *frame, _Py_CODEUNIT *curr_instr,
    _Py_CODEUNIT *start_instr, _Py_CODEUNIT *close_loop_instr, _PyStackRef *stack_pointer, int chain_depth,
    _PyExitData *exit, int oparg, _PyExecutorObject *current_executor)
{
    _PyThreadStateImpl *_tstate = (_PyThreadStateImpl *)tstate;
    if (_tstate->jit_tracer_state == NULL) {
        _tstate->jit_tracer_state = (_PyJitTracerState *)_PyObject_VirtualAlloc(sizeof(_PyJitTracerState));
        if (_tstate->jit_tracer_state == NULL) {
            // Don't error, just go to next instruction.
            return 0;
        }
        _tstate->jit_tracer_state->is_tracing = false;
    }
    _PyJitTracerState *tracer = _tstate->jit_tracer_state;
    // A recursive trace.
    if (tracer->is_tracing) {
        return 0;
    }
    if (oparg > 0xFFFF) {
        return 0;
    }
    PyObject *func = PyStackRef_AsPyObjectBorrow(frame->f_funcobj);
    if (func == NULL || !PyFunction_Check(func)) {
        return 0;
    }
    PyCodeObject *code = _PyFrame_GetCode(frame);
#ifdef Py_DEBUG
    char *python_lltrace = Py_GETENV("PYTHON_LLTRACE");
    int lltrace = 0;
    if (python_lltrace != NULL && *python_lltrace >= '0') {
        lltrace = *python_lltrace - '0';  // TODO: Parse an int and all that
    }
    DPRINTF(2,
        "Tracing %s (%s:%d) at byte offset %d at chain depth %d\n",
        PyUnicode_AsUTF8(code->co_qualname),
        PyUnicode_AsUTF8(code->co_filename),
        code->co_firstlineno,
        2 * INSTR_IP(close_loop_instr, code),
        chain_depth);
#endif
    /* Set up tracing buffer*/
    _PyJitUopBuffer *trace = &tracer->code_buffer;
    uop_buffer_init(trace, &tracer->uop_array[0], UOP_MAX_TRACE_LENGTH);
    _PyJitTracerTranslatorState *ts = &tracer->translator_state;
    ts->fitness = tstate->interp->opt_config.fitness_initial;
    ts->frame_depth = 0;
    ADD_TO_TRACE(_START_EXECUTOR, 0, (uintptr_t)start_instr, INSTR_IP(start_instr, code));
    ADD_TO_TRACE(_MAKE_WARM, 0, 0, 0);

    tracer->initial_state.start_instr = start_instr;
    tracer->initial_state.close_loop_instr = close_loop_instr;
    tracer->initial_state.code = (PyCodeObject *)Py_NewRef(code);
    tracer->initial_state.func = (PyFunctionObject *)Py_NewRef(func);
    tracer->initial_state.executor = (_PyExecutorObject *)Py_XNewRef(current_executor);
    tracer->initial_state.exit = exit;
    tracer->initial_state.stack_depth = (int)(stack_pointer - _PyFrame_Stackbase(frame));
    tracer->initial_state.chain_depth = chain_depth;
    tracer->prev_state.instr_code = (PyCodeObject *)Py_NewRef(_PyFrame_GetCode(frame));
    tracer->prev_state.instr = curr_instr;
    tracer->prev_state.instr_frame = frame;
    tracer->prev_state.instr_oparg = oparg;
    tracer->prev_state.instr_stacklevel = tracer->initial_state.stack_depth;
    tracer->prev_state.recorded_count = 0;
    for (int i = 0; i < MAX_RECORDED_VALUES; i++) {
        tracer->prev_state.recorded_values[i] = NULL;
    }
    const _PyOpcodeRecordEntry *record_entry = &_PyOpcode_RecordEntries[curr_instr->op.code];
    for (int i = 0; i < record_entry->count; i++) {
        _Py_RecordFuncPtr record_func = _PyOpcode_RecordFunctions[record_entry->indices[i]];
        record_func(frame, stack_pointer, oparg, &tracer->prev_state.recorded_values[i]);
    }
    tracer->prev_state.recorded_count = record_entry->count;
    assert(curr_instr->op.code == JUMP_BACKWARD_JIT || curr_instr->op.code == RESUME_CHECK_JIT || (exit != NULL));
    tracer->initial_state.jump_backward_instr = curr_instr;

    DPRINTF(3, "Fitness init: chain_depth=%d, fitness=%d\n",
            chain_depth, ts->fitness);

    tracer->is_tracing = true;
    return 1;
}

Py_NO_INLINE void
_PyJit_FinalizeTracing(PyThreadState *tstate, int err)
{
    _PyThreadStateImpl *_tstate = (_PyThreadStateImpl *)tstate;
    _PyJitTracerState *tracer = _tstate->jit_tracer_state;
    // Deal with backoffs
    assert(tracer != NULL);
    _PyExitData *exit = tracer->initial_state.exit;
    if (exit == NULL) {
        // We hold a strong reference to the code object, so the instruction won't be freed.
        if (err <= 0) {
            _Py_BackoffCounter counter = tracer->initial_state.jump_backward_instr[1].counter;
            tracer->initial_state.jump_backward_instr[1].counter = restart_backoff_counter(counter);
        }
        else {
            /* Compilation may have replaced the triggering instruction with
             * ENTER_EXECUTOR. Recover its original opcode, including when an
             * EXTENDED_ARG prefix was the executor insertion point. */
            PyCodeObject *code = tracer->initial_state.code;
            int offset = (int)(tracer->initial_state.jump_backward_instr -
                               _PyCode_CODE(code));
            int opcode = _Py_GetBaseCodeUnit(code, offset).op.code;
            assert(opcode == JUMP_BACKWARD || opcode == RESUME);
            if (opcode == JUMP_BACKWARD) {
                tracer->initial_state.jump_backward_instr[1].counter = initial_jump_backoff_counter(&tstate->interp->opt_config);
            }
            else {
                tracer->initial_state.jump_backward_instr[1].counter = initial_resume_backoff_counter(&tstate->interp->opt_config);
            }
        }
    }
    else if (FT_ATOMIC_LOAD_UINT8(
                 tracer->initial_state.executor->vm_data.valid))
    {
        // Likewise, we hold a strong reference to the executor containing this exit, so the exit is guaranteed
        // to be valid to access.
        if (err <= 0) {
            exit->temperature = restart_backoff_counter(exit->temperature);
        }
        else {
            exit->temperature = initial_temperature_backoff_counter(&tstate->interp->opt_config);
        }
    }
    // Clear all recorded values
    _PyJitUopBuffer *buffer = &tracer->code_buffer;
    for (_PyUOpInstruction *inst = buffer->start; inst < buffer->next; inst++) {
        if (_PyUop_Flags[inst->opcode] & HAS_RECORDS_VALUE_FLAG) {
            Py_XDECREF((PyObject *)(uintptr_t)inst->operand0);
        }
    }
    Py_CLEAR(tracer->initial_state.code);
    Py_CLEAR(tracer->initial_state.func);
    Py_CLEAR(tracer->initial_state.executor);
    Py_CLEAR(tracer->prev_state.instr_code);
    for (int i = 0; i < MAX_RECORDED_VALUES; i++) {
        Py_CLEAR(tracer->prev_state.recorded_values[i]);
    }
    tracer->prev_state.recorded_count = 0;
    uop_buffer_init(buffer, &tracer->uop_array[0], UOP_MAX_TRACE_LENGTH);
    tracer->is_tracing = false;
}

bool
_PyJit_EnterExecutorShouldStopTracing(int og_opcode)
{
    // Continue tracing (skip over the executor). If it's a RESUME
    // trace to form longer, more optimizeable traces.
    // We want to trace over RESUME traces. Otherwise, functions with lots of RESUME
    // end up with many fragmented traces which perform badly.
    // See for example, the richards benchmark in pyperformance.
    // For consideration: We may want to consider tracing over side traces
    // inserted into bytecode as well in the future.
    return og_opcode == RESUME_CHECK_JIT;
}

void
_PyJit_TracerFree(_PyThreadStateImpl *_tstate)
{
    if (_tstate->jit_tracer_state != NULL) {
        _PyObject_VirtualFree(_tstate->jit_tracer_state, sizeof(_PyJitTracerState));
        _tstate->jit_tracer_state = NULL;
    }
}

#undef RESERVE
#undef INSTR_IP
#undef ADD_TO_TRACE
#undef DPRINTF

#define UNSET_BIT(array, bit) (array[(bit)>>5] &= ~(1<<((bit)&31)))
#define SET_BIT(array, bit) (array[(bit)>>5] |= (1<<((bit)&31)))
#define BIT_IS_SET(array, bit) (array[(bit)>>5] & (1<<((bit)&31)))

/* Count the number of unused uops and exits
*/
static int
count_exits(_PyUOpInstruction *buffer, int length)
{
    int exit_count = 0;
    for (int i = 0; i < length; i++) {
        uint16_t base_opcode = _PyUop_Uncached[buffer[i].opcode];
        if (base_opcode == _EXIT_TRACE || base_opcode == _DYNAMIC_EXIT) {
            exit_count++;
        }
    }
    return exit_count;
}

/* The number of cached registers at any exit (`EXIT_IF` or `DEOPT_IF`)
 * This is the number of cached at entries at start, unless the uop is
 * marked as `exit_depth_is_output` in which case it is the number of
 * cached entries at the end */
static int
get_cached_entries_for_side_exit(_PyUOpInstruction *inst)
{
    // Maybe add another generated table for this?
    int base_opcode = _PyUop_Uncached[inst->opcode];
    assert(base_opcode != 0);
    for (int i = 0; i <= MAX_CACHED_REGISTER; i++) {
        const _PyUopTOSentry *entry = &_PyUop_Caching[base_opcode].entries[i];
        if (entry->opcode == inst->opcode) {
            return entry->exit;
        }
    }
    Py_UNREACHABLE();
}

static void make_exit(_PyUOpInstruction *inst, int opcode, int target, bool is_control_flow)
{
    assert(opcode > MAX_UOP_ID && opcode <= MAX_UOP_REGS_ID);
    inst->opcode = opcode;
    inst->oparg = 0;
    inst->operand0 = 0;
    inst->format = UOP_FORMAT_TARGET;
    inst->target = target;
    inst->operand1 = is_control_flow;
#ifdef Py_STATS
    inst->fitness = 0;
    inst->execution_count = 0;
#endif
}

/* Convert implicit exits, errors and deopts
 * into explicit ones. */
static int
prepare_for_execution(_PyUOpInstruction *buffer, int length)
{
    int32_t current_jump = -1;
    int32_t current_jump_target = -1;
    int32_t current_error = -1;
    int32_t current_error_target = -1;
    int32_t current_popped = -1;
    int32_t current_exit_op = -1;
    /* Leaving in NOPs slows down the interpreter and messes up the stats */
    _PyUOpInstruction *copy_to = &buffer[0];
    for (int i = 0; i < length; i++) {
        _PyUOpInstruction *inst = &buffer[i];
        if (inst->opcode != _NOP) {
            if (copy_to != inst) {
                *copy_to = *inst;
            }
            copy_to++;
        }
    }
    length = (int)(copy_to - buffer);
    int next_spare = length;
    for (int i = 0; i < length; i++) {
        _PyUOpInstruction *inst = &buffer[i];
        int base_opcode = _PyUop_Uncached[inst->opcode];
        assert(inst->opcode != _NOP);
        int32_t target = (int32_t)uop_get_target(inst);
        uint16_t exit_flags = _PyUop_Flags[base_opcode] & (HAS_EXIT_FLAG | HAS_DEOPT_FLAG | HAS_PERIODIC_FLAG);
        if (exit_flags) {
            uint16_t base_exit_op = _EXIT_TRACE;
            if (exit_flags & HAS_DEOPT_FLAG) {
                base_exit_op = _DEOPT;
            }
            else if (exit_flags & HAS_PERIODIC_FLAG) {
                base_exit_op = _HANDLE_PENDING_AND_DEOPT;
            }
            int32_t jump_target = target;
            if (dynamic_exit_uop[base_opcode]) {
                base_exit_op = _DYNAMIC_EXIT;
            }
            int exit_depth = get_cached_entries_for_side_exit(inst);
            assert(_PyUop_Caching[base_exit_op].entries[exit_depth].opcode > 0);
            int16_t exit_op = _PyUop_Caching[base_exit_op].entries[exit_depth].opcode;
            bool is_control_flow = (base_opcode == _GUARD_IS_FALSE_POP || base_opcode == _GUARD_IS_TRUE_POP || is_for_iter_test[base_opcode]);
            if (jump_target != current_jump_target || current_exit_op != exit_op) {
                make_exit(&buffer[next_spare], exit_op, jump_target, is_control_flow);
                current_exit_op = exit_op;
                current_jump_target = jump_target;
                current_jump = next_spare;
                next_spare++;
            }
            buffer[i].jump_target = current_jump;
            buffer[i].format = UOP_FORMAT_JUMP;
        }
        if (_PyUop_Flags[base_opcode] & HAS_ERROR_FLAG) {
            int popped = (_PyUop_Flags[base_opcode] & HAS_ERROR_NO_POP_FLAG) ?
                0 : _PyUop_num_popped(base_opcode, inst->oparg);
            if (target != current_error_target || popped != current_popped) {
                current_popped = popped;
                current_error = next_spare;
                current_error_target = target;
                make_exit(&buffer[next_spare], _ERROR_POP_N_r00, 0, false);
                buffer[next_spare].operand0 = target;
                next_spare++;
            }
            buffer[i].error_target = current_error;
            if (buffer[i].format == UOP_FORMAT_TARGET) {
                buffer[i].format = UOP_FORMAT_JUMP;
                buffer[i].jump_target = 0;
            }
        }
        if (base_opcode == _JUMP_TO_TOP) {
            assert(_PyUop_Uncached[buffer[0].opcode] == _START_EXECUTOR);
            buffer[i].format = UOP_FORMAT_JUMP;
            buffer[i].jump_target = 1;
        }
    }
    return next_spare;
}

/* Executor side exits */

static _PyExecutorObject *
allocate_executor(int exit_count, int length)
{
    int size = exit_count*sizeof(_PyExitData) + length*sizeof(_PyUOpInstruction);
    _PyExecutorObject *res = PyObject_GC_NewVar(_PyExecutorObject, &_PyUOpExecutor_Type, size);
    if (res == NULL) {
        return NULL;
    }
    res->trace = (_PyUOpInstruction *)(res->exits + exit_count);
    res->code_size = length;
    res->exit_count = exit_count;
    res->jit_registration = NULL;
    return res;
}

#ifdef Py_DEBUG

#define CHECK(PRED) \
if (!(PRED)) { \
    printf(#PRED " at %d\n", i); \
    assert(0); \
}

static int
target_unused(int opcode)
{
    return (_PyUop_Flags[opcode] & (HAS_ERROR_FLAG | HAS_EXIT_FLAG | HAS_DEOPT_FLAG)) == 0;
}

static void
sanity_check(_PyExecutorObject *executor)
{
    for (uint32_t i = 0; i < executor->exit_count; i++) {
        _PyExitData *exit = &executor->exits[i];
        CHECK(exit->target < (1 << 25));
    }
    bool ended = false;
    uint32_t i = 0;
    CHECK(_PyUop_Uncached[executor->trace[0].opcode] == _START_EXECUTOR ||
        _PyUop_Uncached[executor->trace[0].opcode] == _COLD_EXIT ||
        _PyUop_Uncached[executor->trace[0].opcode] == _COLD_DYNAMIC_EXIT);
    if (executor->vm_data.is_method) {
        bool has_method_exit = false;
        for (; i < executor->code_size; i++) {
            const _PyUOpInstruction *inst = &executor->trace[i];
            uint16_t opcode = inst->opcode;
            uint16_t base_opcode = _PyUop_Uncached[opcode];
            CHECK(opcode > MAX_UOP_ID);
            CHECK(opcode <= MAX_UOP_REGS_ID);
            CHECK(base_opcode > 0 && base_opcode <= MAX_UOP_ID);
            if (inst->format == UOP_FORMAT_JUMP) {
                CHECK(inst->jump_target < executor->code_size);
            }
            else {
                CHECK(target_unused(base_opcode));
            }
            if (_PyUop_Flags[base_opcode] & HAS_ERROR_FLAG) {
                CHECK(inst->format == UOP_FORMAT_JUMP);
                CHECK(inst->error_target < executor->code_size);
            }
            has_method_exit |= base_opcode == _METHOD_DEOPT ||
                base_opcode == _METHOD_EXIT;
        }
        CHECK(has_method_exit);
        return;
    }
    for (; i < executor->code_size; i++) {
        const _PyUOpInstruction *inst = &executor->trace[i];
        uint16_t opcode = inst->opcode;
        uint16_t base_opcode = _PyUop_Uncached[opcode];
        CHECK(opcode > MAX_UOP_ID);
        CHECK(opcode <= MAX_UOP_REGS_ID);
        CHECK(base_opcode <= MAX_UOP_ID);
        CHECK(base_opcode != 0);
        switch(inst->format) {
            case UOP_FORMAT_TARGET:
                CHECK(target_unused(base_opcode));
                break;
            case UOP_FORMAT_JUMP:
                CHECK(inst->jump_target < executor->code_size);
                break;
        }
        if (_PyUop_Flags[base_opcode] & HAS_ERROR_FLAG) {
            CHECK(inst->format == UOP_FORMAT_JUMP);
            CHECK(inst->error_target < executor->code_size);
        }
        if (is_terminator(inst)) {
            ended = true;
            i++;
            break;
        }
    }
    CHECK(ended);
    for (; i < executor->code_size; i++) {
        const _PyUOpInstruction *inst = &executor->trace[i];
        uint16_t base_opcode = _PyUop_Uncached[inst->opcode];
        CHECK(
            base_opcode == _DEOPT ||
            base_opcode == _HANDLE_PENDING_AND_DEOPT ||
            base_opcode == _EXIT_TRACE ||
            base_opcode == _ERROR_POP_N ||
            base_opcode == _DYNAMIC_EXIT);
    }
}

#undef CHECK
#endif

/* Makes an executor from a buffer of uops.
 * Account for the buffer having gaps and NOPs by computing a "used"
 * bit vector and only copying the used uops. Here "used" means reachable
 * and not a NOP.
 */
static _PyExecutorObject *
make_executor_from_uops(
    PyInterpreterState *interp,
    _PyUOpInstruction *buffer,
    int length,
    const _PyBloomFilter *dependencies,
    int chain_depth,
    bool is_method)
{
    int exit_count = count_exits(buffer, length);
    _PyExecutorObject *executor = allocate_executor(exit_count, length);
    if (executor == NULL) {
        return NULL;
    }

    /* Initialize exits */
    _PyExecutorObject *cold = _PyExecutor_GetColdExecutor();
    _PyExecutorObject *cold_dynamic = _PyExecutor_GetColdDynamicExecutor();
    cold->vm_data.chain_depth = chain_depth;
    for (int i = 0; i < exit_count; i++) {
        executor->exits[i].index = i;
        executor->exits[i].temperature = initial_temperature_backoff_counter(&interp->opt_config);
    }
    int next_exit = exit_count-1;
    _PyUOpInstruction *dest = (_PyUOpInstruction *)&executor->trace[length];
    assert(_PyUop_Uncached[buffer[0].opcode] == _START_EXECUTOR);
    buffer[0].operand0 = (uint64_t)executor;
    for (int i = length-1; i >= 0; i--) {
        uint16_t base_opcode = _PyUop_Uncached[buffer[i].opcode];
        dest--;
        *dest = buffer[i];
        if (base_opcode == _EXIT_TRACE || base_opcode == _DYNAMIC_EXIT) {
            _PyExitData *exit = &executor->exits[next_exit];
            exit->target = buffer[i].target;
            dest->operand0 = (uint64_t)exit;
            exit->executor = base_opcode == _EXIT_TRACE ? cold : cold_dynamic;
            exit->is_dynamic = (char)(base_opcode == _DYNAMIC_EXIT);
            exit->is_control_flow = (char)buffer[i].operand1;
            next_exit--;
        }
    }
    assert(next_exit == -1);
    assert(dest == executor->trace);
    assert(_PyUop_Uncached[dest->opcode] == _START_EXECUTOR);
    // Note: we MUST track it here before any Py_DECREF(executor) or
    // linking of executor. Otherwise, the GC tries to untrack a
    // still untracked object during dealloc.
    _PyObject_GC_TRACK(executor);
    if (_Py_ExecutorInit(executor, dependencies) < 0) {
        Py_DECREF(executor);
        return NULL;
    }
    executor->vm_data.is_method = is_method;
#ifdef Py_DEBUG
    char *python_lltrace = Py_GETENV("PYTHON_LLTRACE");
    int lltrace = 0;
    if (python_lltrace != NULL && *python_lltrace >= '0') {
        lltrace = *python_lltrace - '0';  // TODO: Parse an int and all that
    }
    if (lltrace >= 2) {
        printf("Optimized trace (length %d):\n", length);
        for (int i = 0; i < length; i++) {
            printf("%4d OPTIMIZED: ", i);
            _PyUOpPrint(&executor->trace[i]);
            printf("\n");
        }
    }
    sanity_check(executor);
#endif
#ifdef _Py_JIT
    executor->jit_code = NULL;
    executor->jit_size = 0;
    // This is initialized to false so we can prevent the executor
    // from being immediately detected as cold and invalidated.
    executor->vm_data.cold = false;
    if (_PyJIT_Compile(executor, executor->trace, length)) {
        Py_DECREF(executor);
        return NULL;
    }
#endif
    return executor;
}

#ifdef Py_STATS
/* Returns the effective trace length.
 * Ignores NOPs and trailing exit and error handling.*/
int effective_trace_length(_PyUOpInstruction *buffer, int length)
{
    int nop_count = 0;
    for (int i = 0; i < length; i++) {
        int opcode = buffer[i].opcode;
        if (opcode == _NOP) {
            nop_count++;
        }
        if (is_terminator(&buffer[i])) {
            return i+1-nop_count;
        }
    }
    Py_FatalError("No terminating instruction");
    Py_UNREACHABLE();
}
#endif


static int
stack_allocate(
    _PyUOpInstruction *buffer,
    _PyUOpInstruction *output,
    int length,
    uint16_t *offset_map)
{
    assert(buffer[0].opcode == _START_EXECUTOR);
    /* The input buffer and output buffers will overlap.
       Make sure that we can move instructions to the output
       without overwriting the input. */
    if (buffer == output) {
        // This can only happen if optimizer has not been run
        for (int i = 0; i < length; i++) {
            buffer[i + UOP_MAX_TRACE_LENGTH] = buffer[i];
        }
        buffer += UOP_MAX_TRACE_LENGTH;
    }
    int depth = 0;
    _PyUOpInstruction *write = output;
    for (int i = 0; i < length; i++) {
        if (offset_map != NULL) {
            ptrdiff_t offset = write - output;
            if (offset > UINT16_MAX) {
                return -1;
            }
            offset_map[i] = (uint16_t)offset;
        }
        int uop = buffer[i].opcode;
        if (uop == _NOP) {
            continue;
        }
        int new_depth = _PyUop_Caching[uop].best[depth];
        if (new_depth != depth) {
            write->opcode = _PyUop_SpillsAndReloads[depth][new_depth];
            assert(write->opcode != 0);
            write->format = UOP_FORMAT_TARGET;
            write->oparg = 0;
            write->target = 0;
            write++;
            depth = new_depth;
        }
        *write = buffer[i];
        uint16_t new_opcode = _PyUop_Caching[uop].entries[depth].opcode;
        assert(new_opcode != 0);
        write->opcode = new_opcode;
        write++;
        depth = _PyUop_Caching[uop].entries[depth].output;
    }
    return (int)(write - output);
}


/* Method frontend
 *
 * The tracing frontend can carry cached stack entries across a single known
 * path. A method has merge points, so its control-flow uops have an empty
 * cache signature. stack_allocate() consequently spills before every edge,
 * and every block starts with the Python value stack as its only state.
 */

typedef enum {
    METHOD_FALLTHROUGH,
    METHOD_BRANCH,
    METHOD_JUMP,
    METHOD_RETURN,
} _PyMethodTerminator;

typedef struct {
    uint16_t offset;
    uint16_t opcode_offset;
    uint16_t next_offset;
    uint16_t opcode;
    uint32_t oparg;
} _PyMethodInstruction;

typedef struct {
    uint16_t first;
    uint16_t last;
    uint16_t uop_offset;
    int16_t target;
    int16_t fallthrough;
    uint8_t initialized;
    uint8_t in_queue;
    uint16_t stack_depth;
    _PyMethodTerminator terminator;
} _PyMethodBlock;

typedef enum {
    METHOD_VALUE_UNKNOWN,
    METHOD_VALUE_NULL,
    METHOD_VALUE_TYPE,
    METHOD_VALUE_CONST,
} _PyMethodValueKind;

typedef struct {
    PyObject *object;
    uint8_t kind;
    uint8_t compact_int;
} _PyMethodValue;

static _PyMethodValue
method_value_unknown(void)
{
    return (_PyMethodValue) { .kind = METHOD_VALUE_UNKNOWN };
}

static _PyMethodValue
method_value_null(void)
{
    return (_PyMethodValue) { .kind = METHOD_VALUE_NULL };
}

static _PyMethodValue
method_value_type(PyTypeObject *type, bool compact_int)
{
    return (_PyMethodValue) {
        .object = (PyObject *)type,
        .kind = METHOD_VALUE_TYPE,
        .compact_int = compact_int,
    };
}

static _PyMethodValue
method_value_const(PyObject *value)
{
    bool compact = PyLong_CheckExact(value) &&
        _PyLong_IsCompact((PyLongObject *)value);
    return (_PyMethodValue) {
        .object = value,
        .kind = METHOD_VALUE_CONST,
        .compact_int = compact,
    };
}

static PyTypeObject *
method_value_get_type(_PyMethodValue value)
{
    if (value.kind == METHOD_VALUE_CONST) {
        return Py_TYPE(value.object);
    }
    if (value.kind == METHOD_VALUE_TYPE) {
        return (PyTypeObject *)value.object;
    }
    return NULL;
}

static bool
method_value_equal(_PyMethodValue left, _PyMethodValue right)
{
    return left.kind == right.kind &&
        left.object == right.object &&
        left.compact_int == right.compact_int;
}

static _PyMethodValue
method_value_merge(_PyMethodValue left, _PyMethodValue right)
{
    if (method_value_equal(left, right)) {
        return left;
    }
    PyTypeObject *left_type = method_value_get_type(left);
    PyTypeObject *right_type = method_value_get_type(right);
    if (left_type != NULL && left_type == right_type) {
        return method_value_type(
            left_type, left.compact_int && right.compact_int);
    }
    return method_value_unknown();
}

static int
method_apply_stack_effect(
    PyCodeObject *code,
    const _PyMethodInstruction *mi,
    _PyMethodValue *values,
    int locals_count,
    int stack_capacity,
    int *depth,
    bool jump)
{
    int opcode = mi->opcode;
    int base_opcode = _PyOpcode_Deopt[opcode];
    _PyMethodValue *stack = values + locals_count;

    /* The generated stack-effect tables deliberately treat superinstructions
     * as opaque.  Preserve their local-state transfers here so that facts can
     * survive across the following bytecode and around loop backedges. */
    if (opcode == LOAD_FAST_LOAD_FAST ||
        opcode == LOAD_FAST_BORROW_LOAD_FAST_BORROW)
    {
        uint32_t first = mi->oparg >> 4;
        uint32_t second = mi->oparg & 15;
        if (mi->oparg > UINT8_MAX || first >= (uint32_t)locals_count ||
            second >= (uint32_t)locals_count ||
            *depth + 2 > stack_capacity)
        {
            return 0;
        }
        stack[(*depth)++] = values[first];
        stack[(*depth)++] = values[second];
        return 1;
    }
    if (opcode == STORE_FAST_LOAD_FAST) {
        uint32_t store = mi->oparg >> 4;
        uint32_t load = mi->oparg & 15;
        if (mi->oparg > UINT8_MAX || store >= (uint32_t)locals_count ||
            load >= (uint32_t)locals_count || *depth < 1)
        {
            return 0;
        }
        values[store] = stack[--(*depth)];
        stack[(*depth)++] = values[load];
        return 1;
    }
    if (opcode == STORE_FAST_STORE_FAST) {
        uint32_t first = mi->oparg >> 4;
        uint32_t second = mi->oparg & 15;
        if (mi->oparg > UINT8_MAX || first >= (uint32_t)locals_count ||
            second >= (uint32_t)locals_count || *depth < 2)
        {
            return 0;
        }
        values[first] = stack[*depth - 1];
        values[second] = stack[*depth - 2];
        *depth -= 2;
        return 1;
    }
    if (opcode == LOAD_FAST_BORROW) {
        if (mi->oparg >= (uint32_t)locals_count ||
            *depth >= stack_capacity)
        {
            return 0;
        }
        stack[(*depth)++] = values[mi->oparg];
        return 1;
    }
    if (opcode == CALL_PY_EXACT_ARGS) {
        int popped = 2 + (int)mi->oparg;
        if (popped > *depth || *depth - popped >= stack_capacity) {
            return 0;
        }
        *depth -= popped;
        stack[(*depth)++] = method_value_unknown();
        return 1;
    }

    if (base_opcode == FOR_ITER) {
        if (*depth < 2) {
            return 0;
        }
        if (jump) {
            /* The direct edge skips END_FOR and lands on POP_ITER, which
             * performs the two-value cleanup. */
            return 1;
        }
        if (*depth >= stack_capacity) {
            return 0;
        }
        PyTypeObject *item_type = NULL;
        if (opcode == FOR_ITER_RANGE) {
            item_type = &PyLong_Type;
        }
        stack[(*depth)++] = item_type == NULL
            ? method_value_unknown()
            : method_value_type(item_type, true);
        return 1;
    }

    switch (base_opcode) {
        case LOAD_CONST:
            if (*depth >= stack_capacity) {
                return 0;
            }
            stack[(*depth)++] = method_value_const(
                PyTuple_GET_ITEM(code->co_consts, mi->oparg));
            return 1;
        case LOAD_SMALL_INT:
            if (*depth >= stack_capacity) {
                return 0;
            }
            stack[(*depth)++] = method_value_type(&PyLong_Type, true);
            return 1;
        case LOAD_FAST:
            if (mi->oparg >= (uint32_t)locals_count ||
                *depth >= stack_capacity)
            {
                return 0;
            }
            stack[(*depth)++] = values[mi->oparg];
            return 1;
        case LOAD_FAST_AND_CLEAR:
            if (mi->oparg >= (uint32_t)locals_count ||
                *depth >= stack_capacity)
            {
                return 0;
            }
            stack[(*depth)++] = values[mi->oparg];
            values[mi->oparg] = method_value_null();
            return 1;
        case STORE_FAST:
            if (mi->oparg >= (uint32_t)locals_count || *depth < 1) {
                return 0;
            }
            values[mi->oparg] = stack[--(*depth)];
            return 1;
        case DELETE_FAST:
            if (mi->oparg >= (uint32_t)locals_count) {
                return 0;
            }
            values[mi->oparg] = method_value_null();
            return 1;
        case PUSH_NULL:
            if (*depth >= stack_capacity) {
                return 0;
            }
            stack[(*depth)++] = method_value_null();
            return 1;
        case COPY:
            if (mi->oparg == 0 || mi->oparg > (uint32_t)*depth ||
                *depth >= stack_capacity)
            {
                return 0;
            }
            stack[*depth] = stack[*depth - (int)mi->oparg];
            (*depth)++;
            return 1;
        case SWAP:
            if (mi->oparg == 0 || mi->oparg > (uint32_t)*depth) {
                return 0;
            }
            {
                _PyMethodValue tmp = stack[*depth - 1];
                stack[*depth - 1] = stack[*depth - (int)mi->oparg];
                stack[*depth - (int)mi->oparg] = tmp;
            }
            return 1;
    }

    int popped = _PyOpcode_num_popped(opcode, mi->oparg);
    int pushed = _PyOpcode_num_pushed(opcode, mi->oparg);
    if (popped < 0 || pushed < 0 || popped > *depth ||
        *depth - popped + pushed > stack_capacity)
    {
        return 0;
    }
    *depth -= popped;
    _PyMethodValue result = method_value_unknown();
    switch (opcode) {
        case BINARY_OP_ADD_INT:
        case BINARY_OP_SUBTRACT_INT:
        case BINARY_OP_MULTIPLY_INT:
            result = method_value_type(&PyLong_Type, false);
            break;
        case BINARY_OP_ADD_FLOAT:
        case BINARY_OP_SUBTRACT_FLOAT:
        case BINARY_OP_MULTIPLY_FLOAT:
            result = method_value_type(&PyFloat_Type, false);
            break;
        case BINARY_OP_ADD_UNICODE:
            result = method_value_type(&PyUnicode_Type, false);
            break;
        case COMPARE_OP_INT:
        case COMPARE_OP_FLOAT:
        case COMPARE_OP_STR:
        case IS_OP:
        case CONTAINS_OP:
        case TO_BOOL:
        case TO_BOOL_ALWAYS_TRUE:
        case TO_BOOL_BOOL:
        case TO_BOOL_INT:
        case TO_BOOL_LIST:
        case TO_BOOL_NONE:
        case TO_BOOL_STR:
        case UNARY_NOT:
            result = method_value_type(&PyBool_Type, false);
            break;
        case BUILD_LIST:
            result = method_value_type(&PyList_Type, false);
            break;
        case BUILD_TUPLE:
            result = method_value_type(&PyTuple_Type, false);
            break;
        case BUILD_MAP:
            result = method_value_type(&PyDict_Type, false);
            break;
        case BUILD_SET:
            result = method_value_type(&PySet_Type, false);
            break;
    }
    for (int i = 0; i < pushed; i++) {
        stack[(*depth)++] = i == pushed - 1
            ? result : method_value_unknown();
    }
    return 1;
}

static int
method_merge_block(
    _PyMethodBlock *block,
    _PyMethodValue *destination,
    const _PyMethodValue *source,
    int locals_count,
    int stack_capacity,
    int depth)
{
    if (depth < 0 || depth > stack_capacity) {
        return -1;
    }
    int active = locals_count + depth;
    if (!block->initialized) {
        memcpy(destination, source, active * sizeof(*destination));
        block->stack_depth = (uint16_t)depth;
        block->initialized = 1;
        return 1;
    }
    if (block->stack_depth != depth) {
        return -1;
    }
    int changed = 0;
    for (int i = 0; i < active; i++) {
        _PyMethodValue merged = method_value_merge(destination[i], source[i]);
        if (!method_value_equal(destination[i], merged)) {
            destination[i] = merged;
            changed = 1;
        }
    }
    return changed;
}

static PyFunctionObject *
method_lookup_function(PyInterpreterState *interp, uint32_t version)
{
    if (version < FUNC_VERSION_FIRST_VALID) {
        return NULL;
    }
    PyFunctionObject *func = NULL;
    FT_MUTEX_LOCK(&interp->func_state.mutex);
    struct _func_version_cache_item *slot =
        &interp->func_state.func_version_cache[
            version % FUNC_VERSION_CACHE_SIZE];
    if (slot->func != NULL && slot->func->func_version == version) {
        func = (PyFunctionObject *)Py_NewRef((PyObject *)slot->func);
    }
    FT_MUTEX_UNLOCK(&interp->func_state.mutex);
    return func;
}

static int
method_emit(
    _PyUOpInstruction *buffer,
    int *length,
    int limit,
    uint16_t opcode,
    uint16_t oparg,
    uint64_t operand,
    uint32_t target)
{
    if (*length >= limit) {
        return 0;
    }
    _PyUOpInstruction *inst = &buffer[(*length)++];
    inst->opcode = opcode;
    inst->format = UOP_FORMAT_TARGET;
    inst->oparg = oparg;
    inst->target = target;
    inst->operand0 = operand;
    inst->operand1 = 0;
#ifdef Py_STATS
    inst->fitness = 0;
    inst->execution_count = 0;
#endif
    return 1;
}

static bool
method_is_conditional_jump(int opcode)
{
    return opcode == POP_JUMP_IF_FALSE ||
           opcode == POP_JUMP_IF_TRUE ||
           opcode == POP_JUMP_IF_NONE ||
           opcode == POP_JUMP_IF_NOT_NONE ||
           opcode == FOR_ITER;
}

static bool
method_is_unconditional_jump(int opcode)
{
    return opcode == JUMP_FORWARD ||
           opcode == JUMP_BACKWARD ||
           opcode == JUMP_BACKWARD_NO_INTERRUPT;
}

static int
method_replacement(int uop)
{
    switch (uop) {
        case _POP_JUMP_IF_FALSE:
            return _METHOD_POP_JUMP_IF_FALSE;
        case _POP_JUMP_IF_TRUE:
            return _METHOD_POP_JUMP_IF_TRUE;
        case _FOR_ITER:
        case _FOR_ITER_VIRTUAL:
            return _METHOD_FOR_ITER;
        case _ITER_JUMP_LIST:
            return _METHOD_ITER_JUMP_LIST;
        case _ITER_JUMP_TUPLE:
            return _METHOD_ITER_JUMP_TUPLE;
        case _ITER_JUMP_RANGE:
            return _METHOD_ITER_JUMP_RANGE;
        default:
            return _PyUOp_Replacements[uop];
    }
}

static int
method_optimize_guard(
    int uop,
    const _PyMethodValue *values,
    int locals_count,
    int stack_depth)
{
    int stack_index = -1;
    PyTypeObject *expected = NULL;
    bool compact = false;
    switch (uop) {
        case _GUARD_TOS_INT:
        case _GUARD_TOS_EXACT_INT:
        case _GUARD_TOS_OVERFLOWED:
            stack_index = stack_depth - 1;
            expected = &PyLong_Type;
            compact = uop != _GUARD_TOS_EXACT_INT;
            break;
        case _GUARD_NOS_INT:
        case _GUARD_NOS_OVERFLOWED:
            stack_index = stack_depth - 2;
            expected = &PyLong_Type;
            compact = true;
            break;
        case _GUARD_TOS_FLOAT:
            stack_index = stack_depth - 1;
            expected = &PyFloat_Type;
            break;
        case _GUARD_NOS_FLOAT:
            stack_index = stack_depth - 2;
            expected = &PyFloat_Type;
            break;
        case _GUARD_TOS_LIST:
            stack_index = stack_depth - 1;
            expected = &PyList_Type;
            break;
        case _GUARD_NOS_LIST:
            stack_index = stack_depth - 2;
            expected = &PyList_Type;
            break;
        case _GUARD_TOS_TUPLE:
            stack_index = stack_depth - 1;
            expected = &PyTuple_Type;
            break;
        case _GUARD_NOS_TUPLE:
            stack_index = stack_depth - 2;
            expected = &PyTuple_Type;
            break;
        case _GUARD_TOS_UNICODE:
            stack_index = stack_depth - 1;
            expected = &PyUnicode_Type;
            break;
        case _GUARD_NOS_UNICODE:
            stack_index = stack_depth - 2;
            expected = &PyUnicode_Type;
            break;
        case _GUARD_TOS_DICT:
        case _GUARD_TOS_ANY_DICT:
            stack_index = stack_depth - 1;
            expected = &PyDict_Type;
            break;
        case _GUARD_TOS_SET:
            stack_index = stack_depth - 1;
            expected = &PySet_Type;
            break;
        case _GUARD_TOS_FROZENSET:
            stack_index = stack_depth - 1;
            expected = &PyFrozenSet_Type;
            break;
        case _GUARD_TOS_SLICE:
            stack_index = stack_depth - 1;
            expected = &PySlice_Type;
            break;
        default:
            return uop;
    }
    if (stack_index < 0) {
        return uop;
    }
    _PyMethodValue value = values[locals_count + stack_index];
    if (method_value_get_type(value) != expected) {
        return uop;
    }
    if (!compact || value.compact_int) {
        return _NOP;
    }
    if (uop == _GUARD_TOS_INT) {
        return _GUARD_TOS_OVERFLOWED;
    }
    if (uop == _GUARD_NOS_INT) {
        return _GUARD_NOS_OVERFLOWED;
    }
    return uop;
}

static void
method_apply_uop_effect(
    int uop,
    int oparg,
    uint64_t operand,
    _PyMethodValue *values,
    int locals_count,
    int stack_capacity,
    int *stack_depth)
{
    _PyMethodValue *stack = values + locals_count;
    switch (uop) {
        case _LOAD_FAST:
        case _LOAD_FAST_BORROW:
            if (oparg < locals_count && *stack_depth < stack_capacity) {
                stack[(*stack_depth)++] = values[oparg];
            }
            return;
        case _LOAD_SMALL_INT:
            if (*stack_depth < stack_capacity) {
                stack[(*stack_depth)++] =
                    method_value_type(&PyLong_Type, true);
            }
            return;
        case _LOAD_CONST_INLINE:
        case _LOAD_CONST_INLINE_BORROW:
            if (*stack_depth < stack_capacity) {
                stack[(*stack_depth)++] =
                    method_value_const((PyObject *)(uintptr_t)operand);
            }
            return;
        case _PUSH_NULL:
            if (*stack_depth < stack_capacity) {
                stack[(*stack_depth)++] = method_value_null();
            }
            return;
        case _SWAP_FAST:
            if (oparg < locals_count && *stack_depth > 0) {
                _PyMethodValue tmp = values[oparg];
                values[oparg] = stack[*stack_depth - 1];
                stack[*stack_depth - 1] = tmp;
            }
            return;
        case _POP_TOP:
        case _POP_TOP_INT:
        case _POP_TOP_FLOAT:
        case _POP_TOP_UNICODE:
        case _POP_TOP_NOP:
            if (*stack_depth > 0) {
                (*stack_depth)--;
            }
            return;
        case _BINARY_OP_ADD_INT:
        case _BINARY_OP_SUBTRACT_INT:
        case _BINARY_OP_MULTIPLY_INT:
        case _BINARY_OP_ADD_FLOAT:
        case _BINARY_OP_SUBTRACT_FLOAT:
        case _BINARY_OP_MULTIPLY_FLOAT:
        case _COMPARE_OP_INT:
        case _COMPARE_OP_FLOAT:
        case _COMPARE_OP_STR:
            if (*stack_depth >= 2 && *stack_depth < stack_capacity) {
                _PyMethodValue result;
                if (uop == _BINARY_OP_ADD_INT ||
                    uop == _BINARY_OP_SUBTRACT_INT ||
                    uop == _BINARY_OP_MULTIPLY_INT)
                {
                    result = method_value_type(&PyLong_Type, false);
                }
                else if (uop == _BINARY_OP_ADD_FLOAT ||
                         uop == _BINARY_OP_SUBTRACT_FLOAT ||
                         uop == _BINARY_OP_MULTIPLY_FLOAT)
                {
                    result = method_value_type(&PyFloat_Type, false);
                }
                else {
                    result = method_value_type(&PyBool_Type, false);
                }
                *stack_depth -= 2;
                stack[(*stack_depth)++] = result;
                stack[(*stack_depth)++] = method_value_unknown();
                stack[(*stack_depth)++] = method_value_unknown();
            }
            return;
        case _TO_BOOL:
        case _TO_BOOL_INT:
        case _TO_BOOL_LIST:
        case _TO_BOOL_STR:
            if (*stack_depth > 0 && *stack_depth < stack_capacity) {
                (*stack_depth)--;
                stack[(*stack_depth)++] =
                    method_value_type(&PyBool_Type, false);
                stack[(*stack_depth)++] = method_value_unknown();
            }
            return;
    }
}

static int
method_inline_straight_line(
    PyThreadState *tstate,
    PyCodeObject *root_code,
    PyFunctionObject *func,
    _PyBloomFilter *dependencies,
    _PyUOpInstruction *buffer,
    int *length,
    int limit);

/* Translate one non-jump bytecode. The caller emits the block edge. */
static int
method_translate_instruction(
    PyThreadState *tstate,
    PyCodeObject *root_code,
    _PyBloomFilter *dependencies,
    bool allow_inline,
    PyCodeObject *code,
    _Py_CODEUNIT *bytecode,
    const _PyMethodInstruction *mi,
    int target_block,
    const _PyMethodValue *state,
    int locals_count,
    int stack_depth,
    int stack_capacity,
    _PyMethodValue *uop_state,
    _PyUOpInstruction *buffer,
    int *length,
    int limit)
{
    _Py_CODEUNIT *instr = bytecode + mi->opcode_offset;
    int opcode = mi->opcode;
    uint32_t oparg = mi->oparg;
    uint32_t target = mi->offset;
    memcpy(uop_state, state,
           (size_t)(locals_count + stack_depth) * sizeof(*state));
    int uop_stack_depth = stack_depth;

    if (!method_emit(buffer, length, limit, _CHECK_VALIDITY, 0, 0, target)) {
        return 0;
    }
    if (opcode == RESUME || opcode == RESUME_CHECK_JIT || opcode == RESUME_CHECK) {
        return method_emit(
            buffer, length, limit, _TIER2_RESUME_CHECK, 0, 0, target);
    }
    if (OPCODE_HAS_NEEDS_GUARD_IP(opcode) &&
        _PyOpcode_Deopt[opcode] != RETURN_VALUE &&
        !(allow_inline && opcode == CALL_PY_EXACT_ARGS))
    {
        return 0;
    }
    if (!OPCODE_HAS_NO_SAVE_IP(opcode) &&
        !method_emit(
            buffer, length, limit, _SET_IP, 0,
            (uintptr_t)(bytecode + mi->offset), target))
    {
        return 0;
    }

    const struct opcode_macro_expansion *expansion =
        &_PyOpcode_macro_expansion[opcode];
    if (expansion->nuops == 0) {
        return 0;
    }
    uint32_t inline_version = 0;
    bool pushes_frame = false;
    for (int i = 0; i < expansion->nuops; i++) {
        if (expansion->uops[i].uop == _PUSH_FRAME) {
            pushes_frame = true;
        }
        if (expansion->uops[i].uop == _CHECK_FUNCTION_VERSION &&
            expansion->uops[i].size == OPARG_CACHE_2)
        {
            int offset = expansion->uops[i].offset + 1;
            inline_version = read_u32(&instr[offset].cache);
        }
    }
    if (pushes_frame &&
        (!allow_inline || opcode != CALL_PY_EXACT_ARGS ||
         inline_version < FUNC_VERSION_FIRST_VALID))
    {
        return 0;
    }

    uint32_t orig_oparg = oparg;
    uint32_t orig_target = target;
    int direct_jump_index = -1;
    for (int i = 0; i < expansion->nuops; i++) {
        oparg = orig_oparg;
        target = orig_target;
        uint32_t uop = expansion->uops[i].uop;
        uint64_t operand = 0;
        int offset = expansion->uops[i].offset + 1;
        switch (expansion->uops[i].size) {
            case OPARG_SIMPLE:
                break;
            case OPARG_CACHE_1:
                operand = read_u16(&instr[offset].cache);
                break;
            case OPARG_CACHE_2:
                operand = read_u32(&instr[offset].cache);
                break;
            case OPARG_CACHE_4:
                operand = read_u64(&instr[offset].cache);
                break;
            case OPARG_TOP:
                if (orig_oparg > UINT8_MAX) {
                    return 0;
                }
                oparg = orig_oparg >> 4;
                break;
            case OPARG_BOTTOM:
                if (orig_oparg > UINT8_MAX) {
                    return 0;
                }
                oparg = orig_oparg & 0x0f;
                break;
            case OPARG_SAVE_RETURN_OFFSET:
                oparg = offset;
                break;
            case OPARG_REPLACED:
                uop = method_replacement(uop);
                if (uop == 0) {
                    return 0;
                }
                if (uop == _TIER2_RESUME_CHECK) {
                    if (instr > bytecode && instr[-1].op.code == LOAD_SPECIAL) {
                        uop = _NOP;
                    }
                    else {
                        /* The call is complete when its periodic check runs.
                         * A side exit must continue at the next bytecode rather
                         * than execute the call again with its result stack. */
                        target = mi->next_offset;
                    }
                }
                break;
            case OPERAND1_1:
                if (*length == 0) {
                    return 0;
                }
                buffer[*length - 1].operand1 = read_u16(&instr[offset].cache);
                continue;
            case OPERAND1_2:
                if (*length == 0) {
                    return 0;
                }
                buffer[*length - 1].operand1 = read_u32(&instr[offset].cache);
                continue;
            case OPERAND1_4:
                if (*length == 0) {
                    return 0;
                }
                buffer[*length - 1].operand1 = read_u64(&instr[offset].cache);
                continue;
            default:
                return 0;
        }
        int original_uop = (int)uop;
        uop = method_optimize_guard(
            original_uop, uop_state, locals_count, uop_stack_depth);
        if (_PyUop_Flags[uop] & HAS_RECORDS_VALUE_FLAG) {
            continue;
        }
        if (uop == _NOP || uop == _LOAD_BYTECODE) {
            method_apply_uop_effect(
                original_uop, (int)oparg, operand, uop_state,
                locals_count, stack_capacity, &uop_stack_depth);
            continue;
        }
        if (uop == _BINARY_OP_INPLACE_ADD_UNICODE) {
            _Py_CODEUNIT *next = bytecode + mi->next_offset;
            if (next >= bytecode + Py_SIZE(code) ||
                _PyOpcode_Deopt[next->op.code] != STORE_FAST)
            {
                return 0;
            }
            operand = next->op.arg;
        }
        if (!method_emit(
                buffer, length, limit, (uint16_t)uop, (uint16_t)oparg,
                operand, target))
        {
            return 0;
        }
        method_apply_uop_effect(
            original_uop, (int)oparg, operand, uop_state,
            locals_count, stack_capacity, &uop_stack_depth);
        if (uop == _PUSH_FRAME) {
            PyFunctionObject *func =
                method_lookup_function(tstate->interp, inline_version);
            if (func == NULL) {
                return 0;
            }
            int inlined = method_inline_straight_line(
                tstate, root_code, func, dependencies,
                buffer, length, limit);
            Py_DECREF(func);
            if (inlined <= 0) {
                return inlined;
            }
        }
        if (uop == _METHOD_POP_JUMP_IF_FALSE ||
            uop == _METHOD_POP_JUMP_IF_TRUE ||
            uop == _METHOD_FOR_ITER ||
            uop == _METHOD_ITER_JUMP_LIST ||
            uop == _METHOD_ITER_JUMP_TUPLE ||
            uop == _METHOD_ITER_JUMP_RANGE)
        {
            direct_jump_index = *length - 1;
        }
    }
    if (direct_jump_index >= 0) {
        if (target_block < 0) {
            return 0;
        }
        buffer[direct_jump_index].operand1 = (uint64_t)target_block;
    }
    return 1;
}

static int
method_decode_cfg(
    PyCodeObject *code,
    _Py_CODEUNIT *bytecode,
    _PyMethodInstruction *instructions,
    int *instruction_count,
    int16_t *offset_to_instruction,
    _PyMethodBlock *blocks,
    int *block_count,
    int16_t *instruction_to_block)
{
    int code_size = (int)Py_SIZE(code);
    uint8_t *block_start = PyMem_Calloc((size_t)code_size, 1);
    if (block_start == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    for (int i = 0; i < code_size; i++) {
        offset_to_instruction[i] = -1;
        instruction_to_block[i] = -1;
    }

    int count = 0;
    for (int offset = 0; offset < code_size;) {
        int start = offset;
        uint32_t oparg = 0;
        int opcode;
        do {
            opcode = bytecode[offset].op.code;
            oparg = (oparg << 8) | bytecode[offset].op.arg;
            if (opcode == EXTENDED_ARG) {
                offset++;
                if (offset >= code_size || oparg > UINT16_MAX) {
                    PyMem_Free(block_start);
                    return 0;
                }
            }
        } while (opcode == EXTENDED_ARG);

        if (opcode == ENTER_EXECUTOR) {
            int index = oparg & 255;
            if (code->co_executors == NULL ||
                index >= code->co_executors->size)
            {
                PyMem_Free(block_start);
                return 0;
            }
            _PyExecutorObject *executor = code->co_executors->executors[index];
            opcode = executor->vm_data.opcode;
            oparg = (oparg & ~255U) | executor->vm_data.oparg;
        }
        int deopt = _PyOpcode_Deopt[opcode];
        int next = offset + 1 + _PyOpcode_Caches[deopt];
        if (next > code_size || count > UINT16_MAX || start > UINT16_MAX) {
            PyMem_Free(block_start);
            return 0;
        }
        instructions[count] = (_PyMethodInstruction) {
            .offset = (uint16_t)start,
            .opcode_offset = (uint16_t)offset,
            .next_offset = (uint16_t)next,
            .opcode = (uint16_t)opcode,
            .oparg = oparg,
        };
        offset_to_instruction[start] = (int16_t)count;
        count++;
        offset = next;
    }
    if (count == 0) {
        PyMem_Free(block_start);
        return 0;
    }

    block_start[0] = 1;
    for (int i = 0; i < count; i++) {
        _PyMethodInstruction *mi = &instructions[i];
        int opcode = _PyOpcode_Deopt[mi->opcode];
        int next = mi->next_offset;
        int target = -1;
        if (method_is_conditional_jump(opcode)) {
            if (opcode == FOR_ITER) {
                target = next + (int)mi->oparg + 1;
            }
            else {
                target = next + (int)mi->oparg;
            }
        }
        else if (opcode == JUMP_FORWARD) {
            target = next + (int)mi->oparg;
        }
        else if (opcode == JUMP_BACKWARD ||
                 opcode == JUMP_BACKWARD_NO_INTERRUPT)
        {
            target = next - (int)mi->oparg;
        }
        if (target >= 0) {
            if (target >= code_size || offset_to_instruction[target] < 0) {
                PyMem_Free(block_start);
                return 0;
            }
            block_start[target] = 1;
        }
        if ((method_is_conditional_jump(opcode) ||
             method_is_unconditional_jump(opcode) ||
             opcode == RETURN_VALUE) && next < code_size)
        {
            if (offset_to_instruction[next] < 0) {
                PyMem_Free(block_start);
                return 0;
            }
            block_start[next] = 1;
        }
    }

    int nblocks = 0;
    for (int i = 0; i < count; i++) {
        if (!block_start[instructions[i].offset]) {
            continue;
        }
        if (nblocks > INT16_MAX) {
            PyMem_Free(block_start);
            return 0;
        }
        blocks[nblocks].first = (uint16_t)i;
        if (nblocks > 0) {
            blocks[nblocks - 1].last = (uint16_t)(i - 1);
        }
        nblocks++;
    }
    blocks[nblocks - 1].last = (uint16_t)(count - 1);
    for (int b = 0; b < nblocks; b++) {
        blocks[b].target = -1;
        blocks[b].fallthrough = -1;
        blocks[b].initialized = 0;
        blocks[b].in_queue = 0;
        blocks[b].stack_depth = 0;
        for (int i = blocks[b].first; i <= blocks[b].last; i++) {
            instruction_to_block[i] = (int16_t)b;
        }
    }
    for (int b = 0; b < nblocks; b++) {
        _PyMethodInstruction *mi = &instructions[blocks[b].last];
        int opcode = _PyOpcode_Deopt[mi->opcode];
        int next = mi->next_offset;
        int target = -1;
        if (method_is_conditional_jump(opcode)) {
            blocks[b].terminator = METHOD_BRANCH;
            target = opcode == FOR_ITER
                ? next + (int)mi->oparg + 1
                : next + (int)mi->oparg;
        }
        else if (method_is_unconditional_jump(opcode)) {
            blocks[b].terminator = METHOD_JUMP;
            target = opcode == JUMP_FORWARD
                ? next + (int)mi->oparg
                : next - (int)mi->oparg;
        }
        else if (opcode == RETURN_VALUE) {
            blocks[b].terminator = METHOD_RETURN;
        }
        else {
            blocks[b].terminator = METHOD_FALLTHROUGH;
        }
        if (target >= 0) {
            int target_instr = offset_to_instruction[target];
            blocks[b].target = instruction_to_block[target_instr];
        }
        if ((blocks[b].terminator == METHOD_BRANCH ||
             blocks[b].terminator == METHOD_FALLTHROUGH) && next < code_size)
        {
            int next_instr = offset_to_instruction[next];
            blocks[b].fallthrough = instruction_to_block[next_instr];
        }
    }
    PyMem_Free(block_start);
    *instruction_count = count;
    *block_count = nblocks;
    return 1;
}

static int
method_analyze_cfg(
    PyCodeObject *code,
    const _PyMethodInstruction *instructions,
    _PyMethodBlock *blocks,
    int block_count,
    _PyMethodValue *states,
    int state_width,
    int locals_count,
    int stack_capacity)
{
    int *queue = PyMem_Calloc((size_t)block_count, sizeof(*queue));
    _PyMethodValue *fallthrough = PyMem_Calloc(
        (size_t)state_width, sizeof(*fallthrough));
    _PyMethodValue *jump = PyMem_Calloc(
        (size_t)state_width, sizeof(*jump));
    if (queue == NULL || fallthrough == NULL || jump == NULL) {
        PyMem_Free(queue);
        PyMem_Free(fallthrough);
        PyMem_Free(jump);
        PyErr_NoMemory();
        return -1;
    }

    _PyMethodValue *entry = states;
    for (int i = 0; i < locals_count; i++) {
        entry[i] = method_value_unknown();
    }
    blocks[0].initialized = 1;
    blocks[0].in_queue = 1;
    blocks[0].stack_depth = 0;
    int head = 0;
    int tail = 0;
    int count = 1;
    queue[tail++] = 0;
    Py_ssize_t visits = 0;
    Py_ssize_t max_visits =
        (Py_ssize_t)block_count * ((Py_ssize_t)state_width * 2 + 1);

    while (count > 0) {
        int block_index = queue[head++];
        if (head == block_count) {
            head = 0;
        }
        count--;
        _PyMethodBlock *block = &blocks[block_index];
        block->in_queue = 0;
        _PyMethodValue *input = states + block_index * state_width;
        memcpy(fallthrough, input, (size_t)state_width * sizeof(*input));
        int fallthrough_depth = block->stack_depth;

        if (++visits > max_visits) {
            PyMem_Free(queue);
            PyMem_Free(fallthrough);
            PyMem_Free(jump);
            return 0;
        }

        for (int i = block->first; i <= block->last; i++) {
            const _PyMethodInstruction *mi = &instructions[i];
            bool last = i == block->last;
            int opcode = _PyOpcode_Deopt[mi->opcode];
            if (last && block->terminator == METHOD_BRANCH &&
                opcode == FOR_ITER)
            {
                if (block->target < 0 || block->fallthrough < 0) {
                    PyMem_Free(queue);
                    PyMem_Free(fallthrough);
                    PyMem_Free(jump);
                    return 0;
                }
                memcpy(jump, fallthrough,
                       (size_t)state_width * sizeof(*jump));
                int jump_depth = fallthrough_depth;
                if (!method_apply_stack_effect(
                        code, mi, jump, locals_count, stack_capacity,
                        &jump_depth, true) ||
                    !method_apply_stack_effect(
                        code, mi, fallthrough, locals_count, stack_capacity,
                        &fallthrough_depth, false))
                {
                    PyMem_Free(queue);
                    PyMem_Free(fallthrough);
                    PyMem_Free(jump);
                    return 0;
                }
                int changed = method_merge_block(
                    &blocks[block->target],
                    states + block->target * state_width,
                    jump, locals_count, stack_capacity, jump_depth);
                if (changed < 0) {
                    PyMem_Free(queue);
                    PyMem_Free(fallthrough);
                    PyMem_Free(jump);
                    return 0;
                }
                if (changed) {
                    if (!blocks[block->target].in_queue) {
                        queue[tail++] = block->target;
                        if (tail == block_count) {
                            tail = 0;
                        }
                        blocks[block->target].in_queue = 1;
                        count++;
                    }
                }
                changed = method_merge_block(
                    &blocks[block->fallthrough],
                    states + block->fallthrough * state_width,
                    fallthrough, locals_count, stack_capacity,
                    fallthrough_depth);
                if (changed < 0) {
                    PyMem_Free(queue);
                    PyMem_Free(fallthrough);
                    PyMem_Free(jump);
                    return 0;
                }
                if (changed) {
                    if (!blocks[block->fallthrough].in_queue) {
                        queue[tail++] = block->fallthrough;
                        if (tail == block_count) {
                            tail = 0;
                        }
                        blocks[block->fallthrough].in_queue = 1;
                        count++;
                    }
                }
                goto next_block;
            }
            if (!method_apply_stack_effect(
                    code, mi, fallthrough, locals_count, stack_capacity,
                    &fallthrough_depth, false))
            {
                PyMem_Free(queue);
                PyMem_Free(fallthrough);
                PyMem_Free(jump);
                return 0;
            }
        }

        {
            int successors[2] = {-1, -1};
            if (block->terminator == METHOD_BRANCH) {
                successors[0] = block->target;
                successors[1] = block->fallthrough;
            }
            else if (block->terminator == METHOD_JUMP) {
                successors[0] = block->target;
            }
            else if (block->terminator == METHOD_FALLTHROUGH) {
                successors[0] = block->fallthrough;
            }
            for (int i = 0; i < 2; i++) {
                int successor = successors[i];
                if (successor < 0) {
                    continue;
                }
                int changed = method_merge_block(
                    &blocks[successor], states + successor * state_width,
                    fallthrough, locals_count, stack_capacity,
                    fallthrough_depth);
                if (changed < 0) {
                    PyMem_Free(queue);
                    PyMem_Free(fallthrough);
                    PyMem_Free(jump);
                    return 0;
                }
                if (changed) {
                    if (!blocks[successor].in_queue) {
                        queue[tail++] = successor;
                        if (tail == block_count) {
                            tail = 0;
                        }
                        blocks[successor].in_queue = 1;
                        count++;
                    }
                }
            }
        }

next_block:
        ;
    }

    PyMem_Free(queue);
    PyMem_Free(fallthrough);
    PyMem_Free(jump);
    return 1;
}

static int
method_inline_straight_line(
    PyThreadState *tstate,
    PyCodeObject *root_code,
    PyFunctionObject *func,
    _PyBloomFilter *dependencies,
    _PyUOpInstruction *buffer,
    int *length,
    int limit)
{
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    if (func->vectorcall != _PyFunction_Vectorcall || code == root_code ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_GENERATOR | CO_COROUTINE |
                           CO_ASYNC_GENERATOR | CO_VARARGS |
                           CO_VARKEYWORDS)) ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        Py_SIZE(code) <= 0 || Py_SIZE(code) > METHOD_INLINE_MAX_CODE_SIZE)
    {
        return 0;
    }

    int start_length = *length;
    size_t code_size = (size_t)Py_SIZE(code);
    _PyMethodInstruction *instructions = PyMem_Calloc(
        code_size, sizeof(*instructions));
    _PyMethodBlock *blocks = PyMem_Calloc(code_size, sizeof(*blocks));
    int16_t *offset_to_instruction = PyMem_Calloc(
        code_size, sizeof(*offset_to_instruction));
    int16_t *instruction_to_block = PyMem_Calloc(
        code_size, sizeof(*instruction_to_block));
    _PyMethodValue *state = NULL;
    _PyMethodValue *uop_state = NULL;
    if (instructions == NULL || blocks == NULL ||
        offset_to_instruction == NULL || instruction_to_block == NULL)
    {
        PyErr_NoMemory();
        goto error;
    }

    _Py_CODEUNIT *bytecode = _PyCode_CODE(code);
    int instruction_count = 0;
    int block_count = 0;
    int decoded = method_decode_cfg(
        code, bytecode, instructions, &instruction_count,
        offset_to_instruction, blocks, &block_count,
        instruction_to_block);
    if (decoded < 0) {
        goto error;
    }
    if (decoded == 0 || block_count != 1 ||
        blocks[0].terminator != METHOD_RETURN ||
        _PyOpcode_Deopt[instructions[0].opcode] != RESUME)
    {
        goto unsupported;
    }

    int locals_count = code->co_nlocalsplus;
    int stack_capacity = code->co_stacksize;
    int state_width = locals_count + stack_capacity;
    if (state_width <= 0) {
        goto unsupported;
    }
    state = PyMem_Calloc((size_t)state_width, sizeof(*state));
    uop_state = PyMem_Calloc((size_t)state_width, sizeof(*uop_state));
    if (state == NULL || uop_state == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    int stack_depth = 0;
    _PyMethodBlock *block = &blocks[0];
    for (int i = block->first; i <= block->last; i++) {
        _PyMethodInstruction *mi = &instructions[i];
        if (i == block->last) {
            if (!method_emit(buffer, length, limit, _SET_IP, 0,
                             (uintptr_t)(bytecode + mi->offset), mi->offset) ||
                !method_emit(buffer, length, limit, _MAKE_HEAP_SAFE,
                             0, 0, mi->offset) ||
                !method_emit(buffer, length, limit, _RETURN_VALUE,
                             0, 0, mi->offset))
            {
                goto unsupported;
            }
            break;
        }
        int translated = method_translate_instruction(
            tstate, root_code, dependencies, false,
            code, bytecode, mi, -1,
            state, locals_count, stack_depth, stack_capacity, uop_state,
            buffer, length, limit);
        if (translated < 0) {
            goto error;
        }
        if (translated == 0 ||
            !method_apply_stack_effect(
                code, mi, state, locals_count, stack_capacity,
                &stack_depth, false))
        {
            goto unsupported;
        }
    }
    _Py_BloomFilter_Add(dependencies, func);
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 1;

unsupported:
    *length = start_length;
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 0;

error:
    *length = start_length;
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return -1;
}

static int
method_finish_uops(
    _PyUOpInstruction *input,
    int input_length,
    _PyUOpInstruction *output,
    uint16_t *offset_map,
    const _PyMethodBlock *blocks,
    int block_count)
{
    for (int pc = 0; pc < input_length; pc++) {
        int opcode = input[pc].opcode;
        int oparg = input[pc].oparg;
        if (oparg < _PyUop_Replication[opcode].stop &&
            oparg >= _PyUop_Replication[opcode].start)
        {
            input[pc].opcode = opcode + oparg + 1 -
                _PyUop_Replication[opcode].start;
        }
    }
    int length = stack_allocate(input, output, input_length, offset_map);
    if (length < 0 || length >= UOP_MAX_TRACE_LENGTH) {
        return 0;
    }
    int spare = length;
    for (int i = 0; i < length; i++) {
        int opcode = _PyUop_Uncached[output[i].opcode];
        uint16_t flags = _PyUop_Flags[opcode];
        spare += !!(flags & (HAS_EXIT_FLAG | HAS_DEOPT_FLAG | HAS_PERIODIC_FLAG));
        spare += !!(flags & HAS_ERROR_FLAG);
    }
    if (spare >= UOP_MAX_TRACE_LENGTH) {
        return 0;
    }
    length = prepare_for_execution(output, length);
    for (int i = 0; i < length; i++) {
        int opcode = _PyUop_Uncached[output[i].opcode];
        if (opcode != _METHOD_POP_JUMP_IF_FALSE &&
            opcode != _METHOD_POP_JUMP_IF_TRUE &&
            opcode != _METHOD_JUMP &&
            opcode != _METHOD_FOR_ITER &&
            opcode != _METHOD_ITER_JUMP_LIST &&
            opcode != _METHOD_ITER_JUMP_TUPLE &&
            opcode != _METHOD_ITER_JUMP_RANGE)
        {
            continue;
        }
        int target_block = (int)output[i].operand1;
        if (target_block < 0 || target_block >= block_count) {
            return 0;
        }
        int input_target = blocks[target_block].uop_offset;
        if (input_target < 0 || input_target >= input_length) {
            return 0;
        }
        output[i].jump_target = offset_map[input_target];
        output[i].format = UOP_FORMAT_JUMP;
        output[i].operand1 = 0;
    }
    return length;
}

int
_PyJit_CompileMethod(PyThreadState *tstate, _PyInterpreterFrame *frame)
{
    PyInterpreterState *interp = tstate->interp;
    if (!FT_ATOMIC_LOAD_UINT8(interp->jit) || interp->compiling) {
        return 0;
    }
    PyCodeObject *code = _PyFrame_GetCode(frame);
    if ((code->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR)) ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        Py_SIZE(code) <= 0 || Py_SIZE(code) > INT16_MAX)
    {
        return 0;
    }
    _Py_CODEUNIT *bytecode = _PyCode_CODE(code);
    _Py_CODEUNIT *entry = bytecode;
    if (entry->op.code == ENTER_EXECUTOR) {
        return 1;
    }
    if (_PyOpcode_Deopt[entry->op.code] != RESUME) {
        return 0;
    }
    if (!has_space_for_executor(code, entry)) {
        return 0;
    }

    size_t code_size = (size_t)Py_SIZE(code);
    _PyMethodInstruction *instructions = PyMem_Calloc(
        code_size, sizeof(*instructions));
    _PyMethodBlock *blocks = PyMem_Calloc(code_size, sizeof(*blocks));
    int16_t *offset_to_instruction = PyMem_Calloc(
        code_size, sizeof(*offset_to_instruction));
    int16_t *instruction_to_block = PyMem_Calloc(
        code_size, sizeof(*instruction_to_block));
    _PyUOpInstruction *input = PyMem_Calloc(
        UOP_MAX_TRACE_LENGTH, sizeof(*input));
    _PyUOpInstruction *output = PyMem_Calloc(
        UOP_MAX_TRACE_LENGTH, sizeof(*output));
    uint16_t *offset_map = PyMem_Calloc(
        UOP_MAX_TRACE_LENGTH, sizeof(*offset_map));
    _PyMethodValue *states = NULL;
    _PyMethodValue *state = NULL;
    _PyMethodValue *uop_state = NULL;
    if (instructions == NULL || blocks == NULL ||
        offset_to_instruction == NULL || instruction_to_block == NULL ||
        input == NULL || output == NULL || offset_map == NULL)
    {
        PyErr_NoMemory();
        goto error;
    }

    int instruction_count = 0;
    int block_count = 0;
    int decoded = method_decode_cfg(
        code, bytecode, instructions, &instruction_count,
        offset_to_instruction, blocks, &block_count,
        instruction_to_block);
    if (decoded <= 0) {
        if (decoded < 0) {
            goto error;
        }
        goto unsupported;
    }
    int locals_count = code->co_nlocalsplus;
    int stack_capacity = code->co_stacksize;
    int state_width = locals_count + stack_capacity;
    if (state_width <= 0 ||
        (size_t)block_count > PY_SSIZE_T_MAX /
            ((size_t)state_width * sizeof(*states)))
    {
        goto unsupported;
    }
    states = PyMem_Calloc(
        (size_t)block_count * state_width, sizeof(*states));
    state = PyMem_Calloc((size_t)state_width, sizeof(*state));
    uop_state = PyMem_Calloc((size_t)state_width, sizeof(*uop_state));
    if (states == NULL || state == NULL || uop_state == NULL) {
        PyErr_NoMemory();
        goto error;
    }
    int analyzed = method_analyze_cfg(
        code, instructions, blocks, block_count, states, state_width,
        locals_count, stack_capacity);
    if (analyzed <= 0) {
        if (analyzed < 0) {
            goto error;
        }
        goto unsupported;
    }

    _PyBloomFilter dependencies;
    _Py_BloomFilter_Init(&dependencies);
    _Py_BloomFilter_Add(&dependencies, code);

    int length = 0;
    int limit = UOP_MAX_TRACE_LENGTH / 2;
    if (!method_emit(
            input, &length, limit, _START_EXECUTOR, 0,
            (uintptr_t)entry, 0) ||
        !method_emit(input, &length, limit, _MAKE_WARM, 0, 0, 0))
    {
        goto unsupported;
    }

    int translated = 0;
    for (int block_index = 0; block_index < block_count; block_index++) {
        _PyMethodBlock *block = &blocks[block_index];
        if (!block->initialized) {
            continue;
        }
        memcpy(state, states + block_index * state_width,
               (size_t)state_width * sizeof(*state));
        int stack_depth = block->stack_depth;
        block->uop_offset = (uint16_t)length;
        bool supported = true;
        for (int i = block->first; i <= block->last; i++) {
            _PyMethodInstruction *mi = &instructions[i];
            int target_block = i == block->last ? block->target : -1;
            int opcode = _PyOpcode_Deopt[mi->opcode];
            if (i == block->last && block->terminator == METHOD_RETURN) {
                if (!method_emit(input, &length, limit, _SET_IP, 0,
                                 (uintptr_t)(bytecode + mi->offset),
                                 mi->offset) ||
                    !method_emit(input, &length, limit, _MAKE_HEAP_SAFE,
                                 0, 0, mi->offset) ||
                    !method_emit(input, &length, limit, _RETURN_VALUE,
                                 0, 0, mi->offset) ||
                    !method_emit(input, &length, limit, _METHOD_EXIT,
                                 0, 0, mi->offset))
                {
                    goto unsupported;
                }
                translated++;
                break;
            }
            if (i == block->last && method_is_unconditional_jump(opcode)) {
                if (opcode != JUMP_BACKWARD_NO_INTERRUPT &&
                    !method_emit(
                        input, &length, limit, _CHECK_PERIODIC, 0, 0,
                        mi->offset))
                {
                    goto unsupported;
                }
                if (!method_emit(
                        input, &length, limit, _METHOD_JUMP, 0, 0,
                        mi->offset))
                {
                    goto unsupported;
                }
                input[length - 1].operand1 = (uint64_t)block->target;
                translated++;
                break;
            }
            int instruction_start = length;
            int instruction_translated = method_translate_instruction(
                    tstate, code, &dependencies, true,
                    code, bytecode, mi, target_block,
                    state, locals_count, stack_depth,
                    stack_capacity, uop_state,
                    input, &length, limit);
            if (instruction_translated <= 0) {
                length = instruction_start;
                if (instruction_translated < 0) {
                    goto error;
                }
                supported = false;
                if (!method_emit(
                        input, &length, limit, _METHOD_DEOPT, 0, 0,
                        mi->offset))
                {
                    goto unsupported;
                }
                break;
            }
            translated++;
            if (!method_apply_stack_effect(
                    code, mi, state, locals_count, stack_capacity,
                    &stack_depth, false))
            {
                goto unsupported;
            }
        }
        if (!supported || block->terminator == METHOD_RETURN) {
            continue;
        }
        if (block->terminator == METHOD_BRANCH ||
            block->terminator == METHOD_FALLTHROUGH)
        {
            if (block->fallthrough < 0 ||
                !method_emit(
                    input, &length, limit, _METHOD_JUMP, 0, 0,
                    instructions[block->last].offset))
            {
                goto unsupported;
            }
            input[length - 1].operand1 = (uint64_t)block->fallthrough;
        }
    }
    if (translated < 2) {
        goto unsupported;
    }

    length = method_finish_uops(
        input, length, output, offset_map, blocks, block_count);
    if (length <= 0) {
        goto unsupported;
    }
    interp->compiling = true;
    _PyExecutorObject *executor = make_executor_from_uops(
        interp, output, length, &dependencies, 0, true);
    interp->compiling = false;
    if (executor == NULL) {
        goto error;
    }
    int index = get_index_for_executor(code, entry);
    if (index < 0) {
        Py_DECREF(executor);
        goto error;
    }
    insert_executor(code, entry, index, executor);
    executor->vm_data.chain_depth = 0;
    Py_DECREF(executor);
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(input);
    PyMem_Free(output);
    PyMem_Free(offset_map);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 1;

unsupported:
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(input);
    PyMem_Free(output);
    PyMem_Free(offset_map);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 0;

error:
    interp->compiling = false;
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(input);
    PyMem_Free(output);
    PyMem_Free(offset_map);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return -1;
}

static int
uop_optimize(
    _PyInterpreterFrame *frame,
    PyThreadState *tstate,
    _PyExecutorObject **exec_ptr,
    bool progress_needed)
{
    _PyThreadStateImpl *_tstate = (_PyThreadStateImpl *)tstate;
    assert(_tstate->jit_tracer_state != NULL);
    _PyUOpInstruction *buffer = _tstate->jit_tracer_state->code_buffer.start;
    OPT_STAT_INC(attempts);
    bool is_noopt = !tstate->interp->opt_config.uops_optimize_enabled;
    int curr_stackentries = _tstate->jit_tracer_state->initial_state.stack_depth;
    int length = uop_buffer_length(&_tstate->jit_tracer_state->code_buffer);
    if (length <= CODE_SIZE_NO_PROGRESS) {
        return 0;
    }
    assert(length > 0);
    assert(length < UOP_MAX_TRACE_LENGTH);
    OPT_STAT_INC(traces_created);

    _PyBloomFilter dependencies;
    _Py_BloomFilter_Init(&dependencies);
    if (!is_noopt) {
        _PyUOpInstruction *output = &_tstate->jit_tracer_state->uop_array[UOP_MAX_TRACE_LENGTH];
        length = _Py_uop_analyze_and_optimize(
            _tstate, buffer, length, curr_stackentries,
            output, &dependencies);

        if (length <= 0) {
            return length;
        }
        buffer = output;
    }
    assert(length < UOP_MAX_TRACE_LENGTH);
    assert(length >= 1);
    /* Fix up */
    for (int pc = 0; pc < length; pc++) {
        int opcode = buffer[pc].opcode;
        int oparg = buffer[pc].oparg;
        if (oparg < _PyUop_Replication[opcode].stop && oparg >= _PyUop_Replication[opcode].start) {
            buffer[pc].opcode = opcode + oparg + 1 - _PyUop_Replication[opcode].start;
            assert(strncmp(_PyOpcode_uop_name[buffer[pc].opcode], _PyOpcode_uop_name[opcode], strlen(_PyOpcode_uop_name[opcode])) == 0);
        }
        else if (_PyUop_Flags[opcode] & HAS_RECORDS_VALUE_FLAG) {
            Py_XDECREF((PyObject *)(uintptr_t)buffer[pc].operand0);
            buffer[pc].opcode = _NOP;
        }
        else if (is_terminator(&buffer[pc])) {
            break;
        }
        assert(_PyOpcode_uop_name[buffer[pc].opcode]);
    }
    // We've cleaned up the references in the buffer, so discard the code buffer
    // to avoid doing it again during tracer cleanup
    _PyJitUopBuffer *code_buffer = &_tstate->jit_tracer_state->code_buffer;
    code_buffer->next = code_buffer->start;

    OPT_HIST(effective_trace_length(buffer, length), optimized_trace_length_hist);
    _PyUOpInstruction *output = &_tstate->jit_tracer_state->uop_array[0];
    length = stack_allocate(buffer, output, length, NULL);
    buffer = output;
    length = prepare_for_execution(buffer, length);
    assert(length <= UOP_MAX_TRACE_LENGTH);
    _PyExecutorObject *executor = make_executor_from_uops(
        tstate->interp, buffer, length, &dependencies,
        _tstate->jit_tracer_state->initial_state.chain_depth, false);
    if (executor == NULL) {
        return -1;
    }
    assert(length <= UOP_MAX_TRACE_LENGTH);

    // Check executor coldness
    // It's okay if this ends up going negative.
    if (--tstate->interp->executor_creation_counter == 0) {
        _Py_set_eval_breaker_bit(tstate, _PY_EVAL_JIT_INVALIDATE_COLD_BIT);
    }

    *exec_ptr = executor;
    return 1;
}


/*****************************************
 *        Executor management
 ****************************************/

static int
link_executor(_PyExecutorObject *executor, const _PyBloomFilter *bloom)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->executor_count == interp->executor_capacity) {
        size_t new_cap = interp->executor_capacity ? interp->executor_capacity * 2 : 64;
        _PyBloomFilter *new_blooms = PyMem_Realloc(
            interp->executor_blooms, new_cap * sizeof(_PyBloomFilter));
        if (new_blooms == NULL) {
            return -1;
        }
        _PyExecutorObject **new_ptrs = PyMem_Realloc(
            interp->executor_ptrs, new_cap * sizeof(_PyExecutorObject *));
        if (new_ptrs == NULL) {
            /* Revert blooms realloc — the old pointer may have been freed by
             * a successful realloc, but new_blooms is the valid pointer. */
            interp->executor_blooms = new_blooms;
            return -1;
        }
        interp->executor_blooms = new_blooms;
        interp->executor_ptrs = new_ptrs;
        interp->executor_capacity = new_cap;
    }
    size_t idx = interp->executor_count++;
    interp->executor_blooms[idx] = *bloom;
    interp->executor_ptrs[idx] = executor;
    executor->vm_data.bloom_array_idx = (int32_t)idx;
    return 0;
}

static void
unlink_executor(_PyExecutorObject *executor)
{
    PyInterpreterState *interp = PyInterpreterState_Get();
    int32_t idx = executor->vm_data.bloom_array_idx;
    assert(idx >= 0 && (size_t)idx < interp->executor_count);
    size_t last = --interp->executor_count;
    if ((size_t)idx != last) {
        /* Swap-remove: move the last element into the vacated slot */
        interp->executor_blooms[idx] = interp->executor_blooms[last];
        interp->executor_ptrs[idx] = interp->executor_ptrs[last];
        interp->executor_ptrs[idx]->vm_data.bloom_array_idx = idx;
    }
    executor->vm_data.bloom_array_idx = -1;
}

/* This must be called by optimizers before using the executor */
int
_Py_ExecutorInit(_PyExecutorObject *executor, const _PyBloomFilter *dependency_set)
{
    FT_ATOMIC_STORE_UINT8(executor->vm_data.valid, true);
    executor->vm_data.is_method = false;
    executor->vm_data.pending_deletion = 0;
    executor->vm_data.code = NULL;
    if (link_executor(executor, dependency_set) < 0) {
        return -1;
    }
    return 0;
}

static _PyExecutorObject *
make_cold_executor(uint16_t opcode)
{
    _PyExecutorObject *cold = allocate_executor(0, 1);
    if (cold == NULL) {
        Py_FatalError("Cannot allocate core JIT code");
    }
    ((_PyUOpInstruction *)cold->trace)->opcode = opcode;
    // Cold executors bypass _Py_ExecutorInit().
    FT_ATOMIC_STORE_UINT8(cold->vm_data.valid, true);
    cold->vm_data.is_method = false;
    cold->vm_data.pending_deletion = 0;
    cold->vm_data.code = NULL;

    // This is initialized to false so we can prevent the executor
    // from being immediately detected as cold and invalidated.
    cold->vm_data.cold = false;
#ifdef _Py_JIT
    cold->jit_code = NULL;
    cold->jit_size = 0;
    if (_PyJIT_Compile(cold, cold->trace, 1)) {
        _PyExecutor_Free(cold);
        Py_FatalError("Cannot allocate core JIT code");
    }
#endif
    _Py_SetImmortal((PyObject *)cold);
    return cold;
}

_PyExecutorObject *
_PyExecutor_GetColdExecutor(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->cold_executor == NULL) {
        return interp->cold_executor = make_cold_executor(_COLD_EXIT_r00);;
    }
    return interp->cold_executor;
}

_PyExecutorObject *
_PyExecutor_GetColdDynamicExecutor(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->cold_dynamic_executor == NULL) {
        interp->cold_dynamic_executor = make_cold_executor(_COLD_DYNAMIC_EXIT_r00);
    }
    return interp->cold_dynamic_executor;
}

void
_PyExecutor_ClearExit(_PyExitData *exit)
{
    if (exit == NULL) {
        return;
    }
    _PyExecutorObject *old = exit->executor;
    if (exit->is_dynamic) {
        exit->executor = _PyExecutor_GetColdDynamicExecutor();
    }
    else {
        exit->executor = _PyExecutor_GetColdExecutor();
    }
    Py_DECREF(old);
}

/* Detaches the executor from the code object (if any) that
 * holds a reference to it */
void
_Py_ExecutorDetach(_PyExecutorObject *executor)
{
    PyCodeObject *code = executor->vm_data.code;
    if (code == NULL) {
        return;
    }
    _Py_CODEUNIT *instruction = &_PyCode_CODE(code)[executor->vm_data.index];
    assert(instruction->op.code == ENTER_EXECUTOR);
    int index = instruction->op.arg;
    assert(code->co_executors->executors[index] == executor);
    instruction->op.code = _PyOpcode_Deopt[executor->vm_data.opcode];
    instruction->op.arg = executor->vm_data.oparg;
    executor->vm_data.code = NULL;
    code->co_executors->executors[index] = NULL;
    Py_DECREF(executor);
}

/* Executors can be invalidated at any time,
   even with a stop-the-world lock held.
   Consequently it must not run arbitrary code,
   including Py_DECREF with a non-executor. */
static void
executor_invalidate(PyObject *op)
{
    _PyExecutorObject *executor = _PyExecutorObject_CAST(op);
    if (!FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid)) {
        return;
    }
    FT_ATOMIC_STORE_UINT8(executor->vm_data.valid, 0);
    unlink_executor(executor);
    executor_clear_exits(executor);
    _Py_ExecutorDetach(executor);
    _PyObject_GC_UNTRACK(op);
}

static int
executor_clear(PyObject *op)
{
    executor_invalidate(op);
    return 0;
}

void
_Py_Executor_DependsOn(_PyExecutorObject *executor, void *obj)
{
    assert(FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid));
    PyInterpreterState *interp = _PyInterpreterState_GET();
    int32_t idx = executor->vm_data.bloom_array_idx;
    assert(idx >= 0 && (size_t)idx < interp->executor_count);
    _Py_BloomFilter_Add(&interp->executor_blooms[idx], obj);
}

/* Invalidate all executors that depend on `obj`
 * May cause other executors to be invalidated as well.
 * Uses contiguous bloom filter array for cache-friendly scanning.
 */
static void
invalidate_dependencies(
    PyInterpreterState *interp,
    const _PyBloomFilter *filter,
    const _PyBloomFilter *other,
    int is_invalidation)
{
    /* Scan contiguous bloom filter array */
    PyObject *invalidate = PyList_New(0);
    if (invalidate == NULL) {
        goto error;
    }
    /* Clearing an executor can clear others, so we need to make a list of
     * executors to invalidate first */
    for (size_t i = 0; i < interp->executor_count; i++) {
        assert(FT_ATOMIC_LOAD_UINT8(
            interp->executor_ptrs[i]->vm_data.valid));
        if ((bloom_filter_may_contain(&interp->executor_blooms[i], filter) ||
             (other != NULL &&
              bloom_filter_may_contain(&interp->executor_blooms[i], other))) &&
            PyList_Append(invalidate, (PyObject *)interp->executor_ptrs[i]))
        {
            goto error;
        }
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(invalidate); i++) {
        PyObject *exec = PyList_GET_ITEM(invalidate, i);
        executor_invalidate(exec);
        if (is_invalidation) {
            OPT_STAT_INC(executors_invalidated);
        }
    }
    Py_DECREF(invalidate);
    return;
error:
    PyErr_Clear();
    Py_XDECREF(invalidate);
    // If we're truly out of memory, wiping out everything is a fine fallback:
    _Py_Executors_InvalidateAll(interp, is_invalidation);
}

void
_Py_Executors_InvalidateDependency(
    PyInterpreterState *interp, void *obj, int is_invalidation)
{
    _PyBloomFilter filter;
    _Py_BloomFilter_Init(&filter);
    _Py_BloomFilter_Add(&filter, obj);
    invalidate_dependencies(interp, &filter, NULL, is_invalidation);
}

bool
_Py_Executors_InvalidateGlobalDependency(
    PyInterpreterState *interp,
    void *dict,
    Py_hash_t key_hash,
    bool value_only)
{
    _PyBloomFilter legacy;
    _PyBloomFilter changed;
    _PyBloomFilter structure;
    _Py_BloomFilter_Init(&legacy);
    _Py_BloomFilter_Init(&changed);
    _Py_BloomFilter_Init(&structure);
    _Py_BloomFilter_Add(&legacy, dict);
    _Py_BloomFilter_AddGlobal(
        &changed, dict, value_only ? key_hash : 0, !value_only);
    _Py_BloomFilter_AddGlobal(&structure, dict, 0, true);
    invalidate_dependencies(interp, &legacy, &changed, 1);
    for (size_t i = 0; i < interp->executor_count; i++) {
        if (bloom_filter_may_contain(
                &interp->executor_blooms[i], &structure))
        {
            return true;
        }
    }
    return false;
}

/* Invalidate all executors */
void
_Py_Executors_InvalidateAll(PyInterpreterState *interp, int is_invalidation)
{
    while (interp->executor_count > 0) {
        /* Invalidate from the end to avoid repeated swap-remove shifts */
        _PyExecutorObject *executor = interp->executor_ptrs[interp->executor_count - 1];
        assert(FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid));
        if (executor->vm_data.code) {
            // Clear the entire code object so its co_executors array be freed:
            _PyCode_Clear_Executors(executor->vm_data.code);
        }
        else {
            executor_invalidate((PyObject *)executor);
        }
        if (is_invalidation) {
            OPT_STAT_INC(executors_invalidated);
        }
    }
}

void
_Py_Executors_InvalidateCold(PyInterpreterState *interp)
{
    /* Scan contiguous executor array */
    PyObject *invalidate = PyList_New(0);
    if (invalidate == NULL) {
        goto error;
    }

    /* Clearing an executor can deallocate others, so we need to make a list of
     * executors to invalidate first */
    for (size_t i = 0; i < interp->executor_count; i++) {
        _PyExecutorObject *exec = interp->executor_ptrs[i];
        assert(FT_ATOMIC_LOAD_UINT8(exec->vm_data.valid));

        if (exec->vm_data.cold && PyList_Append(invalidate, (PyObject *)exec) < 0) {
            goto error;
        }
        else {
            exec->vm_data.cold = true;
        }
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(invalidate); i++) {
        PyObject *exec = PyList_GET_ITEM(invalidate, i);
        executor_invalidate(exec);
    }
    Py_DECREF(invalidate);
    return;
error:
    PyErr_Clear();
    Py_XDECREF(invalidate);
    // If we're truly out of memory, wiping out everything is a fine fallback
    _Py_Executors_InvalidateAll(interp, 0);
}

#include "record_functions.c.h"

static int
escape_angles(const char *input, Py_ssize_t size, char *buffer) {
    int written = 0;
    for (Py_ssize_t i = 0; i < size; i++) {
        char c = input[i];
        if (c == '<' || c == '>') {
            buffer[written++] = '&';
            buffer[written++] = c == '>' ? 'g' : 'l';
            buffer[written++] = 't';
            buffer[written++] = ';';
        }
        else {
            buffer[written++] = c;
        }
    }
    return written;
}

static void
write_str(PyObject *str, FILE *out)
{
    // Encode the Unicode object to the specified encoding
    PyObject *encoded_obj = PyUnicode_AsEncodedString(str, "utf8", "strict");
    if (encoded_obj == NULL) {
        PyErr_Clear();
        return;
    }
    const char *encoded_str = PyBytes_AsString(encoded_obj);
    Py_ssize_t encoded_size = PyBytes_Size(encoded_obj);
    char buffer[120];
    bool truncated = false;
    if (encoded_size > 24) {
        encoded_size = 24;
        truncated = true;
    }
    int size = escape_angles(encoded_str, encoded_size, buffer);
    fwrite(buffer, 1, size, out);
    if (truncated) {
        fwrite("...", 1, 3, out);
    }
    Py_DECREF(encoded_obj);
}

static int
find_line_number(PyCodeObject *code, _PyExecutorObject *executor)
{
    int code_len = (int)Py_SIZE(code);
    for (int i = 0; i < code_len; i++) {
        _Py_CODEUNIT *instr = &_PyCode_CODE(code)[i];
        int opcode = instr->op.code;
        if (opcode == ENTER_EXECUTOR) {
            _PyExecutorObject *exec = code->co_executors->executors[instr->op.arg];
            if (exec == executor) {
                return PyCode_Addr2Line(code, i*2);
            }
        }
        i += _PyOpcode_Caches[_Py_GetBaseCodeUnit(code, i).op.code];
    }
    return -1;
}

#define RED "#ff0000"
#define WHITE "#ffffff"
#define BLUE "#0000ff"
#define BLACK "#000000"
#define LOOP "#00c000"

#ifdef Py_STATS

static const char *COLORS[10] = {
    "9",
    "8",
    "7",
    "6",
    "5",
    "4",
    "3",
    "2",
    "1",
    WHITE,
};
const char *
get_background_color(_PyUOpInstruction const *inst, uint64_t max_hotness)
{
    uint64_t hotness = inst->execution_count;
    int index = (hotness * 10)/max_hotness;
    if (index > 9) {
        index = 9;
    }
    if (index < 0) {
        index = 0;
    }
    return COLORS[index];
}

const char *
get_foreground_color(_PyUOpInstruction const *inst, uint64_t max_hotness)
{
    if(_PyUop_Uncached[inst->opcode] == _DEOPT) {
        return RED;
    }
    uint64_t hotness = inst->execution_count;
    int index = (hotness * 10)/max_hotness;
    if (index > 3) {
        return BLACK;
    }
    return WHITE;
}
#endif

static void
write_row_for_uop(_PyExecutorObject *executor, uint32_t i, FILE *out)
{
    /* Write row for uop.
        * The `port` is a marker so that outgoing edges can
        * be placed correctly. If a row is marked `port=17`,
        * then the outgoing edge is `{EXEC_NAME}:17 -> {TARGET}`
        * https://graphviz.readthedocs.io/en/stable/manual.html#node-ports-compass
        */
    _PyUOpInstruction const *inst = &executor->trace[i];
    const char *opname = _PyOpcode_uop_name[inst->opcode];
#ifdef Py_STATS
    const char *bg_color = get_background_color(inst, executor->trace[0].execution_count);
    const char *color = get_foreground_color(inst, executor->trace[0].execution_count);
    fprintf(out, "        <tr><td port=\"i%d\" border=\"1\" color=\"%s\" bgcolor=\"%s\" ><font color=\"%s\"> %s [%d]&nbsp;--&nbsp; %" PRIu64 "</font></td></tr>\n",
        i, color, bg_color, color, opname, inst->fitness, inst->execution_count);
#else
    const char *color = (_PyUop_Uncached[inst->opcode] == _DEOPT) ? RED : BLACK;
    fprintf(out, "        <tr><td port=\"i%d\" border=\"1\" color=\"%s\" >%s op0=%" PRIu64 "</td></tr>\n", i, color, opname, inst->operand0);
#endif
}

static bool
is_stop(_PyUOpInstruction const *inst)
{
    uint16_t base_opcode = _PyUop_Uncached[inst->opcode];
    return (base_opcode == _EXIT_TRACE || base_opcode == _DEOPT || base_opcode == _JUMP_TO_TOP);
}


/* Writes the node and outgoing edges for a single tracelet in graphviz format.
 * Each tracelet is presented as a table of the uops it contains.
 * If Py_STATS is enabled, execution counts are included.
 *
 * https://graphviz.readthedocs.io/en/stable/manual.html
 * https://graphviz.org/gallery/
 */
static void
executor_to_gv(_PyExecutorObject *executor, FILE *out)
{
    PyCodeObject *code = executor->vm_data.code;
    fprintf(out, "executor_%p [\n", executor);
    fprintf(out, "    shape = none\n");

    /* Write the HTML table for the uops */
    fprintf(out, "    label = <<table border=\"0\" cellspacing=\"0\">\n");
    fprintf(out, "        <tr><td port=\"start\" border=\"1\" ><b>Executor</b></td></tr>\n");
    if (code == NULL) {
        fprintf(out, "        <tr><td border=\"1\" >No code object</td></tr>\n");
    }
    else {
        fprintf(out, "        <tr><td  border=\"1\" >");
        write_str(code->co_qualname, out);
        int line = find_line_number(code, executor);
        fprintf(out, ": %d</td></tr>\n", line);
    }
    for (uint32_t i = 0; i < executor->code_size; i++) {
        write_row_for_uop(executor, i, out);
        if (is_stop(&executor->trace[i])) {
            break;
        }
    }
    fprintf(out, "    </table>>\n");
    fprintf(out, "]\n\n");

    /* Write all the outgoing edges */
    _PyExecutorObject *cold = _PyExecutor_GetColdExecutor();
    _PyExecutorObject *cold_dynamic = _PyExecutor_GetColdDynamicExecutor();
    for (uint32_t i = 0; i < executor->code_size; i++) {
        _PyUOpInstruction const *inst = &executor->trace[i];
        uint16_t base_opcode = _PyUop_Uncached[inst->opcode];
        uint16_t flags = _PyUop_Flags[base_opcode];
        _PyExitData *exit = NULL;
        if (base_opcode == _JUMP_TO_TOP) {
            fprintf(out, "executor_%p:i%d -> executor_%p:i%d [color = \"" LOOP "\"]\n", executor, i, executor, inst->jump_target);
            break;
        }
        if (base_opcode == _EXIT_TRACE) {
            exit = (_PyExitData *)inst->operand0;
        }
        else if (flags & HAS_EXIT_FLAG) {
            assert(inst->format == UOP_FORMAT_JUMP);
            _PyUOpInstruction const *exit_inst = &executor->trace[inst->jump_target];
            uint16_t base_exit_opcode = _PyUop_Uncached[exit_inst->opcode];
            (void)base_exit_opcode;
            assert(base_exit_opcode == _EXIT_TRACE || base_exit_opcode == _DYNAMIC_EXIT);
            exit = (_PyExitData *)exit_inst->operand0;
        }
        if (exit != NULL) {
            if (exit->executor == cold || exit->executor == cold_dynamic) {
#ifdef Py_STATS
                /* Only mark as have cold exit if it has actually exited */
                uint64_t diff = inst->execution_count - executor->trace[i+1].execution_count;
                if (diff) {
                    fprintf(out, "cold_%p%d [ label = \"%"  PRIu64  "\" shape = ellipse color=\"" BLUE "\" ]\n", executor, i, diff);
                    fprintf(out, "executor_%p:i%d -> cold_%p%d\n", executor, i, executor, i);
                }
#endif
            }
            else {
                fprintf(out, "executor_%p:i%d -> executor_%p:start\n", executor, i, exit->executor);
            }
        }
        if (is_stop(inst)) {
            break;
        }
    }
}

/* Write the graph of all the live tracelets in graphviz format. */
int
_PyDumpExecutors(FILE *out)
{
    fprintf(out, "digraph ideal {\n\n");
    fprintf(out, "    rankdir = \"LR\"\n\n");
    fprintf(out, "    node [colorscheme=greys9]\n");
    PyInterpreterState *interp = PyInterpreterState_Get();
    for (size_t i = 0; i < interp->executor_count; i++) {
        executor_to_gv(interp->executor_ptrs[i], out);
    }
    fprintf(out, "}\n\n");
    return 0;
}

#else

int
_PyJit_IsOnlyStrongReferenceBesidesTracer(PyThreadState *tstate, PyObject *obj)
{
    return 0;
}

int
_PyDumpExecutors(FILE *out)
{
    PyErr_SetString(PyExc_NotImplementedError, "No JIT available");
    return -1;
}

void
_PyExecutor_Free(struct _PyExecutorObject *self)
{
    /* This should never be called */
    Py_UNREACHABLE();
}

#endif /* _Py_TIER2 */
