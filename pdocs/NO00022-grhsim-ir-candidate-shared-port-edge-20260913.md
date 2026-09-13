# NO00022：共享提交端口边沿并一次消费活动位

- Node：`residual_eval_20260913_01`。
- 当前阶段：`ACCEPTED`；完整时间门与六次交错均通过，本报告随节点最终归档。
- 根基线：`2f1f9cb`；子模块 `118d024096d7cfc0792227b6dcde971b6f44ae1d`。
- 节点开始时工作区干净；本节点在 ACCEPTED 后集中提交。

最终保留机制是共享提交端口的边沿检查与活动位消费，前述通知方向的尝试均未保留。
三次新 Host 为 **63.589 / 62.558 / 63.522 s**，均值 **63.223 s**；同窗口按
旧/新交替的旧样本为 **65.589 / 65.944 / 64.625 s**，均值 **65.386 s**。
降低 **3.308048%**，`max(new)=63.589 < min(old)=64.625`，U=0、单侧精确 p=0.05。
六次均 50k NEMU PASS，完整生成 **615.88 s**、fresh 编译 **253.93 s**。节点局部
接受；距约 40 s 仍有 **23.223 s**，整个长期目标未完成。

## IDEA 与证据计划

上一节点已消除混合 commit task 内可共享的 history。旧诊断中 compute 为主要
成本，但该诊断不代表当前版本。因此先以当前最佳可执行文件刷新相位及平坦采样，
再从依赖、输入变化、状态访问等通用语义特征选择减少重复求值的核心机制。
机制、新意、覆盖面、收益上界和证伪条件在实现前补齐；不预填实验结果。

## BASELINE 与预注册

- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，top SimTop，
  冻结 RTL/GRH/GRH pass/测试负载不变，不按模块名优化。
- CoreMark SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；
  NEMU SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
- NO00021 对照 emu SHA-256
  `3cd75af70fd115a5f9fab97cd17ad68b4c06726993888236aea0abba16d029c0`，
  使用已验收的完整生成和 fresh 编译产物。
