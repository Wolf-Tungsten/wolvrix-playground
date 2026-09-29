#!/usr/bin/env python3
"""Pack a RobTap text trace into the binary replay format that
``rob_bench --trace`` consumes.

Binary layout (all little-endian):
    header: char magic[8] = "RobTrc01", u64 cycles, u32 in_words, u32 out_words
    per cycle: u64 flags (bit0 = reset), u64 in[in_words], u64 out[out_words]

The input reads the tap manifest (port order of the text lines) and the bench
record layout (which port lands at which record word offset), so the two name
spaces are joined strictly by port name.  Record ports missing from the tap
dump are a hard error; tap ports not present in the record (gsim-only or
optimized-away ports) are dropped and reported.

Reads FIFOs as well as regular files, so the Verilator emu can stream the
text trace without it ever touching disk.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

MAGIC = b"RobTrc01"
WORD_MASK = (1 << 64) - 1


def log(message: str) -> None:
    sys.stderr.write(f"[pack-rob-trace] {message}\n")


def build_plan(record_ports: list[dict], manifest_ports: list[dict], what: str) -> tuple[list, list[str]]:
    """Join record ports against manifest ports by name.

    Returns (plan, dropped_names) where plan entries are
    (record_offset, width, words, manifest_token_index).
    """
    manifest_index = {p["name"]: i for i, p in enumerate(manifest_ports)}
    manifest_width = {p["name"]: p["width"] for p in manifest_ports}
    plan = []
    missing = []
    for port in record_ports:
        if port["offset"] is None:
            continue  # static config input: not carried in the record
        idx = manifest_index.get(port["name"])
        if idx is None:
            missing.append(port["name"])
            continue
        if manifest_width[port["name"]] != port["width"]:
            log(f"WARNING: width mismatch on {port['name']}: "
                f"record={port['width']} tap={manifest_width[port['name']]} (using record width)")
        plan.append((port["offset"], port["width"], port["words"], idx))
    if missing:
        raise RuntimeError(
            f"{len(missing)} {what} record ports missing from tap dump: "
            + ",".join(missing[:20])
            + (" ..." if len(missing) > 20 else ""))
    record_names = {p["name"] for p in record_ports}
    dropped = [p["name"] for p in manifest_ports if p["name"] not in record_names]
    return plan, dropped


def store_words(rec: list[int], base: int, value: int, width: int, words: int) -> None:
    value &= (1 << width) - 1
    for k in range(words):
        rec[base + k] = value & WORD_MASK
        value >>= 64


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="tap_ports.json from gen_rob_tap.py")
    parser.add_argument("--layout", required=True, help="layout.json from gen_rob_bench.py --layout-out")
    parser.add_argument("--in", dest="input", required=True, help="text trace path (may be a FIFO)")
    parser.add_argument("--out", required=True, help="output binary path")
    parser.add_argument("--limit", type=int, default=0, help="stop after N cycles (0 = all)")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    in_words = layout["in_words"]
    out_words = layout["out_words"]
    rec_len = 1 + in_words + out_words

    in_plan, dropped_in = build_plan(layout["inputs"], manifest["inputs"], "input")
    out_plan, dropped_out = build_plan(layout["outputs"], manifest["outputs"], "output")
    static_names = [p["name"] for p in layout["inputs"] if p["offset"] is None]
    static_idx = {p["name"]: i for i, p in enumerate(manifest["inputs"]) if p["name"] in static_names}
    log(f"record: in_words={in_words} out_words={out_words} stride_bytes={8 * rec_len}")
    log(f"tap ports dropped (not in record): inputs={len(dropped_in)} outputs={len(dropped_out)}")
    if dropped_in:
        log("  dropped inputs: " + ",".join(dropped_in[:10]) + (" ..." if len(dropped_in) > 10 else ""))
    if dropped_out:
        log("  dropped outputs: " + ",".join(dropped_out[:10]) + (" ..." if len(dropped_out) > 10 else ""))

    pack = struct.Struct(f"<{rec_len}Q").pack
    header = struct.Struct("<8sQII")

    cycles = 0
    reset_cycles = 0
    first_reset = None
    static_nonzero = 0
    start = time.monotonic()
    with open(args.input, "r", encoding="ascii", errors="strict", buffering=1 << 20) as stream, \
            open(args.out, "w+b", buffering=1 << 20) as out:
        out.write(header.pack(MAGIC, 0, in_words, out_words))
        while True:
            if args.limit and cycles >= args.limit:
                break
            line_i = stream.readline()
            if not line_i:
                break
            parts = line_i.split()
            if len(parts) < 3 or parts[0] != "I":
                raise RuntimeError(f"cycle {cycles}: expected 'I <cyc> <reset> ...' line, got: {line_i[:80]!r}")
            cyc = int(parts[1])
            if cyc != cycles:
                raise RuntimeError(f"cycle {cycles}: tap reported cycle {cyc}")
            reset = int(parts[2])
            tokens = parts[3:]
            if len(tokens) != len(manifest["inputs"]):
                raise RuntimeError(
                    f"cycle {cycles}: I line has {len(tokens)} tokens, "
                    f"manifest expects {len(manifest['inputs'])}")
            line_o = stream.readline()
            oparts = line_o.split()
            if len(oparts) < 2 or oparts[0] != "O" or int(oparts[1]) != cyc:
                raise RuntimeError(f"cycle {cycles}: missing/mismatched O line: {line_o[:80]!r}")
            otokens = oparts[2:]
            if len(otokens) != len(manifest["outputs"]):
                raise RuntimeError(
                    f"cycle {cycles}: O line has {len(otokens)} tokens, "
                    f"manifest expects {len(manifest['outputs'])}")

            rec = [0] * rec_len
            rec[0] = reset & 1
            for offset, width, words, idx in in_plan:
                store_words(rec, 1 + offset, int(tokens[idx], 16), width, words)
            for offset, width, words, idx in out_plan:
                store_words(rec, 1 + in_words + offset, int(otokens[idx], 16), width, words)
            for name, idx in static_idx.items():
                if int(tokens[idx], 16) != 0:
                    static_nonzero += 1
            out.write(pack(*rec))

            if first_reset is None:
                first_reset = reset & 1
            reset_cycles += reset & 1
            cycles += 1
            if cycles % 5000 == 0:
                elapsed = time.monotonic() - start
                log(f"progress: cycles={cycles} elapsed_s={elapsed:.1f} "
                    f"cycles_per_s={cycles / max(elapsed, 1e-9):.0f}")
        out.seek(0)
        out.write(header.pack(MAGIC, cycles, in_words, out_words))

    elapsed = time.monotonic() - start
    log(f"done: cycles={cycles} reset_cycles={reset_cycles} first_reset={first_reset} "
        f"static_nonzero={static_nonzero} bytes={24 + cycles * 8 * rec_len} elapsed_s={elapsed:.1f}")
    if cycles == 0:
        log("ERROR: no cycles parsed (emu died before producing trace?)")
        return 2
    if first_reset == 0:
        log("WARNING: trace does not start in reset; replay rounds will not rebuild state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
