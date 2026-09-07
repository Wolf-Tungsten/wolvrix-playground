# NO0539 GrhSIM IR CPU wide concat gate

日期：2026-09-06

通过项目 Makefile 完成 `make py_install` 后，重新执行 `make xs_wolf_grhsim_ir`。lowering、
八阶段 CPU mapping 和 emitter 入口均成功；emitter 已越过原先的超宽类型门禁，开始处理
words-backed 生成。

新的首个失败点为：`CPU C++ emit mixed scalar/wide concat is not implemented`，操作为
`core.compute.concat`。这证明固定 word 数 `std::array<uint64_t, N>` 与已有 words runtime
helper 已被实际加载；下一步需要用 `grhsim_concat_scalars_words`/scalar 插入 helper 支持
scalar 与 wide operand 混合拼接。完整 XiangShan 仿真和 CoreMark 50k 仍未完成。
