"""Shared validation for elaboration-time simulation model selections."""
MODELS = frozenset((
    'commit-rat', 'int-mul', 'fp-mul', 'vec-int-mul', 'vec-fp-mul',
    'int-alu', 'int-bku',
    'vec-int-alu-lane', 'vec-int-alu-whole',
    'vec-int-pu-lane', 'vec-int-pu-whole',
    'vec-int-mac-lane', 'vec-int-mac-whole',
))
VECTOR_BOUNDARY_FAMILIES = (
    frozenset(('vec-int-alu-lane', 'vec-int-alu-whole')),
    frozenset(('vec-int-pu-lane', 'vec-int-pu-whole')),
    frozenset(('vec-int-mac-lane', 'vec-int-mac-whole')),
)


def selected_models(value):
    if value == 'hardware':
        return frozenset()
    names = value.split(',')
    if len(names) != len(set(names)) or any(name not in MODELS for name in names):
        raise ValueError('unknown or duplicate simulation model selection: ' + value)
    selected = frozenset(names)
    for family in VECTOR_BOUNDARY_FAMILIES:
        if len(selected.intersection(family)) > 1:
            raise ValueError('vector behavior boundaries are mutually exclusive: ' + ','.join(sorted(family)))
    if 'vec-int-mul' in selected and selected.intersection(VECTOR_BOUNDARY_FAMILIES[2]):
        raise ValueError('legacy vec-int-mul cannot be combined with a boundary-specific MAC model')
    return selected


def model_mode(value):
    selected_models(value)
    return value
