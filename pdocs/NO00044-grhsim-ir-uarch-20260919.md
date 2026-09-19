# NO00044：微结构特性分析驱动的 commit 紧凑走查（ACCEPTED +3.023%）

日期：2026-09-19。最终判定：**ACCEPTED（+3.023168%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点按用户建议以**宿主微结构特性实测**为起点：对当前最佳 GrhSIM-IR 构建
（NO00043 flow-final，sha256 `9550498a…`）与归档 gsim 构建（编译于
2026-09-10）在完全相同的 100k CoreMark 配置（CPU2、XS_EMU_THREADS=1、
waveform/commit/RAM trace 关闭）下做 perf PMU 对比，再以 perf record 做
符号级归因，最后用 dyn-stats 插桩构建定量 commit/compute 行为，据此提出机制。

## 微结构普查（2026-09-19，perf stat，100k cycles，每事件组独立运行）

机器：AMD Ryzen 9 7950X3D（Zen 4），perf_event_paranoid=-1。

### 组 A：流水线总量

| 指标 | gsim | GrhSIM-IR | IR/gsim |
|---|---:|---:|---:|
| cycles | 238.998G | 389.775G | 1.631× |
| instructions | 185.172G | 512.387G | **2.767×** |
| IPC | 0.775 | 1.314 | — |
| stalled-cycles-frontend | 133.417G（55.8%） | 177.905G（45.6%） | 1.333× |
| branch-instructions | 9.647G | 22.690G | 2.352× |
| branch-misses | 4.722G（**48.9%** of branches） | 4.524G（19.9%） | 0.958× |

### 组 B：指令缓存/ITLB

| 指标 | gsim | GrhSIM-IR | IR/gsim |
|---|---:|---:|---:|
| L1i tag accesses | 96.090G | 125.566G | 1.307× |
| L1i tag miss | 30.830G（32.1%） | 61.729G（**49.2%**） | 2.002× |
| ic fill from L2 | 1.399G | 2.417G | 1.727× |
| iTLB-loads（generic） | 51.5M | 107.7M | 2.09× |
| iTLB-load-misses（generic） | 576.3M | 1,036.6M | 1.80× |

### 组 C：数据缓存/DTLB

| 指标 | gsim | GrhSIM-IR | IR/gsim |
|---|---:|---:|---:|
| L1d loads | 107.798G（58.2% of instr） | 266.928G（52.1%） | 2.476× |
| L1d miss | 4.322G（4.01%） | 12.590G（4.72%） | 2.913× |
| dTLB-load-misses | 2.08M | 3.53M | 可忽略 |

### 组 D：分支细分（AMD ex_ret_*）

| 指标 | gsim | GrhSIM-IR |
|---|---:|---:|
| retired branches | 9.646G | 22.688G |
| mispredicted | 4.721G | 4.525G |
| conditional | 8.755G | 19.117G |
| indirect | 78.0M | 205.3M |
| near-return mispred | 11.45M | 21.07M |

两侧误预测几乎全部为条件分支；绝对量相等（≈4.5G/100k cycles），gsim 的
条件分支误预测率 ≈54%、IR ≈23.7%。

### 组 E：代码流供给（AMD ic/l2/bp）

| 指标 | gsim | GrhSIM-IR |
|---|---:|---:|
| ic fill from L2 | 1.408G | 2.450G |
| ic fill from system（L3/DRAM） | 25.920G | 49.510G |
| L2 ic access | 27.328G | 51.960G |
| L2 ic fill miss | 25.920G（94.8%） | 49.510G（95.3%） |
| bp_de_redirect | 2.954G | 4.389G |

两侧 L1i/L2 对代码完全容量失效：每个 eval 从 L3 流式取指 ~10–16 MB
（IR 49.5G×64B/200k evals ≈ 15.8 MB/eval；gsim ≈ 8.3 MB/eval），带宽
35–40 GB/s。IR 的每 eval 取指字节恰约为 gsim 的 1.9 倍（≈text 比 1.78×）。

