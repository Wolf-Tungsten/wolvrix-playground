# Stage 02 — kSliceArray 重定义（数组一等访问）

- 日期：2026-10-08（2026-10-08 修订：comb_lane_pack 适配点改为直接删除——pass 退役；
  2026-10-09 实施完成，Q1 按 Verilator 实证重定稿）
- 状态：已实施（2026-10-09）
- 依赖：stage-01（Value shape）
- 对应总目标：#3

## 实施记录（2026-10-09）

已合入：kSliceArray 新语义（无 sliceWidth、1..N 索引、宽度/形状来自 base value shape）；
ingest 桥接（物化点为无 shape 的 base 回填 1 维 shape=[元素数]——新增
`Graph::setValueShape`/`GraphBuilder::setValueShape` 回填 API，仅允许空 shape 时设置；
result 继承 base shape 的剩余维）；`grh.verify` 增加 kSliceArray 规则（base 必须带
shape、1≤k≤rank、索引为标量、result width/shape 与几何一致）；const_fold 按新语义折叠
并**修正了旧代码索引不乘 sliceWidth 的 bug**（grhsim const_fold 同款 bug 同修）；
slice_index_const 支持 kSliceArray 全常量折叠为 kSliceStatic；SV emit 多索引行主序
线性化（见 §8 Q1 重定稿）；grh_to_grhsim 过渡：转换层为 sliceArray 补 sliceWidth 参数
（= 元素宽），仅支持单索引，多索引归 stage-06；comb-lane-pack pass 整体删除
（lib/transform/comb_lane_pack.cpp、include、注册点、测试、pybind 适配器与
`__init__.py` kwargs 编译器、3 个脚本管线引用一并移除——ctest 既有失败
transform-comb-lane-pack 随之消失）。

与 §3.5 清单的偏差：

1. **SV emit 未改声明形态**：§8 Q1 原结论（"一律发 packed 数组声明"）被实证推翻后
   重定稿为扁平声明 + 线性化切片（见 §8 Q1）。
2. slice_index_const 只实现"全常量 → kSliceStatic"；部分索引折叠（降低 k）在桥接期
   无生产者（桥接只产 k=1），留待 stage-04 后按需补。
3. `grh-ir-visualize` 的索引展示增强不阻塞，顺延（同 stage-01 的顺延项一并处理）。
4. comb_loop_elim 的 kSliceArray 位段分析保持现状（置 uncertain 放弃），数组感知归
   stage-05。

## 1. 目标

把 kSliceArray 从"扁平位向量上的定宽动态切片（sliceWidth 属性判宽）"重定义为
"**只能作用于数组类型 value 的多维元素访问 op**"：1 到 N 个索引操作数，支持高维数组访问，
宽度信息完全来自被切 value 的类型，不再有任何 sliceWidth 属性。

## 2. 现状事实

- 现行语义（`wolvrix/docs/grh/grh-ir.md:817-834`）：操作数 `[flatArray, index]`，属性
  `sliceWidth`（须整除被切值宽 W），结果 = `array[index*sliceWidth +: sliceWidth]`，
  index 按无符号解释；多维 packed 数组访问靠 kSliceArray **级联**。
- 生产端：ingest `makeSliceArray`（`wolvrix/lib/core/ingest.cpp:6150-6162`）、
  `ElementSelectExpression` 两处（`ingest.cpp:8447-8453, 20925-20934`）；常量下标在落地时
  预折叠为 kSliceStatic（`ingest.cpp:21481-21503`）。
- 消费端：
  - SV emit：`base[idx*W +: W]`（`wolvrix/lib/emit/system_verilog.cpp:4121-4164`），
    emit 时才乘宽度。
  - GrhSIM lowering：`core.compute.sliceArray`（`wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp:92`）；
    CPU emit `start = idx*width` + 钳位（`wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:1593-1612`，
    宽位路径 1896-1911）。
  - `const_fold.cpp:529-548`：按位偏移折叠、**未乘 sliceWidth**——与文档语义不一致的
    现存 bug，当前靠 ingest 预折叠常量下标掩盖（常量 kSliceArray 很少活到 const-fold）。
    本阶段必须一并修正。
  - `comb_loop_elim.cpp:880-882`：位段分析遇 kSliceArray 直接置 uncertain 放弃。
  - `slice_index_const.cpp:342-392`：只处理 kSliceDynamic，不碰 kSliceArray。

## 3. 设计

### 3.1 新语义

