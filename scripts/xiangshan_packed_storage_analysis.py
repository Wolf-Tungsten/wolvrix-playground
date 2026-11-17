#!/usr/bin/env python3
"""Offline source/ELF evidence for the two frozen packed-storage experiments."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import CXX, ROOT
from grhsim_single_baseline import identity, save
from xiangshan_cv32_compare import verify_identity
from xiangshan_cv32_structure import cpp, machine
from xiangshan_shared_layout_audit import arrays

FULL = ROOT / 'build/xs/cv32-transfer-20261116-v3/after'


def read(path):
    return json.loads(Path(path).read_text())


def group_text(folder, number):
    token = '// Supernode ' + str(number) + ':'
    for path in sorted(folder.glob('*_sched_*.cpp')):
        code = path.read_text()
        start = code.find(token)
        if start < 0:
            continue
        end = re.search(r'// Supernode \d+:|void GrhSIM_', code[start + len(token):])
        end = start + len(token) + end.start() if end else len(code)
        return path, code.count('\n', 0, start) + 1, code[start:end]
    raise ValueError('missing group ' + str(number))


def offsets(model, output, fields):
    source = output.with_suffix('.cpp')
    assembly = output.with_suffix('.s')
    source.write_text('#include "' + str(model / 'model/grhsim_SimTop.hpp') + '"\n' +
        ''.join('extern "C" std::size_t q_' + str(i) + '() { return __builtin_offsetof(GrhSIM_SimTop, ' +
                field + '); }\n' for i, field in enumerate(fields)))
    command = [str(CXX), '-std=c++20', '-O2', '-fno-access-control', '-Wno-invalid-offsetof',
               '-S', str(source), '-o', str(assembly)]
    subprocess.run(command, check=True, capture_output=True)
    text = assembly.read_text()
    result = {}
    for i, field in enumerate(fields):
        body = re.search(r'(?m)^q_' + str(i) + r':(.*?)(?=^\.Lfunc_end)', text, re.S)
        if body is None:
            raise ValueError('missing offsetof probe')
        match = re.search(r'\bmov[lq]\s+\$(\d+),\s*%[er]ax', body[1])
        if not match:
            raise ValueError('unrecognized offset constant: ' + body[1])
        result[field] = int(match[1])
    return dict(offsets=result, source=identity(source), assembly=identity(assembly), command=command)


def disassemble(model, batch, destination):
    binary = Path(read(model / 'binary.json')['path'])
    symbols = subprocess.check_output(['nm', '--defined-only', str(binary)], text=True)
    choices = [line.split()[-1] for line in symbols.splitlines()
               if line.split()[-1].endswith('eval_compute_batch_' + str(batch) + 'Ev')
               and line.split()[-2] in ('t', 'T')]
    if len(choices) != 1:
        raise ValueError('ambiguous batch symbol')
    command = ['objdump', '-d', '-w', '--no-show-raw-insn', '--disassemble=' + choices[0], str(binary)]
    with destination.open('w') as stream:
        subprocess.run(command, stdout=stream, check=True)
    text = destination.read_text()
    counts = Counter(re.findall(r'(?m)^\s*[0-9a-f]+:\s+(\w+)', text))
    return dict(file=identity(destination), instruction_mnemonics=dict(counts),
                vpinsrb=counts['vpinsrb'], command=command)


def rob_calls(model, output, label, functions):
    path, line, code = group_text(model / 'model', 94733)
    prefix = '\n'.join(path.read_text().splitlines()[:line])
    word = int(re.findall(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\]', prefix)[-1])
    bit = int(re.search(r'activeWordFlags & UINT8_C\((\d+)\)', code)[1])
    probe = offsets(model, output / (label + '-active-offset'), ['supernode_active_curr_'])
    address = probe['offsets']['supernode_active_curr_'] + word
    lines = (output / (label + '-batch9.s')).read_text().splitlines()
    begin = next(i for i, s in enumerate(lines) if re.search(r'movb\s+\$0x0,0x' + f'{address:x}' + r'\(%r(?!sp)\w+\)', s))
    branch = next(i for i in range(begin, begin + 15) if re.search(r'test\s+\$0x' + f'{bit:x}' + ',', lines[i]))
    assert re.search(r'test\s+\$0x' + f'{bit * 2:x}' + ',', lines[branch + 2])
    target = re.search(r'jne\s+([0-9a-f]+)', lines[branch + 1])[1]
    stop = re.search(r'jne\s+([0-9a-f]+)', lines[branch + 3])[1]
    start = next(i for i, s in enumerate(lines) if s.strip().startswith(target + ':'))
    end = next(i for i, s in enumerate(lines) if s.strip().startswith(stop + ':'))
    body = lines[start:end]
    assert re.search(r'test\s+\$0x' + f'{bit * 2:x}' + ',', body[-2]) and '\tje ' in body[-1]
    witness = output / (label + '-rob-arrays-block.s')
    witness.write_text('\n'.join(body) + '\n')
    loads = [s for s in body if re.search(r'\(%rsp,%r\w+,8\)', s)]
    callees = re.findall(r'\bcall\s+[0-9a-f]+ <(_ZZN13GrhSIM_SimTop\S+)>', '\n'.join(body))
    helpers = []
    binary = read(model / 'binary.json')['path']
    for i, symbol in enumerate(callees):
        demangled = subprocess.check_output(['c++filt', symbol], text=True).strip()
        destination = output / (label + '-rob-helper-' + str(i) + '.s')
        command = ['objdump', '-d', '-w', '--no-show-raw-insn', '--disassemble=' + symbol, binary]
        with destination.open('w') as stream:
            subprocess.run(command, stdout=stream, check=True)
        indexed = [s for s in destination.read_text().splitlines() if re.search(r'\(%rsp,%r\w+,8\)', s)]
        row = functions[demangled]
        helpers.append(dict(symbol=demangled, file=identity(destination),
            entry_stack_subtractions=row['entry_stack_subtractions'], counts=row['counts'], indexed_stack_loads=indexed))
    return dict(activity_word=word, bit=bit, offset_probe=probe, address=hex(address),
        start=target, end_exclusive=stop, file=identity(witness), instruction_window=len(body),
        caller_indexed_stack_loads=loads, outlined_helpers=helpers,
        note='Caller frame reduction is not removal of construction: inspect outlined helpers and their own frames.')


def audit(source, candidate='candidate', baseline=FULL):
    output = source / ('machine-evidence' if candidate == 'candidate' else candidate + '-evidence')
    output.mkdir(exist_ok=True)
    models = {'full': baseline, 'candidate': source / candidate}
    feature = read(source / 'policy.json').get('feature', candidate)
    result = dict(feature=feature, mode='offline_no_simulator_execution', models={},
        inputs=[identity(source / n) for n in ('build.json', 'structure.json', 'policy.json')])
    invariants = None
    for label, model in models.items():
        binary = read(model / 'binary.json')
        verify_identity(binary)
        for record in read(model / 'model-sources.json'):
            verify_identity(record)
        cached = output / (label + '-structure.json')
        if cached.exists() and read(cached)['machine']['binary'] == binary:
            cached_data = read(cached)
            structure, elf = cached_data['cpp'], cached_data['machine']
        else:
            structure = cpp(model / 'model')
            elf = machine(Path(binary['path']))
            save(cached, dict(cpp=structure, machine=elf))
        guards = structure['counts']
        if invariants is None:
            invariants = guards
        elif guards != invariants:
            raise ValueError('activity, check or cache site counts changed')
        row = dict(binary=binary, counts=guards, totals=elf['totals'],
            audit=identity(output / (label + '-structure.json')),
            compute_lambda_functions=sum('::$_' in name and value['phase'] == 'compute'
                                         for name, value in elf['functions'].items()),
            batch9_frame=elf['functions']['GrhSIM_SimTop::eval_compute_batch_9()']['entry_stack_subtractions'])
        for batch in (5, 9):
            row['batch' + str(batch)] = disassemble(model, batch, output / (label + '-batch' + str(batch) + '.s'))
        path, line, ftq = group_text(model / 'model', 93956)
        packed = arrays(ftq)
        assert len(packed) == 64 and all(a['count'] == 64 and a['bits'] == 8 for a in packed)
        first = packed[0]
        # The source is emitted in concat operand order, so reconstruct lane order.
        fields = ['state_logic_storage_.' + field for _, field in
                  sorted(zip(first['lane_indices'], first['state_fields']))]
        fields.append(first['name'])
        probe = offsets(model, output / (label + '-ftq-offsets'), fields)
        values = [probe['offsets'][field] for field in fields[:-1]]
        row['ftq'] = dict(source=identity(path), line=line, arrays=len(packed),
            first_array=first['name'], lane_offsets=values,
            lane_strides=sorted({b - a for a, b in zip(values, values[1:])}), probe=probe)
        assembly = (output / (label + '-batch5.s')).read_text().splitlines()
        destination = probe['offsets'][first['name']]
        stores = [i for i, line in enumerate(assembly) if re.search(
            r'\bv\w+\s+%[xyz]mm\d+,0x' + f'{destination:x}' + r'\(', line)]
        stop = stores[-1]
        starts = [i for i, line in enumerate(assembly[:stop]) if f'0x{values[0]:x}(' in line]
        start = starts[-1]
        window = assembly[start:stop + 1]
        witness = output / (label + '-ftq-first-pack.s')
        witness.write_text('\n'.join(window) + '\n')
        row['ftq']['first_pack'] = dict(file=identity(witness), instructions=len(window),
            vpinsrb=sum('vpinsrb' in line for line in window),
            note='Window from first source address to final vector store; may contain unrelated instructions.')
        path, line, rob = group_text(model / 'model', 94733)
        local = arrays(rob)
        assert len(local) == 8 and all(a['local'] and a['bytes'] == 2048 for a in local)
        row['rob'] = dict(source=identity(path), line=line,
            array_count=len(local), declared_bytes=sum(a['bytes'] for a in local),
            scoped_selects=rob.count('// Scoped packed array:'),
            last_uses_nonoverlapping=all(a['last'] < b['first'] for a, b in zip(local, local[1:])))
        if feature == 'scope':
            row['rob']['call_evidence'] = rob_calls(model, output, label, elf['functions'])
        result['models'][label] = row
    result['status'] = 'pass'
    result['limits'] = ['Static ELF counts are not execution counts or cycle attribution.',
        'Batch frames include other groups; the FTQ/ROB witnesses are the predeclared TNO0039 examples.',
        'The two emitter options are tested independently; no results feed generation or select a combined candidate.']
    result['script'] = identity(Path(__file__).resolve())
    save(output / 'report.json', result)
    print(json.dumps({label: dict(stride=row['ftq']['lane_strides'],
        batch5_vpinsrb=row['batch5']['vpinsrb'], batch9_frame=row['batch9_frame'],
        rob_scopes=row['rob']['scoped_selects']) for label, row in result['models'].items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--candidate', default='candidate')
    parser.add_argument('--baseline', type=Path, default=FULL)
    args = parser.parse_args()
    audit(args.source.resolve(), args.candidate, args.baseline.resolve())
