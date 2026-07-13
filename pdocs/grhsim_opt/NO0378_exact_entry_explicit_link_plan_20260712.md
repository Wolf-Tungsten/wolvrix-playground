# NO0378 Exact-entry explicit-link plan

日期：2026-07-12

## 1. 目标

[NO0377](./NO0377_exact_entry_object_mutation_abandonment_20260712.md) 已证明不能安全改写或 relocatable-link 原 sched
objects。本轮改为最终链接层的隔离实验：保持 NO0300/direct 的所有 model objects 原样，只在显式 object 序列中插入
独立 `.text` padding objects，使两版 117 个 `eval_compute/commit_batch` 完整入口地址逐项相同。

该实验只消除 NO0365 中最明显的入口布局变量，不把 4 KiB 对齐引入生产实现，也不修改 direct state-read 的默认关闭
状态。

## 2. 显式链接可复现性预检

从 XiangShan difftest Make 数据库提取 40 个 harness objects，再按原 archive member order 展开 152 个 model objects，
使用原 flags `-lz -lzstd -ldl` 显式链接：

| Side | Original emu SHA256 | Explicit-link emu SHA256 | Result |
| --- | --- | --- | --- |
| NO0300 | `c30220ac6f7601a261e2aec4eccbf2191af100a8a16de77a6deb87267d159078` | same | byte-exact |
| direct | `cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4` | same | byte-exact |

这证明最终链接可以不用 archive extraction heuristic，并且显式 object 顺序精确复现原布局。

两次原构建的 40 个 harness objects 中，39 个 byte-exact；唯一不同的 `common.o` 的 `.text` size/content 仍完全相同，
最终 emu section headers 和 117 个 model entries 也不变，差异只是 `.rodata` 中 5 个编译时刻字符。正式 paired 构造统一
使用 NO0300 的 40 个 harness objects，以去掉该无关时刻字面量并保证 model 前缀完全相同。

## 3. Padding 传播预检

构造一个只含 16 个零字节、`.text` alignment=1 的新 object，并在 NO0300 `sched_0.o` 后插入。相对 byte-exact
显式链接基线：

| Gate | Result |
| --- | ---: |
| Entry symbols | 117 |
| `compute:0` address delta | 0 |
| Other 116 entry deltas | exactly +16 |
| Symbol key/size mismatches | 0 |
| Output `.text` delta | exactly +16 bytes |

因此，在 sched object 后插入 N-byte、alignment=1 的 padding，可以精确控制下一个以及后续全部 batch entries，且
不会改变当前 entry。

## 4. Paired stride 算法

从两个原始 emu 按最终地址提取同序的 117 个入口。对 `i = 0..115`：

```text
baseline_stride[i] = baseline_addr[i + 1] - baseline_addr[i]
direct_stride[i]   = direct_addr[i + 1] - direct_addr[i]
target_stride[i]   = max(baseline_stride[i], direct_stride[i])
baseline_pad[i]    = target_stride[i] - baseline_stride[i]
direct_pad[i]      = target_stride[i] - direct_stride[i]
```

两版首入口原本都为 `0x18c310`。在各自 `sched_i.o` 后插入对应 padding 后，由地址递推可知下一入口相同，进而全部
117 个入口相同。实际计算结果为：

| Metric | NO0300 | Direct |
| --- | ---: | ---: |
| 原始同址 entries | 1/117 | 1/117 |
| Nonzero inter-entry pads | 45 | 53 |
| Inter-entry padding sum | 855,664 | 1,926,496 |
| Max single padding | 151,008 | 647,904 |
| Non-16-byte padding | 0 | 0 |

共同 target span 为 `87,279,936` bytes，预期最后一个 `commit:116` 入口为 `0x54c8c50`。inter-entry padding 后
两版 `.text` 预计为 `89,041,385/89,041,406` bytes；差值 21 正好等于最后一个 direct function 多出的 21 bytes。
在 baseline `sched_116.o` 后再插入 21-byte tail padding，使两版最终 `.text` 都为 `89,041,406` bytes；该 tail 位于
最后入口之后，不影响任何目标入口。

## 5. 构造和结构门禁

1. 不复制、改写或重新归档原 model objects；在两个新 output 目录中只创建 response files、padding objects 和 emu。
2. 两侧使用相同 40 个 NO0300 harness objects、各自原 152 个 model objects，并保持原 archive member order。
3. 每个 padding object 只允许 `.text` 零字节和空 `.note.GNU-stack`，`.text` alignment 必须为 1；文件名编码 side、
   slot 和 bytes。
4. 重新核对两个原 archive 和全部输入 object SHA256，构造前后必须不变。
5. 输出必须各有 117 个同序 entries，完整地址逐项相同；symbol size 必须分别等于其原 emu；共同最后入口必须为
   `0x54c8c50`。
6. 两个 output `.text` size 必须同为 `89,041,406`，且 baseline/direct 实际 padding count/sum 必须等于上述计算。
7. 任一门禁失败即停止，不进入仿真。

## 6. 后续功能与性能门禁

结构通过后，按独立文档依次执行两侧 10k、50k CoreMark + NEMU difftest。要求 guest/model cycles、指令数、PC、去掉
host time 的 progress checkpoints 一致，并且无 mismatch、assert 或 `input_fullpass_blocked`。

功能通过后再执行 fixed-ASLR、CPU138、NUMA1 的 NO0300-layout/direct-layout/NO0300-layout 50k A/B/A，采集
cycles、instructions、frontend empty、cmask6 和 backend stalls。正式运行前检查机器负载；A/B/A baseline spread
必须 `<=1%`，五事件必须 100% 调度。结果用于回答：在完整入口地址严格一致后，direct 的 `-3.465%` instructions
是否能转化为 cycles 收益；不把本次 padding binary 当作可提交的生产优化。

本篇只声明 corrected construction 和验收口径，尚未生成正式 paired emu 或运行仿真。
