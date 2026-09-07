# NO0545 GrhSIM IR CPU wide slice gate

日期：2026-09-06

Make gate 15 已越过常量和 memory commit verifier，首个失败点为 256 位
`core.compute.sliceStatic`。emitter 已接入 `grhsim_slice_words<DestN,SrcN>`，支持宽源的
固定起点 slice；修改已通过项目 `make py_install` 编译刷新。动态 slice、混合宽度和其余
算术/比较操作仍待覆盖，CoreMark 50k 尚未完成。
