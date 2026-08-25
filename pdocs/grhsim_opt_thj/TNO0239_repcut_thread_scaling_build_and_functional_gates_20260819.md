# RepCut 线程缩放构建与功能门禁

日期：2026-08-19

状态：`BLOCKED`。本记录闭合配置审计和功能门禁；正式 1/2/4/8 线程性能矩阵没有启动。

## 1. 先前构建的配置问题

初轮构建全部返回 `rc=0`，但使用了工作区现成的 `testcase/xiangshan/build/generated-src`。该目录是普通 XiangShan 配置，`DifftestMacros.svh` 定义 `CPU_XIANGSHAN`，接口宽度为 `79263`。

冻结的原始 `SimTop.sv` 并不是这个配置生成的。`build/xs/rtl/time.log` 明确记录原始 RTL 由以下命令生成：

```text
mill ... top.XiangShanSim --config TLConfig --issue E.b --num-cores 1 \
  --difftest-config G --target systemverilog --split-verilog ...
```

因此初轮得到的五个 ELF 只能作为“错误 profile 下的编译诊断”，不能作为性能结果：

| 路径 | 初轮构建 wall | `rc` | 结论 |
| --- | ---: | ---: | --- |
| native `t1` | `13:59.23` | `0` | 配置不匹配，作废 |
| native `t2` | `18:47.38` | `0` | 配置不匹配，作废 |
| native `t4` | `22:23.92` | `0` | 配置不匹配，作废 |
| native `t8` | `29:09.55` | `0` | 配置不匹配，作废 |
| partitioned | `2:29.77` | `0` | 配置不匹配，作废 |

初轮 ELF、命令和资源消耗保留在：

```text
build/repcut_thread_scaling_20260819/build/
build/repcut_thread_scaling_20260819/logs/build/
```

本次没有删除或覆盖这些诊断产物。

## 2. 修正后的 profile 生成

在独立目录重新执行 XiangShan difftest 生成，命令为：

```bash
env NOOP_HOME="$PWD/testcase/xiangshan" make -s \
  -C testcase/xiangshan/difftest difftest_verilog \
  BUILD_DIR="$PWD/build/repcut_thread_scaling_20260819/generated/difftest-src-fresh" \
  RTL_DIR="$PWD/build/repcut_thread_scaling_20260819/generated/xs_wolf_repcut" \
  SIM_TOP=SimTop NUM_CORES=1 CONFIG=G
```

生成命令返回 `rc=0`，耗时 `27.73 s`。修正后的身份是：

| 项目 | 修正值 |
| --- | --- |
| CPU macro | `CPU_DEMO` |
| interface width | `45871` |
| difftest config | `G` |
| target RTL | `build/repcut_thread_scaling_20260819/generated/xs_wolf_repcut` |
| `DifftestMacros.svh` SHA-256 | `a7611839ba3e1c97ed1e7021f0eb4f486cffd99d26de05976eb349ed57d919a5` |
| `difftest-extmodule.cpp` SHA-256 | `89bced135ffa104c5fef5d60299f843ae7c80f14f7801ff5ab8c19a6f802f6b3` |
| `difftest-dpic.cpp` SHA-256 | `812b0c391f046665cf537a0aabe75bc081ecd22959961411956dadbc1422c3c7` |

这组生成源与冻结原始 RTL 的 profile 一致。RepCut JSON、split SV 和 partitioned package 仍沿用 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 冻结的单次生成结果，没有重新切分。

## 3. 修正 profile 下的构建进度

修正构建使用独立根目录 `build/repcut_thread_scaling_20260819/build_freshG`，并按两波并行：第一波为 native `t1/t2` 和 partitioned，第二波为 native `t4/t8`。

截至本记录形成时：

| 配置 | 构建状态 | 说明 |
| --- | --- | --- |
| partitioned | `PASS` | ELF 已生成，`261,051,064` B，构建 `rc=0`，wall `4.25 s`（复用 package/unit 缓存） |
| native `t1` | `RUNNING` | Verilator 前端仍在展开完整 split SV |
| native `t2` | `RUNNING` | Verilator 前端仍在展开完整 split SV |
| native `t4` | `PENDING` | 等第一波结束 |
| native `t8` | `PENDING` | 等第一波结束 |

运行中的构建属于本记录的诊断过程，不改变性能矩阵尚未获得有效样本这一结论。对应日志：

```text
build/repcut_thread_scaling_20260819/logs/build_freshG/
```

## 4. 功能门禁结果

### 4.1 初轮短 smoke

