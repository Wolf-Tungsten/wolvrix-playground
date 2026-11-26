"""Extract bounded, source-linked evidence for named GRH R4 discrepancy samples."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from benchmark_f29_pass_trace import sha256, write_json_atomic
from capture_f35_pipeline import capture_lock
from f35_compare import WORK, open_table
from f35_gsim_reference import load_frozen_reference
from semantic_node_exchange import HEADERS, decode_cell, parsed_row


ROW_LIMIT = 32
RELATED_LIMIT = 64
GSIM_ORIGINS = ('node_id', 'source_path_json', 'scope_depth', 'source_line', 'native_kind',
                'source_kind', 'source_owner_id', 'state_pair_id', 'lowered_from_id')
GSIM_ASSIGNMENTS = ('target_source_node_id', 'source_line', 'kind', 'lowering')
GSIM_SCOPES = ('instance_path_json', 'module', 'module_line', 'instance_line', 'kind')
GSIM_DETAILS = ('node_id', 'native_kind', 'width', 'signed', 'shape_json', 'clock_node_id',
                'state_pair_node_id', 'native_status', 'used_width', 'assignment_count')
GSIM_BRIDGE_HEADER = ('before_node_id', 'after_node_id')


class Evidence:
    def __init__(self, path):
        self.path = path
        self.rows = []
        self.count = 0

    def add(self, line, row):
        self.count += 1
        if len(self.rows) < ROW_LIMIT:
            self.rows.append({'line': line, **row})

    def report(self):
        return {'path': str(self.path), 'matching_rows': self.count, 'rows': self.rows}


def decoded_row(fields, header):
    return dict(zip(header, map(decode_cell, fields), strict=True))


def tsv_evidence(path, header, matches):
    evidence = Evidence(path)
    with open_table(path, header) as table:
        for line, row in enumerate(table.rows(), 3):
            if matches(row):
                evidence.add(line, decoded_row(row, header))
    return evidence.report()


def jsonl_evidence(path, matches, *, hint=None, optional=False):
    if optional and not path.exists():
        return None
    evidence = Evidence(path)
    with path.open(encoding='utf-8') as stream:
        header = json.loads(stream.readline())
        if header.get('record') not in ('metadata', 'header'):
            raise ValueError(f'missing native JSONL header {path}')
        for line, raw in enumerate(stream, 2):
            # Native JSONL writes a canonical record prefix. The fallback
            # also recognizes external fixtures with whitespace.
            if hint and not raw.startswith('{"record":"footer"') and not hint.search(raw):
                if raw.startswith('{"record":'):
                    continue
            row = json.loads(raw)
            if row.get('record') == 'footer':
                if row.get('complete') is not True or stream.read(1):
                    raise ValueError(f'incomplete native JSONL {path}')
                return evidence.report()
            if matches(row):
                evidence.add(line, row)
    raise ValueError(f'missing native JSONL footer {path}')


def inventory(path, names, related):
    found = Evidence(path)
    exact = defaultdict(list)
    with open_table(path, HEADERS['nodes']) as table:
        for line, (identifier, raw_path, native_name) in enumerate(table.rows(), 3):
            if raw_path == r'\N':
                continue
            # Avoid decoding all paths. A path for an exact requested name
            # must contain that name's escaped final component.
            if identifier not in related and not any(hint in raw_path for hint in names.values()):
                continue
            path_parts = json.loads(decode_cell(raw_path))
            name = '.'.join(path_parts)
            if name in names:
                exact[name].append(identifier)
            if name in names or identifier in related:
                found.add(line, {'node_id': int(identifier), 'name': name, 'path': path_parts,
                                 'native_name': decode_cell(native_name)})
        if table.footer.get('nodeInventoryComplete') is not True:
            raise ValueError(f'incomplete sample inventory {path}')
    return exact, found.report()


def connection_evidence(path, identifiers):
    neighbors = set()

    def includes(row):
        _, source, target, _, _, candidates, _ = row
        matches = {source, target} & identifiers
        if not matches and candidates != '[]':
            matches = identifiers.intersection(map(str, json.loads(candidates)))
        if matches:
            neighbors.update((source, target))
            neighbors.discard(r'\N')
        return bool(matches)

    return tsv_evidence(path, HEADERS['connections'], includes), neighbors


def evolution(path, identifiers):
    evidence = Evidence(path)
    relations = Evidence(path)
    neighbors = set()
    events = {}
    encoded_ids = {identifier.encode('ascii') for identifier in identifiers}
    reference_fields = (b'"source_node_id"', b'"target_node_id"', b'"candidate_sources_json"', b'"owner_node_ids"')
    relevant = re.compile(b'|'.join(sorted(encoded_ids))) if encoded_ids else None
    node_subjects = {b'node', b'anchor'}
    reference_subjects = {b'connection', b'operand', b'boundary'}
    detail_records = {b'decision', b'edit', b'lineage', b'mutation', b'evidence', b'provenance'}
    with path.open('rb') as stream:
        columns = '\t'.join(HEADERS['evolution']).encode('ascii') + b'\n'
        if stream.readline() != columns:
            raise ValueError(f'unexpected trace header {path}')
        complete = False
        event_sequence = None
        for line, raw in enumerate(stream, 2):
            fields = raw.split(b'\t', 8)
            record = fields[0]
            if record == b'footer':
                body = fields[-1].rstrip(b'\n').decode('utf-8')
                footer = json.loads(decode_cell(body))
                complete = footer.get('complete') is True and footer.get('replayComplete') is True
                break
            if record == b'event':
                _, event_sequence, _, action, reason, *_ = fields
                event = {'line': line, 'seq': int(event_sequence), 'action': action.decode('utf-8'),
                         'reason': decode_cell(reason.decode('utf-8'))}
                continue
            if not relevant or record not in detail_records:
                continue
            _, seq, ordinal, action, reason, subject, side, identifier, body = fields
            detail = None
            matches = subject in node_subjects and identifier in encoded_ids
            if record == b'provenance' and subject == b'liveness':
                # The object ID numbers provenance rows, rather than nodes.
                if reason not in (b'start', b'residual') or not relevant.search(body):
                    continue
                detail = json.loads(decode_cell(body.rstrip(b'\n').decode('utf-8')))
                references = [detail.get('node_id'), *detail.get('owner_ids', [])]
                matches = not identifiers.isdisjoint(map(str, references))
            if record == b'lineage':
                if not matches and not relevant.search(body):
                    continue
                detail = json.loads(decode_cell(body.rstrip(b'\n').decode('utf-8')))
                child = str(detail['to_node_id'])
                matches = identifier in encoded_ids or child in identifiers
                if matches:
                    neighbors.update((identifier.decode('ascii'), child))
                    relations.add(line, {'seq': int(seq), 'from_node_id': int(identifier), **detail})
            if not matches and subject in reference_subjects:
                if not any(field in body for field in reference_fields) or not relevant.search(body):
                    continue
                detail = json.loads(decode_cell(body.rstrip(b'\n').decode('utf-8')))
                references = [detail.get(key) for key in ('source_node_id', 'target_node_id')]
                references.extend(detail.get('candidate_sources_json', []))
                references.extend(detail.get('owner_node_ids', []))
                matches = not identifiers.isdisjoint(map(str, references))
            if matches:
                if detail is None:
                    detail = json.loads(decode_cell(body.rstrip(b'\n').decode('utf-8')))
                evidence.add(line, {
                    'record': record.decode('ascii'), 'seq': int(seq), 'ordinal': int(ordinal),
                    'action': decode_cell(action.decode('utf-8')), 'reason': decode_cell(reason.decode('utf-8')),
                    'subject': subject.decode('ascii'), 'side': side.decode('ascii'),
                    'object_id': int(identifier), 'detail': detail,
                })
                if event_sequence == seq and len(events) < ROW_LIMIT:
                    events[seq] = event
        if not complete or stream.read(1):
            raise ValueError(f'incomplete native evolution {path}')
    return {**evidence.report(), 'footer': footer, 'event_headers': list(events.values()),
            'lineage': relations.report()}, neighbors


def gsim_native_mutations(path, identifiers, neighbors):
    def includes(row):
        owner = str(row.get('node_id'))
        endpoints = {str(row.get(key)) for key in
                     ('before_node_id', 'after_node_id', 'member_node_id', 'representative_node_id')}
        return owner in identifiers or (owner in neighbors and not endpoints.isdisjoint(identifiers))

    hint = re.compile(r'"(?:node_id|before_node_id|after_node_id|member_node_id|representative_node_id)"\s*:\s*(?:'
                      + '|'.join(sorted(identifiers)) + r')\b') if identifiers else None
    return jsonl_evidence(path, includes, hint=hint, optional=True)


def alias_trace(path, identifiers):
    def includes(row):
        refs = [row[key] for key in ('node', 'ref', 'from', 'to', 'target', 'targetAfter', 'subject') if key in row]
        refs = [ref for ref in refs if not isinstance(ref, dict) or ref.get('kind', 'gsim-node') == 'gsim-node']
        refs.extend(row.get('representatives', []))
        return any(str(ref.get('id') if isinstance(ref, dict) else ref) in identifiers for ref in refs)

    hint = re.compile(r'"(?:id|from|to|target|targetAfter|subject)"\s*:\s*(?:'
                      + '|'.join(sorted(identifiers)) + r')\b') if identifiers else None
    return jsonl_evidence(path, includes, hint=hint, optional=True)


def bundle_evidence(directory, stage, names, carried_ids):
    print(f'F35 sample trace {stage}: scanning Node inventories', flush=True)
    before, before_rows = inventory(directory / 'before.nodes.tsv', names, carried_ids)
    after, after_rows = inventory(directory / 'after.nodes.tsv', names, carried_ids)
    tracked = carried_ids | {identifier for inventory in (before, after)
                             for ids in inventory.values() for identifier in ids}
    print(f'F35 sample trace {stage}: scanning evolution for {len(tracked)} Node IDs', flush=True)
    journal, related = evolution(directory / 'evolution.tsv', tracked)
    print(f'F35 sample trace {stage}: scanning connection tables', flush=True)
    edge_rows, adjacent = {}, set()
    for side in ('before', 'after'):
        edges, neighbors = connection_evidence(directory / f'{side}.connections.tsv', tracked)
        edge_rows[side] = edges
        adjacent.update(neighbors)
    result = {
        'pass': stage, 'directory': str(directory), 'before_exact_names': before, 'after_exact_names': after,
        'before_nodes': before_rows, 'after_nodes': after_rows, 'evolution': journal, 'connections': edge_rows,
        'related_id_count': len(related),
    }
    if related - tracked:
        for side in ('before', 'after'):
            _, result[f'{side}_lineage_nodes'] = inventory(directory / f'{side}.nodes.tsv', {}, related - tracked)
    mutations_path = directory / 'native-mutations.jsonl'
    mutations = gsim_native_mutations(mutations_path, tracked | related, adjacent) if tracked else None
    if mutations:
        result['native_mutations'] = mutations
    if tracked and stage in ('alias-analysis', 'alias-analysis#0'):
        migrations = alias_trace(directory.parent / 'alias-analysis-migrations.jsonl', tracked | related)
        if migrations:
            result['alias_migrations'] = migrations
    for side in ('before', 'after'):
        details = directory / f'{side}.node-details.tsv'
        if details.is_file():
            result[f'{side}_native_details'] = tsv_evidence(
                details, GSIM_DETAILS, lambda row: row[0] in tracked or row[0] in related)
    result['follow_forward'] = sorted(
        {str(row['to_node_id']) for row in journal['lineage']['rows']
         if str(row['from_node_id']) in tracked and str(row['to_node_id']) not in tracked}, key=int)
    return result, tracked | related


def finish_representatives(stages, bridges=None):
    # The primary scan runs backwards. Revisit only later Node inventories
    # when a substitution identifies a previously unknown representative.
    carried = set()
    for stage in stages:
        if bridge := (bridges or {}).get(stage['pass']):
            forward, _ = bridge
            carried = {forward.get(identifier, identifier) for identifier in carried}
        if carried:
            path = Path(stage['directory'])
            for side in ('before', 'after'):
                _, rows = inventory(path / f'{side}.nodes.tsv', {}, carried)
                stage[f'{side}_earlier_representatives'] = rows
        carried.update(stage['follow_forward'][:max(0, RELATED_LIMIT - len(carried))])


def grh_origins(root, bundles, ids):
    origins = {}
    for module, local_ids in ids.items():
        path = root / 'ingest-origins' / f'{module}.jsonl'
        if path.is_file():
            origins[module] = jsonl_evidence(path, lambda row: str(row.get('node_id')) in local_ids)
    for bundle in bundles:
        directory = Path(bundle)
        if directory.name in ids:
            _, rows = inventory(directory / 'before.nodes.tsv', {}, ids[directory.name])
            origins.setdefault(directory.name, {})['initial_nodes'] = rows
    return origins


def grh_relocations(path, identifiers, expected):
    evidence = Evidence(path)
    if not path.exists() and expected == 0:
        return evidence.report()
    count = 0
    columns = HEADERS['relocations']
    with path.open(encoding='utf-8') as stream:
        if not next(stream).startswith('#meta\t') or next(stream).rstrip('\n').split('\t') != list(columns):
            raise ValueError('invalid hierarchy relocations: ' + str(path))
        for line, raw in enumerate(stream, 3):
            count += 1
            row = parsed_row(raw, columns)
            if row['target_node_id'] in identifiers:
                evidence.add(line, row)
    if count != expected:
        raise ValueError('hierarchy relocation count disagrees with evolution footer')
    return evidence.report()


def trace_grh(root, summary, names, r4_ids):
    passes = summary['passes']
    found = []
    carried = {str(identifier) for identifier in r4_ids}
    for stage in reversed(passes):
        bundle = Path(stage['bundles'][0])
        if stage['pass'] == 'xmr-resolve#0':
            break
        if len(stage['bundles']) != 1:
            raise ValueError(f'expected one flattened GRH bundle at {stage["pass"]}')
        print(f'F35 sample trace GRH {stage["pass"]}', flush=True)
        result, related = bundle_evidence(bundle, stage['pass'], names, carried)
        carried.update(sorted(related - carried, key=int)[:max(0, RELATED_LIMIT - len(carried))])
        found.append(result)
    if not found or found[-1]['pass'] != 'hier-flatten#0' or passes[0]['pass'] != 'xmr-resolve#0':
        raise ValueError('missing GRH hierarchy and ingest boundaries')
    flat = found[-1]
    flat_path = Path(flat['directory'])
    relocations = grh_relocations(flat_path / 'relocations.tsv', carried,
                                  flat['evolution']['footer'].get('relocationRecordCount', 0))
    flat['relocations'] = relocations
    initial_ids = defaultdict(set)
    initial_ids[flat_path.name].update(str(row['node_id']) for row in flat['before_nodes']['rows'])
    for row in relocations['rows']:
        initial_ids[row['source_module']].add(row['source_node_id'])
    for bundle in passes[0]['bundles']:
        bundle_path = Path(bundle)
        if local := initial_ids.get(bundle_path.name):
            result, related = bundle_evidence(bundle_path, 'xmr-resolve#0', {}, local)
            found.append(result)
            local.update(sorted(related - local, key=int)[:max(0, RELATED_LIMIT - len(local))])
    origins = grh_origins(root, passes[0]['bundles'], initial_ids)
    found.reverse()
    finish_representatives([entry for entry in found if entry['pass'] != 'xmr-resolve#0'])
    return {'passes': found, 'ingest': origins}


def gsim_bridges(root, summary, frozen):
    result = {}
    for bundle, record in summary['binary'].get('recovery_bridge', {}).items():
        if relative := record.get('node_id_remap'):
            path = root / relative
            if sha256(path) != frozen['files'][relative]['sha256']:
                raise ValueError(f'frozen GSIM Node bridge changed at {bundle}')
            forward, backward = {}, {}
            with path.open(encoding='utf-8') as stream:
                if stream.readline().rstrip('\n').split('\t') != list(GSIM_BRIDGE_HEADER):
                    raise ValueError(f'invalid GSIM Node bridge header: {path}')
                for row in stream:
                    left, right = row.rstrip('\n').split('\t')
                    if left in forward or right in backward:
                        raise ValueError(f'non-bijective GSIM Node bridge: {path}')
                    forward[left] = right
                    backward[right] = left
            result[bundle] = forward, backward
    return result


def trace_gsim(root, summary, names, frozen):
    found = []
    carried = set()
    bridges = gsim_bridges(root, summary, frozen)
    # Exact names recover the pre-retirement identity while walking backwards.
    for stage in reversed(summary['passes']):
        print(f'F35 sample trace GSIM {stage["pass"]}', flush=True)
        result, related = bundle_evidence(Path(stage['bundles'][0]), stage['pass'], names, carried)
        carried.update(sorted(related - carried, key=int)[:max(0, RELATED_LIMIT - len(carried))])
        if bridge := bridges.get(stage['pass']):
            _, backward = bridge
            result['bridged_before_node_ids'] = {
                identifier: backward[identifier] for identifier in sorted(carried, key=int)
                if identifier in backward and backward[identifier] != identifier
            }
            carried = {backward.get(identifier, identifier) for identifier in carried}
        found.append(result)
    found.reverse()
    finish_representatives(found, bridges)
    origins = tsv_evidence(root / 'init-node-origins.tsv', GSIM_ORIGINS, lambda row: row[0] in carried)
    target_ids = {row['node_id'] for row in origins['rows']}
    target_ids.update(row['lowered_from_id'] for row in origins['rows'] if row['lowered_from_id'] is not None)
    source_scopes = {tuple(json.loads(row['source_path_json'])[:int(row['scope_depth'])]) for row in origins['rows']}
    assignments = tsv_evidence(root / 'init-source-assignments.tsv', GSIM_ASSIGNMENTS,
                               lambda row: row[0] in target_ids)
    scopes = tsv_evidence(root / 'init-source-scopes.tsv', GSIM_SCOPES,
                          lambda row: tuple(json.loads(decode_cell(row[0]))) in source_scopes)
    return {'passes': found, 'init': {'origins': origins, 'assignments': assignments, 'scopes': scopes}}


def read_summary(directory, engine):
    report = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    if (report.get('schema') != 'wolvrix.f35.capture.v1' or report.get('engine') != engine
            or report.get('complete') is not True):
        raise ValueError(f'incomplete {engine} capture in {directory}')
    return report


def validate_comparison(report, grh, frozen):
    gsim_nodes = frozen['files']['dce-3/after.nodes.tsv']
    if (report['grh_nodes']['sha256'] != grh['final_inventory']['sha256']
            or report['gsim_nodes']['sha256'] != gsim_nodes['sha256']):
        raise ValueError('comparison does not match the captured fourth-DCE inventories')


def recheck_pass(summary, instance, names, r4_ids):
    stage, = [stage for stage in summary['passes'] if stage['pass'] == instance]
    bundle, = stage['bundles']
    evidence, _ = bundle_evidence(Path(bundle), instance, names, {str(node) for node in r4_ids})
    return {'passes': [evidence]}


def sample_name_hints(names):
    hints = {name: json.dumps(name.rsplit('.', 1)[-1], ensure_ascii=False)[1:-1] for name in names}
    if any('\\' in hint for hint in hints.values()):
        # Handle TSV escaping and differing JSON escapes on unusual symbols.
        return dict.fromkeys(names, '')
    return hints


def explicit_samples(report, requested, *, recheck=False):
    names = sample_name_hints(requested)
    grh, _ = inventory(Path(report['grh_nodes']['path']), names, set())
    gsim, _ = inventory(Path(report['gsim_nodes']['path']), names, set())
    candidates = {row['node_id']: row for kind in report['classes'] for row in kind['samples']}
    samples = []
    for name in names:
        grh_ids = list(map(int, grh.get(name, [])))
        gsim_ids = list(map(int, gsim.get(name, [])))
        if not recheck and not grh_ids:
            raise ValueError(f'{name!r} is absent from the GRH fourth-DCE inventory')
        if not recheck and gsim_ids:
            raise ValueError(f'{name!r} has a same-name GSIM fourth-DCE match')
        for identifier in grh_ids or [None]:
            sample = candidates.get(identifier, {'node_id': identifier, 'name': name})
            if recheck:
                sample = {**sample, 'grh_r4_ids': grh_ids, 'gsim_r4_ids': gsim_ids}
            samples.append(sample)
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh', 'gsim', 'comparison', 'output'):
        parser.add_argument('--' + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument('--category')
    parser.add_argument('--name', action='append')
    parser.add_argument('--recheck', action='store_true',
                        help='trace explicitly named samples even if matched or removed after a repair')
    parser.add_argument('--grh-pass', choices=('alias-analysis#0', 'common-expr#0', 'dead-code-elim#3'),
                        help='recheck one changed GRH pass and both fourth-DCE inventories')
    args = parser.parse_args()
    if args.output == WORK or not args.output.is_relative_to(WORK):
        parser.error('sample evidence must be under ptmp/firrtl-ingest/F35/')
    if args.name and args.category:
        parser.error('choose a category or explicit names')
    if args.recheck and not args.name:
        parser.error('--recheck requires --name')
    if args.grh_pass and not args.recheck:
        parser.error('--grh-pass requires --recheck')
    with capture_lock('grh', read_only=True):
        trace_samples(args)


def trace_samples(args):
    report = json.loads(args.comparison.read_text(encoding='utf-8'))
    if args.name:
        samples = explicit_samples(report, args.name, recheck=args.recheck)
    else:
        classes = report['classes']
        category = (next((row for row in classes if row['category'] == args.category), None)
                    if args.category else next(iter(classes), None))
        if category is None:
            parser.error('the selected category has no representative samples')
        samples = category['samples'][:3]
    names = [row['name'] for row in samples]
    if not names or any(not name for name in names):
        parser.error('sample extraction requires at least one named discrepancy')
    # Decode exact names after a cheap final-component filter. A native path
    # may flatten a full path into one token, hence the hint omits JSON quotes.
    names = sample_name_hints(names)
    grh = read_summary(args.grh, 'grh')
    gsim = read_summary(args.gsim, 'gsim')
    if grh['inputs'] != gsim['inputs'] or grh['reference']['run_id'] != gsim['run_id']:
        raise ValueError('GRH and GSIM captures do not share a frozen input and reference')
    frozen = load_frozen_reference(args.gsim)
    validate_comparison(report, grh, frozen)
    r4_ids = [row['node_id'] for row in samples if row['node_id'] is not None]
    evidence = {
        'samples': samples, 'names': list(names), 'input': grh['inputs'],
        'comparison': str(args.comparison), 'row_limit_per_artifact': ROW_LIMIT,
    }
    if args.grh_pass:
        evidence['grh'] = recheck_pass(grh, args.grh_pass, names, r4_ids)
    else:
        evidence.update(grh=trace_grh(args.grh, grh, names, r4_ids),
                        gsim=trace_gsim(args.gsim, gsim, names, frozen))
        evidence['firrtl'] = sample_sources(evidence['gsim']['init'], grh['inputs'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output, evidence)
    print(f'Wrote sample evidence for {len(names)} names to {args.output}')


def sample_sources(gsim_sources, inputs):
    lines = {int(row['source_line']) for table in ('origins', 'assignments')
             for row in gsim_sources[table]['rows'] if row['source_line'] is not None}
    lines.update(int(row['module_line']) for row in gsim_sources['scopes']['rows'])
    firrtl = next(source['path'] for source in inputs['sources'] if source['language'] == 'firrtl')
    snippets = []
    if lines:
        final_line = max(lines)
        with Path(firrtl).open(encoding='utf-8') as source:
            for number, text in enumerate(source, 1):
                if number in lines:
                    snippets.append({'line': number, 'text': text.rstrip('\n')})
                if number >= final_line:
                    break
    return {'path': firrtl, 'lines': snippets}


if __name__ == '__main__':
    main()
