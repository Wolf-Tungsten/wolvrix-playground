# 从保形对齐到追 gsim：preserve-aggregate GrhSIM IR 的一次性能优化实战

> 2026-10-18。本文记录一条很具体的优化路径：输入固定为
> `--preserve-aggregate=all` 的 XiangShan，行为只跟 plain Verilator 对齐，
> 然后再一点点把 GrhSIM 的仿真时间往 gsim 的方向推。这里的“快”必须建立在
> 提交轨迹不变的前提上；只看最终 PC 或一次偶然的 Host time 都不算验收。

## 先把比赛规则钉死

这次的 workload 是 `coremark-2-iteration.bin`，运行窗口为 100,000 个 guest
周期，单核、单 emu 线程、CPU 2、NEMU difftest 开启，关闭 waveform、commit/RAM
trace 和 runtime profile。正式 A/B 通过仓库已有的 `make benchmark_grhsim_ir`
执行；每次运行前对对应二进制做页缓存逐出，顺序是 old1 → new1 → old2 →
new2 → old3 → new3。

机器是 AMD Ryzen 9 7950X3D 16-Core，32 个逻辑 CPU。端点门禁钉为：

```text
instrCnt=238535
cycleCnt=99996
Guest cycle=100001
pc=0x80000cde
```

plain Verilator 是唯一的行为参考。gsim 只用来观察性能目标；没有生成
aggregate Verilator，也没有拿 gsim 的调度差异替换 plain 的对齐门禁。

## 第一幕：profile 先告诉我们钱花在哪里

20k 周期的采样剖面显示，绝大多数时间都在 `general_supernode`：

| 类别 / 函数 | 样本占比 |
| --- | ---: |
| `general_supernode` | 78.08% |
| `main_other` | 14.23% |
| `general_chunk` | 5.82% |
| `sn_12277__op_12795()` | 17.33% |

`sn_12277__op_12795()` 的生成代码里反复出现 preserve-aggregate 数组的整值
搬运：一个宽 `std::array` 从存储打包出来，经过一两个只做赋值的临时值，再写回
下游。这个模式对 RTL 语义没有贡献，却会制造数组复制、宽 `_BitInt` 打包和逐
元素写回。原始采样结果在
[`profile20k/analysis.txt`](../../ptmp/perf-blog-20261018/profile20k/analysis.txt)。

这也解释了为什么“把超节点再合大一点”不是第一步：先把完全没有信息量的搬运
删掉，风险更小，而且可以直接用 IR pass 的计数和提交 trace 验证。

## 第二幕：先让编译器用上这台机器

第一步没有改变 IR，只重建生成模型时的编译参数：

```text
-std=c++20 -O3 -march=native -fno-strict-aliasing
```

`-march=native` 让 clang 可以为本机的宽整数、比较和拷贝选择合适的指令；
`-fno-strict-aliasing` 与既有生成模型的别名假设保持一致。用同一份
preserve-aggregate 模型做 3+3 对照后，原始 old 均值从 369.026s 降到
331.213s：

| 版本 | Host time（s） | 样本标准差 |
| --- | ---: | ---: |
| 原始 `-O3` | 369.026 | 3.239 |
| `-march=native` | 331.213 | 0.478 |

这是 **10.247%** 的确定性收益，三次 new 的最大值小于三次 old 的最小值。
逐次原始数据和预注册参数见
[`march-native-bench3/summary.json`](../../ptmp/perf-blog-20261018/march-native-bench3/summary.json)
与 [`march-native-bench3/results.json`](../../ptmp/perf-blog-20261018/march-native-bench3/results.json)。

## 第三幕：给 preserve-aggregate 数组别名做一次消元

### 原来的限制

`grhsim.canonicalize-compute` 之前只把精确类型匹配的、无 shape 的 two-state
标量 `assign` 当作纯别名消掉。preserve-aggregate 以后，一个数组也有完整的
interned type：元素宽度、维数和每一维 extent 都包含在 type 中。因此下面这类
操作同样是纯别名：

