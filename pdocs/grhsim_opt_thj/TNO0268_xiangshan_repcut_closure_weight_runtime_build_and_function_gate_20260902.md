# TNO0268: XiangShan RepCut closure-weight runtime build and function gate

日期：2026-09-02

状态：`BUILT; C=100 FUNCTIONAL PASS; DEFAULT UNCHANGED`。

## 1. 结论

[TNO0266](./TNO0266_xiangshan_repcut_closure_weight_k32_static_ab_20260901.md) 的
`closure-aware` K32 assignment 已物化为完整 RepCut JSON、split SV、partitioned package 和
XiangShan ELF。candidate 重新运行得到的 HGR、raw assignment、effective assignment SHA-256
与 TNO0266 冻结值完全相同；baseline 复用了与当前 baseline assignment 相同的 v7 package，
并在本轮重新链接 ELF。

两侧最终 ELF 均通过 `C=100, N=1`：返回码 0、difftest/cycle-limit 端点一致、thread config
为 `requested=1/effective=1/max_parallel=32/available_cpus=1`，timing JSONL 均为 302 steps、
36 条 schema-v1 record。没有拆分大 ASC，没有改变 RepCut 默认 mode；N=1/C=10000 的
运行时对照独立记录于
[TNO0269](./TNO0269_xiangshan_repcut_closure_weight_n1_partition_runtime_diagnostic_20260902.md)。

## 2. 冻结输入与工具身份

| 项目 | 值 |
| --- | --- |
| 原始 GRH JSON | `build/xs/wolf/wolf_emit/xs_wolf.json` |
| 原始 JSON SHA-256 | `82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba` |
| 原始 JSON 大小 | `3,427,740,706 B` |
| top / K | `SimTop / 32` |
| epsilon / preset / seed | `0.015 / deterministic-quality / 0` |
| Wolvrix HEAD | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| nested diff SHA-256 | `985b7cf0a727ad636df411006896a88e103ce4ecf6aeddfa628ac668e61fc3e9` |
| `_wolvrix.so` SHA-256 | `86eb9b354156c8bd6830d16a166b205cbd029bccf9a24237ecb2687869030f91` |
| `libwolvrix-lib.so` SHA-256 | `a97bb01351df3ed0a4b84a657435eb07c6cda9624ee202ce2b0258ae6aa65ac7` |
| Verilator | `5.048 2026-04-26 rev v5.048` |
| compiler | `Ubuntu clang 19.1.1` |
| build runner SHA-256 | `2ad2e1d7042828cdabf2f8ff5d0eaab4c84365c2425ba3bb41d569822e32de89` |

源码 HEAD、diff、Python extension 和 native library 在 candidate generation 前及两侧 build
后均保持不变。

## 3. assignment 与生成物身份

### 3.1 baseline

当前 static A/B 的 baseline `.part32` SHA 为：

```text
c2712f03b0ed58f23db1b49be1f3809d35b4abb290415abc88ed0a3044f308f3
```

它与 `build/repcut_fix_20260825/generated-v4/work/SimTop_repcut_k32.hgr.part32`
逐字节相同；v7 package 正是从该 frozen baseline RepCut JSON 再发射得到，且当前 emitter 的
SV/package 源码身份仍与 v7 相同。因此本轮没有再次保存一份 3.68 GB baseline JSON，而是复用：

| artifact | SHA-256 |
| --- | --- |
| frozen RepCut JSON | `5bbe6f8eaffedf136529535fe7eab722c0bd7d5c71282f57fb161b7ad2d4fff6` |
| `SimTop.sv` | `71994d1cd618f087273735c7284860ecd25edae9dca02d842e62d73246c6f364` |
| package `units.mk` | `c73e12f63e40f81aab6b6310dd69d6f9f03714ca5a21aaae65ac4e28450211a3` |
| package common C++ | `eedcf24c79e7f7dfcbff055bd57a7a97868676667dd0e9d71c8222e13189904f` |

这个复用证明的是 assignment、旧 frozen JSON、emitter/package 入口一致；它不是“2026-09-02
fresh baseline JSON 再发射后逐文件 tree hash 相同”的额外实验。该 provenance 非对称在
TNO0269 的证据边界中保留。

### 3.2 closure-aware

candidate 在 node033 重新执行完整 transform/store-json/roundtrip/SV/package 流程：

