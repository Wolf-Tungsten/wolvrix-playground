"""Analyze native F30 comb/split exchanges against an existing GSIM exchange.

This consumes producer snapshots and runtime journals only. It never ingests or
rewrites a design, and name candidates do not establish functional equivalence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from functools import lru_cache
import json
from multiprocessing import get_context
from pathlib import Path
import sqlite3
import time

from benchmark_f29_pass_trace import sha256
from compare_f29_node_names import (bundle_identity, compare_phase, load_nodes,
                                     save_report, write_rows)
from export_f29_full_split_exchange import (comparison_boundaries, evolution_summary,
                                           last_line, name_comparison_metadata,
                                           public_compare, verify_grh_continuity)
from semantic_node_exchange import HEADERS, IDENTITY, integer, parsed_row, verify_bundle

ROOT = Path(__file__).resolve().parents[1]
FILES = ('before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
         'after.nodes.tsv', 'after.connections.tsv')
LEGACY_ANCESTOR_QUERY = '''WITH RECURSIVE ancestors(id) AS
    (VALUES(?) UNION SELECT parent FROM lineage JOIN ancestors ON child=ancestors.id WHERE engine='grh')
    SELECT id FROM ancestors ORDER BY id'''
ANCESTOR_QUERY = '''WITH RECURSIVE ancestors(id) AS
    (VALUES(?) UNION SELECT parent FROM ancestors CROSS JOIN lineage ON child=ancestors.id WHERE engine='grh')
    SELECT id FROM ancestors ORDER BY id'''
DECISION_QUERY = "SELECT stage,node_id,pass,outcome,reason,detail FROM decisions WHERE engine='grh' AND node_id=?"
LINK_QUERY = "SELECT stage,parent,child,relation,coordinates FROM lineage WHERE engine='grh' AND child=?"
DECISION_COLUMNS = ('engine', 'stage', 'node_id', 'ordinal', 'pass', 'outcome', 'reason',
                    'blocker_node_ids_json', 'update_ordinal', 'axis', 'detail_json')
UNMATCHED_COLUMNS = ('engine', 'node_id', 'canonical_firrtl_path', 'name_path_json', 'native_name',
                     'reason', 'self_path_count', 'peer_path_count')
NAME_REASONS = {'missing_public_path', 'ambiguous_normalized_path_on_self',
                'missing_normalized_path_on_peer', 'ambiguous_normalized_path_on_peer'}


def query_plans(output):
    """Inspect the explanation hot paths without executing an inventory scan."""
    output = Path(output).resolve()
    with sqlite3.connect((output / 'analysis.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        queries = {'ancestors': ANCESTOR_QUERY, 'legacy_ancestors': LEGACY_ANCESTOR_QUERY,
            'decisions': DECISION_QUERY, 'links': LINK_QUERY,
            'children': 'SELECT child,coordinates FROM lineage WHERE engine=? AND parent=?',
            'node': 'SELECT path FROM after_grh_nodes WHERE id=?',
            'peer': 'SELECT node_id,occurrences FROM pre_comb_gsim_names WHERE path=?'}
        result = {'schema': 'wolvrix.f30.explanation-query-plans.v1', 'database': str(output / 'analysis.sqlite'),
                  'read_only': True, 'plans': {}}
        for name, query in queries.items():
            parameters = ('grh', 2) if name == 'children' else ('example.path',) if name == 'peer' else (2,)
            result['plans'][name] = [list(row) for row in db.execute('EXPLAIN QUERY PLAN ' + query, parameters)]
        result['indexes'] = [list(row) for row in db.execute(
            "SELECT name,tbl_name,sql FROM sqlite_schema WHERE type='index' AND tbl_name IN ('decisions','lineage')")]
        return result


@contextmanager
def phase_progress(name, started, **detail):
    phase_started = time.monotonic()
    print(json.dumps({'event': 'phase-start', 'phase': name,
                      'elapsed_s': phase_started - started, **detail}), flush=True)
    outcome = {}
    try:
        yield outcome
    except BaseException as error:
        finished = time.monotonic()
        print(json.dumps({'event': 'phase-failed', 'phase': name,
                          'elapsed_s': finished - started, 'phase_wall_s': finished - phase_started,
                          'error': repr(error), **detail}), flush=True)
        raise
    else:
        finished = time.monotonic()
        print(json.dumps({'event': 'phase-end', 'phase': name,
                          'elapsed_s': finished - started, 'phase_wall_s': finished - phase_started,
                          **detail, **outcome}), flush=True)


def boundary_evidence(bundle, engine):
    """Read identity and completion markers without trusting them as a replay."""
    bundle = Path(bundle).resolve()
    identity = bundle_identity(bundle, engine)
    footer_row = parsed_row(last_line(bundle / 'evolution.tsv'), HEADERS['evolution'])
    footer = json.loads(footer_row['detail_json'])
    if (footer_row['record'] != 'footer' or footer.get('complete') is not True or
            footer.get('replayComplete') is not True):
        raise ValueError('native bundle has no completion footer')
    result = {'identity': identity, 'header': identity['header'], 'footer': footer}
    for phase in ('before', 'after'):
        inventory = {}
        for table in ('nodes', 'connections'):
            path = bundle / f'{phase}.{table}.tsv'
            with path.open(encoding='utf-8', newline='') as stream:
                first = stream.readline()
                if not first.startswith('#meta\t') or not first.endswith('\n'):
                    raise ValueError('native snapshot has no metadata')
                metadata = json.loads(first[len('#meta\t'):])
                if stream.readline() != '\t'.join(HEADERS[table]) + '\n':
                    raise ValueError('native snapshot columns do not match')
            last = last_line(path)
            if not last.startswith('#footer\t'):
                raise ValueError('native snapshot has no completion footer')
            completion = json.loads(last[len('#footer\t'):])
            count = phase + ('NodeCount' if table == 'nodes' else 'ConnectionCount')
            if (any(metadata.get(key) != identity['header'].get(key) for key in IDENTITY) or
                    metadata.get('table') != table or metadata.get('snapshot_id') != identity['header'][phase + '_snapshot_id'] or
                    completion.get('complete') is not True or completion.get('rowCount') != footer.get(count)):
                raise ValueError('native snapshot identity/footer is not part of its journal')
            inventory[table] = {'metadata': metadata, 'footer': completion}
        result[phase] = inventory
    return result


def database_matches(database, verification, boundaries):
    if not isinstance(verification, dict) or not verification.get('complete') or not verification.get('replay_exact'):
        return False
    if verification.get('header') != boundaries['header'] or verification.get('footer') != boundaries['footer']:
        return False
    for phase in ('before', 'after'):
        if (verification.get(phase, {}).get('metadata') != boundaries[phase]['nodes']['metadata'] or
                any(verification.get(phase, {}).get(table) != boundaries[phase][table]['footer']
                    for table in ('nodes', 'connections'))):
            return False
    try:
        with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
            for record in ('header', 'footer'):
                rows = db.execute('SELECT detail_json FROM evolution WHERE record=?', (record,)).fetchall()
                if len(rows) != 1 or json.loads(rows[0][0]) != boundaries[record]:
                    return False
            for phase in ('before', 'after'):
                for table in ('nodes', 'connections'):
                    count = db.execute(f'SELECT COUNT(*) FROM {phase}_{table}').fetchone()[0]
                    if count != boundaries[phase][table]['footer']['rowCount']:
                        return False
            for table in ('nodes', 'connections'):
                for left, right in (('current', 'after'), ('after', 'current')):
                    if db.execute(f'SELECT * FROM {left}_{table} EXCEPT SELECT * FROM {right}_{table} LIMIT 1').fetchone():
                        return False
    except (sqlite3.Error, ValueError, OSError):
        return False
    return True


def verified_gsim(work, output):
    """Reuse only a replay cache bound to all five file hashes and database bytes."""
    work, output = Path(work).resolve(), Path(output).resolve()
    bundle, database = work / 'gsim-split', work / 'gsim-split.sqlite'
    cache_path = work / 'gsim-verification-cache.json'
    boundaries = boundary_evidence(bundle, 'gsim')
    evidence = {'bundle': str(bundle), 'source_work': str(work), 'reused': False}
    fingerprints = {name: sha256(bundle / name) for name in FILES}
    if cache_path.is_file() and database.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cache = {}
        verification = cache.get('verification', {}) if isinstance(cache, dict) else {}
        if (isinstance(cache, dict) and cache.get('schema') == 'wolvrix.f30.native-verification-cache.v1' and
                cache.get('bundle_sha256') == fingerprints and cache.get('database_sha256') == sha256(database) and
                database_matches(database, verification, boundaries)):
            evidence.update(reused=True, database=str(database), source_report=str(cache_path),
                source_report_sha256=sha256(cache_path), database_sha256=cache['database_sha256'],
                verification_basis='complete native replay cache bound to all five current file hashes and exact database SHA256')
            evidence['bundle_sha256'] = fingerprints
            (output / 'gsim-split').symlink_to(bundle, target_is_directory=True)
            (output / 'gsim-split.sqlite').symlink_to(database)
            (output / 'gsim-verification-cache.json').write_text(json.dumps(cache, indent=2) + '\n', encoding='utf-8')
            return database, verification, evidence
    database = output / 'gsim-split.sqlite'
    verification = verify_bundle(bundle, database)
    evidence.update(database=str(database), database_sha256=sha256(database),
                    bundle_sha256=fingerprints,
                    verification_basis='fresh native before+journal replay and exact after comparison')
    if (output / 'gsim-split').resolve() != bundle.resolve():
        (output / 'gsim-split').symlink_to(bundle, target_is_directory=True)
    (output / 'gsim-verification-cache.json').write_text(json.dumps({
        'schema': 'wolvrix.f30.native-verification-cache.v1', 'verification': verification,
        'bundle_sha256': fingerprints, 'database_sha256': evidence['database_sha256'],
        'source_work': str(work)}, indent=2) + '\n', encoding='utf-8')
    return database, verification, evidence


def verify_input(kind, source, output, started):
    """Spawn-safe worker; each task owns distinct SQLite and cache artifacts."""
    source, output = Path(source), Path(output)
    if kind in ('grh-comb', 'grh-split'):
        with phase_progress('replay-' + kind, started, bundle=str(source)):
            return verify_bundle(source, output / (kind + '.sqlite'))
    if kind == 'gsim-split':
        with phase_progress('verify-gsim-split-or-cache', started, work=str(source)) as outcome:
            result = verified_gsim(source, output)
            outcome['cache_reused'] = result[2]['reused']
            return result
    raise ValueError('unknown native verification input: ' + kind)


def import_evolution(db, database, engine, stage):
    db.execute('ATTACH DATABASE ? AS journal', (Path(database).resolve().as_uri() + '?mode=ro',))
    db.execute('''INSERT INTO lineage SELECT ?,?,object_id,json_extract(detail_json,'$.to_node_id'),
        json_extract(detail_json,'$.relation'),json_extract(detail_json,'$.coordinates')
        FROM journal.evolution WHERE record='lineage' ''', (engine, stage))
    db.execute('''INSERT INTO decisions SELECT ?,?,object_id,ordinal,
        json_extract(detail_json,'$.pass'),json_extract(detail_json,'$.outcome'),reason,
        json_extract(detail_json,'$.blocker_node_ids'),json_extract(detail_json,'$.update_ordinal'),
        json_extract(detail_json,'$.axis'),detail_json FROM journal.evolution WHERE record='decision' ''', (engine, stage))
    db.commit()
    db.execute('DETACH DATABASE journal')


def completed_rows(path, columns, metadata):
    """Decode a completed derived TSV; validation finishes before its consumer publishes."""
    count, footer = 0, None
    with path.open(encoding='utf-8', newline='') as stream:
        first = stream.readline()
        if not first.startswith('#meta\t') or not first.endswith('\n'):
            raise ValueError('completed TSV has no metadata: ' + str(path))
        actual = json.loads(first[len('#meta\t'):])
        if any(actual.get(key) != value for key, value in metadata.items()):
            raise ValueError('completed TSV identity does not match this analysis: ' + str(path))
        if stream.readline() != '\t'.join(columns) + '\n':
            raise ValueError('completed TSV columns do not match: ' + str(path))
        for line in stream:
            if footer is not None or not line.endswith('\n') or line.endswith('\r\n'):
                raise ValueError('invalid completed TSV: ' + str(path))
            if line.startswith('#footer\t'):
                footer = json.loads(line[len('#footer\t'):])
                continue
            row = parsed_row(line, columns)
            count += 1
            yield row
    if not footer or footer.get('complete') is not True or footer.get('rowCount') != count:
        raise ValueError('incomplete TSV footer: ' + str(path))


def unmatched_grh_rows(output, report):
    """Reuse compare_phase's exact predicate instead of repeating its full graph join."""
    comparison = report['comparison']['after']
    expected_path = output / 'after.unmatched.tsv'
    if not comparison.get('complete') or Path(comparison['unmatched_file']).resolve() != expected_path.resolve():
        raise ValueError('no completed after-stage unmatched inventory in this output')
    metadata = {'schema': 'wolvrix.f29.node-name-candidates.v1', 'phase': 'after',
        'grh_stage': comparison['grh_stage'], 'gsim_stage': comparison['gsim_stage'], **name_comparison_metadata()}
    counts, reasons, previous = Counter(), Counter(), {'grh': -1, 'gsim': -1}
    seen_gsim = False
    for row in completed_rows(expected_path, UNMATCHED_COLUMNS, metadata):
        engine, reason = row['engine'], row['reason']
        if engine not in previous or reason not in NAME_REASONS or (engine == 'grh' and seen_gsim):
            raise ValueError('invalid unmatched engine/reason/order')
        seen_gsim |= engine == 'gsim'
        identifier = integer(row['node_id'])
        if identifier <= previous[engine]:
            raise ValueError('unmatched Node IDs are not uniquely sorted')
        previous[engine] = identifier
        own, peer_count = integer(row['self_path_count']), integer(row['peer_path_count'])
        expected_reason = ('missing_public_path' if row['canonical_firrtl_path'] is None else
            'ambiguous_normalized_path_on_self' if own > 1 else
            'missing_normalized_path_on_peer' if peer_count == 0 else 'ambiguous_normalized_path_on_peer')
        if reason != expected_reason or (own == 1 and peer_count == 1):
            raise ValueError('unmatched reason conflicts with recorded multiplicities')
        counts[engine] += 1
        reasons[reason] += 1
        if engine == 'grh':
            yield identifier, row['canonical_firrtl_path'], reason
    if (any(counts[engine] != comparison[engine + '_unmatched_nodes'] for engine in previous) or
            dict(reasons) != comparison['unmatched_reasons']):
        raise ValueError('unmatched TSV counts differ from the completed name comparison')


