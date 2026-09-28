"""Semantic and ownership counterexamples for NO00028 guarded writes."""

import copy
from pathlib import Path
import tempfile
import unittest

from grhsim_guarded_write_census import (
    BooleanProof, Refused, View, census, dead_candidates, prove_write, verify_production,
)


class Fixture:
    def __init__(self):
        self.model = {'strings': [], 'operations': [], 'values': [], 'states': [],
                      'types': [[1, 0, 'logic', 1, False, '2-state'],
                                [2, 0, 'logic', 8, False, '2-state'],
                                [3, 0, 'logic', 8, True, '2-state'],
                                [4, 0, 'logic', 1, False, '4-state']]}

    def string(self, text):
        if text not in self.model['strings']:
            self.model['strings'].append(text)
        return self.model['strings'].index(text) + 1

    def op(self, kind, args=(), typ=1, params=None, refs=(), result=True):
        oid = len(self.model['operations']) + 1
        values = []
        if result:
            vid = len(self.model['values']) + 1
            self.model['values'].append([vid, typ, 0, 0])
            values.append(vid)
        self.model['operations'].append([
            oid, self.string(kind), 0, 0, list(args), values, list(refs),
            [[self.string(k), 'string', v] for k, v in (params or {}).items()]])
        return values[0] if values else oid

    def atom(self, typ=1):
        return self.op('core.input.read', typ=typ)

    def compute(self, kind, *args, typ=1):
        return self.op('core.compute.' + kind, args, typ)

    def const(self, literal="1'b1", typ=1):
        return self.op('core.compute.constant', typ=typ, params={'constValue': literal})

    def write(self, enable, data, mask=None, clock=None, edge='posedge'):
        typ = self.model['values'][data - 1][1]
        state = len(self.model['states']) + 1
        self.model['states'].extend([[state, self.string(f'q{state}'), typ, 0],
                                     [state + 1, self.string(f'h{state}'), 1, 0]])
        mask = mask or self.const("8'hff" if typ != 1 else "1'b1", typ)
        clock = clock or self.atom()
        return self.op('core.state.regWrite', [enable, data, mask, clock],
                       refs=[['state', state], ['state', state + 1]],
                       params={'event_edges': [edge]}, result=False)

    def proof(self, write):
        view = View(self.model)
        return prove_write(view, view.ops[write])

    def mapping(self):
        compute = [op[0] for op in self.model['operations']
                   if not self.model['strings'][op[1] - 1].startswith('core.state.regWrite')]
        self.model['mappings'] = [[[0, 0, [[100, 0, 3, 0, [], compute],
                                          [10, 0, 6, 0, [11], []],
                                          [11, 10, 5, 0, [100], []]], [],
                                     [[[None, [[None, [[1, 10, None, 0]]]]]]]]]]