### perf record 符号归因（-F 999，cycles + branch-misses，全量 100k）

GrhSIM-IR（cycles 391.8G、branch-misses 4.539G；NEMU/difftest 占比 <0.4%，
**4.5G 误预测全部来自模型自身代码**，不是共有 harness）：

| 类别 | cycles | branch-misses |
|---|---:|---:|
| compute tasks（<4200，3,049 个，top 仅 0.30%） | 63.0% | 35.7% |
| commit tasks（42xx/43xx） | 20.3% | **46.8%** |
| cpu_helper | 4.6% | 5.9% |
| cpu_write_cell&lt;bool,1&gt; | 4.14% | 1.8% |
| eval 派发循环 | 4.04% | 5.3% |
| cpu_direct_state_changed / write_scalar / publish+mem* | 2.4% | 2.9% |

- commit 前 10 大 task（4221/4215/4225/4222/4200/4220/4241/4242/4206/4214）
  占全部 branch-misses 的 **33%**；task_4221 误预测密度为 cycles 占比的 3.4×。
- compute 侧**无热点**：3049 个 task 平坦分布——compute 只能靠系统性机制，
  逐 task 定点无意义。

### 静态指令形态（objdump 全 text，17.59M 指令）

- cpu_task 函数 16.12M 条（91.6%）；其中 **46.3% 带访存操作数**。
- opcode 前列：mov 4.45M、movzbl 2.21M、or 1.97M、and 1.44M、xor 685k。
- 函数粒度：4,690 个 cpu_task 共 77.2 MB；中位 12.5 KB、p90 28 KB、
  最大 331.9 KB；>32 KB 的函数占 task text 28.4%。
- 典型 task 反汇编（task_1000）：中间值经 `cpu_local[]` 字节槽全部 spill
  到栈（`mov %al,-0x19(%rsp)` + reload），栈流量占该函数指令 ~10%。

### 动态插桩复核（dyn-stats 构建自 NO00043 checkpoint，100k，VALID_DIAGNOSTIC）

- evals=200,102、rounds=402,258（2.008 轮/eval）；compute 74.6% / commit 24.0% /
  publish 1.2%（插桩构建相位，比例有效）。
- supernode：sn_act 5,188/eval、sn_body 4,746/eval（quiesce/edge-direction 仅跳
  8.5%）、sn_chg 1,312/eval——**72.4% 的 body 激活无 boundary 产出**（3,437 次
  惰性 body/eval × 均 ~109 ops）。
- commit：task 进入 316.6/eval（490 个 commit task 中顶部数组族**每轮都进入**）；
  armed 端口求值 port_eval 1,744/round、开火 port_fire 1,215/round（触发率 69.6%，
  与 NO00042-A 的 82% 同族结论一致：被求值的门大多是真工作）。
- 大数组 commit task（task_4221 逐指令归因）：每次进入 64 个 word 预过滤 +
  ~128 字节测试 + 676 位测试 + ~240 enable 测试 + ~196 次开火；
  **56% cycles 在条件跳转、31% 在 test/cmp**；误预测 512 次/进入（单函数占全模型
  branch-miss 的 4.5%）。walk 骨架（找端口）远大于写体。
- 逐字节注入计数（task_4221，diag build）：每进入 byte_nonzero=128、
  arm_eval=676、fire=196——armed 位稠密散布，两级预过滤已尽力。

### 编译参数诊断（筛选口径，单对，页帧驱逐）

- 同一 model 源以 `-O2` 重建：Host **80.737 s** vs 同窗口 NO00043 参考
  **77.484 s**——**慢 4.2%**：-O3 内联/优化是净收益，"缩小函数/减少内联"
  方向证伪（与 NO00034-B 大范围局部变量 −3.36%、NO00036-A 细粒度 −30.7%
  一致：该代码形态下 GCC -O3 的大函数处理并非瓶颈根因）。
