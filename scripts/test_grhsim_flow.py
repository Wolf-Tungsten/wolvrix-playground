"""Execute the ordinary Python API and every completed checkpoint restart."""

import json
import os
import shutil
import unittest
from pathlib import Path

import wolvrix

from grhsim_flow import FlowOptions, STAGES, checked, emit_cpp, finish_simulation_graph, store_checkpoint
from grhsim_supernode_origin_stats import build_grh_manifest
from grhsim_provenance import generated_identity
from wolvrix_xs_grhsim import GRH_PIPELINE


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("GRHSIM_FLOW_TEST_WORK", ROOT / "ptmp/remove-grhsim-ir/r6-flow-tests"))


class FlowTest(unittest.TestCase):
    def test_retired_api_is_absent(self):
        for name in ("lower_grhsim", "run_grhsim_pass", "run_grhsim_pipeline", "load_grhsim", "store_grhsim"):
            self.assertFalse(hasattr(wolvrix.Session, name), name)
        self.assertFalse(hasattr(wolvrix, "list_grhsim_passes"))
        for name in ("session_lower_grhsim", "session_run_grhsim_pass", "session_load_grhsim",
                     "session_store_grhsim", "list_grhsim_passes"):
            self.assertFalse(hasattr(wolvrix._native, name), name)

    def test_real_frontend_and_checkpoint_restarts(self):
        WORK.mkdir(parents=True, exist_ok=True)
        source = WORK / "fixture.sv"
        source.write_text("""module flow_top(input logic clk, reset_n, gate, en,
    input logic [2:0] addr, input logic [7:0] data,
    output logic [7:0] qout, mout, shadowout);
logic [7:0] q = 8'd5;
logic [7:0] mem [0:3];
logic [7:0] shadow [0:3];
initial begin
    for (integer i=0; i<4; i=i+1) begin mem[i]=8'd1; shadow[i]=8'd0; end
end
wire gated = clk & gate;
always @(posedge gated or negedge reset_n)
    if (!reset_n) q <= 8'd18; else if (en) q <= data;
always @(posedge clk) if (en) begin
    mem[addr] <= data;
    shadow[addr] <= mem[addr];
end
assign qout = q;
assign mout = mem[addr];
assign shadowout = shadow[addr];
endmodule
""")
        options = FlowOptions(mem_min_bytes=4, max_node_work=2, max_supernode_work=4,
                              enable_guard_min_size=2)
        checkpoints = {}
        with wolvrix.Session() as session:
            session.diagnostics_raise_min_level = "none"
            checked(session.read_sv(str(source), out_design="design.main", slang_args=["--top", "flow_top"]), "ingest fixture")
            for name, pass_options in GRH_PIPELINE:
                checked(session.run_pass(name, design="design.main", **pass_options), name)
            self.assertNotIn("grhsim.stage", session.graph_metadata(design="design.main")["metadata"])

            def checkpoint(stage):
                path = WORK / f"{stage}.json"
                store_checkpoint(session, path, design="design.main", top="flow_top")
                checkpoints[stage] = path

            finish_simulation_graph(session, design="design.main", top="flow_top", options=options, checkpoint=checkpoint)
            self.assertEqual(set(checkpoints), set(STAGES))
            self.assertEqual(session.kind("design.main"), "design")
            self.assertFalse(any(session.kind(key) == "grhsim-model" for key in session.keys()))

        final = checkpoints["sink-partitioned"].read_bytes()
        for stage, path in checkpoints.items():
            graph = json.loads(path.read_bytes())["graphs"][0]
            if stage == "converted":
                self.assertFalse(any("grhsim.partition" in op.get("attrs", {}) for op in graph["ops"]))
            if stage == "event-output-split":
                self.assertTrue(all(op["attrs"]["grhsim.partition"]["vs"][0] in ("event", "general", "output")
                                    for op in graph["ops"] if "grhsim.partition" in op.get("attrs", {})))
            with wolvrix.Session() as session:
                session.diagnostics_raise_min_level = "none"
                checked(session.read_json_file(str(path), out_design="design.main"), "reload checkpoint")
                bad = WORK / "missing-schedule"
                if bad.exists():
                    shutil.rmtree(bad)
                diagnostics = session.emit_grhsim_cpu_st_cpp(design="design.main", output=str(bad))
                self.assertTrue(any(entry.get("kind") == "error" for entry in diagnostics))
                self.assertFalse(bad.exists())
                resume_options = options if stage != "sink-partitioned" else None
                finish_simulation_graph(session, design="design.main", top="flow_top", options=resume_options)
                rewritten = WORK / f"{stage}-resumed.json"
                store_checkpoint(session, rewritten, design="design.main", top="flow_top")
                if stage in ("nonsink-partitioned", "sink-partitioned"):
                    self.assertEqual(rewritten.read_bytes(), final)
                for budget in (16, 1024):
                    case = WORK / f"{stage}-b{budget}"
                    case.mkdir(exist_ok=True)
                    emit_cpp(session, design="design.main", top="flow_top", output=case / "model", overwrite=True,
                             max_function_lines=budget, max_tu_bytes=4096)
                    self.write_driver(case)
                    manifest = json.loads((case / "model/manifest.json").read_bytes())
                    identity = json.loads((case / "model/generation-identity.json").read_bytes())
                    self.assertEqual(identity["kind"], "api-emit")
                    self.assertTrue(identity["loaded_libraries"])
                    self.assertEqual(identity["emit"]["options"]["max_function_lines"], budget)
                    self.assertEqual(identity["generated"], generated_identity(case / "model"))
                    self.assertLessEqual(max(fn["lines"] for fn in manifest["functions"]), budget)
                    graph_ops = json.loads(rewritten.read_bytes())["graphs"][0]["ops"]
                    supernodes = {tuple(op["attrs"]["grhsim.partition"]["vs"][:3]) for op in graph_ops
                                  if op.get("attrs", {}).get("grhsim.partition", {}).get("vs", [])[:2] == ["general", "nonsink"]}
                    leaves = {tuple(op["attrs"]["grhsim.partition"]["vs"]) for op in graph_ops
                              if "grhsim.partition" in op.get("attrs", {})}
                    self.assertEqual({tuple(fn["partition"]) for fn in manifest["nonsink_functions"]}, supernodes)
                    self.assertEqual(manifest["virtual_partition_count"], len(leaves))
                    origin = build_grh_manifest(rewritten, json.loads(rewritten.read_bytes()),
                                                case / "model/manifest.json", op_level=True)
                    self.assertEqual(len(origin["supernodes"]), len(manifest["nonsink_functions"]))
                    self.assertTrue(all(entry["partition"] == manifest["nonsink_functions"][entry["ordinal"]]["partition"]
                                        for entry in origin["supernodes"]))
                    if manifest["nonsink_functions"]:
                        manifest["nonsink_functions"][0]["operation_symbols"].append("missing-operation")
                        corrupted = case / "stale-manifest.json"
                        corrupted.write_text(json.dumps(manifest))
                        with self.assertRaisesRegex(ValueError, "Unknown/duplicate"):
                            build_grh_manifest(rewritten, json.loads(rewritten.read_bytes()), corrupted)
                # Failed replacement must preserve a reviewable previous model.
                destination = WORK / f"{stage}-b16/model"
                header = (destination / "grhsim_flow_top.hpp").read_bytes()
                identity = (destination / "generation-identity.json").read_bytes()
                with self.assertRaises(RuntimeError):
                    emit_cpp(session, design="design.main", top="flow_top", output=destination, overwrite=True,
                             max_function_lines=4)
                self.assertEqual((destination / "grhsim_flow_top.hpp").read_bytes(), header)
                self.assertEqual((destination / "generation-identity.json").read_bytes(), identity)

        cases = [f"{stage}-b{budget}" for stage in STAGES for budget in (16, 1024)]
        make = ".PHONY: run " + " ".join(cases) + "\nrun: " + " ".join(cases) + "\n"
        for case in cases:
            make += f"{case}:\n\t$(MAKE) -C {case} -f run.mk run\n"
        (WORK / "Makefile").write_text(make)

    @staticmethod
    def write_driver(case):
        (case / "driver.cpp").write_text(r'''#include "model/grhsim_flow_top.hpp"
#include <array>
#include <cassert>
#include <cstdio>
int main() {
    GrhSIM_flow_top model;
    for (unsigned epoch=0; epoch<3; ++epoch) {
        model.init();
        std::array<unsigned,4> mem{1,1,1,1}, shadow{};
        unsigned q=5;
        bool oldClk=false, oldGated=false, oldReset=false;
        for (unsigned step=0; step<80; ++step) {
            const bool clk=step%2, gate=(step/7)%2, reset=step%13!=5, en=step%5!=3;
            const unsigned addr=step%7, data=step*17%256;
            const bool gated=clk && gate;
            if ((!oldGated && gated) || (oldReset && !reset)) {
                if (!reset) q=18; else if(en) q=data;
            }
            if (!oldClk && clk && en && addr<4) { shadow[addr]=mem[addr]; mem[addr]=data; }
            model.clk=clk; model.gate=gate; model.reset_n=reset; model.en=en; model.addr=addr; model.data=data;
            model.eval();
            if (model.qout!=q || model.mout!=(addr<4?mem[addr]:0) || model.shadowout!=(addr<4?shadow[addr]:0)) {
                std::fprintf(stderr,"epoch=%u step=%u actual=%u,%u,%u expected=%u,%u,%u\n",epoch,step,
                    model.qout,model.mout,model.shadowout,q,addr<4?mem[addr]:0,addr<4?shadow[addr]:0); return 1;
            }
            const auto before=model.perf_counters().totalRoundCount;
            model.eval();
            assert(model.qout==q && model.mout==(addr<4?mem[addr]:0));
            assert(model.perf_counters().totalRoundCount==before+1);
            oldClk=clk; oldGated=gated; oldReset=reset;
        }
    }
}
''')
        (case / "run.mk").write_text("""CXX := clang++
CXXFLAGS := -std=c++20 -O1 -fno-strict-aliasing -DWOLVRIX_GRHSIM_PERF=1
model/libgrhsim_flow_top.a: model/Makefile
	$(MAKE) -C model CXX='$(CXX)' CXXFLAGS='$(CXXFLAGS)'
driver: driver.cpp model/libgrhsim_flow_top.a
	$(CXX) $(CXXFLAGS) $< model/libgrhsim_flow_top.a -o $@
run: driver
	./driver
.PHONY: run
""")


if __name__ == "__main__":
    unittest.main()
