"""Prebuild or copy one unused F32 native structure index from frozen captures.

Use a new staging directory while the inventory comparison runs separately.
After completion, move that directory to comparison/structure/Pn before the
first proof resume. This helper creates no candidate pairs or proof results.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import subprocess
import textwrap

from compare_f32_semantics import (ROOT, capture, compact, digest, structure_index,
                                   write_json)

EMPTY_TABLES = ('pairs', 'native_type_evidence', 'disconnected_members')
REUSE_SCHEMA = 'wolvrix.f32.structure-index-reuse.v1'
IMPLEMENTATION_PATHS = (Path(__file__).resolve(), ROOT / 'scripts/compare_f32_semantics.py',
                        ROOT / 'scripts/compare_f28_semantic_tree.py', ROOT / 'scripts/semantic_node_exchange.py')
LOADED_IMPLEMENTATION = {str(path): digest(path) for path in IMPLEMENTATION_PATHS}


def file_stamp(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('structure reuse input must be a regular file: ' + str(path))
    info = path.stat()
    return {key: getattr(info, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def closed_index(source):
    if {path.name for path in source.iterdir()} != {'index.json', 'comparison.sqlite'}:
        raise ValueError('reuse requires a closed prebuilt stage with only database and index marker; no sidecars or proof files')
    return file_stamp(source / 'comparison.sqlite')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate structure reuse JSON key')
        result[key] = value
    return result


def small_json(path):
    before = file_stamp(path)
    if before['size'] > 4 * 1024**2:
        raise ValueError('oversized structure reuse metadata')
    raw = path.read_bytes()
    if file_stamp(path) != before:
        raise ValueError('structure reuse metadata changed while reading')
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError('structure reuse metadata must be an object')
    return value, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'stat_before': before}


def expected_schema():
    """Use only the current builder's literal schema, never supplied SQL."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(structure_index)))
    scripts = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == 'executescript' and
        isinstance(node.func.value, ast.Name) and node.func.value.id == 'db'), key=lambda node: node.lineno)
    if len(scripts) != 2 or any(len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or
                                not isinstance(node.args[0].value, str) for node in scripts):
        raise ValueError('current native structure builder no longer has the approved literal schema')
    with closing(sqlite3.connect(':memory:')) as db:
        for node in scripts:
            db.executescript(node.args[0].value)
        schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
    tables = {row[1] for row in schema if row[0] == 'table'}
    if len(tables) != 14 or not set(EMPTY_TABLES) <= tables or any(row[0] not in ('table', 'index') for row in schema):
        raise ValueError('current builder schema is outside the narrow 14-table reuse contract')
    return schema


def validate_database(path, schema):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        actual = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        if actual != schema:
            raise ValueError('structure reuse database schema differs from the current native builder')
        for name in EMPTY_TABLES:
            if db.execute('SELECT 1 FROM ' + name + ' LIMIT 1').fetchone() is not None:
                raise ValueError('structure reuse requires empty prebuilt table: ' + name)


def copy_database(source, target):
    # cp never hardlinks here. A supported filesystem can clone shared extents;
    # otherwise this explicitly authorized workflow makes an independent copy.
    subprocess.run(['cp', '--reflink=auto', '--sparse=always', '--', str(source), str(target)], check=True)


