# Xiangshan Boolean chain census (aggr-global-enhanced)

The baseline below is retained for comparison. Expanded maskedOr recovery
reduces the >=16-node chain count from 2,108 to 636 (Event 0, General 632,
Output 4); see [matching and validation](20261016-cpu-masked-or-matching.md).

Scanned all 1,269 `grhsim_SimTop_tu*.cpp` files (2,303,579,162 bytes) in
`build/xs/grhsim-ir-aggr-global-enhanced/model/` on 2026-10-16. The scan
recognized 1,663,323 explicit normalized one-bit binary assignments: 1,303,010
named `cpu_vN`/`cpu_f.vN` results and 360,313 terminal `cpu_value` expressions
in boundary writes.

## Counting rule

A chain is a maximal serial run of the same binary operator (`|`, `&`, `^`,
`||`, `&&`) on one-bit values. The preceding result must be a direct operand of
the next operation and have exactly one continuation. Fanout and two-chain
joins break the run. Length counts binary operations: the 48-term TLB
permission reduction is 47 OR operations. Chains of length 1 are excluded from
the distribution. `OR-of-AND` means every term in the serial OR run is the
result of a one-bit AND operation.

The scan covers generated C++ expressions in all six runtime phases. It does
not count wide-value operations or binary operators nested inside a single
generated expression. Initialization and dump functions are outside the six
runtime phases; neither contains a counted chain. The figures describe C++
source structure, not optimized native instruction counts or execution time.

This is not a Mux1H inventory. The subsequent
[Chisel/FIRRTL coverage audit](20261016-xiangshan-mux1h-coverage.md) counts
source call sites, elaborated selectors and ground fields separately, and
maps all 220 recovered IR regions to two TLB permission call sites.

## Results

| Phase | Chains >=2 | >=16 | >=32 | Maximum | OR-of-AND >=16 |
| --- | ---: | ---: | ---: | ---: | ---: |
| P_input | 0 | 0 | 0 | 0 | 0 |
| P_event | 514 | 21 | 20 | 47 | 21 |
| P_general | 122,164 | 2,083 | 1,569 | 128 | 788 |
| P_large_sink | 0 | 0 | 0 | 0 | 0 |
| P_publish | 0 | 0 | 0 | 0 | 0 |
| P_output | 17 | 4 | 2 | 67 | 0 |
| **Total** | **122,695** | **2,108** | **1,591** | **128** | **809** |

| Length (operations) | P_event | P_general | P_output | Total |
| --- | ---: | ---: | ---: | ---: |
| 2-3 | 407 | 101,612 | 11 | 102,030 |
| 4-7 | 84 | 13,977 | 2 | 14,063 |
| 8-15 | 2 | 4,492 | 0 | 4,494 |
| 16-31 | 1 | 514 | 2 | 517 |
| 32-63 | 20 | 982 | 0 | 1,002 |
| 64-127 | 0 | 533 | 2 | 535 |
| 128 | 0 | 54 | 0 | 54 |

By operator, P_event has 284 OR chains and 230 AND chains of length >=2;
P_general has 57,061 OR and 65,103 AND; P_output has 5 OR and 12 AND.

Of the 2,108 chains with at least 16 operations, 2,099 are OR chains and 9
are AND chains. There are no long XOR, `||`, or `&&` chains in the recognized
form. In P_general, 788 long OR chains are OR-of-AND; in P_event, all 21 long
chains are OR-of-AND. Exactly 164 OR-of-AND chains have 47 OR operations
(20 in P_event, 144 in P_general).

Representative endpoints:

- The discussed ITLB `perm.r` chain has 47 OR operations and 48 AND terms:
  [`cpu_f.v4561707`](../../build/xs/grhsim-ir-aggr-global-enhanced/model/grhsim_SimTop_tu17.cpp#L2073).
  P_event contains 20 such 47-operation chains in this TLB permission group.
- A 63-operation OR-of-AND chain in P_general ends at
  [`cpu_v1821801`](../../build/xs/grhsim-ir-aggr-global-enhanced/model/grhsim_SimTop_tu975.cpp#L9616).
- The longest P_general chains have 128 OR operations, for example a BPU PHR
  write-enable calculation at
  [`cpu_value`](../../build/xs/grhsim-ir-aggr-global-enhanced/model/grhsim_SimTop_tu851.cpp#L10337).
  This example repeats the same boundary operand in its tail; static length
  alone does not establish the cost after `-O3` simplification.
- The longest P_output chain has 67 OR operations at
  [`cpu_f.v4572550`](../../build/xs/grhsim-ir-aggr-global-enhanced/model/grhsim_SimTop_tu1188.cpp#L6678).
- The longest AND chain has 22 operations and is in P_general; it ends at
  [`cpu_value`](../../build/xs/grhsim-ir-aggr-global-enhanced/model/grhsim_SimTop_tu66.cpp#L1042).

The reusable scanner is `scripts/grhsim_bool_chain_stats.py`, invoked through
`make analyze_grhsim_bool_chains`. Full exact histograms and the 2,108
endpoints of length >=16 are in
[`ptmp/grhsim-bool-chains-aggr-global-enhanced.json`](../../ptmp/grhsim-bool-chains-aggr-global-enhanced.json)
and
[`ptmp/grhsim-bool-chains-aggr-global-enhanced-ge16.csv`](../../ptmp/grhsim-bool-chains-aggr-global-enhanced-ge16.csv).
`make test_grhsim_bool_chains` passed its four synthetic regression cases.

This is a static candidate list for optimization. Runtime prioritization needs
profiling of this exact build: some 128-operation source chains include repeated
terms that the C++ compiler may remove, while the OR-of-AND chains read many
independent state fields and are more likely to retain work.
