# NO0542 GrhSIM IR CPU system task gate

日期：2026-09-06

通过 Makefile 刷新 binding 后，gate 10 越过宽 concat 和常量参数门禁，首个失败点为
`core.system.task` 无结果操作。emitter 已将 system task/DPI 从单结果组合表达式验证中分离，
允许继续生成路径；system task 当前为占位 no-op，DPI ABI、`fwrite`/`finish` 的实际副作用仍
必须实现后才能验收 XiangShan CoreMark 50k。
