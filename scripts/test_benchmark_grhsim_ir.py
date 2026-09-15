import unittest

from benchmark_grhsim_ir import endpoint, summary


class BenchmarkTests(unittest.TestCase):
    def test_endpoint_requires_difftest_and_complete_matching_run(self):
        log = """Difftest enabled
[CYCLE_LIMIT] cycles=100000 max_cycles=100000
EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c
Core-0 instrCnt = 240349, cycleCnt = 99996, IPC = 2.403586
Seed=0 Guest cycle spent: 100001
Host time spent: 122471ms
"""
        self.assertEqual(endpoint(log), (240349, 99996, 100001, "0x80000c0c", 122.471))
        for invalid in (log + "difftest mismatch", log.replace("Difftest enabled", ""),
                        log.replace("cycles=100000", "cycles=50000")):
            with self.assertRaises(ValueError):
                endpoint(invalid)

    def test_rank_gate_including_ties(self):
        def results(old, new):
            return [{"mode": mode, "host_s": value} for mode, values in (("old", old), ("new", new))
                    for value in values]
        stats = summary(results([6, 7, 8], [3, 4, 5]))
        self.assertTrue(stats["rank_gate_pass"])
        self.assertEqual(stats["one_sided_exact_p"], 0.05)
        self.assertEqual(stats["cliff_delta"], -1)
        self.assertFalse(summary(results([5, 6, 7], [3, 4, 5]))["rank_gate_pass"])
        self.assertFalse(summary(results([6], [3]))["rank_gate_pass"])


if __name__ == "__main__":
    unittest.main()
