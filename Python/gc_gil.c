#include "Python.h"
#include "pycore_freelist.h"   // _PyObject_ClearFreeLists()
#include "pycore_runtime.h"    // _Py_FOR_EACH_TSTATE_BEGIN()

#ifndef Py_GIL_DISABLED

/* Clear all free lists
 * All free lists are cleared during the collection of the highest generation.
 * Allocated items in the free list may keep a pymalloc arena occupied.
 * Clearing the free lists may give back memory to the OS earlier.
 */
void
_PyGC_ClearAllFreeLists(PyInterpreterState *interp)
{
    // No thread may allocate from its caches while the collector clears them.
    assert(interp->stoptheworld.world_stopped);
    // Hold the thread-list lock as detached native threads can add states.
    _Py_FOR_EACH_TSTATE_BEGIN(interp, p) {
        _PyObject_ClearFreeLists(&((_PyThreadStateImpl *)p)->freelists, 0);
    }
    _Py_FOR_EACH_TSTATE_END(interp);
}

#endif
