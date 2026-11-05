"""Record and report CPU call stacks for the fixed-input FIRRTL flatten prefix."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from benchmark_xs_firrtl_ingest import native_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / "ptmp/firrtl-ingest/F15/perf-10t-20261103"
DEFAULT_MANIFEST = ROOT / "ptmp/firrtl-ingest/F15/manifests/threads-10.json"


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text_identity(path: Path) -> dict:
    result = subprocess.run(["readelf", "-SW", str(path)], cwd=ROOT,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"readelf failed for {path}: {result.stderr.strip()}")
    match = re.search(r"^\s*\[\s*\d+\]\s+\.text\s+\S+\s+"
                      r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\b",
                      result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"No .text section in {path}")
    address, offset, size = (int(value, 16) for value in match.groups())
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as stream:
        stream.seek(offset)
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise RuntimeError(f"Truncated .text section: {path}")
            digest.update(chunk)
            remaining -= len(chunk)
    return {"address": address, "offset": offset, "bytes": size,
            "sha256": digest.hexdigest()}


def prepare_symbols(work: Path, native_dir: Path | None = None) -> list[dict]:
    symbols = work / "symbols"
    symfs = work / "symfs"
    symbols.mkdir(exist_ok=True)
    symfs.mkdir(exist_ok=True)
    for name in ("usr", "lib", "lib64", "bin", "sbin", "opt"):
        source = Path("/") / name
        target = symfs / name
        if source.exists() and not target.exists():
            target.symlink_to(source, target_is_directory=True)
    source_roots = {
        "libwolvrix-lib.so": ROOT / "wolvrix/build/skbuild/libwolvrix-lib.so",
        "_wolvrix.so": ROOT / "wolvrix/build/skbuild/python/wolvrix/_wolvrix.so",
    }
    result = []
    for library in native_identity():
        installed = Path(library["path"])
        source = (native_dir / (installed.stem + ".unstripped.so") if native_dir else
                  source_roots.get(installed.name))
        if native_dir and installed.resolve() != (native_dir / installed.name).resolve():
            raise RuntimeError(f"Profile loaded outside the selected native snapshot: {installed}")
        if source is None or not source.is_file():
            raise RuntimeError(f"No unstripped build counterpart for {installed}")
        before = text_identity(installed)
        after = text_identity(source)
        if any(before[key] != after[key] for key in ("address", "bytes", "sha256")):
            raise RuntimeError(f"Installed/build .text identity mismatch: {installed} / {source}")
        snapshot = symbols / installed.name
        shutil.copy2(source, snapshot)
        mapped = symfs / str(installed).lstrip("/")
        mapped.parent.mkdir(parents=True, exist_ok=True)
        if mapped.is_symlink():
            mapped.unlink()
        elif mapped.exists():
            raise RuntimeError(f"Refusing to replace existing symfs file: {mapped}")
        mapped.symlink_to(snapshot)
        result.append({"installed": library, "unstripped_source": str(source),
                       "snapshot": str(snapshot), "snapshot_sha256": sha256(snapshot),
                       "text_identity": before})
    write_json(work / "symbol-identity.json", result)
    return result


def environment(work: Path) -> dict:
    env = dict(os.environ)
    for path in (work / "build-id", work / "cache", work / "tmp"):
        path.mkdir(exist_ok=True)
    env.update({"PERF_BUILDID_DIR": str(work / "build-id"),
                "XDG_CACHE_HOME": str(work / "cache"), "PERF_CONFIG": "/dev/null",
                "TMPDIR": str(work / "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1", "WOLF_ENV_SOURCED": "1"})
    return env


def perf_prefix(perf: str, call_graph: str) -> list[str]:
    return [perf, "record", "--no-buildid-cache", "-e", "cpu-clock:u", "-F", "199",
            "--call-graph", call_graph, "--clockid", "mono"]


def record(args) -> None:
    work = args.work
    if (work / "perf.data").exists():
        raise RuntimeError(f"Profile already exists; use a new work directory: {work}")
    env = environment(work)
    version = subprocess.run([args.perf, "--version"], text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=env)
    metadata = {"work": str(work), "manifest": str(args.manifest),
                "manifest_sha256": sha256(args.manifest),
                "perf_version": version.stdout.strip(), "perf_version_returncode": version.returncode,
                "call_graph": args.call_graph, "python": sys.executable, "status": "preparing"}
    write_json(work / "record.json", metadata)
    probe = perf_prefix(args.perf, args.call_graph) + ["-o", str(work / "probe.perf.data"), "--", sys.executable,
        "-c", "import time\nend = time.monotonic() + 0.3\nwhile time.monotonic() < end: pass"]
    for path in (work / "probe.perf.data", work / "probe.perf.data.old"):
        path.unlink(missing_ok=True)
    metadata["probe_command"] = probe
    with (work / "probe.log").open("w") as log:
        completed = subprocess.run(probe, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    metadata["probe_returncode"] = completed.returncode
    if completed.returncode:
        metadata["status"] = "probe-failed"
        write_json(work / "record.json", metadata)
        raise RuntimeError(f"perf permission/capability probe failed ({completed.returncode}); "
                           f"see {work / 'probe.log'}")
    print("perf probe passed; checking unstripped symbol snapshots", flush=True)
    metadata["symbols"] = prepare_symbols(work, args.native_dir)
    benchmark_args = "--through-flatten --profile-timestamps" + (" --fused-prefix" if args.fused_prefix else "")
    python = sys.executable + (" -S" if args.native_dir else "")
    command = perf_prefix(args.perf, args.call_graph) + ["-o", str(work / "perf.data"), "--", "make",
        "--no-print-directory", "benchmark_f15_firrtl_ingest", "SKIP_PY_INSTALL=1",
        f"PYTHON={python}", f"F15_FIRRTL_MANIFEST={args.manifest}",
        f"F15_FIRRTL_BENCH_WORK={work / 'run'}",
        f"F15_FIRRTL_BENCH_ARGS={benchmark_args}"]
    metadata.update({"record_command": command, "status": "recording",
                     "started_at_unix": time.time()})
    write_json(work / "record.json", metadata)
    print(f"Recording ingest through hier-flatten into {work / 'perf.data'}", flush=True)
    started = time.monotonic()
    with (work / "record.log").open("w") as log:
        completed = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    metadata.update({"returncode": completed.returncode, "wall_s": time.monotonic() - started,
                     "finished_at_unix": time.time(),
                     "status": "complete" if completed.returncode == 0 else "record-failed"})
    write_json(work / "record.json", metadata)
    if completed.returncode:
        raise RuntimeError(f"perf record/benchmark failed ({completed.returncode}); "
                           f"see {work / 'record.log'}")
    print(json.dumps({key: metadata[key] for key in ("status", "returncode", "wall_s")}), flush=True)


def sample_quality(path: Path) -> dict:
    """Count sampled CPU period by thread and unresolved sampled leaf symbols."""
    prefix = re.compile(r"^\s*(?P<comm>.*?)\s+(?P<pid>\d+)/(?P<tid>\d+)\s+"
                        r"(?P<time>\d+\.\d+):\s+(?P<period>\d+)\s+"
                        r"(?P<ip>[0-9a-fA-F]+)\s+(?P<body>.*)$")
    threads = defaultdict(lambda: {"samples": 0, "period_ns": 0})
    unresolved = defaultdict(lambda: {"samples": 0, "period_ns": 0})
    total_samples = total_period = unknown_samples = unknown_period = 0
    lost_lines, unparsed = [], []
    with path.open() as stream:
        for line in stream:
            if not line.strip() or line.startswith("#"):
                continue
            match = prefix.match(line.rstrip())
            if not match:
                (lost_lines if "LOST" in line.upper() else unparsed).append(line.rstrip())
                continue
            row = match.groupdict()
            period = int(row["period"])
            key = (int(row["pid"]), int(row["tid"]), row["comm"].strip())
            threads[key]["samples"] += 1
            threads[key]["period_ns"] += period
            total_samples += 1
            total_period += period
            body = row["body"]
            if " (" in body and body.endswith(")"):
                symbol, dso = body.rsplit(" (", 1)
                dso = dso[:-1]
            else:
                symbol, dso = body, "[unknown]"
            if symbol == "[unknown]" or re.fullmatch(r"(?:0x)?[0-9a-fA-F]+", symbol):
                unknown_samples += 1
                unknown_period += period
                unresolved[dso]["samples"] += 1
                unresolved[dso]["period_ns"] += period
    return {
        "event": "cpu-clock:u", "period_unit": "nanoseconds",
        "scope": "sampled leaf symbol resolution; this does not measure callchain completeness",
        "samples": total_samples, "period_ns": total_period,
        "sampled_cpu_s": total_period / 10**9,
        "unresolved_leaf_samples": unknown_samples, "unresolved_leaf_period_ns": unknown_period,
        "unresolved_leaf_sample_fraction": unknown_samples / total_samples if total_samples else None,
        "unresolved_leaf_period_fraction": unknown_period / total_period if total_period else None,
        "unresolved_by_dso": dict(sorted(unresolved.items())),
        "lost_event_lines": lost_lines, "unparsed_lines": unparsed,
        "threads": [dict(pid=key[0], tid=key[1], comm=key[2], is_process_main_thread=key[0] == key[1], **value,
                         sampled_cpu_s=value["period_ns"] / 10**9,
                         period_fraction=value["period_ns"] / total_period if total_period else None)
                    for key, value in sorted(threads.items(), key=lambda item: -item[1]["period_ns"])],
    }


def stage_windows(stages: list[dict]) -> list[dict]:
    """Keep the fused endpoint as one observed interval; never split its CPU."""
    if (not stages or stages[0]["name"] not in ("ingest", "ingest-pre-flatten") or
            not stages[-1]["name"].endswith("hier-flatten")):
        raise RuntimeError("Incomplete ingest-through-flatten stage boundaries")
    for index, row in enumerate(stages):
        if (row["end_ns"] <= row["start_ns"] or not re.fullmatch(r"[A-Za-z0-9_-]+", row["name"]) or
                (index and stages[index - 1]["end_ns"] > row["start_ns"])):
            raise RuntimeError(f"Invalid stage boundary: {row}")
    if stages[0]["name"] == "ingest-pre-flatten" and len(stages) != 2:
        raise RuntimeError("Fused ingest prefix must have one joint interval and hier-flatten")
    spans = list(stages)
    spans.append({"name": "whole", "start_ns": stages[0]["start_ns"], "end_ns": stages[-1]["end_ns"]})
    if stages[0]["name"] == "ingest" and len(stages) > 2:
        spans.append({"name": "pre-flatten", "start_ns": stages[1]["start_ns"], "end_ns": stages[-2]["end_ns"]})
    priority = {stages[0]["name"]: 0, stages[-1]["name"]: 1, "whole": 2, "pre-flatten": 3}
    return sorted(spans, key=lambda row: priority.get(row["name"], 4))


def report(args) -> None:
    work = args.work
    data = json.loads((work / "run/profile-stages.json").read_text())
    if data.get("clock") != "monotonic":
        raise RuntimeError("Profile stages must use the monotonic clock")
    stages = data["stages"]
    spans = stage_windows(stages)
    if args.stage:
        names = {row["name"] for row in spans}
        if set(args.stage) - names:
            raise RuntimeError(f"Unknown report stages: {sorted(set(args.stage) - names)}")
        spans = [row for row in spans if row["name"] in args.stage]
    output = args.report_dir.resolve() if args.report_dir else work / "reports"
    if not output.is_relative_to(work) or output == work:
        raise RuntimeError("report directory must be a subdirectory of the profile work directory")
    output.mkdir(exist_ok=True)
    env = environment(work)
    if args.perf_preload:
        preload = args.perf_preload.resolve()
        if not preload.is_relative_to(work) or not preload.is_file():
            raise RuntimeError("perf preload must be an existing analysis helper under work")
        env["LD_PRELOAD"] = str(preload)
        env["WOLVRIX_DWFL_BIAS_FIX"] = "1"
    commands = []

    def execute(row, label, command):
        destination = output / f"{row['name']}.{label}.txt"
        error = destination.with_suffix(".stderr.log")
        with destination.open("w") as stdout, error.open("w") as stderr:
            completed = subprocess.run(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        commands.append({"stage": row, "variant": label, "command": command,
                         "returncode": completed.returncode, "stdout": str(destination),
                         "stderr": str(error)})
        write_json(output / "commands.json", commands)
        if output == work / "reports":
            write_json(work / "report-commands.json", commands)
        if completed.returncode:
            raise RuntimeError(f"perf report/script failed ({completed.returncode}): {error}")
        return destination

    for row in spans:
        start = f"{row['start_ns'] // 10**9}.{row['start_ns'] % 10**9:09d}"
        end = f"{row['end_ns'] // 10**9}.{row['end_ns'] % 10**9:09d}"
        common = [args.perf, "report", "--stdio", "--stdio-color", "never",
                  "--symfs", str(work / "symfs"), "-i", str(work / "perf.data"),
                  "--time", f"{start},{end}", "-n", "--show-total-period",
                  "--sort", "dso,symbol", "--percent-limit", "0"]
        variants = [("self", ["--no-children", "-g", "none"]),
                    ("inclusive", ["--children", "-g", "none"])]
        if row["name"] in ("ingest", "ingest-pre-flatten") or row["name"].endswith("hier-flatten"):
            variants.append(("calltree", ["--children", "-g", "graph,0.5,caller"]))
        for label, options in variants:
            execute(row, label, common + options)
        if row["name"] in ("ingest", "ingest-pre-flatten", "whole") or row["name"].endswith("hier-flatten"):
            stats = execute(row, "stats", common + ["--no-children", "-g", "none", "--stats", "--header"])
            samples = execute(row, "samples", [args.perf, "script", "--hide-call-graph", "--ns",
                "--show-lost-events", "--symfs", str(work / "symfs"), "-i", str(work / "perf.data"),
                "--time", f"{start},{end}", "-F", "pid,tid,time,period,comm,ip,sym,dso"])
            quality = sample_quality(samples)
            quality.update({"stage": row, "stats_report": str(stats),
                            "stats_scope": "perf report --stats counts the full recording even with --time; "
                                           "interval sample counts come from perf script",
                            "lost_record_stat_lines": [line.strip() for line in stats.read_text().splitlines()
                                                       if re.search(r"\bLOST(?:_SAMPLES)?\s+events:",
                                                                    line, re.IGNORECASE)]})
            write_json(output / f"{row['name']}.quality.json", quality)
        print(f"Reported {row['name']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "report"))
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--perf", default="perf")
    parser.add_argument("--call-graph", default="dwarf,8192", choices=("dwarf,8192", "fp"),
                        help="perf call-stack collection mode")
    parser.add_argument("--fused-prefix", action="store_true", help="record the joint ingest/pre-flatten endpoint")
    parser.add_argument("--native-dir", type=Path, help="load and symbolize an immutable packaged native snapshot")
    parser.add_argument("--report-dir", type=Path,
                        help="separate output directory under work for offline analysis variants")
    parser.add_argument("--stage", action="append", help="report only selected stage names")
    parser.add_argument("--perf-preload", type=Path,
                        help="load a work-local offline unwinder adapter into perf processes only")
    args = parser.parse_args()
    args.work = args.work.resolve()
    args.manifest = args.manifest.resolve()
    if args.native_dir:
        args.native_dir = args.native_dir.resolve()
    if not args.work.is_relative_to(ROOT / "ptmp/firrtl-ingest"):
        parser.error("work must be under repository ptmp/firrtl-ingest")
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the project root")
    args.work.mkdir(parents=True, exist_ok=True)
    {"record": record, "report": report}[args.action](args)


if __name__ == "__main__":
    main()
