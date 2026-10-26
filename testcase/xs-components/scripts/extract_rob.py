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


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finish_file(temporary, target):
    if target.is_file() and file_digest(temporary) == file_digest(target):
        temporary.unlink()
    else:
        temporary.replace(target)


def write_if_changed(path, text):
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "output", "work"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    generation_log = args.source.parent / "time.log"
    generation_text = generation_log.read_text()
    if not re.search(r"--preserve-aggregate=all(?:\s|\")", generation_text) or \
            not re.search(r"Exit status: 0\s*$", generation_text):
        raise ValueError(f"missing successful preserve-aggregate=all generation record: {generation_log}")
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
    temporary_fir = args.work / "Rob.fir.partial"
    temporary_resolved = args.work / "Rob_resolved.fir.partial"
    with source.open("rb") as stream, temporary_fir.open("wb") as out, \
            temporary_resolved.open("wb") as resolved:
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
    finish_file(temporary_fir, output_fir)
    finish_file(temporary_resolved, args.work / "Rob_resolved.fir")
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
        target = sv_dir / path.name
        if not target.is_file() or file_digest(target) != digest(data):
            shutil.copyfile(path, target)
        sv_modules[name] = {"source": str(path), "bytes": len(data), "sha256": digest(data),
                            "instances": children}
        pending.extend(typ for typ, _inst in children)
    sv_paths = [sv_dir / f"{name}.sv" for name in sorted(sv_modules)]
    repo = Path(__file__).resolve().parents[3]
    assert_source = repo / "testcase/xiangshan/difftest/src/test/vsrc/common/assert.v"
    assert_target = sv_dir / "assert.v"
    if not assert_target.is_file() or file_digest(assert_source) != file_digest(assert_target):
        shutil.copyfile(assert_source, assert_target)
    sv_paths.insert(0, assert_target)
    expected_files = {path.name for path in sv_paths}
    for old_path in sv_dir.iterdir():
        if old_path.suffix in (".sv", ".v") and old_path.name not in expected_files:
            old_path.unlink()
    write_if_changed(args.output / "rtl.f", "".join(f"rtl/{p.name}\n" for p in sv_paths))
    write_if_changed(args.work / "rtl.f", "".join(f"{p.resolve()}\n" for p in sv_paths))
    write_if_changed(args.work / "read_args.txt", f"-I\n{sv_dir.resolve()}\n-D\nDIFFTEST\n")
    manifest = {
        "instance": "cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rob",
        "top": "Rob", "source_firrtl": str(source), "source_firrtl_sha256": hasher.hexdigest(),
        "preserve_aggregate": "all",
        "generation_record": {"source": str(generation_log), "sha256": file_digest(generation_log)},
        "firrtl_sha256": digest(output_fir.read_bytes()), "firrtl_modules": records,
        "sv_modules": sv_modules,
        "dpi_declaration": {"source": str(assert_source), "sha256": digest(assert_source.read_bytes())},
        "gsim_boundary_adaptation": "Only Rob.input reset changes from abstract Reset to UInt<1> in work/Rob_resolved.fir, matching the synchronous SV reset. Original extracted Rob.fir remains verbatim.",
        "extraction": "Module bodies copied verbatim; FIRRTL circuit name changed to Rob and design-level annotations omitted. SV module bodies and macros unchanged.",
        "boundary": "Standalone Rob ports are unconstrained; includes transitive child modules.",
    }
    write_if_changed(args.output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"SV: {len(sv_paths)} modules, {sum(r['bytes'] for r in sv_modules.values())} bytes", flush=True)
    print(f"wrote {args.output / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
