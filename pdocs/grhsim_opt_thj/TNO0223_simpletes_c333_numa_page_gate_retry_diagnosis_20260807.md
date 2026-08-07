# TNO0223：SimpleTES c333 候选 NUMA 固定页数门禁持续 retry 诊断

日期：2026-08-07

## 1. 结论

[TNO0222](./TNO0222_simpletes_node032_scanner_recovery_and_retry_diagnostics_20260806.md) 修复 dependency scanner 后，
node032 上的 auto research 已从 `34/64` 推进到 `54/64` valid；当前持续 retry 不是 scanner 复发，而是候选
`c3339dcb53a6c6a8` 触发了另一个可稳定复现的 runtime gate 误判。

该候选把 SimTop `emu` 从 `91,320,384 B` 缩小到 `87,445,568 B`，绝对减少 `3,874,816 B`，即
`4.243101%`。进程审计时，control 有 `20,825` 个 file-backed pages，candidate 有 `19,877` 个；两者全部位于
所选 NUMA node，`local_ratio` 都是 `1.0`。但是 runtime 把二进制最低页数硬编码为 `20,000`，通过条件为：

```text
total_pages >= 20,000 && local_ratio >= 0.999
```

因此 candidate 仅因比固定门槛少 `123` 页而失败，即使它的实际 NUMA placement 完全正确。evaluator 把这个结果
标记为 retryable infrastructure，engine 每 `30 s` 对同一个 candidate 开始新的外层 evaluation；每轮还会重新清理、
构建和跑功能门禁，形成约 `36..41 min` 一次、不会增加 valid count 的持续循环。

本阶段只做只读取证和文档记录：没有停止或重启 launcher/main，没有修改 SimpleTES runtime，也没有改动 Wolvrix
源码、默认选项或当前候选。由于 candidate 在正式 50k 运行约 `5 s` 的 process audit 时即被终止，当前没有可用于
性能裁决的 candidate 50k walltime。

## 2. 当前进度与候选状态

最新持久化 checkpoint 为 `db_state_095718`：

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `71` |
| completed evaluations | `62` |
| valid evaluations | `54/64` |
| best score | `1.0772030197366194` |
| scheduler | `0 active / 0 queued` gen，`1 active / 3 queued` eval |

这证明 TNO0222 的 scanner 恢复有效：valid count 已由迁移时的 `34` 增至 `54`，并非仍卡在 control build。
当前 active evaluator 对应 digest
`c3339dcb53a6c6a85400e297f52e4680b9592a26d87547bebd9ab30e6ff9081a`，是一个
`default-path`、零 option、仅修改 `lib/emit/grhsim_cpp.cpp` 的 persistent-state field-sensitive/原生 bool storage
候选。

在每次进入正式 runtime 前，候选均已通过：

| 门禁 | 绝对结果 |
| --- | --- |
| candidate build/link | PASS |
| focused tests | `29/29` PASS |
| fixed-ASLR 100-cycle | PASS，`Host time spent: 116 ms` |
| fixed-ASLR 10k-cycle | PASS，`Host time spent: 4,475 ms` |
| control ELF | `91,320,384 B` |
| candidate ELF | `87,445,568 B` |
| ELF reduction | `3,874,816 B / 4.243101%` |

focused log 开头的 `sitecustomize`/`rich` import warning 不影响 29 个用例全部通过，也不是 runtime retry 的原因。

## 3. 固定页数门禁为何误判

`datasets/grhsim/simtop_50k/runtime.py` 的 `RuntimeConfig.min_binary_pages` 默认固定为 `20_000`；
`audit_numa_maps()` 从 `/proc/<pid>/numa_maps` 汇总目标 ELF 的 file-backed pages，并同时要求绝对页数和本地比例过线。
本轮取证的稳定结果为：

| variant | ELF bytes | 审计总页数 | 目标 node 本地页数 | local ratio | min pages | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| control | `91,320,384` | `20,825` | `20,825` | `1.0` | `20,000` | PASS |
| candidate | `87,445,568` | `19,877` | `19,877` | `1.0` | `20,000` | FAIL |

