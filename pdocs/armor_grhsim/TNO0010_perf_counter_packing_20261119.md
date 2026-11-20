# TNO0010：性能计数器从 Chisel 到 GrhSIM 的打包路径

**XiangShan 的三万多个性能计数器集中在顶层一个模块里，更新逻辑完全同形。`comb-lane-pack` 把它们的“复位、清零”两层选择按最多 16 路并成宽字，加法留在标量。** 每组计数器每拍都有成员在变，所以承载这些宽字的 supernode 大多每拍都跑，每次重算包内全部各路。下面用 `utilizationCounter_31` 一个计数器走完四层。

本文只读源码、生成记录和已有计数，没有新的运行或计时。[静态热集合的背景](./TNO0009_static_hot_set_20261119.md)

## Chisel：调用处只登记，寄存器在端点模块里集中创建

队列模块里写的是一行 `QueuePerf(size, validCount, full)`。它展开成四个累加计数器和一个直方图：

```scala
object QueuePerf {
  def apply(size: Int, utilization: UInt, full: UInt, ...) = {
    XSPerfAccumulate("utilization", utilization, perfLevel)
    XSPerfHistogram("util", utilization, true.B, 0, size, 1, perfLevel = perfLevel)
    XSPerfAccumulate("full", full, perfLevel)
    val exHalf = utilization > (size/2).U
    val empty = utilization === 0.U
    XSPerfAccumulate("exHalf", exHalf, perfLevel)
    XSPerfAccumulate("empty", empty, perfLevel)
  }
}
```

`XSPerfAccumulate.apply` 只把（模块、名字、信号）记进一张表。真正的寄存器由 `collect` 在 `LogPerfEndpoint` 模块里统一生成，信号从原模块穿线引过来：

```scala
val perfCnt = tapOrGet(perfCnt_bore)
val counter = RegInit(0.U(64.W)).suggestName(perfName + "Counter")
next_counter := counter + perfCnt
counter := Mux(perfClean, 0.U, next_counter)
XSPerfPrint(curMod)(perfDump, p"$perfName, $next_counter\n")
```

`SimTop` 用 `XSLog.collect(timer, logEnable, clean, dump)` 实例化这个端点，`clean` 和 `dump` 接 DiffTest 的控制输入。两点后面会用到：

- 所有计数器的更新式都是 `Mux(perfClean, 0, counter + perfCnt)`，只有 `perfCnt` 不同。
- `empty` 定义为 `utilization === 0`。占用量非零时 `utilization` 计数器在变，为零时 `empty` 计数器在变，**每个队列每拍恰有一个在变**。直方图的使能是常量真，`NSamples` 每拍加一，并且恰有一个桶加一。

