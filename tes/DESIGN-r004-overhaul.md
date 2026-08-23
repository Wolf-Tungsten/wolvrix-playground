# r004 搜索流程修复设计（protocol & toolchain overhaul）

> 状态：已获用户批准（2026-08-23，设计评审于会话内完成）。
> 本文是变更的设计依据；实施完成后，正式变更折叠进 `tes/DESIGN.md`、`tes/RULES.md`、
> `tes/<task>/protocol.md`、`tes/<task>/playbook.md` 与 `config.json`，本文保留作历史记录。

## 0. 背景与证据基

三个 run 的台账事实（详见各 `runs/rNNN/summary.md`）：

- r001（C=3 L=8 K=2）：t0/t1 全程有收益，t2 自 s03 起 11 候选无干净改善——轨迹内前重后轻。
- r002（C=2）：账面 best 停在 s02 的 261.5s，后被三重证据 overturn 为双态快态抽签；
  真实收益（同窗口径）分布在 s01/s03/s04/s07/s08。
- r003（C=2）：t0 best 在 s02、t1 best 在 s01，之后 6~7 轮零刷新；三个建立 best 的机制
  全部是对 r002 已验证机制的重新锚定，真正的新探索（s03-s08）颗粒无收。

诊断（分析见 2026-08-23 会话记录，方法学依据 arXiv:2604.19341 SimpleTES）：

1. **L 快速饱和是论文预言的正常现象**（论文 Fig.2：L 增大初期有效、迅速饱和，
   解法是给 C 加宽）；我们 C=2~3 远小于论文默认 32，盆地锁定来得更早。
2. **每 run 前几步的"突破"主要是收割上一 run 已验证机制的库存**；论文对
   best-solution restart 的观察同样是第 2~3 次 restart 后饱和。r003 正是第二次 restart。
3. **评估噪声地板吃掉后期小收益**：双态 ×1.3-1.4 + 漂移 ±5% 使跨窗读数不可裁，
   winner 选择退化为抽签，K=2 过滤不了评估噪声，Φ 历史被 artifact 分数污染。
4. **证据供给中断**：后期假设建立在静态代理上（链数、共享度），recon 动态证据
   没有随步刷新，候选质量递减。
5. **规则与执行脱节**：RULES §4 规定 run 内轨迹独立，但 r002 的 6 个候选是跨轨迹
   迁移（且"迁移三连中"是该 run 最可靠收益通道）；信息流不入 proposal_nodes，
   RPUCG 信用分配失真。
6. **表型漏传无硬门**：r003 有 4 个候选因开关未传而成为无效测量（append-only
   勘误 corr-e00073/74/75/76）。

机器事实（2026-08-23 实测）：AMD EPYC 9654（2 socket / 2 NUMA 节点 / 384 线程）、
THP=madvise、`numactl` 可用。r002 A0056 已直接检出**同批并行 rep 内的双态分裂**
（295.0/389.2/295.0s）——抽签是 per-process 页放置运气，不是全局时间窗，这决定
修复必须作用在 rep 粒度的启动方式或 rep 粒度的裁决上。

已确认的决策（用户，2026-08-23）：目标 = 继续冲击 gsim 持平（ratio ≤ 1.0）；
落地 = 修工具链一次到位；预算 = **C=6 L=4 K=2（N=48）**；restart.max 放宽到 3；
§1.1 冒烟实验先行。

## 1. 测量协议修复（evaluator.py）——一切的前置

### 1.1 冒烟实验（先于代码改动，不占评估预算）

gsim emu 为现成二进制，`evaluator.py gsim` 模式只做协议化计时，是零构建成本的
测试载体。用台账外 eval-id（如 `smokeN`，仅写 build/ 产物，不进 ledger）跑三组对照：

- 组 A 现状：6 rep（批内绑核 12/13/14 不变）；
- 组 B：`numactl --membind=<绑核所在节点>` × 6 rep；
- 组 C：`numactl --membind=<对侧节点>` × 6 rep（错位绑定本身即对照：
  若错位一致慢、同侧一致快，NUMA 根因直接坐实；cores 12/13/14 的节点归属
  以 `numactl --hardware` 实测为准）。

每组每 rep 记录协变量：`/proc/<pid>/smaps_rollup` 的 AnonHugePages、
`/proc/<pid>/numa_maps` 节点分布（1Hz 只读采样，与计时纪律兼容，r002 有先例）、
绑核实际频率。判据：B/C 组 host_ms 双峰消失且快簇水位与 A 组快簇一致 →
NUMA 页放置为根因，主修复 = 启动命令统一 numactl 包装；若仅减轻或无效 →
主修复 = 1.2 聚簇裁决，numactl 结果一并记入 insights.md。

### 1.2 聚簇裁决（无论冒烟结果如何都实施）

- 每 eval 先跑 3 rep（批内并行、绑核不变）；检出双峰（max/min > 1.15 且簇内
  CV < 3%）自动加跑至 6 rep；rep 上限 9，超出标 `degraded`。
- **score = 快簇中位**，弃用跨簇 median（r002 A0056 的正式提请落地）；
  未检出双峰（单簇）时 score = 全部有效 rep 中位（即现状语义）。
  result.json 记录每 rep 的簇归属、簇内中位、协变量。
- 协议文本由"固定 3 rep 不因 CV 扩增"改为"rep 随簇结构自适应（双峰检出才加跑），
  不因 CV 扩增"；CV>5% 的 noisy 标记保留。

### 1.3 整批慢态兜底

