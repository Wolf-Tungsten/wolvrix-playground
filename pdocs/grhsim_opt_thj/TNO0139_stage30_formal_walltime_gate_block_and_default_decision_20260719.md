# TNO0139 Stage 30 formal walltime gate block and default decision

日期：2026-07-19

状态：Stage30 12-pair strict 获得一组完整有效的 N0 ABBA，但 N0 BAAB 和 N1
ABBA/BAAB 在持续外部 CI 负载下无法形成有效组。单个 node/order 的 walltime 是正向信号，
但不满足双 NUMA balanced 采用条件，因此 `cofire-strict` 保持显式 default-off；本阶段
不能声称端到端性能已提升，也不能据此否定该机制。

## 1. Formal 协议

control/candidate/image/NEMU 使用 TNO0138 记录的每 node 独立 fresh `/dev/shm` inode；
复制时在目标 CPU 上执行 `taskset + numactl --physcpubind/--membind` first-touch。
运行使用：

```text
taskset -c <cpu> numactl --physcpubind=<cpu> --membind=<node> \
  perf stat ... -- setarch x86_64 -R <emu> \
  -i <coremark> --diff <nemu> -b 0 -e 0 -C 50000
```

runner 对每个样本要求：30 秒整 node admission 的 192 threads
`mean_idle>=99%`、`min_idle>=95%`、target/sibling `>=98%`；运行期除 target 外
191 threads 同样满足 mean/min；emu 页面 `>=99.9%` local 且总页数 `>=20000`，NEMU
页面 `>=95%` local 且总页数 `>=100`；五项 PMU scheduled、migration=0、功能终点、
fixed ASLR、唯一正 `Host time spent` 全部通过。

## 2. 唯一完整有效组：N0 ABBA try2

raw 目录：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/
  stage30_deferred_activation_12pair_strict_final_abba_try2/
```

每个样本的 `run_status/placement/monitor/perf/scheduler/function/affinity/walltime_ok`
全部为 1；功能终点均为 `instrCnt=73,580`、`cycleCnt=49,996`、guest=`50,001`。
control emu placement 为 `21260/0` pages，strict 为 `21272/0` pages，NEMU 均为
`115/0` pages。

| sample | variant | Host time spent / walltime_ms | instructions |
| --- | --- | ---: | ---: |
| a1 | control | 74,500 ms | 164,223,417,761 |
| b1 | strict | 74,293 ms | 164,203,497,807 |
| b2 | strict | 74,239 ms | 164,203,497,344 |
| a2 | control | 74,359 ms | 164,223,417,583 |

该组的 walltime 绝对均值为：

```text
control=74429.500 ms
strict=74266.000 ms
delta=-163.500 ms
delta=-0.219670964%
```

instructions 绝对均值为 control=`164,223,417,672.0`、strict=`164,203,497,575.5`，
差 `-19,920,096.5`（`-0.012129876%`）。instructions 只解释 Stage30 删除 648 个
tracked values 的动态影响，最终口径仍是 walltime；单个 N0 ABBA 不能外推到双 NUMA。

## 3. 被排除的 attempts

以下 walltime 都直接来自 raw `*_result.env`，但只要同组任一样本失败，就整组作废且不
拼接旧样本：

| node/order/try | 已启动的绝对 walltime | 排除原因 |
| --- | --- | --- |
| N0 ABBA try1 | control `74,504/74,482`；strict `74,309/74,376` ms | 最后 control 运行期 min idle=`94.600%`，`monitor_ok=0` |
| N0 BAAB try1 | strict `74,363`；control `74,393/74,435` ms | 第二 control min idle=`94.700%`；第四样本未启动 |
| N0 BAAB try2 | strict `74,512`；control `74,413/74,419` ms | 第二 control min idle=`94.980%`；第四样本未启动 |
| N0 BAAB try3/try4 | 无 | 各 10 次 30 秒 admission 均无 quiet window |
| N1 ABBA try1 | 无 | 10 次 30 秒 admission 均无 quiet window |
| N0 BAAB try5 | 无 | 60 次 30 秒 admission 均无 quiet window |

try5 raw driver：

```text
build/logs/xs_perf/stage30_deferred_activation_12pair_strict_20260718/
  n0_baab_try5_driver.log
sha256=0bdc6b739b3eb86075964c50927c0c96b7154197a1b8550d15597e5f23da74a0
bytes=1310
```

try5 group 中 60 个 `b1_whole_node_gate_attempt*.log` 共 `34,827,720` bytes；每个
都完整包含 192 threads。60 次 mean idle 范围为
`95.870729%..98.434844%`，低于 99%；每次 min idle 都是 `0%`，所以没有启动
emu、没有 walltime 样本。

同一 30 分钟监控期内两节点持续有外部 cirunner emu：数量在 `6..10` 间变化，任务
结束后 CI 又补充新任务。最后完整窗口 N0 mean/min=`96.564948%/0%`，N1 为
`98.376250%/0%`；没有终止或改绑任何外部进程，也没有降低门槛。

## 4. 决定

1. N0 ABBA 的 `-0.219670964%` 是值得继续验证的正向信号，但不是双 NUMA headline。
2. 没有有效 N0 BAAB、N1 ABBA/BAAB，无法形成 balanced walltime，也无法判断 node
   对称性和样本 spread。
3. Stage30 保留 `cofire-strict` 显式入口，C++ 默认继续 `off`；XS 不增加独立默认。
4. 后续安静窗口可用新 attempt 重测，不复用无效组。与此同时 Stage31 先扩展小型
   no-mutation cofire probe，不把 Stage30 未完成的 walltime 当作 strict 采用证据。

