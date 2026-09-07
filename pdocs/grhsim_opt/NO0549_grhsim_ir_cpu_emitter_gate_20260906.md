# NO0549 GrhSIM IR CPU emitter Gate

日期：2026-09-06

通过项目 Makefile target `xs_wolf_grhsim_ir` 完成 XiangShan 全图 CPU C++ emitter gate 21b。8 个 CPU mapping/schedule 阶段、emitter、checkpoint 写入、fresh session 读取及 round-trip 稳定性均通过；生成目录包含 task 分区源文件、header 和 runtime。

本 gate 仅证明模型生成与 IR 持久化稳定，不代表生成 C++ 已编译、独立仿真或 CoreMark 50k 已通过。下一步进入生成模型编译和 XiangShan runtime 集成。
