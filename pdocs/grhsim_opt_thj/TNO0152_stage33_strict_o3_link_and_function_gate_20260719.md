# TNO0152 Stage 33 strict O3, link, and function gate

日期：2026-07-19

状态：fresh production strict 已完成 O3/archive、独立 difftest link 和 page-local fixed-ASLR
100/10k/50k 功能门禁，全部 exit0 且功能终点精确一致。本文记录的单次 walltime 只证明运行
完成，不与跨 commit/旧 page cache control 做性能比较；正式默认决定仍等待 fresh same-commit
control 与双 NUMA balanced 50k `Host time spent`。

## 1. O3 archive

generated Makefile 使用 `CXX=clang++ -O3 -j4`，未注入额外 CXXFLAGS。结果：

| artifact | SHA256 | bytes | result |
| --- | --- | ---: | --- |
| O3 raw log | `7376fda9459cafcd6582e225fabd208c52ec88c97d49c3c665b8ecb6f67c4afa` | `24890` | exit0, wall `9:26.48` |
| strict `libgrhsim_SimTop.a` | `dc60653cddb3b05889edc126e68f26cbe45476f24a771ef719538ddc1730076c` | `99225382` | PASS |
| current-default archive oracle | `d257613a74a33dd2c9abe501373bd573f1ce053ffe29103d2cbab0410b779a90` | `99249366` | historical same-config oracle |

strict archive 相对 oracle 为 `-23,984 B`。oracle 来自 Stage23 current-default build，仅用于
静态大小解释；正式 walltime control 后续在同一 Stage33 commit fresh 重建。

## 2. Difftest link and ELF

link 使用独立 `BUILD_DIR=build/xs_activity_stage33_same_batch_cohort_strict_20260719/grhsim`，
`GRHSIM_MODEL_DIR` 指向已经 O3 的 strict emit 目录，`NUM_CORES=1`、ChiselDB/Constantin/waveform
均关闭；没有调用顶层生成 recipe。

| artifact | SHA256 | bytes | result |
| --- | --- | ---: | --- |
| link raw log | `002c303ba3735777a7ac7e2a7eeafc3b2ced6aae591742d70914c6d91ddffd6c` | `6970` | exit0, wall `15.96 s` |
| strict emu | `b195d2e533a4dd818ebb56c57f59af54df1ee69dc4fc9b3cc60c76be133bba51` | `93659528` | PASS |
| current-default emu oracle | `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` | `93671816` | historical same-config oracle |

两个 `emu` 路径在 build tree 中都是 symlink；表内 SHA/bytes 与下表 section 均针对解引用后的
ELF target（`stat -L`/普通 `sha256sum`），不是 symlink inode 自身的 142/137 bytes。

ELF section absolute comparison：

| section | current default | strict | delta |
| --- | ---: | ---: | ---: |
| `.text` | `87,095,345` | `87,083,985` | `-11,360` |
| `.rodata` | `5,647,080` | `5,646,936` | `-144` |
| `.eh_frame` | `706,144` | `706,144` | `0` |
| `.data` | `152` | `152` | `0` |
| `.bss` | `14,688` | `14,688` | `0` |
| whole ELF | `93,671,816` | `93,659,528` | `-12,288` |

`.text` 小幅下降只说明 strict 没有 code-size 膨胀，不能替代动态 walltime。

## 3. Fresh node-local staging

N0 function staging 目录此前不存在：

```text
/dev/shm/grhsim_stage33_cohort_strict_function_n0_20260719/
```

每个文件均用 CPU86 执行：

```text
taskset -c 86 numactl --physcpubind=86 --membind=0 \
  cp --reflink=never <source> <target.tmp>
mv <target.tmp> <target>
```

staged absolute identity：

| file | SHA256 | bytes |
| --- | --- | ---: |
| emu | `b195d2e533a4dd818ebb56c57f59af54df1ee69dc4fc9b3cc60c76be133bba51` | `93659528` |
| coremark image | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` | `16712` |
| NEMU | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` | `567504` |

runtime 使用同一 CPU86：`taskset + numactl --physcpubind=86 --membind=0 + setarch
x86_64 -R`。10k/50k audit 的 CPU allowed list 均为86，ASLR personality均为 `00040000`；
`Mems_allowed_list=0-1` 是 job allowance，实际 policy 与 file placement 由 numactl/numa_maps gate
裁决，见 [TNO0149](./TNO0149_stage33_numa_symmetry_and_quiet_window_recheck_20260719.md)。

## 4. Function absolute values

| guest stop | instr/cycle | guest cycle | Host time | emu pages N0/N1 | NEMU pages N0/N1 | result |
| ---: | --- | ---: | ---: | --- | --- | --- |
| `100` | `0 / 96` | `101` | `194 ms` | short-run | short-run | PASS |
| `10,000` | `458 / 9,996` | `10,001` | `9,509 ms` | `21,257 / 0` | `115 / 0` | PASS |
| `50,000` | `73,580 / 49,996` | `50,001` | `74,459 ms` | `21,257 / 0` | `115 / 0` | PASS |

三轮均只有一个正 `Host time spent`，无 mismatch/assert/fatal/error/bad trap；run status 均为
0（exit0），placement/function/affinity gate 均为1。100 太短，明确只复用同一 first-touch
inode，不伪造 live numa_maps。

raw log：

| guest stop | SHA256 | bytes |
| ---: | --- | ---: |
| `100` | `238c94a6e8add76dc5db343ed63a76aefa3ca4d7194c034bac3103b49f562b66` | `625` |
| `10,000` | `df93cb5f6d69fdec0289a82248681542719d2bca4dae2bfea1c1311c15d0365c` | `763` |
| `50,000` | `2dfeadd20f28df29e4ca507f95bab7de0d1d72e47da762cef4c53064552b36df` | `965` |

10k/50k placement TSV 相同，SHA256
`72a8df9186e43fdf0404f1bb16a3e956a80faecc058ff6d0fdee791ba5276488`、bytes=`23`。

## 5. Performance boundary

strict 50k 的 `74,459 ms` 与历史 current-default 样本数值接近，但它不是 balanced A/B，不能
据此计算或宣称收益。后续必须：

1. 在实际 committed Stage33 code 上 fresh emit/O3/link current C++ default control；
2. control/strict 在每个 node 使用各自新建、互不复用的 first-touch inode；
3. 每样本通过 30 秒 whole-node pre-gate、运行期 monitor、placement/PMU/scheduler/ASLR/功能；
4. 完成双 NUMA ABBA/BAAB，最终只按 absolute `Host time spent` 裁决默认。
