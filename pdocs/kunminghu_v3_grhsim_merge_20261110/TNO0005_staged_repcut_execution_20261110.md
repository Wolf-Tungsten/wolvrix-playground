# TNO0005 RepCut 分阶段执行记录

## 执行边界

before 的标准 `grhsim32.py --performance` 流程完成 8 次初始运行和两次 trace 后，选择了一个自动迁移候选，正在 replay/emit 候选。该流程后续仍需内部 AB/BA 决定 retained 版本。

after 已有冻结 RTL 和独立源码，因此先进行只读使用现有 native tools 的 frontend 与 memory conversion。后续工具/solver 构建、partition、emit、compile、运行及 migration 均等 before 释放 `build/.grhsim32.lock` 后串行执行。after 不会与 before 同时运行 emulator。

执行脚本位于 [after-repcut-staged.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/after-repcut-staged.py)。它直接调用同一个 `scripts/grhsim32.py` 的 `Pipeline`，按 `inputs → dependencies → solve → emit → measure → search → publish` 执行；仅将已冻结前端的准备提前。工具 source 未修改、共享工具构建不并发。脚本和 Pipeline SHA、源码 commit 记录于 `after/repcut/staged-driver.json`。

## 配置一致性

- `performance=true`、32 partitions、8 个 solver seeds、相同 solver revision/options、384 build jobs。
- runtime CPUs 均为 0–31，NUMA0，ASLR disabled、codepages=auto、pinning enabled。
- CoreMark/NEMU 使用 artifacts/inputs 下的冻结副本。
- after 采用 [TNO0004](./TNO0004_upstream_rtl_schema_memory_20261110.md) 的独立 memory 配置。
- native tools 与 emit/compile 参数沿用共同 Pipeline；DefaultConfig 对应硬件变化单独记录。
- 前端准备固定 CPU128–159，后续阶段恢复标准生成 affinity；正式前后配对等全部构建结束后执行。

为支持隔离源码，native/RepCut runner 增加可选 `--xs-source`；默认仍指向 `testcase/xiangshan`。RepCut 配置写出提取为共用 `write_configuration()`，默认和 performance 的行为不变。相关 20 项 RepCut/paired gate 测试通过，日志为 `logs/repcut-isolated-source-tests.log`。

## 当前状态

after 前端已启动；before migration 尚未完成。本记录不包含正式前后 walltime 结论。最终 partition、selection、migration 与 paired CSV/JSON 将在后续独立文档中归档。
