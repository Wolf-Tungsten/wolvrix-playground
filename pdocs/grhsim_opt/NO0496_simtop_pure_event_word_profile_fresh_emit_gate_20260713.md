# NO0496 SimTop pure-event word profile fresh emit gate

日期：2026-07-13

## 1. Preflight and configuration

按 [NO0495](./NO0495_simtop_pure_event_word_profile_fresh_plan_20260713.md) 先执行 editable reinstall。Python extension
加载 site-package 内 2026-07-13 12:04 重建的 `libwolvrix-lib.so`，`ldd` 路径正确，library strings 同时包含 profile
attribute 与 `WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE`。

fresh flow 复用 checkpoint 与 SHA256 `bd420039...` 的 read-args，只开启 direct state read 与 profile，明确关闭 bypass 和
per-supernode runtime profile。日志配置确认 ordered/decoded reg-to-mem、108-op、64-batch target、4 路 emit、
full-active-word consume off 和 `level-id` topo 均与 NO0357 一致。

输出与日志：

```text
build/xs_grhsim_no0495_pure_event_profile_20260713/grhsim/grhsim_emit
build/logs/xs/xs_wolf_grhsim_build_no0495_pure_event_profile_emit_20260713.log
```

## 2. Fresh flow result

```text
read checkpoint        54.868 s
reg-to-mem            170.724 s
activity schedule     157.698 s
C++ emission           77.240 s
reported total        460.532 s
wall clock            464.69  s
peak RSS               27.77 GiB
exit status             0
```

这些时间受当时主机 load 影响，只是完整执行记录，不作为性能数据。

## 3. Schedule and direct-read identity

activity-schedule stats 与 NO0357 精确一致：

```text
graph ops                     7,204,108
compute supernodes               63,241
commit supernodes                    485
total supernodes                 63,726
DAG edges                        528,622
boundary values                1,000,463
boundary activation edges      1,983,923
stats SHA256 e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

direct-state-read 仍为 reads/canonical/aliases=`75,830/40,108/35,722`，removed source heads 与 consumer heads 仍为
`37,672/39,602`。因此 profile 没有改变 graph lowering、schedule 或 direct frontier。

## 4. Production eligibility

production emitter 得到：

```text
eligible pure-event words  107
batches with eligible       22
hit increment sites        107
bypass markers               0
```

这与 [NO0484](./NO0484_active_word_event_mask_audit_gate_20260713.md) generated-source audit 的 107 pure words 精确一致，
证明 GRH purity/event classifier 没有丢覆盖。最大三个 batch 为 35/58/21，eligible 分别 `37/21/8`；其余 19 batches
合计 41。

## 5. Generated-source delta

NO0357 与本轮都有 154 个 `.cpp + .hpp`，文件集合相同：

| Metric | NO0357 | Profile | Delta |
|---|---:|---:|---:|
| bytes | 1,357,263,998 | 1,357,312,756 | +48,758 |
| changed files | - | 25 | 22 sched + header/state/reset |
| byte-identical files | - | 129 | - |
| sched added lines | - | 749 | `107 * 7` |
| sched deleted lines | - | 0 | - |

22 个 changed sched files 与 22 个 eligible batches 一一对应；每个 site 只在 underlying clear 后新增 runtime-enabled
hit/miss block，原 entry/payload/restore 行序列未删除。header/state/reset 只增加 API、arrays、TSV dump 与 init clear。

## 6. Decision

fresh emit/source gate 通过。下一步使用该 154-file model 做标准 Clang O3 archive/emu build；build 成功后先执行短 smoke，
再运行 profile-enabled 10k CoreMark/NEMU difftest并验证 22-row TSV 与 guest endpoint。
