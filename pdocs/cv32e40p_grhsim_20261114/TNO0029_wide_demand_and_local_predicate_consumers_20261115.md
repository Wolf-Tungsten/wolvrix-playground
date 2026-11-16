# TNO0029：宽值条件执行与局部译码消费者修复

针对 TNO0028 的后两个问题，完成了两个独立 emitter 规则及同轮对照。宽值准备进入所属条件分支后，外部 walltime 降低 **0.3434%**，95% CI **[−0.7410%, −0.0450%]**。局部译码消费者化简降低 **0.2535%**，CI **[−0.6072%, +0.0527%]**，整机收益尚不明确。两者都通过完整功能与总线 trace；相对同 RTL Verilator 分别仍为 **1.03692 倍**和 **1.03785 倍**。

跨区域接口问题按用户要求保留。本轮没有把运行结果用于生成规则、阈值、站点选择或后验组合；两项规则各自默认关闭，未改变当前保留版或生产默认。只有一组四后端、8 轮正反序测量，没有追加跑分选优。

## 两个静态规则

`conditional_mux_wide` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_WIDE` 扩展现有条件锥：在原有纯区域、唯一用户、非物化、无 event／别名／跨区域逃逸证明之下，允许 concat、assign、静态／动态 slice 的 word lowering 进入私有分支。位宽固定不超过 4096，分支预算仍为 16–256 个 op。沿用原 word emitter 的截断、部分末字和越界语义，不重新实现索引公式。

实际命中 root 4333 的 6 个宽操作：三组 concat／slice，包括两份 2048-bit counter view 和一份 1024-bit view。连同新纳入的私有 scalar 准备，true arm 从 19 个 op 扩到 40 个，false arm 仍为 30 个。两份等价 counter view 尚未合并；这次解决的是需求未成立时仍构造它们的问题，没有改变共享对象或用户集合。

`local_predicate_sets` / `WOLVRIX_GRHSIM_LOCAL_PREDICATE_SETS` 在原消费者位置将密集等值 OR 集合转换为无符号区间判断。它沿用此前 predicate-set 的固定门：至少 16 个不同常量，平均每个不回绕区间至少 8 个常量，最多 512 个叶子／2048 次访问；源宽 2–64 bit。源必须是输入或拥有独立 canonical 槽位的值，整个区域纯且顺序有效；signed、未知常量、稀疏集合及别名等情况回退。

这次不在调度前改图。现有持久译码缓存和条件锥保有其操作；其他 Boolean 叶子保留。仅删除已无生成代码用户的局部 Eq／OR／concat／ReduceOr，公开、跨区域、判变和打包输入仍保留。这样避免 TNO0017 中消费者化简同时破坏稀疏缓存、重建通知边界的问题，也不引入新的持久 one-hot 表。

实际命中 **10 个消费者**，涉及 810 个常量成员、64 个区间；不同消费者集合有重叠，810 不能当作删除的不同 Eq 数。两组 CSR 局部比较声明分别从 **170→141**、**170→16**。还留有其他用户或属于其他 lowering 的谓词，不能一并删除。

两项候选均保持原 IR、39 个区域、209 个 checked values，以及 bool/u8/u16/u32/u64 的 346/55/5/91/2 个槽位。原有持久共享译码和精确输入缓存站点一致。关闭新选项时，生成源码逐文件等于保留版。规则与限制见[功能文档](../../wolvrix/docs/emit/grhsim-consumer-structure.md)，运行前固定假设见[hypothesis.json](../../build/cv32e40p/consumer-structure-v2/hypothesis.json)，[结构核对](../../build/cv32e40p/consumer-structure-v2/structure.json)。

## 输入与功能验证

| 后端 | binary SHA-256 |
| --- | --- |
| 既有精确键缓存基线 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` |
| 宽值条件执行 | `0ab828142d89cda7efe198aa053e9890960644bb18b429c9e75b39806db2f853` |
| 局部译码消费者 | `f3e3118770f0072be4cb1441b083ad5dc7ce20463f9834ecf0ed8262af05612d` |
| 同归一化 RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

