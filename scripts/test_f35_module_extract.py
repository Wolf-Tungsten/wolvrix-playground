import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from f35_module_extract import extract_module


FIRRTL = """FIRRTL version 6.0.0
circuit Top :%[[
  {"class":"firrtl.transforms.DontTouchAnnotation",
   "target":"~Top|Parent>observed"},
  {"class":"firrtl.transforms.BlackBoxInlineAnno","target":"~|Gate","name":"ClockGate.sv","text":"// { } ] ]"},
  {"class":"firrtl.transforms.DedupGroupAnnotation","target":"~|Top","group":"Top"}
]]
   layer Verification, bind :
      layer Assert, inline :
   type Bit = UInt<1>
   extmodule Gate :
      input in : Bit
      defname = ClockGate
   module Child :
      when UInt<1>(1) :
         inst gate of Gate
   public module Parent : @[Parent.scala 1:1]
      input observed : Bit
      inst child of Child
      layerblock Verification :
         skip
   module Top :
      inst parent of Parent
      inst discard of Unused
   module Unused :
      skip
"""


class ModuleExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "original.fir"
        self.output = Path(temporary.name) / "excerpt.fir"
        self.source.write_text(FIRRTL)

    def test_dependencies_annotations_and_source_lines(self):
        result = extract_module(self.source, "Parent", self.output)
        payload = self.output.read_bytes()
        text = payload.decode()
        self.assertEqual(result["modules"], ["Gate", "Child", "Parent"])
        self.assertEqual(result["external_modules"], ["Gate"])
        self.assertEqual(result["external_implementations"], {"Gate": "ClockGate"})
        self.assertEqual(result["output_bytes"], len(payload))
        self.assertEqual(result["output_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertIn("circuit Parent :%[[", text)
        self.assertNotIn("module Top", text)
        self.assertNotIn("module Unused", text)
        self.assertIn("layer Assert, inline", text)
        self.assertIn("type Bit = UInt<1>", text)
        annotations = json.loads(text.split("%[", 1)[1].split("\n]]", 1)[0] + "\n]")
        self.assertEqual([record["target"] for record in annotations], ["~Parent|Parent>observed", "~|Gate"])
        self.assertEqual(annotations[1]["text"], "// { } ] ]")
        output_lines = text.splitlines()
        source_lines = FIRRTL.splitlines()
        for entry in result["line_map"]:
            if entry["kind"] in {"module", "extmodule", "layer", "type"}:
                self.assertEqual(output_lines[entry["output_start"] - 1:entry["output_end"]],
                                 source_lines[entry["source_start"] - 1:entry["source_end"]])

    def test_size_limit_preserves_previous_output(self):
        self.output.write_text("previous output")
        with self.assertRaisesRegex(ValueError, "32-byte limit"):
            extract_module(self.source, "Parent", self.output, max_bytes=32)
        self.assertEqual(self.output.read_text(), "previous output")

    def test_missing_dependency_is_reported(self):
        self.source.write_text(FIRRTL.replace("inst gate of Gate", "inst gate of Missing"))
        with self.assertRaisesRegex(ValueError, "undeclared module or class 'Missing'"):
            extract_module(self.source, "Parent", self.output)

    def test_inline_annotation_and_literal_identifier(self):
        self.source.write_text("""FIRRTL version 6.0.0
circuit Top :%[[{"class":"firrtl.transforms.DedupGroupAnnotation","target":"~|123","group":"123"}]]
  module Top :
    inst a of `123`
  module `123` :
    skip""")
        result = extract_module(self.source, "123", self.output)
        self.assertEqual(result["modules"], ["123"])
        self.assertTrue(self.output.read_text().splitlines()[1].startswith("circuit `123` :"))

    def test_reset_binding_is_limited_to_the_selected_modules_scalar_input(self):
        self.source.write_text("""FIRRTL version 6.0.0
circuit Top :
  module Child :
    input reset : Reset
  module Top :
    input reset : Reset @[Top.scala 2:3]
    input sync : const Reset ; synchronous domain
    input untouched : Reset
    input already_typed : AsyncReset
    input reset_vector : Reset[2]
    output reset_out : Reset
    inst child of Child
""")
        result = extract_module(self.source, "Top", self.output,
                                reset_ports={"reset": "AsyncReset", "sync": "UInt<1>"})
        output_lines = self.output.read_text().splitlines()
        self.assertEqual(result["abstract_reset_ports"], ["untouched"])
        self.assertEqual(result["reset_bindings"], [
            {"port": "reset", "source_type": "Reset", "output_type": "AsyncReset",
             "source_line": 6, "output_line": 6},
            {"port": "sync", "source_type": "Reset", "output_type": "UInt<1>",
             "source_line": 7, "output_line": 7},
        ])
        self.assertEqual(output_lines[3], "    input reset : Reset")
        self.assertEqual(output_lines[5], "    input reset : AsyncReset @[Top.scala 2:3]")
        self.assertEqual(output_lines[6], "    input sync : const UInt<1> ; synchronous domain")
        self.assertEqual(output_lines[9], "    input reset_vector : Reset[2]")

        for name in ("unknown", "already_typed", "reset_vector", "reset_out"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "no scalar abstract Reset input"):
                extract_module(self.source, "Top", self.output, reset_ports={name: "UInt<1>"})


if __name__ == "__main__":
    unittest.main()
