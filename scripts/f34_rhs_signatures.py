r"""rhs-root-signature.v2, a read-only SemanticNodeExchange TSV sidecar.

The #meta/header/#footer and cell escaping follow semantic_node_exchange.
One row per live Node. name is the public qualified name (null for unnamed);
node_id is native and boundary-local. Those two columns identify the record
and are not comparison fields. Missing requested names have exists=false and
all other fields null in the ledger, with no synthetic row in the snapshot.

root_op preserves the GRH anchor's defining kind or GSIM assignTree[0]'s
opType (suffix :nodePtr for a native pointer). Only root_class is compared.
The classes are reference, array_index, sign_view, kSliceStatic, kConstant,
the explicitly mapped computational kinds, and other:<native>.
GRH skips same-type assign wrappers around internal, unbound, non-port
values, stopping at a named boundary or the first computation. A same-type
assign to a named operand is a reference, and a sign-only assign is a
sign_view. GSIM takes the operand of a sign cast when it is a direct nodePtr.
named_source records the direct name at that boundary, never the names
under a computation. constant_indices records array indices in operand/child
order, [] for no indices and null entries for dynamic or unsupported indices.
For example, kAssign(kSliceArray(bank, 1)) and a GSIM node pointer bank
with OP_INDEX_INT(1) both yield array_index, named_source=bank, indices=[1].

width, signed and shape use the GRH anchor's leaf width, sign and shape or
the GSIM Node's width, sign and dimensions. GSIM width and sign are unknown
at Init and SplitArray, before InferAllWidth. At InferAllWidth and later a
native negative width gives null width and sign. Unknown (TSV \U, ledger
JSON "unknown") is distinct from null (TSV \N, ledger JSON null).
predecessor_count counts distinct resolved named GRH dependency sources,
excluding separate state-update edges and operand slots marked clock/reset
events. GSIM uses native prev.size(). assignment_count is the anchor's
SSA definition count (0 or 1) or GSIM assignTree.size(). constant marks a
literal root after normalization.

GRH zero/multiple anchors have null anchor-derived fields. No particular
anchor is chosen. Two nulls compare equal; null versus a known value differs.
At a one-sided boundary only exists is compared. With both names present,
unknown fields are skipped. unknown_fields lists skips through the first
divergence or the final compared boundary. Duplicate requested qualified
names are rejected. Unnamed Nodes have no comparison key.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

from benchmark_f29_pass_trace import native_identity, sha256
from benchmark_f30_pipeline import verify_loaded_native, verify_package_identity
from benchmark_f33_performance import normalized_environment
from benchmark_xs_firrtl_ingest import request_from_manifest
from capture_f32_pipeline import action, native_rows
from capture_f34_pipeline import production_calls
from semantic_node_exchange import compact, decode_cell, encode_cell, integer


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F34/culprit-ledger'
SCHEMA = 'rhs-root-signature.v2'
TABLE = 'rhs-root-signatures'
FIELDS = ('exists', 'root_op', 'root_class', 'width', 'signed', 'shape', 'named_source',
          'constant_indices', 'predecessor_count', 'assignment_count', 'constant')
HEADER = ('name', 'node_id', *FIELDS)
LEDGER = ('name', 'cohort', 'divergence_boundary', 'culprit_pass',
          'grh_signature', 'gsim_signature', 'differing_fields', 'unknown_fields', 'disposition')
# Ordered equivalents from §8.5. SplitArray is additionally exportable on its
# own, before InferAllWidth. Both grouped GRH prefixes run the production order.
BOUNDARIES = {
    'B0': ('hier-flatten#0', 'Init'),
    'B1': ('split-static-array#0', 'InferAllWidth'),
    'P0': ('dead-code-elim#0', 'RemoveDeadNodes0'),
    'P1': ('expr-opt#0', 'ExprOpt'),
    'P2': ('used-bits#0', 'UsedBits'),
    'P3': ('split-nodes#0', 'SplitNodes'),
    'P4': ('dead-code-elim#1', 'RemoveDeadNodes1'),
    'Q1': ('constant-analysis#0', 'ConstantAnalysis'),
    'R0': ('dead-code-elim#2', 'RemoveDeadNodes2'),
    'R1': ('alias-analysis#0', 'AliasAnalysis'),
}
BOUNDARY_ALIASES = {'Q0': 'P4', 'Q2': 'R0'}
GSIM_STAGES = ('Init', 'SplitArray', *(stage for boundary, (_, stage) in BOUNDARIES.items() if boundary != 'B0'))
ABSENT = (False, *(None for _ in FIELDS[1:]))
UNKNOWN = object()
TYPE_FIELDS = ('width', 'signed')


def tsv_row(values):
    return '\t'.join(r'\U' if value is UNKNOWN else encode_cell(value) for value in values) + '\n'


def name_list(paths):
    names = {}
    for path in paths:
        match = re.fullmatch(r'cohort-([ABCD])\.tsv', path.name)
        cohort = match[1] if match else ''
        with path.open() as stream:
            for index, line in enumerate(stream):
                line = line.rstrip('\n')
                if index == 0 and line.split('\t', 1)[0] == 'name':
                    continue
                name = decode_cell(line.split('\t', 1)[0])
                if not name or '\n' in name or '\r' in name:
                    raise ValueError(f'invalid requested name in {path}:{index + 1}')
                cohorts = names.setdefault(name, set())
                if cohort:
                    cohorts.add(cohort)
    return names


def selection_file(output, paths):
    if not paths:
        return None
    path = output / 'requested-names.tsv'
    with path.open('x') as stream:
        stream.write('name\n')
        for name in sorted(name_list(paths)):
            stream.write(tsv_row((name,)))
    # Native selection receives unescaped one-name-per-line input.
    native = output / 'native-names.txt'
    with path.open() as stream, native.open('x') as out:
        next(stream)
        for line in stream:
            out.write(decode_cell(line.rstrip('\n')) + '\n')
    return native


def replacement_sources(cohorts, migration_index, inventory):
    """Use the frozen migration index's expression root, which can differ from to_id."""
    retired = set()
    for path in cohorts:
        with path.open() as stream:
            for row in csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE):
                if row['gsim_node_id'] != r'\N':
                    retired.add(integer(row['gsim_node_id']))
    with migration_index.open() as stream:
        migrations = csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE)
        roots = {integer(row['root_node']) for row in migrations
                 if integer(row['from_id']) in retired and row['root_node']}
    names = set()
    with inventory.open() as stream:
        meta = stream.readline()
        if not meta.startswith('#meta\t') or json.loads(meta[6:]).get('engine') != 'gsim':
            raise ValueError(f'invalid GSIM Node inventory in {inventory}')
        if stream.readline() != 'node_id\tname_path_json\tnative_name\n':
            raise ValueError(f'invalid Node inventory header in {inventory}')
        count = 0
        for line in stream:
            if line.startswith('#footer\t'):
                footer = json.loads(line[8:])
                if footer.get('complete') is not True or footer.get('rowCount') != count or stream.read(1):
                    raise ValueError(f'incomplete Node inventory in {inventory}')
                return names
            count += 1
            node, path, _ = line.split('\t', 2)
            if integer(node) in roots and (name := decode_cell(path)) is not None:
                names.add('.'.join(json.loads(name)))
    raise ValueError(f'missing Node inventory footer in {inventory}')


