#!/usr/bin/env python3
"""S4 阶段性 smoke：对 XS preserve-aggregate split SV 逐文件 ingest + grh.verify。

用法: python3 scripts/xs_aggr_ingest_smoke.py <rtl_dir> [--require-no-struct] [--max-mb N] [--limit N]
输出: 每文件一行 OK/FAIL + 末尾汇总; FAIL 首行诊断进 ptmp/logs/xs_aggr_smoke_failures.log
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".venv" / "lib"))
import wolvrix  # noqa: E402


def main() -> int:
    rtl_dir = pathlib.Path(sys.argv[1])
    require_no_struct = "--require-no-struct" in sys.argv
    max_mb = 64
    limit = 0
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--max-mb" and i + 1 < len(args):
            max_mb = int(args[i + 1])
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    files = sorted(rtl_dir.glob("*.sv"))
    ok = 0
    failed: list[tuple[str, str]] = []
    skipped = 0
    for path in files:
        if path.stat().st_size > max_mb * 1024 * 1024:
            skipped += 1
            continue
        if require_no_struct and "struct packed" in path.read_text(errors="ignore"):
            skipped += 1
            continue
        if limit and (ok + len(failed)) >= limit:
            break
        text = path.read_text(errors="ignore")
        defined = set(re.findall(r"(?m)^\s*module\s+(\w+)", text))
        instantiated = set(re.findall(r"(?m)^\s*(\w+)\s+\w+\s*\(\s*$", text)) - defined
        keywords = {"module", "endmodule", "assign", "always", "always_ff", "always_comb",
                    "always_latch", "if", "else", "for", "wire", "reg", "logic", "input",
                    "output", "initial", "function", "endfunction", "task", "endtask"}
        if instantiated - keywords:
            skipped += 1
            print(f"SKIP {path.name}: cross-file module dependency", flush=True)
            continue
        sess = wolvrix.Session()
        try:
            sess.read_sv(str(path))
            sess.run_pass("grh.verify", design="design.main")
            ok += 1
            print(f"OK   {path.name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            failed.append((path.name, msg))
            print(f"FAIL {path.name}: {msg[:160]}", flush=True)

    total = ok + len(failed)
    print(f"== {pathlib.Path(sys.argv[1]).name}: ok={ok} fail={len(failed)} "
          f"skip={skipped} (of {len(files)} files) ==")
    fail_log = pathlib.Path("ptmp/logs/xs_aggr_smoke_failures.log")
    with fail_log.open("a") as fh:
        fh.write(f"=== {sys.argv[1]} ok={ok} fail={len(failed)} skip={skipped} ===\n")
        for name, msg in failed:
            fh.write(f"{name}: {msg}\n")
    return 0 if failed == [] else 1


if __name__ == "__main__":
    sys.exit(main())
