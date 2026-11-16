#!/usr/bin/env python3
"""Summarize frozen local-decoder counters, PMU and machine code; no model runs."""
import argparse
import csv
import json
from pathlib import Path
import re

from cv32e40p_binary_shape import function_symbols, disassemble, instructions, instruction_shape
from cv32e40p_compare import identity, save, summarize_named
from cv32e40p_event_regions_compare import check


def analyze(source, counts, output):
    if output.exists():
        raise FileExistsError('use a new report path')
    manifest = check(source)
    observed = json.loads((counts / 'counts.json').read_text())['coremark']
    inputs = json.loads((counts / 'inputs.json').read_text())
    if inputs['model'] != manifest['binaries']['grhsim_local_decode']:
        raise ValueError('counter binary mismatch')
    functional = json.loads((source / 'functional.json').read_text())
    reference = functional['workloads']['coremark']['verilator']
    if observed['cycles'] != reference['cycles'] or observed['trace']['sha256'] != reference['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    cycles = observed['cycles']
    models, pmu, files = {}, {}, []
    for backend, entry in manifest['binaries'].items():
        binary = Path(entry['path']); functions = []
        for symbol in function_symbols(binary):
            name = symbol['symbol']
            selected = (name.startswith('GrhSIM_Cv32Bench::eval') if backend != 'verilator' else
                name.startswith('VCv32Bench___024root___') and any(tag in name for tag in (
                    '___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if not selected:
                continue
            asm = disassemble(binary, symbol)
            functions.append(dict(**symbol, **instruction_shape(instructions(asm))))
            if name == 'GrhSIM_Cv32Bench::eval_compute_batch_3()':
                path = source / (backend + '-batch3.s'); path.write_text(asm); files.append(path)
        models[backend] = dict(binary=entry, functions=functions,
            totals={key: sum(f[key] for f in functions) for key in ('bytes', 'instructions',
                'memory_operand_instructions', 'stack_operand_instructions', 'compare_or_test', 'cmov_or_setcc')})
        if backend != 'verilator':
            path = source / (backend + '-stat.csv'); files.append(path)
            records = {}
            for row in csv.reader(path.read_text().splitlines()):
                if len(row) >= 3 and row[2].endswith(':u'):
                    records[row[2]] = int(row[0]) / cycles
            if set(records) != {'cycles:u', 'instructions:u', 'branches:u', 'branch-misses:u'}:
                raise ValueError('missing PMU event')
            pmu[backend] = records | {'ipc': records['instructions:u'] / records['cycles:u']}
    measured = json.loads((source / 'pairs.json').read_text())
    report = dict(scope='Independent diagnostics. Static stack/memory operands are not dynamic spill counts; profile percentages do not apportion paired time.',
        baseline_vs_verilator=summarize_named(measured, 'grhsim_event_regions', 'verilator'),
        cycles=cycles, phases=inputs['phases'],
        counters_per_cycle={k: [v / cycles for v in values] for k, values in observed['counts'].items()
            if k.startswith(('local_decode_', 'scalar_', 'round'))},
        pmu=pmu, models=models,
        references=[identity(p) for p in [source / 'build.json', source / 'summary.json',
            source / 'diagnostic-runs.json', source / 'local-perf.data', source / 'local-perf.txt',
            source / 'local-lines.txt', counts / 'inputs.json', counts / 'counts.json', *files,
            Path(__file__).resolve()]])
    save(output, report)
    print(json.dumps({k: report[k] for k in ('counters_per_cycle', 'pmu')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.source.resolve(), args.counts.resolve(), args.output.resolve())
