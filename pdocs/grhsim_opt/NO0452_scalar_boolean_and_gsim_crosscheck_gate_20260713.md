# NO0452 Scalar Boolean AND GSim crosscheck gate

日期：2026-07-13

## 1. Run validity

按 [NO0451](./NO0451_scalar_boolean_and_gsim_crosscheck_plan_20260713.md)，本轮只扫描 existing same-FIR GSim source；没有
重新编译、运行仿真或采集 perf。输入精确复现 204 个 scalar Boolean `kAnd` payload samples，其中 stable-name
147 samples/144 unique values、anonymous 57 samples。

对 GSim 331 个 `SimTop*.cpp`/3.7 GiB source 执行单次多 pattern `rg -F`，得到 599 行 exact-name occurrences。canonical
name 0 collision，assignment parser 0 conflicting shape；analyzer exit 0，wall `0.78s`，maximum RSS `27,648 KiB`。

## 2. Strict exact-name result

按预声明只接受 exact canonical LHS assignment：

| Class | Samples | Unique values | Direct total share |
| --- | ---: | ---: | ---: |
| Exact GSim AND assignment | 34 | 34 | 0.509% |
| Exact GSim non-AND assignment | 1 | 1 | 0.015% |
| Stable name not found | 112 | 109 | 1.678% |
| Anonymous GrhSIM value | 57 | 57 | 0.854% |
| Total | 204 | 201 | 3.056% |

34 个 exact common samples 中，23 个同时连接到 GSim old snapshot 和 old/new compare，20 个还直接连接到显式
`activeFlags/oldFlag`。其余 common values 可能是未跟踪 local 或 inline boundary；不影响其 AND payload 已在两边共同存在的结论。

从 204 中只扣除 34 个 exact common 后，保守残余为 170 samples/direct `2.546816%`，明显通过 67 samples/direct 1%
门槛。

## 3. Name-not-found correction

`name_not_found` 不能解释为 GSim 没有对应 RTL 逻辑。112 samples 中 49 个是 `_GEN_*`、3 个是 `__xmr*`、60 个有
语义名字；抽查后已看到 GSim 使用同层级、不同 temporary 名承载相同逻辑：

- GrhSIM `error$w_q$do_enq` 对应 GSim `_do_enq_T`，GSim RHS 同样是 Boolean AND，并保留 old/cond/activation；
- GrhSIM `rename$needIntDest_4` 对应 GSim `_needIntDest_4_T`，GSim 同样执行 AND 与 old/new compare；
- GrhSIM `LoadUnit_0$s2_exception_vec_5` 在 GSim 中由 `_s2_exception_vec_5_T*` 多级临时量计算后赋给最终值。

这些 alias 没有按相似名字从 residual 扣除，因为 NO0451 要求 exact LHS，且一个 semantic result 可能对应多个 GSim
temporaries。它们只证明 residual 是保守上界，也把下一问题从“GSim 是否做 AND”改为“两边如何实现共同 Boolean DAG”。

## 4. Machine-shape signal

170 个 residual samples 的头部 opcode 为：

| Opcode group | Samples |
| --- | ---: |
| `setne` / `sete` / `setae` | 43 |
| `cmpb` / `cmpw` / `cmp` | 34 |
| `test` | 16 |
| `and` / `pand` / `pandn` | 32 |
| Other scalar/SIMD/fused | 45 |

对应 GrhSIM source 中，简单 materialized operands 可直接生成 `value_bool_slots_[a] & value_bool_slots_[b]`；inline state 或
嵌套 expression 则常出现逐 operand `static_cast<bool>(uint8_t)`。同时 generated header 把 651,848 个 Boolean value slots
声明为 `std::array<std::uint8_t, ...>`，packed 1-bit state 也由 `uint8_t&` 读取，编译器不能天然使用运行时 0/1 不变量。

这个现象与历史 NO0089 中 GrhSIM 相对 GSim 大量增加 `cmp/setne` 的全局画像一致，但当前还不能把 93 个 compare/set/test
samples 全部视为可删：其中可能包含真正的 RTL compare、最终 Boolean normalization 或已融合的 changed check。

## 5. Decision

scalar Boolean AND 的 strict GSim gate 通过，保留 170-sample residual 上界；本篇不修改 emitter。下一步对全部 204 samples
读取 production-identical O3 基本块，互斥拆 per-operand normalization、final-result normalization、necessary AND/load、changed
fusion 和其他 consumer fusion；同时用 standalone O3 probe 验证“已知 0/1 byte”能否真实删除机器指令。

之所以覆盖全部 204 而不只看 170 residual，是因为 exact common AND 只证明逻辑两边都存在，不能证明 GrhSIM 的 byte-to-bool
实现与 GSim 同样高效。只有可消除 normalization 本身仍达到 direct 1%，且 0/1 写入不变量可闭合，才进入 emitter 实验。

产物：

```text
build/logs/xs_perf/no0451/analyze_scalar_and_gsim.py
build/logs/xs_perf/no0451/gsim_{name_patterns,occurrences}.txt
build/logs/xs_perf/no0451/{value_crosscheck,sample_crosscheck,class_summary}.tsv
build/logs/xs_perf/no0451/analysis_summary.txt
```
