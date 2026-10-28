#!/usr/bin/env python3
"""Render an offline RepCut F/G timing report from completed paired runs.

This script never runs a simulator. It verifies the JSON summaries against the
raw timing records and renders phase-aligned averages, not an event trace.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
FORMAL = (ROOT / "build/repcut_grhsim_20260925/active_dispatch_20261003/"
          "dirty_input_bridge_20261012/formal")
VARIANTS = ("baseline", "candidate")
PART_FIELDS = {"input": "input_apply_avg_us", "eval": "eval_avg_us",
               "update": "update_push_avg_us"}
GLOBAL_FIELDS = {"input": "input_load_us", "eval": "eval_us", "update": "update_us"}


def read(path: Path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(a, b, label):
    require(math.isfinite(a) and math.isfinite(b) and
            math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8),
            f"{label}: {a!r} != {b!r}")


def stats(values):
    return {"mean": statistics.mean(values), "median": statistics.median(values),
            "min": min(values), "max": max(values)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def font_css(font: Path | None, text: str):
    if font is None:
        return "", None
    from fontTools import subset

    options = subset.Options()
    options.flavor = "woff"
    face = subset.load_font(str(font), options)
    required = {ord(c) for c in text if 0x3400 <= ord(c) <= 0x9FFF}
    require(required <= set(face.getBestCmap()), "font lacks required Chinese glyphs")
    worker = subset.Subsetter(options=options)
    worker.populate(text=text)
    worker.subset(face)
    stream = io.BytesIO()
    subset.save_font(face, stream, options)
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    css = ("@font-face{font-family:TimelineCJK;src:url(data:font/woff;base64," + encoded +
           ") format('woff');font-weight:400;font-style:normal;font-display:swap;}")
    return css, {"source_sha256": digest(font), "chinese_glyphs_verified": len(required),
                 "embedded_bytes": len(stream.getvalue())}


def build_data(source: Path, verification: Path, output: Path):
    manifest = read(source / "manifest.json")
    summary = read(source / "summary.json")
    runs = read(source / "runs.json")
    parts = read(source / "parts.json")
    verify = read(verification)
    require(all(x["status"] == "pass" for x in (manifest, summary, verify)),
            "source window did not pass")
    require(summary["input_identity_unchanged"] and manifest["input_identity_unchanged"],
            "source identities changed")
    count, n = manifest["pairs"], manifest["partitions"]
    require(len(runs) == count * 2 and len(parts) == count * 2 * n,
            "incomplete run/partition matrix")
    require(manifest["threads"] == n == 32 and manifest["cpus"] == "96-127" and
            manifest["host"].split(".")[0] == "node030", "unexpected runtime scope")
    expected = manifest["expected_signatures"][str(manifest["measured_cycles"])]
    raw_runs = {x["name"]: x for x in manifest["runs"] if x["pair"] > 0}
    require(len(raw_runs) == count * 2, "duplicate/missing manifest runs")
    runtime = None
    rows, sources = [], []
    for name in ("manifest.json", "summary.json", "runs.json", "parts.json", "pairs.json"):
        path = source / name
        sources.append({"file": name, "sha256": digest(path),
                        "href": os.path.relpath(path, output)})
    sources.append({"file": verification.name, "sha256": digest(verification),
                    "href": os.path.relpath(verification, output)})
    for pair in range(1, count + 1):
        order = ["baseline", "candidate"] if pair % 2 else ["candidate", "baseline"]
        for variant in VARIANTS:
            matches = [r for r in runs if r["pair"] == pair and r["variant"] == variant]
            require(len(matches) == 1, f"missing/duplicate pair {pair} {variant}")
            run = matches[0]
            original = raw_runs[run["name"]]
            require(run["functional"] == original["status"] == "pass" and
                    original["signature"] == expected and original["exit_code"] == 0,
                    f"failed source run: {run['name']}")
            require(run["slot"] == ("a" if order[0] == variant else "b"), "unexpected order")
            config = original["runtime_config"]
            runtime = runtime or config
            require(config == runtime, "runtime config drift")
            require(config["worker_to_part"] == list(range(n)) and
                    config["part_cpus"] == list(range(96, 128)) and
                    config["host_lane"] == 9 and config["host_cpu"] == 105 and
                    config["host_spin_infinite"] and config["worker_spin_infinite"],
                    "unexpected thread mapping/wait policy")
            raw_path = source / f"{run['name']}.timing.jsonl"
            raw = [json.loads(line) for line in raw_path.read_text().splitlines() if line.strip()]
            step = [r for r in raw if r["record_type"] == "step_timing_summary"]
            require(len(step) == 1 and step[0]["steps"] == expected["steps"], "wrong step count")
            close(step[0]["total_ms"] / 1000, run["step_s"], "step total")
            phases = {r["phase"]: r for r in raw if r["record_type"] == "step_timing_phase"}
            for key, field in (("input_load", "input_load_us"), ("part_eval", "eval_us"),
                               ("global_update", "update_us")):
                close(phases[key]["avg_us"], run[field], f"{run['name']} {key}")
            selected = sorted((p for p in parts if p["name"] == run["name"]),
                              key=lambda p: int(p["part_name"].split("_")[1]))
            raw_parts = {r["part_name"]: r for r in raw if r["record_type"] == "part_timing"}
            require(len(raw_parts) == len(selected) == n, "incomplete raw parts")
            normalized = []
            for i, part in enumerate(selected):
                require(part["part_name"] == f"part_{i}" and part["steps"] == expected["steps"],
                        "partition order/count mismatch")
                require(part["pair"] == pair and part["variant"] == variant, "partition metadata drift")
                for key, value in raw_parts[part["part_name"]].items():
                    require(part[key] == value, f"raw partition differs: {run['name']} {i} {key}")
                normalized.append({"part": i, "cpu": config["part_cpus"][i], "host": i == 9,
                                   **{key: part[field] for key, field in PART_FIELDS.items()}})
            rows.append({**run, "parts": normalized, "steps": expected["steps"],
                         "order": "AB" if pair % 2 else "BA", "step_us": step[0]["avg_us"]})
            sources.append({"file": raw_path.name, "sha256": digest(raw_path),
                            "href": os.path.relpath(raw_path, output)})

    metrics = {}
    for field, verified in verify["metrics"].items():
        if not all(field in r for r in rows):
            continue
        a = [r[field] for r in rows if r["variant"] == "baseline"]
        b = [r[field] for r in rows if r["variant"] == "candidate"]
        delta = [(y / x - 1) * 100 for x, y in zip(a, b)]
        for variant, values in (("baseline", a), ("candidate", b)):
            for aggregation in ("mean", "median"):
                close(stats(values)[aggregation], verified[f"{variant}_{aggregation}"],
                      f"verified {field} {variant} {aggregation}")
        close(statistics.median(delta), verified["paired_delta_median_pct"], "paired delta")
        metrics[field] = {"baseline": stats(a), "candidate": stats(b),
                          "mean_ratio_pct": (statistics.mean(b) / statistics.mean(a) - 1) * 100,
                          "paired_median_pct": statistics.median(delta),
                          "wins": sum(y < x for x, y in zip(a, b)), "pair_delta_pct": delta}
    part_summary = []
    for i in range(n):
        for key in PART_FIELDS:
            a = [r["parts"][i][key] for r in rows if r["variant"] == "baseline"]
            b = [r["parts"][i][key] for r in rows if r["variant"] == "candidate"]
            if key == "eval":
                for variant, values in (("baseline", a), ("candidate", b)):
                    close(statistics.mean(values), verify["parts"][str(i)][f"{variant}_mean"],
                          f"verified part {i} {variant}")
            part_summary.append({"part": i, "cpu": 96 + i, "host": i == 9, "metric": key,
                                 "baseline_mean_us": statistics.mean(a),
                                 "candidate_mean_us": statistics.mean(b),
                                 "baseline_median_us": statistics.median(a),
                                 "candidate_median_us": statistics.median(b),
                                 "mean_ratio_pct": (statistics.mean(b) / statistics.mean(a) - 1) * 100,
                                 "paired_median_pct": statistics.median([(y / x - 1) * 100
                                                                        for x, y in zip(a, b)])})
    # The three-stage view requires no nonempty early-eval/update phases.
    wrappers = {}
    for variant, binary in manifest["binaries"].items():
        package = Path(binary["path"]).parent / "package"
        common = list(package.glob("*_common.cpp"))
        require(len(common) == 1, f"missing wrapper audit source for {variant}")
        text = common[0].read_text()
        require("run_phase_workers_(load_step_fns_)" in text, "input loading is not parallel")
        for phase in ("early_eval", "early_update"):
            require(f"{phase}_step_fns_.reserve(0);" in text, "early phases need a separate layout")
        wrappers[variant] = {"path": str(common[0]), "sha256": digest(common[0]),
                             "parallel_input": True, "early_phases_empty": True}
    return {"title": "GrhSIM F → G · 最新多线程平均 step 时空图", "date": "2026-10-12",
            "pairs": count, "cycles": manifest["measured_cycles"], "steps": expected["steps"],
            "runtime": runtime, "rows": rows, "metrics": metrics, "part_summary": part_summary,
            "binaries": manifest["binaries"], "sources": sources,
            "config": {k: manifest[k] for k in ("host", "cpus", "numa_node", "aslr", "threads", "partitions")},
            "codepage": summary["codepage"], "wrappers": wrappers,
            "labels": {"baseline": "F · 同期基线", "candidate": "G · 最新保留版"},
            "descriptions": {"baseline": "累计优化线 F；未启用本轮输入变化跟踪",
                             "candidate": "F + 通信变化标记复用 + 输入旧快照精简"}}, part_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=FORMAL / "candidate/ordinary_c100000_8pairs")
    parser.add_argument("--verification", type=Path, default=FORMAL / "verification_8pairs.json")
    parser.add_argument("--output", type=Path, default=FORMAL / "timeline_8pairs")
    parser.add_argument("--font", type=Path, help="optional full TTF/OTF to subset and embed; needs fontTools")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data, parts = build_data(args.source.resolve(), args.verification.resolve(), args.output.resolve())
    template = Path(__file__).with_suffix(".html").read_text()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    font, font_audit = font_css(args.font, template + payload)
    html = template.replace("/*__FONT__*/", font).replace("/*__DATA__*/null", payload.replace("</", "<\\/"))
    (args.output / "grhsim_f_g_timeline.html").write_text(html)
    (args.output / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    with (args.output / "part_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(parts[0]))
        writer.writeheader()
        writer.writerows(parts)
    rows = [{k: v for k, v in r.items() if k != "parts"} for r in data["rows"]]
    with (args.output / "run_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    audit = {"status": "pass", "runs": len(rows), "partition_records": len(rows) * 32,
             "raw_jsonl_verified": True, "verification_statistics_matched": True,
             "parallel_input_and_empty_early_phases_verified": True,
             "font": font_audit,
             "sources": data["sources"], "generator_sha256": digest(Path(__file__)),
             "template_sha256": digest(Path(__file__).with_suffix(".html")),
             "html_sha256": digest(args.output / "grhsim_f_g_timeline.html")}
    (args.output / "validation.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({"status": "pass", "html": str(args.output / "grhsim_f_g_timeline.html"),
                      "runs": len(rows), "walltime": data["metrics"]["elapsed_s"]}, indent=2))


if __name__ == "__main__":
    main()
