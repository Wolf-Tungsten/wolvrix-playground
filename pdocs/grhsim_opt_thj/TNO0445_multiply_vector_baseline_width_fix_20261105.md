# TNO0445：乘法定向负载暴露的布尔操作数位宽问题（2026-11-05）

## 基线失败与复现

在旧完整 S3 硬件基线 `build/xs/behavior_grouped_rat_20261105_v1/A` 上运行乘法定向程序，
8,372 周期触发 VTypeBuffer one-hot 一致性断言。改为固定 SEW32 的探针同样在 8,348 周期
失败。因此不能把失败归因于行为乘法或连续切换 SEW。

失败报告的指针为 1、one-hot 为 2，本应一致。原 SV 是：

```systemverilog
wire bad = (64'h1 << index) != onehot;
```

Wolvrix 导入声明初始化表达式时，把 1-bit 目标上下文传给比较操作数，导致移位结果先截成
1 位再与 64-bit onehot 比较。直接连续赋值形式没有这一截断，最小 fixture 同时保留了两种形式。
旧模型 C++ 中能直接看到移位后 `& 1` 再零扩展的错误。

## 修复与验证

`ingest.cpp` 在比较和逻辑二元操作内部停止传递结果位宽上下文，使用 slang 已解析的操作数类型。
覆盖相等、不等、case/wildcard 比较、四种大小比较、逻辑 AND/OR 共 12 种操作。

- `ingest-stmt-lowerer` 针对性测试通过。
- 生产 frontend、reg-to-mem、activity schedule、C++ emitter 生成的最小模型，对 64 种索引、
  66 种 one-hot/零/全一组合，共 4,224 组输入检查全部谓词和重复 eval，通过。
- 原失败日志、修复前后 GRH 和运行检查位于
  `wolvrix/build/artifacts/multiply-behavior/onehot-width/` 与 `workload/`。

这是一项阻挡完整向量验证的编译器正确性修复，不是关闭断言或改变指令语义。

## 冻结产物与重新验证

`multiply_behavior_20261105_v1` 的 A/B RTL 均完成，但 native emit 在定位错误后主动停止。
这两组 RTL 保留，不重复 elaboration。后续构建通过 `--rtl-from` 校验 XiangShan 生成源码、
配置和所有 RTL/生成头文件哈希，复用不可变 RTL；A/B 共同使用新冻结编译器。

新局部目录 `local-v4` 包含修正后的工具和八个模型。数学参考检查、四个真实 FU wrapper
（`wrappers-v2`）、有效数乘积边界（`product-boundary-v2`）均通过，各检查三个固定种子、
每种子 10,000 周期。默认硬件与原 YunSuan RTL 去掉注释/空白后仍一致。

先前局部测试的 `cycle % 3` 气泡模式与 FP 格式选择相关，部分格式/舍入组合只覆盖了短暂连续
输入区间。`validation-v4` 补充检查已通过；正式生成器改用与格式和加宽周期独立的 17 周期气泡，
并拒绝覆盖计数为零的操作组合。新 `local-v4` 的全部操作/格式计数非零，避免只依赖总随机周期数。

历史局部性能仍见 [TNO0444](./TNO0444_multiply_behavior_local_performance_20261105.md)。
修复后的性能使用新目录重新测量，不能混用编译器或样本。

## 修复后局部复测结果

`local-v4/performance-v3` 全部通过原准入条件。v1/v2 分别检测到 CPU115/CPU98 的短暂活动，
保留原始样本；后续目录通过 binary/vector 哈希复用已完成且环境合格的场景，只补未完成场景。

| 模型 | 场景 | 配对均值 B/A−1 | 95% bootstrap CI |
|---|---|---:|---|
| int-mul | active | -86.657839% | [-86.775554%, -86.539052%] |
| int-mul | sparse | -88.065576% | [-88.368619%, -87.679826%] |
| int-mul | idle | -90.027018% | [-90.113863%, -89.945821%] |
| vec-int-mul | active | -80.518740% | [-80.658582%, -80.351586%] |
| vec-int-mul | sparse | -78.987129% | [-79.041831%, -78.938796%] |
| vec-int-mul | idle | -78.937584% | [-79.077135%, -78.749781%] |
| fp-mul | active | -63.835971% | [-63.913935%, -63.759475%] |
| fp-mul | sparse | -77.388632% | [-77.463809%, -77.314848%] |
| fp-mul | idle | -83.307447% | [-83.394438%, -83.208946%] |
| vec-fp-mul | active | -45.440821% | [-45.507501%, -45.371935%] |
| vec-fp-mul | sparse | -62.299664% | [-62.370519%, -62.226763%] |
| vec-fp-mul | idle | -69.778665% | [-69.853166%, -69.699002%] |

完整 S3 转入 `build/xs/multiply_behavior_20261105_v2`，原 v1 RTL 不变；B 实际启用
2 个标量整数、4 个标量浮点、2 个向量整数、4 个向量浮点模块实例。未启用 commit-rat 或 intrinsic。

定向程序在同一 NEMU 库中独立预执行 10,000 条指令，89 个乘法/FMA 指令位置全部访问。
这只确认负载和参考库可执行，不代替完整 DUT 的提交轨迹验证。
