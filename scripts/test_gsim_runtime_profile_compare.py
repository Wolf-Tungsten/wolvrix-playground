import unittest

from gsim_runtime_profile_compare import (factor_table, parse_fire_tsv,
                                          parse_ir_dyn_log, parse_profile_line,
                                          parse_static_tsv, parse_stats_json,
                                          parse_weight_assignments,
                                          super_pareto)


class ProfileLineParserTests(unittest.TestCase):
    def sample(self):
        return ("[GSIM_RUNTIME_PROFILE] active_supernodes=900000000 nodes=2500000000 "
                "ref_enodes=800000000 non_ref_enodes=1700000000 total_enodes=2500000000\n")

    def test_counts(self):
        profile = parse_profile_line(self.sample())
        self.assertEqual(profile["active_supernodes"], 900000000)
        self.assertEqual(profile["total_enodes"], 2500000000)

    def test_missing_rejected(self):
        with self.assertRaises(ValueError):
            parse_profile_line("no profile here\n")

    def test_inconsistent_total_rejected(self):
        text = self.sample().replace("total_enodes=2500000000", "total_enodes=7")
        with self.assertRaises(ValueError):
            parse_profile_line(text)


class FireTsvParserTests(unittest.TestCase):
    def test_rows(self):
        rows = parse_fire_tsv("supernode_id\tf\n0\t100\n1\t0\n42\t7\n")
        self.assertEqual(rows, {0: 100, 1: 0, 42: 7})

    def test_malformed_rejected(self):
        with self.assertRaises(ValueError):
            parse_fire_tsv("supernode_id\tf\n0 100\n")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            parse_fire_tsv("supernode_id\tf\n")


class StaticTsvParserTests(unittest.TestCase):
    def test_rows(self):
        rows = parse_static_tsv("supernode_id\tphase\tn_comp\tn_src\tn_sink\tn_const\ta_succ\n"
                                "3\t-\t10\t2\t1\t4\t5\n")
        self.assertEqual(rows[3]["n_sink"], 1)
        self.assertEqual(rows[3]["a_succ"], 5)

    def test_malformed_rejected(self):
        with self.assertRaises(ValueError):
            parse_static_tsv("supernode_id\tphase\tn_comp\tn_src\tn_sink\tn_const\ta_succ\n"
                             "3\t-\t10\n")


class WeightParserTests(unittest.TestCase):
    def test_assignments(self):
        text = ("runtimeProfileNodeWeight[5] = 12;\n"
                "runtimeProfileRefENodeWeight[5] = 4;\n"
                "runtimeProfileNonRefENodeWeight[5] = 8;\n")
        weights = parse_weight_assignments(text)
        self.assertEqual(weights[5], {"nodes": 12, "ref_enodes": 4, "non_ref_enodes": 8})

    def test_incomplete_rejected(self):
        with self.assertRaises(ValueError):
            parse_weight_assignments("runtimeProfileNodeWeight[5] = 12;\n")


class StatsJsonTests(unittest.TestCase):
    def test_fields(self):
        stats = parse_stats_json({"supernodes": 84643, "active_source_nodes": 442722,
                                  "always_active_supernodes": 111,
                                  "activation_edges": 1379970,
                                  "unique_activation_edges": 719095})
        self.assertEqual(stats["unique_activation_edges"], 719095)

    def test_missing_rejected(self):
        with self.assertRaises(ValueError):
            parse_stats_json({"supernodes": 1})


