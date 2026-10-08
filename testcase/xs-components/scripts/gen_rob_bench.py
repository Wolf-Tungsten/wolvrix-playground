#!/usr/bin/env python3
"""Generate the gsim-vs-GrhSIM runtime benchmark testbench for the extracted
XiangShan Rob module.

Parses the generated model headers (gsim ``Rob.h`` and GrhSIM
``grhsim_Rob.hpp``) plus the Rob.sv module port list, pairs top-level ports by
normalized name, and emits ``rob_bench.cpp`` following the
``tb/xs_component_bench.hpp`` conventions (splitmix64 vectors, per-cycle
drive/sample, verify-then-benchmark with [BENCH] lines).

Port-shape notes discovered on this design (see README "运行时基准"):

* gsim keeps some top-level vectors as C arrays (``name[8]`` or even
  ``name[8][32]``); their accessors were rewritten to pointer form by
  ``fix_gsim_array_ports.py``. The SV/GrhSIM side flattens the same vectors
  into scalar ports with the element index folded into the name
  (``io_enq_req_3_bits_isRVC``). Element-wise pairing searches for the name
  component position where each array dimension's index was inserted.
* firtool prunes unused input bundle fields and dead output elements, so many
  gsim ports have no GrhSIM counterpart (driven constant-0 on the gsim side
  by simply never calling their set_ after construction; excluded from
  output comparison and reported in the pairing TSV).
* A few GrhSIM outputs correspond to a single constant-folded gsim port
  (``io_commits_info_N_ftqOffset`` vs scalar ``get_io__DOT__commits__DOT__
  info__DOT__ftqOffset()`` returning 0) or to a gsim member without accessor
  (``io_error_0`` vs ``io_error``). These pair through reverse index
  stripping and broadcast comparison.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

CTYPE_RE = r"(?:unsigned _BitInt\(\d+\)|uint8_t|uint16_t|uint32_t|uint64_t)"

# Static configuration inputs driven with constant 0 instead of random data.
STATIC_ZERO_PORTS = {"io_hartId"}

# Distinct random input combinations kept resident; the bench loops over the
# pool so --vectors may exceed it.
POOL_SIZE = 2048


def log(message: str) -> None:
    sys.stderr.write(f"[gen-rob-bench] {message}\n")


def norm_name(name: str) -> str:
    return name.replace("__DOT__", "_")


@dataclass
class GsimPort:
    name: str  # member/accessor name in Rob.h
    direction: str  # input | output
    ctype: str  # accessor element type
    width: int  # FIRRTL width (from the // width comment; 0 if no member)
    dims: tuple[int, ...]  # array dims, () for scalar
    has_member: bool
    pointer_accessor: bool  # array ports patched to pointer form

    @property
    def element_count(self) -> int:
        total = 1
        for d in self.dims:
            total *= d
        return total

    def element_indices(self) -> list[tuple[int, ...]]:
        result = []
        for flat in range(self.element_count):
            idx = []
            rest = flat
            for d in reversed(self.dims):
                idx.append(rest % d)
                rest //= d
            result.append(tuple(reversed(idx)))
        return result


@dataclass
class Leaf:
    """One comparable/drivable scalar-or-wide leaf port."""

    name: str  # logical name (GrhSIM/SV style)
    direction: str
    width: int
    gsim: GsimPort | None = None
    gsim_index: tuple[int, ...] | None = None  # element index for array ports
    gsim_broadcast: bool = False  # gsim side is a shared scalar (const-folded vector)
    grhsim_name: str = ""
    grhsim_type: str = ""  # bool/std::uintN_t/std::array<...>

    @property
    def words(self) -> int:
        return max(1, (self.width + 63) // 64)

    @property
    def paired(self) -> bool:
        return self.gsim is not None and bool(self.grhsim_name)

    @property
    def wide(self) -> bool:
        return self.width > 64


def parse_gsim_header(text: str) -> tuple[dict[str, GsimPort], dict[str, tuple[str, tuple[int, ...], int]]]:
    members: dict[str, tuple[str, tuple[int, ...], int]] = {}
    member_re = re.compile(rf"^({CTYPE_RE}) (\w+)((?:\[\d+\])*) *; // width = (\d+)", re.MULTILINE)
    for m in member_re.finditer(text):
        dims = tuple(int(d) for d in re.findall(r"\[(\d+)\]", m.group(3)))
        members[m.group(2)] = (m.group(1), dims, int(m.group(4)))

    ports: dict[str, GsimPort] = {}
    for m in re.finditer(rf"^void set_(\w+)\(({CTYPE_RE}) val\);$", text, re.MULTILINE):
        name, ctype = m.group(1), m.group(2)
        if name in ("clock", "reset"):
            continue
        mem = members.get(name)
        ports[name] = GsimPort(
            name=name, direction="input", ctype=ctype,
            width=mem[2] if mem else 0, dims=mem[1] if mem else (),
            has_member=mem is not None, pointer_accessor=False,
        )
    for m in re.finditer(rf"^void set_(\w+)\(const ({CTYPE_RE}) \*val\);$", text, re.MULTILINE):
        name, ctype = m.group(1), m.group(2)
        mem = members.get(name)
        ports[name] = GsimPort(
            name=name, direction="input", ctype=ctype,
            width=mem[2] if mem else 0, dims=mem[1] if mem else (),
            has_member=mem is not None, pointer_accessor=True,
        )
    for m in re.finditer(rf"^({CTYPE_RE}) get_(\w+)\(\);$", text, re.MULTILINE):
        ctype, name = m.group(1), m.group(2)
        mem = members.get(name)
        ports[name] = GsimPort(
            name=name, direction="output", ctype=ctype,
            width=mem[2] if mem else 0, dims=mem[1] if mem else (),
            has_member=mem is not None, pointer_accessor=False,
        )
    for m in re.finditer(rf"^void get_(\w+)\(({CTYPE_RE}) \*out\);$", text, re.MULTILINE):
        name, ctype = m.group(1), m.group(2)
        mem = members.get(name)
        ports[name] = GsimPort(
            name=name, direction="output", ctype=ctype,
            width=mem[2] if mem else 0, dims=mem[1] if mem else (),
            has_member=mem is not None, pointer_accessor=True,
        )
    return ports, members


def parse_grhsim_header(text: str, top: str) -> dict[str, tuple[str, int]]:
    """name -> (ctype, nominal width)."""
    class_match = re.search(rf"class GrhSIM_{top}\b", text)
    if not class_match:
        raise RuntimeError(f"class GrhSIM_{top} not found in grhsim header")
    start = text.find("public:", class_match.end())
    end = text.find("private:", class_match.end())
    if start < 0 or end < 0:
        raise RuntimeError("public/private section not found in grhsim header")
    body = text[start:end]
    result: dict[str, tuple[str, int]] = {}
    scalar = re.compile(
        r"^\s*(bool|std::uint8_t|std::uint16_t|std::uint32_t|std::uint64_t)\s+(\w+)\s*(?:\{[^;]*\}|=[^;]*);",
        re.MULTILINE,
    )
    for m in scalar.finditer(body):
        ctype, name = m.group(1), m.group(2)
        width = {"bool": 1, "std::uint8_t": 8, "std::uint16_t": 16,
                 "std::uint32_t": 32, "std::uint64_t": 64}[ctype]
        result[name] = (ctype, width)
    wide = re.compile(
        r"^\s*std::array<\s*std::uint64_t\s*,\s*(\d+)\s*>\s+(\w+)\s*(?:\{[^;]*\}|=[^;]*);",
        re.MULTILINE,
    )
    for m in wide.finditer(body):
        result[m.group(2)] = (f"std::array<std::uint64_t, {m.group(1)}>", int(m.group(1)) * 64)
    result.pop("clock", None)
    result.pop("reset", None)
    return result


def parse_sv_ports(sv_path: Path, top: str) -> dict[str, tuple[str, int]]:
    ports: dict[str, tuple[str, int]] = {}
    with sv_path.open("r", encoding="utf-8", errors="replace") as stream:
        in_header = False
        for line in stream:
            if not in_header:
                if re.match(rf"module {top}\s*\(", line):
                    in_header = True
                continue
            if line.strip().startswith(");"):
                break
            m = re.match(
                r"\s*(input|output)\s+(?:wire\s+|reg\s+)?(?:\[\s*(\d+)\s*:\s*\d+\]\s*)?(\w+)",
                line,
            )
            if m:
                width = int(m.group(2)) + 1 if m.group(2) else 1
                ports[m.group(3)] = (m.group(1), width)
    if not ports:
        raise RuntimeError(f"no SV ports parsed from {sv_path} module {top}")
    return ports


def element_name(comps: list[str], positions: tuple[int, ...], indices: tuple[int, ...]) -> str:
    out: list[str] = []
    for k, comp in enumerate(comps):
        out.append(comp)
        for d, pos in enumerate(positions):
            if pos == k:
                out.append(str(indices[d]))
    return "_".join(out)


def find_positions(comps: list[str], dims: tuple[int, ...], indices: list[tuple[int, ...]],
                   candidates: set[str]) -> tuple[tuple[int, ...] | None, int]:
    """Search the name-component position of each array dim that maximizes the
    number of element names present in ``candidates``."""
    best: tuple[tuple[int, ...] | None, int] = (None, 0)
    for positions in product(range(len(comps)), repeat=len(dims)):
        if any(positions[i] > positions[i + 1] for i in range(len(positions) - 1)):
            continue
        count = sum(1 for idx in indices if element_name(comps, positions, idx) in candidates)
        if count > best[1]:
            best = (positions, count)
            if count == len(indices):
                break
    return best


def build_leaves(
    gsim_ports: dict[str, GsimPort],
    gsim_members: dict[str, tuple[str, tuple[int, ...], int]],
    grhsim_members: dict[str, tuple[str, int]],
    sv_ports: dict[str, tuple[str, int]],
) -> list[Leaf]:
    leaves: dict[str, Leaf] = {}
    grhsim_names = set(grhsim_members)

    def leaf_for(name: str, direction: str, width: int) -> Leaf:
        leaf = leaves.get(name)
        if leaf is None:
            leaf = Leaf(name=name, direction=direction, width=width)
            leaves[name] = leaf
        return leaf

    for port in sorted(gsim_ports.values(), key=lambda p: p.name):
        base = norm_name(port.name)
        if not port.dims:
            leaf = leaf_for(base, port.direction, port.width)
            leaf.gsim = port
            continue
        indices = port.element_indices()
        positions, matched = find_positions(base.split("_"), port.dims, indices, grhsim_names)
        for idx in indices:
            if positions is not None and matched:
                name = element_name(base.split("_"), positions, idx)
            else:
                name = base + "__e" + "_".join(map(str, idx))
            leaf = leaf_for(name, port.direction, port.width)
            leaf.gsim = port
            leaf.gsim_index = idx

    # Attach GrhSIM members; reverse index stripping handles GrhSIM ports
    # whose gsim counterpart collapsed to a scalar (const-folded vectors).
    gsim_scalar = {n for n, p in leaves.items() if p.gsim is not None and p.gsim_index is None}
    gsim_member_only = set(gsim_members) - {p.name for p in gsim_ports.values()}
    for name in sorted(grhsim_names):
        if name in leaves:
            leaf = leaves[name]
        else:
            comps = name.split("_")
            target = None
            for pos in range(len(comps) - 1, -1, -1):
                if not comps[pos].isdigit():
                    continue
                candidate = "_".join(comps[:pos] + comps[pos + 1:])
                if candidate in gsim_scalar or candidate in gsim_member_only:
                    target = candidate
                    break
            leaf = leaf_for(name, "", 0)
            if target is not None:
                port = gsim_ports.get(target)
                if port is None and target in leaves and leaves[target].gsim is not None:
                    # candidate is a normalized leaf name (e.g. const-folded
                    # scalar io_commits_info_ftqOffset): reuse its port
                    port = leaves[target].gsim
                if port is not None:
                    leaf.gsim = port
                    leaf.gsim_broadcast = True
                else:
                    # member without accessor (e.g. io_error): read directly
                    ctype, dims, width = gsim_members[target]
                    leaf.gsim = GsimPort(
                        name=target, direction="", ctype=ctype, width=width, dims=dims,
                        has_member=True, pointer_accessor=False,
                    )
                    leaf.gsim_broadcast = True
        ctype, nominal = grhsim_members[name]
        leaf.grhsim_name = name
        leaf.grhsim_type = ctype
        if not leaf.width:
            leaf.width = nominal
        if name in sv_ports and not leaf.direction:
            leaf.direction = sv_ports[name][0]
        if leaf.gsim is not None and not leaf.direction:
            leaf.direction = leaf.gsim.direction

    result = list(leaves.values())
    for leaf in result:
        if not leaf.direction:
            leaf.direction = sv_ports.get(leaf.name, ("internal", 0))[0] or "internal"
        if leaf.gsim is not None and leaf.gsim.width and leaf.width != leaf.gsim.width:
            # gsim carries the FIRRTL true width
            leaf.width = leaf.gsim.width
    return sorted(result, key=lambda l: l.name)


# Outputs excluded from compare and checksum (see CPP_HEAD notes):
# - "*_bore": difftest WiringControl taps whose frame counters/timestamps
#   differ between the two generated models.
# - io_storeDebugInfo_{0,1}_pc: dynamic-index reads of the 352-entry
#   robEntries.debug_pc array via robidx.value (9 bits). Random stimulus
#   regularly drives the index >= 352, an out-of-bounds read whose result is
#   undefined by FIRRTL; gsim resolves it to 0, GrhSIM to an aliased entry.
#   Every in-bounds vector matched on every cycle (probe8 evidence).
# - io_diffCommits_info rows >= 353: see DIFF_COMMITS_WRAP_ROW note below.
OOB_DEBUG_OUTPUTS = frozenset({"io_storeDebugInfo_0_pc", "io_storeDebugInfo_1_pc"})

# io_diffCommits_info rows >= 353 come from the RAB difftest commit lookahead
# window: io.diffCommits shows 520 rows starting at diffPtr over the 352-entry
# circular RAB, so rows >= 353 require the pointer sum to wrap *twice*
# (ptr + N - 704). The real chip (and GrhSIM, bit-exact against the 100k-cycle
# trace) wraps correctly; the gsim model resolves the second wrap differently
# (mismatch frequency grows linearly with row index, exactly the
# ptr >= 704 - N region). These are difftest-observability taps, not functional
# ROB outputs, so they are excluded from compare and checksum like the bore
# ports.
DIFF_COMMITS_WRAP_ROW = 353
DIFF_COMMITS_ROW_RE = re.compile(r"^io_diffCommits_info_(\d+)_")


def is_diffcommits_excluded(name: str) -> bool:
    m = DIFF_COMMITS_ROW_RE.match(name)
    return m is not None and int(m.group(1)) >= DIFF_COMMITS_WRAP_ROW


def is_excluded_output(name: str) -> bool:
    if name.endswith("_bore") or name in OOB_DEBUG_OUTPUTS:
        return True
    return is_diffcommits_excluded(name)


CPP_HEAD = """// Generated by testcase/xs-components/scripts/gen_rob_bench.py. Do not edit.
//
// Per-cycle conventions (see testcase/xs-components/rob/README.md "运行时基准"):
// - gsim:   drive(rec); step(); sample. The generated model commits every
//   register from a NEXT value computed in the *previous* step() (rotated
//   schedule: static census of the emitted supernodes shows 7436/7478
//   register commits sort before their producer across supernodes, and the
//   remaining 42 commit first inside one supernode), so after consuming
//   rec[i] gsim exposes comb(S(i-1), rec[i]).
// - grhsim: drive(rec); clock=false eval; sample; clock=true eval. Sampling
//   before this cycle's posedge exposes the identical (state, input) pair
//   comb(S(i-1), rec[i]), which makes functional outputs bit-identical per
//   cycle with no input skew. Each vector still costs exactly 2 evals.
// - Ports ending in "_bore" (diffTest WiringControl observability taps) are
//   excluded from compare and checksum: their payload lanes were verified
//   equal, but the tap frames embed wrapper counters/timestamps whose
//   counting conventions differ between the two generated models.
// - io_storeDebugInfo_{0,1}_pc are excluded: they read the 352-entry
//   robEntries.debug_pc array through robidx.value (9 bits), and random
//   stimulus drives the index out of bounds, which FIRRTL leaves undefined
//   (gsim yields 0, GrhSIM an aliased entry). All in-bounds cycles matched.
// - io_diffCommits_info rows >= 353 are excluded (trace mode finding): the
//   RAB difftest lookahead window needs a second RabSize wrap there, which
//   the gsim model resolves differently from the real chip; GrhSIM matches
//   the chip bit-exactly. Observability-only, no functional impact.
//   The excluded counts are printed on the [VERIFY] line.
#include "Rob.h"
#include "grhsim_Rob.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <new>
#include <sstream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static std::uint64_t g_assert_count = 0;

