// Allocation graph for the experimental, non-moving tracing collector.
// Included by gc_free_threading.c, after the precise stack visitors.
// All heap enumeration and marking takes place with the world stopped.

struct tracing_old_page {
    uintptr_t start;
    uintptr_t end;
    size_t block_size;
    size_t stride;
    size_t offset;
    size_t used;
    Py_ssize_t candidates;
};

struct tracing_page {
    uintptr_t start;
    uintptr_t end;
    size_t block_size;
    size_t stride;
    size_t offset;
    size_t capacity;
    // Restore the allocator's GC-heap visit order after address sorting.
    size_t classify_heap;
    size_t classify_page;
    uint32_t divisor_magic;
    unsigned divisor_shift;
    // Zero: free slot; one: unmarked allocation; two: visited allocation.
    // Larger values link the pending traversal through slot indices plus 3.
    // Leaves need no traversal links and use one byte per slot instead.
    // Nursery collections use three for a staged death, swept after restart.
    // Page-local links need no pointer-sized storage. The allocator's page
    // geometry leaves room for both links and sentinels in 16 bits.
    uint16_t *marks;
    uint8_t *leaf_marks;
    size_t pending;
    struct tracing_page *next_pending;
    bool typed;
    bool leaf;
    bool may_defer;
};

#define TRACING_PAGE_CACHE_SIZE 1024
#define TRACING_OLD_SLOT UINT16_MAX
#define TRACING_YOUNG_BUFFER (UINT16_MAX - 1)
#define TRACING_DEFERRED_SLOT (UINT16_MAX - 2)

// Small pages hold at most one block per pointer-sized slot. Larger page
// classes have larger minimum block sizes; huge allocations use one slot.
// Keep the runtime guard too, in case allocator geometry changes.
static_assert(MI_SMALL_PAGE_SIZE / sizeof(mi_block_t) <= UINT16_MAX - 5,
              "small-page slot indices must fit in tracing marks");
static_assert(MI_MEDIUM_PAGE_SIZE / (MI_SMALL_OBJ_SIZE_MAX + 1) <= UINT16_MAX - 5,
              "medium-page slot indices must fit in tracing marks");
static_assert(MI_SEGMENT_SIZE / (MI_MEDIUM_OBJ_SIZE_MAX + 1) <= UINT16_MAX - 5,
              "large-page slot indices must fit in tracing marks");

struct tracing_mark_chunk {
    struct tracing_mark_chunk *next;
    size_t used;
    size_t capacity;
    uint16_t data[];
};

struct tracing_heap {
    struct tracing_page *pages;
    struct tracing_mark_chunk *mark_chunks;
    size_t size;
    size_t capacity;
    size_t buffer_page_count;
    struct tracing_page *pending;
    uintptr_t live_bytes;
    uintptr_t nonleaf_live_bytes;
    uintptr_t start;
    uintptr_t end;
    struct tracing_page *cache[TRACING_PAGE_CACHE_SIZE];
    size_t offset;
    int tag;
    bool leaf_only;
    bool young_containers;
    bool temporary_marks;
    bool tracing_deferred;
    uintptr_t deferred_young_bytes;
    uintptr_t deferred_young_limit;
    uintptr_t deferred_leaf_bytes;
    int leaf_pagemap_fd;
    size_t os_page_size;
    uintptr_t skipped_leaf_bytes;
    uint32_t skipped_leaf_pages;
    const struct tracing_old_page *previous_old_pages;
    size_t previous_old_page_count;
    struct tracing_old_page *old_pages;
    size_t old_page_count;
    size_t old_page_capacity;
    bool old_page_cache_failed;
    Py_ssize_t skipped_old_objects;
    Py_ssize_t skipped_old_candidates;
    size_t skipped_old_pages;
    // Current allocator heap and page sequence captured by snapshot_area().
    size_t classify_heap;
    size_t classify_page;
};

static bool tracing_area_clean(const struct tracing_heap *graph,
                                    const mi_heap_area_t *area);

static void
tracing_clear_old_pages(GCState *gcstate)
{
    PyMem_RawFree(gcstate->tracing_old_pages);
    gcstate->tracing_old_pages = NULL;
    gcstate->tracing_old_page_count = 0;
}

static const struct tracing_old_page *
tracing_find_old_page(const struct tracing_heap *graph,
                      const mi_heap_area_t *area, size_t offset)
{
    uintptr_t start = (uintptr_t)area->blocks;
    size_t lo = 0, hi = graph->previous_old_page_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        const struct tracing_old_page *page = &graph->previous_old_pages[mid];
        if (page->start < start) {
            lo = mid + 1;
        }
        else if (page->start > start) {
            hi = mid;
        }
        else {
            if (page->end == start + area->committed &&
                page->block_size == area->block_size &&
                page->stride == area->full_block_size &&
                page->offset == offset && page->used == area->used)
            {
                return page;
            }
            return NULL;
        }
    }
    return NULL;
}

static void
tracing_cache_old_page(struct tracing_heap *graph,
                       const struct tracing_old_page *page)
{
    if (graph->old_page_cache_failed) {
        return;
    }
    if (graph->old_page_count == graph->old_page_capacity) {
        size_t capacity = graph->old_page_capacity ? graph->old_page_capacity * 2 : 64;
        if (capacity < graph->old_page_capacity ||
            capacity > SIZE_MAX / sizeof(*graph->old_pages))
        {
            graph->old_page_cache_failed = true;
            return;
        }
        void *pages = PyMem_RawRealloc(graph->old_pages,
                                      capacity * sizeof(*graph->old_pages));
        if (pages == NULL) {
            // The cache is optional. Keep using the original allocation map.
            graph->old_page_cache_failed = true;
            return;
        }
        graph->old_pages = pages;
        graph->old_page_capacity = capacity;
    }
    graph->old_pages[graph->old_page_count++] = *page;
}

static int
tracing_compare_old_pages(const void *a, const void *b)
{
    uintptr_t x = ((const struct tracing_old_page *)a)->start;
    uintptr_t y = ((const struct tracing_old_page *)b)->start;
    return (x > y) - (x < y);
}

static void
tracing_publish_old_pages(GCState *gcstate, struct tracing_heap *graph)
{
    if (graph->old_page_cache_failed) {
        return;
    }
    if (graph->old_page_count > 1) {
        qsort(graph->old_pages, graph->old_page_count,
              sizeof(*graph->old_pages), tracing_compare_old_pages);
    }
    tracing_clear_old_pages(gcstate);
    gcstate->tracing_old_pages = graph->old_pages;
    gcstate->tracing_old_page_count = graph->old_page_count;
    graph->old_pages = NULL;
}

static void *
tracing_alloc_marks(struct tracing_heap *graph, size_t capacity, bool leaf)
{
    // Pack byte maps and halfword maps into the same arena, keeping each map
    // halfword-aligned. Maps stay stable when the page table grows or is sorted.
    size_t units = leaf ? capacity / sizeof(uint16_t) +
                          (capacity % sizeof(uint16_t) != 0) : capacity;
    struct tracing_mark_chunk *chunk = graph->mark_chunks;
    if (chunk == NULL || units > chunk->capacity - chunk->used) {
        size_t count = Py_MAX(units, 65536 / sizeof(uint16_t));
        if (count > (SIZE_MAX - sizeof(*chunk)) / sizeof(uint16_t)) {
            return NULL;
        }
        // These buffers belong only to this snapshot. Never allocate from
        // a Python heap being visited, or retain them after collection.
        chunk = PyMem_RawMalloc(sizeof(*chunk) + count * sizeof(uint16_t));
        if (chunk == NULL) {
            return NULL;
        }
        chunk->next = graph->mark_chunks;
        chunk->used = 0;
        chunk->capacity = count;
        graph->mark_chunks = chunk;
    }
    void *marks = &chunk->data[chunk->used];
    chunk->used += units;
    return marks;
}

static inline size_t
tracing_page_index(const struct tracing_page *page, uintptr_t address)
{
    size_t offset = address - page->start;
    if (page->divisor_shift != 0) {
        // The same invariant 32-bit division used by mimalloc's heap visitor.
        // Only the snapshot's bounded offsets use this multiplication path.
        size_t index = ((((uint64_t)offset * page->divisor_magic) >> 32) +
                        offset) >> page->divisor_shift;
        assert(index == offset / page->stride);
        return index;
    }
    return offset / page->stride;
}

static void
tracing_snapshot_use_full_heap(struct tracing_heap *graph)
{
    assert(graph->young_containers && !graph->leaf_only);
    assert(graph->pending == NULL);
    // No edges have been traced yet. Keep the allocation maps, but discard
    // the nursery's implicit roots. The initial full mark records reachability
    // only in these maps, so it need not clear every object's promotion bit.
    // The current page's free slots are already excluded, even if its
    // object-header loop has not finished.
    for (size_t i = 0; i < graph->size; i++) {
        struct tracing_page *page = &graph->pages[i];
        if (page->leaf) {
            continue;
        }
        for (size_t j = 0; j < page->capacity; j++) {
            if (page->marks[j] != 0) {
                page->marks[j] = 1;
                if (!page->typed) {
                    // Header classification may already have identified a
                    // private young buffer. Full tracing needs it unmarked.
                    continue;
                }
            }
        }
    }
    graph->young_containers = false;
    graph->temporary_marks = true;
    graph->live_bytes = 0;
    graph->nonleaf_live_bytes = 0;
}

