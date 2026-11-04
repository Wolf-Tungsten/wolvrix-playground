"""Execute the ordinary Python API and every completed checkpoint restart."""

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import wolvrix

from grhsim_flow import FlowOptions, STAGES, checked, emit_cpp, finish_simulation_graph, run_pass, store_checkpoint
from grhsim_supernode_origin_stats import build_grh_manifest
from grhsim_provenance import generated_identity
from wolvrix_xs_grhsim import GRH_PIPELINE, GRH_BRINGUP_PIPELINE, grh_pipeline, read_source_pipeline


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("GRHSIM_FLOW_TEST_WORK", ROOT / "ptmp/remove-grhsim-ir/r6-flow-tests"))


class FlowTest(unittest.TestCase):
    def test_production_prefix_selection_and_historical_native_compatibility(self):
        request = {"sources": [{"language": "firrtl", "path": "input.fir"}]}
        report = {"prefix_wall_s": 1.25, "ingest_diagnostic_count": 0,
                  "stages": [{"pass": name} for name, _ in GRH_PIPELINE[:8]]}
        session = mock.Mock()
        session.read_sources.return_value = []
        session.get.return_value = report
        diagnostics, remaining, actual = read_source_pipeline(session, request, GRH_PIPELINE)
        self.assertEqual(diagnostics, [])
        self.assertEqual(remaining, GRH_PIPELINE[8:])
        self.assertEqual(actual["stages"], report["stages"])
        self.assertEqual(actual["ingest_diagnostics"], [])
        self.assertEqual([(row["pass"], row["options"]) for row in actual["pipeline"]], GRH_PIPELINE[:8])
        session.read_sources.assert_called_once_with(**request, out_design="design.main", pipeline="grh-pre-flatten")
        session.get.assert_called_once_with("design.main.prefix")
        session.reset_mock()
        session.read_sources.side_effect = [TypeError("'pipeline' is an invalid keyword argument for this function"), []]
        diagnostics, remaining, actual = read_source_pipeline(session, request, GRH_PIPELINE)
        self.assertEqual(remaining, GRH_PIPELINE)
        self.assertIsNone(actual)
        self.assertEqual(session.read_sources.call_args_list[-1], mock.call(**request, out_design="design.main"))
        session.get.assert_not_called()
        session.reset_mock(side_effect=True)
        session.read_sources.return_value = []
        _, remaining, actual = read_source_pipeline(session, request, GRH_BRINGUP_PIPELINE)
        self.assertEqual(remaining, GRH_BRINGUP_PIPELINE)
        self.assertIsNone(actual)
        session.read_sources.assert_called_once_with(**request, out_design="design.main")
        session.read_sources.side_effect = TypeError("unrelated conversion failure")
        with self.assertRaisesRegex(TypeError, "unrelated conversion failure"):
            read_source_pipeline(session, request, GRH_PIPELINE)
        session.read_sources.side_effect = None
        session.get.return_value = {**report, "stages": []}
        with self.assertRaisesRegex(RuntimeError, "production pass order"):
            read_source_pipeline(session, request, GRH_PIPELINE)

    def test_firrtl_node_annotations_compiled(self):
        work = WORK / "firrtl-node-annotations"
        work.mkdir(parents=True, exist_ok=True)
        fixtures = ROOT / "wolvrix/tests/ingest/data/firrtl/state"
        driver = r'''#include "model/grhsim_top.hpp"
#include "workload.hpp"
#include <fstream>
int main() {
    std::ofstream output("outputs.txt");
    output.exceptions(std::ios::badbit | std::ios::failbit);
    GrhSIM_top model;
    for (unsigned epoch=0; epoch<3; ++epoch) {
        model.init();
        firrtl_state_test::renameTrace([&](const auto& in, const auto& expected) {
            model.clk=in.at("clk"); model.reset=in.at("reset");
            model.en0=in.at("en0"); model.en1=in.at("en1"); model.copy=in.at("copy");
            model.addr0=in.at("addr0"); model.addr1=in.at("addr1");
            model.data0=in.at("data0"); model.data1=in.at("data1");
            for (unsigned i=0; i<4; ++i) model.initialValue[i]=(in.at("initialValue")>>(8*i))&255;
            model.eval();
            uint64_t packed=0;
            for (unsigned i=0; i<4; ++i) packed |= uint64_t(model.tableOut[i])<<(8*i);
            if (packed!=expected.at("tableOut") || model.readOut!=expected.at("readOut"))
                throw std::runtime_error("node annotation compiled rename scoreboard mismatch");
            output << packed << ' ' << uint64_t(model.readOut) << '\n';
        });
    }
}
'''
        cases = [(profile, annotations) for profile in ("optimized", "bringup", "one-round", "one-round-bytes")
                 for annotations in (True, False)]
        for profile, annotations in cases:
            case = work / f"{profile}-{'on' if annotations else 'off'}"
            case.mkdir(parents=True, exist_ok=True)
            with self.subTest(profile=profile, node_annotations=annotations), wolvrix.Session() as session:
                session.diagnostics_raise_min_level = "none"
                checked(session.read_firrtl(str(fixtures / "rename.fir"), tops=["top"],
                    firrtl_options={"node_annotations": annotations, "init_policy": "zero",
                                    "invalid_policy": "zero"}), "read FIRRTL annotation fixture")
                metadata = session.graph_metadata(design="design.main", top="top")["metadata"]
                self.assertEqual("firrtl.nodeScopePolicy" in metadata, annotations)
                with mock.patch.dict(os.environ, {"XS_GRHSIM_PIPELINE_PROFILE": "bringup"}):
                    for name, pass_options in grh_pipeline():
                        checked(session.run_pass(name, design="design.main", **pass_options), name)
                options = FlowOptions(firrtl_node_cse="off", firrtl_nodes="off", max_supernode_nodes=4)
                if profile != "optimized":
                    options.simplify = profile.startswith("one-round")
                    options.pack_bit_registers = False
                    options.recover_masked_or = False
                    options.partition_simplify = False
                    options.clone_shared = False
                if profile.startswith("one-round"):
                    options.simplify_max_rounds = 1
                if profile == "one-round-bytes":
                    options.cost_model = "bytes"
                with mock.patch("grhsim_flow.run_pass", wraps=run_pass) as passes:
                    finish_simulation_graph(session, design="design.main", top="top", options=options)
                executed = [call.args[1] for call in passes.call_args_list]
                for name in ("grh-to-grhsim", "grhsim-split-event-and-output",
                             "grhsim-split-nonsink-and-sink", "grhsim-partition-nonsink",
                             "grhsim-partition-sink"):
                    self.assertIn(name, executed)
                self.assertEqual("grhsim-simplify" in executed, profile != "bringup")
                for name in ("grhsim-pack-bit-registers", "grhsim-recover-masked-or"):
                    self.assertEqual(name in executed, profile == "optimized")
                if profile.startswith("one-round"):
                    simplified = [call for call in passes.call_args_list if call.args[1] == "grhsim-simplify"]
                    self.assertEqual(len(simplified), 1)
                    self.assertEqual(simplified[0].kwargs["max_rounds"], 1)
                metadata = session.graph_metadata(design="design.main", top="top")["metadata"]
                if annotations:
                    self.assertEqual(metadata["firrtl.nodeCseConfig"], "v2/off/5/256/1")
                else:
                    self.assertFalse(any(key.startswith("firrtl.node") for key in metadata))
                emit_cpp(session, design="design.main", top="top", output=case / "model",
                         overwrite=True, waveform=False, readable_names=profile != "one-round-bytes")
            shutil.copyfile(fixtures / "workload.hpp", case / "workload.hpp")
            self.write_driver(case, driver_text=driver, top="top")
        names = [f"{profile}-{'on' if annotations else 'off'}" for profile, annotations in cases]
        make = ".PHONY: run " + " ".join(names) + "\nrun: " + " ".join(names) + "\n"
        for name in names[1:]:
            make += f"\tcmp optimized-on/outputs.txt {name}/outputs.txt\n"
        make += " ".join(names) + ":\n\t$(MAKE) -C $@ -f run.mk run\n"
        (work / "run.mk").write_text(make)

    def test_firrtl_node_modes_and_resume(self):
        work = WORK / "firrtl-nodes"
        work.mkdir(parents=True, exist_ok=True)
        source = work / "top.fir"
        source.write_text("FIRRTL version 6.0.0\ncircuit top :\n  public module top :\n"
            "    input a : UInt<8>\n    input b : UInt<8>\n" +
            "".join(f"    output y{i} : UInt<8>\n" for i in range(5)) +
            "".join(f"    node n{i} = not(and(a, b))\n" for i in range(5)) +
            "".join(f"    connect y{i}, n{i}\n" for i in range(5)))
        for mode in ("off", "gsim"):
            checkpoints = {}
            options = FlowOptions(firrtl_node_cse=mode, max_supernode_nodes=4,
                                  firrtl_nodes="prefer" if mode == "gsim" else "off",
                                  cost_model="bytes" if mode == "gsim" else "legacy",
                                  nonsink_report=str(work / f"{mode}-partition.txt"))
            with wolvrix.Session() as session:
                session.diagnostics_raise_min_level = "none"
                checked(session.read_firrtl(str(source)), "read FIRRTL node fixture")
                for name, pass_options in GRH_PIPELINE:
                    checked(session.run_pass(name, design="design.main", **pass_options), name)
                def checkpoint(stage):
                    path = work / f"{mode}-{stage}.json"
                    store_checkpoint(session, path, design="design.main", top="top")
                    checkpoints[stage] = path
                finish_simulation_graph(session, design="design.main", top="top", options=options, checkpoint=checkpoint)
                self.assertEqual(set(checkpoints), set(STAGES))
                emit_cpp(session, design="design.main", top="top", output=work / f"model-{mode}", overwrite=True)
                identity = json.loads((work / f"model-{mode}/generation-identity.json").read_text())
                self.assertEqual(identity["firrtl_node_policy"]["firrtl.nodeCseConfig"], f"v2/{mode}/5/256/1")
                self.assertIn("grhsim.nonsinkConfig", identity["firrtl_node_policy"])
                self.assertIn("grhsim.nonsinkHintStats", identity["firrtl_node_policy"])
                self.assertIn(f"requested={options.firrtl_nodes}", (work / f"{mode}-partition.txt").read_text())
            for stage, path in checkpoints.items():
                with wolvrix.Session() as session:
                    session.diagnostics_raise_min_level = "none"
                    checked(session.read_json_file(str(path), out_design="design.main"), "reload FIRRTL")
                    metadata = session.graph_metadata(design="design.main", top="top")["metadata"]
                    self.assertEqual(FlowOptions.from_metadata(metadata).firrtl_node_cse, mode)
                    self.assertEqual(metadata["firrtl.nodeRetention"][0], "v2")
                    with self.assertRaisesRegex(ValueError, "policy/configuration differs"):
                        finish_simulation_graph(session, design="design.main", top="top",
                            options=FlowOptions(firrtl_node_cse="gsim" if mode == "off" else "off"))
                    finish_simulation_graph(session, design="design.main", top="top")
                    resumed = work / f"{mode}-{stage}-resumed.json"
                    store_checkpoint(session, resumed, design="design.main", top="top")
                    if stage in ("nonsink-partitioned", "sink-partitioned"):
                        self.assertEqual(resumed.read_bytes(), checkpoints["sink-partitioned"].read_bytes())
                        restored = FlowOptions.from_metadata(session.graph_metadata(design="design.main", top="top")["metadata"])
                        self.assertEqual(restored.nonsink_options(), options.nonsink_options())
                        restored.firrtl_nodes = "auto"
                        with self.assertRaisesRegex(ValueError, "Changed activity configuration"):
                            finish_simulation_graph(session, design="design.main", top="top", options=restored)
        self.assertNotEqual((work / "off-converted.json").read_bytes(), (work / "gsim-converted.json").read_bytes())

    def test_f09_configuration_validation(self):
        for policy in ("off", "prefer", "auto"):
            for cost in ("legacy", "bytes"):
                config = f"v3/4/1/0/1/8/250000/1/{policy}/{cost}/hint-mffc-v1"
                restored = FlowOptions.from_metadata({"grhsim.nonsinkConfig": config})
                self.assertEqual((restored.firrtl_nodes, restored.cost_model, restored.max_supernode_nodes), (policy, cost, 4))
        for config in ("v1/gsim/5/256/1", "v2/bad/5/256/1"):
            with self.assertRaises(ValueError):
                FlowOptions.from_metadata({"firrtl.nodeCseConfig": config})
        for config in ("v2/2/4/1/0/1/8/250000/1/must/legacy/0/op-hints-v1",
                       "v2/2/4/1/0/1/8/250000/1/off/unknown/0/op-hints-v1",
                       "v2/2/4/1/0/1/8/250000/1/prefer/legacy/0/op-hints-v1",
                       "v3/0/1/0/1/8/250000/1/prefer/legacy/hint-mffc-v1",
                       "v3/4/1/2/1/8/250000/1/prefer/legacy/hint-mffc-v1",
                       "v3/4/1/0/1/8/250000/1/must/legacy/hint-mffc-v1",
                       "v3/4/1/0/1/8/250000/1/off/unknown/hint-mffc-v1"):
            with self.assertRaises(ValueError):
                FlowOptions.from_metadata({"grhsim.nonsinkConfig": config})
        class Checkpoint:
            def __init__(self, metadata):
                self.metadata = metadata
            def graph_metadata(self, **kwargs):
                return {"metadata": self.metadata}
        with self.assertRaisesRegex(ValueError, "Legacy nonsink"):
            finish_simulation_graph(Checkpoint({"grhsim.stage": "sink-partitioned",
                "grhsim.nonsinkConfig": "2/4/1/0/1/8/250000/1"}), design="test", top="top")
        with self.assertRaisesRegex(ValueError, "soft-node-v2"):
            finish_simulation_graph(Checkpoint({"grhsim.stage": "converted", "firrtl.nodeSchema": 1,
                "firrtl.nodeScopePolicy": "source-node-v1", "firrtl.nodeInventory": []}), design="test", top="top")

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
        options = FlowOptions(mem_min_bytes=4, max_supernode_nodes=4,
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
        cases.append("firrtl-node-annotations")
        make = ".PHONY: run " + " ".join(cases) + "\nrun: " + " ".join(cases) + "\n"
        for case in cases:
            make += f"{case}:\n\t$(MAKE) -C {case} -f run.mk run\n"
        (WORK / "Makefile").write_text(make)

    @staticmethod
    def write_driver(case, *, driver_text=None, top="flow_top"):
        (case / "driver.cpp").write_text(driver_text if driver_text is not None else r'''#include "model/grhsim_flow_top.hpp"
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
""".replace("grhsim_flow_top", f"grhsim_{top}"))


if __name__ == "__main__":
    unittest.main()
