# NO0555 GrhSIM IR CPU concat scalar overload Gate

Gate 28 的全量编译继续暴露少量 concat 表达式的 scalar/wide 静态类型不一致。已为 `grhsim_concat_wide_scalar` 增加 scalar lhs 重载，直接写入结果 words，兼容生成器边界表达式并保持 legacy words 结果表示。集成编译待重新验证。
