# TNO0334 XiangShan 原生 Verilator 线程扩展

日期：2026-10-12

## 1. 测量目标与固定配置

测量完整 XiangShan RTL 直接经 Verilator 生成的 1、2、4、8、16、32 线程版本。
线程数通过 XiangShan Difftest Makefile 的 `EMU_THREADS` 在构建时确定；
每档生成独立模型和 emu，不经过 Wolvrix 转换或 RepCut 分区。

全部性能运行位于 node030：N=1 使用 CPU96，N=2 使用 CPU96–97，依次扩展，
N=32 使用 CPU96–127；NUMA memory bind=1。CPU96–127 均为不同物理核。
同档包含运行 Difftest 的主线程和 Verilator worker，共享该档的完整 CPU 预算。
Verilator 检测到外部 affinity 小于机器全部硬件线程后，保留外部设置，
不额外给每个 worker 单独选核；本轮保留这一标准行为，逐线程核验允许范围和实际 CPU。

构建采用 `testcase/xiangshan/difftest` 的 `make emu` 标准 recipe，Verilator
5.048，Clang 23.1.2（与当前 GrhSIM 验证线相同）。保留标准模型生成 `-O3`、
`OPT_FAST=-O3`、`OPT_SLOW=-O0`、`--threads-dpi all`、assertion、output split
和 C++17；不增加 `-march=native`、LTO、PGO 或 BOLT。

32 线程档只额外容忍 `UNOPTTHREADS` 诊断（`-Wno-UNOPTTHREADS`）。
该诊断说明原生调度器难以达到所请求的并行度；不调整调度、成本或优化参数。
已完整生成的模型继续通过原 Makefile 编译，未重新生成不同配置的模型。

调试配置：不编译波形，不启用 snapshot、coverage、ChiselDB、ConstantIn、
随机初始化或内部阶段 profile；启用单 guest 核 Difftest。保留 RTL 中既有
XSPerf/打印逻辑，运行使用 `-b 0 -e 0`，不 dump wave 或 RAM trace。

冻结输入为现有 `asc_counter_print_20260915/candidate_v4/rtl` 的未分区 RTL，
对应当前 GrhSIM 验证线沿用的 counter-print 实验；本轮复用现有 elaboration。
Difftest generated-src 的 C++/头文件与该 RTL 的原配 generated-src 逐字节一致，
只有不参与编译的 profile JSON 存在差异。冻结副本共 2106 个文件，完整身份见
[plan.json](../../build/xs_native_verilator_scaling_20261012/plan.json)。

运行使用同一 `coremark-2-iteration.bin`、NEMU、seed=0 和 C=100000 窗口。
沿用当前 GrhSIM 的 ASLR 关闭和代码 THP preload，对可覆盖的 2 MiB 对齐
可执行区间使用 THP，逐次验证该区间完全覆盖；区间两端不足 2 MiB 的页保留原映射。
这是固定周期窗口的速度测量，不是完整 CoreMark 跑分。

原生单线程先完成一次 C100000 签名校准并通过 Difftest：PC=`0x80000cde`、
instructions=238535、cycleCnt=99996、Guest=100001。RepCut 既有签名是
PC=`0x80000c0c`、instructions=240349，其余周期计数相同。正式六档原生模型
使用同一原生签名校验，两个 RepCut 模型使用同一 RepCut 签名校验；两侧均须
通过 Difftest。原生提交指令少约 0.75%，因此除固定周期速度外也统计指令速度，
不能把三条实现称为完全相同的周期级执行。此处确认了差异，未归因其具体原因。
校准日志不参与后续六轮正式性能统计。

## 2. 分布式构建与交错测量

node030 顺序构建 N=1/8，node031 顺序构建 N=2/16，node032 顺序构建 N=4/32。
三台机器并行，每台同时只有一个模型构建任务，C++ 编译并行度各为 12。
六档各自记录完整命令、编译日志、总编译 walltime 和 ELF SHA256。

所有编译结束后，先对每档执行 C=100 检查，再运行六轮完整 C=100000：
奇数轮按 Native 1→2→4→8→16→32→RepCut V32→RepCut G32，偶数轮按相反顺序。
所有版本都在本窗口重新运行，
不复用历史控制时间。记录 Host、外层 walltime、用户/内核时间、RSS、功能签名
和本进程线程的 CPU 允许范围；保留全部通过功能校验的样本，不按快慢筛选。

按用户追加要求，加入两份已有的正常性能二进制（不重新编译）：

- RepCut Verilator：`clang23_threeway/verilator_o3/partitioned-emu/verilator-compile/emu`，
  SHA256 `12ff6327e7fa4a4866974bfe6727821bebe6f9e46e8b2c9407482251d136958d`。
