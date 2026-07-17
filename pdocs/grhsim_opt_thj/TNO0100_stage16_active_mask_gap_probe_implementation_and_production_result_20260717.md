# TNO0100 Stage 16 active-mask gap-pack probe implementation and production result

记录日期：2026-07-17

状态：default-off/no-mutation probe 的实现、focused/plumbing tests、两轮独立 review 与 production scan 已完成。current native-hybrid/cap4096 下，non-table global active-mask 的等价 zero-hole plan 将 write/chunk proxy 从 `653,299` 降至 `623,294`，减少 `30,005`（`-4.592843%`）；table entry 的 zero-hole plan 相对同一 entry map 的 contiguous chunk control 从 `19,942` 降至 `17,530`，减少 `2,412`（`-12.095076%`）。default、explicit-off、probe 三套 fresh emit 的全部 `157` 个文件和 `155` 个 generated source 文件分别 byte-exact，且 source 与 Stage 14 current native-hybrid baseline 相同；validator、自测和 production invalid breakdown 全部通过。probe 不发 candidate，所以本阶段不重复构建相同 O3/ELF 或运行无差异的 SimTop 50k；下一阶段只先实现 non-table direct targeted encoding，table 在取得 category runtime counter 前不修改。

## 1. 实现范围与唯一默认源

本轮实现 [TNO0097](./TNO0097_stage16_emitter_local_zero_hole_active_mask_pack_probe_plan_20260717.md) 的 `off/probe` 阶段，不实现 `targeted`，也不修改 graph、activity schedule 或 generated activation statement。C++ emitter 的唯一默认值为：

```text
activeMaskGapPackPolicy = off
```

低层解析优先级为：

```text
emitter attribute
  > WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY
  > C++ native default off
```

Python `Session.emit_grhsim_cpp(..., active_mask_gap_pack_policy=None)` 不写 attribute；显式 `off/probe` 才透传，非法类型和值在入口拒绝。native positional argument 追加在既有参数末尾，保持旧 positional 调用兼容，并允许显式 `None`。

XS 只把 `WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY` 作为 sparse attribute override。高层变量未设置时不注入 `off`，也不写回低层环境；日志区分三种来源：

| 配置状态 | effective | source |
| --- | --- | --- |
| 高层、低层均未设置 | `cpp-default` | `cpp-default` |
| 仅设置低层环境 | 低层原值 | `cpp-low-env` |
| 设置 XS 高层环境 | 高层原值 | `xs-override` |

若高、低层同时存在，高层通过 attribute 覆盖低层，仍符合 C++ 的统一优先级。XS 只观察低层值用于日志，不把它复制进 attribute，也不改写进程环境。因此默认仍只存在于 C++，不会重新形成按 XS 特判的第二套默认。

## 2. Planner、validator 与 no-mutation 契约

probe 复用 production lowering 的 local/global split 与 byte-entry merge：local target 先移出，global active ID 再按 `activeId/8` 合并，相同 byte 的 bit OR 成唯一 nonzero entry。baseline direct/table 判定保持现有 `32`-entry threshold；probe 的 candidate write 数不能反向改变该分支，也不能合并不同 condition。

对每个已排序 entry list，suffix DP 只尝试 `8/4/2/1` 四种宽度，复杂度为 `O(4n)`，且每个 chunk 必须从当前首个尚未覆盖的 real entry 精确起步。cost 依次为：

1. write/chunk 数最少；
2. 同 write 数下 zero-hole byte 最少；
3. 再按 width histogram、当前 width、next entry 与 mask 稳定打破平局。

允许 chunk 在真实 entry 之间或最后一个真实 entry 后补零，但不得越过 active byte array bounds。只有实际含 hole 的 chunk 才受 logical `index/64` lane no-cross 限制；无洞连续 chunk 保持原 lowering 的跨 logical lane 能力。这里的 logical lane 仍不是实际 cache-line 证明，因为 active array 当前没有据此确认的 `alignas(64)`。

独立 validator 不信任 planner 的合法性判断，逐 chunk/byte 检查：

