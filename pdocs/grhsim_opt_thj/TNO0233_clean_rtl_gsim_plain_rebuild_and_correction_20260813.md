# TNO0233：从 RTL 干净重建 GSIM plain 与旧对照勘误

日期：2026-08-13

## 1. 结论

本轮按要求不复用旧 FIR、GSIM C++、对象文件、profile 或 generated-src，先从
XiangShan Scala/Chisel 重新 elaboration 出 `SimTop.sv` 和 `SimTop.fir`，再由
GSIM 重新生成并编译全部 `332` 个模型 C++。最终 clean plain SimTop 50k 的
node032 正式 pooled walltime 为 **`30,907.75 ms`**。

这同时推翻了 [TNO0232](./TNO0232_pgo_toolchain_and_plain_crosscheck_20260813.md)
里把旧 `17,032.25 ms` 产物认作真正 plain 的结论。旧所谓 GSIM plain 目录在
构建前已经包含 PGO 阶段生成的 `332` 个 `.o`；其 build log 只重编了 `41` 个
harness/common 对象，模型对象重编数为 `0`。旧 plain 的 `SimTop0.o` 与 PGO
目录逐字节相同，两个完整 model 目录 `diff -qr` 也为零差异。因此旧产物实际是
“PGO model objects + plain harness”，不能用于 plain/PGO 收益判断。

本轮 clean plain 与历史 PGO 同 CCD 对照为 `30,907.75→16,954.75 ms`，历史
PGO 数值快 `13,953.00 ms/45.144017%`。但是 fresh elaboration 产生的模型源码
与历史 PGO 源码不完全相同，所以这个百分比只作为跨构建端到端观察，**不能归因
为 PGO 的纯收益**。要回答 PGO 自身收益，必须基于本轮同一份 clean model C++
分别全量编译 plain 与 instrumentation-PGO。

## 2. 干净构建边界

构建机为 node030；每条命令先执行：

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
```

源码和工具身份：

| 项目 | 身份 |
| --- | --- |
| parent | `bc2ea41fba8f68d775e9927b34b90f68d332f9d6` |
| XiangShan | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` |
| GSIM | `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a` |
| GSIM version | `master-3b19dc1-7-ga3ecb26` |
| compiler | Ubuntu Clang `19.1.1` |
| private root | `/tmp/gsim_plain_rtl_clean_node030_20260813_2041` |

GSIM 本身消费 FIR 而不是直接消费 SystemVerilog。这里“从 RTL 开始”的严格含义
是先运行 XiangShan 的 `sim-verilog`，从 Scala/Chisel 设计重新生成 RTL 和 FIR，
然后才把新 FIR 交给 GSIM：

```bash
env -u LLVM_PROFILE_FILE -u MAKEFLAGS -u CCACHE_DIR -u SCCACHE_DIR \
  NOOP_HOME=/tmp/gsim_plain_rtl_clean_node030_20260813_2041/noop \
  make -B -C testcase/xiangshan sim-verilog \
    BUILD_DIR=/tmp/gsim_plain_rtl_clean_node030_20260813_2041/rtl \
    CONFIG=TLConfig ISSUE=E.b NUM_CORES=1 RTL_SUFFIX=sv GSIM=1
```

然后在另一个全新目录执行 `make ... emu`，输入只指向上述新 RTL/FIR 和 private
`NOOP_HOME`。关键显式配置为：

```text
GSIM=1 GSIM_CXX=clang++ EMU_OPTIMIZE=-O3
PGO_WORKLOAD= PGO_CFLAGS= PGO_LDFLAGS= PGO_BOLT=0
LLVM_PROFDATA= LLVM_BOLT= GSIM_EMIT_RUNTIME_PROFILE=0
```

构建过程由 `strace -ff -e trace=execve` 留存。execve 记录确认 `332/332` 个
`SimTop*.cpp` 各自调用了 Clang，另外编译 `41` 个非模型对象，最终共生成
`373` 个 `.o`。抽查 `SimTop0.cpp` 与 `SimTop331.cpp` 的实际命令均为 `-O3`，
无 `-fprofile-generate` 或 `-fprofile-use`。

## 3. 产物与无 PGO 证明

| 产物 | 大小（bytes） | SHA-256 / Build ID |
| --- | ---: | --- |
| fresh `SimTop.sv` | `1,587,569` | `15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559` |
| fresh `SimTop.fir` | `2,049,803,936` | `2368d73a8068e0e728803b36ef217d954d7ab467aa0507973acd4b9a9a43814e` |
| clean GSIM plain ELF | `56,352,168` | `b07e23b2f6be7d26873583026522e84dcd48492d37a79a2b21d380525ec375a3` |
| clean ELF Build ID | - | `47b4958a23ea3b7d652fba54710dff54f3ebdb7e` |

`SimTop.sv` SHA 与此前基准一致，说明 RTL 语义输入没有漂移。clean ELF 比旧混合
plain 的 `78,273,960 bytes` 小 `21,921,792 bytes`。完整 build log 和 execve
trace 中下列模式命中数均为 `0`：`-fprofile-generate`、`-fprofile-use`、
`llvm-profdata`、`llvm-bolt`、`perf2bolt`、`perf record`、`ccache`、`sccache`。
private root 内 profile/BOLT 中间产物数为 `0`，ELF 中 `bolt/llvm_prf` section
或 marker 数也为 `0`。

