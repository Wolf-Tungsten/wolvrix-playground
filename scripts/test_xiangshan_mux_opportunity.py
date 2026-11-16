"""Independent edge-deletion and demand oracles for the static analysis."""
from array import array
import csv
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest

from xiangshan_mux_opportunity import prepare

MASK = (1 << 64) - 1


def word(value):
    value = (value + 0x9e3779b97f4a7c15) & MASK
    value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & MASK
    value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & MASK
    return value ^ (value >> 31)


def reachable(nodes, removed=None, choices=None):
    todo = [i for i, n in enumerate(nodes) if i and n['flags'] & 2]
    seen = set()
    while todo:
        v = todo.pop()
        if not v or v in seen:
            continue
        seen.add(v)
        node = nodes[v]
        for position, pred in enumerate(node['in']):
            if removed == (v, position):
                continue
            if choices is not None and node['flags'] & 4 and position:
                choice = node['truth'] if node['truth'] >= 0 else choices[node['selector']]
                if position != (1 if choice else 2):
                    continue
            todo.append(pred)
    return seen


def node(ins=(), mux=False, output=False, pure=True, scalar=True, selector=0, truth=-1):
    return dict(in_=list(ins), flags=(1 if pure else 0) | (2 if output or not pure else 0) |
                (4 if mux else 0) | (8 if scalar else 0), selector=selector, truth=truth)


def graph(*items):
    result = [dict(in_=[], flags=2, selector=0, truth=-1), *items]
    for n in result:
        n['in'] = n.pop('in_')
    return result


def packed(nodes, path):
    offsets = array('Q', [0]);pred = array('I')
    for n in nodes:
        pred.extend(n['in']);offsets.append(len(pred))
    with path.open('wb') as f:
        f.write(b'MUXGRH01')
        f.write(struct.pack('<QQQ', len(nodes), len(pred), 100))
        for a in (offsets, pred, array('I', (n['flags'] for n in nodes)),
                  array('I', (32 if n['flags'] & 8 else 128 for n in nodes)),
                  array('I', (n['selector'] for n in nodes)), array('b', (n['truth'] for n in nodes)),
                  array('I', (int(bool(n['flags'] & 4)) for n in nodes)), array('Q', range(len(nodes)))):
            a.tofile(f)


class OpportunityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ['XIANGSHAN_MUX_ANALYZER']).resolve()

    def check_graph(self, nodes):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp);packed(nodes, out / 'graph.bin')
            subprocess.run([self.binary, out, '8'], check=True, capture_output=True)
            live = reachable(nodes)
            pure = {v for v in live if nodes[v]['flags'] & 1}
            with (out / 'muxes.tsv').open() as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            for row in rows:
                mux = int(row['op_index'])
                for arm, name in ((1, 'exclusive_true'), (2, 'exclusive_false')):
                    expected = pure - reachable(nodes, removed=(mux, arm))
                    self.assertEqual(int(row[name]), len(expected), (mux, arm, nodes))
            # Enumerate the exact choices represented by the seeded bitset,
            # using a separate recursive demand walk for each assignment.
            selectors = {n['selector'] for n in nodes if n['flags'] & 4}
            expected = []
            for batch in range(8):
                masks = {v: word((v + batch * 0xd1342543de82ef95 + 20261115) & MASK) for v in selectors}
                count = sum(len(pure & reachable(nodes, choices={v: (masks[v] >> b) & 1 for v in selectors}))
                            for b in range(64))
                expected.append(count / 64)
            with (out / 'demand-batches.tsv').open() as f:
                actual = [float(r['expected_ops']) for r in csv.DictReader(f, delimiter='\t')]
            self.assertEqual(actual, expected)
            with (out / 'exclusive.tsv').open() as f:
                result = next(csv.DictReader(f, delimiter='\t'))
            with (out / 'bounded-scalar.tsv').open() as f:
                result['bounded'] = next(csv.DictReader(f, delimiter='\t'))
            return result

    def test_nested_independent(self):
        result = self.check_graph(graph(node(), node(), node((0,1,2), mux=True, selector=1),
                                        node(), node((0,3,4), mux=True, selector=2, output=True)))
        self.assertEqual(float(result['expected_saved']), 2.5)
        self.assertEqual(int(result['unique_gated']), 4)

    def test_reused_selector_and_impossible_path(self):
        result = self.check_graph(graph(node(), node(), node((2,)),
                                        node((0,1,3), mux=True, selector=1), node(),
                                        node((0,4,5), mux=True, selector=1, output=True)))
        self.assertEqual(float(result['expected_saved']), 3.5)

    def test_shared_inside_arm(self):
        self.check_graph(graph(node(), node((1,)), node((1,)), node((2,3)),
                               node((0,4,0), mux=True, selector=1, output=True)))

    def test_external_consumer_and_selector_overlap(self):
        self.check_graph(graph(node(output=True), node((1,)), node((1,)),
                               node((2,3,0), mux=True, selector=1, output=True)))

    def test_shared_across_arms_and_other_mux(self):
        self.check_graph(graph(node(), node((1,)), node((1,)),
                               node((0,2,3), mux=True, selector=1, output=True),
                               node((0,1,0), mux=True, selector=2, output=True)))

    def test_constants_wide_state_and_dead(self):
        self.check_graph(graph(node(pure=False), node((1,), scalar=False), node(),
                               node((0,2,3), mux=True, scalar=False, selector=1, truth=1, output=True),
                               node(), node((5,)), node((1,), pure=False)))

    def test_budget_endpoints(self):
        for length, expected in ((15, 0), (16, 16), (256, 256), (257, 0)):
            items=[node((i,)) for i in range(length)]
            items.append(node((0,length,0),mux=True,selector=1,output=True))
            with self.subTest(length=length):
                result=self.check_graph(graph(*items))
                self.assertEqual(int(result['bounded']['unique_ops']),expected)
                self.assertEqual(float(result['bounded']['expected_saved']),expected/2)

    def test_outer_first_budget_avoids_double_count(self):
        items=[node((i,)) for i in range(20)]
        items.append(node((0,20,0),mux=True,selector=1))
        items.append(node((0,21,0),mux=True,selector=2,output=True))
        result=self.check_graph(graph(*items))
        self.assertEqual(int(result['bounded']['unique_ops']),21)
        self.assertEqual(int(result['bounded']['roots']),1)
        self.assertEqual(float(result['bounded']['expected_saved']),10.5)

    def test_random_dags(self):
        rng = random.Random(1907)
        for trial in range(24):
            items = []
            for i in range(1,31):
                mux = rng.randrange(3)==0
                ins = ((0, rng.randrange(i), rng.randrange(i)) if mux else
                       (rng.randrange(i), rng.randrange(i)))
                items.append(node(ins, mux=mux, selector=rng.randrange(1,5), output=i in (28,30)))
            with self.subTest(trial=trial):self.check_graph(graph(*items))

    def test_loader_ports_and_unordered_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'source.json'
            vals=[dict(sym=s,w=32,type='logic',**{'in':s=='s','out':s=='o'}) for s in ('s','x','o')]
            ops=[dict(sym='m',kind='kMux',**{'in':['s','x','s'],'out':['o']}),
                 dict(sym='xop',kind='kAdd',**{'in':['s','s'],'out':['x']})]
            source.write_text('{\n"graphs": [\n{\n"symbol": "SimTop",\n"vals": [\n' +
                              ',\n'.join(json.dumps(v) for v in vals) + '\n],\n"ops": [\n' +
                              ',\n'.join(json.dumps(v) for v in ops) + '\n]\n}\n]\n}\n')
            out=base/'out';prepare(source,out)
            subprocess.run([self.binary,out,'1'],check=True,capture_output=True)
            with (out/'exclusive.tsv').open() as f:r=next(csv.DictReader(f,delimiter='\t'))
            self.assertEqual(float(r['expected_saved']),.5)


if __name__ == '__main__':unittest.main()
