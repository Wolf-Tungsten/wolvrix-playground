# NO0387 Direct state-read instruction profile plan

日期：2026-07-12

## 1. 优先级

[NO0386](./NO0386_exact_entry_fixed_aslr_runtime_gate_20260712.md) 证明 direct state-read 在入口同址时净加速
`1.733%`，但只把 host instructions 从 baseline `172.879B` 降到 `166.888B`。复用
[NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md) 的 same-FIR GSim instructions 均值
`80.071B`：

```text
direct / GSim instructions       = 2.084x
baseline instruction excess      = 92.809B
direct instruction excess        = 86.818B
closed excess                     = 5.991B / 6.455%
```

额外 instructions 仍是 GrhSIM/GSim gap 的第一主项，因此先更新 direct 的 instruction profile，再继续处理
NO0386 的小幅 cmask6 density 残差。

## 2. 采集口径

对 NO0379 exact-entry direct emu 运行 CoreMark 50k：

```text
event:      instructions:u
period:     25,000,000
call graph: dwarf,8192
CPU:        188
sibling:    380
NUMA:       node1
ASLR:       setarch -R
```

所有命令先执行 `source env.sh`。运行前 CPU188/380 三秒平均 idle 必须都 `>=99%`；固定 seed、image、NEMU
difftest 和 `-b 0 -e 0 -C 50000`，unset `EMU_RUNTIME_PROFILE`，关闭 progress 输出。本轮只做 attribution，不使用
profile wall time 评价性能，也不需要 A/B/A。

exact-entry direct 的真实函数 body 和 native direct 相同，padding 不在运行路径中；使用该 binary 可以保持当前已验证
的 fixed mapping，同时避免再引入 native entry-address 漂移。

## 3. 数据门禁

必须满足：

1. exit 0，guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、PC `0x80001312`；
2. 无 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`；
3. `perf report` 的 `Total Lost Samples = 0`；
4. event/config 为 `instructions:u`、period 25M、DWARF 8192；
5. 当前 stat instructions 为 `166,888,327,986`，预期约 `6,676` samples；profile approximate count 与 stat 的
   差异不得超过一个 period；
6. direct/GSim sample ratio 与 `2.084x` stat ratio的相对误差不得超过 `0.5%`。

## 4. 对照与输出

沿用 [NO0349](./NO0349_fixed_aslr_latest_instruction_profile_codegen_compare_20260712.md) 的 leaf-symbol 分类，把 direct
样本拆为 compute、commit、`eval()` control、generated helpers 和 other，并与以下固定输入比较：

```text
NO0300 baseline: 6,914 samples / 172.850B approximate instructions
same-FIR GSim:   3,201 samples /  80.025B approximate instructions
```

重点输出：

1. direct 总样本和各类别 share；
2. 相对 NO0300 少掉的约 238 samples 分配到 compute/commit/helper 的位置；
3. 每个 batch 的 sample delta，确认 state-read direct 命中的 compute8 等热点是否实际下降；
4. direct compute/commit 与 GSim 全部 `subStep*` 的 approximate excess 分解；
5. 对 top remaining GrhSIM batches 阅读 generated C++，并在 GSim 中找同一状态/操作的写回与 activation 代码，选择
   下一项能成批删指令的候选。

本篇只声明 profile 计划，尚未运行 `perf record`。
