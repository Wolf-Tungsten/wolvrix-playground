# Rob 独立模块 trace 回放基准：gsim vs GrhSIM IR（整机真实激励）

| 字段 | 值 |
|---|---|
| 日期 | 2026-09-29 |
| 角色 | 独立模块性能对标分析（非 goal 战役节点，无谱系字段） |
| 机器 | AMD Ryzen 9 7950X3D（32 逻辑核，187 GiB） |
| 工具链 | clang++ 22.1.2（`-O3`，无 PGO）、Verilator 5.051（ref emu）、gsim（`--supernode-max-size=15`） |
| 被测模块 | XiangShan `Rob`（含内嵌 `RenameBuffer rab`），独立顶层精确提取 |
| 激励 | 整机 Verilator ref emu 跑 `coremark-2-iteration.bin` + nemu difftest，cycle 0 起 100,050 周期完整 I/O trace |
| 相关文档 | `testcase/xs-components/rob/README.md`（设施与口径细节）、`pdocs/grhsim-ir-xiangshan-coremark.index.md`（整机口径） |
| 工作区 | `ptmp/xs-components-rob/trace/` |

## 1. 问题与动机

随机激励基准（`rob_bench`，见 README"运行时基准"）给出 GrhSIM IR 比 gsim 慢 2.53×，但随机激励下两模型执行的是相同却**非法**的状态轨迹，吞吐不代表现实负载，且无法回答"真实工作负载下差距是多少、为什么"。本基准改用从整机 XiangShan 仿真导出的真实 trace 回放，并要求回放轨迹与真实芯片**逐周期逐位对齐**作为正确性锚。

## 2. 方法

```
build/xs/rtl/rtl (XiangShan 全设计 SV)
        │  bind Rob RobTap u_rob_tap (.*)          ← scripts/gen_rob_tap.py
        ▼
Verilator ref emu（difftest，NUM_CORES=1，EMU_RANDOMIZE=0）
        │  每周期 $fwrite 两行文本：I <cyc> <reset> <全部输入 %0h…> / O <cyc> <全部输出 %0h…>
        ▼  FIFO（文本不落盘）
rob_trace.bin（二进制）                            ← scripts/pack_rob_trace.py
  header: magic "RobTrc01" + u64 cycles + u32 in_words + u32 out_words
  每周期: u64 flags(bit0=reset) + u64 in[1509] + u64 out[4327]（46,696 B/周期）
        │  mmap
        ▼
rob_bench --trace                                  ← scripts/gen_rob_bench.py 生成 TB
  每周期：flags→reset + trace 输入 → 同时驱动 gsim / GrhSIM 独立模型 →
  按既定约定求值采样（gsim: drive,step,sample；GrhSIM: drive,clock=0 eval,sample,clock=1 eval）
```

关键约定与机制：

- **逐轮状态重建**：trace 前 52 个周期 reset=1；每个计时轮（含 warmup）都从**全新构造的模型**开始回放，构造开销在计时区外。grhsim 经 `init()` 零初始化；gsim 用 `make_gsim_zeroed()`（清零内存 + placement new），见 §4 工程发现一。
- **静态配置口**：`io_hartId` 恒 0（trace 全程实测为 0，packer 校验 `static_nonzero=0`）。
- **端口覆盖**：打包以端口名连接 tap 清单与 bench 记录布局，1,507/1,507 输入、4,275/4,275 输出全配对，零丢弃；记录中每个口都确认是真实 SV 端口（`non_sv_record_ports=0`）。
- **gsim 内部暴露口**（4,738 个 `set_` 可写的内部节点，如 `io__DOT__debugEnqLsq__DOT__iqAccept[8]`）不是 SV 端口，不驱动、不参与记录。
- **difftest 参数解析器拒绝未知 `+plusarg`**：tap 不能用 `+rob_trace=` 传路径，固定 `$fopen("rob_trace.txt")`（emu 工作目录），该路径即 FIFO。

## 3. 结果

### 3.1 功能验证（100,000 周期三方比对）

