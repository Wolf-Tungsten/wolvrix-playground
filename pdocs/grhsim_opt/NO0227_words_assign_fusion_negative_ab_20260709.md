# NO0227 Words Assign Fusion Negative A/B

记录日期：2026-07-09

关联：[`NO0225`](./NO0225_full_width_words_helper_ab_20260709.md)、[`NO0226`](./NO0226_full_width_words_always_inline_ab_20260709.md)

## 1. 背景

`NO0226` 通过 `always_inline` 消除了 `grhsim_*_words_full<16>` 的 out-of-line helper symbol/call site，并在 `VtypeBuffer/FTQ/Tage` 上取得明显收益。下一步自然想到继续做 producer/assign fusion：把

```cpp
const auto next_words = grhsim_xor_words_full<16>(lhs, rhs);
if (grhsim_assign_words_full<16>(dst, next_words)) {
    activeWordFlags |= ...;
}
```

直接改写成逐 lane 写回 `dst[i]` 并累积 changed bit，避免 `next_words` 中间数组。

本轮做了一个保守 A/B：只识别 RHS 是 `grhsim_{and,or,xor,xnor,not}_words_full<N>(...)`、目标是 full-width wide logic、且需要 change detect 的场景；不融合 generic helper / 非整 word 宽度 / slice/concat/mux。

## 2. 实验性代码形态

实验代码在 `emitLogicAssignFromWordsExpr()` 中增加了 RHS 字符串解析和 lane loop 生成。以 `VtypeBuffer` 为例，原来 `sched_3.cpp` 中 6 个 `assign_words_full<16>` 被改写成：

```cpp
{
    bool grhsim_changed_words = false;
    for (std::size_t i = 0; i < 16; ++i) {
        const std::uint64_t next_word = (((grhsim_v3317_0))[i]) ^ (((grhsim_v3318_0))[i]);
        grhsim_changed_words = static_cast<bool>(grhsim_changed_words |
            (grhsim_value_3319_0_slot[i] != next_word));
        grhsim_value_3319_0_slot[i] = next_word;
    }
    if (grhsim_changed_words) {
        activeWordFlags |= UINT8_C(192);
    }
}
```

命中确认：

- `VtypeBuffer` 生成源码中 `grhsim_assign_words_full<` 文本调用数从 `6` 变为 `0`。
- `eval_compute_batch_3()` size 从 NO0226 的 `0x54db` 小幅降到 `0x543c`。
- verify 均通过。

## 3. Raw A/B 结果

对照基线是 `NO0226` always-inline 版本；本轮只看 fusion 是否能在 always-inline 基础上继续带来收益。

| case | NO0226 GrhSIM ms | fusion GrhSIM ms | GrhSIM 变化 | NO0226 ratio | fusion ratio | GrhSIM instr/text 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal075RobVtypebufferLarge` | 399.980 | 399.424 | -0.14% | 1.912 | 1.942 | -35 instr / -159 B |
| `XsReal053FtqFtqLarge` | 516.147 | 517.581 | +0.28% | 1.342 | 1.332 | -3 instr / +20 B |
| `XsReal043TageTageLarge` | 445.004 | 456.563 | +2.60% | 1.453 | 1.501 | -14 instr / -68 B |

说明：

- `VtypeBuffer` 只有噪声级微小收益，ratio 反而因本轮 GSIM 更快而变差。
- `FTQ` 基本持平略慢。
- `Tage` 明确回退 `+2.60%`。

## 4. 结论

这个 fusion 不建议保留，实验代码已回退，当前源码回到 `NO0226` always-inline 方案。

解释倾向：

- `always_inline` 后，clang 已经能对 full helper 做 SROA/内联传播；手写 lane loop 没有提供新的优化信息。
- 手写 loop 反而可能限制编译器对局部 `std::array` 临时、常量数组和相邻宽字表达式的整体优化，尤其在 `Tage` 中出现明显回退。
- 因此下一步不应继续做“字符串级 RHS assign fusion”，而应从更结构化的 IR/codegen 层面入手，例如：
  - 在生成 local expr 时就做 16-lane scalar form，避免先形成 `std::array` 表达式；
  - 或增加更高层的 wide-lane SSA/codegen path，让 producer、consumer、slice 和 assign 共享同一组 lane 标量，而不是只在最终 assign 处局部改写。

## 5. 状态

- fusion 实验源码：已回退。
- 保留源码改动：`NO0226` 的 `GRHSIM_ALWAYS_INLINE` full-width helper。
- `make py_install` 已在回退后重新执行，确保当前 installed emitter 与源码一致。
- 产物：

```text
tmp/no0227_words_assign_fusion_20260709/
tmp/no0227_words_assign_fusion_20260709/summary/raw_assign_fusion_ab.tsv
testcase/xs-components/build/no0227_words_assign_fusion_20260709/raw_bench/
```
