#!/usr/bin/env python3
"""Validate the frozen AheadBtbReplacer against an independent tree-PLRU model."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess

import wolvrix

from grhsim_flow import FlowOptions, checked, emit_cpp, finish_simulation_graph, store_checkpoint
from grhsim_provenance import capture_generation, file_identity, generated_identity, write_identity
from wolvrix_xs_grhsim import GRH_PIPELINE, firrtl_grh_pipeline, timed
from xs_firrtl_compare import (LAYERS, ROOT, bindings, canonical_leaves, driver,
                               packed_words, port_values, sv_closure, word_layout, words_in)
from xs_firrtl_inputs import create_manifest

TOP = "AheadBtbReplacer"
VARIANTS = ("firrtl-off", "firrtl-prefer", "sv-off", "verilator")
INPUT_WIDTHS = [("clock", 1), ("reset", 1), ("io_readValid", 1),
                ("io_readSetIdx", 5), *[(f"io_readWayMask_{i}", 1) for i in range(8)],
                ("io_writeValid", 1), ("io_writeSetIdx", 5),
                ("io_writeWayIdx", 3), ("io_replaceSetIdx", 5)]


def touch(state, way):
    """Point each node on the accessed leaf's path toward its sibling subtree.

    Nodes use the RTL's postorder numbering, with bit 6 at the root. This
    iterative interval walk is independent of the RTL's recursive bit slices.
    """
    low, size, node = 0, 8, 6
    while size > 1:
        half = size // 2
        upper = way >= low + half
        state = (state & ~(1 << node)) | (int(not upper) << node)
        if upper:
            low += half
            node -= 1
        else:
            node -= half
        size = half
    return state


def victim(state):
    low, size, node = 0, 8, 6
    while size > 1:
        half = size // 2
        if state & (1 << node):
            low += half
            node -= 1
        else:
            node -= half
        size = half
    return low


def update(states, values):
    if values["reset"]:
        states[:] = [0] * 32
        return
    read_set, write_set = values["io_readSetIdx"], values["io_writeSetIdx"]
    if values["io_readValid"] and not (values["io_writeValid"] and read_set == write_set):
        state = states[read_set]
        for way in range(8):
            if values[f"io_readWayMask_{way}"]:
                state = touch(state, way)
        states[read_set] = state
    if values["io_writeValid"]:
        states[write_set] = touch(states[write_set], values["io_writeWayIdx"])


def operations():
    """Yield directed traffic; scans observe every set between each mask sweep."""
    def op(kind, set_idx=0, mask=0, way=0, write_set=None, valid=1):
        return {"kind": kind, "reset": int(kind == "reset"),
                "io_readValid": int(kind in ("read", "same", "different", "invalid") and valid),
                "io_readSetIdx": set_idx, "io_readWayMask": mask,
                "io_writeValid": int(kind in ("write", "same", "different", "check")),
                "io_writeSetIdx": set_idx if write_set is None else write_set,
                "io_writeWayIdx": way, "io_replaceSetIdx": set_idx}

    for _ in range(4):
        yield op("reset")
    for set_idx in range(32):
        yield op("scan", set_idx)
    for kind in ("read", "same", "different", "invalid"):
        for set_idx in range(32):
            for mask in range(256):
                for way in (range(8) if kind in ("same", "different") else (0,)):
                    write_set = (set_idx + way + 1) % 32 if kind == "different" else set_idx
                    yield op(kind, set_idx, mask, way, write_set, valid=kind != "invalid")
                    if kind == "different":
                        # Observe the independently updated write set as well.
                        yield op("scan", write_set)
                if kind in ("read", "invalid"):
                    # Trigger the unmodified duplicate-state assertion after
                    # every mask, without changing the observed read set.
                    yield op("check", set_idx, way=mask % 8, write_set=(set_idx + 1) % 32)
            for observed in range(32):
                yield op("scan", observed)
    for set_idx in range(32):
        for way in range(8):
            yield op("write", set_idx, way=way)
    rng = random.Random(0xAB7BF10)
    for _ in range(8192):
        set_idx, write_set = rng.randrange(32), rng.randrange(32)
        kind = rng.choice(("read", "write", "same", "different", "invalid", "scan"))
        if kind == "same":
            write_set = set_idx
        if kind == "different" and write_set == set_idx:
            write_set = (write_set + 1) % 32
        yield op(kind, set_idx, rng.randrange(256), rng.randrange(8), write_set,
                 valid=kind != "invalid")
    for set_idx in range(32):
        yield op("check", set_idx, way=set_idx % 8)


def stimulus(args, layout, selected_ops=None):
    work = args.output
    states, coverage, state_values, victim_values = [0] * 32, Counter(), set(), set()
    ops = list(operations()) if selected_ops is None else selected_ops
    in_record = struct.Struct(f"<{words_in(layout['inputs'])}Q")
    with (work / "inputs.bin").open("wb") as source, (work / "expected.bin").open("wb") as expected:
        source.write(struct.pack("<8sQII", b"FirXio01", len(ops) * 2,
                                 words_in(layout["inputs"]), words_in(layout["outputs"])))
        for cycle, operation in enumerate(ops):
            values = dict(operation)
            mask = values.pop("io_readWayMask")
            for way in range(8):
                values[f"io_readWayMask_{way}"] = (mask >> way) & 1
            coverage[values["kind"]] += 1
            coverage["zero_mask_read"] += bool(values["io_readValid"] and not mask)
            coverage["multiple_mask_read"] += bool(values["io_readValid"] and mask.bit_count() > 1)
            for clock in (0, 1):
                values["clock"] = clock
                source.write(in_record.pack(*packed_words(layout["inputs"], values)))
                # All state starts under source reset. Both clock levels are
                # fully checked, including reset, with no comparison masks.
                if values["reset"] or clock:
                    update(states, values)
                selected = states[values["io_replaceSetIdx"]]
                state_values.add(selected)
                result = victim(selected)
                victim_values.add(result)
                expected.write(struct.pack("<Q", result))
    write_identity(work / "stimulus-identity.json", {
        "cycles": len(ops), "records": len(ops) * 2, "seed": "0xAB7BF10",
        "coverage": dict(coverage), "observed_plru_states": sorted(state_values),
        "observed_victims": sorted(victim_values), "sets": 32,
        "directed": ({"read_set_mask_combinations": 32 * 256,
                     "same_set_mask_way_combinations": 32 * 256 * 8,
                     "different_set_mask_way_combinations": 32 * 256 * 8,
                     "invalid_read_set_mask_combinations": 32 * 256} if selected_ops is None else {"minimal_original_module": ops}),
        "assertions": "FIRRTL verification layers enabled; original SV assertion DPI terminates; Verilator --assert",
        "observations": "all output bits at both clock levels, each evaluated three times; no exclusions",
        "inputs": file_identity(work / "inputs.bin"), "scoreboard": file_identity(work / "expected.bin")})


def minimal(args):
    work = args.output / "minimal"
    work.mkdir(exist_ok=True)
    layout = json.loads((args.output / "layout.json").read_text())
    (work / "layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    def op(kind, reset=0, read=0, mask=0, write=0, write_set=9, way=0):
        return {"kind": kind, "reset": reset, "io_readValid": read,
                "io_readSetIdx": 9, "io_readWayMask": mask, "io_writeValid": write,
                "io_writeSetIdx": write_set, "io_writeWayIdx": way, "io_replaceSetIdx": 9}
    ops = [op("reset", reset=1), op("reset", reset=1),
           op("write", write=1, way=6), op("write", write=1, way=4),
           op("different", read=1, mask=4, write=1, write_set=10, way=0),
           op("check", write=1, write_set=11, way=1)]
    stimulus(argparse.Namespace(output=work), layout, ops)
    (work / "operations.json").write_text(json.dumps(ops, indent=2) + "\n")
    for variant in VARIANTS:
        (work / variant).mkdir(exist_ok=True)
    (work / "run.mk").write_text(".PHONY: run " + " ".join(VARIANTS) + "\nrun: " + " ".join(VARIANTS) + "\n" +
        "\n".join(f'{variant}:\n\t"{args.output / variant / "driver"}" inputs.bin {variant}/outputs.bin'
                  for variant in VARIANTS) + "\n")


def reference_identity(args):
    """Record the frozen RTL, current harness/macros and tools before a build."""
    files = {"firrtl": args.firrtl, "filelist": args.sv_dir / "filelist.f"}
    for name in files["filelist"].read_text().splitlines():
        if name.strip():
            files[f"rtl/{name}"] = args.sv_dir / name
    difftest = ROOT / "testcase/xiangshan/difftest"
    roots = [difftest / "src/test", difftest / "config", *args.include_dir]
    for directory in roots:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in (".v", ".sv", ".svh", ".cpp", ".h", ".hpp"):
                files[str(path.relative_to(ROOT))] = path
    for path in [difftest / "Makefile", *difftest.glob("*.mk")]:
        files[str(path.relative_to(ROOT))] = path
    for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so"):
        files[name] = ROOT / "testcase/xiangshan/ready-to-run" / name
    tools = {}
    for name in ("verilator", "verilator_bin", "clang", "clang++", "make"):
        path = shutil.which(name)
        if path:
            tools[name] = {**file_identity(path),
                "version": subprocess.check_output([path, "--version"], text=True).splitlines()[0]}
    identity = capture_generation("xs-firrtl-original-sv-reference-noopt", inputs=files,
        configuration={"top": "SimTop", "rtl": args.sv_dir, "build": args.output,
                       "EMU_OPTIMIZE": "-O0", "XS_SIM_VFLAGS": (args.reference_vflags or "+define+DIFFTEST") +
                           (f" --language {args.reference_language}" if args.reference_language else ""),
                       "EMU_RANDOMIZE": 0, "XS_ZERO_INIT": 0, "NUM_CORES": 1,
                       "EMU_THREADS": 2, "VM_BUILD_JOBS": 4, "XS_WAVEFORM": 0,
                       "assertions": "--assert; original xs_assert_v2 DPI; no SYNTHESIS/TB_NO_DPIC/STOP_COND override",
                       "runtime": "fixed 100000 cycles with original CoreMark and NEMU"})
    identity["tools"] = tools
    identity["source_scope"] = "all frozen filelist RTL; actual common/generated SV, macros, harness C++/headers and difftest Makefiles"
    write_identity(args.output / "reference-input-identity.json", identity)
    print(f"reference identity: {len(files)} input files; {args.output / 'reference-input-identity.json'}", flush=True)


def reference_result(args):
    work = args.output
    identity = json.loads((work / "reference-input-identity.json").read_text())
    changed, controls = [], {}
    for name, original in identity["inputs"].items():
        current = file_identity(original["path"])
        is_control = Path(original["path"]).name == "Makefile" or Path(original["path"]).suffix == ".mk"
        if is_control:
            controls[name] = {"before": original, "after": current,
                              "changed": current["sha256"] != original["sha256"]}
        elif current["sha256"] != original["sha256"]:
            changed.append(name)
    root_before = identity["sources"]["files_sha256"]["Makefile"]
    root_after = file_identity(ROOT / "Makefile")
    controls["root/Makefile"] = {"before": {"sha256": root_before}, "after": root_after,
        "changed": root_before != root_after["sha256"],
        "authorized_changes": "reference pipefail and native harness/default-freshness/test rules; actual hardware and compiler flags are bound by input identities and build logs"}
    generated = work / "verilator-compile"
    result = {"kind": "xs-firrtl-original-sv-reference-noopt-result",
              "inputs": file_identity(work / "reference-input-identity.json"),
              "changed_hardware_harness_inputs": changed, "build_controls": controls,
              "binary": file_identity(work / "emu"),
              "generated_sources": generated_identity(generated),
              "build_records": {name: file_identity(generated / name) for name in
                  ("VSimTop.mk", "VSimTop__verFiles.dat", "VSimTop__ver.d") if (generated / name).exists()},
              "logs": {path.name: file_identity(path) for path in work.glob("*.log")},
              "runtime_result": "read the fixed-cycle NEMU run log; artifact capture alone does not imply pass"}
    write_identity(work / "reference-output-identity.json", result)
    if changed:
        raise RuntimeError(f"reference build inputs changed: {changed}")
    print(f"reference artifact identity: {result['binary']['sha256']}; hardware/harness/CoreMark/NEMU inputs unchanged; build controls recorded separately", flush=True)


def generate(args):
    work = args.output
    work.mkdir(parents=True, exist_ok=True)
    sv = [ROOT / "testcase/xiangshan/difftest/src/test/vsrc/common/assert.v",
          *sv_closure(args.sv_dir, TOP)]
    mixed = create_manifest(args.firrtl, top=TOP, enabled_layers=LAYERS,
        include_dirs=args.include_dir, resource_roots=args.include_dir, defines=["DIFFTEST"])
    (work / "sources.json").write_text(json.dumps(mixed, indent=2) + "\n")
    options = FlowOptions(firrtl_nodes="off")
    identity = capture_generation("xs-firrtl-replacer-compare", inputs={
        "firrtl": args.firrtl, **{f"sv_{i}": path for i, path in enumerate(sv)}},
        configuration={"top": TOP, "mixed": mixed, "flow": asdict(options)})
    for language in ("firrtl", "sv"):
        with wolvrix.Session() as session:
            session.log_level = "info"
            if language == "firrtl":
                request = {key: value for key, value in mixed.items() if key != "schema"}
                checked(timed("replacer FIRRTL", lambda: session.read_sources(**request)), "read FIRRTL")
                identity["ingest_dependencies"] = session.graph_metadata(design="design.main", top=TOP)["metadata"].get("ingest.dependencies", [])
            else:
                slang_args = [str(path) for path in sv] + ["--top", TOP, "-D", "DIFFTEST"]
                slang_args += [arg for directory in args.include_dir for arg in ("-I", str(directory))]
                checked(timed("replacer SV", lambda: session.read_sv(None, slang_args=slang_args)), "read SV")
            pipeline = firrtl_grh_pipeline(GRH_PIPELINE) if language == "firrtl" else GRH_PIPELINE
            for name, opts in pipeline:
                checked(timed(f"replacer/{language} {name}", lambda name=name, opts=opts:
                    session.run_pass(name, design="design.main", **opts)), name)
            base = work / f"{language}-base.json"
            store_checkpoint(session, base, design="design.main", top=TOP)
            (work / f"{language}-ports.json").write_text(json.dumps(port_values(base), indent=2) + "\n")
            finish_simulation_graph(session, design="design.main", top=TOP, options=options,
                                    stop_after="nonsink-sink-split")
            common = work / f"{language}-common.json"
            store_checkpoint(session, common, design="design.main", top=TOP)
            for mode in (("off", "prefer") if language == "firrtl" else ("off",)):
                design = "design." + mode
                checked(session.clone_design(design="design.main", out_design=design), "clone common graph")
                variant = work / f"{language}-{mode}"
                variant.mkdir(exist_ok=True)
                branch = replace(options, firrtl_nodes=mode, nonsink_report=str(variant / "nonsink.txt"))
                finish_simulation_graph(session, design=design, top=TOP, options=branch)
                store_checkpoint(session, variant / "final.json", design=design, top=TOP)
                emit_cpp(session, design=design, top=TOP, output=variant / "model", overwrite=True,
                    generation_identity={**identity, "language": language, "mode": mode,
                                         "optimized_checkpoint": file_identity(common)})
                session.delete(design)
    write_identity(work / "identity.json", identity)
    drivers(args)


def verilator_driver(layout, monitor=False):
    paired = {name: (name, 0, width, "input") for name, width in INPUT_WIDTHS
              if not name.startswith("io_readWayMask_")}
    for way in range(8):
        paired[f"io_readWayMask_{way}"] = ("io_readWayMask", way, 1, "input")
    paired["io_victimWayIdx"] = ("io_victimWayIdx", 0, 3, "output")
    code = driver(TOP, paired, layout)
    code = code.replace(f'#include "model/grhsim_{TOP}.hpp"',
        f'#include "VAheadBtbReplacer.h"\n#include "VAheadBtbReplacer___024root.h"\n#include "verilated.h"\n'
        '#include <algorithm>\n#include <cstdint>\n#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n#include <vector>')
    code = code.replace(f"GrhSIM_{TOP}", f"V{TOP}").replace("m.init();", "")
    if not monitor:
        return code.replace("m.eval();", "m.eval(); if(Verilated::gotFinish()) return 7;")
    return code.replace("m.eval();", '''m.eval(); if(Verilated::gotFinish()) return 7;
            if(std::getenv("ABTB_MONITOR")){
                const auto& primary=m.rootp->AheadBtbReplacer__DOT__states__DOT__states;
                const auto& checker=m.rootp->AheadBtbReplacer__DOT__state_vec;
                auto state=[](const auto& words,unsigned set){
                    unsigned bit=7*set,word=bit/32,shift=bit%32;
                    std::uint64_t pair=words[word];
                    if(word+1<7)pair|=std::uint64_t(words[word+1])<<32;
                    return unsigned((pair>>shift)&127);
                };
                for(unsigned set=0;set<32;++set)if(state(primary,set)!=state(checker,set)){
                    output.flush();
                    std::fprintf(stderr,"first state divergence step=%llu cycle=%llu clock=%u set=%u primary=0x%x checker=0x%x read=%u/%u/0x%x write=%u/%u/%u replace=%u\\n",
                        (unsigned long long)step,(unsigned long long)(step/2),unsigned(step%2),set,state(primary,set),state(checker,set),
                        unsigned(m.io_readValid),unsigned(m.io_readSetIdx),unsigned(m.io_readWayMask),
                        unsigned(m.io_writeValid),unsigned(m.io_writeSetIdx),unsigned(m.io_writeWayIdx),unsigned(m.io_replaceSetIdx));
                    return 8;
                }
            }''')


def traced_driver(code):
    code = code.replace('#include <memory>', '#include <memory>\n'
        'static std::uint64_t current_step;\nstatic std::ofstream* active_output;')
    code = code.replace('std::fprintf(stderr,"SV assertion %s:%lld\\n",file,line);std::exit(1);',
        'if(active_output)active_output->flush();'
        'std::fprintf(stderr,"SV assertion %s:%lld step=%llu cycle=%llu clock=%u\\n",file,line,'
        '(unsigned long long)current_step,(unsigned long long)(current_step/2),unsigned(current_step%2));std::exit(1);')
    code = code.replace('std::ofstream output(argv[2],std::ios::binary);',
        'std::ofstream output(argv[2],std::ios::binary);active_output=&output;')
    return code.replace('for(std::uint64_t step=0;step<count;++step){',
        'for(std::uint64_t step=0;step<count;++step){current_step=step;')


def drivers(args):
    work = args.output
    fir_ports = json.loads((work / "firrtl-ports.json").read_text())
    leaves = canonical_leaves(args, TOP, fir_ports)
    layout = {"inputs": word_layout([(name, leaf.width) for name, (direction, leaf) in sorted(leaves.items()) if direction == "input"]),
              "outputs": word_layout([(name, leaf.width) for name, (direction, leaf) in sorted(leaves.items()) if direction == "output"])}
    if {row["name"]: row["width"] for row in layout["inputs"]} != dict(INPUT_WIDTHS):
        raise ValueError("frozen AheadBtbReplacer input interface changed")
    if [(row["name"], row["width"]) for row in layout["outputs"]] != [("io_victimWayIdx", 3)]:
        raise ValueError("frozen AheadBtbReplacer output interface changed")
    (work / "layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    mapping = {}
    for variant in VARIANTS[:-1]:
        language = variant.split("-")[0]
        directory = work / variant
        ports = json.loads((work / f"{language}-ports.json").read_text())
        paired, extra = bindings(ports, directory / f"model/grhsim_{TOP}.hpp", TOP, leaves, language)
        mapping[variant] = {"bindings": paired, "retained_extra_inputs": extra}
        (directory / "driver.cpp").write_text(traced_driver(driver(TOP, paired, layout)))
        (directory / "run.mk").write_text(f"""ifeq ($(origin CXX),default)
