# A0087 step：r004/t0/s01 event 优先与 unsigned-div64（2026-08-23）

对应 `next` = `step-resume`，轨迹 `t0`，step 1/4，K=2。`begin-step` 已在本 action
恢复前完成并分配 e00087/e00088；本次从 pending `[1,2]` 继续，没有重复 begin-step、
没有重跑已登记候选，也没有手改 `run.json`。Phi 唯一来源为 r004 AM 基线 e00085
（commit `1563c3d837fc`，Host **193.403s**，完整 12 开关表型）。两项候选均引用
A0086/e00085 recon 的动态权重，分别处理 task 守卫池与 unsigned division 池，机制互异。

## 候选与结果

| 候选 | eval / commit | 来源 -> 动态病灶 -> 局部改动 -> 可证伪预期 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 `--sys-task-event-first` | e00087 / `066eac1` | e00085 -> b90656/b90657 执行 88,260/100,791 次、合计占总块 cycles **4.683%**，outline 后仍密集执行 `fire && event` -> 对非 final system task 把纯读取条件改排为 `event/pending && fire`，pending 累积及 once/pending 状态更新不变 -> 若稀有 event 能挡住共享 fire 读取，应越过 3% noise 门；否则该局部顺序不是一阶成本 | **191.726s**（191.726/191.213/195.341s，CV 1.17%，单簇、非 noisy），`compile_s=640.8s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-0.87%** | 弱正向但未越 3% 门；非确认收益 |
| c2 `--inline-unsigned-div64` | e00088 / `7083852` | e00085 -> b93085 执行 100,053 次、占总块 cycles **1.159%**，生产代码有密集 `divide_value(...,64,false)` -> 64-bit unsigned `Div` 生成 instruction-id 唯一 RHS 局部量及 `rhs==0 ? 0 : lhs/rhs`，signed、窄宽度与 Mod 保持 helper -> 若跨 TU helper 边界是可见成本，应越过 3% noise 门；否则原生化只给小幅或零收益 | **189.829s**（189.829/189.005/193.632s，CV 1.29%，单簇、非 noisy），`compile_s=643.5s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-1.85%**，同窗较 c1 **-0.99%** | raw-score winner；`finish-step` outcome=`initial`，未越 3% 门 |

两个 `tes-candidate.json` 都声明完整父表型的单一增量；正式 evaluator 显式传入 12 项
冻结父表型再追加候选开关，`result.json.emit_args` 与声明逐项完全一致。生产 engagement
核对显示 c1 重排 **7,236** 个 system-task event 守卫（其中 **7,235** 个调用既有
outlined fwrite body）；c2 原生化 **1,252** 个 unsigned-64 Div，全部位于动态热点
b93085。开关缺席或显式 false 时，候选自测确认生成文件逐字节不变。

## 裁决与机制分析

- 两次正式评估严格串行，只通过任务 evaluator；每个候选均在独立 wbuild/emu_build
  完成全量构建、17 项回归、金标 difftest 和绑核 3 rep。两批都是单簇且 CV <1.3%，
  c2/c1 的 0.99% 同窗差可用于 raw 排名，但仍小于 r004 的 3% adjudication noise。
- c1 确实覆盖 recon 指出的 7,235 站 task 池，但只得到 0.87% 名义改善。事件优先能
  减少无事件时的 fire 读取，却没有消除 event 谓词本身或其上游生成；当前证据不支持
  继续做同类语法重排。重开前需要 event/fire 命中率或按条件分解的动态成本。
- c2 把 1,252 个目标调用全部集中命中 b93085，避免跨 TU helper 调用且 RHS 只加载
  一次，名义改善 1.85%，并在相邻测量窗口胜 c1 0.99%。这说明该形态有小幅正向信号，
  但结果仍在 noise 带内；不能把它写成已确认的 1.85% 因果收益，也不能据此外推 signed
  Div 或 Mod。
- `finish-step` 按 raw score 将 e00088 快移到 `tes/r004/t0/main`，作为 t0 的首个
  `initial` 节点和当前 `best_overall`。这不是 `outcome=win`；r004 AM/gsim 口径由
  8.512x 名义降至 **8.355x**，目标仍远未达到。

## 后续建议

t0 再次到期时应先对 e00088 做新 recon：若 b93085 cycles 明显下降，再围绕该块寻找
覆盖同一动态池但机制不同的优化；若权重不降，则关闭 unsigned-div helper 边界微调。
task 守卫方向在获得 event/fire 命中率或参数准备动态分解前不再做条件顺序、hint 或
冷体布局精修。当前状态机的下一 action 是 **t1/e00085 recon**（非计时 profiling）；
本 action 只预告，不启动它。
