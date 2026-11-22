"""Validate native training counts against independent C++ counters and line coverage."""
from collections import Counter, defaultdict
import gzip
import re
import struct
from pathlib import Path

from diagnostics import OUT, ROOT, save
from source_categories import read_lcov

DEST = ROOT / "build/armor-xs-site-pgo-v1"


def main():
    profile = {}
    with gzip.open(DEST/"both05/build/grhsim-sites.tsv.gz","rt") as src:
        next(src)
        for line in src:
            fields = line.split()
            if len(fields) == 2:
                shard = fields[0]
            else:
                kind, number, visits, changes = fields
                profile[kind,shard,int(number)] = int(visits),int(changes)
    result = defaultdict(Counter)
    def check(key, train, observed):
        summary = result[key[0]]
        summary["matched_sites"] += 1
        summary["mismatches"] += int(train != observed)
    site_dir = OUT/"sitewatch/gr_pgo"
    rows = [list(struct.iter_unpack("<QQ",(site_dir/file).read_bytes())) for file in ("sites.bin","micro.bin")]
    quiet = Counter()
    with (OUT/"sparse-sites.tsv").open() as stream:
        for line in stream:
            idx, shard, _, value, _ = line.split()
            key = ("SPARSE",shard,int(value))
            if key not in profile: continue
            n,c = profile[key]
            check(key,(n,c),rows[0][int(idx)])
            if n>=25000 and 200*c<=n:
                m,h = rows[1][int(idx)]
                quiet.update(sites=1,visits=m,changes=h)

    write_ids = {}
    with (OUT/"audit/stages/after-clone.ops.tsv").open() as stream:
        for row in stream:
            if "\tkRegisterWritePort\t" in row:
                index, _, name, _ = row.split("\t",3)
                write_ids[name.strip('"')] = int(index)
    commit_re = re.compile(r"// op (\S+) \[kRegisterWritePort\]")
    hot = Counter()
    seen = set()
    for wl in ("coremark", "microbench"):
        for file,lines,_ in read_lcov(OUT/"coverage/gr_pgo"/wl/"model.lcov"):
            path = Path(file)
            if "_sched_" not in path.name:continue
            key = pending = None
            with path.open() as stream:
                for i,raw in enumerate(stream,1):
                    t = raw.strip()
                    if t.startswith("// op "):
                        match = commit_re.match(t)
                        key = ("EAGER", path.name, write_ids.get(match[1])) if match else None
                        pending = None
                    elif key in profile:
                        if "state_logic_storage_" in t and " != next_value" in t:
                            pending = lines.get(i,0)
                        elif pending is not None and t.endswith(" = next_value;"):
                            pair = pending,lines.get(i,0)
                            n,c = profile[key]
                            if wl == "coremark":
                                if key in seen: raise ValueError(f"duplicate commit match {key}")
                                seen.add(key)
                                check(key,(n,c),pair)
                            elif n>=1000 and 5*c>=n:
                                hot.update(sites=1,visits=pair[0],changes=pair[1])
                            pending = None
    save(DEST/"crosscheck.json",dict(training=result,holdout_shared_sparse_05=quiet,holdout_eager_20=hot))


if __name__ == "__main__":
    main()
