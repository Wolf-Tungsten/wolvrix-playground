# NO00035：布尔选择的 IR 语义与按位发射

日期：2026-09-16。最终阶段：**ACCEPTED（尝试 B）**。

新增 `grhsim.bitwise-muxes` 与 `core.compute.bitSelect`，将 **199429** 个
两态 unsigned bit mux 发射为按位选择。正式六次交替100k的Host均值
**105.865 → 102.506 s**，降低 **3.172909%**；max(new)102.711 <
min(old)105.742，U=0、单侧精确p=0.05。六次NEMU对拍及终点全部通过，
完整SV生成 **696.82 s**、fresh编译 **214.24 s**。compute静态条件跳转
减少 **42477（10.343442%）**，分区/存储/调度完全相同；总指令与ELF text略增。
同条件mux/concat融合A筛选未通过，已撤回。该节点确认布尔数据选择发射为
分支是一项局部成本，剩余与gsim的时间比为 **2.182604×**，没有解释全部差距。

根基线 `ea6b7cea0a5f8656d23341e980387248ad069af8`、wolvrix 基线 `1fb8feb`，
节点开始时两个工作树均干净。
NO00034 已完成；本节点由新的用户 goal 启动，不是其收尾延续。

机器为 AMD Ryzen 9 7950X3D，16核/32逻辑CPU。冻结的wolvrix基线为
`1fb8feb40d9bb7bca272bb4f04a069276a86be94`，XiangShan为
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`。CoreMark输入SHA256为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，
NEMU为`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

## IDEA 与诊断范围

起始假设使用NO00032历史诊断：compute占eval约78.65%；当前基线的独立诊断
见下文，二者分别记录。NO00034 的计算原生指令约
1500 万、条件跳转 410666，ELF text 103230628 bytes；100k Host 均值
104.594333 s，对 gsim 归档 46.965 s 的剩余差距为 2.227070 倍。

先审计同条件逐 lane mux 经 concat 拼接的依赖锥，探索将多个选择融合为
一次整字选择。创新目标是消除中间选择结果及其跨分区物化，由 GrhSIM IR
表达更大的纯计算，再由 emitter 发射融合表达式。若静态覆盖不足，或原生
代码/运行收益不支持，记录证伪并在同一节点继续；不重复 NO00026 的独立
分量拆分、NO00031 的置位 bit 分派或 NO00034 的缓存阈值调整。

不修改冻结 GRH、GRH pass、XiangShan 或基准源码；候选由类型、operand、
使用次数与依赖关系选择，不匹配模块名。静态候选数不等于执行次数或收益。

## BASELINE 与预注册

对照为 NO00034 `ptmp/no00034_local_cse_probe/flow-readcache-final`，预选
止损比较值为 104.594333 s；每次 emu 截止 **156.8914995 s**。生成和编译
从 Make 启动分别计时，启动前安装 `timeout --signal=KILL 1800s`，超时
立即终止进程树并隔离不完整产物。所有工作产物位于
`ptmp/no00035_compute_fusion_20260916/`。

