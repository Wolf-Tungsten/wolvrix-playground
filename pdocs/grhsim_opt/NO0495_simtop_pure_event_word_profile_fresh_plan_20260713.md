# NO0495 SimTop pure-event word profile fresh plan

日期：2026-07-13

## 1. Scope

承接 [NO0494](./NO0494_pure_event_compute_word_dynamic_profile_gate_20260713.md)，从 NO0300/NO0357 相同的
pre-reg-to-mem checkpoint fresh 执行 reg-to-mem、activity-schedule 和 C++ emission。保持 NO0357 direct-state-read 生产
配置，只新增 profile，不开启 bypass：

```text
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=0
```

输入与输出：

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
read args:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
  SHA256 bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
output:
  build/xs_grhsim_no0495_pure_event_profile_20260713/grhsim/grhsim_emit
```

108-op compute supernode、4096-op commit、2048-op/8192-line batch limits、64 batch target、4 路 emit、ordered/decoded
reg-to-mem 与 `level-id` final topo 均保持不变。

## 2. Preflight

所有命令先 `source env.sh`。fresh emit 前执行 editable reinstall，并检查 site-package `libwolvrix-lib.so` 同时包含：

```text
pure_event_compute_word_profile
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE
```

当前主机为 384 个逻辑 CPU、约 832 GiB available memory，load average `108.45/103.16/101.29`，无其他 C++ compiler
进程。本阶段不是 runtime 性能测试，可以执行 emit/build；后续 runtime 若机器负载高，必须相邻复跑原 baseline，不使用本阶段 raw
host time 作性能结论。

## 3. Fresh emit gates

- graph ops、compute/commit supernodes、DAG、boundary 与 NO0357 schedule stats 精确一致；
- direct-state-read 仍命中 `75,830 = 40,108 + 35,722`；
- generated source 不含 bypass marker，含 profile arrays/increments/getter/TSV dump；
- `kPureEventComputeWordEligibleCount` 非零；
- 按 batch 汇总 eligible words，并与 NO0484 source audit 的 107 pure words 对照；差异必须落入生产 purity、split helper、
  full-word consume 或 final materialization gate，不能直接视为 bug 或覆盖率损失；
- profile-only generated C++ 相对 fresh no-profile 只增加诊断字段/插桩，不改变 schedule 或原 payload source sequence。

## 4. Build and function gates

emit 通过后用标准 XiangShan difftest GrhSIM O3 入口构建独立 emu。先跑短 smoke，再以
`EMU_RUNTIME_PROFILE=1` 执行 10k CoreMark/NEMU difftest：

- guest endpoint 与 NO0300/NO0357 相同；
- 无 assertion、abort、difftest mismatch 或 `input_fullpass_blocked`；
- TSV 行数、static eligible 与日志总计闭合，所有行 `active_total = hit + miss`；
- 根据 10k miss ratio 决定是否再跑 50k profile，不把插桩 host time 当性能数据。

只有 profile 分布证明大量 active misses 且集中在已有 hot batches，才进入 bypass fresh build 与 fixed-ASLR A/B/A。
