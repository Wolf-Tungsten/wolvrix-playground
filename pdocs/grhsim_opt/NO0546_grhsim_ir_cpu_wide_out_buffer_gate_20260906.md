# NO0546 GrhSIM IR CPU wide out-buffer gate

日期：2026-09-06

参照 legacy runtime 的 pointer/out-buffer API，emitter 对宽 `and/or/xor/not` 增加了直接写入
结果 value slot 的生成路径，避免 `std::array` 临时返回和复制；`make py_install` 成功。
Make gate 16 通过宽固定 slice 后，新的首个失败点为 `core.compute.sliceArray width=256`。
后续继续以 out-buffer 方式实现 array slice 和动态 slice；CoreMark 50k 仍未完成。
