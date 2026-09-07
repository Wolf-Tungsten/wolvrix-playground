# NO0541 GrhSIM IR CPU constant parameter gate

日期：2026-09-06

Make emitter gate 9 暴露 XiangShan `core.compute.constant` 使用 `constValue` 参数名，而
emitter 仅查找 `value`。已兼容 `value`/`constValue` 两种名称及 string/int64/bool 三种参数
类型，并通过项目 `make py_install` 刷新 binding。下一次 Make emitter 将验证该修复；完整
CoreMark 50k 仍未完成。
