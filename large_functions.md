# Largest functions in CPython

Top 25 functions in the rebuilt `./python` on `main`, before merging the bytes and 1-byte Unicode decimal-output paths.

Sizes are function symbol sizes in bytes, obtained with `readelf --symbols --wide ./python` and sorted in descending order. They include inlined code but exclude separately stored data tables and out-of-line callees. The comments summarize the main reasons for the code size, based on the source and inline debug information.

| Rank | Function | Bytes | Why it is large |
|---:|---|---:|---|
| 1 | `_PyEval_EvalFrameDefault` | 61,487 | Main bytecode interpreter: many instructions and specialized variants, with inlined stack and reference-count operations. |
| 2 | `add_ast_annotations` | 49,036 | Generated code repeats type construction, dictionary insertion, cleanup, and error handling for every AST field. |
| 3 | `obj2ast_stmt` | 31,029 | Converts Python AST objects into internal statement nodes, with separate field validation and conversion for each statement type. |
| 4 | `long_to_decimal_string_internal` | 24,989 | Decimal digit output is duplicated for bytes and 1-, 2-, and 4-byte Unicode representations, with substantial SIMD expansion. |
| 5 | `obj2ast_expr` | 20,585 | The expression counterpart: many expression types, each with its own attribute checks and conversion logic. |
| 6 | `type_ready` | 20,027 | Many type-initialization helpers are inlined, especially the extensive slot-inheritance logic in `inherit_slots`. |
| 7 | `sre_ucs2_match` | 17,008 | Complete regex matching engine for 2-byte characters, including repetition, backtracking, and inlined character-set checks. |
| 8 | `sre_ucs4_match` | 16,341 | A separately compiled copy of the regex matching engine for 4-byte characters. |
| 9 | `sre_ucs1_match` | 16,288 | A separately compiled copy of the regex matching engine for 1-byte characters. |
| 10 | `_PyConfig_Read` | 15,804 | Command-line parsing, environment processing, encoding configuration, and other initialization helpers are extensively inlined. |
| 11 | `ast2obj_stmt.part.0` | 15,590 | Builds Python AST objects from internal statements, with repeated attribute assignments and inlined list conversions. |
| 12 | `_PyAST_Fini` | 13,914 | Generated `Py_CLEAR` operations individually expand reference-count checks and cleanup for many AST state fields. |
| 13 | `errno_exec` | 13,753 | Registers many errno constants individually; the `_add_errcode` helper is inlined at repeated call sites. |
| 14 | `_PyUnicode_ToNumeric` | 13,106 | A generated switch maps a large, sparse set of Unicode code points to numeric values. |
| 15 | `init_types` | 12,346 | Generated initialization for all AST classes and operator singletons, plus inlined identifier initialization. |
| 16 | `split` | 12,249 | Inlines whitespace and separator splitting for ASCII and 1-, 2-, and 4-byte Unicode representations. |
| 17 | `replace` | 12,168 | Handles several replacement strategies and character-width conversions, with inlined search and counting routines. |
| 18 | `r_object` | 12,135 | Main marshal decoder: handles many object types, nested containers, code objects, and shared-reference reconstruction. |
| 19 | `PyUnicode_Format` | 11,388 | Inlines `%` format parsing, argument conversion, padding, width, and precision handling. |
| 20 | `codegen_visit_expr_impl` | 11,387 | Compiles many expression types, with inlined helpers for calls, method-call optimization, subscripts, and string construction. |
| 21 | `_PyUnicode_InitGlobalObjects` | 11,154 | Contains generated static-string interning calls and inlined initialization of the global table and interpreter intern dictionary. |
| 22 | `simple_stmt_rule` | 9,764 | Generated parser alternatives inline several statement rules, particularly imports, plus lookahead, backtracking, and syntax-error handling. |
| 23 | `codegen_visit_stmt` | 9,732 | Dispatches statement compilation and inlines helpers for imports, assignments, returns, and pattern matching. |
| 24 | `compound_stmt_rule` | 9,705 | Inlines substantial parsing logic for `with`, `match`, `try`, and `for`, including invalid-syntax rules. |
| 25 | `_PyLexer_get_normal` | 9,681 | Combines token recognition, indentation handling, and identifier validation with inlined character-reading and buffer-refill logic. |

## Comparison with `fp-code-size2-src/python`

Measured on 2026-09-13, using the same `readelf --symbols --wide` method:

