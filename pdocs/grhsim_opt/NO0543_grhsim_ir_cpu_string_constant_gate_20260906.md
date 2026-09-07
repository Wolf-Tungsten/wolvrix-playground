# NO0543 GrhSIM IR CPU string constant gate

日期：2026-09-06

Make gate 12 越过宽常量参数后，暴露 `core.compute.constant` 的 `core.string` 结果。emitter
已加入 `std::string` 类型和字符串常量生成；随后 gate 13 暴露宽 array element storage
步长仍按 64 位限制，已改为按 word 数计算（`ceil(width/64)*8`）。修改待下一次 Makefile
`py_install`/emitter 验证。system task/DPI 副作用与 CoreMark 50k 仍未完成。
