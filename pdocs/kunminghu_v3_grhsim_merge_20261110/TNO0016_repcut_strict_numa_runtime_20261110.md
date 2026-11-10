# TNO0016 RepCut 配对运行的严格 NUMA 绑定

## 首次运行被 locality 门拒绝

初始配对 runner 沿用 performance Pipeline 的 `numactl --preferred=0`。before 的 10k smoke 通过，但随后 100k verify 在运行中出现 1 页 NUMA1 anonymous memory；527 个监控样本中有 286 个记录到该远端页。其完整 DiffTest、PC/指令数/周期数/UART 均通过，locality 门按既定零远端页标准拒绝该运行。

该次发生于正式 8 对前的验证阶段，尚无 RepCut 正式 pair。原目录 [repcut-comparison](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison/) 保持不变，拒绝原因和功能结果汇总在 [repcut-locality-rejection.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-locality-rejection.json)。其中 531.337 s 的 Host time 不进入正式统计。

## 运行参数修正

配对 runner 现在对两侧统一使用 `numactl --membind=0`。CPU0–31、NUMA 节点、ASLR、code-page、LD_PRELOAD、thread pinning、binary、workload、REF 和 locality 判据均不变。严格绑定避免 preferred policy 允许的远端分配；公共默认/performance Pipeline 本身的策略不修改。

runtime command 和 manifest 显式记录 bind policy；若再出现 locality 错误，会保留首次异常时的原始 maps/numa_maps，便于定位具体 VMA。仍拒绝任何受检查的 binary/library/anonymous 远端页；系统 ELF loader 的既有独立统计规则维持不变。

新增测试验证 policy 替换保留 CPU/ASLR/preload 等其余 argv，并拒绝缺失、错误节点或重复 policy。完整 `test_grhsim*.py` 测试组 **84 项通过**，见 [测试日志](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/grhsim-python-tests-bound-policy.log)。

## 重启后的边界

新输出目录为 [repcut-comparison-bound](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-bound/)，从两侧 smoke/verify/warmup 开始重新执行，然后采集全部 8 对。已完成的 native 8 对及其产物保持原样。

重启脚本：[run-repcut-pairs-bound.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/run-repcut-pairs-bound.py)，精确命令和 runner SHA：[repcut-bound-command.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-bound-command.json)。

本记录形成时，严格绑定后的 before 10k smoke、100k verify 和预热均通过；after 已通过 smoke，正在完成完整检查。后续正式统计只使用新目录中通过全部门的 pair。
