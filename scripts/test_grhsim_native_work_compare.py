import unittest

from grhsim_native_work_compare import (MAIN_EVENTS, classify_gsim, classify_ir,
                                        endpoint_fields, parse_perf_report,
                                        parse_perf_stat, task_phases)


class PerfStatParserTests(unittest.TestCase):
    def sample(self):
        return ("# started on Thu Sep 24 17:00:00 2026\n"
                "226063,,cycles:u,226063,100.00,,\n"
                "144388,,instructions:u,226063,100.00,,\n"
                "2556,,branch-misses:u,226063,100.00,,\n"
                "66858,,L1-dcache-loads:u,226063,100.00,,\n"
                "2482,,L1-dcache-load-misses:u,226063,100.00,,\n"
                "0.001033600,,seconds time elapsed,,\n")

    def test_counts(self):
        counts = parse_perf_stat(self.sample(), MAIN_EVENTS)
        self.assertEqual(counts["cycles:u"], 226063)
        self.assertEqual(counts["instructions:u"], 144388)
        self.assertEqual(counts["L1-dcache-load-misses:u"], 2482)

    def test_not_counted_rejected(self):
        text = self.sample().replace("2482,,L1-dcache-load-misses:u",
                                     "<not counted>,,L1-dcache-load-misses:u")
        with self.assertRaises(ValueError):
            parse_perf_stat(text, MAIN_EVENTS)

    def test_missing_event_rejected(self):
        text = self.sample().replace("2482,,L1-dcache-load-misses:u,226063,100.00,,\n", "")
        with self.assertRaises(ValueError):
            parse_perf_stat(text, MAIN_EVENTS)


class PerfReportParserTests(unittest.TestCase):
    def test_rows(self):
        text = ("# comment\n"
                "     9.95%  libc.so.6             [.] __strlen_evex\n"
                "     5.56%  emu                   [.] GrhSIM_SimTop::cpu_task_3974()\n"
                "     0.01%  emu                   [.] 0x0000000000086c5a\n")
        rows = parse_perf_report(text)
        self.assertEqual(rows[0], (9.95, "libc.so.6", "__strlen_evex"))
        self.assertEqual(rows[1], (5.56, "emu", "GrhSIM_SimTop::cpu_task_3974()"))
        self.assertEqual(rows[2], (0.01, "emu", "0x0000000000086c5a"))

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            parse_perf_report("# only comments\n")


class TaskPhaseTests(unittest.TestCase):
    def model(self, tick_args):
        return ("void GrhSIM_SimTop::eval(){\n"
                "if(cpu_flags[0])cpu_task_1();\n"
                "if(cpu_flags[1])cpu_task_2();\n"
                f"cpu_profile_tick(cpu_profile_data.compute_ns{tick_args});\n"
                "if(cpu_flags[2])cpu_task_3();\n"
                f"cpu_profile_tick(cpu_profile_data.commit_ns{tick_args});\n"
                "cpu_publish();\n"
                "void GrhSIM_SimTop::dump_runtime_profile(){}\n")

    def test_two_arg_tick(self):
        phases = task_phases(self.model(",cpu_b_compute_ns").replace(
            "commit_ns,cpu_b_compute_ns", "commit_ns,cpu_b_commit_ns"))
        self.assertEqual(phases, {1: "compute_task", 2: "compute_task", 3: "commit_task"})

    def test_one_arg_tick(self):
        phases = task_phases(self.model(""))
        self.assertEqual(phases, {1: "compute_task", 2: "compute_task", 3: "commit_task"})

    def test_split_boundaries_rejected(self):
        text = self.model("").replace(
            "cpu_profile_tick(cpu_profile_data.compute_ns);",
            "cpu_profile_tick(cpu_profile_data.compute_ns);\n"
            "cpu_profile_tick(cpu_profile_data.compute_ns);")
        with self.assertRaises(ValueError):
            task_phases(text)

    def test_duplicate_task_rejected(self):
        text = self.model("").replace("if(cpu_flags[1])cpu_task_2();",
                                      "if(cpu_flags[1])cpu_task_1();")
        with self.assertRaises(ValueError):
            task_phases(text)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.phases = {3974: "compute_task", 4000: "commit_task"}

    def test_ir_classes(self):
        self.assertEqual(classify_ir("GrhSIM_SimTop::cpu_task_3974()", "emu", self.phases),
                         "compute_task")
        self.assertEqual(classify_ir("GrhSIM_SimTop::cpu_task_4000()", "emu", self.phases),
                         "commit_task")
        self.assertEqual(classify_ir("GrhSIM_SimTop::cpu_task_9999()", "emu", self.phases),
                         "task_unmapped")
        self.assertEqual(classify_ir("GrhSIM_SimTop::eval()", "emu", self.phases), "evaluator")
        self.assertEqual(classify_ir("GrhSIM_SimTop::cpu_publish()", "emu", self.phases),
                         "model_infra")
        self.assertEqual(classify_ir("cpu_write_cell<bool, 1ul>(bool*, unsigned long)",
                                     "emu", self.phases), "helpers")
        self.assertEqual(classify_ir("difftest_step()", "riscv64-nemu-interpreter-so",
                                     self.phases), "difftest_ref")
        self.assertEqual(classify_ir("__memcpy_avx512", "libc.so.6", self.phases), "libc")

    def test_ir_mangled(self):
        self.assertEqual(classify_ir("_ZN13GrhSIM_SimTop13cpu_task_3974Ev", "emu", self.phases),
                         "compute_task")
        self.assertEqual(classify_ir("_ZN13GrhSIM_SimTop4evalEv", "emu", self.phases),
                         "evaluator")
        self.assertEqual(classify_ir("_Z14cpu_write_cellIbLj1EEvPT_m", "emu", self.phases),
                         "helpers")

    def test_gsim_classes(self):
        self.assertEqual(classify_gsim("SSimTop::subStep42()", "emu"), "model_step")
        self.assertEqual(classify_gsim("SSimTop::step()", "emu"), "model_infra")
        self.assertEqual(classify_gsim("_ZN7SSimTop8subStep7Ev", "emu"), "model_step")
        self.assertEqual(classify_gsim("ref_difftest_exec(unsigned long)",
                                       "riscv64-nemu-interpreter-so"), "difftest_ref")
        self.assertEqual(classify_gsim("GsimSim::step(unsigned long)", "emu"), "harness")
        self.assertEqual(classify_gsim("__memmove_avx_unaligned", "libc.so.6"), "libc")


class EndpointFieldsTests(unittest.TestCase):
    def sample(self, counts="238550, cycleCnt = 99998", guest="100001", host="27376"):
        return ("The reference model is riscv64-nemu-interpreter-so\n"
                f"Core-0 instrCnt = {counts}, IPC = 2.385548\n"
                f"Seed=0 Guest cycle spent: {guest} (this will be different)\n"
                "EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000b40\n"
                f"Host time spent: {host}ms\n")

    def test_plain(self):
        fields = endpoint_fields(self.sample(), require_difftest=True)
        self.assertEqual(fields, (238550, 99998, 100001, "0x80000b40", 27.376))

    def test_thousands_separators(self):
        fields = endpoint_fields(self.sample(counts="238,550, cycleCnt = 99,998",
                                             guest="100,001", host="66,740"),
                                 require_difftest=True)
        self.assertEqual(fields, (238550, 99998, 100001, "0x80000b40", 66.740))

    def test_missing_difftest_rejected(self):
        with self.assertRaises(ValueError):
            endpoint_fields(self.sample().replace("The reference model is", "x"),
                            require_difftest=True)


if __name__ == "__main__":
    unittest.main()
