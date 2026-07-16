# TNO0091 Stage 14 native hybrid default implementation and fresh gates

记录日期：2026-07-17

状态：实现与 fresh gate 完成，严格 runtime 待补。按 [TNO0090](./TNO0090_stage14_native_hybrid_default_adoption_plan_20260717.md) 将 direct single-writer state-read 与 pure-event compute-word bypass 成对迁为 C++ native defaults；Python binding 与 XS 脚本只传显式 override，XS 不再自建默认或写回低层环境。focused/full tests、fresh default/off identity、O3 与 fixed-ASLR 100/10k/50k 功能均通过；首次严格 runtime 入口因整机 node idle 不合格而拒绝，因此本文不形成 50k 性能结论或最终采用裁决。

## 1. Native 默认与配置层级

C++ emitter 的两个解析入口现以 `true` 作为 native fallback：

```text
direct_single_writer_state_reads = true
pure_event_compute_word_bypass   = true
```

两项均保持统一优先级：

```text
emitter attribute > WOLVRIX_GRHSIM_* environment > C++ native default
```

因此无 attribute、无低层环境时启用 hybrid；显式 attribute `false` 可压过环境 `1`，显式 attribute `true` 也可压过环境 `0`。这使默认值只存在于 C++ 一处，不再依赖具体调用脚本。

Python 层新增 `direct_single_writer_state_reads: bool | None`，并将对应 native keyword 接入 `session_emit_grhsim_cpp`。`None` 不写 emitter attribute，交由低层环境或 C++ default 解析；显式 `False` 必须作为 attribute 传递，不能被 Python 假值判断吞掉。既有 `pure_event_compute_word_bypass` 同样保持 `bool | None` 语义。

XS 脚本对每项采用：

```text
WOLVRIX_XS_GRHSIM_* > WOLVRIX_GRHSIM_* > None
```

两层都缺失时传 `None`，日志显示 `cpp-default`；脚本不再把解析值写回 `WOLVRIX_GRHSIM_*`。profile 仍为 `false`，word-pack policy 仍为 `off`，Stage 6 packing 没有随本次默认迁移启用。

## 2. 自动测试与完整回归

配置层 focused tests 覆盖了 native default、显式开关、环境开关与优先级：

- C++ emitter fixture 验证 default 与 explicit-on source 相同，explicit-off 与 legacy source 相同，并验证 attribute 可覆盖相反的环境值；长测通过，独立运行用时 `290.47s`。
- Python 自动测试 `3/3` 通过，覆盖 `None` 省略、`False` 原样传递、非 bool 拒绝以及新增 native keyword 可接受。
- XS 自动测试 `3/3` 通过，覆盖 high-level > low-level > `None`、两项 option 对称行为、`cpp-default` 日志和环境不写回。

子模块 full build 为 PASS。串行 full CTest 为 `46/48`，其中 `emit-grhsim-cpp` 与 `transform-activity-schedule` 均通过；仅保留此前连续存在的两项失败：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

失败集合与 Stage 11..13 相同，没有新增回归。

## 3. Fresh default/off 生成配置

从同一 current canonical checkpoint 完整生成两套目录：

```text
build/xs_activity_stage14_native_hybrid_default_20260717
build/xs_activity_stage14_native_hybrid_explicit_off_20260717
```

default 日志确认两项均未由 XS 显式赋值：

```text
direct_single_writer_state_reads=cpp-default
pure_event_compute_word_bypass=cpp-default
```

explicit-off 日志确认两项均为显式 `False`。两套 activity schedule 结构完全相同，均保持当前 NO0300 canonical stats：

| 指标 | default | explicit-off |
| --- | ---: | ---: |
| supernodes | `63726` | `63726` |
| boundary activation edges | `1983923` | `1983923` |
| stats SHA256 | `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77` | 同左 |

这是预期结果：本阶段只改变 emitter 消费相同 schedule 的方式，不改变 activity-schedule 本身。

## 4. Source identity 与回滚

default 生成精确出现 hybrid source 形状：

```text
direct reads       75830 = 40108 canonical + 35722 aliases
pure-event words     107
```

explicit-off 中两类 marker 均为 `0`。154 个 generated C++/header 的汇总如下：

| 指标 | explicit-off NO0300 | native default hybrid | 变化 |
| --- | ---: | ---: | ---: |
| source bytes | `1377532061` | `1356872724` | `-1.499735%` |
| source lines | `13911084` | `13684888` | `-1.626013%` |

native default 与历史 Stage 7 hybrid 比较时，raw 文件中有 `66/154` 因 fresh checkpoint 的纯 op/value 诊断注释编号而不同；删除这些整行纯注释后 `154/154` byte-exact。explicit-off 与 Stage 13 canonical NO0300 则 raw `154/154` byte-exact，无需 normalization。由此同时闭合了“无显式配置等于历史 hybrid”和“显式 `false/false` 精确回到当前 NO0300”两条 identity。

## 5. Fresh O3 静态结果

