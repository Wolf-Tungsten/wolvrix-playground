#!/usr/bin/env python3
"""Collect gsim native runtime-profile calibers on the 100k CoreMark caliber and
build the two-sided dynOps factor decomposition (changes x act/change x work).

The gsim side uses the in-tree runtime profile feature (GSIM_EMIT_RUNTIME_PROFILE
codegen option, EMU_RUNTIME_PROFILE harness chain, GSIM_SUPERNODE_TSV fire-count
output). Runs go through the project Make run target with the environment
injected through XS_EMU_PREFIX (the profile_grhsim_ir.py pattern); the anchored
gsim builds are never touched. The ir side is parsed from an archived
dynamic-stats log ([grhsim-dyn] lines); dynOps itself stays locked by the
source-identity transmission chain and is passed in as an archived constant.

Outputs: summary.md + summary.json with the factor table, per-super Pareto and
super-class attribution.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import statistics
import subprocess
import time

from benchmark_grhsim_ir import FAILURE, evict_page_cache
from grhsim_native_work_compare import endpoint_fields

PROFILE_LINE = re.compile(
    r"\[GSIM_RUNTIME_PROFILE\] active_supernodes=(\d+) nodes=(\d+) "
    r"ref_enodes=(\d+) non_ref_enodes=(\d+) total_enodes=(\d+)")
FIRE_ROW = re.compile(r"^(\d+)\t(\d+)\s*$")
WEIGHT_ROW = re.compile(r"runtimeProfile(Node|RefENode|NonRefENode)Weight\[(\d+)\] = (\d+);")
IR_TOTALS = re.compile(r"^\[grhsim-dyn\] totals (.*)$", re.M)
IR_KIND = re.compile(r"^\[grhsim-dyn\] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)\s*$", re.M)
IR_SN = re.compile(r"^\[grhsim-dyn\] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)\s*$", re.M)


# --- pure parsers (unit-tested) ---

def parse_profile_line(text: str) -> dict[str, int]:
    matches = PROFILE_LINE.findall(text)
    if not matches:
        raise ValueError("missing [GSIM_RUNTIME_PROFILE] line")
    if len(matches) > 1 and matches.count(matches[0]) != len(matches):
        raise ValueError("conflicting [GSIM_RUNTIME_PROFILE] lines")
    active, nodes, ref, nonref, total = (int(v) for v in matches[0])
    if total != ref + nonref:
        raise ValueError("total_enodes != ref_enodes + non_ref_enodes")
    return {"active_supernodes": active, "nodes": nodes, "ref_enodes": ref,
            "non_ref_enodes": nonref, "total_enodes": total}


def parse_fire_tsv(text: str) -> dict[int, int]:
    rows: dict[int, int] = {}
    for line in text.splitlines():
        if not line or line.startswith("supernode_id"):
            continue
        match = FIRE_ROW.match(line)
        if not match:
            raise ValueError(f"malformed fire tsv row: {line!r}")
        rows[int(match.group(1))] = int(match.group(2))
    if not rows:
        raise ValueError("empty fire tsv")
    return rows


def parse_static_tsv(text: str) -> dict[int, dict[str, int]]:
    rows: dict[int, dict[str, int]] = {}
    for line in text.splitlines():
        if not line or line.startswith("supernode_id"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError(f"malformed static tsv row: {line!r}")
        sid = int(fields[0])
        rows[sid] = {"n_comp": int(fields[2]), "n_src": int(fields[3]),
                     "n_sink": int(fields[4]), "n_const": int(fields[5]),
                     "a_succ": int(fields[6])}
    if not rows:
        raise ValueError("empty static tsv")
    return rows


def parse_weight_assignments(text: str) -> dict[int, dict[str, int]]:
    weights: dict[int, dict[str, int]] = {}
    for kind, sid, value in WEIGHT_ROW.findall(text):
        key = {"Node": "nodes", "RefENode": "ref_enodes",
               "NonRefENode": "non_ref_enodes"}[kind]
        weights.setdefault(int(sid), {})[key] = int(value)
    if not weights:
        raise ValueError("no runtimeProfile weight assignments")
    for sid, row in weights.items():
        if set(row) != {"nodes", "ref_enodes", "non_ref_enodes"}:
            raise ValueError(f"incomplete weight row for super {sid}")
    return weights


def parse_stats_json(data: dict) -> dict[str, int]:
    out = {}
    for key in ("supernodes", "active_source_nodes", "always_active_supernodes",
                "activation_edges", "unique_activation_edges"):
        if key not in data or not isinstance(data[key], int):
            raise ValueError(f"stats json missing int field {key}")
        out[key] = data[key]
    return out


def parse_ir_dyn_log(text: str) -> dict[str, int]:
    totals = IR_TOTALS.search(text)
    if not totals:
        raise ValueError("missing [grhsim-dyn] totals line")
    counters = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", totals.group(1))}
    kinds = IR_KIND.findall(text)
    if not kinds:
        raise ValueError("missing [grhsim-dyn] kind lines")
    counters["boundary_wr"] = sum(int(wr) for _, wr, _, _ in kinds)
    counters["boundary_chg"] = sum(int(ch) for _, _, ch, _ in kinds)
    counters["boundary_silent"] = sum(int(sl) for _, _, _, sl in kinds)
    sns = IR_SN.findall(text)
    if not sns:
        raise ValueError("missing [grhsim-dyn] sn lines")
    counters["sn_activations"] = sum(int(act) for _, act, _, _, _ in sns)
    counters["sn_bodies"] = sum(int(body) for _, _, body, _, _ in sns)
    return counters


# --- factor decomposition (pure, unit-tested) ---

def factor_table(gsim_profile: dict[str, int], gsim_statics: dict[str, int],
                 ir: dict[str, int], guest_cycles: int, ir_dyn_ops: int,
                 ir_compute_instr_per_cycle: float, gsim_model_instr_per_cycle: float,
                 gsim_enodes_per_super: float, ir_ops_per_body: float) -> dict:
    if guest_cycles <= 0:
        raise ValueError("guest_cycles must be positive")
    g_act = gsim_profile["active_supernodes"] / guest_cycles
    g_node = gsim_profile["nodes"] / guest_cycles
    g_enode = gsim_profile["total_enodes"] / guest_cycles
    consumers_per_value = gsim_statics["unique_activation_edges"] / gsim_statics["active_source_nodes"]
    always_fires = gsim_statics["always_active_supernodes"]
    g_chg = (g_act - always_fires) / consumers_per_value
    if g_chg <= 0 or g_act <= 0 or g_enode <= 0:
        raise ValueError("gsim profile counters must be positive")
    ir_act = ir["sn_activations"] / guest_cycles
    ir_body = ir["sn_bodies"] / guest_cycles
    ir_chg = ir["boundary_chg"] / guest_cycles
    ir_dynops = ir_dyn_ops / guest_cycles
    g_work = g_enode / g_act
    ir_work = ir_dynops / ir_body
    g_instr = gsim_model_instr_per_cycle / g_enode
    ir_instr = ir_compute_instr_per_cycle / ir_dynops
    compute_instr_ratio = ir_compute_instr_per_cycle / gsim_model_instr_per_cycle
    table = {
        "guest_cycles": guest_cycles,
        "gsim": {"activations_per_cycle": g_act,
                 "nodes_per_cycle": g_node,
                 "enodes_per_cycle": g_enode,
                 "changes_per_cycle_derived": g_chg,
                 "act_per_change_derived": g_act / g_chg,
                 "consumers_per_value": consumers_per_value,
                 "enodes_per_activation": g_work,
                 "instr_per_enode": g_instr},
        "ir": {"activations_per_cycle": ir_act,
               "bodies_per_cycle": ir_body,
               "dynops_per_cycle": ir_dynops,
               "changes_per_cycle": ir_chg,
               "bodies_per_change": ir_body / ir_chg,
               "dynops_per_body": ir_work,
               "instr_per_dynop": ir_instr,
               "boundary_writes_per_cycle": ir["boundary_wr"] / guest_cycles},
        "ratio": {"changes": ir_chg / g_chg,
                  "work_per_activation": ir_work / g_work,
                  "dynamic_work": ir_dynops / g_enode,
                  "instr_per_work": ir_instr / g_instr,
                  "compute_instr": compute_instr_ratio},
    }
    table["ratio"]["closure_instr"] = (table["ratio"]["dynamic_work"]
                                       * table["ratio"]["instr_per_work"]
                                       / compute_instr_ratio)
    return table


def super_pareto(fires: dict[int, int], weights: dict[int, dict[str, int]],
                 statics: dict[int, dict[str, int]], guest_cycles: int,
                 top: int = 20) -> dict:
    rows = []
    sink_fires = 0
    detect_compares = 0
    total_enode_work = 0
    for sid, fire in fires.items():
        weight = weights.get(sid, {})
        enodes = weight.get("ref_enodes", 0) + weight.get("non_ref_enodes", 0)
        work = fire * enodes
        total_enode_work += work
        static = statics.get(sid, {})
        detect_compares += fire * static.get("a_succ", 0)
        if static.get("n_sink", 0) > 0:
            sink_fires += fire
        rows.append({"supernode": sid, "fires": fire, "enode_weight": enodes,
                     "enode_work": work, "a_succ": static.get("a_succ", 0),
                     "n_sink": static.get("n_sink", 0)})
    rows.sort(key=lambda row: -row["enode_work"])
    total_fires = sum(fires.values())
    return {"top": rows[:top],
            "total_fires": total_fires,
            "total_enode_work": total_enode_work,
            "sink_fire_share": sink_fires / max(total_fires, 1),
            "detect_compares_per_cycle": detect_compares / guest_cycles}


# --- run orchestration (same watchdog pattern as grhsim_native_work_compare) ---

def run_diag(root: Path, output: Path, label: str, build: Path, fire_tsv: Path,
             expected_endpoint: list, cutoff: float, cpu: int) -> dict:
    directory = output / label
    directory.mkdir()
    evicted = evict_page_cache(build / "emu")
    prefix = [f"EMU_RUNTIME_PROFILE=1", f"GSIM_SUPERNODE_TSV={fire_tsv}",
              "taskset", "-c", str(cpu), "stdbuf", "-oL", "-eL"]
    command = ["make", "--no-print-directory", "run_xs_gsim_emu",
               f"XS_GSIM_BUILD={build}", f"XS_LOG_DIR={directory / 'logs'}",
               f"RUN_ID=no00008_rtprof_20260925_{label}",
               "XS_NUM_CORES=1", "XS_EMU_THREADS=1", "EMU_THREADS=1",
               "XS_SIM_MAX_CYCLE=100000", "XS_WAVEFORM=0", "XS_WAVEFORM_PATH=",
               "XS_COMMIT_TRACE=0", "XS_RAM_TRACE=0", "XS_PROGRESS_EVERY_CYCLES=0",
               f"XS_EMU_PREFIX={shlex.join(prefix)}"]
    (directory / "command.sh").write_text(shlex.join(command) + "\n")
    print(f"START {label}", flush=True)
    start = time.monotonic()
    log = directory / "make.log"
    killed = None
    env = dict(os.environ)
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
    if status or killed:
        reason = killed or "INVALID"
        raise RuntimeError(f"{label}: {reason}, make exit={status}; see {log}")
    parsed = endpoint_fields(log.read_text(errors="replace"), require_difftest=True)
    if list(parsed[:4]) != expected_endpoint:
        raise RuntimeError(f"{label}: INVALID endpoint {parsed[:4]}")
    if not fire_tsv.is_file():
        raise RuntimeError(f"{label}: fire tsv not produced: {fire_tsv}")
    print(f"DONE {label} Host={parsed[4]:.3f}s", flush=True)
    return {"label": label, "host_s": parsed[4], "endpoint": list(parsed[:4]),
            "evicted": evicted, "log": str(log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-build", type=Path, required=True,
                        help="rtprof build dir (build/xs/gsim-rtprof)")
    parser.add_argument("--anchor-model", type=Path, required=True,
                        help="anchored gsim-pgo model dir for stats-json consistency")
    parser.add_argument("--ir-dyn-log", type=Path, required=True,
                        help="archived [grhsim-dyn] emu log (current code state)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--cutoff", type=float, default=300.0)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--ir-dyn-ops", type=int, default=99479933605)
    parser.add_argument("--ir-compute-instr-per-cycle", type=float, default=3.843e6)
    parser.add_argument("--gsim-model-instr-per-cycle", type=float, default=1.926e6)
    parser.add_argument("--gsim-enodes-per-super", type=float, default=59.3)
    parser.add_argument("--ir-ops-per-body", type=float, default=110.01)
    parser.add_argument("--gsim-endpoint", default="238550,99998,100001,0x80000b40")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        parser.error("output must be a new directory")
    output.mkdir(parents=True)
    build = args.gsim_build.resolve()
    if not (build / "emu").is_file():
        parser.error(f"missing emu binary: {build / 'emu'}")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("CPU must be available")
    fields = args.gsim_endpoint.split(",")
    expected = [int(fields[0]), int(fields[1]), int(fields[2]), fields[3]]

    # model consistency gate: regenerated stats json must equal the anchored one
    regen_stats = build / "gsim-compile" / "model" / "SimTop_supernode_stats.json"
    anchor_stats = args.anchor_model.resolve() / "SimTop_supernode_stats.json"
    if regen_stats.read_bytes() != anchor_stats.read_bytes():
        raise RuntimeError(f"stats json mismatch: {regen_stats} vs {anchor_stats}")
    stats = parse_stats_json(json.loads(regen_stats.read_text()))
    static_tsv = build / "gsim-compile" / "model" / "SimTop_supernode_static.tsv"
    statics = parse_static_tsv(static_tsv.read_text())

    run_results = []
    profiles = []
    fires = []
    for i in range(1, args.runs + 1):
        fire_tsv = output / f"fire-{i}.tsv"
        result = run_diag(root, output, f"run{i}", build, fire_tsv, expected,
                          args.cutoff, args.cpu)
        run_results.append(result)
        log_text = Path(result["log"]).read_text(errors="replace")
        profiles.append(parse_profile_line(log_text))
        fires.append(parse_fire_tsv(fire_tsv.read_text()))
    if profiles.count(profiles[0]) != len(profiles) or any(f != fires[0] for f in fires[1:]):
        raise RuntimeError("non-deterministic runtime profile counters")
    profile = profiles[0]
    fire = fires[0]
    guest_cycles = run_results[0]["endpoint"][2]

    # weight assignments come from the regenerated model cpp (init function)
    model_dir = build / "gsim-compile" / "model"
    weight_text = ""
    for cpp in sorted(model_dir.glob("SimTop*.cpp")):
        chunk = cpp.read_text(errors="replace")
        if "runtimeProfileNodeWeight[" in chunk:
            weight_text += chunk
    weights = parse_weight_assignments(weight_text)

    ir = parse_ir_dyn_log(args.ir_dyn_log.read_text(errors="replace"))
    table = factor_table(profile, stats, ir, guest_cycles, args.ir_dyn_ops,
                         args.ir_compute_instr_per_cycle, args.gsim_model_instr_per_cycle,
                         args.gsim_enodes_per_super, args.ir_ops_per_body)
    pareto = super_pareto(fire, weights, statics, guest_cycles)

    summary = {"runs": run_results, "profile": profile, "stats": stats,
               "factor_table": table, "pareto": pareto,
               "ir_counters": ir}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    lines = ["# gsim runtime profile calibers (no00008)", ""]
    g, r, i = table["gsim"], table["ratio"], table["ir"]
    lines.append(f"guest_cycles={guest_cycles}")
    lines.append(f"M-gact  gsim activations/cycle = {g['activations_per_cycle']:.1f}")
    lines.append(f"M-gwork gsim nodes/cycle = {g['nodes_per_cycle']:.1f} "
                 f"enodes/cycle = {g['enodes_per_cycle']:.1f}")
    lines.append(f"M-gchg  gsim changes/cycle (derived) = {g['changes_per_cycle_derived']:.1f} "
                 f"(consumers/value {g['consumers_per_value']:.3f})")
    lines.append(f"gsim enodes/activation = {g['enodes_per_activation']:.2f} "
                 f"instr/enode = {g['instr_per_enode']:.3f}")
    lines.append(f"ir changes/cycle = {i['changes_per_cycle']:.1f} "
                 f"bodies/change = {i['bodies_per_change']:.3f} "
                 f"dynOps/body = {i['dynops_per_body']:.2f} "
                 f"instr/dynOp = {i['instr_per_dynop']:.3f}")
    lines.append(f"ir bodies/cycle = {i['bodies_per_cycle']:.1f} "
                 f"boundary write-detects/cycle = {i['boundary_writes_per_cycle']:.1f}")
    lines.append(f"ratios: changes {r['changes']:.3f} work/act {r['work_per_activation']:.3f} "
                 f"dynwork {r['dynamic_work']:.3f} instr/work {r['instr_per_work']:.3f} "
                 f"compute-instr {r['compute_instr']:.3f} closure-instr {r['closure_instr']:.3f}")
    lines.append(f"gsim sink-super fire share = {100 * pareto['sink_fire_share']:.2f}% "
                 f"detect compares/cycle = {pareto['detect_compares_per_cycle']:.1f}")
    lines.append("")
    lines.append("top supers by dynamic enode work:")
    for row in pareto["top"]:
        lines.append(f"  super {row['supernode']}: fires={row['fires']} "
                     f"enodes={row['enode_weight']} work={row['enode_work']} "
                     f"a_succ={row['a_succ']} n_sink={row['n_sink']}")
    (output / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
