# TNO0086 Stage 13 canonical commit order full gate

记录日期：2026-07-16

状态：Stage 13 第二层 canonical commit locality group topo-order 已实现并完成防御修复、focused tests、四档 production full emit、typed-slot strict gate、O3/link 与 100/10k 功能门禁。cap4096 对 current-default same-post control 的 154 个源文件 byte-identical；cap8192/16384/32768 的 typed ValueId mapping 相对 4096 均为 changed/missing/extra/type-changed `0`。正确 page-local NUMA 50k 正在执行，本记录不下性能结论，默认仍为 `4096`。

## 1. 第二层 canonical order

[TNO0084](./TNO0084_stage13_anchor_only_production_gate_and_order_correction_20260716.md) 已固定 canonical 4096 locality group 的 state anchor，但 commit-only Value 的 `firstReadSequence` 仍跟随 actual high-cap merged topo，留下 `12k..15k` 个 slot 漂移。本轮新增 `commit_locality_group_order`，在 `level-id` 下构造伪 baseline DAG：

1. compute supernode 部分保留 final schedule 的 compute-to-compute DAG；
2. 每个 canonical 4096 locality group 建成一个独立 pseudo commit node；
3. 从组内每个 sink operand 的 defining compute supernode 重建 compute-to-group edge；
4. 复用现有 `level-id` topo helper，导出 dense group permutation；
5. actual high-cap supernode partition、执行 topo 和 commit op vector 均保持不变。

Emitter 先按 actual schedule 扫描 compute reads 一次，再按 canonical group topo 和组内 baseline op order 扫描 commit reads一次。这样 value-order key 中的 `stateAnchor`、`firstReadSequence` 和 `totalReads` 均不再依赖 high-cap merged commit topo；没有重复累计 commit read。

Metadata 使用整图 gate：map 必须覆盖全部 graph op，compute op 必须为 invalid group，全部 commit op 必须且只能出现一次，group ID 必须 dense，order 必须是 group 的完整 permutation。任一条件不满足时整张图回退 legacy actual-schedule value order，不做半表混用。非 `level-id` 目前导出空 canonical order，也由同一 gate 明确回退。

## 2. groupCount 防御与 focused tests

独立 review 发现 emitter 首版会在检查 `groupCount > commitOpCount` 前按 metadata 最大 group ID 分配 vector。损坏 metadata 若包含接近 `UINT32_MAX` 的 group，可能先触发超大分配而不是安全 fallback。

修复后先在 `uint64_t` 中计算 `maxGroup + 1`，并在任何 group-sized vector 分配前要求：

```text
candidate group count <= commit op count
candidate group count <= size_t max
```

随后才分配 dense/permutation、state-anchor 和 grouped-op vectors。Emitter fixture 新增 group=`UINT32_MAX-1` 的畸形 metadata，要求不发生 `bad_alloc`、完整回退 legacy order，并与 metadata erase/malformed map/malformed order 的生成源码和 slot mapping 一致。

Focused 覆盖还包括 default native/fallback 全源码 identity、split 与 merged+canonical slot identity、high-cap group map/order identity、default canonical order 与 commit topo 一致。最终结果：

```text
emit-grhsim-cpp              PASS 295.03 sec
transform-activity-schedule  PASS   0.15 sec
git diff --check             PASS
```

## 3. Production full emit 与结构 identity

四档均从相同 post-reg checkpoint 恢复：

```text
post-stats SHA256  165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
DP penalty          1000000 PPM
final topo          level-id
optional schedule/emitter experiments off
commit cap          4096 / 8192 / 16384 / 32768
```

四份 Stage 13 stats 与 Stage 12 对应 cap 的 JSON 均 `cmp=0`：

| cap | total/commit SN | DAG | total BAE | compute/commit pairs | stats SHA256 |
| ---: | ---: | ---: | ---: | ---: | --- |
| `4096` | `63726 / 485` | `528622` | `1983923` | `1721698 / 262225` | `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77` |
| `8192` | `63709 / 468` | `527990` | `1983326` | `1721698 / 261628` | `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` |
| `16384` | `63700 / 459` | `527331` | `1981862` | `1721698 / 260164` | `70bb3f488b608e028191ab3c2f04233d163e3f2c39c67e4e92413851d551c5cf` |
| `32768` | `63696 / 455` | `526921` | `1981680` | `1721698 / 259982` | `d75ee7b61c3001e321855983a5dbb2345328aa38078f2f7fd66f2451a696baa1` |

