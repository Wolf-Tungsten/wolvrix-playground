#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pylibfst
    from pylibfst import ffi, lib
except Exception as exc:  # pragma: no cover
    pylibfst = None  # type: ignore
    ffi = None  # type: ignore
    lib = None  # type: ignore
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@dataclass
class SourceAnchor:
    file: Path
    container: str
    symbol: str
    line_text: str
    kind: str
    line: int
    score: int = 0
    reason: str = ""


@dataclass
class FstSignalCandidate:
    path: str
    scope: str
    name: str
    width: Optional[int]
    handle: Optional[int]
    score: int = 0
    reason: str = ""


SV_EXTS = {".sv", ".v", ".svh", ".vh"}
CHISEL_EXTS = {".scala", ".sc"}
KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "logic", "reg", "wire", "var",
    "signed", "unsigned", "assign", "always", "always_ff", "always_comb", "always_latch",
    "if", "else", "begin", "end", "class", "extends", "val", "new", "when", "switch",
    "bool", "uint", "sint", "bundle", "vec", "input", "output", "io", "flipped",
    "reg", "reginit", "regnext", "wire", "wireinit", "module",
}

IDENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_$]*)")
SV_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)")
SV_INSTANCE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\(")
SV_ASSIGN_RE = re.compile(r"^\s*assign\s+([A-Za-z_][A-Za-z0-9_$]*)")
CHISEL_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s+extends\s+([A-Za-z0-9_().]+)")
CHISEL_VAL_RE = re.compile(r"^\s*val\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")


def die(message: str) -> "None":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def ensure_pylibfst() -> None:
    if pylibfst is None:
        exe = sys.executable
        hint = ""
        if exe != "/usr/bin/python3" and os.path.exists("/usr/bin/python3"):
            hint = "\ntry: /usr/bin/python3 .codex/skills/fst-roi-discovery/fst_roi_discovery.py ..."
        die(
            "missing dependency pylibfst. Install with: pip install pylibfst\n"
            f"python: {exe}\n"
            f"import error: {IMPORT_ERROR}{hint}"
        )


def lower(text: str) -> str:
    return text.lower()


def trim(text: str) -> str:
    return text.strip()


def strip_line_comment(line: str) -> str:
    pos = line.find("//")
    return trim(line if pos < 0 else line[:pos])


def build_terms(hint: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", lower(trim(hint)))


def has_allowed_extension(rtl_kind: str, path: Path) -> bool:
    ext = lower(path.suffix)
    return ext in (SV_EXTS if rtl_kind == "sv" else CHISEL_EXTS)


def default_priority(kind: str) -> int:
    priorities = {
        "module": 90,
        "state": 80,
        "io": 70,
        "flow": 55,
        "assign": 45,
        "instance": 40,
        "decl": 35,
    }
    return priorities.get(kind, 0)


def pick_trailing_identifier(text: str) -> Optional[str]:
    identifiers = [m.group(1) for m in IDENT_RE.finditer(text) if lower(m.group(1)) not in KEYWORDS]
    return identifiers[-1] if identifiers else None


def append_anchor(anchors: List[SourceAnchor], path: Path, container: str, symbol: str, line_text: str, kind: str, line: int) -> None:
    if symbol:
        anchors.append(SourceAnchor(path, container, symbol, line_text, kind, line))


def scan_sv_file(path: Path, anchors: List[SourceAnchor]) -> None:
    container = ""
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = strip_line_comment(raw_line)
        if not line:
            continue
        match = SV_MODULE_RE.search(line)
        if match:
            container = match.group(1)
            append_anchor(anchors, path, container, container, line, "module", line_no)
            continue
        if line.startswith("endmodule"):
            container = ""
            continue
        match = SV_INSTANCE_RE.search(line)
        if match and lower(match.group(1)) not in KEYWORDS:
            append_anchor(anchors, path, container, match.group(2), line, "instance", line_no)
            continue
        if line.startswith("always"):
            append_anchor(anchors, path, container, f"always@{line_no}", line, "flow", line_no)
            continue
        match = SV_ASSIGN_RE.search(line)
        if match:
            append_anchor(anchors, path, container, match.group(1), line, "assign", line_no)
            continue
        if line.startswith(("input", "output", "inout")):
            symbol = pick_trailing_identifier(line)
            if symbol:
                append_anchor(anchors, path, container, symbol, line, "io", line_no)
            continue
        if line.startswith(("logic", "reg", "wire")):
            symbol = pick_trailing_identifier(line)
            if symbol:
                append_anchor(anchors, path, container, symbol, line, "state", line_no)


def scan_chisel_file(path: Path, anchors: List[SourceAnchor]) -> None:
    container = ""
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = strip_line_comment(raw_line)
        if not line:
            continue
        match = CHISEL_CLASS_RE.search(line)
        if match:
            container = match.group(1)
            append_anchor(anchors, path, container, container, line, "module", line_no)
            continue
        if line.startswith("when"):
            append_anchor(anchors, path, container, f"when@{line_no}", line, "flow", line_no)
            continue
        if line.startswith("switch"):
            append_anchor(anchors, path, container, f"switch@{line_no}", line, "flow", line_no)
            continue
        match = CHISEL_VAL_RE.search(line)
        if not match:
            continue
        symbol, rhs = match.group(1), match.group(2)
        kind = "decl"
        if any(token in rhs for token in ("IO(", "Input(", "Output(", "Flipped(")):
            kind = "io"
        elif "Reg" in rhs or "Wire" in rhs:
            kind = "state"
        append_anchor(anchors, path, container, symbol, line, kind, line_no)


def expand_inputs(rtl_kind: str, inputs: Sequence[Path]) -> List[Path]:
    expanded: List[Path] = []
    seen = set()
    for input_path in inputs:
        if input_path.is_file() and has_allowed_extension(rtl_kind, input_path):
            resolved = str(input_path.resolve())
            if resolved not in seen:
                expanded.append(input_path)
                seen.add(resolved)
            continue
        if not input_path.is_dir():
            continue
        for path in sorted(input_path.rglob("*")):
            if not path.is_file() or not has_allowed_extension(rtl_kind, path):
                continue
            resolved = str(path.resolve())
            if resolved not in seen:
                expanded.append(path)
                seen.add(resolved)
    return expanded


def build_rtl_index(rtl_kind: str, inputs: Sequence[Path]) -> List[SourceAnchor]:
    anchors: List[SourceAnchor] = []
    for path in expand_inputs(rtl_kind, inputs):
        if rtl_kind == "sv":
            scan_sv_file(path, anchors)
        else:
            scan_chisel_file(path, anchors)
    return anchors


def score_text_candidate(symbol: str, container: str, line_text: str, kind: str, terms: Sequence[str]) -> Tuple[int, str]:
    score = default_priority(kind)
    lowered_symbol = lower(symbol)
    lowered_container = lower(container)
    lowered_line = lower(line_text)
    if not terms:
        return score, "default priority"
    matched = 0
    reason = ""
    for token in terms:
        if lowered_symbol == token:
            score += 120
            matched += 1
            reason = reason or "exact symbol match"
            continue
        if token in lowered_symbol:
            score += 60
            matched += 1
            reason = reason or "symbol token match"
            continue
        if lowered_container and token in lowered_container:
            score += 30
            matched += 1
            reason = reason or "container token match"
            continue
        if token in lowered_line:
            score += 15
            matched += 1
            reason = reason or "source line token match"
    if matched == 0:
        return 0, ""
    if matched == len(terms):
        score += 20
    return score, reason or "token match"


def query_anchors(anchors: Sequence[SourceAnchor], hint: str, limit: int) -> List[SourceAnchor]:
    terms = build_terms(hint)
    ranked: List[SourceAnchor] = []
    for anchor in anchors:
        score, reason = score_text_candidate(anchor.symbol, anchor.container, anchor.line_text, anchor.kind, terms)
        if score <= 0:
            continue
        ranked.append(SourceAnchor(anchor.file, anchor.container, anchor.symbol, anchor.line_text, anchor.kind, anchor.line, score, reason))
    ranked.sort(key=lambda item: (-item.score, item.file.as_posix(), item.line, item.symbol))
    return ranked[:limit]


def open_fst(path: str):
    ensure_pylibfst()
    ctx = lib.fstReaderOpen(path.encode())
    if ctx == ffi.NULL:
        die(f"failed to open fst: {path}")
    return ctx


def close_fst(ctx) -> None:
    if ctx and ctx != ffi.NULL:
        lib.fstReaderClose(ctx)


def load_fst_signals(path: Path) -> List[FstSignalCandidate]:
    ctx = open_fst(str(path))
    try:
        scopes, signals = pylibfst.get_scopes_signals2(ctx)
    finally:
        close_fst(ctx)
    _ = scopes
    if not hasattr(signals, "by_name"):
        die("unexpected pylibfst signal format: missing by_name")
    candidates: List[FstSignalCandidate] = []
    for full_name, sig in signals.by_name.items():
        full = str(full_name)
        parts = full.split(".")
        scope = ".".join(parts[:-1]) if len(parts) > 1 else ""
        name = parts[-1]
        width = getattr(sig, "length", None)
        if width is None:
            width = getattr(sig, "width", None)
        handle = getattr(sig, "handle", None)
        candidates.append(FstSignalCandidate(full, scope, name, width, handle))
    candidates.sort(key=lambda item: item.path)
    return candidates


def query_signals(signals: Sequence[FstSignalCandidate], hint: str, limit: int) -> List[FstSignalCandidate]:
    terms = build_terms(hint)
    ranked: List[FstSignalCandidate] = []
    for signal in signals:
        score, reason = score_text_candidate(signal.name, signal.scope, signal.path, "state", terms)
        if score <= 0:
            continue
        ranked.append(FstSignalCandidate(signal.path, signal.scope, signal.name, signal.width, signal.handle, score, reason))
    ranked.sort(key=lambda item: (-item.score, item.path, -1 if item.handle is None else item.handle))
    return ranked[:limit]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def json_anchor(anchor: SourceAnchor) -> Dict[str, object]:
    return {
        "file": anchor.file.as_posix(),
        "container": anchor.container,
        "symbol": anchor.symbol,
        "kind": anchor.kind,
        "line": anchor.line,
        "score": anchor.score,
        "reason": anchor.reason,
    }


def json_signal(signal: FstSignalCandidate) -> Dict[str, object]:
    return {
        "path": signal.path,
        "width": signal.width,
        "handle": signal.handle,
        "score": signal.score,
        "reason": signal.reason,
    }


def write_metadata(path: Path, payload: Dict[str, object]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_signals_tsv(path: Path, all_signals: Sequence[FstSignalCandidate], ranked_signals: Sequence[FstSignalCandidate]) -> None:
    ensure_parent(path)
    ranked_by_handle: Dict[Optional[int], Tuple[int, int, str]] = {}
    for index, signal in enumerate(ranked_signals, start=1):
        ranked_by_handle[signal.handle] = (index, signal.score, signal.reason)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("path\tscope\tname\twidth\thandle\tcandidate_rank\tcandidate_score\tcandidate_reason\n")
        for signal in all_signals:
            rank_info = ranked_by_handle.get(signal.handle)
            columns = [
                signal.path,
                signal.scope,
                signal.name,
                "" if signal.width is None else str(signal.width),
                "" if signal.handle is None else str(signal.handle),
            ]
            if rank_info is None:
                columns.extend(["", "", ""])
            else:
                columns.extend([str(rank_info[0]), str(rank_info[1]), rank_info[2]])
            handle.write("\t".join(column.replace("\t", " ").replace("\n", " ") for column in columns) + "\n")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python ROI discovery helper for RTL and FST evidence extraction.")
    parser.add_argument("--fst", type=Path, help="Path to .fst file")
    parser.add_argument("--rtl-kind", choices=["sv", "chisel"], help="RTL kind")
    parser.add_argument("--rtl", action="append", type=Path, default=[], help="RTL file or source root (repeatable)")
    parser.add_argument("--artifact-prefix", type=Path, required=True, help="Artifact prefix for .metadata.json / .signals.tsv / .ai.md")
    parser.add_argument("--hint", default="", help="Behavioral hint")
    parser.add_argument("--limit", type=int, default=8, help="Top candidate limit")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.fst and not args.rtl:
        die("provide at least one of --fst or --rtl")
    if args.rtl and not args.rtl_kind:
        die("--rtl-kind is required when --rtl is provided")

    anchors: List[SourceAnchor] = []
    if args.rtl_kind:
        anchors = query_anchors(build_rtl_index(args.rtl_kind, args.rtl), args.hint, args.limit)

    all_signals: List[FstSignalCandidate] = []
    ranked_signals: List[FstSignalCandidate] = []
    if args.fst:
        all_signals = load_fst_signals(args.fst)
        ranked_signals = query_signals(all_signals, args.hint, args.limit)

    prefix = args.artifact_prefix
    metadata_path = Path(str(prefix) + ".metadata.json")
    signals_path = Path(str(prefix) + ".signals.tsv")
    payload = {
        "query": {
            "hint": args.hint,
            "rtl_kind": args.rtl_kind or "",
        },
        "artifacts": {
            "artifact_prefix": prefix.as_posix(),
            "metadata_json": metadata_path.as_posix(),
            "signals_tsv": signals_path.as_posix(),
            "expected_ai_report": Path(str(prefix) + ".ai.md").as_posix(),
            "exported_signal_rows": len(all_signals),
        },
        "candidate_regions": [json_anchor(anchor) for anchor in anchors],
        "candidate_signals": [json_signal(signal) for signal in ranked_signals],
    }

    write_metadata(metadata_path, payload)
    write_signals_tsv(signals_path, all_signals, ranked_signals)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())