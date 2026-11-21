"""TNO0026: timed user-mode counters and separate sampling of the DPI-aligned XiangShan models."""
import argparse
import csv
import os
from pathlib import Path
import platform
import resource
import subprocess
import time

from armor_xs_pgo_measure import Baseline, IMAGES, LLVM, LOCK, NEMU, WINDOW, measurement_lock
from grhsim_numa import inspect_locality, locality_errors
from grhsim_single_baseline import cpu_counters, idle_percent, parse_run, save
from xiangshan_cv32_ablation_measure import read, signature

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
OUT = BUILD / "armor-xs-gap-current-v1"
DEFAULT = BUILD / "armor-xs-mode-defaults-v1"
MATCHED = BUILD / "armor-gsim-gap-v1/pgo/gsim-nodpi"
BINS = {"gs_off": MATCHED / "off/emu", "gs_pgo": MATCHED / "use/emu",
        "gr_off": DEFAULT / "ordinary/build/emu", "gr_pgo": DEFAULT / "pgo/build/emu",
        "layout": OUT / "control/build/emu"}
ORDERS = [("gr_off", "gs_off", "gs_pgo", "gr_pgo", "layout"),
          ("layout", "gs_off", "gr_pgo", "gr_off", "gs_pgo"),
          ("gr_pgo", "gs_pgo", "layout", "gs_off", "gr_off"),
          ("gs_pgo", "gr_off", "gr_pgo", "layout", "gs_off")]
GROUPS = [
    ("branches", "branch-misses", "ex_ret_ops"),
    ("de_no_dispatch_per_slot.no_ops_from_frontend", "ic_cache_fill_l2", "ic_cache_fill_sys"),
    ("de_no_dispatch_per_slot.backend_stalls", "L1-dcache-loads", "L1-dcache-load-misses"),
    ("ex_ret_cond", "bp_l1_tlb_miss_l2_tlb_miss.all", "ls_any_fills_from_sys.dram_io_near"),
]
PERIOD = {"cycles": 4000003, "instructions": 4000019, "branch-misses": 10007}


def expected(label, wl):
    if label.startswith("gs"):
        return read(BUILD / "armor-xs-pgo-v1/gsim/verify/result.json")["workloads"][wl]["signature"]
    mode = "ordinary" if label == "gr_off" else "pgo"
    return read(DEFAULT / "verify" / mode / wl / "result.json")["signature"]


