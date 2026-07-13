# NO0424 Full active-word fixed-ASLR runtime plan

日期：2026-07-12

## 1. Objective and binaries

[NO0423](./NO0423_simtop_full_active_word_50k_functional_gate_20260712.md) 已闭合 SimTop 功能回归。本轮测量
完整 compute word consume 相对同一 direct state-read baseline 的实际 runtime 影响：

```text
baseline:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim-compile/emu
candidate:
  build/xs_grhsim_no0416_full_word_consume_20260712/grhsim/grhsim-compile/emu
```

两者 graph、schedule、direct state-read、commit 和 persistent layout 相同；candidate 只在 7,853 个 full compute
word 删除 62,824 次 local clear 与 7,853 次 restore。主要假设是 host instructions 下降，并至少部分转化为 cycles
收益。

## 2. CPU selection

在任何 PMU run 前，把 survey 进程固定到 CPU0，对 NUMA1 的 96 对 SMT siblings 执行五秒 `mpstat`。当前最安静
的是：

```text
primary CPU=191
sibling CPU=383
node/socket/core=1/1/191
five-second average idle=100.00% / 100.00%
```

survey 时全机 load average 约 `45/41/43` on 384 CPUs、available memory 约 936 GiB。选择后从 100-cycle
preflight 开始锁定 CPU191，不因中途排名变化而换核。

## 3. Controlled A/B/A

正式顺序固定为 baseline / candidate / baseline：

- 每条命令先 `source env.sh`；
- 外层 `setarch "$(uname -m)" -R` 固定 PIE load base；
- `numactl --membind=1 taskset -c 191` 固定 memory node 与运行核；
- 监控 sibling CPU383；
- seed 0、CoreMark image、NEMU difftest、`-b 0 -e 0 -C 50000`；
- `EMU_RUNTIME_PROFILE` unset，`EMU_PROGRESS_EVERY_CYCLES=0`；
- 每轮前记录 load/memory/process，并执行 `mpstat -P 191,383 1 3`；两核平均 idle 都必须 `>=99%` 才启动，
  rejected attempt 原样保留；
- 即使全机负载变化，也始终现场夹跑两侧 baseline，不引用历史绝对时间。

正式事件组沿用 NO0362/NO0382：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

先对 candidate 做相同绑定的 100-cycle preflight，五事件必须全部 100% scheduled，且 fixed-ASLR state address
为稳定 `0x5555...` 形式，才进入 50k A/B/A。

## 4. Acceptance gates

三轮均要求：

```text
exit=0
Guest cycles=50,001
cycleCnt=49,996
instrCnt=73,580
terminal PC=0x80001312
```

不得出现 mismatch、assert/abort、fatal/error、segmentation fault 或 `input_fullpass_blocked`。五事件均须
100% scheduled；两次 baseline cycles spread 必须 `<=1%`。任一失败则不形成 candidate/baseline ratio。

以两次 baseline 均值计算 host time/cycles/instructions、IPC、frontend empty/cmask6/backend stall 的绝对值和
per-cycle density，并计算删 instructions 对 cycles 收益的实现比例。

## 5. Layout caveat

candidate text 比 baseline 小 674,176 bytes，117 个 sched function 的后续入口地址因此改变。native fixed-ASLR
A/B/A 回答单一可复现 load base 下的整体结果，但不能单独证明删语句机制的 layout-independent cycles 收益。若 cycles
方向与 instructions 方向相反、或 cmask6 density 变化超过 1%，下一步必须复用 NO0378 的 explicit-link padding
方法构造对应 sched entry 同址版本，再做 exact-entry A/B/A；不能直接把 native layout 结果归因于协议本身。

## 6. Planned artifacts

```text
build/logs/xs_perf/no0424/numa1_idle_survey.log
build/logs/xs_perf/no0424/candidate_preflight_{emu.log,perf.csv}
build/logs/xs_perf/no0424/{baseline1,candidate,baseline2}_{emu.log,perf.csv}
build/logs/xs_perf/no0424/*_quiet_gate_attempt_*.log
```
