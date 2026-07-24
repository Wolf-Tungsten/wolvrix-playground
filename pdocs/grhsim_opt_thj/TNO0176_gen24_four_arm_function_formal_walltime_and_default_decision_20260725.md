# TNO0176 gen24 four-arm function, formal walltime, and default decision

## 1. 状态与最终裁决

[TNO0174](./TNO0174_gen24_targeted_direct_dependency_audit_and_landing_plan_20260725.md) 定义的
A/B/C/D 四臂已经完成隔离 production SimTop 构建与 100/10k 功能门禁；决定默认值所需的 A/C、C/D
两组 50k fixed-ASLR、quiet whole-CCD ABBA+BAAB 正式 walltime 也已完成。

最终裁决如下：

- 独立 `commit_exact_event_policy` 默认开启，C++ 原生默认保持
  `targeted-cold-layout`。A/C 合并绝对 walltime 为 `74,773.25 -> 61,284.00 ms`，减少
  `13,489.25 ms`，改善 `18.040208229547%`；ABBA 与 BAAB 均同向且远超 `1%` 门槛。
- `active_mask_gap_pack_policy=targeted-direct` 继续默认关闭。C/D 合并为
  `60,759.50 -> 60,665.25 ms`，仅减少 `94.25 ms`，改善 `0.155119775508%`；虽两种 order
  同向，但低于 `1%` 门槛，也小于 control 的 `426 ms` 样本 spread。
- 这个决定只依据 SimTop 50k 的端到端 `Host time spent` walltime。100/10k host time 只作为功能
  gate 的绝对记录，不参与默认裁决。
- exact-event closure 与 gap packing 仍由两个独立 option 控制；开启 exact-event 不隐式开启
  `targeted-direct`，后者仍可供显式实验使用。

## 2. 四臂定义与产物身份

四臂均从同一代码与默认生成配置构建，仅用 XS 显式 override 构造 2x2 消融：

| arm | `commit_exact_event_policy` | `active_mask_gap_pack_policy` | 作用 |
| --- | --- | --- | --- |
| A | `off` | `off` | landing 前的 current-default control |
| B | `off` | `targeted-direct` | gap packing 单独开启 |
| C | `targeted-cold-layout` | `off` | exact-event 独立开启，也是最终默认组合 |
| D | `targeted-cold-layout` | `targeted-direct` | 两项同时开启，复现历史 gen24 组合 |

`generated fingerprint` 使用 SimpleTES evaluator 的同一算法：按相对路径排序，覆盖
`grhsim_emit` 下全部 `134` 个非 symlink `.cpp/.cc/.cxx/.h/.hpp`，对路径长度、路径和内容做
SHA-256。四臂 fingerprint 与最终 emu 均不同，排除了 override 没有落到产物的假消融：

| arm | generated fingerprint SHA-256 | emu bytes | emu SHA-256 |
| --- | --- | ---: | --- |
| A | `2d733597a7ba6031800e1448dba57d73b79d998a316f1e309c61886cb9433eef` | `93,671,816` | `e32506d621b9d364879014103f529786234d196c6aa53c7f5865934aeaed2236` |
| B | `2542b86424b04286845784c68a5d2784b6e35e88928851068c94ffac344d7f08` | `93,577,608` | `dcf1b454dfa821b2b17513cf1ce68afddf9e8e87149e2490fe50a001f1108ae0` |
| C | `9f1200284dc887eecf8adc47147cab0e80c319944fded414b32439d1c5c896ca` | `91,673,160` | `83a62f9b35d23e35bd98711db9c25fa8469dcb49c32ac042a15d545b0aa4f79f` |
| D | `63fbf8c466543800c15638113da13c5060823dd8ccd20606ee53be929f60ab42` | `91,587,144` | `f247bbb963724fbf4c37bc7c914b3be237fc1a03bc1c3e04a0439154c3b3ce82` |

