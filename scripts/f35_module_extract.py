"""Extract an original FIRRTL module and its dependencies for F35."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_MAX_BYTES = 64 * 1024 * 1024
COPY_BYTES = 1024 * 1024
SCAN_LIMIT = 8 * COPY_BYTES
IDENTIFIER = rb"(?:[A-Za-z_][A-Za-z0-9_]*|`[A-Za-z0-9_]+`)"
VERSION = re.compile(rb"FIRRTL +version +6\.0\.0 *(?:;[^\r\n]*)?\r?\n")
CIRCUIT = re.compile(rb"circuit +(" + IDENTIFIER + rb") *: *(%\[\[)?")
DECLARATION = re.compile(
    rb"(?:(?:public +)?(module|extmodule|intmodule|class|extclass)|"
    rb"(layer|type|formal)) +(" + IDENTIFIER + rb")(?=[:=, ])"
)
DEPENDENCY = re.compile(rb"(?:inst|object) +" + IDENTIFIER + rb" +of +(" + IDENTIFIER + rb")(?=[ @;\r\n]|$)")
DEFNAME = re.compile(rb"defname *= *(" + IDENTIFIER + rb") *(?=[@;\r\n]|$)")
RESET_PORT = re.compile(rb"input +(" + IDENTIFIER + rb") *: *(?:const +)?(Reset) *(?=[@;\r\n]|$)")
RESET_TYPES = {"AsyncReset", "UInt<1>"}
# Annotation records have JSON string fields. Match complete strings before
# delimiters so brackets and braces inside blackbox source are ordinary text.
ANNOTATION_TOKEN = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|[{}\]]')
TARGET_MODULE = re.compile(r"[^/>]*")


@dataclass
class Block:
    kind: str
    name: str
    begin: int
    first_line: int
    end: int = 0
    after_line: int = 0
    dependencies: set[str] = field(default_factory=set)
    implementation: str | None = None


def identifier(token: bytes) -> str:
    return token.strip(b"`").decode("ascii")


def lines(stream, limit, first_line=1, *, digest=None):
    number = first_line
    while line := stream.readline(limit + 1):
        if len(line) > limit:
            raise ValueError(f"FIRRTL line {number} exceeds the {limit}-byte read limit")
        if digest is not None:
            digest.update(line)
        yield number, line
        number += 1


def annotations(source_lines, initial, limit, *, capture):
    # The opening %[[ was consumed with the circuit header. Read records
    # independently, keeping at most one record in memory.
    record = bytearray() if capture else None
    first_line = None
    closed_array = False
    number, line = initial
    while True:
        start = 0 if first_line is not None else None
        for token in ANNOTATION_TOKEN.finditer(line):
            marker = token.group()
            if marker == b"{":
                if start is not None or closed_array:
                    raise ValueError(f"unexpected FIRRTL annotation object on line {number}")
                start, first_line = token.start(), number
            elif marker == b"}":
                if start is None:
                    raise ValueError(f"unexpected closing annotation brace on line {number}")
                if capture:
                    record.extend(line[start:token.end()])
                    if len(record) > limit:
                        raise ValueError(f"FIRRTL annotation on line {first_line} exceeds {limit} bytes")
                    item = json.loads(record)
                    if (not isinstance(item, dict) or not isinstance(item.get("target"), str) or
                        not isinstance(item.get("class"), str)):
                        raise ValueError(f"invalid FIRRTL annotation on line {first_line}")
                    yield first_line, number, item
                    record.clear()
                start = None
                first_line = None
            elif marker == b"]" and start is None:
                if closed_array:
                    return
                closed_array = True
        if start is not None and capture:
            record.extend(line[start:])
            if len(record) > limit:
                raise ValueError(f"FIRRTL annotation on line {first_line} exceeds {limit} bytes")
        try:
            number, line = next(source_lines)
        except StopIteration:
            raise ValueError("unterminated FIRRTL circuit annotations") from None


def index_circuit(stream, digest, module):
    source_lines = lines(stream, SCAN_LIMIT, digest=digest)
    header = []
    offset = 0
    for number, line in source_lines:
        start = offset
        offset += len(line)
        if line.lstrip().startswith(b";") or not line.strip():
            continue
        if not header and VERSION.fullmatch(line):
            header.append(number)
            continue
        if not header or not (match := CIRCUIT.match(line)):
            raise ValueError(f"expected a FIRRTL 6.0.0 circuit header on line {number}")
        circuit = identifier(match[1])
        annotation_start = (start + match.end(), number) if match[2] else None
        header.append(number)
        break
    else:
        raise ValueError("missing FIRRTL circuit header")

    if annotation_start:
        for _ in annotations(source_lines, (number, line[match.end():]), SCAN_LIMIT, capture=False):
            raise AssertionError("annotation indexing must not yield records")
        offset = stream.tell()

    blocks = []
    reset_inputs = {}
    block = None
    circuit_indent = None
    after_line = header[-1] + 1
    for number, line in source_lines:
        start = offset
        offset += len(line)
        after_line = number + 1
        content = line.lstrip(b" ")
        if content.startswith((b";", b"\r", b"\n")) or not content:
            continue
        indent = len(line) - len(content)
        if circuit_indent is None:
            if indent == 0:
                raise ValueError(f"expected indented circuit declarations on line {number}")
            circuit_indent = indent
        if indent == circuit_indent and (match := DECLARATION.match(content)):
            if block is not None:
                block.end, block.after_line = start, number
            kind = (match[1] or match[2]).decode("ascii")
            block = Block(kind, identifier(match[3]), start, number)
            blocks.append(block)
        elif block is not None and indent > circuit_indent:
            if content.startswith((b"inst ", b"object ")) and (match := DEPENDENCY.match(content)):
                block.dependencies.add(identifier(match[1]))
            elif block.kind == "extmodule" and content.startswith(b"defname") and (match := DEFNAME.match(content)):
                block.implementation = identifier(match[1])
            elif block.kind == "module" and block.name == module and content.startswith(b"input "):
                if match := RESET_PORT.match(content):
                    reset_inputs[identifier(match[1])] = (start + indent + match.start(2), number)
    if block is not None:
        block.end, block.after_line = offset, after_line
    return circuit, annotation_start, header, blocks, reset_inputs


def selected_blocks(blocks, module):
    modules = {}
    for block in blocks:
        if block.kind in {"layer", "type", "formal"}:
            continue
        if block.name in modules:
            raise ValueError(f"duplicate FIRRTL module or class {block.name!r}")
        modules[block.name] = block
    if module not in modules or modules[module].kind != "module":
        raise ValueError(f"FIRRTL module {module!r} is missing or lacks an internal body")

    selected = set()
    pending = [module]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in modules:
            raise ValueError(f"{module!r} depends on undeclared module or class {name!r}")
        selected.add(name)
        pending.extend(sorted(modules[name].dependencies))
    return [block for block in blocks if block.kind in {"layer", "type"} or (
        block.kind != "formal" and block.name in selected
    )], selected


def source_state(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def extract_module(source: Path, module: str, output: Path, *, max_bytes: int = DEFAULT_MAX_BYTES,
                   reset_ports: dict[str, str] | None = None) -> dict:
    if max_bytes <= 0:
        raise ValueError("the FIRRTL extraction size limit must be positive")
    source = source.resolve(strict=True)
    output = output.resolve()
    if source == output or (output.exists() and output.samefile(source)):
        raise ValueError("the FIRRTL source and extraction output must be different files")
    module = module.strip("`")
    reset_ports = reset_ports or {}
    for name, kind in reset_ports.items():
        if kind not in RESET_TYPES:
            raise ValueError(f"invalid reset type {kind!r} for {name!r}")
    with source.open("rb") as stream:
        state = os.fstat(stream.fileno())
        source_digest = hashlib.sha256()
        circuit, annotation_start, header, blocks, reset_inputs = index_circuit(stream, source_digest, module)
        selected, module_names = selected_blocks(blocks, module)
        if missing := reset_ports.keys() - reset_inputs.keys():
            names = ", ".join(sorted(missing))
            raise ValueError(f"{module!r} has no scalar abstract Reset input named {names}")
        body_bytes = sum(block.end - block.begin for block in selected)
        body_bytes += sum(len(kind) - len("Reset") for kind in reset_ports.values())
        if body_bytes >= max_bytes:
            raise ValueError(f"{module!r} requires {body_bytes} FIRRTL body bytes, exceeding the "
                             f"{max_bytes}-byte limit for the extracted circuit")

        output.parent.mkdir(parents=True, exist_ok=True)
        output_bytes = 0
        digest = hashlib.sha256()
        line_map = [
            {"kind": "version", "output_start": 1, "output_end": 1,
             "source_start": header[0], "source_end": header[0]},
            {"kind": "circuit", "output_start": 2, "output_end": 2,
             "source_start": header[1], "source_end": header[1]},
        ]
        copied_annotations = 0
        annotation_kinds = set()
        reset_bindings = []
        with tempfile.TemporaryDirectory(dir=output.parent, prefix=f".{output.name}.") as staging:
            staged = Path(staging) / output.name
            target = staged.open("wb")

            def write(data):
                nonlocal output_bytes
                output_bytes += len(data)
                if output_bytes > max_bytes:
                    raise ValueError(f"{module!r} exceeds the {max_bytes}-byte FIRRTL extraction limit")
                digest.update(data)
                target.write(data)

            def copy(count):
                while count:
                    data = stream.read(min(count, COPY_BYTES))
                    if not data:
                        raise ValueError("FIRRTL source ended during extraction")
                    write(data)
                    count -= len(data)

            with target:
                module_token = module if module[0].isalpha() or module[0] == "_" else f"`{module}`"
                write(f"FIRRTL version 6.0.0\ncircuit {module_token} :".encode("ascii"))
                output_line = 2
                if annotation_start is not None:
                    start, number = annotation_start
                    stream.seek(start)
                    records = lines(stream, SCAN_LIMIT, number)
                    initial = next(records, (number, b""))
                    for first, last, record in annotations(records, initial, SCAN_LIMIT, capture=True):
                        circuit_target, separator, component = record["target"].partition("|")
                        name = TARGET_MODULE.match(component).group()
                        if name not in module_names:
                            continue
                        if circuit_target == f"~{circuit}":
                            record["target"] = f"~{module}{separator}{component}"
                        write(b",\n" if copied_annotations else b"%[[\n")
                        write(b"  " + json.dumps(record, ensure_ascii=True).encode("ascii"))
                        output_line += 1
                        line_map.append({"kind": "annotation", "output_start": output_line, "output_end": output_line,
                                         "source_start": first, "source_end": last})
                        copied_annotations += 1
                        annotation_kinds.add(record["class"])
                    if copied_annotations:
                        write(b"\n]]")
                        output_line += 1
                write(b"\n")
                output_line += 1

                for block in selected:
                    stream.seek(block.begin)
                    if block.kind == "module" and block.name == module:
                        for name, (offset, number) in reset_inputs.items():
                            if name in reset_ports:
                                copy(offset - stream.tell())
                                if stream.read(len("Reset")) != b"Reset":
                                    raise ValueError("FIRRTL reset declaration changed during extraction")
                                kind = reset_ports[name]
                                write(kind.encode("ascii"))
                                reset_bindings.append({
                                    "port": name, "source_type": "Reset", "output_type": kind,
                                    "source_line": number, "output_line": output_line + number - block.first_line,
                                })
                    copy(block.end - stream.tell())
                    line_count = block.after_line - block.first_line
                    line_map.append({"kind": block.kind, "name": block.name, "output_start": output_line,
                                     "output_end": output_line + line_count - 1, "source_start": block.first_line,
                                     "source_end": block.after_line - 1})
                    output_line += line_count
            if source_state(source.stat()) != source_state(state):
                raise ValueError("FIRRTL source changed during extraction")
            staged.replace(output)

    external = {block.name: block.implementation or block.name for block in selected if block.kind == "extmodule"}
    return {
        "schema": "wolvrix.f35-module-extraction.v1",
        "source": str(source),
        "source_bytes": state.st_size,
        "source_sha256": source_digest.hexdigest(),
        "source_mtime_ns": state.st_mtime_ns,
        "source_circuit": circuit,
        "module": module,
        "output": str(output),
        "output_bytes": output_bytes,
        "output_sha256": digest.hexdigest(),
        "max_bytes": max_bytes,
        "modules": [block.name for block in selected if block.name in module_names and block.kind not in {"layer", "type"}],
        "external_modules": list(external),
        "external_implementations": external,
        "abstract_reset_ports": [name for name in reset_inputs if name not in reset_ports],
        "reset_bindings": reset_bindings,
        "annotations": {"count": copied_annotations, "classes": sorted(annotation_kinds)},
        "line_map": line_map,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--module", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    try:
        for path in (args.source, args.output):
            if args.manifest.resolve() == path.resolve() or (
                args.manifest.exists() and path.exists() and args.manifest.samefile(path)
            ):
                raise ValueError("the extraction manifest must be a separate file")
        manifest = extract_module(args.source, args.module, args.output, max_bytes=args.max_bytes)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"f35_module={manifest['module']} modules={len(manifest['modules'])} "
              f"bytes={manifest['output_bytes']} manifest={args.manifest}")
        return 0
    except (OSError, ValueError) as error:
        print(f"[f35-module-extract] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
