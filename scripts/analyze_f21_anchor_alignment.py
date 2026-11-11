"""Build a streamed F21 GRH/GSIM anchor identity and survival report.

The report deliberately separates exact identity joins from representation rules.
It only compares serialized anchor records; it does not claim behavioral or
semantic equivalence.
"""
from __future__ import annotations

import argparse
import json
import re
import resource
import sys
import time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

from grhsim_f21_dce_compare import module_name, normalize


RECORD_ID = re.compile(r'\{"id":\s*(\d+)')
STATE_PARENT_TYPES = {"NODE_REG_SRC"}
MEMORY_TYPE = "NODE_MEMORY"
REG_SRC_TYPE = "NODE_REG_SRC"
TOP_IO_TYPES = {"NODE_INP", "NODE_OUT"}
EXT_TYPES = {"NODE_EXT", "NODE_EXT_IN", "NODE_EXT_OUT"}
SYSTEM_TASK_KINDS = {"kSystemTask"}
DPI_KINDS = {"kDpicCall", "kDpicImport"}
LATCH_KINDS = {"kLatch"}
MEMORY_PIPELINE_ATTR = "firrtl.memoryPipeline"
MEMORY_ATTR = "firrtl.memory"

SEMANTIC_NODE = re.compile(
    r'\{"parent": (\d+), "kind": "(module|declaration|expression|field|element)", '
    r'"name": ("(?:\\.|[^"\\])*")(?:, "index": (-?\d+))?\},?'
)
SEMANTIC_KIND = {name: index for index, name in enumerate(
    ("invalid", "module", "declaration", "expression", "field", "element"))}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def attr_value(attrs: dict, key: str, default=None):
    value = attrs.get(key)
    if not isinstance(value, dict):
        return default
    if "v" in value:
        return value["v"]
    if "vs" in value:
        return value["vs"]
    return default


def grh_width(record: dict | None):
    if record is None:
        return None
    if isinstance(record.get("w"), int):
        return record["w"]
    return attr_value(record.get("attrs", {}), "width")


def grh_shape(record: dict | None):
    if record is None:
        return []
    if isinstance(record.get("shape"), list):
        return record["shape"]
    return attr_value(record.get("attrs", {}), "shape", [])


def record_name(record: dict | None, side: str) -> str:
    if not record:
        return ""
    return normalize(record.get("sym", "") if side == "grh" else record.get("name", ""))


def record_from_line(line: str) -> dict:
    return json.loads(line.strip().rstrip(","))


def shape_count(shape) -> int:
    count = 1
    for value in shape or []:
        if not isinstance(value, int) or value <= 0:
            return 0
        count *= value
    return count


def shape_width_match(grh_record: dict | None, gsim_record: dict | None) -> tuple[bool | None, bool | None]:
    """Compare packed GRH shape/width with a GSIM element width/dimension.

    GRH kRegister widths include every packed array dimension.  GSIM REG_SRC
    records expose the element width and keep dimensions separately.  The
    comparison therefore divides the GRH packed width by its shape product
    before comparing widths, while the GRH shape is compared with the GSIM
    dimension (a scalar has an empty dimension).
    """
    if grh_record is None or gsim_record is None:
        return None, None
    shape = list(grh_shape(grh_record) or [])
    dimension = list(gsim_record.get("dimension", []) or [])
    grh_width_value = grh_width(grh_record)
    gsim_width_value = gsim_record.get("width")
    if not isinstance(grh_width_value, int) or not isinstance(gsim_width_value, int):
        return None, None
    count = shape_count(shape)
    width = grh_width_value // count if count and grh_width_value % count == 0 else None
    width_match = width == gsim_width_value if width is not None else False
    # A singleton GRH dimension is serialized for some FIRRTL aggregates even
    # when GSIM canonicalizes it to a scalar dimension.  Remove singleton
    # axes before comparing the representation shape; all non-singleton axes
    # must still match exactly.
    normalized_shape = [axis for axis in shape if axis != 1]
    normalized_dimension = [axis for axis in dimension if axis != 1]
    shape_match = normalized_shape == normalized_dimension
    return width_match, shape_match


def _trailing_member_variants(name: str):
    """Yield ``(parent, suffix)`` candidates for numeric member names.

    A generated member can end in ``_0`` or ``_0_1_3``.  Yielding every
    prefix makes the rule work for both a single packed array and nested
    dimensions while the caller validates the total width and member set.
    """
    value = normalize(name)
    match = re.search(r"((?:_\d+)+)$", value)
    if match is None:
        return
    suffix = match.group(1)
    tokens = suffix[1:].split("_")
    for count in range(1, len(tokens) + 1):
        parent = value[:match.start()] + suffix[: -(sum(len(token) + 1 for token in tokens[-count:]))]
        # The expression above leaves the separator before the retained
        # suffix intact for nested dimensions; normalize an accidental one.
        parent = parent.rstrip("_")
        yield parent, "_".join(tokens[-count:])


def build_aggregate_pairs(grh_records: dict[str, dict], gsim_records: dict[str, dict]):
    """Pair one aggregate row with its numeric-suffix member rows.

    The rule is deliberately conservative: the parent name must be the exact
    prefix before a numeric suffix, the member count must equal the aggregate
    shape product, and the sum of member widths must equal the aggregate
    packed width.  Records are returned with per-member suffixes so survival
    can be reported as an any-member status plus detail.
    """
    grh_members: defaultdict[str, list[tuple[str, dict]]] = defaultdict(list)
    gsim_members: defaultdict[str, list[tuple[str, dict]]] = defaultdict(list)
    for key, record in grh_records.items():
        for parent, suffix in _trailing_member_variants(key) or ():
            grh_members[parent].append((suffix, record))
    for key, record in gsim_records.items():
        for parent, suffix in _trailing_member_variants(key) or ():
            gsim_members[parent].append((suffix, record))

    pairs = []
    used_grh: set[str] = set()
    used_gsim: set[str] = set()

    def valid_group(aggregate: dict, members: list[tuple[str, dict]], side: str):
        shape = grh_shape(aggregate) if side == "grh" else aggregate.get("dimension", [])
        expected_count = shape_count(shape)
        packed_width = grh_width(aggregate) if side == "grh" else aggregate.get("width")
        if expected_count <= 1 or not isinstance(packed_width, int):
            return None
        unique = {}
        for suffix, record in members:
            unique.setdefault(suffix, record)
        if len(unique) != expected_count:
            return None
        # ``side`` identifies the aggregate side.  The member rows are from
        # the opposite serialized format, so read their width from that
        # format explicitly.
        widths = [record.get("width") if side == "grh" else grh_width(record)
                  for record in unique.values()]
        if any(not isinstance(width, int) for width in widths):
            return None
        if sum(widths) != packed_width:
            return None
        return sorted(unique.items(), key=lambda item: tuple(int(token) for token in item[0].split("_")))

    for parent, aggregate in sorted(grh_records.items()):
        if parent in used_grh:
            continue
        members = [(suffix, record) for suffix, record in grh_members.get(parent, [])
                   if normalize(record.get("sym", "")) not in used_grh]
        # GRH aggregate -> GSIM split members.
        candidates = [(suffix, record) for suffix, record in gsim_members.get(parent, [])
                      if normalize(record.get("name", "")) not in used_gsim]
        valid = valid_group(aggregate, candidates, "grh")
        if valid is None:
            continue
        pairs.append({"direction": "grh_aggregate_to_gsim_members",
                      "parent": parent, "aggregate": aggregate,
                      "members": valid})
        used_grh.add(parent)
        used_gsim.update(normalize(record.get("name", "")) for _suffix, record in valid)

    for parent, aggregate in sorted(gsim_records.items()):
        if parent in used_gsim:
            continue
        candidates = [(suffix, record) for suffix, record in grh_members.get(parent, [])
                      if normalize(record.get("sym", "")) not in used_grh]
        valid = valid_group(aggregate, candidates, "gsim")
        if valid is None:
            continue
        pairs.append({"direction": "gsim_aggregate_to_grh_members",
                      "parent": parent, "aggregate": aggregate,
                      "members": valid})
        used_gsim.add(parent)
        used_grh.update(normalize(record.get("sym", "")) for _suffix, record in valid)
    return pairs, used_grh, used_gsim


def load_semantic_paths(source: Path, target_ids: set[int]) -> dict[int, str]:
    """Resolve only selected GRH SemanticTree IDs to flattened names.

    The first pass stores compact parent/kind arrays; the second pass decodes
    names only for the ancestor closure of the requested IDs.  This avoids a
    multi-million-entry Python string path table while retaining the exact
    separator rules used by the existing F21 trace tools.
    """
    if not target_ids:
        return {}
    parents = array("I", [0, 0])
    kinds = array("B", [0, SEMANTIC_KIND["module"]])
    module_children: list[tuple[int, str]] = []
    declarations: list[tuple[int, str, int]] = []
    in_tree = False
    roots = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if '"semanticTree": {' in line:
                in_tree = True
                continue
            if not in_tree:
                continue
            if '"declaredSymbols":' in line or line.lstrip().startswith('"vals":'):
                break
            match = SEMANTIC_NODE.search(line)
            if match is None:
                continue
            parent = int(match.group(1))
            kind = SEMANTIC_KIND[match.group(2)]
            name = json.loads(match.group(3))
            if parent == 0:
                roots += 1
                continue
            semantic_id = len(parents)
            if parent >= len(parents):
                raise ValueError(f"invalid SemanticTree parent {parent} at node {semantic_id}")
            parents.append(parent)
            kinds.append(kind)
            if kind == SEMANTIC_KIND["module"]:
                module_children.append((parent, name))
            elif kind == SEMANTIC_KIND["declaration"] and kinds[parent] == SEMANTIC_KIND["module"]:
                declarations.append((parent, name, semantic_id))
    if roots != 1:
        raise ValueError(f"expected one flattened semantic root, got {roots}")
    instance_declarations = {
        semantic_id for parent, name, semantic_id in declarations
        if (parent, name) in {(module_parent, module_name)
                              for module_parent, module_name in module_children}
    }
    closure: set[int] = set()
    for target in target_ids:
        if target <= 0 or target >= len(parents):
            continue
        current = target
        while current > 1 and current not in closure:
            closure.add(current)
            current = parents[current]
    components: dict[int, str] = {}
    in_tree = False
    semantic_id = 1
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if '"semanticTree": {' in line:
                in_tree = True
                continue
            if not in_tree:
                continue
            if '"declaredSymbols":' in line or line.lstrip().startswith('"vals":'):
                break
            match = SEMANTIC_NODE.search(line)
            if match is None:
                continue
            parent = int(match.group(1))
            kind = SEMANTIC_KIND[match.group(2)]
            if parent == 0:
                continue
            semantic_id += 1
            if semantic_id not in closure:
                continue
            name = json.loads(match.group(3))
            index = match.group(4)
            components[semantic_id] = (
                f"[{index}]" if kind == SEMANTIC_KIND["element"] else name
            )
    paths = {1: ""}
    for semantic_id in sorted(closure):
        parent = parents[semantic_id]
        kind = kinds[semantic_id]
        parent_path = paths.get(parent, "")
        component = components.get(semantic_id, "")
        if kind == SEMANTIC_KIND["element"]:
            separator = ""
        elif (kind == SEMANTIC_KIND["module"] or kinds[parent] == SEMANTIC_KIND["module"]
              or parent in instance_declarations):
            separator = "$" if parent_path else ""
        else:
            separator = "__DOT__"
        paths[semantic_id] = parent_path + separator + component
    return {target: paths.get(target, "") for target in target_ids}


def suffix_kind(name: str) -> str | None:
    """Classify the known generated REG_SRC suffixes."""
    normalized = normalize(name)
    if normalized.endswith("__DOT__ADDR"):
        return "gsim_addr_pipeline"
    if normalized.endswith("__DOT__ADDRESS"):
        return "gsim_address_generated"
    if ("copy__DOT__copySrc" in normalized or "$copy$copySrc" in name
            or "$$copy$$copySrc" in name or "__DOT__copy__DOT__copySrc" in name):
        return "gsim_copy_derived"
    return None


def generated_reg_reason(record: dict) -> str | None:
    width = record.get("width")
    if width == 0:
        return "gsim_zero_width_register"
    name = normalize(record.get("name", ""))
    if re.search(r"ramDatas__DOT__(?:tag|reservedBits)_\d+$", name):
        return "gsim_ramdatas_residual"
    if "$ram" in record.get("name", ""):
        return "gsim_depth1_memory_conversion"
    return suffix_kind(record.get("name", ""))


def survival_label(grh_alive: bool, gsim_alive: bool) -> str:
    if grh_alive and gsim_alive:
        return "both_alive"
    if grh_alive:
        return "grh_only"
    if gsim_alive:
        return "gsim_only"
    return "both_dead"


def name_pattern(name: str) -> str:
    """Stable module/name grouping used by the report's top-N sections."""
    value = re.sub(r"\d+", "#", name)
    value = re.sub(r"_#+", "_#", value)
    return value


def _append_name(mapping: dict[str, list[dict]], name: str, record: dict) -> None:
    mapping.setdefault(normalize(name), []).append(record)


def collect_grh(source: Path) -> dict:
    """Collect only anchor records from a GRH JSON stream."""
    result = {
        "registers": {},
        "register_duplicates": [],
        "top_io": {},
        "top_io_duplicates": [],
        "latches": [],
        "system_tasks": [],
        "system_functions": [],
        "dpi_calls": [],
        "dpi_imports": [],
        "instances": [],
        "blackboxes": [],
        "stats": Counter(),
    }
    section = ""
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.lstrip().startswith('"vals":'):
                section = "vals"
                continue
            if line.lstrip().startswith('"ops":'):
                section = "ops"
                continue
            if section == "vals" and line.lstrip().startswith('{"id":'):
                if ('"in": true' not in line and '"out": true' not in line
                        and '"inout": true' not in line):
                    continue
                record = record_from_line(line)
                name = record.get("sym", "")
                key = normalize(name)
                result["stats"]["vals_seen"] += 1
                if key in result["top_io"]:
                    result["top_io_duplicates"].append(record)
                else:
                    result["top_io"][key] = record
                result["stats"]["top_io"] += 1
                continue
            if section != "ops" or not line.lstrip().startswith('{"id":'):
                continue
            if '"kind": "kRegister"' in line:
                record = record_from_line(line)
                name = record.get("sym", "")
                key = normalize(name)
                if key in result["registers"]:
                    result["register_duplicates"].append(record)
                else:
                    result["registers"][key] = record
                result["stats"]["kRegister"] += 1
                continue
            kind = None
            for candidate in ("kLatch", "kSystemTask", "kSystemFunction",
                              "kDpicCall", "kDpicImport", "kInstance", "kBlackbox"):
                if f'"kind": "{candidate}"' in line:
                    kind = candidate
                    break
            if kind is None:
                continue
            record = record_from_line(line)
            result["stats"][kind] += 1
            if kind == "kLatch":
                result["latches"].append(record)
            elif kind == "kSystemTask":
                result["system_tasks"].append(record)
            elif kind == "kSystemFunction":
                result["system_functions"].append(record)
            elif kind == "kDpicCall":
                result["dpi_calls"].append(record)
            elif kind == "kDpicImport":
                result["dpi_imports"].append(record)
            elif kind == "kInstance":
                result["instances"].append(record)
            else:
                result["blackboxes"].append(record)
    result["stats"] = dict(sorted(result["stats"].items()))
    log(f"GRH anchor scan {source}: {result['stats']}")
    return result


def load_gsim_init(source: Path) -> dict:
    """Load memory and array-parent metadata from the Init graph.

    Split-map parents are not uniformly ``NODE_REG_SRC``: arrays that are
    wires are ``NODE_OTHERS``.  Keep every non-empty dimension node so the
    subsequent split-map filter can use parent IDs without assuming a node
    type.
    """
    array_nodes: dict[int, dict] = {}
    memories: dict[int, dict] = {}
    stats = Counter()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            if f'"type": "{MEMORY_TYPE}"' in line:
                record = record_from_line(line)
                memories[record["id"]] = record
                stats[f"type:{record.get('type')}"] += 1
                continue
            # This is only a cheap lexical filter; the Init graph has many
            # dimension=[] records that must not be retained.
            if '"dimension": [' not in line or '"dimension": []' in line:
                continue
            record = record_from_line(line)
            array_nodes[record["id"]] = record
            stats[f"array_type:{record.get('type')}"] += 1
    log(f"GSIM Init anchor scan {source}: {dict(stats)}")
    return {"array_nodes": array_nodes, "memories": memories,
            "stats": dict(sorted(stats.items()))}


def load_state_family_names(source: Path | None) -> set[str] | None:
    """Load the normalized parent symbols from an established family report.

    The report is intentionally a small, bounded input compared with the
    multi-gigabyte GRH/GSIM dumps.  ``None`` keeps the legacy GRH-name
    heuristic available for callers that do not have the F21 reference
    report.
    """
    if source is None:
        return None
    with source.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    families = payload.get("families", [])
    names = {
        normalize(family["symbol"])
        for family in families
        if isinstance(family, dict) and isinstance(family.get("symbol"), str)
    }
    if not names:
        raise ValueError(f"state-family report contains no family symbols: {source}")
    return names


def load_f20_stats(source: Path | None) -> dict:
    """Load the compact ordinary-register baseline from F20, when present."""
    if source is None:
        return {}
    report = source / "ordinary-register-name-join.json"
    if not report.exists():
        raise FileNotFoundError(f"F20 ordinary-register report not found: {report}")
    with report.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return {
        key: payload[key]
        for key in (
            "grh_plain", "gsim_plain", "matched", "width_mismatches",
            "grh_only", "gsim_only", "gsim_only_zero_width",
        )
        if key in payload
    }