产物根目录为 `build/xs_commit_exact_event_landing_20260725/arm_{a,b,c,d}`；正式 runtime
在搬运到 `/dev/shm` 时再次核对了相应 emu SHA-256。

## 3. emitter policy diagnostics

exact-event 诊断与四臂定义完全一致：

| arm | policy | selected | fallback | cold runs | cold guards | lockstep groups | lockstep writes |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| A | `off` | `0` | `policy_off` | `0` | `0` | `0` | `0` |
| B | `off` | `0` | `policy_off` | `0` | `0` | `0` | `0` |
| C | `targeted-cold-layout` | `1` | `none` | `16` | `44,976` | `2,089` | `11,799` |
| D | `targeted-cold-layout` | `1` | `none` | `16` | `44,976` | `2,089` | `11,799` |

C/D 的 exact-event 绝对计数逐项相同，说明 gap packing 没有改变 exact-event closure 的选择集合。
A/C 因 gap policy 为 `off` 不输出 gap-pack active diagnostic；B/D 均输出：

| arm | validation | self-test | selected groups | baseline writes | candidate writes | selected savings | invalid groups |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| B | `pass` | `pass` | `16,045` | `87,117` | `56,994` | `30,123` | `0` |
| D | `pass` | `pass` | `16,045` | `87,117` | `56,994` | `30,123` | `0` |

B/D 的 selected 集合和写数逐项相同；仅非语义的 emitter 计时不同，分别为 `76,261 us` 与
`78,059 us`。细分诊断中，两臂同为 non-table `359,256` groups、`653,394 -> 623,271`
writes、gap saved `30,123`，table `587` groups、`89,969 -> 17,546` writes、gap saved
`2,499`，并且 `unclassified_groups=0`、所有 invalid breakdown 均为 `0`。因此四臂同时满足
选择集合可解释、validator 通过和策略正交性要求。

## 4. 100/10k 功能 gate

四个独立 emu 均完成 cycle-limited 100/10k 运行，功能签名一致：

- 100 cycles：`Core-0 instrCnt = 0, cycleCnt = 96`，`Guest cycle spent: 101`；
- 10k cycles：`Core-0 instrCnt = 458, cycleCnt = 9996`，`Guest cycle spent: 10001`。

绝对 host walltime 如下；这些短运行只判功能 PASS，不用于性能裁决：

| arm | 100 host time | 100 result | 10k host time | 10k result |
| --- | ---: | --- | ---: | --- |
| A | `219 ms` | PASS | `9,804 ms` | PASS |
| B | `156 ms` | PASS | `10,620 ms` | PASS |
| C | `158 ms` | PASS | `7,012 ms` | PASS |
| D | `147 ms` | PASS | `7,130 ms` | PASS |

功能日志位于 `build/logs/xs_function/commit_exact_event_landing_20260725/`。

## 5. 正式 50k protocol 与有效性

正式结果复用 SimpleTES trusted runtime：每组先动态选择完整空闲 CCD，再固定单一物理核、SMT
sibling 与 NUMA node；emu/NEMU/image 搬到本 NUMA 的 `/dev/shm`；以 `setarch x86_64 -R`
关闭 ASLR，并在每个有效样本中核对 `personality=00040000`。每组按 ABBA 或 BAAB 顺序运行，headline
metric 只取每次日志唯一的 `Host time spent`，组内和 pooled 均取算术平均值。

本轮只把 quiet-CCD admission 的最大尝试次数从 `3` 提高到 `8`，用于容忍外部负载造成的 transient
retry；idle、affinity、monitor、NUMA、PMU 与功能门槛均未放宽。全部 `16` 个纳入统计的样本均为
`personality=00040000`，并满足完整 `16` CPU CCD 的 placement/admission/pre gate；运行期 monitor
覆盖另外 `15` 个 peer CPU，target CPU 由固定 affinity、零 CPU migration 与 perf audit 覆盖。因此
整组 CCD 的 monitor、PMU scheduled、binary/NEMU NUMA locality 与功能 audit 均 PASS。最终 headline
明确为 `Host time spent` walltime。有效 placement 为：