static bool
tracing_snapshot_area(const mi_heap_t *heap, const mi_heap_area_t *area,
                      void *block, size_t block_size, void *arg)
{
    assert(block == NULL);
    // The allocator has already merged pending frees. Empty pages contain
    // neither roots nor candidates and need no entry or allocation map.
    if (area->used == 0) {
        return true;
    }
    struct tracing_heap *graph = arg;
    bool leaf = graph->tag == _Py_MIMALLOC_HEAP_LEAF;
    if (leaf && (graph->leaf_only || graph->young_containers) &&
        tracing_area_clean(graph, area))
    {
        // A new allocation must write its header. An unchanged scalar page
        // therefore contains only objects retained from the full-GC baseline.
        // They have no outgoing object references and need neither a mark
        // map nor an individual header visit in this nursery collection.
        uintptr_t bytes = area->used * area->block_size;
        graph->live_bytes += bytes;
        graph->skipped_leaf_bytes += bytes;
        if (area->used != 0) {
            uintptr_t start = (uintptr_t)area->blocks;
            size_t pages = (start + area->committed - 1) / graph->os_page_size -
                           start / graph->os_page_size + 1;
            if (pages > UINT32_MAX - graph->skipped_leaf_pages) {
                graph->skipped_leaf_pages = UINT32_MAX;
            }
            else {
                graph->skipped_leaf_pages += (uint32_t)pages;
            }
        }
        return true;
    }
    if (graph->young_containers &&
        (graph->tag == _Py_MIMALLOC_HEAP_GC ||
         graph->tag == _Py_MIMALLOC_HEAP_GC_PRE))
    {
        const struct tracing_old_page *old = tracing_find_old_page(
            graph, area, graph->offset);
        if (old != NULL && tracing_area_clean(graph, area)) {
            // Geometry alone cannot detect reuse. A new allocation, a free,
            // or a replacement mapping must also dirty this area's PTEs.
            // Only exact builtins without external traversal were cached.
            // Their unchanged bodies have no new edges; separately allocated
            // list/dict/set storage is still visited by the dirty scanner.
            uintptr_t bytes = area->used * area->block_size;
            graph->live_bytes += bytes;
            graph->nonleaf_live_bytes += bytes;
            graph->skipped_old_objects += area->used;
            graph->skipped_old_candidates += old->candidates;
            graph->skipped_old_pages++;
            tracing_cache_old_page(graph, old);
            return true;
        }
    }
    if (graph->size == graph->capacity) {
        size_t capacity = graph->capacity ? graph->capacity * 2 : 256;
        if (capacity < graph->capacity ||
            capacity > SIZE_MAX / sizeof(*graph->pages))
        {
            return false;
        }
        // Never allocate from a heap that we are visiting.
        void *pages = PyMem_RawRealloc(graph->pages,
                                     capacity * sizeof(*graph->pages));
        if (pages == NULL) {
            return false;
        }
        graph->pages = pages;
        graph->capacity = capacity;
        if (graph->buffer_page_count != 0) {
            // Prefix lookups cache addresses inside the page table.
            memset(graph->cache, 0, sizeof(graph->cache));
        }
    }
    size_t capacity = area->committed / area->full_block_size;
    if (capacity > UINT16_MAX - 5) {
        // The largest link is (capacity - 1) + 3 and must not overlap the
        // reserved nursery states, even if the allocator's limits change.
        return false;
    }
    // Every slot is initialized below, including free slots. Avoid zeroing
    // each map only to overwrite it immediately with allocation marks.
    void *marks = tracing_alloc_marks(graph, capacity, leaf);
    if (marks == NULL) {
        return false;
    }
    struct tracing_page *page = &graph->pages[graph->size++];
    *page = (struct tracing_page) {
        .start = (uintptr_t)area->blocks,
        .end = (uintptr_t)area->blocks + area->committed,
        .block_size = area->block_size,
        .stride = area->full_block_size,
        .offset = graph->offset,
        .capacity = capacity,
        .classify_heap = graph->classify_heap,
        .classify_page = graph->classify_page++,
        .marks = marks,
        .leaf_marks = leaf ? marks : NULL,
        .pending = SIZE_MAX,
        .typed = leaf || graph->tag == _Py_MIMALLOC_HEAP_GC ||
                         graph->tag == _Py_MIMALLOC_HEAP_GC_PRE,
        .leaf = leaf,
    };
    if (area->committed <= UINT32_MAX && page->stride > 1) {
        unsigned shift = MI_INTPTR_BITS - mi_clz(page->stride - 1);
        page->divisor_shift = shift;
        page->divisor_magic = (uint32_t)(
            ((UINT64_C(1) << 32) * ((UINT64_C(1) << shift) - page->stride)) /
            page->stride + 1);
    }
    if (leaf) {
        memset(page->leaf_marks, 1, capacity);
    }
    else {
        for (size_t i = 0; i < capacity; i++) {
            page->marks[i] = 1;
        }
    }
    if (graph->young_containers && !page->typed) {
        // Auxiliary allocations have no age header. Count them until
        // ownership by a young container proves they are not old roots.
        graph->live_bytes += area->used * page->block_size;
        graph->nonleaf_live_bytes += area->used * page->block_size;
    }
    return true;
}

static void
tracing_snapshot_free_slots(struct tracing_heap *graph, size_t begin)
{
    // Enumeration has merged remote/local frees in every page. Interleave
    // independent free-list walks so a cache miss does not serialize the
    // entire snapshot. No object header is read until all maps are ready.
    // These pointers come only from the allocator's captured live areas;
    // the world remains stopped and our scratch storage uses the raw heap.
    enum { BATCH_SIZE = 8 };
    for (size_t first = begin; first < graph->size; first += BATCH_SIZE) {
        size_t count = Py_MIN(graph->size - first, BATCH_SIZE);
        mi_page_t *allocator_pages[BATCH_SIZE];
        mi_block_t *free_slots[BATCH_SIZE];
        for (size_t i = 0; i < count; i++) {
            struct tracing_page *page = &graph->pages[first + i];
            mi_page_t *allocator_page = _mi_ptr_page((void *)page->start);
            assert(allocator_page->local_free == NULL);
            assert(allocator_page->capacity == page->capacity);
            allocator_pages[i] = allocator_page;
            free_slots[i] = allocator_page->free;
        }
        bool pending;
        do {
            pending = false;
            for (size_t i = 0; i < count; i++) {
                mi_block_t *free = free_slots[i];
                if (free == NULL) {
                    continue;
                }
                struct tracing_page *page = &graph->pages[first + i];
                free_slots[i] = mi_block_next(allocator_pages[i], free);
                size_t index = tracing_page_index(page, (uintptr_t)free);
                assert(index < page->capacity);
                if (page->leaf) {
                    page->leaf_marks[index] = 0;
                }
                else {
                    page->marks[index] = 0;
                }
                pending = true;
            }
        } while (pending);
    }
}

static void
tracing_young_buffer(struct tracing_heap *graph, const void *buffer)
{
    // MEM and OBJECT heaps are fully captured and sorted before typed heaps.
    // Later page-table growth preserves these indices, but clears the cache.
    size_t count = graph->buffer_page_count;
    uintptr_t address = (uintptr_t)buffer;
    if (count == 0 || address < graph->pages[0].start ||
        address >= graph->pages[count - 1].end)
    {
        return;
    }
    size_t slot = (address >> 16) & (TRACING_PAGE_CACHE_SIZE - 1);
    struct tracing_page *page = graph->cache[slot];
    if (page == NULL || address < page->start || address >= page->end) {
        size_t low = 0, high = count;
        while (low < high) {
            size_t middle = low + (high - low) / 2;
            if (graph->pages[middle].start <= address) {
                low = middle + 1;
            }
            else {
                high = middle;
            }
        }
        page = &graph->pages[low - 1];
        if (address >= page->end) {
            return;
        }
        graph->cache[slot] = page;
    }
    assert(!page->typed);
    size_t index = tracing_page_index(page, address);
    assert(address - (page->start + index * page->stride) < page->block_size);
    if (page->marks[index] == 1) {
        // Only one young owner can claim this private allocation.
        page->marks[index] = TRACING_YOUNG_BUFFER;
        graph->live_bytes -= page->block_size;
        graph->nonleaf_live_bytes -= page->block_size;
    }
}

static void
tracing_prepare_young_buffer(struct tracing_heap *graph, PyObject *op)
{
    if (PyList_CheckExact(op)) {
        tracing_young_buffer(graph, ((PyListObject *)op)->ob_item);
    }
    else if (PyDict_CheckExact(op)) {
        PyDictObject *dict = (PyDictObject *)op;
        if (dict->ma_values == NULL && dict->ma_keys->dk_refcnt == 1) {
            tracing_young_buffer(graph, dict->ma_keys);
        }
        if (dict->ma_values != NULL && !dict->ma_values->embedded) {
            tracing_young_buffer(graph, dict->ma_values);
        }
    }
}

static bool
tracing_snapshot_headers(struct tracing_heap *graph, size_t begin)
{
    for (size_t p = begin; p < graph->size; p++) {
        struct tracing_page *page = &graph->pages[p];
        if (page->typed && !page->leaf) {
            // The first full root pass records reachability in the snapshot
            // map and classifies it before releasing that map.
            // A later resurrection pass still clears ALIVE and retraces the
            // whole graph because finalizers may have mutated live objects.
            if (!graph->young_containers && graph->temporary_marks) {
                continue;
            }
            for (size_t i = 0; i < page->capacity; i++) {
                if (page->marks[i] != 0) {
                    PyObject *op = (PyObject *)(page->start + i * page->stride +
                                               page->offset);
                    if (!graph->young_containers) {
                        gc_clear_alive(op);
                    }
                    else {
                        bool old = gc_is_alive(op) || gc_is_frozen(op) ||
                                   _Py_IsImmortal(op);
                        if (old) {
                            page->marks[i] = TRACING_OLD_SLOT;
                            graph->live_bytes += page->block_size;
                            graph->nonleaf_live_bytes += page->block_size;
                        }
                        else if (!tracing_nursery_container(op, true)) {
                            page->may_defer = true;
                            // These young objects and their children must
                            // wait for full tracing if they are unreachable.
                            // A large volume warrants an early full snapshot.
                            graph->deferred_young_bytes += page->block_size;
                            if (graph->deferred_young_bytes >
                                graph->deferred_young_limit)
                            {
                                // Skipped allocations cannot be restored
                                // from these maps. Otherwise all maps are
                                // complete, including later pages, so a full
                                // fallback can reuse the whole snapshot.
                                if (graph->skipped_leaf_bytes != 0 ||
                                    graph->skipped_old_objects != 0)
                                {
                                    return false;
                                }
                                tracing_snapshot_use_full_heap(graph);
                                return true;
                            }
                        }
                        if (!old) {
                            tracing_prepare_young_buffer(graph, op);
                        }
                    }
                }
            }
        }
    }
    return true;
}

