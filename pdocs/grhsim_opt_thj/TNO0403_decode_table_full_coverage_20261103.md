# TNO0403：译码表完整覆盖、真实表验证与结构记录

日期：2026-11-03。状态：功能与局部生成结构已验证，整机 A/B 构建中，尚无 walltime 结论。

## 本轮冻结范围

整机目录为 `build/xs/decode_table_20261103_v3`。A/B 的源码身份完全一致，Wolvrix Python 绑定与共享库均复制冻结。A 使用 `none`，B 使用 `decode-table`；RTL、模型、编译与运行四层 DiffTest 都为 on。

完整 Chisel 生成发现 106 次主源码译码调用，涉及 24 张不同的合法常量表。B 接入 70 次，其余 36 次为 `PreDecode` 中 `BranchAttribute.decode` 的输入在调用时尚无已知位宽，保留原库路径。A 对全部调用保留硬件路线。A/B 导出的原始表载荷逐字节一致。这里的次数是 elaboration 次数，不是动态执行频率，也不是 firtool 合并后的模块数。

## 实际表

| 名称 | 输入位 | 输出位 | 行数 | 实例数 | 生成形态 | 常量表字节 |
|---|---:|---:|---:|---:|---|---:|
| Ifu / `83af1c51` | 32 | 2 | 7 | 1 | LUT | 65568 |
| RobImp / `daaf3899` | 6 | 5 | 44 | 8 | LUT | 200 |
| RobImp / `a58b7b24` | 6 | 4 | 44 | 8 | LUT | 136 |
| indexedLSUopTable / `ab90a3b3` | 4 | 6 | 16 | 1 | LUT | 24 |
| indexedLSUopTable / `8afa4c15` | 4 | 6 | 16 | 1 | LUT | 48 |
| indexedLSUopTable / `7f483cf2` | 4 | 6 | 16 | 1 | LUT | 64 |
| indexedLSUopTable / `411f01a1` | 4 | 6 | 16 | 1 | LUT | 64 |
| indexedLSUopTable / `6ced100e` | 4 | 6 | 16 | 1 | LUT | 80 |
| indexedLSUopTable / `68bda87f` | 4 | 6 | 16 | 1 | LUT | 80 |
| indexedLSUopTable / `3d1dbcee` | 4 | 6 | 16 | 1 | LUT | 80 |
| indexedLSUopTable / `114c881e` | 4 | 6 | 16 | 1 | LUT | 80 |
| DecodeUnit / `209c1d06` | 32 | 74 | 739 | 8 | 共同约束树（深 5、叶最大 26） | 0 |
| strdiedLSNumOfUopTable / `7354cad2` | 5 | 4 | 32 | 8 | LUT | 104 |
| indexedLSNumOfUopTable / `0ba7a080` | 7 | 4 | 128 | 8 | LUT | 200 |
| CompressUnit / `43577565` | 16 | 104 | 6561 | 1 | LUT | 67600 |
| Rename / `e50df135` | 8 | 6 | 44 | 8 | LUT | 616 |
| PrivilegePermitModule / `6d856f20` | 5 | 1 | 11 | 1 | LUT | 48 |
| I2F / `a1607bf0` | 4 | 4 | 11 | 2 | LUT | 56 |
| FliHTable / `b1fbd8d6` | 5 | 16 | 32 | 2 | LUT | 280 |
| FliSTable / `4c9720c2` | 5 | 16 | 32 | 2 | LUT | 288 |
| FliDTable / `c39e6905` | 5 | 16 | 32 | 2 | LUT | 288 |
| VIAluDecoder / `3c53191c` | 9 | 15 | 18 | 1 | LUT | 664 |
| VCVT / `448aeeef` | 4 | 4 | 9 | 1 | LUT | 56 |
| VCVT / `07a31ec8` | 3 | 4 | 6 | 1 | LUT | 40 |

主译码是 739 行、74 位输出，按 14 个字段打包；递归树有 646 个节点、最大深度 5。最大叶长 26 表示该叶没有所有候选共同约束的剩余位，因此按规则直接匹配，没有复制通配项。CompressUnit 是 16 位输入、6,561 行、104 位输出，结果池和索引合计 67,600 字节。

BranchAttribute 虽然只有 7 行，匹配涉及 16 个有效输入位，因此按预先固定的规则生成约 64 KiB LUT。这未必优于小型比较链，后续计时会保留该结果，不事后排除该调用。

## 来源覆盖及边界

主源码扫描到 17 个调用位置，均已路由到同名 utility。`Bundle.scala` 与 `FCVT.scala` 中的接口本轮未出现实际表实例，其余实际调用见 `coverage.json` 的 sites。另有 19 处 Rocket Chip／YunSuan 内部调用未替换，不引入第三方库对 utility 的反向依赖；utility 内部的 4 个原库回退位置也单独记录。

