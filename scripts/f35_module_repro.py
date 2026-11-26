"""Run the F35 GRH pipeline on a selected FIRRTL module and inspect named samples."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import resource
import sys
from tempfile import TemporaryDirectory
import time

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f33_performance import normalized_environment
from benchmark_xs_firrtl_ingest import request_from_manifest
from capture_f32_pipeline import action
from capture_f34_pipeline import production_calls
from f35_compare import ENDPOINT_HEADER, WORK
from f35_trace_samples import inventory, sample_name_hints, tsv_evidence
from semantic_node_exchange import HEADERS


DESIGN = 'design.main'
DETAIL_LIMIT = 32
LOADER_MARKER = 'F35_MODULE_LIBRARY_SELECTED'
DEFAULT_FIRRTL_OPTIONS = {
    'init_policy': 'unknown',
    'invalid_policy': 'zero',
    'node_annotations': True,
    'enabled_layers': ['Verification.Assert', 'Verification.Assume', 'Verification.Cover'],
}


def input_request(source, isolated, module, manifest, helpers, threads):
    if manifest:
        request = request_from_manifest(manifest)
        firrtl = [entry for entry in request['sources'] if entry['language'] == 'firrtl']
        if len(firrtl) != 1 or Path(firrtl[0]['path']) != source:
            raise ValueError('--manifest must contain one FIRRTL source matching --firrtl')
        firrtl[0]['path'] = str(isolated)
    else:
        request = {
            'sources': [{'language': 'firrtl', 'path': str(isolated), 'unit': 'xiangshan'}],
            'input_root': str(source.parent),
            'firrtl_options': dict(DEFAULT_FIRRTL_OPTIONS),
        }
    known = {entry['path'] for entry in request['sources']}
    for helper in helpers:
        if str(helper) not in known:
            request['sources'].append({'language': 'sv', 'path': str(helper), 'unit': 'helpers'})
            known.add(str(helper))
    request['tops'] = [module]
    request.setdefault('firrtl_options', {})['lower_threads'] = threads
    return request


def file_evidence(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def choose_passes(calls, requested):
    passing = [instance for _, instance, _, _ in calls]
    chosen = set()
    for selector in requested:
        matches = [instance for instance in passing if selector in (instance, instance.split('#')[0])]
        if len(matches) != 1:
            raise ValueError(f'pass selection {selector!r} must identify one occurrence: {", ".join(passing)}')
        chosen.add(matches[0])
    return [instance for instance in passing if instance in chosen]


def select_library(path):
    if not path:
        return
    if path.name != 'libwolvrix-lib.so' or not path.is_file():
        raise ValueError('--wolvrix-lib must select a libwolvrix-lib.so file')
    if os.environ.pop(LOADER_MARKER, '') != str(path):
        environment = {**os.environ, LOADER_MARKER: str(path), 'LD_LIBRARY_PATH': str(path.parent)}
        os.execve(sys.executable, [sys.executable, *sys.argv], environment)


def snapshot(session, args, stage, names):
    directory = args.out / stage
    directory.mkdir()
    with TemporaryDirectory(dir=directory) as scratch:
        scratch = Path(scratch)
        snapshot_args = {'design': DESIGN, 'top': args.module, 'stage': stage, 'output': str(scratch)}
        action(session.semantic_snapshot(**snapshot_args), stage)
        if args.rhs_only:
            names_path = scratch / 'rhs-names.txt'
            names_path.write_text(''.join(name + '\n' for name in names), encoding='utf-8')
            action(session.semantic_snapshot(**snapshot_args, rhs_only=True,
                                             rhs_names=str(names_path)), stage + ' RHS')
            rhs_path = directory / 'rhs-root-signatures.tsv'
            (scratch / rhs_path.name).replace(rhs_path)
        exact, nodes = inventory(scratch / 'nodes.tsv', names, set())
        identifiers = {identifier for ids in exact.values() for identifier in ids}
        if len(identifiers) > DETAIL_LIMIT:
            raise ValueError(f'{stage} matched {len(identifiers)} nodes, select more specific sample names')
        endpoints = tsv_evidence(scratch / 'node-endpoints.tsv', ENDPOINT_HEADER,
                                 lambda row: row[0] in identifiers)
        connections = tsv_evidence(scratch / 'connections.tsv', HEADERS['connections'],
                                   lambda row: row[1] in identifiers or row[2] in identifiers)
        slices = tsv_evidence(scratch / 'bit-slices.tsv', ('before_node_id', 'after_node_id', 'low', 'width'),
                              lambda row: row[0] in identifiers or row[1] in identifiers)
        result = {
            'exact_names': {name: list(map(int, exact.get(name, []))) for name in names},
            'nodes': nodes['rows'],
            'endpoints': endpoints,
            'connections': connections,
            'bit_slices': slices,
        }
        if args.source_order:
            metadata = session.graph_metadata(design=DESIGN, top=args.module)['metadata']
            ranks = metadata.get('firrtl.commonExprSourceOrder', [])
            result['common_expr_source_order'] = {
                name: {str(identifier): ranks[int(identifier)] if int(identifier) < len(ranks) else None
                       for identifier in exact.get(name, [])}
                for name in names
            }
        for evidence in (endpoints, connections, slices):
            evidence['source_table'] = Path(evidence.pop('path')).name
        if identifiers:
            action(session.semantic_snapshot(**snapshot_args, detail_node_ids=sorted(map(int, identifiers))),
                   stage + ' details')
            details = directory / 'node-details.jsonl'
            (scratch / details.name).replace(details)
            result['details'] = file_evidence(details)
            if args.named_inputs:
                import json
                inputs = []
                with details.open(encoding='utf-8') as records:
                    for line in records:
                        row = json.loads(line)
                        if row.get('record') == 'boundary' and row.get('kind') == 'data':
                            inputs.append(row)
                result['named_data_inputs'] = inputs
    write_json_atomic(directory / 'samples.json', result)
    return result


def run_pipeline(args, request, calls, selected):
    import wolvrix

    names = sample_name_hints(args.sample)
    stages, passes = {}, []
    with wolvrix.Session() as session:
        session.log_level = 'error'
        started = time.monotonic()
        action(session.read_sources(**request, out_design=DESIGN, pipeline='ingest'), 'module ingest')
        ingest_s = time.monotonic() - started
        for name, instance, keep, options in calls:
            final = instance == calls[-1][1]
            if instance in selected:
                stages['before-' + instance] = snapshot(session, args, 'before-' + instance, names)
            print('F35 module ' + instance, flush=True)
            started = time.monotonic()
            action(session.run_pass(name, design=DESIGN, keep_declared_symbols=keep, **options), instance)
            passes.append({'instance': instance, 'wall_s': time.monotonic() - started,
                           'keep_declared_symbols': keep, 'options': options})
            if final or instance in selected:
                boundary = 'R4' if final else 'after-' + instance
                stages[boundary] = snapshot(session, args, boundary, names)
    return {'passes': passes, 'stages': stages, 'ingest_wall_s': ingest_s}


def main():
    from f35_module_extract import DEFAULT_MAX_BYTES, extract_module

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('firrtl', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('manifest', 'wolvrix-lib'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--module', required=True, help='name of the FIRRTL module to use as the top')
    parser.add_argument('--sample', action='append', required=True, help='exact module-relative SemanticNode name')
    parser.add_argument('--pass', action='append', dest='passes', required=True,
                        help='capture before and after this production pass occurrence')
    parser.add_argument('--sv', action='append', type=Path, default=[], help='additional SV implementation source')
    parser.add_argument('--threads', type=int, default=4, help='FIRRTL lowering threads')
    parser.add_argument('--source-order', action='store_true',
                        help='record CommonExpr source-order ranks for selected sample names')
    parser.add_argument('--rhs-only', action='store_true',
                        help='export selected samples’ normalized RHS signatures at each captured boundary')
    parser.add_argument('--named-inputs', action='store_true',
                        help='record direct named data boundaries for selected nodes')
    parser.add_argument('--max-firrtl-bytes', type=int, default=DEFAULT_MAX_BYTES,
                        help='maximum extracted FIRRTL size')
    args = parser.parse_args()
    for field in ('firrtl', 'out', 'manifest', 'wolvrix_lib'):
        if (path := getattr(args, field)) is not None:
            setattr(args, field, path.resolve())
    args.sv = [path.resolve() for path in args.sv]
    if args.out == WORK or not args.out.is_relative_to(WORK):
        parser.error('module artifacts must be under ptmp/firrtl-ingest/F35/')
    if args.threads < 1 or len(set(args.sample)) > DETAIL_LIMIT or not all(args.sample):
        parser.error(f'use positive lowering threads and between 1 and {DETAIL_LIMIT} unique nonempty sample names')
    if args.max_firrtl_bytes < 1:
        parser.error('--max-firrtl-bytes must be positive')
    args.module = args.module.strip('\x60')
    select_library(args.wolvrix_lib)
    normalized_environment()
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)

    import wolvrix
    from wolvrix_xs_grhsim import firrtl_canonical_pipeline

    prefix, window = production_calls(firrtl_canonical_pipeline())
    calls = prefix + window
    selected = choose_passes(calls, args.passes)
    binary = native_identity(wolvrix)
    if args.wolvrix_lib and str(args.wolvrix_lib) not in {entry['path'] for entry in binary['libraries']}:
        raise RuntimeError(f'requested Wolvrix library was not loaded: {args.wolvrix_lib}; loaded {binary["libraries"]}')

    started = time.monotonic()
    isolated = args.out / 'isolated.fir'
    request = input_request(args.firrtl, isolated, args.module, args.manifest, args.sv, args.threads)
    args.out.mkdir(parents=True)
    extraction = extract_module(args.firrtl, args.module, isolated, max_bytes=args.max_firrtl_bytes)
    sources = [
        {**entry, 'bytes': extraction['output_bytes'], 'sha256': extraction['output_sha256']}
        if entry['language'] == 'firrtl' else {**entry, **file_evidence(Path(entry['path']))}
        for entry in request['sources']
    ]
    prepare_s = time.monotonic() - started
    result = run_pipeline(args, request, calls, selected)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report = {
        'schema': 'wolvrix.f35.module-repro.v1',
        'complete': True,
        'module': args.module,
        'selected_passes': selected,
        'manifest': file_evidence(args.manifest) if args.manifest else None,
        'input_sources': sources,
        'ingest_request': request,
        'extraction': extraction,
        'binary': binary,
        'prepare_wall_s': prepare_s,
        'wall_s': time.monotonic() - started,
        'peak_rss_kib': usage.ru_maxrss,
        **result,
    }
    write_json_atomic(args.out / 'summary.json', report)
    print(f'F35 module {args.module} finished in {report["wall_s"]:.2f} s, '
          f'peak RSS {usage.ru_maxrss / 1024:.1f} MiB, evidence {args.out / "summary.json"}', flush=True)


if __name__ == '__main__':
    main()
