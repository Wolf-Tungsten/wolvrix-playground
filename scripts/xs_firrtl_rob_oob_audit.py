#!/usr/bin/env python3
"""Explain saved ROB diffCommits differences without changing the comparison."""

import argparse
from collections import Counter
from contextlib import ExitStack
import json
import mmap
from pathlib import Path
import re
import struct

from grhsim_provenance import file_identity, write_identity

INFO_FIELDS = {"ldest": 6, "pdest": 8, "rfWen": 1, "fpWen": 1,
               "vecWen": 1, "v0Wen": 1, "vlWen": 1, "isMove": 1}


def check_defined_records(layout, stimulus_path, mask_path, output_paths, cycles):
    """Check every observed bit, projecting only the proven OOB info values."""
    outputs = {leaf["name"]: leaf for leaf in layout["outputs"]}
    inputs = {leaf["name"]: leaf for leaf in layout["inputs"]}
    valid_names = [f"io_diffCommits_commitValid_{i}" for i in range(520)]
    for lane in range(520):
        if outputs[valid_names[lane]]["width"] != 1:
            raise ValueError("source-definedness requires 520 one-bit diff commit-valid outputs")
        for field, width in INFO_FIELDS.items():
            leaf = outputs[f"io_diffCommits_info_{lane}_{field}"]
            if leaf["width"] != width or leaf["words"] != 1 or leaf.get("native_probe") or leaf.get("sv_internal"):
                raise ValueError("source-definedness info geometry differs from the audited source")
    probe_mask = sum(((1 << leaf["width"]) - 1) << (leaf["offset"] * 64)
                     for leaf in outputs.values() if leaf.get("native_probe"))
    internal_mask = sum(((1 << leaf["width"]) - 1) << (leaf["offset"] * 64)
                        for leaf in outputs.values() if leaf.get("sv_internal"))
    commit_names = [name for name in outputs if re.fullmatch(r"io_commits_commitValid_\d+", name)]
    counts = Counter()
    activity = Counter()
    cached_projection = {}
    with ExitStack() as stack:
        def mapped(path):
            stream = stack.enter_context(Path(path).open("rb"))
            return stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))
        stimulus = mapped(stimulus_path)
        masks = mapped(mask_path)
        data = {name: mapped(path) for name, path in output_paths.items()}
        if set(data) != {"sv-off", "firrtl-off", "firrtl-prefer"}:
            raise ValueError("source-defined comparison requires all three routes")
        magic, records, input_words, output_words = struct.unpack_from("<8sQII", stimulus)
        record_bytes = output_words * 8
        if (magic != b"FirXio01" or records != cycles * 2 or
                len(stimulus) != 24 + records * input_words * 8 or
                len(masks) != records * record_bytes or
                any(len(value) != len(masks) for value in data.values())):
            raise ValueError("source-defined comparison requires complete declared stimulus, masks and outputs")
        if output_words != max(leaf["offset"] + leaf["words"] for leaf in outputs.values()):
            raise ValueError("source-defined comparison output layout differs from the stimulus header")
        def output(row, name):
            return struct.unpack_from("<Q", row, outputs[name]["offset"] * 8)[0]
        def input_value(step, name):
            return struct.unpack_from("<Q", stimulus, 24 + (step * input_words + inputs[name]["offset"]) * 8)[0]
        def projection(pointer):
            if pointer not in cached_projection:
                lanes, bits = [], 0
                for lane in range(520):
                    value = pointer + lane
                    index = (value - 352 if value >= 352 else value) & 511
                    if index < 352:
                        continue
                    lanes.append((lane, index))
                    for field, width in INFO_FIELDS.items():
                        bits |= ((1 << width) - 1) << (outputs[f"io_diffCommits_info_{lane}_{field}"]["offset"] * 64)
                cached_projection[pointer] = (lanes, bits)
            return cached_projection[pointer]
        pointer, commit_size = 0, 0
        first_oob = None
        for step in range(records):
            rows = {name: value[step * record_bytes:(step + 1) * record_bytes] for name, value in data.items()}
            mask = int.from_bytes(masks[step * record_bytes:(step + 1) * record_bytes], "little")
            values = {name: int.from_bytes(row, "little") for name, row in rows.items()}
            if input_value(step, "clock") != step % 2:
                raise ValueError("source-definedness stimulus clock does not match its record level")
            if not step % 2:
                valid = [output(rows["sv-off"], name) for name in valid_names]
                commit_size = sum(valid)
                if commit_size > 511 or valid != [int(i < commit_size) for i in range(520)]:
                    raise ValueError("source-definedness commitValid is not the audited contiguous commitSize encoding")
            if input_value(step, "reset"):
                pointer = 0
            elif step % 2:
                value = pointer + commit_size
                pointer = (value - 352 if value >= 352 else value) & 511
            if pointer >= 352:
                raise ValueError("source-definedness reconstructed diffPtr is out of its declared range")
            lanes, projected_bits = projection(pointer)
            active_oob_mask = mask & projected_bits
            if active_oob_mask:
                row_zero_lane = 0 if not pointer else 352 - pointer
                for lane, index in lanes:
                    if not any(mask & (((1 << width) - 1) << (outputs[f"io_diffCommits_info_{lane}_{field}"]["offset"] * 64))
                               for field, width in INFO_FIELDS.items()):
                        continue
                    if any(output(row, valid_names[lane]) for row in rows.values()):
                        raise ValueError(f"source-definedness OOB lane valid at step {step}, lane {lane}")
                    for field in INFO_FIELDS:
                        name = f"io_diffCommits_info_{lane}_{field}"
                        row_zero_name = f"io_diffCommits_info_{row_zero_lane}_{field}"
                        if any(output(rows[variant], name) != 0 for variant in ("firrtl-off", "firrtl-prefer")):
                            raise ValueError(f"source-definedness native OOB policy at step {step}, {name}")
                        row_zero = output(rows["sv-off"], row_zero_name)
                        if output(rows["sv-off"], name) != row_zero:
                            raise ValueError(f"source-definedness SV OOB padding policy at step {step}, {name}")
                        if any(output(rows[variant], row_zero_name) != row_zero for variant in ("firrtl-off", "firrtl-prefer")):
                            raise ValueError(f"source-definedness in-range row-zero mismatch at step {step}, {name}")
                    counts["indeterminate_lane_records"] += 1
                    if first_oob is None:
                        first_oob = {"step": step, "cycle": step // 2, "clock": step % 2,
                                     "diff_pointer": pointer, "lane": lane, "index": index,
                                     "row_zero_observed_at_lane": row_zero_lane}
            if (values["firrtl-off"] ^ values["firrtl-prefer"]) & mask:
                raise ValueError(f"source-definedness native full-observation mismatch at step {step}")
            sv_mask = mask & ~probe_mask & ~projected_bits
            if (values["sv-off"] ^ values["firrtl-off"]) & sv_mask:
                raise ValueError(f"source-definedness in-range SV/native mismatch at step {step}")
            counts["ordinary_source_defined_bits"] += (sv_mask & ~internal_mask).bit_count()
            counts["sv_internal_source_defined_bits"] += (sv_mask & internal_mask).bit_count()
            counts["native_probe_bits"] += (mask & probe_mask).bit_count()
            counts["native_all_observed_bits"] += mask.bit_count()
            counts["indeterminate_info_bits"] += active_oob_mask.bit_count()
            if step % 2:
                for variant, row in rows.items():
                    activity[variant] += sum(bool(output(row, name)) for name in commit_names
                                             if mask & (1 << (outputs[name]["offset"] * 64)))
    if not counts["ordinary_source_defined_bits"] or any(not activity[name] for name in output_paths):
        raise ValueError("source-defined comparison requires observed ordinary outputs and actual commit activity")
    return {"complete": True, "passed": True, "comparison_kind": "source-definedness and indeterminate-policy checks",
            "bitwise_all_output_equality": False, "compared_records": records, "expected_records": cycles * 2,
            **dict(counts), "activity": dict(activity), "first_indeterminate_read": first_oob,
            "policy": {"native_oob": "zero from invalid-policy unknown through shared 2state conversion",
                       "frozen_sv_oob": "same-record in-range row-zero value for the proven padding",
                       "oob_valid": "zero in all three routes",
                       "native_off_prefer": "strict equality on all observed ordinary, recovered and Probe bits"}}


