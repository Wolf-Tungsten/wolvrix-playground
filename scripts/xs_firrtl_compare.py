#!/usr/bin/env python3
"""Compare real XiangShan components through SV and native FIRRTL ingestion."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import datetime, timezone
from itertools import islice, product
import json
from pathlib import Path
import random
import re
import struct
import sys
from types import SimpleNamespace

import wolvrix

from grhsim_flow import FlowOptions, checked, emit_cpp, finish_simulation_graph, store_checkpoint
from grhsim_provenance import capture_generation, file_identity, generated_identity, write_identity
from wolvrix_xs_grhsim import GRH_PIPELINE, firrtl_grh_pipeline, timed
from xs_firrtl_inputs import create_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "testcase/xs-components/scripts"))
# Reuse only ABI parsers. The old ROB benchmark's exclusions and assertion
# stubs are deliberately outside this workflow.
from gen_rob_bench import (element_name, find_positions, norm_name,
                           parse_grhsim_header, parse_sv_ports, sv_port_leaves)

MEMORY = "sram_array_1p128x138m69s1h0l1b_icache_meta"
LAYERS = ["Verification.Assert", "Verification.Assume", "Verification.Cover"]

# Frozen firtool removed this unused module output, but retained its exact
# expression as the data input of this register. Expose that existing value;
# do not reconstruct the expression or alter any state/effect.
SV_OBSERVATIONS = {"Rob": [{
    "firrtl_port": "io__DOT__isVsetFlushPipe", "reg_symbol": "isVsetFlushPipeReg",
    "sv_port": "f10_observe_isVsetFlushPipe", "width": 1,
    "equivalence": "FIRRTL io.isVsetFlushPipe and isVsetFlushPipeReg nextValue both connect to isVsetFlushPipe = rawInfo[0].commit_w & deqHasFlushed & exceptionGen.io.state.bits.isVset; frozen SV register nextValue is _GEN_455.commit_w & deqHasFlushed & _exceptionGen_io_state.bits.isVset",
    "firrtl_statements": [
        "node _isVsetFlushPipe_T = and(rawInfo[0].commit_w, deqHasFlushed)",
        "node isVsetFlushPipe = and(_isVsetFlushPipe_T, exceptionGen.io.state.bits.isVset)",
        "connect isVsetFlushPipeReg, isVsetFlushPipe",
        "connect io.isVsetFlushPipe, isVsetFlushPipe"],
    "sv_statement": "isVsetFlushPipeReg <= _GEN_455.commit_w & deqHasFlushed & _exceptionGen_io_state.bits.isVset;",
}]}


def firrtl_abi_name(member):
    # Frozen SV preserves this field as attribute_0; source FIRRTL uses
    # attribute. Keep the SV/trace leaf names and the real native member access.
    return norm_name(member.replace("__DOT__attribute__DOT__", "__DOT__attribute_0__DOT__"))


def observation_source_evidence(firrtl, sv, top, specifications):
    expected = {statement: [] for spec in specifications for statement in spec["firrtl_statements"]}
    module = re.compile(rf"^  (?:public )?module {re.escape(top)} :")
    selected = False
    with firrtl.open() as stream:
        for number, line in enumerate(stream, 1):
            if not selected:
                selected = bool(module.match(line))
                continue
            if re.match(r"^  (?:public )?(?:ext)?module ", line):
                break
            statement = line.split(" @[", 1)[0].strip()
            if statement in expected and line.startswith("    " + statement):
                expected[statement].append({"line": number, "source": line.rstrip()})
    if any(len(matches) != 1 for matches in expected.values()):
        raise ValueError(f"FIRRTL observation source evidence changed: {expected}")
    registers = {spec["reg_symbol"]: spec for spec in specifications}
    assignments = {symbol: [] for symbol in registers}
    with sv.open() as stream:
        lines = iter(enumerate(stream, 1))
        for number, line in lines:
            symbol = next((name for name in registers if re.search(rf"\b{re.escape(name)}\s*<=", line)), None)
            if symbol is None:
                continue
            snippet = line
            for _ in range(8):
                if ";" in snippet:
                    break
                snippet += next(lines)[1]
            if "".join(snippet.split()) != "".join(registers[symbol]["sv_statement"].split()):
                raise ValueError(f"SV observation source expression changed: {snippet}")
            assignments[symbol].append({"line": number, "source": snippet.rstrip()})
    if any(len(matches) != 1 for matches in assignments.values()):
        raise ValueError(f"SV observation requires one matching assignment: {assignments}")
    return {"firrtl": expected, "sv": assignments}


def observe_register_data_checkpoint(source, destination, specifications):
    """Add output views of existing scalar register nextValue operands only.

    kRegisterWritePort operands are [updateCond, nextValue, events...]. The
    checkpoint is streamed so the large ROB graph need not be duplicated in
    Python. Every operation, state declaration and existing port stays intact.
    """
    if source.resolve() == destination.resolve():
        raise ValueError("observation checkpoint must preserve its source")
    matches = {spec["reg_symbol"]: [] for spec in specifications}
    with source.open() as stream:
        for line in stream:
            if '"kind": "kRegisterWritePort"' not in line:
                continue
            op = json.loads(line.strip().removesuffix(","))
            symbol = op.get("attrs", {}).get("regSymbol", {}).get("v")
            if symbol in matches:
                matches[symbol].append(op)
    observations = []
    for spec in specifications:
        writes = matches[spec["reg_symbol"]]
        if len(writes) != 1:
            raise ValueError(f"observation requires one register write: {spec['reg_symbol']}: {len(writes)}")
        write = writes[0]
        if len(write["in"]) != 3 or write["attrs"].get("eventEdge", {}).get("vs") != ["posedge"]:
            raise ValueError(f"observation requires a single posedge write: {write}")
        observations.append({**spec, "write_operation": write,
                             "source_value": write["in"][1], "operand_index": 1})
    selected = {item["source_value"]: item for item in observations}
    if len(selected) != len(observations):
        raise ValueError("observation values must be distinct")
    changed, output_lists, in_ports = set(), 0, False
    try:
        with source.open() as stream, destination.open("w") as output:
            for line in stream:
                if line.startswith('      "ports": {'):
                    in_ports = True
                if in_ports and line.startswith('        "out": ['):
                    if line.strip() != '"out": [':
                        raise ValueError("observation requires a nonempty output port list")
                    output_lists += 1
                    output.write(line)
                    for item in observations:
                        output.write("          " + json.dumps({"name": item["sv_port"],
                            "val": item["source_value"]}) + ",\n")
                    continue
                if line.startswith('        {"sym":') and '"kind":' not in line:
                    symbol = line.split('"', 4)[3]
                    if symbol in selected:
                        value = json.loads(line.strip().removesuffix(","))
                        item = selected[symbol]
                        if (value["w"] != item["width"] or value.get("shape") or
                                value["in"] or value["out"] or value.get("inout")):
                            raise ValueError(f"incompatible observation value: {value}")
                        item["source_geometry"] = dict(value)
                        value["out"] = True
                        output.write("        " + json.dumps(value) + ("," if line.rstrip().endswith(",") else "") + "\n")
                        changed.add(symbol)
                        continue
                output.write(line)
        if changed != set(selected) or output_lists != 1:
            raise ValueError(f"incomplete observation adapter: values={changed}, output_lists={output_lists}")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"source_checkpoint": file_identity(source), "adapted_checkpoint": file_identity(destination),
            "observations": observations,
            "mutation": "existing nextValue value out flag plus output port entry only; all operations and existing ports preserved"}


def observe_sv(args, top):
    work = args.output / top
    specifications = SV_OBSERVATIONS.get(top, [])
    if not specifications:
        raise ValueError(f"no audited SV observation specification for {top}")
    source = work / "sv-base.json"
    adapted = work / "sv-observed-base.json"
    evidence = observation_source_evidence(args.firrtl, args.sv_dir / f"{top}.sv", top, specifications)
    report = observe_register_data_checkpoint(source, adapted, specifications)
    report["source_evidence"] = evidence
    report["firrtl"] = file_identity(args.firrtl)
    report["sv"] = file_identity(args.sv_dir / f"{top}.sv")
    write_identity(work / "sv-observation.json", report)
    identity = capture_generation("xs-firrtl-sv-observation", inputs={
        "source_checkpoint": source, "adapted_checkpoint": adapted,
        "observation": work / "sv-observation.json"},
        configuration={"top": top, "observation": report})
    with wolvrix.Session() as session:
        session.log_level = "info"
        checked(timed(f"{top} load SV observation", lambda: session.read_json_file(str(adapted))), "load SV observation")
        checked(session.run_pass("grh.verify", design="design.main"), "verify SV observation")
        options = FlowOptions(firrtl_nodes="off")
        finish_simulation_graph(session, design="design.main", top=top, options=options)
        variant = work / "sv-observed"
        variant.mkdir(exist_ok=True)
        store_checkpoint(session, variant / "final.json", design="design.main", top=top)
        emit_cpp(session, design="design.main", top=top, output=variant / "model", overwrite=True,
                 generation_identity={**identity, "flow": "xs-firrtl-sv-observation", "observation": report,
                                      "flow_options": asdict(options)})


def audit_sv_observation(args, top):
    """Record a later provenance audit without rewriting generation evidence."""
    if args.installation_log is None or args.observation_generation_log is None:
        raise ValueError("observation audit requires installation and generation logs")
    work = args.output / top
    model = work / "sv-observed/model"
    original = json.loads((model / "generation-identity.json").read_text())
    observation = json.loads((work / "sv-observation.json").read_text())
    for key, path in (("source_checkpoint", work / "sv-base.json"),
                      ("adapted_checkpoint", work / "sv-observed-base.json")):
        if file_identity(path) != observation[key]:
            raise ValueError(f"observation audit checkpoint differs: {path}")
    actual = generated_identity(model)
    if actual != original["generated"]:
        raise ValueError("observation audit generated sources differ from original identity")
    report = capture_generation("xs-firrtl-sv-observation-post-generation-audit", inputs={
        "source_checkpoint": work / "sv-base.json", "adapted_checkpoint": work / "sv-observed-base.json",
        "observation": work / "sv-observation.json", "final_checkpoint": work / "sv-observed/final.json",
        "generation_identity": model / "generation-identity.json",
        "original_sv_generation_identity": work / "sv-off/model/generation-identity.json",
        "model_archive": model / f"libgrhsim_{top}.a", "installation_log": args.installation_log,
        "observation_generation_log": args.observation_generation_log}, configuration={"top": top})
    report.update({"audit_time_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "post-generation metadata audit; original generation-identity.json preserved",
        "model_source_identity": actual,
        "limitation": "Loaded library and source hashes were captured at audit time. Original observation generation did not capture them; installation/generation logs and the session chronology support install14 attribution but do not retroactively prove the process mappings at generation time. SV base and native models retain their original install13 generation identities."})
    write_identity(work / "sv-observed/provenance-audit.json", report)


def audit_retained_inputs(args, top, ports, extras):
    """Require source context evidence for every live input absent from SV."""
    expected, data_targets, rows = {}, {}, []

    def require(module, statement):
        expected.setdefault(module, {}).setdefault(statement, [])

    def track_data(module, path):
        data_targets.setdefault(module, set()).add(path)

    for extra in extras:
        port = ports[extra["name"]]
        users = len(port.get("users", []))
        row = {**extra, "source_user_count": users, "initialized_value": 0}
        if not users:
            row["policy"] = "unused in ordinary optimized native graph"
        else:
            match = re.fullmatch(r"io__DOT__exuWriteback__DOT__(\d+)__DOT__bits__DOT__data", extra["name"])
            if top != "Rob" or not match or extra["width"] != 64 or extra["shape"] or extra["matched"]:
                raise ValueError(f"live unmatched FIRRTL input requires source context proof: {extra}")
            lane = match[1]
            field = f"`{lane}`"
            require("WbDataPath", f"connect io.toCtrlBlock.writeback.{field}.bits.data, UInt<64>(0h0)")
            require("Region", "inst intWBDataPath of WbDataPath")
            require("Region", f"connect io.wbDataPathToCtrlBlock.writeback.{field}, intWBDataPath.io.toCtrlBlock.writeback.{field}")
            require("BackendInlined", "inst intRegion of Region")
            require("BackendInlined", "inst ctrlBlock of CtrlBlock")
            require("BackendInlined", f"connect ctrlBlock.io.fromWB.wbData.{field}.bits.data, intRegion.io.wbDataPathToCtrlBlock.writeback.{field}.bits.data")
            require("CtrlBlock", f"connect delayedNotFlushedWriteBack_delayed_bits_r_{lane}, io.fromWB.wbData.{field}.bits")
            require("CtrlBlock", f"connect delayedNotFlushedWriteBack_{lane}.bits, delayedNotFlushedWriteBack_delayed_bits_r_{lane}")
            require("CtrlBlock", f"connect delayedWriteBack.{field}.bits.data, delayedNotFlushedWriteBack_{lane}.bits.data")
            require("CtrlBlock", f"connect rob.io.exuWriteback.{field}.bits.data, delayedWriteBack.{field}.bits.data")
            track_data("WbDataPath", f"io.toCtrlBlock.writeback.{field}.bits.data")
            track_data("Region", f"io.wbDataPathToCtrlBlock.writeback.{field}.bits.data")
            track_data("BackendInlined", f"ctrlBlock.io.fromWB.wbData.{field}.bits.data")
            for path in (f"delayedNotFlushedWriteBack_delayed_bits_r_{lane}.data",
                         f"delayedNotFlushedWriteBack_{lane}.bits.data",
                         f"delayedWriteBack.{field}.bits.data", f"rob.io.exuWriteback.{field}.bits.data"):
                track_data("CtrlBlock", path)
            row.update(policy="whole-design source context constant", source_constant="UInt<64>(0h0)", lane=int(lane))
        rows.append(row)
    if expected:
        module = None
        with args.firrtl.open() as source:
            for number, line in enumerate(source, 1):
                match = re.match(r"^  (?:public )?(?:ext)?module (\S+) :", line)
                if match:
                    module = match[1]
                if module not in expected:
                    continue
                statement = line.split(" @[", 1)[0].strip()
                if statement.startswith("connect "):
                    destination = statement.removeprefix("connect ").split(",", 1)[0]
                    if any(target == destination or target.startswith(destination + ".")
                           or destination.startswith(target + ".") for target in data_targets[module]):
                        if statement not in expected[module]:
                            raise ValueError(f"retained input data path has another assignment: {module}:{number}: {statement}")
                if statement in expected[module]:
                    expected[module][statement].append({"line": number, "source": line.rstrip()})
        missing = {f"{module}: {statement}": len(matches)
                   for module, statements in expected.items() for statement, matches in statements.items()
                   if len(matches) != 1}
        if missing:
            raise ValueError(f"retained input source context proof changed: {missing}")
    return {"firrtl": file_identity(args.firrtl), "inputs": rows,
            "source_evidence": expected,
            "initialization": "source unknown converted by shared logic_domain=2state to zero; clocked delays retain the upstream zero data",
            "unused_inputs": sum(row["source_user_count"] == 0 for row in rows),
            "context_constant_inputs": sum(row["source_user_count"] != 0 for row in rows)}


def retained_input_audit(args, top):
    work = args.output / top
    mapping = json.loads((work / "bindings.json").read_text())
    ports = port_values(work / "firrtl-base.json")
    report = audit_retained_inputs(args, top, ports, mapping["firrtl-off"]["retained_extra_inputs"])
    report["source_checkpoint"] = file_identity(work / "firrtl-base.json")
    write_identity(work / "retained-input-audit.json", report)


def rob_trace_activity(args):
    """Inspect the captured trace before paying for the real component build."""
    layout = json.loads(args.rob_layout.read_text())
    groups = {
        "enqueue": [1 + row["offset"] for row in layout["inputs"]
                    if re.fullmatch(r"io_enq_req_\d+_valid", row["name"])],
        "writeback": [1 + row["offset"] for row in layout["inputs"]
                      if re.fullmatch(r"io_writeback_\d+_valid", row["name"])],
        "commit": [1 + layout["in_words"] + row["offset"] for row in layout["outputs"]
                   if re.fullmatch(r"io_commits_commitValid_\d+", row["name"])],
    }
    counts, first = Counter(), {}
    with args.rob_trace.open("rb") as trace:
        magic, records, ins, outs = struct.unpack("<8sQII", trace.read(24))
        if magic != b"RobTrc01" or args.cycles > records or (ins, outs) != (
                layout["in_words"], layout["out_words"]):
            raise ValueError("invalid or insufficient original ROB trace")
        record = struct.Struct(f"<{1 + ins + outs}Q")
        for cycle in range(args.cycles):
            values = record.unpack(trace.read(record.size))
            for name, indices in groups.items():
                active = sum(bool(values[i]) for i in indices)
                counts[name] += active
                if active and name not in first:
                    first[name] = cycle
    result = {"cycles": args.cycles, "valid_lanes": dict(counts), "first_cycle": first}
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def sv_closure(directory, top):
    pending, paths = [top], {}
    instances = re.compile(r"^  ([A-Za-z_][\w$]*)\s+[A-Za-z_][\w$]*\s*\(", re.MULTILINE)
    while pending:
        name = pending.pop()
        if name in paths:
            continue
        path = directory / f"{name}.sv"
        text = path.read_text()
        if not re.search(rf"^module\s+{re.escape(name)}\s*\(", text, re.MULTILINE):
            raise ValueError(f"not a split module source: {path}")
        paths[name] = path
        pending.extend(instances.findall(text))
    return [paths[name] for name in sorted(paths)]


def port_values(path):
    """Read the top's port geometry without loading the full graph into Python."""
    values, ports = {}, []
    in_ports, direction = False, None
    with path.open() as stream:
        for line in stream:
            if line.startswith('        {"sym":') and any(
                    f'"{flag}": true' in line for flag in ("in", "out", "inout")):
                value = json.loads(line.strip().removesuffix(","))
                values[value["sym"]] = value
            if line.startswith('      "ports": {'):
                in_ports = True
            elif in_ports and line.startswith('      },'):
                in_ports = False
            elif in_ports and re.match(r'^        "(?:in|out|inout)":', line):
                direction = line.split('"')[1]
            elif in_ports and line.startswith('          {"name":'):
                ports.append({**json.loads(line.strip().removesuffix(",")), "direction": direction})
    if not ports:
        raise ValueError(f"no top port values: {path}")
    # A simplified constant can drive several named output ports. The public
    # ABI is the port list, not the surviving value's single symbol.
    return {port["name"]: {**values[port["val"]], "sym": port["name"],
                           "value_symbol": port["val"],
                           **{flag: flag == port["direction"] for flag in ("in", "out", "inout")}}
            for port in ports}