```
kSliceArray
  操作数: [array, i0, i1, ..., ik-1]
    array      : 数组类型 value，shape = [d0, d1, ..., dn-1]，元素类型 E
    i0..ik-1   : 标量 value（任意宽度，按无符号解释），1 <= k <= n
  属性: 无（sliceWidth 废除）
  结果:
    k == n  : 标量，类型 E（元素）
    k < n   : 数组，元素类型 E，shape = [dk, ..., dn-1]（子数组，SSA 单一定义）
  位语义: 结果等价于从 array 的扁平位表示中取出
          offset = (i0*d1*...*dn-1 + i1*d2*...*dn-1 + ... + ik-1*dk*...*dn-1) * E.width
          开始的 resultTotalBits 位。
  越界: 任一索引 >= 对应维长度时行为为实现定义（两态仿真按现行钳位，四态/SV 为 x），
        文档明确不写死，避免成为仿真器间差异源。
```

### 3.2 例子

```systemverilog
logic [7:0] a [0:3][0:5];
logic [7:0] e;
logic [7:0] row [0:5];
assign e   = a[i][j];   // 全索引
assign row = a[i];      // 部分索引
```

```
%a  : UInt8[4][6]
%e  = kSliceArray(%a, %i, %j)   // k=2=n，结果标量 UInt8
%r  = kSliceArray(%a, %i)       // k=1<n，结果 UInt8[6]（子数组，SSA）
```

旧表示需要两条级联 kSliceArray + sliceWidth 属性，且第二条的"数组"其实是第一条的位切片。

### 3.3 与既有 op 的边界

- **kSliceArray 作用于组合 value；状态数组的索引访问走 kRegisterReadArrayPort /
  kRegisterWriteArrayPort**（stage-03）。两者共享同一套"下标不足 rank = 高维子数组"
  规则（stage-03 §3.3 与本节 §3.1 逐字对齐）。

- **kSliceStatic**：常量下标的数组元素访问不再折叠成 kSliceStatic 位段？——仍然折叠，
  但结果 value 带上正确的 shape（stage-01 §3.4 已允许 kSliceStatic result 带 shape）。
  即"常量索引折叠"从 ingest 特例（`ingest.cpp:21481-21503`）升级为通用规则。
- **kSliceDynamic**：保持现状（动态位段切片，纯位语义），可用于任何 value（含带 shape
  的——packed 扁平语义下合法）。与 kSliceArray 的分工是惯例而非约束：ingest 对数组元素
  访问一律用 kSliceArray，位段访问用 kSliceDynamic。verifier 只强制：kSliceArray 输入
  必须 shape 非空。
- **kConcat**：stage-01 已定义同形数组拼接；数组的"构造"走 kConcat / kConstant / kMux /
  kRegisterReadPort / kSliceArray(部分索引) / kRegisterReadArrayPort(部分索引，stage-03)。

### 3.4 迁移策略：旧语义一次性废除，不并存

- OpKind 枚举与 `kOperationNames` 表保持原位（`grh.cpp:2605-2663`），语义直接替换。
  GRH JSON 格式未发布（stage-01 §3.5），旧式 kSliceArray（带 sliceWidth 属性）只可能
  出现在旧产物里——load 端不做兼容，旧产物重新生成即可；内存表示统一为新语义。
- ingest 在新语义落地前（stage-04 之前）必须停止产生旧式 kSliceArray：临时桥接方案是
  ingest 把 packed 数组值声明为 1 维数组（shape=[元素数]），访问即合法的新式 kSliceArray。
  该桥接保证 stage-02 合入后 HDLBits 等门禁仍可运行（具体豁免以实测为准并登记）。

### 3.5 消费端适配清单

