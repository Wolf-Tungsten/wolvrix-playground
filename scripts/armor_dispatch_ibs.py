"""Attribute IBS samples of the `lines` build to statements of the generated model.

usage: armor_dispatch_ibs.py decode op|cycles|fetch <sample directory>
       armor_dispatch_ibs.py report <sample directory>

`op` tags one retired operation per period of operations and records whether it
is a branch, taken, mispredicted. `cycles` tags by elapsed core cycles, so its
sample counts follow time. `fetch` tags instruction fetches and records where
the fetched bytes came from. Sample addresses are mapped to source lines through
the line tables of the sampled binary; no machine code is read.
"""
import collections
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from cv32e40p_compare import ROOT
from grhsim_single_baseline import save

OUT = ROOT / 'build/armor-dispatch-v1'
LLVM = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin')
BASE = 0x555555554000  # load address of a position-independent executable with address randomization off
GUEST_CYCLES = 100001
GROUP = re.compile(r'// Supernode (\d+): run when its activity flag is set\.')
BATCH = re.compile(r'void GrhSIM_SimTop::eval_(compute|commit)_batch_(\d+)\(\)')
SCHED = re.compile(r'grhsim_SimTop_sched_\d+\.cpp$')
ENABLE = re.compile(r'if \((?:unlikely\()?\(value_\w+_slots_\[\d+\]\) != 0\)')
OP_FIELDS = ('samples', 'branches', 'taken', 'mispredicted', 'returns', 'fused')
FETCH_FIELDS = ('samples', 'completed', 'ic_miss', 'l2_miss', 'l3_miss', 'itlb_l1_miss', 'itlb_l2_miss', 'op_cache_miss', 'latency')


def classify(text, phase):
    t = text.strip()
    if 'activeWordFlags' in t:
        if '!= UINT8_C(0)' in t or 'supernode_active_curr_' in t or 'hot_event_posedge_' in t:
            return 'word test'
        if t.startswith('if ('):
            return 'supernode test'
        return 'dispatch bookkeeping'
    if t.startswith(('constexpr std::uint8_t dispatchMask', 'constexpr std::uint8_t clearMask')):
        return 'word test'
    if '!= next_value' in t:
        return 'state compare' if phase == 'commit' else 'value compare'
    if phase == 'commit' and ENABLE.search(t):
        return 'write enable test'
    if 'supernode_active_curr_' in t or 'grhsim_or_active' in t or 'commit_activated_readers_' in t:
        return 'reader notification'
    if 'next_value = ' in t or 'next_words' in t:
        return 'next value expression'
    if t.endswith('= next_value;'):
        return 'store'
    if t.startswith(('const ', 'bool ', 'std::uint', 'auto ')):
        return 'local expression'
    if 'hot_event_posedge_' in t or 'event_edge_storage_' in t:
        return 'event test'
    if 'grhsim_accumulate_bank_' in t:
        return 'accumulate bank'
    if t.startswith(('if (', 'else', 'switch', 'for (', 'while (')):
        return 'other control flow'
    return 'other statement'


def read_rows(out, width):
    rows = {}
    for line in (out / 'ip.tsv').open():
        f = line.rstrip('\n').split('\t')
        rows[int(f[0], 16)] = (list(map(int, f[1:1 + width])), f[1 + width], f[2 + width])
    return rows


