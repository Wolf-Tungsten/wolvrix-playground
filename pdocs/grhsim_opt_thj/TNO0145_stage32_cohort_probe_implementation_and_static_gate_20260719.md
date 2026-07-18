# TNO0145 Stage 32 cohort probe implementation and static gate

日期：2026-07-19

状态：Stage32 的 C++ default-off、no-mutation probe 已实现并通过 production static gate。
current-default SimTop 上找到 `252` 个 exact same-batch activation cohort、`902` 个成员；
投影 BAE 从绝对 `3,619` 降到 `1,450`，可减少 `2,169`。本记录不包含未插桩性能结论，
动态等价性见 [TNO0146](./TNO0146_stage32_cohort_probe_50k_equivalence_gate_20260719.md)。

## 1. 基线与 option ownership

唯一基线仍是仓库当前 C++ 默认生成配置：NO0300、ASLR 关闭、native hybrid 默认开启、
commit cap `8192`，Stage30/31 deferred overlay 默认关闭。新增选项为：

```text
same_batch_activation_cohort_policy = off | probe
same_batch_activation_cohort_profile_path = <supernode fire TSV>
```

默认值直接在 C++ emitter 中为 `off`。native/Python/XS 只稀疏转发显式值；未设置时 XS
日志打印 `cpp-default`，没有在 XiangShan 脚本中另设默认。

## 2. 实现契约

probe 在 final `EmitModel` 与 final `scheduleBatches` 上执行，反向构造每个 active ID 的
真实 `boundaryFanoutByValue` signature。候选必须同时满足：

- ordinary compute-only、pure operation kind、非 event/side effect；
- 无 input/state/direct-state/memory activation；
- source `ValueId` 非空，defining compute SN 的 batch 严格早于 target batch；
- 同一 compute batch、完整 source `ValueId/SN/batch` signature 相同；
- batch order 与 active ID 都连续；
- profile 覆盖全部 `63,241` 个 compute SN，候选成员的 50k fire 绝对相同且非零；
- gap-pack、deferred-forward、pure-event word-pack 与本 probe 不能同时显式启用。

生成代码只在 ordinary batch method 的首个 word/helper 前读入口 bits，在所有 ordinary
word 完成后读出口 bits；body-fire 排除 fullpass 和 commit。probe 不改变 graph、session、
fanout、active ID、batch、seed 或 body guard。

## 3. Review 后的 fail-closed 收紧

独立 review 找到旧实现用 profile 行数 `63,241 + 485` 识别 production、且只检查 pinned
首尾成员的问题。修正后：

- `graph.symbol()=="SimTop"` 无条件触发 production contract，不再用 commit row 数判身份；
- 逐项验证 SN `10999..11049`、active ID `10602..10652`、每 member `108` ops；
- 唯一 source 为 graph 内 `ValueId=1539803:0`、SN6969、batch7；
- 51 个 member 与 source 的 profile fire 都必须是绝对 `19,175`；
- 任一字段不符均 `fail_closed=production_witness_missing production_request=true`。

compute fire profile 来自旧 commit partition，包含 `485` 个仅忽略的 commit row；当前默认
schedule 是 `63,241 compute + 468 commit = 63,709` SN。commit row 不参与 compute-only
probe 的 identity 或候选判断，避免把不同 commit partition 误当成错误。

## 4. Focused gate

最小 fixture 有 `16` 个 SN，source 在 batch0，batch1 中 5 个连续 member 跨 active byte。
它验证：

- implicit default 与 explicit `off` 的全部 artifacts byte-identical；
- probe repeat 的 header/schedule/static row deterministic；
- missing profile、invalid policy 与缺失 production witness fail-closed；
- entry marker 在首 word consumption 前、exit marker 在后；
- generated archive/harness 可编译运行；
- TSV 为绝对 `28` 列，`members=5`、partial/mismatch=`0`、pending=`body_fire`；
- reset 存在，session key 不变。

验证结果：

| gate | result |
| --- | --- |
| focused cohort + existing deferred CTest | `2/2 PASS` |
| native/Python options | `17/17 PASS` |
| XS sparse options | `28/28 PASS` |
| full CTest（收紧 production pin 后） | `48/50 PASS`; full emitter `294.46 s` |
| parent/submodule `git diff --check` | PASS |

两项失败仍是工作树既有的 `transform-comb-lane-pack`（storage frontier packed kAnd）和
`transform-repcut`（static feature export）；Stage32 未触碰对应实现，新 focused/full emitter
均通过，没有新增失败。

## 5. Stale extension 诊断

第一次 production 命令的 XS 层正确打印了显式 probe，但 editable Python extension 是在
core emitter 完成前编译的旧 `.so`。该轮没有任何
`GRHSIM_SAME_BATCH_ACTIVATION_COHORT` marker，生成 stats/CPP 实际仍是 baseline，故明确
判为无效，未进入 O3 或功能结论。

```text
log: build/logs/xs/stage32_same_batch_cohort_probe_stale_extension_emit_20260719.log
sha256: 9e65252e8cfb668be51ee4b2ecfecdab7a0cbd4f25c9ab96ae85a57dc7848028
bytes: 14037
```

重新执行 editable install 后，installed `libwolvrix-lib.so` 可直接找到 production marker，
随后才进行 fresh production emit。此诊断也固定了后续顺序：core emitter 最终改动后必须
重装 binding，不能只依赖 kwargs 单测。

## 6. Production static absolute values

有效 emit 使用 current C++ defaults、p050 checkpoint、`max compute=108`、batch target
`64`、parallelism `4`，只显式开启本 probe/profile。activity/emitter stats 与 Stage23
current-default baseline 均 `cmp=0`：

| artifact | SHA256 | bytes |
| --- | --- | ---: |
| emit raw log | `9e5afbe20db7285a32459251165d9e1bbfd7c317f64abd9e5daefb840f3413e0` | `122230` |
| `activity_schedule_supernode_stats.json` | `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` | `5382` |
| `grhsim_emit_stats.json` | `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b` | `418` |

scan 的全部绝对值：

```text
compute_supernodes=63241
pure_boundary_only=14814
signature_runs=252
selected_cohorts=252
selected_members=902
selected_ops=88334
control_bae=3619
projected_bae=1450
bae_saved=2169
control_entries=342
projected_entries=252
control_chunks=257
projected_chunks=252
```

reject 绝对值为 `impure=306`、`input=2354`、`state=41152`、`memory=2050`、
`event=801`、`empty_source=12`、`source_order=1752`；`commit/source_owner/profile/
noncontiguous` 均为 `0`。

pinned row 是 cohort11：

```text
batch=12 source_value=1539803 source=6969 source_batch=7
SN=10999..11049 active=10602..10652 members=51 ops=5508
profile_fire=19175 control_bae=51 projected_bae=1
control_entries=7 projected_entries=1 control_chunks=3 projected_chunks=1
```

## 7. Probe code-size boundary

probe 会插桩，源码/`.text` 增长只用于解释 build 成本，不能当性能 candidate：

| field | current default | probe | absolute delta |
| --- | ---: | ---: | ---: |
| CPP files | `132` | `132` | `0` |
| CPP bytes | `1,356,097,029` | `1,369,226,177` | `+13,129,148` |
| header bytes | `437,257` | `438,673` | `+1,416` |
| emu `.text` | `93,495,071` | `96,035,456` | `+2,540,385` |

结论：static gate 通过但默认仍为 C++ `off`。只有动态 probe 全等后才能另立 strict；strict
必须无 runtime counters，并由 SimTop 50k `Host time spent` 裁决。