```text
array_input : Logic<8>[4]
      │
assign(array_input → array_alias)
      │
assign(array_alias → array_alias2)
      │
array_output = array_alias2
```

本轮把判断推广到 shape 完全一致的 two-state Logic，同时保留原来的 phase
兼容检查、跨 phase 使用保护、object/parameter 保护和 out-of-scope consumer
保护。也就是说，只有确认这是同一语义值的别名才重连 producer；不会把不同
数组几何或不同阶段的值强行折叠。

实现位于
[`canonicalize_compute.cpp`](../../wolvrix/lib/grhsim/pass/canonicalize_compute.cpp)，
回归测试在
[`test_grhsim_ir.cpp`](../../wolvrix/tests/grhsim/test_grhsim_ir.cpp)，新增了
shaped array 的两级 assign 链，并检查输出重新连回原始输入且第二次运行幂等。

同一份 checkpoint 重发射后的 pass 统计为：

```text
identity_assigns_removed=46949
common_expressions_removed=78860
rewritten_uses=141918
translation_units=1197
```

模型从 1,207 个普通 TU 降到 1,197 个；生成模型的 ELF text 从
409,154,816 bytes 降到 326,998,052 bytes，约减少 20.08%。这不是把数组从
aggregate 改回 scalar，而是让同一个 aggregate value 少经过几层无意义的
临时复制。完整重发射记录在
[`aggregate-alias-reemit.log`](../../ptmp/perf-blog-20261018/aggregate-alias-reemit.log)，
候选构建记录在
[`aggregate-alias-build.log`](../../ptmp/perf-blog-20261018/aggregate-alias-build.log)。

## 正确性验收：先看提交轨迹，再看秒数

候选二进制单独跑到 100k 的结果是：

```text
instrCnt = 238535
cycleCnt = 99996
Guest cycle spent: 100001
pc = 0x80000cde
Host time spent: 313117ms
```

更严格的检查开启完整 commit trace。plain 和 alias 两侧各有 **231,568** 条
提交记录，流式比较结果为：

```text
plain_records=231568
grhsim_records=231568
compared_records=231568
differing_records=0
differing_payloads_excluding_cycle=0
min_cycle_delay=0
max_cycle_delay=0
```

原始 trace、比较结果和候选运行日志分别在
[`aggregate-alias-trace/logs/`](../../ptmp/perf-blog-20261018/aggregate-alias-trace/logs/)、
[`plain-vs-alias-trace-compare.txt`](../../ptmp/perf-blog-20261018/aggregate-alias-trace/plain-vs-alias-trace-compare.txt)
和 [`aggregate-alias-trace/make.log`](../../ptmp/perf-blog-20261018/aggregate-alias-trace/make.log)。
因此这次优化不仅保持了 endpoint，也保持了每条提交的 cycle、PC、指令和写回
payload。

代码侧验证也保持全绿：`make test_grhsim_ir` 通过，完整
`make test_wolvrix` 为 **64/64**。

## 第四幕：3+3 的结果

alias 候选与 `-march=native` 版本做正式 3+3 交替，六次都 exit 0、difftest
无失配、端点完全相同：

| 版本 | 逐次 Host time（s） | 均值 ± sd（s） |
| --- | --- | ---: |
| `-march=native` | 329.112 / 334.199 / 332.388 | **331.900 ± 2.578** |
| aggregate alias | 322.916 / 322.226 / 319.092 | **321.411 ± 2.038** |

alias pass 在这个口径下再带来 **3.160%** 加速，`max(new) < min(old)` 门禁通过。
相对最初的 369.026s，当前候选累计下降约 **12.903%**。正式结果见
[`aggregate-alias-bench3b/summary.json`](../../ptmp/perf-blog-20261018/aggregate-alias-bench3b/summary.json)
和 [`aggregate-alias-bench3b/results.json`](../../ptmp/perf-blog-20261018/aggregate-alias-bench3b/results.json)。

一次单独的 endpoint run 是 313.117s；它只用于快速验收，最终结论以逐出页缓存
的 3+3 结果为准。

## gsim 还在前面，但现在知道差距是什么量级

