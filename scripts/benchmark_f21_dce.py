"""Benchmark optional split-static-array and one independent dead-code-elim from post-elim."""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import threading
import time
from pathlib import Path

from benchmark_xs_firrtl_ingest import checked, json_identity, native_identity


def current_rss_kib() -> int:
    with Path("/proc/self/status").open("r", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError("VmRSS is unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--store-post-dce", action="store_true")
    parser.add_argument("--store-post-split", action="store_true")
    parser.add_argument("--split-static-array", action="store_true")
    parser.add_argument("--keep-declared-symbols", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--sample-rss", action="store_true")
    parser.add_argument("--validate-semantic", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.store_post_split and not args.split_static_array:
        parser.error("--store-post-split requires --split-static-array")
    if args.cpu is not None:
        if args.cpu not in os.sched_getaffinity(0):
            parser.error("--cpu must name an allowed CPU")
        os.sched_setaffinity(0, {args.cpu})

    import wolvrix

    args.output.mkdir(parents=True, exist_ok=True)
    input_identity = json_identity(args.input)
    records = []
    deterministic_after = None
    deterministic_phase = None
    for index in range(args.runs):
        with wolvrix.Session() as session:
            session.diagnostics_raise_min_level = "none"
            load_started = time.perf_counter()
            checked(session.read_json_file(str(args.input.resolve()), out_design="design.main"), "load post-elim")
            load_s = time.perf_counter() - load_started
            before = session.semantic_stats(design="design.main")
            rss_before = current_rss_kib()
            cpu_before = resource.getrusage(resource.RUSAGE_SELF)
            samples = []
            stop = threading.Event()

            def sample_rss() -> None:
                while not stop.wait(0.05):
                    samples.append(current_rss_kib())

            sampler = threading.Thread(target=sample_rss, daemon=True) if args.sample_rss else None
            if sampler is not None:
                sampler.start()
            split_wall_s = 0.0
            post_split = None
            if args.split_static_array:
                split_started = time.perf_counter()
                split_diagnostics = session.run_pass(
                    "split-static-array", design="design.main",
                    keep_declared_symbols=args.keep_declared_symbols)
                split_wall_s = time.perf_counter() - split_started
                checked(split_diagnostics, "split-static-array")
                post_split = session.semantic_stats(design="design.main")
                if args.store_post_split and index == 0:
                    destination = args.output / "post-split.json"
                    checked(session.store_json(design="design.main", output=str(destination)),
                            "store post-split")
            started = time.perf_counter()
            diagnostics = session.run_pass(
                "dead-code-elim", design="design.main", args=["-output-key=dce.f21"],
                keep_declared_symbols=args.keep_declared_symbols)
            outer_wall_s = time.perf_counter() - started
            if sampler is not None:
                stop.set()
                sampler.join()
            checked(diagnostics, "dead-code-elim")
            cpu_after = resource.getrusage(resource.RUSAGE_SELF)
            rss_after = current_rss_kib()
            after = session.semantic_stats(design="design.main")
            phase = json.loads(session.get("dce.f21.phase").text)
            semantic_phase = dict(phase["semantic"])
            validation = None
            if args.validate_semantic:
                validation = session.semantic_validate(design="design.main")
                if validation["module_path_duplicates"] or validation["register_symbol_mismatches"]:
                    raise RuntimeError(f"SemanticTree validation failed: {validation}")
            if deterministic_after is None:
                deterministic_after = after
                deterministic_phase = semantic_phase
                deterministic_split = post_split
            elif (after != deterministic_after or semantic_phase != deterministic_phase or
                  post_split != deterministic_split):
                raise RuntimeError("split/DCE results differ across runs")

            record = {
                "run": index + 1,
                "load_s": load_s,
                "split_wall_s": split_wall_s,
                "outer_wall_s": outer_wall_s,
                "combined_wall_s": split_wall_s + outer_wall_s,
                "post_split_semantic_stats": post_split,
                "cpu_s": (cpu_after.ru_utime - cpu_before.ru_utime +
                          cpu_after.ru_stime - cpu_before.ru_stime),
                "phase": phase,
                "before_semantic_stats": before,
                "after_semantic_stats": after,
                "rss_before_kib": rss_before,
                "rss_after_kib": rss_after,
                "rss_delta_kib": rss_after - rss_before,
                "rss_peak_kib": max([rss_before, rss_after, *samples]),
                "process_maxrss_kib": cpu_after.ru_maxrss,
                "semantic_validation": validation,
            }
            if args.store_post_dce and index == 0:
                store_started = time.perf_counter()
                destination = args.output / "post-dce.json"
                checked(session.store_json(design="design.main", output=str(destination)), "store post-dce")
                record["post_dce_store_s"] = time.perf_counter() - store_started
                record["post_dce_identity"] = json_identity(destination)
            records.append(record)
            print(json.dumps({"run": index + 1, "split_wall_s": split_wall_s,
                              "outer_wall_s": outer_wall_s,
                              "combined_wall_s": record["combined_wall_s"],
                              "phase": phase, "rss_delta_kib": record["rss_delta_kib"]},
                             sort_keys=True), flush=True)

    summary = {
        "schema": "wolvrix.f21.dce-benchmark.v1",
        "input": {"path": str(args.input.resolve()), **input_identity},
        "native_libraries": native_identity(),
        "split_static_array": args.split_static_array,
        "keep_declared_symbols": args.keep_declared_symbols,
        "runs": records,
        "median": {
            "split_wall_s": statistics.median(record["split_wall_s"] for record in records),
            "outer_wall_s": statistics.median(record["outer_wall_s"] for record in records),
            "combined_wall_s": statistics.median(record["combined_wall_s"] for record in records),
            "analysis_ms": statistics.median(record["phase"]["analysisMs"] for record in records),
            "removal_ms": statistics.median(record["phase"]["removalMs"] for record in records),
            "semantic_prune_ms": statistics.median(record["phase"]["semanticPruneMs"] for record in records),
            "rss_delta_kib": statistics.median(record["rss_delta_kib"] for record in records),
            "rss_peak_kib": statistics.median(record["rss_peak_kib"] for record in records),
        },
        "deterministic": True,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary["median"], sort_keys=True))


if __name__ == "__main__":
    main()
