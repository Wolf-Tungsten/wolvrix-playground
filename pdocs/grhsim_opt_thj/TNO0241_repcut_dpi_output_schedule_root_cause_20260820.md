# RepCut DPI output 调度错误根因调查

日期：2026-08-20

状态：`ROOT CAUSE CLOSED FOR NATIVE T1; PARTITIONED HIGH CONFIDENCE; FIX NOT IMPLEMENTED`。

关联记录：[TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md) 与 [TNO0240](./TNO0240_repcut_thread_scaling_performance_results_20260819.md)。

## 1. 结论

本轮 `csr_dbltrp_inMN` 不是新加入的 XiangShan 断言，也不是实际同时运行多个 host 线程造成的数据竞争。直接故障机制是：

1. 原始 `FlashHelper.v` 在一个 `posedge` 过程内调用 `void flash_read(input addr, output data)`，DPI output 直接写 `r_data`。
2. Wolvrix ingest/emit 后把它拆成 `_val_9993955_intm`、连续赋值和独立的 `r_data_1` 状态提交。
3. RepCut 把 `hasReturn=false` 等同于“不产生 effect value”，没有把 `output/inout` 参数视为返回 effect；因此原过程内的 DPI producer 与状态消费者之间没有形成足以约束后端调度的依赖。
4. Verilator native t1 和 partitioned part3 最终均按 `reader -> commit -> producer` 执行，提交了旧的 flash 返回值；native t2 则按 `producer -> reader -> commit` 执行，偶然掩盖了问题。
5. 在冻结 native t1 中仅把这三个任务改成 t2 的相对顺序，其他生成对象和 harness 保持不变，原固定 cycle 605 assertion 消失，CoreMark 跑满 C10000，并得到与 t2 相同的 `pc/instr/cycle` 签名。

因此 native t1 的当前报错已经完成因果闭环。partitioned 的内部 part3 具有同类错误顺序，且 host `N=1/2/4/8` 只并行不同 part、不会改变 part3 的单线程内部顺序；这与四档都在 cycle 605 失败完全一致。partitioned 尚未做独立的 patched-unit 动态 A/B，故在本文中标为高置信度而不是完全闭环。

## 2. 报错只是下游检测点

XiangShan 源码 `testcase/xiangshan/src/main/scala/xiangshan/backend/fu/NewCSR/NewCSR.scala:1521-1524` 定义：

```scala
val criticalErrors = Seq(
  ("csr_dbltrp_inMN", !mnstatus.regOut.NMIE && hasTrap && !entryDebugMode),
)
```

对应原始生成 RTL 为 `build/xs/rtl/rtl/NewCSR.sv:6038-6039`。该条件表示 NMIE 已经为 0 时又收到非 debug trap；它说明更早的启动状态已经错误，不能证明 CSR 自身是首个错误模块。

该断言由 XiangShan `85a8d7ca95be7636399af9f3c39382ab20231da7` 于 2024-11-01 引入。2026-03-24/25 的历史 RepCut timing 仍分别完成 `60102` steps，说明“早期仓库不报错”不是因为当时没有该断言。

日志中的 `time=608` 还经过 NewCSR、CSR wrapper 和 ExeUnitImp 共六级寄存传播；原始 `criticalErrorStateInCSR` 的异常窗口约在 time 602 附近。因此 `ExuBlock.sv:908` 是延迟后的报警位置，不是错误发生的第一拍。

## 3. 排除实际 host 并发竞态

native t2 模型要求 VerilatedContext 至少配置两个线程，不能直接用单线程 context 启动。调查脚本先允许它创建 main/worker，再把两个 TID 都重新绑定到 CPU0：

```text
pid 663090: affinity 0,1 -> 0
pid 663105: affinity 0,1 -> 0
```

结果仍越过原失败点并正常到 C700 cycle limit：

```text
rc=0, instrCnt=3, cycleCnt=696, guest=701, no assertion
```

同一 CPU0 上的 native t1 则稳定在 `cycleCnt=605 / guest=609 / time=608` 报错。单个逻辑 CPU 不存在两个线程同时执行，故 t1/t2 分叉来自 Verilator 编译期形成的任务图与任务顺序，而不是物理并行或机器负载。