| comparison/order | CCD | target / sibling | NUMA | group result |
| --- | --- | --- | ---: | --- |
| A/C ABBA | `node1:144-151,336-343` | `147 / 339` | `1` | valid |
| A/C BAAB | `node1:112-119,304-311` | `118 / 310` | `1` | valid |
| C/D ABBA | `node0:8-15,200-207` | `8 / 200` | `0` | valid |
| C/D BAAB | `node0:8-15,200-207` | `8 / 200` | `0` | valid |

### 5.1 丢弃的 quiet-CCD group

A/C 的前两次 ABBA attempt 都完成了前两个临时 50k 样本，但第三个样本的 fixed-CCD pre-gate
被外部负载拒绝。trusted runtime 因此丢弃整个不完整 group，对外结果均为 `samples=[]`、
`valid=false`、`retryable_infra=true`；临时样本只作为 infra 诊断保留，没有数据混入正式均值：

| attempt | selected CCD / target | 作废的临时 walltime | 失败前最后一次 whole-CCD gate | 处理 |
| --- | --- | --- | --- | --- |
| `ac/abba_try1` | `node0:88-95,280-287` / CPU `88` | `A 74,081 ms; C 60,363 ms` | mean idle `97.186875%`，min idle `92.33%`，target idle `92.67%`；低于 `98%/95%/98%` 门槛 | 对外 `0` samples，整组丢弃 |
| `ac/abba_try2` | `node1:168-175,360-367` / CPU `169` | `A 74,303 ms; C 60,738 ms` | mean idle `99.271875%`，min idle `93.33%`；min 低于 `95%` 门槛 | 对外 `0` samples，整组丢弃 |

## 6. A/C：exact-event 独立收益

A 为 exact off/gap off，C 为 exact on/gap off，因此该比较只测独立 exact-event closure。

| order | 实际顺序与绝对 walltime (ms) | A samples / mean (ms) | C samples / mean (ms) | A-C 绝对减少 | 相对改善 |
| --- | --- | --- | --- | ---: | ---: |
| ABBA | `A 74,727; C 61,443; C 61,067; A 74,859` | `[74,727, 74,859] / 74,793.00` | `[61,443, 61,067] / 61,255.00` | `13,538.00 ms` | `18.100624389983%` |
| BAAB | `C 61,498; A 74,814; A 74,693; C 61,128` | `[74,814, 74,693] / 74,753.50` | `[61,498, 61,128] / 61,313.00` | `13,440.50 ms` | `17.979760145010%` |
| pooled | 两个 order 等权合并 | `[74,727, 74,859, 74,814, 74,693] / 74,773.25` | `[61,443, 61,067, 61,498, 61,128] / 61,284.00` | `13,489.25 ms` | `18.040208229547%` |

A 的 pooled range 为 `74,693..74,859 ms`，绝对 spread `166 ms`，相对 mean 为
`0.222004527020%`；裁决门槛 `max(1%, control spread)=1%`。两种 order 均稳定正向，pooled
`18.040208229547%` 显著越过门槛。因此 exact-event 独立优化通过默认开启 gate。

## 7. C/D：targeted-direct 在 exact-event 上的增量

C 为 exact on/gap off，D 为 exact on/gap targeted-direct，因此该比较只测 gap packing 在最终
exact-event 组合上的增量。