def load_split_state_map(source: Path, init: dict, grh_before: dict | None = None,
                         state_family_names: set[str] | None = None,
                         candidate_names: set[str] | None = None,
                         candidate_member_ids: set[int] | None = None) -> dict:
    """Load only split families represented by GRH state registers.

    The split map also contains ordinary array-valued wires and ports.  A
    family is an anchor family when its normalized parent or at least one of
    its normalized member names occurs in the post-split GRH register set.
    This retains the 64 aggregate families as well as the 4,768 memberized
    families while excluding non-state arrays.
    """
    grh_names = set(grh_before["registers"]) if grh_before is not None else set()
    state_rows_by_parent: dict[int, list[dict]] = defaultdict(list)
    state_member_to_row: dict[int, dict] = {}
    state_parent_names: dict[int, str] = {}
    non_state_names: set[str] = set()
    stats = Counter()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.lstrip().startswith('{"parentId":'):
                continue
            stats["entries"] += 1
            record = record_from_line(line)
            parent_id = record.get("parentId")
            if parent_id not in init["array_nodes"]:
                continue
            parent_name = normalize(record.get("parentName", ""))
            member_name = normalize(record.get("memberName", ""))
            if state_family_names is not None:
                if parent_name not in state_family_names:
                    if candidate_names is not None and (
                            parent_name in candidate_names
                            or member_name in candidate_names):
                        member_id = record.get("memberId")
                        if (member_name in candidate_names
                                and (candidate_member_ids is None
                                     or member_id in candidate_member_ids)):
                            non_state_names.add(member_name)
                    stats["filtered_by_family_report"] += 1
                    continue
            elif (parent_id not in state_rows_by_parent
                  and parent_name not in grh_names
                  and member_name not in grh_names):
                # Do not retain rows for non-state arrays.  A later row in a
                # family can still activate the group through its member name.
                stats["non_state_entries"] += 1
                continue
            state_rows_by_parent[parent_id].append(record)
            state_member_to_row[record["memberId"]] = record
            state_parent_names[parent_id] = parent_name
            stats["state_entries"] += 1
    families = {}
    for parent_id, rows in state_rows_by_parent.items():
        parent = init["array_nodes"][parent_id]
        parent_name = state_parent_names[parent_id]
        key = f"{parent_name}#{parent_id}"
        families[key] = {
            "key": key,
            "parent_id": parent_id,
            "parent_name": parent_name,
            "parent_width": parent.get("width", rows[0].get("parentWidth")),
            "parent_dimension": parent.get("dimension", rows[0].get("parentDimension", [])),
            "rows": sorted(rows, key=lambda row: row["memberIndex"]),
        }
    stats["families"] = len(families)
    stats["members"] = sum(len(family["rows"]) for family in families.values())
    if state_family_names is not None:
        stats["family_report_names"] = len(state_family_names)
        stats["family_report_missing"] = len(state_family_names - {
            family["parent_name"] for family in families.values()
        })
    log(f"GSIM split state scan {source}: {dict(stats)}")
    return {"families": families, "member_to_row": state_member_to_row,
            "parent_to_family": {family["parent_id"]: key
                                 for key, family in families.items()},
            "non_state_names": non_state_names,
            "stats": dict(sorted(stats.items()))}


def collect_gsim_reg_names(source: Path) -> tuple[set[str], set[int]]:
    """Collect valid REG_SRC names for split-map residual classification.

    This is a lightweight first pass over the pre-DCE GSIM node section.  It
    lets the split-map loader retain only excluded-family names that are
    actual GRH or GSIM register anchors instead of materializing all 2M map
    entries.
    """
    names: set[str] = set()
    ids: set[int] = set()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if ('"type": "NODE_REG_SRC"' not in line
                    or '"status": "VALID_NODE"' not in line):
                continue
            record = record_from_line(line)
            name = normalize(record.get("name", ""))
            if name:
                names.add(name)
            if isinstance(record.get("id"), int):
                ids.add(record["id"])
    log(f"GSIM REG_SRC name scan {source}: {len(names)} names")
    return names, ids


def _scan_gsim_nodes(source: Path, split: dict, init: dict) -> dict:
    state_member_to_row = split["member_to_row"]
    state_parent_to_family = {
        family["parent_id"]: family["key"]
        for family in split["families"].values()
    }
    memory_parent_ids = set(init["memories"])
    memory_member_to_parent: dict[int, int] = {}
    for parent_id, record in init["memories"].items():
        for member_id in record.get("members", []):
            memory_member_to_parent[member_id] = parent_id

    result = {
        "state_indices": defaultdict(set),
        "state_parent_alive": set(),
        "state_records": {},
        "memory_parent_alive": set(),
        "memory_member_alive": set(),
        "memory_member_alive_ids": set(),
        "memory_direct_records": {},
        "reg_src": {},
        "reg_src_duplicates": [],
        "pipeline": [],
        "pipeline_rows": [],
        "pipeline_names": set(),
        "top_io": {},
        "top_io_duplicates": [],
        "special": [],
        "ext": defaultdict(list),
        "stats": Counter(),
    }
    state_ids = set(state_member_to_row) | set(state_parent_to_family)
    memory_ids = memory_parent_ids | set(memory_member_to_parent)
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            if '"type": "NODE_' not in line:
                continue
            match = RECORD_ID.match(line.lstrip())
            if match is None:
                continue
            node_id = int(match.group(1))
            node_type_known = any(f'"type": "{kind}"' in line for kind in
                                  (REG_SRC_TYPE, *TOP_IO_TYPES, *EXT_TYPES,
                                   "NODE_SPECIAL", MEMORY_TYPE))
            # Split members can be NODE_OTHERS.  Decode only those ordinary
            # nodes whose IDs are explicitly present in the split map.
            if node_id not in state_ids and node_id not in memory_ids and not node_type_known:
                continue
            record = record_from_line(line)
            if record.get("status") != "VALID_NODE":
                continue
            node_type = record.get("type")
            result["stats"][f"type:{node_type}"] += 1
            if node_id in state_member_to_row:
                row = state_member_to_row[node_id]
                family_key = split["parent_to_family"].get(row["parentId"])
                if family_key is not None:
                    result["state_indices"][family_key].add(row["memberIndex"])
                    result["state_records"][(family_key, row["memberIndex"])] = record
                continue
            if node_id in state_parent_to_family:
                result["state_parent_alive"].add(state_parent_to_family[node_id])
                continue
            if node_id in memory_parent_ids:
                result["memory_parent_alive"].add(node_id)
                result["memory_direct_records"][node_id] = record
                continue
            if node_id in memory_member_to_parent:
                result["memory_member_alive"].add(memory_member_to_parent[node_id])
                result["memory_member_alive_ids"].add(node_id)
                continue
            if node_type in TOP_IO_TYPES:
                key = normalize(record.get("name", ""))
                if key in result["top_io"]:
                    result["top_io_duplicates"].append(record)
                else:
                    result["top_io"][key] = record
                continue
            if node_type == "NODE_SPECIAL":
                result["special"].append(record)
                continue
            if node_type in EXT_TYPES:
                result["ext"][node_type].append(record)
                continue
            if node_type != REG_SRC_TYPE:
                continue
            if suffix_kind(record.get("name", "")) == "gsim_addr_pipeline":
                result["pipeline"].append(record)
                result["pipeline_rows"].append(record)
                result["pipeline_names"].add(normalize(record.get("name", "")))
                continue
            key = normalize(record.get("name", ""))
            if key in result["reg_src"]:
                result["reg_src_duplicates"].append(record)
            else:
                result["reg_src"][key] = record
    result["stats"] = dict(sorted(result["stats"].items()))
    log(f"GSIM anchor scan {source}: {result['stats']}")
    return result


def register_kind(record: dict) -> str:
    attrs = record.get("attrs", {})
    if MEMORY_PIPELINE_ATTR in attrs:
        return "memory_pipeline"
    if MEMORY_ATTR in attrs:
        return "memory_storage"
    return "register"


def grh_state_name_sets(grh: dict, split: dict) -> tuple[set[str], set[str]]:
    aggregate_names = set()
    member_names = set()
    for family in split["families"].values():
        parent_name = family["parent_name"]
        if parent_name in grh["registers"]:
            aggregate_names.add(parent_name)
        for row in family["rows"]:
            member_names.add(normalize(row["memberName"]))
    return aggregate_names, member_names


def grh_register_groups(grh: dict, split: dict) -> dict:
    aggregate_names, member_names = grh_state_name_sets(grh, split)
    non_state_names = split.get("non_state_names", set())
    groups = {
        "memory_storage": [],
        "memory_pipeline": [],
        "plain": [],
        "other_array": [],
        "state_aggregate": [],
    }
    for name, record in grh["registers"].items():
        kind = register_kind(record)
        if kind == "memory_storage":
            groups["memory_storage"].append(record)
        elif kind == "memory_pipeline":
            groups["memory_pipeline"].append(record)
        elif name in aggregate_names:
            groups["state_aggregate"].append(record)
        elif name in member_names:
            # Expanded below as one logical state member per split-map row.
            continue
        elif name in non_state_names or grh_shape(record):
            groups["other_array"].append(record)
        else:
            groups["plain"].append(record)
    groups["state_aggregate_names"] = aggregate_names
    groups["state_member_names"] = member_names
    return groups


def row_base(category: str, key: str, grh_name: str = "", gsim_name: str = "") -> dict:
    chosen = grh_name or gsim_name or key
    return {
        "category": category,
        "key": key,
        "grh_name": grh_name,
        "gsim_name": gsim_name,
        "module": module_name(chosen),
        "name_pattern": name_pattern(chosen),
    }


def mapped_row(category: str, key: str, grh_record: dict | None,
               gsim_record: dict | None, grh_alive: bool, gsim_alive: bool,
               reason: str = "") -> dict:
    grh_name = normalize(grh_record.get("sym", "")) if grh_record else ""
    gsim_name = normalize(gsim_record.get("name", "")) if gsim_record else ""
    row = row_base(category, key, grh_name, gsim_name)
    row.update({
        "relation": "1:1",
        "pairable": True,
        "grh_pre": bool(grh_record),
        "gsim_pre": bool(gsim_record),
        "grh_post": grh_alive,
        "gsim_post": gsim_alive,
        "survival": survival_label(grh_alive, gsim_alive),
        "grh_width": grh_width(grh_record),
        "gsim_width": gsim_record.get("width") if gsim_record else None,
        "grh_shape": grh_shape(grh_record),
        "gsim_dimension": gsim_record.get("dimension", []) if gsim_record else [],
        "width_match": (
            grh_record is not None and gsim_record is not None
            and grh_width(grh_record) == gsim_record.get("width")
        ),
        "shape_match": (
            grh_record is not None and gsim_record is not None
            and list(grh_shape(grh_record) or []) == list(gsim_record.get("dimension", []) or [])
        ),
        "reason": reason,
    })
    return row


_GSIM_EFFECT_SUFFIX = re.compile(
    r"^(.*)\$(ASSERT|PRINTF|STOP|FINISH|FATAL|WARNING|WARN|INFO)_(\d+)$"
)


def _grh_effect_kind(record: dict) -> str:
    """Return the GSIM special kind expected for a GRH effect operation."""
    kind = attr_value(record.get("attrs", {}), "firrtl.effectKind", "")
    return {
        "assert": "ASSERT",
        "assume": "ASSERT",
        "cover-hit": "PRINTF",
        "printf": "PRINTF",
        "stop": "STOP",
    }.get(str(kind), "")


def _grh_effect_key(record: dict) -> tuple[str, int, str] | None:
    """Build the stable module/line/kind identity for a GRH effect."""
    line = attr_value(record.get("attrs", {}), "firrtl.line")
    try:
        line = int(line)
    except (TypeError, ValueError):
        return None
    name = _grh_root_prefix(record.get("sym", ""))
    kind = _grh_effect_kind(record)
    if not name or line <= 0 or not kind:
        return None
    return name, line, kind


def _gsim_effect_key(record: dict) -> tuple[str, int, str] | None:
    """Build the module/lineno/kind key used by GSIM special nodes."""
    try:
        line = int(record.get("lineno", -1))
    except (TypeError, ValueError):
        return None
    name = normalize(record.get("name", ""))
    match = _GSIM_EFFECT_SUFFIX.match(name)
    if line <= 0:
        return None
    if match is not None:
        return match.group(1), line, match.group(2)
    # Named FIRRTL effects use the source label instead of an ASSERT/PRINTF/
    # STOP suffix (for example ``cpu$stop``).  The final component still
    # identifies the effect module path; retain CUSTOM for labels whose kind
    # cannot be inferred from the spelling.
    if "$" not in name:
        return None
    module, label = name.rsplit("$", 1)
    kind = {
        "assert": "ASSERT", "assume": "ASSERT", "printf": "PRINTF",
        "stop": "STOP", "finish": "STOP", "fatal": "ASSERT",
    }.get(label.lower(), "CUSTOM")
    return module, line, kind


def _effect_side_row(category: str, rule: str, side: str, record: dict,
                     post: bool, reason: str, key: str = "") -> dict:
    """Create a non-pairable effect row with an explicit missing-side reason."""
    if side == "grh":
        name = normalize(record.get("sym", ""))
        grh_name, gsim_name = name, ""
        grh_pre, gsim_pre = True, False
        grh_post, gsim_post = bool(post), False
        line = attr_value(record.get("attrs", {}), "firrtl.line", "")
        kind = attr_value(record.get("attrs", {}), "firrtl.effectKind", "")
        gsim_line = ""
    else:
        name = normalize(record.get("name", ""))
        grh_name, gsim_name = "", name
        grh_pre, gsim_pre = False, True
        grh_post, gsim_post = False, bool(post)
        line = ""
        kind = _gsim_effect_key(record)[2] if _gsim_effect_key(record) else ""
        gsim_line = record.get("lineno", "")
    row = row_base(category, key or f"{side}:{name}", grh_name, gsim_name)
    row.update({
        "relation": "effect-line-identity",
        "rule": rule,
        "side": side,
        "pairable": False,
        "grh_pre": grh_pre,
        "gsim_pre": gsim_pre,
        "grh_post": grh_post,
        "gsim_post": gsim_post,
        "survival": "not_pairable",
        "side_post": bool(post),
        "effect_kind": kind,
        "module_path": _grh_root_prefix(grh_name or gsim_name),
        "grh_line": line,
        "gsim_lineno": gsim_line,
        "reason": reason,
    })
    return row


def build_effect_identity(grh_before: dict, grh_after: dict,
                          gsim_before: dict, gsim_after: dict) -> tuple[list[dict], dict]:
    """Pair FIRRTL effects by module path, statement line, and effect kind.

    GRH kSystemTask carries ``firrtl.line`` and ``firrtl.effectKind``. GSIM
    special nodes carry the same parser line in ``lineno`` and encode the
    effect kind in their ASSERT/PRINTF/STOP suffix. DPI and ext-boundary rows
    without that evidence remain explicit, non-pairable rows.
    """
    grh_entries = []
    for category, records in (
        ("system_task_effect", grh_before.get("system_tasks", [])),
        ("dpi_effect", grh_before.get("dpi_calls", [])),
        ("dpi_boundary", grh_before.get("dpi_imports", [])),
        ("ext_boundary", grh_before.get("instances", []) + grh_before.get("blackboxes", [])),
    ):
        for record in records:
            grh_entries.append((category, record))

    gsim_entries = []
    for record in gsim_before.get("special", []):
        gsim_entries.append(("system_task_effect", "special", record))
    for node_type, records in gsim_before.get("ext", {}).items():
        for record in records:
            gsim_entries.append(("dpi_effect" if node_type == "NODE_EXT" else "dpi_boundary",
                                 node_type, record))

    gsim_by_key: defaultdict[tuple[str, int, str], list[tuple[str, dict]]] = defaultdict(list)
    for category, node_type, record in gsim_entries:
        key = _gsim_effect_key(record)
        if key is not None:
            gsim_by_key[(key[0], key[1], key[2])].append((node_type, record))

    grh_after_names = {
        category: {normalize(record.get("sym", "")) for record in records}
        for category, records in (
            ("system_task_effect", grh_after.get("system_tasks", [])),
            ("dpi_effect", grh_after.get("dpi_calls", [])),
            ("dpi_boundary", grh_after.get("dpi_imports", [])),
            ("ext_boundary", grh_after.get("instances", []) + grh_after.get("blackboxes", [])),
        )
    }
    gsim_after_names = {
        category: {normalize(record.get("name", "")) for record in records}
        for category, records in (
            ("system_task_effect", gsim_after.get("special", [])),
            ("dpi_effect", gsim_after.get("ext", {}).get("NODE_EXT", [])),
            ("dpi_boundary", gsim_after.get("ext", {}).get("NODE_EXT_IN", []) +
             gsim_after.get("ext", {}).get("NODE_EXT_OUT", [])),
        )
    }

    rows: list[dict] = []
    used_gsim: set[int] = set()
    pairs = 0
    unmatched_grh = Counter()
    unmatched_gsim = Counter()
    survival = Counter()
    for category, record in grh_entries:
        grh_name = normalize(record.get("sym", ""))
        key = _grh_effect_key(record)
        candidates = []
        if key is not None:
            candidates = [entry for entry in gsim_by_key.get(key, [])
                          if id(entry[1]) not in used_gsim and
                          (category == "system_task_effect" and entry[0] == "special" or
                           category == "dpi_effect" and entry[0] == "NODE_EXT" or
                           category == "dpi_boundary" and entry[0] in {"NODE_EXT_IN", "NODE_EXT_OUT"} or
                           category == "ext_boundary" and entry[0] == "NODE_EXT")]
        if len(candidates) == 1:
            _node_type, gsim_record = candidates[0]
            used_gsim.add(id(gsim_record))
            gsim_name = normalize(gsim_record.get("name", ""))
            grh_post = grh_name in grh_after_names.get(category, set())
            gsim_post = gsim_name in gsim_after_names.get(category, set())
            status = survival_label(grh_post, gsim_post)
            row = row_base(category, f"line:{key[0]}:{key[1]}:{key[2]}", grh_name, gsim_name)
            row.update({
                "relation": "1:1", "rule": "effect_line_identity", "side": "paired",
                "pairable": True, "grh_pre": True, "gsim_pre": True,
                "grh_post": grh_post, "gsim_post": gsim_post,
                "survival": status, "side_post": "",
                "effect_kind": key[2], "module_path": key[0],
                "grh_line": key[1], "gsim_lineno": gsim_record.get("lineno", ""),
                "reason": "module path + FIRRTL line + effect kind",
            })
            rows.append(row)
            pairs += 1
            survival[status] += 1
        else:
            reason = (
                "missing firrtl.line/effect kind evidence" if key is None else
                "no unique GSIM special/ext node at module path + FIRRTL line + effect kind"
            )
            rows.append(_effect_side_row(
                category, "effect_line_identity", "grh", record,
                grh_name in grh_after_names.get(category, set()), reason,
                f"grh:{grh_name}"))
            unmatched_grh[category] += 1

    for category, node_type, record in gsim_entries:
        if id(record) in used_gsim:
            continue
        name = normalize(record.get("name", ""))
        key = _gsim_effect_key(record)
        reason = (
            "GSIM special/ext node has no recognizable effect line/module suffix" if key is None else
            "no GRH effect op has matching module path + FIRRTL line + effect kind"
        )
        rows.append(_effect_side_row(
            category, "effect_line_identity", "gsim", record,
            name in gsim_after_names.get(category, set()), reason,
            f"gsim:{name}"))
        unmatched_gsim[category] += 1

    return rows, {
        "rows": len(rows), "pairs": pairs,
        "unmatched_grh": sum(unmatched_grh.values()),
        "unmatched_gsim": sum(unmatched_gsim.values()),
        "unmatched_grh_by_category": counter_dict(unmatched_grh),
        "unmatched_gsim_by_category": counter_dict(unmatched_gsim),
        "survival": complete_survival(survival),
        "pairable": pairs,
        "not_pairable": len(rows) - pairs,
    }


def top_modules(rows: list[dict], limit: int = 20) -> list[dict]:
    counts = Counter((row.get("module", "<top>"), row.get("name_pattern", "")) for row in rows)
    return [
        {"module": module, "name_pattern": pattern, "count": count}
        for (module, pattern), count in counts.most_common(limit)
    ]


def _grh_root_prefix(name: str) -> str:
    """Return the stable module/operation prefix used for root matching."""
    value = normalize(name)
    value = re.sub(r"\$_op_\d+$", "", value)
    return value


