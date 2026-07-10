# NO0241：Input full-pass specialization P0 codegen A/B

日期：2026-07-09

## 1. 背景

承接：

- [NO0238](./NO0238_dynamic_fire_compare_20260709.md)：`VtypeBuffer` GrhSIM `input_low` 中 `38` 个 compute supernode 几乎每 vector 全部 fire，主因不是 fire 次数，而是 always-active 下仍保留的 changed/active 框架和大 supernode slot/ref 代码；
- [NO0239](./NO0239_no_propagate_fullpass_probe_20260709.md)：手工 no-propagate full-pass probe 使 low-only `203.141ms -> 131.593ms`（`-35.22%`），证明 compute active/change propagation 是真实 hot cost；
- [NO0240](./NO0240_input_fullpass_specialization_plan_20260709.md)：规划把 unsafe probe 收敛为默认关闭的 codegen A/B。

本轮完成 P0 codegen 原型：默认关闭，启用后生成 input-change full-pass fast path 和 `eval_compute_batch_N_fullpass()` variants。

## 2. 实现概要

新增 Python / native / C++ emit option：

```python
sess.emit_grhsim_cpp(..., input_fullpass_specialization=True)
```

也支持环境变量：

```bash
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1
```

`xs-components` flow 新增：

```bash
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1 make ... grhsim
```

默认值为关闭，默认生成物不包含 `_fullpass` 方法。

启用后，GrhSIM 额外生成：

```cpp
void eval_compute_batch_0_fullpass();
void eval_compute_batch_1_fullpass();
void eval_compute_batch_2_fullpass();
void eval_compute_batch_3_fullpass();
```

`eval()` 中新增 fast path：

- 由普通 data input change 触发时置 `input_fullpass_candidate`；
- `initial_eval`、`reset` 变化、posedge event 触发时置 `input_fullpass_blocked`；
- 满足 `candidate && !blocked` 时：
  1. 清空 `supernode_active_curr_`；
  2. 顺序调用 fullpass compute batches；
  3. 清空 active/event edge；
  4. `refresh_outputs()` 并更新 prev input baseline；
  5. 直接 return，不进入 fixed-point loop。

fullpass batch variant 复用原 supernode emit 逻辑，但：

- 每个 active word 的 `activeWordFlags` 直接初始化为常量 dispatch mask；
- 不读写 `supernode_active_curr_`；
- `ActivationEmitContext::suppressComputePropagation=true`；
- 不构造 / flush deferred activation groups。

normal `eval_compute_batch_N()` 保持不变，作为 fallback path。

## 3. 构建与生成检查

执行前：

```bash
source env.sh
set -euo pipefail
python -m pip install --no-build-isolation -e wolvrix
```

生成目录：

```text
tmp/no0241_input_fullpass_codegen_20260709/off/model
tmp/no0241_input_fullpass_codegen_20260709/on/model
```

检查结果：

- off 生成物：没有 `fullpass` / `input_fullpass`；
- on 生成物：header 中有 `eval_compute_batch_0..3_fullpass()`，`eval.cpp` 中有 `input_fullpass_candidate` / `input_fullpass_blocked` fast path；
- off/on 模型均可用 `clang++ -O3 -std=c++20` 编译成 `libgrhsim_XsReal075RobVtypebufferLarge.a`。

## 4. Correctness P0

负载：`XsReal075RobVtypebufferLarge`。

bench：临时链接同一份 GSIM object，分别链接 off/on GrhSIM。命令口径：

```bash
--vectors 20000 --verify 4096 --repeat 1 --model grhsim
```

结果：

| mode | verify | 20k GrhSIM ms | checksum |
|---|---|---:|---|
| off | pass `4096` | `43.137` | `0x88ffb13eae3268ec` |
| on | pass `4096` | `37.042` | `0x88ffb13eae3268ec` |

P0 VtypeBuffer correctness 通过。

尚未完成的 gate：BigComb / FTQ / Tage / 更大随机窗口。后续如果要默认开启或扩大适用范围，必须补这些 gate。

## 5. Runtime A/B

200k vectors，`--verify 4096 --repeat 3 --model grhsim`：

| mode | min ms | median ms | vs off |
|---|---:|---:|---:|
| off | `429.834` | `430.048` | - |
| on | `370.474` | `370.881` | `-13.81%` |

完整 GrhSIM eval 有双位数收益。

### 5.1 Phase profile

200k vectors，`--grhsim-phase-profile`：

| mode | bench ms | measured ms | low eval ms | high eval ms | low ns/vector | high ns/vector |
|---|---:|---:|---:|---:|---:|---:|
| off | `462.963` | `442.408` | `215.391` | `216.946` | `1076.9` | `1084.7` |
| on | `401.745` | `381.138` | `156.242` | `214.843` | `781.2` | `1074.2` |

解读：

- low eval：`215.391ms -> 156.242ms`，约 `-27.46%`；
- high eval 基本不变；
- 完整 eval 收益来自 input-low fast path，符合预期。

## 6. Static asm A/B

比较 off normal compute batch 与 on fullpass compute batch：

| batch | off bytes | on normal bytes | on fullpass bytes | off instr | fullpass instr | off stack | fullpass stack | off mem | fullpass mem |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `0` | `11905` | `11905` | `5056` | `2757` | `1192` | `220` | `23` | `935` | `433` |
| `1` | `7887` | `7887` | `4564` | `1738` | `980` | `122` | `76` | `699` | `436` |
| `2` | `11072` | `11072` | `8010` | `2392` | `1911` | `190` | `524` | `1027` | `896` |
| `3` | `21723` | `21723` | `19296` | `4352` | `3845` | `788` | `778` | `2111` | `1908` |
| total | `52587` | `52587` | `36926` | `11239` | `7928` | `1320` | `1401` | `4772` | `3673` |

总体：

- bytes：`52587 -> 36926`，`-29.78%`；
- static instructions：`11239 -> 7928`，`-29.46%`；
- memory operands：`4772 -> 3673`，`-23.03%`；
- stack operands 未整体下降（`1320 -> 1401`），主要是 batch2 增加；后续仍需看 register pressure。

这与 NO0239 手工 probe 的方向一致，说明本轮 codegen 原型确实把 no-propagate full-pass 收敛成了可生成、可编译、可验证的 P0 fast path。

## 7. 当前限制与风险

1. 只跑了 `VtypeBuffer` P0 correctness；还不能默认开启；
2. fast path 目前用 posedge event blocker，适合当前 posedge commit 模型；若存在 negedge/event commit，需要更精确地从 commit event expression 派生 blocker；
3. reset 变化已保守 fallback；initial eval fallback；
4. fullpass variant 仍复用大 supernode slot/ref 代码，剩余与 GSIM 的差距仍然存在；
5. fullpass 减少指令但 batch2 stack operands 增加，后续要结合 perf/stat 再看。

## 8. 下一步

建议按以下顺序推进：

1. 补 BigComb / FTQ / Tage / VtypeBuffer 小矩阵 correctness + runtime；
2. 若 correctness 都通过，跑 2M perf stat 对比 instructions/cycles；
3. 更精确地区分 event blocker，不要硬编码只看 posedge；
4. 继续压 fullpass variant 中的 slot/ref 和 stack pressure。
