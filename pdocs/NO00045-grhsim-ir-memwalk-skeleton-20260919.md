# NO00045：微结构驱动的 commit memWrite 走查骨架削减（ACCEPTED +1.304%）

日期：2026-09-19。最终判定：**ACCEPTED（+1.303620%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点延续用户"加强微结构特性分析"的建议：对当前最佳 GrhSIM-IR 构建
（NO00044 flow-final，sha256 `37504dce…`）重做 perf PMU 普查、perf record
符号归因与 dyn-stats 动态复核，据此提出机制。gsim 侧复用归档普查（配置不变）。

## 微结构普查（2026-09-19，perf stat，100k cycles，CPU2 单核，trace 全关）

机器：AMD Ryzen 9 7950X3D（Zen 4），perf_event_paranoid=-1。
历次对照：gsim 归档（NO00044 测）、NO00043 归档（NO00044 测）、本节点实测 NO00044。

### 组 A：流水线总量

| 指标 | gsim | NO00043 | NO00044（实测） |
|---|---:|---:|---:|
| cycles | 238.998G | 389.775G | 379.016G |
| instructions | 185.172G | 512.387G | 513.799G |
| IPC | 0.775 | 1.314 | 1.356 |
| stalled-cycles-frontend | 133.417G（55.8%） | 177.905G（45.6%） | 171.827G（45.3%） |
| branch-instructions | 9.647G | 22.690G | 22.417G |
| branch-misses | 4.722G（48.9%） | 4.524G（19.9%） | **3.947G（17.6%）** |

NO00044 紧凑走查把 branch-misses 压低 12.8%（4.524G→3.947G），**IR 绝对误预测量
已低于 gsim**（3.947G < 4.722G）；指令数基本持平（+0.28%），cycles −2.75%。
分支预测不再是与 gsim 的差距来源；剩余差距 = cycles 1.586× ≈ 指令 2.774× 在
前端受限（45.3% 停滞）下的直接体现。

### 组 B：指令缓存/ITLB

| 指标 | gsim | NO00044（实测） |
|---|---:|---:|
| L1i tag accesses | 96.090G | 117.762G |
| L1i tag miss | 30.830G（32.1%） | 59.477G（**50.5%**） |
| ic fill from L2 | 1.399G | 2.495G |
| iTLB-loads | 51.5M | 98.4M |
| iTLB-load-misses | 576.3M | 1,010.4M |

### 组 C：数据缓存/DTLB

| 指标 | gsim | NO00044（实测） |
|---|---:|---:|
| L1d loads | 107.798G | 263.981G（51.4% of instr） |
| L1d miss | 4.322G（4.01%） | 12.285G（4.65%）≈61k/eval |
| dTLB-load-misses | 2.08M | 3.43M（可忽略） |

### 组 D/E：分支细分与代码流供给（AMD 事件）

- retired branches 22.416G，mispred 3.945G（条件 18.707G，indirect 205.3M，
  near-ret mispred 20.4M）。
- ic fill from sys（L3/DRAM）48.054G ≈ 每 eval 流式取指 **15.4 MB**
  （48.054G×64B/200k evals），L2 ic fill miss 95.1%——L1i/L2 对代码流完全
  容量失效，text 体积与指令数仍是长期杠杆。

### perf record 符号归因（-F 999，cycles + branch-misses，全量 100k）

| 类别 | cycles | branch-misses |
|---|---:|---:|
| compute tasks（<4200） | 64.07% | 39.03% |
| commit tasks（42xx/43xx） | 18.50% | **40.06%** |
| cpu_helper | 4.75% | 6.89% |
| cpu_write_cell（全实例） | 4.21% | 2.05% |
| eval()（派发 + 内联 publish） | 4.16% | 6.19% |
| cpu_direct_state_changed | 1.15% | 1.77% |
| libc memcmp/memcpy | 0.57% | 0.28% |
| cpu_write_scalar | 0.56% | 0.83% |

- commit 误预测份额 46.8%→40.06%（NO00044 走查生效），但仍是最大单一来源；
  最热 commit task：4215（1.33% cycles + **4.09% misses**）、4225、4241、4242、
  4200、4206。