- 字节槽 spill 微实验：真实 task_1000 单块独立编译仍 25.2% 栈引用——spill
  来自 ~24 个 helper 读缓存输入的寄存器压力（15 GPR），溢出槽与 boundary
  重读同为 L1 命中字节加载，代价近似——**spill 消除不是杠杆**（据此否决
  发射层函数分段候选，不进入实现）。

## IDEA（定稿，2026-09-19）

### 假设与机制：commit 均一 u64 端口组的批量无分支变化扫描（commit word batch）

**瓶颈证据**（上述实测）：commit tasks = 20.9% cycles + **47.9% branch-misses**；
成本集中在 42xx 数组族——每轮进入、逐端口 `test arm bit → cmpb enable →
cmp current` 链式求值（task_4221 每次进入 ~3,100 条条件分支、512 次误预测、
87% cycles 在 test/branch 骨架）。其中 7 个 task（4218–4224）的端口 **100%
是 u64 全掩码直接提交**（全模型 36,387 个此类端口，占直接提交体 34%），且
布局高度规律：**目标状态为连续 u64 数组（stride 8），boundary 记录为
{enable:8B, data:8B} 16 字节等距记录**（stride 16 覆盖 2,980/3,351）。

**机制**：对满足资格的 pflag 字节（≤8 个端口）：元素类型统一 u64 二态、掩码
全 1（next=data）、notify 为 direct_state_changed_one、组内 guard 一致
（消费语义 = 字节清零）、状态偏移 stride 8 连续、boundary 记录等距——发射为
**单条向量化批量扫描**：

```
if(armed byte){ pflags[b]=0;
  cur8   = 2×ymm 连续加载（state 数组）
  data8  = 4×ymm 覆盖 8 条记录 + 偶数 qword 抽取
  en8    = 同 4×ymm 的 pmovmskb 偶数位抽取
  todo   = vpcmpeqq 比较取反 & en8        // 分支less
  while(todo){i=ctz;todo&=todo-1;         // 仅真开火端口进入
    obj[sbase+8i]=data_i; ntf_off[i]/ntf_mask[i] 通知; }   // 升序，序不变
}
```

**语义不变性**：单写者直接提交（`planDirectCommits`：writers==1 且全部引用为
读/写）⟹ 端口间不共享状态、提交顺序无关；通知为 `cpu_flags[off]|=mask` 的
可交换 OR；未 armed 端口求值是幂等无操作（操作数未变 ⟹ cur==data ⟹ 不写不
通知）；字节清零时机与现状一致（body 不写 pflags）；开火按 ctz 升序与现状
逐位序相同。**仅改发射形态，IR/映射/调度/布局不动**。

**新意**：把"找端口"从逐位数据相关分支链换成无分支向量比较 + ctz 迭代，
直接削减 (a) 每进入 ~2.4k 条走查指令中的位测试层、(b) commit 侧 48% 的
branch-miss 主力（字节/位测试）、(c) 每轮流式取指的 commit 函数体体积
（4,096 条内联写体折叠为共享循环 + 每字节通知表，task_4221 级函数
185 KB → ~15 KB 量级）。与 NO00042-A（给 memWrite 门加武装，82% 触发率
证伪）不同：本机制不改武装语义、不加生产者钩子，只改变**既有 armed 端口**
的扫描形态；与 NO00019 的字预过滤互补（保留 word/byte 预过滤，替换其下
的逐位层）。

### 预期与证伪标准

- 覆盖：u64 全掩码直接提交端口 36,387 个（直接提交体 34%），其中 4218–4224
  七个 task 全覆盖（约 commit cycles 的 6–8 个百分点）。
- 预期收益：+1.5%~4%（commit 侧走查分支/指令削减 + text 缩小）；单对筛选门
  +0.4%（页帧驱逐协议）；正式门 6 次交替秩次判据。