现有 gsim 二进制在同一输入、CPU 2 和 100k 窗口下单次跑出 **46.832s**，约为
当前 GrhSIM alias 候选的 6.86 倍速度。这个 gsim 产物编译于 2026-10-05，
本次运行的端点是 `instrCnt=238550 / cycleCnt=99998 / pc=0x80000b40`；它和
plain 的端点不同，但 NEMU difftest 正常。因此这条数据只回答“性能目标还有多远”，
不回答“行为是否正确”。运行记录在
[`gsim-run2.log`](../../ptmp/perf-blog-20261018/gsim-run2.log)。

这个差距也给出下一轮的方向：profile 中 78% 仍集中在 general supernode，
数组别名只是先清掉了一层结构噪声。这里先把 PGO 的边界说清楚：PGO 本身当然
可能带来收益，但只给 GrhSIM IR 开 PGO 会把 gsim 的比较口径改变，而且每轮都要
增加 instrument、训练和 profile-use 重编译时间。在两边没有同等 PGO 流程之前，
主线一律使用相同的非 PGO 编译和运行口径；当前 PGO 试验只保留为诊断记录，不
计入性能结论。只有非 PGO 的差距已经收敛，并且能对 gsim 做同样 workload、同样
采样和同样编译器参数的 PGO A/B，才重新打开这个实验。

因此后续应在同一 plain trace 门禁下继续做：

1. 对 alias 候选重新采样，确认 `sn_12277` 的占比是否下降，并把剩余的宽数组
   临时值按“是否真的跨边界”分类；
2. 继续减少 general supernode 的边界比较和函数调用成本，比较生成代码形状
   与 gsim 的无分支变化检测；
3. 每一个候选都重复 plain Verilator 的逐条 commit trace 比较，性能收益不足
   或 trace 有一条偏移就回退。

## 第五幕：concat fast path 的小实验

剩余的 `general_supernode` 代码里还可以看到一种 preserve-aggregate 形状：多个
同宽 scalar lane 先 concat 成一个宽值，随后马上按数组行拆回去。于是我在 CPU
emitter 中加了一个很窄的 fast path，只处理“operand 数等于数组行数、结果宽度
超过 64 位、所有 operand 都是同宽 two-state scalar”的情况，直接写入目标数组的
行，绕过宽 `_BitInt` 的 pack/unpack 往返。这个候选没有放宽 preserve-aggregate
的语义，也没有改变 alias pass。

候选的 100k commit trace 使用 `-b 0 -e -1` 与 plain Verilator 比较，双方均为
231,568 条记录，cycle、PC、指令、写回数据和 ROB index 全部相同，端点仍为：

```text
instrCnt=238535
cycleCnt=99996
Guest cycle=100001
pc=0x80000cde
```

性能没有形成可重复的收益。逐出页缓存的单次 A/B 为 321.092s 对 319.638s，
表面差异只有 0.453%，预注册的秩检验门禁未通过。随后启动的 3+3 只完成了 alias
侧第一轮（317.166s）；候选侧因确认“没有明显收益”而停止，且当时的命令误用了
`-e 0`，会让 emu 交替开关 commit trace，不能把那半程数据当作性能证据。这个
实验的结论是：对齐安全，但性能基本中性，不能作为追 gsim 的有效优化点。

因此原始 concat 实验先回到 alias 基线；后续只保留能在 plain trace 门禁下通过、
并在完整重复测量中显示稳定收益的改动。相关候选生成物、trace 和 A/B 记录保留
在 [`aggregate-concat-wide/`](../../ptmp/perf-blog-20261018/aggregate-concat-wide/)、
[`aggregate-concat-wide-bench1/`](../../ptmp/perf-blog-20261018/aggregate-concat-wide-bench1/)
和 [`aggregate-concat-wide-bench3/`](../../ptmp/perf-blog-20261018/aggregate-concat-wide-bench3/)。

## 收尾：回退无收益试验，保留窄路径

