#!/usr/bin/env python3
"""Validate complete traces and render a self-contained, cycle-selectable chart.

No simulator is run by this script. Blocks are gzip compressed independently,
so the browser only decompresses the selected cycles, not the entire trace.
"""
from __future__ import annotations

import argparse
from array import array
import base64
import gzip
import json
from pathlib import Path
import struct
import sys
import shutil

from repcut_cycle_trace import DEFAULT_OUTPUT
from repcut_grhsim_timeline import digest, font_css, require

BLOCK_CYCLES = 256


def read_trace(path, timing):
    raw = path.read_bytes()
    require(raw[:8] == b"GRHCYC01", f"bad magic: {path}")
    version, steps, parts, fields = struct.unpack_from("<4I", raw, 8)
    require((version, parts, fields) == (1, 32, 3), "unsupported trace schema")
    require(len(raw) == 24 + steps * (4 + parts * fields) * 4, "truncated/extra trace bytes")
    values = array("I")
    values.frombytes(raw[24:])
    if sys.byteorder != "little":
        values.byteswap()
    require(0xffffffff not in values, "missing/overflow trace record")
    global_rows = values[:steps * 4]
    lanes = [values[steps * (4 + p * 3):steps * (4 + (p + 1) * 3)] for p in range(parts)]
    flags = global_rows[0::4]
    require(steps % 2 == 0, "incomplete final cycle")
    require(all((flags[s] & 1, flags[s + 1] & 1) == (1, 0) and
                flags[s] >> 1 == flags[s + 1] >> 1 for s in range(0, steps, 2)),
            "cycles must be adjacent rising/falling steps with matching reset")
    first = next((s for s, flag in enumerate(flags) if not flag & 2), None)
    require(first is not None and first % 2 == 0, "missing normal-cycle boundary")
    require(all(flag & 2 for flag in flags[:first]) and
            all(not flag & 2 for flag in flags[first:]), "non-prefix reset cycles")
    records = [json.loads(line) for line in timing.read_text().splitlines()]
    totals = [r for r in records if r["record_type"] == "step_timing_summary"]
    require(len(totals) == 1 and totals[0]["steps"] == steps, "aggregate step mismatch")
    comparisons = []

    def check(ns, ms, name):
        # Existing JSON reports milliseconds to three decimals, i.e. +/-500 ns.
        error = abs(ns - ms * 1_000_000)
        require(error <= 501, f"trace/aggregate mismatch {name}: {error} ns")
        comparisons.append(error)

    global_fields = ("input_load", "part_eval", "global_update")
    for i, phase in enumerate(global_fields):
        rows = [r for r in records if r["record_type"] == "step_timing_phase" and r["phase"] == phase]
        require(len(rows) == 1, f"missing global {phase}")
        check(sum(global_rows[i + 1::4]), rows[0]["total_ms"], phase)
    part_rows = {int(r["part_name"].split("_")[1]): r for r in records if r["record_type"] == "part_timing"}
    require(sorted(part_rows) == list(range(parts)), "incomplete aggregate partitions")
    for p, lane in enumerate(lanes):
        for i, field in enumerate(("input_apply_total_ms", "eval_total_ms", "update_push_total_ms")):
            check(sum(lane[i::3]), part_rows[p][field], f"p{p}/{field}")
    # A callback cannot outlive the surrounding completed phase. This catches
    # mis-indexed step/lane records in addition to the aggregate reconciliation.
    for p, lane in enumerate(lanes):
        for phase in range(3):
            require(all(local <= global_ns for local, global_ns in
                        zip(lane[phase::3], global_rows[phase + 1::4])),
                    f"callback outside phase: p{p}/{phase}")
    audit = {"file": str(path), "sha256": digest(path), "steps": steps,
             "reset_cycles": first // 2, "cycles": (steps - first) // 2,
             "callback_records": steps * parts * fields,
             "aggregate_checks": len(comparisons), "max_rounding_error_ns": max(comparisons),
             "all_callbacks_within_phase": True}
    return global_rows, lanes, first, audit


