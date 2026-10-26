import json
from pathlib import Path
import struct
import tempfile
import unittest

from grhsim_cpu_profile import read_profile, six_phase_category, six_phase_model


class ProfileReaderTests(unittest.TestCase):
    def profile(self):
        # Two stacks with distinct leaf PCs: parent PCs must not add flat samples.
        words = (0, 3, 0, 5025, 0, 7, 2, 0x8123, 0x8456, 11, 1, 0x8567, 0, 1, 0)
        return struct.pack("<15Q", *words) + b"8000-9000 r-xp 00000000 00:01 1 /model\n"

    def test_flat_weight_and_mapping(self):
        period, records, maps = read_profile(self.profile())
        self.assertEqual(period, 5025)
        self.assertEqual(records, [(7, 0x8123), (11, 0x8567)])
        self.assertEqual(sum(count for count, _ in records), 18)
        self.assertEqual(maps, [(0x8000, 0x9000, "r-xp", 0, "/model")])

    def test_reject_incomplete_or_unsupported(self):
        data = self.profile()
        for bad in (data[:20], data[:80], data[:120], b"bad!!!!!" + data[8:],
                    data[:120] + b"not a mapping\n"):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                read_profile(bad)

    def test_six_phase_function_categories(self):
        cases = {
            "GrhSIM_SimTop::sn_42_data()": "general_supernode",
            "GrhSIM_SimTop::sn_42_data__c1(GrhSIM_SimTop::Frame&)": "general_supernode",
            "GrhSIM_SimTop::writer_run7()": "sink_writer",
            "GrhSIM_SimTop::writer_run7_chunk3(GrhSIM_SimTop::chunkFrame_writer_run7&)": "sink_writer",
            "GrhSIM_SimTop::commit_run8()": "large_sink_commit",
            "GrhSIM_SimTop::commit_run8_chunk2(GrhSIM_SimTop::chunkFrame_commit_run8&)": "large_sink_commit",
            "GrhSIM_SimTop::writer_23()": "sink_writer",
            "GrhSIM_SimTop::commit_23_chunk2(GrhSIM_SimTop::chunkFrame_commit_23&)": "large_sink_commit",
            "GrhSIM_SimTop::writer_run7_other()": "main_other",
            "GrhSIM_SimTop::pGeneral_c7()": "general_chunk",
            "GrhSIM_SimTop::pMem_c9()": "mem_chunk",
            "GrhSIM_SimTop::pMem()": "mem_schedule",
            "GrhSIM_SimTop::pPublish()": "publication",
            "GrhSIM_SimTop::pPublish_chunk2(GrhSIM_SimTop::ChunkFrame_pPublish&)": "publication",
            "GrhSIM_SimTop::pEvent_chunk3(GrhSIM_SimTop::ChunkFrame_pEvent&)": "event",
            "GrhSIM_SimTop::pLargeSink_chunk4()": "large_sink_chunk",
            "GrhSIM_SimTop::pLargeSink()": "large_sink_schedule",
            "GrhSIM_SimTop::init_chunk9()": "initialization",
            "GrhSIM_SimTop::eval()": "evaluator",
            "grhsim_helper()": "main_other",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(six_phase_category(name), expected)

    def test_model_manifest_replaces_single_source_assumption(self):
        work = Path(__file__).resolve().parents[1] / "ptmp/remove-grhsim-ir/profile-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            path = Path(directory)
            manifest = path / "manifest.json"
            manifest.write_text(json.dumps({"emitter": "grhsim-cpu-st-cpp", "functions": [], "nonsink_functions": []}))
            self.assertTrue(six_phase_model(path))
            self.assertTrue(six_phase_model(path / "grhsim_SimTop.cpp"))
            manifest.write_text(json.dumps({"emitter": "grhsim-cpu-st-cpp"}))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                six_phase_model(path)


if __name__ == "__main__":
    unittest.main()