2026-10-19 再检查时，flat-state memcpy 和 sub-byte concat 的试验代码仍然回退；
sub-byte 版本曾在重发射时触发 sink boundary 缺失错误（`v533373`）。经过拆分，
只把有明确 3+3 证据的 byte/word mixed aggregate/scalar concat 路径重新放回
emitter。它只接受 two-state、元素宽度 8/16/32/64 bit、scalar 宽度按 64 bit
对齐且行数完全匹配的形状，其他输入继续走原来的 pack/unpack 路径。回退前的完整
源文件备份在 [`rollback-backup/`](../../ptmp/perf-blog-20261018/rollback-backup/)；
当前保留的实现位于
[`cpu_phase_emit.cpp`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp)。

新增的 `mixedShapedConcatTest` 会执行两个输入更新，检查 256-bit aggregate 的
结果，并断言生成源码包含直接 scalar/row `memcpy`。`test_grhsim_cpu_phase_emit`
和 `test_grhsim_ir` 均通过。当前还没有用这份重新收窄后的源码重跑 100k，因此历史
`292.708s` 仍是原始候选的证据，不能直接当作这次最小实现的承诺。

到这里的经验是：先把“行为参考”和“性能目标”分开，才能放心地把
preserve-aggregate 保留下来优化。数组别名消元并没有改变 aggregate 的表达能力，
却让生成器少发射了一批搬运代码；这正是下一轮追 gsim 时值得继续坚持的方向。

## 复现入口与证据索引

正式 A/B 的入口仍是 `make benchmark_grhsim_ir`。本轮使用的关键参数是：

```sh
make benchmark_grhsim_ir \
  GRHSIM_IR_BENCH_OLD=ptmp/perf-blog-20261018/march-native \
  GRHSIM_IR_BENCH_NEW=ptmp/perf-blog-20261018/aggregate-alias \
  GRHSIM_IR_BENCH_OUTPUT=ptmp/perf-blog-20261018/<new-output> \
  GRHSIM_IR_BENCH_CPU=2 GRHSIM_IR_BENCH_PAIRS=3 \
  GRHSIM_IR_BENCH_BASELINE_SECONDS=331.213 \
  GRHSIM_IR_BENCH_EXPECTED_ENDPOINT=238535,99996,100001,0x80000cde
```

`<new-output>` 必须是尚不存在的 `ptmp/` 子目录；benchmark 脚本会自动完成
页缓存逐出、Make 运行、端点检查和统计。整个过程的目录索引在
[`ptmp/perf-blog-20261018/`](../../ptmp/perf-blog-20261018/)。

## 当前最新回退后实测（2026-10-19）

按回退后的工作区重新发射并构建了一份 preserve-aggregate=all 的 GrhSIM IR
模型。重发射输入是 aggregate alias checkpoint，使用当前 shaped alias pass；emu
模型编译明确使用 `VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32`，没有开启 PGO。
运行口径为单核、CPU 2、NEMU difftest、100,000 guest cycles，关闭 waveform、
commit trace、RAM trace 和 runtime profile。

本次结果：

```text
instrCnt = 238535
cycleCnt = 99996
Guest cycle spent: 100001
pc = 0x80000cde
IPC = 2.385445
Host time spent: 321790ms (321.790s)
```

端点与 plain Verilator 门禁一致。当前结果与此前 aggregate alias 的
`321.411s` 3+3 均值处在同一噪声范围内，没有把它宣称为新的性能收益。运行日志、
模型和 emu 的校验摘要如下：

```text
emu sha256   b03b01be05113a9af380d4c7d799bbbdfa6414be86abd60d516011979ba05e5c
model sha256 77bf105b045c2a7ad769d36600f0672b78d817b4702034e75ea4d4b9b705945d
```

完整运行记录在
[`current-retest-20261019/logs/xs_wolf_grhsim_current-retest-20261019.log`](../../ptmp/perf-blog-20261018/current-retest-20261019/logs/xs_wolf_grhsim_current-retest-20261019.log)，
生成物目录为
[`current-retest-20261019/`](../../ptmp/perf-blog-20261018/current-retest-20261019/)。

## 历史约 300 秒结果追溯：它来自哪一段代码

