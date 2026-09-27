from copy import deepcopy
import unittest

from grhsim_checkpoint_identity import source_renumber_identity
from grhsim_demonitor_gates import gate_model_neutral


def fixture():
    return {
        "strings": ["model", "grh.event", "__event_100_0", "source", "core.init.const", "value", "grh.operation"],
        "name": 1,
        "origins": [[1, 2, 4, 100, 0, 0, 0, 0, 0, 0, 0],
                    [2, 7, 4, 100, 0, 0, 0, 0, 0, 0, 0]],
        "states": [[1, 3, 1, 1]],
        "values": [], "inputs": [], "outputs": [], "interface": [],
        "operations": [], "types": [], "dialects": [], "functions": [],
        "init": [[1, [[5, [[6, "string", "0"]]]]]],
        "mappings": [],
    }


class IdentityTests(unittest.TestCase):
    def pair(self):
        old = fixture()
        new = deepcopy(old)
        new["strings"][2] = "__event_7_0"
        for row in new["origins"]:
            row[3] = 7
        return old, new

    def test_annotated_renumber(self):
        old, new = self.pair()
        before = deepcopy(new)
        self.assertFalse(gate_model_neutral(old, new).ok)
        self.assertTrue(gate_model_neutral(old, new, True).ok)
        self.assertEqual(new, before)

    def test_same_model(self):
        self.assertEqual(source_renumber_identity(fixture(), fixture())[0], [])

    def test_semantic_drift(self):
        for key in ("operations", "types", "states", "values", "init", "interface"):
            with self.subTest(key=key):
                old, new = self.pair()
                new[key].append([999])
                # Malformed semantic data is also rejected before annotation checks.
                self.assertTrue(source_renumber_identity(old, new)[0])

    def test_origin_location(self):
        old, new = self.pair()
        new["origins"][0][5] = 1
        self.assertTrue(source_renumber_identity(old, new)[0])

    def test_event_identity_required(self):
        for name in ("__event_8_0", "__event_7_1", "other"):
            with self.subTest(name=name):
                old, new = self.pair()
                new["strings"][2] = name
                self.assertTrue(source_renumber_identity(old, new)[0])

    def test_array_length(self):
        old, new = self.pair()
        new["strings"].append("unused")
        self.assertTrue(source_renumber_identity(old, new)[0])

    def test_private_state_required(self):
        old, new = self.pair()
        old["states"][0][3] = new["states"][0][3] = 2
        self.assertTrue(source_renumber_identity(old, new)[0])

    def test_public_name_collision(self):
        for section, row in (("inputs", [1, 3, 1, 0]), ("outputs", [1, 3, 1, 0]),
                             ("interface", [3, "input", 1, 0, 0]),
                             ("values", [1, 1, 3, 0]),
                             ("operations", [1, 3, 0, 0, [], [], [], []]),
                             ("mappings", [3, 5, True, []]),
                             ("mappings", [5, 5, True, [[3, "string", "0"]]])):
            with self.subTest(section=section):
                old, new = self.pair()
                old[section].append(row)
                new[section].append(row)
                self.assertTrue(source_renumber_identity(old, new)[0])

    def test_parameter_name_collision(self):
        old, new = self.pair()
        op = [1, 5, 0, 0, [], [], [], [[3, "string", "0"]]]
        old["operations"].append(op)
        new["operations"].append(op)
        self.assertTrue(source_renumber_identity(old, new)[0])

    def test_new_mapping_name_collision(self):
        old, new = self.pair()
        old["mappings"] = [[5, 5, True, []]]
        new["mappings"] = [[3, 5, True, []]]
        self.assertTrue(source_renumber_identity(old, new)[0])

    def test_foreign_source_index(self):
        old, new = self.pair()
        old["strings"][6] = new["strings"][6] = "other.source"
        self.assertTrue(source_renumber_identity(old, new)[0])


if __name__ == "__main__":
    unittest.main()
