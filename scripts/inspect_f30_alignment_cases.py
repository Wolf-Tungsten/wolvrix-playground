"""Inspect explicit F30 Node IDs using only indexed, read-only lookups.

This consumes a completed native-exchange analysis. Public names and native
lineage provide structural evidence, never cross-engine functional equivalence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3

from analyze_f30_alignment import NAME_REASONS, UNMATCHED_COLUMNS, completed_rows
from export_f29_full_split_exchange import name_comparison_metadata
from semantic_node_exchange import encode_cell, integer

ROOT = Path(__file__).resolve().parents[1]
ENGINES = ('grh', 'gsim')
PHASES = ('pre_comb', 'before', 'after')
NODE_COLUMNS = ('id', 'path', 'path_json', 'native_name')
LINEAGE_COLUMNS = ('stage', 'parent', 'child', 'relation', 'coordinates')
DECISION_COLUMNS = ('stage', 'node_id', 'ordinal', 'pass', 'outcome', 'reason',
                    'blockers', 'update_ordinal', 'axis', 'detail')
SCOPE = ('Native inventory and direct producer lineage only; public names are '
         'candidates and do not establish cross-engine functional equivalence.')
CLASSIFIED_COLUMNS = ('engine', 'node_id', 'canonical_firrtl_path', 'name_match_reason',
    'path_pattern', 'category', 'parent_id', 'parent_path', 'parent_alive',
    'own_live_children', 'peer_parent_id', 'peer_parent_path', 'peer_parent_alive',
    'peer_live_children', 'coordinates_json', 'peer_candidates_json',
    'native_decision_reasons_json', 'peer_native_decision_reasons_json', 'evidence_level', 'note')


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def queries():
    result = {}
    for phase in PHASES:
        for engine in ENGINES:
            prefix = phase + '_' + engine
            result[prefix + '_node'] = (
                f'SELECT id,path,path_json,native_name FROM {prefix}_nodes WHERE id=?', (1,))
            result[prefix + '_name'] = (
                f'SELECT node_id,occurrences FROM {prefix}_names WHERE path=?', ('example.path',))
    result['children'] = ('SELECT stage,parent,child,relation,coordinates FROM lineage '
                          'WHERE engine=? AND parent=? LIMIT ?', ('grh', 1, 4097))
    result['origins'] = ('SELECT stage,parent,child,relation,coordinates FROM lineage '
                         'WHERE engine=? AND child=? LIMIT ?', ('grh', 1, 4097))
    result['decisions'] = ('SELECT stage,node_id,ordinal,pass,outcome,reason,blockers,'
                           'update_ordinal,axis,detail FROM decisions '
                           'WHERE engine=? AND node_id=? LIMIT ?', ('grh', 1, 4097))
    return result


class Inspector:
    def __init__(self, db, limit=4096):
        self.db, self.limit, self.sql = db, limit, queries()

    def plans(self):
        result = {}
        for name, (query, parameters) in self.sql.items():
            plan = [list(row) for row in self.db.execute('EXPLAIN QUERY PLAN ' + query, parameters)]
            if any('SCAN ' in row[3].upper() for row in plan) or not any(
                    'SEARCH ' in row[3].upper() for row in plan):
                raise ValueError(f'lookup does not use an existing index: {name}: {plan}')
            result[name] = plan
        return result

    @lru_cache(maxsize=32768)
    def node(self, engine, phase, identifier):
        row = self.db.execute(self.sql[phase + '_' + engine + '_node'][0], (identifier,)).fetchone()
        return None if row is None else dict(zip(NODE_COLUMNS, row))

    @lru_cache(maxsize=8192)
    def name(self, engine, phase, path):
        if path is None:
            return None
        row = self.db.execute(self.sql[phase + '_' + engine + '_name'][0], (path,)).fetchone()
        return None if row is None else {'node_id': row[0], 'occurrences': row[1]}

    def records(self, kind, engine, identifier, columns):
        rows = self.db.execute(self.sql[kind][0], (engine, identifier, self.limit + 1)).fetchall()
        return {'truncated': len(rows) > self.limit,
                'records': [dict(zip(columns, row)) for row in rows[:self.limit]]}

    @lru_cache(maxsize=1024)
    def children(self, engine, parent):
        result = self.records('children', engine, parent, LINEAGE_COLUMNS)
        for record in result['records']:
            value = record['coordinates']
            record['coordinates'] = None if value is None else json.loads(value)
            record['after'] = self.node(engine, 'after', record['child'])
        result['live_children'] = sum(row['after'] is not None and row['relation'] == 'split'
                                      for row in result['records'])
        return result

    @lru_cache(maxsize=4096)
    def origins(self, engine, child):
        result = self.records('origins', engine, child, LINEAGE_COLUMNS)
        for record in result['records']:
            value = record['coordinates']
            record['coordinates'] = None if value is None else json.loads(value)
        return result

    @lru_cache(maxsize=4096)
    def decisions(self, engine, identifier):
        result = self.records('decisions', engine, identifier, DECISION_COLUMNS)
        for record in result['records']:
            for key in ('blockers', 'detail'):
                record[key] = json.loads(record[key])
        return result

    def parent(self, engine, identifier):
        peer_engine = 'gsim' if engine == 'grh' else 'grh'
        before = self.node(engine, 'pre_comb', identifier)
        own_name = None if before is None else self.name(engine, 'pre_comb', before['path'])
        peer_name = None if before is None else self.name(peer_engine, 'pre_comb', before['path'])
        unique = (own_name is not None and own_name['occurrences'] == 1 and
                  peer_name is not None and peer_name['occurrences'] == 1)
        peer = peer_name['node_id'] if unique else None
        return {'engine': engine, 'parent_id': identifier, 'pre_comb': before,
                'before': self.node(engine, 'before', identifier),
                'after': self.node(engine, 'after', identifier),
                'own_pre_comb_name': own_name, 'peer_pre_comb_name': peer_name,
                'own_children': self.children(engine, identifier),
                'native_decisions': self.decisions(engine, identifier),
                'unique_public_parent_peer': unique, 'peer_engine': peer_engine,
                'peer_parent_id': peer,
                'peer_pre_comb': None if peer is None else self.node(peer_engine, 'pre_comb', peer),
                'peer_after': None if peer is None else self.node(peer_engine, 'after', peer),
                'peer_children': None if peer is None else self.children(peer_engine, peer),
                'peer_native_decisions': None if peer is None else self.decisions(peer_engine, peer)}

    def inspect(self, engine, identifier):
        incoming = self.origins(engine, identifier)
        parents = sorted({identifier, *(row['parent'] for row in incoming['records'])})
        return {'engine': engine, 'node_id': identifier,
                'pre_comb': self.node(engine, 'pre_comb', identifier),
                'before': self.node(engine, 'before', identifier),
                'after': self.node(engine, 'after', identifier),
                'incoming_lineage': incoming,
                'parent_contexts': [self.parent(engine, parent) for parent in parents],
                'identity_conflicts': self.identity_conflicts(engine, identifier, incoming)}

    def identity_conflicts(self, engine, identifier, incoming):
        result = {'status': 'not_assessable', 'checks': [],
            'scope': 'Selected case only; stable original IDs or unique original parents and exact direct native coordinates.',
            'limitation': 'Structural identity evidence does not prove functional inequality.'}
        own = self.node(engine, 'after', identifier)
        original = self.node(engine, 'pre_comb', identifier)
        if own is None:
            result['reason'] = 'Selected Node is absent after.'
            return result
        if original is not None:
            parent = self.parent(engine, identifier)
            if not parent['unique_public_parent_peer'] or parent['peer_after'] is None:
                result['reason'] = 'Original Node lacks a unique original public peer alive after the pass.'
                return result
            coordinates, expected_kind = None, 'pre_comb_original'
            peer = parent['peer_after']
            result.update(pair_basis='stable_original_ids', original_path=original['path'])
        else:
            if incoming['truncated'] or len(incoming['records']) != 1:
                result['reason'] = 'Direct incoming lineage is absent, multiple, or truncated.'
                return result
            link = incoming['records'][0]
            coordinates = link['coordinates']
            if (link['relation'] != 'split' or not full_coordinates(coordinates) or
                    self.node(engine, 'pre_comb', link['parent']) is None):
                result['reason'] = 'No direct split from an original parent with complete native coordinates.'
                return result
            parent = self.parent(engine, link['parent'])
            if (not parent['unique_public_parent_peer'] or parent['own_children']['truncated'] or
                    parent['peer_children']['truncated']):
                result['reason'] = 'Original public parent is ambiguous or direct member inventory truncated.'
                return result
            if any(row['after'] is not None and row['relation'] == 'split' and
                    not full_coordinates(row['coordinates'])
                    for family in (parent['own_children'], parent['peer_children'])
                    for row in family['records']):
                result['reason'] = 'A live split member has incomplete coordinates; uniqueness is not inferred.'
                return result
            members = lambda children: [row for row in children['records'] if row['after'] is not None and
                row['relation'] == 'split' and row['coordinates'] == coordinates]
            own_members, peer_members = members(parent['own_children']), members(parent['peer_children'])
            if len(own_members) != 1 or own_members[0]['child'] != identifier or len(peer_members) != 1:
                result['reason'] = 'Complete direct coordinates do not identify exactly one live member on both sides.'
                return result
            expected_kind, peer = 'direct_split_member', peer_members[0]['after']
            result.update(pair_basis='direct_native_coordinates', coordinates=coordinates)
        peer_engine = parent['peer_engine']
        result.update(parent_anchor={'path': parent['pre_comb']['path'],
                engine + '_parent_id': parent['parent_id'], peer_engine + '_parent_id': parent['peer_parent_id']},
            identity_members=[{'engine': engine, 'node_id': identifier, 'path': own['path']},
                              {'engine': peer_engine, 'node_id': peer['id'], 'path': peer['path']}])
        if expected_kind == 'direct_split_member':
            result['coordinate_members'] = result['identity_members']
        if own['path'] is None or peer['path'] is None or own['path'] == peer['path']:
            result['reason'] = 'Expected identity peers have missing or equal public paths; no name collision tested.'
            return result

        def candidate_identity(candidate_engine, candidate_id):
            origin = self.origins(candidate_engine, candidate_id)
            identity = {'established': False, 'incoming_lineage': origin}
            original = self.node(candidate_engine, 'pre_comb', candidate_id)
            if original is not None:
                parent_id, kind, member_coordinates = candidate_id, 'pre_comb_original', None
            elif (not origin['truncated'] and len(origin['records']) == 1 and
                    origin['records'][0]['relation'] == 'split'):
                source = origin['records'][0]
                parent_id, kind, member_coordinates = source['parent'], 'direct_split_member', source['coordinates']
                if (not isinstance(member_coordinates, list) or not member_coordinates or
                        any(type(value) is not int or value < 0 for value in member_coordinates)):
                    identity['reason'] = 'Candidate split has no complete native coordinates.'
                    return identity
                original = self.node(candidate_engine, 'pre_comb', parent_id)
            else:
                identity['reason'] = 'Candidate has no unique complete direct original lineage.'
                return identity
            if original is None:
                identity['reason'] = 'Candidate direct parent is absent pre-comb; coordinates are not composed.'
                return identity
            candidate_peer_engine = 'gsim' if candidate_engine == 'grh' else 'grh'
            own_name = self.name(candidate_engine, 'pre_comb', original['path'])
            other_name = self.name(candidate_peer_engine, 'pre_comb', original['path'])
            identity.update(kind=kind, coordinates=member_coordinates,
                pre_comb_anchor={'engine': candidate_engine, 'node_id': parent_id, 'path': original['path'],
                    'own_name': own_name, 'peer_engine': candidate_peer_engine, 'peer_name': other_name})
            identity['established'] = (own_name is not None and own_name['occurrences'] == 1 and
                other_name is not None and other_name['occurrences'] == 1)
            if not identity['established']:
                identity['reason'] = 'Candidate original public parent has no unique peer.'
            return identity

        for source_engine, source, target_engine, expected in (
                (engine, own, peer_engine, peer), (peer_engine, peer, engine, own)):
            own_name = self.name(source_engine, 'after', source['path'])
            other_name = self.name(target_engine, 'after', source['path'])
            check = {'source_engine': source_engine, 'source_node_id': source['id'], 'path': source['path'],
                'source_name': own_name, 'candidate_engine': target_engine, 'candidate_name': other_name,
                'expected_peer_node_id': expected['id'], 'expected_peer_path': expected['path'],
                'pair_basis': result['pair_basis'], 'status': 'no_unique_name_candidate'}
            if expected_kind == 'direct_split_member':
                check.update(expected_coordinate_peer_node_id=expected['id'],
                             expected_coordinate_peer_path=expected['path'])
            if (own_name is not None and own_name['occurrences'] == 1 and
                    other_name is not None and other_name['occurrences'] == 1):
                candidate = self.node(target_engine, 'after', other_name['node_id'])
                if candidate is None or candidate['path'] != source['path'] or own_name['node_id'] != source['id']:
                    raise ValueError('after name lookup differs from its Node inventory')
                identity = candidate_identity(target_engine, candidate['id'])
                check.update(candidate_node_id=candidate['id'], candidate_path=candidate['path'],
                             candidate_identity=identity, status='collision_risk')
                if (candidate['id'] != expected['id'] and identity['established'] and
                        (identity['kind'] != expected_kind or
                         identity['pre_comb_anchor']['path'] != parent['pre_comb']['path'] or
                         identity['coordinates'] != coordinates)):
                    check['status'] = 'structural_identity_conflict'
            result['checks'].append(check)
        statuses = {check['status'] for check in result['checks']}
        result['status'] = ('structural_identity_conflict' if 'structural_identity_conflict' in statuses else
            'collision_risk' if 'collision_risk' in statuses else 'no_unique_name_collision')
        return result

    def classify(self, engine, identifier, path, name_reason):
        after = self.node(engine, 'after', identifier)
        if after is None or after['path'] != path:
            raise ValueError(f'unmatched Node differs from after inventory: {engine}:{identifier}')
        result = dict.fromkeys(CLASSIFIED_COLUMNS)
        result.update(engine=engine, node_id=identifier, canonical_firrtl_path=path,
            name_match_reason=name_reason, path_pattern=path_pattern(path),
            category='other_unresolved', peer_candidate_ids=[], peer_candidates_json='[]',
            coordinates_json='null', native_decision_reasons_json='[]',
            peer_native_decision_reasons_json='[]',
            evidence_level='inventory-only', note='No direct comparable original parent.')
        original = self.node(engine, 'pre_comb', identifier)
        link = None
        if original is None:
            origins = self.origins(engine, identifier)
            if origins['truncated'] or len(origins['records']) != 1:
                result['note'] = 'Incoming lineage is absent, multiple, or truncated; no coordinates composed.'
                return result
            link = origins['records'][0]
            if link['relation'] != 'split':
                result['note'] = 'Direct incoming relation is not split.'
                return result
            result['coordinates_json'] = compact(link['coordinates'])
            if not full_coordinates(link['coordinates']):
                result['note'] = 'Direct split coordinates are absent or incomplete; no coordinates guessed.'
                return result
            if self.node(engine, 'pre_comb', link['parent']) is None:
                result['note'] = 'Direct parent is absent pre-comb; multi-level coordinates are not guessed.'
                return result
        parent = self.parent(engine, identifier if link is None else link['parent'])
        own_children, peer_children = parent['own_children'], parent['peer_children']
        reasons = [{'node_id': row['node_id'], 'stage': row['stage'],
                    'outcome': row['outcome'], 'reason': row['reason']}
                   for row in parent['native_decisions']['records']]
        peer_reasons = [{'node_id': row['node_id'], 'stage': row['stage'],
                         'outcome': row['outcome'], 'reason': row['reason']}
                        for row in (parent['peer_native_decisions'] or {}).get('records', [])]
        result.update(parent_id=parent['parent_id'], parent_path=parent['pre_comb']['path'],
            parent_alive=parent['after'] is not None, own_live_children=own_children['live_children'],
            peer_parent_id=parent['peer_parent_id'],
            peer_parent_path=None if parent['peer_pre_comb'] is None else parent['peer_pre_comb']['path'],
            peer_parent_alive=None if not parent['unique_public_parent_peer'] else parent['peer_after'] is not None,
            peer_live_children=None if peer_children is None else peer_children['live_children'],
            native_decision_reasons_json=compact(reasons),
            peer_native_decision_reasons_json=compact(peer_reasons))
        if not parent['unique_public_parent_peer']:
            result.update(category=('baseline_original_without_unique_public_peer' if link is None else
                'split_member_parent_without_unique_public_peer'),
                note='Pre-comb original public path has no unique peer; no cross-engine parent inferred.')
            return result
        if own_children['truncated'] or peer_children['truncated']:
            result['note'] = 'Bounded child lookup truncated; child counts are lower bounds.'
            return result
        result['evidence_level'] = 'native-lineage-and-inventory'
        own_live, peer_live = own_children['live_children'], peer_children['live_children']
        if link is None:
            if own_live:
                category = ('live_parent_with_members_peer_alive' if parent['peer_after'] is not None
                            else 'live_parent_with_members_peer_retired')
                result.update(category=category,
                    note='Own parent survives with native live members; this is not an unsplit parent.')
            elif peer_live and parent['peer_after'] is None:
                result.update(category='live_parent_unsplit_peer_split',
                    note='Own live parent has no native live members; peer parent retired with live members.')
            else:
                result['note'] = 'Comparable original parents exist; no asymmetric direct split established.'
            return result
        if parent['peer_after'] is not None and not peer_live:
            result.update(category='split_member_peer_parent_retained',
                peer_candidate_ids=[parent['peer_parent_id']],
                peer_candidates_json=compact([{'node_id': parent['peer_parent_id'],
                                               'path': parent['peer_after']['path']}]),
                note='Own direct split member; peer original parent is live without native live members.')
            return result
        if any(row['after'] is not None and row['relation'] == 'split' and
                not full_coordinates(row['coordinates']) for row in peer_children['records']):
            result['note'] = 'A live peer member has absent or incomplete coordinates.'
            return result
        matched = [row for row in peer_children['records'] if row['after'] is not None and
                   row['relation'] == 'split' and row['coordinates'] == link['coordinates']]
        result['peer_candidate_ids'] = [row['child'] for row in matched]
        result['peer_candidates_json'] = compact([{'node_id': row['child'],
            'path': row['after']['path']} for row in matched])
        if len(matched) > 1:
            result.update(category='split_member_coordinate_ambiguous',
                          note='Multiple live peer members have the same complete direct coordinates.')
        elif not matched:
            result.update(category='split_member_without_peer_coordinates',
                          note='No live peer member has the same complete direct coordinates.')
        else:
            peer_after = matched[0]['after']
            own_name = self.name(engine, 'after', path)
            peer_engine = parent['peer_engine']
            peer_name = self.name(peer_engine, 'after', peer_after['path'])
            if ((own_name and own_name['occurrences'] > 1) or
                    (peer_name and peer_name['occurrences'] > 1)):
                result.update(category='split_member_same_coordinate_name_ambiguous',
                    note='Unique parent and complete coordinates locate a member with an ambiguous public name.')
            elif peer_after['path'] != path:
                result.update(category='split_member_same_coordinate_name_difference',
                    note='Unique parent and complete coordinates locate a member with a different public name.')
            else:
                result['note'] = 'Same unique public name unexpectedly appears in unmatched input.'
        return result


def full_coordinates(value):
    return isinstance(value, list) and bool(value) and all(type(item) is int and item >= 0 for item in value)


def path_pattern(path):
    value = path or ''
    if re.search(r'(?:^|\.)when@', value):
        return 'when_at_leaf'
    if '$address' in value:
        return 'dollar_address'
    if '$storage' in value:
        return 'dollar_storage'
    if '$ADDR' in value:
        return 'dollar_ADDR_pipeline'
    return 'other'


def unmatched_rows(source, summary):
    comparison, path = summary['comparison']['after'], source / 'after.unmatched.tsv'
    if not comparison.get('complete') or Path(comparison['unmatched_file']).resolve() != path.resolve():
        raise ValueError('unmatched source is not bound to the completed after comparison')
    metadata = {'schema': 'wolvrix.f29.node-name-candidates.v1', 'phase': 'after',
        'grh_stage': comparison['grh_stage'], 'gsim_stage': comparison['gsim_stage'],
        **name_comparison_metadata()}
    previous, counts, reasons, seen_gsim = dict.fromkeys(ENGINES, -1), Counter(), Counter(), False
    for row in completed_rows(path, UNMATCHED_COLUMNS, metadata):
        engine, reason = row['engine'], row['reason']
        if engine not in previous or reason not in NAME_REASONS or (engine == 'grh' and seen_gsim):
            raise ValueError('invalid unmatched engine/reason/order')
        seen_gsim |= engine == 'gsim'
        identifier = integer(row['node_id'])
        if identifier <= previous[engine]:
            raise ValueError('unmatched Node IDs are not unique and ordered within engine')
        own, peer = integer(row['self_path_count']), integer(row['peer_path_count'])
        expected = ('missing_public_path' if row['canonical_firrtl_path'] is None else
                    'ambiguous_normalized_path_on_self' if own > 1 else
                    'missing_normalized_path_on_peer' if peer == 0 else 'ambiguous_normalized_path_on_peer')
        if reason != expected or (own == 1 and peer == 1):
            raise ValueError('unmatched reason conflicts with recorded multiplicities')
        previous[engine], counts[engine] = identifier, counts[engine] + 1
        reasons[reason] += 1
        yield engine, identifier, row['canonical_firrtl_path'], reason
    if (any(counts[engine] != comparison[engine + '_unmatched_nodes'] for engine in ENGINES) or
            dict(reasons) != comparison['unmatched_reasons']):
        raise ValueError('unmatched TSV counts or reason totals differ from completed comparison')


def classify_all(inspector, source, output, summary, metadata):
    counts = {engine: Counter() for engine in ENGINES}
    patterns = {engine: Counter() for engine in ENGINES}
    cross = {engine: Counter() for engine in ENGINES}
    row_counts = Counter()
    pending = {engine: output / (engine + '.unmatched.pending') for engine in ENGINES}
    with ExitStack() as stack:
        streams = {engine: stack.enter_context(path.open('w', encoding='utf-8', newline=''))
                   for engine, path in pending.items()}
        for engine, stream in streams.items():
            stream.write('#meta\t' + compact({**metadata, 'engine': engine}) + '\n' +
                         '\t'.join(CLASSIFIED_COLUMNS) + '\n')
        for engine, identifier, path, reason in unmatched_rows(source, summary):
            row = inspector.classify(engine, identifier, path, reason)
            streams[engine].write('\t'.join(encode_cell(row[column]) for column in CLASSIFIED_COLUMNS) + '\n')
            counts[engine][row['category']] += 1
            patterns[engine][row['path_pattern']] += 1
            cross[engine][(row['category'], row['path_pattern'])] += 1
            row_counts[engine] += 1
            if sum(row_counts.values()) % 50000 == 0:
                print(compact({'phase': 'classify-unmatched', 'rows': dict(row_counts)}), flush=True)
        for engine, stream in streams.items():
            expected = summary['comparison']['after'][engine + '_unmatched_nodes']
            if row_counts[engine] != expected:
                raise ValueError(f'{engine} unmatched count {row_counts[engine]} != summary {expected}')
            stream.write('#footer\t' + compact({'complete': True, 'rowCount': row_counts[engine]}) + '\n')
    return pending, {'complete': True, 'rows': dict(row_counts),
        'categories': {engine: dict(value) for engine, value in counts.items()},
        'path_patterns': {engine: dict(value) for engine, value in patterns.items()},
        'category_path_patterns': {engine: [{'category': category, 'path_pattern': pattern, 'rows': count}
            for (category, pattern), count in sorted(value.items())] for engine, value in cross.items()}}


def write_tsv(path, columns, rows, metadata):
    pending, count = path.with_suffix('.pending'), 0
    with pending.open('w', encoding='utf-8', newline='') as stream:
        stream.write('#meta\t' + compact(metadata) + '\n' + '\t'.join(columns) + '\n')
        for row in rows:
            stream.write('\t'.join(encode_cell(value) for value in row) + '\n')
            count += 1
        stream.write('#footer\t' + compact({'complete': True, 'rowCount': count}) + '\n')
    return pending, count


def selected_ids(value):
    fields = re.split(r'[\s,]+', value.strip())
    if not fields or any(not re.fullmatch(r'[1-9][0-9]*', value) for value in fields):
        raise argparse.ArgumentTypeError('IDs must be positive decimal integers separated by spaces or commas')
    result = list(dict.fromkeys(int(value) for value in fields))
    if len(result) > 32 or any(value > 2**63 - 1 for value in result):
        raise argparse.ArgumentTypeError('select at most 32 IDs within signed 64-bit range')
    return result


def identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def no_journal(database):
    for suffix in ('-wal', '-journal'):
        journal = Path(str(database) + suffix)
        if journal.exists() and journal.stat().st_size:
            raise ValueError('completed source database has a nonempty journal: ' + str(journal))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engine', choices=ENGINES, default='grh')
    parser.add_argument('--ids', type=selected_ids)
    parser.add_argument('--limit', type=int, default=4096)
    parser.add_argument('--query-plans-only', action='store_true')
    parser.add_argument('--all-unmatched', action='store_true',
                        help='stream both engines from after.unmatched.tsv; no full graph SQL scan')
    args = parser.parse_args()
    if not 1 <= args.limit <= 4096:
        parser.error('--limit must be between 1 and 4096')
    if not args.ids and not args.query_plans_only and not args.all_unmatched:
        parser.error('select --ids, --all-unmatched, or --query-plans-only')
    source, output = args.analysis.resolve(), args.output.resolve()
    if not source.is_relative_to(ROOT / 'ptmp') or not output.is_relative_to(ROOT / 'ptmp'):
        parser.error('analysis and output must be under repository ptmp/')
    summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
    if (summary.get('schema') != 'wolvrix.f30.native-alignment-analysis.v1' or
            summary.get('complete') is not True or summary.get('failed')):
        parser.error('analysis must be complete before inspecting its inventory')
    if not args.query_plans_only and (output / 'summary.json').exists():
        parser.error('inspection output already published; choose a new output directory')
    output.mkdir(parents=True, exist_ok=True)
    metadata = {'schema': 'wolvrix.f30.indexed-node-inspection.v1', 'scope': SCOPE,
                'input_sha256': summary['input_sha256'], 'analysis': str(source),
                'read_only': True, 'lookup_limit': args.limit,
                'live_children_definition': 'Live direct successors with native relation=split only.'}
    database = source / 'analysis.sqlite'
    watched = [database, source / 'summary.json']
    if args.all_unmatched:
        watched.append(source / 'after.unmatched.tsv')
    no_journal(database)
    identities = {path: identity(path) for path in watched}
    classified, all_report = {}, None
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-4096')
        db.execute('PRAGMA busy_timeout=1000')
        inspector = Inspector(db, args.limit)
        plans = inspector.plans()
        (output / 'query-plans.json').write_text(
            json.dumps({**metadata, 'plans': plans}, ensure_ascii=False, indent=2) + '\n')
        if args.query_plans_only:
            print(compact({'complete': True, 'indexed_query_count': len(plans), 'output': str(output)}))
            return
        cases = [inspector.inspect(args.engine, identifier) for identifier in (args.ids or [])]
        if args.all_unmatched:
            classified, all_report = classify_all(inspector, source, output, summary, metadata)
    no_journal(database)
    if any(identity(path) != value for path, value in identities.items()):
        raise ValueError('source analysis changed during read-only inspection; pending output not published')
    for engine, pending in classified.items():
        pending.replace(output / (engine + '.unmatched.tsv'))
    if cases:
        pending, count = write_tsv(output / 'cases.tsv', ('engine', 'node_id', 'after_path',
            'after_alive', 'inspection_json'), ((case['engine'], case['node_id'],
            None if case['after'] is None else case['after']['path'], case['after'] is not None,
            compact(case)) for case in cases), metadata)
        pending.replace(output / 'cases.tsv')
        (output / 'cases.json').write_text(json.dumps({**metadata, 'cases': cases},
                                                     ensure_ascii=False, indent=2) + '\n')
    (output / 'summary.json').write_text(json.dumps({**metadata, 'complete': True,
        'selected_engine': args.engine, 'selected_ids': args.ids or [], 'rows': len(cases),
        'all_unmatched': all_report,
        'path_pattern_scope': 'Text patterns only; no Node excluded and no semantic correspondence inferred.'},
        ensure_ascii=False, indent=2) + '\n')
    print(compact({'complete': True, 'selected_rows': len(cases),
                  'unmatched_rows': None if all_report is None else all_report['rows'], 'output': str(output)}))


if __name__ == '__main__':
    main()