`rob_bench --trace --verify 100000`：两模型互比 + 各自与真实芯片 trace 比。

| 配对 | 失配周期数 |
|---|---:|
| gsim vs GrhSIM | 0 |
| gsim vs trace（真实芯片） | 0 |
| **GrhSIM vs trace（真实芯片）** | **0** |

排除项（与随机口径同例，均非功能输出）：17 个 `*_bore` 观测口（69 字，帧计数器约定差异）、2 个 `io_storeDebugInfo_*_pc`（2 字，越界动态索引读）、966 个 `io_diffCommits_info` 行 ≥353 口（966 字，见 §4 工程发现二）。

**结论：GrhSIM IR 在 10 万周期真实激励下对全部 4,275 个输出逐位复现了真实芯片**；排除观测口后 gsim 同样全对。两个计时模型与真机轨迹严格同步。

### 3.2 性能

每轮全新模型，3 轮取 min；两模型 bench checksum 完全一致（`0xd27a5e546e6474cc`）。

| 口径 | gsim | GrhSIM IR | 比值 |
|---|---:|---:|---:|
| **trace 全程 100,050 周期（稳态为主）** | 8,792.354 ms / 11,379 c/s / 87.9 µs/cyc | 20,499.539 ms / 4,881 c/s / 204.9 µs/cyc | **2.33×** |
| trace 全程（议题四 输入融合+扇出打包后复测，工作树） | 8,525.001 ms / 11,736 c/s / 85.2 µs/cyc | 19,366.835 ms / 5,166 c/s / 193.6 µs/cyc | 2.27×（噪声级，见 §4） |
| trace 全程（TODO 六项批量落地后复测，工作树） | 8,891.485 ms / 11,252 c/s / 88.9 µs/cyc | 20,038.595 ms / 4,993 c/s / 200.4 µs/cyc | 2.25×（性能中性，见 §4 末） |
| trace 前 5,050 周期（boot，ROB 近空） | 42.130 ms / 119,866 c/s / 8.3 µs/cyc | 256.275 ms / 19,705 c/s / 50.7 µs/cyc | 6.08× |
| 随机满活动（100k 向量，对照） | 10,427 ms / 9,590 c/s / 104.3 µs/cyc | 26,420 ms / 3,785 c/s / 264.2 µs/cyc | 2.53× |

### 3.3 微观数据（perf stat，trace 全程；进程含 warmup+1 计时轮共 200,100 仿真周期）

| 指标（每仿真周期） | gsim | GrhSIM IR | 比值 |
|---|---:|---:|---:|
| 指令数 | 443k | 1,661k | 3.75× |
| IPC | 0.92 | 1.49 | — |
| 分支数 / 误码率 | 21.0k / 43.0% | 120.2k / 11.9% | 5.7× |
| L1 loads / miss | 263k / 4.2k | 867k / 17.8k | 3.3× / 4.2× |
| CPU 周期 | 479k | 1,112k | 2.32× |

原始计数：gsim 指令 88.61G / CPU 周期 95.93G；GrhSIM 指令 332.33G / CPU 周期 222.60G。随机口径对照：指令 527k vs 2,276k（4.32×）、IPC 0.83 vs 1.54、误码率 47.7% vs 18.1%。

## 4. 分析

### 为什么慢 ~2.3×（稳态真实激励）

1. **指令口径差距 3.75× 是主因**，与随机口径（4.32×）同源：GrhSIM 每周期 2 次 eval（低相全组合结算 + 高相寄存器提交与下游重传播）对 gsim 单趟 `step()`，约 2×；GrhSIM 状态存于字节数组、经 `cpu_at<T>` 访问器 + trunc/cast helper 读写（单 op 5–7 条指令），gsim 具名成员直接参与原生 C++ 表达式（2–3 条），又约 2×。
2. **IPC 反向对冲**：gsim 误码率 43.0%（mux 选择难预测）压 IPC 至 0.92；GrhSIM 误码率 11.9%、IPC 1.49。3.75× 指令差被压缩成 2.3× 时间差（CPU 周期比 2.32× 与墙钟比 2.33× 精确吻合）。
3. **差距是活动率的函数**：boot 段 ROB 近空，gsim 事件驱动几乎全跳（比自身稳态快 10.5×），GrhSIM 活动跳过收益较小（4.1×），比值瞬时拉大到 6.08×；稳态真实活动（ROB 持续有入队/提交/回滚）回到 2.33×，与随机满活动（2.53×）接近但略低——真实激励下两模型都快于满随机（gsim +19%、GrhSIM +29%），GrhSIM 受益更多，比值略收窄。