def reuse_prebuilt(grh, gsim, stage, source, output):
    """Clone only an unused native index; every comparison result is recomputed.

    This retains the historical builder's cache trust. Exact schema and empty
    derived tables do not independently rederive every cached native row.
    """
    if type(stage) is not int or stage not in (0, 1, 2):
        raise ValueError('structure reuse is limited to P0 through P2')
    implementation = {str(path): digest(path) for path in IMPLEMENTATION_PATHS}
    if implementation != LOADED_IMPLEMENTATION:
        raise ValueError('structure reuse implementation changed since module load')
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to((ROOT / 'ptmp').resolve()):
        raise ValueError('structure reuse output must be a new directory under repository ptmp')
    if not source.is_relative_to((ROOT / 'ptmp').resolve()):
        raise ValueError('structure reuse source must be a project prebuilt stage under ptmp')
    source_before = closed_index(source)
    previous, marker_record = small_json(source / 'index.json')
    if set(previous) != {'schema', 'inputs', 'counts'} or previous['schema'] != 'wolvrix.f32.structure-index.v1':
        raise ValueError('unsupported completed prebuilt structure marker')
    counts = previous['counts']
    required = {'paths', 'grh_nodes', 'grh_values', 'grh_ops', 'gsim_nodes'}
    if (not isinstance(counts, dict) or not required <= set(counts) or
            set(counts) - required - {'gsim_repeated_memory_records'} or counts['paths'] != 1 or
            any(type(value) is not int or value < 0 for value in counts.values())):
        raise ValueError('invalid prebuilt native index counts')
    old_inputs = previous['inputs']
    if not isinstance(old_inputs, list) or len(old_inputs) != 2:
        raise ValueError('prebuilt structure marker must bind two native inputs')
    metadata, inputs, native_stamps, captured = [marker_record], [], [], []
    for engine, directory, old in zip(('grh', 'gsim'), (grh, gsim), old_inputs):
        directory = Path(directory).resolve()
        _, summary_record = small_json(directory / 'summary.json')
        metadata.append(summary_record)
        current = capture(directory, engine)
        captured.append(current)
        record = current['snapshots'][f'P{stage}']
        artifact = record.get('artifacts', {}).get('structure')
        path = Path(record.get('structure') or '').resolve()
        before = file_stamp(path)
        sha = digest(path)
        if (not isinstance(artifact, dict) or Path(artifact.get('path', '')).resolve() != path or
                artifact.get('bytes') != before['size'] or artifact.get('sha256') != sha or
                not isinstance(old, dict) or set(old) != {'path', 'sha256', 'bytes'} or
                not isinstance(old.get('path'), str) or not Path(old['path']).is_absolute() or
                type(old.get('bytes')) is not int or old['bytes'] != before['size'] or old.get('sha256') != sha):
            raise ValueError('old/new frozen native structure hash/bytes mismatch')
        if file_stamp(path) != before:
            raise ValueError('native structure changed while validating reuse identity')
        inputs.append({'path': str(path), 'sha256': sha, 'bytes': before['size']})
        native_stamps.append((path, before))
    if captured[0]['input_sha256'] != captured[1]['input_sha256']:
        raise ValueError('GRH and GSIM captures have different raw FIRRTL inputs')
    schema = expected_schema()
    if closed_index(source) != source_before:
        raise ValueError('source prebuilt database changed before validation')
    validate_database(source / 'comparison.sqlite', schema)
    if closed_index(source) != source_before:
        raise ValueError('source prebuilt database changed before copy')
    source_sha = digest(source / 'comparison.sqlite')
    output.mkdir(parents=True, exist_ok=False)
    target = output / 'comparison.sqlite'
    copy_database(source / 'comparison.sqlite', target)
    target_before = file_stamp(target)
    if (target_before['dev'], target_before['ino']) == (source_before['dev'], source_before['ino']):
        raise ValueError('structure reuse must use an independent inode, never a hardlink')
    if target_before['size'] != source_before['size'] or digest(target) != source_sha:
        raise ValueError('copied structure database differs from source')
    validate_database(target, schema)
    if {path.name for path in output.iterdir()} != {'comparison.sqlite'}:
        raise ValueError('copied structure stage contains sidecars or unexpected files')
    source_after = closed_index(source)
    if source_after != source_before or digest(source / 'comparison.sqlite') != source_sha:
        raise ValueError('source prebuilt database changed during reuse')
    if file_stamp(source / 'comparison.sqlite') != source_before or file_stamp(target) != target_before:
        raise ValueError('structure database changed during final verification')
    for path, before in native_stamps:
        if file_stamp(path) != before:
            raise ValueError('native structure changed during reuse')
    for record in metadata:
        path = Path(record['path'])
        if file_stamp(path) != record['stat_before'] or digest(path) != record['sha256']:
            raise ValueError('structure reuse metadata changed during reuse')
        record['stat_after'] = file_stamp(path)
    if any(digest(Path(path)) != sha for path, sha in implementation.items()):
        raise ValueError('structure reuse implementation changed during reuse')
    marker = {'schema': 'wolvrix.f32.structure-index.v1', 'inputs': inputs, 'counts': counts}
    receipt = {'schema': REUSE_SCHEMA, 'status': 'completed', 'stage': f'P{stage}',
        'source': str(source), 'output': str(output), 'source_marker': previous, 'metadata': metadata,
        'source_database': {'sha256': source_sha, 'stat_before': source_before, 'stat_after': source_after},
        'copied_database': {'sha256': source_sha, 'stat_before': target_before, 'stat_after': file_stamp(target)},
        'implementation': implementation, 'current_builder_source_sha256': hashlib.sha256(
            inspect.getsource(structure_index).encode()).hexdigest(),
        'schema_sha256': hashlib.sha256(compact(schema).encode()).hexdigest(),
        'exact_current_builder_schema_checked': True, 'empty_tables': list(EMPTY_TABLES),
        'hardlink_used': False, 'proof_rows_reused': False, 'comparison_results_reused': False,
        'raw_rows_independently_rederived': False, 'marker_counts_independently_recounted': False,
        'cache_trust': 'historical completed native builder cache; no independent whole-cache proof',
        'builder_compatibility': 'current literal native schema; unchanged native-index builder reviewed separately; historical marker has no implementation identity'}
    # The reader recognizes only index.json. Publish this completion seal last.
    try:
        write_json(output / 'reuse.json', receipt)
        # Publication itself can take time. Recheck the closed stage and all
        # frozen file identities at the last boundary before the reader seal.
        if closed_index(source) != source_before:
            raise ValueError('source prebuilt database changed before marker publication')
        if {path.name for path in output.iterdir()} != {'comparison.sqlite', 'reuse.json'}:
            raise ValueError('copied structure stage contains sidecars or unexpected files before marker publication')
        if file_stamp(target) != target_before:
            raise ValueError('copied structure database changed before marker publication')
        for path, before in native_stamps:
            if file_stamp(path) != before:
                raise ValueError('native structure changed before marker publication')
        for record in metadata:
            if file_stamp(Path(record['path'])) != record['stat_before']:
                raise ValueError('structure reuse metadata changed before marker publication')
        if any(digest(Path(path)) != sha for path, sha in implementation.items()):
            raise ValueError('structure reuse implementation changed before marker publication')
        write_json(output / 'index.json', marker)
    except Exception:
        if (output / 'index.json').exists():
            (output / 'index.json').unlink()
        receipt['status'] = 'publication_failed'
        if (output / 'reuse.json').exists():
            write_json(output / 'reuse.json', receipt)
        raise
    return marker