def explanation_metadata(report):
    return {'schema': 'wolvrix.f30.native-decision-explanation.v1', 'input_sha256': report['input_sha256'],
            'scope': 'native pass decisions and lineage joined by producer IDs; name candidates do not prove functional equivalence'}


def completed_decisions(output, report):
    counts, breakdown = Counter(), Counter()
    previous = None
    for row in completed_rows(output / 'decisions.tsv', DECISION_COLUMNS, explanation_metadata(report)):
        if (row['engine'], row['stage']) not in {('grh', 'comb'), ('grh', 'split'), ('gsim', 'split')}:
            raise ValueError('invalid completed native decision engine/stage')
        key = (row['engine'], row['stage'], integer(row['node_id']), integer(row['ordinal']))
        if previous is not None and key < previous:
            raise ValueError('completed native decisions are not sorted')
        previous = key
        detail = json.loads(row['detail_json'])
        if any(detail.get(field) != row[field] for field in ('pass', 'outcome')):
            raise ValueError('completed native decision detail differs from its columns')
        counts[(row['engine'], row['stage'])] += 1
        breakdown[tuple(row[field] for field in ('engine', 'stage', 'pass', 'outcome', 'reason'))] += 1
    expected = {('grh', 'comb'): report['grh_verification']['grh-comb'].get('decisions', 0),
                ('grh', 'split'): report['grh_verification']['grh-split'].get('decisions', 0),
                ('gsim', 'split'): report['gsim_verification'].get('decisions', 0)}
    if any(counts[key] != count for key, count in expected.items()):
        raise ValueError('completed decisions count differs from the verified native journals')
    return sum(counts.values()), [dict(zip(('engine', 'stage', 'pass', 'outcome', 'reason', 'records'), (*key, count)))
        for key, count in sorted(breakdown.items())]