- eval() 内部最热循环经反汇编定位为**内联 cpu_publish 的 pending 走查**
  （Pending 40B 步长、逐 i `p.memory` 分支与 `cpu_read_offsets[i]==p.offset`
  比较）。

### 动态插桩复核（dyn-stats 构建 = NO00044 checkpoint + commit-compact-walk +
--dynamic-stats，100k，VALID_DIAGNOSTIC，Host 91.291 s 仅作比例参考）

- evals=200,102、rounds=402,258；相位 compute 76.7% / commit 22.0% /
  publish 1.2%。
- supernode：激活 1,038.2M、body 949.6M（quiescence 跳 8.53%），chg/act 均值
  30.13%——**约 70% 激活无 boundary 产出**（与 NO00036 一致）。
- 动态 compute op 514,748/eval；boundary 写回 107.7k/eval，真实变化 5.97%。
- commit：进入 63.36M（**4200–4228 全部每轮进入**，ent≈400,204/任务）；
  port_eval 701.47M、port_fire 487.23M（69.46%）；publish 159.66 pending/call、
  76.3% 真变化。
- **memWrite 端口走查**：task_42xx 中 `if((edge_snapshot) && enable_byte &&
  addr<count)` 形态 memWrite 站点 **29,426** 个（任务 4200–4216 为主，
  __reg_to_mem/l3cache refillBuffer 等族）；这些端口**无 arm 位**，每次任务
  进入都逐端口求值 enable 字节 + 分支。连续段审计：4215 有 519×3 的连续段、
  4212 有 1798+847、4200 有 911、4201 有 535+257——64 端口字分组可行。
- write_cell（4.21% cycles）仅 0.57% libc memcmp——开销在逐端口调用骨架而非
  数据复制。

- **memWrite 端口走查**：task_42xx 中 `if((edge_snapshot) && enable_byte &&
  addr<count)` 形态 memWrite 站点 **29,426** 个（任务 4200–4216 为主，
  __reg_to_mem/l3cache refillBuffer 等族）；这些端口**无 arm 位**，每次任务
  进入都逐端口求值 enable 字节 + 分支。连续段审计：4215 有 519×3 的连续段、
  4212 有 1798+847、4200 有 911、4201 有 535+257——64 端口字分组可行。
- write_cell（4.21% cycles）仅 0.57% libc memcmp——开销在逐端口调用骨架而非
  数据复制。

### memWrite 门精确计数（mw_gate/mw_fire 插桩，dyn2 构建，100k）

- **mw_gate=3,622,956,150（≈9,005/round）**：memWrite 边沿 guard 为真的
  逐端口求值次数；**mw_fire=664,051,213（≈1,650/round）**：guard&&enable&&
  addr 全真、进入 write_cell 的次数。enable 否率 ≈82%（guard 为真前提下）。
- 走查骨架动态成本：9,005/round × ~4 instr（test 快照寄存器 + cmpb enable
  字节 + 2×分支）≈ 36k instr/round ≈ **14.5G instr/run（≈2.8% 总指令）**；
  开火侧 1,650/round × ~30 instr（10 参数调用 + 内部合并比较）≈ 13.3G
  （≈2.6%，write_cell 符号实测 4.21% cycles 印证）。
- enable 共享结构：30,851 站点对应 **17,214 个全局去重 enable 字节**
  （任务内去重如 4212：2,701 站点 / 115 个值，跨数组共享多）；同
  （任务，数组）内 enable 多为互异（单 enable 数组仅覆盖 17.2% 站点）。

## IDEA（定稿，2026-09-19）

### 假设与机制：commit memWrite 走查骨架削减（guard 提升 + enable 缓存）

**瓶颈证据**（上述实测）：commit tasks 18.5% cycles + 40.06% branch-misses；
memWrite 走查骨架 ≈2.8% 总指令、每次进入重读同一组散乱 boundary enable 字节
（L1d 压力）；最热 commit task 4215 独占 4.09% 误预测。

**机制**（纯发射形态，IR/映射/调度/布局不动）：

