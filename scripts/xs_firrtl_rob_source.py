"""Strict source proof for the captured ROB diffCommits definedness audit.

This recognizes one frozen RenameBuffer implementation. It does not infer a
general FIRRTL or SV equivalence rule, and rejects changes to the dependency
slice used by the trace auditor. No observation masks or models are modified.
"""

from collections import Counter
import hashlib
from pathlib import Path
import re

from grhsim_provenance import file_identity


DEPTH = 352
LANES = 520
FIELDS = (("ldest", 6), ("pdest", 8), ("rfWen", 1), ("fpWen", 1),
          ("vecWen", 1), ("v0Wen", 1), ("vlWen", 1), ("isMove", 1))
FIR_INFO = "{ " + ", ".join(f"{name} : UInt<{width}>" for name, width in FIELDS) + "}"
FIR_PTR = "{ flag : UInt<1>, value : UInt<9>}"
FIR_ENTRY = "{ info : " + FIR_INFO + ", robIdx : " + FIR_PTR + "}"
SV_INFO = "struct packed {" + " ".join(
    f"logic [{width - 1}:0] {name};" if width > 1 else f"logic {name};"
    for name, width in FIELDS) + " }"
SV_PTR = "struct packed {logic flag; logic [8:0] value; }"
SV_ENTRY = "struct packed {" + SV_INFO + " info; " + SV_PTR + " robIdx; }"


def _digest(lines):
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _pointer_statements(prefix, amount, depth_width):
    """The exact unsigned add / signed single-subtraction pointer family."""
    return [
        f"wire {prefix}_new_ptr : {FIR_PTR}",
        f"node {prefix}_new_value = add(diffPtr.value, {amount})",
        f"node _{prefix}_diff_T = cat(UInt<1>(0h0), {prefix}_new_value)",
        f"node _{prefix}_diff_T_1 = asSInt(_{prefix}_diff_T)",
        f"node _{prefix}_diff_T_2 = cat(UInt<1>(0h0), UInt<{depth_width}>(0h160))",
        f"node _{prefix}_diff_T_3 = asSInt(_{prefix}_diff_T_2)",
        f"node _{prefix}_diff_T_4 = sub(_{prefix}_diff_T_1, _{prefix}_diff_T_3)",
        f"node _{prefix}_diff_T_5 = tail(_{prefix}_diff_T_4, 1)",
        f"node {prefix}_diff = asSInt(_{prefix}_diff_T_5)",
        f"node {prefix}_reverse_flag = geq({prefix}_diff, SInt<1>(0h0))",
        f"node _{prefix}_new_ptr_flag_T = eq(diffPtr.flag, UInt<1>(0h0))",
        f"node _{prefix}_new_ptr_flag_T_1 = mux({prefix}_reverse_flag, _{prefix}_new_ptr_flag_T, diffPtr.flag)",
        f"connect {prefix}_new_ptr.flag, _{prefix}_new_ptr_flag_T_1",
        f"node _{prefix}_new_ptr_value_T = asUInt({prefix}_diff)",
        f"node _{prefix}_new_ptr_value_T_1 = mux({prefix}_reverse_flag, _{prefix}_new_ptr_value_T, {prefix}_new_value)",
        f"connect {prefix}_new_ptr.value, _{prefix}_new_ptr_value_T_1",
    ]


def _firrtl_expected():
    expected = [
        f"wire _diffPtr_WIRE : const {FIR_PTR}",
        "connect _diffPtr_WIRE.value, UInt<9>(0h0)",
        "connect _diffPtr_WIRE.flag, UInt<1>(0h0)",
        f"regreset diffPtr : {FIR_PTR}, clock, reset, _diffPtr_WIRE",
        f"wire diffPtrNext : {FIR_PTR}",
        f"reg renameBuffer : {FIR_ENTRY}[352], clock",
        f"wire renameBufferEntries : {FIR_ENTRY}[352]",
    ]
    expected.extend(f"connect renameBufferEntries[{i}], renameBuffer[{i}]" for i in range(DEPTH))
    expected.extend(_pointer_statements("diffPtrNext", "io.fromRob.commitSize", 10))
    expected.extend(("connect diffPtrNext, diffPtrNext_new_ptr", "connect diffPtr, diffPtrNext"))
    for i in range(LANES):
        expected.extend(f"connect io.diffCommits.info[{i}].{name}, UInt<{width}>(0h0)"
                        for name, width in reversed(FIELDS))
    expected.extend(f"connect io.diffCommits.commitValid[{i}], UInt<1>(0h0)" for i in range(LANES))
    expected.extend(("connect io.diffCommits.isCommit, UInt<1>(0h0)",
                     "connect io.diffCommits.isCommit, UInt<1>(0h1)"))
    for i in range(LANES):
        constant = f"UInt<{max(1, i.bit_length())}>(0h{i:x})"
        expected.extend((
            f"node _io_diffCommits_commitValid_{i}_T = lt({constant}, io.fromRob.commitSize)",
            f"connect io.diffCommits.commitValid[{i}], _io_diffCommits_commitValid_{i}_T"))
        expected.extend(_pointer_statements(f"io_diffCommits_info_{i}", constant,
                                            10 if i < 512 else 11))
        expected.append(f"connect io.diffCommits.info[{i}], renameBufferEntries[io_diffCommits_info_{i}_new_ptr.value].info")
    return expected


