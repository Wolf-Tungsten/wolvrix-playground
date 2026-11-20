"""Activity-dispatch diagnostics on the released default XiangShan model.

Every variant is a private copy of the default (accumulate bank on) model
sources under build/armor-dispatch-v1:

  obs     counters per fixed-point round kind and per compare site; they never feed model logic
  lines   unchanged sources compiled with line tables, for sampled branch and fetch statistics
  pgogen  unchanged sources with compiler instrumentation.  This build computes one value wrongly (TNO0016), so
          its run leaves the reference path; kept as the record of that finding
  pgogen2 the same without SLP vectorization, which avoids the wrong value; trains the profile
  pgo     unchanged sources compiled with the profile of pgogen2 (pgolines: with line tables)
  e4cpgogen, e4cpgo  the same two steps on the eager4096 sources with the conditional-move flag
  cmov    unchanged sources; the compiler keeps conditional moves that read memory (cmovlines: with line tables)
  ubsan   unchanged sources with run-time checks for undefined operations
  muxhint the scalar multiplexer helper marks its condition as unpredictable (muxhintlines: with line tables)
  sdplain, sdpgo  a probe that records the bytes of the model object after chosen evals, built with the
          default flags and with compiler instrumentation, to find where two builds first differ

A variant emitted by armor_dispatch_emit.sh keeps its own sources (prepare only records them).  A name that
ends in cmov, lines or cmovlines after the name of an existing variant reuses that variant's sources with
the corresponding flags, for example eager64cmov; the suffix ubsan gives the checked build.  A name that
ends in hint (or is hint) reuses the sources with the dispatch tests re-hinted from the observer counts,
for example eager4096hint.

usage: armor_dispatch_diag.py prepare|build <variant>
       armor_dispatch_diag.py observe            run the observer with DiffTest on (node029)
       armor_dispatch_diag.py train [<variant>]  run an instrumented model (default pgogen2) once and merge its
                                                 profile (node029)
       armor_dispatch_diag.py counts <variant>   PMU event counts per guest cycle (node029, counts only)
       armor_dispatch_diag.py sample <variant> op|cycles|fetch [period]   IBS samples of the 100k window (node029)
       armor_dispatch_diag.py measure <variant>  eight paired rounds against the released default (node030)
       armor_dispatch_diag.py rounds <tag> <variant> ...   trace check, then eight rounds over the released
                                                 default and all named variants in rotating order (node030)
"""
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import sys
import time

from armor_followup_compare import ARCHIVE
from cv32e40p_compare import ROOT, run
from grhsim_single_baseline import clean_environment, identity, save
from xiangshan_cv32_ablation_measure import read
from xiangshan_packed_storage_compare import source_inventory

OUT = ROOT / 'build/armor-dispatch-v1'
DEFAULT = ROOT / 'build/armor-acc-default-v1/perf-regression/default-reemit'
RUNTIME = DEFAULT / 'verify/default/runs/runtime'
LLVM = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin')
# Keep conditional moves whose operand is a load instead of turning them into branches.
CMOV = ' -mllvm -x86-cmov-converter-force-mem-operand=false'
LINES = ' -gline-tables-only'
EXTRA_FLAGS = {'obs': '', 'lines': LINES, 'pgogen': f' -fprofile-generate={OUT}/pgogen/profile',
               'pgogen2': f' -fprofile-generate={OUT}/pgogen2/profile -fno-slp-vectorize',
               'pgo': f' -fprofile-use={OUT}/pgogen2/profile/default.profdata',
               'pgolines': f' -fprofile-use={OUT}/pgogen2/profile/default.profdata' + LINES,
               'cmov': CMOV, 'cmovlines': CMOV + LINES,
               'muxhint': '', 'muxhintlines': ' -gline-tables-only',
               # Report undefined operations at run time; line tables give the reports source lines.
               # The full check set at -O3 takes hours to compile; these checks at -O1 take minutes.
               'ubsan': ' -O1 -fsanitize=shift,signed-integer-overflow,bool,bounds,integer-divide-by-zero,unreachable,builtin'
                        ' -gline-tables-only',
               # Probes for reads of uninitialized locals: give them a fixed value.
               'autopattern': ' -ftrivial-auto-var-init=pattern',
               'pgogenzero': f' -fprofile-generate={OUT}/pgogenzero/profile -ftrivial-auto-var-init=zero',
               # Probe for type-based alias assumptions.
               'pgogennsa': f' -fprofile-generate={OUT}/pgogennsa/profile -fno-strict-aliasing',
               'sdplain': '', 'sdpgo': f' -fprofile-generate={OUT}/sdpgo/profile',
               'e4cpgogen': CMOV + f' -fprofile-generate={OUT}/e4cpgogen/profile -fno-slp-vectorize',
               'e4cpgo': CMOV + f' -fprofile-use={OUT}/e4cpgogen/profile/default.profdata'}