def build(source, output, font):
    manifest = json.loads((source / "manifest.json").read_text())
    codepage = json.loads((source / "codepage_verification.json").read_text())
    require(manifest["status"] == codepage["status"] == "pass" and manifest["input_identity_unchanged"],
            "unverified source window")
    require(manifest["host"].split(".")[0] == "node030" and manifest["cpus"] == "96-127" and
            manifest["threads"] == manifest["partitions"] == 32, "unexpected runtime scope")
    measured = [r for r in manifest["runs"] if r["pair"]]
    require([(r["pair"], r["variant"]) for r in measured] ==
            [(1, "baseline"), (1, "candidate"), (2, "candidate"), (2, "baseline")], "not fresh AB/BA")
    traces, audits, runs = [], [], []
    output.mkdir(parents=True, exist_ok=True)
    for run in sorted(measured, key=lambda r: (r["pair"], r["variant"])):
        require(run["status"] == "pass" and run["signature"] ==
                manifest["expected_signatures"][str(run["cycles"])], "functional mismatch")
        name = run["name"]
        global_rows, lanes, first, audit = read_trace(source / f"{name}.trace.bin",
                                                    source / f"{name}.timing.jsonl")
        require((audit["steps"], audit["cycles"], audit["reset_cycles"]) == (200102, 100001, 50),
                "unexpected C100000 cycle mapping")
        traces.append((global_rows, lanes, first))
        audits.append(audit)
        runs.append({"name": name, "variant": run["variant"], "pair": run["pair"],
                     "order": "F → G" if run["pair"] == 1 else "G → F",
                     "signature": run["signature"], "binary_sha256": manifest["binaries"][run["variant"]]["sha256"]})
    config = measured[0]["runtime_config"]
    require(all(r["runtime_config"] == config for r in measured), "runtime configuration drift")
    data = {"schema": 1, "cycles": 100001, "reset_cycles": 50, "parts": 32,
            "block_cycles": BLOCK_CYCLES, "words_per_step": 100, "runs": runs,
            "codec": "gzip-u32-byteplanes-v1",
            "runtime": config, "source": str(source), "trace_unit": "ns", "codepage": codepage["mode"],
            "labels": {"baseline": "F · 基线", "candidate": "G · 最新候选"},
            "note": "逐周期诊断采集；不是全程平均值，不用于宣称 ordinary walltime 收益。"}
    template = Path(__file__).with_suffix(".html").read_text()
    page_note = ("完整代码 THP" if codepage["mode"] == "thp" else "本批代码为 4 KiB 小页（非 THP）")
    template = template.replace("__CODEPAGE__", page_note)
    template = template.replace("__PAGE_NOTE__", "" if codepage["mode"] == "thp" else
        "<p><b>本批诊断数据使用 4 KiB 代码页：</b>当前服务器大页分配未能完成，因此 F/G 都用相同小页配置采集。"
        "与上一版采用 THP 的平均时空图不属于同一计时口径，不能直接比较绝对耗时；仓库默认大页配置未改动。</p>")
    if font is not None and (font.parent / "OFL.txt").is_file():
        license_text = (font.parent / "OFL.txt").read_text()
        template = template.replace("</head>", "<!-- Embedded Noto Sans CJK font license:\n" +
                                    license_text.replace("--", "—") + "\n-->\n</head>")
        shutil.copy2(font.parent / "OFL.txt", output / "OFL.txt")
    css, font_info = font_css(font, template + json.dumps(data, ensure_ascii=False))
    template = template.replace("/*__FONT__*/", css).replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    before, after = template.split("<!--__BLOCKS__-->")
    total_compressed, block_sizes = 0, []
    with (output / "grhsim_cycle_histogram.html").open("w") as stream:
        stream.write(before)
        for block, cycle_offset in enumerate(range(0, data["cycles"], BLOCK_CYCLES)):
            n = min(BLOCK_CYCLES, data["cycles"] - cycle_offset)
            packet = array("I")
            for global_rows, lanes, first in traces:
                start, end = first + cycle_offset * 2, first + (cycle_offset + n) * 2
                packet.extend(global_rows[start * 4:end * 4])
                for lane in lanes:
                    packet.extend(lane[start * 3:end * 3])
            if sys.byteorder != "little":
                packet.byteswap()
            # Lossless byte-plane shuffling improves compression of uint32 ns
            # values (high bytes are mostly zero). No timing quantization.
            raw = packet.tobytes()
            shuffled = b"".join(raw[i::4] for i in range(4))
            compressed = gzip.compress(shuffled, compresslevel=6, mtime=0)
            total_compressed += len(compressed)
            block_sizes.append(len(compressed))
            stream.write(f'<script type="application/octet-stream" id="block-{block}">')
            stream.write(base64.b64encode(compressed).decode())
            stream.write("</script>\n")
        stream.write(after)
    spot_checks = []
    for cycle in (1, 2, 256, 257, 50001, 100000, 100001):
        for run, (global_rows, lanes, first) in zip(runs, traces):
            for edge, offsets in (("rise", (0,)), ("fall", (1,)), ("both", (0, 1))):
                steps = [first + (cycle - 1) * 2 + i for i in offsets]
                spot_checks.append({"cycle": cycle, "pair": run["pair"], "variant": run["variant"],
                    "edge": edge, "steps": [s + 1 for s in steps],
                    "globals": [sum(global_rows[s * 4 + 1 + phase] for s in steps) for phase in range(3)],
                    "parts": [[sum(lane[s * 3 + phase] for s in steps) for phase in range(3)] for lane in lanes]})
    (output / "spot_checks.json").write_text(json.dumps(spot_checks) + "\n")
    validation = {"status": "pass", "diagnostic_only": True, "data": data,
                  "trace_checks": audits, "font": font_info, "blocks": len(block_sizes),
                  "compressed_bytes": total_compressed, "max_block_bytes": max(block_sizes),
                  "html_sha256": digest(output / "grhsim_cycle_histogram.html")}
    (output / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": "pass", "cycles": data["cycles"], "runs": len(runs),
                      "compressed_mb": total_compressed / 1e6, "output": str(output)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_OUTPUT / "runs")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "viewer")
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    build(args.source.resolve(), args.output.resolve(), args.font)
