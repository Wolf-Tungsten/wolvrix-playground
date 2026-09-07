# NO0557 GrhSIM IR CPU driver compile bottleneck gate (2026-09-06)

## 结论

Gate36 通过 Makefile 完成 XiangShan 全图 IR lowering、八阶段 CPU mapping、checkpoint/round-trip 和 76 MB C++ driver 生成。生成模型随后进入 `grhsim_SimTop.cpp` 单文件编译，但在 `-std=c++20 -O3`、`VM_BUILD_JOBS=1` 下长时间未产生 object；未观察到编译器语义错误。

Gate37 使用新的空输出目录复现同一行为。Gate38 将 `GRHSIM_MODEL_CXXFLAGS` 降为 `-std=c++20 -O0`，仍停留在该 driver 编译。两次任务均被主动中断；这些观测不足以证明编译不能完成，也不能排除优化级别的影响。

后续 gate39 的直接证据：初始化按 4096 steps 分成 170 个源文件后，driver 从 76,268,528 bytes 降至约 8.7 MiB，driver object 已生成。gate45 编译通过 driver、init_0 至 init_169、task_1 至 task_6，在 task_7 编译阶段发生 clang segmentation fault；不是绝大多数 task 已通过。

## 下一步

保留 task 文件拆分，优先把 driver 中的静态 target 表和初始化/发布/调度实现分散到多个 translation unit，同时保持生成 Makefile 和 legacy runtime ABI 不变。完成后再通过 `xs_wolf_grhsim_ir_emu` 重新验证链接和短周期仿真；当前不能宣称 emu 或 CoreMark 50k 已通过。
