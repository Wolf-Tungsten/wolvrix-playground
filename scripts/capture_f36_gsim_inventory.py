"""Capture only the live GSIM R4 state and port inventory for F36."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from benchmark_f29_pass_trace import sha256, write_json_atomic
from benchmark_f30_gsim import ANSI, freeze_native
from benchmark_f30_pipeline import verified_input_request


GSIM_ROOT = Path(__file__).resolve().parents[1] / 'reference/gsim'
STAGE = 'RemoveDeadNodes3'
PASS = 'RemoveDeadNodes#2'


def inventory_table(path, schema):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        meta_line = stream.readline()
        header = stream.readline()
        digest.update(meta_line)
        digest.update(header)
        if not meta_line.startswith(b'#meta\t') or not header.strip():
            raise ValueError(f'missing inventory metadata or header: {path}')
        metadata = json.loads(meta_line.split(b'\t', 1)[1])
        if (metadata.get('schema'), metadata.get('stage'), metadata.get('pass_instance')) != (schema, STAGE, PASS):
            raise ValueError(f'unexpected inventory boundary or schema: {path}')
        expected_tabs = header.count(b'\t')
        rows = 0
        for line in stream:
            digest.update(line)
            if line.startswith(b'#footer\t'):
                footer = json.loads(line.split(b'\t', 1)[1])
                if footer.get('complete') is not True or footer.get('rowCount') != rows or stream.read(1):
                    raise ValueError(f'invalid inventory footer or row count: {path}')
                break
            if line.count(b'\t') != expected_tabs:
                raise ValueError(f'invalid inventory row {rows + 1}: {path}')
            rows += 1
        else:
            raise ValueError(f'missing inventory footer: {path}')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'rows': rows,
            'producer_version': metadata['producer_version']}


def capture(args, report):
    args.output.mkdir(parents=True, exist_ok=False)
    native, identity = freeze_native(args.binary, GSIM_ROOT, args.output)
    model = args.output / 'model'
    model.mkdir()
    command = [native['binary'], '--dir=' + str(model), '--stop-after-stage=' + STAGE,
               '--state-port-inventory=' + str(args.output), str(args.firrtl)]
    with (args.output / 'gsim.log').open('x', encoding='utf-8') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    _, sources = verified_input_request(args.firrtl, args.manifest)
    if (sha256(Path(native['binary'])) != native['sha256'] or sources != report['sources'] or
            sha256(args.manifest) != report['manifest_sha256']):
        raise ValueError('GSIM inputs or frozen binary changed during capture')
    report.update(provenance='execution-captured', binary=native['binary'], binary_sha256=native['sha256'],
                  native_identity=str(identity), native_identity_sha256=sha256(identity), command=command)
    return native['binary']


def recover(args, report):
    launch = args.recover_launch_log
    if 'ModuleNotFoundError: No module named \'check_state_port_inventory\'' not in launch.read_text():
        raise ValueError('recovery requires a launch log with the post-export parser import failure')
    oldest_output = min((args.output / name).stat().st_mtime_ns for name in ('gsim.log', 'states.tsv', 'actions.tsv'))
    if any(path.stat().st_mtime_ns > oldest_output for path in (args.binary, args.manifest, args.firrtl)):
        raise ValueError('recovery input, manifest or binary is newer than the original inventory')
    report.update(provenance='recovered', recovery_launch_log=str(launch),
                  recovery_launch_log_sha256=sha256(launch), binary_candidate=str(args.binary),
                  binary_candidate_sha256=sha256(args.binary))
    return str(args.binary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recover-launch-log', type=lambda value: Path(value).resolve())
    args = parser.parse_args()

    args.binary = args.binary.resolve()
    args.firrtl = args.firrtl.resolve()
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    request, sources = verified_input_request(args.firrtl, args.manifest)
    firrtl_sources = [row for row in sources if row['language'] == 'firrtl']
    if len(firrtl_sources) != 1:
        parser.error('manifest must identify the requested single FIRRTL input')
    if len(request.get('tops', [])) != 1:
        parser.error('manifest must select exactly one top')
    receipt = args.output / 'capture.json'
    if receipt.exists():
        parser.error('refusing to overwrite an existing F36 capture receipt')
    report = {'schema': 'wolvrix.f36.gsim-inventory-capture.v1', 'stage': STAGE, 'pass_instance': PASS,
              'top': request['tops'][0], 'input': str(args.firrtl),
              'input_sha256': firrtl_sources[0]['sha256'], 'manifest_sha256': sha256(args.manifest), 'sources': sources}
    binary = recover(args, report) if args.recover_launch_log else capture(args, report)
    log_path = args.output / 'gsim.log'
    log = ANSI.sub('', log_path.read_text(encoding='utf-8'))
    parser_threads = re.findall(r'\[Parser\] using (\d+) threads to parse ', log)
    if parser_threads != ['1'] or len(re.findall(r'^RemoveDeadNodes3 = \d+ ms$', log, re.MULTILINE)) != 1:
        raise ValueError(f'GSIM log lacks the single-thread parser or R4 completion evidence: {log_path}')
    version = subprocess.check_output([binary, '--version'], text=True).strip()
    tables = {name: inventory_table(args.output / f'{name}.tsv', f'gsim.f36.{name}.v1')
              for name in ('states', 'actions')}
    if any(version.splitlines()[0] != f"GSIM {table['producer_version']}" for table in tables.values()):
        raise ValueError('GSIM producer versions differ between binary and inventory tables')
    report.update(complete=True, version=version, parser_threads=1, tables=tables,
                  log=str(log_path), log_sha256=sha256(log_path))
    write_json_atomic(receipt, report)
    print(f"F36 GSIM inventory complete: {tables['states']['rows']} states, {tables['actions']['rows']} actions")


if __name__ == '__main__':
    main()
