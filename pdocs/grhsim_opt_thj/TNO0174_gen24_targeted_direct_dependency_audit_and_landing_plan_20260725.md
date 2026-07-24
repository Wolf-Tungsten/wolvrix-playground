# TNO0174 gen24 targeted-direct dependency audit and landing plan

## 1. 结论

SimpleTES gen24 在源码中曾由 `active_mask_gap_pack_policy=targeted-direct` 硬性门控，但 dependency audit 没有发现对 gap-pack planner、selected chunks、probe 或宽写结果的逻辑/数据依赖。该关系是搜索阶段借用实验开关，不是 correctness dependency。

原始 `targeted-direct` 只改变 non-table direct active bitmap OR 写的组织形式。其独立正式 walltime 为：

| order | default mean (ms) | targeted-direct mean (ms) | candidate-default | 方向 |
| --- | ---: | ---: | ---: | --- |
| ABBA | `(74,629+74,738)/2 = 74,683.50` | `(74,806+74,868)/2 = 74,837.00` | `+153.50 ms / +0.205534%` | 回退 |
| BAAB | `(74,668+74,732)/2 = 74,700.00` | `(74,430+74,494)/2 = 74,462.00` | `-238.00 ms / -0.318608%` | 改善 |
| pooled | `74,691.75` | `74,649.50` | `-42.25 ms / -0.056566%` | 中性 |

两种 order 方向相反，且绝对变化低于 spread，因此 [TNO0104](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md) 已判定它保持 C++ default `off`。gen24 的 fresh 结果 `74,055.00 -> 60,648.25 ms`、改善 `13,406.75 ms / 18.103774%` 不能反向作为默认开启 gap packing 的证据。

## 2. 真实依赖链

gen24 aggregate 的四个部分实际依赖如下：

- event-qualified continuation 只要求 `supernode_active_curr_` 保持正确；baseline byte writes 与 gap-packed writes 都满足；
- selective `trackCommitActivation` 是 continuation protocol 的内部依赖；
- lockstep scalar writes 只依赖 write metadata、single-writer proof、guard/next/init expression；
- cold `unlikely` 只依赖 exact-event singleton register guard census；
- bitmap `alignas(64)` 是该 continuation layout closure 的实现部分，不是 gap packing correctness requirement。

原 patch 中 `activeMaskGapPackPolicy == kTargetedDirect -> eventQualifiedBitmapContinuation` 是唯一硬门。`canElideTerminalActiveScan` 不读取任何 gap-pack 状态。

## 3. 落地边界

新增独立 `commit_exact_event_policy=off|targeted-cold-layout`：

- 它控制 gen24 event-qualified continuation、selective tracking、lockstep、selected bitmap alignment 与 `>=1024` cold guard hint；
- `active_mask_gap_pack_policy` 恢复只控制 gap packing；
- C++ 是唯一默认源，Python `None` 继承 C++，XS 仅稀疏转发显式 override；
- 目标默认是 exact-event policy `targeted-cold-layout`、gap-pack policy `off`，但必须先通过下述独立 runtime gate。

四臂定义：

| arm | commit exact-event | active-mask gap-pack | 用途 |
| --- | --- | --- | --- |
| A | off | off | 旧 current-default |
| B | off | targeted-direct | 原 gap packing 单独效果 |
| C | targeted-cold-layout | off | 拟议独立默认 |
| D | targeted-cold-layout | targeted-direct | 历史 gen24 组合与交互 |

正式 walltime 至少完成 A/C 与 C/D 两组 fixed-ASLR、quiet whole-CCD SimTop 50k ABBA+BAAB。A/C 决定 gen24 能否独立默认，C/D 决定 gap packing 是否有额外正收益。裁决门槛为两 order 同向且 pooled 改善超过 `max(1%, control spread)`。

## 4. 当前实现 gate

authoritative gen24 candidate：

```text
candidate bytes/SHA-256: 37922 / 8f84146b6457552161b46870503cc290e2e74557f1ecf53c2b0ab27598e3e5a2
patch bytes/SHA-256:     29687 / 8e88033519a4d2b065a97f15fc0ed7d843ecefbad4098fe6203a61ec8163f78c
raw target SHA-256:      23619556e2b80e04bf6a9751456528a79a09b8db26bd28fd59d526dfb493118b
raw diffstat:            +421/-7, lib/emit/grhsim_cpp.cpp only
```

已先机械恢复 raw target，再将 gate 解耦到新 policy。fresh CMake/Ninja build 成功；独立 `emit-grhsim-cpp-commit-exact-event` focused CTest `1/1` PASS，原 active-mask gap-pack focused branch PASS。production SimTop 四臂、full regression 与正式 walltime 另行新增记录。

## 5. 提交原则

实现、功能与性能闭环后先提交 wolvrix 子模块，再提交父仓 gitlink、稀疏 override 和阶段文档。若 A/C 不过门槛，不默认启用 exact-event policy；若 C/D 不过门槛，targeted-direct 必须继续保持 `off`。
