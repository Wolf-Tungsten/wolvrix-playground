# TNO0255：g158 fresh build 与功能回归

日期：2026-08-27

## 1. 阶段结论

对当前默认生成配置分别建立了 baseline 和 g158 landed 两套完全隔离的
Wolvrix/生成输出。两套构建使用同一份冻结 RTL、generated-src、XiangShan
输入、编译器和构建参数；只有 g158 物理 state-storage 声明顺序发生变化。
两套产物均完成 fresh `187/187` Ninja build、focused `29/29` 测试以及
100/10000 cycle 功能门禁，未发现语义回归。50k walltime 尚不在本文预填，
正式结果另见后续增量记录；此前因共享节点负载作废的 attempt 不作为性能结论。

## 2. 源码与输入身份

| 项目 | baseline | g158 landed |
| --- | --- | --- |
| parent commit | `42c43ef6742be64c79c2bd3bb8c3de092f93ac16` | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| Wolvrix commit | `cedf61048d3b8873702e6db1120a386ecbf474f5` | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| XiangShan gitlink | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` | 同左 |
| generation input fingerprint | `1e00edec4bd3d6dc449a4970e35399a0a14ac7f484b728885b0f49cf8546c5d2` | 同左 |
| frozen RTL fingerprint | `bcbc10f8f0f0c7dbd466ba5b1e4c2c70913097a2d12c5572ede55deed4643738` | 同左 |
| generated fingerprint | `8e45aad743534def83267cfd8f97148e16c0fc4c286d51f635751324203aabe9` | `0931d22011907b96bb3f3019da23eec6a6df0689b503c7766f54262c22a55da6` |

输入冻结清单为 2104 个 regular files：RTL 2097 个（244,285,492 bytes），
generated-src 7 个（215,617 bytes）。其中 `SimTop.sv` SHA-256 为
`15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559`，
`DifftestMacros.svh` SHA-256 为
`914e3168bd8de5a08e4ad1ba086e697ba61242d3ae2c49cb21b503c69a4b2faf`。
完整输入身份和冻结副本说明保存在
`build/grhsim_g158_landing_20260827/input_identity.json`。

## 3. 构建环境与固定参数

构建在 node032（AMD EPYC 9684X 96-Core Processor，Linux 6.8.0-137-generic）
完成。两边均使用 Release/Ninja、`-O3`，并关闭 waveform、perf、resume/stats、
PGO 和 BOLT；`WOLVRIX_ENABLE_MT_KAHYPAR=OFF`、`WOLVRIX_ENABLE_LIBFST=OFF`。
顶层 evaluator 固定的 build-config fingerprint 为
`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`，
toolchain fingerprint 为
`7669097de01707e2fab9a40ae7b308617c33dece545dcc5a6e0d38be217b98bc`。

需要明确区分 jobs：顶层 evaluator assignment 是 `XS_VM_BUILD_JOBS=4`，
但 XiangShan/GrhSIM nested model make 的实际日志为
`VM_BUILD_JOBS/GRHSIM_MODEL_BUILD_JOBS=64`。baseline 与 landed 完全相同，
因此不影响 A/B 公平性；build fingerprint 只表示 evaluator 的固定 assignment，
不把整条 nested make 链误称为 `-j4`。

## 4. 产物与生成差异

产物快照位于 `build/grhsim_g158_landing_20260827/snapshots/`，每个目录都有
`provenance.json`、`SHA256SUMS`、regular ELF 和输入映射。两边的公共产物
`coremark.bin` 为 16,712 bytes、`nemu.so` 为 567,504 bytes；对应 SHA-256
分别为 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` 和
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

| 产物 | baseline | g158 landed |
| --- | --- | --- |
| `emu` bytes | 83,705,968 | 83,517,552 |
| `emu` SHA-256 | `4d2fb3e07820637432c958d8ea7c221cf78827b7a51b02e3d38c674eb3a05b8b` | `d087bcf7e5203c0f4aa9fd4e906521365b2ab3db07cd6ccb377eb73a5135d6b7` |

每边 emitted C++/header 共 134 个文件、总计 1,276,448,695 bytes；逐文件
比较显示只有 `grhsim_SimTop.hpp` 内容不同，其余 133 个文件（包括 schedule
和 stats JSON）逐字节相同。两边 `state_logic_storage_t` 均有 208,964 个字段，
字段 multiset 完全一致且无重复；差异仅为 g158 排序后的物理声明顺序。这与
实现边界一致：不改变 field name/type/index、schedule、guard、event 或
materialized value，也不读取 SimTop/benchmark 名称或 `targeted-direct`。

## 5. 功能门禁

- 两套 fresh build 均为 `187/187` steps，exit code `0`。
- 两套 focused test log 均为 `Ran 29 tests ... OK`。
- C=100 gate：`rc=0`，counter `cycleCnt=96`、guest cycle `101`，无 diff 错误。
- C=10000 gate：两边均 `rc=0`，`instrCnt=458`、`cycleCnt=9996`、guest cycle
  `10001`，终止 PC 同为 `0x800027c6`，无 diff 错误。

100/10000 的 host wall 只用于功能门禁（baseline 10000 为 4421 ms，landed
为 4209 ms），不作为 50k 性能结论。正式性能必须在运行时关闭 ASLR（使用
`setarch x86_64 -R`）、通过 whole-CCD/NUMA/PMU gate，并以同一 placement 的
ABBA+BAAB walltime 作为唯一 headline。

## 6. 可复核文件

- `build/grhsim_g158_landing_20260827/build_summary.json`
- `build/grhsim_g158_landing_20260827/input_identity.json`
- `build/grhsim_g158_landing_20260827/snapshots/baseline_control/`
- `build/grhsim_g158_landing_20260827/snapshots/g158_landed/`
- `build/grhsim_g158_landing_20260827/build_logs/`

SimpleTES 已在独立提交 `d1b689608751faf757ffd7c3eafc322f5d4e37eb` repin 到
parent `6e2436e`/Wolvrix `054c6a7`；bench focused `82 passed`，但本记录不启动
新的 auto research。后续 runtime 记录会单独记录 node/CCD、ASLR、每个样本的
绝对 walltime、ABBA/BAAB gap 及是否采纳。
