#!/usr/bin/env python3
"""Compare frozen CV32/XS evidence; compile offsets and disassemble, never simulate.

The addresses below identify the already measured TNO0044 ELF. They are evidence
locators, not optimization decisions or candidates supplied to a generator.
"""
import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess

from cv32e40p_compare import ROOT
from grhsim_single_baseline import identity, save
from xiangshan_cv32_compare import verify_identity
from xiangshan_cv32_lineage_report import rules


def read(path):
    return json.loads(path.read_text())


def delta(before, after):
    return dict(before=before, after=after, percent=(after / before - 1) * 100)


def stacks(model):
    rows = [v for k, v in model['machine']['functions'].items()
            if re.fullmatch(r'GrhSIM_SimTop::eval_compute_batch_\d+\(\)', k)]
    amounts = [sum(v['entry_stack_subtractions']) for v in rows]
    return dict(main_functions=len(rows), median=statistics.median(amounts),
                maximum=max(amounts), over_4096=sum(x > 4096 for x in amounts))


def sections(binary):
    result = {}
    for line in subprocess.check_output(['size', '-A', str(binary)], text=True).splitlines():
        fields = line.split()
        if fields and fields[0] in ('.text', '.rodata'):
            result[fields[0]] = int(fields[1])
    return result


def disassemble(binary, start, size, path):
    cmd = ['objdump', '-d', '-w', '-C', '--no-show-raw-insn',
           '--start-address=' + str(start), '--stop-address=' + str(start + size), str(binary)]
    with path.open('w') as stream:
        subprocess.run(cmd, stdout=stream, check=True)
    rows = []
    for line in path.read_text().splitlines():
        match = re.match(r'^\s*([0-9a-f]+):\s+(.+)$', line)
        if match:
            rows.append((int(match[1], 16), match[2]))
    return rows, cmd


