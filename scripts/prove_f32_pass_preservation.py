"""Bounded native GRH anchor preservation, replayed from common formal inputs.

This verifier proves current combinational anchor values under defined 0/1
formal inputs for a small explicit operation subset. It does not certify X/Z,
complete Node membership, source bindings, state/effects, retirement, GSIM, or
the F32 acceptance gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import prod
from pathlib import Path
import re

import prove_f32_reconstruction as native_loader
from prove_f32_reconstruction import FrozenInputs, ROOT, identities, load_capture, require

SCHEMA = 'wolvrix.f32.pass-anchor-preservation.v1'
MAX_BITS = 4096
MAX_TERMS = 100000
LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class Unsupported(ValueError):
    pass


class Arena:
    """Hash-cons exact finite expression keys; proof equality never uses a hash."""
    def __init__(self):
        self.terms, self.index = [], {}
        self.zero, self.one = self.term('literal', '0'), self.term('literal', '1')

    def term(self, *key):
        if key not in self.index:
            if len(self.terms) >= MAX_TERMS:
                raise Unsupported('symbolic term budget exceeded')
            self.index[key] = len(self.terms)
            self.terms.append(key)
        return self.index[key]

    def mux(self, select, yes, no):
        if yes == no:
            return yes
        if select in (self.zero, self.one):
            return yes if select == self.one else no
        return self.term('defined-mux', select, yes, no)

    def index_equal(self, bits, coordinate):
        if coordinate >= 1 << len(bits):
            return self.zero
        expected = tuple(self.one if coordinate >> bit & 1 else self.zero for bit in range(len(bits)))
        if all(bit in (self.zero, self.one) for bit in bits):
            return self.one if bits == expected else self.zero
        return self.term('defined-logical-equality', bits, expected)


class Model:
    def __init__(self, native, arena, endpoints=None, identity_rows=None):
        require(len(native.get('graphs', [])) == 1, 'requires one native Wolvrix IR graph')
        self.graph, self.arena, self.endpoints = native['graphs'][0], arena, endpoints
        tree = self.graph.get('semanticTree', {})
        require(tree.get('namesFlattened') is True, 'requires flattened native SemanticTree')
        self.tree = tree
        paths = identities(tree.get('paths'), limit=128)
        root = tree.get('rootPath')
        require(len(paths) == 1 and type(root) is int and root in paths and
                type(paths[root].get('parent')) is int and paths[root]['parent'] == 0 and
                all(isinstance(value, str) and bool(value) for value in
                    (self.graph.get('symbol'), tree.get('sourceUnit'), tree.get('circuit'), paths[root].get('name'))),
                'requires one complete flattened native graph/path identity')
        self.identity_context = (self.graph['symbol'], tree['sourceUnit'], tree['circuit'], root, paths[root]['name'])
        self.nodes = identities(tree.get('nodes'), limit=128)
        self.values = identities(self.graph.get('vals'))
        self.ops = identities(self.graph.get('ops'))
        self.native_ids = {}
        if identity_rows is not None:
            self.native_ids = {'value': {}, 'operation': {}}
            native_indices = {'value': set(), 'operation': set()}
            for row in identity_rows:
                kind = row.get('kind')
                require(kind in self.native_ids, 'invalid native serialization identity kind')
                serialized = native_loader.integer(row['serialized_id'])
                physical = (native_loader.integer(row['native_index']), native_loader.integer(row['native_generation']))
                require(serialized > 0 and physical[0] > 0 and serialized not in self.native_ids[kind] and
                        physical[0] not in native_indices[kind], 'duplicate or null native serialization identity')
                self.native_ids[kind][serialized] = physical
                native_indices[kind].add(physical[0])
            require(set(self.native_ids['value']) == set(self.values) and set(self.native_ids['operation']) == set(self.ops),
                    'native serialization identity map does not cover the actual serialized graph')
        require(all(type(node.get('parent')) is int and node['parent'] == root and
                    isinstance(node.get('name'), str) and bool(node['name']) and
                    isinstance(node.get('anchors'), list) and
                    all(type(value) is int and value in self.values for value in node['anchors'])
                    for node in self.nodes.values()), 'invalid flattened native Node identity/anchor')
        self.producers, self.inputs, self.memo, self.active = {}, {}, {}, set()
        for op in self.ops.values():
            require(isinstance(op.get('in'), list) and isinstance(op.get('out'), list) and
                    all(type(value) is int and value in self.values for value in op['in'] + op['out']),
                    'invalid native operation values')
            for value in op['out']:
                require(value not in self.producers, 'duplicate native value producer')
                self.producers[value] = op
        metadata = self.graph.get('metadata', {})
        name_attr, node_attr = (metadata.get(key, {}) for key in
                               ('firrtl.semanticPortNames', 'firrtl.semanticPortNodes'))
        names, node_ids = name_attr.get('vs'), node_attr.get('vs')
        require(name_attr.get('t') == 'string[]' and node_attr.get('t') == 'int[]' and
                isinstance(names, list) and isinstance(node_ids, list) and len(names) == len(node_ids) and
                all(isinstance(name, str) and bool(name) for name in names) and
                all(type(identifier) is int and identifier in self.nodes for identifier in node_ids) and
                len(set(node_ids)) == len(node_ids) and len(set(names)) == len(names),
                'missing or ambiguous native semantic formal port bindings')
        bindings = dict(zip(names, node_ids))
        ports = self.graph.get('ports', {})
        require(ports.get('inout') == [] and isinstance(ports.get('in'), list) and
                isinstance(ports.get('out'), list), 'inout or malformed interface unsupported')
        all_ports = ports['in'] + ports['out']
        require(all(isinstance(port, dict) and isinstance(port.get('name'), str) and
                    port['name'] in bindings and type(port.get('val')) is int and port['val'] in self.values
                    for port in all_ports) and len(all_ports) == len(bindings) and
                len({port['name'] for port in all_ports}) == len(bindings),
                'formal port inventory differs from native semantic metadata')
        require(all(self.nodes[bindings[port['name']]]['anchors'] == [port['val']] and
                    self.values[port['val']].get('out') is True for port in ports['out']),
                'formal output lacks unique actual Node/anchor binding')
        self.formal_identity = tuple((direction, ordinal, bindings[port['name']], port['name'])
                                    for direction in ('in', 'out') for ordinal, port in enumerate(ports[direction]))
        for ordinal, port in enumerate(ports['in']):
            node = bindings.get(port.get('name'))
            value = port.get('val')
            require(type(node) is int and node in self.nodes and type(value) is int and
                    value in self.values and self.nodes[node].get('anchors') == [value] and
                    self.values[value].get('in') is True and value not in self.producers and
                    value not in self.inputs, 'formal input lacks unique actual Node/anchor binding')
            # A name alone cannot create this identity: native binding and the
            # exact physical formal input anchor above are mandatory.
            self.inputs[value] = (node, ordinal, port['name'])
        self.input_identity = tuple((identity, self.typ(value)) for value, identity in self.inputs.items())

    def typ(self, identifier):
        value = self.values[identifier]
        shape = value.get('shape', [])
        require(type(value.get('w')) is int and 0 < value['w'] <= MAX_BITS and
                type(value.get('sgn')) is bool and value.get('type') == 'logic' and
                value.get('domain') in ('2state', '4state') and isinstance(shape, list) and
                all(type(extent) is int and extent > 0 for extent in shape) and
                value['w'] % prod(shape) == 0, 'invalid or oversized native logical type')
        return value['w'], value['sgn'], value['domain'], tuple(shape)

    def bits(self, identifier, depth=0):
        if identifier in self.memo:
            return self.memo[identifier]
        if depth >= 128 or identifier in self.active:
            raise Unsupported('cyclic or deep combinational cone')
        width, signed, domain, shape = self.typ(identifier)
        if signed:
            raise Unsupported('signed operation semantics not implemented')
        self.active.add(identifier)
        try:
            if identifier in self.inputs:
                result = tuple(self.arena.term('formal-input', self.inputs[identifier], bit, domain)
                               for bit in range(width))
            elif identifier not in self.producers:
                raise Unsupported('cone reaches an unbound nonformal value')
            else:
                op = self.producers[identifier]
                if op['out'] != [identifier]:
                    raise Unsupported('multi-result operation unsupported')
                result = self.operation(op, identifier, depth)
            if len(result) != width:
                raise Unsupported('operation result geometry mismatch')
            self.memo[identifier] = tuple(result)
            return self.memo[identifier]
        finally:
            self.active.remove(identifier)

    def operation(self, op, output, depth):
        arena = self.arena
        width, _, _, shape = self.typ(output)
        kind, inputs = op.get('kind'), op['in']
        attrs = op.get('attrs', {})

        def attr(name, typ):
            value = attrs.get(name, {})
            if value.get('t') != typ:
                raise Unsupported('missing typed operation attribute')
            return value.get('vs' if typ.endswith('[]') else 'v')

        def arg(index):
            if index >= len(inputs):
                raise Unsupported('operation arity mismatch')
            return self.bits(inputs[index], depth + 1)

        def arity(count, keys=()):
            if len(inputs) != count or set(attrs) != set(keys):
                raise Unsupported('operation arity or attributes unsupported')

        def resize(bits):
            return (bits + (arena.zero,) * max(0, width - len(bits)))[:width]

        if kind == 'grh.constant':
            arity(0, ('constValue',))
            text = attr('constValue', 'string').replace('_', '').lower()
            match = re.fullmatch(r"([0-9]+)'([bhd])([0-9a-fxz]+)", text)
            if text.isdecimal():
                number = int(text)
                return tuple(arena.one if number >> bit & 1 else arena.zero for bit in range(width))
            if not match or int(match[1]) != width:
                raise Unsupported('constant syntax or literal width unsupported')
            base, digits = match[2], match[3]
            if 'x' in digits or 'z' in digits:
                raise Unsupported('unknown literal outside defined-value premise')
            if base == 'b':
                if not re.fullmatch('[01xz]+', digits):
                    raise Unsupported('invalid binary constant')
                digits = digits.rjust(width, '0')[-width:]
                return tuple(arena.term('literal', bit) for bit in reversed(digits))
            try:
                number = int(digits, 16 if base == 'h' else 10)
            except ValueError as error:
                raise Unsupported('invalid numeric constant') from error
            return tuple(arena.one if number >> bit & 1 else arena.zero for bit in range(width))
        if kind == 'grh.assign':
            arity(1)
            return resize(arg(0))
        if kind == 'grh.concat':
            if not inputs or attrs:
                raise Unsupported('empty or attributed concat unsupported')
            joined = tuple(bit for index in reversed(range(len(inputs))) for bit in arg(index))
            return resize(joined)
        if kind == 'grh.sliceStatic':
            arity(1, ('sliceStart', 'sliceEnd'))
            low, high = attr('sliceStart', 'int'), attr('sliceEnd', 'int')
            if type(low) is not int or type(high) is not int or not 0 <= low <= high < len(arg(0)):
                raise Unsupported('invalid static slice')
            return arg(0)[low:high + 1]
        if kind == 'grh.bitNot':
            arity(1)
            if len(arg(0)) != width:
                raise Unsupported('width-changing bitwise not unsupported')
            return tuple(arena.term('defined-not', bit) for bit in arg(0))
        if kind in ('grh.bitAnd', 'grh.bitOr', 'grh.bitXor'):
            arity(2)
            return tuple(arena.term(kind, left, right) for left, right in zip(resize(arg(0)), resize(arg(1))))
        if kind == 'grh.mux':
            arity(3)
            if len(arg(0)) != 1:
                raise Unsupported('non-bit mux control')
            return tuple(arena.mux(arg(0)[0], yes, no) for yes, no in zip(resize(arg(1)), resize(arg(2))))
        if kind == 'grh.sliceArray':
            arity(2)
            source_shape = self.typ(inputs[0])[3]
            index = arg(1)
            if not source_shape or any(bit not in (arena.zero, arena.one) for bit in index):
                raise Unsupported('dynamic array read unsupported')
            coordinate = sum((bit == arena.one) << offset for offset, bit in enumerate(index))
            stride = len(arg(0)) // source_shape[0]
            if coordinate >= source_shape[0] or shape != source_shape[1:] or width != stride:
                raise Unsupported('array read geometry or bounds unsupported')
            return arg(0)[coordinate * stride:(coordinate + 1) * stride]
        if kind == 'grh.combArrayUpdate':
            counts = attr('indexCounts', 'int[]')
            if (set(attrs) != {'indexCounts'} or not shape or self.typ(inputs[0]) != self.typ(output) or
                    not isinstance(counts, list) or any(type(count) is not int or not 0 <= count <= len(shape)
                                                       for count in counts) or
                    len(inputs) != 1 + sum(count + 2 for count in counts)):
                raise Unsupported('invalid combinational array update geometry')
            result, operand = list(arg(0)), 1
            leaves, leaf_width = prod(shape), width // prod(shape)
            for rank in counts:
                enable, payload = arg(operand), arg(operand + rank + 1)
                suffix = prod(shape[rank:])
                if (len(enable) != 1 or len(payload) != suffix * leaf_width or
                        self.typ(inputs[operand + rank + 1])[3] != shape[rank:]):
                    raise Unsupported('array update control or payload geometry mismatch')
                for leaf in range(leaves):
                    match, stride = enable[0], leaves
                    for axis in range(rank):
                        stride //= shape[axis]
                        index = arg(operand + 1 + axis)
                        if self.typ(inputs[operand + 1 + axis])[3]:
                            raise Unsupported('array-valued update index')
                        equal = arena.index_equal(index, leaf // stride % shape[axis])
                        match = arena.term('grh.bitAnd', match, equal)
                    for bit in range(leaf_width):
                        offset = leaf * leaf_width + bit
                        result[offset] = arena.mux(match, payload[(leaf % suffix) * leaf_width + bit], result[offset])
                operand += rank + 2
            return tuple(result)
        raise Unsupported('operation unsupported: ' + str(kind))


def source_geometry(model, node, anchor):
    """Accept actual v2 binding geometry, never a typed anchor candidate."""
    rows = [row for row in model.endpoints or [] if native_loader.integer(row['node_id']) == node]
    if len(rows) != 1 or rows[0].get('evidence') != 'native-binding' or rows[0].get('role') != 'value':
        raise Unsupported('retained projection requires one actual native source binding per Node')
    row = rows[0]
    if not model.native_ids:
        raise Unsupported('retained projection requires explicit native-to-serialized identity map')
    try:
        value = (native_loader.integer(row['value_id']), native_loader.integer(row['value_generation']))
        operation = (native_loader.integer(row['operation_id']), native_loader.integer(row['operation_generation']))
        producer = model.producers.get(anchor)
        expected_operation = model.native_ids['operation'][producer['id']] if producer else (0, 0)
        expected_kind = producer['kind'] if producer else 'input'
        if (value != model.native_ids['value'][anchor] or operation != expected_operation or
                row['native_kind'] != expected_kind or (producer is None and anchor not in model.inputs)):
            raise Unsupported('native endpoint does not bind the actual serialized anchor and its defining operation')
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, Unsupported):
            raise
        raise Unsupported('invalid native endpoint value/defining-operation identity') from error
    width, signed, domain, shape = model.typ(anchor)
    leaf_width = width // prod(shape)
    try:
        native_shape = native_loader.parse_json(row['shape_json'])
        source_shape = native_loader.parse_json(row['source_shape_json'])
        projection = native_loader.parse_json(row['projection_json'])
        field_depths = native_loader.parse_json(row['source_shape_field_depths_json'])
        if (any(not isinstance(axes, list) or any(type(axis) is not int for axis in axes)
                for axes in (native_shape, source_shape, projection))):
            raise Unsupported('invalid typed native projection axes')
        source_width = native_loader.integer(row['source_width'])
        low = native_loader.integer(row['source_bit_offset'])
        retained = source_width if row['source_bit_width'] == '-1' else native_loader.integer(row['source_bit_width'])
        if (native_loader.integer(row['value_id']) <= 0 or
                native_loader.integer(row['width']) != leaf_width or
                native_loader.boolean(row['signed']) != signed or native_loader.boolean(row['source_signed']) != signed or
                row['logic_domain'] != domain or native_shape != list(shape) or source_shape != list(shape) or
                (projection != [] and projection != [-1] * len(shape)) or
                not isinstance(field_depths, list) or
                any(type(depth) is not int or depth < 0 for depth in field_depths) or
                (field_depths and len(field_depths) != len(shape)) or field_depths != sorted(field_depths) or
                retained != leaf_width or retained < 1 or source_width < 1 or low + retained > source_width):
            raise Unsupported('native source binding geometry differs from actual typed anchor')
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, Unsupported):
            raise
        raise Unsupported('invalid native source projection geometry') from error
    return {'source_width': source_width, 'source_shape': source_shape, 'source_signed': signed,
            'source_shape_field_depths': field_depths, 'projection': [-1] * len(shape),
            'source_bit_offset': low, 'source_bit_width': retained, 'physical_leaf_width': leaf_width,
            'native_endpoint': dict(row)}


def identity_map(frozen, capture_record, record):
    name = 'serialization-id-map.tsv'
    artifact = capture_record.get('artifacts', {}).get(name)
    if artifact is None:
        return None
    path = Path(capture_record['directory']) / name
    lines = frozen.read(path, expected=artifact).decode('utf-8').splitlines(keepends=True)
    require(3 <= len(lines) <= 8195 and all(line.endswith('\n') and '\r' not in line for line in lines) and
            lines[0].startswith('#meta\t') and lines[-1].startswith('#footer\t'),
            'incomplete or oversized native serialization identity map')
    metadata, footer = native_loader.parse_json(lines[0][6:]), native_loader.parse_json(lines[-1][8:])
    node_meta = record['tables']['nodes.tsv']['metadata']
    native = frozen.json(record['structure'])
    require(metadata.get('schema') == 'grh.native-serialization-map.v1' and metadata.get('engine') == 'grh' and
            all(metadata.get(key) == node_meta[key] for key in ('run_id', 'snapshot_id', 'stage', 'graph_id')) and
            metadata.get('session_id') == node_meta.get('exchange_session_id') and
            type(metadata.get('graph_index')) is int and metadata['graph_index'] > 0 and
            str(metadata['graph_index']) == node_meta['graph_id'] and
            type(metadata.get('graph_generation')) is int and metadata['graph_generation'] >= 0 and
            len(native.get('graphs', [])) == 1 and metadata.get('graph_symbol') == native['graphs'][0].get('symbol'),
            'native serialization identity map snapshot/schema mismatch')
    columns = ('kind', 'serialized_id', 'native_index', 'native_generation')
    require(lines[1] == '\t'.join(columns) + '\n', 'unsupported native serialization identity map columns')
    rows = []
    for line in lines[2:-1]:
        fields = line[:-1].split('\t')
        require(len(fields) == len(columns) and not line.startswith('#'), 'invalid native serialization identity row')
        rows.append(dict(zip(columns, fields)))
    require(footer.get('complete') is True and type(footer.get('rowCount')) is int and footer['rowCount'] == len(rows),
            'incomplete native serialization identity map footer')
    return rows


def retained_projection(before, after, identifier, left, right):
    old_type, new_type = before.typ(left), after.typ(right)
    if old_type[1:] != new_type[1:] or old_type[0] <= new_type[0]:
        raise Unsupported('physical anchor geometry change is not a same-shape unsigned leaf narrowing')
    old, new = source_geometry(before, identifier, left), source_geometry(after, identifier, right)
    for field in ('source_width', 'source_shape', 'source_signed', 'source_shape_field_depths', 'projection'):
        if old[field] != new[field]:
            raise Unsupported('native source identities or projection axes differ across narrowing')
    # This first certificate rule is deliberately only the actual prefix case.
    # An arbitrary source interval needs an explicit source/physical bit map.
    if old['source_bit_offset'] != 0 or new['source_bit_offset'] != 0:
        raise Unsupported('retained projection rule requires native zero-offset leaf prefixes')
    old_bits, new_bits = before.bits(left), after.bits(right)
    old_stride, new_stride = old['physical_leaf_width'], new['physical_leaf_width']
    leaves = prod(old['source_shape'])
    projected = tuple(old_bits[cell * old_stride + bit] for cell in range(leaves) for bit in range(new_stride))
    if projected != new_bits:
        raise Unsupported('retained source projection symbolic lanes differ')
    return {'status': 'retained_projection_preservation_proved', 'retained_projection_preservation_proved': True,
        'reason': 'every retained native source leaf-prefix lane equals its prior typed anchor lane',
        'rule': 'native-source-leaf-prefix-preservation.v1', 'before_source_geometry': old,
        'after_source_geometry': new, 'leaf_count': leaves, 'before_leaf_width': old_stride,
        'after_leaf_width': new_stride, 'retained_bits_proved': len(new_bits),
        'discarded_bits_unobservable_proved': False, 'full_width_anchor_equality_proved': False,
        'lane_witness_sha256': hashlib.sha256(json.dumps(projected).encode()).hexdigest()}


def compare_models(before, after, stage):
    require(before.identity_context == after.identity_context and before.formal_identity == after.formal_identity,
            'native graph/path identity context or semantic formal metadata changed across pass')
    require(before.input_identity == after.input_identity,
            'formal input identities, bindings, order, or types changed across pass')
    results = []
    for identifier in sorted(set(before.nodes) | set(after.nodes)):
        row = {'boundary': f'P{stage}', 'node_id': identifier, 'status': 'unproved',
               'anchor_value_preservation_proved': False, 'complete_node_preservation_proved': False,
               'retained_projection_preservation_proved': False,
               'proof_domain': 'all formal input bits are arbitrary defined 0/1 values',
               'four_state_behavior_proved': False}
        if identifier not in before.nodes or identifier not in after.nodes:
            row['reason'] = 'new or retired native Node needs a separate certificate'
        else:
            old, new = before.nodes[identifier], after.nodes[identifier]
            if old.get('name') != new.get('name') or old.get('parent') != new.get('parent'):
                row['reason'] = 'native Node identity context changed'
            elif len(old.get('anchors', [])) != 1 or len(new.get('anchors', [])) != 1:
                row['reason'] = 'requires one current native anchor per Node'
            else:
                left, right = old['anchors'][0], new['anchors'][0]
                row.update(before_anchor_value_id=left, after_anchor_value_id=right)
                try:
                    if before.typ(left) != after.typ(right):
                        row.update(retained_projection(before, after, identifier, left, right))
                        results.append(row)
                        continue
                    left_bits, right_bits = before.bits(left), after.bits(right)
                    if left_bits != right_bits:
                        raise Unsupported('symbolic lane forms differ; no preservation claim')
                    row.update(status='anchor_value_preservation_proved', anchor_value_preservation_proved=True,
                        reason='exact symbolic lanes from the same native formal inputs',
                        width=len(left_bits), logic_domain=before.typ(left)[2],
                        lane_witness_sha256=hashlib.sha256(json.dumps(left_bits).encode()).hexdigest())
                except Unsupported as error:
                    row['reason'] = str(error)
        results.append(row)
    return results


def prove(comparison, grh, output):
    comparison, grh, output = (Path(path).resolve() for path in (comparison, grh, output))
    require(output.is_relative_to(ROOT / 'ptmp') and not output.exists(),
            'output must be a new directory under repository ptmp')
    frozen, arena = FrozenInputs(), Arena()
    summary = frozen.json(comparison / 'summary.json')
    checkpoint = frozen.json(comparison / 'inputs.json')
    require(summary.get('schema') == 'wolvrix.f32.semantic-comparison.v1' and
            summary.get('status') == 'analyzed' and summary.get('complete') is True and
            checkpoint.get('schema') == 'wolvrix.f32.comparison-checkpoint.v1' and
            checkpoint.get('inventory_complete') is True and summary.get('snapshots') == checkpoint.get('snapshots'),
            'requires completed closed comparison with native inventory checkpoint')
    capture, records = load_capture(frozen, grh, 'grh', checkpoint)
    require(capture['input_sha256'] == summary.get('input_sha256'), 'original FIRRTL identity mismatch')
    models = {}
    for stage, record in records.items():
        model = Model(frozen.json(record['structure']), arena, record['tables']['node-endpoints.tsv']['rows'],
                      identity_map(frozen, capture['snapshots'][f'P{stage}'], record))
        inventory = {int(row['node_id']) for row in record['tables']['nodes.tsv']['rows']}
        require(set(model.nodes) == inventory, 'structure/native Node inventory mismatch')
        models[stage] = model
    rows = [row for stage in range(1, 5) for row in compare_models(models[stage - 1], models[stage], stage)]
    for path, expected in ((Path(__file__).resolve(), LOADED_SOURCE_SHA256),
                           (Path(__file__).with_name('prove_f32_reconstruction.py'), native_loader.LOADED_SOURCE_SHA256)):
        require(hashlib.sha256(frozen.read(path)).hexdigest() == expected,
                'verifier or native loader source changed since module load')
    frozen.verify()
    output.mkdir(parents=True)
    artifacts = {'anchor_certificates.jsonl': ''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows),
                 'symbolic_terms.json': json.dumps(arena.terms, separators=(',', ':')) + '\n'}
    for name, body in artifacts.items():
        (output / name).write_text(body)
    report = {'schema': SCHEMA, 'status': 'analyzed', 'complete': True,
        'scope': 'GRH current typed combinational anchor values from identical native formal input bindings',
        'premise': 'Every native formal input bit is defined and has an arbitrary 0/1 value; identical native formal bindings denote the same input vector across one pass.',
        'four_state_behavior_proved': False, 'cross_engine_equivalence_proved': False,
        'full_node_membership_proved': False, 'source_bindings_proved': False,
        'state_effects_initialization_proved': False, 'retirement_proved': False,
        'window_acceptance': False, 'semantic_acceptance': False, 'upstream_gate_modified': False,
        'certificate_ingestion_implemented': False,
        'original_firrtl_sha256': capture['input_sha256'], 'frozen_inputs': list(frozen.records.values()),
        'results_by_boundary': {f'P{stage}': dict(Counter(row['status'] for row in rows if row['boundary'] == f'P{stage}'))
                                for stage in range(1, 5)},
        'artifacts': {name: {'path': str(output / name), 'sha256': hashlib.sha256(body.encode()).hexdigest()}
                      for name, body in artifacts.items()}}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('comparison', 'grh', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = prove(args.comparison, args.grh, args.output)
    print(json.dumps(report['results_by_boundary'], sort_keys=True))


if __name__ == '__main__':
    main()
