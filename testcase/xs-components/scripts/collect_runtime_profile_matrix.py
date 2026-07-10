#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


def log(message: str) -> None:
    print(f"[xs-profile] {message}", flush=True)


def run_make_list() -> list[str]:
    result = subprocess.run(
        ["make", "list"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_bench_log(path: Path) -> dict[str, dict[str, str]]:
    bench: dict[str, dict[str, str]] = {}
    if not path.exists():
        return bench
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if not line.startswith("[BENCH]"):
            continue
        fields: dict[str, str] = {}
        for token in line.split()[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[key] = value
        model = fields.get("model")
        if model:
            bench[model] = fields
    return bench


def tsv_data_rows(path: Path) -> int:
    with path.open("r", encoding="ascii", errors="replace") as fp:
        rows = sum(1 for line in fp if line.strip())
    return max(0, rows - 1)


def complete_case(out_dir: Path) -> bool:
    required = [
        out_dir / "bench.log",
        out_dir / "gsim_supernode_static.tsv",
        out_dir / "gsim_supernode_fire.tsv",
        out_dir / "grhsim_supernode_static.tsv",
        out_dir / "grhsim_supernode_fire.tsv",
    ]
    if not all(path.exists() and path.stat().st_size > 0 for path in required):
        return False
    bench = parse_bench_log(out_dir / "bench.log")
    return "gsim" in bench and "grhsim" in bench


def copy_required(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def run_logged_make(cmd: list[str], env: dict[str, str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="ascii", errors="replace") as fp:
        fp.write("$ " + " ".join(cmd) + "\n")
        fp.flush()
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=fp,
            stderr=subprocess.STDOUT,
        )
    return completed.returncode


def is_verify_failure(path: Path) -> bool:
    return path.exists() and "[FAIL]" in path.read_text(encoding="ascii", errors="replace")


def collect_one(
    case: str,
    build_dir: Path,
    out_root: Path,
    vectors: int,
    verify: int,
    repeat: int,
    make_jobs: int | None,
    resume: bool,
) -> dict[str, object]:
    case_out = out_root / case
    if resume and complete_case(case_out):
        log(f"{case}: resume skip")
        return summarize_case(case, build_dir, case_out, skipped=True)

    case_out.mkdir(parents=True, exist_ok=True)
    make_log = case_out / "make.log"
    gsim_fire = case_out / "gsim_supernode_fire.tsv"
    grhsim_fire = case_out / "grhsim_supernode_fire.tsv"

    env = os.environ.copy()
    pybind_path = REPO_ROOT / "wolvrix" / "build" / "skbuild" / "python"
    env["PYTHONPATH"] = (
        str(pybind_path)
        if not env.get("PYTHONPATH")
        else str(pybind_path) + os.pathsep + env["PYTHONPATH"]
    )
    env.update(
        {
            "GSIM_EMIT_RUNTIME_PROFILE": "1",
            "GRHSIM_EMIT_RUNTIME_PROFILE": "1",
            "EMU_RUNTIME_PROFILE": "1",
            "GSIM_SUPERNODE_TSV": str(gsim_fire.resolve()),
            "WOLVRIX_GRHSIM_SUPERNODE_TSV": str(grhsim_fire.resolve()),
        }
    )

    def make_cmd(verify_count: int) -> list[str]:
        cmd = [
            "make",
            f"CASE={case}",
            f"BUILD_DIR={build_dir}",
            f"BENCH_VECTORS={vectors}",
            f"BENCH_VERIFY={verify_count}",
            f"BENCH_REPEAT={repeat}",
            "bench",
        ]
        if make_jobs is not None:
            cmd.insert(1, f"-j{make_jobs}")
        return cmd

    cmd = make_cmd(verify)
    log(f"{case}: run {' '.join(cmd)}")
    first_returncode = run_logged_make(cmd, env, make_log)
    verify_status = "pass"
    verify_failure_bench: Path | None = None
    verify_failure_make: Path | None = None
    if first_returncode != 0:
        case_build = build_dir / case
        failed_bench = case_build / "tb" / f"{case}_bench.log"
        if verify != 0 and is_verify_failure(failed_bench):
            verify_status = "failed_then_collected_with_verify0"
            verify_failure_make = case_out / "make_verify_failure.log"
            verify_failure_bench = case_out / "verify_failure_bench.log"
            shutil.copy2(make_log, verify_failure_make)
            copy_required(failed_bench, verify_failure_bench)
            cmd = make_cmd(0)
            log(f"{case}: verify mismatch; rerun for raw collection with {' '.join(cmd)}")
            first_returncode = run_logged_make(cmd, env, make_log)
        if first_returncode != 0:
            raise subprocess.CalledProcessError(first_returncode, cmd)

    case_build = build_dir / case
    copy_required(case_build / "tb" / f"{case}_bench.log", case_out / "bench.log")
    copy_required(case_build / "gsim" / "model" / f"{case}_supernode_static.tsv", case_out / "gsim_supernode_static.tsv")
    copy_required(case_build / "grhsim" / "model" / "grhsim_supernode_static.tsv", case_out / "grhsim_supernode_static.tsv")
    for path in [gsim_fire, grhsim_fire]:
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(path)

    summary = summarize_case(
        case,
        build_dir,
        case_out,
        skipped=False,
        verify_status=verify_status,
        verify_failure_bench=verify_failure_bench,
        verify_failure_make=verify_failure_make,
    )
    (case_out / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    log(
        f"{case}: gsim_ms={summary['gsim']['ms']} grhsim_ms={summary['grhsim']['ms']} "
        f"rows gsim={summary['gsim']['static_rows']}/{summary['gsim']['fire_rows']} "
        f"grhsim={summary['grhsim']['static_rows']}/{summary['grhsim']['fire_rows']} "
        f"verify_status={summary['verify_status']}"
    )
    return summary


def summarize_case(
    case: str,
    build_dir: Path,
    case_out: Path,
    skipped: bool,
    verify_status: str | None = None,
    verify_failure_bench: Path | None = None,
    verify_failure_make: Path | None = None,
) -> dict[str, object]:
    if skipped:
        manifest_path = case_out / "manifest.json"
        if manifest_path.exists():
            summary = json.loads(manifest_path.read_text(encoding="ascii"))
            summary.setdefault("verify_status", "pass")
            summary.setdefault("verify_failure_bench_log", "")
            summary.setdefault("verify_failure_make_log", "")
            summary["skipped"] = True
            return summary
    bench = parse_bench_log(case_out / "bench.log")
    gsim = bench.get("gsim", {})
    grhsim = bench.get("grhsim", {})
    summary: dict[str, object] = {
        "case": case,
        "skipped": skipped,
        "verify_status": verify_status or "pass",
        "verify_failure_bench_log": str(verify_failure_bench.resolve()) if verify_failure_bench else "",
        "verify_failure_make_log": str(verify_failure_make.resolve()) if verify_failure_make else "",
        "build_dir": str((build_dir / case).resolve()),
        "out_dir": str(case_out.resolve()),
        "bench_log": str((case_out / "bench.log").resolve()),
        "make_log": str((case_out / "make.log").resolve()),
        "gsim": {
            "ms": gsim.get("ms", ""),
            "vectors": gsim.get("vectors", ""),
            "repeat": gsim.get("repeat", ""),
            "static_tsv": str((case_out / "gsim_supernode_static.tsv").resolve()),
            "fire_tsv": str((case_out / "gsim_supernode_fire.tsv").resolve()),
            "static_rows": tsv_data_rows(case_out / "gsim_supernode_static.tsv"),
            "fire_rows": tsv_data_rows(case_out / "gsim_supernode_fire.tsv"),
        },
        "grhsim": {
            "ms": grhsim.get("ms", ""),
            "vectors": grhsim.get("vectors", ""),
            "repeat": grhsim.get("repeat", ""),
            "static_tsv": str((case_out / "grhsim_supernode_static.tsv").resolve()),
            "fire_tsv": str((case_out / "grhsim_supernode_fire.tsv").resolve()),
            "static_rows": tsv_data_rows(case_out / "grhsim_supernode_static.tsv"),
            "fire_rows": tsv_data_rows(case_out / "grhsim_supernode_fire.tsv"),
        },
    }
    return summary

def write_summary(out_root: Path, summaries: list[dict[str, object]]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(json.dumps(summaries, indent=2, sort_keys=True), encoding="ascii")
    with (out_root / "timings.tsv").open("w", encoding="ascii") as fp:
        fp.write(
            "case\tverify_status\tgsim_ms\tgrhsim_ms\tbench_log\tverify_failure_bench_log\t"
            "gsim_static_tsv\tgsim_fire_tsv\tgrhsim_static_tsv\tgrhsim_fire_tsv\n"
        )
        for item in summaries:
            gsim = item["gsim"]
            grhsim = item["grhsim"]
            assert isinstance(gsim, dict)
            assert isinstance(grhsim, dict)
            fp.write(
                "\t".join(
                    [
                        str(item["case"]),
                        str(item.get("verify_status", "")),
                        str(gsim["ms"]),
                        str(grhsim["ms"]),
                        str(item["bench_log"]),
                        str(item.get("verify_failure_bench_log", "")),
                        str(gsim["static_tsv"]),
                        str(gsim["fire_tsv"]),
                        str(grhsim["static_tsv"]),
                        str(grhsim["fire_tsv"]),
                    ]
                )
                + "\n"
            )


def parse_args() -> argparse.Namespace:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", default=f"build/no0190_runtime_profile_{stamp}")
    parser.add_argument("--out-dir", default=f"build/no0190_runtime_profile_{stamp}/raw")
    parser.add_argument("--case", action="append", dest="cases", help="case to collect; may be repeated")
    parser.add_argument("--case-regex", default="", help="optional regex filter over the Makefile case list")
    parser.add_argument("--vectors", type=int, default=100000)
    parser.add_argument("--verify", type=int, default=2048)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--make-jobs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_dir = Path(args.build_dir)
    out_root = Path(args.out_dir)
    if not build_dir.is_absolute():
        build_dir = ROOT / build_dir
    if not out_root.is_absolute():
        out_root = ROOT / out_root

    cases = args.cases if args.cases else run_make_list()
    if args.case_regex:
        pattern = re.compile(args.case_regex)
        cases = [case for case in cases if pattern.search(case)]
    if not cases:
        raise SystemExit("no cases selected")

    log(f"root={ROOT}")
    log(f"build_dir={build_dir}")
    log(f"out_dir={out_root}")
    log(f"cases={len(cases)} vectors={args.vectors} verify={args.verify} repeat={args.repeat}")

    summaries: list[dict[str, object]] = []
    try:
        for index, case in enumerate(cases, start=1):
            log(f"[{index}/{len(cases)}] {case}")
            summaries.append(
                collect_one(
                    case=case,
                    build_dir=build_dir,
                    out_root=out_root,
                    vectors=args.vectors,
                    verify=args.verify,
                    repeat=args.repeat,
                    make_jobs=args.make_jobs,
                    resume=args.resume,
                )
            )
            write_summary(out_root, summaries)
    except Exception as exc:
        write_summary(out_root, summaries)
        log(f"failed: {exc}")
        return 1

    write_summary(out_root, summaries)
    log(f"wrote {out_root / 'manifest.json'}")
    log(f"wrote {out_root / 'timings.tsv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