### 反汇编级证据（2026-09-29，议题二：访存模式与指令膨胀）

方法：`perf record -F 999` 分别采样 trace 全程单轮（`--model grhsim|gsim`），`perf annotate --stdio` 落盘后逐指令归并热点；静态指令数用 `objdump -d --no-show-raw-insn` 按函数统计。原始数据：`trace/perf_{grhsim,gsim}.data`、`trace/anno_{grhsim,gsim}.txt`。

热点函数（周期占比，perf report）：

| grhsim | % | gsim | % |
|---|---|---|---|
| `GrhSIM_Rob::eval()` | 5.82 | `SRob::subStep7` | 11.97 |
| `cpu_write_cell<bool,1>` | 3.84 | `SRob::subStep10` | 11.20 |
| `cpu_task_33` / `cpu_task_68` | 3.28 / 3.22 | `SRob::subStep11` | 10.22 |
| （top70 任务函数摊薄，各 2–3%） | | `SRob::subStep9` | 9.64 |

静态指令数（objdump，按函数族求和）：**grhsim `cpu_task_*` 合计 2,610,347 条 vs gsim `subStep*` 合计 1,137,106 条 ≈ 2.29×**。指令混合占比两侧接近（load 23.2%/23.2%、store 11.6%/9.6%），差异在总量而非单条形态。

证据一：**1 位写的 helper 调用开销实测**。`cpu_write_cell<bool,1>`（10 参数、未内联）独占全程 3.84% 周期；annotate 显示其内部 **78% 的周期是函数序言/尾声/栈参数重载**（`pushq %rbp/%r15/%r14/%r13`、`subq $0x38,%rsp`、`movl 0x90(%rsp)`、…、`retq`），真正的位写（`movzbl`/`andl`/`orl`/`movb`）只占约 22%。生成代码中 `cpu_write_cell` 调用点共 **14,748 处，其中 1 位写 4,928 处**。换算：仅这一个 1 位写 helper 的纯调用开销 ≈ 全程 3% 墙钟。对照 gsim：1 位信号是 `Rob.h` 里的具名 `uint8_t` 成员，写操作是源级 `member = value;`（`Rob0.cpp:65199`），编译为内联 `movzbl`+`movb` 两条。

证据二：**eval() 的两类纯调度开销占据最热指令**。整个 grhsim 采样中最热的单条指令是 `eval()` 里任务分派循环的比较（`cmpq 0x8(%r15),%rcx`，309 样本）与活动标志扫描（`cmpb $0x1,0x21(%r15)`、`jne` 等）；生成代码（`grhsim_Rob.cpp:98746` 起）显示每 round 对 71 个任务各做一次 `if (cpu_flags[i]||…||cpu_flags[i+10])` 字节或扫描 ≈ 780 次字节测试，×2 rounds ×2 evals ≈ **3,100 次/周期纯分派测试**。此外 eval() 开头把 ~1,500 个输入字经 `cpu_at<T>(cpu_objects.get(),off)=trunc(...)` 逐字节拷入状态数组（annotate 头部可见成对 `movzbl/movb`）。`eval()` 自身 5.82% + write_cell 3.84% ≈ 10% 周期在任何任务体执行前就已花掉。

证据三：gsim 侧最热单条指令是 `rep movsb`（状态快照 memcpy，83/17k 样本 ≈ 0.5%），其分派为 `subStep*` 直接调用 + 每个 supernode 一字节 `activeFlags[]` 检查（`Rob0.cpp:65202` 起，变化检测内联 `xor`+`or`），无独立 helper 调用层。

