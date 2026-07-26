# ST00009 发射体积压缩（块内值局部化）

- 父节点：ST00001
- 状态：trunk（2026-07-25，L1 2k −4.9%；L2 50k 经用户批准豁免）
- 代码状态：wolvrix @ `afcd5fd` + ST00002/ST00008 本地改动 + 本节点 `lib/grhsim/am/cpp_emitter.cpp` 改动（未提交）
- 创建日期：2026-07-25

## 假设

AN00004：AM emu 是取指瓶颈（.text 360MB vs legacy 84MB），代码体积是硬通货。文本画像（baseline 生成代码）：no-op resize/冗余 mask 占源码 ~30% 但编译器已折叠，对 .text 无贡献；.text 主源是**每条指令经 `values_[]` 全局数组存取**（索引物化 + load/store，阻碍寄存器分配）。全设计 ~9.39M scheduled 变量中仅 ~1.9M 有跨块使用——块内定义且仅块内使用的值应发成 C++ 局部变量，这是 legacy 代码紧凑（704k boundary）的同一结构。

死 detector 静态消除（原 ST00006 子项）经审查放弃：物化构造上每个 detector 一一对应真实跨块 def-use，无静态死项。

## 改动

`wolvrix/lib/grhsim/am/cpp_emitter.cpp`（+330/−66）：

- 两遍扫描全部 block 指令构建逃逸集（确定性纯函数，measureBlockCase 与实际发射两处逐字节一致）；
- 逃逸规则（取并集，宁可保守）：跨块使用 / ChangedAny 全部操作数与结果 / 块内先于定义的使用（跨 epoch 反向边）/ state 写目标与 memory 写全部操作数 / ports 与 interface 变量 / commit capture 与 pre-commit snapshot / 带 init 语义（Constant/Actions）/ system task·DPI 相关 / 定义次数≠1 / 宽值·real·string；
- 非逃逸窄值（BitVector ≤64 bit）发成块内稠密局部变量 `local_<k>`（合并声明行），逃逸值维持 `values_[N]`；ActForward/Backward guard 按普通使用处理（可局部化）。

## 测量

**覆盖率与源码体积（2026-07-25，XiangShan emit）**：局部值 2,553,380（27.2% scheduled 变量，分母含 detector 旧值槽/捕获槽/宽值等强制逃逸项），局部值引用 8.0M 次（均 ~2.1 次/值）；block 源文件合计 1,526,914,065 → 1,509,963,635 字节（-1.1%，声明行开销抵消大部分引用变短收益——源码字节不是主指标，.text 才关键）。

2k 功能 gate 与性能门控结果如下；早期 baseline 140,573 ms / 360MB 仅作跨会话参考，正式判定采用同会话交错数据。

**emu .text（2026-07-25）**：359,937,610 → 334,390,470 字节（**-7.1%，-25.5MB**；对照：legacy 84MB、gsim 66MB）。

**2k 门控（2026-07-25，solo，`setarch -R` + `taskset -c 7`，profile OFF，-C 2000）**：

| 运行 | wall_ms |
| --- | --- |
| ST00009 ×3 | 138,683 / 138,746 / 138,591（中位 138,683，离散 0.1%） |
| baseline 同会话 ×3 | 146,932 / 145,782 / 145,834（中位 145,834，离散 0.8%） |

中位数对比 **-4.9%**，超出 2% 噪声带 → **L1 收益确认**。功能 gate 全部逐字一致（instrCnt=3 / cycleCnt=1,996）。

**重要方法学发现**：baseline 同二进制跨会话漂移达 ~3.7%（当早 140,573 vs 当晚 145,834）——360MB fetch-bound 二进制对机器/布局状态敏感。**emit 级对比必须同会话交错测量**（ST9 与 baseline 本次为同会话交替，差值稳健）。

**50k 确认（L2）**：用户决定跳过（2026-07-25，单次 50k ~70 分钟成本过高）；本节点凭 L1 同会话交错结果定案，50k ratio 待后续节点顺带回填。

## 结论

**接受（trunk）**。2k 同会话交错 −4.9%（超噪声带），.text −7.1%，功能 gate 逐字一致；L2 50k 经用户批准豁免。这是树搜索首个正收益节点，方向与 AN00004 fetch-bound 模型自洽（体积 −7% ≈ 时间 −5%），局部化基础设施对后续 emit 类节点有复利价值。

## 子节点候选

- **扩大局部化覆盖率**（本节点仅 27.2%）：逃逸集中 detector 旧值槽（每 detector 一个全局槽）是最大强制逃逸类——旧值槽只在源 block 的 ChangedAny 中读写，若该 block 每 epoch 必执行则可降级……需更精细的活性分析，收益待估；
- **宽值（>64 bit）局部化**：本次只做了窄值，宽值走 wideValues_ 同理可局部化（需数组型局部变量）；
- commit 巨块（单块 7MB 源码）是体积异常点；ST00005 已证 event 生命周期减重不足，后续转由 ST00011 直接削减写槽脚手架。