- width 必须属于 `1/2/4/8`，并满足 array bounds；
- chunk 不 overlap，且锚定当前首个未覆盖 real entry；
- mask 高位、每个 real mask、hole 的零值均精确；
- 不得 missing、extra 或 mask mismatch；
- 含 hole chunk 不得跨 logical lane；
- plan 的 write、hole 与 width histogram metadata 必须可重算。

若 validator 失败，candidate 不进入 saved/gap-saved 统计；`candidate_worse` 也作为独立失败类别。probe 构造时还执行一组 validator self-test，覆盖 plan-invalid、非法 width、bounds、overlap、leading-hole/anchor、mask high bits、missing、extra、mask mismatch、cross-lane、metadata 和全部四种合法 width。

`off` 路径不构造 probe scratch。`probe` 只在 emitter 内观察已经形成的 entry/chunk，并继续发原 baseline 内容；统计聚合由 mutex 保护，serial/parallel normalized log 一致。它不写 session state，不改变 schedule、topo、active ID、batch、typed value slot、source file/function membership 或生成源码。

## 3. Focused、plumbing 与独立 review

已完成的定向门禁为：

| gate | 结果 | 主要覆盖 |
| --- | --- | --- |
| `cmake --build wolvrix/build --target emit-grhsim-cpp -j2` | PASS | emitter 与新增 fixture 编译 |
| `WOLVRIX_TEST_ACTIVE_MASK_GAP_PACK=1 wolvrix/build/bin/emit-grhsim-cpp` | PASS | default/off/probe artifact identity、serial/parallel determinism、planner/validator 正反例、table threshold/conditional、分类和非法 policy |
| Python/pybind unittests | `7/7 PASS` | `None` 省略、off/probe 验证、native keyword/explicit None、旧 positional 兼容 |
| XS option unittests | `9/9 PASS` | sparse default、low-env observation、high-env override、source 日志与环境不写回 |
| `py_compile`、editable incremental build、定向 `git diff --check` | PASS | binding/脚本语法与补丁格式 |

两轮独立 static review 中，首轮要求补齐 coverage owner 与 chunk anchor/validator 约束；修正后复审未发现 blocker，并确认 failure 映射、自测反例、`8/4/2/1` histogram、seed/commit-range/unclassified 断言和 thread-safe aggregation 正确。

当前唯一非阻塞测试覆盖缺口是 deferred 与 memory-row 没有各自的专门 synthetic fixture。production 中 deferred direct、deferred aggregate 与 memory-row 三类均形成非零且互斥的 owner 统计，见第 7 节；本阶段又不发 candidate，因此该缺口不阻塞 no-mutation probe。完整串行 CTest 正在独立执行，结果按增量规则另立后续 TNO，不在本文提前宣告。

## 4. Production 配置与三路 identity

三路 fresh production emit 均从相同 post-stats checkpoint 运行，固定：

```text
direct_single_writer_state_reads = cpp-default/native true
pure_event_compute_word_bypass   = cpp-default/native true
commit cap                       = 4096
DP segment penalty               = 1000000 PPM
all other experimental schedule policies = off
active-mask mode                 = default / explicit-off / probe
```

对应输出与日志为：

```text
build/xs_activity_stage16_active_mask_gap_default_20260717/
build/xs_activity_stage16_active_mask_gap_explicit_off_20260717/
build/xs_activity_stage16_active_mask_gap_probe_20260717/

build/logs/xs/xs_wolf_grhsim_build_activity_stage16_active_mask_gap_default_20260717.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage16_active_mask_gap_explicit_off_20260717.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage16_active_mask_gap_probe_20260717.log
```

default 日志为 `effective=cpp-default/source=cpp-default`，explicit-off 与 probe 分别为 `effective=off/probe`、`source=xs-override`。三套 output 在 O3 build 前各有 `157` 个文件，其中 `155` 个为 `Makefile + *.cpp + *.hpp`，另两个为 activity/emitter JSON。按相对文件名排序后先计算各文件 SHA256、再对 manifest 计算 SHA256：

| manifest | default | explicit-off | probe |
| --- | --- | --- | --- |
| all `157` files | `8d4ccb9627485e2525c8aac4a34b8eee38b40e29e26f9206442862f4b0a6d5ec` | 同左 | 同左 |
| `155` generated source files | `bfcf0b9d4554b5da76bcc0f08c733a8bb9f9f6b96c50150c51cdded162853cda` | 同左 | 同左 |