初轮 `canary_fixed_numactl` 的 100-cycle native `t1/t2/t4/t8` 均能返回 `rc=0`，但终止原因为 `EXCEEDING CYCLE/INSTR LIMIT`，guest cycles 为 `101`、instruction count 为 `0`；严格功能 gate 被显式标记为 skipped。这些只证明 launcher/ELF 能启动，不能证明 CoreMark 功能正确。

初轮唯一尝试的 native `t1` 10k canary 三次均以 `rc=139` 结束，NEMU 栈落在 `map_read -> isa_fetch_decode`，且运行期 CPU admission 受到外部负载污染。因此不纳入任何性能统计。

### 4.2 修正 profile 的可复现 probe

使用修正后的 G profile、partitioned ELF、CPU 176/NUMA 1、`--no-diff -C 1000` 运行一次 probe，结果如下：

| 字段 | 结果 |
| --- | --- |
| exit code | `1` |
| assertion | `build/xs/rtl/rtl/ExuBlock.sv:908` |
| terminal | `ABORT at pc = 0x0` |
| `cycleCnt` | `605` |
| guest cycle | `609` |
| host time | `5425 ms`（到失败为止，非成功运行时间） |
| critical error | `csr_dbltrp_inMN` at simulation time `608` |
| step timing | `steps=1318`, total `5416.670 ms` |

原始日志和 timing JSONL：

```text
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_g_c1000.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_g_c1000.timing.jsonl
```

同一 `csr_dbltrp_inMN`/`ExuBlock.sv:908` 失败在此前错误 profile 的 native/partitioned probe 中也出现过。现在用正确 `CPU_DEMO` profile 重现，说明 profile 偏差不是唯一阻断；当前单次 RepCut 变换结果自身仍未通过功能门。

## 5. 结论与停止条件

1. 初轮五个成功编译的 ELF 因 profile 不匹配作废。
2. profile 修正已完成，partitioned 构建已成功；native 线程构建正在继续留存诊断证据。
3. 正确 profile 下的短程 probe 在 cycle 605 触发 assertion，因此 30,000-cycle 正式运行没有启动。
4. 在 assertion 修复并重新冻结 RepCut 输出前，不能把任何 `Host time spent`（包括失败前的 `5425 ms`）写成 1/2/4/8 线程性能。

要恢复正式矩阵，必须重新通过：正确 G profile、五个独立构建、八个配置的 100-cycle/10k canary、静默/NUMA admission，然后才执行 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 规定的 32 个正式样本。

## 6. 增量更新（2026-08-19 19:45）

### 6.1 五个正确 profile 构建均完成

第二波构建已结束，五个 ELF 均为 `rc=0`。构建仍然只作为 gate/诊断，不是仿真运行性能：

| 配置 | wall | max RSS (kB) | ELF 大小 | ELF SHA-256 |
| --- | ---: | ---: | ---: | --- |
| native `t1` | `13:21.20` | `35,300,224` | `190,122,952` B | `2b7b3194f7862705d1d35c3938c06fda92240f621d934c79a69cad2dacc9b514` |
| native `t2` | `17:45.16` | `56,193,100` | `191,017,128` B | `1c2d3aa62a513987a928108284540ddb0337430ab095b62c0eafc098c5aa23fe` |
| native `t4` | `23:14.63` | `91,708,580` | `191,239,848` B | `1cc1da29e59901299d61defe08578dd0a51857b5207e9d02fc376314cc119d22` |
| native `t8` | `28:35.93` | `133,109,228` | `191,477,464` B | `90d74e513d9498a8e503ba9b784dd19e69a07e74fce695e042b67c903fc9d7f3` |
| partitioned | `0:04.25` | `476,456` | `261,051,064` B | `d2b79dcfc2a14b39afbf1cccc059312812127263004dbbfe81c125d9b205e345` |

`native t8` 的 SHA 以构建目录中的最终 ELF 为准；完整命令、时间统计和退出状态在 `build/repcut_thread_scaling_20260819/logs/build_freshG/`。

### 6.2 正确 profile 的五个短 probe

五个 probe 均使用独立 CPU 集合、NUMA 1、ASLR 关闭、`-C 1000 --no-diff`，且一次只运行一个。它们不是正式 canary，因为 `--no-diff` 只用于隔离硬件启动/断言行为；共同的 CoreMark 正常终点尚未出现。

