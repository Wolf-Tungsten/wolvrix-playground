"""Compare current native split families using a bound, read-only before index.

Only original public paths come from the old index. Current after inventories
provide IDs, never names or inferred lineage. This is inventory accounting, not
an independent journal replay or cross-engine functional equivalence proof.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from analyze_f30_alignment import boundary_evidence
from compare_f29_node_names import input_digest
from export_f30_connection_differences import closed_database_identity, file_identity, phase_progress, save_json
from f30_split_gap_accounting import classify_family, family_gap
from semantic_node_exchange import HEADERS, IDENTITY, decode_cell, encode_cell, integer

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.split-enhancement.v1'
ENGINES = ('grh', 'gsim')
FILES = ('before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
         'after.nodes.tsv', 'after.connections.tsv')
COLUMNS = ('category', 'parent_path', 'grh_parent', 'gsim_parent', 'grh_children', 'gsim_children',
           'grh_parent_alive', 'gsim_parent_alive', 'net_gap_contribution', 'grh_retain_reasons',
           'grh_decisions_json')
COORDINATE_COLUMNS = ('category', 'parent_path', 'grh_parent', 'gsim_parent', 'side',
                      'coordinates_json', 'grh_child', 'gsim_child')


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class SparseIds:
    """Paged bitset: dense native IDs cost one bit; large holes cost no pages."""
    def __init__(self):
        self.pages = {}
        self.count = 0

    def add(self, identifier):
        page = self.pages.get(identifier >> 12)
        if page is None:
            page = self.pages[identifier >> 12] = bytearray(512)
        byte, bit = (identifier & 4095) >> 3, 1 << (identifier & 7)
        if page[byte] & bit:
            return False
        page[byte] |= bit
        self.count += 1
        return True

    def __contains__(self, identifier):
        page = self.pages.get(identifier >> 12)
        return page is not None and bool(page[(identifier & 4095) >> 3] & (1 << (identifier & 7)))

    def __len__(self):
        return self.count


class Sources:
    def __init__(self):
        self.files = {}

    def watch(self, path, expected=None):
        path = Path(path).resolve()
        identity = file_identity(path)
        if expected is not None and identity != expected:
            raise ValueError('bound source identity changed: ' + str(path))
        prior = self.files.get(str(path))
        if prior is not None and prior['identity'] != identity:
            raise ValueError('source changed during analysis: ' + str(path))
        self.files.setdefault(str(path), {'identity': identity})
        return path

    def digest(self, path, digest):
        source = self.files[str(Path(path).resolve())]
        if source.get('sha256', digest) != digest:
            raise ValueError('source content changed during analysis: ' + str(path))
        source['sha256'] = digest

    def json(self, path, expected=None):
        path = self.watch(path, None if expected is None else expected['identity'])
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if expected is not None and expected['sha256'] != digest:
            raise ValueError('bound report SHA256 changed: ' + str(path))
        self.digest(path, digest)
        return json.loads(content)

    def check(self):
        for path, evidence in self.files.items():
            if file_identity(Path(path)) != evidence['identity'] or 'sha256' not in evidence:
                raise ValueError('source changed or lacks a digest: ' + path)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def checked_id(value):
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError('native Node ID must be a positive integer')
    return value


def scan_nodes(path, expected, before_ids=None, store=True):
    """Hash exact data rows and retain only IDs; snapshot names are not decoded."""
    full, body = hashlib.sha256(), hashlib.sha256()
    identifiers = SparseIds() if store else None
    count, previous, survivors, footer = 0, 0, 0, None
    with path.open('rb') as stream:
        first = stream.readline()
        full.update(first)
        if not first.startswith(b'#meta\t') or not first.endswith(b'\n'):
            raise ValueError('missing native Node metadata: ' + str(path))
        metadata = json.loads(first[6:])
        header = expected['header']
        digest = input_digest(metadata, path, required=False)
        if (any(metadata.get(key) != header.get(key) for key in IDENTITY) or
                metadata.get('table') != 'nodes' or not metadata.get('stage') or
                metadata.get('snapshot_id') != expected['snapshot_id'] or
                metadata.get('root_name', expected['root_name']) != expected['root_name'] or
                (digest is not None and digest != expected['input_sha256']) or
                ('metadata' in expected and metadata != expected['metadata'])):
            raise ValueError('Node inventory is not bound to its native identity: ' + str(path))
        columns = stream.readline()
        full.update(columns)
        if columns != ('\t'.join(HEADERS['nodes']) + '\n').encode():
            raise ValueError('invalid Node inventory columns')
        for line in stream:
            full.update(line)
            if footer is not None or not line.endswith(b'\n') or line.endswith(b'\r\n'):
                raise ValueError('truncated or trailing Node inventory data')
            if line.startswith(b'#footer\t'):
                footer = json.loads(line[8:])
                continue
            raw_id, separator, remainder = line[:-1].partition(b'\t')
            if (not separator or remainder.count(b'\t') != 1 or not raw_id.isdigit() or
                    raw_id.startswith(b'0')):
                raise ValueError('invalid Node inventory row')
            identifier = checked_id(int(raw_id))
            if identifier <= previous:
                raise ValueError('Node inventory IDs must be uniquely sorted')
            previous, count = identifier, count + 1
            body.update(line)
            if identifiers is not None:
                identifiers.add(identifier)
            if before_ids is not None:
                survivors += identifier in before_ids
    if (not footer or footer.get('complete') is not True or footer.get('nodeInventoryComplete') is not True or
            footer.get('rowCount') != count or count != expected['rows'] or
            ('footer' in expected and footer != expected['footer'])):
        raise ValueError('Node inventory footer/count does not close')
    return {'ids': identifiers, 'rows': count, 'survivors': survivors, 'metadata': metadata,
            'footer': footer, 'sha256': full.hexdigest(), 'body_sha256': body.hexdigest()}


def native_records(bundle, before, after, watcher):
    path = bundle / 'evolution.tsv'
    counts, decisions, records = Counter(), defaultdict(list), Counter()
    children, digest = SparseIds(), hashlib.sha256()
    coordinates, missing_coordinates = defaultdict(dict), Counter()
    header, footer, sequence, ordinal, events = None, None, 0, -1, 0
    with path.open('rb') as stream:
        first = stream.readline()
        digest.update(first)
        if first != ('\t'.join(HEADERS['evolution']) + '\n').encode():
            raise ValueError('invalid native evolution columns')
        for line in stream:
            digest.update(line)
            if footer is not None or not line.endswith(b'\n') or line.endswith(b'\r\n'):
                raise ValueError('truncated or trailing native journal data')
            fields = line[:-1].split(b'\t', 8)
            if len(fields) != 9:
                raise ValueError('invalid native evolution row')
            kind = fields[0].decode()
            current_seq, current_ordinal = (integer(value.decode()) for value in fields[1:3])
            if current_seq != sequence:
                if current_seq != sequence + 1 or kind != 'event' or current_ordinal != 0:
                    raise ValueError('noncontiguous native event sequence')
                sequence, ordinal = current_seq, -1
            if current_ordinal != ordinal + 1:
                raise ValueError('noncontiguous native record ordinal')
            ordinal = current_ordinal
            records[kind] += 1
            if header is None:
                if kind != 'header' or sequence or ordinal:
                    raise ValueError('missing native evolution header')
                header = json.loads(decode_cell(fields[8].decode()))
            elif kind == 'event':
                events += 1
                if sequence != events or fields[3] not in (b'add', b'delete', b'replace'):
                    raise ValueError('invalid native event')
            elif kind == 'edit':
                if not events or fields[5] not in (b'node', b'connection') or fields[6] not in (b'before', b'after'):
                    raise ValueError('edit outside a native event')
            elif kind in ('lineage', 'decision'):
                parent = checked_id(integer(fields[7].decode()))
                if fields[5:7] != [b'node', b'before'] or parent not in before['ids']:
                    raise ValueError('native lineage/decision parent absent from before inventory')
                detail = json.loads(decode_cell(fields[8].decode()))
                if not isinstance(detail, dict):
                    raise ValueError('native lineage/decision detail must be an object')
                if kind == 'lineage':
                    child = checked_id(detail.get('to_node_id'))
                    coordinate = detail.get('coordinates')
                    if (not events or detail.get('relation') != 'split' or child not in after['ids'] or
                            child in before['ids'] or not children.add(child) or
                            (coordinate is not None and (not isinstance(coordinate, list) or
                             any(type(value) is not int or value < 0 for value in coordinate)))):
                        raise ValueError('split successor must be unique, live, new and from an original parent')
                    if coordinate is None:
                        missing_coordinates[parent] += 1
                    else:
                        key = tuple(coordinate)
                        if key in coordinates[parent]:
                            raise ValueError('one original parent has duplicate native member coordinates')
                        coordinates[parent][key] = child
                    counts[parent] += 1
                else:
                    blockers = detail.get('blocker_node_ids')
                    reason = decode_cell(fields[4].decode())
                    if (events or sequence or detail.get('outcome') not in ('retain', 'replace') or
                            detail.get('pass') not in header.get('pass', '').split(',') or not reason or
                            not isinstance(blockers, list) or
                            any(checked_id(value) not in before['ids'] for value in blockers) or
                            len(set(blockers)) != len(blockers)):
                        raise ValueError('invalid current native pass decision')
                    decisions[parent].append({'outcome': detail['outcome'], 'reason': reason,
                        'blockers': blockers, 'update': detail.get('update_ordinal'), 'axis': detail.get('axis')})
            elif kind == 'footer':
                footer = json.loads(decode_cell(fields[8].decode()))
            else:
                raise ValueError('unsupported native journal record')
    if (not footer or footer.get('complete') is not True or footer.get('replayComplete') is not True or
            footer.get('nodeInventoryComplete') is not True or footer.get('eventCount') != events or
            footer.get('beforeNodeCount') != before['rows'] or footer.get('afterNodeCount') != after['rows'] or
            ('decisionCount' in footer and footer['decisionCount'] != records['decision'])):
        raise ValueError('native evolution footer/count does not close')
    watcher.digest(path, digest.hexdigest())
    return counts, dict(decisions), {'rows': dict(records), 'split_children': len(children),
        'known_coordinate_children': sum(map(len, coordinates.values())),
        'missing_coordinate_children': sum(missing_coordinates.values()),
        'header': header, 'footer': footer}, dict(coordinates), missing_coordinates


def aggregate_rows(groups):
    return [{'reason': name, **dict(counts)} for name, counts in
            sorted(groups.items(), key=lambda item: (-item[1]['gsim_children'], item[0]))]


def analyze(baseline_report, grh_bundle, gsim_bundle, output):
    started = time.monotonic()
    baseline_report, output = Path(baseline_report).resolve(), Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp')
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ('summary.json', 'parent-families.tsv', 'parent-families.pending',
                                               'coordinate-differences.tsv', 'coordinate-differences.pending')):
        raise ValueError('refusing to overwrite an existing analysis')
    watcher = Sources()
    baseline = watcher.json(baseline_report)
    if baseline.get('schema') != 'wolvrix.f30.split-gap.v1' or baseline.get('complete') is not True:
        raise ValueError('requires a completed bound split-gap report')
    digest, root = baseline.get('input_sha256'), baseline.get('root_name')
    if not digest or not root:
        raise ValueError('baseline report lacks native input/root identity')
    reports = {}
    for name in ('analysis', 'naming'):
        path = (Path(baseline[name]) / 'summary.json').resolve()
        expected = baseline.get('report_inputs', {}).get(str(path))
        if expected is None:
            raise ValueError('baseline does not bind its ' + name + ' report')
        reports[name] = watcher.json(path, expected)
        if (reports[name].get('complete') is not True or reports[name].get('input_sha256') != digest or
                reports[name].get('root_name') != root):
            raise ValueError('baseline index reports have incompatible input/root identities')
    if reports['naming'].get('passed') is not True:
        raise ValueError('requires passing baseline naming evidence')
    database = (Path(baseline['analysis']) / 'analysis.sqlite').resolve()
    database_identity = closed_database_identity(database)
    if database_identity != baseline.get('database'):
        raise ValueError('bound baseline database identity changed')
    bundles = {'grh': Path(grh_bundle).resolve(), 'gsim': Path(gsim_bundle).resolve()}
    boundaries, snapshots, counts, decisions, journals, before_bindings = {}, {}, {}, {}, {}, {}
    coordinate_members, coordinate_missing = {}, {}
    for engine in ENGINES:
        boundary = boundaries[engine] = boundary_evidence(bundles[engine], engine)
        if boundary['identity']['input_sha256'] != digest or boundary['header']['root_name'] != root:
            raise ValueError('current bundle has a different native input/root identity')
        for filename in FILES:
            watcher.watch(bundles[engine] / filename)
        baseline_inventory = reports['analysis']['inventories']['before_' + engine]
        source = Path(baseline_inventory['source']).resolve()
        recorded = reports['naming'].get('source_files', {})
        matches = [identity for path, identity in recorded.items() if Path(path).resolve() == source]
        if len(matches) != 1:
            raise ValueError('baseline before source is not uniquely bound to naming evidence')
        watcher.watch(source, matches[0])
        expected = {'header': baseline_inventory['metadata'], 'metadata': baseline_inventory['metadata'],
                    'snapshot_id': baseline_inventory['metadata']['snapshot_id'], 'input_sha256': digest,
                    'root_name': root, 'rows': baseline_inventory['nodes'], 'footer': baseline_inventory['footer']}
        with phase_progress('hash-bound-before', started, engine=engine):
            original = scan_nodes(source, expected, store=False)
            watcher.digest(source, original['sha256'])
        snapshots[engine] = {}
        for phase in ('before', 'after'):
            expected = {'header': boundary['header'], 'snapshot_id': boundary['header'][phase + '_snapshot_id'],
                        'input_sha256': digest, 'root_name': root, 'rows': boundary['footer'][phase + 'NodeCount'],
                        **boundary[phase]['nodes']}
            path = bundles[engine] / (phase + '.nodes.tsv')
            with phase_progress('scan-current-node-ids', started, engine=engine, snapshot=phase):
                scanned = scan_nodes(path, expected,
                    before_ids=None if phase == 'before' else snapshots[engine]['before']['ids'])
                watcher.digest(path, scanned['sha256'])
                snapshots[engine][phase] = scanned
            if phase == 'before' and scanned['body_sha256'] != original['body_sha256']:
                raise ValueError('current before Node data differs from the bound original index: ' + engine)
        before_bindings[engine] = {'baseline_source': str(source), 'rows': original['rows'],
                                  'body_sha256': original['body_sha256'], 'equal': True}
        with phase_progress('scan-current-native-records', started, engine=engine):
            counts[engine], decisions[engine], journals[engine], coordinate_members[engine], coordinate_missing[engine] = \
                native_records(bundles[engine], snapshots[engine]['before'], snapshots[engine]['after'], watcher)
        if journals[engine]['header'] != boundary['header'] or journals[engine]['footer'] != boundary['footer']:
            raise ValueError('current native journal changed after boundary validation')
        with phase_progress('bind-current-connections', started, engine=engine):
            for phase in ('before', 'after'):
                path = bundles[engine] / (phase + '.connections.tsv')
                watcher.digest(path, hash_file(path))
    accounting = {}
    for engine in ENGINES:
        before, after = snapshots[engine]['before'], snapshots[engine]['after']
        retired = sum(parent not in after['ids'] for parent in counts[engine])
        accounting[engine] = {'before': before['rows'], 'after': after['rows'], 'survivors': after['survivors'],
            'new_nodes': after['rows'] - after['survivors'], 'retired_originals': before['rows'] - after['survivors'],
            'parents': len(counts[engine]), 'children': sum(counts[engine].values()),
            'retired': retired, 'residual': len(counts[engine]) - retired}
        if (accounting[engine]['new_nodes'] != accounting[engine]['children'] or
                accounting[engine]['retired_originals'] != retired):
            raise ValueError('current native split lineage does not explain all additions/deletions: ' + engine)
    report = {'schema': SCHEMA, 'complete': False, 'input_sha256': digest, 'root_name': root,
        'baseline_report': str(baseline_report), 'database': database_identity, 'before_bindings': before_bindings,
        'journals': journals, 'accounting': accounting,
        'scope': 'Current split family counts and parent retention; names locate unique original-parent candidates and do not prove functional equivalence. Current journals are producer-complete, not independently replayed here. Connection files are bound by SHA256 and headers/footers, not analyzed.',
        'index_scope': 'Only before_*_nodes/names are read from the baseline sealed database; its existing stat identity and hashed baseline reports bind the index. Old after IDs, names and lineage are not used.',
        'decision_scope': 'All current native retain attempts grouped by complete reason sets; historical decisions are not inferred final temporal causes.',
        'coordinate_scope': 'Exact native coordinate vectors under unique original-parent name candidates. Every axis, including singleton axes, is retained. Missing/null coordinates are unavailable; no coordinates are inferred from names. Duplicate coordinates under one parent are rejected. This classification is independent of inventory-count categories.'}
    save_json(output / 'summary.json', report)
    seen, groups, reasons, grh_only_reasons, rows = set(), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), 0
    pending = output / 'parent-families.pending'
    coordinate_pending = output / 'coordinate-differences.pending'
    coordinate_groups, coordinate_totals, coordinate_rows = defaultdict(Counter), Counter(), 0
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db, \
            pending.open('x', encoding='utf-8') as stream, coordinate_pending.open('x', encoding='utf-8') as coordinate_stream:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-16384')
        for engine in ENGINES:
            for table, key in (('nodes', 'id'), ('names', 'path')):
                query = f'SELECT 1 FROM before_{engine}_{table} WHERE {key}=?'
                plan = db.execute('EXPLAIN QUERY PLAN ' + query, (1 if key == 'id' else 'example',)).fetchall()
                if not any('SEARCH ' in row[3].upper() for row in plan) or any('SCAN ' in row[3].upper() for row in plan):
                    raise ValueError('before lookup lacks an existing index')
        stream.write('#meta\t' + compact(report) + '\n' + '\t'.join(COLUMNS) + '\n')
        coordinate_stream.write('#meta\t' + compact(report) + '\n' + '\t'.join(COORDINATE_COLUMNS) + '\n')
        with phase_progress('compare-current-parent-families', started):
            for engine in ENGINES:
                peer = 'gsim' if engine == 'grh' else 'grh'
                for parent in sorted(counts[engine]):
                    own = db.execute(f'SELECT path FROM before_{engine}_nodes WHERE id=?', (parent,)).fetchone()
                    if own is None:
                        raise ValueError('native parent is absent from the bound before index')
                    path = own[0]
                    names = {side: None if path is None else db.execute(
                        f'SELECT node_id,occurrences FROM before_{side}_names WHERE path=?', (path,)).fetchone()
                        for side in ENGINES}
                    unique = all(value is not None and value[1] == 1 for value in names.values())
                    peer_id = names[peer][0] if unique else None
                    if unique and names[engine][0] != parent:
                        raise ValueError('original name index disagrees with original parent ID')
                    ids = {engine: parent, peer: peer_id}
                    key = ids['grh'], ids['gsim']
                    if key in seen:
                        continue
                    seen.add(key)
                    child = {side: counts[side].get(ids[side], 0) for side in ENGINES}
                    alive = {side: None if ids[side] is None else ids[side] in snapshots[side]['after']['ids'] for side in ENGINES}
                    if peer_id is None:
                        category = engine + '_split_parent_without_unique_original_peer'
                        contribution = (1 if engine == 'gsim' else -1) * (child[engine] - int(not alive[engine]))
                    else:
                        if peer_id not in snapshots[peer]['before']['ids']:
                            raise ValueError('peer from original index absent from current before inventory')
                        category = classify_family(child['grh'], child['gsim'], alive['grh'], alive['gsim'])
                        contribution = family_gap(child['grh'], child['gsim'], alive['grh'], alive['gsim'])
                    evidence = decisions['grh'].get(ids['grh'], [])
                    retain = sorted({record['reason'] for record in evidence if record['outcome'] == 'retain'})
                    values = (category, path, ids['grh'], ids['gsim'], child['grh'], child['gsim'],
                              alive['grh'], alive['gsim'], contribution, compact(retain), compact(evidence))
                    stream.write('\t'.join(encode_cell(value) for value in values) + '\n')
                    rows += 1
                    metric = Counter(families=1, grh_children=child['grh'], gsim_children=child['gsim'], net_gap=contribution)
                    groups[category].update(metric)
                    known = {side: coordinate_members[side].get(ids[side], {}) for side in ENGINES}
                    missing = {side: coordinate_missing[side].get(ids[side], 0) for side in ENGINES}
                    if peer_id is None:
                        coordinate_category = 'no_unique_original_peer'
                    elif child['grh'] and child['gsim']:
                        if any(missing.values()):
                            coordinate_category = 'both_split_coordinates_unavailable'
                        elif known['grh'].keys() == known['gsim'].keys():
                            coordinate_category = 'both_split_coordinates_equal'
                        else:
                            coordinate_category = 'both_split_coordinates_different'
                    else:
                        coordinate_category = 'not_both_split'
                    coordinate_groups[coordinate_category].update(metric)
                    for side in ENGINES:
                        coordinate_totals[side + '_known_children'] += len(known[side])
                        coordinate_totals[side + '_missing_children'] += missing[side]
                    if peer_id is not None:
                        shared = known['grh'].keys() & known['gsim'].keys()
                        coordinate_totals['known_coordinate_member_pairs'] += len(shared)
                        if any(missing.values()):
                            values = (coordinate_category, path, ids['grh'], ids['gsim'], 'unavailable', None, None, None)
                            coordinate_stream.write('\t'.join(encode_cell(value) for value in values) + '\n')
                            coordinate_rows += 1
                            coordinate_totals['families_with_unavailable_coordinates'] += 1
                        else:
                            for side in ENGINES:
                                other = 'gsim' if side == 'grh' else 'grh'
                                for coordinate in sorted(known[side].keys() - known[other].keys()):
                                    values = (coordinate_category, path, ids['grh'], ids['gsim'], side,
                                              compact(coordinate), known['grh'].get(coordinate), known['gsim'].get(coordinate))
                                    coordinate_stream.write('\t'.join(encode_cell(value) for value in values) + '\n')
                                    coordinate_rows += 1
                                    coordinate_totals[side + '_only_known_coordinates'] += 1
                    if category == 'gsim_only_split':
                        reasons['+'.join(retain) or 'no_retain_decision'].update(metric)
                    elif category == 'grh_only_split':
                        replace = sorted({record['reason'] for record in evidence if record['outcome'] == 'replace'})
                        grh_only_reasons['+'.join(replace) or 'no_replace_decision'].update(metric)
            stream.write('#footer\t' + compact({'complete': True, 'rowCount': rows}) + '\n')
            coordinate_stream.write('#footer\t' + compact({'complete': True, 'rowCount': coordinate_rows}) + '\n')
    expected_gap = ((accounting['gsim']['after'] - accounting['gsim']['before']) -
                    (accounting['grh']['after'] - accounting['grh']['before']))
    if sum(value['net_gap'] for value in groups.values()) != expected_gap:
        raise ValueError('family contributions do not close current inventory growth gap')
    for engine in ENGINES:
        if sum(value[engine + '_children'] for value in groups.values()) != accounting[engine]['children']:
            raise ValueError('family groups do not cover all current split children')
        if coordinate_totals[engine + '_known_children'] + coordinate_totals[engine + '_missing_children'] != accounting[engine]['children']:
            raise ValueError('coordinate inventories do not cover all current split children')
    if sum(value['families'] for value in coordinate_groups.values()) != rows:
        raise ValueError('coordinate categories do not cover all current parent families')
    watcher.check()
    if closed_database_identity(database) != database_identity:
        raise ValueError('baseline index changed during analysis')
    pending.replace(output / 'parent-families.tsv')
    coordinate_pending.replace(output / 'coordinate-differences.tsv')
    baseline_gap = baseline['net_split_gap']
    report.update(complete=True, sources=watcher.files, categories=aggregate_rows(groups),
        immediate_reasons=aggregate_rows(reasons), grh_only_reasons=aggregate_rows(grh_only_reasons),
        parent_families=rows, net_split_gap=expected_gap,
        coordinate_categories=aggregate_rows(coordinate_groups), coordinate_totals=dict(coordinate_totals),
        coordinate_differences_rows=coordinate_rows,
        baseline_net_split_gap=baseline_gap, net_split_gap_reduction=baseline_gap - expected_gap,
        wall_s=time.monotonic() - started)
    save_json(output / 'summary.json', report)
    print(compact({'complete': True, 'accounting': accounting, 'net_split_gap': expected_gap,
                   'net_split_gap_reduction': baseline_gap - expected_gap,
                   'categories': report['categories'], 'immediate_reasons': report['immediate_reasons']}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-report', 'grh-bundle', 'gsim-bundle', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    analyze(args.baseline_report, args.grh_bundle, args.gsim_bundle, args.output)


if __name__ == '__main__':
    main()