- 证伪条件：资格覆盖率远低于普查（如布局正则性砍半）、筛选 <+0.4%、或正式
  交替不通过秩次判据——记录 REJECTED（含变体数据）并改换机制（备选：
  同族 u8/bool SWAR 批量、notify 合并、冷体 outlining）。
- 止损：生成/编译 1800 s 截止、仿真 1.5× 基线截止（同既有协议）。

## BASELINE（2026-09-19）

- 对照（old）：NO00043 正式二进制
  （`ptmp/no00043_mux_chain_fold_20260918/flow-final/emu/emu`，sha256
  `9550498a5f5a499eb5a4daa8f8aa3f74d844f780e2e85ffb2bf1a47af0ae6585`），
  正式三次 new 均值 **77.917333 s**；同窗口参考复测 77.484 s。
- 基线 commit：wolvrix 子模块 `52dd805`（NO00043 接受）；根仓库 `c3806de`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、trace 全关、交替 old/new、
  每次运行前 posix_fadvise(DONTNEED) 页帧驱逐；止损 1.5×（77.9 s → 116.9 s）；
  预注册顺序 old1/new1/old2/new2/old3/new3。
- 筛选路径：`make reemit_grhsim_ir` 自 NO00043 checkpoint 加新开关重发射。
- 资源：生成/编译 timeout 1800 s 截止；编译 `VM_BUILD_JOBS=nproc=32`。
- 诊断构建（dyn-stats）与全部探针日志在 `ptmp/no00044_uarch_20260919/`。

## 阶段记录

### IMPLEMENTED（2026-09-19）

实现（wolvrix 子模块工作区差异，基线 `52dd805`）：

- `cpu.st.emit-cpp` 新增 `--commit-batch-scan`（默认关；主流水线
  `scripts/wolvrix_xs_grhsim_ir.py` 显式开启；筛选经 `reemit_grhsim_ir.py
  --commit-batch-scan` / Makefile `GRHSIM_REEMIT_COMMIT_BATCH_SCAN=1` 透传）。
- `lib/grhsim/backend/cpu_emit.cpp`：DomainGatedCommit 的 armed 端口走查中，
  每个 pflag 字节（恰好 8 个端口、组 guard 一致）若全部为**单写者直接提交、
  u64 二态、掩码全 1 常量（next==data）、单目标通知**的 regWrite/latchWrite，
  发射为批量无分支扫描：`cpu_todo` 8 路 `(cur!=data)&enable` 逐位计算 +
  `if(cpu_todo&bit)` 升序开火（写 + notify 常量与逐位形态逐项一致）；
  字节整清零语义与 `portMask==255` 分支相同。其余形态回退既有逐位走查。
  统计经 `commit_batch_bytes/commit_batch_ports` 计入 packSummary。
- 聚焦测试 `test_cpu_emit.cpp::testCommitBatchScan` + 夹具
  `tests/grhsim/data/cpu_commit_batch.{mk,_main.cpp}`：8 个均一 u64 端口 +
  1 个变掩码端口（须保持逐位），JSON 往返→发射检查 `cpu_commit_batch_scan`
  恰好 1 处且逐位形式保留；ASan/UBSan 下随机记分板 3×4096 步比对（含
  posedge 提交、惰性非触发轮、双 eval 幂等）。
- `grhsim-cpu-emit-tests`（93 s）、`grhsim-ir-tests`、`grhsim-cpu-mapping-tests`、
  `grhsim-cpu-schedule-tests` 全部通过。
- 可复现性对照：flow-plain（同 checkpoint、不带开关重发射）全部 4,798 个
  源文件与 NO00043 正式 model md5 全等——发射器在开关关闭时零差异。

### 筛选构建（2026-09-19）

- flow-batch 重发射（同 checkpoint + `--commit-batch-scan`）：覆盖
  **commit_batch_bytes=3,984 / commit_batch_ports=31,872**（u64 全掩码普查
  36,387 的 87.6%；其余落在不满 8 端口的字节或非一致 guard 组）；
  task_4221 源文件 2.71 MB→1.54 MB；模型源总量 −9.1 MB。