| 配置 | `rc` | terminal / instr | cycle / guest | `Host time` | 判定 |
| --- | ---: | --- | ---: | ---: | --- |
| native `t1` | `1` | `ABORT`，`instrCnt=0` | `605 / 609` | `1646 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |
| native `t2` | `0` | `EXCEEDING CYCLE/INSTR LIMIT`，`instrCnt=3` | `996 / 1001` | `1466 ms` | PC `0x0`，未启动 workload |
| native `t4` | `0` | `EXCEEDING CYCLE/INSTR LIMIT`，`instrCnt=3` | `996 / 1001` | `891 ms` | PC `0x0`，未启动 workload |
| native `t8` | `0` | `EXCEEDING CYCLE/INSTR LIMIT`，`instrCnt=3` | `996 / 1001` | `913 ms` | PC `0x0`，未启动 workload |
| partitioned (`N=1`) | `1` | `ABORT`，`instrCnt=0` | `605 / 609` | `4005 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |

原始 probe 日志：

```text
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t1_g_c1000.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t2_g_c1000.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t4_g_c1000.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t8_g_c1000.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_g_c1000_repeat.log
```

这组结果比单一 assertion 更严格地说明：正确 profile 的 RepCut 构建尚未形成可比较的功能等价仿真；不同 native 线程数甚至在错误终点上分叉。因此所有 probe 的 `Host time` 都只能作为失败诊断，不得计算 speedup。

### 6.3 运行器 provenance 修正

实验本地 `run_matrix.py` 新增 `--build-root`，默认值为 `build_freshG`，并在 raw attempt 中记录 build root 和 ELF SHA。已有 `results/canary`、`results/canary_fixed_numactl` 目录保持不变；后续正式运行必须显式确认使用 fresh G root。

### 6.4 对第 3 节构建状态的勘误

第 3 节是第一波构建尚未结束时的中间快照，其中 `native t1/t2` 的 `RUNNING` 和 `native t4/t8` 的 `PENDING` 已被本节 6.1 的最终记录取代；五个正确 profile ELF 均已完成且返回 `rc=0`。该勘误只澄清时间顺序，不改变功能门禁仍为 `BLOCKED` 的结论。

## 7. profile 身份勘误（2026-08-19）

对第 1、2、4、5 节的 profile 判断作如下更正。初轮五个 ELF 的构建命令实际指向工作区已有的 `testcase/xiangshan/build/generated-src`，其中 `DifftestMacros.svh` 定义 `CPU_XIANGSHAN`、interface width `79263`；冻结 RTL 的 `GatewayEndpoint.sv` 也声明 `input [79262:0] in`。因此初轮 ELF 是与冻结 XiangShan `SimTop` 相匹配的构建，不能再以“普通 profile/配置不匹配”理由整体作废。

相反，第二轮 `difftest-src-fresh` 是直接调用通用 `difftest.DifftestMain` 的 `CONFIG=G` 生成，得到 `CPU_DEMO`、width `45871`。它不是 XiangShan `SimTop` 的 generated-src，fresh-G ELF 和对应 probe 只能作为错误 profile 诊断，不能用于性能结果。两组 profile 的身份证据为：

| 来源 | CPU macro | interface width | `DifftestMacros.svh` SHA-256 | 结论 |
| --- | --- | ---: | --- | --- |
| 匹配冻结 RTL 的工作区 generated-src | `CPU_XIANGSHAN` | `79263` | `914e3168bd8de5a08e4ad1ba086e697ba61242d3ae2c49cb21b503c69a4b2faf` | 初轮五个 ELF 的构建 profile |
| 通用 `difftest_verilog CONFIG=G` fresh 目录 | `CPU_DEMO` | `45871` | `a7611839ba3e1c97ed1e7021f0eb4f486cffd99d26de05976eb349ed57d919a5` | 错误 profile，排除 |

对应匹配 profile 的初轮 ELF 身份如下；这些是后续恢复正式矩阵时应使用的 build root `build` 产物：

| 配置 | wall | ELF 大小 | ELF SHA-256 |
| --- | ---: | ---: | --- |
| native `t1` | `13:59.23` | `190,117,944` B | `0958e2c08ed9bd13af55fc773dabb7153c51337247ed23e9ea39eff57d398132` |
| native `t2` | `18:47.38` | `191,012,096` B | `b867a568bb1bb8560ce7bd9d86aee75137d4bb0b7115fa29bfa569df5e4cd8aa` |
| native `t4` | `22:23.92` | `191,239,848` B | `990440c89bb23879ba6bfc6be199f4b32bdbbab4acad0ec2673e492f0ef1c5ef` |
| native `t8` | `29:09.55` | `191,472,456` B | `d1175b8f1789ebc5695428d5d3e5ee348cad0c4d1c73b7191525ae23043225a3` |
| partitioned | `2:29.77` | `261,041,896` B | `99c801808868adfaa433ee580fffcbc0abce7720ecf10b38cea70eeb6141de2c` |

