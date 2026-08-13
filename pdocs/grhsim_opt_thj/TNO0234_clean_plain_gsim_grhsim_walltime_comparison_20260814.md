# TNO0234：clean plain GSIM/GrhSIM SimTop 50k walltime 对比

日期：2026-08-14

## 1. 结论

基于 [TNO0233](./TNO0233_clean_rtl_gsim_plain_rebuild_and_correction_20260813.md)
从 Scala/Chisel 全新生成的同一套 RTL，本轮重新发射并全量编译当前 Wolvrix 默认
GrhSIM；GSIM 与 GrhSIM 两边均为普通 `-O3`，没有 PGO 或 BOLT。node032 同 CCD
ABBA+BAAB 的正式 SimTop 50k pooled walltime 为：

| 引擎 | walltime | 相对 GSIM |
| --- | ---: | ---: |
| clean GSIM plain | **`30,643.00 ms`** | baseline |
| clean current-default GrhSIM plain | **`42,837.25 ms`** | **慢 `12,194.25 ms/39.794570%`** |

等价地，GrhSIM 本轮吞吐为 GSIM 的 `0.715335x`。该结果修正了 TNO0232 中由污染
GSIM plain 导出的旧 plain 横向对比；当前 clean plain 条件下，性能差距约为 `40%`，
不是旧记录中的 `154%` 量级。

## 2. 构建边界与身份

构建在 node030 完成，每条命令前均 source parent `env.sh`。源码身份为：

| 项目 | 身份 |
| --- | --- |
| parent | `3d9f2359aa0921ae8420ef1cd4d6d55308f09b79` |
| Wolvrix | `79ec2037b00f2d4894d72785277ebe3f5d37782d` |
| fresh RTL root | `/tmp/gsim_plain_rtl_clean_node030_20260813_2041` |
| fresh `SimTop.sv` SHA-256 | `15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559` |
| 2097-file RTL manifest SHA-256 | `2819766b19acd0be1d1822effdf9cef674a95156d24b8cd5650021912958c0d1` |
| fresh `DifftestMacros.svh` SHA-256 | `914e3168bd8de5a08e4ad1ba086e697ba61242d3ae2c49cb21b503c69a4b2faf` |

GrhSIM 没有复用旧 emitted C++、`.o` 或 ELF。`xs_wolf_grhsim_emu` 的
`XS_RTL_BUILD` 和 `XS_DIFFTEST_GEN_DIR` 显式指向上述 fresh RTL/generated-src，
resume-from-JSON 为 `0`，waveform/perf instrumentation 为 off。发射使用的近期隔离
Python 安装来自 typed-state `full_native_bool_values` 工作区；其 emitter 源与当前
Wolvrix HEAD 逐字节一致：当前及该工作区 `lib/emit/grhsim_cpp.cpp` SHA-256 均为
`88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164`。

新模型目录包含 `132` 个 `.cpp`、`132` 个 `.o`，生成源码 manifest SHA-256 为
`282c8fc2e5f20aa54243f3c922eb5db0552c67d362cf39b9f1d51ee4d044c7d5`。
构建日志中恰有 `132` 条模型编译命令，全部为：

```text
clang++ -std=c++20 -O3 ... -c grhsim_SimTop*.cpp
```

`fprofile`、`llvm-profdata`、`llvm-bolt`、`perf2bolt`、`profraw`、`profdata`、
`fdata` 的日志命中为 `0`；private build root 内对应 profile/BOLT 文件数为 `0`，
ELF 也没有 `llvm_prf/bolt` section。最终二进制为：

| 引擎 | 大小（bytes） | SHA-256 | Build ID |
| --- | ---: | --- | --- |
| clean GSIM plain | `56,352,168` | `b07e23b2f6be7d26873583026522e84dcd48492d37a79a2b21d380525ec375a3` | `47b4958a23ea3b7d652fba54710dff54f3ebdb7e` |
| clean GrhSIM plain | `83,726,448` | `4d950aa65ba348f5d5b99d6b7fd607ad545890ed87240d5086cba06f83990c51` | `7bdbbd7f580051c7537df967bdfa2b5030fc6a09` |