def _firrtl_target(statement):
    definition = re.match(r"(?:node|wire|regreset|reg) ([A-Za-z_][\w]*)", statement)
    if definition:
        name = definition[1]
        return (name in ("renameBuffer", "renameBufferEntries") or
                re.match(r"_?(?:diffPtr|io_diffCommits)(?:_|$|Next)", name) is not None)
    assignment = re.match(r"(?:connect|invalidate) ([^,\s]+)", statement)
    if not assignment:
        return False
    destination = assignment[1]
    return (destination == "io" or destination.startswith("io.diffCommits") or
            destination.startswith("io.fromRob") or
            destination.startswith(("renameBufferEntries", "diffPtr", "_diffPtr", "io_diffCommits", "_io_diffCommits")))


def _audit_firrtl(path):
    selected, declarations, inputs, module_lines = [], [], [], []
    active, module_count = False, 0
    source_hash, module_hash = hashlib.sha256(), hashlib.sha256()
    module_header = re.compile(r"^  (?:public )?(?:ext)?module ([^\s:]+)\s*:")
    byte_count = 0
    with path.open("rb") as source:
        for number, raw in enumerate(source, 1):
            source_hash.update(raw)
            byte_count += len(raw)
            line = raw.decode()
            header = module_header.match(line)
            if header:
                active = header[1] == "RenameBuffer"
                module_count += active
            if not active:
                continue
            module_hash.update(raw)
            statement = line.split(" @[", 1)[0].rstrip()
            if statement.startswith("    output io : "):
                declarations.append((number, statement.strip()))
            if statement.startswith("    input "):
                inputs.append(statement.strip())
            if _firrtl_target(statement.strip()):
                if not statement.startswith("    ") or statement.startswith("     "):
                    raise ValueError(f"source proof requires unconditional RenameBuffer statement at {number}")
                selected.append(statement.strip())
                module_lines.append(number)
    if module_count != 1 or len(declarations) != 1:
        raise ValueError("source proof requires one RenameBuffer module and one io declaration")
    if inputs != ["input clock : Clock", "input reset : Reset"]:
        raise ValueError("source proof requires the frozen clock/reset declarations")
    port = declarations[0][1]
    for fragment in (
            "fromRob : { flip walkSize : UInt<9>, flip walkEnd : UInt<1>, flip commitSize : UInt<9>,",
            f"diffCommits : {{ isCommit : UInt<1>, commitValid : UInt<1>[520], info : {FIR_INFO}[520]}}"):
        if port.count(fragment) != 1:
            raise ValueError(f"RenameBuffer source port shape changed: {fragment}")
    expected = _firrtl_expected()
    if selected != expected:
        first = next((i for i, pair in enumerate(zip(selected, expected)) if pair[0] != pair[1]),
                     min(len(selected), len(expected)))
        raise ValueError(f"RenameBuffer source proof differs at statement {first}: "
                         f"actual={selected[first:first + 1]}, expected={expected[first:first + 1]}; "
                         f"counts={len(selected)}/{len(expected)}")
    return {"path": str(path.resolve()), "bytes": byte_count, "sha256": source_hash.hexdigest(),
            "module": "RenameBuffer", "module_sha256": module_hash.hexdigest(),
            "checked_statements": len(selected), "checked_statement_sha256": _digest(selected),
            "first_checked_line": module_lines[0], "last_checked_line": module_lines[-1],
            "io_declaration_line": declarations[0][0]}


def _compact(text):
    return re.sub(r"\s+", "", text)


