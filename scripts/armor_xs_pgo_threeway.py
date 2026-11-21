"""Same-round PGO timing of stock and DPI-aligned GSIM and the old and new GrhSIM binaries."""
import argparse
import csv
import json
import platform
import resource
from pathlib import Path

from armor_xs_pgo_measure import Baseline, IMAGES, LLVM, LOCK, NEMU, WINDOW, measurement_lock, paired
from armor_xs_pgo_build import execute
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import clean_environment, identity, parse_run, save
from xiangshan_cv32_ablation_measure import read, signature, verify

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
BASELINE = BUILD / "armor-xs-pgo-v1"
PREVIOUS = BUILD / "armor-gap-followup-v1"
OUT = BUILD / "armor-xs-pgo-threeway-v1"
LABELS = ("old", "new", "gsim", "gsim_matched")
# A balanced Latin square also balances which binary precedes each other binary.
ORDERS = [("old", "new", "gsim_matched", "gsim"), ("new", "gsim", "old", "gsim_matched"),
          ("gsim", "gsim_matched", "new", "old"), ("gsim_matched", "old", "gsim", "new")]
COMPARISONS = (("old", "new"), ("gsim", "old"), ("gsim", "new"),
               ("gsim_matched", "old"), ("gsim_matched", "new"), ("gsim", "gsim_matched"))


def archived_inputs():
    old, gsim = (read(BASELINE / engine / "verify/result.json") for engine in ("grhsim", "gsim"))
    matched = read(BUILD / "armor-gsim-gap-v1/timing/cross-engine/policy.json")["binaries"]["gsim-nodpi-use"]
    new = read(PREVIOUS / "verify/joint/coremark/result.json")["binary"]
    records = {"old": old["binaries"]["use"], "new": new, "gsim": gsim["binaries"]["use"], "gsim_matched": matched}
    for record in records.values():
        verify(record)
    signatures = {}
    for wl in IMAGES:
        grh = old["workloads"][wl]["signature"]
        gs = gsim["workloads"][wl]["signature"]
        proof = read(PREVIOUS / "verify/joint" / wl / "result.json")
        assert proof["binary"] == new and proof["signature"] == grh
        signatures[wl] = {"old": grh, "new": grh, "gsim": gs, "gsim_matched": gs}
    return records, signatures


def verify_matched_traces(out):
    from armor_dispatch_diag import pick_cpu

    records, expected = archived_inputs()
    for wl, image in IMAGES.items():
        folder = out / "verify" / wl
        folder.mkdir(parents=True, exist_ok=True)
        command = ["taskset", "-c", str(pick_cpu()[0]), "numactl", "--membind=1", "setarch", "x86_64",
                   "-R", records["gsim_matched"]["path"], "-i", image, "--diff", NEMU, "-b", "0", "-e", "0",
                   "-s", "0", "-C", str(WINDOW), "--dump-difftrace", "./trace"]
        execute(command, "run", folder, clean_environment(), folder)
        row = parse_run((folder / "run.log").read_text(), WINDOW)
        if signature(row) != expected[wl]["gsim"]:
            raise RuntimeError(f"matched GSIM endpoint differs on {wl}")
        check = compare_traces(BASELINE / "gsim/verify/comparator/compare",
                               BASELINE / "gsim/use" / ("check-" + wl) / "trace",
                               folder / "trace", folder / "comparison.json")
        save(folder / "result.json", {"coverage": validate_trace_coverage(check, row),
             "reference": records["gsim"], "candidate": records["gsim_matched"], "endpoint": signature(row)})


