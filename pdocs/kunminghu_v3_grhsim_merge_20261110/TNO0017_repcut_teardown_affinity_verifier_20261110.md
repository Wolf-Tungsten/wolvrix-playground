# TNO0017 RepCut 退出阶段 affinity 检查勘误

## 误判证据

严格 NUMA 绑定后的系列在完成第 1 对后，于第 2 对 B 运行结束时被一条旧检查拒绝。拒绝项仅为 host affinity 恢复为 CPU0–31；该次所有 NUMA 检查和完整 DiffTest 均通过。

原始 160 个 `/proc` 样本显示：前面的稳定运行快照均有 32 个线程，逐线程单 CPU 绑定正确。最后一个快照在 elapsed 160.190255 s，仅剩 1 个主线程，其 affinity 恢复为原来的 CPU0–31。Host time 为 160.087 s。生成的 wrapper 在 join 完全部 worker 后调用 `restore_host_affinity_`，这是既有退出行为。

证据：[repcut-teardown-rejection.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-teardown-rejection.json)、[原始 locality 样本](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-bound/B/pair01.locality.json)、[生成的 runtime source](../../build/xs/kunminghu-v3-grhsim-merge-20261110/after/repcut/initial/package/wolvi_repcut_grhsim_sim_common.cpp)。

## 修正与验证

移除 monitor loop 中依赖 `Difftest enabled` 日志的重复单 CPU 检查，统一使用已存在的 `validate_thread_placement`：对稳定的完整线程池快照要求恰好 32 个线程、每 CPU 一个线程；退出后只剩 host 的快照不当作运行期线程池。

回归用例明确加入“worker 已全部退出，host 恢复原 32 CPU mask”的情况，同时保留拒绝运行中宽 affinity、重复 CPU、错误 CPU 集和没有完整线程池观测的检查。真实失败样本通过修正后的运行期 verifier。完整 `test_grhsim*.py` 测试组 **84 项通过**，见 [测试日志](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/grhsim-python-tests-runtime-phase.log)。

## 数据处理

`repcut-comparison-bound/` 的整段部分系列完整保留，全部排除在最终统计外。新目录 [repcut-comparison-final](../../build/xs/kunminghu-v3-grhsim-merge-20261110/repcut-comparison-final/) 重新完成两侧 smoke/verify/warmup，并重新采集全部 8 对；不补造失败运行未落盘的外部 walltime。

binary、workload、REF、CPU0–31、严格 membind=0、ASLR、code-page 和计时设置均不变。只修正退出阶段的监控范围，运行期 placement 和 locality 判据保持原标准。native 已完成的 8 对不重跑。

重启命令与 runner SHA：[repcut-final-command.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-final-command.json)。本记录形成时 before 的检查和预热已通过，after 检查进行中；最终统计另文记录。
