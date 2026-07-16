---
id: NO00029
date: 2026-07-16
title: Executable exchange workflow freshness and validated-default hardening
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, makefile, freshness, validation, xiangshan]
parents: [NO00028]
related: [NO00023, NO00027]
supersedes: []
---

# NO00029 Executable exchange workflow freshness and validated-default hardening (2026-07-16)

> 归档编号：`NO00029`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 问题

NO00028 已证明手工固定产物和参数时，GSim executable GRH -> GrhSIM 可以通过 XiangShan
CoreMark 50k。顶层 `xs_gsim_executable_grh_*` 入口仍有三个复现风险：

1. 默认 `XS_GSIM_BIN=reference/gsim/build/gsim/gsim` 只检查可执行，可能早于 exporter 源码；
2. import 只检查 Wolvrix native binding 已存在，不保证它包含当前 emitter/scheduler 修改；
3. import 沿用 direct-SV 的 target-256 默认值，并让 split 取脚本默认值，未复现通过 gate 的
   target-512、split-on 配置。

此外 executable envelope guard 检查 nested `gsim.boundary`，但遗漏 root `boundary`。损坏的 root
metadata 会通过所谓 strict validation。

## 实现

顶层 `Makefile` 现在：

- 新增 `xs_gsim_executable_grh_gsim`；使用默认 GSim 路径时先增量执行 `build-gsim`，自定义
  `XS_GSIM_BIN` 时保持 no-op；
- `xs_gsim_executable_grh_export` 依赖上述 freshness target；
- `xs_gsim_executable_grh_import` 依赖 `py_install`，遵循仓库已激活 `.venv` 的标准口径刷新
  native binding；
- 为 executable exchange 单独定义并显式传递已验证参数：compute supernode/node 108、split
  enabled、split max 108、commit max 4096、commit guard buckets enabled、batch max ops 2048、
  estimated lines 8192、target count 512、每 TU 一个 batch、emit parallelism 4。

`scripts/wolvrix_xs_grhsim.py` 的 executable guard 现在要求 root
`boundary=PreCoarsen`，再检查 root/nested metadata 一致性。

## 验证

### 默认 GSim freshness

通过新 target 实际重建默认 binary，exit 0：

```text
reference/gsim/build/gsim/gsim
mtime=2026-07-16 15:52:26 +0800
size=19288864 bytes
```

随后在默认 build 目录运行：

```bash
make -C reference/gsim test-executable-grh-synchronous-memory-address
```

checker 输出 `executable GRH synchronous-memory-address PASS`，exit 0。自定义
`XS_GSIM_BIN=ptmp/.../gsim_exporter_fix_build/gsim/gsim` 的 dry-run 不触发默认 binary build。

### Binding 与参数

使用已激活环境等价口径执行：

```bash
make py_install PYTHON=.venv/bin/python
```

editable wheel build/install exit 0，`.venv` native module 刷新。直接使用系统 Python 会被 PEP 668
拒绝，这是未激活仓库环境的预期保护，不使用 `--break-system-packages` 绕过。

`make -n xs_gsim_executable_grh_import` 确认先执行 `py_install`，并包含：

```text
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE=108
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES=1
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS=108
WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS=1
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=512
```

顶层 `xs_gsim_executable_grh_emu` 指向 NO00028 产物执行成功，wall 0.36 s，并生成：

```text
difftest/emu -> difftest/grhsim-compile/emu
```

### Envelope 负例

构造 root `boundary=PostCoarsen`、nested boundary 仍为 `PreCoarsen` 的小 envelope；strict guard 在
LoadJson 前返回 `bad root boundary rejected`。NO00028 的完整 2.78 GB artifact 仍验证为
`xiangshan-gsim-coremark-stub`。

最终 `git diff --check` 通过。验证日志与小型负例保存在：

```text
ptmp/gsim_assign_elide_20260716/workflow_fix/
```

## 结论

正确性修复和通过 50k 的配置现在不再只存在于一次性脚本：默认顶层流程会刷新两个 native
producer，并显式使用已验证的 executable scheduling/emitter 参数。自定义 GSim binary 仍可用于
受控实验，不会被默认构建覆盖。

## 增量更新：公开入口回归

默认 GSim binary 重建后，七个 executable-GRH 定向 target 全部 exit 0：split-register clock、
register-clock liveness、async-reset constant-next、effects、empty memory writer、synchronous memory
address 和 node-final assign elision。其中 effects 同时通过 native unit 与 exported model checker。

公开运行入口也直接复用 NO00028 产物完成 2k NEMU difftest：

```bash
make run_xs_gsim_executable_grh_emu \
  XS_GSIM_EXECUTABLE_GRH_ROOT=ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512 \
  XS_SIM_MAX_CYCLE=2000 RUN_ID=workflow_public_2k
```

结果为 `instrCnt=3, cycleCnt=1996, guest cycles=2001`，exit 0，无 assertion、mismatch 或 ABORT。
这确认 Makefile 的 build symlink 和 run target 与手工验证路径一致。
