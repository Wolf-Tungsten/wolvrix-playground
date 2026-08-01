# 28 LogPerf 核查证伪与 memory op 语义备忘（2026-08-01）

承接目标「ingest 层面降 op」的两个前置核查。结论：

1. **LogPerfEndpoint 不是配置可关项，"快赢"证伪**（但保留一个行为变更型可选项）。
2. **kMemoryWritePort 已有逐位 mask 语义**——ingest 直出存储语义大概率不需要
   IR 扩展，P1 的可行域比 doc 25 估计的大。

## 1. LogPerfEndpoint 核查：证伪

doc 22 I4 的采样（AM logic_and 19,475 + logic_or 19,474 + concat 10,534 vs
gsim ≈0）曾被怀疑是"gsim 构建关了性能计数"。核查证据：

- **两侧输入同一份 RTL**：`build/xs/rtl/rtl/LogPerfEndpoint.sv`（CIRCT 生成），
  AM/gsim 流水都从它出发。
- **gsim 并没有删掉它**（module_attr_20260731.json）：gsim 侧 LogPerfEndpoint
  total 184,565 ops——reg_update 31,767 + when 22,398 + geq 19,883 + pad/ref
  等。计数器和比较都在，只是 guard 组合用 **`when` 区域 op**（22,398 个）承载，
  不物化成 and/or 数据流树；AM 侧物化成 logic_and/or 树 + 每寄存器
  register/read_port/write_port 三元组（30,936 × 3 = 92,808 state ops）。
- **AM 侧打印也没删**：E1 stats 里 kSystemTask(fwrite) 7,236 个，emit 出的
  C++ 里以 `TaskFormatter`/`task_output_N` 形式真实存在
  （grhsim-am-l1l2/grhsim_emit/grhsim_SimTop_blocks_13_part_18.cpp 等）。
- **模块纯汇聚、无输出**：LogPerfEndpoint 端口全为 input（perfCnt_bore_* 数百
  个），计数器只喂内部 $fwrite。数据不出模块。

全量对账（LogPerfEndpoint，AM vs gsim）：

| 口径 | AM | gsim |
|---|---:|---:|
| total ops | 252,927 | 184,565 |
| compute ops（logic+mux+concat+slice+cmp+arith+cast） | 148,475 | 142,581 |
| logic_and+logic_or | 38,949 | 0（由 when 22,398 承载） |

**判断**：不是快赢。两边都完整保留了性能计数与打印；43k 的 logic 差还是
I4 guard 物化 vs `when` 区域的老故事，不在 ingest 数组语义路线的射程内。

**保留的可选项（行为变更，未做）**：ingest/流水加开关跳过 LogPerfEndpoint
（或 XSPerf 类纯观测模块）的计数器与打印——可省 AM 侧 252,927 total ops
（compute 148,475），difftest 不受影响（不校验 perf 日志），但 emu 将失去
性能计数打印能力，属于**可观测性行为变更**，且 gsim 侧保留该模块、对比口径
会变成"AM 删了 gsim 留着的内容"。是否采用由用户拍板，默认不做。

## 2. memory op 语义备忘：P1 不需要 IR 扩展（大概率）

`wolvrix/docs/grh/grh-ir.md` §存储器（1026 行起）：

- **kMemoryWritePort**（1116 行）：operands = updateCond, addr, data,
  **mask（逐位写掩码，位宽同行宽）**, events...；
  `memoryWrite.priorityGroup/priority` 支持同组有序写（0 为最高优先级、最后
  写入，同地址掩码重叠时高优先级赢）。
  → **字段级部分写可直接表达**：mask = 字段位段的常量掩码，data = 字段值
  zext/拼接到行宽。doc 25 设想的 "masked write IR 扩展" 已存在。
- **kMemoryReadPort**（1094 行）：异步读，operand = addr，result = 整行。
  读字段 = 读整行 + kSliceStatic（每读口每字段 1 个 slice）。
- **kMemoryFillPort**：整存填充，可用于统一 reset 形态。
- 复位：写端口无复位语义，由上层显式控制 updateCond/data——reset 写成额外
  写口或 data/cond 上的 mux，与 reg-to-mem 现有做法一致。
- 多维数组：地址表达式拍平（bankSel*N + ptr；N 为 2 的幂时退化为 concat）。

含义：P0 决策门里 "C 类（需要 masked write）" 应从"需要 IR 扩展"改判为
"现有语义可装"。P1 的覆盖面因此扩大到几乎所有规则数组，关键约束只剩：

- 读地址/写地址必须能由地址表达式计算（动态索引 OK，一热译码树不再需要）；
- 写口数量 = SV 源码里的写站点数（而非 entry 数），guard 逻辑进 addr/cond；
- reset 非统一的数组需要逐行 reset 写口或拍平 fill + 例外写口。

## 3. ingest 挂点摸底

ingest.cpp 已解析 unpackedDims（`UnpackedDimInfo`，ingest.cpp:471；
声明处理 9927 附近；元素访问 5660/15147/15476/18570 附近）。P1 的改动面：
数组声明 → 建 kMemory + 读/写口 op 而非逐 entry register；访问点（读写
select）→ kMemoryReadPort/kMemoryWritePort + 地址表达式。
