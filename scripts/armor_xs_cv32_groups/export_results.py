"""Keep portable raw times alongside the TNO record."""
import csv
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0,str(root/'scripts'))
from xiangshan_cv32_ablation_measure import read

fields = ['workload','host','cpu','round','position','configuration','wall_s','host_ms','smt_sibling_idle_pct',
          'pc','instr_count','cycle_count','guest_cycles']
csv_path = root/'pdocs/armor_grhsim/data/TNO0020_xiangshan_group_times.csv'
with csv_path.open('w') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for wl, path in [('CoreMark',out/'timing'),('microbench',out/'microbench')]:
        policy = read(path/'policy.json')
        rounds = read(path/'rounds.json')
        assert len(rounds) == len(policy['orders'])
        for row,order in zip(rounds,policy['orders']):
            assert row['order'] == order
            for position,n in enumerate(order, 1):
                sample=row[n]
                sibling_idle = next(v for c,v in sample['sibling_idle'].items() if int(c)!=policy['cpu'])
                writer.writerow(dict(workload=wl,host=policy['host'],cpu=policy['cpu'],round=row['round'],
                     position=position,configuration=n,wall_s=f"{sample['external_wall_s']:.6f}",
                     host_ms=sample['host_ms'],smt_sibling_idle_pct=f"{sibling_idle:.1f}",
                     **{k:sample[k] for k in ('pc','instr_count','cycle_count','guest_cycles')}))
print(csv_path)
