"""Prepare private file-cache pages and audit native GrhSIM NUMA placement."""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import subprocess


def file_identity(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def runtime_plan(binary, reference, image, directory, cpu, node, env):
    """Resolve libraries on the execution host before making byte-identical copies."""
    directory = Path(directory).resolve()
    entries = []
    for role, source, relative in [('binary', binary, 'bin/emu'),
                                    ('reference', reference, 'ref/nemu.so'),
                                    ('image', image, 'image/workload.bin')]:
        entries.append(dict(role=role, source=file_identity(source),
                            destination=str(directory / relative)))
    libraries = {}
    ldd_logs = {}
    for source in [binary, reference]:
        output = subprocess.check_output(['ldd', str(source)], text=True, env=env)
        ldd_logs[str(source)] = output
        if 'not found' in output:
            raise ValueError('unresolved runtime library: ' + output)
        for name, path in re.findall(r'^\s*(\S+) => (/\S+) \(', output, re.M):
            if Path(name).name != name:
                raise ValueError('unsupported dependency name: ' + name)
            record = file_identity(path)
            if name in libraries and libraries[name] != record:
                raise ValueError('conflicting runtime libraries: ' + name)
            libraries[name] = record
    for name, source in sorted(libraries.items()):
        entries.append(dict(role='library', source=source,
                            destination=str(directory / 'lib' / name)))
    headers = subprocess.check_output(['readelf', '-lW', str(binary)], text=True, env=env)
    match = re.search(r'Requesting program interpreter: ([^\]]+)', headers)
    if not match:
        raise ValueError('native ELF interpreter not found')
    return dict(cpu=cpu, node=node, directory=str(directory), files=entries,
                interpreter=file_identity(match[1]), ldd=ldd_logs,
                policy='Private copies populated on the target CPU/node; native ELF loader retained')


def inspect_locality(maps_text, numa_text, plan):
    """Join VMA starts; separate anonymous/model pages from the system loader."""
    mappings = {}
    for line in maps_text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) >= 5:
            mappings[int(parts[0].split('-')[0], 16)] = dict(
                permissions=parts[1], path=parts[5] if len(parts) == 6 else '')
    owned = {entry['destination']: entry['role'] for entry in plan['files']}
    groups = {}
    external = {}
    seen = set()
    unknown_executable = set()
    for line in numa_text.splitlines():
        fields = line.split()
        if not fields:
            continue
        mapping = mappings.get(int(fields[0], 16))
        if mapping is None:
            continue  # Maps can change during startup between the two reads.
        path = mapping['path']
        nodes = {n: int(v) for n, v in re.findall(r'\bN(\d+)=(\d+)', line)}
        executable = 'x' in mapping['permissions']
        if path in owned:
            kind = owned[path]
            seen.add(path)
            target = groups
        elif not path or path in ('[heap]', '[stack]') or path.startswith('[anon'):
            kind, target = 'anonymous', groups
        else:
            kind, target = path, external
            if executable and path.startswith('/') and path != plan['interpreter']['path']:
                unknown_executable.add(path)
        entry = target.setdefault(kind, dict(pages={}, executable_pages={}, mappings=0))
        entry['mappings'] += 1
        for n, count in nodes.items():
            entry['pages'][n] = entry['pages'].get(n, 0) + count
            if executable:
                entry['executable_pages'][n] = entry['executable_pages'].get(n, 0) + count
    return dict(groups=groups, external=external, seen_files=sorted(seen),
                unknown_executable=sorted(unknown_executable))


def locality_errors(record, node):
    errors = []
    for kind, data in record['groups'].items():
        remote = {n: count for n, count in data['pages'].items() if n != str(node) and count}
        if remote:
            errors.append(dict(kind=kind, remote_pages=remote))
    if record['unknown_executable']:
        errors.append(dict(unmanaged_executable=record['unknown_executable']))
    return errors


def prepare(plan_path):
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text())
    if os.sched_getaffinity(0) != {plan['cpu']}:
        raise ValueError('runtime preparation must be pinned to the measurement CPU')
    directory = Path(plan['directory'])
    directory.mkdir(exist_ok=False)
    mapped = []
    files = []
    try:
        for entry in plan['files']:
            source = Path(entry['source']['path'])
            if file_identity(source) != entry['source']:
                raise ValueError('runtime input changed: ' + str(source))
            dest = Path(entry['destination'])
            dest.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as src, dest.open('xb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            dest.chmod(source.stat().st_mode & 0o777)
            actual = file_identity(dest)
            if (actual['sha256'], actual['bytes']) != (entry['source']['sha256'], entry['source']['bytes']):
                raise ValueError('runtime copy differs: ' + str(dest))
            entry['copy'] = actual
            stream = dest.open('rb')
            files.append(stream)
            region = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            mapped.append(region)
            # Fault every file page before timing; touching the last byte covers
            # a partial final page too. Keep mappings alive for the NUMA audit.
            checksum = sum(region[i] for i in range(0, len(region), mmap.PAGESIZE))
            entry['prefault_checksum'] = checksum + region[-1]
        maps = Path('/proc/self/maps').read_text()
        numa = Path('/proc/self/numa_maps').read_text()
        record = inspect_locality(maps, numa, plan)
        owned_errors = [e for e in locality_errors(record, plan['node'])
                        if e.get('kind') in {entry['role'] for entry in plan['files']}]
        expected = {entry['destination'] for entry in plan['files']}
        (directory / 'prefault.maps').write_text(maps)
        (directory / 'prefault.numa_maps').write_text(numa)
        plan['prefault'] = record
        plan['status'] = 'fail' if owned_errors or not expected.issubset(record['seen_files']) else 'pass'
        (directory / 'manifest.json').write_text(json.dumps(plan, indent=2) + '\n')
        if plan['status'] != 'pass':
            raise ValueError('runtime file prefault is not local: ' + str(owned_errors))
        print(json.dumps(dict(status='pass', cpu=plan['cpu'], node=plan['node'],
                              files=len(plan['files']))))
    finally:
        for region in mapped:
            region.close()
        for stream in files:
            stream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    prepare(parser.parse_args().plan)
