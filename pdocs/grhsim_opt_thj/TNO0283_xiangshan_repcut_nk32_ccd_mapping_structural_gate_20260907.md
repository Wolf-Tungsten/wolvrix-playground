# TNO0283: XiangShan RepCut N=K=32 CCD mapping structural gate

日期：2026-09-07

状态：`STATIC CANDIDATE FROZEN; RUNTIME PENDING AFTER STAGE 1`。

前置计划：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)。

## 1. 通信图来源

冻结 package 的 build-manifest 未序列化 emitter 内存中的 connection manifest，
因此由生成的 update wrapper 恢复实际端点拷贝，而不是假定磁盘存在该 manifest。
严格语法识别逐条 scalar/wide copy，并核对已校验 SHA 的 SV 端口宽度及 Verilator
public port 的实际 C++ 存储类型；未知语句、漏函数、重复目标或位宽不一致拒绝。

共 5137 个端点拷贝，449729 storage bytes/update，114489 ceil(width/32) words/update。
32 分区间有向通信边 691/992，密度 69.66%。这里统计实际生成的 unit-to-unit 拷贝，
不包含顶层输出，不等同旧 partition 静态 cross-value 总 words，也不等同一致性协议流量。

## 2. 固定候选

每个 CCD 恰好八个 partition。目标为跨 CCD 实际存储 bytes 总和，固定 seed
20260907、连续初始解加 128 个确定性随机起点，逐对交换至局部稳定。22 个起点达到
同一个最小值，不声称全局最优；性能结果不参与映射搜索。

| 指标 / update | 连续编号 | 固定候选 |
| --- | ---: | ---: |
| 跨 CCD storage bytes | 286194 | 192598 |
| 跨 CCD words32 | 72904 | 49529 |
| 最大单 CCD 进出 bytes 合计 | 215793 | 143829 |

跨 CCD payload 减少 93596 bytes，即 32.704%；逻辑总拷贝量不变。

worker-to-part 排列：

```text
0,1,2,3,7,13,29,30,4,5,12,24,25,26,27,28,6,16,17,18,19,21,23,31,8,9,10,11,14,15,20,22
```

每八项对应一个物理 CCD；根据实际选中 CPU 列表生成 part-to-CPU，不绑定 node030。
lane 0 在本候选仍是 part 0，但 runtime/verifier 不以此作通用假设。

## 3. 证据与后续

实现及 7 个通过的聚焦测试位于 `build/repcut_nk32_opt_20260907/mapping/`。
产物目录 `mapping/closure-aware-width-20260907/` 保留逐端点表、32x32 矩阵、每 CCD
流量、正逆映射、129 次搜索记录及输入身份。`optimized.json` SHA-256：
`116d371de97a7b67321aef478974fa789e36e2598849f8ddd5eea35e754c4aeb`。

下一步在阶段一选定 runtime 下，用同一 ELF 仅改变上述排列做 AB/BA。
静态减少尚不代表 Host 收益；eval cache locality 与关键分区落核也会随排列改变。
