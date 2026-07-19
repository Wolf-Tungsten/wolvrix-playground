# TNO0149 Stage 33 NUMA symmetry and quiet-window recheck

日期：2026-07-19

状态：重新核对 NUMA 拓扑、正式绑定形态并连续执行两轮 whole-node 30 秒 survey。最初
N0 PASS/N1 FAIL，随后落盘重跑变成 N0 FAIL/N1 PASS；失败 minimum 分别出现在 N1
CPU373 和 N0 CPU2，而镜像 target/sibling 本身均接近全空闲。这证明 Stage7+ 早期的巨大
node 差异来自随时间和 CPU 迁移的外部负载窗口，不是两个 socket 的静态不对称，也不是
`taskset`/`numactl` 参数把 node 写反。formal run 仍须每个样本独立通过 pre/runtime gate，
不能把本 survey 当性能样本。

## 1. 镜像拓扑与正式绑定

`numactl -H` 显示 N0=`0-95,192-287`、N1=`96-191,288-383`，每 node 192 个 logical
CPU、约 512 GiB memory，local/remote distance=`10/32`。已重新读取 topology：

| role | N0 | N1 | relation |
| --- | --- | --- | --- |
| primary target | CPU43 / sibling235 | CPU139 / sibling331 | socket-relative physical slot 相同，core id 都为 83 |
| alternate target | CPU86 / sibling278 | CPU182 / sibling374 | socket-relative physical slot 相同，core id 都为 46 |
| helper | CPU191 | CPU95 | 始终放在对侧 node |

正式 workload 的正确形态保持：

```text
taskset -c <target> \
  numactl --physcpubind=<target> --membind=<node> \
  perf stat ... -- \
  setarch x86_64 -R <node-local-/dev/shm-emu> \
    -i <node-local-image> --diff <node-local-nemu> -b 0 -e 0 -C 50000
```

这同时固定执行 CPU、memory allocation node 和 ASLR。每个 node/variant 的 emu、image、
NEMU 都必须由目标 node first-touch copy 到新建的独立 `/dev/shm` inode，再用 live
`numa_maps` 检查 file pages；`membind` 本身不能把已存在的 NFS page cache 变成本地页。

## 2. 第一轮即时汇总及证据边界

第一轮顺序 survey 使用 N0 helper191、N1 helper95，绝对结果为：

| node | count | mean idle | minimum idle | minimum CPU | CPU43/139 | sibling235/331 | gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| N0 | 192 | `99.495781%` | `96.260000%` | 210 | `99.670000%` | `99.230000%` | PASS |
| N1 | 192 | `99.190625%` | `31.200000%` | 373 | `99.700000%` | `99.530000%` | FAIL |

该轮 stdout 只进入 awk，未保存 raw、SHA、bytes 或精确 timestamp。这里如实保留其绝对
汇总来解释为何立即重跑，但不把它冒充可独立审计的正式 gate 证据。

## 3. 落盘重跑的绝对结果

重跑 protocol 为每 node `mpstat -P <全部192线程> 1 30`；门槛是 mean idle `>=99%`、
minimum `>=95%`、target/sibling 各 `>=98%`。raw 目录：

```text
build/logs/xs_perf/stage33_same_batch_cohort_strict_20260719/numa_survey/
```

| node | interval | count | mean idle | minimum idle | minimum CPU | primary target/sibling | alternate target/sibling | gate |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| N0 | `07:45:36.914`..`07:46:06.972` | 192 | `99.138542%` | `31.480000%` | 2 | `99.67% / 98.73%` | `99.87% / 100.00%` | FAIL |
| N1 | `07:46:31.558`..`07:47:01.621` | 192 | `99.455000%` | `95.560000%` | 322 | `98.97% / 99.37%` | `100.00% / 99.90%` | PASS |

raw 绝对元数据：

| artifact | SHA256 | bytes |
| --- | --- | ---: |
| `n0_whole_node_mpstat_30s.log` | `20154f5e5a902bc35ed8e20e4ce1ada5bfa34bd97781c51a5411b434c9a25284` | `580462` |
| `n1_whole_node_mpstat_30s.log` | `da8127eec2d97d79259fabfac2de277860da3f377fe1c35bc0b61eb5bd0da118` | `580462` |
| `summary.txt` | `9028bd3755cea38216ab7e54cde2708a7638385dea41c130769fec1479927500` | `2532` |
| `process_snapshot_after_n1.txt` | `2bb335d683e27197e565b0ef48ff4865b83c0a2860393cdec8202b50b9699572` | `12659` |
| `binding_probe.txt` | `55fa94cab04238e7dc0a038042b0150ee0abab3e21bddd3b03bcd6ef6bca26dc` | `2770` |

N0/N1 的 exact command、date before/after 也分别保存；summary 保留 lowest 20 CPU 的 absolute
idle。两次落盘 raw 大小相同是相同 CPU 数和采样数的自然结果，不代表内容相同，SHA 已明确
不同。逐秒 raw 显示 N0 CPU2 在前约 21 秒几乎持续 user busy，随后恢复空闲；Average 为
`usr=67.29% / sys=1.23% / idle=31.48%`，不是 I/O wait 或平均值解析误差。N1 CPU322 只是
零散 activity，Average 为 `usr=0.63% / sys=3.80% / idle=95.56%`。

独立 binding probe 对 CPU43/139/86/182 分别实际执行 `taskset + numactl`，读取到 affinity
精确为目标单核，`physcpubind` 为同一核，`cpubind/nodebind/membind` 分别为对应 N0/N1。
`/proc/status` 的 `Mems_allowed_list=0-1` 是作业允许范围，不能据此否定进程内部的
`numactl --membind` policy；probe 已直接证明命令没有把两个 node 写反。

## 4. 结论与后续规则

相邻两轮从 N0 PASS/N1 FAIL 反转为 N0 FAIL/N1 PASS，且 minimum 污染 CPU 从373变为2。
因此“NUMA1 天生慢/NUMA0 天生快”不成立；target 核安静也不能掩盖同 node 其他核污染。
当前可见 Java/Bloop 曾在 N1 CPU104 上消耗明显 CPU，但落盘 N1 minimum 是 CPU322；survey
后的 process snapshot 中 CPU2/CPU322 已无持续高 CPU 线程。事后快照只能证明污染已经消退
或迁移，不能识别 `07:45` 的历史 owner，因此不能把每个低 idle 点都武断归因于同一 PID，
也不干预其他用户进程。

后续 Stage33 与 Stage7+ 每一个 50k 样本继续执行：fresh independent inode、30 秒
whole-node pre-gate、运行期 191 non-target monitor、placement/affinity/ASLR/PMU/scheduler/
function/walltime 全 gate。某 node 当前 FAIL 时等待新窗口，不降低门槛，也不跨时间拼接
不完整 order；headline 仍只用唯一的 `Host time spent` absolute walltime。
