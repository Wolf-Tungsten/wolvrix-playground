# TNO0224：SimpleTES 相对 NUMA 页 coverage 门禁与在线恢复

日期：2026-08-07

## 1. 结论

[TNO0223](./TNO0223_simpletes_c333_numa_page_gate_retry_diagnosis_20260807.md) 定位的固定 `20,000` 页误判已修复。
SimpleTES `414ad80899fb6611449a374c5b2c142653975639` 不再要求不同大小的 ELF 达到相同绝对 file-backed resident
pages，而是以 control ELF 的 `PT_LOAD` file-backed footprint 为参考，把原 `20,000` 页换算成最低 coverage，再按
candidate 自身 `PT_LOAD` 页数缩放。严格 `local_ratio >= 0.999`、NEMU 页数/本地比例、fixed-ASLR、CPU affinity、
whole-CCD、PMU 和功能门禁均未放宽。

修复先在独立 worktree 完成并通过 `108/108` 定向、`256/256` 全量回归，再一次性 fast-forward 到 live
`SimpleTES/` 路径。node032 的 launcher/main PID `18435/21161` 没有停止或重启；当前 evaluator 在完成 artifact
build 后动态加载了新的 `runtime.py`，所以同一个 outer attempt 已直接热生效。

真实 c333 candidate audit 从旧结果
`19,877 local / 19,877 total < 20,000, ok=false` 变为
`19,877 local / 19,877 total >= 19,151, ok=true`。该 candidate 随后第一次完整跑完 SimTop 50k，不再在约
10k cycles 被误杀。正式 ABBA+BAAB 随后全部通过，pooled SimTop 50k walltime 为
`48,120.25 -> 44,186.75 ms`，绝对减少 `3,933.50 ms`、提升 `8.174313%`，order gap `0.088714 pp`。
该 candidate 已成为第 `55/64` 个 valid 和新 best，auto research 继续处理剩余 queued evaluations。

## 2. 原则化页数门禁

runtime 新增只读 ELF program-header 解析器，支持 ELF32/ELF64 与大小端，根据 `PT_LOAD` 的 file offset/file size
计算去重后的 file-backed page intervals。它不以整个文件大小代替运行时可映射 footprint，也不依赖外部 `readelf`
命令。

设：

- `R`：control/reference 的唯一 `PT_LOAD` file-backed pages；
- `B`：当前 variant 的唯一 `PT_LOAD` file-backed pages；
- `M=20,000`：原配置的 reference minimum；
- `M_ref=min(M,R)`：reference 自身可实现的最低页数；

则当前 variant 的门槛为：

```text
M_variant = ceil(M_ref * B / R)
```

并继续同时要求：

```text
resident_file_pages >= M_variant
local_pages / resident_file_pages >= 0.999
```

因此 control 与 candidate 必须达到相同的最低 ELF coverage；缩小代码不会仅因总页数下降而被惩罚，未充分触达或
页面落到远端 node 仍会失败。初始 no-control seed 以自身为 reference；如果 future native control 本身小于
`20,000` 个 loadable pages，coverage 会 fail-close 到 `100%`，不会构造不可实现的绝对阈值。

## 3. c333 真实绝对数值

本轮读取 live control/candidate ELF 并由新 parser 得到：

| 项目 | control | candidate |
| --- | ---: | ---: |
| ELF bytes | `91,320,384` | `87,445,568` |
| ELF reduction | - | `3,874,816 B / 4.243101%` |
| unique `PT_LOAD` file pages | `22,260` | `21,314` |
| reference minimum coverage | `20,000/22,260 = 89.847260%` | 同一 coverage |
| effective minimum pages | `20,000` | `19,151` |
| live resident/local pages | `20,825/20,825` | `19,877/19,877` |
| local ratio | `1.0` | `1.0` |
| new minimum headroom | `825` pages | `726` pages |
| audit | PASS | PASS |

candidate 不是通过取消门禁过线：它的实际 resident coverage 为 `19,877/21,314`，高于从 control 保留下来的
`89.847260%` 最低 coverage；其页面也仍须全部位于本次 target NUMA node。NEMU 仍为 `115/115` local pages，要求
至少 `100` 页且 `local_ratio >= 0.95`。

每份 runtime audit 现在还会记录 `min_pages_policy`，包括 policy mode、配置的 reference minimum、control/candidate
loadable pages、coverage 和最终 scaled minimum，避免以后仅看到一个动态数字而无法复算。

## 4. 内部 runtime retry 可观测性

`_run_runtime_with_retries()` 仍保持 `DEFAULT_INFRA_RETRIES=2`，即一次 outer evaluation 最多三次 runtime invocation，
但不再只留下最后一次原因。每次 retryable invocation 的序号、已脱敏 error 和 diagnostics 会按顺序保存在
`diagnostics.runtime_retry_attempts`；若三次都失败，`retry_diagnostic` 会串联三次 error。

