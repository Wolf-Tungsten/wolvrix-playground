#!/usr/bin/env python3
"""Build a diagnostic GrhSIM archive that counts input-dirty events.

This is a mechanism probe for the generic input-dirty-tracking candidate.  It
replaces only the generated update translation unit in a copied archive and
leaves the ordinary candidate package untouched.  The counter is written at
process exit when ``GRHSIM_DIRTY_COUNTER_FILE`` is set.  The resulting binary
must not be used as a walltime benchmark: the counter is intentionally an
instrumentation build.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LLVM = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin")
DEFAULT_SOURCE = ROOT / (
    "build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/"
    "backend_hgr_from_scratch_20261020/structural_replay_stage3_shape_p29_top_current_20261022/"
    "phase_activity_20261023/input_dirty_tracking_same_assignment_20261025_emitonly"
)


def align_object(path: Path) -> None:
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError(f"not an ELF64 object: {path}")
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_size, section_count, string_index = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data,
                                   section_offset + index * section_size)
                for index in range(section_count)]
    strings = sections[string_index]
    names = data[strings[4]:strings[4] + strings[5]]
    flags = []
    for section in sections:
        if section[2] & 4 and section[5]:
            name = names[section[0]:names.index(b"\0", section[0])].decode()
            flags.append(f"--set-section-alignment={name}={max(64, section[8])}")
    subprocess.run([str(LLVM / "llvm-objcopy"), *flags, str(path)], check=True)


def instrument_update(text: str) -> tuple[str, int]:
    part_ids = [int(part) for part in re.findall(r'run_update_final_part_(\d+)_', text)]
    offsets = [int(offset) for offset in re.findall(r'input_changes_\[(\d+)u\]', text)]
    if not part_ids or not offsets or any(offset % 64 for offset in offsets):
        raise ValueError('missing update functions or invalid dirty-marker offsets')
    prefix = r'''#include <array>
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstdint>

namespace repcut_dirty_counter {
alignas(64) std::array<std::array<std::atomic<std::uint64_t>, MARKER_COUNT>, PART_COUNT> events{};

void record(std::size_t part, std::size_t marker) {
  events[part][marker].fetch_add(1, std::memory_order_relaxed);
}

struct Dump {
  ~Dump() {
    const char* path = std::getenv("GRHSIM_DIRTY_COUNTER_FILE");
    if (path == nullptr || *path == '\0') return;
    FILE* file = std::fopen(path, "w");
    if (file == nullptr) return;
    std::fprintf(file, "{\"schema_version\":1,\"record_type\":\"dirty_events\",\"parts\":[");
    for (std::size_t part = 0; part < events.size(); ++part) {
      if (part != 0) std::fputc(',', file);
      std::fprintf(file, "{\"part\":%zu,\"markers\":[", part);
      bool first_marker = true;
      for (std::size_t marker = 0; marker < events[part].size(); ++marker) {
        const auto count = events[part][marker].load(std::memory_order_relaxed);
        if (count == 0) continue;
        if (!first_marker) std::fputc(',', file);
        first_marker = false;
        std::fprintf(file, "{\"marker\":%zu,\"events\":%llu}", marker,
                     static_cast<unsigned long long>(count));
      }
      std::fputs("]}", file);
    }
    std::fprintf(file, "]}\n");
    std::fclose(file);
  }
};

Dump dump;
}  // namespace repcut_dirty_counter

'''
    prefix = prefix.replace('MARKER_COUNT', str(max(offsets) // 64 + 1))
    prefix = prefix.replace('PART_COUNT', str(max(part_ids) + 1))
    pattern = re.compile(
        r"if \(copy_tracked_wide_words_\((?P<args>[^\n]+?)\)\) "
        r"unit_part_(?P<part>\d+)_->input_changes_\[(?P<offset>[^\]]+)\] = 1;")

    def replace(match: re.Match[str]) -> str:
        part = int(match.group("part"))
        marker = int(match.group("offset").rstrip("u")) // 64
        return (f"if (copy_tracked_wide_words_({match.group('args')})) {{ "
                f"repcut_dirty_counter::record({part}, {marker}); "
                f"unit_part_{part}_->input_changes_[{match.group('offset')}] = 1; }}")

    instrumented, count = pattern.subn(replace, text)
    if count == 0:
        raise ValueError("no tracked input marker assignments found")
    return prefix + instrumented, count


def link_harness(dest: Path, package: Path, archive: Path) -> Path:
    harness = dest / "harness"
    command = [
        "make", "-j16", "-C", str(ROOT / "testcase/xiangshan/difftest"), "emu-grhsim",
        "CC=" + str(LLVM / "clang"), "CXX=" + str(LLVM / "clang++"),
        "BUILD_DIR=" + str(harness),
        "GEN_CSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "GEN_VSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "NUM_CORES=1", "WITH_CHISELDB=0", "WITH_CONSTANTIN=0", "EMU_THREADS=0",
        "EMU_RANDOMIZE=0", "GRHSIM=1",
        "GRHSIM_MODEL_DIR=" + str(package), "GRHSIM_MODEL_LIB=" + str(archive),
        "GRHSIM_MODEL_BUILD_JOBS=24", "GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native",
        "EMU_OPTIMIZE=-O3", "WOLVRIX_GRHSIM_WAVEFORM=0",
    ]
    with (dest / "harness.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return harness / "grhsim-compile/emu"


def build(source: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    source_package = source / "package"
    source_archive = source_package / "libgrhsim_SimTop.a"
    update_source = source_package / "wolvi_repcut_grhsim_sim_update_0.cpp"
    if not source_archive.is_file() or not update_source.is_file():
        raise ValueError(f"missing source package artifacts under {source_package}")
    output.mkdir(parents=True, exist_ok=False)
    package = output / "package"
    package.mkdir()
    for item in source_package.iterdir():
        if item.name != source_archive.name:
            (package / item.name).symlink_to(item)
    archive = package / source_archive.name
    shutil.copy2(source_archive, archive)
    source_text, marker_count = instrument_update(update_source.read_text())
    instrumented_source = output / update_source.name
    instrumented_source.write_text(source_text)
    object_path = output / "wolvi_repcut_grhsim_sim_update_0.o"
    command = [str(LLVM / "clang++"), "-std=c++20", "-O3", "-march=native", "-pthread",
               "-I", str(package), "-c", str(instrumented_source), "-o", str(object_path)]
    with (output / "compile.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    align_object(object_path)
    subprocess.run([str(LLVM / "llvm-ar"), "r", str(archive), str(object_path)],
                   cwd=ROOT, check=True)
    binary = link_harness(output, package, archive)
    result = {"source": str(source), "package": str(package), "archive": str(archive),
              "binary": str(binary), "diagnostic_only": True,
              "marker_assignments": marker_count}
    (output / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