- **M1 guard 提升**：commit 任务体内，共用同一边沿快照局部量
  （`cpu_edge_snapshot_N`/`cpu_cached_*` 或 `"true"`）的**连续 memWrite 段**
  （段长 ≥4，段内允许交错的 history 采样——采样写 shadow 历史、guard 读
  当前 obj，互不依赖）发射为 `if(guard){ 各端口 if(en&&addr<count){写} }`+
  段尾采样保持原序。语义：guard 是纯读局部量，提升不改变任何求值时机；
  端口相对顺序不变；采样与写体无数据依赖（pending 记录顺序变化仅涉及
  不相交存储，publish 的 memcpy/flag-OR/dirty 清除均可交换）。
- **M2 enable 任务级缓存**：commit 任务（DomainGatedCommit）体内**从不写
  boundary**（结构保证：commit op 不产生 boundary 值；实测 401 个含 mem
  站点的任务文件零 boundary 存储）——因此任务进入后 enable 字节稳定。
  对任务内 memWrite 的 boundary bool enable 操作数（去重，≤1024/任务），
  在走查区起始一次性读入 `const bool cpu_men_*` 局部量，各端口复用。
  消除每端口重复的散乱字节 load（4212：2,701→115 次/进入）。

**新意**：与 NO00042-A（给 memWrite 门加 fired-sticky 武装，82% 触发率证伪）
不同——不改任何武装/跳过语义，只削减**必然求值**的门的骨架成本；与 NO00041
（副作用门 compaction）同族但作用于 memWrite 写门（当时未覆盖）；与
NO00033/34 的读缓存同型但作用于 commit 体（此前仅限 compute helper）。

**预期与证伪标准**：

- 覆盖：memWrite 标量端口站点 ~29.4k，其中共用快照 guard 的连续段
  （36,787 站点中 snapshot_0 主导）。
- 预期收益：指令 −1.4%（guard 测试消除）+ enable load 消除的 uop/L1 收益，
  合计局部目标 **+1%~3%** Host；单对筛选门 +0.4%（页帧驱逐协议）；
  正式门 6 次交替秩次判据。
- 证伪条件：筛选 <+0.4% 或正式不分离 → REJECTED 并改换机制（备选：
  站点描述符化削减 write_cell 调用建立、publish pending 按 memory 拆环）。
- 止损：生成/编译 1800 s 截止；仿真 1.5×（75.372 s → 113.1 s）截止。

## BASELINE（2026-09-19）

- 对照（old）：NO00044 正式二进制
  （`ptmp/no00044_uarch_20260919/flow-final/emu/grhsim-compile/emu`，sha256
  `37504dce7581ef9c303feb64e2f55b4f68b04686edf90a1141f398b724aff15d`），
  正式三次 new 均值 **75.372333 s**。
- 基线 commit：wolvrix 子模块 `aea47d5`（NO00044 接受）；根仓库 `4f0d05a`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、trace 全关、交替 old/new、
  每次运行前 posix_fadvise(DONTNEED) 页帧驱逐；预注册顺序
  old1/new1/old2/new2/old3/new3。
- 筛选路径：`make reemit_grhsim_ir` 自 NO00044 checkpoint
  （`ptmp/no00044_uarch_20260919/flow-final/xiangshan_grhsim_ir.json`）
  加新开关重发射。
- 资源：生成/编译 timeout 1800 s 截止；编译 `VM_BUILD_JOBS=nproc=32`。
- 诊断构建（dyn/dyn2）与探针日志在 `ptmp/no00045_uarch_20260919/`。

## 阶段记录

### IMPLEMENTED（2026-09-19，进行中）

实现（wolvrix 子模块工作区差异，基线见 BASELINE）：

- `cpu.st.emit-cpp` 新增 `--commit-mem-walk`（默认关；主流水线
  `scripts/wolvrix_xs_grhsim_ir.py` 显式开启；筛选经 `reemit_grhsim_ir.py
  --commit-mem-walk` / Makefile `GRHSIM_REEMIT_COMMIT_MEM_WALK=1` 透传）。
