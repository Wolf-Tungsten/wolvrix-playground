"""Capture, validate, and identify the single GSIM reference used by F35."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from benchmark_f29_pass_trace import sha256, write_json_atomic
from benchmark_f30_gsim import freeze_native
from capture_f32_pipeline import table_artifact
from capture_f34_pass_trace import GSIM_BUNDLES, run_gsim
from capture_f34_pipeline import GSIM_ROOT
from f35_pass_guard import GSIM_CALLS, read_gsim_times
from semantic_node_exchange import HEADERS, parsed_row


GSIM_BOUNDARY_LABELS = {
    'RemoveDeadNodes': 'RemoveDeadNodes0',
    '{g->usedBits()}': 'UsedBits',
    '{g->splitNodes()}': 'SplitNodes',
}
SOURCE_TABLES = {
    'init-node-origins.tsv': 'gsim.init-node-origins.v1',
    'init-source-scopes.tsv': 'gsim.init-scopes.v1',
    'init-source-assignments.tsv': 'gsim.init-assignments.v1',
}
TRACE_MUTATIONS = {'detect-loop', 'topo-sort', 'infer-width', 'expr-opt', 'used-bits',
                   'split-nodes', 'constant-analysis', 'alias-analysis', 'pattern-detect', 'common-expr'}
SNAPSHOT_TABLES = ('nodes', 'connections', 'node-details', 'bit-slices')
TIMING = 'native-timing.jsonl'
BUDGETS = 'pass-budgets.json'
SUMMARY = 'summary.json'
FROZEN = 'frozen.json'
RECEIPT = 'native-capture.json'
RECOVERY = 'recovery-from-dce-2'
ALIAS_RECOVERY = 'recovery-from-alias-analysis'
TAIL_BUNDLES = GSIM_BUNDLES[10:]
BUDGET_SCHEMA = 'wolvrix.f35.pass-budgets.v1'
FROZEN_SCHEMA = 'wolvrix.f35.gsim-reference.v1'


def pass_budgets(path):
    times = read_gsim_times(path)
    return {logical: {'gsim_stage': GSIM_BOUNDARY_LABELS.get(stage, stage),
                      'gsim_pass_instance': instance, 'reference_s': times[stage, instance],
                      'budget_s': 2 * times[stage, instance]}
            for logical, (stage, instance) in GSIM_CALLS.items()}


def recovery_timing_evidence(root, input_sha):
    """Use the captured native pass rows while graph stitching is verified."""
    tail = root / ALIAS_RECOVERY
    receipt = json.loads((tail / RECEIPT).read_text())
    if receipt['input_sha256'] != input_sha or sha256(Path(receipt['binary']['path'])) != receipt['binary']['sha256']:
        raise ValueError('GSIM tail timing input or binary differs from build receipt')
    original = root / 'native-timing-interrupted.jsonl'
    if not original.is_file():
        original = root / TIMING
    sections = (
        (original, None, 'RemoveDeadNodes#1'),
        (root / RECOVERY / TIMING, 'RemoveDeadNodes#1', 'AliasAnalysis#0'),
        (tail / TIMING, 'AliasAnalysis#0', None),
    )
    captured = []
    for path, first, last in sections:
        rows = path.read_text().splitlines()
        instances = [json.loads(row)['pass_instance'] for row in rows]
        captured.extend(rows[instances.index(first) if first else 0:
                             instances.index(last) if last in instances else len(rows)])
    timing = root.parent / 'recovery-timing.jsonl'
    timing.write_text('\n'.join(captured) + '\n')
    pass_budgets(timing)
    return timing, {'run_id': receipt['run_id'], 'timing_status': 'recovery-captures',
                    'timing_sha256': sha256(timing)}


def run_gsim_reference(args, input_sha):
    if args.binary is None or args.stop_before_final_dce:
        raise ValueError('F35 GSIM reference requires a binary and the fourth DCE stop')
    if (args.output / FROZEN).exists() or (args.output / 'gsim.log').exists():
        raise ValueError('F35 reference already has a GSIM invocation')
    native, native_path = freeze_native(args.binary, GSIM_ROOT, args.output)
    run_id = args.run_id
    options = ('--timing-output=' + str(args.output / TIMING),
               '--trace-init-sources=' + str(args.output), '--run-id=' + run_id)
    launch = SimpleNamespace(**vars(args))
    launch.binary = Path(native['binary'])
    identity, passes = run_gsim(launch, input_sha, extra_options=options)
    return finish_invocation(args, input_sha, native, native_path, identity, passes)


def finish_invocation(args, input_sha, native, native_path, identity, passes):
    budgets = pass_budgets(args.output / TIMING)
    if sha256(args.firrtl) != input_sha or identity['sha256'] != native['sha256']:
        raise ValueError('F35 GSIM input or frozen binary changed during its capture')
    log_path = Path(identity.get('execution_log', args.output / 'gsim.log'))
    with log_path.open(encoding='utf-8') as log:
        parser_threads = [int(match[1]) for line in log
                          if (match := re.search(r'\[Parser\] using ([0-9]+) threads to parse ', line))]
    if parser_threads != [1]:
        raise ValueError(f'F35 GSIM expected the existing single-thread parser configuration, got {parser_threads}')
    identity.update(native_identity=str(native_path), run_id=args.run_id, parser_threads=parser_threads[0],
                    cpu_affinity=sorted(os.sched_getaffinity(0)),
                    native_timing_sha256=sha256(args.output / TIMING),
                    version=subprocess.check_output([native['binary'], '--version'], text=True).strip())
    write_json_atomic(args.output / BUDGETS, {'schema': BUDGET_SCHEMA, 'run_id': args.run_id,
                                              'native_timing_sha256': identity['native_timing_sha256'],
                                              'pass_budgets': budgets})
    write_json_atomic(args.output / RECEIPT, {'engine': 'gsim', 'binary': identity, 'passes': passes,
                                               'input_sha256': input_sha, 'top': args.top})
    return identity, passes


def compare_boundary(old, new, *, remap_path=None):
    """Match every byte after the per-invocation metadata line."""
    if remap_path is not None:
        return compare_remapped_boundary(old, new, remap_path)
    result = {}
    for table in SNAPSHOT_TABLES:
        name = f'before.{table}.tsv'
        with (old / name).open('rb') as left, (new / name).open('rb') as right:
            left.readline()
            right.readline()
            for chunk in iter(lambda: left.read(1024 * 1024), b''):
                if chunk != right.read(len(chunk)):
                    raise ValueError('GSIM recovery changed the DCE2 input: ' + name)
            if right.read(1):
                raise ValueError('GSIM recovery expanded the DCE2 input: ' + name)
        result[name] = {'original_sha256': sha256(old / name), 'recovery_sha256': sha256(new / name)}
    return result


def compare_remapped_boundary(old, new, remap_path):
    """Compare exported snapshots in the recovered invocation's ID space."""
    null = b'\\N'
    with remap_path.open('rb') as stream:
        if stream.readline() != b'before_node_id\tafter_node_id\n':
            raise ValueError('invalid GSIM recovery ID mapping header')
        pairs = [tuple(row.rstrip(b'\n').split(b'\t')) for row in stream]
    remap = dict(pairs)
    if len(remap) != len(pairs) or len({right for _, right in pairs}) != len(pairs) or any(
            left == right or not left.isdigit() or not right.isdigit() for left, right in pairs):
        raise ValueError('invalid GSIM recovery ID mapping')

    result = {}
    with TemporaryDirectory(dir=os.environ.get('TMPDIR', old.parent)) as scratch:
        scratch = Path(scratch)
        for table in SNAPSHOT_TABLES:
            name = f'before.{table}.tsv'
            left_file, right_file = old / name, new / name
            left_artifact, right_artifact = checked_table(left_file), checked_table(right_file)
            if left_artifact['footer'] != right_artifact['footer']:
                raise ValueError('GSIM recovery table footer changed: ' + name)
            columns = {'nodes': (0,), 'node-details': (0, 5, 6), 'connections': (1, 2),
                       'bit-slices': (0, 1)}[table]
            sorted_paths = []
            for side, path in enumerate((left_file, right_file)):
                projection = scratch / f'{side}.tsv'
                with path.open('rb') as source, projection.open('wb') as output:
                    source.readline()
                    header = source.readline()
                    if side == 0:
                        expected = header
                    elif header != expected:
                        raise ValueError('GSIM recovery table columns changed: ' + name)
                    for row in source:
                        if row.startswith(b'#footer\t'):
                            break
                        if not side:
                            fields = row.rstrip(b'\n').split(b'\t')
                            for column in columns:
                                token = fields[column]
                                fields[column] = remap.get(token, token)
                            if table == 'connections' and fields[5] != b'[]':
                                candidates = sorted(int(remap.get(token, token)) for token in fields[5][1:-1].split(b','))
                                fields[5] = b'[' + b','.join(str(value).encode() for value in candidates) + b']'
                            offset = 1 if table == 'connections' else 0
                            output.write(b'\t'.join(fields[offset:]) + b'\n')
                        else:
                            output.write(row.partition(b'\t')[2] if table == 'connections' else row)
                sorted_path = scratch / f'{side}.sorted'
                subprocess.run(['sort', '-S', '256M', '-T', str(scratch), '-o', str(sorted_path), str(projection)],
                               check=True, env={**os.environ, 'LC_ALL': 'C'})
                projection.unlink()
                sorted_paths.append(sorted_path)
            if sha256(sorted_paths[0]) != sha256(sorted_paths[1]):
                raise ValueError('GSIM recovery graph differs after ID remap: ' + name)
            for path in sorted_paths:
                path.unlink()
            result[name] = {'original_sha256': left_artifact['sha256'], 'recovery_sha256': right_artifact['sha256'],
                            'row_count': left_artifact['footer']['rowCount']}
    return {'tables': result, 'renumbered_ids': len(remap)}


