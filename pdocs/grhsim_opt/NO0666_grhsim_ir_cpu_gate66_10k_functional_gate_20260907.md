# Gate66 10k functional gate with build overlap

- Date: 2026-09-07
- Candidate: NO0665 ordinary O3 binary.
- Status: 10k functionality passed; not a performance measurement.

Original run-only Makefile session 44439 exited 0. It completed 10000 host/model
cycles, 458 instructions, cycleCnt 9996, guest 10001, IPC 0.045818, sampled
commit PC 0x80001cdc and trap/limit PC 0x800027c6. NEMU was enabled and reported
no mismatch. Exactly ten ordered progress samples and all three terminal
records match gate63 after removing only host_ms, ANSI colors and UART prefixes.
The diff exited 0 with empty ptmp/grhsim_gate66_functional_10k_identity.log.

Run log: ptmp/grhsim_gate66_functional_10000_build_overlap.log. Recorded host
time is 233638 ms, but gate64 was compiling throughout; do not compare it to
the serial gate63 10k time or use it to claim improvement/regression. No other
simulation overlapped. The ordinary binary and emitter fingerprints remain
5e1c7db9a41bb09ae452b0427bd61b00ab71e5cb38bb3650ec080909ee2721d5 and
a37ad00df6259a12485c908394150e238025dcd48e73c2f68012654b8772156f.

Only gate64's original packing build (session 95253) remains running. It has
advanced to task22 without an error, but is not complete. Controlled serial
gate63/gate66 comparisons and packing-candidate runtime remain pending; do
not restart the existing build or treat an observation timeout as failure.
