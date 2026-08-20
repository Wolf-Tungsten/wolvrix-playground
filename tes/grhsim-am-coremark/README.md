# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（3-rep 中位、绑核、串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- 当前 run：**r002 进行中**（C=2, L=8, K=2，N=32；base/y0 = r001 best
  `9c0a89db`；2026-08-20 init-run，见 [A0034](actions/A0034_run-init_r002新机器clang与并行rep基线_20260820.md)）
- 基线（2026-08-20，新机器 + clang 21.1.8 + rep 绑核并行协议，3-rep 中位）：
  AM y0 = **619.0s**（e00001，CV ~0.0%）；gsim target = **46.8s**（e00002，
  CV ~0.0%）；**起跑差距 13.23x**
- r002 环境刻度：AMD EPYC 9654（384 线程）；输入切换为 wolvrix 自解析
  post-stats JSON（sha256 cbd78c0b…3246，取代 gsim 导出 exec-GRH）；rep 批内
  并行绑独立物理核（12/13/14），并行批均匀抬升 ~15-18%（AM +14.8%、gsim
  +18.1%，两侧同协议可比）；r001 绝对读数自此仅作历史
- r001 已收口（2026-08-20，A0033）：best **194.2s**（e00045 `9c0a89db`，旧机
  较 AM y0 -28.89%、gsim 7.87x、差距关闭 31.75%）；轨迹 best t0 194.2 /
  t1 219.0 / t2 254.5；候选 48/48 走满（ok 44 / compile_timeout 3 /
  difftest_fail 1）。机制族裁决与 restart 建议（已采纳为 r002 y0 与 C/L/K）见
  [runs/r001/summary.md](runs/r001/summary.md)
- r001 各 step/round 笔记见 [actions/](actions/)（A0001–A0033，append-only）

## 本任务构成

- `brief.md` — 常驻任务指令（目标、硬约束、已知机制背景）
- `protocol.md` — 评估协议（Φ 会原样内联进每个 proposal）
- `playbook.md` — 任务专属操作细节（基线流程、候选评估命令、结果解读）
- `config.json` — 默认参数与路径（run-init 冻结）
- `evaluator.py` — 评估器 V：`run`（候选/基线全流水线）与 `gsim`（现存 emu 协议化计时）两模式
- 评估构建规则见 [`playbook.md`](playbook.md)「构建与依赖复用」：候选 `wbuild`/
  `emu_build` 按 eval 隔离，FetchContent 依赖与 `build/tes/ccache` 复用，正式评估
  不联网；不要把新 build 目录误解为重新下载依赖
- `state/` — `run.json`、`ledger.jsonl`（append-only）、`insights.md`
- `actions/` `proposals/` `runs/` — action 笔记、Φ 快照、run 清单/总结
- 评估输入：wolvrix 自解析 XiangShan SV 的归一化 GRH（post-stats JSON，路径见 config `inputs`，run-init 记 sha256；r002 起取代 gsim 导出的 exec-GRH）

## 快速命令

评估前先遵守上面的“构建与依赖复用”规则：候选 build 目录隔离，FetchContent
依赖和 ccache 复用，不联网、不手工重建依赖。

```bash
python3 tes/tools/tesctl.py status            # 状态
python3 tes/tools/tesctl.py next              # 下一个 action
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <wt> --eval-id eNNNNN
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id eNNNNN
```
