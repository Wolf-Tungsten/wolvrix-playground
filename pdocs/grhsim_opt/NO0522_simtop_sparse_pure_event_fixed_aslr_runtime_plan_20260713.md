# NO0522 SimTop sparse pure-event fixed-ASLR runtime plan

日期：2026-07-13

## 1. Inputs and purpose

[NO0521](./NO0521_simtop_sparse_pure_event_50k_functional_gate_20260713.md) 已确认 hybrid 的 50k 功能轨迹正确；
[NO0518](./NO0518_simtop_sparse_pure_event_build_codegen_gate_20260713.md) 确认其静态 codegen 相对 baseline 与 plain 均下降。
本轮验证 107 个 pure-event word wrappers 的动态 miss bypass 能否转化为真实 host cycles 收益。

```text
baseline:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim-compile/emu
  cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4
hybrid:
  build/xs_grhsim_no0516_sparse_pure_event_20260713/grhsim/grhsim-compile/emu
  eed8e6157dd113e11a5bee81b3101d9d4d01101937cef2b2fe582bb828e2b132
```

## 2. Controlled sequence

复用 [NO0507](./NO0507_simtop_pure_event_word_bypass_fixed_aslr_runtime_plan_20260713.md) 的固定口径：

- `setarch -R` 固定 PIE load base，`numactl --membind=1`，固定 NUMA1 primary CPU；
- seed 0、相同 image/NEMU、`-b 0 -e 0 -C 50000`；
- profile/TSV unset，progress off；
- events 为 cycles、instructions、frontend empty、frontend cmask6、backend stalls；
- 先做 candidate 100-cycle PMU preflight，再串行 baseline/hybrid/baseline；
- 每轮前 primary 与 SMT sibling 三秒平均 idle 都须 `>=99%`，两次 baseline cycles spread 须 `<=1%`。

fresh survey 可以在任何正式样本前重选 CPU；一旦 preflight 启动则锁定 CPU，不在组内换核。全机 load 只作辅助，不能替代
目标 sibling gate。

## 3. Functional and PMU validity

三轮都必须达到 guest/cycleCnt/instr/terminal PC=`50,001/49,996/73,580/0x80001312`，负向扫描为 0；五项 PMU
必须全部 `100.00%` 调度。fixed-ASLR 下两次 baseline 及 hybrid 的 difftest state pointer 应一致。

主比较以两次 baseline 均值计算 hybrid 的 cycles、instructions、IPC 和 stall density。只有该 A/B/A 有效后，才考虑在同一 quiet
窗口追加 NO0501 plain 对照；不先执行四轮长序列，以免扩大共享机漂移窗口。

## 4. Stop rule

若 fresh survey 或三次独立 quiet gate 未达到 `>=99%`，不启动 perf/emu、不放宽门限，也不把 NO0521 raw time 作为性能样本。
等待期间继续分析 GSIM/GrhSIM codegen 与动态 work，不重复无效 runtime。产物放在 `build/logs/xs_perf/no0522/`。