四档 compute SN 均为 `63241`，boundary values 均为 `1000463`。因此本轮只稳定 emitter locality metadata/order，没有改变 Stage 12 已验证的 schedule partition、BAE 或 DAG。

cap4096 full emit 与 Stage 10 same-post current-default control 的文件集合均为 154 个 `.cpp/.hpp`，逐文件内容 byte-identical，identity diff 为空。这闭合了新增 metadata 在仓库默认 NO0300 下不改变生成源码的硬门槛。

## 4. Typed-slot strict gate

从四档 full generated C++ 提取 `(ValueId, typed slot family, slot index)`：

| cap | raw rows | unique ValueId | duplicate rows | forward conflict | changed | missing | extra | type changed |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4096` | `1,000,264` | `1,000,032` | `232` | `0` | `0` | `0` | `0` | `0` |
| `8192` | `1,000,264` | `1,000,032` | `232` | `0` | `0` | `0` | `0` | `0` |
| `16384` | `1,000,264` | `1,000,032` | `232` | `0` | `0` | `0` | `0` | `0` |
| `32768` | `1,000,264` | `1,000,032` | `232` | `0` | `0` | `0` | `0` | `0` |

raw 行顺序会随实际 high-cap commit partition 改变，但同一 ValueId 的重复记录没有冲突；三档 high-cap 的 sorted unique TSV 与 cap4096 均 `cmp=0`。TNO0083 设定的 `changed=0` partition-stable slot 目标至此严格闭合，不再用“漂移大幅下降”替代完成。

## 5. O3 与功能门禁

cap8192/16384/32768 均完成 fresh O3/archive/link。cap4096 因 154 个生成源文件与 same-post control byte-identical，复用该 control 的既有 O3 ELF：

| cap | ELF bytes | GNU size text | ELF `.text` bytes | emu SHA256 |
| ---: | ---: | ---: | ---: | --- |
| `4096` | `94,768,184` | `94,592,303` | `88,186,297` | `453b5dad1b332facbfe1bc229256b08a88a3b304f4a4f60b7a124a843f639976` |
| `8192` | `94,745,048` | `94,571,569` | `88,171,851` | `b88f3355e4a4ad3d94ce544f17b6ba8a26c2df8ea621fc7994da1cdd599b964e` |
| `16384` | `94,738,960` | `94,566,565` | `88,173,215` | `a6d400e84a280849ded83badf06d4be9498cc84f11209fb9c20aa994ec371469` |
| `32768` | `94,733,632` | `94,561,327` | `88,173,665` | `a0303b1d70bf1912eb1639d4926a89e923bde978c99a769794188ea52a8a3cd5` |

三个 high-cap ELF 的 file size 与 GNU text 均小于 4096；静态大小只作为 build 完整性与后续归因输入，不预判 cycles。

三个 high-cap fresh ELF 均完成 CoreMark + NEMU diff 的 100/10k；cap4096 使用 byte-identical control 的既有同门禁结果：

| Gate | guest cycles | cycleCnt | instrCnt | PC | result |
| --- | ---: | ---: | ---: | --- | --- |
| `100` | `101` | `96` | `0` | `0x0` | 四档 PASS |
| `10k` | `10001` | `9996` | `458` | `0x800027c6` | 四档 PASS |

所有 fresh high-cap 进程退出码为 0，没有 diff mismatch、assert、fatal 或异常终点。

## 6. Runtime 状态

四档已进入 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 定义的 correct page-local NUMA runtime：per-node `/dev/shm` 独立 inode、镜像核、全 CCD quiet gate、fixed ASLR 和逐样本 `numa_maps` placement audit。该矩阵仍在进行；本记录不引用 partial wall/perf 样本，也不据未完成序列修改默认。

当前决定保持：

- current-default NO0300 继续使用 commit cap `4096`；
- `8192/16384/32768` 仅作为显式实验档；
- 最终性能只认完成后的 page-local SimTop 50k 包夹和五项 PMU。

## 7. 产物

```text
build/xs_activity_stage13b_partition_stable_order_commit_guard_merge_cap{4096,8192,16384,32768}_full_20260716/
build/logs/xs/xs_wolf_grhsim_build_activity_stage13b_partition_stable_order_commit_guard_merge_cap{4096,8192,16384,32768}_full_20260716_emit.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage13b_partition_stable_order_commit_guard_merge_cap{8192,16384,32768}_o3_20260716.log
build/logs/xs/stage13b_slot_gate_20260716/
build/logs/xs/stage13b_default_source_identity.diff
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage13_functional/
```