| artifact | SHA-256 |
| --- | --- |
| HGR | `f48e4156022f2d94d848c39674f31f4c66a1637f6ea66968e2e52251abf5aae0` |
| raw `.hgr.part32` | `aa4745967a588a4bc446308a698150bd5cb84fdc0a3c4ad0ddb34b59ad781de8` |
| effective `.hgr.closure-aware.part32` | `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589` |
| RepCut JSON | `1f20f4bca4356d3a5e9027d01da505e23e57c093d6bea8b1f748384dcf179c49` |
| `SimTop.sv` | `0f5b4f041bdd6c57736e00b115c4ce5aba2b591a341716a9a6babd59ec6a6153` |
| package `units.mk` | `c73e12f63e40f81aab6b6310dd69d6f9f03714ca5a21aaae65ac4e28450211a3` |
| package common C++ | `eedcf24c79e7f7dfcbff055bd57a7a97868676667dd0e9d71c8222e13189904f` |

candidate JSON 为 `3,845,597,231 B`。generation `/usr/bin/time -v` 为 wall `8:43.33`、
max RSS `52,503,248 KB`、exit 0；它只描述生成资源，不是仿真性能。

两侧 `units.mk` 和 common runtime C++ 相同，说明 partition count、unit naming 和调度 wrapper
入口没有变化；`SimTop.sv`、各 unit RTL/C++ 和最终 ELF 按 assignment 改变。

## 4. 构建结果

第一次远程 build 均失败于环境前置条件，而非 RTL/代码错误：非交互 SSH 没有继承
`VERILATOR_ROOT`，Difftest 形成了错误的 `/include/verilated.h` 与
`/include/verilated.cpp` 路径。失败目录和 `compile.{stdout,stderr,time}` 原样保留。

runner 随后显式冻结：

```text
VERILATOR=/nfs/home/tanghaojin/verilator/bin/verilator
VERILATOR_ROOT=/nfs/home/tanghaojin/verilator
CC=clang
CXX=clang++
```

attempt 2 的结果：

| mode | build host | wall | max RSS | ELF size | ELF SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| baseline | `node030` | `8.91 s` | `535,200 KB` | `261,042,736 B` | `0c41ed948b4d6a3abded47e91a0069537b935fe7dce2537ebe3888ef589c02a2` |
| closure-aware | `node033` | `49.15 s` | `763,952 KB` | `270,068,888 B` | `4b865c225815e72aea5c87caba0f2ffcdeebab4491e296ed91b62f536ea0bb9b` |

两个 build 使用已生成 package 中不同程度的中间产物复用，wall 不可比较，也不进入性能结论。
运行 runner 在每个样本启动和结束时重新计算实际 ELF target SHA，均与上表一致。

## 5. C=100 功能门

最终用于 TNO0269 的 node038/CPU80 diagnostic pair 中，两侧 C=100 均首次通过：

| mode | rc | terminal PC | instr / cycle / guest | timing steps / records | Host time |
| --- | ---: | --- | --- | --- | ---: |
| baseline | 0 | `0x0` | `0 / 96 / 101` | `302 / 36` | `1,021 ms` |
| closure-aware | 0 | `0x0` | `0 / 96 / 101` | `302 / 36` | `1,110 ms` |

共同 thread config：

```text
[WOLVI][thread-config] requested=1 effective=1 max_parallel=32 available_cpus=1
```

日志无 assertion、abort、bad trap、difftest mismatch、runtime error/fatal/segfault。C=100
Host time 只做启动 sanity check，不比较性能。

## 6. 决策

- build/function gate 通过，可以评估 N=1 per-part timing；
- 默认仍为 `baseline`，本轮没有修改生产代码；
- baseline frozen package 的复用 provenance 已显式披露，不外推为 fresh tree byte identity；
- 大 ASC 拆分不在本轮；
- N=1 runtime 结果和 strict/shared-host 限制见 TNO0269。

## 7. 勘误与 clean-v4 增量更新（2026-09-02）

### 7.1 attempt 2 的跨 arm runtime 身份无效

独立对象级审计发现，第 4 节 attempt 2 虽然都由外层 Difftest 重新链接，但 baseline
package 内保留了 2026-08-25 的 `build/verilated` 缓存：其中 partition `.o/.a` 的
`.comment` 为 Clang 21.1.5；closure-aware package 的对应对象则为 Ubuntu Clang 19.1.1。
因此 baseline attempt-2 ELF 同时包含 Clang 19/21 标记，candidate ELF 只包含 Clang 19。

这意味着第 4 节两个 attempt-2 ELF 不能作为分区方案 runtime A/B 的共同基线。由它们产生的
`build/repcut_closure_runtime_20260902/results/` 和 `results-v2/` 全部跨 arm runtime
差值均标记为 **INVALID**，包括旧的 Host time、`eval` sum/max 和 CV；不能只加 caveat 后继续
引用。第 5 节的旧 C=100 只保留为当时二进制各自的功能 sanity，下面的 clean-v4 功能门已将其
完整替代。