`155`-source manifest 也与 [TNO0091](./TNO0091_stage14_native_hybrid_default_implementation_and_fresh_gates_20260717.md) 的 Stage 14 current native-hybrid/cap4096 generated source 相同。两个 JSON 的单文件 SHA 也三路一致，并与 Stage 14 相同：

```text
activity_schedule_supernode_stats.json
  e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77

grhsim_emit_stats.json
  9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

这同时闭合 C++ default-off、显式 off 与 probe no-mutation identity；probe 的计时与统计只写 stderr，不进入任何 artifact。

## 5. Activity-schedule identity

三路 full emit 的结构完全相同：

| 指标 | default | explicit-off | probe |
| --- | ---: | ---: | ---: |
| total supernodes | `63,726` | `63,726` | `63,726` |
| compute supernodes | `63,241` | `63,241` | `63,241` |
| commit supernodes | `485` | `485` | `485` |
| final DAG edges | `528,622` | `528,622` | `528,622` |
| boundary activation edges | `1,983,923` | `1,983,923` | `1,983,923` |
| compute-commit value pairs | `262,225` | `262,225` | `262,225` |

Stage 16 是 emitter-local lowering probe，不是 schedule mutation；因此上述 identity 是预期硬门禁，而不是声称 raw BAE 已下降。它也再次说明本轮收益口径是同一 schedule 的 active-mask encoding proxy，不能写成“BAE 减少 `4.59%`”。

## 6. Non-table production 结果

production probe 的 non-table 精确统计为：

| metric | value |
| --- | ---: |
| groups / activation lists | `359,259` |
| local targets | `3` |
| global active IDs | `802,749` |
| merged byte entries / real covered bytes | `683,621` |
| conditional groups | `138,063` |
| baseline contiguous writes | `653,299` |
| zero-hole candidate writes | `623,294` |
| gap saved | `30,005` (`-4.592843%`) |
| groups improved by gap | `15,913` |
| candidate covered bytes | `768,767` |
| inserted hole bytes | `85,146` (`110,756 ppm`，即 `11.0756%`) |
| invalid groups | `0` |
| rejected bounds/lane DP transitions | `594 / 111,705` |

candidate width histogram 与总 writes 精确对账：

```text
width1  581,735
width2   16,904
width4   11,004
width8   13,651
total   623,294
```

这里 `baseline_writes == contiguous_writes`，所以 `30,005` 是同一 direct/non-table 表示中由允许 zero hole 单独带来的 write/chunk proxy 下降，没有混入 table representation rewrite。相对 TNO0097 的离线估算，正式 emitter owner/local/conditional 分类后仍复现约 `4.6%` 的候选规模，足以进入独立 targeted stage。

代价同样明确：为少发 `30,005` 个 RMW helper，candidate 多覆盖 `85,146` 个零 byte。静态 planner 不知道各 group 的动态 fire 次数，也没有证明 logical lane 对齐实际 cache line。因此 `-4.592843%` 不是 instruction 或 cycles 预测；Stage 17 必须用真实 source、汇编、功能和 SimTop 50k 判断更宽 RMW 是否值得。

## 7. Table、excluded 与 coverage 边界

table 类精确结果为：

| metric | current per-entry table | contiguous chunk proxy | zero-hole chunk proxy |
| --- | ---: | ---: | ---: |
| groups | `586` | `586` | `586` |
| global active IDs | `186,671` | `186,671` | `186,671` |
| merged entries / real bytes | `89,903` | `89,903` | `89,903` |
| conditional groups | `92` | `92` | `92` |
| writes/chunks | `89,903` | `19,942` | `17,530` |
| gap-only delta | - | control | `-2,412` (`-12.095076%`) |
| candidate covered/hole bytes | - | - | `95,057 / 5,154` (`54,220 ppm`) |
| groups improved vs current / vs contiguous | - | - | `586 / 533` |
| invalid groups | - | - | `0` |
| rejected bounds/lane transitions | - | - | `55 / 2,711` |

table candidate width histogram 为：

```text
width1   4,919
width2   1,139
width4     979
width8  10,493
total   17,530
```

日志中的 table `saved=72,373` 是 current per-entry count `89,903` 对 zero-hole chunks `17,530` 的差，不是 gap pack 的纯收益。它混合了“table loop/per-entry representation 改成 chunk representation”和“contiguous chunk 再允许 gap”两层变化；与 non-table 的 `30,005` 不能直接相加。table 的同表示 gap-only 数字只能使用 `19,942 -> 17,530`，即 `2,412/-12.095076%`。

更重要的是，current table 是紧凑 loop body，`89,903` 个静态 entries 不等于每个 50k 周期执行 `89,903` 次 write；其中可能有 reset/cold condition。没有 runtime category evidence 前，不能据 `saved=72,373` 直接 inline/rewrite table。后续先增加不改变 production 行为的 table evaluated/change/hit counter，再决定是否值得单独 targeted。

本轮明确排除且单列的 owner 为：

| excluded owner | groups | entries |
| --- | ---: | ---: |
| deferred direct final | `135,754` | `174,665` |
| deferred aggregate final | `109` | `2,210` |
| memory row | `46,248` | `77,216` |
| seed/initial | `6` | `8,590` |
| commit range | `0` | `0` |
| unclassified | `0` | `0` |

另有 local-only `13` groups / `13` targets，其中 conditional `11`；它们不进入 global headline。production 首行将 coverage 明示为 `classified_global_activation_path`，不能把本文数字外推为全部 activation work。

最终 validation 为：

```text
validation=pass
validator_self_test=pass

