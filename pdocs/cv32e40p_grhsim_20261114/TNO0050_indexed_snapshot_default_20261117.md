# TNO0050：紧凑快照数组默认开启

将 `indexed_concat_snapshot_array` / `WOLVRIX_GRHSIM_INDEXED_CONCAT_SNAPSHOT_ARRAY` 的缺省值从 false 改为 true。采用依据是 TNO0049 的固定三对：CV32 walltime −6.25%，95% CI [−6.69%, −5.48%]；XiangShan −0.042%，CI [−0.084%, +0.003%]，未见明确退化。这些仍是既有三对探索结果，本轮没有新增性能样本。

生产 emitter 相对 TNO0049 冻结源码只有缺省布尔值这一处差异。快照的等宽、局部性、寿命及静态存储成本证明继续生效。`indexed_concat_slice` 仍是父级条件：关闭父级后不采用快照数组。其他实验选项的默认值没有改变。

需要恢复原word-reader表示时，设置 emit attribute `indexed_concat_snapshot_array=0`，或环境变量 `WOLVRIX_GRHSIM_INDEXED_CONCAT_SNAPSHOT_ARRAY=0`。attribute优先于环境变量，两个方向均有回归。[功能说明](../../wolvrix/docs/emit/grhsim-indexed-snapshot-arrays.md)

## 默认与关闭行为

已有专项回归改为检查默认/显式开启/环境开启生成的完整CPP和header逐字相同；显式关闭/环境关闭同样逐字相同。另检查attribute开覆盖环境关、attribute关覆盖环境开，以及父级关闭。原indexed-concat回归显式关闭快照数组，继续覆盖原reader实现；O0/O3 ASan/UBSan独立逐bit oracle沿用，无新的语义规则。

默认生成对照移除新选项的环境设置，并保持TNO0049两边其余配置。CV32默认生成的21个文件（CPP/header/Makefile）逐字匹配已测开启版；显式关闭同样21个文件匹配已测控制组。normalized IR一致。[CV32默认身份](../../build/xs/indexed-snapshot-default-20261117-v1/cv32.json)

XiangShan默认生成的140个文件（137个CPP、2个header、Makefile）逐字匹配TNO0049已测开启版。[XiangShan默认身份](../../build/xs/indexed-snapshot-default-20261117-v1/xs.json)、[两设计对照结果](../../build/xs/indexed-snapshot-default-20261117-v1/report.json)

三项CTest全部通过：`emit-grhsim-cpp-indexed-snapshot-array`、`emit-grhsim-cpp-indexed-concat-slice`、`emit-grhsim-execution-plan`。专项回归包含默认/开关优先级检查及O0/O3 ASan/UBSan生成模型执行。测试源码、生产源码与构建快照一致。[CTest日志](../../build/xs/indexed-snapshot-default-20261117-v1/validation/ctest.log)、[归档检查](../../build/xs/indexed-snapshot-default-20261117-v1/validation.json)

## 可复现记录

默认验证驱动仅生成代码和比较文件，没有运行模拟器或采集计时。它冻结新的native库、headers、emitter与测试源码，独立断言生产改动仅为缺省值切换。[驱动](../../scripts/indexed_snapshot_default_verify.py)、[规则](../../build/xs/indexed-snapshot-default-20261117-v1/policy.json)

此前TNO0049的结果与冻结模型保留为当时显式开启实验的证据。本轮的默认变更单独记录，不修改历史候选或重新挑选样本。此次随实现、回归、对照工具和TNO0046–0050记录一起提交。
