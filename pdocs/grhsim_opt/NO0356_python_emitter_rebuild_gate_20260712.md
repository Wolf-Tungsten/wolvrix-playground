# NO0356 Python emitter rebuild gate

日期：2026-07-12

## 1. Preflight mismatch

在按 [NO0355](./NO0355_single_writer_state_read_direct_forward_implementation_gate_20260712.md) 启动 SimTop fresh
emit 前，检查到 Python flow 实际加载：

```text
.venv/lib/python3.12/site-packages/wolvrix/_wolvrix.so
.venv/lib/python3.12/site-packages/wolvrix/libwolvrix-lib.so
```

两者时间戳仍为 `07:18`，早于 `wolvrix/build/libwolvrix-lib.so` 的 `08:04`。`ldd` 证明 `_wolvrix.so` 的
`$ORIGIN` RUNPATH 指向 site-package 内的 `libwolvrix-lib.so`，不会自动使用刚由 CMake 重建的
`wolvrix/build/libwolvrix-lib.so`。因此只通过 C++ CTest 不能证明 Python SimTop flow 已加载新 emitter。

该问题在 fresh emit 启动前发现，没有产生旧代码生成结果或需要废弃的 SimTop output。

## 2. Correction

所有命令均先执行 `source env.sh`。按仓库标准命令重建 editable package：

```text
python3 -m pip install --no-build-isolation -e wolvrix
```

构建和安装成功，新文件时间戳为：

```text
2026-07-12 08:11:02 .venv/lib/python3.12/site-packages/wolvrix/_wolvrix.so
2026-07-12 08:11:02 .venv/lib/python3.12/site-packages/wolvrix/libwolvrix-lib.so
```

新 site-package library 的 strings 同时包含：

```text
direct_single_writer_state_reads
[GRHSIM_DIRECT_STATE_READ] enabled=1 reads=...
```

`ldd` 再次确认 Python extension 加载的正是上述新 library。editable wheel 构建及 reinstall 均成功，源码仓库没有
因此产生 tracked 修改。

## 3. Next gate

后续 SimTop fresh emit 使用新编号和新 output/log；必须在日志中出现 `[GRHSIM_DIRECT_STATE_READ]` 且 reads 非零，
否则视为开关或 Python runtime 仍未生效。该结构门禁与实际覆盖统计单独记录，不写回本篇。
