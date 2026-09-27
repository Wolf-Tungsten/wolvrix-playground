"""Independent truth tables and ownership failures for the one-bit census."""

from copy import deepcopy
import itertools
from pathlib import Path
import random
from types import SimpleNamespace
import tempfile
import unittest
import json

from grhsim_bit_update_census import (
    BDD, Model, analyze, check_dynamic, compare_identity, counter_sites, exclusive_ops,
    gsim_details, literal_bit,
)


class Fixture:
    def __init__(self):
        self.m = {'strings': [], 'types': [[1, 0, 'logic', 1, False, '2-state'],
                                          [2, 0, 'logic', 2, False, '2-state']],
                  'values': [], 'operations': [], 'states': [], 'init': []}
        self.q = self.state('unrelated_7', 0)
        self.hist = self.state('past', 0)
        self.old = self.op('core.state.read', [], refs=[['state', self.q]])
        self.en = self.op('core.input.read', [])
        self.mask = self.op('core.input.read', [])
        self.clk = self.op('core.input.read', [])
        self.one = self.op('core.compute.constant', [], params={'constValue': "1'b1"})
        self.zero = self.op('core.compute.constant', [], params={'constValue': "1'b0"})

    def intern(self, s):
        if s not in self.m['strings']:
            self.m['strings'].append(s)
        return self.m['strings'].index(s) + 1

    def state(self, name, init):
        sid = len(self.m['states']) + 1
        self.m['states'].append([sid, self.intern(name), 1, 0])
        self.m['init'].append([sid, [[self.intern('core.init.const'),
                                     [[self.intern('value'), 'string', f"1'b{init}"]]]]])
        return sid

    def op(self, kind, args, refs=None, params=None, width=1, name=''):
        oid, value = len(self.m['operations']) + 1, len(self.m['values']) + 1
        self.m['values'].append([value, width, self.intern(name) if name else 0, 0])
        self.m['operations'].append([oid, self.intern(kind), 0, 0, args, [value], refs or [],
                                     [[self.intern(k), 'string', v] for k, v in (params or {}).items()]])
        return value

    def write(self, data, en=None, mask=None, q=None, hist=None, edge='posedge'):
        oid = len(self.m['operations']) + 1
        self.m['operations'].append([oid, self.intern('core.state.regWrite'), 0, 0,
                                     [self.en if en is None else en, data,
                                      self.mask if mask is None else mask, self.clk], [],
                                     [['state', self.q if q is None else q], ['state', self.hist if hist is None else hist]],
                                     [[self.intern('event_edges'), 'strings', [edge]]]])
        return oid

    def proof(self, oid):
        v = Model(self.m)
        local, _ = v.local(v.ops[oid][4][:3])
        return v.proof(self.q, oid, local)

    def mapping(self):
        compute = [o[0] for o in self.m['operations'] if self.m['strings'][o[1]-1] != 'core.state.regWrite']
        self.m['mappings'] = [[[0, 0, [[100, 0, 3, 0, [], compute],
                                      [10, 0, 6, 0, [11], []], [11, 10, 5, 0, [100], []]], [],
                               [[[None, [[None, [[1, 10, None, 0]]]]]]]]]]