def boolean(value):
    if value not in ('true', 'false'):
        raise ValueError(f'invalid boolean {value!r}')
    return value == 'true'


def number_list(value, *, dynamic=False):
    values = json.loads(value)
    if not isinstance(values, list) or any(type(v) is not int and not (v is None and dynamic) for v in values):
        raise ValueError(f'invalid integer list {value!r}')
    return values


def parse_signature(cells, before_width_inference):
    parsers = (boolean, str, str, integer, boolean, number_list, str,
               lambda text: number_list(text, dynamic=True), integer, integer, boolean)
    signature = []
    for field, cell, parse in zip(FIELDS, cells, parsers):
        expected_unknown = before_width_inference and field in TYPE_FIELDS
        if (cell == r'\U') != expected_unknown:
            raise ValueError(f'invalid availability for {field}')
        if expected_unknown:
            signature.append(UNKNOWN)
        else:
            value = decode_cell(cell)
            signature.append(None if value is None else parse(value))
    if signature[0] is not True or signature[FIELDS.index('predecessor_count')] is None:
        raise ValueError('live signature is missing existence or predecessor count')
    return tuple(signature)


def read_table(path, engine, stage, wanted):
    rows = {}
    count = 0
    before_width_inference = engine == 'gsim' and stage in ('Init', 'SplitArray')
    with path.open() as stream:
        prefix, _, data = stream.readline().partition('\t')
        metadata = json.loads(data)
        if prefix != '#meta' or any(metadata.get(key) != value for key, value in
                                    dict(schema=SCHEMA, engine=engine, stage=stage, table=TABLE).items()):
            raise ValueError(f'invalid signature metadata in {path}')
        if tuple(stream.readline().rstrip('\n').split('\t')) != HEADER:
            raise ValueError(f'missing or reordered signature field in {path}')
        for line in stream:
            if line.startswith('#footer\t'):
                footer = json.loads(line.split('\t', 1)[1])
                if footer.get('complete') is not True or footer.get('rowCount') != count or stream.read(1):
                    raise ValueError(f'invalid signature footer in {path}')
                return rows, metadata
            count += 1
            cells = line.rstrip('\n').split('\t')
            if not line.endswith('\n') or len(cells) != len(HEADER) or not all(cells):
                raise ValueError(f'missing signature field in {path} at row {count}')
            name = decode_cell(cells[0])
            if name is None or name not in wanted:
                continue
            if name in rows:
                raise ValueError(f'ambiguous qualified name {name!r} in {path}')
            integer(cells[1])
            rows[name] = parse_signature(cells[2:], before_width_inference)
    raise ValueError(f'missing signature footer in {path}')


