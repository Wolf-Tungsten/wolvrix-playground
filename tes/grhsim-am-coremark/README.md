# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（3-rep 中位、绑核、串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- 活跃 run：**r001**（C=3, L=8, K=2，N=48；base `a88e7a2`）
- 基线（2026-08-14，同协议 3-rep 中位）：AM y0 = **273.1s**（e00001，CV 0.39%）；
  gsim target = **24.7s**（e00002，CV 1.5%）；**差距 11.06x**
- 下一个 action：`step`（t0/s01，K=2 候选）
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
