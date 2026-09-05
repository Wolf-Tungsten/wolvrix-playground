#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
import sys
import time
from pathlib import Path

import wolvrix


GRH_PIPELINE: list[tuple[str, dict]] = [
    ("xmr-resolve", {}),
    ("memory-read-retime", {}),
    ("multidriven-guard", {}),
    ("blackbox-guard", {}),
    ("latch-transparent-read", {}),
    ("hier-flatten", {}),
    ("comb-loop-elim", {}),
    ("simplify", {"semantics": "2state"}),
    ("memory-init-check", {}),
]


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim-ir] {message}\n")
    sys.stderr.flush()


def has_error(diagnostics: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diagnostics)


def require_ok(diagnostics: list[dict], action: str) -> None:
    if has_error(diagnostics):
        raise RuntimeError(f"{action} failed")


def timed(action: str, callback):
    start = time.perf_counter()
    log(f"{action} start")
    result = callback()
    log(f"{action} done {int((time.perf_counter() - start) * 1000)}ms")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and round-trip the independent XiangShan GrhSIM IR checkpoint"
    )
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("flat_grh_json")
    parser.add_argument("grhsim_json")
    parser.add_argument("roundtrip_json")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--resume-from-flat-grh", action="store_true")
    parser.add_argument("--keep-origins", action="store_true")
    return parser.parse_args()


def read_slang_args(filelist: Path, top: str, read_args_file: Path) -> list[str]:
    if not filelist.is_file():
        raise RuntimeError(f"filelist not found: {filelist}")
    if not read_args_file.is_file():
        raise RuntimeError(f"read args file not found: {read_args_file}")
    result = ["-f", str(filelist), "--top", top]
    for line in read_args_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            result.extend(shlex.split(line))
    return result


def main() -> int:
    args = parse_args()
    filelist = Path(args.filelist).resolve()
    flat_grh_json = Path(args.flat_grh_json).resolve()
    grhsim_json = Path(args.grhsim_json).resolve()
    roundtrip_json = Path(args.roundtrip_json).resolve()
    read_args_file = Path(args.read_args_file).resolve()

    for path in (flat_grh_json, grhsim_json, roundtrip_json):
        path.parent.mkdir(parents=True, exist_ok=True)

    total_start = time.perf_counter()
    with wolvrix.Session() as session:
        session.log_level = args.log_level
        session.diagnostics_raise_min_level = "none"

        if args.resume_from_flat_grh:
            if not flat_grh_json.is_file():
                raise RuntimeError(f"flat GRH checkpoint not found: {flat_grh_json}")
            diagnostics = timed(
                f"load flat GRH {flat_grh_json}",
                lambda: session.read_json_file(str(flat_grh_json), out_design="design.main"),
            )
            require_ok(diagnostics, "load flat GRH")
        else:
            read_args = read_slang_args(filelist, args.top, read_args_file)
            diagnostics = timed(
                "ingest XiangShan RTL",
                lambda: session.read_sv(None, out_design="design.main", slang_args=read_args),
            )
            require_ok(diagnostics, "ingest XiangShan RTL")
            for pass_name, pass_options in GRH_PIPELINE:
                diagnostics = timed(
                    f"GRH pass {pass_name}",
                    lambda name=pass_name, options=pass_options: session.run_pass(
                        name, design="design.main", **options
                    ),
                )
                require_ok(diagnostics, f"GRH pass {pass_name}")
            diagnostics = timed(
                f"store flat GRH checkpoint {flat_grh_json}",
                lambda: session.store_json(
                    design="design.main", output=str(flat_grh_json), top=[args.top]
                ),
            )
            require_ok(diagnostics, "store flat GRH checkpoint")

        diagnostics = timed(
            "lower GRH to independent GrhSIM IR",
            lambda: session.lower_grhsim(
                design="design.main",
                out_model="grhsim.main",
                top=args.top,
                logic_domain="2-state",
                keep_origins=args.keep_origins,
                consume=True,
            ),
        )
        require_ok(diagnostics, "lower GRH to GrhSIM IR")
        diagnostics = timed(
            "GrhSIM verify pass",
            lambda: session.run_grhsim_pass("grhsim.verify", model="grhsim.main"),
        )
        require_ok(diagnostics, "GrhSIM verify pass")
        diagnostics = timed(
            f"store GrhSIM checkpoint {grhsim_json}",
            lambda: session.store_grhsim(model="grhsim.main", output=str(grhsim_json)),
        )
        require_ok(diagnostics, "store GrhSIM checkpoint")

    with wolvrix.Session() as fresh_session:
        fresh_session.diagnostics_raise_min_level = "none"
        diagnostics = timed(
            f"load GrhSIM checkpoint in fresh session {grhsim_json}",
            lambda: fresh_session.load_grhsim(str(grhsim_json), out_model="grhsim.roundtrip"),
        )
        require_ok(diagnostics, "load GrhSIM checkpoint")
        diagnostics = timed(
            f"store GrhSIM round-trip {roundtrip_json}",
            lambda: fresh_session.store_grhsim(
                model="grhsim.roundtrip", output=str(roundtrip_json)
            ),
        )
        require_ok(diagnostics, "store GrhSIM round-trip")

    if grhsim_json.read_bytes() != roundtrip_json.read_bytes():
        raise RuntimeError("GrhSIM store/load/store changed stable JSON bytes")
    log(f"stable round-trip verified: {grhsim_json} == {roundtrip_json}")
    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"fatal: {error}")
        raise
