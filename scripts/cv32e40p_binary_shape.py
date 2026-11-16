#!/usr/bin/env python3
"""Inspect frozen CV32E40P model binaries and reuse their existing perf profiles."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save

RUN2 = ROOT / 'build/cv32e40p/run2'
CURRENT = ROOT / 'build/cv32e40p/shared-equality-validated'
OLD_PROFILES = ROOT / 'build/cv32e40p/code-shapes-v1'
EXPECTED_TRACE = 'ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098'


def command(argv: list[str]) -> str:
    return subprocess.check_output(list(map(str, argv)), text=True)


def read_json(path: Path):
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def function_symbols(binary: Path):
    rows = []
    for line in command(['nm', '-S', '--defined-only', '--demangle', binary]).splitlines():
        match = re.match(r'([0-9a-fA-F]+) ([0-9a-fA-F]+) ([A-Za-z]) (.+)$', line)
        if match:
            rows.append(dict(address=int(match[1], 16), bytes=int(match[2], 16),
                             symbol=match[4], type=match[3]))
    return rows


def perf_symbols(report: Path):
    return parse_perf_symbols(report.read_text())


def parse_perf_symbols(text: str):
    rows = []
    for line in text.splitlines():
        match = re.match(r'^\s*([\d.]+)%\s+emu\s+emu\s+\[\.\]\s+(.+?)\s*$', line)
        if match and not match[2].startswith(('main', 'std::', 'void std::')):
            rows.append(dict(percent=float(match[1]), symbol=match[2]))
    return rows


def select_symbols(backend: str, symbols: list[dict], profile: list[dict]):
    by_name = {row['symbol']: row for row in symbols}
    if backend == 'grhsim':
        chosen = [name for name in by_name if name == 'GrhSIM_Cv32Bench::eval()' or
                  re.match(r'GrhSIM_Cv32Bench::eval_(?:compute|commit)_batch_\d+\(\)$', name)]
        return [by_name[name] for name in sorted(chosen)]
    preferred = [row['symbol'] for row in profile[:10]]
    return [by_name[name] for name in preferred if name in by_name]


def disassemble(binary: Path, symbol: dict) -> str:
    start = symbol['address']
    stop = start + symbol['bytes']
    text = command(['llvm-objdump', '-d', '--demangle', '--no-show-raw-insn',
                    '--symbolize-operands', f'--start-address=0x{start:x}',
                    f'--stop-address=0x{stop:x}', binary])
    return f"# symbol: {symbol['symbol']}\n# address: 0x{start:x}\n# bytes: {symbol['bytes']}\n" + text


def instructions(text: str):
    rows = []
    for line in text.splitlines():
        match = re.match(r'^\s*([0-9a-fA-F]+):\s+([a-zA-Z][\w.]*)\s*(.*?)\s*$', line)
        if match:
            rows.append(dict(address=int(match[1], 16), mnemonic=match[2].lower(), operands=match[3]))
    return rows


def instruction_shape(rows):
    mnemonics = Counter(row['mnemonic'] for row in rows)
    stack = [row for row in rows if re.search(r'\(%(?:rsp|rbp)\)|\b(?:rsp|rbp)\b', row['operands'])]
    memory = [row for row in rows if '(' in row['operands'] and ')' in row['operands']]
    branches = [row for row in rows if row['mnemonic'].startswith('j') or row['mnemonic'].startswith('loop')]
    conditional = [row for row in branches if row['mnemonic'] not in ('jmp', 'jmpq')]
    calls = [row for row in rows if row['mnemonic'].startswith('call')]
    returns = [row for row in rows if row['mnemonic'].startswith('ret')]
    vector = [row for row in rows if row['mnemonic'].startswith(('v', 'k')) or
              re.search(r'%(?:xmm|ymm|zmm|k[0-7])\d*', row['operands'])]
    compare = [row for row in rows if row['mnemonic'].startswith(('cmp', 'test'))]
    select = [row for row in rows if row['mnemonic'].startswith(('cmov', 'set'))]
    return dict(instructions=len(rows), branches=len(branches), conditional_branches=len(conditional),
        calls=len(calls), returns=len(returns), memory_operand_instructions=len(memory),
        stack_operand_instructions=len(stack), vector_or_mask_instructions=len(vector),
        compare_or_test=len(compare), cmov_or_setcc=len(select),
        top_mnemonics=mnemonics.most_common(16))


def annotation(text: str):
    rows = []
    for line in text.splitlines():
        match = re.match(r'^\s*([\d.]+)\s*:\s*([0-9a-fA-F]+):\s*([a-zA-Z][\w.]*)\s*(.*?)\s*$', line)
        if match:
            rows.append(dict(function_percent=float(match[1]), address=int(match[2], 16),
                             mnemonic=match[3].lower(), operands=match[4]))
    return rows


def parse_addr2line(text: str, count: int):
    lines = text.splitlines()
    if len(lines) != count * 2:
        raise ValueError('addr2line returned an unexpected number of lines')
    return [dict(function=lines[index * 2], location=lines[index * 2 + 1])
            for index in range(count)]


def source_locations(binary: Path, addresses: list[int]):
    if not addresses:
        return []
    text = command(['llvm-addr2line', '-f', '-C', '-e', binary,
                    *[f'0x{address:x}' for address in addresses]])
    return parse_addr2line(text, len(addresses))


def tool_version(program: str):
    lines = command([program, '--version']).splitlines()
    return next((line.strip() for line in lines if line.strip().startswith('LLVM version')),
                lines[0].strip() if lines else 'unknown')


def annotate(binary: Path, perf_data: Path, symbol: str) -> str:
    return command(['perf', 'annotate', '--stdio', '--stdio-color', 'never', '--no-source',
                    '--symbol', symbol, '-i', perf_data])


def verify_inputs(out: Path):
    run2 = read_json(RUN2 / 'build.json')
    current = read_json(CURRENT / 'build.json')
    prior = read_json(OLD_PROFILES / 'static.json')
    current_report = read_json(CURRENT / 'report.json')
    code_counts = read_json(OLD_PROFILES / 'counts.json')
    expected = {
        'grhsim': (Path(current['binaries']['grhsim_shared_equality']['path']),
                   CURRENT / 'grhsim_shared_equality-perf.data',
                   CURRENT / 'grhsim_shared_equality-perf.txt',
                   CURRENT / 'runs/perf-record/grhsim_shared_equality/result.json'),
        'verilator': (Path(run2['binaries']['verilator']['path']),
                      OLD_PROFILES / 'verilator-perf.data', OLD_PROFILES / 'verilator-perf.txt',
                      OLD_PROFILES / 'runs/sample/verilator/result.json'),
        'verilator-original': (Path(run2['binaries']['verilator-original']['path']),
                      OLD_PROFILES / 'verilator-original-perf.data', OLD_PROFILES / 'verilator-original-perf.txt',
                      OLD_PROFILES / 'runs/sample/verilator-original/result.json'),
    }
    if current['flags'] != run2['flags'] or current['cxx'] != run2['cxx']:
        raise ValueError('GrhSIM and Verilator build compiler/flags differ')
    if Path(current['baseline']).resolve() != RUN2.resolve():
        raise ValueError('current GrhSIM build does not reference the frozen run2 baseline')
    for rtl in run2['rtl']:
        if identity(Path(rtl['path'])) != rtl:
            raise ValueError('frozen RTL input mismatch: ' + rtl['path'])
    normalized_rtl = run2['normalization']['rtl']
    if identity(Path(normalized_rtl['path'])) != normalized_rtl:
        raise ValueError('frozen normalized RTL input mismatch')
    if identity(Path(current['graph']['path'])) != current['graph']:
        raise ValueError('current GrhSIM graph input mismatch')
    if current_report['functional']['cycles'] != 3376065:
        raise ValueError('unexpected current CoreMark cycle count')
    result = {}
    for backend, (binary, perf_data, perf_text, sample_path) in expected.items():
        manifest_entry = (current['binaries']['grhsim_shared_equality'] if backend == 'grhsim'
                          else run2['binaries'][backend])
        actual = identity(binary)
        if actual != manifest_entry:
            raise ValueError('frozen binary mismatch for ' + backend)
        if backend != 'grhsim':
            profile_entry = prior['models'][backend]['binary']
            if actual != profile_entry:
                raise ValueError('Verilator profile binary SHA differs for ' + backend)
        sample = read_json(sample_path)
        if sample['binary']['sha256'] != actual['sha256'] or sample['cycles'] != 3376065:
            raise ValueError('profile sample does not match binary/workload for ' + backend)
        if sample['placement_errors'] or sample['audit']['start']['placement'] != dict(
                threads=1, cpu=96, affinity_count=1, aslr_disabled=True):
            raise ValueError('profile placement invalid for ' + backend)
        trace = (current_report['functional']['trace_sha256'] if backend == 'grhsim'
                 else code_counts[backend]['coremark']['trace']['sha256'])
        if trace != EXPECTED_TRACE:
            raise ValueError('CoreMark trace differs for ' + backend)
        if not perf_data.is_file() or not perf_text.is_file():
            raise ValueError('missing existing perf input for ' + backend)
        result[backend] = dict(binary=actual, perf_data=identity(perf_data), perf_report=identity(perf_text),
            source_sample=identity(sample_path), sample_cycles=sample['cycles'], trace_sha256=trace,
            placement=sample['audit']['start']['placement'], cpu288_idle=sample['cpu_idle_percent']['288'])
    return result, run2, current, prior


def elf_sections(binary: Path):
    result = []
    for line in command(['size', '-A', binary]).splitlines():
        match = re.match(r'^(\S+)\s+(\d+)\s+(\d+)$', line.strip())
        if match:
            result.append(dict(section=match[1], bytes=int(match[2]), address=int(match[3])))
    return result


def run(out: Path):
    if out.exists(): raise FileExistsError('output directory must be new: ' + str(out))
    identities, run2, current, prior = verify_inputs(out)
    normalized_rtl = run2['normalization']['rtl']
    out.mkdir(parents=True)
    (out / 'disassembly').mkdir(); (out / 'annotations').mkdir()
    backends = {
        'grhsim': (Path(identities['grhsim']['binary']['path']), identities['grhsim']['perf_data']['path'],
                   identities['grhsim']['perf_report']['path']),
        'verilator': (Path(identities['verilator']['binary']['path']), identities['verilator']['perf_data']['path'],
                   identities['verilator']['perf_report']['path']),
        'verilator-original': (Path(identities['verilator-original']['binary']['path']),
                   identities['verilator-original']['perf_data']['path'],
                   identities['verilator-original']['perf_report']['path']),
    }
    result = {}
    tool_versions = {
        program: tool_version(program)
        for program in ('llvm-objdump', 'llvm-addr2line', 'perf', 'nm', 'size')
    }
    for backend, (binary, perf_data, perf_text) in backends.items():
        symbols = function_symbols(binary)
        profile = perf_symbols(Path(perf_text))
        selected = select_symbols(backend, symbols, profile)
        by_symbol = {row['symbol']: row for row in symbols}
        functions = []
        for index, symbol_row in enumerate(selected):
            symbol = symbol_row['symbol']
            asm = disassemble(binary, symbol_row)
            rows = instructions(asm)
            if not rows: raise ValueError('disassembler returned no instructions: ' + symbol)
            stem = f'{index:02d}-{symbol_row["address"]:x}'
            (out / 'disassembly' / f'{backend}-{stem}.asm').write_text(asm)
            annotation_text = annotate(binary, Path(perf_data), symbol)
            (out / 'annotations' / f'{backend}-{stem}.txt').write_text(annotation_text)
            annotations = annotation(annotation_text)
            hot_rows = sorted(annotations, key=lambda row: -row['function_percent'])[:12]
            locations = source_locations(binary, [row['address'] for row in hot_rows])
            for hot_row, location in zip(hot_rows, locations):
                hot_row['source'] = location
            profile_percent = next((row['percent'] for row in profile if row['symbol'] == symbol), None)
            functions.append(dict(symbol=symbol, address=symbol_row['address'], bytes=symbol_row['bytes'],
                profile_symbol_percent=profile_percent, static=instruction_shape(rows),
                annotation_instruction_samples=len(annotations), annotation_top=hot_rows,
                disassembly=identity(out / 'disassembly' / f'{backend}-{stem}.asm'),
                annotation=identity(out / 'annotations' / f'{backend}-{stem}.txt')))
        model_symbols = []
        for row in symbols:
            name = row['symbol']
            model = (name == 'GrhSIM_Cv32Bench::eval()' or name.startswith('GrhSIM_Cv32Bench::eval_compute_batch_') or
                     name.startswith('GrhSIM_Cv32Bench::eval_commit_batch_')) if backend == 'grhsim' else (
                     name.startswith('VCv32Bench___024root___') and any(token in name for token in
                     ('___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if model: model_symbols.append(row)
        selected_totals = {key: sum(function['static'][key] for function in functions)
                           for key in ('instructions', 'branches', 'conditional_branches', 'calls',
                                       'returns', 'memory_operand_instructions',
                                       'stack_operand_instructions', 'vector_or_mask_instructions',
                                       'compare_or_test', 'cmov_or_setcc')}
        result[backend] = dict(binary=identities[backend]['binary'], perf_data=identities[backend]['perf_data'],
            perf_report=identities[backend]['perf_report'],
            sections=elf_sections(binary), model_text_bytes=sum(row['bytes'] for row in model_symbols),
            largest_symbols=sorted(symbols, key=lambda row: -row['bytes'])[:16],
            model_symbols=model_symbols, profile_top=profile[:16], selected_function_static_totals=selected_totals,
            functions=functions)
    source_paths = set()
    for model in result.values():
        for function in model['functions']:
            for row in function['annotation_top']:
                location = row['source']['location']
                source_path, separator, _ = location.rpartition(':')
                if separator and Path(source_path).is_file():
                    source_paths.add(Path(source_path).resolve())
    source_files = [identity(path) for path in sorted(source_paths)]
    save(out / 'inputs.json', dict(binaries=identities, run2_manifest=identity(RUN2 / 'build.json'),
        current_manifest=identity(CURRENT / 'build.json'), profile_static=identity(OLD_PROFILES / 'static.json'),
        profile_counts=identity(OLD_PROFILES / 'counts.json'), current_report=identity(CURRENT / 'report.json'),
        source_revisions={key: run2[key] for key in ('wolvrix', 'cv32e40p', 'core_v_verif')},
        source_rtl=run2['rtl'], normalized_rtl=normalized_rtl, grhsim_graph=current['graph'],
        analysis_driver=identity(Path(__file__).resolve()), tool_versions=tool_versions,
        source_files=source_files,
        flags=run2['flags'], cxx=run2['cxx'], cpu='node030 CPU96 / NUMA1',
        profile_note='Existing samples are not same-time paired. Use each profile to rank hot instructions only; do not compare profile percentages causally.'))
    current_report = read_json(CURRENT / 'report.json')
    prior_report = read_json(OLD_PROFILES / 'report.json')
    report = dict(models=result,
        wall_ratios={'grhsim_over_normalized_verilator': current_report['versus_verilator']['wall_s'],
                     'grhsim_over_original_verilator': current_report['versus_verilator_original']['wall_s']},
        host_instructions_per_guest_cycle={'grhsim_current': current_report['diagnostics']['grhsim_shared_equality']['counters']['instructions:u']['per_guest_cycle'],
            'normalized_verilator': prior_report['diagnostics']['verilator']['stat']['instructions:u']['per_guest_cycle'],
            'original_verilator': prior_report['diagnostics']['verilator-original']['stat']['instructions:u']['per_guest_cycle']},
        conclusions_scope='Static instruction and symbol facts are exact for the frozen ELF. Existing perf annotations rank hot code within each separately collected profile; profile percentages are not cross-run causal comparisons.')
    save(out / 'report.json', report)
    print(json.dumps(dict(model_text_bytes={k:v['model_text_bytes'] for k,v in result.items()},
        top={k:[(x['symbol'],x['profile_symbol_percent'],x['static']['instructions']) for x in v['functions'][:5]]
             for k,v in result.items()}, instructions=report['host_instructions_per_guest_cycle']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/binary-shape-v1')
    args = parser.parse_args()
    run(args.output.resolve())
