# NO00031：布尔谓词的数据流规范化

日期：2026-09-15。最终阶段：**ACCEPTED**。

本节点保留的候选是 `grhsim.bitwise-predicates`：将377635个已求值的一位两态
逻辑与/或规范化为位运算，配合CPU emitter生成直接bool数据运算。计算任务的
静态条件跳转减少15.00%，完整生成/编译通过，六次交错100k均对拍通过。
Host均值 **122.377667→118.631667 s**，降低 **3.061016%**；max(new)118.886
<min(old)122.062，U=0，单侧精确p=0.05。距离gsim归档46.965 s仍为2.525959倍。
先前按置位bit分派活动任务的候选A慢13.18%，已撤回，以下保留其完整过程。

## 基线、假设与判据

根基线 `6eb87486a091cec5e3647d848761f23cf37183d1`，wolvrix 基线
`75be3ad8a2508f49a0be92e31ddba8d77f0e9044`（NO00030），开始时两仓库干净。
沿用 NO00030 的完整模型/二进制为 old，正式比较在本节点重新交替测量。
沿用 gsim 46.965 s，仅表示追赶目标，不作为同窗因果对照。

NO00030 的基线相位诊断显示 model_step 占 99.60%，其中 compute 76.78%、
commit 21.64%；该比例来自 NO00029，不冒充本次基线的新测量。
NO00030 静态模型有 3,994,535 个 operation、875,735 个 boundary value、
4,467 个 active word 和 4,972 个 task。每个非空 compute 活动字仍检查所有
已分配的 bit；这提供一个可测量的活动扫描假设，但尚没有动态稀疏度证据，
不能据此认定是剩余 2.59 倍差距的主要原因。

候选 A 在同一个 active word 内按最低置位 bit 分派对应 supernode。
不建立跨 task 队列，不改变 task 的顺序。每次执行清除该 bit，沿用现有
通知规则：同字中更高的 bit 加入局部活动字，已过位置或其他字的通知写回
持久 flags。因而每个字内的可执行 bit 按原 activeId 升序执行。
最后不满八个 unit 的 padding bit 无对应运算，default 清除它们。
此候选只改 CPU emitter，语义 IR 与 mapping 保持，作为核心活动执行方向的
第一次证伪实验；不以源码检查数代替动态成本。

局部探索目标为 1–5%，不是接受硬阈值；最乐观的上界也只能来自实际被省去的
bit 检查成本，不能把全部 compute 时间当作潜在收益。候选可能增加间接跳转、
循环和分支预测成本；若对拍失败、截止触发或同窗统计不分离，否定该次尝试并
在同一节点继续改进。

## 资源与验证约定

仿真 CPU 2，单线程，100000 cycles，CoreMark 两次迭代镜像，NEMU 对拍，
waveform/commit/RAM trace、progress 和 profile 均关闭。
预选 NO00030 正式三次 Host 均值 121.836667 s，1.5 倍止损为 182.7550005 s。
正式顺序 old1/new1/old2/new2/old3/new3，主指标 Host，另报 emu wall。
要求 max(new)<min(old)，报告均值、样本 SD、效应量、单侧精确 U/p。
筛选使用独立目录的一对 old/new，不混入正式三对。
生成、编译均由 `timeout --signal=KILL 1800s` 包住 Make 及子进程组。
所有流程通过根 Make 目标，日志与产物在 `ptmp/no00031_sparse-active-dispatch_20260915`。

## 候选 A 实现与过程

