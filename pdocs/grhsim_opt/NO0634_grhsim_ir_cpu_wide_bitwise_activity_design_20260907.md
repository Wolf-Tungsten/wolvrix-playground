# Wide bitwise true-change activation design

- Date: 2026-09-07
- Evidence: [NO0633](./NO0633_grhsim_ir_cpu_gate61_phase_profile_20260907.md).

## Gap and scope

The CPU emitter's pointer-based wide operations currently activate their mapped
fanout after every execution, even when the result is unchanged. This is
conservative for values, but falls short of the activity plan's true-change
write-site requirement and may propagate unnecessary work. The generated gate61
sources contain 13228 and, 9443 or, 749 xor, 4840 not, 1673 add, 56 sub,
3380 shl, 2207 lshr and 2 ashr pointer calls. These are static call counts,
not dynamic execution counts or proof of performance impact.

This stage handles and/or/xor/not only. Arithmetic and shifts remain explicit
follow-up gaps, not silently accepted substitutes for the full requirement.

## Implementation contract

Reference: the pointer overloads in wolvrix/lib/emit/grhsim_runtime.cpp,
grhsim_not_words and grhsim_and/or/xor_words, including zero extension and final
width truncation. The shared legacy runtime and its ABI stay unchanged.

For a result with mapped fanout, emit a CPU-only templated pointer helper that
computes one word, applies the final output mask, compares the old output word,
and writes it in place. Return a scalar changed flag, then invoke the existing
activation emitter only if true. No wide snapshots or return-value arrays.
For untracked/local outputs, retain the original legacy helpers and do not read
old output storage. Initial activation and zero-initialized boundary storage
remain unchanged. Exact input/output pointer aliasing is valid for the bitwise
helper; arbitrary partial overlaps are not promised by the generated layout.

No model, mapping, DPI, event, state publication or history policy changes.

## Verification gates

- Compare helper output against the existing legacy pointer overloads and the
  changed flag against an independent before/after comparison.
- Exercise unequal input lengths, scalar inputs, 65/129-bit tails, full words,
  large widths, unchanged output, dirty old padding, first/final-word changes,
  and exact lhs/rhs aliases under ASan/UBSan.
- Emit tracked and local fixtures, check guarded activation and original local
  helper paths, and run generated-model randomized/repeated-input checks.
- Run the existing full CPU/schedule suites and HDLBits before promotion.
- Generate an independent candidate, retain gate61, and measure serial ordinary
  binaries before claiming benefit. Final XS 50k and legacy+5% remain required.
