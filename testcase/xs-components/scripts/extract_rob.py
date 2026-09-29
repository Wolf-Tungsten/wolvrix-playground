#!/usr/bin/env python3
"""Copy the exact Rob FIRRTL and SV dependency closures, preserving source bytes."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "output", "work"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    source = args.source / "SimTop.fir"
    module_re = re.compile(rb"^  (module|extmodule|intmodule) (\S+) :")
    inst_re = re.compile(rb"^\s*inst (\S+) of ([^ \r\n\[]+)")
    modules = {}
    current = None
    offset = 0
    hasher = hashlib.sha256()
    print(f"indexing {source}", flush=True)
    with source.open("rb") as stream:
        for lineno, line in enumerate(stream, 1):
            hasher.update(line)
            match = module_re.match(line)
            if match:
                if current:
                    modules[current]["end"] = offset
                current = match[2].decode()
                if current in modules:
                    raise ValueError(f"duplicate FIRRTL module {current}")
                modules[current] = {"start": offset, "line": lineno,
                                    "kind": match[1].decode(), "instances": []}
            match = inst_re.match(line)
            if match and current:
                modules[current]["instances"].append([match[1].decode(), match[2].decode()])
            offset += len(line)
    modules[current]["end"] = offset
    needed = set()
    pending = ["Rob"]
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        pending.extend(child for _instance, child in modules[name]["instances"])
    ordered = sorted(needed, key=lambda name: modules[name]["start"])
    output_fir = args.output / "Rob.fir"
    records = []
    with source.open("rb") as stream, output_fir.open("wb") as out, \
            (args.work / "Rob_resolved.fir").open("wb") as resolved:
        out.write(b"FIRRTL version 6.0.0\ncircuit Rob :\n")
        resolved.write(b"FIRRTL version 6.0.0\ncircuit Rob :\n")
        for name in ordered:
            record = modules[name]
            stream.seek(record["start"])
            data = stream.read(record["end"] - record["start"])
            out.write(data)
            if name == "Rob":
                adapted, count = re.subn(rb"(?m)^(    input reset : )Reset( )", rb"\g<1>UInt<1>\2", data)
                if count != 1:
                    raise ValueError("expected exactly one abstract top reset port")
                resolved.write(adapted)
            else:
                resolved.write(data)
            records.append({"module": name, **record, "sha256": digest(data)})
    print(f"FIRRTL: {len(ordered)} modules, {output_fir.stat().st_size} bytes", flush=True)

    sv_dir = args.output / "rtl"
    sv_dir.mkdir(exist_ok=True)
    # firtool split-verilog emits unparameterized instances as 'Type inst ('.
    sv_inst = re.compile(rb"^  ([A-Za-z_][\w$]*)\s+([A-Za-z_][\w$]*)\s*\(", re.MULTILINE)
    sv_modules = {}
    pending = ["Rob"]
    while pending:
        name = pending.pop()
        if name in sv_modules:
            continue
        path = args.source / f"{name}.sv"
        data = path.read_bytes()
        definitions = re.findall(rb"^module\s+([A-Za-z_][\w$]*)\s*\(", data, re.MULTILINE)
        if definitions != [name.encode()]:
            raise ValueError(f"unexpected split-verilog definitions: {path}")
        children = [[typ.decode(), instance.decode()] for typ, instance in sv_inst.findall(data)]
        missing = [typ for typ, _inst in children if not (args.source / f"{typ}.sv").is_file()]
        if missing:
            raise ValueError(f"missing SV dependencies of {name}: {missing}")
        shutil.copyfile(path, sv_dir / path.name)
        sv_modules[name] = {"source": str(path), "bytes": len(data), "sha256": digest(data),
                            "instances": children}
        pending.extend(typ for typ, _inst in children)
    sv_paths = [sv_dir / f"{name}.sv" for name in sorted(sv_modules)]
    repo = Path(__file__).resolve().parents[3]
    assert_source = repo / "testcase/xiangshan/difftest/src/test/vsrc/common/assert.v"
    assert_target = sv_dir / "assert.v"
    shutil.copyfile(assert_source, assert_target)
    sv_paths.insert(0, assert_target)
    (args.output / "rtl.f").write_text("".join(f"rtl/{p.name}\n" for p in sv_paths))
    (args.work / "rtl.f").write_text("".join(f"{p.resolve()}\n" for p in sv_paths))
    (args.work / "read_args.txt").write_text(f"-I\n{sv_dir.resolve()}\n-D\nDIFFTEST\n")
    manifest = {
        "instance": "cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rob",
        "top": "Rob", "source_firrtl": str(source), "source_firrtl_sha256": hasher.hexdigest(),
        "firrtl_sha256": digest(output_fir.read_bytes()), "firrtl_modules": records,
        "sv_modules": sv_modules,
        "dpi_declaration": {"source": str(assert_source), "sha256": digest(assert_source.read_bytes())},
        "gsim_boundary_adaptation": "Only Rob.input reset changes from abstract Reset to UInt<1> in work/Rob_resolved.fir, matching the synchronous SV reset. Original extracted Rob.fir remains verbatim.",
        "extraction": "Module bodies copied verbatim; FIRRTL circuit name changed to Rob and design-level annotations omitted. SV module bodies and macros unchanged.",
        "boundary": "Standalone Rob ports are unconstrained; includes transitive child modules.",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"SV: {len(sv_paths)} modules, {sum(r['bytes'] for r in sv_modules.values())} bytes", flush=True)
    print(f"wrote {args.output / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
