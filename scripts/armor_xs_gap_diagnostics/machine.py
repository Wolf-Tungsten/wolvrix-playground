"""Read model symbol sizes and the actual profiled instructions from the timed executables."""
from bisect import bisect_right
from collections import Counter, defaultdict
import ctypes as ct
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from armor_xs_current_gap import BINS, DEFAULT, LLVM, MATCHED, OUT
from grhsim_single_baseline import save


def phase(sym):
    if sym.startswith("GrhSIM_SimTop::eval_compute_batch_"):
        return "compute"
    if sym.startswith("GrhSIM_SimTop::eval_commit_batch_"):
        return "commit"
    if sym.startswith("SSimTop::subStep"):
        return "subStep"
    if sym.startswith(("SSimTop::", "GrhSIM_SimTop::", "grhsim_")):
        return "model-other"
    return "harness"


class Elf:
    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        assert self.data[:6] == b"\x7fELF\x02\x01"
        off = struct.unpack_from("<Q", self.data, 40)[0]
        sz, count, strings = struct.unpack_from("<HHH", self.data, 58)
        sections = [struct.unpack_from("<IIQQQQIIQQ", self.data, off + i*sz) for i in range(count)]
        tab = self.data[sections[strings][4]:sections[strings][4]+sections[strings][5]]
        self.sec = {tab[s[0]:tab.index(b"\0", s[0])].decode(): (s[3], s[4], s[5]) for s in sections}
        entries = subprocess.check_output([LLVM/"llvm-nm", "-S", "-C", "--defined-only", path], text=True)
        self.funcs = {}
        for line in entries.splitlines():
            m = re.match(r"([0-9a-f]+) ([0-9a-f]+) [tTwW] (.+)", line)
            if m and int(m[2],16):
                self.funcs[m[3]] = (int(m[1],16), int(m[2],16))
        self.starts = sorted((addr, name) for name, (addr, _) in self.funcs.items())
        self.addrs = [v for v, _ in self.starts]

    def code(self, addr, size):
        va, off, _ = self.sec[".text"]
        return self.data[addr-va+off:addr-va+off+size]

    def function(self, addr):
        i = bisect_right(self.addrs, addr)-1
        if i >= 0:
            start, name = self.starts[i]
            if addr < start + self.funcs[name][1]:
                return name
        return None


class Disassembler:
    def __init__(self):
        self.lib = ct.CDLL("/lib/x86_64-linux-gnu/libLLVM.so.20.1")
        for name in ("TargetInfo","Target","TargetMC","Disassembler","AsmPrinter"):
            getattr(self.lib,"LLVMInitializeX86"+name)()
        self.lib.LLVMCreateDisasmCPUFeatures.argtypes = [ct.c_char_p]*3 + [ct.c_void_p,ct.c_int,ct.c_void_p,ct.c_void_p]
        self.lib.LLVMCreateDisasmCPUFeatures.restype = ct.c_void_p
        self.ctx = self.lib.LLVMCreateDisasmCPUFeatures(b"x86_64-pc-linux-gnu",b"znver4",b"",None,0,None,None)
        assert self.ctx
        self.lib.LLVMDisasmInstruction.argtypes = [ct.c_void_p,ct.c_char_p,ct.c_uint64,ct.c_uint64,ct.c_char_p,ct.c_size_t]
        self.lib.LLVMDisasmInstruction.restype = ct.c_size_t
        self.buf = ct.create_string_buffer(350)

    def get(self, data, addr):
        n = self.lib.LLVMDisasmInstruction(self.ctx,data,len(data),addr,self.buf,len(self.buf))
        return self.buf.value.decode().strip() if n else "invalid"


def asmclass(s):
    m = s.split()[0]
    if m.startswith("j"):
        return "jump" if m.startswith("jmp") else "jcc"
    if m.startswith("cmov"):
        return "cmov"
    if m.startswith("set"):
        return "setcc"
    if m.startswith(("cmp","test","bt")):
        return "compare"
    if m.startswith(("mov","vmov")):
        if "(" in s:
            # LLVM AT&T uses the source operand first.
            return "store" if s.rstrip().endswith(")") else "load"
        return "register move"
    if m.startswith(("call","ret")):
        return "call/return"
    return "other"


def hotset(counter, frac):
    total = sum(counter.values())
    cum = 0
    for i, n in enumerate(sorted(counter.values(), reverse=True), 1):
        cum += n
        if cum >= frac*total:
            return i
    return 0


