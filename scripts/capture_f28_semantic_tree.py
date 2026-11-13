"""Record the ordinary F28 ingest/xmr/flatten pipeline and GSIM Init inventory.

This driver only invokes native producers and exports their current objects.
It does not construct Nodes or infer membership from an offline checkpoint.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import time

from benchmark_xs_firrtl_ingest import checked, json_identity, native_identity, request_from_manifest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gsim-binary", type=Path, required=True)
    parser.add_argument("--grh-only", action="store_true")
    parser.add_argument("--gsim-only", action="store_true")
    parser.add_argument("--store-ingest", action="store_true")
    parser.add_argument("--assign-trees", action="store_true")
    parser.add_argument("--timing-only", action="store_true",
                        help="time only native ingest/xmr/flatten calls, without inspect or JSON export")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    if args.grh_only and args.gsim_only:
        parser.error("select at most one engine-only option")
    if args.timing_only and (not args.grh_only or args.store_ingest or args.assign_trees):
        parser.error("--timing-only requires --grh-only without --store-ingest or --assign-trees")
    output.mkdir(parents=True, exist_ok=True)
    source = args.firrtl.resolve()
    request = request_from_manifest(args.manifest.resolve()) if args.manifest else {
        "sources": [{"path": str(source), "language": "firrtl", "unit": "f28"}],
        "firrtl_options": {"invalid_policy": "zero", "node_annotations": True},
    }
    firrtl = [Path(row["path"]).resolve() for row in request["sources"] if row["language"] == "firrtl"]
    if firrtl != [source]:
        parser.error("manifest must contain exactly the --firrtl input")
    report = {"schema": "wolvrix.f28.capture.v1", "complete": False,
              "stages": [], "input": {"path": str(source), **json_identity(source)},
              "sources": [{**row, **json_identity(Path(row["path"]))} for row in request["sources"]],
              "request": request, "grh_stage": "post-hier-flatten", "gsim_stage": "Init",
              "emit_source_locations": True,
              "membership_producer": "native SemanticTree; no offline reconstruction"}
    summary = output / ("capture-summary-gsim.json" if args.gsim_only else "capture-summary-grh.json")
    if args.timing_only:
        summary = output / "timing-summary-grh.json"
        report.update({"schema": "wolvrix.f28.timing.v1", "gsim_stage": None,
                       "emit_source_locations": False,
                       "measurement_scope": "native read_sources/run_pass calls only",
                       "extra_semantic_validate": False, "extra_semantic_stats": False,
                       "json_export": False, "native_pass_checks": "normal production behavior"})

    def persist():
        report["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary.write_text(json.dumps(report, indent=2) + "\n")

    def stage(name, action):
        print(f"[F28] start {name}", flush=True)
        before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        report["active_stage"] = name
        persist()
        try:
            result = action()
        except Exception as error:
            report["stages"].append({"name": name, "wall_s": time.perf_counter() - started,
                                     "failed": True, "error": str(error)})
            persist()
            raise
        after = resource.getrusage(resource.RUSAGE_SELF)
        row = {"name": name, "wall_s": time.perf_counter() - started,
               "cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime}
        if result is not None:
            row["result"] = result
        report["stages"].append(row)
        report.pop("active_stage", None)
        persist()
        print(f"[F28] done {name}: {row['wall_s']:.3f}s", flush=True)
        return result

    persist()
    if not args.gsim_only:
        import wolvrix
        report["grh_producer_libraries"] = native_identity()
        with wolvrix.Session() as session:
            session.log_level = "info"
            session.diagnostics_raise_min_level = "none"

            if args.timing_only:
                for name in ("ingest-firrtl", "xmr-resolve", "hier-flatten"):
                    print(f"[F28] start {name} (native call only)", flush=True)
                    report["active_stage"] = name
                    persist()
                    before = resource.getrusage(resource.RUSAGE_SELF)
                    started = time.perf_counter()
                    try:
                        if name == "ingest-firrtl":
                            diagnostics = session.read_sources(**request, out_design="design.main", pipeline="ingest")
                        else:
                            diagnostics = session.run_pass(name, design="design.main", keep_declared_symbols=True)
                    except Exception as error:
                        elapsed = time.perf_counter() - started
                        report["stages"].append({"name": name, "wall_s": elapsed,
                                                 "failed": True, "error": str(error)})
                        persist()
                        raise
                    elapsed = time.perf_counter() - started
                    after = resource.getrusage(resource.RUSAGE_SELF)
                    row = {"name": name, "wall_s": elapsed,
                           "cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                           "maxrss_kib": after.ru_maxrss, "diagnostic_count": len(diagnostics)}
                    report["stages"].append(row)
                    try:
                        checked(diagnostics, name)
                    except Exception as error:
                        row.update({"failed": True, "error": str(error)})
                        persist()
                        raise
                    report.pop("active_stage", None)
                    persist()
                    print(f"[F28] done {name}: {elapsed:.3f}s (native call only)", flush=True)
                report["pipeline_stage_sum_s"] = sum(row["wall_s"] for row in report["stages"])
                report["complete"] = True
                persist()
                return

            def inspect():
                validation = session.semantic_validate(design="design.main")
                if not validation["valid"]:
                    raise RuntimeError(json.dumps(validation))
                return {"stats": session.semantic_stats(design="design.main"), "validation": validation}

            def ingest():
                checked(session.read_sources(**request, out_design="design.main", pipeline="ingest"), "ingest")
                return inspect()

            def store(name):
                path = output / (name + ".json")
                checked(session.store_json(design="design.main", output=str(path), mode="pretty-compact",
                                           emit_source_locations=True), name)
                return {"path": str(path), **json_identity(path)}

            stage("ingest-firrtl", ingest)
            if args.store_ingest:
                stage("store-ingest", lambda: store("ingest"))
            for name in ("xmr-resolve", "hier-flatten"):
                def transform(name=name):
                    checked(session.run_pass(name, design="design.main", keep_declared_symbols=True), name)
                    return inspect()
                stage(name, transform)
            stats = session.semantic_stats(design="design.main")
            if stats["path_count"]:
                raise RuntimeError("hier-flatten retained internal semantic Paths")
            report["flatten"] = inspect()
            report["dump"] = stage("store-flatten", lambda: store("flatten"))

    if not args.grh_only:
        binary = args.gsim_binary.resolve()
        (output / "gsim").mkdir(parents=True, exist_ok=True)
        report["gsim_producer"] = {"path": str(binary), **json_identity(binary)}
        command = [str(binary), "--dir", str(output / "gsim"), "--dump-json",
                   "--dump-stages=Init", "--stop-after-stage=Init"]
        if args.assign_trees:
            command.append("--dump-assign-tree")
        command.append(str(source))
        report["gsim_command"] = command

        def gsim():
            with (output / "gsim.log").open("w") as log:
                process = subprocess.Popen(command, cwd=ROOT / "reference/gsim", stdout=log, stderr=subprocess.STDOUT)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command)
            files = sorted((output / "gsim").glob("*Init.json"))
            if len(files) != 1:
                raise RuntimeError("expected exactly one native GSIM Init inventory")
            return {"dump": {"path": str(files[0]), **json_identity(files[0])},
                    "maxrss_kib": usage.ru_maxrss, "cpu_s": usage.ru_utime + usage.ru_stime}

        stage("gsim-Init", gsim)
    report["complete"] = True
    persist()


if __name__ == "__main__":
    main()
