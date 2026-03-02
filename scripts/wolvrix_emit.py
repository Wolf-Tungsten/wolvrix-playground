#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import wolvrix


def getenv(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value else default


def split_args(text: str) -> list[str]:
    if not text:
        return []
    return shlex.split(text)


def resolve_output_path(path_text: str, output_dir: str) -> str:
    path = Path(path_text)
    if not path.parent and output_dir:
        return str(Path(output_dir) / path)
    return str(path)


def ensure_parent_dir(path_text: str) -> None:
    path = Path(path_text)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def read_extra_args_from_file(path_text: str) -> list[str]:
    tokens: list[str] = []
    with open(path_text, "r", encoding="utf-8") as handle:
        for line in handle:
            token = line.strip()
            if token:
                tokens.append(token)
    return tokens


def main() -> int:
    filelist = getenv("WOLVRIX_FILELIST")
    sources_text = getenv("WOLVRIX_SOURCES")
    top_name = getenv("WOLVRIX_TOP")
    sv_out = getenv("WOLVRIX_SV_OUT")
    if not sv_out:
        print("WOLVRIX_SV_OUT not set", file=sys.stderr)
        return 1

    json_out = getenv("WOLVRIX_JSON_OUT")
    if not json_out:
        json_out = str(Path(sv_out).parent / "grh.json")

    output_dir = getenv("WOLVRIX_OUTPUT_DIR")
log_level = getenv("WOLVRIX_LOG_LEVEL", "info")

    sources = split_args(sources_text)
    if not sources and not filelist:
        print("WOLVRIX_FILELIST or WOLVRIX_SOURCES/WOLVRIX_READ_ARGS must be provided", file=sys.stderr)
        return 1

    read_args: list[str] = []
    if filelist:
        read_args.extend(["-f", filelist])

    if top_name:
        read_args.extend(["--top", top_name])

    extra_args_file = getenv("WOLVRIX_READ_ARGS_FILE")
    if extra_args_file:
        if not Path(extra_args_file).exists():
            print(f"WOLVRIX_READ_ARGS_FILE not found: {extra_args_file}", file=sys.stderr)
            return 1
        read_args.extend(read_extra_args_from_file(extra_args_file))

    extra_args = getenv("WOLVRIX_READ_ARGS")
    read_args.extend(split_args(extra_args))

    path: str | None = None
    if sources:
        path = sources[0]
        read_args.extend(sources[1:])

    if not read_args and path is None:
        print("WOLVRIX_FILELIST or WOLVRIX_SOURCES/WOLVRIX_READ_ARGS must be provided", file=sys.stderr)
        return 1

    sv_out = resolve_output_path(sv_out, output_dir)
    json_out = resolve_output_path(json_out, output_dir)
    ensure_parent_dir(sv_out)
    ensure_parent_dir(json_out)

    try:
        design, _read_diags = wolvrix.read_sv(
            path,
            slang_args=read_args,
            log_level=log_level,
            diagnostics="warn",
            print_diagnostics_level="warn",
            raise_diagnostics_level="error",
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    skip_transform = getenv("WOLVRIX_SKIP_TRANSFORM", "0")
    if skip_transform != "1":
        for pass_name in [
            "xmr-resolve",
            "latch-transparent-read",
            "simplify",
            "memory-init-check",
            "stats",
        ]:
            try:
                design.run_pass(
                    pass_name,
                    diagnostics="warn",
                    log_level=log_level,
                    print_diagnostics_level="warn",
                    raise_diagnostics_level="error",
                )
            except Exception as exc:
                print(str(exc), file=sys.stderr)
                return 1

    json_roundtrip = getenv("WOLVRIX_JSON_ROUNDTRIP", "0")
    store_json = getenv("WOLVRIX_STORE_JSON", "0")

    try:
        if json_roundtrip == "1":
            design.write_json(json_out)
            design = wolvrix.read_json(json_out)
        elif store_json == "1":
            design.write_json(json_out)

        design.write_sv(sv_out)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