static void
tracing_free_snapshot(struct tracing_heap *graph)
{
    struct tracing_mark_chunk *chunk = graph->mark_chunks;
    while (chunk != NULL) {
        struct tracing_mark_chunk *next = chunk->next;
        PyMem_RawFree(chunk);
        chunk = next;
    }
    PyMem_RawFree(graph->pages);
    PyMem_RawFree(graph->old_pages);
}

static int
tracing_compare_pages(const void *a, const void *b)
{
    uintptr_t x = ((const struct tracing_page *)a)->start;
    uintptr_t y = ((const struct tracing_page *)b)->start;
    return (x > y) - (x < y);
}

static int
tracing_compare_classification_order(const void *a, const void *b)
{
    const struct tracing_page *x = a;
    const struct tracing_page *y = b;
    if (x->classify_heap != y->classify_heap) {
        return (x->classify_heap > y->classify_heap) -
               (x->classify_heap < y->classify_heap);
    }
    return (x->classify_page > y->classify_page) -
           (x->classify_page < y->classify_page);
}

static int
tracing_snapshot(PyInterpreterState *interp, struct tracing_heap *graph)
{
    assert(interp->stoptheworld.world_stopped);
    size_t debug_offset = _PyMem_DebugEnabled() ? 2 * sizeof(size_t) : 0;
    int err = 0;
    HEAD_LOCK(&_PyRuntime);
    for (int tag = 0; tag < _Py_MIMALLOC_HEAP_COUNT; tag++) {
        if (graph->leaf_only && tag != _Py_MIMALLOC_HEAP_LEAF) {
            continue;
        }
        size_t begin = graph->size;
        graph->tag = tag;
        graph->offset = debug_offset;
        if (tag == _Py_MIMALLOC_HEAP_GC_PRE) {
            graph->offset += 2 * sizeof(PyObject *);
        }
        size_t classify_heap = 0;
        _Py_FOR_EACH_TSTATE_UNLOCKED(interp, p) {
            struct _mimalloc_thread_state *m = &((_PyThreadStateImpl *)p)->mimalloc;
            if (!_Py_atomic_load_int(&m->initialized)) {
                continue;
            }
            graph->classify_heap = 2 * classify_heap++ +
                                   (tag == _Py_MIMALLOC_HEAP_GC_PRE);
            graph->classify_page = 0;
            if (!mi_heap_visit_blocks(&m->heaps[tag], false,
                                      tracing_snapshot_area, graph))
            {
                err = -1;
                goto done;
            }
        }
        graph->classify_heap = 2 * classify_heap +
                               (tag == _Py_MIMALLOC_HEAP_GC_PRE);
        graph->classify_page = 0;
        if (!_mi_abandoned_pool_visit_blocks(&interp->mimalloc.abandoned_pool,
                                             tag, false,
                                             tracing_snapshot_area, graph))
        {
            err = -1;
            goto done;
        }
        tracing_snapshot_free_slots(graph, begin);
        if (graph->young_containers && tag == _Py_MIMALLOC_HEAP_OBJECT) {
            // Private buffers use these two untyped heaps. Prepare their
            // lookup prefix before reading any GC/GC_PRE object headers.
            assert(_Py_MIMALLOC_HEAP_MEM < _Py_MIMALLOC_HEAP_OBJECT);
            assert(_Py_MIMALLOC_HEAP_OBJECT < _Py_MIMALLOC_HEAP_GC);
            assert(_Py_MIMALLOC_HEAP_OBJECT < _Py_MIMALLOC_HEAP_GC_PRE);
            if (graph->size > 1) {
                qsort(graph->pages, graph->size, sizeof(*graph->pages),
                      tracing_compare_pages);
            }
            graph->buffer_page_count = graph->size;
        }
        if (!tracing_snapshot_headers(graph, begin)) {
            err = -1;
            goto done;
        }
    }
done:
    HEAD_UNLOCK(&_PyRuntime);
    if (err == 0 && graph->size > 1) {
        qsort(graph->pages, graph->size, sizeof(*graph->pages),
              tracing_compare_pages);
    }
    if (graph->buffer_page_count != 0) {
        // The complete table has a different order from the buffer prefix.
        memset(graph->cache, 0, sizeof(graph->cache));
    }
    if (err == 0 && graph->size != 0) {
        graph->start = graph->pages[0].start;
        graph->end = graph->pages[graph->size - 1].end;
    }
    return err;
}

static inline Py_ALWAYS_INLINE struct tracing_page *
tracing_find_page(struct tracing_heap *graph, uintptr_t address)
{
    // Only inspect metadata captured from the allocator. An arbitrary word
    // must never be dereferenced or passed to mimalloc's page lookup.
    if (address - graph->start >= graph->end - graph->start) {
        return NULL;
    }
    size_t slot = (address >> 16) & (TRACING_PAGE_CACHE_SIZE - 1);
    struct tracing_page *page = graph->cache[slot];
    if (page != NULL && address >= page->start && address < page->end) {
        return page;
    }
    size_t low = 0, high = graph->size;
    while (low < high) {
        size_t middle = low + (high - low) / 2;
        if (graph->pages[middle].start <= address) {
            low = middle + 1;
        }
        else {
            high = middle;
        }
    }
    page = &graph->pages[low - 1];
    if (address >= page->end) {
        return NULL;
    }
    graph->cache[slot] = page;
    return page;
}

static inline int
tracing_mark_typed(struct tracing_heap *graph, struct tracing_page *page,
                   size_t index, uintptr_t block)
{
    assert(page->typed);
    if (page->leaf) {
        if (page->leaf_marks[index] != 1) {
            return 0;
        }
        // These exact builtins have no outgoing object references.
        if (graph->tracing_deferred &&
            !gc_is_alive((PyObject *)(block + page->offset)))
        {
            graph->deferred_leaf_bytes += page->block_size;
        }
        page->leaf_marks[index] = 2;
    }
    else {
        if (page->marks[index] != 1) {
            return 0;
        }
        // Keep pending slots on their page. Popping the next object then
        // needs neither another page lookup nor a division by the stride.
        if (page->pending == SIZE_MAX) {
            page->marks[index] = 2;
            page->next_pending = graph->pending;
            graph->pending = page;
        }
        else {
            assert(page->pending < page->capacity);
            page->marks[index] = (uint16_t)(page->pending + 3);
        }
        page->pending = index;
    }
    if (!graph->leaf_only && !(graph->young_containers && page->leaf))
    {
        graph->live_bytes += page->block_size;
    }
    if (!page->leaf) {
        graph->nonleaf_live_bytes += page->block_size;
    }
    PyObject *op = (PyObject *)(block + page->offset);
    if (!graph->temporary_marks) {
        gc_set_alive(op);
    }
    return 0;
}

static inline int
tracing_mark_untyped(struct tracing_heap *graph, struct tracing_page *page,
                     size_t index)
{
    assert(!page->typed && !page->leaf);
    bool young_buffer = page->marks[index] == TRACING_YOUNG_BUFFER;
    if (page->marks[index] != 1 && !young_buffer) {
        return 0;
    }
    if (page->pending == SIZE_MAX) {
        page->marks[index] = 2;
        page->next_pending = graph->pending;
        graph->pending = page;
    }
    else {
        assert(page->pending < page->capacity);
        page->marks[index] = (uint16_t)(page->pending + 3);
    }
    page->pending = index;
    // A nursery collection initially counts unowned auxiliary allocations.
    // A claimed young buffer was excluded and must be added back here.
    bool counted = graph->young_containers && !young_buffer;
    if (!graph->leaf_only && !counted) {
        graph->live_bytes += page->block_size;
    }
    if (!counted) {
        graph->nonleaf_live_bytes += page->block_size;
    }
    return 0;
}

static int
tracing_mark_address(struct tracing_heap *graph, uintptr_t address)
{
    // Interpreter and JIT stack references may have low-bit tags. Interior
    // pointers are accepted, but padding and unallocated slots are not.
    address &= ~(uintptr_t)Py_TAG_BITS;
    struct tracing_page *page = tracing_find_page(graph, address);
    if (page == NULL) {
        return 0;
    }
    size_t index = tracing_page_index(page, address);
    uintptr_t block = page->start + index * page->stride;
    if (address - block >= page->block_size) {
        return 0;
    }
    if (page->typed) {
        return tracing_mark_typed(graph, page, index, block);
    }
    return tracing_mark_untyped(graph, page, index);
}

static int
tracing_mark_object(struct tracing_heap *graph, PyObject *op)
{
    uintptr_t address = (uintptr_t)op;
    struct tracing_page *page = tracing_find_page(graph, address);
    if (page == NULL) {
        return 0;
    }
    size_t index = tracing_page_index(page, address);
    uintptr_t block = page->start + index * page->stride;
    if (!page->typed) {
        if (address - block >= page->block_size) {
            return 0;
        }
        return tracing_mark_untyped(graph, page, index);
    }
    assert(address == block + page->offset);
    return tracing_mark_typed(graph, page, index, block);
}