def generate(args, top):
    work = args.output / top
    work.mkdir(parents=True, exist_ok=True)
    if top == "Rob":
        activity = rob_trace_activity(args)
        write_identity(work / "trace-activity.json", activity)
        if not all(activity["valid_lanes"].get(name) for name in ("enqueue", "writeback", "commit")):
            raise ValueError("ROB trace prefix must exercise enqueue, writeback and commit")
    sv = sv_closure(args.sv_dir, top)
    sv.insert(0, ROOT / "testcase/xiangshan/difftest/src/test/vsrc/common/assert.v")
    mixed = create_manifest(args.firrtl, top=top, enabled_layers=LAYERS,
        include_dirs=args.include_dir, resource_roots=args.include_dir, defines=["DIFFTEST"])
    (work / "sources.json").write_text(json.dumps(mixed, indent=2) + "\n")
    options = FlowOptions(firrtl_nodes="off")
    identity = capture_generation("xs-firrtl-component-compare", inputs={
        "firrtl": args.firrtl, **{f"sv_{i}": path for i, path in enumerate(sv)}},
        configuration={"top": top, "mixed": mixed, "flow": asdict(options)})
    write_identity(work / "identity.json", identity)
    for language in ("firrtl", "sv"):
        with wolvrix.Session() as session:
            session.log_level = "info"
            if language == "firrtl":
                request = {key: value for key, value in mixed.items() if key != "schema"}
                checked(timed(f"{top} FIRRTL", lambda: session.read_sources(**request)), "read FIRRTL")
                identity["ingest_dependencies"] = session.graph_metadata(design="design.main", top=top)["metadata"].get("ingest.dependencies", [])
            else:
                slang_args = [str(path) for path in sv] + ["--top", top, "-D", "DIFFTEST"]
                slang_args += [arg for directory in args.include_dir for arg in ("-I", str(directory))]
                checked(timed(f"{top} SV", lambda: session.read_sv(None, slang_args=slang_args)), "read SV")
            pipeline = firrtl_grh_pipeline(GRH_PIPELINE) if language == "firrtl" else GRH_PIPELINE
            for name, opts in pipeline:
                if name == "simplify" and args.dump_pre_simplify:
                    store_checkpoint(session, work / f"{language}-pre-simplify.json",
                                     design="design.main", top=top)
                checked(timed(f"{top}/{language} {name}", lambda name=name, opts=opts:
                    session.run_pass(name, design="design.main", **opts)), name)
            base = work / f"{language}-base.json"
            store_checkpoint(session, base, design="design.main", top=top)
            (work / f"{language}-ports.json").write_text(json.dumps(port_values(base), indent=2) + "\n")
            finish_simulation_graph(session, design="design.main", top=top, options=options,
                                    stop_after="nonsink-sink-split")
            common = work / f"{language}-common.json"
            store_checkpoint(session, common, design="design.main", top=top)
            common_identity = file_identity(common)
            for mode in (("off", "prefer") if language == "firrtl" else ("off",)):
                design = "design." + mode
                checked(session.clone_design(design="design.main", out_design=design), "clone common optimized graph")
                variant = work / f"{language}-{mode}"
                variant.mkdir(exist_ok=True)
                branch_options = replace(options, firrtl_nodes=mode,
                    nonsink_report=str(variant / "nonsink.txt"))
                finish_simulation_graph(session, design=design, top=top, options=branch_options)
                store_checkpoint(session, variant / "final.json", design=design, top=top)
                emit_cpp(session, design=design, top=top, output=variant / "model", overwrite=True,
                    generation_identity={**identity, "language": language, "mode": mode,
                                         "optimized_checkpoint": common_identity})
                session.delete(design)
    write_identity(work / "identity.json", identity)
    if top in SV_OBSERVATIONS:
        observe_sv(args, top)
    drivers(args, top)