修改 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`，增加只接收非零 uint8 的
最低置位查询并发射 `while`/`switch`。宽值 helper ABI 没有变化。

- 第一轮 emitter 测试发现生成 switch 的多余闭括号，已修正。
- `make test_grhsim_cpu_emit test_grhsim_cpu_mapping` 随后通过：emit 69.85 s，
  IR/mapping 各 0.01 s，包含生成模型 ASan/UBSan、helper 拆分、状态事件等已有回归。
- 第一次完整生成在 hier-flatten 期间被代理误发 Ctrl-C 中断，session 15590
  返回 130。没有生成终点、没有可计时间和性能结果。重跑前未正确隔离目录且
  复用了 RUN_ID，原始日志被覆盖；此前 commentary 中“目录已隔离”不准确。
  保留这一过程缺陷，不能把中断尝试算作成功、失败性能数据或时间门槛证据。
- 重跑 session 28770 完整生成成功：Make wall **664.97 s**、exit 0，内部
  **659.155 s**，fresh-session GrhSIM JSON 往返一致。fresh 编译 **248.28 s**，exit 0。

## 候选 A：REJECTED

新旧 GrhSIM IR checkpoint（包含 mapping）逐字节相同。ELF text 从
112,707,382 增至 113,341,458 bytes（+634,076），新增循环和 switch 没有缩小
机器代码。独立单对筛选 `screen-a`：old Host **120.936 s** / wall **120.97 s**，
new Host **136.881 s** / wall **136.91 s**，Make/emu 均 0/0，均为精确终点
instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c，NEMU 无 mismatch。
候选慢 **13.184660%**。未进入正式六次，已撤回全部候选 A emitter 改动。
此结果否定按最低置位分派的实现，不证明所有 bit 扫描成本都为零；循环和
多目标跳转增加的成本可能超过省去检查，具体占比需要采样证据。

## 候选 B：布尔谓词的位运算规范化

当前 old 的新采样运行（独立诊断，不进入性能基线）Host 122.723 s，100k
NEMU 正确终点，Make/emu exit 0/0。model_step=122.222862 s；eval=122.311162035 s，
compute=93.476219076 s、commit=27.027434498 s、publish=1.659634767 s；
evals=200102、rounds=402258。200 Hz 采样 24548 个：compute task 17116
（69.724621%）、commit task 4420（18.005540%）、evaluator 741（3.018576%）。
有采样的 compute task 为 2924 个，前十仅 676 samples；热点分散，不能把
一个小 helper 当作全局根因。分析脚本验证了样本总数、终止标记、ELF 映射、
符号范围及全部 4972 个 task 的相位归属。

最初采样包装器的 profiler 诊断 regex 不匹配实际格式，包装器后处理 exit2；
emu 自身 exit0、profile 已完整产生。修正 parser，并使用 Make 分析保存的
`cpu.prof_26`（唯一非空 profile），没有重跑诊断以挑选样本。

当前 IR 中 logicAnd=243868、logicOr=139175；其中输入及输出全部 unsigned
two-state logic<1>、无参数/对象引用的分别 **238460 / 139175** 个，合计
**377635**。其中 boundary 结果 **141055 / 47516**，合计 **188571**。
统计脚本首版错误地假定 JSON type 只有6列而漏计，已按真实8列 schema修正，
不使用首版零计数作推断。

创新点是将已物化的布尔 SSA 数据依赖规范化为 eager bitwise 运算，而不是
在生成 C++ 中再次引入短路控制依赖。每个输入已求值，值域严格为 {0,1}，所以
`logicAnd(a,b)` 等价于 `and(a,b)`，`logicOr(a,b)` 等价于 `or(a,b)`。
例如 a=0,b=1 时 AND=0、OR=1；a=1,b=1 时二者均1。宽输入（如2和4）不能
这样改写，因为逻辑与为1而位与为0；signed1/四态/有参数同样保留。

新增 SemanticTransform [grhsim.bitwise-predicates](../wolvrix/lib/grhsim/pass/bitwise_predicates.cpp)，放在已有 CSE/clone
之后，保留 operation/value 身份、数量和依赖，不另做跨锥合并。mapping 随
语义变换失效后重建。[CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp) 对一位无符号位运算直接使用 bool operands，
免去通用宽度转换包装；commit、通知和所有副作用仍由原调度实现。
参考 gsim `instsAnd/instsOr` 的位表达式策略；legacy scalar logical emit 则也
使用 &&/||，因此不能宣称此问题为 IR 独有或足以解释全部差距。

探索目标仍为1–5%；若机器码分支/运行时间未减少，则短路假设不成立。
覆盖数字不是动态执行量。先做逐类型保护和生成模型真值表/状态检查，再在
独立目录执行完整 SV 生成和 fresh 编译筛选；通过后做独立六次交替。

### 实现与聚焦验证

新增 pass 的注册、实现和文档，以及 CPU emitter 中的标量 bool 表达式规则；
XiangShan 和 HDLBits IR 公共流水线在 clone 后运行此 pass。
`XS_WOLF_GRHSIM_IR_BITWISE_PREDICATES=0` 可关闭 IR 规范化，默认开启。
该开关在完整生成启动后加入 Python 脚本；已启动的进程此前加载了同样默认
开启的流水线。同期 pass 新增显式 `<vector>` include，仅补齐依赖。

`make test_grhsim_cpu_mapping test_grhsim_cpu_emit` 通过，IR/mapping 各0.01 s，
emit 72.89 s。新增 IR 测试检查位宽/符号/四态/参数保护、实体数量、语义 revision、
幂等和 JSON 往返；生成模型在普通分区和强制单操作 helper 两种映射下，分别做
393216 次真值表、宽值及 signed fallback、上升沿写入、重复 eval 和三次 init，
启用 ASan/UBSan。映射先建立、变换后检查失效、再重建。

`make test_grhsim_cpu_schedule test_grhsim_cpu_profile test_benchmark_grhsim_ir`
通过；两组脚本各2项测试，调度0.01 s。
`make run_hdlbits_grhsim_ir DUT=086/097 SKIP_PY_INSTALL=1` 分别验证 byte-enable
寄存器和带复位的下降沿事件锁存，均通过。
节点收尾对最终源码再次执行上述IR/mapping/emit/schedule和脚本自测，全部通过：
emit72.86 s，其余C++套件各0.01 s。该轮补验生成时新增显式include后的最终源码，
未再运行性能实验。没有修改XiangShan或HDLBits测试源码；新增fixture属于GrhSIM测试。

完整 SV→C++ 为 **672.64 s**（内部658.051 s），exit0，fresh-session IR roundtrip
逐字节相同。flat GRH SHA256 与 old 均为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`，
生成模型 header 也逐字节相同。