历史记录里确实有一组接近 300 秒的 preserve-aggregate=all 结果，但它不是
PGO，也不是把构建并行度从 2 调到更高带来的运行时收益。结果来自临时的
`mixed-concat` emitter 实验，最终用于正式 A/B 的候选目录是
[`mixed-concat-fixed3/`](../../ptmp/perf-blog-20261018/mixed-concat-fixed3/)。
候选和旧基线的 IR JSON SHA256 都是
`28644a94ef679059a9905476c8e0832d2153888929f7d2ec10a228196a5d0e22`，所以
差异来自 CPU emitter 生成的 C++ 形状，而不是输入设计、IR 或仿真窗口变化。

这个实验针对 XiangShan 中反复出现的一种 preserve-aggregate 形状：若干 scalar
先做 concat，结果随即作为数组使用或写回数组。原路径会先构造整个宽
`_BitInt`，然后在每次数组读写时按行 slice/unpack。临时 emitter 增加了两个窄的
直通条件：

1. （历史候选，当前未保留）对 whole-array write，识别“结果是 `core.compute.concat`、总宽度正好等于
   行数乘元素宽度、每个 operand 恰好是一行 two-state scalar”的情况，按 concat
   的 MSB 顺序反向收集成 row expressions，直接生成 `std::array` 和逐行写入，
   不再先生成总宽度 `_BitInt`。
2. （当前保留）对 shaped concat，若 operand 是 row-backed aggregate 或 64-bit 对齐的 scalar，
   且元素宽度为 8/16/32/64 bit，则直接复制物理行或用 `memcpy` 拼接数组；不满足
   这些形状时仍走原来的通用 pack/unpack 路径。副作用表达式不会被重复求值，
   非 little-endian 目标保留逐行 fallback。

因此它减少的是运行时宽值搬运和宽值拆包，保持了同一份 aggregate 语义。候选和
plain Verilator 的 100k commit trace 也完全一致：两边各有 231,568 条记录，
`differing_records=0`、排除 cycle 后 `differing_payloads=0`；端点为
`instrCnt=238535 / cycleCnt=99996 / Guest cycle=100001 / pc=0x80000cde`。
逐条比较记录在
[`plain-vs-fixed3-trace-compare.txt`](../../ptmp/perf-blog-20261018/mixed-concat-fixed3-trace/plain-vs-fixed3-trace-compare.txt)。

正式 3+3 交替 benchmark 的 host time 如下：

| 版本 | 三次用时（秒） | 均值（秒） |
| --- | ---: | ---: |
| old：`aggregate-alias` | 321.657、317.032、321.097 | 319.929 |
| new：`mixed-concat-fixed3` | 291.845、293.313、292.965 | 292.708 |

表面收益为 8.508%，且 `max(new) < min(old)`，脚本的秩检验门禁通过。完整统计见
[`summary.json`](../../ptmp/perf-blog-20261018/mixed-concat-fixed3-bench3/summary.json)，
逐次命令和端点见
[`mixed-concat-fixed3-bench3-command.log`](../../ptmp/perf-blog-20261018/mixed-concat-fixed3-bench3-command.log)。
正式运行使用单核、CPU 2、单 emu 线程、100,000 guest cycles、NEMU difftest，
关闭 waveform、commit trace、RAM trace 和 runtime profile；两边最终都用
`-std=c++20 -O3 -march=native -fno-strict-aliasing`。`-j` 只影响构建耗时，
不会解释已经生成的 emu 为什么快了约 30 秒。

原始候选还包含 flat-state memcpy、sub-byte concat 和 whole-array write 等额外试验；
这些没有一起保留。在这段记录形成时，当前工作区在重新加入窄路径后尚未重测 100k，因而此前回退版本的
321.790 秒仍是最近一次完整基线，约 292.708 秒应被看作原始候选的临时实验结果，
不能直接作为当前基线或后续性能承诺。实验源码备份在
[`rollback-backup/cpu_phase_emit.cpp.before-rollback`](../../ptmp/perf-blog-20261018/rollback-backup/cpu_phase_emit.cpp.before-rollback)，
正式构建参数记录在
[`mixed-concat-fixed3-build-native-emu.log`](../../ptmp/perf-blog-20261018/mixed-concat-fixed3-build-native-emu.log)。