结论：指令膨胀 3.75× 可分解为——静态代码体积 2.29×（helper 调用形式 + 字节数组间址），外加动态的 helper 调用开销（单次 1 位写 78% 是调用约定开销）与每 round 全量标志扫描。优化方向据此可排序：(1) `cpu_write_cell` 小宽度特化内联/改宏，(2) 标志扫描合并为 64 位字测试（bitmap），(3) 输入拷贝做脏跳过。

### 工程发现一：gsim 生成模型状态未初始化（已修）

gsim 的 `SRob::init()` 在未定义 `RANDOMIZE_INIT` 时只调 `activateAll()`，**不初始化任何数据成员**（参考 emu 依赖"reset + X 无关"语义）。同进程重复构造时堆残余导致轨迹不确定：实测连续三轮 checksum 互不相同（`0xe6a19e0d2521c056` → `0xd119b44118475fce` → `0x6ed999b9cabbab2b`），只有首轮（恰好零页堆）与 GrhSIM 一致。修复：TB 以清零内存 + placement new 构造 gsim 模型（`make_gsim_zeroed`），对齐 Verilator 零初始化语义；此后全部轮次 checksum 收敛一致。

### 工程发现二：gsim 的 RAB diffCommits 前瞻窗双回绕发散（已排除，非功能口）

`io_diffCommits` 由 Rob 内嵌的 `RenameBuffer rab` 实例驱动：520 行前瞻窗 = 从 `diffPtr` 起、352 项循环 RAB 的连续视图，行 N 读 `entries[(diffPtr+N) mod 352]`。行 ≥353 时指针和需**回绕两次**（最大 351+519=870）。真实 trace 证实芯片正确双回绕（同周期 `row 352 == row 0`、`row 353 == row 1`）；gsim 模型（`Rob0.cpp` 中 `io_diffCommits_info_N_new_value = diffPtr.value + N` 的单次回绕形态）在行 ≥353 发散，失配频率随行号线性增长（327…42,685 周期），恰好覆盖 `ptr ≥ 704−N` 区间。首失配周期 9283（真实提交开始后）。

GrhSIM 对这些行与真实芯片逐位一致。gsim 发散仅限此 difftest 观测结构（ROB 功能输出全部一致），故对 `io_diffCommits_info_{N≥353}_*` 按 bore 同例排除比对与 checksum，并在 `[VERIFY]` 行打印排除计数（`excluded_diffcommits_ports=966`）。

### 双 eval 分相插桩（2026-09-29，议题一）

方法：`probe_trace_phase` 复用 trace 回放，对每周期 GrhSIM 的两次 eval 分别用 `steady_clock` 计时（drive → clock=false eval → sample → clock=true eval），gsim 侧对 `step()` 计时作参照；同时开 `set_runtime_profile_enabled` 收集 compute/commit/publish 分解。自检：两侧 checksum 均 = `0xd27a5e546e6474cc`，与 bench 口径一致。

每周期分相耗时（ns，全 100,050 周期）：

| 段 | mean | p50 | p90 | p99 |
|---|---|---|---|---|
| grhsim drive | 1,013 | 731 | 1,162 | 4,729 |
| **grhsim eval 下降沿** | **104,974** | 124,012 | 161,552 | 175,368 |
| grhsim sample | 2,384 | 2,334 | 2,504 | 2,555 |
| **grhsim eval 上升沿** | **92,451** | 101,659 | 136,796 | 147,566 |
| gsim drive | 7,881 | 8,926 | 9,488 | 10,820 |
| **gsim step** | **76,450** | 93,896 | 106,609 | 113,682 |
| gsim sample | 2,351 | 2,334 | 2,354 | 2,495 |

分桶（mean ns）：

