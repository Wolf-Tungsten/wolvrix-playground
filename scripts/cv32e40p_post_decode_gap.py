#!/usr/bin/env python3
"""Compare frozen post-decoder code, counters and samples without running models."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_regfile_compare import check_identity
from cv32e40p_decode_counts import check as check_counts

CURRENT = ROOT / 'build/cv32e40p/shared-equality-validated'
COUNTS = ROOT / 'build/cv32e40p/shared-equality-counts-v1'
PREVIOUS = ROOT / 'build/cv32e40p/remaining-gap-v1'
ORIGINAL = ROOT / 'build/cv32e40p/run2'
MODEL = CURRENT / 'grhsim_shared_equality'


def constant(op):
    literal = op['attrs']['constValue']['v']
    if literal == '0': return 0
    match = re.fullmatch(r"\d+'([bdh])([0-9a-fA-F]+)", literal)
    if not match: raise ValueError('unknown constant: ' + literal)
    return int(match[2], {'b': 2, 'd': 10, 'h': 16}[match[1]])


def run_report(out):
    manifest = check_identity(CURRENT)
    check_counts(COUNTS)
    patch = subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary'])
    if hashlib.sha256(patch).hexdigest() != manifest['patch']['sha256']:
        raise ValueError('current Wolvrix tracked patch differs from measured version')
    prior = json.loads((PREVIOUS / 'static.json').read_text())
    for name in ('verilator', 'verilator-original'):
        frozen = prior['models'][name]
        for entry in [frozen['binary'], frozen['header'], *frozen['sources']]:
            if identity(entry['path']) != entry:
                raise ValueError('Verilator frozen source differs: ' + entry['path'])
    if identity(MODEL / 'normalized.json')['sha256'] != prior['graph']['sha256']:
        raise ValueError('mapping graph differs')
    graph = json.loads((MODEL / 'normalized.json').read_text())['graphs'][0]
    values = {v['sym']: v for v in graph['vals']}
    ops = {o['sym']: o for o in graph['ops']}
    observed = json.loads((COUNTS / 'counts.json').read_text())['coremark']
    cycles = observed['cycles']
    totals = {k: sum(v) / cycles for k, v in observed['counts'].items()}
    mapping = {}
    for row in csv.DictReader((PREVIOUS / 'sources.csv').open()):
        for index, value in zip(row['value_ids'].split(';'), row['value_symbols'].split(';')):
            if index: mapping[index] = dict(row, value=value)
    kinds, widths = {}, {}
    state_slices = defaultdict(list)
    for index, meta in prior['values'].items():
        if mapping[index]['value'] != meta['value']:
            raise ValueError('value mapping mismatch')
        for table, key in ((kinds, meta['kind']), (widths, str(meta['width']))):
            row = table.setdefault(key, dict(sites=0, comparisons=0., changes=0.))
            row['sites'] += 1
            row['comparisons'] += totals['cmp:' + index]
            row['changes'] += totals['chg:' + index]
        if meta['kind'] == 'kSliceStatic':
            source = meta['operands'][0]
            op = ops.get(values[source].get('def'), {})
            if op.get('kind') == 'kRegisterReadPort':
                state_slices[op['attrs']['regSymbol']['v']].append(index)
    assert abs(sum(v['comparisons'] for v in kinds.values()) - totals['scalar_comparisons']) < 1e-7
    state_slices = {reg: dict(values=ids, comparisons=sum(totals['cmp:' + i] for i in ids),
        changes=sum(totals['chg:' + i] for i in ids), groups=sorted({prior['values'][i]['group'] for i in ids}))
        for reg, ids in state_slices.items()}
    source_lines = {}
    for p in MODEL.glob('*'):
        if p.suffix in ('.cpp', '.hpp'): source_lines[p.name] = p.read_text().splitlines()
    hot_lines = []
    for line in (out / 'grhsim-lines.txt').read_text().splitlines():
        m = re.match(r'\s*([\d.]+)%\s+\[.\]\s+(.*?)\s+(\S+):(\d+)\s+', line)
        if not m: continue
        file, lineno = m[3], int(m[4])
        text = source_lines.get(file, [])
        row = dict(percent=float(m[1]), symbol=m[2], file=file, line=lineno)
        if 0 < lineno <= len(text): row['source'] = text[lineno - 1]
        hot_lines.append(row)
    save(out / 'hot-lines.json', hot_lines)

    models = {}
    for name, folder in {'grhsim': MODEL, 'verilator': ORIGINAL / 'verilator',
                         'verilator-original': ORIGINAL / 'verilator-original'}.items():
        symbols = []
        for line in subprocess.check_output(['nm', '-S', '--size-sort', '--defined-only', '--demangle', folder / 'emu'], text=True).splitlines():
            m = re.match(r'[0-9a-f]+ ([0-9a-f]+) [TtWw] (.*)', line)
            if not m: continue
            sym = m[2]
            included = (sym.startswith('GrhSIM_Cv32Bench::eval') if name == 'grhsim' else
                sym.startswith('VCv32Bench___024root___') and any(s in sym for s in
                ('___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if included: symbols.append(dict(symbol=sym, bytes=int(m[1], 16)))
        models[name] = dict(binary=identity(folder / 'emu'), model_text=sum(s['bytes'] for s in symbols), symbols=symbols)

    banks = []
    for sym, index in [('core$_13859_', '41658'), ('core$_13860_', '41659')]:
        value = values[sym]; op = ops[value['def']]
        assert value['w'] == 2048 and op['kind'] == 'kConcat' and len(value['users']) == 1
        consumer = ops[value['users'][0]['op']]
        assert consumer['kind'] == 'kSliceDynamic' and values[consumer['out'][0]]['w'] == 32
        inputs = []
        for operand in op['in']:
            v = values[operand]; definition = ops[v['def']]
            row = dict(value=operand, width=v['w'], kind=definition['kind'])
            if definition['kind'] == 'kConstant': row['constant'] = constant(definition)
            inputs.append(row)
        assert inputs[0]['width'] == 1792 and inputs[0]['constant'] == 0
        banks.append(dict(value=sym, mapping=mapping[index], inputs=inputs,
            consumer=consumer, executions_per_cycle=totals['group:' + mapping[index]['group']],
            existing_rule_blocker='collectIndexedConcatSlices requires every operand to be scalar; 1792-bit zero padding fails'))

    reductions = []
    for sym, index in [('_val_12419', '42275'), ('_val_12607', '42338'), ('_val_6808', '42132')]:
        op = ops[values[sym]['def']]; sets = defaultdict(list); other = []
        for operand in op['in']:
            definition = ops[values[operand]['def']]
            if definition['kind'] == 'kEq':
                constants = [x for x in definition['in'] if ops[values[x]['def']]['kind'] == 'kConstant']
                if len(constants) == 1:
                    source = next(x for x in definition['in'] if x != constants[0])
                    sets[source].append(constant(ops[values[constants[0]]['def']]))
                    continue
            other.append(operand)
        packed_sets = {}
        for source, entries in sets.items():
            ranges = []
            for val in sorted(set(entries)):
                if ranges and val == ranges[-1][1] + 1: ranges[-1][1] = val
                else: ranges.append([val, val])
            # An exhaustive 12-bit domain check establishes the set identity,
            # independently of which addresses CoreMark happens to execute.
            assert values[source]['w'] == 12
            for addr in range(4096):
                assert (addr in entries) == any(lo <= addr <= hi for lo, hi in ranges)
            packed_sets[source] = dict(constants=entries, ranges=ranges, exhaustive_addresses=4096)
        reductions.append(dict(value=sym, operands=len(op['in']), other_inputs=other, sets=packed_sets,
            mapping=mapping[index], executions_per_cycle=totals['group:' + mapping[index]['group']]))

    # Check the exact shift source in the frozen IR before giving a narrow formula.
    def definition(sym): return ops[values[sym]['def']]
    shift = definition('_val_8720')
    assert shift['kind'] == 'kSub' and constant(definition(shift['in'][0])) == 0
    assign = definition(shift['in'][1]); assert assign['kind'] == 'kAssign'
    concat = definition(assign['in'][0]); assert concat['kind'] == 'kConcat'
    hi, idx, lo = concat['in']
    assert values[hi]['w'] == 23 and constant(definition(hi)) == 0
    assert values[lo]['w'] == 5 and constant(definition(lo)) == 0
    idx_op = definition(idx)
    assert idx_op['kind'] == 'kSliceStatic' and idx_op['in'] == ['_val_6162']
    assert idx_op['attrs']['sliceStart']['v'] == 0 and idx_op['attrs']['sliceEnd']['v'] == 4
    words = [0, 0xffffffff, *[1 << bit for bit in range(32)]]
    for addr in range(32):
        amount = 32 * addr
        mask = ((0xffffffff << amount) >> 96) & 0xffff
        assert mask == (0xffff if addr == 3 else 0)
        for word in words:
            data = ((word << amount) >> 96) & 0xffff
            assert data == ((word & 0xffff) if addr == 3 else 0)
    shift_evidence = dict(group=45, executions_per_cycle=totals['group:45'], original_width=1024,
        consumed_slice=[96, 111], output_width=16, source='CSR address low 5 bits',
        narrow_data='address_low5 == 3 ? (write_data & 0xffff) : 0',
        narrow_mask='address_low5 == 3 ? 0xffff : 0',
        checked_addresses=32, checked_data_basis=len(words),
        note='Identity of the shift/mask fragment only. Existing write enable, reset, snapshot and commit remain required.',
        mapping=[mapping[i] for i in ('47661', '47662', '42416', '42417', '42418', '42421', '42422', '42423', '41689')])

    production = json.loads((CURRENT / 'report.json').read_text())
    previous_report = json.loads((PREVIOUS / 'report.json').read_text())
    instructions = {'grhsim': production['diagnostics']['grhsim_shared_equality']['counters']['instructions:u']['per_guest_cycle']}
    for name in ('verilator', 'verilator-original'):
        assert models[name]['binary']['sha256'] == previous_report['static']['models'][name]['binary']['sha256']
        instructions[name] = previous_report['production_pmu'][name]['counters']['instructions:u']['per_cycle']
    references = [CURRENT / 'report.json', CURRENT / 'build.json', MODEL / 'normalized.json',
        CURRENT / 'grhsim_shared_equality-perf.data', COUNTS / 'counts.json', COUNTS / 'report.json',
        PREVIOUS / 'static.json', PREVIOUS / 'report.json', PREVIOUS / 'sources.csv',
        out / 'grhsim-lines.txt', out / 'batch4-annotate.txt', out / 'batch5-annotate.txt', out / 'batch8-annotate.txt']
    execution = {phase: [sum(v[i] / cycles for k, v in observed['counts'].items() if k.startswith('group:')
                          and prior['groups'][k[6:]]['phase'] == phase) for i in (0, 1)] for phase in ('compute', 'commit')}
    save(out / 'report.json', dict(models=models, cycles=cycles, kinds=kinds, widths=widths,
        scalar_comparisons=totals['scalar_comparisons'], scalar_changes=totals['scalar_changes'],
        direct_active_or_executions=totals['direct_active_or_executions'], execution=execution,
        rounds=totals['round'], state_slices=state_slices, csr_banks=banks, csr_write=shift_evidence,
        reductions=reductions, host_instructions_per_cycle=instructions,
        instruction_ratios={n: instructions['grhsim'] / instructions[n] for n in ('verilator', 'verilator-original')},
        pmu_scope='Existing production samples; Verilator identity unchanged. No new simultaneous PMU or performance samples.',
        source_line_scope='843 cycles:u samples, rounded attribution with possible skid; not a causal cost breakdown.',
        references=[identity(p) for p in references], driver=identity(__file__)))
    print(json.dumps(dict(instructions=instructions, csr_banks=len(banks), reductions=[(r['value'], r['operands']) for r in reductions],
                         csr_write=shift_evidence['narrow_data'], scalar_comparisons=totals['scalar_comparisons']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Existing directory with perf report and three annotate outputs')
    run_report(parser.parse_args().output.resolve())
