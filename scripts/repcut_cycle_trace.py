#!/usr/bin/env python3
"""Build isolated wrapper-only probes, then collect full-cycle F/G AB/BA traces.

The instrumented binaries are diagnostic, not ordinary walltime benchmarks.
All model archive members remain byte-identical to their respective source.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import repcut_cost_model_compare as common
import repcut_formal_zero_thp_compare as thp

ROOT = common.REPO
HERE = ROOT / "build/repcut_grhsim_20260925/active_dispatch_20261003"
DEFAULT_SOURCES = {
    "baseline": HERE / "shared_deferred_formal_20261011/candidate",
    "candidate": HERE / "dirty_input_bridge_20261012/formal/candidate",
}
DEFAULT_OUTPUT = HERE / "dirty_input_bridge_20261012/formal/cycle_trace_20261013"
LLVM = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin")
from repcut_cycle_instrument import instrument, SUFFIXES


def archive_hashes(path):
    data = path.read_bytes()
    assert data[:8] == b"!<arch>\n", path
    pos, names, result = 8, b"", {}
    while pos < len(data):
        header = data[pos:pos + 60]
        assert header[58:] == b"`\n", (path, pos)
        name = header[:16].decode().strip()
        size = int(header[48:58])
        payload = memoryview(data)[pos + 60:pos + 60 + size]
        if name == "//":
            names = bytes(payload)
        elif name not in ("/", "/SYM64/"):
            if name.startswith("/"):
                offset = int(name[1:])
                name = names[offset:names.index(b"/\n", offset)].decode()
            else:
                name = name.rstrip("/")
            assert name not in result, name
            result[name] = hashlib.sha256(payload).hexdigest()
        pos += 60 + size + size % 2
    return result


def align_object(path):
    data = path.read_bytes()
    assert data[:6] == b"\x7fELF\x02\x01", path
    offset = struct.unpack_from("<Q", data, 40)[0]
    size, count, strings = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * size) for i in range(count)]
    row = sections[strings]
    names = data[row[4]:row[4] + row[5]]
    flags = []
    for row in sections:
        if row[2] & 4 and row[5]:
            name = names[row[0]:names.index(b"\0", row[0])].decode()
            flags.append(f"--set-section-alignment={name}={max(64, row[8])}")
    subprocess.run([str(LLVM / "llvm-objcopy"), *flags, str(path)], check=True)



def link_harness(dest: Path, model_dir: Path, model_lib: Path, compiler_flags=()) -> Path:
    """Link an isolated diagnostic harness around the instrumented archive."""
    harness = dest / "harness"
    command = [
        "make", "-j16", "-C", str(ROOT / "testcase/xiangshan/difftest"), "emu-grhsim",
        "CC=" + str(LLVM / "clang"), "CXX=" + str(LLVM / "clang++"),
        "BUILD_DIR=" + str(harness),
        "GEN_CSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "GEN_VSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "NUM_CORES=1", "WITH_CHISELDB=0", "WITH_CONSTANTIN=0", "EMU_THREADS=0",
        "EMU_RANDOMIZE=0", "GRHSIM=1",
        "GRHSIM_MODEL_DIR=" + str(model_dir), "GRHSIM_MODEL_LIB=" + str(model_lib),
        "GRHSIM_MODEL_BUILD_JOBS=24",
        "GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native " + " ".join(compiler_flags),
        "EMU_OPTIMIZE=-O3", "WOLVRIX_GRHSIM_WAVEFORM=0",
    ]
    with (dest / "harness.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return harness / "grhsim-compile/emu"


def build_variant(name: str, source: Path, output: Path) -> dict:
    """Build one wrapper-instrumented variant without mutating its source tree."""
    source = source.resolve(strict=True)
    source_package = source / "package"
    source_archive = source_package / "libgrhsim_SimTop.a"
    if not source_archive.is_file():
        raise ValueError(f"missing GrhSIM archive: {source_archive}")
    build_record = source / "build.json"
    compiler_flags = (json.loads(build_record.read_text()).get("compiler_flags", [])
                      if build_record.exists() else [])
    dest = output / name
    dest.mkdir(exist_ok=False)
    package = dest / "package"
    package.mkdir()
    for item in source_package.iterdir():
        if item.name != source_archive.name:
            (package / item.name).symlink_to(item)
    dest_archive = package / source_archive.name
    shutil.copy2(source_archive, dest_archive)
    before = {key: common.identity(source / key)
              for key in ("harness/grhsim-compile/emu", "package/libgrhsim_SimTop.a")}

    def compile_one(suffix):
        name = f"wolvi_repcut_grhsim_sim_{suffix}"
        cpp, obj = dest / f"{name}.cpp", dest / f"{name}.o"
        cpp.write_text(instrument((source_package / f"{name}.cpp").read_text(), suffix))
        command = [str(LLVM / "clang++"), "-std=c++20", "-O3", "-march=native", *compiler_flags, "-pthread",
                   "-I", str(package), "-I", str(Path(__file__).resolve().parent),
                   "-c", str(cpp), "-o", str(obj)]
        with (dest / f"{name}.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        align_object(obj)
        return obj

    with ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(compile_one, SUFFIXES))
    subprocess.run([str(LLVM / "llvm-ar"), "rcs", str(dest_archive), *map(str, objects)],
                   cwd=ROOT, check=True)
    binary = link_harness(dest, package, dest_archive, compiler_flags)
    (dest / "emu").symlink_to(binary)
    after = {key: common.identity(source / key) for key in before}
    if before != after:
        raise ValueError(f"source changed while instrumenting {source}")
    return {"source": str(source), "package": str(package),
            "archive": common.identity(dest_archive), "binary": common.identity(binary),
            "diagnostic_only": True,
            "compiler_flags": compiler_flags,
            "changed_members": [obj.name for obj in objects],
            "source_before": before}


def build(output, sources):
    output.mkdir(parents=True, exist_ok=True)
    records = {variant: build_variant(variant, sources[variant], output)
               for variant in common.VARIANTS}
    (output / "build.json").write_text(json.dumps(records, indent=2) + "\n")
    return records


def run(output, sources, run_dir="runs", retry_preload=None, codepage_mode="thp",
        pairs=2, cycles=100000, numa_policy="bind"):
    if numa_policy not in ("bind", "preferred"):
        raise ValueError(f"unsupported NUMA policy: {numa_policy}")
    original = common.command_for

    def command_for(spec, binaries, runs):
        command = original(spec, binaries, runs)
        if numa_policy == "preferred":
            command[command.index("--membind=1")] = "--preferred=1"
        pos = command.index(str(binaries[spec["variant"]]))
        preload = f"{retry_preload}:{thp.PRELOAD}" if retry_preload else str(thp.PRELOAD)
        command[pos:pos] = ["/usr/bin/env", f"LD_PRELOAD={preload}",
                           f"REPCUT_CODEPAGE_MODE={codepage_mode}",
                           f"REPCUT_CYCLE_TRACE_FILE={runs / (spec['name'] + '.trace.bin')}"]
        return command

    common.command_for = command_for
    sys.argv = [sys.argv[0], "--pairs", str(pairs), "--cycles", str(cycles),
                "--output", str(output / run_dir)]
    for variant in common.VARIANTS:
        sys.argv += [f"--{variant}-binary", str(output / variant / "emu"),
                     f"--{variant}-package", str(output / variant / "package")]
    common.main()
    reports = []
    for log in sorted((output / run_dir).glob("*.log")):
        matches = re.findall(r"\[codepage\] PASS mode=(\w+) bytes=(\d+) anon_huge=(\d+) "
                             r"regions=(\d+) setup_s=([0-9.]+) pid=(\d+)", log.read_text())
        assert len(matches) == 1, log
        mode, size, huge, regions, setup, pid = matches[0]
        assert mode == codepage_mode and int(size) > 0
        assert int(huge) == (int(size) if mode == "thp" else 0), log
        reports.append(dict(log=log.name, mode=mode, bytes=int(size), huge_bytes=int(huge),
                            setup_s=float(setup), pid=int(pid)))
    assert len(reports) == 2 + 2 * pairs
    (output / run_dir / "codepage_verification.json").write_text(json.dumps({
        "status": "pass", "mode": codepage_mode, "preload": common.identity(thp.PRELOAD),
        "runs": reports,
    }, indent=2) + "\n")
    annotate(output / run_dir, codepage_mode, numa_policy)
    if retry_preload:
        (output / run_dir / "startup_retry.json").write_text(json.dumps({
            "preload": common.identity(retry_preload),
            "scope": "process-local MADV_COLLAPSE retries before simulation; no runtime sample filtering",
        }, indent=2) + "\n")


def annotate(directory, codepage_mode, numa_policy="bind"):
    for name in ("manifest.json", "summary.json"):
        path = directory / name
        record = json.loads(path.read_text())
        record.update(diagnostic_only=True, codepage_mode=codepage_mode,
                      numa_policy=numa_policy,
                      timing_use="full-cycle diagnostic trace, not an ordinary walltime benefit measurement",
                      trace_driver=common.identity(Path(__file__)),
                      trace_header=common.identity(Path(__file__).with_suffix(".hpp")))
        path.write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "run"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline-source", type=Path, default=DEFAULT_SOURCES["baseline"])
    parser.add_argument("--candidate-source", type=Path, default=DEFAULT_SOURCES["candidate"])
    parser.add_argument("--run-dir", default="runs")
    parser.add_argument("--retry-preload", type=Path)
    parser.add_argument("--codepage-mode", choices=("thp", "small"), default="thp")
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--numa-policy", choices=("bind", "preferred"), default="bind")
    parser.add_argument("--cycles", type=int, choices=(10000, 30000, 100000), default=100000)
    args = parser.parse_args()
    sources = {"baseline": args.baseline_source, "candidate": args.candidate_source}
    if args.action == "build":
        build(args.output.resolve(), sources)
    else:
        run(args.output.resolve(), sources, args.run_dir, args.retry_preload,
            args.codepage_mode, args.pairs, args.cycles, args.numa_policy)
