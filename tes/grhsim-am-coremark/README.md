# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（3-rep 中位、绑核、串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- 活跃 run：**r001**（C=3, L=8, K=2，N=48；base `a88e7a2`）
- 基线（2026-08-14，同协议 3-rep 中位）：AM y0 = **273.1s**（e00001，CV 0.39%）；
  gsim target = **24.7s**（e00002，CV 1.5%）；**差距 11.06x**
- 当前 best：**244.3s**（e00018，inline scalar helpers，较 AM y0
  **-10.55%**）；仍为 gsim 的 **9.89x**，AM/gsim 绝对差距关闭 11.60%；
  t0/t1/t2 步进 **3/3/2**
- t1/s03（A0011）：winner c2 `--inline-scalar-helpers` 将窄标量 slice/
  移位/signed helper 改为生成 header 内 `constexpr`，244.3s（vs t1 tip
  **-9.69%，CV 1.62%**），3 rep difftest 与 17/17 ctest 全过；至少
  531K 个静态调用站点暴露了跨 TU helper 边界的一阶成本，c2 已入
  t1/main 并刷新 run best。c1 `stateLayout=affinity` 已修正宽 init store
  物理顺序，但正式流水线仍于 2399.1s compile_timeout，无运行时证据
- t0/s03（A0010）：两个候选均越过第 3 轮 3% 门。winner c1
  `--source-part-activity-guard` 247.5s（vs e00010 **-9.44%，CV 0.82%**），
  334 个静态 part 调用以精确 64-bit activity 区间预检，静默时跳过调用与逐 byte
  扫描；c2 `--wide-storage-first-touch` 257.4s（**-5.79%，CV 1.15%**），
  将 Block-touched 宽态跨度压缩 65.66%、page 减少 7.69%，首次确认布局 locality
  是有效运行时轴。两者 ctest 17/17、3 rep difftest 全过；c1 已入 t0/main
- 第 2 轮小结（A0009）：6 候选仍无 ≥5% 一阶收益；t0 弱正组合回到 y0、
  t1 激活恒写 +6.9% 且 preset 摘除 difftest 死锁，粗粒度机械路线关闭；
  t2 守卫事件门控 -1.10% 为唯一干净收益。commit 写站 7.32G compare/
  97.35% idle 是唯一动态大数锚点，但朝代门控仅覆盖 6%，正确形态指向
  commit 内锥状态输入快照检测。第 3 轮候选须先有离线覆盖/成本模型且
  目标 ≥3%，否则不再消耗正式 eval
- t2/s02（A0008）：commit 写站空转实测坐实（`--commit-station-stats` 离线
  插桩：7.32G compares、idle 97.35%）但朝代门控证伪——静态覆盖仅 6%
  （其余写站 next 锥在 commit 块内部），协议中位 +13.5%（噪声日 CV 41.7%，
  rep5≈基线，机制≈中性），路线关闭，正确机制指向 commit 内锥状态输入
  快照检测；**winner c2 `--guard-event-gating` 269.7s（-1.10%，CV 0.88%
  干净窗口）——纯 fatal/fwrite 守卫块（b83400+b26518）按 changedResults_
  事件槽整块门控，negedge 半数触发消除，已入 t2/main**
- t1/s02（A0007）：块间机械首轮触探双证伪——`--branchless-activation` 289.2s
  （+6.9%，条件激活写承力、轴关闭）；`--am-skip-preset-activation` difftest
  死锁（preset→act.b 双激活承力）；winner e00011 机械入 t1/main（语义中性：
  默认 off 开关，emit 不携带即逐字节等价，回退不继承）
- t0/s02（A0006）：`--init-zero-elision` 元杠杆落地（init() 1.82M→4.2 万行，
  runtime.o 572s→14.7s，emu_build -56%，运行时中性）——布局轴前置已备
  （分支 tes/r001/t0/s02-c1 常备）；弱正组合 273.3s 可加性证伪（~1% 级微调
  路线到头）；winner e00010 机械入 t0/main；evaluator parser 修复一处
- t2/s01（A0004）：亲和布局+init修复 再遭 compile_timeout（炸弹是 init()
  182 万行死 store 流本身，98.2% 宽池 store 为字面量 0——方向升级为
  `--init-zero-elision`）；宽态炸开 272.7s 持平证伪（ABTB 族命中但 NO0018
  已吸收其成本，轴关闭）；t2/main 噪声级 adopted c2（+0.13% < CV）
- t1/s01 双攻坚（A0003）：状态亲和布局 compile_timeout（init 写出与布局耦合
  破坏 clang idiom 识别，修复方向已定位、可重测）；resize 胶消除弱正（-0.95%，
  94.1% 静态胶消除仅 ~1% 运行时，胶归一降级非一阶）
- t0/s01 双探针（A0002）：chunk 12000 证伪（+2.2% 回退，跨 chunk 往返非一阶）；
  branchy-mux 弱正（-0.74%，分支轴未否决、非一阶）
- 第 1 轮小结（A0005）：静态 emit 单旋钮空间扫完、收益饱和 ~1%/个；主失败
  模式是编译预算门（2/6）；`--init-zero-elision` 为元杠杆；块间机械
  （调度器/事件/commit）是唯一未触探大轴
- 下一个 action：`step`（r001/t2/s03，K=2；由下一 action 的 t2-local proposal
  选候选，`cross_trajectory=false` 下不注入本次 t1 结果）
- 已知参考点：AM Host 324.0s（emit-cost NO0018 收口，2026-08-14；与 r001 实测 273.1s
  有约 15% 漂移，单点数字注意机器状态/布局影响）
- run-init 备注：evaluator 修了 emu 相对路径 exec bug；金标改为计数窗
  （73584/49998 ±16/±8，覆盖两种 emu 停止点确定性小差）。详见
  [A0001](actions/A0001_run-init_基线与系统校准_20260814.md)

## 本任务构成

- `brief.md` — 常驻任务指令（目标、硬约束、已知机制背景）
- `protocol.md` — 评估协议（Φ 会原样内联进每个 proposal）
- `playbook.md` — 任务专属操作细节（基线流程、候选评估命令、结果解读）
- `config.json` — 默认参数与路径（run-init 冻结）
- `evaluator.py` — 评估器 V：`run`（候选/基线全流水线）与 `gsim`（现存 emu 协议化计时）两模式
- `state/` — `run.json`、`ledger.jsonl`（append-only）、`insights.md`
- `actions/` `proposals/` `runs/` — action 笔记、Φ 快照、run 清单/总结
- 评估输入：gsim 导出的 exec-GRH（路径见 config `paths.exec_json`，run-init 记 sha256）

## 快速命令

```bash
python3 tes/tools/tesctl.py status            # 状态
python3 tes/tools/tesctl.py next              # 下一个 action
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <wt> --eval-id eNNNNN
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id eNNNNN
```
