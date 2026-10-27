"""Exercise readable GRH/C++ exports through the real public Python API."""

import json
import os
import re
import shutil
import unittest
from pathlib import Path

import wolvrix

from grhsim_flow import FlowOptions, STAGES, checked, finish_simulation_graph
from wolvrix_xs_grhsim import GRH_PIPELINE


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("GRHSIM_READABLE_TEST_WORK", ROOT / "ptmp/grhsim-readable/python"))
TOP = "readable_top"
VARIANTS = {
    "default": {},
    "compact-names": {"readable_names": False},
    "no-comments": {"source_comments": False},
    "no-dump": {"readable_dump": False},
    "compact-frames": {"readable_frames": False},
}

SOURCE = r"""module readable_alu(input logic clk, en, input logic [7:0] data,
    output logic [7:0] qout, prevout, mixed);
logic [7:0] accumulator = 8'd5;
logic [7:0] previous = 8'd0;
wire [7:0] sum = accumulator + data;
always @(posedge clk) if (en) begin
    accumulator <= sum;
    previous <= accumulator;
end
assign qout = accumulator;
assign prevout = previous;
assign mixed = accumulator ^ data;
endmodule

module readable_core(input logic clk, en, input logic [2:0] addr,
    input logic [7:0] data, output logic [7:0] qout, prevout, mixed, mout, shadowout);
logic [7:0] memory [0:3];
logic [7:0] shadow [0:3];
initial begin
    for (integer i = 0; i < 4; i = i + 1) begin
        memory[i] = 8'd1;
        shadow[i] = 8'd0;
    end
end
readable_alu alu(.clk(clk), .en(en), .data(data),
    .qout(qout), .prevout(prevout), .mixed(mixed));
always @(posedge clk) if (en) begin
    memory[addr] <= data;
    shadow[addr] <= memory[addr];
end
assign mout = memory[addr];
assign shadowout = shadow[addr];
endmodule

module readable_top(input logic clk, en, input logic [2:0] addr,
    input logic [7:0] data, output logic [7:0] qout, prevout, mixed, mout, shadowout);
readable_core core(.clk(clk), .en(en), .addr(addr), .data(data),
    .qout(qout), .prevout(prevout), .mixed(mixed), .mout(mout), .shadowout(shadowout));
endmodule
"""

DRIVER = r'''#include "model/grhsim_readable_top.hpp"
#include <array>
#include <cstdio>
int main() {
    GrhSIM_readable_top model;
    for (unsigned epoch = 0; epoch < 3; ++epoch) {
        model.init();
        std::array<unsigned, 4> memory{1,1,1,1}, shadow{};
        unsigned accumulator = 5, previous = 0;
        bool oldClock = false;
        for (unsigned step = 0; step < 80; ++step) {
            const bool clock = step % 2, enable = step % 5 != 3;
            const unsigned address = step % 7, data = step * 17 % 256;
            if (!oldClock && clock && enable) {
                previous = accumulator;
                accumulator = (accumulator + data) & 255;
                if (address < 4) { shadow[address] = memory[address]; memory[address] = data; }
            }
            model.clk = clock; model.en = enable; model.addr = address; model.data = data;
            for (unsigned repeat = 0; repeat < 2; ++repeat) {
                model.eval();
                const unsigned expectedMemory = address < 4 ? memory[address] : 0;
                const unsigned expectedShadow = address < 4 ? shadow[address] : 0;
                if (model.qout != accumulator || model.prevout != previous ||
                    model.mixed != (accumulator ^ data) || model.mout != expectedMemory ||
                    model.shadowout != expectedShadow) {
                    std::fprintf(stderr, "epoch=%u step=%u repeat=%u actual=%u,%u,%u,%u,%u expected=%u,%u,%u,%u,%u\n",
                        epoch, step, repeat, model.qout, model.prevout, model.mixed, model.mout, model.shadowout,
                        accumulator, previous, accumulator ^ data, expectedMemory, expectedShadow);
                    return 1;
                }
            }
            oldClock = clock;
        }
    }
    std::puts("readability NBA/read/write checks passed");
}
'''