| order | 实际顺序与绝对 walltime (ms) | C samples / mean (ms) | D samples / mean (ms) | C-D 绝对减少 | 相对改善 |
| --- | --- | --- | --- | ---: | ---: |
| ABBA | `C 60,619; D 60,670; D 60,739; C 61,020` | `[60,619, 61,020] / 60,819.50` | `[60,670, 60,739] / 60,704.50` | `115.00 ms` | `0.189084093095%` |
| BAAB | `D 60,500; C 60,594; C 60,805; D 60,752` | `[60,594, 60,805] / 60,699.50` | `[60,500, 60,752] / 60,626.00` | `73.50 ms` | `0.121088312095%` |
| pooled | 两个 order 等权合并 | `[60,619, 61,020, 60,594, 60,805] / 60,759.50` | `[60,670, 60,739, 60,500, 60,752] / 60,665.25` | `94.25 ms` | `0.155119775508%` |

C 的 pooled range 为 `60,594..61,020 ms`，绝对 spread `426 ms`，相对 mean 为
`0.701124926966%`；裁决门槛仍为 `1%`。C/D 虽然两种 order 都是小幅正向，但 pooled 只减少
`94.25 ms`，明显小于 `426 ms` spread 且只有 `0.155119775508%`，不满足默认开启门槛。
这也与 [TNO0104](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md)
记录的独立 targeted-direct 中性结论一致。

不同 comparison 在不同时间窗口和 CCD 上运行，因此 A/C 中的 C 绝对值与 C/D 中的 C 绝对值不作
跨组比较；所有 effect 都只由同一 group 内的成对 order 与 pooled 结果计算。

## 8. 默认来源、回归与后续探索

落地后的默认 contract 为：

- C++ emitter 是唯一默认源：`commit_exact_event_policy=targeted-cold-layout`，
  `active_mask_gap_pack_policy=off`；
- Python `None` 不注入 option，直接继承 C++；
- XS 只稀疏转发显式环境 override，不为 SimTop 单独暗开任何优化；
- SimpleTES 仍可分别显式控制 exact-event 与 gap-pack option，后续探索不会再借用
  `targeted-direct` 去门控 gen24 closure。

[TNO0175](./TNO0175_gen24_independent_policy_implementation_and_static_gate_20260725.md) 已在同一最终实现上
完成完整回归，绝对结果为：

```text
fresh Ninja Release: 94 build steps, PASS
full CTest:          49/51 PASS
Total Test time:     291.62 s
emit-grhsim-cpp:     PASS, 291.61 s
commit-exact-event:  PASS, 17.94 s
pybind unittest:     22/22 PASS
XS sparse unittest:  32/32 PASS, 0.038 s
```

仅失败 `transform-comb-lane-pack` 与 `transform-repcut`，名称和断言与 Stage 11..33 的既有失败相同；
本实现没有修改对应 transform，失败集合没有扩大，故回归结论为 `no new failure`。四臂 100/10k
和本记录的 `16` 个正式 50k 样本进一步覆盖了 production 生成、链接与运行路径。

## 9. native no-policy identity：PENDING

`build/xs_commit_exact_event_landing_20260725/native_default_fresh` 的 fresh no-policy identity 在本记录
成文时仍在运行。该检查会在不设置两个 XS policy override 的条件下，验证原生路径解析为
`commit_exact_event_policy=targeted-cold-layout`、`active_mask_gap_pack_policy=off`，并核对生成产物与
显式 C 臂的身份关系。

当前没有可归档的 generated fingerprint、emu SHA、功能结果或 identity 结论；本记录不把该项写成
PASS，也没有用它替代任何正式 walltime 样本。默认裁决来自已经完成且有效的 A/C、C/D factorial
gate；native identity 完成后应按 append-only 规则在后续 TNO 中追加结果。

## 10. 结果文件

- 四臂 build logs：`build/xs_commit_exact_event_landing_20260725/arm_{a,b,c,d}/logs/xs/`；
- 功能 logs：`build/logs/xs_function/commit_exact_event_landing_20260725/`；
- A/C 正式结果：`build/logs/xs_perf/commit_exact_event_landing_20260725/ac/`；
- C/D 正式结果：`build/logs/xs_perf/commit_exact_event_landing_20260725/cd/`。
