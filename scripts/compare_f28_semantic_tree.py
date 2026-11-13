"""Consume native F28 leaf Nodes and GSIM Init Nodes without rebuilding membership.

Names locate candidates only. A separate conservative check compares the actual
owned combinational subgraphs, with paired boundary values as explicit premises.
Unsupported state, memory, effects and partial assignments remain unverified.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from functools import lru_cache
import hashlib
from itertools import product
import json
from math import prod
import os
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import subprocess
import time

from semantic_bitvector import (BVType, Unverified, cast, concatenate, constant, mux,
                           normalize_grh, normalize_gsim, resize, slice_bits, source)

ROOT = Path(__file__).resolve().parents[1]
SECTION = re.compile(r'^"(paths|nodes|memories|vals|values|ops)":\s*\[\s*$')
STRINGS = re.compile(r'"(?:[^"\\]|\\.)*"')
STATE = re.compile(r'Register|Latch|Memory|System|Dpic|Blackbox|Instance|XMR|Xmr')


def qualified(tokens):
    return '.'.join(''.join('\\' + ch if ch in '.\\[]' else ch for ch in token)
                    for token in tokens)


def records(path):
    """Read producer PrettyCompact records; multiline GSIM assignTrees stay bounded.

    Only one record is buffered. The producer emits section headers on their own
    lines and each record begins with '{'; JSON strings are never brace-counted.
    """
    section, collecting, chunks, depth = '', False, [], 0
    with Path(path).open(encoding='utf-8') as stream:
        for raw in stream:
            text = raw.strip()
            if not collecting:
                match = SECTION.match(text)
                if match:
                    section = match[1]
                    continue
                if text.startswith('"namesFlattened":'):
                    yield 'flattened', json.loads(text.split(':', 1)[1].rstrip(','))
                if text.startswith('"formatVersion":'):
                    yield 'version', json.loads(text.split(':', 1)[1].rstrip(','))
                if text.startswith(('"sourceUnit":', '"circuit":', '"rootPath":')):
                    key = text[1:text.index('"', 1)]
                    yield 'context', (key, json.loads(text.split(':', 1)[1].rstrip(',')))
                if text.startswith('"symbol":'):
                    yield 'graph', json.loads(text.split(':', 1)[1].rstrip(','))
                if text.startswith('"metadata":'):
                    section = 'metadata'
                    raw = text.split(':', 1)[1]
                    text = raw.strip()
                if text.startswith(']'):
                    section = ''
                if not section or not text.startswith('{'):
                    continue
                # GRH PrettyCompact and GSIM without trees use one line per
                # object. Keep their large-file hot path in the JSON C parser.
                try:
                    row = json.loads(text.rstrip(','))
                except json.JSONDecodeError:
                    pass
                else:
                    yield section, row
                    continue
                collecting, chunks, depth = True, [], 0
            chunks.append(raw)
            # JSON strings cannot contain literal newlines. Remove complete
            # string tokens in C before counting structural delimiters.
            structural = STRINGS.sub('', raw)
            depth += structural.count('{') + structural.count('[') - structural.count('}') - structural.count(']')
            if depth == 0:
                yield section, json.loads(''.join(chunks).strip().rstrip(','))
                collecting = False
    if collecting:
        raise ValueError(f'truncated {section} record in {path}')


def attr(row, key, default=None):
    value = row.get('attrs', {}).get(key, default)
    return value.get('v', value.get('vs', default)) if isinstance(value, dict) else value


def uncovered_source_registry(grh):
    """Use the capture's actual input registry; display names prove no origin."""
    summary = Path(grh).parent / 'capture-summary-grh.json'
    if not summary.exists():
        return set(), None
    capture = json.loads(summary.read_text())
    files = {str(Path(row['path']).expanduser().resolve())
             for row in capture.get('request', {}).get('sources', [])
             if row.get('language', '').lower() in ('sv', 'systemverilog')}
    return files, str(summary.resolve())


def uncovered_source(row, sv_files):
    location = row.get('loc', {})
    if location.get('pass') in ('ingest-firrtl', 'ingest-firrtl-abi'):
        return 'confirmed_FIRRTL_missing_membership'
    source_file = location.get('file')
    if source_file and str(Path(source_file).expanduser().resolve()) in sv_files:
        return 'confirmed_SV'
    return 'unknown'


def candidate_name(row):
    semantic = row.get('semantic', {})
    tokens = list(semantic.get('path', ()))
    if not tokens:
        return None
    role = semantic.get('role')
    if role == 'memory-read-address':
        # The native endpoint is explicit, but its pipeline stage has no
        # cross-engine producer mapping yet. Do not alias it with its reader.
        return None
    # These are producer endpoint labels used only for candidate location.
    if role == 'register-next':
        tokens[-1] += '$NEXT'
    elif role == 'memory-storage':
        depth = semantic.get('scopeDepth')
        if type(depth) is int and 0 <= depth < len(tokens):
            tokens.insert(depth + 1, '$storage')
        elif depth is None and len(tokens) == 1:
            tokens.append('$storage')
        else:
            return None
    return qualified(tokens)


def create_index(grh, native, output):
    os.environ['SQLITE_TMPDIR'] = str(output.resolve())
    dbpath = output / 'comparison.sqlite'
    if dbpath.exists():
        dbpath.unlink()
    db = sqlite3.connect(dbpath)
    db.executescript('''
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
        CREATE TABLE grh_nodes(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE members(node INTEGER,op INTEGER,PRIMARY KEY(node,op));
        CREATE TABLE anchors(node INTEGER,value INTEGER,PRIMARY KEY(node,value));
        CREATE TABLE values_ir(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE ops(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE producers(value INTEGER PRIMARY KEY,op INTEGER NOT NULL);
        CREATE TABLE gs_nodes(id INTEGER PRIMARY KEY,name TEXT,native_name TEXT,inventory TEXT,payload TEXT NOT NULL);
        CREATE TABLE pairs(grh INTEGER PRIMARY KEY,gsim INTEGER UNIQUE,name TEXT NOT NULL);
        CREATE TABLE results(grh INTEGER PRIMARY KEY,gsim INTEGER,status TEXT,reason TEXT);
        CREATE TABLE native_type_evidence(id INTEGER PRIMARY KEY,width INTEGER,signed INTEGER,shape TEXT,evidence TEXT);
        CREATE TABLE disconnected_members(node INTEGER,op INTEGER,kind TEXT,PRIMARY KEY(node,op));
    ''')
    counts, flattened, version, active_tree = Counter(), None, None, False
    with db:
        for section, row in records(grh):
            if section == 'version':
                version = row
            elif section == 'graph':
                active_tree = False
            elif section == 'flattened':
                if flattened is not None:
                    raise ValueError('expected one flattened graph with a SemanticTree')
                flattened = row
                active_tree = True
            elif section == 'paths':
                if not active_tree:
                    continue
                counts['paths'] += 1
                if row['id'] != 1 or row['parent'] != 0:
                    raise ValueError('comparison requires post-flatten root-only Paths')
            elif section == 'nodes':
                if not active_tree:
                    continue
                if row['parent'] != 1 or 'ops' not in row:
                    raise ValueError('requires v5 named leaf Nodes with authoritative ops')
                db.execute('INSERT INTO grh_nodes VALUES(?,?)', (row['id'], row['name']))
                for key, table, column in (('ops', 'members', 'op'), ('anchors', 'anchors', 'value')):
                    refs = row.get(key, [])
                    if len(refs) != len(set(refs)):
                        raise ValueError(f'duplicate native Node {key}: {row["id"]}')
                    db.executemany(f'INSERT INTO {table}(node,{column}) VALUES(?,?)',
                                   ((row['id'], ref) for ref in refs))
                counts['grh_nodes'] += 1
            elif section in ('vals', 'values'):
                if not active_tree:
                    continue
                db.execute('INSERT INTO values_ir VALUES(?,?)', (row['id'], json.dumps(row, separators=(',', ':'))))
                counts['grh_values'] += 1
            elif section == 'ops':
                if not active_tree:
                    continue
                db.execute('INSERT INTO ops VALUES(?,?)', (row['id'], json.dumps(row, separators=(',', ':'))))
                db.executemany('INSERT INTO producers VALUES(?,?)', ((value, row['id']) for value in row.get('out', [])))
                counts['grh_ops'] += 1
                if counts['grh_ops'] % 1000000 == 0:
                    print(f'[F28] indexed {counts["grh_ops"]:,} native GRH ops', flush=True)
        if version != 5 or flattened is not True or counts['paths'] != 1:
            raise ValueError('requires JSON v5, namesFlattened=true and exactly one root Path')
        for section, row in records(native):
            if section not in ('nodes', 'memories'):
                continue
            db.execute('INSERT INTO gs_nodes VALUES(?,?,?,?,?)',
                       (row['id'], candidate_name(row), row.get('name', ''), section,
                        json.dumps(row, separators=(',', ':'))))
            counts['gsim_' + section] += 1
            counts['gsim_total_nodes'] += 1
            if counts['gsim_total_nodes'] % 1000000 == 0:
                print(f'[F28] indexed {counts["gsim_total_nodes"]:,} native GSIM Nodes', flush=True)
        db.executescript('''
            CREATE INDEX members_by_op ON members(op,node);
            CREATE INDEX anchors_by_value ON anchors(value,node);
            CREATE INDEX grh_names ON grh_nodes(name);
            CREATE INDEX gs_names ON gs_nodes(name);
            CREATE INDEX gs_native_names ON gs_nodes(native_name);
            INSERT INTO pairs SELECT g.id,s.id,g.name FROM grh_nodes g JOIN gs_nodes s ON s.name=g.name
              WHERE (SELECT count(*) FROM grh_nodes gg WHERE gg.name=g.name)=1
                AND (SELECT count(*) FROM gs_nodes ss WHERE ss.name=s.name)=1;
        ''')
        missing = db.execute('SELECT count(*) FROM members m LEFT JOIN ops o ON o.id=m.op WHERE o.id IS NULL').fetchone()[0]
        missing += db.execute('SELECT count(*) FROM anchors a LEFT JOIN values_ir v ON v.id=a.value WHERE v.id IS NULL').fetchone()[0]
        if missing:
            raise ValueError(f'{missing} native Node members/anchors refer to missing IR objects')
    return db, counts


