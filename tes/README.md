# tes — grhsim-am 性能调优的结构化搜索（SimpleTES 式）

按 SimpleTES（arXiv:2604.19341，见 `../ptmp/2604.19341.pdf`）的 (C, L, K, Φ) 框架组织
grhsim-am 仿真 xiangshan coremark 50k 的性能调优：目标 Host wall time 不劣于 gsim
同等负载。设计与映射论证见 [DESIGN.md](DESIGN.md)，执行纪律见 [RULES.md](RULES.md)。

## 当前状态速览

- 活跃 run：无（系统已初始化，等待第一个 goal 执行 run-init）
- 下一个 action：`run-init`（冻结配置、pin 现场、双基线测量）
- 默认参数：C=3, L=8, K=2（N=48），见 [config.json](config.json)

## 如何使用

每次推进 = 启动一个 goal（如「推进 tes 下一个 action」）。goal 会话加载
`.agents/skills/tes` skill，运行 `python3 tes/tools/tesctl.py next` 得到唯一 action，
按 playbook 执行到底后停止。系统无状态：所有进度在 tes/ 的文件里。

## 目录

- `brief.md` — 常驻任务指令（x0）：目标、硬约束、已知机制背景
- `config.json` — 默认参数（run-init 时冻结）
- `state/` — `run.json`（活跃 run 状态机）、`ledger.jsonl`（append-only 评估台账）、`insights.md`
- `actions/` — action 笔记（`Axxxx_类型_主题_日期.md`）
- `proposals/` — Φ 生成的 proposal 快照
- `runs/` — 每个 run 的 `manifest.json`（冻结配置/基线/指纹）与收口 `summary.md`
- `tools/` — `tesctl.py`（调度器）、`phi.py`（Φ/RPUCG）、`evaluate.py`（评估器 V）

重物（不入库，在 `build/tes/`）：`src/`（wolvrix worktree）、`evals/e*/`（每次评估的
构建/emit/emu/日志/result.json）、`ccache/`、`LOCK`（串行锁）。

## 相关文献与记录

- 方法论来源：`ptmp/2604.19341.pdf`
- 机制背景：`pdocs/grh-notepad/emit-cost/`（NO0001–NO0018 归因链）
- 测量纪律先例：`pdocs/grh-notepad/supernode-align/`（NO0017 测量纪律）
