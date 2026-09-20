#ifndef Py_INTERNAL_JIT_CALL_H
#define Py_INTERNAL_JIT_CALL_H

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_ceval.h"
#include "pycore_interpframe.h"
#include "pycore_optimizer.h"
#include "pycore_pystate.h"
#include "opcode_ids.h"

static inline Py_ALWAYS_INLINE void
_PyJit_ClearSmallFrame(PyThreadState *tstate, _PyInterpreterFrame *frame,
                       int locals_count)
{
    PyObject **base = (PyObject **)frame;
    if (frame->owner != FRAME_OWNED_BY_THREAD ||
        FT_ATOMIC_LOAD_PTR_RELAXED(frame->frame_obj) != NULL ||
        frame->f_locals != NULL ||
        base == &tstate->datastack_chunk->data[0])
    {
        _PyEval_FrameClearAndPop(tstate, frame);
        return;
    }
    assert(tstate->current_frame != frame);
    assert(locals_count == _PyFrame_GetCode(frame)->co_nlocalsplus);
    assert(frame->stackpointer == frame->localsplus + locals_count);
    assert(base + _PyFrame_GetCode(frame)->co_framesize == tstate->datastack_top);
    _PyThreadState_UpdateLastProfiledFrame(tstate, frame, tstate->current_frame);
    frame->stackpointer = frame->localsplus;
    /* Unrolled for small methods. Keep the generic cleanup order and keep
     * the stack storage reserved while a finalizer can re-enter Python. */
    for (int i = locals_count; --i >= 0;) {
        PyStackRef_XCLOSE(frame->localsplus[i]);
    }
    PyStackRef_CLEAR(frame->f_funcobj);
    PyStackRef_CLEAR(frame->f_executable);
    tstate->datastack_top = base;
}

static inline Py_ALWAYS_INLINE _Py_CODEUNIT *
_PyJit_CallMethodImpl(PyThreadState *tstate, _PyExecutorObject *caller_executor,
                     _PyInterpreterFrame **frame, _PyJitEntryFuncPtr enter)
{
    _PyStackRef *stack_pointer = _PyFrame_GetStackPointer(*frame);
    PyCodeObject *code = _PyFrame_GetCode(*frame);
    _Py_CODEUNIT *entry = _PyFrame_GetBytecode(*frame);
    _Py_CODEUNIT *jit_entry = entry;
    /* COPY_FREE_VARS only acquires cell references. Handle this allocation-
     * free prefix after all entry guards, so a closure call can return to
     * its compiled caller. MAKE_CELL and extended prefixes stay in Tier 1. */
    if (code->_co_firsttraceable == 1 && code->co_ncellvars == 0 &&
        entry->op.code == COPY_FREE_VARS &&
        entry->op.arg == code->co_nfreevars)
    {
        jit_entry++;
    }
    if (jit_entry->op.code != ENTER_EXECUTOR ||
        _Py_ReachedRecursionLimitWithMargin(tstate, 2)) {
        return entry;
    }
    uintptr_t version = FT_ATOMIC_LOAD_UINTPTR_ACQUIRE(
        code->_co_instrumentation_version);
    if (_Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) != version) {
        return entry;
    }
#ifdef Py_GIL_DISABLED
    if ((*frame)->tlbc_index != ((_PyThreadStateImpl *)tstate)->tlbc_index) {
        return entry;
    }
#endif
    _PyExecutorObject *callee = code->co_executors->executors[jit_entry->op.arg];
    if (jit_entry != entry) {
        PyFunctionObject *function = (PyFunctionObject *)
            PyStackRef_AsPyObjectBorrow((*frame)->f_funcobj);
        PyObject *closure = function->func_closure;
        int offset = code->co_nlocalsplus - code->co_nfreevars;
        for (int i = 0; i < code->co_nfreevars; i++) {
            (*frame)->localsplus[offset + i] =
                PyStackRef_FromPyObjectNew(PyTuple_GET_ITEM(closure, i));
        }
        (*frame)->instr_ptr = jit_entry;
    }
    /* Nested execution temporarily replaces the thread's current executor.
     * Hold the caller alive even if a callback invalidates it and runs GC. */
    Py_INCREF(caller_executor);
    _PyFrame_StackPointerInvalidate(*frame);
    tstate->current_executor = NULL;
    _Py_CODEUNIT *next = enter(callee, *frame, stack_pointer, tstate);
    *frame = tstate->current_frame;
    /* The generated calling uop expects a synchronized frame on return
     * from an escaping C call. The callee may have popped its own frame. */
    _PyFrame_StackPointerValidate(*frame);
    tstate->current_executor = (PyObject *)caller_executor;
    Py_DECREF(caller_executor);
    return next;
}

#endif /* Py_INTERNAL_JIT_CALL_H */
