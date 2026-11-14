"""Provenance regressions for F30 frozen package snapshots; run via Make."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from snapshot_f30_package import (ROOT, archived_source, build_identity, dependencies_content_hash,
                                  dependency_snapshot, sha256, snapshot, snapshot_source)


CACHE = '''CMAKE_BUILD_TYPE:STRING=Release
CMAKE_CXX_COMPILER:FILEPATH=/toolchain/clang++
CMAKE_CXX_FLAGS:STRING=
CMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG
WOLVRIX_ENABLE_LIBFST:BOOL=ON
WOLVRIX_MIMALLOC_STATS:BOOL=OFF
SLANG_USE_THREADS:BOOL=ON
'''


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'ptmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='f30-snapshot-test-', dir=ROOT / 'ptmp')
        self.work = Path(self.temporary.name)
        self.cache = self.work / 'cache.txt'
        self.cache.write_text(CACHE, encoding='utf-8')

    def tearDown(self):
        self.temporary.cleanup()

    def arguments(self, output, **changes):
        defaults = dict(output=output, existing_package=None, record_existing=False,
                        build_cache=self.cache, source_root=self.work,
                        source_archive=None, source_patch=None, head_file=None)
        defaults.update(changes)
        return argparse.Namespace(**defaults)

    def baseline_sources(self):
        archive, patch, head = (self.work / name for name in ('source.tar.gz', 'source.patch', 'head.txt'))
        archive.write_bytes(b'original source archive including untracked F29')
        patch.write_text('original working tree patch\n', encoding='utf-8')
        head.write_text('1' * 40 + '\n', encoding='utf-8')
        return dict(source_archive=archive, source_patch=patch, head_file=head)

    def package(self, name):
        output = self.work / name
        (output / 'wolvrix').mkdir(parents=True)
        (output / 'wolvrix' / '_wolvrix.so').write_bytes(b'original extension')
        (output / 'wolvrix' / 'libwolvrix-lib.so').write_bytes(b'original library')
        (output / 'wolvrix' / '__init__.py').write_text('# package\n', encoding='utf-8')
        return output

    def test_existing_baseline_keeps_binaries_and_uses_only_archived_sources(self):
        output = self.package('baseline')
        sources = self.baseline_sources()
        before = {path: sha256(path) for path in output.rglob('*.so')}
        result = snapshot(self.arguments(output, record_existing=True, source_root=self.work / 'missing', **sources))
        self.assertEqual(before, {path: sha256(path) for path in before})
        self.assertEqual(result['source']['mode'], 'archived-baseline')
        self.assertTrue(result['source_revision'].startswith('1' * 40 + '+archive-patch-sha256:'))
        self.assertEqual(result['build']['CMAKE_CXX_FLAGS_RELEASE'], '-O3 -DNDEBUG')
        self.assertEqual(result['build']['features']['WOLVRIX_MIMALLOC_STATS'], 'OFF')
        self.assertEqual(json.loads((output / 'identity.json').read_text()), result)
        with self.assertRaisesRegex(ValueError, 'existing package identity'):
            snapshot(self.arguments(output, record_existing=True, **sources))

    def test_candidate_copies_real_bytes_and_satisfies_relative_library_path(self):
        original = self.package('installed')
        output = self.work / 'candidate'
        result = snapshot(self.arguments(output, existing_package=original, **self.baseline_sources()))
        original_library = original / 'wolvrix/libwolvrix-lib.so'
        for path in (output / 'wolvrix/libwolvrix-lib.so', output / 'lib/libwolvrix-lib.so'):
            self.assertEqual(sha256(path), sha256(original_library))
            self.assertFalse(path.is_symlink())
        original_library.write_bytes(b'changed later install')
        self.assertNotEqual(sha256(original_library), sha256(output / 'wolvrix/libwolvrix-lib.so'))
        self.assertEqual(len(result['libraries']), 3)

    def test_baseline_identity_changes_with_uncommitted_source_patch(self):
        sources = self.baseline_sources()
        first, _ = archived_source(*sources.values())
        sources['source_patch'].write_text('different F29 patch\n', encoding='utf-8')
        second, _ = archived_source(*sources.values())
        self.assertNotEqual(first, second)

    def test_source_snapshot_is_deterministic_and_includes_untracked_sources(self):
        source = self.work / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        (source / 'tracked.cpp').write_text('tracked\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(source), 'add', 'tracked.cpp'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=F30 test',
                        '-c', 'user.email=f30@example.invalid', 'commit', '-q', '-m', 'fixture'], check=True)
        (source / 'f29_untracked.cpp').write_text('untracked F29\n', encoding='utf-8')
        (source / 'build').mkdir()
        (source / 'build/generated.cpp').write_text('generated output\n', encoding='utf-8')
        first, metadata = snapshot_source(source, self.work / 'first.tar.gz')
        second, _ = snapshot_source(source, self.work / 'second.tar.gz')
        self.assertEqual(first, second)
        self.assertEqual(sha256(self.work / 'first.tar.gz'), sha256(self.work / 'second.tar.gz'))
        self.assertEqual(metadata['file_count'], 2)
        with tarfile.open(self.work / 'first.tar.gz') as archive:
            self.assertEqual(archive.getnames(), ['f29_untracked.cpp', 'tracked.cpp'])
        (source / 'f29_untracked.cpp').write_text('modified F29\n', encoding='utf-8')
        third, _ = snapshot_source(source, self.work / 'third.tar.gz')
        self.assertNotEqual(first, third)

    def test_missing_build_fields_and_unbound_baseline_provenance_are_rejected(self):
        self.cache.write_text('CMAKE_BUILD_TYPE:STRING=Release\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'required fields'):
            build_identity(self.cache)
        with self.assertRaisesRegex(ValueError, 'archived baseline'):
            snapshot(self.arguments(self.package('baseline'), record_existing=True))

    def test_dependencies_bind_dirty_sources_and_archive_only_modified_files(self):
        source = self.work / 'sources'
        dependency = source / 'external/slang'
        dependency.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(dependency)], check=True)
        (dependency / 'tracked.cpp').write_text('baseline dependency\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(dependency), 'add', 'tracked.cpp'], check=True)
        subprocess.run(['git', '-C', str(dependency), '-c', 'user.name=F30 test',
                        '-c', 'user.email=f30@example.invalid', 'commit', '-q', '-m', 'dependency'], check=True)
        clean_output, dirty_output = self.work / 'clean', self.work / 'dirty'
        clean_output.mkdir()
        dirty_output.mkdir()
        clean = dependency_snapshot(source, self.work / 'no-build', clean_output)
        self.assertFalse(clean['repositories'][0]['dirty'])
        with tarfile.open(clean_output / 'dependencies.tar.gz') as archive:
            self.assertEqual(archive.getnames(), [])
        (dependency / 'tracked.cpp').write_text('changed dependency\n', encoding='utf-8')
        (dependency / 'untracked.cpp').write_text('untracked dependency\n', encoding='utf-8')
        dirty = dependency_snapshot(source, self.work / 'no-build', dirty_output)
        self.assertTrue(dirty['repositories'][0]['dirty'])
        self.assertNotEqual(clean['content_sha256'], dirty['content_sha256'])
        self.assertEqual(dirty['content_sha256'], dependencies_content_hash(dirty['repositories']))
        with tarfile.open(dirty_output / 'dependencies.tar.gz') as archive:
            self.assertEqual(archive.getnames(), ['external/slang/tracked.cpp', 'external/slang/untracked.cpp'])


if __name__ == '__main__':
    unittest.main()
