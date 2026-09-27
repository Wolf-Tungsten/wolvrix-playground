"""Check a mapped checkpoint's semantic sections across GRH round-trip renumbering.

GRH JSON reload compacts source operation/value IDs. GrhSIM records those IDs
in Origin.sourceIndex and private __event_<operation>_<edge> names. They are
annotations, not GrhSIM IDs. Every other array field must remain identical.
"""

import re


EVENT_NAME = re.compile(r"__event_(\d+)_(\d+)")


def source_renumber_identity(old, new):
    """Return (errors, notes); never mutate either checkpoint."""
    errors, notes = [], []
    keys = set(old) - {"mappings"}
    if keys != set(new) - {"mappings"}:
        return ["top-level section keys differ"], notes
    for key in sorted(keys - {"origins", "strings"}):
        if old[key] != new[key]:
            errors.append(f"section '{key}' differs")
    a, b = old.get("origins", []), new.get("origins", [])
    strings_a, strings_b = old.get("strings", []), new.get("strings", [])
    if len(a) != len(b) or len(strings_a) != len(strings_b):
        return errors + ["origin/string array length differs"], notes
    pairs = set()
    renamed_origins = 0
    for left, right in zip(a, b):
        if len(left) != 11 or len(right) != 11 or left[:3] != right[:3] or left[4:] != right[4:]:
            errors.append("origin fields other than sourceIndex differ")
            break
        if not 0 < left[1] <= len(strings_a):
            errors.append("invalid origin sourceKind")
            break
        kind_a, kind_b = strings_a[left[1] - 1], strings_b[right[1] - 1]
        if left[3] != right[3]:
            renamed_origins += 1
            if kind_a != kind_b or kind_a not in {"grh.operation", "grh.value", "grh.port", "grh.event"}:
                errors.append(f"sourceIndex changed for unsupported sourceKind {kind_a}")
                break
        if kind_a == kind_b == "grh.event":
            pairs.add((left[3], right[3]))
    changed = set()
    for sid, (left, right) in enumerate(zip(strings_a, strings_b), 1):
        if left == right:
            continue
        x, y = EVENT_NAME.fullmatch(left), EVENT_NAME.fullmatch(right)
        if not x or not y or x[2] != y[2] or (int(x[1]), int(y[1])) not in pairs:
            errors.append(f"string {sid} is not a proven GRH event rename")
            break
        changed.add(sid)

    # A matching spelling alone is insufficient: the string table can be shared
    # by public names or op/parameter kinds. Only private history state names
    # (or now-unused strings) may change.
    forbidden = {old.get("name", 0)}
    for row in old.get("dialects", []):
        forbidden.update(row)
    for row in old.get("types", []):
        forbidden.add(row[1])
    for section in ("inputs", "outputs"):
        forbidden.update(row[1] for row in old.get(section, []))
    forbidden.update(row[0] for row in old.get("interface", []))
    forbidden.update(row[2] for row in old.get("values", []))
    for row in old.get("functions", []):
        forbidden.update(row[1:4])
        forbidden.update(arg[0] for arg in row[6])
    for row in old.get("operations", []):
        forbidden.update(row[1:3])
        forbidden.update(parameter[0] for parameter in row[7])
    for model in (old, new):
        for row in model.get("mappings", []):
            forbidden.update(row[:2])
            forbidden.update(parameter[0] for parameter in row[3])
    for row in old.get("init", []):
        for step in row[1]:
            forbidden.add(step[0])
            forbidden.update(parameter[0] for parameter in step[1])
    for row in a:
        forbidden.update(row[i] for i in (1, 2, 4, 9, 10))
    for row in old.get("states", []):
        if row[1] not in changed:
            continue
        origin = a[row[3] - 1] if 0 < row[3] <= len(a) else None
        if origin is None or strings_a[origin[1] - 1] != "grh.event":
            errors.append("renamed state is not an event history")
    if changed & forbidden:
        errors.append("event rename also changes a public name or semantic string")
    notes.append(f"GRH sourceIndex changes: {renamed_origins}; proven private event names: {len(changed)}")
    return errors, notes
