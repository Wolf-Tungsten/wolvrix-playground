# TNO0013 Backend 兼容修复的基线一致性与 after 功能门

## before 生成代码逐字节一致

使用 [TNO0012](./TNO0012_repcut_undriven_wrapper_compatibility_20261110.md) 的 Wolvrix `3a749d2`，从冻结的 before candidate partitioned graph 和 assignment 重新发射 package，并使用原 performance 配置中的 generation options。

结果：全部 **15,754 个 `.cpp/.h/.hpp` 文件逐字节一致，差异为 0**。审计同时核对文件集合和每个文件 SHA256。因此 wrapper 对无驱动信号的兼容补丁没有改变旧版本的生成 C++，原 before binary 可以继续作为相同生成行为的控制组。

完整文件清单、两套 SHA 和结果：[comparison.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/before-package-compatibility/comparison.json)。输入 graph/assignment 的 SHA、精确命令和环境：[command.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/before-package-compatibility/command.json)。重新生成的 source 保留在同目录 `package/`。

本次 backend source 的必要版本变化为 `aece4ae → 3a749d2`。native C++ emitter 未修改；两个 native binary 与此前 trace 门完全相同。前后 RepCut 的有效代码生成行为由本项 byte-identity 检查及新路径 fixture 验证共同约束。

## after RepCut 初始版本完整功能门

修复后 package 发射、编译通过，初始版本连续 8 次 100,000 周期运行全部通过完整 DiffTest。每次功能签名均与 after native 相同：

- PC `0x80000c1a`；instrCnt `250838`；cycleCnt `99995`；Guest cycles `100001`。
- 正常 cycle-limit 终止；UART `Running CoreMark for 2 iterations\n`。
- 固定 CoreMark/NEMU，默认 DUT ROM，完整 collection/checking 开启。

日志身份、功能签名和 binary SHA：[after-repcut-initial-functional.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/after-repcut-initial-functional.json)。本阶段时间用于标准 pipeline 的候选选择，未混入正式 revision pair。

after pipeline 当前继续执行 trace/context/migration。配对调度已同时要求 before 生成代码一致性通过和两侧 performance 构建完成。最终 retained 分区及 8 对前后 walltime 另文记录。
