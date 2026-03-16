#!/usr/bin/env python3
import argparse
import json
import os
import sys

try:
    import pylibfst
    from pylibfst import ffi, lib
except Exception as exc:  # pragma: no cover - import guard for missing deps
    pylibfst = None  # type: ignore
    ffi = None  # type: ignore
    lib = None  # type: ignore
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def _ensure_pylibfst() -> None:
    if pylibfst is None:
        exe = sys.executable
        hint = ""
        if exe != "/usr/bin/python3" and os.path.exists("/usr/bin/python3"):
            hint = "\ntry: /usr/bin/python3 tools/fst_tools/fst_stats.py ..."
        _die(
            "missing dependency pylibfst. Install with: pip install pylibfst\n"
            f"python: {exe}\n"
            f"import error: {_IMPORT_ERROR}{hint}"
        )


def _open_fst(path: str):
    _ensure_pylibfst()
    ctx = lib.fstReaderOpen(path.encode())
    if ctx == ffi.NULL:
        _die(f"failed to open fst: {path}")
    return ctx


def _close_fst(ctx) -> None:
    if ctx and ctx != ffi.NULL:
        lib.fstReaderClose(ctx)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count total signals and total value-change records in an FST waveform."
    )
    parser.add_argument("--fst", required=True, help="Path to .fst file")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def _count_stats(ctx):
    scopes, signals = pylibfst.get_scopes_signals2(ctx)
    _ = scopes

    if not hasattr(signals, "by_name"):
        _die("unexpected pylibfst signal format: missing by_name")

    by_name = signals.by_name
    signal_count = len(by_name)
    handles = {sig.handle for sig in by_name.values()}

    lib.fstReaderClrFacProcessMaskAll(ctx)
    for handle in handles:
        lib.fstReaderSetFacProcessMask(ctx, handle)

    total_changes = 0

    def cb(user, time, facidx, value):
        nonlocal total_changes
        _ = user
        _ = time
        _ = value
        if facidx in handles:
            total_changes += 1

    pylibfst.fstReaderIterBlocks(ctx, cb)
    return signal_count, total_changes


def main() -> int:
    args = _parse_args()
    ctx = _open_fst(args.fst)
    try:
        signal_count, total_changes = _count_stats(ctx)
    finally:
        _close_fst(ctx)

    if args.json:
        print(
            json.dumps(
                {
                    "fst": args.fst,
                    "signal_count": signal_count,
                    "total_changes": total_changes,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"fst: {args.fst}")
        print(f"signal_count: {signal_count}")
        print(f"total_changes: {total_changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())