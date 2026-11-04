# TNO0411：调整版译码表整机构建与两组周期轨迹验证

日期：2026-11-03。状态：构建、smoke、两组轨迹比较通过，正式计时准备中。

本轮来源与实现见 [TNO0409](./TNO0409_decode_table_lowering_adjustments_20261103.md)，
局部复验见 [TNO0410](./TNO0410_decode_table_adjusted_local_verification_20261103.md)。
产物根目录：`build/xs/decode_table_tuned_20261103_v1`；新模型位于 `C`。

## 构建与结构

从经哈希核验的上一轮 B 的 RTL 和 DiffTest 生成结果重新执行前端、变换、活动调度及
C++ 编译。XiangShan/utility/测试封装源码身份与上一轮相同；本轮没有 Scala 改动。
采用专用单模型单线程流程，Clang 23.1.2、`-O3 -march=native`、默认 SLP，四层
DiffTest 全部开启。导入与生成 1,369.49 秒，32 并行编译 96.75 秒。

| 结构项 | 上一版 intrinsic B | 调整版 C |
|---|---:|---:|
| 化简后 kDecodeTable | 62 | 61 |
| 不同译码表 | 23 | 22 |
| 活动调度输入操作数 | 4,886,906 | 4,886,857 |
| 活动调度最终 supernode | 63,083 | 63,069 |
| ELF .text 字节 | 70,407,072 | 70,459,629 |
| ELF .rodata 字节 | 6,806,008 | 6,794,064 |

被消除的表为 `ab90a3b3674e7d79ed393586fbc00d89c452ceb74be6b891cb86dbcf5f4c9531`
（`indexedLSUopTable`、uopIdx=0、确定的恒零输出）。其他表的操作数量未变。
CSR helper 的位图表达式出现在完整模型 runtime header 中，常量表 helper 已消失。

少量逻辑删除也改变了调度聚类与代码布局；因此操作数减少不意味着二进制必然缩小。
这里完整模型 `.text` 增加 52,557 字节，不能把局部优化直接推成整机收益。
`structure.json`、`schedule_structure.json`、`binary_structure.json` 保存明细。

## 功能验证

三个版本 smoke 均通过 NEMU，完成相同的 10,000 周期窗口。新 C 分别以 seed 0、1
运行 C100000 并记录 DiffTest；每组 100,000 条有效记录分别与原硬件 A、旧 intrinsic B
比较，合计四项全部通过。比较包括有效 payload、提交顺序、数量与周期字段。

复用原 A/B 轨迹前，核验 binary、负载、NEMU、生成 schema 和运行依赖库的身份，
并确认前一轮 A/B 对应轨迹比较成功。本轮比较器重新读取原轨迹，不只相信旧结果摘要。
所有运行均为单线程 CPU96，实际文件页/匿名页本地 NUMA 检查通过；SMT sibling
CPU288 在两个验证窗口的空闲率分别为 99.92% 与 100%。

轨迹证据：`comparison/trace-{A,B}-C-s{0,1}.json`。
运行命令、原始日志、每 5 秒页面和线程状态记录在 `comparison/C/runs`。
这些带轨迹的约 100 秒运行只用于功能验证，不属于正式 walltime 样本。

## 随后测量

先分别预热 A/B/C，再按预先固定的轮换顺序各测 8 次 C100000。正式计时关闭轨迹与
诊断，所有本实验构建已结束。随后执行 24 张真实表的多分布局部新旧 intrinsic 对照。
结果单独追加记录；此处没有提前给出性能收益结论。
