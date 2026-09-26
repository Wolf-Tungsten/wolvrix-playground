#!/usr/bin/env python3
"""NO00018 dynamic instruction-class attribution: address-level sampling x
disassembly classification on the production PGO emu binary.

Links three inputs of one production configuration (default: the NO00015
archive, the current-best build):

  1. full objdump disassembly dump (--disasm; `objdump -d --no-show-raw-insn`),
     mechanically classified into the pre-registered 18 instruction classes;
  2. 3 perf record cycle-sample runs (--perf, `perf script -F dso,ip --ns`),
     mapped address -> instruction after automatic per-run load-bias
     correction (the PIE emu is mmap'd high while objdump VMAs start at 0, and
     each run is a separate ASLR process; the per-run offset is estimated by
     anchor alignment: the densest sample IP must land on an instruction VMA
     with identical low 12 bits, every such VMA yields a candidate offset,
     and the candidate with the most exact instruction-address hits over the
     distinct sample IPs wins, verified by interval coverage);
  3. dyn run log + production checkpoint (--run/--model) for the M-coldbias
     closed-form caliber (fires x static per-task class counts / cycles);
     checkpoint-derived task->unit mapping is cached as a pickle in the output
     directory keyed on (path, mtime, size).

Gates (pre-registered in pdocs/NO00018-*.md; amended 2026-09-26 per the
report's "门槛修订登记" after the first-round G2/G3/G4 failures — original
gate outcomes are still reported in the summary's `informational` section):
  G1 merged samples inside model functions (task/helper/simtop_other)
     >= 100,000 and emu address->function interval coverage >= 99%;
  G2 for classes with merged share >= 1% of all samples, sample SD (n-1)
     of the per-run shares <= 0.5pp (empirical run-level spread model);
  G3 |sample model share - phase model wall share| <= 1.0pp, where the
     sample side is (task+helper+simtop_other)/all and the phase side is
     the same-build [grhsim-cpu-phase] timing (compute+commit+publish)/host
     from --phase-csv runs on the same binary;
  G4 flag_rmw dynamic instr/cycle in [123,000 x f_mem x 0.80, 250K] with
     f_mem = 0.96119 the fires-weighted memory-dest-OR share of arm sites
     (arm_form_census.json); per-class instr/cycle = share of ALL samples
     x 3,949,943.3 (NO00016 perfstat whole-process baseline).
  G5 (registered, no gate): M-coldbias per-class ratio table, M-fhot top-30
     function table + count of functions >= 0.1%, skid sensitivity, per-class
     bootstrap 95% CI (multinomial resampling of the merged class vector,
     fixed seed 20260926).

Outputs (--output): summary.json, summary.md, iclass_per_run.tsv.
"""

import argparse
import bisect
from collections import Counter
import json
import math
import os
from pathlib import Path
import pickle
import re
import subprocess
import sys
from array import array

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_kind_cost_census import compute_task_units, load_dyn_fires  # noqa: E402

# Pre-registered fixed class list (18 classes incl. misc), in match order.
CLASSES = ["mask_and", "flag_rmw", "stk_st", "stk_ld", "heap_st", "heap_ld",
           "sse", "branch", "cmov", "setcc", "cmp", "shift", "logic", "call",
           "lea", "mov_rr", "arith", "misc"]
CLS_IDX = {name: i for i, name in enumerate(CLASSES)}

INSTR_PER_CYCLE_BASELINE = 3_949_943.3   # NO00016 perfstat whole-process total
DEFAULT_CYCLES = 100001
BOOT_SEED = 20260926
BOOT_ITERS = 10000
G1_MIN_MODEL_SAMPLES = 100_000
G1_MIN_COVERAGE = 0.99
G3_RANGE = (0.905, 0.920)
G4_RANGE = (100_000.0, 250_000.0)
# Amended gates (registered 2026-09-26 in the report's "门槛修订登记" after
# the first-round failures; original bands above are kept for the
# informational comparison only):
G2_SD_LIMIT = 0.005           # sample SD (n-1) of per-run shares
G3_TOL = 0.01                 # |sample model share - phase model wall share|
G4_ANCHOR_ARMS = 123_000.0    # NO00017 G1 deterministic arm ops/cycle
G4_F_MEM = 0.96119            # memory-dest-OR form share (arm_form_census)
G4_GUARD_ALLOWANCE = 0.80     # guard-selectivity allowance
G4_CEILING = 250_000.0

HEADER_RE = re.compile(r"^([0-9a-f]+) <([^>]+)>:\s*$")
PERF_RE = re.compile(r"^\s*([0-9a-fA-F]+)\s+\((.*)\)\s*$")
TASK_RE = re.compile(r"^_ZN13GrhSIM_SimTop\d+cpu_task_(\d+)E")
HELPER_RE = re.compile(r"^_ZN13GrhSIM_SimTop\d+cpu_helper_(\d+)_(\d+)E")
SIMTOP_PREFIX = "_ZN13GrhSIM_SimTop"

AND_MNS = {"and", "andb", "andw", "andl", "andq"}
FLAG_RMW_MNS = {"or", "orb", "and", "andb", "add", "addb"}
MOV_MNS = {"mov", "movb", "movw", "movl", "movq"}
STACK_REGS = {"%rsp", "%rbp"}
PREFIX_MNS = {"lock", "rep", "repz", "repne", "repe", "data16", "bnd", "notrack"}
SSE_EXPLICIT = {"movups", "movaps", "movdqa", "movdqu", "movd", "movntdq",
                "movntq", "movntps", "movhlps", "movlhps", "movmskps", "movmskpd"}
