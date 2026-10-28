#!/usr/bin/env python3
"""Build and measure XiangShan's native Verilator thread scaling."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import statistics
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "build/xs_native_verilator_scaling_20261012"
XS = REPO / "testcase/xiangshan"
LLVM = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin")
VERILATOR = Path("/nfs/home/tanghaojin/verilator/bin/verilator")
THREADS = (1, 2, 4, 8, 16, 32)
ASSIGNMENTS = {"node030": (1, 8), "node031": (2, 16), "node032": (4, 32)}
IMAGE = XS / "ready-to-run/coremark-2-iteration.bin"
NEMU = XS / "ready-to-run/riscv64-nemu-interpreter-so"
PRELOAD = REPO / ("build/repcut_grhsim_20260925/active_dispatch_20261003/"
                  "formal_zero_backend_perf_20261010/codepage_probe_once/codepage.so")
COLLAPSE_RETRY = OUT / "setup_tools/collapse_retry.so"
REFERENCES = {
    "repcut-v32": {
        "label": "RepCut Verilator 32", "short_label": "RepCut V32", "backend": "verilator",
        "source": REPO / "build/repcut_grhsim_20260925/clang23_threeway/verilator_o3/partitioned-emu/verilator-compile/emu",
        "sha256": "12ff6327e7fa4a4866974bfe6727821bebe6f9e46e8b2c9407482251d136958d",
    },
    "repcut-g32": {
        "label": "RepCut GrhSIM G 32", "short_label": "RepCut G32", "backend": "grhsim",
        "source": REPO / "build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/candidate/emu",
        "sha256": "203e9fb21f633ddc8f74115ebd9e9ac55438a9b07ec5e5d8bd7964fc4a6fe6e4",
    },
}
ARMS = {
    **{f"native-t{n:02d}": {"threads": n, "label": f"Native Verilator {n}",
                           "short_label": f"Native {n}", "backend": "verilator",
                           "layout": "native", "expected_os_threads": n,
                           "binary": OUT / f"t{n:02d}/emu"}
       for n in THREADS},
    **{name: {"threads": 32, "label": spec["label"], "short_label": spec["short_label"],
              "backend": spec["backend"], "layout": "repcut",
              "expected_os_threads": 63 if spec["backend"] == "verilator" else 32,
              "binary": OUT / f"controls/{name}/emu"} for name, spec in REFERENCES.items()},
}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def clean_environment() -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("PGO_", "WOLVRIX_", "WOLVI_", "XS_")) or key in (
            "LLVM_PROFILE_FILE", "LD_PRELOAD", "MAKEFLAGS", "MFLAGS",
            "EMU_PHASE_TIMING", "GRHSIM", "GSIM", "EMU_TRACE", "EMU_TRACE_ALL",
        ):
            env.pop(key)
    env["PATH"] = str(LLVM) + ":" + env.get("PATH", "")
    env["NOOP_HOME"] = str(XS)
    return env


def plan() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for label, source in {
        "rtl": REPO / "build/asc_counter_print_20260915/candidate_v4/rtl",
        "generated-src": XS / "build/generated-src",
    }.items():
        target = OUT / "inputs" / label
        if not target.exists():
            shutil.copytree(source, target)
    files = sorted(path for path in (OUT / "inputs").rglob("*") if path.is_file())
    inputs = [identity(path) for path in files]
    references = {}
    for name, spec in REFERENCES.items():
        source = identity(spec["source"])
        if source["sha256"] != spec["sha256"]:
            raise RuntimeError(f"{name}: reference binary changed from validated version")
        target = ARMS[name]["binary"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(spec["source"], target)
        frozen = identity(target)
        if frozen["sha256"] != source["sha256"]:
            raise RuntimeError(f"{name}: frozen binary mismatch")
        references[name] = {"source": source, "frozen": frozen, "label": spec["label"]}
    write_json(OUT / "plan.json", {
        "threads": THREADS, "build_assignments": ASSIGNMENTS, "build_jobs_per_host": 12,
        "simulation_host": "node030", "cpu_masks": {
            str(n): "96" if n == 1 else f"96-{95 + n}" for n in THREADS},
        "numa_node": 1, "cycles": 100000, "seed": 0,
        "compiler": str(LLVM / "clang++"), "verilator": str(VERILATOR),
        "recipe": "testcase/xiangshan/difftest: make emu (native Verilator)",
        "thread32_diagnostic": "-Wno-UNOPTTHREADS only; no scheduling or optimization change",
        "opt_fast": "Makefile default -O3", "opt_slow": "Makefile default -O0",
        "waveform": False, "pgo": False, "randomize": False,
        "chisel_db": False, "constantin": False, "difftest": True,
        "aslr": False, "codepage": "2MiB-aligned executable interior THP, same preload as GrhSIM",
        "inputs": inputs, "image": identity(IMAGE), "nemu": identity(NEMU),
        "source_rtl": str(REPO / "build/asc_counter_print_20260915/candidate_v4/rtl"),
        "reference_binaries": references, "arms": list(ARMS),
        "repcut_runtime": "N=K=32, host lane9/CPU105, 31 workers, all-spin, phase timing disabled",
        "parent_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "xiangshan_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=XS, text=True).strip(),
        "difftest_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=XS / "difftest", text=True).strip(),
    })
    print(f"Frozen {len(files)} input files; plan: {OUT / 'plan.json'}", flush=True)


def build(host: str, jobs: int) -> None:
    if socket.gethostname().split(".")[0] != host:
        raise RuntimeError(f"build assigned to {host}, running on {socket.gethostname()}")
    env = clean_environment()
    for threads in ASSIGNMENTS[host]:
        directory = OUT / f"t{threads:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        binary = directory / "emu"
        completed = directory / "build.json"
        if completed.exists() and binary.is_file():
            record = json.loads(completed.read_text())
            if record.get("status") == "pass" and identity(binary) == record["binary"]:
                print(f"[{host}] already built t{threads}", flush=True)
                continue
        command = [
            "make", "-C", str(XS / "difftest"), "emu", f"BUILD_DIR={directory}",
            f"GEN_CSRC_DIR={OUT / 'inputs/generated-src'}",
            f"GEN_VSRC_DIR={OUT / 'inputs/generated-src'}", f"RTL_DIR={OUT / 'inputs/rtl'}",
            f"SIM_TOP_V={OUT / 'inputs/rtl/SimTop.sv'}", "NUM_CORES=1", "RTL_SUFFIX=sv",
            f"EMU_THREADS={threads}", f"VM_BUILD_JOBS={jobs}", "EMU_RANDOMIZE=0",
            "WITH_CHISELDB=0", "WITH_CONSTANTIN=0", "EMU_TRACE=0", "EMU_SNAPSHOT=0",
            "EMU_COVERAGE=0", "GRHSIM=0", "GSIM=0", "WOLVRIX_PARTITIONED_PACKAGE_DIR=",
            f"CC={LLVM / 'clang'}", f"CXX={LLVM / 'clang++'}", f"VERILATOR={VERILATOR}",
        ]
        # This diagnostic only reports insufficient available parallelism; it does
        # not alter scheduling or generated code. Keep the requested 32-thread arm.
        if threads == 32:
            command.append("SIM_VFLAGS=+define+DIFFTEST -Wno-UNOPTTHREADS")
        command_path = directory / "build_command.json"
        previous_command = json.loads(command_path.read_text()) if command_path.exists() else None
        resuming = (directory / "verilator-compile/VSimTop.mk").is_file() and previous_command is not None
        if resuming and previous_command != command:
            if previous_command != command[:-1] or threads != 32:
                raise RuntimeError("cannot resume generated model with changed build settings")
        started_at = command_path.stat().st_mtime if resuming else time.time()
        write_json(command_path, command)
        print(f"[{host}] building t{threads}, jobs={jobs}", flush=True)
        with (directory / "build.log").open("a" if resuming else "w") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        elapsed = time.time() - started_at
        if result.returncode or not binary.is_file():
            raise RuntimeError(f"t{threads} build failed ({result.returncode}): {directory / 'build.log'}")
        model = (directory / "verilator-compile/VSimTop.cpp").read_text()
        if not re.search(r"VSimTop::threads\(\)\s*const\s*\{\s*return "
                         + str(threads) + r";\s*\}", model):
            raise RuntimeError(f"t{threads}: generated model thread count missing")
        record = {"status": "pass", "host": host, "threads": threads,
                  "jobs": jobs, "wall_s": elapsed, "binary": identity(binary),
                  "resumed": resuming, "generation_command": previous_command if resuming else command,
                  "command": command, "compiler": subprocess.check_output(
                      [str(LLVM / "clang++"), "--version"], text=True).splitlines()[0],
                  "verilator": subprocess.check_output([str(VERILATOR), "--version"], text=True).strip()}
        write_json(completed, record)
        print(f"[{host}] t{threads} PASS build_wall={elapsed:.3f}s", flush=True)


def one(pattern: str, text: str, cast=str):
    matches = re.findall(pattern, text, re.M)
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern!r}, found {len(matches)}")
    return cast(matches[0])


def parse_result(path: Path, cycles: int, layout: str = "native") -> dict:
    log = re.sub(r"\x1b\[[0-9;]*m", "", path.with_suffix(".log").read_text(errors="replace"))
    timing = path.with_suffix(".time").read_text()
    if re.search(r"HIT BAD TRAP|DIFFTEST.*FAIL|ABORT|Assertion.*failed|Segmentation fault", log, re.I):
        raise RuntimeError(f"negative diagnostic: {path}")
    signature = {
        "pc": one(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-f]+)", log),
        "instructions": one(r"instrCnt = (\d+), cycleCnt = \d+", log, int),
        "cycles": one(r"instrCnt = \d+, cycleCnt = (\d+)", log, int),
        "guest_cycles": one(r"Guest cycle spent: (\d+)", log, int),
    }
    expected = {100: {"pc": "0x0", "instructions": 0, "cycles": 96, "guest_cycles": 101},
                100000: {"pc": "0x80000cde" if layout == "native" else "0x80000c0c",
                         "instructions": 238535 if layout == "native" else 240349,
                         "cycles": 99996, "guest_cycles": 100001}}[cycles]
    if signature != expected:
        raise RuntimeError(f"functional signature: {signature} != {expected}")
    if cycles == 100000 and "Difftest enabled" not in log:
        raise RuntimeError("Difftest was not enabled")
    if one(r"Exit status: (\d+)$", timing, int) != 0:
        raise RuntimeError("nonzero timed exit status")
    mode, size, huge = one(r"^\[codepage\] PASS mode=(\w+) bytes=(\d+) anon_huge=(\d+) .*",
                          log, lambda groups: groups)
    if mode != "thp" or int(size) == 0 or size != huge:
        raise RuntimeError("code THP coverage incomplete")
    fields = one(r"Elapsed \(wall clock\) time .*: ([0-9:.]+)$", timing).split(":")
    wall = 0.0
    for field in fields:
        wall = wall * 60 + float(field)
    host = one(r"Host time spent: (\d+)ms", log, int) / 1000
    return {"host_s": host, "wall_s": wall, "guest_cycles_per_s": cycles / host,
            "user_s": one(r"User time \(seconds\): ([0-9.]+)$", timing, float),
            "system_s": one(r"System time \(seconds\): ([0-9.]+)$", timing, float),
            "rss_kib": one(r"Maximum resident set size \(kbytes\): (\d+)$", timing, int),
            "signature": signature, "code_thp_bytes": int(huge)}


class CodepageUnavailable(RuntimeError):
    pass


def sample(round_id: int, arm: str, cycles: int, env: dict) -> dict:
    for attempt in range(64):
        try:
            return sample_once(round_id, arm, cycles, env)
        except CodepageUnavailable:
            if attempt == 63:
                raise
            print(f"[retry init] {arm}: code THP allocation unavailable", flush=True)
            time.sleep(0.5)
    raise AssertionError("unreachable")


def sample_once(round_id: int, arm: str, cycles: int, env: dict) -> dict:
    spec = ARMS[arm]
    threads = spec["threads"]
    env = dict(env)
    if spec["layout"] == "repcut":
        env["XS_EMU_THREADS"] = "32"
        env["XS_REPCUT_STEP_TIMING"] = "0"
    cpus = "96" if threads == 1 else f"96-{95 + threads}"
    directory = OUT / "runs"
    directory.mkdir(exist_ok=True)
    name = f"r{round_id:02d}-{arm}-c{cycles}"
    path = directory / name
    binary = spec["binary"]
    command = ["/usr/bin/time", "-v", "-o", str(path.with_suffix(".time")),
               "taskset", "--cpu-list", cpus, "numactl", f"--physcpubind={cpus}",
               "--membind=1", "setarch", "x86_64", "-R", "/usr/bin/env",
               f"LD_PRELOAD={PRELOAD}:{COLLAPSE_RETRY}", "REPCUT_CODEPAGE_MODE=thp", str(binary),
               "-i", str(IMAGE), "--diff", str(NEMU), "-b", "0", "-e", "0", "-C", str(cycles)]
    print(f"[run] {name}, CPUs={cpus}", flush=True)
    start = time.monotonic()
    with path.with_suffix(".log").open("w") as log:
        process = subprocess.Popen(command, cwd=binary.parent, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        audits = []
        last_audit = 0.0
        audit_interval = 0.05 if cycles == 100 else 1.0
        while process.poll() is None:
            now = time.monotonic()
            if now - last_audit >= audit_interval:
                last_audit = now
                # Audit the launched executable and all its threads, not other users.
                pending = [process.pid]
                while pending:
                    pid = pending.pop()
                    try:
                        children = Path(f"/proc/{pid}/task/{pid}/children").read_text()
                        pending.extend(int(child) for child in children.split())
                        if Path(f"/proc/{pid}/exe").resolve() != binary.resolve():
                            continue
                        threads_status = []
                        for task in Path(f"/proc/{pid}/task").iterdir():
                            data = (task / "status").read_text()
                            allowed = one(r"^Cpus_allowed_list:\s*(.*)$", data)
                            for group in allowed.split(","):
                                ends = [int(value) for value in group.split("-")]
                                if min(ends) < 96 or max(ends) > 95 + threads:
                                    raise RuntimeError(f"thread escaped CPU budget: {allowed}")
                            stat_fields = (task / "stat").read_text().rsplit(")", 1)[1].split()
                            cpu = int(stat_fields[36])
                            if cpu < 96 or cpu > 95 + threads:
                                raise RuntimeError(f"thread observed outside CPU budget: {cpu}")
                            threads_status.append({"tid": int(task.name), "allowed_cpus": allowed,
                                                   "observed_cpu": cpu})
                        audits.append({"elapsed_s": now - start, "pid": pid, "tasks": threads_status})
                    except (FileNotFoundError, ProcessLookupError):
                        continue
            time.sleep(0.02 if cycles == 100 else 0.1)
    if process.returncode == 123:
        diagnostic = path.with_suffix(".log").read_text()
        if "[codepage] FAIL MADV_COLLAPSE: Cannot allocate memory" in diagnostic and "Guest cycle spent:" not in diagnostic:
            raise CodepageUnavailable(name)
    if process.returncode:
        raise RuntimeError(f"{name}: exit {process.returncode}")
    row = {"name": name, "round": round_id, "arm": arm, "label": spec["label"],
           "threads": threads, "cpus": cpus, "layout": spec["layout"],
           "cycles": cycles, **parse_result(path, cycles, spec["layout"])}
    if spec["layout"] == "repcut":
        runtime = json.loads(one(r"^\[runtime-config\] (\{.*\})$", path.with_suffix(".log").read_text()))
        expected_runtime = {"lanes": 32, "background_workers": 31, "host_cpu": 105,
                            "host_lane": 9, "host_participates": True,
                            "dispatch_kind": "per-lane-atomic-spin", "update_mode": "push",
                            "wait_policy": "all-spin", "part_cpus": list(range(96, 128)),
                            "worker_to_part": list(range(32))}
        if any(runtime.get(key) != value for key, value in expected_runtime.items()):
            raise RuntimeError(f"{name}: RepCut runtime configuration mismatch: {runtime}")
        row["runtime_config"] = runtime
    row["command"] = command
    row["runtime_env"] = {key: value for key, value in env.items() if key.startswith("XS_")}
    if cycles == 100000 and not audits:
        raise RuntimeError(f"{name}: no live thread audit")
    write_json(path.with_suffix(".audit.json"), audits)
    row["observed_thread_count_max"] = max((len(a["tasks"]) for a in audits), default=0)
    if cycles == 100000 and row["observed_thread_count_max"] != spec["expected_os_threads"]:
        raise RuntimeError(f"{name}: observed {row['observed_thread_count_max']} threads, expected {spec['expected_os_threads']}")
    write_json(path.with_suffix(".json"), row)
    print(f"[pass] {name}: wall={row['wall_s']:.3f}s host={row['host_s']:.3f}s", flush=True)
    return row


def measure(rounds: int, resume: bool = False) -> None:
    if socket.gethostname().split(".")[0] != "node030":
        raise RuntimeError("performance measurement must run on node030")
    env = clean_environment()
    artifacts = {arm: identity(spec["binary"]) for arm, spec in ARMS.items()}
    inputs_before = {"image": identity(IMAGE), "nemu": identity(NEMU), "preload": identity(PRELOAD)}
    planned = [(round_id, arm) for round_id in range(1, rounds + 1)
               for arm in (tuple(ARMS) if round_id % 2 else tuple(reversed(ARMS)))]
    rows = json.loads((OUT / "runs.json").read_text()) if resume else []
    if resume:
        if [(r["round"], r["arm"]) for r in rows] != planned[:len(rows)]:
            raise RuntimeError("saved measurements are not a prefix of this schedule")
        provenance = json.loads((OUT / "plan.json").read_text())
        for key in ("image", "nemu"):
            if inputs_before[key] != provenance[key]:
                raise RuntimeError(f"{key}: input changed before resume")
        for arm, spec in ARMS.items():
            expected = (json.loads((OUT / f"t{spec['threads']:02d}/build.json").read_text())["binary"]
                        if spec["layout"] == "native" else provenance["reference_binaries"][arm]["frozen"])
            if artifacts[arm] != expected:
                raise RuntimeError(f"{arm}: executable changed before resume")
        for row in rows:
            parsed = parse_result(OUT / "runs" / row["name"], 100000, row["layout"])
            if any(row[key] != value for key, value in parsed.items()):
                raise RuntimeError("saved sample changed")
        print(f"[resume] retaining {len(rows)} validated samples", flush=True)
    else:
        for arm in ARMS:
            sample(0, arm, 100, env)
    # Every odd/even pair measures forward and reverse order; each arm is freshly run.
    for round_id in range(1, rounds + 1):
        order = tuple(ARMS) if round_id % 2 else tuple(reversed(ARMS))
        for arm in order:
            if (round_id, arm) in [(r["round"], r["arm"]) for r in rows]:
                continue
            rows.append(sample(round_id, arm, 100000, env))
            write_json(OUT / "runs.json", rows)
    after = {arm: identity(spec["binary"]) for arm, spec in ARMS.items()}
    inputs_after = {"image": identity(IMAGE), "nemu": identity(NEMU), "preload": identity(PRELOAD)}
    if after != artifacts or inputs_after != inputs_before:
        raise RuntimeError("input or executable identity changed during measurement")
    grouped = {arm: [row for row in rows if row["arm"] == arm] for arm in ARMS}
    summary = []
    for arm, spec in ARMS.items():
        n = spec["threads"]
        group = grouped[arm]
        summary.append({"arm": arm, "label": spec["label"], "short_label": spec["short_label"],
                        "backend": spec["backend"], "layout": spec["layout"],
                        "threads": n, "cpu_mask": group[0]["cpus"], "samples": len(group),
                        "wall_mean_s": statistics.mean(r["wall_s"] for r in group),
                        "wall_median_s": statistics.median(r["wall_s"] for r in group),
                        "wall_min_s": min(r["wall_s"] for r in group),
                        "wall_max_s": max(r["wall_s"] for r in group),
                        "host_mean_s": statistics.mean(r["host_s"] for r in group),
                        "host_median_s": statistics.median(r["host_s"] for r in group),
                        "build_wall_s": json.loads((OUT / f"t{n:02d}/build.json").read_text())["wall_s"]
                        if spec["layout"] == "native" else None})
    for row in summary:
        row["wall_speedup"] = summary[0]["wall_median_s"] / row["wall_median_s"]
        row["host_cycles_per_s"] = 100000 / row["host_median_s"]
        row["host_instructions_per_s"] = grouped[row["arm"]][0]["signature"]["instructions"] / row["host_median_s"]
        row["parallel_efficiency"] = row["wall_speedup"] / row["threads"] if row["layout"] == "native" else None
        row["wall_paired_speedup_median"] = statistics.median(
            control["wall_s"] / candidate["wall_s"]
            for control, candidate in zip(grouped["native-t01"], grouped[row["arm"]]))
    write_json(OUT / "summary.json", {"status": "pass", "rows": summary,
               "artifacts": artifacts, "inputs": inputs_before, "rounds": rounds,
               "schedule": "forward/reverse paired rounds", "runs": rows})
    with (OUT / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    report(summary, rows)
    print(json.dumps(summary, indent=2), flush=True)


def analyze() -> None:
    """Validate completed raw measurements and regenerate the standalone report."""
    path = OUT / "summary.json"
    data = json.loads(path.read_text())
    if data["status"] != "pass" or len(data["runs"]) != data["rounds"] * len(ARMS):
        raise RuntimeError("measurement is incomplete")
    for arm, spec in ARMS.items():
        if identity(spec["binary"]) != data["artifacts"][arm]:
            raise RuntimeError(f"{arm}: executable changed after measurement")
    grouped = {arm: [r for r in data["runs"] if r["arm"] == arm] for arm in ARMS}
    for arm, group in grouped.items():
        if sorted(r["round"] for r in group) != list(range(1, data["rounds"] + 1)):
            raise RuntimeError(f"{arm}: missing or duplicated round")
    for row in data["runs"]:
        prefix = OUT / "runs" / row["name"]
        parsed = parse_result(prefix, 100000, row["layout"])
        if any(row[key] != value for key, value in parsed.items()):
            raise RuntimeError(f"{row['name']}: raw log differs from saved measurement")
        audits = json.loads(prefix.with_suffix(".audit.json").read_text())
        if not audits or max(len(a["tasks"]) for a in audits) != ARMS[row["arm"]]["expected_os_threads"]:
            raise RuntimeError(f"{row['name']}: incomplete thread audit")
        for audit in audits:
            for task in audit["tasks"]:
                if not 96 <= task["observed_cpu"] <= 95 + row["threads"]:
                    raise RuntimeError(f"{row['name']}: CPU outside budget")
                for group in task["allowed_cpus"].split(","):
                    ends = [int(value) for value in group.split("-")]
                    if min(ends) < 96 or max(ends) > 95 + row["threads"]:
                        raise RuntimeError(f"{row['name']}: affinity outside budget")
        row["codepage_setup_s"] = one(r"^\[codepage\] PASS .* setup_s=([0-9.]+) pid=\d+$",
                                     prefix.with_suffix(".log").read_text(), float)
    for row in data["rows"]:
        row["host_instructions_per_s"] = grouped[row["arm"]][0]["signature"]["instructions"] / row["host_median_s"]
        row["codepage_setup_median_s"] = statistics.median(r["codepage_setup_s"] for r in grouped[row["arm"]])
        row["observed_os_threads"] = max(r["observed_thread_count_max"] for r in grouped[row["arm"]])
    comparisons = []
    for baseline, candidate in (("native-t32", "repcut-v32"),
                                ("native-t32", "repcut-g32"),
                                ("repcut-v32", "repcut-g32")):
        ratios = [c["wall_s"] / b["wall_s"] for b, c in zip(grouped[baseline], grouped[candidate])]
        comparisons.append({"baseline": baseline, "candidate": candidate,
                            "paired_wall_reduction_median_pct": (1 - statistics.median(ratios)) * 100,
                            "candidate_faster_rounds": sum(value < 1 for value in ratios)})
    data["paired_comparisons"] = comparisons
    data["analysis_script"] = identity(Path(__file__))
    data["codepage_preprocessing"] = {"primary": identity(PRELOAD), "collapse_retry": identity(COLLAPSE_RETRY),
        "samples_without_retry_library": [r["name"] for r in data["runs"]
             if not any(str(COLLAPSE_RETRY) in arg for arg in r["command"])]}
    write_json(path, data)
    with (OUT / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data["rows"][0]))
        writer.writeheader()
        writer.writerows(data["rows"])
    report(data["rows"], data["runs"])
    print(json.dumps({"rows": data["rows"], "paired_comparisons": comparisons}, indent=2), flush=True)


def report(summary: list[dict], rows: list[dict]) -> None:
    payload = json.dumps({"summary": summary, "runs": rows}, ensure_ascii=False)
    html = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XiangShan 原生 Verilator 线程扩展与 RepCut 对照</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0b1220;color:#e2e8f0}
body{max-width:1120px;margin:32px auto;padding:0 20px}h1{font-size:25px;margin-bottom:8px}
p{color:#a9bad2;line-height:1.7}.panel{background:#131e30;border:1px solid #2a3b55;border-radius:12px;padding:20px;margin:20px 0}
select,button{background:#1e3049;color:#edf2fa;border:1px solid #415674;border-radius:6px;padding:8px}
svg{width:100%;height:auto}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:10px 8px;border-bottom:1px solid #2a3b55}th:first-child,td:first-child{text-align:left}
a{color:#7dd3fc}.hint{font-size:13px}.point{fill:#fbbf24;opacity:.85}.bar{fill:#38bdf8}.bar:hover{opacity:.7}.repcut-v{fill:#a78bfa}.repcut-g{fill:#34d399}
</style><body><h1>XiangShan 原生 Verilator：1–32 线程与 RepCut 对照</h1>
<p>node030 · CPU96 起连续使用 N 个物理核 · C=100000 · 单 guest 核 Difftest<br>
Verilator 5.048 / Clang 23.1.2 · 无波形/PGO · NUMA1 · ASLR 关闭 · 代码 THP · 关闭阶段采样</p>
<p class="hint">蓝色为未分区 RTL 的原生 Verilator，采用标准 Makefile -O3/-O0，不加 -march=native。
紫色为现成 RepCut Verilator/O3；绿色为当前累计优化的 GrhSIM 正式候选 G（-O3 -march=native）。
两个 RepCut 版本均 N=K=32、Host105 参与、31 worker、all-spin。这是各条完整实现的端点比较。</p>
<div class="panel"><label>展示指标：<select id="metric">
<option value="wall_median_s">walltime 中位数 / s</option><option value="host_median_s">Host 中位数 / s</option>
<option value="wall_mean_s">walltime 均值 / s</option><option value="host_mean_s">Host 均值 / s</option>
<option value="host_cycles_per_s">仿真速度 / guest cycles/s</option><option value="wall_speedup">相对 Native 1 线程加速比</option>
<option value="host_instructions_per_s">指令速度 / guest instructions/s</option>
<option value="parallel_efficiency">原生并行效率</option><option value="build_wall_s">原生构建 walltime / s</option>
</select></label><label style="margin-left:20px"><input type="checkbox" id="points" checked>显示每次运行</label>
<label style="margin-left:20px">比较范围：<select id="scope"><option value="all">全部版本</option><option value="native">原生线程扩展</option><option value="32">仅三个 32 线程版本</option></select></label>
<svg id="chart" viewBox="0 0 1040 440" role="img" aria-label="各线程档位的性能柱状图"></svg>
<p class="hint">时间默认展示中位数，可切换均值；黄色点为各次样本，鼠标悬停查看数值。编译时间为每档一次完整生成和编译。
正反顺序交错测量，全部功能通过样本均保留。</p></div>
<div class="panel"><table><thead><tr><th>版本 / CPU</th><th>walltime / s</th><th>walltime 范围 / s</th><th>Host / s</th><th>速度 / kcycles/s</th><th>加速比</th><th>构建 / s</th></tr></thead><tbody id="table"></tbody></table></div>
<p class="hint">原生 Verilator worker 共享整档 CPU affinity；RepCut 的仿真线程各自绑核。
原生 32 线程生成时有 UNOPTTHREADS 诊断，仅容忍该诊断，未改变默认调度。
所有 C100000 样本通过 Difftest；原生提交 238535 条指令，RepCut 提交 240349 条，
两侧固定周期窗口的提交数相差约 0.75%，故另提供指令速度。RepCut V32 的 31 个附属库线程休眠，
实际仿真仍使用 Host+31 个 RepCut worker，全部 OS 线程均限制在 CPU96–127。</p>
<p><a href="summary.json">完整数据 JSON</a> · <a href="summary.csv">汇总 CSV</a> · <a href="plan.json">输入和构建配置</a></p>
<script>const DATA=__DATA__;
const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
function el(tag,attrs,text){const x=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))x.setAttribute(k,v);if(text!==undefined)x.textContent=text;return x}
function draw(){const metric=$('metric').value,svg=$('chart');svg.replaceChildren();
const selected=DATA.summary.filter(r=>Number.isFinite(r[metric])&&($('scope').value==='all'||($('scope').value==='native'?r.layout==='native':r.threads===32)));
const raw=r=>['wall_median_s','wall_mean_s'].includes(metric)?r.wall_s:['host_median_s','host_mean_s'].includes(metric)?r.host_s:metric==='host_cycles_per_s'?r.guest_cycles_per_s:metric==='host_instructions_per_s'?r.signature.instructions/r.host_s:null;
const show=$('points').checked&&['wall_median_s','wall_mean_s','host_median_s','host_mean_s','host_cycles_per_s','host_instructions_per_s'].includes(metric);
const rawRuns=DATA.runs.filter(r=>selected.some(a=>a.arm===r.arm));
const max=Math.max(...selected.map(r=>r[metric]),...(show?rawRuns.map(raw):[]))*1.15;
const y=v=>370-v/max*320;for(let i=0;i<=5;i++){const value=max*i/5,py=y(value);svg.append(el('line',{x1:80,y1:py,x2:1010,y2:py,stroke:'#2a3b55'}));svg.append(el('text',{x:68,y:py+5,'text-anchor':'end',fill:'#a9bad2','font-size':13},value<10?value.toFixed(2):value.toFixed(0)))}
selected.forEach((r,i)=>{const x=100+i*920/selected.length,v=r[metric],bar=el('rect',{x,y:y(v),width:66,height:370-y(v),rx:4,class:'bar '+(r.arm==='repcut-v32'?'repcut-v':r.arm==='repcut-g32'?'repcut-g':'')});bar.append(el('title',{},`${r.label}，CPU ${r.cpu_mask}\\n${$('metric').selectedOptions[0].text}: ${v.toFixed(4)}`));svg.append(bar);svg.append(el('text',{x:x+33,y:y(v)-10,'text-anchor':'middle',fill:'#e2e8f0','font-size':14},v<10?v.toFixed(3):v.toFixed(1)));svg.append(el('text',{x:x+33,y:400,'text-anchor':'middle',fill:'#cbd5e1','font-size':12},r.short_label));if(show)DATA.runs.filter(a=>a.arm===r.arm).forEach((a,j)=>{const p=el('circle',{cx:x+10+j*9,cy:y(raw(a)),r:4,class:'point'});p.append(el('title',{},`${a.name}: ${raw(a).toFixed(4)}`));svg.append(p)})});}
$('table').innerHTML=DATA.summary.map(r=>`<tr><td>${r.short_label} / ${r.cpu_mask}</td><td>${r.wall_median_s.toFixed(3)}</td><td>${r.wall_min_s.toFixed(2)}–${r.wall_max_s.toFixed(2)}</td><td>${r.host_median_s.toFixed(3)}</td><td>${(r.host_cycles_per_s/1000).toFixed(2)}</td><td>${r.wall_speedup.toFixed(2)}×</td><td>${r.build_wall_s===null?'现成 binary':r.build_wall_s.toFixed(1)}</td></tr>`).join('');
$('metric').onchange=draw;$('points').onchange=draw;$('scope').onchange=draw;draw();
</script></body></html>"""
    (OUT / "native_verilator_scaling.html").write_text(html.replace("__DATA__", payload))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "build", "measure", "analyze"))
    parser.add_argument("--host", choices=tuple(ASSIGNMENTS))
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--resume", action="store_true", help="continue the same interrupted measurement window")
    args = parser.parse_args()
    if args.action == "plan":
        plan()
    elif args.action == "build":
        if not args.host:
            parser.error("build requires --host")
        build(args.host, args.jobs)
    elif args.action == "measure":
        measure(args.rounds, args.resume)
    else:
        analyze()


if __name__ == "__main__":
    main()