class BitUpdatesTest(unittest.TestCase):
    def test_literal_rejects_unknown_and_wrong_width(self):
        for text, expected in (("1'b0", 0), ("1'sh1", 1), ('0', 0), ("'1", 1), ("1'bx", None),
                               ("2'b01", None), ('garbage', None)):
            self.assertEqual(literal_bit(text), expected)

    def test_raw_zero_event_initial(self):
        f = Fixture()
        first = f.write(f.one)
        f.m['init'][1][1][0][1][0][2] = '0'
        self.assertEqual(Model(f.m).group_key(f.q, first)[1], 'eligible')

    def test_group_calls_differ_from_publish_sites(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'model.cpp'
            p.write_text('++cpu_dyn_sn_grp[7];\n++cpu_dyn_sn_grp[7];\n'
                         'cpu_dyn_sn_chg[7]+=cpu_dyn_any;\n'
                         '                    ++cpu_dyn_grp_pub;\n')
            groups, pubs = counter_sites(d)
            self.assertEqual(dict(groups), {7: 2})
            self.assertEqual(dict(pubs), {7: 1})
            p.write_text('++cpu_dyn_sn_grp[7];')
            with self.assertRaisesRegex(ValueError, 'counter sites'):
                counter_sites(d)

    def test_bdd_random_circuits_against_exhaustive_truth(self):
        rng = random.Random(25)
        bdd = BDD()
        nodes = [(bdd.node(i, 0, 1), lambda x, i=i: x[i]) for i in range(5)]
        nodes += [(0, lambda _: 0), (1, lambda _: 1)]
        for _ in range(100):
            a, b, c = [rng.choice(nodes) for _ in range(3)]
            node = bdd.ite(a[0], b[0], c[0])
            formula = lambda x, a=a, b=b, c=c: b[1](x) if a[1](x) else c[1](x)
            for bits in itertools.product((0, 1), repeat=5):
                self.assertEqual(bdd.evaluate(node, bits), formula(bits))
            nodes.append((node, formula))

    def test_bdd_cofactor_truth(self):
        bdd = BDD()
        q, set_, clear = [bdd.node(i, 0, 1) for i in range(3)]
        expr = bdd.ite(clear, 0, bdd.ite(set_, 1, q))
        for old in (0, 1):
            f = bdd.restrict(expr, 0, old)
            for s, c in itertools.product((0, 1), repeat=2):
                self.assertEqual(bdd.evaluate(f, {1: s, 2: c}), int(not c and (s or old)))

    def test_bdd_canonical_and_budget(self):
        bdd = BDD(limit=4)
        a, b = bdd.node(1, 0, 1), bdd.node(2, 0, 1)
        self.assertEqual(a, bdd.node(1, 0, 1))
        self.assertEqual(a, bdd.node(5, a, a))
        with self.assertRaisesRegex(ValueError, 'bdd_budget'):
            bdd.ite(a, b, 0)

    def test_clear_priority_and_hold_proof(self):
        f = Fixture()
        set_ = f.op('core.input.read', [])
        clear = f.op('core.input.read', [])
        data = f.op('core.compute.and', [f.op('core.compute.not', [clear]),
                                        f.op('core.compute.or', [set_, f.old])])
        oid = f.write(data)
        self.assertEqual(f.proof(oid)['status'], 'set_clear_hold')
        for q, en, mask, s, c in itertools.product((0, 1), repeat=5):
            direct = ((not c) and (s or q)) if en and mask else q
            set_when = en and mask and not c and s
            clear_when = en and mask and c
            self.assertEqual(direct, (q or set_when) and not clear_when)

    def test_toggle_is_not_set_clear(self):
        f = Fixture()
        oid = f.write(f.op('core.compute.not', [f.old]))
        self.assertEqual(f.proof(oid)['status'], 'may_toggle')

    def test_zero_mask_always_holds(self):
        f = Fixture()
        result = f.proof(f.write(f.one, mask=f.zero))
        self.assertTrue(result['always_hold'])

    def test_redundant_enable_proven(self):
        f = Fixture()
        data = f.op('core.compute.bitSelect', [f.en, f.one, f.old])
        self.assertTrue(f.proof(f.write(data, mask=f.one))['enable_mask_redundant'])

    def test_opaque_feedback_not_assumed_independent(self):
        f = Fixture()
        hidden = f.op('core.compute.not', [f.old], name='visible_signal')
        data = f.op('core.compute.and', [f.en, hidden])
        self.assertEqual(f.proof(f.write(data))['status'], 'hidden_feedback')

    def test_unknown_constant_not_given_false_value(self):
        f = Fixture()
        unknown = f.op('core.compute.constant', [], params={'constValue': "1'bx"})
        result = f.proof(f.write(unknown))
        self.assertGreater(result['atoms'], 0)

    def test_named_boundaries_and_roots(self):
        f = Fixture()
        a = f.op('core.compute.not', [f.en], name='public')
        b = f.op('core.compute.not', [a])
        view = Model(f.m)
        self.assertEqual(view.local([b]), ({b}, {a}))
        self.assertEqual(view.local([a]), ({a}, {f.en}))

    def test_external_use_retains_all_upstream_dependencies(self):
        f = Fixture()
        a = f.op('core.compute.not', [f.en])
        b = f.op('core.compute.or', [a, f.mask])
        c = f.op('core.compute.and', [b, f.old])
        oid = f.write(c)
        f.op('core.compute.xor', [b, f.clk], name='unrelated_observer')
        view = Model(f.m)
        self.assertEqual(exclusive_ops(view, {a, b, c}, {oid}), {c})

    def test_shared_subgraph_removed_only_with_both_sinks(self):
        f = Fixture()
        a = f.op('core.compute.not', [f.en])
        first = f.write(a)
        q, hist = f.state('another_17', 0), f.state('other_past', 0)
        second = f.write(a, q=q, hist=hist)
        view = Model(f.m)
        self.assertFalse(exclusive_ops(view, {a}, {first}))
        self.assertEqual(exclusive_ops(view, {a}, {first, second}), {a})

    def test_event_input_is_never_a_removable_data_dependency(self):
        f = Fixture()
        a = f.op('core.compute.not', [f.en])
        oid = f.write(a)
        f.m['operations'][oid-1][4][3] = a
        self.assertFalse(exclusive_ops(Model(f.m), {a}, {oid}))

    def test_group_excludes_enable_but_preserves_event_and_initial(self):
        f = Fixture()
        first = f.write(f.one)
        q, hist = f.state('strange_42', 0), f.state('other_past', 0)
        second = f.write(f.zero, en=f.mask, q=q, hist=hist)
        view = Model(f.m)
        self.assertEqual(view.group_key(f.q, first)[0], view.group_key(q, second)[0])
        f.m['operations'][-1][7][0][2] = ['negedge']
        view = Model(f.m)
        self.assertNotEqual(view.group_key(f.q, first)[0], view.group_key(q, second)[0])

    def test_shared_history_is_rejected(self):
        f = Fixture()
        first = f.write(f.one)
        q = f.state('strange_42', 0)
        f.write(f.zero, q=q)
        self.assertEqual(Model(f.m).group_key(f.q, first)[1], 'nonprivate_or_unknown_history')

    def test_unknown_initial_rejected(self):
        f = Fixture()
        first = f.write(f.one)
        f.m['init'][0][1][0][1][0][2] = "1'bx"
        self.assertEqual(Model(f.m).group_key(f.q, first)[1], 'target_initial_unknown')

    def test_initial_values_split_groups(self):
        f = Fixture()
        first = f.write(f.one)
        q, hist = f.state('different', 0), f.state('different_past', 1)
        second = f.write(f.one, q=q, hist=hist)
        view = Model(f.m)
        self.assertNotEqual(view.group_key(f.q, first)[0], view.group_key(q, second)[0])
        f.m['init'][-1][1][0][1][0][2] = "1'b0"
        f.m['init'][-2][1][0][1][0][2] = "1'b1"
        view = Model(f.m)
        self.assertNotEqual(view.group_key(f.q, first)[0], view.group_key(q, second)[0])

    def test_multiple_writers_rejected(self):
        f = Fixture()
        first = f.write(f.one)
        f.write(f.zero)
        self.assertEqual(Model(f.m).group_key(f.q, first)[1], 'multiple_writers')

    def test_non_boolean_and_signed_targets_excluded(self):
        for pos, value in ((3, 2), (4, True), (5, '4-state')):
            f = Fixture()
            f.write(f.one)
            f.m['types'][0][pos] = value
            self.assertFalse(Model(f.m).bit_type(1))

    def test_analysis_deduplicates_and_requires_all_counters(self):
        f = Fixture()
        data = f.op('core.compute.not', [f.en])
        f.write(data)
        q, hist = f.state('strange_42', 0), f.state('other_past', 0)
        f.write(data, q=q, hist=hist)
        f.mapping()
        result = analyze(f.m, {100: 11}, 5)
        self.assertEqual(result['coverage'], {'bit_writers': 2, 'eligible': 2})
        self.assertEqual(result['local_execs'], 11)
        self.assertEqual(result['exclusive_execs'], 11)
        self.assertEqual(result['groups'][0]['rows'], 2)
        with self.assertRaisesRegex(ValueError, 'coverage mismatch'):
            analyze(f.m, {}, 5)

    def test_analysis_does_not_mutate_input(self):
        f = Fixture()
        f.write(f.op('core.compute.not', [f.en]))
        f.mapping()
        original = deepcopy(f.m)
        self.assertEqual(analyze(f.m, {100: 11}, 5), analyze(f.m, {100: 11}, 5))
        self.assertEqual(original, f.m)

    def test_production_identity_and_pre_string_suffix(self):
        f = Fixture()
        f.write(f.one)
        f.mapping()
        for key in ('inputs', 'outputs', 'interface', 'functions', 'origins'):
            f.m[key] = []
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for name in ('pre', 'final', 'parent', 'dynamic'):
                folder = Path(directory) / name
                folder.mkdir()
                paths[name] = folder / 'checkpoint.json'
                paths[name].write_text(json.dumps(f.m))
                (folder / 'model').mkdir()
                (folder / 'model' / 'a.cpp').write_text('same source')
            pre = deepcopy(f.m)
            pre['mappings'] = []
            paths['pre'].write_text(json.dumps(pre))
            for name in ('final', 'parent', 'dynamic'):
                copied = deepcopy(f.m)
                copied['strings'].append('backend-new-string')
                paths[name].write_text(json.dumps(copied))
            args = SimpleNamespace(**paths)
            self.assertEqual(compare_identity(args)['pre']['backend_appended_strings'], 1)
            pre['strings'][0] = 'changed'
            paths['pre'].write_text(json.dumps(pre))
            with self.assertRaisesRegex(ValueError, 'referenced strings differ'):
                compare_identity(args)
            paths['pre'].write_text(json.dumps(f.m))
            paths['dynamic'].write_text('{}')
            with self.assertRaisesRegex(ValueError, 'checkpoint bytes differ'):
                compare_identity(args)

    def test_dynamic_two_runs_and_runtime_closure(self):
        f = Fixture()
        f.write(f.one)
        f.mapping()
        endpoint = ('Difftest enabled\ninstrCnt = 240349, cycleCnt = 99996\n'
                    'Guest cycle spent: 100001\nEXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c\n'
                    'Host time spent: 123ms\ncycles=100000 max_cycles=100000\n')
        log = (endpoint + '[grhsim-dyn] sn 100 act=10 body=10 grp=20 chg=3\n'
               '[grhsim-dyn] totals grp_pub=10 grp_fire=3\n')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / 'a.cpp').write_text('++cpu_dyn_sn_grp[100];++cpu_dyn_sn_grp[100];\n'
                                      'cpu_dyn_sn_chg[100]+=cpu_dyn_any;\n'
                                      '                    ++cpu_dyn_grp_pub;\n')
            a, b = path / 'a.log', path / 'b.log'
            a.write_text(log)
            b.write_text(log)
            fires, cycles, result = check_dynamic(f.m, a, b, path)
            self.assertEqual(fires, {100: 10})
            self.assertEqual(cycles, 100001)
            self.assertEqual(result['compute_execs'], 60)
            b.write_text(log.replace('body=10', 'body=11'))
            with self.assertRaisesRegex(ValueError, 'counters differ'):
                check_dynamic(f.m, a, b, path)
            b.write_text(log.replace('grp_pub=10', 'grp_pub=11'))
            with self.assertRaisesRegex(ValueError, 'publish counter closure'):
                check_dynamic(f.m, a, b, path)
            b.write_text(log.replace('grp=20', 'grp=21'))
            with self.assertRaisesRegex(ValueError, 'group-call counter closure'):
                check_dynamic(f.m, a, b, path)
            b.write_text(log.replace('grp_fire=3', 'grp_fire=4'))
            with self.assertRaisesRegex(ValueError, 'group-fire counter closure'):
                check_dynamic(f.m, a, b, path)

    def test_gsim_pair_and_reference_expansion(self):
        def tree(ref):
            return [{'root': 0, 'nodes': [{'op': 'OP_EMPTY', 'node': ref, 'children': []}]}]
        payload = {'nodes': [
            {'name': 'top__DOT__q_9', 'width': 1, 'type': 'NODE_REG_SRC', 'assignTrees': tree('dst')},
            {'name': 'dst', 'width': 1, 'type': 'NODE_REG_DST', 'assignTrees': tree('intermediate')},
            {'name': 'intermediate', 'width': 1, 'type': 'NODE_OTHERS', 'assignTrees': tree('input')},
            {'name': 'input', 'width': 1, 'type': 'NODE_INP', 'assignTrees': []},
        ]}
        analysis = {'groups': [{'sample': {'state': 'top$q_9'}}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'gsim.json'
            p.write_text(json.dumps(payload))
            detail = gsim_details(p, analysis)[0]
            self.assertEqual(detail['status'], 'matched')
            self.assertEqual({n['name'] for n in detail['nodes']}, {'dst', 'intermediate', 'input'})
            payload['nodes'][0]['width'] = 2
            p.write_text(json.dumps(payload))
            self.assertEqual(gsim_details(p, analysis)[0]['status'], 'ambiguous_or_missing_name_width')
            payload['nodes'][0]['width'] = 1
            payload['nodes'].pop()
            p.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'missing gsim'):
                gsim_details(p, analysis)


if __name__ == '__main__':
    unittest.main()
