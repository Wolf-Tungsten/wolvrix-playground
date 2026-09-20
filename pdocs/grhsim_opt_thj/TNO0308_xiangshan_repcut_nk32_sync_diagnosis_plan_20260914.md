# TNO0308: XiangShan RepCut N=K=32 sync diagnosis plan

日期：2026-09-14

状态：`PLAN REGISTERED; INDEPENDENT DIAGNOSTIC IMPLEMENTATION IN PROGRESS`。

前置：[TNO0307](./TNO0307_xiangshan_repcut_nk32_node031_reserved96_ab_ba_result_20260914.md)。
用户授权先做同步归因，再依证据做一个最小候选；本轮不拆 ASC、不改 partition assignment、
CCD 映射或 push 更新端点，不修改生产默认与历史 frozen ELF/runner。

## 1. 诊断对照

独立 common-only 插桩 ELF，保持 C++17 与 model ABI；复用冻结且逐项 SHA/编译器审计的
1422 个 partition 对象。A=legacy、B=pipeline-workers，在同一诊断 ELF 中采用对称的
callback 边界计时，冻结周期每16个 step采样一次，从step1开始，C100与C10000均使用
相同配置。不按性能结果调整采样密度。

每个采样 step 保存各 lane 的 eval begin/end、update begin/end，以及 host 派发/返回时间。
worker 只写各自 cache-line 分离的槽位，host 在现有完成同步后收集；不为事件增加共享锁。
原始事件在 teardown 输出，不在测量中的每一步写日志。测试须覆盖完整性、事件顺序、
跨线程可见性、停止/异常路径，不得读取仍在写入的 worker 状态。

每 step 以 `E=max(eval_end)`、`U=max(update_end)`、`H=host_return` 定义：

- `update_begin_i-E`：该 lane 从全体 eval 完成到开始 update 的延迟；含屏障/host 派发/唤醒等。
- `update_end_i-update_begin_i`：该 lane 的 callback 本体局部墙钟。
- `U-E`：全体 eval 完成到最后 update 完成的区间，内部各 lane 的延迟与执行相互重叠。
- `H-U`：最后 update 完成到 host 观察完成的尾部延迟。

满足 `H-E=(U-E)+(H-U)`，但不能把各 lane 的 delay max 与 duration max 相加冒充精确分解。
诊断插桩样本单独归档，不混入无 probe 的正式 Host 比较；现有 PMU/上下文切换证据
与事件计时共同使用，不预先宣称已完成 futex 因果归因。

## 2. 固定运行与质量门

优先用户指定的 node031 CPU96-127、NUMA1，完整 SMT288-319 纳入监控，monitor35。
使用原 runner 先 C100、后 C10000，完成独立 AB/BA；相同 spec/pair-id、不同 staging inode。
复查资源，不因已预约而豁免 admission。仅未 launch 的 admission 允许原4次重试；
已启动样本全部保留。功能/身份/页面/worker 门和原 CPU verdict 保留；CPU residual
按既有 balanced diagnostic 边界解释，不重抽至偶然通过，不降低至少3次快照要求。

## 3. 一轮定位、一个候选

先看两个顺序中释放延迟、实际 update callback 和 host 完成尾部的变化。如主要新增
时间集中在 eval→update 放行，再构造一个仅改变该屏障的独立候选；若不支持，停止该
假设，明确报告最值得优化的实际位置，不直接扩展到全套 atomic/spin 运行时。

最小候选保持 phase 语义（任一 update 不得早于全部 eval）、start/completion 结构及
映射不变，先通过同步正确性、异常/取消、ABI/编译器/对象身份、C100 功能等门。
随后以无新增诊断 probe 的 ELF 对照 legacy 做 C100/C10000 AB/BA；必要的机制对照
另立 pair，不拿不同插桩版本直接比较性能。AB/BA 都变快且 pooled 改善至少2%才暂选
新实验 control，不要求每序各2%，不引入0.25 pp门槛。

每项实现/构建、诊断结果、候选构建与性能结果分别新增 TNO、同步 README。
不无限优化 pipeline；本轮完成后依据结果决定补测 host 参与并恢复 CCD 映射等原计划。
