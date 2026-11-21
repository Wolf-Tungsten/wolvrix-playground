"""Classify generated source statements and read Clang coverage for the TNO0026 comparisons."""

import collections
import re

G_WORD = re.compile(r'if\(unlikely\(activeFlags\[\d+\] != 0\)\) \{')

G_SUPER = re.compile(r'if\(unlikely\((?:oldFlag|activeFlags\[\d+\]) & 0x[0-9a-f]+\)\) \{ // id=(\d+)')

G_OLD = re.compile(r'^[\w ]+ [\w$]+\$old\$\d+ = ')

G_COND = re.compile(r'^bool cond_')

G_ACT = re.compile(r'^(?:\*\(uint\d+_t\*\)&)?(?:activeFlags\[\d+\]|oldFlag) \|= ')

G_CHANGE_IF = re.compile(r'^if \(.*\$old\$\d+\) \{$')

G_ASSIGN = re.compile(r'^([\w$]+(?:\[[^\]]*\])*) = (.*);$')

G_DECL = re.compile(r'^(?:u?int\d+_t|unsigned _BitInt\(\d+\)|__uint128_t|bool) [\w$]+(?:\[[^\]]*\])*;$')

G_SUBJECT = re.compile(r'(?:[\w ]+ ([\w$]+)\$old\$\d+ = )|(?:bool cond_([\w$]+) = )|(?:cond_([\w$]+))|(?:if \(([\w$]+) != )')

class GsimClassifier:
    """Statement category of GSIM lines; bookkeeping is split by what the watched value is."""

    def __init__(self, registers):
        self.registers = registers
        self.kind = 'value'

    def subject(self, t):
        m = G_SUBJECT.match(t) or G_SUBJECT.search(t)
        name = next((g for g in (m.groups() if m else ()) if g), None)
        if name is not None:
            self.kind = 'next-value' if name.endswith('$NEXT') else 'register' if name in self.registers else 'value'
        return self.kind

    def __call__(self, t):
        if G_WORD.match(t):
            return 'word test'
        if t.startswith(('uint8_t oldFlag = ', 'activeFlags[')) and (t.endswith('= 0;') or 'oldFlag' in t):
            return 'word bookkeeping'
        if G_SUPER.match(t):
            return 'supernode test'
        if G_OLD.match(t):
            return self.subject(t) + ': old value save'
        if G_COND.match(t):
            return self.subject(t) + ': change compare'
        if G_ACT.match(t):
            return self.subject(t) + ': reader notification'
        if G_CHANGE_IF.match(t):
            return self.subject(t) + ': change branch'
        if t.startswith('for(') or t.startswith('for ('):
            return 'register array copy' if '$NEXT' in t else 'array loop'
        if t.startswith('if ') or t.startswith('if('):
            return 'when test'
        if t.startswith(('}', 'else')):
            return 'block end'
        if G_DECL.match(t):
            return 'declaration'
        m = G_ASSIGN.match(t)
        if m:
            left, right = m.groups()
            base = left.split('[')[0]
            if right.split('[')[0] == base + '$NEXT':
                return 'register update'
            if '$NEXT' in base:
                return 'register next value'
            if '[' in left:
                return 'array or memory write'
            return 'value expression'
        if t.endswith(');') and '=' not in t.split('(')[0]:
            return 'call'
        return 'other statement'

H_ENABLE = re.compile(r'if \((?:unlikely\()?\(value_\w+_slots_\[\d+\]\) != 0\)')

def classify_grhsim(t, phase):
    if 'activeWordFlags' in t:
        if '!= UINT8_C(0)' in t or 'supernode_active_curr_' in t or 'hot_event_posedge_' in t:
            return 'word test'
        if t.startswith('if ('):
            return 'supernode test'
        return 'word bookkeeping'
    if t.startswith(('constexpr std::uint8_t dispatchMask', 'constexpr std::uint8_t clearMask')):
        return 'word bookkeeping'
    if '!= next_value' in t:
        return 'state compare' if phase == 'commit' else 'change compare'
    if t.startswith('grhsim_any_changed_') or 'grhsim_slice_changes_' in t:
        return 'change aggregate'
    if phase == 'commit' and H_ENABLE.search(t):
        return 'write enable test'
    if 'supernode_active_curr_' in t or 'grhsim_or_active' in t or 'commit_activated_readers_' in t:
        return 'reader notification'
    if 'next_value = ' in t or 'next_words' in t:
        return 'next value expression'
    if t.endswith('= next_value;'):
        return 'store'
    if t.startswith(('const ', 'bool ', 'std::uint', 'auto ')):
        return 'local expression'
    if 'hot_event_posedge_' in t or 'event_edge_storage_' in t:
        return 'event test'
    if 'grhsim_accumulate_bank_' in t:
        return 'accumulate bank'
    if t.startswith(('if (', 'else', 'switch', 'for (', 'while (')):
        return 'other control flow'
    if t.startswith(('}', '{')):
        return 'block end'
    return 'other statement'

def read_lcov(path):
    """Yield (file, {line: count}, {line: [taken, ...]}) per source file."""
    name, lines, branches = None, {}, collections.defaultdict(list)
    with path.open() as stream:
        for record in stream:
            if record.startswith('DA:'):
                number, count = record[3:].split(',')[:2]
                lines[int(number)] = int(count)
            elif record.startswith('BRDA:'):
                number, _, _, taken = record[5:].rstrip('\n').split(',')
                branches[int(number)].append(0 if taken == '-' else int(taken))
            elif record.startswith('SF:'):
                name = record[3:].rstrip('\n')
            elif record.startswith('end_of_record'):
                yield name, lines, branches
                name, lines, branches = None, {}, collections.defaultdict(list)

def bucket(engine, category):
    if engine == 'gsim':
        if category in ('word test', 'word bookkeeping', 'supernode test'):
            return 'dispatch tests'
        if category.startswith('register') and category != 'register next value':
            return 'register update'
        if category.startswith('next-value:'):
            return 'register update'
        if category.startswith('value:'):
            return 'change detection and notification'
        return 'value computation'
    phase, kind = category.split('|')
    if phase == 'commit':
        return 'register update'
    if kind in ('word test', 'word bookkeeping', 'supernode test'):
        return 'dispatch tests'
    if kind in ('change compare', 'change aggregate', 'reader notification', 'store'):
        return 'change detection and notification'
    return 'value computation'
