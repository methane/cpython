# Native same-input acceptance

Measured with ordinary hotness in fresh processes. Every call used `initial=2**40`; no compact seed was used. Timings include per-call result validation. Each resident sample was calibrated to roughly 100 ms.

| workload | n | off ns/call | resident ns/call | resident sample ms | resident iterations | code bytes |
|---|---:|---:|---:|---:|---:|---:|
| sum | 1000 | 24241.1 | 976.4 | 97.6 | 299400000 | 4096 |
| sum | 100000 | 2980141.4 | 82288.3 | 82.3 | 299994000 | 4096 |
| squares | 1000 | 30142.4 | 1192.8 | 119.3 | 299400000 | 4096 |
| squares | 100000 | 4891159.1 | 103712.4 | 103.7 | 299994000 | 4096 |

All eight runs were complete and stable. The off runs made zero resident progress; every resident run entered, processed iterations, and reported nonempty code for every sample. Raw per-sample diagnostics are retained in the adjacent JSON files.

Representative headerless native code was captured from the actual same-input executors and disassembled with `objdump -D -b binary -m i386:x86-64` into `sum.asm` and `squares.asm`. The manifest distinguishes the tested source tree from the executable hash.
The sum loop contains checked `add`/`jo`, while the squares loop contains
checked `imul`/`jo` followed by checked `add`/`jo`; both retain the loop-bound
and polling checks before their out-of-line reconstruction/runtime calls.
