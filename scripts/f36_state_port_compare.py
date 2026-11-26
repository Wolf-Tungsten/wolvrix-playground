"""Compare post-fourth-DCE state declarations and their read/write geometries."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from f36_grh_access import grh_accesses
from f36_gsim_access import gsim_accesses


def read_json_lines(path, schema, *, states_only=False):
    rows = []
    counts = Counter()
    with path.open(encoding='utf-8') as stream:
        first = stream.readline().rstrip('\n')
        if not first.startswith('#meta\t'):
            raise ValueError(f'missing metadata in {path}')
        metadata = json.loads(first.split('\t', 1)[1])
        if metadata.get('schema') != schema:
            raise ValueError(f'unexpected schema in {path}: {metadata.get("schema")}')
        for line in stream:
            if states_only and line.startswith('{"record":"action",'):
                counts['action'] += 1
                continue
            record = json.loads(line)
            if record.get('record') == 'footer':
                if (record.get('complete') is not True or record.get('states') != counts['state']
                        or record.get('actions') != counts['action']):
                    raise ValueError(f'incomplete state/action export in {path}')
                if stream.read(1):
                    raise ValueError(f'trailing content after footer in {path}')
                return rows, metadata
            kind = record['record']
            if kind not in ('state', 'action'):
                raise ValueError(f'unexpected record {kind} in {path}')
            counts[kind] += 1
            if not states_only or kind == 'state':
                rows.append(record)
    raise ValueError(f'missing footer in {path}')


def read_tsv(path, schema):
    with path.open(encoding='utf-8') as stream:
        first = stream.readline().rstrip('\n')
        if not first.startswith('#meta\t'):
            raise ValueError(f'missing metadata in {path}')
        metadata = json.loads(first.split('\t', 1)[1])
        if metadata.get('schema') != schema:
            raise ValueError(f'unexpected schema in {path}: {metadata.get("schema")}')
        header = stream.readline().rstrip('\n').split('\t')
        rows = []
        for line in stream:
            if line.startswith('#footer\t'):
                footer = json.loads(line.rstrip('\n').split('\t', 1)[1])
                if footer.get('complete') is not True or footer.get('rowCount') != len(rows):
                    raise ValueError(f'incomplete TSV export in {path}')
                if stream.read(1):
                    raise ValueError(f'trailing content after footer in {path}')
                return rows, metadata
            fields = line.rstrip('\n').split('\t')
            if len(fields) != len(header):
                raise ValueError(f'invalid TSV row in {path}')
            rows.append(dict(zip(header, fields)))
    raise ValueError(f'missing footer in {path}')


def read_gsim_actions(path):
    """Validate the large action table while retaining only per-state rows."""
    grouped = defaultdict(list)
    with path.open(encoding='utf-8') as stream:
        first = stream.readline().rstrip('\n')
        if not first.startswith('#meta\t'):
            raise ValueError(f'missing metadata in {path}')
        metadata = json.loads(first.split('\t', 1)[1])
        if metadata.get('schema') != 'gsim.f36.actions.v1':
            raise ValueError(f'unexpected schema in {path}: {metadata.get("schema")}')
        header = stream.readline().rstrip('\n').split('\t')
        count = 0
        for line in stream:
            if line.startswith('#footer\t'):
                footer = json.loads(line.rstrip('\n').split('\t', 1)[1])
                if footer.get('complete') is not True or footer.get('rowCount') != count:
                    raise ValueError(f'incomplete TSV export in {path}')
                if stream.read(1):
                    raise ValueError(f'trailing content after footer in {path}')
                return grouped, metadata
            fields = line.rstrip('\n').split('\t')
            if len(fields) != len(header):
                raise ValueError(f'invalid TSV row in {path}')
            row = dict(zip(header, fields))
            grouped[row['owner_state_id']].append(row)
            count += 1
    raise ValueError(f'missing footer in {path}')


def attribute_map(row):
    return row.get('attrs') or {}


def attr_value(attrs, name, default=None):
    value = attrs.get(name, default)
    if isinstance(value, dict) and 't' in value:
        return value.get('v', value.get('vs', default))
    return value


def grh_type(state):
    attrs = attribute_map(state)
    width = state.get('width')
    shape = state.get('shape', [])
    if not isinstance(width, int) or width < 1 or not isinstance(shape, list):
        return None
    if any(not isinstance(dim, int) or dim < 1 for dim in shape):
        return None
    kind = state['kind']
    depth = attr_value(attrs, 'firrtl.memoryDepth')
    if (attr_value(attrs, 'firrtl.memory') and isinstance(depth, int)
            and depth > 0 and shape and shape[0] == depth):
        kind = 'memory'
    else:
        kind = 'latch' if kind == 'kLatch' else 'register'
    signed = state.get('signed', attr_value(attrs, 'isSigned'))
    return kind, width, signed, tuple(shape)


def gsim_type(state):
    width = int(state['width'])
    shape = json.loads(state['shape_json'])
    kind = state['native_kind']
    if kind == 'NODE_MEMORY':
        shape = [int(state['depth']), *shape]
    return ('memory' if kind == 'NODE_MEMORY' else 'register', width, state['signed'] == 'true', tuple(shape))


def endpoint_names(state):
    names = []
    for endpoint in state.get('semantic_nodes', []):
        path = endpoint.get('path_components')
        if isinstance(path, list) and path:
            names.append(tuple(path[1:]) if len(path) > 1 else tuple(path))
    return sorted(set(names))


def grh_states_actions(path, *, states_only=False):
    rows, metadata = read_json_lines(path, 'semantic-state-actions.v1', states_only=states_only)
    if metadata.get('stage') != 'post-fourth-dead-code-elim':
        raise ValueError('GRH export is not at post-fourth-dead-code-elim')
    states = [row for row in rows if row.get('record') == 'state']
    actions = [row for row in rows if row.get('record') == 'action']
    state_by_symbol = defaultdict(list)
    actions_by_symbol = defaultdict(list)
    for state in states:
        if state.get('symbol'):
            state_by_symbol[state['symbol']].append(state)
    for action in actions:
        if action.get('target_symbol'):
            actions_by_symbol[action['target_symbol']].append(action)
    return states, actions_by_symbol, state_by_symbol, metadata


def gsim_states_actions(directory, *, states_only=False):
    states, state_metadata = read_tsv(directory / 'states.tsv', 'gsim.f36.states.v1')
    if state_metadata.get('stage') != 'RemoveDeadNodes3':
        raise ValueError('GSIM export is not at RemoveDeadNodes3')
    if states_only:
        return states, {}
    actions, action_metadata = read_gsim_actions(directory / 'actions.tsv')
    if any(action_metadata.get(key) != state_metadata.get(key)
           for key in ('stage', 'pass_instance', 'producer_version')):
        raise ValueError('GSIM state and action metadata differ')
    return states, actions


def capture_identity(grh_path, gsim_directory, *, states_only):
    grh_receipt = grh_path.with_name('capture.json')
    gsim_receipt = gsim_directory / 'capture.json'
    grh = json.loads(grh_receipt.read_text(encoding='utf-8'))
    gsim = json.loads(gsim_receipt.read_text(encoding='utf-8'))
    if (grh['schema'] != 'wolvrix.f36.grh-state-capture.v1'
            or gsim['schema'] != 'wolvrix.f36.gsim-inventory-capture.v1'
            or grh['complete'] is not True or gsim['complete'] is not True
            or grh['stage'] != 'post-fourth-dead-code-elim' or gsim['stage'] != 'RemoveDeadNodes3'
            or gsim['provenance'] != 'execution-captured'):
        raise ValueError('capture reports do not identify two completed R4 runs')
    for field in ('input_sha256', 'manifest_sha256', 'top'):
        if grh[field] != gsim[field]:
            raise ValueError(f'GRH and GSIM capture reports differ in {field}')
    files = {grh_path: grh['inventory_sha256'],
             gsim_directory / 'states.tsv': gsim['tables']['states']['sha256']}
    if not states_only:
        files[gsim_directory / 'actions.tsv'] = gsim['tables']['actions']['sha256']
    for path, expected in files.items():
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError(f'capture inventory hash does not match: {path}')
    return {'grh_receipt': str(grh_receipt), 'gsim_receipt': str(gsim_receipt),
            'input_sha256': grh['input_sha256'], 'manifest_sha256': grh['manifest_sha256'],
            'grh_package_identity_sha256': grh['package_identity_sha256'],
            'gsim_binary_sha256': gsim['binary_sha256']}


def access_geometry(accesses):
    geometry = {'read': set(), 'write': set()}
    for direction, axes, shape, leaf_width in accesses:
        geometry[direction].add((len(axes), shape, leaf_width))
    return geometry


def access_record(signature):
    indexed_axes, shape, leaf_width = signature
    return {'mode': 'indexed' if indexed_axes else 'whole', 'indexed_axes': indexed_axes,
            'shape': shape, 'leaf_width': leaf_width}


def compare_accesses(grh, gsim, grh_issues, gsim_issues):
    details = {}
    for direction in ('read', 'write'):
        left = grh[direction]
        right = gsim[direction]
        uncertain = any(not issue.startswith(('read-', 'write-')) or issue.startswith(direction + '-')
                        for issue in (*grh_issues, *gsim_issues))
        details[direction] = {
            'status': 'unknown' if uncertain else 'match' if left == right else 'mismatch',
            'grh_only': [access_record(signature) for signature in sorted(left - right)],
            'gsim_only': [access_record(signature) for signature in sorted(right - left)],
        }
    statuses = {entry['status'] for entry in details.values()}
    status = 'mismatch' if 'mismatch' in statuses else 'unknown' if 'unknown' in statuses else 'match'
    return status, details


def compare(grh_path, gsim_directory, *, states_only=False):
    grh_states, grh_actions_by_symbol, state_by_symbol, grh_metadata = grh_states_actions(
        grh_path, states_only=states_only)
    gsim_states, gsim_actions = gsim_states_actions(gsim_directory, states_only=states_only)
    gsim_by_path = defaultdict(list)
    for state in gsim_states:
        path = tuple(json.loads(state['name_path_json']))
        gsim_by_path[path].append(state)

    grh_by_path_shape = defaultdict(list)
    for state in grh_states:
        for name in endpoint_names(state):
            grh_by_path_shape[(name, grh_type(state))].append(state)
    rows = []
    counts = Counter()
    by_state_kind = defaultdict(Counter)
    access_issues = {'grh': Counter(), 'gsim': Counter()}
    matched_gsim_ids = set()
    for state in grh_states:
        names = endpoint_names(state)
        grh_name = names[0] if len(names) == 1 else None
        grh_shape = grh_type(state)
        candidates = gsim_by_path.get(grh_name, []) if grh_name else []
        shape_candidates = [candidate for candidate in candidates
                            if gsim_type(candidate) == grh_shape]
        if len(shape_candidates) == 1 and grh_shape is not None:
            reverse = grh_by_path_shape[(grh_name, grh_shape)]
        else:
            reverse = []
        matched = shape_candidates[0] if len(shape_candidates) == 1 and len(reverse) == 1 else None
        row = {'grh_symbol': state.get('symbol'), 'grh_kind': state.get('kind'),
               'grh_operation': state.get('operation'),
               'grh_name_path': list(grh_name) if grh_name else None,
               'grh_shape': grh_shape, 'gsim_candidates': [int(c['state_id']) for c in candidates],
               'gsim_shape_candidates': [int(c['state_id']) for c in shape_candidates],
               'same_name_shape': matched is not None}
        if matched is None:
            reason = ('missing-grh-name' if not names else
                      'ambiguous-grh-name' if grh_name is None else
                      'unknown-grh-shape' if grh_shape is None else
                      'no-same-name-gsim-state' if not candidates else
                      'shape-mismatch' if not shape_candidates else
                      'ambiguous-shape-match' if len(shape_candidates) != 1 else 'non-bijective-match')
            row['reason'] = reason
            counts['N'] += 1
            counts[f'first_failure:{reason}'] += 1
            rows.append(row)
            continue
        gsim_id = matched['state_id']
        matched_gsim_ids.add(gsim_id)
        row.update(gsim_state_id=int(gsim_id), gsim_name_path=json.loads(matched['name_path_json']),
                   gsim_shape=gsim_type(matched))
        counts['N'] += 1
        counts['S'] += 1
        if states_only:
            rows.append(row)
            continue
        symbol = state.get('symbol')
        grh_actions = grh_actions_by_symbol.get(symbol, [])
        gsim_state_actions = gsim_actions.get(gsim_id, [])
        grh_native, grh_issues = grh_accesses(state, grh_actions)
        gsim_native, gsim_issues = gsim_accesses(matched, gsim_state_actions)
        if not symbol or len(state_by_symbol[symbol]) != 1:
            grh_issues = [*grh_issues, 'ambiguous-or-missing-state-symbol']
        grh_geometry = access_geometry(grh_native)
        gsim_geometry = access_geometry(gsim_native)
        status, details = compare_accesses(grh_geometry, gsim_geometry, grh_issues, gsim_issues)
        row.update(access_status=status, access_differences=details,
                   grh_accesses={direction: [access_record(sig) for sig in sorted(signatures)]
                                 for direction, signatures in grh_geometry.items()},
                   gsim_accesses={direction: [access_record(sig) for sig in sorted(signatures)]
                                  for direction, signatures in gsim_geometry.items()},
                   grh_access_issues=sorted(set(grh_issues)), gsim_access_issues=sorted(set(gsim_issues)),
                   grh_native_action_count=len(grh_actions), gsim_native_action_count=len(gsim_state_actions))
        counts[f'access:{status}'] += 1
        for direction, detail in details.items():
            counts[f'{direction}:{detail["status"]}'] += 1
        if status != 'match':
            counts[f'first_failure:access-{status}'] += 1
        kind = grh_shape[0]
        if kind == 'register':
            kind = 'array-register' if grh_shape[3] else 'scalar-register'
        by_state_kind[kind][status] += 1
        access_issues['grh'].update(set(grh_issues))
        access_issues['gsim'].update(set(gsim_issues))
        rows.append(row)

    denominator = counts['N']
    summary = {
        'schema': 'wolvrix.f36.state-access-alignment.v1', 'complete': True,
        'observation': {'grh': 'post-fourth-dead-code-elim', 'gsim': 'RemoveDeadNodes3'},
        'source': {'grh': str(grh_path), 'gsim': str(gsim_directory),
                   'grh_run_id': grh_metadata.get('run_id')},
        'counts': {'N': counts['N'], 'S': counts['S'], 'A': counts['access:match']},
        'access': {scope: {status: counts[f'{scope}:{status}']
                           for status in ('match', 'mismatch', 'unknown')}
                   for scope in ('access', 'read', 'write')},
        'access_by_state_kind': by_state_kind,
        'access_issues': access_issues,
        'rates': {'same_name_shape_over_all_grh_states': counts['S'] / denominator if denominator else None,
                  'state_and_access_over_all_grh_states': counts['access:match'] / denominator if denominator else None,
                  'access_given_same_name_shape': counts['access:match'] / counts['S'] if counts['S'] else None,
                  'state_and_access_upper_bound': (counts['access:match'] + counts['access:unknown']) / denominator
                      if denominator else None},
        'first_failure_counts': {key.removeprefix('first_failure:'): value
                                 for key, value in counts.items() if key.startswith('first_failure:')},
        'gsim_state_count': len(gsim_states), 'grh_state_count': len(grh_states),
        'gsim_unpaired_state_count': len(gsim_states) - len(matched_gsim_ids),
        'gsim_action_count': sum(len(rows) for rows in gsim_actions.values()),
        'grh_action_count': sum(len(rows) for rows in grh_actions_by_symbol.values()),
        'semantics_note': 'Set of per-direction access geometries, each keyed by the number of leading axes '
                          'indexed, remaining shape and leaf width. Shared memory ports contribute both directions. '
                          'Equal geometries collapse. Index values and control/timing fields are outside the comparison.'}
    if states_only:
        summary['comparison_scope'] = 'states-only'
        summary['counts'] = {key: counts[key] for key in ('N', 'S')}
        summary['rates'] = {'same_name_shape_over_all_grh_states':
                            summary['rates']['same_name_shape_over_all_grh_states']}
        for key in ('access', 'access_by_state_kind', 'access_issues', 'gsim_action_count', 'grh_action_count',
                    'semantics_note'):
            del summary[key]
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--states-only', action='store_true')
    parser.add_argument('--verify-captures', action='store_true')
    args = parser.parse_args()
    identity = None
    if args.verify_captures:
        identity = capture_identity(args.grh, args.gsim, states_only=args.states_only)
    summary, rows = compare(args.grh, args.gsim, states_only=args.states_only)
    if identity is not None:
        summary['source']['verified_capture_identity'] = identity
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    with (args.output / 'states.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    rates = summary['rates']
    print(f"F36 same name and shape {summary['counts']['S']}/{summary['counts']['N']} "
          f"({rates['same_name_shape_over_all_grh_states']:.4%})" if summary['counts']['N']
          else 'F36 has no GRH states')
    if not args.states_only:
        result = summary['access']['access']
        print(f"F36 access geometry: {result['match']} match, {result['mismatch']} mismatch, "
              f"{result['unknown']} unknown")


if __name__ == '__main__':
    main()