def _sv_valid_expression(lane):
    if lane >= 511:
        return "1'h0"
    if lane == 510:
        return "&io_fromRob_commitSize"
    if lane == 0:
        return "|io_fromRob_commitSize"
    if lane == 255:
        return "io_fromRob_commitSize[8]"
    if not (lane & (lane + 1)):
        return f"|(io_fromRob_commitSize[8:{(lane + 1).bit_length() - 1}])"
    return f"io_fromRob_commitSize > 9'h{lane:X}"


def _sv_expected():
    expected = {
        "_GEN_685": "wire [9:0] _GEN_685 = {1'h0, diffPtr.value};",
        "_GEN_689": "wire [10:0] _GEN_689 = {2'h0, diffPtr.value};",
        "_GEN_690": f"wire {SV_ENTRY}[159:0] _GEN_690 = {{160{{renameBuffer[9'h0]}}}};",
        "_GEN_691": f"wire {SV_ENTRY}[511:0] _GEN_691 = {{_GEN_690, renameBuffer}};",
        "diffPtrNext_new_value": "wire [9:0] diffPtrNext_new_value = 10'(_GEN_685 + {1'h0, io_fromRob_commitSize});",
        "_diffPtrNext_diff_T_4": "wire [10:0] _diffPtrNext_diff_T_4 = 11'({1'h0, diffPtrNext_new_value} - 11'h160);",
        "diffPtrNext_reverse_flag": "wire diffPtrNext_reverse_flag = $signed(_diffPtrNext_diff_T_4) > -11'sh1;",
        "_diffPtrNext_new_ptr_value_T_1": "wire [8:0] _diffPtrNext_new_ptr_value_T_1 = diffPtrNext_reverse_flag ? _diffPtrNext_diff_T_4[8:0] : diffPtrNext_new_value[8:0];",
    }
    info = []
    for i in range(LANES):
        prefix = f"io_diffCommits_info_{i}"
        width = 10 if i < 512 else 11
        if i:
            base = "_GEN_685" if width == 10 else "_GEN_689"
            expected[f"{prefix}_new_value"] = f"wire [{width - 1}:0] {prefix}_new_value = {width}'({base} + {width}'h{i:X});"
            difference = f"{width + 1}'({{1'h0, {prefix}_new_value}} - {width + 1}'h160)"
            alternative = f"{prefix}_new_value[8:0]"
        else:
            difference = "11'(_GEN_689 - 11'h160)"
            alternative = "diffPtr.value"
        expected[f"_{prefix}_diff_T_4"] = f"wire [{width}:0] _{prefix}_diff_T_4 = {difference};"
        info.append("{_GEN_691[$signed(" + f"_{prefix}_diff_T_4) > -{width + 1}'sh1 ? " +
                    f"_{prefix}_diff_T_4[8:0] : {alternative}].info" + "}")
    expected["_GEN_707"] = "wire [519:0] _GEN_707 = {" + ",".join(
        "{" + _sv_valid_expression(i) + "}" for i in reversed(range(LANES))) + "};"
    expected["_GEN_716"] = f"wire {SV_INFO}[519:0] _GEN_716 = {{" + ",".join(reversed(info)) + "};"
    expected["io_diffCommits"] = "assign io_diffCommits = '{isCommit: (1'h1), commitValid: _GEN_707, info: _GEN_716};"
    return expected


