# Unicode UTF-8 storage

Normal completed strings have a compact UTF-8 payload. Valid UTF-8 input is
validated and copied directly, without an intermediate FSR. Invalid input uses
the existing decoder and error handlers before finalizing into UTF-8 storage.
ASCII keeps the existing small header and shares its payload with fixed-width
readers. Non-ASCII uses
`PyCompactUnicodeObject`, followed by `utf8_length` bytes and a terminating NUL.
Lengths exposed to Python and the C API still count code points.

The payload is UTF-8 with surrogatepass: every surrogate is a separate three-byte
sequence, including adjacent high/low surrogates. `has_surrogates` records content,
not whether the value originated in a surrogateescape decoder. Strict UTF-8
exports reject these strings. Concatenation never combines surrogate pairs.

## Fixed-width access

`kind` records the required PEP 393 element width without allocating. `fsr` is
initially NULL, except for statically allocated Latin-1 singletons, which have a
static one-byte view. `_PyUnicode_GetFSR()` allocates a terminated array and
publishes it only after completion. The free-threaded build uses an acquire load
and a release store under the object's critical section. A failed allocation
leaves the object unchanged. A published view is retained until destruction.

`PyUnicode_DATA()` and the typed data macros return NULL on allocation failure;
`PyUnicode_READ_CHAR()` returns `(Py_UCS4)-1`. Every caller must propagate the
exception. `PyUnicode_READ()` itself still operates on a caller-supplied array.
Internal allocation-free consumers can scan with `_PyUnicode_ReadCharNoAlloc()`;
this is not the API for repeated random access.

Hashing, equality, ordering, UTF-8 output, concatenation, and ordinary and virtual
iteration consume the primary payload without generating a FSR. Hashing uses
surrogatepass bytes for both storage forms. Non-ASCII hashes can therefore differ
from earlier releases. ASCII hashes retain their correspondence with bytes.
Algorithms without a native path acquire a FSR before their fixed-width loops.

`str.count` and `str.replace` search the encoded bytes directly when all
operands have a primary UTF-8 representation (including ASCII). Nonempty UTF-8
patterns can only match at code point boundaries, including surrogatepass
sequences. Count bounds are converted from code point offsets to byte offsets;
empty patterns count code point boundaries. Replacement inserts empty-pattern
matches only between code points and recomputes the result's character width
and surrogate flag. Mixed FSR operands retain the fixed-width implementation;
ASCII-only replacement also retains its existing specialized implementation.

The native UTF-8 paths also cover containment, forward/reverse searches,
prefix/suffix matching and removal, contiguous slices, explicit-separator and
whitespace splitting, partitioning, line splitting, stripping, joining,
repetition, padding, zero filling, and tab expansion. Bounded searches translate
character offsets to byte boundaries; returned indices count code points.
Suffix operations locate boundaries from the end when that is closer.

Character predicates (`isalpha`, `isalnum`, `isspace`, `isdecimal`, `isdigit`,
`isnumeric`, `islower`, `isupper`, `istitle`, and `isprintable`) decode sequentially
without allocating an FSR, or reuse an existing FSR. `isascii`, `isidentifier`,
length, iteration, comparisons, hashing and UTF-8 output already have native
paths. Case conversion decodes sequentially and writes mapped code points into
a temporary UTF-8 buffer, sharing the existing full mapping tables. Final sigma
looks backward and forward through the original UTF-8 code points, preserving
case-ignorable context. Translation, representation and formatting retain their
fixed-width algorithms and need separate performance work.

`Tools/scripts/bench_unicode_methods.py` measures first-call CPU time and retained
input memory; `--warm` measures calls after indexing has materialized a FSR.
Use matching build options. Avoid interpreting debug-build ratios as release
performance claims. The byte-oriented methods preserve existing ASCII
specializations where applicable and fall back for FSR-primary operands.
Whitespace and line splitting also reuse an already materialized FSR to avoid
paying to decode the same text again. Impossible matches are rejected using
length and known character-width metadata before scanning either payload.

## Construction and compatibility

`PyUnicode_New()` returns a writable FSR (inline for ASCII, separately allocated
for non-ASCII). Completed constructors and Writer results convert to compact
UTF-8. Subclasses retain separately allocated data.