- 50,000 cycles、CPU 2、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`；
  waveform、commit/RAM trace 关闭；主机 32 CPU，C++ 编译 32 jobs。
- 启动前固定参考值 NO00021 三次均值 64.585333 s；仿真进程树 KILL 截止
  **96.878 s**（1.5 倍，毫秒取整）。诊断同样安装截止，其时间不混入性能样本。
- 生成、编译从各自 Make 启动计时，预装 1800 s 进程树 KILL；超时记
  TIMEOUT_KILLED，隔离不完整 flow。恢复 checkpoint 仅作筛选，正式生成走完整 SV。
- 正式六次预注册顺序为 `old1/new1/old2/new2/old3/new3`；同窗口串行，
  Host 为主指标，同时报告 emu 墙钟、退出状态与完整 NEMU 终点。
  每组 3 次有效样本，要求 `max(new)<min(old)`（单侧精确 p=0.05），报告均值、
  样本标准差、效应量。无效运行保留原因并补跑，不择优删除样本。
- 标准等价终点：73,580 instructions、cycleCnt 49,996、PC `0x80001312`、
  guest cycles 50,001；非零、断言、mismatch 和止损均否定该次尝试。
- 复用配置未变的 gsim 20.640 s 档案；不重复运行。
- 临时日志、产物与命令放在 `ptmp/no00022_residual_eval_20260913_01/`。

## REJECTED：inline fanout 通知

当前 profile 将 `cpu_direct_state_changed` 归因到 201 个采样，占 1.53% 名义 CPU
时间；该函数定义在主翻译单元，而调用分散在数千个 task 翻译单元，未启用 LTO 时
每次状态变化都支付调用边界。候选把相同实现生成为模型类内 `inline` 方法，仍使用
同一 `cpu_targets` 区间、`projection` 汇总和逐目标 arm/flag 更新；没有改变 GRH、
调度、状态布局、遍历次序或运行时分配。预期总收益上界约为该热点的全部 1.53%，
实际目标为 0.5–2%，若六次交替无法与噪声区分则继续本节点修正机制。聚焦验证先
覆盖 emitter 生成和既有 schedule/mapping/IR 测试，再进行完整生成、fresh 编译与
六次交替复测。

聚焦 emitter、schedule、mapping、IR 测试通过（emitter 50.78 s）。完整生成内部
597.966 s、Make 墙钟 608.92 s，fresh 编译 265.40 s；flat GRH 与 NO00021 完全一致。
筛选 Host 68.608 s、phase Host 69.520 s 均 NEMU PASS；后者 compute 44.707 s、
commit 22.916 s、publish 1.630 s，evals/rounds 100102/201258。
正式第一对 old1=65.428 s、new1=68.711 s，同窗口候选慢 5.02%，与筛选一致，
已足以否定尝试；六次剩余四次未运行，该对不作统计接受证据。撤销 inline 改动。
相邻旧运行恢复到 65.428 s，不能将候选回退归咎于机器漂移。很可能内联增大
大 task 的代码/寄存器压力抵消调用节省，尚无硬件计数器证据做更强归因。

## REJECTED：按 enable 限制端口失效传播

新鲜 NO00021 诊断：phase Host 65.188 s，compute 42.884369 s、commit 20.525955 s、
publication 1.522528 s，100102 evals / 201258 rounds。另一次平坦采样 Host
65.568 s、13118 samples（200 Hz），compute tasks 59.9024%、commit tasks 25.8805%、
evaluator 2.9578%、main-other 8.9419%、external 2.1955%；`cpu_stage_cell` 2.9273%、
`cpu_direct_state_changed` 1.5322%。均 NEMU PASS，诊断不计入性能样本。
compute 热点分散在 2539 个 task；commit 的前十 task 占 1127/13118=8.59%。
例如 task 5116 的 4096 个 unique-writer 端口，每个 data 变化都会置位，即使其
enable 为零，随后逐位进入 commit 才发现不能写。该 task 本身 134 样本=1.0215%。
这是一类不必要的依赖传播，不依赖此 task 编号或模块名字触发。

机制把 data/mask→port 的失效边变成由该端口 enable 控制的条件边。enable 本身
的变化始终无条件置位；data/mask 变化仅在当前 boundary enable 非零时置位。
如 data 先在禁用期间改变、enable 后变为 1，enable 的独立变化通知补回唤醒，
即使二者跨 task、round 或 eval。若 enable 一直为 0，原写口本来就没有作用。
首次 init 的全部 pflags 置 1、持久到触发边沿才消费的规则保持。分组键包含 enable
ValueId，防止共享 data 但使能不同的端口被错误合并；目标按 enable 分组并条件写入，
消除禁用时的 pflag 存储和后续扫描工作。仅现有 armable direct commit 端口适用，
boundary 在 commit 期间稳定，唯一写者前提保持，公共 helper ABI 不变。

预期总 Host 降低 2–10%，成本上界是 20.526 s commit 加对应 compute 传播部分，
实际受 enable 活跃率、预测和数据布局限制。可证伪标准仍为聚焦语义回归、50k
终点、1800 s 门槛、96.878 s 止损和六次正式交替的全秩分离；未通过则继续改进。
为这次新尝试预注册独立六次顺序 `enabled_old1/new1/old2/new2/old3/new3`，筛选不计入。

聚焦 emitter 测试先通过 50.67 s；扩展共享 payload 的相反 enable 用例后再次通过
53.79 s。覆盖 bool、signed 5-bit、64-bit、零/部分/全 mask、禁用期间 data/mask
多次改变后仅 enable 改变、重复 eval、四次 init，以及同一 payload 的不同条件目标。
既有 emitter suite 还包含 ASan/UBSan 与 Verilator 差分的多时钟寄存器/存储用例。
筛选从冻结 flat checkpoint 恢复，Make 102.58 s（内部 91.682 s），C++ 编译
260.78 s；两者 exit 0，均预装 1800 s 截止。前者不作为完整 SV 生成门槛证据。
生成包含 243064 个条件传播站点，覆盖 3468 个 compute task；这是静态覆盖，
不直接当作动态跳过次数或收益。

筛选 Host 72.885 s，紧邻旧对照 65.582 s（回退 11.14%），均 NEMU PASS。
相位诊断 Host 72.936 s、compute 52.064180 s、commit 19.029868 s、publication
1.590726 s，evals/rounds 100102/201258 不变。commit 确实少约 1.50 s，但 compute
增加约 9.18 s，额外条件检查/分组成本超出收益。因此撤销条件传播实现，未运行该
尝试的完整 SV 生成或正式六次复测。扩展的语义用例对后续直接写优化仍有价值。

## IDEA / IMPLEMENTED：合并相同通知目标

新证据来自当前旧模型的状态目标表：例如 task 5116 多个相邻寄存器均指向相同
`(cpu_flags[1039], mask=8, arm=false)` 或 mask=4，状态内容不同但通知是重复的。
该任务有 4096 个直接写端口、profile 134 samples=1.0215%；通用
`cpu_direct_state_changed` 另有 201 samples=1.5322%。与先前 inline 尝试不同，
本机制先消除相同消费者的重复通知，再发布一次，不把目标遍历展开到每个写站点。

在同一 task 内按完整 `(projection, [(offset,mask,arm),...])` 签名分组，只覆盖
至少两个直接写状态的组；每组一个局部位，发生真变化时置位，task 尾一次发布。
局部 `uint64_t[]` 位图每次调用清零；没有宽值返回、运行时分配或公共 helper ABI
变化。状态唯一写者及无 commit 观察者的既有证明保持，实际写入/比较不移动。
compute flags、next-domain arms 和 `cpu_direct_again` 在 task 结束之后才被观察，
这些通知的 OR/set 是幂等的，因此组内任何一个或多个状态变化都只需通知一次。
未分组状态、history 和 staged memory 路径不变；不改变冻结 GRH 或调度结构。

覆盖与收益在生成后测量；局部预期为总时间减少 1–5%，可消除的通知本体 1.53%
加调用者重复数据读取/边界成本是搜索依据，不将全部 commit 20.526 s 当作预期。
原有正确性、1800 s、96.878 s 门槛不变；正式六次独立预注册顺序为
`notify_old1/new1/old2/new2/old3/new3`，只有全秩分离才 ACCEPTED。

候选静态覆盖：158375 个直接写状态合为 17526 组，覆盖 490 个 commit task，最大
563 组/task（位图 72 bytes）。task 5116 的 4096 个状态合为 33 组，只用 8 bytes
位图。这说明通知签名重复广泛存在，不是循环同一状态的 pending 记录去重；后者
已被 NO00013 的唯一 dirty key 不变量排除，与本机制无关。
聚焦 emitter 先通过 51.89 s；新增投影状态及共享输出的 sanitizer 运行用例后通过
110.92 s（与筛选编译并行，该耗时不作性能比较）。非投影 fixture 两种 partition
配置各检查 4668 次/4 次 init，聚合 fixture 明确触发 4 状态/1 通知组；投影 fixture
明确触发 2 状态/1 通知组并验证当前 eval 完成后的组合输出，防止丢失收敛轮次。
扩展测试首次编译有 InputId/ValueId 共用 auto 声明错误，修正后通过；未作为仿真失败
或性能样本。筛选恢复 Make 101.98 s（内部 88.218 s），exit 0，正式 SV 门槛另测。

## 进展

输入与对照二进制 SHA-256 已与上节点档案核对相符，XiangShan 工作区干净。
通知合并首版筛选 Host 66.076 s，紧邻旧对照 65.348 s（候选慢 0.728 s，约 1.11%），
均通过精确 50k 终点；未形成收益证据。前述用户更新中一次误称“快约 0.7 s”，
正确方向是候选较慢。修正限制小组成本：目前最终候选要求至少 4 个同签名状态。
中间曾选择 8 个，但未运行性能实验；先前 2/4 状态夹具不能触发新阈值，重写为
8 个独立寄存器共享组合消费者的投影夹具，最终覆盖独立数据/使能、仅一个状态
变化、部分掩码、重复 eval 和四次 init。移除过渡期夹具后旧 suite 通过 50.61 s，
新增最终夹具另验。通知合并不修改输入/模型语义；本版完整 SV 生成结果见下一节。

### 四状态门槛尝试：六次交错未排除噪声

该版完整 SV→C++ Make 墙钟 613.65 s（内部 599.708 s），fresh 编译 265.40 s，
exit 0，均低于 1800 s；flat GRH 与 NO00021 逐字节相同。聚焦 emitter 最终夹具
通过 55.01 s。静态合并 139736 状态/9422 组/101 task，最大347组/task。
2026-09-13 正式六次如下，RUN_ID 前缀 `no00022_notify_`，时间均 UTC+08:00。

| RUN_ID 后缀 | 启动时间 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| old1 | 16:20:12 | 65.659 | 65.69 | 0/0 | NEMU PASS |
| new1 | 16:22:07 | 62.753 | 62.78 | 0/0 | NEMU PASS |
| old2 | 16:23:29 | 64.471 | 64.50 | 0/0 | NEMU PASS |
| new2 | 16:24:47 | 64.535 | 64.56 | 0/0 | NEMU PASS |
| old3 | 16:27:02 | 65.721 | 65.75 | 0/0 | NEMU PASS |
| new3 | 16:29:51 | 63.032 | 63.06 | 0/0 | NEMU PASS |

两组均值 old=65.283667 / new=63.440000 s，样本标准差 0.704472 / 0.958504 s。
均值减少 1.843667 s（2.824086%），Cohen's d=2.191884，但 `U_new=1`，单侧精确
p=0.10；new2 比 old2 慢 0.064 s，因此不 ACCEPTED，全部六次保留。
均为 73580 instructions、cycleCnt 49996、PC 0x80001312、guest cycles 50001，
无无效样本或补跑；正确性/时间门槛通过不能替代未通过的秩次门槛。

### 修正：直接聚合目标活动字

上一版先记录组号，末尾仍逐组判断并转换为活动位。比如 task 5116 的 33 组仍有
33 个分支/目标 OR，实际只更新 5 个相邻活动字节。修正按 `(arm, offset/8)`
建立局部 64-bit 通知字，状态真变化时直接 OR 预计算目标掩码，末尾每字只做一次
活动数组读取、OR 和定长 memcpy；投影标记在真变化点按原规则置 true。没有通过
函数返回宽数组，继续使用 caller-owned 局部缓冲和 memcpy，native endian 掩码
在编译期确定，尾字长度限制在 runtimeBytes 内。其他状态的已有活动位通过 OR 保留。
同签名四状态门槛保持；这是删除从组号到目标位的运行时转换，非继续调节门槛。
预期在已改善的通知路径上再减少 0.5–2 s；若新增字数、寄存器压力或生成代码增大
抵消收益，仍按相同门槛否定。新版本六次独立预注册 `word_old1/new1/old2/new2/old3/new3`。

### REJECTED：目标活动字版仍未排除噪声

最终源码的 emitter 测试通过 51.97 s；完整 SV 生成 Make 602.25 s（内部
588.108 s），fresh 编译 269.70 s，均 exit 0 且预装 1800 s 截止。正式运行如下：

| RUN_ID 后缀（前缀 no00022_word_） | 启动时间 UTC+08 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| old1 | 16:52:50 | 65.343 | 65.37 | 0/0 | NEMU PASS |
| new1 | 16:53:55 | 65.308 | 65.34 | 0/0 | NEMU PASS |
| old2 | 16:55:00 | 64.110 | 64.14 | 0/0 | NEMU PASS |
| new2 | 16:56:05 | 63.678 | 63.71 | 0/0 | NEMU PASS |
| old3r | 17:15:26 | 65.618 | 65.65 | 0/0 | NEMU PASS |
| new3 | 17:16:32 | 63.882 | 63.91 | 0/0 | NEMU PASS |

原 old3 在 40k cycles 中断，Host/退出码缺失；恢复时已从主机进程表确认
emu/Make/timeout 全部不存在，保留为 INVALID，用唯一 RUN_ID old3r 补跑。
中断原因没有足够证据判定，没有把部分结果当成性能样本。有效六次终点均为
73580 instructions、cycleCnt 49996、PC 0x80001312、guest cycles 50001。
old/new 均值 65.023667/64.289333 s，样本标准差 0.803117/0.888068 s，均值减少
0.734333 s（1.129332%），Cohen's d=0.867331；U_new=1、单侧精确 p=0.10。
new1 慢于 old2，未通过全秩分离；中断拉长了窗口也进一步限制解释。撤销本版实现，
不以平均数改善作为接受依据。

## IDEA：未变化的高扇出 compute 通知整组跳过

新鲜 NO00021 compute 42.884369 s 是仍占主导的瓶颈。源码中 computeGroup 已按
相同消费者合并值变化标记，但每个通知仍执行 `flags |= -changed & mask`；即使
changed=false 也读写活动数组。按每个 computeGroup 的局部标记重新计数，旧生成
代码有 473948 组、1024307 个通知写站点；其中至少四个站点的 35635 组覆盖
434449 个写站点（42.4%），最大组有 20947 个。这里只是静态覆盖，未测动态不变率。

核心机制是利用已有整组变化谓词，令高扇出组在 changed=false 时整组跳过通知；
changed=true 时按原次序发出常量 OR。不增加逐值比较或输入读取，不移动计算本体，
也不改变同活动字后继 unit 的即时唤醒规则。小组维持原分支消除形式，阈值固定为
至少四个实际通知站点，避免单个零掩码存储换成大量新分支。该机制覆盖 compute
活动位、domain arm 和 commit-port pflags，通用触发条件只有通知扇出。

预期总 Host 减少 2–8%，上界受 42.884 s compute 成本及动态变化率约束；若分支
成本超过跳过的写入则否定。与前述按 enable 条件传播不同，条件来自原有完整值
变化谓词，不读取其他端口条件，不改变依赖图。撤销未接受的 commit 合并以独立
测量此机制。聚焦测试将覆盖多个活动字、独立 enable/data、无变化/单变化/部分 mask、
重复 eval 和 init。仍保持完整 SV/编译 1800 s、仿真 96.878 s 截止，正式六次预注册
`fanout_old1/new1/old2/new2/old3/new3`；恢复筛选与诊断不混入正式样本。

实现仅修改 emitter 的 computeGroup 通知尾部及 armPorts 的常量掩码生成；没有
修改 scheduler、layout、GRH 或测试负载。首轮 emitter 52.03 s，40 寄存器夹具
9220 次 eval/4 次 init，ASan/UBSan 通过；schedule/mapping/IR 回归也通过。
测试首次命令遗漏 WOLF_ENV_SOURCED，Make 在构建前拒绝，补齐原环境后成功。
最终夹具覆盖共享 mask 同时驱动组合消费者与五个 pflag 字节，两种分区配置
（superOps/helperLines = 128/10000、2/1）各 9220 次 eval、4 次 init，ASan/UBSan
通过，包含仅 mask 改变但未触发时钟边沿时的组合输出。完整 emitter suite 109.18 s
（与筛选编译并行，只作功能结果），含宽值、多时钟寄存器和双口 RAM 的 Verilator
差分；最终临时测试日志保存于本节点目录。checkpoint 筛选生成内部 89.793 s，
Make 103.56 s、exit 0；覆盖 2179 个 compute task、35635 组、434449 个通知写站点，
最大 20947 站点/组，与原始源码事前统计一致。该时间不替代完整 SV 门槛。

筛选编译 255.49 s，exit 0；筛选新/旧 Host 62.000/65.130 s（emu 墙钟
62.03/65.16 s），均 exit 0、NEMU 精确终点通过。候选单对减少 3.130 s（4.8058%），
仅作为继续正式验证的依据。生成 C++ 总字节从 1339210868 降为 1309019472
（减少 30191396 bytes），ELF `size` text 从 137415119 降为 136166579 bytes。
正式完整 SV 生成已完成：Make 墙钟 **601.66 s**（内部 592.378 s），exit 0，
预装 1800 s 截止。flat GRH 经 cmp 确认与 NO00021 逐字节相同，SHA-256 为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`；checkpoint
round-trip 同样通过。工作区 emitter 源码在测试、筛选和正式生成期间保持相同，
SHA-256 `f975290710beab7bf73a34af2489770edc121b205d3976ee637a3c5b02eee300`。
正式与筛选生成目录排除编译产物后 diff 完全相同，包括全部 5749 个 C++ 文件、
头文件和 Makefile；因此正式运行覆盖的就是已通过聚焦测试与筛选的实现。
fresh 32-job 编译 **248.90 s**，exit 0、预装 1800 s 截止；从全新目录编译模型
和 harness，非增量复用。两个时间门槛已通过。六次独立交错结果如下：

