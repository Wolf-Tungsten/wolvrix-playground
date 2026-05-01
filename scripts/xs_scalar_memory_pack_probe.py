#!/usr/bin/env python3

import argparse
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

import wolvrix
from wolvrix.adapters.stats import StatsValue


def parse_tokens(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)


def log(message: str) -> None:
    sys.stderr.write(f"[xs-merge-reg-probe] {message}\n")
    sys.stderr.flush()


def read_extra_args(path: str) -> list[str]:
    if not path:
        return []
    file = Path(path)
    if not file.exists():
        raise RuntimeError(f"read args file not found: {path}")
    out: list[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            out.extend(parse_tokens(token))
    return out


def has_error_diagnostic(diags: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diags)


def require_ok(diags: list[dict], label: str) -> None:
    if has_error_diagnostic(diags):
        raise RuntimeError(f"{label} failed")


def write_stats_json(sess: wolvrix.Session, key: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    value = sess.get(key)
    if not isinstance(value, StatsValue):
        raise TypeError(f"session key is not stats: {key}")
    value.write_json(str(out_path))
    log(f"stats json written {out_path}")


def latest_info_message(diags: list[dict], pass_name: str) -> str | None:
    target = pass_name.lower()
    for item in reversed(diags):
        if str(item.get("kind", "")).lower() != "info":
            continue
        if str(item.get("pass", "")).lower() != target:
            continue
        return str(item.get("message", ""))
    return None


_REGISTER_LINE_RE = re.compile(r'"sym":\s*"((?:\\.|[^"\\])*)",\s*"kind":\s*"kRegister"')
_NATURAL_PART_RE = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple[object, ...]:
    parts: list[object] = []
    for part in _NATURAL_PART_RE.split(value):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part), len(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def extract_registers_from_json(json_path: Path) -> set[str]:
    registers: set[str] = set()
    with json_path.open("r", encoding="utf-8") as file:
        for line in file:
            match = _REGISTER_LINE_RE.search(line)
            if match:
                registers.add(json.loads(f'"{match.group(1)}"'))
    return registers


def write_register_list(path: Path, registers: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(registers, key=natural_key)
    path.write_text("".join(f"{name}\n" for name in ordered), encoding="utf-8")


def write_register_reports(before_json: Path, after_json: Path, out_dir: Path) -> dict[str, object]:
    before = extract_registers_from_json(before_json)
    after = extract_registers_from_json(after_json)
    merged = before - after
    residual = before & after
    created = after - before

    all_txt = out_dir / "merge_reg_all_registers_sorted.txt"
    merged_txt = out_dir / "merge_reg_merged_registers.txt"
    residual_txt = out_dir / "merge_reg_residual_registers.txt"
    created_txt = out_dir / "merge_reg_created_registers.txt"
    report_json = out_dir / "merge_reg_register_report.json"

    write_register_list(all_txt, before)
    write_register_list(merged_txt, merged)
    write_register_list(residual_txt, residual)
    write_register_list(created_txt, created)

    report = {
        "before_register_count": len(before),
        "after_register_count": len(after),
        "merged_register_count": len(merged),
        "residual_register_count": len(residual),
        "created_register_count": len(created),
        "artifacts": {
            "merge_reg_all_registers_sorted_txt": str(all_txt),
            "merge_reg_merged_registers_txt": str(merged_txt),
            "merge_reg_residual_registers_txt": str(residual_txt),
            "merge_reg_created_registers_txt": str(created_txt),
            "merge_reg_register_report_json": str(report_json),
        },
    }
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or resume a XiangShan checkpoint JSON, then probe merge-reg from that JSON."
    )
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("out_dir")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument(
        "--checkpoint",
        choices=["xmr-resolve", "flatten-simplify"],
        default="flatten-simplify",
        help="Which pre-merge-reg stage to materialize before replaying merge-reg",
    )
    parser.add_argument(
        "--with-stats",
        action="store_true",
        help="Also run stats before and after merge-reg. Disabled by default because it is expensive on XiangShan.",
    )
    parser.add_argument(
        "--resume-checkpoint-json",
        default="",
        help="Skip read_sv and checkpoint passes, then replay merge-reg from this checkpoint JSON.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_tag = args.checkpoint.replace("-", "_")
    checkpoint_json = out_dir / f"after_{checkpoint_tag}.json"
    merge_reg_json = out_dir / f"after_{checkpoint_tag}_plus_merge_reg.json"
    checkpoint_stats_json = out_dir / f"after_{checkpoint_tag}_stats.json"
    merge_reg_stats_json = out_dir / f"after_{checkpoint_tag}_plus_merge_reg_stats.json"
    merge_reg_memory_report_json = out_dir / "merge_reg_scalar_memory_pack_report.json"
    summary_json = out_dir / "summary.json"
    checkpoint_source_json = (
        Path(args.resume_checkpoint_json).resolve()
        if args.resume_checkpoint_json
        else checkpoint_json
    )

    summary: dict[str, object] = {
        "filelist": str(Path(args.filelist).resolve()),
        "top": args.top,
        "read_args_file": str(Path(args.read_args_file).resolve()),
        "out_dir": str(out_dir),
        "checkpoint": args.checkpoint,
        "artifacts": {
            f"after_{checkpoint_tag}_json": str(checkpoint_json),
            f"after_{checkpoint_tag}_plus_merge_reg_json": str(merge_reg_json),
            "merge_reg_all_registers_sorted_txt": str(out_dir / "merge_reg_all_registers_sorted.txt"),
            "merge_reg_merged_registers_txt": str(out_dir / "merge_reg_merged_registers.txt"),
            "merge_reg_residual_registers_txt": str(out_dir / "merge_reg_residual_registers.txt"),
            "merge_reg_created_registers_txt": str(out_dir / "merge_reg_created_registers.txt"),
            "merge_reg_register_report_json": str(out_dir / "merge_reg_register_report.json"),
            "merge_reg_scalar_memory_pack_report_json": str(merge_reg_memory_report_json),
        },
        "with_stats": args.with_stats,
        "resume_checkpoint_json": str(checkpoint_source_json) if args.resume_checkpoint_json else None,
        "timing_ms": {},
    }
    if args.resume_checkpoint_json:
        summary["artifacts"][f"after_{checkpoint_tag}_json"] = str(checkpoint_source_json)
    if args.with_stats:
        summary["artifacts"][f"after_{checkpoint_tag}_stats_json"] = str(checkpoint_stats_json)
        summary["artifacts"][f"after_{checkpoint_tag}_plus_merge_reg_stats_json"] = str(merge_reg_stats_json)

    total_start = time.perf_counter()

    if args.resume_checkpoint_json:
        if not checkpoint_source_json.exists():
            raise RuntimeError(f"resume checkpoint JSON not found: {checkpoint_source_json}")
        log(f"resume checkpoint json {checkpoint_source_json}")
    else:
        read_args = ["-f", args.filelist, "--top", args.top]
        read_args.extend(read_extra_args(args.read_args_file))

        with wolvrix.Session() as sess:
            sess.log_level = args.log_level
            sess.diagnostics_raise_min_level = "none"

            start = time.perf_counter()
            log("read_sv start")
            diags = sess.read_sv(None, out_design="design.main", slang_args=read_args)
            require_ok(diags, "read_sv")
            summary["timing_ms"]["read_sv"] = int((time.perf_counter() - start) * 1000)
            log(f"read_sv done {summary['timing_ms']['read_sv']}ms")

            checkpoint_pipeline: list[tuple[str, dict]] = [("xmr-resolve", {})]
            if args.checkpoint == "flatten-simplify":
                checkpoint_pipeline.extend(
                    [
                        ("multidriven-guard", {}),
                        ("blackbox-guard", {}),
                        ("latch-transparent-read", {}),
                        ("hier-flatten", {}),
                        ("comb-lane-pack", {"enable_declared_roots": False}),
                        ("comb-loop-elim", {}),
                        ("simplify", {"semantics": "2state", "keep_declared_symbols": False}),
                    ]
                )

            for pass_name, pass_kwargs in checkpoint_pipeline:
                start = time.perf_counter()
                log(f"pass {pass_name} start")
                diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
                require_ok(diags, f"pass {pass_name}")
                timing_key = pass_name.replace("-", "_")
                summary["timing_ms"][timing_key] = int((time.perf_counter() - start) * 1000)
                log(f"pass {pass_name} done {summary['timing_ms'][timing_key]}ms")

            if args.with_stats:
                start = time.perf_counter()
                log(f"pass stats(after_{checkpoint_tag}) start")
                checkpoint_stats_key = f"stats.after_{checkpoint_tag}"
                diags = sess.run_pass("stats", design="design.main", out_stats=checkpoint_stats_key)
                require_ok(diags, f"pass stats(after_{checkpoint_tag})")
                write_stats_json(sess, checkpoint_stats_key, checkpoint_stats_json)
                summary["timing_ms"][f"stats_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
                log(f"pass stats(after_{checkpoint_tag}) done {summary['timing_ms'][f'stats_after_{checkpoint_tag}']}ms")

            start = time.perf_counter()
            log(f"store_json after_{checkpoint_tag} start {checkpoint_json}")
            diags = sess.store_json(design="design.main", output=str(checkpoint_json), top=[args.top])
            require_ok(diags, f"store_json(after_{checkpoint_tag})")
            summary["timing_ms"][f"store_json_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
            log(f"store_json after_{checkpoint_tag} done {summary['timing_ms'][f'store_json_after_{checkpoint_tag}']}ms")

    with wolvrix.Session() as sess:
        sess.log_level = args.log_level
        sess.diagnostics_raise_min_level = "none"

        start = time.perf_counter()
        log(f"read_json_file after_{checkpoint_tag} start {checkpoint_source_json}")
        diags = sess.read_json_file(str(checkpoint_source_json), out_design="design.main")
        require_ok(diags, f"read_json_file(after_{checkpoint_tag})")
        summary["timing_ms"][f"read_json_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
        log(f"read_json_file after_{checkpoint_tag} done {summary['timing_ms'][f'read_json_after_{checkpoint_tag}']}ms")

        start = time.perf_counter()
        log("pass merge-reg start")
        previous_memory_report = os.environ.get("WOLVRIX_SCALAR_MEMORY_PACK_REPORT_JSON")
        os.environ["WOLVRIX_SCALAR_MEMORY_PACK_REPORT_JSON"] = str(merge_reg_memory_report_json)
        try:
            diags = sess.run_pass("merge-reg", design="design.main", keep_declared_symbols=False)
        finally:
            if previous_memory_report is None:
                os.environ.pop("WOLVRIX_SCALAR_MEMORY_PACK_REPORT_JSON", None)
            else:
                os.environ["WOLVRIX_SCALAR_MEMORY_PACK_REPORT_JSON"] = previous_memory_report
        require_ok(diags, "pass merge-reg")
        summary["timing_ms"]["merge_reg"] = int((time.perf_counter() - start) * 1000)
        summary["merge_reg_info"] = latest_info_message(diags, "merge-reg")
        summary["merge_reg_diagnostics"] = diags
        log(f"pass merge-reg done {summary['timing_ms']['merge_reg']}ms")

        if args.with_stats:
            start = time.perf_counter()
            log(f"pass stats(after_{checkpoint_tag}_plus_merge_reg) start")
            merge_reg_stats_key = f"stats.after_{checkpoint_tag}_plus_merge_reg"
            diags = sess.run_pass("stats", design="design.main", out_stats=merge_reg_stats_key)
            require_ok(diags, f"pass stats(after_{checkpoint_tag}_plus_merge_reg)")
            write_stats_json(sess, merge_reg_stats_key, merge_reg_stats_json)
            summary["timing_ms"][f"stats_after_{checkpoint_tag}_plus_merge_reg"] = int(
                (time.perf_counter() - start) * 1000
            )
            log(
                f"pass stats(after_{checkpoint_tag}_plus_merge_reg) done "
                f"{summary['timing_ms'][f'stats_after_{checkpoint_tag}_plus_merge_reg']}ms"
            )

        start = time.perf_counter()
        log(f"store_json after_{checkpoint_tag}_plus_merge_reg start {merge_reg_json}")
        diags = sess.store_json(design="design.main", output=str(merge_reg_json), top=[args.top])
        require_ok(diags, f"store_json(after_{checkpoint_tag}_plus_merge_reg)")
        summary["timing_ms"][f"store_json_after_{checkpoint_tag}_plus_merge_reg"] = int(
            (time.perf_counter() - start) * 1000
        )
        log(
            f"store_json after_{checkpoint_tag}_plus_merge_reg done "
            f"{summary['timing_ms'][f'store_json_after_{checkpoint_tag}_plus_merge_reg']}ms"
        )

    start = time.perf_counter()
    log("write merge-reg register reports start")
    summary["merge_reg_register_report"] = write_register_reports(checkpoint_source_json, merge_reg_json, out_dir)
    summary["artifacts"].update(summary["merge_reg_register_report"]["artifacts"])
    summary["timing_ms"]["write_merge_reg_register_reports"] = int((time.perf_counter() - start) * 1000)
    log(
        f"write merge-reg register reports done "
        f"{summary['timing_ms']['write_merge_reg_register_reports']}ms"
    )

    summary["timing_ms"]["total"] = int((time.perf_counter() - total_start) * 1000)
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"summary written {summary_json}")
    log(f"total done {summary['timing_ms']['total']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
