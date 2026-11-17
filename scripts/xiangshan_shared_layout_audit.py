#!/usr/bin/env python3
"""Offline witnesses for shared-region activity, storage layout and array lifetimes.

Reads frozen C++/ELF artifacts and the saved compiler offsetof probes. Does not
execute a simulator, collect profiles, or change a production generation rule.
"""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT
from grhsim_single_baseline import identity, save
from xiangshan_cv32_compare import verify_identity

MODELS = {
    'full': ROOT / 'build/xs/cv32-transfer-20261116-v3/after',
    'off': ROOT / 'build/xs/cv32-ablation-20261116-v2/no_shared',
    'local': ROOT / 'build/xs/shared-cycle-refinement-20261116-v1/candidate',
}
AUDITS = {
    'full': ROOT / 'build/xs/cv32-transfer-20261116-v3/offline-structure/after.json',
    'off': ROOT / 'build/xs/cv32-ablation-20261116-v2/offline-structure/no_shared.json',
    'local': ROOT / 'build/xs/shared-cycle-refinement-20261116-v1/offline-structure/candidate.json',
}
GROUP = re.compile(r'// Supernode (\d+):')
OP = re.compile(r'// op (\S+) \[(k\w+)\]')
FIELD = re.compile(r'state_logic_storage_\.(\w+)')
NOTIFY = re.compile(r'supernode_active_(curr|next)_\[(\d+)u\] \|= UINT8_C\((\d+)\);')
ARRAY = re.compile(r'(?m)^\s*(?:std::array<std::uint(\d+)_t, (\d+)> (packed_array_lanes_local_\w+)\{\};|'
                   r'(packed_array_lanes_\w+) = std::array<std::uint(\d+)_t, (\d+)>\{\};)')


def read(path):
    return json.loads(Path(path).read_text())


def literal_notifications(text):
    sites = NOTIFY.findall(text)
    masks = {}
    for phase, word, mask in sites:
        masks[phase + ':' + word] = masks.get(phase + ':' + word, 0) | int(mask)
    return dict(sites=len(sites), words=len(masks), target_bits=sum(v.bit_count() for v in masks.values()), masks=masks)


def arrays(text):
    result = []
    for match in ARRAY.finditer(text):
        local = match[3] is not None
        bits, count, name = (match[1], match[2], match[3]) if local else (match[5], match[6], match[4])
        fills = list(re.finditer(re.escape(name) + r'\[(\d+)\] = ([^\n]+);', text))
        states = [FIELD.findall(m[2]) for m in fills]
        refs = list(re.finditer(re.escape(name), text))
        result.append(dict(name=name, local=local, bits=int(bits), count=int(count),
                           bytes=int(bits) // 8 * int(count),
                           lane_indices=[int(m[1]) for m in fills],
                           state_fields=[s[0] for s in states if len(s) == 1],
                           all_lanes_single_state=len(fills) == int(count) and all(len(s) == 1 for s in states),
                           first=refs[0].start(), last=refs[-1].end(), references=len(refs)))
    return result


class Sources:
    def __init__(self):
        self.audits = {label: read(path) for label, path in AUDITS.items()}
        self.groups = {label: {g['group']: g for g in a['cpp']['groups']} for label, a in self.audits.items()}
        self.cache = {}

    def group(self, label, group):
        record = self.groups[label][group]
        path = MODELS[label] / 'model' / record['file']
        if path not in self.cache:
            self.cache[path] = path.read_text().splitlines(keepends=True)
        lines = self.cache[path]
        start = record['line'] - 1
        end = next((i for i in range(start + 1, len(lines))
                    if GROUP.search(lines[i]) or lines[i].startswith('void GrhSIM_')), len(lines))
        text = ''.join(lines[start:end])
        word = re.findall(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\]',
                          ''.join(lines[:start]))[-1]
        bit = re.search(r'activeWordFlags & UINT8_C\((\d+)\)', text)[1]
        return dict(path=str(path), line=record['line'], end_line=end,
                    group=group, word=int(word), bit=int(bit)), text