## 当前收窄版重测（2026-10-19）

按当前工作区重新发射并构建了 preserve-aggregate=all 的 GrhSIM IR 模型。输入
checkpoint 的 SHA256 为
`28644a94ef679059a9905476c8e0832d2153888929f7d2ec10a228196a5d0e22`；构建使用
`VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32`、`-std=c++20 -O3 -march=native
-fno-strict-aliasing`，没有开启 PGO。运行仍是 CPU 2、单核、单 emu 线程、NEMU
difftest、100,000 guest cycles，并关闭 waveform、commit trace、RAM trace 和
runtime profile。

单次候选运行首先确认了行为端点：

```text
instrCnt = 238535
cycleCnt = 99996
Guest cycle spent: 100001
pc = 0x80000cde
Host time spent: 317316ms (317.316s)
```

随后用 `make benchmark_grhsim_ir` 做页缓存逐出后的 3+3 交替测试。六次运行均
exit 0，端点均为 `238535,99996,100001,0x80000cde`：

| 版本 | 三次用时（秒） | 均值 ± sd（秒） |
| --- | ---: | ---: |
| old：`aggregate-alias` | 315.646 / 314.914 / 313.929 | **314.830 ± 0.862** |
| new：当前收窄版 | 318.117 / 317.596 / 313.940 | **316.551 ± 2.276** |

当前收窄版相对 old 为 **0.547% 回归**，`max(new) < min(old)` 门禁未通过，因而
没有把它作为性能收益。这个结果也说明此前约 292.7 s 的 `mixed-concat-fixed3`
实验收益来自当时仍包含的 whole-array、flat-state 等更宽路径；仅保留 byte/word
mixed aggregate/scalar concat 后，运行时收益不足以抵消测量噪声，后续应继续保持
收窄实现或回退它，而不要引用 292.7 s 作为当前性能。

重发射、并行 32 构建、候选运行和 benchmark 的记录分别在
[`mixed-concat-retained-20261019-reemit.log`](../../ptmp/perf-blog-20261018/mixed-concat-retained-20261019-reemit.log)、
[`mixed-concat-retained-20261019-build-native-emu.log`](../../ptmp/perf-blog-20261018/mixed-concat-retained-20261019-build-native-emu.log)、
[`mixed-concat-retained-20261019-candidate.log`](../../ptmp/perf-blog-20261018/mixed-concat-retained-20261019-candidate.log)
和 [`mixed-concat-retained-20261019-bench3-command.log`](../../ptmp/perf-blog-20261018/mixed-concat-retained-20261019-bench3-command.log)。
统计结果见
[`summary.json`](../../ptmp/perf-blog-20261018/mixed-concat-retained-20261019-bench3/summary.json)，
当前 emu SHA256 为
`8248d2804e2f97e6186184dda1029a772495bd9416f58794000b55b1e13ce52a`。

## 完整优化组合复现（2026-10-19）

为了验证历史约 292 秒是否来自优化组合本身，我把回退备份中的完整 emitter 路径
重新加入当前工作区：flat-state aggregate view 的整块 `memcpy`、whole-array
concat write 的逐行直写、shaped mixed concat 的 row/byte/word 直通，以及
sub-byte concat 的逐行写入。保形输入仍是同一个 checkpoint，SHA256 为
`28644a94ef679059a9905476c8e0832d2153888929f7d2ec10a228196a5d0e22`；构建使用
`VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32` 和
`-std=c++20 -O3 -march=native -fno-strict-aliasing`，没有开启 PGO。

