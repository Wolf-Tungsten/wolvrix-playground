"""Measure fourth-DCE same-name coverage and classify unmatched GRH Nodes."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path

from benchmark_f29_pass_trace import write_json_atomic
from f35_gsim_reference import GSIM_BUNDLES, load_frozen_reference
from semantic_node_exchange import HEADERS, KINDS, SCHEMA, decode_cell, encode_cell, integer


WORK = Path(__file__).resolve().parents[1] / 'ptmp/firrtl-ingest/F35'
ENDPOINT_SCHEMA = 'grh.semantic-node-endpoints.v2'
ENDPOINT_HEADER = (
    'node_id', 'role', 'value_id', 'value_generation', 'operation_id', 'operation_generation',
    'native_kind', 'width', 'signed', 'shape_json', 'logic_domain', 'source_width', 'source_signed',
    'source_shape_json', 'source_shape_field_depths_json', 'projection_json', 'source_bit_offset',
    'source_bit_width', 'evidence',
)
INDEX_SCHEMA = 'f35.unmatched-names.v1'
INDEX_HEADER = ('name', 'node_count')
BOUNDARY_KINDS = {'state_update', 'storage_read', 'storage_write', 'external_binding'}
AGGREGATE_KINDS = {
    'grh.concat', 'grh.arrayCreate', 'grh.replicate', 'grh.sliceStatic', 'grh.sliceDynamic', 'grh.sliceArray',
    'grh.combArrayUpdate',
}
EFFECT_KINDS = {'grh.systemTask', 'grh.dpicCall', 'grh.dpicImport', 'grh.blackbox', 'grh.instance', 'grh.xmrWrite'}
STATE_ROLES = {'register-current', 'register-next', 'clock', 'reset', 'memory-read-address', 'memory-storage'}


class Table:
    """Read a native inventory once, validating framing and hashing its exact bytes."""

    def __init__(self, path, stream, header):
        self.path = path
        self.stream = stream
        self.digest = sha256()
        self.count = 0
        self.footer = None
        self.metadata = self.read_json(self.read_line(), '#meta\t')
        self.header = header
        if self.read_line().split('\t') != list(header):
            raise ValueError(f'unexpected columns in {path}')

    def read_line(self):
        line = self.stream.readline()
        if not line.endswith(b'\n') or line.endswith(b'\r\n'):
            raise ValueError(f'missing or invalid line ending in {self.path}')
        self.digest.update(line)
        return line[:-1].decode('utf-8')

    def read_json(self, line, prefix):
        if not line.startswith(prefix):
            raise ValueError(f'missing {prefix.strip()} in {self.path}')
        value = json.loads(line[len(prefix):])
        if not isinstance(value, dict):
            raise ValueError(f'invalid {prefix.strip()} in {self.path}')
        return value

    def rows(self):
        while True:
            line = self.read_line()
            if line.startswith('#footer\t'):
                self.footer = self.read_json(line, '#footer\t')
                if self.footer.get('complete') is not True or self.footer.get('rowCount') != self.count:
                    raise ValueError(f'incomplete inventory {self.path}')
                if self.stream.read(1):
                    raise ValueError(f'rows follow footer in {self.path}')
                return
            values = line.split('\t')
            if len(values) != len(self.header):
                raise ValueError(f'invalid row in {self.path}')
            self.count += 1
            yield values

    def identity(self):
        if self.footer is None:
            raise ValueError(f'cannot identify incompletely read inventory {self.path}')
        return {
            'path': str(self.path), 'sha256': self.digest.hexdigest(),
            'row_count': self.count, 'metadata': self.metadata,
        }


@contextmanager
def open_table(path, header):
    with path.open('rb') as stream:
        yield Table(path, stream, header)


def native_nodes(table, engine):
    meta = table.metadata
    if meta.get('schema') != SCHEMA or meta.get('engine') != engine or meta.get('table') != 'nodes':
        raise ValueError(f'invalid {engine} Node inventory {table.path}')
    if engine == 'gsim':
        if meta.get('stage') != 'RemoveDeadNodes3' or meta.get('pass_instance') != 'RemoveDeadNodes#2':
            raise ValueError(f'expected GSIM fourth DCE inventory in {table.path}')
    elif meta.get('stage') not in ('after-dead-code-elim#3', 'post-fourth-dead-code-elim'):
        raise ValueError(f'expected GRH fourth DCE inventory in {table.path}')

    previous = -1
    for identifier, path, _ in table.rows():
        identifier = integer(identifier)
        if identifier <= previous:
            raise ValueError(f'Node IDs are not uniquely ordered in {table.path}')
        previous = identifier
        if path == r'\N':
            yield identifier, None
            continue
        tokens = json.loads(decode_cell(path))
        if not isinstance(tokens, list) or not tokens or any(not isinstance(part, str) or not part for part in tokens):
            raise ValueError(f'invalid Node path for {identifier} in {table.path}')
        yield identifier, '.'.join(tokens)
    if table.footer.get('nodeInventoryComplete') is not True:
        raise ValueError(f'incomplete Node inventory {table.path}')


def name_inventory(path, engine, reference=None):
    names, duplicates = set(), set()
    anonymous, matches, duplicate_rows = 0, 0, 0
    unmatched = {}
    with open_table(path, HEADERS['nodes']) as table:
        for identifier, name in native_nodes(table, engine):
            if name is None:
                anonymous += 1
            elif name in names:
                duplicates.add(name)
                duplicate_rows += 1
            else:
                names.add(name)
            if reference is not None:
                if name in reference:
                    matches += 1
                else:
                    unmatched[identifier] = name
        identity = table.identity()
    return names, unmatched, {
        **identity, 'anonymous_nodes': anonymous, 'distinct_names': len(names),
        'duplicate_names': len(duplicates), 'duplicate_rows_beyond_first': duplicate_rows,
        'matches': matches,
    }


def validate_grh_table(table, nodes, schema, table_name=None):
    meta, source = table.metadata, nodes['metadata']
    # A separate endpoint-only export can have a fresh session ID. The design
    # run and boundary must still match the R4 Node inventory.
    if (meta.get('engine') != 'grh' or meta.get('schema') != schema
            or any(not meta.get(key) or meta[key] != source.get(key) for key in ('run_id', 'stage'))):
        raise ValueError(f'different GRH R4 snapshot in {table.path}')
    if table_name and (meta.get('table') != table_name or
                       any(not meta.get(key) or meta[key] != source.get(key)
                           for key in ('graph_id', 'snapshot_id'))):
        raise ValueError(f'different GRH R4 snapshot in {table.path}')


def endpoint_shapes(path, nodes, unmatched):
    signatures = {}
    with open_table(path, ENDPOINT_HEADER) as table:
        validate_grh_table(table, nodes, ENDPOINT_SCHEMA)
        for identifier, role, _, _, operation, _, kind, width, *rest in table.rows():
            identifier = int(identifier)
            if identifier in unmatched:
                endpoint = (role, kind, int(width), rest[1] != '[]', rest[-1], int(operation) != 0)
                signatures.setdefault(identifier, set()).add(endpoint)
        identity = table.identity()
    if len(signatures) != len(unmatched):
        missing = next(identifier for identifier in unmatched if identifier not in signatures)
        raise ValueError(f'GRH R4 endpoint evidence missing for Node {missing} in {path}')
    return signatures, identity


def connection_shapes(path, nodes, unmatched):
    flags = {}
    with open_table(path, HEADERS['connections']) as table:
        validate_grh_table(table, nodes, SCHEMA, 'connections')
        for _, source, target, kind, resolution, _, _ in table.rows():
            if kind not in KINDS or resolution not in ('resolved', 'unresolved'):
                raise ValueError(f'invalid connection shape in {path}')
            source = None if source == r'\N' else int(source)
            target = int(target)
            for identifier, direction in ((source, 'out'), (target, 'in')):
                if identifier in unmatched:
                    counts = flags.setdefault(identifier, {})
                    key = f'{direction}:{kind}:{resolution}'
                    counts[key] = counts.get(key, 0) + 1
        identity = table.identity()
    return flags, identity


def classify(name, endpoints, connections):
    if name is None:
        return 'anonymous'
    roles = {role for role, *_ in endpoints}
    kinds = {kind for _, kind, *_ in endpoints}
    edge_kinds = {key.split(':')[1] for key in connections}
    if 'external_binding' in edge_kinds or kinds & EFFECT_KINDS or 'effect' in roles:
        return 'external-effects'
    if (edge_kinds & BOUNDARY_KINDS or roles & STATE_ROLES
            or any(kind.startswith(('grh.register', 'grh.latch')) for kind in kinds)):
        return 'state-and-storage'
    if kinds == {'input'}:
        return 'input-or-unanchored'
    if len(kinds) != 1:
        return 'mixed-endpoints'
    kind = next(iter(kinds))
    if kind == 'grh.assign':
        return 'assignments'
    if kind == 'grh.constant':
        return 'constants'
    if kind == 'grh.mux':
        return 'muxes'
    if kind in AGGREGATE_KINDS or any(aggregate for _, _, _, aggregate, *_ in endpoints):
        return 'slices-and-packing'
    return 'other-combinational'


def module_owner(name):
    if name is None:
        return ''
    # The flattened name may contain field selectors as well as module paths.
    # This is a grouping hint. The ingest query supplies the actual module.
    return name.rpartition('.')[0]


def sample_shape(endpoints, connections):
    kinds = '+'.join(sorted({kind for _, kind, *_ in endpoints}))
    operation_only = all(evidence == 'operation-only' for _, _, _, _, evidence, _ in endpoints)
    incoming = any(key.startswith('in:') for key in connections)
    outgoing = any(key.startswith('out:') for key in connections)
    return kinds, operation_only, incoming, outgoing


def classify_all(unmatched, endpoints, connections, sample_limit, last_seen=None):
    classes = {}
    for identifier, name in unmatched.items():
        native = endpoints[identifier]
        edges = connections.get(identifier, {})
        kind = classify(name, native, edges)
        info = classes.setdefault(kind, {
            'count': 0, 'native_shapes': Counter(), 'owners': Counter(), 'representatives': {},
        })
        shape, operation_only, incoming, outgoing = sample_shape(native, edges)
        owner = module_owner(name)
        info['count'] += 1
        info['native_shapes'][shape, operation_only, incoming, outgoing] += 1
        info['owners'][owner] += 1
        if last_seen is not None:
            boundary = last_seen.get(name, 'no-prior-same-name') if name is not None else 'anonymous'
            info.setdefault('gsim_last_seen', Counter())[boundary] += 1
        # Keep one first-encountered sample per native shape and owner.
        # Candidate ranks are based on the complete unmatched inventory.
        subgroup = (shape, operation_only, incoming, outgoing, owner)
        if subgroup not in info['representatives']:
            info['representatives'][subgroup] = identifier, name

    result = []
    for kind, info in sorted(classes.items(), key=lambda row: (-row[1]['count'], row[0])):
        shapes = info['native_shapes']
        owners = info['owners']
        representatives = info['representatives']
        ranked = sorted(representatives, key=lambda group: (-shapes[group[:4]], -owners[group[-1]], group))
        selected = []
        seen_shapes, seen_owners = set(), set()
        for diversify in (True, False):
            for group in ranked:
                if len(selected) == sample_limit:
                    break
                if group in selected or (diversify and (group[:4] in seen_shapes or group[-1] in seen_owners)):
                    continue
                selected.append(group)
                seen_shapes.add(group[:4])
                seen_owners.add(group[-1])
        samples = []
        for group in selected:
            identifier, name = representatives[group]
            shape, operation_only, incoming, outgoing, owner = group
            samples.append({
                'node_id': identifier, 'name': name, 'owner_name_prefix': owner,
                'native_shape': shape, 'operation_only': operation_only,
                'has_incoming_connections': incoming, 'has_outgoing_connections': outgoing,
                'shape_count': shapes[group[:4]], 'owner_count': owners[owner],
                'endpoints': [
                    {'role': role, 'native_kind': native_kind, 'width': width,
                     'aggregate': aggregate, 'evidence': evidence, 'has_operation': operation}
                    for role, native_kind, width, aggregate, evidence, operation
                    in sorted(endpoints[identifier])
                ],
                'connections': connections.get(identifier, {}),
            })
        record = {
            'category': kind, 'count': info['count'], 'fraction_of_unmatched': info['count'] / len(unmatched),
            'top_native_shapes': [
                {'native_shape': shape, 'operation_only': operation_only,
                 'has_incoming_connections': incoming, 'has_outgoing_connections': outgoing, 'count': count}
                for (shape, operation_only, incoming, outgoing), count in shapes.most_common(12)
            ],
            'samples': samples,
        }
        if last_seen is not None:
            record['gsim_last_seen'] = dict(info['gsim_last_seen'].most_common())
            for row in samples:
                row['gsim_last_seen'] = (last_seen.get(row['name'], 'no-prior-same-name')
                                         if row['name'] is not None else 'anonymous')
        result.append(record)
    return result


def read_index(path, gsim_identity):
    with open_table(path, INDEX_HEADER) as table:
        meta = table.metadata
        if meta.get('schema') != INDEX_SCHEMA or meta.get('gsim_sha256') != gsim_identity['sha256']:
            raise ValueError(f'unmatched index {path} uses a different GSIM reference')
        names = {}
        for name, count in table.rows():
            name, count = decode_cell(name), integer(count)
            if not name or name in names or count == 0:
                raise ValueError(f'invalid unmatched name multiplicity in {path}')
            names[name] = count
        if sum(names.values()) != meta.get('named_unmatched'):
            raise ValueError(f'named unmatched index total disagrees with metadata in {path}')
        return names, meta


def write_index(path, names, report):
    metadata = {
        'schema': INDEX_SCHEMA, 'gsim_sha256': report['gsim_nodes']['sha256'],
        'grh_sha256': report['grh_nodes']['sha256'], 'named_unmatched': sum(names.values()),
        'anonymous_nodes': report['grh_nodes']['anonymous_nodes'],
    }
    with path.open('x', encoding='utf-8') as out:
        out.write('#meta\t' + json.dumps(metadata) + '\n')
        out.write('\t'.join(INDEX_HEADER) + '\n')
        for name, count in sorted(names.items()):
            out.write(f'{encode_cell(name)}\t{count}\n')
        out.write('#footer\t' + json.dumps({'complete': True, 'rowCount': len(names)}) + '\n')


def last_seen_in_gsim(directory, gsim, unmatched_names):
    """Find the last pass's before-inventory containing each final unmatched name."""
    frozen = load_frozen_reference(directory)
    if frozen['files']['dce-3/after.nodes.tsv']['sha256'] != gsim['sha256']:
        raise ValueError('frozen history does not match the comparison GSIM R4 inventory')
    remaining = set(unmatched_names)
    seen = {}
    boundaries = [(bundle, f'{bundle}/before.nodes.tsv') for bundle in reversed(GSIM_BUNDLES)]
    for boundary, relative in boundaries:
        with open_table(directory / relative, HEADERS['nodes']) as table:
            # Native snapshots serialize a compact JSON array. With no escaping,
            # joining the components directly is equivalent to JSON decoding.
            for _, raw_name, _ in table.rows():
                if raw_name == r'\N':
                    continue
                if '\\' in raw_name or '", "' in raw_name:
                    name = '.'.join(json.loads(decode_cell(raw_name)))
                else:
                    name = raw_name[2:-2].replace('","', '.')
                if name in remaining:
                    seen[name] = boundary
                    remaining.remove(name)
            if (table.footer.get('nodeInventoryComplete') is not True or
                    table.identity()['sha256'] != frozen['files'][relative]['sha256']):
                raise ValueError(f'frozen Node inventory changed at {relative}')
        print(f'GSIM last-seen boundary before {boundary}: {len(seen):,} distinct unmatched names located', flush=True)
        if not remaining:
            break
    return seen


