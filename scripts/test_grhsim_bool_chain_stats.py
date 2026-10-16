"""Focused checks for generated Boolean chain census rules."""

import io
import unittest

from grhsim_bool_chain_stats import Census, phase_of, PHASE_IDS


class BoolChainCensusTest(unittest.TestCase):
    def scan(self, source):
        census = Census()
        census.file_paths.append("synthetic.cpp")
        census.scan_stream(io.StringIO(source), 1)
        return list(census.chains())

    def test_or_of_and_across_event_chunks(self):
        chains = self.scan("""void GrhSIM_SimTop::pEvent_c0(EventFrame &cpu_f){
    const bool cpu_v1=static_cast<bool>(((a&b)&UINT64_C(0x1)));
    const bool cpu_v2=static_cast<bool>(((c&d)&UINT64_C(0x1)));
    cpu_f.v3=static_cast<bool>(((cpu_v1|cpu_v2)&UINT64_C(0x1)));
}
void GrhSIM_SimTop::pEvent_c1(EventFrame &cpu_f){
    const bool cpu_v4=static_cast<bool>(((e&f)&UINT64_C(0x1)));
    cpu_f.v5=static_cast<bool>(((cpu_f.v3|cpu_v4)&UINT64_C(0x1)));
}
""")
        self.assertEqual([(row["phase"], row["operator"], row["length"], row["and_terms"])
                          for row in chains], [("event", "|", 2, True)])

    def test_fanout_breaks_chains(self):
        chains = self.scan("""void GrhSIM_SimTop::sn_1(){
    const bool cpu_v1=static_cast<bool>(((a|b)&UINT64_C(0x1)));
    const bool cpu_v2=static_cast<bool>(((cpu_v1|c)&UINT64_C(0x1)));
    const bool cpu_v3=static_cast<bool>(((cpu_v2|d)&UINT64_C(0x1)));
    const bool cpu_v4=static_cast<bool>(((cpu_v2|e)&UINT64_C(0x1)));
}
""")
        self.assertEqual([(row["value"], row["length"]) for row in chains], [(2, 2)])

    def test_other_phases_and_nested_expression(self):
        self.assertEqual(phase_of("sn_12__op_4__c3"), PHASE_IDS["general"])
        self.assertEqual(phase_of("pLargeSink_c4"), PHASE_IDS["large_sink"])
        self.assertEqual(phase_of("pOutput_c1"), PHASE_IDS["output"])
        chains = self.scan("""void GrhSIM_SimTop::pOutput_c0(){
    const bool cpu_v1=static_cast<bool>(((((a|b)&c)|d)&UINT64_C(0x1)));
    const bool cpu_v2=static_cast<bool>(((cpu_v1|e)&UINT64_C(0x1)));
}
""")
        self.assertEqual([(row["phase"], row["operator"], row["length"])
                          for row in chains], [("output", "|", 2)])

    def test_boundary_store_is_final_operator(self):
        chains = self.scan("""void GrhSIM_SimTop::sn_2(){
    const bool cpu_v1=static_cast<bool>(((a|b)&UINT64_C(0x1)));
    const bool cpu_v2=static_cast<bool>(((cpu_v1|c)&UINT64_C(0x1)));
    {
        const auto &cpu_value=static_cast<bool>(((cpu_v2|d)&UINT64_C(0x1)));
    }
}
""")
        self.assertEqual([(row["phase"], row["operator"], row["length"], row["line"])
                          for row in chains], [("general", "|", 3, 5)])


if __name__ == "__main__":
    unittest.main()
