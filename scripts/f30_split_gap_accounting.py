"""Pure Node-family accounting for F30 split analysis.

Each family denotes one original Node on each engine. Child counts are distinct
live direct ``relation=split`` successors, not lineage rows or edited Node rows.
Callers establish original-parent correspondence and unique child ownership.
Families without a peer belong in a separate, single-engine inventory account.

``resolve_blocker`` accepts ``{node_id: [decision, ...]}``, where each decision
has ``outcome``, ``reason`` and an optional ``blockers`` list of native Node IDs.
The result contains recorded terminal facts and evidence issues, not a guess at
functional equivalence. Lists and dictionaries in the result are JSON compatible.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


TRANSITIVE_BLOCKER_REASONS = frozenset({
    'unsplit_upstream_array', 'unsplit_array_input', 'unsplit_state_payload',
})


def _family_arguments(grh_children, gsim_children, grh_alive, gsim_alive):
    for name, value in (('grh_children', grh_children), ('gsim_children', gsim_children)):
        if type(value) is not int or value < 0:
            raise ValueError(name + ' must be a nonnegative distinct live child count')
    for name, value in (('grh_alive', grh_alive), ('gsim_alive', gsim_alive)):
        if type(value) is not bool:
            raise ValueError(name + ' must be a bool from the after inventory')


def classify_family(grh_children, gsim_children, grh_alive, gsim_alive):
    """Classify count/retention asymmetry; equal counts do not establish geometry."""
    _family_arguments(grh_children, gsim_children, grh_alive, gsim_alive)
    if not grh_children and not gsim_children:
        return ('neither_split' if grh_alive and gsim_alive else
                'neither_split_with_retirement')
    if not grh_children:
        return 'gsim_only_split'
    if not gsim_children:
        return 'grh_only_split'
    if grh_children != gsim_children:
        return 'both_split_different_children'
    return ('both_split_equal_children_equal_retention' if grh_alive == gsim_alive else
            'both_split_equal_children_different_retention')


def family_gap(grh_children, gsim_children, grh_alive, gsim_alive):
    """Return GSIM minus GRH net growth, including residual live parents."""
    _family_arguments(grh_children, gsim_children, grh_alive, gsim_alive)
    return ((gsim_children - int(not gsim_alive)) -
            (grh_children - int(not grh_alive)))


def _node_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('native Node ID must be a positive integer')
    return value


def _decision(record):
    if not isinstance(record, Mapping):
        raise ValueError('decision must be a mapping')
    outcome, reason = record.get('outcome'), record.get('reason')
    if not isinstance(outcome, str) or not outcome or not isinstance(reason, str) or not reason:
        raise ValueError('decision needs nonempty outcome and reason strings')
    blockers = record.get('blockers', [])
    if not isinstance(blockers, (list, tuple)):
        raise ValueError('decision blockers must be a list or tuple of native Node IDs')
    return {'outcome': outcome, 'reason': reason,
            'blockers': sorted({_node_id(blocker) for blocker in blockers})}


def resolve_blocker(node_id, decisions):
    """Follow every recorded transitive retain blocker, preserving all branches.

    ``terminals`` contains distinct retained terminal facts with the native Node
    path from the queried root. Other retain reasons (including
    ``dynamic_state_index``) are terminals as recorded: a blocker attached to
    such a reason is retained in the fact, without reinterpreting its meaning.
    No reason is assigned to missing evidence or cycles. Those appear in
    ``issues``, making ``complete`` false. Non-retain decisions encountered as
    causes likewise remain explicit issues, rather than being called blockers.
    ``terminal_reasons`` is a set represented as a sorted list; its entries may
    overlap and must not each receive the family's full numeric gap.

    Traversal is iterative, so long dependency chains do not use Python's call
    stack. Every distinct simple path is retained; cyclic paths end at an issue.
    """
    node_id = _node_id(node_id)
    if not isinstance(decisions, Mapping):
        raise ValueError('decisions must map native Node IDs to decision lists')
    terminals, issues = [], []
    terminal_keys, issue_keys = set(), set()
    pending = [(node_id, ())]

    def issue(kind, identifier, path, **detail):
        record = {'kind': kind, 'node_id': identifier, 'path': list(path), **detail}
        key = (kind, identifier, path, detail.get('outcome'), detail.get('reason'),
               tuple(detail.get('blockers', ())))
        if key not in issue_keys:
            issue_keys.add(key)
            issues.append(record)

    while pending:
        identifier, preceding = pending.pop()
        path = preceding + (identifier,)
        if identifier in preceding:
            issue('cycle', identifier, path)
            continue
        records = decisions.get(identifier)
        if records is None or records == [] or records == ():
            issue('missing_decisions', identifier, path)
            continue
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise ValueError('each native Node must map to a sequence of decisions')
        follow = set()
        for raw in records:
            record = _decision(raw)
            outcome, reason, blockers = record['outcome'], record['reason'], record['blockers']
            if outcome != 'retain':
                issue('non_retaining_decision', identifier, path, **record)
            elif reason in TRANSITIVE_BLOCKER_REASONS:
                if not blockers:
                    issue('missing_blocker', identifier, path, **record)
                follow.update(blockers)
            else:
                key = (identifier, path, outcome, reason, tuple(blockers))
                if key not in terminal_keys:
                    terminal_keys.add(key)
                    terminals.append({'node_id': identifier, 'path': list(path), **record})
        pending.extend((blocker, path) for blocker in sorted(follow, reverse=True))

    terminals.sort(key=lambda record: (record['path'], record['reason'], record['blockers']))
    issues.sort(key=lambda record: (record['path'], record['kind'], record.get('reason', '')))
    return {'root_node_id': node_id,
            'terminal_reasons': sorted({record['reason'] for record in terminals}),
            'terminal_node_ids': sorted({record['node_id'] for record in terminals}),
            'terminals': terminals, 'issues': issues, 'complete': not issues}
