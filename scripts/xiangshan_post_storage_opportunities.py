#!/usr/bin/env python3
"""Offline witnesses after TNO0040; compiler probes only, no model execution.

This is an audit of frozen examples, not a production eligibility rule. In
particular, source and static ELF counts do not estimate runtime frequency.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import CXX, ROOT
from grhsim_single_baseline import identity, save
from xiangshan_cv32_compare import verify_identity
from xiangshan_packed_storage_analysis import group_text, offsets
from xiangshan_shared_layout_audit import arrays, literal_notifications


def read(path):
    return json.loads(path.read_text())


def instructions(text):
    return [(int(m[1], 16), m[2].strip()) for m in
            re.finditer(r'(?m)^\s*([0-9a-f]+):\s+(.+)$', text)]


def scoped_inventory(folder):
    pattern = re.compile(r'// Scoped packed array: value=(\d+) slice=(\d+) lanes=(\d+)\n'
                         r'(.*?)\n        \}\(\);', re.S)
    rows = []
    for path in sorted(folder.glob('*_sched_*.cpp')):
        text = path.read_text()
        for match in pattern.finditer(text):
            body = match[4]
            bank = arrays(body)
            assert len(bank) == 1
            array = bank[0]
            assert sorted(array['lane_indices']) == list(range(array['count']))
            index = re.search(r'static_cast<std::size_t>\(([^\n]+)\);', body)[1]
            rows.append(dict(file=path.name, line=text.count('\n', 0, match.start()) + 1,
                             value=int(match[1]), result=int(match[2]), index=index,
                             **{k: array[k] for k in ('name', 'bits', 'count', 'bytes',
                                                     'all_lanes_single_state')},
                             distinct_state_fields=len(set(array['state_fields']))))
    shapes = Counter((r['bits'], r['count'], r['distinct_state_fields'],
                      r['all_lanes_single_state']) for r in rows)
    return dict(sites=len(rows), all_state_sites=sum(r['all_lanes_single_state'] for r in rows),
                shapes=[dict(bits=k[0], lanes=k[1], distinct_state_fields=k[2],
                             all_lanes_single_state=k[3], sites=n) for k, n in sorted(shapes.items())],
                rows=rows)


def ftq_evidence(root, out):
    path, line, code = group_text(root / 'layout/model', 93956)
    bank = arrays(code)
    assert len(bank) == 64 and all(a['all_lanes_single_state'] and not a['local'] for a in bank)
    assert all(sorted(a['lane_indices']) == list(range(64)) for a in bank)
    assert len(set(f for a in bank for f in a['state_fields'])) == 4096
    op_kinds = Counter(re.findall(r'// op \S+ \[(k\w+)\]', code))
    assert op_kinds == {'kRegisterReadPort': 4096, 'kConcat': 64}
    historical_map = ROOT / 'build/xs/shared-local-cpp-elf-analysis-v1/sample-off-op-map.json'
    old = read(historical_map)['80580']
    assert {r['op'] for r in old} == set(re.findall(r'// op (\S+) \[k\w+\]', code))
    packet = read(root / 'layout-evidence/report.json')['models']['candidate']['ftq']
    first = packet['lane_offsets'][0]
    # TNO0040 proves all 64 bundles use contiguous, disjoint states. Locate the
    # final bundle read and then the next supernode's guard, retaining the exact
    # interval in the report rather than assigning an entire batch to this group.
    asm_path = root / 'layout-evidence/candidate-batch5.s'
    rows = instructions(asm_path.read_text())
    start = next(i for i, (_, op) in enumerate(rows) if op.startswith(f'vpandq 0x{first:x}('))
    stop = next(i for i in range(start, len(rows)) if re.match(r'test\s+\$0x20,%al', rows[i][1]))
    window = rows[start:stop]
    reads = [op for _, op in window if op.startswith('vpandq ')]
    assert len(reads) == 64
    assert [int(re.search(r'0x([0-9a-f]+)\(', op)[1], 16) for op in reads] == [first + i * 64 for i in range(64)]
    redundant = []
    for i, (address, op) in enumerate(window[:-2]):
        zero = re.fullmatch(r'vmovdqu64 %zmm0,(0x[0-9a-f]+\(%rdi\))', op)
        if not zero:
            continue
        following, write = window[i + 1][1], window[i + 2][1]
        load = re.fullmatch(r'vpandq (0x[0-9a-f]+)\(%rdi\),%zmm1,(%zmm\d+)', following)
        assert load and write == 'vmovdqu64 ' + load[2] + ',' + zero[1]
        dest = int(re.search(r'0x([0-9a-f]+)', zero[1])[1], 16)
        assert dest + 64 <= first or dest >= first + 4096
        redundant.append(dict(address=hex(address), destination=zero[1], overwrite=write))
    # zmm0 is zeroed at group entry, and is not redefined until the final
    # selected-data load, immediately after the last redundant zero store.
    assert rows[start - 2][1] == 'vpxor  %xmm0,%xmm0,%xmm0'
    assert all(not op.endswith(',%zmm0') for _, op in window[:-2])
    ors = [op for _, op in window if re.match(r'or(?:b)?\s+\$0x', op)]
    activity_stores = [op for _, op in window if re.match(r'(?:orb\s+\$0x\w+|mov\s+%[cd]l),0x', op)]
    address_counts = Counter(re.search(r'(0x[0-9a-f]+)\(%rdi\)', op)[1] for op in activity_stores)
    target = out / 'layout-ftq-body.s'
    target.write_text(''.join(f'{addr:x}:\t{op}\n' for addr, op in window))
    return dict(source=identity(path), line=line, source_notifications=literal_notifications(code),
                assembly_input=identity(asm_path), window=identity(target),
                start=hex(window[0][0]), end_exclusive=hex(rows[stop][0]),
                window_instructions=len(window), full_vector_reads=len(reads),
                full_vector_stores=sum(op.startswith('vmovdqu64 ') for _, op in window),
                redundant_zero_stores=len(redundant), redundant_zero_bytes=64 * len(redundant),
                zero_overwrite_witnesses=redundant, literal_or_instructions=len(ors),
                activity_byte_writes=len(activity_stores), activity_bytes=len(address_counts),
                independent_source_fields=4096,
                op_kinds=dict(op_kinds), historical_off_group_count=len({r['group'] for r in old}),
                historical_op_map=identity(historical_map),
                limit='Straight-line body, excluding entry/exit guard and constant setup. No execution frequency.')


def rob_evidence(root, out):
    path, line, code = group_text(root / 'scope/model', 94733)
    bank = arrays(code)
    assert len(bank) == 8 and all(a['all_lanes_single_state'] for a in bank)
    fields = []
    mapping = []
    for a in bank:
        lanes = dict(zip(a['lane_indices'], a['state_fields']))
        assert sorted(lanes) == list(range(256))
        assert len({lanes[i] for i in range(160)}) == 160
        assert all(lanes[i] == lanes[0] for i in range(160, 256))
        original = re.findall(re.escape(a['name']) + r'\[(\d+)\] = ([^\n]+);', code)
        assert all(expr == 'static_cast<std::uint64_t>((state_logic_storage_.' + lanes[int(i)] + '))'
                   for i, expr in original)
        mapping.append(dict(name=a['name'], fields=[lanes[i] for i in range(160)],
                            repeated_lanes=list(range(160, 256)), repeated_source=lanes[0]))
        fields.extend('state_logic_storage_.' + lanes[i] for i in range(160))
    indices = re.findall(r'const std::size_t scoped_packed_index_\d+ = static_cast<std::size_t>\(([^\n]+)\);', code)
    assert indices == ['value_u8_slots_[12490]'] * 8
    probe = offsets(root / 'fixed', out / 'rob-field-offsets', fields)
    for m in mapping:
        m['offsets'] = [probe['offsets']['state_logic_storage_.' + f] for f in m['fields']]
        m['adjacent_stride_counts'] = dict(Counter(b - a for a, b in zip(m['offsets'], m['offsets'][1:])))
    # A typed pointer-to-member table is valid for distinct struct members. It
    # does not rely on pointer arithmetic across neighbouring members. Compile
    # one representative read, but never link/run a model or use this as an
    # eligibility/threshold search. Exhaustive static mapping checks all indices.
    source = out / 'selected-member-probe.cpp'
    source.write_text('#include "' + str(root / 'fixed/model/grhsim_SimTop.hpp') + '"\n'
        'using S = GrhSIM_SimTop::state_logic_storage_t;\n'
        'extern "C" std::uint64_t selected_member_probe(const S& state, std::uint8_t index) {\n'
        '    static constexpr std::uint64_t S::* members[] = {\n' +
        ',\n'.join('        &S::' + f for f in mapping[0]['fields']) + '\n    };\n'
        '    const unsigned lane = index < 160u ? index : 0u;\n'
        '    return state.*members[lane];\n}\n')
    obj, asm = out / 'selected-member-probe.o', out / 'selected-member-probe.s'
    command = [str(CXX), '-std=c++20', '-O3', '-march=native', '-fno-access-control', '-c', str(source), '-o', str(obj)]
    subprocess.run(command, check=True, capture_output=True)
    disasm = ['objdump', '-drw', '--no-show-raw-insn', '--disassemble=selected_member_probe', str(obj)]
    with asm.open('w') as stream:
        subprocess.run(disasm, check=True, stdout=stream)
    selected = instructions(asm.read_text())
    sizes = subprocess.check_output(['nm', '-S', '--size-sort', str(obj)], text=True)
    table = next(line.split() for line in sizes.splitlines() if line.endswith('E7members'))
    assert selected and not any(re.match(r'(call|push|pop)\b', op) for _, op in selected)
    assert not any('%rsp' in op for _, op in selected)
    for index in range(256):
        assert mapping[0]['fields'][index if index < 160 else 0] == dict(zip(bank[0]['lane_indices'], bank[0]['state_fields']))[index]
    call = read(root / 'scope-evidence/report.json')['models']['candidate']['rob']['call_evidence']
    for helper in call['outlined_helpers']:
        verify_identity(helper['file'])
    return dict(source=identity(path), line=line, arrays=8, lane_count=256, distinct_lanes_per_array=160,
                shared_index=indices[0], mapping=mapping, offsetof_probe=probe,
                current_helpers=call['outlined_helpers'], caller_window_instructions=call['instruction_window'],
                selected_member_probe=dict(source=identity(source), object=identity(obj), assembly=identity(asm),
                    command=command, disassemble_command=disasm, static_instructions=len(selected),
                    readonly_table_bytes=int(table[1], 16),
                    static_index_mapping_checks=256, compiler=subprocess.check_output([str(CXX), '--version'], text=True),
                    host=subprocess.check_output(['hostname'], text=True).strip(),
                    limit='Isolated compiler probe, not integrated/generated candidate, no simulator or timing. '
                          'Does not prove snapshot/alias eligibility for arbitrary graphs.'))


def audit(root, out):
    out.mkdir(parents=True, exist_ok=True)
    inputs = []
    for name in ('fixed', 'layout', 'scope'):
        folder = root / name
        verify_identity(read(folder / 'binary.json'))
        for record in read(folder / 'model-sources.json'):
            verify_identity(record)
        inputs += [identity(folder / n) for n in ('binary.json', 'model-sources.json')]
    inventory = scoped_inventory(root / 'scope/model')
    cv = ROOT / 'build/cv32e40p/packed-storage-fixed-v1/grhsim_ownership_fixed'
    cv_inputs = sorted(cv.glob('*_sched_*.cpp'))
    assert cv_inputs
    cv_counts = Counter()
    for path in cv_inputs:
        code = path.read_text()
        cv_counts['packed_lane_references'] += code.count('packed_array_lanes_')
        cv_counts['scoped_array_sites'] += code.count('// Scoped packed array:')
    result = dict(mode='offline_only_with_compile_only_probe', status='pass', inputs=inputs,
        scope_inventory=inventory, ftq=ftq_evidence(root, out), rob=rob_evidence(root, out),
        cv32=dict(counts=dict(cv_counts), sources=[identity(p) for p in cv_inputs],
                  limit='No packed-lane references in this frozen CV32 model; no timing prediction.'),
        implementation_inputs=[identity(ROOT / p) for p in ('wolvrix/lib/emit/grhsim_cpp.cpp',
                                                           'wolvrix/lib/transform/activity_schedule.cpp')],
        script=identity(Path(__file__)), limits=[
            'Machine/body counts are static and cannot partition measured walltime.',
            'The historical no_shared artifact predates the span lifetime fix; regenerate a corrected control before a new grouping experiment.',
            'Candidate selection must depend on static semantics, not the timing outcomes or example names.'])
    save(out / 'report.json', result)
    print(json.dumps(dict(status=result['status'], scopes=inventory['sites'],
        all_state_sites=inventory['all_state_sites'], ftq_zero_stores=result['ftq']['redundant_zero_stores'],
        ftq_activity_writes=result['ftq']['activity_byte_writes'],
        selected_read_probe_instructions=result['rob']['selected_member_probe']['static_instructions'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/xs/packed-storage-fixed-20261116-v1')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/xs/post-packed-storage-analysis-v1')
    args = parser.parse_args()
    audit(args.source.resolve(), args.output.resolve())
