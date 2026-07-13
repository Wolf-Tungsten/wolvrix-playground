# NO0309 NO0286 / NO0300 dynamic-work comparison plan

日期：2026-07-12

## 1. 背景

[NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) 已确认，NO0300 相对
NO0286 的 CoreMark 50k host instructions 下降 `8.45%`，但 IPC 下降 `11.84%`，最终 host cycles
回退 `3.85%`。[NO0303](./NO0303_ordered_memory_write_affine_post_profile_20260712.md) 随后定位到剩余
sample 增量主要在被全局重排的 compute batches，而 RAT affine loop 本体已不是热点。NO0304--NO0308
尝试稳定最终拓扑和复现 GSim ready-stack，均未能稳定 strict/ordered 两版的 batch overlap。

继续修改排序前，需要先区分两个根本不同的解释：

1. ordered-write 图在同一 guest workload 下触发了更多 supernode 或执行了更多动态算子工作；
2. ordered-write 的动态工作没有增加，甚至下降，但生成代码布局、分支、cache 或单次 fire 成本变差。

## 2. A/B 口径

两版均从同一 checkpoint 恢复：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

共同配置：

```text
GRHSIM_EMIT_RUNTIME_PROFILE=1
WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY=level-id
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=64
WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM=4
```

严格 NO0286 形态必须同时设置：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_DECODED_WRITE_STORAGE=0
WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES=0
```

NO0300 形态设置：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_DECODED_WRITE_STORAGE=1
WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES=1
```

独立输出目录：

```text
build/xs_grhsim_no0309_no0286_rtprof_20260712
build/xs_grhsim_no0309_no0300_rtprof_20260712
```

## 3. 运行口径

两套 profile-enabled emu 都使用 CoreMark 两迭代镜像、NEMU difftest 和 `50,000` cycle limit：

```text
EMU_RUNTIME_PROFILE=1
XS_SIM_MAX_CYCLE=50000
XS_WAVEFORM=0
XS_WAVEFORM_FULL=0
XS_COMMIT_TRACE=0
```

必须核对两版均到达 `guest cycles=50001`、`cycleCnt=49996`、`instrCnt=73580` 和相同 terminal PC，
否则动态计数不可比较。运行前记录 load average；profile run 的 host time 仅用于发现异常，不替代 NO0302 的
无插桩固定 CPU 性能结论。

## 4. 比较指标

将每版 emit 期 `grhsim_supernode_static.tsv` 与运行期 `grhsim_supernode_fire.tsv` 按
`(supernode_id, phase)` 严格一一连接，至少汇总：

- compute / commit / total fire；
- `f * n_comp`、`f * n_src`、`f * n_sink`、`f * n_const`；
- `work_total = f * (n_comp + n_src + n_sink + n_const)`；
- `a_succ_work = f * a_succ`；
- 各 phase 的非零 supernode 数、top-by-fire 和 top-by-work。

由于两版图结构不同，不把相同数值的 supernode ID 当作跨版本身份。跨版本先比较聚合动态规模，再结合
generated C++ 和已有 NO0303 fixed-period profile 归因热点 batch。

## 5. 判定

- 若 NO0300 的动态 work 增量与 `3.85%` cycles 回退同方向且量级足够，下一步定位额外 fire 的触发来源；
- 若 NO0300 的动态 work 下降或基本不变，则停止把回退归因于 activation 数量，转向单位 work 成本，重点检查
  compute batch 的 branch/instruction mix、代码布局和 cache/backend 行为；
- 无论结果如何，runtime-profile 插桩版不直接用于决定默认性能开关。