CXX := clang++
endif
CXXFLAGS ?= -std=c++20 -O1 -fno-strict-aliasing
model/libgrhsim_{TOP}.a: model/Makefile
	$(MAKE) -C model CXX='$(CXX)' CXXFLAGS='$(CXXFLAGS)'
driver: driver.cpp model/libgrhsim_{TOP}.a
	$(CXX) $(CXXFLAGS) driver.cpp model/libgrhsim_{TOP}.a -lz -o $@
outputs.bin: driver ../inputs.bin
	./driver ../inputs.bin outputs.bin
.PHONY: run
run: outputs.bin
""")
    (work / "bindings.json").write_text(json.dumps(mapping, indent=2) + "\n")
    directory = work / "verilator"
    directory.mkdir(exist_ok=True)
    (directory / "driver.cpp").write_text(traced_driver(verilator_driver(layout, monitor=True)))
    (directory / "driver-noopt.cpp").write_text(traced_driver(verilator_driver(layout)))
    sv = [ROOT / "testcase/xiangshan/difftest/src/test/vsrc/common/assert.v", *sv_closure(args.sv_dir, TOP)]
    include = " ".join(f'-I"{path}"' for path in args.include_dir)
    sources = " ".join(f'"{path}"' for path in sv)
    source_deps = " ".join(str(path).replace(" ", "\\ ") for path in sv)
    (directory / "run.mk").write_text(f"""VERILATOR ?= verilator