RUN_MAKE = """CXX := clang++
CXXFLAGS := -std=c++20 -O1 -fno-strict-aliasing
model/libgrhsim_readable_top.a: model/Makefile
\t$(MAKE) -C model CXX='$(CXX)' CXXFLAGS='$(CXXFLAGS)'
driver: driver.cpp model/libgrhsim_readable_top.a
\t$(CXX) $(CXXFLAGS) $< model/libgrhsim_readable_top.a -o $@
run: driver
\t./driver
.PHONY: run
"""


class ReadableTest(unittest.TestCase):
    def test_public_api_and_generated_mapping(self):
        WORK.mkdir(parents=True, exist_ok=True)
        source = WORK / "hierarchy.sv"
        source.write_text(SOURCE)
        with wolvrix.Session() as session:
            session.diagnostics_raise_min_level = "none"
            checked(session.read_sv(str(source), out_design="design.main", slang_args=["--top", TOP]), "read hierarchy")
            for name, options in GRH_PIPELINE:
                checked(session.run_pass(name, design="design.main", **options), name)
            saved_stages = set()

            def checkpoint(stage):
                path = WORK / f"{stage}.grh.txt"
                checked(session.store_text(design="design.main", output=str(path)), f"store readable {stage}")
                snapshot = path.read_text()
                self.assertIn(f'grhsim.stage = "{stage}"', snapshot)
                self.assertIn("six-phase-model:", snapshot)
                self.assertIn("hierarchy.sv", snapshot)
                if stage == "sink-partitioned":
                    self.assertIn("status: validated complete=true", snapshot)
                else:
                    self.assertIn("status: unavailable", snapshot)
                saved_stages.add(stage)

            finish_simulation_graph(session, design="design.main", top=TOP,
                options=FlowOptions(pack_bit_registers=False, recover_masked_or=False, mem_min_bytes=4,
                                    max_node_work=2, max_supernode_work=4, clone_shared=False,
                                    enable_guard_min_size=2), checkpoint=checkpoint)
            self.assertEqual(saved_stages, set(STAGES))
            checkpoint_before = WORK / "before.json"
            checked(session.store_json(design="design.main", output=str(checkpoint_before)), "store original JSON")
            baseline = checkpoint_before.read_bytes()
            graph = next(item for item in json.loads(baseline)["graphs"] if item["symbol"] == TOP)
            failure = WORK / "byte-budget-model"
            for invalid in (0, -1, 2**64):
                with self.assertRaises(ValueError):
                    session.emit_grhsim_cpu_st_cpp(design="design.main", output=str(failure),
                                                  max_output_file_bytes=invalid)
            errors = session.emit_grhsim_cpu_st_cpp(design="design.main", output=str(failure),
                                                  max_output_file_bytes=1)
            self.assertTrue(any(item["kind"] == "error" for item in errors))
            self.assertFalse(failure.exists())
            self.assertFalse(list(WORK.glob("byte-budget-model.staging-*")))
            for variant, options in VARIANTS.items():
                case = WORK / variant
                case.mkdir(exist_ok=True)
                model = case / "model"
                if model.exists():
                    shutil.rmtree(model)
                checked(session.emit_grhsim_cpu_st_cpp(design="design.main", output=str(model), top=[TOP],
                    max_function_lines=16, max_tu_bytes=4096,
                    max_output_file_bytes=32 * 1024**3 if variant == "default" else 4 * 1024**3,
                    **options), f"emit {variant}")
                self.check_model(model, variant, graph)
                checkpoint_after = case / "after.json"
                checked(session.store_json(design="design.main", output=str(checkpoint_after)), "store unmodified JSON")
                self.assertEqual(checkpoint_after.read_bytes(), baseline, variant)
                (case / "driver.cpp").write_text(DRIVER)
                (case / "run.mk").write_text(RUN_MAKE)
        make = ".PHONY: run " + " ".join(VARIANTS) + "\nrun: " + " ".join(VARIANTS) + "\n"
        for variant in VARIANTS:
            make += f"{variant}:\n\t$(MAKE) -C {variant} -f run.mk run\n"
        (WORK / "Makefile").write_text(make)

    def check_model(self, model, variant, graph):
        manifest = json.loads((model / "manifest.json").read_bytes())
        mapping = json.loads((model / "code-map.json").read_bytes())
        self.assertEqual(mapping["schema"], "grhsim-code-map.v1")
        self.assertEqual(mapping["readable_names"], variant != "compact-names")
        self.assertEqual(manifest["readable_names"], variant != "compact-names")
        self.assertEqual(manifest["source_comments"], variant != "no-comments")
        self.assertEqual(manifest["readable_frames"], variant != "compact-frames")
        self.assertLessEqual(max(item["lines"] for item in manifest["functions"]), 16)
        self.assertEqual(len(mapping["values"]), len(graph["vals"]))
        self.assertEqual(len(mapping["operations"]), len(graph["ops"]))
        operations = {item["operation_id"]: item for item in mapping["operations"]}
        values = {item["value_id"]: item for item in mapping["values"]}
        self.assertEqual(len(operations), len(graph["ops"]))
        self.assertEqual(len(values), len(graph["vals"]))
        files = {path.name: path.read_text() for path in model.glob("*.cpp")}
        header = (model / "grhsim_readable_top.hpp").read_text()
        all_code = header + "\n" + "\n".join(files.values())
        self.assertTrue(any(item.get("source_location", {}).get("file", "").endswith("hierarchy.sv")
                            and item["source_location"].get("line", 0) > 0 for item in operations.values()))
        for value in values.values():
            if "producer" in value:
                self.assertIn(value["producer"], operations)
            for storage in value["storage"]:
                reference = storage["reference"]
                self.assertIsInstance(reference, str)
                self.assertTrue(reference)
                if storage["role"] != "snapshot-view":
                    self.assertIn(reference.split(".")[0], all_code)
                    field = re.search(r"\.([A-Za-z_][A-Za-z_0-9]*)", reference)
                    if field:
                        self.assertIn(field.group(1), all_code)
        for function in mapping["functions"]:
            body = files[function["source"]]
            self.assertIn("::" + function["name"] + "(", body)
            for operation in function["operations"]:
                self.assertIn(operation, operations)
            for local in function["locals"]:
                self.assertIn(local["reference"], body)
            self.assertIn(function["root_function"], {item["name"] for item in mapping["functions"]})
        self.assertEqual({item["name"] for item in manifest["functions"]},
                         {item["name"] for item in mapping["functions"]})
        self.assertTrue(any(function["operations"] for function in mapping["functions"]))
        dump = model / "grhsim.txt"
        self.assertEqual(dump.exists(), variant != "no-dump")
        if dump.exists():
            readable = dump.read_text()
            self.assertIn("status: validated complete=true", readable)
            self.assertIn("core$alu", readable)
            self.assertIn("origin-set[", readable)
            self.assertIn("hierarchy.sv", readable)
        if variant == "compact-names":
            self.assertTrue(all(re.fullmatch(r"v\d+", item["cpp_name"]) for item in values.values()))
        else:
            self.assertTrue(any("alu" in item["cpp_name"] and "accumulator" in item["cpp_name"]
                                for item in operations.values()))
        if variant == "no-comments":
            self.assertNotIn("Phase 1 Input:", all_code)
            self.assertNotIn("origin unavailable/generated", all_code)
        else:
            self.assertIn("Phase 1 Input:", all_code)
            self.assertIn("source=", all_code)


if __name__ == "__main__":
    unittest.main()