def latest_windows(out, binary, model, machine, inventory):
    symbols = {}
    for line in subprocess.check_output(['nm', '-S', '-C', '--defined-only', str(binary)], text=True).splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    names = {
        'latest-batch12': 'GrhSIM_SimTop::eval_compute_batch_12()',
        'latest-batch19': 'GrhSIM_SimTop::eval_compute_batch_19()',
        'latest-helper19': 'GrhSIM_SimTop::eval_compute_batch_19()::$_0::operator()(unsigned long) const',
    }
    rows = {}; commands = []
    for label, name in names.items():
        rows[label], command = disassemble(binary, *symbols[name], out / (label + '.s'))
        commands.append(command)
    helper = machine['functions'][names['latest-helper19']]
    assert symbols[names['latest-helper19']][0] == 0x1621ea0
    caller = rows['latest-batch19']
    call = next(i for i, (_, op) in enumerate(caller) if re.match(r'call\s+1621ea0\b', op))
    window = caller[call-1600:call]
    stores = []
    for address, op in window:
        match = re.match(r'mov\s+(%r\w+),0x([0-9a-f]+)\(%rsp\)', op)
        if match and 0x16b0 <= int(match[2], 16) < 0x1eb0:
            stores.append(dict(address=address, register=match[1], offset=int(match[2], 16)))
    assert len(stores) == 256
    assert {s['offset'] for s in stores} == set(range(0x16b0, 0x1eb0, 8))
    assert any(re.match(r'lea\s+0x16b0\(%rsp\),%rax', op) for _, op in window)
    assert any(re.match(r'mov\s+%rax,%rdi', op) for _, op in caller[call-8:call])
    first = next(i for i, (addr, _) in enumerate(caller) if addr == stores[0]['address'])
    (out / 'latest-closure-window.s').write_text(''.join(
        f'{addr:x}:\t{op}\n' for addr, op in caller[first-5:call+1]))
    source_site = next(r for r in inventory['indexed_sites'] if r['file'].endswith('_19.cpp'))
    assert source_site['captured_named_snapshots'] == 256

    # Only compile offsetof constants. No generated executable is run.
    fields = ['value_words_2_slots_', 'value_u64_slots_', 'value_u8_slots_']
    probe = out / 'latest-bitmapcache-offsets.cpp'
    probe.write_text('#include "' + str(model / 'grhsim_SimTop.hpp') + '"\n' + ''.join(
        'extern "C" std::size_t q_' + str(i) + '() { return __builtin_offsetof(GrhSIM_SimTop, '
        + field + '); }\n' for i, field in enumerate(fields)))
    assembly = probe.with_suffix('.s')
    command = ['/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++', '-std=c++20', '-O3',
               '-fno-access-control', '-Wno-invalid offsetof'.replace(' ', '-'),
               '-S', str(probe), '-o', str(assembly)]
    subprocess.run(command, check=True); commands.append(command)
    constants = [int(v) for v in re.findall(r'movl\s+\$(\d+),\s*%eax', assembly.read_text())]
    assert len(constants) == 3
    offsets = dict(zip(fields, constants))
    expected = dict(array=constants[0] + 732 * 16, index=constants[1] + 8603 * 8,
                    result=constants[2] + 2888)
    assert expected == dict(array=0x1f9c68, index=0x12f680, result=0xe192c)
    text = (model / 'grhsim_SimTop_sched_12.cpp').read_text()
    pos = text.index('// op _op_12496825 [kSliceArray]')
    block = text[pos:text.index('\n            // op ', pos+1)]
    assert all(s in block for s in ('_val_11840339', 'grhsim_slice_words<1>',
                                    'value_words_2_slots_[732]', 'value_u64_slots_[8603]',
                                    'value_u8_slots_[2888]'))
    (out / 'latest-bitmapcache.cpp.txt').write_text(block + '\n')
    bitmap = []
    for label, low, high in [('entry', 0xe5e683, 0xe5e6c0), ('tail', 0xec7e19, 0xec7e2f)]:
        part = [(a, op) for a, op in rows['latest-batch12'] if low <= a < high]
        (out / ('latest-bitmapcache-' + label + '.s')).write_text(''.join(
            f'{addr:x}:\t{op}\n' for addr, op in part))
        bitmap.extend(part)
    assert len(bitmap) == 17
    assert sum(op.startswith(('je ', 'jne ')) for _, op in bitmap) == 2
    assert all((index * 4) % 64 + 4 <= 64 for index in range(32))
    return dict(closure=dict(source=source_site, pointer_stores=stores, pointer_bytes=2048,
                             helper_static_instructions=helper['counts']['instructions'],
                             helper_stack_subtractions=helper['entry_stack_subtractions']),
                bitmap=dict(offsets=offsets, effective_offsets=expected, static_instructions=17,
                            conditional_branches=2, no_cross_word_proof=True,
                            source_line=text.count('\n', 0, pos)+1), commands=commands,
                limits='Both alternative paths are included in static counts. No runtime frequency or net timing attribution.')


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    old_dir = ROOT / 'build/xs/cv32-transfer-20261116-v3/before'
    new_dir = ROOT / 'build/xs/shared-connected-20261116-v1/candidate'
    old_path = old_dir.parent / 'offline-structure/before.json'
    new_path = new_dir.parent / 'offline-structure/candidate.json'
    old, new = read(old_path), read(new_path)
    verified = {}
    for label, folder, model in [('old', old_dir, old), ('latest', new_dir, new)]:
        verify_identity(model['machine']['binary'])
        sources = read(folder / 'model-sources.json')
        for source in sources:
            verify_identity(source)
        verified[label] = dict(binary=model['machine']['binary'], source_files=len(sources))
    print('Both XS ELF/source manifests verified', flush=True)
    inventory = rules(new_dir / 'model')
    checked = set()
    for path in (new_dir / 'model').glob('*_sched_*.cpp'):
        checked.update(re.findall(r'const bool grhsim_changed_(\d+)\s*=', path.read_text()))
    inventory['unique_scalar_checks'] = len(checked)
    inventory['outlined_word_readers'] = sum('operator()(unsigned long)' in n
        for n in new['machine']['functions'])
    cpp = {k: delta(v, new['cpp']['counts']['compute'][k])
           for k, v in old['cpp']['counts']['compute'].items()}
    machine = {phase: {k: delta(v, new['machine']['totals'][phase][k])
                       for k, v in old['machine']['totals'][phase].items() if v}
               for phase in ('compute', 'commit', 'eval')}
    cv_path = ROOT / 'build/cv32e40p/shared-connected-v1/structure.json'
    cv_build_path = cv_path.with_name('build.json')
    cv = read(cv_path)['models']['grhsim_shared_connected']
    cv_bin = read(cv_build_path)['binaries']['grhsim_shared_connected']
    verify_identity(cv_bin)
    cv_old_path = ROOT / 'build/cv32e40p/run2/build.json'
    cv_old_bin = read(cv_old_path)['binaries']['grhsim']; verify_identity(cv_old_bin)
    binaries = {**{k: v['binary'] for k, v in verified.items()}, 'cv_latest': cv_bin, 'cv_initial': cv_old_bin}
    result = dict(mode='Offline aggregation and current ELF witness verification; no simulator runs',
        xs=dict(identities=verified, cpp=cpp, machine=machine,
                compute_groups=delta(77041, 84690), stacks=dict(old=stacks(old), latest=stacks(new)),
                rules=inventory),
        cv=dict(shape=cv['shape'], views=len(cv['views']), composed=len(cv['composed']),
                families=len(cv['families']), cones=len(cv['cones'])),
        sections={k: dict(binary=v, sections=sections(Path(v['path']))) for k, v in binaries.items()},
        formal_result=read(ROOT / 'build/xs/pre-cv32-vs-connected-8pairs-v1/report.json')['external_wall'])
    result['current_witnesses'] = latest_windows(out, Path(binaries['latest']['path']),
        new_dir / 'model', new['machine'], inventory)
    inputs = [old_path, new_path, cv_path, cv_build_path, cv_old_path,
              ROOT / 'build/xs/pre-cv32-vs-connected-8pairs-v1/report.json',
              ROOT / 'build/xs/cv32-lineage-audit-v1/report.json',
              old_dir / 'model-sources.json', new_dir / 'model-sources.json',
              ROOT / 'scripts/xiangshan_cv32_lineage_report.py', Path(__file__).resolve()]
    result['inputs'] = [identity(p) for p in inputs]
    result['artifacts'] = [identity(p) for p in sorted(out.iterdir()) if p.suffix in ('.s', '.cpp')]
    result['limits'] = ['Static counts are not runtime work or stall fractions.',
        'Historical ablations are not additive; no formal latest-versus-old PMU sample exists here.',
        'CV32 full CoreMark and XS first 100k cycles have different workload and harness boundaries.']
    result['status'] = 'pass'
    save(out / 'report.json', result)
    print('Current C++/ELF witnesses and cross-design report complete', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output.resolve())