def compare(grh_nodes, gsim_nodes, grh_endpoints, grh_connections, *, sample_limit=3,
            gsim_history=None,
            unmatched_index=None, previous_index=None, previous_report=None):
    reference, _, gsim = name_inventory(gsim_nodes, 'gsim')
    _, unmatched, grh = name_inventory(grh_nodes, 'grh', reference)
    denominator, numerator = grh['row_count'], grh['matches']
    if not denominator:
        raise ValueError('GRH R4 inventory is empty')
    edges, connections_id = connection_shapes(grh_connections, grh, unmatched)
    endpoints, endpoints_id = endpoint_shapes(grh_endpoints, grh, unmatched)
    counts = Counter(name for name in unmatched.values() if name is not None)
    last_seen = last_seen_in_gsim(gsim_history, gsim, counts) if gsim_history else None
    classes = classify_all(unmatched, endpoints, edges, sample_limit, last_seen)
    if numerator + len(unmatched) != denominator or sum(row['count'] for row in classes) != len(unmatched):
        raise ValueError('unmatched classes do not partition GRH R4')
    report = {
        'numerator': numerator, 'denominator': denominator, 'unmatched': len(unmatched),
        'ratio': numerator / denominator, 'target_ratio': 199 / 200,
        'target_met': 200 * numerator >= 199 * denominator,
        'grh_nodes': grh, 'gsim_nodes': gsim, 'grh_endpoints': endpoints_id, 'grh_connections': connections_id,
        'classes': classes,
    }
    if previous_index:
        prior_counts, prior_meta = read_index(previous_index, gsim)
        eliminated = sum(count - counts.get(name, 0) for name, count in prior_counts.items()
                         if count > counts.get(name, 0))
        introduced = sum(count - prior_counts.get(name, 0) for name, count in counts.items()
                         if count > prior_counts.get(name, 0))
        report['unmatched_delta'] = {
            'eliminated_named_rows': eliminated, 'introduced_named_rows': introduced,
            'previous_anonymous_rows': prior_meta['anonymous_nodes'], 'current_anonymous_rows': grh['anonymous_nodes'],
        }
        # Against the same GSIM name set, a previously unmatched full name
        # cannot become a match. Candidate lineage still distinguishes a
        # legitimate deletion from an exact rename to an existing GSIM name.
    if previous_report:
        previous = json.loads(previous_report.read_text(encoding='utf-8'))
        if previous['gsim_nodes']['sha256'] != gsim['sha256'] or (
                previous_index and previous['grh_nodes']['sha256'] != prior_meta['grh_sha256']):
            raise ValueError('previous report and reference/index identities disagree')
        old_classes = {row['category']: row['count'] for row in previous['classes']}
        new_classes = {row['category']: row['count'] for row in classes}
        report['change_pp'] = 100 * (
            numerator * previous['denominator'] - previous['numerator'] * denominator
        ) / (denominator * previous['denominator'])
        report['previous_count_by_category'] = old_classes
        report['change_by_category'] = {
            category: new_classes.get(category, 0) - old_classes.get(category, 0)
            for category in sorted(new_classes.keys() | old_classes.keys())
        }
    if unmatched_index:
        write_index(unmatched_index, counts, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh-nodes', 'gsim-nodes', 'grh-endpoints', 'grh-connections', 'output'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve(), required=True)
    for name in ('unmatched-index', 'previous-index', 'previous-report', 'gsim-history'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve())
    parser.add_argument('--sample-limit', type=int, default=3)
    args = parser.parse_args()
    if args.sample_limit < 1:
        parser.error('--sample-limit must be positive')
    for output in (args.output, args.unmatched_index):
        if output is not None and (output == WORK or not output.is_relative_to(WORK)):
            parser.error('comparison artifacts must be under ptmp/firrtl-ingest/F35/')
    for output in (args.output, args.unmatched_index):
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
    report = compare(args.grh_nodes, args.gsim_nodes, args.grh_endpoints, args.grh_connections,
                     sample_limit=args.sample_limit, gsim_history=args.gsim_history, unmatched_index=args.unmatched_index,
                     previous_index=args.previous_index, previous_report=args.previous_report)
    write_json_atomic(args.output, report)
    print(f"GRH R4: {report['numerator']:,} / {report['denominator']:,} same-name "
          f"({report['ratio']:.5%}), {report['unmatched']:,} unmatched")
    for row in report['classes']:
        print(f"{row['category']:24} {row['count']:>10,} {row['fraction_of_unmatched']:8.2%}")


if __name__ == '__main__':
    main()