旧产物污染的直接证据为：

| 检查 | 结果 |
| --- | --- |
| 旧 plain model `.cpp/.o` | `332/332` |
| 旧 plain build log 的 model CXX | `0` |
| 旧 plain `SimTop0.o` SHA | `09cce66728f48e83b6cd806343d853c8a1c85fac3e71d7a62a3758ceee8dfdd7` |
| PGO `SimTop0.o` SHA | 同为 `09cce667...8dfdd7` |
| 旧 plain 与 PGO model 目录差异 | `0` |
| fresh clean `SimTop0.o` SHA | `237cf14e6a6e30db7f1223990d74385e5d26e7e4742f94bd5a263e00502d01e2` |

所以旧 plain 与 PGO 的 ELF SHA/Build ID 不同，只能证明最终链接产物不同，不能
证明其模型代码分别由 plain/PGO flags 编译；TNO0232 的身份检查层级不够深。

## 4. 功能回归

node030 上用 `setarch x86_64 -R` 关闭 ASLR 后执行 SimTop 50k。输入身份为：

| 输入 | SHA-256 |
| --- | --- |
| `coremark-2-iteration.bin` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| `riscv64-nemu-interpreter-so` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

功能签名通过：PC `0x8000131e`、`instrCnt=73584`、`cycleCnt=49998`、guest
cycle `50001`，负向日志命中为零。该未门控冒烟的绝对 walltime 为
`30,944 ms`，只作功能佐证，不作为正式性能值。

## 5. node032 正式 walltime

正式测试在 node032 使用动态选择出的同一 placement：

```text
CCD: node0:72-79,264-271
target CPU: 72
SMT sibling: 264
helper CPU: 96
NUMA node: 0
```

ABBA 和 BAAB 始终复用这一 CCD/CPU。每个样本前执行 3 秒 whole-CCD gate，
并使用 `taskset`、`numactl`、`cp --reflink=never` 做目标 NUMA first-touch；
运行通过 `setarch x86_64 -R` 关闭 ASLR。结果如下：

| 顺序 | clean plain (ms) | historical PGO (ms) | plain mean (ms) | PGO mean (ms) | PGO 相对快 |
| --- | --- | --- | ---: | ---: | ---: |
| ABBA | `30,876`, `30,963` | `16,908`, `16,992` | `30,919.50` | `16,950.00` | `45.180226%` |
| BAAB | `30,913`, `30,879` | `16,944`, `16,975` | `30,896.00` | `16,959.50` | `45.107781%` |
| pooled | `30,876`, `30,963`, `30,913`, `30,879` | `16,908`, `16,992`, `16,944`, `16,975` | **`30,907.75`** | **`16,954.75`** | **`45.144017%`** |

双 order 差为 `0.072445 pp`，低于 `0.25 pp` 复测线。8 个样本全部通过：

- 功能签名和唯一正 walltime；
- personality `00040000`、allowed CPU 仅 `[72]`、migration `0`；
- PMU event 与 task-clock scheduled percent 均为 `100%`；
- binary/NEMU NUMA local ratio 均为 `1.0`；
- pre-gate 最低 mean/min idle 为 `99.56375%/95.35%`；
- 连续监控最低 mean/min idle 为 `99.894%/99.2%`；
- 最大 context switches 为 `12.212760/s`，低于 `20/s` gate。

GSIM ELF 页数和 GrhSIM 基准不同，因此本次跨 GSIM artifact 测量仍只旁路了不适用
的绝对页数下限（`min_binary_coverage=1e-6`）；NUMA local ratio、NEMU 页数、
PMU、功能、连续 CCD 与 ASLR gate 均未放宽。

## 6. 可归因边界与后续

fresh 与历史模型的文件名集合都是 `332` 个，但逐文件 SHA 只有 `166` 个相同，
另外 `166` 个不同。raw C++ manifest 分别为：

- fresh clean：`b97918fbd8db204f990aba73a6b9091e1a7aab8080978d332f429c1c081a7552`
- historical PGO source：`63ee8aee6526ac423b0b078ade7c38e5b1a3fd671b73b56e972774b67885c281`

去注释和空白后仍有 `166` 个不同；部分是语句/临时编号次序，部分包含真实的
signal grouping 与 mask 差异。fresh FIR 也不同于历史 FIR 的
`429626c8...4fd57`，尽管生成的 SV SHA 相同。这表明 elaboration/FIR/GSIM
partition 的非确定性会改变 C++ 布局。

因此本记录建立的可靠结论只有两项：本轮 clean default plain 的正式 walltime
是 `30,907.75 ms`；旧 `17 s` plain 无效。它没有建立“PGO 稳定提升
45.144017%”这一因果结论。严格的下一项实验应固定本轮 C++ manifest，从零
分别编译 plain、profile-generate 并训练、profile-use，再做同 CCD
ABBA+BAAB。当前未修改 GSIM/Wolvrix 默认配置、SimpleTES runtime 或正在运行
的 auto research。