| 桶 | grhsim 下降沿 | grhsim 上升沿 | gsim step |
|---|---|---|---|
| 全周期 | 104,974 | 92,451 | 76,450 |
| active（非 reset，n=99,998） | 105,009 | 92,482 | 76,422 |
| boot（i<5050） | 20,091 | 33,837 | 3,036 |
| steady（i≥5050） | 109,486 | 95,567 | 80,352 |

runtime profile 分解（全程累计，秒）：

| eval 类别 | evals | rounds | eval | compute | commit | publish |
|---|---|---|---|---|---|---|
| 上升沿（pos） | 100,050 | 200,100 | 9.244 | 6.008 | 2.429 | 0.632 |
| 无沿（falling/other） | 100,000 | 199,999 | 10.499 | 10.214 | 0.019 | 0.013 |
| 下降沿识别（neg，仅首 50 周期） | 50 | 100 | 0.00009 | — | — | — |

解读：

1. **下降沿 eval 仅比上升沿贵 ~14%（105.0 vs 92.5 µs/cyc），不存在显著两相不对称**。随机激励口径下的"低相 181.6µs ≈ 2× 高相 89.5µs"在真实 trace 下消失——随机口径的高相便宜是因为随机激励下时钟升高后活动很快收敛；真实激励下两相都要全量结算组合网络。
2. **两次 eval 合计 197.4 µs vs gsim 单趟 step 76.4 µs ≈ 2.58×**，与墙钟比 2.33× 基本对应（其余为 drive/sample 开销抵消）。双 eval 结构确为差距的主结构因素。
3. **但"省掉上升沿 eval"并不能追平**：即便只算下降沿一次 eval（105 µs），仍比 gsim 整周期 step（76.4 µs）慢 1.37×——单次 eval 的纯 compute（102 µs/次）就已超 gsim 全周期。两个因素叠加：双 eval × 单 eval 指令效率低（字节数组状态 + cpu_at 访问器）。
4. 上升沿 eval 的 92.5 µs 中 commit+publish 占 ~30.7 µs（24.3+6.3），纯重传播 compute ~60 µs——说明时钟升高后大部分组合锥被重新求值，活动粒度跳过收益有限。每个 eval 固定 2 rounds（400,199 rounds / 200,100 evals），活动一轮不收敛。
5. gsim drive（7.9 µs）比 grhsim drive（1.0 µs）贵，但绝对值小，不改变结论。

### 输入检测融合 + 扇出 u64 打包（2026-09-29，议题四；阴性结果：收益 ≈0）

动机：议题二证据二指出 eval() 输入段的两处形态冗余——(1) 先把 `this->io_*` 逐字节拷进 `cpu_objects` 状态数组、再读出来与 `cpu_inputs` 快照比较，本可在寄存器里一次完成的比较被拆成"写内存 + 读内存"；(2) 扇出置活动标志是逐字节 `cpu_flags[off] |= imm`，而 gsim 用 `*(uint64_t*)&activeFlags[w] |= imm64` 一条覆盖 8 字节（`Rob0.cpp:36638` 起）。

改动（`wolvrix/lib/grhsim/backend/cpu_emit.cpp`，工作树未提交）：

1. **输入检测融合**：`this->io_*` 直接与 `cpu_inputs` 快照比较，不等才同时更新 `cpu_objects` 与快照再扇出（无扇出的输入口保留无条件拷贝；行值 TypeId 与端口 TypeId 不等时回退旧式）。
2. **扇出 u64 打包**：`activate()` 对无条件扇出的连续 offset run（≥2 字节且掩码均 ≤0xff）合并为 `cpu_or8(cpu_flags.data(), base, imm64)`——memcpy 版 8 字节 RMW，对齐安全；底层 `cpu_flags` 仍是字节数组，结构不变。

生成代码形态（Rob 模型）：源行数 103,185 → **61,961（−40%）**，`cpu_or8` 6,146 处；但 `GrhSIM_Rob::eval()` 二进制仅 234,690 → 231,803 B（**−1.2%**）。