| 后缀（前缀 no00022_fanout_） | 启动 UTC+08 | Host s | emu 墙钟 s | 状态 / 等价性 |
|---|---|---:|---:|---|
| old1 | 17:45:34 | 65.121 | 65.15 | VALID / NEMU PASS |
| new1 | 17:46:39 | 63.733 | 63.76 | VALID / NEMU PASS |
| old2 | 17:47:43 | 64.527 | 64.56 | VALID / NEMU PASS |
| new2 | 17:48:48 | 65.086 | 65.11 | VALID / NEMU PASS |
| old3 | 17:49:53 | 64.738 | 64.77 | VALID / NEMU PASS |
| new3 | 17:50:58 | 63.633 | 63.66 | VALID / NEMU PASS |

三次旧均值 **64.795333 s**、样本标准差 **0.301122 s**；三次新均值
**64.150667 s**、样本标准差 **0.811564 s**，均值减少 **0.644667 s（0.994928%）**，
Cohen's d **1.053220**。所有运行均为 73580 instructions、cycleCnt 49996、PC
0x80001312、guest cycles 50001，退出码均 0；无效样本为 0。`new2=65.086 s`
高于 `old2=64.527 s`，所以 `U_new=2`、单侧精确 p=0.20，未达到要求的全秩
分离（p≤0.05）。该尝试记录为 REJECTED，代码和测试保留在工作区供节点内继续
改进；不得将 0.994928% 平均下降当作接受收益。

