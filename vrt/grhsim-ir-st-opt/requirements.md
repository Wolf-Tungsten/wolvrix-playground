# grhsim-ir-st-opt 任务需求

优化 grhsim-ir 路线单线程仿真 xiangshan coremark 50k 的性能。参照物 gsim 仿真同样负载只需要 40s，目标是优化 grhsim-ir 的单线程性能。

鼓励的优化方法：

1. 扩展 grhsim-ir 语义，增加更多可以高性能 emit 的 IR 操作，并配合修改 emit；
2. 改进调度算法，改善分区效果；
3. 增加更多匹配替换 pass，将 grhsim IR 中部分图结构替换为仿真行为更优的结构。

禁止的优化方法：

1. 使用多线程加速；
2. 修改本应冻结的 GRH IR；
3. 修改 XiangShan 及测试方法。

## 第 1 周补充

本周聚焦 grhsim-ir 路线单线程仿真 XiangShan CoreMark 50k 的性能优化，以 gsim 同负载 40 秒作为参照。探索必须保持单线程，不修改冻结的 GRH IR、XiangShan 或测试方法；优先从 grhsim-ir 语义与高性能 emit、调度分区，以及匹配替换 pass 三类方向寻找可验证的加速机会。