在匹配 profile 的初轮 ELF 上补做的短 probe 进一步收窄阻断点：native `t1` 和 partitioned `N=1/2/4/8` 均在 cycle 605、`ExuBlock.sv:908` 报 `csr_dbltrp_inMN`；native `t2/t4/t8` 的 `--no-diff -C10000` probe 可到 `pc=0x800027c6` 的 cycle-limit，native `t2` 的 10k difftest probe 也正常到同一 cycle-limit。后者仍不是正式性能样本，但说明不能把所有 native 档都笼统描述为 profile 失败。

匹配 profile 的新增 probe 日志保存在：

```text
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t1_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t2_xiangshan_c10000_diff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t2_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t4_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/native_t8_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_t2_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_t4_xiangshan_c10000_nodiff.log
build/repcut_thread_scaling_20260819/logs/fresh_probe/partitioned_t8_xiangshan_c10000_nodiff.log
```

本勘误不改变正式结果状态：matching-profile 的 native `t1` 与整个 partitioned 路径仍未通过功能门，因此 32 个正式样本没有启动；本地 runner 默认 build root 已同步改回 `build`，避免后续误用 `build_freshG`。

## 8. 最终生效口径与匹配 profile 诊断表（2026-08-19）

本节是本记录在后续恢复实验前的最终生效口径。第 1--6 节中把 fresh-G 描述为“正确 profile”的文字属于实验过程快照，已由第 7 节及本节更正；不得据此选择 `build_freshG` ELF。当前唯一匹配冻结 RTL 的构建根目录是 `build`，其 `DifftestMacros.svh` 为 `CPU_XIANGSHAN`/79263。

第 6.3 节中“runner 默认值为 `build_freshG`、后续使用 fresh G root”的句子同样是中间快照；当前 `run_matrix.py --help` 已核验为 `--build-root ... (default: build)`，正式恢复不得省略 profile 和 build-root 的双重核验。

在匹配 profile ELF 上取得的 `-C 10000` 诊断如下。`Host time` 只表示到 cycle-limit 或 assertion 的失败/截断耗时，不是正式性能结果：

| 入口 / 配置 | 选项 | rc | 终点 | cycle / guest / instr | Host time | 诊断结论 |
| --- | --- | ---: | --- | ---: | ---: | --- |
| native `t1` | `--no-diff` | `1` | `ABORT`, pc `0x0` | `605 / 609 / 0` | `1956 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |
| native `t2` | `--diff` | `0` | cycle limit, pc `0x800027c6` | `9996 / 10001 / 458` | `14730 ms` | 短程诊断到达正常限止点 |
| native `t4` | `--no-diff` | `0` | cycle limit, pc `0x800027c6` | `9996 / 10001 / 458` | `8869 ms` | 短程诊断到达正常限止点 |
| native `t8` | `--no-diff` | `0` | cycle limit, pc `0x800027c6` | `9996 / 10001 / 458` | `5946 ms` | 短程诊断到达正常限止点 |
| partitioned `N=1` | `--no-diff` | `1` | `ABORT`, pc `0x0` | `605 / 609 / 0` | `6063 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |
| partitioned `N=2` | `--no-diff` | `1` | `ABORT`, pc `0x0` | `605 / 609 / 0` | `3512 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |
| partitioned `N=4` | `--no-diff` | `1` | `ABORT`, pc `0x0` | `605 / 609 / 0` | `2258 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |
| partitioned `N=8` | `--no-diff` | `1` | `ABORT`, pc `0x0` | `605 / 609 / 0` | `1371 ms` | `ExuBlock.sv:908`, `csr_dbltrp_inMN` |

日志文件位于 `build/repcut_thread_scaling_20260819/logs/fresh_probe/`，文件名分别为 `native_t1_xiangshan_c10000_nodiff.log`、`native_t2_xiangshan_c10000_diff.log`、`native_t2_xiangshan_c10000_nodiff.log`、`native_t4_xiangshan_c10000_nodiff.log`、`native_t8_xiangshan_c10000_nodiff.log`、`partitioned_xiangshan_c10000_nodiff.log`、`partitioned_t2_xiangshan_c10000_nodiff.log`、`partitioned_t4_xiangshan_c10000_nodiff.log` 和 `partitioned_t8_xiangshan_c10000_nodiff.log`。

该表仅用于定位功能门和说明为什么不能比较失败耗时。native `t2/t4/t8` 的截断点不能替代 native `t1` 或 partitioned 的成功功能签名；正式矩阵仍为 `0/32`，必须先修复并重新冻结 RepCut 输出，再按 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 执行 ABBA/BAAB。
