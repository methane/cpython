# Base16 regression diagnosis

The fixed-main and candidate workers load byte-for-byte identical `base64.py`
files (SHA-256 `4b0f878149dfe3426e62439af3649aaf25c4dbd829cb6db5cd47d21c20a964fb`).
The two pyperformance copies of `bm_base64/run_benchmark.py` are also
identical.  The merge therefore removed the earlier source-revision mismatch.

Matched focused runs nevertheless reproduce the regression with native JIT
execution disabled.  Two opposite-order blocks give geometric-mean
candidate/main ratios of 1.085751 for `base16_small` and 1.134878 for
`base16_large`.  Enabling the native JIT with every experimental opt-in absent
gives 1.059544 and 1.128936 in one block.  The merged binary saved before the
Go work gives 1.062404 and 1.135306 with the JIT disabled.  The effect therefore
predates the Go optimizations and does not require native JIT execution.

Splitting the 1 MiB path into operations, again in opposite orders, gives:

| Operation | Candidate/main |
|---|---:|
| `binascii.hexlify` | 1.056739 |
| `bytes.upper` | 1.054533 |
| six absent `bytes` membership tests | 1.017705 |
| `binascii.unhexlify` | 1.001973 |
| complete `base64.b16encode` | 1.341611 |
| complete `base64.b16decode` | 1.009457 |

The large regression comes from the encode path when its large return value is
discarded immediately, as it is by the benchmark.  A matching 800-encode perf
probe executes essentially the same instruction count and incurs about 816,000
minor faults on both binaries.  Candidate spends substantially more user
cycles; kernel cycles and syscall counts are close.  Raising the diagnostic
glibc mmap, trim, and top-pad thresholds reduces the minor faults to about
2,600 and reduces the task-clock ratio to about 1.06.  These allocator settings
are diagnostic only and were not used for the suite result.

The relevant extension-module `.text` is identical.  In the executable,
`_Py_bytes_upper` also has identical instructions, but its hot loop starts at
offset 8 within a 32-byte block in fixed main and offset 24 in candidate.  The
candidate loop therefore crosses that block boundary.  The merged pre-Go
binary has the same address as the current candidate.  This is consistent with
a binary-layout effect that is amplified by repeated allocation, page faults,
and immediate release of multi-megabyte temporary bytes.

The Base16 source mismatch is fixed.  The remaining result is a rebuild and
code-layout sensitivity, rather than a semantic regression in `Lib/base64.py`
or one of the opt-in native-JIT transformations.  Removing the two Base16
results as a post-hoc sensitivity calculation changes the suite geometric mean
from 0.972383 over 117 loop-matched results to 0.970367 over 115 results; the
predeclared primary result remains unchanged.