def defined_comparison(args):
    from xs_firrtl_rob_source import audit_source
    work = args.work
    write_identity(work / "defined-comparison.json", {"complete": False, "passed": False,
                   "comparison_kind": "source-definedness and indeterminate-policy checks", "status": "pending"})
    source_audit = audit_source(args.firrtl, args.sv_dir)
    original = json.loads((work / "comparison.json").read_text())
    stimulus = json.loads((work / "stimulus-identity.json").read_text())
    diagnosis = json.loads((work / "oob-audit.json").read_text())
    if (not original["complete"] or not diagnosis["all_reported_differences_explained"] or
            not diagnosis["all_out_of_range_lanes_invalid"] or
            not diagnosis["all_out_of_range_info_native_zero_sv_row_zero"] or
            diagnosis["comparison"] != file_identity(work / "comparison.json") or
            diagnosis["stimulus_identity"] != file_identity(work / "stimulus-identity.json")):
        raise ValueError("source-defined comparison requires the unchanged complete strict comparison and OOB diagnosis")
    output_paths = {variant: work / variant / "outputs.bin" for variant in ("sv-off", "firrtl-off", "firrtl-prefer")}
    if (file_identity(work / "inputs.bin") != stimulus["inputs"] or
            file_identity(work / "compare-mask.bin") != stimulus["compare_mask"] or
            any(file_identity(path) != original["outputs"][variant] for variant, path in output_paths.items())):
        raise ValueError("source-defined comparison input/mask/output identity changed after the strict comparison")
    result = check_defined_records(json.loads((work / "layout.json").read_text()), work / "inputs.bin",
                                   work / "compare-mask.bin", output_paths, stimulus["cycles"])
    if result["indeterminate_info_bits"] != diagnosis["out_of_range_info_bits"]:
        raise ValueError("source-defined comparison OOB bit count differs from the independent diagnosis")
    result.update({"strict_comparison": file_identity(work / "comparison.json"),
                   "oob_diagnosis": file_identity(work / "oob-audit.json"),
                   "stimulus_identity": file_identity(work / "stimulus-identity.json"),
                   "outputs": original["outputs"], "source_audit": source_audit,
                   "strict_different_leaves": len(original["differences"]),
                   "strict_differing_leaf_records": diagnosis["differing_leaf_records"]})
    write_identity(work / "defined-comparison.json", result)
    print(json.dumps({key: value for key, value in result.items() if key not in ("outputs", "source_audit")}), flush=True)