正式新 emu SHA-256 为
`8c2aafb6e8680dfb2dcf582934ff5afeed7504477b403cce90e45f7368143f70`，旧 emu 身份见
BASELINE；两者 ELF .comment 均包含相同 clang 22.1.2 与 GCC 13.3.0 工具链标记。
正式新 ELF text/data/bss 为 136166579/9344/18416 bytes，与筛选一致。

## IDEA / IMPLEMENTED：多个变化组按目标 pflag 字节汇聚

整组跳过首版虽然筛选有收益，但六次结果未全秩分离。继续分析原代码可见，同一个
compute unit 内 1024307 个通知站点仅涉及 499336 个唯一目标字节（245694 个目标
64-bit 字），不同变化组重复写同一目标。下一版只在 pflags 上验证目标汇聚：同一个
unit 的一个目标 pflag 字节若由至少四个变化组驱动，先将原 `-changed & mask`
在局部 uint8_t 汇总，尾部非零时对目标执行一次 OR。compute 活动位仍按原规则，
未覆盖 pflag 继续原路径；原计算/比较不移动，不新增条件输入，不修改依赖图。

这不把某个 enable 作为别的端口的传播条件。每个原目标位来自原变化谓词，OR
结合律与幂等性保证不同组的变化不会覆盖彼此或丢失既有 pflags。所有 pflags 到
commit 阶段才消费，unit 内延迟写回不可观察；局部标量无需运行时分配。目标是
用一个写回替代多组重复零掩码读改写。预期总 Host 再减少 1–4%，若局部变量和
分支成本抵消收益就否定；仍需完整 SV/编译 1800 s、50k 96.878 s 截止和六次
新旧全秩分离。正式顺序另预注册 `aggregate_old1/new1/old2/new2/old3/new3`。