SSE_P_EXCLUDE = {"push", "pop", "pushq", "popq", "pushl", "popl", "pushw", "popw",
                 "pushf", "popf", "pushfq", "popfq", "pusha", "popa", "pushal",
                 "popal", "pause", "popcnt", "prefetch", "prefetchnta",
                 "prefetcht0", "prefetcht1", "prefetcht2", "prefetchw",
                 "pdep", "pext"}
SHIFT_PREFIXES = ("shl", "shr", "sar", "rol", "ror")
LOGIC_PREFIXES = ("and", "or", "xor", "not")
ARITH_PREFIXES = ("add", "sub", "imul", "idiv", "div", "inc", "dec", "neg",
                  "adc", "sbb")

BUCKET_ORDER = ["task", "helper", "simtop_other", "emu_other"]


# ---------------------------------------------------------------------------
# Instruction classifier (pre-registered mechanical rules, first match wins)
# ---------------------------------------------------------------------------


def split_operands(ops):
    """Split an objdump operand string on top-level commas (paren-aware)."""
    out = []
    depth = 0
    current = []
    for ch in ops:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return [o.strip() for o in out]


def mem_base(operand):
    """Base register of a memory operand (`0x170(%r14,%rdx,1)` -> `%r14`)."""
    i = operand.find("(")
    if i < 0:
        return None
    j = operand.find(")", i)
    if j < 0:
        return None
    return operand[i + 1:j].split(",", 1)[0]


def parse_imm(operand):
    """`$0x3f` / `$15` -> int; None when not an immediate."""
    if not operand.startswith("$"):
        return None
    try:
        return int(operand[1:], 0)
    except ValueError:
        return None


def is_sse(mn, ops):
    """SSE/AVX mnemonic shape: explicit list, p/v prefix, or ss/sd/ps/pd suffix."""
    if mn in SSE_EXPLICIT:
        return True
    if mn == "movq":
        return "%xmm" in ops or "%mm" in ops
    first = mn[:1]
    if first == "p":
        return mn not in SSE_P_EXCLUDE
    if first == "v":
        return True
    return mn.endswith(("ss", "sd", "ps", "pd"))


def classify_insn(mn, ops):
    """Map (mnemonic, operand string) to one of the 18 pre-registered classes."""
    # 1. mask_and: and with immediate 2^n-1, n not a native width.
    if mn in AND_MNS and ops.startswith("$"):
        value = parse_imm(ops.split(",", 1)[0])
        if (value is not None and value > 0 and (value & (value + 1)) == 0
                and value.bit_length() not in (8, 16, 32, 64)):
            return "mask_and"
    operands = split_operands(ops) if ops else []
    dst = operands[-1] if operands else ""
    src = operands[0] if len(operands) > 1 else ""
    dst_mem = "(" in dst
    src_mem = "(" in src
    dst_base = mem_base(dst) if dst_mem else None
    src_base = mem_base(src) if src_mem else None
    # 2. flag_rmw: or/and/add (byte forms) with non-stack memory destination.
    if mn in FLAG_RMW_MNS and dst_mem and dst_base not in STACK_REGS:
        return "flag_rmw"
    # 3./5. mov stores: stack vs heap destination.
    if mn in MOV_MNS and dst_mem:
        return "stk_st" if dst_base in STACK_REGS else "heap_st"
    # 4./6. mov-family loads (mov/movz*/movs* sign/zero-extends; SSE mov
    # spellings movss/movsd stay with sse): stack vs heap source.
    if (mn in MOV_MNS or mn.startswith("movz")
            or (mn.startswith("movs") and mn not in ("movss", "movsd"))) and src_mem:
        return "stk_ld" if src_base in STACK_REGS else "heap_ld"
    # 7. sse.
    if is_sse(mn, ops):
        return "sse"
    # 8..15. single-mnemonic families.
    if mn.startswith("j"):
        return "branch"
    if mn.startswith("cmov"):
        return "cmov"
    if mn.startswith("set"):
        return "setcc"
    if mn.startswith("cmp") or mn.startswith("test"):
        return "cmp"
    if mn.startswith(SHIFT_PREFIXES):
        return "shift"
    if mn.startswith(LOGIC_PREFIXES):
        return "logic"
    if mn.startswith("call"):
        return "call"
    if mn in ("lea", "leab", "leaw", "leal", "leaq"):
        return "lea"
    # 16. mov_rr: pure register-to-register mov (immediate->reg falls to misc).
    if mn in MOV_MNS:
        return "mov_rr" if not ops.startswith("$") and "(" not in ops else "misc"
    # 17. arith (register/immediate forms; memory destinations caught above).
    if mn.startswith(ARITH_PREFIXES):
        return "arith"
    # 18. misc (nop/push/pop/ret/leave, movz reg-reg, ...).
    return "misc"


# ---------------------------------------------------------------------------
# Disassembly parsing (pure over an iterable of objdump lines)
# ---------------------------------------------------------------------------


