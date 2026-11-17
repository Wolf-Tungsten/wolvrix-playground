"""Replay one narrow, conditional unsigned reconstruction lemma on small captures.

This standalone loader does not import the F32 reader or any normalizer. The
closed comparison's historical implementation is pinned separately from this
tool. A certificate concerns only current anchor expressions under paired,
arbitrary defined 0/1 boundary premises; it never upgrades the original reader.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SCHEMA = 'wolvrix.f32.reconstruction-certificates.v1'
RULE = 'unsigned-concat128-shl128-or256-eq-congruence.v1'
HISTORICAL_IMPLEMENTATION = {
    'compare_f32_semantics.py': 'cd4aa9ad9f0f203a5a576616a44d2a1754030ecec22358da9733344434ac12f7',
    'compare_f28_semantic_tree.py': '0007e3ca9135bf4548d0dbeb001ce642376e03a3d15b776b2aaafaa560378702',
    'semantic_bitvector.py': '9c4ac1486b8533bbfceb4be715195a15340ca3bc0fb3c334b8bbb41246487acf',
    'semantic_node_exchange.py': 'd837080317ed9ceabdda95c92ccec4719f600cf75571648a4e207f2582451acf',
}
ACCEPTED_IMPLEMENTATIONS = {
    'closed-v8-reader-cd4aa9ad': HISTORICAL_IMPLEMENTATION,
    'typed-index-reader-564c8a57': {
        'compare_f32_semantics.py': '564c8a57e290372bf30d72c497b8fba52d52103b0ed00d40129c5742ae978f95',
        'compare_f28_semantic_tree.py': '0007e3ca9135bf4548d0dbeb001ce642376e03a3d15b776b2aaafaa560378702',
        'semantic_bitvector.py': '9c4ac1486b8533bbfceb4be715195a15340ca3bc0fb3c334b8bbb41246487acf',
        'semantic_node_exchange.py': 'd837080317ed9ceabdda95c92ccec4719f600cf75571648a4e207f2582451acf',
    },
}
STAGES = {
    'grh': ('post-first-dead-code-elim', 'post-expr-opt', 'post-used-bits',
            'post-split-nodes', 'post-second-dead-code-elim'),
    'gsim': ('RemoveDeadNodes0', 'ExprOpt', 'UsedBits', 'SplitNodes', 'RemoveDeadNodes1'),
}
HEADERS = {
    'nodes.tsv': ('node_id', 'name_path_json', 'native_name'),
    'connections.tsv': ('connection_id', 'source_node_id', 'target_node_id', 'kind',
                        'resolution', 'candidate_sources_json', 'reason'),
    'bit-slices.tsv': ('before_node_id', 'after_node_id', 'low', 'width'),
    'node-details.tsv': ('node_id', 'native_kind', 'width', 'signed', 'shape_json', 'clock_node_id',
                         'state_pair_node_id', 'native_status', 'used_width', 'assignment_count'),
    'node-endpoints.tsv': ('node_id', 'role', 'value_id', 'value_generation', 'operation_id',
        'operation_generation', 'native_kind', 'width', 'signed', 'shape_json', 'logic_domain',
        'source_width', 'source_signed', 'source_shape_json', 'source_shape_field_depths_json',
        'projection_json', 'source_bit_offset', 'source_bit_width', 'evidence'),
}
MAX_FILE = 2 * 1024**2
MAX_DATABASE = 16 * 1024**2
MAX_TOTAL = 32 * 1024**2
MAX_NODES = 128
UNPROVED = {
    'reader_results_modified': False, 'four_state_behavior_proved': False,
    'initialization_proved': False, 'full_node_behavior_proved': False,
    'source_binding_proved': False, 'pass_transformation_preservation_proved': False,
    'paired_producer_equivalence_proved': False, 'semantic_acceptance': False,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def parse_json(body):
    return json.loads(body, object_pairs_hook=unique_object,
                      parse_constant=lambda value: require(False, 'nonfinite JSON constant: ' + value))


def stamp(path):
    require(not path.is_symlink() and path.is_file(), 'input must be a regular file: ' + str(path))
    info = path.stat()
    return {key: getattr(info, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


class FrozenInputs:
    def __init__(self):
        self.records = {}
        self.total = 0

    def read(self, path, limit=MAX_FILE, expected=None):
        path = Path(path).absolute()
        before = stamp(path)
        require(before['size'] <= limit, 'input exceeds small-capture byte limit: ' + str(path))
        if str(path) in self.records:
            record = self.records[str(path)]
            require(before == record['stat_before'], 'input changed between reads: ' + str(path))
            if expected is not None:
                require(isinstance(expected, dict) and Path(expected.get('path', '')).absolute() == path and
                        expected.get('sha256') == record['sha256'] and expected.get('bytes') == record['bytes'],
                        'frozen native artifact path/hash/bytes mismatch: ' + str(path))
            return path.read_bytes()
        self.total += before['size']
        require(self.total <= MAX_TOTAL, 'combined inputs exceed small-capture byte limit')
        body = path.read_bytes()
        require(stamp(path) == before, 'input changed during read: ' + str(path))
        record = {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                  'stat_before': before}
        if expected is not None:
            require(isinstance(expected, dict) and
                    Path(expected.get('path', '')).absolute() == path and
                    expected.get('sha256') == record['sha256'] and expected.get('bytes') == len(body),
                    'frozen native artifact path/hash/bytes mismatch: ' + str(path))
        self.records[str(path)] = record
        return body

    def json(self, path, expected=None):
        value = parse_json(self.read(path, expected=expected))
        require(isinstance(value, dict), 'JSON input must be an object')
        return value

    def verify(self):
        for record in self.records.values():
            path = Path(record['path'])
            require(stamp(path) == record['stat_before'], 'input stat changed during proof: ' + str(path))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            require(digest == record['sha256'], 'input hash changed during proof: ' + str(path))
            record.update(stat_after=stamp(path), sha256_after=digest)
            require(record['stat_after'] == record['stat_before'], 'input changed during final hash')


def integer(value):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]*', value) is not None,
            'invalid native integer')
    result = int(value)
    require(result <= 2**63 - 1, 'native integer out of range')
    return result


def boolean(value):
    require(value in ('true', 'false', '0', '1'), 'invalid native boolean')
    return value in ('true', '1')


def decode_cell(value):
    if value == r'\N':
        return None
    output, index = [], 0
    escapes = {'\\': '\\', 't': '\t', 'n': '\n', 'r': '\r'}
    while index < len(value):
        item = value[index]
        index += 1
        if item == '\\':
            require(index < len(value) and value[index] in escapes, 'invalid TSV escape')
            item = escapes[value[index]]
            index += 1
        output.append(item)
    return ''.join(output)


def table(frozen, path, artifact, engine, stage, node_meta=None):
    body = frozen.read(path, expected=artifact)
    lines = body.decode('utf-8').splitlines(keepends=True)
    require(3 <= len(lines) <= 4099 and all(line.endswith('\n') and '\r' not in line for line in lines),
            'incomplete, oversized or malformed native table')
    require(lines[0].startswith('#meta\t') and lines[-1].startswith('#footer\t'), 'incomplete native table')
    meta, footer = parse_json(lines[0][6:]), parse_json(lines[-1][8:])
    columns = HEADERS[path.name]
    require(lines[1] == '\t'.join(columns) + '\n', 'unsupported native table columns')
    schema = {'node-endpoints.tsv': 'grh.semantic-node-endpoints.v2',
              'bit-slices.tsv': 'semantic-node-bit-slices.v1'}.get(path.name, 'semantic-node-exchange.v1')
    require(meta.get('schema') == schema and meta.get('engine') == engine and
            meta.get('stage') == STAGES[engine][stage], 'mixed native table identity/schema')
    if node_meta is not None:
        for key in ('run_id', 'snapshot_id'):
            require(meta.get(key) == node_meta[key], 'mixed native snapshot identity')
        if path.name in ('connections.tsv', 'node-details.tsv'):
            for key in ('graph_id', 'exchange_session_id'):
                require(meta.get(key) == node_meta[key], 'mixed native graph/session identity')
    table_name = {'nodes.tsv': 'nodes', 'connections.tsv': 'connections', 'node-details.tsv': 'node-details'}
    if path.name in table_name:
        require(meta.get('table') == table_name[path.name], 'wrong native table kind')
    if path.name == 'node-details.tsv':
        require(meta.get('detail_schema') == 'gsim.node-details.v1', 'unsupported native details schema')
    rows = []
    for line in lines[2:-1]:
        fields = line[:-1].split('\t')
        require(not line.startswith('#') and len(fields) == len(columns), 'invalid native table row')
        rows.append(dict(zip(columns, map(decode_cell, fields))))
    require(footer.get('complete') is True and type(footer.get('rowCount')) is int and
            footer['rowCount'] == len(rows), 'incomplete native table footer/count')
    if path.name == 'nodes.tsv':
        require(footer.get('nodeInventoryComplete') is True and len(rows) <= MAX_NODES,
                'native Node inventory incomplete or exceeds small-capture limit')
        ids = [integer(row['node_id']) for row in rows]
        require(ids == sorted(set(ids)), 'duplicate or unsorted native Node identities')
    return {'rows': rows, 'metadata': meta, 'footer': footer}


def load_capture(frozen, directory, engine, checkpoint):
    summary_path = directory / 'summary.json'
    capture = frozen.json(summary_path)
    require(capture.get('schema') == 'wolvrix.f32.pipeline-capture.v1' and
            capture.get('engine') == engine and capture.get('status') == 'completed' and
            capture.get('source') == 'raw-firrtl' and capture.get('trace_enabled') is False and
            capture.get('trace_validation') is False and capture.get('full_structure') is True,
            'requires completed native full-structure raw-FIRRTL F32 capture')
    require(re.fullmatch('[0-9a-f]{64}', capture.get('input_sha256', '')) is not None,
            'capture lacks original input identity')
    recorded = checkpoint['capture_summaries'][engine]
    require(recorded == {'path': str(directory), 'sha256': frozen.records[str(summary_path)]['sha256']},
            'capture summary identity differs from closed comparison')
    require(set(capture.get('snapshots', {})) == {f'P{i}' for i in range(5)}, 'requires five captured boundaries')
    loaded, run, snapshots = {}, None, set()
    for stage in range(5):
        key = f'P{stage}'
        snapshot = capture['snapshots'][key]
        base = directory / key
        require(snapshot.get('directory') == str(base) and snapshot.get('stage') == STAGES[engine][stage],
                'capture snapshot path/order mismatch')
        artifacts = snapshot.get('artifacts', {})
        nodes = table(frozen, base / 'nodes.tsv', artifacts.get('nodes.tsv'), engine, stage)
        meta = nodes['metadata']
        require(all(isinstance(meta.get(field), str) and meta[field] for field in
                    ('run_id', 'graph_id', 'exchange_session_id', 'snapshot_id')), 'missing native identity')
        require(run in (None, meta['run_id']) and meta['snapshot_id'] not in snapshots,
                'requires distinct snapshots of one native run')
        require(meta.get('input_identity', {}).get('sha256') in (None, capture['input_sha256']),
                'native table original input identity mismatch')
        run = meta['run_id']
        snapshots.add(meta['snapshot_id'])
        tables = {'nodes.tsv': nodes}
        for name in ('connections.tsv', 'bit-slices.tsv',
                     'node-endpoints.tsv' if engine == 'grh' else 'node-details.tsv'):
            tables[name] = table(frozen, base / name, artifacts.get(name), engine, stage, meta)
        expected = {'run_id': run, 'snapshot_id': meta['snapshot_id'], 'nodes': len(nodes['rows']),
                    'connections': len(tables['connections.tsv']['rows']),
                    'coverage': tables['connections.tsv']['footer'].get('connectionCoverage')}
        require(checkpoint['snapshots'][engine][key] == expected, 'checkpoint/native inventory mismatch')
        structure = Path(snapshot.get('structure', ''))
        require(structure.is_absolute(), 'native structure path must be absolute')
        frozen.read(structure, expected=artifacts.get('structure'))
        loaded[stage] = {'tables': tables, 'structure': structure}
    return capture, loaded


def identities(rows, key='id', limit=4096):
    require(isinstance(rows, list) and len(rows) <= limit, 'missing or oversized native structure inventory')
    result = {}
    for row in rows:
        require(isinstance(row, dict) and type(row.get(key)) is int and row[key] > 0 and row[key] not in result,
                'duplicate or invalid native identity')
        result[row[key]] = row
    return result


def grh_structure(frozen, record):
    native = frozen.json(record['structure'])
    require(native.get('formatVersion') == 5 and len(native.get('graphs', [])) == 1, 'requires one native GRH v5 graph')
    graph = native['graphs'][0]
    tree = graph.get('semanticTree', {})
    require(tree.get('namesFlattened') is True and isinstance(tree.get('boundaryUses'), list),
            'requires flat native SemanticTree with boundary uses')
    paths = identities(tree.get('paths'), limit=MAX_NODES)
    require(len(paths) == 1 and type(tree.get('rootPath')) is int and tree['rootPath'] in paths and
            type(paths[tree['rootPath']].get('parent')) is int and
            paths[tree['rootPath']]['parent'] == 0, 'requires single flattened root path')
    nodes = identities(tree.get('nodes'), limit=MAX_NODES)
    inventory = {integer(row['node_id']) for row in record['tables']['nodes.tsv']['rows']}
    require(set(nodes) == inventory and all(type(row.get('parent')) is int and row['parent'] == tree['rootPath']
                                          for row in nodes.values()),
            'GRH structure/native Node inventory mismatch')
    values, ops = identities(graph.get('vals')), identities(graph.get('ops'))
    producers, owners = {}, {}
    for op in ops.values():
        require(isinstance(op.get('in'), list) and isinstance(op.get('out'), list) and
                all(type(item) is int and item in values for item in op['in'] + op['out']),
                'invalid native GRH operation values')
        for value in op['out']:
            require(value not in producers, 'duplicate native GRH value producer')
            producers[value] = op
    for node in nodes.values():
        for field, available in (('ops', ops), ('anchors', values)):
            members = node.get(field)
            require(isinstance(members, list) and all(type(item) is int and item in available for item in members)
                    and len(set(members)) == len(members), 'incomplete native GRH Node membership')
        for op in node['ops']:
            require(op not in owners, 'GRH operation has multiple owners')
            owners[op] = node['id']
    for use in tree['boundaryUses']:
        require(isinstance(use, dict) and
                all(type(use.get(key)) is int for key in ('source', 'target', 'value', 'user', 'operandIndex')) and
                use['source'] in nodes and use['target'] in nodes and use['value'] in values and
                0 <= use['user'] <= 2**32 - 1 and 0 <= use['operandIndex'] <= 2**32 - 1 and use.get('kind') == 'data',
                'incomplete or unsupported native boundary use')
        if use['user'] == 0:
            require(use['operandIndex'] == 2**32 - 1, 'malformed generic native boundary slot')
        else:
            require(use['user'] in ops and use['operandIndex'] < len(ops[use['user']]['in']) and
                    ops[use['user']]['in'][use['operandIndex']] == use['value'] and
                    owners.get(use['user']) == use['target'], 'invalid native boundary operation/slot reference')
    return tree, nodes, values, producers


def native_type(value, width, engine):
    if engine == 'grh':
        require(type(value.get('w')) is int and value['w'] == width and value.get('sgn') is False and
                value.get('shape', []) == [] and value.get('type') == 'logic' and
                value.get('domain') in ('2state', '4state'), 'unsupported GRH unsigned scalar type')
        return {'width': width, 'signed': False, 'shape': [], 'logic_domain': value['domain']}
    require(type(value.get('width')) is int and value['width'] == width and
            type(value.get('sign')) in (bool, int) and value['sign'] == 0 and value.get('dimension') == [],
            'unsupported GSIM unsigned scalar type')
    return {'width': width, 'signed': False, 'shape': []}


def sidecar_type(record, identifier, width, engine, expected_domain=None):
    name = 'node-endpoints.tsv' if engine == 'grh' else 'node-details.tsv'
    rows = [row for row in record['tables'][name]['rows'] if integer(row['node_id']) == identifier]
    require(len(rows) == 1, 'requires unique native Node type sidecar row')
    row = rows[0]
    require(integer(row['width']) == width and boolean(row['signed']) is False and
            parse_json(row['shape_json']) == [], 'native structure/type sidecar mismatch')
    if engine == 'grh':
        require(row['role'] == 'value' and integer(row['value_id']) > 0 and
                row['logic_domain'] == expected_domain, 'unsupported GRH native anchor type')
    else:
        require(row['clock_node_id'] is None and row['state_pair_node_id'] is None and
                row['native_kind'] in ('NODE_INP', 'NODE_OUT', 'NODE_OTHERS'), 'stateful GSIM boundary unsupported')
    return row


def gsim_structure(frozen, record):
    native = frozen.json(record['structure'])
    require(native.get('nodeStructureSchema') == 'gsim.node-structure.v1' and
            native.get('nodeStructureComplete') is True and native.get('assignmentOrder') == 'native-vector-order'
            and native.get('memoryInventoryComplete') is True and native.get('memories') == [],
            'requires complete native GSIM structure without memories')
    nodes = identities(native.get('nodes'), limit=MAX_NODES)
    require(set(nodes) == {integer(row['node_id']) for row in record['tables']['nodes.tsv']['rows']},
            'GSIM structure/native Node inventory mismatch')
    return nodes


def pair(db, stage, grh):
    rows = db.execute('SELECT gsim FROM pairs WHERE stage=? AND grh=?', (stage, grh)).fetchall()
    require(len(rows) == 1 and type(rows[0][0]) is int, 'missing or ambiguous actual boundary pair')
    return rows[0][0]


def typed_node(node, width, record):
    native_type(node, width, 'gsim')
    require(node.get('type') in ('NODE_INP', 'NODE_OUT', 'NODE_OTHERS') and
            node.get('status') == 'VALID_NODE' and node.get('isClock') is False and node.get('clockId') == -1 and
            node.get('asReset') == 0 and isinstance(node.get('assignTrees'), list) and
            all(field in node and node[field] is None for field in
                ('valTree', 'resetTree', 'resetCond', 'resetVal', 'memTree')), 'incomplete or stateful GSIM Node')
    sidecar = sidecar_type(record, node['id'], width, 'gsim')
    require(sidecar['native_kind'] == node['type'] and
            integer(sidecar['assignment_count']) == len(node['assignTrees']), 'GSIM assignment/type sidecar mismatch')


def proof(frozen, db, grh_record, gsim_record, stage, grh_id, gsim_id):
    require(pair(db, stage, grh_id) == gsim_id, 'target is not the actual comparison pair')
    original = db.execute('SELECT status,reason,gsim FROM structural WHERE stage=? AND grh=?',
                          (stage, grh_id)).fetchall()
    require(original == [('unverified', 'nonidentical_expression_exceeds_exhaustive_bit_budget', gsim_id)],
            'target is not the supported historical reader gap')
    tree, nodes, values, producers = grh_structure(frozen, grh_record)
    native_nodes = gsim_structure(frozen, gsim_record)
    require(grh_id in nodes and gsim_id in native_nodes, 'missing target native Node')
    output = nodes[grh_id]
    require(len(output['anchors']) == 1, 'requires one current output anchor')
    anchor = output['anchors'][0]
    native_type(values[anchor], 1, 'grh')

    def operation(value, kind, arity, width):
        native_type(values[value], width, 'grh')
        op = producers.get(value, {})
        require(op.get('kind') == kind and len(op.get('in', [])) == arity and op.get('out') == [value]
                and op.get('attrs', {}) == {} and op.get('id') in output['ops'], 'unsupported GRH anchor expression')
        return op

    assign = operation(anchor, 'kAssign', 1, 1)
    equal = operation(assign['in'][0], 'kEq', 2, 1)
    concat = operation(equal['in'][0], 'kConcat', 2, 256)
    require(set(output['ops']) == {assign['id'], equal['id'], concat['id']} and len(output['ops']) == 3,
            'output owned-operation inventory differs from exact anchor expression')
    roles = (('H', concat['in'][0], concat['id'], 0, 128),
             ('L', concat['in'][1], concat['id'], 1, 128),
             ('C', equal['in'][1], equal['id'], 1, 256))
    bindings = {}
    for role, value, user, slot, width in roles:
        value_type = native_type(values[value], width, 'grh')
        uses = [use for use in tree['boundaryUses'] if use['target'] == grh_id and use['value'] == value and
                ((use['user'] == user and use['operandIndex'] == slot) or
                 (role == 'C' and use['user'] == 0 and use['operandIndex'] == 2**32 - 1))]
        require(len(uses) == 1, 'missing or ambiguous actual ' + role + ' operand-slot boundary')
        use = uses[0]
        source = use['source']
        require(source != grh_id and nodes[source]['anchors'] == [value], 'boundary source lacks exact native anchor')
        native_id = pair(db, stage, source)
        require(native_id in native_nodes and native_id != gsim_id, 'missing actual paired native boundary')
        typed_node(native_nodes[native_id], width, gsim_record)
        sidecar = sidecar_type(grh_record, source, width, 'grh', value_type['logic_domain'])
        bindings[role] = {'grh_node': source, 'gsim_node': native_id, 'compact_value': value,
                          'type': value_type, 'grh_boundary_use': dict(use),
                          'physical_type_sidecar': sidecar}
    require(sum(use['target'] == grh_id for use in tree['boundaryUses']) == 3,
            'requires complete exact three-slot incoming boundary structure')
    require(len({binding['grh_node'] for binding in bindings.values()}) == 3 and
            len({binding['gsim_node'] for binding in bindings.values()}) == 3,
            'requires three distinct paired boundary identities')
    sidecar_type(grh_record, grh_id, 1, 'grh', values[anchor]['domain'])
    native_output = native_nodes[gsim_id]
    typed_node(native_output, 1, gsim_record)
    require(len(native_output['assignTrees']) == 1, 'requires exactly one complete native output assignment')
    assignment = native_output['assignTrees'][0]
    entries = assignment.get('nodes')
    require(isinstance(entries, list) and len(entries) == 7, 'incomplete or unsupported GSIM expression inventory')
    expressions, native_ids = {}, set()
    for entry in entries:
        require(isinstance(entry, dict) and type(entry.get('id')) is int and entry['id'] >= 0 and
                entry['id'] not in expressions and type(entry.get('nativeId')) is int and entry['nativeId'] > 0 and
                entry['nativeId'] not in native_ids, 'duplicate or invalid GSIM expression identity')
        expressions[entry['id']] = entry
        native_ids.add(entry['nativeId'])
    visited = set()

    def expression(identifier, op, width, arity, boundary=None, shift=False):
        require(type(identifier) is int and identifier in expressions and identifier not in visited,
                'missing, shared or cyclic native expression')
        visited.add(identifier)
        entry = expressions[identifier]
        require(entry.get('op') == op and type(entry.get('opcode')) is int and
                entry['opcode'] == {'OP_EQ': 11, 'OP_OR': 16, 'OP_SHL': 30, 'OP_EMPTY': 0}[op]
                and type(entry.get('width')) is int and entry['width'] == width and
                type(entry.get('sign')) in (bool, int) and entry['sign'] == 0 and
                entry.get('memoryNodeId', 'missing') is None and entry.get('isClock') == 0 and
                entry.get('reset') == 0 and entry.get('strVal') == '' and
                entry.get('values') == ([128] if shift else []) and
                isinstance(entry.get('children'), list) and len(entry['children']) == arity and
                entry.get('nodeId', 'missing') == boundary and
                (boundary is None or type(entry['nodeId']) is int), 'unsupported typed GSIM expression/operand identity')
        require(not shift or type(entry['values'][0]) is int, 'static native shift must be an integer')
        return entry

    eq = expression(assignment.get('root'), 'OP_EQ', 1, 2)
    reconstruction = expression(eq['children'][0], 'OP_OR', 256, 2)
    c = expression(eq['children'][1], 'OP_EMPTY', 256, 0, bindings['C']['gsim_node'])
    shifted = expression(reconstruction['children'][0], 'OP_SHL', 256, 1, shift=True)
    low = expression(reconstruction['children'][1], 'OP_EMPTY', 128, 0, bindings['L']['gsim_node'])
    high = expression(shifted['children'][0], 'OP_EMPTY', 128, 0, bindings['H']['gsim_node'])
    lvalue = expression(assignment.get('lvalue'), 'OP_EMPTY', 1, 0, gsim_id)
    require(visited == set(expressions), 'unreachable native expression inventory')
    for role, entry in (('H', high), ('L', low), ('C', c)):
        bindings[role]['gsim_expression'] = {'id': entry['id'], 'nativeId': entry['nativeId'], 'nodeId': entry['nodeId']}

    # Deterministic typed lane replay. Names and compact Value IDs are never
    # source identities; paired SemanticIds name the independent free vectors.
    def lanes(role, width):
        binding = bindings[role]
        return [(binding['grh_node'], binding['gsim_node'], bit) for bit in range(width)]

    high_lanes, low_lanes, c_lanes = lanes('H', 128), lanes('L', 128), lanes('C', 256)
    grh_lanes = low_lanes + high_lanes
    shifted_lanes = [None] * 128 + high_lanes
    extended_low_lanes = low_lanes + [None] * 128
    gsim_lanes = []
    for upper, lower in zip(shifted_lanes, extended_low_lanes):
        require(upper is None or lower is None, 'OR operands overlap in typed reconstruction')
        gsim_lanes.append(lower if upper is None else upper)
    require(grh_lanes == gsim_lanes and len(c_lanes) == len(grh_lanes) == 256, 'typed lane lemma failed')
    witness = json.dumps({'grh': grh_lanes, 'gsim': gsim_lanes, 'C': c_lanes}, separators=(',', ':')).encode()
    return {'boundary': f'P{stage}', 'grh_node': grh_id, 'gsim_node': gsim_id,
        'status': 'conditional_anchor_expression_proved', 'rule': RULE,
        'reader_result': {'status': original[0][0], 'reason': original[0][1]},
        'premise': 'For each listed pair, corresponding bits of the current H128/L128/C256 boundaries are equal arbitrary defined 0/1 values; distinct pairs remain independent.',
        'boundary_bindings': bindings,
        'grh_operations': {'assign': assign, 'eq': equal, 'concat': concat, 'anchor': anchor},
        'gsim_expression_locators': {role: {'id': entry['id'], 'nativeId': entry['nativeId']}
            for role, entry in (('eq', eq), ('or', reconstruction), ('shl', shifted), ('lvalue', lvalue))},
        'lemma_replay': {'lane_count': 256, 'lane_witness_sha256': hashlib.sha256(witness).hexdigest(),
            'low_range': [0, 127], 'high_range': [128, 255], 'shift': 128,
            'rules': ['concat L then H in ascending bit order', 'unsigned zero extension',
                      'static left shift 128', 'disjoint bitwise OR with zero', 'Eq congruence on same C256',
                      'type-preserving assignment']}, **UNPROVED}


def closed_database(path):
    require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
            'comparison database has SQLite sidecars; requires completed and closed database')


def prove(comparison, grh, gsim, output, targets):
    comparison, grh, gsim = map(lambda path: Path(path).absolute(), (comparison, grh, gsim))
    output = Path(output).resolve()
    require(output.is_relative_to(ROOT / 'ptmp') and not output.exists(), 'output must be a new directory under repository ptmp')
    require(1 <= len(targets) <= 6 and len(set(targets)) == len(targets) and
            all(type(stage) is int and stage in (3, 4) and type(left) is int and left > 0 and type(right) is int and right > 0
                for stage, left, right in targets), 'requires 1..6 distinct explicit P3/P4 Node pairs')
    output.mkdir(parents=True)
    frozen = FrozenInputs()
    report = {'schema': SCHEMA, 'status': 'unverified', 'complete': False, 'certificates': [],
              'comparison_implementation_group': None, **UNPROVED}
    try:
        own_path = Path(__file__).resolve()
        own_sha = hashlib.sha256(frozen.read(own_path)).hexdigest()
        require(own_sha == LOADED_SOURCE_SHA256, 'verifier source changed since module load')
        report['proof_implementation'] = {'standalone_loader_and_lemma': str(own_path), 'sha256': own_sha,
                                           'normalizer_called': False, 'reader_called': False}
        summary = frozen.json(comparison / 'summary.json')
        inputs = frozen.json(comparison / 'inputs.json')
        require(summary.get('schema') == 'wolvrix.f32.semantic-comparison.v1' and
                summary.get('status') == 'analyzed' and summary.get('complete') is True and
                summary.get('full_native_structure_compared') is True and
                inputs.get('schema') == 'wolvrix.f32.comparison-checkpoint.v1' and
                inputs.get('inventory_complete') is True and summary.get('snapshots') == inputs.get('snapshots'),
                'requires completed comparison with complete inventory/structure checkpoint')
        implementation_group = next((name for name, identity in ACCEPTED_IMPLEMENTATIONS.items()
                                     if inputs.get('proof_implementation') == identity), None)
        require(implementation_group is not None,
                'unsupported historical reader/dependency hashes: no exact approved identity group')
        report['comparison_implementation_group'] = implementation_group
        database = comparison / 'comparison.sqlite'
        require(summary.get('comparison_database') == str(database), 'comparison database path mismatch')
        closed_database(database)
        frozen.read(database, MAX_DATABASE)
        frozen.read(comparison / 'differences.jsonl')
        left_capture, left = load_capture(frozen, grh, 'grh', inputs)
        right_capture, right = load_capture(frozen, gsim, 'gsim', inputs)
        require(left_capture['input_sha256'] == right_capture['input_sha256'] == summary.get('input_sha256'),
                'capture original input identity mismatch')
        certificates, failures = [], []
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            for stage, left_id, right_id in targets:
                try:
                    certificates.append(proof(frozen, db, left[stage], right[stage], stage, left_id, right_id))
                except (ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as error:
                    failures.append({'boundary': f'P{stage}', 'grh_node': left_id, 'gsim_node': right_id,
                                     'status': 'unverified', 'reason': str(error)})
        report.update(status='conditional_anchor_expressions_proved' if not failures else 'unverified',
                      complete=True, certificates=certificates if not failures else [], failures=failures,
                      historical_comparison_implementation=inputs['proof_implementation'],
                      historical_comparison_implementation_is_current_code_claim=False,
                      comparison_database_cache_trust='closed historical reader cache; no independent whole-cache proof')
        closed_database(database)
        frozen.verify()
    except (ValueError, TypeError, KeyError, IndexError, OSError, sqlite3.Error) as error:
        report.update(status='unverified', complete=False, certificates=[], error=str(error))
    report['inputs'] = list(frozen.records.values())
    (output / 'summary.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return report


def target(value):
    match = re.fullmatch(r'P([34]):([1-9][0-9]*):([1-9][0-9]*)', value)
    if match is None:
        raise argparse.ArgumentTypeError('target must be P3:GRH_ID:GSIM_ID or P4:GRH_ID:GSIM_ID')
    return tuple(map(int, match.groups()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('comparison', 'grh', 'gsim', 'output'):
        parser.add_argument('--' + field, required=True, type=Path)
    parser.add_argument('--target', action='append', required=True, type=target)
    args = parser.parse_args()
    try:
        report = prove(args.comparison, args.grh, args.gsim, args.output, args.target)
    except (ValueError, OSError) as error:
        parser.exit(2, 'unverified: ' + str(error) + '\n')
    print(json.dumps({'status': report['status'], 'certificates': len(report['certificates']),
                      'semantic_acceptance': False, 'output': str(args.output)}))
    return 0 if report['status'] == 'conditional_anchor_expressions_proved' else 1


if __name__ == '__main__':
    raise SystemExit(main())
