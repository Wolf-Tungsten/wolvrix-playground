# TNO0047：掩码规则默认开启与最终回归

日期：2026-11-11（America/Los_Angeles）。按用户“验证其他是否退化，如果没问题就默认启动”的指示，在完成收益边界和跨分区验证后默认开启新规则。

## 默认策略

`grhsim-cpp` 的 `scalar_concat_reduction_masks` 默认值改为 true；[标准 32 线程配置](../../config/grhsim32.json) 也显式记录 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS=1`。后续生成使用新默认。

仍依赖父选项 `scalar_concat_reduction=1`。父选项本身的默认值未变；已有单核 native 生成环境没有开启该父选项，本次默认开关不绕过它。GSIM 后端没有代码变更。生产/性能模式分离、默认线程放置策略和 code-page 默认策略保持原有契约。

32 线程 pipeline 的关闭方式是在所用配置的 `options` 中设置：

```json
"WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS": "0"
```

直接使用 emitter 时，可设置 attribute `scalar_concat_reduction_masks=0` 或同名环境变量为 `0`。显式 attribute 优先于环境变量。完整当前契约见 [后端说明](../../wolvrix/docs/emit/grhsim-bool-reduction-masks.md)。

## 开启依据与收益门

- [TNO0044](./TNO0044_reduction_mask_default_profitability_guard_20261111.md)：边界诊断发现重复谓词的 pack 成本退化，已改为至少 **16 个不同的 `(mask, reduction-family)` 谓词** 才接受。重复谓词回退；其余 14 类有效局部样本没有观察到退化。
- [TNO0045](./TNO0045_before_seed2_mask_nonregression_20261111.md)：before seed2 的 7,857 个源文件与最终 binary 全部逐字节相同，无新运行代码。
- [TNO0046](./TNO0046_after_seed1_mask_nonregression_20261111.md)：另一份 after seed1 在相同 Clang 修正对象控制下，8 对 Host time **−32.50%**，CI 完全低于零，22 次完整运行通过。
- 先前 after seed7 命中的 119 个节点至少有 35 个不同 mask，全部超过新增门槛；先前 [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md) 的优化命中范围保留。核验见 [seed7-guard-coverage.json](../../build/artifacts/reduction-mask-default-20261111/seed7-guard-coverage.json)。

增加了廉价的候选数量预筛选，使没有足够 concat 的节点在构造详细计划前返回。它不改变可接受集合。

本次判断依据是所测图与边界样本，而非宣称所有电路或编译器都不可能退化。主测量使用 Clang 23、CoreMark；保留显式关闭选项供后续其他设计做对照。

## 最终测试

默认开关控制矩阵共 8 种模式通过：

- 默认与显式开启的生成源码相同。
- attribute 关闭、environment 关闭、attribute 对 environment 的正反方向覆盖正确。
- 父规则关闭时，子规则开启/关闭生成相同源码。
- 15 个不同谓词回退，16 个不同谓词接受；24 个 concat 只有两个不同谓词的情况回退。
- 位宽、重复字段、内部写入、numeric use、混合归约族、未知副作用等原有边界继续通过。

源码不同的 on、off、parent-off 三种路径分别用 Clang 23 `-O0/-O3` 加 ASan/UBSan 验证，每种 12,000 组固定种子数据、每组重复 eval 两次；字节相同的变体不重复编译。显式开启规则的完整 emitter 回归通过。23 项相关 Python 测试、native tools/focused build、canonical production/performance Make target 的 `make -n`、Python 编译和 diff 检查通过。

## 产物

- [最终 JSON 报告](../../build/artifacts/reduction-mask-default-20261111/report.json)、[检查索引](../../build/artifacts/reduction-mask-default-20261111/checks.json)
- [默认控制矩阵日志](../../build/artifacts/reduction-mask-default-20261111/default-tests.log)、[完整 emitter 回归](../../build/artifacts/reduction-mask-default-20261111/emitter-enabled-regression.log)、[Python 测试](../../build/artifacts/reduction-mask-default-20261111/python-tests.log)
- [最终源码快照与身份](../../build/artifacts/reduction-mask-default-20261111/source-provenance.json)、[Wolvrix 补丁](../../build/artifacts/reduction-mask-default-20261111/wolvrix.patch)

冻结基线、此前 TNO0041–TNO0043 的历史默认关闭记录和全部原始测量均保留。本记录表示默认策略的后续变更。
