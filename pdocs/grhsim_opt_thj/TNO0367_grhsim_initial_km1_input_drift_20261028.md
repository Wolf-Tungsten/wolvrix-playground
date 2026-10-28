# TNO0367：默认路线初解 km1 增大与旧 RTL 复用问题

日期：2026-10-28。承接 [TNO0366](./TNO0366_grhsim_clean_default_completion_20261028.md)。

## 结论

默认入口发现 `build/xs/rtl/rtl/SimTop.sv` 已存在时跳过当前 Scala 的 RTL 生成，实际读取了旧 RTL。它与此前 portfolio8 使用的 `candidate_v4/rtl` 不同。因此没有保持历史输入口径，不能把 km1 增大仅归因于 seed 波动，也不能称为对原来完整优化路线的同输入固化。

39,450,970 确实是这份超图八次求解的最低可行值；数值本身没有抄错。全流程功能通过不证明历史优化已完整继承。

## 同一计分公式复核

使用新工具 `grhsim32_score` 重新读取旧 `resource_multiconstraint.hgr` 和旧 portfolio8 的 `best_assignment.part32`，输出 `0 27912141 1`。旧值 **27,912,141** 可由同一个完整图计分器复现且满足容量条件；没有把 reduced31 与 full32 km1 混淆。

| 指标 | 此前 portfolio8 | 本轮默认路线 |
| --- | ---: | ---: |
| 最低完整图 km1 | 27,912,141，seed 1 | 39,450,970，seed 6 |
| ASC 数 | 301,184 | 301,173 |
| 超边数 | 584,259 | 589,150 |
| pin 数 | 240,457,882 | 240,572,477 |
| 超边权重总和 | 40,738,017 | 41,851,234 |
| ASC 5 的 scalar inventory 权重 | 217,808 | 289,284 |

km1 数字增加 **41.34%**，超边权重总和只增加 **2.73%**，不是简单的全局权重同比放大。节点归属、边连接与六维负载分布均有变化。ASC 编号不是跨任意 RTL 的稳定标识，此表不将编号相同视为完整逻辑集合相同的证明。

六维总量旧图为 `2533632,2533632,3243157,3229418,4035822,5779329`；新图为 `2533632,2533632,3243071,3229332,4044477,5779243`。总工作近似不变不代表大 ASC 和可划分性不变。

## 上游输入漂移

两份 filelist 都含 2,100 个文件；按文件名匹配有六个文件不同：`CommitIDModule.sv`、`Ifu.sv`、`LogPerfEndpoint.sv`、`NewCSR.sv`、`PreDecode.sv`、`SimTop.sv`。

关键差异可在 `LogPerfEndpoint.sv` 观察：旧保留路线打印 `counter`，本轮读入的旧 RTL 仍打印 `next_counter`，使打印逻辑继续引用加法组合锥。此前这项改动及其解除部分 memory/ASC 共置的效果，已有 [TNO0321 语义审计](./TNO0321_xiangshan_counter_print_rtl_semantic_audit_20260915.md) 和 [TNO0323 结构结果](./TNO0323_xiangshan_counter_print_asc_split_result_20260915.md) 记录。打印当前值与 next 值并非严格日志等价。

当前 `PerfCounterUtils.scala` 已有打印 `counter` 的代码，SHA-256 为 `e3f1ddc1abd95f263348884461fcb99f5568f3671a3b618856dc173228ef0ced`，与历史 candidate_v4 的生成记录相同。问题是默认入口绕过了这份源码。

固定三个 memory、row_limit=2 和六维方法不等于固定上游 RTL。本次确认输入漂移，但尚未通过单因素重生成/求解量化每个差异对 41.34% 增量的贡献，不能排除当前前端和 solver 构建的其它影响。

## 修正与验证

默认 `--rtl` 改为未指定；未显式提供 `--rtl` 或 `--filelist` 时，在本次输出目录执行 `sim-verilog`，不因全局旧 SimTop 存在而跳过。显式提供的 RTL/filelist 仍作为输入直接读取。没有引入历史 JSON/HGR、指定迁移端点或中间历史校验。

新增回归覆盖“旧 SimTop 存在仍生成新 RTL”和“显式 RTL 不启动生成器”。共 **46 项相关测试通过**，Python 编译及 `git diff --check` 通过。计分复核和测试日志保存在 `wolvrix/build/artifacts/grhsim32-km1-audit/`。

修正后尚未重跑香山全量，因此 **没有新的 km1 或 walltime**；此前 39,450,970 / 13.102951 s 保留为旧 RTL 输入的实际结果，不能作为完整恢复历史优化路线的性能结论。实现见 [默认入口](../../scripts/grhsim32.py)、[测试](../../scripts/test_grhsim32.py) 和 [使用文档](../../docs/grhsim32.md)。
