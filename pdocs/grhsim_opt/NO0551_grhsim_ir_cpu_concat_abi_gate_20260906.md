# NO0551 GrhSIM IR CPU concat ABI Gate

日期：2026-09-06

Gate 24 的实际 XiangShan 编译已越过宽 slice 与宽 pointer ABI 错误，暴露 concat 分支判定问题：两个 scalar operand 被错误生成到 `concat_wide_scalar`。已修正生成器，使 scalar+scalar 使用 `grhsim_concat_u64`，只有 lhs/rhs 中至少一个宽值时才选择对应 words helper。

已通过 `make py_install` 刷新 binding；生成模型编译仍需重新执行确认。