- 最新保留的 GrhSIM 正式候选 G：`dirty_input_bridge_20261012/formal/candidate/emu`，
  SHA256 `203e9fb21f633ddc8f74115ebd9e9ac55438a9b07ec5e5d8bd7964fc4a6fe6e4`。

两份 ELF 复制到本轮 controls 目录后冻结，运行前后核验身份。两侧均使用
N=K=32、Host lane9/CPU105、31 个后台 worker、push update、all-spin；
运行日志里的 runtime-config 和实际线程数均核验。统一关闭阶段计时采样
（`XS_REPCUT_STEP_TIMING=0`），测量正常 walltime。
GrhSIM G 保留累计优化及 `-march=native`，RepCut V 是既有 Clang23/O3 包，
原生 V 使用标准 Makefile 不增加该编译选项。这是三条完整实现的端点比较，
不能归因成仅替换仿真器的收益。

RepCut V 的每个 Verilator unit 为 `--threads 1`，但共享 VerilatedContext
在实例化模型时还创建 31 个库线程；这些线程在等待第一项任务时休眠，unit
不投递内部多线程任务。因此本版本实测共 63 个 OS 线程，执行仿真的仍是
Host+31 个 RepCut worker，使用 32 个物理核。GrhSIM 实测为 32 个 OS 线程。
CPU 审计包含这些附属线程，全部限制在 CPU96–127。

代码页预处理增加了进程内 `MADV_COLLAPSE` 重试：遇到单个区域分配暂不可用时，
保留已经折叠的大页，再重试同一映射；最终仍要求原区域完整 THP 覆盖。
实现见 [xiangshan_codepage_retry.cpp](../../scripts/xiangshan_codepage_retry.cpp)，
编译产物为本轮 `setup_tools/collapse_retry.so`。首轮 Native 1/2/4/8 的已通过
样本使用原 preload，其余运行加此重试辅助库；主 ELF、代码地址及最终页覆盖
保持相同。辅助库仅处理预初始化，walltime 包含该时间，Host 计时在其后开始；
最终分析会分别核对预处理耗时，保留全部通过样本。

## 3. 完整构建时间

| Native 线程 | 构建节点 | Verilator 生成 / s | C++ 编译链接 / s | 两阶段合计 / s | 整体构建 / s |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | node030 | 396.63 | 237.21 | 633.84 | 635.412 |
| 2 | node031 | 502.15 | 239.27 | 741.42 | 742.836 |
| 4 | node032 | 681.15 | 239.60 | 920.75 | 922.220 |
| 8 | node030 | 850.51 | 263.59 | 1114.10 | 1115.561 |
| 16 | node031 | 1517.89 | 294.02 | 1811.91 | 1813.178 |
| 32 | node032 | 1848.00 | 244.24 | 2092.24 | 2171.234 |

生成和编译链接分别取标准 recipe 的 GNU time 记录，整体时间从首次 make
启动计至成功构建结束。32 线程整体时间包含容忍并行度诊断后按原 recipe
续编的间隔；不把该间隔解释为 C++ 编译耗时。三节点上的构建时间不作为
同一台机器的编译性能 AB 对照。两份 RepCut ELF 复用已有构建，不将本轮
未发生的编译时间计作零。

复现入口：[xiangshan_native_verilator_scaling.py](../../scripts/xiangshan_native_verilator_scaling.py)。

## 4. 六轮正式结果与结论

八个版本各完成六次新的 C100000 测量，共 48 次；全部通过 Difftest 检查，
到达各自预期的周期限制签名并正常退出。逐次核验 CPU affinity、实际 CPU、
OS 线程数及可覆盖代码区间的完整 THP，最终核对 ELF、guest image 与 NEMU 身份。
所有性能运行均在 node030，无并行仿真；全部通过样本保留。

以下 walltime 和 Host 的主指标为六次中位数；六个数排序后取中间两项的平均。
walltime 包含进程启动和代码页预处理，Host 来自 emu 的 `Host time spent`。
速度为 `100000 / Host 中位数`，wall 比值为 `213.105 / 本行 walltime 中位数`。
RepCut 的该比值是完整实现的端点比较，不用它计算原生线程并行效率。