聚焦 emitter 53.40 s 通过。第一次测试停在旧的生成文本覆盖断言：完整 unit
中的高扇出组已改由目标汇聚路径处理，原 skip 标记不再出现；扩展该断言识别
汇聚路径后，两种分区各 9220 次 scoreboard eval、4 次 init 及完整 sanitizer/
Verilator suite 均通过，未出现行为不等价。该次属于测试路径断言更新，非性能样本。
恢复筛选生成 Make 104.20 s（内部 90.248 s），exit 0；静态汇聚 1799 个 task
中的 20147 个目标字节，将 117890 个写站点合为最多 20147 次发布（减少 97743，
仅静态上界）。剩余整组跳过覆盖 34703 组/423540 站点。源码总字节 1311736592，
比仅整组跳过版多 2717120 bytes；下面以筛选测量判断。

筛选结果否定目标汇聚：编译 256.31 s；新 Host 71.189 s、紧邻旧 Host
65.510 s，均 exit 0、精确 50k NEMU PASS，新慢 8.67%。因此 REJECTED，未运行
该版完整 SV 或正式六次。局部目标变量和新分支可能增加寄存器压力，尚未通过
硬件计数器证明归因；减少静态写站点不足以证明动态收益。撤销这部分实现。

## IDEA：在最后一次贡献后立即发布变化组

旧 computeGroup 在 unit 入口声明所有 bool 变化标记，直到完整 unit 结束才
发布通知。统计为 38750 个 unit、473948 个组，最大 128 个组/unit。许多组仅
一个生产者也保留其标记直到末尾，延长临时值活跃区间；上一版目标汇聚进一步
增加局部变量后明显回退，提示应缩短生命周期而非增加汇聚缓冲。

新机制在每组第一个生产者前声明变化标记，并在最后一个生产者结束后立即
发出原目标通知。相同目标的多个贡献仍 OR 合并一次；不改变计算操作顺序、
表达式、值比较和分组键。computeGroup 执行过程中不会消费 scheduler 活动位或
pflags，同字后继 unit 也到当前 unit 返回之后才检查，因此提前 OR 通知不可
观察；DPI 的通知同为 OR 并保持外部调用本身的位置。不增加运行时状态或缓冲。

保留高扇出组的变化谓词门，核心新增是基于最后使用位置缩短变化标记生命周期，
非调节扇出阈值。预期总 Host 减少 3–10%，若编译器原本已消除全部生命周期成本
或提前发布增加访存，则证伪。原正确性、1800 s、96.878 s 门槛保持；正式顺序
独立预注册 `early_old1/new1/old2/new2/old3/new3`。筛选先验证，不预填收益。

提前发布版 emitter suite 53.35 s 通过；schedule/mapping/IR 回归通过。两种分区
的独立 scoreboard 保留 9220 eval/4 init，数据与使能属于相同通知目标但在不同
操作产生，覆盖仅一项贡献改变时仍须发布的情况；宽值和多时钟 suite 也通过。

筛选生成内部 92.138 s，exit 0。对原/新生成源码按 unit 重置局部变量编号，
以声明到最后一次文本引用计算区间，组数均为 473948；平均区间长度从
178.955 行降至 11.8043 行，最大同时活跃标记从 128 降至 56。这证明源码层面
的生命周期缩短，不等价于实测寄存器占用或 spill 次数；性能仍以运行结果判断。