def recover_reference(args, input_sha):
    root = args.output
    if (root / RECEIPT).exists() or not (root / 'dce-2/before.nodes.tsv').is_file():
        raise ValueError('GSIM recovery requires the interrupted DCE2 reference')
    if any((root / bundle).exists() for bundle in TAIL_BUNDLES[1:]):
        raise ValueError('refusing to replace any captured GSIM tail bundle')
    original_id = json.loads((root / 'native/identity.json').read_text())
    if sha256(Path(original_id['binary'])) != original_id['sha256']:
        raise ValueError('original GSIM binary changed')
    with (root / 'split/before.nodes.tsv').open() as stream:
        meta = json.loads(stream.readline().partition('\t')[2])
    if meta.get('input_identity', {}).get('sha256') != input_sha or meta.get('root_name') != args.top:
        raise ValueError('GSIM recovery input does not match the captured prefix')
    captured_dce = root / RECOVERY
    use_previous_dce = (captured_dce / 'dce-2/evolution.tsv').is_file()
    start = 'alias-analysis' if use_previous_dce else 'dce-2'
    tail = root / (ALIAS_RECOVERY if use_previous_dce else RECOVERY)
    capture_receipt = tail / RECEIPT
    if capture_receipt.is_file():
        receipt = json.loads(capture_receipt.read_text())
        identity, native = receipt['binary'], receipt['native']
        native_path = tail / 'native/identity.json'
        args.run_id = receipt['run_id']
        if receipt['input_sha256'] != input_sha or sha256(Path(identity['path'])) != identity['sha256']:
            raise ValueError('GSIM tail capture receipt changed')
    else:
        tail.mkdir(exist_ok=False)
        native, native_path = freeze_native(args.binary, GSIM_ROOT, tail)
        launch = SimpleNamespace(**vars(args))
        launch.output = tail
        launch.binary = Path(native['binary'])
        identity, _ = run_gsim(launch, input_sha, selection='pipeline-from-' + start, extra_options=(
            '--timing-output=' + str(tail / TIMING),
            '--run-id=' + args.run_id,
        ))
        write_json_atomic(capture_receipt, {'binary': identity, 'native': native,
                                          'run_id': args.run_id, 'input_sha256': input_sha})
    dce = captured_dce if use_previous_dce else tail
    joins = {'dce-2': (root / 'dce-2', dce / 'dce-2')}
    if use_previous_dce:
        joins[start] = (captured_dce / start, tail / start)
    bridge = {}
    for boundary, (left, right) in joins.items():
        source = args.recovery_maps / f'{boundary}.complete.tsv' if args.recovery_maps else None
        record = compare_boundary(left, right, remap_path=source)
        if source:
            target = root / f'{boundary}-recovery-id-map.tsv'
            shutil.copy2(source, target)
            record['node_id_remap'] = target.name
        bridge[boundary] = record
        print(f'GSIM recovery boundary validated: {boundary}', flush=True)
    original_timing = root / 'native-timing-interrupted.jsonl'
    original_rows = (root / TIMING).read_text().splitlines()
    tail_rows = (tail / TIMING).read_text().splitlines()
    dce_start = GSIM_CALLS['dead-code-elim#2'][1]
    original_end = next(index for index, line in enumerate(original_rows)
                        if json.loads(line).get('pass_instance') == dce_start)
    if use_previous_dce:
        dce_rows = (dce / TIMING).read_text().splitlines()
        first_dce_row = next(index for index, line in enumerate(dce_rows)
                             if json.loads(line).get('pass_instance') == dce_start)
        original_rows = original_rows[:original_end] + dce_rows[first_dce_row:]
        original_end = len(original_rows)
    tail_start = next(index for index, line in enumerate(tail_rows)
                      if json.loads(line).get('pass_instance') == ('AliasAnalysis#0' if use_previous_dce else dce_start))
    shutil.copy2(root / TIMING, original_timing)
    (root / TIMING).write_text('\n'.join(original_rows[:original_end] + tail_rows[tail_start:]) + '\n')
    pass_budgets(root / TIMING)
    shutil.move(root / 'dce-2', dce / 'interrupted-dce-2')
    shutil.move(dce / 'dce-2', root / 'dce-2')
    for name in (*TAIL_BUNDLES[1:], 'alias-analysis-migrations.jsonl'):
        shutil.move(tail / name, root / name)
    identity.update(execution_log=str(tail / 'gsim.log'), recovery_bridge=bridge,
                    recovery_directories=list(dict.fromkeys((dce.name, tail.name))),
                    prefix_binary_sha256=original_id['sha256'])
    passes = [{'pass': name, 'bundles': [str(root / name)]} for name in GSIM_BUNDLES]
    return finish_invocation(args, input_sha, native, native_path, identity, passes)


