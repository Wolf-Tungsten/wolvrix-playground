"""Report one frozen F32 Node inventory without waiting for structural proofs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from compare_f32_semantics import STAGES, capture, read_table
from semantic_node_exchange import HEADERS, integer, json_value, validate_node

ROOT = Path(__file__).resolve().parents[1]


def ingest(db, directory, engine, stage, summary):
    record = summary['snapshots'][stage]
    artifact = record['artifacts']['nodes.tsv']
    pending, previous = [], -1

    def consume(row):
        nonlocal previous
        row['node_id'] = integer(row['node_id'])
        row['name_path_json'] = (None if row['name_path_json'] is None else
                                 json_value(row['name_path_json'], list))
        validate_node(row)
        if row['node_id'] <= previous:
            raise ValueError('native Node inventory is not uniquely sorted')
        previous = row['node_id']
        name = '.'.join(row['name_path_json']) if row['name_path_json'] else None
        pending.append((engine, row['node_id'], name))
        if len(pending) == 8192:
            db.executemany('INSERT INTO nodes VALUES(?,?,?)', pending)
            pending.clear()

    metadata, footer = read_table(directory / stage / 'nodes.tsv', HEADERS['nodes'], artifact,
        {'engine': engine, 'stage': STAGES[engine][int(stage[1])], 'table': 'nodes'},
        'semantic-node-exchange.v1', consume)
    db.executemany('INSERT INTO nodes VALUES(?,?,?)', pending)
    if footer.get('nodeInventoryComplete') is not True:
        raise ValueError('native Node inventory is partial')
    if any(not isinstance(metadata.get(key), str) or not metadata[key]
           for key in ('run_id', 'graph_id', 'exchange_session_id', 'snapshot_id')):
        raise ValueError('missing native snapshot identity')
    if metadata.get('input_identity', {}).get('sha256') not in (None, summary['input_sha256']):
        raise ValueError('native Node inventory input mismatch')
    return {'nodes': footer['rowCount'], 'snapshot_id': metadata['snapshot_id'], 'artifact': artifact}


def report(grh, gsim, output, stage='P4'):
    grh, gsim, output = (Path(path).resolve() for path in (grh, gsim, output))
    if not output.is_relative_to(ROOT / 'ptmp') or output.exists():
        raise ValueError('output must be a new directory under repository ptmp')
    summaries = {engine: capture(directory, engine) for engine, directory in (('grh', grh), ('gsim', gsim))}
    if summaries['grh']['input_sha256'] != summaries['gsim']['input_sha256']:
        raise ValueError('captures use different original FIRRTL inputs')
    semantics = {engine: summary.get('window_semantics') for engine, summary in summaries.items()}
    semantics_status = ('unspecified' if any(value is None for value in semantics.values()) else
                        'explicit-match' if semantics['grh'] == semantics['gsim'] else 'explicit-mismatch')
    started = time.monotonic()
    output.mkdir(parents=True)
    db = sqlite3.connect(output / 'names.sqlite')
    try:
        db.executescript('''PRAGMA journal_mode=DELETE; PRAGMA temp_store=FILE;
            PRAGMA cache_size=-65536;
            CREATE TABLE nodes(engine TEXT,id INTEGER,name TEXT,PRIMARY KEY(engine,id));''')
        records = {engine: ingest(db, directory, engine, stage, summaries[engine])
                   for engine, directory in (('grh', grh), ('gsim', gsim))}
        db.execute('CREATE INDEX names ON nodes(engine,name)')
        db.execute('''CREATE TABLE unique_names AS SELECT engine,name,min(id) id FROM nodes
            WHERE name IS NOT NULL GROUP BY engine,name HAVING count(*)=1''')
        db.execute('CREATE UNIQUE INDEX unique_names_key ON unique_names(engine,name)')
        pairs = db.execute('''SELECT count(*) FROM unique_names g JOIN unique_names s ON s.name=g.name
            AND s.engine='gsim' WHERE g.engine='grh' ''').fetchone()[0]
        total = records['grh']['nodes']
        result = {'schema': 'wolvrix.f32.inventory-report.v1', 'status': 'diagnostic-inventory', 'complete': True,
            'boundary': stage, 'scope': 'complete native Node counts and unique canonical-name candidates',
            'window_semantics_by_engine': semantics, 'window_semantics_comparison': semantics_status,
            'semantic_comparison_performed': False,
            'input_sha256': summaries['grh']['input_sha256'], 'snapshots': records,
            'unique_name_candidates': pairs, 'grh_unique_name_candidate_ratio': pairs / total if total else None,
            'unpaired_nodes': {engine: row['nodes'] - pairs for engine, row in records.items()},
            'semantic_acceptance': False, 'functional_equivalence_proved': False,
            'capture_summaries': {engine: {'path': str(directory / 'summary.json'),
                'sha256': hashlib.sha256((directory / 'summary.json').read_bytes()).hexdigest()}
                for engine, directory in (('grh', grh), ('gsim', gsim))},
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'wall_s': time.monotonic() - started}
        db.commit()
    finally:
        db.close()
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh', 'gsim', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--stage', choices=tuple(f'P{i}' for i in range(5)), default='P4')
    args = parser.parse_args()
    print(json.dumps(report(args.grh, args.gsim, args.output, args.stage), sort_keys=True))


if __name__ == '__main__':
    main()