class Subgraphs:
    """Bounded local checks; no traversal outside the native Node op set."""
    def __init__(self, db, budget=10000):
        self.db, self.budget = db, budget
        self.members, self.visited, self.active = set(), set(), set()
        self.root = None
        self.steps = 0
        self.type_active = set()

    @lru_cache(maxsize=8192)
    def value(self, vid):
        row = self.db.execute('SELECT payload FROM values_ir WHERE id=?', (vid,)).fetchone()
        if not row:
            raise Unverified('missing_GRH_value')
        return json.loads(row[0])

    @lru_cache(maxsize=8192)
    def operation(self, oid):
        row = self.db.execute('SELECT payload FROM ops WHERE id=?', (oid,)).fetchone()
        if not row:
            raise Unverified('missing_GRH_op')
        return json.loads(row[0])

    @lru_cache(maxsize=8192)
    def native(self, nid):
        row = self.db.execute('SELECT payload FROM gs_nodes WHERE id=?', (nid,)).fetchone()
        if not row:
            raise Unverified('missing_GSIM_Node')
        return json.loads(row[0])

    def step(self):
        self.steps += 1
        if self.steps > self.budget:
            raise Unverified('local_subgraph_budget_exceeded')

    def geometry(self, row):
        shape = tuple(row.get('shape', []))
        width = row.get('w', 0)
        if width < 1 or any(x < 1 for x in shape) or width % prod(shape):
            raise Unverified('unknown_or_zero_GRH_geometry')
        domain = row.get('domain')
        if row.get('type') != 'logic' or domain not in ('2state', 'two', 'two-state', '4state'):
            raise Unverified('requires_known_logic_domain')
        # BV terms serve as a normalized structure signature for four-state
        # GRH too. That result is never a claim about X/Z behavior.
        if domain == '4state':
            self.four_state = True
        return width // prod(shape), bool(row.get('sgn', False)), shape

    def gtype(self, vid):
        width, signed, _ = self.geometry(self.value(vid))
        return BVType(width, signed)

    def boundary(self, vid, index):
        # The identity is a native shared anchor, not a guessed producer cone.
        paired = self.db.execute('''SELECT p.gsim FROM anchors a JOIN pairs p ON p.grh=a.node
                                   WHERE a.value=? ORDER BY p.gsim LIMIT 1''', (vid,)).fetchone()
        if not paired:
            raise Unverified('unpaired_GRH_subgraph_boundary')
        return source(('native_anchor', vid, index), self.gtype(vid))

    @lru_cache(maxsize=8192)
    def native_geometry(self, nid):
        row = self.native(nid)
        shape = tuple(row.get('dimension', []))
        if row.get('width', -1) > 0:
            return row['width'], bool(row.get('sign', False)), shape
        if nid in self.type_active:
            raise Unverified('native_type_dependency_cycle')
        if row.get('type') in ('NODE_REG_SRC', 'NODE_REG_DST', 'NODE_MEMORY', 'NODE_READER', 'NODE_WRITER', 'NODE_SPECIAL', 'NODE_EXT'):
            raise Unverified('unknown_state_memory_effect_boundary_type')
        self.type_active.add(nid)
        try:
            trees = row.get('assignTrees', [])
            if not trees:
                raise Unverified('unknown_native_boundary_type_without_assignment')
            inferred = []
            for tree in trees:
                entries = {item['id']: item for item in tree['nodes']}
                inferred.append(self.native_enode_geometry(entries, tree['root']))
            if len(set((width, signed) for width, signed, _ in inferred)) != 1:
                raise Unverified('native_assignments_have_different_element_types')
            width, signed, _ = inferred[0]
            if width < 1:
                raise Unverified('zero_or_unknown_native_boundary_width')
            self.db.execute('INSERT OR REPLACE INTO native_type_evidence VALUES(?,?,?,?,?)',
                            (nid, width, signed, json.dumps(shape), 'actual_native_assignTrees'))
            return width, signed, shape
        finally:
            self.type_active.remove(nid)

    def native_enode_geometry(self, entries, eid):
        self.step()
        entry = entries[eid]
        kind = entry['op'] if entry['op'].startswith('OP_') else 'OP_' + entry['op']
        children = entry.get('children', [])
        if kind == 'OP_EMPTY' and entry.get('node'):
            refs = self.db.execute('SELECT id FROM gs_nodes WHERE native_name=?', (entry['node'],)).fetchall()
            if len(refs) != 1:
                raise Unverified('native_type_reference_is_not_unique')
            width, signed, shape = self.native_geometry(refs[0][0])
            if len(children) > len(shape):
                raise Unverified('native_type_array_rank_disagreement')
            return width, signed, shape[len(children):]
        args = [self.native_enode_geometry(entries, child) for child in children]
        width, signed = entry.get('width', -1), bool(entry.get('sign', False))
        values = entry.get('values', [])
        if kind == 'OP_GROUP':
            if not args or len(set(args)) != 1:
                raise Unverified('native_group_element_type_disagreement')
            return args[0][0], args[0][1], (len(args),) + args[0][2]
        shape = args[1][2] if kind in ('OP_MUX', 'OP_WHEN') and len(args) == 3 else ()
        if width > 0:
            return width, signed, shape
        if kind in ('OP_ADD', 'OP_SUB', 'OP_AND', 'OP_OR', 'OP_XOR') and len(args) == 2:
            width = max(item[0] for item in args) + (kind in ('OP_ADD', 'OP_SUB'))
            signed = args[0][1] if kind in ('OP_ADD', 'OP_SUB') else False
        elif kind == 'OP_MUL' and len(args) == 2:
            width, signed = sum(item[0] for item in args), args[0][1]
        elif kind == 'OP_CAT' and len(args) >= 1:
            width, signed = sum(item[0] for item in args), False
        elif kind in ('OP_EQ', 'OP_NEQ', 'OP_LT', 'OP_LEQ', 'OP_GT', 'OP_GEQ', 'OP_ANDR', 'OP_ORR', 'OP_XORR'):
            width, signed = 1, False
        elif kind in ('OP_MUX', 'OP_WHEN') and len(args) == 3:
            if args[1][2] != args[2][2]:
                raise Unverified('native_mux_array_shape_disagreement')
            width, signed = max(args[1][0], args[2][0]), args[1][1]
        elif len(args) == 1 and kind in ('OP_NOT', 'OP_ASUINT', 'OP_ASSINT', 'OP_ASCLOCK', 'OP_ASASYNCRESET'):
            width, signed = args[0][0], kind == 'OP_ASSINT'
            if kind in ('OP_ASCLOCK', 'OP_ASASYNCRESET'):
                width = 1
        elif len(args) == 1 and kind in ('OP_PAD', 'OP_SHL', 'OP_SHR', 'OP_HEAD', 'OP_TAIL', 'OP_BITS'):
            if len(values) != (2 if kind == 'OP_BITS' else 1):
                raise Unverified('invalid_native_type_parameters')
            width = {'OP_PAD': max(args[0][0], values[0]), 'OP_SHL': args[0][0] + values[0],
                     'OP_SHR': max(args[0][0] - values[0], 0), 'OP_HEAD': values[0],
                     'OP_TAIL': max(args[0][0] - values[0], 0), 'OP_BITS': values[0] - values[-1] + 1}[kind]
            signed = args[0][1] if kind in ('OP_PAD', 'OP_SHL', 'OP_SHR') else False
        elif len(args) == 1 and kind in ('OP_CVT', 'OP_NEG'):
            width, signed = args[0][0] + (not args[0][1] if kind == 'OP_CVT' else 1), True
        else:
            raise Unverified('unknown_native_ENode_type:' + kind)
        return width, signed, shape

    def native_boundary(self, nid, index):
        anchors = self.db.execute('''SELECT a.value FROM pairs p JOIN anchors a ON a.node=p.grh
                                    WHERE p.gsim=? ORDER BY a.value''', (nid,)).fetchall()
        if len(anchors) != 1:
            raise Unverified('GSIM_boundary_has_no_unique_native_anchor')
        width, signed, shape = self.geometry(self.value(anchors[0][0]))
        if self.native_geometry(nid) != (width, signed, shape):
            raise Unverified('GSIM_boundary_type_is_unknown_or_different')
        if len(index) != len(shape) or any(not 0 <= item < extent for item, extent in zip(index, shape)):
            raise Unverified('GSIM_boundary_array_projection_out_of_bounds')
        return self.boundary(anchors[0][0], index)

    def grh_expr(self, vid, index=()):
        self.step()
        key = ('grh', vid, index)
        if key in self.active:
            raise Unverified('combinational_cycle')
        row = self.value(vid)
        width, signed, shape = self.geometry(row)
        if len(index) != len(shape) or any(not 0 <= i < d for i, d in zip(index, shape)):
            raise Unverified('GRH_array_projection_out_of_bounds')
        producer = self.db.execute('SELECT op FROM producers WHERE value=?', (vid,)).fetchone()
        if not producer or producer[0] not in self.members:
            return self.boundary(vid, index)
        oid = producer[0]
        self.visited.add(oid)
        op = self.operation(oid)
        kind, args, typ = op['kind'], op.get('in', []), BVType(width, signed)
        self.active.add(key)
        try:
            if kind == 'kArrayCreate':
                if not shape or len(args) != shape[0]:
                    raise Unverified('array_create_geometry_disagreement')
                return self.grh_expr(args[index[0]], index[1:])
            if kind == 'kAssign':
                if len(args) != 1 or self.geometry(self.value(args[0])) != (width, signed, shape):
                    raise Unverified('assign_geometry_disagreement')
                return self.grh_expr(args[0], index)
            if kind == 'kMux':
                if len(args) != 3:
                    raise Unverified('mux_arity')
                return mux(self.grh_expr(args[0]), self.grh_expr(args[1], index), self.grh_expr(args[2], index), typ)
            if kind == 'kSliceArray':
                parent_shape = self.geometry(self.value(args[0]))[2]
                indices = []
                for value in args[1:]:
                    term = self.grh_expr(value)
                    if term.op != 'const':
                        raise Unverified('dynamic_array_index_unverified')
                    indices.append(term.params[0])
                if tuple(parent_shape[len(indices):]) != shape:
                    raise Unverified('array_slice_geometry_disagreement')
                return self.grh_expr(args[0], tuple(indices) + index)
            if shape:
                if kind == 'kConstant':
                    packed = normalize_grh(kind, BVType(row['w'], False), (), op.get('attrs'))
                    flat = 0
                    for axis, value in enumerate(index):
                        flat += value * prod(shape[axis + 1:])
                    return slice_bits(packed, flat * width, width, signed)
                raise Unverified('unsupported_GRH_array_operation:' + kind)
            return normalize_grh(kind, typ, [self.grh_expr(arg) for arg in args], op.get('attrs'))
        finally:
            self.active.remove(key)

    def native_ref(self, name, index=()):
        rows = self.db.execute('SELECT id FROM gs_nodes WHERE native_name=?', (name,)).fetchall()
        if len(rows) != 1:
            raise Unverified('GSIM_reference_is_not_unique')
        if rows[0][0] == self.native_root_id:
            raise Unverified('self_reference_is_not_a_free_boundary')
        return self.native_boundary(rows[0][0], index)

    def native_expr(self, entries, eid, expected, index=()):
        self.step()
        if eid not in entries:
            raise Unverified('missing_GSIM_ENode')
        enode = entries[eid]
        op = enode.get('op', '')
        if not op.startswith('OP_'):
            op = 'OP_' + op
        children = enode.get('children', [])
        if op == 'OP_EMPTY' and enode.get('node'):
            indices = []
            for child in children:
                item = entries[child]
                if item.get('op') not in ('OP_INDEX_INT', 'INDEX_INT') or len(item.get('values', [])) != 1:
                    raise Unverified('dynamic_GSIM_array_reference')
                indices.append(item['values'][0])
            return self.native_ref(enode['node'], tuple(indices) + index)
        if op == 'OP_GROUP':
            if not index or index[0] >= len(children):
                raise Unverified('GSIM_group_projection_disagreement')
            return self.native_expr(entries, children[index[0]], expected, index[1:])
        if index and op not in ('OP_MUX', 'OP_WHEN'):
            raise Unverified('unsupported_GSIM_array_operation:' + op)
        args = [self.native_expr(entries, child, None, index if op in ('OP_MUX', 'OP_WHEN') and slot else ())
                for slot, child in enumerate(children)]
        width = enode.get('width', -1)
        signed = bool(enode.get('sign', False))
        if width < 1:
            if op == 'OP_INT':
                if expected is None:
                    raise Unverified('unknown_native_constant_width')
                width, signed = expected.width, expected.signed
            elif op in ('OP_AND', 'OP_OR', 'OP_XOR', 'OP_ADD', 'OP_SUB') and len(args) == 2:
                width = max(arg.type.width for arg in args)
                if op in ('OP_ADD', 'OP_SUB'):
                    width += 1
                signed = args[0].type.signed if op in ('OP_ADD', 'OP_SUB') else False
            elif op == 'OP_MUL' and len(args) == 2:
                width = sum(arg.type.width for arg in args)
                signed = args[0].type.signed
            elif op in ('OP_EQ', 'OP_NEQ', 'OP_LT', 'OP_LEQ', 'OP_GT', 'OP_GEQ', 'OP_ANDR', 'OP_ORR', 'OP_XORR'):
                width, signed = 1, False
            elif op == 'OP_CAT':
                width, signed = sum(arg.type.width for arg in args), False
            elif op in ('OP_MUX', 'OP_WHEN') and len(args) == 3:
                width = max(arg.type.width for arg in args[1:])
                signed = args[1].type.signed
            elif len(args) == 1 and op in ('OP_NOT', 'OP_ASUINT', 'OP_ASSINT', 'OP_ASCLOCK', 'OP_ASASYNCRESET'):
                width = args[0].type.width
                signed = op == 'OP_ASSINT'
                if op in ('OP_ASCLOCK', 'OP_ASASYNCRESET'):
                    width = 1
            elif len(args) == 1 and op in ('OP_PAD', 'OP_SHL', 'OP_SHR', 'OP_HEAD', 'OP_TAIL', 'OP_BITS'):
                values = enode.get('values', [])
                required = 2 if op == 'OP_BITS' else 1
                if len(values) != required:
                    raise Unverified('invalid_native_width_parameters:' + op)
                width = {'OP_PAD': max(args[0].type.width, values[0]),
                         'OP_SHL': args[0].type.width + values[0],
                         'OP_SHR': max(args[0].type.width - values[0], 0),
                         'OP_HEAD': values[0],
                         'OP_TAIL': max(args[0].type.width - values[0], 0),
                         'OP_BITS': values[0] - values[-1] + 1}[op]
                signed = args[0].type.signed if op in ('OP_PAD', 'OP_SHL', 'OP_SHR') else False
            elif len(args) == 1 and op in ('OP_CVT', 'OP_NEG'):
                width = args[0].type.width + (not args[0].type.signed if op == 'OP_CVT' else 1)
                signed = True
            else:
                raise Unverified('unknown_GSIM_ENode_width:' + op)
        term = normalize_gsim(op, BVType(width, signed), args, enode.get('values', []), enode.get('strVal', ''))
        return resize(term, expected) if expected is not None else term

    def native_root(self, native, typ, index):
        trees = native.get('assignTrees')
        if trees is None:
            raise Unverified('assign_trees_not_dumped')
        if not trees:
            raise Unverified('no_native_assignment_tree')
        selected = []
        for tree in trees:
            entries = {item['id']: item for item in tree['nodes']}
            lvalue = entries.get(tree.get('lvalue'), {})
            indices = []
            for child in lvalue.get('children', []):
                entry = entries[child]
                if entry.get('op') not in ('OP_INDEX_INT', 'INDEX_INT') or len(entry.get('values', [])) != 1:
                    raise Unverified('dynamic_GSIM_lvalue')
                indices.append(entry['values'][0])
            if index[:len(indices)] == tuple(indices):
                selected.append((tree, entries, index[len(indices):]))
        if len(selected) != 1:
            raise Unverified('multiple_or_missing_GSIM_assignments_for_projection')
        tree, entries, remainder = selected[0]
        return self.native_expr(entries, tree['root'], typ, remainder)

    def owned_reachable(self, vid):
        pending, seen, reached = [vid], set(), set()
        while pending:
            self.step()
            value = pending.pop()
            if value in seen:
                continue
            seen.add(value)
            producer = self.db.execute('SELECT op FROM producers WHERE value=?', (value,)).fetchone()
            if producer and producer[0] in self.members:
                reached.add(producer[0])
                pending.extend(self.operation(producer[0]).get('in', []))
        return reached

    def compare(self, grh_id, gsim_id):
        self.root, self.steps = grh_id, 0
        self.four_state = False
        self.native_root_id = gsim_id
        self.members = {row[0] for row in self.db.execute('SELECT op FROM members WHERE node=?', (grh_id,))}
        self.visited, self.active = set(), set()
        native = self.native(gsim_id)
        if native.get('type') in ('NODE_REG_SRC', 'NODE_REG_DST', 'NODE_MEMORY', 'NODE_READER', 'NODE_WRITER', 'NODE_SPECIAL', 'NODE_EXT'):
            return 'unverified', 'state_memory_effect_unverified'
        if any(STATE.search(self.operation(oid)['kind']) for oid in self.members):
            return 'unverified', 'state_memory_effect_unverified'
        anchors = [row[0] for row in self.db.execute('SELECT value FROM anchors WHERE node=?', (grh_id,))]
        if len(anchors) != 1:
            return 'unverified', 'no_unique_native_Node_anchor'
        try:
            vid = anchors[0]
            reached = self.owned_reachable(vid)
            for oid in self.members - reached:
                self.db.execute('INSERT OR REPLACE INTO disconnected_members VALUES(?,?,?)',
                                (grh_id, oid, self.operation(oid)['kind']))
            width, signed, shape = self.geometry(self.value(vid))
            native_width, native_signed, native_shape = self.native_geometry(gsim_id)
            if native_shape != shape or native_width != width:
                return 'different', 'physical_geometry_disagreement'
            if native_signed != signed:
                return 'different', 'signedness_disagreement'
            if native.get('type') == 'NODE_INP':
                if self.members or not self.value(vid).get('in'):
                    return 'different', 'input_boundary_disagreement'
                if native.get('width', -1) != width:
                    raise Unverified('unknown_native_input_width')
                if self.four_state:
                    return 'structural_checked', 'input_geometry_and_native_anchor_X_semantics_unproved'
                return 'interface_checked', 'input_type_and_native_anchor'
            if prod(shape) > 4096:
                raise Unverified('array_projection_budget_exceeded')
            for index in product(*(range(dim) for dim in shape)):
                left = self.grh_expr(vid, index)
                right = self.native_root(native, BVType(width, signed), index)
                if left != right:
                    return 'different', 'canonical_boundary_expressions_differ'
            if reached != self.members:
                return 'unverified', 'owned_operations_not_reached_from_anchor'
            if self.visited != reached:
                return 'unverified', 'expression_check_did_not_visit_all_reachable_members'
            if self.four_state:
                return 'structural_checked', 'equal_typed_boundary_structure_X_semantics_unproved'
            return 'expression_checked', 'equal_typed_boundary_expressions'
        except (Unverified, RecursionError) as error:
            return 'unverified', str(error) or 'recursion_limit'