The existing `PyUnicode_WriteChar`, `PyUnicode_Fill`, and
`PyUnicode_CopyCharacters` contracts also allow a private, unused decoded string
to be modified. Such a string is promoted to FSR-primary storage in place:
`utf8_storage` continues to describe its allocation, while `fsr_primary` selects
the active representation. The original inline payload is no longer read.
`inline_length` preserves its allocation size for `__sizeof__`; `utf8_length` is
then available for a newly generated UTF-8 cache. Resizing copies these compact
allocations into a construction buffer rather than resizing their old payload.

Exporting an inline UTF-8 pointer records it in `utf8`, preventing a subsequent
promotion from invalidating that pointer. Hashing, interning, sharing, and other
uses continue to prohibit modification. Raw `PyUnicode_WRITE()` cannot notify
the object of a write and must only target a `PyUnicode_New()` construction buffer.

The layout and the non-limited direct-access API are incompatible with old
headers. Extensions using them need rebuilding and error handling updates.
Stable ABI function signatures are unchanged; their behavior must be validated
with limited-API extension tests. This implementation does not establish an
upstream transition schedule or an acceptance threshold for performance.

## Validation

The C API storage tests inspect lazy views without materializing them. They cover
ASCII/Latin-1/BMP/non-BMP values, embedded NUL, surrogatepass/surrogateescape,
virtual iteration, cache allocation failure and retry, and native operations.
Existing string, codec, C API, formatting, serialization, and size tests cover
Python behavior and writable construction APIs. Run both debug GIL and debug
free-threaded configurations; cache publication requires concurrent testing.

For each out-of-tree build, run:

```sh
./python -m test -j2 test_str test_capi.test_unicode test_codecs test_sys test_hash
./python -m test -j2 test_faulthandler test_gdb.test_pretty_print
```

Additionally run `test_free_threading.test_str` in the `--disable-gil` build,
and `test_gdb.test_pretty_print -u cpu -m '*test_strings'` to include the longer
UTF-8 debugger regression. A full regression run is needed to cover consumers
outside the Unicode implementation. Stable ABI validation should also load the
same limited-API extension binary built against unchanged headers in both the
baseline and modified interpreters.

The Linux debug regression suite completed in two batches: 270 modules passed
in the initial run, followed by 211 passing modules in the retry/remaining batch
(including four repeated modules). Platform and optional-resource skips remain.
The final free-threaded run passed 713 tests, and a separately built `_decimal`
extension passed 738 tests. The same limited-API smoke-test binary passed with
both the baseline and modified debug interpreters.

Allocation-failure sweeps passed for 21 string and codec operations with a
precompiled regular expression. Compiling that expression inside the sweep can
crash in `tuple_alloc()` while resetting a freelist tuple's hash cache. The same
crash and C stack were reproduced on the unchanged baseline revision recorded below;
this pre-existing allocator-failure issue is outside the storage change.

Measure UTF-8-only and FSR-materialized memory separately. UTF-8 increases the
payload size of Latin-1 and BMP-only non-ASCII strings; accessing their FSR adds a
second payload. ASCII-heavy strings containing a few wide code points may shrink.
The first indexed read is linear; later indexed reads use the retained FSR.

`Tools/scripts/bench_unicode_storage.py` reports these sizes and exploratory
timings. On a 64-bit AArch64 debug build, for 4096-code-point strings:

| Content | Baseline bytes | UTF-8 bytes | After FSR access |
| --- | ---: | ---: | ---: |
| ASCII | 4137 | 4137 | 4137 |
| Latin-1 (`é`) | 4153 | 8265 | 12362 |
| BMP (`日`) | 8250 | 12361 | 20555 |
| Non-BMP (`😀`) | 16444 | 16457 | 32845 |
| 4095 ASCII + one `😀` | 16444 | 4172 | 20560 |

The baseline was revision `6dad8b88cc39d8f9f41c22502a0b52304b326dd9`;
both builds used GCC 13.3 and `--with-pydebug`. First non-ASCII indexed reads
took about 22–29 microseconds with this change, versus 0.5–2.5 microseconds in
the baseline. UTF-8 decode, encode, and non-ASCII concatenation improved in this
small experiment; hashing and warm BMP/non-BMP indexing sometimes regressed.
These debug-build measurements were collected while other tests were running
and are not release-build performance claims.