验证：trace verify 100k 三方比对全过，两模型 checksum 均 = `0xd27a5e546e6474cc`（语义零变化）；`make test_grhsim_cpu_emit` 通过；HDLBits DUT=001 冒烟通过。

性能（同口径 repeat=3 取 min，对应 §3.2 新增行）：grhsim 4,881 → 5,166 c/s，gsim 11,379 → 11,736 c/s，比值 2.33× → **2.27×**。分相探针同幅漂移：falling 105.0→102.1 µs、rising 92.5→89.6 µs、**未改动的 gsim step 也 76.5→74.1 µs**——两侧同向 ~3%，说明 +2.6% 归一化收益在机器噪声量级，与"理论上不会有太大提升"的预期一致。

为什么没用（三条原因）：

1. **clang 本就在合并**：逐字节 `cpu_flags[off] |= imm` 的连续 run 在 −O2 下早已被编译器合并成 64 位 OR——eval() 二进制只缩 1.2% 是直接证据。源码 −40% 减的是静态体积与编译时间，不是动态指令流。
2. **输入检测段不是动态热点**：未变化输入口的扇出体被编译器 cold-block 放置、执行时整段跳过；议题二 annotate 中热点集中在任务体与分派循环，输入段占比本就很小。静态膨胀 ≠ 动态成本。
3. **剩余大头位置不变**：任务体指令效率（字节数组 + `cpu_at` 访问器 vs gsim 具名成员，指令口径 3.75×）、每 round ~780 次字节分派测试、双 eval 结构——融合/打包均未触及。

对照实验（议题三，已撤销）：`cpu_write_cell` 热/冷路径分离 + `always_inline` 强制内联——功能全过、checksum 不变，但 grhsim **−13%**（4,249 c/s；同期 gsim 10,829 c/s 机器漂移 −4.8%，比值恶化到 2.55×）；降档普通 `inline` 后 clang 仍拒绝内联（14,369 处调用点照旧生成弱符号外调）。结论：14.7k 调用点的全域内联使任务体膨胀、压垮 I-cache，代价超过 3.84% 的调用开销收益；该改动已 `git checkout` 撤销。helper 调用开销的可回收上限 ≈3% 墙钟，不是主战场。

### TODO 六项批量落地（2026-09-29；清单与逐条结论见 `pdocs/rob_standalone/TODO.md`）

一批以**可读性/结构净化**为动机的 emitter 修改（`wolvrix/lib/grhsim/backend/cpu_emit.cpp`），统一门槛全过（verify 100k 三方比对 + checksum `0xd27a5e546e6474cc` + `test_grhsim_cpu_emit` + HDLBits DUT=001 冒烟）：

| 项 | 内容 | Rob 实测效果 |
|---|---|---|
| TODO-1 | 边沿历史扫描按退化程度分级发射：单组单字节→纯比较、单组连续→裸 `!memchr`（去 IIFE）、多组 `&&` 短路边 | 形态净化，性能不变（预期内，objdump 早已证实运行时零成本） |
| TODO-3 | commit 写体两级守卫嵌套（同沿守卫 run≥4 合并 `cpu_mem_guard_hoist`；段内同 enable 连续段 ≥2 嵌套 `cpu_mem_enable_hoist`），`cpu_men_*` 预读机制（memEnableCache_）整体删除 | enable_hoist 785 块 / guard_hoist 715 块 / `cpu_men_` 归零；21,401 次 enable 测试去重到每行使能一次 |
| TODO-4 | emit 期常量折叠：`scalarConstantValue()` 识别常量行号，恒在界删边界检查、行号发字面量，恒越界发 `// cpu_mem_write_dead` | 边界检查 14,748 → 176（残余为真动态行）；运行时零成本（clang 本就折叠），纯源码净化 |
| TODO-5 | `cpu_write_cell` 四形态特化：通用 / `_f`（全 mask）/ `_c`（常量行）/ `_cf`（两者），9 个编译期常量参数折掉 | Rob 全部 memWrite 命中 `_cf`/`_f`；归一化打平（0.4414 vs 基线 0.4402） |
| TODO-2 | 生成代码分阶段注释：`/* [phase] ... */` 块注释标注 eval 七阶段、compute/commit 任务头、commit 内各相位（任务头注释无数字以保 twin 折叠） | 纯注释，零性能影响；踩坑见下 |
| TODO-6 | commit 内存写直写化（`planDirectMemories` + `cpu_write_cell_direct[_f]`，fanout 为 noinline 外调） | **实测净亏损，默认关闭**（详见下表）；保留 opt-in 开关 `GRHSIM_DIRECT_MEM=1`（可选 `GRHSIM_DIRECT_MEM_MAX_READERS=N`） |

