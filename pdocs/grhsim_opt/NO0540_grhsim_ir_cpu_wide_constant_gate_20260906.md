# NO0540 GrhSIM IR CPU wide constant gate

日期：2026-09-06

words-backed fixed-array value generation 已越过 mixed scalar/wide concat 门禁。随后 XiangShan
emitter 暴露 `core.compute.constant` 参数形态差异：实际 IR 使用 `int64`/`bool` 参数，而首版
emitter 只接受字符串字面量。已兼容这两种参数并通过项目 `make py_install` 刷新 binding；
下一次 Make emitter 将继续验证宽常量数组初始化及后续运算。CoreMark 50k 仍未完成。
