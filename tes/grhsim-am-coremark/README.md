# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（3-rep 中位、绑核、串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- 当前 run：**r002 进行中**（C=2, L=8, K=2，N=32；base/y0 = r001 best
  `9c0a89db`；2026-08-20 init-run，见 [A0034](actions/A0034_run-init_r002新机器clang与并行rep基线_20260820.md)）
- 基线（2026-08-20，新机器 + clang 21.1.8 + rep 绑核并行协议，3-rep 中位）：
  AM y0 = **619.0s**（e00001，CV ~0.0%）；gsim target = **46.8s**（e00002，
  CV ~0.0%）；**起跑差距 13.23x**。**⚠ 基线完整性红旗（A0035）**：e00001/e00002
  测于晨间慢机器态，同配置下午参照 452.8s（差 27%），vs 基线/gsim 的 ratio
  暂不可裁，待重锚
- t1/s02（2026-08-21，[A0039](actions/A0039_step_t1s02_二级活动摘要扫描与同窗安慰剂_20260821.md)）：
  recon 驱动（recon-t1s02：commit 29.7%、43 commit 巨块独占 29.0%、b116236
  单块 12.63% 前端绑定、扫描骨架墙钟缺口 ~50%）；**winner e00009 = 414.867s**
  （`--activity-summary-scan` 二级活动摘要扫描，2,076 探针 + 576,615 镜像站点，
  off 逐字节等价，已入 t1/main；t1 有效 emit_args = config 调度 + 3 旋钮 +
  activity-summary-scan）；**机制量级不可裁**：同窗安慰剂 e00010（t1 tip 原样）
  574.637s 锚定本窗=慢态，c1 同窗名义 -27.8% 但双态翻转可吸收，c1 读数低于
  快态带下沿提示机制方向为正（2%~28% 不可裁），t1/s03 需同态锚定。evals 10/32
- t0/s02（2026-08-20 晚，[A0038](actions/A0038_step_t0s02_宽站detect快速路径与守卫变量聚簇_20260820.md)）：
  recon 驱动（recon-t0s02：commit 相 32.4% 集中、43 宽站巨块独占 31.7%、守卫
  双块 9.2%、rounds 恒定 2.00/eval）；**winner e00007 = 261.543s**
  （`--wide-detect-fast-path`，commit 宽站 memcmp/memcpy 快速路径，名义
  -27.9%，同窗逻辑控制排除机器态抽签，已入 t0/main；t0 有效 emit_args =
  默认调度 + 9 旋钮 + wide-detect-fast-path）；c2 守卫变量聚簇 358.456s
  亚分辨证伪（9.2% 池非散射 miss 主导，守卫布局路线关闭）。evals 8/32
- r002 第 1 轮 round-summary（2026-08-20，[A0037](actions/A0037_round-summary_第1轮跨轨迹小结_20260820.md)）：
  两轨迹各完成 s01，round best = e00003 **362.869s**（对同窗 config 参照 452.803s
  **-19.86%**；vs 基线 ratio 因基线慢态污染不可裁）。收敛：**常量/状态瘦身族在新
  输入图整体关闭**（t0 死宽池 0.46% 证伪 × t1 常量内连同频中性互证）；发散：
  **调度点一阶（gsim-aligned 单变量 -16.4%），分区/调度轴重开**（旧图 NO0002
  不适用新输入）。现协议只可分辨 ≥30% 效应，协议升级（机器态记录/跨窗口批次/
  基线重锚）待用户裁决
- t1/s01（2026-08-20，[A0036](actions/A0036_step_t1s01_t1链迁移与常量内联重实现_20260820.md)）：
  winner e00006 = 443.899s（**快窗口抽签，非机制收益**；`--inline-scalar-constants`
  重实现：12,795 只读窄常量/711,978 读取点字面量化，off 逐字节等价，已入 t1/main；
  验证同频 3.7GHz 下与 c1 差 -1.6%/-6.1% = 机制中性）。**刻画 ×1.3-1.4 双态环境
  混杂**（快簇 ~430s/慢簇 ~590s，20-40min 翻转；频率轨迹证伪 CPU 频率，嫌疑
  THP/NUMA 页放置）：现协议只能分辨 ≥30% 效应；t1 常量/状态瘦身族在新图关闭；
  测量协议升级（rep 期机器态记录/跨窗口批次/基线重锚）提请用户裁决
- t0/s01（2026-08-20，[A0035](actions/A0035_step_t0s01_机制链迁移与死宽态消除_20260820.md)）：
  winner e00003 = **362.869s**（gsim-aligned 默认调度点 + r001 t0 winner 9 旋钮链，
  已入 t0/main；t0 有效 emit_args = CLI 默认调度 + 9 旋钮）。因子分解：调度点
  一阶（gsim-aligned 比 config 点快 16.4%，分区轴在 r002 重开）、旋钮链在
  config 点上 -14.1%；死态瘦身族证伪（新图死宽池仅 0.46%）。测量教训：
  evaluator `--emit-args` 为整体替换，候选须显式携带调度点全参数
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