第一次完整重发射暴露了一个边界条件：whole-array write 若把 sink payload
boundary 上的 concat 结果拆成 lane 表达式，某些中间 lane 只有
`boundaryByValue`，没有当前 sink context 的 payload field。修复后的 fast path
只有在每个 lane 都能在当前 context 直接读取时才展开，否则保留带 boundary 的宽
concat。这样既保留优化，也不改变原有边界语义。重发射成功生成 1,197 个 TU，
记录在
[`mixed-concat-debug4-20261019-reemit.log`](../../ptmp/perf-blog-20261018/mixed-concat-debug4-20261019-reemit.log)；
并行 32 构建记录在
[`mixed-concat-debug4-20261019-build.log`](../../ptmp/perf-blog-20261018/mixed-concat-debug4-20261019-build.log)。

完整组合的单次 100k 运行端点为：

```text
instrCnt = 238535
cycleCnt = 99996
Guest cycle spent: 100001
pc = 0x80000cde
Host time spent: 249932ms (249.932s)
```

随后按同一 `make benchmark_grhsim_ir` 协议，对 `aggregate-alias` 基线和完整组合
做逐出页缓存的 old1 → new1 → old2 → new2 → old3 → new3 测量。六次均 exit 0，
每次端点都等于 plain Verilator 门禁：

| 版本 | 三次 Host time（秒） | 均值 ± sd（秒） |
| --- | ---: | ---: |
| old：`aggregate-alias` | 310.595 / 314.022 / 321.104 | **315.240 ± 5.359** |
| new：完整优化组合 | 253.953 / 256.154 / 258.687 | **256.265 ± 2.369** |

完整组合相对当前 alias 基线下降 **18.708%**，`max(new) < min(old)` 门禁通过，
单侧精确秩检验 `p=0.05`。这次不仅复现了历史约 292 秒路径，还在本次机器状态下
测到约 256 秒；差异来自完整路径相对当时 `mixed-concat-fixed3` 还包含 flat-state
和 sub-byte 等优化，以及运行时噪声。统计与逐次端点见
[`full-optimization-bench3-20261019/summary.json`](../../ptmp/perf-blog-20261018/full-optimization-bench3-20261019/summary.json)
和
[`full-optimization-bench3-20261019/results.json`](../../ptmp/perf-blog-20261018/full-optimization-bench3-20261019/results.json)。

移除重发射期间的诊断打印后，`make test_grhsim_cpu_phase_emit`（45.42 s）和
`make test_grhsim_ir`（0.02 s）均通过，回归记录在
[`full-optimization-regression-20261019.log`](../../ptmp/perf-blog-20261018/full-optimization-regression-20261019.log)。

## 把完整组合放进默认入口（2026-10-19）

这一轮将完整组合保留为 XS aggregate 的默认实现。数组同类型别名消元随既有
`grhsim.canonicalize-compute` 执行；flat-state 行镜像、whole-array concat write、
byte/word mixed concat 和 sub-byte concat 均由 emitter 根据类型、几何和 boundary
可见性自动选择，没有新增 Makefile 变量、环境变量或 CLI 开关。

标准 `make xs_wolf_grhsim_ir_emu` 还固定使用已验收的模型编译参数
`-std=c++20 -O3 -march=native -fno-strict-aliasing`，因而无需再手工传入
`GRHSIM_MODEL_CXXFLAGS`。PGO 保持关闭，构建产物使用构建主机的指令集。
benchmark 的默认端点也更新为 plain Verilator 已验证的
`238535,99996,100001,0x80000cde`。

本次从标准 aggregate SV 输入重新执行完整默认流水线，输出到
`ptmp/xs/grhsim-ir/`，使用 `VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32`。先前默认目录
保存在 [`previous-default/`](../../ptmp/xs-aggregate-default-20261019/previous-default/)。
构建和生成日志为
[`build.log`](../../ptmp/xs-aggregate-default-20261019/build.log)。本次性能测量继续使用
既有 `make benchmark_grhsim_ir`：默认产物跑三次，另跑三次 `aggregate-alias` 作为
交替基线，沿用页缓存逐出、CPU 2、单线程、NEMU difftest 和关闭 trace/profile 的
口径。构建后还单独打开 commit trace，与归档的 plain Verilator 100k trace
逐条比较；该次带 trace 的 Host time 不计入性能统计。