def checked_table(path):
    report = table_artifact(path)
    del report['path']
    return report


def checked_jsonl(path):
    first, last, report = journal_artifact(path)
    header, footer = json.loads(first), json.loads(last)
    if header.get('record') != 'header' or footer.get('record') != 'footer' or footer.get('complete') is not True:
        raise ValueError('native JSONL footer missing: ' + str(path))
    return dict(report, metadata=header, footer=footer)


def checked_evolution(path):
    with path.open('rb') as stream:
        columns = stream.readline()
    if columns.decode().rstrip('\n').split('\t') != list(HEADERS['evolution']):
        raise ValueError('bad native evolution columns: ' + str(path))
    first, last, report = journal_artifact(path, skip=len(columns))
    begin = parsed_row(first.decode(), HEADERS['evolution'])
    end = parsed_row(last.decode(), HEADERS['evolution'])
    header, footer = json.loads(begin['detail_json']), json.loads(end['detail_json'])
    if (begin['record'] != 'header' or end['record'] != 'footer' or
            footer.get('complete') is not True or footer.get('replayComplete') is not True):
        raise ValueError('native evolution footer missing: ' + str(path))
    return dict(report, metadata=header, footer=footer)


def journal_artifact(path, *, skip=0):
    """Checksum large journals in chunks and read just their framing records."""
    with path.open('rb') as stream:
        stream.seek(skip)
        first = stream.readline()
        length = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, length - 16384))
        tail = stream.read()
    if (not first.endswith(b'\n') or not tail.endswith(b'\n') or
            length <= skip + len(first) or b'\n' not in tail[:-1]):
        raise ValueError('unfinished native journal: ' + str(path))
    last = tail[:-1].rsplit(b'\n', 1)[-1] + b'\n'
    return first, last, {'bytes': length, 'sha256': sha256(path)}