证据：

```text
build/repcut_error_investigation_20260820/rebind_after_thread_init.sh
build/repcut_error_investigation_20260820/logs/native_t2_rebound_cpu0_c700_affinity.log
build/repcut_error_investigation_20260820/logs/native_t2_rebound_cpu0_c700.log
build/repcut_error_investigation_20260820/logs/native_t1_cpu0_c10000.log
```

## 4. 原始语义如何被拆开

### 4.1 原始 RTL

`build/xs/rtl/rtl/FlashHelper.v:6-10,20-23`：

```systemverilog
import "DPI-C" function void flash_read(
  input int unsigned addr,
  output longint unsigned data
);

always @(posedge clock) begin
  if (r_en) flash_read(r_addr, r_data);
end
```

这里 C 函数本身是 `void`，但 `output data` 是可观察结果。

### 4.2 GRH 已经保留 output value

冻结 JSON `build/repcut_thread_scaling_20260819/generated/xs_wolf_repcut.json:2751234-2751235` 中：

```text
kDpicImport flash_read:
  argsDirection=[input, output], hasReturn=false
kDpicCall _op_10884357:
  out=[_val_9993955], outArgName=[data], hasReturn=false
```

因此“C return type 为 void”和“GRH operation 不产出 value”不是一回事。

### 4.3 RepCut 分类遗漏 output/inout

`wolvrix/lib/transform/repcut.cpp:252-280` 的 `opHasReturnedEffectValue()` 只检查 `hasReturn`；为 false 时立即返回，不查看 `outArgName` 或 `inoutArgName`。后续 returned-effect cone 收集和 DSU 共置也只使用这个 predicate（同文件 `1201-1207,1597-1620`）。

现有测试 `wolvrix/tests/transform/test_repcut_pass.cpp:612-659` 只覆盖：

- `hasReturn=true` 的 DPI；
- `hasReturn=false` 且没有 output 的 DPI。

没有覆盖本次的 `void DPI(input, output) -> state` 形态。

### 4.4 SV emitter 引入中间状态

`wolvrix/lib/emit/system_verilog.cpp:5512-5523,5553-5622` 为 DPI result 建立 `<value>_intm`，再通过独立 value assign 连接。冻结输出 `SimTop_repcut_part3.sv:2398560-2398562,2636875-2636879` 为：

```systemverilog
assign helper$r_data = helper$r_data_1;
assign _val_9993955 = _val_9993955_intm;

if (DifftestFlash_io_en)
  flash_read(io_addr, _val_9993955_intm);
if (DifftestFlash_io_en)
  helper$r_data_1 <= _val_9993955;
```

原来“DPI output 直接更新状态”的一个过程，被变成 DPI producer、连续连接和寄存器提交。Verilator 无法从外部 DPI output side effect 推导出所需的 producer-before-commit 约束，故不同 `--threads` 设置生成了不同顺序。

## 5. 三种后端中的实际任务顺序

| 构建 | producer | reader | commit | 最终顺序 | C10000 结果 |
| --- | --- | --- | --- | --- | --- |
| native t1 | `TOP__124` | `TOP__36` | `TOP__107` | reader -> commit -> producer | assertion @ 605 |
| native t2 | `TOP__1181` | `TOP__1182` | `TOP__1183` | producer -> reader -> commit | cycle limit @ 9996 |
| partitioned part3 | `TOP__24` | `TOP__9` | `TOP__21` | reader -> commit -> producer | assertion @ 605，N=1/2/4/8 相同 |

native t1 调度位置：

```text
build/repcut_thread_scaling_20260819/build/native-t1/verilator-compile/
  VSimTop___024root__518.cpp:10717,10922,10938
  VSimTop___024root__38.cpp:1541        # reader
  VSimTop___024root__96.cpp:16460-16462 # commit
  VSimTop___024root__111.cpp:6824-6837  # producer
```

native t2 的三个任务在同一个 `nba_mtask20` 中连续执行：

