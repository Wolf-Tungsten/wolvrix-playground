# TNO0258：SimpleTES control 偏差作废与 mirrored 测量协议修复

日期：2026-08-27

## 1. 阶段结论

TNO0257 启动的 post-g158 research 已按指示终止。该实例及其全部后代只作为
诊断档案保留，不再 resume、不作为 seed、不进入 landing 决策，也不引用其中的
score 作为性能证据。最终冻结点为：

```text
output root:
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_gpt56sol_max_fresh_20260827_170020

instance:
2026-08-27/instance-0c4c9416

stop:
2026-08-27 19:19:08 +08:00 SIGTERM

final checkpoint:
db_state_191910
```

终止后 launcher、main、generation、evaluation 和 Codex 子进程均已退出。最终
checkpoint 记录 `6` 次 generation attempt、`2` 次 completed evaluation、
`1/32` valid、`1` 次 generation failure 和 `3` 次 cancellation。冻结树显示的
best `1.0041417447` 不是可接受的正式结果。

这次作废只影响上述 research 树。TNO0256 中 g158 落地前后的正式同 CCD
ABBA+BAAB 结果 `43,702.00 -> 42,959.00 ms`、提升
`743.00 ms/1.700151%`、order gap `0.232711 pp` 仍然有效；Wolvrix 默认配置
和 post-g158 baseline pin 均未改变。

## 2. 根因证据

### 2.1 空 control 不应产生非 1.0 的 initial score

旧 initial evaluation 的 control 与 candidate-control 是同一个二进制：

```text
ELF SHA-256:
a5559e06c4615fbd80fc5289b465ecbc7220e04cdf9b3a4e00ff525227814a9e

ELF size:
83,517,504 bytes

ABBA walltime:
A = [42,371, 42,382] ms, mean 42,376.50 ms
B = [42,809, 43,271] ms, mean 43,040.00 ms

raw same-artifact delta:
-663.50 ms / -1.565726%

old initial score:
0.9845841078066915
```

image 与 NEMU 的 SHA-256 也分别相同。instructions 几乎完全一致，而 candidate
cycles 约高 `1.546%`、backend stalls 约高 `3.91%`，说明这里测到的是运行期
漂移，不是代码差异。旧 evaluator 只对 initial control 跑四样本 ABBA，并把
同码 A/B 的瞬时比值直接作为初始 score，因此把环境噪声错误编码进了搜索树。

### 2.2 唯一候选也未通过 order 稳定性

旧树唯一完成的真实候选给出 pooled：

```text
control 44,488.50 ms -> candidate 44,305.00 ms
delta   +183.50 ms / +0.412466%
```

但分 order 后为：

| order | CPU | control mean | candidate mean | improvement |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 164 | 44,412.00 ms | 44,343.00 ms | 0.155363% |
| BAAB | 160 | 44,565.00 ms | 44,267.00 ms | 0.668686% |

两者相差 `0.513323 pp`，超过既定 `<0.25 pp` 门槛；而且旧 runtime 在 ABBA
与 BAAB 之间重新选择了落点。故 pooled 正数不能证明候选存在稳定收益。新协议
会把同一份证据判为 retryable infrastructure outcome，并重跑完整八样本组。

## 3. 修复后的测量协议

SimpleTES commit：

```text
e107401b95ceec3b2fdad33742abb4d12b80547f
```

实现采用一个不可拆分的 `ABBABAAB` 八样本组：前四样本是 ABBA，后四样本是
BAAB；整个组只选择一次 CCD、target CPU 与 NUMA node。每个样本仍执行关闭
ASLR、whole-CCD pre/monitor gate、CPU affinity、NUMA、PMU 和功能审计，并由
evaluator 验证八个样本实际使用同一个 target CPU。

接受条件新增：

- ABBA 与 BAAB 的 improvement 差值必须严格小于 `0.25 pp`；等于或超过均将
  整个八样本组标记为 retryable，不能计 valid。
- empty control 同样必须跑完整八样本；同一 artifact 的 pooled self-bias 必须
  严格小于 `0.25%`。
- control 通过门禁后，对外 score 固定为精确 `1.0`，headline delta 固定为
  `0`；原始 A/B 均值、样本、双 order 结果和 self-bias 完整保存在 diagnostics，
  不用归一化掩盖测量问题。
- 任一样本中途遇到基础设施失败时，已经完成的样本、失败 index/role、固定落点
  和 order diagnostics 都保留在 retry history 中。

runtime/evaluation/attempt schema 已由 `2` 提升到 `3`。launcher 在 resume/seed
时除 parent/Wolvrix pin 外还检查 evaluator result schema；因此旧实例即使 pin
相同也会 fail-close，不能被新的搜索误用。

## 4. 回归结果

```text
focused GrhSIM tests: 127 passed
full SimpleTES tests: 277 passed, 24 warnings
compileall: PASS
git diff --check: PASS
validate-only empty control: PASS
GPT 5.6 Sol max 64/32, 4-gen/1-eval dry-run: PASS
```

测试覆盖八样本顺序、同 CPU 证明、control 精确归一化、两种 `0.25` 边界、
完整组 retry、失败中途证据保留、malformed placement 拒绝，以及 schema-v2
checkpoint 的 resume/seed 拒绝。此次改动仅修改 SimpleTES bench 和测试，没有
修改 Wolvrix 源码或默认优化。

## 5. 冻结产物校验

旧 final checkpoint 的关键 SHA-256 为：

```text
metadata.json   cca75e3547a9999982445a29e5e6e69fe7f3c59404cafdaf7cbd24e99798da8f
config.json     39a6864ac1f35904c70721b14d1939b6a0711f91a636b405832e40e7fc7bd074
policy.json     3ecc3c458191ab03ecd8304f240b71d95e705146bfcd4d08332d28b6769eca80
nodes.json      d360b8d9b7b8e010f057416cdf1d7891f02831dc3d39bf2c1f1d2f8cabd9dec9
best_program    3edd564a8d571c2224399005ccacbabdfecb8163d3336a66a3ce7a2096557f4b
scores CSV      74bf766af8214f5c26b57aae2bc156dbb6d40c420785b9b8be181b1e367c2aa9
```

这些 hash 仅用于证明冻结档案未被改写，不代表其性能结论有效。下一轮必须建立
独立 fresh output root，并先看到 schema-v3 control score 精确为 `1.0` 后才允许
generation 结果进入有效计数。