class TestImplication(unittest.TestCase):
    def test_true_branch_when_enable_is_condition(self):
        f = Fixture()
        c, a, b = f.atom(), f.atom(2), f.atom(2)
        data = f.compute('mux', c, a, b, typ=2)
        write = f.write(c, data)
        before = copy.deepcopy(f.model)
        proof, status = f.proof(write)
        self.assertEqual(status, 'proven')
        self.assertEqual(proof['replacement'], a)
        self.assertEqual(proof['assignments'], 2)
        self.assertEqual(f.model, before)

    def test_enable_conjunction_implies_condition(self):
        f = Fixture()
        c, d, a, b = [f.atom() for _ in range(4)]
        enable = f.compute('and', c, d)
        data = f.compute('mux', c, a, b)
        proof, _ = f.proof(f.write(enable, data))
        self.assertEqual(proof['replacement'], a)
        self.assertEqual(proof['active_assignments'], 1)

    def test_negative_enable_picks_false(self):
        f = Fixture()
        c, a, b = f.atom(), f.atom(2), f.atom(2)
        data = f.compute('mux', c, a, b, typ=2)
        proof, _ = f.proof(f.write(f.compute('logicNot', c), data))
        self.assertEqual(proof['replacement'], b)

    def test_reverse_implication_is_not_enough(self):
        f = Fixture()
        c, d, a, b = [f.atom() for _ in range(4)]
        data = f.compute('mux', f.compute('and', c, d), a, b)
        proof, status = f.proof(f.write(c, data))
        self.assertIsNone(proof)
        self.assertEqual(status, 'unproved_condition')

    def test_const_enable_is_separate(self):
        for literal, status in (("1'b0", 'constant_false_enable'),
                                ("1'b1", 'constant_true_enable')):
            with self.subTest(literal=literal):
                f = Fixture()
                c, a, b = [f.atom() for _ in range(3)]
                proof, found = f.proof(f.write(f.const(literal), f.compute('mux', c, a, b)))
                self.assertIsNone(proof)
                self.assertEqual(found, status)

    def test_bitselect_requires_one_bit_mask(self):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        proof, _ = f.proof(f.write(c, f.compute('bitSelect', c, a, b)))
        self.assertEqual(proof['replacement'], a)
        f = Fixture()
        c, a, b = f.atom(2), f.atom(2), f.atom(2)
        with self.assertRaises(Refused):
            f.proof(f.write(f.atom(), f.compute('bitSelect', c, a, b, typ=2)))

    def test_nested_selection_stops_at_unproved_condition(self):
        f = Fixture()
        c, d, a, b, x = [f.atom() for _ in range(5)]
        inner = f.compute('mux', d, a, b)
        outer = f.compute('mux', c, inner, x)
        proof, _ = f.proof(f.write(c, outer))
        self.assertEqual(proof['replacement'], inner)
        self.assertEqual(len(proof['chain']), 1)

    def test_nested_same_condition(self):
        f = Fixture()
        c, a, b, x = [f.atom() for _ in range(4)]
        inner = f.compute('mux', c, a, b)
        outer = f.compute('mux', c, inner, x)
        proof, _ = f.proof(f.write(c, outer))
        self.assertEqual(proof['replacement'], a)
        self.assertEqual(len(proof['chain']), 2)

    def test_priority_skips_false_conditions(self):
        f = Fixture()
        c, d, a, b, x = [f.atom() for _ in range(5)]
        enable = f.compute('and', f.compute('not', c), d)
        data = f.compute('prioritySelect', c, d, a, b, x)
        proof, _ = f.proof(f.write(enable, data))
        self.assertEqual(proof['replacement'], b)

    def test_priority_later_unknown_is_irrelevant(self):
        f = Fixture()
        c, d, a, b, x = [f.atom() for _ in range(5)]
        data = f.compute('prioritySelect', c, d, a, b, x)
        proof, _ = f.proof(f.write(c, data))
        self.assertEqual(proof['replacement'], a)
        self.assertEqual(proof['atoms'], 1)

    def test_priority_default(self):
        f = Fixture()
        c, d, a, b, x = [f.atom() for _ in range(5)]
        enable = f.compute('not', f.compute('or', c, d))
        data = f.compute('prioritySelect', c, d, a, b, x)
        proof, _ = f.proof(f.write(enable, data))
        self.assertEqual(proof['replacement'], x)

    def test_priority_unknown_earlier_cannot_be_skipped(self):
        f = Fixture()
        c, d, a, b, x = [f.atom() for _ in range(5)]
        data = f.compute('prioritySelect', c, d, a, b, x)
        self.assertIsNone(f.proof(f.write(d, data))[0])

    def test_bool_algebra_truth_vectors(self):
        for kind in BooleanProof.ARITIES:
            with self.subTest(kind=kind):
                f = Fixture()
                args = [f.atom() for _ in range(BooleanProof.ARITIES[kind])]
                value = f.compute(kind, *args)
                proof = BooleanProof(View(f.model))
                node = proof.compile(value)
                vectors, count, _ = proof.independent_vectors()
                atoms = sorted(proof.atoms)
                for row in range(count):
                    env = {v: bool(row & (1 << i)) for i, v in enumerate(atoms)}
                    self.assertEqual(proof.bdd.evaluate(node, env), (vectors[value] >> row) & 1)

    def test_xor_and_equality_implication(self):
        for kind, expected in (('eq', True), ('ne', False), ('xor', False)):
            f = Fixture()
            c, d, a, b = [f.atom() for _ in range(4)]
            enable = f.compute('and', c, f.compute(kind, c, d))
            data = f.compute('mux', d, a, b)
            proof, _ = f.proof(f.write(enable, data))
            self.assertEqual(proof['replacement'], a if expected else b)

    def test_shared_complex_condition_is_an_exact_leaf(self):
        f = Fixture()
        c = f.atom()
        for _ in range(20):
            c = f.compute('and', c, f.atom())
        a, b = f.atom(2), f.atom(2)
        data = f.compute('mux', c, a, b, typ=2)
        proof, _ = f.proof(f.write(c, data))
        self.assertEqual(proof['replacement'], a)
        self.assertEqual(proof['atoms'], 1)
        self.assertEqual(proof['chain'][0]['proof_mode'], 'condition_leaves')

    def test_condition_cut_does_not_assume_unrelated_implication(self):
        f = Fixture()
        a, b, c, x, y = [f.atom() for _ in range(5)]
        condition = f.compute('and', a, b)
        data = f.compute('mux', condition, x, y)
        self.assertIsNone(f.proof(f.write(c, data))[0])

    def test_known_constant_selection_is_not_guard_profit(self):
        for literal in ("1'b0", "1'b1"):
            f = Fixture()
            enable, a, b = [f.atom() for _ in range(3)]
            data = f.compute('mux', f.const(literal), a, b)
            proof, status = f.proof(f.write(enable, data))
            self.assertIsNone(proof)
            self.assertEqual(status, 'unconditional_selection')

    def test_structural_contradiction_is_not_guard_profit(self):
        f = Fixture()
        a, b, x, y = [f.atom() for _ in range(4)]
        cond = f.compute('and', b, f.compute('not', b))
        enable = f.compute('or', a, b)
        data = f.compute('mux', cond, x, y)
        self.assertEqual(f.proof(f.write(enable, data)), (None, 'unconditional_selection'))

    def test_shared_false_condition_does_not_hide_vacuous_enable(self):
        f = Fixture()
        a, x, y = [f.atom() for _ in range(3)]
        condition = f.compute('and', a, f.compute('not', a))
        data = f.compute('mux', condition, x, y)
        self.assertEqual(f.proof(f.write(condition, data)), (None, 'constant_false_enable'))

    def test_expansion_recovers_structurally_different_condition(self):
        f = Fixture()
        a, b, x, y = [f.atom() for _ in range(4)]
        enable = f.compute('and', a, b)
        condition = f.compute('not', f.compute('or', f.compute('not', a), f.compute('not', b)))
        proof, _ = f.proof(f.write(enable, f.compute('mux', condition, x, y)))
        self.assertEqual(proof['replacement'], x)
        self.assertEqual(proof['chain'][0]['proof_mode'], 'expanded')


