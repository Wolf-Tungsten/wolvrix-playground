"""Tiny synthetic capture contracts; no native ingestion or behavioral claims."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import audit_f32_capture_identity as audit
from benchmark_f30_pipeline import verified_dependencies
from snapshot_f30_package import build_identity, dependencies_content_hash, package_files
import test_compare_f32_semantics as fixtures


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def store(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def load(path):
    return json.loads(path.read_text())


class CaptureIdentityTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get('F32_CAPTURE_IDENTITY_TEST_ROOT',
                                  ROOT / 'ptmp/firrtl-ingest/F32/capture-equality-contract/tmp'))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / 'minimal.fir'
        self.source.write_text('FIRRTL version 4.2.0\ncircuit Tiny :\n')
        self.manifest = self.work / 'manifest.json'
        store(self.manifest, {'schema': 'wolvrix.xs.firrtl-inputs.v1', 'input_root': str(self.work),
                             'sources': [{'path': self.source.name, 'language': 'firrtl', 'unit': 'tiny'}],
                             'tops': ['Tiny']})
        self.captures = []
        for label in ('before', 'after'):
            fixture = fixtures.NativeComparisonTests('test_equal_inventory_is_only_a_candidate_result')
            fixture.work = self.work / label
            fixture.work.mkdir()
            fixture.frames = {engine: [{'nodes': [(1, 'input'), (2, 'middle'), (3, 'out')],
                'edges': [(1, 1, 2, 'dependency', 'resolved', [], None),
                          (2, 2, 3, 'dependency', 'resolved', [], None)],
                'widths': {}, 'shapes': {}, 'slices': [], 'structure': None}
                for _ in range(5)] for engine in ('grh', 'gsim')}
            fixture.attach_structure()
            directory = fixture.write_capture('grh')
            self.captures.append(directory)
            summary = load(directory / 'summary.json')
            package, identity, native, dependencies = self.package(label)
            summary.update(input=str(self.source), input_sha256=sha(self.source), input_bytes=self.source.stat().st_size,
                           manifest=str(self.manifest), manifest_sha256=sha(self.manifest),
                           sources=[{'path': str(self.source), 'language': 'firrtl', 'unit': 'tiny',
                                     'bytes': self.source.stat().st_size, 'sha256': sha(self.source)}],
                           package_identity=identity, native=native, dependencies=dependencies,
                           identity_file=str(package / 'identity.json'), identity_sha256=sha(package / 'identity.json'),
                           serialization_id_map=False, snapshot_run_id=label + '-run', pass_calls=[])
            for index, instance in enumerate(audit.CALLS):
                name = instance.split('#')[0]
                summary['pass_calls'].append({'pass': name, 'logical_instance': instance, 'prefix': index < 5,
                    'native_timers': [{'scope': 'pass', 'stage': name, 'complete': True}]})
            for stage in range(5):
                snapshot = summary['snapshots'][f'P{stage}']
                snapshot['semantic_validation'] = {'valid': True, 'error_count': 0}
                session = f'{label}-session-{stage}'
                for name in audit.TABLES:
                    path = directory / f'P{stage}' / name
                    raw, body = path.read_bytes().split(b'\n', 1)
                    meta = json.loads(raw[6:])
                    meta.update(run_id=label + '-run', snapshot_id=session + ':snapshot:' + snapshot['stage'])
                    if name in ('nodes.tsv', 'connections.tsv'):
                        meta.update(graph_id='123', exchange_session_id=session)
                    else:
                        meta.pop('graph_id', None)
                        meta.pop('exchange_session_id', None)
                        meta['session_id'] = session
                    path.write_bytes(('#meta\t' + json.dumps(meta) + '\n').encode() + body)
                    snapshot['artifacts'][name] = {**fixtures.artifact(path), 'metadata': meta}
            summary['resource_guard'] = {'status': 'completed', 'path': str(directory / 'guard.json'),
                                         'diagnostic_only': True}
            store(directory / 'guard.json', {'schema': 'wolvrix.f30.resource-guard.v1', 'status': 'completed',
                'returncode': 0, 'reason': 'child_completed', 'limits': {'rss_bytes': 96 * 1024**3},
                'command': ['synthetic-capture-test', '--engine', 'grh', '--output', str(directory),
                            '--firrtl', str(self.source), '--manifest', str(self.manifest),
                            '--package', str(package), '--guard-child']})
            store(directory / 'summary.json', summary)

    def package(self, label):
        package = self.work / ('package-' + label)
        (package / 'wolvrix').mkdir(parents=True)
        for name in ('_wolvrix.so', 'libwolvrix-lib.so'):
            (package / 'wolvrix' / name).write_bytes((label + '-' + name).encode())
        (package / 'wolvrix/__init__.py').write_text('# synthetic package metadata fixture\n')
        cache = package / 'CMakeCache.txt'
        cache.write_text('CMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_COMPILER:FILEPATH=/fixture/clang++\n'
                         'CMAKE_CXX_FLAGS:STRING=\nCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG\n')
        source = b'synthetic package source\n'
        archive = package / 'source.tar.gz'
        with tarfile.open(archive, 'w:gz') as packed:
            member = tarfile.TarInfo('fixture.cpp')
            member.size, member.mode = len(source), 0o644
            packed.addfile(member, io.BytesIO(source))
        record = json.dumps(['fixture.cpp', len(source), False, hashlib.sha256(source).hexdigest()],
                            separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
        content = hashlib.sha256(record).hexdigest()
        dependency_archive = package / 'dependencies.tar.gz'
        with tarfile.open(dependency_archive, 'w:gz'):
            pass
        dependency = {'schema': 'wolvrix.f30.dependencies.v1', 'repositories': [],
                      'content_sha256': dependencies_content_hash([]), 'archive': str(dependency_archive),
                      'archive_sha256': sha(dependency_archive)}
        store(package / 'dependencies.json', dependency)
        bound = {'path': str(package / 'dependencies.json'), 'sha256': sha(package / 'dependencies.json'),
                 'content_sha256': dependency['content_sha256']}
        identity = {'schema': 'wolvrix.f30.package-identity.v1', 'package': str(package),
                    'build_cache': {'path': str(cache), 'sha256': sha(cache)}, 'build': build_identity(cache),
                    'source': {'mode': 'working-tree', 'git_head': '1' * 40, 'content_sha256': content,
                               'archive': str(archive), 'archive_sha256': sha(archive), 'file_count': 1,
                               'dependencies': bound},
                    'source_revision': '1' * 40 + '+source-sha256:' + content +
                                       '+dependencies-sha256:' + dependency['content_sha256'],
                    'libraries': package_files(package)}
        store(package / 'identity.json', identity)
        native = {'package': str(package / 'wolvrix/__init__.py'),
                  'libraries': [{'path': str(package / row['path']), 'sha256': row['sha256']}
                                for row in identity['libraries']]}
        dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
        return package, identity, native, dependencies

    def run_audit(self, name='audit'):
        return audit.audit(*self.captures, self.work / name)

    def summary(self, side=1):
        return load(self.captures[side] / 'summary.json')

    def update_summary(self, value, side=1):
        store(self.captures[side] / 'summary.json', value)

    def refresh(self, stage, name, side=1):
        summary = self.summary(side)
        path = self.captures[side] / f'P{stage}' / ('design.json' if name == 'structure' else name)
        summary['snapshots'][f'P{stage}']['artifacts'][name] = fixtures.artifact(path)
        self.update_summary(summary, side)

    def metadata(self, stage, updates, names=audit.TABLES):
        for name in names:
            path = self.captures[1] / f'P{stage}' / name
            raw, body = path.read_bytes().split(b'\n', 1)
            meta = {**json.loads(raw[6:]), **updates}
            path.write_bytes(('#meta\t' + json.dumps(meta) + '\n').encode() + body)
            self.refresh(stage, name)

    def assert_failed_receipt(self, name='audit'):
        receipt = load(self.work / name / 'receipt.json')
        self.assertEqual(receipt['status'], 'failed')
        self.assertFalse(receipt['complete'])
        self.assertNotIn('result', receipt)

    def test_same_data_distinct_native_metadata_and_packages(self):
        with patch.object(audit.reader, 'database', side_effect=AssertionError('no comparison DB')):
            result = self.run_audit()
        self.assertEqual(result['result'], 'equal')
        self.assertTrue(result['data_equal'])
        self.assertEqual(len(result['boundaries']), 5)
        self.assertEqual(result['native_histories'][0]['runs'], ['before-run'])
        self.assertEqual(result['native_histories'][1]['runs'], ['after-run'])
        self.assertNotEqual(result['before']['package']['identity_sha256'],
                            result['after']['package']['identity_sha256'])
        self.assertFalse(result['semantic_acceptance_evaluated'])
        self.assertFalse(result['behavior_equivalence_proved'])
        self.assertFalse(result['comparison_database_opened'])
        self.assertTrue(all(row['stat_before'] == row['stat_after'] for row in result['frozen_files']))

    def test_body_difference_is_complete_truthful_difference(self):
        path = self.captures[1] / 'P2/nodes.tsv'
        path.write_bytes(path.read_bytes().replace(b'["middle"]\tmiddle', b'["changed"]\tchanged'))
        self.refresh(2, 'nodes.tsv')
        result = self.run_audit()
        self.assertEqual(result['result'], 'different')
        self.assertTrue(result['complete'])
        self.assertFalse(result['boundaries']['P2']['tables'][0]['body_equal'])
        self.assertTrue(result['boundaries']['P2']['structure']['exact_bytes_equal'])

    def test_structure_bytes_are_not_normalized(self):
        path = self.captures[1] / 'P3/design.json'
        path.write_bytes(path.read_bytes() + b' \n')
        self.refresh(3, 'structure')
        result = self.run_audit()
        self.assertEqual(result['result'], 'different')
        self.assertFalse(result['boundaries']['P3']['structure']['exact_bytes_equal'])

    def test_forged_table_hash_is_rejected(self):
        path = self.captures[1] / 'P0/nodes.tsv'
        path.write_bytes(path.read_bytes().replace(b'input', b'other'))
        with self.assertRaisesRegex(ValueError, 'changed since capture'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_forged_footer_is_rejected_even_with_updated_artifact_hash(self):
        path = self.captures[1] / 'P0/nodes.tsv'
        data = path.read_bytes()
        path.write_bytes(data.replace(b'"rowCount":3', b'"rowCount":99').replace(b'"rowCount": 3', b'"rowCount": 99'))
        self.assertNotEqual(data, path.read_bytes())
        self.refresh(0, 'nodes.tsv')
        with self.assertRaisesRegex(ValueError, 'incorrect row count'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_mixed_run_graph_and_snapshot_reject(self):
        for index, updates in enumerate(({'run_id': 'foreign'}, {'graph_id': 'foreign'},
                                         {'snapshot_id': 'foreign'})):
            with self.subTest(updates=updates):
                original = {name: (self.captures[1] / 'P1' / name).read_bytes() for name in audit.TABLES}
                self.metadata(1, updates)
                with self.assertRaises(ValueError):
                    self.run_audit(f'mixed-{index}')
                self.assert_failed_receipt(f'mixed-{index}')
                for name, data in original.items():
                    (self.captures[1] / 'P1' / name).write_bytes(data)
                    self.refresh(1, name)

    def test_endpoint_session_is_not_borrowed_from_other_snapshot(self):
        self.metadata(1, {'session_id': 'after-session-0'}, names=('node-endpoints.tsv',))
        with self.assertRaisesRegex(ValueError, 'exporter session'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_duplicate_snapshot_and_session_are_rejected(self):
        self.metadata(1, {'snapshot_id': 'after-session-0:snapshot:' + audit.reader.STAGES['grh'][0]})
        with self.assertRaises(ValueError):
            self.run_audit()
        self.assert_failed_receipt()

    def test_unfinished_or_nonzero_guard_rejects(self):
        path = self.captures[1] / 'guard.json'
        original = load(path)
        for index, update in enumerate(({'status': 'running'}, {'returncode': -15}, {'reason': 'cgroup_pressure'})):
            store(path, {**original, **update})
            with self.assertRaisesRegex(ValueError, 'guard did not complete'):
                self.run_audit(f'guard-{index}')
            self.assert_failed_receipt(f'guard-{index}')

    def test_manifest_and_input_identity_mismatch_reject(self):
        original = self.summary()
        for index, field in enumerate(('input_sha256', 'manifest_sha256')):
            changed = deepcopy(original)
            changed[field] = 'f' * 64
            self.update_summary(changed)
            with self.assertRaises(ValueError):
                self.run_audit(f'input-{index}')
            self.assert_failed_receipt(f'input-{index}')
        self.update_summary(original)

    def test_package_and_recorded_native_mismatch_reject(self):
        original = self.summary()
        changed = deepcopy(original)
        changed['native']['libraries'][0]['sha256'] = '0' * 64
        self.update_summary(changed)
        with self.assertRaisesRegex(ValueError, 'loaded native'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_changed_package_library_rejects(self):
        summary = self.summary()
        path = Path(summary['native']['libraries'][0]['path'])
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'library inventory'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_structure_frozen_hash_mismatch_rejects(self):
        path = self.captures[1] / 'P0/design.json'
        path.write_bytes(path.read_bytes() + b' \n')
        with self.assertRaisesRegex(ValueError, 'invalid frozen structure identity'):
            self.run_audit()
        self.assert_failed_receipt()

    def test_map_presence_or_unsupported_mapping_rejects_without_guessing(self):
        original = self.summary()
        for side in (0, 1):
            summary = self.summary(side)
            summary['serialization_id_map'] = True
            for stage in range(5):
                path = self.captures[side] / f'P{stage}/serialization-id-map.tsv'
                path.write_text('unsupported synthetic map\n')
                summary['snapshots'][f'P{stage}']['artifacts']['serialization-id-map.tsv'] = fixtures.artifact(path)
            self.update_summary(summary, side)
            if side == 0:
                with self.assertRaisesRegex(ValueError, 'map presence differs'):
                    self.run_audit('map-mismatch')
            else:
                with self.assertRaisesRegex(ValueError, 'mapped captures are unsupported'):
                    self.run_audit('map-unsupported')
        self.assert_failed_receipt('map-mismatch')
        self.assert_failed_receipt('map-unsupported')

    def test_metadata_changed_during_audit_cannot_publish_success(self):
        original = audit.compare_structure
        changed = False

        def mutate(*args):
            nonlocal changed
            result = original(*args)
            if not changed:
                path = self.captures[1] / 'summary.json'
                path.write_bytes(path.read_bytes() + b' \n')
                changed = True
            return result

        with patch.object(audit, 'compare_structure', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'frozen input changed'):
                self.run_audit()
        self.assert_failed_receipt()

    def test_existing_output_is_not_overwritten(self):
        self.run_audit()
        path = self.work / 'audit/receipt.json'
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'fresh directory'):
            self.run_audit()
        self.assertEqual(path.read_bytes(), before)

    def test_failed_receipt_publication_cannot_leave_an_equal_result(self):
        original = audit.reader.write_json
        calls = 0

        def fail_once(path, value):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.assertEqual(value['result'], 'equal')
                raise OSError('deliberate publication failure')
            original(path, value)

        with patch.object(audit.reader, 'write_json', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'publication failure'):
                self.run_audit()
        self.assert_failed_receipt()


if __name__ == '__main__':
    unittest.main()