# Variants of EXTRA_FLAGS that are not built from the default model's sources.
BASES = {'e4cpgogen': 'eager4096', 'e4cpgo': 'eager4096'}
KINDS = 12  # eval phase (posedge, negedge, other) times round index (1, 2, 3, 4 or later)
EVENTS = [
    'cycles', 'instructions', 'ex_ret_ops', 'ex_ret_brn', 'ex_ret_brn_misp', 'ex_ret_brn_tkn', 'ex_ret_cond', 'ex_ret_brn_ind_misp',
    'ic_tag_hit_miss.all_instruction_cache_accesses', 'ic_tag_hit_miss.instruction_cache_miss', 'ic_cache_fill_l2', 'ic_cache_fill_sys',
    'l2_cache_req_stat.ic_fill_miss', 'l2_cache_req_stat.ic_fill_hit_s', 'l2_cache_req_stat.ic_fill_hit_x',
    'op_cache_hit_miss.op_cache_hit', 'op_cache_hit_miss.op_cache_miss', 'de_src_op_disp.decoder', 'de_src_op_disp.op_cache',
    'bp_l1_tlb_miss_l2_tlb_hit', 'bp_l1_tlb_miss_l2_tlb_miss.all',
    'de_no_dispatch_per_slot.no_ops_from_frontend', 'de_no_dispatch_per_slot.backend_stalls', 'de_no_dispatch_per_slot.smt_contention',
    'bp_de_redirect', 'resyncs_or_nc_redirects',
    'L1-dcache-loads', 'L1-dcache-load-misses', 'l2_cache_req_stat.ls_rd_blk_c', 'ls_l1_d_tlb_miss.all',
    'ls_any_fills_from_sys.local_l2', 'ls_any_fills_from_sys.local_ccx', 'ls_any_fills_from_sys.dram_io_near',
]

GROUP = re.compile(r'// Supernode (\d+): run when its activity flag is set\.')
BATCH = re.compile(r'void GrhSIM_SimTop::eval_(compute|commit)_batch_(\d+)\(\)')
FIRE = re.compile(r'^(\s*if \((?:unlikely|GRHSIM_LIKELY)\()(activeWordFlags & UINT8_C\(\d+\))(\)\) \{\s*)$')
WORD = re.compile(r'^(\s*if \(unlikely\()(activeWordFlags != UINT8_C\(0\))(\)\) \{\s*)$')
SAME = re.compile(r'^(\s*if \((?:unlikely\()?)([\w.\[\]]+ != next_value)((?:\))?\) \{\s*)$')
ENABLE = re.compile(r'^(\s*if \((?:unlikely\()?)(\(value_\w+_slots_\[\d+\]\) != 0)((?:\))?\) \{\s*)$')
WRITE = re.compile(r'// op \S+ \[kRegisterWritePort\] reg=(\S+)')


def spec(variant):
    """Source directory (None: emitted in place) and extra compiler flags of a variant."""
    if variant in EXTRA_FLAGS:
        return (OUT / BASES[variant] / 'model' if variant in BASES else DEFAULT / 'model'), EXTRA_FLAGS[variant]
    for suffix, flags in (('cmovlines', CMOV + LINES), ('cmov', CMOV), ('lines', LINES), ('ubsan', EXTRA_FLAGS['ubsan'])):
        base = OUT / variant.removesuffix(suffix) / 'model'
        if variant.endswith(suffix) and base.is_dir():
            return base, flags
    if variant == 'hint':
        return DEFAULT / 'model', ''
    if variant.endswith('hint') and (OUT / variant.removesuffix('hint') / 'model').is_dir():
        return OUT / variant.removesuffix('hint') / 'model', ''
    if (OUT / variant / 'emit-settings.txt').exists():
        return None, ''
    raise KeyError(variant)


def copy_sources(variant):
    dst = OUT / variant / 'model'
    dst.mkdir(parents=True, exist_ok=False)
    for path in sorted(spec(variant)[0].iterdir()):
        if path.suffix in ('.cpp', '.hpp') or path.name == 'Makefile':
            shutil.copy2(path, dst / path.name)
    return dst