筛选 Make 105.81 s，编译 247.82 s，均 exit 0。首次仿真在 20k 后进程消失，
无 Host/退出码；主机进程表确认无残留，记 INVALID 中断，未作性能样本。
新 RUN_ID `_new_retry1` 重跑 Host 64.866 s（墙钟 64.90 s），紧邻旧
`_old_retry1` 65.385 s，均精确 NEMU 终点、exit 0。单对改善 0.7938%，不足以
支持独立接受；未运行此单独版本的完整 SV 和正式六次，继续加入下述语义简化。

## IDEA / IMPLEMENTED：单生产者通知与值写入合并

原 473948 个变化组中，372479 组只有一个生产者，覆盖 822291/1024307 个通知
站点（80.28%）。单生产者不需要独立积累变化标记：对于 1–64 bit 两态逻辑，
直接生成 `if(old != new){ boundary=new; 原消费者 OR 通知; }`，合并值写入与
通知的条件分支；旧代码无论变化与否都写 boundary，并在组末执行零掩码 OR。
组内有多个生产者时仍保留前版的 OR 标记与最后贡献后发布；宽值保持原 pointer
helper 路径。跳过相同值写入对普通非 volatile boundary 无可观察影响；通知的
原时点依赖约束与提前发布版相同，其他 pflags 原值保持，DPI 不走单生产者路径。

这个机制针对 80% 以上通知站点的冗余存储与分离条件处理，预期总 Host 减少
5–15%，上界受 compute 42.884 s 及实际值变化率限制，若新增分支不划算则证伪。
没有改动冻结 IR、layout、调度顺序或模块名匹配。聚焦 sanitizer/scoreboard
覆盖共享数据、mask、独立使能、多贡献组；完整 1800 s、50k 96.878 s 截止保持。
独立正式六次顺序预注册 `single_old1/new1/old2/new2/old3/new3`。

该版 emitter suite 53.38 s 通过。旧 singleton 文本断言依赖 `cpu_changed_` 标记，
在消除该标记后更新为识别变化分支；地址化内存读激活的原断言保留。首次断言
失败发生于行为测试前，其余已执行的 sanitizer 用例通过；修正断言后完整
sanitizer/Verilator/多时钟和新夹具均通过。恢复筛选结果见下文。

恢复筛选生成 Make 107.66 s（内部 93.833 s），exit 0；单生产者标量路径实际覆盖
371183 个组/4694 个 compute task，排除其余宽值组。原预测 372479 是未按位宽
筛选的上界，差额 1296 组不走本路径。保留的多生产者/宽值高扇出门为
7343 组/68293 站点。总生成 C++ 从基线 1339210868 bytes 降至 1268993888，
减少 70216980 bytes（5.24%）；仅作代码规模证据。

筛选编译 252.20 s，exit 0；候选 Host 84.764 s（墙钟 84.79 s），紧邻旧对照
65.125 s（墙钟 65.15 s），均 NEMU 精确终点通过、exit 0，新慢 30.16%。该尝试
REJECTED，广泛新增的变化分支没有换来净收益，
不继续完整 SV 或六次试验；撤销提前发布和单生产者路径。

## IDEA：组合两层通知优化

回到已经各自显示平均改善、但尚未排除噪声的两个独立机制：四状态提交签名合并
（原六次均值降低 2.824086%）与 compute 高扇出通知整组跳过（降低 0.994928%）。
前者在 commit task 中消除同消费者重复通知，后者在 compute unit 中跳过未变化
的高扇出通知；数据结构、调度顺序和彼此的消费时点均不变，可以按原语义证明
组合。恢复四状态组位图版本，不保留目标活动字、pflag 目标汇聚、提前发布或
单生产者分支。两个阈值均保持最初版本的四，未调节参数。

新意在于同时削减两阶段的冗余通知，预期降低 2–6%，不能把各自平均数简单相加
当成收益；因代码布局和工作集相互影响，也可能不叠加，完整六次将证伪。
仍按同一旧基线，聚焦测试必须同时触发 commit 合并和 compute skip 并检查行为。
正式顺序独立预注册 `combined_old1/new1/old2/new2/old3/new3`，1800 s 与
96.878 s 门槛保持，先做独立筛选。

组合候选 emitter suite 53.31 s、schedule/mapping/IR 均通过。新增夹具在
superOps=128 时明确断言 40 个投影状态合为一组，在另一种分区验证高扇出
compute 门包含同字后继活动位、多字消费者和五个 pflags 字节；两种配置均
9220 次 eval/4 次 init 的独立 scoreboard 与 ASan/UBSan 通过。

组合筛选生成 Make 105.11 s（内部 91.095 s），编译 250.79 s，exit 0；覆盖
139736 状态/9422 组/101 commit task，compute 35635 组/434449 站点，均与各自
独立版相同。新 Host 71.095 s，紧邻旧 65.418 s，均精确 NEMU PASS，新慢 8.678%：
组合没有相加收益，REJECTED，未运行组合版完整 SV 或六次，撤销两个机制。

## IDEA：共享边沿端口块的一次消费

通知路径的多次变体未能稳定改善，转向 commit 活动扫描本身。旧版 192340 个
armable 端口虽共用已缓存的边沿快照，却仍对每个活动 bit 单独测试相同快照，
逐位累积 consumed，再对每字节执行 `pflags &= ~consumed`。对一个 64 端口块，
若全部端口使用同一缓存边沿，64 次边沿检查与逐位消费都可由一次共同检查取代。