完整 IR 检查确认 counts/strings/types/values/states/init/mappings 等15个非 operation
section 全部相同；3,994,535 个 operation 中恰好238460个 logicAnd→and、139175个
logicOr→or，每行其余字段完全相同。因而 task数4972、compute4467/commit505、
active word4467、boundary875735及全部依赖、布局与通知策略相同。
还保留5408个非适用 logicAnd；logicNot95943个未改变。
首次分析 Make 调用漏设 WOLF_ENV_SOURCED，在入口即拒绝，未执行分析；补全环境后成功。

fresh 编译 **231.46 s**，exit0。模型 C++ 使用 `-std=c++20 -O3`、32 jobs，
候选 ELF text为110552534 bytes，old112707382，减少2154848 bytes。
emitter 同时精简已有一位 bitwise AND/OR 的 cast 包装，因此将本次性能归因于
“IR 规范化与 bool emit 协同”的整体；不能从这一组实验独立估计各自贡献。

### 机器码证据与局部根因

使用 [机器码分析工具](../scripts/grhsim_cpu_code_stats.py) 通过
`make analyze_grhsim_cpu_code` 遍历两个 ELF 的反汇编，以生成 evaluator 的调度
区间识别 compute/commit，检查全部4972个 task的符号覆盖。下表为静态指令数，
包含 objdump 识别的对齐指令，不是动态执行量或 branch-miss 计数。

| 项目 | old | new | 变化 |
|---|---:|---:|---:|
| ELF text bytes | 112707382 | 110552534 | −2154848（−1.911896%） |
| compute 指令 | 15445604 | 15033251 | −412353（−2.669711%） |
| compute 条件跳转 | 784241 | 666606 | −117635（−14.999853%） |
| compute 全部跳转 | 940045 | 792190 | −147855 |
| compute call | 65260 | 65260 | 0 |
| commit 指令 / 条件跳转 | 2925709 / 539754 | 2925709 / 539754 | 0 |
| evaluator 指令 / 条件跳转 | 27731 / 6486 | 27731 / 6486 | 0 |

选择静态条件跳转减少最多的 task140作可读例子，不按名称触发优化，也不声称
它是运行时最热任务。其条件跳转687→15，指令3056→1392。以下表达式两端的
arena及偏移在新旧完全相同：

```cpp
// old: result boundary offset 2189695
result = bool(object_bool_1148031 && boundary_bool_2189454);
// new
result = bool(object_bool_1148031 & boundary_bool_2189454);
```

old机器码在对象偏移0x11847f（1148031）执行`cmpb $1`和`jne`，仅非零分支
读取boundary偏移0x21688e（2189454），另一分支产生0，再写0x21697f（2189695）。
new变成三条连续指令：`movzbl boundary`、`and object`、`mov result`。同一块内
大量已物化 bool 的逻辑依赖因此从分支网络变成字节数据运算。

这证明旧 emit 为部分纯布尔值引入了可避免的控制依赖，且改写确实减少了
相应机器码。IR/mapping逐项一致排除了分区和状态删减的混杂。净运行收益仍由
下面的交错实验判定；没有硬件 branch-miss 数据，不能把所有收益归给分支预测。
这也是局部根因，不能解释全部约2.6倍的差距。

### 筛选与正式验证

单对筛选old Host **122.605 s** / wall **122.63 s**，new **118.504 s** / **118.53 s**，
均Make/emu exit0/0且精确100k终点一致，无NEMU mismatch。候选快**3.344888%**；
n=1+1单侧精确p=0.5，仅用于进入正式实验。机器码分析同期绑定CPU3运行，
该筛选不混入正式样本。正式测试期间无本节点编译或CPU采样任务并行。
正式六次以独立目录`formal-b`预注册，2026-09-15 21:23:28（Asia/Shanghai）开始；
21:35:33完成。全部6次有效，无补跑、无超时、无非零退出。