candidate 的 file size 约为 control 的 `95.756899%`，审计页数也相应减少 `948` 页；其所有已触达页面仍在目标 node。
固定 `20,000` 是按较大 baseline ELF 校准的绝对值，因此优化一旦让二进制缩小约 `4.24%`，就会跨过门槛并被错误
拒绝。这个条件没有证明 remote placement 或缺页异常，只证明“新二进制没有 baseline 那么多可计数页面”。

正式 candidate 进程启动后约 `5 s` 即被 audit 终止，emu log 只到 `10,000/50,000` cycles，配套 perf CSV 为
`0 B`。所以 control 的完整 50k walltime 不能与这段被中止的 candidate 运行配对，也不能据此推断候选性能收益。

## 4. 外层 retry 序列与错误被遮蔽

截至 `2026-08-07 14:54:56 CST` 已完成八个 immutable outer attempts：

| attempt 完成时间 | 对外发布的最终错误 |
| --- | --- |
| `10:33:47` | `NUMA file-page locality audit failed` |
| `11:10:21` | `NUMA file-page locality audit failed` |
| `11:47:27` | `NUMA file-page locality audit failed` |
| `12:24:25` | `NUMA file-page locality audit failed` |
| `13:00:19` | `external load prevented the fixed CCD pre-gate` |
| `13:38:32` | `NUMA file-page locality audit failed` |
| `14:14:23` | `external load prevented the fixed CCD pre-gate` |
| `14:54:55` | `NUMA file-page locality audit failed` |

其中六次最终结果直接报告 NUMA gate；另外两次的 external load 是真实但瞬态的 whole-CCD pre-gate 失败，不是持续
不前进的主因。evaluator 的 `DEFAULT_INFRA_RETRIES=2` 意味着每个 outer evaluation 最多调用 runtime 三次；
`_run_runtime_with_retries()` 当前只返回最后一次内部结果。若前一、两次已经因 candidate 的 `19,877` 页失败，而最后
一次恰好遇到 CCD load，对外 JSON 和 scheduler 日志就只显示 external load，从而遮蔽确定性的页数门禁失败。

第八个 outer attempt 于 `14:54:55` 完成并再次发布 NUMA gate failure。它在 `14:50:25`、`14:52:40` 两次审计
candidate，分别落在
CPU `88` 和 CPU `136` 所属目标 node，结果都精确复现：`19,877` total、`19,877` local、ratio `1.0`、
`min_pages=20,000`、`ok=false`。跨 CPU、跨 NUMA node 的相同结果排除了偶发迁页，足以闭合根因；scheduler 随后
仍按原语义等待 `30 s`，并开始同一 candidate 的下一次 outer retry。

## 5. 建议修复方向（本阶段未实施）

原则化修复应让“是否充分触达本 ELF”随候选自身的可映射规模变化，同时继续严格验证页面位置：

1. 从 ELF `PT_LOAD` 或 `/proc/<pid>/maps` 推导该进程实际可 file-back 的预期页数；
2. 用相对 coverage/合理容差判断是否充分预热，而不是要求所有候选都超过 baseline-sized `20,000`；
3. 保留 `local_ratio >= 0.999`，因此远端页、错误 NUMA node 和明显未充分触达仍会失败；
4. 增加回归：`19,877/19,877` 全本地的小 ELF 应通过，低 coverage 或 remote pages 仍应失败；
5. 让 `_run_runtime_with_retries()` 保留三次内部错误摘要，避免最后一次瞬态 CCD load 覆盖先前确定性失败。

这项修复不需要放宽 fixed-ASLR、功能、PMU、whole-CCD 或最终 SimTop 50k walltime 门禁。当前 main 已经运行并加载
旧 engine，但每个新的 outer evaluator 会重新加载 evaluator/runtime；如后续实施，可以等待当前 outer attempt 自然
结束后由下一次 retry 采用新门禁，无需为了修复而主动停止整个 auto research。

在修复前，当前 candidate 会继续重复同一误判，`54/64` valid 不会自然靠重试跨过该门禁。
