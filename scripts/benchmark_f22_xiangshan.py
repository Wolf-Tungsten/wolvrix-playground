"""Benchmark the standalone F22 ExprOpt and UsedBits passes on XiangShan.

The input is an ordinary GRH checkpoint produced after the caller's first
explicit dead-code-elim pass.  This benchmark deliberately does not run DCE or
any simplify pass: it measures the two GSIM stages in their user-visible order
and checks that they do not remove operation/value rows themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import statistics
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_CONVERSION = False
STORE_AFTER_F22: Path | None = None
_METRIC_RE = {
    "operations": re.compile(r"operations=(\d+)->(\d+)"),
    "values": re.compile(r"values=(\d+)->(\d+)"),
    "width_sum": re.compile(r"width-sum=(\d+)->(\d+)"),
    "mux_rewrites": re.compile(r"mux-rewrites=(\d+)"),
    "narrowed": re.compile(r"narrowed=(\d+)"),
}


def checked(diagnostics: list[dict], action: str) -> list[dict]:
    errors = [entry for entry in diagnostics if str(entry.get("kind", "")).lower() == "error"]
    if errors:
        raise RuntimeError(f"{action}: {errors}")
    return diagnostics


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def rss_kib() -> int:
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def diagnostics_metrics(diagnostics: list[dict]) -> dict:
    result: dict[str, int] = {}
    for entry in diagnostics:
        message = str(entry.get("message", ""))
        for key, pattern in _METRIC_RE.items():
            match = pattern.search(message)
            if match:
                if len(match.groups()) == 1:
                    result[key] = int(match.group(1))
                else:
                    result[f"{key}_before"] = int(match.group(1))
                    result[f"{key}_after"] = int(match.group(2))
    return result


def run_once(wolvrix, source: Path) -> dict:
    with wolvrix.Session() as session:
        session.log_level = "info"
        session.diagnostics_raise_min_level = "none"
        load_started = time.perf_counter()
        checked(session.read_json_file(str(source), out_design="design.main"), "load post-DCE checkpoint")
        load_s = time.perf_counter() - load_started
        before = session.semantic_stats(design="design.main")
        rss_before = rss_kib()
        cpu_before = resource.getrusage(resource.RUSAGE_SELF)
        stages = []
        pass_names = ("expr-opt", "used-bits")
        for name in pass_names:
            stage_cpu_before = resource.getrusage(resource.RUSAGE_SELF)
            started = time.perf_counter()
            diagnostics = checked(session.run_pass(name, design="design.main",
                                                    keep_declared_symbols=False), name)
            elapsed = time.perf_counter() - started
            after = session.semantic_stats(design="design.main")
            metrics = diagnostics_metrics(diagnostics)
            for key in ("operations", "values"):
                before_key, after_key = f"{key}_before", f"{key}_after"
                if before_key in metrics and after_key in metrics and metrics[after_key] < metrics[before_key]:
                    raise RuntimeError(f"{name} removed {key} rows; DCE is outside F22: {metrics}")
            stages.append({
                "pass": name,
                "wall_s": elapsed,
                "cpu_s": (resource.getrusage(resource.RUSAGE_SELF).ru_utime - stage_cpu_before.ru_utime +
                          resource.getrusage(resource.RUSAGE_SELF).ru_stime - stage_cpu_before.ru_stime),
                "rss_kib": rss_kib(),
                "metrics": metrics,
                "semantic_stats": after,
            })
        conversion = None
        if STORE_AFTER_F22 is not None:
            checked(session.store_json(design="design.main", output=str(STORE_AFTER_F22)),
                    "store post-F22 checkpoint")
        if RUN_CONVERSION:
            stage_cpu_before = resource.getrusage(resource.RUSAGE_SELF)
            started = time.perf_counter()
            diagnostics = checked(session.run_pass(
                "grh-to-grhsim", design="design.main", logic_domain="2state"),
                "grh-to-grhsim")
            stage_cpu_after = resource.getrusage(resource.RUSAGE_SELF)
            conversion = {
                "wall_s": time.perf_counter() - started,
                "cpu_s": (stage_cpu_after.ru_utime - stage_cpu_before.ru_utime +
                          stage_cpu_after.ru_stime - stage_cpu_before.ru_stime),
                "semantic_stats": session.semantic_stats(design="design.main"),
                "diagnostics": diagnostics,
            }
        cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        final = session.semantic_stats(design="design.main")
        validation = session.semantic_validate(design="design.main")
        if validation["module_path_duplicates"] or validation["register_symbol_mismatches"]:
            raise RuntimeError(f"F22 SemanticTree validation failed: {validation}")
        return {
            "load_s": load_s,
            "before_semantic_stats": before,
            "stages": stages,
            "after_semantic_stats": final,
            "semantic_validation": validation,
            "rss_before_kib": rss_before,
            "rss_after_kib": rss_kib(),
            "rss_delta_kib": rss_kib() - rss_before,
            "process_maxrss_kib": cpu_after.ru_maxrss,
            "cpu_s": cpu_after.ru_utime - cpu_before.ru_utime + cpu_after.ru_stime - cpu_before.ru_stime,
            "conversion": conversion,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="ordinary GRH JSON after the caller's explicit first DCE")
    parser.add_argument("--output", required=True, type=Path,
                        help="report directory; keep it under repository ptmp/")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--convert", action="store_true",
                        help="run grh-to-grhsim after F22 and record conversion timing")
    parser.add_argument("--store-after-f22", type=Path,
                        help="store ordinary GRH after F22 before optional conversion")
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if not source.is_file():
        parser.error(f"input not found: {source}")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    if args.cpu is not None:
        if args.cpu not in os.sched_getaffinity(0):
            parser.error("--cpu must name an allowed CPU")
        os.sched_setaffinity(0, {args.cpu})

    import wolvrix

    global RUN_CONVERSION
    RUN_CONVERSION = args.convert
    global STORE_AFTER_F22
    STORE_AFTER_F22 = args.store_after_f22.resolve() if args.store_after_f22 else None
    if STORE_AFTER_F22 is not None and not STORE_AFTER_F22.is_relative_to(ROOT / "ptmp"):
        parser.error("--store-after-f22 must be under repository ptmp/")
    if STORE_AFTER_F22 is not None:
        STORE_AFTER_F22.parent.mkdir(parents=True, exist_ok=True)

    output.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(args.runs):
        record = run_once(wolvrix, source)
        record["run"] = index + 1
        records.append(record)
        print(json.dumps({"run": index + 1,
                          "expr_opt_s": record["stages"][0]["wall_s"],
                          "used_bits_s": record["stages"][1]["wall_s"],
                          "expr_opt": record["stages"][0]["metrics"],
                          "used_bits": record["stages"][1]["metrics"],
                          "rss_delta_kib": record["rss_delta_kib"],
                          "conversion_s": (record["conversion"] or {}).get("wall_s")}, sort_keys=True), flush=True)

    def median(path):
        return statistics.median(path)

    expr = [record["stages"][0] for record in records]
    used = [record["stages"][1] for record in records]
    conversions = [record["conversion"] for record in records if record["conversion"] is not None]
    summary = {
        "schema": "wolvrix.f22.xiangshan-benchmark.v1",
        "input": identity(source),
        "runs": records,
        "median": {
            "expr_opt_s": median([row["wall_s"] for row in expr]),
            "used_bits_s": median([row["wall_s"] for row in used]),
            "f22_s": median([expr[i]["wall_s"] + used[i]["wall_s"] for i in range(len(records))]),
            "expr_opt_metrics": expr[0]["metrics"],
            "used_bits_metrics": used[0]["metrics"],
            "rss_delta_kib": median([record["rss_delta_kib"] for record in records]),
            "conversion_s": median([row["wall_s"] for row in conversions]) if conversions else None,
            "conversion_semantic_stats": conversions[0]["semantic_stats"] if conversions else None,
        },
        "dce_boundary": "external input checkpoint; neither F22 pass runs DCE",
        "simplify": "not run",
        "conversion": "grh-to-grhsim after F22" if args.convert else "not run",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary["median"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