def write_tsv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows)


def write_json_atomic(path, payload):
    temporary = path.with_name(path.name + '.publishing')
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def input_identity(grh, native, require_captures=False):
    identity = {}
    for label, path in (('grh', Path(grh)), ('gsim', Path(native))):
        stat = path.stat()
        identity[label] = {'path': str(path.resolve()), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    captures = {}
    for label in ('grh', 'gsim'):
        summary = Path(grh).parent / f'capture-summary-{label}.json'
        if label == 'gsim' and not summary.exists():
            summary = Path(native).resolve().parent.parent / 'capture-summary-gsim.json'
        if not summary.exists():
            continue
        raw = summary.read_bytes()
        capture = json.loads(raw)
        if not capture.get('complete'):
            continue
        dumps = [capture.get('dump', {})]
        dumps += [stage.get('result', {}).get('dump', {}) for stage in capture.get('stages', [])]
        matched = [dump for dump in dumps if dump.get('path') and
                   str(Path(dump['path']).resolve()) == identity[label]['path']]
        if not matched or any(dump.get('bytes') != identity[label]['bytes'] or
                              dump.get('sha256') != matched[0].get('sha256') for dump in matched) or not matched[0].get('sha256'):
            raise ValueError(f'{label} capture dump identity does not match the comparison input')
        identity[label]['sha256'] = matched[0]['sha256']
        captures[label] = {'path': str(summary.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
                           'source': capture.get('input'),
                           'producer': capture.get('grh_producer_libraries') if label == 'grh'
                           else capture.get('gsim_producer')}
    if require_captures and set(captures) != {'grh', 'gsim'}:
        raise ValueError('reuse requires complete native GRH and GSIM capture identities')
    if set(captures) == {'grh', 'gsim'}:
        left, right = (captures[label].get('source') or {} for label in ('grh', 'gsim'))
        if not left.get('sha256') or left['sha256'] != right.get('sha256'):
            raise ValueError('native captures have different FIRRTL content identities')
    identity['captures'] = captures
    return identity


def check_pairs(db, budget, changed_only=False):
    checker, checked = Subgraphs(db, budget), 0
    query = 'SELECT grh,gsim FROM pairs ORDER BY grh'
    if changed_only:
        query = '''SELECT p.grh,p.gsim FROM pairs p JOIN changed_pairs c ON c.grh=p.grh ORDER BY p.grh'''
    with db:
        for grh_id, gs_id in db.execute(query):
            status, reason = checker.compare(grh_id, gs_id)
            db.execute('INSERT OR REPLACE INTO results VALUES(?,?,?,?)', (grh_id, gs_id, status, reason))
            checked += 1
            if checked % 100000 == 0:
                print(f'[F28] compared {checked:,} candidate pairs', flush=True)
    return checked


def refresh_candidates(db):
    """Refresh only producer-labelled storage endpoints; membership stays native."""
    db.executescript('''
        CREATE TEMP TABLE candidate_changes(id INTEGER PRIMARY KEY,old_name TEXT,new_name TEXT);
        CREATE TEMP TABLE affected_names(name TEXT PRIMARY KEY);
        CREATE TEMP TABLE old_pairs(grh INTEGER PRIMARY KEY,gsim INTEGER);
        CREATE TEMP TABLE changed_pairs(grh INTEGER PRIMARY KEY);
    ''')
    with db:
        # Payloads use canonical compact JSON. The substring only limits the
        # scan; the parsed producer role and scopeDepth establish the update.
        for nid, old_name, payload in db.execute('''SELECT id,name,payload FROM gs_nodes
                WHERE instr(payload,'"role":"memory-storage"')>0'''):
            row = json.loads(payload)
            if row.get('semantic', {}).get('role') != 'memory-storage':
                continue
            new_name = candidate_name(row)
            if old_name != new_name:
                db.execute('INSERT INTO candidate_changes VALUES(?,?,?)', (nid, old_name, new_name))
        updates = '''
            INSERT OR IGNORE INTO affected_names SELECT old_name FROM candidate_changes WHERE old_name IS NOT NULL;
            INSERT OR IGNORE INTO affected_names SELECT new_name FROM candidate_changes WHERE new_name IS NOT NULL;
            INSERT INTO old_pairs SELECT p.grh,p.gsim FROM pairs p JOIN affected_names a ON a.name=p.name;
            UPDATE gs_nodes SET name=(SELECT c.new_name FROM candidate_changes c WHERE c.id=gs_nodes.id)
                WHERE id IN (SELECT id FROM candidate_changes);
            DELETE FROM pairs WHERE name IN (SELECT name FROM affected_names);
            INSERT INTO pairs SELECT g.id,s.id,g.name FROM affected_names a
                JOIN grh_nodes g ON g.name=a.name JOIN gs_nodes s ON s.name=g.name
                WHERE (SELECT count(*) FROM grh_nodes gg WHERE gg.name=g.name)=1
                  AND (SELECT count(*) FROM gs_nodes ss WHERE ss.name=s.name)=1;
            INSERT INTO changed_pairs SELECT o.grh FROM old_pairs o LEFT JOIN pairs p ON p.grh=o.grh
                WHERE p.gsim IS NULL OR p.gsim!=o.gsim;
            INSERT OR IGNORE INTO changed_pairs SELECT p.grh FROM pairs p JOIN affected_names a ON a.name=p.name
                LEFT JOIN old_pairs o ON o.grh=p.grh WHERE o.gsim IS NULL OR o.gsim!=p.gsim;
        '''
        for statement in updates.split(';'):
            if statement.strip():
                db.execute(statement)
        scalar = lambda sql: db.execute(sql).fetchone()[0]
        changed_anchors = scalar('SELECT count(*) FROM anchors a JOIN changed_pairs c ON c.grh=a.node')
        result = {'memory_candidate_names_changed': scalar('SELECT count(*) FROM candidate_changes'),
                  'grh_pair_mappings_changed': scalar('SELECT count(*) FROM changed_pairs'),
                  'changed_pair_anchor_edges': changed_anchors,
                  'recheck_scope': 'all_pairs' if changed_anchors else 'changed_pairs_only',
                  'reuse_basis': 'unchanged native inventory and membership; changed pair endpoints have no anchors'
                  if not changed_anchors else 'anchor premises changed; all candidate pairs rechecked'}
        if changed_anchors:
            db.execute('DELETE FROM results')
            db.execute('DELETE FROM disconnected_members')
        else:
            db.execute('DELETE FROM results WHERE grh IN (SELECT grh FROM changed_pairs)')
            db.execute('DELETE FROM disconnected_members WHERE node IN (SELECT grh FROM changed_pairs)')
    return result


def semantic_context(path):
    graph, version, context, result = None, None, {}, None
    for section, row in records(path):
        if section == 'version':
            version = row
        elif section == 'graph':
            graph, context = row, {}
        elif section == 'context':
            context[row[0]] = row[1]
        elif section == 'flattened':
            if result is not None:
                raise ValueError('expected one native SemanticTree context')
            result = {'graph': graph, 'version': version, 'flattened': row, **context, 'paths': []}
        elif section == 'paths' and result is not None:
            result['paths'].append(row)
        elif section in ('nodes', 'vals', 'values', 'ops') and result is not None:
            return result
    if result is None:
        raise ValueError('missing native SemanticTree context')
    return result


def semantic_graph_metadata(path):
    active = False
    with Path(path).open() as stream:
        for raw in stream:
            text = raw.strip()
            if text.startswith('"symbol":'):
                active = False
            elif text.startswith('"semanticTree":'):
                active = True
            elif text.startswith('"metadata":') and active:
                payload = text.split(':', 1)[1]
                try:
                    return json.loads(payload.rstrip(','))
                except json.JSONDecodeError:
                    chunks = [payload]
                    depth = STRINGS.sub('', payload).count('{') - STRINGS.sub('', payload).count('}')
                    while depth:
                        raw = next(stream)
                        chunks.append(raw)
                        structural = STRINGS.sub('', raw)
                        depth += structural.count('{') - structural.count('}')
                    return json.loads(''.join(chunks).strip().rstrip(','))
    return {}


def same_json(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


def verify_native_refresh(db, grh, old_grh, counts, expected_added=None):
    """Stage only additions and loc changes after checking every native object."""
    expected_context = semantic_context(old_grh)
    expected_metadata = semantic_graph_metadata(old_grh)
    if expected_context.get('version') != 5 or expected_context.get('flattened') is not True:
        raise ValueError('native refresh requires the original flattened v5 context')
    db.executescript('''
        CREATE TEMP TABLE member_additions(node INTEGER,op INTEGER,PRIMARY KEY(node,op));
        CREATE TEMP TABLE changed_pairs(grh INTEGER PRIMARY KEY);
        CREATE TEMP TABLE payload_changes(kind TEXT,id INTEGER,old_loc TEXT,new_loc TEXT,payload TEXT,
                                         PRIMARY KEY(kind,id));
    ''')
    checked, last = Counter(), Counter()
    graph, version, pending_context, tree_context, active_tree = None, None, {}, None, False
    metadata_changes, saw_metadata, checked_context = {}, False, False
    with db:
        for section, row in records(grh):
            if section == 'version':
                version = row
            elif section == 'graph':
                graph, pending_context, active_tree = row, {}, False
            elif section == 'context':
                pending_context[row[0]] = row[1]
            elif section == 'flattened':
                if tree_context is not None:
                    raise ValueError('new capture has multiple SemanticTrees')
                if row is not True:
                    raise ValueError('new native SemanticTree is not flattened')
                active_tree = True
                tree_context = {'graph': graph, 'version': version, 'flattened': row,
                                **pending_context, 'paths': []}
            elif section == 'paths' and active_tree:
                if type(row.get('id')) is not int or type(row.get('parent')) is not int:
                    raise ValueError('native Path IDs must be integers')
                tree_context['paths'].append(row)
                checked['paths'] += 1
            elif section == 'metadata' and active_tree:
                saw_metadata = True
                for key in set(expected_metadata) | set(row):
                    if not same_json(expected_metadata.get(key), row.get(key)):
                        if not key.startswith('firrtl.externalInstance'):
                            raise ValueError(f'native top graph metadata changed: {key}')
                        metadata_changes[key] = {'old': expected_metadata.get(key), 'new': row.get(key)}
            elif section in ('nodes', 'vals', 'values', 'ops') and active_tree:
                kind = 'nodes' if section == 'nodes' else 'values' if section in ('vals', 'values') else 'ops'
                identifier = row['id']
                if type(identifier) is not int or identifier <= last[kind]:
                    raise ValueError(f'native refresh requires strictly increasing {kind} IDs')
                last[kind] = identifier
                checked[kind] += 1
                if kind == 'nodes':
                    if not checked_context:
                        if not same_json(tree_context, expected_context):
                            raise ValueError('native SemanticTree root context or Paths changed')
                        checked_context = True
                    old = db.execute('SELECT name FROM grh_nodes WHERE id=?', (identifier,)).fetchone()
                    if not old or old[0] != row.get('name') or type(row.get('parent')) is not int or row['parent'] != 1:
                        raise ValueError(f'native Node ID/name/parent changed at {identifier}')
                    if set(row) != {'id', 'name', 'parent', 'ops', 'anchors'}:
                        raise ValueError(f'native Node fields changed at {identifier}')
                    old_anchors = [item[0] for item in db.execute('SELECT value FROM anchors WHERE node=? ORDER BY value', (identifier,))]
                    if not all(type(vid) is int and vid > 0 for vid in row['anchors']) or row['anchors'] != old_anchors:
                        raise ValueError(f'native Node anchors changed at {identifier}')
                    old_members = {item[0] for item in db.execute('SELECT op FROM members WHERE node=?', (identifier,))}
                    members = row['ops']
                    if not all(type(oid) is int and oid > 0 for oid in members) or members != sorted(set(members)) or not old_members.issubset(members):
                        raise ValueError(f'existing native Node membership removed or duplicated at {identifier}')
                    additions = set(members) - old_members
                    if additions:
                        db.execute('INSERT INTO changed_pairs VALUES(?)', (identifier,))
                        db.executemany('INSERT INTO member_additions VALUES(?,?)', ((identifier, oid) for oid in additions))
                    checked['memberships'] += len(members)
                    checked['anchors'] += len(old_anchors)
                else:
                    table = 'values_ir' if kind == 'values' else 'ops'
                    previous = db.execute(f'SELECT payload FROM {table} WHERE id=?', (identifier,)).fetchone()
                    if previous is None:
                        raise ValueError(f'native {kind} ID inventory changed at {identifier}')
                    old = json.loads(previous[0])
                    current_physical, old_physical = dict(row), dict(old)
                    current_physical.pop('loc', None)
                    old_physical.pop('loc', None)
                    if not same_json(current_physical, old_physical):
                        raise ValueError(f'native physical {kind} payload changed at {identifier}')
                    if row.get('loc') != old.get('loc'):
                        db.execute('INSERT INTO payload_changes VALUES(?,?,?,?,?)',
                            (kind, identifier, json.dumps(old.get('loc'), separators=(',', ':')),
                             json.dumps(row.get('loc'), separators=(',', ':')),
                             json.dumps(row, separators=(',', ':'))))
                if checked[kind] % 1000000 == 0:
                    print(f'[F28] verified {checked[kind]:,} native GRH {kind}', flush=True)
        if not same_json(tree_context, expected_context):
            raise ValueError('native SemanticTree root context or Paths changed')
        if expected_metadata and not saw_metadata:
            raise ValueError('native top graph metadata was removed')
        for key, inventory in (('nodes', 'grh_nodes'), ('values', 'grh_values'), ('ops', 'grh_ops'), ('paths', 'paths')):
            if checked[key] != counts[inventory]:
                raise ValueError(f'native {key} inventory count changed')
        scalar = lambda sql: db.execute(sql).fetchone()[0]
        additions = scalar('SELECT count(*) FROM member_additions')
        if expected_added is not None and additions != expected_added:
            raise ValueError(f'expected {expected_added} added memberships, observed {additions}')
        if scalar('SELECT count(*) FROM member_additions a LEFT JOIN ops o ON o.id=a.op WHERE o.id IS NULL'):
            raise ValueError('added native membership refers to missing op')
        if checked['memberships'] != counts['membership_edges'] + additions or checked['anchors'] != counts['anchor_edges']:
            raise ValueError('native relationship inventory count changed unexpectedly')
        evidence = {'verified_objects': dict(checked), 'member_edges_added': additions,
                    'membership_nodes_changed': scalar('SELECT count(*) FROM changed_pairs'),
                    'op_locations_changed': scalar("SELECT count(*) FROM payload_changes WHERE kind='ops'"),
                    'value_locations_changed': scalar("SELECT count(*) FROM payload_changes WHERE kind='values'"),
                    'physical_payloads_changed': 0, 'existing_members_removed': 0, 'anchor_changes': 0,
                    'boundary_metadata_changes': metadata_changes,
                    'node_identity_changes': 0, 'recheck_scope': 'membership_changed_nodes_only',
                    'reuse_basis': 'every native Node ID/name/parent/anchor and physical op/value payload verified unchanged; existing membership retained; paired boundary anchors unchanged'}
    return evidence


def apply_native_refresh(db, output, previous_coverage):
    coverage = dict(previous_coverage)
    scalar = lambda sql: db.execute(sql).fetchone()[0]
    with db:
        coverage['membership_edges'] += scalar('SELECT count(*) FROM member_additions')
        coverage['unique_covered_ops'] += scalar('''SELECT count(DISTINCT a.op) FROM member_additions a
            WHERE NOT EXISTS(SELECT 1 FROM members m WHERE m.op=a.op)''')
        coverage['shared_ops'] += scalar('''SELECT count(*) FROM (SELECT a.op,count(*) AS added,
            (SELECT count(*) FROM members m WHERE m.op=a.op) AS existing FROM member_additions a GROUP BY a.op)
            WHERE existing<2 AND existing+added>=2''')
        coverage['empty_op_nodes'] -= scalar('''SELECT count(*) FROM changed_pairs c
            WHERE NOT EXISTS(SELECT 1 FROM members m WHERE m.node=c.grh)''')
        write_tsv(output / 'native-member-additions.tsv', ['node_id', 'op_id'],
                  db.execute('SELECT node,op FROM member_additions ORDER BY node,op'))
        write_tsv(output / 'native-location-changes.tsv', ['object_kind', 'id', 'old_loc', 'new_loc'],
                  db.execute('SELECT kind,id,old_loc,new_loc FROM payload_changes ORDER BY kind,id'))
        db.execute('INSERT INTO members SELECT node,op FROM member_additions')
        for kind, table in (('values', 'values_ir'), ('ops', 'ops')):
            db.execute(f'''UPDATE {table} SET payload=(SELECT c.payload FROM payload_changes c
                WHERE c.kind=? AND c.id={table}.id) WHERE id IN
                (SELECT id FROM payload_changes WHERE kind=?)''', (kind, kind))
        db.execute('DELETE FROM results WHERE grh IN (SELECT grh FROM changed_pairs)')
        db.execute('DELETE FROM disconnected_members WHERE node IN (SELECT grh FROM changed_pairs)')
    return coverage


def write_unlocated_details(db, output):
    """Export direct IR evidence for uncovered ops whose producer has no loc."""
    count = 0
    with (output / 'uncovered-ops.tsv').open() as rows, (output / 'unlocated-ops.jsonl').open('w') as stream:
        for item in csv.DictReader(rows, delimiter='\t'):
            if item.get('loc_file') or item.get('loc_pass'):
                continue
            oid = int(item['op_id'])
            row = db.execute('SELECT payload FROM ops WHERE id=?', (oid,)).fetchone()
            if not row:
                raise ValueError(f'uncovered diagnostic references missing native op {oid}')
            operation = json.loads(row[0])
            producers, anchors = [], []
            for vid in operation.get('in', []):
                source_row = db.execute('''SELECT o.id,o.payload FROM producers p
                    JOIN ops o ON o.id=p.op WHERE p.value=?''', (vid,)).fetchone()
                if source_row:
                    producers.append({'value': vid, 'op_id': source_row[0], 'op': json.loads(source_row[1])})
            for vid in set(operation.get('in', []) + operation.get('out', [])):
                anchors.extend({'value': vid, 'node_id': nid, 'name': name}
                    for nid, name in db.execute('''SELECT n.id,n.name FROM anchors a
                        JOIN grh_nodes n ON n.id=a.node WHERE a.value=?''', (vid,)))
            stream.write(json.dumps({'op_id': oid, 'source_class': item['source_class'], 'op': operation,
                'input_producers': producers, 'boundary_anchors': anchors}, separators=(',', ':')) + '\n')
            count += 1
    return count


def emit_report(grh, native, output, db, counts, started, identity, previous=None, refresh=None, native_refresh=None):
    statuses = Counter(dict(db.execute('SELECT status,count(*) FROM results GROUP BY status')))
    reasons = Counter(dict(db.execute('SELECT reason,count(*) FROM results GROUP BY reason')))
    scalar = lambda sql: db.execute(sql).fetchone()[0]
    coverage = dict(previous['grh_op_coverage']) if previous else {'total_ops': counts['grh_ops'],
                'membership_edges': scalar('SELECT count(*) FROM members'),
                'unique_covered_ops': scalar('SELECT count(DISTINCT op) FROM members'),
                'shared_ops': scalar('SELECT count(*) FROM (SELECT op FROM members GROUP BY op HAVING count(*)>1)'),
                'anchor_edges': scalar('SELECT count(*) FROM anchors'),
                'empty_op_nodes': scalar('SELECT count(*) FROM grh_nodes n WHERE NOT EXISTS(SELECT 1 FROM members m WHERE m.node=n.id)')}
    coverage['uncovered_ops'] = coverage['total_ops'] - coverage['unique_covered_ops']
    coverage['covered_fraction'] = coverage['unique_covered_ops'] / coverage['total_ops'] if coverage['total_ops'] else 0
    reused_artifacts = []

    def native_tsv(name, header, rows):
        path = output / name
        may_reuse = native_refresh is None or name == 'grh-node-anchors.tsv'
        if previous and may_reuse and path.is_file() and path.stat().st_size:
            reused_artifacts.append(name)
        else:
            write_tsv(path, header, rows)

    write_tsv(output / 'grh-nodes.tsv', ['node_id', 'qualified_name', 'op_members', 'anchors', 'candidate_gsim_id', 'status', 'reason'],
              db.execute('''SELECT n.id,n.name,(SELECT count(*) FROM members m WHERE m.node=n.id),
                 (SELECT count(*) FROM anchors a WHERE a.node=n.id),coalesce(p.gsim,''),
                 coalesce(r.status,'unpaired'),coalesce(r.reason,'no_unique_qualified_name_candidate')
                 FROM grh_nodes n LEFT JOIN pairs p ON p.grh=n.id LEFT JOIN results r ON r.grh=n.id ORDER BY n.id'''))
    write_tsv(output / 'gsim-nodes.tsv', ['node_id', 'qualified_candidate_name', 'native_name', 'inventory', 'enode_records', 'candidate_grh_id'],
              ((nid, name or '', native_name, inventory,
                sum(len(tree.get('nodes', [])) for tree in json.loads(payload).get('assignTrees', [])), gid or '')
               for nid, name, native_name, inventory, payload, gid in db.execute('''SELECT s.id,s.name,s.native_name,s.inventory,s.payload,p.grh
                  FROM gs_nodes s LEFT JOIN pairs p ON p.gsim=s.id ORDER BY s.id''')))
    write_tsv(output / 'unpaired-grh.tsv', ['node_id', 'qualified_name', 'reason'],
              db.execute('''SELECT n.id,n.name,'no_unique_qualified_name_candidate' FROM grh_nodes n
                            LEFT JOIN pairs p ON p.grh=n.id WHERE p.grh IS NULL ORDER BY n.id'''))
    write_tsv(output / 'unpaired-gsim.tsv', ['node_id', 'qualified_candidate_name', 'native_name', 'inventory', 'reason'],
              ((nid, name or '', native_name, inventory,
                'missing_pipeline_stage_correspondence' if json.loads(payload).get('semantic', {}).get('role') == 'memory-read-address'
                else 'no_unique_qualified_name_candidate')
               for nid, name, native_name, inventory, payload in db.execute('''SELECT s.id,s.name,s.native_name,s.inventory,s.payload
                  FROM gs_nodes s LEFT JOIN pairs p ON p.gsim=s.id WHERE p.gsim IS NULL ORDER BY s.id''')))
    write_tsv(output / 'unverified-or-different.tsv', ['grh_node_id', 'gsim_node_id', 'qualified_name', 'status', 'reason'],
              db.execute('''SELECT r.grh,r.gsim,p.name,r.status,r.reason FROM results r JOIN pairs p ON p.grh=r.grh
                            WHERE r.status NOT IN ('expression_checked','interface_checked','structural_checked') ORDER BY r.grh'''))
    sv_files, source_registry = uncovered_source_registry(grh)
    source_counts = dict.fromkeys(('confirmed_FIRRTL_missing_membership', 'confirmed_SV', 'unknown'), 0)
    reuse_uncovered = previous and native_refresh is None and (output / 'uncovered-ops.tsv').is_file() and (output / 'uncovered-ops.tsv').stat().st_size
    if reuse_uncovered:
        source_counts.update(previous['grh_op_coverage']['uncovered_by_source'])

    def uncovered_rows():
        for oid, payload in db.execute('''SELECT o.id,o.payload FROM ops o
                WHERE NOT EXISTS(SELECT 1 FROM members m WHERE m.op=o.id) ORDER BY o.id'''):
            row = json.loads(payload)
            provenance = uncovered_source(row, sv_files)
            source_counts[provenance] += 1
            location = row.get('loc', {})
            yield oid, row['kind'], provenance, location.get('file', ''), location.get('pass', '')

    native_tsv('uncovered-ops.tsv', ['op_id', 'kind', 'source_class', 'loc_file', 'loc_pass'], uncovered_rows())
    coverage['uncovered_by_source'] = source_counts
    native_tsv('grh-node-members.tsv', ['node_id', 'op_id', 'kind'],
              ((nid, oid, json.loads(payload)['kind']) for nid, oid, payload in db.execute('''
                  SELECT m.node,m.op,o.payload FROM members m JOIN ops o ON o.id=m.op ORDER BY m.node,m.op''')))
    native_tsv('grh-node-anchors.tsv', ['node_id', 'value_id', 'width', 'signed', 'shape', 'domain'],
              ((nid, vid, row.get('w'), row.get('sgn'), json.dumps(row.get('shape', []), separators=(',', ':')),
                row.get('domain', '')) for nid, vid, payload in db.execute('''
                  SELECT a.node,a.value,v.payload FROM anchors a JOIN values_ir v ON v.id=a.value ORDER BY a.node,a.value''')
               for row in (json.loads(payload),)))
    write_tsv(output / 'gsim-derived-types.tsv', ['node_id', 'element_width', 'signed', 'shape', 'evidence'],
              db.execute('SELECT id,width,signed,shape,evidence FROM native_type_evidence ORDER BY id'))
    write_tsv(output / 'grh-disconnected-members.tsv', ['node_id', 'qualified_name', 'op_id', 'kind'],
              db.execute('''SELECT d.node,n.name,d.op,d.kind FROM disconnected_members d
                            JOIN grh_nodes n ON n.id=d.node ORDER BY d.node,d.op'''))
    paired = scalar('SELECT count(*) FROM pairs')
    if paired != counts['grh_nodes']:
        statuses['unpaired'] = counts['grh_nodes'] - paired
    report = {'schema': 'wolvrix.f28.node-comparison.v1', 'complete': True,
              'inputs': {'grh': str(Path(grh).resolve()), 'gsim': str(Path(native).resolve())},
              'input_identity': identity,
              'inventory': dict(counts), 'grh_op_coverage': coverage, 'unique_name_candidates': paired,
              'uncovered_source_evidence': {'capture_summary': source_registry,
                  'registered_sv_files': sorted(sv_files),
                  'policy': 'FIRRTL requires loc.pass=ingest-firrtl or ingest-firrtl-abi; SV requires exact normalized loc.file match with an SV request source; all other uncovered ops remain unknown'},
              'candidate_fraction_of_grh_nodes': paired / counts['grh_nodes'] if counts['grh_nodes'] else 0,
              'checked_fraction_of_grh_nodes': (statuses['expression_checked'] + statuses['interface_checked']) / counts['grh_nodes'] if counts['grh_nodes'] else 0,
              'structurally_checked_fraction_of_grh_nodes': statuses['structural_checked'] / counts['grh_nodes'] if counts['grh_nodes'] else 0,
              'statuses': dict(statuses), 'reasons': dict(reasons),
              'evidence_scope': 'owned combinational subgraphs with corresponding native anchor boundaries as premises; four-state GRH uses structure signatures only',
              'limitations': ['qualified names locate candidates and never establish expression equality',
                              'state, memory, effects, missing assignTrees, partial assignments and unsupported operations stay unverified',
                              'structural_checked checks normalized typed connections only; GRH four-state X/Z semantics are not proved',
                              'canonical expression inequality is not a proof of behavioral inequivalence',
                              'GSIM enode_records count serialized tree occurrences, not unique native ENode pointers'],
              'wall_s': time.perf_counter() - started,
              'maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    if refresh is not None:
        report['candidate_refresh'] = {**refresh, 'reused_native_artifacts': reused_artifacts,
            'native_artifact_reuse_basis': 'same input capture SHA identities, authoritative Node membership and IR inventory unchanged; existing files verified present',
            'previous_candidate_count': previous['unique_name_candidates'],
            'previous_wall_s': previous['wall_s']}
    if native_refresh is not None:
        report['native_inventory_refresh'] = {**native_refresh, 'reused_native_artifacts': reused_artifacts,
            'native_artifact_reuse_basis': 'all native anchor relations and Node identities verified equal; member and uncovered artifacts regenerated from new producer relations',
            'previous_wall_s': previous['wall_s']}
    if refresh is not None or native_refresh is not None:
        report['unlocated_op_diagnostics'] = {'path': str((output / 'unlocated-ops.jsonl').resolve()),
            'count': write_unlocated_details(db, output),
            'scope': 'actual uncovered op payload, input producer payload and native anchor references; no inferred source classification'}
    write_json_atomic(output / 'summary.json', report)
    db.close()
    return report


def compare(grh, gsim_dir, output, budget=10000, reuse_index=False, refresh=False,
            reuse_grh_from=None, expected_added=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    native_files = sorted(Path(gsim_dir).glob('*Init.json'))
    if len(native_files) != 1:
        raise ValueError('expected exactly one actual GSIM Init inventory')
    if refresh and not reuse_index:
        raise ValueError('candidate refresh requires --reuse-index')
    if reuse_grh_from and (reuse_index or refresh):
        raise ValueError('--reuse-grh-from cannot be combined with candidate refresh modes')
    started, native = time.perf_counter(), native_files[0]
    identity = input_identity(grh, native, require_captures=bool(reuse_index or reuse_grh_from))
    previous, refresh_info = None, None
    if reuse_grh_from:
        source_report = Path(reuse_grh_from).resolve()
        raw_previous = source_report.read_bytes()
        original = json.loads(raw_previous)
        if not original.get('complete') or not original.get('input_identity'):
            raise ValueError('native refresh requires a completed report with input capture identities')
        old_identity = input_identity(original['inputs']['grh'], original['inputs']['gsim'], require_captures=True)
        if old_identity != original['input_identity']:
            raise ValueError('old native inputs or capture identities changed since the original report')
        if identity['gsim'] != old_identity['gsim'] or identity['captures']['gsim'] != old_identity['captures']['gsim']:
            raise ValueError('native refresh requires the identical GSIM capture')
        if identity['captures']['grh']['source']['sha256'] != old_identity['captures']['grh']['source']['sha256']:
            raise ValueError('native refresh requires the same FIRRTL content identity')
        if str(Path(grh).resolve()) == original['inputs']['grh'] or output.resolve() == source_report.parent:
            raise ValueError('native refresh must preserve the original GRH dump and comparison directory')
        dbpath = output / 'comparison.sqlite'
        if dbpath.exists():
            raise ValueError('native refresh destination index already exists; refusing to overwrite it')
        if any(output.glob('*.tsv')) or any(output.glob('*.jsonl')):
            raise ValueError('native refresh destination has existing TSV or JSONL artifacts')
        write_json_atomic(output / 'summary.json', {'complete': False, 'phase': 'validating_new_native_inventory',
            'source_report': str(source_report), 'input_identity': identity})
        (output / 'summary-source-before-native-refresh.json').write_bytes(raw_previous)
        subprocess.run(['cp', '--reflink=auto', '--sparse=always',
                        str(source_report.parent / 'comparison.sqlite'), str(dbpath)], check=True)
        db = sqlite3.connect(dbpath)
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('PRAGMA synchronous=OFF')
        db.execute('PRAGMA temp_store=FILE')
        os.environ['SQLITE_TMPDIR'] = str(output.resolve())
        counts = Counter(original['inventory'])
        verification_counts = {**counts, **original['grh_op_coverage']}
        for table, key in (('grh_nodes', 'grh_nodes'), ('values_ir', 'grh_values'), ('ops', 'grh_ops'),
                           ('gs_nodes', 'gsim_total_nodes'), ('members', 'membership_edges'), ('anchors', 'anchor_edges')):
            if db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] != verification_counts[key]:
                raise ValueError(f'source index {table} inventory disagrees with its completed report')
        if db.execute('SELECT count(*) FROM pairs').fetchone()[0] != original['unique_name_candidates'] or \
                db.execute('SELECT count(*) FROM results').fetchone()[0] != original['unique_name_candidates']:
            raise ValueError('source index does not contain all completed candidate results')
        evidence = verify_native_refresh(db, grh, original['inputs']['grh'], verification_counts, expected_added)
        print('[F28] verified native refresh ' + json.dumps(evidence, sort_keys=True), flush=True)
        coverage = apply_native_refresh(db, output, original['grh_op_coverage'])
        evidence['pairs_rechecked'] = check_pairs(db, budget, changed_only=True)
        evidence['source_report'] = {'path': str(source_report), 'sha256': hashlib.sha256(raw_previous).hexdigest()}
        evidence['previous_input_identity'] = old_identity
        previous = {**original, 'grh_op_coverage': coverage}
        anchor_file = source_report.parent / 'grh-node-anchors.tsv'
        if anchor_file.is_file() and anchor_file.stat().st_size:
            shutil.copyfile(anchor_file, output / anchor_file.name)
        return emit_report(grh, native, output, db, counts, started, identity, previous,
                           native_refresh=evidence)
    elif reuse_index:
        summary_path = output / 'summary.json'
        previous = json.loads(summary_path.read_text())
        if not previous.get('complete') or previous.get('inputs') != {
                'grh': str(Path(grh).resolve()), 'gsim': str(native.resolve())}:
            raise ValueError('reuse requires a complete report for the same absolute native inputs')
        if previous.get('input_identity') and previous['input_identity'] != identity:
            raise ValueError('input or capture identity changed since index creation')
        if not previous.get('input_identity'):
            # The first F28 report predates persisted capture identities. Its
            # absolute inputs and unchanged completed capture files bind this
            # one-time adoption; future refreshes require exact identities.
            if any(Path(row['path']).stat().st_mtime_ns > summary_path.stat().st_mtime_ns
                   for row in identity['captures'].values()):
                raise ValueError('capture was modified after the indexed report')
            if any(identity[label]['mtime_ns'] > summary_path.stat().st_mtime_ns for label in ('grh', 'gsim')):
                raise ValueError('native input was modified after the indexed report')
        dbpath = output / 'comparison.sqlite'
        if not dbpath.is_file():
            raise ValueError('reuse requires an existing native comparison index')
        db = sqlite3.connect(dbpath)
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('PRAGMA synchronous=OFF')
        db.execute('PRAGMA temp_store=FILE')
        os.environ['SQLITE_TMPDIR'] = str(output.resolve())
        counts = Counter(previous['inventory'])
        (output / 'summary-before-refresh.json').write_text(json.dumps(previous, indent=2, sort_keys=True) + '\n')
        summary_path.write_text(json.dumps({'complete': False, 'inputs': previous['inputs'],
            'phase': 'refreshing_existing_candidates', 'previous_summary': 'summary-before-refresh.json'}) + '\n')
        if refresh:
            refresh_info = refresh_candidates(db)
            refresh_info['pairs_rechecked'] = check_pairs(db, budget,
                changed_only=refresh_info['recheck_scope'] == 'changed_pairs_only')
            refresh_info['unique_name_candidates'] = db.execute('SELECT count(*) FROM pairs').fetchone()[0]
            print('[F28] candidate refresh ' + json.dumps(refresh_info, sort_keys=True), flush=True)
        else:
            db.execute('DELETE FROM results')
            db.execute('DELETE FROM disconnected_members')
            check_pairs(db, budget)
            refresh_info = {'recheck_scope': 'all_pairs', 'pairs_rechecked': db.execute('SELECT count(*) FROM pairs').fetchone()[0]}
    else:
        db, counts = create_index(Path(grh), native, output)
        print(f'[F28] indexed {counts["grh_nodes"]:,} GRH Nodes, {counts["grh_ops"]:,} ops, '
              f'{counts["gsim_total_nodes"]:,} GSIM Nodes', flush=True)
        check_pairs(db, budget)
    return emit_report(grh, native, output, db, counts, started, identity, previous, refresh_info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, required=True)
    parser.add_argument('--gsim-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-local-steps', type=int, default=10000)
    parser.add_argument('--reuse-index', action='store_true')
    parser.add_argument('--refresh-candidates', action='store_true')
    parser.add_argument('--reuse-grh-from', type=Path)
    parser.add_argument('--expected-added-memberships', type=int)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    if args.max_local_steps < 1:
        parser.error('--max-local-steps must be positive')
    print(json.dumps(compare(args.grh, args.gsim_dir, args.output, args.max_local_steps,
                             args.reuse_index, args.refresh_candidates, args.reuse_grh_from,
                             args.expected_added_memberships), sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
