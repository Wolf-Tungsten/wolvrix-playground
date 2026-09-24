#!/usr/bin/env python3
"""Compare native dynamic work and per-instruction cost between the GrhSIM-IR emu
and the gsim emu on the single-threaded 100k CoreMark caliber.

All emu runs go through the project Make run targets with perf injected through
XS_EMU_PREFIX (the profile_grhsim_ir.py pattern). Passes:
  perfstat  3+3 alternating perf stat runs (main 5-event group, difftest on)
  icache   one perf stat run per side (icache/TLB event group, difftest on)
  nodiff   one perf stat run per side with XS_EMU_DIFF_ARGS= (model net work)
  record   one perf record run per side + perf report symbol attribution
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import statistics
import subprocess
import time

from benchmark_grhsim_ir import FAILURE, digest, evict_page_cache

MAIN_EVENTS = ("cycles:u", "instructions:u", "branch-misses:u",
               "L1-dcache-loads:u", "L1-dcache-load-misses:u")
ICACHE_EVENTS = ("cycles:u", "instructions:u", "L1-icache-load-misses:u",
                 "iTLB-load-misses:u", "dTLB-load-misses:u")


# --- pure parsers (unit-tested) ---

def parse_perf_stat(text: str, events: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(",")
        if len(fields) < 3:
            continue
        value, event = fields[0].strip(), fields[2].strip()
        if event not in events:
            continue
        if value in ("<not counted>", "<not supported>"):
            raise ValueError(f"perf event {event}: {value}")
        counts[event] = counts.get(event, 0) + int(value)
    missing = [event for event in events if event not in counts]
    if missing:
        raise ValueError(f"missing perf events: {missing}")
    return counts


REPORT_ROW = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)%\s+(\S+)\s+\[.\]\s+(.+?)\s*$")


def parse_perf_report(text: str) -> list[tuple[float, str, str]]:
    rows = []
    for line in text.splitlines():
        match = REPORT_ROW.match(line)
        if match:
            rows.append((float(match.group(1)), match.group(2), match.group(3)))
    if not rows:
        raise ValueError("no perf report rows")
    return rows


TICK = r"cpu_profile_tick\(cpu_profile_data\.%s(?:,[^)]*)?\);"


def task_phases(text: str) -> dict[int, str]:
    """Map generated cpu_task_N() ids to compute/commit phase via eval() source.

    Tolerates both the one-argument and the two-argument (edge-split) profile
    tick call forms; the phase boundaries are the single compute_ns and
    commit_ns tick calls inside eval().
    """
    match = re.search(r"void \w+::eval\(\)\{(.*?)void \w+::dump_runtime_profile", text, re.S)
    if not match:
        raise ValueError("no generated evaluator/profile boundaries")
    parts = re.split(TICK % "compute_ns", match[1])
    if len(parts) != 2:
        raise ValueError("expected one contiguous compute phase")
    commit = re.split(TICK % "commit_ns", parts[1])
    if len(commit) != 2:
        raise ValueError("expected one contiguous commit phase")
    phases: dict[int, str] = {}
    for phase, body in (("compute_task", parts[0]), ("commit_task", commit[0])):
        for task in re.findall(r"cpu_task_(\d+)\(\);", body):
            if int(task) in phases:
                raise ValueError("duplicate scheduled task")
            phases[int(task)] = phase
    if not phases:
        raise ValueError("no scheduled tasks")
    return phases


IR_TASK = re.compile(r"(?:\w+::cpu_task_|_ZN\w*SimTop\d+cpu_task_)(\d+)\(?")
IR_EVAL = re.compile(r"(?:\w+::eval\(\)|_ZN\w*SimTop4evalEv)$")
IR_MODEL = re.compile(r"^(?:GrhSIM_SimTop::|_ZN13GrhSIM_SimTop)")
IR_HELPER = re.compile(r"^(?:cpu_\w+|_Z\d+cpu_[A-Za-z0-9_]+)")
GSIM_STEP = re.compile(r"(?:\bSSimTop::subStep|_ZN7SSimTop\d+subStep)\d+")
GSIM_MODEL = re.compile(r"^(?:SSimTop::|_ZN7SSimTop)")


def _dso_class(symbol: str, dso: str) -> str:
    dso_l = dso.lower()
    if "nemu" in dso_l:
        return "difftest_ref"
    if "libc" in dso_l or "ld-musl" in dso_l or "ld-linux" in dso_l:
        return "libc"
    if "emu" in dso_l:
        return "harness"
    return "external"


def classify_ir(symbol: str, dso: str, phases: dict[int, str]) -> str:
    if "nemu" in dso.lower():
        return "difftest_ref"
    task = IR_TASK.search(symbol)
    if task:
        return phases.get(int(task.group(1)), "task_unmapped")
    if IR_EVAL.search(symbol):
        return "evaluator"
    if IR_MODEL.search(symbol):
        return "model_infra"
    if IR_HELPER.search(symbol):
        return "helpers"
    return _dso_class(symbol, dso)


def classify_gsim(symbol: str, dso: str) -> str:
    if "nemu" in dso.lower():
        return "difftest_ref"
    if GSIM_STEP.search(symbol):
        return "model_step"
    if GSIM_MODEL.search(symbol):
        return "model_infra"
    return _dso_class(symbol, dso)


def endpoint_fields(text: str, require_difftest: bool) -> tuple[int, int, int, str, float]:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if FAILURE.search(text):
        raise ValueError("failed run")
    # "The reference model is" is printed only when the reference .so is actually
    # loaded (difftest attached); [DIFFTEST_INIT] prints even with --no-diff.
    if require_difftest and "The reference model is" not in text:
        raise ValueError("missing difftest")
    # difftest formats counters with %'d, so digits may carry locale thousands
    # separators (setlocale(LC_NUMERIC, "") in common.cpp); accept both forms.
    counts = re.search(r"instrCnt = ([\d,]+), cycleCnt = ([\d,]+)", text)
    guest = re.search(r"Guest cycle spent: ([\d,]+)", text)
    pc = re.search(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-f]+)", text)
    host = re.search(r"Host time spent: ([\d,]+)ms", text)
    if not all((counts, guest, pc, host)):
        raise ValueError("missing endpoint fields")
    return (int(counts[1].replace(",", "")), int(counts[2].replace(",", "")),
            int(guest[1].replace(",", "")), pc[1], int(host[1].replace(",", "")) / 1000)


def summarize(counter_runs: dict[str, list[dict]], events: tuple[str, ...]) -> dict:
    out: dict[str, dict] = {}
    for side, runs in counter_runs.items():
        means = {event: statistics.mean(run["counts"][event] for run in runs) for event in events}
        instr = [run["counts"]["instructions:u"] for run in runs]
        out[side] = {"runs": len(runs), "means": means,
                     "instructions": instr,
                     "instr_spread_ratio": (max(instr) - min(instr)) / statistics.mean(instr),
                     "cpi": means["cycles:u"] / means["instructions:u"],
                     "host_s": [run["host_s"] for run in runs],
                     "host_mean_s": statistics.mean(run["host_s"] for run in runs)}
    if len(out) == 2:
        ir, gsim = out["ir"], out["gsim"]
        instr_ratio = ir["means"]["instructions:u"] / gsim["means"]["instructions:u"]
        cpi_ratio = ir["cpi"] / gsim["cpi"]
        cycle_ratio = ir["means"]["cycles:u"] / gsim["means"]["cycles:u"]
        out["ratio"] = {"instructions": instr_ratio, "cpi": cpi_ratio, "cycles": cycle_ratio,
                        "closure_deviation": abs(instr_ratio * cpi_ratio / cycle_ratio - 1.0),
                        "host": ir["host_mean_s"] / gsim["host_mean_s"]}
    return out


# --- run orchestration ---

def run_emu(root: Path, output: Path, label: str, side: dict, prefix: list[str],
            difftest: bool, cutoff: float, env: dict[str, str],
            extra_make_vars: tuple[str, ...] = ()) -> dict:
    directory = output / label
    directory.mkdir()
    evicted = evict_page_cache(side["binary"])
    command = ["make", "--no-print-directory", side["make_target"],
               f"{side['build_var']}={side['flow']}", f"XS_LOG_DIR={directory / 'logs'}",
               f"RUN_ID={output.parent.name}_{output.name}_{label}",
               "XS_NUM_CORES=1", "XS_EMU_THREADS=1", "EMU_THREADS=1",
               "XS_SIM_MAX_CYCLE=100000", "XS_WAVEFORM=0", "XS_WAVEFORM_PATH=",
               "XS_COMMIT_TRACE=0", "XS_RAM_TRACE=0", "XS_PROGRESS_EVERY_CYCLES=0",
               f"XS_EMU_PREFIX={shlex.join(prefix)}", *extra_make_vars]
    (directory / "command.sh").write_text(shlex.join(command) + "\n")
    print(f"START {label}", flush=True)
    start = time.monotonic()
    log = directory / "make.log"
    killed = None
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        while process.poll() is None:
            if FAILURE.search(log.read_text(errors="replace")):
                killed = "INVALID"
            elif time.monotonic() - start > cutoff + 30:
                killed = "REGRESSION_KILLED"
            if killed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            time.sleep(0.5)
        status = process.wait()
    result = {"label": label, "side": side["name"], "make_exit": status,
              "make_wall_s": time.monotonic() - start, "evicted": evicted,
              "difftest": difftest}
    if status or killed:
        reason = killed or ("REGRESSION_KILLED" if status in (137, -9) or result["make_wall_s"] >= cutoff else "INVALID")
        result["classification"] = reason
        (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
        raise RuntimeError(f"{label}: {reason}, Make exit={status}; see {log}")
    parsed = endpoint_fields(log.read_text(), require_difftest=difftest)
    if list(parsed[:4]) != side["expected_endpoint"]:
        result["classification"] = "INVALID"
        (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
        raise RuntimeError(f"{label}: INVALID endpoint {parsed[:4]}")
    result.update(host_s=parsed[4], endpoint=list(parsed[:4]), classification="VALID")
    (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"DONE {label} Host={parsed[4]:.3f}s", flush=True)
    return result


def perf_stat_pass(root: Path, output: Path, label: str, side: dict, events: tuple[str, ...],
                   difftest: bool, env: dict[str, str]) -> dict:
    directory = output / label
    stat_file = directory / "perf.stat"
    prefix = ["perf", "stat", "-x,", "-e", ",".join(events), "-o", str(stat_file),
              "taskset", "-c", str(side["cpu"]), "stdbuf", "-oL", "-eL"]
    extra = () if difftest else ("XS_EMU_DIFF_ARGS=--no-diff",)
    result = run_emu(root, output, label, side, prefix, difftest, side["cutoff"], env, extra)
    result["counts"] = parse_perf_stat(stat_file.read_text(), events)
    result["events"] = list(events)
    (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def perf_record_pass(root: Path, output: Path, label: str, side: dict,
                     env: dict[str, str]) -> dict:
    directory = output / label
    data = directory / "perf.data"
    prefix = ["perf", "record", "-o", str(data), "-F", "999", "-e", "cycles:u",
              "taskset", "-c", str(side["cpu"]), "stdbuf", "-oL", "-eL"]
    result = run_emu(root, output, label, side, prefix, True, side["cutoff"], env)
    report = subprocess.check_output(
        ["perf", "report", "--stdio", "-i", str(data), "--no-children", "-g", "none",
         "--sort=dso,sym", "--demangle", "--percent-limit=0.001"], text=True)
    (directory / "perf.report").write_text(report)
    rows = parse_perf_report(report)
    classes: dict[str, float] = {}
    functions: dict[str, float] = {}
    for pct, dso, symbol in rows:
        klass = (classify_ir(symbol, dso, side["phases"]) if side["name"] == "ir"
                 else classify_gsim(symbol, dso))
        classes[klass] = classes.get(klass, 0.0) + pct
        functions[f"{symbol} [{dso}]"] = pct
    top = sorted(functions.items(), key=lambda item: item[1], reverse=True)[:20]
    result["class_shares"] = dict(sorted(classes.items(), key=lambda item: -item[1]))
    result["reported_share"] = sum(pct for pct, _, _ in rows)
    result["top_functions"] = [{"symbol": name, "share": pct} for name, pct in top]
    (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ir-flow", type=Path, required=True)
    parser.add_argument("--gsim-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--ir-endpoint", default="240349,99996,100001,0x80000c0c")
    parser.add_argument("--gsim-endpoint", default="238550,99998,100001,0x80000b40")
    parser.add_argument("--ir-baseline-seconds", type=float, required=True)
    parser.add_argument("--gsim-baseline-seconds", type=float, required=True)
    parser.add_argument("--ir-model-cpp", type=Path, default=None,
                        help="generated model translation unit with eval(); default <ir-flow>/model/grhsim_SimTop.cpp")
    parser.add_argument("--passes", default="perfstat,icache,nodiff,record")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "ptmp") or output.exists():
        parser.error("output must be a new directory under ptmp")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("CPU must be available")
    if not (math.isfinite(args.ir_baseline_seconds) and args.ir_baseline_seconds > 0
            and math.isfinite(args.gsim_baseline_seconds) and args.gsim_baseline_seconds > 0):
        parser.error("baseline times must be positive and finite")
    passes = [name.strip() for name in args.passes.split(",") if name.strip()]
    if not passes or any(name not in ("perfstat", "icache", "nodiff", "record") for name in passes):
        parser.error("--passes must be a comma subset of perfstat,icache,nodiff,record")

    def endpoint(value: str) -> list:
        fields = value.split(",")
        return [int(fields[0]), int(fields[1]), int(fields[2]), fields[3]]

    ir_flow = args.ir_flow.resolve()
    gsim_build = args.gsim_build.resolve()
    model_cpp = (args.ir_model_cpp or ir_flow / "model" / "grhsim_SimTop.cpp").resolve()
    sides = {
        "ir": {"name": "ir", "flow": ir_flow, "binary": ir_flow / "emu" / "emu",
               "make_target": "run_xs_wolf_grhsim_ir_emu", "build_var": "XS_GRHSIM_IR_BUILD",
               "expected_endpoint": endpoint(args.ir_endpoint),
               "cutoff": args.ir_baseline_seconds * 1.5, "cpu": args.cpu},
        "gsim": {"name": "gsim", "flow": gsim_build, "binary": gsim_build / "emu",
                 "make_target": "run_xs_gsim_emu", "build_var": "XS_GSIM_BUILD",
                 "expected_endpoint": endpoint(args.gsim_endpoint),
                 "cutoff": args.gsim_baseline_seconds * 1.5, "cpu": args.cpu},
    }
    for side in sides.values():
        if not side["binary"].is_file():
            parser.error(f"missing emu binary: {side['binary']}")
    phases = task_phases(model_cpp.read_text()) if "record" in passes else None
    if phases is not None:
        sides["ir"]["phases"] = phases
    order = [(name, i) for i in range(1, args.pairs + 1) for name in ("gsim", "ir")]
    registration = {"passes": passes, "order": [f"{name}{i}" for name, i in order],
                    "main_events": list(MAIN_EVENTS), "icache_events": list(ICACHE_EVENTS),
                    "binaries": {name: {"path": str(side["binary"]),
                                        "sha256": digest(side["binary"])}
                                 for name, side in sides.items()},
                    "inputs": {name: digest(root / "testcase/xiangshan/ready-to-run" / name)
                               for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so")},
                    "expected_endpoints": {name: side["expected_endpoint"] for name, side in sides.items()},
                    "cutoffs_s": {name: side["cutoff"] for name, side in sides.items()},
                    "cpu": args.cpu, "threads": 1, "cycles": 100000, "trace": False,
                    "make_targets": {name: side["make_target"] for name, side in sides.items()},
                    "model_cpp": str(model_cpp),
                    "kind": "perf-instrumented diagnostic; Host times recorded, never baselines",
                    "timestamp": time.time()}
    output.mkdir(parents=True)
    (output / "preregister.json").write_text(json.dumps(registration, indent=2) + "\n")
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPUPROFILE", "CPUPROFILE_FREQUENCY", "LD_PRELOAD")}
    env.update(WOLF_ENV_SOURCED="1", EMU_THREADS="1", EMU_RUNTIME_PROFILE="0",
               EMU_PHASE_TIMING="0", LC_ALL="C")

    results: dict[str, list] = {"perfstat": [], "icache": [], "nodiff": [], "record": []}
    if "perfstat" in passes:
        for name, repeat in order:
            results["perfstat"].append(perf_stat_pass(
                root, output, f"{name}{repeat}", sides[name], MAIN_EVENTS, True, env))
    if "icache" in passes:
        for name in ("gsim", "ir"):
            results["icache"].append(perf_stat_pass(
                root, output, f"{name}_icache", sides[name], ICACHE_EVENTS, True, env))
    if "nodiff" in passes:
        for name in ("gsim", "ir"):
            results["nodiff"].append(perf_stat_pass(
                root, output, f"{name}_nodiff", sides[name], MAIN_EVENTS, False, env))
    if "record" in passes:
        for name in ("gsim", "ir"):
            results["record"].append(perf_record_pass(
                root, output, f"{name}_record", sides[name], env))
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")

    summary: dict = {"passes": passes}
    if results["perfstat"]:
        per_side = {"ir": [r for r in results["perfstat"] if r["side"] == "ir"],
                    "gsim": [r for r in results["perfstat"] if r["side"] == "gsim"]}
        summary["perfstat"] = summarize(per_side, MAIN_EVENTS)
    if results["nodiff"]:
        per_side = {"ir": [r for r in results["nodiff"] if r["side"] == "ir"],
                    "gsim": [r for r in results["nodiff"] if r["side"] == "gsim"]}
        model = summarize(per_side, MAIN_EVENTS)
        if "perfstat" in summary and "ratio" in summary["perfstat"]:
            full_ir = summary["perfstat"]["ir"]["means"]["instructions:u"]
            full_gsim = summary["perfstat"]["gsim"]["means"]["instructions:u"]
            model["framework_share"] = {
                "ir": 1.0 - model["ir"]["means"]["instructions:u"] / full_ir,
                "gsim": 1.0 - model["gsim"]["means"]["instructions:u"] / full_gsim}
        summary["nodiff"] = model
    if results["icache"]:
        summary["icache"] = {r["side"]: r["counts"] for r in results["icache"]}
    if results["record"]:
        summary["record"] = {r["side"]: {"class_shares": r["class_shares"],
                                         "reported_share": r["reported_share"],
                                         "top_functions": r["top_functions"]}
                             for r in results["record"]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