```text
build/repcut_thread_scaling_20260819/build/native-t2/verilator-compile/
  VSimTop___024root__224.cpp:4757-4759
  VSimTop___024root__217.cpp:8723-8736  # producer
  VSimTop___024root__218.cpp:9044       # reader
  VSimTop___024root__219.cpp:12021-12023 # commit
```

partitioned part3 位置：

```text
build/repcut_thread_scaling_20260819/generated/package/xs_wolf_repcut_partitioned/build/verilated/part_3/
  VWolviRepCutUnit_part_3___024root__119.cpp:1379,1391,1394
  VWolviRepCutUnit_part_3___024root__47.cpp:23041 # reader
  VWolviRepCutUnit_part_3___024root__57.cpp:7157-7159 # commit
  VWolviRepCutUnit_part_3___024root__60.cpp:3801-3814 # producer
```

partitioned runtime 当前统一执行 `load all -> eval all -> update all`，见 `wolvrix/lib/emit/verilator_repcut_package.cpp:1796-1813`。host `N` 只改变各 part 的并行 worker 数量，part3 模型本身仍是无 `--threads` 的单线程 Verilator unit，所以四档重复同一错误顺序。

## 6. 单点调度 A/B 因果验证

### 6.1 严格变更

在调查副本中只改 `VSimTop___024root__518.cpp` 的调用位置：

```diff
+ TOP__124  # flash producer，移到 TOP__36 reader 之前
  TOP__36   # reader
  ...
- TOP__107  # 原 commit 位置
  ...
- TOP__124  # 原 producer 位置
+ TOP__107  # commit 移到 producer 原位置
```

即把原 `reader -> commit -> producer` 严格改为 t2 的 `producer -> reader -> commit`。没有改 RTL、Wolvrix、XiangShan、DPI C 实现或仿真参数。

对新旧 `VSimTop__ALL.a` 解包逐成员做 SHA-256：只有 `VSimTop___024root__518.o` 不同，其他 archive member 全部相同：

```text
old 7bd5e6769a2f389250b3314f0534453e5b912b537cd9bf8831156a528d045282
new 2df807a7fce94c90fdbef394f33418f4f23cea2c9882895f721460626b41652f
```

最终链接还复用了冻结原始 t1 的全部 user/global harness objects，仅替换上述 model archive。ELF 身份：

```text
original t1: 0958e2c08ed9bd13af55fc773dabb7153c51337247ed23e9ea39eff57d398132
strict A/B:  e261b3003422357afe033a987aaa4efe4057a86955c6ec0624fa98c183c57123
```

### 6.2 运行结果

```text
rc=0
pc=0x800027c6
instrCnt=458
cycleCnt=9996
guest cycles=10001
Host time spent=25007ms
```

这与 matching-profile native t2 的 C10000 功能签名一致，并与原 t1 的固定 `assertion@605 / instrCnt=0` 明确分叉。host time 仅是诊断运行耗时，不进入线程缩放性能统计。

证据：

```text
build/repcut_error_investigation_20260820/schedule_probe/native-t1-flash-first/
  VSimTop___024root__518.cpp
  emu-strict-order-frozen-support
build/repcut_error_investigation_20260820/logs/
  native_t1_strict_t2_order_frozen_support_c10000.log
  native_t1_strict_t2_order_frozen_support_c10000.time
```

此前 `native_t1_flash_first_c10000.log` 实际运行的是复制出的旧 `emu`，不是新链接 ELF，故其失败结果已废止。正确的局部交换 ELF 为 `emu-flash-first`，严格 t2 顺序复核使用本文的 `emu-strict-order-frozen-support`。

## 7. 为什么早期仓库没有报错

最后一个有历史正确运行证据的父仓库版本为：

```text
parent c4b9c1b3eeb805b62a7231937b2cca6a467284a3
wolvrix 3fe4168c48a263c7b6bc2cc42cfb2270241647db
verilator v5.046
```

历史 `scripts/wolvrix_xs_repcut.py:510-587` 的流程是：

```text
strip-debug SimTop
repcut SimTop.logic_part (128 parts)
instance-inline SimTop.logic_part
```