- flow-batch fresh 编译 201 s（nproc=32），exit 0。**ELF text 99.48 MB，
  较基线 98.60 MB 反增 +0.9 MB**（扫描序列在 SSE2 基线下未向量化，GCC 对
  每 lane 生成 cmp+cmov+shl 约 8–9 条，超过原逐位链）。
- 聚焦测试全部通过（含 ASan/UBSan 随机记分板）。
- **单对筛选（screen1，页帧驱逐协议，端点一致、NEMU PASS）：old 77.873 /
  new 78.525 = −0.837%——REJECTED（低于 +0.4% 门）。**
- 归因 perf stat（同配置 100k）：new 较 old 指令 **+0.72%**
  （512.39G→516.10G）、branch-misses **−4.71%**（4.524G→4.311G，确认
  分支削减成立）、cycles +0.41%。结论：无分支全宽扫描每 lane 求值成本
  （~8 条）超过被替换的逐位测试（armed 过滤后 ~4.3 条/armed 端口）——
  **指令增量 1.19 cycles/instr 的前端约束下恰好吃掉误预测节省**。
  收支模型：胜率要求 |Δmiss|/Δinstr > 0.092，v1 实测 0.057。
- 变体 v3（扫描剔除 enable、开火分支内联测 enable）按收支核账
  Δinstr 仍为正、|Δmiss|/Δinstr ≈ 0.08 < 0.092，未进入构建——该族在
  标量形态下枯竭：armed 过滤后的逐位内联常量链已是指令最优，无分支
  全宽扫描只有在可向量化（连续布局 + AVX 级 ISA）时才同时降指令与分支，
  两者均超出本节点合法范围（generic 构建无 AVX；布局重排改变读者侧成本）。
- 编译参数诊断（同窗口单对，仅诊断不作机制）：同 model 源 `-O2` 重建
  **80.737 s（+4.2% 慢，去内联证伪）**；`-O3 -march=native` **75.797 s
  （−2.2%）**——text 98.6→95.6 MB，逐符号分析显示收益弥散（3,387 个函数
  普遍缩小，task_27 16,831→6,251 条），主因是 AVX512 字节向量形态
  （vpermi2b/vmovdqu8/kmovd）替代 SSE2 shuffle 序列。**该发现仅作诊断
  记录**：主机特定 ISA flag 不满足"通用特征触发"的方案要求，不作为节点
  机制；但它定量证明生成代码存在约 2% 的指令选择余量。
- 微实验补充：`cpu_local[]` 字节槽 spill 在小函数中同样存在（寄存器压力
  来自 ~24 个缓存输入 > 15 GPR），且溢出槽与 boundary 重读同为 L1 字节
  加载——发射层函数分段/局部变量化（NO00034-B 已在 −3.36% 证伪）不列为
  本节点候选。

### 变体 v2：紧凑 ctz 走查 + 描述符共享体（正式 ACCEPTED，见下）

**v1 失败的精确教训**：v1 对非零字节内的**全部 8 条 lane** 做无分支扫描
（含未 armed lane），每字节 ~65 条指令 vs 旧走查 ~43 条——指令增量恰好吃掉
分支节省。正确形态是**让未 armed 端口零成本**：arm 字节本来就是位图——
8 字节一次 u64 读入即为 64 端口的 armed 位向量，`ctz` 迭代只访问 armed 端口。

**机制（v2）**：对每个**满 64 端口**（8 字节 × 8 位）且组内 guard 一致、端口
全部为"单写者直接提交 u64 二态全掩码单目标通知"的 pflag 组，发射：