新机制只在现有最多八个 pflag 字节块内、所有端口 guard 是同一个非空缓存快照
时触发：块入口测试一次边沿；为 false 时保留全部武装位；为 true 时执行原 bit/
enable/写值/通知序列，并一次清除该字节所有实际端口位。完全占满的字节直接
赋 0，部分字节仅清除真实端口位，保留 padding。其他块维持原实现。快照在原
采样之前计算，不改变 history 顺序，commit 不会写入 pflags，故消费时点等价。
保留每端口 enable 和值差异检查，不引入新的每值分支、局部通知缓冲或宽值复制。

预期主要降低约 20.526 s commit 成本，总 Host 目标减少 5–15%；若编译器已完成
这类控制合并或热端口太少则证伪。通用条件为共享事件语义，完全不依赖模块名。
聚焦多时钟/异步/重复 eval/init/部分字节夹具和 50k 验证；所有原时间门槛保持。
独立正式六次顺序预注册 `edgeblock_old1/new1/old2/new2/old3/new3`。

原生成代码按已有活动扫描块的静态检查显示 3407 个块/191917 个带缓存 guard
的端口均共享块内快照，说明并非少数端口特例。完整 emitter suite 53.34 s
通过，41 端口 fixture 明确断言共享块入口与 `pflags[5] &= ~1` 的尾字节消费；
两种分区各 9220 eval/4 init，覆盖禁用时数据改变、随后仅 enable 改变、mask
更新、边沿不触发时保留位。此前 CDC/双口 RAM sanitizer+Verilator 差分亦通过。

筛选恢复 Make 105.53 s（内部 91.781 s），exit 0；生成覆盖 497 个 task 的
3412 个共享块，原缓存边沿的逐端口重复检查剩余 0，C++ 总字节从 1339210868
降至 1330404870（减少 8805998 bytes）。该覆盖包含五个先前纯文本统计未计入
的小块，最终数字以 emitter 生成结构为准。

块级筛选编译 258.45 s，exit 0；新 Host 64.300 s、紧邻旧 64.638 s，均精确
50k NEMU PASS，仅单对改善 0.523%。继续将相同语义覆盖到整个端口任务：若
一个 task 的全部 armable 端口使用同一非空缓存快照，只在全部扫描块外检查一次，
不同快照任务仍按块检测并回退原路径。没有端口跨 task 移动或阈值调整。原
history 采样在入口检查之前原位执行；共同边沿不成立时全部端口均不能消费，
因此可整段跳过。该修正删除同任务内剩余重复快照检查，单独完整验证。
正式六次顺序改用唯一 `taskedge_old1/new1/old2/new2/old3/new3`，其他门槛不变。

任务级修正 emitter 53.20 s 通过，schedule/mapping/IR 回归亦通过。完整 SV
生成、fresh 编译和独立六次交错已启动；不将此前块级筛选当作完整生成证据。

