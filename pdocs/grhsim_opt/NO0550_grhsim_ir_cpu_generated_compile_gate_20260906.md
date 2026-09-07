# NO0550 GrhSIM IR CPU generated compile Gate

日期：2026-09-06

通过新增 Makefile target `xs_wolf_grhsim_ir_emu` 实际进入 XiangShan difftest 编译。编译暴露生成宽值调用未统一 pointer ABI：`std::array` 被直接传给 legacy `*_words(const uint64_t *, ..., uint64_t *, ...)` helper；同时发现宽源到标量 slice 误走 `grhsim_trunc_u64`。

已修正 scalar-result 宽 slice 的 `grhsim_slice_words_u64` 路径，并将宽 compute 的输入/输出改为 `.data()` 指针。生成模型编译与 emu 尚未通过，后续继续处理 mixed scalar/wide helper ABI。