driver: driver.cpp {source_deps}
	CCACHE_DIR="{work / 'ccache'}" $(VERILATOR) --cc --exe --build --assert -Wno-fatal --top-module {TOP} --Mdir obj_dir -o ../driver -DDIFFTEST {include} -CFLAGS '-std=c++20 -O1' {sources} "{directory / 'driver.cpp'}"
driver-noopt: driver-noopt.cpp {source_deps}
	CCACHE_DIR="{work / 'ccache'}" $(VERILATOR) -O0 --cc --exe --build --assert -Wno-fatal --top-module {TOP} --Mdir obj_noopt -o ../driver-noopt -DDIFFTEST {include} -CFLAGS '-std=c++20 -O1' {sources} "{directory / 'driver-noopt.cpp'}"
.PHONY: run
run: driver ../inputs.bin
	./driver ../inputs.bin outputs.bin
.PHONY: run-noopt
run-noopt: driver-noopt ../inputs.bin
	./driver-noopt ../inputs.bin outputs-noopt.bin
.PHONY: monitor
monitor: driver ../inputs.bin
	ABTB_MONITOR=1 ./driver ../inputs.bin monitor.bin
""")
    stimulus(args, layout)
    (work / "run.mk").write_text(".PHONY: run " + " ".join(VARIANTS) + "\nrun: " + " ".join(VARIANTS) + "\n" +
        f'\t$(PYTHON) "{ROOT}/scripts/xs_firrtl_replacer.py" compare --output "{work}"\n' +
        " ".join(VARIANTS) + ":\n\t$(MAKE) -C $@ -f run.mk run\n")


def compare(args, *, noopt=False):
    work, differences, first = args.output, Counter(), None
    expected = (work / "expected.bin").read_bytes()
    if not expected or len(expected) % 8:
        raise ValueError("invalid PLRU scoreboard records")
    variants = (*VARIANTS[:-1], "verilator-noopt") if noopt else VARIANTS
    paths = {variant: work / variant / "outputs.bin" for variant in variants}
    if noopt:
        paths["verilator-noopt"] = work / "verilator/outputs-noopt.bin"
    for variant, path in paths.items():
        actual = path.read_bytes()
        if len(actual) != len(expected):
            raise ValueError(f"{variant}: output size {len(actual)} != scoreboard {len(expected)}")
        for step, ((wanted,), (got,)) in enumerate(zip(struct.iter_unpack("<Q", expected), struct.iter_unpack("<Q", actual))):
            if got != wanted:
                differences[variant] += 1
                if first is None:
                    first = {"variant": variant, "step": step, "cycle": step // 2,
                             "clock": step % 2, "expected": wanted, "actual": got}
    report = {"top": TOP, "records": len(expected) // 8, "compared_bits_per_variant": len(expected) // 8 * 3,
              "differences": dict(differences), "first": first,
              "scoreboard": file_identity(work / "expected.bin"),
              "outputs": {variant: file_identity(path) for variant, path in paths.items()}}
    write_identity(work / ("comparison-noopt.json" if noopt else "comparison.json"), report)
    if differences:
        raise RuntimeError(f"AheadBtbReplacer mismatch: {json.dumps(first)}")
    reference = "Verilator -O0" if noopt else "Verilator"
    print(f"{TOP}: native FIRRTL off/prefer, Wolvrix SV and {reference} agree with PLRU scoreboard on {report['records']} records each", flush=True)


def diagnose(args):
    """Inspect completed output prefixes after an assertion terminates a model."""
    work = args.output
    expected = (work / "expected.bin").read_bytes()
    layout = json.loads((work / "layout.json").read_text())
    report = {"expected_records": len(expected) // 8, "variants": {}}
    paths = {variant: work / variant / "outputs.bin" for variant in VARIANTS}
    paths["verilator-noopt"] = work / "verilator/outputs-noopt.bin"
    for variant, path in paths.items():
        if not path.exists():
            continue
        actual = path.read_bytes()
        if len(actual) % 8 or len(actual) > len(expected):
            raise ValueError(f"invalid output prefix: {path}")
        first, differences = None, 0
        for step, ((wanted,), (got,)) in enumerate(zip(struct.iter_unpack("<Q", expected), struct.iter_unpack("<Q", actual))):
            if got != wanted:
                differences += 1
                if first is None:
                    first = {"step": step, "cycle": step // 2, "clock": step % 2,
                             "expected": wanted, "actual": got}
        item = {"completed_records": len(actual) // 8, "differences": differences, "first": first}
        if len(actual) < len(expected):
            next_step = len(actual) // 8
            count = words_in(layout["inputs"])
            with (work / "inputs.bin").open("rb") as stream:
                stream.seek(24 + next_step * count * 8)
                words = struct.unpack(f"<{count}Q", stream.read(count * 8))
            values = {row["name"]: words[row["offset"]] for row in layout["inputs"]}
            ops = json.loads((work / "operations.json").read_text()) if (work / "operations.json").exists() else operations()
            operation = next(op for cycle, op in enumerate(ops) if cycle == next_step // 2)
            item["next_input"] = {"step": next_step, "cycle": next_step // 2,
                                  "operation": operation, "inputs": values}
        report["variants"][variant] = item
    write_identity(work / "diagnosis.json", report)
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "drivers", "compare", "compare-noopt", "diagnose", "minimal", "reference-identity", "reference-result"))
    parser.add_argument("--firrtl", type=Path, default=ROOT / "ptmp/xs/rtl/rtl/SimTop.fir")
    parser.add_argument("--sv-dir", type=Path, default=ROOT / "ptmp/xs/rtl/rtl")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-dir", action="append", default=[], type=Path)
    parser.add_argument("--reference-language")
    parser.add_argument("--reference-vflags")
    args = parser.parse_args()
    args.firrtl, args.sv_dir, args.output = args.firrtl.resolve(), args.sv_dir.resolve(), args.output.resolve()
    {"generate": generate, "drivers": drivers, "compare": compare,
     "compare-noopt": lambda args: compare(args, noopt=True),
     "diagnose": diagnose, "minimal": minimal, "reference-identity": reference_identity,
     "reference-result": reference_result}[args.action](args)


if __name__ == "__main__":
    main()
