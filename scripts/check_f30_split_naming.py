"""Check F30 split naming inventories without replaying connections or journals.

Sorted native Node IDs permit streaming before/after checks. SQLite stores only
after-stage names; generated IDs shared by two runs are never treated as proof
of semantic identity. Only the five known GSIM child origins are decoded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
from typing import NamedTuple

from compare_f29_node_names import bundle_identity, input_digest
from export_f29_full_split_exchange import last_line, name_comparison_metadata
from export_f30_connection_differences import file_identity, phase_progress, save_json
from semantic_node_exchange import HEADERS, IDENTITY, decode_cell, encode_cell, integer, parsed_row
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.split-naming-check.v1'
FILES = ('before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
         'after.nodes.tsv', 'after.connections.tsv')
KNOWN_CASES = tuple(dict(zip(('grh_original', 'gsim_original', 'gsim_child', 'gsim_parent', 'coordinates'), row))
    for row in ((5581354, 5562182, 9356717, 5560441, [3]),
                (6834382, 6911217, 9794356, 6911214, [1]),
                (6892434, 6971257, 9804561, 6971254, [1]),
                (6950486, 7031297, 9814766, 7031294, [1]),
                (7008538, 7091337, 9824971, 7091334, [1])))
CHANGE_COLUMNS = ('engine', 'change_kind', 'node_id', 'baseline_path', 'current_path',
                  'baseline_native_name', 'current_native_name', 'identity_scope')
DUPLICATE_COLUMNS = ('version', 'engine', 'name_kind', 'name', 'nodes', 'minimum_node_id', 'maximum_node_id')
CHILD_ID = re.compile(r'"to_node_id"\s*:\s*([0-9]+)')


class Node(NamedTuple):
    id: int
    path: str | None
    tokens: tuple | None
    native_name: str


def bundle(path, engine):
    identity = bundle_identity(Path(path).resolve(), engine)
    directory = Path(identity['directory'])
    footer_row = parsed_row(last_line(directory / 'evolution.tsv'), HEADERS['evolution'])
    footer = json.loads(footer_row['detail_json'])
    if (footer_row['record'] != 'footer' or footer.get('complete') is not True or
            footer.get('replayComplete') is not True):
        raise ValueError('native journal lacks a complete producer footer: ' + str(directory))
    identity['footer'] = footer
    for name in FILES:
        if not (directory / name).is_file():
            raise ValueError('missing native bundle file: ' + str(directory / name))
    return identity


def snapshot_rows(identity, phase):
    """Read one native inventory exactly once; completion is checked on exhaustion."""
    source = Path(identity['directory']) / (phase + '.nodes.tsv')
    header = identity['header']
    with source.open(encoding='utf-8', newline='') as stream:
        first = stream.readline()
        if not first.startswith('#meta\t') or not first.endswith('\n'):
            raise ValueError('missing native Node metadata: ' + str(source))
        metadata = json.loads(first[6:])
        digest = input_digest(metadata, source, required=False)
        if (any(metadata.get(key) != header.get(key) for key in IDENTITY) or
                metadata.get('table') != 'nodes' or not metadata.get('stage') or
                metadata.get('snapshot_id') != header[phase + '_snapshot_id'] or
                (metadata.get('root_name') is not None and metadata['root_name'] != header['root_name']) or
                (digest is not None and digest != identity['input_sha256']) or
                stream.readline() != '\t'.join(HEADERS['nodes']) + '\n'):
            raise ValueError('Node inventory differs from its native header: ' + str(source))
        previous, count, footer = -1, 0, None
        for line in stream:
            if footer is not None or not line.endswith('\n') or line.endswith('\r\n'):
                raise ValueError('incomplete or trailing Node inventory data: ' + str(source))
            if line.startswith('#footer\t'):
                footer = json.loads(line[8:])
                continue
            fields = line[:-1].split('\t')
            if len(fields) != 3:
                raise ValueError('invalid Node inventory columns')
            identifier = integer(fields[0])
            if identifier <= previous:
                raise ValueError('Node inventory IDs are not uniquely sorted')
            path_json, native_name = (decode_cell(value) if '\\' in value else value for value in fields[1:])
            if native_name is None:
                raise ValueError('missing native Node name')
            tokens = None if path_json is None else json.loads(path_json)
            if tokens is not None and (not isinstance(tokens, list) or not tokens or
                    any(not isinstance(value, str) or not value for value in tokens)):
                raise ValueError('invalid native public path')
            previous, count = identifier, count + 1
            yield Node(identifier, None if tokens is None else '.'.join(tokens),
                       None if tokens is None else tuple(tokens), native_name)
        expected = identity['footer'][phase + 'NodeCount']
        if (not footer or footer.get('complete') is not True or footer.get('nodeInventoryComplete') is not True or
                footer.get('rowCount') != count or count != expected):
            raise ValueError('incomplete Node inventory footer/count: ' + str(source))


def different(left, right):
    return left is not None and right is not None and (left.tokens != right.tokens or left.native_name != right.native_name)


def row(stream, values):
    stream.write('\t'.join(encode_cell(value) for value in values) + '\n')


def merge_engine(db, engine, old, new, changes, selected_ids):
    started = time.monotonic()
    for version in ('baseline', 'current'):
        native = ',native_name TEXT NOT NULL' if version == 'current' else ''
        db.execute(f'CREATE TABLE {version}_{engine}(id INTEGER PRIMARY KEY,path TEXT{native})')
    sources = {'old_before': snapshot_rows(old, 'before'), 'new_before': snapshot_rows(new, 'before'),
               'old_after': snapshot_rows(old, 'after'), 'new_after': snapshot_rows(new, 'after')}
    heads = {key: next(iterator, None) for key, iterator in sources.items()}
    counts, selected = Counter(), {key: {} for key in sources}
    batches = {'baseline': [], 'current': []}

    def change(kind, identifier, left, right, scope):
        row(changes, (engine, kind, identifier, None if left is None else left.path,
            None if right is None else right.path, None if left is None else left.native_name,
            None if right is None else right.native_name, scope))
        counts['change_rows'] += 1

    def flush(version):
        columns = '?,?,?' if version == 'current' else '?,?'
        db.executemany(f'INSERT INTO {version}_{engine} VALUES({columns})', batches[version])
        batches[version].clear()

    db.execute('BEGIN')
    while any(value is not None for value in heads.values()):
        identifier = min(value.id for value in heads.values() if value is not None)
        current = {key: value if value is not None and value.id == identifier else None for key, value in heads.items()}
        ob, nb, oa, na = (current[key] for key in ('old_before', 'new_before', 'old_after', 'new_after'))
        for key, value in current.items():
            if value is not None:
                counts[key + '_nodes'] += 1
                if identifier in selected_ids:
                    selected[key][identifier] = value
        if (ob is None) != (nb is None):
            counts['before_id_differences'] += 1
            change('baseline_before_id_difference', identifier, ob, nb, 'original-input-identity')
        elif different(ob, nb):
            counts['before_name_differences'] += 1
            change('baseline_before_name_difference', identifier, ob, nb, 'original-input-identity')
        if nb is not None and na is not None:
            counts['original_survivors'] += 1
            if different(nb, na):
                counts['original_renamed'] += 1
                change('current_surviving_original_renamed', identifier, nb, na, 'stable-original-id')
        if oa is not None and na is not None:
            counts['after_common_ids'] += 1
            if different(oa, na):
                counts['after_name_differences'] += 1
                change('baseline_after_name_difference', identifier, oa, na,
                       'stable-original-id' if nb is not None and ob is not None else 'generated-id-coincidence-only')
        elif oa is not None or na is not None:
            counts['after_added' if oa is None else 'after_removed'] += 1
            change('baseline_after_id_added' if oa is None else 'baseline_after_id_removed', identifier, oa, na,
                   'ID-set-diagnostic-only; generated IDs do not establish semantic identity')
        if oa is not None:
            batches['baseline'].append((oa.id, oa.path))
        if na is not None:
            batches['current'].append((na.id, na.path, na.native_name))
            if counts['new_after_nodes'] % 1000000 == 0:
                print(json.dumps({'event': 'inventory-progress', 'engine': engine,
                    'current_after_nodes': counts['new_after_nodes'],
                    'baseline_after_nodes': counts['old_after_nodes'],
                    'phase_wall_s': time.monotonic() - started}), flush=True)
        for version in batches:
            if len(batches[version]) >= 4096:
                flush(version)
        for key, value in current.items():
            if value is not None:
                heads[key] = next(sources[key], None)
    for version in batches:
        flush(version)
    db.commit()
    for version in batches:
        db.execute(f'CREATE INDEX {version}_{engine}_path ON {version}_{engine}(path)')
    db.execute(f'CREATE INDEX current_{engine}_native ON current_{engine}(native_name)')
    db.commit()
    return counts, selected


def name_counts(db, version, inventories, duplicates):
    # Both GROUP BY streams use the path indexes. Merge their sorted unique
    # groups without materializing another pair of tables of long paths.
    cursors = {engine: iter(db.execute(f'''SELECT path,COUNT(*),MIN(id),MAX(id) FROM {version}_{engine}
        WHERE path IS NOT NULL GROUP BY path ORDER BY path''')) for engine in ('grh', 'gsim')}
    heads = {engine: next(cursor, None) for engine, cursor in cursors.items()}
    ambiguous, matches, duplicate_rows = Counter(), 0, 0
    while any(value is not None for value in heads.values()):
        path = min(value[0] for value in heads.values() if value is not None)
        equal = {engine: value for engine, value in heads.items() if value is not None and value[0] == path}
        if len(equal) == 2 and all(value[1] == 1 for value in equal.values()):
            matches += 1
        for engine, value in equal.items():
            if value[1] > 1:
                ambiguous[engine] += value[1]
                row(duplicates, (version, engine, 'public_path', *value))
                duplicate_rows += 1
            heads[engine] = next(cursors[engine], None)
    counts = {'unique_name_candidates': matches, 'ambiguous_public_nodes': dict(ambiguous)}
    for engine in ('grh', 'gsim'):
        nodes = inventories[engine]['old_after_nodes' if version == 'baseline' else 'new_after_nodes']
        counts[engine + '_nodes'] = nodes
        counts[engine + '_candidate_ratio'] = matches / nodes if nodes else None
    return counts, duplicate_rows


def known_origins(identity, cases):
    wanted = {case['gsim_child'] for case in cases}
    origins = {identifier: [] for identifier in wanted}
    if not wanted:
        return origins
    with (Path(identity['directory']) / 'evolution.tsv').open(encoding='utf-8', newline='') as stream:
        for line in stream:
            if not line.startswith('lineage\t'):
                continue
            fields = line.rstrip('\n').split('\t', 8)
            if len(fields) != 9:
                raise ValueError('malformed native lineage row')
            # Producer emits this key literally; do not JSON-decode millions
            # of unrelated edit/lineage payloads to inspect five children.
            match = CHILD_ID.search(fields[8])
            if match is None:
                raise ValueError('unsupported native lineage child field')
            child = int(match[1])
            if child in wanted and len(origins[child]) < 2:
                detail = json.loads(decode_cell(fields[8]))
                origins[child].append({'parent': integer(fields[7]), 'child': child,
                    'relation': detail.get('relation'), 'coordinates': detail.get('coordinates')})
    return origins


def check_known(db, selected, origins, cases):
    results = []
    for case in cases:
        g, s = selected['grh'], selected['gsim']
        gi, si, ci, pi = (case[key] for key in ('grh_original', 'gsim_original', 'gsim_child', 'gsim_parent'))
        required = ((g, 'new_before', gi), (g, 'new_after', gi), (g, 'old_after', gi),
                    (s, 'new_before', si), (s, 'new_before', pi), (s, 'new_after', si),
                    (s, 'new_after', ci), (s, 'old_after', si), (s, 'old_after', ci))
        item = {**case, 'passed': False, 'native_origins': origins.get(ci, []), 'native_origin_sample_limit': 2}
        if any(identifier not in rows[phase] for rows, phase, identifier in required):
            item['reason'] = 'A required stable original, parent, or known child ID is absent.'
        else:
            grh, gsim, child = g['new_after'][gi], s['new_after'][si], s['new_after'][ci]
            item.update(current_grh_path=grh.path, current_gsim_original_path=gsim.path,
                current_gsim_child_path=child.path, parent_before_path=s['new_before'][pi].path,
                baseline_grh_path=g['old_after'][gi].path,
                baseline_gsim_original_path=s['old_after'][si].path,
                baseline_gsim_child_path=s['old_after'][ci].path)
            unique = all(db.execute(f'SELECT COUNT(*) FROM current_{engine} WHERE path=?', (node.path,)).fetchone()[0] == 1
                         for engine, node in (('grh', grh), ('gsim', gsim), ('gsim', child)))
            expected_origin = [{'parent': pi, 'child': ci, 'relation': 'split', 'coordinates': case['coordinates']}]
            item['passed'] = bool(grh.path is not None and grh.path == gsim.path and child.path != grh.path and
                grh.tokens == g['new_before'][gi].tokens and gsim.tokens == s['new_before'][si].tokens and
                g['new_before'][gi].path == s['new_before'][si].path and unique and origins.get(ci) == expected_origin and
                g['old_after'][gi].path == s['old_after'][ci].path and
                g['old_after'][gi].path != s['old_after'][si].path)
            if not item['passed']:
                item['reason'] = 'Known baseline collision, corrected unique original pair, or exact native child origin did not verify.'
        results.append(item)
    return results


def check(grh_bundle, gsim_bundle, baseline_grh_bundle, baseline_gsim_bundle, output, *, known_cases=KNOWN_CASES):
    started = time.monotonic()
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    paths = {'grh': grh_bundle, 'gsim': gsim_bundle,
             'baseline_grh': baseline_grh_bundle, 'baseline_gsim': baseline_gsim_bundle}
    with phase_progress('verify-naming-sources', started):
        evidence = {label: bundle(path, label.split('_')[-1]) for label, path in paths.items()}
        if len({(value['input_sha256'], value['header']['root_name']) for value in evidence.values()}) != 1:
            raise ValueError('naming sources have different input/root identity')
        for engine in ('grh', 'gsim'):
            if evidence[engine]['header']['pass'] != evidence['baseline_' + engine]['header']['pass']:
                raise ValueError('baseline/current native pass scopes differ')
        watched = {str(Path(value['directory']) / name): file_identity(Path(value['directory']) / name)
                   for value in evidence.values() for name in FILES}
    output.mkdir(parents=True, exist_ok=True)
    summary, scratch = output / 'summary.json', output / 'names.sqlite'
    names = ('node-name-changes.tsv', 'duplicate-names.tsv')
    if summary.exists() or scratch.exists() or any((output / name).exists() or
            (output / name).with_suffix('.pending').exists() for name in names):
        raise ValueError('refusing to overwrite naming evidence')
    metadata = {'schema': SCHEMA, 'input_sha256': evidence['grh']['input_sha256'],
        'root_name': evidence['grh']['header']['root_name'], 'source_files': watched,
        'native_headers': {key: value['header'] for key, value in evidence.items()},
        'name_comparison': name_comparison_metadata(),
        'scope': 'Node naming inventories and selected native origins only; journals/connections are not replayed; no functional equivalence claim',
        'generated_id_scope': 'Old/new after generated IDs are count/set/name diagnostics only and do not establish semantic identity.',
        'source_binding': 'native input/root headers, complete producer/snapshot footers and unchanged source stat identities; source bytes not rehashed'}
    report = {**metadata, 'complete': False, 'passed': False, 'status': 'running', 'issues': [],
        'sqlite': {'temp_store': 'FILE', 'cache_targets_kib': {'main': 32768, 'temp': 16384},
                   'cache_targets_are_not_rss_limit': True, 'scratch_retained': False}}
    save_json(summary, report)
    db = None
    pending = {name: (output / name).with_suffix('.pending') for name in names}
    try:
        db = sqlite3.connect(scratch)
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA main.cache_size=-32768')
        db.execute('PRAGMA temp.cache_size=-16384')
        db.execute('PRAGMA mmap_size=0')
        inventories, selected = {}, {}
        with pending[names[0]].open('x', encoding='utf-8', newline='') as changes, \
                pending[names[1]].open('x', encoding='utf-8', newline='') as duplicates:
            for stream, columns in ((changes, CHANGE_COLUMNS), (duplicates, DUPLICATE_COLUMNS)):
                stream.write('#meta\t' + json.dumps(metadata, separators=(',', ':')) + '\n')
                row(stream, columns)
            for engine in ('grh', 'gsim'):
                wanted = {case['grh_original'] for case in known_cases} if engine == 'grh' else {
                    case[key] for case in known_cases for key in ('gsim_original', 'gsim_parent', 'gsim_child')}
                with phase_progress('merge-node-inventories', started, engine=engine) as phase:
                    inventories[engine], selected[engine] = merge_engine(db, engine,
                        evidence['baseline_' + engine], evidence[engine], changes, wanted)
                    phase.update(inventories[engine])
            report['preservation'] = {engine: {key: inventories[engine][key] for key in
                ('before_id_differences', 'before_name_differences', 'original_survivors', 'original_renamed')}
                for engine in ('grh', 'gsim')}
            report['after_id_sets'] = {engine: {'added': inventories[engine]['after_added'],
                'removed': inventories[engine]['after_removed'], 'common': inventories[engine]['after_common_ids'],
                'name_differences': inventories[engine]['after_name_differences'],
                'generated_id_comparison_scope': metadata['generated_id_scope']} for engine in ('grh', 'gsim')}
            duplicate_count = 0
            report['name_candidates'] = {}
            for version in ('baseline', 'current'):
                with phase_progress('count-unique-public-name-candidates', started, version=version) as phase:
                    counts, written = name_counts(db, version, inventories, duplicates)
                    report['name_candidates'][version] = counts
                    duplicate_count += written
                    phase.update(counts)
            report['name_candidates']['delta'] = (report['name_candidates']['current']['unique_name_candidates'] -
                                                  report['name_candidates']['baseline']['unique_name_candidates'])
            native_duplicates = Counter()
            with phase_progress('check-current-native-name-duplicates', started):
                for engine in ('grh', 'gsim'):
                    for values in db.execute(f'''SELECT native_name,COUNT(*),MIN(id),MAX(id) FROM current_{engine}
                            GROUP BY native_name HAVING COUNT(*)>1'''):
                        row(duplicates, ('current', engine, 'native_name', *values))
                        native_duplicates[engine] += values[1]
                        duplicate_count += 1
            report['current_native_duplicate_nodes'] = dict(native_duplicates)
            for engine, counts in inventories.items():
                for key in ('before_id_differences', 'before_name_differences', 'original_renamed'):
                    if counts[key]:
                        report['issues'].append({'code': key, 'engine': engine, 'nodes': counts[key]})
                if engine == 'gsim' and (counts['after_added'] or counts['after_removed']):
                    report['issues'].append({'code': 'gsim_after_id_set_changed',
                                            'added': counts['after_added'], 'removed': counts['after_removed']})
                if report['name_candidates']['current']['ambiguous_public_nodes'].get(engine, 0):
                    report['issues'].append({'code': 'duplicate_public_path', 'engine': engine})
                if native_duplicates[engine]:
                    report['issues'].append({'code': 'duplicate_native_name', 'engine': engine})
            with phase_progress('verify-known-native-origins', started):
                report['known_cases'] = check_known(db, selected, known_origins(evidence['gsim'], known_cases), known_cases)
                report['issues'].extend({'code': 'known_collision_not_corrected', **item}
                                        for item in report['known_cases'] if not item['passed'])
            changes.write('#footer\t' + json.dumps({'complete': True,
                'rowCount': sum(counts['change_rows'] for counts in inventories.values())}) + '\n')
            duplicates.write('#footer\t' + json.dumps({'complete': True, 'rowCount': duplicate_count}) + '\n')
        with phase_progress('publish-naming-report', started):
            if any(file_identity(Path(path)) != expected for path, expected in watched.items()):
                raise ValueError('source inventory changed during naming validation')
            for name, temporary in pending.items():
                temporary.replace(output / name)
            report.update(complete=True, passed=not report['issues'],
                status='failed' if report['issues'] else 'passed', wall_s=time.monotonic() - started,
                files={name: str(output / name) for name in names})
            save_json(summary, report)
        return report
    except BaseException as error:
        report.update(complete=False, passed=False, status='failed', error=repr(error), wall_s=time.monotonic() - started)
        save_json(summary, report)
        raise
    finally:
        if db is not None:
            db.close()
        scratch.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh-bundle', 'gsim-bundle', 'baseline-grh-bundle', 'baseline-gsim-bundle', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = check(args.grh_bundle, args.gsim_bundle, args.baseline_grh_bundle, args.baseline_gsim_bundle, args.output)
    print(json.dumps({'complete': report['complete'], 'passed': report['passed'],
                      'name_candidates': report['name_candidates'], 'issues': report['issues']}, ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