class TestRejection(unittest.TestCase):
    def test_unknown_constant(self):
        f = Fixture()
        value = f.const("1'bx")
        p = BooleanProof(View(f.model))
        with self.assertRaisesRegex(Refused, 'unknown_constant'):
            p.compile(value)

    def test_four_state(self):
        f = Fixture()
        c = f.atom(4)
        with self.assertRaisesRegex(Refused, 'non_boolean'):
            BooleanProof(View(f.model)).compile(c)

    def test_type_mismatch(self):
        f = Fixture()
        c, a, b = f.atom(), f.atom(2), f.atom(3)
        data = f.compute('mux', c, a, b, typ=2)
        with self.assertRaisesRegex(Refused, 'select_types'):
            f.proof(f.write(c, data))

    def test_event_shape_and_kind(self):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        write = f.write(c, f.compute('mux', c, a, b), edge='level')
        with self.assertRaisesRegex(Refused, 'write_events'):
            f.proof(write)

    def test_nonboolean_enable(self):
        f = Fixture()
        c, a, b = f.atom(), f.atom(2), f.atom(2)
        data = f.compute('mux', c, a, b, typ=2)
        with self.assertRaisesRegex(Refused, 'write_types'):
            f.proof(f.write(f.atom(2), data))

    def test_atom_budget(self):
        f = Fixture()
        a, b = f.atom(), f.atom()
        both = f.compute('and', a, b)
        with self.assertRaisesRegex(Refused, 'atom_budget'):
            BooleanProof(View(f.model), atoms_limit=1).compile(both)

    def test_value_budget(self):
        f = Fixture()
        a = f.atom()
        n = f.compute('not', a)
        with self.assertRaisesRegex(Refused, 'value_budget'):
            BooleanProof(View(f.model), values_limit=1).compile(n)

    def test_boolean_cycle(self):
        f = Fixture()
        a = f.atom()
        b = f.compute('not', a)
        f.model['operations'][-1][4] = [b]
        with self.assertRaisesRegex(Refused, 'boolean_cycle'):
            BooleanProof(View(f.model)).compile(b)

    def test_data_cycle(self):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        data = f.compute('mux', c, a, b)
        f.model['operations'][-1][4][1] = data
        with self.assertRaisesRegex(Refused, 'data_cycle'):
            f.proof(f.write(c, data))

    def test_contradictory_enable_no_vacuous_profit(self):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        enable = f.compute('and', c, f.compute('not', c))
        data = f.compute('mux', c, a, b)
        self.assertEqual(f.proof(f.write(enable, data)), (None, 'constant_false_enable'))


