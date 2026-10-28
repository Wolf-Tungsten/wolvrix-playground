# TNO0345：恢复版相同源码的 no-SLP 编译对照

日期：2026-10-28。控制方案见 [TNO0343](./TNO0343_grhsim_restored_memory_control_20261028.md)；Clang23错误与通用保护见 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md)。

恢复版原生成源码未改，7851个archive成员全量以相同Clang23/O3/native重新编译，统一增加`-fno-slp-vectorize`。原archive与新archive成员数量/顺序完全一致，7240个compute入口全部64B对齐。构建172.00s，原恢复版binary保持SHA `0b5364eb70513c84f9705f9a84613b3cb81bbcc44e8c766ade8997cab05f5fdc`。新binary SHA为 `6be5ee8ffc7ca742907aacaa578ee813999d2f2faccd733bcb2ac4fe1a8d1900`。

本对照测量“增加兼容选项后全量重编和重新链接”的合计影响，包含对应的机器码和布局变化，不将其解释为单个指令或单个函数成本。原始恢复版仅在已测工作负载上通过功能，并不据此认定Clang23错误对所有图都不存在。

node03096–127、32线程、C100000、preferred NUMA1、all-spin、ASLR off、代码THP。8对fresh AB/BA，全部16次正式运行及2次C100 smoke功能/THP/对齐和输入身份通过。

| 指标 | 恢复版原binary | 统一no-SLP重编 | 配对变化中位数 | 候选更快 |
|---|---:|---:|---:|---:|
| walltime(s) | 10.4200 | 11.3400 | +8.987% | 0/8 |
| Host(s) | 10.3425 | 11.2595 | +9.005% | 0/8 |
| global eval(µs) | 40.4245 | 44.3720 | +10.134% | 0/8 |
| global update(µs) | 7.3410 | 7.8730 | +7.157% | 0/8 |
| max part eval(µs) | 25.9490 | 28.1490 | +8.697% | 0/8 |
| sum part eval(µs) | 578.5915 | 643.7680 | +11.325% | 0/8 |

walltime配对增加8.987%，0/8更快；关闭SLP的通用兼容构建确实贡献了先前完整自动路线的一部分退化。不能与其它测量窗口的百分比直接相加或相减。

[构建身份](../../build/grhsim_fixed_restored_memory_20261028/restored_compatible/build.json)、[源码来源](../../build/grhsim_fixed_restored_memory_20261028/restored_compatible/source.json)、[AB/BA汇总](../../build/grhsim_fixed_restored_memory_20261028/restored_compiler_ab_ba/summary.json)。后续以该no-SLP恢复版对照新初解，消除两条线的SLP开关差异。
