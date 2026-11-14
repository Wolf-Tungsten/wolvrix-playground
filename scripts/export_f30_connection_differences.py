"""Export coarse resolved connection differences from a completed F30 analysis."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import time

from export_f29_full_split_exchange import name_comparison_metadata
from semantic_node_exchange import encode_cell

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.connection-differences.v1'
EDGE_COLUMNS = ('source_path', 'target_path', 'kind', 'grh_source_node_id', 'grh_target_node_id',
                'gsim_source_node_id', 'gsim_target_node_id')
NODE_COLUMNS = ('canonical_firrtl_path', 'grh_node_id', 'gsim_node_id', 'grh_only_outgoing',
                'grh_only_incoming', 'gsim_only_outgoing', 'gsim_only_incoming', 'difference_incidents')
SCOPE = {
    'phase': 'after', 'resolution': 'resolved',
    'endpoints': 'both endpoints have the same unique normalized path on both engines',
    'identity': 'DISTINCT (source_path,target_path,kind); multiplicity and exchange-local connection IDs ignored',
    'excluded': ['unresolved connections', 'connections with an unmatched or ambiguous endpoint'],
    'limitations': ['coarse public Node connections; no bit ranges, ports, op/ENode or functional equivalence',
                   'affected Node incidents count source and target separately; a self-edge contributes two incidents'],
}


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def file_identity(path):
    status = path.stat()
    return {'path': str(path.resolve()), 'device': status.st_dev, 'inode': status.st_ino,
            'bytes': status.st_size, 'mtime_ns': status.st_mtime_ns}


def closed_database_identity(path):
    path = path.resolve()
    for suffix in ('-wal', '-journal'):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('source database has a pending journal: ' + str(path))
    return file_identity(path)


def save_json(path, value):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pending.replace(path)


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


def require_count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('missing or invalid completed count: ' + name)
    return value


def completed_analysis(directory):
    directory = Path(directory).resolve()
    source = directory / 'summary.json'
    contents = source.read_bytes()
    report = json.loads(contents)
    if (not isinstance(report, dict) or report.get('schema') != 'wolvrix.f30.native-alignment-analysis.v1' or
            report.get('complete') is not True or report.get('failed') or
            report.get('comparison', {}).get('after', {}).get('complete') is not True):
        raise ValueError('connection export requires a completed F30 alignment analysis')
    if Path(report.get('report_path', '')).resolve() != source:
        raise ValueError('completed alignment report path does not match its directory')
    digest, root = report.get('input_sha256'), report.get('root_name')
    if (not isinstance(digest, str) or len(digest) != 64 or
            any(character not in '0123456789abcdef' for character in digest) or
            not isinstance(root, str) or not root):
        raise ValueError('completed analysis lacks input/root identity')
    verifications = (report.get('grh_verification', {}).get('grh-split', {}),
                     report.get('gsim_verification', {}))
    for engine, verification in zip(('grh', 'gsim'), verifications):
        header = verification.get('header', {})
        declared = header.get('input_sha256', header.get('input_identity', {}).get('sha256'))
        if (verification.get('complete') is not True or verification.get('replay_exact') is not True or
                header.get('engine') != engine or header.get('root_name') != root or declared != digest):
            raise ValueError('completed native replay has incompatible input/root identity: ' + engine)
    expected = report.get('public_comparison')
    if not isinstance(expected, dict) or expected.get('name_comparison') != name_comparison_metadata():
        raise ValueError('completed public comparison has a different name comparison contract')
    fields = ('unique_name_candidates_after', 'grh_connections_after', 'gsim_connections_after',
              'grh_resolved_after', 'gsim_resolved_after', 'grh_unresolved_after', 'gsim_unresolved_after',
              'grh_comparable_resolved_after', 'gsim_comparable_resolved_after', 'matched_resolved_after')
    for field in fields:
        require_count(expected.get(field), field)
    if expected['unique_name_candidates_after'] != report['comparison']['after'].get('unique_name_candidates'):
        raise ValueError('completed name and public connection comparisons disagree')
    databases = {name: directory / filename for name, filename in
                 (('analysis', 'analysis.sqlite'), ('grh', 'grh-split.sqlite'), ('gsim', 'gsim-split.sqlite'))}
    identities = {}
    for name, path in databases.items():
        if not path.is_file():
            raise ValueError('missing completed analysis database: ' + str(path))
        identities[name] = closed_database_identity(path)
    return report, source, contents, databases, identities


def write_tsv(path, columns, rows, metadata):
    pending = path.with_suffix('.pending')
    count = 0
    with pending.open('x', encoding='utf-8', newline='') as stream:
        stream.write('#meta\t' + json.dumps(metadata, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.write('\t'.join(columns) + '\n')
        for row in rows:
            if len(row) != len(columns):
                raise ValueError('connection difference TSV column count mismatch')
            stream.write('\t'.join(encode_cell(value) for value in row) + '\n')
            count += 1
        stream.write('#footer\t' + json.dumps({'complete': True, 'rowCount': count}) + '\n')
    return pending, count


def build_connections(db, engine):
    # The common GRH ID is a bijective surrogate for the unique path. Integer
    # keys preserve public_compare's path tuple identity without copying long
    # hierarchy strings into every connection row.
    db.execute(f'''CREATE TEMP TABLE {engine}_edges(
        source INTEGER,target INTEGER,kind TEXT,PRIMARY KEY(source,target,kind)) WITHOUT ROWID''')
    db.execute(f'''INSERT OR IGNORE INTO {engine}_edges
        SELECT src.grh_id,dst.grh_id,json_extract(e.body,'$.kind')
        FROM {engine}.after_connections e
        JOIN common src ON src.{engine}_id=json_extract(e.body,'$.source_node_id')
        JOIN common dst ON dst.{engine}_id=json_extract(e.body,'$.target_node_id')
        WHERE json_extract(e.body,'$.resolution')='resolved' ''')
    return list(db.execute(f'''SELECT json_extract(e.body,'$.kind'),json_extract(e.body,'$.resolution'),
        COUNT(*),SUM(CASE WHEN src.grh_id IS NOT NULL AND dst.grh_id IS NOT NULL THEN 1 ELSE 0 END)
        FROM {engine}.after_connections e
        LEFT JOIN common src ON src.{engine}_id=json_extract(e.body,'$.source_node_id')
        LEFT JOIN common dst ON dst.{engine}_id=json_extract(e.body,'$.target_node_id')
        GROUP BY json_extract(e.body,'$.kind'),json_extract(e.body,'$.resolution')'''))


def summarize(db, raw):
    per_kind = {}
    for engine, rows in raw.items():
        for kind, resolution, count, comparable in rows:
            counts = per_kind.setdefault(kind, Counter())
            counts[engine + '_raw_connections'] += count
            counts[engine + '_raw_' + resolution] += count
            if resolution == 'resolved':
                counts[engine + '_raw_comparable_resolved'] += comparable
                counts[engine + '_excluded_resolved_unmatched_endpoints'] += count - comparable
    for engine in ('grh', 'gsim'):
        for kind, count in db.execute(f'SELECT kind,COUNT(*) FROM {engine}_edges GROUP BY kind'):
            per_kind.setdefault(kind, Counter())[engine + '_comparable_resolved_distinct'] = count
        for kind, count in db.execute(f'SELECT kind,COUNT(*) FROM {engine}_only GROUP BY kind'):
            per_kind.setdefault(kind, Counter())[engine + '_only_distinct'] = count
    for kind, count in db.execute('''SELECT g.kind,COUNT(*) FROM grh_edges g JOIN gsim_edges s
        ON g.source=s.source AND g.target=s.target AND g.kind=s.kind GROUP BY g.kind'''):
        per_kind.setdefault(kind, Counter())['matched_distinct'] = count
    columns = [engine + suffix for engine in ('grh', 'gsim') for suffix in
               ('_raw_connections', '_raw_resolved', '_raw_unresolved', '_raw_comparable_resolved',
                '_excluded_resolved_unmatched_endpoints', '_comparable_resolved_distinct', '_only_distinct',
                '_duplicates_in_comparable_resolved')] + ['matched_distinct']
    result, total = [], Counter({column: 0 for column in columns})
    for kind, counts in sorted(per_kind.items()):
        for engine in ('grh', 'gsim'):
            counts[engine + '_duplicates_in_comparable_resolved'] = (
                counts[engine + '_raw_comparable_resolved'] - counts[engine + '_comparable_resolved_distinct'])
            if (counts[engine + '_comparable_resolved_distinct'] !=
                    counts['matched_distinct'] + counts[engine + '_only_distinct']):
                raise ValueError('connection difference partition is inconsistent: ' + kind)
        row = {column: counts[column] for column in columns}
        result.append({'kind': kind, **row})
        total.update(row)
    return result, dict(total)


def summarize_unresolved(db, engine, expected):
    # Filter the native inventory once. Group indexes keep bounded example
    # lookups from rescanning every connection for each reason/candidate count.
    db.execute(f'''CREATE TEMP TABLE {engine}_unresolved AS
        SELECT id AS connection_id,json_extract(body,'$.target_node_id') AS target_id,
            json_extract(body,'$.kind') AS kind,json_extract(body,'$.reason') AS reason,
            json_array_length(body,'$.candidate_sources_json') AS candidate_source_count,
            json_extract(body,'$.candidate_sources_json') AS candidates
        FROM {engine}.after_connections WHERE json_extract(body,'$.resolution')='unresolved' ''')
    db.execute(f'''CREATE INDEX {engine}_unresolved_group ON
        {engine}_unresolved(kind,reason,candidate_source_count,connection_id)''')
    groups, reasons, total = [], Counter(), 0
    for kind, reason, candidate_count, count in db.execute(f'''SELECT kind,reason,candidate_source_count,COUNT(*)
            FROM {engine}_unresolved GROUP BY kind,reason,candidate_source_count
            ORDER BY kind,reason,candidate_source_count'''):
        examples = []
        samples = db.execute(f'''SELECT u.connection_id,u.target_id,n.path,n.native_name
            FROM {engine}_unresolved u LEFT JOIN analysis.after_{engine}_nodes n ON n.id=u.target_id
            WHERE u.kind=? AND u.reason IS ? AND u.candidate_source_count IS ?
            ORDER BY u.connection_id LIMIT 3''', (kind, reason, candidate_count))
        for identifier, target, target_path, native_name in samples:
            candidate_nodes = [dict(zip(('node_id', 'canonical_firrtl_path', 'native_name'), row))
                for row in db.execute(f'''SELECT j.value,n.path,n.native_name
                    FROM {engine}_unresolved u,json_each(u.candidates) j
                    LEFT JOIN analysis.after_{engine}_nodes n ON n.id=j.value
                    WHERE u.kind=? AND u.reason IS ? AND u.candidate_source_count IS ? AND u.connection_id=?
                    ORDER BY CAST(j.key AS INTEGER) LIMIT 16''', (kind, reason, candidate_count, identifier))]
            examples.append({'connection_id': identifier, 'target_node_id': target,
                'target_path': target_path, 'target_native_name': native_name,
                'candidate_sources': candidate_nodes, 'candidates_truncated': candidate_count > 16})
        groups.append({'kind': kind, 'reason': reason, 'candidate_source_count': candidate_count,
                       'connections': count, 'examples': examples})
        reasons[reason] += count
        total += count
    if total != expected:
        raise ValueError('unresolved counts differ from completed public comparison: ' + engine)
    return {'total': total, 'by_reason': [{'reason': reason, 'connections': count}
            for reason, count in sorted(reasons.items())], 'groups': groups}


def export(analysis, output, top_count=20):
    started = time.monotonic()
    if type(top_count) is not int or not 1 <= top_count <= 100:
        raise ValueError('top count must be between 1 and 100')
    with phase_progress('verify-source', started):
        source_report, report_path, report_bytes, databases, identities = completed_analysis(analysis)
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    summary = output / 'summary.json'
    scratch = output / 'scratch.sqlite'
    filenames = ('grh-only.connections.tsv', 'gsim-only.connections.tsv', 'affected-nodes.tsv')
    if summary.exists() or scratch.exists() or any((output / filename).exists() or (output / filename).with_suffix('.pending').exists()
                               for filename in filenames):
        raise ValueError('refusing to overwrite existing connection difference evidence')
    metadata = {'schema': SCHEMA, 'input_sha256': source_report['input_sha256'],
                'root_name': source_report['root_name'], 'source_report': str(report_path),
                'source_report_sha256': sha256_bytes(report_bytes), 'source_databases': identities,
                'source_binding': 'completed report SHA256 and source database stat identities; database bytes are not rehashed',
                'native_headers': {'grh': source_report['grh_verification']['grh-split']['header'],
                                   'gsim': source_report['gsim_verification']['header']},
                'name_comparison': name_comparison_metadata(), 'scope': SCOPE}
    report = {**metadata, 'complete': False, 'status': 'running', 'output': str(output),
              'sqlite': {'temp_store': 'FILE', 'schema_cache_target_kib': 8192,
                         'total_schema_cache_target_kib': 5 * 8192, 'source_databases_read_only': True,
                         'cache_targets_are_not_a_process_rss_limit': True}}
    save_json(summary, report)
    db = None
    try:
        with phase_progress('open-source-databases', started):
            db = sqlite3.connect(scratch)
            db.execute('PRAGMA temp_store=FILE')
            for name, path in databases.items():
                db.execute('ATTACH DATABASE ? AS ' + name, (path.resolve().as_uri() + '?mode=ro',))
            for schema in ('main', 'temp', 'analysis', 'grh', 'gsim'):
                db.execute('PRAGMA ' + schema + '.cache_size=-8192')
                db.execute('PRAGMA ' + schema + '.mmap_size=0')
        with phase_progress('construct-common', started) as phase:
            db.executescript('''CREATE TEMP TABLE common(path TEXT PRIMARY KEY,grh_id INTEGER,gsim_id INTEGER) WITHOUT ROWID;
                INSERT INTO common SELECT g.path,g.node_id,s.node_id FROM analysis.after_grh_names g
                    JOIN analysis.after_gsim_names s USING(path) WHERE g.occurrences=1 AND s.occurrences=1;
                CREATE UNIQUE INDEX common_grh ON common(grh_id);
                CREATE UNIQUE INDEX common_gsim ON common(gsim_id);''')
            common = db.execute('SELECT COUNT(*) FROM common').fetchone()[0]
            if common != source_report['public_comparison']['unique_name_candidates_after']:
                raise ValueError('common Node candidates differ from completed public comparison')
            phase['nodes'] = common
        raw = {}
        for engine in ('grh', 'gsim'):
            with phase_progress('build-connections', started, engine=engine) as phase:
                raw[engine] = build_connections(db, engine)
                phase['raw_connections'] = sum(row[2] for row in raw[engine])
        with phase_progress('partition-crosscheck', started) as phase:
            for own, peer in (('grh', 'gsim'), ('gsim', 'grh')):
                db.execute(f'''CREATE TEMP TABLE {own}_only AS SELECT * FROM {own}_edges e
                    WHERE NOT EXISTS(SELECT 1 FROM {peer}_edges p
                        WHERE p.source=e.source AND p.target=e.target AND p.kind=e.kind)''')
            per_kind, totals = summarize(db, raw)
            check = {'unique_name_candidates_after': common, 'matched_resolved_after': totals.get('matched_distinct', 0)}
            for engine in ('grh', 'gsim'):
                for field, suffix in (('connections', '_raw_connections'), ('resolved', '_raw_resolved'),
                                      ('unresolved', '_raw_unresolved'),
                                      ('comparable_resolved', '_comparable_resolved_distinct')):
                    check[engine + '_' + field + '_after'] = totals.get(engine + suffix, 0)
            expected = source_report['public_comparison']
            if any(expected[key] != value for key, value in check.items()):
                raise ValueError('connection counts differ from completed public comparison: ' +
                                 json.dumps({key: [expected[key], value] for key, value in check.items()
                                             if expected[key] != value}))
            report.update(public_comparison_crosscheck={'exact': True, 'counts': check},
                          totals=totals, per_kind=per_kind)
            phase.update(totals)
        pending = []
        for engine in ('grh', 'gsim'):
            with phase_progress('export-edges', started, engine=engine) as phase:
                path = output / (engine + '-only.connections.tsv')
                query = f'''SELECT src.path,dst.path,e.kind,src.grh_id,dst.grh_id,src.gsim_id,dst.gsim_id
                    FROM {engine}_only e JOIN common src ON src.grh_id=e.source
                    JOIN common dst ON dst.grh_id=e.target ORDER BY src.path,dst.path,e.kind'''
                temporary, count = write_tsv(path, EDGE_COLUMNS, db.execute(query), {**metadata, 'engine': engine})
                if count != totals.get(engine + '_only_distinct', 0):
                    raise ValueError('connection difference TSV count mismatch')
                pending.append((temporary, path))
                phase['rows'] = count
        report['unresolved_diagnostics'] = {
            'scope': 'all unresolved native connections; excluded from resolved connection differences',
            'grouping': ['kind', 'reason', 'candidate_source_count'],
            'sample_limits': {'connections_per_group': 3, 'candidate_nodes_per_connection': 16},
            'samples_are_not_population_counts': True}
        for engine in ('grh', 'gsim'):
            with phase_progress('summarize-unresolved', started, engine=engine) as phase:
                report['unresolved_diagnostics'][engine] = summarize_unresolved(
                    db, engine, totals[engine + '_raw_unresolved'])
                phase['connections'] = report['unresolved_diagnostics'][engine]['total']
                phase['groups'] = len(report['unresolved_diagnostics'][engine]['groups'])
        with phase_progress('export-affected', started) as phase:
            db.executescript('''CREATE TEMP TABLE incidents AS
            SELECT source AS node,1 AS grh_out,0 AS grh_in,0 AS gsim_out,0 AS gsim_in FROM grh_only UNION ALL
            SELECT target,0,1,0,0 FROM grh_only UNION ALL
            SELECT source,0,0,1,0 FROM gsim_only UNION ALL
            SELECT target,0,0,0,1 FROM gsim_only;
            CREATE TEMP TABLE affected AS SELECT node,SUM(grh_out) AS grh_out,SUM(grh_in) AS grh_in,
                SUM(gsim_out) AS gsim_out,SUM(gsim_in) AS gsim_in,COUNT(*) AS incidents
                FROM incidents GROUP BY node;
            CREATE UNIQUE INDEX affected_node ON affected(node);''')
            node_query = '''SELECT c.path,c.grh_id,c.gsim_id,a.grh_out,a.grh_in,a.gsim_out,a.gsim_in,a.incidents
                FROM affected a JOIN common c ON c.grh_id=a.node'''
            report['affected_nodes'] = {'total': db.execute('SELECT COUNT(*) FROM affected').fetchone()[0],
                'grh_only': db.execute('SELECT COUNT(*) FROM affected WHERE grh_out+grh_in>0').fetchone()[0],
                'gsim_only': db.execute('SELECT COUNT(*) FROM affected WHERE gsim_out+gsim_in>0').fetchone()[0],
                'top_cases': [dict(zip(NODE_COLUMNS, row)) for row in db.execute(
                    node_query + ' ORDER BY a.incidents DESC,c.path LIMIT ?', (top_count,))]}
            path = output / 'affected-nodes.tsv'
            temporary, count = write_tsv(path, NODE_COLUMNS, db.execute(node_query + ' ORDER BY c.path'), metadata)
            if count != report['affected_nodes']['total']:
                raise ValueError('affected Node TSV count mismatch')
            pending.append((temporary, path))
            phase['nodes'] = count
        with phase_progress('publish', started):
            if report_path.read_bytes() != report_bytes or any(closed_database_identity(path) != identities[name]
                                                             for name, path in databases.items()):
                raise ValueError('source report or database changed during connection export')
            for temporary, path in pending:
                temporary.replace(path)
            report.update(complete=True, status='passed', wall_s=time.monotonic() - started,
                          maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          files={filename: str(output / filename) for filename in filenames})
            save_json(summary, report)
        return report
    except BaseException as error:
        report.update(complete=False, status='failed', error=repr(error), wall_s=time.monotonic() - started)
        save_json(summary, report)
        raise
    finally:
        if db is not None:
            db.close()
        scratch.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--top-count', type=int, default=20)
    args = parser.parse_args()
    report = export(args.analysis, args.output, args.top_count)
    print(json.dumps({'complete': report['complete'], 'totals': report['totals'],
                      'affected_nodes': report['affected_nodes']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