def source_dir(label):
    return (MATCHED / "model" if label.startswith("gs") else
            DEFAULT / ("ordinary" if label == "gr_off" else "pgo") / "model")


def size_info(label, elf):
    model = source_dir(label)
    files = [p for p in model.iterdir() if p.suffix in (".h",".hpp",".cpp")]
    count, size = Counter(), Counter()
    for name, (start, nb) in elf.funcs.items():
        key = phase(name)
        count[key] += 1
        size[key] += nb
    folder = OUT / "machine" / label
    folder.mkdir(exist_ok=True,parents=True)
    gs = label.startswith("gs")
    hdr, ty = ("SimTop.h","SSimTop") if gs else ("grhsim_SimTop.hpp","GrhSIM_SimTop")
    src = f'#include "{hdr}"\n#include <cstdio>\nint main(){{std::printf("%zu\\n",sizeof({ty}));}}'
    check = folder / "size-of-model"
    subprocess.run([LLVM/"clang++","-std=c++20","-march=native","-w","-x","c++","-","-I",model,"-o",check],
                   input=src,text=True,check=True)
    result = dict(elf=len(elf.data), sections={s:v[2] for s,v in elf.sec.items()},
                  model_object=int(subprocess.check_output([check])),functions=count,function_bytes=size,
                  source_bytes=sum(p.stat().st_size for p in files),source_files=len(files),
                  cpp_files=sum(p.suffix==".cpp" for p in files))
    save(folder/"sizes.json",result)


def sample(label, wl, elf):
    profiles = sorted((OUT/"measurement").glob("session-*/"+wl+"/"+label+"/runs/profile-*/sample.json"))
    if not profiles:
        return
    root = profiles[-1].parent
    dest = OUT/"machine"/label/wl
    dest.mkdir(exist_ok=True, parents=True)
    exe = root.parent / "runtime/bin/emu"
    first = next(l for l in (root/"maps").read_text().splitlines() if l.endswith(" "+str(exe)))
    base = int(first.split("-")[0],16)-int(first.split()[2],16)
    totals, page, syms, ops = (defaultdict(Counter) for _ in range(4))
    ips = defaultdict(Counter)
    cmd = ["perf","script","-i",root/"perf.data","-F","event,ip,sym,dso"]
    proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,text=True)
    for line in proc.stdout:
        m = re.match(r"\s*([^/]+)/[^:]+:\s+([0-9a-f]+)\s+(.*?) \((.*)\)\s*$",line)
        if not m:
            if line.strip(): raise ValueError(line)
            continue
        ev, ip, sym, dso = m.groups()
        addr = int(ip,16)-base
        model = dso == str(exe)
        key = phase(sym) if model else ("NEMU" if "nemu.so" in dso else "unresolved" if dso=="[unknown]" else "lib/other")
        totals[ev][key] += 1
        if model and key in ("compute","commit","subStep","model-other"):
            page[ev][addr>>12] += 1
            syms[ev][sym] += 1
            ips[addr][ev] += 1
    if proc.wait(): raise RuntimeError(cmd)
    mc = Disassembler()
    for addr, freq in ips.items():
        key = asmclass(mc.get(elf.code(addr,16),addr))
        for ev, n in freq.items():
            ops[ev][key] += n
    best = sorted(ips, key=lambda a:ips[a]["cycles"],reverse=True)[:30]
    spots = [dict(addr=hex(a),sym=elf.function(a),asm=mc.get(elf.code(a,16),a),samples=ips[a]) for a in best]
    save(dest/"summary.json",dict(base=hex(base),phase=totals,instructions_at_sample=ops,
         pages90={k:hotset(v,.9) for k,v in page.items()},pages50={k:hotset(v,.5) for k,v in page.items()},
         model_functions90={k:hotset(v,.9) for k,v in syms.items()},top_functions=syms["cycles"].most_common(12),spots=spots))
    with (dest/"model-ips.tsv").open("w") as f:
        for a, counts in ips.items():
            f.write(f"{a:x}\t{counts['cycles']}\t{counts['instructions']}\t{counts['branch-misses']}\n")


if __name__ == "__main__":
    for label in sys.argv[1:] or BINS:
        elf=Elf(BINS[label])
        if not (OUT/"machine"/label/"sizes.json").exists():
            size_info(label,elf)
        for wl in ("coremark","microbench"):
            if not (OUT/"machine"/label/wl/"model-ips.tsv").exists(): sample(label,wl,elf)