这修复了 TNO0223 中“前两次 NUMA 误判、最后一次偶发 CCD load，最终 JSON 只看到 CCD load”的遮蔽问题。
当前 main 在 `a32116d` 之前已经启动，因此内存中的 engine console formatter 不会热替换；新的 evaluator 子进程仍会
把完整 history 写进 immutable JSON，未来正常重启后 console 也会采用已有的限长、脱敏显示逻辑。

## 5. 回归

| 验证 | 结果 |
| --- | --- |
| changed modules `py_compile` | PASS |
| GrhSIM runtime + bench focused | `108 passed` |
| SimpleTES full pytest | `256 passed`，仅 `24` 条既有 `datetime.utcnow()` deprecation warnings |
| `git diff --check` | PASS |
| synthetic ELF overlapping `PT_LOAD` intervals | 正确去重 |
| reference control scaling | `20,000 -> 20,000`，原 control 强度不变 |
| smaller fully-local candidate | `19,877` pages 在 scaled `19,152` synthetic gate 下 PASS |
| under-coverage candidate | FAIL |
| `local_ratio < 0.999` candidate | FAIL |
| mixed internal retry reasons | 三次顺序、error、diagnostics 和合并 diagnostic 全部保留 |
| node032 live control audit | `20,825 local`, minimum `20,000`, PASS |
| node032 live c333 audit | `19,877 local`, minimum `19,151`, PASS |

测试中的 `19,152` 来自合成 `22,296 -> 21,350` footprints；live ELF 的确切 `22,260 -> 21,314` 换算结果为
`19,151`，两者均使用同一个整数向上取整公式。

## 6. 在线部署与当前运行状态

为避免运行中的 evaluator 读到半成品，修改先在 detached worktree 完成全部测试并提交，再将 live `SimpleTES/main`
从 `a32116d` fast-forward 到 `414ad80`；临时 worktree 在确认提交已被 main 包含后删除。没有 signal、cancel、slot
清理、checkpoint 回退或新 instance。

当时 active evaluator PID `3380832` 在代码部署前已加载旧 `evaluator.py`，但 `runtime.py` 只在 build/功能 gate 后由
`_invoke_runtime()` 动态导入。部署发生在 candidate link 完成前，因此该 evaluator 的第一份新 control audit 已直接
出现：

```text
mode=reference-elf-pt-load-coverage
reference_loadable_file_pages=22260
binary_loadable_file_pages=22260
min_pages=20000
total_pages=20825
local_ratio=1.0
ok=true
```

紧随其后的 candidate audit 为：

```text
reference_loadable_file_pages=22260
binary_loadable_file_pages=21314
min_pages=19151
total_pages=19877
local_pages=19877
local_ratio=1.0
ok=true
```

第一次 runtime invocation 的 control `47,984 ms`、candidate `44,047/45,599 ms` 都完整跑到 50k，但 candidate
第二样本期间外部任务突然让其余 CCD threads 平均 idle 降到约 `89.99%..94.29%`，所以该 invocation 被 continuous
monitor 正确作废，不能作为性能结果。内部 retry 随后在另一空闲 CCD 完成 quiet ABBA：

| order | control walltime | candidate walltime |
| --- | ---: | ---: |
| A | `48,135 ms` | - |
| B | - | `44,097 ms` |
| B | - | `44,271 ms` |
| A | `48,146 ms` | - |
| arithmetic mean | `48,140.50 ms` | `44,184.00 ms` |

该 ABBA 绝对减少 `3,956.50 ms / 8.218652%`，方向为正，因此 evaluator 正常进入 BAAB promotion。promotion 使用
另一组安静 CCD，结果为：

| order | control walltime | candidate walltime |
| --- | ---: | ---: |
| B | - | `44,240 ms` |
| A | `48,159 ms` | - |
| A | `48,041 ms` | - |
| B | - | `44,139 ms` |
| arithmetic mean | `48,100.00 ms` | `44,189.50 ms` |

BAAB 绝对减少 `3,910.50 ms / 8.129938%`；ABBA 与 BAAB improvement gap 为 `0.088714 pp`，低于既定
`0.25 pp` order-gap 门槛。四样本 pooled 正式结果为：

| 指标 | 绝对值 |
| --- | ---: |
| control pooled walltime | `48,120.25 ms` |
| candidate pooled walltime | `44,186.75 ms` |
| absolute reduction | `3,933.50 ms` |
| relative improvement | `8.174313%` |
| score | `1.0890198984989845` |
| control spread | `118 ms` |
| candidate spread | `174 ms` |

immutable attempt `01786094909198670422-3380832-9a9eea749adc4941ad767a5a53e89d49` 已发布为
`valid_candidate=1`、`infrastructure_retry=0`，且 `direction_consistent_positive=true`。新 checkpoint
`db_state_172829` 的绝对状态为 `72 generation attempts / 63 completed evaluations / 55 valid evaluations`，best node
为 `2525589049e448db9633df499dd04fd1`，best score 从 `1.0772030197366194` 更新为
`1.0890198984989845`。checkpoint 发布后 scheduler 已自动取走下一项：截至 `17:29 CST` 为
`1 active / 0 queued` generation、`1 active / 2 queued` evaluations；新 evaluator PID `3475793` 已由未重启的 main
启动，没有因修复或结果发布而停止。