def _gsim_special_prefix(name: str) -> str:
    """Strip a GSIM effect suffix (ASSERT/PRINTF/FINISH/...) from a root."""
    value = normalize(name)
    match = re.match(
        r"^(.*)\$(?:ASSERT|PRINTF|FINISH|STOP|FATAL|WARNING|WARN|INFO|DISPLAY)(?:_|$)",
        value,
    )
    return match.group(1) if match else value


def _root_catalog(gsim_before: dict | None, gsim_after: dict | None) -> dict:
    """Build name/prefix indexes for GSIM effect and boundary roots.

    A GSIM NODE_SPECIAL does not carry the GRH operation id.  Prefix matching
    therefore records the evidence level explicitly; callers must not infer a
    one-to-one root identity when no prefix match exists.
    """
    gsim_before = gsim_before or {}
    gsim_after = gsim_after or {}
    special_before = list(gsim_before.get("special", []))
    special_after = list(gsim_after.get("special", []))
    special_after_names = {normalize(row.get("name", "")) for row in special_after}
    special_by_prefix: defaultdict[str, list[dict]] = defaultdict(list)
    for row in special_before:
        name = normalize(row.get("name", ""))
        special_by_prefix[_gsim_special_prefix(name)].append(row)
    ext_before = [row for rows in gsim_before.get("ext", {}).values() for row in rows]
    ext_after = [row for rows in gsim_after.get("ext", {}).values() for row in rows]
    ext_after_names = {normalize(row.get("name", "")) for row in ext_after}
    ext_by_prefix: defaultdict[str, list[dict]] = defaultdict(list)
    for row in ext_before:
        name = normalize(row.get("name", ""))
        ext_by_prefix[name].append(row)
    top_io_before = list((gsim_before.get("top_io") or {}).values())
    top_io_after = list((gsim_after.get("top_io") or {}).values())
    top_io_after_names = {normalize(row.get("name", "")) for row in top_io_after}
    return {
        "special_by_prefix": special_by_prefix,
        "special_after_names": special_after_names,
        "ext_by_prefix": ext_by_prefix,
        "ext_after_names": ext_after_names,
        "top_io_after_names": top_io_after_names,
        "special_pre_count": len(special_before),
        "special_post_count": len(special_after),
        "ext_pre_count": len(ext_before),
        "ext_post_count": len(ext_after),
        "top_io_pre_count": len(top_io_before),
        "top_io_post_count": len(top_io_after),
    }


def _map_grh_root(trace: dict, catalog: dict) -> dict:
    """Map one traced GRH root to a GSIM root, conservatively.

    Prefix matches establish that a corresponding GSIM root is present in the
    dump.  A missing prefix is reported as unresolved evidence rather than
    being treated as a legitimate representation difference.
    """
    root_kind = trace.get("root", "")
    path = trace.get("path", []) or []
    root_entry = path[-1] if path else {}
    root_name = root_entry.get("symbol") or ""
    prefix = _grh_root_prefix(root_name)
    result = {
        "gsim_root_kind": "",
        "gsim_root_name": "",
        "gsim_root_alive": None,
        "root_mapping": "unresolved:root has no stable serialized GSIM key",
        "root_prefix": prefix,
    }
    if root_kind == "port":
        normalized = normalize(root_name)
        if normalized in catalog["top_io_after_names"]:
            result.update({
                "gsim_root_kind": "top_io",
                "gsim_root_name": normalized,
                "gsim_root_alive": True,
                "root_mapping": "normalized top-level I/O name",
            })
        else:
            result["root_mapping"] = "unresolved:GRH port has no GSIM top-I/O name"
        return result
    if root_kind == "kSystemTask":
        matches = catalog["special_by_prefix"].get(prefix, [])
        if matches:
            names = [normalize(row.get("name", "")) for row in matches]
            alive = [name for name in names if name in catalog["special_after_names"]]
            result.update({
                "gsim_root_kind": "NODE_SPECIAL",
                "gsim_root_name": ",".join(alive or names[:8]),
                "gsim_root_alive": bool(alive),
                "root_mapping": "GSIM NODE_SPECIAL prefix matched GRH kSystemTask module/op prefix",
            })
        else:
            result["root_mapping"] = (
                "unresolved:no GSIM NODE_SPECIAL with the GRH kSystemTask module/op prefix"
            )
        return result
    if root_kind in {"kDpicCall", "kDpicImport", "kSystemFunction", "kInstance", "kBlackbox"}:
        matches = catalog["ext_by_prefix"].get(prefix, [])
        if matches:
            names = [normalize(row.get("name", "")) for row in matches]
            alive = [name for name in names if name in catalog["ext_after_names"]]
            result.update({
                "gsim_root_kind": "NODE_EXT/NODE_EXT_IN_OUT",
                "gsim_root_name": ",".join(alive or names[:8]),
                "gsim_root_alive": bool(alive),
                "root_mapping": "GSIM ext-module/boundary prefix matched GRH effect root",
            })
        else:
            result["root_mapping"] = (
                "unresolved:no GSIM ext-module/boundary name has the GRH effect-root prefix"
            )
        return result
    result["root_mapping"] = f"unresolved:unsupported GRH root kind {root_kind or '<empty>'}"
    return result


def _representation_reason(row: dict) -> str | None:
    """Return an evidence-backed legitimate representation reason."""
    name = row.get("grh_name", "")
    if row.get("category") == "sv_or_grh_only_register" and (
            "$implementation$" in name or "$helper$implementation$" in name):
        return (
            "SV/blackbox implementation internals are not serialized as GSIM REG_SRC; "
            "GSIM exposes the enclosing implementation as an ext-module boundary"
        )
    if row.get("category") == "memory_pipeline" and row.get("grh_post") and row.get("gsim_post"):
        return "GRH memory data-delay role paired with a live GSIM address-delay register"
    return None


def _path_divergence_probe(trace: dict) -> dict:
    """Record the first GRH operation on the traced dependency path.

    The probe is deliberately evidence-only: it does not claim that this
    operation is the GSIM divergence until a GSIM dependency walk establishes
    the counterpart.  The ledger therefore uses an unresolved verdict when
    the counterpart walk is unavailable.
    """
    path = trace.get("path", []) or []
    state_kinds = {
        "kRegister", "kRegisterReadPort", "kRegisterReadArrayPort",
        "kRegisterWritePort", "kRegisterWriteMaskPort",
        "kRegisterWriteArrayPort", "kRegisterWriteArrayMaskPort",
        "kRegisterFillPort", "kLatch", "kLatchReadPort", "kLatchWritePort",
    }
    first_op = next(
        (entry for entry in path
         if entry.get("entity") == "op" and entry.get("kind") not in state_kinds),
        None,
    )
    if first_op is None:
        return {
            "divergence_op_id": "",
            "divergence_kind": "",
            "divergence_semantic_id": "",
            "divergence_lineno": "",
            "divergence_source": "",
            "mechanism": "gsim_dependency_unresolved",
        }
    semantic_ids = first_op.get("semanticIds", []) or []
    return {
        "divergence_op_id": first_op.get("id", ""),
        "divergence_kind": first_op.get("kind", ""),
        "divergence_semantic_id": semantic_ids[0] if semantic_ids else "",
        "divergence_lineno": first_op.get("lineno", ""),
        "divergence_source": "GRH path probe only; GSIM counterpart/dependency walk not established",
        "mechanism": f"gsim_dependency_unresolved:{first_op.get('kind', 'unknown')}",
    }


def mechanism_representatives(rows: list[dict]) -> dict:
    """Return one deterministic ledger example for every mechanism.

    ``top_mechanism_examples`` is intentionally bounded for the large report,
    but a bounded prefix can omit low-frequency mechanisms.  The mechanism
    table needs a representative for every observed bucket, so keep the first
    row in ledger order for each non-empty mechanism.
    """
    representatives = {}
    for row in rows:
        mechanism = str(row.get("mechanism", ""))
        if not mechanism or mechanism in representatives:
            continue
        representatives[mechanism] = {
            "name": row.get("grh_name", ""),
            "divergence_kind": row.get("divergence_kind", ""),
            "divergence_op_id": row.get("divergence_op_id", ""),
            "divergence_semantic_id": row.get("divergence_semantic_id", ""),
            "divergence_lineno": row.get("divergence_lineno", ""),
        }
    return dict(sorted(representatives.items()))


def build_grh_extra_justification(grh_after_path: Path, rows: list[dict],
                                  output_dir: Path,
                                  gsim_before: dict | None = None,
                                  gsim_after: dict | None = None) -> tuple[list[dict], dict]:
    """Build the asymmetric GRH-retention ledger.

    A root reached in GRH is evidence that the GRH liveness walk retained the
    row; it is not evidence of a legitimate difference.  The row is
    legitimate only for an explicit representation rule.  Otherwise the
    GSIM root mapping and dependency divergence must be established; when the
    serialized inputs do not establish that walk the row remains unresolved.
    Pre-DCE-only rows are counted separately and never enter the retention
    ledger.
    """
    pre_only = [row for row in rows
                if row.get("grh_pre") and not row.get("grh_post")]
    role_pair_dropped = [row for row in rows
                         if row.get("category") == "memory_pipeline"
                         and row.get("grh_post") and row.get("gsim_post")]
    live_rows = [row for row in rows
                 if row.get("grh_post")
                 and row not in role_pair_dropped]
    targets = sorted({row.get("grh_name", "") for row in live_rows
                      if row.get("grh_name")})
    scratch = output_dir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    names_path = scratch / "grh-extra-trace-names.txt"
    candidates_path = scratch / "grh-extra-trace-candidates.txt"
    unmatched_path = scratch / "grh-extra-trace-unmatched.txt"
    trace_path = output_dir / "grh-extra-trace.json"
    names_path.write_text("\n".join(targets) + ("\n" if targets else ""), encoding="utf-8")
    candidates_path.write_text("\n", encoding="utf-8")
    unmatched_path.write_text("\n", encoding="utf-8")
    trace_report = {}
    trace_error = ""
    if targets:
        try:
            from trace_f21_retained import trace_grh
            trace_report = trace_grh(
                grh_after_path, candidates_path, unmatched_path, names_path,
                trace_path, 160, direct_state_symbols=True,
            )
        except Exception as exc:  # a bounded unresolved record is preferable to losing the report
            trace_error = f"{type(exc).__name__}: {exc}"
            trace_path.write_text(json.dumps({"error": trace_error}, indent=2) + "\n", encoding="utf-8")
    target_reports = trace_report.get("targets", {})
    catalog = _root_catalog(gsim_before, gsim_after)
    justified = []
    for row in live_rows:
        name = row.get("grh_name", "")
        item = dict(row)
        item["root_kind"] = ""
        item["root_name"] = ""
        item["path_length"] = ""
        item["cycle_check"] = "not_checked"
        item["cycle_only"] = False
        item["cycle_state_symbols"] = []
        item["gsim_root_kind"] = ""
        item["gsim_root_name"] = ""
        item["gsim_root_alive"] = ""
        item["root_mapping"] = ""
        item["divergence_op_id"] = ""
        item["divergence_kind"] = ""
        item["divergence_semantic_id"] = ""
        item["divergence_lineno"] = ""
        item["divergence_source"] = ""
        item["verdict"] = "unresolved"
        item["verdict_reason"] = ""
        traced = target_reports.get(name)
        if traced is None:
            item["cycle_check"] = "trace_failed" if trace_error else "no_root_found"
            item["cycle_only"] = False
            item["mechanism"] = "trace_unresolved"
            item["verdict_reason"] = (
                f"{trace_error}" if trace_error else
                "GRH post-DCE row is present but no root path was returned"
            )
            justified.append(item)
            continue

        path = traced.get("path", []) or []
        state_symbols = [entry.get("storageSymbol") for entry in path
                         if entry.get("storageSymbol")]
        repeated_state = len(state_symbols) != len(set(state_symbols))
        item["root_kind"] = traced.get("root", "")
        item["root_name"] = (path[-1].get("symbol") if path else "") or traced.get("root", "")
        item["path_length"] = traced.get("entities", len(path))
        item["cycle_state_symbols"] = sorted(set(state_symbols))
        item["cycle_check"] = (
            "state-symbol-repeat-but-root-reached" if repeated_state
            else "no-state-cycle-on-root-path"
        )
        # A path that reaches an approved effect/port root is not cycle-only;
        # a repeated state symbol is retained as an explicit diagnostic.
        item["cycle_only"] = False
        item.update(_map_grh_root(traced, catalog))
        probe = _path_divergence_probe(traced)
        item.update(probe)

        representation_reason = _representation_reason(row)
        if representation_reason is not None:
            item["verdict"] = "legitimate:representation_boundary"
            item["verdict_reason"] = representation_reason
            item["mechanism"] = "representation_boundary"
        elif item.get("gsim_root_alive") is True:
            # The GSIM root is live, but the serialized inputs do not yet
            # establish the first non-dependent GSIM counterpart operation.
            # Keep the required asymmetric verdict conservative: this is not
            # called legitimate, and the missing divergence evidence is named.
            item["verdict"] = "unresolved"
            item["verdict_reason"] = (
                "GSIM corresponding root is alive while the GRH row is absent "
                "from GSIM; first GRH/GSIM dependency divergence is not established "
                "from the serialized GSIM node dump"
            )
        elif item.get("gsim_root_alive") is False:
            item["verdict"] = "unresolved"
            item["verdict_reason"] = (
                "the mapped GSIM root prefix has no live post-DCE root, but no "
                "approved representation reason was established for this GRH row"
            )
            item["mechanism"] = "root_absent_without_representation_reason"
        else:
            item["verdict"] = "unresolved"
            item["verdict_reason"] = item.get("root_mapping", "root mapping unavailable")
            item["mechanism"] = "root_mapping_unresolved"
        justified.append(item)
    verdict_counts = Counter(item["verdict"] for item in justified)
    # Keep the three closure terms explicit in machine-readable output even
    # when one term is zero for this checkpoint.
    verdict_counts.setdefault("optimization-gap", 0)
    mechanisms = Counter(item.get("mechanism", "") for item in justified)
    optimization_mechanisms = Counter(
        item.get("mechanism", "") for item in justified
        if str(item.get("verdict", "")).startswith("optimization-gap")
    )
    unresolved_reasons = Counter(
        item.get("mechanism", "unresolved") for item in justified
        if item.get("verdict") == "unresolved"
    )
    root_mapping_counts = Counter(
        f"{item.get('root_kind', '')}:{item.get('gsim_root_alive', '')}"
        for item in justified
    )
    return justified, {
        "total": len(justified),
        "verdict_counts": counter_dict(verdict_counts),
        "optimization_gap_mechanisms": counter_dict(optimization_mechanisms),
        "mechanism_counts": counter_dict(mechanisms),
        "mechanism_representatives": mechanism_representatives(justified),
        "unresolved_mechanisms": counter_dict(unresolved_reasons),
        "root_mapping_counts": counter_dict(root_mapping_counts),
        "trace_targets": len(targets),
        "trace_error": trace_error,
        "trace_path": str(trace_path),
        "pre_dce_only_deleted_by_grh_dce": {
            "total": len(pre_only),
            "by_category": counter_dict(Counter(row.get("category", "") for row in pre_only)),
        },
        "dropped_live_role_pairs": {
            "total": len(role_pair_dropped),
            "by_category": counter_dict(Counter(row.get("category", "") for row in role_pair_dropped)),
        },
        "top_optimization_gap_examples": [
            {"mechanism": item.get("mechanism", ""), "name": item.get("grh_name", "")}
            for item in justified if item["verdict"] == "optimization-gap"
        ][:20],
        "top_mechanism_examples": [
            {"mechanism": item.get("mechanism", ""), "name": item.get("grh_name", ""),
             "divergence_kind": item.get("divergence_kind", "")}
            for item in justified
        ][:50],
        "mechanism_locations": {
            "gsim_dependency_unresolved:kConcat": "wolvrix/lib/transform/split_static_array.cpp:483-544; wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kSliceStatic": "wolvrix/lib/transform/split_static_array.cpp:188-214, 483-544; wolvrix/lib/transform/simplify.cpp:90-122",
            "gsim_dependency_unresolved:kMux": "wolvrix/lib/transform/simplify.cpp:90-122; wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kAssign": "wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kAnd": "wolvrix/lib/transform/simplify.cpp:90-122; wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kRegisterReadPort": "wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kRegisterReadArrayPort": "wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kEq": "wolvrix/lib/transform/simplify.cpp:90-122; wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "gsim_dependency_unresolved:kOr": "wolvrix/lib/transform/simplify.cpp:90-122; wolvrix/lib/transform/dead_code_elim.cpp:664-690",
            "root_mapping_unresolved": "wolvrix/lib/transform/dead_code_elim.cpp:598-704 (root-mask propagation)",
        },
    }


def write_tsv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\t".join(columns) + "\n")
        for row in rows:
            values = []
            for column in columns:
                value = row.get(column, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, sort_keys=True, separators=(",", ":"))
                elif value is None:
                    value = ""
                values.append(str(value).replace("\t", " ").replace("\n", " "))
            stream.write("\t".join(values) + "\n")


def counter_dict(counter: Counter) -> dict:
    return dict(sorted(counter.items()))


def complete_survival(counter: Counter) -> dict:
    """Emit all four survival states, including zero-count states."""
    return {
        state: int(counter.get(state, 0))
        for state in ("both_alive", "grh_only", "gsim_only", "both_dead")
    }


