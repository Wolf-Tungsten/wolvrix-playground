# TNO0287: XiangShan RepCut N=K=32 full control reproduction

日期：2026-09-07

状态：`FULL FROZEN ASSIGNMENT RECONSTRUCTION AND INDEPENDENT AUDIT PASS; NO NEW PARTITION CANDIDATE`。

实现前置：[TNO0285](./TNO0285_xiangshan_repcut_nk32_communication_refinement_tool_gate_20260907.md)。

## 1. 完整运行

使用隔离 overlay-v1，在 node029 执行 `stage4_analysis/run_frozen_control.sh`。
原始 GRH SHA 为 `82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba`，
输入大小 3427740706 bytes；导入冻结 closure-aware assignment，SHA 为
`ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589`。

仅加载一次原图，不 clone、不做 JSON roundtrip；跳过 mt-kahypar 与旧后处理，执行完整
分区重建并 emit package 和 flat-SV。运行正常退出，没有修改 assignment 或原始源文件。

| 项目 | 结果 |
| --- | ---: |
| 原图 load | 48.213 s |
| RepCut pass | 332.674 s |
| package emit | 77.389 s |
| flat-SV emit | 50.990 s |
| 总 wall（含身份校验/收尾） | 520.153 s |
| 峰值 RSS | 31424700 KiB，约 29.97 GiB |

这是转换工具耗时，不是仿真 Host wall，不能加入四项仿真速度比较。
运行产物：`build/repcut_nk32_opt_20260907/stage4_analysis/frozen-control-v1/`。

## 2. 独立验证

`verify_frozen_control.py` 读取最终 pass run.json 后才开始审计，不对运行中写入的文件
给结论。38 项检查全部通过，耗时约 23.86 s：

- 65 个 package SV、Sim header、4 个 wrapper，共 70 个源文件，对冻结 inventory
  逐字节 SHA 一致；33 个 flat-SV 也一致。只排除固有绝对目录路径的 filelist，未对源码
  做归一化或忽略差异。因此本例省略 JSON roundtrip 不改变重建输出。
- 从 piece->ASC CSR 独立重算全部 ASC full closure、全部 partition load、sparse
  occupancy、compute KM1 和原通信 proxy KM1，与 snapshot 及冻结基线一致。
- 另以 C++ refiner 的 `--validate` 路径复核相同指标；该路径不生成 assignment，使用
  unit 通信系数仅做一致性检查，不冒充已校准成本。新增此测试后 refiner 测试为 15 项通过。

| 指标 | 导入后 / 独立重算 |
| --- | ---: |
| ASC 数 | 301172 |
| piece 数 | 1327211 |
| piece-ASC incidence 数 | 49310136 |
| 非零 piece-partition occupancy 数 | 690460 |
| 最大 exact load | 1115421 |
| exact load sum | 13498964 |
| compute KM1 | 1048195 |
| 原通信 proxy KM1 | 22306433 |

验证产物 `stage4_analysis/frozen-control-verification-v1/verification.json` SHA：
`2551293821306cfe6add27ed5f93da64e2dd12126d8f9c67a946850edd87bf76`。

## 3. 结论与后续边界

已证明独立 assignment 导入/导出和重建路径可复现当前完整控制模型，后续可以在同一
原图上导入明确记录的新 assignment，不必重新随机求解。本篇没有生成新划分，没有
运行 C100/C10000，更没有测出通信或 Host 收益。

下一步仍须先完成前三项 runtime AB/BA 并选定执行框架，校准 owner update 成本，再
按前述限制生成候选、完整重编新模型并实测。当前性能资源阻断独立记录于
[TNO0286](./TNO0286_xiangshan_repcut_nk32_resource_blocker_20260907.md)。
