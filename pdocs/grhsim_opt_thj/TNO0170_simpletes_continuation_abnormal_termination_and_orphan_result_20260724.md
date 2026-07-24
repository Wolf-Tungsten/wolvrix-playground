# TNO0170 SimpleTES continuation abnormal termination and orphan result

## 1. 结论

[TNO0169](./TNO0169_simpletes_fresh_replication_interim_checkpoint_and_new_best_20260724.md) 记录的 instance `50c610a6` 已不再运行。它没有达到 `16/16`，也没有写正常结束 footer；scheduler/launcher 在最后一个 evaluation 进行中消失，属于异常终止或外部终止，不能记为正常 complete。

截至 `2026-07-24 14:24 +08:00` 的只读核对：

- unified exec session `32342` 已返回 `Unknown process id`
- 宿主进程列表中没有该 instance 的 launcher、SimpleTES evaluator、build、`perf` 或 `emu`
- `run.log` 最后修改时间为 `13:44:55`，末行仍是 `eval workers: 1 active / 3 queued`
- 日志没有 `Final Results`、正常 shutdown、Python traceback、signal 或 exit code
- 临时 slot 在 `14:16:14` 后没有新产物

因此这不是“仍在运行但日志暂时没有输出”，当前没有可以自行继续推进的 worker。

## 2. 最后持久化账本

最后 checkpoint 仍是：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/db_state_092715
```

其 metadata 写于 `09:27:15`：

- completed evaluations：`7`，即 initial `1` 次加 generated valid `6` 次
- valid evaluations：`6/16`
- generation attempts：`15`
- generation failures：`6`
- evaluation failures：`0`
- best node：`07aed5e981084c0d9befc39643a50728`
- best digest：`c0c066cd9b9e824e`
- best score：`1.2326159492826159`
- best walltime：`73,883.00 -> 59,940.00 ms`，改善 `13,943.00 ms / 18.871730%`

checkpoint 之后的 live log 还出现一次 generation failure 和一次 generation success，但没有新 checkpoint，故不把推导出的实时 attempts/failures 写成最终 durable 账本。终止时显示的另三个 queued evaluation 没有开始运行。

## 3. 脱离 scheduler 完成的 evaluation

最后在途 digest `1051b1e8a495bfb6` 曾在 `11:05:53` 和 `12:39:24` 两次因 quiet-CCD infrastructure contamination retry。第三次运行开始后，scheduler 日志在 `13:44:55` 停止，但 evaluator 子进程继续写产物，并在 `14:16:14` 生成：

```text
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_result_1051b1e8a495bfb6.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_1051b1e8a495bfb6.json
```

该 evaluation 本身是有效的正式结果：

| order | 原始顺序 (ms) | control mean (ms) | candidate mean (ms) | 改善 (ms) | 改善 (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `C 74657 / K 60775 / K 60674 / C 74499` | `74,578.00` | `60,724.50` | `13,853.50` | `18.575853%` |
| BAAB | `K 60485 / C 74262 / C 74182 / K 60536` | `74,222.00` | `60,510.50` | `13,711.50` | `18.473633%` |
| pooled | 上述 8 个样本 | `74,400.00` | `60,617.50` | `13,782.50` | `18.524866%` |

- score：`1.2273683342269146`
- control spread：`475 ms / 0.638441%`
- candidate spread：`290 ms`
- ABBA/BAAB 方向一致
- quiet-CCD、personality `00040000`、affinity、NUMA、PMU、零 migration 与功能 gate 均通过

但 scheduler 已经消失，没有 ingest 这个 JSON，也没有把它写进 `nodes.json` 或新 checkpoint。因此 durable ledger 仍是 `6/16`；该孤立结果可以作为额外正式证据保存，但不能伪称 instance 已 checkpoint 到 `7/16`。它的 score 也低于持久化 best，不改变最佳候选。

## 4. 原因边界

现有文件只能证明 launcher/scheduler 在 `13:44:55` 左右停止，而 evaluator 子进程继续到 `14:16:14`。没有退出码、signal、traceback 或系统 OOM 证据，无法确定具体根因。

从 `2026-07-23 19:42` 到日志停止约为 `18 h 03 min`，外层 exec/PTY 或执行时限是可能解释，但目前只是推断，不能记录成已证实原因。

## 5. 当前决定

- 不把该 instance 标记为正常完成。
- 不自动 resume、fresh restart 或重放三个 queued candidate。
- 保留最后 durable checkpoint、孤立 valid evaluation 和当前 best program。
- wolvrix 与默认配置不变；四组件正式消融仍未完成。

后续若继续搜索，需要显式决定是从 durable best fresh 启动，还是先增强 SimpleTES 的外层会话持久化和 orphan-result 恢复；本记录不替用户作该决定。
