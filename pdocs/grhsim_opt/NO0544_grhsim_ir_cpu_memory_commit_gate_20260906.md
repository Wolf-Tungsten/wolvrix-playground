# NO0544 GrhSIM IR CPU memory commit gate

日期：2026-09-06

Make gate 14 暴露 emitter verifier 白名单遗漏：`core.state.memWrite` 是无结果 commit op，
但仍被当作组合 op 检查 result arity。已将 `memWrite`、`memWriteSeq`、`memFill`、`memAssign`
全部加入 commit skip；通过项目 `make py_install` 编译刷新。下一步继续 Make emitter 验证。