- Baseline: `/home/methane/work/python/cpython-gc/python` (ELF build ID `f3b5fd0fe4e43f3985925a78e4aac90c3eddeeca`).
- Comparison: `/tmp/cpython-dispatch-opt.AkBnol/fp-code-size2-src/python` (ELF build ID `7754438415a98369e464bdf48c29245c2ddae002`).

The rows retain the baseline's top 25 and ranking. All sizes and reductions are in bytes. Reduction is baseline minus comparison; a negative value means growth. The baseline sizes above were checked against the current binary and still match exactly.

| Rank | Function | Baseline | Comparison | Reduction | Reduction (%) |
|---:|---|---:|---:|---:|---:|
| 1 | `_PyEval_EvalFrameDefault` | 61,487 | 61,487 | 0 | 0.00% |
| 2 | `add_ast_annotations` | 49,036 | Inlined into `init_types` | See combined total below | — |
| 3 | `obj2ast_stmt` | 31,029 | 31,029 | 0 | 0.00% |
| 4 | `long_to_decimal_string_internal` | 24,989 | 24,989 | 0 | 0.00% |
| 5 | `obj2ast_expr` | 20,585 | 20,585 | 0 | 0.00% |
| 6 | `type_ready` | 20,027 | 20,027 | 0 | 0.00% |
| 7 | `sre_ucs2_match` | 17,008 | 17,008 | 0 | 0.00% |
| 8 | `sre_ucs4_match` | 16,341 | 16,341 | 0 | 0.00% |
| 9 | `sre_ucs1_match` | 16,288 | 16,288 | 0 | 0.00% |
| 10 | `_PyConfig_Read` | 15,804 | 15,804 | 0 | 0.00% |
| 11 | `ast2obj_stmt.part.0` | 15,590 | 15,590 | 0 | 0.00% |
| 12 | `_PyAST_Fini` | 13,914 | 135 | 13,779 | 99.03% |
| 13 | `errno_exec` | 13,753 | 13,753 | 0 | 0.00% |
| 14 | `_PyUnicode_ToNumeric` | 13,106 | 13,106 | 0 | 0.00% |
| 15 | `init_types` | 12,346 | 12,812 | -466 | -3.77% |
| 16 | `split` | 12,249 | 10,783 | 1,466 | 11.97% |
| 17 | `replace` | 12,168 | 11,034 | 1,134 | 9.32% |
| 18 | `r_object` | 12,135 | 12,135 | 0 | 0.00% |
| 19 | `PyUnicode_Format` | 11,388 | 11,388 | 0 | 0.00% |
| 20 | `codegen_visit_expr_impl` | 11,387 | 11,387 | 0 | 0.00% |
| 21 | `_PyUnicode_InitGlobalObjects` | 11,154 | 748 | 10,406 | 93.29% |
| 22 | `simple_stmt_rule` | 9,764 | 9,764 | 0 | 0.00% |
| 23 | `codegen_visit_stmt` | 9,732 | 9,732 | 0 | 0.00% |
| 24 | `compound_stmt_rule` | 9,705 | 9,705 | 0 | 0.00% |
| 25 | `_PyLexer_get_normal` | 9,681 | 7,572 | 2,109 | 21.78% |

`add_ast_annotations` no longer has a standalone function symbol. Source-annotated disassembly (`objdump -d -l --disassemble=init_types`) confirms that its code is inlined into `init_types`. Together, these two functions go from **61,382 to 12,812 bytes: 48,570 bytes smaller (79.13%)**. The 466-byte increase in `init_types` is already included in this combined reduction.

Counting that pair together, the original top 25 occupy **450,666 → 373,202 bytes**, a reduction of **77,464 bytes (17.19%)**. Eighteen of the 25 have unchanged symbol sizes. This subtotal excludes separately emitted helpers and data tables; it is not the total executable saving.

Whole-executable section sizes, measured with `size -A`, account for code outside these 25 functions:

| Sections | Baseline | Comparison | Reduction | Reduction (%) |
|---|---:|---:|---:|---:|
| `.text` | 3,484,850 | 3,398,690 | 86,160 | 2.47% |
| `.rodata` | 1,227,797 | 1,244,341 | -16,544 | -1.35% |
| `.text` + `.rodata` | 4,712,647 | 4,643,031 | 69,616 | 1.48% |

These are differences between the existing binaries. Their source checkouts have different HEADs (`58cdff72de8` and `851f12322be`, respectively), so the differences do not isolate the effect of a single optimization patch.
