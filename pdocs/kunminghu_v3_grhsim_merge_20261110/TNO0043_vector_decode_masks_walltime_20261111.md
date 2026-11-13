# TNO0043：向量译码共享掩码的正式 walltime 对测

日期：2026-11-11（America/Los_Angeles）。实现见 [TNO0041](./TNO0041_vector_decode_reduction_masks_20261111.md)，生成内容、编译后等价检查和完整功能门见 [TNO0042](./TNO0042_vector_decode_generated_functional_gate_20261111.md)。

## 对照与结果

固定 after 原 seed7 的分区图、Clang 23、CoreMark、100,000 周期上限、完整 DiffTest/NEMU。A 使用原 binary，B 只增加 `scalar_concat_reduction_masks` 规则；两侧使用相同编译参数、performance runtime、CPU96–127、NUMA1 bind、ASLR off、code-page/preload/pinning。未重新选择分区，不使用补丁 seed1。

双方分别完成 smoke、100k 验证、预热，随后串行 8 对 AB/BA。22 次运行全部通过功能和 placement/locality 门，没有拒绝样本。正式统计只使用 8 对配对样本。

| 指标 | A 均值 | B 均值 | 每对相对变化均值 | 配对 bootstrap 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 16.274875 s | 13.654750 s | **−16.0962%** | **[−16.8202%, −15.3548%]** | 8/8 |
| 外部 walltime | 16.382753 s | 13.760606 s | **−16.0028%** | **[−16.7149%, −15.2680%]** | 8/8 |

Host 中位数 16.189 → 13.639 s；每对 delta 中位数 −16.4154%。bootstrap 使用固定 seed `20261102`、10,000 次有放回的配对重采样。负号表示 B 耗时更短，统计口径沿用现有 runner；没有按计时高低剔除样本。

这次完整图的收益超过噪声范围。原型 2 对诊断曾得到约 −19%，正式结果采用本次同窗口 8 对数据，不能用不同时间窗口的绝对值拼接对照。

## 收益来源与剩余热点

双方保留既有 performance phase timing，未加入额外 runtime profile 或 trace。下表为 8 次正式样本的分项累计时间中位数，不是可直接相加的并行 CPU 成本占比。

| 项目 | A | B | 说明 |
|---|---:|---:|---|
| `part_eval` phase | 14.1228 s | 11.5229 s | 主要整体收益来自分区计算 |
| `input_load` phase | 0.4258 s | 0.4544 s | 未优化此路径 |
| `global_update` phase | 1.3812 s | 1.3796 s | 基本相同 |
| `part_8` eval | 10.8043 s | 4.3739 s | **−59.52%**，原主要译码热点下降 |
| `part_18` eval | 10.0557 s | 8.7362 s | −13.12%，目前最慢分区 |
| `part_19` eval | 7.3595 s | 7.3479 s | 基本相同，当前次慢分区 |

`part_8/batch_53` 的机器码函数体由 174,099 B 降至 29,778 B（−82.90%）；其余几个主要译码 batch 函数体也明显减少。binary 总体减少 2,129,920 B（−1.7843%）。不是仅缩短源码：核心函数机器码和实际 eval 时间都下降。相关数据见 [function-sizes.json](../../build/artifacts/repcut-vector-decode-20261111/function-sizes.json)。

原来多次展开的标量 AND/OR 现在复用同一个 64 位输入词，再做掩码比较，降低了这些函数的运算和临时值压力。每个输出写入、活动传播、断言及 DiffTest 均保留。源文件恢复审计确认没有其他代码改动。

## 保留方式与适用范围

新规则默认关闭，通过 performance 配置的 `options` 显式添加：

```json
"WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS": "1"
```

同时保留原 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION=1`。本次完整选项保存在 [performance-config.json](../../build/artifacts/repcut-vector-decode-20261111/performance-config.json)。优化后的独立候选 binary 位于：

```text
build/xs/repcut-vector-decode-20261111/generated/initial/harness/grhsim-compile/emu
```

没有修改默认 production/performance 配置。收益结论限定于 after seed7 的 32 线程 RepCut GrhSIM、Clang 23 和此 CoreMark 运行；不外推为 GSIM、单核 GrhSIM或任意 RVV workload 的收益。任意 Boolean 输入的 kernel 检查补足了译码谓词验证，但不等同于完整 RVV 架构工作负载。

当前最慢分区已转到 `part_18`，不能继续按 `part_8` 的局部下降幅度外推整体收益。后续若继续迭代，应先定位 `part_18` 的剩余热点。

## 归档

- [综合 JSON 报告](../../build/artifacts/repcut-vector-decode-20261111/report.json)
- [8 对 summary](../../build/xs/repcut-vector-decode-20261111/measure-generated/summary.json)、[CSV](../../build/xs/repcut-vector-decode-20261111/measure-generated/pairs.csv)、[逐对完整 JSON](../../build/xs/repcut-vector-decode-20261111/measure-generated/pairs.json)
- [配对 runner](../../build/artifacts/repcut-vector-decode-20261111/measure.py)、[核验与统计脚本](../../build/artifacts/repcut-vector-decode-20261111/report.py)
- [通过门的候选 metadata](../../build/xs/repcut-vector-decode-20261111/generated/result.json)

新增 focused test、旧 concat reduction 回归、完整 emitter 回归、native tools 构建通过；Python 编译、文档相对链接和工作树 diff 检查通过。既有 TNO0035–TNO0040 及其他工作内容保留。

## 增量更新 2026-11-11：默认策略变更

在新增重复谓词收益门并完成其他图验证后，规则已默认开启，见 [TNO0047](./TNO0047_reduction_masks_default_enabled_20261111.md)。本篇记录的实验配置和“当时默认关闭”的状态保留；新收益门保留本实验全部 119 个匹配节点。
