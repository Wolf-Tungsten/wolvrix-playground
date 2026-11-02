#!/usr/bin/env python3
"""Freeze generated DiffTest inputs beside a FIRRTL flow and identify builds.

The Make entry point supplies --firrtl, --generated-dir, --xs-root,
--output-dir and repeated --configuration key=value arguments. The first call
copies generated resources (including difftest-state.h) into generated-src.
Later calls validate that snapshot and the FIRRTL digest without rereading the
shared generated directory. --refresh explicitly replaces the pairing and
archives the old files; capture does not prove which elaboration produced them.

snapshot-identity.json records the fixed pairing. build-identity.json records
the current common harness sources, resolved tools and supplied options, with
history in build-identities/. Its unchanged mtime lets Make use it as a harness
object prerequisite. This identity records inputs; it neither proves design
equivalence nor adds flag tracking to the generated model library's Makefile.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid


SNAPSHOT_SCHEMA = "wolvrix.xs.firrtl-harness-snapshot.v1"
BUILD_SCHEMA = "wolvrix.xs.firrtl-harness-build.v1"
HARNESS_ENVIRONMENT_KEYS = (
    "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CPATH", "CPLUS_INCLUDE_PATH",
    "LIBRARY_PATH", "LD_LIBRARY_PATH", "ARFLAGS", "NO_DIFF", "NUM_CORES",
    "WITH_CHISELDB", "WITH_CONSTANTIN", "WITH_IPC", "DIFFTEST_PERFCNT", "DIFFTEST_QUERY",
    "EMU_OPTIMIZE", "EMU_THREADS", "EMU_SNAPSHOT", "EMU_COVERAGE", "EMU_TRACE", "EMU_TRACE_ALL",
    "PGO_CFLAGS", "PGO_LDFLAGS", "SIM_CXXFLAGS", "SIM_LDFLAGS", "GRHSIM_CXXFLAGS",
    "GRHSIM_MODEL_CXXFLAGS", "WOLVRIX_GRHSIM_WAVEFORM", "WOLVRIX_GRHSIM_PERF",
    "WOLVRIX_GRHSIM_SN_TIMING", "FPGA", "FPGA_SIM", "REF", "WITH_DRAMSIM3", "DRAMSIM3_HOME",
    "OUTPUT_CPI_TO_FILE", "PMEM_CHECK", "RELEASE", "SHOW_SCREEN", "IMAGE_GZ_COMPRESS",
    "NO_ZSTD_COMPRESSION", "IMAGE_ELF", "WITH_SPIKE_DASM", "WITH_RUNAHEAD", "ENABLE_SIMFRONTEND",
    "XFUZZ", "FUZZER_LIB", "FUZZING", "FIRRTL_COVER", "LLVM_COVER", "IOTRACE_ZSTD", "CXX_NO_WARNING",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_identity(path):
    path = Path(path)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": checksum}


def tree_identity(directory):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"not a regular input directory: {directory}")
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"input symlink must be materialized before snapshot: {path}")
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = file_identity(path)
    return files


def write_json(path, value):
    path = Path(path)
    contents = json.dumps(value, indent=2, sort_keys=True) + "\n"
    # This file can be a Make prerequisite: unchanged inputs must keep its mtime.
    if path.is_file() and path.read_text() == contents:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    pending.write_text(contents)
    pending.replace(path)


def common_harness_identity(xs_root):
    """Cover shared harness inputs, independently of the frozen generated files."""
    xs_root = Path(xs_root)
    difftest = xs_root / "difftest"
    if not (difftest / "Makefile").is_file():
        raise ValueError(f"missing DiffTest Makefile: {difftest / 'Makefile'}")
    paths = set(difftest.glob("*.mk")) | {difftest / "Makefile"}
    for directory in (difftest / "config", difftest / "src/test/csrc"):
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    for name in ("Makefile", "build.sc", "build.mill"):
        if (xs_root / name).is_file():
            paths.add(xs_root / name)
    files = {path.relative_to(xs_root).as_posix(): file_identity(path) for path in sorted(paths)}
    return {"root": str(xs_root), "files": files, "sha256": digest(files)}


def parse_configuration(entries):
    result = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        if not separator or not key or key in result:
            raise ValueError(f"expected a unique configuration key=value: {entry}")
        result[key] = value
    return result


def make_variable_overrides(makeflags):
    """Retain command-line assignments, excluding GNU Make scheduling options."""
    # GNU Make backslash-escapes spaces in exported MAKEFLAGS. Literal quote
    # characters belong to assignment values; they are not shell delimiters.
    lexer = shlex.shlex(makeflags, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.quotes = ""
    overrides = {}
    for token in lexer:
        key, separator, value = token.partition("=")
        if separator and key and not key.startswith("-"):
            overrides[key] = value
    return dict(sorted(overrides.items()))


def tool_identities(configuration):
    defaults = {"CC": shutil.which("clang") or shutil.which("gcc") or "cc",
                "CXX": shutil.which("clang++") or shutil.which("g++") or "c++",
                "AR": "ar", "MAKE": "make", "PYTHON": sys.executable}
    result = {}
    for key, default in defaults.items():
        command = configuration.get(key) or os.environ.get(key) or default
        arguments = shlex.split(command)
        executable = shutil.which(arguments[0]) if arguments else None
        if not executable:
            raise ValueError(f"build tool not found for {key}: {command}")
        executable = str(Path(executable).resolve())
        version = subprocess.run([*arguments, "--version"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, check=False)
        result[key] = {"command": command, "executable": executable,
                       **file_identity(executable), "version": version.stdout.strip(),
                       "version_exit_code": version.returncode}
    return result


def validate_snapshot(identity, output_dir, firrtl_identity):
    if identity.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("unsupported harness snapshot identity")
    payload = {key: value for key, value in identity.items() if key != "sha256"}
    if identity.get("sha256") != digest(payload):
        raise ValueError("harness snapshot identity is damaged")
    if identity.get("firrtl", {}).get("identity") != firrtl_identity:
        raise ValueError("FIRRTL differs from the harness snapshot; select its matching flow or use --refresh")
    actual = tree_identity(output_dir / "generated-src")
    if actual != identity.get("generated", {}).get("files"):
        raise ValueError("harness snapshot files differ from their identity; restore them or use --refresh")


def prepare_harness(*, firrtl, generated_dir, xs_root, output_dir, configuration=None, refresh=False):
    firrtl = Path(firrtl).resolve()
    generated_dir = Path(generated_dir).absolute()
    xs_root = Path(xs_root).resolve()
    output_dir = Path(output_dir).absolute()
    configuration = dict(configuration or {})
    if output_dir == generated_dir or generated_dir in output_dir.parents:
        raise ValueError("harness output must be outside the generated source directory")
    firrtl_identity = file_identity(firrtl)
    common = common_harness_identity(xs_root)
    identity_path = output_dir / "snapshot-identity.json"
    snapshot_dir = output_dir / "generated-src"
    if output_dir.is_symlink() or snapshot_dir.is_symlink():
        raise ValueError("harness output directories must not be symlinks")
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
        if not isinstance(identity, dict):
            raise ValueError("invalid harness snapshot identity")
        if not refresh:
            validate_snapshot(identity, output_dir, firrtl_identity)
    elif snapshot_dir.exists():
        raise ValueError(f"refusing to replace an unrecorded harness directory: {snapshot_dir}")
    else:
        identity = None

    if identity is None or refresh:
        if not (generated_dir / "difftest-state.h").is_file():
            raise ValueError(f"missing generated difftest-state.h in {generated_dir}; provide matching Chisel resources")
        files = tree_identity(generated_dir)
        # Keep partial work for diagnosis, and preserve every old snapshot on refresh.
        output_dir.mkdir(parents=True, exist_ok=True)
        pending = output_dir / ("snapshot-pending-" + uuid.uuid4().hex)
        shutil.copytree(generated_dir, pending)
        if tree_identity(pending) != files or tree_identity(generated_dir) != files:
            raise ValueError(f"generated harness files changed while being copied; partial snapshot: {pending}")
        if file_identity(firrtl) != firrtl_identity:
            raise ValueError(f"FIRRTL changed while harness files were being copied; partial snapshot: {pending}")
        if identity_path.exists():
            archive = output_dir / "snapshots" / uuid.uuid4().hex
            archive.mkdir(parents=True)
            if snapshot_dir.exists():
                snapshot_dir.rename(archive / "generated-src")
            identity_path.rename(archive / "snapshot-identity.json")
        pending.rename(snapshot_dir)
        identity = {"schema": SNAPSHOT_SCHEMA,
                    "firrtl": {"path": str(firrtl), "identity": firrtl_identity},
                    "generated": {"source_directory": str(generated_dir),
                                  "snapshot_directory": str(snapshot_dir), "files": files,
                                  "sha256": digest(files)},
                    "common_harness_at_capture": common,
                    "association": "captured together; elaboration equivalence is not inferred"}
        identity["sha256"] = digest(identity)
        write_json(identity_path, identity)

    environment = {key: os.environ[key] for key in HARNESS_ENVIRONMENT_KEYS if key in os.environ}
    script = Path(__file__).resolve()
    build = {"schema": BUILD_SCHEMA, "snapshot_sha256": identity["sha256"],
             "firrtl": {"path": str(firrtl), "identity": firrtl_identity},
             "generated_directory": str(snapshot_dir), "common_harness": common,
             "common_harness_matches_capture": common == identity["common_harness_at_capture"],
             "configuration": configuration, "environment": environment,
             "make_variable_overrides": make_variable_overrides(os.environ.get("MAKEFLAGS", "")),
             "tools": tool_identities(configuration),
             "identity_script": {"path": str(script), **file_identity(script)},
             "workflow_makefile": {"path": str(script.parent.parent / "Makefile"),
                                   **file_identity(script.parent.parent / "Makefile")},
             "design_compatibility": "not inferred from build identity"}
    build["sha256"] = digest(build)
    write_json(output_dir / "build-identities" / (build["sha256"] + ".json"), build)
    write_json(output_dir / "build-identity.json", build)
    return build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--xs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--configuration", action="append", default=[])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        build = prepare_harness(firrtl=args.firrtl, generated_dir=args.generated_dir,
            xs_root=args.xs_root, output_dir=args.output_dir,
            configuration=parse_configuration(args.configuration), refresh=args.refresh)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"FIRRTL harness: {error}\n")
    print(f"FIRRTL harness: {build['generated_directory']} (build {build['sha256']})")


if __name__ == "__main__":
    main()
