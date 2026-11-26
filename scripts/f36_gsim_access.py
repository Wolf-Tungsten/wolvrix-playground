"""Recover the projection of each GSIM state access from the R4 inventory."""

from __future__ import annotations

import json
import re


_TSV_ESCAPE = re.compile(r'\\([\\tnr])')
_TSV_UNESCAPED = {'\\': '\\', 't': '\t', 'n': '\n', 'r': '\r'}


def _expression(field):
    if '\\' in field:
        field = _TSV_ESCAPE.sub(lambda match: _TSV_UNESCAPED[match[1]], field)
    return json.loads(field)


def _literal(expression):
    text = expression.get('text', '')
    try:
        return int(text) if text.lstrip('-').isdecimal() else int(text, 0)
    except ValueError:
        return None


def _register_projection(expression, node_id, shape):
    if not expression or expression.get('op') != 'OP_EMPTY' or str(expression.get('node_id')) != node_id:
        return None
    children = expression['children']
    if len(children) > len(shape):
        return None
    selectors = []
    for child in children:
        if child and child['op'] == 'OP_INDEX_INT' and len(child.get('values', [])) == 1:
            selectors.append(child['values'][0])
        elif child and child['op'] == 'OP_INDEX' and len(child['children']) == 1 and child['children'][0]:
            index = child['children'][0]
            selectors.append(_literal(index) if index['op'] == 'OP_INT' else None)
        else:
            return None
    return tuple(selectors)


def _register_accesses(state, actions, shape, width):
    accesses = set()
    uncertainty = set()
    for action in actions:
        kind = action['action_kind']
        if kind == 'read-reference':
            direction = 'read'
            expression = _expression(action['root_json'])
            node_id = state['state_id']
        elif kind == 'update':
            direction = 'write'
            expression = _expression(action['lvalue_json'])
            node_id = state['state_pair_node_id']
        elif kind == 'reset':
            direction = 'write'
            expression = _expression(action['lvalue_json'])
            node_id = state['state_id']
            root = _expression(action['root_json'])
            if not root or root['op'] != 'OP_RESET' or len(root['children']) != 2:
                uncertainty.add('write-reset-projection')
                continue
            condition, value = root['children']
            if (condition and condition['op'] == 'OP_INT' and _literal(condition) == 0
                    or not value or value['op'] == 'OP_INVALID'
                    or _register_projection(value, node_id, shape) == ()):
                continue
        else:
            continue
        axes = _register_projection(expression, node_id, shape)
        if axes is None:
            uncertainty.add(f'{direction}-register-projection')
        else:
            accesses.add((direction, axes, shape[len(axes):], width))
    return accesses, uncertainty


def _memory_accesses(state, actions, shape, width):
    accesses = set()
    uncertainty = set()
    read_ports = set()
    observed_reads = set()
    for action in actions:
        kind = action['action_kind']
        if kind in ('read-port', 'shared-port'):
            read_ports.add(action['port_id'])
        if kind in ('read-access', 'read-port', 'shared-port'):
            direction, opcode = 'read', 'OP_READ_MEM'
        elif kind == 'write-access':
            direction, opcode = 'write', 'OP_WRITE_MEM'
        else:
            continue
        root = _expression(action['root_json'])
        if not root or root['op'] != opcode or str(root.get('memory_id')) != state['state_id']:
            if kind in ('read-access', 'write-access'):
                uncertainty.add(f'{direction}-memory-projection')
            continue
        children = root['children']
        if len(children) != (1 if direction == 'read' else 2) or not children[0]:
            uncertainty.add(f'{direction}-memory-projection')
            continue
        index = children[0]
        selector = _literal(index) if index['op'] == 'OP_INT' else None
        # A write's assignment target can project into the selected memory row.
        row_axes = ()
        if direction == 'write':
            row_axes = _register_projection(_expression(action['lvalue_json']), action['port_id'], shape)
            if row_axes is None:
                uncertainty.add('write-memory-row-projection')
                continue
        else:
            observed_reads.add(action['port_id'])
        accesses.add((direction, (selector, *row_axes), shape[len(row_axes):], width))
    if read_ports - observed_reads:
        uncertainty.add('read-memory-projection')
    return accesses, uncertainty


def gsim_accesses(state, actions):
    """Return unique access signatures and the reasons for any unknown projection."""
    shape = tuple(json.loads(state['shape_json']))
    width = int(state['width'])
    if state['native_kind'] == 'NODE_MEMORY':
        accesses, uncertainty = _memory_accesses(state, actions, shape, width)
    else:
        accesses, uncertainty = _register_accesses(state, actions, shape, width)
    return sorted(accesses, key=repr), sorted(uncertainty)