static void _Py_NO_SANITIZE_ADDRESS _Py_NO_SANITIZE_MEMORY
tracing_scan_words(struct tracing_heap *graph, const void *memory, size_t size)
{
    const unsigned char *cursor = memory;
    uintptr_t start = graph->start, span = graph->end - start;
    while (size >= sizeof(uintptr_t)) {
        uintptr_t address;
        memcpy(&address, cursor, sizeof(address));
        address &= ~(uintptr_t)Py_TAG_BITS;
        // Most words are not heap pointers. Reject them here without a
        // function call or any page metadata access.
        if (address - start < span) {
            tracing_mark_address(graph, address);
        }
        cursor += sizeof(address);
        size -= sizeof(address);
    }
}

static int
tracing_visit(PyObject *op, void *arg)
{
    if (_PyObject_IsImmediate(op)) {
        return 0;
    }
    struct tracing_heap *graph = arg;
    // Precise visitors supply valid object pointers, so already-marked GC
    // containers can normally be rejected before looking up their allocation.
    // During the initial full mark, use the dense snapshot map instead of
    // loading a header from every referenced object.
    if (!graph->temporary_marks) {
        uint8_t mask = _PyGC_BITS_TRACKED | _PyGC_BITS_ALIVE;
        if ((op->ob_gc_bits & mask) == mask) {
            return 0;
        }
    }
    return tracing_mark_object(graph, op);
}

// Claim an auxiliary allocation whose references the caller will visit
// precisely. If it is already pending, leave its traversal links intact: the
// conservative visitor will cover its references instead. Embedded arrays
// still need to mark their containing object, including its other fields.
static bool
tracing_claim_buffer(struct tracing_heap *graph, const void *buffer)
{
    uintptr_t address = (uintptr_t)buffer;
    struct tracing_page *page = tracing_find_page(graph, address);
    if (page == NULL) {
        return true;
    }
    if (page->typed) {
        tracing_mark_address(graph, address);
        return true;
    }
    size_t index = tracing_page_index(page, address);
    assert(address - (page->start + index * page->stride) < page->block_size);
    assert(page->marks[index] != 0);
    bool young_buffer = page->marks[index] == TRACING_YOUNG_BUFFER;
    if (page->marks[index] != 1 && !young_buffer) {
        return false;
    }
    page->marks[index] = 2;
    if (!graph->young_containers || young_buffer) {
        graph->live_bytes += page->block_size;
        graph->nonleaf_live_bytes += page->block_size;
    }
    return true;
}

static void
tracing_visit_dict_keys(struct tracing_heap *graph, PyDictKeysObject *keys)
{
    Py_ssize_t size = keys->dk_nentries;
    if (tracing_claim_buffer(graph, keys)) {
        // Cyclic GC's dict visitor omits exact string keys. A tracing GC
        // needs all keys, including shared keys absent from this instance.
        if (keys->dk_kind == DICT_KEYS_SPLIT) {
            PyTypeObject *owner = _PyDictKeys_AsSharedKeys(keys)->dsk_owning_type;
            if (owner != NULL) {
                tracing_visit((PyObject *)owner, graph);
            }
        }
        if (DK_IS_UNICODE(keys)) {
            PyDictUnicodeEntry *entries = DK_UNICODE_ENTRIES(keys);
            for (Py_ssize_t i = 0; i < size; i++) {
                if (entries[i].me_key != NULL) {
                    tracing_visit(entries[i].me_key, graph);
                }
                if (entries[i].me_value != NULL) {
                    tracing_visit(entries[i].me_value, graph);
                }
            }
        }
        else {
            PyDictKeyEntry *entries = DK_ENTRIES(keys);
            for (Py_ssize_t i = 0; i < size; i++) {
                if (entries[i].me_key != NULL) {
                    tracing_visit(entries[i].me_key, graph);
                }
                if (entries[i].me_value != NULL) {
                    tracing_visit(entries[i].me_value, graph);
                }
            }
        }
    }
}

static void
tracing_visit_dict(struct tracing_heap *graph, PyDictObject *dict)
{
    PyDictKeysObject *keys = dict->ma_keys;
    tracing_visit_dict_keys(graph, keys);
    if (dict->ma_values != NULL &&
        tracing_claim_buffer(graph, dict->ma_values))
    {
        for (Py_ssize_t i = 0; i < keys->dk_nentries; i++) {
            PyObject *value = dict->ma_values->values[i];
            if (value != NULL) {
                tracing_visit(value, graph);
            }
        }
    }
}

static void
tracing_scan_native_stack(struct tracing_heap *graph, _PyThreadStateImpl *ts,
                          uintptr_t bottom)
{
    uintptr_t top = ts->c_stack_top;
    if (bottom == 0 || top == 0) {
        return;
    }
    bottom &= ~(uintptr_t)(sizeof(uintptr_t) - 1);
    top &= ~(uintptr_t)(sizeof(uintptr_t) - 1);
    // Native evaluator frames are nested in the same order as C frames.
    // Their Python values are visited precisely below; scan only the C
    // frames between them, including the evaluator wrappers' saved registers.
    for (struct _tracing_native_frame *frame = ts->gc.native_frames;
         frame != NULL; frame = frame->previous)
    {
        uintptr_t start = frame->bottom, end = frame->top;
#if _Py_STACK_GROWS_DOWN
        if (start >= bottom && end >= start && end <= top) {
            tracing_scan_words(graph, (void *)bottom, start - bottom);
            bottom = end;
        }
#else
        if (start <= bottom && end <= start && end >= top) {
            tracing_scan_words(graph, (void *)start, bottom - start);
            bottom = end;
        }
#endif
    }
    if (bottom > top) {
        uintptr_t temporary = bottom;
        bottom = top;
        top = temporary;
    }
    tracing_scan_words(graph, (void *)bottom, top - bottom);
}

static void
tracing_scan_static_type(struct tracing_heap *graph, PyTypeObject *type)
{
    // The type itself is a C global, not an allocation in the snapshot.
    // Its owned heap fields are roots. Do not follow tp_weaklist, which is
    // borrowed, or call tp_traverse, which describes instances of this type.
    assert(!(type->tp_flags & (Py_TPFLAGS_HEAPTYPE |
                              _Py_TPFLAGS_STATIC_BUILTIN)));
    tracing_mark_address(graph, (uintptr_t)type->tp_bases);
    tracing_mark_address(graph, (uintptr_t)type->tp_mro);
    tracing_mark_address(graph, (uintptr_t)type->tp_cache);
    tracing_mark_address(graph, (uintptr_t)type->tp_dict);
    tracing_mark_address(graph, (uintptr_t)type->tp_subclasses);
    tracing_mark_address(graph, (uintptr_t)type->_tp_cache);
}

static void
tracing_scan_interp_roots(struct tracing_heap *graph, PyInterpreterState *interp)
{
    // The executor registry is borrowed. Following it would keep every
    // generated trace (and its code and constants) alive indefinitely.
    tracing_scan_words(graph, interp,
                       offsetof(PyInterpreterState, executor_blooms));
    size_t tail = offsetof(PyInterpreterState, executor_deletion_list_head);
    tracing_scan_words(graph, (char *)interp + tail, sizeof(*interp) - tail);
    struct types_state *types = &interp->types;
    for (size_t i = 0; i < types->tracing_static_types_size; i++) {
        tracing_scan_static_type(graph, types->tracing_static_types[i]);
    }
    // Managed static types already have interpreter-owned dictionaries and
    // caches, and immortal tp_bases/tp_mro tuples. No extra scan is needed.
}

#ifdef _Py_TIER2
static void
tracing_scan_jit_roots(struct tracing_heap *graph, _PyThreadStateImpl *ts)
{
    _PyJitTracerState *tracer = ts->jit_tracer_state;
    if (tracer == NULL || !tracer->is_tracing) {
        return;
    }
    // The tracer is a virtual allocation, outside the mimalloc snapshot.
    tracing_scan_words(graph, &tracer->initial_state,
                       sizeof(tracer->initial_state));
    tracing_scan_words(graph, &tracer->prev_state, sizeof(tracer->prev_state));
    tracing_scan_words(graph, tracer->code_buffer.start,
                       uop_buffer_length(&tracer->code_buffer) *
                       sizeof(_PyUOpInstruction));
    if (ts->base.interp->compiling) {
        tracing_scan_words(graph, &tracer->opt_context,
                           sizeof(tracer->opt_context));
        // Optimization and stack allocation use both halves of the array,
        // including after code_buffer has been reset for tracer cleanup.
        tracing_scan_words(graph, tracer->uop_array, sizeof(tracer->uop_array));
    }
}
#endif

static int
tracing_scan_roots(PyInterpreterState *interp, struct collection_state *state,
                   struct tracing_heap *graph)
{
    tracing_scan_interp_roots(graph, interp);
    // The main interpreter is embedded in the runtime; do not scan its
    // borrowed executor registry again through the enclosing structure.
    tracing_scan_words(graph, &_PyRuntime,
                       offsetof(_PyRuntimeState, _main_interpreter));
    if (interp != &_PyRuntime._main_interpreter) {
        tracing_scan_interp_roots(graph, &_PyRuntime._main_interpreter);
    }
    _Py_FOR_EACH_TSTATE_BEGIN(interp, p) {
        _PyThreadStateImpl *ts = (_PyThreadStateImpl *)p;
        tracing_scan_words(graph, ts, sizeof(*ts));
#ifdef _Py_TIER2
        tracing_scan_jit_roots(graph, ts);
#endif
        uintptr_t low = ts->gc.stack_pointer;
        if (p == interp->stoptheworld.requester) {
            low = state->native_roots->stack_pointer;
        }
        else if (low == 0) {
            low = ts->c_stack_hard_limit;
        }
        tracing_scan_native_stack(graph, ts, low);
    }
    _Py_FOR_EACH_TSTATE_END(interp);
    tracing_scan_words(graph, &state->native_roots->registers,
                       sizeof(state->native_roots->registers));
    gc_mark_args_t args = {.tracing = graph};
    int err = gc_visit_thread_stacks_mark_alive(interp, &args);
    for (_PyArg_Parser *parser = _PyRuntime.getargs.static_parsers;
         parser != NULL; parser = parser->next)
    {
        tracing_mark_address(graph, (uintptr_t)parser->kwtuple);
    }
    return err;
}