- `lib/grhsim/backend/cpu_emit.cpp`：
  - M1（guard 提升）：commit 任务 op 流中，共用同一边沿快照局部量
    （`findGuard` 非空）的连续 memWrite run（长度 ≥4、不跨 unit）发射为
    `if(guard){ // cpu_mem_guard_hoist ops=N ...}`，端口写体剥离 guard
    逐序保留；run 的 history 采样在块后按原序补发（写体只写 memory cell、
    采样只 stage 状态历史，互不相交；pending 顺序对不相交 key 可交换）。
    短 run 与非快照 guard 维持原形态。
  - M2（enable 缓存）：commit 任务的 memWrite enable 操作数中，位宽 1
    两态无符号、Boundary 存储、非常量/非别名者去重为 `const bool cpu_men_*`
    局部量（任务走查区起始一次性读入，>1024 个时整任务放弃缓存）；commit
    任务体内不写 boundary（结构性），故缓存值在任务体内稳定。
  - 统计计入 packSummary：mem_guard_hoist_runs/sites、
    mem_enable_cache_values/sites。
  - 附带诊断：`--dynamic-stats` 下新增 mw_gate/mw_fire 计数（仅插桩构建，
    不进入性能路径）。
  - **v2 订正**：enable 缓存从"全部去重 + >1024 整任务放弃"改为**仅缓存
    ≥2 次使用的共享值**——单用值缓存不省指令（test 寄存器 ≈ cmpb 内存），
    且 v1 的整任务上限会把 4215（2098 个几乎全互异 enable）这类任务整体
    排除；共享过滤后缓存量由共享度自然界定。
  - 聚焦测试 `test_cpu_emit.cpp::testCommitMemWalk` + 夹具
    `tests/grhsim/data/cpu_commit_memwalk.{mk,_main.cpp}`：12 个同 guard
    memWrite 端口（前 4 个共享同一 enable 值）+ 3 个异事件短 run；断言
    hoist 块与 `cpu_men_` 缓存存在、短 run 保持逐端口形态；ASan/UBSan 下
    随机记分板 3×4096 步比对（含地址别名、双 eval 幂等、双时钟沿）。
  - 聚焦测试通过；`grhsim-ir-tests`、`grhsim-cpu-mapping-tests`、
    `grhsim-cpu-schedule-tests` 全部通过。
  - 可复现性对照：flow-plain（同 checkpoint、仅 `--commit-compact-walk`）全部
    **4,799 个源文件 md5 与 NO00044 正式 model 全等**——开关关闭时零差异。
  - v2 重发射覆盖：**mem_guard_hoist_runs=1,588 / mem_guard_hoist_sites=
    32,972 / mem_enable_cache_values=1,927 / mem_enable_cache_sites=15,189**；
    commit_compact_groups/ports 保持 490/31,360 不变。

### 筛选（2026-09-19）

- flow-memwalk 重发射（同 checkpoint + `--commit-mem-walk`）+ fresh 编译 exit 0。
- **单对筛选（screen1，页帧驱逐协议，端点 240349/99996/100001/0x80000c0c
  一致、退出码 0、NEMU PASS）：old 75.661 / new 74.136 = +2.018%**——越过
  +0.4% 门，进入正式门槛。

### 正式门槛（2026-09-19）

- 完整 SV→C++ 生成 **693.0 s**（<1800 s，完整 SV 路线、
  `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`、非 checkpoint 恢复，
  round-trip 校验通过；`timeout -s KILL 1800` 在位未触发）；管线内
  `cpu.st.emit-cpp` 带 `commit_compact_walk=true, commit_mem_walk=true`。
- 正式 model 与筛选 model（flow-memwalk）全部 **4,799 个源文件 md5 全等**。
- HDLBits DUT=001 回归通过（`[TB] dut_001 passed: one=1`）。
- fresh 编译 **198.9 s**（<1800 s，exit 0，`VM_BUILD_JOBS=nproc=32`）。
- 轮次结构不变性：正式二进制 profile 复测 `evals=200,102、rounds=402,258`，
  与 NO00044 完全一致；相位（profile 开销下）compute 54.48 s /
  commit 17.98 s / publish 1.36 s / 合计 73.95 s。

### 正式 6 次交替复测：ACCEPTED（2026-09-19）