源码扫描记录语法出现；`SourceInfo`、模块类名和完整 table_id 共同记录真实 elaboration。当前不把 Chisel 类名冒充唯一硬件实例路径。完整 source_scan、calls 和原表可在 `coverage.json`、`tables/*.table` 复核。

## 验证

24 张表已通过独立解释器、原库 Verilator、普通 GrhSIM 和 intrinsic。不超过 16 位输入的表穷举整个输入空间；32 位表使用两组固定种子，每组至少 100,000 个随机向量，加每行定向命中、全零、全一及单置位输入。输出仅按原始 care_mask 比较，未命中行为使用原表默认值。

补充 fixture 覆盖：部分 DontCare、兼容重叠约束、优先匹配、65 位输入／129 位输出、宽输入递归树、无共同约束位的 TruthTable 合并叶子。针对公共 API 还验证了 Bool 返回类型、动态默认值回退、未知位宽回退、when 内调用以及同 JVM elaboration 隔离。

针对 GRH 的 native 测试覆盖序列化、来源、常量折叠、CSE、DCE、SSA、无关输入、输出不变时禁止后续激活、必要的跨组物化。普通 DPI 回归及错误 transport 拒绝测试通过。

对多字段 TruthTable 的局部 replay 增加字段拆分再组合，确保 metadata 与完整 elaboration 的载荷相同；旧版只验证打包后的位语义，记录保留。

## 测量准备

局部 runner 为 `scripts/decode_table_measure.py`：CPU96、node1 私有 binary/library 副本和运行中 NUMA 检查，kernel 与完整 eval 分开，每种分布 8 对 AB/BA。真实提交指令由 `scripts/decode_table_trace_inputs.py` 从有效 DiffTest commit slot 按顺序导出，只代表已提交的扩展后指令，不代表全部推测译码活动。

整机仍由 `grhsim_single_compare.py` 进行两个种子的 C100000 有效轨迹检查和 8 对正式测量。构建完成前不开始正式计时。

## 产物与前序

- `build/xs/decode_table_20261103_v3/coverage.json`、`local_structure.json`。
- `wolvrix/build/artifacts/decode-table-study/real-final-v3/cases.json`，后续字段完整 replay 在 `field-layout-v4`。
- `wolvrix/build/artifacts/decode-table-study/wide-tree-v1`、`trace-export-fixture`。
- [TNO0402 语义契约与 NEMU 调研](./TNO0402_decode_table_intrinsic_contract_20261103.md)。

## 补充：36 次未知位宽回退的具体来源

36 次全部在 `PreDecode` 的指令槽 `i=0..35`，manifest 调用 id 为 `262..297`。
`frontend/ifu/PreDecode.scala:47` 的循环中，48 行 `val inst = WireInit(rawInsts(i))`，
57 行调用 `BranchAttribute.decode(inst, io.req.valid)`，最终在
`frontend/bpu/Bundles.scala:108` 使用 `PreDecodeInst.brTable`。

表只有 7 行：C_EBREAK、C_J、C_JALR、C_BRANCH、JAL、JALR、BRANCH。
C_EBREAK 必须先于 C_JALR，避免压缩断点被当成间接跳转。该次替换范围是 2 位
branchType 的 ListLookup，后面的 rd/rs 与 RAS push/pop 逻辑仍按原代码生成。

输入 IO 明确为 UInt(32.W)。Chisel 7.3.0 的 `Data.scala` 中，单参数
`WireDefaultImpl.apply` 对非字面量 Bits 使用 `cloneTypeWidth(Width())`；WireInit 是
该实现的别名，故调用时新 wire 的宽度未知，留到后续推导。B 的 `PreDecode.sv`
确认 `io_req_bits_data_0..35` 均为 32 位。问题是 elaboration 阶段的信息缺失，不是
表输出动态或最终硬件位宽不确定。

另一个 IFU 非缓存路径 `Ifu.scala:713` 的输入位宽已知，使用相同表并已成功替换。
如果后续扩展这 36 次覆盖，可显式创建 `WireInit(UInt(32.W), rawInsts(i))` 或在无重赋值
需求时直接使用原输入；本轮已冻结的 A/B 保持当前范围。完整原始调用记录见
`build/xs/decode_table_20261103_v3/fallback_detail.json`。

## 补充：实际分组与有效输入穷举

主译码原表的共同输入 mask 为 `0x7f`，根节点按 23 个 opcode 值分组；
load 子组继续得到 `0x7000` 的 funct3 mask。层次由表生成，不是后端硬编码。
`table_shape_examples.json` 保存 ADDI、ADD、JAL、BEQ 及未命中输入的匹配行和 14 个
输出字段，未命中时保留主表原有 74 位确定性默认值。

BranchAttribute 虽为 32 位输入，其有效位仅为 0..15。除两个种子的随机／定向
验证外，补充枚举全部 65,536 个有效输入组合，并把无关高 16 位置一；原 Verilator、
普通 GrhSIM 与 intrinsic 全部通过。证据在
`wolvrix/build/artifacts/decode-table-study/effective-inputs`。