plan_invalid=0 invalid_width=0 bounds=0 overlap=0 anchor=0
mask_high_bits=0 missing=0 extra=0 mask_mismatch=0 cross_lane=0
metadata=0 candidate_worse=0
```

`rejected_bounds_transitions` 与 `rejected_lane_transitions` 是 DP 搜索中被合法 gate 排除的备选 transition，不是 validator failure；不能与 invalid breakdown 混为一谈。

## 8. 决策与 Stage 17 边界

Stage 16 probe 已证明两件事：

1. 在完全相同的 current native-hybrid schedule/source 上，non-table direct path 存在可验证的 `30,005/-4.592843%` write/chunk proxy 机会；
2. table 的静态数字更大，但其主要收益先来自 representation 改写，且缺动态 hotness 证据，不能与 direct 一起采用。

因此下一阶段采用最小可归因范围：

- 只对已验证的 non-table direct global path 发 zero-hole candidate；
- schedule、topo、active ID、batch、value slot、file/function order 和 baseline table/deferred/memory-row/seed path 全部冻结；
- source diff validator 只允许 selected direct active-mask statement encoding 变化；
- 检查 O3 `.text/.data/.eh_frame`、相关 helper 汇编和 active array 对齐/实际跨 cache-line 行为；
- 通过 100/10k/50k 功能门禁后，按 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的 node-local inode、`taskset + numactl`、fixed-ASLR、whole-node gate 与平衡顺序跑 SimTop 50k；
- table 先做 category runtime counter，不与 direct candidate 混测。

本阶段没有运行 O3 或 SimTop 不是以静态指标替代最终性能，而是因为 default/off/probe 的所有 generated source 已 byte-exact；三者会构建出同一可执行代码，重复 50k 不可能测量尚未发出的 candidate。Stage 17 一旦真正改变 direct encoding，即使结构指标不变或静态代价有温和疑点，也应按用户要求完成 SimTop 功能与性能闭环。

`activeMaskGapPackPolicy` 当前继续保持 C++ native `off`。只有后续 targeted candidate 在有效双 NUMA 50k 上形成方向一致且超过噪声的收益，才另立 adoption 记录讨论是否改为 C++ native default；XS 不单独暗设默认。

## 9. 提交与回归边界

Stage 16 的 C++ option/probe、Python/native/XS sparse plumbing、focused tests、production no-mutation result 与本文构成一个任务粒度。提交时先提交 `wolvrix` 子模块，再提交父仓 submodule pointer、脚本和 `pdocs`；production build/log 目录不提交。

完整串行 CTest 的完成时间晚于本文 production 结论，按目录增量规则另立 TNO。Stage 17 targeted mutation、O3/功能/50k 与 table runtime counter 也分别作为后续阶段记录，不向本文追加新的独立实验。
