# perf-script handler: aggregate AMD IBS samples by instruction address.
# Loaded by `perf script -s`; armor_dispatch_ibs.py sets the two environment variables.
import collections
import json
import os
import struct

WHAT = os.environ['ARMOR_IBS_WHAT']
OUT = os.environ['ARMOR_IBS_OUT']
rows = {}
meta = collections.Counter()
latency = collections.defaultdict(collections.Counter)


def process_event(event):
    raw = event.get('raw_buf')
    if raw is None or len(raw) < 28:
        meta['without_raw_data'] += 1
        return
    meta['samples'] += 1
    if WHAT == 'fetch':
        ctl, ip = struct.unpack_from('<QQ', raw, 4)
        row = rows.get(ip)
        if row is None:
            row = rows[ip] = [0] * 9 + [event.get('dso', ''), event.get('symbol', '')]
        lat = ctl >> 32 & 0xffff
        ic, l2, l3 = ctl >> 51 & 1, ctl >> 58 & 1, ctl >> 61 & 1
        row[0] += 1
        row[1] += ctl >> 50 & 1          # fetch completed
        row[2] += ic; row[3] += l2; row[4] += l3
        row[5] += ctl >> 55 & 1          # L1 iTLB miss
        row[6] += ctl >> 56 & 1          # L2 iTLB miss
        row[7] += ctl >> 60 & 1          # op cache miss
        row[8] += lat
        latency[f'{ic}{l2}{l3}'][min(lat, 2000)] += 1
        return
    ctl, ip, data = struct.unpack_from('<QQQ', raw, 4)
    if data >> 38 & 1:
        meta['rip_invalid'] += 1
        return
    row = rows.get(ip)
    if row is None:
        row = rows[ip] = [0] * 6 + [event.get('dso', ''), event.get('symbol', '')]
    row[0] += 1
    if data >> 37 & 1:                   # retired branch
        row[1] += 1
        row[2] += data >> 35 & 1         # taken
        row[3] += data >> 36 & 1         # mispredicted
        row[4] += data >> 34 & 1         # return
        row[5] += data >> 39 & 1         # fused with the preceding compare


def trace_end():
    with open(os.path.join(OUT, 'ip.tsv'), 'w') as stream:
        for ip, row in rows.items():
            stream.write(f'{ip:x}\t' + '\t'.join(map(str, row)) + '\n')
    with open(os.path.join(OUT, 'meta.json'), 'w') as stream:
        json.dump(dict(meta=meta, latency={k: sorted(v.items()) for k, v in latency.items()}), stream)
