# 29 路线重锚：爆炸发生在 firtool，不在 wolvrix ingest（2026-08-01）

为 P1（ingest 直出存储语义）做挂点摸底时发现一个改变前提的事实：
**香山 SV 输入里根本没有数组可认——逐 entry 爆炸是 firtool 生成 Verilog
时打平的，发生在 wolvrix 之外。**

## 1. 证据链

- `build/xs/rtl/rtl/Rob.sv:7510` 起：`reg robEntries_0_vls; reg
  robEntries_0_interrupt_safe; ...`——352 entry × 每字段一个独立标量 reg
  声明，全模块 159,064 处 robEntries 引用。SV 源码里不存在
  `robEntries[352]` 数组声明。
- pre-reg2mem GRH 里的寄存器符号（`cpu$...$rob$_robEntries_0_uopNum_T_2`，
  14,432 个 kRegister）名字直接来自 SV 的这些标量 reg + Chisel 临时名。
- reg-to-mem 的 discovery 本来就是"按名字模式把标量 reg 聚成组"——SV 里
  仅存的真数组（`logic [W-1:0] xxx [N]`）由 ingest 的 memoryRows 路径
  （ingest.cpp:17693 起）直接建 kMemory，根本不经 reg-to-mem。
- gsim 的输入是 **FIR**（`build/xs/rtl/rtl/SimTop.fir`，1.67G）：里面
  `robEntries[0].debug_commitType` 等聚合形态完好。gsim 的 splitArray /
  mergeNodes / OP_WHEN 全部工作在数组和 when 区域语义还在的图上。
  module_attr：Rob 在 gsim 侧 register=0、mem=80、state 总计 6,764
  （AM 54,357）——gsim 把 robEntries 保持为数组级节点，一个节点装全部
  352 entry。

**结论：87.1 万 logic 差的根源是输入语言层——AM 吃打平后的 SV，gsim 吃
保留聚合语义的 FIR。** 不是哪一边优化强，是 gsim 的图从第一天起就是
数组/向量级的。

## 2. 对 P1 的影响：原方案落空，三条替代路线

原 P1（"ingest 把 SV 数组直出 kMemory"）没有工作对象：SV 里真数组已被
现有两条路径（ingest memoryRows + reg-to-mem）覆盖，爆炸大头来自 firtool
打平的标量 reg。替代路线：

### R-A：firtool `--preserve-aggregate` 重生成 RTL
让 SV 保留数组/结构体形态，ingest 的 isPackedAggregateVariable 路径
（ingest.cpp:17398 起）有可能直接吃下。
- 卡点链：mill 不在 PATH（2026-07-31 重生成已失败，exit 127）→ Chisel
  重跑（40G JVM）→ firtool 版本是否支持所需 preserve 模式 → ingest 对
  聚合端口支持不全（ingest.cpp:893 "Unpacked array port flattened"）→
  下游全部重新验证。
- 风险：每一步都可能炸；但成了就是"输入对齐"，最治本。

### R-B：图级重向量化 pass（名字聚合 + 同构锥合并）
在 wolvrix 里加 pass：按名字模式（`arr_<i>_<field>`）把标量 reg 聚成宽
向量寄存器，把逐 entry 同构逻辑锥（结构相同、仅常量 `==i` 不同）合并成
宽位向量 op。这是 gsim 优势的"逆向工程"：它从数组出发，我们从打平图
重建向量。
- 关键性质：**不需要做 guard 语义匹配**（doc 25 证伪的是"识别 guard 里
  的地址等式"，而向量化只要求逐 lane 锥同构，guard 树原样变宽即可——
  `enqPtr==i` 各 lane 合并成一个宽 eq+onehot 掩码形态）。
- 与现有资产的关系：comb-lane-pack 已做同构 comb 树打包（签名匹配），
  缺的是寄存器侧聚合（宽向量 reg + masked 写）让打包有落点。
- 语义等价可机验：逐 lane 锥同构是结构判据，difftest 兜底。
- 风险：多驱动/非统一 reset/非规则访问的数组要排除；合并率依赖
  firtool 打平后逻辑保持逐 lane 同构（大概率成立，因为是复制生成的）。

### R-C：FIR frontend
给 wolvrix 写 FIR 解析。工程量不在本目标预算内，否决。

## 3. 与 P0 的关系

P0（doc 27，进行中）按"SV 数组声明"盘点，其 reg-to-mem 拒绝组的名字
join 与 guard 形态分类仍然有效——那正是 R-B 的分组输入。P0 结论需要按
本节重读：决策门"可直出 memory 语义的数组"应改判为"可名字聚合且逐
lane 同构的标量 reg 组"，R-B 的覆盖面用同一份数据估算。

## 4. R-B 实证：wflags 352 lane 同构验证（E1 图）

用全图 op 索引 + 重建的写口映射（`/tmp/grh_write_ports.json`，211,641 个
kRegisterWritePort 的 regSymbol→operands，从 post stats JSON 流式提取——
注意写口的寄存器引用在 `regSymbol` attr，in = [updateCond, data, events...]）：

- `robEntries_<i>_wflags`（i=0..351）352 个寄存器的写锥做结构签名
  （op kind 树，常量抽象为 `C`，寄存器读为叶）：
  **351 lane 共享同一签名**，lane 0 略异（reset 特化，cone 151 vs 144）。
- 每 lane 写锥 ≈ 300 ops（cond 144 + data 157）。若向量化合并 351 lane，
  理论节省 ≈ 351 × (lane 相关部分) ~ 10 万 op 量级（**单字段**；
  lane 无关子表达式经 CSE 共享后实际收益打折，打五折也有 ~5 万）。
- 合并需要"常量按 lane 参数化"：`enqPtr==i` 的常量 i 变成 lane 函数
  （onehot 掩码/常量向量），lane 0 的 reset 特化单独处理或排除。

结论：R-B 的核心假设（firtool 复制生成的逐 lane 逻辑保持同构）成立，
且不需要理解 guard 语义——签名相等是结构判据。

## 5. 下一步

1. 等 P0 完成，用其分组数据估算 R-B 覆盖 op 数（≥40 万门槛不变）。
2. R-B 技术设计：分组判据（名字模式 + 元素数×字段宽度）、同构锥判定
   （结构哈希，常量按 lane 参数化）、宽 reg 的 reset/多写口形态、与
   comb-lane-pack 的先后关系。
3. R-A 作为平行选项评估环境成本（mill/firtool 可得性）。
