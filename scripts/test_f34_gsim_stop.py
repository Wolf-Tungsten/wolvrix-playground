"""GSIM's F34 stages, process-isolated calibration, and CAT behavior."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from f33_guard import F34
from semantic_node_exchange import verify_bundle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'reference/gsim/test/post-dce-semantic-nodes.fir'
CAT = '''FIRRTL version 6.0.0
circuit PatternCat :
  module PatternCat :
    input high : UInt<2>
    input low : UInt<3>
    output out : UInt<1>
    node matched = eq(cat(high, low), UInt<5>(13))
    connect out, matched
'''
ALIAS_LVALUE = '''FIRRTL version 6.0.0
circuit AliasLvalue :
  module AliasLvalue :
    input clock : Clock
    input index : UInt<2>
    input data : UInt<8>
    output result : UInt<8>
    node indexSource = xor(index, UInt<2>(1))
    node indexAlias = indexSource
    reg values : UInt<8>[4], clock
    connect values[indexAlias], data
    connect result, values[index]
'''
MUTATIONS = '''FIRRTL version 6.0.0
circuit Mutations :
  module Mutations :
    input data : UInt<16>
    input index : UInt<3>
    input condition : UInt<1>
    output narrow : UInt<4>
    output testBit : UInt<1>
    output full : UInt<16>
    node wide = xor(data, UInt<16>(7))
    node chosen = mux(condition, wide, wide)
    node same = xor(data, UInt<16>(7))
    node oneHot = dshl(UInt<1>(1), index)
    node bitThree = bits(oneHot, 3, 3)
    node trimmed = xor(data, UInt<16>(3))
    node constSum = add(UInt<2>(1), UInt<2>(2))
    node aliasBit = bitThree
    connect narrow, xor(bits(chosen, 3, 0), bits(trimmed, 3, 0))
    connect testBit, aliasBit
    connect full, xor(xor(chosen, same), constSum)
'''


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class GsimF34Tests(unittest.TestCase):
    def setUp(self):
        self.binary = Path(os.environ['F34_GSIM_BINARY'])
        self.assertTrue(self.binary.is_file(), str(self.binary))
        temporary = tempfile.TemporaryDirectory(prefix='gsim-f34-')
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)

    def run_gsim(self, stop, *options, source=FIXTURE, events=False):
        case = Path(tempfile.mkdtemp(dir=self.work))
        command = [str(self.binary), '--dir=' + str(case), '--timing-output=' + str(case / 'timing.jsonl')]
        if stop:
            command.append('--stop-after-stage=' + stop)
        if events:
            command += ['--stage-events=' + str(case / 'events.jsonl'), '--run-id=f34-test']
        options = [option.replace('{case}', str(case)) for option in options]
        result = subprocess.run([*command, *options, str(source)], cwd=case, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        return case, jsonl(case / 'timing.jsonl'), result.stdout

    def assert_f34_events(self, case, rows, batch):
        passes = [(row['stage'], row['pass_instance']) for row in rows if row['scope'] == 'pass']
        self.assertEqual(passes[-4:], [(stage, instance) for _, instance, stage in F34.calls])
        self.assertFalse(any(row['stage'] == 'graphPartition' for row in rows))
        events = jsonl(case / 'events.jsonl')
        self.assertEqual(len(events), 8)
        self.assertEqual([event['monotonic_s'] for event in events],
                         sorted(event['monotonic_s'] for event in events))
        for i, (logical, instance, _) in enumerate(F34.calls):
            start, end = events[2*i:2*i+2]
            for kind, event in zip(('start', 'end'), (start, end)):
                self.assertEqual((event['event'], event['engine'], event['run_id'], event['logical_instance'],
                                  event['input_boundary'], event['batch_count']),
                                 (kind, 'gsim', 'f34-test', logical, f'R{i}', batch))
            timers = [row for row in rows if row['scope'] == 'pass' and row['pass_instance'] == instance]
            self.assertEqual(len(timers), 1)
            timer = timers[0]
            self.assertEqual(timer['batch_count'], batch)
            self.assertEqual(timer['wall_s'], end['wall_s'])
            self.assertGreater(timer['wall_s'], 0)
            if batch > 1:
                members = timer['native_member_times_s']
                self.assertEqual(len(members), batch)
                self.assertTrue(all(seconds > 0 for seconds in members))
                self.assertLessEqual(sum(members), timer['wall_s'])

    def test_legacy_stop_and_dump_labels(self):
        for stop in ('RemoveDeadNodes', 'RemoveDeadNodes0', 'RemoveDeadNodes1', 'RemoveDeadNodes2'):
            with self.subTest(stop=stop):
                _, rows, _ = self.run_gsim(stop, events=True)
                first = stop in ('RemoveDeadNodes', 'RemoveDeadNodes0')
                stages = [row['stage'] for row in rows if row['scope'] == 'pass']
                bounds = [row['stage'] for row in rows if row['scope'] == 'boundary']
                self.assertEqual(stages[-1], 'RemoveDeadNodes' if first else stop)
                self.assertEqual(bounds[-1], 'RemoveDeadNodes0' if first else stop)
                self.assertNotIn('AliasAnalysis', stages)
        case, _, _ = self.run_gsim('RemoveDeadNodes3', '--dump-json', '--dump-stages=RemoveDeadNodes')
        self.assertEqual(len(list(case.glob('*RemoveDeadNodes.json'))), 2)

    def test_f32_and_f33_snapshot_contracts(self):
        for phase, prefix, total, final in (
                ('F32', 'P', 5, 'RemoveDeadNodes1'), ('F33', 'Q', 3, 'RemoveDeadNodes2')):
            with self.subTest(phase=phase):
                case, rows, _ = self.run_gsim(None, '--semantic-node-exchange={case}/snapshot',
                                             '--semantic-node-exchange-mode=snapshot',
                                             '--semantic-node-exchange-stage=' + phase, events=True)
                self.assertEqual(sorted(path.name for path in (case / 'snapshot').iterdir()),
                                 [prefix + str(index) for index in range(total)])
                self.assertEqual(rows[-1]['stage'], final)
                self.assertFalse(any(row['stage'] == 'AliasAnalysis' for row in rows))
                if phase == 'F33':
                    events = jsonl(case / 'events.jsonl')
                    self.assertEqual([row['logical_instance'] for row in events],
                                     ['constant-analysis#0'] * 2 + ['dead-code-elim#2'] * 2)

    def test_fourth_stop_and_batch(self):
        for count in (1, 3):
            with self.subTest(count=count):
                options = (f'--f34-batch={count}',) if count > 1 else ()
                case, rows, _ = self.run_gsim('RemoveDeadNodes3', *options, events=True)
                self.assert_f34_events(case, rows, count)
                if count == 1:
                    self.assertEqual(rows[-1]['stage'], 'RemoveDeadNodes3')
                    window = [row for row in rows if row['stage'] == 'F34Window']
                    self.assertEqual(len(window), 1)
                    self.assertEqual(window[0]['pass_instance'], 'F34Window#0')
                    pass_total = sum(row['wall_s'] for row in rows if row['scope'] == 'pass' and
                                     row['pass_instance'] in {timer for _, timer, _ in F34.calls})
                    self.assertGreaterEqual(window[0]['wall_s'], pass_total)
                else:
                    self.assertEqual(rows[0]['stage'], 'F34BatchPrefix')
                    self.assertEqual(len(rows), 5)

    def test_f34_inventories(self):
        for phase, count in (('F34R0', 1), ('F34Alias', 2), ('F34', 5)):
            with self.subTest(phase=phase):
                case, rows, _ = self.run_gsim(None, '--semantic-node-exchange={case}/snapshot',
                                             '--semantic-node-exchange-mode=snapshot',
                                             '--semantic-node-exchange-stage=' + phase, events=phase != 'F34R0')
                snapshots = sorted((case / 'snapshot').iterdir())
                self.assertEqual([path.name for path in snapshots], ['R' + str(i) for i in range(count)])
                run_ids, snapshot_ids = set(), set()
                stages = ['RemoveDeadNodes2', *(stage for _, _, stage in F34.calls)]
                for directory, stage in zip(snapshots, stages):
                    records = {}
                    for name in ('nodes.tsv', 'connections.tsv', 'node-details.tsv', 'bit-slices.tsv',
                                 'execution-membership.tsv'):
                        lines = (directory / name).read_text().splitlines()
                        records[name] = (json.loads(lines[0].split('\t', 1)[1]),
                                         json.loads(lines[-1].split('\t', 1)[1]))
                    nodes, inventory = records['nodes.tsv']
                    for metadata, footer in records.values():
                        self.assertEqual(metadata['stage'], stage)
                        self.assertEqual(metadata['snapshot_id'], nodes['snapshot_id'])
                        self.assertEqual(metadata['run_id'], nodes['run_id'])
                        self.assertTrue(footer['complete'])
                    membership = records['execution-membership.tsv'][1]
                    self.assertEqual(inventory['rowCount'], membership['rowCount'])
                    self.assertEqual(inventory['rowCount'], sum(membership[field] for field in
                                     ('activeComputation', 'inlineConstantSource', 'sourceCatalog')))
                    run_ids.add(nodes['run_id'])
                    snapshot_ids.add(nodes['snapshot_id'])
                self.assertEqual(len(run_ids), 1)
                self.assertEqual(len(snapshot_ids), count)
                self.assertEqual(rows[-1]['stage'], stages[count-1])
                if phase == 'F34':
                    self.assert_f34_events(case, rows, 1)
                elif phase == 'F34Alias':
                    events = jsonl(case / 'events.jsonl')
                    self.assertEqual([(event['logical_instance'], event['input_boundary'], event['event'])
                                      for event in events],
                                     [('alias-analysis#0', 'R0', 'start'), ('alias-analysis#0', 'R0', 'end')])

    def test_pipeline_native_trace(self):
        stages = (
            ('split', 'Init', 'SplitArray'),
            ('detect-loop', 'SplitArray', 'DetectLoop'),
            ('topo-sort', 'DetectLoop', 'TopoSort'),
            ('infer-width', 'TopoSort', 'InferAllWidth'),
            ('dce', 'InferAllWidth', 'RemoveDeadNodes0'),
            ('expr-opt', 'RemoveDeadNodes0', 'ExprOpt'),
            ('used-bits', 'ExprOpt', 'UsedBits'),
            ('split-nodes', 'UsedBits', 'SplitNodes'),
            ('dce-1', 'SplitNodes', 'RemoveDeadNodes1'),
            ('constant-analysis', 'RemoveDeadNodes1', 'ConstantAnalysis'),
            ('dce-2', 'ConstantAnalysis', 'RemoveDeadNodes2'),
            ('alias-analysis', 'RemoveDeadNodes2', 'AliasAnalysis'),
            ('pattern-detect', 'AliasAnalysis', 'PatternDetect'),
            ('common-expr', 'PatternDetect', 'CommonExpr'),
            ('dce-3', 'CommonExpr', 'RemoveDeadNodes3'),
        )
        source = self.work / 'mutations.fir'
        source.write_text(MUTATIONS)
        observed = {}
        dce_boundaries = FIXTURE.with_name('dce-node-boundaries.fir')
        for fixture in (FIXTURE, dce_boundaries, source):
            with self.subTest(fixture=fixture.name):
                case, _, _ = self.run_gsim('RemoveDeadNodes3', '--semantic-node-exchange={case}/trace',
                                           '--semantic-node-exchange-pass=pipeline', source=fixture)
                plain, _, _ = self.run_gsim(None, '--semantic-node-exchange={case}/plain',
                                            '--semantic-node-exchange-mode=snapshot',
                                            '--semantic-node-exchange-stage=F34', source=fixture)
                trace = case / 'trace'
                prev = None
                for directory, before, after in stages:
                    bundle = trace / directory
                    result = verify_bundle(bundle, bundle / 'verified.sqlite')
                    self.assertTrue(result['replay_exact'])
                    before_lines = (bundle / 'before.nodes.tsv').read_text().splitlines()
                    after_lines = (bundle / 'after.nodes.tsv').read_text().splitlines()
                    for lines, stage in ((before_lines, before), (after_lines, after)):
                        self.assertEqual(json.loads(lines[0].split('\t', 1)[1])['stage'], stage)
                    if prev is not None:
                        self.assertEqual(prev, before_lines[1:])
                    prev = after_lines[1:]
                    mutations = bundle / 'native-mutations.jsonl'
                    if mutations.exists():
                        header, *changes, footer = jsonl(mutations)
                        self.assertEqual(header['record'], 'header')
                        self.assertEqual([change['seq'] for change in changes], list(range(1, len(changes) + 1)))
                        self.assertEqual(footer, {'record': 'footer', 'complete': True, 'mutation_count': len(changes)})
                        observed.setdefault(directory, set()).update(change['reason'] for change in changes)
                    if after in ('RemoveDeadNodes2', 'AliasAnalysis', 'PatternDetect', 'CommonExpr', 'RemoveDeadNodes3'):
                        index = ('RemoveDeadNodes2', 'AliasAnalysis', 'PatternDetect', 'CommonExpr', 'RemoveDeadNodes3').index(after)
                        expected = plain / 'plain' / f'R{index}'
                        for file in ('nodes.tsv', 'node-details.tsv', 'bit-slices.tsv'):
                            self.assertEqual((bundle / ('after.' + file)).read_text().splitlines()[1:],
                                             (expected / file).read_text().splitlines()[1:])
                self.assertEqual(observed['detect-loop'], set())
                self.assertEqual(observed['topo-sort'], set())
        for directory, reason in (('expr-opt', 'equal_mux_arms'), ('used-bits', 'limit_node_to_used_bits'),
                                  ('split-nodes', 'bit_slice'),
                                  ('constant-analysis', 'constant_node'), ('alias-analysis', 'identity_alias'),
                                  ('alias-analysis', 'native_clock_refers_to_retired_node'),
                                  ('pattern-detect', 'one_hot_bit_test'), ('common-expr', 'common_expression_operand')):
            self.assertIn(reason, observed[directory])

    def test_select_single_native_trace(self):
        case, _, _ = self.run_gsim('ExprOpt', '--semantic-node-exchange={case}/trace',
                                   '--semantic-node-exchange-pass=ExprOpt')
        bundle = case / 'trace'
        self.assertTrue(verify_bundle(bundle)['replay_exact'])
        self.assertFalse((bundle / 'split').exists())
        mutations = jsonl(bundle / 'native-mutations.jsonl')
        self.assertEqual(mutations[0]['pass_instance'], 'ExprOpt#0')
        self.assertTrue(any(row.get('reason') == 'equal_mux_arms' for row in mutations))

    def test_alias_trace_includes_lvalue_rewrite(self):
        source = self.work / 'alias-lvalue.fir'
        source.write_text(ALIAS_LVALUE)
        case, _, _ = self.run_gsim('AliasAnalysis', '--trace-alias-analysis={case}/trace.jsonl', source=source)
        rows = jsonl(case / 'trace.jsonl')
        migrations = [row for row in rows if row['record'] == 'migration']
        self.assertEqual([(row['fromName'], row['toName']) for row in migrations],
                         [('indexAlias', 'indexSource')])
        rewrites = [row for row in rows if row['record'] == 'event' and row['action'] == 'replace']
        self.assertEqual(len(rewrites), 1)
        mutations = [row for row in rows if row['record'] == 'mutation' and row['action'] == 'update']
        self.assertEqual(len(mutations), 1)
        self.assertEqual((mutations[0]['eventSeq'], mutations[0]['ref']),
                         (rewrites[0]['seq'], rewrites[0]['after'][0]))
        self.assertTrue(rows[-1]['replayComplete'])

    def test_asymmetric_cat_oracle(self):
        source = self.work / 'pattern-cat.fir'
        source.write_text(CAT)
        case, _, output = self.run_gsim('RemoveDeadNodes3', '--dump-json', '--dump-assign-tree',
                                       '--dump-stages=AliasAnalysis,PatternDetect', source=source)
        matches = re.search(r'\[patternDetect\] find (\d+) pattern2', output)
        self.assertIsNotNone(matches, output)
        self.assertEqual(int(matches[1]), 1)

        def read_tree(stage):
            path, = case.glob('*' + stage + '.json')
            nodes = json.loads(path.read_text())['nodes']
            matched, = (node for node in nodes if node['name'] == 'matched')
            tree, = matched['assignTrees']
            indexed = {node['id']: node for node in tree['nodes']}
            return tree['root'], indexed

        def truth_table(tree):
            root, nodes = tree

            def evaluate(index, inputs):
                node = nodes[index]
                if node['nodeId'] is not None:
                    return inputs[node['node']]
                if node['op'] == 'OP_INT':
                    literal = node['strVal']
                    return int(literal[2:], 16) if literal.startswith('0h') else int(literal, 0)
                left, right = node['children']
                a, b = evaluate(left, inputs), evaluate(right, inputs)
                if node['op'] == 'OP_CAT':
                    return (a << nodes[right]['width']) | b
                if node['op'] == 'OP_EQ':
                    return int(a == b)
                if node['op'] == 'OP_AND':
                    return a & b
                self.fail('unsupported GSIM fixture expression: ' + str(node))

            return [(high, low) for high in range(4) for low in range(8)
                    if evaluate(root, {'high': high, 'low': low})]

        self.assertEqual(truth_table(read_tree('AliasAnalysis')), [(1, 5)])
        # The reference drops bit 3 of 0b01101 when it slices the high field.
        self.assertEqual(truth_table(read_tree('PatternDetect')), [(0, 5)])


if __name__ == '__main__':
    unittest.main()