```cpp
static constexpr std::uint32_t cpu_cw_state/enable/data[64], cpu_cw_ntf[64];
static constexpr std::uint8_t cpu_cw_nfmask/nfflags[64];   // 函数块内 static constexpr
std::uint64_t cpu_todo=cpu_word8(cpu_pflags.data(),base,8); // 64 armed 位一次读入
if(cpu_todo){ memcpy(pflags+base,0,8);                       // 整组消费（语义同现状）
  do{ i=ctz(todo); todo&=todo-1;                             // 只访问 armed 端口，升序
      en = flags[i]&4 ? flags[i]>>3&1 : bnd[enable[i]];      // 支持常量 enable
      if(en){ d=bnd[data[i]]; c=obj[state[i]];
              if(c!=d){c=d; direct_state_changed_one(ntf[i],nfmask[i],...);} }
  }while(todo); }
```

- **与 v1 的本质差异**：未 armed 端口完全零成本（v1 为每 lane ~8 条指令），
  armed 端口走描述符共享循环（每组 ~1 KB 热代码，替代 64 条内联常量测试链，
  task_4221 级 185 KB 函数的测试链文本整体消失）。
- **语义**：单写者直接提交 ⟹ 端口间无共享状态、提交顺序无关；通知为可交换
  OR；armed 求值与逐位形态逐项一致（enable 门 → cur!=data → 写 → 通知），
  ctz 升序 = 逐位升序；整组清零 ⟺ 逐字节 `=0`（body 不写 pflags）。
  **bug 修复记录**：初版误用常量 enable/data 操作数的 layout 槽（常量经
  `value()` 渲染为字面量，其槽位未初始化）——difftest 在 instr 43 处检出
  ft0 提交丢失（INVALID，筛选协议拦截）；改为常量 enable 折叠进 flags 位
  （bit2=常量、bit3=值）、常量 data 回退逐位，并新增聚焦测试覆盖该回退。
- 覆盖：**490 组 / 31,360 端口**（u64 全掩码直接提交普查 36,387 的 86%，其余
  落在不满 64 端口的尾组或混合 guard 组）。
- 聚焦测试 `testCommitCompactWalk`（64 均一端口紧凑化 + 变掩码/常量 enable
  回退断言 + ASan/UBSan 随机记分板 3×4096 步）通过；`grhsim-ir-tests`、
  mapping/schedule 测试通过。
- 重发射（同 checkpoint）：ELF text 98.60 MB → **97.68 MB**（−0.92 MB）。
- **单对筛选（screen3，页帧驱逐协议，端点 240349/99996/100001/0x80000c0c
  一致、退出码 0、NEMU PASS）：old 77.700 / new 75.356 = +3.017%**——越过
  +0.4% 门，进入正式门槛。

### 正式门槛（2026-09-19）

- 完整 SV→C++ 生成 **703.2 s**（<1800 s，完整 SV 路线、
  `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`、非 checkpoint 恢复，
  round-trip 校验通过；`timeout -s KILL 1800` 截止机制在位未触发）；
  管线内 `cpu.st.emit-cpp` 带 `commit_compact_walk=true`。
- 正式 model 与筛选 model（flow-cwalk3）全部 **4,798 个源文件 md5 全等**。
- fresh 编译 **200.5 s**（<1800 s，exit 0，`VM_BUILD_JOBS=nproc=32`）。
- HDLBits DUT=001 回归通过（`[TB] dut_001 passed: one=1`）。
- 轮次结构不变性：新构建 `evals=200,102、rounds=402,258` 与 NO00043 完全一致。

### 正式 6 次交替复测：ACCEPTED（2026-09-19）

被测二进制 `ptmp/no00044_uarch_20260919/flow-final/emu/grhsim-compile/emu`
（正式 SV 路线构建，sha256 `37504dce7581ef9c303feb64e2f55b4f68b04686edf90a1141f398b724aff15d`）；
对照 old 为 NO00043 flow-final sha256 `9550498a…`（其正式三次 new 均值
77.917333 s）。6 次交替（`formal/summary.json`；预注册 old1/new1/old2/new2/
old3/new3；每次运行前对 old/new emu 均 posix_fadvise(DONTNEED) 驱逐；CPU2、
单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 77.998 | 75.333 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 77.605 | 75.349 | 0 | 同上 |
| 3 | 77.563 | 75.435 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **77.722000 s**（样本 SD 0.239944）、new 均值 **75.372333 s**
  （样本 SD 0.054857），降低 **3.023168%**。
