# TNO0214：原则化 hot-event 门禁落地与 native gate

日期：2026-08-01

## 1. 结论

[TNO0213](./TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md) 的最终 `TRBS` 形态已经作为
Wolvrix 通用 C++ emitter 默认行为落地，但原搜索 patch 的 `eventEdgeSlotCount >= 256` 门禁被删除。新门禁只依据
最终 schedule 中 input event 的 exact-`posedge` 复用量，并且不读取端口名、SimTop 类型、固定 ValueId、benchmark
身份或 raw model-size 阈值。

代码身份为：

| 对象 | commit |
| --- | --- |
| Wolvrix | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| parent gitlink pin | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |

新旧门禁在 SimTop 上生成相同 C++ fingerprint。正式同 CCD 50k 比较为
`47,567.25 -> 47,597.00 ms`，新门禁慢 `29.75 ms / 0.062543%`；ABBA/BAAB order gap 仅
`0.072499 pp`，判运行时等价而不是性能回退。原则化实现保留并默认启用。

## 2. 原则化选择器

选择器在 final pure-event word-pack 可能完成调度重建之后、active-mask probe 之前运行。对每个注册 input event，
它遍历最终 `scheduleBatches` 和对应 supernode operations，只统计 exact-`posedge` operand：

```text
posedgeUses   = final schedule 中 exact-posedge operand 数
coveredBatches = 至少包含一次该 operand 的最终 batch 数
reusableUses  = posedgeUses - coveredBatches
fixedCost     = 2  # object bool materialization + clear
apply         = reusableUses > fixedCost
```

候选先按 `reusableUses`、再按 `posedgeUses` 取最大；完全相等时保持 input registration order，不引入 ValueId
或名字 tie-break。`reusableUses == 2` 明确 fail-closed。

采用后继续发射 TNO0213 的最终表示：

1. event edge backing 改为 typed enum array；
2. 选中的 input event 稳定 remap 到 slot 0；
3. object 中预解码 exact-posedge bool；
4. schedule method 使用 batch-local bool snapshot；
5. 同一事件的 negedge/general residual 仍读取完整 enum，未改变语义。

SimTop fresh 默认生成的实际诊断为：

```text
[GRHSIM_DIRECT_HOT_INPUT_EVENT] applied=1 input_events=2 event_slots=412 selected_input_index=0 posedge_uses=220132 covered_batches=76 reusable_uses=220056 fixed_cost=2
```

这不是临界触发：可复用量比固定成本大五个数量级。该逻辑位于 C++ emitter 默认路径，Python 直接调用同样继承；
没有新增 SimTop wrapper 开关，也没有借用或开启 `targeted-direct`。

## 3. 去 benchmark 特化测试

新增 `emit-grhsim-cpp-direct-hot-input-event` 独立 CTest，覆盖：

- 任意端口重命名和反向 port-binding 顺序；
- hot input event 不是第一个注册项；
- 完全相等候选的稳定 tie；
- `reusableUses == fixedCost` 时 fail-closed；
- event slot count `255/256/257` 三个边界的结构决策相同；
- posedge/negedge/general 混用，完整 enum residual 保持正确；
- 生成 C++ 的独立 compile/run harness。

fresh 测试结果：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| fresh Release/Ninja | `407/407` steps | PASS |
| main emitter | `1/1`，`288.78 s` | PASS |
| direct-hot 专项 | `1/1`，`7.43 s` | PASS |
| commit exact-event | `1/1`，`18.19 s` | PASS |
| assertion outer-guard | `1/1`，`8.07 s` | PASS |
| deferred activation | `1/1`，`0.26 s` | PASS |
| same-batch cohort | `1/1`，`13.19 s` | PASS |
| fresh full CTest | `51/53`，`426.77 s` | PASS，仅两项历史失败 |
| isolated pybind | `29/29` | PASS |
| XS sparse-option | `32/32`，`0.041 s` | PASS |

full CTest 的失败集合仍恰好为 `transform-comb-lane-pack` 与 `transform-repcut`，与 TNO0207 相同；没有新增失败。

## 4. Fresh production artifact 与功能门禁

首次 `principled_landing_v1` 冷构建在 oneTBB 远端 clone 部分下载后从零重试，因此在产生任何 SimTop artifact
之前主动停止并保留为 infrastructure failure 现场。正式 `principled_landing_v2` 只从 evaluator 固定 control
worktree 复用同版本第三方 Git objects；Wolvrix、generated C++ 和 SimTop ELF 均从空 build tree 重新生成编译。

正式 artifact：

| 对象 | 绝对值 |
| --- | --- |
| candidate digest | `8f48fb47438f8b2bb5210807fd5009c6c9e3ec816fdc2a73b78a5046363c9bc2` |
| generated fingerprint | `9eeec63950179e4d517a87c7e8f31556bdd2903a80fd278f8f6af729a3686a7f` |
| emu bytes | `91,094,720` |
| emu SHA-256 | `79214fe9f1da44ddb42cd7e6be288607e66d30268beb6a663490fb779b63ad81` |
| fresh evaluator elapsed | `1,632.864641 s` |

