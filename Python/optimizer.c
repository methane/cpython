#include "Python.h"

#ifdef _Py_TIER2

#include "opcode.h"
#include "pycore_interp.h"
#include "pycore_backoff.h"
#include "pycore_bitutils.h"        // _Py_popcount32()
#include "pycore_ceval.h"       // _Py_set_eval_breaker_bit
#include "pycore_code.h"            // _Py_GetBaseCodeUnit
#include "pycore_dict.h"
#include "pycore_function.h"        // _PyFunction_Vectorcall()
#include "pycore_interpframe.h"
#include "pycore_iterobject.h"    // _PyZip_NextListPair()
#include "pycore_object.h"          // _PyObject_GC_UNTRACK()
#include "pycore_opcode_metadata.h" // _PyOpcode_OpName[]
#include "pycore_opcode_utils.h"  // MAX_REAL_OPCODE
#include "pycore_optimizer.h"     // _Py_uop_optimize_method_block()
#include "pycore_pystate.h"       // _PyInterpreterState_GET()
#include "pycore_tuple.h"         // _PyTuple_FromArraySteal
#include "pycore_typeobject.h"    // _PyType_LookupByVersion()
#include "pycore_unicodeobject.h" // _PyUnicode_FromASCII
#include "pycore_uop_ids.h"
#include "pycore_jit.h"
#include "pycore_jit_call.h"
#include "pycore_long.h"           // _PyLong_GetOne()
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#define NEED_OPCODE_METADATA
#include "pycore_uop_metadata.h" // Uop tables
#undef NEED_OPCODE_METADATA

#define MAX_EXECUTORS_SIZE 256

/* Executor metadata is changed only while this interpreter is stopped.
 * Native execution is thread-local and does not hold a runtime-wide lock.
 * Invalidation also runs inside instrumentation/GC stop-the-world scopes. */
bool
_PyJit_StopTheWorld(PyInterpreterState *interp)
{
#ifdef Py_GIL_DISABLED
    PyThreadState *tstate = _PyThreadState_GET();
    if ((interp->stoptheworld.world_stopped &&
         interp->stoptheworld.requester == tstate) ||
        (interp->runtime->stoptheworld.world_stopped &&
         interp->runtime->stoptheworld.requester == tstate))
    {
        return false;
    }
    _PyEval_StopTheWorld(interp);
    return true;
#else
    return false;
#endif
}

void
_PyJit_StartTheWorld(PyInterpreterState *interp, bool stopped)
{
    if (stopped) {
        _PyEval_StartTheWorld(interp);
    }
}

/* Compilation and executor lookup use the calling thread's specialization.
 * Do not allocate a TLBC here: callees without one are not yet specialized. */
static _Py_CODEUNIT *
method_bytecode(PyCodeObject *code)
{
#ifdef Py_GIL_DISABLED
    _Py_CODEUNIT *bytecode = _PyCode_GetTLBCFast(_PyThreadState_GET(), code);
    if (bytecode != NULL) {
        return bytecode;
    }
#endif
    return _PyCode_CODE(code);
}

static bool method_is_edge(int opcode);

#define _PyExecutorObject_CAST(op)  ((_PyExecutorObject *)(op))

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
    if (code->co_executors->size < MAX_EXECUTORS_SIZE) {
        return true;
    }
    for (int i = 0; i < code->co_executors->size; i++) {
        if (code->co_executors->executors[i] == NULL) {
            return true;
        }
    }
    return false;
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
        for (int i = 0; i < size; i++) {
            if (old->executors[i] == NULL) {
                return i;
            }
        }
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
        if (capacity == 0) {
            memset(new->method_backoff, 0, sizeof(new->method_backoff));
            new->next_method_backoff = 0;
        }
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
    else if (code->co_executors->size == index) {
        assert(code->co_executors->capacity > index);
        code->co_executors->size++;
    }
    else {
        assert(index < code->co_executors->size);
        assert(code->co_executors->executors[index] == NULL);
    }
    executor->vm_data.opcode = instr->op.code;
    executor->vm_data.oparg = instr->op.arg;
    executor->vm_data.code = code;
    executor->vm_data.index = (int)(instr - method_bytecode(code));
    executor->vm_data.bytecode = method_bytecode(code);
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
    const _PyBloomFilter *dependencies);

_Py_CODEUNIT *
_PyJit_CallMethod(PyThreadState *tstate, _PyExecutorObject *caller_executor,
                  _PyInterpreterFrame **frame)
{
    return _PyJit_CallMethodImpl(tstate, caller_executor, frame, _Py_jit_entry);
}

static _PyExecutorObject *
get_executor_lock_held(PyCodeObject *code, int offset)
{
#ifdef Py_GIL_DISABLED
    if (_PyCode_GetTLBCFast(_PyThreadState_GET(), code) == NULL) {
        PyErr_SetString(PyExc_ValueError, "no executor at given byte offset");
        return NULL;
    }
#endif
    int code_len = (int)Py_SIZE(code);
    for (int i = 0 ; i < code_len;) {
        if (method_bytecode(code)[i].op.code == ENTER_EXECUTOR && i*2 == offset) {
            int oparg = method_bytecode(code)[i].op.arg;
            _PyExecutorObject *res = code->co_executors->executors[oparg];
            Py_INCREF(res);
            return res;
        }
        // Specialization does not change instruction widths. The canonical
        // decoder also handles instrumented instructions and executor entries.
        i += _PyInstruction_GetLength(code, i);
    }
    PyErr_SetString(PyExc_ValueError, "no executor at given byte offset");
    return NULL;
}