def instrument(dst):
    """Wrap dispatch tests and scalar compares in counting helpers that return the tested value."""
    groups, words, sites = {}, [], []
    for path in sorted(dst.glob('grhsim_SimTop_sched_*.cpp')):
        phase = group = pending = None
        text = path.read_text(errors='replace').splitlines(keepends=True)
        with path.open('w') as out:
            out.write('#include "grhsim_observe.hpp"\n')
            for number, line in enumerate(text, 1):
                if line.startswith('void ') and (m := BATCH.match(line)):
                    phase = m[1]; group = None
                elif pending is not None:
                    m = FIRE.match(line); assert m, line
                    groups[pending]['likely'] = 'GRHSIM_LIKELY(' in m[1]
                    line = f'{m[1]}grhsim_observe::fire({pending}u, {m[2]}){m[3]}'; pending = None
                elif '// Supernode ' in line and (m := GROUP.search(line)):
                    group = pending = int(m[1]); assert group not in groups
                    groups[group] = dict(phase=phase, file=path.name, word=len(words) - 1, likely=None)
                    words[-1]['groups'].append(group)
                elif m := WORD.match(line):
                    line = f'{m[1]}grhsim_observe::word({len(words)}u, {m[2]}){m[3]}'
                    words.append(dict(phase=phase, file=path.name, line=number, groups=[])); group = None
                elif group is not None and (m := SAME.match(line)):
                    line = f'{m[1]}grhsim_observe::test({len(sites)}u, {m[2]}){m[3]}'
                    sites.append(dict(kind='compare', phase=phase, group=group, file=path.name, line=number,
                                      expr=m[2].removesuffix(' != next_value'), writes=0))
                elif group is not None and phase == 'commit' and (m := ENABLE.match(line)):
                    line = f'{m[1]}grhsim_observe::test({len(sites)}u, {m[2]}){m[3]}'
                    sites.append(dict(kind='enable', phase=phase, group=group, file=path.name, line=number,
                                      expr=m[2].removesuffix(' != 0'), writes=0))
                elif sites and group is not None and sites[-1]['group'] == group and WRITE.search(line):
                    sites[-1]['writes'] += 1
                out.write(line)
            assert pending is None
    (dst / 'grhsim_observe.hpp').write_text(f'''#pragma once
#include <cstdint>
namespace grhsim_observe {{
inline constexpr unsigned kGroups = {max(groups) + 1}, kWords = {len(words)}, kSites = {len(sites)}, kKinds = {KINDS};
extern std::uint64_t tested[kGroups][kKinds], fired[kGroups][kKinds], wordSeen[kWords][kKinds], wordHit[kWords][kKinds];
extern std::uint64_t siteSeen[kSites], siteHit[kSites], rounds[kKinds], evals[3];
extern unsigned phase, kind;
// Activity bitmaps of single rounds, kept for windows of consecutive guest cycles.
inline constexpr unsigned kGroupBytes = (kGroups + 7) / 8, kWordBytes = (kWords + 7) / 8;
extern bool tracing;
extern unsigned char groupBits[kGroupBytes], wordBits[kWordBytes];
template <typename T> inline T fire(unsigned group, T flags) {{
    ++tested[group][kind];
    if (flags != 0) {{ ++fired[group][kind]; if (tracing) groupBits[group >> 3] |= static_cast<unsigned char>(1u << (group & 7u)); }}
    return flags;
}}
inline bool word(unsigned index, bool hit) {{
    ++wordSeen[index][kind];
    if (hit) {{ ++wordHit[index][kind]; if (tracing) wordBits[index >> 3] |= static_cast<unsigned char>(1u << (index & 7u)); }}
    return hit;
}}
inline bool test(unsigned site, bool hit) {{ ++siteSeen[site]; siteHit[site] += hit; return hit; }}
void begin_eval(bool posedge, bool negedge);
void begin_round(std::uint64_t round);
void end_round(std::uint64_t round);
void dump();
}}
''')
    st = dst / 'grhsim_SimTop_state.cpp'; s = st.read_text()
    key = '    finalized_ = true;\n'; assert s.count(key) == 1
    st.write_text('#include "grhsim_observe.hpp"\n' + s.replace(key, key + '    grhsim_observe::dump();\n') + '''
#include <cstdio>
#include <cstdlib>
namespace grhsim_observe {
std::uint64_t tested[kGroups][kKinds]{}, fired[kGroups][kKinds]{}, wordSeen[kWords][kKinds]{}, wordHit[kWords][kKinds]{};
std::uint64_t siteSeen[kSites]{}, siteHit[kSites]{}, rounds[kKinds]{}, evals[3]{};
unsigned phase = 2, kind = 0;
bool tracing = false;
unsigned char groupBits[kGroupBytes]{}, wordBits[kWordBytes]{};
static std::FILE *trace = nullptr;
void begin_eval(bool posedge, bool negedge) {
    phase = posedge ? 0u : (negedge ? 1u : 2u);
    ++evals[phase];
    // 20 consecutive guest cycles out of every 2000, counted in rising clock edges.
    tracing = evals[0] % 2000u < 20u;
}
void begin_round(std::uint64_t round) {
    kind = phase * 4u + (round < 4u ? static_cast<unsigned>(round) : 4u) - 1u;
    ++rounds[kind];
}
void end_round(std::uint64_t round) {
    if (!tracing) return;
    if (!trace) {
        const char *path = std::getenv("GRHSIM_OBSERVE_TRACE"); if (!path) std::abort();
        trace = std::fopen(path, "wb"); if (!trace) std::abort();
    }
    const std::uint32_t head[3] = {static_cast<std::uint32_t>(evals[0]), phase, static_cast<std::uint32_t>(round)};
    std::fwrite(head, sizeof head, 1, trace);
    std::fwrite(groupBits, sizeof groupBits, 1, trace);
    std::fwrite(wordBits, sizeof wordBits, 1, trace);
    for (auto &byte : groupBits) byte = 0;
    for (auto &byte : wordBits) byte = 0;
}
static void row(std::FILE *f, const char *tag, unsigned index, const std::uint64_t *a, const std::uint64_t *b) {
    bool any = false;
    for (unsigned k = 0; k < kKinds; ++k) any = any || a[k] || b[k];
    if (!any) return;
    std::fprintf(f, "%s\\t%u", tag, index);
    for (unsigned k = 0; k < kKinds; ++k) std::fprintf(f, "\\t%llu\\t%llu", (unsigned long long)a[k], (unsigned long long)b[k]);
    std::fputc('\\n', f);
}
void dump() {
    const char *path = std::getenv("GRHSIM_OBSERVE_FILE"); if (!path) std::abort();
    auto *f = std::fopen(path, "w"); if (!f) std::abort();
    std::fprintf(f, "E\\t%llu\\t%llu\\t%llu\\n", (unsigned long long)evals[0], (unsigned long long)evals[1], (unsigned long long)evals[2]);
    std::fprintf(f, "R");
    for (unsigned k = 0; k < kKinds; ++k) std::fprintf(f, "\\t%llu", (unsigned long long)rounds[k]);
    std::fputc('\\n', f);
    for (unsigned i = 0; i < kGroups; ++i) row(f, "G", i, tested[i], fired[i]);
    for (unsigned i = 0; i < kWords; ++i) row(f, "W", i, wordSeen[i], wordHit[i]);
    for (unsigned i = 0; i < kSites; ++i)
        if (siteSeen[i]) std::fprintf(f, "S\\t%u\\t%llu\\t%llu\\n", i, (unsigned long long)siteSeen[i], (unsigned long long)siteHit[i]);
    if (std::fclose(f)) std::abort();
    if (trace && std::fclose(trace)) std::abort();
}
}
''')
    ev = dst / 'grhsim_SimTop_eval.cpp'; s = ev.read_text()
    loop, step, last = '    while (pending_eval_round) {\n', '++fixed_point_round_count;', '        hot_event_posedge_ = false;\n'
    assert s.count(loop) == 1 and s.count(step) == 1 and s.count(last) == 1
    s = s.replace(loop, '    grhsim_observe::begin_eval(hot_event_posedge_, '
                  'event_edge_storage_[0] == grhsim_event_edge_kind::negedge);\n' + loop)
    s = s.replace(step, step + ' grhsim_observe::begin_round(fixed_point_round_count);')
    s = s.replace(last, last + '        grhsim_observe::end_round(fixed_point_round_count);\n')
    ev.write_text('#include "grhsim_observe.hpp"\n' + s)
    save(OUT / 'obs/groups.json', groups)
    save(OUT / 'obs/words.json', words)
    with (OUT / 'obs/sites.tsv').open('w') as stream:
        for index, site in enumerate(sites):
            stream.write('\t'.join(map(str, (index, site['kind'], site['phase'], site['group'], site['file'], site['line'],
                                             site['writes'], site['expr']))) + '\n')
    print('observer: supernodes', len(groups), 'words', len(words), 'sites', len(sites),
          {k: sum(s['kind'] == k for s in sites) for k in ('compare', 'enable')}, flush=True)