被测二进制 `ptmp/no00045_uarch_20260919/flow-final/emu/emu`
（正式 SV 路线构建，sha256
`18964d9b6768eb1d635bcb86235e3c8706dfddaeae8d7125c57bce327a1750e2`）；
对照 old 为 NO00044 flow-final sha256 `37504dce…`（其正式三次 new 均值
75.372333 s）。6 次交替（`formal/summary.json`；预注册 old1/new1/old2/new2/
old3/new3；每次运行前对 old/new emu 均 posix_fadvise(DONTNEED) 驱逐；CPU2、
单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 74.993 | 73.954 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 75.245 | 74.245 | 0 | 同上 |
| 3 | 74.981 | 74.084 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **75.073000 s**（样本 SD 0.149077）、new 均值 **74.094333 s**
  （样本 SD 0.145775），降低 **1.303620%**。
- `max(new) 74.245 < min(old) 74.981`，Mann-Whitney U=0、单侧精确 p=0.05、
  Cohen d=−6.64、Cliff's delta=−1.0，**秩次判据通过**。

**最终判定：ACCEPTED（commit memWrite 走查骨架削减——同快照 guard 连续段
提升 + 共享 boundary enable 任务级缓存，+1.303620%，秩次判据通过，生成/编译
门槛通过，100k 等价确认，HDLBits 回归通过）。** 按新均值计算，GrhSIM-IR 为
归档 gsim 46.965 s 的 **1.577656×**（上一节点 NO00044 为 1.604912×）。

**语义约束**：M1 仅作用于共用同一边沿快照局部量（`findGuard` 非空）的连续
memWrite run（≥4、不跨 unit）；guard 为纯读局部量，提升不改变求值时机；端口
写体在块内保持程序序；run 的 history 采样在块后按原序补发（写体只写 memory
cell、采样只 stage 状态历史；pending 记录顺序变化仅涉不相交 key，publish 的
memcpy/flag-OR/dirty 清除均可交换）。M2 仅作用于 DomainGatedCommit 任务中
memWrite 的位宽 1 两态无符号、Boundary 存储、非常量非别名、任务内 ≥2 次使用
的 enable 值；commit 任务体内不写 boundary（结构性成立，实测 401 个含 mem
站点的任务文件零 boundary 存储），缓存局部量在任务体内稳定。IR、GRH pass、
映射、调度、布局、XiangShan 与测试源码均未改；开关关闭时发射输出与 NO00044
逐字节一致（4,799 文件 md5 全等）。

**保留实现**：wolvrix 子模块 commit `ecb8190`（`lib/grhsim/backend/cpu_emit.cpp`
memWrite 走查骨架发射 + `--commit-mem-walk` 选项 +
`include/grhsim/backend/cpu_emit.hpp` 签名 +
`tests/grhsim/test_cpu_emit.cpp::testCommitMemWalk` +
`tests/grhsim/data/cpu_commit_memwalk.{mk,_main.cpp}` 聚焦夹具，含
`--dynamic-stats` 的 mw_gate/mw_fire 诊断计数）；根仓库 commit `bfbca7e`
（子模块指针 + `scripts/wolvrix_xs_grhsim_ir.py` 主流水线开启
`commit_mem_walk`、`scripts/reemit_grhsim_ir.py` `--commit-mem-walk`、Makefile
`GRHSIM_REEMIT_COMMIT_MEM_WALK` 透传、本报告与索引）。

**被否决尝试**：enable 缓存 v1（全部去重 + >1024 整任务放弃）在覆盖率审查中
发现 4215 等任务被整体排除（2,098 个几乎全互异 enable），未进入测量即按
≥2 次使用过滤订正（v2）；无性能意义上的失败变体。

**后续方向**：(a) write_cell 开火体仍是 commit 侧最大单笔（664M 次调用/run、
4.21% cycles），10 参数调用的描述符化可削减调用建立与 text，但 NO00036-B
内联证伪与 NO00044-v1 教训要求先算清指令收支；(b) eval() 内联 publish 的
per-record memcmp 调用与 per-i `p.memory` 分支（4.16% cycles + 6.19% misses）
可按 memory/non-memory 拆环消除数据相关分支；(c) compute 侧 64% cycles、
70% 惰性激活的结构事实未变——任何"近零固定成本"前提下的激活精度机制仍是
最大潜在杠杆；(d) 微结构普查的剩余结论：指令数 2.774× 与 L1i 容量失效
（15.4 MB/eval 代码流）主导与 gsim 的差距，branch-miss 绝对量已低于 gsim。