def cv32_contractions():
    directory = ROOT / 'build/cv32e40p/state-expressions-v1'
    before_path = ROOT / 'build/cv32e40p/cross-region-views-v1/unshared-sources.csv'
    after_path = directory / 'sources.csv'
    graph_path = directory / 'grhsim_state_expression_inline/normalized.json'
    before = {r['op_symbol']: int(r['group']) for r in csv.DictReader(before_path.open())}
    after = list(csv.DictReader(after_path.open()))
    graph = read(graph_path)['graphs'][0]
    ops = {o['sym']: o for o in graph['ops']}
    definitions = {value: o['sym'] for o in graph['ops'] for value in o['out']}
    rows = []
    for group in range(29, 35):
        members = {r['op_symbol'] for r in after if int(r['group']) == group}
        edges = []
        for symbol in sorted(members):
            for value in ops[symbol]['in']:
                definition = definitions.get(value)
                if (definition in members and before[definition] != before[symbol]
                        and ops[definition]['kind'] not in ('kConstant', 'kRegisterReadPort')):
                    edges.append(dict(value=value, producer=definition, consumer=symbol))
        rows.append(dict(group=group, ops=len(members), original_groups=len({before[s] for s in members}),
                         internalized_operand_edges=len(edges), examples=edges[:3]))
    return dict(rows=rows, inputs=[identity(p) for p in (before_path, after_path, graph_path)],
                limit='IR operand-edge occurrences, excluding constant and register-read producers. '
                      'Not eliminated machine instructions or an acceptance rule.')


