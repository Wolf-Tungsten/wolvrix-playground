---
id: NO00023
date: 2026-07-14
title: Full XiangShan executable GRH export and activity-schedule import
kind: validation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, activity-schedule, xiangshan, coremark]
parents: [NO00022]
related: [NO00002, NO00015]
supersedes: []
---

# NO00023 Full XiangShan executable GRH export and activity-schedule import (2026-07-14)

> 归档编号：`NO00023`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run14 导出成功

```text
ptmp/gsim_full_exec_20260714/run14/strict-export.log
wall=10:08.42
maxRSS=99,913,696 KiB
exit=0
```

原子输出：

```text
ptmp/gsim_full_exec_20260714/run14/gsim/SimTop.exec.json
size=3,369,244,412 bytes
sha256=24493706a4a416d8d2190876d8c4ca5b0a14858b427506c790742398f34eb900
```

envelope 和尾部闭合检查确认：

```text
format=gsim.executable-grh.v2
stage=pre-coarsen
boundary=PreCoarsen
analysisOnly=false
executionProfile=xiangshan-gsim-coremark-stub
graph/top=SimTop
nodeCount=2,710,434
valueCount=7,597,096
operationCount=7,908,902
externalInstanceCount=111
externalCallCount=114
dpiImportCount=32
```

## Fresh Wolvrix binding

首次 import 启动后，动态链接审计发现 editable venv 仍加载 7 月 13 日的旧
`libwolvrix-lib.so`。该进程在 activity-schedule 的 `source_clone_refreeze` 前被主动中止，没有产生
emit 文件。随后执行仓库标准 editable install，确认 `.venv` 中 native module 和 shared library 均为
当前源码，并包含 ordered external-call 调度校验字符串。

```text
python3 -m pip install --no-build-isolation -e wolvrix
ctest --test-dir wolvrix/build -R '^transform-activity-schedule$'
```

定向测试通过，fresh import 使用 `run14_import_fresh` 日志。

## Direct LoadJson 与 activity-schedule

```text
read_gsim_executable_grh=24.947 s
activity-schedule=120.732 s
write_grhsim_cpp=69.870 s
total=215.552 s
wall=3:37.47
maxRSS=34,284,560 KiB
exit=0
```

脚本明确记录 executable branch 跳过 pre-schedule normalization、reg-to-mem 和 stats，LoadJson 后
直接进入 activity-schedule。主要规模：

```text
input ops=7,757,160
topo edges=12,832,384
source clones=2,662,209
post-clone ops=10,419,369
compute nodes=861,970
compute supernodes=112,840
commit supernodes=7
final supernodes=112,847
final DAG edges=636,801
compute ops max=108
```

schedule stats：

```text
ptmp/gsim_full_exec_20260714/run14/grhsim_emit/activity_schedule_supernode_stats.json
```

## GrhSIM C++ emit

emit 成功生成 `Makefile`、`grhsim_SimTop.hpp`、runtime header、71 个 schedule translation units、
33 个 state-init translation units及辅助源文件，共 106 个 C++ 文件，目录约 1.3 GiB。

## 后续

构建 XiangShan difftest emulator，先运行 2k sanity，再运行最终 CoreMark `-C 50000` NEMU
difftest。只有 50k 退出码 0 且无 mismatch 才算完整目标通过。

## 增量更新

后续 build/run 结果使用新记录；本文保留首次 full export、direct LoadJson、activity-schedule 和 emit
成功的证据。
