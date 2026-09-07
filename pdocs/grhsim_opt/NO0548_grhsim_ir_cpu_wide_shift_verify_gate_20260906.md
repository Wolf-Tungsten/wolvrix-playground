# NO0548 GrhSIM IR CPU wide shift verify gate

日期：2026-09-06

gate 18 发现宽 `shl` 已有 out-buffer 生成，但 verifier 仍走 expression fallback 并报不支持。
已补齐宽 `shl/lshr/ashr` 的 words expression helper，且通过项目 `make py_install`。下一步
继续 Make emitter 验证；性能路径仍优先使用 out-buffer。