def freeze_reference(args, summary):
    """Finalize completed on-disk journals; this never launches GSIM."""
    output = args.output
    if (output / FROZEN).exists() or summary.get('engine') != 'gsim':
        raise ValueError('expected one unfrozen GSIM capture')
    source = next(row for row in summary['inputs']['sources'] if row['path'] == str(args.firrtl))
    input_sha = source['sha256']
    receipt = json.loads((output / RECEIPT).read_text())
    if (receipt['binary'] != summary['binary'] or receipt['passes'] != summary['passes'] or
            receipt['input_sha256'] != input_sha or receipt['top'] != args.top):
        raise ValueError('F35 reference summary differs from the successful GSIM capture receipt')
    if tuple(stage['pass'] for stage in summary['passes']) != GSIM_BUNDLES:
        raise ValueError('GSIM capture summary lacks the ordered F35 pass prefix')
    files = {}
    for bundle in (*GSIM_BUNDLES, 'preparation'):
        for side in ('before', 'after'):
            for table in SNAPSHOT_TABLES:
                path = f'{bundle}/{side}.{table}.tsv'
                files[path] = checked_table(output / path)
                meta = files[path]['metadata']
                if meta.get('input_identity', {}).get('sha256') != input_sha or meta.get('root_name') != args.top:
                    raise ValueError('GSIM snapshot input or root mismatch: ' + path)
        if bundle != 'preparation':
            path = f'{bundle}/evolution.tsv'
            files[path] = journal = checked_evolution(output / path)
            for side in ('before', 'after'):
                nodes = files[f'{bundle}/{side}.nodes.tsv']
                connections = files[f'{bundle}/{side}.connections.tsv']
                if (journal['metadata'].get(f'{side}_snapshot_id') != nodes['metadata']['snapshot_id'] or
                        journal['footer'].get(f'{side}NodeCount') != nodes['footer']['rowCount'] or
                        journal['footer'].get(f'{side}ConnectionCount') != connections['footer']['rowCount']):
                    raise ValueError('GSIM pass journal does not cover ' + path)
        if bundle in TRACE_MUTATIONS:
            path = f'{bundle}/native-mutations.jsonl'
            files[path] = checked_jsonl(output / path)
        if summary.get('verified_replay') and bundle != 'preparation':
            path = f'{bundle}/verification.json'
            files[path] = {'bytes': (output / path).stat().st_size, 'sha256': sha256(output / path)}
    init = files['split/before.nodes.tsv']
    final = files['dce-3/after.nodes.tsv']
    if (init['metadata'].get('stage') != 'Init' or final['metadata'].get('stage') != 'RemoveDeadNodes3' or
            final['metadata'].get('pass_instance') != 'RemoveDeadNodes#2'):
        raise ValueError('GSIM Init or fourth DCE Node boundary is missing')
    for path, schema in SOURCE_TABLES.items():
        files[path] = checked_table(output / path)
        meta = files[path]['metadata']
        if meta.get('schema') != schema or meta.get('input_sha256') != input_sha:
            raise ValueError('GSIM source sidecar identity mismatch: ' + path)
    origins = files['init-node-origins.tsv']
    if (origins['metadata'].get('snapshot_id') != init['metadata']['snapshot_id'] or
            origins['footer']['rowCount'] != init['footer']['rowCount']):
        raise ValueError('GSIM source sidecar does not cover Init')
    files['alias-analysis-migrations.jsonl'] = checked_jsonl(output / 'alias-analysis-migrations.jsonl')
    for path in (SUMMARY, BUDGETS, TIMING, RECEIPT, 'gsim.log', 'preparation/summary.json', 'native/identity.json', 'native/gsim',
                 'native/source.tar.gz', 'native/source.patch', 'native/ldd.log'):
        files[path] = {'bytes': (output / path).stat().st_size, 'sha256': sha256(output / path)}
    native_run_ids = {'prefix': init['metadata']['run_id'], 'tail': final['metadata']['run_id']}
    if 'recovery_bridge' in summary['binary']:
        for bridge in summary['binary']['recovery_bridge'].values():
            if path := bridge.get('node_id_remap'):
                files[path] = {'bytes': (output / path).stat().st_size, 'sha256': sha256(output / path)}
        for directory in summary['binary']['recovery_directories']:
            for name in ('gsim.log', TIMING, 'native/identity.json', 'native/gsim', 'native/source.tar.gz',
                         'native/source.patch', 'native/ldd.log'):
                path = f'{directory}/{name}'
                files[path] = {'bytes': (output / path).stat().st_size, 'sha256': sha256(output / path)}
        path = 'native-timing-interrupted.jsonl'
        files[path] = {'bytes': (output / path).stat().st_size, 'sha256': sha256(output / path)}
    elif native_run_ids['prefix'] != native_run_ids['tail']:
        raise ValueError('unexplained GSIM run ID change between Init and fourth DCE')
    write_json_atomic(output / FROZEN, {'schema': FROZEN_SCHEMA, 'run_id': summary['binary']['run_id'],
                                        'input_sha256': input_sha, 'top': args.top,
                                        'native_run_ids': native_run_ids, 'files': files})
    return load_frozen_reference(output)


