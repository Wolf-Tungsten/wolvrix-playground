#!/usr/bin/env python3
"""Isolate indivisible oversized nodes in a weighted multi-constraint HGR.

Node IDs and destination partitions are derived from weights, never supplied.
The caller must establish the HGR's ASC identity before replaying its labels.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path


def read_weights(path: Path) -> tuple[int, list[tuple[int, ...]]]:
    with path.open() as stream:
        edges, nodes, fmt, dimensions = map(int, stream.readline().split())
        if fmt != 11 or dimensions < 1 or nodes < 1:
            raise ValueError('expected weighted, multi-constraint hMetis graph')
        for _ in range(edges):
            if not stream.readline():
                raise ValueError('truncated edge section')
        weights = []
        for _ in range(nodes):
            row = tuple(map(int, stream.readline().split()))
            if len(row) != dimensions or any(value < 0 for value in row):
                raise ValueError('invalid node weights')
            weights.append(row)
        if stream.read().strip():
            raise ValueError('extra node rows')
    return edges, weights


def select_oversized(weights, partitions: int, epsilon: Fraction) -> list[int]:
    if not 1 < partitions <= len(weights) or epsilon < 0:
        raise ValueError('invalid partition count or imbalance')
    remaining = set(range(len(weights)))
    isolated = []
    totals = [sum(row[d] for row in weights) for d in range(len(weights[0]))]
    while partitions - len(isolated) > 1:
        lanes = partitions - len(isolated)
        capacities = [Fraction((total + lanes - 1) // lanes) * (1 + epsilon)
                      for total in totals]
        def score(node):
            return max((Fraction(value, 1) / capacity if capacity else Fraction(0))
                       for value, capacity in zip(weights[node], capacities))
        largest = max(remaining, key=lambda node: (score(node), -node))
        if score(largest) <= 1:
            break
        isolated.append(largest)
        remaining.remove(largest)
        totals = [total - value for total, value in zip(totals, weights[largest])]
    return isolated


def reduce_graph(source: Path, destination: Path, isolated: list[int]) -> dict:
    edges, weights = read_weights(source)
    removed = set(isolated)
    if len(removed) != len(isolated) or not removed <= set(range(len(weights))):
        raise ValueError('invalid derived isolation set')
    remaining = [node for node in range(len(weights)) if node not in removed]
    dense = {old + 1: new + 1 for new, old in enumerate(remaining)}
    kept = 0
    with source.open() as src, destination.open('w+') as dst:
        src.readline()
        dst.write(' ' * 127 + '\n')
        for _ in range(edges):
            fields = list(map(int, src.readline().split()))
            if len(fields) < 3 or fields[0] < 0:
                raise ValueError('invalid edge')
            if any(pin < 1 or pin > len(weights) for pin in fields[1:]):
                raise ValueError('out-of-range edge pin')
            pins = [dense[pin] for pin in fields[1:] if pin in dense]
            if len(pins) != len(set(pins)):
                raise ValueError('duplicate edge pins')
            if len(pins) >= 2:
                dst.write(' '.join(map(str, [fields[0], *pins])) + '\n')
                kept += 1
        for node in remaining:
            dst.write(' '.join(map(str, weights[node])) + '\n')
        dst.seek(0)
        dst.write(f'{kept} {len(remaining)} 11 {len(weights[0])}'.ljust(127) + '\n')
    return dict(nodes=len(weights), edges=edges, remaining_nodes=len(remaining),
                remaining_edges=kept, isolated=isolated,
                isolated_weights=[weights[node] for node in isolated],
                dimensions=len(weights[0]))


def restore_labels(labels: list[int], nodes: int, isolated: list[int], partitions: int) -> list[int]:
    if len(labels) != nodes - len(isolated) or set(labels) != set(range(partitions - len(isolated))):
        raise ValueError('solver labels do not cover the remaining partition set')
    fixed = {node: part for part, node in enumerate(isolated)}
    result = []
    cursor = iter(labels)
    for node in range(nodes):
        result.append(fixed[node] if node in fixed else next(cursor) + len(isolated))
    if set(result) != set(range(partitions)):
        raise ValueError('restored assignment has missing partitions')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    reduce = sub.add_parser('reduce')
    reduce.add_argument('--graph', type=Path, required=True)
    reduce.add_argument('--output', type=Path, required=True)
    reduce.add_argument('--record', type=Path, required=True)
    reduce.add_argument('--partitions', type=int, default=32)
    reduce.add_argument('--epsilon', type=Fraction, default=Fraction(5, 100))
    restore = sub.add_parser('restore')
    restore.add_argument('--labels', type=Path, required=True)
    restore.add_argument('--record', type=Path, required=True)
    restore.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'reduce':
        _, weights = read_weights(args.graph)
        isolated = select_oversized(weights, args.partitions, args.epsilon)
        record = reduce_graph(args.graph, args.output, isolated)
        record.update(partitions=args.partitions, epsilon=str(args.epsilon),
                      supplied_node_ids=[], selection='largest normalized capacity violation; repeat until fit')
        args.record.write_text(json.dumps(record, indent=2) + '\n')
    else:
        record = json.loads(args.record.read_text())
        labels = restore_labels(list(map(int, args.labels.read_text().split())),
                                record['nodes'], record['isolated'], record['partitions'])
        args.output.write_text(''.join(f'{part}\n' for part in labels))


if __name__ == '__main__':
    main()