def export_decisions_and_reasons(db, output, report, *, reuse_decisions=False):
    metadata = explanation_metadata(report)
    if reuse_decisions:
        report['decision_count'], report['decision_breakdown'] = completed_decisions(output, report)
    else:
        full = write_rows(output / 'decisions.tsv', DECISION_COLUMNS, db.execute(
            'SELECT * FROM decisions ORDER BY engine,stage,node_id,ordinal'), metadata, report)
        report['decision_count'] = full['rows']
        report['decision_breakdown'] = [dict(zip(('engine', 'stage', 'pass', 'outcome', 'reason', 'records'), row))
            for row in db.execute('SELECT engine,stage,pass,outcome,reason,COUNT(*) FROM decisions GROUP BY engine,stage,pass,outcome,reason')]

    @lru_cache(maxsize=4096)
    def node(engine, phase, identifier):
        return db.execute(f'SELECT path FROM {phase}_{engine}_nodes WHERE id=?', (identifier,)).fetchone()

    @lru_cache(maxsize=4096)
    def peer(engine, phase, path):
        result = db.execute(f'SELECT node_id,occurrences FROM {phase}_{engine}_names WHERE path=?', (path,)).fetchone()
        return result[0] if result is not None and result[1] == 1 else None

    @lru_cache(maxsize=4096)
    def children(engine, parent):
        return tuple(db.execute('SELECT child,coordinates FROM lineage WHERE engine=? AND parent=?', (engine, parent)))

    @lru_cache(maxsize=4096)
    def ancestors_of(identifier):
        return tuple(row[0] for row in db.execute(ANCESTOR_QUERY, (identifier,)))

    @lru_cache(maxsize=4096)
    def decisions_of(identifier):
        return tuple(db.execute(DECISION_QUERY, (identifier,)))

    @lru_cache(maxsize=4096)
    def links_of(identifier):
        return tuple(db.execute(LINK_QUERY, (identifier,)))

    categories, decision_reasons = Counter(), Counter()
    reason_columns = ('grh_node_id', 'canonical_firrtl_path', 'name_match_reason', 'category',
        'native_decisions_json', 'ancestor_node_ids_json', 'lineage_json', 'blocker_nodes_json',
        'peer_native_candidates_json', 'evidence_level')

    def rows():
        for identifier, path, name_reason in unmatched_grh_rows(output, report):
            ancestors = ancestors_of(identifier)
            decisions, links, blockers = [], [], []
            for ancestor in ancestors:
                for stage, origin, pass_name, outcome, reason, detail in decisions_of(ancestor):
                    record = {'stage': stage, 'node_id': origin, 'pass': pass_name, 'outcome': outcome,
                              'reason': reason, 'detail': json.loads(detail)}
                    decisions.append(record)
                    decision_reasons[reason] += 1
                    phase = 'pre_comb' if stage == 'comb' else 'before'
                    for blocker in record['detail']['blocker_node_ids']:
                        value = node('grh', phase, blocker)
                        blockers.append({'stage': stage, 'node_id': blocker, 'path': value[0] if value else None})
                links.extend(dict(zip(('stage', 'parent', 'child', 'relation', 'coordinates'), row))
                    for row in links_of(ancestor))
            category, peers, level = 'unexplained_native_difference', [], 'inventory-only'
            if name_reason != 'missing_normalized_path_on_peer':
                category = name_reason
            elif any(record['outcome'] == 'retain' for record in decisions):
                category, level = 'grh_retained_by_native_decision', 'native-decision-confirmed'
            for ancestor in ancestors:
                prior = node('grh', 'pre_comb', ancestor)
                if not prior:
                    continue
                other = peer('gsim', 'pre_comb', prior[0])
                if other is None:
                    continue
                own_children, peer_children = children('grh', ancestor), children('gsim', other)
                live_peer_children = [child for child, _ in peer_children if node('gsim', 'after', child)]
                if ancestor == identifier and live_peer_children and not node('gsim', 'after', other):
                    category, peers, level = 'gsim_split_grh_retained', live_peer_children, 'native-lineage-confirmed'
                    break
                if ancestor != identifier and own_children:
                    if not peer_children and node('gsim', 'after', other):
                        category, peers, level = 'grh_split_gsim_retained', [other], 'native-lineage-confirmed'
                        break
                    own_coordinates = [coords for child, coords in own_children if child == identifier]
                    matched = [child for child, coords in peer_children if coords in own_coordinates and node('gsim', 'after', child)]
                    if len(matched) == 1:
                        category, peers, level = 'split_member_name_difference', matched, 'native-lineage-confirmed'
                        break
            if category == 'unexplained_native_difference' and decisions:
                category, level = 'native_decision_without_unique_peer', 'native-decision-confirmed'
            categories[category] += 1
            yield (identifier, path, name_reason, category, json.dumps(decisions, ensure_ascii=False),
                json.dumps(ancestors), json.dumps(links, ensure_ascii=False), json.dumps(blockers, ensure_ascii=False),
                json.dumps(peers), level)
    written = write_rows(output / 'unmatched-reasons.tsv', reason_columns, rows(), metadata, report)
    if written['rows'] != report['comparison']['after']['grh_unmatched_nodes']:
        raise ValueError('unmatched native explanation count differs from the complete GRH inventory')
    report['unmatched_categories'] = dict(categories)
    report['unmatched_decision_reason_occurrences'] = dict(decision_reasons)