def resume_reference(args, input_sha):
    """Reuse the receipt for a completed native invocation after later validation failed."""
    receipt = json.loads((args.output / RECEIPT).read_text())
    if (receipt.get('engine') != 'gsim' or receipt.get('input_sha256') != input_sha or
            receipt.get('top') != args.top):
        raise ValueError('GSIM capture receipt does not match the requested input')
    binary = receipt['binary']
    if (sha256(Path(binary['path'])) != binary['sha256'] or
            sha256(args.output / TIMING) != binary['native_timing_sha256']):
        raise ValueError('native GSIM artifacts changed before finalization')
    return binary, receipt['passes']


def load_frozen_reference(output):
    """Check the frozen manifest and small timing files without rereading the graph."""
    output = Path(output)
    frozen = json.loads((output / FROZEN).read_text())
    if frozen.get('schema') != FROZEN_SCHEMA or not frozen.get('run_id'):
        raise ValueError('invalid F35 GSIM reference marker')
    for name in (SUMMARY, BUDGETS, TIMING):
        path = output / name
        record = frozen['files'][name]
        if path.stat().st_size != record['bytes'] or sha256(path) != record['sha256']:
            raise ValueError('frozen GSIM reference changed: ' + name)
    budgets = json.loads((output / BUDGETS).read_text())
    if (budgets.get('schema') != BUDGET_SCHEMA or budgets.get('run_id') != frozen['run_id'] or
            budgets.get('native_timing_sha256') != frozen['files'][TIMING]['sha256'] or
            budgets.get('pass_budgets') != pass_budgets(output / TIMING)):
        raise ValueError('frozen GSIM budgets do not match native timing')
    return frozen
