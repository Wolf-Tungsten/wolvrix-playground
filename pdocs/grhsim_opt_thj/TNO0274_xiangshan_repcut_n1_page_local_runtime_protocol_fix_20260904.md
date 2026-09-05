# TNO0274: XiangShan RepCut N=1 page-local runtime protocol fix

日期：2026-09-04

状态：`IMPLEMENTED AND TESTED; LEGACY PAGE-CONFOUNDED RESULTS ISOLATED; N=1 AB/BA RETEST IN PROGRESS`。

## 1. 目的

[TNO0273](./TNO0273_xiangshan_repcut_n1_frontend_numa_page_root_cause_20260904.md)
确认旧 N=1 runner 没有控制或验证数百 MiB executable 的 file-backed page residency，
导致 baseline/candidate 分别约 `98.95% local/99.27% remote`。本篇修正实验协议，
不改变 RepCut 算法、RTL、生成模型、N=1 dispatch 或冻结功能签名。

旧 runner `run_n1_pair.py` 保持不变，用于解释历史 artifact；新协议使用：

```text
build/repcut_closure_runtime_20260902/run_n1_pair_v2.py
protocol_revision = n1-page-local-v2
SHA-256 = 2019def21d67ef009041857c686136a686f58a156483bfa978fb5d3baa7f9f0a
```

新旧结果不能混池。`summarize.py` 与 `pool_order_results.py` 已增加 revision、
placement gate 和 AB/BA pair identity 检查。

## 2. 修正后的输入 staging

每个 order、每个 arm 都在目标机器 `/dev/shm` 下创建独占目录，并分别复制：

1. partitioned Verilator ELF；
2. CoreMark image；
3. NEMU shared object。

因此一个 order 有 6 个 staged regular inode，runner 要求它们的
`(st_dev, st_ino)` 全部互异、`nlink=1`、非 symlink。复制和 staged SHA 均由目标
CPU/NUMA 执行，核心命令形态为：

```bash
taskset --cpu-list CPU \
  /nfs/home/tanghaojin/bin/numactl \
  --physcpubind=CPU --membind=NODE \
  cp --reflink=never --sparse=never --preserve=mode,timestamps -- SOURCE DEST
```

staging 前检查目标 mount 的 filesystem type 必须是 `tmpfs`，并检查可用空间；
copy 后记录 source/staged size、SHA-256、mode、device major/minor、inode、nlink、
mtime/ctime 和完整 argv。实际仿真命令只引用 staged ELF/image/NEMU，不再引用 NFS
原文件。

旧 runner 在 admission 后、运行前后会由 monitor CPU 全量 SHA 数百 MiB ELF；
v2 删除了这条 gate-to-run 干扰。每个 sample 前后只比较 cheap stat identity，整个
order 结束后再由目标 CPU/NUMA 对 6 个 staged 文件做一次完整 SHA 复核。source
build manifest 也在 order 前后复核。

本阶段为了保留审计现场，不自动删除精确 staged 目录；header 明确记录
`staging_cleanup_policy = retained for audit; no automatic deletion`。它们只是 node-local
传输身份，持久 build identity 仍是 clean-v4 manifest 与 source ELF SHA。

## 3. 运行中 executable page audit

v2 不按 `numa_maps` 的 `file=/path` 字符串识别映射。每次连续审计按以下链路取证：

1. 从 outer perf PID 枚举 descendant；
2. 用 `/proc/PID/exe` 的 `(st_dev, st_ino)` 确认实际 model 是该 arm 的 staged ELF；
3. 记录 `(PID, /proc/PID/stat start_ticks)`，防止 PID reuse；
4. 从 `/proc/PID/maps` 选择 dev-major/minor+inode 等于 staged 文件且 permissions 含
   `x` 的 VMA；
5. 按 VMA start address 与 `/proc/PID/numa_maps` 关联；
6. 解析每个 `N<node>=pages` 和 `kernelpagesize_kB`，以 byte 计数，兼容非 4 KiB 页；
7. 保存每次 compact sample 和 resident coverage 最大的完整 VMA snapshot。

这同时规避同名不同 inode、路径含空格、`(deleted)` 后缀和非 executable rodata 映射
被误计的问题。

## 4. C=10000 page gate

`C=100` 仍只是功能签名门，不因运行太短而强求页采样。`C=10000` 在 strict 和
diagnostic 两种 policy 下都执行相同的硬 page gate：

| 对象 | resident 下限 | executable coverage | target-node local ratio |
| --- | ---: | ---: | ---: |
| model ELF RX VMA | 20,000 个 4 KiB 等价页 | >=95% | >=99.9% |
| NEMU RX VMA | 64 个 4 KiB 等价页 | >=90% | >=95% |

