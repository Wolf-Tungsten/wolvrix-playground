# NO0391 Scalar read-locality Python emitter rebuild gate

日期：2026-07-12

## 1. Preflight

承接 [NO0390](./NO0390_materialized_scalar_read_locality_diagnostic_implementation_gate_20260712.md)，SimTop fresh emit
前检查到 Python extension 仍加载 `2026-07-12 08:11` 的 site-package library，而最新 CMake library 已在 `13:39`
构建。旧 library 的 strings 中不存在 `materialized_scalar_read_locality_stats`，因此不能直接启动 Python flow。

## 2. Editable rebuild

所有命令先执行 `source env.sh`，随后运行仓库标准命令：

```text
python3 -m pip install --no-build-isolation -e wolvrix
```

editable wheel 构建、卸载旧包和安装新包全部成功。新文件为：

```text
2026-07-12 13:58:31  .venv/lib/python3.12/site-packages/wolvrix/_wolvrix.so
2026-07-12 13:58:31  .venv/lib/python3.12/site-packages/wolvrix/libwolvrix-lib.so
library SHA256: 825bf889a35802d320d014de4a99e4bb070d3b5770fcdeabc972e649a2343bf1
```

`strings` 同时命中 option、environment 和 stderr summary：

```text
materialized_scalar_read_locality_stats
WOLVRIX_GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY_STATS
[GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY] ...
```

`ldd _wolvrix.so` 指向同一 site-package 目录中的上述 `libwolvrix-lib.so`，不是 CMake build 或旧安装路径。reinstall
没有产生 tracked 源码修改。

## 3. Next gate

下一阶段从 NO0300 相同 pre-reg-to-mem checkpoint fresh 执行 direct-state SimTop emit，只额外打开 scalar locality
诊断。fresh 日志必须同时出现原有 `[GRHSIM_DIRECT_STATE_READ]` 和新的
`[GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY]`，否则不进入静态/动态连接。