| 顺序 | Host s | emu wall s | Make / emu exit | 100k NEMU与终点 |
|---|---:|---:|---|---|
| old1 | 122.062 | 122.09 | 0 / 0 | PASS，一致 |
| new1 | 118.886 | 118.92 | 0 / 0 | PASS，一致 |
| old2 | 122.885 | 122.91 | 0 / 0 | PASS，一致 |
| new2 | 118.579 | 118.61 | 0 / 0 | PASS，一致 |
| old3 | 122.186 | 122.21 | 0 / 0 | PASS，一致 |
| new3 | 118.430 | 118.46 | 0 / 0 | PASS，一致 |

六次均为instrCnt=240349、cycleCnt=99996、IPC=2.403586、guest cycles=100001、
PC=0x80000c0c、harness cycles=100000/max_cycles=100000，明确启用Difftest且无mismatch。
输入和二进制运行前后哈希相同。waveform/trace/progress/profile均关闭；诊断采样
在六轮全部结束后才启动。

Host old均值**122.377667 s**、样本SD**0.443717 s**；new均值**118.631667 s**、
SD**0.232517 s**。按`1−mean(new)/mean(old)`降低**3.061016%**，绝对减少
**3.746000 s**，速度比1.031577。new−old的Cohen d为**−10.575242**，
Cliff delta=**−1**。全部new<全部old，Mann–Whitney U=**0**，枚举n=3+3的20种
分组得到单侧精确p=**0.05**，满足预注册秩次门槛。样本量小，大d主要反映
本窗口组内离散度，不能推导跨机器或全工作负载收益。

wall old均值**122.403333 s**、SD**0.442869 s**；new均值**118.663333 s**、
SD**0.234592 s**，降低**3.055472%**，同样完全分离。old三次范围122.062–122.885，
跨度0.823 s；最慢new与最快old仍间隔3.176 s。没有用较早筛选或历史old补足统计。

gsim沿用46.965 s归档，不重跑；新均值为其**2.525959×**，高**71.666667 s
（152.595905%）**。它的100k终点为instrCnt238550、cycleCnt99998、PC0x80000b40、
guest100001，与IR的harness进程范围各自保持。该比率仅表示剩余追赶距离，
不是同窗因果效应，也不意味着两条路线100k区间完成同样指令数。

## 输入、版本及完整复现

主机corvus02，AMD Ryzen 9 7950X3D，16核32逻辑CPU，约187 GiB内存；
Clang22.1.2（ELF记录LLVM revision `1ab49a973e210e97d61e5db6557180dcb92c3e98`）。
old复用NO00030完整构建，新旧harness、RTL、GRH pass、镜像及NEMU相同。
输入身份如下，哈希只用于复核，正确性由对拍和精确终点判定：

| 对象 | SHA256 |
|---|---|
| CoreMark `coremark-2-iteration.bin` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU `riscv64-nemu-interpreter-so` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| old emu | `9bed364b7c5339bcf64b1a549f2716722e69842d865297d4fcd684617062d605` |
| new emu | `53824635c5ea5be9d271c7470a7749dfa5bd7f4c6b7d3ea79c966842b885d241` |

在根目录执行以下命令。`old_flow`指向NO00030的已生成构建；重建old需在基线
commit上执行相同完整生成/编译流程。新输出目录必须尚不存在，每次实验选择
独立目录及RUN_ID。Make目标负责安装/生成/编译，不直接运行底层工具。

```bash
node_dir="$PWD/ptmp/no00031_sparse-active-dispatch_20260915"
old_flow="$PWD/ptmp/no00030_localize_20260915/flow-bijective-final"
flow="$node_dir/flow-predicates-final"
mkdir -p "$node_dir/work-tmp" "$node_dir/pip-cache" "$flow"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32
export PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD="$flow" XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00031_predicates_generate \
  >"$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00031_predicates_compile \
  >"$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old_flow" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-b" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=121.836667 \
  >"$node_dir/formal-b.log" 2>&1
```

筛选只将`PAIRS`改为1、输出目录改为`screen-b`。候选A使用相同生成/编译
和筛选目标，目录`flow-active-bit`/`screen-a`，生成RUN_ID为
`no00031_active_bit_generate`（见前述中断与复用缺陷）。正式脚本为每轮指定独立RUN_ID，
预注册输入与二进制哈希，清除LD_PRELOAD/CPUPROFILE，设置运行期profile为0，
再经`run_xs_wolf_grhsim_ir_emu`固定CPU2执行。该目标实际参数为镜像路径、
`--diff`上述NEMU、`-b 0 -e 0 -C 100000`；不启用waveform、commit/RAM trace、progress。
`timeout --signal=KILL 182.755000s`包住emu进程组，time仅测emu区间；Host由emu报告。
脚本每0.5秒检查失败标记，失败立即杀进程组；生成和编译time从Make启动计至目标完成。