def make_report(args) -> dict:
    started = time.monotonic()
    grh_before = collect_grh(args.grh_before)
    grh_after = collect_grh(args.grh_after)
    init = load_gsim_init(args.gsim_init)
    split = load_split_state_map(args.gsim_split_map, init)
    gsim_before = _scan_gsim_nodes(args.gsim_before, split, init)
    gsim_after = _scan_gsim_nodes(args.gsim_after, split, init)
    grh_before_groups = grh_register_groups(grh_before, split)
    grh_after_groups = grh_register_groups(grh_after, split)
    one_to_one: list[dict] = []
    n_m_rows: list[dict] = []
    one_sided: list[dict] = []
    unexplained: list[dict] = []
    rule_specs: list[dict] = []

    def add_one_sided(category: str, side: str, record: dict, reason: str):
        name = normalize(record.get("sym", record.get("name", "")))
        row = row_base(category, f"{side}:{name}",
                       name if side == "grh" else "",
                       name if side == "gsim" else "")
        row.update({
            "relation": "one-sided-known",
            "side": side,
            "grh_pre": side == "grh",
            "gsim_pre": side == "gsim",
            "grh_post": side == "grh",
            "gsim_post": side == "gsim",
            "survival": "grh_only" if side == "grh" else "gsim_only",
            "grh_width": attr_value(record.get("attrs", {}), "width") if side == "grh" else "",
            "gsim_width": record.get("width", "") if side == "gsim" else "",
            "reason": reason,
        })
        one_sided.append(row)

    def add_unexplained(category: str, side: str, record: dict, reason: str):
        name = normalize(record.get("sym", record.get("name", "")))
        row = row_base(category, f"{side}:{name}",
                       name if side == "grh" else "",
                       name if side == "gsim" else "")
        row.update({"relation": "unexplained", "side": side,
                    "reason": reason,
                    "grh_pre": side == "grh", "gsim_pre": side == "gsim"})
        unexplained.append(row)

    # Exact ordinary-register name join. Generated and state representations
    # are removed before this join.
    grh_plain = {normalize(row.get("sym", "")): row
                 for row in grh_before_groups["plain"]}
    grh_plain_after = {normalize(row.get("sym", "")): row
                       for row in grh_after_groups["plain"]}
    gsim_plain = gsim_before["plain"]
    gsim_plain_after = gsim_after["plain"]
    for key in sorted(set(grh_plain) & set(gsim_plain)):
        row = mapped_row("plain_register", key, grh_plain[key], gsim_plain[key],
                         key in grh_plain_after, key in gsim_plain_after,
                         "normalized exact register name (GSIM $$ -> GRH __DOT__)")
        one_to_one.append(row)
    for key in sorted(set(grh_plain) - set(gsim_plain)):
        add_one_sided("sv_or_grh_only_register", "grh", grh_plain[key],
                      "no normalized GSIM REG_SRC; F20 baseline treats the 15 residual GRH registers as SV state when count is 15")
    known_gsim = set()
    for records in gsim_before["generated"].values():
        for record in records:
            known_gsim.add(normalize(record.get("name", "")))
            add_one_sided("generated_gsim_register", "gsim", record,
                          generated_reg_reason(record) or "known GSIM generated register")
    for key in sorted(set(gsim_plain) - set(grh_plain) - known_gsim):
        add_unexplained("plain_register", "gsim", gsim_plain[key],
                        "scalar REG_SRC has no GRH normalized-name match and no established generated-register rule")

    # State member expansion.  An aggregate GRH declaration is conservatively
    # treated as all members alive; this is the established 64-family fallback.
    state_grh_pre = grh_before["registers"]
    state_grh_post = grh_after["registers"]
    for family_key, family in sorted(split["families"].items()):
        grh_aggregate = family["parent_name"] in state_grh_pre
        grh_aggregate_after = family["parent_name"] in state_grh_post
        gsim_indices_before = set(gsim_before["state_indices"].get(family_key, set()))
        gsim_indices_after = set(gsim_after["state_indices"].get(family_key, set()))
        if family_key in gsim_before["state_parent_alive"]:
            gsim_indices_before = {row["memberIndex"] for row in family["rows"]}
        if family_key in gsim_after["state_parent_alive"]:
            gsim_indices_after = {row["memberIndex"] for row in family["rows"]}
        for split_row in family["rows"]:
            index = split_row["memberIndex"]
            member_name = normalize(split_row["memberName"])
            grh_record = state_grh_pre.get(member_name) or (
                state_grh_pre.get(family["parent_name"]) if grh_aggregate else None)
            grh_after_record = state_grh_post.get(member_name) or (
                state_grh_post.get(family["parent_name"]) if grh_aggregate_after else None)
            gsim_record = gsim_before["state_records"].get((family_key, index))
            key = f"{family_key}:{index}"
            grh_alive = grh_after_record is not None
            gsim_alive = index in gsim_indices_after
            if grh_record is not None and (gsim_record is not None or index in gsim_indices_before):
                row = mapped_row("array_state_member", key, grh_record,
                                 gsim_record, grh_alive, gsim_alive,
                                 "explicit split-array parent/member index")
                row["member_index"] = index
                row["parent_name"] = family["parent_name"]
                row["grh_representation"] = "aggregate" if member_name not in state_grh_pre else "member"
                row["gsim_member_name"] = member_name
                row["gsim_width"] = (
                    gsim_record.get("width") if gsim_record else split_row.get("memberWidth")
                )
                row["width_match"] = (
                    attr_value(grh_record.get("attrs", {}), "width") is not None
                    and row["gsim_width"] is not None
                    and attr_value(grh_record.get("attrs", {}), "width")
                    == row["gsim_width"] * max(1, shape_count(family["parent_dimension"]))
                    if row["grh_representation"] == "aggregate" else
                    attr_value(grh_record.get("attrs", {}), "width") == row["gsim_width"]
                )
                one_to_one.append(row)
            elif grh_record is not None:
                add_one_sided("array_state_member", "grh", grh_record,
                              "state split-map member has no valid GSIM pre-DCE member")
            elif gsim_record is not None or index in gsim_indices_before:
                add_one_sided("array_state_member", "gsim", gsim_record or split_row,
                              "state split-map member has no GRH member/aggregate declaration")
            else:
                add_unexplained("array_state_member", "gsim", split_row,
                                "split-map row is absent from both serialized pre-DCE node views")

    def add_rule(name: str, category: str, grh_items: list[dict],
                 gsim_items: list[dict], reason: str,
                 grh_after_items: list[dict] | None = None,
                 gsim_after_items: list[dict] | None = None,
                 grh_key=lambda row: normalize(row.get("sym", "")),
                 gsim_key=lambda row: normalize(row.get("name", ""))):
        grh_after_items = grh_after_items or []
        gsim_after_items = gsim_after_items or []
        grh_after_keys = {grh_key(row) for row in grh_after_items}
        gsim_after_keys = {gsim_key(row) for row in gsim_after_items}
        for row in grh_items:
            key = grh_key(row)
            out = row_base(category, f"{name}:grh:{key}", key, "")
            out.update({"relation": "n:m-rule", "rule": name, "side": "grh",
                        "grh_pre": True, "gsim_pre": False,
                        "grh_post": key in grh_after_keys, "gsim_post": False,
                        "survival": "grh_only" if key in grh_after_keys else "both_dead",
                        "reason": reason,
                        "width": attr_value(row.get("attrs", {}), "width"),
                        "shape": attr_value(row.get("attrs", {}), "shape", [])})
            n_m_rows.append(out)
        for row in gsim_items:
            key = gsim_key(row)
            out = row_base(category, f"{name}:gsim:{key}", "", key)
            out.update({"relation": "n:m-rule", "rule": name, "side": "gsim",
                        "grh_pre": False, "gsim_pre": True,
                        "grh_post": False, "gsim_post": key in gsim_after_keys,
                        "survival": "gsim_only" if key in gsim_after_keys else "both_dead",
                        "reason": reason,
                        "width": row.get("width"),
                        "shape": row.get("dimension", [])})
            n_m_rows.append(out)
        rule_specs.append({
            "rule": name,
            "category": category,
            "grh_pre": len(grh_items),
            "gsim_pre": len(gsim_items),
            "grh_post": len(grh_after_items),
            "gsim_post": len(gsim_after_items),
            "reason": reason,
        })

    # Memory storage is intentionally a count/depth rule.  GSIM starts with
    # NODE_MEMORY and depth-one entries that become REG_SRC/field registers.
    grh_mem_pre = grh_before_groups["memory_storage"]
    grh_mem_post = grh_after_groups["memory_storage"]
    gsim_mem_pre = list(init["memories"].values())
    gsim_mem_post = [record for record in gsim_mem_pre
                     if record["id"] in gsim_after["memory_parent_alive"]
                     or record["id"] in gsim_after["memory_member_alive"]]
    add_rule("memory_storage_depth1_conversion", "memory_storage",
             grh_mem_pre, gsim_mem_pre, grh_mem_post, gsim_mem_post,
             "GRH firrtl.memory storage ↔ GSIM NODE_MEMORY; depth-one GSIM memory is represented by REG_SRC/field registers, so identity is count/depth rule only")

    # Memory read address pipeline is a count/role rule.  The suffix is a GSIM
    # implementation role, not an exact GRH symbol key.
    add_rule("memory_pipeline_addr_role", "memory_pipeline",
             grh_before_groups["memory_pipeline"], gsim_before["pipeline"],
             "488 GRH firrtl.memoryPipeline registers ↔ 488 GSIM __DOT__ADDR REG_SRC candidates; count and role are reported without semantic 1:1 claim",
             grh_after_groups["memory_pipeline"], gsim_after["pipeline"])

    # GSIM specials are exactly the RemoveDeadNodes special roots; GRH tasks
    # are the corresponding effect operations, but names/roles are not stable.
    add_rule("system_task_special_root", "system_task_effect",
             grh_before["system_tasks"], gsim_before["special"],
             "GRH kSystemTask ↔ GSIM NODE_SPECIAL root; equal count is count-only and does not prove task identity",
             grh_after["system_tasks"], gsim_after["special"],
             grh_key=lambda row: str(row.get("id")),
             gsim_key=lambda row: str(row.get("id")))

    add_rule("dpi_call_ext_module", "dpi_effect",
             grh_before["dpi_calls"], gsim_before["ext"].get("NODE_EXT", []),
             "GRH kDpicCall is represented through GSIM external-module roots; call/module counts differ and no stable 1:1 key is serialized",
             grh_after["dpi_calls"], gsim_after["ext"].get("NODE_EXT", []),
             grh_key=lambda row: str(row.get("id")),
             gsim_key=lambda row: str(row.get("id")))
    ext_boundary_pre = gsim_before["ext"].get("NODE_EXT_IN", []) + gsim_before["ext"].get("NODE_EXT_OUT", [])
    ext_boundary_post = gsim_after["ext"].get("NODE_EXT_IN", []) + gsim_after["ext"].get("NODE_EXT_OUT", [])
    add_rule("dpi_import_ext_boundary", "dpi_boundary",
             grh_before["dpi_imports"], ext_boundary_pre,
             "GRH kDpicImport declarations and GSIM NODE_EXT_IN/OUT boundary ports are different granularity; listed as known n:m representation",
             grh_after["dpi_imports"], ext_boundary_post,
             grh_key=lambda row: str(row.get("id")),
             gsim_key=lambda row: str(row.get("id")))

    # Exact top-level ports.
    grh_io_pre = grh_before["top_io"]
    grh_io_post = grh_after["top_io"]
    gsim_io_pre = gsim_before["top_io"]
    gsim_io_post = gsim_after["top_io"]
    for key in sorted(set(grh_io_pre) & set(gsim_io_pre)):
        one_to_one.append(mapped_row("top_io", key, grh_io_pre[key], gsim_io_pre[key],
                                     key in grh_io_post, key in gsim_io_post,
                                     "exact normalized top-level I/O name"))
    for key in sorted(set(grh_io_pre) - set(gsim_io_pre)):
        add_one_sided("top_io", "grh", grh_io_pre[key], "top-level port has no GSIM NODE_INP/NODE_OUT name")
    for key in sorted(set(gsim_io_pre) - set(grh_io_pre)):
        add_one_sided("top_io", "gsim", gsim_io_pre[key], "GSIM NODE_INP/NODE_OUT has no GRH top-level port name")

    # Latches have no direct GSIM NODE_LATCH representation in this dump.
    for record in grh_before["latches"]:
        add_one_sided("latch", "grh", record,
                      "GRH kLatch has no direct GSIM NODE_LATCH anchor type")

    # Anything left in the known GRH register set is a reportable unexplained
    # anchor rather than silently dropping it from the closure.
    known_grh_names = set(grh_plain) | set(grh_before_groups["memory_storage"] and
                                           (normalize(row.get("sym", "")) for row in grh_before_groups["memory_storage"]))
    known_grh_names |= {normalize(row.get("sym", "")) for row in grh_before_groups["memory_pipeline"]}
    known_grh_names |= grh_state_name_sets(grh_before, split)[0]
    known_grh_names |= grh_state_name_sets(grh_before, split)[1]
    for record in grh_before_groups["other_array"]:
        add_unexplained("register_array", "grh", record,
                        "shape-bearing kRegister is outside the 4,832 explicit state families, memory storage, and pipeline rules")

    # Assign the 15 known SV residuals as one-sided-known only when the F20
    # cardinality is exactly the established 15; otherwise preserve them as
    # unexplained and let the report expose the discrepancy.
    grh_sv_rows = [row for row in one_sided
                   if row.get("category") == "sv_or_grh_only_register"]
    if len(grh_sv_rows) != 15:
        for row in grh_sv_rows:
            one_sided.remove(row)
            unexplained.append({**row, "relation": "unexplained",
                                "reason": "GRH-only scalar register count differs from the established 15 SV-state baseline"})

    # Closure uses physical anchor rows in the four buckets.  Exact 1:1 rows
    # contribute on both sides; n:m and one-sided rows contribute their side.
    grh_bucket = Counter()
    gsim_bucket = Counter()
    for row in one_to_one:
        grh_bucket[row["category"]] += 1
        gsim_bucket[row["category"]] += 1
    for row in n_m_rows:
        if row["side"] == "paired":
            grh_bucket[row["category"]] += 1
            gsim_bucket[row["category"]] += 1
        elif row["side"] == "grh":
            grh_bucket[row["category"]] += 1
        else:
            gsim_bucket[row["category"]] += 1
    for row in one_sided:
        (grh_bucket if row["side"] == "grh" else gsim_bucket)[row["category"]] += 1
    for row in unexplained:
        (grh_bucket if row["side"] == "grh" else gsim_bucket)[row["category"]] += 1

    survival_matrix = Counter(row["survival"] for row in one_to_one)
    survival_by_category = defaultdict(Counter)
    for row in one_to_one:
        survival_by_category[row["category"]][row["survival"]] += 1
    plain_rows = [row for row in one_to_one if row["category"] == "plain_register"]
    plain_diff = [row for row in plain_rows if row["survival"] != "both_alive"]
    unexplained_top = top_modules(unexplained)
    grh_only_rows = [row for row in one_to_one if row["survival"] == "grh_only"]
    gsim_only_rows = [row for row in one_to_one if row["survival"] == "gsim_only"]

    output_dir = args.out_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = ["category", "key", "relation", "grh_name", "gsim_name", "module",
               "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post",
               "survival", "grh_width", "gsim_width", "grh_shape",
               "gsim_dimension", "width_match", "reason"]
    write_tsv(output_dir / "anchors-1to1.tsv", one_to_one, columns)
    write_tsv(output_dir / "anchors-n-m-rules.tsv", n_m_rows,
              ["category", "rule", "key", "relation", "side", "grh_name", "gsim_name",
               "module", "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post",
               "survival", "width", "shape", "reason"])
    write_tsv(output_dir / "anchors-one-sided-known.tsv", one_sided,
              ["category", "key", "relation", "side", "grh_name", "gsim_name", "module",
               "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post", "survival",
               "grh_width", "gsim_width", "reason"])
    write_tsv(output_dir / "anchors-unexplained.tsv", unexplained,
              ["category", "key", "relation", "side", "grh_name", "gsim_name", "module",
               "name_pattern", "grh_pre", "gsim_pre", "reason"])
    for label, rows in (("both-alive", [row for row in one_to_one if row["survival"] == "both_alive"]),
                        ("grh-only", grh_only_rows),
                        ("gsim-only", gsim_only_rows),
                        ("both-dead", [row for row in one_to_one if row["survival"] == "both_dead"])):
        write_tsv(output_dir / f"survival-{label}.tsv", rows, columns)
    write_tsv(output_dir / "plain-register-survival.tsv", plain_rows, columns)

    grh_total = sum(grh_bucket.values())
    gsim_total = sum(gsim_bucket.values())
    category_counts = {
        "grh": counter_dict(grh_bucket),
        "gsim": counter_dict(gsim_bucket),
    }
    report = {
        "schema": "wolvrix.f21.anchor-alignment.v1",
        "inputs": {key: str(value) for key, value in {
            "grh_post_split_pre_dce": args.grh_before,
            "grh_post_dce": args.grh_after,
            "gsim_toposort_pre_dce": args.gsim_before,
            "gsim_remove_dead_nodes_post_dce": args.gsim_after,
            "gsim_init": args.gsim_init,
            "gsim_split_array_map": args.gsim_split_map,
        }.items()},
        "definitions": {
            "normalized_name": "GSIM $$ is normalized to GRH __DOT__; no other spelling is folded",
            "one_to_one": "Both sides have a pre-DCE anchor under the stated identity key; post-DCE status is compared by that key",
            "n_m_rule": "Both sides are enumerated, but only an explicit representation/count rule is established",
            "effect_line_identity": "GRH and GSIM effect endpoints pair by normalized module path, FIRRTL statement line, and effect kind; missing line evidence is non-pairable",
            "one_sided_known": "The other representation is absent or has a documented known representation difference",
            "unexplained": "An anchor remains after the exact joins and documented rules",
            "survival": "both_alive, grh_only, gsim_only, or both_dead for exact 1:1 rows",
        },
        "inventory": {
            "grh": {"total": grh_total, "categories": category_counts["grh"],
                    "category_sum": sum(category_counts["grh"].values())},
            "gsim": {"total": gsim_total, "categories": category_counts["gsim"],
                     "category_sum": sum(category_counts["gsim"].values())},
            "raw_scans": {
                "grh_before": grh_before["stats"],
                "grh_after": grh_after["stats"],
                "gsim_init": init["stats"],
                "split_map": split["stats"],
                "gsim_before": gsim_before["stats"],
                "gsim_after": gsim_after["stats"],
            },
        },
        "closure": {
            "grh_total_equals_bucket_sum": grh_total == sum(category_counts["grh"].values()),
            "gsim_total_equals_bucket_sum": gsim_total == sum(category_counts["gsim"].values()),
            "grh_bucket_sum": sum(category_counts["grh"].values()),
            "gsim_bucket_sum": sum(category_counts["gsim"].values()),
            "state_families": len(split["families"]),
            "state_members": sum(len(family["rows"]) for family in split["families"].values()),
        },
        "mapping": {
            "one_to_one": {"total": len(one_to_one),
                           "by_category": counter_dict(Counter(row["category"] for row in one_to_one))},
            "n_m_rules": rule_specs,
            "one_sided_known": {"total": len(one_sided),
                                "by_side": counter_dict(Counter(row["side"] for row in one_sided)),
                                "by_category": counter_dict(Counter(row["category"] for row in one_sided))},
            "unexplained": {"total": len(unexplained),
                            "by_side": counter_dict(Counter(row["side"] for row in unexplained)),
                            "by_category": counter_dict(Counter(row["category"] for row in unexplained))},
        },
        "survival": {
            "exact_1to1_matrix": counter_dict(survival_matrix),
            "by_category": {category: counter_dict(values)
                            for category, values in sorted(survival_by_category.items())},
            "plain_register": {
                "mapped": len(plain_rows),
                "differences": len(plain_diff),
                "matrix": counter_dict(Counter(row["survival"] for row in plain_rows)),
                "top_grh_only": top_modules([row for row in plain_diff if row["survival"] == "grh_only"]),
                "top_gsim_only": top_modules([row for row in plain_diff if row["survival"] == "gsim_only"]),
            },
            "n_m_rule_survival": {
                rule["rule"]: {
                    "grh_pre": rule["grh_pre"], "gsim_pre": rule["gsim_pre"],
                    "grh_post": rule["grh_post"], "gsim_post": rule["gsim_post"]
                } for rule in rule_specs
            },
        },
        "top_groups": {
            "unexplained": unexplained_top,
            "grh_only": top_modules(grh_only_rows),
            "gsim_only": top_modules(gsim_only_rows),
            "plain_register_differences": top_modules(plain_diff),
        },
        "verdict": {
            "anchor_identity_mapping_complete_enough_for_support_set_comparison": (
                not unexplained and not one_sided and all(
                    rule["rule"] not in {"memory_storage_depth1_conversion",
                                         "memory_pipeline_addr_role",
                                         "system_task_special_root",
                                         "dpi_call_ext_module",
                                         "dpi_import_ext_boundary"}
                    for rule in rule_specs
                )
            ),
            "reason": "Support-set comparison requires unresolved one-sided anchors and representation-only rules to be closed; this report does not treat count-only memory, pipeline, task, or DPI rules as identity proof.",
        },
        "performance": {
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_md(output_dir / "report.md", report, rule_specs,
                    one_to_one, one_sided, unexplained, grh_only_rows,
                    gsim_only_rows, plain_diff)
    return report


def write_report_md(path: Path, report: dict, rules: list[dict], one_to_one: list[dict],
                    one_sided: list[dict], unexplained: list[dict], grh_only: list[dict],
                    gsim_only: list[dict], plain_diff: list[dict]) -> None:
    inv = report["inventory"]
    lines = [
        "# F21 anchor identity alignment",
        "",
        "This is a serialized post-split/pre-DCE anchor inventory with post-DCE survival. It records structural identity and representation rules; it does not claim semantic or behavioral equivalence.",
        "",
        "## Inputs and scope",
        "",
        "The GRH pair is `post-split.json` → `post-dce.json`; the GSIM pair is `SimTop_0TopoSort.json` → `SimTop_2RemoveDeadNodes.json`. GSIM split members are resolved by `split-array-map.json` and original memory/state types by `SimTop_0Init.json`.",
        "",
        "Anchors include ordinary registers, explicit state-array members, memory storage, memory pipeline registers, latches, top-level I/O, DPI calls/imports, GRH system tasks, and GSIM special/external-boundary roots. GSIM reader/writer port nodes are supporting graph nodes rather than independent state/effect anchors.",
        "",
        "## Inventory closure",
        "",
        "| Side | Anchor total | Bucket sum | Closed |",
        "| --- | ---: | ---: | --- |",
        f"| GRH | {inv['grh']['total']} | {inv['grh']['category_sum']} | {report['closure']['grh_total_equals_bucket_sum']} |",
        f"| GSIM | {inv['gsim']['total']} | {inv['gsim']['category_sum']} | {report['closure']['gsim_total_equals_bucket_sum']} |",
        "",
        "Bucket sums are over mutually exclusive physical anchor rows: exact 1:1 rows, explicit n:m-rule rows, one-sided-known rows, and unexplained rows.",
        "",
        "## Exact 1:1 mapping and survival",
        "",
        f"Exact 1:1 rows: **{len(one_to_one)}**. State-family closure: **{report['closure']['state_families']} families / {report['closure']['state_members']} members**.",
        "",
        "| Survival | Count |",
        "| --- | ---: |",
    ]
    for key, value in report["survival"]["exact_1to1_matrix"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "Plain-register survival differences are counted by exact normalized name; see `plain-register-survival.tsv` for every mapped row and the report summary for grouped samples.",
        "",
        "| Plain-register metric | Count |",
        "| --- | ---: |",
        f"| mapped | {report['survival']['plain_register']['mapped']} |",
        f"| differences | {report['survival']['plain_register']['differences']} |",
    ]
    for key, value in report["survival"]["plain_register"]["matrix"].items():
        lines.append(f"| plain {key} | {value} |")
    lines += ["", "## Explicit n:m rules", "", "| Rule | GRH pre/post | GSIM pre/post |", "| --- | ---: | ---: |"]
    for rule in rules:
        lines.append(f"| {rule['rule']} | {rule['grh_pre']} / {rule['grh_post']} | {rule['gsim_pre']} / {rule['gsim_post']} |")
    lines += [
        "",
        "Memory storage is counted as GRH `firrtl.memory` versus GSIM `NODE_MEMORY` with depth-one conversion. The 488 memory pipeline rows are a count/role rule for GRH `firrtl.memoryPipeline` and GSIM `__DOT__ADDR`. System tasks/special roots and DPI/ext boundaries are also representation rules; equal totals do not establish identity.",
        "",
        "## One-sided and unexplained buckets",
        "",
        f"One-sided-known rows: **{len(one_sided)}**; unexplained rows: **{len(unexplained)}**. Full lists are in `anchors-one-sided-known.tsv` and `anchors-unexplained.tsv`.",
        "",
        "| Survival list | Rows | TSV |",
        "| --- | ---: | --- |",
        f"| GRH-only exact 1:1 | {len(grh_only)} | `survival-grh-only.tsv` |",
        f"| GSIM-only exact 1:1 | {len(gsim_only)} | `survival-gsim-only.tsv` |",
        f"| both dead exact 1:1 | {report['survival']['exact_1to1_matrix'].get('both_dead', 0)} | `survival-both-dead.tsv` |",
        "",
        "Top module/name-pattern groups are recorded in `summary.json` under `top_groups`; all rows remain in the TSV files.",
        "",
        "## Verdict",
        "",
        "**Anchor identity mapping is not complete enough to start support-set comparison.** Exact ordinary-register, state-member, and top-I/O joins are available, but memory storage, memory pipeline roles, system-task/special roots, DPI/ext boundaries, and any residual one-sided/unexplained rows require representation-specific closure before a support-set comparison can be interpreted as an identity comparison.",
        "",
        "The verdict is a mapping statement only. It makes no claim that either implementation is semantically equivalent or that a survival difference is safe.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh-before", required=True, type=Path)
    parser.add_argument("--grh-after", required=True, type=Path)
    parser.add_argument("--gsim-before", required=True, type=Path)
    parser.add_argument("--gsim-after", required=True, type=Path)
    parser.add_argument("--gsim-init", required=True, type=Path)
    parser.add_argument("--gsim-split-map", required=True, type=Path)
    parser.add_argument(
        "--state-family-report", type=Path,
        help="established state-element report whose families[].symbol set selects state parents",
    )
    parser.add_argument(
        "--f20-stats-dir", type=Path,
        help="F20 state-analysis directory containing ordinary-register-name-join.json",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    report = make_report(args)
    print(json.dumps({
        "grh": report["inventory"]["grh"],
        "gsim": report["inventory"]["gsim"],
        "closure": report["closure"],
        "performance": report["performance"],
    }, sort_keys=True))


# v2 implementation.  It is defined after the original draft so the public
# helpers above remain available to the F21 unit-test target while the report
# entry point uses the corrected streamed implementation.
def _anchor_name(record: dict | None, side: str) -> str:
    if record is None:
        return ""
    return normalize(record.get("sym" if side == "grh" else "name", ""))


def _single_side_row(category: str, side: str, identity: str,
                     record: dict, pre: bool, post: bool,
                     reason: str, relation: str) -> dict:
    name = _anchor_name(record, side)
    row = row_base(category, f"{side}:{identity}",
                   name if side == "grh" else "",
                   name if side == "gsim" else "")
    row.update({
        "relation": relation,
        "side": side,
        "grh_pre": bool(pre and side == "grh"),
        "gsim_pre": bool(pre and side == "gsim"),
        "grh_post": bool(post and side == "grh"),
        "gsim_post": bool(post and side == "gsim"),
        # A single-side row has no counterpart against which a two-sided
        # survival label can be evaluated.  Keep the side's post-DCE bit
        # separately and reserve ``survival`` for pairable rows.
        "survival": "not_pairable",
        "side_post": bool(post),
        "pairable": False,
        "grh_width": grh_width(record) if side == "grh" else "",
        "gsim_width": record.get("width", "") if side == "gsim" else "",
        "grh_shape": grh_shape(record) if side == "grh" else [],
        "gsim_dimension": record.get("dimension", []) if side == "gsim" else [],
        "reason": reason,
    })
    return row


def _known_generated_reason(reason: str | None) -> bool:
    return reason in {
        "gsim_zero_width_register",
        "gsim_copy_derived",
        "gsim_address_generated",
    }


def _rule_key(record: dict, side: str, prefix: str = "") -> str:
    if side == "grh":
        value = record.get("sym", record.get("id", ""))
        return prefix + normalize(str(value))
    value = record.get("name", record.get("id", ""))
    return prefix + normalize(str(value))


def paired_rule_row(category: str, rule: str, key: str,
                    grh_record: dict | None, gsim_record: dict | None,
                    grh_post: bool, gsim_post: bool, reason: str,
                    details: dict | None = None) -> dict:
    """Create one pairable n:m rule row carrying both side statuses."""
    grh_name = _anchor_name(grh_record, "grh")
    gsim_name = _anchor_name(gsim_record, "gsim")
    row = row_base(category, f"{rule}:{key}", grh_name, gsim_name)
    row.update({
        "relation": "n:m-rule",
        "rule": rule,
        "side": "paired",
        "pairable": True,
        "grh_pre": grh_record is not None,
        "gsim_pre": gsim_record is not None,
        "grh_post": bool(grh_post),
        "gsim_post": bool(gsim_post),
        "survival": survival_label(bool(grh_post), bool(gsim_post)),
        "grh_width": grh_width(grh_record),
        "gsim_width": gsim_record.get("width") if gsim_record else None,
        "grh_shape": grh_shape(grh_record),
        "gsim_dimension": gsim_record.get("dimension", []) if gsim_record else [],
        "reason": reason,
    })
    if grh_record is not None and gsim_record is not None:
        width_match, shape_match = shape_width_match(grh_record, gsim_record)
        row["width_match"] = width_match
        row["shape_match"] = shape_match
    if details:
        row.update(details)
    return row


def _physical_grh_inventory(grh: dict, groups: dict, split: dict) -> dict:
    categories = {
        "plain_scalar": len(groups["plain"]),
        "array_state_member": sum(
            normalize(record.get("sym", "")) in groups["state_member_names"]
            for record in grh["registers"].values()),
        "array_state_aggregate": len(groups["state_aggregate"]),
        "other_array": len(groups["other_array"]),
        "memory_storage": len(groups["memory_storage"]),
        "memory_pipeline": len(groups["memory_pipeline"]),
    }
    total = sum(categories.values())
    return {
        "kRegister": len(grh["registers"]),
        "categories": categories,
        "category_sum": total,
        "closed": total == len(grh["registers"]),
        "duplicates": len(grh.get("register_duplicates", [])),
    }


def _write_anchor_report_md(path: Path, report: dict) -> None:
    logical = report["inventory"]["logical_anchor_rows"]
    physical = report["inventory"]["physical"]
    mapping = report["mapping"]
    survival = report["survival"]
    lines = [
        "# F21 anchor identity alignment",
        "",
        "This report enumerates serialized post-split/pre-DCE anchors and compares their presence after DCE. It records structural identity and representation rules; it does not claim semantic or behavioral equivalence.",
        "",
        "## Scope and identity rules",
        "",
        "Names are normalized only by replacing GSIM `$$` with GRH `__DOT__`. Exact 1:1 rows use that normalized name for ordinary registers and top-level I/O, and split-map parent/member ID plus member index for array-state members. State families are expanded to logical member rows even when GRH retains an aggregate register; raw physical counts are reported separately.",
        "",
        "Anchors include plain registers, 4,832 split-array state families (58,255 members), memory storage, memory read pipeline registers, latches, top-level I/O, GRH system tasks and DPI operations, and GSIM special/external-module boundary roots. GSIM reader/writer nodes and memory port members are supporting graph nodes and are not counted as independent storage/effect anchors.",
        "",
        "Width and shape fields are emitted for every mapped row and width checks are summarized in `summary.json`. The serialized kRegister and REG_SRC anchor records do not expose direct clock/reset fields, so clock/reset presence is not used as an identity key.",
        "",
        "## F20 ordinary-register baseline",
        "",
        "The F20 hier-flatten baseline reports 195,155 exact ordinary-register matches. The post-split checkpoint has 177,227 exact scalar-register rows. Register-array identity has 44,900 exact normalized joins plus an aggregate-to-member rule covering 91 GRH aggregates and 2,437 GSIM members; 16 GSIM register-array rows remain unexplained. The historical F20 counts remain in `summary.json` under `baselines.f20_ordinary_register_join`.",
        "",
        "## Logical anchor-row closure",
        "",
        "| Side | Logical rows | Bucket sum | Closed |",
        "| --- | ---: | ---: | --- |",
        f"| GRH | {logical['grh']['total']} | {logical['grh']['category_sum']} | {report['closure']['grh_total_equals_bucket_sum']} |",
        f"| GSIM | {logical['gsim']['total']} | {logical['gsim']['category_sum']} | {report['closure']['gsim_total_equals_bucket_sum']} |",
        "",
        "The bucket sum is exact 1:1 rows plus the side rows in explicit n:m rules, one-sided-known rows, and unexplained rows. It is a logical anchor-row closure, not a claim that the two graph formats have equal physical node counts.",
        "",
        "| Aggregated category | GRH rows | GSIM rows |",
        "| --- | ---: | ---: |",
    ]
    all_categories = sorted(set(logical["grh"]["categories"]) | set(logical["gsim"]["categories"]))
    for category in all_categories:
        lines.append(
            f"| {category} | {logical['grh']['categories'].get(category, 0)} | "
            f"{logical['gsim']['categories'].get(category, 0)} |"
        )
    lines += [
        "",
        f"Closure equations: GRH **{logical['grh']['total']} = {logical['grh']['category_sum']}**; GSIM **{logical['gsim']['total']} = {logical['gsim']['category_sum']}**.",
        "",
        "| Mapping bucket | GRH rows | GSIM rows |",
        "| --- | ---: | ---: |",
    ]
    for bucket, values in report["mapping"]["bucket_counts"].items():
        lines.append(f"| {bucket} | {values['grh']} | {values['gsim']} |")
    lines += [
        "",
        "| Exact 1:1 category | Rows |",
        "| --- | ---: |",
    ]
    for category, count in mapping["one_to_one"]["by_category"].items():
        lines.append(f"| {category} | {count} |")
    lines += [
        "",
        "## Raw physical inventory",
        "",
        "| Side | Physical inventory | Category sum | Closed |",
        "| --- | ---: | ---: | --- |",
        f"| GRH kRegister | {physical['grh']['kRegister']} | {physical['grh']['category_sum']} | {physical['grh']['closed']} |",
        f"| GSIM REG_SRC | {physical['gsim']['reg_src']} | {physical['gsim']['reg_src_category_sum']} | {physical['gsim']['reg_src_closed']} |",
        "",
        "The GRH physical categories retain state member and aggregate representations separately. GSIM REG_SRC categories retain exact plain rows, generated rows, and the 488 address-pipeline role; NODE_MEMORY is listed in the n:m rule inventory.",
        "",
        "## Post-DCE survival",
        "",
        "| Exact 1:1 survival | Count |",
        "| --- | ---: |",
    ]
    for key, value in survival["exact_1to1_matrix"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "| Mapped anchor survival (including n:m side rows) | Count |",
        "| --- | ---: |",
    ]
    for key, value in survival["mapped_anchor_matrix"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        f"Plain-register rows mapped by exact normalized name: **{survival['plain_register']['mapped']}**; rows with a survival difference: **{survival['plain_register']['differences']}**.",
        "",
        "| Plain-register survival | Count |",
        "| --- | ---: |",
    ]
    for key, value in survival["plain_register"]["matrix"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "| Mapped survival by category (n:m rows use side-inventory status) | both_alive | grh_only | gsim_only | both_dead |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    mapped_by_category = survival["by_category_including_n_m_rules"]
    for category in sorted(mapped_by_category):
        values = mapped_by_category[category]
        lines.append(
            f"| {category} | {values.get('both_alive', 0)} | {values.get('grh_only', 0)} | "
            f"{values.get('gsim_only', 0)} | {values.get('both_dead', 0)} |"
        )
    lines += [
        "",
        "The survival TSVs contain exact 1:1 rows plus the side rows from explicit n:m rules; `plain-register-survival.tsv` contains every exact plain-register row. Exact-only and rule-inclusive matrices are both in `summary.json`.",
        "",
        "## Explicit n:m rules",
        "",
        "| Rule | Category | GRH pre/post | GSIM pre/post |",
        "| --- | --- | ---: | ---: |",
    ]
    for rule in mapping["n_m_rules"]:
        lines.append(f"| {rule['rule']} | {rule['category']} | {rule['grh_pre']} / {rule['grh_post']} | {rule['gsim_pre']} / {rule['gsim_post']} |")
    lines += [
        "",
        "The memory rule closes the storage count as GRH 4,877 = GSIM 3,324 `NODE_MEMORY` + 1,553 depth-one conversions represented by REG_SRC fields. The 488 GRH `firrtl.memoryPipeline` rows and 488 GSIM `__DOT__ADDR` rows are a role/count rule; the equal count is not treated as identity proof. Effect endpoints use the FIRRTL line attribute where available; DPI/ext rows without a line keyed counterpart remain non-pairable.",
        "",
        "## FIRRTL-line effect identity",
        "",
        "GRH `kSystemTask` rows carry `firrtl.line` and `firrtl.effectKind`; GSIM `NODE_SPECIAL` rows carry the same parser line in `lineno` and an ASSERT/PRINTF/STOP suffix. The identity key is normalized module path + FIRRTL line + effect kind. `effect-identity.tsv` contains every pair and every unmatched GRH/GSIM effect row.",
        "",
        "| Effect identity metric | Count |",
        "| --- | ---: |",
        f"| pairs | {report.get('effect_identity', {}).get('pairs', 0)} |",
        f"| unmatched GRH | {report.get('effect_identity', {}).get('unmatched_grh', 0)} |",
        f"| unmatched GSIM | {report.get('effect_identity', {}).get('unmatched_gsim', 0)} |",
        f"| non-pairable rows | {report.get('effect_identity', {}).get('not_pairable', 0)} |",
        f"| both alive | {report.get('effect_identity', {}).get('survival', {}).get('both_alive', 0)} |",
        f"| GRH-only | {report.get('effect_identity', {}).get('survival', {}).get('grh_only', 0)} |",
        f"| GSIM-only | {report.get('effect_identity', {}).get('survival', {}).get('gsim_only', 0)} |",
        f"| both dead | {report.get('effect_identity', {}).get('survival', {}).get('both_dead', 0)} |",
        "",
        "",
        "### GSIM-only array watch list",
        "",
        "These 16 array members are retained by GSIM while GRH deletes the corresponding member. They are listed for correctness monitoring only, per the asymmetric review rule.",
        "",
        "| Key | GSIM name | Survival |",
        "| --- | --- | --- |",
    ]
    for row in report.get("watch_lists", {}).get("gsim_only_array_elements", []):
        lines.append(
            f"| {row.get('key', '')} | {row.get('gsim_name', '')} | {row.get('survival', '')} |"
        )
    lines += [
        "",
        "## One-sided-known and unexplained anchors",
        "",
        f"One-sided-known rows: **{mapping['one_sided_known']['total']}**. Unexplained rows: **{mapping['unexplained']['total']}**. Full lists are `anchors-one-sided-known.tsv` and `anchors-unexplained.tsv`.",
        "",
        "### Unexplained examples",
        "",
        "| Category | Side | Key | Module | Name pattern | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in mapping["unexplained"].get("examples", []):
        reason = str(row.get("reason", "")).replace("|", "\\|")
        lines.append(
            f"| {row.get('category', '')} | {row.get('side', '')} | {row.get('key', '')} | "
            f"{row.get('module', '')} | {row.get('name_pattern', '')} | {reason} |"
        )
    lines += [
        "",
        "Top-N module/name-pattern groups for unexplained rows and mapped survival differences are in `summary.json` under `top_groups`.",
        "",
        "## Verdict",
        "",
        "**Anchor identity mapping is not complete enough to start support-set comparison.** Exact plain-register, split-state-member, and top-I/O joins are enumerated, but memory storage conversions, memory pipeline roles, system-task/special roots, DPI/ext boundaries, and any residual one-sided or unexplained rows require representation-specific closure before support-set comparison can be interpreted as an identity comparison.",
        "",
        "This verdict is about mapping completeness only. It makes no claim of semantic equivalence and does not classify a survival difference as safe.",
    ]
    delta = report.get("v1_v2_delta", {})
    lines += [
        "",
        "## v1 → v2 delta",
        "",
        f"Exact register-array joins: **{delta.get('register_array_exact_joins', 'n/a')}**; aggregate/member rule consumed **{report.get('survival', {}).get('n_m_rule_survival', {}).get('aggregate_member_split', {}).get('grh_pre', 'n/a')} GRH aggregates / {report.get('survival', {}).get('n_m_rule_survival', {}).get('aggregate_member_split', {}).get('gsim_pre', 'n/a')} GSIM members**; unexplained residual after that rule: **{delta.get('register_array_residual_grh', 'n/a')} / {delta.get('register_array_residual_gsim', 'n/a')}**.",
        f"Plain-register asymmetric survival differences: **{delta.get('plain_register_asymmetric_differences', 'n/a')}** (GRH-only **{delta.get('plain_register_grh_only', 'n/a')}**, GSIM-only **{delta.get('plain_register_gsim_only', 'n/a')}**); both-dead rows are excluded from this difference count.",
        f"n:m survival rows marked not pairable: **{delta.get('not_pairable_n_m_rows', 'n/a')}**.",
        f"GRH-extra rows after the corrected root criterion: **{report.get('grh_extra', {}).get('total', 'n/a')}**; pre-DCE-only rows excluded: **{report.get('grh_extra', {}).get('pre_dce_only_deleted_by_grh_dce', {}).get('total', 'n/a')}**; live role pairs dropped because both sides survive: **{report.get('grh_extra', {}).get('dropped_live_role_pairs', {}).get('total', 'n/a')}**.",
        "v2 no longer treats reaching a GRH system-task or DPI root as a legitimate purpose. Root reachability is recorded as evidence; legitimacy requires an explicit representation boundary or role rule, and missing GSIM dependency divergence remains unresolved.",
        "",
        "### v2 → v3 effect identity delta",
        "",
        f"The v3 line identity rule produced **{report.get('effect_identity', {}).get('pairs', 0)}** pairs, **{report.get('effect_identity', {}).get('unmatched_grh', 0)}** unmatched GRH rows, and **{report.get('effect_identity', {}).get('unmatched_gsim', 0)}** unmatched GSIM rows. Rows without source-line evidence remain explicitly non-pairable; no fake survival matrix is emitted for them.",
        "",
        "## Memory identity",
        "",
        "`memory-identity.tsv` pairs each GRH `firrtl.memory` storage row by SemanticTree memory field path with a GSIM `NODE_MEMORY` or depth-1 converted `REG_SRC`. `NODE_MEMORY` is absent from both F21 serialized node sections; survival is witnessed by any associated valid reader/writer member ID in the post-DCE dump. `memory-pipeline-identity.tsv` pairs the 488 ports by semantic declaration and `$$ADDR`, while recording the GRH data-delay versus GSIM address-delay role difference.",
        f"Per-memory rows: **{report.get('memory_identity', {}).get('rows', 'n/a')}**; unmatched: **{report.get('memory_identity', {}).get('unmatched', 'n/a')}**; survival: **{report.get('memory_identity', {}).get('survival', {})}**.",
        f"The per-memory result is GRH 3,502 live versus GSIM 3,503 live witnesses (2,299 NODE_MEMORY plus 1,204 depth-1 REG_SRC), with GRH-only **{report.get('memory_identity', {}).get('survival', {}).get('grh_only', 0)}** and GSIM-only **{report.get('memory_identity', {}).get('survival', {}).get('gsim_only', 0)}**. The earlier 3,502 versus 1,204 comparison was a GSIM depth-1-only counting artifact.",
        "",
        "## GRH-extra justification",
        "",
        "`grh-extra-justification.tsv` is the name-level ledger for rows retained by GRH after DCE while absent/dead in GSIM. A GRH path reaching a system task, DPI call, or port is liveness evidence only; it is never used as a legitimacy criterion. The ledger records the mapped GSIM root status, the first GRH path operation probed for divergence, and the state-cycle check. Pre-DCE-only rows are counted separately and are excluded from this ledger.",
        "",
        "| Verdict | Count |",
        "| --- | ---: |",
    ]
    for verdict, count in report.get("grh_extra", {}).get("verdict_counts", {}).items():
        lines.append(f"| {verdict} | {count} |")
    lines += [
        "",
        f"Closure: GRH-extra total **{report.get('grh_extra', {}).get('total', 0)}** = legitimate **{sum(v for k, v in report.get('grh_extra', {}).get('verdict_counts', {}).items() if k.startswith('legitimate:'))}** + optimization-gap **{report.get('grh_extra', {}).get('verdict_counts', {}).get('optimization-gap', 0)}** + unresolved **{report.get('grh_extra', {}).get('verdict_counts', {}).get('unresolved', 0)}**.",
        f"Pre-DCE-only rows deleted by GRH DCE and excluded from the ledger: **{report.get('grh_extra', {}).get('pre_dce_only_deleted_by_grh_dce', {}).get('total', 0)}** (latch **{report.get('grh_extra', {}).get('pre_dce_only_deleted_by_grh_dce', {}).get('by_category', {}).get('latch', 0)}**, SV/GRH-only register **{report.get('grh_extra', {}).get('pre_dce_only_deleted_by_grh_dce', {}).get('by_category', {}).get('sv_or_grh_only_register', 0)}**). Live role pairs dropped from the ledger because both sides survive: **{report.get('grh_extra', {}).get('dropped_live_role_pairs', {}).get('total', 0)}**.",
        "",
        "### Legitimate rows by name",
        "",
        "| Category | Name | Root | Root name | Path length | Evidence |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in report.get("grh_extra", {}).get("legitimate_rows", []):
        lines.append(
            f"| {row.get('category', '')} | {row.get('grh_name', '')} | {row.get('root_kind', '')} | {row.get('root_name', '')} | {row.get('path_length', '')} | {row.get('verdict_reason', '')} |"
        )
    lines += [
        "",
        "### Mechanism groups",
        "",
        "| Mechanism | Count | Representative | Divergence op kind | Op id | SemanticId | FIRRTL line |",
        "| --- | ---: | --- | --- | ---: | --- | ---: |",
    ]
    representatives = report.get("grh_extra", {}).get("mechanism_representatives", {})
    for mechanism, count in report.get("grh_extra", {}).get("mechanism_counts", {}).items():
        representative = representatives.get(mechanism, {})
        lines.append(
            f"| {mechanism} | {count} | {representative.get('name', '')} | "
            f"{representative.get('divergence_kind', '')} | "
            f"{representative.get('divergence_op_id', '')} | "
            f"{representative.get('divergence_semantic_id', '')} | "
            f"{representative.get('divergence_lineno', '')} |"
        )
    locations = report.get("grh_extra", {}).get("mechanism_locations", {})
    top_mechanisms = sorted(
        report.get("grh_extra", {}).get("mechanism_counts", {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:3]
    lines += [
        "",
        "### Top mechanism source candidates",
        "",
        "These are the first three ledger mechanisms by row count. The locations are pass locations to inspect; unresolved rows do not assert that the listed pass is the proven divergence.",
        "",
        "| Mechanism | Count | Candidate pass/location |",
        "| --- | ---: | --- |",
    ]
    for mechanism, count in top_mechanisms:
        lines.append(f"| {mechanism} | {count} | {locations.get(mechanism, 'location not established')} |")
    lines += [
        "",
        "For unresolved dependency probes, the operation kind is a GRH path observation; it is not asserted to be the GSIM divergence. Candidate pass locations for the largest path mechanisms are `wolvrix/lib/transform/dead_code_elim.cpp` (liveness propagation around lines 644–704), `wolvrix/lib/transform/split_static_array.cpp` (static-slice/concat rewriting around lines 483–544), and `wolvrix/lib/transform/simplify.cpp` (constant/slice simplification around lines 90–122). These locations identify where the corresponding comparison should be completed; they are not implementation changes made by this analysis.",
        "An unresolved row identifies the missing GSIM root/dependency evidence explicitly; no unresolved row is labeled legitimate.",
        "",
        "**Asymmetric verdict:** GSIM-only anchors are reported as counts (with the 16 array-element watch list); every GRH-extra row is listed and classified individually. Support-set comparison remains blocked until the unresolved GRH-extra rows are closed and any optimization-gap mechanism is addressed. This is an identity and liveness report only; it makes no semantic-equivalence claim.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_report(args) -> dict:
    started = time.monotonic()
    grh_before = collect_grh(args.grh_before)
    grh_after = collect_grh(args.grh_after)
    init = load_gsim_init(args.gsim_init)
    f20_stats = load_f20_stats(args.f20_stats_dir)
    state_family_names = load_state_family_names(args.state_family_report)
    gsim_reg_names, gsim_reg_ids = collect_gsim_reg_names(args.gsim_before)
    split = load_split_state_map(args.gsim_split_map, init, grh_before,
                                 state_family_names,
                                 set(grh_before["registers"]) | gsim_reg_names,
                                 gsim_reg_ids)
    gsim_before = _scan_gsim_nodes(args.gsim_before, split, init)
    gsim_after = _scan_gsim_nodes(args.gsim_after, split, init)
    grh_before_groups = grh_register_groups(grh_before, split)
    grh_after_groups = grh_register_groups(grh_after, split)

    semantic_target_ids = {
        sid for record in [*grh_before_groups["memory_storage"],
                           *grh_before_groups["memory_pipeline"]]
        for sid in record.get("semanticIds", []) if isinstance(sid, int)
    }
    semantic_paths = load_semantic_paths(args.grh_before, semantic_target_ids)

    one_to_one: list[dict] = []
    n_m_rows: list[dict] = []
    one_sided: list[dict] = []
    unexplained: list[dict] = []
    rule_specs: list[dict] = []

    grh_plain = {normalize(row.get("sym", "")): row for row in grh_before_groups["plain"]}
    grh_plain_after = {normalize(row.get("sym", "")): row for row in grh_after_groups["plain"]}
    grh_array = {normalize(row.get("sym", "")): row for row in grh_before_groups["other_array"]}
    grh_array_after = {normalize(row.get("sym", "")): row for row in grh_after_groups["other_array"]}
    gsim_reg_pre = gsim_before["reg_src"]
    gsim_reg_after = gsim_after["reg_src"]
    gsim_array_exact = {key: record for key, record in gsim_reg_pre.items() if key in grh_array}
    gsim_array_exact_after = {key: record for key, record in gsim_reg_after.items() if key in grh_array_after}
    gsim_plain = {}
    gsim_plain_after = {}
    generated_pre: defaultdict[str, list[dict]] = defaultdict(list)
    generated_after: defaultdict[str, list[dict]] = defaultdict(list)
    non_state_gsim_pre: list[dict] = []
    unexplained_generated_pre: list[dict] = []
    unexplained_generated_after: set[str] = set()
    unknown_gsim_pre: list[dict] = []

    # Exact plain-register joins are decided before generated-name rules.  In
    # particular, the 32 ADDRESS names that also occur in GRH remain exact
    # plain matches; only unmatched generated rows enter one-sided buckets.
    for key, record in gsim_reg_pre.items():
        if key in gsim_array_exact:
            continue
        if key in grh_plain:
            gsim_plain[key] = record
            continue
        reason = generated_reg_reason(record)
        if reason == "gsim_depth1_memory_conversion":
            continue  # accounted for by the memory n:m rule below
        if reason == "gsim_ramdatas_residual":
            unexplained_generated_pre.append(record)
            continue
        if key in split.get("non_state_names", set()):
            non_state_gsim_pre.append(record)
            continue
        if reason is not None:
            generated_pre[reason].append(record)
        else:
            unknown_gsim_pre.append(record)
    for key, record in gsim_reg_after.items():
        if key in gsim_array_exact_after:
            continue
        if key in grh_plain_after:
            gsim_plain_after[key] = record
            continue
        reason = generated_reg_reason(record)
        if reason == "gsim_depth1_memory_conversion":
            continue
        if reason == "gsim_ramdatas_residual":
            unexplained_generated_after.add(key)
            continue
        if key in split.get("non_state_names", set()):
            continue
        if reason is not None:
            generated_after[reason].append(record)

    for key in sorted(set(grh_plain) & set(gsim_plain)):
        one_to_one.append(mapped_row(
            "plain_register", key, grh_plain[key], gsim_plain[key],
            key in grh_plain_after, key in gsim_plain_after,
            "normalized exact register name (GSIM $$ -> GRH __DOT__)",
        ))
    for key in sorted(gsim_array_exact):
        row = mapped_row(
            "register_array", key, grh_array[key], gsim_array_exact[key],
            key in grh_array_after, key in gsim_array_exact_after,
            "normalized exact array-register name (GSIM $$ -> GRH __DOT__)",
        )
        row["width_match"], row["shape_match"] = shape_width_match(
            grh_array[key], gsim_array_exact[key])
        one_to_one.append(row)

    # Residual shape-bearing rows are handled by an explicit aggregate↔member
    # rule.  They remain n:m representation rows in the physical closure;
    # the paired group table carries the meaningful any-member survival.
    unmatched_grh_array = {
        key: record for key, record in grh_array.items()
        if key not in gsim_array_exact
    }
    unmatched_gsim_array = {}
    for record in [*non_state_gsim_pre, *unknown_gsim_pre]:
        key = normalize(record.get("name", ""))
        unmatched_gsim_array[key] = record
    aggregate_pairs, aggregate_grh_used, aggregate_gsim_used = build_aggregate_pairs(
        unmatched_grh_array, unmatched_gsim_array)
    aggregate_group_rows: list[dict] = []
    aggregate_rule_member_rows: list[dict] = []
    aggregate_reason = (
        "aggregate/member split matched by parent name, numeric member suffix, "
        "member count, and total packed width"
    )
    for pair in aggregate_pairs:
        parent = pair["parent"]
        aggregate = pair["aggregate"]
        if pair["direction"] == "grh_aggregate_to_gsim_members":
            grh_record = aggregate
            gsim_record = None
            grh_post = normalize(grh_record.get("sym", "")) in grh_array_after
            members = []
            for suffix, member in pair["members"]:
                name = normalize(member.get("name", ""))
                post = name in gsim_reg_after
                members.append({"suffix": suffix, "gsim_name": name,
                                "grh_name": parent, "gsim_post": post,
                                "grh_post": grh_post,
                                "survival": survival_label(grh_post, post)})
                aggregate_rule_member_rows.append({
                    "rule": "aggregate_member_split", "parent_name": parent,
                    "direction": pair["direction"], "member_suffix": suffix,
                    "grh_name": parent, "gsim_name": name,
                    "grh_post": grh_post, "gsim_post": post,
                    "survival": survival_label(grh_post, post),
                    "grh_width": grh_width(grh_record),
                    "gsim_width": member.get("width"),
                })
            gsim_post = any(row["gsim_post"] for row in members)
            detail = {"group_key": parent, "group_survival": survival_label(grh_post, gsim_post),
                      "member_detail": members, "direction": pair["direction"]}
            aggregate_group_rows.append(paired_rule_row(
                "register_array", "aggregate_member_split", parent,
                grh_record, None, grh_post, gsim_post, aggregate_reason, detail))
            physical = [_single_side_row("register_array", "grh", parent, grh_record,
                                         True, grh_post, aggregate_reason, "n:m-rule")]
            for suffix, member in pair["members"]:
                name = normalize(member.get("name", ""))
                physical.append(_single_side_row("register_array", "gsim", name,
                                                 member, True, name in gsim_reg_after,
                                                 aggregate_reason, "n:m-rule"))
            for row in physical:
                row.update({"rule": "aggregate_member_split", "group_key": parent,
                            "group_survival": detail["group_survival"]})
            n_m_rows.extend(physical)
        else:
            gsim_record = aggregate
            grh_record = None
            gsim_post = parent in gsim_reg_after
            members = []
            for suffix, member in pair["members"]:
                name = normalize(member.get("sym", ""))
                post = name in grh_array_after
                members.append({"suffix": suffix, "grh_name": name,
                                "gsim_name": parent, "grh_post": post,
                                "gsim_post": gsim_post,
                                "survival": survival_label(post, gsim_post)})
                aggregate_rule_member_rows.append({
                    "rule": "aggregate_member_split", "parent_name": parent,
                    "direction": pair["direction"], "member_suffix": suffix,
                    "grh_name": name, "gsim_name": parent,
                    "grh_post": post, "gsim_post": gsim_post,
                    "survival": survival_label(post, gsim_post),
                    "grh_width": grh_width(member),
                    "gsim_width": gsim_record.get("width"),
                })
            grh_post = any(row["grh_post"] for row in members)
            detail = {"group_key": parent, "group_survival": survival_label(grh_post, gsim_post),
                      "member_detail": members, "direction": pair["direction"]}
            aggregate_group_rows.append(paired_rule_row(
                "register_array", "aggregate_member_split", parent,
                None, gsim_record, grh_post, gsim_post, aggregate_reason, detail))
            physical = [_single_side_row("register_array", "gsim", parent, gsim_record,
                                         True, gsim_post, aggregate_reason, "n:m-rule")]
            for suffix, member in pair["members"]:
                name = normalize(member.get("sym", ""))
                physical.append(_single_side_row("register_array", "grh", name,
                                                 member, True, name in grh_array_after,
                                                 aggregate_reason, "n:m-rule"))
            for row in physical:
                row.update({"rule": "aggregate_member_split", "group_key": parent,
                            "group_survival": detail["group_survival"]})
            n_m_rows.extend(physical)
    aggregate_survival = Counter(row["survival"] for row in aggregate_group_rows)
    rule_specs.append({
        "rule": "aggregate_member_split", "category": "register_array",
        "grh_pre": sum(1 + (len(pair["members"]) if pair["direction"] == "gsim_aggregate_to_grh_members" else 0)
                        for pair in aggregate_pairs),
        "gsim_pre": sum(1 + (len(pair["members"]) if pair["direction"] == "grh_aggregate_to_gsim_members" else 0)
                         for pair in aggregate_pairs),
        "grh_post": sum(row["grh_pre"] and row["grh_post"] for row in n_m_rows
                         if row.get("rule") == "aggregate_member_split" and row.get("side") == "grh"),
        "gsim_post": sum(row["gsim_pre"] and row["gsim_post"] for row in n_m_rows
                          if row.get("rule") == "aggregate_member_split" and row.get("side") == "gsim"),
        "reason": aggregate_reason,
        "details": {"groups": len(aggregate_group_rows),
                     "survival": complete_survival(aggregate_survival),
                     "group_rows": aggregate_group_rows},
    })
    for key in sorted(set(grh_plain) - set(gsim_plain)):
        post = key in grh_plain_after
        one_sided.append(_single_side_row(
            "sv_or_grh_only_register", "grh", key, grh_plain[key], True,
            post,
            "no normalized GSIM REG_SRC; the established F20 residual category contains 15 GRH SV-state registers",
            "one-sided-known",
        ))
    for reason, records in sorted(generated_pre.items()):
        for record in records:
            key = normalize(record.get("name", ""))
            post = key in {normalize(row.get("name", "")) for row in generated_after.get(reason, [])}
            one_sided.append(_single_side_row(
                "generated_gsim_register", "gsim", key, record, True, post,
                reason, "one-sided-known",
            ))
    for record in unknown_gsim_pre:
        key = normalize(record.get("name", ""))
        if key in aggregate_gsim_used:
            continue
        post = key in gsim_reg_after
        category = "register_array" if key in unmatched_gsim_array else "plain_register"
        unexplained.append(_single_side_row(
            category, "gsim", key, record, True, post,
            "REG_SRC has no GRH normalized-name match and no established generated-register rule"
            if category == "plain_register" else
            "numeric member REG_SRC has no GRH exact-name match and no aggregate/member rule",
            "unexplained",
        ))
    for record in non_state_gsim_pre:
        key = normalize(record.get("name", ""))
        if key in aggregate_gsim_used:
            continue
        post = key in gsim_reg_after and key in split.get("non_state_names", set())
        unexplained.append(_single_side_row(
            "register_array", "gsim", key, record, True, post,
            "REG_SRC name is a member/parent of a split-map family outside the established 4,832 state families",
            "unexplained",
        ))
    for record in unexplained_generated_pre:
        key = normalize(record.get("name", ""))
        unexplained.append(_single_side_row(
            "register_array", "gsim", key, record, True,
            key in unexplained_generated_after,
            "GSIM ramDatas tag/reservedBits register is outside the established 1,553 depth-one memory conversion set",
            "unexplained",
        ))

    # Expand each explicit split family to logical member anchors.  A valid
    # aggregate parent stands for all its split-map member indices.
    state_grh_pre = grh_before["registers"]
    state_grh_post = grh_after["registers"]
    for family_key, family in sorted(split["families"].items()):
        parent_name = family["parent_name"]
        grh_aggregate_pre = parent_name in state_grh_pre
        grh_aggregate_post = parent_name in state_grh_post
        gsim_before_indices = set(gsim_before["state_indices"].get(family_key, set()))
        gsim_after_indices = set(gsim_after["state_indices"].get(family_key, set()))
        if family_key in gsim_before["state_parent_alive"]:
            gsim_before_indices = {row["memberIndex"] for row in family["rows"]}
        if family_key in gsim_after["state_parent_alive"]:
            gsim_after_indices = {row["memberIndex"] for row in family["rows"]}
        for split_row in family["rows"]:
            index = split_row["memberIndex"]
            member_name = normalize(split_row["memberName"])
            grh_record = state_grh_pre.get(member_name)
            if grh_record is None and grh_aggregate_pre:
                grh_record = state_grh_pre[parent_name]
            grh_post = state_grh_post.get(member_name)
            if grh_post is None and grh_aggregate_post:
                grh_post = state_grh_post[parent_name]
            gsim_record = gsim_before["state_records"].get((family_key, index))
            gsim_synthetic = gsim_record or {
                "name": split_row.get("memberName", ""),
                "width": split_row.get("memberWidth"),
                "dimension": split_row.get("memberDimension", []),
            }
            gsim_pre = index in gsim_before_indices
            gsim_post = index in gsim_after_indices
            key = f"{family_key}:{index}"
            if grh_record is not None and gsim_pre:
                row = mapped_row(
                    "array_state_member", key, grh_record, gsim_synthetic,
                    grh_post is not None, gsim_post,
                    "explicit split-array parent/member ID and member index",
                )
                row["member_index"] = index
                row["parent_name"] = parent_name
                row["grh_representation"] = "aggregate" if member_name not in state_grh_pre else "member"
                row["gsim_member_name"] = member_name
                row["gsim_width"] = gsim_synthetic.get("width")
                expected_width = gsim_synthetic.get("width")
                if row["grh_representation"] == "aggregate":
                    expected_widths = {expected_width, expected_width * max(1, shape_count(family["parent_dimension"]))} if isinstance(expected_width, int) else set()
                    row["width_match"] = grh_width(grh_record) in expected_widths
                else:
                    row["width_match"] = grh_width(grh_record) == expected_width
                one_to_one.append(row)
            elif grh_record is not None:
                one_sided.append(_single_side_row(
                    "array_state_member", "grh", key, grh_record, True,
                    grh_post is not None,
                    "split-map member has no valid GSIM pre-DCE member ID",
                    "one-sided-known",
                ))
            elif gsim_pre:
                one_sided.append(_single_side_row(
                    "array_state_member", "gsim", key, gsim_synthetic, True,
                    gsim_post,
                    "split-map member has no GRH member/aggregate declaration",
                    "one-sided-known",
                ))
            else:
                unexplained.append(_single_side_row(
                    "array_state_member", "gsim", key, gsim_synthetic, False,
                    False,
                    "split-map row is absent from both serialized pre-DCE node views",
                    "unexplained",
                ))

    def add_rule(name: str, category: str, grh_items: list[dict],
                 gsim_items: list[dict], reason: str,
                 grh_after_items: list[dict], gsim_after_items: list[dict],
                 grh_key, gsim_key, details: dict | None = None) -> None:
        grh_after_keys = {grh_key(row) for row in grh_after_items}
        gsim_after_keys = {gsim_key(row) for row in gsim_after_items}
        for record in grh_items:
            key = grh_key(record)
            name_value = _anchor_name(record, "grh")
            out = row_base(category, f"{name}:grh:{key}", name_value, "")
            out.update({
                "relation": "n:m-rule", "rule": name, "side": "grh",
                "pairable": False,
                "grh_pre": True, "gsim_pre": False,
                "grh_post": key in grh_after_keys, "gsim_post": False,
                "survival": "not_pairable", "side_post": key in grh_after_keys,
                "grh_width": grh_width(record), "grh_shape": grh_shape(record),
                "reason": reason,
            })
            n_m_rows.append(out)
        for record in gsim_items:
            key = gsim_key(record)
            name_value = _anchor_name(record, "gsim")
            out = row_base(category, f"{name}:gsim:{key}", "", name_value)
            out.update({
                "relation": "n:m-rule", "rule": name, "side": "gsim",
                "pairable": False,
                "grh_pre": False, "gsim_pre": True,
                "grh_post": False, "gsim_post": key in gsim_after_keys,
                "survival": "not_pairable", "side_post": key in gsim_after_keys,
                "gsim_width": record.get("width"), "gsim_dimension": record.get("dimension", []),
                "reason": reason,
            })
            n_m_rows.append(out)
        rule = {
            "rule": name, "category": category,
            "grh_pre": len(grh_items), "gsim_pre": len(gsim_items),
            "grh_post": len(grh_after_items), "gsim_post": len(gsim_after_items),
            "reason": reason,
        }
        if details:
            rule["details"] = details
        rule_specs.append(rule)

    # Per-memory identity.  NODE_MEMORY is stored in the Init graph's
    # separate memory table and is absent from both F21 serialized node
    # sections.  Its post-DCE status is therefore derived from the validity of
    # any associated reader/writer member ID in the before/after dumps.
    grh_mem_pre = grh_before_groups["memory_storage"]
    grh_mem_post_by_name = {
        normalize(record.get("sym", "")): record
        for record in grh_after_groups["memory_storage"]
    }
    gsim_mem_by_name = {
        normalize(record.get("name", "")): record
        for record in init["memories"].values()
    }
    converted_pre = {
        key: record for key, record in gsim_reg_pre.items()
        if generated_reg_reason(record) == "gsim_depth1_memory_conversion"
    }
    converted_after = {
        key: record for key, record in gsim_reg_after.items()
        if generated_reg_reason(record) == "gsim_depth1_memory_conversion"
    }
    gsim_memory_by_name = {
        **{key: ("NODE_MEMORY", record) for key, record in gsim_mem_by_name.items()},
        **{key: ("REG_SRC_DEPTH1", record) for key, record in converted_pre.items()},
    }
    memory_identity_rows: list[dict] = []
    memory_unmatched = []
    for record in sorted(grh_mem_pre, key=lambda item: normalize(item.get("sym", ""))):
        semantic_ids = record.get("semanticIds", [])
        semantic_path = semantic_paths.get(semantic_ids[0], "") if semantic_ids else ""
        memory_key = normalize(semantic_path)
        representation, gsim_record = gsim_memory_by_name.get(memory_key, (None, None))
        grh_name = normalize(record.get("sym", ""))
        grh_post = grh_name in grh_mem_post_by_name
        gsim_post = False
        member_ids = []
        alive_member_ids = []
        method = ""
        if representation == "NODE_MEMORY":
            member_ids = list(gsim_record.get("members", []))
            alive_member_ids = sorted(set(member_ids) & set(gsim_after["memory_member_alive_ids"]))
            gsim_post = bool(alive_member_ids)
            method = "NODE_MEMORY absent from TopoSort/RemoveDeadNodes; any valid associated reader/writer member ID is the survival witness"
        elif representation == "REG_SRC_DEPTH1":
            gsim_name = normalize(gsim_record.get("name", ""))
            gsim_post = gsim_name in converted_after
            method = "depth-1 memory is serialized as a direct REG_SRC; post-DCE status is its normalized REG_SRC name"
        else:
            memory_unmatched.append({"grh_name": grh_name, "semantic_path": semantic_path})
            method = "no GSIM NODE_MEMORY or depth-1 REG_SRC name matched the semantic memory path"
        shape = list(grh_shape(record) or [])
        depth = shape[0] if shape else 1
        data_width = (grh_width(record) // shape_count(shape)
                      if isinstance(grh_width(record), int) and shape_count(shape)
                      and grh_width(record) % shape_count(shape) == 0 else None)
        # A depth-one memory converted to REG_SRC has no serialized depth
        # field.  The representation rule fixes that depth at one for the
        # per-memory width/depth check.
        gsim_depth = (
            1 if representation == "REG_SRC_DEPTH1"
            else gsim_record.get("depth") if gsim_record else None
        )
        gsim_dimension = list(gsim_record.get("dimension", []) or []) if gsim_record else []
        gsim_width = gsim_record.get("width") if gsim_record else None
        row = {
            "category": "memory_storage", "rule": "memory_storage_identity",
            "key": memory_key or grh_name, "relation": "n:m-rule", "side": "paired",
            "pairable": representation is not None,
            "grh_name": grh_name, "semantic_path": semantic_path,
            "gsim_name": normalize(gsim_record.get("name", "")) if gsim_record else "",
            "representation": representation or "unmatched",
            "grh_pre": True, "gsim_pre": representation is not None,
            "grh_post": grh_post, "gsim_post": gsim_post,
            "survival": survival_label(grh_post, gsim_post) if representation else "not_pairable",
            "grh_width": grh_width(record), "gsim_width": gsim_width,
            "grh_shape": shape, "gsim_dimension": gsim_dimension,
            "grh_depth": depth, "gsim_depth": gsim_depth,
            "grh_data_width": data_width,
            "depth_match": gsim_depth == depth if gsim_depth is not None else None,
            "width_match": data_width == gsim_width if data_width is not None and gsim_width is not None else None,
            "dimension_match": (
                [axis for axis in shape[1:] if axis != 1]
                == [axis for axis in gsim_dimension if axis != 1]
                if gsim_record else None
            ),
            "member_ids": member_ids, "alive_member_ids": alive_member_ids,
            "member_count": len(member_ids), "alive_member_count": len(alive_member_ids),
            "method": method,
        }
        memory_identity_rows.append(row)
        n_m_rows.append(row)
    memory_survival = Counter(row["survival"] for row in memory_identity_rows if row["pairable"])
    rule_specs.append({
        "rule": "memory_storage_identity", "category": "memory_storage",
        "grh_pre": len(grh_mem_pre), "gsim_pre": len(memory_identity_rows),
        "grh_post": sum(row["grh_post"] for row in memory_identity_rows),
        "gsim_post": sum(row["gsim_post"] for row in memory_identity_rows),
        "reason": "per-memory semantic path/name identity; NODE_MEMORY survival uses associated port members",
        "details": {
            "gsim_node_memory_pre": len(gsim_mem_by_name),
            "gsim_node_memory_post_witnessed": sum(row["representation"] == "NODE_MEMORY" and row["gsim_post"] for row in memory_identity_rows),
            "gsim_depth1_converted_pre": sum(
                row["representation"] == "REG_SRC_DEPTH1"
                for row in memory_identity_rows
            ),
            "gsim_depth1_converted_post": sum(row["representation"] == "REG_SRC_DEPTH1" and row["gsim_post"] for row in memory_identity_rows),
            "unmatched": len(memory_unmatched),
            "survival": complete_survival(memory_survival),
            "depth_mismatches": sum(row["depth_match"] is False for row in memory_identity_rows),
            "width_mismatches": sum(row["width_match"] is False for row in memory_identity_rows),
            "dimension_mismatches": sum(row["dimension_match"] is False for row in memory_identity_rows),
        },
    })

    # Memory read pipeline role pair.  GRH delays data; GSIM delays the read
    # address.  The semantic declaration leaf plus the GRH op prefix yields
    # the exact GSIM $$ADDR name after normalization.
    pipeline_identity_rows: list[dict] = []
    pipeline_unmatched = []
    for record in sorted(grh_before_groups["memory_pipeline"], key=lambda item: normalize(item.get("sym", ""))):
        semantic_ids = record.get("semanticIds", [])
        declaration_path = semantic_paths.get(semantic_ids[0], "") if semantic_ids else ""
        port_leaf = declaration_path.rsplit("$", 1)[-1] if declaration_path else ""
        prefix = re.sub(r"\$_op_\d+$", "", normalize(record.get("sym", "")))
        expected = normalize(prefix + "$" + port_leaf + "$$ADDR") if port_leaf else ""
        gsim_record = gsim_before["pipeline"].get(expected) if isinstance(gsim_before["pipeline"], dict) else None
        if gsim_record is None:
            gsim_record = next((item for item in gsim_before.get("pipeline_rows", [])
                                if normalize(item.get("name", "")) == expected), None)
        grh_name = normalize(record.get("sym", ""))
        grh_post = grh_name in {normalize(item.get("sym", "")) for item in grh_after_groups["memory_pipeline"]}
        gsim_post = expected in gsim_after.get("pipeline_names", set())
        if gsim_record is None:
            pipeline_unmatched.append({"grh_name": grh_name, "expected_gsim": expected})
        row = {
            "category": "memory_pipeline", "rule": "memory_pipeline_role_pair",
            "key": grh_name, "relation": "n:m-rule", "side": "paired",
            "pairable": gsim_record is not None,
            "grh_name": grh_name, "gsim_name": expected,
            "grh_pre": True, "gsim_pre": gsim_record is not None,
            "grh_post": grh_post, "gsim_post": gsim_post,
            "survival": survival_label(grh_post, gsim_post) if gsim_record else "not_pairable",
            "grh_width": grh_width(record), "gsim_width": gsim_record.get("width") if gsim_record else None,
            "grh_shape": grh_shape(record), "gsim_dimension": gsim_record.get("dimension", []) if gsim_record else [],
            "role_grh": "data_delay", "role_gsim": "address_delay",
            "semantic_port": declaration_path, "address_width": gsim_record.get("width") if gsim_record else None,
            "method": "semantic port declaration plus register prefix and $$ADDR suffix",
        }
        pipeline_identity_rows.append(row)
        n_m_rows.append(row)
    pipeline_survival = Counter(row["survival"] for row in pipeline_identity_rows if row["pairable"])
    rule_specs.append({
        "rule": "memory_pipeline_role_pair", "category": "memory_pipeline",
        "grh_pre": len(grh_before_groups["memory_pipeline"]),
        "gsim_pre": len(pipeline_identity_rows),
        "grh_post": sum(row["grh_post"] for row in pipeline_identity_rows),
        "gsim_post": sum(row["gsim_post"] for row in pipeline_identity_rows),
        "reason": "per-port pairing; GRH data-delay role versus GSIM address-delay role",
        "details": {"unmatched": len(pipeline_unmatched), "survival": complete_survival(pipeline_survival)},
    })
    # Effects are identity-paired by module path + originating FIRRTL line.
    # Rows without line evidence (currently DPI/ext boundaries in this
    # flattened checkpoint) stay explicit non-pairable rows; they do not get a
    # fabricated survival matrix.
    effect_identity_rows, effect_identity_summary = build_effect_identity(
        grh_before, grh_after, gsim_before, gsim_after)
    n_m_rows.extend(effect_identity_rows)
    rule_specs.append({
        "rule": "effect_line_identity", "category": "effect_identity",
        "grh_pre": sum(row.get("grh_pre", False) for row in effect_identity_rows),
        "gsim_pre": sum(row.get("gsim_pre", False) for row in effect_identity_rows),
        "grh_post": sum(row.get("grh_post", False) for row in effect_identity_rows),
        "gsim_post": sum(row.get("gsim_post", False) for row in effect_identity_rows),
        "reason": "module path + FIRRTL line + effect kind; rows without evidence are not pairable",
        "details": effect_identity_summary,
    })

    # Exact top-level I/O names.
    for key in sorted(set(grh_before["top_io"]) & set(gsim_before["top_io"])):
        one_to_one.append(mapped_row(
            "top_io", key, grh_before["top_io"][key], gsim_before["top_io"][key],
            key in grh_after["top_io"], key in gsim_after["top_io"],
            "exact normalized top-level I/O name",
        ))
    for key in sorted(set(grh_before["top_io"]) - set(gsim_before["top_io"])):
        one_sided.append(_single_side_row(
            "top_io", "grh", key, grh_before["top_io"][key], True,
            key in grh_after["top_io"],
            "top-level port has no GSIM NODE_INP/NODE_OUT name", "one-sided-known"))
    for key in sorted(set(gsim_before["top_io"]) - set(grh_before["top_io"])):
        one_sided.append(_single_side_row(
            "top_io", "gsim", key, gsim_before["top_io"][key], True,
            key in gsim_after["top_io"],
            "GSIM NODE_INP/NODE_OUT has no GRH top-level port name", "one-sided-known"))

    # Latches and any system functions are known one-sided GRH effects.
    latch_after_ids = {str(record.get("id")) for record in grh_after["latches"]}
    for record in grh_before["latches"]:
        one_sided.append(_single_side_row(
            "latch", "grh", str(record.get("id")), record, True,
            str(record.get("id")) in latch_after_ids,
            "GRH kLatch has no direct GSIM NODE_LATCH anchor type", "one-sided-known"))
    latch_function_after_ids = {str(record.get("id")) for record in grh_after["system_functions"]}
    for record in grh_before["system_functions"]:
        one_sided.append(_single_side_row(
            "grh_system_function", "grh", str(record.get("id")), record, True,
            str(record.get("id")) in latch_function_after_ids,
            "GRH kSystemFunction is not a NODE_SPECIAL identity in this dump", "one-sided-known"))

    for record in grh_before_groups["other_array"]:
        key = normalize(record.get("sym", ""))
        if key in gsim_array_exact or key in aggregate_grh_used:
            continue
        one_sided_or_post = key in grh_after["registers"]
        unexplained.append(_single_side_row(
            "register_array", "grh", key, record, True, one_sided_or_post,
            "shape-bearing kRegister is outside the explicit split-state, memory-storage, and pipeline rules",
            "unexplained"))

    # Logical bucket closure.  Exact state rows intentionally count members;
    # physical register closure below reports the unexpanded representation.
    grh_bucket = Counter()
    gsim_bucket = Counter()
    for row in one_to_one:
        grh_bucket[row["category"]] += 1
        gsim_bucket[row["category"]] += 1
    for row in n_m_rows:
        if row["side"] == "paired":
            grh_bucket[row["category"]] += 1
            gsim_bucket[row["category"]] += 1
        elif row["side"] == "grh":
            grh_bucket[row["category"]] += 1
        else:
            gsim_bucket[row["category"]] += 1
    for row in one_sided:
        (grh_bucket if row["side"] == "grh" else gsim_bucket)[row["category"]] += 1
    for row in unexplained:
        (grh_bucket if row["side"] == "grh" else gsim_bucket)[row["category"]] += 1

    pairable_n_m_rows = [row for row in n_m_rows if row.get("pairable")]
    mapped_survival_rows = one_to_one + pairable_n_m_rows
    survival_matrix = Counter(row["survival"] for row in one_to_one)
    mapped_survival_matrix = Counter(row["survival"] for row in mapped_survival_rows)
    survival_by_category: defaultdict[str, Counter] = defaultdict(Counter)
    for row in one_to_one:
        survival_by_category[row["category"]][row["survival"]] += 1
    mapped_survival_by_category: defaultdict[str, Counter] = defaultdict(Counter)
    for row in mapped_survival_rows:
        mapped_survival_by_category[row["category"]][row["survival"]] += 1
    plain_rows = [row for row in one_to_one if row["category"] == "plain_register"]
    plain_diff = [row for row in plain_rows if row["survival"] in {"grh_only", "gsim_only"}]
    grh_only_rows = [row for row in mapped_survival_rows if row["survival"] == "grh_only"]
    gsim_only_rows = [row for row in mapped_survival_rows if row["survival"] == "gsim_only"]
    both_dead_rows = [row for row in mapped_survival_rows if row["survival"] == "both_dead"]
    grh_extra_candidates = []
    grh_extra_seen = set()

    def add_grh_extra(row: dict):
        if row.get("side") == "gsim":
            return
        key = (row.get("category", ""), row.get("key", ""), row.get("grh_name", ""))
        if key not in grh_extra_seen:
            grh_extra_seen.add(key)
            grh_extra_candidates.append(dict(row))

    for row in unexplained:
        if row.get("side") == "grh":
            add_grh_extra(row)
    for row in one_sided:
        if row.get("side") == "grh":
            add_grh_extra(row)
    for row in grh_only_rows:
        add_grh_extra(row)
    for row in pipeline_identity_rows:
        # The role pair is an explicit requested watch list even when both
        # implementations serialize a live anchor.
        add_grh_extra(row)
    for row in memory_identity_rows:
        if row.get("grh_post") and not row.get("gsim_post"):
            add_grh_extra(row)
    for row in aggregate_group_rows:
        if row.get("grh_post") and not row.get("gsim_post"):
            add_grh_extra(row)
    grh_extra_rows, grh_extra_summary = build_grh_extra_justification(
        args.grh_after, grh_extra_candidates, args.out_dir,
        gsim_before=gsim_before, gsim_after=gsim_after)
    bucket_counts = {
        "one_to_one": {"grh": len(one_to_one), "gsim": len(one_to_one)},
        "n_m_rules": {
            "grh": sum(row["side"] == "grh" or row["side"] == "paired" for row in n_m_rows),
            "gsim": sum(row["side"] == "gsim" or row["side"] == "paired" for row in n_m_rows),
        },
        "one_sided_known": {
            "grh": sum(row["side"] == "grh" for row in one_sided),
            "gsim": sum(row["side"] == "gsim" for row in one_sided),
        },
        "unexplained": {
            "grh": sum(row["side"] == "grh" for row in unexplained),
            "gsim": sum(row["side"] == "gsim" for row in unexplained),
        },
    }
    width_check = Counter()
    for row in one_to_one:
        if row.get("grh_width") in (None, "") or row.get("gsim_width") in (None, ""):
            width_check["unknown"] += 1
        elif row.get("width_match"):
            width_check["match"] += 1
        else:
            width_check["mismatch"] += 1
    unexplained_examples = sorted(
        unexplained,
        key=lambda row: (row.get("category", ""), row.get("side", ""), row.get("key", "")),
    )[:20]

    output_dir = args.out_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "category", "key", "relation", "grh_name", "gsim_name", "module",
        "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post",
        "survival", "grh_width", "gsim_width", "grh_shape", "gsim_dimension",
        "width_match", "shape_match", "pairable", "side_post", "member_index", "parent_name", "reason",
    ]
    write_tsv(output_dir / "anchors-1to1.tsv", one_to_one, columns)
    write_tsv(output_dir / "anchors-n-m-rules.tsv", n_m_rows, [
        "category", "rule", "key", "relation", "side", "grh_name", "gsim_name",
        "module", "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post",
        "survival", "pairable", "side_post", "group_key", "group_survival",
        "grh_width", "gsim_width", "grh_shape", "gsim_dimension", "reason",
    ])
    known_columns = columns + ["side"]
    write_tsv(output_dir / "anchors-one-sided-known.tsv", one_sided, known_columns)
    write_tsv(output_dir / "anchors-unexplained.tsv", unexplained, known_columns)
    write_tsv(output_dir / "survival-both-alive.tsv", [row for row in mapped_survival_rows if row["survival"] == "both_alive"], columns)
    write_tsv(output_dir / "survival-grh-only.tsv", grh_only_rows, columns)
    write_tsv(output_dir / "survival-gsim-only.tsv", gsim_only_rows, columns)
    write_tsv(output_dir / "survival-both-dead.tsv", both_dead_rows, columns)
    write_tsv(output_dir / "plain-register-survival.tsv", plain_rows, columns)
    write_tsv(output_dir / "memory-identity.tsv", memory_identity_rows, [
        "category", "rule", "key", "grh_name", "semantic_path", "gsim_name",
        "representation", "grh_pre", "gsim_pre", "grh_post", "gsim_post", "survival",
        "grh_width", "gsim_width", "grh_shape", "gsim_dimension", "grh_depth", "gsim_depth",
        "grh_data_width", "depth_match", "width_match", "dimension_match", "member_ids",
        "alive_member_ids", "member_count", "alive_member_count", "method",
    ])
    write_tsv(output_dir / "memory-pipeline-identity.tsv", pipeline_identity_rows, [
        "category", "rule", "key", "grh_name", "semantic_port", "gsim_name",
        "grh_pre", "gsim_pre", "grh_post", "gsim_post", "survival", "grh_width",
        "gsim_width", "role_grh", "role_gsim", "address_width", "method",
    ])
    write_tsv(output_dir / "effect-identity.tsv", effect_identity_rows, [
        "category", "rule", "key", "relation", "side", "grh_name", "gsim_name",
        "module_path", "effect_kind", "grh_line", "gsim_lineno", "grh_pre",
        "gsim_pre", "grh_post", "gsim_post", "survival", "pairable", "side_post",
        "reason",
    ])
    write_tsv(output_dir / "aggregate-member-groups.tsv", aggregate_group_rows, [
        "category", "rule", "key", "grh_name", "gsim_name", "direction",
        "group_survival", "member_detail", "grh_post", "gsim_post", "reason",
    ])
    write_tsv(output_dir / "aggregate-member-detail.tsv", aggregate_rule_member_rows, [
        "rule", "parent_name", "direction", "member_suffix", "grh_name", "gsim_name",
        "grh_post", "gsim_post", "survival", "grh_width", "gsim_width",
    ])
    write_tsv(output_dir / "grh-extra-justification.tsv", grh_extra_rows, [
        "category", "key", "relation", "rule", "grh_name", "gsim_name", "module",
        "name_pattern", "grh_pre", "gsim_pre", "grh_post", "gsim_post", "survival",
        "reason", "root_kind", "root_name", "path_length", "cycle_check", "cycle_only",
        "cycle_state_symbols", "gsim_root_kind", "gsim_root_name", "gsim_root_alive",
        "root_mapping", "divergence_op_id", "divergence_kind", "divergence_semantic_id",
        "divergence_lineno", "divergence_source", "verdict", "mechanism",
        "verdict_reason", "semantic_path", "representation", "method",
    ])

    physical_grh = _physical_grh_inventory(grh_before, grh_before_groups, split)
    regsrc_categories = Counter()
    for key, record in gsim_reg_pre.items():
        if key in gsim_array_exact:
            regsrc_categories["register_array_exact"] += 1
        elif key in gsim_plain:
            regsrc_categories["plain_exact"] += 1
        elif generated_reg_reason(record) == "gsim_depth1_memory_conversion":
            regsrc_categories["depth1_memory_conversion"] += 1
        elif generated_reg_reason(record) == "gsim_zero_width_register":
            regsrc_categories["zero_width"] += 1
        elif generated_reg_reason(record) == "gsim_copy_derived":
            regsrc_categories["copy_derived"] += 1
        elif generated_reg_reason(record) == "gsim_address_generated":
            regsrc_categories["address_generated"] += 1
        else:
            regsrc_categories["unexplained"] += 1
    regsrc_categories["addr_pipeline"] = len(gsim_before["pipeline"])
    regsrc_sum = sum(regsrc_categories.values())
    physical_gsim = {
        "reg_src": len(gsim_before["reg_src"]) + len(gsim_before["pipeline"]),
        "reg_src_categories": dict(sorted(regsrc_categories.items())),
        "reg_src_category_sum": regsrc_sum,
        "reg_src_closed": regsrc_sum == len(gsim_before["reg_src"]) + len(gsim_before["pipeline"]),
        "node_memory": len(init["memories"]),
        "node_types_pre": dict(sorted((key.removeprefix("type:"), value) for key, value in gsim_before["stats"].items() if key.startswith("type:"))),
    }
    logical_counts = {
        "grh": {"total": sum(grh_bucket.values()), "categories": counter_dict(grh_bucket), "category_sum": sum(grh_bucket.values())},
        "gsim": {"total": sum(gsim_bucket.values()), "categories": counter_dict(gsim_bucket), "category_sum": sum(gsim_bucket.values())},
    }
    report = {
        "schema": "wolvrix.f21.anchor-alignment.v2",
        "inputs": {key: str(value) for key, value in {
            "grh_post_split_pre_dce": args.grh_before,
            "grh_post_dce": args.grh_after,
            "gsim_toposort_pre_dce": args.gsim_before,
            "gsim_remove_dead_nodes_post_dce": args.gsim_after,
            "gsim_init": args.gsim_init,
            "gsim_split_array_map": args.gsim_split_map,
            "state_family_report": args.state_family_report,
            "f20_stats_dir": args.f20_stats_dir,
        }.items()},
        "baselines": {"f20_ordinary_register_join": f20_stats},
        "definitions": {
            "normalized_name": "GSIM $$ is normalized to GRH __DOT__; no other spelling is folded",
            "logical_anchor_rows": "Exact state-family rows are expanded by split-map member index; aggregate GRH state declarations stand for their member rows",
            "one_to_one": "Both sides have a pre-DCE anchor under the stated identity key; post-DCE status is compared by the same key",
            "n_m_rule": "Both sides are enumerated, but only an explicit representation/count rule is established",
            "one_sided_known": "The other representation is absent or has a documented known representation difference",
            "unexplained": "An anchor remains after exact joins and documented representation rules",
            "survival": "both_alive, grh_only, gsim_only, or both_dead for exact 1:1 rows; n:m rows use side-inventory survival",
        },
        "inventory": {
            "grh": logical_counts["grh"],
            "gsim": logical_counts["gsim"],
            "logical_anchor_rows": logical_counts,
            "physical": {"grh": physical_grh, "gsim": physical_gsim},
            "raw_scans": {
                "grh_before": grh_before["stats"], "grh_after": grh_after["stats"],
                "gsim_init": init["stats"], "split_map": split["stats"],
                "gsim_before": gsim_before["stats"], "gsim_after": gsim_after["stats"],
            },
        },
        "closure": {
            "grh_total_equals_bucket_sum": logical_counts["grh"]["total"] == logical_counts["grh"]["category_sum"],
            "gsim_total_equals_bucket_sum": logical_counts["gsim"]["total"] == logical_counts["gsim"]["category_sum"],
            "grh_bucket_sum": logical_counts["grh"]["category_sum"],
            "gsim_bucket_sum": logical_counts["gsim"]["category_sum"],
            "state_families": len(split["families"]),
            "state_members": sum(len(family["rows"]) for family in split["families"].values()),
            "physical_grh_kregister_closed": physical_grh["closed"],
            "physical_gsim_regsrc_closed": physical_gsim["reg_src_closed"],
            "grh_extra_total_equals_verdict_sum": grh_extra_summary["total"] == (
                sum(value for key, value in grh_extra_summary["verdict_counts"].items()
                    if key.startswith("legitimate:"))
                + grh_extra_summary["verdict_counts"].get("optimization-gap", 0)
                + grh_extra_summary["verdict_counts"].get("unresolved", 0)
            ),
        },
        "mapping": {
            "one_to_one": {"total": len(one_to_one), "by_category": counter_dict(Counter(row["category"] for row in one_to_one))},
            "n_m_rules": rule_specs,
            "bucket_counts": bucket_counts,
            "one_sided_known": {"total": len(one_sided), "by_side": counter_dict(Counter(row["side"] for row in one_sided)), "by_category": counter_dict(Counter(row["category"] for row in one_sided))},
            "unexplained": {"total": len(unexplained), "by_side": counter_dict(Counter(row["side"] for row in unexplained)), "by_category": counter_dict(Counter(row["category"] for row in unexplained)), "examples": unexplained_examples},
        },
        "survival": {
            "exact_1to1_matrix": complete_survival(survival_matrix),
            "mapped_anchor_matrix": complete_survival(mapped_survival_matrix),
            "by_category": {category: counter_dict(values) for category, values in sorted(survival_by_category.items())},
            "by_category_including_n_m_rules": {
                category: complete_survival(values)
                for category, values in sorted(mapped_survival_by_category.items())
            },
            "plain_register": {
                "mapped": len(plain_rows), "differences": len(plain_diff),
                "matrix": counter_dict(Counter(row["survival"] for row in plain_rows)),
                "top_grh_only": top_modules([row for row in plain_diff if row["survival"] == "grh_only"]),
                "top_gsim_only": top_modules([row for row in plain_diff if row["survival"] == "gsim_only"]),
            },
            "n_m_rule_survival": {
                rule["rule"]: {
                    "grh_pre": rule["grh_pre"], "gsim_pre": rule["gsim_pre"],
                    "grh_post": rule["grh_post"], "gsim_post": rule["gsim_post"],
                    "details": rule.get("details", {}),
                } for rule in rule_specs
            },
            "memory_identity": complete_survival(memory_survival),
            "memory_pipeline_role_pair": complete_survival(pipeline_survival),
            "aggregate_member_groups": complete_survival(aggregate_survival),
        },
        "top_groups": {
            "unexplained": top_modules(unexplained),
            "grh_only": top_modules(grh_only_rows),
            "gsim_only": top_modules(gsim_only_rows),
            "plain_register_differences": top_modules(plain_diff),
        },
        "watch_lists": {
            "gsim_only_array_elements": [
                {"key": row.get("key", ""), "gsim_name": row.get("gsim_name", ""),
                 "survival": row.get("survival", "")}
                for row in one_to_one
                if row.get("category") == "array_state_member"
                and row.get("survival") == "gsim_only"
            ],
        },
        "memory_identity": {
            "rows": len(memory_identity_rows),
            "unmatched": len(memory_unmatched),
            "survival": complete_survival(memory_survival),
            "node_memory_pre": sum(row.get("representation") == "NODE_MEMORY" for row in memory_identity_rows),
            "depth1_converted_pre": sum(row.get("representation") == "REG_SRC_DEPTH1" for row in memory_identity_rows),
            "node_memory_serialized_in_toposort": False,
            "node_memory_serialized_in_post_dce": False,
            "node_memory_survival_method": "any associated Init NODE_MEMORY member ID present as VALID_NODE in the after dump",
            "depth_checks": {
                "mismatch": sum(row.get("depth_match") is False for row in memory_identity_rows),
                "unknown": sum(row.get("depth_match") is None for row in memory_identity_rows),
            },
            "width_checks": {
                "mismatch": sum(row.get("width_match") is False for row in memory_identity_rows),
                "unknown": sum(row.get("width_match") is None for row in memory_identity_rows),
            },
        },
        "effect_identity": effect_identity_summary,
        "grh_extra": {
            **grh_extra_summary,
            "legitimate_rows": [row for row in grh_extra_rows
                                if str(row.get("verdict", "")).startswith("legitimate:")],
        },
        "v1_v2_delta": {
            "register_array_exact_joins": len(gsim_array_exact),
            "register_array_residual_grh": len(unmatched_grh_array) - len(aggregate_grh_used),
            "register_array_residual_gsim": len(unmatched_gsim_array) - len(aggregate_gsim_used),
            "aggregate_groups": len(aggregate_group_rows),
            "plain_register_asymmetric_differences": len(plain_diff),
            "plain_register_grh_only": sum(row.get("survival") == "grh_only" for row in plain_diff),
            "plain_register_gsim_only": sum(row.get("survival") == "gsim_only" for row in plain_diff),
            "not_pairable_n_m_rows": sum(not row.get("pairable") for row in n_m_rows),
        },
        "v2_v3_delta": {
            "effect_identity_rule": True,
            "effect_identity_pairs": effect_identity_summary["pairs"],
            "effect_identity_unmatched_grh": effect_identity_summary["unmatched_grh"],
            "effect_identity_unmatched_gsim": effect_identity_summary["unmatched_gsim"],
            "effect_identity_not_pairable": effect_identity_summary["not_pairable"],
        },
        "sanity_checks": {
            "exact_1to1_width": counter_dict(width_check),
            "clock_reset_presence": {
                "status": "unavailable_in_anchor_records",
                "reason": "The serialized GRH kRegister and GSIM REG_SRC anchor records contain no direct clock/reset fields; clock/reset presence is not used as an identity key.",
            },
        },
        "verdict": {
            "anchor_identity_mapping_complete_enough_for_support_set_comparison": False,
            "reason": "The asymmetric GRH-extra ledger still contains unresolved rows or representation-role rules; support-set comparison must wait for every GRH-extra row to have evidence and for optimization gaps to be addressed. This is a mapping verdict only.",
        },
        "performance": {
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_anchor_report_md(output_dir / "report.md", report)
    return report

if __name__ == "__main__":
    main()