class TestDeadGraph(unittest.TestCase):
    def scenario(self, shared=False, count=1):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        work = f.compute('not', b)
        data = f.compute('mux', c, a, work)
        writes = [f.write(c, data) for _ in range(count)]
        if shared:
            f.op('core.output.write', [data], result=False)
        proofs = [f.proof(w)[0] for w in writes]
        return f, proofs, data, work

    def test_removes_newly_unused_cone(self):
        f, proofs, data, work = self.scenario()
        view = View(f.model)
        dead, prior = dead_candidates(view, proofs)
        self.assertEqual(dead, {view.producer[data], view.producer[work]})
        self.assertEqual(prior, 0)

    def test_preserves_external_use(self):
        f, proofs, _, _ = self.scenario(shared=True)
        self.assertEqual(dead_candidates(View(f.model), proofs)[0], set())

    def test_simultaneous_writes_remove_shared_root_once(self):
        f, proofs, data, work = self.scenario(count=2)
        view = View(f.model)
        self.assertEqual(dead_candidates(view, proofs)[0], {view.producer[data], view.producer[work]})

    def test_partial_writes_keep_root(self):
        f, proofs, _, _ = self.scenario(count=2)
        self.assertEqual(dead_candidates(View(f.model), proofs[:1])[0], set())

    def test_dead_existing_uses_do_not_hold_live_roots(self):
        f, proofs, data, work = self.scenario()
        orphan = f.compute('not', data)
        view = View(f.model)
        dead, prior = dead_candidates(view, proofs)
        self.assertEqual(dead, {view.producer[data], view.producer[work]})
        self.assertEqual(prior, 1)
        self.assertNotIn(view.producer[orphan], dead)

    def test_duplicate_operand_edges(self):
        f, proofs, data, work = self.scenario()
        sink = f.compute('and', data, data)
        f.op('core.output.write', [sink], result=False)
        self.assertEqual(dead_candidates(View(f.model), proofs)[0], set())

    def test_mask_and_other_writes_are_retained(self):
        f, proofs, data, work = self.scenario()
        f.write(f.atom(), f.atom(), mask=data)
        self.assertEqual(dead_candidates(View(f.model), proofs)[0], set())

    def test_feedback_read_is_not_deleted(self):
        f = Fixture()
        c = f.atom()
        old = f.op('core.state.read', refs=[['state', 1]])
        data = f.compute('mux', c, f.atom(), old)
        w = f.write(c, data)
        view = View(f.model)
        proof, _ = prove_write(view, view.ops[w])
        self.assertEqual(dead_candidates(view, [proof])[0], {view.producer[data]})


class TestCensusAndIdentity(unittest.TestCase):
    def test_pricing_deduplicates_shared_writes(self):
        f = Fixture()
        c, a, b = [f.atom() for _ in range(3)]
        data = f.compute('mux', c, a, b)
        f.write(c, data)
        f.write(c, data)
        f.mapping()
        original = copy.deepcopy(f.model)
        result, proofs, dead = census(f.model, {100: 11}, {data: (11, 3)})
        self.assertEqual(result['guard_writes'], 2)
        self.assertEqual(result['selected_ops'], 1)
        self.assertEqual(result['dead_execs'], 11)
        self.assertEqual(result['dead_wr'], 11)
        self.assertEqual(len(dead), 1)
        self.assertEqual(f.model, original)
        self.assertEqual((result, proofs, dead), census(f.model, {100: 11}, {data: (11, 3)}))
        with self.assertRaisesRegex(ValueError, 'coverage mismatch'):
            census(f.model, {}, {data: (11, 3)})

    def test_production_identity_rejects_checkpoint_and_source_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            base, prod = Path(folder) / 'base', Path(folder) / 'prod'
            for path in (base, prod):
                (path / 'model').mkdir(parents=True)
                (path / 'model' / 'a.cpp').write_text('same source')
                (path / 'xiangshan_grhsim_ir.json').write_text('same checkpoint')
                (path / 'xiangshan_grhsim_ir_roundtrip.json').write_text('same checkpoint')
                (path / 'pre_partition.json').write_text('same pre')
            self.assertEqual(verify_production(base, prod)['identical_source_files'], 1)
            (prod / 'model' / 'a.cpp').write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'source differs'):
                verify_production(base, prod)
            (prod / 'model' / 'a.cpp').write_text('same source')
            (prod / 'xiangshan_grhsim_ir_roundtrip.json').write_text('changed checkpoint')
            with self.assertRaisesRegex(ValueError, 'roundtrip differs'):
                verify_production(base, prod)


if __name__ == '__main__':
    unittest.main()
