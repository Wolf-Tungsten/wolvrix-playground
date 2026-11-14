"""Explain unmatched full-graph F29 Nodes using native inventories and lineage."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time

from semantic_node_exchange import encode_cell, parsed_row

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-work', type=Path, required=True)
    parser.add_argument('--names-work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    full, names, output = args.full_work.resolve(), args.names_work.resolve(), args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    database = output / 'evidence.sqlite'
    if database.exists():
        parser.error('evidence database already exists; use a new output directory')
    verified = json.loads((full / 'summary.json').read_text())
    named = json.loads((names / 'summary.json').read_text())
    if not verified.get('comparison_report_complete') or not named.get('complete'):
        raise ValueError('full replay/comparison and Node name comparison must be complete')
    if named['input_sha256'] != verified['input']['sha256']:
        raise ValueError('Node report and replay report refer to different FIRRTL inputs')
    expected = named['comparison']['after']['grh_unmatched_nodes']
    rows = []
    source = names / 'after.unmatched.tsv'
    with source.open() as stream:
        stream.readline()
        columns = stream.readline().rstrip('\n').split('\t')
        for line in stream:
            if line.startswith('#footer\t'):
                break
            row = parsed_row(line, columns)
            if row['engine'] == 'grh':
                rows.append(row)
    if len(rows) != expected:
        raise ValueError('unmatched input count differs from completed name report')
    started = time.monotonic()
    report = {'schema': 'wolvrix.f29.unmatched-explanation.v1', 'complete': False,
              'input_sha256': named['input_sha256'], 'grh_unmatched_nodes': expected,
              'source': str(source), 'evidence_database': str(database),
              'scope': 'native Node identity and split lineage; not functional equivalence',
              'categories': {}, 'evidence_levels': {}}

    def save(stage: str) -> None:
        report['stage'] = stage
        report['wall_s'] = time.monotonic() - started
        pending = output / 'summary.pending'
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        pending.replace(output / 'summary.json')
        print(f'[F29 unmatched] {stage}', flush=True)

    db = sqlite3.connect(database, uri=True)
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('PRAGMA synchronous=OFF')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('PRAGMA cache_size=-65536')
    db.execute('ATTACH DATABASE ? AS names', ((names / 'nodes.sqlite').as_uri() + '?mode=ro',))
    try:
        for engine in ('grh', 'gsim'):
            save('extract-lineage-' + engine)
            db.execute('ATTACH DATABASE ? AS trace', ((full / f'{engine}-split.sqlite').as_uri() + '?mode=ro',))
            db.execute(f'''CREATE TABLE {engine}_lineage AS
                SELECT object_id AS parent, json_extract(detail_json,'$.to_node_id') AS child,
                       json_extract(detail_json,'$.coordinates') AS coordinates
                FROM trace.evolution WHERE record='lineage' ''')
            db.execute(f'CREATE INDEX {engine}_lineage_parent ON {engine}_lineage(parent)')
            db.execute(f'CREATE INDEX {engine}_lineage_child ON {engine}_lineage(child)')
            db.commit()
            db.execute('DETACH DATABASE trace')
            report[engine + '_lineage_count'] = db.execute(f'SELECT COUNT(*) FROM {engine}_lineage').fetchone()[0]
        save('evidence-ready')

        def node(engine: str, phase: str, identifier: int):
            return db.execute(f'SELECT id,path FROM names.{phase}_{engine}_nodes WHERE id=?', (identifier,)).fetchone()

        def lookup(engine: str, phase: str, path: str):
            return db.execute(f'SELECT node_id,occurrences FROM names.{phase}_{engine}_names WHERE path=?', (path,)).fetchone()

        children_cache = {}

        def children(engine: str, parent: int):
            key = engine, parent
            if key not in children_cache:
                children_cache[key] = db.execute(f'SELECT child,coordinates FROM {engine}_lineage WHERE parent=?', (parent,)).fetchall()
            return children_cache[key]

        def parents(engine: str, child: int):
            return db.execute(f'SELECT parent,coordinates FROM {engine}_lineage WHERE child=?', (child,)).fetchall()

        categories, levels, examples = Counter(), Counter(), {}
        columns = ('grh_node_id', 'grh_path', 'category', 'evidence_level', 'peer_node_ids_json',
                   'grh_parent_id', 'gsim_parent_id', 'coordinates_json', 'grh_split_children',
                   'gsim_split_children', 'preexisting_before', 'evidence')
        pending = output / 'unmatched-reasons.pending'
        with pending.open('w') as target:
            target.write('#meta\t' + json.dumps({key: report[key] for key in ('schema', 'input_sha256', 'scope')}) + '\n')
            target.write('\t'.join(columns) + '\n')
            for index, row in enumerate(rows):
                identifier, path = int(row['node_id']), row['canonical_firrtl_path']
                before = node('grh', 'before', identifier)
                prior = before is not None and before[1] == path
                category, level, evidence = 'unexplained', 'unclassified', 'No confirmed native relation yet'
                peers, grh_parent, gsim_parent, coords, grh_n, gsim_n = [], None, None, None, 0, 0
                if int(row['peer_path_count']) > 1:
                    category, level = 'gsim_path_collision', 'inventory-confirmed'
                    peers = [value[0] for value in db.execute('SELECT id FROM names.after_gsim_nodes WHERE path=?', (path,))]
                    evidence = 'Multiple live GSIM Nodes have the same normalized public path'
                else:
                    transformations = []
                    if '$ADDR0' in path:
                        transformations.append(('address_pipeline_name', path.replace('$ADDR0', '.$address')))
                    if '.$storage' in path:
                        transformations.append(('storage_lowering_name', path.replace('.$storage', '')))
                    for candidate_category, candidate_path in transformations:
                        peer = lookup('gsim', 'after', candidate_path)
                        if peer and peer[1] == 1:
                            category, level, peers = candidate_category, 'inventory-and-source-rule', [peer[0]]
                            evidence = f'Alternate source-rule path exists; preexisting_before={prior}; no semantic equivalence inferred'
                            break
                    if category == 'unexplained' and before:
                        peer = lookup('gsim', 'before', before[1])
                        if peer and peer[1] == 1:
                            peer_id = peer[0]
                            peer_children = children('gsim', peer_id)
                            own_children = children('grh', identifier)
                            if peer_children and not node('gsim', 'after', peer_id):
                                category = 'grh_retained_split_parent' if own_children else 'gsim_split_grh_kept'
                                level, peers, grh_parent, gsim_parent = 'native-lineage-confirmed', [item[0] for item in peer_children], identifier, peer_id
                                grh_n, gsim_n = len(own_children), len(peer_children)
                                evidence = 'Same unique before path; GSIM retires parent and records split; GRH parent remains live'
                    if category == 'unexplained':
                        for parent, coordinates in parents('grh', identifier):
                            parent_before = node('grh', 'before', parent)
                            if not parent_before:
                                continue
                            peer = lookup('gsim', 'before', parent_before[1])
                            if not peer or peer[1] != 1:
                                continue
                            peer_id = peer[0]
                            own_children, peer_children = children('grh', parent), children('gsim', peer_id)
                            if not peer_children and node('gsim', 'after', peer_id):
                                category, level, peers = 'grh_split_gsim_kept', 'native-lineage-confirmed', [peer_id]
                                evidence = 'Same unique before parent path; GRH records split child; GSIM parent remains live without split'
                            else:
                                matched = [child for child, peer_coords in peer_children
                                           if peer_coords == coordinates and node('gsim', 'after', child)]
                                if len(matched) != 1:
                                    continue
                                category, level, peers = 'split_member_name_difference', 'native-lineage-confirmed', matched
                                evidence = 'Unique same before parent path and identical native split coordinates; after names differ'
                            grh_parent, gsim_parent, coords = parent, peer_id, coordinates
                            grh_n, gsim_n = len(own_children), len(peer_children)
                            break
                categories[category] += 1
                levels[level] += 1
                detail = dict(zip(columns, (identifier, path, category, level, json.dumps(peers), grh_parent,
                                            gsim_parent, coords, grh_n, gsim_n, int(prior), evidence)))
                if len(examples.setdefault(category, [])) < 3:
                    examples[category].append(detail)
                target.write('\t'.join(encode_cell(detail[key]) for key in columns) + '\n')
                if (index + 1) % 10000 == 0:
                    report.update(categories=dict(categories), evidence_levels=dict(levels))
                    save(f'classified-{index + 1}')
            target.write('#footer\t' + json.dumps({'complete': True, 'rowCount': len(rows)}) + '\n')
        pending.replace(output / 'unmatched-reasons.tsv')
        if sum(categories.values()) != expected:
            raise ValueError('category total differs from unmatched inventory')
        report.update(complete=True, categories=dict(categories), evidence_levels=dict(levels), examples=examples,
                      table=str(output / 'unmatched-reasons.tsv'))
        save('complete')
    finally:
        db.close()


if __name__ == '__main__':
    main()