static void
tracing_find_dead_leaves(struct tracing_heap *graph,
                         struct collection_state *state)
{
    for (size_t i = 0; i < graph->size; i++) {
        struct tracing_page *page = &graph->pages[i];
        if (!page->leaf) {
            continue;
        }
        for (size_t j = 0; j < page->capacity; j++) {
            if (page->leaf_marks[j] == 0) {
                continue;
            }
            PyObject *op = (PyObject *)(page->start + j * page->stride +
                                       page->offset);
            bool immortal = _Py_IsImmortal(op);
            if (!immortal) {
                state->candidates++;
            }
            if (graph->leaf_only || graph->young_containers) {
                if (immortal || gc_is_alive(op)) {
                    graph->live_bytes += page->block_size;
                }
                else {
                    // Stage nursery deaths in the allocation map, not in
                    // an intrusive list through every dead object's header.
                    // Only these slots may be read after resuming mutators.
                    page->leaf_marks[j] = 3;
                }
                continue;
            }
            if (immortal) {
                continue;
            }
            if (page->leaf_marks[j] != 1) {
                if (graph->temporary_marks) {
                    gc_set_alive(op);
                }
                continue;
            }
            // Leaf snapshots do not clear old ALIVE bits. Only a new mark
            // may resurrect a candidate during a full GC's finalizer pass.
            // Do not set UNREACHABLE: legacy finalizers assume tp_traverse.
            gc_clear_alive(op);
            op->ob_tid = 0;
            op->ob_ref_local = 0;
            op->ob_ref_shared = _Py_REF_SHARED(1, _Py_REF_MERGED);
            worklist_push(&state->leaf_unreachable, op);
        }
    }
    state->leaf_candidates_ready = true;
}

static bool
tracing_delete_leaf(GCState *gcstate, PyObject *op)
{
    gc_clear_unreachable(op);
    gc_clear_alive(op);
    if (gcstate->debug & _PyGC_DEBUG_SAVEALL) {
        return false;
    }
#if !defined(Py_DEBUG) && !defined(Py_TRACE_REFS)
    // These exact leaves have no owned buffers or finalizers. Preserve the
    // normal destruction path for debug builds and reference tracers.
    if (_PyRuntime.ref_tracer.tracer_func == NULL &&
        (PyLong_CheckExact(op) || PyFloat_CheckExact(op) ||
         PyComplex_CheckExact(op) || PyBytes_CheckExact(op)))
    {
        PyObject_Free(op);
        return true;
    }
#endif
    op->ob_tid = 0;
    op->ob_ref_local = 0;
    op->ob_ref_shared = _Py_REF_MERGED;
    _Py_Dealloc(op);
    return true;
}

static bool
tracing_module_is_pinned(PyObject *op)
{
    if (!PyModule_Check(op)) {
        return false;
    }
    // Pure Python modules have no native state or callbacks requiring a
    // special destruction order. Their dictionaries participate in tracing
    // like other containers. Keep the conservative policy for C modules,
    // including slot-based modules that do not have a PyModuleDef.
    PyModuleObject *module = _PyModule_CAST(op);
    return module->md_token_is_def || module->md_token != NULL ||
           module->md_state != NULL || module->md_state_size != 0 ||
           module->md_state_traverse != NULL ||
           module->md_state_clear != NULL || module->md_state_free != NULL ||
           module->md_exec != NULL;
}

static void
tracing_classify_snapshot(struct tracing_heap *graph,
                          struct collection_state *state)
{
    assert(graph->temporary_marks);
    assert(graph->pending == NULL);
    assert(!state->tracing_classified);
    // Marking needs address order for binary searches. Classification and
    // worklist construction retain the allocator visitor's prior order so
    // that deallocation and freelist reuse do not change as a side effect.
    if (graph->size > 1) {
        qsort(graph->pages, graph->size, sizeof(*graph->pages),
              tracing_compare_classification_order);
    }
    for (size_t i = 0; i < graph->size; i++) {
        struct tracing_page *page = &graph->pages[i];
        if (!page->typed || page->leaf) {
            continue;
        }
        for (size_t j = 0; j < page->capacity; j++) {
            uint16_t mark = page->marks[j];
            if (mark == 0) {
                continue;
            }
            assert(mark == 1 || mark == 2);
            PyObject *op = (PyObject *)(page->start + j * page->stride +
                                       page->offset);
            state->long_lived_total++;
            bool marked = mark != 1;
            uint8_t bits = op->ob_gc_bits;
            bits &= ~(_PyGC_BITS_UNREACHABLE | _PyGC_BITS_ALIVE);
            if (marked &&
                state->gcstate->tracing_container_nursery_enabled)
            {
                bits |= _PyGC_BITS_ALIVE;
            }
            op->ob_gc_bits = bits;
            if (!(bits & _PyGC_BITS_TRACKED) ||
                (bits & _PyGC_BITS_FROZEN) || _Py_IsImmortal(op))
            {
                continue;
            }
            state->candidates++;
            if (marked) {
                continue;
            }
            gc_set_unreachable(op);
            _Py_atomic_store_uintptr_relaxed(&op->ob_tid, 0);
            _Py_atomic_store_uint32_relaxed(&op->ob_ref_local, 0);
            _Py_atomic_store_ssize_relaxed(
                &op->ob_ref_shared, _Py_REF_SHARED(1, _Py_REF_MERGED));
            if (has_legacy_finalizer(op)) {
                gc_clear_unreachable(op);
                worklist_push(&state->legacy_finalizers, op);
            }
            else {
                worklist_push(&state->unreachable, op);
            }
            state->long_lived_total--;
        }
    }
    state->tracing_classified = true;
}

static int
tracing_traverse_object(struct tracing_heap *graph,
                        struct tracing_page *page, uintptr_t block)
{
    int err = 0;
    PyObject *op = (PyObject *)(block + page->offset);
    // Body scans skip the header, so explicitly retain heap types.
    if (Py_TYPE(op)->tp_flags & Py_TPFLAGS_HEAPTYPE) {
        tracing_visit((PyObject *)Py_TYPE(op), graph);
    }
    if (PyType_Check(op) &&
        (((PyTypeObject *)op)->tp_flags & Py_TPFLAGS_HEAPTYPE))
    {
        PyHeapTypeObject *type = (PyHeapTypeObject *)op;
        // Claim owned storage before scanning the type's body. Shared
        // keys allocate more entries than they use; their unused tail
        // must not link unrelated allocations through stale pointers.
        if (type->ht_cached_keys != NULL) {
            tracing_visit_dict_keys(graph, type->ht_cached_keys);
        }
        // These are C strings, not arrays of Python references.
        tracing_claim_buffer(graph, type->ht_type.tp_doc);
        tracing_claim_buffer(graph, type->_ht_tpname);
    }
    if (PyAnyDict_CheckExact(op)) {
        tracing_visit_dict(graph, (PyDictObject *)op);
        return err;
    }
    if (PyAnySet_CheckExact(op)) {
        if (tracing_claim_buffer(graph, ((PySetObject *)op)->table)) {
            err = Py_TYPE(op)->tp_traverse(op, tracing_visit, graph);
        }
        return err;
    }
    bool precise = PyList_CheckExact(op) || PyTuple_CheckExact(op) ||
                   PyFunction_Check(op) || PyCell_Check(op) ||
                   (Py_TYPE(op)->tp_flags & _Py_TPFLAGS_TRACING_PRECISE);
    if (graph->young_containers && PyList_CheckExact(op)) {
        // The nursery initially excluded this exclusively owned buffer
        // from its live-byte count. Its owner has now been reached; count
        // the storage without conservatively scanning unused list slots.
        tracing_claim_buffer(graph, ((PyListObject *)op)->ob_item);
    }
    if (!PyWeakref_Check(op) && !precise) {
        // ob_tid can link sweep candidates during resurrection.
        uintptr_t body = (uintptr_t)(op + 1);
        tracing_scan_words(graph, (void *)block, page->offset);
        tracing_scan_words(graph, (void *)body,
                           block + page->block_size - body);
    }
    if (_PyObject_GC_IS_TRACKED(op) || precise) {
        // Include deliberately untracked audit hooks and tuples.
        err = Py_TYPE(op)->tp_traverse(op, tracing_visit, graph);
    }
    return err;
}

static int
tracing_drain_pending(struct tracing_heap *graph)
{
    int err = 0;
    while (err == 0 && graph->pending != NULL) {
        struct tracing_page *page = graph->pending;
        size_t index = page->pending;
        uintptr_t block = page->start + index * page->stride;
        if (page->marks[index] > 2) {
            page->pending = page->marks[index] - 3;
        }
        else {
            page->pending = SIZE_MAX;
            graph->pending = page->next_pending;
            page->next_pending = NULL;
        }
        page->marks[index] = 2;
        if (!page->typed) {
            // Auxiliary arrays are edges, not roots. Rooting all of them
            // would keep every list/dict cycle alive indefinitely.
            tracing_scan_words(graph, (void *)block, page->block_size);
            continue;
        }
        err = tracing_traverse_object(graph, page, block);
    }
    return err;
}