旧 partitioned runtime 会单独执行 `debug_part`，立即 gather/publish 其 DPI/device output，再执行普通逻辑分区。仓库文档 `../draft/xs-repcut-verilator-partitioned-backend-plan.md:25-50,535-537` 明确记录该顺序对 `flash_read/sd_read/difftest_ram_read/jtag_tick` 是已验证正确性约束。

首个高概率回归父提交为：

```text
parent b836afec9e142cf063a3a12767a7abb723aaa626
wolvrix eb805fdff181de85ed1e47b9d4d2aa72842cc22e
date 2026-03-26
```

该变化同时：

- 改为直接 `repcut SimTop`，分区数改为 32；
- 删除固定 `debug_part` 生成/调度路径；
- 在 `eb805fd` 引入只看 `hasReturn` 的 `opHasReturnedEffectValue()`；
- 删除 runtime 中 `debug_part` 先 eval、立即发布 output 的实现。

同日方案 `../draft/repcut-debug-sink-asc-plan.md:275-300,371-390,421-430` 实际要求用 `phase=early|normal` 替代固定模块名，而不是取消 early phase。但该方案列出的阶段 3 没有落到当前 runtime。随后 `da66f53 / wolvrix 52a1af8` 又把统一 `load/eval/update` 两阶段调度固化。

XiangShan 在这一回归区间没有相关 Scala/RTL core 变化；Verilator v5.046 横跨已知正确点与 2026-03-26 流程变化。因此当前 v5.048 可能改变错误暴露方式，但不是最初引入回归的原因。

## 8. 修复边界

不应把 native t2/t4/t8“能跑过”或把 partitioned unit 改成 `--threads 2` 当作修复；那只是在依赖另一种 Verilator 调度掩盖 IR/emitter 语义缺陷。

建议分三层修复：

1. RepCut effect 分类：把 `kDpicCall` 是否产生可观察 GRH value 统一定义为 `hasReturn || !outArgName.empty() || !inoutArgName.empty()`，并统一用于 sink 分类、cone 收集、DSU 共置和 cross-edge 校验，不能只改一个 callsite。
2. SV emitter：保持 `void DPI(output)` 的同一过程内原子关系。可在同一 procedural block 中接收 output 并立即完成相关状态更新，或在合法时直接把状态作为 DPI output actual；不能继续让 `_intm` 与 commit 成为无依赖的可重排任务。
3. Partitioned runtime：若 result-producing effect 仍可跨 partition，则实现 manifest `phase=early|normal` 和 early eval/immediate publish；否则必须禁止这种 cross-partition edge。当前 flash producer/reader/commit 都在 part3，故局部 emitter/依赖修复是 cycle 605 的首要最小闭环，early phase 仍是其他 DPI/device 路径的架构正确性要求。

必须新增以下回归：

- `void DPI(input, output) -> register/state` 的 RepCut 单测；
- 原始 SV 与 emitted SV 的逐边沿等价测试；
- Verilator `--threads 1` 与 `--threads 2 --threads-dpi all` 一致性测试；
- XiangShan native t1/t2 与 partitioned N1/N2 至少越过 cycle 605，并继续跑 10k/difftest gate。

## 9. 证据边界与产物完整性

本轮只调查和构造生成 C++ 调度 A/B，没有修改 Wolvrix、XiangShan 或 Verilator 源码，也没有宣称代码修复已经完成。正式 1/2/4/8 性能矩阵仍保持 [TNO0240](./TNO0240_repcut_thread_scaling_performance_results_20260819.md) 的 `N/A / 0 of 32` 状态；必须修复、重新冻结并通过八配置功能门后才能开始采样。

首次在复制目录重链接时，Verilator 生成 Makefile 的默认 target 保留了原构建的绝对输出路径，曾短暂把 patched ELF 链接到原 target。发现后立即保留 patched ELF，并用原复制 ELF 恢复原 target。最终复核：

```text
original target SHA-256 = 0958e2c08ed9bd13af55fc773dabb7153c51337247ed23e9ea39eff57d398132
```

