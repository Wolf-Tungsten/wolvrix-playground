# TNO0113 Stage 19 table activation runtime probe plan

记录日期：2026-07-17

状态：计划。Stage 16 的 table zero-hole 统计只说明静态 lowering opportunity，不能说明这些 table loop 在 SimTop 50k 中实际执行了多少次。Stage 19 先增加仅在显式 runtime-profile emit 中编译的动态计数，不改变默认生成程序；只有计数证明 table path 足够热，才另立 table encoding candidate。

## 1. 已知基线与问题

当前 baseline 是仓库默认生成配置：NO0300、ASLR 关闭、C++ native hybrid default、commit cap `4096`。Stage 16 在同一 schedule 上得到：

```text
table groups                  586
merged table entries       89,903
current per-entry writes   89,903
contiguous chunk proxy      19,942
zero-hole chunk proxy       17,530
gap-only static delta        2,412 (-12.095076%)
```

这些是 emit-time 静态计数。table lowering 当前是 `kActivationMasks[]` 加逐 entry loop；一个 group 可能位于条件分支、reset/initial 或其它低频路径，不能把 `2,412` 静态 writes 直接乘成端到端收益。direct-only Stage 17 已完成并判定 walltime 中性，因此 table 需要独立、可归因的动态证据。

## 2. 探针边界

探针只在以下组合中启用：

```text
active_mask_gap_pack_policy = probe
emit_runtime_profile        = true
```

默认 `off`、显式 `off`、普通 `probe`（未请求 runtime profile）均不得改变现有 generated C++。计数器不进入正常 `PerfCounters`，避免污染正式 walltime。计数只覆盖 `probeSite=generic` 的 table activation block；memory-row、deferred、seed/initial、commit-range 和 unclassified owner 继续排除并单独保持既有分类。

每次实际进入 table block 时累计：

```text
table_block_evaluations
current_entry_writes       += merged entry count
contiguous_chunk_writes    += baseline contiguous chunk count
zero_hole_chunk_writes     += validated DP candidate chunk count
```

计数器应在 table loop 内、条件已经成立之后递增，因此 `evaluations` 是动态 block executions/hits，不是 condition evaluations 或静态 groups。计数器用 `uint64_t`，在 `init()` 清零；`set_runtime_profile_enabled(true)` 必须在统计窗口首次 eval 前开启。现有 emu 在 `init/eval` 前开启，并在结束时调用一次 `dump_runtime_profile()`，向 raw log 输出唯一 summary 行；不追加到既有 supernode TSV，以免破坏其三列 schema。

## 3. 生成与运行协议

1. 用 `source env.sh` 后从相同 post-stats checkpoint fresh emit `off+emit_runtime_profile` 与 `probe+emit_runtime_profile` 两套产物；另以普通 default/off/probe 保持 byte identity。记录 manifest、activity-schedule JSON、emitter JSON 和 policy source。
2. 两套 profile 产物只允许新增 Stage 19 counter/increment/reset/dump；不得改变 schedule、active-ID、batch、slot 或原 table loop。`probe` 仍只报告 planner，不发 candidate。
3. 先用固定 ASLR 关闭的 100/10k 功能 gate，确认 raw log 中 summary 唯一、每个 counter 非负，并从生成 source 的 `586` 个 generic table site 重算静态常量和。另有 memory-row/seed 等 excluded table，不得计入动态 headline。
4. 运行 SimTop 50k profile binary，只把动态计数用于 hotness/机会量，不把插桩 binary 的 walltime 与未插桩 binary 直接比较。计数不受 page-cache/NUMA 性能噪声影响，因此 profile 运行可只记录固定 ASLR、绑核/绑内存和功能结果；它不冒充通过 whole-node 性能 admission 的样本。
5. 若动态计数显示 table path 足够热，再另立 strict table encoding 阶段：生成未插桩 candidate/control，做 O3/source/functional gate，并按 `Host time spent` 的 ABBA+BAAB walltime 裁决。若不热，记录停止，不实现 table candidate。

## 4. 硬门禁与判据

- profile build 必须通过 focused emitter/runtime-profile tests；default/off 产物保持 byte identity。
- table counter 必须只在真实 table block 执行时累加，不能由静态 emit 循环或 profile dump 伪造。
- production profile 源码中 generic 插点数和静态常量和必须精确重算为 `586`、`89,903`、`19,942`、`17,530`；运行期必须满足 `current_entry_writes >= contiguous_chunk_writes >= zero_hole_chunk_writes`。
- profile 运行不得用于性能优劣结论；插桩开销只用于动态计数采集。
- 后续 candidate/control 的最终端到端判据统一为 SimTop 50k `Host time spent`（ms），每个样本必须恰有一个正值；cycles、instructions、BAE、DAG、静态 write proxy 仅作诊断或机会量。
- 双 NUMA 重测必须使用独立 `/dev/shm` inode、`taskset`+`numactl --physcpubind/--membind`、`setarch x86_64 -R` 和 whole-node pre/runtime idle gate；任一 gate 失败不启动正式 run。

## 5. 预期输出

本阶段应形成一份独立 runtime 记录，至少包含：生成配置与 SHA、`586` 个静态 generic table sites、静态常量和、动态 evaluations/current/contiguous/gap writes 绝对值、profile 路径、100/10k/50k 功能结果，以及是否进入 strict table candidate 的决定。profile 的 walltime 只按原值归档、不做 A/B；下一阶段若没有有效安静窗口，只记录 survey rejection，不用 cycles 或相对百分比替代 walltime。