static int
tracing_defer_unreachable(struct tracing_heap *graph)
{
    assert(graph->young_containers && graph->pending == NULL);
    if (graph->deferred_young_bytes == 0) {
        return 0;
    }
    uintptr_t live_base = graph->live_bytes;
    // Real roots have been traced first. Turn only the remaining unsupported
    // young objects into implicit roots, without promoting their headers.
    // Mark all of them before traversing edges, so cycles among these roots
    // cannot accidentally promote an unreachable object during this pass.
    for (size_t i = 0; i < graph->size; i++) {
        struct tracing_page *page = &graph->pages[i];
        if (!page->may_defer) {
            continue;
        }
        bool deferred = false;
        for (size_t j = 0; j < page->capacity; j++) {
            if (page->marks[j] != 1) {
                continue;
            }
            PyObject *op = (PyObject *)(page->start + j * page->stride +
                                       page->offset);
            if (tracing_nursery_container(op, true)) {
                continue;
            }
            assert(!gc_is_alive(op));
            page->marks[j] = TRACING_DEFERRED_SLOT;
            graph->live_bytes += page->block_size;
            graph->nonleaf_live_bytes += page->block_size;
            deferred = true;
        }
        page->may_defer = deferred;
    }
    graph->tracing_deferred = true;
    int result = 0;
    for (size_t i = 0; result == 0 && i < graph->size; i++) {
        struct tracing_page *page = &graph->pages[i];
        if (!page->may_defer) {
            continue;
        }
        for (size_t j = 0; j < page->capacity; j++) {
            if (page->marks[j] != TRACING_DEFERRED_SLOT) {
                continue;
            }
            uintptr_t block = page->start + j * page->stride;
            if (tracing_traverse_object(graph, page, block) != 0 ||
                tracing_drain_pending(graph) != 0)
            {
                result = -1;
                break;
            }
            // Count each newly retained descendant once. Old objects and
            // children already reached from real roots add no pressure here.
            uintptr_t retained = graph->live_bytes - live_base +
                                 graph->deferred_leaf_bytes;
            if (retained > graph->deferred_young_limit) {
                result = 1;
                break;
            }
        }
    }
    graph->tracing_deferred = false;
    return result;
}

static int
tracing_mark_roots(PyInterpreterState *interp, struct collection_state *state)
{
    struct tracing_heap graph;
    if (state->saved_snapshot != NULL) {
        // The nursery fallback has kept the world stopped. No heap mutation
        // or finalizer has run since it flushed the freelists and took this
        // snapshot. Consume it once; resurrection requires a fresh snapshot.
        graph = *state->saved_snapshot;
        PyMem_RawFree(state->saved_snapshot);
        state->saved_snapshot = NULL;
        assert(!graph.young_containers && !graph.leaf_only);
    }
    else {
        // Freelist entries have dead object headers; do not interpret them
        // as typed allocations in the snapshot.
        _PyGC_ClearAllFreeLists(interp);
        graph = (struct tracing_heap){
            .temporary_marks = !state->leaf_candidates_ready,
        };
        if (tracing_snapshot(interp, &graph) < 0) {
            tracing_free_snapshot(&graph);
            return -1;
        }
    }
    int err = tracing_scan_roots(interp, state, &graph);
    for (size_t i = 0; i < graph.size; i++) {
        struct tracing_page *page = &graph.pages[i];
        if (!page->typed || page->leaf) {
            continue;
        }
        for (size_t j = 0; j < page->capacity; j++) {
            if (page->marks[j] == 0) {
                continue;
            }
            PyObject *op = (PyObject *)(page->start + j * page->stride +
                                       page->offset);
            // Instances without GC support are not yet reclaimed. Their
            // heap types must likewise remain valid in this prototype.
            bool pinned_type = PyType_Check(op) &&
                !(((PyTypeObject *)op)->tp_flags & Py_TPFLAGS_HAVE_GC);
            if (gc_is_frozen(op) || _Py_IsImmortal(op) || pinned_type ||
                tracing_module_is_pinned(op))
            {
                tracing_mark_address(&graph, (uintptr_t)op);
            }
        }
    }
    PyObject *op;
    WORKSTACK_FOR_EACH(&state->legacy_finalizers, op) {
        tracing_mark_address(&graph, (uintptr_t)op);
    }
    if (err == 0) {
        err = tracing_drain_pending(&graph);
    }
    if (err == 0 && !state->leaf_candidates_ready) {
        tracing_find_dead_leaves(&graph, state);
    }
    if (err == 0 && graph.temporary_marks) {
        tracing_classify_snapshot(&graph, state);
    }
    state->live_bytes = graph.live_bytes;
    if (err == 0) {
        state->gcstate->tracing_nonleaf_live_bytes = graph.nonleaf_live_bytes;
    }
    tracing_free_snapshot(&graph);
    return err;
}

// A leaf nursery can skip old containers only if writes to their storage
// are observed. This experimental backend uses Linux soft-dirty PTEs rather
// than requiring a write barrier at every C API pointer store. Unknown GC
// types still run tp_traverse: their edges may live outside managed heaps.
static bool
tracing_leaf_workload(GCState *gcstate)
{
    uintptr_t budget = (uintptr_t)gcstate->young.threshold * 4096;
    if (budget < gcstate->tracing_live_bytes) {
        budget = gcstate->tracing_live_bytes;
    }
    // A scalar nursery treats even newly allocated containers as roots.
    // Limit their allocation debt to one eighth of the nursery budget:
    // otherwise retaining their scalar children defeats partial collection.
    return gcstate->tracing_nonleaf_bytes < budget / 8;
}

#ifdef __linux__

static bool
tracing_dirty_allowed(PyInterpreterState *interp)
{
    if (!interp->gc.tracing_soft_dirty_enabled ||
        interp != &_PyRuntime._main_interpreter)
    {
        return false;
    }
    // clear_refs affects the whole process, not just one interpreter.
    HEAD_LOCK(&_PyRuntime);
    bool alone = _PyRuntime.interpreters.head == interp && interp->next == NULL;
    HEAD_UNLOCK(&_PyRuntime);
    return alone;
}

static bool
tracing_read_pagemap(int fd, uintptr_t first_page, uint64_t *entries, size_t count)
{
    size_t bytes = count * sizeof(*entries);
    off_t offset = (off_t)(first_page * sizeof(*entries));
    char *dest = (char *)entries;
    while (bytes != 0) {
        ssize_t n = pread(fd, dest, bytes, offset);
        if (n < 0 && errno == EINTR) {
            continue;
        }
        if (n <= 0 || n % sizeof(*entries) != 0) {
            return false;
        }
        dest += n;
        bytes -= n;
        offset += n;
    }
    return true;
}

static bool
tracing_dirty_epoch_valid(GCState *gcstate, int fd)
{
    if (gcstate->tracing_dirty_pid != (long)getpid() ||
        gcstate->tracing_dirty_sentinel == 0)
    {
        return false;
    }
    uint64_t entry;
    return tracing_read_pagemap(fd, gcstate->tracing_dirty_sentinel /
                               gcstate->tracing_os_page_size, &entry, 1) &&
           (entry & (UINT64_C(1) << 55)) != 0;
}

static void
tracing_reset_dirty(PyInterpreterState *interp)
{
    GCState *gcstate = &interp->gc;
    gcstate->tracing_dirty_pid = 0;
    if (!tracing_dirty_allowed(interp)) {
        return;
    }
    if (gcstate->tracing_dirty_sentinel == 0) {
        long page_size = sysconf(_SC_PAGESIZE);
        if (page_size <= 0 || (size_t)page_size > SIZE_MAX / 3) {
            return;
        }
        // Isolate the sentinel's VMA with guard pages. A neighboring mmap
        // (notably a new JIT code page) can otherwise merge with its mapping
        // and set VM_SOFTDIRTY without writing the sentinel, hiding an
        // external clear_refs and invalidating the nursery's old roots.
        size_t size = (size_t)page_size * 3;
        char *mapping = mmap(NULL, size, PROT_NONE,
                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapping == MAP_FAILED) {
            return;
        }
        void *sentinel = mapping + page_size;
        if (mprotect(sentinel, page_size, PROT_READ | PROT_WRITE) < 0) {
            munmap(mapping, size);
            return;
        }
        gcstate->tracing_os_page_size = (size_t)page_size;
        gcstate->tracing_dirty_sentinel = (uintptr_t)sentinel;
    }
    int fd = open("/proc/self/clear_refs", O_WRONLY | O_CLOEXEC);
    if (fd < 0) {
        return;
    }
    ssize_t n;
    do {
        n = write(fd, "4", 1);
    } while (n < 0 && errno == EINTR);
    close(fd);
    if (n == 1) {
        // Only the collector writes this private page. Check it before AND
        // after reading PTEs to detect any intervening external clear_refs.
        // This also handles tools which reset soft-dirty tracking between GCs.
        *(volatile unsigned char *)gcstate->tracing_dirty_sentinel = 1;
        gcstate->tracing_dirty_pid = (long)getpid();
    }
}

static bool
tracing_pte_dirty(uint64_t entry)
{
    // Shared/file pages and non-present pages are always scanned. Shared
    // mappings may lose soft-dirty information when zapped or swapped out.
    const uint64_t mask = (UINT64_C(1) << 63) | (UINT64_C(1) << 61) |
                          (UINT64_C(1) << 55);
    return (entry & mask) != (UINT64_C(1) << 63);
}

static bool
tracing_area_clean(const struct tracing_heap *graph,
                        const mi_heap_area_t *area)
{
    if (area->used == 0) {
        return true;
    }
    if (area->used == area->committed / area->full_block_size) {
        // All slots are allocated, so the first header is safe to inspect
        // without a free-slot map. A young first object already proves that
        // this area needs a snapshot; avoid a pagemap syscall in that case.
        PyObject *op = (PyObject *)((uintptr_t)area->blocks + graph->offset);
        if (!gc_is_alive(op) && !_Py_IsImmortal(op)) {
            return false;
        }
    }
    assert(graph->os_page_size != 0);
    uintptr_t start = (uintptr_t)area->blocks;
    uintptr_t first = start / graph->os_page_size;
    uintptr_t last = (start + area->committed - 1) / graph->os_page_size;
    // Keep large allocations bounded without allocating another
    // buffer. Read failures, swapped pages and shared mappings all retain
    // the ordinary allocation map and traversal. The caller validates the
    // dirty epoch again before it commits any nursery deaths.
    uint64_t entries[64];
    while (first <= last) {
        size_t count = last - first + 1;
        if (count > Py_ARRAY_LENGTH(entries)) {
            count = Py_ARRAY_LENGTH(entries);
        }
        if (!tracing_read_pagemap(graph->leaf_pagemap_fd, first, entries, count)) {
            return false;
        }
        for (size_t i = 0; i < count; i++) {
            if (tracing_pte_dirty(entries[i])) {
                return false;
            }
        }
        first += count;
    }
    return true;
}