def differences(grh, gsim):
    if not grh[0] or not gsim[0]:
        return (['exists'] if grh[0] != gsim[0] else []), []
    differing, skipped = [], []
    for field, left, right in zip(FIELDS, grh, gsim):
        if field == 'root_op':
            continue
        if left is UNKNOWN or right is UNKNOWN:
            skipped.append(field)
        elif left != right:
            differing.append(field)
    return differing, skipped


def signature_json(signature):
    return compact({field: 'unknown' if value is UNKNOWN else value for field, value in zip(FIELDS, signature)})


def canonical_boundaries(text):
    given = tuple(text.split(','))
    boundaries = tuple(BOUNDARY_ALIASES.get(entry, entry) for entry in given)
    if tuple(entry for entry in BOUNDARIES if entry in boundaries) != boundaries or not boundaries:
        raise ValueError('provide distinct boundaries in production order')
    return boundaries


def validate_selection(directory, names):
    requested = directory / 'requested-names.tsv'
    if not requested.is_file():
        return 'all'
    absent = names.keys() - name_list([requested]).keys()
    if absent:
        raise ValueError(f'{len(absent)} comparison names outside {directory} selection (e.g. {min(absent)})')
    return 'selected-plus-direct-sources'


def compare(grh_dir, gsim_dir, boundaries, names, output):
    scope = (validate_selection(grh_dir, names), validate_selection(gsim_dir, names))
    for boundary in boundaries:
        for path in (grh_dir / boundary / (TABLE + '.tsv'),
                     gsim_dir / BOUNDARIES[boundary][1] / (TABLE + '.tsv')):
            if not path.is_file():
                raise ValueError(f'missing boundary {boundary}: {path}')
    pending = dict(names)
    unknown_by_name = {}
    temporary = output.with_suffix('.pending')
    try:
        with temporary.open('x') as ledger:
            ledger.write(tsv_row(LEDGER))
            for boundary in boundaries:
                gsim_stage = BOUNDARIES[boundary][1]
                grh, grh_meta = read_table(grh_dir / boundary / (TABLE + '.tsv'), 'grh', boundary, pending)
                gsim, gsim_meta = read_table(gsim_dir / gsim_stage / (TABLE + '.tsv'), 'gsim', gsim_stage, pending)
                if (grh_meta.get('scope'), gsim_meta.get('scope')) != scope:
                    raise ValueError(f'signature selection metadata mismatch at {boundary}')
                resolved = []
                for name, cohorts in pending.items():
                    left, right = grh.get(name, ABSENT), gsim.get(name, ABSENT)
                    fields, skipped = differences(left, right)
                    if skipped:
                        unknown_by_name[name] = ','.join(skipped)
                    # C/D attribute the first one-sided existence, even when
                    # earlier same-name signatures differ in other fields.
                    if fields and (not (cohorts & {'C', 'D'}) or fields == ['exists']):
                        ledger.write(tsv_row((name, ','.join(sorted(cohorts)), boundary, ' / '.join(BOUNDARIES[boundary]),
                                              signature_json(left), signature_json(right), ','.join(fields),
                                              unknown_by_name.pop(name, ''), '')))
                        resolved.append(name)
                for name in resolved:
                    del pending[name]
                print(f'{boundary} first divergences={len(resolved)}, pending={len(pending)}', flush=True)
            for name, cohorts in pending.items():
                ledger.write(tsv_row((name, ','.join(sorted(cohorts)), '', '', '', '', '',
                                      unknown_by_name.get(name, ''), '')))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def export_grh(args, selected):
    if args.package:
        package = verify_package_identity(args.package, args.package / 'identity.json')
        sys.meta_path[:] = [finder for finder in sys.meta_path
                            if not type(finder).__module__.startswith('_wolvrix_editable')]
        sys.path.insert(0, str(args.package))
    import wolvrix
    from wolvrix_xs_grhsim import firrtl_canonical_pipeline

    if args.package:
        verify_loaded_native(args.package, package, native_identity(wolvrix))
    prefix, window = production_calls(firrtl_canonical_pipeline(remove_singleton_state_axis=False))
    points = canonical_boundaries(args.boundaries)
    captures = {BOUNDARIES[point][0]: point for point in points}
    request = request_from_manifest(args.manifest)
    start = previous = time.monotonic()
    with wolvrix.Session() as session:
        session.log_level = 'error'
        session.diagnostics_raise_min_level = 'none'
        print('GRH begin ingest', flush=True)
        action(session.read_sources(**request, out_design='design.main', pipeline='ingest'), 'ingest')
        for name, logical, keep, options in prefix + window[:1]:
            print(f'GRH begin {logical}', flush=True)
            action(session.run_pass(name, design='design.main', keep_declared_symbols=keep, **options), logical)
            if logical in captures:
                point = captures[logical]
                started = time.monotonic()
                action(session.semantic_snapshot(design='design.main', stage=point, output=str(args.output / point),
                                                 rhs_only=True, rhs_names=str(selected) if selected else None), point)
                now = time.monotonic()
                print(f'GRH {point} export {now - started:.3f} s, interval {now - previous:.3f} s, '
                      f'elapsed {now - start:.3f} s, peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss} KiB',
                      flush=True)
                previous = now
                if point == points[-1]:
                    return
    raise ValueError('GRH export missed its final requested boundary')