_PyExecutorObject *
_Py_GetExecutor(PyCodeObject *code, int offset)
{
    _PyExecutorObject *executor;
    PyInterpreterState *interp = _PyInterpreterState_GET();
    bool stopped = _PyJit_StopTheWorld(interp);
    executor = get_executor_lock_held(code, offset);
    _PyJit_StartTheWorld(interp, stopped);
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
_Py_ClearExecutorDeletionList_stopped(PyInterpreterState *interp)
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
        bool deallocating = false;
#ifdef Py_GIL_DISABLED
        HEAD_LOCK(runtime);
        for (PyThreadState *t = PyInterpreterState_ThreadHead(interp);
             t != NULL; t = t->next)
        {
            if (((_PyThreadStateImpl *)t)->jit_deallocating_executor ==
                (PyObject *)exec)
            {
                deallocating = true;
                break;
            }
        }
        HEAD_UNLOCK(runtime);
#endif
        if (Py_REFCNT(exec) == 0 && !deallocating) {
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

void
_Py_ClearExecutorDeletionList(PyInterpreterState *interp)
{
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_ClearExecutorDeletionList_stopped(interp);
    _PyJit_StartTheWorld(interp, stopped);
}

static void
add_to_pending_deletion_list(_PyExecutorObject *self)
{
    if (self->vm_data.pending_deletion) {
        return;
    }
    self->vm_data.pending_deletion = 1;
    PyInterpreterState *interp = self->vm_data.interp;
    self->vm_data.links.previous = NULL;
    self->vm_data.links.next = interp->executor_deletion_list_head;
    interp->executor_deletion_list_head = self;
}

static void
uop_dealloc(PyObject *op) {
    _PyExecutorObject *self = _PyExecutorObject_CAST(op);
#ifdef Py_GIL_DISABLED
    _PyThreadStateImpl *tstate = (_PyThreadStateImpl *)_PyThreadState_GET();
    PyObject *previous = tstate->jit_deallocating_executor;
    tstate->jit_deallocating_executor = op;
#endif
    bool stopped = _PyJit_StopTheWorld(self->vm_data.interp);
    executor_invalidate(op);
    assert(self->vm_data.code == NULL);
    add_to_pending_deletion_list(self);
#ifdef Py_GIL_DISABLED
    tstate->jit_deallocating_executor = previous;
#endif
    _PyJit_StartTheWorld(self->vm_data.interp, stopped);
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
    .tp_basicsize = offsetof(_PyExecutorObject, uops),
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

static int
is_terminator(const _PyUOpInstruction *uop)
{
    int opcode = _PyUop_Uncached[uop->opcode];
    return (
        opcode == _EXIT_TRACE ||
        opcode == _DEOPT ||
        opcode == _JUMP_TO_TOP
    );
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

static void make_exit(_PyUOpInstruction *inst, int opcode, int target)
{
    assert(opcode > MAX_UOP_ID && opcode <= MAX_UOP_REGS_ID);
    inst->opcode = opcode;
    inst->oparg = 0;
    inst->operand0 = 0;
    inst->format = UOP_FORMAT_TARGET;
    inst->target = target;
    inst->operand1 = 0;
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
    uint64_t current_exit_descr = 0;
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
        if (exit_flags && !method_is_edge(base_opcode)) {
            uint16_t base_exit_op = _EXIT_TRACE;
            uint64_t exit_descr = 0;
            if (exit_flags & HAS_DEOPT_FLAG) {
                base_exit_op = _DEOPT;
            }
            else if (exit_flags & HAS_PERIODIC_FLAG) {
                base_exit_op = _HANDLE_PENDING_AND_DEOPT;
            }
            else if (base_opcode == _GUARD_BINARY_OP_EXTEND ||
                     base_opcode == _GUARD_BINARY_OP_EXTEND_LHS ||
                     base_opcode == _GUARD_BINARY_OP_EXTEND_RHS) {
                base_exit_op = _EXIT_BINARY_OP;
                exit_descr = inst->operand0;
            }
            int32_t jump_target = target;
            int exit_depth = get_cached_entries_for_side_exit(inst);
            assert(_PyUop_Caching[base_exit_op].entries[exit_depth].opcode > 0);
            int16_t exit_op = _PyUop_Caching[base_exit_op].entries[exit_depth].opcode;
            if (jump_target != current_jump_target || current_exit_op != exit_op ||
                exit_descr != current_exit_descr) {
                make_exit(&buffer[next_spare], exit_op, jump_target);
                buffer[next_spare].operand0 = exit_descr;
                current_exit_op = exit_op;
                current_exit_descr = exit_descr;
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
            bool region_sets_ip = base_opcode == _UPDATE_INT_ATTRIBUTE ||
                base_opcode == _FLOAT_ATTRIBUTE_SUM_PRODUCTS ||
                base_opcode == _FLOAT_ATTRIBUTE_SUM_PRODUCTS_0 ||
                base_opcode == _FLOAT_ATTRIBUTE_SUM_PRODUCTS_1;
            int32_t error_target = region_sets_ip ? -1 : target;
            if (error_target != current_error_target || popped != current_popped) {
                current_popped = popped;
                current_error = next_spare;
                current_error_target = error_target;
                make_exit(&buffer[next_spare], _ERROR_POP_N_r00, 0);
                buffer[next_spare].operand0 = (uint32_t)error_target;
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
allocate_executor(int length)
{
    int size = length * sizeof(_PyUOpInstruction);
    _PyExecutorObject *res = PyObject_GC_NewVar(_PyExecutorObject, &_PyUOpExecutor_Type, size);
    if (res == NULL) {
        return NULL;
    }
    res->trace = res->uops;
    res->code_size = length;
    res->jit_registration = NULL;
    res->vm_data.interp = _PyInterpreterState_GET();
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
    uint32_t i = 0;
    CHECK(_PyUop_Uncached[executor->trace[0].opcode] == _START_EXECUTOR);
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
            base_opcode == _METHOD_EXIT || base_opcode == _METHOD_YIELD_EXIT ||
            base_opcode == _DEOPT;
    }
    CHECK(has_method_exit);
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
    const _PyBloomFilter *dependencies)
{
    _PyExecutorObject *executor = allocate_executor(length);
    if (executor == NULL) {
        return NULL;
    }

    assert(_PyUop_Uncached[buffer[0].opcode] == _START_EXECUTOR);
    buffer[0].operand0 = (uint64_t)executor;
    memcpy(executor->uops, buffer, length * sizeof(*buffer));
    // Note: we MUST track it here before any Py_DECREF(executor) or
    // linking of executor. Otherwise, the GC tries to untrack a
    // still untracked object during dealloc.
    _PyObject_GC_TRACK(executor);
    if (_Py_ExecutorInit(executor, dependencies) < 0) {
        Py_DECREF(executor);
        return NULL;
    }
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
    if (_PyJIT_Compile(executor, executor->trace, length)) {
        Py_DECREF(executor);
        return NULL;
    }
#endif
    return executor;
}

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
        int uop = buffer[i].opcode;
        if (offset_map != NULL && uop == _METHOD_LABEL) {
            int entry_depth = buffer[i].oparg;
            assert(entry_depth <= 2);
            if (entry_depth != depth) {
                *write++ = (_PyUOpInstruction) {
                    .opcode = _PyUop_SpillsAndReloads[depth][entry_depth],
                    .format = UOP_FORMAT_TARGET,
                };
                depth = entry_depth;
            }
            /* Incoming edges already use the block ABI. Only the linear
             * fallthrough executes the conversion emitted above. */
            offset_map[i] = (uint16_t)(write - output);
            continue;
        }
        if (offset_map != NULL) {
            ptrdiff_t offset = write - output;
            if (offset > UINT16_MAX) {
                return -1;
            }
            offset_map[i] = (uint16_t)offset;
        }
        if (uop == _NOP) {
            continue;
        }
        int new_depth = _PyUop_Caching[uop].best[depth];
        if (offset_map != NULL && method_is_edge(uop)) {
            uint64_t target = buffer[i].operand1;
            assert(target < (uint64_t)length);
            assert(buffer[target].opcode == _METHOD_LABEL);
            new_depth = buffer[target].oparg +
                (uop == _METHOD_POP_JUMP_IF_FALSE ||
                 uop == _METHOD_POP_JUMP_IF_TRUE);
        }
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
 * Method block labels define a common cache depth for incoming edges.
 * stack_allocate() converts each predecessor to that convention and removes
 * the labels. Iterator exhaustion edges retain their two iterator operands.
 */

typedef enum {
    METHOD_FALLTHROUGH,
    METHOD_BRANCH,
    METHOD_JUMP,
    METHOD_RETURN,
    METHOD_RAISE,
    METHOD_SUSPEND,
} _PyMethodTerminator;

typedef struct {
    uint16_t offset;
    uint16_t opcode_offset;
    uint16_t next_offset;
    uint16_t opcode;
    uint32_t oparg;
    uint32_t alternate_versions[3];
    bool dynamic_method;
    uint16_t type_family;
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

static PyTypeObject *
method_value_get_stable_type(_PyMethodValue value)
{
    PyTypeObject *type = method_value_get_type(value);
    if (type != NULL && _Py_IsImmortal(type) &&
        (type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) &&
        !PyType_IsSubtype(type, &PyModule_Type))
    {
        return type;
    }
    /* Module instances may change __class__ even when their current type
     * is immutable. Such a type cannot be retained across an escaping call. */
    return NULL;
}

static bool
method_value_equal(_PyMethodValue left, _PyMethodValue right)
{
    return left.kind == right.kind &&
        left.object == right.object &&
        left.compact_int == right.compact_int &&
        left.unique == right.unique && left.borrowed == right.borrowed &&
        left.origin == right.origin && left.type_version == right.type_version &&
        left.managed_guards == right.managed_guards &&
        left.dynamic_method == right.dynamic_method &&
        left.stack_alias == right.stack_alias &&
        left.type_family == right.type_family;
}

static bool
method_close_cannot_escape(_PyMethodValue value)
{
    if (value.kind == METHOD_VALUE_NULL ||
        (value.kind == METHOD_VALUE_CONST && _Py_IsImmortal(value.object))) {
        return true;
    }
    PyTypeObject *type = method_value_get_type(value);
    return type == &PyLong_Type || type == &PyFloat_Type ||
        type == &PyBool_Type || type == &PyUnicode_Type ||
        type == &PyBytes_Type || type == &_PyNone_Type;
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
method_specialize_cleanup(_PyMethodValue value)
{
    PyTypeObject *type = method_value_get_type(value);
    if (value.kind == METHOD_VALUE_NULL || value.borrowed ||
        (value.kind == METHOD_VALUE_CONST && _Py_IsImmortal(value.object)) ||
        type == &PyBool_Type || type == &_PyNone_Type)
    {
        return _POP_TOP_NOP;
    }
    if (type == &PyLong_Type) {
        return _POP_TOP_INT;
    }
    if (type == &PyFloat_Type) {
        return _POP_TOP_FLOAT;
    }
    if (type == &PyUnicode_Type) {
        return _POP_TOP_UNICODE;
    }
    return _POP_TOP;
}

static bool
method_checked_local_store(int opcode, uint32_t local,
                           const _PyMethodValue *values,
                           int locals_count, int depth)
{
#ifdef Py_GIL_DISABLED
    return false;
#else
    return opcode == STORE_FAST && local < (uint32_t)locals_count && depth > 0 &&
        !method_close_cannot_escape(values[local]) &&
        method_close_cannot_escape(values[locals_count + depth - 1]);
#endif
}

/* Resolve bindings from the function's static namespace. Value changes are
 * covered by named dependencies, and mapping identity guards handle code
 * shared across globals. Free threading only embeds immortal objects. */
static PyObject *
method_global_value(PyFunctionObject *func, PyCodeObject *code,
                       const _PyMethodInstruction *mi)
{
    if (mi->opcode != LOAD_GLOBAL_MODULE && mi->opcode != LOAD_GLOBAL_BUILTIN) {
        return NULL;
    }
    _PyLoadGlobalCache *cache = (_PyLoadGlobalCache *)(
        method_bytecode(code) + mi->opcode_offset + 1);
    PyObject *mapping = func->func_globals;
    if (!PyDict_CheckExact(mapping) ||
        ((PyDictObject *)mapping)->ma_keys->dk_version != cache->module_keys_version) {
        return NULL;
    }
    uint32_t version = cache->module_keys_version;
    if (mi->opcode == LOAD_GLOBAL_BUILTIN) {
        PyInterpreterState *interp = _PyInterpreterState_GET();
        mapping = func->func_builtins;
        if (mapping != interp->builtins ||
            interp->rare_events.builtin_dict >= _Py_MAX_ALLOWED_BUILTINS_MODIFICATIONS) {
            return NULL;
        }
        version = cache->builtin_keys_version;
    }
    PyDictObject *dict = (PyDictObject *)mapping;
    if (!PyDict_CheckExact(mapping) || dict->ma_keys->dk_version != version ||
        dict->ma_keys->dk_kind != DICT_KEYS_UNICODE ||
        cache->index >= dict->ma_keys->dk_nentries) {
        return NULL;
    }
    PyObject *value = DK_UNICODE_ENTRIES(dict->ma_keys)[cache->index].me_value;
    if (mi->opcode == LOAD_GLOBAL_MODULE) {
        PyObject *name = PyTuple_GET_ITEM(code->co_names, mi->oparg >> 1);
        if (_PyJit_IsUnstableGlobal(mapping, PyObject_Hash(name))) {
            return NULL;
        }
    }
    return value;
}

static PyObject *
method_global_constant(PyFunctionObject *func, PyCodeObject *code,
                       const _PyMethodInstruction *mi)
{
    PyObject *value = method_global_value(func, code, mi);
#ifdef Py_GIL_DISABLED
    return value != NULL && _Py_IsImmortal(value) ? value : NULL;
#else
    /* A constant symbol also implies its exact type. A mutable instance can
     * change __class__ without changing its namespace binding, so retain
     * an unknown-type binding load for those objects (including modules). */
    return value != NULL &&
        (Py_TYPE(value)->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) &&
        !PyModule_Check(value) ? value : NULL;
#endif
}

#ifndef Py_GIL_DISABLED
static uint32_t
method_default_instancecheck_version(_PyMethodValue value)
{
    if ((value.kind != METHOD_VALUE_CONST &&
         value.kind != METHOD_VALUE_BINDING_HINT) || !PyType_Check(value.object))
    {
        return 0;
    }
    PyTypeObject *metaclass = Py_TYPE(value.object);
    if (metaclass == &PyType_Type) {
        // The symbolic optimizer already handles ordinary class constants.
        return 0;
    }
    PyObject *checker = _PyType_LookupRef(metaclass, &_Py_ID(__instancecheck__));
    PyObject *default_checker = _PyType_LookupRef(
        &PyType_Type, &_Py_ID(__instancecheck__));
    uint32_t version = checker != NULL && checker == default_checker
        ? metaclass->tp_version_tag : 0;
    Py_XDECREF(checker);
    Py_XDECREF(default_checker);
    // This is only a hint. The emitted operation guards the live metaclass
    // version, including changes to the class object's own __class__.
    return version;
}

static PyObject *
method_module_attribute(PyCodeObject *code, const _PyMethodInstruction *mi,
                        _PyMethodValue owner, PyObject **namespace)
{
    if (mi->opcode != LOAD_ATTR_MODULE ||
        owner.kind != METHOD_VALUE_BINDING_HINT ||
        !PyModule_CheckExact(owner.object))
    {
        return NULL;
    }
    PyDictObject *dict = (PyDictObject *)PyModule_GetDict(owner.object);
    _PyAttrCache *cache = (_PyAttrCache *)(
        method_bytecode(code) + mi->opcode_offset + 1);
    // Never invoke a non-string key's equality method during compilation.
    if (dict->ma_keys->dk_kind != DICT_KEYS_UNICODE ||
        dict->ma_keys->dk_version != read_u32(cache->version) ||
        cache->index >= dict->ma_keys->dk_nentries)
    {
        return NULL;
    }
    *namespace = (PyObject *)dict;
    return DK_UNICODE_ENTRIES(dict->ma_keys)[cache->index].me_value;
}
#endif

static bool
method_is_empty_set_call(int opcode, uint32_t oparg,
                         const _PyMethodValue *values, int locals_count,
                         int depth)
{
    return opcode == CALL_BUILTIN_CLASS && oparg == 0 && depth >= 2 &&
        values[locals_count + depth - 1].kind == METHOD_VALUE_NULL &&
        values[locals_count + depth - 2].kind == METHOD_VALUE_CONST &&
        values[locals_count + depth - 2].object == (PyObject *)&PySet_Type;
}

static PyObject *
method_attribute_default(PyCodeObject *code, const _PyMethodInstruction *mi)
{
#ifdef Py_GIL_DISABLED
    return NULL;
#else
    if (mi->opcode != LOAD_ATTR_INSTANCE_VALUE) {
        return NULL;
    }
    _PyAttrCache *cache = (_PyAttrCache *)(
        method_bytecode(code) + mi->opcode_offset + 1);
    PyTypeObject *type = _PyType_LookupByVersion(read_u32(cache->version));
    if (type == NULL) {
        return NULL;
    }
    PyObject *name = PyTuple_GET_ITEM(code->co_names, mi->oparg >> 1);
    PyObject *value = _PyType_LookupRef(type, name);
    if (value == NULL) {
        return NULL;
    }
    /* The existing type-version guard covers the class binding. Restrict
     * defaults to immortal non-descriptors with immutable types, so neither
     * the pointer nor descriptor behavior can change behind that guard. */
    bool usable = _Py_IsImmortal(value) &&
        (Py_TYPE(value)->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) &&
        Py_TYPE(value)->tp_descr_get == NULL;
    Py_DECREF(value);
    return usable ? value : NULL;
#endif
}

static void
method_forget_local_origin(_PyMethodValue *values, int locals_count,
                            int depth, int local)
{
    for (int i = 0; i < depth; i++) {
        if (values[locals_count + i].origin == local + 1) {
            values[locals_count + i].origin = 0;
        }
    }
}

static PyObject *
method_cached_function(PyCodeObject *code, const _PyMethodInstruction *mi)
{
#ifdef Py_GIL_DISABLED
    return NULL;
#else
    if (mi->dynamic_method || !(mi->oparg & 1) ||
        (mi->opcode != LOAD_ATTR_METHOD_WITH_VALUES &&
         mi->opcode != LOAD_ATTR_METHOD_NO_DICT))
    {
        return NULL;
    }
    _PyLoadMethodCache *cache = (_PyLoadMethodCache *)(
        method_bytecode(code) + mi->opcode_offset + 1);
    PyTypeObject *type = _PyType_LookupByVersion(read_u32(cache->type_version));
    if (type == NULL) {
        return NULL;
    }
    PyObject *name = PyTuple_GET_ITEM(code->co_names, mi->oparg >> 1);
    PyObject *value = _PyType_LookupRef(type, name);
    if (value == NULL) {
        return NULL;
    }
    bool known = PyFunction_Check(value) && value == read_obj(cache->descr);
    Py_DECREF(value);
    /* The guarded descriptor is owned by the type dictionary. A family
     * with distinct overriding descriptors uses dynamic_method instead. */
    return known ? value : NULL;
#endif
}

static void
method_refine_scalar_input(_PyMethodValue *values, int locals_count,
                           int depth, int index, PyTypeObject *type,
                           bool compact)
{
    if (index < 0 || index >= depth) {
        return;
    }
    _PyMethodValue *value = &values[locals_count + index];
    int origin = value->origin;
    if (origin > 0 && origin <= locals_count) {
        /* No store or escaping operation may intervene between the load and
         * its guard. The guard then proves the current local's type too. */
        if (method_value_get_type(values[origin - 1]) != type) {
            values[origin - 1] = method_value_type(type, compact);
        }
        else {
            values[origin - 1].compact_int |= compact;
        }
    }
}

static int
method_apply_stack_effect(
    PyFunctionObject *func,
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

    /* Successful specialized scalar operations guard their operands before
     * doing work. Propagate that proof over CFG edges, without sampling the
     * running frame or assuming an arithmetic result remains compact. */
    PyTypeObject *guarded_scalar = NULL;
    switch (opcode) {
        case BINARY_OP_ADD_INT:
        case BINARY_OP_SUBTRACT_INT:
        case BINARY_OP_MULTIPLY_INT:
        case COMPARE_OP_INT:
            guarded_scalar = &PyLong_Type;
            break;
        case BINARY_OP_ADD_FLOAT:
        case BINARY_OP_SUBTRACT_FLOAT:
        case BINARY_OP_MULTIPLY_FLOAT:
        case COMPARE_OP_FLOAT:
            guarded_scalar = &PyFloat_Type;
            break;
    }
    if (guarded_scalar != NULL) {
        for (int i = *depth - 2; i < *depth; i++) {
            method_refine_scalar_input(values, locals_count, *depth, i,
                                       guarded_scalar, guarded_scalar == &PyLong_Type);
        }
    }
    else if (opcode == TO_BOOL_INT) {
        method_refine_scalar_input(values, locals_count, *depth, *depth - 1,
                                   &PyLong_Type, false);
    }

    bool borrowed_attribute =
        (opcode == LOAD_ATTR_INSTANCE_VALUE ||
         opcode == LOAD_ATTR_INSTANCE_VALUE_NONDATA || opcode == LOAD_ATTR_SLOT) &&
        *depth > 0 && stack[*depth - 1].borrowed;
    bool borrowed_none_test =
        (base_opcode == POP_JUMP_IF_NONE || base_opcode == POP_JUMP_IF_NOT_NONE) &&
        *depth > 0 && stack[*depth - 1].borrowed;
    bool guarded_deref = false;
    bool borrowed_store = false;
#ifndef Py_GIL_DISABLED
    guarded_deref = opcode == LOAD_DEREF;
    borrowed_store = (opcode == STORE_ATTR_INSTANCE_VALUE ||
                      opcode == STORE_ATTR_INSTANCE_VALUE_NONDATA ||
                      opcode == STORE_ATTR_SLOT) &&
        *depth >= 2 && stack[*depth - 1].borrowed;
#endif
    bool safe_pop = opcode == POP_TOP && *depth > 0 &&
        method_close_cannot_escape(stack[*depth - 1]);
    bool safe_store = base_opcode == STORE_FAST &&
        mi->oparg < (uint32_t)locals_count &&
        method_close_cannot_escape(values[mi->oparg]);
    safe_store |= method_checked_local_store(opcode, mi->oparg, values,
                                            locals_count, *depth);
    if (opcode == STORE_FAST_LOAD_FAST && mi->oparg <= UINT8_MAX &&
        (mi->oparg >> 4) < (uint32_t)locals_count) {
        safe_store = method_close_cannot_escape(values[mi->oparg >> 4]);
    }
    if (opcode == STORE_FAST_STORE_FAST && mi->oparg <= UINT8_MAX) {
        uint32_t first = mi->oparg >> 4;
        uint32_t second = mi->oparg & 15;
        safe_store = first != second && first < (uint32_t)locals_count &&
            second < (uint32_t)locals_count &&
            method_close_cannot_escape(values[first]) &&
            method_close_cannot_escape(values[second]);
    }
    // Python calls and indexing transfer to another frame without necessarily
    // having a C-level escaping operation in their macro.
    bool may_escape = OPCODE_HAS_ESCAPES(opcode) ||
        base_opcode == CALL || base_opcode == CALL_KW ||
        opcode == BINARY_OP_SUBSCR_GETITEM || opcode == FOR_ITER_GEN ||
        opcode == LOAD_ATTR_PROPERTY || opcode == LOAD_ATTR_GETATTRIBUTE_OVERRIDDEN;
    if (may_escape && !borrowed_attribute && !borrowed_none_test &&
        !guarded_deref && !safe_store && !safe_pop && !borrowed_store &&
        !(opcode == BUILD_MAP && mi->oparg == 0) &&
        !method_is_empty_set_call(opcode, mi->oparg, values, locals_count, *depth)) {
        for (int i = 0; i < *depth; i++) {
            stack[i].unique = stack[i].borrowed = false;
            stack[i].origin = stack[i].type_version = 0;
            stack[i].type_family = 0;
            stack[i].stack_alias = 0;
            stack[i].managed_guards = 0;
        }
        for (int i = 0; i < locals_count; i++) {
            values[i].type_version = 0;
            values[i].type_family = 0;
            values[i].managed_guards = 0;
        }
    }
    if (borrowed_attribute || borrowed_store) {
        // A borrowed receiver's guarded store either exits before mutation
        // or completes without a callback, preserving its type version.
        int origin = stack[*depth - 1].origin;
        if (origin > 0 && origin <= locals_count) {
            _PyAttrCache *cache = (_PyAttrCache *)(
                method_bytecode(code) + mi->opcode_offset + 1);
            values[origin - 1].type_version = mi->alternate_versions[0]
                ? 0 : read_u32(cache->version);
            values[origin - 1].type_family = mi->type_family;
#ifndef Py_GIL_DISABLED
            if (opcode == STORE_ATTR_INSTANCE_VALUE ||
                opcode == STORE_ATTR_INSTANCE_VALUE_NONDATA)
            {
                values[origin - 1].managed_guards = 3;
            }
            else if (opcode == LOAD_ATTR_INSTANCE_VALUE ||
                     opcode == LOAD_ATTR_INSTANCE_VALUE_NONDATA)
            {
                values[origin - 1].managed_guards |= 1;
            }
#endif
        }
    }

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
        stack[*depth - 2].origin = first + 1;
        stack[*depth - 1].origin = second + 1;
        if (opcode == LOAD_FAST_BORROW_LOAD_FAST_BORROW) {
            stack[*depth - 1].borrowed = stack[*depth - 2].borrowed = true;
        }
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
        method_forget_local_origin(values, locals_count, *depth, store);
        values[store] = stack[--(*depth)];
        values[store].unique = values[store].borrowed = false;
        values[store].origin = 0;
        values[store].stack_alias = 0;
        stack[(*depth)++] = values[load];
        stack[*depth - 1].origin = load + 1;
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
        method_forget_local_origin(values, locals_count, *depth, first);
        method_forget_local_origin(values, locals_count, *depth, second);
        values[first] = stack[*depth - 1];
        values[second] = stack[*depth - 2];
        values[first].unique = values[first].borrowed = false;
        values[second].unique = values[second].borrowed = false;
        values[first].origin = values[second].origin = 0;
        values[first].stack_alias = values[second].stack_alias = 0;
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
        stack[*depth - 1].borrowed = true;
        stack[*depth - 1].origin = mi->oparg + 1;
        return 1;
    }
    if (base_opcode == CALL || base_opcode == CALL_KW) {
        int popped = 2 + (base_opcode == CALL_KW) + (int)mi->oparg;
        if (popped > *depth || *depth - popped >= stack_capacity) {
            return 0;
        }
        _PyMethodValue callable = stack[*depth - popped];
        _PyMethodValue result = method_value_unknown();
        if (callable.kind == METHOD_VALUE_CONST &&
            (callable.object == (PyObject *)&PyEnum_Type ||
             callable.object == (PyObject *)&PyZip_Type ||
             callable.object == (PyObject *)&PyList_Type ||
             callable.object == (PyObject *)&PyTuple_Type ||
             callable.object == (PyObject *)&PyDict_Type ||
             callable.object == (PyObject *)&PySet_Type ||
             callable.object == (PyObject *)&PyFrozenSet_Type ||
             callable.object == (PyObject *)&PyRange_Type ||
             callable.object == (PyObject *)&PyBool_Type)) {
            result = method_value_type((PyTypeObject *)callable.object, false);
        }
        *depth -= popped;
        stack[(*depth)++] = result;
        return 1;
    }

    PyObject *method = method_cached_function(code, mi);
    if (method != NULL) {
        if (*depth < 1 || *depth >= stack_capacity) {
            return 0;
        }
        _PyMethodValue owner = stack[*depth - 1];
        stack[*depth - 1] = method_value_const(method);
        stack[(*depth)++] = owner;
        return 1;
    }
    if (mi->dynamic_method) {
        assert(base_opcode == LOAD_ATTR && (mi->oparg & 1));
        if (*depth < 1 || *depth >= stack_capacity) {
            return 0;
        }
        _PyMethodValue owner = stack[*depth - 1];
        stack[*depth - 1] = method_value_type(&PyFunction_Type, false);
        stack[*depth - 1].dynamic_method = true;
        stack[(*depth)++] = owner;
        return 1;
    }

#ifndef Py_GIL_DISABLED
    if (opcode == LOAD_ATTR_MODULE && *depth > 0 &&
        *depth + (int)(mi->oparg & 1) <= stack_capacity &&
        stack[*depth - 1].kind == METHOD_VALUE_BINDING_HINT &&
        PyModule_CheckExact(stack[*depth - 1].object))
    {
        PyObject *namespace;
        PyObject *value = method_module_attribute(
            code, mi, stack[*depth - 1], &namespace);
        stack[*depth - 1] = method_value_unknown();
        if (value != NULL &&
            (PyFunction_Check(value) || PyModule_CheckExact(value) || PyType_Check(value)))
        {
            stack[*depth - 1].kind = METHOD_VALUE_BINDING_HINT;
            stack[*depth - 1].object = value;
        }
        if (mi->oparg & 1) {
            stack[(*depth)++] = method_value_null();
        }
        return 1;
    }
#endif

    if (base_opcode == GET_ITER && *depth > 0 && *depth < stack_capacity) {
        PyTypeObject *type = method_value_get_type(stack[*depth - 1]);
        if (type == &PyEnum_Type || type == &PyZip_Type) {
            /* These immutable builtin types always return themselves from
             * tp_iter, and use the ordinary (non-virtual) iterator protocol. */
            stack[(*depth)++] = method_value_null();
            return 1;
        }
    }

    if (base_opcode == LOAD_GLOBAL) {
        if (*depth + 1 + (int)(mi->oparg & 1) > stack_capacity) {
            return 0;
        }
        PyObject *constant = method_global_constant(func, code, mi);
        stack[(*depth)++] = constant == NULL
            ? method_value_unknown() : method_value_const(constant);
#ifndef Py_GIL_DISABLED
        if (constant == NULL) {
            PyObject *value = method_global_value(func, code, mi);
            if (value != NULL && (PyModule_CheckExact(value) || PyType_Check(value))) {
                stack[*depth - 1].kind = METHOD_VALUE_BINDING_HINT;
                stack[*depth - 1].object = value;
            }
        }
#endif
        if (mi->oparg & 1) {
            stack[(*depth)++] = method_value_null();
        }
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
            /* The method lowering checks compactness before advancing the
             * iterator. Every compiled successor sees a checked item. */
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
            stack[*depth - 1].origin = mi->oparg + 1;
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
            method_forget_local_origin(values, locals_count, *depth, (int)mi->oparg);
            values[mi->oparg] = stack[--(*depth)];
            values[mi->oparg].unique = values[mi->oparg].borrowed = false;
            values[mi->oparg].origin = 0;
            values[mi->oparg].stack_alias = 0;
            return 1;
        case DELETE_FAST:
            if (mi->oparg >= (uint32_t)locals_count) {
                return 0;
            }
            method_forget_local_origin(values, locals_count, *depth, (int)mi->oparg);
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
            stack[*depth - (int)mi->oparg].unique = false;
            if (stack[*depth - (int)mi->oparg].stack_alias == 0) {
                stack[*depth - (int)mi->oparg].stack_alias = mi->opcode_offset + 1;
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

    if (opcode == TO_BOOL_BOOL && *depth > 0) {
        uint16_t alias = stack[*depth - 1].stack_alias;
        if (alias != 0) {
            /* The exact-bool guard also proves that any surviving COPY of
             * the same value is immortal, as in a short-circuit expression. */
            for (int i = 0; i < *depth; i++) {
                if (stack[i].stack_alias == alias) {
                    stack[i] = method_value_type(&PyBool_Type, false);
                }
            }
        }
    }

    /* A CFG edge describes the completed bytecode, including a Python callee's
     * eventual return. Specialized frame-pushing opcodes describe the immediate
     * evaluator transition instead (for example LOAD_ATTR_PROPERTY pushes zero
     * values). Their unspecialized opcode gives the logical stack effect here. */
    int popped = _PyOpcode_num_popped(base_opcode, mi->oparg);
    int pushed = _PyOpcode_num_pushed(base_opcode, mi->oparg);
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
            result.unique = true;
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
    if (base_opcode == LOAD_ATTR && (mi->oparg & 1) && pushed == 2) {
        const struct opcode_macro_expansion *expansion =
            &_PyOpcode_macro_expansion[opcode];
        if (expansion->nuops > 0 &&
            expansion->uops[expansion->nuops - 1].uop == _PUSH_NULL_CONDITIONAL)
        {
            /* Specialized value loads cannot bind an implicit self. This
             * fact comes from the opcode, not from the cached attribute. */
            stack[*depth - 1] = method_value_null();
        }
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
        for (int i = 0; i < active; i++) {
            destination[i].unique = destination[i].borrowed = false;
            destination[i].origin = 0;
            destination[i].stack_alias = 0;
        }
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
        merged.unique = merged.borrowed = false;
        merged.origin = 0;
        merged.stack_alias = 0;
        if (!method_value_equal(destination[i], merged)) {
            destination[i] = merged;
            changed = 1;
        }
    }
    return changed;
}

static PyFunctionObject *
method_lookup_function(PyInterpreterState *interp, uint32_t version,
                       PyObject *known)
{
    if (version < FUNC_VERSION_FIRST_VALID) {
        return NULL;
    }
    /* The direct-mapped version cache may have evicted a live function.
     * Prefer a callable already proven by the static CFG and retain the
     * normal function-version guard at the call site. */
    PyFunctionObject *func = NULL;
    FT_MUTEX_LOCK(&interp->func_state.mutex);
    if (known != NULL && PyFunction_Check(known) &&
        ((PyFunctionObject *)known)->func_version == version)
    {
        func = (PyFunctionObject *)Py_NewRef(known);
    }
    else {
        struct _func_version_cache_item *slot =
            &interp->func_state.func_version_cache[
                version % FUNC_VERSION_CACHE_SIZE];
        if (slot->func != NULL && slot->func->func_version == version) {
            func = (PyFunctionObject *)Py_NewRef((PyObject *)slot->func);
        }
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

static void method_find_attribute_family(PyCodeObject *, _PyMethodInstruction *);

static bool
method_attribute_has_family(PyCodeObject *code, int offset)
{
    _Py_CODEUNIT inst = method_bytecode(code)[offset];
    _PyMethodInstruction mi = {
        .offset = offset,
        .opcode_offset = offset,
        .opcode = inst.op.code,
        .oparg = inst.op.arg,
    };
    method_find_attribute_family(code, &mi);
    return mi.alternate_versions[0] != 0;
}

typedef struct {
    uint64_t layout;
    uint32_t versions[4];
} _PyMethodPredicate;

/* Inline a small boolean expression over stored attributes. All attribute
 * values are checked before consuming call arguments, so a descriptor,
 * non-bool truth test, or missing field falls back to the ordinary call.
 * The truth table comes from the whole bytecode CFG, not an observed path. */
static bool
method_boolean_predicate(PyThreadState *tstate, PyFunctionObject *func,
                          _PyMethodPredicate *predicate)
{
#if defined(Py_GIL_DISABLED) || defined(WITH_DTRACE)
    return false;
#else
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    if (func->vectorcall != _PyFunction_Vectorcall ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR |
                          CO_VARARGS | CO_VARKEYWORDS)) ||
        code->co_nlocalsplus != 1 || code->co_argcount != 1 ||
        code->co_kwonlyargcount != 0 || code->co_nfreevars != 0 ||
        Py_SIZE(code) > 96 || PyBytes_GET_SIZE(code->co_exceptiontable) != 0)
    {
        return false;
    }
    for (int event = 0; event < _PY_MONITORING_UNGROUPED_EVENTS; event++) {
        if (tstate->interp->monitors.tools[event] ||
            (code->_co_monitoring != NULL &&
             (code->_co_monitoring->local_monitors.tools[event] ||
              code->_co_monitoring->active_monitors.tools[event])))
        {
            return false;
        }
    }
    _Py_CODEUNIT *bytecode = method_bytecode(code);
    int attributes[96];
    for (int i = 0; i < 96; i++) {
        attributes[i] = -1;
    }
    uint32_t versions[3][4];
    uint64_t layout = 0;
    int count = 0;
    for (int pc = 0; pc < Py_SIZE(code);) {
        int opcode = bytecode[pc].op.code;
        int base = _Py_GetBaseCodeUnit(code, pc).op.code;
        int next = pc + 1 + _PyOpcode_Caches[base];
        if (next > Py_SIZE(code) || base == EXTENDED_ARG) {
            return false;
        }
        if (base == LOAD_ATTR) {
            if (count == 3 || (bytecode[pc].op.arg & 1) ||
                (opcode != LOAD_ATTR_INSTANCE_VALUE && opcode != LOAD_ATTR_SLOT))
            {
                return false;
            }
            _PyAttrCache *cache = (_PyAttrCache *)(bytecode + pc + 1);
            if (cache->index >= 32768 || read_u32(cache->version) == 0) {
                return false;
            }
            _PyMethodInstruction mi = {
                .offset = pc, .opcode_offset = pc, .next_offset = next,
                .opcode = opcode, .oparg = bytecode[pc].op.arg,
            };
            method_find_attribute_family(code, &mi);
            versions[count][0] = read_u32(cache->version);
            for (int i = 0; i < 3; i++) {
                versions[count][i + 1] = mi.alternate_versions[i];
            }
            uint64_t field = cache->index |
                (opcode == LOAD_ATTR_INSTANCE_VALUE ? 32768 : 0);
            layout |= field << (16 * count);
            attributes[pc] = count++;
        }
        pc = next;
    }
    if (count == 0) {
        return false;
    }
    int accepted = 0;
    for (int i = 0; i < 4; i++) {
        uint32_t version = versions[0][i];
        if (version == 0) {
            continue;
        }
        bool matches = true;
        for (int attr = 1; attr < count; attr++) {
            bool found = false;
            for (int j = 0; j < 4; j++) {
                found |= versions[attr][j] == version;
            }
            matches &= found;
        }
        if (matches) {
            predicate->versions[accepted++] = version;
        }
    }
    if (accepted == 0) {
        return false;
    }
    unsigned int truth_table = 0;
    for (int inputs = 0; inputs < (1 << count); inputs++) {
        int stack[8];
        int depth = 0;
        int pc = 0;
        bool returned = false;
        for (int steps = 0; steps < 96 && pc < Py_SIZE(code); steps++) {
            _Py_CODEUNIT inst = _Py_GetBaseCodeUnit(code, pc);
            int opcode = inst.op.code;
            int next = pc + 1 + _PyOpcode_Caches[opcode];
            if (depth < 0 || depth >= 7) {
                return false;
            }
            switch (opcode) {
                case RESUME:
                case NOP:
                case NOT_TAKEN:
                    break;
                case LOAD_FAST:
                case LOAD_FAST_BORROW:
                    if (inst.op.arg != 0) {
                        return false;
                    }
                    stack[depth++] = 2;  // The receiver, not a boolean value.
                    break;
                case LOAD_ATTR:
                    if (depth == 0 || stack[depth - 1] != 2 || attributes[pc] < 0) {
                        return false;
                    }
                    stack[depth - 1] = (inputs >> attributes[pc]) & 1;
                    break;
                case LOAD_CONST: {
                    PyObject *value = PyTuple_GET_ITEM(code->co_consts, inst.op.arg);
                    if (!PyBool_Check(value)) {
                        return false;
                    }
                    stack[depth++] = value == Py_True;
                    break;
                }
                case COPY:
                    if (inst.op.arg == 0 || inst.op.arg > depth) {
                        return false;
                    }
                    stack[depth] = stack[depth - inst.op.arg];
                    depth++;
                    break;
                case TO_BOOL:
                case UNARY_NOT:
                    if (depth == 0 || stack[depth - 1] > 1) {
                        return false;
                    }
                    stack[depth - 1] ^= opcode == UNARY_NOT;
                    break;
                case POP_TOP:
                    if (depth-- == 0) {
                        return false;
                    }
                    break;
                case POP_JUMP_IF_TRUE:
                case POP_JUMP_IF_FALSE:
                    if (depth == 0 || stack[depth - 1] > 1) {
                        return false;
                    }
                    if (stack[--depth] == (opcode == POP_JUMP_IF_TRUE)) {
                        next += inst.op.arg;
                    }
                    break;
                case JUMP_FORWARD:
                    next += inst.op.arg;
                    break;
                case RETURN_VALUE:
                    if (depth != 1 || stack[0] > 1) {
                        return false;
                    }
                    truth_table |= stack[0] << inputs;
                    returned = true;
                    break;
                default:
                    return false;
            }
            if (returned) {
                break;
            }
            pc = next;
        }
        if (!returned) {
            return false;
        }
    }
    predicate->layout = layout | ((uint64_t)count << 48) |
                        ((uint64_t)truth_table << 50);
    return true;
#endif
}

/* A leaf whose body cannot call Python needs no materialized interpreter
 * frame. Value-dependent guards preserve callbacks and their frame visibility.
 * Call-site guards and argument cleanup remain in the caller. */
static int
method_trivial_return(PyThreadState *tstate, PyFunctionObject *function,
                      _PyBloomFilter *dependencies, uint64_t *operand)
{
#if defined(Py_GIL_DISABLED) || defined(WITH_DTRACE)
    return 0;
#endif
    PyCodeObject *code = (PyCodeObject *)function->func_code;
    bool indexed_attribute = Py_SIZE(code) ==
        7 + INLINE_CACHE_ENTRIES_LOAD_ATTR + INLINE_CACHE_ENTRIES_BINARY_OP;
    if (function->vectorcall != _PyFunction_Vectorcall ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR |
                          CO_VARARGS | CO_VARKEYWORDS)) ||
        code->co_kwonlyargcount != 0 ||
        code->co_nlocalsplus != code->co_argcount || code->co_argcount > 255 ||
        (!indexed_attribute && Py_SIZE(code) != 4 &&
         Py_SIZE(code) != 5 + INLINE_CACHE_ENTRIES_LOAD_ATTR &&
         Py_SIZE(code) != 6 + INLINE_CACHE_ENTRIES_STORE_ATTR &&
         Py_SIZE(code) != 7 + INLINE_CACHE_ENTRIES_STORE_ATTR) ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0)
    {
        return 0;
    }
    for (int event = 0; event < _PY_MONITORING_UNGROUPED_EVENTS; event++) {
        if (tstate->interp->monitors.tools[event] ||
            (code->_co_monitoring != NULL &&
             (code->_co_monitoring->local_monitors.tools[event] ||
              code->_co_monitoring->active_monitors.tools[event])))
        {
            return 0;
        }
    }
    _Py_CODEUNIT *instructions = method_bytecode(code);
    int entry = instructions[0].op.code;
    if (entry == ENTER_EXECUTOR) {
        entry = code->co_executors->executors[instructions[0].op.arg]->vm_data.opcode;
    }
    if (_PyOpcode_Deopt[entry] != RESUME ||
        instructions[Py_SIZE(code) - 1].op.code != RETURN_VALUE)
    {
        return 0;
    }
    int opcode = instructions[2].op.code;
    int arg = instructions[2].op.arg;
    int result = _CALL_RETURN_ARGUMENT;
    if (Py_SIZE(code) == 6 + INLINE_CACHE_ENTRIES_STORE_ATTR ||
        Py_SIZE(code) == 7 + INLINE_CACHE_ENTRIES_STORE_ATTR)
    {
        int value_arg, owner_arg, pc = 2;
        if (opcode == LOAD_FAST_LOAD_FAST ||
            opcode == LOAD_FAST_BORROW_LOAD_FAST_BORROW)
        {
            value_arg = arg >> 4;
            owner_arg = arg & 15;
            pc++;
        }
        else if (opcode == LOAD_FAST || opcode == LOAD_FAST_BORROW) {
            value_arg = arg;
            opcode = instructions[++pc].op.code;
            owner_arg = instructions[pc++].op.arg;
            if (opcode != LOAD_FAST && opcode != LOAD_FAST_BORROW) {
                return 0;
            }
        }
        else {
            return 0;
        }
        int attribute = instructions[pc].op.code;
        if (value_arg >= code->co_argcount || owner_arg >= code->co_argcount ||
            value_arg > 15 || owner_arg > 15 ||
            (attribute != STORE_ATTR_SLOT && attribute != STORE_ATTR_INSTANCE_VALUE) ||
            method_attribute_has_family(code, pc))
        {
            /* A frame-free access has only one receiver version. Keep the
             * full static callee when it can guard several compatible types,
             * instead of exiting the caller for every other receiver. */
            return 0;
        }
        _PyAttrCache *cache = (_PyAttrCache *)&instructions[pc + 1];
        pc += 1 + INLINE_CACHE_ENTRIES_STORE_ATTR;
        if (pc + 2 != Py_SIZE(code)) {
            return 0;
        }
        PyObject *constant = NULL;
        opcode = instructions[pc].op.code;
        arg = instructions[pc].op.arg;
        if (opcode == LOAD_CONST && arg < PyTuple_GET_SIZE(code->co_consts)) {
            constant = PyTuple_GET_ITEM(code->co_consts, arg);
        }
        else if (opcode == LOAD_COMMON_CONSTANT && arg < NUM_COMMON_CONSTANTS) {
            constant = PyStackRef_AsPyObjectBorrow(tstate->interp->common_consts[arg]);
        }
        uint32_t version = read_u32(cache->version);
        if (constant != Py_None || version == 0) {
            return 0;
        }
        *operand = (uint64_t)owner_arg | ((uint64_t)value_arg << 4) |
                   ((uint64_t)cache->index << 8) | ((uint64_t)version << 24) |
                   ((uint64_t)(attribute == STORE_ATTR_INSTANCE_VALUE) << 56);
        result = _CALL_STORE_ATTRIBUTE;
    }
    else if (indexed_attribute || Py_SIZE(code) == 5 + INLINE_CACHE_ENTRIES_LOAD_ATTR) {
        int attribute = instructions[3].op.code;
        if ((opcode != LOAD_FAST && opcode != LOAD_FAST_BORROW) ||
            arg >= code->co_argcount || (instructions[3].op.arg & 1) ||
            (attribute != LOAD_ATTR_SLOT && attribute != LOAD_ATTR_INSTANCE_VALUE) ||
            method_attribute_has_family(code, 3))
        {
            return 0;
        }
        _PyAttrCache *cache = (_PyAttrCache *)&instructions[4];
        uint32_t version = read_u32(cache->version);
        if (version == 0) {
            return 0;
        }
        *operand = (uint64_t)arg | ((uint64_t)cache->index << 8) |
                   ((uint64_t)version << 24) |
                   ((uint64_t)(attribute == LOAD_ATTR_INSTANCE_VALUE) << 56);
        result = _CALL_RETURN_ATTRIBUTE;
        if (indexed_attribute) {
            int pc = 4 + INLINE_CACHE_ENTRIES_LOAD_ATTR;
            int load_key = instructions[pc].op.code;
            int key_arg = instructions[pc].op.arg;
            int subscript = instructions[pc + 1].op.code;
            if ((load_key != LOAD_FAST && load_key != LOAD_FAST_BORROW) ||
                key_arg >= code->co_argcount || key_arg >= 128 ||
                (subscript != BINARY_OP_SUBSCR_TUPLE_INT &&
                 subscript != BINARY_OP_SUBSCR_LIST_INT))
            {
                return 0;
            }
            *operand |= (uint64_t)key_arg << 57;
            result = _CALL_RETURN_ATTRIBUTE_ITEM;
        }
    }
    else if (opcode == LOAD_FAST || opcode == LOAD_FAST_BORROW) {
        if (arg >= code->co_argcount) {
            return 0;
        }
        *operand = arg;
    }
    else {
        PyObject *constant = NULL;
        if (opcode == LOAD_CONST && arg < PyTuple_GET_SIZE(code->co_consts)) {
            constant = PyTuple_GET_ITEM(code->co_consts, arg);
        }
        else if (opcode == LOAD_COMMON_CONSTANT && arg < NUM_COMMON_CONSTANTS) {
            constant = PyStackRef_AsPyObjectBorrow(tstate->interp->common_consts[arg]);
        }
        else if (opcode == LOAD_SMALL_INT) {
            constant = (PyObject *)&_PyLong_SMALL_INTS[_PY_NSMALLNEGINTS + arg];
        }
        if (constant == NULL || !_Py_IsImmortal(constant)) {
            return 0;
        }
        *operand = (uintptr_t)constant;
        result = _CALL_RETURN_CONSTANT;
    }
    /* Local monitoring changes must invalidate a caller that removed this
     * callee's frame, even though its function version need not change. */
    _Py_BloomFilter_Add(dependencies, code);
    _Py_BloomFilter_Add(dependencies, function);
    return result;
}

/* C vectorcall arguments remain owned by the caller. These recognized bodies
 * neither allocate nor call Python, so omitting their temporary frame cannot
 * move a finalizer across the call boundary. NULL means ordinary evaluation. */
PyObject *
_PyJit_TryTrivialCall(PyThreadState *tstate, PyCodeObject *code,
                      PyObject *const *args, Py_ssize_t nargs, PyObject *kwnames)
{
#if !defined(Py_GIL_DISABLED) && !defined(WITH_DTRACE)
    _Py_CODEUNIT *entry = method_bytecode(code);
    assert(entry->op.code == ENTER_EXECUTOR);
    _PyExecutorObject *executor = code->co_executors->executors[entry->op.arg];
    if (!executor->trivial_call || !executor->vm_data.valid ||
        !tstate->interp->jit || tstate->interp->eval_frame != NULL ||
        tstate->c_tracefunc != NULL || tstate->c_profilefunc != NULL ||
        kwnames != NULL || nargs != code->co_argcount ||
        tstate->py_recursion_remaining <= 1 ||
        _Py_ReachedRecursionLimitWithMargin(tstate, 2) ||
        _Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) !=
            code->_co_instrumentation_version)
    {
        return NULL;
    }
    /* This entry bypasses the executor's _MAKE_WARM instruction. */
    executor->vm_data.cold = false;
    uint64_t operand = executor->trivial_operand;
    switch (executor->trivial_call) {
        case _CALL_RETURN_ARGUMENT:
            return Py_NewRef(args[operand]);
        case _CALL_RETURN_CONSTANT:
            return Py_NewRef((PyObject *)(uintptr_t)operand);
        case _CALL_RETURN_ATTRIBUTE:
        case _CALL_RETURN_ATTRIBUTE_ITEM: {
            PyObject *owner = args[operand & 255];
            uint32_t version = (uint32_t)(operand >> 24);
            if (Py_TYPE(owner)->tp_version_tag != version ||
                (((operand >> 56) & 1) && !_PyObject_InlineValues(owner)->valid))
            {
                return NULL;
            }
            uint16_t offset = (uint16_t)(operand >> 8);
            PyObject *value = *(PyObject **)((char *)owner + offset);
            if (executor->trivial_call == _CALL_RETURN_ATTRIBUTE_ITEM) {
                PyObject *key = args[operand >> 57];
                if (value == NULL ||
                    (!PyTuple_CheckExact(value) && !PyList_CheckExact(value)) ||
                    !PyLong_CheckExact(key) || !_PyLong_IsCompact((PyLongObject *)key))
                {
                    return NULL;
                }
                Py_ssize_t index = _PyLong_CompactValue((PyLongObject *)key);
                Py_ssize_t length = Py_SIZE(value);
                if (index < 0) {
                    index += length;
                }
                if ((size_t)index >= (size_t)length) {
                    return NULL;
                }
                value = PySequence_Fast_GET_ITEM(value, index);
            }
            return Py_XNewRef(value);
        }
    }
#endif
    return NULL;
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

/* Recognize a small initializer that only copies positional arguments into
 * distinct specialized fields. This describes ordinary record constructors,
 * without depending on class, attribute or parameter names. */
static uint64_t
method_simple_initializer(PyThreadState *tstate, PyFunctionObject *function,
                          int nargs, uint32_t type_version,
                          _PyBloomFilter *dependencies)
{
#if defined(Py_GIL_DISABLED) || defined(WITH_DTRACE)
    return 0;
#endif
    PyCodeObject *code = (PyCodeObject *)function->func_code;
    if (nargs < 1 || nargs > 3 || type_version == 0 ||
        function->vectorcall != _PyFunction_Vectorcall ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR |
                          CO_VARARGS | CO_VARKEYWORDS)) ||
        code->co_argcount != nargs + 1 || code->co_kwonlyargcount != 0 ||
        code->co_nlocalsplus != code->co_argcount ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0)
    {
        return 0;
    }
    for (int event = 0; event < _PY_MONITORING_UNGROUPED_EVENTS; event++) {
        if (tstate->interp->monitors.tools[event] ||
            (code->_co_monitoring != NULL &&
             (code->_co_monitoring->local_monitors.tools[event] ||
              code->_co_monitoring->active_monitors.tools[event])))
        {
            return 0;
        }
    }
    _Py_CODEUNIT *instructions = method_bytecode(code);
    int entry = _Py_GetBaseCodeUnit(code, 0).op.code;
    if (_PyOpcode_Deopt[entry] != RESUME) {
        return 0;
    }
    int pc = 1 + _PyOpcode_Caches[RESUME];
    int kind = -1;
    uint64_t fields = 0;
    unsigned seen_args = 0;
    uint16_t offsets[3];
    for (int field = 0; field < nargs; field++) {
        if (pc + 2 >= Py_SIZE(code)) {
            return 0;
        }
        int opcode = instructions[pc].op.code;
        int arg;
        if (opcode == LOAD_FAST_LOAD_FAST || opcode == LOAD_FAST_BORROW_LOAD_FAST_BORROW) {
            arg = instructions[pc].op.arg >> 4;
            if ((instructions[pc].op.arg & 15) != 0) {
                return 0;
            }
            pc++;
        }
        else if (opcode == LOAD_FAST || opcode == LOAD_FAST_BORROW) {
            arg = instructions[pc++].op.arg;
            opcode = instructions[pc].op.code;
            if ((opcode != LOAD_FAST && opcode != LOAD_FAST_BORROW) ||
                instructions[pc++].op.arg != 0)
            {
                return 0;
            }
        }
        else {
            return 0;
        }
        if (arg < 1 || arg > nargs || (seen_args & (1U << arg)) ||
            pc + (int)INLINE_CACHE_ENTRIES_STORE_ATTR >= Py_SIZE(code))
        {
            return 0;
        }
        seen_args |= 1U << arg;
        opcode = instructions[pc].op.code;
        if ((opcode != STORE_ATTR_SLOT && opcode != STORE_ATTR_INSTANCE_VALUE) ||
            (kind >= 0 && kind != opcode))
        {
            return 0;
        }
        kind = opcode;
        _PyAttrCache *cache = (_PyAttrCache *)&instructions[pc + 1];
        int offset = cache->index;
        if (read_u32(cache->version) != type_version ||
            offset % SIZEOF_VOID_P || offset / SIZEOF_VOID_P > 255)
        {
            return 0;
        }
        for (int previous = 0; previous < field; previous++) {
            if (offsets[previous] == offset) {
                return 0;
            }
        }
        offsets[field] = offset;
        fields |= (uint64_t)((offset / SIZEOF_VOID_P) | ((arg - 1) << 8)) << (10 * field);
        pc += 1 + INLINE_CACHE_ENTRIES_STORE_ATTR;
    }
    if (pc + 2 != Py_SIZE(code) || instructions[pc + 1].op.code != RETURN_VALUE) {
        return 0;
    }
    int opcode = instructions[pc].op.code;
    int arg = instructions[pc].op.arg;
    PyObject *constant = NULL;
    if (opcode == LOAD_CONST && arg < PyTuple_GET_SIZE(code->co_consts)) {
        constant = PyTuple_GET_ITEM(code->co_consts, arg);
    }
    else if (opcode == LOAD_COMMON_CONSTANT && arg < NUM_COMMON_CONSTANTS) {
        constant = PyStackRef_AsPyObjectBorrow(tstate->interp->common_consts[arg]);
    }
    if (constant != Py_None) {
        return 0;
    }
    _Py_BloomFilter_Add(dependencies, function);
    _Py_BloomFilter_Add(dependencies, code);
    return fields | ((uint64_t)(kind == STORE_ATTR_INSTANCE_VALUE) << 30) |
           ((uint64_t)type_version << 32);
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
    uint64_t operand,
    uint16_t type_family,
    const _PyMethodValue *values,
    int locals_count,
    int stack_depth)
{
    bool type_version_guard = uop == _GUARD_TYPE_VERSION;
#ifndef Py_GIL_DISABLED
    // Locking is a no-op with the GIL, so the same receiver fact applies.
    type_version_guard |= uop == _GUARD_TYPE_VERSION_LOCKED;
    if (uop == _LOCK_OBJECT) {
        return _NOP;
    }
    if (stack_depth > 0) {
        int guards = values[locals_count + stack_depth - 1].managed_guards;
        if ((uop == _GUARD_DORV_NO_DICT && guards == 3) ||
            (uop == _CHECK_MANAGED_OBJECT_HAS_VALUES && (guards & 1)))
        {
            return _NOP;
        }
    }
#endif
    if (type_version_guard && operand != 0 && stack_depth > 0 &&
        values[locals_count + stack_depth - 1].type_version == operand) {
        return _NOP;
    }
    if (uop == _GUARD_TYPE_VERSION_FAMILY && type_family != 0 &&
        stack_depth > 0 &&
        values[locals_count + stack_depth - 1].type_family == type_family) {
        return _NOP;
    }
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
                stack[*stack_depth - 1].borrowed = uop == _LOAD_FAST_BORROW;
                stack[*stack_depth - 1].origin = oparg + 1;
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
                method_forget_local_origin(values, locals_count, *stack_depth, oparg);
                _PyMethodValue tmp = values[oparg];
                values[oparg] = stack[*stack_depth - 1];
                values[oparg].unique = values[oparg].borrowed = false;
                values[oparg].origin = 0;
                values[oparg].stack_alias = 0;
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
                    result.unique = true;
                }
                else {
                    result = method_value_type(&PyBool_Type, false);
                }
                _PyMethodValue left = stack[*stack_depth - 2];
                _PyMethodValue right = stack[*stack_depth - 1];
                *stack_depth -= 2;
                stack[(*stack_depth)++] = result;
                stack[(*stack_depth)++] = left;
                stack[(*stack_depth)++] = right;
            }
            return;
        case _TO_BOOL:
            if (*stack_depth > 0) {
                stack[*stack_depth - 1] =
                    method_value_type(&PyBool_Type, false);
            }
            return;
        case _TO_BOOL_INT:
        case _TO_BOOL_LIST:
        case _TO_BOOL_STR:
        case _REPLACE_WITH_TRUE:
            if (*stack_depth > 0 && *stack_depth < stack_capacity) {
                _PyMethodValue value = stack[*stack_depth - 1];
                (*stack_depth)--;
                stack[(*stack_depth)++] =
                    method_value_type(&PyBool_Type, false);
                stack[(*stack_depth)++] = value;
            }
            return;
    }
}

#define METHOD_TARGET_OFFSET_FLAG (UINT64_C(1) << 63)

static bool
method_is_edge(int opcode)
{
    return opcode == _METHOD_POP_JUMP_IF_FALSE ||
        opcode == _METHOD_POP_JUMP_IF_TRUE || opcode == _METHOD_JUMP ||
        opcode == _METHOD_FOR_ITER || opcode == _METHOD_ITER_NEXT_INLINE ||
        opcode == _METHOD_TRY_SIMPLE_INIT ||
        opcode == _METHOD_TRY_SIMPLE_INIT_1 ||
        opcode == _METHOD_TRY_SIMPLE_INIT_2 ||
        opcode == _METHOD_TRY_SIMPLE_INIT_3 ||
        opcode == _METHOD_ITER_JUMP_LIST ||
        opcode == _METHOD_ITER_JUMP_TUPLE || opcode == _METHOD_ITER_JUMP_RANGE;
}

static int
method_optimize_blocks(PyFunctionObject *func, _PyUOpInstruction *input,
                       int length, int limit, _PyMethodBlock *blocks,
                       int block_count, const _PyMethodValue *states,
                       int state_width, _PyBloomFilter *dependencies);

static int
method_inline_small_cfg(
    PyThreadState *tstate,
    PyCodeObject *root_code,
    PyFunctionObject *func,
    int inline_depth,
    const _PyMethodValue *arguments,
    int argument_count,
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
    int inline_depth,
    PyFunctionObject *func,
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

#ifdef Py_GIL_DISABLED
    /* Normalize mutable operations in the CFG as well as here: using a
     * generic call must not retain the result-type facts of its old cache. */
    if (tstate->interp->jit_multithreaded &&
        (opcode == LOAD_GLOBAL || opcode == LOAD_ATTR ||
         opcode == STORE_ATTR || opcode == CALL))
    {
        if (!method_emit(buffer, length, limit, _CHECK_VALIDITY, 0, 0, target) ||
            !method_emit(buffer, length, limit, _SET_IP, 0,
                         (uintptr_t)instr, target))
        {
            return 0;
        }
        if (opcode == LOAD_GLOBAL) {
            return method_emit(buffer, length, limit, _LOAD_GLOBAL,
                               (uint16_t)oparg, 0, target) &&
                method_emit(buffer, length, limit, _PUSH_NULL_CONDITIONAL,
                            (uint16_t)oparg, 0, target);
        }
        if (opcode == LOAD_ATTR || opcode == STORE_ATTR) {
            return method_emit(buffer, length, limit,
                               opcode == LOAD_ATTR ? _LOAD_ATTR : _STORE_ATTR,
                               (uint16_t)oparg, 0, target);
        }
        /* The general vectorcall path also handles Python functions. It
         * owns frame entry and locking; no cached function fields are read. */
        return method_emit(buffer, length, limit, _MAYBE_EXPAND_METHOD,
                           (uint16_t)oparg, 0, target) &&
            method_emit(buffer, length, limit, _CALL_NON_PY_GENERAL,
                        (uint16_t)oparg, 0, target) &&
            method_emit(buffer, length, limit, _TIER2_RESUME_CHECK,
                        0, 0, mi->next_offset);
    }
    int base_opcode = _PyOpcode_Deopt[opcode];
    if (tstate->interp->jit_multithreaded &&
        (base_opcode == CALL_KW || base_opcode == CALL_FUNCTION_EX ||
         base_opcode == LOAD_DEREF || base_opcode == STORE_DEREF ||
         base_opcode == DELETE_DEREF || base_opcode == MAKE_CELL ||
         base_opcode == COPY_FREE_VARS))
    {
        return 0;
    }
#endif

    if (!method_emit(buffer, length, limit, _CHECK_VALIDITY, 0, 0, target)) {
        return 0;
    }
    PyObject *constant = method_global_constant(func, code, mi);
    bool mutable_binding = false;
#ifndef Py_GIL_DISABLED
    if (constant == NULL) {
        PyObject *value = method_global_value(func, code, mi);
        if (value != NULL) {
            constant = value;
            mutable_binding = true;
        }
    }
#endif
    if (constant != NULL) {
        bool builtin = opcode == LOAD_GLOBAL_BUILTIN;
        PyObject *name = PyTuple_GET_ITEM(code->co_names, oparg >> 1);
        if (_PyJit_WatchMethodGlobal(tstate, func->func_globals, name,
                                    builtin, dependencies) < 0) {
            return -1;
        }
        _PyLoadGlobalCache *cache = (_PyLoadGlobalCache *)(instr + 1);
        if (!method_emit(buffer, length, limit, _GUARD_GLOBALS_VERSION_AND_IDENTITY,
                         0, cache->module_keys_version, target)) {
            return 0;
        }
        buffer[*length - 1].operand1 = (uintptr_t)func->func_globals;
        if (builtin && !method_emit(buffer, length, limit,
                                   _GUARD_BUILTINS_IDENTITY, 0, 0, target)) {
            return 0;
        }
        int load = _Py_IsImmortal(constant) || _PyObject_HasDeferredRefcount(constant)
            ? _LOAD_CONST_INLINE_BORROW : _LOAD_CONST_INLINE;
        if (mutable_binding) {
            load = _LOAD_GLOBAL_BINDING;
        }
        if (!method_emit(buffer, length, limit, (uint16_t)load,
                         0, (uintptr_t)constant, target)) {
            return 0;
        }
        return !(oparg & 1) || method_emit(
            buffer, length, limit, _PUSH_NULL, 0, 0, target);
    }
    if (opcode == LOAD_CONST) {
        PyObject *value = PyTuple_GET_ITEM(code->co_consts, oparg);
        if (_Py_IsImmortal(value)) {
            return method_emit(buffer, length, limit, _LOAD_CONST_INLINE_BORROW,
                               0, (uintptr_t)value, target);
        }
    }
#ifndef Py_GIL_DISABLED
    if (opcode == LOAD_ATTR_MODULE && stack_depth > 0) {
        PyObject *namespace;
        PyObject *value = method_module_attribute(
            code, mi, state[locals_count + stack_depth - 1], &namespace);
        PyObject *name = PyTuple_GET_ITEM(code->co_names, oparg >> 1);
        if (value != NULL &&
            (Py_TYPE(value)->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) &&
            !_PyJit_IsUnstableGlobal(namespace, PyObject_Hash(name)))
        {
            if (_PyJit_WatchMethodGlobal(tstate, namespace, name,
                                        false, dependencies) < 0) {
                return -1;
            }
            if (!method_emit(buffer, length, limit, _SET_IP, 0,
                             (uintptr_t)(bytecode + mi->opcode_offset), target) ||
                !method_emit(buffer, length, limit, _LOAD_ATTR_MODULE_CONST,
                             0, (uintptr_t)namespace, target)) {
                return 0;
            }
            buffer[*length - 1].operand1 = (uintptr_t)value;
            // Load the result before releasing the module, just as the
            // ordinary attribute operation does. Keep guard/load atomic.
            if (!method_emit(buffer, length, limit, _POP_TOP, 0, 0, target)) {
                return 0;
            }
            return !(oparg & 1) || method_emit(
                buffer, length, limit, _PUSH_NULL, 0, 0, target);
        }
    }
#endif
    if (opcode == RESUME || opcode == RESUME_CHECK_JIT || opcode == RESUME_CHECK) {
        return method_emit(
            buffer, length, limit, _TIER2_RESUME_CHECK, 0, 0, target);
    }
    if ((opcode == BINARY_OP || opcode == COMPARE_OP || opcode == TO_BOOL) &&
        (instr[1].counter.value_and_backoff & BACKOFF_MASK) <=
            ADAPTIVE_WARMUP_BACKOFF)
    {
        /* A statically reachable arm may never have executed in Tier 1.
         * Emitting its generic operation would freeze the initial cache:
         * native execution does not advance the adaptive counter. Let this
         * arm specialize before recompilation. Operations which have already
         * failed specialization retain their general method implementation. */
        return 0;
    }
    if (method_checked_local_store(opcode, oparg, state, locals_count, stack_depth)) {
        return method_emit(buffer, length, limit, _STORE_FAST_NOESCAPE,
                           (uint16_t)oparg, 0, target);
    }
    if (opcode == LOAD_ATTR_PROPERTY || opcode == LOAD_ATTR_GETATTRIBUTE_OVERRIDDEN) {
        /* These Tier 1 specializations enter a Python frame. Use the general
         * attribute operation until the method frontend can guard and inline
         * that entry. A normal call returns to this method instead of forcing
         * its entire continuation back into Tier 1. It also reads the current
         * descriptor, rather than retaining a mutable property's old getter. */
        return method_emit(buffer, length, limit, _SET_IP, 0,
                           (uintptr_t)(bytecode + mi->opcode_offset), target) &&
            method_emit(buffer, length, limit, _LOAD_ATTR,
                        (uint16_t)oparg, 0, target);
    }
    if (OPCODE_HAS_NEEDS_GUARD_IP(opcode) &&
        _PyOpcode_Deopt[opcode] != RETURN_VALUE &&
        !(opcode == CALL_PY_EXACT_ARGS || opcode == CALL_PY_GENERAL ||
          opcode == CALL_BOUND_METHOD_EXACT_ARGS ||
          opcode == CALL_BOUND_METHOD_GENERAL || opcode == CALL_KW_PY ||
          opcode == CALL_KW_BOUND_METHOD || opcode == CALL_ALLOC_AND_ENTER_INIT ||
          opcode == CALL_EX_PY || opcode == BINARY_OP_SUBSCR_GETITEM))
    {
        return 0;
    }
    if (!OPCODE_HAS_NO_SAVE_IP(opcode) &&
        !method_emit(
            buffer, length, limit, _SET_IP, 0,
            /* Frame returns are relative to the opcode, after EXTENDED_ARG.
             * Guard exits still restart at target, including the prefixes. */
            (uintptr_t)instr, target))
    {
        return 0;
    }

    if (method_is_empty_set_call(opcode, oparg, state, locals_count, stack_depth))
    {
        // Keep the ordinary call boundary check after the completed result.
        return method_emit(buffer, length, limit, _CALL_SET_EMPTY, 0, 0, target) &&
            method_emit(buffer, length, limit, _POP_TOP_NOP, 0, 0, target) &&
            method_emit(buffer, length, limit, _TIER2_RESUME_CHECK,
                        0, 0, mi->next_offset);
    }

    const struct opcode_macro_expansion *expansion =
        &_PyOpcode_macro_expansion[opcode];
    int callable_index = stack_depth - (int)oparg - 2;
    PyObject *known_callee = NULL;
    if (_PyOpcode_Deopt[opcode] == CALL && callable_index >= 0 &&
        (state[locals_count + callable_index].kind == METHOD_VALUE_CONST ||
         state[locals_count + callable_index].kind == METHOD_VALUE_BINDING_HINT))
    {
        known_callee = state[locals_count + callable_index].object;
    }
    bool dynamic_call = (opcode == CALL_PY_EXACT_ARGS || opcode == CALL_PY_GENERAL) &&
        callable_index >= 0 && state[locals_count + callable_index].dynamic_method;
    if (dynamic_call) {
        /* The receiver guard admits several overriding Python methods. Bind
         * the actual function's arguments and use its method entry without
         * specializing this call to one function version or frame size. */
        return method_emit(buffer, length, limit, _CHECK_PEP_523, 0, 0, target) &&
            method_emit(buffer, length, limit, _CHECK_PY_FUNCTION,
                        (uint16_t)oparg, 0, target) &&
            method_emit(buffer, length, limit, _CHECK_RECURSION_REMAINING,
                        0, 0, target) &&
            method_emit(buffer, length, limit, _PY_FRAME_GENERAL,
                        (uint16_t)oparg, 0, target) &&
            method_emit(buffer, length, limit, _SAVE_RETURN_OFFSET,
                        (uint16_t)(mi->next_offset - mi->opcode_offset), 0, target) &&
            method_emit(buffer, length, limit, _PUSH_FRAME, 0, 0, target) &&
            method_emit(buffer, length, limit, _METHOD_CALL, 0, 0, target);
    }
    if (expansion->nuops == 0) {
        return 0;
    }
    PyObject *attribute_default = method_attribute_default(code, mi);
    uint32_t inline_version = 0;
    uint32_t constructor_version = 0;
    uint32_t subscript_type_version = 0;
    if (opcode == BINARY_OP_SUBSCR_GETITEM) {
#ifdef Py_GIL_DISABLED
        return 0;
#else
        _PyBinaryOpSubscrCache *cache = (_PyBinaryOpSubscrCache *)(instr + 1);
        subscript_type_version = read_u32(cache->type_version);
        inline_version = read_u32(cache->func_version);
        PyTypeObject *type = _PyType_LookupByVersion(subscript_type_version);
        if (type == NULL || !(type->tp_flags & Py_TPFLAGS_HEAPTYPE)) {
            return 0;
        }
        known_callee = ((PyHeapTypeObject *)type)->_spec_cache.getitem;
        if (known_callee == NULL || !PyFunction_Check(known_callee) ||
            ((PyFunctionObject *)known_callee)->func_version != inline_version)
        {
            return 0;
        }
#endif
    }
    bool pushes_frame = false;
    for (int i = 0; i < expansion->nuops; i++) {
        if (expansion->uops[i].uop == _PUSH_FRAME) {
            pushes_frame = true;
        }
        if ((expansion->uops[i].uop == _CHECK_FUNCTION_VERSION ||
             expansion->uops[i].uop == _CHECK_METHOD_VERSION ||
             expansion->uops[i].uop == _CHECK_FUNCTION_VERSION_KW ||
             expansion->uops[i].uop == _CHECK_METHOD_VERSION_KW) &&
            expansion->uops[i].size == OPARG_CACHE_2)
        {
            int offset = expansion->uops[i].offset + 1;
            inline_version = read_u32(&instr[offset].cache);
        }
#ifndef Py_GIL_DISABLED
        if (opcode == CALL_ALLOC_AND_ENTER_INIT &&
            expansion->uops[i].uop == _CHECK_OBJECT)
        {
            int offset = expansion->uops[i].offset + 1;
            constructor_version = read_u32(&instr[offset].cache);
            PyTypeObject *type = _PyType_LookupByVersion(constructor_version);
            if (type != NULL && (type->tp_flags & Py_TPFLAGS_HEAPTYPE)) {
                PyObject *init = ((PyHeapTypeObject *)type)->_spec_cache.init;
                if (init != NULL && PyFunction_Check(init)) {
                    known_callee = init;
                    inline_version = _PyFunction_GetVersionForCurrentState(
                        (PyFunctionObject *)init);
                }
            }
        }
#endif
    }
    if (pushes_frame && opcode != CALL_ALLOC_AND_ENTER_INIT &&
        opcode != CALL_EX_PY &&
        inline_version < FUNC_VERSION_FIRST_VALID)
    {
        return 0;
    }

    int callee_framesize = -1;
    int callee_argcount = -1;
    int trivial_return = 0;
    uint64_t trivial_operand = 0;
    _PyMethodPredicate predicate = {0};
    uint64_t initializer_fields = 0;
    if (inline_version >= FUNC_VERSION_FIRST_VALID) {
        PyFunctionObject *callee = method_lookup_function(
            tstate->interp, inline_version, known_callee);
        if (callee != NULL) {
            PyCodeObject *callee_code = (PyCodeObject *)callee->func_code;
            callee_framesize = callee_code->co_framesize;
            callee_argcount = callee_code->co_argcount;
            if (opcode == CALL_PY_EXACT_ARGS || opcode == CALL_BOUND_METHOD_EXACT_ARGS) {
                trivial_return = method_trivial_return(
                    tstate, callee, dependencies, &trivial_operand);
                if (trivial_return == 0 &&
                    method_boolean_predicate(tstate, callee, &predicate))
                {
                    trivial_return = _CALL_BOOL_ATTRIBUTES;
                    trivial_operand = predicate.layout;
                    _Py_BloomFilter_Add(dependencies, callee_code);
                }
            }
            if (inline_depth && opcode == CALL_ALLOC_AND_ENTER_INIT) {
                initializer_fields = method_simple_initializer(
                    tstate, callee, oparg, constructor_version, dependencies);
            }
            Py_DECREF(callee);
        }
    }

    uint32_t orig_oparg = oparg;
    uint32_t orig_target = target;
    int direct_jump_index = -1;
    int skip_float_cleanup = -1;
    int initializer_jump = -1;
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
        if (uop == _METHOD_FOR_ITER && stack_depth >= 2) {
            PyTypeObject *type = method_value_get_type(
                state[locals_count + stack_depth - 2]);
            if (type == &PyEnum_Type || type == &PyZip_Type) {
                uop = _METHOD_ITER_NEXT_INLINE;
                operand = (uintptr_t)type->tp_iternext;
#ifndef Py_GIL_DISABLED
                if (type == &PyZip_Type) {
                    operand = (uintptr_t)_PyZip_NextListPair;
                }
#endif
            }
        }
        if (uop == _BINARY_OP_SUBSCR_CHECK_FUNC) {
            uop = _METHOD_SUBSCR_CHECK_FUNC;
            operand = subscript_type_version;
        }
#ifndef Py_GIL_DISABLED
        if (uop == _CALL_ISINSTANCE && stack_depth >= 4) {
            uint32_t version = method_default_instancecheck_version(
                state[locals_count + stack_depth - 1]);
            if (version != 0) {
                uop = _CALL_ISINSTANCE_DEFAULT;
                operand = version;
            }
        }
        if (mi->dynamic_method &&
            (uop == _LOAD_ATTR_METHOD_WITH_VALUES || uop == _LOAD_ATTR_METHOD_NO_DICT))
        {
            uop = _LOAD_ATTR_METHOD_DYNAMIC;
            operand = 0;
        }
        if ((uop == _GUARD_TYPE_VERSION || uop == _GUARD_TYPE_VERSION_LOCKED) &&
            mi->alternate_versions[0])
        {
            uop = _GUARD_TYPE_VERSION_FAMILY;
            operand |= (uint64_t)mi->alternate_versions[0] << 32;
        }
        if (uop == _GUARD_STORE_ATTR_NONDATA) {
            _PyAttrCache *cache = (_PyAttrCache *)(instr + 1);
            PyTypeObject *type = _PyType_LookupByVersion(read_u32(cache->version));
            PyObject *descr = type == NULL ? NULL : _PyType_LookupRef(
                type, PyTuple_GET_ITEM(code->co_names, oparg));
            if (descr == NULL) {
                return 0;
            }
            // No Python can run between the owner guard and this check.
            operand = (uintptr_t)descr;
            Py_DECREF(descr);
            uop = _GUARD_STORE_ATTR_NONDATA_CACHED;
        }
        if (uop == _STORE_ATTR_INSTANCE_VALUE) {
            uop = _STORE_ATTR_INSTANCE_VALUE_NOESCAPE;
        }
        else if (uop == _STORE_ATTR_SLOT) {
            uop = _STORE_ATTR_SLOT_NOESCAPE;
        }
        else if (uop == _POP_TOP &&
                 (opcode == STORE_ATTR_INSTANCE_VALUE ||
                  opcode == STORE_ATTR_INSTANCE_VALUE_NONDATA || opcode == STORE_ATTR_SLOT) &&
                 stack_depth >= 2 && state[locals_count + stack_depth - 1].borrowed)
        {
            // The guarded store cannot call Python or change the borrowed
            // receiver's lifetime before discarding this stack reference.
            uop = _POP_TOP_NOP;
        }
#endif
        if (uop == _ITER_NEXT_RANGE) {
            uop = _ITER_NEXT_RANGE_COMPACT;
        }
        if (uop == _BUILD_MAP && oparg == 0) {
            uop = _BUILD_EMPTY_MAP;
        }
        int original_uop = (int)uop;
        if (uop == _CREATE_INIT_FRAME && initializer_fields != 0) {
            int guard = *length;
            if (!method_emit(buffer, length, limit, _METHOD_TRY_SIMPLE_INIT,
                             (uint16_t)oparg, initializer_fields, target) ||
                !method_emit(buffer, length, limit, _METHOD_JUMP, 0, 0, target))
            {
                return 0;
            }
            initializer_jump = *length - 1;
            buffer[guard].operand1 = (uint64_t)*length | METHOD_TARGET_OFFSET_FLAG;
            if (!method_emit(buffer, length, limit, _METHOD_LABEL, 0, 0, target)) {
                return 0;
            }
        }
        if (uop == _INIT_CALL_PY_EXACT_ARGS && trivial_return != 0) {
            /* Retain an entry periodic check before consuming arguments.
             * The replacement closes them in normal frame-clear order. */
            if (!method_emit(buffer, length, limit, _TIER2_RESUME_CHECK,
                             0, 0, target)) {
                return 0;
            }
            if (trivial_return == _CALL_BOOL_ATTRIBUTES) {
                uint64_t first = predicate.versions[0] |
                    ((uint64_t)predicate.versions[1] << 32);
                if (!method_emit(buffer, length, limit, _GUARD_CALL_TYPE_VERSION_FAMILY,
                                 (uint16_t)oparg, first, target)) {
                    return 0;
                }
                buffer[*length - 1].operand1 = predicate.versions[2] |
                    ((uint64_t)predicate.versions[3] << 32);
            }
            return method_emit(buffer, length, limit, trivial_return,
                               (uint16_t)oparg, trivial_operand, target);
        }
        if (uop == _CHECK_PEP_523 && tstate->interp->eval_frame == NULL) {
            /* Changing the evaluation hook invalidates all executors. */
            uop = _NOP;
        }
#ifndef Py_GIL_DISABLED
        if (uop == _LOAD_DEREF) {
            /* Loading a populated cell cannot run Python. Leave unbound-cell
             * errors to the original bytecode, avoiding escape bookkeeping
             * on every successful load. FT retains its lock-free getter. */
            uop = _LOAD_DEREF_GUARDED;
        }
#endif
        if (uop == _CHECK_STACK_SPACE && callee_framesize >= 0) {
            /* The preceding function-version guard also guards its code
             * object and hence the immutable frame size. */
            uop = _CHECK_STACK_SPACE_OPERAND;
            operand = callee_framesize;
            oparg = 0;
        }
        if (uop == _CHECK_FUNCTION_EXACT_ARGS && callee_argcount >= 0) {
            int self_index = stack_depth - (int)mi->oparg - 1;
            bool bound = opcode == CALL_BOUND_METHOD_EXACT_ARGS;
            bool null = self_index >= 0 &&
                state[locals_count + self_index].kind == METHOD_VALUE_NULL;
            if ((bound && callee_argcount == (int)mi->oparg + 1) ||
                (!bound && null && callee_argcount == (int)mi->oparg))
            {
                uop = _NOP;
            }
        }
        uop = method_optimize_guard(
            (int)uop, operand, mi->type_family, uop_state,
            locals_count, uop_stack_depth);
        if (uop == _IS_NONE && uop_stack_depth > 0 &&
            uop_state[locals_count + uop_stack_depth - 1].borrowed)
        {
            uop = _IS_NONE_BORROW;
        }
        if (uop == _PUSH_NULL_CONDITIONAL) {
            /* Resolve the static stack effect before assigning stack-cache
             * registers. */
            uop = (oparg & 1) ? _PUSH_NULL : _NOP;
        }
        if (uop == _POP_TOP && uop_stack_depth > 0 &&
            (opcode == STORE_FAST || opcode == STORE_FAST_LOAD_FAST ||
             opcode == STORE_FAST_STORE_FAST))
        {
            /* _SWAP_FAST leaves the previous local on top. Its facts are
             * exact here, including each component of a superinstruction. */
            uop = method_specialize_cleanup(
                uop_state[locals_count + uop_stack_depth - 1]);
        }
        if (opcode == POP_TOP && uop == _POP_TOP && uop_stack_depth > 0 &&
            method_close_cannot_escape(uop_state[locals_count + uop_stack_depth - 1]))
        {
            uop = method_specialize_cleanup(
                uop_state[locals_count + uop_stack_depth - 1]);
        }
        if ((uop == _POP_TOP_INT || uop == _POP_TOP_FLOAT ||
             uop == _POP_TOP_UNICODE) && uop_stack_depth > 0 &&
            (opcode == BINARY_OP_ADD_INT || opcode == BINARY_OP_SUBTRACT_INT ||
             opcode == BINARY_OP_MULTIPLY_INT || opcode == BINARY_OP_ADD_FLOAT ||
             opcode == BINARY_OP_SUBTRACT_FLOAT || opcode == BINARY_OP_MULTIPLY_FLOAT ||
             opcode == COMPARE_OP_INT || opcode == COMPARE_OP_FLOAT ||
             opcode == COMPARE_OP_STR))
        {
            /* These operations return both untouched inputs above the result.
             * Their cleanup must preserve borrowed and immortal ownership. */
            _PyMethodValue value = uop_state[locals_count + uop_stack_depth - 1];
            if (value.borrowed ||
                (value.kind == METHOD_VALUE_CONST && _Py_IsImmortal(value.object)))
            {
                uop = _POP_TOP_NOP;
            }
        }
        if ((opcode == TO_BOOL_INT || opcode == TO_BOOL_LIST ||
             opcode == TO_BOOL_STR || opcode == TO_BOOL_ALWAYS_TRUE) &&
            (uop == _POP_TOP || uop == _POP_TOP_INT ||
             uop == _POP_TOP_UNICODE) &&
            uop_stack_depth > 0 &&
            uop_state[locals_count + uop_stack_depth - 1].borrowed)
        {
            /* Specialized truth tests return the untouched input above the
             * boolean. A borrowed input needs no closing or escape check. */
            uop = _POP_TOP_NOP;
        }
        if (uop == _POP_TOP &&
            (opcode == LOAD_ATTR_SLOT || opcode == LOAD_ATTR_INSTANCE_VALUE ||
             opcode == LOAD_ATTR_INSTANCE_VALUE_NONDATA) &&
            stack_depth > 0 && state[locals_count + stack_depth - 1].borrowed)
        {
            /* These expansions return the receiver above the attribute.
             * Closing a borrowed receiver cannot escape or need a spill. */
            uop = _POP_TOP_NOP;
        }
        if (uop == _POP_TOP &&
            (opcode == BINARY_OP_SUBSCR_LIST_INT ||
             opcode == BINARY_OP_SUBSCR_TUPLE_INT) &&
            stack_depth >= 2 && state[locals_count + stack_depth - 2].borrowed)
        {
            uop = _POP_TOP_NOP;
        }
        if (uop == _POP_TOP_INT &&
            (opcode == BINARY_OP_SUBSCR_LIST_INT ||
             opcode == BINARY_OP_SUBSCR_TUPLE_INT) &&
            stack_depth >= 2 && state[locals_count + stack_depth - 1].borrowed)
        {
            uop = _POP_TOP_NOP;
        }
        if (i == skip_float_cleanup) {
            assert(uop == _POP_TOP_FLOAT);
            uop = _POP_TOP_NOP;
        }
        if (uop_stack_depth >= 2) {
            _PyMethodValue *stack = uop_state + locals_count;
            bool left = stack[uop_stack_depth - 2].unique;
            bool right = stack[uop_stack_depth - 1].unique;
            if (left || right) {
                switch (uop) {
                    case _BINARY_OP_ADD_FLOAT:
                        uop = left ? _BINARY_OP_ADD_FLOAT_INPLACE
                                   : _BINARY_OP_ADD_FLOAT_INPLACE_RIGHT;
                        break;
                    case _BINARY_OP_SUBTRACT_FLOAT:
                        uop = left ? _BINARY_OP_SUBTRACT_FLOAT_INPLACE
                                   : _BINARY_OP_SUBTRACT_FLOAT_INPLACE_RIGHT;
                        break;
                    case _BINARY_OP_MULTIPLY_FLOAT:
                        uop = left ? _BINARY_OP_MULTIPLY_FLOAT_INPLACE
                                   : _BINARY_OP_MULTIPLY_FLOAT_INPLACE_RIGHT;
                        break;
                }
                if (uop != (uint32_t)original_uop &&
                    (original_uop == _BINARY_OP_ADD_FLOAT ||
                     original_uop == _BINARY_OP_SUBTRACT_FLOAT ||
                     original_uop == _BINARY_OP_MULTIPLY_FLOAT)) {
                    skip_float_cleanup = i + (left ? 2 : 1);
                }
            }
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
        if (uop == _METHOD_ITER_NEXT_INLINE &&
            operand == (uintptr_t)PyEnum_Type.tp_iternext &&
            !method_emit(buffer, length, limit, _NOP, 0, 0, target))
        {
            return 0;
        }
        if (uop == _LOAD_ATTR_INSTANCE_VALUE && attribute_default != NULL) {
            uop = _LOAD_ATTR_INSTANCE_VALUE_OR_DEFAULT;
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
        if (uop == _GUARD_TYPE_VERSION_FAMILY) {
            buffer[*length - 1].operand1 = mi->alternate_versions[1] |
                ((uint64_t)mi->alternate_versions[2] << 32);
        }
        if (uop == _METHOD_SUBSCR_CHECK_FUNC) {
            buffer[*length - 1].operand1 = inline_version;
        }
        if (uop == _LOAD_ATTR_INSTANCE_VALUE_OR_DEFAULT) {
            buffer[*length - 1].operand1 = (uintptr_t)attribute_default;
        }
        if (uop == _LOAD_ATTR_SLOT || uop == _LOAD_ATTR_INSTANCE_VALUE) {
            _PyAttrCache *cache = (_PyAttrCache *)(
                bytecode + mi->opcode_offset + 1);
            buffer[*length - 1].operand1 = read_u32(cache->version) |
                ((uint64_t)(uop == _LOAD_ATTR_INSTANCE_VALUE) << 32);
        }
        else if (uop == _STORE_ATTR_SLOT_NOESCAPE ||
                 uop == _STORE_ATTR_INSTANCE_VALUE_NOESCAPE)
        {
            _PyAttrCache *cache = (_PyAttrCache *)(instr + 1);
            buffer[*length - 1].operand1 = read_u32(cache->version);
        }
        if (uop == _PUSH_FRAME) {
            PyFunctionObject *func = inline_depth && inline_version >= FUNC_VERSION_FIRST_VALID
                ? method_lookup_function(tstate->interp, inline_version, known_callee) : NULL;
            int inlined = 0;
            if (func != NULL) {
                const _PyMethodValue *arguments = NULL;
                int argument_count = 0;
                if (opcode == BINARY_OP_SUBSCR_GETITEM && stack_depth >= 2) {
                    arguments = state + locals_count + stack_depth - 2;
                    argument_count = 2;
                }
                else if (opcode == CALL_PY_EXACT_ARGS &&
                         callee_argcount >= 0 && callee_argcount <= stack_depth &&
                         (callee_argcount == (int)mi->oparg ||
                          callee_argcount == (int)mi->oparg + 1))
                {
                    /* The function/argument guards have proved whether the
                     * optional self slot is present. Bound-method bytecodes
                     * are excluded: they replace that slot during binding. */
                    arguments = state + locals_count + stack_depth - callee_argcount;
                    argument_count = callee_argcount;
                }
                else if (opcode == CALL_PY_GENERAL && callable_index >= 0 &&
                         state[locals_count + callable_index + 1].kind == METHOD_VALUE_NULL &&
                         callee_argcount >= (int)mi->oparg)
                {
                    /* The general binder has initialized the frame. Only
                     * positional arguments explicitly supplied after a
                     * proven NULL self slot have a known mapping here.
                     * Defaults, including mutable keyword defaults, remain
                     * unknown. Bound-method and keyword calls are excluded. */
                    arguments = state + locals_count + stack_depth - mi->oparg;
                    argument_count = (int)mi->oparg;
                }
                inlined = method_inline_small_cfg(
                    tstate, root_code, func, inline_depth,
                    arguments, argument_count, dependencies,
                    buffer, length, limit);
                Py_DECREF(func);
            }
            if (inlined < 0) {
                return inlined;
            }
            if (inlined > 0 && opcode == CALL_ALLOC_AND_ENTER_INIT &&
                !method_emit(buffer, length, limit, _METHOD_CALL, 2, 0, target))
            {
                return 0;
            }
            if (inlined == 0 && !method_emit(
                    buffer, length, limit, _METHOD_CALL,
                    opcode == CALL_ALLOC_AND_ENTER_INIT, 0, target)) {
                return 0;
            }
        }
        if (uop == _METHOD_POP_JUMP_IF_FALSE ||
            uop == _METHOD_POP_JUMP_IF_TRUE ||
            uop == _METHOD_FOR_ITER ||
            uop == _METHOD_ITER_NEXT_INLINE ||
            uop == _METHOD_ITER_JUMP_LIST ||
            uop == _METHOD_ITER_JUMP_TUPLE ||
            uop == _METHOD_ITER_JUMP_RANGE)
        {
            direct_jump_index = *length - 1;
        }
    }
    if (initializer_jump >= 0) {
        buffer[initializer_jump].operand1 = (uint64_t)*length | METHOD_TARGET_OFFSET_FLAG;
        if (!method_emit(buffer, length, limit, _METHOD_LABEL, 0, 0, orig_target)) {
            return 0;
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

/* A static method may be called with sibling subclasses which share an
 * attribute layout or inherited method. Validate a bounded set of already
 * cached types, without executing Python or observing a live activation.
 * Every accepted version independently protects the same lookup semantics.
 * No exact receiver type may be inferred from this disjunction. */
static void
method_find_attribute_family(PyCodeObject *code, _PyMethodInstruction *mi)
{
#ifndef Py_GIL_DISABLED
    int opcode = mi->opcode;
    bool instance = opcode == LOAD_ATTR_INSTANCE_VALUE ||
        opcode == STORE_ATTR_INSTANCE_VALUE;
    bool slot = opcode == LOAD_ATTR_SLOT || opcode == STORE_ATTR_SLOT;
    bool method = opcode == LOAD_ATTR_METHOD_WITH_VALUES ||
        opcode == LOAD_ATTR_METHOD_NO_DICT;
    if (!instance && !slot && !method) {
        return;
    }
    bool store = _PyOpcode_Deopt[opcode] == STORE_ATTR;
    _PyAttrCache *cache = (_PyAttrCache *)(
        method_bytecode(code) + mi->opcode_offset + 1);
    unsigned int version = read_u32(cache->version);
    PyTypeObject *original = _PyType_LookupByVersion(version);
    if (original == NULL || original->tp_base == NULL ||
        original->tp_base == &PyBaseObject_Type ||
        original->tp_getattro != PyObject_GenericGetAttr ||
        (store && original->tp_setattro != PyObject_GenericSetAttr))
    {
        return;
    }
    PyObject *name = PyTuple_GET_ITEM(
        code->co_names, store ? mi->oparg : mi->oparg >> 1);
    PyObject *descriptor = _PyType_LookupRef(original, name);
    /* Mutable non-data descriptor types need their own extra guard. */
    if (instance && descriptor != NULL) {
        Py_DECREF(descriptor);
        return;
    }
    PyInterpreterState *interp = _PyInterpreterState_GET();
    int count = 0;
    for (int i = 0; i < TYPE_VERSION_CACHE_SIZE && count < 3; i++) {
        PyTypeObject *type = interp->types.type_version_cache[i];
        if (type == NULL || type == original || type->tp_version_tag == 0 ||
            type->tp_base != original->tp_base ||
            type->tp_getattro != PyObject_GenericGetAttr ||
            (store && type->tp_setattro != PyObject_GenericSetAttr))
        {
            continue;
        }
        PyObject *other = _PyType_LookupRef(type, name);
        bool same = other == descriptor;
        bool python_method = method && descriptor != NULL && other != NULL &&
            PyFunction_Check(descriptor) && PyFunction_Check(other);
        Py_XDECREF(other);
        if (!same && !python_method) {
            continue;
        }
        if (instance || opcode == LOAD_ATTR_METHOD_WITH_VALUES) {
            if (!(type->tp_flags & Py_TPFLAGS_INLINE_VALUES) ||
                !(type->tp_flags & Py_TPFLAGS_HEAPTYPE))
            {
                continue;
            }
            Py_ssize_t index = _PyDictKeys_StringLookup(
                ((PyHeapTypeObject *)type)->ht_cached_keys, name);
            if (instance) {
                if (index < 0 || type->tp_basicsize +
                    (Py_ssize_t)offsetof(PyDictValues, values) +
                    index * (Py_ssize_t)sizeof(PyObject *) != cache->index)
                {
                    continue;
                }
            }
            else if (index >= 0) {
                continue;
            }
        }
        else if (opcode == LOAD_ATTR_METHOD_NO_DICT && type->tp_dictoffset != 0) {
            continue;
        }
        /* The identical slot descriptor has the same offset and semantics. */
        mi->alternate_versions[count++] = type->tp_version_tag;
        mi->dynamic_method |= !same;
    }
    Py_XDECREF(descriptor);
#endif
}

static int
method_decode_cfg(
    PyCodeObject *code,
    _Py_CODEUNIT *bytecode,
    int entry_offset,
    int osr_offset,
    _PyMethodInstruction *instructions,
    int *instruction_count,
    int16_t *offset_to_instruction,
    _PyMethodBlock *blocks,
    int *block_count,
    int16_t *instruction_to_block)
{
    int code_size = (int)Py_SIZE(code);
#ifndef Py_GIL_DISABLED
    /* Intern small disjunctions so dataflow can recognize the same guard
     * without retaining a type pointer or enlarging every abstract value.
     * The bound limits compilation work; further sets simply stay unknown. */
    uint32_t families[32][4];
    int family_count = 0;
#endif
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
    for (int offset = entry_offset; offset < code_size;) {
        int start = offset;
        uint32_t oparg = 0;
        int opcode;
        do {
            _Py_CODEUNIT instruction = bytecode[offset];
            if (instruction.op.code == ENTER_EXECUTOR) {
                int index = instruction.op.arg;
                if (code->co_executors == NULL ||
                    index >= code->co_executors->size ||
                    code->co_executors->executors[index] == NULL)
                {
                    PyMem_Free(block_start);
                    return 0;
                }
                _PyExecutorObject *executor = code->co_executors->executors[index];
                instruction.op.code = executor->vm_data.opcode;
                instruction.op.arg = executor->vm_data.oparg;
            }
            /* An installed loop executor may replace the first EXTENDED_ARG,
             * rather than the jump opcode. Decode it before joining prefixes. */
            opcode = instruction.op.code;
            oparg = (oparg << 8) | instruction.op.arg;
            if (opcode == EXTENDED_ARG) {
                offset++;
                if (offset >= code_size || oparg > UINT16_MAX) {
                    PyMem_Free(block_start);
                    return 0;
                }
            }
        } while (opcode == EXTENDED_ARG);

        int deopt = _PyOpcode_Deopt[opcode];
#ifdef Py_GIL_DISABLED
        if (_PyInterpreterState_GET()->jit_multithreaded &&
            (deopt == LOAD_GLOBAL || deopt == LOAD_ATTR ||
             deopt == STORE_ATTR || deopt == CALL))
        {
            opcode = deopt;
        }
#endif
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
        method_find_attribute_family(code, &instructions[count]);
#ifndef Py_GIL_DISABLED
        _PyMethodInstruction *mi = &instructions[count];
        if (mi->alternate_versions[0]) {
            _PyAttrCache *cache = (_PyAttrCache *)(bytecode + offset + 1);
            uint32_t versions[4] = {
                read_u32(cache->version), mi->alternate_versions[0],
                mi->alternate_versions[1], mi->alternate_versions[2],
            };
            /* The inline cache may name a different member of the same set
             * at each attribute site. Canonicalize before comparing sets. */
            for (int i = 1; i < 4; i++) {
                uint32_t version = versions[i];
                int j = i;
                while (j > 0 && versions[j - 1] > version) {
                    versions[j] = versions[j - 1];
                    j--;
                }
                versions[j] = version;
            }
            int index = 0;
            while (index < family_count &&
                   memcmp(families[index], versions, sizeof(versions)) != 0) {
                index++;
            }
            if (index < (int)Py_ARRAY_LENGTH(families)) {
                if (index == family_count) {
                    memcpy(families[family_count++], versions, sizeof(versions));
                }
                mi->type_family = (uint16_t)(index + 1);
            }
        }
#endif
        offset_to_instruction[start] = (int16_t)count;
        count++;
        offset = next;
    }
    if (count == 0) {
        PyMem_Free(block_start);
        return 0;
    }

    block_start[entry_offset] = 1;
    if (osr_offset >= 0) {
        if (osr_offset >= code_size ||
            offset_to_instruction[osr_offset] < 0)
        {
            PyMem_Free(block_start);
            return 0;
        }
        block_start[osr_offset] = 1;
    }
    /* Compile normal control flow in protected regions. Errors return to
     * Tier 1 with the real frame and bytecode position; handler entries do
     * not become additional roots of this CFG. Keep protection boundaries
     * as block boundaries so region lowering cannot move errors between
     * different handlers. Reject malformed tables rather than reading past
     * their end during compilation. */
    const unsigned char *table = (const unsigned char *)
        PyBytes_AS_STRING(code->co_exceptiontable);
    const unsigned char *table_end = table + PyBytes_GET_SIZE(code->co_exceptiontable);
    while (table < table_end) {
        unsigned int fields[4] = {0};
        for (int field = 0; field < 4; field++) {
            unsigned char byte;
            do {
                if (table == table_end || fields[field] > (UINT_MAX >> 6)) {
                    PyMem_Free(block_start);
                    return 0;
                }
                byte = *table++;
                fields[field] = (fields[field] << 6) | (byte & 63);
            } while (byte & 64);
        }
        unsigned int start = fields[0], size = fields[1], handler = fields[2];
        if (start >= (unsigned int)code_size ||
            size > (unsigned int)code_size - start ||
            handler >= (unsigned int)code_size ||
            offset_to_instruction[start] < 0 ||
            offset_to_instruction[handler] < 0 ||
            (start + size < (unsigned int)code_size &&
             offset_to_instruction[start + size] < 0))
        {
            PyMem_Free(block_start);
            return 0;
        }
        block_start[start] = block_start[handler] = 1;
        if (start + size < (unsigned int)code_size) {
            block_start[start + size] = 1;
        }
    }
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
             opcode == RETURN_VALUE || opcode == YIELD_VALUE ||
             opcode == RAISE_VARARGS ||
             opcode == RERAISE) && next < code_size)
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
        else if (opcode == RAISE_VARARGS || opcode == RERAISE) {
            blocks[b].terminator = METHOD_RAISE;
        }
        else if (opcode == YIELD_VALUE) {
            /* Resumption is a new interpreter activation, not a CFG edge.
             * In particular, no facts may survive a caller's send/throw or
             * writes through the suspended frame's locals proxy. */
            blocks[b].terminator = METHOD_SUSPEND;
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
    PyFunctionObject *func,
    PyCodeObject *code,
    const _PyMethodInstruction *instructions,
    _PyMethodBlock *blocks,
    int block_count,
    _PyMethodValue *states,
    int state_width,
    int locals_count,
    int stack_capacity,
    int entry_block,
    int entry_depth,
    bool is_osr,
    const _PyMethodValue *entry_values)
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

    _PyMethodValue *entry = states + entry_block * state_width;
    int arguments = code->co_argcount + code->co_kwonlyargcount +
        !!(code->co_flags & CO_VARARGS) + !!(code->co_flags & CO_VARKEYWORDS);
    for (int i = 0; i < locals_count; i++) {
        _PyLocals_Kind kind = _PyLocals_GetKind(code->co_localspluskinds, i);
        /* Cell creation and free-variable binding precede the entry RESUME
         * and have already run in Tier 1. Their slots are live even when
         * they are not arguments. Never treat them as empty locals. */
        entry[i] = (is_osr || i < arguments ||
                    (kind & (CO_FAST_CELL | CO_FAST_FREE)))
            ? method_value_unknown() : method_value_null();
        if (entry_values != NULL && entry_values[i].kind == METHOD_VALUE_TYPE) {
            entry[i] = entry_values[i];
        }
    }
    /* OSR accepts the interpreter's live stack. No value, ownership, or
     * type facts from this particular activation are assumed by the CFG. */
    for (int i = 0; i < entry_depth; i++) {
        entry[locals_count + i] = method_value_unknown();
    }
    blocks[entry_block].initialized = 1;
    blocks[entry_block].in_queue = 1;
    blocks[entry_block].stack_depth = entry_depth;
    int head = 0;
    int tail = 0;
    int count = 1;
    queue[tail++] = entry_block;
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
                        func, code, mi, jump, locals_count, stack_capacity,
                        &jump_depth, true) ||
                    !method_apply_stack_effect(
                        func, code, mi, fallthrough, locals_count, stack_capacity,
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
                    func, code, mi, fallthrough, locals_count, stack_capacity,
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
method_inline_small_cfg(
    PyThreadState *tstate,
    PyCodeObject *root_code,
    PyFunctionObject *func,
    int inline_depth,
    const _PyMethodValue *arguments,
    int argument_count,
    _PyBloomFilter *dependencies,
    _PyUOpInstruction *buffer,
    int *length,
    int limit)
{
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    assert(inline_depth > 0);
    if (func->vectorcall != _PyFunction_Vectorcall ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_GENERATOR | CO_COROUTINE |
                           CO_ASYNC_GENERATOR | CO_VARARGS |
                           CO_VARKEYWORDS)) ||
        Py_SIZE(code) <= 0 || Py_SIZE(code) > INT16_MAX)
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
    _PyMethodValue *states = NULL;
    _PyMethodValue *state = NULL;
    _PyMethodValue *uop_state = NULL;
    if (instructions == NULL || blocks == NULL ||
        offset_to_instruction == NULL || instruction_to_block == NULL)
    {
        PyErr_NoMemory();
        goto error;
    }

    _Py_CODEUNIT *bytecode = method_bytecode(code);
    int instruction_count = 0;
    int block_count = 0;
    int decoded = method_decode_cfg(
        code, bytecode, 0, -1, instructions, &instruction_count,
        offset_to_instruction, blocks, &block_count,
        instruction_to_block);
    if (decoded < 0) {
        goto error;
    }
    /* Inline caches add no executable work. Attribute-heavy callees may
     * have a small CFG despite occupying many bytecode units. The caller's
     * uop budget still bounds the generated expansion. */
    bool closure_prefix = decoded > 0 && instruction_count > 1 &&
        instructions[0].opcode == COPY_FREE_VARS &&
        code->co_ncellvars == 0 &&
        _PyOpcode_Deopt[instructions[1].opcode] == RESUME;
    if (decoded == 0 ||
        instruction_count > METHOD_INLINE_MAX_INSTRUCTIONS ||
        (inline_depth < METHOD_INLINE_MAX_DEPTH && instruction_count > 48) ||
        (_PyOpcode_Deopt[instructions[0].opcode] != RESUME && !closure_prefix))
    {
        goto unsupported;
    }

    int locals_count = code->co_nlocalsplus;
    int stack_capacity = code->co_stacksize;
    int state_width = locals_count + stack_capacity;
    if (state_width <= 0) {
        goto unsupported;
    }
    states = PyMem_Calloc((size_t)block_count * state_width, sizeof(*states));
    state = PyMem_Calloc((size_t)state_width, sizeof(*state));
    uop_state = PyMem_Calloc((size_t)state_width, sizeof(*uop_state));
    if (states == NULL || state == NULL || uop_state == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    if (arguments != NULL && argument_count <= code->co_argcount) {
        for (int i = 0; i < argument_count; i++) {
            PyTypeObject *type = method_value_get_stable_type(arguments[i]);
            if (type != NULL) {
                /* These facts were proved in the caller's CFG. Do not carry
                 * identity, compactness, ownership, or mutable heap types
                 * into a separately analyzed callee. */
                state[i] = method_value_type(type, false);
            }
        }
    }
    int analyzed = method_analyze_cfg(
        func, code, instructions, blocks, block_count, states, state_width,
        locals_count, stack_capacity, 0, 0, false, state);
    if (analyzed < 0) {
        goto error;
    }
    if (analyzed == 0) {
        goto unsupported;
    }
    bool has_return = false;
    for (int b = 0; b < block_count; b++) {
        _PyMethodBlock *block = &blocks[b];
        if (!block->initialized) {
            continue;
        }
        /* Bound both nesting and code size. Small nested callees can share
         * the native caller, while their Python frames remain observable. */
        memcpy(state, states + b * state_width,
               (size_t)state_width * sizeof(*state));
        int stack_depth = block->stack_depth;
        block->uop_offset = (uint16_t)*length;
        if (!method_emit(buffer, length, limit, _METHOD_LABEL,
                         Py_MIN(stack_depth, 2), 0, 0)) {
            goto unsupported;
        }
        bool supported = true;
        for (int i = block->first; i <= block->last; i++) {
            _PyMethodInstruction *mi = &instructions[i];
            if (i == block->last && block->terminator == METHOD_RETURN) {
                if (!method_emit(buffer, length, limit, _SET_IP, 0,
                                 (uintptr_t)(bytecode + mi->opcode_offset), mi->offset) ||
                    !method_emit(buffer, length, limit, _MAKE_HEAP_SAFE,
                                 0, 0, mi->offset) ||
                    !method_emit(buffer, length, limit,
                                 locals_count <= 4 ? _METHOD_RETURN_VALUE : _RETURN_VALUE,
                                 locals_count <= 4 ? (uint16_t)locals_count : 0,
                                 0, mi->offset) ||
                    !method_emit(buffer, length, limit, _METHOD_JUMP,
                                 0, 0, mi->offset))
                {
                    goto unsupported;
                }
                buffer[*length - 1].operand1 = UINT64_MAX;
                has_return = true;
                break;
            }
            if (i == block->last && block->terminator == METHOD_JUMP) {
                int opcode = _PyOpcode_Deopt[mi->opcode];
                if (opcode == JUMP_BACKWARD &&
                    opcode != JUMP_FORWARD &&
                    !method_emit(buffer, length, limit, _CHECK_PERIODIC,
                                 0, 0, mi->offset))
                {
                    goto unsupported;
                }
                if (!method_emit(buffer, length, limit, _METHOD_JUMP,
                                 0, 0, mi->offset))
                {
                    goto unsupported;
                }
                buffer[*length - 1].operand1 = (uint64_t)block->target;
                break;
            }
            int instruction_start = *length;
            int translated = method_translate_instruction(
                tstate, root_code, dependencies, inline_depth - 1,
                func, code, bytecode, mi, i == block->last ? block->target : -1,
                state, locals_count, stack_depth, stack_capacity, uop_state,
                buffer, length, limit);
            if (translated < 0) {
                goto error;
            }
            if (translated == 0) {
                /* A cold unsupported arm need not prevent inlining the
                 * useful paths. The callee frame is still current here;
                 * resume its bytecode with its original stack and locals. */
                *length = instruction_start;
                if (!method_emit(buffer, length, limit, _METHOD_DEOPT,
                                 0, 0, mi->offset)) {
                    goto unsupported;
                }
                supported = false;
                break;
            }
            if (!method_apply_stack_effect(
                    func, code, mi, state, locals_count, stack_capacity,
                    &stack_depth, false))
            {
                goto unsupported;
            }
        }
        if (!supported) {
            continue;
        }
        if (block->terminator == METHOD_BRANCH ||
            block->terminator == METHOD_FALLTHROUGH)
        {
            if (block->fallthrough < 0 ||
                !method_emit(buffer, length, limit, _METHOD_JUMP,
                             0, 0, instructions[block->last].offset))
            {
                goto unsupported;
            }
            buffer[*length - 1].operand1 = (uint64_t)block->fallthrough;
        }
    }
    if (!has_return) {
        goto unsupported;
    }
    int optimized_length = method_optimize_blocks(
        func, buffer, *length, limit - 1, blocks, block_count,
        states, state_width, dependencies);
    if (optimized_length < 0) {
        goto error;
    }
    *length = optimized_length;
    /* Returns join at the caller continuation with an empty cache ABI. */
    int continuation = *length;
    if (!method_emit(buffer, length, limit, _METHOD_LABEL, 0, 0, 0)) {
        goto unsupported;
    }
    /* Resolve local block numbers before the callee CFG is freed. */
    for (int pc = start_length; pc < continuation; pc++) {
        if (!method_is_edge(buffer[pc].opcode)) {
            continue;
        }
        uint64_t target = buffer[pc].operand1;
        if (target == UINT64_MAX) {
            target = (uint64_t)continuation;
        }
        else if (target & METHOD_TARGET_OFFSET_FLAG) {
            /* A nested callee already resolved its own local block numbers. */
            continue;
        }
        else {
            if (target >= (uint64_t)block_count || !blocks[target].initialized) {
                goto unsupported;
            }
            target = blocks[target].uop_offset;
        }
        buffer[pc].operand1 = target | METHOD_TARGET_OFFSET_FLAG;
    }
    _Py_BloomFilter_Add(dependencies, func);
    _Py_BloomFilter_Add(dependencies, code);
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 1;

unsupported:
    *length = start_length;
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return 0;

error:
    *length = start_length;
    PyMem_Free(instructions);
    PyMem_Free(blocks);
    PyMem_Free(offset_to_instruction);
    PyMem_Free(instruction_to_block);
    PyMem_Free(states);
    PyMem_Free(state);
    PyMem_Free(uop_state);
    return -1;
}

#include "optimizer_regions.h"

/* Ignore only metadata and labels with one predecessor. A matched body must
 * have no entry that bypasses its unpack or comparison. */
static int
method_scan_next(_PyUOpInstruction *input, int length, int pc,
                 const uint16_t *predecessors)
{
    while (pc < length) {
        int op = input[pc].opcode;
        if (op == _NOP || op == _SET_IP || op == _CHECK_VALIDITY ||
            (op == _METHOD_LABEL && predecessors[pc] <= 1))
        {
            pc++;
            continue;
        }
        break;
    }
    return pc;
}

static void
method_fuse_enum_scans(_PyUOpInstruction *input, int length,
                      const uint16_t *predecessors)
{
    for (int next = 1; next < length; next++) {
        if (input[next].opcode != _METHOD_ITER_NEXT_INLINE ||
            input[next].operand0 != (uintptr_t)PyEnum_Type.tp_iternext ||
            input[next - 1].opcode != _NOP)
        {
            continue;
        }
        int header = next - 2;
        while (header >= 0 && (input[header].opcode == _NOP ||
               input[header].opcode == _CHECK_VALIDITY ||
               input[header].opcode == _SET_IP))
        {
            header--;
        }
        if (header < 0 || input[header].opcode != _METHOD_LABEL) {
            continue;
        }
        int pc = next + 1;
        int index_local, item_local, key_local, field, mask;
#define SCAN_NEXT() \
        (pc = method_scan_next(input, length, pc, predecessors))
#define SCAN_EXPECT(OP) \
        do { \
            if (SCAN_NEXT() >= length || input[pc].opcode != (OP)) { \
                goto no_scan; \
            } \
            pc++; \
        } while (0)
#define SCAN_OPTIONAL(OP) \
        do { \
            if (SCAN_NEXT() < length && input[pc].opcode == (OP)) { \
                pc++; \
            } \
        } while (0)
        SCAN_OPTIONAL(_GUARD_TOS_TUPLE);
        SCAN_EXPECT(_UNPACK_SEQUENCE_TWO_TUPLE);
        SCAN_EXPECT(_SWAP_FAST);
        index_local = input[pc - 1].oparg;
        SCAN_EXPECT(_POP_TOP);
        SCAN_EXPECT(_SWAP_FAST);
        item_local = input[pc - 1].oparg;
        SCAN_EXPECT(_POP_TOP);
        SCAN_EXPECT(_LOAD_FAST_BORROW);
        if (input[pc - 1].oparg != item_local) {
            continue;
        }
        if (SCAN_NEXT() >= length || !region_small_int(&input[pc], &field)) {
            continue;
        }
        pc++;
        SCAN_OPTIONAL(_GUARD_NOS_TUPLE);
        SCAN_EXPECT(_GUARD_BINARY_OP_SUBSCR_TUPLE_INT_BOUNDS);
        SCAN_EXPECT(_BINARY_OP_SUBSCR_TUPLE_INT);
        if (SCAN_NEXT() >= length ||
            (input[pc].opcode != _POP_TOP_INT && input[pc].opcode != _POP_TOP_NOP))
        {
            continue;
        }
        pc++;
        if (SCAN_NEXT() >= length ||
            (input[pc].opcode != _POP_TOP && input[pc].opcode != _POP_TOP_NOP))
        {
            continue;
        }
        pc++;
        SCAN_EXPECT(_LOAD_FAST_BORROW);
        key_local = input[pc - 1].oparg;
        SCAN_OPTIONAL(_GUARD_TOS_INT);
        SCAN_OPTIONAL(_GUARD_NOS_INT);
        SCAN_EXPECT(_COMPARE_OP_INT);
        mask = input[pc - 1].oparg & 15;
        for (int i = 0; i < 2; i++) {
            if (SCAN_NEXT() >= length ||
                (input[pc].opcode != _POP_TOP_INT &&
                 input[pc].opcode != _POP_TOP_NOP))
            {
                goto no_scan;
            }
            pc++;
        }
        if (SCAN_NEXT() >= length ||
            (input[pc].opcode != _METHOD_POP_JUMP_IF_TRUE &&
             input[pc].opcode != _METHOD_POP_JUMP_IF_FALSE))
        {
            continue;
        }
        /* Only batch the fallthrough continue path. The taken path, including
         * its reference releases and returned values, is always executed
         * by the original uops. */
        if (input[pc].opcode == _METHOD_POP_JUMP_IF_TRUE) {
            mask ^= 15;
        }
        pc++;
        SCAN_EXPECT(_CHECK_PERIODIC);
        SCAN_EXPECT(_METHOD_JUMP);
        if (input[pc - 1].operand1 != (uint64_t)header ||
            index_local > 255 || item_local > 255 || key_local > 255 ||
            index_local == item_local || index_local == key_local ||
            item_local == key_local)
        {
            continue;
        }
        input[next - 1].opcode = _ENUM_LIST_INT_SCAN;
        input[next - 1].oparg = mask;
        input[next - 1].operand0 = key_local | (index_local << 8) |
                                  (item_local << 16);
        input[next - 1].operand1 = field;
no_scan:
        ;
#undef SCAN_NEXT
#undef SCAN_EXPECT
#undef SCAN_OPTIONAL
    }
}

/* Reuse the symbolic uop optimizer on straight-line portions of the static
 * CFG. Inlined callees are optimized separately with their own local namespace.
 * Stop before a frame-producing operation. Shortened blocks retain their old
 * offsets; growing blocks relocate labels and already-resolved inline edges. */
static int
method_optimize_blocks(PyFunctionObject *func, _PyUOpInstruction *input,
                       int length, int limit,
                       _PyMethodBlock *blocks, int block_count,
                       const _PyMethodValue *states, int state_width,
                       _PyBloomFilter *dependencies)
{
#ifdef Py_GIL_DISABLED
    /* Watchers run inside mutations, not around their entire transaction.
     * A concurrent compilation could otherwise install a folded value after
     * its invalidation callback but before the mutation has completed. Keep
     * runtime guards/loads until dependency publication has that contract. */
    if (_PyInterpreterState_GET()->jit_multithreaded) {
        return length;
    }
#endif
    JitOptContext *ctx = NULL;
    _PyUOpInstruction *scratch = NULL;
    _PyUOpInstruction *optimized = NULL;
    for (int b = 0; b < block_count; b++) {
        if (!blocks[b].initialized) {
            continue;
        }
        int start = blocks[b].uop_offset + 1;
        int end = length;
        for (int next = b + 1; next < block_count; next++) {
            if (blocks[next].initialized) {
                end = blocks[next].uop_offset;
                break;
            }
        }
        for (int pc = start; pc < end; pc++) {
            int opcode = input[pc].opcode;
            if (opcode == _INIT_CALL_PY_EXACT_ARGS ||
                opcode == _BINARY_OP_SUBSCR_INIT_CALL ||
                opcode == _PY_FRAME_GENERAL || opcode == _PY_FRAME_KW ||
                opcode == _PY_FRAME_EX || opcode == _CREATE_INIT_FRAME ||
                opcode == _PUSH_FRAME ||
                opcode == _METHOD_CALL ||
                opcode == _METHOD_LABEL ||
                opcode == _YIELD_VALUE)
            {
                end = pc;
                break;
            }
            if (method_is_edge(opcode) || opcode == _METHOD_DEOPT ||
                opcode == _RETURN_VALUE || opcode == _METHOD_RETURN_VALUE ||
                is_terminator(&input[pc]))
            {
                end = pc;
                break;
            }
        }
        if (end - start < 3) {
            continue;
        }
        if (ctx == NULL) {
            ctx = PyMem_Calloc(1, sizeof(*ctx));
            scratch = PyMem_Calloc(UOP_MAX_TRACE_LENGTH, sizeof(*scratch));
            optimized = PyMem_Calloc(UOP_MAX_TRACE_LENGTH, sizeof(*optimized));
            if (ctx == NULL || scratch == NULL || optimized == NULL) {
                PyMem_Free(ctx);
                PyMem_Free(scratch);
                PyMem_Free(optimized);
                PyErr_NoMemory();
                return -1;
            }
        }
        int count = end - start;
        memcpy(scratch, input + start, count * sizeof(*scratch));
        scratch[count] = (_PyUOpInstruction){
            .opcode = _DEOPT, .format = UOP_FORMAT_TARGET,
        };
        int result = _Py_uop_optimize_method_block(
            func, ctx, scratch, count + 1, blocks[b].stack_depth,
            states + b * state_width, optimized, dependencies);
        if (result <= 0 || optimized[result - 1].opcode != _DEOPT)
        {
            continue;
        }
        int live = 0;
        for (int pc = 0; pc < result - 1; pc++) {
            if (optimized[pc].opcode != _NOP) {
                optimized[live++] = optimized[pc];
            }
        }
        if (live > count) {
            int extra = live - count;
            if (length + extra > limit) {
                continue;
            }
            memmove(input + end + extra, input + end,
                    (length - end) * sizeof(*input));
            length += extra;
            for (int next = b + 1; next < block_count; next++) {
                if (blocks[next].initialized) {
                    blocks[next].uop_offset += extra;
                }
            }
            for (int pc = 0; pc < length; pc++) {
                if (pc >= start && pc < end + extra) {
                    continue;
                }
                /* UINT64_MAX is an unresolved enclosing callee return,
                 * not an absolute offset to relocate while growing a
                 * nested callee. Adding to it would wrap the sentinel. */
                if (method_is_edge(input[pc].opcode) &&
                    input[pc].operand1 != UINT64_MAX &&
                    (input[pc].operand1 & METHOD_TARGET_OFFSET_FLAG))
                {
                    uint64_t target = input[pc].operand1 & ~METHOD_TARGET_OFFSET_FLAG;
                    if (target >= (uint64_t)end) {
                        input[pc].operand1 = (target + extra) | METHOD_TARGET_OFFSET_FLAG;
                    }
                }
            }
            end += extra;
        }
        result = live;
        memcpy(input + start, optimized, result * sizeof(*input));
        for (int pc = start + result; pc < end; pc++) {
            input[pc].opcode = _NOP;
        }
    }
    PyMem_Free(ctx);
    PyMem_Free(scratch);
    PyMem_Free(optimized);
    return length;
}

static void
method_fuse_global_identity(_PyUOpInstruction *input, int length)
{
    for (int pc = 0; pc < length; pc++) {
        if (input[pc].opcode != _LOAD_GLOBAL_BINDING) {
            continue;
        }
        int compare = pc + 1;
        while (compare < length &&
               (input[compare].opcode == _NOP || input[compare].opcode == _SET_IP))
        {
            compare++;
        }
        if (compare >= length || input[compare].opcode != _IS_OP) {
            continue;
        }
        int pop = compare + 1;
        while (pop < length && input[pop].opcode == _NOP) {
            pop++;
        }
        if (pop >= length || input[pop].opcode != _POP_TOP) {
            continue;
        }
        /* The watched dictionary keeps the right operand alive. No escape,
         * guard exit or CFG edge occurs between its load and its cleanup,
         * so its temporary reference can be omitted. Keep the left operand's
         * cleanup in its original position: it may run a finalizer. */
        input[compare].opcode = _IS_GLOBAL_BINDING;
        input[compare].operand0 = input[pc].operand0;
        input[pc].opcode = _NOP;
        input[pop].opcode = _NOP;
    }
}

static bool
method_prune_unreachable(
    _PyUOpInstruction *input,
    int input_length,
    const _PyMethodBlock *blocks,
    int block_count,
    bool continuation)
{
    /* Bytecode reachability includes paths past unsupported operations.
     * Those paths cannot be reached by the native method. Resolve edges
     * before traversing the native CFG, including inlined return edges. */
    for (int pc = 0; pc < input_length; pc++) {
        if (!method_is_edge(input[pc].opcode)) {
            continue;
        }
        uint64_t target = input[pc].operand1;
        if (target & METHOD_TARGET_OFFSET_FLAG) {
            target &= ~METHOD_TARGET_OFFSET_FLAG;
        }
        else {
            if (target >= (uint64_t)block_count || !blocks[target].initialized) {
                return 0;
            }
            target = blocks[target].uop_offset;
        }
        if (target >= (uint64_t)input_length) {
            return 0;
        }
        input[pc].operand1 = target;
        assert(input[target].opcode == _METHOD_LABEL);
    }
    bool reachable[UOP_MAX_TRACE_LENGTH] = {true};
    uint16_t pending[UOP_MAX_TRACE_LENGTH] = {0};
    int count = 1;
    while (count) {
        int pc = pending[--count];
        int opcode = input[pc].opcode;
        if (method_is_edge(opcode)) {
            int target = (int)input[pc].operand1;
            if (!reachable[target]) {
                reachable[target] = true;
                pending[count++] = (uint16_t)target;
            }
        }
        if (pc + 1 < input_length && opcode != _METHOD_JUMP &&
            opcode != _METHOD_DEOPT && opcode != _METHOD_EXIT &&
            opcode != _METHOD_YIELD_EXIT && !is_terminator(&input[pc]) &&
            !reachable[pc + 1])
        {
            reachable[pc + 1] = true;
            pending[count++] = (uint16_t)(pc + 1);
        }
    }
    int useful = 0;
    for (int pc = 0; pc < input_length; pc++) {
        if (!reachable[pc]) {
            /* Preserve offsets until stack allocation remaps the edges. */
            input[pc].opcode = _NOP;
            continue;
        }
        switch (input[pc].opcode) {
            case _NOP:
            case _START_EXECUTOR:
            case _MAKE_WARM:
            case _METHOD_PROFILE:
            case _METHOD_LABEL:
            case _METHOD_JUMP:
            case _METHOD_DEOPT:
            case _DEOPT:
            case _CHECK_VALIDITY:
            case _CHECK_PERIODIC:
            case _TIER2_RESUME_CHECK:
            case _SET_IP:
            case _POP_TOP:
            case _SWAP_FAST:
            case _STORE_FAST_NOESCAPE:
                break;
            default:
                useful++;
                break;
        }
    }
    /* Entering and leaving native code for a single operation (for example
     * LIST_APPEND after a generator yield) costs more than its dispatch.
     * Require some work between the two interpreter transitions. */
    return useful >= (continuation ? 2 : 1);
}

static int
method_finish_uops(
    _PyUOpInstruction *input,
    int input_length,
    _PyUOpInstruction *output,
    uint16_t *offset_map,
    bool partial_method,
    bool continuation)
{
    bool block_start[UOP_MAX_TRACE_LENGTH] = {false};
    uint16_t predecessors[UOP_MAX_TRACE_LENGTH] = {0};
    for (int pc = 0; pc < input_length; pc++) {
        if (input[pc].opcode == _METHOD_LABEL) {
            block_start[pc] = true;
        }
        if (method_is_edge(input[pc].opcode)) {
            predecessors[input[pc].operand1]++;
        }
    }
    /* Elide an adjacent edge with one predecessor. The remaining label
     * still enforces its entry convention for physical fallthrough. */
    for (int pc = 0; pc + 1 < input_length; pc++) {
        if (input[pc].opcode == _METHOD_JUMP &&
            input[pc].operand1 == (uint64_t)(pc + 1) &&
            predecessors[pc + 1] == 1)
        {
            input[pc].opcode = _NOP;
        }
    }
#ifdef Py_GIL_DISABLED
    if (!_PyInterpreterState_GET()->jit_multithreaded)
#endif
    {
        method_fuse_enum_scans(input, input_length, predecessors);
    }
    /* Region lowering must never cross an incoming CFG edge. */
    for (int start = 0; start < input_length;) {
        int end = start + 1;
        while (end < input_length && !block_start[end]) {
            end++;
        }
        lower_int_attribute_updates(input + start, end - start);
        lower_constant_attribute_stores(input + start, end - start);
        lower_bounded_int_regions(input + start, end - start);
        lower_len_regions(input + start, end - start);
        lower_tuple_comparisons(input + start, end - start);
#ifdef Py_GIL_DISABLED
        if (!_PyInterpreterState_GET()->jit_multithreaded)
#endif
        {
            fuse_list_pair_comparisons(input + start, end - start);
        }
        fuse_list_length_predicates(input + start, end - start);
        lower_float_attribute_products(input + start, end - start);
        lower_int_attribute_comparisons(input + start, end - start);
        fuse_borrowed_input_cleanup(input + start, end - start);
        /* A resumed generator-loop body has unknown old locals. A fused
         * unpack would exit before doing any work whenever their cleanup
         * can run Python. Keep individual stores unless cleanup is proved
         * safe, so finalizers can run without abandoning the native body. */
        fuse_unpack_stores(input + start, end - start, 2, continuation);
        start = end;
    }
    /* A validity check is redundant at a join only when every predecessor
     * has checked the executor since its last escape. _START_EXECUTOR checks
     * validity itself; _TIER2_RESUME_CHECK either stays in Tier 2 without
     * escaping or leaves it permanently to handle pending work. Propagate
     * the may-escape bit to a fixed point, including backedges and inlined
     * frame transitions. Saved instruction pointers remain local. */
    bool unchecked_escape[UOP_MAX_TRACE_LENGTH] = {true};
    bool changed;
    do {
        changed = false;
        for (int pc = 0; pc < input_length; pc++) {
            int opcode = input[pc].opcode;
            bool escaped = unchecked_escape[pc];
            if (opcode == _CHECK_VALIDITY || opcode == _START_EXECUTOR) {
                escaped = false;
            }
            else if ((_PyUop_Flags[opcode] & HAS_ESCAPES_FLAG) ||
                     opcode == _PUSH_FRAME || opcode == _RETURN_VALUE ||
                     opcode == _METHOD_RETURN_VALUE ||
                     opcode == _METHOD_CALL ||
                     opcode == _YIELD_VALUE)
            {
                escaped = true;
            }
            if (!escaped) {
                continue;
            }
            if (method_is_edge(opcode)) {
                int target = (int)input[pc].operand1;
                if (!unchecked_escape[target]) {
                    unchecked_escape[target] = true;
                    changed = true;
                }
            }
            if (pc + 1 < input_length && opcode != _METHOD_JUMP &&
                opcode != _METHOD_EXIT && opcode != _METHOD_YIELD_EXIT &&
                !is_terminator(&input[pc]) &&
                !unchecked_escape[pc + 1])
            {
                unchecked_escape[pc + 1] = true;
                changed = true;
            }
        }
    } while (changed);
    int last_set_ip = -1;
    bool may_have_escaped = true;
    bool builtins_checked = false;
    bool globals_checked = false;
    uint64_t globals_version = 0;
    uint64_t globals_identity = 0;
    for (int pc = 0; pc < input_length; pc++) {
        if (block_start[pc]) {
            last_set_ip = -1;
            may_have_escaped = unchecked_escape[pc];
            builtins_checked = false;
            globals_checked = false;
        }
        int opcode = input[pc].opcode;
        if (opcode == _SET_IP) {
            input[pc].opcode = _NOP;
            last_set_ip = pc;
        }
        else if (opcode == _START_EXECUTOR) {
            may_have_escaped = false;
        }
        else if (opcode == _CHECK_VALIDITY) {
            if (!may_have_escaped) {
                input[pc].opcode = _NOP;
            }
            may_have_escaped = false;
        }
        else if (opcode == _GUARD_BUILTINS_IDENTITY) {
            /* A frame's builtins mapping cannot change. Keep the first
             * guard, including for functions sharing code but not builtins.
             * Value changes still invalidate the executor dependencies. */
            if (builtins_checked) {
                input[pc].opcode = _NOP;
            }
            builtins_checked = true;
        }
        else if (opcode == _GUARD_GLOBALS_VERSION_AND_IDENTITY) {
            /* Folded names have individual invalidation dependencies. After
             * checking the mapping once, those dependencies and the existing
             * validity checks also cover writes by intervening callbacks. */
            if (globals_checked && globals_version == input[pc].operand0 &&
                globals_identity == input[pc].operand1)
            {
                input[pc].opcode = _NOP;
            }
            else {
                globals_checked = true;
                globals_version = input[pc].operand0;
                globals_identity = input[pc].operand1;
            }
        }
        else {
            uint16_t flags = _PyUop_Flags[opcode];
            bool changes_frame = opcode == _PUSH_FRAME ||
                                 opcode == _RETURN_VALUE || opcode == _METHOD_RETURN_VALUE ||
                                 opcode == _METHOD_CALL ||
                                 opcode == _YIELD_VALUE;
            if (changes_frame) {
                builtins_checked = false;
                globals_checked = false;
            }
            if ((flags & (HAS_ESCAPES_FLAG | HAS_ERROR_FLAG)) || changes_frame) {
                if (last_set_ip >= 0) {
                    input[last_set_ip].opcode = _SET_IP;
                    last_set_ip = -1;
                }
            }
            if ((flags & HAS_ESCAPES_FLAG) || changes_frame) {
                may_have_escaped = true;
            }
        }
    }
    method_fuse_global_identity(input, input_length);
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
    if (partial_method) {
        /* Do this after region matching, which recognizes ordinary periodic
         * checks. Complete methods need no progress accounting. */
        for (int pc = 0; pc < input_length; pc++) {
            if (input[pc].opcode == _CHECK_PERIODIC) {
                input[pc].opcode = _METHOD_CHECK_PERIODIC;
            }
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
        if (!method_is_edge(opcode)) {
            continue;
        }
        int input_target = (int)output[i].operand1;
        assert(input_target >= 0 && input_target < input_length);
        output[i].jump_target = offset_map[input_target];
        output[i].format = UOP_FORMAT_JUMP;
        output[i].operand1 = 0;
    }
    return length;
}

static uint64_t
method_bytecode_fingerprint(PyCodeObject *code)
{
    /* Ignore execution counters and branch histories. Cache versions and
     * specialized opcodes matter: a newly specialized operation may make a
     * previously unsupported region useful. This cache only suppresses an
     * optimization attempt, so collisions cannot affect Python semantics. */
    uint64_t hash = 14695981039346656037ULL;
    _Py_CODEUNIT *bytecode = method_bytecode(code);
    for (int offset = 0; offset < Py_SIZE(code);) {
        _Py_CODEUNIT inst = bytecode[offset];
        if (inst.op.code == ENTER_EXECUTOR) {
            _PyExecutorObject *executor = code->co_executors->executors[inst.op.arg];
            inst.op.code = executor->vm_data.opcode;
            inst.op.arg = executor->vm_data.oparg;
        }
        else if (inst.op.code >= MIN_INSTRUMENTED_OPCODE) {
            inst = _Py_GetBaseCodeUnit(code, offset);
        }
        int opcode = _PyOpcode_Deopt[inst.op.code];
        int caches = _PyOpcode_Caches[opcode];
        hash = (hash ^ inst.cache) * 1099511628211ULL;
        bool branch = opcode == POP_JUMP_IF_TRUE || opcode == POP_JUMP_IF_FALSE ||
                      opcode == POP_JUMP_IF_NONE || opcode == POP_JUMP_IF_NOT_NONE;
        if (!branch) {
            for (int i = 2; i <= caches; i++) {
                hash = (hash ^ bytecode[offset + i].cache) * 1099511628211ULL;
            }
        }
        offset += 1 + caches;
    }
    return hash;
}

static bool
method_retry_is_deferred(PyCodeObject *code, int offset)
{
    _PyExecutorArray *array = code->co_executors;
    if (array == NULL) {
        return false;
    }
    for (size_t i = 0; i < Py_ARRAY_LENGTH(array->method_backoff); i++) {
        if (array->method_backoff[i].remaining &&
            array->method_backoff[i].offset == offset)
        {
            if (array->method_backoff[i].fingerprint ==
                method_bytecode_fingerprint(code))
            {
                array->method_backoff[i].remaining--;
                return true;
            }
            array->method_backoff[i].remaining = 0;
        }
    }
    return false;
}

static void
method_defer_retry(PyCodeObject *code, int offset)
{
    _PyExecutorArray *array = code->co_executors;
    assert(array != NULL);
    size_t index = array->next_method_backoff++ %
                   Py_ARRAY_LENGTH(array->method_backoff);
    for (size_t i = 0; i < Py_ARRAY_LENGTH(array->method_backoff); i++) {
        if (array->method_backoff[i].remaining &&
            array->method_backoff[i].offset == offset)
        {
            index = i;
            break;
        }
    }
    array->method_backoff[index].fingerprint = method_bytecode_fingerprint(code);
    array->method_backoff[index].offset = offset;
    array->method_backoff[index].remaining = 15;
}

static void
method_debug_rejection(PyCodeObject *code, const char *phase, int length)
{
#ifdef Py_DEBUG
    const char *debug = Py_GETENV("PYTHON_LLTRACE");
    if (debug != NULL && *debug >= '1' && *debug <= '9') {
        const char *name = PyUnicode_IS_COMPACT_ASCII(code->co_qualname)
            ? (const char *)PyUnicode_1BYTE_DATA(code->co_qualname)
            : "<non-ASCII name>";
        fprintf(stderr, "Method rejected: %s, phase=%s, uops=%d, code_units=%zd\n",
                name, phase, length, Py_SIZE(code));
    }
#endif
}

static int
method_prioritize_entry(_PyMethodBlock *blocks, int block_count,
                        int *entry_block, bool loop_entry)
{
    int first = *entry_block;
    if (loop_entry) {
        assert(blocks[*entry_block].terminator == METHOD_JUMP);
        first = blocks[*entry_block].target;
    }
    assert(first >= 0 && first < block_count);
    if (first == 0) {
        return 1;
    }
    _PyMethodBlock *original = PyMem_Malloc(
        (size_t)block_count * sizeof(*original));
    if (original == NULL) {
        PyErr_NoMemory();
        return 0;
    }
    memcpy(original, blocks, (size_t)block_count * sizeof(*original));
    /* Keep source order from the loop header or generator resume, then wrap
     * around to the rest of the method. Earlier code can consume the uop
     * budget before the loop containing the entry is translated. This is
     * a static CFG layout choice; both conditional successors remain. */
    for (int b = 0; b < block_count; b++) {
        blocks[b] = original[(b + first) % block_count];
        if (blocks[b].target >= 0) {
            blocks[b].target = (blocks[b].target + block_count - first) % block_count;
        }
        if (blocks[b].fallthrough >= 0) {
            blocks[b].fallthrough =
                (blocks[b].fallthrough + block_count - first) % block_count;
        }
    }
    *entry_block = (*entry_block + block_count - first) % block_count;
    PyMem_Free(original);
    return 1;
}

static int
method_compile(PyThreadState *tstate, _PyInterpreterFrame *frame,
               _Py_CODEUNIT *entry, int entry_depth, bool continuation)
{
    PyInterpreterState *interp = tstate->interp;
    if (!FT_ATOMIC_LOAD_UINT8(interp->jit) || interp->compiling) {
        return 0;
    }
    PyObject *function = PyStackRef_AsPyObjectBorrow(frame->f_funcobj);
    if (function == NULL || !PyFunction_Check(function)) {
        return 0;
    }
    PyFunctionObject *func = (PyFunctionObject *)function;
    PyCodeObject *code = _PyFrame_GetCode(frame);
    bool generator = (code->co_flags & CO_GENERATOR) != 0;
    if ((code->co_flags & (CO_COROUTINE | CO_ASYNC_GENERATOR |
                          CO_ITERABLE_COROUTINE)) ||
        Py_SIZE(code) <= 0 || Py_SIZE(code) > INT16_MAX)
    {
        return 0;
    }
    _Py_CODEUNIT *bytecode = method_bytecode(code);
    int entry_offset = (int)(entry - bytecode);
    if (entry_offset < 0 || entry_offset >= Py_SIZE(code) ||
        entry_depth < 0 || entry_depth > code->co_stacksize)
    {
        return 0;
    }
    if (entry->op.code == ENTER_EXECUTOR) {
        return 1;
    }
    int opcode_offset = entry_offset;
    while (bytecode[opcode_offset].op.code == EXTENDED_ARG) {
        if (++opcode_offset >= Py_SIZE(code)) {
            return 0;
        }
    }
    int opcode = _PyOpcode_Deopt[bytecode[opcode_offset].op.code];
    bool loop_entry = opcode == JUMP_BACKWARD;
    bool is_osr = continuation || loop_entry || (generator && opcode == RESUME);
    if (!is_osr && (opcode != RESUME || entry_depth != 0)) {
        return 0;
    }
    if (!has_space_for_executor(code, entry)) {
        return 0;
    }
    if (method_retry_is_deferred(code, entry_offset)) {
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
    _PyMethodValue *osr_values = NULL;
    const char *failure_phase = "decode";
    int length = 0;
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
        code, bytecode, code->_co_firsttraceable,
        is_osr ? entry_offset : -1, instructions, &instruction_count,
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
    failure_phase = "analyze";
    int entry_block = instruction_to_block[offset_to_instruction[entry_offset]];
    if (loop_entry && !generator && locals_count > 0) {
        /* Infer from the complete bytecode CFG, never from the suspended
         * activation. An OSR entry must guard these facts before using them:
         * Tier 1 or a callback could have changed a live local. */
        int inferred = method_analyze_cfg(
            func, code, instructions, blocks, block_count, states, state_width,
            locals_count, stack_capacity, 0, 0, false, NULL);
        if (inferred < 0) {
            goto error;
        }
        if (inferred && blocks[entry_block].initialized) {
            osr_values = PyMem_Calloc((size_t)locals_count, sizeof(*osr_values));
            if (osr_values == NULL) {
                PyErr_NoMemory();
                goto error;
            }
            for (int i = 0; i < locals_count; i++) {
                PyTypeObject *type = method_value_get_stable_type(
                    states[entry_block * state_width + i]);
                if (type != NULL) {
                    /* Only the exact type is guarded, not identity,
                     * compactness, uniqueness, or a particular value. */
                    osr_values[i] = method_value_type(type, false);
                }
            }
        }
        memset(states, 0, (size_t)block_count * state_width * sizeof(*states));
        for (int b = 0; b < block_count; b++) {
            blocks[b].initialized = blocks[b].in_queue = 0;
            blocks[b].stack_depth = 0;
        }
    }
    if (is_osr && !method_prioritize_entry(
            blocks, block_count, &entry_block, loop_entry)) {
        goto error;
    }
    int analyzed = method_analyze_cfg(
        func, code, instructions, blocks, block_count, states, state_width,
        locals_count, stack_capacity, entry_block, entry_depth, is_osr, osr_values);
    if (analyzed <= 0) {
        if (analyzed < 0) {
            goto error;
        }
        goto unsupported;
    }

    _PyBloomFilter dependencies;
    _Py_BloomFilter_Init(&dependencies);
    _Py_BloomFilter_Add(&dependencies, code);

    failure_phase = "emit";
    int limit = UOP_MAX_TRACE_LENGTH / 2;
    int remaining_blocks = 0;
    for (int b = 0; b < block_count; b++) {
        remaining_blocks += blocks[b].initialized != 0;
    }
    /* Every reachable block needs a label and at least a deopt stub. Keep
     * room for those even if an earlier block consumes its code budget.
     * Also guarantee progress past the entry RESUME before any budget exit. */
    if (remaining_blocks > (limit - 8) / 2) {
        goto unsupported;
    }
    if (!method_emit(
            input, &length, limit, _START_EXECUTOR, 0,
            (uintptr_t)entry, entry_offset) ||
        !method_emit(input, &length, limit, _MAKE_WARM, 0, 0, entry_offset) ||
        !method_emit(input, &length, limit, _METHOD_PROFILE, 0, 0, entry_offset))
    {
        goto unsupported;
    }
    if (is_osr) {
        if (osr_values != NULL) {
            int target = blocks[entry_block].target;
            if (target < 0) {
                goto unsupported;
            }
            int fallback = instructions[blocks[target].first].offset;
            for (int i = 0; i < locals_count; i++) {
                if (osr_values[i].kind == METHOD_VALUE_TYPE &&
                    !method_emit(input, &length, limit, _GUARD_OSR_LOCAL_TYPE,
                                 (uint16_t)i, (uintptr_t)osr_values[i].object,
                                 fallback))
                {
                    goto unsupported;
                }
            }
        }
        if (!method_emit(input, &length, limit, _METHOD_JUMP, 0, 0,
                         entry_offset))
        {
            goto unsupported;
        }
        input[length - 1].operand1 = (uint64_t)entry_block;
    }

    int translated = 0;
    for (int block_index = 0; block_index < block_count; block_index++) {
        _PyMethodBlock *block = &blocks[block_index];
        if (!block->initialized) {
            continue;
        }
        remaining_blocks--;
        int block_limit = limit - 2 * remaining_blocks;
        memcpy(state, states + block_index * state_width,
               (size_t)state_width * sizeof(*state));
        int stack_depth = block->stack_depth;
        block->uop_offset = (uint16_t)length;
        if (!method_emit(input, &length, block_limit, _METHOD_LABEL,
                         Py_MIN(stack_depth, 2), 0, 0)) {
            goto unsupported;
        }
        bool supported = true;
        for (int i = block->first; i <= block->last; i++) {
            _PyMethodInstruction *mi = &instructions[i];
            int target_block = i == block->last ? block->target : -1;
            int opcode = _PyOpcode_Deopt[mi->opcode];
            if (continuation && mi->opcode == FOR_ITER_GEN) {
                /* The adaptive interpreter performs the generator frame
                 * transition. Its yielded result re-enters this method at
                 * the statically compiled loop-body continuation. */
                if (!method_emit(input, &length, block_limit, _DEOPT,
                                 0, 0, mi->offset)) {
                    goto unsupported;
                }
                supported = false;
                break;
            }
            if (generator && i == block->last &&
                block->terminator == METHOD_SUSPEND)
            {
                if (!method_emit(input, &length, block_limit, _CHECK_VALIDITY,
                                 0, 0, mi->offset) ||
                    !method_emit(input, &length, block_limit, _SET_IP, 0,
                                 (uintptr_t)(bytecode + mi->opcode_offset), mi->offset) ||
                    !method_emit(input, &length, block_limit, _MAKE_HEAP_SAFE,
                                 0, 0, mi->offset) ||
                    !method_emit(input, &length, block_limit, _YIELD_VALUE,
                                 (uint16_t)mi->oparg, 0, mi->offset) ||
                    !method_emit(input, &length, block_limit, _METHOD_YIELD_EXIT,
                                 0, 0, mi->offset)) {
                    goto unsupported;
                }
                supported = false;
                translated++;
                break;
            }
            if (generator && i == block->last &&
                block->terminator == METHOD_RETURN)
            {
                /* Tier 1 handles generator exhaustion and StopIteration.
                 * This planned boundary is not an unsupported-method miss. */
                if (!method_emit(input, &length, block_limit, _DEOPT,
                                 0, 0, mi->offset)) {
                    goto unsupported;
                }
                supported = false;
                translated++;
                break;
            }
            if (length + 4 > block_limit) {
                if (!method_emit(input, &length, block_limit, _METHOD_DEOPT,
                                 0, 0, mi->offset)) {
                    goto unsupported;
                }
                supported = false;
                break;
            }
            if (i == block->last && block->terminator == METHOD_RETURN) {
                if (!method_emit(input, &length, block_limit, _SET_IP, 0,
                                 (uintptr_t)(bytecode + mi->opcode_offset),
                                 mi->offset) ||
                    !method_emit(input, &length, block_limit, _MAKE_HEAP_SAFE,
                                 0, 0, mi->offset) ||
                    !method_emit(input, &length, block_limit,
                                 locals_count <= 4 ? _METHOD_RETURN_VALUE : _RETURN_VALUE,
                                 locals_count <= 4 ? (uint16_t)locals_count : 0,
                                 0, mi->offset) ||
                    !method_emit(input, &length, block_limit, _METHOD_EXIT,
                                 0, 0, mi->offset))
                {
                    goto unsupported;
                }
                translated++;
                break;
            }
            if (i == block->last && method_is_unconditional_jump(opcode)) {
                if (opcode == JUMP_BACKWARD &&
                    !method_emit(
                        input, &length, block_limit, _CHECK_PERIODIC, 0, 0,
                        mi->offset))
                {
                    goto unsupported;
                }
                if (!method_emit(
                        input, &length, block_limit, _METHOD_JUMP, 0, 0,
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
                    tstate, code, &dependencies, METHOD_INLINE_MAX_DEPTH,
                    func, code, bytecode, mi, target_block,
                    state, locals_count, stack_depth,
                    stack_capacity, uop_state,
                    input, &length, block_limit - 1);
            if (instruction_translated <= 0) {
                length = instruction_start;
                if (instruction_translated < 0) {
                    goto error;
                }
                supported = false;
                if (!method_emit(
                        input, &length, block_limit, _METHOD_DEOPT, 0, 0,
                        mi->offset))
                {
                    goto unsupported;
                }
                break;
            }
            translated++;
            if (!method_apply_stack_effect(
                    func, code, mi, state, locals_count, stack_capacity,
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
                        input, &length, block_limit, _METHOD_JUMP, 0, 0,
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

    failure_phase = "optimize";
    int optimized_length = method_optimize_blocks(
        func, input, length, limit, blocks, block_count,
        states, state_width, &dependencies);
    if (optimized_length < 0) {
        goto error;
    }
    length = optimized_length;

    failure_phase = "native reachability";
    if (!method_prune_unreachable(input, length, blocks, block_count, continuation)) {
        /* A rejected empty entry needs the same retry backoff as an
         * executor retired for immediately returning to Tier 1. Otherwise
         * rejecting it merely replaces native-code churn with CFG analysis
         * on every compilation attempt. Changed specializations retry. */
        if (code->co_executors == NULL &&
            get_index_for_executor(code, entry) < 0)
        {
            PyErr_NoMemory();
            goto error;
        }
        method_defer_retry(code, entry_offset);
        goto unsupported;
    }

    bool complete_method = true;
    for (int pc = 0; pc < length; pc++) {
        if (input[pc].opcode == _METHOD_DEOPT) {
            complete_method = false;
        }
    }
    assert(input[2].opcode == _METHOD_PROFILE);
    if (complete_method) {
        input[2].opcode = _NOP;
    }
    failure_phase = "finish";
    length = method_finish_uops(
        input, length, output, offset_map, !complete_method, continuation);
    if (length <= 0) {
        goto unsupported;
    }
    uint64_t trivial_operand = 0;
    int trivial_call = is_osr ? 0 : method_trivial_return(
        tstate, func, &dependencies, &trivial_operand);
    if (trivial_call == _CALL_STORE_ATTRIBUTE) {
        trivial_call = 0;
    }
    interp->compiling = true;
    _PyExecutorObject *executor = make_executor_from_uops(
        interp, output, length, &dependencies);
    interp->compiling = false;
    if (executor == NULL) {
        goto error;
    }
    int index = get_index_for_executor(code, entry);
    if (index < 0) {
        Py_DECREF(executor);
        goto error;
    }
    executor->trivial_call = trivial_call;
    executor->trivial_operand = trivial_operand;
    executor->vm_data.partial_method = !complete_method;
#ifdef Py_DEBUG
    const char *method_debug = Py_GETENV("PYTHON_LLTRACE");
    if (!complete_method && method_debug != NULL && *method_debug >= '1' &&
        *method_debug <= '9')
    {
        const char *name = PyUnicode_IS_COMPACT_ASCII(code->co_qualname)
            ? (const char *)PyUnicode_1BYTE_DATA(code->co_qualname)
            : "<non-ASCII name>";
        fprintf(stderr, "Partial method: %s, entry=%d, uops=%d\n",
                name, entry_offset, length);
        for (int pc = 0; pc < length; pc++) {
            if (_PyUop_Uncached[output[pc].opcode] == _METHOD_DEOPT) {
                fprintf(stderr, "  fallback at code unit %u\n",
                        output[output[pc].jump_target].target);
            }
        }
    }
#endif
    insert_executor(code, entry, index, executor);
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
    PyMem_Free(osr_values);
    return 1;

unsupported:
    method_debug_rejection(code, failure_phase, length);
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
    PyMem_Free(osr_values);
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
    PyMem_Free(osr_values);
    return -1;
}

static int
_PyJit_CompileMethod_stopped(PyThreadState *tstate, _PyInterpreterFrame *frame,
                     _Py_CODEUNIT *entry, int entry_depth)
{
    if (!FT_ATOMIC_LOAD_UINT8(tstate->interp->jit) || tstate->interp->compiling)
    {
        return 0;
    }
    /* A hot generator loop can compile its body even when the frame
     * transition at the header must run in Tier 1. The stack effect and
     * entry are determined from bytecode, never from a recorded path. */
    PyCodeObject *code = _PyFrame_GetCode(frame);
    _Py_CODEUNIT *bytecode = method_bytecode(code);
    _Py_CODEUNIT *end = bytecode + Py_SIZE(code);
    uint32_t oparg = 0;
    _Py_CODEUNIT *jump = entry;
    while (jump < end) {
        oparg = (oparg << 8) | jump->op.arg;
        if (jump->op.code != EXTENDED_ARG) {
            break;
        }
        jump++;
    }
    if (jump >= end || _PyOpcode_Deopt[jump->op.code] != JUMP_BACKWARD) {
        goto regular_entry;
    }
    int target = (int)(jump - bytecode) + 1 + _PyOpcode_Caches[JUMP_BACKWARD];
    if (oparg > (uint32_t)target) {
        goto regular_entry;
    }
    target -= oparg;
    while (target < Py_SIZE(code) && bytecode[target].op.code == EXTENDED_ARG) {
        target++;
    }
    if (target >= Py_SIZE(code) || bytecode[target].op.code != FOR_ITER_GEN) {
        goto regular_entry;
    }
    target += 1 + _PyOpcode_Caches[FOR_ITER];
    if (target >= Py_SIZE(code) || bytecode[target].op.code == ENTER_EXECUTOR) {
        return 0;
    }
    int compiled = method_compile(tstate, frame, bytecode + target,
                                  entry_depth + 1, true);
    /* The requested backedge still belongs to Tier 1. The new executor
     * will run only after a subsequent successful generator iteration. */
    return compiled < 0 ? -1 : 0;

regular_entry:
    return method_compile(tstate, frame, entry, entry_depth, false);
}

int
_PyJit_CompileMethod(PyThreadState *tstate, _PyInterpreterFrame *frame,
                     _Py_CODEUNIT *entry, int entry_depth)
{
#ifdef Py_GIL_DISABLED
    if (!tstate->interp->config.tlbc_enabled ||
        frame->tlbc_index != ((_PyThreadStateImpl *)tstate)->tlbc_index)
    {
        return 0;
    }
#endif
    PyInterpreterState *interp = tstate->interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    int result = _PyJit_CompileMethod_stopped(tstate, frame, entry, entry_depth);
    _PyJit_StartTheWorld(interp, stopped);
    return result;
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
    memset(interp->executor_global_misses, 0,
           sizeof(interp->executor_global_misses));
    size_t idx = interp->executor_count++;
    interp->executor_blooms[idx] = *bloom;
    interp->executor_ptrs[idx] = executor;
    executor->vm_data.bloom_array_idx = (int32_t)idx;
    return 0;
}

static void
unlink_executor(_PyExecutorObject *executor)
{
    PyInterpreterState *interp = executor->vm_data.interp;
    int32_t idx = executor->vm_data.bloom_array_idx;
    assert(idx >= 0 && (size_t)idx < interp->executor_count);
    assert(interp->executor_ptrs[idx] == executor);
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
    /* An installed executor may be scanned before its first execution, in
     * both native and interpreted Tier 2 builds. */
    executor->vm_data.cold = false;
    executor->vm_data.partial_method = false;
    executor->method_window = 0;
    executor->method_misses = 0;
    executor->method_backedges = 0;
    executor->trivial_call = 0;
    executor->trivial_operand = 0;
    executor->vm_data.pending_deletion = 0;
    executor->vm_data.code = NULL;
    executor->vm_data.bytecode = NULL;
    if (link_executor(executor, dependency_set) < 0) {
        return -1;
    }
    return 0;
}

/* Detaches the executor from the code object (if any) that
 * holds a reference to it */
static void
_Py_ExecutorDetach_stopped(_PyExecutorObject *executor)
{
    PyCodeObject *code = executor->vm_data.code;
    if (code == NULL) {
        return;
    }
    _Py_CODEUNIT *instruction = &executor->vm_data.bytecode[executor->vm_data.index];
    assert(instruction->op.code == ENTER_EXECUTOR);
    int index = instruction->op.arg;
    assert(code->co_executors->executors[index] == executor);
    instruction->op.code = _PyOpcode_Deopt[executor->vm_data.opcode];
    instruction->op.arg = executor->vm_data.oparg;
    executor->vm_data.code = NULL;
    executor->vm_data.bytecode = NULL;
    code->co_executors->executors[index] = NULL;
    Py_DECREF(executor);
}

void
_Py_ExecutorDetach(_PyExecutorObject *executor)
{
    PyInterpreterState *interp = executor->vm_data.interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_ExecutorDetach_stopped(executor);
    _PyJit_StartTheWorld(interp, stopped);
}

/* Executors can be invalidated at any time,
   even with a stop-the-world lock held.
   Consequently it must not run arbitrary code,
   including Py_DECREF with a non-executor. */
static void
executor_invalidate_stopped(PyObject *op)
{
    _PyExecutorObject *executor = _PyExecutorObject_CAST(op);
    if (!FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid)) {
        return;
    }
    FT_ATOMIC_STORE_UINT8(executor->vm_data.valid, 0);
    unlink_executor(executor);
    _Py_ExecutorDetach(executor);
    _PyObject_GC_UNTRACK(op);
}

static void
executor_invalidate(PyObject *op)
{
    PyInterpreterState *interp = _PyExecutorObject_CAST(op)->vm_data.interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    executor_invalidate_stopped(op);
    _PyJit_StartTheWorld(interp, stopped);
}

static void
_PyJit_InvalidateStaleBinaryOp_stopped(_PyExecutorObject *executor,
                              _Py_CODEUNIT *instruction, uint64_t descr)
{
    /* A guard miss alone is not evidence that the specialization is stale.
     * Tier 1 still owns the adaptive counter: only retire this method after
     * Tier 1 has replaced the opcode or its specialization descriptor.
     * The instruction belongs to the active frame, which may be inlined. */
    if (instruction->op.code == BINARY_OP_EXTEND &&
        read_u64(&instruction[2].cache) == descr)
    {
        return;
    }
    Py_INCREF(executor);
    executor_invalidate((PyObject *)executor);
    Py_DECREF(executor);
}

void
_PyJit_InvalidateStaleBinaryOp(_PyExecutorObject *executor,
                              _Py_CODEUNIT *instruction, uint64_t descr)
{
    PyInterpreterState *interp = executor->vm_data.interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    _PyJit_InvalidateStaleBinaryOp_stopped(executor, instruction, descr);
    _PyJit_StartTheWorld(interp, stopped);
}

static int
_PyJit_RecordMethodFallback_stopped(_PyExecutorObject *executor)
{
    if (!executor->vm_data.partial_method ||
        !FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid) ||
        executor->vm_data.code == NULL ||
        executor->method_backedges >= METHOD_MIN_BACKEDGES)
    {
        return 0;
    }
    /* Only unsupported bytecodes count here. A failed speculative guard or
     * an unavailable callee does not imply the method itself is unusable:
     * retiring it can repeatedly discard useful code in polymorphic loops.
     * Several completed loop backedges demonstrate useful work even when an
     * unsupported continuation eventually returns to Tier 1. Entries that
     * make no such progress still retire under the usual miss threshold.
     * Count at most once per entry, since a fallback abandons the activation. */
    int misses = ++executor->method_misses;
    int entries = 256 - executor->method_window;
    if (misses < 32 || misses * 2 < entries) {
        return 0;
    }
    PyCodeObject *code = executor->vm_data.code;
    int offset = executor->vm_data.index;
    method_debug_rejection(code, "frequent fallback", executor->code_size);
    method_defer_retry(code, offset);
    _Py_CODEUNIT *entry = executor->vm_data.bytecode + offset;
    int opcode = executor->vm_data.opcode;
    while (opcode == EXTENDED_ARG) {
        opcode = (++entry)->op.code;
    }
    opcode = _PyOpcode_Deopt[opcode];
    if (opcode == RESUME || opcode == JUMP_BACKWARD) {
        entry[1].counter = restart_backoff_counter(entry[1].counter);
    }
    Py_INCREF(executor);
    executor_invalidate((PyObject *)executor);
    Py_DECREF(executor);
    return 1;
}

int
_PyJit_RecordMethodFallback(_PyExecutorObject *executor)
{
    PyInterpreterState *interp = executor->vm_data.interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    int result = _PyJit_RecordMethodFallback_stopped(executor);
    _PyJit_StartTheWorld(interp, stopped);
    return result;
}

static int
executor_clear(PyObject *op)
{
    executor_invalidate(op);
    return 0;
}

static void
_Py_Executor_DependsOn_stopped(_PyExecutorObject *executor, void *obj)
{
    assert(FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid));
    PyInterpreterState *interp = executor->vm_data.interp;
    int32_t idx = executor->vm_data.bloom_array_idx;
    assert(idx >= 0 && (size_t)idx < interp->executor_count);
    memset(interp->executor_global_misses, 0,
           sizeof(interp->executor_global_misses));
    _Py_BloomFilter_Add(&interp->executor_blooms[idx], obj);
}

void
_Py_Executor_DependsOn(_PyExecutorObject *executor, void *obj)
{
    PyInterpreterState *interp = executor->vm_data.interp;
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_Executor_DependsOn_stopped(executor, obj);
    _PyJit_StartTheWorld(interp, stopped);
}

/* Invalidate all executors that depend on `obj`
 * May cause other executors to be invalidated as well.
 * Uses contiguous bloom filter array for cache-friendly scanning.
 * Return true only when no executor matched.
 */
static bool
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
        if (!bloom_filter_may_contain(&interp->executor_blooms[i], filter) &&
            (other == NULL ||
             !bloom_filter_may_contain(&interp->executor_blooms[i], other)))
        {
            continue;
        }
        if (PyList_Append(invalidate, (PyObject *)interp->executor_ptrs[i])) {
            goto error;
        }
    }
    bool no_matches = PyList_GET_SIZE(invalidate) == 0;
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(invalidate); i++) {
        PyObject *exec = PyList_GET_ITEM(invalidate, i);
        executor_invalidate(exec);
        if (is_invalidation) {
            OPT_STAT_INC(executors_invalidated);
        }
    }
    Py_DECREF(invalidate);
    return no_matches;
error:
    PyErr_Clear();
    Py_XDECREF(invalidate);
    _Py_Executors_InvalidateAll(interp, is_invalidation);
    return false;
}

static void
_Py_Executors_InvalidateDependency_stopped(
    PyInterpreterState *interp, void *obj, int is_invalidation)
{
    _PyBloomFilter filter;
    _Py_BloomFilter_Init(&filter);
    _Py_BloomFilter_Add(&filter, obj);
    invalidate_dependencies(interp, &filter, NULL, is_invalidation);
}

void
_Py_Executors_InvalidateDependency(PyInterpreterState *interp, void *obj, int is_invalidation)
{
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_Executors_InvalidateDependency_stopped(interp, obj, is_invalidation);
    _PyJit_StartTheWorld(interp, stopped);
}

bool
_PyJit_IsUnstableGlobal(PyObject *globals, Py_hash_t key_hash)
{
#ifdef Py_GIL_DISABLED
    return false;
#else
    PyInterpreterState *interp = _PyInterpreterState_GET();
    size_t slot = ((size_t)key_hash ^ ((uintptr_t)globals >> 4)) %
        Py_ARRAY_LENGTH(interp->executor_global_mutations);
    return interp->executor_global_mutations[slot].dict == globals &&
        interp->executor_global_mutations[slot].key_hash == key_hash &&
        interp->executor_global_mutations[slot].mutations >=
            _Py_MAX_ALLOWED_GLOBALS_MODIFICATIONS;
#endif
}

static void
record_global_invalidation(PyInterpreterState *interp, void *dict,
                           Py_hash_t key_hash)
{
#ifndef Py_GIL_DISABLED
    size_t slot = ((size_t)key_hash ^ ((uintptr_t)dict >> 4)) %
        Py_ARRAY_LENGTH(interp->executor_global_mutations);
    if (interp->executor_global_mutations[slot].dict != dict ||
        interp->executor_global_mutations[slot].key_hash != key_hash)
    {
        interp->executor_global_mutations[slot].dict = dict;
        interp->executor_global_mutations[slot].key_hash = key_hash;
        interp->executor_global_mutations[slot].mutations = 0;
    }
    if (interp->executor_global_mutations[slot].mutations <
        _Py_MAX_ALLOWED_GLOBALS_MODIFICATIONS)
    {
        interp->executor_global_mutations[slot].mutations++;
    }
    /* Cache eviction can only permit another guarded compilation. Address
     * reuse or key-hash collisions can only suppress constant folding; no
     * cached address is dereferenced and no Python value is inferred. */
#endif
}

static bool
_Py_Executors_InvalidateGlobalDependency_stopped(
    PyInterpreterState *interp,
    void *dict,
    Py_hash_t key_hash,
    bool value_only)
{
    size_t slot = (size_t)key_hash % Py_ARRAY_LENGTH(interp->executor_global_misses);
    if (value_only) {
        for (size_t i = 0; i < Py_ARRAY_LENGTH(interp->executor_global_misses); i++) {
            if (interp->executor_global_misses[i].dict == NULL) {
                slot = i;
            }
            else if (interp->executor_global_misses[i].dict == dict &&
                     interp->executor_global_misses[i].key_hash == key_hash)
            {
                /* Unlinking executors cannot create a dependency. Linking one
                 * or extending its dependencies clears this cache. Raw dict
                 * addresses are never dereferenced; reuse is safe for the same
                 * reason. Hash collisions conservatively share dependents. */
                return true;
            }
        }
    }
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
    bool no_matches = invalidate_dependencies(interp, &legacy, &changed, 1);
    if (value_only && !no_matches) {
        record_global_invalidation(interp, dict, key_hash);
    }
    for (size_t i = 0; i < interp->executor_count; i++) {
        if (bloom_filter_may_contain(
                &interp->executor_blooms[i], &structure))
        {
            if (value_only && no_matches) {
                interp->executor_global_misses[slot].dict = dict;
                interp->executor_global_misses[slot].key_hash = key_hash;
            }
            return true;
        }
    }
    return false;
}

bool
_Py_Executors_InvalidateGlobalDependency(PyInterpreterState *interp, void *dict,
    Py_hash_t key_hash, bool value_only)
{
    bool stopped = _PyJit_StopTheWorld(interp);
    bool result = _Py_Executors_InvalidateGlobalDependency_stopped(interp, dict, key_hash, value_only);
    _PyJit_StartTheWorld(interp, stopped);
    return result;
}

/* Invalidate all executors */
static void
_Py_Executors_InvalidateAll_stopped(PyInterpreterState *interp, int is_invalidation)
{
    while (interp->executor_count > 0) {
        /* Invalidate from the end to avoid repeated swap-remove shifts */
        _PyExecutorObject *executor = interp->executor_ptrs[interp->executor_count - 1];
        assert(FT_ATOMIC_LOAD_UINT8(executor->vm_data.valid));
        if (executor->vm_data.code) {
            // Clear the entire code object so its co_executors array be freed:
            _PyCode_Clear_Executors(interp, executor->vm_data.code);
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
_Py_Executors_InvalidateAll(PyInterpreterState *interp, int is_invalidation)
{
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_Executors_InvalidateAll_stopped(interp, is_invalidation);
    _PyJit_StartTheWorld(interp, stopped);
}

static void
_Py_Executors_InvalidateCold_stopped(PyInterpreterState *interp)
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

void
_Py_Executors_InvalidateCold(PyInterpreterState *interp)
{
    bool stopped = _PyJit_StopTheWorld(interp);
    _Py_Executors_InvalidateCold_stopped(interp);
    _PyJit_StartTheWorld(interp, stopped);
}


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
        _Py_CODEUNIT *instr = &executor->vm_data.bytecode[i];
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

/* Writes a method CFG in graphviz format.
 * Each executor is presented as a table of the uops it contains.
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
    }
    fprintf(out, "    </table>>\n");
    fprintf(out, "]\n\n");

    for (uint32_t i = 0; i < executor->code_size; i++) {
        const _PyUOpInstruction *inst = &executor->trace[i];
        int opcode = _PyUop_Uncached[inst->opcode];
        if (inst->format == UOP_FORMAT_JUMP) {
            fprintf(out, "executor_%p:i%d -> executor_%p:i%d\n",
                    executor, i, executor, inst->jump_target);
        }
        if (_PyUop_Flags[opcode] & HAS_ERROR_FLAG) {
            fprintf(out, "executor_%p:i%d -> executor_%p:i%d [color=\"" RED "\"]\n",
                    executor, i, executor, inst->error_target);
        }
    }
}

/* Write the graph of all live method executors in graphviz format. */
static int
_PyDumpExecutors_stopped(FILE *out)
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

int
_PyDumpExecutors(FILE *out)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    bool stopped = _PyJit_StopTheWorld(interp);
    int result = _PyDumpExecutors_stopped(out);
    _PyJit_StartTheWorld(interp, stopped);
    return result;
}

#else

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
