# NO0231 Empty-compute round skip A/B 负向记录（2026-07-09）

## 1. 背景

`NO0230` 的 eval trace 显示：`VtypeBuffer` high phase 常见形态是：

1. round 1：`active_in=0`，但 clock/event 触发 posedge commit；
2. commit touch writes，并设置 `commit_activated=1`；
3. round 2：消费 commit 激活出来的 active readers。

因此一个自然的微优化尝试是：当 round 入口已知没有 active compute supernode 时，跳过 compute batch dispatch，只执行 commit batch。理论上可省掉 high phase 第一轮的若干空 compute batch 调用。

## 2. 实验实现

临时实现点：`wolvrix/lib/emit/grhsim_cpp.cpp` 的 `eval()` 生成逻辑。

实验做法：

- 增加 `active_flags_maybe_nonzero`；
- initial/input seed 时置真；
- round 开始时若该值为 false，则不调用 compute schedule batches；
- commit 之后仍使用既有 `grhsim_any_active_flags(supernode_active_curr_)` 判断下一轮，并把下一轮 active 状态写回 `active_flags_maybe_nonzero`；
- perf trace 与普通路径都加同样逻辑。

注意：该实验代码已在测后撤回，当前源码不保留此优化。

## 3. 验证与 A/B 结果

重建 skbuild 后，用独立 build dir 生成普通 `GRHSIM_PERF=off` 模型：

```text
testcase/xs-components/build/no0231_compute_skip_20260709/raw_bench/
```

### 3.1 VtypeBuffer

命令：

```bash
PYTHONPATH=$PWD/wolvrix/build/skbuild/python:$PWD/wolvrix/app/pybind \
make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0231_compute_skip_20260709/raw_bench \
  BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3
```

结果：

| model | baseline NO0228 ms | compute-skip ms | delta |
|---|---:|---:|---:|
| GSIM | 206.247 | 204.294 | -0.95% |
| GrhSIM | 410.359 | 410.009 | -0.09% |

VtypeBuffer GrhSIM 基本持平，收益低于噪声级。

### 3.2 FTQ / Tage 补测

使用同一 compute-skip build dir 补测：

| case | model | NO0226 raw ms | compute-skip ms | delta vs NO0226 |
|---|---|---:|---:|---:|
| `XsReal053FtqFtqLarge` | GSIM | 384.663 | 383.388 | -0.33% |
| `XsReal053FtqFtqLarge` | GrhSIM | 516.147 | 525.719 | +1.85% |
| `XsReal043TageTageLarge` | GSIM | 306.343 | 311.909 | +1.82% |
| `XsReal043TageTageLarge` | GrhSIM | 445.004 | 449.426 | +0.99% |

FTQ/Tage 不是严格同 build A/B，存在同日重建噪声；但至少没有看到可支撑保留优化的明确正向信号。

## 4. 结论

empty-compute round skip 不建议保留：

- VtypeBuffer 的目标场景只得到 `-0.09%`，属于噪声级；
- FTQ/Tage 补测偏负；
- 该优化需要在 eval 状态机中维护额外 active 状态，增加语义风险；
- `NO0230` 已显示 high phase 的真实工作主要来自 commit 后激活的第二轮 compute，第一轮空 compute batch dispatch 并不是主要成本。

因此本实验代码已撤回，后续不沿这个方向继续投入。

## 5. 下一步

下一步应继续沿两个更可能有收益的方向推进：

1. **减少 commit 后 activation fanout / 第二轮 active compute 工作量**：high phase 真正重的部分不是进入 commit 前的空 compute，而是 commit 之后被激活的 reader cone。
2. **回到宽字 lane / producer fusion 的结构化优化**：`NO0224`-`NO0227` 已证明宽字 `std::array<uint64_t,N>` materialize 与 batch 内宽字表达仍是重要代码形态问题；但应做结构化 lowering，而不是字符串级 assign fusion。