仿真固定 CPU2、`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、100000 cycles，
CoreMark 两次迭代、NEMU 对拍，waveform/commit/RAM trace/profile 关闭。
有效终点为 instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c，
exit 0 且无 mismatch。输入及二进制身份在运行前后检查。gsim 配置不变，
复用归档，仅作目标差距参考。

筛选独立 old/new 一对；最终以新目录完整 SV→C++ 和 fresh 编译产物执行
**old1/new1/old2/new2/old3/new3**。主指标 Host、辅指标 emu 墙钟；报告
均值、样本 SD、效应量及精确单侧 U/p，要求 max(new)<min(old)。失败作废
并记录，全部有效结果保留；不把筛选样本或历史数据混入正式统计。
正式性能运行期间不并行编译、profile 或大型分析；模型编译使用 32 jobs。

本节点仅在统计收益、100k 正确性、完整生成/编译门槛及归档全部通过后
判定 `ACCEPTED`，统一提交子模块再提交根仓库并停止。以上口径在有效性能
运行前确定。

## 尝试 A：同条件 mux/concat 融合

静态审计确切 NO00034 checkpoint，得到 219203 个 scalar concat，其中
1630 组的全部独占 lane 都由同一 condition 的 mux 产生，覆盖 **31916** 个
不同 mux。另有 4071 个连续同条件段（含嵌套重复计数），第一版不处理部分段。
实际 task 为 compute 4453、domain-gated commit 490、always-scan commit 1，
因此不能将全部4944个task误当作逐轮必执行的commit调用。

`grhsim.fuse-mux-concats` 在 pack-bit-registers 后运行，选择精确宽度、
无参数/对象引用、1–64位两态 concat 的独占嵌套树。每个叶子必须是只有
一个使用点的 mux，true/false/结果类型完全相同，所有 condition 为同一
ValueId。改写成 `core.compute.muxConcat(condition,t0,f0,t1,f1,...)`，
lane按高位到低位排列；删除独占中间concat和mux，保留根ValueId后统一compact。
emitter发射 `condition ? concat(t0,t1,...) : concat(f0,f1,...)`，只构造
选中分支的拼接。读取operand本身无副作用，条件以非零为真，符号lane先按
各自宽度截断；不跨过共享值、不修改commit/事件/历史、不新增宽helper ABI。

局部目标 1–4% Host。31916/3945332约0.81%的静态节点覆盖不能直接换算收益；
省去的是其中选择、物化、比较及依赖传播的组合成本。若代码规模未改善、
同窗筛选无正向或最终六次不分离，则该尝试被否定。只修改后端IR与emit，
不重做全局CSE。

### 实现与小模型验证

新增 semantic pass、op 注册与 verifier、scalar emitter，以及共享/类型/形状
保护测试。生成的执行 fixture 覆盖嵌套 concat、64 位结果、signed lane 与
signed result、多位非零条件、共享 mux 保留、异条件保留、寄存器边沿快照、
重复 eval 与 init。两种 mapping 各执行 24576 次 eval / 3 次 init，启用
ASan/UBSan。JSON roundtrip 后再发射执行；已有 mapping 必须被 semantic
pass 丢弃。

`make test_grhsim_cpu_emit test_grhsim_cpu_mapping test_grhsim_cpu_schedule`
通过：emitter 100.84 s，IR/mapping/schedule 各约 0.01 s，整个 Make
108.38 s、exit 0。首次测试因新 fixture 将 InputId 与 ValueId 放在同一
`const auto` 声明中而编译失败；拆分声明后完成上述验证。该编译失败没有
产生性能样本。

从确切 NO00034 checkpoint 筛选重发射 60.69 s、fresh 编译 221.15 s，
均 exit 0；重发射时间不计作完整 SV 生成门槛。实际融合 1630 组、31916
lanes，删除 31916 个 op；此设计中的候选没有额外嵌套 concat 被删除。

| 静态量 | NO00034 old | 尝试 A |
|---|---:|---:|
| semantic ops | 3945332 | 3913416 |
| mux ops | 787256 | 755340 |
| concat ops | 232137 | 230507 |
| muxConcat ops | 0 | 1630 |
| compute tasks | 4453 | 4428 |
| gated / unconditional commit tasks | 490 / 1 | 490 / 1 |
| boundary values | 835511 | 834035 |
| boundary bytes | 2186824 | 2184792 |
| object bytes | 25714368 | 25714368 |
| runtime bytes | 5414 | 5390 |

边界存储只少 2032 bytes，不能据此声称消除了主要存储成本；当前证据只是
选择节点及其调度/变化检查的静态减少。

### A 筛选：REJECTED

old/new Host **105.957 / 107.375 s**，emu wall **105.99 / 107.40 s**；
候选表观慢 **1.338279%**。两次 Make/emu 均 exit 0，100k 精确终点及
NEMU 对拍通过。n=1+1、单侧精确 p=1.0，不声称已证明真实回退，但它没有
支持预注册的正向筛选标准，因此 A 不进入完整 SV 与正式六次性能验证。
所有输入及两个 emu 的 SHA256 在运行前后相同。旧 emu 为
`8d61acafd3250768f0fade709ffce65c3fafc8b9a75c9fc9b0a8c0aa2af7dd42`，
A 为 `6353b15250c5db491eab132561478187b680d2a05d1863551cded7a6e49ac9c9`。
完整融合覆盖不足 1% 的 semantic ops，且经过 remapping，不能把这一对
测量的差值全归因于某个机器码结构。继续在本节点审计选择计算的更大覆盖面。

A 原生静态 compute 指令 15005705→14937193（−68512，−0.456573%），
条件跳转 410666→410187（仅−479），ELF text 103230628→102885984 bytes。
commit 指令 2135503→2135721、calls 79661→79735。融合操作数后仍需生成
各 lane 的拼接；大部分中间选择原本已在本地，源码 op 减少没有转成大幅机器码
减少。A 源码与 fixture 已撤回，仅保留本节过程记录与通用静态分析工具。

## 当前基线诊断

对确切 NO00034 emu 独立执行 200 Hz CPU 采样与相位计时，Host 106.820 s、
emu wall 106.86 s，exit 0、100k 预期终点/NEMU PASS。此运行不进入性能统计。
evals=200102、rounds=402258；tick total 106.763068 s，model_step
106.330461 s，difftest 0.334493 s。eval 106.419701896 s 中 compute
81.963052026 s、commit 22.672859108 s、publish 1.623816040 s。
compute 占 eval **77.018682%**，模型执行占 tick **99.594797%**，对拍不是
当前主要成本。

共 21367 samples（period 5000 µs），compute task 14854（69.518416%）、
commit task 3645（17.059016%）、evaluator 689（3.224599%）、external
209（0.978144%）。2767 个 compute task 有样本，前十合计896个，仅占
总样本约4.19%；热点仍然分散。分析器核对终止标记、ELF映射、全部4944个
task与样本总数。该诊断定位compute，但不能直接把样本归为mux分支成本。

## 尝试 B：布尔 mux 变为逐位选择

扩大覆盖面的方向是消除硬件 bit 数据选择被 C++ `?:` 表达为控制流的成本。
审计同一基线找到 **199429** 个完全同类型 unsigned two-state 1-bit mux，
占全部 semantic ops约5.055%，是A覆盖量的约6.25倍。producer已经求值，
可将 `mux(c,a,b)` 改成 `bitSelect(c,a,b)`，emitter发射
`(c & a) | ((c ^ 1) & b)`。原 op/result/operand IDs、共享与依赖保持；不通过
删除共享计算改变通知图，需检查 remapping 后的分区、layout和schedule一致性。

新op的通用定义是逐位mask选择，所有operand/result同TypeId、1–64位两态：
`bitSelect(mask,t,f)[i] = mask[i] ? t[i] : f[i]`。这与多位mux的非零谓词
不同，所以自动转换严格限于unsigned bit。signed bit、多位条件、不同类型、
四态、参数或对象引用不转换；原state/DPI/commit求值与边沿快照保留。
完整语义及例子见[bitwise-muxes](../wolvrix/docs/grhsim_ir/passes/bitwise-muxes.md)。

局部目标1–5% Host；覆盖数不等于执行频率，不能把77% compute当成潜在收益。
机器码应减少由数据选择引入的条件跳转，同窗筛选应正向，最终仍需六次秩次
分离。若编译器原本已使用无分支选择、额外位运算抵消收益或正式样本不分离，
则否定本尝试并继续本节点。A的完整融合代码不与B叠加。

B 小模型验证通过：`make test_grhsim_cpu_emit test_grhsim_cpu_mapping
test_grhsim_cpu_schedule` 总墙钟127.34 s、exit0；emitter112.50 s，
IR/mapping/schedule各0.01 s。两种mapping各24576次eval / 3次init，
ASan/UBSan下遍历全部bit选择组合，检查嵌套与共享结果、多位非零条件保持
原mux、5位signed与64位通用mask的独立逐bit参考、同边沿两级寄存器快照、
连续eval、幂等、mapping失效与JSON roundtrip。另验证8种不转换条件及
7种非法bitSelect被拒绝。没有以源码形式断言替代行为scoreboard。

B checkpoint筛选重发射60.37 s，fresh编译221.06 s，均exit0；这些是筛选
构建，不能代替完整SV门槛。独立Python逐字段比较确认：恰199429行op名称
改为bitSelect、字符串表仅追加该op，其余semantic sections、operand/result
IDs、pool计数、partition、layout（含helper输入缓存）、schedule均完全相同。
没有删除或新增operation/state/value；task4944、boundary2186824 bytes、
object25714368 bytes、runtime5414 bytes与基线一致。
`make run_hdlbits_grhsim_ir DUT=086/097 SKIP_PY_INSTALL=1`通过16位byte-enable
寄存器与下降沿reset验证。筛选运行已在编译、静态分析和这些回归结束后启动。

B 筛选 old/new Host **105.763 / 102.634 s**，emu wall **105.79 / 102.66 s**，
表观降低 **2.958502%**。两次Make/emu均exit0、预期100k终点一致、NEMU PASS；
运行前后输入与二进制哈希相同。B筛选emu SHA256为
`e845de594c9b8ac713688ac58adccc56c87fb823b156d7565995856977640c9e`。
n=1+1的精确单侧p=0.5，仅支持进入下一验证阶段，不作接受依据。

### B 原生代码与局部根因

同样的 `clang++ -std=c++20 -O3` 编译路径下，完整静态反汇编比较如下。
4944个task内容/ID对应关系已经IR逐字段比较确认，可逐task比较。

| 指标 | old | B | 变化 |
|---|---:|---:|---:|
| compute 指令 | 15005705 | 15203003 | +197298（+1.314820%） |
| compute 条件跳转 | 410666 | 368189 | −42477（−10.343442%） |
| compute 全部跳转 | 492759 | 432846 | −59913 |
| compute call | 65623 | 65622 | −1 |
| commit 指令 / 条件跳转 / call | 2135503 / 374355 / 79661 | 2135503 / 374355 / 79661 | 0 |
| evaluator 指令 / 条件跳转 | 27653 / 6460 | 27653 / 6460 | 0 |
| ELF text bytes | 103230628 | 103826836 | +596208（+0.577550%） |

例如同一task1025的条件跳转512→16，指令6232→6636；task1026为511→16，
task3800为420→18。它们是全量分析后按跳转减少排序的示例，不是变换选择条件。
task1025中boundary结果909061的两种生成式（省略相同截断/changed通知）为：

```cpp
// c = local[61], t = cached value 2793239, f = boundary[899926]
boundary[909061] = c ? t : f;                 // old
boundary[909061] = (c & t) | ((c ^ 1) & f);  // B
```

old 原生地址0x18c28a8起为`test %r11b,%sil; jne ...; movzbl
0xdbb56(%rcx),%r15d`，通过条件跳转选择是否读取f，再写同一0xddf05结果槽。
B在0x18def5e起先读同一0xdbb56，再执行`xor; and; xor`选值，并写同一结果槽；
此处数据选择跳转消失。该例的源位本来已由producer求值，两路读取无副作用，
因而可用按位算术表达选择。IR资格证明让后端无需保留软件控制流含义。

因此，这次机制针对的是 **布尔数据选择被发射为分支** 的局部成本，未减少
状态/边界存储或调度任务，也不是靠减少静态指令总数。没有硬件branch-miss或
动态指令计数，不能将42477条静态跳转减少等同于某个执行次数或误预测比例。
代码大小略增、无条件读取两路数据也有代价；筛选净收益及最终统计须同时成立。
它与NO00031的logicAnd/logicOr规范化同属两态数据运算方向，但覆盖的是尚未处理
的三操作数选择，并通过独立bitSelect语义与相同mapping隔离机制。

## B 完整验证的复现命令

以下从根仓库运行，使用全新 `flow-b-final`，不从已有flat GRH或GrhSIM checkpoint
恢复，也不复用筛选构建的object。生成和编译分别预装1800s进程组截止。
完整生成期间并行执行筛选二进制的静态反汇编；正式仿真窗口不并行重工作。
代码在B筛选通过后保持不变。正式测量命令预注册如下。

```bash
node_dir="$PWD/ptmp/no00035_compute_fusion_20260916"
flow="$node_dir/flow-b-final"
old="$PWD/ptmp/no00034_local_cse_probe/flow-readcache-final"
mkdir -p "$flow" "$node_dir/work-tmp" "$node_dir/pip-cache" "$node_dir/ccache"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export CCACHE_DIR="$node_dir/ccache" CCACHE_DISABLE=1
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00035_bitselect_final_generate > "$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00035_bitselect_final_compile > "$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-b" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=104.594333 \
  > "$node_dir/formal-b.log" 2>&1
