"""Audit bounded, closed F32 comparison inventories; origin is never a semantic proof."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f32.window-origin-audit.v1'
MAX_LINEAGE_DEPTH = 64
TABLES = {
    'inventory': ('engine', 'stage', 'id', 'name', 'path', 'native'),
    'slices': ('engine', 'stage', 'parent', 'child', 'low', 'width'),
    'endpoints': ('stage', 'node', 'ordinal', 'value', 'role', 'type_key', 'domain', 'evidence', 'payload'),
    'details': ('stage', 'node', 'type_key', 'kind', 'clock', 'pair', 'payload'),
    'pairs': ('stage', 'grh', 'gsim', 'name'),
    'differences': ('stage', 'category', 'key', 'engine', 'grh', 'gsim', 'reason', 'evidence'),
}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def integer(value, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid native integer')
    return value


def physical_type(value):
    try:
        width, signed, shape = json.loads(value)
        integer(width)
        if type(signed) is not bool or not isinstance(shape, list):
            return None
        for extent in shape:
            integer(extent)
        return {'leaf_width': width, 'signed': signed, 'shape': shape}
    except (TypeError, ValueError):
        return None


def native_binding_geometry_checked(row):
    """Check recorded v2 geometry without promoting an anchor candidate."""
    if row['evidence'] != 'native-binding' or row['domain'] not in ('2state', '4state'):
        return False
    try:
        payload = json.loads(row['payload'])
        if not isinstance(payload, dict):
            return False
        if (payload.get('source_signed') not in ('true', 'false', '1', '0') or
                payload.get('logic_domain') != row['domain']):
            return False
        if payload.get('source_geometry_schema') != 'grh.semantic-node-endpoints.v2':
            return False
        if payload.get('source_geometry_complete') is not True:
            return False
        values = []
        for key in ('source_width', 'source_bit_offset', 'source_bit_width'):
            text = payload[key]
            if not isinstance(text, str) or not re.fullmatch(r'-?(0|[1-9][0-9]*)', text):
                return False
            values.append(int(text))
        width, low, retained = values
        shape = json.loads(payload['source_shape_json'])
        projection = json.loads(payload['projection_json'])
        depths = json.loads(payload['source_shape_field_depths_json'])
        if (width < 0 or low < 0 or retained < -1 or
                (retained == -1 and low != 0) or (retained >= 0 and low + retained > width)):
            return False
        if not all(isinstance(item, list) for item in (shape, projection, depths)):
            return False
        if any(type(item) is not int or item < 0 for item in shape + depths):
            return False
        if ((projection and len(projection) != len(shape)) or
                any(type(item) is not int or item < -1 or item >= extent
                    for item, extent in zip(projection, shape)) or
                (depths and len(depths) != len(shape)) or depths != sorted(depths)):
            return False
        typ = physical_type(row['type_key'])
        remaining_shape = [extent for index, extent in enumerate(shape)
                           if not projection or projection[index] == -1]
        return (integer(row['value']) > 0 and typ is not None and
                typ['leaf_width'] == (width if retained == -1 else retained) and
                typ['shape'] == remaining_shape)
    except (KeyError, TypeError, ValueError):
        return False


def closed_stamp(path, maximum):
    if path.is_symlink() or not path.is_file():
        raise ValueError('input must be a regular closed database')
    # A finished summary alone does not make a resumed writer safe to inspect.
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('database has active or uncheckpointed SQLite sidecars')
    info = path.stat()
    if info.st_size > maximum:
        raise ValueError('database exceeds bounded audit byte limit')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def read_inputs(comparison, max_rows, max_bytes):
    if max_rows < 1 or max_bytes < 1:
        raise ValueError('audit bounds must be positive')
    summary_path, path = comparison / 'summary.json', comparison / 'comparison.sqlite'
    if summary_path.stat().st_size > 4 * 1024**2:
        raise ValueError('comparison summary exceeds bounded audit byte limit')
    summary_bytes = summary_path.read_bytes()
    summary = json.loads(summary_bytes)
    if (summary.get('schema') != 'wolvrix.f32.semantic-comparison.v1' or
            summary.get('status') != 'analyzed' or summary.get('complete') is not True):
        raise ValueError('audit requires a completed comparison; running indexes are not inputs')
    if not isinstance(summary.get('input_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', summary['input_sha256']):
        raise ValueError('missing original FIRRTL identity')
    for engine in ('grh', 'gsim'):
        snapshots = summary.get('snapshots', {}).get(engine, {})
        if set(snapshots) != {f'P{i}' for i in range(5)}:
            raise ValueError('audit requires five native boundaries per engine')
        runs, ids = set(), set()
        for snapshot in snapshots.values():
            for key in ('run_id', 'snapshot_id'):
                if not isinstance(snapshot.get(key), str) or not snapshot[key]:
                    raise ValueError('missing native run/snapshot identity')
            runs.add(snapshot['run_id'])
            ids.add(snapshot['snapshot_id'])
            integer(snapshot.get('nodes'))
        if len(runs) != 1 or len(ids) != 5:
            raise ValueError('five native boundaries must share one run and distinct snapshots')
    before = closed_stamp(path, max_bytes)
    frozen_hash = digest(path)
    def records(db, table, columns):
        with closing(db.execute('SELECT rowid,' + ','.join(columns) + ' FROM ' + table)) as cursor:
            for row in cursor:
                yield dict(zip(('rowid', *columns), row))

    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        for table, columns in TABLES.items():
            actual = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
            if not set(columns) <= actual:
                raise ValueError('unsupported comparison table schema: ' + table)
            if db.execute('SELECT count(*) FROM ' + table).fetchone()[0] > max_rows:
                raise ValueError('table exceeds bounded audit row limit: ' + table)
        tables = {table: records(db, table, columns) for table, columns in TABLES.items()}
        try:
            yield summary, tables, {
                'database': str(path), 'sha256': frozen_hash, 'bytes': before[2],
                'summary': str(summary_path), 'summary_sha256': hashlib.sha256(summary_bytes).hexdigest()}
        finally:
            for rows in tables.values():
                rows.close()
    if (closed_stamp(path, max_bytes) != before or digest(path) != frozen_hash or
            summary_path.read_bytes() != summary_bytes):
        raise ValueError('comparison changed while the closed audit was reading it')


def analyze(summary, tables):
    nodes, endpoint_rows, detail_rows = {}, defaultdict(list), {}
    occurrences, inventory_counts = defaultdict(set), Counter()
    for row in tables['inventory']:
        engine, stage, identifier = row['engine'], integer(row['stage']), integer(row['id'])
        if engine not in ('grh', 'gsim') or stage > 4:
            raise ValueError('invalid native inventory namespace')
        key = (engine, stage, identifier)
        if key in nodes:
            raise ValueError('duplicate native inventory identity')
        try:
            path = json.loads(row['path'])
        except (TypeError, ValueError):
            path = None
        named = (isinstance(path, list) and bool(path) and
                 all(isinstance(part, str) and bool(part) for part in path) and
                 isinstance(row['name'], str) and row['name'] == '.'.join(path) and
                 isinstance(row['native'], str) and bool(row['native']))
        nodes[key] = {**row, 'token_path': path, 'name_path_valid': named}
        occurrences[engine, identifier].add(stage)
        inventory_counts[engine, stage] += 1
    for engine in ('grh', 'gsim'):
        for stage in range(5):
            expected = summary['snapshots'][engine][f'P{stage}']['nodes']
            if inventory_counts[engine, stage] != expected:
                raise ValueError('inventory count differs from completed comparison')
    for row in tables['endpoints']:
        key = ('grh', integer(row['stage']), integer(row['node']))
        if key not in nodes:
            raise ValueError('endpoint outside native inventory')
        endpoint_rows[key].append(row)
    for row in tables['details']:
        key = ('gsim', integer(row['stage']), integer(row['node']))
        if key not in nodes or key in detail_rows:
            raise ValueError('invalid native detail identity')
        detail_rows[key] = row

    geometries = {}

    def geometry(key):
        if key in geometries:
            return geometries[key]
        if key[0] == 'grh':
            rows = [row for row in endpoint_rows[key] if type(row['value']) is int and
                    row['value'] > 0 and row['evidence'] != 'operation-only']
        else:
            rows = [detail_rows[key]] if key in detail_rows else []
        values = [physical_type(row['type_key']) for row in rows]
        geometries[key] = values[0] if values and values[0] and all(item == values[0] for item in values) else None
        return geometries[key]

    relations = defaultdict(dict)
    for row in tables['slices']:
        if row['engine'] not in ('grh', 'gsim') or integer(row['stage']) > 4:
            raise ValueError('invalid native slice namespace')
        for field in ('parent', 'child', 'low', 'width'):
            integer(row[field])
        identity = tuple(row[field] for field in ('parent', 'child', 'low', 'width'))
        prior = relations[row['engine'], row['child']].get(identity)
        if prior is None or row['stage'] < prior['stage']:
            relations[row['engine'], row['child']][identity] = row
    published_children = defaultdict(list)
    for family in relations.values():
        for row in family.values():
            published_children[row['engine'], row['stage'], row['parent']].append(row)

    origins, active = {}, set()

    def unresolved(issue):
        return {'classification': 'unresolved-origin', 'p0_node_id': None,
                'projection': None, 'issues': [issue], 'lineage': []}

    def resolve(key, depth=0):
        if key in origins:
            return origins[key]
        if key in active:
            return unresolved('cyclic-producer-lineage')
        if depth >= MAX_LINEAGE_DEPTH:
            return unresolved('producer-lineage-depth-budget-exceeded')
        active.add(key)
        engine, stage, identifier = key
        node = nodes[key]
        result = {'classification': 'unresolved-origin', 'p0_node_id': None,
                  'projection': None, 'issues': [], 'lineage': []}
        candidates = [row for row in relations[engine, identifier].values() if row['stage'] <= stage]
        previous = (engine, stage - 1, identifier)
        earlier = any(item < stage for item in occurrences[engine, identifier])
        if stage == 0:
            result.update(classification='unchanged-identity', p0_node_id=identifier)
            typ = geometry(key)
            if typ and not typ['shape']:
                result['projection'] = {'low': 0, 'width': typ['leaf_width']}
        elif previous in nodes:
            old = nodes[previous]
            parent = resolve(previous, depth + 1)
            result = {**parent, 'issues': list(parent['issues']), 'lineage': list(parent['lineage'])}
            if any(node[field] != old[field] for field in ('name', 'token_path', 'native')):
                result.update(classification='unresolved-origin', p0_node_id=None, projection=None)
                result['issues'].append('surviving-native-identity-renamed')
            old_typ, typ = geometry(previous), geometry(key)
            if old_typ != typ:
                result['projection'] = None
                result['issues'].append('identity-physical-geometry-change-needs-projection-evidence')
            if any(row['stage'] == stage for row in candidates):
                result.update(classification='unresolved-origin', p0_node_id=None, projection=None)
                result['issues'].append('late-lineage-for-existing-identity')
        elif earlier:
            result['issues'].append('retired-native-identity-reappeared')
        elif not candidates:
            result.update(classification='new')
            result['issues'].append('no-producer-lineage-to-P0')
        elif len(candidates) != 1:
            result['issues'].append('ambiguous-producer-parents-or-geometry')
        else:
            relation = candidates[0]
            parent_key = (engine, stage - 1, relation['parent'])
            if parent_key not in nodes and not any(item < stage for item in occurrences[engine, relation['parent']]):
                parent_key = (engine, stage, relation['parent'])
            typ, parent_typ = geometry(key), geometry(parent_key) if parent_key in nodes else None
            reasons = []
            if relation['stage'] != stage or stage != 3:
                reasons.append('lineage-not-recorded-at-F32-split-birth')
            if parent_key not in nodes or relation['parent'] == identifier:
                reasons.append('missing-or-self-producer-parent')
            if (not typ or not parent_typ or typ['shape'] or parent_typ['shape']):
                reasons.append('incomplete-physical-scalar-projection-geometry')
            elif (relation['width'] <= 0 or relation['low'] + relation['width'] > parent_typ['leaf_width'] or
                  relation['width'] != typ['leaf_width']):
                reasons.append('producer-projection-out-of-bounds-or-width-mismatch')
            if not reasons:
                parent = resolve(parent_key, depth + 1)
                if parent['p0_node_id'] is None or parent['projection'] is None:
                    reasons.extend(parent['issues'])
                    reasons.append('producer-parent-has-unresolved-P0-origin')
                elif len(parent['lineage']) >= MAX_LINEAGE_DEPTH:
                    reasons.append('producer-lineage-depth-budget-exceeded')
                else:
                    result.update(classification='producer-projection', p0_node_id=parent['p0_node_id'],
                        projection={'low': parent['projection']['low'] + relation['low'], 'width': relation['width']},
                        lineage=[*parent['lineage'], {'table': 'slices', 'rowid': relation['rowid'],
                            'parent_stage': parent_key[1], **{field: relation[field] for field in
                                ('engine', 'stage', 'parent', 'child', 'low', 'width')}}])
            result['issues'].extend(reasons)
        if not node['name_path_valid']:
            result.update(classification='unresolved-origin', p0_node_id=None, projection=None)
            result['issues'].append('missing-or-invalid-native-name-path')
        result['issues'] = list(dict.fromkeys(result['issues']))
        active.remove(key)
        typ = geometry(key)
        rows = endpoint_rows[key]
        bindings_checked = bool(rows) and all(native_binding_geometry_checked(row) for row in rows)
        result.update(engine=engine, stage=f'P{stage}', node_id=identifier,
            run_id=summary['snapshots'][engine][f'P{stage}']['run_id'],
            snapshot_id=summary['snapshots'][engine][f'P{stage}']['snapshot_id'],
            name=node['name'], token_path=node['token_path'], physical_geometry=typ,
            source_binding_geometry_checked=bindings_checked if engine == 'grh' else False,
            source_binding_status=('native-v2-binding-geometry-checked' if bindings_checked else 'missing-or-incomplete-binding')
                if engine == 'grh' else 'not-supplied-by-node-details-sidecar',
            semantic_preservation_proved=False,
            evidence={'inventory': {'table': 'inventory', 'rowid': node['rowid']},
                'endpoint_rows': [row['rowid'] for row in rows],
                'detail_row': detail_rows[key]['rowid'] if key in detail_rows else None})
        origins[key] = result
        return result

    for key in nodes:
        resolve(key)

    def origin_reference(row):
        return {field: row[field] for field in ('engine', 'stage', 'node_id', 'p0_node_id',
                'classification', 'projection', 'evidence')}

    def obligations():
        sequence = 0

        def obligation(kind, stage, evidence, **identities):
            nonlocal sequence
            sequence += 1
            return {'id': sequence, 'kind': kind, 'boundary': f'P{stage}',
                'status': 'unclosed', 'semantic_certificate': None, 'evidence': evidence, **identities}

        for row in origins.values():
            stage = int(row['stage'][1:])
            identity = {'engine': row['engine'], 'node_id': row['node_id'], 'p0_node_id': row['p0_node_id']}
            if stage:
                yield obligation('semantic-transformation-certificate-missing', stage, row['evidence'], **identity)
            for issue in row['issues']:
                yield obligation(issue, stage, {'lineage': row['lineage'], **row['evidence']}, **identity)
            if row['physical_geometry'] is None:
                yield obligation('physical-geometry-unproved', stage, row['evidence'], **identity)
            if row['engine'] == 'grh' and not row['source_binding_geometry_checked']:
                yield obligation('source-binding-geometry-unproved', stage, row['evidence'], **identity)
        for key in nodes:
            engine, previous_stage, identifier = key
            stage = previous_stage + 1
            if stage > 4 or (engine, stage, identifier) in nodes:
                continue
            yield obligation('retirement-semantic-certificate-missing', stage,
                {'prior_origin': origin_reference(origins[key]),
                 'published_child_projections': published_children[engine, stage, identifier]},
                engine=engine, node_id=identifier, p0_node_id=origins[key]['p0_node_id'])
        paired = set()
        for pair in tables['pairs']:
            stage = integer(pair['stage'])
            keys = [('grh', stage, integer(pair['grh'])), ('gsim', stage, integer(pair['gsim']))]
            if stage > 4 or any(key not in nodes or key in paired for key in keys):
                raise ValueError('cross-engine candidate outside inventory or reused')
            if (not isinstance(pair['name'], str) or not pair['name'] or
                    any(nodes[key]['name'] != pair['name'] for key in keys)):
                raise ValueError('cross-engine candidate is not its recorded common name')
            paired.update(keys)
            yield obligation('cross-engine-name-candidate-is-not-lineage-or-semantic-proof', stage,
                {'table': 'pairs', 'rowid': pair['rowid'],
                 'grh_origin': origin_reference(origins[keys[0]]),
                 'gsim_origin': origin_reference(origins[keys[1]])},
                grh_node_id=pair['grh'], gsim_node_id=pair['gsim'])
        for key in nodes:
            if key not in paired:
                yield obligation('cross-engine-counterpart-unproved', key[1], origins[key]['evidence'],
                    engine=key[0], node_id=key[2], p0_node_id=origins[key]['p0_node_id'])
        for difference in tables['differences']:
            stage = integer(difference['stage'])
            if stage > 4 or difference['engine'] not in ('grh', 'gsim', 'both'):
                raise ValueError('difference outside F32 boundaries or namespaces')
            for engine in ('grh', 'gsim'):
                if difference[engine] is not None:
                    integer(difference[engine])
            # Historical slice IDs can be retired, so their current presence is not required.
            # No reason/key/amount match can close an inherited or new difference.
            yield obligation('comparison-difference-needs-origin-and-semantic-review', stage,
                {'table': 'differences', **difference})
    return origins.values(), obligations()


def audit(comparison, output, *, max_rows=10000, max_bytes=64 * 1024**2):
    comparison, output = Path(comparison).resolve(), Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp') or output.exists():
        raise ValueError('audit output must be a new directory under repository ptmp/')
    origin_counts, obligation_counts = Counter(), Counter()
    with read_inputs(comparison, max_rows, max_bytes) as (summary, tables, source):
        records, obligations = analyze(summary, tables)
        output.mkdir(parents=True, exist_ok=False)
        for filename, rows, counter, field in (
                ('origins.jsonl', records, origin_counts, 'classification'),
                ('window_obligations.jsonl', obligations, obligation_counts, 'kind')):
            with (output / filename).open('x', encoding='utf-8') as stream:
                for row in rows:
                    stream.write(compact(row) + '\n')
                    counter[row[field]] += 1
    report = {'schema': SCHEMA, 'status': 'audited', 'diagnostic_only': True,
        'input': source, 'original_firrtl_sha256': summary['input_sha256'],
        'upstream_semantic_acceptance': summary.get('semantic_acceptance'),
        'upstream_gate_modified': False, 'window_acceptance': False,
        'semantic_transformation_certificates_checked': 0,
        'certificate_ingestion_implemented': False,
        'obligations_are_error_count': False,
        'obligation_interpretation': 'includes missing tool coverage; not a count of new errors or required fixes',
        'gate_reason': 'origin relations are not semantic certificates; certificate ingestion is not implemented',
        'memory_model': {'streamed': ['database rows', 'origin report', 'obligation report'],
            'resident': ['native identity indexes', 'endpoints', 'node details', 'producer relations', 'origins'],
            'production_scale_validated': False},
        'bounds': {'maximum_rows_per_table': max_rows, 'maximum_database_bytes': max_bytes,
                   'maximum_lineage_depth': MAX_LINEAGE_DEPTH},
        'origin_counts': dict(origin_counts),
        'unclosed_obligations': sum(obligation_counts.values()),
        'obligations_by_kind': dict(obligation_counts),
        'artifacts': {name: {'path': str(output / name), 'sha256': digest(output / name)}
            for name in ('origins.jsonl', 'window_obligations.jsonl')}}
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-rows', type=int, default=10000)
    parser.add_argument('--max-database-bytes', type=int, default=64 * 1024**2)
    args = parser.parse_args()
    report = audit(args.comparison, args.output, max_rows=args.max_rows, max_bytes=args.max_database_bytes)
    print(compact({key: report[key] for key in ('status', 'origin_counts', 'unclosed_obligations', 'window_acceptance')}))


if __name__ == '__main__':
    main()