def export_gsim(args, selected):
    stages = GSIM_STAGES if args.stage == 'all' else tuple(args.stage.split(','))
    if len(set(stages)) != len(stages) or any(stage not in GSIM_STAGES for stage in stages):
        raise ValueError('provide distinct GSIM stages from Init through AliasAnalysis')
    source_sha = sha256(args.firrtl)
    measured = os.environ.get('F34_RHS_MEASURE_GSIM') == '1'
    for stage in stages:
        point = args.output / stage
        point.mkdir()
        timing = point / 'timing.jsonl'
        if measured:
            from f30_resource_guard import GuardLimits, run_guarded
            preflight(point / 'preflight.log')
        command = [str(args.binary), '--dir=' + str(point), '--stop-after-stage=' + stage,
                   '--timing-output=' + str(timing), '--semantic-node-exchange=' + str(point),
                   '--semantic-node-exchange-mode=snapshot', '--semantic-node-exchange-stage=' + stage,
                   '--semantic-node-exchange-rhs=' + (str(selected) if selected else ''),
                   '--trace-input-sha256=' + source_sha, str(args.firrtl)]
        started = time.monotonic()
        with (point / 'gsim.log').open('w') as log:
            if measured:
                from benchmark_f31_dce import process_tree_sample
                # The private shell redirects the process, while the parent
                # keeps its Make log and guard evidence independent.
                wrapper = ['/bin/bash', '-c', 'cd "$1" && shift && exec "$@" >gsim.log 2>&1', 'gsim-run', str(point)]
                timed = ['/usr/bin/time', '-f', '%e\t%M', '-o', str(point / 'time-rss.tsv')]
                print(f'GSIM begin {stage}', flush=True)
                if run_guarded(wrapper + timed + command, point, GuardLimits(rss_bytes=120 * 1024**3),
                               sampler=process_tree_sample):
                    raise RuntimeError(f'GSIM resource guard failed at {stage}: {point / "guard.json"}')
            else:
                subprocess.run(command, cwd=point, stdout=log, stderr=subprocess.STDOUT, check=True)
        rows = native_rows(timing, 'gsim')
        if rows[-1]['stage'] != stage or not (point / (TABLE + '.tsv')).is_file():
            raise ValueError(f'GSIM failed to export and stop at {stage}')
        print(f'GSIM {stage} export {rows[-1]["wall_s"]:.3f} s, elapsed {time.monotonic() - started:.3f} s', flush=True)