```

筛选重发射用同一环境与1800s包装器执行：

```bash
make --no-print-directory reemit_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_REEMIT_MODEL="$old/xiangshan_grhsim_ir.json" \
  GRHSIM_REEMIT_FLOW="$node_dir/flow-b-probe" \
  GRHSIM_REEMIT_BITWISE_MUXES=1 GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT=0
```

随后编译参数同完整构建，flow换成`flow-b-probe`、RUN_ID为
`no00035_bitselect_b_compile`；筛选benchmark的new指向该flow、output为
`screen-b`、pairs=1。A相应目录为`flow-a-probe`/`screen-a`，当时重发射选项为
`GRHSIM_REEMIT_FUSE_MUX_CONCATS=1`（已随失败实现撤回），编译RUN_ID为
`no00035_muxconcat_a_compile`。A使用基线加本文所述muxConcat变换与emit，
其余资源、输入、deadline及运行口径相同，未执行完整SV与正式六次。

诊断与比较均由已有或本节点新增Make目标调用，不直接运行Python工作流：

```bash
make profile_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_PROFILE_FLOW="$old" GRHSIM_IR_PROFILE_OUTPUT="$node_dir/profile-old" \
  GRHSIM_IR_PROFILE_BASELINE_SECONDS=104.594333
make analyze_grhsim_mux_fusion PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_MUX_FUSION_MODEL="$node_dir/flow-b-probe/xiangshan_grhsim_ir.json" \
  GRHSIM_MUX_FUSION_REFERENCE="$old/xiangshan_grhsim_ir.json"