同一冻结图、CoreMark、harness、Clang 23.1.2 和 `-O3 -march=native`。模型在 node030 编译，只有两个独立新选项分别启用。源码、工具、选项和生成文件 SHA 见[build.json](../../build/cv32e40p/consumer-structure-v2/build.json)。宽值版发射／编译／链接约 2.162／20.497／1.353 秒，译码版约 2.261／20.559／1.282 秒，不计入运行时间。

四后端 smoke 和完整 CoreMark 的 UART、退出码、CRC、完成周期及逐周期总线 trace 一致；CoreMark 均为 **3,376,065 周期**，trace SHA 为 `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[功能门](../../build/cv32e40p/consumer-structure-v2/functional.json)。

两个独立诊断版本也通过相同 trace。与原版已有计数对比，**512 项可比计数全部相同**，包括区域执行、逐值比较／变化、缓存访问和条件分支。CSR root 4333 仍为 true 0 次、false 3,376,066 次；全部 scalar 检查仍为每周期 167.255326 次。新诊断器另有 16 项旧归档尚未提供的 deferred-OR 探针，单独保留，不将缺失的旧探针当作零。[诊断与计数一致性](../../build/cv32e40p/consumer-structure-v2/consumer-analysis.json)。

开发阶段修正了一个 operand span 生命周期错误：局部 use-count 分析曾从临时 `Operation` 取得 span，造成无用表达式消除误删 live 值。它在整机编译门被发现，`consumer-structure-v1` 保留失败日志且没有进入计时；修复后在新目录 v2 完成上述功能门和唯一正式测量。新增独立逻辑保留回归。测试 oracle 还将内部算术用例限制为合法位宽输入，直接输入的 spare-high-bit 检查另行保留。两项修正均发生在正式计时之前，不是按快慢调整候选。

## 测量结果

node030 CPU96、NUMA1、单线程、ASLR 关闭。四后端各预热一次，每样本完整重启一次 CoreMark；一组 8 轮正反序，全部 placement/locality 和功能门通过，attempt 均为 0，没有重试或删样本。sibling 活动由既有 runner 记录，没有改变其他进程。

| 后端 | 外部 walltime 均值 | 相对本轮保留版的配对变化 | 95% CI |
| --- | ---: | ---: | --- |
| 保留版 | 2.939055 s | — | — |
| 宽值条件执行 | 2.928914 s | −0.3434% | [−0.7410%, −0.0450%] |
| 局部译码消费者 | 2.931563 s | −0.2535% | [−0.6072%, +0.0527%] |
| Verilator | 2.824694 s | — | — |

宽值版 7/8 轮更快，仿真循环降低 0.3310%，CI [−0.6862%, −0.0477%]。译码版 6/8 轮更快，循环降低 0.3142%，CI [−0.5998%, −0.0320%]；但外部 walltime CI 跨零，不能将循环结果替代整机收益结论。两候选相对保留版的初始化比值 CI 均跨 1。

本轮保留版／Verilator 为 **1.040489**，CI [1.038431, 1.041966]；宽值版为 **1.036916**，CI [1.032484, 1.040650]；译码版为 **1.037850**，CI [1.034073, 1.041341]。这里仅比较同轮样本，不把历史轮次的绝对 walltime 差当作优化收益。[逐对数据](../../build/cv32e40p/consumer-structure-v2/pairs.csv)、[汇总](../../build/cv32e40p/consumer-structure-v2/summary.json)、[完整报告](../../build/cv32e40p/consumer-structure-v2/report.json)。

## 为什么结构改动只带来小幅收益

每后端一次独立 PMU 计数，包含初始化，不能用其主机周期差代替 8 轮统计：

| 每模拟周期 | 保留版 | 宽值条件执行 | 局部译码消费者 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| retired instructions | 10276.327 | 10273.859 | 10246.571 | 9799.121 |
| branches | 465.027 | 485.027 | 479.027 | 568.442 |
| branch misses | 1.263 | 1.225 | 1.264 | 0.877 |

**宽值版确实取消了未选分支的数组准备，但编译器重组了入口控制。** 原版 `0xbcab` 的一条 guard 分支之前，两份数组各 4 条向量清零 store 均为必经。新 ELF 的这些 store 位于 `0xbd7a` 开始的 true arm；直接 CFG 检查确认该入口只接收 guard 链的跳转，且它支配全部 8 条 store。结合相同谓词的精确计数，可以确认它们在本负载中不再执行。

同时，Clang 将原本的一条入口分支展开为 **14 条跳转到同一 true arm 的条件分支**。整个模型的 PMU 分支数增加约 20 次／周期，退休指令净减少仅 **2.468 条／周期（0.0240%）**。这说明移除准备工作后，其他比较和控制形态发生了变化，不能按删除的 C++ op 或 8 条 store 直接估算净收益；也不能把整机新增的 20 条分支全部归于这 14 条入口分支。

主 compute batch 2 的栈帧分配从 **2456 B 降到 1960 B**，但静态指令 8221→8252、函数字节 39563→39621。栈帧缩小与新控制形态同时出现；本轮没有分别隔离它们的时间贡献。两份等价 view 在选中分支内仍独立存在，也未宣称视图合并问题已全部解决。[逐指令与 CFG 证据](../../build/cv32e40p/consumer-structure-v2/consumer-analysis.json)、[反汇编](../../build/cv32e40p/consumer-structure-v2/machine-evidence/)。

**译码版删除了很多局部表达式，但其中一部分原本已被编译器合并或下沉到冷路径。** 两家族的独立比较声明共减少 183 条，scheduler C++ 从 1,024,938 B 减到 961,047 B；退休指令只净减少 **29.756 条／周期（0.2896%）**，同时分支增加约 14 次／周期。compute batch 1 的静态指令反而 2267→2326，batch 2 为 8221→8199。这与 TNO0028 的限制一致：源码谓词数量不是每周期执行比较数量。

这次消除了原先“改消费者就改变调度／缓存”的问题，512 项行为计数保持一致，说明收益没有依赖调度边界变化。剩余限制则在局部表示本身：相互重叠的消费者仍分别生成区间条件，编译器会重新分配比较、分支和临时值。这个证据值得记录，但本轮不据此追加表示、阈值或组合搜索。

两条规则都只依赖静态用途、类型和集合，因而也可能作用于 XiangShan 的宽 CSR view 与局部译码。是否命中、是否受公开值或跨区域用户限制，需要单独静态审计；本轮未运行 XiangShan，也不外推其性能。

## 验证与复现

两项新 CTest 与相关 conditional-mux、input-cache、shared-equality-family、local-equality-decode 回归通过，共 6 个目标。生命周期修复后重新运行受影响的局部谓词目标并通过。生成代码使用 Clang O0／O3，O3 带 ASan/UBSan；覆盖 held-clock 更新、重新初始化、动态 slice 边界、公开宽值、effect／预算回退、共享谓词、多源、完整域、输入存储高位和 64-bit 两端。18 项相关 Python 测试通过。`py_compile`、两仓 diff、文档链接、冻结源码和统计一致性检查通过。[验证汇总](../../build/cv32e40p/consumer-structure-v2/validation.json)。

在 node030 仓库根，用新目录复现当前两条固定规则：

```bash
python3 scripts/cv32e40p_consumer_structure_compare.py build --output build/cv32e40p/consumer-structure-reproduce
python3 scripts/cv32e40p_consumer_structure_compare.py verify --output build/cv32e40p/consumer-structure-reproduce
python3 scripts/cv32e40p_consumer_structure_compare.py measure --output build/cv32e40p/consumer-structure-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_consumer_structure_compare.py diagnose --output build/cv32e40p/consumer-structure-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/consumer-structure-reproduce \
  --backend grhsim_conditional_wide --output build/cv32e40p/consumer-wide-counts-reproduce --detailed
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/consumer-structure-reproduce \
  --backend grhsim_local_predicate_sets --output build/cv32e40p/consumer-predicate-counts-reproduce --detailed
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_consumer_structure_analysis.py --source build/cv32e40p/consumer-structure-reproduce \
  --counts grhsim_conditional_wide=build/cv32e40p/consumer-wide-counts-reproduce \
  --counts grhsim_local_predicate_sets=build/cv32e40p/consumer-predicate-counts-reproduce
```

实现、测试和报告留在当前调查分支；未提交或 push。原保留配置、跨区域接口和全局默认均未修改。