def file_identity(path):
    stat = path.stat()
    return {'device': stat.st_dev, 'inode': stat.st_ino, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def resume_preflight(db, output, report):
    """Reuse completed proof stages explicitly; do not replay or scan native graphs."""
    if (report.get('schema') != 'wolvrix.f30.native-alignment-analysis.v1' or report.get('complete') is not False or
            Path(report.get('report_path', '')).resolve() != output / 'summary.json' or
            report.get('grh_continuity', {}).get('complete') is not True or
            report.get('grh_continuity', {}).get('exact') is not True or
            any(report.get('comparison', {}).get(phase, {}).get('complete') is not True
                for phase in ('pre_comb', 'before', 'after')) or
            not report.get('public_comparison') or not report.get('evolution')):
        raise ValueError('resume requires completed native replay, continuity and all comparisons')
    watched = {output / 'analysis.sqlite', output / 'decisions.tsv', output / 'after.unmatched.tsv'}
    stages = (('grh-comb', 'grh', 'pre_comb_grh', report.get('grh_verification', {}).get('grh-comb', {})),
              ('grh-split', 'grh', 'before_grh', report.get('grh_verification', {}).get('grh-split', {})),
              ('gsim-split', 'gsim', 'before_gsim', report.get('gsim_verification', {})))
    expected_counts = {'decisions': Counter(), 'lineage': Counter()}
    for label, engine, inventory, verification in stages:
        if verification.get('complete') is not True or verification.get('replay_exact') is not True:
            raise ValueError('resume requires three completed exact native replays')
        source = Path(report['inventories'][inventory]['source']).parent
        boundaries = boundary_evidence(source, engine)
        if (verification.get('header') != boundaries['header'] or verification.get('footer') != boundaries['footer'] or
                boundaries['identity']['input_sha256'] != report['input_sha256'] or
                boundaries['header']['root_name'] != report['root_name']):
            raise ValueError('native source identity changed since completed replay: ' + label)
        for phase in ('before', 'after'):
            if (verification.get(phase, {}).get('metadata') != boundaries[phase]['nodes']['metadata'] or
                    any(verification.get(phase, {}).get(table) != boundaries[phase][table]['footer']
                        for table in ('nodes', 'connections'))):
                raise ValueError('native boundary changed since completed replay: ' + label)
        expected_counts['decisions'][engine] += verification.get('decisions', 0)
        expected_counts['lineage'][engine] += verification.get('lineage_count', 0)
        watched.update(source / name for name in FILES)
        watched.add(output / (label + '.sqlite'))
    schemas = {'decisions': ('engine', 'stage', 'node_id', 'ordinal', 'pass', 'outcome', 'reason',
                            'blockers', 'update_ordinal', 'axis', 'detail'),
               'lineage': ('engine', 'stage', 'parent', 'child', 'relation', 'coordinates')}
    for table, columns in schemas.items():
        if tuple(row[1] for row in db.execute('PRAGMA table_info(' + table + ')')) != columns:
            raise ValueError('resume database has incompatible native trace schema: ' + table)
    for index, columns in (('decision_node', ('engine', 'node_id')),
                           ('lineage_parent', ('engine', 'parent')), ('lineage_child', ('engine', 'child'))):
        if tuple(row[2] for row in db.execute('PRAGMA index_info(' + index + ')')) != columns:
            raise ValueError('resume database is missing a trace lookup index: ' + index)
    # These are covering trace-index counts, not node/connection inventory scans.
    for table in ('decisions', 'lineage'):
        counts = dict(db.execute('SELECT engine,COUNT(*) FROM ' + table + ' GROUP BY engine'))
        expected = {engine: count for engine, count in expected_counts[table].items() if count}
        if counts != expected:
            raise ValueError('imported native trace count differs from completed replay: ' + table)
    for phase in ('pre_comb', 'before', 'after'):
        for engine in ('grh', 'gsim'):
            prefix = phase + '_' + engine
            if tuple(row[1] for row in db.execute('PRAGMA table_info(' + prefix + '_nodes)')) != (
                    'id', 'path', 'path_json', 'native_name'):
                raise ValueError('resume is missing a completed Node inventory: ' + prefix)
            if tuple(row[1] for row in db.execute('PRAGMA table_info(' + prefix + '_names)')) != (
                    'path', 'node_id', 'occurrences'):
                raise ValueError('resume is missing a completed name index: ' + prefix)
    # Fully validate small completed exports before touching interrupted outputs.
    sum(1 for _ in unmatched_grh_rows(output, report))
    completed_decisions(output, report)
    return {str(path): file_identity(path) for path in sorted(watched)}


def unused_artifact(path, label):
    ordinal = 1
    while (candidate := path.with_name(path.stem + '.' + label + '-' + str(ordinal) + path.suffix)).exists():
        ordinal += 1
    return candidate


def resume_export(output):
    """Finish explanations from an interrupted analysis using its read-only database."""
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    summary = output / 'summary.json'
    original = summary.read_bytes()
    report = json.loads(original)
    started = time.monotonic()
    database = output / 'analysis.sqlite'
    for suffix in ('-wal', '-journal'):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('resume requires an inactive analysis database without a pending journal')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA cache_size=-65536')
        db.execute('BEGIN')
        with phase_progress('validate-export-resume', started):
            watched = resume_preflight(db, output, report)
        backup = unused_artifact(summary, 'before-resume')
        with backup.open('xb') as stream:
            stream.write(original)
        pending = output / 'unmatched-reasons.pending'
        if pending.exists():
            pending.rename(unused_artifact(pending, 'interrupted'))
        report.pop('failed', None)
        report.pop('error', None)
        report['resume_export'] = {'mode': 'explanations-only', 'database_read_only': True,
            'previous_summary': str(backup), 'previous_summary_sha256': sha256(backup),
            'source_file_boundaries_checked': True, 'imported_trace_counts_checked': True,
            'native_replay_repeated': False, 'name_comparisons_repeated': False,
            'basis': 'reuse completed exact replay and comparisons from the saved report; native boundary markers and derived trace-index counts rechecked',
            'watched_files': watched}
        try:
            with phase_progress('resume-export-decisions-and-unmatched-reasons', started):
                export_decisions_and_reasons(db, output, report, reuse_decisions=True)
            if any(file_identity(Path(path)) != identity for path, identity in watched.items()):
                raise ValueError('resume source/database changed while exporting explanations')
            if summary.read_bytes() != original:
                raise ValueError('analysis summary changed while exporting explanations')
            report.update(complete=True)
            report['resume_export']['wall_s'] = time.monotonic() - started
            save_report(report)
            return report
        except BaseException as error:
            report.update(complete=False, failed=True, error=repr(error))
            report['resume_export']['wall_s'] = time.monotonic() - started
            if summary.read_bytes() == original:
                save_report(report)
            raise


def analyze(grh_comb, grh_split, gsim_work, output, names_work=None, verification_workers=3):
    if type(verification_workers) is not int or not 1 <= verification_workers <= 3:
        raise ValueError('verification_workers must be between 1 and 3')
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    if (output / 'summary.json').exists():
        raise ValueError('refusing to overwrite an existing alignment analysis')
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'schema': 'wolvrix.f30.native-alignment-analysis.v1', 'complete': False,
        'report_path': str(output / 'summary.json'), 'inventories': {}, 'comparison': {},
        'verification_workers': verification_workers,
        'names_work_supplied': str(Path(names_work).resolve()) if names_work else None,
        'scope': 'native before/evolution/after replay, unique producer-name candidates, public connections, decisions and lineage; not functional equivalence'}
    save_report(report)
    db = None
    try:
        comb_dir, split_dir = Path(grh_comb).resolve(), Path(grh_split).resolve()
        jobs = (('grh-comb', comb_dir), ('grh-split', split_dir), ('gsim-split', Path(gsim_work).resolve()))
        verified, failures = {}, []
        # No SQLite connection exists in this process until all workers finish.
        if verification_workers == 1:
            for kind, source in jobs:
                try:
                    verified[kind] = verify_input(kind, source, output, started)
                except Exception as error:
                    failures.append((kind, error))
        else:
            with ProcessPoolExecutor(max_workers=verification_workers, mp_context=get_context('spawn')) as executor:
                futures = {executor.submit(verify_input, kind, source, output, started): kind
                           for kind, source in jobs}
                for future in as_completed(futures):
                    kind = futures[future]
                    try:
                        verified[kind] = future.result()
                    except Exception as error:
                        failures.append((kind, error))
        if failures:
            report['verification_failures'] = [{'input': kind, 'error': repr(error)} for kind, error in failures]
            raise failures[0][1]
        comb, split = verified['grh-comb'], verified['grh-split']
        native_db, gsim, evidence = verified['gsim-split']
        identities = {'comb': bundle_identity(comb_dir, 'grh'), 'split': bundle_identity(split_dir, 'grh'),
                      'gsim': bundle_identity(Path(gsim_work).resolve() / 'gsim-split', 'gsim')}
        if len({item['input_sha256'] for item in identities.values()}) != 1 or len({item['header']['root_name'] for item in identities.values()}) != 1:
            raise ValueError('native bundles refer to different FIRRTL inputs or circuit roots')
        with phase_progress('verify-grh-comb-to-split-continuity', started):
            continuity = verify_grh_continuity(output / 'grh-comb.sqlite', output / 'grh-split.sqlite', comb, split)
        report.update(input_sha256=identities['comb']['input_sha256'], root_name=identities['comb']['header']['root_name'],
            grh_verification={'grh-comb': comb, 'grh-split': split}, gsim_verification=gsim,
            gsim_source_evidence=evidence,
            grh_continuity=continuity,
            semantic_boundaries=comparison_boundaries(split, gsim, comb))
        if names_work:
            prior_path = Path(names_work).resolve() / 'summary.json'
            prior = json.loads(prior_path.read_text(encoding='utf-8'))
            if not prior.get('complete') or prior.get('input_sha256') != report['input_sha256'] or prior.get('root_name') != report['root_name']:
                raise ValueError('prior names report has incompatible native input/root identity')
            report['prior_names_evidence'] = {'path': str(prior_path), 'sha256': sha256(prior_path),
                'reused': False, 'reason': 'all current GRH/GSIM name inventories are rebuilt from the verified native snapshots'}
        with phase_progress('compare-public-nodes-and-connections', started):
            report['public_comparison'] = public_compare(output / 'grh-split.sqlite', native_db)
        with phase_progress('summarize-native-evolution', started):
            report['evolution'] = {label: evolution_summary(directory / 'evolution.tsv')
                for label, directory in (('grh_comb', comb_dir), ('grh_split', split_dir),
                                         ('gsim_split', Path(gsim_work).resolve() / 'gsim-split'))}
        db = sqlite3.connect(output / 'analysis.sqlite', uri=True)
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA cache_size=-65536')
        for phase, grh_dir, grh_phase, gsim_phase in (('pre_comb', comb_dir, 'before', 'before'),
                ('before', split_dir, 'before', 'before'), ('after', split_dir, 'after', 'after')):
            for engine, bundle, native_phase, identity in (
                    ('grh', grh_dir, grh_phase, identities['comb' if phase == 'pre_comb' else 'split']),
                    ('gsim', Path(gsim_work).resolve() / 'gsim-split', gsim_phase, identities['gsim'])):
                prefix = phase + '_' + engine
                with phase_progress('import-node-inventory', started, snapshot=prefix):
                    report['inventories'][prefix] = load_nodes(db, bundle / (native_phase + '.nodes.tsv'), prefix,
                                                              engine, native_phase, identity, report)
            with phase_progress('compare-node-names', started, snapshot=phase):
                compare_phase(db, phase, output, report)
        db.executescript('''CREATE TABLE decisions(engine,stage,node_id,ordinal,pass,outcome,reason,blockers,update_ordinal,axis,detail);
            CREATE INDEX decision_node ON decisions(engine,node_id);
            CREATE TABLE lineage(engine,stage,parent,child,relation,coordinates);
            CREATE INDEX lineage_parent ON lineage(engine,parent);
            CREATE INDEX lineage_child ON lineage(engine,child);''')
        with phase_progress('import-native-decisions-and-lineage', started):
            import_evolution(db, output / 'grh-comb.sqlite', 'grh', 'comb')
            import_evolution(db, output / 'grh-split.sqlite', 'grh', 'split')
            import_evolution(db, native_db, 'gsim', 'split')
        with phase_progress('export-decisions-and-unmatched-reasons', started):
            export_decisions_and_reasons(db, output, report)
        db.commit()
        report.update(complete=True, wall_s=time.monotonic() - started)
        save_report(report)
        return report
    except Exception as error:
        report.update(failed=True, error=repr(error), wall_s=time.monotonic() - started)
        save_report(report)
        raise
    finally:
        if db is not None:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh-comb', type=Path)
    parser.add_argument('--grh-split', type=Path)
    parser.add_argument('--gsim-work', type=Path)
    parser.add_argument('--names-work', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verification-workers', type=int, choices=range(1, 4), default=3,
                        help='independent native replay workers, 1..3 (default: 3; 1 runs sequentially)')
    parser.add_argument('--query-plans', action='store_true', help='read-only EXPLAIN of explanation queries; no data scans')
    parser.add_argument('--resume-export', action='store_true', help='resume explanations only from a completed native replay/comparison database')
    args = parser.parse_args()
    if args.query_plans:
        print(json.dumps(query_plans(args.output), indent=2))
        return
    if args.resume_export:
        report = resume_export(args.output)
    elif any(value is None for value in (args.grh_comb, args.grh_split, args.gsim_work)):
        parser.error('--grh-comb, --grh-split and --gsim-work are required for a new analysis')
    else:
        report = analyze(args.grh_comb, args.grh_split, args.gsim_work, args.output, args.names_work,
                         args.verification_workers)
    print(json.dumps({'complete': report['complete'], 'comparison': report['comparison'],
                      'unmatched_categories': report['unmatched_categories']}, indent=2))


if __name__ == '__main__':
    main()
