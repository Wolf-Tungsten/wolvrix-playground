# TNO0115 Stage 20 table encoding candidate plan

记录日期：2026-07-17

状态：计划。TNO0114 的动态 profile 证明 generic table block 在 50k 中持续命中，进入未插桩 table encoding candidate。为避免把两种 representation 变化混在一起，本阶段拆成两个显式 emitter policy：先比较 current per-entry table loop 与 contiguous chunk control，再比较 contiguous 与 zero-hole chunk candidate。C++ native default 继续 `off`。

## 1. 冻结对象与 policy

基线仍是当前仓库默认 NO0300、ASLR 关闭、native hybrid、commit cap4096。以下对象必须 byte/结构保持不变：

```text
GRH / activity schedule / supernode partition / DAG
active-ID assignment / schedule batch order
typed value slots / state layout / non-table activation lowering
```

新增仅供实验的 `active_mask_gap_pack_policy` 值：

```text
off                       current per-entry table loop (native default)
probe                     no-mutation static probe
targeted-direct           已完成的 non-table direct candidate
targeted-table-contiguous table groups -> baseline contiguous 8/4/2/1 chunks
targeted-table-gap        table groups -> validated zero-hole DP chunks
```

`targeted-table-contiguous` 和 `targeted-table-gap` 都只作用于 `probeSite=generic` 且 `entries.size() >= 32` 的 table group；memory-row、deferred、seed/initial、commit-range 与 unclassified 路径冻结。候选失败或 validator 不通过时整次 emit 失败，不静默混用表示。

## 2. 语义与结构 gate

对每个 table group，candidate chunk 展开后的每个 active byte 必须与原 `kActivationMasks[]` entry map 完全相同。contiguous control 使用已有 `buildActiveMaskChunks`；gap candidate 使用 TNO0100 的 DP planner/validator，允许零洞但不跨 logical 64-byte lane。candidate 不得改变：

```text
table threshold (31/32)
condition wrapper / event expression
active mask OR semantics
source function/batch membership outside table statements
```

emit 后要求：

- default/off/普通 probe 继续 byte-exact；
- activity JSON、topo、active-ID、batch、slot JSON 与 default exact；
- table candidate 只在预期 table statement 区域有 diff；
- generated source 的 table constants、chunk count 与 emitter summary 可重算；
- no candidate path 修改 session state。

## 3. 编译、功能与性能协议

每个 policy 都做 fresh O3 archive/emu link，以及固定 ASLR 100/10k/50k 功能 gate。随后 candidate/control 使用独立 `/dev/shm` inode，`setarch x86_64 -R`、`numactl --physcpubind/--membind`、镜像核和整节点 pre/runtime idle hard gate，按 ABBA 与 BAAB 各四样本运行。每个样本必须：

```text
exactly one positive Host time spent: <ms>
functional signature: instrCnt=73580, cycleCnt=49996, guest=50001
no migration/affinity/page-placement violation
```

最终 headline 只用未插桩 SimTop 50k `Host time spent` walltime；cycles/instructions、BAE/DAG、静态 chunk/write 数仅作诊断。任一 NUMA survey/runtime gate 失败就记录绝对 idle 数值并不启动该组，不降低门槛，也不拼接旧样本。

## 4. 采用规则

先以 contiguous candidate 的 source/`.text`/功能和 walltime 判断 table loop rewrite 是否值得；只有它没有明显 wall regression，才比较 gap candidate。轻微结构退化不单独否决，但明显 walltime 回退或 source/ELF 灾难性膨胀则停止。无有效双 NUMA 窗口时只归档静态/功能结果，保持 default `off`，不得以 profile binary walltime 或 cycles 代替 headline。