NEMU 门槛是 64 而不是 100，因为当前 NEMU 的 executable VMA 总量约 303,104 B，
实际稳定 resident 为 71 个 4 KiB 页；100 页是此前把非 executable file mappings
也计入时的粗口径。

另外：

- model 与 NEMU 各至少需要 3 个 qualifying samples；
- model identity 必须恰好一个；
- audit parse/error 非空即拒绝；
- 从 model resident 达到 20,000 个等价页、NEMU 达到 64 页起，任一 sample 的
  local ratio 低于阈值都拒绝，不能只靠最后或最佳快照掩盖 transient remote pages。

`99.9%/95%` 是显式容差，不等价于声称绝对零 remote；artifact 同时保存绝对
local/remote bytes。本次 root cause 是 candidate 约 99% remote，因此该门足以排除
原 confound；正式复测还应报告实际是否为 `remote_bytes=0`。

## 5. 其他 admission 不放宽

v2 继续复用 `run_matrix_v6.py` 的 topology、3x1 s admission、affinity、continuous
foreign-task、full-CCD guard、target unexplained-busy、perf、timing JSONL 和冻结签名
校验。

diagnostic policy 仍只豁免 `runtime_foreign_task_load`，不豁免：

- `runtime_guard_mean_idle`；
- `runtime_guard_min_idle`；
- `runtime_unexplained_target_busy`；
- affinity/model identity；
- 新增 page placement gate。

admission 失败后新增 5 s 可配置退避，避免机器负载突发时瞬间耗尽所有 retry；退避
发生在 workload launch 之前，不进入 accepted sample 计时。

## 6. AB/BA pair identity

每个 opposite-order pair 记录同一个 `pair_id`，并冻结：

- hostname、boot ID、uname/kernel；
- target CPU、NUMA、monitor CPU 与完整 CCD topology；
- source binary、image、NEMU、build manifest 和工具 identity；
- page gate 参数与映射匹配方法；
- arm order 和 protocol revision。

pooling 时要求 AB/BA：顺序相反但上述上下文相同，且两个 order 的 12 个 staged
inode 全部互异。这样反序只平衡 order，不会重新复用同一个 tmpfs page-cache inode。

## 7. 验证

聚焦测试：

```text
python3 -m unittest -v \
  build/repcut_closure_runtime_20260902/test_run_n1_pair_v2.py

Ran 9 tests
OK
```

覆盖项包括：

- maps dev/inode 精确匹配、同名异 inode 和非 executable 排除；
- 路径空格/`(deleted)` 不影响匹配；
- 4 KiB/huge-page byte 换算；
- 无 observation、多个 model identity、audit error；
- local threshold 等号/低 1 byte 边界；
- 少于 3 个 qualifying samples；
- coverage 尚未达到 95% 时已达到 resident 下限的 remote transient 仍拒绝。

`py_compile`、`git diff --check` 同时通过。

## 8. 首次现场 smoke 与边界

node030 的第一次 v2 AB 尝试已经证明 gate 能区分页问题和机器负载问题：

| sample | Host | ELF RX page | NEMU RX page | runtime guard | 结果 |
| --- | ---: | --- | --- | --- | --- |
| baseline | 59.819 s | 61,084 pages, 100% local | 71 pages, 100% local | pass | accepted |
| closure-aware | 69.165 s | 63,177 pages, 100% local | 71 pages, 100% local | mean/min 91.34%/76.18% | rejected |

candidate 的失败 reason 仅为 `runtime_guard_mean_idle/runtime_guard_min_idle`，page gate
通过且 `remote_bytes=0`。该目录没有 `accepted.json`，不能拼接或进入性能结论。
它说明修正后的 runner 不会因为功能完成或页本地就忽略运行中外部负载。

正式 N=1 AB/BA 结果另立增量文档；N=8、N=32 按用户要求暂不执行。

## 9. Artifact

实现与测试：

```text
build/repcut_closure_runtime_20260902/run_n1_pair_v2.py
build/repcut_closure_runtime_20260902/test_run_n1_pair_v2.py
build/repcut_closure_runtime_20260902/summarize.py
build/repcut_closure_runtime_20260902/pool_order_results.py
```

首次负载拒绝证据：

```text
build/repcut_closure_runtime_20260902/runs/
  node030_ccd8_cleanv4_pagelocalv2_diagnostic_ab_20260904_1610/
  node030_ccd72_cleanv4_pagelocalv2_diagnostic_ba_20260904_1615/
```

其中第二个目录是 BA partial：candidate C=10000 page/guard 已通过，但随后大规模 CI
compile 启动，baseline 的 20 次 admission 均未 launch；同样没有 `accepted.json`。
