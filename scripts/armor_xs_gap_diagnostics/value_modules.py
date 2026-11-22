"""Map timed ELF samples to the result of each sampled C++ value expression and its RTL module."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

from attribute import gs_kind, gr_kind
from machine import BINS, Disassembler, Elf, OUT, ROOT, phase, save, source_dir, asmclass
from source_categories import GsimClassifier, bucket
from armor_dispatch_ibs import symbolize

DEST = ROOT / "build/armor-xs-site-pgo-v1/modules"
WORKLOADS = ("coremark", "microbench")
FIR = ROOT.parent / "wolvrix-playground-new-xiangshan/build/xs/parent-default-single-20261114-v1/rtl/rtl/SimTop.fir"
MODULE = re.compile(rb"^  (?:public )?(?:ext)?module (\w+) :")
INSTANCE = re.compile(rb"^ +inst (\w+) of (\w+)")
DECLARATION = re.compile(rb"^ +(?:input|output|wire|node|reg|regreset|mem) ([\w$]+)\b")
GS_NAME = re.compile(r"[\w$]+(?:__DOT__[\w$]+)+")
GR_LOCAL = re.compile(r"^const [\w:<>]+ grhsim_v(\d+)_\d+ =")
GR_VALUE = re.compile(r"\[value_id=(\d+):")
EVENTS = ("cycles", "instructions")


def fir_hierarchy():
    hierarchy = defaultdict(dict)
    signals = defaultdict(set)
    module = None
    with FIR.open("rb") as src:
        for line in src:
            if match := MODULE.match(line):
                module = match[1].decode()
            elif (b"inst " in line and module and (match := INSTANCE.match(line))):
                hierarchy[module][match[1].decode()] = match[2].decode()
            elif module and (match := DECLARATION.match(line)):
                signals[module].add(match[1].decode())
    return hierarchy, signals


def signal_owner(signal, tree):
    hierarchy, signals = tree
    module = "SimTop"
    for part in signal.split("__DOT__")[:-1]:
        child = hierarchy[module].get(part)
        if child:
            module = child
        elif part in signals[module]:
            # FIRRTL bundle fields and vector indices stay in their declaring module.
            return module
        else:
            return None
    return module


def value_lines(label, wanted):
    gs = label.startswith("gs")
    hierarchy = fir_hierarchy() if gs else None
    regs = set((OUT / "gs-registers.txt").read_text().splitlines()) if gs else set()
    result = {}
    for name, lines in wanted.items():
        g = GsimClassifier(regs)
        ph = value = None
        with (source_dir(label) / name).open() as stream:
            for no, raw in enumerate(stream, 1):
                if raw.startswith("void "):
                    ph = "commit" if "::eval_commit_batch_" in raw else "compute" if "::eval_compute_batch_" in raw or "::subStep" in raw else None
                    value = None
                if gs and ("$old$" in raw and " = " in raw or "bool cond_" in raw):
                    g.subject(raw.strip())
                if not gs:
                    if "// value " in raw:
                        m = GR_VALUE.search(raw)
                        value = int(m[1]) if m else None
                    elif "// op " in raw or raw.strip() == "}":
                        value = None
                if not ph or no not in lines:
                    continue
                t = raw.strip()
                cat = gs_kind(t,g) if gs else ph + "|" + gr_kind(t,ph)
                if bucket("gsim" if gs else "grhsim", cat) != "value computation":
                    continue
                owner = None
                if gs:
                    # Assignment destination, or a condition whose named operands agree.
                    # Never infer an owner from another line (a group can span many modules).
                    expr = t.split(" = ", 1)[0] if " = " in t else t
                    paths = set()
                    for signal in GS_NAME.findall(expr):
                        paths.add(signal_owner(signal,hierarchy))
                    if len(paths) == 1:
                        owner = paths.pop()
                elif m := GR_LOCAL.match(t):
                    owner = int(m[1])
                elif "next_value = " in t or "next_words = " in t:
                    owner = value
                result[name,no] = (owner, " = " in t)
    if not gs:
        ids = {v for v,_ in result.values() if v is not None}
        defs = {}
        with (OUT / "audit/stages/after-clone.values.tsv").open() as src:
            next(src)
            for row in src:
                first, _, rest = row.partition("\t")
                if (i := int(first)) in ids:
                    defs[i] = int(rest.split("\t")[3])
        modules = dict.fromkeys(defs.values())
        with (OUT / "audit/stages/after-clone.ops.tsv").open() as src:
            next(src)
            for row in src:
                first, _, rest = row.partition("\t")
                if (i := int(first)) in modules:
                    filename = rest.split("\t",5)[3].strip('"')
                    if filename.endswith(".sv"):
                        modules[i] = Path(filename).stem
        return {line:(modules.get(defs.get(v)),assigned) for line,(v,assigned) in result.items()}
    return result


def main(label):
    dest = DEST / label
    dest.mkdir(parents=True, exist_ok=True)
    elf = Elf(BINS[label])
    debug = Elf(next((OUT / "lines" / label / "work").glob("*-compile/emu")))
    ips = defaultdict(lambda: Counter())
    totals = {}
    for wl in WORKLOADS:
        folder = OUT / "machine" / label / wl
        mix = json.loads((folder / "attribution.json").read_text())
        totals[wl] = mix
        for line in (folder / "model-ips.tsv").read_text().splitlines():
            ip, cycles, instructions, _ = line.split()
            p = int(ip,16)
            for ev, n in zip(EVENTS, (cycles, instructions)):
                if int(n):
                    ips[p][wl,ev] = int(n)
    mc = Disassembler()
    valid = {}
    opclass = {}
    for p in ips:
        sym = elf.function(p)
        if sym not in debug.funcs or elf.funcs[sym][1] != debug.funcs[sym][1]:
            continue
        q = debug.funcs[sym][0] + p - elf.funcs[sym][0]
        data = elf.code(p,16)
        size = mc.lib.LLVMDisasmInstruction(mc.ctx,data,len(data),p,mc.buf,len(mc.buf))
        if size and data[:size] == debug.code(q,size):
            valid[p] = q
            opclass[p] = asmclass(mc.buf.value.decode().strip())
    located = symbolize(debug.path, sorted(set(valid.values())), dest)
    wanted = defaultdict(set)
    where = {}
    for p,q in valid.items():
        path,ln,*_ = located.get(q,("",0))
        name = Path(path).name
        if ln and re.fullmatch(r"(?:SimTop|grhsim_SimTop_sched_)\d+\.cpp", name):
            where[p] = name,ln
            wanted[name].add(ln)
    lines = value_lines(label,wanted)
    freq = defaultdict(Counter)
    opmix = defaultdict(Counter)
    assignment = defaultdict(Counter)
    hot = defaultdict(Counter)
    for p, line in where.items():
        if line not in lines:
            continue
        owner, assigned = lines[line]
        module = owner or "(unresolved owner)"
        for (wl,ev), n in ips[p].items():
            freq[wl,ev][module] += n
            if assigned and owner:
                assignment[wl,ev][module] += n
            opmix[wl,ev,module][opclass[p]] += n
            if ev == "cycles": hot[wl,module][(p,line)] += n
    metrics=json.loads((OUT/"metrics.json").read_text())
    out = {}
    for wl in WORKLOADS:
        out[wl] = {}
        for ev in EVENTS:
            expected = totals[wl]["buckets"][ev]["value computation"]
            assert sum(freq[wl,ev].values()) == expected, (label,wl,ev,sum(freq[wl,ev].values()),expected)
            scale = metrics[wl]["per_guest"][label][ev] / totals[wl]["total"][ev]
            out[wl][ev] = {mod:{"samples":n, "per_guest":n*scale, "assignment_per_guest":assignment[wl,ev][mod]*scale,
                                 "opcodes":opmix[wl,ev,mod],
                                 "example":[[hex(p),line,mc.get(elf.code(p,16),p),count] for (p,line),count in hot[wl,mod].most_common(1)]}
                           for mod,n in freq[wl,ev].most_common()}
    save(dest/"results.json",out)

if __name__ == "__main__":
    main(sys.argv[1])
