"""F30 timing evidence must bind frozen binaries, provenance and actual inputs."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from benchmark_f29_pass_trace import WATCHDOG_SOURCE
from benchmark_f30_pipeline import (ROOT, verified_input_request, verify_loaded_native,
                                    verified_dependencies, verify_package_identity, verify_source_provenance,
                                    configure_flatten_profile, checked_stage_diagnostics, main)
from snapshot_f30_package import dependencies_content_hash, sha256, snapshot, snapshot_source


CACHE = '''CMAKE_BUILD_TYPE:STRING=Release
CMAKE_CXX_COMPILER:FILEPATH=/toolchain/clang++
CMAKE_CXX_FLAGS:STRING=
CMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG
'''


class BenchmarkIdentityTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / 'ptmp' / 'firrtl-ingest' / 'F30' / 'benchmark-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        installed = self.work / 'installed' / 'wolvrix'
        installed.mkdir(parents=True)
        (installed / '__init__.py').write_text('# frozen Python package\n')
        (installed / '_wolvrix.so').write_bytes(b'extension bytes')
        (installed / 'libwolvrix-lib.so').write_bytes(b'core bytes')
        cache = self.work / 'build-cache.txt'
        cache.write_text(CACHE)
        archive, patch, head = (self.work / name for name in ('source.tar.gz', 'source.patch', 'head.txt'))
        archive.write_bytes(b'immutable source archive')
        patch.write_bytes(b'immutable source patch')
        head.write_text('1' * 40 + '\n')
        self.package = self.work / 'package'
        self.identity = snapshot(argparse.Namespace(output=self.package, existing_package=installed.parent,
            record_existing=False, build_cache=cache, source_root=self.work,
            source_archive=archive, source_patch=patch, head_file=head))
        self.identity_path = self.package / 'identity.json'
        self.native = {'package': str(self.package / 'wolvrix/__init__.py'), 'libraries': [
            {'path': str(self.package / relative), 'sha256': sha256(self.package / relative)}
            for relative in ('wolvrix/_wolvrix.so', 'lib/libwolvrix-lib.so')]}

    def tearDown(self):
        self.temporary.cleanup()

    def store_identity(self, value):
        self.identity_path.write_text(json.dumps(value))

    def test_frozen_package_and_exact_mapped_native_hashes_are_bound(self):
        self.assertEqual(verify_package_identity(self.package, self.identity_path), self.identity)
        verify_loaded_native(self.package, self.identity, self.native)

    def test_flatten_profile_requires_explicit_diagnostic_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            configure_flatten_profile(False)
            self.assertNotIn('WOLVRIX_HIER_FLATTEN_PROFILE', os.environ)
            configure_flatten_profile(True)
            self.assertEqual(os.environ['WOLVRIX_HIER_FLATTEN_PROFILE'], '1')
            with self.assertRaisesRegex(ValueError, 'explicit --profile-flatten'):
                configure_flatten_profile(False)

    def test_resource_guard_cli_launches_external_child_before_native_import(self):
        arguments = ['benchmark', '--firrtl', str(self.work / 'SimTop.fir'),
                     '--manifest', str(self.work / 'manifest.json'), '--output', str(self.work / 'guarded'),
                     '--package', str(self.package), '--gsim-reference', str(self.work / 'gsim.json'),
                     '--resource-guard', '--resource-guard-rss-gib', '96']
        with patch.object(sys, 'argv', arguments), patch.dict(os.environ, {}, clear=True), \
                patch('f30_resource_guard.run_guarded', return_value=0) as guarded:
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        command, output, limits = guarded.call_args.args
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[-1], '--resource-guard-child')
        self.assertIn('--resource-guard', command)
        self.assertEqual(output, self.work / 'guarded')
        self.assertEqual(limits.rss_bytes, 96 * 1024**3)
        self.assertEqual(limits.psi_seconds, 8)

    def test_flatten_profile_keeps_info_diagnostics_and_checks_errors(self):
        session = Mock()
        diagnostics = [{'kind': 'info', 'message': 'profile source-calls=2 total-ms=4'}]
        checked_stage_diagnostics(session, diagnostics, 'hier-flatten', True)
        session.print_diagnostics.assert_called_once_with(diagnostics, min_level='info')
        session.reset_mock()
        checked_stage_diagnostics(session, diagnostics, 'hier-flatten', False)
        checked_stage_diagnostics(session, diagnostics, 'xmr-resolve', True)
        session.print_diagnostics.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'hier-flatten'):
            checked_stage_diagnostics(session, [{'kind': 'error'}], 'hier-flatten', True)
        session.print_diagnostics.assert_not_called()

    def test_schema_package_and_build_cache_must_match_frozen_metadata(self):
        for field, invalid in (('schema', 'wrong'), ('package', str(self.work / 'elsewhere')),
                               ('source_revision', 'unbound-revision'), ('build', {'flags': '-O0'})):
            with self.subTest(field=field):
                changed = deepcopy(self.identity)
                changed[field] = invalid
                self.store_identity(changed)
                with self.assertRaises(ValueError):
                    verify_package_identity(self.package, self.identity_path)
        self.store_identity(self.identity)
        (self.package / 'CMakeCache.txt').write_text(CACHE + 'CMAKE_CXX_FLAGS_DEBUG:STRING=-g\n')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            verify_package_identity(self.package, self.identity_path)

    def test_frozen_library_tampering_is_rejected_before_import(self):
        (self.package / 'lib/libwolvrix-lib.so').write_bytes(b'changed later build')
        with self.assertRaisesRegex(ValueError, 'library inventory'):
            verify_package_identity(self.package, self.identity_path)

    def test_loaded_paths_and_hashes_cannot_borrow_another_core_or_extension(self):
        for library in (0, 1):
            for field, invalid in (('path', str(self.work / 'other.so')), ('sha256', 'f' * 64)):
                with self.subTest(library=library, field=field):
                    changed = deepcopy(self.native)
                    changed['libraries'][library][field] = invalid
                    with self.assertRaisesRegex(ValueError, 'loaded native library'):
                        verify_loaded_native(self.package, self.identity, changed)
        for invalid in ([], self.native['libraries'][:1], [self.native['libraries'][0]] * 2):
            with self.subTest(libraries=invalid):
                changed = {**self.native, 'libraries': invalid}
                with self.assertRaises(ValueError):
                    verify_loaded_native(self.package, self.identity, changed)
        with self.assertRaisesRegex(ValueError, 'Python package selection'):
            verify_loaded_native(self.package, self.identity, {**self.native, 'package': '/editable/wolvrix/__init__.py'})

    def test_archived_source_hash_revision_and_head_are_verified(self):
        for field in ('archive', 'patch', 'head_file'):
            with self.subTest(field=field):
                path = Path(self.identity['source'][field])
                original = path.read_bytes()
                path.write_bytes(original + b'tampered')
                with self.assertRaises(ValueError):
                    verify_source_provenance(self.identity)
                path.write_bytes(original)
        changed = deepcopy(self.identity)
        changed['source']['content_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            verify_source_provenance(changed)

    def test_working_tree_archive_reconstructs_source_content_identity(self):
        source = self.work / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        (source / 'test.cpp').write_text('source\n')
        subprocess.run(['git', '-C', str(source), 'add', 'test.cpp'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=F30 test',
                        '-c', 'user.email=f30@example.invalid', 'commit', '-q', '-m', 'fixture'], check=True)
        revision, provenance = snapshot_source(source, self.work / 'working-tree.tar.gz')
        identity = {'source_revision': revision, 'source': provenance}
        verify_source_provenance(identity)
        for field in ('content_sha256', 'file_count'):
            changed = deepcopy(identity)
            changed['source'][field] = 'f' * 64 if field == 'content_sha256' else 99
            with self.assertRaises(ValueError):
                verify_source_provenance(changed)

    def test_all_manifest_sources_including_sv_are_content_hashed(self):
        firrtl, sv = self.work / 'SimTop.fir', self.work / 'External.sv'
        firrtl.write_text('FIRRTL source\n')
        sv.write_text('SystemVerilog source\n')
        manifest = self.work / 'manifest.json'
        manifest.write_text(json.dumps({'schema': 'wolvrix.xs.firrtl-inputs.v1', 'input_root': str(self.work),
            'sources': [{'language': 'firrtl', 'path': firrtl.name, 'unit': 'main'},
                        {'language': 'sv', 'path': sv.name}], 'tops': ['SimTop']}))
        request, sources = verified_input_request(firrtl, manifest)
        self.assertEqual([entry['language'] for entry in sources], ['firrtl', 'sv'])
        self.assertEqual([entry['path'] for entry in sources], [str(firrtl), str(sv)])
        self.assertEqual(sources[1]['sha256'], sha256(sv))
        self.assertEqual(request['sources'][0]['path'], str(firrtl))
        before = sources[1]['sha256']
        sv.write_text('changed external source\n')
        self.assertNotEqual(verified_input_request(firrtl, manifest)[1][1]['sha256'], before)
        other = self.work / 'Other.fir'
        other.write_bytes(firrtl.read_bytes())
        with self.assertRaisesRegex(ValueError, 'not an actual FIRRTL input'):
            verified_input_request(other, manifest)

    def test_dependency_sidecar_is_bound_without_rewriting_legacy_baseline_identity(self):
        path = self.package / 'dependencies.json'
        verified = verified_dependencies(self.package, path, self.identity)
        self.assertEqual(verified['content_sha256'], self.identity['source']['dependencies']['content_sha256'])
        self.assertEqual(verified['provenance'], 'frozen-source-bound')
        legacy = deepcopy(self.identity)
        del legacy['source']['dependencies']
        legacy['source_revision'] = legacy['source_revision'].split('+dependencies-sha256:')[0]
        verify_source_provenance(legacy)
        original = deepcopy(legacy)
        self.assertEqual(verified_dependencies(self.package, path, legacy)['provenance'], 'post-build-sidecar')
        self.assertEqual(legacy, original)
        for field, invalid in (('schema', 'wrong'), ('content_sha256', 'f' * 64), ('repositories', [{}])):
            with self.subTest(field=field):
                value = json.loads(path.read_text())
                changed = {**value, field: invalid}
                other = self.work / 'other-dependencies.json'
                other.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    verified_dependencies(self.package, other, legacy)
        other = self.work / 'unbound-dependencies.json'
        other.write_text(path.read_text())
        with self.assertRaisesRegex(ValueError, 'differs from frozen source binding'):
            verified_dependencies(self.package, other, self.identity)
        value = json.loads(path.read_text())
        repository = {'path': 'external/test', 'git_head': '1' * 40, 'content_sha256': 'f' * 64,
                      'file_count': 1, 'dirty': True, 'changed_files': [{'path': 'omitted.cpp', 'deleted': False}]}
        value.update(repositories=[repository], content_sha256=dependencies_content_hash([repository]))
        other.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'omits dirty source files'):
            verified_dependencies(self.package, other, legacy)

    def test_watchdog_persists_absolute_end_and_entire_production_boundary(self):
        summary = self.work / 'timed-out-summary.json'
        payload = {'timeout_s': 1.0, 'parent_pid': 123, 'row': {'pass': 'split-static-array'},
            'result': {'passes': []}, 'report': {'status': 'running', 'started_at_ns': 100},
            'case_started': 99.0, 'run_started': 50.0, 'case_key': 'trace',
            'timing_path': str(self.work / 'timing.json'), 'summary_path': str(summary),
            'marker_path': str(self.work / 'marker.json'), 'perf_pid': None}
        with patch.object(sys, 'argv', ['watchdog', json.dumps(payload)]), \
                patch('os.read', return_value=b'arm 100.0\n'), patch('os.write'), \
                patch('select.select', return_value=([], [], [])), \
                patch('time.monotonic', return_value=120.0), \
                patch('time.time_ns', return_value=123456789), patch('os.kill') as killed:
            exec(WATCHDOG_SOURCE, {})
        value = json.loads(summary.read_text())
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['finished_at_ns'], 123456789)
        self.assertEqual(value['wall_s'], 70.0)
        self.assertEqual(value['trace']['wall_s'], 21.0)
        self.assertEqual(value['trace']['passes'][0]['pass_s'], 20.0)
        self.assertNotIn('pass_returned', value['trace']['passes'][0])
        killed.assert_called_once()


if __name__ == '__main__':
    unittest.main()
