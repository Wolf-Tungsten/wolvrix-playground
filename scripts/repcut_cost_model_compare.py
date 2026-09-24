#!/usr/bin/env python3
"""Compare RepCut cost-model binaries with C100 checks and AB/BA pairs.

Run on node030. The fixed CoreMark image, NEMU, runtime configuration and
functional signatures match the existing all-spin calibration experiment.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[1]
ANALYZER = REPO / "build/asc_separator_20260920/analyze_allspin_comparison.py"
IMAGE = REPO / "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin"
NEMU = REPO / "testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so"
NUMACTL = Path("/nfs/home/tanghaojin/bin/numactl")
VARIANTS = ("baseline", "candidate")
CPUS = "96-127"


def identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path.resolve()), "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def load_analyzer():
    spec = importlib.util.spec_from_file_location("repcut_allspin_analyzer", ANALYZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load analyzer: {ANALYZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SIGNATURES[30000] = {
        "pc": "0x80000442", "instructions": 27809, "cycles": 29996,
        "guest_cycles": 30001, "steps": 60102,
    }
    return module


def schedule(pairs: int, cycles: int = 10000) -> list[dict[str, Any]]:
    runs = [
        {"name": f"c100-{variant}", "variant": variant, "cycles": 100,
         "pair": 0, "slot": slot}
        for slot, variant in zip(("a", "b"), VARIANTS)
    ]
    for pair in range(1, pairs + 1):
        order = VARIANTS if pair % 2 else tuple(reversed(VARIANTS))
        runs.extend(
            {"name": f"pair{pair:02d}-{slot}-{variant}", "variant": variant,
             "cycles": cycles, "pair": pair, "slot": slot}
            for slot, variant in zip(("a", "b"), order)
        )
    return runs


def command_for(run: dict, binaries: dict[str, Path], output: Path) -> list[str]:
    return [
        "/usr/bin/time", "-v", "-o", str(output / f"{run['name']}.time"),
        "taskset", "--cpu-list", CPUS, str(NUMACTL),
        f"--physcpubind={CPUS}", "--membind=1", "setarch", "x86_64", "-R",
        str(binaries[run["variant"]]), "-i", str(IMAGE), "--diff", str(NEMU),
        "-b", "0", "-e", "0", "-C", str(run["cycles"]),
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def write_success_exports(output: Path, runs: list[dict], analyzer) -> None:
    """Checkpoint every successful sample, including an incomplete final pair."""
    successful = [run for run in runs if run["status"] == "pass"]
    measured = [run for run in successful if run["pair"]]
    rows = [
        {"pair": run["pair"], "slot": run["slot"], "variant": run["variant"],
         **run["row"]}
        for run in measured
    ]
    parts = [
        {"name": run["name"], "pair": run["pair"], "variant": run["variant"], **part}
        for run in measured for part in run["parts"]
    ]
    write_json(output / "functional_signatures.json", {
        run["name"]: {"cycles": run["cycles"], "signature": run["signature"],
                      "runtime_config": run["runtime_config"]}
        for run in successful
    })
    write_json(output / "runs.json", rows)
    write_json(output / "parts.json", parts)
    if rows:
        analyzer.write_csv(output / "runs.csv", rows)
        analyzer.write_csv(output / "parts.csv", parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-binary", required=True, type=Path)
    parser.add_argument("--candidate-binary", required=True, type=Path)
    parser.add_argument("--baseline-package", required=True, type=Path)
    parser.add_argument("--candidate-package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--cycles", type=int, choices=(10000, 30000), default=10000)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the fixed schedule without executing or writing anything")
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("--pairs must be positive")
    binaries = {variant: getattr(args, f"{variant}_binary").resolve() for variant in VARIANTS}
    packages = {variant: getattr(args, f"{variant}_package").resolve() for variant in VARIANTS}
    output = args.output.resolve()
    planned = schedule(args.pairs, args.cycles)
    if args.dry_run:
        print(json.dumps({
            "required_host": "node030", "cpus": CPUS, "numa_node": 1,
            "aslr": "disabled", "lanes": 32, "partitions": 32,
            "wait_policy": "current-default-all-spin", "output": str(output),
            "packages": {key: str(path) for key, path in packages.items()},
            "analyzer": str(ANALYZER),
            "runs": [{**run, "command": command_for(run, binaries, output)} for run in planned],
        }, indent=2))
        return
    if socket.gethostname().split(".")[0] != "node030":
        parser.error("run on node030; CPUs 96-127 are reserved for this experiment")
    for binary in binaries.values():
        if not binary.is_file() or not os.access(binary, os.X_OK):
            parser.error(f"not an executable file: {binary}")
    for package in packages.values():
        if not package.is_dir():
            parser.error(f"package directory missing: {package}")
    for path in (IMAGE, NEMU, ANALYZER, NUMACTL, Path("/usr/bin/time")):
        if not path.is_file():
            parser.error(f"required input or tool missing: {path}")
    for tool in ("taskset", "setarch"):
        if shutil.which(tool) is None:
            parser.error(f"required tool missing: {tool}")
    analyzer = load_analyzer()
    transfers = {variant: analyzer.communication(package) for variant, package in packages.items()}
    artifacts = {f"{variant}_elf": path for variant, path in binaries.items()}
    artifacts.update(image=IMAGE, nemu=NEMU)
    before = {name: identity(path) for name, path in artifacts.items()}
    environment = os.environ.copy()
    removed = sorted(key for key in environment
                     if key.startswith(("WOLVI_REPCUT_", "XS_REPCUT_", "EMU_"))
                     or key in ("LD_PRELOAD", "LD_LIBRARY_PATH"))
    for key in removed:
        del environment[key]
    environment.update(LC_ALL="C", XS_EMU_THREADS="32", XS_REPCUT_STEP_TIMING="1")
    manifest = {
        "schema_version": 1, "status": "running", "host": socket.getfqdn(),
        "started_utc": datetime.now(timezone.utc).isoformat(), "pairs": args.pairs,
        "measured_cycles": args.cycles,
        "cpus": CPUS, "numa_node": 1, "aslr": "disabled", "threads": 32,
        "partitions": 32, "wait_policy": "current-default-all-spin",
        "binaries": {variant: before[f"{variant}_elf"] for variant in VARIANTS},
        "image": before["image"], "nemu": before["nemu"], "inputs_before": before,
        "analysis_script": identity(ANALYZER), "runner_script": identity(Path(__file__)),
        "packages": {variant: str(path) for variant, path in packages.items()},
        "cleared_runtime_env_names": removed, "runtime_overrides": {},
        "environment": {key: environment[key] for key in ("LC_ALL", "XS_EMU_THREADS", "XS_REPCUT_STEP_TIMING")},
        "communication": transfers, "planned_runs": planned, "runs": [],
        "sampling_policy": "retain every functionally successful sample; no external-load gate, retries or outlier filtering",
        "smoke_note": "C100 is initialization/reset validation; measured runs enable difftest",
        "expected_signatures": analyzer.SIGNATURES,
    }
    output.mkdir(parents=True, exist_ok=False)

    def save() -> None:
        write_json(output / "manifest.json", manifest)
        write_success_exports(output, manifest["runs"], analyzer)

    def capture_after() -> None:
        after = {}
        for name, path in artifacts.items():
            try:
                after[name] = identity(path)
            except OSError as error:
                after[name] = {"path": str(path), "error": str(error)}
        manifest["inputs_after"] = after
        manifest["input_identity_unchanged"] = after == before

    save()
    try:
        for planned_run in planned:
            run = {**planned_run, "status": "running",
                   "started_utc": datetime.now(timezone.utc).isoformat(),
                   "command": command_for(planned_run, binaries, output)}
            manifest["runs"].append(run)
            save()
            print(f"[run] {run['name']}", flush=True)
            env = dict(environment, WOLVI_REPCUT_TIMING_JSONL=str(output / f"{run['name']}.timing.jsonl"))
            with (output / f"{run['name']}.log").open("x") as log:
                completed = subprocess.run(run["command"], cwd=REPO, env=env,
                                           stdout=log, stderr=subprocess.STDOUT, check=False)
            run["exit_code"] = completed.returncode
            if completed.returncode:
                raise RuntimeError(f"{run['name']}: process exited {completed.returncode}")
            if run["pair"] and "Difftest enabled" not in (output / f"{run['name']}.log").read_text():
                raise RuntimeError(f"{run['name']}: difftest was not enabled")
            result = analyzer.parse_run(output, run["name"], run["cycles"])
            run.update(result, status="pass", finished_utc=datetime.now(timezone.utc).isoformat())
            save()
            print(f"[pass] {run['name']}: Host={run['row']['host_s']:.3f}s, "
                  f"wall={run['row']['elapsed_s']:.2f}s", flush=True)
        capture_after()
        if not manifest["input_identity_unchanged"]:
            raise RuntimeError("ELF, image or NEMU identity changed during comparison")
        manifest.update(status="pass", finished_utc=datetime.now(timezone.utc).isoformat())
        save()
        summary = analyzer.analyze(output)
        summary.update(inputs_before=before, inputs_after=manifest["inputs_after"],
                       input_identity_unchanged=True, sampling_policy=manifest["sampling_policy"],
                       measured_cycles=args.cycles, smoke_note=manifest["smoke_note"])
        write_json(output / "summary.json", summary)
        analyzer.write_csv(output / "summary.csv", [
            {"metric": metric, **values} for metric, values in summary["metrics"].items()
        ])
        with (output / "pairs.csv").open(newline="") as stream:
            pairs = [
                {key: int(value) if key == "pair" else value if key == "order" else float(value)
                 for key, value in row.items()}
                for row in csv.DictReader(stream)
            ]
        write_json(output / "pairs.json", pairs)
        print(json.dumps({"status": "pass", "output": str(output), "metrics": summary["metrics"]}, indent=2))
    except BaseException as error:
        for run in manifest["runs"]:
            if run["status"] == "running":
                run.update(status="error", error=str(error),
                           finished_utc=datetime.now(timezone.utc).isoformat())
        capture_after()
        manifest.update(status="error", error_type=type(error).__name__, error=str(error),
                        finished_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == "__main__":
    main()