- `max(new) 75.435 < min(old) 77.563`，Mann-Whitney U=0、单侧精确 p=0.05、
  Cohen d=−13.50、Cliff's delta=−1.0，**秩次判据通过**。

**最终判定：ACCEPTED（commit 均一 u64 端口组的紧凑 ctz 走查 + 描述符共享体，
+3.023168%，秩次判据通过，生成/编译门槛通过，100k 等价确认，HDLBits 回归
通过）。** 按新均值计算，GrhSIM-IR 为归档 gsim 46.965 s 的 **1.604912×**
（上一节点 NO00043 为 1.659065×）。

**语义约束**：紧凑走查仅作用于满 64 端口、组 guard 一致、全部为单写者直接
提交 u64 二态全掩码（next==data）单目标通知端口的 pflag 组；armed 位按 u64
一次读入、ctz 升序访问；enable 为 boundary 字节或 1 位常量（折叠进 flags）；
data 非常量（常量回退逐位）；组字节整清零与逐字节 `=0` 语义一致。IR、
GRH pass、映射、调度、布局、XiangShan 与测试源码均未改；轮次结构实测不变。

**保留实现**：wolvrix 子模块 commit（`lib/grhsim/backend/cpu_emit.cpp`
紧凑走查发射 + `include/grhsim/backend/cpu_emit.hpp` 签名 + pass 选项
`--commit-compact-walk` + `tests/grhsim/test_cpu_emit.cpp::testCommitCompactWalk`
+ `tests/grhsim/data/cpu_commit_batch.{mk,_main.cpp}` 聚焦夹具）；根仓库随本
报告归档的提交（`scripts/wolvrix_xs_grhsim_ir.py` 主流水线开启
`commit_compact_walk`、`scripts/reemit_grhsim_ir.py` `--commit-compact-walk`、
`Makefile` `GRHSIM_REEMIT_COMMIT_COMPACT_WALK` 透传、报告与索引）。

**被否决尝试**：变体 v1（armed 字节内全 8 lane 无分支扫描 + 逐 lane 开火）
筛选 **−0.837%** REJECTED——perf 显示 branch-misses −4.71% 成立但指令
+0.72%（SSE2 基线下每 lane ~8–9 条 cmp/cmov/shl），在前端约束 ~1.19
cycles/instr 下打平略亏；逐函数归因确认 commit 任务自身 +1.73G cycles。
教训：armed 过滤后的逐位内联常量链已是指令最优，"求值更多但以分支换指令"
在前端受限代码上净亏。v1/v3 模型/日志保留在 `ptmp/no00044_uarch_20260919/`
（flow-batch、screen1、probe_batch_A、rec_batch）。

**后续方向**：(a) u8/bool 族（47.9k 端口，当前未覆盖）可用同形态扩展——需
boundary 记录打包（cur 连续 + data/en 等距），SWAR 8 字节一字比较无须 SIMD；
(b) 混合 guard 组与不满 64 端口的尾组（本次未覆盖的 ~5k 端口）可用部分字
掩码扩展；(c) 微结构普查的剩余结论：compute 63% 为 72% 惰性激活的平坦载荷
（粒度细化已被 NO00036-A 证伪，需"近零固定成本"前提）、两侧 branch-miss
绝对量相等（≈4.5G/100k，数据熵主导）、指令选择余量 ~2%（AVX512 诊断值，
不可作机制）、L1i/L2 对 ~16 MB/eval 代码流完全容量失效（text 体积仍是长期
杠杆）；(d) 本节点证明 commit 走查的描述符化是可行方向，commit 剩余成本
（真开火体、写助手调用开销）仍未动。





