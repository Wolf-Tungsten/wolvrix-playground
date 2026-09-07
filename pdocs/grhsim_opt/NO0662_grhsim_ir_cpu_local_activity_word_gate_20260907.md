# Local activity word CPU gate

- Date: 2026-09-07
- Implementation/design: NO0661.
- Status: complete CPU suite passed; XS runtime benefit not measured.

Existing make test_grhsim_cpu_emit exited 0 in 72.28 seconds. Four new activity
variants (inline/helpers crossed with tracked/local outputs) each passed
4480 helper cases, 8192 generated model evaluations and four resets with
ASan/UBSan. Structural assertions verify the local-byte load, shared helper
reference, same-word forward activation and tracked/local helper selection.
The complete existing suite includes multiclock, gated/derived clocks, DPI
results/event histories, priority writes, wide state and repeated initialization.
The new local identifier is included in port collision rejection tests.

Log: ptmp/grhsim_local_activity_cpu_tests.log. Root and nested git diff --check
both pass. The backend documentation now defines consumption, forward versus
backward activation, helper lifetime and writeback with a bit2 -> bit1/bit5
example. No mapping, scheduling order, state publication or DPI policy change.

Next candidate gate66 combines the verified NO0659 helper change with NO0661
local-word/mask-coalescing structure. Gate65 remains the helper-only generated
artifact, without a built XS binary. Any future gate63/gate66 timing measures
the combined changes, not their separate dynamic contributions. Gate64 remains
the original packing-only build and has not completed or been restarted.