default 与 explicit-off 均完成独立 O3/link：

| 指标 | explicit-off NO0300 | native default hybrid | 变化 |
| --- | ---: | ---: | ---: |
| emu bytes | `94768184` | `93694944` | `-1.132490%` |
| ELF `.text` | `88186297` | `87113502` | `-1.216510%` |

对应 ELF SHA256：

```text
native default  51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788
explicit-off    c1674532559292fba857ba56dff3acf20a2789e70517c677ba9e1e683c7ce204
```

两者的 emu bytes 与 ELF `.text` 分别精确复现用于既有 hybrid/NO0300 对照的对应历史产物，说明 default 来源迁移本身没有引入额外 codegen 或 link-layout 漂移。

## 6. Fixed-ASLR 功能门禁

两套 fresh emu 均在 `setarch x86_64 -R` 下通过 100/10k/50k：

| Limit | Guest / cycle / instr | PC | default | explicit-off |
| ---: | --- | --- | --- | --- |
| 100 | `101 / 96 / 0` | `0x0` | PASS | PASS |
| 10k | `10001 / 9996 / 458` | `0x800027c6` | PASS | PASS |
| 50k | `50001 / 49996 / 73580` | `0x80001312` | PASS | PASS |

所有进程 exit 均为 `0`，mismatch/assert/error/fail/bad-trap 等负向扫描均为 `0`。这些 wall time 仅作功能门禁，不作为性能数据。

## 7. Strict runtime 暂停点

进入 fresh default/off 性能测试前执行了 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 要求的整 node 30 秒 gate；当时 N0/N1 mean idle 仅为 `88.517%/85.964%`，显著低于 `99%` 门槛，因此整组在启动 emu 前即被拒绝。

本次拒绝是协议按预期工作，不构成候选性能数据。后续仍须在 node-local `/dev/shm` 独立 inode、镜像核、整 node pre/run monitor、page placement、PMU、scheduler 和平衡 AB/BA 全部通过时，完成 native-default hybrid 对 explicit-off NO0300 的 fresh 50k。该结果形成独立增量文档前，不用当前功能 wall time 替代性能结论，也不在本文宣告最终 runtime 采用裁决。

## 8. 增量补充：历史 runtime ELF 的 section identity

为判断 Stage 14 fresh ELF 是否仍代表 [TNO0087](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) 已测的机器码，进一步比较两对完整二进制：

```text
Stage 14 native default  <-> Stage 7 measured hybrid
Stage 14 explicit-off    <-> Stage 10 same-post NO0300 control
```

直接按 ELF section 的 file offset/size 读取原始字节并计算 SHA256，结果为：

| section | Stage 14 default = Stage 7 hybrid | Stage 14 off = same-post NO0300 |
| --- | --- | --- |
| `.text` | `49a1ff89bc7a9e46cdc5a7a992c1a20c43065982153969ad8fe3bd94933dbee8` | `af29cce355a5af9baac260ed805a0df82c723ef93c6d6dd261bc98f61ac02ff1` |
| `.data` | `ec8bd5bcb93f2efbf7a54d622fad4172a48ff462d5acb9b66b30577e1a91e7fb` | `5fe8f6dcfe3a137e8ef615e7358945f4faca35cf9b2d02ed3c7a837aef1f3a89` |
| `.eh_frame` | `c31d402ae8fb2488dbebd45e0dfb8d4ebf429dbc145920437c0dd059d512a362` | `f46576b1b0f7bf8bb17b155fe61538292af7f39bfef36801eae30851f7ccddc0` |

每个表格单元中的 SHA 在左右两个对应 ELF 间完全相同。完整 ELF SHA 本身不同：

| 对象 | SHA256 |
| --- | --- |
| Stage 14 native default | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| Stage 7 measured hybrid | `ae6b6df7ab5fff8b003414d9b2e3c80937b9ef30e9fe55bb8c670742e35b281e` |
| Stage 14 explicit-off | `c1674532559292fba857ba56dff3acf20a2789e70517c677ba9e1e683c7ce204` |
| Stage 10 same-post NO0300 | `453b5dad1b332facbfe1bc229256b08a88a3b304f4a4f60b7a124a843f639976` |

但 `cmp -l` 对每一对都只返回 `6` 个差异字节，且全部位于 `.rodata` 的编译日期/时间字符串：

```text
Stage 14 default   Jul 17 2026, 01:42:10
Stage 7 hybrid     Jul 15 2026, 20:47:35

Stage 14 off       Jul 17 2026, 01:44:42
same-post NO0300   Jul 16 2026, 06:03:33
```

除这 6 个不可执行的 build timestamp 字节外，两对完整 ELF 均一致；尤其 `.text`、`.data` 和 `.eh_frame` 没有任何漂移。这把 source normalization identity 提升为机器码 identity：Stage 14 native default 执行的正是 TNO0087 已测 hybrid 代码，explicit-off 执行的正是 same-post NO0300 control 代码。
