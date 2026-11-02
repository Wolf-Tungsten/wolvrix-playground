"""RTL provenance and structural paths for an exact GrhSIM execution plan.

Measurements always belong to batches. Source associations are sets and must
never be summed as independent per-line timings.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import csv
import hashlib
import json
from pathlib import Path
import re

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def identity(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def part_number(text):
    text = str(text)
    if text.isdecimal():
        return int(text)
    match = re.fullmatch(r'(?:G)?(?:inst_)?part_(\d+)(?:_model)?', text)
    if not match:
        raise ValueError(f'unsupported partition identifier {text!r}')
    return int(match[1])


@lru_cache(maxsize=32768)
def normalized_source(file, rtl_root=None, source_root=ROOT):
    path = Path(file)
    absolute = path if path.is_absolute() else Path(source_root) / path
    absolute = absolute.resolve()
    roots = [('rtl', Path(rtl_root).resolve())] if rtl_root else []
    roots.append(('repo', Path(source_root).resolve()))
    for prefix, root in roots:
        if absolute.is_relative_to(root):
            return f'{prefix}/{absolute.relative_to(root).as_posix()}', absolute
    return absolute.as_posix(), absolute


def source_span(row, rtl_root=None, source_root=ROOT):
    if not row.get('file') or int(row.get('line') or 0) <= 0:
        return None
    file, path = normalized_source(row['file'], rtl_root, source_root)
    line, column = int(row['line']), int(row.get('column') or 0)
    end_line, end_column = int(row.get('end_line') or 0), int(row.get('end_column') or 0)
    if column < 0 or end_line < 0 or end_column < 0:
        raise ValueError('negative source position')
    if end_line and (end_line, end_column) < (line, column):
        raise ValueError('reversed source range')
    precision = 'range' if end_line and end_column else 'point'
    key = [file, line, column, end_line, end_column]
    sid = hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest()[:24]
    return dict(source_span_id=sid, file=file, resolved_file=str(path), line=line, column=column,
                end_line=end_line or None, end_column=end_column or None, precision=precision)


def rows(path):
    with Path(path).open(newline='') as stream:
        yield from csv.DictReader(stream)


def batch_key(part, phase, batch):
    return f'{part_number(part)}:{phase}:{int(batch)}'



def verify_package(directory, package, jobs=8):
    """Join plans by supernode membership, not by coincidental batch number."""
    expected = {}
    for path in Path(directory).glob('*.batches.csv'):
        for row in rows(path):
            key = batch_key(row['part'], row['phase'], row['batch'])
            if key in expected:
                raise ValueError(f'duplicate batch {key}')
            expected[key] = {int(x) for x in row['groups'].split(';') if x}
    if not expected:
        raise ValueError('no execution-plan batches')

    def inspect(path):
        text = path.read_text()
        names = list(re.finditer(r'void GrhSIM_Gpart_(\d+)_model::eval_(compute|commit)_batch_(\d+)\(', text))
        result = {}
        for index, match in enumerate(names):
            body = text[match.end():names[index+1].start() if index+1 < len(names) else len(text)]
            result[batch_key(*match.groups())] = {int(g) for g in re.findall(r'// Supernode (\d+):', body)}
        return result

    actual = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for entry in pool.map(inspect, sorted(Path(package).glob('grhsim_Gpart_*_model_sched_*.cpp'))):
            if actual.keys() & entry.keys():
                raise ValueError('duplicate emitted batch')
            actual.update(entry)
    mismatches = [key for key in sorted(expected.keys() | actual.keys()) if expected.get(key) != actual.get(key)]
    if mismatches:
        raise ValueError(f'package and plan differ in {len(mismatches)} batches: {mismatches[:8]}')
    return dict(status='pass', batches=len(expected), comparison='exact batch phase and supernode membership')


def build_source_map(directory, output, rtl_root=None, source_root=ROOT):
    directory, output = Path(directory), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    spans, batches, path_records, parts, files = {}, {}, [], {}, {}
    total = Counter()
    mapping = output / 'operation_map.jsonl'
    source_inputs = sorted(directory.glob('*.sources.csv'))
    if not source_inputs:
        raise ValueError('native source export is missing')
    with mapping.open('w') as operation_file:
        for source_file in source_inputs:
            part = part_number(source_file.name.split('.')[0])
            stats = Counter()
            seen, path_nodes = set(), {}
            native_paths = list(rows(directory / (source_file.name.split('.')[0] + '.paths.csv')))
            requested = {int(row['op_index']) for row in native_paths}
            for row in rows(source_file):
                if part_number(row['part']) != part:
                    raise ValueError('partition/source file mismatch')
                op_index = int(row['op_index'])
                if op_index in seen:
                    raise ValueError(f'duplicate operation {part}:{op_index}')
                seen.add(op_index)
                span = source_span(row, rtl_root, source_root)
                sid = span['source_span_id'] if span else None
                work = int(row['work'])
                stats['operations'] += 1
                stats['structural_work'] += work
                if span:
                    spans.setdefault(sid, dict(**span, operations=0, structural_work=0, parts=set(),
                                               transformations=set(), association_kinds=set()))
                    item = spans[sid]
                    item['operations'] += 1
                    item['structural_work'] += work
                    item['parts'].add(part)
                    item['association_kinds'].add(row.get('location_kind', 'operation'))
                    if row.get('pass'):
                        item['transformations'].add((row.get('origin', ''), row['pass'], row.get('note', '')))
                    files[span['file']] = span['resolved_file']
                    stats['mapped_operations'] += 1
                    stats['mapped_work'] += work
                    stats[span['precision'] + '_operations'] += 1
                else:
                    stats['unmapped_operations'] += 1
                phase = row['phase']
                key = batch_key(part, phase, row['batch']) if row.get('batch') else None
                if key:
                    batch = batches.setdefault(key, dict(part=part, batch=int(row['batch']), phase=phase,
                        operations=0, structural_work=0, unknown_work=0, rise_work=0, fall_work=0,
                        source_spans=Counter(), groups=set(), active_ids=set(), unmapped_operations=0,
                        kinds=Counter(), fanout_max=0, memory_operations=0))
                    batch['operations'] += 1
                    batch['structural_work'] += work
                    batch['groups'].add(int(row['group']))
                    batch['active_ids'].add(int(row['active_id']))
                    mask = int(row['activity_mask'])
                    for bit, name in ((1, 'rise_work'), (2, 'fall_work'), (1 << 63, 'unknown_work')):
                        if mask & bit:
                            batch[name] += work
                    batch['kinds'][row['op_kind']] += 1
                    batch['fanout_max'] = max(batch['fanout_max'], int(row.get('fanout') or 0))
                    batch['memory_operations'] += 'Memory' in row['op_kind']
                    if sid:
                        batch['source_spans'][sid] += 1
                    else:
                        batch['unmapped_operations'] += 1
                entry = dict(part=part, op_index=op_index, op_symbol=row['op_symbol'], op_kind=row['op_kind'],
                    value_ids=[int(x) for x in row.get('value_ids', '').split(';') if x],
                    value_symbols=row.get('value_symbols', '').split(';') if row.get('value_symbols') else [],
                    source_span_id=sid, batch=key, group=int(row['group']), active_id=int(row['active_id']),
                    phase=phase, activity_mask=int(row['activity_mask']), group_mask=int(row['group_mask']),
                    work=work, boundary=bool(int(row.get('boundary') or 0)), storage=row.get('storage', ''),
                    provenance=dict(origin=row.get('origin',''), pass_name=row.get('pass',''), note=row.get('note','')),
                    asc_ids=None, asc_status='requires_original_graph_membership')
                operation_file.write(json.dumps(entry, separators=(',', ':')) + '\n')
                if op_index in requested:
                    path_nodes[op_index] = {k: entry[k] for k in ('op_index', 'op_symbol', 'op_kind', 'source_span_id', 'batch', 'boundary', 'storage')}
            grouped = defaultdict(list)
            for row in native_paths:
                grouped[int(row['clock']), int(row['rank'])].append(row)
            for (clock, rank), entries in sorted(grouped.items()):
                entries.sort(key=lambda row: int(row['position']))
                # Unscheduled helper nodes remain explicit; never assign a nearby span.
                nodes = [path_nodes.get(int(row['op_index']), dict(op_index=int(row['op_index']),
                    source_span_id=None, reason='not_in_scheduled_operation_map')) for row in entries]
                path_records.append(dict(part=part, clock=clock, rank=rank, structural_work=int(entries[0]['work']),
                    unknown_operations=int(entries[0]['unknown_operations']), nodes=nodes))
            parts[str(part)] = dict(stats)
            total.update(stats)
    for span in spans.values():
        span['parts'] = sorted(span['parts'])
        span['association_kinds'] = sorted(span['association_kinds'])
        span['transformations'] = [dict(origin=o, pass_name=p, note=n) for o,p,n in sorted(span['transformations'])]
    for batch in batches.values():
        for name in ('groups','active_ids'):
            batch[name] = sorted(batch[name])
        batch['source_spans'] = dict(sorted(batch['source_spans'].items()))
        batch['kinds'] = dict(batch['kinds'])
    source_records = {}
    for file, resolved in files.items():
        p = Path(resolved)
        source_records[file] = identity(p) if p.is_file() else dict(path=resolved, missing=True)
    summary = dict(total)
    summary['operation_coverage'] = total['mapped_operations'] / total['operations'] if total['operations'] else 0
    summary['work_coverage'] = total['mapped_work'] / total['structural_work'] if total['structural_work'] else 0
    summary['source_files_missing'] = sum(row.get('missing', False) for row in source_records.values())
    summary['source_spans'] = len(spans)
    summary['batch_count'] = len(batches)
    summary['multiple_source_batches'] = sum(len(b['source_spans'])>1 for b in batches.values())
    summary['complete_transform_chains_available'] = False
    result = dict(schema_version=SCHEMA_VERSION, status='pass', diagnostic_only=True, spans=spans,
                  batches=batches, summary=summary, parts=parts, static_paths=path_records,
                  source_files=source_records, operation_map=str(mapping.resolve()),
                  static_units='grhsim-v1 structural work; not instructions, delay or elapsed time',
                  attribution='source associations are non-additive; no per-line timing allocation',
                  provenance_limit='stored source locations and recorded transformations; unknown origins stay unknown')
    save(output/'source_map.json', result)
    save(output/'mapping_summary.json', dict(schema_version=SCHEMA_VERSION, **summary, parts=parts))
    with (output/'batch_map.csv').open('w',newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['part','batch','phase','groups','active_ids','operations','structural_work','source_span_ids','unmapped_operations'])
        for batch in sorted(batches.values(), key=lambda b:(b['part'],b['batch'])):
            writer.writerow([batch['part'],batch['batch'],batch['phase'],json.dumps(batch['groups']),
                json.dumps(batch['active_ids']),batch['operations'],batch['structural_work'],
                json.dumps(list(batch['source_spans'])),batch['unmapped_operations']])
    return result


def add_asc_map(mapping, native, output, selected_parts):
    """Exact original-graph join; transformed/unqueried operations stay unknown.

    The large per-operation membership is a sidecar. Batch unions identify
    possible owning cones, and are never used to split measured batch time.
    """
    matches = {}
    for row in rows(native):
        key = (int(row['part']),row['op_symbol'],row['op_kind'],row['value_symbols'])
        if key in matches: raise ValueError('ambiguous original ASC membership')
        matches[key] = (int(row['raw_op_index']),[int(x) for x in row['asc_ids'].split(';') if x])
    selected_parts=set(selected_parts)
    totals=Counter(); batch_as = defaultdict(set); batch_counts=Counter()
    sidecar=Path(output)/'operation_asc_map.jsonl'
    with Path(mapping['operation_map']).open() as source, sidecar.open('w') as target:
        for line in source:
            row=json.loads(line)
            if row['part'] not in selected_parts: continue
            totals['queried_operations']+=1
            key=(row['part'],row['op_symbol'],row['op_kind'],';'.join(row['value_symbols']))
            if key not in matches:
                totals['unmapped_operations']+=1
                continue
            raw_op,ascs=matches[key]
            if not ascs: continue
            totals['mapped_operations']+=1
            target.write(json.dumps(dict(part=row['part'],op_index=row['op_index'],raw_op_index=raw_op,
                batch=row['batch'],asc_ids=ascs,method='exact symbol, kind, result symbols and assigned partition'))+'\n')
            if row['batch']:
                batch_as[row['batch']].update(ascs);batch_counts[row['batch']]+=1
    for key,batch in mapping['batches'].items():
        batch['asc_ids']=sorted(batch_as[key]) if batch['part'] in selected_parts else None
        batch['asc_mapped_operations']=batch_counts[key]
        batch['asc_queried']=batch['part'] in selected_parts
    record=dict(schema_version=1,parts=sorted(selected_parts),**totals,sidecar=str(sidecar.resolve()),
        raw_membership=identity(native),method='exact symbol/kind/result match in the original ASC builder, filtered by assignment',
        limitation='only automatically selected diagnostic partitions are queried; no ASC identity is guessed for rewritten operations')
    mapping['asc_provenance']=record
    mapping['summary']['asc_queried_operations']=totals['queried_operations']
    mapping['summary']['asc_mapped_operations']=totals['mapped_operations']
    save(Path(output)/'asc_summary.json',record)
    return record


def add_communication(mapping, native, package):
    """Exact emitted copy sites + exact planner input-bit activation targets."""
    inputs={}
    for path in Path(native).glob('*.ports.csv'):
        for row in rows(path):
            if row['direction']!='input':continue
            match=re.fullmatch(r'repcut_port_(\d+)',row['name'])
            if not match:raise ValueError('unexpected canonical input port')
            inputs[part_number(row['part']),int(match[1])]=row
    targets=defaultdict(set)
    masks=defaultdict(list)
    for row in rows(Path(native)/'input_masks.csv'):
        key=part_number(row['part']),int(row['value'])
        targets[key].add(int(row['target']))
        masks[key].append(dict(target=int(row['target']),word=int(row['word']),mask=int(row['mask'])))
    edges=[]
    pattern=re.compile(r'(copy_\w+_)\(unit_part_(\d+)_\->in_(\d+), unit_part_(\d+)_\->out_(\d+)(?:, (\d+))?\)')
    for path in sorted(Path(package).glob('wolvi_repcut_grhsim_sim_*.cpp')):
        for line in path.read_text().splitlines():
            if 'copy_' not in line or 'unit_part_' not in line:continue
            match=pattern.search(line)
            if not match:raise ValueError('unsupported inter-partition copy site: '+line[:140])
            helper,receiver,port,sender,source,words=match.groups()
            receiver,port,sender=int(receiver),int(port),int(sender)
            input_port=inputs.get((receiver,port))
            key=(receiver,int(input_port['value'])) if input_port else None
            edge=dict(id=len(edges),sender=sender,receiver=receiver,input_port=port,output_port=int(source),
                helper=helper,words=int(words) if words else None,width=int(input_port['width']) if input_port else None,
                input_value=int(input_port['value']) if input_port else None,
                active_ids=sorted(targets[key]) if key in targets else None,
                input_bit_masks=masks[key] if key in masks else [],
                provenance='emitted wrapper copy site',activation='bit targets' if key in targets else 'not exported as bit targets')
            edges.append(edge)
    for batch in mapping['batches'].values():
        batch['cross_partition_inputs']=[e['id'] for e in edges if e['receiver']==batch['part'] and
            e['active_ids'] is not None and set(e['active_ids']).intersection(batch['active_ids'])]
    mapping['communication']=edges
    mapping['summary']['cross_partition_copy_sites']=len(edges)
    mapping['summary']['copy_sites_without_bit_targets']=sum(e['active_ids'] is None for e in edges)
    return edges