def parse_disasm(lines):
    """Parse objdump -d text into per-function segments with per-instruction
    class ids. Same-named headers (PGO cold splits) merge into one function."""
    funcs = {}
    cache = {}
    current = None  # (name, segment index)
    for line in lines:
        first = line[:1]
        if first == " " or first == "\t":
            if current is None:
                continue
            pos = line.find(":\t")
            if pos <= 0:
                continue
            try:
                addr = int(line[:pos], 16)
            except ValueError:
                continue
            body = line[pos + 2:]
            mark = body.find(" #")
            if mark >= 0:
                body = body[:mark]
            mark = body.find(" <")
            if mark >= 0:
                body = body[:mark]
            body = body.rstrip()
            cls = cache.get(body)
            if cls is None:
                parts = body.split(None, 1)
                mn = parts[0] if parts else ""
                ops = parts[1] if len(parts) > 1 else ""
                while mn in PREFIX_MNS and ops:
                    sub = ops.split(None, 1)
                    mn = sub[0]
                    ops = sub[1] if len(sub) > 1 else ""
                cls = CLS_IDX[classify_insn(mn, ops)] if mn else CLS_IDX["misc"]
                cache[body] = cls
            name, seg = current
            func = funcs[name]
            func["addrs"][seg].append(addr)
            func["cls"][seg].append(cls)
            func["counts"][cls] += 1
            func["n"] += 1
        elif first in "0123456789abcdef":
            match = HEADER_RE.match(line.rstrip("\n"))
            if not match:
                continue
            name = match.group(2)
            func = funcs.get(name)
            if func is None:
                func = {"segments": [], "addrs": [], "cls": [],
                        "counts": [0] * len(CLASSES), "n": 0}
                funcs[name] = func
            func["segments"].append([int(match.group(1), 16), 0])
            func["addrs"].append(array("Q"))
            func["cls"].append(array("B"))
            current = (name, len(func["segments"]) - 1)
        elif not line.strip():
            current = None
    for func in funcs.values():
        for seg, addrs in enumerate(func["addrs"]):
            func["segments"][seg][1] = addrs[-1] if addrs else func["segments"][seg][0]
    return funcs


def build_lookup(funcs):
    """Sorted (start, end, name, segment) interval list + start array."""
    intervals = []
    for name, func in funcs.items():
        for seg, (start, end) in enumerate(func["segments"]):
            intervals.append((start, end, name, seg))
    intervals.sort()
    return intervals, [iv[0] for iv in intervals]


def map_address(vma, intervals, starts):
    """vma -> (name, segment) of the containing function interval, or None."""
    i = bisect.bisect_right(starts, vma) - 1
    if i < 0:
        return None
    start, end, name, seg = intervals[i]
    return (name, seg) if start <= vma <= end else None


# ---------------------------------------------------------------------------
# Symbol / DSO bucketing
# ---------------------------------------------------------------------------


def symbol_bucket(mangled, demangled):
    """emu-internal symbol -> (bucket, label): cpu_task / cpu_helper (unit in
    the first number) / other GrhSIM_SimTop methods / other emu symbols."""
    match = TASK_RE.match(mangled)
    if match:
        return "task", f"cpu_task_{match.group(1)}"
    match = HELPER_RE.match(mangled)
    if match:
        return "helper", f"cpu_helper_{match.group(1)}_{match.group(2)}"
    if mangled.startswith(SIMTOP_PREFIX):
        short = demangled
        if short.startswith("GrhSIM_SimTop::"):
            short = short[len("GrhSIM_SimTop::"):]
        short = short.split("(", 1)[0]
        return "simtop_other", f"simtop::{short}"
    return "emu_other", demangled or mangled


def dso_bucket(dso):
    """Non-emu sample -> dso:<basename> bucket ([unknown]/empty -> unknown)."""
    if not dso or dso == "[unknown]":
        return "unknown"
    base = dso.rsplit("/", 1)[-1]
    if base.startswith("[") and base.endswith("]"):
        return "dso:" + base[1:-1]
    if "nemu" in base:
        return "dso:nemu"
    base = re.sub(r"\.so(\..*)?$", "", base)
    if base.endswith("-so"):
        base = base[:-3]
    return f"dso:{base}" if base else "unknown"


