# TNO0402：香山译码表 intrinsic 语义、接入与实施进度

日期：2026-11-03。状态：实施中，尚无性能结论。

## 已核对的真实调用

`backend/Bundles.scala` 中 `DecodeOutUop.decode` 使用 `ListLookup`，32 位输入生成
14 个控制字段，TLConfig 现有产物有 8 个 DecodeUnit。另覆盖前端 BranchAttribute、
CompressUnit、UopInfoGen、DecodeUnitComp、VIPU 中的 ListLookup / DecodeLogic / decoder。
不以旧的独立 utility 微基准替代这些实际实例。

## NEMU 调研

固定上游版本 `03e3b5c857f808c7c11de38c6ab26311bcab2d76`（2026-11-02）。
[decode.c](https://github.com/OpenXiangShan/NEMU/blob/03e3b5c857f808c7c11de38c6ab26311bcab2d76/src/isa/riscv64/instr/decode.c)
先区分指令长度，main 表按 opcode 类别转到子表，子表继续检查 funct 等字段。
[宏定义](https://github.com/OpenXiangShan/NEMU/blob/03e3b5c857f808c7c11de38c6ab26311bcab2d76/include/cpu/decode.h)
将模式转换为 key/mask/shift，并以条件匹配和 return 分派。用当前 Clang 23.1.2
对三个摘取的匹配器编译 `-O3 -march=native`，字符串解析被常量折叠，只剩 mask/test/cmp。
这不是对整个 NEMU 的汇编或速度测量。

NEMU 还使用指令／基本块译码缓存；本轮只借鉴分层匹配，不引入按 PC 或历史输入缓存。
共享约束位递归分组由实际表推导，不硬编码 RISC-V 字段，也不固定取低 8 位。

## 等价契约

- ListLookup 保留表项顺序和首次匹配，默认值与字段宽度不变。
- TruthTable 合并所有命中项的有约束输出位；相交且冲突的原表保留硬件路线。
- 输入 `?` 是通配符；输出／默认值真正未约束的位确定性填零，允许不同于生成器。
- 原表解释器计算 value/care，验证 `(actual ^ value) & care == 0`。
- 生成 SV 自包含常量表。导入后只有输入是动态操作数，表属性不是运行时依赖。
- C++ 使用小表 LUT 或共同 mask 递归分组；不超过 4 项或无共同约束时使用叶子。

## 实施记录

2026-11-03：开始 utility 同名入口、版本化 transport、纯组合 kDecodeTable 和真实表采集。
整机将使用同次源码的 A=none/B=decode-table；DiffTest 两侧均开启，node030 CPU96，
专用单模型单线程，保留 SLP，正式 8 对 AB/BA C100000。当前尚未开始构建或采样。


## 增量：基础闭环验证

小型优先表已通过 Chisel→SV→GRH→C++ 全链路；GRH 只有一个动态输入和
`decode.table` 属性，生成的 C++ 使用静态 LUT，未残留 DPI。两个种子的输入穷举均与
原始 Verilator、普通 GrhSIM、独立原表解释器一致。

新增 native 检查已通过：序列化和来源、常量折叠、CSE、DCE、无关输入不激活、
输入变化但结果不变时不传播到后续组，以及跨组必要的值物化。当前仅为 fixture 验证，
真实香山生成与更完整的宽值、DontCare 验证仍在进行。


## 增量：完整限定名调用补齐

初次真实生成成功，初步覆盖 35 个实例／14 个不同表。主译码为 739 项、74 位输出、
8 个实例；CompressUnit 为 6,561 项、16 位输入、104 位输出。
进一步不限制参数书写方式的源码扫描发现 Rename/ROB 退休数量编码、浮点转换、
FliTable 和 CSR 权限判断中的完整限定名 decoder 调用。已将这些调用也路由到 utility。
因此上述 35／14 仅为初步数目；首个整机 A 构建在采样前停止，保留 v1 记录，
补齐后使用新目录重新固定源码并完整生成 A/B。


## 增量：实际大表与公共 API 检查

初步 14 张真实表全部通过原库 Verilator、普通 GrhSIM、intrinsic 与独立约束解释器交叉验证。
32 位主译码使用两组各超过 100,000 个随机和逐行定向输入；CompressUnit 穷举 65,536 个输入，
包括表外默认值。小表均按完整输入空间穷举。

检查修复了两处实验实现问题：kernel 提取需保留各原始作用域并提供仅用于诊断的活动字临时量；
Scala 冲突检测不能在 List 内层反复按索引访问，已改为索引集合，并对同 mask 的不同 key
直接判为互斥。另补齐 Bool 返回类型、动态输出／未知宽度回退和单次 elaboration 开关隔离检查。
为保证整机 A/B 源码冻结，v2 也在正式采样前停止；最终使用新的 v3 目录，前两轮不计入性能样本。
