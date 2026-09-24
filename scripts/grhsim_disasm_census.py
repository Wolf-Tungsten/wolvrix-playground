import subprocess, re, sys, json
from collections import Counter

SSE_OPS = ('movd','movdqa','movdqu','movaps','movups','pshuf','punpck','packus','pand','pandn','por','pxor','pcmpeq','psll','psrl','pmovmskb','movmskps','pinsrw','pextrw','padd','psub','pmull','pcmpgt','pminub','pmaxub','pavgb','pmaddwd','psadbw','pshufb','pmovzx','pblendw','movhps','movlps','shufps','movlhps','movhlps','movdq2q','movq2dq')
MOV_OPS = ('mov','movb','movw','movl','movq','movzbl','movzwl','movzbq','movzwq','movsbl','movswl','movslq','movabs')

def categorize(op, rest, c):
    has_mem = '(' in rest
    if op.startswith(SSE_OPS) or (op in ('movd','movq','pinsrw','pextrw') and '%xmm' in rest):
        c['sse'] += 1; return
    if re.match(r'\$0x0,', rest):
        c['zero_store' if has_mem else 'zero_reg'] += 1; return
    if op.startswith(MOV_OPS):
        sd = rest.split(',')
        if has_mem:
            if '(' in sd[0]: c['load'] += 1
            elif rest.startswith('$'): c['imm_store'] += 1
            else: c['store'] += 1
        else: c['mov_rr'] += 1
        return
    if op.startswith('lea'): c['lea'] += 1; return
    if op.startswith(('j','call','ret','loop')): c['branch'] += 1; return
    if op.startswith(('cmp','test','bt')): c['cmp_mem' if has_mem else 'cmp'] += 1; return
    if op.startswith('set'): c['setcc'] += 1; return
    if op.startswith(('push','pop')): c['pushpop'] += 1; return
    if op.startswith(('nop','endbr','xchg','fnop','data16')): c['nop'] += 1; return
    c['alu_mem' if has_mem else 'alu'] += 1

def census(binpath, out_path):
    funcs = {}
    cur = None
    pat_label = re.compile(r'^[0-9a-f]+ <_ZN13GrhSIM_SimTop\d+(cpu_(?:task|helper)_\d+)Ev>:')
    pat_insn = re.compile(r'^\s+[0-9a-f]+:\s+(\S+)\s*(.*)$')
    p = subprocess.Popen(['objdump','-d','--no-show-raw-insn',binpath],
                         stdout=subprocess.PIPE, text=True, bufsize=1<<20)
    for line in p.stdout:
        m = pat_label.match(line)
        if m:
            cur = m.group(1); funcs[cur] = Counter(); continue
        if line.startswith('0') and '<' in line:
            cur = None; continue  # other symbol
        if cur is not None:
            m = pat_insn.match(line)
            if m: categorize(m.group(1), m.group(2), funcs[cur])
    p.wait()
    with open(out_path,'w') as f:
        json.dump({k: dict(v) for k,v in funcs.items()}, f)
    print(out_path, len(funcs), 'functions')

census(sys.argv[1], sys.argv[2])
