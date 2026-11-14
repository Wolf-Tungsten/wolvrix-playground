"""Measure F29 pass time with and without the public SemanticNode exchange trace."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import time

from benchmark_xs_firrtl_ingest import checked, request_from_manifest

ROOT = Path(__file__).resolve().parents[1]
SPLIT_BASELINE_S = 24.523
SPLIT_MAXIMUM_S = 2 * SPLIT_BASELINE_S

# A separate interpreter can enforce a deadline even while run_pass holds the GIL.
WATCHDOG_SOURCE = r'''
import json, os, select, signal, sys, time
payload = json.loads(sys.argv[1])
os.write(1, b"ready\n")
command, _, pending = os.read(0, 256).partition(b"\n")
if not command.startswith(b"arm "):
    sys.exit(0)
started = float(command.split()[1])
deadline = started + payload["timeout_s"]
ready = bool(pending)
if not ready:
    ready, _, _ = select.select([0], [], [], max(0.0, deadline - time.monotonic()))
if ready:
    command = pending or os.read(0, 256)
    if not command or command.startswith(b"cancel"):
        sys.exit(0)
    if command.startswith(b"done ") and float(command.split()[1]) <= deadline:
        sys.exit(0)
elapsed = time.monotonic() - started
row = payload["row"]
row.update(status="timeout", pass_s=elapsed, timeout_s=payload["timeout_s"],
           error="split-static-array exceeded its pass deadline")
result = payload["result"]
result["passes"].append(row)
result.update(status="failed", wall_s=time.monotonic() - payload["case_started"])
report = payload["report"]
report[payload["case_key"]] = result
report["status"] = "failed"
report["finished_at_ns"] = time.time_ns()
if payload.get("run_started") is not None:
    report["wall_s"] = time.monotonic() - payload["run_started"]
try:
    for path, value in ((payload["timing_path"], result),
                        (payload["summary_path"], report),
                        (payload["marker_path"], row)):
        temporary = path + ".watchdog.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
finally:
    os.write(2, ("split-static-array FAILED: exceeded %.3f s deadline\n" % payload["timeout_s"]).encode())
    if payload.get("perf_pid"):
        try:
            os.kill(payload["perf_pid"], signal.SIGINT)
        except ProcessLookupError:
            pass
    os.kill(payload["parent_pid"], signal.SIGKILL)
'''


class SplitWatchdog:
    def __init__(self, payload: dict):
        self.process = subprocess.Popen(
            [sys.executable, "-c", WATCHDOG_SOURCE, json.dumps(payload)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        if self.process.stdout.readline() != b"ready\n":
            raise RuntimeError("split watchdog did not start")

    def arm(self, started: float) -> None:
        os.write(self.process.stdin.fileno(), f"arm {started}\n".encode())

    def finish(self, finished: float | None) -> None:
        command = b"cancel\n" if finished is None else f"done {finished}\n".encode()
        communication_error = None
        try:
            os.write(self.process.stdin.fileno(), command)
        except OSError as error:
            communication_error = error
        finally:
            self.process.stdin.close()
            self.process.stdout.close()
        status = self.process.wait()
        if status != 0:
            raise RuntimeError(f"split watchdog failed with status {status}") from communication_error
        if communication_error is not None:
            raise RuntimeError("split watchdog communication failed") from communication_error


class SplitProfile:
    """Sample only the pass; perf setup and finalization stay outside its timer."""
    def __init__(self, output: Path):
        from profile_xs_firrtl_ingest import environment, prepare_symbols

        output.mkdir(parents=True, exist_ok=True)
        self.symbols = prepare_symbols(output)
        control_read, self.control_write = os.pipe()
        self.ack_read, ack_write = os.pipe()
        self.log = (output / "record.log").open("w")
        try:
            self.process = subprocess.Popen(
                ["perf", "record", "--no-buildid-cache", "-e", "cpu-clock:u", "-F", "99",
                 "--call-graph", "dwarf,8192", "--clockid", "mono", "-D", "-1",
                 "--control", f"fd:{control_read},{ack_write}",
                 "-o", str(output / "perf.data"), "-p", str(os.getpid())],
                pass_fds=(control_read, ack_write), env=environment(output),
                stdout=self.log, stderr=subprocess.STDOUT)
        finally:
            os.close(control_read)
            os.close(ack_write)
        try:
            self.command("enable")
        except BaseException:
            self.finish()
            raise

    def command(self, command: str) -> None:
        os.write(self.control_write, (command + "\n").encode())
        acknowledgement = os.read(self.ack_read, 256) if select.select([self.ack_read], [], [], 10)[0] else b""
        # perf writes its C string terminator on some versions.
        if acknowledgement.rstrip(b"\0\r\n") != b"ack":
            raise RuntimeError(f"perf did not acknowledge sampling ({acknowledgement!r}); see profile/record.log")

    def finish(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        status = self.process.wait(timeout=15)
        os.close(self.control_write)
        os.close(self.ack_read)
        self.log.close()
        if status not in (0, -signal.SIGINT):
            raise RuntimeError(f"perf record failed with status {status}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def native_identity(wolvrix) -> dict:
    from wolvrix import _wolvrix

    paths = {Path(_wolvrix.__file__).resolve()}
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        if "libwolvrix-lib.so" in line:
            candidate = Path(line.split(maxsplit=5)[5])
            if candidate.is_file():
                paths.add(candidate.resolve())
    return {"package": str(Path(wolvrix.__file__).resolve()),
            "libraries": [{"path": str(path), "sha256": sha256(path)} for path in sorted(paths)]}


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".failed.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_case(session, source: Path, output: Path, trace: bool, design: str,
             top: str, skip_comb: bool, input_sha256: str, split_timeout_s: float,
             report: dict, summary: Path, validate_after: bool = False,
             profile_split: bool = False, verify_after: bool = False,
             run_started: float | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    result = {"trace": trace, "design": design, "output": str(output), "passes": [], "skip_comb": skip_comb}
    case_started = time.monotonic()
    pass_stages = (("split-static-array", "post-split-static-array"),) if skip_comb else (
        ("comb-loop-elim", "post-comb"), ("split-static-array", "post-split-static-array"))
    for name, stage in pass_stages:
        bundle = output / name
        row = {"pass": name}
        total_started = time.perf_counter()
        total_usage = resource.getrusage(resource.RUSAGE_SELF)
        profile = None
        watchdog = None
        pass_started = None
        pass_finished = None
        row_recorded = False
        failure_stage = "trace-setup"
        try:
            if trace:
                print(json.dumps({"event": "trace-setup-start", "pass": name}), flush=True)
                setup_started = time.perf_counter()
                setup_usage = resource.getrusage(resource.RUSAGE_SELF)
                try:
                    session.semantic_exchange_start(
                        design=design, top=top, output=str(bundle),
                        stage=("post-hier-flatten" if skip_comb else "pre-split-after-comb")
                              if name == "split-static-array" else "flatten",
                        pass_name=name, input_sha256=input_sha256, validate_at_finish=validate_after)
                finally:
                    row["trace_setup_s"] = time.perf_counter() - setup_started
                    after_setup = resource.getrusage(resource.RUSAGE_SELF)
                    row["trace_setup_user_s"] = after_setup.ru_utime - setup_usage.ru_utime
                    row["trace_setup_system_s"] = after_setup.ru_stime - setup_usage.ru_stime
                row["trace_validate_at_finish"] = validate_after
                print(json.dumps({"event": "trace-setup-done", "pass": name,
                                  "trace_setup_s": row["trace_setup_s"]}), flush=True)
            failure_stage = "profile-setup"
            profile = SplitProfile(output / "profile") if profile_split and name == "split-static-array" else None
            if profile:
                row["profile"] = {"call_graph": "dwarf,8192", "frequency": 99,
                                  "symbols": profile.symbols}
            failure_stage = "watchdog-setup"
            if name == "split-static-array" and split_timeout_s > 0:
                watchdog = SplitWatchdog({
                    "timeout_s": split_timeout_s, "parent_pid": os.getpid(), "row": row,
                    "result": result, "report": report, "case_started": case_started,
                    "case_key": "trace" if trace else "no_trace", "timing_path": str(output / "timing.json"),
                    "summary_path": str(summary), "marker_path": str(output.parent / "split-timeout.marker"),
                    "run_started": run_started,
                    "perf_pid": profile.process.pid if profile else None})
            pass_started = time.monotonic()
            pass_usage = resource.getrusage(resource.RUSAGE_SELF)
            if watchdog:
                watchdog.arm(pass_started)
            failure_stage = "run-pass"
            pass_result = session.run_pass(name, design=design)
            pass_finished = time.monotonic()
            after_pass = resource.getrusage(resource.RUSAGE_SELF)
            row["pass_s"] = pass_finished - pass_started
            row["user_s"] = after_pass.ru_utime - pass_usage.ru_utime
            row["system_s"] = after_pass.ru_stime - pass_usage.ru_stime
            row["pass_returned"] = True
            failure_stage = "watchdog-finish"
            if watchdog:
                finishing_watchdog, watchdog = watchdog, None
                finishing_watchdog.finish(pass_finished)
            failure_stage = "profile-finish"
            if profile:
                finishing_profile, profile = profile, None
                finishing_profile.finish()
            failure_stage = "pass-result"
            checked(pass_result, name)
            print(json.dumps({"event": "pass-returned", "trace": trace, "pass": name,
                              "pass_s": row["pass_s"]}), flush=True)
            if trace:
                failure_stage = "trace-finish"
                finish_started = time.perf_counter()
                finish_usage = resource.getrusage(resource.RUSAGE_SELF)
                try:
                    session.semantic_exchange_finish(design=design, top=top, stage=stage)
                finally:
                    row["trace_finish_s"] = time.perf_counter() - finish_started
                    after_finish = resource.getrusage(resource.RUSAGE_SELF)
                    row["trace_finish_user_s"] = after_finish.ru_utime - finish_usage.ru_utime
                    row["trace_finish_system_s"] = after_finish.ru_stime - finish_usage.ru_stime
            if validate_after:
                failure_stage = "semantic-validation"
                validation_started = time.perf_counter()
                try:
                    row["semantic_validation"] = session.semantic_validate(design=design)
                finally:
                    row["semantic_validation_s"] = time.perf_counter() - validation_started
                if not row["semantic_validation"].get("valid"):
                    raise RuntimeError(f"{name}: semantic validation failed")
            if verify_after and name == "split-static-array":
                failure_stage = "grh-verification"
                verification_started = time.perf_counter()
                try:
                    checked(session.run_pass("grh.verify", design=design), "verify split result")
                finally:
                    row["grh_verification_s"] = time.perf_counter() - verification_started
                row["grh_verification"] = "passed"
            failure_stage = "reporting"
            total_finished_usage = resource.getrusage(resource.RUSAGE_SELF)
            row["total_user_s"] = total_finished_usage.ru_utime - total_usage.ru_utime
            row["total_system_s"] = total_finished_usage.ru_stime - total_usage.ru_stime
            row["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if trace:
                row["bytes"] = sum(path.stat().st_size for path in bundle.iterdir() if path.is_file())
            row["total_s"] = time.perf_counter() - total_started
            row["status"] = "passed"
            result["passes"].append(row)
            row_recorded = True
            write_json_atomic(output / "timing.json", result)
            print(json.dumps({"trace": trace, **row}), flush=True)
        except BaseException as error:
            row.update(status="failed", failure_stage=failure_stage, error=repr(error))
            if pass_started is not None and pass_finished is None:
                pass_finished = time.monotonic()
                row["pass_s"] = pass_finished - pass_started
            if failure_stage == "run-pass" and watchdog and row["pass_s"] > split_timeout_s:
                row.update(status="timeout", timeout_s=split_timeout_s)
            if watchdog:
                try:
                    watchdog.finish(pass_finished)
                except BaseException as cleanup_error:
                    row["watchdog_error"] = repr(cleanup_error)
            if profile:
                try:
                    profile.finish()
                except BaseException as cleanup_error:
                    row["profile_error"] = repr(cleanup_error)
            row["total_s"] = time.perf_counter() - total_started
            row["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if not row_recorded:
                result["passes"].append(row)
            result.update(status="failed", wall_s=time.monotonic() - case_started)
            report["trace" if trace else "no_trace"] = result
            report["status"] = "failed"
            for path, value in ((output / "timing.json", result), (summary, report)):
                try:
                    write_json_atomic(path, value)
                except BaseException as persistence_error:
                    try:
                        print(json.dumps({"event": "failure-report-write-error", "path": str(path),
                                          "error": repr(persistence_error)}), file=sys.stderr, flush=True)
                    except Exception:
                        pass
            raise
    result["wall_s"] = time.monotonic() - case_started
    result["status"] = "passed"
    result["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write_json_atomic(output / "timing.json", result)
    return result


def prepare_design(session, source: Path, manifest: Path, flatten_json: Path | None,
                   top: str, source_only: bool, clone: bool) -> dict:
    request = request_from_manifest(manifest)
    if source_only:
        request["sources"] = [{"path": str(source), "language": "firrtl", "unit": source.stem}]
        request["tops"] = [top]
        request.pop("slang_args", None)
        request["firrtl_options"] = {"invalid_policy": "zero", "node_annotations": True}
    stages = []
    def record_stage(name: str, started: float) -> None:
        row = {"stage": name, "wall_s": time.perf_counter() - started}
        stages.append(row)
        print(json.dumps(row), flush=True)

    if flatten_json:
        started = time.perf_counter()
        checked(session.read_json_file(str(flatten_json), out_design="design.main"), "load flattened checkpoint")
        record_stage("load-flatten-checkpoint", started)
    else:
        started = time.perf_counter()
        checked(session.read_sources(**request, out_design="design.main", pipeline="ingest"), "ingest")
        record_stage("ingest", started)
        started = time.perf_counter()
        checked(session.run_pass("xmr-resolve", design="design.main", keep_declared_symbols=True), "xmr-resolve")
        record_stage("xmr-resolve", started)
        started = time.perf_counter()
        checked(session.run_pass("hier-flatten", design="design.main", keep_declared_symbols=True), "hier-flatten")
        record_stage("hier-flatten", started)
    if clone:
        started = time.perf_counter()
        checked(session.clone_design(design="design.main", out_design="design.trace"), "clone flattened graph")
        record_stage("clone-flattened-graph", started)
    return {"stages": stages, "wall_s": sum(stage["wall_s"] for stage in stages)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--flatten-json", type=Path,
                        help="load an already flattened graph so timings exclude FIRRTL ingest/flatten")
    parser.add_argument("--top", default="SimTop", help="semantic graph top (default: SimTop)")
    parser.add_argument("--source-only", action="store_true",
                        help="ingest --firrtl as a standalone FIRRTL fixture instead of manifest sources")
    parser.add_argument("--skip-comb", action="store_true",
                        help="skip comb-loop-elim to isolate split-static-array timing")
    parser.add_argument("--validate-after", action="store_true",
                        help="validate SemanticTree after each pass, outside the pass timer")
    parser.add_argument("--profile-split", action="store_true",
                        help="record CPU call stacks during split only, preserving its hard deadline")
    parser.add_argument("--verify-after", action="store_true",
                        help="run the full GRH verifier after split, outside the pass timer")
    parser.add_argument("--mode", choices=("both", "no-trace", "trace"), default="both",
                        help="select which instrumentation case to run")
    parser.add_argument("--split-timeout-s", type=float, default=SPLIT_MAXIMUM_S,
                        help="hard wall-time limit for split-static-array only (default: 2 * 24.523 s)")
    args = parser.parse_args()
    if not math.isfinite(args.split_timeout_s) or not 0 < args.split_timeout_s <= SPLIT_MAXIMUM_S:
        parser.error(f"--split-timeout-s must be positive and at most {SPLIT_MAXIMUM_S:.3f} s (2x baseline)")
    source, manifest, output = (args.firrtl.resolve(), args.manifest.resolve(), args.output.resolve())
    if not source.is_file() or not manifest.is_file() or (args.flatten_json and not args.flatten_json.is_file()):
        parser.error("F29 benchmark requires an existing FIRRTL input and manifest")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "wolvrix.f29.pass-trace-benchmark.v1", "input": str(source),
              "manifest": str(manifest), "input_bytes": source.stat().st_size,
              "input_sha256": sha256(source),
              "top": args.top,
              "source_only": args.source_only,
              "skip_comb": args.skip_comb,
              "validate_after": args.validate_after,
              "profile_split": args.profile_split,
              "verify_after": args.verify_after,
              "mode": args.mode,
              "split_timeout_s": args.split_timeout_s,
              "split_historical_baseline_s": SPLIT_BASELINE_S,
              "split_maximum_multiplier": 2,
              "flatten_checkpoint": str(args.flatten_json.resolve()) if args.flatten_json else None}
    flatten_json = args.flatten_json.resolve() if args.flatten_json else None
    summary = output / "summary.json"
    summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    import wolvrix

    report["native"] = native_identity(wolvrix)
    summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with wolvrix.Session() as session:
        session.log_level = "error"
        session.diagnostics_raise_min_level = "none"
        report["prefix"] = prepare_design(session, source, manifest, flatten_json, args.top, args.source_only,
                                           clone=args.mode == "both")
        summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if args.mode in {"both", "no-trace"}:
            report["no_trace"] = run_case(session, source, output / "no-trace", False, "design.main",
                                           args.top, args.skip_comb, report["input_sha256"],
                                           args.split_timeout_s, report, summary, args.validate_after,
                                           args.profile_split, args.verify_after)
            summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if args.mode in {"both", "trace"}:
            report["trace"] = run_case(session, source, output / "trace", True,
                                        "design.trace" if args.mode == "both" else "design.main",
                                        args.top, args.skip_comb, report["input_sha256"],
                                        args.split_timeout_s, report, summary, args.validate_after,
                                        args.profile_split, args.verify_after)
            summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report["status"] = "passed"
        summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