def audit(out):
    sources = Sources()
    inputs = [identity(Path(__file__).resolve())]
    for label, folder in MODELS.items():
        binary = read(folder / 'binary.json')
        verify_identity(binary)
        assert binary == sources.audits[label]['machine']['binary']
        for record in read(folder / 'model-sources.json'):
            verify_identity(record)
        inputs += [identity(folder / n) for n in ('binary.json', 'model-sources.json')]
        inputs.append(identity(AUDITS[label]))

    ftq_location, ftq = sources.group('local', 80580)
    full_location, full_ftq = sources.group('full', 93956)
    bank = arrays(ftq)
    assert len(bank) == 64 and all(not a['local'] and a['all_lanes_single_state'] for a in bank)
    assert all(a['bits'] == 8 and a['count'] == 64 for a in bank)
    assert len(set(s for a in bank for s in a['state_fields'])) == 4096
    assert {a['name']: a['state_fields'] for a in bank} == {a['name']: a['state_fields'] for a in arrays(full_ftq)}
    off_mapping_path = out / 'sample-off-op-map.json'
    mapped = read(off_mapping_path)['80580']
    assert len(mapped) == 4160
    before_groups = sorted({row['group'] for row in mapped})
    before_arrays, before_sites, before_locations = {}, 0, []
    for group in before_groups:
        loc, code = sources.group('off', group)
        before_locations.append(loc)
        for array in arrays(code):
            if array['name'] in {a['name'] for a in bank}:
                before_arrays[array['name']] = array['state_fields']
                first = code.index(array['name'] + ' = std::array')
                end = code.find('// op ', first)
                before_sites += literal_notifications(code[first:end if end >= 0 else None])['sites']
    assert len(before_groups) == 64
    assert before_arrays == {a['name']: a['state_fields'] for a in bank}
    layout = read(out / 'state-layout.json')
    strides = {}
    for label, offsets in layout.items():
        fields = [offsets[str(11351 + 109 * i)] for i in range(64)]
        strides[label] = dict(offsets=fields, stride=sorted({b - a for a, b in zip(fields, fields[1:])}))
    assert strides['off']['stride'] == [1] and strides['full']['stride'] == strides['local']['stride'] == [64]
    asm = (out / 'local-ftq-bank-block.s').read_text().splitlines()
    first_notify = next(i for i, line in enumerate(asm) if 'orb    $0x10,0x2455(' in line)
    assert sum('vpinsrb' in line for line in asm[:first_notify]) == 63
    assert sum('vpinsrb' in line for line in asm) == 4032
    machine_notifications = [line for line in asm if re.search(r'\bor[bwlq]?\s+\$0x[0-9a-f]+,0x[0-9a-f]+\(%rdi\)', line)]
    assert len(machine_notifications) == 192
    packing = {}
    for label in MODELS:
        packet = (out / (label + '-ftq-first-pack.s')).read_text().splitlines()
        packing[label] = dict(window_instructions=len(packet),
                              byte_inserts=sum('vpinsrb' in line for line in packet))
    assert packing['off']['byte_inserts'] == 0
    assert packing['full']['byte_inserts'] == packing['local']['byte_inserts'] == 63
    ftq_report = dict(local=ftq_location, full=full_location, no_shared=before_locations,
                      arrays=64, fields_per_array=64, disjoint_source_states=4096,
                      no_shared_array_notifications=before_sites,
                      local_array_notifications=literal_notifications(ftq),
                      state_layout=strides, first_array_machine_vpinsrb=63,
                      bank_machine_vpinsrb=4032, constant_memory_or_instructions=192,
                      first_array_machine_window_instructions=first_notify,
                      per_variant_packing=packing,
                      mechanism='Equal terminal sets pool 64 independent array constructions. '
                                'Any source state change activates the common guard. The reference-demand '
                                'layout loses per-array reader distinctions, reverting to graph order.')

    rob_location, rob = sources.group('local', 81357)
    local_arrays = arrays(rob)
    assert len(local_arrays) == 8 and all(a['local'] and a['bytes'] == 2048 for a in local_arrays)
    assert all(a['last'] < b['first'] for a, b in zip(local_arrays, local_arrays[1:]))
    rob_asm = (out / 'local-rob-arrays-block.s').read_text()
    reads = re.findall(r'(?m)^\s*([0-9a-f]+):\s+mov\s+(0x[0-9a-f]+)\(%rsp,%r\w+,8\),(%r\w+)', rob_asm)
    assert len(reads) == 8 and len({r[1] for r in reads}) == 8
    rob_report = dict(location=rob_location, arrays=local_arrays,
                      summed_declared_bytes=sum(a['bytes'] for a in local_arrays),
                      lexical_last_uses_do_not_overlap=True, elf_indexed_loads=reads,
                      batch9_frames={label: sources.audits[label]['machine']['functions'][
                          'GrhSIM_SimTop::eval_compute_batch_9()']['entry_stack_subtractions'] for label in MODELS},
                      limit='The functions contain other groups. Frame difference is not an isolated '
                            'array-lifetime ablation or a dynamic spill measurement.')

    mapping_path = out / 'local-to-full-groups.json.gz'
    mapping = json.load(gzip.open(mapping_path, 'rt'))['rows']
    remainder = next(row for row in mapping if row['group'] == 6671)
    rem_location, rem = sources.group('local', 6671)
    full_fragments = []
    for group in sorted(map(int, remainder['full_group_counts'])):
        loc, code = sources.group('full', group)
        full_fragments.append(dict(**loc, changes=code.count('const bool grhsim_changed_'),
                                   fields=sorted(set(FIELD.findall(code)))))
    assert len(full_fragments) == 36 and all(g['changes'] == 1 and len(g['fields']) == 1 for g in full_fragments)
    assert rem.count('const bool grhsim_changed_') == 36 and len(set(FIELD.findall(rem))) == 36
    assert set(FIELD.findall(rem)) == {g['fields'][0] for g in full_fragments}
    remainder_report = dict(local=rem_location, full_fragments=full_fragments, checks_per_local_activation=36,
                            mechanism='Thirty-six independent MSHR state views now share one activity flag. '
                                      'This proves possible activation broadening, not its workload frequency.')
    mixed = [r for r in mapping if r['group'] < 77286 and len(r['full_group_counts']) > 1
             and r['mapped_ops'] == r['emitted_ops']]
    summaries = {label: dict(cpp=a['cpp']['counts']['compute'], elf=a['machine']['totals']['compute'])
                 for label, a in sources.audits.items()}
    cv32 = cv32_contractions()
    probe_files = [p for p in out.iterdir() if p.suffix in ('.s', '.cpp') or p.name in
                   ('layout.json', 'state-layout.json', 'sample-off-op-map.json', 'local-to-full-groups.json.gz')]
    inputs += [identity(p) for p in sorted(probe_files)]
    result = dict(status='pass', mode='offline_no_simulation', models=summaries,
                  ftq=ftq_report, rob=rob_report, remainder=remainder_report,
                  completely_mapped_rejoined_remainders=len(mixed), cv32=cv32, inputs=inputs,
                  limits='The 2.88% timing regression is not quantitatively attributed. FTQ layout and '
                         'ROB lifetime costs are common to full and local; the remainder witness concerns '
                         'local versus full. Counts are static. No workload frequency was used to select rules.')
    save(out / 'report.json', result)
    print(json.dumps(dict(status=result['status'], ftq_arrays=64, before_notifications=before_sites,
                          local_notifications=ftq_report['local_array_notifications'],
                          layout_strides={k: v['stride'] for k, v in strides.items()},
                          distinct_rob_stack_buffers=len(reads), mixed_remainders=len(mixed)), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/xs/shared-local-cpp-elf-analysis-v1')
    args = parser.parse_args()
    audit(args.source.resolve())
