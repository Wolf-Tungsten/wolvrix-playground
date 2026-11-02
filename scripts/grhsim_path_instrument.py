"""Create diagnostic wrapper/dispatcher copies; retain compute/commit bodies."""
import re
from pathlib import Path


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f'unsupported generated source shape: {before[:100]}')
    return text.replace(before, after)


def instrument_wrapper(text, suffix, parts=32):
    text = '#include "grhsim_path_trace.hpp"\n' + text
    if suffix == 'common':
        for name in ('early_eval_step_fns_', 'early_update_step_fns_'):
            if f'{name}.reserve(0);' not in text:
                raise ValueError('early effect phases require a separate trace adapter')
        before = '  const auto stepBegin = WolviClock::now();'
        text = replace_once(text, before,
            '  grhsim_path_trace::begin(step_count_, top_in_clock_, top_in_reset_);\n' + before)
        before = '  step_timing_.total_ns += elapsed_ns_(stepBegin, finalUpdateEnd);'
        return replace_once(text, before, before + '\n' + '\n'.join(
            f'  grhsim_path_trace::phase({parts}, {kind}, {begin}, {end});'
            for kind,begin,end in ((5,'inputLoadBegin','inputLoadEnd'),
                                  (6,'normalEvalBegin','normalEvalEnd'),(7,'finalUpdateBegin','finalUpdateEnd'))))
    fn, begin, end, kind = dict(load_0=('load','inputApplyBegin','inputApplyEnd',0),
        eval_0=('eval','evalBegin','evalEnd',1),update_0=('update_final','updatePushBegin','updatePushEnd',2))[suffix]
    found = set()
    def wrapper(match):
        p = int(match[1]); found.add(p)
        body = match[0]
        before = f'  const auto {begin} = WolviClock::now();'
        body = replace_once(body, before, f'  grhsim_path_trace::enter({p});\n' + before)
        before = f'  partTimingStats->total_ns += elapsed_ns_({begin}, {end});'
        return replace_once(body,before,before+f'\n  grhsim_path_trace::phase({p}, {kind}, {begin}, {end});')
    text = re.sub(rf'void WolviRepCutGrhSimSim::run_{fn}_part_(\d+)_\([^\n]+\) \{{.*?\n\}}',wrapper,text,flags=re.S)
    if found != set(range(parts)):
        raise ValueError(f'missing {fn} wrapper lanes: {sorted(found)}')
    return text


def instrument_eval(text, package, part):
    text = '#include "grhsim_path_trace.hpp"\n' + text
    before = '        ++fixed_point_round_count;'
    text = replace_once(text,before,before+'\n        grhsim_path_trace::round(fixed_point_round_count);')
    before = '        pending_eval_round = commit_activated_readers_ ||'
    text = replace_once(text,before,'        grhsim_path_trace::committed(commit_activated_readers_);\n'+before)
    sites = []
    def call(match):
        phase, batch = match[1], int(match[2])
        file = Path(package)/f'grhsim_Gpart_{part}_model_sched_{batch}.cpp'
        body = file.read_text()
        if phase == 'compute':
            words = re.findall(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\] & dispatchMask\);',body)
            masks = re.findall(r'constexpr std::uint8_t dispatchMask = UINT8_C\((\d+)\);',body)
            if not words or len(words)!=len(masks):
                raise ValueError(f'unsupported batch activity dispatch: {file}')
            activity_words = [dict(word=int(w), mask=int(m)) for w,m in zip(words,masks)]
            if any(not 0 < entry['mask'] <= 255 for entry in activity_words):
                raise ValueError(f'invalid batch dispatch mask: {file}')
            # Multi-word batches retain one timed interval. UINT32_MAX marks
            # a bytewise OR of the entry masks, not a physical activity word.
            # This preserves zero/nonzero evidence without claiming which
            # word or group executed inside the batch.
            word = int(words[0]) if len(words)==1 else 0xffffffff
            mask = 0
            for entry in activity_words: mask |= entry['mask']
            active = ' | '.join(f"static_cast<uint32_t>(supernode_active_curr_[{e['word']}u] & UINT8_C({e['mask']}))" for e in activity_words)
        else:
            word, mask, active = 0xffffffff, 0xffffffff, 'UINT32_MAX'
            activity_words = []
        sites.append(dict(part=part,batch=batch,phase=phase,word=word,dispatch_mask=mask,
            activity_words=activity_words,entry_mask_kind='not_applicable' if phase=='commit' else
                'word' if len(activity_words)==1 else 'or_of_words'))
        original = match[0].strip()
        return (f'        if (grhsim_path_trace::sample()) {{\n'
                f'            grhsim_path_trace::batch({batch}, {3 if phase=="compute" else 4}, {word}u, {active}, [&] {{ {original} }});\n'
                f'        }} else {{ {original} }}')
    text, count = re.subn(r'        this->eval_(compute|commit)_batch_(\d+)\(\);',call,text)
    if not count:
        raise ValueError('no batch calls in dispatcher')
    return text, sites
