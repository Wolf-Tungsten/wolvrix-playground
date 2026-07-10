# NO0236 Manual wide-slice fusion negative A/B（2026-07-09）

## 1. 背景

`NO0235` 证明：把 `grhsim_slice_words<1>(..., 64*k, 64)[0]` 改成直接 lane 读取，在当前 `clang++ -O3` 下是机器码 no-op，不能解释 `VtypeBuffer` input-low 热点。

本轮继续沿 `NO0234` 的主线，尝试验证一个更强的假设：

> 若某个 `value_words_16_slots_` 刚由 `next_words` 写入，并且同一 supernode 内紧接着把低若干 lane slice 到 `value_u64_slots_`，那么把这些 scalar 写直接改为 `next_words[i]`，也许能减少 wide slot store 后的 reload。

这是一个跨 op producer-consumer fusion。为了避免贸然改 emitter，本轮只手工 patch 临时生成的 C++，看它是否真的改变机器码并带来收益。

## 2. 实验口径

环境：所有构建/测试命令均先执行：

```bash
source env.sh
set -euo pipefail
```

注意：`source env.sh` 会恢复 shell options，因此需要在 source 之后重新设置 `set -euo pipefail`。

临时目录：

```text
tmp/no0236_manual_wide_slice_fusion_20260709/fresh/XsReal075RobVtypebufferLarge/
```

复制 baseline：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/
```

手工 patch 文件：

```text
grhsim/model/grhsim_XsReal075RobVtypebufferLarge_sched_3.cpp
```

另一个操作注意点：复制已有 generated model 后必须删除旧 PCH：

```bash
rm -f grhsim/model/*.o grhsim/model/*.a grhsim/model/*.pch
```

否则 PCH 中保留旧绝对路径，可能导致 runtime header 被双重包含并报大量 redefinition。

## 3. 手工 patch 内容

针对两个片段：

1. `grhsim_value_3498_0_slot = value_words_16_slots_[6]`
2. `grhsim_value_3520_0_slot = value_words_16_slots_[3]`

原始形态：

```cpp
{
    const auto next_words = grhsim_or_words_full<16>(...);
    if (grhsim_assign_words_full<16>(grhsim_value_3498_0_slot, next_words)) {
        activeWordFlags |= UINT8_C(32);
    }
}
{
    const std::uint64_t next_value =
        (grhsim_slice_words<1>((grhsim_value_3498_0_slot), static_cast<std::size_t>(0), 64))[0];
    value_u64_slots_[149] = next_value;
}
```

手工融合后：

```cpp
{
    const auto next_words = grhsim_or_words_full<16>(...);
    if (grhsim_assign_words_full<16>(grhsim_value_3498_0_slot, next_words)) {
        activeWordFlags |= UINT8_C(32);
    }
    value_u64_slots_[149] = next_words[0];
    value_u64_slots_[153] = next_words[1];
    // ... lower lanes only ...
}
```

本轮只融合两个 wide value 的 lower 11 lanes，共 22 个 slice。upper 5 lanes 在另一个被 local active bit 激活的 supernode 中，未融合。

## 4. 静态结果

| metric | baseline | manual fusion |
|---|---:|---:|
| `sched_3.cpp` bytes | `252029` | `246185` |
| `sched_3.cpp` `grhsim_slice_words<1>` refs | `112` | `90` |
| `sched_3.o` SHA256 | `643272af97c08644190a7f019eb6949eeb272f810cff00a1da40d1e0c64dc2a4` | `fa5f307a1626065dc99b9775aa964fb17c3c37954ac4ffd5d59b98bd7b4ac4bd` |
| `eval_compute_batch_3()` symbol size | `0x54db` | `0x55d1` |

与 `NO0235` 不同，这次 object 确实改变了。但 hot symbol 反而增大：`0x54db -> 0x55d1`，增加 `0xf6` bytes。

## 5. runtime 结果

手工链接 bench，避免 `make bench` 重新触发 `emit_grhsim.py` 覆盖 patch。

正确性：

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=4096 status=pass
```

200k vectors，`--model grhsim --repeat 3`：

| model | min ms | median ms |
|---|---:|---:|
| baseline | `399.354` | `399.566` |
| manual fusion | `413.754` | `413.977` |

manual fusion 比 baseline 慢约：

```text
413.754 / 399.354 - 1 = +3.61%
```

## 6. 结论

本实验是 **negative A/B，不应工程化到 emitter**。

原因：

1. 这次 patch 确实改变了机器码，说明它比 `NO0235` 的表层 lane slice 替换更“真实”；
2. 但只融合 22 个同 supernode slice 后，`eval_compute_batch_3()` 代码尺寸变大，runtime 也变慢约 `3.6%`；
3. 朴素地把 slice 从 wide slot reload 改为 `next_words[i]` 可能拉长 `next_words` live range、增加寄存器压力或破坏 Clang 对原始模式的布局/向量化；
4. 因此不能简单把 “producer-consumer fusion” 理解为局部挪动几行赋值。

## 7. 下一步

后续如果继续做 wide producer/local scalarization，应避免这种局部手工模式，改为更系统的策略：

1. 先用 object / assembly 指标 gate：hot symbol size、basic block layout、SIMD 指令数量、spill/reload 指标；
2. 优先寻找能减少 live range 的融合，而不是把更多 scalar consumer 塞进 `next_words` 作用域；
3. 考虑从 IR/schedule 层面减少 materialized wide boundary，而不是在 emitted C++ 末端挪动 slice；
4. 如果继续做手工 A/B，必须直接编译手工 patch 后的 model，不能用 `make bench` 触发重新 emit。