class IrDynLogParserTests(unittest.TestCase):
    def sample(self):
        return ("[grhsim-dyn] sn 1 act=10 body=9 grp=9 chg=3\n"
                "[grhsim-dyn] sn 2 act=20 body=18 grp=18 chg=6\n"
                "[grhsim-dyn] kind core.compute.and wr=100 ch=5 silent=7\n"
                "[grhsim-dyn] kind core.compute.or wr=50 ch=3 silent=1\n"
                "[grhsim-dyn] totals grp_pub=27 grp_fire=9 port_eval=10 port_fire=7 "
                "in_chk=4 in_chg=1 pub_calls=2 pub_pending=1 pub_changes=1 cm_stable=0 "
                "cm_inactive=0 mw_gate=0 mw_fire=0\n")

    def test_counters(self):
        counters = parse_ir_dyn_log(self.sample())
        self.assertEqual(counters["sn_activations"], 30)
        self.assertEqual(counters["sn_bodies"], 27)
        self.assertEqual(counters["boundary_wr"], 150)
        self.assertEqual(counters["boundary_chg"], 8)
        self.assertEqual(counters["boundary_silent"], 8)
        self.assertEqual(counters["grp_pub"], 27)

    def test_missing_totals_rejected(self):
        with self.assertRaises(ValueError):
            parse_ir_dyn_log("[grhsim-dyn] sn 1 act=1 body=1 grp=1 chg=1\n")


class FactorTableTests(unittest.TestCase):
    def test_closure(self):
        profile = {"active_supernodes": 900000, "nodes": 2500000,
                   "ref_enodes": 800000, "non_ref_enodes": 1700000,
                   "total_enodes": 2500000}
        stats = {"supernodes": 100, "active_source_nodes": 1000,
                 "always_active_supernodes": 10, "activation_edges": 3000,
                 "unique_activation_edges": 1624}
        ir = {"sn_activations": 1000000, "sn_bodies": 900000, "boundary_wr": 22000000,
              "boundary_chg": 127000}
        table = factor_table(profile, stats, ir, 100, 10000000, 3.86e5, 1.9e5, 59.3, 110.01)
        self.assertAlmostEqual(table["gsim"]["activations_per_cycle"], 9000.0)
        self.assertAlmostEqual(table["gsim"]["changes_per_cycle_derived"],
                               (9000.0 - 10) / 1.624, places=6)
        self.assertAlmostEqual(table["ir"]["changes_per_cycle"], 1270.0)
        self.assertAlmostEqual(table["gsim"]["enodes_per_activation"],
                               2500000 / 900000, places=6)
        self.assertAlmostEqual(table["ir"]["dynops_per_body"],
                               10000000 / 900000, places=6)
        closure = table["ratio"]["closure_instr"]
        self.assertGreater(closure, 0.0)

    def test_bad_cycles_rejected(self):
        with self.assertRaises(ValueError):
            factor_table({"active_supernodes": 1, "nodes": 1, "ref_enodes": 0,
                          "non_ref_enodes": 1, "total_enodes": 1},
                         {"supernodes": 1, "active_source_nodes": 1,
                          "always_active_supernodes": 0, "activation_edges": 1,
                          "unique_activation_edges": 1},
                         {"sn_activations": 1, "sn_bodies": 1, "boundary_wr": 1,
                          "boundary_chg": 1},
                         0, 1, 1.0, 1.0, 1.0, 1.0)


class SuperParetoTests(unittest.TestCase):
    def test_attribution(self):
        fires = {0: 100, 1: 50}
        weights = {0: {"nodes": 10, "ref_enodes": 4, "non_ref_enodes": 6},
                   1: {"nodes": 30, "ref_enodes": 8, "non_ref_enodes": 22}}
        statics = {0: {"n_comp": 6, "n_src": 1, "n_sink": 1, "n_const": 0, "a_succ": 2},
                   1: {"n_comp": 12, "n_src": 0, "n_sink": 0, "n_const": 1, "a_succ": 3}}
        pareto = super_pareto(fires, weights, statics, 100)
        self.assertEqual(pareto["total_fires"], 150)
        self.assertEqual(pareto["total_enode_work"], 100 * 10 + 50 * 30)
        self.assertAlmostEqual(pareto["sink_fire_share"], 100 / 150)
        self.assertAlmostEqual(pareto["detect_compares_per_cycle"],
                               (100 * 2 + 50 * 3) / 100)
        self.assertEqual(pareto["top"][0]["supernode"], 1)


if __name__ == "__main__":
    unittest.main()
