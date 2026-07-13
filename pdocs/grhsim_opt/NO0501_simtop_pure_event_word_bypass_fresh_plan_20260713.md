# NO0501 SimTop pure-event word bypass fresh plan

日期：2026-07-13

## 1. Candidate scope

承接 [NO0500](./NO0500_simtop_pure_event_word_profile_50k_gate_20260713.md)，从同一 pre-reg-to-mem checkpoint
fresh 生成 production candidate：

```text
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE=0
GRHSIM_EMIT_RUNTIME_PROFILE=0
```

checkpoint/read-args、ordered/decoded reg-to-mem、108-op compute supernode、4096-op commit、64-batch target、4 路 emit、
full-active-word consume off 与 `level-id` topo 全部保持 NO0357/NO0496 配置。输出：

```text
build/xs_grhsim_no0501_pure_event_bypass_20260713/grhsim/grhsim_emit
```

## 2. Fresh source gates

- schedule stats SHA 与 NO0357/NO0496 的 `e3056375...` 一致；
- direct-state-read 仍为 `75,830/40,108/35,722`；
- marker 数精确为 107，分布在 NO0496 的相同 22 batches；
- 无 profile getter、arrays、increments 或 TSV dump；
- 相对 NO0357 只允许 22 个 sched files 改变，header/state/eval/init 必须 byte-identical；
- 22 个 sched diff 只新增每 word 的 marker、outer event guard 和 restore 后 closing brace，删除 0 条原 payload source；
- representative batches 35/58/21 的 marker 数为 37/21/8。

## 3. Build and function gates

fresh source 通过后，以标准 Clang O3/difftest GrhSIM 入口构建独立 emu。要求 153 generated compiles、117 sched
objects、完整 archive/link 和 0 errors。记录全 binary text/instruction delta，但静态改善不代替 runtime。

功能依次执行：

1. 100-cycle smoke，检查初始化/NEMU 与历史 guest endpoint；
2. 10k CoreMark，10 个 checkpoints 与 NO0360/NO0499 一致；
3. 50k CoreMark，5 个 checkpoints、73,580 instructions 与 NO0361/NO0500 一致；
4. 全程负向扫描 `input_fullpass_blocked`、mismatch/assert/abort/segfault/fatal/error。

## 4. Runtime gate

只有 50k 功能通过后才执行 performance。按 fixed-ASLR (`setarch -R`)、固定 CPU/NUMA、相同 50k image，采用
baseline/bypass/baseline 串行夹测。运行前检查机器/目标 CPU 负载；若全机负载偏高，必须保留相邻 baseline，不能与历史 raw
time 直接比较。至少采集 cycles、instructions 与 frontend/backend stalls；baseline cycles spread 要求 `<=1%`。

主要判据是 candidate cycles 与 cycles/work 改善且无 PMU 明显回退；若静态收益未转化为 runtime，转向分析 wrapper branch 的
hit/miss 混合与 batch layout，而不是掩盖或默认开启。
