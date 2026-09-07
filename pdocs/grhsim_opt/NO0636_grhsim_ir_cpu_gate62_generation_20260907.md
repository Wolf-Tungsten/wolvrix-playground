# Gate62 generation and source identity

- Date: 2026-09-07
- Implementation: [NO0635](./NO0635_grhsim_ir_cpu_wide_bitwise_activity_implementation_20260907.md).

Project-local make py_install exited 0. Independent generation, fresh-session
load and stable roundtrip through make xs_wolf_grhsim_ir exited 0 in 95817 ms.
The command follows [NO0620](./NO0620_grhsim_ir_cpu_gate60_generation_20260907.md)
with gate62 identifiers, the same flat GRH checkpoint, explicit empty
XS_WOLF_DEPS, target_batch_count=0 and project-local temporary storage.

cmp of ptmp/xs_ir_gate61.json and ptmp/xs_ir_gate62.json exited 0: full IR and
CPU mapping are byte-identical. Candidate versus its own
ptmp/xs_ir_gate62_roundtrip.json also compares equal.

Generated model: ptmp/xs_emit_make_gate62. Excluding baseline objects/archive
and its unused phase-probe header, exactly 272 files differ: the public header
(one added inline helper template) and 271 compute tasks. Driver, runtime,
initializers, all commit tasks and generated Makefile are unchanged.

| Operation | Tracked helper calls | Untracked legacy pointer calls |
| --- | ---: | ---: |
| and | 227 | 13001 |
| or | 352 | 9091 |
| xor | 80 | 669 |
| not | 193 | 4647 |
| Total | 852 | 27408 |

Each tracked call puts the existing activation statements under its changed
condition. These counts describe static coverage, not dynamic execution,
activation savings, or a performance result. The large local-call population
continues to avoid old-output reads and uses the original legacy helpers.

Logs: ptmp/grhsim_gate62_py_install.log,
ptmp/grhsim_gate62_generation.log, ptmp/grhsim_gate62_source_diff.log.

HDLBits is still running, with no XS O3 candidate build or runtime started yet.
Next use the existing xs_wolf_grhsim_ir_build_emu target with gate62 build/model
directories and the same O3/8-job settings, then serial ordinary gate61/gate62
comparisons after all other workloads finish. Retain the gate61 reference.
Gate62 10k/50k and the final legacy+5% gate remain unproven.