def symbolize(binary, addresses, out):
    """Outermost model frame and innermost function for every address."""
    listing = out / 'addresses.txt'
    listing.write_text(''.join(f'0x{a:x}\n' for a in addresses))
    result = {}
    with listing.open() as stdin:
        proc = subprocess.Popen([LLVM / 'llvm-symbolizer', f'--obj={binary}', '--output-style=JSON'],
                                stdin=stdin, stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            entry = json.loads(line)
            frames = entry.get('Symbol') or []
            if not frames:
                continue
            inner, outer = frames[0], frames[-1]
            result[int(entry['Address'], 16)] = (outer['FileName'], outer['Line'], outer['FunctionName'], inner['FunctionName'])
        if proc.wait():
            raise RuntimeError('symbolizer failed')
    listing.unlink()
    return result


def source_context(model, wanted):
    """Phase, supernode and statement category of the wanted lines of each generated file."""
    info = {}
    for name, lines in wanted.items():
        phase = batch = group = None
        with (model / name).open(errors='replace') as stream:
            for number, line in enumerate(stream, 1):
                if line.startswith('void ') and (m := BATCH.match(line)):
                    phase, batch, group = m[1], int(m[2]), None
                elif '// Supernode ' in line and (m := GROUP.search(line)):
                    group = int(m[1])
                elif 'constexpr std::uint8_t dispatchMask' in line:
                    group = None
                if number in lines:
                    info[name, number] = (phase, batch, group, classify(line, phase), line.strip()[:160])
    return info


def decode(what, out):
    run = json.loads((out / 'run.json').read_text())
    binary = Path(run['binary']['path'])
    model = binary.parents[2] / 'model'
    handler = ROOT / 'scripts/armor_dispatch_ibs_handler.py'
    env = dict(os.environ, ARMOR_IBS_WHAT='fetch' if what == 'fetch' else 'op', ARMOR_IBS_OUT=str(out))
    subprocess.run(['perf', 'script', '-i', out / 'perf.data', '-s', handler], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    fields = FETCH_FIELDS if what == 'fetch' else OP_FIELDS
    rows = read_rows(out, len(fields))
    emu = {ip: row for ip, row in rows.items() if row[1].endswith('/bin/emu')}
    located = symbolize(binary, sorted(ip - BASE for ip in emu), out)
    # The load address is assumed, so require the two symbol sources to agree.
    checked = agree = 0
    for ip, (_, _, symbol) in emu.items():
        if ip - BASE in located and symbol.startswith('GrhSIM_SimTop::eval_'):
            checked += 1
            agree += located[ip - BASE][2].startswith(symbol.split('(')[0])
    if checked < 1000 or agree < 0.999 * checked:
        raise RuntimeError(f'symbol sources disagree: {agree} of {checked}')
    wanted = collections.defaultdict(set)
    for file, line, _, _ in located.values():
        if SCHED.search(file):
            wanted[Path(file).name].add(line)
    context = source_context(model, wanted)
    total = collections.Counter()
    by_region = collections.defaultdict(collections.Counter)
    by_category = collections.defaultdict(collections.Counter)
    by_group = collections.defaultdict(collections.Counter)
    by_line = collections.defaultdict(collections.Counter)
    by_helper = collections.defaultdict(collections.Counter)

    def add(table, key, values):
        for field, value in zip(fields, values):
            table[key][field] += value

    for ip, (values, dso, symbol) in rows.items():
        add(by_region, '_all', values)
        if ip not in emu:
            name = Path(dso).name
            region = 'reference model' if 'nemu' in name else 'kernel' if 'kernel' in name else 'libraries and other'
            add(by_region, region, values)
            continue
        where = located.get(ip - BASE)
        if where is None:
            add(by_region, 'unresolved', values)
            continue
        file, line, outer, inner = where
        key = (Path(file).name, line)
        if key not in context:
            region = 'model, outside batches' if 'grhsim_SimTop' in file or outer.startswith('GrhSIM_SimTop::') else 'harness'
            add(by_region, region, values)
            if region != 'harness':
                add(by_helper, outer.split('(')[0], values)
            continue
        phase, batch, group, category, text = context[key]
        add(by_region, phase or 'model, outside batches', values)
        add(by_category, f'{phase}|{category}', values)
        if group is not None:
            add(by_group, group, values)
        add(by_line, f'{key[0]}:{key[1]}', values)
        if inner != outer and not inner.startswith('GrhSIM_SimTop::eval_'):
            add(by_helper, f'{phase}|inlined {inner.split("(")[0]}', values)
        total['classified'] += values[0]
    order = fields[3] if what == 'op' else fields[0]
    top = sorted(by_line.items(), key=lambda item: -item[1][order])[:400]
    top_lines = []
    for name, values in top:
        file, number = name.rsplit(':', 1)
        phase, batch, group, category, text = context[file, int(number)]
        top_lines.append(dict(line=name, phase=phase, group=group, category=category, text=text, **values))
    save(out / 'summary.json', dict(what=what, period=run['period'], guest_cycles=GUEST_CYCLES, fields=fields,
         symbol_check=dict(checked=checked, agree=agree), regions=by_region, categories=by_category,
         helpers=dict(sorted(by_helper.items(), key=lambda item: -item[1][fields[0]])[:60]), top_lines=top_lines))
    with (out / 'groups.tsv').open('w') as stream:
        for group, values in sorted(by_group.items()):
            stream.write(f'{group}\t' + '\t'.join(str(values[f]) for f in fields) + '\n')
    with (out / 'lines.tsv').open('w') as stream:
        for name, values in by_line.items():
            stream.write(name + '\t' + '\t'.join(str(values[f]) for f in fields) + '\n')
    print(what, 'decoded: addresses', len(rows), 'in emu', len(emu), 'symbol check', agree, '/', checked, flush=True)


def report(out):
    d = json.loads((out / 'summary.json').read_text())
    scale = d['period'] / d['guest_cycles']
    fields = d['fields']
    all_ = d['regions']['_all']
    print(f"== {out.name}: {all_['samples']} samples, one per {d['period']}")
    if d['what'] == 'fetch':
        head = f"{'':44s}{'fetches':>9s}{'share':>7s}{'L1 miss':>9s}{'L2 miss':>9s}{'L3 miss':>9s}{'iTLB2':>8s}{'lat':>7s}"
    else:
        head = f"{'':44s}{'per cyc':>9s}{'share':>7s}{'branch':>9s}{'taken':>8s}{'mispred':>9s}{'share':>7s}{'rate':>7s}"
    for title, table in (('region', d['regions']), ('category', d['categories'])):
        print(head.replace(' ' * 44, f'{title:44s}', 1))
        for key, v in sorted(table.items(), key=lambda item: -item[1]['samples']):
            if d['what'] == 'fetch':
                n = max(1, v['samples'])
                print(f"{key:44s}{v['samples']:9d}{100 * v['samples'] / all_['samples']:6.1f}%{100 * v['ic_miss'] / n:8.1f}%"
                      f"{100 * v['l2_miss'] / n:8.1f}%{100 * v['l3_miss'] / n:8.2f}%{100 * v['itlb_l2_miss'] / n:7.2f}%{v['latency'] / n:7.1f}")
            else:
                print(f"{key:44s}{v['samples'] * scale:9.0f}{100 * v['samples'] / all_['samples']:6.1f}%{v['branches'] * scale:9.0f}"
                      f"{v['taken'] * scale:8.0f}{v['mispredicted'] * scale:9.0f}"
                      f"{100 * v['mispredicted'] / max(1, all_['mispredicted']):6.1f}%{100 * v['mispredicted'] / max(1, v['branches']):6.1f}%")
        print()


if __name__ == '__main__':
    if sys.argv[1] == 'decode':
        decode(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        report(Path(sys.argv[2]).resolve())
