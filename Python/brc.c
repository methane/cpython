// Biased reference counting between ThreadGroups. Objects keep their ownership
// ID after merging; OS thread exit does not abandon a group's local counts.
#include "Python.h"
#include "pycore_brc.h"
#include "pycore_ceval.h"
#include "pycore_object.h"
#include "pycore_pystate.h"
#include "pycore_threadgroup.h"

static void
merge_object(PyObject *op)
{
    // Subtract the reference stolen by the queue.
    if (_Py_ExplicitMergeRefcount(op, -1) == 0) {
        _Py_Dealloc(op);
    }
}

void
_Py_brc_queue_object(PyObject *op)
{
    PyThreadState *tstate = _PyThreadState_GET();
    _PyThreadGroupState *group = _PyThreadGroup_Find(
        tstate->interp, op->ob_owner_id);
    if (group == NULL || !_PyEval_IsGILEnabled(tstate)) {
        // An absent group belonged to an interpreter that has shut down.
        // A live group may still have an active updater in a parallel build.
        if (group != NULL) {
            PyMutex_LockFlags(&group->brc_mutex, 0);
            int err = _PyObjectStack_Push(&group->objects_to_merge, op);
            PyMutex_Unlock(&group->brc_mutex);
            if (err == 0) {
                PyMutex_LockFlags(&group->holder_mutex, 0);
                if (group->holder != NULL) {
                    _Py_set_eval_breaker_bit(group->holder,
                                             _PY_EVAL_EXPLICIT_MERGE_BIT);
                }
                PyMutex_Unlock(&group->holder_mutex);
                _PyThreadGroup_Decref(group);
                return;
            }
            _PyThreadGroup_Decref(group);
            // No allocation is needed to merge while all mutators are stopped.
            _PyEval_StopTheWorld(tstate->interp);
            Py_ssize_t refcnt = _Py_ExplicitMergeRefcount(op, -1);
            _PyEval_StartTheWorld(tstate->interp);
            if (refcnt == 0) {
                _Py_Dealloc(op);
            }
            return;
        }
    }
    // With the interpreter GIL, no group can concurrently update its local
    // counter. Keep this path while bringing up the parallel allocator and GC.
    if (group != NULL) {
        _PyThreadGroup_Decref(group);
    }
    merge_object(op);
}

void
_Py_brc_merge_refcounts(PyThreadState *tstate)
{
    _PyThreadGroupState *group = tstate->threadgroup;
    assert(tstate->holds_threadgroup);
    _PyObjectStack pending = {0};
    PyMutex_LockFlags(&group->brc_mutex, 0);
    _PyObjectStack_Merge(&pending, &group->objects_to_merge);
    PyMutex_Unlock(&group->brc_mutex);
    PyObject *op;
    while ((op = _PyObjectStack_Pop(&pending)) != NULL) {
        merge_object(op);
    }
}