默认流程完整生成成功：1,197 个 TU、47,874 个 helper chunks，IR stable round-trip
通过，生成流水线耗时 1,515.146 秒。含 Python 包构建、完整 SV 流水线和 C++/emu
编译的总时间为 **35:11.79**，最大单进程 RSS 为 56,211,664 KiB，退出 0，未发生
OOM，详见 [`build.time`](../../ptmp/xs-aggregate-default-20261019/build.time)。本次不复用
历史实验目录的生成模型。默认 checkpoint SHA256 为
`e1ec9bb36da76b1080620335bd263fd7c32e7dac1cfa0db17a59d9f84badce39`，默认 emu SHA256 为
`8f9db2e6dfa294125fb0dabffde2ce253d8b7998ab8db9a733ede8be00d03d1b`。

独立 trace 验证退出 0：plain 与默认 GrhSIM 各 **231,568** 条，逐条 cycle、PC、
指令、写使能和有效 dst/data 全部相同，`differing_records=0`，最小/最大周期偏移
均为 0。最终端点为 `238535,99996,100001,0x80000cde`；带 trace 的 Host time 为
257.006 秒，仅作为正确性运行记录。比较结果见
[`plain-vs-default-trace-compare.txt`](../../ptmp/xs-aggregate-default-20261019/plain-vs-default-trace-compare.txt)，
原始运行见 [`trace.log`](../../ptmp/xs-aggregate-default-20261019/trace.log)。本次四项回归
`make test_xs_workflow test_benchmark_grhsim_ir test_grhsim_cpu_phase_emit test_grhsim_ir`
均通过，见 [`regression.log`](../../ptmp/xs-aggregate-default-20261019/regression.log)。

三次正式复测已经完成。输入为同一份 preserve-aggregate=all RTL，对照两边都没有
PGO；old 是此前带 `-march=native` 的 `aggregate-alias`，new 是本次完整标准流水线
生成的 `ptmp/xs/grhsim-ir/emu/emu`：

| 版本 | 三次 Host time（秒） | 均值 ± sd（秒） |
| --- | ---: | ---: |
| old：`aggregate-alias` | 314.196 / 317.538 / 322.196 | **317.977 ± 4.018** |
| new：默认完整优化组合 | 260.696 / 262.858 / 264.572 | **262.709 ± 1.942** |

同口径耗时下降 **17.381%**，`max(new)=264.572 < min(old)=314.196`，秩检验门禁
通过（单侧精确 `p=0.05`）。六次均退出 0，NEMU difftest 无失配，端点全部为
`238535,99996,100001,0x80000cde`。这次从默认入口新建产物的成绩是
**262.709 秒**；此前 256.265 秒继续作为检查点重发射实验的历史记录保留。

统计和逐次端点分别见
[`bench3/summary.json`](../../ptmp/xs-aggregate-default-20261019/bench3/summary.json) 和
[`bench3/results.json`](../../ptmp/xs-aggregate-default-20261019/bench3/results.json)，
预注册的二进制及输入散列见
[`bench3/preregister.json`](../../ptmp/xs-aggregate-default-20261019/bench3/preregister.json)。
逐次命令、运行日志及退出状态位于各 `old1`…`new3` 子目录，主日志为
[`benchmark.log`](../../ptmp/xs-aggregate-default-20261019/benchmark.log)。完整复现入口：

```sh
make xs_wolf_grhsim_ir_emu VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32

make benchmark_grhsim_ir \
  GRHSIM_IR_BENCH_OLD=ptmp/perf-blog-20261018/aggregate-alias \
  GRHSIM_IR_BENCH_NEW=ptmp/xs/grhsim-ir \
  GRHSIM_IR_BENCH_OUTPUT=ptmp/xs-aggregate-default-20261019/bench3-rerun \
  GRHSIM_IR_BENCH_BASELINE_SECONDS=317.977
```

第二条命令的输出目录需尚不存在。优化实现、编译选项和行为端点均来自当前默认值，
无需传入优化相关参数；以上 benchmark 参数只选择对照产物、结果目录和超时基准。
