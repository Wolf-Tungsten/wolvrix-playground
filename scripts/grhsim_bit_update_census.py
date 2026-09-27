"""Measure local one-bit register updates without changing the production IR.

Event-compatible groups are only candidates. Different enables, hidden feedback,
external consumers and vector gathers remain explicit; counts are not speedups.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path
import re

from grhsim_gsim_module_compare import is_generated_value_name, normalize_name
from grhsim_residual_write_cones import (
    checked_fires, fingerprint, SEMANTIC_ARRAYS, source_fingerprints,
    tree_summary, unit_index,
)
from grhsim_dynamic_stats import SN_LINE, TOTALS_LINE
from benchmark_grhsim_ir import digest


def literal_bit(text):
    if str(text) in ('0', '1', "'0", "'1"):
        return int(str(text)[-1])
    match = re.fullmatch(r"1'[sS]?([bBdDhH])([01])", str(text))
    return int(match[2]) if match else None


class BDD:
    """Small reduced ordered decision graph; IDs 0/1 are Boolean constants."""

    def __init__(self, limit=10000):
        self.nodes = [(10**20, 0, 0), (10**20, 1, 1)]
        self.unique, self.cache = {}, {}
        self.limit = limit

    def node(self, var, low, high):
        if low == high:
            return low
        key = (var, low, high)
        if key not in self.unique:
            if len(self.nodes) >= self.limit:
                raise ValueError("bdd_budget")
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def ite(self, cond, yes, no):
        if cond < 2:
            return yes if cond else no
        if yes == no:
            return yes
        if (yes, no) == (1, 0):
            return cond
        key = (cond, yes, no)
        if key in self.cache:
            return self.cache[key]
        var = min(self.nodes[n][0] for n in key)
        children = [self.nodes[n][1:] if self.nodes[n][0] == var else (n, n) for n in key]
        result = self.node(var, self.ite(*(c[0] for c in children)),
                           self.ite(*(c[1] for c in children)))
        self.cache[key] = result
        return result

    def restrict(self, root, var, value):
        cache = {}
        def visit(node):
            if node < 2:
                return node
            if node in cache:
                return cache[node]
            v, low, high = self.nodes[node]
            result = (visit(high if value else low) if v == var else
                      self.node(v, visit(low), visit(high)))
            cache[node] = result
            return result
        return visit(root)

    def evaluate(self, root, values):
        while root > 1:
            var, low, high = self.nodes[root]
            root = high if values[var] else low
        return root


class Model:
    def __init__(self, model):
        self.model, self.strings = model, model['strings']
        self.ops = {op[0]: op for op in model['operations']}
        self.states = {s[0]: s for s in model['states']}
        self.values = {v[0]: v for v in model['values']}
        self.types = {t[0]: t for t in model['types']}
        self.producer, self.users = {}, defaultdict(set)
        self.refs, self.writes = defaultdict(list), defaultdict(list)
        for oid, op in self.ops.items():
            for v in op[5]:
                if v in self.producer:
                    raise ValueError('duplicate value producer')
                self.producer[v] = oid
            for v in op[4]:
                self.users[v].add(oid)
            for kind, obj in op[6]:
                if kind == 'state':
                    self.refs[obj].append(oid)
            if self.kind(oid) == 'core.state.regWrite':
                if not op[6] or op[6][0][0] != 'state' or len(op[4]) < 3:
                    raise ValueError('malformed regWrite')
                self.writes[op[6][0][1]].append(oid)
        self.initial = {}
        init_counts = Counter(record[0] for record in model['init'])
        for sid, steps in model['init']:
            if init_counts[sid] == 1 and len(steps) == 1 and self.text(steps[0][0]) == 'core.init.const':
                params = {self.text(p[0]): p[2] for p in steps[0][1]}
                if set(params) == {'value'}:
                    self.initial[sid] = literal_bit(params['value'])

    def text(self, idx):
        return self.strings[idx - 1] if idx else ''

    def kind(self, oid):
        return self.text(self.ops[oid][1])

    def params(self, oid):
        return {self.text(p[0]): p[2] for p in self.ops[oid][7]}

    def bit_type(self, tid):
        t = self.types[tid]
        return t[2:6] == ['logic', 1, False, '2-state']

    def bit(self, value):
        return self.bit_type(self.values[value][1])

    def width(self, value):
        return self.types[self.values[value][1]][3]

    def local(self, roots):
        """Expand root computations; named intermediates/read/constant are leaves."""
        roots, seen, leaves = set(roots), set(), set()
        stack = sorted(roots)
        while stack:
            v = stack.pop()
            if v not in self.producer:
                raise ValueError(f'value {v} has no producer')
            oid = self.producer[v]
            kind = self.kind(oid)
            name = self.text(self.values[v][2])
            if (not kind.startswith('core.compute.') or kind == 'core.compute.constant' or
                    (v not in roots and not is_generated_value_name(name))):
                leaves.add(v)
                continue
            if oid not in seen:
                seen.add(oid)
                stack.extend(self.ops[oid][4])
        return seen, leaves

    def group_key(self, sid, oid):
        op = self.ops[oid]
        if len(self.writes[sid]) != 1:
            return None, 'multiple_writers'
        if self.initial.get(sid) is None:
            return None, 'target_initial_unknown'
        for other in self.refs[sid]:
            if other == oid:
                continue
            read = self.ops[other]
            if (self.kind(other) != 'core.state.read' or read[6] != [['state', sid]] or
                    read[4] or len(read[5]) != 1 or read[7] or not self.bit(read[5][0])):
                return None, 'non_read_target_reference'
        args, refs, params = op[4], op[6], self.params(oid)
        edges = params.get('event_edges')
        if (set(params) != {'event_edges'} or not isinstance(edges, list) or not edges or
                len(args) != 3 + len(edges) or len(refs) != 1 + len(edges) or op[5] or
                any(e not in ('posedge', 'negedge') for e in edges) or
                any(not self.bit(v) for v in args)):
            return None, 'unsupported_write'
        histories = []
        for kind, hist in refs[1:]:
            if (kind != 'state' or self.refs[hist] != [oid] or
                    not self.bit_type(self.states[hist][2]) or self.initial.get(hist) is None):
                return None, 'nonprivate_or_unknown_history'
            histories.append(self.initial[hist])
        return (tuple(args[3:]), tuple(edges), tuple(histories), self.initial[sid]), 'eligible'

    def hidden_feedback(self, roots, sid, budget=4096):
        """Conservative check: an opaque leaf must be independent of old state."""
        seen, stack = set(), sorted(roots)
        while stack:
            v = stack.pop()
            if v in seen:
                continue
            if len(seen) >= budget:
                return 'feedback_check_budget'
            seen.add(v)
            op = self.ops[self.producer[v]]
            if ['state', sid] in op[6]:
                return 'hidden_feedback'
            stack.extend(op[4])
        return None

    def proof(self, sid, oid, local):
        bdd, atoms, opaque, memo = BDD(), set(), set(), {}
        q = bdd.node(0, 0, 1)
        def calc(v):
            if v in memo:
                return memo[v]
            if not self.bit(v):
                raise ValueError('non_boolean_value')
            pid = self.producer[v]
            op, kind = self.ops[pid], self.kind(pid).removeprefix('core.compute.')
            if self.kind(pid) == 'core.state.read' and op[6] == [['state', sid]]:
                result = q
            elif kind == 'constant' and literal_bit(self.params(pid).get('constValue')) is not None:
                result = literal_bit(self.params(pid)['constValue'])
            elif (pid in local and not op[6] and not op[7] and
                  kind in {'and', 'or', 'xor', 'not', 'logicNot', 'mux', 'bitSelect', 'eq', 'ne', 'assign'} and
                  len(op[4]) == {'not': 1, 'logicNot': 1, 'assign': 1, 'mux': 3, 'bitSelect': 3}.get(kind, 2) and
                  all(self.bit(a) for a in op[4])):
                vals = [calc(a) for a in op[4]]
                if kind in ('not', 'logicNot'):
                    result = bdd.ite(vals[0], 0, 1)
                elif kind == 'assign':
                    result = vals[0]
                elif kind == 'and':
                    result = bdd.ite(vals[0], vals[1], 0)
                elif kind == 'or':
                    result = bdd.ite(vals[0], 1, vals[1])
                elif kind in ('xor', 'ne', 'eq'):
                    result = bdd.ite(vals[0], bdd.ite(vals[1], 0, 1), vals[1])
                    if kind == 'eq':
                        result = bdd.ite(result, 0, 1)
                else:
                    result = bdd.ite(*vals)
            else:
                atoms.add(v)
                opaque.add(v)
                if len(atoms) > 24:
                    raise ValueError('atom_budget')
                result = bdd.node(v, 0, 1)
            memo[v] = result
            return result
        try:
            en, data, mask = [calc(v) for v in self.ops[oid][4][:3]]
            feedback = self.hidden_feedback(opaque, sid)
            if feedback:
                return {'status': feedback, 'atoms': len(atoms)}
            f = bdd.ite(bdd.ite(en, mask, 0), data, q)
            low, high = bdd.restrict(f, 0, 0), bdd.restrict(f, 0, 1)
            monotone = bdd.ite(low, bdd.ite(high, 0, 1), 0) == 0
            # Independent opaque inputs overapproximate the reachable inputs.
            # A monotonicity proof is sound; a toggle witness may be unreachable.
            status = 'old_independent' if low == high else ('set_clear_hold' if monotone else 'may_toggle')
            return {'status': status, 'atoms': len(atoms), 'bdd_nodes': len(bdd.nodes) - 2,
                    'enable_mask_redundant': f == data, 'always_hold': f == q}
        except ValueError as error:
            if str(error) not in {'atom_budget', 'bdd_budget', 'non_boolean_value'}:
                raise
            return {'status': str(error), 'atoms': len(atoms)}

    def sample(self, sid, oid, local, leaves, proof):
        def value(v):
            op = self.ops[self.producer[v]]
            return {'id': v, 'name': self.text(self.values[v][2]), 'width': self.width(v),
                    'kind': self.kind(op[0]), 'params': self.params(op[0]),
                    'states': [self.text(self.states[x][1]) for k, x in op[6] if k == 'state']}
        return {'state': self.text(self.states[sid][1]), 'writer': oid,
                'roots_enable_data_mask': self.ops[oid][4][:3], 'proof': proof,
                'operations': [{'id': o, 'kind': self.kind(o), 'args': self.ops[o][4],
                                'results': self.ops[o][5], 'params': self.params(o)} for o in sorted(local)],
                'leaves': [value(v) for v in sorted(leaves)]}


def exclusive_ops(view, local, sinks):
    """Keep an op if any result escapes; propagate that need towards its inputs."""
    external = local | sinks
    event_inputs = {v for sink in sinks for v in view.ops[sink][4][3:]}
    retained = {o for o in local if any(view.users[v] - external or v in event_inputs
                                       for v in view.ops[o][5])}
    stack = list(retained)
    while stack:
        o = stack.pop()
        for v in view.ops[o][4]:
            p = view.producer[v]
            if p in local and p not in retained:
                retained.add(p)
                stack.append(p)
    return local - retained


def analyze(model, fires, cycles):
    if cycles <= 0:
        raise ValueError('cycles must be positive')
    view = Model(model)
    units, owners = unit_index(model)
    if units != set(fires):
        raise ValueError('body-counter coverage mismatch')
    execs = {o: fires[u] for o, u in owners.items()}
    def price(ops):
        if ops - execs.keys():
            raise ValueError('local op lacks compute owner')
        return sum(execs[o] for o in ops)
    groups, coverage, candidates = defaultdict(list), Counter(), []
    schedule = model['mappings'][0][-1][4]
    def projected(sid):
        if len(schedule) <= 8 or sid >= schedule[7]:
            return None
        return bool((schedule[8][sid // 64] >> (sid % 64)) & 1)
    for sid, writers in sorted(view.writes.items()):
        if not view.bit_type(view.states[sid][2]):
            continue
        for oid in writers:
            coverage['bit_writers'] += 1
            key, reason = view.group_key(sid, oid)
            coverage[reason] += 1
            if key is not None:
                local, leaves = view.local(view.ops[oid][4][:3])
                row = (sid, oid, local, leaves, view.proof(sid, oid, local))
                groups[key].append(row)
                candidates.append(row)
    all_local, all_sinks = set(), set()
    reports = []
    for key, rows in sorted(groups.items()):
        local = set().union(*(r[2] for r in rows))
        sinks = {r[1] for r in rows}
        exclusive = exclusive_ops(view, local, sinks)
        all_local.update(local)
        all_sinks.update(sinks)
        controls = Counter(tuple(view.ops[r[1]][4][i] for i in (0, 2)) for r in rows)
        projection_counts = Counter(str(projected(r[0])) for r in rows)
        names = [view.text(view.states[r[0]][1]) for r in rows]
        families = Counter(re.sub(r'_\d+$', '', n) for n in names)
        rows.sort(key=lambda r: (-price(r[2]), view.text(view.states[r[0]][1])))
        sid, oid, one, leaves, proof = rows[0]
        reports.append({'events': list(key[0]), 'edges': list(key[1]), 'history_initial': list(key[2]),
                        'target_initial': key[3], 'rows': len(rows), 'local_ops': len(local),
                        'local_execs': price(local), 'exclusive_ops': len(exclusive),
                        'exclusive_execs': price(exclusive), 'control_groups': len(controls),
                        'shared_control_rows': sum(n for n in controls.values() if n > 1),
                        'max_shared_control_rows': max(controls.values()),
                        'projection_counts': dict(sorted(projection_counts.items())),
                        'controls_with_projection': len({(tuple(view.ops[r[1]][4][i] for i in (0, 2)),
                                                         projected(r[0])) for r in rows}),
                        'proof_counts': dict(sorted(Counter(r[4]['status'] for r in rows).items())),
                        'redundant_enable_mask_rows': sum(r[4].get('enable_mask_redundant', False) for r in rows),
                        'families': dict(sorted(families.items())),
                        'kind_execs': dict(sorted((k, sum(execs[o] for o in local if view.kind(o) == k))
                                                  for k in {view.kind(o) for o in local})),
                        'sample': view.sample(sid, oid, one, leaves, proof)})
    reports.sort(key=lambda r: (-r['local_execs'], r['events'], r['edges'], r['target_initial']))
    # The global closure can remove shared-between-groups computation as well.
    exclusive = exclusive_ops(view, all_local, all_sinks)
    family_sets, family_sinks, family_rows = defaultdict(set), defaultdict(set), Counter()
    for sid, oid, local, _, _ in candidates:
        key = re.sub(r'_\d+$', '', view.text(view.states[sid][1]))
        family_sets[key].update(local)
        family_sinks[key].add(oid)
        family_rows[key] += 1
    family_report = [{'family': k, 'rows': family_rows[k], 'local_ops': len(v),
                      'local_execs': price(v), 'exclusive_execs': price(exclusive_ops(view, v, family_sinks[k]))}
                     for k, v in family_sets.items()]
    family_report.sort(key=lambda r: (-r['local_execs'], r['family']))
    coverage_ok = coverage['bit_writers'] == sum(v for k, v in coverage.items() if k != 'bit_writers')
    if not coverage_ok or not price(exclusive) <= price(all_local) <= sum(r['local_execs'] for r in reports):
        raise ValueError('coverage/exclusivity closure failed')
    return {'cycles': cycles, 'coverage': dict(sorted(coverage.items())),
            'compute_units': len(units), 'compute_ops': len(owners), 'compute_execs': sum(execs.values()),
            'local_ops': len(all_local), 'local_execs': price(all_local),
            'exclusive_ops': len(exclusive), 'exclusive_execs': price(exclusive),
            'sum_group_execs': sum(r['local_execs'] for r in reports), 'group_count': len(reports),
            'proof_counts': dict(sorted(Counter(r[4]['status'] for r in candidates).items())),
            'groups': reports, 'families': family_report}


def counter_sites(directory):
    groups, publishes = Counter(), Counter()
    for path in sorted(Path(directory).glob('*.cpp')):
        text = path.read_text()
        groups.update(int(x) for x in re.findall(r'\+\+\s*cpu_dyn_sn_grp\[(\d+)\]\s*;', text))
        publishes.update(int(x) for x in re.findall(
            r'cpu_dyn_sn_chg\[(\d+)\]\+=cpu_dyn_any;\s*\+\+\s*cpu_dyn_grp_pub\s*;', text))
    if not groups or not publishes or publishes.keys() - groups.keys():
        raise ValueError('missing/inconsistent dynamic counter sites')
    return groups, publishes


def check_dynamic(model, first_path, second_path, source_dir):
    first, cycles = checked_fires(first_path)
    second, other_cycles = checked_fires(second_path)
    if first != second or cycles != other_cycles:
        raise ValueError('independent dynamic counters differ')
    groups, publishes = counter_sites(source_dir)
    checks = []
    for path in (first_path, second_path):
        rows, totals = {}, None
        for line in Path(path).read_text().splitlines():
            if match := SN_LINE.fullmatch(line):
                rows[int(match[1])] = tuple(map(int, match.groups()[1:]))
            if match := TOTALS_LINE.fullmatch(line):
                if totals is not None:
                    raise ValueError('duplicate runtime totals')
                totals = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', match[1])}
        if totals is None:
            raise ValueError('missing runtime totals')
        if set(groups) != set(rows) or any(rows[u][2] != first[u] * groups[u] for u in rows):
            raise ValueError('runtime group-call counter closure failed')
        if sum(first[u] * n for u, n in publishes.items()) != totals['grp_pub']:
            raise ValueError('runtime group-publish counter closure failed')
        if sum(row[3] for row in rows.values()) != totals['grp_fire']:
            raise ValueError('runtime group-fire counter closure failed')
        checks.append({k: totals[k] for k in ('grp_pub', 'grp_fire')})
    if checks[0] != checks[1]:
        raise ValueError('independent runtime totals differ')
    units, owners = unit_index(model)
    if set(first) != units:
        raise ValueError('body-counter coverage mismatch')
    # Independent per-partition subtree accounting, as in grhsim_dynamic_stats.
    parts = {p[0]: p for p in model['mappings'][0][-1][2]}
    total = 0
    for u, count in first.items():
        stack, seen = [u], set()
        while stack:
            p = parts[stack.pop()]
            if p[0] in seen:
                raise ValueError('duplicate subtree partition')
            seen.add(p[0])
            stack.extend(p[4])
            total += len(p[5]) * count
    if total != sum(first[u] for u in owners.values()):
        raise ValueError('compute execution closure failed')
    return first, cycles, {'compute_execs': total, 'group_totals': checks[0],
                           'group_calls': sum(first[u] * n for u, n in groups.items()),
                           'groups_without_published_values': sum(groups.values()) - sum(publishes.values()),
                           'independent_runs_equal': True}


def compare_identity(args):
    print('Checking production checkpoint and source identity', flush=True)
    final = json.loads(args.final.read_bytes())
    expected = {k: fingerprint(final, k) for k in SEMANTIC_ARRAYS}
    final_strings = final['strings']
    final_digest = digest(args.final)
    results = {}
    del final
    gc.collect()
    for label, path in (('parent', args.parent), ('pre', args.pre), ('dynamic', args.dynamic)):
        if label != 'pre':
            if digest(path) != final_digest:
                raise ValueError(f'{label} production checkpoint bytes differ')
            results[label] = {'checkpoint_bytes_equal': True}
        else:
            model = json.loads(path.read_bytes())
            bad = [k for k in sorted(expected) if fingerprint(model, k) != expected[k]]
            if bad:
                raise ValueError(f'{label} checkpoint changed: {bad}')
            # Mapping/emission may intern new strings; all referenced pre-pass
            # strings must remain at the same indices, exactly as in NO00023.
            n = len(model['strings'])
            if model['strings'] != final_strings[:n]:
                raise ValueError('pre/final referenced strings differ')
            results[label] = {'equal_sections': sorted(expected),
                              'backend_appended_strings': len(final_strings) - n}
            del model
            gc.collect()
    if source_fingerprints(args.final.parent / 'model') != source_fingerprints(args.parent.parent / 'model'):
        raise ValueError('production generated sources changed')
    results['production_sources_equal'] = True
    return results


def gsim_details(path, analysis):
    wanted = [r['sample']['state'] for r in analysis['groups'][:3]]
    payload = json.loads(path.read_bytes())
    nodes = payload['nodes']
    normalized = defaultdict(list)
    wanted_keys = {normalize_name(n) for n in wanted}
    for node in nodes:
        if node['type'] == 'NODE_REG_SRC' and normalize_name(node['name']) in wanted_keys:
            normalized[normalize_name(node['name'])].append(node)
    details = []
    for state in wanted:
        srcs = normalized[normalize_name(state)]
        if len(srcs) != 1 or srcs[0].get('width') != 1:
            details.append({'state': state, 'status': 'ambiguous_or_missing_name_width'})
            continue
        src = srcs[0]
        refs = tree_summary(src.get('assignTrees') or [])['refs']
        refs = [n for n in refs if n != src['name']]
        if len(refs) != 1:
            details.append({'state': state, 'status': 'ambiguous_destination'})
            continue
        wanted_names, found = set(refs), {}
        for depth in range(4):
            next_names = set()
            for node in nodes:
                name = node['name']
                if name not in wanted_names or name in found:
                    continue
                tree = tree_summary(node.get('assignTrees') or [])
                found[name] = {'name': name, 'type': node['type'], 'width': node.get('width'),
                               'layer': depth, 'summary': tree,
                               'assignTrees': node.get('assignTrees') or []}
                if node['type'] not in {'NODE_REG_SRC', 'NODE_INP', 'NODE_MEMORY'}:
                    next_names.update(tree['refs'])
            if wanted_names - found.keys():
                raise ValueError('missing gsim named reference')
            wanted_names = next_names - found.keys()
        details.append({'state': state, 'status': 'matched', 'source': src['name'], 'destination': refs[0],
                        'nodes': [found[n] for n in sorted(found)], 'frontier': sorted(wanted_names)})
    return details


def render(report):
    a = report['analysis']
    lines = ['# One-bit update census', '', f"Coverage: {a['coverage']}",
             f"Local/exclusive execs per cycle: {a['local_execs']/a['cycles']:.6f} / "
             f"{a['exclusive_execs']/a['cycles']:.6f}", '',
             '| Group | Rows | Controls | Local execs/cycle | Exclusive execs/cycle | Proofs |',
             '|---|---:|---:|---:|---:|---|']
    for i, row in enumerate(a['groups'][:10], 1):
        lines.append(f"| {i} | {row['rows']} | {row['control_groups']} | "
                     f"{row['local_execs']/a['cycles']:.6f} | {row['exclusive_execs']/a['cycles']:.6f} | "
                     f"{row['proof_counts']} |")
    lines += ['', '| Family | Rows | Local execs/cycle | Exclusive execs/cycle |',
              '|---|---:|---:|---:|']
    for row in a['families'][:20]:
        lines.append(f"| {row['family']} | {row['rows']} | {row['local_execs']/a['cycles']:.6f} | "
                     f"{row['exclusive_execs']/a['cycles']:.6f} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pre', 'final', 'parent', 'dynamic', 'run1', 'run2', 'gsim', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1] / 'ptmp'):
        parser.error('output must be under repository ptmp')
    identity = compare_identity(args)
    print('Analyzing bit updates and dynamic ownership', flush=True)
    model = json.loads(args.dynamic.read_bytes())
    fires, cycles, dynamic = check_dynamic(model, args.run1, args.run2, args.dynamic.parent / 'model')
    analysis = analyze(model, fires, cycles)
    del model
    gc.collect()
    print('Expanding matched gsim expressions', flush=True)
    details = gsim_details(args.gsim, analysis)
    report = {'identity': identity, 'dynamic': dynamic, 'analysis': analysis, 'gsim': details}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (args.output / 'summary.md').write_text(render(report))
    print(render(report), flush=True)


if __name__ == '__main__':
    main()
