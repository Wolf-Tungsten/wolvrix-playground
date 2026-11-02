"""Chinese, RTL-first presentation of existing static paths and batch evidence.

Module names come from source declarations. Signal labels are lexical names at
the recorded source location, not a reconstruction of elaborated instance paths.
Only the GRH dependency sequence supplies arrows; batch members form a set.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

from grhsim_source_map import save
from grhsim_chisel_map import DEFAULT_ROOT, resolve_contexts


_NON_CODE = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"')
_NUMBER = re.compile(r"\b[0-9][0-9_]*(?:\s*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ?_]+)?|'[01xXzZ]")
_NAME = re.compile(r'\\[^\s]+|(?<![\w$])[A-Za-z_$][\w$]*')
_MODULE = re.compile(r'\b(module|interface|program)\s+(?:(?:automatic|static)\s+)?(\\[^\s]+|[A-Za-z_$][\w$]*)|\b(endmodule|endinterface|endprogram)\b')
_KEYWORDS = set('''always always_comb always_ff always_latch and assign automatic begin bit break byte
case casex casez chandle class const continue default disable do else end endcase endclass endfunction
endgenerate endinterface endmodule endpackage endprogram endtask enum event final for force foreach forever
fork function generate genvar if iff import inout input int integer interface join localparam logic longint
module nand negedge new nor not or output package packed parameter posedge program real realtime ref reg
release repeat return shortint signed static string struct task time typedef union unique unsigned var
void wait wand while wire wor xnor xor'''.split())
_OPERATIONS = {
    'kSliceStatic': '位段读取', 'kSliceArray': '索引选择', 'kMux': '条件选择',
    'kConcat': '拼接', 'kAdd': '加法', 'kSub': '减法', 'kMul': '乘法',
    'kAnd': '按位与', 'kOr': '按位或', 'kXor': '按位异或', 'kNot': '按位取反',
    'kLogicAnd': '逻辑与', 'kLogicOr': '逻辑或', 'kLogicNot': '逻辑取反',
    'kRegisterReadPort': '寄存器读', 'kRegisterWritePort': '寄存器提交',
    'kMemoryReadPort': '存储器读', 'kMemoryWritePort': '存储器提交',
    'kLatchReadPort': '锁存器读', 'kLatchWritePort': '锁存器提交',
    'kDpicCall': 'DPI 调用', 'kSystemTask': '系统任务', 'kAssign': '赋值',
    'kEqual': '相等比较', 'kEq': '相等比较', 'kReduceOr': '或归约',
    'kConstant': '常量', 'kShl': '左移', 'kShr': '右移',
}
_STAGES = {'compute': '组合计算', 'commit': '状态提交', 'eval': '求值',
           'input': '输入分发', 'update': '跨分区发布'}
_WAVES = {'first': '首次计算', 'after_commit': '提交后传播', 'later': '后续传播'}
_DYNAMIC_STATUS = {'measured': '已有实测', 'not_measured': '尚未采样',
    'no_critical_samples': '没有稳定拖尾采样', 'no_batch_calls': '采样步中没有批次调用'}


def _blank(match):
    return re.sub(r'[^\n]', ' ', match.group())


def source_contexts(spans):
    """Resolve only requested positions, reading each file once; no guessed hierarchy."""
    by_file = defaultdict(list)
    result = {}
    for sid, span in spans.items():
        result[sid] = dict(source_span_id=sid, file=span['file'], line=span['line'],
            column=span['column'], precision=span.get('precision', 'point'),
            end_line=span.get('end_line'), end_column=span.get('end_column'),
            module=None, signals=[], label=None, source_line=None,
            context_status='unknown', signal_evidence='源码位置的标识符；不推断实例层次')
        by_file[span['resolved_file']].append((sid, span))
    for filename, positions in by_file.items():
        try:
            text = Path(filename).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        # Blanking preserves offsets and newlines, including comments that
        # mention fake modules or identifiers and strings containing RTL text.
        code = _NON_CODE.sub(_blank, text)
        line_offsets = [0] + [m.end() for m in re.finditer('\n', code)]
        modules = []
        current = None
        for match in _MODULE.finditer(code):
            if match.group(1):
                if current is not None:
                    modules.append((current[0], match.start(), current[1]))
                current = (match.start(), match.group(2))
            elif current is not None:
                modules.append((current[0], match.end(), current[1])); current = None
        if current is not None:
            modules.append((current[0], len(code), current[1]))
        module_starts = [start for start, end, name in modules]
        for sid, span in positions:
            line_number = int(span['line'])
            if not 0 < line_number <= len(line_offsets):
                continue
            start = line_offsets[line_number - 1]
            end = line_offsets[line_number] if line_number < len(line_offsets) else len(code)
            raw_line = text[start:end].rstrip('\r\n')
            clean = _NUMBER.sub(_blank, code[start:end])
            tokens = [m for m in _NAME.finditer(clean)
                      if m.group() not in _KEYWORDS and not m.group().startswith('$')]
            module_index = bisect_right(module_starts, start + max(0, int(span['column']) - 1)) - 1
            module = None
            if module_index >= 0:
                begin, finish, name = modules[module_index]
                if begin <= start + max(0, int(span['column']) - 1) < finish:
                    module = name
            tokens = [m for m in tokens if m.group() != module]
            point = max(0, int(span['column']) - 1)
            # A point on a name is exact lexical evidence. For an operator,
            # retain the line's expression rather than claiming its operand is
            # the operation's result signal.
            hit = next((m.group() for m in tokens if m.start() <= point < m.end()), None)
            signals = list(dict.fromkeys(m.group() for m in tokens))
            label = hit or (signals[0] if len(signals) == 1 else None)
            result[sid].update(module=module, signals=signals[:24], label=label,
                source_line=raw_line.strip()[:1400], context_status='source',
                signal_evidence='位置命中的标识符' if hit else '同一源码行的标识符')
    return result


def node_context(node, contexts):
    source = contexts.get(node.get('source_span_id'))
    operation = _OPERATIONS.get(node.get('op_kind'), '组合运算')
    symbol = node.get('op_symbol', '')
    if source and source['source_line']:
        label = source['label'] or source['source_line'][:120]
        return dict(op_index=node['op_index'], module=source['module'], label=label,
            signals=source['signals'], source_span_id=node.get('source_span_id'),
            operation=operation, batch=node.get('batch'), mapped=True,
            storage=node.get('storage', ''), op_kind=node.get('op_kind'),
            chisel_status=source.get('chisel_status'), chisel_candidates=source.get('chisel_candidates', []),
            chisel_selected=source.get('chisel_selected'))
    if node.get('storage'):
        label = node['storage']
    elif symbol.startswith('repcut_out_bundle_'):
        label = '跨分区数据打包'
    elif symbol.startswith('repcut_in_'):
        label = '跨分区输入解包'
    else:
        label = '未映射的生成操作'
    return dict(op_index=node['op_index'], module=None, label=label, signals=[],
        source_span_id=node.get('source_span_id'), operation=operation,
        batch=node.get('batch'), mapped=False, storage=node.get('storage', ''),
        op_kind=node.get('op_kind'), generated_symbol=symbol)


def build_view(report, mapping):
    """Keep path order exact and batch timing separate from RTL signal labels."""
    part_rows = {(r['part'], r['clock']): r for r in report['part_ranking'] if r['phase'] == 'eval'}
    batch_rows = {b['batch_key']: b for b in report['batch_ranking']}
    def path_order(path):
        mapped = sum(bool(n.get('source_span_id')) for n in path['nodes'])
        tail = part_rows.get((path['part'], path['clock']), {}).get('exclusive_tail_ns', 0)
        return (not mapped, -tail, path['rank'], path['part'], path['clock'])
    candidate_raw = sorted((p for p in report['static_paths'] if p['rank'] == 1), key=path_order)
    selected = {n['source_span_id'] for path in candidate_raw for n in path['nodes'] if n.get('source_span_id')}
    # Source contexts for all associations in the top batches, without loading
    # every one of the millions of spans in the entire design into the view.
    dynamic = report.get('dynamic_top1', dict(rows=[], parts=[], measured_parts=[], scope_labels={}))
    displayed_keys = {b['batch_key'] for b in report['batch_ranking'][:100]}
    displayed_keys.update(r['batch_key'] for r in dynamic['rows'] if r['batch_key'])
    displayed_batches = [b for b in report['batch_ranking'] if b['batch_key'] in displayed_keys]
    for batch in displayed_batches:
        selected.update(batch['source_spans'])
    contexts = source_contexts({sid: mapping['spans'][sid] for sid in selected})
    _, chisel_summary = resolve_contexts(contexts, DEFAULT_ROOT)
    phase_costs = defaultdict(Counter)
    for row in report['phase_costs']:
        if row['scope'] == 'stable_last':
            phase_costs[row['batch_key'], row['clock']][row['wave']] += row['ns']
    paths = []
    for path in candidate_raw:
        nodes = [node_context(node, contexts) for node in path['nodes']]
        batch_keys = list(dict.fromkeys(n['batch'] for n in nodes if n.get('batch')))
        modules = list(dict.fromkeys(n['module'] for n in nodes if n['module']))
        signals = list(dict.fromkeys(s for n in nodes for s in n['signals']))
        last = part_rows.get((path['part'], path['clock']), {})
        measured = [key for key in batch_keys if sum(phase_costs[key, path['clock']].values()) > 0]
        chisel_modules = []
        for node in nodes:
            selected_chisel = node.get('chisel_selected')
            if selected_chisel:
                item = (selected_chisel['qualified'], selected_chisel['file'], selected_chisel['line'], selected_chisel['relative'])
                if item not in chisel_modules:
                    chisel_modules.append(item)
            elif node.get('chisel_candidates'):
                for candidate in node['chisel_candidates'][:8]:
                    item = (candidate['qualified'], candidate['file'], candidate['line'], candidate['relative'])
                    if item not in chisel_modules:
                        chisel_modules.append(item)
        paths.append(dict(id=f"p{path['part']}-c{path['clock']}-r{path['rank']}",
            part=path['part'], clock=path['clock'], rank=path['rank'],
            structural_work=path['structural_work'], unknown_operations=path['unknown_operations'],
            modules=modules, signals=signals, nodes=nodes, batch_keys=batch_keys,
            chisel_modules=[dict(qualified=name, file=file, line=line, relative=relative)
                            for name,file,line,relative in chisel_modules],
            measured_batch_keys=measured, last_count=last.get('last_count', 0),
            exclusive_tail_ns=last.get('exclusive_tail_ns', 0),
            longest_body_disagrees=last.get('last_not_longest_count', 0),
            mapped_nodes=sum(n['mapped'] for n in nodes),
            dynamic_status='所在分区反复拖尾，相关批次有采样' if measured else '仅有静态结构证据'))
    # Present the longest structural paths in repeatedly tailing partitions
    # first. The table states this order; it is not a fitted runtime model.
    paths.sort(key=lambda p: (not p['mapped_nodes'], -p['exclusive_tail_ns'], p['rank'], p['part'], p['clock']))
    hot_batches = []
    for batch in displayed_batches:
        modules = Counter()
        entries = []
        for sid, count in batch['source_spans'].items():
            context = contexts[sid]
            modules[context['module'] or '未定位模块'] += count
            entries.append(dict(source_span_id=sid, operations=count))
        entries.sort(key=lambda x: (-x['operations'], x['source_span_id']))
        module_rows = [dict(name=name, operations=count) for name, count in modules.most_common()]
        representative = []
        seen = set()
        # Choose representative locations within the largest source modules,
        # so a shared top-level input cannot hide every internal signal. This
        # is an inventory ordering, never a measured module/signal ranking.
        for module in module_rows:
            added = 0
            for entry in entries:
                context = contexts[entry['source_span_id']]
                if (context['module'] or '未定位模块') != module['name']: continue
                signals = list(dict.fromkeys(([context['label']] if context['label'] else []) + context['signals']))
                for signal in signals:
                    key = context['module'], signal
                    if key not in seen:
                        representative.append(dict(module=context['module'], signal=signal,
                                                   source_span_id=entry['source_span_id']))
                        seen.add(key); added += 1
                    if added >= 2 or len(representative) >= 8: break
                if added >= 2 or len(representative) >= 8: break
            if len(representative) >= 8: break
        hot_batches.append(dict(batch_key=batch['batch_key'], part=batch['part'], batch=batch['batch'],
            phase=batch['phase'], phase_label=_STAGES[batch['phase']], modules=module_rows,
            signals=representative, critical_sample_ns=batch['critical_sample_ns'],
            chisel_modules=sorted({(contexts[sid].get('chisel_selected') or {}).get('qualified')
                                   for sid in batch['source_spans']
                                   if contexts[sid].get('chisel_selected')} | {
                candidate['qualified'] for sid in batch['source_spans']
                for candidate in contexts[sid].get('chisel_candidates', [])[:8]
                if not contexts[sid].get('chisel_selected')}),
            calls=batch['critical_sample_calls'], operations=batch['operations'],
            unmapped_operations=batch['unmapped_operations'],
            source_entries=entries[:80], source_count=len(entries),
            asc_ids=batch.get('asc_ids'),
            clocks=[dict(clock=clock, ns=sum(phase_costs[batch['batch_key'], clock].values()),
                         waves=[dict(name=_WAVES[k], ns=v) for k,v in phase_costs[batch['batch_key'], clock].items()])
                    for clock in (0,1)]))
    # Keep only source contexts reachable from the actual displayed report.
    needed={n['source_span_id'] for p in paths for n in p['nodes'] if n.get('source_span_id')}
    for batch in hot_batches:
        needed.update(s['source_span_id'] for s in batch['source_entries'])
        needed.update(s['source_span_id'] for s in batch['signals'])
    batch_contexts = {b['batch_key']: b for b in hot_batches}
    dynamic_rows = []
    for row in dynamic['rows']:
        item = dict(row, status_label=_DYNAMIC_STATUS[row['status']],
                    scope_label=dynamic['scope_labels'][row['scope']],
                    phase_label=_STAGES.get(row.get('phase')), modules=[], signals=[], chisel=[])
        if row['batch_key']:
            batch = batch_contexts[row['batch_key']]
            item['modules'] = batch['modules']
            seen = set()
            for signal in batch['signals']:
                src = contexts[signal['source_span_id']]
                item['signals'].append(dict(signal, file=src['file'], line=src['line'], column=src['column']))
                candidates = [src['chisel_selected']] if src.get('chisel_selected') else src.get('chisel_candidates', [])[:8]
                for candidate in candidates:
                    key = candidate['qualified'], candidate['file'], candidate['line']
                    if key not in seen:
                        item['chisel'].append({k:candidate[k] for k in ('qualified','file','line','relative')})
                        seen.add(key)
            item['source_count'] = batch['source_count']
            item['unmapped_operations'] = batch['unmapped_operations']
        dynamic_rows.append(item)
    return dict(schema_version=1, language='zh-CN', title='RTL 仿真关键路径',
        paths=paths, path_count=sum(p['rank'] == 1 for p in mapping['static_paths']),
        hotspots=hot_batches, sources={sid:contexts[sid] for sid in sorted(needed)},
        chisel=dict(summary=chisel_summary),
        dynamic_top1=dict(dynamic, rows=dynamic_rows),
        parts=report['part_ranking'], runtime=report.get('runtime', {}), mapping=report['mapping'],
        stable_eval_steps=report.get('stable_eval_steps'),
        limits=[
            '箭头顺序来自真实 GRH 组合依赖。源码名称用于定位；并不表示每个名称都是对应操作的输出。',
            '模块名来自 RTL 的 module/interface/program 声明；尚不能恢复唯一实例路径。',
            '静态工作量是结构指标，不是硬件时序延迟，也不是测得的逐信号耗时。',
            '运行时计时粒度为批次。同一批次中的模块和信号是关联集合，不能拼成因果链或重复累加耗时。',
            '只有起始行列的位置保留为点位置；没有可靠来源的生成操作明确标为未映射。',
            '批次标签取自两次独立线程追踪一致的拖尾步骤。诊断插桩会扰动运行时间。',
            '动态第一名按同一分区、同一 clock 的 batch 实测累计时间排序；全部采样排名不等于全局关键路径。',
            '入口活动掩码为零表示调用开始时没有活动标记，不代表逐组执行计数；多字节批次只记录入口掩码的按位或。',
            'Chisel 定位是模块名和源码标识符匹配的候选，不是经 elaboration 验证的唯一实例路径。',
        ])


def path_text(path):
    nodes = path['nodes']
    if len(nodes) > 36:
        nodes = nodes[:28] + [dict(module=None, label=f'… 中间省略 {len(path["nodes"])-33} 个节点 …')] + nodes[-5:]
    return ' → '.join((n['module'] + '.' if n['module'] else '') + n['label'] for n in nodes)


def write_view(view, filename):
    filename = Path(filename)
    save(filename.with_name('rtl_paths.json'), view)
    with filename.with_name('critical_paths.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['路径编号','分区','时钟电平','静态名次','模块','信号与表达式路径','源码位置',
                         '结构工作量','已映射节点','节点总数','所在分区最后完成次数','运行时证据'])
        for path in view['paths']:
            locations = [f"{view['sources'][n['source_span_id']]['file']}:{view['sources'][n['source_span_id']]['line']}:{view['sources'][n['source_span_id']]['column']}"
                         for n in path['nodes'] if n.get('source_span_id')]
            writer.writerow([path['id'],path['part'],path['clock'],path['rank'],'、'.join(path['modules']),
                path_text(path),' → '.join(locations),path['structural_work'],path['mapped_nodes'],len(path['nodes']),
                path['last_count'],path['dynamic_status']])
    # A small Chinese text list is useful even when HTML cannot be opened.
    lines = ['# RTL 仿真关键路径清单', '', '按所在分区的动态拖尾、分沿静态名次排序。批次耗时不分摊到信号。', '']
    for path in view['paths'][:20]:
        lines += [f"## {path['id']} · clock={path['clock']} · {'、'.join(path['modules']) or '模块未映射'}", '',
                  f"结构工作量：{path['structural_work']}；来源覆盖：{path['mapped_nodes']}/{len(path['nodes'])} 个节点。", '',
                  path_text(path), '']
    lines += ['## 说明', '', *['- '+limit for limit in view['limits']]]
    filename.with_name('critical_paths.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write_dynamic(view, filename.parent)
    encoded = json.dumps(view, ensure_ascii=False, separators=(',',':')).replace('<','\\u003c').replace('&','\\u0026')
    template = Path(__file__).with_name('grhsim_critical_path.html').read_text(encoding='utf-8')
    filename.write_text(template.replace('__REPORT_JSON__', encoded), encoding='utf-8')
    return view


def write_dynamic(view, directory):
    """A compact, independently readable ranking beside the HTML report."""
    dynamic = view.get('dynamic_top1', dict(rows=[], scope_labels={}))
    save(directory/'dynamic_top1.json', dict(dynamic, runtime=view.get('runtime', {})))
    with (directory/'dynamic_top1.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['范围','分区','clock','状态','第一名 batch','阶段','累计时间 ns','占本分区采样批次时间',
            '采样步数','调用次数','同为第一名的重复次数','重复总数','单次最大时间 ns','入口零掩码时间占比',
            '首轮 ns','提交后传播 ns','后续传播 ns','并列第一名','每次重复第一名及累计 ns','RTL 模块','关联信号与位置','Chisel 候选'])
        for r in dynamic['rows']:
            writer.writerow([r['scope_label'],r['part'],r['clock'],r['status_label'],r['batch_key'],r['phase_label'],
                r.get('ns'),r.get('share'),r['sampled_steps'],r.get('calls'),r.get('repeat_top_agreement'),r['probe_runs'],
                r.get('max_call_ns'),r.get('entry_zero_share'),*[r.get('waves',{}).get(w,0) for w in ('first','after_commit','later')],
                ';'.join(r['tied_keys']),
                ';'.join(f"第 {repeat['repeat']+1} 次：{' / '.join(repeat['top_keys']) or '无样本'} ({repeat['top_ns']})" for repeat in r['repeats']),
                ';'.join(m['name'] for m in r['modules']),
                ';'.join(f"{s['module']}.{s['signal']} ({s['file']}:{s['line']}:{s['column']})" for s in r['signals']),
                ';'.join(f"{c['qualified']} ({c['relative']}:{c['line']})" for c in r['chisel'])])
    lines = ['# 动态关键路径第一名（batch 粒度）', '',
        '按每个分区、每个 clock 的 batch 实测累计时间选择第一名，包含计算与状态提交。',
        '模块、信号是该 batch 的关联源码集合，不是测得的逐信号依赖链；Chisel 为源码匹配候选。', '',
        '“全局稳定拖尾”只统计两次独立线程追踪均由该分区最后完成的步骤；没有样本时不补用静态排名。',
        '“分区全部采样”也包含非拖尾步骤。时间为采样累计值，不外推为整段仿真耗时。', '']
    for scope, label in dynamic['scope_labels'].items():
        lines += [f'## {label}', '',
            '| 分区 | clock | 第一名 | 累计 µs | 批次时间占比 | 采样步数 | 重复第一名 | RTL 模块（最多 3 个） |',
            '|---|---:|---|---:|---:|---:|---|---|']
        for r in dynamic['rows']:
            if r['scope'] != scope: continue
            if not r['batch_key']:
                lines.append(f"| p{r['part']} | {r['clock']} | {r['status_label']} | — | — | {r['sampled_steps']} | — | — |")
                continue
            names = '、'.join(m['name'] for m in r['modules'][:3]).replace('|','\\|')
            warning = '；并列' if len(r['tied_keys'])>1 else ''
            if r['entry_zero_share'] > .5: warning += '；入口零掩码时间为主'
            lines.append(f"| p{r['part']} | {r['clock']} | {r['phase_label']} {r['batch']}{warning} | {r['ns']/1000:.3f} | {r['share']:.2%} | {r['sampled_steps']} | {r['repeat_top_agreement']}/{r['probe_runs']} | {names} |")
        lines.append('')
    lines += ['详细信号、RTL 行列、Chisel 文件以及每次重复结果见同目录 report.html / dynamic_top1.json。', '']
    (directory/'dynamic_top1.md').write_text('\n'.join(lines), encoding='utf-8')