完整 SV→C++ Make **615.88 s**（内部 601.726 s）、exit 0，预装 1800 s 截止。
flat GRH 与冻结 NO00021 逐字节一致，SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`；checkpoint
round-trip 通过。497 个任务均可用 task 级共同边沿，将 3412 个块检查归为 497 个
入口检查；最终源码 SHA-256
`08995f6cf5ca69a6d99edf4cf5d7923792f92a9b5523a212869e706b7a8571b4`。

fresh 32-job 编译 **253.93 s**、exit 0，1800 s 截止安装有效。正式 emu SHA-256
`4e05a152cb8e6c97bc50c0960d04801ff40b634aba5154048aefc3f9f651f815`；ELF text
134244983 bytes（旧 137415119，减少 3170136），data/bss 9344/18416 与旧一致。

## VALIDATED / ACCEPTED：最终六次交错与统计

全部测量在 2026-09-13 **19:19:36–19:26:02 UTC+08** 同一窗口连续串行执行，
顺序和比较口径在运行前预注册。下表 RUN_ID 统一前缀 `no00022_taskedge_`。

| 后缀 | 启动 UTC+08 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| old1 | 19:19:36 | 65.589 | 65.62 | 0/0 | NEMU PASS |
| new1 | 19:20:42 | 63.589 | 63.62 | 0/0 | NEMU PASS |
| old2 | 19:21:46 | 65.944 | 65.97 | 0/0 | NEMU PASS |
| new2 | 19:22:52 | 62.558 | 62.59 | 0/0 | NEMU PASS |
| old3 | 19:23:54 | 64.625 | 64.65 | 0/0 | NEMU PASS |
| new3 | 19:24:59 | 63.522 | 63.55 | 0/0 | NEMU PASS |

所有六次均开启 NEMU difftest、无 mismatch/断言/异常退出，终点为 **73580
instructions、cycleCnt 49996、PC 0x80001312、guest cycles 50001**。输入、harness
NUM_CORES=1、CPU 2、单线程、50k 范围和无 waveform/trace 设置一致。没有无效样本、
补跑或删除；筛选和诊断未加入样本池。各次均低于预选止损线 96.878 s。

| 统计量 | 旧 | 新 |
|---|---:|---:|
| Host 均值 s | 65.386000 | 63.223000 |
| Host 样本标准差 s（n−1） | 0.682530 | 0.576880 |
| Host 范围 s | 64.625–65.944 | 62.558–63.589 |
| emu 墙钟均值 s | 65.413333 | 63.253333 |

效应量按 `(old_mean-new_mean)/old_mean`：降低 **2.163000 s / 3.308048%**；
相对速度比 old/new=**1.034212**，合并样本标准差口径 Cohen's d=**3.422918**。
所有三次新均优于全部三次旧，分离间隔 **1.036 s**。Mann–Whitney `U_new=0`，
六个不同秩下 3+3 个标签的 20 种等可能分配中只有一种达到该方向全分离，单侧
精确 **p=1/20=0.05**，满足 goal 规定的秩次判据。不是以跨窗口历史值或单对
筛选证明收益；亦未把旧样本池中较慢数据择优拿来当控制。

节点结论为 **ACCEPTED**。功能、输入身份、完整生成和编译时间、六次交错统计
均已通过。最终实现只修改 CPU emitter 的共享 guard 和消费生成，配套 41 端口
两种分区的回归及文档；冻结 GRH IR/pass、XiangShan 与负载源码均未改动。通知
分组、inline、enable 条件传播、目标聚合、提前发布与单生产者分支均已撤销。
所有前期失败、未执行门槛与中断在本报告保留，不混入最终性能证据。

本节点后续方向：当前均值距 40 s 仍差 23.223 s，先使用最终相位证据判断残余
compute/commit 成本，再考虑稀疏端口访问或重复计算消除。通知分支和局部汇聚的
几次回退说明静态代码量/存储数不能替代运行收益；不继续调四状态/四扇出阈值。
本次为距 NO00020 定期复盘后的第二个节点，下一个完整节点收尾需作三节点复盘。

最终相位诊断 RUN_ID=`no00022_taskedge_final_phase`：Host **62.323 s**、emu 墙钟
**62.35 s**，Make/emu exit 0，精确 50k NEMU 终点一致。eval=62.151959 s，
compute=**41.914338 s（67.4385%）**、commit=**18.606339 s（29.9369%）**、
publication=**1.557333 s（2.5057%）**；evals **100102**、rounds **201258**，
收敛轮次结构与 NO00021 相同。相较本节点开始的旧相位，commit 少 1.919616 s，
方向符合重复边沿/消费计算减少的机制；compute 仍是主要成本。两次诊断跨窗口且
有计时插桩，因此不把该相位差作为因果效应量或性能基线，最终收益只由上述六次
未插桩交错样本确定。没有重新采集平坦 profile；最近平坦采样仍属于 NO00021。

归档范围：子模块 CPU emitter、回归 fixture 和 backend 文档，根仓库本报告、
goal 当前基线与索引；不提交生成代码、日志、profile、波形或二进制。最终实现
commit 为 **`2f3b72f7496ee6e4a29f40a39faaf8873d883000`**
（`perf(grhsim): share port edge checks and activity consumption`），
其父提交为 `118d024096d7cfc0792227b6dcde971b6f44ae1d`，保留源码与上述测试/生成
哈希一致。根档案 commit 同时更新子模块指针。子模块初始化核对已完成；此前
受限 Git 配置写入在节点收尾通过已有授权集中处理。节点完成后停止，不启动下一节点。

## 复现命令与计时

机器为 AMD Ryzen 9 7950X3D（16 核/32 逻辑 CPU、单 NUMA node），新旧编译器
均 clang 22.1.2（ELF .comment 一致）。从根仓库执行以下命令；复现时换唯一目录
和 RUN_ID，以免覆盖本节点产物。引用的临时路径只作运行参数，结果证据归档在正文。

```bash
root=$PWD
node=$root/ptmp/no00022_residual_eval_20260913_01
flow=$node/flow-taskedge-final
old=$root/ptmp/no00021_history_cohorts_20260913_01/flow-final
mkdir -p "$node/tmp" "$node/logs"
export PATH="$root/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export TMPDIR="$node/tmp" PIP_CACHE_DIR="$node/pip-cache"
export CCACHE_DIR="$root/ptmp/cpu_emit_ccache" CMAKE_BUILD_PARALLEL_LEVEL=32
export LC_ALL=C EMU_RUNTIME_PROFILE=0
common=(PYTHON="$root/.venv/bin/python" XS_NUM_CORES=1 XS_EMU_THREADS=1
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
  XS_LOG_DIR="$node/logs" XS_GRHSIM_IR_BUILD="$flow"
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0)
make --no-print-directory test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00022_taskedge_full_generate.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00022_taskedge_full_generate \
  > "$node/no00022_taskedge_full_generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00022_taskedge_full_build.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu "${common[@]}" \
  RUN_ID=no00022_taskedge_full_build > "$node/no00022_taskedge_full_build.log" 2>&1
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00022_taskedge_${version}${pair}"
    run_flow="$flow"
    if [[ "$version" == old ]]; then run_flow="$old"; fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 96.878s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1 || exit "$?"
    # 继续前检查本文固定的 NEMU 终点、退出状态与失败标记。
  done
done
```

实际 runner 另外存储每次完整 shell-quoted 命令、启动/结束时间、退出码、VALID 状态，
非零立即停；生成/编译超时将该 flow 重命名隔离。Make 计时包括 package 更新和
完整流程准备；仿真计时包裹 emu 本身，不含 Make 和编译。诊断通过相同 run Make
目标，phase 设 `EMU_RUNTIME_PROFILE=1`；flat 在 emu prefix 末尾加入
`env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0 CPUPROFILE=... CPUPROFILE_FREQUENCY=200`。
平坦采样解码使用 `make analyze_grhsim_cpu_profile`，参数为对应 `.prof`、emu、
`grhsim_SimTop.cpp` 和 `GRHSIM_CPU_PROFILE_SAMPLES=13118`，通过终止符、mapping、
ELF/符号边界及样本总数检查。初次 profile 因 flow 参数指向未构建目录失败，没有
启动 emu；换唯一 RUN_ID、指定 NO00021 flow 后成功，未采用失败结果。