def canonical_leaves(args, top, fir_ports):
    path = args.sv_dir / f"{top}.sv"
    ports = parse_sv_ports(path, top)
    leaves = {}
    fir_by_name = {firrtl_abi_name(name): value for name, value in fir_ports.items()}
    for name, values in sv_port_leaves(path, top).items():
        for leaf in values:
            geometry = fir_by_name.get(norm_name(leaf.member_name))
            shape = geometry.get("shape", []) if geometry else []
            rows = 1
            for extent in shape:
                rows *= extent
            bool_vector = (geometry and shape and geometry["w"] == rows and
                           len(shape) == len(leaf.row_indices) + 1 and shape[-1] == leaf.width)
            if bool_vector:
                for i in range(leaf.width):
                    item = replace(leaf, name_parts=leaf.name_parts + (str(i),),
                        width=1, offset=leaf.offset + i,
                        member_bit_offset=i, member_row_indices=leaf.row_indices)
                    leaves[item.logical_name] = (ports[name].direction, item)
            else:
                leaves[leaf.logical_name] = (ports[name].direction, leaf)
    observation_path = args.output / top / "sv-observation.json"
    if observation_path.exists():
        report = json.loads(observation_path.read_text())
        for item in report["observations"]:
            name = firrtl_abi_name(item["firrtl_port"])
            if name in leaves:
                raise ValueError(f"SV observation collides with an existing port: {name}")
            leaves[name] = ("output", SimpleNamespace(width=item["width"], member_name=item["sv_port"],
                row_indices=(), member_row_indices=None, member_bit_offset=0, sv_internal=True))
    # firtool resolves passive probes through hierarchical references and can
    # remove their module ports. Keep these views in the native off/prefer
    # comparison; source verification effects remain enabled in both routes.
    module = re.compile(rf"^  (?:public )?module {re.escape(top)} :")
    probes, selected = set(), False
    with args.firrtl.open() as stream:
        for line in stream:
            if not selected:
                selected = bool(module.match(line))
                continue
            if not line.strip():
                break
            match = re.match(r"^    output (\w+) : (?:RW)?Probe<", line)
            if match:
                probes.add(match[1])
    for member, value in fir_ports.items():
        if member.split("__DOT__")[0] not in probes or norm_name(member) in leaves:
            continue
        shape = value.get("shape", ())
        indices = list(product(*(range(d) for d in shape))) if shape else [()]
        for idx in indices:
            name = "_".join([norm_name(member), *map(str, idx)])
            if name not in leaves:
                leaves[name] = ("probe", SimpleNamespace(width=value["w"] // len(indices)))
    return leaves


def bindings(ports, header, top, leaves, language):
    members = parse_grhsim_header(header.read_text(), top)
    result, extra = {}, []
    if language == "sv":
        for name, (direction, leaf) in leaves.items():
            if direction == "probe":
                continue
            indices = leaf.row_indices if leaf.member_row_indices is None else leaf.member_row_indices
            member = leaf.member_name
            if member not in members and member not in ("clock", "reset"):
                raise ValueError(f"SV model lacks port member {member}")
            access = member + "".join(f"[{i}]" for i in indices)
            result[name] = (access, leaf.member_bit_offset or 0, leaf.width, direction)
        return result, extra
    for member, value in ports.items():
        shape = tuple(value.get("shape", ()))
        indices = list(product(*(range(d) for d in shape))) if shape else [()]
        comps = firrtl_abi_name(member).split("_")
        positions, count = find_positions(comps, shape, indices, set(leaves))
        if not shape:
            positions, count = (), int(firrtl_abi_name(member) in leaves)
        if count != len(indices):
            extra.append({"name": member, "direction": "input" if value["in"] else "output",
                          "width": value["w"], "shape": shape, "matched": count})
        for idx in indices:
            name = element_name(comps, positions, idx) if positions is not None else firrtl_abi_name(member)
            if name not in leaves:
                continue
            width = value["w"] // len(indices)
            direction, leaf = leaves[name]
            if width != leaf.width or value["in"] != (direction == "input"):
                raise ValueError(f"incompatible port {name}: FIRRTL {width}, SV {leaf.width}")
            if name in result:
                raise ValueError(f"ambiguous FIRRTL port binding: {name}")
            if member not in members and member not in ("clock", "reset"):
                raise ValueError(f"model lacks port member {member}")
            result[name] = (member + "".join(f"[{i}]" for i in idx), 0, width, direction)
    unmatched_outputs = [port for port in extra if port["direction"] == "output"]
    if unmatched_outputs:
        raise ValueError(f"unmatched FIRRTL outputs: {json.dumps(unmatched_outputs, sort_keys=True)}")
    missing = set(leaves) - set(result)
    if missing:
        raise ValueError(f"unbound SV ports: {sorted(missing)}")
    return result, extra


def drivers(args, top):
    work = args.output / top
    for language in ("firrtl", "sv"):
        (work / f"{language}-ports.json").write_text(json.dumps(
            port_values(work / f"{language}-base.json"), indent=2) + "\n")
    fir_ports = json.loads((work / "firrtl-ports.json").read_text())
    leaves = canonical_leaves(args, top, fir_ports)
    mapping = {}
    for language, mode in (("sv", "off"), ("firrtl", "off"), ("firrtl", "prefer")):
        variant = work / ("sv-observed" if language == "sv" and (work / "sv-observation.json").exists()
                          else f"{language}-{mode}")
        ports = json.loads((work / f"{language}-ports.json").read_text())
        paired, extra = bindings(ports, variant / f"model/grhsim_{top}.hpp", top, leaves, language)
        mapping[f"{language}-{mode}"] = {"bindings": paired, "retained_extra_inputs": extra,
                                        "model_directory": str(variant / "model")}
    retained_report = audit_retained_inputs(args, top, fir_ports, mapping["firrtl-off"]["retained_extra_inputs"])
    retained_report["source_checkpoint"] = file_identity(work / "firrtl-base.json")
    write_identity(work / "retained-input-audit.json", retained_report)
    (work / "bindings.json").write_text(json.dumps(mapping, indent=2) + "\n")
    inputs = [(name, leaf.width) for name, (direction, leaf) in sorted(leaves.items()) if direction == "input"]
    outputs = [(name, leaf.width) for name, (direction, leaf) in sorted(leaves.items()) if direction in ("output", "probe")]
    layout = {"inputs": word_layout(inputs), "outputs": word_layout(outputs)}
    for leaf in layout["outputs"]:
        leaf["native_probe"] = leaves[leaf["name"]][0] == "probe"
        leaf["sv_internal"] = bool(getattr(leaves[leaf["name"]][1], "sv_internal", False))
    (work / "layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    stimulus(args, top, layout)
    for variant, info in mapping.items():
        directory = work / variant
        model = Path(info["model_directory"])
        (directory / "driver.cpp").write_text(driver(top, info["bindings"], layout,
            header=str(model / f"grhsim_{top}.hpp")))
        (directory / "run.mk").write_text(f"""ifeq ($(origin CXX),default)
CXX := clang++
endif
CXXFLAGS ?= -std=c++20 -O1 -fno-strict-aliasing
{model}/libgrhsim_{top}.a: {model}/Makefile
	$(MAKE) -C {model} CXX='$(CXX)' CXXFLAGS='$(CXXFLAGS)'
driver: driver.cpp {model}/libgrhsim_{top}.a
	$(CXX) $(CXXFLAGS) driver.cpp {model}/libgrhsim_{top}.a -lz -o $@
outputs.bin: driver ../inputs.bin
	./driver ../inputs.bin outputs.bin
.PHONY: run
run: outputs.bin
""")
    (work / "run.mk").write_text(".PHONY: run " + " ".join(mapping) + "\n" +
        "run: " + " ".join(mapping) + "\n" +
        f"\t$(PYTHON) {ROOT}/scripts/xs_firrtl_compare.py compare --firrtl {args.firrtl} --sv-dir {args.sv_dir} --output {args.output} --top {top}\n" +
        " ".join(mapping) + ":\n\t$(MAKE) -C $@ -f run.mk run\n")


def word_layout(leaves):
    result, offset = [], 0
    for name, width in leaves:
        words = (width + 63) // 64
        result.append({"name": name, "width": width, "words": words, "offset": offset})
        offset += words
    return result


def words_in(leaves):
    return sum(leaf["words"] for leaf in leaves)


def packed_words(leaves, values):
    return [((values.get(leaf["name"], 0) & ((1 << leaf["width"]) - 1)) >> (64 * i)) & ((1 << 64) - 1)
            for leaf in leaves for i in range(leaf["words"])]


def stimulus(args, top, layout):
    work = args.output / top
    ins, outs = layout["inputs"], layout["outputs"]
    in_words, out_words = words_in(ins), words_in(outs)
    input_record = struct.Struct(f"<{in_words}Q")
    output_record = struct.Struct(f"<{out_words}Q")
    randomizer = random.Random(0xF10)
    coverage = Counter()
    memory = [None] * 128
    read_result = 0
    cycles = args.cycles if top != MEMORY else max(512, args.cycles)
    trace = None
    static_inputs = []
    static_evidence = {}
    if top == "Rob":
        trace = args.rob_trace.open("rb")
        magic, count, ti, to = struct.unpack("<8sQII", trace.read(24))
        if magic != b"RobTrc01" or cycles > count:
            raise ValueError("invalid or insufficient original ROB trace")
        trace_layout = json.loads(args.rob_layout.read_text())
        if (ti, to) != (trace_layout["in_words"], trace_layout["out_words"]):
            raise ValueError("ROB trace/layout geometry differs")
        trace_fields = {row["name"]: row for row in trace_layout["inputs"]}
        missing = {leaf["name"] for leaf in ins} - set(trace_fields) - {"clock", "reset"}
        if missing:
            raise ValueError(f"original trace lacks input leaves: {sorted(missing)}")
        for leaf in ins:
            row = trace_fields.get(leaf["name"])
            if row is None:
                continue
            if row["width"] != leaf["width"]:
                raise ValueError(f"trace input width differs: {leaf['name']}")
            if row["offset"] is None:
                if row.get("kind") != "static":
                    raise ValueError(f"trace input has no offset or static contract: {row}")
                # RobTrc01 omits static-zero fields. The FST packer validates
                # that each corresponding captured slice remains zero.
                static_inputs.append({"name": leaf["name"], "width": leaf["width"], "value": 0})
        if static_inputs:
            mapping = json.loads(args.rob_capture_mapping.read_text())
            captured = {row["name"]: row for row in mapping["mapped"]}
            summary = json.loads(args.rob_capture_summary.read_text())
            if ((summary["cycles"], summary["in_words"], summary["out_words"], summary["bytes"]) !=
                    (count, ti, to, args.rob_trace.stat().st_size) or not summary["first_reset"]):
                raise ValueError("static input capture summary does not describe this trace")
            for item in static_inputs:
                witness = captured.get(item["name"])
                if (not witness or not isinstance(witness.get("handle"), int) or
                        witness["bit"] + item["width"] > witness["source_width"]):
                    raise ValueError(f"static input lacks capture geometry: {item}")
                item["capture"] = witness
            static_evidence = {"capture_mapping": file_identity(args.rob_capture_mapping),
                               "capture_summary": file_identity(args.rob_capture_summary)}
        trace_record = struct.Struct(f"<{1 + ti + to}Q")
    clock = "RW0_clk" if top == MEMORY else "clock"
    previous_read = False
    with ExitStack() as files:
        source = files.enter_context((work / "inputs.bin").open("wb"))
        masks = files.enter_context((work / "compare-mask.bin").open("wb"))
        expected = files.enter_context((work / "expected.bin").open("wb")) if top == MEMORY else None
        source.write(struct.pack("<8sQII", b"FirXio01", cycles * 2, in_words, out_words))
        for cycle in range(cycles):
            values = {leaf["name"]: 0 for leaf in ins}
            if "reset" in values:
                values["reset"] = int(cycle < 4)
            if trace:
                record = trace_record.unpack(trace.read(trace_record.size))
                values["reset"] = record[0] & 1
                for leaf in ins:
                    row = trace_fields.get(leaf["name"])
                    if row and row["offset"] is not None:
                        values[leaf["name"]] = sum(record[1 + row["offset"] + i] << (64 * i) for i in range(row["words"]))
            elif top == MEMORY:
                values.update(RW0_addr=cycle if cycle < 128 else randomizer.randrange(128),
                    RW0_en=1 if cycle < 128 else int(cycle % 11 != 0),
                    RW0_wmode=1 if cycle < 128 else int(cycle % 3 == 0),
                    RW0_wmask=3 if cycle < 128 else randomizer.randrange(4),
                    RW0_wdata=randomizer.getrandbits(138))
            else:
                for leaf in ins:
                    name = leaf["name"]
                    if any(group in name for group in ("readPorts", "specWritePorts", "archWritePorts", "diffWritePorts")):
                        values[name] = randomizer.getrandbits(leaf["width"])
                        if name.endswith("_wen") and "diffWritePorts" in name:
                            values[name] &= int(randomizer.randrange(32) == 0)
                        if cycle < 4 and (name.endswith("_wen") or name.endswith("_hold")):
                            values[name] = 0
                # Exercise one populated snapshot, a later rollback and ordinary
                # redirects without over/underflowing the snapshot queue.
                values["io_snpt_snptEnq"] = int(cycle == 192)
                values["io_redirect"] = int(cycle in (96, 240, 384))
                values["io_snpt_useSnpt"] = int(cycle == 240)
            coverage["reset_cycles"] += bool(values.get("reset"))
            for name, value in values.items():
                if value and name not in (clock, "reset"):
                    coverage["nonzero_input_cycles"] += 1
                    break
            if top == "Rob":
                coverage["enqueue_valid_lanes"] += sum(bool(value) for name, value in values.items()
                    if re.fullmatch(r"io_enq_req_\d+_valid", name))
                coverage["writeback_valid_lanes"] += sum(bool(value) for name, value in values.items()
                    if re.fullmatch(r"io_writeback_\d+_valid", name))
            if top == MEMORY:
                enabled = bool(values["RW0_en"])
                writing = enabled and bool(values["RW0_wmode"])
                coverage["disabled_cycles"] += not enabled
                coverage["read_cycles"] += enabled and not writing
                coverage[f"write_mask_{values['RW0_wmask']}"] += writing
            for edge in (0, 1):
                values[clock] = edge
                source.write(input_record.pack(*packed_words(ins, values)))
                observable = cycle >= 8
                if top == MEMORY:
                    observable = (bool(values["RW0_en"] and not values["RW0_wmode"]) if edge else previous_read)
                    if edge:
                        address = values["RW0_addr"]
                        if values["RW0_en"] and values["RW0_wmode"]:
                            old = memory[address]
                            if old is None:
                                if values["RW0_wmask"] != 3:
                                    raise ValueError("SRAM scoreboard requires full initialization before masked writes")
                                old = 0
                            for lane in range(2):
                                if values["RW0_wmask"] & (1 << lane):
                                    bits = ((1 << 69) - 1) << (lane * 69)
                                    old = (old & ~bits) | (values["RW0_wdata"] & bits)
                            memory[address] = old
                        elif observable:
                            read_result = memory[address]
                            if read_result is None:
                                raise ValueError("SRAM scoreboard read precedes initialization")
                    expected.write(output_record.pack(*packed_words(outs, {"RW0_rdata": read_result})))
                mask = {leaf["name"]: (1 << leaf["width"]) - 1 if observable else 0 for leaf in outs}
                masks.write(output_record.pack(*packed_words(outs, mask)))
            if top == MEMORY:
                previous_read = bool(values["RW0_en"] and not values["RW0_wmode"])
    if trace:
        trace.close()
    if top == "Rob" and not (coverage["enqueue_valid_lanes"] and coverage["writeback_valid_lanes"]):
        raise ValueError("ROB trace prefix must exercise enqueue and writeback")
    write_identity(work / "stimulus-identity.json", {"cycles": cycles, "seed": "0xF10",
        "inputs": file_identity(work / "inputs.bin"), "compare_mask": file_identity(work / "compare-mask.bin"),
        "initialization": "source unknown; shared 2state conversion; reset prefix for logic; full initial write for SRAM",
        "observations": "all SV output leaves and audited existing-expression observations after 8 reset/warmup cycles; SRAM only defined read results; both clock levels; additional source-typed passive Probe views compared between native off/prefer",
        "assertions": "FIRRTL Verification.Assert/Assume/Cover enabled; SV assertion DPI terminates on any invocation",
        "coverage": dict(coverage),
        **({"scoreboard": file_identity(work / "expected.bin")} if top == MEMORY else {}),
        **({"trace": file_identity(args.rob_trace), "trace_layout": file_identity(args.rob_layout),
            "trace_static_inputs": static_inputs,
            "trace_static_evidence": static_evidence,
            "trace_static_contract": "RobTrc01 static rows are zero; pack_rob_fst.cpp rejects nonzero captured static slices",
            "trace_packer": file_identity(ROOT / "testcase/xs-components/scripts/pack_rob_fst.cpp")}
           if top == "Rob" else {})})


def driver(top, paired, layout, header=None):
    drive, sample = [], []
    for leaf in layout["inputs"]:
        access, shift, width, _direction = paired[leaf["name"]]
        drive.append(f"put(m.{access}, {shift}, {width}, inputs.data()+{leaf['offset']});")
    for leaf in layout["outputs"]:
        if leaf["name"] not in paired and leaf.get("native_probe"):
            continue
        access, shift, width, _direction = paired[leaf["name"]]
        sample.append(f"get(m.{access}, {shift}, {width}, outputs.data()+{leaf['offset']});")
    roots = sorted({access.split("[")[0] for access, _shift, _width, direction in paired.values() if direction == "input"})
    return f'''#include "{header or f'model/grhsim_{top}.hpp'}"
#include <fstream>
#include <memory>
extern "C" void xs_assert(long long line){{std::fprintf(stderr,"SV assertion line=%lld\\n",line);std::exit(1);}}
extern "C" void xs_assert_v2(const char* file,long long line){{std::fprintf(stderr,"SV assertion %s:%lld\\n",file,line);std::exit(1);}}
template<class T> void put(T& value,unsigned shift,unsigned width,const std::uint64_t* input){{
    for(unsigned w=0;w<(width+63)/64;++w){{
        unsigned bits=std::min(64u,width-64*w);
        std::uint64_t word=input[w] & (bits==64?~std::uint64_t(0):((std::uint64_t(1)<<bits)-1));
        value=static_cast<T>(value | (static_cast<T>(word)<<(shift+64*w)));
    }}
}}
template<class T> void get(T value,unsigned shift,unsigned width,std::uint64_t* output){{
    for(unsigned w=0;w<(width+63)/64;++w){{
        unsigned bits=std::min(64u,width-64*w);
        output[w]=static_cast<std::uint64_t>(value>>(shift+64*w)) & (bits==64?~std::uint64_t(0):((std::uint64_t(1)<<bits)-1));
    }}
}}
int main(int argc,char** argv){{
    if(argc!=3)return 2;
    std::ifstream input(argv[1],std::ios::binary);
    std::ofstream output(argv[2],std::ios::binary);
    char magic[8];std::uint64_t count;std::uint32_t ni,no;
    input.read(magic,8);input.read(reinterpret_cast<char*>(&count),8);
    input.read(reinterpret_cast<char*>(&ni),4);input.read(reinterpret_cast<char*>(&no),4);
    if(!input||std::memcmp(magic,"FirXio01",8)||ni!={words_in(layout['inputs'])}||no!={words_in(layout['outputs'])})return 3;
    auto model=std::make_unique<GrhSIM_{top}>();auto& m=*model;m.init();
    std::vector<std::uint64_t> inputs(ni),outputs(no),previous(no);
    for(std::uint64_t step=0;step<count;++step){{
        input.read(reinterpret_cast<char*>(inputs.data()),ni*8);if(!input)return 4;
        {''.join('m.'+root+'={};' for root in roots)}
        {''.join(drive)}
        for(unsigned repeat=0;repeat<3;++repeat){{
            m.eval();{''.join(sample)}
            if(repeat&&outputs!=previous){{std::fprintf(stderr,"unstable repeated eval step=%llu\\n",(unsigned long long)step);return 5;}}
            previous=outputs;
        }}
        output.write(reinterpret_cast<const char*>(outputs.data()),no*8);
    }}
    return output?0:6;
}}
'''


def compare(args, top, prefix_cycles=None):
    work = args.output / top
    layout = json.loads((work / "layout.json").read_text())
    outs = layout["outputs"]
    record = struct.Struct(f"<{words_in(outs)}Q")
    stimulus_path = work / "stimulus-identity.json"
    if not stimulus_path.is_file():
        raise ValueError("comparison requires stimulus identity with declared cycles")
    expected_records = json.loads(stimulus_path.read_text())["cycles"] * 2
    variants = ("sv-off", "firrtl-off", "firrtl-prefer")
    output_paths = [work / variant / "outputs.bin" for variant in variants]
    if top == MEMORY:
        variants += ("scoreboard",)
        output_paths.append(work / "expected.bin")
    output_sizes = {variant: path.stat().st_size for variant, path in zip(variants, output_paths)}
    mask_size = (work / "compare-mask.bin").stat().st_size
    if prefix_cycles is not None:
        if prefix_cycles <= 0:
            raise ValueError("comparison prefix must contain positive cycles")
        required = prefix_cycles * 2 * record.size
        if any(size < required for size in output_sizes.values()) or mask_size < required:
            raise ValueError("model outputs have not reached requested comparison prefix")
    elif mask_size != expected_records * record.size or any(
            size != mask_size for size in output_sizes.values()):
        raise ValueError("final comparison requires every complete stimulus/output record")
    streams = [path.open("rb") for path in output_paths]
    compared = 0
    compared_sv, compared_probe, compared_internal = 0, 0, 0
    first, differences = None, {}
    activity = {variant: Counter() for variant in variants}
    with (work / "compare-mask.bin").open("rb") as masks:
        chunks = iter(lambda: masks.read(record.size), b"")
        if prefix_cycles is not None:
            chunks = islice(chunks, prefix_cycles * 2)
        for step, chunk in enumerate(chunks):
            mask = record.unpack(chunk)
            values = [record.unpack(stream.read(record.size)) for stream in streams]
            for leaf in outs:
                for word in range(leaf["words"]):
                    i = leaf["offset"] + word
                    bits = mask[i].bit_count()
                    compared += bits
                    if leaf.get("native_probe"):
                        compared_probe += bits
                    elif leaf.get("sv_internal"):
                        compared_internal += bits
                    else:
                        compared_sv += bits
                    if top == "Rob" and step % 2 and mask[i] and re.fullmatch(
                            r"io_commits_(?:commitValid|walkValid)_\d+", leaf["name"]):
                        for variant, value in zip(variants, values):
                            activity[variant][leaf["name"].rsplit("_", 1)[0]] += bool(value[i])
                    observed = values[1:] if leaf.get("native_probe") else values
                    if any((value[i] ^ observed[0][i]) & mask[i] for value in observed[1:]):
                        differences[leaf["name"]] = differences.get(leaf["name"], 0) + 1
                        if first is None:
                            first = {"step": step, "cycle": step // 2, "clock": step % 2,
                                     "port": leaf["name"], "word": word,
                                     "values": {name: hex(value[i]) for name, value in zip(variants, values)},
                                     "mask": hex(mask[i])}
    for stream in streams:
        if prefix_cycles is None and stream.read(1):
            raise ValueError("model output has trailing records")
        stream.close()
    report = {"top": top, "compared_bits": compared, "sv_firrtl_bits": compared_sv,
              "native_probe_bits": compared_probe, "sv_internal_bits": compared_internal,
              "differences": differences, "first": first,
              "activity": {variant: dict(counts) for variant, counts in activity.items()},
              "complete": prefix_cycles is None,
              "passed": bool(prefix_cycles is None and compared and not differences and
                             (top != "Rob" or activity["sv-off"]["io_commits_commitValid"])),
              "acceptance": "incomplete prefix diagnosis" if prefix_cycles is not None else "complete comparison",
              "compared_records": prefix_cycles * 2 if prefix_cycles is not None else expected_records,
              "expected_records": expected_records,
              "audit_time_utc": datetime.now(timezone.utc).isoformat(),
              "outputs": {variant: (file_identity(work / variant / "outputs.bin") if prefix_cycles is None else
                  {"path": str(work / variant / "outputs.bin"), "prefix_bytes": required,
                   "limitation": "live prefix diagnosis; complete file identity captured only by final comparison"})
                  for variant in variants if variant != "scoreboard"},
              **({"prefix_cycles": prefix_cycles,
                  "available_full_records": {variant: size // record.size for variant, size in output_sizes.items()},
                  "ignored_tail_bytes": {variant: size % record.size for variant, size in output_sizes.items()}}
                 if prefix_cycles is not None else {}),
              **({"scoreboard": file_identity(work / "expected.bin")} if top == MEMORY else {})}
    report_path = work / ("comparison.json" if prefix_cycles is None else "comparison-prefix.json")
    write_identity(report_path, report)
    if prefix_cycles is not None:
        write_identity(work / f"comparison-prefix{prefix_cycles}.json", report)
    if differences or not compared:
        raise RuntimeError(f"{top} mismatch: {json.dumps(first)}; {len(differences)} ports; see {report_path}")
    if prefix_cycles is None and top == "Rob" and not activity["sv-off"]["io_commits_commitValid"]:
        raise RuntimeError("ROB trace prefix must exercise commit outputs")
    print(f"{top}{f' INCOMPLETE prefix {prefix_cycles} cycles' if prefix_cycles is not None else ''}: "
          f"SV/FIRRTL off/prefer agree on {compared_sv} defined output bits; "
          f"SV existing-expression observations agree on {compared_internal} additional bits; "
          f"native off/prefer agree on {compared_probe} additional Probe bits", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "observe-sv", "audit-sv-observation", "audit-inputs", "drivers", "compare", "compare-prefix", "trace-activity"))
    parser.add_argument("--firrtl", required=True, type=Path)
    parser.add_argument("--sv-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--top", action="append")
    parser.add_argument("--include-dir", action="append", default=[], type=Path)
    parser.add_argument("--cycles", type=int, default=10000)
    parser.add_argument("--prefix-cycles", type=int)
    parser.add_argument("--dump-pre-simplify", action="store_true")
    parser.add_argument("--rob-trace", type=Path, default=ROOT / "ptmp/xs-components-rob/trace/rob_trace.bin")
    parser.add_argument("--rob-layout", type=Path, default=ROOT / "ptmp/xs-components-rob/trace/layout.json")
    parser.add_argument("--rob-capture-mapping", type=Path, default=ROOT / "ptmp/xs-components-rob/trace/fst_mapping.json")
    parser.add_argument("--rob-capture-summary", type=Path, default=ROOT / "ptmp/xs-components-rob/trace/capture_summary.json")
    parser.add_argument("--installation-log", type=Path)
    parser.add_argument("--observation-generation-log", type=Path)
    args = parser.parse_args()
    args.firrtl, args.sv_dir, args.output = args.firrtl.resolve(), args.sv_dir.resolve(), args.output.resolve()
    if args.action == "trace-activity":
        rob_trace_activity(args)
        return
    tops = args.top or ["RenameTable", MEMORY, "Rob"]
    for top in tops:
        if args.action == "generate":
            generate(args, top)
        elif args.action == "observe-sv":
            observe_sv(args, top)
        elif args.action == "audit-sv-observation":
            audit_sv_observation(args, top)
        elif args.action == "audit-inputs":
            retained_input_audit(args, top)
        elif args.action == "drivers":
            drivers(args, top)
        elif args.action == "compare-prefix":
            if args.prefix_cycles is None:
                raise ValueError("prefix comparison requires --prefix-cycles")
            compare(args, top, prefix_cycles=args.prefix_cycles)
        else:
            compare(args, top)
    if args.action in ("generate", "drivers"):
        (args.output / "run.mk").write_text(".PHONY: run " + " ".join(tops) + "\nrun: " + " ".join(tops) + "\n" +
            " ".join(tops) + ":\n\t$(MAKE) -C $@ -f run.mk run\n")


if __name__ == "__main__":
    main()