struct tracing_dirty_scan {
    struct tracing_heap *graph;
    size_t page_size;
    size_t offset;
    int fd;
    bool typed;
    PyObject **opaque;
    size_t opaque_count;
    size_t opaque_capacity;
};

static bool
tracing_scan_dirty_area(const mi_heap_t *heap, const mi_heap_area_t *area,
                        void *block, size_t block_size, void *arg)
{
    assert(block == NULL);
    if (area->used == 0) {
        return true;
    }
    struct tracing_dirty_scan *scan = arg;
    uintptr_t start = (uintptr_t)area->blocks;
    struct tracing_page *young_page = NULL;
    if (scan->graph->young_containers) {
        young_page = tracing_find_page(scan->graph, start);
        if (young_page == NULL) {
            // Only cached clean typed areas can be omitted from a nonleaf
            // snapshot. The final uncached sentinel check still guards the
            // epoch before any deaths or cached metadata are committed.
            assert(scan->typed && tracing_find_old_page(
                scan->graph, area, scan->offset) != NULL);
            return true;
        }
        assert(young_page != NULL && young_page->start == start);
        bool has_roots = false;
        for (size_t i = 0; i < young_page->capacity; i++) {
            uint16_t mark = young_page->marks[i];
            if (scan->typed ? mark == TRACING_OLD_SLOT :
                mark != 0 && mark != TRACING_YOUNG_BUFFER)
            {
                has_roots = true;
                break;
            }
        }
        if (!has_roots) {
            // A page of only young containers or their private buffers has
            // no old-to-young roots. Avoid even reading its pagemap entries.
            return true;
        }
    }
    uintptr_t end = start + area->committed;
    uintptr_t first = start / scan->page_size;
    size_t pages = (end - 1) / scan->page_size - first + 1;
    if (pages > SIZE_MAX / sizeof(uint64_t)) {
        return false;
    }
    uint64_t *entries = PyMem_RawMalloc(pages * sizeof(*entries));
    if (entries == NULL) {
        return false;
    }
    if (!tracing_read_pagemap(scan->fd, first, entries, pages)) {
        PyMem_RawFree(entries);
        return false;
    }
    bool dirty = false;
    for (size_t i = 0; i < pages; i++) {
        dirty |= tracing_pte_dirty(entries[i]);
    }
    if (!dirty && !scan->typed) {
        PyMem_RawFree(entries);
        return true;
    }
    size_t capacity = area->committed / area->full_block_size;
    uint8_t *allocated = NULL;
    if (young_page == NULL) {
        allocated = PyMem_RawMalloc(capacity);
        if (allocated == NULL) {
            PyMem_RawFree(entries);
            return false;
        }
        memset(allocated, 1, capacity);
        mi_page_t *page = _mi_ptr_page(area->blocks);
        assert(page->local_free == NULL);
        for (mi_block_t *free = page->free; free != NULL;
             free = mi_block_next(page, free))
        {
            allocated[((uintptr_t)free - start) / area->full_block_size] = 0;
        }
    }
    else {
        // The container snapshot already has an allocation map. The world
        // has remained stopped, so there is no need to reconstruct it.
        assert(young_page->capacity == capacity);
    }
    bool ok = true;
    bool cache_old = !dirty && scan->typed && young_page != NULL;
    Py_ssize_t old_candidates = 0;
    for (size_t i = 0; i < capacity; i++) {
        if (young_page != NULL) {
            uint16_t mark = young_page->marks[i];
            if (mark != 0 && mark != TRACING_OLD_SLOT) {
                cache_old = false;
            }
            if (scan->typed ? mark != TRACING_OLD_SLOT :
                mark == 0 || mark == TRACING_YOUNG_BUFFER)
            {
                // Young bodies/buffers are traced only after reaching an owner.
                continue;
            }
        }
        else if (!allocated[i]) {
            continue;
        }
        uintptr_t address = start + i * area->full_block_size;
        uintptr_t limit = address + area->block_size;
        PyObject *op = scan->typed ? (PyObject *)(address + scan->offset) : NULL;
        bool precise = op != NULL &&
                       (Py_TYPE(op)->tp_flags & _Py_TPFLAGS_TRACING_PRECISE);
        if (dirty && !precise) {
            uintptr_t cursor = address;
            while (cursor < limit) {
                size_t index = cursor / scan->page_size - first;
                uintptr_t next = (cursor / scan->page_size + 1) * scan->page_size;
                if (next > limit) {
                    next = limit;
                }
                if (tracing_pte_dirty(entries[index])) {
                    tracing_scan_words(scan->graph, (void *)cursor, next - cursor);
                }
                cursor = next;
            }
        }
        if (scan->typed) {
            bool managed = PyAnyDict_CheckExact(op) || PyAnySet_CheckExact(op) ||
                           PyList_CheckExact(op) || PyTuple_CheckExact(op) ||
                           PyFunction_Check(op) || PyCell_Check(op);
            if (!managed) {
                cache_old = false;
            }
            if (cache_old && !_Py_IsImmortal(op)) {
                old_candidates++;
            }
            if (!managed && (_PyObject_GC_IS_TRACKED(op) || precise)) {
                if (scan->opaque_count == scan->opaque_capacity) {
                    size_t capacity = scan->opaque_capacity ? scan->opaque_capacity * 2 : 256;
                    if (capacity < scan->opaque_capacity ||
                        capacity > SIZE_MAX / sizeof(*scan->opaque))
                    {
                        ok = false;
                        break;
                    }
                    void *items = PyMem_RawRealloc(scan->opaque,
                                                   capacity * sizeof(*scan->opaque));
                    if (items == NULL) {
                        ok = false;
                        break;
                    }
                    scan->opaque = items;
                    scan->opaque_capacity = capacity;
                }
                scan->opaque[scan->opaque_count++] = op;
            }
        }
    }
    PyMem_RawFree(allocated);
    PyMem_RawFree(entries);
    if (ok && cache_old) {
        struct tracing_old_page old = {
            .start = start,
            .end = end,
            .block_size = area->block_size,
            .stride = area->full_block_size,
            .offset = scan->offset,
            .used = area->used,
            .candidates = old_candidates,
        };
        tracing_cache_old_page(scan->graph, &old);
    }
    return ok;
}

static bool
tracing_scan_dirty_heaps(PyInterpreterState *interp, struct tracing_heap *graph,
                         int fd)
{
    struct tracing_dirty_scan scan = {
        .graph = graph,
        .page_size = interp->gc.tracing_os_page_size,
        .fd = fd,
    };
    size_t debug_offset = _PyMem_DebugEnabled() ? 2 * sizeof(size_t) : 0;
    bool ok = true;
    HEAD_LOCK(&_PyRuntime);
    for (int tag = 0; tag < _Py_MIMALLOC_HEAP_COUNT; tag++) {
        if (tag == _Py_MIMALLOC_HEAP_LEAF) {
            continue;
        }
        scan.typed = tag == _Py_MIMALLOC_HEAP_GC || tag == _Py_MIMALLOC_HEAP_GC_PRE;
        scan.offset = debug_offset;
        if (tag == _Py_MIMALLOC_HEAP_GC_PRE) {
            scan.offset += 2 * sizeof(PyObject *);
        }
        _Py_FOR_EACH_TSTATE_UNLOCKED(interp, p) {
            struct _mimalloc_thread_state *m = &((_PyThreadStateImpl *)p)->mimalloc;
            if (_Py_atomic_load_int(&m->initialized) &&
                !mi_heap_visit_blocks(&m->heaps[tag], false,
                                       tracing_scan_dirty_area, &scan))
            {
                ok = false;
                goto done;
            }
        }
        if (!_mi_abandoned_pool_visit_blocks(&interp->mimalloc.abandoned_pool,
                                             tag, false,
                                             tracing_scan_dirty_area, &scan))
        {
            ok = false;
            break;
        }
    }
done:
    HEAD_UNLOCK(&_PyRuntime);
    // Do not invoke extension traversals while holding the runtime head lock.
    // The world is still stopped and no nonleaf object is being reclaimed.
    for (size_t i = 0; ok && i < scan.opaque_count; i++) {
        PyObject *op = scan.opaque[i];
        ok = Py_TYPE(op)->tp_traverse(op, tracing_visit, graph) == 0;
    }
    PyMem_RawFree(scan.opaque);
    return ok;
}