def export_csv(out, path):
    policy = read(out / "policy.json")
    rows = read(out / "rounds.json")
    samples = []
    for wl in IMAGES:
        if len(rows[wl]) != len(ORDERS):
            raise ValueError(f"incomplete rounds for {wl}")
        for i, row in enumerate(rows[wl], 1):
            if row["round"] != i or tuple(row["order"]) != ORDERS[i - 1]:
                raise ValueError(f"incorrect order in {wl} round {i}")
            for position, label in enumerate(row["order"], 1):
                sample = row[label]
                sibling_idle = min(value for cpu, value in sample["sibling_idle"].items()
                                   if int(cpu) != sample["cpu"])
                if (sample != {**read(out / sample["run"]), "run": sample["run"]}
                    or signature(sample) != policy["expected"][wl][label]
                    or sample["binary_sha256"] != policy["bins"][label]["sha256"]
                    or sample["cpu"] != 96 or sample["numa_node"] != 1
                    or sample["max_threads"] != 1 or sibling_idle < 98
                    or not sample["locality_pass"] or not sample["reference_mapped"]):
                    raise ValueError(f"sample validation failed for {wl}/{i}/{label}")
                samples.append(dict(workload=wl, round=i, position=position, variant=label,
                    external_wall_s=sample["external_wall_s"], host_ms=sample["host_ms"],
                    guest_cycles=sample["guest_cycles"], instructions_committed=sample["instr_count"],
                    cpu=sample["cpu"], numa_node=sample["numa_node"], sibling_idle_pct=sibling_idle,
                    image_sha256=policy["images"][wl]["sha256"], binary_sha256=sample["binary_sha256"]))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=samples[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(samples)


def run(out):
    if platform.node().split(".")[0] != "node030":
        raise RuntimeError("use node030 CPU 96 for this series")
    records, expected = archived_inputs()
    with measurement_lock(LOCK, wait=True):
        out.mkdir(parents=True, exist_ok=True)
        policy = dict(host=platform.node(), cpu=96, numa=1, rounds=4, seed=0, window=WINDOW, threads=1,
                      aslr=False, orders=ORDERS, bins=records, images={w:identity(p) for w,p in IMAGES.items()},
                      nemu=identity(NEMU), expected=expected, metric="external_wall_s",
                      load_order=[["coremark", "microbench"], ["microbench", "coremark"]] * 2)
        policy_file = out / "policy.json"
        if policy_file.exists() and read(policy_file) != json.loads(json.dumps(policy)):
            raise RuntimeError("stored policy or binaries differ from requested series")
        save(policy_file, policy)
        results = out / "rounds.json"
        rows = read(results) if results.exists() else {wl: [] for wl in IMAGES}
        sessions = out / "sessions"
        sessions.mkdir(exist_ok=True)
        session = sessions / f"session{len(list(sessions.iterdir())) + 1}"
        session.mkdir()
        prepared = {}

        def collect(wl, label, tag):
            runner, setup = prepared[wl, label]
            result = runner.run_sample(setup, tag, WINDOW, 0, [])
            if signature(result) != expected[wl][label] or not result["reference_mapped"]:
                raise RuntimeError(f"{wl}/{label}/{tag}: reference or endpoint differs")
            result["run"] = str((setup["directory"] / (tag + ".json")).relative_to(out))
            return result

        def collect_set(wl, order, tag):
            # A busy SMT sibling invalidates the entire paired block, including completed samples.
            attempt = 0
            while True:
                attempt += 1
                trial = f"{tag}-try{attempt}"
                current = {"order": order}
                for label in order:
                    try:
                        current[label] = collect(wl, label, trial)
                    except RuntimeError as exc:
                        if "SMT sibling busy" not in str(exc) and "SMT sibling remains busy" not in str(exc):
                            raise
                        save(session / f"{wl}-{trial}-rejected.json", {"reason":str(exc), "partial":current})
                        print("RETRY", wl, tag, label, str(exc), flush=True)
                        break
                    print("SAMPLE", wl, trial, label, f"{current[label]['external_wall_s']:.3f}", flush=True)
                else:
                    return current

        for idx, workloads in enumerate(policy["load_order"]):
            for wl in workloads:
                if len(rows[wl]) > idx:
                    continue
                if (wl, LABELS[0]) not in prepared:
                    for label in LABELS:
                        engine = "gsim" if label.startswith("gsim") else "grhsim"
                        opts = argparse.Namespace(output=session/wl/label, binary=Path(records[label]["path"]),
                            simulator=engine, compiler=LLVM/"clang++", cpu=96, cycles=WINDOW, jobs=1, repeats=4,
                            tools_dir=None, sim_primitives="none", image=IMAGES[wl], nemu=NEMU, skip_idle_check=False)
                        runner = Baseline(opts)
                        prepared[wl, label] = (runner, runner.prepare_measurement())
                    save(session / f"{wl}-warmup.json", collect_set(wl, list(reversed(ORDERS[idx])), "warmup"))
                row = collect_set(wl, list(ORDERS[idx]), f"round{idx + 1}")
                row["round"] = idx + 1
                rows[wl].append(row)
                save(results, rows)
                print("ROUND", wl, idx + 1, {n:round(row[n]["external_wall_s"], 3) for n in LABELS}, flush=True)
        summary = {wl:{f"{b}_vs_{a}":paired(rows[wl],a,b) for a,b in COMPARISONS} for wl in IMAGES}
        save(out / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--verify-matched", action="store_true", help="compare aligned and stock GSIM traces on node029")
    action.add_argument("--export-csv", type=Path, help="validate and export all timed samples to this CSV")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    if args.verify_matched:
        verify_matched_traces(args.output.resolve())
    elif args.export_csv:
        export_csv(args.output.resolve(), args.export_csv)
    else:
        run(args.output.resolve())
