"""Measure the F30 production prefix from raw FIRRTL, using an explicit native package."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import re
import sys
import time
import tarfile

from benchmark_f29_pass_trace import native_identity, run_case, sha256, write_json_atomic
from benchmark_xs_firrtl_ingest import checked, request_from_manifest
from snapshot_f30_package import (SCHEMA as PACKAGE_SCHEMA, archived_source, build_identity,
                                  dependencies_content_hash, package_files)

ROOT = Path(__file__).resolve().parents[1]


def verify_file(record, field='path'):
    if (not isinstance(record, dict) or not isinstance(record.get(field), str) or
            re.fullmatch('[0-9a-f]{64}', str(record.get('sha256'))) is None):
        raise ValueError('invalid frozen file provenance')
    path = Path(record[field]).resolve()
    if not path.is_file() or sha256(path) != record['sha256']:
        raise ValueError(f'frozen file hash mismatch: {path}')
    return path


def verify_source_provenance(identity):
    source = identity.get('source')
    if (not isinstance(source, dict) or re.fullmatch('[0-9a-fA-F]{40,64}', str(source.get('git_head'))) is None or
            re.fullmatch('[0-9a-f]{64}', str(source.get('content_sha256'))) is None):
        raise ValueError('invalid frozen source provenance')
    archive = verify_file({'path': source.get('archive'), 'sha256': source.get('archive_sha256')})
    if source.get('mode') == 'archived-baseline':
        patch = verify_file({'path': source.get('patch'), 'sha256': source.get('patch_sha256')})
        if not isinstance(source.get('head_file'), str):
            raise ValueError('archived source lacks frozen HEAD identity')
        revision, actual = archived_source(archive, patch, Path(source['head_file']))
        if any(actual[key] != source[key] for key in ('git_head', 'content_sha256', 'archive_sha256', 'patch_sha256')):
            raise ValueError('archived source identity is inconsistent with frozen artifacts')
    elif source.get('mode') == 'working-tree':
        digest = hashlib.sha256()
        names = []
        with tarfile.open(archive, 'r:gz') as packed:
            for member in packed:
                name = Path(member.name)
                if not member.isfile() or name.is_absolute() or '..' in name.parts:
                    raise ValueError('source archive contains an unsafe or non-file member')
                content = hashlib.sha256()
                with packed.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                        content.update(block)
                record = json.dumps([member.name, member.size, bool(member.mode & 0o111), content.hexdigest()],
                                    separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
                digest.update(record)
                names.append(member.name)
        if not names or names != sorted(set(names)) or len(names) != source.get('file_count'):
            raise ValueError('source archive file inventory is inconsistent')
        if digest.hexdigest() != source['content_sha256']:
            raise ValueError('source archive content digest mismatch')
        revision = source['git_head'] + '+source-sha256:' + digest.hexdigest()
    else:
        raise ValueError('unsupported frozen source provenance mode')
    if 'dependencies' in source:
        dependency = source['dependencies']
        if (not isinstance(dependency, dict) or
                re.fullmatch('[0-9a-f]{64}', str(dependency.get('content_sha256'))) is None):
            raise ValueError('invalid source dependency provenance')
        verify_file(dependency)
        with Path(dependency['path']).open(encoding='utf-8') as stream:
            frozen = json.load(stream)
        if not isinstance(frozen, dict) or dependency.get('content_sha256') != frozen.get('content_sha256'):
            raise ValueError('source dependency content identity mismatch')
        revision += '+dependencies-sha256:' + frozen['content_sha256']
    if identity.get('source_revision') != revision:
        raise ValueError('source_revision is not bound to frozen source artifacts')


def verify_package_identity(package, identity_path):
    package, identity_path = Path(package).resolve(), Path(identity_path).resolve()
    with identity_path.open(encoding='utf-8') as stream:
        identity = json.load(stream)
    if (not isinstance(identity, dict) or identity.get('schema') != PACKAGE_SCHEMA or
            identity.get('package') != str(package)):
        raise ValueError('package identity schema or package path mismatch')
    cache = verify_file(identity.get('build_cache'))
    if cache != package / 'CMakeCache.txt' or build_identity(cache) != identity.get('build'):
        raise ValueError('build configuration is not bound to the frozen package cache')
    verify_source_provenance(identity)
    libraries = identity.get('libraries')
    if not isinstance(libraries, list) or libraries != package_files(package):
        raise ValueError('frozen native library inventory/hash/size mismatch')
    return identity


def verify_loaded_native(package, identity, native):
    package = Path(package).resolve()
    if not isinstance(native, dict) or native.get('package') != str(package / 'wolvrix/__init__.py'):
        raise ValueError('frozen Python package selection was overridden')
    expected = {}
    for library in identity['libraries']:
        relative = Path(library['path'])
        path = (package / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(package) or str(path) in expected:
            raise ValueError('unsafe or duplicate frozen native library path')
        expected[str(path)] = library['sha256']
    loaded = native.get('libraries')
    if not isinstance(loaded, list) or not loaded:
        raise ValueError('loaded native library identity is missing')
    names = []
    for library in loaded:
        if (not isinstance(library, dict) or library.get('path') not in expected or
                library.get('sha256') != expected[library['path']]):
            raise ValueError('actual loaded native library path/hash differs from frozen identity')
        names.append(Path(library['path']).name)
    if len(set(names)) != len(names) or not {'_wolvrix.so', 'libwolvrix-lib.so'} <= set(names):
        raise ValueError('actual mapped extension/core identity is incomplete or duplicated')


def verified_dependencies(package, path, identity):
    package, path = Path(package).resolve(), Path(path).resolve()
    with path.open(encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or value.get('schema') != 'wolvrix.f30.dependencies.v1':
        raise ValueError('missing frozen external dependency identity')
    repositories = value.get('repositories')
    if not isinstance(repositories, list):
        raise ValueError('invalid frozen dependency repository inventory')
    names, changed_paths = [], set()
    for repository in repositories:
        if not isinstance(repository, dict) or not isinstance(repository.get('path'), str):
            raise ValueError('invalid frozen dependency repository')
        relative = Path(repository['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[:1] not in (('external',), ('fetch',)):
            raise ValueError('invalid frozen dependency repository path')
        names.append(repository['path'])
        if (re.fullmatch('[0-9a-fA-F]{40,64}', str(repository.get('git_head'))) is None or
                re.fullmatch('[0-9a-f]{64}', str(repository.get('content_sha256'))) is None or
                type(repository.get('file_count')) is not int or repository['file_count'] < 0 or
                type(repository.get('dirty')) is not bool or not isinstance(repository.get('changed_files'), list)):
            raise ValueError('invalid frozen dependency content identity')
        changed = []
        for entry in repository['changed_files']:
            if (not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry['path'] or
                    type(entry.get('deleted')) is not bool):
                raise ValueError('invalid frozen dependency edit inventory')
            filename = Path(entry['path'])
            if filename.is_absolute() or '..' in filename.parts:
                raise ValueError('invalid frozen dependency edit path')
            changed.append(entry['path'])
            if (not entry['deleted'] and not any(part in ('build', 'ptmp', '.git', '__pycache__') for part in filename.parts)
                    and not filename.name.endswith(('.pyc', '.pyo'))):
                changed_paths.add((relative / filename).as_posix())
        if changed != sorted(set(changed)):
            raise ValueError('duplicate or unsorted frozen dependency edits')
    if names != sorted(set(names)) or value.get('content_sha256') != dependencies_content_hash(repositories):
        raise ValueError('frozen dependency global content digest mismatch')
    archive = verify_file({'path': value.get('archive'), 'sha256': value.get('archive_sha256')})
    with tarfile.open(archive, 'r:gz') as packed:
        seen = set()
        for member in packed:
            if not member.isfile() or member.name not in changed_paths or member.name in seen:
                raise ValueError('dependency archive differs from its dirty source inventory')
            seen.add(member.name)
        if seen != changed_paths:
            raise ValueError('dependency archive omits dirty source files')
    bound = identity['source'].get('dependencies')
    if bound is not None and (Path(bound['path']).resolve() != path or bound['sha256'] != sha256(path) or
                              bound['content_sha256'] != value['content_sha256']):
        raise ValueError('dependency sidecar differs from frozen source binding')
    return {'path': str(path), 'sha256': sha256(path), 'content_sha256': value['content_sha256'],
            'repositories': repositories, 'archive_sha256': value['archive_sha256'],
            'capture': value.get('capture'),
            'provenance': 'frozen-source-bound' if bound is not None else 'post-build-sidecar'}


def verified_input_request(source, manifest):
    source, manifest = Path(source).resolve(), Path(manifest).resolve()
    request = request_from_manifest(manifest)
    sources = []
    matched = False
    for entry in request['sources']:
        path = Path(entry['path']).resolve()
        sources.append({'path': str(path), 'language': entry['language'], 'unit': entry.get('unit'),
                        'bytes': path.stat().st_size, 'sha256': sha256(path)})
        matched |= entry['language'] == 'firrtl' and path == source
    if not matched:
        raise ValueError('--firrtl is not an actual FIRRTL input in the manifest')
    return request, sources


def configure_flatten_profile(enabled):
    if not enabled and os.environ.get('WOLVRIX_HIER_FLATTEN_PROFILE') == '1':
        raise ValueError('WOLVRIX_HIER_FLATTEN_PROFILE=1 requires explicit --profile-flatten; diagnostic samples must be marked')
    if enabled:
        os.environ['WOLVRIX_HIER_FLATTEN_PROFILE'] = '1'


def checked_stage_diagnostics(session, diagnostics, name, profile_flatten):
    checked(diagnostics, name)
    if name == 'hier-flatten' and profile_flatten:
        session.print_diagnostics(diagnostics, min_level='info')


def resolve_split_timeout(reference_paths, context, completed_before_ns):
    # Import after this module's provenance helpers are defined: the reference
    # inspector uses those same checks for the frozen GSIM source artifacts.
    from compare_f30_gsim import derive_split_timeout
    return derive_split_timeout(reference_paths, context, completed_before_ns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--identity', type=Path, help='frozen package identity.json (defaults to package/identity.json)')
    parser.add_argument('--dependencies-file', type=Path, help='frozen external dependency identity (defaults to package/dependencies.json)')
    parser.add_argument('--mode', choices=('no-trace', 'trace'), default='no-trace')
    parser.add_argument('--gsim-reference', type=Path, nargs='+', required=True,
                        help='at least three completed frozen GSIM no-trace summaries; split watchdog is twice their splitArray median')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--profile-flatten', action='store_true',
                        help='diagnostic native hier-flatten metrics; excluded from formal GSIM performance samples')
    parser.add_argument('--profile-split', action='store_true',
                        help='diagnostic CPU sampling during split; excluded from formal GSIM performance samples')
    parser.add_argument('--resource-guard', action='store_true',
                        help='diagnostic external RSS/PSI monitor; excluded from all formal performance samples')
    parser.add_argument('--resource-guard-rss-gib', type=float, default=96)
    parser.add_argument('--resource-guard-psi-percent', type=float, default=25)
    parser.add_argument('--resource-guard-psi-seconds', type=float, default=8)
    parser.add_argument('--resource-guard-interval-s', type=float, default=0.25)
    parser.add_argument('--resource-guard-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.resource_guard_child and not args.resource_guard:
        parser.error('--resource-guard-child requires --resource-guard')
    try:
        configure_flatten_profile(args.profile_flatten)
    except ValueError as error:
        parser.error(str(error))
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    summary = output / 'summary.json'
    if summary.exists():
        parser.error('refusing to overwrite an existing run')
    if args.resource_guard and not args.resource_guard_child:
        from f30_resource_guard import GuardLimits, run_guarded
        try:
            if not math.isfinite(args.resource_guard_rss_gib) or args.resource_guard_rss_gib <= 0:
                raise ValueError('resource guard RSS GiB must be positive and finite')
            limits = GuardLimits(rss_bytes=int(args.resource_guard_rss_gib * 1024**3),
                                 psi_percent=args.resource_guard_psi_percent,
                                 psi_seconds=args.resource_guard_psi_seconds,
                                 interval_s=args.resource_guard_interval_s)
            limits.validate()
        except ValueError as error:
            parser.error(str(error))
        raise SystemExit(run_guarded([sys.executable, str(Path(__file__).resolve()),
                                      *sys.argv[1:], '--resource-guard-child'], output, limits))
    package = args.package.resolve()
    identity_path = (args.identity or package / 'identity.json').resolve()
    # Validate the immutable snapshot before importing any of its native code.
    identity = verify_package_identity(package, identity_path)
    dependencies = verified_dependencies(package, args.dependencies_file or package / 'dependencies.json', identity)
    source, manifest = args.firrtl.resolve(), args.manifest.resolve()
    request, sources = verified_input_request(source, manifest)
    # Editable-install finders take precedence over sys.path. A frozen baseline
    # must load its own package and extension after later rebuilds.
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(package))
    import wolvrix

    loaded_native = native_identity(wolvrix)
    verify_loaded_native(package, identity, loaded_native)
    cpu_model = next((line.partition(':')[2].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                      if line.startswith('model name')), platform.machine())
    configuration = {
        'machine': list(platform.uname()), 'cpu_model': cpu_model,
        'thread_environment': {key: os.environ.get(key) for key in
                               ('OMP_NUM_THREADS', 'OMP_PROC_BIND', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS')},
        'build': identity.get('build'),
        'pass_parameters': {'ingest': 'manifest', 'xmr-resolve': {'keep_declared_symbols': True},
                            'hier-flatten': {'keep_declared_symbols': True}, 'comb-loop-elim': {},
                            'split-static-array': {}},
        'instrumentation': {'trace': args.mode == 'trace', 'verify': args.verify, 'statistics': False,
                            'source': 'raw-firrtl', 'clone': False, 'profile_flatten': args.profile_flatten,
                            'profile_split': args.profile_split, 'resource_guard': args.resource_guard},
        'sources': sources,
        'dependencies': {'content_sha256': dependencies['content_sha256'], 'repositories': dependencies['repositories']},
        'python_version': platform.python_version()}
    input_sha256 = sha256(source)
    affinity = sorted(os.sched_getaffinity(0))
    timeout_reference = resolve_split_timeout(args.gsim_reference,
        {'input': str(source), 'input_sha256': input_sha256, 'cpu_affinity': affinity,
         'configuration': configuration}, time.time_ns())
    split_timeout_s = timeout_reference['split_timeout_s']
    report = {'schema': 'wolvrix.f30.pipeline-benchmark.v1', 'status': 'running',
              'input': str(source), 'input_sha256': input_sha256,
              'manifest': str(manifest), 'manifest_sha256': sha256(manifest),
              'native': loaded_native, 'mode': args.mode,
              'cpu_affinity': affinity, 'verify': args.verify,
              'configuration': configuration, 'source_revision': identity.get('source_revision'),
              'identity_file': str(identity_path), 'identity_sha256': sha256(identity_path),
              'package_identity_verified': True, 'source_identity_verified': True, 'sources': sources,
              'dependencies_verified': True, 'dependencies': dependencies,
              'dependencies_provenance': dependencies['provenance'],
              'resource_scope': 'process CPU and cumulative process peak RSS; main wall is ingest through split before teardown',
              'workload': {'source_bytes': sum(entry['bytes'] for entry in sources),
                           'source_count': len(sources), 'graph_node_op_counts': 'not collected; semantic_stats traverses the full graph'},
              'split_timeout_s': split_timeout_s, 'split_timeout_reference': timeout_reference,
              'prefix': {'stages': []}}
    write_json_atomic(summary, report)
    started = time.monotonic()
    report['started_at_ns'] = time.time_ns()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    try:
        with wolvrix.Session() as session:
            session.log_level = 'error'
            session.diagnostics_raise_min_level = 'none'
            def stage(name, action):
                if args.resource_guard:
                    report['active_stage'] = {'kind': 'prefix', 'name': name, 'started_at_ns': time.time_ns()}
                    write_json_atomic(summary, report)
                before = resource.getrusage(resource.RUSAGE_SELF)
                clock = time.monotonic()
                diagnostics = action()
                after = resource.getrusage(resource.RUSAGE_SELF)
                row = {'stage': name, 'wall_s': time.monotonic() - clock,
                       'user_s': after.ru_utime - before.ru_utime,
                       'system_s': after.ru_stime - before.ru_stime,
                       'maxrss_kib': after.ru_maxrss}
                checked_stage_diagnostics(session, diagnostics, name, args.profile_flatten)
                if name == 'hier-flatten' and args.profile_flatten:
                    row['profile_diagnostics'] = diagnostics
                    row['profile_scope'] = 'native emitted total ends before local-map destruction; stage wall includes run_pass return and destruction'
                report['prefix']['stages'].append(row)
                write_json_atomic(summary, report)
                print(json.dumps(row), flush=True)
            stage('ingest', lambda: session.read_sources(**request, out_design='design.main', pipeline='ingest'))
            stage('xmr-resolve', lambda: session.run_pass('xmr-resolve', design='design.main', keep_declared_symbols=True))
            stage('hier-flatten', lambda: session.run_pass('hier-flatten', design='design.main', keep_declared_symbols=True))
            trace = args.mode == 'trace'
            if args.resource_guard:
                report['active_stage'] = {'kind': 'transform', 'name': 'comb-loop-elim', 'started_at_ns': time.time_ns()}
                write_json_atomic(summary, report)
            report['trace' if trace else 'no_trace'] = run_case(
                session, source, output / args.mode, trace, 'design.main', 'SimTop', False,
                report['input_sha256'], split_timeout_s, report, summary,
                validate_after=args.verify, profile_split=args.profile_split,
                verify_after=args.verify, run_started=started)
            # Record the complete boundary before session teardown frees the large graph.
            after = resource.getrusage(resource.RUSAGE_SELF)
            report.update(status='passed', wall_s=time.monotonic() - started,
                          finished_at_ns=time.time_ns(),
                          user_s=after.ru_utime - usage.ru_utime,
                          system_s=after.ru_stime - usage.ru_stime, maxrss_kib=after.ru_maxrss)
            if args.resource_guard:
                report['active_stage'] = {'kind': 'teardown', 'name': 'session-teardown'}
            write_json_atomic(summary, report)
    except BaseException as error:
        report.update(status='failed', error=repr(error), wall_s=time.monotonic() - started,
                      finished_at_ns=time.time_ns())
        write_json_atomic(summary, report)
        raise
    if args.resource_guard:
        report['active_stage'] = {'kind': 'complete', 'name': 'completed'}
        write_json_atomic(summary, report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