| 实现 | walltime 中位数 / s | walltime 均值 / s | walltime 范围 / s | Host 中位数 / s | 速度 / cycles/s | 相对 Native 1 的 wall 比值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Native 1 | 213.105 | 212.980 | 212.49–213.35 | 213.0265 | 469.43 | 1.000× |
| Native 2 | 143.075 | 143.133 | 142.64–143.67 | 142.9950 | 699.33 | 1.489× |
| Native 4 | 77.830 | 77.972 | 77.75–78.35 | 77.7475 | 1286.21 | 2.738× |
| Native 8 | 45.815 | 45.805 | 45.46–46.16 | 45.7350 | 2186.51 | 4.651× |
| Native 16 | 53.360 | 56.493 | 40.48–76.96 | 53.2835 | 1876.75 | 3.994× |
| Native 32 | 44.965 | 60.610 | 31.57–119.95 | 44.8765 | 2228.34 | 4.739× |
| RepCut Verilator 32 | 22.615 | 22.640 | 22.27–23.36 | 22.5145 | 4441.58 | 9.423× |
| RepCut GrhSIM G 32 | 10.995 | 10.940 | 10.68–11.13 | 10.9150 | 9161.70 | 19.382× |

原生 1/2/4/8 档重复性较好；8→32 的 walltime 中位数只缩短约 1.855%，
16 线程中位数反而更慢。原生 32 线程均值为 60.610 s，明显高于中位数，
不能只用最好的一次 31.570 s 代表这一档。默认共享 affinity、生成时的
`UNOPTTHREADS` 诊断及 RepCut 各线程单独绑核属于实现差异，但本轮没有完成
波动的因果归因，也没有改变默认调度来消除慢样本。

按 walltime 中位数直接相除，GrhSIM G 比 RepCut V 快 2.057×，比 Native 32
快 4.090×。下面另列同轮配对统计，计算方式为
`[1 - median(T_candidate[r] / T_baseline[r])] × 100%`；这是“逐轮比值的中位数”，
与“两个 walltime 中位数相除”不是同一算法，不混用两者。

| baseline → candidate | 配对 walltime 降幅中位数 | candidate 更快的轮数 |
| --- | ---: | ---: |
| Native 32 → RepCut V32 | 49.987% | 6/6 |
| Native 32 → RepCut G32 | 75.738% | 6/6 |
| RepCut V32 → RepCut G32 | 51.692% | 6/6 |

三个 32 线程版本的各轮原始 walltime 如下，便于直接检查顺序和波动。
奇数轮这三个版本的相对顺序为 Native→V→G，偶数轮为 G→V→Native。

| 轮次 | Native 32 / s | RepCut V32 / s | RepCut G32 / s |
| --- | ---: | ---: | ---: |
| 1 | 31.57 | 22.31 | 10.77 |
| 2 | 43.47 | 22.27 | 10.68 |
| 3 | 34.98 | 23.36 | 11.07 |
| 4 | 87.23 | 22.61 | 10.93 |
| 5 | 119.95 | 22.62 | 11.06 |
| 6 | 46.46 | 22.67 | 11.13 |

所有正式样本代码页预处理耗时为 35.193–66.174 ms；首轮四个不含重试辅助库的
样本同样完整覆盖可对齐代码区域。该预处理发生在 Host 计时前，保留在外层
walltime 中；不能用它解释 Native 16/32 的数十秒波动。
本轮关闭阶段采样，不能直接把历史开启阶段计时的 Host 数据当作本轮 baseline。
三条实现的配置及约 0.75% 的提交指令差异仍按 §1/§2 的限制解释。

产物：[交互式 HTML](../../build/xs_native_verilator_scaling_20261012/native_verilator_scaling.html)、
[完整原始/汇总 JSON](../../build/xs_native_verilator_scaling_20261012/summary.json)、
[汇总 CSV](../../build/xs_native_verilator_scaling_20261012/summary.csv)。
HTML 可选择全部版本、仅原生档位或仅三个 32 线程版本，切换中位数/均值、
Host、周期/指令速度、原生并行效率及构建时间，并显示每次样本。
已执行实际 HTML 内嵌脚本，核验 8 个版本、48 个点、54 种指标/范围/样本开关组合
及数据链接；最终分析重新读取全部日志和 CPU 审计，未使用历史性能样本。

重试辅助库的构建命令如下，在仓库根目录执行；输出目录为
`build/xs_native_verilator_scaling_20261012/setup_tools`。该库没有替换主 ELF。

```sh
mkdir -p build/xs_native_verilator_scaling_20261012/setup_tools
/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++ \
  -std=c++17 -O2 -fPIC -shared -Wall -Wextra \
  scripts/xiangshan_codepage_retry.cpp \
  -o build/xs_native_verilator_scaling_20261012/setup_tools/collapse_retry.so
```

`plan` 冻结输入和控制 ELF，`build --host node030/node031/node032 --jobs 12`
分别按预定分配构建各档，`measure --rounds 6` 必须在 node030 执行。
`measure --rounds 6 --resume` 只续接同一未完成窗口，核验并保留其已通过前缀。
本轮已完成结果可在仓库根目录运行以下命令重新核验并生成 HTML，无需重测：

```sh
.venv/bin/python scripts/xiangshan_native_verilator_scaling.py analyze
```