后续严格 A/B 已把复制 Makefile target 改为本地文件名，不再触碰原构建。工作区既有内容没有删除。

## 10. FST 正反对照

为排除纯静态代码阅读的歧义，使用同一份冻结 `SimTop.sv` 分别构建带 FST 的 native t1/t2 模型。两边均使用固定随机初始化、同一个 CoreMark 镜像、`--no-diff -C 700 -b 0 -e 620 --dump-wave-full`；区别仅为 Verilator `--threads 1` 与 `--threads 2 --threads-dpi all`。

运行结果为：

| 配置 | 退出 | `cycleCnt / guest` | assertion |
| --- | --- | --- | --- |
| trace native t1 | `rc=1` | `605 / 609` | `csr_dbltrp_inMN`，与非 trace 版本相同 |
| trace native t2 | `rc=0` | `696 / 701` | 无，因 `-C 700` 正常结束 |

trace 插桩改变了生成函数编号，但没有改变关键相对顺序：t1 仍是 flash commit 先于 producer，t2 则由 mtask 同步明确保证 DPI producer 先于 commit。因此波形本身没有掩盖原问题。

### 10.1 首个分歧就是 Flash DPI output

两份 FST 中首次 Flash 请求完全相同：

```text
t=1178..1180: DifftestFlash_io_en=1
io_addr=0
```

但 DPI output 的提交结果不同：

| 信号 | native t1 | native t2 |
| --- | --- | --- |
| `helper$r_data_1` | 从 t=0 到 FST 结束始终为 `0` | t=1180 由 `0` 变为 `0x01f292930010029b` |
| `DifftestFlash.io_data` | 始终为 `0` | t=1180 变为 `0x01f292930010029b` |

这里的正确值不是根据后续 CPU 行为反推得到的。运行命令没有传 `-F`，`testcase/xiangshan/difftest/src/test/csrc/common/flash.cpp:62-69` 会把 `flash_dev.base[0]` 初始化为 `0x01f292930010029b`；同文件 `38-46` 规定 addr 0 读取 index 0。因此 t1 在请求之后仍为 0 是确定的错误，t2 的值与 DPI C 实现精确一致。

### 10.2 CSR assertion 的下游传播

t1 的后续波形为：

```text
t=1234: 第一次 exception_delay.valid / trapEntryM
t=1268: 第二次 exception，m_EX_DT=1，dbltrpToMN=1，trapEntryMN=1
t=1270: mnstatus.NMIE 从 1 清为 0
t=1302: 第三次 exception，hasTrap=1，m_EX_DT=1，criticalErrorStateInCSR=1
t=1314: 经六个寄存级传播到日志检测点，对应日志 time=608
```

`entryDebugMode` 全程为 0。相比之下，t2 的 FST 全窗口 `0..1347` 内没有 exception pulse，`NMIE` 始终为 1，`criticalErrorStateInCSR` 始终为 0。

这组同输入、同 trace 配置的正反对照把首次动态分歧定位到 addr 0 的 Flash DPI output：t1 因错误任务顺序丢失正确返回值，约 62 个硬件周期后才表现为 CSR double-trap assertion。它进一步确认 assertion 是下游症状，而不是近期新增或自身逻辑回归。

### 10.3 波形产物

```text
build/repcut_error_investigation_20260820/waves/native_t1_c700.fst
  size=8617508
  sha256=33185d99500f1ea8c43653b26c52b525d91a0ac2c85c846cc94d97e98bacb73f
build/repcut_error_investigation_20260820/waves/native_t2_c700.fst
  size=8634894
  sha256=6aae61acacb037449bf04a3e97e28b72e341685d61e53cf625a3b4b7aa11ef74
build/repcut_error_investigation_20260820/logs/native_t{1,2}_trace_c700.{log,time}
```

FST 输入、RTL 根目录和 Scala 根目录先通过 `hardware-debug-waveform inspect-inputs` 校验；目标值使用 Verilator 随附的 GTKWave `fstapi` 按完整层次和 timestamp 精确读取。宽范围 packet 查询会反复扫描该超大层次，故本轮没有把其未完成输出作为证据。