make analyze_grhsim_cpu_code PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_CPU_CODE_OLD="$old" GRHSIM_CPU_CODE_NEW="$node_dir/flow-b-probe"
make test_grhsim_cpu_emit test_grhsim_cpu_mapping test_grhsim_cpu_schedule
make run_hdlbits_grhsim_ir DUT=086 SKIP_PY_INSTALL=1 PYTHON="$PWD/.venv/bin/python"
make run_hdlbits_grhsim_ir DUT=097 SKIP_PY_INSTALL=1 PYTHON="$PWD/.venv/bin/python"
```

静态机会审计old/A时仅传各自MODEL，不传REFERENCE；A机器码比较另设
`GRHSIM_CPU_CODE_PHASE_ONLY=1`，因为task内容改变不能逐ID对应。
全部日志、checkpoint、生成代码、profile与二进制留在`ptmp/`，不提交。

完整SV生成实测 **696.82 s**（脚本内部690.577 s），Make exit0，低于1800s。
bitwise-muxes pass本身0.401 s。fresh-session JSON store/load/store逐字节一致；
与old的flat GRH SHA256同为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`。
XiangShan工作树仍干净，冻结GRH与GRH pass源码未改动。
完整路线的GrhSIM checkpoint与B筛选版逐字节相同；C++、header、runtime和
Makefile逐文件相同（排除编译产物`.o/.a/.tmp`），因此上述IR与生成代码证据
适用于最终路线。新目录独立fresh编译 **214.24 s**、exit0，低于1800s，
未触发任何时间截止。

