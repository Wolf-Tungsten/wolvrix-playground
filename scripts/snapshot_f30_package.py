"""Freeze an installed F30 native package and its source/build provenance.

Invoke through the project Makefile. Existing baseline binaries are immutable;
--record-existing adds provenance from the explicitly archived baseline sources.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'wolvrix'
SCHEMA = 'wolvrix.f30.package-identity.v1'
BUILD_FIELDS = ('CMAKE_BUILD_TYPE', 'CMAKE_CXX_COMPILER', 'CMAKE_CXX_FLAGS',
                'CMAKE_CXX_FLAGS_RELEASE')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build_identity(cache: Path) -> dict:
    entries = {}
    features = {}
    for line in cache.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([^/#:=][^:=]*):([^=]+)=(.*)', line)
        if not match:
            continue
        key, kind, value = match.groups()
        entries[key] = value
        if ((key.startswith(('WOLVRIX_', 'SLANG_', 'MI_', 'TBB_')) and kind == 'BOOL') or
                key in ('BUILD_SHARED_LIBS', 'CMAKE_INTERPROCEDURAL_OPTIMIZATION',
                        'WOLVRIX_MIMALLOC_GENERIC_COLLECT')):
            features[key] = value
    missing = set(BUILD_FIELDS) - entries.keys()
    if missing:
        raise ValueError('build cache lacks required fields: ' + ', '.join(sorted(missing)))
    if not entries['CMAKE_BUILD_TYPE'] or not entries['CMAKE_CXX_COMPILER']:
        raise ValueError('build cache must identify compiler and build type')
    return {**{key: entries[key] for key in BUILD_FIELDS}, 'features': dict(sorted(features.items()))}


def git(source: Path, *arguments: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(source), *arguments])


def snapshot_source(source: Path, archive: Path) -> tuple[str, dict]:
    head = git(source, 'rev-parse', 'HEAD').decode().strip()
    paths = sorted(set(git(source, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0')))
    digest = hashlib.sha256()
    count = 0
    with archive.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as packed:
        with tarfile.open(fileobj=packed, mode='w|') as tar:
            for encoded in paths:
                if not encoded:
                    continue
                name = encoded.decode('utf-8')
                relative = Path(name)
                if relative.parts[0] in ('external', 'build', 'ptmp', '.git', '.venv', '__pycache__'):
                    continue
                path = source / relative
                if not path.is_file() or path.name.endswith(('.pyc', '.pyo')):
                    continue
                data = path.read_bytes()
                executable = bool(path.stat().st_mode & 0o111)
                record = json.dumps([name, len(data), executable, hashlib.sha256(data).hexdigest()],
                                    separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
                digest.update(record)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if executable else 0o644
                tar.addfile(info, io.BytesIO(data))
                count += 1
    if not count:
        raise ValueError('source snapshot contains no files')
    content = digest.hexdigest()
    return head + '+source-sha256:' + content, {
        'mode': 'working-tree', 'git_head': head, 'content_sha256': content,
        'file_count': count, 'archive': str(archive.resolve()), 'archive_sha256': sha256(archive)}


def archived_source(archive: Path, patch: Path, head_file: Path) -> tuple[str, dict]:
    head = head_file.read_text(encoding='utf-8').strip()
    if re.fullmatch(r'[0-9a-fA-F]{40,64}', head) is None:
        raise ValueError('baseline head file must contain a git commit identity')
    archive_hash, patch_hash = sha256(archive), sha256(patch)
    content = hashlib.sha256(('archive:' + archive_hash + '\npatch:' + patch_hash + '\n').encode()).hexdigest()
    return head + '+archive-patch-sha256:' + content, {
        'mode': 'archived-baseline', 'git_head': head, 'content_sha256': content,
        'archive': str(archive.resolve()), 'archive_sha256': archive_hash,
        'patch': str(patch.resolve()), 'patch_sha256': patch_hash,
        'head_file': str(head_file.resolve())}


def dependencies_content_hash(repositories: list[dict]) -> str:
    return hashlib.sha256(json.dumps(repositories, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def dependency_snapshot(source: Path, build_directory: Path, output: Path) -> dict:
    """Freeze git-owned dependency sources, including dirty/untracked files."""
    metadata_path, archive = output / 'dependencies.json', output / 'dependencies.tar.gz'
    if metadata_path.exists() or archive.exists():
        raise ValueError('refusing to replace existing dependency provenance')
    repositories = {}
    external = source / 'external'
    if external.is_dir():
        for path in sorted(external.rglob('.git')):
            if path.parent.is_dir():
                repositories['external/' + path.parent.relative_to(external).as_posix()] = path.parent
    fetched = build_directory / '_deps'
    if fetched.is_dir():
        for path in sorted(fetched.glob('*-src')):
            if (path / '.git').exists():
                repositories['fetch/' + path.name.removesuffix('-src')] = path
    identities = []
    with archive.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as packed:
        with tarfile.open(fileobj=packed, mode='w|') as tar:
            for name, repository in sorted(repositories.items()):
                head = git(repository, 'rev-parse', 'HEAD').decode().strip()
                paths = sorted(set(git(repository, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0')))
                changed = set(git(repository, 'diff', '--name-only', 'HEAD', '-z').split(b'\0'))
                changed.update(git(repository, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))
                changed.discard(b'')
                digest = hashlib.sha256()
                count = 0
                for encoded in paths:
                    if not encoded:
                        continue
                    relative = Path(encoded.decode('utf-8'))
                    if any(part in ('build', 'ptmp', '.git', '__pycache__') for part in relative.parts):
                        continue
                    path = repository / relative
                    if not path.is_file() or path.name.endswith(('.pyc', '.pyo')):
                        continue
                    data = path.read_bytes()
                    executable = bool(path.stat().st_mode & 0o111)
                    record = json.dumps([relative.as_posix(), len(data), executable, hashlib.sha256(data).hexdigest()],
                                        separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
                    digest.update(record)
                    if encoded in changed:
                        info = tarfile.TarInfo(name + '/' + relative.as_posix())
                        info.size = len(data)
                        info.mode = 0o755 if executable else 0o644
                        tar.addfile(info, io.BytesIO(data))
                    count += 1
                identities.append({'path': name, 'git_head': head,
                                   'content_sha256': digest.hexdigest(), 'file_count': count,
                                   'changed_files': [{'path': item.decode('utf-8'),
                                                      'deleted': not (repository / item.decode('utf-8')).is_file()}
                                                     for item in sorted(changed)],
                                   'dirty': bool(git(repository, 'status', '--porcelain', '--untracked-files=all'))})
    digest = dependencies_content_hash(identities)
    result = {'schema': 'wolvrix.f30.dependencies.v1', 'content_sha256': digest,
              'repositories': identities, 'archive': str(archive.resolve()), 'archive_sha256': sha256(archive),
              'archive_scope': 'dirty and untracked dependency files only; clean files are identified by repository HEAD',
              'capture': 'current dependency working trees; does not retroactively establish pre-build capture'}
    with metadata_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return result


def installed_package() -> Path:
    import wolvrix
    from wolvrix import _wolvrix

    package = Path(_wolvrix.__file__).resolve().parent
    if not (package / '__init__.py').is_file():
        raise ValueError('native extension directory is not an installed wolvrix package')
    return package.parent


def package_files(package: Path) -> list[dict]:
    files = []
    for path in sorted(package.rglob('*')):
        if path.is_file() and (path.name.endswith('.so') or '.so.' in path.name):
            files.append({'path': str(path.relative_to(package)), 'sha256': sha256(path),
                          'size': path.stat().st_size})
    names = {Path(row['path']).name for row in files}
    if not {'_wolvrix.so', 'libwolvrix-lib.so'} <= names:
        raise ValueError('package is missing the native extension or core library')
    return files


def snapshot(args: argparse.Namespace) -> dict:
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    if (output / 'identity.json').exists():
        raise ValueError('refusing to replace an existing package identity')
    supplied_archive = (args.source_archive, args.source_patch, args.head_file)
    if any(supplied_archive) and not all(supplied_archive):
        raise ValueError('source archive, source patch and head file must be supplied together')
    if args.record_existing and not all(supplied_archive):
        raise ValueError('--record-existing requires explicit archived baseline source provenance')
    if args.record_existing:
        if args.existing_package is not None:
            raise ValueError('--record-existing cannot copy another package')
        if not output.is_dir():
            raise ValueError('existing frozen package does not exist')
    else:
        if output.exists():
            raise ValueError('refusing to overwrite an existing snapshot directory')
        source_package = (args.existing_package or installed_package()).resolve()
        native = source_package / 'wolvrix'
        if not native.is_dir():
            raise ValueError('--existing-package must contain a wolvrix/ package directory')
        output.mkdir(parents=True)
        shutil.copytree(native, output / 'wolvrix', symlinks=False,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '*.bak'))
        # The native extension can carry an RPATH to ../lib. Freeze the same
        # core bytes there without retaining links into the editable install.
        (output / 'lib').mkdir()
        shutil.copy2(output / 'wolvrix' / 'libwolvrix-lib.so', output / 'lib' / 'libwolvrix-lib.so')
    cache = output / 'CMakeCache.txt'
    if not cache.exists():
        shutil.copy2(args.build_cache, cache)
    build = build_identity(cache)
    if all(supplied_archive):
        revision, source = archived_source(*supplied_archive)
    else:
        revision, source = snapshot_source(args.source_root.resolve(), output / 'source.tar.gz')
    dependency = dependency_snapshot(args.source_root.resolve(), args.build_cache.resolve().parent, output)
    source['dependencies'] = {'path': str(output / 'dependencies.json'),
                              'sha256': sha256(output / 'dependencies.json'),
                              'content_sha256': dependency['content_sha256']}
    revision += '+dependencies-sha256:' + dependency['content_sha256']
    identity = {'schema': SCHEMA, 'package': str(output), 'build': build,
                'source_revision': revision, 'source': source,
                'build_cache': {'path': str(cache), 'sha256': sha256(cache)},
                'libraries': package_files(output)}
    temporary = output / '.identity.pending'
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(identity, stream, indent=2, sort_keys=True)
        stream.write('\n')
    temporary.replace(output / 'identity.json')
    return identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--existing-package', type=Path)
    parser.add_argument('--record-existing', action='store_true')
    parser.add_argument('--dependencies-only', action='store_true',
                        help='freeze current dependencies beside an immutable existing baseline identity')
    parser.add_argument('--build-cache', type=Path, default=SOURCE / 'build/skbuild/CMakeCache.txt')
    parser.add_argument('--source-root', type=Path, default=SOURCE)
    parser.add_argument('--source-archive', type=Path)
    parser.add_argument('--source-patch', type=Path)
    parser.add_argument('--head-file', type=Path)
    args = parser.parse_args()
    try:
        if args.dependencies_only:
            output = args.output.resolve()
            if not output.is_relative_to(ROOT / 'ptmp') or not (output / 'identity.json').is_file():
                raise ValueError('--dependencies-only requires an existing frozen package under ptmp/')
            dependency = dependency_snapshot(args.source_root.resolve(), args.build_cache.resolve().parent, output)
            print(json.dumps({'dependencies': str(output / 'dependencies.json'),
                              'content_sha256': dependency['content_sha256']}, sort_keys=True))
            return
        identity = snapshot(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(json.dumps({'identity': str(args.output.resolve() / 'identity.json'),
                      'source_revision': identity['source_revision'],
                      'libraries': len(identity['libraries'])}, sort_keys=True))


if __name__ == '__main__':
    main()