def _audit_sv(path):
    text = path.read_text()
    # Only whitespace is ignored. Comments inserted into the supported source
    # expressions intentionally invalidate this exact frozen-source proof.
    compact = _compact(text)
    expected = _sv_expected()
    for symbol, statement in expected.items():
        if compact.count(_compact(statement)) != 1:
            raise ValueError(f"frozen SV source proof changed: {symbol}")
    for statement in (f"{SV_PTR} diffPtr;", f"{SV_ENTRY}[351:0] renameBuffer;",
                      "input [8:0] io_fromRob_commitSize,"):
        if compact.count(_compact(statement)) != 1:
            raise ValueError(f"frozen SV declaration changed: {statement}")
    reset = "diffPtr <= '{flag: 1'h0, value: 9'h0};"
    update = "diffPtr <= '{flag: (diffPtrNext_reverse_flag ^ diffPtr.flag), value: _diffPtrNext_new_ptr_value_T_1};"
    initial_writes = (
        "diffPtr.flag = _RANDOM[9'h26][19];",
        "diffPtr.value = _RANDOM[9'h26][18:10];",
        "diffPtr = '{flag: 1'h0, value: 9'h0};")
    pointer_writes = Counter(_compact(statement) for statement in (reset, update, *initial_writes))
    # Reject subsequent or partial writes, rather than only finding one valid
    # initializer that a later assignment could override. Frozen initial-only
    # assignments are checked separately; captured reset precedes observations.
    names = set(expected) | {"diffPtr"}
    lhs = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) +
                     r")((?:\.[A-Za-z_]\w*|\[[^\]\n]+\])*)\s*(<=|=(?!=))")
    assignments = Counter()
    actual_pointer_writes = Counter()
    for match in lhs.finditer(text):
        if match[1] == "diffPtr":
            end = text.find(";", match.start())
            actual_pointer_writes[_compact(text[match.start():end + 1])] += 1
        elif match[2]:
            raise ValueError(f"frozen SV has an unsupported partial write: {match[0]}")
        assignments[match[1]] += 1
    if assignments != Counter({name: 5 if name == "diffPtr" else 1 for name in names}):
        raise ValueError("frozen SV source proof requires unique definitions and the five supported diffPtr assignments")
    if actual_pointer_writes != pointer_writes:
        raise ValueError("frozen SV diffPtr reset/update changed")
    # Generated indentation identifies unconditional statements inside the
    # reset/else branches. Nested guards and another process are rejected.
    lines = text.splitlines()
    writes = [i for i, line in enumerate(lines) if re.search(r"\bdiffPtr\s*<=", line)]
    starts = [i for i, line in enumerate(lines) if line == "  always @(posedge clock or posedge reset) begin"]
    owners = []
    for start in starts:
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^  end(?:\s|$)", lines[i])), None)
        if end is not None and all(start < write < end for write in writes):
            owners.append((start, end))
    if len(owners) != 1 or len(writes) != 2:
        raise ValueError("frozen SV diffPtr writes do not share the supported reset process")
    start, end = owners[0]
    branch = next((i for i in range(start + 1, end) if lines[i:i + 2] == ["    end", "    else begin"]), None)
    if (lines[start + 1] != "    if (reset) begin" or branch is None or
            not (start < writes[0] < branch < writes[1] < end) or
            any(not lines[i].startswith("      diffPtr <=") for i in writes)):
        raise ValueError("frozen SV diffPtr reset/else guards changed")
    initial = [i for i, line in enumerate(lines) if line == "    initial begin"]
    if len(initial) != 1:
        raise ValueError("frozen SV requires one supported initial process")
    init_start = initial[0]
    init_end = next((i for i in range(init_start + 1, len(lines))
                     if re.match(r"^    end(?:\s|$)", lines[i])), None)
    if init_end is None:
        raise ValueError("frozen SV initial process is not recognized")
    for statement in initial_writes:
        locations = [i for i, line in enumerate(lines) if line == "        " + statement]
        if len(locations) != 1 or not init_start < locations[0] < init_end:
            raise ValueError("frozen SV initialization write escaped its initial process")
    return {**file_identity(path), "checked_definitions": len(expected),
            "checked_definition_sha256": _digest([_compact(expected[name]) for name in sorted(expected)]),
            "pointer_write_lines": [i + 1 for i in writes], "padding_rows": 160,
            "padded_depth": 512, "padding_value": "renameBuffer[0]",
            "initialization": "only the three frozen initial-only writes; captured reset precedes observed records"}


def audit_source(firrtl_path, sv_dir):
    """Prove the exact source slice used to reconstruct ROB read definedness.

    Returns identities and bounded witness summaries. Failure to recognize any
    family member, alias, declaration, write priority or guard rejects proof.
    The caller must separately validate the saved model/stimulus identities.
    """
    firrtl = _audit_firrtl(Path(firrtl_path))
    sv = _audit_sv(Path(sv_dir) / "RenameBuffer.sv")
    return {"schema": 1, "proof": "exact frozen RenameBuffer dependency slice",
            "firrtl": firrtl, "sv": sv, "depth": DEPTH, "lanes": LANES,
            "pointer_bits": 9, "commit_size_bits": 9, "info_fields": dict(FIELDS),
            "pointer_transition": "reset ? 0 : ((p + commitSize >= 352 ? p + commitSize - 352 : p + commitSize) & 511)",
            "read_index": "(p + lane >= 352 ? p + lane - 352 : p + lane) & 511",
            "commit_valid": "lane < commitSize, for every lane 0..519",
            "firrtl_out_of_range": "invalidPolicy (captured native policy unknown projects to zero in shared 2state)",
            "sv_out_of_range": "padded indices 352..511 select renameBuffer[0]",
            "limitation": "This recognizes source expressions; it does not prove arbitrary transformed models or authorize changing strict comparison evidence."}