## 3. 正式 walltime

测试输入沿用同一份 CoreMark/NEMU，SHA-256 分别为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` 和
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
正式入选轮固定 placement 为：

```text
CCD: node0:88-95,280-287
target CPU: 88
SMT sibling: 280
helper CPU: 96
NUMA node: 0
```

ABBA 与 BAAB 复用同一 placement；每样本关闭 ASLR，并保留正式 runtime 的 quiet
CCD、live-process、NUMA locality、连续负载、PMU scheduling 和 migration 门禁。

| 顺序 | GSIM samples (ms) | GrhSIM samples (ms) | GSIM mean | GrhSIM mean | GrhSIM 慢 |
| --- | --- | --- | ---: | ---: | ---: |
| ABBA | `30,804`, `30,775` | `42,876`, `43,153` | `30,789.50` | `43,014.50` | `39.705094%` |
| BAAB | `30,449`, `30,544` | `42,562`, `42,758` | `30,496.50` | `42,660.00` | `39.884905%` |
| pooled | `30,804`, `30,775`, `30,449`, `30,544` | `42,876`, `43,153`, `42,562`, `42,758` | **`30,643.00`** | **`42,837.25`** | **`39.794570%`** |

ABBA/BAAB order gap 为 `0.179811 pp`，低于 `0.25 pp` 正式门槛。八个正式样本
全部满足：

- GSIM 功能签名 `instrCnt=73584/cycleCnt=49998/PC=0x8000131e`；
- GrhSIM 功能签名 `instrCnt=73580/cycleCnt=49996/PC=0x80001312`；
- guest cycle 均为 `50001`，负向日志为零，每样本恰有一个正 walltime；
- personality 均为 `00040000`，allowed CPU 仅 `[88]`，migration 均为 `0`；
- binary/NEMU NUMA local ratio 均为 `1.0`；
- PMU event 与 task-clock scheduled percent 均为 `100%`；
- 最低 pre-gate mean/min idle 为 `99.916875%/99.33%`；
- 最低连续监控 mean/min idle 为 `99.933333%/99.64%`；
- 最大 context switches 为 `5.448761/s`，低于 `20/s` 门槛。

GSIM 与 GrhSIM ELF footprint 不同，因此仅将不适用于跨引擎的绝对 binary 页数
下限改为 `min_binary_coverage=1e-6`；local ratio、NEMU minimum pages、功能、
ASLR、CPU/CCD、连续负载和 PMU 门禁均未放宽。

## 4. 复测历史与结果边界

脚本按“首个完整 same-CCD ABBA+BAAB 且 gap `<0.25 pp`”选择正式轮：

| 轮次 | 状态 | GSIM mean | GrhSIM mean | GrhSIM 慢 | order gap |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | 完整但 gap 超线 | `30,941.00` | `43,383.75` | `40.214440%` | `0.384279 pp` |
| 2 | 作废 | - | - | pre-gate 外部负载 | - |
| 3 | 作废 | - | - | continuous min idle `92.06%` | - |
| 4 | 完整但 gap 超线 | `30,812.75` | `43,169.75` | `40.103529%` | `0.323231 pp` |
| 5 | **正式入选** | **`30,643.00`** | **`42,837.25`** | **`39.794570%`** | **`0.179811 pp`** |

三轮完整结果均落在 GrhSIM 慢 `39.79%..40.21%` 的窄区间，结论对轮次选择不
敏感。测量过程通过 benchmark lock 与正在运行的 SimpleTES evaluator 串行，未停止、
重启或改动 auto research；结束后 launcher/main 仍在运行。临时跨引擎适配层只增加
双引擎功能签名识别，没有修改 SimpleTES 源码或后续研究基线。