def preflight(path, group=Path('/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service')):
    with path.open('a') as log:
        while True:
            memory = subprocess.check_output(['free', '-g'], text=True)
            available = int(next(row for row in memory.splitlines() if row.startswith('Mem:')).split()[-1])
            pressure = (group / 'memory.pressure').read_text()
            some = float(pressure.splitlines()[0].split()[1].split('=')[1])
            stat = [row for row in (group / 'memory.stat').read_text().splitlines()
                    if row.split()[0] in ('anon', 'file', 'active_file')]
            print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), memory.rstrip(), pressure.rstrip(), *stat,
                  sep='\n', file=log, flush=True)
            if available >= 120 and some < 5:
                print(f'available_gib={available} some_avg10={some:.2f} passed', file=log, flush=True)
                return
            print(f'Preflight waiting: {available} GiB available, some.avg10={some:.2f}', flush=True)
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    for engine in ('grh', 'gsim', 'compare', 'sources'):
        mode = modes.add_parser(engine)
        mode.add_argument('--output', type=lambda path: Path(path).resolve(), required=True)
        mode.add_argument('--names', type=Path, action='append', default=[], required=engine in ('compare', 'sources'))
        if engine in ('grh', 'compare'):
            mode.add_argument('--boundaries', default=','.join(BOUNDARIES))
    modes.choices['grh'].add_argument('--manifest', type=Path, required=True)
    modes.choices['grh'].add_argument('--package', type=lambda path: Path(path).resolve())
    modes.choices['gsim'].add_argument('--stage', required=True)
    for arg in ('binary', 'firrtl'):
        modes.choices['gsim'].add_argument('--' + arg, type=lambda path: Path(path).resolve(), required=True)
    for arg in ('grh', 'gsim'):
        modes.choices['compare'].add_argument('--' + arg, type=Path, required=True)
    for arg in ('migration-index', 'gsim-r0'):
        modes.choices['sources'].add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    if args.output == WORK or not args.output.is_relative_to(WORK):
        parser.error('outputs must be inside the F34 culprit-ledger')
    if args.mode == 'compare':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        compare(args.grh, args.gsim, canonical_boundaries(args.boundaries), name_list(args.names), args.output)
    elif args.mode == 'sources':
        names = replacement_sources(args.names, args.migration_index, args.gsim_r0)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            stream.write('name\n')
            for name in sorted(names):
                stream.write(tsv_row((name,)))
        print(f'GSIM replacement root names={len(names)}')
    else:
        normalized_environment()
        args.output.mkdir(parents=True)
        selected = selection_file(args.output, args.names)
        (export_grh if args.mode == 'grh' else export_gsim)(args, selected)


if __name__ == '__main__':
    main()