**TODO-6 归因实验**（同日背靠背 REPEAT=1，gsim 双侧漂移 ≤0.6%；归一化 = grhsim/gsim 同轮比值）：

| 配置 | grhsim c/s | 归一化 | 结论 |
|---|---:|---:|---|
| 直写关（shadow+publish，TODO-5 形态） | 4,941 | 0.4414 | 最优 |
| 全直写（inline fanout，task_68 膨胀到 1.47 MB） | 4,738 | 0.4198 | −4.9% |
| 全直写（noinline fanout，task_68 缩回 0.55 MB） | 4,620 | 0.4151 | −6.0%，代码体积不是主因 |
| 宽窄混合（≤8 读者数组直写，其余 shadow） | 4,420 | 0.3874 | −12%，最差 |

结论：**直写在 Rob 上任何配置都是净亏损**。shadow+publish 的批处理形态（紧凑 shadow 区顺序写 + round 末集中 memcmp/memcpy 回拷 + 每变化单元一次读者扫描）优于直写的交错散写 + 写点即扫；亏损与内联形态无关。gsim 的 `$NEXT` 整组回拷之所以快，靠的是"用内存带宽换零记账"的 rep movsb，而不是逐写点直写——grhsim 的 publish 与其同构，直写反而破坏了这个批处理。该机制保留为 opt-in 实验开关，供其他设计形态（写少、扇出窄）复测。

**TODO-2 踩坑记录**：(1) 发射器 IndentBuffer 美化器把 `//` 行注释粘到前一行尾部（trailing 注释设计），连续独立注释两两粘连——段首注释必须用 `/* [phase] ... */` 块注释形态；(2) 注释文本不得含被测试做缺席断言的 token（`cpu_edge_snapshot`，`wolvrix/tests/grhsim/test_cpu_emit.cpp:934`）；(3) 任务体内注释必须无数字（shapeTwinShare/branchShapeShare 文本折叠）。

**最终性能**（REPEAT=3 取 min，verify 全过 + 双 checksum `0xd27a5e546e6474cc`）：grhsim **4,993 c/s**（4,993/4,964/4,970）vs gsim **11,252 c/s**（11,252/11,175/11,132）= **2.25×**，与本轮起点（2.27×）持平——六项修改净效果为性能中性、结构净化。分相探针：pos eval 9.52 s / compute 6.20 s / commit 2.45 s / publish 0.71 s（对照基线 9.24/6.01/2.43/0.63，+2~3% 为机器漂移量级）。

## 5. 复现