诊断与静态核对同样通过Make，profile独立运行，不进入六轮性能样本：

```bash
make analyze_grhsim_predicates PYTHON=.venv/bin/python \
  GRHSIM_PREDICATE_MODEL="$flow/xiangshan_grhsim_ir.json" \
  GRHSIM_PREDICATE_REFERENCE="$old_flow/xiangshan_grhsim_ir.json"
make analyze_grhsim_cpu_code PYTHON=.venv/bin/python \
  GRHSIM_CPU_CODE_OLD="$old_flow" GRHSIM_CPU_CODE_NEW="$flow"
make profile_grhsim_ir PYTHON=.venv/bin/python GRHSIM_IR_PROFILE_FLOW="$flow" \
  GRHSIM_IR_PROFILE_OUTPUT="$node_dir/profile-new" \
  GRHSIM_IR_PROFILE_BASELINE_SECONDS=121.836667
make test_grhsim_cpu_mapping test_grhsim_cpu_emit test_grhsim_cpu_schedule \
  test_grhsim_cpu_profile test_benchmark_grhsim_ir PYTHON=.venv/bin/python
make run_hdlbits_grhsim_ir DUT=086 SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python
make run_hdlbits_grhsim_ir DUT=097 SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python
```

首次old profile后处理失败后，保存的非空profile通过`make analyze_grhsim_cpu_profile`
读取，指定`GRHSIM_CPU_PROFILE`、`GRHSIM_CPU_PROFILE_BINARY`、`GRHSIM_CPU_PROFILE_MODEL`
和`GRHSIM_CPU_PROFILE_SAMPLES=24548`，没有更换性能数据。

正式六轮完成后对候选新模型单独进行一次200 Hz profile：Host **117.470 s**，
emu wall **117.51 s**，23,498 samples，endpoint和NEMU均PASS；profile输出选择
唯一非空的`cpu.prof_113`。`make analyze_grhsim_cpu_profile`报告22,920条采样
记录，compute task **16,296（69.350583%）**、commit task **4,313（18.354754%）**、
evaluator **666（2.834284%）**，覆盖compute4467/commit505全部4972个task。
与old诊断的compute 69.724621% / commit 18.005540%接近，剩余热点仍然分散。
两个诊断均为evals200102、rounds402258，阶段调度结构一致。

| 相位诊断 | old s | new s |
|---|---:|---:|
| model_step | 122.222862 | 116.979496 |
| eval | 122.311162035 | 117.070535178 |
| compute | 93.476219076 | 89.592875953 |
| commit | 27.027434498 | 25.695037982 |
| publish | 1.659634767 | 1.643836748 |

采样启用`EMU_RUNTIME_PROFILE=1`和`EMU_PHASE_TIMING=1`，且old/new诊断不在六轮
交错窗口内。未修改的commit相位也有时间漂移；不将上表差值视为各相位独立的
优化收益，不用117.470 s替换正式new均值。可信净收益仍是六轮的3.061016%。

## 最终判定与归档

候选A（稀疏最低位活动分派）记录为`REJECTED`，因为独立单对新Host136.881 s
比旧120.936 s慢13.184660%，随后源码已撤销；其生成/编译中断复用缺陷也不被
当作性能证据。候选B满足语义、正确性、生成/编译和六次交错统计全部门槛，
节点判定为 **ACCEPTED**。本节点不声称解决全部约2.6倍差距；保留的收益是
一项可组合的 GrhSIM-IR/CPU emit 优化，后续节点可在此版本上继续探索。

节点最终修改集中在wolvrix子模块和根仓库：新增pass、bool emitter规则、测试/文档、
可关闭的XiangShan流水线选项，以及predicate/机器码/profile分析工具和本报告。
没有提交`ptmp`生成物、日志、profile、波形或ELF，也没有修改XiangShan/HDLBits
测试源或冻结的GRH实现。子模块先提交，
再由根仓库更新指针、索引和goal结果。

后续优先测量compute值物化、内存访问及通知的动态成本，探索能覆盖分散热点的
依赖融合或状态访问机制。最低置位switch分派已在本节点证伪；一位谓词的改进
不构成重复微调同一参数的理由。本次仅完成NO00031，不启动下一节点。
