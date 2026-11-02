"""Map generated RTL module/signal evidence back to canonical XiangShan Chisel.

This is a source evidence join. It does not claim that a generated wire name
is a unique Chisel Data node: elaboration, Vec indices and wrapper renaming can
erase that one-to-one relation. Ambiguous candidates stay visible.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / 'testcase/xiangshan'
DECL = re.compile(r'\b(class|object|trait)\s+([A-Za-z_$][\w$]*)\b')
PACKAGE = re.compile(r'^\s*package\s+([\w.]+)')
TOKEN = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*)(?![\w$])')
KEYWORDS = set('class object trait extends with private protected final override val var def if else match case true false'.split())


def normalized_module(name):
    name = str(name).split('.')[-1]
    # Chisel module names commonly receive a numeric suffix from an elaborated
    # instance. Preserve a nonnumeric base such as MSHRBuffer_1 -> MSHRBuffer.
    return re.sub(r'(?:_\d+)+$', '', name)


def signal_bases(signals):
    bases = []
    for signal in signals or []:
        signal = str(signal)
        # generated Vec/index suffixes are useful evidence only through their
        # stable prefix; leave names such as io_alloc_bits_source intact.
        base = re.sub(r'(?:_\d+)+$', '', signal)
        if base and base not in bases and not base.startswith(('_GEN_', 'repcut_')):
            bases.append(base)
    return bases


def _brace_end(lines, start):
    depth = 0
    seen = False
    for index in range(start - 1, len(lines)):
        line = re.sub(r'//.*', '', lines[index])
        depth += line.count('{') - line.count('}')
        seen |= '{' in line
        if seen and depth <= 0:
            return index + 1
    return len(lines)


def build_chisel_index(root=DEFAULT_ROOT):
    root = Path(root).resolve(strict=True)
    entries = defaultdict(list)
    files = []
    for path in sorted(root.rglob('*.scala')):
        if any(part in {'out', 'build', 'target', 'mill-out'} for part in path.parts):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        lines = text.splitlines()
        package = ''
        for line in lines[:80]:
            match = PACKAGE.match(line)
            if match:
                package = match.group(1)
                break
        for match in DECL.finditer(text):
            line = text.count('\n', 0, match.start()) + 1
            end = _brace_end(lines, line)
            name = match.group(2)
            body_tokens = set(TOKEN.findall('\n'.join(lines[line - 1:end])))
            record = dict(name=name, kind=match.group(1), package=package,
                file=str(path), relative=str(path.relative_to(root)), line=line,
                end_line=end, qualified=f'{package}.{name}' if package else name,
                tokens=body_tokens)
            entries[name].append(record)
        files.append(dict(path=str(path), relative=str(path.relative_to(root)),
                          bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return dict(schema_version=1, root=str(root), declarations={k:v for k,v in entries.items()}, files=files,
                declaration_count=sum(map(len, entries.values())))


def _candidate_score(record, signals):
    tokens = record['tokens']
    matched = [signal for signal in signal_bases(signals) if signal in tokens]
    return len(matched), matched


def resolve_module(module, signals, index):
    declarations = index['declarations']
    base = normalized_module(module)
    names = [module]
    if base not in names:
        names.append(base)
    # LazyModule wrappers commonly elaborate their `NameImp` implementation
    # as the actual RTL module. Include it as evidence, then let stable signal
    # prefixes choose between wrapper and implementation.
    if base + 'Imp' not in names:
        names.append(base + 'Imp')
    candidates = []
    seen_files = set()
    for name in names:
        for candidate in declarations.get(name, []):
            key=(candidate['file'],candidate['line'],candidate['name'])
            if key not in seen_files:
                candidates.append(candidate);seen_files.add(key)
    rows = []
    for record in candidates:
        score, matched = _candidate_score(record, signals)
        rows.append(dict(name=record['name'], kind=record['kind'], package=record['package'],
            qualified=record['qualified'], file=record['file'], relative=record['relative'],
            line=record['line'], end_line=record['end_line'], signal_score=score,
            matched_signals=matched))
    rows.sort(key=lambda row: (-row['signal_score'], row['file'], row['line']))
    if not rows:
        status = 'unresolved'
    elif len(rows) == 1:
        status = 'unique' if rows[0]['signal_score'] else 'unique-name-no-signal-evidence'
    elif rows[0]['signal_score'] > rows[1]['signal_score']:
        status = 'best-signal-match'
    else:
        status = 'ambiguous'
    return dict(rtl_module=module, normalized_module=base, status=status,
                candidates=[{k:v for k,v in row.items() if k != 'tokens'} for row in rows],
                selected=rows[0] if rows and status in {'unique','best-signal-match','unique-name-no-signal-evidence'} else None)


def resolve_contexts(contexts, root=DEFAULT_ROOT):
    index = build_chisel_index(root)
    cache = {}
    for context in contexts.values():
        key = (context.get('module'), tuple(context.get('signals', [])))
        if key not in cache:
            cache[key] = resolve_module(key[0], key[1], index) if key[0] else dict(
                rtl_module=None, normalized_module=None, status='unresolved', candidates=[], selected=None)
        resolved = cache[key]
        context['chisel_status'] = resolved['status']
        context['chisel_candidates'] = resolved['candidates']
        context['chisel_selected'] = resolved['selected']
    evidence = CounterStatus(cache.values())
    return index, dict(schema_version=1, root=str(Path(root).resolve()),
        context_count=len(contexts), unique_contexts=len(cache), statuses=evidence)


def CounterStatus(rows):
    result = defaultdict(int)
    for row in rows:
        result[row['status']] += 1
    return dict(sorted(result.items()))
