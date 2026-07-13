# NO0516 SimTop sparse pure-event fresh source plan

日期：2026-07-13

## 1. Scope

承接 [NO0515](./NO0515_sparse_batch_pure_event_predicate_implementation_gate_20260713.md)，从 NO0495/NO0501 使用的
同一 pre-reg-to-mem checkpoint 与 read-args fresh 生成 production candidate。只开启 direct-state-read 与 pure-event bypass：

```text
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=1
WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE=0
GRHSIM_EMIT_RUNTIME_PROFILE=0
```

输入与输出：

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
read args:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
  SHA256 bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
output:
  build/xs_grhsim_no0516_sparse_pure_event_20260713/grhsim/grhsim_emit
```

ordered/decoded reg-to-mem、108-op compute、4096-op commit、2048-op/8192-line batch limits、64-batch target、4 路
emit、full-active-word consume off 与 `level-id` topo 均保持 NO0357/NO0501 配置。

## 2. Preflight

所有命令先 `source env.sh`。fresh emit 前重新 editable-install 当前 `wolvrix` 子仓库，并确认 Python 实际加载的
`libwolvrix-lib.so` 包含 sparse volatile 生成文本。记录 checkpoint/read-args SHA、当前子仓库提交和主机 load；emit/build 用时只作
执行记录，不作为 runtime 性能数据。

## 3. Source gates

- schedule stats SHA 必须仍为 NO0357/NO0501 的 `e3056375...`；
- direct-state-read 必须仍为 reads/canonical/aliases=`75,830/40,108/35,722`；
- total bypass markers 仍为 `107`，且分布在相同 `22` 个 batches；
- 按 production batch eligibility count 推导，`14` 个 sparse batches 的 `20` 个 wrappers 必须使用 volatile hit；
- 其余 `87` 个 wrappers 必须保留 direct exact-event outer predicate；
- sparse batch 集合应为 `12,16,18,20,22,24,25,27,37,50,51,56,57,61`，该列表只用于外部验收，不进入 emitter；
- 相对 NO0501 plain candidate，只允许上述 `14` 个 sched files 改变；header/state/eval/init 与另外 8 个 eligible sched files
  必须 byte-identical；
- profile getter/arrays/increments/TSV dump 必须为零，原 entry/payload/restore 行序不变。

## 4. Follow-up gates

source gate 通过后，以标准 Clang O3/difftest 入口构建独立 emu，并和 NO0357 baseline、NO0501 plain candidate 比较 full binary
与 22 个 changed objects。预期 fresh object 方向与 NO0513 的 generated-copy probe 一致，但必须以 fresh build 实测为准。

随后依次执行 100/10k/50k 功能门禁，checkpoint 与终点对齐 NO0504-NO0506，并负向扫描
`input_fullpass_blocked`、mismatch/assert/abort/segfault/fatal/error。runtime PMU 仍执行 fixed-ASLR 相邻 A/B/A；若主机负载不满足
NO0507 的 sibling-idle gate，则继续保留零样本，不引用历史 raw time。
