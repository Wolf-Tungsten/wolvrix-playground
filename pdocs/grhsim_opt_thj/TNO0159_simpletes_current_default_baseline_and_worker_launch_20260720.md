# TNO0159 SimpleTES current-default baseline and worker launch

日期：2026-07-20

状态：正式 SimpleTES instance `91f6580e` 已完成 fresh current-default build、focused tests、
100/10k 功能门禁和一组有效 dynamic-CCD ABBA 50k 基线；四个样本的绝对
`Host time spent` 为 `74,900 / 74,933 / 74,956 / 74,441 ms`。SimpleTES 已接受初始节点并
实际启动 `gpt-5.6-sol`/`ultra` generation worker。当前没有优化候选完成评价，wolvrix
默认配置没有改变。

## 1. Identity and artifacts

```text
instance                  91f6580e
checkpoint                SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01
slot                      /tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0
parent                    b90d20461d276def682f19a28be1fe65a4387eef
wolvrix                   f17e90e14c3ad70a3ee93f7c6540e13dae54940a
generated fingerprint     57819a3d9f1165af8dbfe1976b152a8664b7b1d69a908c13198b9c918c50d2a2
build-config fingerprint  920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3
toolchain fingerprint     3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038
emu SHA256                b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6
emu bytes                 93,671,768
archive bytes             99,248,718
image SHA256              c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
NEMU SHA256               094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e
```

fresh activity-schedule 的绝对结构值为 `63,709` supernodes、`63,241/468`
compute/commit、`527,990` DAG edges、`1,000,463` boundary values、`1,983,326`
boundary activation edges；与 [TNO0154](./TNO0154_stage33_fresh_same_commit_default_control_20260719.md)
的 current-default 值完全一致。生成日志同时明确 waveform/perf/runtime-profile 均关闭，
所有实验 policy 为 `cpp-default` 或 `off`。

## 2. Build and function gates

```text
focused Python tests  24 passed, exit 0
100-cycle endpoint    instr/cycle/guest = 0/96/101, Host time spent = 163 ms
10k endpoint          instr/cycle/guest = 458/9996/10001, Host time spent = 9,975 ms
```

两轮均由 `setarch x86_64 -R` 执行，只有一个正 walltime，且无
mismatch/assert/fatal/bad-trap。build/focused log 含一条非致命
`sitecustomize: ModuleNotFoundError: rich` 环境告警，但相关命令 exit `0`、24/24 tests 通过，
生成 fingerprint/功能/50k 均闭合；它不进入 walltime。后续可单独清理日志噪声，不能因此
改写本轮 accepted 结果。

## 3. Dynamic CCD placement

sysfs L3 动态选择到：

```text
NUMA node       0
CCD CPUs        64-71,256-263
target/sibling  66/258
helper          96 (outside measured CCD)
selection gate  count=16 mean=99.814375% min=99.34%
                target=100.00% sibling=100.00%
```

每个样本重新通过 3 秒 whole-CCD pre-gate；运行期间持续监控其余 15 个逻辑 CPU：

| sample | pre mean/min/target/sibling idle | runtime other-15 mean/min/sibling idle |
| --- | ---: | ---: |
| 1 | `99.833750/98.67/100.00/99.67%` | `99.730667/99.20/99.99%` |
| 2 | `99.834375/99.33/100.00/100.00%` | `99.703333/99.19/99.97%` |
| 3 | `99.710625/99.00/100.00/99.67%` | `99.756000/99.22/99.99%` |
| 4 | `99.833750/98.67/100.00/100.00%` | `99.670667/99.09/99.96%` |

四次均满足 mean `>=98%`、minimum `>=95%` 和 target/sibling `>=98%`。每次 workload
进程的 `Cpus_allowed_list=[66]`、personality=`00040000`、resolved executable 为独立
`/dev/shm` inode；binary `21,260/21,260` pages、NEMU `115/115` pages 均在 node0，
local ratio=`1.0`。

## 4. Accepted 50k absolute walltime

ABBA 初始节点的 A/B 都指向同一 current-default ELF；role 名只用于检验框架顺序，不是
优化对比：

| index | role | `Host time spent` | functional endpoint |
| --- | --- | ---: | --- |
| 1 | control A1 | `74,900 ms` | `50001/49996/73580/0x80001312` |
| 2 | control-alias B1 | `74,933 ms` | same |
| 3 | control-alias B2 | `74,956 ms` | same |
| 4 | control A2 | `74,441 ms` | same |

```text
all-four arithmetic mean  74,807.5 ms
all-four absolute range   515 ms = 0.688433646% of mean
A mean                    74,670.5 ms
B mean                    74,944.5 ms
B-A                       +274.0 ms = +0.366945447%
initial score             0.996343961198
evaluation elapsed        2,622.668 s
```

因为 A/B 是同一 generated fingerprint，`+0.3669%` 只量化本窗口的顺序噪声，不能解释为
代码回退。后续候选必须与同组 fresh current-default 比较；只有候选 wall 严格正向才补
`BAAB` promotion，最后按全部绝对样本的算术均值决定保留/default。

## 5. PMU and scheduler audit

四次所有五个 PMU events 与 task-clock/context-switch/migration 都为 `100.00%` scheduled，
task clock 均为 `1.000 CPUs utilized`，CPU migrations 全为 `0`。context switches 原值为
`159 / 185 / 168 / 407`，对应 `2.122 / 2.468 / 2.241 / 5.467 per second`，均低于
`20/s` 硬门槛。全部 sample 的 affinity、personality、NUMA、PMU、scheduler、function 和
唯一 walltime gate 均为 PASS。

## 6. Auto-research launch state

02:49:15 框架记录：

```text
Initial score: 0.996344
Starting 1 gen workers and 1 eval workers
Starting scheduler loop
```

随后宿主机进程确认真实 backend 参数为 `gpt-5.6-sol`、reasoning effort `ultra`、
read-only sandbox；generation worker 正在读取仓库、历史文档和 generated C++。截至本文，
gen worker 为 `1 active / 3 queued`，eval queue 尚为空，valid candidate 仍为 `0/8`。
正式会话继续运行；本阶段没有候选代码、没有 wolvrix 子模块提交，也没有默认开关变化。
