#!/usr/bin/env python3
"""Offline analysis of frozen aligned-array-read models, without simulation."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save
from grhsim_elf_section_identity import sections
from xiangshan_cv32_structure import machine
from aligned_array_slice_compare import check_xs, contract, XS_BASE, BASE, CANDIDATE


def read(path):
    return json.loads(path.read_text())


def xs(out):
    check_xs(out); target = out / 'candidate'; dest = out / 'machine-evidence'; dest.mkdir(exist_ok=True)
    binary = target / 'emu/grhsim-compile/emu'
    cached = dest / 'candidate.json'
    if cached.exists():
        current = read(cached); assert current['binary'] == identity(binary)
    else:
        current = machine(binary); save(cached, current)
    before = read(XS_BASE / 'offline-structure/candidate.json')['machine']
    totals = {phase: {key: dict(before=value, after=current['totals'][phase].get(key, 0),
                     percent=100*(current['totals'][phase].get(key, 0)/value-1))
                     for key, value in before['totals'][phase].items() if value}
              for phase in ('compute', 'commit', 'eval')}
    symbols = {}
    for line in subprocess.check_output(['nm', '-S', '-C', '--defined-only', str(binary)], text=True).splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4: symbols[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    name = 'GrhSIM_SimTop::eval_compute_batch_12()'
    address, size = symbols[name]
    command = ['objdump', '-d', '-w', '-C', '--no-show-raw-insn', '--start-address='+str(address),
               '--stop-address='+str(address+size), str(binary)]
    text = subprocess.check_output(command, text=True); (dest / 'bitmapcache-batch.s').write_text(text)
    rows = [(int(m[1], 16), m[2]) for m in re.finditer(r'(?m)^\s*([0-9a-f]+):\s+(.+)$', text)]
    # Header identity preserves the independently compiled TNO0046 offsets.
    assert (target / 'model/grhsim_SimTop.hpp').read_bytes() == (out / 'full/model/grhsim_SimTop.hpp').read_bytes()
    matches = [i for i, (_, op) in enumerate(rows) if re.search(r',0xe192c\(%r\w+\)', op)]
    assert len(matches) == 1
    index = matches[0]
    window = rows[max(0, index-20):index+1]
    (dest / 'bitmapcache-window.s').write_text(''.join(f'{addr:x}:\t{op}\n' for addr, op in window))
    core = window[-8:]
    assert core[0][0] == 0xe5e2b4 and core[-1][0] == 0xe5e2d8
    assert not any(op.startswith('j') for _, op in core)
    core_path = dest / 'bitmapcache-core.s'
    core_path.write_text(''.join(f'{addr:x}:\t{op}\n' for addr, op in core))
    save(out / 'bitmapcache-core-evidence.json', dict(old_static_instructions=17, old_conditional_branches=2,
        candidate_core_static_instructions=len(core), candidate_core_conditional_branches=0,
        candidate_core=identity(core_path),
        old_evidence=identity(ROOT / 'build/xs/cross-design-explanation-v1/report.json'),
        note='Equivalent result extraction, excluding source construction. Old count contains both alternatives; no runtime frequency claim.'))
    source = target / 'model/grhsim_SimTop_sched_12.cpp'; code = source.read_text()
    position = code.index('// op _op_12496825 [kSliceArray]')
    block = code[position:code.index('\n            // op ', position+1)]
    assert all(token in block for token in ('_val_11840339', 'grhsim_aligned_array_slice_words<4u>',
        'value_words_2_slots_[732]', 'value_u64_slots_[8603]', 'value_u8_slots_[2888]'))
    (dest / 'bitmapcache-source.txt').write_text(block + '\n')
    save(out / 'machine-analysis.json', dict(status='pass', totals=totals,
        bitmapcache=dict(source=identity(source), line=code.count('\n', 0, position)+1,
            window=identity(dest / 'bitmapcache-window.s'), result_offset='0xe192c',
            array_offset='0x1f9c68', index_offset='0x12f680'),
        before=identity(XS_BASE / 'offline-structure/candidate.json'), candidate=identity(dest / 'candidate.json'),
        sources=identity(target / 'model-sources.json'), binary=identity(binary), script=identity(Path(__file__).resolve()),
        limits='Static instruction positions, not runtime frequencies. The saved window includes neighbouring work.'))
    print('XS ELF and bitmapcache source correspondence complete', flush=True)


def cv(out):
    from cv32e40p_event_regions_compare import check
    build = check(out); old = out / BASE; new = out / CANDIDATE
    files = {p.name: p.read_bytes() == (new / p.name).read_bytes() for p in old.glob('*.cpp')}
    result = {name: sections(build['binaries'][name]['path']) for name in (BASE, CANDIDATE)}
    assert contract(new)['sites'] == 0 and all(files.values()) and result[BASE] == result[CANDIDATE]
    save(out / 'code-identity.json', dict(status='pass', cpp_files_equal=files, elf_sections=result,
        binaries=[build['binaries'][name] for name in (BASE, CANDIDATE)], script=identity(Path(__file__).resolve()),
        note='No CV32 sites. The unused new runtime template adds no allocated code/data; timing variation is not optimization benefit.'))
    print('CV32 model C++ and allocated code/data sections are identical', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=('xs', 'cv'))
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args(); {'xs': xs, 'cv': cv}[args.model](args.source.resolve())
