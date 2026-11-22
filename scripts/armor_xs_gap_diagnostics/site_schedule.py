"""Trace ROB enqueue lanes across passes and weight small schedule changes on both workloads."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import struct

from diagnostics import DEFAULT, OUT, ROOT, save
from source_categories import read_lcov

DEST = ROOT / "build/armor-xs-site-pgo-v1"
STAGES = OUT / "audit/stages"


def trace_rob():
    values = {}
    with (STAGES / "after-clone.values.tsv").open() as f:
        for row in f:
            if "uopCanEnqSeq_" in row and (m := re.search(r'\$rob\$uopCanEnqSeq_([0-7])_67"$',row.rstrip())):
                fields = row.split("\t")
                values[int(fields[0])] = (int(m[1]), int(fields[4]))
    assert len(values) == 8
    users = defaultdict(set)
    # Filter the input column exactly, including dependencies in the middle of an operand list.
    pattern = re.compile(r"(?:^|,)(" + "|".join(map(str,values)) + r")(?=,|$)")
    with (STAGES / "after-clone.ops.tsv").open() as f:
        next(f)
        for row in f:
            fields = row.rstrip("\n").rsplit("\t",2)
            for m in pattern.finditer(fields[1]):
                users[int(m[1])].add(int(fields[0].split("\t",1)[0]))
    ops = {op for _,op in values.values()} | set().union(*users.values())
    def owners(path, targets, nodes):
        data = path.read_bytes()
        words = memoryview(data).cast("I")
        # Look up candidate word offsets once, retain only matches in membership arrays.
        hits = []
        for target in targets:
            key = struct.pack("<I",target)
            pos = 0
            while (pos := data.find(key,pos)) >= 0:
                if pos % 4 == 0: hits.append((pos//4,target))
                pos += 1
        hits.sort()
        j, p = 0, 1
        result = {}
        for i in range(words[0]):
            if nodes: p += 1
            end = p+1+words[p]
            while j < len(hits) and hits[j][0] < end:
                off, target = hits[j]
                if off > p:
                    if target in result: raise ValueError(f"duplicate member {target} in {path}")
                    result[target] = (i, words[p])
                j += 1
            p = end
            if nodes: p += 1+words[p]
        assert p == len(words) and set(result) == targets, path
        return result

    states = []
    for label in ["nodes-created","nodes-declared-split","nodes-final"]:
        node = owners(STAGES/(label+".nodes.bin"), ops, True)
        states.append((label,node))
    nodes = {n for n,_ in node.values()}
    groups = sorted(STAGES.glob("clusters-[0-9]*.groups.bin"), key=lambda p: (int(p.name.split("-")[1]),
                    ["out1","in1","siblings"].index(p.name.split("-")[2].split(".")[0])))
    for path in [STAGES/"clusters-before-coarsen.groups.bin",*groups,STAGES/"clusters-after-coarsen-topo.groups.bin",
                 STAGES/"final-compute-members.groups.bin"]:
        group = owners(path,nodes,False)
        states.append((path.name.split(".")[0],{op:group[n] for op,(n,_) in node.items()}))
    result = {}
    for value,(lane,producer) in sorted(values.items(),key=lambda v:v[1]):
        reads = sorted(users[value])
        result[lane] = dict(value=value,producer=producer,users=reads,stages=[
            dict(stage=name,producer=groups[producer],users=[groups[op] for op in reads])
            for name,groups in states])
    save(DEST/"rob.json",result)


def scenarios():
    audit = {}
    with (DEST/"scenarios.tsv").open() as f:
        next(f)
        for row in f:
            v, *data = map(int,row.split())
            audit[v] = data
    ids = [int(row.split()[3]) for row in (OUT/"sparse-sites.tsv").read_text().splitlines()]
    point = OUT/"sitewatch/gr_pgo"
    counts = {wl:list(struct.iter_unpack("<QQ",(point/name).read_bytes()))
              for wl,name in (("coremark","sites.bin"),("microbench","micro.bin"))}
    assert all(len(r)==len(ids) for r in counts.values())
    totals = {wl:defaultdict(Counter) for wl in counts}
    for i,v in enumerate(ids):
        if v not in audit: continue
        readers,needed,order,old,clones,edges,boundaries = audit[v]
        quiet = counts["coremark"][i][0] >= 25000 and counts["coremark"][i][1]*20 <= counts["coremark"][i][0]
        categories=[]
        if readers == 1 and order and not old:
            categories += [f"single cap {cap}" for cap in (160,176,192,216) if needed<=cap]
            categories += [f"single cap {cap} existing inputs" for cap in (160,176,192,216)
                           if needed<=cap and not edges]
        if clones:
            categories.append("two-reader cheap op")
            if not edges: categories.append("two-reader existing inputs")
            if not edges and needed <= 161: categories.append("two-reader existing inputs <=161")
            if edges and not boundaries: categories.append("two-reader needs edges only")
        for category in categories:
            for wl, rows in counts.items():
                n,c = rows[i]
                totals[wl][category].update(sites=1,checks=n,changes=c,sparse_checks=n if quiet else 0,
                                             missing_edges=edges, new_input_values=boundaries,
                                             visits_times_missing_edges=n*edges)
    save(DEST/"scenarios.json", totals)


def standalone(wl):
    counts=defaultdict(Counter)
    details={}
    physical={}
    active=False
    physical_index=0
    for line in (DEFAULT/"pgo/model/grhsim_SimTop.hpp").read_text().splitlines():
        if "struct state_logic_storage_t {" in line:
            active=True
        elif active and line.strip()=="};":
            break
        elif active and line.endswith(";"):
            physical[line.rsplit(" ",1)[-1][:-1]]=physical_index
            physical_index+=1
    adjacency=defaultdict(Counter)
    for src,lines,_ in read_lcov(OUT/"coverage/gr_pgo"/wl/"model.lcov"):
        path=Path(src)
        if "_sched_" not in path.name: continue
        phase=False
        scopes=[]
        writes=[]
        rhs=""
        with path.open() as f:
            for i,line in enumerate(f,1):
                if line.startswith("void "):
                    phase = "::eval_commit_batch_" in line
                    scopes=[]
                if not phase: continue
                t=line.strip()
                if not t or t.startswith(("//","#")):continue
                if t.startswith("const auto next_value = "):rhs=t
                if "!= next_value" in t and "data" not in scopes and "enable" not in scopes:
                    if "state_logic_storage_" not in t: kind="other storage"
                    elif re.fullmatch(r"const auto next_value = static_cast<[^>]+>\(value_\w+_slots_\[\d+\]\);",rhs):
                        kind="scalar slot"
                    elif "state_logic_storage_" in rhs: kind="reads state"
                    elif "_C(" in rhs or re.search(r"\((?:true|false)\)",rhs): kind="literal or folded expression"
                    else: kind="other RHS"
                    counts[kind].update(sites=1,visits=lines.get(i,0))
                    details.setdefault(kind,(path.name,i,rhs[:220],t))
                if "!= next_value" in t:
                    state=re.search(r"state_logic_storage_\.(\w+_slots_\d+) != next_value",t)
                    slot=re.fullmatch(r"const auto next_value = static_cast<[^>]+>\(value_(\w+)_slots_\[(\d+)\]\);",rhs)
                    lane=(slot[1],int(slot[2]),physical[state[1]]) if state and slot and state[1] in physical else None
                    writes.append((lane, "data" not in scopes and "enable" not in scopes, lines.get(i,0)))
                kind=("data" if "std::memcmp(" in t and "disabled_commit_guards" not in t else
                      "enable" if re.match(r"^if \(unlikely\(\(value_bool_slots_\[\d+\]\) != 0\)\) \{",t) else "other")
                net=t.count("{")-t.count("}")
                if net>0:scopes.extend([kind]*net)
                elif net<0:del scopes[net:]
        for i,(lane,standalone_site,n) in enumerate(writes):
            if not standalone_site or lane is None:continue
            reason=0
            for step in (-1,1):
                if not 0<=i+step<len(writes):continue
                neighbor=writes[i+step][0]
                if neighbor is None or neighbor[0]!=lane[0]:continue
                reason=max(reason,1)
                if neighbor[1]!=lane[1]+step:continue
                reason=max(reason,2)
                if neighbor[2]==lane[2]+step:reason=3
            key=("different type or no adjacent scalar snapshot", "next slots not consecutive",
                 "physical fields not consecutive","adjacent layout; inspect guard or run boundary")[reason]
            adjacency[key].update(sites=1,visits=n)
    save(DEST/f"standalone-{wl}.json",dict(counts=counts,examples=details,adjacent_compare=adjacency))


if __name__ == "__main__":
    trace_rob()
    scenarios()
    for workload in ("coremark","microbench"):
        standalone(workload)
