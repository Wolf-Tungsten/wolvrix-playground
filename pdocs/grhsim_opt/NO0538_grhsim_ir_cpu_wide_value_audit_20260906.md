# NO0538 GrhSIM IR CPU 宽值使用审计

日期：2026-09-06

## 结果

从 `cpu_xs_schedule_20260906.json` 的实际 operations/value type 引用统计，超出 64 位的
2-state 结果共有 204,216 个，分布在 26 类操作。主要类别为：

- `core.compute.sliceStatic`：89,337
- `core.compute.and`：26,456
- `core.compute.or`：18,886
- `core.compute.sliceDynamic`：19,427
- `core.compute.mux`：10,558
- `core.compute.concat`：6,137
- `core.state.memWrite`：6,906
- `core.state.regWrite`：3,280

最大示例宽度为 16,384 位以上；宽值参与真实组合运算，而不只是 memory storage metadata。
因此 CPU emitter 必须采用 words-backed value 表示，并扩展 concat/slice/bitwise/mux/reduce 等
runtime ABI；仅将 arena 扩展为数组或把类型映射到 `uint64_t` 都会截断语义。

## 当前门禁

`cpu.st.emit-cpp` 对超宽 scalar 在实际生成点显式拒绝；数组 `memRead`、`memWrite`、
`memWriteSeq`、`memFill` 已有首版 shadow/publish 路径，但尚不能处理宽元素。该审计为后续
words-backed 实现提供操作覆盖基线；XiangShan CoreMark 50k 仍未完成。

随后 emitter 首次接入固定 word 数 `std::array<uint64_t, N>` 的值类型，并覆盖 wide
`assign`、`and/or/xor/xnor`、`not`、`mux` 到既有 words runtime helper 的生成路径；其余
算术、slice、concat、比较和宽 memory element 仍待实现。`wolvrix-lib` 编译通过。

性能约束：legacy runtime 同时提供 pointer/out-buffer 版本的 words helper；当前 `std::array`
返回值仅用于能力打通，会产生临时对象/复制，不能作为 CoreMark 50k 性能实现。最终 emitter
必须复用 local frame/boundary buffer 就地写入，再接入 schedule 的 value storage。