def hint_mux(dst):
    """Probe: tell the compiler that the scalar multiplexer's condition is not predictable."""
    header = dst / 'grhsim_SimTop_runtime.hpp'
    text = header.read_text()
    old = ('    const std::uint64_t trueMask = static_cast<std::uint64_t>(-static_cast<std::int64_t>(cond != 0));\n'
           '    return (trueValue & trueMask) | (falseValue & ~trueMask);\n')
    head = 'inline std::uint64_t grhsim_mux_u64(std::uint64_t cond, std::uint64_t trueValue, std::uint64_t falseValue)\n{\n'
    assert text.count(head + old) == 1
    header.write_text(text.replace(head + old, head + '    return __builtin_unpredictable(cond != 0) ? trueValue : falseValue;\n'))


def add_state_dump(dst):
    """Probe: after chosen evals, write hashes or the bytes of the whole model object.  It never changes the model."""
    header = dst / 'grhsim_SimTop.hpp'; text = header.read_text()
    key = '    void eval();\n'; assert text.count(key) == 1
    header.write_text(text.replace(key, key + '    void debug_state_tick();\n'))
    ev = dst / 'grhsim_SimTop_eval.cpp'; text = ev.read_text()
    key = '    first_eval_ = false;\n}\n'; assert text.count(key) == 1 and text.endswith(key)
    ev.write_text(text.replace(key, '    first_eval_ = false;\n    debug_state_tick();\n}\n'))
    st = dst / 'grhsim_SimTop_state.cpp'
    st.write_text(st.read_text() + r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
// GRHSIM_STATE_DIR     output directory; unset turns the probe off
// GRHSIM_STATE_EVERY   one record of bucket hashes every this many evals within FROM..TO (0: none)
// GRHSIM_STATE_BUCKET  bytes per bucket
// GRHSIM_STATE_RAW     comma separated eval indices whose object bytes are written in full
void GrhSIM_SimTop::debug_state_tick()
{
    static std::uint64_t index = 0, every = 0, bucket = 4096, from = 0, to = ~UINT64_C(0), raw[32];
    static unsigned rawCount = 0;
    static const char *dir = nullptr;
    static std::FILE *hashes = nullptr;
    static bool configured = false;
    if (!configured) {
        configured = true;
        dir = std::getenv("GRHSIM_STATE_DIR");
        if (dir) {
            const auto number = [](const char *name, std::uint64_t fallback) {
                const char *text = std::getenv(name);
                return text ? std::strtoull(text, nullptr, 10) : fallback;
            };
            every = number("GRHSIM_STATE_EVERY", 0); bucket = number("GRHSIM_STATE_BUCKET", 4096);
            from = number("GRHSIM_STATE_FROM", 0); to = number("GRHSIM_STATE_TO", ~UINT64_C(0));
            if (const char *list = std::getenv("GRHSIM_STATE_RAW")) {
                char *end = nullptr;
                for (const char *at = list; *at && rawCount < 32; at = *end ? end + 1 : end) {
                    raw[rawCount++] = std::strtoull(at, &end, 10);
                }
            }
            if (every) {
                hashes = std::fopen((std::string(dir) + "/hashes.bin").c_str(), "wb"); if (!hashes) std::abort();
                const std::uint64_t head[4] = {sizeof(*this), bucket, every, from};
                std::fwrite(head, sizeof head, 1, hashes);
            }
        }
    }
    ++index;
    if (!dir) return;
    const auto *bytes = reinterpret_cast<const unsigned char *>(this);
    const std::size_t size = sizeof(*this);
    if (hashes && index >= from && index <= to && (index - from) % every == 0) {
        std::fwrite(&index, sizeof index, 1, hashes);
        for (std::size_t at = 0; at < size; at += bucket) {
            const std::size_t stop = at + bucket < size ? at + bucket : size;
            std::uint64_t h = UINT64_C(0x9E3779B97F4A7C15);
            std::size_t i = at;
            for (; i + 8 <= stop; i += 8) {
                std::uint64_t w; std::memcpy(&w, bytes + i, 8);
                h = (h ^ w) * UINT64_C(0x100000001B3); h ^= h >> 29;
            }
            for (; i < stop; ++i) h = (h ^ bytes[i]) * UINT64_C(0x100000001B3);
            std::fwrite(&h, sizeof h, 1, hashes);
        }
        std::fflush(hashes);
    }
    for (unsigned r = 0; r < rawCount; ++r) {
        if (raw[r] != index) continue;
        std::FILE *f = std::fopen((std::string(dir) + "/raw-" + std::to_string(index) + ".bin").c_str(), "wb");
        if (!f || std::fwrite(bytes, 1, size, f) != size || std::fclose(f)) std::abort();
    }
}
""")


def hint_dispatch(dst):
    """Probe: expect the body at supernode tests that fired in more than half of their executions (observer run)."""
    chosen = set()
    for line in (OUT / 'obs/counts.tsv').open():
        f = line.split('\t')
        if f[0] == 'G':
            v = list(map(int, f[2:]))
            if 2 * sum(v[1::2]) > sum(v[0::2]):
                chosen.add(int(f[1]))
    flipped = kept = 0
    for path in sorted(dst.glob('grhsim_SimTop_sched_*.cpp')):
        text = path.read_text(errors='replace').splitlines(keepends=True)
        pending = None
        for number, line in enumerate(text):
            if pending is not None:
                m = FIRE.match(line); assert m, line
                if pending in chosen and m[1].endswith('unlikely('):
                    text[number] = m[1].removesuffix('unlikely(') + 'GRHSIM_LIKELY(' + m[2] + m[3]; flipped += 1
                else:
                    kept += 1
                pending = None
            elif '// Supernode ' in line and (m := GROUP.search(line)):
                pending = int(m[1])
        path.write_text(''.join(text))
    save(dst.parent / 'hint.json', dict(rule='fired in more than half of the tests of the observer run',
         chosen=len(chosen), tests_changed_to_likely=flipped, tests_unchanged=kept))
    print('dispatch hints: chosen', len(chosen), 'changed', flipped, 'unchanged', kept, flush=True)


def prepare(variant):
    base, flags = spec(variant)
    if base is None:
        save(OUT / variant / 'sources.json', dict(
            base='emitted', emit_settings=(OUT / variant / 'emit-settings.txt').read_text().split(),
            files=source_inventory(OUT / variant / 'model'), extra_model_flags=''))
        print(variant, 'prepared', flush=True)
        return
    dst = copy_sources(variant)
    if variant == 'obs':
        instrument(dst)
    if variant in ('muxhint', 'muxhintlines'):
        hint_mux(dst)
    if variant in ('sdplain', 'sdpgo'):
        add_state_dump(dst)
    if variant.endswith('hint'):
        hint_dispatch(dst)
    save(OUT / variant / 'sources.json', dict(base=str(base), base_files=source_inventory(base),
         changed=variant in ('obs', 'muxhint', 'muxhintlines', 'sdplain', 'sdpgo') or variant.endswith('hint'),
         extra_model_flags=flags.strip()))
    print(variant, 'prepared', flush=True)


def build(variant):
    dst = OUT / variant
    shutil.copytree(DEFAULT / 'chisel-home', dst / 'chisel-home', dirs_exist_ok=True)
    env = dict(clean_environment(), NOOP_HOME=str(ARCHIVE / 'testcase/xiangshan'), LC_ALL='C')
    argv = [v.replace(str(DEFAULT), str(dst)) for v in read(DEFAULT / 'compile.command.json')['argv']]
    flags = [i for i, v in enumerate(argv) if v.startswith('GRHSIM_MODEL_CXXFLAGS=')]
    assert len(flags) == 1
    argv[flags[0]] += spec(variant)[1]
    if variant == 'obs':
        # Counter arrays alias everything; the type-based analysis gets very slow on them.
        argv[flags[0]] += ' -fno-strict-aliasing'
    if '-fprofile-generate' in spec(variant)[1]:
        argv.append(f'PGO_LDFLAGS=-fprofile-generate={OUT}/{variant}/profile')
    if variant.endswith('ubsan'):
        argv.append('PGO_LDFLAGS=-fsanitize=undefined')
    run(argv, dst / 'compile.log', env=env)
    save(dst / 'binary.json', identity(dst / 'emu/grhsim-compile/emu'))
    print(variant, 'built', flush=True)


def idle(cpus):
    def snap():
        out = {}
        for line in Path('/proc/stat').read_text().splitlines():
            f = line.split()
            if f[0][3:].isdigit() and int(f[0][3:]) in cpus:
                v = list(map(int, f[1:9])); out[int(f[0][3:])] = (sum(v), v[3] + v[4])
        return out
    a = snap(); time.sleep(2); b = snap()
    return {k: 100 * (b[k][1] - a[k][1]) / max(1, b[k][0] - a[k][0]) for k in a}


def pick_cpu():
    """An idle core on NUMA node 1 whose SMT sibling is idle, in the L3 group with most idle cores."""
    assert platform.node().startswith('node029')
    for _ in range(120):
        rate = idle(set(range(96, 192)) | set(range(288, 384)))
        free = [c for c in range(96, 192) if rate[c] >= 99 and rate[c + 192] >= 99]
        if free:
            by_group = {}
            for c in free:
                by_group.setdefault(c // 8, []).append(c)
            best = max(by_group.values(), key=len)
            return best[len(best) // 2], len(best)
        time.sleep(5)
    raise RuntimeError('no idle core pair on node 1')


def runtime(directory, binary):
    rt = directory / 'runtime'
    for sub in ('image/workload.bin', 'ref/nemu.so'):
        (rt / sub).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(RUNTIME / sub, rt / sub)
    shutil.copytree(RUNTIME / 'lib', rt / 'lib')
    (rt / 'bin').mkdir(); shutil.copy2(binary, rt / 'bin/emu')
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'USER', 'LANG')}
    env.update(LC_ALL='C', LD_LIBRARY_PATH=str(rt / 'lib'))
    emu = [str(rt / 'bin/emu'), '-i', str(rt / 'image/workload.bin'), '--diff', str(rt / 'ref/nemu.so'), '-b', '0', '-e', '0', '-s', '0']
    return rt, env, emu


def launch(prefix, emu, cycles, rt, env, log):
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    cpu, group_idle = pick_cpu()
    cmd = ['taskset', '-c', str(cpu), 'numactl', '--membind=1', *prefix, 'setarch', 'x86_64', '-R', *emu, '-C', str(cycles)]
    start = time.monotonic()
    with log.open('w') as stream:
        code = subprocess.run(cmd, cwd=rt / 'bin', env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
    text = re.sub(r'\x1b\[[0-9;]*m', '', log.read_text(errors='replace'))
    want = {100000: 'instrCnt = 250,838', 10000: 'instrCnt = 371'}[cycles]
    ok = (code == 0 and 'EXCEEDING CYCLE/INSTR LIMIT' in text and want in text
          and not re.search(r'ABORT|HIT BAD TRAP|mismatch|Assertion.*failed', text, re.I))
    record = dict(command=cmd, returncode=code, endpoint_ok=ok, cpu=cpu, idle_cores_in_l3_group=group_idle,
                  wall_s=time.monotonic() - start, tail=[l for l in text.splitlines() if 'instrCnt' in l or 'Host time' in l][-3:])
    if not ok:
        raise RuntimeError(json.dumps(record, indent=1))
    return record


def observe():
    out = OUT / 'obs'
    rt, env, emu = runtime(out, out / 'emu/grhsim-compile/emu')
    env.update(GRHSIM_OBSERVE_FILE=str(out / 'counts.tsv'), GRHSIM_OBSERVE_TRACE=str(out / 'trace.bin'))
    save(out / 'run.json', launch([], emu, 100000, rt, env, out / 'run.log'))
    shutil.rmtree(rt)
    print('observer run complete', flush=True)


def train(variant='pgogen2'):
    out = OUT / variant
    assert not list((out / 'profile').glob('*.profraw')), 'the profile directory already holds a run'
    rt, env, emu = runtime(out, out / 'emu/grhsim-compile/emu')
    record = launch([], emu, 100000, rt, env, out / 'train.log')
    raw = sorted((out / 'profile').glob('*.profraw'))
    assert raw, 'no raw profile written'
    run([LLVM / 'llvm-profdata', 'merge', *raw, '-o', out / 'profile/default.profdata'], out / 'merge.log')
    record.update(raw=[identity(p) for p in raw], merged=identity(out / 'profile/default.profdata'))
    save(out / 'train.json', record)
    shutil.rmtree(rt)
    print('profile trained and merged', flush=True)


def counts(variant):
    out = OUT / 'pmu' / variant
    out.mkdir(parents=True, exist_ok=False)
    binary = DEFAULT / 'emu/grhsim-compile/emu' if variant == 'default' else OUT / variant / 'emu/grhsim-compile/emu'
    rt, env, emu = runtime(out, binary)
    summary = []
    for name, cycles in (('events-100k', 100000), ('events-10k', 10000)):
        prefix = ['perf', 'stat', '-x,', '-e', ','.join(e + ':u' for e in EVENTS), '-o', str(out / f'{name}.stat.txt'), '--']
        record = launch(prefix, emu, cycles, rt, env, out / f'{name}.log')
        record['counts'] = {}
        for line in (out / f'{name}.stat.txt').read_text().splitlines():
            f = line.split(',')
            if len(f) > 4 and f[0].replace('.', '').isdigit():
                record['counts'][f[2].removesuffix(':u')] = dict(count=float(f[0]), running_percent=float(f[4]) if f[4] else None)
        summary.append(dict(name=name, cycles=cycles, **record))
        save(out / 'summary.json', dict(binary=identity(binary), runs=summary))
    shutil.rmtree(rt)
    print(variant, 'event counts complete', flush=True)


def sample(variant, what, period=None):
    # The kernel drops samples above its rate limit (16,000 per second here).  A run that finishes in
    # 90 s needs an op period of 400000 to stay below it; the first runs used 150000 on slower cores.
    default = {'op': 150000, 'cycles': 300000, 'fetch': 50000}[what]
    period = int(period or default)
    out = OUT / 'ibs' / (f'{variant}-{what}' if period == default else f'{variant}-{what}-p{period}')
    out.mkdir(parents=True, exist_ok=False)
    binary = OUT / variant / 'emu/grhsim-compile/emu'
    rt, env, emu = runtime(out, binary)
    event = {'op': 'ibs_op/cnt_ctl=1/', 'cycles': 'ibs_op/cnt_ctl=0/', 'fetch': 'ibs_fetch/rand_en=1/'}[what]
    prefix = ['perf', 'record', '-q', '-e', event, '-c', str(period), '--raw-samples', '-o', str(out / 'perf.data'), '--']
    record = launch(prefix, emu, 100000, rt, env, out / 'run.log')
    save(out / 'run.json', dict(binary=identity(binary), event=event, period=period, **record))
    # The symbolizer needs the sampled binary at the recorded path, so keep it until decoded.
    decode = [sys.executable, ROOT / 'scripts/armor_dispatch_ibs.py', 'decode', what, out]
    run(decode, out / 'decode.log')
    shutil.rmtree(rt)
    print(variant, what, 'samples decoded', flush=True)


def measure(variant):
    """Functional check and eight paired rounds on node030 CPU96: released default against one variant."""
    from armor_mask_layout_measure import LOCK
    from xiangshan_cv32_ablation_measure import measurement_lock
    if platform.node().split('.')[0] != 'node030':
        raise ValueError('walltime runs belong on node030')
    inputs = read(DEFAULT / 'verify/default/runs/input_identity.json')
    args = [sys.executable, '-u', ROOT / 'scripts/grhsim_single_compare.py', '--baseline', DEFAULT,
            '--candidate', OUT / variant, '--output', OUT / f'timing-{variant}', '--pairs', '8', '--cycles', '100000',
            '--candidate-sim-primitives', 'none', '--image', inputs['image']['path'], '--nemu', inputs['nemu']['path'],
            '--skip-idle-check']
    print('Waiting for the shared CPU96 lock.', flush=True)
    with measurement_lock(LOCK, wait=True):
        subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def rounds(tag, variants):
    """One measurement session for several variants: every round runs the default and each variant once."""
    import argparse
    from armor_mask_layout_measure import LOCK
    from grhsim_difftrace import build_comparator, compare_traces
    from grhsim_single_baseline import Baseline
    from grhsim_single_compare import summarize
    from xiangshan_cv32_ablation_measure import measurement_lock, signature
    if platform.node().split('.')[0] != 'node030':
        raise ValueError('walltime runs belong on node030')
    inputs = read(DEFAULT / 'verify/default/runs/input_identity.json')
    names = ['default', *variants]
    binaries = {'default': DEFAULT / 'emu/grhsim-compile/emu', **{v: OUT / v / 'emu/grhsim-compile/emu' for v in variants}}
    # Rotate the starting variant and alternate the direction, so position and neighbours vary over the rounds.
    orders = [(names[i % len(names):] + names[:i % len(names)])[::1 if i % 2 == 0 else -1] for i in range(8)]
    dest = OUT / f'timing-{tag}'
    print('Waiting for the shared CPU96 lock.', flush=True)
    with measurement_lock(LOCK, wait=True):
        dest.mkdir()
        resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        save(dest / 'policy.json', dict(variants=names, order=orders, binaries={n: identity(b) for n, b in binaries.items()},
             placement='node030 CPU96 NUMA1, single thread, ASLR off, shared lock', cycles=100000,
             checks='endpoint of every run; DiffTest trace of every variant against the default trace of this session'))
        setups = {}
        for name in names:
            args = argparse.Namespace(output=dest / name, binary=binaries[name], image=Path(inputs['image']['path']),
                                      nemu=Path(inputs['nemu']['path']), compiler=LLVM / 'clang++', cpu=96, cycles=100000,
                                      jobs=1, repeats=1, sim_primitives='none', tools_dir=None, skip_idle_check=True)
            runner = Baseline(args)
            setups[name] = (runner, runner.prepare_measurement())
        comparator = build_comparator(DEFAULT / 'chisel-home/build/generated-src/difftest-state.h', dest / 'trace-comparator')
        expected, checks = None, {}
        for name in names:
            runner, setup = setups[name]
            run = runner.run_sample(setup, 'verify-s0', 100000, 0, ['--dump-difftrace', './trace_s0'])
            expected = expected or signature(run)
            if signature(run) != expected or run['instr_count'] != 250838:
                raise ValueError(f'unexpected endpoint: {name} {signature(run)}')
            checks[name] = dict(run=run)
            if name != 'default':
                trace = compare_traces(comparator, setups['default'][1]['binary'].parent / 'trace_s0',
                                       setup['binary'].parent / 'trace_s0', dest / f'{name}-trace.json')
                if not trace['pass_']:
                    raise ValueError(f'DiffTest trace differs from the default: {name}')
                checks[name]['trace_records'] = sum(c['records'] for c in trace['chunks'])
            save(dest / 'checks.json', checks)
            print('checked', name, flush=True)

        def sample(name, label):
            runner, setup = setups[name]
            row = runner.run_sample(setup, label, 100000, 0, [])
            if signature(row) != expected:
                raise ValueError(f'unexpected timed endpoint: {name}')
            return row
        save(dest / 'warmups.json', {name: sample(name, 'warmup') for name in names})
        rows = []
        for i, order in enumerate(orders):
            row = dict(round=i, order=order)
            for name in order:
                row[name] = sample(name, f'round{i:02d}')
            rows.append(row)
            save(dest / 'rounds.json', rows)
            print('round', i + 1, 'of 8', {n: row[n]['host_ms'] for n in names}, flush=True)
        pairs = [(a, b) for a in names for b in names if a != b and names.index(a) < names.index(b)]
        save(dest / 'summary.json', dict(
            functional_signature=expected, variants=names,
            comparisons={f'{b} vs {a}': summarize([dict(A=r[a], B=r[b]) for r in rows]) for a, b in pairs}))
    with (dest / 'rounds.csv').open('w') as stream:
        stream.write('round,position,variant,host_s\n')
        for row in rows:
            for position, name in enumerate(row['order']):
                stream.write(f"{row['round']},{position},{name},{row[name]['host_ms'] / 1000}\n")
    print('rounds complete', flush=True)


if __name__ == '__main__':
    stage = sys.argv[1]
    if stage in ('prepare', 'build'):
        {'prepare': prepare, 'build': build}[stage](sys.argv[2])
    elif stage == 'sample':
        sample(*sys.argv[2:5])
    elif stage == 'counts':
        counts(sys.argv[2])
    elif stage == 'measure':
        measure(sys.argv[2])
    elif stage == 'rounds':
        rounds(sys.argv[2], sys.argv[3:])
    elif stage == 'train':
        train(*sys.argv[2:3])
    else:
        observe()
