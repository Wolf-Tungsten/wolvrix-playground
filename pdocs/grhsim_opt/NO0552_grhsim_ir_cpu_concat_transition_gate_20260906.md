# NO0552 GrhSIM IR CPU concat transition Gate

Gate 25 的实际编译继续越过 scalar concat 类型错误，定位到连续 scalar concat 首次超过 64 位时缺少 scalar-to-wide materialization。已新增 `grhsim_concat_scalar_scalar_wide`，保持后续操作使用 words 表示，并通过 `make py_install` 刷新 binding。集成编译仍待重新验证。
