import tempfile
import unittest
from pathlib import Path

from xiangshan_mux1h_census import find_calls, fir_census, split_args


class CensusTests(unittest.TestCase):
    def test_scala_calls_exclude_literals_comments_and_imports(self):
        source = '''import chisel3.util.Mux1H
// Mux1H(a, b)
/* outer Mux1H(a, b) /* nested */ */
val text = "Mux1H(a, b)"
val x = Mux1H[UInt](
  s, data.map(x => Mux1H(t, x))
)
val y = Mux1H.apply(s, data)
def Mux1H(a: Int, b: Int) = a + b
'''
        calls = find_calls(source, "src/main/scala/Example.scala", "xiangshan")
        self.assertEqual([(c["line"], c["end_line"]) for c in calls],
                         [(5, 7), (6, 6), (8, 8)])
        self.assertEqual(calls[0]["column"], 9)

    def test_fir_scalar_fields_aggregate_group_and_instance_weight(self):
        source = "val x = Mux1H(s, data)\n"
        calls = find_calls(source, "src/main/scala/Example.scala", "xiangshan")
        loc = " @[src/main/scala/Example.scala 1:14]"
        fir = "\n".join([
            "FIRRTL version 6.0.0", "circuit SimTop :",
            "  module Sub :",
            "    wire result : { a : UInt<1>, b : UInt<8>}" + loc,
            "    node a0 = mux(s[0], d[0].a, UInt<1>(0h0))" + loc,
            "    node a1 = mux(s[1], d[1].a, UInt<1>(0h0))" + loc,
            "    node ar = or(a0, a1)" + loc,
            "    node ab = bits(ar, 0, 0)" + loc,
            "    connect result.a, ab" + loc,
            "    node b0 = mux(s[0], d[0].b, SInt<1>(0h0))" + loc,
            "    node b1 = mux(s[1], d[1].b, SInt<1>(0h0))" + loc,
            "    node bu0 = asUInt(b0)" + loc,
            "    node bu1 = asUInt(b1)" + loc,
            "    node br = or(bu0, bu1)" + loc,
            "    node bs = asSInt(br)" + loc,
            "    connect result.b, bs" + loc,
            # A zero-else mux in an argument has another source column.
            "    node unrelated = mux(s[0], d[0], UInt<1>(0h0))"
            " @[src/main/scala/Example.scala 1:18]",
            "  public module SimTop :",
            "    inst first of Sub", "    inst second of Sub",
        ]) + "\n"
        with tempfile.TemporaryDirectory(dir="ptmp") as directory:
            path = Path(directory) / "SimTop.fir"
            path.write_text(fir)
            trees, expansions, stats = fir_census(path, calls, Path("."))
        self.assertEqual([t["terms"] for t in trees], [2, 2])
        self.assertEqual(len(expansions), 1)
        self.assertEqual(expansions[0]["fields"], 2)
        self.assertEqual(stats["scalar_trees_instance_weighted"], 4)
        self.assertEqual(stats["grouped_expansions_instance_weighted"], 2)

    def test_fir_arguments(self):
        self.assertEqual(split_args("x, UInt<1>(0h0), mux(s, d[0], d[1])"),
                         ["x", "UInt<1>(0h0)", "mux(s, d[0], d[1])"])


if __name__ == "__main__":
    unittest.main()