| 消费端 | 适配 |
|--------|------|
| `const_fold.cpp:529-548` | 按新语义折叠：全部索引为常量 → 折叠为 kConstant（位段提取）或 kSliceStatic；同时**修正现存的不乘 sliceWidth bug**（旧代码路径随旧语义一起删除） |
| `comb_loop_elim.cpp:880` | 数组感知的位段分析（元素粒度已知），详见 stage-05 |
| `slice_index_const.cpp` | 扩展处理 kSliceArray：部分索引为常量时折叠该维（降低 k），全常量时转 kSliceStatic |
| `system_verilog.cpp:4121-4164` | 多索引发射：`base[i0][i1]...`——数组 value 在 SV 端一律声明为 **packed 数组**（`logic [3:0][7:0] x`），packed 是 integral，表达式全合法（stage-01 §3.4） |
| `grh_to_grhsim.cpp:92` | 映射到扩展后的 `core.compute.sliceArray`（多索引，stage-06） |
| `cpu_phase_emit.cpp:1593-1612, 1896-1911` | 行主序线性化偏移表达式；钳位语义保持 |
| `activity_schedule.cpp`、`repcut.cpp`、`dead_code_elim.cpp`、`redundant_elim.cpp` | 模式匹配点的操作数个数/属性假设逐一核对（这些 pass 把 kSliceArray 当 2 操作数处理） |
| `comb_lane_pack.cpp` | **直接删除**——comb-lane-pack 退役（2026-10-08 定稿，见 stage-05 §8 Q1），连同注册点与文档引用一并移除 |

## 4. 文件级改动点

- `wolvrix/docs/grh/grh-ir.md` §6.2.8：整节重写（语义、操作数、例子、越界条款）。
- `wolvrix/lib/core/grh.cpp` / `include/core/grh.hpp`：op 注释契约更新；verifier 规则
  （stage-01 的 verify pass 增加 kSliceArray 规则：输入必须数组、1≤k≤rank、索引为标量）。
- `wolvrix/lib/core/load.cpp`：无需迁移代码；旧产物自然失效。
- `wolvrix/lib/core/ingest.cpp`：临时桥接（§3.4），正式生产端重写归 stage-04。
- §3.5 表中全部消费端文件。
- `grh-ir-visualize/`：op 详情展示索引操作数列表（跟随 JSON 变化）。

## 5. 基础设施联动

- 持久化：随 stage-01 的格式演进完成；本阶段无额外格式工作。
- diagnostics：verifier 报错走 PassDiagnostics；SV emit 对"数组 value 无法 emit"的临时
  形态报明确错误而非崩溃。

## 6. 文档更新

- `grh-ir.md` §6.2.8 重写；§2.3 中"多维数组访问通过 kSliceArray 级联实现"一句删除。
- `docs/grhsim_ir/dialects/core.md` 中对 GRH kSliceArray 的引用（§8 映射表）标注
  "待 stage-06 落地"。

## 7. 破坏面与回退

- 破坏：含旧式 kSliceArray 的旧 JSON 产物（重新生成即可）；任何直接按
  "2 操作数+sliceWidth" 假设写死的第三方脚本。
- 门禁：目标是不豁免；若 ingest 桥接覆盖不全，登记 HDLBits 用例豁免清单并在 stage-04 清零。
- 回退：单阶段 revert 即可（ingest 桥接与消费端适配在同一阶段内，无跨阶段依赖）。

## 8. 开放问题（全部关闭，2026-10-08）

1. ~~**SV emit 的数组 value 形态**~~ **已关闭（2026-10-08）**：~~问题本身被 packed-first
   决策消解——emit 一律发 **packed 数组声明**（`logic [3:0][7:0] x`，stage-01 §3.4），
   packed 声明是 integral（算术/按位/动态索引全合法）且保留数组下标的可读性；
   原问题的 unpacked/扁平两个候选都不需要。无打包/解包辅助函数。~~
   **重开并重定稿（2026-10-09，实证）**：Verilator 5.051 实测
   （`ptmp/stage02-probe/packed_select_sim.sv`）——packed 数组上的**扁平位选择**语义
   不是扁平位：`x[15:8]`（x 为 `logic [3:0][7:0]`，值 32'hDEADBEEF）结果为
   32'hDEADBEEF（左维 range 被钳到 [3:0]），而扁平位 `[15:8]` 应为 8'hBE；
   只有元素对齐的左维 range（`x[2:1]`）恰与扁平位段一致。而 ingest 会对任意 value 产出
   kSliceStatic/kSliceDynamic 扁平位选择——emit 若发 packed 声明则这些选择全部错位。
   **决定：emit 一律保持扁平声明（`logic [W-1:0]`），kSliceArray 发射为行主序线性化
   扁平切片 `base[(i0*d1+i1)*E +: E]`**。"数组下标可读性"目标让位给正确性；将来若要
   packed 声明可读性，需要 emit 侧把所有扁平选择翻译成逐维选择（非对齐位段无法表达），
   不在当前路线图。
2. ~~索引操作数宽度是否需要上限约束（如 ≤32bit）？~~ **已定（2026-10-08 拍板）：不限制**；
   CPU emit 内部按地址运算所需宽度截断/扩展。
