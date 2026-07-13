# TNO0015 Full active-word consume experiment

记录日期：2026-07-13

来源范围：`NO0415..NO0434`，原始记录见 [NO0415](../grhsim_opt/NO0415_full_active_word_consume_implementation_gate_20260712.md) 至 [NO0434](../grhsim_opt/NO0434_full_active_word_exact_entry_runtime_gate_20260713.md)。

状态：功能与结构正确，但 native 和 exact-entry runtime 均回退，方案停止并保持默认关闭。

## 1. 实现语义

完整 compute word 在 dispatch 后保留 gate 与 local later-bit propagation，只省 per-entry clear 和 word restore；partial word、commit、fullpass 等路径保持旧协议。9 级链 synthetic 覆盖同 word 内传播与跨 partial word。

Python option/native binding 的两次接线失败都在 C++ emit 前停止并明确作废；最终 fresh SimTop 命中：

```text
full compute words  7,853
partial words          79
generated lines    -0.976%
emu text           -0.721%
```

## 2. 功能回归

candidate 完整通过：

- 100-cycle reset smoke；
- 10k、458 instructions 和 10 个 checkpoints；
- 50k、73,580 instructions 和 5 个 checkpoints；
- terminal PC `0x80001312`；
- mismatch/assert/profile leak/`input_fullpass_blocked` 为 0。

## 3. Native runtime

CPU131 fixed-ASLR A/B/A baseline spread `0.283%`：

```text
instructions   -0.717%
cycles         +1.877%
cmask6 density +1.172%
```

静态删指令收益被约 7.904B 额外 CPI/layout cost 覆盖。

## 4. Exact-entry 控制

通过 66 个 alignment=1 pads 使两版 117/117 sched entries 同址且 `.text` 同长，双边 10k/50k 功能一致。exact A/B/A baseline spread `0.075%`：

```text
instructions   -0.717%
cycles         +2.043%
cmask6 density +1.400%
```

同址后回退没有消失，说明不是单纯入口漂移。

## 5. 决策

full active-word consume 在 object 级全指标改善、功能正确，但真实执行改变了局部依赖/分支布局，导致 cycles 稳定回退约 2%。按预声明门槛停止，不默认启用，也不继续围绕该形态调参。

## 6. 规则审计与关键数据

记录类型：full active-word consume 的实现到 runtime 决策闭环。单一议题边界是“静态全指标下降能否转化为 SimTop runtime 收益”。native 与 exact-entry 是对同一候选的因果复核；该候选已停止，后续 dispatch 方案需新建 TNO。

### 6.1 功能终点

Candidate 的 100/10k/50k 依次达到 guest/model/cycleCnt/instr/PC=`101/100/96/0/0`、`10001/10000/9996/458/0x800027c6`、`50001/50000/49996/73580/0x80001312`。10k/50k checkpoints 与 direct baseline byte-exact，无 `input_fullpass_blocked`。

### 6.2 Native 与 exact-entry runtime

| Layout | Baseline mean host ms | Candidate host ms | Baseline mean cycles | Candidate cycles | Instructions delta | Cycles delta | Baseline spread |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native, CPU131 | 83,706 | 85,634 | 304,707,706,787 | 310,425,955,548 | `-0.717%` | `+1.877%` | `0.283%` |
| exact-entry, CPU131 | 77,429.5 | 79,011 | 280,108,418,087 | 285,832,429,148 | `-0.717%` | `+2.043%` | `0.075%` |

两轮均为 fixed-ASLR、50k A/B/A、五事件 `100%` scheduled。Exact-entry 两版 117/117 sched entries 同址且 `.text` 同为 `87,114,910` bytes；同址后 cmask6 density 仍 `+1.400%`，因此回退不是入口漂移。原始表见 [NO0427](../grhsim_opt/NO0427_full_active_word_native_runtime_gate_20260712.md)、[NO0429](../grhsim_opt/NO0429_full_active_word_exact_entry_build_gate_20260712.md) 与 [NO0434](../grhsim_opt/NO0434_full_active_word_exact_entry_runtime_gate_20260713.md)。
