# F30：组合数组的多维有序更新

建立日期：2026-11-14。状态：**新 op 及 ingest→split-static-array 主流程已实现，专项与原生大图结构校验通过；v11 实测性能获用户接受，其他对齐/等价与后端事项继续跟踪**。

F30 承接 [F29 的动态写调查与设计草案](F29-node-changes.md#组合数组有序更新-op-设计待实现)，
新增纯组合 `kArrayUpdate`：一个 op 支持一到多次、有序、多维的数组更新。
首阶段打通正常生产流程：

```text
FIRRTL ingest → xmr-resolve → hier-flatten → comb-loop-elim → split-static-array
```

同步更新 GRH IR 定义、验证器与持久化，沿用 F28 的唯一叶 Node 和 F29 的
add/delete/replace、原生演化 trace 及公共五文件合约。本文件是 F30 的
唯一规划与验收记录入口；下列契约是完成标准，已取得的证据单独记录于 §10。

## 问题与本阶段目标

当前 FIRRTL lowering 对非寄存器组合数组的动态下标写，提前生成整数组宽度的
shift、mask、And/Or 和 Mux。`split-static-array` 可以投影 Mux，但遇到
这些宽位运算通常保留共享宽结果再做切片，不能保证消除宽更新。
GSIM 保留带索引的数组左值，完整元素写可生成 `a[i][j] = data`。

F30 保留寻址与有序覆盖语义，使后续仿真后端有条件生成“一次初始化、多次局部
更新”，同时让 comb/split 能依据真实索引与覆盖范围处理依赖和 Node。
不能只增加一个 op 名字，然后在前序流程中立即还原为整数组位运算。
**性能是完成门：GrhSIM 以 GSIM 等价阶段的耗时为参考。** 用户于
2026-11-14 明确：无论是否开启 semantic trace，都与 GSIM 比速度，允许合理
抖动。原先 GrhSIM 改造前后的对照保留作诊断，正式完成标准以 §9 为准。

首阶段交付范围：

| 范围 | 要达到的行为 |
| --- | --- |
| GRH IR | 多维、不同索引数、单次到多次更新的正式操作定义、访问器和严格校验 |
| FIRRTL ingest | 在依赖安全范围内合并有序更新，保持最终连接、使能、类型和写入顺序 |
| xmr/flatten | 操作数、属性、类型、普通/批量复制及 SemanticNode 归属完整保留 |
| comb-loop-elim | 按更新覆盖范围分析与重写依赖，继续解决静态局部假环 |
| split-static-array | 静态更新可投影，动态更新保留明确边界，维护 Node 与原生 trace |
| 持久化与比较 | store/load、库存/连接导出、演化重放及 GSIM 差异分析继续成立 |

本阶段不把后续 DCE、GrhSIM 转换或 CPU/SV emit 的迁移列入完成门；尚未支持
新 op 的后续路径必须在修改图之前明确拒绝，不能静默套用宽位运算降级。
最终仿真性能需要后端迁移后实测，F30 的 ingest/pass 时间不代替运行性能结论。

## 1. GRH 操作定义

### 1.1 操作数与属性

新增基础 GRH 操作 **`kArrayUpdate`**，effect 为 **Pure**，恰好一个结果：

```text
result = kArrayUpdate(
    base,
    enable0, index00, ..., index0(k0-1), data0,
    enable1, index10, ..., index1(k1-1), data1,
    ...
) { indexCounts = [k0, k1, ...] }
```

| 成分 | 定义 |
| --- | --- |
| `base` | 初始数组 value，Logic 且 shape 非空 |
| `enableJ` | 第 J 次更新的一位无符号标量 Logic 使能 |
| `indexJL` | 第 J 次更新的第 L 维下标，无符号标量 Logic，按最外层到最内层排列 |
| `dataJ` | 本次写入的整个目标元素或后缀子数组值 |
| `indexCounts` | 唯一必需属性，已有 `std::vector<int64_t>` 类型；每项表示该组的下标数 |
| `result` | 执行全部更新后的数组，完整 LogicalType 与 base 相同 |

`M = indexCounts.size()` 为更新次数，要求 `M >= 1`。每组连续占 `kJ+2`
个 operand，总数严格为 `1 + Σ(kJ+2)`。第 J 组起点是
`pJ = 1 + Σ(L<J)(kL+2)`，其中 enable 为 `oper[pJ]`，indices 为随后
kJ 项，data 为 `oper[pJ+kJ+1]`。

不重复保存 offsets、updateCount、shape、strides 或 writerOrder。静态下标
用普通 constant operand；运行时 value、enable、data 不藏进 attr，不新增
JSON 字符串属性或 AttributeValue 变体。组的列表顺序就是写入顺序。

core 提供统一构造/访问接口，例如 `ArrayUpdateEntry{enable,indices,data}`
与分组只读 view；调用方不自行计算分组边界。构造接口消费并复制必要引用，不
保存调用方临时 span；线性遍历只计算一次前缀偏移，不为每组重新扫描全部 attr。
保留底层通用 op 构造能力，由 verifier 独立拒绝非法操作。

### 1.2 多维与类型规则

设 base 的 shape 为 `[D0,...,D(R-1)]`、叶宽为 E。每组允许 `0 <= kJ <= R`：

| 下标数 | 更新范围 | data 的 shape |
| --- | --- | --- |
| `kJ = R` | 一个叶元素 | 空，即标量 |
| `0 < kJ < R` | 一个后缀子数组 | `base.shape[kJ:]` |
| `kJ = 0` | 整个数组 | 与 base 相同 |

data 的总宽必须为 `E * product(base.shape[kJ:])`，kind、叶宽、signedness、
logic domain 均与被寻址部分一致；等总宽但不同 shape 不自动接受。不同组
可以使用不同 kJ。只支持消费 shape 的前缀，与现有 `kSliceArray` 及状态数组
端口一致；任意列切片、步长与位掩码不在本 op 的首版合约中。

enable 必须为 unsigned 1-bit scalar Logic，index 必须为 unsigned scalar
Logic；索引不截为 32 位。TwoState 数组只接受 TwoState 控制，FourState
数组允许两态或四态控制。前端负责必要的显式适配。

verifier 校验 attr 必需性与类型、更新次数、组界限、operand/result 数量、
每组索引数和完整数据类型；分组累加、维度乘积、总宽与地址计算均检查溢出。
不能通过截断数值、忽略尾部 operand 或跳过不合法组来容错。

### 1.3 多维示例

base 为 `UInt<8>` 叶、shape `[2,3,4]`、总宽 192：

```text
%result = kArrayUpdate(
    %base,
    %en0, %i, %j, %k, %byte,
    %en1, %row, %plane,
    %en2, %i2, %j2, %vector
) { indexCounts = [3,1,2] }
```

其中 byte 是 8 位标量，plane 为 width=96、shape `[3,4]`，vector 为
width=32、shape `[4]`。确定地址的执行含义是：

```text
result = base
if en0 and indices valid: result[i][j][k] = byte
if en1 and index valid:   result[row] = plane
if en2 and indices valid: result[i2][j2] = vector
```

后面的 plane/vector 可以覆盖前面的 byte。`indexCounts=[0,3]` 还能表示
一次整数组更新后接一次叶元素更新；k=0 不是标量广播。

## 2. 值语义与四态

`kArrayUpdate` 不修改 base，不访问隐式状态，不带 regSymbol、事件或状态写
副作用。定义 `A0=base`，按第 0 到 M-1 组依次产生下一累积值，唯一公开结果
是 `AM`。已知地址时后写覆盖相交区域；不得按地址、名称或 enable 重排。

全部 operands 是进入 op 前的不可变输入快照。若后一次的 data/index/enable
依赖前一次更新后的结果，必须保留两个 op 的数据依赖，不能删除该依赖后合并。
例如以 base 两处值相互写入时，两组 RHS 都读取旧 base；后端不能把第二组
变为读取已经更新的结果缓冲区。

固定的四态规范以逐叶元素选择定义。对完整目标坐标 t：

```text
matchJ(t) = enableJ & AND(L<kJ)(indexJL == tL)
A(J+1)[t] = mux4(matchJ(t), dataJ[t[kJ:]], AJ[t])
```

比较、按位与及 mux4 使用 GRH 既有四态语义，空索引集合的 AND 为真。比较前
零扩展到足以完整表示 index 与目标坐标的共同宽度，bounds 比较还需表示维长度
本身；不把大坐标截到窄 index 的位宽。该公式定义结果，不要求生成逐槽比较。

已知使能为 0 或任一索引确定越界，仅跳过本组，后面的组继续执行。未知控制
不能当作 false；通过 mux4 融合可能受影响的位。确定写入的 data 中 X/Z 原样
传递。无需 unknownIndexPolicy 等模式属性，不能在 op 内自行把未知量清零。

旧 packed shift/mask 的未知索引与 Z 数据传播可能更悲观，因此验收区分两类
证据：TwoState 与旧路线的等价；FourState 与上述新 IR 定义和 FIRRTL 来源
语义的一致性。旧代码不是四态规范的唯一 oracle，不能声称两种表示天然全等。

## 3. 正常 ingest 的改造

`Lowerer::connect` 在 driver 内积累有序更新，在依赖、别名和语义边界允许时
形成一个多组 `kArrayUpdate`。不能对 M 次写反复复制整个 operand 前缀，也
不能每追加一组就物化一次全数组；组记录先线性积累，在需要结果的边界发布。

必须保持：

- FIRRTL 连接顺序、Bundle flips、guard、显式宽度适配、失效策略与初始化覆盖。
- wire/output 的读取仍观察最终连接，不能变成按文本位置读取临时累积值。
- 原已解析的静态下标、混合静态/动态维数和后缀子数组形状，包含 size-one 轴。
- 具名 driver 的 SemanticNode ID、名字与最终 anchor；更新 op 和其 guard 属于
  真实消费 Node，共享实现仍可多 owner，不为每组写新增 Node。

静态 splice 路线可以继续保留；发生动态更新时先完成必要的静态片段组装，再以
其为 base。后续静态/whole 写可按覆盖范围合入同一更新序列，或在必要的快照/
发布边界结束批次。不能仅为合成一个 op 把已有局部依赖重新变成整数组依赖。

寄存器写继续使用 ordered indexed state ports，实际 memory 的端口/事件语义
也不改。**CHIRRTL mport 的组合 data driver 同样经过 connect**，替换 data
merge 时必须保留独立 memoryMask 的 guard、覆盖累计和写入边界。mask 的
局部更新可以独立使用新 op 表达，但需证明与原覆盖语义一致；不能因 data 已
迁移就删除 mask，或把仍存在的 mask 位运算漏报为已消除。

## 4. xmr-resolve 与 hier-flatten

新 op 是普通纯组合计算，不携带跨 Graph 的隐藏 Value ID 或 symbol 地址。
正常 XMR operand 替换和层次复制均须完整保存 indexCounts、组顺序、全部
operand 类型与结果形状。

检查普通 clone、批量列复制、operand remap、链接和实例内联路线，不只检查
一个逐 op 路径。flatten 后 SemanticTree 仍仅含根 Path 及具名叶 Node，
op/anchor 的成员及双向 use-list 一致。重复实例不得共享可变的更新列表。
数组级环只作待分析输入，不能在 range analysis 前将可解的局部假环误报为
真实组合环，也不能无条件忽略真环。

## 5. comb-loop-elim

为新 op 建立按输出区域反推输入的规则：按相反更新顺序查看覆盖关系，再处理
尚未确定覆盖的 base 区域。已知 enable 为真且确定写入的范围不再依赖旧值；
条件覆盖保留旧值依赖；动态地址保守包含可能目标区域及控制/索引依赖。
任一组 data 仍是外部快照，不能误建为读取上一组结果。

range dependency 与实际 IR 重写都必须支持该规则。仅在分析里删除假边、却
保留实际不可调度的循环，不算通过。不能简单把新 op 归为 monolithic 并将
全部输入连到全部输出；那会重现 `a[0]` 与 `a[1]` 之间的假环。

局部解环时优先保持索引更新或局部投影结构，必要的片段重建、更新次序、
完整结果 anchor 和 Node 归属必须一致。沿用 F29 的 SCC 局部 journal 与
事务回滚；对真正不能安全解开的环明确失败，不暗中生成整数组移位路径。
原位实现变化和环外 consumer 变化均通知 Node trace 与公共连接缓存。

## 6. split-static-array 与 Node 演化

新 op 的支持需同时覆盖 producer eligibility、consumer 检查、上游边界递归、
静态 select、state whole-write payload 选择、局部 scaffold 清理，不能只向
canSplitSemanticArray 添加一个 case。

| 情形 | 目标处理 |
| --- | --- |
| 全部目标索引为静态且可证明合法 | 按元素/子数组覆盖顺序投影，可形成局部窄 Mux，再按实际成员替换 Node |
| 存在真正动态写索引 | 默认保留数组及索引更新，作为 optional split 的明确边界，贴近 GSIM |
| 下游/上游依赖未拆数组 | 保留真实具名边界，记录 blocker，不能绕过具名 Node 偷换投影 |
| 必须为消除假环而拆分 | 与 optional split 区分原因，只做有证据的必要重写 |
| 不满足安全条件 | 保持一致前态并记录具体原因，不发布半组 Node |

拆分时列出全部成员坐标，多维成员命名沿用现有合约；父 Node 只有在实际 op
归属和 anchor 迁移完成后退休。新 op 的一组写不是一个新 SemanticNode。
仅实现/成员变化保留 Node ID，真实成员化使用多对多 replace 和原生 lineage。

公共 before/after nodes、connections 保持静态导出能力，evolution 由 pass
现场记录，继续用 before＋evolution 重建完整 after。新增决策需在公开轨迹中
关联到具体 Node，保留具体 reason；存在边界阻断时带 blocker Node ID，必要
时带 update ordinal/axis。不能只把全部 skip 原因汇总到 complete-pass 字符串。
关闭 trace 时不构建 trace 快照，Node 的正常维护保持相同。

## 7. IR 定义、持久化与源码范围

正式实现时更新下列规范，不能只在 F30 项目笔记里定义新 op：

| 文件 | 需更新的内容 |
| --- | --- |
| `wolvrix/docs/grh/grh-ir.md` | operands、indexCounts、完整类型、顺序、四态和多维输入/输出示例 |
| `wolvrix/docs/grh/grh-json-spec.md` | 新 kind、int[] attr 与方言版本/加载规则 |
| `wolvrix/docs/ingest/firrtl-combinational.md` | 组合动态写改为有序更新，快照/最终连接及 mport mask 边界 |
| `wolvrix/docs/transform/comb-loop-elim.md` | 区域依赖与实际局部重写规则 |
| `wolvrix/docs/transform/split-static-array.md` | 静态投影、动态保留、Node 替换和 decision trace |

源码至少审计 core kind/toString/parse、op descriptor、Graph helper、verifier、
store/load、clone/flatten、FIRRTL driver、两个 pass 和 SemanticNodeExchange
依赖提取。新增 kind 保持既有枚举值稳定，统一修正以 kXMRWrite 为内置范围终点
的表/判断，不能让新基础 op 被误当成未注册的扩展方言。

计划保持 JSON **formatVersion=5**，因为容器布局不变；基础方言新增语义升级
为 **grh:3**。新 writer 写出 grh:3，新 loader 可接受合法的 grh:2 旧图，但
grh:2 中不得出现新 op；旧 loader 通过版本或未知 kind 明确拒绝新图。
方言版本声明、版本接受规则及每个 kind 的引入版本一起校验，不能只将
全局 dialectVersion 常量改为 3 而破坏预期兼容。没有新语义被旧图默默承载。

## 8. 实施顺序与完成门

| 步骤 | 工作 | 完成门 | 当前证据 |
| --- | --- | --- | --- |
| F30.1 | core 操作、统一 accessor/builder、verifier、版本与 store/load | 合法/非法分组和完整类型可独立校验，持久化往返保持语义 | 专项通过 |
| F30.2 | FIRRTL driver 线性积累与正常 xmr/flatten | 动态 data 更新不再提前 packed merge，层次复制与 Node/use-list 正确 | 专项及 v7/v9 原始大图链结构校验通过 |
| F30.3 | comb 区域依赖及真实重写 | 静态局部假环仍可解除，真实环不被掩盖，trace/连接缓存正确 | 专项、大图原生独立校验及 v7 完整轨迹重放通过 |
| F30.4 | split 静态投影、动态边界及 Node/decision trace | 正常生产链到 split 完成，父/成员库存与 op 归属一致 | 专项、大图原生独立校验及 v7 完整轨迹重放通过 |
| F30.5 | 原始 SimTop 全图复核、五文件重放与 GSIM 比较 | 全量轨迹可重放，拆分差异重新分类，GSIM 等价阶段性能及适用的超时门通过 | 正确性及 v7 重放/差异分析通过；仍有 976 个未解释差异，正式性能门尚未通过 |

每一步在本文件补实现状态、命令、输入/原生库身份、产物路径和实际结果。
当前尚未完成所有完成门，不预填通过率或仿真提升。

正确性覆盖至少包括：

- 一维/多维、混合 k、k=0、size-one、静态与动态坐标混合。
- 同址覆盖、子数组与元素交错、失效组后继续、恒假组及整数组条件覆盖。
- 超过 32 位的下标、窄下标配大 extent、确定越界、未知 enable/index/data。
- Z 数据保留、data/base 子数组别名、输入快照、不得合并的跨更新依赖。
- FIRRTL 最终连接、初始化覆盖、Bundle 叶字段与 CHIRRTL mport mask。
- 层次多实例复制、静态局部假环、真实组合环、Node 归属及 rollback。

流程、性能及 GSIM 对齐验收使用原始 **SimTop 大图**，从 FIRRTL 正常 ingest，
不从 checkpoint 起跑，不用小图计时替代。build/test/install/脚本执行均经
项目 Makefile；需要新入口时先加 target。日志和产物统一写
`ptmp/firrtl-ingest/F30/`，不写其他临时目录。

split 保留独立硬超时和“两倍即失败”的规则。2026-11-14 用户明确确认：
**超时也改用 GSIM 基准**。新 F30 轮次使用至少三次完整、同输入 GSIM
无 trace 等价阶段耗时的中位数乘二；当前 **2 × 45.904 = 91.808 s**。
上限由冻结参考样本校验后派生，不能通过任意填入一个较大秒数放宽。
此前 F29/早期 F30 按旧 GrhSIM 24.523 s × 2 = **49.046 s** 执行，
其失败记录和旧工具语义保留，不回写成成功。
trace 开关、setup、pass、finish/导出和结构校验分别计时；原始 FIRRTL 与
实际加载库的身份同时记录。正确性校验耗时不混作 pass 执行时间。

以 F29 最近完整导出为比较基线：after 的 GRH Node **9,262,688**，唯一同名
GSIM 候选 **9,218,505（99.523000%）**，GRH 未匹配 **44,183**；其中
**40,606** 个是两侧拆分粒度不同。F30 重新采集实际 Node 与原生 lineage，
报告各类增减；这些旧数字只作基线，不要求新库存数量机械不变，也不以名称
匹配率代替连接、轨迹或功能等价。

首阶段完成后仍需后续工作：让后端以调用方结果缓冲区初始化至多一次，执行
多维下标写并证明 alias 安全；再用同一整机负载测每周期仿真成本。只有完成
该阶段，才能对“避免宽更新是否改善仿真性能”给出实测结论。

## 9. 性能约束：以 GSIM 等价阶段为参考

F30 必须同时通过正确性与性能验收。按照用户最新要求，正式基线改为
**GSIM 从原始 FIRRTL 出发的等价阶段耗时**。GrhSIM 关闭和开启 semantic
trace 的两条路径都与同一个 GSIM 正常无 trace 参考比较；不以开 trace 后
较慢的 GSIM 作为更宽松分母。GrhSIM 改造前的冻结包及全部既有测量保留，
作为性能诊断证据，不再构成正式验收门。

先按真实工作建立阶段映射，再比较耗时：

| 共同阶段 | GrhSIM 计时组成 | GSIM 计时组成 |
| --- | --- | --- |
| 图构造至层次展开 | ingest + xmr-resolve + hier-flatten | readFile + parseFIR + AST2Graph（Init） |
| 数组依赖解环与拆分 | comb-loop-elim + split-static-array | splitArray（包括内部的数组假环处理） |
| 原始输入至拆分结束 | 上述两阶段之和，另列完整墙钟 | 上述两阶段之和，另列完整墙钟 |

GSIM 的 `Init` 将图构造和层次处理合在一起，没有独立 XMR/flatten 计时；
`detectLoop` 位于 split 后，仅作环检测，不能充当 GrhSIM comb 的分母。
GrhSIM 各 pass 细分耗时仍逐项报告，但不虚构一一对应的 GSIM 单 pass 预算。
输入、机器、计时边界及实际参数随实测报告记录，尚未测量的指标不预填通过。
正式 pass 速度对照为三项：prefix、comb+split 的 pass 执行之和、两者合计。
开启 trace 时，现场记录和 commit 属于 pass 执行，完整纳入该预算。两端原生
pass 计时都不含阶段边界的静态 TSV 导出。按照此前公共交换格式的定义，
nodes/connections 是前后静态插桩，evolution 在 pass 内记录并在结束后导出；
因此 trace setup、finish、TSV 导出分别计时，另以相同 GSIM 无 trace 参考
展示完整 comb-split 边界和端到端墙钟的差值/比例，作为插桩成本诊断，不额外
将数 GB 静态输出加入用户要求的 pass 速度门。全部成本保留，独立正确性校验
轮次不用作正式性能样本。

2026-11-14 用户补充：**合理的抖动可以接受**。对每个阶段 P 和相同运行
模式 C，使用预先固定的抖动带，不根据本轮结果临时调门槛：

```text
before = median(wall_time_gsim[equivalent(P)])
after = median(wall_time_grhsim[P,C])
jitter = max(before * 0.03, 0.010 s)

after <= before          : pass
before < after <= before + jitter : within_jitter（允许，单独标明）
after > before + jitter  : regression（失败）
```

其中 wall time 是阶段真实执行耗时，包含正常 Node 维护和本次新增分析、
数据整理及收尾；不能把现场 trace 的新增工作挪到计时区间外。trace setup、
静态导出和独立校验分别记录，并展示完整边界成本。
抖动带为相对 3%、绝对下限 10 ms；
所有差值、比例及实际门槛仍逐项列出，不将 within_jitter 写成实测提速。
任一等价阶段超出抖动带即未通过，不以 Node 数减少或语义改善豁免。

对照执行要求：

- 使用同一原始 SimTop FIRRTL 与 manifest，每轮从正常 ingest 开始，不读
  checkpoint、不克隆中间图。记录输入、源码版本、实际加载原生库的身份。
- 在同一机器及相同 CPU/线程、构建优化、pass 参数、校验/统计开关下交替
  运行 GSIM/GrhSIM，至少取得三组有效数据，保存全部原始耗时和中位数。
  不能只挑最快的一轮或混用不同机器、负载和线程配置的历史数字。
- 默认关闭 trace 的生产路径与开启 semantic trace 的路径分别报告，两者均
  比较同一个 GSIM 无 trace 参考，不能通过关闭原有 Node 维护或功能换取通过。
- trace setup、pass 执行、finish/导出及结构校验分别记录；共同 pass 阶段用于
  正式速度判断，完整边界用于插桩成本诊断，不能隐藏额外导出成本。
- 记录 wall/user/system、峰值 RSS 和实际工作量用于解释结果；阶段 wall
  time 为速度完成门，不能按 op/Node 数归一化后宣称实际变慢的 pass 通过。
- 若环境噪声超过上述固定抖动带，结果记为待复核并补充相同条件的配对测量，
  不临时放宽门槛，也不删除正常完成但较慢的样本。可收紧至零阈值查看严格
  比较；比较工具不允许超过本文的 3% / 10 ms 上限。

split 的独立硬超时由 GSIM 参考中位数乘二派生，当前为 **91.808 s**，
它仅是提前失败上限，不是允许退化到两倍的验收标准。即使未超时，只要等价
阶段中位数超出 GSIM 的固定
抖动带，仍然失败，必须修复后再验收；不得为通过 F30 调高超时或替换较慢基线。

最终在本文件列出每个等价阶段的 GSIM/GrhSIM 中位数、差值、比例、trace 模式、
完整边界耗时与结论。任一项退化或尚未完成对照，F30 不标记性能验收完成。

## 10. 实施与验证记录（进行中）

已加入 core 操作/accessor/builder/验证器、grh:3 持久化、FIRRTL 有序更新、
comb 区域规则、split 静态投影及动态边界。公开 trace 增加现场记录的
Node decision，保留 add/delete/replace 和 lineage 作为库存重放依据。
专项回归、大图独立结构校验与 v7 完整原生轨迹分析已通过；仍在处理性能，
这些证据不代表跨端功能等价或整条流程已完成验收。

改造前原生包已冻结在 `ptmp/firrtl-ingest/F30/baseline/package/`，同时保存
原始源码压缩包、working-tree patch 与 hash，后续重建不会替换基线库。
GrhSIM 性能入口为 `make benchmark_f30_pipeline`，每次从原始 SimTop ingest。
原 `make compare_f30_performance` 比较两版 GrhSIM，仅用于历史诊断；用户更新
要求后，正式报告采用 §9 的 GSIM 参考与共同阶段映射。
源码、原生库、机器、线程、构建、参数与插桩配置缺失时只能记为未完成。
正式共同阶段的中位数使用 §9 的统一规则；原九项 GrhSIM 版本间门禁由此次
GSIM 参考要求替代。原始样本和失败证据均保留。

初始诊断样本保留在 `baseline/initial-no-trace/` 与 `baseline/initial-trace/`：
无 trace 的 split 单次为 **40.85749 s**；有 trace 的 split 达 **49.09486 s**
时被独立 watchdog 终止，超过 **49.046 s**，该样本明确失败。
这些试跑尚不构成三组有效配对，也不是改造后结果；不能据此宣称无性能退化。
所有失败/正常但较慢的样本继续保留，不通过挑选样本改善中位数。

专项验证入口 `make test_f30_array_update` 的最新完整轮次为 **26/26 通过**，
日志在 `ptmp/firrtl-ingest/F30/trace-opt-v9-tests/tests/test.log`。其中包括真实 XMR
操作数解析、普通/全局 flatten × 单/双实例、宽索引、四态、死更新覆盖、动态
payload 独立 Node、state mask blocker、trace 回滚，以及下述 v9 的并行冻结、
稀疏 CSR 和连接索引回归。专项五文件重放结果在
`ptmp/firrtl-ingest/F30/static-replay/`，`replay_exact=true`，6 条成员 lineage。

改造后第一次原始 SimTop 验证（`candidate/pilot-verified/`，无 trace，开结构
校验）完整通过：ingest **41.49704 s**、xmr **0.34703 s**、flatten
**60.93726 s**、comb **19.42772 s**、split **39.25150 s**。
comb/split 的 SemanticTree/use-list 校验均 valid，split 后 `grh.verify` 通过。
结构校验另计：comb **5.40115 s**、split **6.24678 s**，GRH verifier
**11.82497 s**，并纳入对应完整边界总耗时。这是单次正确性试跑，配置与初始
基线不同，不作为配对性能通过依据。

带 trace 的首次大图验证（`candidate/pilot-trace-verified/`）在 split
**49.09505 s** 触发硬超时，失败，未产生完整 split 后态。随后从源 FIRRTL
重新 ingest 采样 `profile-trace-v1/`，仍受同一超时保护；physical rewrites
约 **41.21 s** 已完成，剩余时间耗在原生连接差异提交：涉及 **4,076,632**
个 affected Node、**7,247,266** 条新连接快照、**13,111,868** 条 fallback
读取证据。正在减少连接记录的深拷贝和向量反复增长；不改超时和完成标准，
不将该轮部分产物当作可重放成功。

冻结包 `candidate-v2/package/` 已减少旧连接深拷贝、差异 vector 扩容、Node
map 插入和 lineage 查找开销，专项仍为 26/26 通过。但正式 trace 首对
`paired-v2/trace/{before,after}-1/` 两侧均在约 **49.095 s** 被 watchdog
终止；候选的独立细分诊断 `profile-trace-v2/` 也超时。**硬超时门失败，
相对性能无退化尚未证明**；这些终止时间不是 pass 的实际完成耗时，不能用它们
计算加速比。失败原件继续保留。正在减少原生缓存对不可变连接记录的重复保存，
并复测关闭 trace 的独立生产路径；尚无三组完整配对或最终中位数表。

基线的源码、原生库及原安装构建配置已冻结；依赖附件为事后对仍未修改的
external 工作树补充捕获，并非构建前捕获。因此其 hash 证明附件内容一致，
不追溯声称已证明旧库编译时的全部依赖身份。该证据限制不省略于最终验收。

第三版候选已冻结在 `candidate-v3/package/`：原生连接 cache 引用 session
持有的不可变初始记录和 journal 记录，避免重复保存完整连接；finish 直接
统计 coverage，不再深拷贝并排序全图连接。新增跨事务连接替换/删除、journal
扩容、abort、空提交和 cached/verified coverage 一致性回归，完整专项 26/26
通过；split 另减少只读成员列表复制和每成员的小容器分配。

`paired-v3/no-trace/{before,after}-1/` 已完整返回：split **40.56554 →
39.56220 s**，comb **20.07056 → 21.19361 s**，整段 **161.29736 →
161.16972 s**。这是首对原始数据，comb 单次差值超出 3% 抖动带；仍需补足
配对并按中位数判断，不能仅根据 split 或总耗时宣告通过。

`candidate-v3/trace-verified/` 与随后正常 ingest 的 `profile-trace-v3/`
均触发 split 硬超时，继续记为失败。后者 physical rewrites 约 **39.17 s**
完成，现场连接采集 **2.73 s**、合并 **2.71 s**、差异计算 **0.30 s**；
截止前完成连接删除，停在 cache reserve。perf 同时采到指针 cache rehash
热点，正在消除重复合并移动与本次整表 rehash。前者额外耗时集中于两个改写
区段，改写数量与 v2 一致，尚不能仅据此归因于新增 IR 分析。

性能比较工具的固定抖动带及失败证据专项 **27 项通过**，benchmark/watchdog
专项 **9 项通过**，日志在 `jitter-contract-tests/tests/`。失败报告保留原始
样本，分别列出 `hard_limit=failed` 与 `relative=incomplete`；超时观察值
明确不作为实际完成耗时。基线依赖附件来源也单独记录，不改变现有包的身份。

第四版减少全图 rehash 和重复合并搬移。`paired-v4/no-trace/{before,after}-1/`
首对 split **39.94497 → 37.85572 s**、comb **20.85703 → 19.64525 s**、
整段 **162.60387 → 158.71605 s**；`candidate-v4/trace-verified/` 仍超时，
watchdog 观察值 **49.09152 s**。这些是历史 GrhSIM 版本间样本，不是 GSIM 对照。

第五版将 final commit 的 fallback 索引重建延迟至下一次 begin，若直接 finish
则不做无消费者的重建；全量独立连接校验保持。新增删除唯一 fallback target
后重新 begin 的生命周期回归，专项仍 **26/26 通过**。
`paired-v5/no-trace/{before,after}-1/` 首对原始耗时如下：

| 指标（秒） | 原 GrhSIM | F30 v5 |
| --- | ---: | ---: |
| ingest | 42.31501 | 42.18424 |
| xmr-resolve | 0.35667 | 0.35088 |
| hier-flatten | 58.02492 | 57.70851 |
| comb-loop-elim | 19.44801 | 20.15936 |
| split-static-array | 40.36285 | 37.96598 |
| 整段 | 160.54511 | 158.40558 |

`candidate-v5/trace-verified/` 仍超时，watchdog 观察值 **49.09467 s**。
physical rewrites 约 **38.48 s**，新连接采集 **2.727 s**、合并 **2.206 s**，
截止时走到新增连接提交。事件涉及 **220,306** 个 before Node 和
**1,877,317** 个 after Node，它们是本次变化的增量，不能当作全图库存。
该次未完成 split 的后态，不能用于全量重放或最终对齐率。

第六版已将公开 Node 缓存改为引用稳定初始记录/journal 的稠密指针索引，
减少 Node 查找与复制；四路连接合并缓存两组胜者，删除连接时合并 ID 查询与
删除。专项 **26/26 通过**，包含首个事件改名后的 cached Node 跨 journal
扩容验证，日志在 `trace-opt-v6-tests/tests/test.log`。
`candidate-v6/trace-verified/` 依然被此前硬超时终止，观察值 **49.05774 s**；
physical rewrites 约 **40.83 s**，新连接采集 **3.685 s**、合并 **1.679 s**。
没有实际完成耗时或完整 split 后态，不宣称通过。

用户改用 GSIM 参考后，新增 `make benchmark_f30_gsim` 和
`make compare_f30_gsim`，GSIM 从同一原始 FIRRTL 正常运行至 SplitArray，
始终关闭 trace、dump 与独立统计。冻结实际二进制、源码归档/patch、构建配置
文件和运行库 hash，保留原生阶段日志及单调时钟墙钟；现有二进制与当前源码
一同冻结不追溯证明旧库构建时的源码身份。新工具的契约测试 **7/7 通过**，
历史 `compare_f30_performance` 的版本间比较语义不变。

GSIM 首轮原生程序正常返回，prefix **82.454 s**、split **45.808 s**，但
Python 收尾把字符串传给 Path-only hash 函数，样本按失败保留于
`gsim-reference/run-1/`，不进入正式中位数。已修复并加入真实文件 hash 的
完整成功生命周期回归；加上 flatten profile 标记/正式样本排除，最新轻量
验证为 benchmark **11 项**、GSIM 比较 **9 项**，全部通过，日志位于
`gsim-profile-contract-tests/tests/`。

GSIM 三轮有效全图参考位于 `gsim-reference/run-{2,3,4}/`，均从原始 FIRRTL
开始，无 trace，无 dump，串行运行：

| 指标（秒） | run-2 | run-3 | run-4 | 中位数 |
| --- | ---: | ---: | ---: | ---: |
| readFile + parseFIR + Init | 82.280 | 82.628 | 82.175 | **82.280** |
| splitArray | 45.993 | 45.475 | 45.904 | **45.904** |
| 两阶段合计 | 128.273 | 128.103 | 128.079 | **128.103** |
| 外层完整墙钟 | 132.62290 | 132.47416 | 132.44391 | **132.47416** |

这些是新的参考数据，尚未宣称 GrhSIM 达标。第七版候选复用 SemanticTree
名称索引，移除 flatten 的重复完整名称表；comb 仅在实际改图后重建全图
CSR/Tarjan，并跳过无自环单节点 SCC 的临时分配。最终环检查仍对应实际新图，
不取消校验或移动计时边界。名称冲突回滚与迭代上限/真假环/no-fix 回归均已
补充，专项 **26/26 通过**，日志为 `trace-opt-v7-tests/tests/test.log`。
该轮专项之后采集的大图耗时、全量 trace 后态及 GSIM 比较结果见下文。

第七版首轮 profile（`candidate-v7/profile-prefix/`，诊断配置）完成：ingest
**41.81802 s**、xmr **0.34541 s**、flatten **53.57300 s**、comb
**10.36365 s**、split **37.72582 s**，完整边界 **143.86184 s**。
comb+split 完整边界 **48.11970 s**；相对 GSIM split 中位数仍慢约 4.8%，
prefix **95.73642 s** 仍高于 GSIM **82.280 s**。该轮显式开启 flatten
profile，不进入正式中位数。profile 定位串行 source freeze **15.401 s**，
正在复用现有图级安全并行机制改善该开销。

`candidate-v7/trace-verified/` 已从原始 FIRRTL 完整通过：comb **11.97924 s**、
split **47.96889 s**，首次在原 **49.046 s** 硬超时内返回；两阶段的
SemanticTree/use-list 校验 valid，split 后 `grh.verify` 通过。静态插桩成本
单列：comb setup/finish **20.63440 / 15.92208 s**，split setup/finish
**20.41902 / 32.00617 s**；独立结构校验 **5.28281 / 6.30082 s**，
GRH verifier **11.60458 s**。原生五文件完整生成，split bundle 约 **7.5 GB**。
该轮开启独立正确性校验，不用作正式性能样本；完整重放及 GSIM 比较已完成，
证据和限制如下。

### v7 全图原生轨迹与跨端库存比较（已完成）

全图重放由 `make analyze_f30_alignment` 执行，输入为 v7 原生 comb/split
两套五文件与 F29 已导出的 GSIM split 原生五文件，产物为 `alignment-v7/`。
先独立验证两套 GRH 和 GSIM 的 before＋evolution→after，再核对
comb.after→split.before 的 Node ID 与完整连接连续性，最后报告名称候选与
现场 decision/lineage 支持的差异。分母是全部 GRH SemanticTree 叶 Node；
名称唯一匹配只表示存在候选。GSIM 旧轨迹没有 Node decision，不能补称其有
完整的 retain 原因证据；GRH 的 dependency 覆盖仍含 unresolved 项，也不
将重放正确或高名称匹配率写成功能等价。

`alignment-v7/summary.json` 已为 **complete=true**。GRH comb、GRH split、
GSIM split 三套原生 before＋evolution→after 均 **complete=true、
replay_exact=true**；GRH comb.after→split.before 的 **7,671,189 Node /
12,986,525 connection** 连续性精确一致。GRH comb 有 **253** 次 replace，
理由为 `false_loop_slice_retarget`，Node 数不变，connection 从
**12,981,915** 变为 **12,986,525**。GRH split 有 **1,876,842** 条成员
lineage，GSIM split 有 **2,051,495** 条；两侧均使用各自原生记录，未从
after 倒造演化。

| 比较点 | GRH 全部叶 Node | GSIM 原生 Node | 唯一同名候选 | GRH 未匹配 | 占 GRH Node 的候选比例 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GRH comb 前 / GSIM Init | 7,671,189 | 7,829,556 | 7,668,660 | 2,529 | 99.96703249% |
| GRH comb 后、split 前 / GSIM Init | 7,671,189 | 7,829,556 | 7,668,660 | 2,529 | 99.96703249% |
| GRH split 后 / GSIM SplitArray | **9,328,200** | **9,635,014** | **9,297,125** | **31,075** | **99.66687035%** |

名称键为 `'.'.join(name_path_json tokens)`，原 token 不再拆分；同一规范
路径必须在两端各出现一次。分母包含该阶段全部 GRH SemanticTree 叶 Node，
没有按来源、辅助 Node 或是否好匹配过滤。GSIM split 后未匹配为 **337,889**。
以上是**唯一名称候选**，不表示逐 op 对应或功能等价。

GRH split 后全部 **31,075** 个未匹配 Node 已导出至
`alignment-v7/unmatched-reasons.tsv`，以下五类互斥且合计完整；百分比的分母
为这 **31,075** 个 Node：

| 分类 | 原生证据含义 | Node 数 | 占未匹配比例 |
| --- | --- | ---: | ---: |
| `gsim_split_grh_retained` | 可从共同前态追到 GSIM 的存活拆分成员，GRH 保留父 Node | **26,263** | **84.515%** |
| `grh_retained_by_native_decision` | GRH 有原生 retain 决策，尚无更具体的双端 lineage 分类 | **1,553** | **4.998%** |
| `grh_split_gsim_retained` | GRH 已产生成员，GSIM 保留共同前态 Node | **1,238** | **3.984%** |
| `split_member_name_difference` | 原生成员坐标有对应物，名称未形成唯一候选 | **1,045** | **3.363%** |
| `unexplained_native_difference` | 当前原生记录仅支持库存差异，原因尚未解释 | **976** | **3.141%** |
| 合计 |  | **31,075** | **100%** |

公开 `decisions.tsv` 保留 **411,857** 条原生决策，不去掉同一 Node 的重复
记录。replace 为 `state_array_split` **17,048** 条和 `static_array_split`
**202,786** 条；retain 为 `dynamic_consumer_index` **6,397**、
`dynamic_state_index` **7,975**、`dynamic_update_index` **456**、
`register_writer_boundary` **678**、`unsplit_array_input` **14,053**、
`unsplit_state_payload` **4,129**、`unsplit_upstream_array` **39,797**、
`unsupported_array_producer` **116,361**、`unsupported_state_family` **2,177**。

未匹配 Node 及其祖先的决策理由共出现 **53,738** 次：
`unsplit_upstream_array` **29,424**、`unsplit_array_input` **11,606**、
`unsupported_array_producer` **5,540**、`unsplit_state_payload` **2,615**、
`static_array_split` **2,286**、`unsupported_state_family` **1,545**、
`dynamic_consumer_index` **556**、`dynamic_state_index` **166**。
这里计的是出现次数：一个 Node 可带多条决定，共同祖先也会在多个未匹配后代
中重复出现，不能把理由条数当作不同 Node 数或相加成差异分类。
`dynamic_update_index` 未出现在该未匹配集合的祖先记录中；这只描述当前
库存/记录结果，不能推导动态更新的跨端功能等价。

| split 后公开连接指标 | GRH | GSIM |
| --- | ---: | ---: |
| 原始 connection 行数 | 15,837,478 | 15,568,445 |
| resolved 行数 | 15,318,589 | 15,568,444 |
| unresolved 行数 | **518,889**（dependency） | **1**（external binding） |
| 两端点均有唯一候选的不同 resolved `(source_path,target_path,kind)` 元组 | 14,393,879 | 14,469,145 |

两端共同的上述 resolved 元组为 **13,508,503**。原始行数、resolved 行数和
去重后的可比较元组是不同分母，不混用。**各侧 replay exact 只证明各自轨迹
能产生各自后态**，不证明公共连接已全部解析；GSIM 轨迹缺少 Node decision，
不能声称已证明其全部保留原因。双端演化整体一致仍未验证，报告保留
**`evolution_alignment_verified=false`**，跨端功能等价也未证明。

分析收尾曾被 SQLite 的递归祖先查询拖慢：旧计划只使用
`lineage_child(engine=?)` 前缀，每个 Node 重扫 GRH lineage。改用
`ancestors CROSS JOIN lineage` 后完整使用 `(engine,child)` 索引；同时流读
已完成的 `after.unmatched.tsv`，避免重做全图名称 join，增加有限大小缓存。
轻量契约 **8/8 通过**，只读 EXPLAIN 证据为
`tests/alignment-query-plans.json`。父进程明确停止旧 writer 后，以
`make resume_f30_alignment_export` 恢复解释导出：原数据库只读，复用既有
精确重放与比较，重查原生首尾边界、已导入 trace 索引计数及完整 TSV footer；
保留 `summary.before-resume-1.json`、原日志和
`unmatched-reasons.interrupted-1.pending`。恢复预检 **3.531 s**、解释导出
**8.989 s**，总计约 **12.52 s**。这是同次分析的恢复，未重新 hash/重放全部
原始文件，不作为 fresh replay 证明，也不是 native pass 的性能数据。

2026-11-14 用户确认硬超时也使用 GSIM 参考，后续测量采用上述三轮冻结
参考导出的 **91.808 s** 上限；固定 3% / 10 ms 的正式速度门不变。早期
v1–v6 在 **49.046 s** 上限下的 watchdog 记录全部保留；v7 在旧上限内
完成也是独立事实，不以新上限替换其历史结果。

### v9 大图正确性与性能状态

**第九版候选已实现并完成专项验证，正式性能门尚未通过。** 在 v7 已定位的
热点上补充以下生产流程优化，不改变 Node 维护、验证要求或计时边界：

| 路径 | v9 已实现改动 | 保持的语义与专项覆盖 |
| --- | --- | --- |
| hier-flatten source freeze | 复用已有 `Design::parallelGraphMutation()`，并行冻结相互独立的源 Graph；默认 worker 数不超过 10，沿用原生 `-threads=N` 参数控制 | 源目录与具名端口资格处理保持串行，全部 worker join 后才开始内联；普通/全局模式、1/4 线程、成功/失败源图覆盖成员重定位、确定诊断及顶层回滚 |
| comb-loop-elim CSR | 将 endpoint 扫描与度数统计融合，构建依赖 CSR 只扫描两次 op；填边时直接复用 offsets 为 cursor，再逆向恢复行首 | 保留所有端点、边界过滤和结果 ValueId；空图、稀疏槽位、已删除尾槽、最高槽出边及真环回归覆盖行首与末端 sentinel；v7 的按实际改图重分析仍保留 |
| SemanticConnection 采集与提交 | 公共连接按 target 优先排序；每个 target 的最后一次 emit 后才排序本段，连续递增 target 和并行连续分片直接拼接，移除全图排序与四路归并 | target 内哈希去重仍比较完整连接；乱序/重复 target 保留全局 sort/unique；commitFinal 后重建的 incoming 桶排序，未变化连接保留原 connection ID；新增目标选择及跨事务索引重建回归 |

统一专项为 **26/26 通过**，日志为
`ptmp/firrtl-ingest/F30/trace-opt-v9-tests/tests/test.log`；安装日志为
`ptmp/firrtl-ingest/F30/trace-opt-v9-install.log`，候选源码、依赖、构建配置与
实际原生包冻结在 `ptmp/firrtl-ingest/F30/candidate-v9/package/`。
这些是实现与专项正确性证据，不是优化收益或 GSIM 等价阶段速度通过的证据。

GSIM 派生硬超时已接入 `make benchmark_f30_pipeline`：通过
`F30_BENCH_GSIM_REFERENCE` 传入至少三个 GSIM `summary.json` 路径，例如
`gsim-reference/run-{2,3,4}/summary.json` 对应的三个完整路径。
工具校验冻结参考的输入、机器、CPU affinity、线程配置、原生版本及文件 hash，
要求参考样本完整、按时间顺序串行且早于本次 GrhSIM 运行，再由原生
`splitArray` 耗时中位数派生 **91.808 s** 上限；报告保存参考来源与派生证据。
相关轻量契约测试为 **15 + 27 + 11 = 53/53 通过**，包含拒绝硬超时验证
未通过的样本，不替代全图测量。
日志为 `ptmp/firrtl-ingest/F30/tests/` 下的 `gsim-contract.log`、
`performance-contract.log` 与 `benchmark-contract.log`。
固定 **3% / 10 ms** 的正式速度门保持不变。

`candidate-v9/trace-verified/` 已从原始 SimTop FIRRTL 跑到 split 并正常返回，
开 trace 及独立正确性校验：comb/split 的 SemanticTree/use-list 校验 valid，
split 后 `grh.verify` 通过。原生导出的库存计数与 v7 相同，split 后为
**9,328,200 Node / 15,837,478 connection**；这不是 v9 的离线轨迹重放，
也不扩展为两个版本逐行或功能一致的证明。

| v9 本轮观测（秒） | 耗时 |
| --- | ---: |
| ingest | 65.95741 |
| hier-flatten | 75.34550 |
| comb-loop-elim | 12.12675 |
| split-static-array | 69.77360 |
| 整段完整边界 | 325.69352 |

该轮开启独立校验，初段与旧 SQL 分析重叠，且观测到严重内核内存压力；
**不是正式性能样本**，原始日志及 summary 保留在上述目录。不能用这轮数据
宣称 v9 变慢或速度门通过，也不能删除它或改写为静默运行。

`candidate-v9/formal-no-trace-1/` 随后在没有其他重型任务的条件下串行完成：
ingest **43.23728 s**、xmr **0.35683 s**、flatten **94.70371 s**、comb
**10.60191 s**、split **40.65321 s**，整段 **189.59301 s**。
prefix **138.29782 s**，comb+split pass **51.25512 s**；均高于 GSIM
参考及固定抖动带，**本轮性能未达标**。split 未超过新硬上限不能替代速度门。
这是首个正式样本，保留原数据及运行前后内存/PSI/vmstat 快照，不据单样本
填报三轮中位数，也不将明显慢的正常完成样本排除。

独立诊断 `candidate-v9/profile-prefix/` 从原始 FIRRTL 起跑，显式开启
flatten profile，正式比较工具拒绝该样本：freeze **5.599 s**，但 flatten
整体 **99.83848 s**，user/system **65.70129 / 60.22088 s**。相比 v7，
并行 freeze 本身缩短，后续内联仍出现显著内核内存整理成本；不能把这一生产
路径上的退化简单归为外部噪声。当前改进方向是使用现有 bulk 导入直接读取
source 原始列，移除不必要的完整 source compact，保留公共 freeze/compact
语义及所有 Node/连接维护。该后续改造尚未验收。

新增显式 `F30_BENCH_PROFILE_SPLIT=1` 仅采样 split 内 CPU 热点，保持 GSIM
派生的硬上限，正式比较同样拒绝 profile 样本；相关 GSIM/benchmark 契约
**16 + 11 项通过**。`alignment-v7/` 正确性/差异分析已完成，F30 仍因
正式性能验收未完成而保持进行中。

v9 的完整 split 诊断已返回，原件位于 `candidate-v9/profile-trace/`：
split pass **64.78613 s**，其中 user **43.35037 s**、system **18.53530 s**。
`trace/profile/report-v9.txt` 的采样事件为 `cpu-clock:u`，约 **43.27 s**
用户 CPU、**0 lost samples**。主要 self 热点包括 boundary 反向索引新增
**3.66%**、`removeValueUser` **3.22%**、`observeSemanticErase`
**2.87%**、新增 boundary **2.01%**、反向索引删除 **1.91%**。
这些比例描述用户 CPU，不能直接当作 wall time 或可获得的提速；索引维护、
Node 通知和现场 trace 都必须保留。该 profile 是独立诊断，不能替换或排除
上面的正式无 trace 失败样本。

### v10 原始来源列导入与稀疏状态引用收集（专项通过，大图失败）

v10 沿用现有 ingest 和 bulk 内联流程，直接读取 source 的原始列；移除为
flatten 预先完整 compact source 的步骤，没有新增 ingest 前端或另一条
仅用于 F30 计时的生产路线。实现与专项覆盖如下：

| 路径 | 改动 | 保持的契约 |
| --- | --- | --- |
| hier-flatten | 直接导入带删除空槽的来源列；按最大 live slot 准备重定位容量；canonical named-port 遍历使用局部端口视图 | 来源 ID、端口次序、属性、SrcLoc 与 Node 成员不因准备工作重编号；positional ABI、失败诊断与顶层回滚保留 |
| 生产 `GrhPreFlatten` prefix | 移除来源 compact 资格的全目录扫描和尾链的隐式 compact，真实 `readSources`/specialization 共用此生产执行路径 | 正常变换仍可增删实体；公共 `Graph::compact()`、`freeze()`、`compactForFlatten()`、一次性 receipt 及 PassManager 显式 opt-in 语义不变 |
| split `collectFamilies` | 一次全图 op 扫描收集 shaped register 声明及真正带 `regSymbol` 的稀疏引用，再只遍历引用表解析 family | 引用可位于声明之前，保持引用顺序、动态下标/unsupported 判定、state family 与 Node/trace 维护 |
| DPI boundary | 合并已有 DPI import 时补齐 source→target operation 映射 | 延后属性及操作符引用解析到实际合并目标，避免丢失边界符号映射，并增加对应回归 |

`make test_f30_array_update` 的完整专项已 **27/27 通过**，日志为
`ptmp/firrtl-ingest/F30/raw-source-v10-final-tests/tests/test.log`。
新增第 27 项 `firrtl-prefix-no-compaction` 通过真实生产 prefix 验证
1/4 线程下保留 source holes、完整 Value/Op ID、source/top 端口次序及 use-list；
既有 `transform-pass-manager` 还验证 `compactAtEnd` ×
`prepareFlattenSources` 的四种组合，显式 compact 仍完成重编号、端口排序
和一次性 receipt，单独 opt-in 不会暗中 compact。

flatten 专项覆盖完整 JSON、来源 ID/端口/SrcLoc/Node、删除空槽、非法引用，
以及普通/全局计划和 1/4 线程。非零 generation 的失效引用仍走既有失败
路线，不将它放宽为合法 source ID。DPI import 合并映射也已纳入回归。

首轮完整专项为 **26/27**，失败日志继续保留在
`raw-source-v10-tests/tests/test.log`；随后定位的两处 source 快照 fixture
问题及中间失败日志也保留：一处未先初始化派生 retention metadata，另一处
为快照整个设计而 clone 了故意非法的 sibling。fixture 现先建立派生状态，
并仅将待核对的目标 source 导入快照；完整 source 内容相等及非法 sibling
的失败断言继续保留，没有删除负例或降低比较要求。中间记录位于
`raw-source-v10-source-fix/`、`raw-source-v10-source-diff/` 和
`raw-source-v10-source-fix2/`。

实际原生包已冻结在 `candidate-v10/package/`。首个原始 SimTop 大图样本
`candidate-v10/formal-no-trace-1/` 完成 ingest **42.29414 s**、xmr
**0.36071 s**，随后在 hier-flatten 期间被 `systemd-oomd` 终止，**本轮失败**，
不存在 flatten/split 完成时间或性能通过结论。27/27 不能替代大图验收。

系统日志记录本地时间 **2026-11-14 16:02:54 +0800**，所处 scope charge
**164.4G**，用户服务内存压力 **66.78% > 50%** 持续超过 **20 s** 后整组
被杀。scope 数值包含文件缓存，**不是图或 benchmark 进程的 RSS**；本轮
仅有 ingest 阶段 maxRSS **53,077,488 KiB**，没有 flatten 的峰值证据。
kernel OOM kill 计数没有增加，实际终止者由 systemd-oomd journal 证实。
日志及外部终止说明分别保留在 `candidate-v10/` 下
`formal-no-trace-1.systemd-oomd.log`、`formal-no-trace-1.termination.json`。
原 summary 停在 `running` 是被杀后未能收尾的结果，不能解释为仍在运行或
有效样本，不回写成完成。

代码审计发现 raw-source 的两处放大路径：`prepareBlockImport` 仍导入整个
历史 attr/list/srcLoc 池（包括已删除或覆盖记录），global port 映射已存在时
仍为递归层分配完整 local ValueId 表。正在改为仅导入活引用和消除冗余映射；
实际各项内存贡献尚未量测，不能将代码推断写成 RSS 归因。公共 compact/
freeze 语义及全部 Node/连接维护继续保持。

重试前仅对已完成 `alignment-v7/` 的常规 SQLite/TSV 文件调用
`POSIX_FADV_DONTNEED`，保留全部文件与内容，不修改系统设置。操作清单和
前后内存/PSI/vmstat 记录为 `resource-cache-preparation/report.json`；该操作
仅尝试释放干净文件缓存，不保证全部释放，也不作为 pass 性能数据。
后续先运行带独立资源监控的诊断（96 GiB RSS，或 PSI avg10 达 25% 持续
8 s 时先落盘再主动终止），不绕过 systemd-oomd；诊断样本禁止进入正式速度门。
v9 正式失败及全部历史样本保持原样，F30 尚未验收。

### 诊断资源保护：独立 RSS 与 scope/用户服务 PSI

`make benchmark_f30_pipeline` 新增 `F30_BENCH_RESOURCE_GUARD=1`。它由外层
supervisor 启动私有 session/process group 中的 benchmark child，独立进程采样，
不依赖 native pass 释放 GIL。仍使用原始 FIRRTL 和原生产流程，不修改系统配置、
systemd-oomd 或 GSIM 派生的 split 硬超时 **91.808 s**。

默认每 **0.25 s** 记录 benchmark 自身 PID 的 `VmRSS`、`RssAnon`、`RssFile`、
`RssShmem`、`VmSwap`、`VmHWM`，单位统一为 bytes；另行记录 child 所处 scope
的 `memory.current`、`memory.stat`、`memory.swap.current`。这些 cgroup 数值包含
缓存和同 scope 其他进程，不能当作 child RSS。压力分别读取 child scope 与其
`user@*.service` 祖先的 `memory.pressure`，以覆盖此前 oomd 使用的用户服务
聚合压力来源；不将祖先的 charge 混入 PID 内存数字。

进程 RSS **≥ 96 GiB**，或任一可读压力源的 some/full `avg10` 最大值
**≥ 25% 连续 8 s**，即将本次运行标记为失败并终止私有 child process group。
`guard.json` 写明触发原因、最新 phase/样本；压力触发还记录具体 cgroup path、
some/full、avg10、持续起点与时长。正常路径先原子写入触发证据，再 SIGTERM，
必要时 SIGKILL；磁盘满等写入异常仍保证尝试终止和回收，不因二次持久化失败
放任 child 继续运行。child 自行成功/失败退出也清理本组遗留辅助进程，不向
调用者的 tmux scope 发信号。

完整采样流为 `resources.samples.jsonl`，原 `summary.json` 保留已返回阶段和
pass 行，资源终止时附加明确的 `termination` 并标记失败，不把终止前等待时间补写为
pass 完成耗时。prefix 在 native 调用前发布活动阶段，transform 根据已返回的
`timing.json` pass 行识别下一阶段。单一 PSI 源不可读时继续使用其余可读源；
没有 cgroup 时明确降级为 PID RSS 保护，PID RSS 不可读且 child 仍存活则失败
并终止。采样有间隔，RSS 可能越过阈值；这不是硬内存上限，也不能保证阻止外部
oomd 或其他系统终止。

可配置项为 `F30_BENCH_RESOURCE_RSS_GIB`（96）、
`F30_BENCH_RESOURCE_PSI_PERCENT`（25）、
`F30_BENCH_RESOURCE_PSI_SECONDS`（8）和
`F30_BENCH_RESOURCE_INTERVAL_S`（0.25）。无论 child 是否正常完成，带 guard 的
运行均为诊断样本，共用 `inspect_sample` 的 GSIM/旧配对性能入口均明确拒收。
关闭 guard 后才可收集正式速度样本，不能将资源保护通过等同于性能门通过。

轻量 Make 验证为 **69/69**：资源保护 **13** 项、benchmark **12** 项、GSIM
合约 **17** 项、旧性能合约 **27** 项。覆盖 GIL 被 native 调用持有时仍能停止、
真实 RSS 超限、持续/瞬态压力、祖先压力及单源缺失退化、外部信号、磁盘写入
失败的无条件清理、正常/失败退出的遗留 helper 清理，以及诊断样本的正式拒收。
日志在 `ptmp/firrtl-ingest/F30/resource-guard-final/tests/` 下的
`resource-guard-contract.log`、`benchmark-contract.log`、`gsim-contract.log` 和
`performance-contract.log`。这些是监控及证据合约测试，没有执行 native 全图，
不构成新候选的内存或速度结论。

### v11 活跃 payload 导入（原生大图已完成，正式验收进行中）

raw source 现在只准备活 op 引用的 AttributeRecord，历史记录只保留 4 B/ID
重定位索引；完整引用的 list 池保留共享快路，其他池只复制实际引用切片并
复用相同切片，SrcLoc 延迟到实际复制时导入。全局 port 映射启用时，不再
为递归层重复分配完整 local ValueId 表。公开 compact/freeze 和 Node/连接
维护继续保留。`liveBlockImportPayload` 覆盖 raw/compact、serial/batched、
全部属性 variant、空列表、别名、历史记录及 source 销毁后的所有权。

`make test_f30_array_update` **27/27 通过**，记录在
`ptmp/firrtl-ingest/F30/live-payload-v11-tests/tests/test.log`。已安装并冻结
`candidate-v11/package/`。`candidate-v11/guarded-no-trace-1/` 从原始 SimTop
FIRRTL 完成了全部原生阶段，没有触发 RSS/PSI 阈值，也没有再次被 oomd 杀掉：

| v11 诊断（秒） | 耗时 |
| --- | ---: |
| ingest | 42.22466 |
| xmr-resolve | 0.35582 |
| hier-flatten | 43.05741 |
| comb-loop-elim | 9.88452 |
| split-static-array | 37.88824 |
| 原生整段边界 | 133.49820 |

进程累计 maxRSS **80,868,356 KiB，约 77.12 GiB**，与采样的 VmHWM 一致。
本轮启用 flatten profile 和外部 guard，禁止进入正式速度比较；也没有开启
独立全图正确性校验。profile 的全局 slots/live/holes 分别为
**34,274,101 / 34,263,308 / 0**，所以不能将本图问题归因为 global ID holes。
这是修复后的一轮观测，v10 缺失 flatten RSS，不能计算修复前后 RSS 降幅。

本轮 child 正常返回 **0**，但 guard 在自然退出时读到缺少 VmRSS 的 `/proc`
状态，误标 `monitor_error`，将 native 已 passed 的 summary 标为 failed。
原始 `guard.json`、`summary.json` 和采样保留，不回写旧证据为成功。
监控现仅对缺少 VmRSS 或进程文件消失的情况有界等待 100 ms，取得真实
退出码后才按成功/失败退出分类；仍活着且读不到 RSS 的 child 保持失败并
终止。新增退出 0/非零及活进程缺 RSS 回归，轻量 **72/72 通过**，日志为
`resource-guard-exit-race/tests/`。需要区分原生运行完成与监控收尾失败。

随后串行的 `candidate-v11/formal-no-trace-1/` 关闭 guard/profile/独立校验，
从原始 FIRRTL 正常完成：ingest **42.37661 s**、xmr **0.34978 s**、flatten
**41.66088 s**、comb **10.16250 s**、split **37.93235 s**，整段边界
**132.55309 s**，maxRSS **83,261,836 KiB（79.40 GiB）**。prefix
**84.38728 s** 位于固定 GSIM 抖动带内，但 comb+split **48.09485 s** 和
native sum **132.48213 s** 分别高于 **47.28112 / 131.94609 s** 上限。
这是单个正式样本，完整保留；不能以三轮中位数或性能通过报告。

`candidate-v11/guarded-trace-verify-1/` 随后完成 trace + 独立全图校验：
ingest **42.57827 s**、xmr **0.35903 s**、flatten **40.62576 s**，comb/split
pass **11.50720 / 40.94432 s**。两次 SemanticTree/use-list 校验 valid，
最终 `grh.verify` passed，原生 child 返回 0，累计 maxRSS
**84,564,608 KiB（80.65 GiB）**。原生整段边界 **234.17639 s** 包含静态
导出及独立校验；setup、finish、校验和 pass 计时仍分别保留，不能将这轮
作为正式性能样本或离线 replay 证明。

该轮同样未达到 RSS/PSI 阈值或被 oomd 杀掉，但 **100 ms** 的退出收割仍
短于真实大进程的内核收尾，guard 再次将 native passed/退出 0 误标为
`monitor_error`。旧证据继续保留；现已将仅缺 RSS/进程文件消失时的真实
退出码收割上限改用已有 **2 s** grace，超时仍活的进程继续失败并终止。
新增真实 child 在监控握手后 **250 ms** 才退出的回归，分别验证退出 0、
非零和进程文件消失；活 child 缺 RSS 时等满默认 2 s 仍失败并终止。
相关轻量 **73/73 通过**（17 guard + 12 benchmark + 17 GSIM + 27 performance），
日志在 `resource-guard-exit-grace/tests/`。该最终收尾修复仅完成轻量回归，
没有再以大图验证，不将旧诊断的失败状态改写为成功。
F30 尚未通过正式验收。

### v11 正式性能验收（2026-11-14，原定阈值未通过；用户接受实测性能）

**最新决定（2026-11-14）：用户已确认当前性能可以接受，保持 v11 实现，
暂不继续本轮性能优化。** 原话：“我觉得这个性能可以接受，先这样吧，记录下来”。
本次人工接受覆盖下述无 trace 和开 trace 的 ingest→split-static-array
实测结果，包括单独列出的静态导出成本。用户接受记录在
`acceptance-v11-20261114/user-decision.json`。

原定 `max(3%, 10 ms)` 自动性能门的失败结果及全部实测数据继续保留；本次
接受不修改基准、阈值、比较工具或原始报告，也不设定未来版本的新默认
容差。F30 其他对齐/功能等价及后端仿真性能事项沿用各自状态。

本轮保持 `candidate-v11/package/` 不变，核心库 SHA256 为
`0f776bba843d727d4cb273b4c26a3cbdd1655a994ae03f2fa9fbebfa8900b560`。
开始测量前登记 `acceptance-v11-20261114/plan.json`，每次从原始 SimTop FIRRTL
导入，按 no-trace-1 → trace-1 → no-trace-2 → trace-2 → no-trace-3 → trace-3
串行完成。未读取 checkpoint、clone 或使用小图；未并行构建、SQL 分析或
其他大图。verify/statistics/flatten profile/split profile/resource guard
全部关闭，额外 profile/debug/marker 及线程环境开关未设置，记录在
`instrumentation.env`。六轮全部正常完成，没有 OOM 或 split 超时。

沿用冻结 GSIM no-trace `gsim-reference/run-{2,3,4}/summary.json`，其 prefix、
SplitArray、两者之和的中位数分别为 **82.280 / 45.904 / 128.103 s**。
这批未重新运行 GSIM，不能描述为同期 GSIM/GRH 交替测量。固定抖动带仍是
**max(3%, 10 ms)**，split 独立硬上限仍是 **91.808 s**；没有调整分母、
计时边界或失败标准。

先前 `candidate-v11/formal-no-trace-1/` 是同冻结版本的有效正式样本，主
no-trace 比较完整纳入该样本及本次新三轮，共四轮。另保留新三轮独立比较；
trace 纳入本次全部三轮。未剔除慢样本或补跑替换样本。正式比较工具验证
来源身份、配置、计时日志、GSIM 派生超时和执行区间，三份报告均
`complete=true, errors=[], hard_limit=passed, status=regressed`。

| 正式指标（每轮合计后取中位数，秒） | GSIM 参考 | 允许上限 | no-trace（旧1＋新3） | trace（新3） |
| --- | ---: | ---: | ---: | ---: |
| ingest＋xmr＋flatten | 82.28000 | 84.74840 | 84.10051，抖动内 | 83.93481，抖动内 |
| comb＋split pass | 45.90400 | 47.28112 | 48.31358，失败 | 53.39927，失败 |
| prefix＋comb＋split pass | 128.10300 | 131.94609 | 132.18271，失败 | 136.81862，失败 |

no-trace 的 comb＋split 比 GSIM 慢 **5.249%**，超允许上限 **1.03246 s**；
trace 慢 **16.328%**，超允许上限 **6.11815 s**。两种模式的总和分别比
GSIM 慢 **3.185% / 6.804%**。因此 **v11 未通过原定自动性能门**；随后
用户接受本轮实测性能，按本节开头的最新决定结束本轮性能优化。
此次仅做验收与结果记录，未修改被测原生实现。

新三轮 no-trace 独立结果为 prefix **83.81374 s**、comb＋split
**48.53232 s**、native 总和 **131.88329 s**：prefix 和总和处于抖动内，
comb＋split 仍失败。旧样本是否纳入会影响总和单项判定，不改变本轮总体
未通过原定自动性能门的结论；两组结果均保留。

| 新样本 | prefix（秒） | comb pass（秒） | split pass（秒） | comb＋split（秒） | 完整边界（秒） | maxRSS（GiB） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| no-trace-1 | 84.60223 | 9.78355 | 39.30191 | 49.08546 | 133.76236 | 74.29 |
| trace-1 | 83.93481 | 11.73115 | 41.15266 | 52.88381 | 201.90869 | 78.58 |
| no-trace-2 | 83.35097 | 10.20790 | 38.32441 | 48.53232 | 131.91982 | 76.81 |
| trace-2 | 82.96387 | 11.52477 | 41.87450 | 53.39927 | 200.77637 | 82.63 |
| no-trace-3 | 83.81374 | 9.88682 | 37.15042 | 47.03725 | 130.89165 | 76.80 |
| trace-3 | 83.97018 | 11.36641 | 42.19566 | 53.56207 | 203.50467 | 79.68 |

trace 的现场记录和提交包含在 pass_s 内；静态 TSV setup/finish/export
单独计时，未将生产 pass 工作移到计时外。trace 每轮额外静态导出约
**64.4–65.9 s**，comb＋split 完整边界中位数 **117.97068 s**，从 ingest
到 split 完整边界中位数 **201.90869 s**。no-trace 主集合完整边界中位数
**132.23645 s**，GSIM supervisor 完整边界中位数 **132.47416 s**；两端
该诊断边界的进程启动/退出范围不同，不能用此项替代正式原生计时门。
本次新样本峰值 RSS **82.63 GiB**，是进程 maxRSS，不是含缓存的 scope charge。

全部产物位于 `ptmp/firrtl-ingest/F30/acceptance-v11-20261114/`：

- `acceptance.json`：最终验收结果与正式/敏感性指标。
- `runs.tsv`：旧有效样本和新六轮的逐轮耗时、RSS。
- `comparison-no-trace-all/`：主 no-trace 四轮与 GSIM 的 JSON/TSV 比较。
- `comparison-no-trace-new/`：新三轮 no-trace 敏感性比较。
- `comparison-trace/`：trace 三轮正式及完整边界比较。
- 每个 `no-trace-{1,2,3}/`、`trace-{1,2,3}/` 保留原始 summary、计时日志和
  原生导出；比较工具的非零返回表示完整验收失败，没有将其当作工具故障。

该性能验收不扩展为跨端功能等价或 v11 离线演化重放证明，后续性能改进须
保持既有 Node/连接/trace 语义，并针对新的冻结版本重新验收。

### 当前实现复核（2026-11-14，ingest→split 已接通）

按用户要求再次检查当前工作区实现，未修改原生生产代码，也未继续性能优化。
本次通过 `make test_f30_array_update` 重跑专项，**27/27 通过**；日志为
`ptmp/firrtl-ingest/F30/verify-array-update-current-20261114/tests/test.log`。
core 定义/构造/校验/持久化、FIRRTL lowering、XMR、flatten、comb、split、
verify 和阶段外拒绝路径共 **14 个关键文件**，逐个内容 hash 与 v11 冻结
源码一致，记录在同目录 `source-v11-comparison.tsv`。此前该版本真实大图
已从原始 FIRRTL 完成全部阶段，trace 轮次的 SemanticTree/use-list 校验及
最终 GRH verifier 通过；本次未另跑大图，也未将旧监控收尾误判改写为成功。

| 检查项 | 当前实现 |
| --- | --- |
| op 定义 | Pure、单结果 `kArrayUpdate`，`indexCounts` 分组多维有序更新；统一 builder/view/verifier，完整 LogicalType 校验及四态参考语义 |
| ingest | 真实 FIRRTL 动态多维写生成新 op；同一 driver 的有序更新线性批量生成，保留 enable/宽下标/后缀子数组类型；CHIRRTL data/mask 分别更新 |
| XMR / flatten | 通用引用重映射及普通/批量复制保留所有 operand、分组属性、类型、SrcLoc 和 Node 成员；专项覆盖实际 XMR 与多实例复制 |
| comb-loop-elim | 根据有序覆盖分析依赖，静态/动态局部假环可重写，真环拒绝并校验回滚；不回退为整数组 shift 更新 |
| split-static-array | 可静态确定的更新按元素/后缀投影并修改 Node；动态索引保留 `kArrayUpdate` 与数组 Node，记录 retain 原因及 update ordinal/axis |
| 持久化与 trace | 新 op 使用 `grh:3`，store/load/clone 有回归；Node/anchor/连接维护和 pass 内 trace 提交已有实现 |

本次代码复核未发现阻断 ingest→split 的确定正确性缺陷，可以将本阶段状态
记为“**新 op 已实现，生产流程已接通**”。该结论有以下证据范围：

- 尚无一个专用的小型 FIRRTL fixture 连续经过五阶段，并逐阶段独立核对
  数值及公共五文件 trace 重放；目前是分段语义专项加真实大图贯通/结构校验。
- 实际 XMR operand 专项的最终恒真 whole write 会覆盖此前两组更新，
  最终数值检查对前两组映射的检出能力有限；多实例 flatten 专项另有逐组
  映射检查，未来应补实际 XMR 的逐组来源检查或无 whole 覆盖的数值用例。
- ArrayUpdate 专项的公共 trace 断言覆盖 decision/lineage 关键字段，不能
  扩展声称已独立证明该 op 在全链上逐阶段数值等价及全部 trace 重放。
- 后续 DCE、GrhSIM 转换和 CPU/SV emit 尚未迁移；遇到残留新 op 时在
  修改图或写出产物前明确拒绝。本阶段贯通不代表可直接生成最终仿真程序。

本轮性能仍按用户已接受 v11 的决定处理，不因上述检查重新启动性能优化。

### v11 完整香山 split 后 Node 图差异（2026-11-14）

本次比较全部 GRH SemanticTree 叶 Node 与 GSIM 固有 Node，包含全部连接类型，
不以内部 op/ENode 数替代 Node 数，也不按名字剔除条件、memory 或外部模块
边界 Node。输入为完整 `build/xs/rtl/rtl/SimTop.fir`，SHA256 为
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。

GRH 来源为 `candidate-v11/guarded-trace-verify-1/trace/` 下的 comb/split
原生五文件；GSIM 来源为 F29
`full-split-fallback-readers-v2-20261114/gsim-split/`。这些文件均由原始
FIRRTL 全图原生流程生成。本轮复用导出做分析，没有重新 ingest，也没有
从 checkpoint 构造图。新产物统一放在
`ptmp/firrtl-ingest/F30/alignment-v11-20261114/`。

本轮重新完整重放 GRH comb 和 split，均精确恢复实际 after 的全部公开
Node/connection 定义；comb.after→split.before 的 **7,671,189 Node /
12,986,525 connection** 精确连续。GSIM 复用已完成精确重放的缓存，重新
核对五个 TSV 的 SHA256、整个 SQLite 的 SHA256、原生首尾身份/计数及数据库
current/after 双向集合相等后才接受，详见主报告 `gsim_source_evidence`。
这是当前文件绑定的重放缓存校验，不记成 GSIM 的一次新原生运行或新重放。

名称比较键仍是原生 `name_path_json` token 按 `.` 拼接；两侧各出现一次才
产生名称候选。连接比较只取两个端点均有上述唯一候选的 resolved 边，按
`(source_path, target_path, kind)` 去重；方向和 kind 均参与身份判断。
原始行数、端点不在共同候选内的行数、去重前重复行和 unresolved 分开统计。
该比较不覆盖位区间、端口、内部 op/ENode 或数值语义，不能由名称候选率
推导功能等价或整体演化等价。

补充 Node 分析使用原生 ID、唯一共同前态父路径及完整直接 split 坐标；
`live_children` 专指仍存活的直接 `relation=split` 后继。NULL/空坐标、
多级坐标需要组合、多个来源或截断时保守保留未解释状态。显式少量样本另查
“按父/坐标找到的成员”与“按同名找到的成员”是否具有冲突的原生来源；
此检查不扩展为全图身份一致证明。双侧分类不删除或过滤任何 unmatched Node。

当前 v11 重算得到以下库存与唯一名称候选；这些数值与 v7 相同，但来自
本轮对当前文件的校验和重算，没有将旧报告数值当作新结果。

| 比较点 | GRH 全部叶 Node | GSIM 固有 Node | 唯一名称候选对 | GRH 未匹配 | GSIM 未匹配 | 候选占 GRH 比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| split 前（GRH 已过 comb） | 7,671,189 | 7,829,556 | 7,668,660 | 2,529 | 160,896 | 99.96703249% |
| split 后 | **9,328,200** | **9,635,014** | **9,297,125** | **31,075** | **337,889** | **99.66687035%** |

split 后名称候选占 GSIM 的 **96.49311355%**。GRH 净增 **1,657,011**
个 Node，GSIM 净增 **1,805,458** 个；GSIM 比 GRH 多出的库存从
**158,367** 增为 **306,814**，增量相差 **148,447**。两侧都是节点数增加，
不能由两侧总量之差推导某一端 split 减少了节点。GRH/GSIM 分别记录
**1,876,842 / 2,051,495** 条原生 split lineage；GRH comb 的 **253** 次
replace 不增减 Node，连接从 **12,981,915** 变为 **12,986,525**。

| split 后连接口径 | GRH | GSIM |
| --- | ---: | ---: |
| 原始行数 | 15,837,478 | 15,568,445 |
| resolved 行数 | 15,318,589 | 15,568,444 |
| unresolved 行数 | **518,889** | **1** |
| 共同唯一端点范围内、去重后的 resolved 元组 | 14,393,879 | 14,469,145 |
| 上述范围内各侧独有元组 | **885,376** | **960,642** |

共同元组为 **13,508,503**，对称差共 **1,846,018**。相同口径的 split 前
GRH/GSIM 可比较元组为 **12,981,467 / 12,823,543**，交集为
**12,479,539**；前态 GRH unresolved 为 **0**，后态升为 **518,889**。
这表明目前的缺口不仅是名称库存：split 后的来源边界解析及连接维护仍需
继续核查。各侧独有边不直接解释成电路功能不同，unresolved 也不计入该差集。

双侧 unmatched 已全部逐行导出，使用直接原生 lineage 进一步细分：

| GRH 未匹配的结构分类 | Node 数 |
| --- | ---: |
| GRH 父仍活、无存活 split 成员；GSIM 父退休并拆出成员 | **26,260** |
| GRH 已拆出成员，但父仍活；GSIM 父已退休 | **3** |
| GRH 已拆成员，GSIM 原始父仍活且无 split 成员 | **1,238** |
| 唯一公共原始父和完整坐标一致，但成员名不同且不涉及重名 | **837** |
| 上述坐标对应成员的任一侧名字有歧义 | **208** |
| split 前即无唯一公共同名 peer 的原始 Node | **2,529** |
| 合计 | **31,075** |

最后一类恰为 **976** 个 `$ADDR` pipeline 名及 **1,553** 个 `$storage`
层级名，均是前态已有差异；不再把这 976 项当作 split 新引入的未知问题。
主分析沿用的 `gsim_split_grh_retained=26,263` 只表示 GRH 父保留，应拆成
上表的 **26,260 个未拆父 + 3 个拆后残留父**。命名项仍共 **1,045** 个，
本次按坐标 peer 的歧义分为 837＋208；208 是 Node 行数，不是重名组数，
也不同于主报告按当前同名键统计的 104 条 peer 歧义口径。

| GSIM 未匹配的结构分类 | Node 数 |
| --- | ---: |
| split 前即无唯一公共同名 peer 的原始 Node | **160,896** |
| GSIM 已拆成员，GRH 原始父仍活且无 split 成员 | **175,876** |
| GSIM 父未拆，GRH 父退休并拆出成员 | **67** |
| 同原始父/完整坐标的不同名成员 | **837** |
| 同原始父/完整坐标、名字存在歧义 | **208** |
| 通用分类暂为 `other_unresolved`，点查确认原始 Node 改名 | **5** |
| 合计 | **337,889** |

GSIM baseline 的 **160,896** 项中，**156,703** 项名字含 `when@`，
**976** 项含 `$address`，其余 **3,217** 项保持为 baseline 表示差异。
`when@` 来自 GSIM `allocCondNode` 创建的独立条件 Node；这是源自 FIRRTL
的原生 Node，不能为改善统计而过滤。名字形态统计不自动证明与某个 GRH op
集合功能相同，也没有把这 3,217 项擅自归为同一种原因。

原生决策和边界的代表样本如下，完整路径与双方 ID 均在 `node-differences/cases.json`：

- GRH **146871** `...dmInner._flags_WIRE.resume` 保留，理由
  `dynamic_consumer_index`、blocker **146874**；GSIM **120266** 退休并
  拆出 **64** 个成员。GRH **201072** `core.io.l2_tlb_req.resp.bits.paddr`
  则因 `unsplit_upstream_array`、blocker **226159** 保留，对侧拆成 **2** 个。
- GRH **1811547/1811548/1811549** 对应 ROB `ftqIdx.flag/value`、
  `ftqOffset`；每个两侧均有 **8** 个同坐标成员，GRH 有
  `replace/static_array_split` 决策但父仍活，GSIM 父 **1933513/14/15**
  已退休。源码 `SemanticArrayNodes::finish` 会为尚不能迁走全部 op 的父保留
  residual；不能跳过 op 归属检查直接删除父节点。
- GRH **7706875** 的 `_WIRE_2_0_0` 与 GSIM **8016587** 的
  `_WIRE_2_0_0_0` 来自同一公共父及坐标 `[0,0]`。GRH **8902279** 与
  GSIM **9269403** 同属 `vIAluMisc._WIRE` 的 `[2,0]`，但 GSIM 的
  `_WIRE_2_0` 公共名有两个活跃 Node。不能将所有命名项归因于单元素维度。

**另已确认 5 对唯一同名候选违反稳定原始身份，99.66687035% 不能称为身份对齐率。**
这五个 GSIM 原始 Node 与 GRH 原始 peer 在前态唯一同名，且两侧原始 ID 都
存活到后态；GSIM 将原始名字追加 `_0`，新数组成员却占用旧名，导致名称
比较选中了另一个身份。下表的错误候选均实际存在于 `after.candidates.tsv`：

| 原始路径尾部 | GRH 原始 ID | GSIM 原始 ID（后态名追加 `_0`） | 后态同名 GSIM 错误候选 | 错误候选的原生 split 来源 |
| --- | ---: | ---: | ---: | --- |
| `dcache.mainPipe.r_3` | 5581354 | 5562182 | 9356717 | 父 5560441 `r`，坐标 `[3]` |
| `slices_0.sinkC.REG_1` | 6834382 | 6911217 | 9794356 | 父 6911214 `REG`，坐标 `[1]` |
| `slices_1.sinkC.REG_1` | 6892434 | 6971257 | 9804561 | 父 6971254 `REG`，坐标 `[1]` |
| `slices_2.sinkC.REG_1` | 6950486 | 7031297 | 9814766 | 父 7031294 `REG`，坐标 `[1]` |
| `slices_3.sinkC.REG_1` | 7008538 | 7091337 | 9824971 | 父 7091334 `REG`，坐标 `[1]` |

`original-name-conflicts/cases.json` 对这五个显式样本均自动输出
`pair_basis=stable_original_ids`、`status=structural_identity_conflict`，
保留候选的真实父和坐标。这证明了具体的身份错配，未扩展声称电路功能不同；
也不将总候选减去 5 后称作全图已验证身份数，其余名称候选尚未逐一完成此类
身份校验。所有连接交集/差集仍是**当前名称映射下**的粗图统计，含这五个
已知错误候选，尚不是修正身份映射后的连接对齐结果。

连接补充导出已 `complete=true`、`public_comparison_crosscheck.exact=true`：

| 共同唯一端点范围内的 kind | 共同元组 | GRH 独有 | GSIM 独有 |
| --- | ---: | ---: | ---: |
| dependency | 13,236,938 | **885,372** | **960,572** |
| state_update | 263,595 | **4** | **70** |
| storage_read | 4,585 | 0 | 0 |
| storage_write | 3,385 | 0 | 0 |

可比较范围内本轮无重复元组；另有 GRH **924,710**、GSIM **1,099,299**
条 resolved 因至少一个端点不在共同唯一候选内而被排除。GRH 的 storage
read/write 各有 **1,553** 条被排除，不能从表内零差异推导全部 memory
身份已经对齐。GSIM 原始 `external_binding` 有 **1,152** 行，GRH 为 **0**；
该类没有共同端点范围内的可比较元组，仍是覆盖缺口。

共有 **1,410,126** 个共同候选 Node 至少连接一条独有边，已经明显超过
未同名的 Node 数。具体非数组例子：`logEndpoint.reset` 在 GRH 独有边中
指向 `ALU0_fire_cntCounter$NEXT`，在 GSIM 独有边中指向
`ALU0_fire_cntCounter`。原生 split.before 中也分别存在这两条边
（GRH connection **12803983**、GSIM **12746683**），说明此例是既有的
寄存器/reset 依赖边界定义差异，不能全部算作 split 新错误。
`logEndpoint.reset` 共关联两侧各 **33,037** 条独有边，是高扇出样本；
尚未将所有 dependency 差异归为这一种原因。

GRH **518,889** 条 unresolved 全部为 `ambiguous-native-boundary`，
候选数 **2–65**；其中双候选 **271,549** 条。例子是
`pma._cfg_T_1`（**184565**）的来源候选
`pma.pmaCfgMerged_0`（**9335326**）与 `pma._cfg_WIRE_0`（**9494308**）：
这三个 Node 都存活且能找到 GSIM 名称/原始坐标对应物，因此问题在依赖边界
来源不能唯一确定，不能解释成 Node 消失或任选一个候选补边。GSIM 唯一
unresolved 是 `cpu.jtag` 的 external-port direction，单独记录。

当前产物入口（均在 `alignment-v11-20261114/`）：

- `summary.json`：主分析 **complete=true**，三套原生重放证据、阶段连续性、
  前后库存及名称/连接统计；仍保留 `evolution_alignment_verified=false`。
- `after.candidates.tsv`、`after.unmatched.tsv`：完整名称候选与双侧缺项；
  `decisions.tsv`、`unmatched-reasons.tsv` 保留原生决定及 GRH 祖先解释。
- `node-differences/{grh,gsim}.unmatched.tsv`：双侧每一个缺项的直接结构
  分类、父/peer 存活状态、成员数、完整坐标与双方原生决策理由。
- `original-name-conflicts/cases.tsv`、`cases.json`：五例稳定身份冲突；
  `gsim-name-candidate-cases/cases.json` 另保留错误同名候选的 split 来源。
- `connection-differences/{grh-only,gsim-only}.connections.tsv`：两侧独有边，
  每行附双方端点 Node ID；`affected-nodes.tsv` 列出每个受影响候选 Node。
  同目录 `summary.json` 含 kind 分组、全部 unresolved 分组及有限样本。

诊断入口为 `make analyze_f30_alignment`、`make inspect_f30_alignment_cases`
及 `make export_f30_connection_differences`；新增两套轻量契约分别
**18/18、9/9 通过**。本轮只改诊断工具和文档，生产 ingest/comb/split
实现及用户已接受的 v11 性能状态不变。后续对齐优先处理拆分资格/上游阻断、
成员冲突命名与稳定身份映射、残留 op 归属，以及共享 value 和寄存器/reset
的依赖边界；不能仅靠改名称比较脚本宣称两端 Node 图已对齐。

## split 成员名称冲突修复（2026-11-14）

上节五例直接由 GSIM 的旧规则引起：新成员取首选名字，已存在的原始 Node
被迫追加 `_0`。例如原始 `r_3` 与数组 `r` 的 `[3]` 成员同时存在时，原始
`r_3` 被改为 `r_3_0`，新成员反而成为 `r_3`，唯一名称比较就会选错身份。
GRH 的 `SemanticArrayNodes::prepareMany` 也采用过同类改名策略，只是提前
检查得更完整；GSIM 还没有把新成员登记到名字表，后续数组可再次取走相同
名字。这是生产 pass 的身份维护问题，需要修改两端生成规则。

两端公开 Node 采用以下规则：

1. 已存在的 Node 保持 ID 和名称，包括此前拆出的成员。
2. 新成员先按现有数组坐标规则取名；冲突时只给新成员反复追加 `_0`，
   直到空闲。例如同时有 `r_3`、`r_3_0` 时，新 `r[3]` 使用 `r_3_0_0`。
3. 每个新名字立即预留。GRH 同一 current/next family 的待生成成员也要
   参与冲突检查；本次 pass 内已经退休的父名也不再分配给另一个身份。
   GSIM 复用 `allSignals`，GRH 仅另存实际退休的名字，避免复制全图名字集合。
4. 公共身份的碰撞后缀与 GSIM `identitySuffix` 同步；不可变原始来源和
   完整 split 坐标仍分别记录，不通过后缀猜测 lineage。

GRH 内部 op/value symbol 的 alpha-renaming 属于另一层，继续沿用现有逻辑；
它不再引起已有 SemanticNode 改名。本次保留单元素轴等既有坐标取名约定，
不同数组的拆分次序也可能影响冲突后缀；规则改善身份稳定性和名字唯一性，
不把唯一同名自动升级为已验证的语义等价。

生产修改位于 GSIM `src/{splitArray,AST2Graph}.cpp` 和 GRH
`lib/transform/split_static_array.cpp`。新增原生回归覆盖连续后缀冲突、
跨数组生成名冲突、原始 ID/名称/op 集合保留、current/next 配对及开关 trace
结果一致。完整原图验收及命名变化清单记录在
`ptmp/firrtl-ingest/F30/naming-fix-20261114/`，后续结果附于本节。

验收使用同一份原始完整 `SimTop.fir`（SHA256 仍为
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`），
GRH 仍按 manifest 导入 SV helper；没有读取 checkpoint、clone 或缩小输入。
执行记录：

- `make test_f29_gsim`、`make test_f29_exchange_gsim`：GSIM 原生 lineage、
  aggregate、expression、演化重放及五文件测试通过，新增碰撞用例开关 trace
  的 Init/TopoSort/InferAllWidth JSON 逐字节一致。
- `make test_f30_array_update`：**27/27** 通过，包含 GRH 活跃名字、退休
  父名、跨数组及同 family 预留回归；内部 symbol 碰撞旧测试仍通过。
- `make test_f29_exchange_pipeline SKIP_PY_INSTALL=1`：真实 ingest/pass 的
  **7 个 fixture** 双端静态快照与原生五文件重放通过。
- `make test_f30_split_naming`：**10/10** 通过；名称诊断检查器可拒绝
  前态漂移、原始保名破坏、当前重名、错误来源坐标、不完整输出及源文件变动。

完整原图原生导出分别使用 `make export_f30_gsim_split` 与
`make benchmark_f30_pipeline`（冻结更新后的 Python/native package，trace、
SemanticTree 校验、`grh.verify`、96 GiB/PSI guard 开启；split 硬时限仍为
GSIM 既有参考派生的 **91.808 s**）。实际完成值：

| 本轮命名修复诊断样本 | 耗时 |
| --- | ---: |
| GSIM splitArray（原生 exchange trace 开启） | **117.762 s** |
| GSIM 整个命令，含原生前后导出和进程退出 | **326.62 s** |
| GRH ingest / XMR / flatten | **42.276 / 0.340 / 41.211 s** |
| GRH comb-loop-elim / split-static-array 原生 pass | **11.335 / 40.833 s** |
| GRH ingest 至 split 校验结束，含 trace setup/finish 和验证 | **235.616 s** |

GSIM 上次同类 trace 导出的 split 为 **117.369 s**，本轮增加约 **0.393 s**；
这不是无 trace 的 GSIM 参考时间。GRH 本轮 comb＋split 原生 pass 合计
**52.168 s**，原始计时、各段导出/校验和资源记录分别在
`full-gsim/{gsim.log,resources.log}`、`full-grh-retry/{summary.json,guard.json}`。
这是带校验、guard 的单次正确性诊断，不替换用户已接受的 v11 多轮性能验收。

GRH 首次尝试 `full-grh/` 在 **flatten** 被持续 PSI 压力主动终止，当时
进程约 **62 GiB**，尚未到修改过的 split，也未触及 96 GiB RSS 上限。
保留失败的 guard/summary；通过 `make release_f30_analysis_cache` 对 F29/F30
大型 TSV/SQLite/JSONL 发出 `POSIX_FADV_DONTNEED`，没有删除文件，主机文件
缓存从约 **97 GiB** 降至 **5.6 GiB**。随后 `full-grh-retry/` 使用相同 guard
阈值完成，峰值 RSS **84,350,904 KiB**，guard 为 `child_completed`。
GSIM 命令峰值 **85,629,952 KiB**、exit 0；两端五文件均写出完整成功 footer。

本轮完整后态库存仍为 GRH **9,328,200**、GSIM **9,635,014**，连接行数也
仍为 **15,837,478 / 15,568,445**。原生 producer 完成各自 journal 的重建
检查；本轮命名诊断不重复离线重放全部连接、不声称更新后的跨端连接已等价。
命名库存和五例原始身份的独立检查使用 `make check_f30_split_naming`，
结果及逐行变化清单放在本轮目录的 `comparison/`。

`comparison/summary.json` 最终为 **complete=true、passed=true、issues=[]**，
全量命名检查耗时 **333.794 s**；SQLite 仅作为有界缓存的临时名字索引，
完成后删除，不进入正常 ingest/pass 流程。

| 完整原图命名检查 | GRH | GSIM |
| --- | ---: | ---: |
| 旧／新 split 前态库存的 ID 或名字差异 | **0** | **0** |
| 旧／新 split 后态 ID 集合增加／删除 | **0 / 0** | **0 / 0** |
| 本轮从前态存活到后态的原始 Node | **7,451,358** | **7,583,519** |
| 上述存活原始 Node 在本轮被改名 | **0** | **0** |
| 旧后态→新后态发生名字变化的行 | **109,692** | **109,242** |
| 其中恢复原名的存活原始 Node（稳定原始 ID） | **472** | **476** |
| 本轮公共路径重名／原生名字重名 | **0 / 0** | **0 / 0** |

恢复原名的 472/476 项来自完整变化 TSV 中的 `stable-original-id` 行；因为
前态完全相同且本轮所有存活原始 Node 均保名，这些行明确表示旧流程曾改变
原名。其余 **109,220 / 108,766** 行只按两次运行的生成 ID 同值统计名称
变化，不能当作逐个生成身份已对齐；分类汇总另存
`changes-by-identity-scope.tsv`。由此可见，两端都需要修复旧策略，而不只是
修补五个名称候选或只改比较器。

| split 后唯一名称候选口径 | 修复前 v11 | 本轮 |
| --- | ---: | ---: |
| 双侧唯一名称候选对 | 9,297,125 | **9,298,160**（增加 **1,035**） |
| 候选占 GRH Node 比例 | 99.66687035% | **99.67796574%** |
| 候选占 GSIM Node 比例 | 96.49311355% | **96.50385562%** |
| GRH / GSIM 名称未匹配 Node | 31,075 / 337,889 | **30,040 / 336,854** |
| 名字存在歧义的 GSIM Node | 208 | **0** |

前述五个原始 ID 在两端均存活且恢复唯一同名，五个 GSIM 新 child 也各有
唯一名字；对每个 child 均读取本轮原生 lineage，验证原父 ID、`split` 关系
和完整坐标仍为旧例的 `[3]` 或 `[1]`。**五例已知身份误配全部消除**：
原始 GSIM **5562182** 继续叫 `...mainPipe.r_3`，child **9356717**
来自 `r[3]` 并叫 `...mainPipe.r_3_0`；四个 `REG_1` 也分别由原始 ID 保名，
新成员使用 `REG_1_0`。不再把 child 当作原始 Node 的 peer。

最终证据为 `comparison/{summary.json,node-name-changes.tsv,duplicate-names.tsv}`；
变化 TSV 逐行列出两端旧／新路径、原生名字、ID 和身份口径。`summary.json`
保存全部五例的当前名字与原生来源。本轮新增的 1,035 对仍只是名称候选，
未将其余所有成员的跨端 lineage 逐一验证，也未重新计算新名称映射下的
连接差集；上节 v11 连接统计继续作为旧映射基线，不能作为本轮连接结果。