## VALIDATED：正式六次交替结果

2026-09-16 11:04–11:15（Asia/Shanghai），按预注册的
old1/new1/old2/new2/old3/new3顺序执行。每次CPU2、单线程、100000 cycles，
关闭trace/profile；全部Make/emu退出码0/0，Difftest enabled且无mismatch，
均为instrCnt=240349、cycleCnt=99996、IPC=2.403586、guest=100001、
PC=0x80000c0c。没有无效样本、补跑、回归截止或剔除异常值。

| 顺序 | Host (s) | emu wall (s) | Make / emu exit | 对拍及终点 |
|---|---:|---:|---|---|
| old1 | 105.742 | 105.77 | 0 / 0 | PASS |
| new1 | 102.565 | 102.59 | 0 / 0 | PASS |
| old2 | 105.794 | 105.82 | 0 / 0 | PASS |
| new2 | 102.711 | 102.74 | 0 / 0 | PASS |
| old3 | 106.059 | 106.09 | 0 / 0 | PASS |
| new3 | 102.242 | 102.27 | 0 / 0 | PASS |

old Host均值 **105.865000 s**、样本SD **0.170009 s**、范围
105.742–106.059 s；new均值 **102.506000 s**、样本SD **0.240002 s**、
范围102.242–102.711 s。均值差 **−3.359000 s**，按
`100*(1-new_mean/old_mean)` 降低 **3.172909%**。组内CV分别0.160590% /
0.234135%；emu墙钟均值105.893333 / 102.533333 s，方向一致。

