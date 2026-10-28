# TNO0348：固定 memory 对齐初解的构建与执行计划检查

日期：2026-10-28。方法见 [TNO0347](./TNO0347_grhsim_fixed_memory_initial_method_alignment_20261028.md)。

## 新初解与精确账本

历史六维 HGR 输入与自动隔离后的 HGR 均已对齐，重新求解得到完整 301,184 个标签。assignment replay 后逐行相同，未复制历史局部迁移。所有生成、分析与编译允许 CPU0–383。

| 静态指标 | 上一轮普通初解 | 对齐方法的新初解 |
|---|---:|---:|
| closure work 总量 | 13,276,069 | 14,213,318 |
| recurring work 总量 | 12,969,981 | 13,859,727 |
| piece copies | 653,365 | 708,340 |
| send calls | 3,987 | 7,760 |
| send bytes | 501,927 | 468,023 |
| 最大 receive bytes | 247,816 | 69,782 |

通信字节与接收峰值下降，但复制工作和调用数增加，静态指标不作为 walltime 结论。

## 构建

完整 26 项历史 preset，冻结 library 与上一轮相同。全包 7,857 个 C++ translation unit，Clang23/O3/native/no-SLP 编译、对象64B对齐、按生成Makefile次序归档并链接，通过7249个compute入口全部64B对齐检查。构建109.20s；binary SHA256为 aeceb0e91a36c7c47e9943c8d8503824b17aaa4f386595f1938b5fa760f7af8d。

首次驱动误重复启动已经运行的plan检查，因输出目录存在而被拒；原检查进程未中断，编译完成后已修改驱动等待现有检查并复用通过的构建。此错误未产生仿真数据。

[精确账本](../../build/grhsim_fixed_memory_aligned_initial_20261028/assignment_audit/summary.json)、[构建记录](../../build/grhsim_fixed_memory_aligned_initial_20261028/initial/build.json)、[emit记录](../../build/grhsim_fixed_memory_aligned_initial_20261028/initial/emit.json)、[分区记录](../../build/grhsim_fixed_memory_aligned_initial_20261028/initial/partition.json)。

执行计划检查与C++生成并行，显式使用上一轮相同完整preset及新partitioned输入；记录引用上一轮成功emit.json仅用于固定library/options，不以旧图代替新图。性能结果另行记录。