assignment、emitter 和 package 顶层生成源的审计仍然成立：baseline assignment 为
`c2712f03...`，closure-aware effective assignment 为 `ffefbb1d...`；两套 package 的
Makefile/header/common/eval/units 等共同入口逐字节一致，load/update 随 assignment 变化。
错误发生在生成源之后的编译缓存层，不推翻 TNO0266 的静态 A/B。

### 7.2 无缓存 clean-v4 构建

修复方式不是清理或覆盖旧 package，而是把两侧 package 的生成源复制到新的 staging 目录，
明确排除 `build/`，并把 32 个 filelist 重写为 staging 内路径。随后在 node030/node033 分别
从零执行 Verilate、partition object 编译和 ELF 链接，统一冻结：

```text
CC=/nfs/home/tanghaojin/LLVM-21.1.5-Linux-X64/bin/clang
CXX=/nfs/home/tanghaojin/LLVM-21.1.5-Linux-X64/bin/clang++
VERILATOR=/nfs/home/tanghaojin/verilator/bin/verilator
VERILATOR_ROOT=/nfs/home/tanghaojin/verilator
```

`clean-v3` 首次尝试因远程环境没有 `rg`，检查脚本前置条件不完整而中止；该目录没有 build
manifest，不进入任何运行。脚本改用系统 `grep` 后，以新的 `clean-v4` 路径重做：

| mode | host | wall / max RSS | partition `.o` | ELF size | ELF SHA-256 |
| --- | --- | --- | ---: | ---: | --- |
| baseline | `node030` | `2:49.47 / 6,248,684 KB` | 1,386 | 261,042,608 B | `355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77` |
| closure-aware | `node033` | `1:57.79 / 5,244,800 KB` | 1,422 | 269,966,456 B | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` |

对象审计逐个读取 1,386/1,422 个 partition `.o` 的 `.comment`；两侧各 47 个外层 runtime
`.o` 也独立复核。所有对象和两个最终 ELF 的唯一 Clang marker 都是
`clang version 21.1.5`，没有第二个 Clang 版本。构建身份为：

| artifact | baseline | closure-aware |
| --- | --- | --- |
| assignment SHA-256 | `c2712f03b0ed58f23db1b49be1f3809d35b4abb290415abc88ed0a3044f308f3` | `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589` |
| staged source inventory SHA-256 | `b14ea4cbb0b16cd23a100f519ef43b94d0cc77e5d9f97923dec27c7ff6fc9d2a` | `41987274d66580208d8d47bb1277d6b7b2e57451387317779390a6b30737678b` |
| build manifest SHA-256 | `f52633e1d753b5da2219e96f58f734134a7e750616f8a4e4f65bd0375514d605` | `c1489ae14dbe564f57598f7093431e9842c5d2187dbeca3a3bc752cd343c90d2` |

clean build runner SHA-256 为
`a56cee47f7b3d8d93ee6d47b558c5ea38d66ad1f8df796c8b40421512a0cc964`。
manifest 同时绑定 assignment、staging inventory、绝对工具链和最终 ELF；runtime runner
启动前强制校验 manifest path/size/SHA，运行前后再次校验 ELF SHA。

### 7.3 clean-v4 C=100 功能门

最终 node033/CPU104 的 AB 和 BA 两序各自先运行两侧 C=100，四个样本均首次通过：

| order | mode | rc | Host time | timing steps / records / parts |
| --- | --- | ---: | ---: | --- |
| AB | baseline | 0 | 1,066 ms | 302 / 36 / 32 |
| AB | closure-aware | 0 | 1,332 ms | 302 / 36 / 32 |
| BA | closure-aware | 0 | 1,275 ms | 302 / 36 / 32 |
| BA | baseline | 0 | 1,029 ms | 302 / 36 / 32 |

四者终点均为 `terminal_pc=0x0`、`guest_cycles=101`、`cycle_count=96`，thread config 均为
`requested=1/effective=1/max_parallel=32/available_cpus=1`。C=100 只作为功能门，不用于
性能比较。clean-v4 的 N=1 C=10000 结果见
[TNO0269](./TNO0269_xiangshan_repcut_closure_weight_n1_partition_runtime_diagnostic_20260902.md)。

因此，本文最终状态应读作：**clean-v4 fresh build and C=100 functional gate PASS；attempt-2
cross-arm runtime INVALID；默认 mode 仍未改变。**

链接勘误：第 7.3 节末尾的 TNO0269 正确文件名为
[TNO0269](./TNO0269_xiangshan_repcut_closure_weight_n1_partition_runtime_diagnostic_20260902.md)。