max(new) **102.711** < min(old) **105.742**，分离间隔 **3.031 s**。
Mann–Whitney U(new)=0，枚举20种3+3分组的单侧精确p=**0.05**，通过秩次门槛；
Cliff delta=**−1**，Cohen d(new−old)=**−16.151279**。d反映本窗口较小的
组内离散度，不作为跨机器效应保证。全部六次均报告，筛选与诊断未混入。
旧均值与NO00034历史104.594333 s不同，正式提升只相对本窗口105.865 s计算；
历史均值仅用于预选止损值，避免跨窗口漂移成为收益证据。

正式old emu SHA256为
`8d61acafd3250768f0fade709ffce65c3fafc8b9a75c9fc9b0a8c0aa2af7dd42`，
正式new为`4b7a5d4622197d44b8957ac7658548890bf60c8839e097bbbdaad17b58f07e35`。
输入与两个二进制在运行前后哈希一致。new使用完整SV路线后的全新编译产物，
与筛选版的二进制身份分别记录，未用筛选emu替代正式构建。

## ACCEPTED 与边界

保留B：类型/语义证明、生成C++独立scoreboard、ASan/UBSan、IR/mapping/
schedule、HDLBits086/097、完整SV与fresh编译门槛、100k NEMU及六次统计全部通过。
保留源码包括pass/op/verifier/emitter、测试、语义文档、默认流水线集成与
静态审计工具。A的代码和fixture撤回，保留完整失败过程与未执行阶段说明。

证据链是：当前模型计算占eval约77.02%，布尔mux覆盖199429个op；只改变
选择的语义表达，所有依赖、分区、布局与调度相同；原生数据选择分支减少，
commit/evaluator静态规模相同；最终同窗六次确认净收益。因此确认的是一种
普遍分布的计算表达成本，不是“整个2.18倍差距都来自分支误预测”。没有测量
branch-miss、动态op次数或当前新模型的相位占比，不将静态计数当成这些指标。

按归档gsim 46.965 s，最新IR均值为 **2.182604×**，高 **55.541 s
（118.260407%）**。gsim配置不变、未重跑，也未参与本节点交替窗口；该比值
只表示剩余追赶距离。主要剩余工作仍在大量compute值的选择、物化与活动传播；
后续机制需先取得对应动态覆盖证据，再决定更大依赖锥或执行机制的变换。
本节点完成后停止，不启动NO00036。

最终wolvrix实现提交：`ff83ba2c17961d010b9729d3d0007e42ce6c7797`
（`feat: lower boolean muxes to bitwise selection`）。根仓库以
`feat: accept NO00035 bitwise mux selection`一次归档默认流水线、工具、该子模块
指针、本报告、索引与goal更新；该提交可用
`git log --diff-filter=A --format='%H %s' -- pdocs/NO00035-grhsim-ir-bitwise-muxes-20260916.md`
定位。两个仓库均仅在节点接受后提交，没有阶段提交或生成产物入库。
