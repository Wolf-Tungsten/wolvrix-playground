"""Correlate two generated change sites with byte-checked instructions in the timing ELFs."""
from collections import Counter
import gzip
from pathlib import Path
import re
import subprocess
import sys

from machine import BINS, DEFAULT, LLVM, ROOT, Elf, phase, save

DEST = ROOT / "build/armor-xs-site-pgo-v1"
SITES = [(21, "968278", "value_bool_slots_[386506] != next_value"),
         (90, "1886767", "state_logic_storage_.u8_slots_25810 != next_value")]


def main(tag):
    if tag not in ("baseline", "both5"):
        raise ValueError("these excerpts compare baseline and both5")
    baseline = tag == "baseline"
    model = (DEFAULT / "pgo" if baseline else DEST/"native") / "model"
    build = (DEFAULT/"pgo" if baseline else DEST/tag) / "build"
    elf = Elf(BINS["gr_pgo"] if baseline else build/"emu")
    out = DEST/"elf"/tag
    out.mkdir(exist_ok=True,parents=True)
    selected = set()
    if not baseline:
        with gzip.open(build/"grhsim-sites.tsv.gz","rt") as src:
            next(src)
            for row in src:
                fields = row.split()
                if len(fields) == 2:
                    shard = fields[0]
                    continue
                kind, number, visits, changes = fields
                n, c = int(visits), int(changes)
                if kind == "SPARSE" and n >= 25000 and c*20 <= n or kind == "EAGER" and n >= 1000 and 5*c >= n:
                    selected.add((shard, kind, number))
    sections = Counter()
    for name, (_,size) in elf.funcs.items():
        sections[phase(name)] += size
    save(out/"size.json",dict(text=elf.sec[".text"][2],rodata=elf.sec[".rodata"][2],function_bytes=sections))
    for batch, site, needle in SITES:
        name = f"grhsim_SimTop_sched_{batch}.cpp"
        source = out/name
        original = (model/name).read_bytes()
        if baseline:
            header = b""
        else:
            header = f'#include "{source.with_suffix(".sites.h").name}"\n'.encode()
            with source.with_suffix(".sites.h").open("w") as f:
                for shard,kind,number in sorted(selected):
                    if shard == name:
                        print(f"#define GRHSIM_{kind}_{number} 1", file=f)
        source.write_bytes(header + original)
        body = source.read_text().splitlines()
        line, = [ln for ln,t in enumerate(body,1) if needle in t]
        lo = line-1
        hi = next(ln for ln in range(line,len(body)) if body[ln].strip() == "}" and
                  (baseline or ln > line+5)) + 1
        obj = source.with_suffix(".o")
        flags = ["-std=c++20","-O3","-march=native",f"-fprofile-use={build/'grhsim.profdata'}",
                 "-mllvm","-x86-cmov-converter-force-mem-operand=false","-gline-tables-only"]
        subprocess.run([LLVM/"clang++",*flags,"-I",model,"-c",name,"-o",obj],cwd=out,check=True)
        fun = f"GrhSIM_SimTop::eval_{'compute' if batch==21 else 'commit'}_batch_{batch}()"
        start, size = elf.funcs[fun]
        # Only attribute a line if the function length and corresponding instruction bytes match.
        nm = subprocess.check_output([LLVM/"llvm-nm","-SC",obj],text=True)
        sizes = {s.split(None,3)[3]:int(s.split()[1],16) for s in nm.splitlines() if re.match(r"^[0-9a-f]+ [0-9a-f]+ [Tt] ",s)}
        if size != sizes[fun]:
            raise ValueError(f"diagnostic code size mismatch: {fun} {size} vs {sizes[fun]}")
        data = subprocess.check_output([LLVM/"llvm-objdump","-d","-l","-C",obj],text=True)
        hits = []
        base = current = None
        for raw in data.splitlines():
            if m := re.match(r"^([0-9a-f]+) <(.*)>:$",raw):
                base = int(m[1],16) if m[2] == fun else None
                current = None
            elif base is not None and raw.startswith(";"):
                m = re.search(re.escape(name)+r":(\d+)",raw)
                current = int(m[1]) if m else None
            elif base is not None and current and lo <= current <= hi:
                m = re.match(r"^\s*([0-9a-f]+): ((?:[0-9a-f]{2} )*[0-9a-f]{2})\s+(.*)$",raw)
                if m:
                    pc = start + int(m[1],16) - base
                    encoding = bytes.fromhex(m[2])
                    if elf.code(pc,len(encoding)) == encoding:
                        # Decode at the final VA so branch targets are shown in the timing binary.
                        hits.append((pc,len(encoding),current))
        if not hits:
            raise ValueError(f"no verified instructions at {name}:{line}")
        with (out/f"site-{site}.asm").open("w") as f:
            print(f"{elf.path}\n{fun} ({size} bytes)\n{name}:{line}, byte-verified ELF instructions",file=f)
            for pc,length,ln in hits:
                dis = subprocess.check_output([LLVM/"llvm-objdump","-d","--no-show-raw-insn",
                    f"--start-address={pc}", f"--stop-address={pc+length}",elf.path],text=True)
                print(f"line {ln}   {dis.splitlines()[-1].strip()}",file=f)


if __name__ == "__main__":
    main(sys.argv[1])