```bash
# 一次性：整机 Verilator ref emu（bind RobTap），约 8 分钟（32 并发）
make -C testcase/xs-components -f rob.mk rob-trace-emu-build ROB_TRACE_JOBS=32

# 采集 trace：emu + FIFO 流式打包（约 4–5 分钟，packer 是瓶颈 ~400 cycles/s）
make -C testcase/xs-components -f rob.mk rob-trace-run ROB_TRACE_CYCLES=100000

# 回放验证 + 计时（verify 覆盖全 10 万周期；bench 3 轮取 min）
make -C testcase/xs-components -f rob.mk rob-bench-trace ROB_BENCH_VERIFY=100000 ROB_BENCH_REPEAT=3

# emitter（cpu_emit.cpp）改动后：重新生成 + 重建 grhsim 模型（emit ~22 s + build ~18 s），再重跑上一条
rm -rf ptmp/xs-components-rob/grhsim-model && make -C testcase/xs-components -f rob.mk rob-grhsim-model

# 可选：perf 微观数据
perf stat -e cycles,instructions,branches,branch-misses,L1-dcache-loads,L1-dcache-load-misses \
  -o ptmp/xs-components-rob/trace/perf_gsim_trace.txt -- \
  ptmp/xs-components-rob/bench/rob_bench --trace ptmp/xs-components-rob/trace/rob_trace.bin \
  --verify 0 --repeat 1 --model gsim      # --model grhsim 同理

# 可选：双 eval 分相插桩（约 40 s，输出分桶分相统计 + CSV）
make -C testcase/xs-components -f rob.mk rob-trace-phase-probe

# 可选：反汇编级热点分析（议题二）
cd ptmp/xs-components-rob/trace
perf record -q -o perf_grhsim.data -F 999 -- ../bench/rob_bench --trace rob_trace.bin --verify 0 --repeat 1 --model grhsim
perf record -q -o perf_gsim.data   -F 999 -- ../bench/rob_bench --trace rob_trace.bin --verify 0 --repeat 1 --model gsim
perf report -i perf_grhsim.data --stdio --no-children | head -25      # 热点函数
perf annotate -i perf_grhsim.data --stdio > anno_grhsim.txt           # 指令级热点（gsim 同理）
objdump -d --no-show-raw-insn ../bench/rob_bench | awk '/cpu_task|subStep/'  # 静态指令统计
```

要点：构建必须走 `rob.mk` target（不要手工拼 cmake/verilator 命令）；`rob.mk` 内已固定 `SHELL=/bin/bash`、`CXX=clang++`（gsim 模型的 C++ `_BitInt` 需 clang ≥19）；trace 二进制 4.7 GB，注意磁盘。

## 6. 产物与原始数据

`ptmp/xs-components-rob/trace/` 下：

- `rob_tap.sv` / `tap_ports.json`：tap 模块与端口清单（`scripts/gen_rob_tap.py` 生成）
- `layout.json`：bench 记录布局（`gen_rob_bench.py --layout-out`）
- `verilator-ref-emu/`：整机 ref emu 构建目录（`emu` 二进制）
- `rob_trace.bin`：打包 trace（4,671,934,824 B，100,050 周期）
- `pack.log`：打包统计（`cycles=100050 reset_cycles=52 first_reset=1 static_nonzero=0`）
- `emu_run.log` / `emu_build.log`：emu 运行/构建日志
- `verify_full.log`：排除 diffcommits 前的完整失配诊断（首失配 9283、492 口明细）
- `perf_{gsim,grhsim}_trace.txt` / `perf_{gsim,grhsim}_trace_bench.log`：perf 原始计数与对应 bench 输出
- `../bench_trace.log`：最终 verify pass + bench 全轮输出
- `trace_phase.log` / `trace_phase.csv`：双 eval 分相插桩统计与逐周期原始数据（`../probe_trace_phase.cpp` 为探针源码，target `rob-trace-phase-probe`）
- `perf_{grhsim,gsim}.data` / `anno_{grhsim,gsim}.txt`：议题二的 perf 采样与指令级 annotate 原始数据

## 7. 已知限制

- **位宽截断输入**：`io_exuWriteback_{4,16,20}_bits_data`（记录 64 位 vs SV 128 位）、`io_debugEnqLsq_needAlloc_*`（1 vs 2）、`io_commits_info_*_ftqOffset`（8 vs 5）按模型声明宽度截断驱动；两模型同样截断且 GrhSIM 与芯片逐位一致，证明被截高位不可达 ROB 输出。
- 计时含每轮模型构造（计时区外）与 mmap 页缓存预热（warmup 轮）；trace 长度 100k 周期覆盖 boot + CoreMark 早段，更长轨迹需更大磁盘（46.7 KB/周期）。
- `*_bore` 与 `io_storeDebugInfo_*_pc` 的排除理由与随机口径相同，详见 README。
