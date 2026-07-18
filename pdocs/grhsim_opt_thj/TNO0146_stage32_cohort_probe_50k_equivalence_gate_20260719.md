# TNO0146 Stage 32 cohort probe 50k equivalence gate

日期：2026-07-19

状态：production O3/archive、emu link、page-local fixed-ASLR 100/10k/50k 全部通过。
`252/252` 个 cohort 在 50k 均满足入口全等、member fire 全等和出口全清；Stage33 可实现
独立 default-off strict。probe 自带插桩，因此本记录中的 walltime 仅是绝对诊断值，不能
与未插桩 current-default 做 A/B，也不改变任何默认选项。

## 1. Build 与 link

| artifact | SHA256 | bytes | result |
| --- | --- | ---: | --- |
| O3 log | `a6dea594679169e2b2bdd2058c9d67a4ed41d224bae96b0196ac23276a061e9d` | `24831` | exit0, wall `9:44.13` |
| `libgrhsim_SimTop.a` | `2981b17fbeec8d80839fdfc6394f3d3fcdf0c534cf1b54cc33b6bf7fd106fd8a` | `101889144` | PASS |
| emu link log | `92810c43f672b672cb678c2fed5640bcc8b09bc08077fdcc0eb7aa5087decdfb` | `6873` | exit0, wall `16.12 s` |
| `grhsim-compile/emu` | `b5081559f6d5d0ca8915e2a96dea32638b71aca9c8dcf0f195cba3f21a266200` | `96208288` | PASS |

O3 使用 `clang++ -O3 -j4`；link 使用 `NUM_CORES=1 WITH_CHISELDB=0
WITH_CONSTANTIN=0 GRHSIM=1 WOLVRIX_GRHSIM_WAVEFORM=0`。

## 2. NUMA/page-cache 方法

本阶段是 counter gate 而非性能 gate，但仍按后续统一规则在 NUMA0/CPU86 first-touch 三个
独立 `/dev/shm` inode：

```text
taskset -c 86 numactl --physcpubind=86 --membind=0 \
  cp --reflink=never <source> /dev/shm/grhsim_stage32_cohort_probe_n0_20260719/<file>

taskset -c 86 numactl --physcpubind=86 --membind=0 \
  setarch x86_64 -R <staged-emu> -i <staged-image> --diff <staged-nemu> \
  -b 0 -e 0 -C <cycles>
```