6 rep 全落慢簇（与历史快带不可比）时标 `state=slow_only`；evaluator 新增
`retime --eval-id` 子命令复用已有 emu 只补计时（不重建），允许在后续窗口覆盖
该 eval 的计时段（rep 日志本为 append 式，取最新段）。

### 1.4 基线重锚

r004 run-init 用新协议重测 AM y0 与 gsim 双基线；round 2 齐平后各复测一次
（2 个 eval，预算外，沿用 run-init 基线不计 N 的既有口径）。r002 悬置的
"基线重锚"至此闭环。

## 2. 搜索结构（config.json + tesctl.py + phi.py）

- **2.1 r004 参数**：C=6 L=4 K=2（N=48）；y0 = r003/e00057（commit `1563c3d8`，
  表型 = r003 冻结 10 开关 + `--sys-task-body-outline --scan-branch-hints`）；
  `restart.max` 2→3（用户已批准）。
- **2.2 安慰剂席位退役**：K=2 两席全部回归机制候选（论文 K 的本义）。测量校准
  需求走 RULES §4 已有的"明确批准的协议动作"通道（如 1.4 的中段重锚），不占
  候选席位。
- **2.3 winner 裁决硬化**：finish-step 一律按快簇中位分数裁决；winner 与父 tip
  差值落入裁决噪声带（簇内 CV 合成）时记 `outcome=neutral`（机器可读，取代
  r001 手记的"机械 winner †"）；全失败轨迹原地耗步的语义不变。
- **2.4 Φ 适配短 L**：L=4 下 S ≤ 5 节点，RPUCG 退化为"tip + 最近 winner"属预期，
  算法不动；唯一改动 = 分数一律取快簇中位，neutral 节点在 min-max 归一化中降权，
  防止 artifact 分数污染历史。

## 3. 跨轨迹迁移合法化（RULES.md §4 / DESIGN.md §3）

规则与实践已脱节，修法是显式化而非封堵：

- round 1 保持纯独立探索（保护早期方向多样性，论文 C 的本义）；
- round ≥ 2 开放迁移席位：每 step 的 K 席中最多 1 席可引用其他轨迹的已确认机制，
  假设必须写明来源 eval，ledger 记 `migration_source` 字段；
- Φ 维持 `cross_trajectory=false`（proposal 文本仍只含本轨迹节点）；迁移材料由
  goal 会话从 insights.md 引用——承认并审计该信息通道；
- RULES §4 与 DESIGN §3 的串行等价论证相应修订（轨迹独立仅限于 round 1 与
  Φ 的 proposal 构造）。

## 4. 证据供给：recon 门控（tesctl.py + 任务 playbook）

- **recon 成为正式 action**（不占 eval 预算）：对轨迹 tip 的生产 emu 跑非计时
  profiling（`EMU_AM_BLOCK_EXECS` / perf record），产出标准化报告（热点块池、
  动态权重、活性分布）至 `build/tes/<task>/recon/<run>-<tid>-sNN/`，ledger 记
  `kind=recon`。
- **新鲜度门**：轨迹距上次 recon ≥ 2 步、或 tip 自上次 recon 后已换 ≥ 2 个
  winner 时，`tesctl.py next` 先出 recon action 再出 step。L=4 下每轨迹约 2 次。
- proposal 任务段加硬要求：候选病灶证据必须引用 recon 报告的动态权重，静态
  计数只作辅证（phi.py 模板与任务 playbook 检查单同步）。

## 5. 候选表型审计门（tesctl.py + evaluator.py）

- 候选 commit 根目录随附 `tes-candidate.json`：声明 emit_args 覆盖与预期在生产
  表型中激活的开关清单（代码内 default-off 新开关必须列出）。
- evaluator 已将实际 emit_args 写入 result.json；record-eval 断言：声明与实际
  emit_args 一致，且声明的开关确实出现在实际表型中；不一致拒绝登记。
  （r003 corr-e00073/74/75/76 的直接教训。）

## 6. 文档与看板同步

- `protocol.md`：新计时口径（聚簇裁决、自适应 rep、numactl 包装与否由冒烟定）。
- `RULES.md`：迁移席位、recon action、安慰剂退役、表型审计门。
- `DESIGN.md`：C=6/L=4/K=2 理由（论文 L 饱和 → 预算从 L 挪到 C）、串行等价
  论证按 §3 修订、restart.max=3。
- 任务 `playbook.md`：候选声明文件规则、recon 操作步骤、retime 用法。
- dashboard：Host 列改用快簇中位，增加 state/簇标记列。

## 7. 节奏、判据与停止规则

- 阶段 0：§1.1 冒烟（约半天，无预算开销）→ 结果定 1.1/1.2 主从；
- 阶段 1：工具链代码与文档（§1.2-1.4、§2-§6）；冒烟式自验：对同一 emu 重复
  测量，快簇中位跨窗口 CV < 2% 视为可裁性恢复；
- 阶段 2：r004 init（新协议重锚双基线）→ N=48 ≈ 3 天串行。
- **停止规则**：若 r004 前 2 轮（12 个 step、24 个候选）零确认收益（同窗/同簇
  口径），按论文 restart 饱和结论停止搜索并回报用户，不再续 run。

## 8. 风险

- numactl 消不掉双态 → 聚簇裁决兜底，协变量数据留作根因分析；
- L=4 下库存收割完后仍可能无新 best → recon 门控保证候选至少有新鲜动态证据，
  C=6 宽度是论文对 L 饱和的标准对冲；
- 流程变更引入新 bug → 所有门（表型审计、新鲜度、聚簇）实现为 fail-open
  可人工覆盖（playbook 登记豁免，同步 insights.md），避免状态机卡死。
