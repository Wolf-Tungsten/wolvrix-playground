# TNO0080 Stage 12 commit guard merge-cap full build and functional gate

记录日期：2026-07-16

状态：完成 `8192/16384/32768` 三档 current-default NO0300 same-poststats full emit、O3/link、generated-code 静态对比和 100/10k 功能门禁。三档均无 CPP/TU 膨胀且功能终点一致，全部进入 fixed-ASLR、跨 NUMA 的 SimTop 50k 裁决。

## 1. 输入与构建闭合

三档均从与 current control 相同的 post-stats checkpoint 恢复：

```text
post-stats SHA256   165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
control stats SHA   e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
emit stats SHA      9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b（四者一致）
```

除 `maxCommitOpsPerSupernode=8192/16384/32768` 外，activity schedule 显式使用仓库默认 `1000000 PPM`，post-DP/Kahn/fanin/direct/bypass/clones 均关闭，排序保持 `level-id`。Stage 12 cap `4096` probe 与 Stage 10 same-post explicit-off control stats 字节一致。

三个 full emit 的最终 schedule stats 与 TNO0079 的 scan 逐项一致。O3/archive/link 均成功，emu SHA256 为：

```text
control  453b5dad1b332facbfe1bc229256b08a88a3b304f4a4f60b7a124a843f639976
8192     e8bb64c554c1b1d1c68229e6d80d9c0fc4a05da77257346359ef67f91d80adad
16384    79e5645635fbd037607495f9974f586e293b52af4d6a5b02f4ffef6014991139
32768    4981ab9fa091474ed4281dccc66cf8428ff8ceceddbb029491508a9399e8b40b
```

## 2. Generated source

| 指标 | control | 8192 | 16384 | 32768 |
| --- | ---: | ---: | ---: | ---: |
| schedule CPP | `117` | `97` | `85` | `79` |
| compute functions | `66` | `66` | `66` | `66` |
| commit functions | `51` | `31` | `19` | `13` |
| CPP bytes | `1,376,984,664` | `1,376,857,805` | `1,376,753,154` | `1,376,647,099` |
| CPP lines | `13,904,899` | `13,903,882` | `13,903,092` | `13,902,750` |
| max CPP bytes | `36,041,985` | `36,046,873` | `36,048,049` | `36,047,748` |

最大 CPP 始终是包含既有 `42,937`-op oversize commit SN 的文件，最坏 TU 没有随 cap 扩大。按行数最大的 CPP 也始终是 compute `sched_5`，为 `512,782` 行。因此三个候选均不存在历史无 cap 方案的编译体积风险。

源码总量下降来自 commit 部分；commit 源码分别减少 `265,884/429,634/513,778` bytes。compute SN 和 op 顺序完全相同，但 value-slot 编号发生全局重排，导致 66 个 compute CPP 都不再 byte-identical。该 layout blast radius 不影响功能和结构等价性，但正式性能不能只按 BAE 解释。

## 3. O3 静态产物

| 指标 | control | 8192 | 16384 | 32768 |
| --- | ---: | ---: | ---: | ---: |
| generated object bytes | `100,287,080` | `100,235,640` | `100,200,656` | `100,186,256` |
| object text sum | `95,126,561` | `95,097,405` | `95,081,371` | `95,075,615` |
| ELF bytes | `94,768,184` | `94,745,048` | `94,734,864` | `94,737,728` |
| GNU size text | `94,592,303` | `94,570,593` | `94,564,685` | `94,564,143` |
| ELF `.text` | `88,186,297` | `88,170,459` | `88,171,135` | `88,176,273` |

静态上 `16384` 最均衡：已经取得 `32768` 总 BAE 收益的约 92%，active-update site 最少且 ELF 最小。`32768` 相对 `16384` 只再减少 `182` BAE，却使最终 `.text` 增加 `5,138` bytes；这只是 runtime 优先级信息，不作为淘汰门槛。

## 4. 功能门禁

三个 emu 分别完成 100 与 10k CoreMark + NEMU diff。功能运行不采集性能，正式 50k 才使用 `setarch x86_64 -R` 固定 ASLR。

```text
100:  guest/cycleCnt/instrCnt/PC = 101/96/0/0x0
10k:  guest/cycleCnt/instrCnt/PC = 10001/9996/458/0x800027c6
```

所有进程退出码为 0，没有 diff mismatch、assert、fatal 或异常终点。

原始产物：

```text
build/xs_activity_stage12_commit_guard_merge_cap{8192,16384,32768}_full_20260716/
build/logs/xs/xs_wolf_grhsim_build_activity_stage12_commit_guard_merge_cap{8192,16384,32768}_full_emit_20260716.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage12_commit_guard_merge_cap{8192,16384,32768}_o3_20260716.log
build/logs/xs/xs_wolf_grhsim_activity_stage12_commit_guard_merge_cap{8192,16384,32768}_{100,10k}_20260716.log
```

## 5. 下一步

三档全部进入 NUMA0/NUMA1 fixed-ASLR 50k。每个 socket 使用相同物理 core 和 memory node，串行执行 `control/8192/16384/32768/control`；每个样本前要求两个 SMT sibling 的 3 秒平均 idle 均 `>=99%`，并记录五项 PMU、gate-to-run gap 与 guest 终点。共享的前后 control 用于识别同 socket 漂移，最终不以跨 socket 平均掩盖方向反转。
