"""Attribute the full-graph split Node count gap to native parent families.

Current and baseline lineage/decision payloads must agree before the existing
read-only name index is used. This report does not modify or replay the IR.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import heapq
import json
from pathlib import Path
import sqlite3
import time

from analyze_f30_alignment import boundary_evidence, phase_progress
from export_f30_connection_differences import closed_database_identity, file_identity, save_json
from f30_split_gap_accounting import classify_family, family_gap, resolve_blocker
from inspect_f30_alignment_cases import Inspector
from semantic_node_exchange import HEADERS, decode_cell, encode_cell

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def native_records(bundle, collect=True):
    counts, decisions = Counter(), defaultdict(list)
    children, seen_children = array('q'), set()
    digests = {kind: hashlib.sha256() for kind in ('lineage', 'decision')}
    records = Counter()
    with (bundle / 'evolution.tsv').open(encoding='utf-8', newline='') as stream:
        if stream.readline() != '\t'.join(HEADERS['evolution']) + '\n':
            raise ValueError('invalid native evolution columns')
        for line in stream:
            kind = line.partition('\t')[0]
            if kind not in digests:
                continue
            fields = line.rstrip('\n').split('\t', 8)
            if len(fields) != 9:
                raise ValueError('invalid native evolution row')
            # Event ordinals can change when obsolete rename edits disappear.
            digests[kind].update(('\t'.join([kind, fields[4], fields[5], fields[6], fields[7], fields[8]]) + '\n').encode())
            identifier = int(fields[7])
            records[kind] += 1
            if not collect:
                continue
            detail = json.loads(decode_cell(fields[8]))
            if kind == 'lineage':
                child = detail['to_node_id']
                if (detail.get('relation') != 'split' or fields[5:7] != ['node', 'before'] or
                        type(child) is not int or child <= 0 or child in seen_children):
                    raise ValueError('split children must have one original parent each')
                seen_children.add(child)
                children.append(child)
                counts[identifier] += 1
            else:
                decisions[identifier].append({'outcome': detail['outcome'], 'reason': decode_cell(fields[4]),
                    'blockers': detail.get('blocker_node_ids', []), 'update': detail.get('update_ordinal'),
                    'axis': detail.get('axis')})
    return counts, dict(decisions), children, {'rows': dict(records),
        'sha256': {kind: digest.hexdigest() for kind, digest in digests.items()}}


def counter_rows(groups):
    return [{'reason': key, **dict(value)} for key, value in
        sorted(groups.items(), key=lambda item: (-item[1]['gsim_children'], item[0]))]


def analyze(analysis, naming, grh, gsim, output):
    started = time.monotonic()
    analysis, naming, grh, gsim, output = (Path(path).resolve() for path in (analysis, naming, grh, gsim, output))
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'summary.json').exists():
        raise ValueError('refusing to overwrite a report')
    report_inputs = {str(path): {'identity': file_identity(path),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in
        (analysis / 'summary.json', naming / 'summary.json')}
    prior = json.loads((analysis / 'summary.json').read_text())
    names = json.loads((naming / 'summary.json').read_text())
    if not prior.get('complete') or not names.get('passed') or not names.get('complete'):
        raise ValueError('requires completed alignment and passing naming evidence')
    if any(prior.get(key) != names.get(key) or not names.get(key)
           for key in ('input_sha256', 'root_name')):
        raise ValueError('alignment and naming reports describe different designs')
    source_stats = names['source_files']
    for path, expected in source_stats.items():
        if file_identity(Path(path)) != expected:
            raise ValueError('naming source changed: ' + path)
    for engine in ('grh', 'gsim'):
        if any(names['preservation'][engine][key] for key in ('before_id_differences', 'before_name_differences')):
            raise ValueError('baseline/current original identities differ')
        if any(names['after_id_sets'][engine][key] for key in ('added', 'removed')):
            raise ValueError('baseline/current after ID sets differ')
    current = {'grh': grh, 'gsim': gsim}
    baseline = {}
    boundaries = {}
    for engine, directory in current.items():
        if str(directory / 'evolution.tsv') not in source_stats:
            raise ValueError('current native bundle is not bound to naming evidence')
        baseline[engine] = Path(prior['inventories']['before_' + engine]['source']).parent
        if str(baseline[engine] / 'evolution.tsv') not in source_stats:
            # Older alignment may use a symlink to the same original bundle.
            resolved = (baseline[engine] / 'evolution.tsv').resolve()
            matches = [Path(path).parent for path in source_stats if path.endswith('/evolution.tsv') and Path(path).resolve() == resolved]
            if not matches:
                raise ValueError('baseline native bundle is not bound to naming evidence')
            baseline[engine] = matches[0]
        boundaries[engine] = boundary_evidence(directory, engine)
        header = boundaries[engine]['header']
        native_sha256 = header.get('input_sha256', header.get('input_identity', {}).get('sha256'))
        if (header.get('root_name') != names['root_name'] or
                native_sha256 != names['input_sha256']):
            raise ValueError('native bundle belongs to a different input/root')
    db_path = analysis / 'analysis.sqlite'
    db_identity = closed_database_identity(db_path)
    counts, decisions, children, bindings = {}, {}, {}, {}
    for engine in ('grh', 'gsim'):
        with phase_progress('bind-native-split-records', started, engine=engine) as phase:
            counts[engine], decisions[engine], children[engine], latest = native_records(current[engine])
            _, _, _, old = native_records(baseline[engine], collect=False)
            if latest != old:
                raise ValueError('native split lineage/decisions changed; baseline indexes cannot be reused: ' + engine)
            bindings[engine] = latest
            phase.update(latest, parents=len(counts[engine]))
    report = {'schema': 'wolvrix.f30.split-gap.v1', 'complete': False,
        'input_sha256': names['input_sha256'], 'root_name': names['root_name'],
        'analysis': str(analysis), 'naming': str(naming), 'report_inputs': report_inputs,
        'native_records_equal_to_baseline': bindings, 'database': db_identity,
        'scope': 'Native parent-family counts and GRH decision blocker evidence; unique before names locate parent candidates, not functional equivalence.',
        'decision_scope': 'All recorded attempts, grouped by complete reason sets without double counting families. Blocker closure records historical Node/reason facts, not final temporal causes or update/axis-level evidence. A cycle is a recorded blocker cycle and does not establish an IR combinational loop; replace, missing and cyclic evidence remain explicit issues.'}
    save_json(output / 'summary.json', report)
    groups, immediate, terminal, regions = (defaultdict(Counter) for _ in range(4))
    seen, top, rows = set(), [], 0
    totals = {engine: Counter() for engine in ('grh', 'gsim')}
    column_names = ('category', 'parent_path', 'grh_parent', 'gsim_parent', 'grh_children', 'gsim_children',
        'grh_parent_alive', 'gsim_parent_alive', 'net_gap_contribution', 'grh_retain_reasons',
        'grh_root_evidence')
    pending = output / 'parent-families.pending'
    with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as db, pending.open('x', encoding='utf-8') as stream:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-16384')
        inspector = Inspector(db)
        inspector.plans()
        with phase_progress('validate-live-new-split-children', started) as phase:
            for engine in ('grh', 'gsim'):
                query = (f'SELECT EXISTS(SELECT 1 FROM after_{engine}_nodes WHERE id=?), '
                         f'EXISTS(SELECT 1 FROM before_{engine}_nodes WHERE id=?)')
                for child_id in children[engine]:
                    if db.execute(query, (child_id, child_id)).fetchone() != (1, 0):
                        raise ValueError('split successor is not a live new Node')
            phase.update(children=sum(len(value) for value in children.values()))
        children.clear()
        stream.write('#meta\t' + compact(report) + '\n' + '\t'.join(column_names) + '\n')
        with phase_progress('attribute-parent-families', started) as phase:
            for engine in ('grh', 'gsim'):
                peer_engine = 'gsim' if engine == 'grh' else 'grh'
                for identifier in sorted(counts[engine]):
                    own = inspector.node(engine, 'before', identifier)
                    if own is None:
                        raise ValueError('lineage parent absent before pass')
                    own_name = inspector.name(engine, 'before', own['path'])
                    peer_name = inspector.name(peer_engine, 'before', own['path'])
                    peer_id = peer_name['node_id'] if own_name and own_name['occurrences'] == 1 and peer_name and peer_name['occurrences'] == 1 else None
                    ids = {engine: identifier, peer_engine: peer_id}
                    key = (ids['grh'], ids['gsim'])
                    if key in seen:
                        continue
                    seen.add(key)
                    child = {side: counts[side].get(ids[side], 0) for side in ('grh', 'gsim')}
                    alive = {side: None if ids[side] is None else inspector.node(side, 'after', ids[side]) is not None for side in ('grh', 'gsim')}
                    if peer_id is None:
                        category = engine + '_split_parent_without_unique_original_peer'
                        contribution = (1 if engine == 'gsim' else -1) * (child[engine] - int(not alive[engine]))
                    else:
                        category = classify_family(child['grh'], child['gsim'], alive['grh'], alive['gsim'])
                        contribution = family_gap(child['grh'], child['gsim'], alive['grh'], alive['gsim'])
                    own_decisions = decisions['grh'].get(ids['grh'], [])
                    reasons = sorted({record['reason'] for record in own_decisions if record['outcome'] == 'retain'})
                    roots = resolve_blocker(ids['grh'], decisions['grh']) if child['gsim'] and not child['grh'] and peer_id is not None else None
                    values = (category, own['path'], ids['grh'], ids['gsim'], child['grh'], child['gsim'],
                        alive['grh'], alive['gsim'], contribution, compact(reasons), compact(roots))
                    stream.write('\t'.join(encode_cell(value) for value in values) + '\n')
                    rows += 1
                    metric = Counter(families=1, grh_children=child['grh'], gsim_children=child['gsim'], net_gap=contribution)
                    groups[category].update(metric)
                    for side in ('grh', 'gsim'):
                        if ids[side] is not None and child[side]:
                            totals[side].update(parents=1, children=child[side], retired=int(not alive[side]), residual=int(alive[side]))
                    if child['gsim'] and not child['grh'] and peer_id is not None:
                        immediate['+'.join(reasons) or 'no_retain_decision'].update(metric)
                        terminal[compact({'reasons': roots['terminal_reasons'],
                            'issues': sorted({issue['kind'] for issue in roots['issues']})})].update(metric)
                        regions['.'.join(own['path'].split('.')[:6])].update(metric)
                        item = {'path': own['path'], 'grh_parent': ids['grh'], 'gsim_parent': ids['gsim'],
                            'gsim_children': child['gsim'], 'net_gap': contribution, 'immediate_reasons': reasons,
                            'root_evidence': roots}
                        rank = (contribution, own['path'], item)
                        if len(top) < 30:
                            heapq.heappush(top, rank)
                        elif rank[:2] > top[0][:2]:
                            heapq.heapreplace(top, rank)
                    if rows % 50000 == 0:
                        print(compact({'event': 'families-progress', 'rows': rows}), flush=True)
            phase.update(rows=rows)
        stream.write('#footer\t' + compact({'complete': True, 'rowCount': rows}) + '\n')
    accounting = {}
    for engine in ('grh', 'gsim'):
        footer = boundaries[engine]['footer']
        survivors = names['preservation'][engine]['original_survivors']
        accounting[engine] = {'before': footer['beforeNodeCount'], 'after': footer['afterNodeCount'],
            'survivors': survivors, 'new_nodes': footer['afterNodeCount'] - survivors,
            'retired_originals': footer['beforeNodeCount'] - survivors, **dict(totals[engine])}
        if accounting[engine]['new_nodes'] != totals[engine]['children'] or accounting[engine]['retired_originals'] != totals[engine]['retired']:
            raise ValueError('native split families do not explain all inventory additions/deletions')
    expected_gap = (accounting['gsim']['after'] - accounting['gsim']['before']) - (accounting['grh']['after'] - accounting['grh']['before'])
    if sum(value['net_gap'] for value in groups.values()) != expected_gap:
        raise ValueError('family contribution sum does not close net inventory gap')
    if closed_database_identity(db_path) != db_identity or any(file_identity(Path(path)) != expected for path, expected in source_stats.items()):
        raise ValueError('source evidence changed during analysis')
    if any(file_identity(Path(path)) != expected['identity'] or
           hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected['sha256']
           for path, expected in report_inputs.items()):
        raise ValueError('input reports changed during analysis')
    pending.replace(output / 'parent-families.tsv')
    report.update(complete=True, accounting=accounting, net_split_gap=expected_gap,
        categories=counter_rows(groups), immediate_reasons=counter_rows(immediate), terminal_reasons=counter_rows(terminal),
        regions=counter_rows(regions), top_families=[item[2] for item in sorted(top, reverse=True)],
        wall_s=time.monotonic() - started, parent_families=rows)
    save_json(output / 'summary.json', report)
    print(compact({'complete': True, 'accounting': accounting, 'net_split_gap': expected_gap,
        'categories': report['categories'], 'immediate_reasons': report['immediate_reasons'], 'terminal_reasons': report['terminal_reasons']}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('analysis', 'naming', 'grh', 'gsim', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    analyze(args.analysis, args.naming, args.grh, args.gsim, args.output)


if __name__ == '__main__':
    main()