extern "C" void xs_assert(long long line)
{
    (void)line;
    ++g_assert_count;
}

extern "C" void xs_assert_v2(const char *filename, std::int64_t line)
{
    (void)filename;
    (void)line;
    ++g_assert_count;
}

namespace rob_bench {

inline std::uint64_t splitmix64(std::uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

inline std::string hex64(std::uint64_t value)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return os.str();
}

inline std::uint64_t fold_word(std::uint64_t acc, std::uint64_t word)
{
    return (acc ^ word) * 0x9e3779b97f4a7c15ULL;
}

inline std::uint64_t mask_word(std::uint64_t value, unsigned width)
{
    return width >= 64U ? value : (value & ((UINT64_C(1) << width) - UINT64_C(1)));
}

template <unsigned Width>
inline unsigned _BitInt(Width) bitint_from_words(const std::uint64_t *words, unsigned true_width)
{
    unsigned _BitInt(Width) value = 0;
    for (unsigned i = 0; i < (Width + 63U) / 64U; ++i) {
        value |= static_cast<unsigned _BitInt(Width)>(words[i]) << (64U * i);
    }
    if (true_width < Width) {
        value &= (static_cast<unsigned _BitInt(Width)>(1) << true_width) - 1;
    }
    return value;
}

"""


def bitint_rounded(width: int) -> int:
    return ((width + 63) // 64) * 64


def subscript(index: tuple[int, ...]) -> str:
    return "".join(f"[{i}]" for i in index)


def compute_record_layout(leaves: list[Leaf]) -> dict:
    """Shared pool-record layout used by both the bench codegen and the
    trace packer (layout.json).  Input record order is pool inputs (sorted by
    leaf name) followed by grhsim-only inputs; output record order is paired
    outputs sorted by leaf name."""
    inputs = [l for l in leaves if l.direction == "input" and l.paired]
    pool_inputs = [l for l in inputs if l.name not in STATIC_ZERO_PORTS]
    static_inputs = [l for l in inputs if l.name in STATIC_ZERO_PORTS]
    grhsim_only_in = [l for l in leaves if l.direction == "input" and not l.gsim and l.grhsim_name]
    outputs = [l for l in leaves if l.direction == "output" and l.paired]

    in_offsets: dict[str, int] = {}
    offset = 0
    for leaf in pool_inputs + grhsim_only_in:
        in_offsets[leaf.name] = offset
        offset += leaf.words
    out_offsets: dict[str, int] = {}
    out_offset = 0
    for leaf in outputs:
        out_offsets[leaf.name] = out_offset
        out_offset += leaf.words
    return {
        "inputs": inputs,
        "pool_inputs": pool_inputs,
        "static_inputs": static_inputs,
        "grhsim_only_in": grhsim_only_in,
        "outputs": outputs,
        "in_offsets": in_offsets,
        "out_offsets": out_offsets,
        "in_words": offset,
        "out_words": out_offset,
    }


def emit_cpp(leaves: list[Leaf], top: str) -> str:
    layout = compute_record_layout(leaves)
    inputs = layout["inputs"]
    pool_inputs = layout["pool_inputs"]
    static_inputs = layout["static_inputs"]
    grhsim_only_in = layout["grhsim_only_in"]
    outputs = layout["outputs"]
    in_offsets = layout["in_offsets"]
    out_offsets = layout["out_offsets"]
    offset = layout["in_words"]
    out_offset = layout["out_words"]

    out: list[str] = []
    out.append(f"constexpr unsigned kInWords = {offset}u;")
    out.append(f"constexpr unsigned kOutWords = {out_offset}u;")
    out.append(f"constexpr unsigned kPoolSize = {POOL_SIZE}u;")
    bore_ports = [l for l in outputs if l.name.endswith("_bore")]
    out.append(f"constexpr unsigned kBoreExcludedPorts = {len(bore_ports)}u;")
    out.append(f"constexpr unsigned kBoreExcludedWords = {sum(l.words for l in bore_ports)}u;")
    oob_ports = [l for l in outputs if l.name in OOB_DEBUG_OUTPUTS]
    out.append(f"constexpr unsigned kOobExcludedPorts = {len(oob_ports)}u;")
    out.append(f"constexpr unsigned kOobExcludedWords = {sum(l.words for l in oob_ports)}u;")
    dc_ports = [l for l in outputs if is_diffcommits_excluded(l.name)]
    out.append(f"constexpr unsigned kDiffCommitsExcludedPorts = {len(dc_ports)}u;")
    out.append(f"constexpr unsigned kDiffCommitsExcludedWords = {sum(l.words for l in dc_ports)}u;")
    out.append("")

    # ---------------- drive gsim ----------------
    out.append(f"void drive_gsim(S{top} &dut, const std::uint64_t *rec)")
    out.append("{")
    # group paired inputs by gsim accessor port
    groups: dict[str, list[Leaf]] = {}
    for leaf in pool_inputs:
        assert leaf.gsim is not None
        groups.setdefault(leaf.gsim.name, []).append(leaf)
    for port_name, members in groups.items():
        port = members[0].gsim
        assert port is not None
        if not port.dims:
            leaf = members[0]
            off = in_offsets[leaf.name]
            if port.width > 64:
                rounded = bitint_rounded(port.width)
                out.append(
                    f"    dut.set_{port.name}(bitint_from_words<{rounded}>(rec + {off}, {port.width}u));")
            else:
                out.append(
                    f"    dut.set_{port.name}(static_cast<{port.ctype}>(mask_word(rec[{off}], {port.width}u)));")
            continue
        total = port.element_count
        out.append("    {")
        out.append(f"        {port.ctype} tmp[{total}];")
        by_index = {l.gsim_index: l for l in members}
        indices = port.element_indices()
        for flat, idx in enumerate(indices):
            leaf = by_index.get(idx)
            if leaf is None:
                # unpaired element of a partially paired array: drive 0
                out.append(f"        tmp[{flat}] = 0;")
                continue
            off = in_offsets[leaf.name]
            if port.width > 64:
                rounded = bitint_rounded(port.width)
                out.append(
                    f"        tmp[{flat}] = bitint_from_words<{rounded}>(rec + {off}, {port.width}u);")
            else:
                out.append(
                    f"        tmp[{flat}] = static_cast<{port.ctype}>(mask_word(rec[{off}], {port.width}u));")
        out.append(f"        dut.set_{port.name}(tmp);")
        out.append("    }")
    for leaf in static_inputs:
        assert leaf.gsim is not None
        out.append(f"    dut.set_{leaf.gsim.name}(0); // static config input")
    out.append("}")
    out.append("")

    # ---------------- drive grhsim ----------------
    out.append(f"void drive_grhsim(GrhSIM_{top} &dut, const std::uint64_t *rec)")
    out.append("{")
    for leaf in inputs + grhsim_only_in:
        if not leaf.grhsim_name:
            continue
        if leaf.name in STATIC_ZERO_PORTS:
            if leaf.wide:
                out.append(f"    dut.{leaf.grhsim_name}.fill(0); // static config input")
            else:
                out.append(f"    dut.{leaf.grhsim_name} = 0; // static config input")
            continue
        off = in_offsets[leaf.name]
        if leaf.grhsim_type.startswith("std::array"):
            out.append(f"    for (unsigned i = 0; i < {leaf.words}u; ++i) {{")
            out.append(f"        dut.{leaf.grhsim_name}[i] = rec[{off} + i];")
            out.append("    }")
            if leaf.width % 64:
                out.append(
                    f"    dut.{leaf.grhsim_name}[{leaf.words - 1}] &= "
                    f"(UINT64_C(1) << {leaf.width % 64}u) - 1;")
        elif leaf.grhsim_type == "bool":
            out.append(f"    dut.{leaf.grhsim_name} = static_cast<bool>(rec[{off}] & 1);")
        else:
            out.append(
                f"    dut.{leaf.grhsim_name} = static_cast<{leaf.grhsim_type}>("
                f"mask_word(rec[{off}], {leaf.width}u));")
    out.append("}")
    out.append("")

    # ---------------- output readers ----------------
    def gsim_value_expr(leaf: Leaf) -> str:
        assert leaf.gsim is not None
        port = leaf.gsim
        if leaf.gsim_broadcast or leaf.gsim_index is None:
            if port.has_member:
                return f"dut.{port.name}"
            return f"dut.get_{port.name}()"
        return f"dut.{port.name}{subscript(leaf.gsim_index)}"

    for side, cls in (("gsim", f"S{top}"), ("grhsim", f"GrhSIM_{top}")):
        # verify reader: fill masked words
        out.append(f"void read_{side}_outputs({cls} &dut, std::uint64_t *out)")
        out.append("{")
        for leaf in outputs:
            off = out_offsets[leaf.name]
            if side == "gsim":
                expr = gsim_value_expr(leaf)
            else:
                expr = f"dut.{leaf.grhsim_name}"
            if leaf.wide:
                if side == "grhsim":
                    for w in range(leaf.words):
                        out.append(f"    out[{off + w}] = {expr}[{w}];")
                elif leaf.gsim is not None and leaf.gsim.ctype.startswith("unsigned _BitInt"):
                    out.append(f"    {{ const auto v = {expr};")
                    for w in range(leaf.words):
                        out.append(
                            f"      out[{off + w}] = static_cast<std::uint64_t>(v >> {64 * w}u);")
                    out.append("    }")
                else:
                    for w in range(leaf.words):
                        out.append(f"    out[{off + w}] = static_cast<std::uint64_t>({expr});")
                if leaf.width % 64:
                    out.append(
                        f"    out[{off + leaf.words - 1}] &= (UINT64_C(1) << {leaf.width % 64}u) - 1;")
            else:
                out.append(
                    f"    out[{off}] = mask_word(static_cast<std::uint64_t>({expr}), {leaf.width}u);")
        out.append("}")
        out.append("")
        # bench sampler: fold masked words into a checksum without storing
        out.append(f"std::uint64_t sample_{side}({cls} &dut, std::uint64_t acc)")
        out.append("{")
        for leaf in outputs:
            if is_excluded_output(leaf.name):
                # excluded from the checksum on both models (see header note)
                continue
            if side == "gsim":
                expr = gsim_value_expr(leaf)
            else:
                expr = f"dut.{leaf.grhsim_name}"
            if leaf.wide:
                is_bitint = (
                    side == "gsim" and leaf.gsim is not None
                    and leaf.gsim.ctype.startswith("unsigned _BitInt"))
                if is_bitint:
                    out.append(f"    {{ const auto v = {expr};")
                indent = "      " if is_bitint else "    "
                for w in range(leaf.words):
                    if side == "grhsim":
                        word_expr = f"{expr}[{w}]"
                    elif is_bitint:
                        word_expr = f"static_cast<std::uint64_t>(v >> {64 * w}u)"
                    else:
                        word_expr = f"static_cast<std::uint64_t>({expr})"
                    if w == leaf.words - 1 and leaf.width % 64:
                        word_expr = (
                            f"({word_expr} & ((UINT64_C(1) << {leaf.width % 64}u) - 1))")
                    out.append(f"{indent}acc = fold_word(acc, {word_expr});")
                if is_bitint:
                    out.append("    }")
            else:
                out.append(
                    f"    acc = fold_word(acc, mask_word(static_cast<std::uint64_t>({expr}), {leaf.width}u));")
        out.append("    return acc;")
        out.append("}")
        out.append("")

    out.append("struct OutWordInfo { unsigned offset; unsigned words; const char *name; bool excluded; };")
    out.append("constexpr OutWordInfo kOutWordInfo[] = {")
    for leaf in outputs:
        excluded = "true" if is_excluded_output(leaf.name) else "false"
        out.append(
            f'    {{{out_offsets[leaf.name]}u, {leaf.words}u, "{leaf.name}", {excluded}}},')
    out.append("};")
    out.append("")

    out.append("std::vector<std::uint64_t> make_input_pool(unsigned cycles)")
    out.append("{")
    out.append("    const unsigned count = std::min(cycles, kPoolSize);")
    out.append("    std::vector<std::uint64_t> pool(static_cast<std::size_t>(count) * kInWords);")
    out.append("    for (unsigned i = 0; i < count; ++i) {")
    out.append("        const std::uint64_t base = splitmix64(0x524f4242454e4348ULL + i);")
    out.append("        for (unsigned j = 0; j < kInWords; ++j) {")
    out.append("            pool[static_cast<std::size_t>(i) * kInWords + j] =")
    out.append("                splitmix64(base ^ (0x9e3779b97f4a7c15ULL * (j + 1)));")
    out.append("        }")
    out.append("    }")
    out.append("    return pool;")
    out.append("}")
    out.append("")

    out.append(f"void reset_gsim(S{top} &dut)")
    out.append("{")
    out.append("    // gsim registers advance on every step() unconditionally (the generated")
    out.append("    // model treats clock as constant; set_clock only feeds delta activation),")
    out.append("    // so the official emu.cpp convention applies: hold reset high for")
    out.append("    // 10 steps, never touch the clock.")
    out.append("    dut.set_reset(1);")
    out.append("    for (int i = 0; i < 10; ++i) {")
    out.append("        dut.step();")
    out.append("    }")
    out.append("    dut.set_reset(0);")
    out.append("}")
    out.append("")
    out.append(f"void reset_grhsim(GrhSIM_{top} &dut)")
    out.append("{")
    out.append("    dut.reset = true;")
    out.append("    for (int i = 0; i < 10; ++i) {")
    out.append("        dut.clock = true;")
    out.append("        dut.eval();")
    out.append("        dut.clock = false;")
    out.append("        dut.eval();")
    out.append("    }")
    out.append("    dut.reset = false;")
    out.append("}")
    out.append("")

    out.append(f"void eval_gsim(S{top} &dut, const std::uint64_t *rec, std::uint64_t *out)")
    out.append("{")
    out.append("    drive_gsim(dut, rec);")
    out.append("    dut.step();")
    out.append("    read_gsim_outputs(dut, out);")
    out.append("}")
    out.append("")
    out.append(f"void eval_grhsim(GrhSIM_{top} &dut, const std::uint64_t *rec, std::uint64_t *out)")
    out.append("{")
    out.append("    // Pre-edge sampling (see header note): gsim's rotated schedule makes")
    out.append("    // its post-step outputs comb(S(i-1), rec[i]); sampling grhsim after the")
    out.append("    // clock-low settle eval, before this cycle's posedge, exposes the same")
    out.append("    // (state, input) pair. The posedge eval then advances the state.")
    out.append("    drive_grhsim(dut, rec);")
    out.append("    dut.clock = false;")
    out.append("    dut.eval();")
    out.append("    read_grhsim_outputs(dut, out);")
    out.append("    dut.clock = true;")
    out.append("    dut.eval();")
    out.append("}")
    out.append("")
    return "\n".join(out)


CPP_MAIN = """
bool verify_models(const std::vector<std::uint64_t> &pool, unsigned count)
{
    auto gsim = std::make_unique<S_TOP>();
    auto grhsim = std::make_unique<GrhSIM_TOP>();
    grhsim->init();
    reset_gsim(*gsim);
    reset_grhsim(*grhsim);
    std::vector<std::uint64_t> gsim_out(kOutWords, 0);
    std::vector<std::uint64_t> grhsim_out(kOutWords, 0);
    const unsigned pool_cycles = static_cast<unsigned>(pool.size() / kInWords);
    unsigned fail_vectors = 0;
    std::map<std::string, unsigned long long> port_mismatches;
    for (unsigned i = 0; i < count; ++i) {
        const std::uint64_t *rec = pool.data() + static_cast<std::size_t>(i % pool_cycles) * kInWords;
        eval_gsim(*gsim, rec, gsim_out.data());
        eval_grhsim(*grhsim, rec, grhsim_out.data());
        bool vector_diff = false;
        for (const OutWordInfo &info : kOutWordInfo) {
            if (info.excluded) {
                continue;
            }
            for (unsigned w = 0; w < info.words; ++w) {
                if (gsim_out[info.offset + w] != grhsim_out[info.offset + w]) {
                    vector_diff = true;
                    break;
                }
            }
            if (vector_diff) {
                break;
            }
        }
        if (!vector_diff) {
            continue;
        }
        ++fail_vectors;
        const bool verbose = fail_vectors <= 3;
        if (verbose) {
            std::cerr << "[FAIL] top=_TOPNAME vector=" << i << "\\n";
        }
        unsigned reported = 0;
        for (const OutWordInfo &info : kOutWordInfo) {
            if (info.excluded) {
                continue;
            }
            bool port_diff = false;
            for (unsigned w = 0; w < info.words; ++w) {
                const std::uint64_t g = gsim_out[info.offset + w];
                const std::uint64_t r = grhsim_out[info.offset + w];
                if (g != r) {
                    port_diff = true;
                    if (verbose && reported < 32) {
                        std::cerr << "  " << info.name;
                        if (info.words > 1) {
                            std::cerr << "[word " << w << "]";
                        }
                        std::cerr << " gsim=" << hex64(g) << " grhsim=" << hex64(r) << "\\n";
                        ++reported;
                    }
                }
            }
            if (port_diff) {
                port_mismatches[info.name] += 1;
            }
        }
    }
    if (fail_vectors == 0) {
        std::cout << "[VERIFY] top=_TOPNAME vectors=" << count << " status=pass"
                  << " excluded_bore_ports=" << kBoreExcludedPorts
                  << " excluded_bore_words=" << kBoreExcludedWords
                  << " excluded_oob_ports=" << kOobExcludedPorts
                  << " excluded_oob_words=" << kOobExcludedWords
              << " excluded_diffcommits_ports=" << kDiffCommitsExcludedPorts
              << " excluded_diffcommits_words=" << kDiffCommitsExcludedWords << "\\n";
        return true;
    }
    std::vector<std::pair<std::string, unsigned long long>> ranked(
        port_mismatches.begin(), port_mismatches.end());
    std::sort(ranked.begin(), ranked.end(), [](const auto &a, const auto &b) {
        return a.second != b.second ? a.second > b.second : a.first < b.first;
    });
    std::cerr << "[VERIFY] top=_TOPNAME vectors=" << count << " status=fail fail_vectors=" << fail_vectors
              << " mismatch_ports=" << ranked.size()
              << " excluded_bore_ports=" << kBoreExcludedPorts
              << " excluded_bore_words=" << kBoreExcludedWords
              << " excluded_oob_ports=" << kOobExcludedPorts
              << " excluded_oob_words=" << kOobExcludedWords
              << " excluded_diffcommits_ports=" << kDiffCommitsExcludedPorts
              << " excluded_diffcommits_words=" << kDiffCommitsExcludedWords << "\\n";
    const std::size_t limit = std::min<std::size_t>(ranked.size(), 40);
    for (std::size_t i = 0; i < limit; ++i) {
        std::cerr << "  port " << ranked[i].first << " mismatched_vectors=" << ranked[i].second << "\\n";
    }
    if (ranked.size() > limit) {
        std::cerr << "  ... and " << (ranked.size() - limit) << " more ports\\n";
    }
    return false;
}

template <typename Model, typename EvalFn>
std::pair<double, std::uint64_t> run_benchmark_once(
    Model &model, const std::vector<std::uint64_t> &pool, unsigned vectors, EvalFn eval)
{
    std::uint64_t accum = 0x9e3779b97f4a7c15ULL;
    const unsigned pool_cycles = static_cast<unsigned>(pool.size() / kInWords);
    const auto begin = std::chrono::steady_clock::now();
    for (unsigned i = 0; i < vectors; ++i) {
        const std::uint64_t *rec = pool.data() + static_cast<std::size_t>(i % pool_cycles) * kInWords;
        accum = eval(model, rec, accum);
    }
    const auto end = std::chrono::steady_clock::now();
    return {std::chrono::duration<double, std::milli>(end - begin).count(), accum};
}

template <typename Model, typename EvalFn>
void run_benchmark(
    const char *label, Model &model, const std::vector<std::uint64_t> &pool, unsigned vectors, unsigned repeat,
    EvalFn eval)
{
    (void)run_benchmark_once(model, pool, vectors, eval);
    std::vector<double> samples;
    samples.reserve(repeat);
    std::uint64_t checksum = 0;
    for (unsigned i = 0; i < repeat; ++i) {
        const auto [ms, accum] = run_benchmark_once(model, pool, vectors, eval);
        checksum = accum;
        samples.push_back(ms);
        if (repeat > 1) {
            std::cout << "[BENCH_RUN] model=" << label << " top=_TOPNAME run=" << i << " vectors=" << vectors
                      << " ms=" << std::fixed << std::setprecision(3) << ms
                      << " vectors_per_s=" << std::setprecision(2)
                      << static_cast<double>(vectors) * 1000.0 / ms << " checksum=" << hex64(accum) << "\\n";
        }
    }
    auto sorted = samples;
    std::sort(sorted.begin(), sorted.end());
    const double min_ms = sorted.front();
    const double median_ms = sorted[sorted.size() / 2u];
    std::cout << "[BENCH] model=" << label << " top=_TOPNAME vectors=" << vectors << " repeat=" << repeat
              << " ms=" << std::fixed << std::setprecision(3) << min_ms
              << " min_ms=" << min_ms << " median_ms=" << std::setprecision(3) << median_ms
              << " vectors_per_s=" << std::setprecision(2) << static_cast<double>(vectors) * 1000.0 / min_ms
              << " checksum=" << hex64(checksum) << "\\n";
}

std::uint64_t eval_gsim_bench(S_TOP &dut, const std::uint64_t *rec, std::uint64_t acc)
{
    drive_gsim(dut, rec);
    dut.step();
    return sample_gsim(dut, acc);
}

std::uint64_t eval_grhsim_bench(GrhSIM_TOP &dut, const std::uint64_t *rec, std::uint64_t acc)
{
    // Same pre-edge sampling convention as eval_grhsim: 2 evals per vector,
    // identical cost structure to the gsim drive+step+sample path.
    drive_grhsim(dut, rec);
    dut.clock = false;
    dut.eval();
    acc = sample_grhsim(dut, acc);
    dut.clock = true;
    dut.eval();
    return acc;
}

// ---------------------------------------------------------------------------
// Whole-design trace replay: stimulus captured from the Verilator ref emu
// via the bound RobTap (see testcase/xs-components/rob/README.md). Binary
// layout: 24-byte header {char magic[8] = "RobTrc01"; u64 cycles;
// u32 in_words; u32 out_words}, then per cycle {u64 flags (bit0 = reset);
// u64 in[in_words]; u64 out[out_words]} in pool record order. The traced
// outputs ride along so replay can also be validated against the real chip
// trajectory, not only model against model.
struct TraceFile {
    int fd = -1;
    const std::uint8_t *map = nullptr;
    std::size_t map_size = 0;
    std::uint64_t cycles = 0;
    std::size_t stride = 0;
};

void close_trace(TraceFile &tf)
{
    if (tf.map != nullptr && tf.map != MAP_FAILED) {
        munmap(const_cast<std::uint8_t *>(tf.map), tf.map_size);
    }
    if (tf.fd >= 0) {
        close(tf.fd);
    }
    tf = TraceFile{};
}

bool open_trace(const char *path, TraceFile &tf)
{
    tf.fd = open(path, O_RDONLY);
    if (tf.fd < 0) {
        std::cerr << "[TRACE] cannot open " << path << ": " << std::strerror(errno) << "\\n";
        return false;
    }
    struct stat st;
    if (fstat(tf.fd, &st) != 0 || st.st_size < 24) {
        std::cerr << "[TRACE] cannot stat " << path << "\\n";
        close_trace(tf);
        return false;
    }
    tf.map_size = static_cast<std::size_t>(st.st_size);
    const void *map = mmap(nullptr, tf.map_size, PROT_READ, MAP_PRIVATE, tf.fd, 0);
    if (map == MAP_FAILED) {
        std::cerr << "[TRACE] cannot mmap " << path << ": " << std::strerror(errno) << "\\n";
        close_trace(tf);
        return false;
    }
    tf.map = static_cast<const std::uint8_t *>(map);
    if (std::memcmp(tf.map, "RobTrc01", 8) != 0) {
        std::cerr << "[TRACE] bad magic in " << path << "\\n";
        close_trace(tf);
        return false;
    }
    std::uint64_t cycles = 0;
    std::uint32_t in_words = 0;
    std::uint32_t out_words = 0;
    std::memcpy(&cycles, tf.map + 8, 8);
    std::memcpy(&in_words, tf.map + 16, 4);
    std::memcpy(&out_words, tf.map + 20, 4);
    if (in_words != kInWords || out_words != kOutWords) {
        std::cerr << "[TRACE] layout mismatch: trace in_words=" << in_words
                  << " out_words=" << out_words << " model kInWords=" << kInWords
                  << " kOutWords=" << kOutWords << "\\n";
        close_trace(tf);
        return false;
    }
    tf.stride = 8 + 8 * (static_cast<std::size_t>(in_words) + out_words);
    if (cycles == 0 || tf.map_size != 24 + cycles * tf.stride) {
        std::cerr << "[TRACE] size mismatch: cycles=" << cycles << " stride=" << tf.stride
                  << " expected_bytes=" << (24 + cycles * tf.stride) << " actual=" << tf.map_size << "\\n";
        close_trace(tf);
        return false;
    }
    tf.cycles = cycles;
    const std::uint64_t first_flags = *reinterpret_cast<const std::uint64_t *>(tf.map + 24);
    std::cerr << "[TRACE] " << path << " cycles=" << tf.cycles << " in_words=" << in_words
              << " out_words=" << out_words << " first_reset=" << (first_flags & 1u) << "\\n";
    if ((first_flags & 1u) == 0) {
        std::cerr << "[TRACE] WARNING: first record is not in reset; per-round state"
                     " rebuild relies on the trace starting inside reset\\n";
    }
    return true;
}

inline const std::uint64_t *trace_record(const TraceFile &tf, std::uint64_t index)
{
    return reinterpret_cast<const std::uint64_t *>(tf.map + 24 + index * tf.stride);
}

std::uint64_t eval_gsim_trace(S_TOP &dut, const std::uint64_t *rec, std::uint64_t acc)
{
    dut.set_reset(rec[0] & 1u);
    drive_gsim(dut, rec + 1);
    dut.step();
    return sample_gsim(dut, acc);
}

std::uint64_t eval_grhsim_trace(GrhSIM_TOP &dut, const std::uint64_t *rec, std::uint64_t acc)
{
    dut.reset = (rec[0] & 1u) != 0;
    drive_grhsim(dut, rec + 1);
    dut.clock = false;
    dut.eval();
    acc = sample_grhsim(dut, acc);
    dut.clock = true;
    dut.eval();
    return acc;
}

void eval_gsim_trace_out(S_TOP &dut, const std::uint64_t *rec, std::uint64_t *out)
{
    dut.set_reset(rec[0] & 1u);
    drive_gsim(dut, rec + 1);
    dut.step();
    read_gsim_outputs(dut, out);
}

void eval_grhsim_trace_out(GrhSIM_TOP &dut, const std::uint64_t *rec, std::uint64_t *out)
{
    dut.reset = (rec[0] & 1u) != 0;
    drive_grhsim(dut, rec + 1);
    dut.clock = false;
    dut.eval();
    read_grhsim_outputs(dut, out);
    dut.clock = true;
    dut.eval();
}

std::unique_ptr<S_TOP> make_gsim_zeroed()
{
    // gsim's init() leaves data members uninitialized unless RANDOMIZE_INIT
    // (the reference emulator relies on reset plus don't-care X semantics).
    // The Verilator reference is zero-initialized and replay diverges from
    // the traced trajectory when it starts from heap garbage, so zero the
    // storage and reconstruct the model on top.
    void *mem = ::operator new(sizeof(S_TOP));
    std::memset(mem, 0, sizeof(S_TOP));
    return std::unique_ptr<S_TOP>(new (mem) S_TOP());
}

bool verify_trace(const TraceFile &tf, unsigned count)
{
    auto gsim = make_gsim_zeroed();
    auto grhsim = std::make_unique<GrhSIM_TOP>();
    grhsim->init();
    std::vector<std::uint64_t> gsim_out(kOutWords, 0);
    std::vector<std::uint64_t> grhsim_out(kOutWords, 0);
    const char *pair_names[3] = {"gsim_vs_grhsim", "gsim_vs_trace", "grhsim_vs_trace"};
    std::map<std::string, unsigned long long> mismatches[3];
    unsigned long long fail_vectors[3] = {0, 0, 0};
    long long first_fail[3] = {-1, -1, -1};
    for (unsigned i = 0; i < count; ++i) {
        const std::uint64_t *rec = trace_record(tf, i);
        const std::uint64_t *traced = rec + 1 + kInWords;
        eval_gsim_trace_out(*gsim, rec, gsim_out.data());
        eval_grhsim_trace_out(*grhsim, rec, grhsim_out.data());
        bool diff[3] = {false, false, false};
        for (const OutWordInfo &info : kOutWordInfo) {
            if (info.excluded) {
                continue;
            }
            bool port_diff[3] = {false, false, false};
            for (unsigned w = 0; w < info.words; ++w) {
                const std::uint64_t g = gsim_out[info.offset + w];
                const std::uint64_t r = grhsim_out[info.offset + w];
                const std::uint64_t t = traced[info.offset + w];
                if (g != r) {
                    port_diff[0] = true;
                }
                if (g != t) {
                    port_diff[1] = true;
                }
                if (r != t) {
                    port_diff[2] = true;
                }
            }
            for (int p = 0; p < 3; ++p) {
                if (port_diff[p]) {
                    diff[p] = true;
                    mismatches[p][info.name] += 1;
                }
            }
        }
        for (int p = 0; p < 3; ++p) {
            if (diff[p]) {
                fail_vectors[p] += 1;
                if (first_fail[p] < 0) {
                    first_fail[p] = static_cast<long long>(i);
                }
            }
        }
    }
    const bool pass = fail_vectors[0] == 0 && fail_vectors[1] == 0 && fail_vectors[2] == 0;
    std::ostream &os = pass ? std::cout : std::cerr;
    os << "[VERIFY] top=_TOPNAME mode=trace vectors=" << count
       << (pass ? " status=pass" : " status=fail")
       << " gsim_vs_grhsim_fail=" << fail_vectors[0]
       << " gsim_vs_trace_fail=" << fail_vectors[1]
       << " grhsim_vs_trace_fail=" << fail_vectors[2]
       << " first_fail=" << first_fail[0] << "," << first_fail[1] << "," << first_fail[2]
       << " excluded_bore_ports=" << kBoreExcludedPorts
       << " excluded_bore_words=" << kBoreExcludedWords
       << " excluded_oob_ports=" << kOobExcludedPorts
       << " excluded_oob_words=" << kOobExcludedWords
       << " excluded_diffcommits_ports=" << kDiffCommitsExcludedPorts
       << " excluded_diffcommits_words=" << kDiffCommitsExcludedWords << "\\n";
    if (!pass) {
        for (int p = 0; p < 3; ++p) {
            if (fail_vectors[p] == 0) {
                continue;
            }
            std::vector<std::pair<std::string, unsigned long long>> ranked(
                mismatches[p].begin(), mismatches[p].end());
            std::sort(ranked.begin(), ranked.end(), [](const auto &a, const auto &b) {
                return a.second != b.second ? a.second > b.second : a.first < b.first;
            });
            std::cerr << "[VERIFY] pairing=" << pair_names[p]
                      << " mismatch_ports=" << ranked.size() << "\\n";
            const std::size_t limit = std::min<std::size_t>(ranked.size(), 500);
            for (std::size_t i = 0; i < limit; ++i) {
                std::cerr << "  port " << ranked[i].first
                          << " mismatched_vectors=" << ranked[i].second << "\\n";
            }
            if (ranked.size() > limit) {
                std::cerr << "  ... and " << (ranked.size() - limit) << " more ports\\n";
            }
        }
    }
    return pass;
}

template <typename MakeModel, typename EvalFn>
std::pair<double, std::uint64_t> run_trace_once(
    MakeModel make_model, const TraceFile &tf, unsigned vectors, EvalFn eval)
{
    // Fresh model per round: the replay is then identical to the verified
    // first pass (memories start zeroed, like the real chip at time 0), so
    // every round's trajectory — and therefore its checksum — matches the
    // trace exactly. Construction stays outside the timed region.
    auto model = make_model();
    std::uint64_t accum = 0x9e3779b97f4a7c15ULL;
    const auto begin = std::chrono::steady_clock::now();
    for (unsigned i = 0; i < vectors; ++i) {
        const std::uint64_t index = static_cast<std::uint64_t>(i) % tf.cycles;
        accum = eval(*model, trace_record(tf, index), accum);
    }
    const auto end = std::chrono::steady_clock::now();
    return {std::chrono::duration<double, std::milli>(end - begin).count(), accum};
}

template <typename MakeModel, typename EvalFn>
void run_benchmark_trace(
    const char *label, MakeModel make_model, const TraceFile &tf, unsigned vectors, unsigned repeat,
    EvalFn eval)
{
    (void)run_trace_once(make_model, tf, vectors, eval);
    std::vector<double> samples;
    samples.reserve(repeat);
    std::uint64_t checksum = 0;
    for (unsigned i = 0; i < repeat; ++i) {
        const auto [ms, accum] = run_trace_once(make_model, tf, vectors, eval);
        checksum = accum;
        samples.push_back(ms);
        if (repeat > 1) {
            std::cout << "[BENCH_RUN] model=" << label << " top=_TOPNAME stimulus=trace run=" << i
                      << " vectors=" << vectors
                      << " ms=" << std::fixed << std::setprecision(3) << ms
                      << " vectors_per_s=" << std::setprecision(2)
                      << static_cast<double>(vectors) * 1000.0 / ms
                      << " checksum=" << hex64(accum) << "\\n";
        }
    }
    auto sorted = samples;
    std::sort(sorted.begin(), sorted.end());
    const double min_ms = sorted.front();
    const double median_ms = sorted[sorted.size() / 2u];
    std::cout << "[BENCH] model=" << label << " top=_TOPNAME stimulus=trace vectors=" << vectors
              << " repeat=" << repeat
              << " ms=" << std::fixed << std::setprecision(3) << min_ms
              << " min_ms=" << min_ms << " median_ms=" << std::setprecision(3) << median_ms
              << " vectors_per_s=" << std::setprecision(2)
              << static_cast<double>(vectors) * 1000.0 / min_ms
              << " checksum=" << hex64(checksum) << "\\n";
}

} // namespace rob_bench

