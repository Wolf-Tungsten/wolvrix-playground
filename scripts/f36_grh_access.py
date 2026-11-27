"""Recover the projection of each GRH state access from the R4 inventory."""

from __future__ import annotations

from math import prod


READ_PORTS = {'grh.registerReadPort', 'grh.registerReadArrayPort', 'grh.latchReadPort'}
WRITE_HEADS = {'grh.registerWritePort': 2, 'grh.registerWriteMaskPort': 3,
               'grh.registerFillPort': 2, 'grh.latchWritePort': 3}
INDEXED_WRITE_HEADS = {'grh.registerWriteArrayPort': 2, 'grh.registerWriteArrayMaskPort': 3}


def _event_count(action):
    edges = action.get('attrs', {}).get('eventEdge')
    if isinstance(edges, dict):
        edges = edges.get('vs')
    return len(edges) if isinstance(edges, list) else None


def grh_accesses(state, actions):
    """Return access signatures and evidence gaps for a single declaration."""
    shape = tuple(state['shape'])
    leaf_width = state['width']
    accesses = []
    uncertainty = set()
    for action in actions:
        if action.get('target_resolution') != 'resolved':
            uncertainty.add('unresolved-state-action')
            continue
        kind = action['kind']
        operands = action.get('operands', [])
        index_count = 0
        if kind in READ_PORTS:
            direction = 'read'
            results = action.get('results', [])
            if len(results) != 1 or (kind == 'grh.registerReadArrayPort') != bool(operands):
                uncertainty.add('read-operand-layout')
                continue
            index_count = len(operands)
            payload = results[0]
        elif kind in WRITE_HEADS or kind in INDEXED_WRITE_HEADS:
            direction = 'write'
            if kind in INDEXED_WRITE_HEADS:
                events = _event_count(action)
                if events is None:
                    uncertainty.add('write-operand-layout')
                    continue
                index_count = len(operands) - events - INDEXED_WRITE_HEADS[kind]
                if index_count < 1:
                    uncertainty.add('write-operand-layout')
                    continue
            elif len(operands) < WRITE_HEADS[kind]:
                uncertainty.add('write-operand-layout')
                continue
            payload = operands[1 + index_count]
        else:
            uncertainty.add('unknown-state-action')
            continue
        if index_count > len(shape):
            uncertainty.add(f'{direction}-index-count')
            continue
        projection = shape[index_count:]
        payload_shape = tuple(payload.get('shape', []))
        payload_width = payload.get('width')
        expected_width = leaf_width if kind == 'grh.registerFillPort' else leaf_width * prod(projection)
        if (payload_width is None or payload_width * prod(payload_shape) != expected_width
                or (direction == 'read' and index_count and payload_shape and payload_shape != projection)):
            uncertainty.add(f'{direction}-projection-shape')
            continue
        accesses.append((direction, (None,) * index_count, projection, leaf_width))
    return accesses, sorted(uncertainty)
