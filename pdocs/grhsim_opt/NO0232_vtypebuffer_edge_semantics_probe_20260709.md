# NO0232 VtypeBuffer edge semantics probe：low eval 不是下降沿工作（2026-07-09）

## 1. 背景

`NO0229` 记录了 `XsReal075RobVtypebufferLarge` 的 GrhSIM phase timing：

- `clock=false eval` 约占 eval 时间 `50.22%`；
- `clock=true eval` 约占 eval 时间 `49.78%`。

这个结果容易被误读成“下降沿和上升沿都有等量顺序逻辑工作”。本轮重新检查这个解释。用户指出很多负载下降沿并不做事，这个怀疑是正确的。

## 2. 生成代码事实

生成的 GrhSIM commit batch 只在 posedge 触发：

```cpp
if (event_edge_slots_[0] == grhsim_event_edge_kind::posedge) {
    activeWordFlags = static_cast<std::uint8_t>(activeWordFlags | UINT8_C(64));
}
```

没有 falling / negedge 条件。因此 `VtypeBuffer` 的状态写入不是下降沿触发。

另一方面，bench 当前 GrhSIM 单 vector 逻辑是：

```cpp
drive_grhsim(dut, in);
dut.clock = false;
dut.eval();
Outputs out = sample_grhsim(dut);
dut.clock = true;
dut.eval();
```

也就是说：

- 新输入先被写入；
- 然后才把 clock 设为 false 并 eval；
- 因此 `clock=false eval` 同时包含：
  - 从上一轮 high 到当前 low 的 falling edge；
  - **新输入变化导致的组合逻辑传播**。

所以 `low_eval` 这个名字不能解释为“下降沿工作”。

## 3. 临时 probe：拆分 fall-only / input-low / posedge

临时程序：

```text
tmp/no0232_edge_semantics_20260709/vtypebuffer_edge_phase_probe.cpp
```

使用既有 raw GrhSIM 模型：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/grhsim/model/
```

对比两种等价时序：

### current 模式

```text
drive(new_input)
clock=false; eval()   // falling + input change combined
sample()
clock=true; eval()    // posedge commit + post-commit propagation
```

### split 模式

```text
clock=false; eval()   // fall-only, input unchanged
drive(new_input)
eval()                // input-only while clock already low
sample()
clock=true; eval()    // posedge commit + post-commit propagation
```

如果下降沿本身有实际工作，`fall-only` 应该很重；如果 `NO0229` 的 low phase 主要来自输入组合传播，则 `fall-only` 应该很轻，而 `input-low` 应接近原 `low`。

## 4. 实测结果

命令：

```bash
./tmp/no0232_edge_semantics_20260709/vtypebuffer_edge_phase_probe 200000
```

输出：

```text
[CURRENT] vectors=200002 low_ms=200.376 high_ms=197.171 low_ns_per_vector=1001.9 high_ns_per_vector=985.8 checksum=0xb48627881e67a6e4
[SPLIT] vectors=200002 fall_only_ms=6.767 input_low_ms=200.324 high_ms=198.203 fall_only_ns_per_vector=33.8 input_low_ns_per_vector=1001.6 high_ns_per_vector=991.0 checksum=0xb48627881e67a6e4
```

整理：

| mode | phase | total ms | ns/vector |
|---|---|---:|---:|
| current | low = falling + input change | 200.376 | 1001.9 |
| current | high = posedge + post-commit | 197.171 | 985.8 |
| split | fall-only | 6.767 | 33.8 |
| split | input-low | 200.324 | 1001.6 |
| split | high | 198.203 | 991.0 |

两个模式 checksum 一致：

```text
0xb48627881e67a6e4
```

## 5. 结论修正

`NO0229` 的 “low/high 约 50/50” 不应解释为“下降沿和上升沿都有等量顺序工作”。更准确的解释是：

> `VtypeBuffer` 的下降沿本身几乎没有实际状态工作；此前 `low_eval` 的重成本来自 bench 在 low eval 前驱动新输入，触发了低电平期间的组合逻辑传播。`high_eval` 则来自 posedge commit 以及 commit 后激活 reader 造成的后续传播。

也就是说，每个 vector 在 GrhSIM 中大致有两类真实工作：

1. **输入变化后的组合 settle**：当前被计入 `clock=false eval`；
2. **posedge state update + post-commit settle**：当前被计入 `clock=true eval`。

falling edge 本身不是慢点。

## 6. 对后续工作的影响

后续分析应避免使用“下降沿工作”这个说法，应改成：

- low/input-settle phase；
- high/posedge-commit phase；
- high post-commit propagation / commit-activated reader cone。

之前提出的下一步仍值得记录，但表述应修正为：

> 下一步优先分析 **posedge commit 后 activation fanout 与第二轮 compute 工作量**，同时对比 GSIM 如何把 input-settle 与 post-commit settle 合并/调度到 `step()` 的 `subStep0/subStep1` 中，而不是继续假设下降沿本身有大量工作。

这也解释了为什么 `NO0231` 的 empty-compute round skip 没有收益：它针对的是 high phase 第一轮 active 为空时的空 compute dispatch，而真正重的 low phase 是输入组合传播，真正重的 high phase主要是 posedge commit 与 commit-activated compute。