#ifndef ROB_BENCH_NO_MAIN
int main(int argc, char **argv)
{
    unsigned vectors = 100000;
    unsigned verify = 2048;
    unsigned repeat = 1;
    bool vectors_set = false;
    std::string model_selection = "both";
    std::string trace_path;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg == "--vectors" && i + 1 < argc) {
            vectors = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
            vectors_set = true;
        } else if (arg == "--verify" && i + 1 < argc) {
            verify = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--repeat" && i + 1 < argc) {
            repeat = std::max(1u, static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0)));
        } else if (arg == "--model" && i + 1 < argc) {
            model_selection = argv[++i];
            if (model_selection != "both" && model_selection != "gsim" && model_selection != "grhsim") {
                std::cerr << "invalid --model value: " << model_selection << "\\n";
                return 2;
            }
        } else if (arg == "--trace" && i + 1 < argc) {
            trace_path = argv[++i];
        } else {
            std::cerr << "usage: " << argv[0]
                      << " [--vectors N] [--verify N] [--repeat N] [--model both|gsim|grhsim] [--trace PATH]\\n";
            return 2;
        }
    }

    if (!trace_path.empty()) {
        // Trace mode: replay the whole-design stimulus captured from the
        // Verilator ref emu. No synthetic pre-reset: the trace's own leading
        // reset records rebuild the architectural state every round.
        rob_bench::TraceFile tf;
        if (!rob_bench::open_trace(trace_path.c_str(), tf)) {
            return 1;
        }
        if (!vectors_set) {
            vectors = static_cast<unsigned>(std::min<std::uint64_t>(tf.cycles, 0xffffffffULL));
        }
        const unsigned verify_cycles = static_cast<unsigned>(
            std::min<std::uint64_t>(verify, tf.cycles));
        if (verify_cycles > 0 && !rob_bench::verify_trace(tf, verify_cycles)) {
            rob_bench::close_trace(tf);
            return 1;
        }
        if (model_selection == "both" || model_selection == "gsim") {
            rob_bench::run_benchmark_trace(
                "gsim", [] { return rob_bench::make_gsim_zeroed(); }, tf, vectors, repeat,
                [](S_TOP &dut, const std::uint64_t *rec, std::uint64_t acc) {
                    return rob_bench::eval_gsim_trace(dut, rec, acc);
                });
        }
        if (model_selection == "both" || model_selection == "grhsim") {
            GrhSIM_TOP *perf_dump_model = nullptr;
            rob_bench::run_benchmark_trace(
                "grhsim",
                [&] {
                    auto model = std::make_unique<GrhSIM_TOP>();
                    model->init();
                    perf_dump_model = model.get();
                    return model;
                },
                tf, vectors, repeat,
                [](GrhSIM_TOP &dut, const std::uint64_t *rec, std::uint64_t acc) {
                    return rob_bench::eval_grhsim_trace(dut, rec, acc);
                });
#if WOLVRIX_GRHSIM_PERF
            if (perf_dump_model) {
                const auto pc = perf_dump_model->perf_counters();
                std::cout << "[PERF] model=grhsim stimulus=trace evalCount=" << pc.evalCount
                          << " round1Count=" << pc.round1Count << " round2Count=" << pc.round2Count
                          << " totalRoundCount=" << pc.totalRoundCount
                          << " computeBatchExecCount=" << pc.computeBatchExecCount
                          << " commitBatchExecCount=" << pc.commitBatchExecCount
                          << " touchedStateShadowCount=" << pc.touchedStateShadowCount
                          << " touchedWriteCount=" << pc.touchedWriteCount << "\\n";
            }
#endif
        }
        rob_bench::close_trace(tf);
        std::cout << "[ASSERT] xs_assert_v2_stub_count=" << g_assert_count << "\\n";
        return 0;
    }

    const auto pool = rob_bench::make_input_pool(std::max(vectors, verify));
    if (verify > 0 && !rob_bench::verify_models(pool, verify)) {
        return 1;
    }

    if (model_selection == "both" || model_selection == "gsim") {
        auto gsim = std::make_unique<S_TOP>();
        rob_bench::reset_gsim(*gsim);
        rob_bench::run_benchmark(
            "gsim", *gsim, pool, vectors, repeat,
            [](S_TOP &dut, const std::uint64_t *rec, std::uint64_t acc) {
                return rob_bench::eval_gsim_bench(dut, rec, acc);
            });
    }
    if (model_selection == "both" || model_selection == "grhsim") {
        auto grhsim = std::make_unique<GrhSIM_TOP>();
        grhsim->init();
        rob_bench::reset_grhsim(*grhsim);
        rob_bench::run_benchmark(
            "grhsim", *grhsim, pool, vectors, repeat,
            [](GrhSIM_TOP &dut, const std::uint64_t *rec, std::uint64_t acc) {
                return rob_bench::eval_grhsim_bench(dut, rec, acc);
            });
#if WOLVRIX_GRHSIM_PERF
        {
            const auto pc = grhsim->perf_counters();
            std::cout << "[PERF] model=grhsim stimulus=random evalCount=" << pc.evalCount
                      << " round1Count=" << pc.round1Count << " round2Count=" << pc.round2Count
                      << " totalRoundCount=" << pc.totalRoundCount
                      << " computeBatchExecCount=" << pc.computeBatchExecCount
                      << " commitBatchExecCount=" << pc.commitBatchExecCount
                      << " touchedStateShadowCount=" << pc.touchedStateShadowCount
                      << " touchedWriteCount=" << pc.touchedWriteCount << "\\n";
        }
#endif
    }
    std::cout << "[ASSERT] xs_assert_v2_stub_count=" << g_assert_count << "\\n";
    return 0;
}
#endif // ROB_BENCH_NO_MAIN
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", default="Rob")
    parser.add_argument("--gsim-header", required=True)
    parser.add_argument("--grhsim-header", required=True)
    parser.add_argument("--sv", required=True)
    parser.add_argument("--out")
    parser.add_argument("--pairing")
    parser.add_argument("--layout-out", help="dump the pool record layout as JSON (for the trace packer)")
    args = parser.parse_args()
    if not args.layout_out and (not args.out or not args.pairing):
        parser.error("--out and --pairing are required unless --layout-out is given")

    gsim_text = Path(args.gsim_header).read_text(encoding="utf-8", errors="replace")
    grhsim_text = Path(args.grhsim_header).read_text(encoding="utf-8", errors="replace")
    gsim_ports, gsim_members = parse_gsim_header(gsim_text)
    grhsim_members = parse_grhsim_header(grhsim_text, args.top)
    sv_ports = parse_sv_ports(Path(args.sv), args.top)
    leaves = build_leaves(gsim_ports, gsim_members, grhsim_members, sv_ports)

    def count(pred) -> int:
        return sum(1 for l in leaves if pred(l))

    stats = {
        "paired_in": count(lambda l: l.direction == "input" and l.paired),
        "paired_out": count(lambda l: l.direction == "output" and l.paired),
        "gsim_only_in": count(lambda l: l.direction == "input" and l.gsim and not l.grhsim_name),
        "gsim_only_out": count(lambda l: l.direction == "output" and l.gsim and not l.grhsim_name),
        "grhsim_only_in": count(lambda l: l.direction == "input" and not l.gsim and l.grhsim_name),
        "grhsim_only_out": count(lambda l: l.direction == "output" and not l.gsim and l.grhsim_name),
        "internal": count(lambda l: l.direction == "internal"),
        "wide_paired": count(lambda l: l.paired and l.width > 64),
        "broadcast_paired": count(lambda l: l.paired and l.gsim_broadcast),
    }
    log("ports: " + " ".join(f"{k}={v}" for k, v in stats.items()))

    if args.layout_out:
        layout = compute_record_layout(leaves)
        inputs_doc = []
        for kind, group in (("pool", layout["pool_inputs"]),
                            ("grhsim_only", layout["grhsim_only_in"])):
            for leaf in group:
                inputs_doc.append({
                    "name": leaf.name,
                    "width": leaf.width,
                    "words": leaf.words,
                    "offset": layout["in_offsets"][leaf.name],
                    "kind": kind,
                    "sv_port": leaf.name in sv_ports,
                })
        for leaf in layout["static_inputs"]:
            inputs_doc.append({
                "name": leaf.name,
                "width": leaf.width,
                "words": leaf.words,
                "offset": None,
                "kind": "static",
                "sv_port": leaf.name in sv_ports,
            })
        outputs_doc = [{
            "name": leaf.name,
            "width": leaf.width,
            "words": leaf.words,
            "offset": layout["out_offsets"][leaf.name],
            "excluded": is_excluded_output(leaf.name),
            "sv_port": leaf.name in sv_ports,
        } for leaf in layout["outputs"]]
        doc = {
            "top": args.top,
            "in_words": layout["in_words"],
            "out_words": layout["out_words"],
            "inputs": inputs_doc,
            "outputs": outputs_doc,
        }
        layout_path = Path(args.layout_out)
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        non_sv = [e["name"] for e in inputs_doc + outputs_doc if not e["sv_port"]]
        log(f"wrote {layout_path} in_words={layout['in_words']} out_words={layout['out_words']}"
            f" non_sv_record_ports={len(non_sv)}")
        if non_sv:
            log("WARNING: record ports not present as SV ports: " + ",".join(non_sv[:20]))
    if not args.out or not args.pairing:
        return 0

    pairing_path = Path(args.pairing)
    pairing_path.parent.mkdir(parents=True, exist_ok=True)
    with pairing_path.open("w", encoding="utf-8") as stream:
        stream.write("logical_name\tdirection\twidth\tgsim_accessor\tgsim_elem\tgrhsim_member\tstatus\n")
        for leaf in leaves:
            if leaf.paired:
                status = "paired_broadcast" if leaf.gsim_broadcast else "paired"
            elif leaf.gsim is not None:
                status = "gsim_only"
            elif leaf.grhsim_name:
                status = "grhsim_only"
            else:
                status = "internal"
            gsim_elem = "_".join(map(str, leaf.gsim_index)) if leaf.gsim_index else "-"
            stream.write(
                f"{leaf.name}\t{leaf.direction}\t{leaf.width}\t"
                f"{leaf.gsim.name if leaf.gsim else '-'}\t{gsim_elem}\t"
                f"{leaf.grhsim_name or '-'}\t{status}\n"
            )

    cpp = CPP_HEAD + emit_cpp(leaves, args.top) + CPP_MAIN
    cpp = cpp.replace("S_TOP", f"S{args.top}").replace("GrhSIM_TOP", f"GrhSIM_{args.top}")
    cpp = cpp.replace("_TOPNAME", args.top)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cpp, encoding="utf-8")
    log(f"wrote {out_path} ({len(cpp)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