static bool
tracing_collect_leaves(PyInterpreterState *interp, struct collection_state *state)
{
    // On success this function also restarts the world and sweeps. Failure
    // leaves it stopped, with no staged deaths committed, for full tracing.
    GCState *gcstate = &interp->gc;
    if (state->reason != _Py_GC_REASON_HEAP ||
        gcstate->tracing_minor_count >= 7 ||
        !tracing_leaf_workload(gcstate) ||
        state->unreachable.head || state->objs_to_decref.head ||
        !tracing_dirty_allowed(interp))
    {
        return false;
    }
    int fd = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }
    if (!tracing_dirty_epoch_valid(gcstate, fd)) {
        close(fd);
        return false;
    }
    _PyGC_ClearAllFreeLists(interp);
    struct tracing_heap graph = {
        .leaf_only = true,
        .leaf_pagemap_fd = fd,
        .os_page_size = gcstate->tracing_os_page_size,
    };
    bool ok = tracing_snapshot(interp, &graph) == 0 &&
              tracing_scan_roots(interp, state, &graph) == 0 &&
              tracing_scan_dirty_heaps(interp, &graph, fd) &&
              tracing_dirty_epoch_valid(gcstate, fd);
    close(fd);
    if (ok) {
        tracing_find_dead_leaves(&graph, state);
        state->live_bytes = graph.live_bytes + gcstate->tracing_nonleaf_live_bytes +
                            gcstate->tracing_nonleaf_bytes;
        state->long_lived_total = gcstate->long_lived_total;
        gcstate->tracing_minor_count++;
        gcstate->tracing_skipped_leaf_pages = graph.skipped_leaf_pages;
        // Retain the dirty-page union until the next full collection; another
        // clear_refs here would refault allocator metadata and recycled leaves.
        // No containers or finalizers are collected in this path. All dead
        // leaves are now identified, and none support weak references, so
        // they cannot be resurrected by another thread. Resume the world
        // before deallocation, which may invoke a reference tracer.
        _PyEval_StartTheWorld(interp);
        for (size_t i = 0; i < graph.size; i++) {
            struct tracing_page *page = &graph.pages[i];
            for (size_t j = 0; j < page->capacity; j++) {
                if (page->leaf_marks[j] != 3) {
                    continue;
                }
                PyObject *op = (PyObject *)(page->start + j * page->stride +
                                           page->offset);
                state->collected += tracing_delete_leaf(gcstate, op);
            }
        }
    }
    tracing_free_snapshot(&graph);
    return ok;
}

static bool
tracing_collect_containers(PyInterpreterState *interp,
                           struct collection_state *state)
{
    GCState *gcstate = &interp->gc;
    if (!gcstate->tracing_container_nursery_enabled ||
        gcstate->tracing_container_backoff != 0 ||
        state->reason != _Py_GC_REASON_HEAP ||
        gcstate->tracing_minor_count >= 7 ||
        (gcstate->debug & _PyGC_DEBUG_SAVEALL) ||
        _PyRuntime.ref_tracer.tracer_func != NULL ||
        state->unreachable.head || state->objs_to_decref.head ||
        !tracing_dirty_allowed(interp))
    {
        return false;
    }
    int fd = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }
    if (!tracing_dirty_epoch_valid(gcstate, fd)) {
        close(fd);
        return false;
    }
    _PyGC_ClearAllFreeLists(interp);
    uintptr_t budget = (uintptr_t)gcstate->young.threshold * 4096;
    if (budget < gcstate->tracing_nursery_base_bytes) {
        budget = gcstate->tracing_nursery_base_bytes;
    }
    // As with the scalar nursery, allow at most one eighth of a full-GC
    // budget in newly allocated objects that this nursery cannot reclaim.
    struct tracing_heap graph = {
        .young_containers = true,
        .previous_old_pages = gcstate->tracing_old_pages,
        .previous_old_page_count = gcstate->tracing_old_page_count,
        .deferred_young_limit = budget / 8,
        .leaf_pagemap_fd = fd,
        .os_page_size = gcstate->tracing_os_page_size,
    };
    bool ok = tracing_snapshot(interp, &graph) == 0;
    if (graph.deferred_young_bytes > graph.deferred_young_limit) {
        // This attempt cannot reclaim enough of the new heap. Including
        // this fallback, use four full collections before trying again.
        // Do not impose this pause for OOM or an invalid dirty epoch.
        gcstate->tracing_container_backoff = 4;
    }
    if (ok && !graph.young_containers) {
        assert(state->saved_snapshot == NULL);
        // Transfer ownership to the immediately following full root pass.
        // If saving the map fails, the ordinary fallback can rebuild it.
        struct tracing_heap *saved = PyMem_RawMalloc(sizeof(*saved));
        if (saved != NULL) {
            *saved = graph;
            state->saved_snapshot = saved;
            close(fd);
            return false;
        }
        ok = false;
    }
    if (ok) {
        ok = tracing_scan_dirty_heaps(interp, &graph, fd) &&
             tracing_scan_roots(interp, state, &graph) == 0 &&
             tracing_drain_pending(&graph) == 0 &&
             tracing_dirty_epoch_valid(gcstate, fd);
        if (ok) {
            int deferred = tracing_defer_unreachable(&graph);
            if (deferred > 0) {
                gcstate->tracing_container_backoff = 4;
            }
            // A late fallback takes a fresh full snapshot: unlike the early
            // fallback, this graph has already traced and promoted children.
            ok = deferred == 0 && tracing_dirty_epoch_valid(gcstate, fd);
        }
    }
    close(fd);
    Py_ssize_t previous_candidates = state->candidates;
    if (ok) {
        // Nursery leaves are only staged in the temporary map, so we can
        // still fall back after accounting for their promoted live bytes.
        tracing_find_dead_leaves(&graph, state);
    }
    // Unknown types are kept for a full collection. Do not let that policy
    // or promotion grow the old generation by more than one full-GC budget.
    if (graph.live_bytes > gcstate->tracing_nursery_base_bytes &&
        graph.live_bytes - gcstate->tracing_nursery_base_bytes > budget)
    {
        ok = false;
    }
    if (ok) {
        // All fallible tracing work has finished. The allocation map already
        // identifies every death, so account and reclaim in a single pass.
        // No callback can observe partial statistics or require an earlier
        // pass that sets UNREACHABLE in all the dead container headers.
        // No candidate has a finalizer, weakref, or dict watcher, and normal
        // deallocation will not be deferred through the trashcan. Finish this
        // callback-free sweep before restarting other threads: otherwise their
        // allocations can outrun reclamation while collection is in progress.
        // Keep the dirty-page union until the next full collection.
        assert(interp->stoptheworld.world_stopped);
        _PyMem_TracingSweep sweep;
        _PyMem_BeginTracingSweep(&sweep, interp);
        state->candidates += graph.skipped_old_candidates;
        state->long_lived_total += graph.skipped_old_objects;
        for (size_t i = 0; i < graph.size; i++) {
            struct tracing_page *page = &graph.pages[i];
            if (!page->typed || page->leaf) {
                continue;
            }
            for (size_t j = 0; j < page->capacity; j++) {
                uint16_t mark = page->marks[j];
                if (mark == 0) {
                    continue;
                }
                PyObject *op = (PyObject *)(page->start + j * page->stride +
                                           page->offset);
                if (!_Py_IsImmortal(op)) {
                    state->candidates++;
                }
                if (mark != 1) {
                    state->long_lived_total++;
                    continue;
                }
                // These exact types cannot invoke finalizers, and decrefs
                // cannot destroy or inspect their children. Their normal
                // deallocators release owned storage without a tp_clear pass.
                assert(tracing_nursery_container(op, true));
                assert(!gc_is_alive(op) && !gc_is_frozen(op));
                assert(!gc_is_unreachable(op));
                // Untrack while exclusive access is guaranteed, avoiding
                // the deallocator's otherwise atomic tracking-bit update.
                gc_clear_bit(op, _PyGC_BITS_TRACKED);
                op->ob_tid = 0;
                op->ob_ref_local = 0;
                op->ob_ref_shared = _Py_REF_MERGED;
                tracing_prepare_nursery_dealloc(op);
                _Py_Dealloc(op);
                state->collected++;
            }
        }
        for (size_t i = 0; i < graph.size; i++) {
            struct tracing_page *page = &graph.pages[i];
            if (!page->leaf) {
                continue;
            }
            for (size_t j = 0; j < page->capacity; j++) {
                if (page->leaf_marks[j] == 3) {
                    PyObject *op = (PyObject *)(page->start + j * page->stride +
                                               page->offset);
                    state->collected += tracing_delete_leaf(gcstate, op);
                }
            }
        }
        // Container deallocation can refill this thread's freelists. Flush
        // them before restarting mutators, as in the full simple sweep.
        _PyThreadStateImpl *tstate = (_PyThreadStateImpl *)_PyThreadState_GET();
        _PyObject_ClearFreeLists(&tstate->freelists, 0);
        _PyMem_EndTracingSweep(&sweep);
        state->live_bytes = graph.live_bytes;
        gcstate->tracing_nonleaf_live_bytes = graph.nonleaf_live_bytes;
        gcstate->tracing_nonleaf_bytes = 0;
        gcstate->long_lived_total = state->long_lived_total;
        gcstate->tracing_minor_count++;
        gcstate->tracing_skipped_leaf_pages = graph.skipped_leaf_pages;
        gcstate->tracing_skipped_old_pages = graph.skipped_old_pages;
        tracing_publish_old_pages(gcstate, &graph);
        _PyEval_StartTheWorld(interp);
    }
    else {
        state->candidates = previous_candidates;
        state->leaf_candidates_ready = false;
    }
    tracing_free_snapshot(&graph);
    return ok;
}

static void
tracing_fini_dirty(GCState *gcstate)
{
    tracing_clear_old_pages(gcstate);
    if (gcstate->tracing_dirty_sentinel != 0) {
        size_t page_size = gcstate->tracing_os_page_size;
        munmap((void *)(gcstate->tracing_dirty_sentinel - page_size),
               page_size * 3);
        gcstate->tracing_dirty_sentinel = 0;
    }
    gcstate->tracing_dirty_pid = 0;
}

#else

static bool
tracing_area_clean(const struct tracing_heap *graph,
                        const mi_heap_area_t *area)
{
    return false;
}

static bool
tracing_collect_containers(PyInterpreterState *interp,
                           struct collection_state *state)
{
    return false;
}

static bool
tracing_collect_leaves(PyInterpreterState *interp, struct collection_state *state)
{
    return false;
}

static void
tracing_reset_dirty(PyInterpreterState *interp)
{
}

static void
tracing_fini_dirty(GCState *gcstate)
{
}

#endif