def prebuild(grh, gsim, stage, output):
    if type(stage) is not int or stage not in range(5):
        raise ValueError('F32 structure stage must be P0 through P4')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('structure prebuild output must be a new directory')
    captures = [capture(Path(grh), 'grh'), capture(Path(gsim), 'gsim')]
    if captures[0]['input_sha256'] != captures[1]['input_sha256']:
        raise ValueError('GRH and GSIM captures have different raw FIRRTL inputs')
    paths, identities, stamps = [], [], []
    for captured in captures:
        record = captured['snapshots'][f'P{stage}']
        filename = record.get('structure')
        artifact = record.get('artifacts', {}).get('structure')
        if not filename or not isinstance(artifact, dict):
            raise ValueError('selected boundary lacks a frozen native structure')
        path = Path(filename).resolve()
        stat = path.stat()
        if (Path(artifact.get('path', '')).resolve() != path or
                artifact.get('bytes') != stat.st_size or
                artifact.get('sha256') != digest(path)):
            raise ValueError('native structure changed since capture')
        paths.append(path)
        identities.append({'path': str(path), 'sha256': artifact['sha256'], 'bytes': artifact['bytes']})
        stamps.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    output.mkdir(parents=True, exist_ok=False)
    local = None
    try:
        local, counts = structure_index(paths[0], paths[1], output)
        local.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;')
        # Captures are immutable. Reject changes during the separate streaming
        # hash and indexing reads before publishing a reusable completion marker.
        for path, stamp in zip(paths, stamps):
            stat = path.stat()
            if stamp != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                raise ValueError('native structure changed during prebuild')
        local.close()
        local = None
        marker = {'schema': 'wolvrix.f32.structure-index.v1', 'inputs': identities, 'counts': counts}
        write_json(output / 'index.json', marker)
        return marker
    finally:
        if local is not None:
            local.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--stage', choices=[f'P{i}' for i in range(5)], required=True)
    parser.add_argument('--output', type=Path, required=True,
                        help='new stage index directory; never an existing comparison directory')
    parser.add_argument('--reuse-from', type=Path,
                        help='closed unused P0/P1/P2 prebuilt stage; copy/reflink native rows only')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'ptmp').resolve()) or output == (ROOT / 'ptmp').resolve():
        parser.error('output must be a new stage directory under repository ptmp/')
    if args.reuse_from is not None:
        marker = reuse_prebuilt(args.grh, args.gsim, int(args.stage[1:]), args.reuse_from, output)
    else:
        marker = prebuild(args.grh.resolve(), args.gsim.resolve(), int(args.stage[1:]), output)
    print(compact({'status': 'completed', 'stage': args.stage,
                   'index': str(output / 'index.json'), 'counts': marker['counts']}))


if __name__ == '__main__':
    main()