def run_one(p, wl, label, number, folder):
    cpu = p["cpu"]
    siblings = p["siblings"]
    folder.mkdir()
    events = ["cycles", "instructions", *GROUPS[number - 1]] if number else []
    if number:
        perf = ["perf", "stat", "--no-big-num", "-x,", "-e", ",".join(e + ":u" for e in events),
                "-o", str(folder / "perf.csv")]
    else:
        perf = ["perf", "record", "--no-buildid", "-o", str(folder / "perf.data")]
        for event, period in PERIOD.items():
            perf += ["-e", f"{event}/period={period}/u"]
    index = p["base"].index(str(p["binary"]))
    command = p["base"][:index] + perf + ["--", "sh", "-c", 'exec "$@" 2>&1', "sh",
                                       *p["base"][index:], "-C", str(WINDOW)]
    save(folder / "command.json", command)
    for _ in range(120):
        before = cpu_counters(siblings)
        time.sleep(2)
        if min(idle_percent(before, cpu_counters(siblings)).values()) >= 98:
            break
    else:
        raise RuntimeError("SMT busy before run")
    before = cpu_counters(siblings)
    seen = set()
    locations = []
    with (folder / "emu.log").open("w") as stream, (folder / "perf.log").open("w") as perf_log:
        start = time.monotonic()
        proc = subprocess.Popen(command, cwd=p["binary"].parent, env=dict(p["runtime"], LC_ALL="C"),
                                stdout=stream, stderr=perf_log)
        while True:
            try:
                proc.wait(timeout=3)
                break
            except subprocess.TimeoutExpired:
                pass
            children = Path(f"/proc/{proc.pid}/task/{proc.pid}/children")
            try:
                for pid in children.read_text().split():
                    task = Path("/proc") / pid
                    if (task / "exe").resolve() != p["binary"]:
                        continue
                    assert os.sched_getaffinity(int(pid)) == {cpu}
                    assert len(list((task / "task").iterdir())) == 1
                    assert int((task / "personality").read_text(), 16) & 0x40000
                    maps = (task / "maps").read_text()
                    loc = inspect_locality(maps, (task / "numa_maps").read_text(), p["plan"])
                    if not locations:
                        (folder / "maps").write_text(maps)
                    locations.append(loc)
                    seen.update(loc["seen_files"])
            except (FileNotFoundError, ProcessLookupError):
                pass
        wall = time.monotonic() - start
    idle = idle_percent(before, cpu_counters(siblings))
    if proc.returncode:
        raise RuntimeError(f"perf/emu failed at {folder}")
    if min(v for c, v in idle.items() if c != cpu) < 98:
        raise RuntimeError("SMT busy during run")
    required = {f["destination"] for f in p["plan"]["files"] if f["role"] in ("binary", "library", "reference")}
    if not locations or not required.issubset(seen) or any(locality_errors(loc, 1) for loc in locations):
        save(folder / "bad-locality.json", locations)
        raise RuntimeError(f"invalid runtime placement at {folder}")
    row = parse_run((folder / "emu.log").read_text(), WINDOW)
    if signature(row) != expected(label, wl):
        raise RuntimeError(f"endpoint mismatch at {folder}")
    counts, running = {}, {}
    if events:
        with (folder / "perf.csv").open() as stream:
            for f in csv.reader(stream):
                if len(f) > 4 and f[2].removesuffix(":u") in events:
                    event = f[2].removesuffix(":u")
                    running[event] = float(f[4])
                    if running[event] < 98:
                        raise RuntimeError(f"multiplexed counters at {folder}")
                    counts[event] = int(f[0])
        if set(counts) != set(events):
            raise ValueError(counts)
    row.update(external_wall_s=wall, counts=counts, counter_running_pct=running, sibling_idle=idle, placements=len(locations),
               binary=p["original_binary"], path=str(folder.relative_to(OUT)))
    save(folder / "sample.json", row)
    print(wl, label, folder.name, round(wall, 2), flush=True)
    return row


def main():
    assert platform.node().split(".")[0] == "node030"
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    with measurement_lock(LOCK, wait=True):
        root = OUT / "measurement"
        root.mkdir(exist_ok=True, parents=True)
        session = root / ("session-" + str(time.time_ns()))
        session.mkdir()
        rows_file = root / "rounds.json"
        rows = read(rows_file) if rows_file.exists() else {w: [] for w in IMAGES}
        prepared = {}
        for number, order in enumerate(ORDERS, 1):
            workloads = list(IMAGES) if number % 2 else list(reversed(IMAGES))
            for wl in workloads:
                if len(rows[wl]) >= number:
                    continue
                for label in order:
                    if (wl, label) in prepared:
                        continue
                    opts = argparse.Namespace(output=session / wl / label, binary=BINS[label],
                        simulator="gsim" if label.startswith("gs") else "grhsim", compiler=LLVM / "clang++",
                        cpu=96, cycles=WINDOW, jobs=1, repeats=4, tools_dir=None, sim_primitives="none",
                        image=IMAGES[wl], nemu=NEMU, skip_idle_check=False)
                    p = Baseline(opts).prepare_measurement()
                    prepared[wl, label] = p
                    if rows[wl] and rows[wl][0][label]["binary"] != p["original_binary"]:
                        raise ValueError("binary changed across sessions")
                    for retry in range(100):
                        try:
                            run_one(p, wl, label, 0, p["directory"] / f"profile-{retry}")
                            break
                        except RuntimeError as err:
                            if "SMT busy" not in str(err):
                                raise
                    else:
                        raise RuntimeError("could not warm up")
                for retry in range(100):
                    result = {"round": number, "order": order}
                    try:
                        for label in order:
                            p = prepared[wl, label]
                            result[label] = run_one(p, wl, label, number, p["directory"] / f"r{number}-{retry}")
                    except RuntimeError as err:
                        if "SMT busy" not in str(err) and "multiplexed counters" not in str(err):
                            raise
                        continue
                    rows[wl].append(result)
                    save(rows_file, rows)
                    break
                else:
                    raise RuntimeError("could not complete paired block")


if __name__ == "__main__":
    main()
