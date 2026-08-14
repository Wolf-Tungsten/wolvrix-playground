# tes — SimpleTES 式结构化搜索实验系统

按 SimpleTES（arXiv:2604.19341，本地副本 `ptmp/2604.19341.pdf`）的 (C, L, K, Φ) 框架
组织性能调优类开放问题的实验。设计与串行等价论证见 [DESIGN.md](DESIGN.md)，执行纪律见
[RULES.md](RULES.md)。

## 驱动方式（无状态工作流）

每次推进 = 启动一个 goal：**`/goal tes/goal.md`**。goal 会话运行
`python3 tes/tools/tesctl.py next` 得到唯一 action，按 [playbook.md](playbook.md)
执行到底后停止。系统无状态：所有进度在任务目录的文件里。

## 任务索引

tes/ 下每个含 `config.json` 的一级子目录是一个独立优化任务，各有自己的
brief/config/state/actions/proposals/runs 与专属 evaluator.py。
新增任务：复制现有任务目录，改 brief.md / config.json / evaluator.py，并在本表登记。

| 任务 | 主题 | 状态 | 最新进展 |
|---|---|---|---|
| [grhsim-am-coremark](grhsim-am-coremark/README.md) | grhsim-am 仿真 xiangshan coremark 50k 的 Host 时间 ≤ gsim 同等负载 | 待 run-init | 系统骨架就绪（2026-08-14） |

## 共享件

- `goal.md` — /goal 入口文件（固定流程 + 纪律）
- `playbook.md` — 各 action 类型的操作步骤
- `tools/tesctl.py` — 调度器/状态机（`--task` 指定任务，单任务自动解析）
- `tools/phi.py` — Φ / RPUCG 提案构造
- `DESIGN.md` / `RULES.md` — 设计与纪律（任务无关部分）

重物（不入库）：`build/tes/LOCK`（全局串行锁）、`build/tes/ccache/`（跨任务共享）、
`build/tes/<task>/{src,evals}/`（worktree 与评估产物）。

## 相关文献与记录

- 方法论来源：`ptmp/2604.19341.pdf`
- 机制背景：`pdocs/grh-notepad/emit-cost/`（NO0001–NO0018 归因链）
- 测量纪律先例：`pdocs/grh-notepad/supernode-align/`（NO0017 测量纪律）