功能 canary：

| cycles | instrCnt | cycleCnt | guest cycles | walltime |
| ---: | ---: | ---: | ---: | ---: |
| `100` | `0` | `96` | `101` | `305 ms` |
| `10,000` | `458` | `9,996` | `10,001` | `4,497 ms` |

旧搜索门禁 final artifact 的 generated fingerprint 也为 `9eeec639...a3686a7f`，且 ELF bytes 同为
`91,094,720`。两个 ELF 的整体 SHA 不同；readelf/strings 审计显示独立 worktree 的绝对源码路径使新 `.rodata`
增加 `0x100`，并改变对应 PC-relative 字节，而 `.text` size 与 generated program identity 相同。因此不能把整体
ELF hash 不同误写为门禁造成的 codegen 差异，正式结论仍由直接运行比较给出。

## 5. 旧门禁到原则化门禁的正式 50k

协议为同一轮完整 ABBA+BAAB，两个 order 固定同一 CCD/CPU/sibling/helper/NUMA；每个样本关闭 ASLR 并验证
`personality=00040000`、whole-CCD quiet、affinity、NUMA residency、PMU scheduling、0 CPU migration 与功能签名。
第一轮即满足 order gap `<0.25 pp`，按时间顺序选为正式结果。

placement 为 `node1:112-119,304-311`，measured CPU `112`，SMT sibling `304`，helper CPU `0`，NUMA `1`。

| order | old gate samples | principled samples | principled improvement |
| --- | --- | --- | ---: |
| ABBA | `47,572 / 47,540 ms` | `47,594 / 47,543 ms` | `-0.026285%` |
| BAAB | `47,569 / 47,588 ms` | `47,669 / 47,582 ms` | `-0.098784%` |
| pooled | `47,567.25 ms` | `47,597.00 ms` | `-29.75 ms / -0.062543%` |

order gap 为 `0.072499 pp`。八个样本全部 `personality=00040000`、CPU migrations `0`，且相同 placement gate
通过。PMU 也符合 byte-layout 噪声而非新 work：instructions 仅 `+0.000002%`，cycles `+0.087523%`，frontend
no-dispatch `+0.095180%`，cmask `+0.127397%`，backend stalls `+0.073271%`。

## 6. HS/TRBS 边界与裁决

完整 HS 不能机械叠加到 TRBS：两者都会对同一 hot event 做分类、存储和 batch snapshot，属于同一思路的两代
实现。理论上只能把 TRBS 未覆盖的 negedge/general residual 另做独立 hybrid arm；在没有新的 SimTop 50k 正收益
前不进入默认实现。本次 landing 没有加入该 residual arm。

最终裁决：

- TNO0213 已证明 `B -> TRBS` 为 `51,562.00 -> 47,632.25 ms`，提升 `7.621407%`；
- 本文证明原则化门禁相对旧搜索门禁为 `-0.062543%` 噪声等价，并生成同一 C++ fingerprint；
- 因此保留 TRBS 通用默认，同时采用结构化门禁，删除 raw slot-count/benchmark 代理；
- 后续 SimpleTES 必须 repin 到 `52ba7d9/d3ed9de` 空 control 后再继续搜索。

## 7. 证据哈希

| 对象 | SHA-256 |
| --- | --- |
| `CMakeLists.txt` | `75fc0bd9481627d9928ceb912353a4eaa9fff56eebfc4a1fc0caa6cc9996f1d5` |
| `lib/emit/grhsim_cpp.cpp` | `7102ba7fde4dd72e4dc7419f1553b61d555482c49f79984c591d78e85b5239a8` |
| `tests/emit/test_emit_grhsim_cpp.cpp` | `9ad22716cb26b5ee104209ad8672c2dac60c3feb9ce221d58b1768b18c9e97a4` |
| fresh build summary | `bf7f6755b8ca7db5969174387497752e1bbfa37526436ed307d31bba955483cf` |
| artifact provenance | `1738c50d6eb5e03d3eefcf62ace7322d08115e4d56ff21dcf1b9d7f335cf610f` |
| artifact manifest | `0017257633843e52fbcb9c8df06ebbdb7aedeefd89d7317cb8ae70291ac05ab4` |
| old/new pair summary | `cb5f68a7b6053a8d9e6ee6afec72f93b0d8abf2280b3d647236e18e7fbc6ab59` |
| selected runtime result | `9c1c07f93f44a60994719a53d7f15dffccedee8ed9dd0b63e35db05f4876fd20` |
| fresh full CTest log | `6c66112ea19a8c6a83de1ce723565cd765950db33940967db1b0a469f5332baf` |
| fresh failed-test list | `d0cdc0cd93aab95d0f917784918e9451dac986842521f158de3d67417d9bef01` |
| same-CCD runner | `6539112dac5b8b9276471afd7e0a474b71327559ac06929586858abe851f71f0` |
| gap-loop runner | `7c7e99c677bbd76bd97fb82f45de29e19c8e11cee627c84b528c42ea00739404` |
