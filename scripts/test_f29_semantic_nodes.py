"""F29 native Node edits: independent replay and ordinary pipeline integration."""
from copy import deepcopy
from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from compare_f28_semantic_tree import ROOT, compare, qualified, verify_node_trace


def node(identifier, name, operations=(), anchors=()):
    return {'id': identifier, 'parent': 1, 'name': name,
            'operations': [{'id': item, 'generation': 0} for item in operations],
            'anchors': [{'id': item, 'generation': 0} for item in anchors]}


def compare_native_relations(grh_traces, gsim_trace, output):
    """Compare native Node dispositions on small fixtures, entirely in memory.

    This consumer does not infer members from suffixes or expand a many-to-many
    boundary event into a Cartesian set of parent/member correspondences.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def read_trace(path):
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        if (not rows or rows[0].get('record') != 'header' or rows[-1].get('record') != 'footer' or
                not rows[-1].get('complete') or not rows[-1].get('replayComplete')):
            raise ValueError('incomplete native evolution evidence')
        return rows

    grh = []
    for path in grh_traces:
        rows = read_trace(path)
        before = {row['state']['id']: row['state'] for row in rows
                  if row['record'] == 'node' and row['stage'] == 'before'}
        after = {row['state']['id']: row['state'] for row in rows
                 if row['record'] == 'node' and row['stage'] == 'after'}
        grh.append((rows[0]['pass'], before, after,
                    [row for row in rows if row['record'] == 'event']))
    if not grh:
        raise ValueError('missing GRH native Node traces')
    # Composition starts at flatten, then applies comb and split in pipeline order.
    order = {'comb-loop-elim': 0, 'split-static-array': 1}
    grh.sort(key=lambda trace: order[trace[0]])
    for previous, following in zip(grh, grh[1:]):
        if previous[2] != following[1]:
            raise ValueError('GRH evolution traces do not join at the actual pass boundary')
    grh_before, grh_after = grh[0][1], grh[-1][2]
    grh_relations = {identifier: {'targets': {identifier}, 'certain': True,
                                 'evidence': [], 'side_effect': False}
                     for identifier in grh_before}
    unassigned_additions = []
    for pass_name, before, after, events in grh:
        for event in events:
            old = {state['id'] for state in event['before']}
            new = {state['id'] for state in event['after']}
            retained, removed, created = old & new, old - new, new - old
            evidence = {'pass': pass_name, 'seq': event['seq'], 'reason': event['reason'],
                        'before_ids': sorted(old), 'after_ids': sorted(new)}
            if created and not removed:
                unassigned_additions.append({**evidence, 'added_ids': sorted(created)})
            for relation in grh_relations.values():
                touched = relation['targets'] & old
                if not touched:
                    continue
                relation['evidence'].append(evidence)
                if touched & retained:
                    relation['side_effect'] = True
                consumed = touched & removed
                if consumed:
                    relation['targets'].difference_update(consumed)
                    relation['targets'].update(created)
                    if len(removed) > 1 and len(created) > 1:
                        relation['certain'] = False
                elif created and not removed:
                    # A residual parent and new siblings share an event. The
                    # event alone cannot assign its additions to retained owners.
                    relation['targets'].update(created)
                    relation['certain'] = False
        if any(not relation['targets'] <= after.keys() for relation in grh_relations.values()):
            raise ValueError('GRH relation refers to a missing pass-after Node')

    native = read_trace(gsim_trace)
    if native[0].get('engine') != 'gsim':
        raise ValueError('expected GSIM native evolution evidence')
    inventories = {stage: {row['ref']['id']: row for row in native
                           if row['record'] == 'entity' and row['stage'] == stage}
                   for stage in ('before', 'after')}
    gs_before, gs_after = inventories['before'], inventories['after']
    body = lambda row: {key: value for key, value in row.items() if key not in ('record', 'stage', 'ref')}
    replayed = {identifier: body(row) for identifier, row in gs_before.items()}
    events = [row for row in native if row['record'] == 'event']
    for sequence, mutation in enumerate((row for row in native if row['record'] == 'mutation'), 1):
        identifier = mutation['ref']['id']
        if mutation['seq'] != sequence or not 1 <= mutation['eventSeq'] <= len(events):
            raise ValueError('invalid GSIM native mutation sequence')
        if mutation['action'] == 'create':
            if identifier in replayed or mutation['expect'] or mutation['unset']:
                raise ValueError('invalid GSIM native creation')
            replayed[identifier] = deepcopy(mutation['set'])
        elif mutation['action'] == 'erase':
            if replayed.pop(identifier) != mutation['expect'] or mutation['set'] or mutation['unset']:
                raise ValueError('invalid GSIM native deletion')
        elif mutation['action'] == 'update':
            current = replayed[identifier]
            if {key: current[key] for key in mutation['expect']} != mutation['expect']:
                raise ValueError('GSIM native update precondition failed')
            for key in mutation['unset']:
                del current[key]
            current.update(deepcopy(mutation['set']))
        else:
            raise ValueError('unsupported GSIM native mutation')
    if replayed != {identifier: body(row) for identifier, row in gs_after.items()}:
        raise ValueError('GSIM before plus native mutations differs from actual after')

    split_edges, gs_evidence = {}, defaultdict(list)
    for event in events:
        for step in event.get('steps', ()):
            for ref in step['before']:
                gs_evidence[ref['id']].append({'event': event['seq'], 'step': step['seq'],
                                               'action': step['action'], 'reason': step['reason']})
            if step['action'] == 'split' and len(step['before']) == 1:
                parent = step['before'][0]['id']
                if parent in split_edges:
                    raise ValueError('GSIM parent has multiple native split decisions')
                split_edges[parent] = {ref['id'] for ref in step['after']}

    def gs_descendants(identifier, active=frozenset()):
        if identifier in gs_after:
            return {identifier}, True
        if identifier in active or identifier not in split_edges:
            return set(), False
        targets, certain = set(), True
        for child in split_edges[identifier]:
            members, verified = gs_descendants(child, active | {identifier})
            targets.update(members)
            certain = certain and verified
        return targets, certain

    gs_names = defaultdict(list)
    grh_names = Counter(state['name'] for state in grh_before.values())
    for identifier, state in gs_before.items():
        gs_names[qualified(state['nodePath'])].append(identifier)
    rows = []
    for identifier, state in sorted(grh_before.items()):
        relation = grh_relations[identifier]
        name = state['name']
        candidates = gs_names[name]
        actual_names = sorted(grh_after[target]['name'] for target in relation['targets'])
        entry = {'grh_before_id': identifier, 'before_name': name, 'grh_after_names': actual_names,
                 'grh_after_ids': sorted(relation['targets']), 'grh_relation_exact': relation['certain'],
                 'grh_evidence': relation['evidence'], 'grh_same_identity_rewrite': relation['side_effect'],
                 'gsim_before_id': None, 'gsim_after_names': [], 'gsim_after_ids': [],
                 'gsim_relation_exact': False, 'gsim_evidence': [], 'gsim_same_identity_rewrite': False}
        if len(candidates) != 1 or grh_names[name] != 1:
            entry['disposition'] = 'unpaired'
        else:
            native_id = candidates[0]
            descendants, certain = gs_descendants(native_id)
            descendant_names = sorted(qualified(gs_after[target]['nodePath']) for target in descendants)
            entry.update({'gsim_before_id': native_id, 'gsim_after_names': descendant_names,
                          'gsim_after_ids': sorted(descendants), 'gsim_relation_exact': certain,
                          'gsim_evidence': gs_evidence[native_id],
                          'gsim_same_identity_rewrite': native_id in gs_after and
                              body(gs_before[native_id]) != body(gs_after[native_id])})
            if not relation['certain'] or not certain:
                entry['disposition'] = 'identity-unverified'
            else:
                # Names locate the already explicit native dispositions. This
                # comparison never claims internal op/ENode behavior equality.
                grh_identity = relation['targets'] == {identifier}
                gs_identity = descendants == {native_id}
                entry['disposition'] = ('trace relation matched' if
                    actual_names == descendant_names and grh_identity == gs_identity else 'different')
        rows.append(entry)

    columns = ['grh_before_id', 'before_name', 'grh_after_names', 'gsim_before_id', 'gsim_after_names',
               'disposition', 'grh_relation_exact', 'gsim_relation_exact',
               'grh_same_identity_rewrite', 'gsim_same_identity_rewrite', 'grh_evidence', 'gsim_evidence']
    with (output / 'node-relations.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(columns)
        for row in rows:
            writer.writerow([json.dumps(row[key], ensure_ascii=False, sort_keys=True)
                             if isinstance(row[key], (list, dict)) else row[key] for key in columns])
    summary = {'complete': True, 'scope': 'small-fixture-in-memory-native-evolution',
               'grh_before_nodes': len(grh_before), 'grh_after_nodes': len(grh_after),
               'gsim_before_nodes': len(gs_before), 'gsim_after_nodes': len(gs_after),
               'gsim_replay_exact': True, 'dispositions': dict(Counter(row['disposition'] for row in rows)),
               'same_identity_rewrites': {side: sum(row[side + '_same_identity_rewrite'] for row in rows)
                                          for side in ('grh', 'gsim')},
               'grh_unassigned_addition_events': unassigned_additions,
               'rows': rows, 'tsv': str(output / 'node-relations.tsv'),
               'limitations': ['Before qualified names locate candidates; native IDs and events define dispositions.',
                               'Many-to-many GRH replacements without per-parent maps remain identity-unverified.',
                               'Candidate descendant sets in unverified rows are not per-element correspondences.',
                               'Same-ID consumer rewrites are listed separately from parent splits.',
                               'Matched dispositions do not establish op/ENode structure or behavior equality.',
                               'This regression helper reads small traces in memory and is not an entire-design workflow.']}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    return {key: value for key, value in summary.items() if key != 'rows'}


class NodeReplayTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / 'ptmp' / 'firrtl-ingest' / 'F29' / 'replay-tests'
        work.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(dir=work))
        self.before = node(1, 'a', [1], [1])
        self.first = node(2, 'a_0', [2], [2])
        self.second = node(3, 'a_1', [3], [3])
        self.rows = [
            {'record': 'header', 'schema': 'wolvrix.semantic-node-evolution.v1',
             'replayContract': 'semantic-node-replace.v1', 'pass': 'split-static-array', 'graph': 'Top'},
            {'record': 'node', 'stage': 'before', 'state': self.before},
            {'record': 'event', 'seq': 1, 'action': 'replace', 'reason': 'array_members',
             'before': [self.before], 'after': [self.first, self.second]},
            {'record': 'node', 'stage': 'after', 'state': self.first},
            {'record': 'node', 'stage': 'after', 'state': self.second},
            {'record': 'footer', 'complete': True, 'replayComplete': True,
             'beforeCount': 1, 'afterCount': 2, 'eventCount': 1}]

    def tearDown(self):
        shutil.rmtree(self.directory)

    def replay(self, rows=None):
        path = self.directory / 'trace.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in (self.rows if rows is None else rows)))
        return verify_node_trace(path)

    def test_one_to_many_replacement(self):
        self.assertEqual(self.replay()['actions'], {'add': 0, 'delete': 0, 'replace': 1})

    def test_same_id_replacement_then_many_to_one(self):
        changed = node(2, 'renamed', [4], [2])
        merged = node(4, 'merged', [4, 3], [4])
        rows = deepcopy(self.rows[:3]) + [
            {'record': 'event', 'seq': 2, 'action': 'replace', 'reason': 'rewrite',
             'before': [self.first], 'after': [changed]},
            {'record': 'event', 'seq': 3, 'action': 'replace', 'reason': 'merge',
             'before': [changed, self.second], 'after': [merged]},
            {'record': 'node', 'stage': 'after', 'state': merged},
            {'record': 'footer', 'complete': True, 'replayComplete': True,
             'beforeCount': 1, 'afterCount': 1, 'eventCount': 3}]
        self.assertEqual(self.replay(rows)['actions']['replace'], 3)

    def test_add_and_delete(self):
        rows = deepcopy(self.rows)
        rows[2:3] = [
            {'record': 'event', 'seq': 1, 'action': 'delete', 'reason': 'erase', 'before': [self.before], 'after': []},
            {'record': 'event', 'seq': 2, 'action': 'add', 'reason': 'create', 'before': [],
             'after': [self.first, self.second]}]
        rows[-1]['eventCount'] = 2
        self.assertEqual(self.replay(rows)['actions'], {'add': 1, 'delete': 1, 'replace': 0})

    def test_missing_event_is_rejected(self):
        del self.rows[2]
        with self.assertRaises(ValueError):
            self.replay()

    def test_stale_before_is_rejected(self):
        self.rows[2] = deepcopy(self.rows[2])
        self.rows[2]['before'][0]['name'] = 'incorrect'
        with self.assertRaises(ValueError):
            self.replay()

    def test_incorrect_actual_after_is_rejected(self):
        self.rows[3] = deepcopy(self.rows[3])
        self.rows[3]['state']['anchors'] = []
        with self.assertRaises(ValueError):
            self.replay()

    def test_deleted_id_cannot_be_reused(self):
        self.rows[2:3] = [
            {'record': 'event', 'seq': 1, 'action': 'delete', 'reason': 'erase', 'before': [self.before], 'after': []},
            {'record': 'event', 'seq': 2, 'action': 'add', 'reason': 'invalid_reuse', 'before': [], 'after': [self.before]}]
        with self.assertRaises(ValueError):
            self.replay()

    def test_action_and_cardinality_must_agree(self):
        self.rows[2]['action'] = 'add'
        with self.assertRaises(ValueError):
            self.replay()

    def test_duplicate_member_is_rejected(self):
        self.rows[2] = deepcopy(self.rows[2])
        self.rows[2]['after'][0]['operations'] *= 2
        with self.assertRaises(ValueError):
            self.replay()

    def test_truncated_trace_is_rejected(self):
        with self.assertRaises(ValueError):
            self.replay(self.rows[:-1])


class NativeTraceArtifactTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('F29_NATIVE_TRACE_ARTIFACTS'),
                         'run via make test_f29_semantic_nodes')
    def test_actual_comb_and_state_rewrites_replay(self):
        artifacts = Path(os.environ['F29_NATIVE_TRACE_ARTIFACTS'])
        reports = []
        for name in ('comb-f29-scalar.jsonl', 'comb-f29-array.jsonl', 'f29-state-nodes.jsonl'):
            with self.subTest(trace=name):
                result = verify_node_trace(artifacts / name)
                self.assertGreater(result['events'], 0)
                reports.append({'trace': str(artifacts / name), **result})
        work = Path(os.environ['F29_WORK']).resolve() / 'tests'
        work.mkdir(parents=True, exist_ok=True)
        (work / 'native-trace-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    @unittest.skipUnless(os.environ.get('F29_NATIVE_TRACE_ARTIFACTS'),
                         'run via make test_f29_semantic_nodes')
    def test_public_comb_rewrites_replay(self):
        from semantic_node_exchange import verify_bundle
        artifacts = Path(os.environ['F29_NATIVE_TRACE_ARTIFACTS'])
        reports = []
        for name in ('comb-f29-scalar-public', 'comb-f29-array-public'):
            with self.subTest(trace=name):
                result = verify_bundle(artifacts / name)
                self.assertGreater(result['events'], 0)
                reports.append({'bundle': str(artifacts / name), **result})
        work = Path(os.environ['F29_WORK']).resolve() / 'tests'
        work.mkdir(parents=True, exist_ok=True)
        (work / 'public-comb-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    @unittest.skipUnless(os.environ.get('F29_NATIVE_TRACE_ARTIFACTS'),
                         'run via make test_f29_semantic_nodes')
    def test_public_split_lineage_and_same_id_touch_replay(self):
        from semantic_node_exchange import verify_bundle, verify_snapshot
        output = Path(os.environ['F29_NATIVE_TRACE_ARTIFACTS']) / 'semantic-nodes/public-exchange'
        self.assertTrue(verify_snapshot(output / 'static')['complete'])
        result = verify_bundle(output / 'trace')
        self.assertEqual(result['events'], 2)
        self.assertEqual(result['lineage_count'], 2)
        self.assertEqual(result['actions'], {'replace': 2})


class NativePipelineTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('F29_GSIM_BINARY'), 'run via make test_f29_pipeline')
    def test_native_nodes_and_replay_at_both_boundaries(self):
        work = Path(os.environ['F29_WORK']).resolve() / 'pipeline'
        work.mkdir(parents=True, exist_ok=True)
        reports = []
        fixtures = [ROOT / 'wolvrix' / 'tests' / 'ingest' / 'data' / 'firrtl' / (name + '.fir')
                    for name in ('f28-arrays', 'f28-bundles', 'f28-state', 'f28-hierarchy',
                                 'f28-comb-boundaries', 'f28-memory-effects')]
        fixtures.append(ROOT / 'reference' / 'gsim' / 'test' / 'node-evolution.fir')
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                directory = work / fixture.stem
                for mode in ('plain', 'traced'):
                    destination = directory / mode
                    destination.mkdir(parents=True, exist_ok=True)
                    command = [sys.executable, str(ROOT / 'scripts' / 'capture_f28_semantic_tree.py'),
                               '--firrtl', str(fixture), '--output', str(destination),
                               '--gsim-binary', os.environ['F29_GSIM_BINARY'], '--through-split', '--assign-trees']
                    if mode == 'traced':
                        command.append('--trace-semantic-nodes')
                    with (destination / 'driver.log').open('w') as log:
                        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
                for stage in ('flatten', 'comb-loop-elim', 'split-static-array'):
                    self.assertEqual((directory / 'plain' / (stage + '.json')).read_bytes(),
                                     (directory / 'traced' / (stage + '.json')).read_bytes())
                traced = directory / 'traced'
                traces = sorted(traced.glob('*.nodes.jsonl'))
                self.assertEqual(len(traces), 2)
                replay = [verify_node_trace(path, path.with_suffix('.sqlite')) for path in traces]
                relations = compare_native_relations(traces, traced / 'gsim' / 'split-array.jsonl',
                                                     directory / 'trace-relations')
                # Native producers alone construct the Node inventories; this
                # consumer only reports their actual candidates and subgraphs.
                comparisons = {}
                for stage, native_stage in (('flatten', 'Init'), ('split-static-array', 'SplitArray')):
                    result = compare(traced / (stage + '.json'), traced / 'gsim',
                                     directory / ('comparison-' + stage), gsim_stage=native_stage)
                    self.assertEqual(result['grh_op_coverage']['uncovered_ops'], 0)
                    comparisons[stage] = result
                if fixture.stem == 'f28-arrays':
                    # The dynamic read keeps alias as an array Node. Its static
                    # consumer must retain this named boundary on both engines.
                    with (directory / 'comparison-split-static-array' / 'grh-nodes.tsv').open() as stream:
                        nodes = {row['qualified_name']: row
                                 for row in csv.DictReader(stream, delimiter='\t')}
                    static = nodes['staticRead']
                    self.assertEqual(static['status'], 'structural_checked')
                    self.assertNotIn('staging', nodes)
                    self.assertIn('staging_0', nodes)
                    self.assertIn('staging_1', nodes)
                    inventory = comparisons['split-static-array']['inventory']
                    self.assertEqual(inventory['grh_nodes'], 10)
                    self.assertEqual(inventory['gsim_nodes'], 10)
                reports.append({'fixture': str(fixture), 'replay': replay, 'relations': relations,
                                'comparisons': comparisons})
        (work / 'summary.json').write_text(json.dumps({'complete': True, 'fixtures': reports}, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