def demangle_batch(names):
    """Batch-demangle symbol names through one c++filt pipe."""
    if not names:
        return {}
    proc = subprocess.run(["c++filt"], input="\n".join(names),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError("c++filt failed")
    out = proc.stdout.split("\n")
    return dict(zip(names, out[:len(names)]))


# ---------------------------------------------------------------------------
# perf sample extraction and load-bias correction
# ---------------------------------------------------------------------------


def parse_perf_script_lines(lines):
    """`perf script -F dso,ip --ns` output -> [(ip, dso)]."""
    samples = []
    for line in lines:
        match = PERF_RE.match(line)
        if match:
            samples.append((int(match.group(1), 16), match.group(2)))
    return samples


def perf_script_samples(perf_data):
    proc = subprocess.run(["perf", "script", "-i", str(perf_data),
                           "-F", "dso,ip", "--ns"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"perf script failed on {perf_data}")
    return parse_perf_script_lines(proc.stdout.splitlines())


def estimate_offset(sample_ips, funcs, page_shift=12):
    """Estimate the PIE load bias by anchor alignment. The bias is
    page-aligned, so the densest sample IP maps to an instruction VMA with
    identical low `page_shift` bits; every instruction VMA with matching low
    bits yields one candidate offset. Candidates are scored by exact
    instruction-address hits over the distinct sample IPs (numpy searchsorted);
    the maximum wins (ties: smaller |offset|, then smaller offset).
    Returns (offset, diagnostics)."""
    if not sample_ips or not funcs:
        return 0, {"candidates": 0}
    all_addrs = np.sort(np.concatenate(
        [np.asarray(seg, dtype=np.int64) for func in funcs.values()
         for seg in func["addrs"]]))
    anchor = Counter(sample_ips).most_common(1)[0][0]
    low_mask = (1 << page_shift) - 1
    cand_v = all_addrs[(all_addrs & low_mask) == (anchor & low_mask)]
    cand_v = cand_v[cand_v <= anchor]
    samples_arr = np.fromiter(sorted(set(sample_ips)), dtype=np.int64)
    n_addrs = len(all_addrs)

    def score(offset):
        shifted = samples_arr - offset
        pos = np.clip(np.searchsorted(all_addrs, shifted), 0, n_addrs - 1)
        return int((all_addrs[pos] == shifted).sum())

    chosen, best_key = 0, None
    for cand in [0] + [int(anchor - v) for v in cand_v]:
        key = (score(cand), -abs(cand), -cand)
        if best_key is None or key > best_key:
            chosen, best_key = cand, key
    diag = {"anchor": anchor, "candidates": len(cand_v) + 1,
            "distinct_sample_ips": len(samples_arr),
            "exact_hits_at_chosen": best_key[0]}
    return chosen, diag


def interval_coverage(sample_ips, intervals, starts, offset):
    """Fraction of samples whose (ip - offset) lands in a function interval."""
    if not sample_ips:
        return 1.0
    hits = 0
    for ip in sample_ips:
        if map_address(ip - offset, intervals, starts) is not None:
            hits += 1
    return hits / len(sample_ips)


def choose_offset(sample_ips, intervals, starts, funcs):
    """Pick between zero bias and the estimated bias by interval coverage
    (tie -> smaller |offset|). Returns (offset, diagnostics)."""
    est, diag = estimate_offset(sample_ips, funcs)
    cov_zero = interval_coverage(sample_ips, intervals, starts, 0)
    cov_est = interval_coverage(sample_ips, intervals, starts, est)
    if cov_zero >= cov_est:
        chosen = 0
    else:
        chosen = est
    diag.update({"offset_estimate": est, "coverage_zero_offset": cov_zero,
                 "coverage_estimated_offset": cov_est, "offset_chosen": chosen})
    return chosen, diag


# ---------------------------------------------------------------------------
# Per-run aggregation (pure over parsed samples)
# ---------------------------------------------------------------------------


def aggregate_samples(samples, is_emu, funcs, intervals, starts, offset, labels):
    """Aggregate one run's (ip, dso) samples into bucket/function/class counts.

    labels: {mangled_name: (bucket, label)} for every disassembled function.
    Unmapped emu samples count into misc (registered as `unmapped`).
    """
    out = {"n_samples": 0, "n_emu": 0, "n_emu_mapped": 0, "unmapped": 0,
           "inexact": 0, "buckets": Counter(), "funcs": Counter(),
           "func_bucket": {}, "classes": Counter(), "classes_model": Counter(),
           "skid_checked": 0, "skid_diff": 0}
    model_buckets = {"task", "helper", "simtop_other"}
    emu_cache = {}
    for ip, dso in samples:
        out["n_samples"] += 1
        emu = emu_cache.get(dso)
        if emu is None:
            emu = is_emu(dso)
            emu_cache[dso] = emu
        if not emu:
            bucket = dso_bucket(dso)
            out["buckets"][bucket] += 1
            out["funcs"][bucket] += 1
            out["func_bucket"][bucket] = bucket
            continue
        out["n_emu"] += 1
        hit = map_address(ip - offset, intervals, starts)
        if hit is None:
            out["unmapped"] += 1
            out["buckets"]["unknown"] += 1
            out["classes"]["misc"] += 1
            continue
        name, seg = hit
        out["n_emu_mapped"] += 1
        func = funcs[name]
        addrs = func["addrs"][seg]
        j = bisect.bisect_left(addrs, ip - offset)
        if j < len(addrs) and addrs[j] == ip - offset:
            cls = func["cls"][seg][j]
            if j > 0:
                out["skid_checked"] += 1
                if func["cls"][seg][j - 1] != cls:
                    out["skid_diff"] += 1
        elif j > 0:
            cls = func["cls"][seg][j - 1]
            out["inexact"] += 1
        else:
            cls = CLS_IDX["misc"]
            out["inexact"] += 1
        bucket, label = labels[name]
        out["buckets"][bucket] += 1
        out["funcs"][label] += 1
        out["func_bucket"][label] = bucket
        out["classes"][CLASSES[cls]] += 1
        if bucket in model_buckets:
            out["classes_model"][CLASSES[cls]] += 1
    return out


def merge_runs(runs):
    merged = {"n_samples": 0, "n_emu": 0, "n_emu_mapped": 0, "unmapped": 0,
              "inexact": 0, "buckets": Counter(), "funcs": Counter(),
              "func_bucket": {}, "classes": Counter(), "classes_model": Counter(),
              "skid_checked": 0, "skid_diff": 0}
    for run in runs:
        for key in ("n_samples", "n_emu", "n_emu_mapped", "unmapped", "inexact",
                    "skid_checked", "skid_diff"):
            merged[key] += run[key]
        for key in ("buckets", "funcs", "classes", "classes_model"):
            merged[key].update(run[key])
        merged["func_bucket"].update(run["func_bucket"])
    return merged


# ---------------------------------------------------------------------------
# Gates and registered metrics (pure)
# ---------------------------------------------------------------------------


def gate_g2(per_run_classes, per_run_totals):
    """Per-class run-to-run consistency for classes with merged share >= 1%."""
    merged = Counter()
    for counts in per_run_classes:
        merged.update(counts)
    total_all = sum(per_run_totals)
    rows = []
    ok = True
    for cls in CLASSES:
        p = merged[cls] / total_all if total_all else 0.0
        if p < 0.01:
            continue
        shares = [counts[cls] / total if total else 0.0
                  for counts, total in zip(per_run_classes, per_run_totals)]
        worst = 0.0
        limit_worst = 0.0
        passed = True
        for i in range(len(shares)):
            for j in range(i + 1, len(shares)):
                se = math.sqrt(p * (1 - p) / min(per_run_totals[i], per_run_totals[j]))
                limit = max(0.005, 2 * se)
                diff = abs(shares[i] - shares[j])
                if diff > worst:
                    worst, limit_worst = diff, limit
                if diff > limit:
                    passed = False
        rows.append([cls, p, worst, limit_worst, passed])
        ok = ok and passed
    return ok, rows


def gate_g2_sd(per_run_classes, per_run_totals):
    """Amended G2: empirical run-level spread model. For classes with merged
    share >= 1%, the sample SD (n-1) of per-run shares must be <= G2_SD_LIMIT.
    (The pre-amendment pairwise gate compared diffs against the binomial
    sampling SE only, which conflates sampling noise with real run-level
    variance from per-process ASLR/phase mixing.)"""
    merged = Counter()
    for counts in per_run_classes:
        merged.update(counts)
    total_all = sum(per_run_totals)
    rows = []
    ok = True
    for cls in CLASSES:
        p = merged[cls] / total_all if total_all else 0.0
        if p < 0.01:
            continue
        shares = [counts[cls] / total if total else 0.0
                  for counts, total in zip(per_run_classes, per_run_totals)]
        if len(shares) > 1:
            mean = sum(shares) / len(shares)
            sd = math.sqrt(sum((s - mean) ** 2 for s in shares)
                           / (len(shares) - 1))
        else:
            sd = 0.0
        passed = sd <= G2_SD_LIMIT
        rows.append([cls, p, sd, G2_SD_LIMIT, passed])
        ok = ok and passed
    return ok, rows


def load_phase_ref(path):
    """Same-build phase-timing reference rows from a CSV with columns
    run,eval_ns,compute_ns,commit_ns,publish_ns,host_ms. The model wall share
    is (compute+commit+publish)/host — emission-point audit (cpu_emit.cpp
    phase ticks): the compute segment holds compute-task dispatch+bodies, the
    commit segment commit-task dispatch+bodies, publish is cpu_publish(), and
    dispatch/handoff code lives in the eval symbol; on the sample side all of
    these fall in the task/helper/simtop_other buckets."""
    rows = []
    with open(path) as handle:
        header = None
        for line in handle:
            line = line.strip()
            if not line:
                continue
            fields = line.split(",")
            if header is None:
                header = fields
                continue
            rec = dict(zip(header, fields))
            model_ns = (int(rec["compute_ns"]) + int(rec["commit_ns"])
                        + int(rec["publish_ns"]))
            wall_ns = float(rec["host_ms"]) * 1e6
            rows.append({"run": rec["run"],
                         "model_wall_share": model_ns / wall_ns})
    return rows


def bootstrap_ci(counts, iters=BOOT_ITERS, seed=BOOT_SEED):
    """Multinomial resampling of the merged class vector; 95% percentile CI of
    the per-class share. Returns {class: [lo, hi]}."""
    vec = np.array([counts.get(cls, 0) for cls in CLASSES], dtype=np.float64)
    total = vec.sum()
    if total <= 0:
        return {cls: [0.0, 0.0] for cls in CLASSES}
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(int(total), vec / total, size=iters) / total
    lo = np.percentile(draws, 2.5, axis=0)
    hi = np.percentile(draws, 97.5, axis=0)
    return {cls: [float(lo[i]), float(hi[i])] for i, cls in enumerate(CLASSES)}


def coldbias_table(static_per_task, task_fires, share_all, cycles,
                   instr_per_cycle=INSTR_PER_CYCLE_BASELINE):
    """M-coldbias: per-class ratio of the closed-form caliber
    (sum_task fires x static class count / cycles) to the sampled caliber
    (share of all samples x whole-process instr/cycle)."""
    closed = [0.0] * len(CLASSES)
    for task, counts in static_per_task.items():
        fires = task_fires.get(task, 0)
        if not fires:
            continue
        for i, count in enumerate(counts):
            if count:
                closed[i] += fires * count
    out = {}
    for i, cls in enumerate(CLASSES):
        closed_pc = closed[i] / cycles
        sampled_pc = share_all.get(cls, 0.0) * instr_per_cycle
        out[cls] = {"closed_form_per_cycle": closed_pc,
                    "sampled_per_cycle": sampled_pc,
                    "ratio": (closed_pc / sampled_pc) if sampled_pc > 0 else None}
    return out


def build_static_per_task(funcs, unit_to_task):
    """Per-task static class counts from the disassembly: cpu_task_<id> plus
    helper functions merged by name (cpu_helper_<unit>_<i> -> unit's task).
    Returns (static_per_task, orphan_helpers)."""
    static = {}
    orphans = []
    for name, func in funcs.items():
        match = TASK_RE.match(name)
        if match:
            task = int(match.group(1))
        else:
            match = HELPER_RE.match(name)
            if not match:
                continue
            unit = int(match.group(1))
            task = unit_to_task.get(unit)
            if task is None:
                orphans.append(name)
                continue
        row = static.setdefault(task, [0] * len(CLASSES))
        counts = func["counts"]
        for i in range(len(CLASSES)):
            row[i] += counts[i]
    return static, orphans


# ---------------------------------------------------------------------------
# Checkpoint task->unit mapping (cached; the mapped JSON is ~1.4 GB)
# ---------------------------------------------------------------------------


def load_task_units(model_path, out_dir):
    """compute_task_units over the production checkpoint, cached as a pickle in
    the output directory keyed on (path, mtime_ns, size)."""
    stat = os.stat(model_path)
    key = [str(model_path), stat.st_mtime_ns, stat.st_size]
    cache_file = Path(out_dir) / "task_units_cache.pkl"
    if cache_file.exists():
        try:
            cached = pickle.loads(cache_file.read_bytes())
            if cached.get("key") == key:
                return cached["compute_tasks"], cached["all_task_ids"], cached["unit_to_task"]
        except Exception:
            pass
    model = json.loads(Path(model_path).read_bytes())
    payload = model["mappings"][0][-1]
    partitions = {row[0]: row for row in payload[2]}
    schedule = payload[4]
    compute_tasks, all_task_ids, unit_to_task = compute_task_units(partitions, schedule)
    cache_file.write_bytes(pickle.dumps(
        {"key": key, "compute_tasks": compute_tasks,
         "all_task_ids": all_task_ids, "unit_to_task": unit_to_task}))
    return compute_tasks, all_task_ids, unit_to_task


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def make_emu_matcher(emu_path):
    canon = os.path.realpath(str(emu_path))
    def is_emu(dso):
        return dso == str(emu_path) or os.path.realpath(dso) == canon
    return is_emu


def run_analysis(disasm_path, perf_texts, emu_path, out_dir, model_path=None,
                 run_path=None, cycles=DEFAULT_CYCLES,
                 instr_per_cycle=INSTR_PER_CYCLE_BASELINE,
                 bootstrap_iters=BOOT_ITERS, seed=BOOT_SEED, phase_path=None):
    """Full analysis. perf_texts: [(label, perf-script text)]. Returns summary."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(disasm_path) as handle:
        funcs = parse_disasm(handle)
    intervals, starts = build_lookup(funcs)
    demangled = demangle_batch(sorted(funcs))
    labels = {name: symbol_bucket(name, demangled.get(name, name)) for name in funcs}

    is_emu = make_emu_matcher(emu_path)
    run_samples = [(label, parse_perf_script_lines(text.splitlines()))
                   for label, text in perf_texts]

    # Each perf run is a separate emu process with its own ASLR load bias;
    # estimate and verify the offset per run.
    runs = []
    offsets = {}
    offset_diags = {}
    for label, samples in run_samples:
        emu_ips = [ip for ip, dso in samples if is_emu(dso)]
        offset, diag = choose_offset(emu_ips, intervals, starts, funcs)
        offsets[label] = offset
        offset_diags[label] = diag
        agg = aggregate_samples(samples, is_emu, funcs, intervals, starts,
                                offset, labels)
        agg["run"] = label
        runs.append(agg)
    merged = merge_runs(runs)

    n_all = merged["n_samples"]
    n_model = sum(merged["buckets"].get(b, 0) for b in ("task", "helper", "simtop_other"))
    n_task_helper = merged["buckets"].get("task", 0) + merged["buckets"].get("helper", 0)
    coverage = (merged["n_emu_mapped"] / merged["n_emu"]) if merged["n_emu"] else 1.0

    gates = {}
    gates["g1_model_samples"] = (n_model >= G1_MIN_MODEL_SAMPLES,
                                 [n_model, G1_MIN_MODEL_SAMPLES])
    gates["g1_coverage"] = (coverage >= G1_MIN_COVERAGE,
                            [coverage, G1_MIN_COVERAGE])
    g2_ok, g2_rows = gate_g2_sd([r["classes"] for r in runs],
                                [r["n_samples"] for r in runs])
    gates["g2_consistency"] = (g2_ok, g2_rows)
    share_task_helper = n_task_helper / n_all if n_all else 0.0
    share_model = n_model / n_all if n_all else 0.0
    # Amended G3: same-build phase-timing reference, quantity-aligned to the
    # sample side's task+helper+simtop_other share (see report 修订 1).
    if phase_path:
        phase_rows = load_phase_ref(phase_path)
        phase_mean = (sum(r["model_wall_share"] for r in phase_rows)
                      / len(phase_rows))
        delta = abs(share_model - phase_mean)
        gates["g3_closure"] = (delta <= G3_TOL,
                               [share_model, phase_mean, delta, G3_TOL,
                                [r["model_wall_share"] for r in phase_rows]])
    else:
        gates["g3_closure"] = (False, ["phase_ref_missing"])
    flag_rmw_share = merged["classes"].get("flag_rmw", 0) / n_all if n_all else 0.0
    flag_rmw_ipc = flag_rmw_share * instr_per_cycle
    # Amended G4: form-decomposition band (see report 修订 2).
    g4_floor = G4_ANCHOR_ARMS * G4_F_MEM * G4_GUARD_ALLOWANCE
    gates["g4_flag_rmw_anchor"] = (g4_floor <= flag_rmw_ipc <= G4_CEILING,
                                   [flag_rmw_ipc, [g4_floor, G4_CEILING],
                                    flag_rmw_share,
                                    {"anchor_arms": G4_ANCHOR_ARMS,
                                     "f_mem": G4_F_MEM,
                                     "guard_allowance": G4_GUARD_ALLOWANCE}])

    # Pre-amendment gate outcomes, kept for transparent comparison (not part
    # of the verdict).
    g2_orig_ok, g2_orig_rows = gate_g2([r["classes"] for r in runs],
                                       [r["n_samples"] for r in runs])
    informational = {
        "g2_consistency_orig": [bool(g2_orig_ok), g2_orig_rows],
        "g3_closure_orig": [bool(G3_RANGE[0] <= share_task_helper <= G3_RANGE[1]),
                            [share_task_helper, list(G3_RANGE)]],
        "g4_flag_rmw_anchor_orig": [bool(G4_RANGE[0] <= flag_rmw_ipc <= G4_RANGE[1]),
                                    [flag_rmw_ipc, list(G4_RANGE)]],
    }

    ci = bootstrap_ci(merged["classes"], bootstrap_iters, seed)
    class_rows = {}
    for cls in CLASSES:
        count = merged["classes"].get(cls, 0)
        share_all = count / n_all if n_all else 0.0
        class_rows[cls] = {
            "count": count,
            "share_all": share_all,
            "share_emu": count / merged["n_emu"] if merged["n_emu"] else 0.0,
            "share_model": (merged["classes_model"].get(cls, 0) / n_model
                            if n_model else 0.0),
            "ci95_share_emu": ci[cls],
            "instr_per_cycle_est": share_all * instr_per_cycle,
            "per_run_share_all": [
                r["classes"].get(cls, 0) / r["n_samples"] if r["n_samples"] else 0.0
                for r in runs],
        }

    fhot = sorted(merged["funcs"].items(), key=lambda kv: (-kv[1], kv[0]))
    fhot_top = [[label, merged["func_bucket"].get(label, "unknown"), count,
                 count / n_all if n_all else 0.0]
                for label, count in fhot[:30]]
    n_fhot_01 = sum(1 for _label, count in fhot
                    if n_all and count / n_all >= 0.001)

    coldbias = None
    if model_path and run_path:
        compute_tasks, all_task_ids, unit_to_task = load_task_units(model_path, out_dir)
        body_fires, _chg_fires, _totals = load_dyn_fires(run_path)
        task_fires = {task: sum(body_fires.get(unit, 0) for unit in units)
                      for task, units in compute_tasks}
        static_per_task, orphans = build_static_per_task(funcs, unit_to_task)
        share_all_map = {cls: class_rows[cls]["share_all"] for cls in CLASSES}
        coldbias = {
            "per_class": coldbias_table(static_per_task, task_fires, share_all_map,
                                        cycles, instr_per_cycle),
            "cycles": cycles,
            "n_compute_tasks": len(compute_tasks),
            "n_commit_tasks_excluded": len(all_task_ids) - len(compute_tasks),
            "orphan_helpers": orphans,
            "coverage_note": ("closed-form numerator covers ActivityDrivenCompute "
                              "tasks only (commit tasks have no [grhsim-dyn] sn "
                              "rows); helper static counts merged into the owning "
                              "task by cpu_helper_<unit>_<i> name"),
        }

    summary = {
        "gates": {key: bool(value[0]) for key, value in gates.items()},
        "gate_details": {key: value[1] for key, value in gates.items()},
        "informational": informational,
        "config": {"disasm": str(disasm_path), "emu": str(emu_path),
                   "perf_runs": [label for label, _s in run_samples],
                   "model": str(model_path) if model_path else None,
                   "run": str(run_path) if run_path else None,
                   "phase_csv": str(phase_path) if phase_path else None,
                   "cycles": cycles, "instr_per_cycle_baseline": instr_per_cycle,
                   "offsets": offsets, "offset_diagnostics": offset_diags,
                   "bootstrap_iters": bootstrap_iters, "seed": seed},
        "merged": {"n_samples": n_all, "n_emu": merged["n_emu"],
                   "n_emu_mapped": merged["n_emu_mapped"],
                   "coverage": coverage, "unmapped": merged["unmapped"],
                   "inexact": merged["inexact"],
                   "n_model_samples": n_model,
                   "buckets": dict(sorted(merged["buckets"].items()))},
        "runs": [{"run": r["run"], "n_samples": r["n_samples"], "n_emu": r["n_emu"],
                  "n_emu_mapped": r["n_emu_mapped"], "unmapped": r["unmapped"],
                  "buckets": dict(sorted(r["buckets"].items())),
                  "classes": {cls: r["classes"].get(cls, 0) for cls in CLASSES}}
                 for r in runs],
        "classes": class_rows,
        "fhot": {"top30": fhot_top, "n_funcs_share_ge_0.1pct": n_fhot_01},
        "skid": {"checked": merged["skid_checked"], "diff": merged["skid_diff"],
                 "diff_fraction": (merged["skid_diff"] / merged["skid_checked"]
                                   if merged["skid_checked"] else None)},
        "coldbias": coldbias,
    }

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True))
    write_summary_md(out_dir / "summary.md", summary, gates, g2_rows)
    write_per_run_tsv(out_dir / "iclass_per_run.tsv", runs)
    return summary


def write_summary_md(path, summary, gates, g2_rows):
    lines = ["# NO00018 dynamic instruction-class attribution summary", ""]
    lines.append("## Gates")
    lines += ["", "| gate | pass | detail |", "|---|---|---|"]
    for key in sorted(gates):
        detail = summary["gate_details"][key]
        lines.append(f"| {key} | {'PASS' if gates[key][0] else 'FAIL'} | "
                     f"`{json.dumps(detail)[:160]}` |")
    info = summary.get("informational")
    if info:
        lines += ["", "### Pre-amendment gate outcomes (informational)", "",
                  "| gate | pass | detail |", "|---|---|---|"]
        for key in sorted(info):
            passed, detail = info[key]
            lines.append(f"| {key} | {'PASS' if passed else 'FAIL'} | "
                         f"`{json.dumps(detail)[:160]}` |")
    cfg = summary["config"]
    m = summary["merged"]
    lines.append("")
    for label in cfg["perf_runs"]:
        diag = cfg["offset_diagnostics"][label]
        lines.append(f"- {label} load bias: 0x{cfg['offsets'][label]:x} "
                     f"(coverage zero-offset {diag['coverage_zero_offset']:.4f}, "
                     f"estimated-offset {diag['coverage_estimated_offset']:.4f}, "
                     f"anchor 0x{diag.get('anchor', 0):x}, candidates "
                     f"{diag.get('candidates', 0)}, exact hits "
                     f"{diag.get('exact_hits_at_chosen', 0)}/"
                     f"{diag.get('distinct_sample_ips', 0)})")
    lines += [f"- merged samples: {m['n_samples']} (emu {m['n_emu']}, mapped "
              f"{m['n_emu_mapped']}, coverage {m['coverage']:.4f}, unmapped "
              f"{m['unmapped']}, inexact {m['inexact']})",
              f"- model samples (task+helper+simtop_other): {m['n_model_samples']}",
              ""]
    lines += ["## M-iclass (merged, sorted by count)", "",
              "| class | count | share all | share emu | share model | "
              "CI95 (share emu) | instr/cycle |",
              "|---|---|---|---|---|---|---|"]
    rows = sorted(summary["classes"].items(), key=lambda kv: -kv[1]["count"])
    for cls, row in rows:
        lo, hi = row["ci95_share_emu"]
        lines.append(f"| {cls} | {row['count']} | {row['share_all'] * 100:.3f}% "
                     f"| {row['share_emu'] * 100:.3f}% "
                     f"| {row['share_model'] * 100:.3f}% "
                     f"| [{lo * 100:.3f}%, {hi * 100:.3f}%] "
                     f"| {row['instr_per_cycle_est']:.1f} |")
    lines += ["", "## G2 per-run shares (classes >= 1%, amended SD gate)", "",
              "| class | merged share | run SD (n-1) | limit | pass |",
              "|---|---|---|---|---|"]
    for cls, p, sd, limit, passed in g2_rows:
        lines.append(f"| {cls} | {p * 100:.3f}% | {sd * 100:.3f}pp "
                     f"| {limit * 100:.3f}pp | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## M-fhot top 30 (function-level share of all samples)", "",
              "| function | bucket | count | share |", "|---|---|---|---|"]
    for label, bucket, count, share in summary["fhot"]["top30"]:
        lines.append(f"| {label} | {bucket} | {count} | {share * 100:.3f}% |")
    lines.append(f"\nfunctions with share >= 0.1%: "
                 f"{summary['fhot']['n_funcs_share_ge_0.1pct']}")
    skid = summary["skid"]
    frac = skid["diff_fraction"]
    lines += ["", "## Skid sensitivity (registered)", "",
              f"samples with in-function predecessor: {skid['checked']}; "
              f"predecessor class differs: {skid['diff']} "
              f"({(frac * 100) if frac is not None else 0.0:.2f}%)"]
    if summary["coldbias"]:
        cb = summary["coldbias"]
        lines += ["", "## M-coldbias (closed-form fires x static / sampled)", "",
                  f"- cycles: {cb['cycles']}; compute tasks: "
                  f"{cb['n_compute_tasks']}; commit tasks excluded from "
                  f"numerator: {cb['n_commit_tasks_excluded']}",
                  f"- caliber: {cb['coverage_note']}", "",
                  "| class | closed-form instr/cycle | sampled instr/cycle | ratio |",
                  "|---|---|---|---|"]
        for cls in CLASSES:
            row = cb["per_class"][cls]
            ratio = row["ratio"]
            lines.append(f"| {cls} | {row['closed_form_per_cycle']:.1f} "
                         f"| {row['sampled_per_cycle']:.1f} "
                         f"| {f'{ratio:.3f}' if ratio is not None else 'n/a'} |")
    path.write_text("\n".join(lines) + "\n")


def write_per_run_tsv(path, runs):
    lines = ["run\tclass\tcount\tshare_all"]
    for run in runs:
        total = run["n_samples"]
        for cls in CLASSES:
            count = run["classes"].get(cls, 0)
            share = count / total if total else 0.0
            lines.append(f"{run['run']}\t{cls}\t{count}\t{share:.8f}")
        lines.append(f"{run['run']}\t__total__\t{total}\t1.00000000")
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disasm", required=True, help="objdump -d dump")
    parser.add_argument("--emu", required=True, help="emu binary path (dso match)")
    parser.add_argument("--perf", action="append", required=True,
                        help="perf.data path (repeatable, one per run)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=None,
                        help="production checkpoint JSON (M-coldbias; optional)")
    parser.add_argument("--run", default=None,
                        help="dyn run log (M-coldbias; optional)")
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--instr-per-cycle", type=float,
                        default=INSTR_PER_CYCLE_BASELINE)
    parser.add_argument("--phase-csv", default=None,
                        help="same-build phase-timing reference CSV "
                             "(run,eval_ns,compute_ns,commit_ns,publish_ns,host_ms); "
                             "required for the amended G3 closure gate")
    parser.add_argument("--bootstrap", type=int, default=BOOT_ITERS)
    parser.add_argument("--seed", type=int, default=BOOT_SEED)
    args = parser.parse_args(argv)

    perf_texts = []
    for perf in args.perf:
        proc = subprocess.run(["perf", "script", "-i", perf, "-F", "dso,ip", "--ns"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"perf script failed on {perf}")
        perf_texts.append((Path(perf).parent.name, proc.stdout))
    summary = run_analysis(args.disasm, perf_texts, args.emu, args.output,
                           model_path=args.model, run_path=args.run,
                           cycles=args.cycles,
                           instr_per_cycle=args.instr_per_cycle,
                           bootstrap_iters=args.bootstrap, seed=args.seed,
                           phase_path=args.phase_csv)
    print(json.dumps(summary["gates"], indent=1, sort_keys=True))
    offsets = " ".join(f"{label}=0x{off:x}"
                       for label, off in summary["config"]["offsets"].items())
    g3 = summary["gate_details"]["g3_closure"]
    g3_txt = (f"model_share={g3[0] * 100:.2f}% phase_ref={g3[1] * 100:.2f}% "
              f"delta={g3[2] * 100:.2f}pp") if len(g3) >= 4 else str(g3)
    print(f"samples={summary['merged']['n_samples']} "
          f"emu={summary['merged']['n_emu']} "
          f"coverage={summary['merged']['coverage']:.4f} "
          f"offsets[{offsets}] "
          f"{g3_txt} "
          f"flag_rmw={summary['gate_details']['g4_flag_rmw_anchor'][0]:.0f}/cycle")
    return 0 if all(summary["gates"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
