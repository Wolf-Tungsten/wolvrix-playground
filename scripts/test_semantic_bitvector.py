import unittest

from semantic_bitvector import (BVType, Term, Unverified, boolean, cast, compare, concatenate, constant,
                          evaluate, mux, normalize_grh, normalize_gsim, resize, slice_bits, source)


class TypedBitvectorTests(unittest.TestCase):
    def test_mux_slots_are_ordered_and_swapping_branches_has_counterexample(self):
        select, a, b = source("s", BVType(1)), source("a", BVType(2)), source("b", BVType(2))
        grh = normalize_grh("kMux", BVType(2), (select, a, b))
        gs = normalize_gsim("OP_MUX", BVType(2), (select, a, b))
        self.assertEqual(compare(grh, gs)["status"], "proved_typed_structural_equality")
        swapped = normalize_gsim("OP_MUX", BVType(2), (select, b, a))
        self.assertEqual(compare(grh, swapped)["status"], "counterexample")

    def test_add_to_sub_mutation_is_rejected(self):
        a, b = source("a", BVType(2)), source("b", BVType(2))
        grh = normalize_grh("kAdd", BVType(3), (resize(a, BVType(3)), resize(b, BVType(3))))
        gs = normalize_gsim("OP_ADD", BVType(3), (a, b))
        self.assertEqual(compare(grh, gs)["status"], "proved_typed_structural_equality")
        changed = normalize_gsim("OP_SUB", BVType(3), (a, b))
        self.assertEqual(compare(grh, changed)["status"], "counterexample")

    def test_width_and_output_signedness_are_part_of_contract(self):
        a = source("a", BVType(3))
        self.assertEqual(compare(a, resize(a, BVType(4)))["status"], "different_output_type")
        self.assertEqual(compare(a, cast(a, BVType(3, True)))["status"], "different_output_type")

    def test_same_named_leaf_with_different_signed_type_is_rejected(self):
        a, wrong = source("a", BVType(3)), source("a", BVType(3, True))
        self.assertEqual(compare(a, cast(wrong, BVType(3)))["status"], "different_source_boundary_types")

    def test_zero_extension_and_sign_extension_differ(self):
        a = source("a", BVType(2, True))
        sign = resize(a, BVType(4, True))
        zero = resize(a, BVType(4, True), False)
        self.assertEqual(evaluate(sign, {"a": 2}), 14)
        self.assertEqual(evaluate(zero, {"a": 2}), 2)
        self.assertEqual(compare(sign, zero)["status"], "counterexample")

    def test_GRH_explicit_concat_extensions_match_GSIM_pad(self):
        for signed in (False, True):
            with self.subTest(signed=signed):
                a = source("a", BVType(3, signed))
                high = normalize_grh("kReplicate", BVType(2), (slice_bits(a, 2, 1),), {"rep": 2}) if signed else constant(0, BVType(2))
                grh = concatenate((high, a), BVType(5, signed))
                gs = normalize_gsim("OP_PAD", BVType(5, signed), (a,), (5,))
                self.assertEqual(compare(grh, gs)["status"], "proved_typed_structural_equality")

    def test_truncation_preserves_low_bits_and_static_slice(self):
        a = source("a", BVType(5))
        grh = normalize_grh("kSliceStatic", BVType(3), (a,), {"sliceStart": 0, "sliceEnd": 2})
        gs = normalize_gsim("OP_BITS", BVType(3), (a,), (2, 0))
        self.assertEqual(compare(grh, gs)["status"], "proved_typed_structural_equality")
        self.assertEqual(evaluate(grh, {"a": 29}), 5)

    def test_signed_comparison_extends_before_comparison(self):
        a, b = source("a", BVType(2, True)), source("b", BVType(4, True))
        grh = normalize_grh("kLt", BVType(1), (resize(a, BVType(4, True)), b))
        gs = normalize_gsim("OP_LT", BVType(1), (a, b))
        self.assertEqual(compare(grh, gs)["status"], "proved_typed_structural_equality")
        self.assertEqual(evaluate(gs, {"a": 2, "b": 1}), 1)

    def test_signed_multiply_extends_operands_to_result_modulo_width(self):
        a, b = source("a", BVType(2, True)), source("b", BVType(3, True))
        term = normalize_gsim("OP_MUL", BVType(5, True), (a, b))
        self.assertEqual(evaluate(term, {"a": 2, "b": 3}), 26)

    def test_native_literal_bases_follow_firStrBase(self):
        for text, expected in (("0hff", 255), ("0b101", 5), ("0o17", 15),
                               ("0d17", 17), ("0017", 17), ("-0h2", 254)):
            with self.subTest(text=text):
                self.assertEqual(evaluate(normalize_gsim("OP_INT", BVType(8), (), strVal=text), {}), expected)
        for text in ("0b2", "0hx", "garbage"):
            with self.assertRaises(Unverified):
                normalize_gsim("OP_INT", BVType(8), (), strVal=text)

    def test_native_head_tail_parameters_change_only_after_inferAllWidth(self):
        a = source("a", BVType(8))
        before = normalize_gsim("OP_HEAD", BVType(3), (a,), (3,))
        after = normalize_gsim("OP_HEAD", BVType(3), (a,), (5,), head_tail_updated=True)
        self.assertEqual(before, after)
        self.assertEqual(evaluate(after, {"a": 0b10111000}), 0b101)
        before = normalize_gsim("OP_TAIL", BVType(5), (a,), (3,))
        after = normalize_gsim("OP_TAIL", BVType(5), (a,), (5,), head_tail_updated=True)
        self.assertEqual(before, after)
        self.assertEqual(evaluate(after, {"a": 0b10111000}), 0b11000)
        with self.assertRaisesRegex(Unverified, "tail_stage_width"):
            normalize_gsim("OP_TAIL", BVType(5), (a,), (3,), head_tail_updated=True)

    def test_native_explicit_SEXT_always_sign_extends_declared_input_bits(self):
        a = source("a", BVType(3))
        extended = normalize_gsim("OP_SEXT", BVType(5, True), (a,), (5,))
        self.assertEqual(evaluate(extended, {"a": 4}), 28)
        with self.assertRaises(Unverified):
            normalize_gsim("OP_SEXT", BVType(5, True), (a,), (6,))

    def test_partial_when_is_unverified_even_if_both_sides_missing_branch(self):
        a, c = source("a", BVType(2)), source("c", BVType(1))
        with self.assertRaisesRegex(Unverified, "partial_when"):
            normalize_gsim("OP_WHEN", BVType(2), (c, a, None))

    def test_unknown_operator_unknown_width_and_arrays_are_unverified(self):
        a = source("a", BVType(2))
        with self.assertRaisesRegex(Unverified, "unsupported_GSIM"):
            normalize_gsim("OP_UNKNOWN", BVType(2), (a,))
        with self.assertRaisesRegex(Unverified, "unsupported_GRH"):
            normalize_grh("kUnrecognized", BVType(2), (a,))
        with self.assertRaises(Unverified):
            source("x", BVType(-1))
        with self.assertRaises(Unverified):
            source("x", BVType(2, shape=(2,)))
        unknown = Term("unknown", BVType(2), (a,))
        self.assertEqual(compare(unknown, unknown)["status"], "unverified")

    def test_four_state_unknowns_are_not_silently_mapped_to_zero(self):
        with self.assertRaises(Unverified):
            source("x", BVType(2, domain="four"))
        with self.assertRaises(Unverified):
            normalize_grh("kConstant", BVType(2), (), {"constValue": "2'bx"})

    def test_boolean_nested_mux_guard_rewrite_has_exhaustive_proof(self):
        a, b = source("a", BVType(1)), source("b", BVType(1))
        nested = mux(a, b, constant(0, BVType(1)), BVType(1))
        conjunction = normalize_grh("kAnd", BVType(1), (a, b))
        self.assertEqual(compare(nested, conjunction)["status"], "proved_exhaustive_two_state_equality")

    def test_large_nonidentical_expression_is_unverified_not_claimed_unequal(self):
        a = source("a", BVType(16))
        expression = normalize_grh("kAdd", BVType(16), (a, constant(0, BVType(16))))
        self.assertEqual(compare(expression, a)["status"], "unverified")

    def test_huge_shift_amounts_are_masked_without_creating_huge_python_integers(self):
        x = source("x", BVType(8))
        amount = constant((1 << 32) - 1, BVType(32))
        for kind in ("kShl", "kLShr", "kAShr"):
            term = normalize_grh(kind, BVType(8), (x, amount))
            self.assertEqual(evaluate(term, {"x": 128}), 255 if kind == "kAShr" else 0)

    def test_deep_shared_DAG_hash_equality_and_commutative_order_preserve_sharing(self):
        left, right = source("x", BVType(1)), source("x", BVType(1))
        for _ in range(200):
            left = Term("and", BVType(1), (left, left))
            right = Term("and", BVType(1), (right, right))
        self.assertEqual(left, right)
        self.assertEqual(hash(left), hash(right))
        self.assertEqual(compare(left, right)["status"], "proved_typed_structural_equality")
        leaf = source("y", BVType(1))
        a = normalize_grh("kAnd", BVType(1), (left, leaf))
        b = normalize_grh("kAnd", BVType(1), (leaf, right))
        self.assertEqual(a, b)
        changed = Term("or", BVType(1), (left, leaf))
        self.assertEqual(compare(a, changed)["status"], "counterexample")

    def test_fingerprint_collision_cannot_substitute_for_structural_equality(self):
        left, right = source("a", BVType(1)), source("b", BVType(1))
        object.__setattr__(right, "_digest", left._digest)
        object.__setattr__(right, "_hash", left._hash)
        self.assertNotEqual(left, right)
        a, b = Term("and", BVType(1), (left, left)), Term("and", BVType(1), (right, right))
        self.assertEqual(a._digest, b._digest)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
