# TNO0175 gen24 independent policy implementation and static gate

## 1. 状态与结论

gen24 aggregate 已从 `active_mask_gap_pack_policy=targeted-direct` 解耦到独立的
`commit_exact_event_policy=off|targeted-cold-layout`。本阶段完成 C++ emitter、Python/native
binding、XiangShan 稀疏 override、生成代码运行 harness 与完整 wolvrix 回归；没有新增功能失败。
production SimTop 四臂功能和正式 50k walltime 另行记录，默认裁决仍以该 runtime gate 为准。

## 2. 策略边界与默认来源

- `commit_exact_event_policy` 独立控制 event-qualified bitmap continuation、selective commit
  activation tracking、lockstep scalar writes、相关 bitmap cache-line alignment，以及 exact-event
  singleton guard 数量达到 `1024` 后的 cold layout hint。
- `active_mask_gap_pack_policy` 只控制 non-table direct active-mask gap packing；它不再选择或门控
  gen24 closure。
- eligibility proof 不满足时 fail closed 到旧 lowering，并记录精确 fallback reason。
- C++ 是唯一原生默认来源。Python 的 `None` 不转发 attribute；XS 脚本只在显式设置
  `WOLVRIX_XS_GRHSIM_COMMIT_EXACT_EVENT_POLICY` 时转发，未增加 SimTop 专用默认。
- 当前实现的拟议原生默认为 `targeted-cold-layout`，但若后续 A/C 正式 gate 不成立，将在最终提交前
  改回 `off`。

新增 emitter 诊断绝对计数：

```text
[GRHSIM_COMMIT_EXACT_EVENT] policy=<...> selected=<0|1> fallback=<...> cold_runs=<N> cold_guards=<N> lockstep_groups=<N> lockstep_writes=<N>
```

这些计数使用 atomics 汇总并行 file emission，后续用于核对 SimTop C/D 两臂是否选择完全相同的
exact-event closure。

## 3. focused 与 binding gate

最终代码上的绝对结果：

| gate | 绝对结果 | 用时 |
| --- | ---: | ---: |
| `emit-grhsim-cpp-commit-exact-event` | `1/1 PASS` | `17.85 s`（完整 CTest 中 `17.94 s`） |
| `emit-grhsim-cpp` 主回归 | `1/1 PASS` | `291.14 s` |
| active-mask gap-pack focused branch | `PASS` | 独立直接执行 |
| pybind option unittest | `22/22 PASS` | 测试进程内 |
| XS sparse-option unittest | `32/32 PASS` | `0.038 s` |
| `git diff --check` | parent/submodule 均 PASS | N/A |

exact-policy focused 覆盖原生默认、显式 off、attribute/environment precedence、非法值、与
targeted-direct 正交性、串/并行确定性、lockstep、`1023/1024` cold threshold、perf/runtime
profile/fullpass/missing-DAG fail-closed。generated harness 实际编译并执行 off 与
targeted-cold-layout 两套产物，覆盖 guard false 不写、guard true 更新、重复 eval 稳定和后续再次更新。

Python/native 参数追加在原 positional ABI 尾部，Python public API 保持 keyword-only；fresh binding
目录运行 `python -S`，避免旧 editable install 污染。XS 回归同样显式使用 fresh binding，确认没有
在 SimTop wrapper 中暗开策略。

## 4. 完整 wolvrix 回归

fresh Ninja Release 目录完成全量 `94` 个 build steps，构建 PASS。并行完整 CTest 的绝对结果为：

```text
49/51 PASS
Total Test time (real): 291.62 s
emit-grhsim-cpp: 291.61 s, PASS
emit-grhsim-cpp-commit-exact-event: 17.94 s, PASS
```

仅有两个失败：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

二者名称与诊断文本和 Stage 11..33 的既有失败完全一致；本阶段没有修改相应 transform，失败集合
没有扩大。因此完整回归判定为 `no new failure`。

## 5. 下一 gate

按 [TNO0174](./TNO0174_gen24_targeted_direct_dependency_audit_and_landing_plan_20260725.md) 的定义
顺序构建 A/B/C/D 四个隔离 SimTop 产物。每臂先完成 fixed-ASLR 100/10k 功能 gate；正式 50k 直接
复用 SimpleTES trusted runtime，动态选择整组空闲 CCD，并完成 A/C、C/D 的 ABBA+BAAB。所有文档
同时记录每个样本和每个 order 的绝对 `Host time spent`，不能只记录相对百分比。
