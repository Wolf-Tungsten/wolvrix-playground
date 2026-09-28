"""Prove register-data selections under their unchanged write enable (NO00028).

Read-only, pre-partition opportunity census. It substitutes only write-data
uses in a virtual graph; it never changes the model or assumes reachable inputs.
BDD implication and independently evaluated exhaustive truth vectors must agree.
Reference-count deletion and whole-graph reachability must find the same newly
dead compute operations. Dynamic prices are deduplicated measured body counts,
not estimates of host instructions or predicted speedups.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, deque
import csv
import gc
import json
from pathlib import Path

from benchmark_grhsim_ir import digest
from grhsim_bit_update_census import BDD, check_dynamic
from grhsim_paired_cone_diff import dynamic_identity, full_counts_check, parse_const_literal
from grhsim_residual_write_cones import semantic_fingerprints, source_fingerprints, unit_index
from grhsim_vchg_profile import closure_check, parse_kinds, parse_sn, parse_vchg


class Refused(ValueError):
    """Unsupported or over-budget proof; never a positive result."""


class View:
    def __init__(self, model):
        self.model = model
        self.strings = model['strings']
        self.ops = [None] + model['operations']
        self.values = [None] + model['values']
        self.types = {t[0]: t for t in model['types']}
        self.states = {s[0]: s for s in model['states']}
        self.producer = array('I', [0]) * len(self.values)
        for oid, op in enumerate(self.ops[1:], 1):
            if op[0] != oid:
                raise ValueError('operations must have dense IDs')
            for value in op[5]:
                if not 0 < value < len(self.values) or self.producer[value]:
                    raise ValueError('invalid or duplicate value definition')
                self.producer[value] = oid
        if any(v[0] != i for i, v in enumerate(self.values[1:], 1)):
            raise ValueError('values must have dense IDs')

    def text(self, sid):
        return self.strings[sid - 1] if sid else ''

    def kind(self, op):
        return self.text(op[1])

    def params(self, op):
        entries = op[7]
        result = {self.text(p[0]): p[2] for p in entries}
        if len(result) != len(entries):
            raise Refused('duplicate_parameters')
        return result

    def type(self, value):
        return self.types[self.values[value][1]]

    def bit(self, value):
        return self.type(value)[2:6] == ['logic', 1, False, '2-state']

    def pure(self, oid):
        op = self.ops[oid]
        return (self.kind(op).startswith('core.compute.') and
                self.kind(op) != 'core.compute.constant' and not op[6] and
                len(op[5]) == 1)

    def valid_write(self, op):
        args, refs = op[4], op[6]
        if len(args) < 4 or len(refs) != len(args) - 2 or op[5]:
            raise Refused('write_shape')
        params = self.params(op)
        edges = params.get('event_edges')
        if (set(params) != {'event_edges'} or not isinstance(edges, list) or
                len(edges) != len(args) - 3 or
                any(edge not in ('posedge', 'negedge') for edge in edges)):
            raise Refused('write_events')
        if any(kind != 'state' or sid not in self.states for kind, sid in refs):
            raise Refused('write_references')
        target = self.types[self.states[refs[0][1]][2]]
        if (target[2] != 'logic' or target[3] <= 0 or target[5] != '2-state' or
                self.values[args[1]][1] != target[0] or
                self.values[args[2]][1] != target[0] or
                not self.bit(args[0]) or not all(self.bit(v) for v in args[3:]) or
                any(self.types[self.states[sid][2]][2:6] !=
                    ['logic', 1, False, '2-state'] for _, sid in refs[1:])):
            raise Refused('write_types')

    def selection(self, value):
        oid = self.producer[value]
        if not oid:
            raise Refused('missing_producer')
        op = self.ops[oid]
        kind = self.kind(op).removeprefix('core.compute.')
        if kind not in ('mux', 'bitSelect', 'prioritySelect'):
            return None
        args = op[4]
        if op[6] or op[7] or op[5] != [value]:
            raise Refused('select_shape')
        if kind in ('mux', 'bitSelect'):
            if len(args) != 3 or not self.bit(args[0]):
                raise Refused('select_condition')
            if kind == 'bitSelect' and not self.bit(value):
                raise Refused('wide_bit_select')
            conds, branches = args[:1], args[1:]
        else:
            if len(args) < 3 or len(args) % 2 != 1:
                raise Refused('priority_shape')
            count = (len(args) - 1) // 2
            conds, branches = args[:count], args[count:]
            if not all(self.bit(v) for v in conds):
                raise Refused('select_condition')
        typ = self.type(value)
        if (typ[2] != 'logic' or typ[5] != '2-state' or typ[3] <= 0 or
                any(self.values[v][1] != typ[0] for v in branches)):
            raise Refused('select_types')
        return oid, tuple(conds), tuple(branches)


class BooleanProof:
    """A bounded Boolean expression DAG and its reduced decision graph."""

    ARITIES = {'assign': 1, 'not': 1, 'logicNot': 1, 'and': 2, 'or': 2,
               'xor': 2, 'logicAnd': 2, 'logicOr': 2, 'eq': 2, 'ne': 2,
               'mux': 3, 'bitSelect': 3}

    def __init__(self, view, atoms_limit=12, values_limit=256, nodes_limit=4096, cutpoints=()):
        self.view = view
        self.bdd = BDD(nodes_limit)
        self.atoms_limit, self.values_limit = atoms_limit, values_limit
        self.expr, self.nodes, self.atoms, self.visiting = {}, {}, set(), set()
        self.cutpoints = set(cutpoints)

    def compile(self, value):
        if value in self.nodes:
            return self.nodes[value]
        if value in self.visiting:
            raise Refused('boolean_cycle')
        if len(self.expr) + len(self.visiting) >= self.values_limit:
            raise Refused('value_budget')
        if not self.view.bit(value):
            raise Refused('non_boolean')
        self.visiting.add(value)
        oid = self.view.producer[value]
        if not oid:
            raise Refused('missing_producer')
        op = self.view.ops[oid]
        name = self.view.kind(op).removeprefix('core.compute.')
        args = tuple(op[4])
        if name == 'constant':
            params = self.view.params(op)
            literal = params.get('constValue', params.get('value'))
            parsed = parse_const_literal(literal, 1)
            if (op[4] or op[6] or op[5] != [value] or len(params) != 1 or
                    parsed is None or parsed[1] != 1):
                raise Refused('unknown_constant')
            desc = ('constant', parsed[0])
            node = parsed[0]
        elif (value not in self.cutpoints and
              name in self.ARITIES and len(args) == self.ARITIES[name] and
              not op[6] and not op[7] and op[5] == [value] and
              all(self.view.bit(v) for v in args)):
            vals = [self.compile(v) for v in args]
            desc = (name, args)
            ite = self.bdd.ite
            if name == 'assign':
                node = vals[0]
            elif name in ('not', 'logicNot'):
                node = ite(vals[0], 0, 1)
            elif name in ('and', 'logicAnd'):
                node = ite(vals[0], vals[1], 0)
            elif name in ('or', 'logicOr'):
                node = ite(vals[0], 1, vals[1])
            elif name in ('xor', 'ne', 'eq'):
                node = ite(vals[0], ite(vals[1], 0, 1), vals[1])
                if name == 'eq':
                    node = ite(node, 0, 1)
            else:
                node = ite(*vals)
        else:
            self.atoms.add(value)
            if len(self.atoms) > self.atoms_limit:
                raise Refused('atom_budget')
            desc = ('atom', value)
            node = self.bdd.node(value, 0, 1)
        self.visiting.remove(value)
        self.expr[value], self.nodes[value] = desc, node
        return node

    def implied(self, enable, condition):
        e, c = self.compile(enable), self.compile(condition)
        if self.bdd.ite(e, c, 1) == 1:
            return True
        if self.bdd.ite(e, c, 0) == 0:
            return False
        return None

    def independent_vectors(self):
        """Enumerate all atom assignments as bit vectors, without using the BDD."""
        atoms = sorted(self.atoms)
        count = 1 << len(atoms)
        mask = (1 << count) - 1
        variables = {value: sum(1 << row for row in range(count) if row & (1 << i))
                     for i, value in enumerate(atoms)}
        result = {}
        # Compile inserts an expression only after its children: independent
        # truth algebra can evaluate this order without BDD reduction rules.
        for value, (kind, args) in self.expr.items():
            if kind == 'atom':
                bits = variables[value]
            elif kind == 'constant':
                bits = mask if args else 0
            else:
                vals = [result[v] for v in args]
                if kind == 'assign':
                    bits = vals[0]
                elif kind in ('not', 'logicNot'):
                    bits = mask ^ vals[0]
                elif kind in ('and', 'logicAnd'):
                    bits = vals[0] & vals[1]
                elif kind in ('or', 'logicOr'):
                    bits = vals[0] | vals[1]
                elif kind in ('xor', 'ne'):
                    bits = vals[0] ^ vals[1]
                elif kind == 'eq':
                    bits = mask ^ vals[0] ^ vals[1]
                else:
                    bits = (vals[0] & vals[1]) | ((mask ^ vals[0]) & vals[2])
            result[value] = bits
        return result, count, mask


def verify_selection(proof, enable, selection, selected, decisions):
    """Prove equality for arbitrary data, masks, old state and event histories."""
    vectors, assignments, mask = proof.independent_vectors()
    active = vectors[enable]
    if not active:
        raise ValueError('BDD/truth-vector disagreement: vacuous proof')
    for cond, answer in decisions:
        wrong = (mask ^ vectors[cond]) if answer else vectors[cond]
        if active & wrong:
            raise ValueError('BDD/truth-vector disagreement: implication')
    # Evaluate the full original selector, giving distinct labels to data
    # branches. Enabled rows must choose the exact same existing value.
    _, conds, branches = selection
    unresolved, chosen = mask, {}
    for cond, branch in zip(conds, branches):
        if cond not in vectors:
            if unresolved & active:
                raise ValueError('unverified reachable priority condition')
            break
        selected_rows = unresolved & vectors[cond]
        chosen[branch] = chosen.get(branch, 0) | selected_rows
        unresolved &= mask ^ vectors[cond]
    chosen[branches[-1]] = chosen.get(branches[-1], 0) | unresolved
    if active & (mask ^ chosen.get(selected, 0)):
        raise ValueError('original selector differs under write enable')
    return {'atoms': len(proof.atoms), 'assignments': assignments,
            'active_assignments': active.bit_count()}


def known_boolean_constant(view, value):
    """Distinguish context-free simplification even when the proof used cuts."""
    try:
        node = BooleanProof(view).compile(value)
        return node if node < 2 else None
    except (Refused, RecursionError):
        return None
    except ValueError as error:
        if str(error) != 'bdd_budget':
            raise
        return None


def choose(view, enable, selection):
    """Try shared condition values as abstract leaves, then bounded expansion.

    Cutting a complex condition is sound: all assignments of the abstraction
    include all assignments of the real circuit. It avoids missing E=>E solely
    because the cone defining E is large. Neither mode uses dynamic observations.
    """
    _, conds, branches = selection
    failure = 'unproved_condition'
    for mode, cutpoints in (('condition_leaves', conds), ('expanded', ())):
        proof = BooleanProof(view, cutpoints=cutpoints)
        try:
            e = proof.compile(enable)
            if e == 0:
                return None, 'constant_false_enable'
            if e == 1:
                return None, 'constant_true_enable'
            decisions = []
            selected = branches[-1]
            for i, cond in enumerate(conds):
                answer = proof.implied(enable, cond)
                if answer is None:
                    selected = None
                    break
                decisions.append((cond, answer))
                if answer:
                    selected = branches[i]
                    break
            if selected is not None:
                verified = verify_selection(proof, enable, selection, selected, decisions)
                constant_enable = known_boolean_constant(view, enable)
                if constant_enable is not None:
                    return None, 'constant_true_enable' if constant_enable else 'constant_false_enable'
                if all(known_boolean_constant(view, condition) == int(answer)
                       for condition, answer in decisions):
                    return None, 'unconditional_selection'
                return {'selected': selected, 'decisions': decisions, 'proof_mode': mode,
                        **verified}, 'proven'
        except (Refused, RecursionError) as error:
            failure = str(error) if isinstance(error, Refused) else 'recursion_budget'
        except ValueError as error:
            if str(error) != 'bdd_budget':
                raise
            failure = 'bdd_budget'
    return None, failure


def prove_write(view, op):
    view.valid_write(op)
    enable, original = op[4][:2]
    if view.selection(original) is None:
        return None, 'no_root_selection'
    value, chain, seen = original, [], set()
    stop = 'non_selection_leaf'
    while selection := view.selection(value):
        if value in seen:
            raise Refused('data_cycle')
        if len(seen) >= 64:
            raise Refused('chain_budget')
        seen.add(value)
        result, stop = choose(view, enable, selection)
        if result is None:
            break
        chain.append({'op': selection[0], 'value': value, **result})
        value = result['selected']
        stop = 'non_selection_leaf'
    if not chain:
        return None, stop
    return {'write': op[0], 'state': op[6][0][1], 'enable': enable,
            'original': original, 'replacement': value, 'chain': chain,
            'atoms': max(s['atoms'] for s in chain),
            'assignments': sum(s['assignments'] for s in chain),
            'active_assignments': sum(s['active_assignments'] for s in chain),
            'stop': stop}, 'proven'


def reachable(view, replacements):
    """Whole-graph reference implementation: treat every non-compute op as root."""
    live = bytearray(len(view.ops))
    stack = []
    for op in view.ops[1:]:
        if not view.pure(op[0]):
            live[op[0]] = 1
            for i, value in enumerate(op[4]):
                if i == 1 and op[0] in replacements:
                    value = replacements[op[0]]
                stack.append(view.producer[value])
    while stack:
        oid = stack.pop()
        if oid == 0:
            raise ValueError('operand without producer')
        if live[oid]:
            continue
        live[oid] = 1
        stack.extend(view.producer[v] for v in view.ops[oid][4])
    return live


def dead_candidates(view, proofs):
    replacements = {p['write']: p['replacement'] for p in proofs}
    before = reachable(view, {})
    refs = array('I', [0]) * len(view.values)
    for op in view.ops[1:]:
        if before[op[0]]:
            for value in op[4]:
                refs[value] += 1
    changed = []
    for proof in proofs:
        old, new = proof['original'], proof['replacement']
        refs[old] -= 1
        refs[new] += 1
        changed.append(old)
    queue = deque(view.producer[v] for v in changed if refs[v] == 0)
    dead = set()
    while queue:
        oid = queue.popleft()
        if oid in dead or not before[oid] or not view.pure(oid):
            continue
        op = view.ops[oid]
        if any(refs[v] for v in op[5]):
            continue
        dead.add(oid)
        for value in op[4]:
            refs[value] -= 1
            if not refs[value]:
                queue.append(view.producer[value])
    after = reachable(view, replacements)
    independent = {oid for oid in range(1, len(view.ops)) if before[oid] and not after[oid]}
    if dead != independent:
        raise ValueError('reference counts disagree with whole-graph reachability')
    return dead, sum(not before[oid] and view.pure(oid) for oid in range(1, len(view.ops)))


def describe(view, value, depth=3):
    op = view.ops[view.producer[value]]
    kind = view.kind(op).removeprefix('core.compute.')
    result = {'value': value, 'kind': kind, 'width': view.type(value)[3]}
    name = view.text(view.values[value][2])
    if name:
        result['name'] = name
    if op[7]:
        result['parameters'] = view.params(op)
    if op[6]:
        result['refs'] = op[6]
    if depth and op[4]:
        result['operands'] = [describe(view, v, depth - 1) for v in op[4]]
    return result


def census(model, fires, vchg):
    view = View(model)
    units, owners = unit_index(model)
    if units != set(fires):
        raise ValueError('compute unit coverage mismatch')
    statuses, proofs, status_roots = Counter(), [], {}
    for op in view.ops[1:]:
        if view.kind(op) != 'core.state.regWrite':
            continue
        try:
            proof, status = prove_write(view, op)
        except (Refused, RecursionError) as error:
            proof, status = None, str(error) if isinstance(error, Refused) else 'recursion_budget'
        except ValueError as error:
            if str(error) != 'bdd_budget':
                raise
            proof, status = None, 'bdd_budget'
        statuses[status] += 1
        if len(op[4]) > 1:
            root = view.producer[op[4][1]]
            if root in owners:
                status_roots.setdefault(status, set()).add(root)
        if proof is not None:
            proofs.append(proof)
    dead, prior_dead = dead_candidates(view, proofs)
    if dead - owners.keys():
        raise ValueError('dead op missing compute owner')
    compute_execs = sum(fires[u] for u in owners.values())
    dead_values = {v for oid in dead for v in view.ops[oid][5]}
    selected = {step['op'] for proof in proofs for step in proof['chain']}
    if selected - owners.keys():
        raise ValueError('selection op missing compute owner')
    by_kind = {}
    for oid in sorted(dead):
        kind = view.kind(view.ops[oid])
        row = by_kind.setdefault(kind, {'ops': 0, 'execs': 0, 'wr': 0, 'ch': 0})
        row['ops'] += 1
        row['execs'] += fires[owners[oid]]
        for value in view.ops[oid][5]:
            wr, ch = vchg.get(value, (0, 0))
            row['wr'] += wr
            row['ch'] += ch
    for proof in proofs:
        proof['state_name'] = view.text(view.states[proof['state']][1])
        proof['root_shared'] = view.producer[proof['original']] not in dead
        proof['chain_execs'] = sum(fires[owners[s['op']]] for s in proof['chain'])
        proof['removed_chain_execs'] = sum(fires[owners[s['op']]] for s in proof['chain'] if s['op'] in dead)
        proof['width'] = view.type(proof['original'])[3]
    dead_execs = sum(fires[owners[oid]] for oid in dead)
    dead_wr = sum(vchg.get(v, (0, 0))[0] for v in dead_values)
    if sum(r['execs'] for r in by_kind.values()) != dead_execs:
        raise ValueError('kind execution closure')
    if sum(r['wr'] for r in by_kind.values()) != dead_wr:
        raise ValueError('kind boundary closure')
    result = {'write_statuses': dict(sorted(statuses.items())), 'guard_writes': len(proofs),
              'selected_ops': len(selected), 'dead_ops': len(dead), 'dead_execs': dead_execs,
              'prior_dead_compute_ops': prior_dead, 'compute_execs': compute_execs,
              'dead_compute_fraction': dead_execs / compute_execs if compute_execs else 0,
              'monitored_values': len(dead_values & vchg.keys()), 'dead_wr': dead_wr,
              'all_wr': sum(wr for wr, _ in vchg.values()),
              'shared_roots': sum(p['root_shared'] for p in proofs),
              'shared_selected_ops': len(selected - dead),
              'proof_assignments': sum(p['assignments'] for p in proofs),
              'max_proof_atoms': max((p['atoms'] for p in proofs), default=0),
              'proof_modes': dict(sorted(Counter(s['proof_mode'] for p in proofs for s in p['chain']).items())),
              'status_root_execs': {status: sum(fires[owners[oid]] for oid in ids)
                                    for status, ids in sorted(status_roots.items())},
              'by_kind': dict(sorted(by_kind.items())),
              'top_writes': []}
    for proof in sorted(proofs, key=lambda p: (-p['removed_chain_execs'], p['write']))[:5]:
        op = view.ops[proof['write']]
        result['top_writes'].append({**proof,
            'enable_expression': describe(view, proof['enable']),
            'data_before': describe(view, proof['original']),
            'data_after': describe(view, proof['replacement']),
            'mask': describe(view, op[4][2]),
            'events': [describe(view, v, 0) for v in op[4][3:]],
            'write_refs': op[6], 'write_parameters': view.params(op)})
    result['dead_wr_fraction'] = dead_wr / result['all_wr'] if result['all_wr'] else 0
    result['followup_threshold_pass'] = (result['dead_compute_fraction'] >= 0.01 or
                                         result['dead_wr_fraction'] >= 0.005)
    return result, proofs, sorted(dead)


def log(message):
    print(message, flush=True)


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    final_hash = digest(args.final)
    if final_hash != digest(args.dynamic):
        raise ValueError('final/dynamic checkpoint identity failed')
    log('load pre-partition semantic fingerprints')
    pre = json.loads(args.pre.read_bytes())
    expected = semantic_fingerprints(pre)
    pre_strings = pre['strings']
    del pre
    gc.collect()
    log('load final model and check semantic identity')
    model = json.loads(args.final.read_bytes())
    counts_ok, counts = full_counts_check(model)
    if not counts_ok:
        raise ValueError('checkpoint count closure failed')
    if expected != semantic_fingerprints(model) or pre_strings != model['strings'][:len(pre_strings)]:
        raise ValueError('pre/final semantic identity failed')
    del pre_strings
    log('verify two dynamic runs and generated counter sites')
    fires, cycles, dynamic = check_dynamic(model, args.run1, args.run2, args.model_dir)
    identity = dynamic_identity(args.run1, args.run2)
    texts = [path.read_text() for path in (args.run1, args.run2)]
    vchg, other = map(parse_vchg, texts)
    if (vchg != other or parse_sn(texts[0]) != parse_sn(texts[1]) or
            parse_kinds(texts[0]) != parse_kinds(texts[1])):
        raise ValueError('dynamic rows differ')
    if not vchg:
        raise ValueError('missing boundary counters')
    closure = closure_check(vchg, parse_kinds(texts[0]))
    if not closure['wr_ok'] or not closure['ch_ok']:
        raise ValueError('boundary closure failed')
    log('prove write selections and price global dead-op union')
    metrics, proofs, dead = census(model, fires, vchg)
    if metrics['compute_execs'] != dynamic['compute_execs']:
        raise ValueError('independent compute closure failed')
    report = {'input_sha256': final_hash, 'cycles': cycles, 'metrics': metrics,
              'gates': {'G1': {'counts': counts, 'semantic_identity': True},
                        'G3': dynamic | {'boundary': closure, 'identity': identity},
                        'G4': {'all_proofs_verified': True, 'proofs': len(proofs)},
                        'G5': {'reference_count_equals_reachability': True, 'closures': True}}}
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (args.output / 'proofs.json').write_text(json.dumps(proofs, indent=2, sort_keys=True) + '\n')
    with (args.output / 'dead_ops.tsv').open('w') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(['op'])
        writer.writerows((oid,) for oid in dead)
    if args.reference:
        for name in ('summary.json', 'proofs.json', 'dead_ops.tsv'):
            if (args.output / name).read_bytes() != (args.reference / name).read_bytes():
                raise ValueError(f'G2 determinism failed: {name}')
        log('G2: three files byte-identical')
    log(json.dumps({k: v for k, v in metrics.items() if k != 'top_writes'}, sort_keys=True))


def verify_production(base, production):
    """Identity gate for a fresh, fully generated production arm."""
    checkpoint = production / 'xiangshan_grhsim_ir.json'
    sha = digest(checkpoint)
    if sha != digest(base / checkpoint.name):
        raise ValueError('production checkpoint differs from baseline')
    if sha != digest(production / 'xiangshan_grhsim_ir_roundtrip.json'):
        raise ValueError('production roundtrip differs')
    sources = source_fingerprints(production / 'model')
    if sources != source_fingerprints(base / 'model'):
        raise ValueError('production model source differs from baseline')
    if digest(production / 'pre_partition.json') != digest(base / 'pre_partition.json'):
        raise ValueError('production pre-partition checkpoint differs')
    return {'checkpoint_sha256': sha, 'checkpoint_and_roundtrip_identical': True,
            'pre_partition_identical': True, 'identical_source_files': len(sources)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-production', type=Path)
    parser.add_argument('--baseline', type=Path)
    for name in ('pre', 'final', 'dynamic', 'run1', 'run2', 'model-dir', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    if args.verify_production:
        if not args.baseline:
            parser.error('--verify-production requires --baseline')
        log(json.dumps(verify_production(args.baseline, args.verify_production), sort_keys=True))
        return
    if any(getattr(args, name) is None for name in
           ('pre', 'final', 'dynamic', 'run1', 'run2', 'model_dir', 'output')):
        parser.error('census requires pre/final/dynamic/run1/run2/model-dir/output')
    if not args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1] / 'ptmp'):
        parser.error('output must be under repository ptmp')
    run(args)


if __name__ == '__main__':
    main()