[QueuePerf 与 XSPerfAccumulate](../../../wolvrix-playground-new-xiangshan/testcase/xiangshan/utility/src/main/scala/utility/PerfCounterUtils.scala#L59) · [端点模块](../../../wolvrix-playground-new-xiangshan/testcase/xiangshan/utility/src/main/scala/utility/LogUtils.scala#L198) · [SimTop 的接法](../../../wolvrix-playground-new-xiangshan/testcase/xiangshan/src/test/scala/top/SimTop.scala#L184)

## Verilog：一个模块，三万多个同形寄存器

firtool 生成的 `LogPerfEndpoint.sv` 有 255,109 行、14,355 个输入端口、32,598 个 64 位寄存器。其中约 1.07 万个是累加计数器，1,178 组是直方图。示例计数器是这样的：

```verilog
input  [3:0]  perfCnt_bore_11049,                       // 从队列模块引来的占用量
reg  [63:0] utilizationCounter_31;
wire [63:0] _utilizationNext_T_62 =
  64'(utilizationCounter_31 + {60'h0, perfCnt_bore_11049});

always @(posedge clock) begin
  if (reset) begin
    utilizationCounter_31 <= 64'h0;
    ...
  end else begin
    utilizationCounter_31 <= io_clean ? 64'h0 : _utilizationNext_T_62;
    fullCounter_31        <= io_clean ? 64'h0 : _fullNext_T_62;
    exHalfCounter_27      <= io_clean ? 64'h0 : _exHalfNext_T_54;
    ...
```

相邻的几千行只差寄存器名和加数。[声明](../../../wolvrix-playground-new-xiangshan/build/xs/kunminghu-v3-grhsim-merge-20261110/after/rtl-preparation/rtl/rtl/LogPerfEndpoint.sv#L46659) · [时钟块](../../../wolvrix-playground-new-xiangshan/build/xs/kunminghu-v3-grhsim-merge-20261110/after/rtl-preparation/rtl/rtl/LogPerfEndpoint.sv#L147337)

## Wolvrix：同形的写数据树被并成宽字

读入并展平后，每个寄存器的写端口数据是同一棵树，同步复位已并入数据：

```text
写数据_i = mux(!reset, mux(clean, 0, assign(assign(counter_i + zext(perfCnt_i)))), 0)
```

`comb-lane-pack` 紧跟在 `hier-flatten` 之后运行。它从寄存器写数据出发，把形状签名相同、操作序号相近的根并成一组，每组最多 16 路、总宽不超过 1,024 位。可并入的内部操作只有按位的与、或、异或、取反、赋值和 mux。**加法不在其中，所以 `counter + perfCnt` 成了包的叶子，被并的只有外面两层 mux。** mux 的并法是把一位的选择复制到路宽、拼成掩码，再做 `(真臂 & 掩码) | (假臂 & ~掩码)`。

示例所在的组有 14 路、896 位，成员按声明顺序相邻，覆盖三个队列的四个计数器和两个相邻的 `accept` 计数器，`utilizationCounter_31` 在第 5 路：

```text
L      = concat(next_13, …, next_0)                 // 14 个加法结果拼成 896 位
Mclean = concat(14 × replicate(clean, 64))
Mrst   = concat(14 × replicate(!reset, 64))
inner  = (0 & Mclean) | (L & ~Mclean)
packed = (inner & Mrst) | (0 & ~Mrst)
写数据_i = slice(packed, 64·i, 64)
```

[流程中的位置](../../scripts/wolvrix_xs_grhsim.py#L984) · [可并操作](../../wolvrix/lib/transform/comb_lane_pack.cpp#L130) · [mux 的并法](../../wolvrix/lib/transform/comb_lane_pack.cpp#L553) · [默认参数](../../wolvrix/include/transform/comb_lane_pack.hpp#L31) · [示例组的成员](../../build/armor-perf-pack-v1/group.json)

## 生成的 C++：加法、打包、提交分在三处

**加法在队列自己的 supernode 578 里**，仍是标量，带比较和通知：

```cpp
// op _op_15882860 [kAdd]
const std::uint64_t next_value = state_logic_storage_.u64_slots_29653 + value_u64_slots_[24113];
const bool grhsim_changed_4939519 = (value_u64_slots_[67279] != next_value);
grhsim_any_changed_578_2 |= grhsim_changed_4939519;       // 变了就通知下面的打包 supernode
value_u64_slots_[67279] = next_value;
```

**打包在 supernode 24616 里。** 先把 14 个标量槽逐个装进局部数组，做四次 14 字的按位运算，再逐路取出：

```cpp
std::array<std::uint64_t, 14> grhsim_v5216619_0{};
grhsim_v5216619_0[5] |= value_u64_slots_[67279];           // 共 14 路，逐个装入
const auto grhsim_v5216623_0 = grhsim_and_words_full<14>(grhsim_v5216619_0, value_words_14_slots_[1]);
const auto grhsim_v5216624_0 = grhsim_or_words_full<14>(value_words_14_slots_[2], grhsim_v5216623_0);
const auto grhsim_v5216627_0 = grhsim_and_words_full<14>(grhsim_v5216624_0, value_words_14_slots_[0]);
const auto grhsim_v5216629_0 = grhsim_or_words_full<14>(grhsim_v5216627_0, value_words_14_slots_[3]);
// op _op_16586317 [kSliceStatic]
const std::uint64_t next_value = grhsim_slice_words<1>(grhsim_v5216629_0, 320, 64)[0];   // 第 5 路
value_u64_slots_[11811] = next_value;                      // 不比较，直接写
```

四个 `value_words_14_slots_` 是在别处算好的掩码：`[0]` 是 `!reset` 的掩码，`[1]` 是 `~clean` 的掩码。`[2]` 和 `[3]` 是“全零与掩码”，恒为零，没有被常量折叠掉。

**提交在 `eval_commit_batch_90` 里**，逐个寄存器比较，变了才写并重新激活读者，读者就是 578：

```cpp
const auto next_value = static_cast<std::uint64_t>(value_u64_slots_[11811]);
if (unlikely(state_logic_storage_.u64_slots_29653 != next_value)) {
    state_logic_storage_.u64_slots_29653 = next_value;
    supernode_active_curr_[48u] |= UINT8_C(64);
}
```

[加法](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_0.cpp#L74171) · [打包](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_47.cpp#L124) · [掩码](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_46.cpp#L130014) · [提交](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_90.cpp#L108685)

## 一拍里发生什么

1. 上升沿提交：某个队列的 `utilization` 或 `empty` 计数器变了，激活 578。
2. 下一轮 578 运行，重算这个队列的全部 15 个值。实测它每拍激活一次，每次有 2 个输出变化，是同一个计数器的两份结果，一份供打包，一份保留为具名线网。
3. 输出变化激活 24616。调度把四个组放进了这个 supernode，共 50 路。它每拍激活一次，每次把 50 路全部装入、运算、取出，写 50 个槽，自身没有任何比较。
4. 下个上升沿，提交把这 50 个寄存器逐个比较。按 Chisel 的定义，每个队列每拍只有一个计数器在变，其余各路是白算。

打包在这里换来的东西很少。原本每个计数器是两次与路宽相同的选择；打包后是逐路装入、四次宽运算、逐路取出，另加两个恒零的宽操作数。

## 规模

| 口径 | 数值 |
| --- | ---: |
| `comb-lane-pack` 全部分组 / 根 | 4,810 / 56,214 |
| 其中全部成员是端点计数器的分组 / 根 | 2,029 / 32,292 |
| 端点计数器占全部被打包根的比例 | 57% |
| 端点寄存器被打包的比例 | 99% |
| 16 路 64 位的分组 | 2,009 |
| 取路 supernode 每拍激活 0.99 次以上的分组 | 1,395 |
| 承载这些分组的 supernode / 占 compute 求值量 | 1,635 / 13.3% |

端点分组只有四种签名：1,312 组是直方图形态，672 组是上面的累加形态。直方图的一组常常同时装着 `Sum`、`NSamples`、上下溢和若干个桶，`NSamples` 每拍加一，同组各路跟着重算。[分组统计脚本](../../build/armor-perf-pack-v1/report.py) · [与激活率的对照](../../build/armor-perf-pack-v1/hist.py) · [生成时的打包报告](../../../wolvrix-playground-new-xiangshan/build/xs/parent-default-single-20261114-v1/comb_lane_pack_report_xs.json)

## 证据边界

- Chisel 源码与生成这份 RTL 的工作区逐字节相同。打包前的 IR 没有直接导出，树形来自打包报告里的签名和生成代码中的四次宽运算，两者一致。
- “其余各路是白算”在本文写成时来自 Chisel 的定义和 578 的变化计数。随后的逐寄存器观察给出了实测值：每拍重算 24,444 路，真正变化的是 1,316 路。[处理建议与实测](./TNO0011_perf_counter_lowering_20261119.md)
- 求值量是源码层面的物化值个数，不是宿主时间。没有做关闭打包的对照；现有开关 `WOLVRIX_XS_GRHSIM_SKIP_COMB_LANE_PACK` 会关掉全部分组，不只是性能计数器。