def source_witness(path, needles, module=None):
    result = {name: [] for name in needles}
    active = module is None
    with path.open() as source:
        for number, line in enumerate(source, 1):
            if module and line.startswith("  module "):
                if active:
                    break
                active = line.startswith(f"  module {module} :")
            if active:
                for name, needle in needles.items():
                    if needle in line:
                        result[name].append({"line": number, "statement": line.strip()})
    if any(len(rows) != 1 for rows in result.values()):
        raise ValueError(f"source witnesses must be unique: {path}: {result}")
    return {"path": str(path), "statements": result}


def audit(args):
    work = args.work
    layout = json.loads((work / "layout.json").read_text())
    comparison = json.loads((work / "comparison.json").read_text())
    if not comparison["complete"] or comparison["passed"]:
        raise ValueError("audit requires the unchanged complete failed comparison")
    outputs = {leaf["name"]: leaf for leaf in layout["outputs"]}
    inputs = {leaf["name"]: leaf for leaf in layout["inputs"]}
    valid_names = [f"io_diffCommits_commitValid_{i}" for i in range(520)]
    difference_fields = {}
    for name in comparison["differences"]:
        match = re.fullmatch(r"io_diffCommits_info_(\d+)_(ldest|pdest|rfWen)", name)
        if not match:
            raise ValueError(f"unexplained output class: {name}")
        difference_fields[name] = (int(match[1]), match[2])
    witnesses = {
        "firrtl": source_witness(args.firrtl, {
            "depth": "wire renameBufferEntries :",
            "info519": "connect io.diffCommits.info[519], renameBufferEntries[io_diffCommits_info_519_new_ptr.value].info",
            "commit_count": "node _io_diffCommits_commitValid_519_T = lt(UInt<10>(0h207), io.fromRob.commitSize)",
            "pointer_add": "node diffPtrNext_new_value = add(diffPtr.value, io.fromRob.commitSize)",
            "pointer_update": "connect diffPtr, diffPtrNext",
        }, "RenameBuffer"),
        "sv": source_witness(args.sv_dir / "RenameBuffer.sv", {
            "padding": "_GEN_690 = {160{renameBuffer[9'h0]}};",
            "concat": "_GEN_691 = {_GEN_690, renameBuffer};",
            "info519": "{{_GEN_691[$signed(_io_diffCommits_info_519_diff_T_4)",
            "pointer_add": "10'(_GEN_685 + {1'h0, io_fromRob_commitSize});",
            "pointer_reset": "diffPtr <= '{flag: 1'h0, value: 9'h0};",
        }),
    }
    with ExitStack() as stack:
        def mapped(path):
            stream = stack.enter_context(path.open("rb"))
            return stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))
        stimulus = mapped(work / "inputs.bin")
        sv = mapped(work / "sv-off/outputs.bin")
        native = mapped(work / "firrtl-off/outputs.bin")
        magic, records, input_words, output_words = struct.unpack_from("<8sQII", stimulus)
        if magic != b"FirXio01" or records != comparison["expected_records"]:
            raise ValueError("stimulus header disagrees with final comparison")
        def output(data, step, name):
            return struct.unpack_from("<Q", data, (step * output_words + outputs[name]["offset"]) * 8)[0]
        def input_value(step, name):
            return struct.unpack_from("<Q", stimulus, 24 + (step * input_words + inputs[name]["offset"]) * 8)[0]
        pointer = 0
        actual_differences = Counter()
        mismatch_samples = []
        first = None
        out_of_range_records = 0
        out_of_range_lane_records = 0
        info_fields = ("ldest", "pdest", "rfWen", "fpWen", "vecWen", "v0Wen", "vlWen", "isMove")
        info_width = sum(outputs[f"io_diffCommits_info_0_{field}"]["width"] for field in info_fields)
        for cycle in range(records // 2):
            low, high = cycle * 2, cycle * 2 + 1
            count = sum(output(sv, low, name) for name in valid_names)
            if any(output(sv, low, name) not in (0, 1) for name in valid_names):
                raise ValueError("commitValid output is not Boolean")
            if [output(sv, low, name) for name in valid_names] != [int(i < count) for i in range(520)]:
                raise ValueError("commitValid does not encode a contiguous commitSize")
            for step in (low, high):
                if input_value(step, "clock") != step % 2:
                    raise ValueError("stimulus clock does not match the comparison record level")
                before = pointer
                if input_value(step, "reset"):
                    pointer = 0
                elif step == high:
                    value = pointer + count
                    pointer = (value - 352 if value >= 352 else value) & 511
                if pointer >= 352:
                    raise ValueError("reconstructed diffPtr left its valid source range")
                row_zero_lane = 0 if not pointer else 352 - pointer
                for lane in range(520):
                    value = pointer + lane
                    index = (value - 352 if value >= 352 else value) & 511
                    if cycle < 8 or index < 352:
                        continue
                    if output(sv, step, f"io_diffCommits_commitValid_{lane}"):
                        raise ValueError(f"out-of-range lane is valid at cycle {cycle}, lane {lane}")
                    for field in info_fields:
                        name = f"io_diffCommits_info_{lane}_{field}"
                        row_zero_name = f"io_diffCommits_info_{row_zero_lane}_{field}"
                        row_zero = output(sv, step, row_zero_name)
                        if (output(native, step, name) != 0 or output(sv, step, name) != row_zero or
                                output(native, step, row_zero_name) != row_zero):
                            raise ValueError(f"out-of-range policy mismatch at cycle {cycle}, lane {lane}, field {field}")
                    out_of_range_lane_records += 1
                for name, (lane, field) in difference_fields.items():
                    left, right = output(sv, step, name), output(native, step, name)
                    if cycle < 8 or left == right:
                        continue
                    value = pointer + lane
                    index = (value - 352 if value >= 352 else value) & 511
                    row_zero = output(sv, step, f"io_diffCommits_info_{row_zero_lane}_{field}")
                    if index < 352 or right != 0 or left != row_zero:
                        raise ValueError(f"OOB row-zero explanation failed at cycle {cycle} step {step} {name}: "
                                         f"ptr={pointer} index={index} sv={left} native={right} row0={row_zero}")
                    actual_differences[name] += 1
                    if first is None:
                        first = {"cycle": cycle, "clock": step % 2, "port": name,
                                 "diff_pointer_before_edge": before, "diff_pointer": pointer,
                                 "commit_size_before_edge": count, "index": index,
                                 "row_zero_observed_at_lane": row_zero_lane,
                                 "sv": left, "native": right, "sv_row_zero": row_zero,
                                 "commit_valid_for_lane": output(sv, step, f"io_diffCommits_commitValid_{lane}")}
                    if len(mismatch_samples) < 8:
                        mismatch_samples.append({"cycle": cycle, "clock": step % 2, "port": name,
                                                 "diff_pointer": pointer, "index": index,
                                                 "sv": left, "native": right, "sv_row_zero": row_zero})
                    out_of_range_records += 1
        if dict(actual_differences) != comparison["differences"]:
            raise ValueError("diagnostic counts do not match the unchanged final comparator")
    result = {"comparison": file_identity(work / "comparison.json"),
              "stimulus_identity": file_identity(work / "stimulus-identity.json"),
              "sources": witnesses, "pointer_reconstruction":
              "reset -> 0; each rising edge adds previous low-level commitValid population (=commitSize), subtracts 352 once and keeps 9 bits",
              "first": first, "mismatch_samples": mismatch_samples,
              "different_leaves": len(actual_differences), "differing_leaf_records": out_of_range_records,
              "out_of_range_lane_records": out_of_range_lane_records,
              "out_of_range_info_bits": out_of_range_lane_records * info_width,
              "all_out_of_range_lanes_invalid": True,
              "all_out_of_range_info_native_zero_sv_row_zero": True,
              "all_reported_differences_explained": True,
              "native_off_prefer_output_sha_equal": comparison["outputs"]["firrtl-off"]["sha256"] == comparison["outputs"]["firrtl-prefer"]["sha256"],
              "equivalence_passed": False,
              "limitation": "Diagnostic only: original comparison, masks, drivers, models and outputs remain unchanged. Native invalid-policy unknown and frozen SV row-zero concretization differ for source out-of-range reads."}
    write_identity(work / "oob-audit.json", result)
    print(json.dumps({key: result[key] for key in ("first", "different_leaves", "differing_leaf_records",
                                                  "out_of_range_lane_records", "out_of_range_info_bits",
                                                  "all_reported_differences_explained", "equivalence_passed")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--sv-dir", type=Path, required=True)
    parser.add_argument("--defined-comparison", action="store_true")
    arguments = parser.parse_args()
    if arguments.defined_comparison:
        try:
            defined_comparison(arguments)
        except Exception as error:
            write_identity(arguments.work / "defined-comparison.json", {"complete": False, "passed": False,
                           "comparison_kind": "source-definedness and indeterminate-policy checks", "error": str(error)})
            raise
    else:
        audit(arguments)