staged SHA256 为 emu=`b5081559f6d5d0ca8915e2a96dea32638b71aca9c8dcf0f195cba3f21a266200`、
image=`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`、
NEMU=`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
10k 与 50k 的 live `numa_maps` 都是 emu
`N0=21691/N1=0`、NEMU `N0=115/N1=0`；CPU allowed list=`86`、ASLR probe=`00040000`。
100 太短，明确不伪造 live placement；它复用同一已 first-touch inode，只作 smoke gate。

## 3. 功能与 walltime 绝对值

| cycles | instr/cycle | guest cycle | Host time | function | placement |
| ---: | --- | ---: | ---: | --- | --- |
| `100` | `0 / 96` | `101` | `216 ms` | PASS | short-run, staged inode |
| `10,000` | `458 / 9,996` | `10,001` | `9,717 ms` | PASS | `21691/0`, `115/0` |
| `50,000` | `73,580 / 49,996` | `50,001` | `76,039 ms` | PASS | `21691/0`, `115/0` |

三个 emu 均 exit0，无 difftest mismatch/assert/fatal。`Host time spent` 是唯一端到端字段，
但 probe 增加 counters/TSV 和 `.text`，所以这些绝对值只证明运行完成，不能用于性能晋升。

raw logs：

| cycles | SHA256 | bytes |
| ---: | --- | ---: |
| `100` | `edf1f51fcc5ade55fe643a3b0285c624afd96a7bc3c93156691ddadec5fc037c` | `74508` |
| `10,000` | `affce643342811fb72218d2ab1f0fd763d90064814413e9d5d65f69a7fece5c2` | `77604` |
| `50,000` | `ad854057d940bd6e670ddf4a31e6d0e55a08a4ca81fef0fd0579a29a177b8518` | `79649` |

## 4. 全 cohort 绝对计数

每个 TSV 有 `902` data rows + 1 header。等价合格要求：每个 cohort 的
`entry_partial=exit_partial=0`，所有 member `mismatch=0`、
`entry_pending=body_fire`、`exit_pending=0`。结果：

| cycles | valid/total | entry pending sum | body fire sum | exit pending sum | member tests saved |
| ---: | ---: | ---: | ---: | ---: | ---: |
| `100` | `252 / 252` | `9,084` | `9,084` | `0` | `6,128` |
| `10,000` | `252 / 252` | `779,958` | `779,958` | `0` | `543,056` |
| `50,000` | `252 / 252` | `9,270,152` | `9,270,152` | `0` | `6,854,019` |

50k 按每 cohort 只取一次 leader/profile fire 的绝对和是 `2,416,133`；
`9,270,152` 是按 902 个 member 展开的实际 body fire 和，两者不能混用。

100/10k 只跑到 workload 前缀，故只有 `56/72` 个 cohort 的当前 body fire 恰等于 50k
profile 值，这是预期的停止点差异，不是等价失败。50k 时 `252/252` 个 cohort 的每个
member body fire 都精确等于 profile fire。

cohort TSV：

| cycles | SHA256 | bytes |
| ---: | --- | ---: |
| `100` | `4906aba1a1b934468f8341676ba1eede57be94e06b3a4816aafe5ca38b49b071` | `76536` |
| `10,000` | `c021b2860efdfbe6f167b659814f30d7924de51c25bffaea6d3ac6e301e80a17` | `91671` |
| `50,000` | `21b3f250b4919ea8414f7c5f2040232f3c9455f82f31581b653c0ab4999b60d0` | `102482` |

完整 supernode fire TSV 也保留绝对值：100/10k/50k 分别为
`1,017,729 / 1,078,154 / 1,155,117` bytes，SHA256 分别为
`82fb59052552fb6920286d719b3eee6c504f14f89106e283f10b99ca18e2cde6`、
`997beccd1c3c4f65bc7f7a20224d72dd49ce428a76b233ea3d3e6273aa1f5d6d`、
`308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a`。
legacy/current profile 的全量差异和 current-profile replay 见
[TNO0147](./TNO0147_stage32_current_profile_replay_and_log_audit_20260719.md)。

## 5. Pinned cohort11

| cycles | source/body fire per member | entry batches | all off/on/partial | entry active sum | body fire sum | exit active/pending | saved |
| ---: | ---: | ---: | --- | ---: | ---: | --- | ---: |
| `100` | `1` | `554` | `553 / 1 / 0` | `51` | `51` | `0 / 0` | `50` |
| `10,000` | `142` | `40,253` | `40,111 / 142 / 0` | `7,242` | `7,242` | `0 / 0` | `7,100` |
| `50,000` | `19,175` | `200,653` | `181,478 / 19,175 / 0` | `977,925` | `977,925` | `0 / 0` | `958,750` |

50k 的 51 行每行 `entry_pending=body_fire=19,175`、`mismatch=0`、
`exit_pending=0`；source min/max/profile 也均为 `19,175`。因此 pinned contract 完整闭合。

## 6. Stage33 入口与默认决定

Stage32 只读 probe 到此完成，C++ 默认保持 `off`。Stage33 使用本次 current 50k fire TSV
作为 profile，可以实现独立 strict policy，
优先支持全部 252 个已证明 cohort，而不是只硬编码 cohort11；但必须保留以下约束：

1. follower active-ID holes 保持，删除 source fanout/initial seed 的 follower bits；
2. ordinary batch 只消费 leader 一次，并按原 topo 顺序无条件执行该 cohort 的全部 payload；
3. 每个 payload 仍使用自己的原 active ID 作为 propagation context；
4. fullpass/commit 不变，不携带 probe counters；
5. fresh O3/link、100/10k/50k difftest 后，正式双 NUMA ABBA/BAAB 的唯一 headline 是
   SimTop 50k `Host time spent` walltime。BAE `-2,169` 和 guard tests `-6,854,019` 只是解释量。
