# TNO0035 after seed1 的 Clang 23 向量掩码错误定位

## 结论

[TNO0034](./TNO0034_after_retry_difftest_rejection_20261111.md) 的可重复失败已定位为 **Clang 23.1.2 的 x86 向量掩码代码生成错误**。新 seed1 分区、生成 C++、harness、CoreMark 和 NEMU 均保持冻结；故障集中在 `grhsim_Gpart_2_model_sched_77.o`。

最强的对照是：仅把这个对象中的一条 `kshiftrw` 改成 `kshiftrb`，`.text` 只变化 **1 字节**，独立 C++ 测试与完整 100k DiffTest 都通过。该修改仅用于根因证明，没有进入 emitter、默认编译选项或正式 retained binary。

这次与此前 [TNO0339](../grhsim_opt_thj/TNO0339_grhsim_clang23_change_reduction_20261027.md) 属于同一工具链的向量化相关错误，但**已证明的具体机制不同**：旧例是 store 提前于旧值读取，导致变化归约丢失；这次是掩码位宽处理错误，导致数据选择错误。不能把它们写成已经确认的同一个 LLVM 缺陷。

## 编译对照与对象二分

执行环境仍是 node030，完整模型使用 CPU96–127、NUMA1 strict membind、`setarch -R`、32 个 worker 和完整 DiffTest。源文件均从原 seed1 package 读取；只使用独立诊断输出目录。模型编译参数为 `-std=c++20 -O3 -march=native -pthread`，`-march=native` 在本机对应 `znver4`。

先用全部原始对象和原 harness 对象重新链接，得到与原失败 binary **完全相同的 SHA256**：

```text
608eb217d01c7d68e85e9c8a76071af9ac75addbd27a300a084648c01e172c61
```

该 binary 再次在 guest=95,577、PC=`0x800010de` 失败，`a4` 为 `0x42`，NEMU 为 `0x80003cc0`。这也验证了诊断链接流程本身没有引入差异。

随后在 9,208 个模型对象之间二分替换，19 次组合验证定位到 partition 2 的 compute batch 77。两个方向都验证了：其余对象均 no-SLP 时，只换回这个原对象便失败；其余对象均原版时，只替换这个对象便通过。

| 模型对象变化，harness 始终保持原对象 | 100k DiffTest |
| --- | --- |
| 全部原始 Clang 23 `-O3` | 相同位置失败 |
| 全部模型加 `-fno-slp-vectorize` | 通过 |
| 仅 `sched_77.o` 使用 Clang 23 `-O3 -fno-slp-vectorize` | 通过 |
| 仅 `sched_77.o` 使用 Clang 19.1.1 `-O3` | 通过 |
| 仅 `sched_77.o` 使用 Clang 23 `-O0` | 通过 |
| 仅修正 `sched_77.o` 的一条掩码右移指令 | 通过 |

所有通过的完整运行均为：PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995、guest=100,001，DiffTest=on，终止于周期上限，workload 输出相同。所有失败组合均重现原 `a4` 差异。合计 **23 次完整模型诊断，9 次通过、14 次预期失败**。

## 独立复现与机器码证据

从 batch 77 抽出 supernode 546，移除 XiangShan、NEMU、分区调度及多线程运行环境，只保留标准 C++ 容器、标量表达式和两个小型 helper。所有字段先做值初始化。独立测试中，Clang 23 `-O3 -march=native` 失败，Clang 19 和 Clang 23/no-SLP 均通过 2,864 个状态转换检查。

进一步保留一个固定输入，得到不依赖项目头文件的 [复现包](../../build/artifacts/repcut-after-clang-diagnosis-20261111/reproducer/README.md)：

```text
Clang 23 O3:       pred1=1 pred9=0 output9=1 expected=0
Clang 23 no-SLP:   pred1=1 pred9=0 output9=0 expected=0
Clang 19 O3:       pred1=1 pred9=0 output9=0 expected=0
```

对应原模型位置是 `value_bool_slots_[5866]`、`value_u8_slots_[6806]`；后者对应整数 issue queue `issueQueueALU3_AluBkuVset` 的 entry 9 数据来源选择。谓词 `pred9` 本身已经正确算成 0，但后续向量 select 错误选中了值 1。

原 LLVM IR 对 8 个谓词执行如下操作，最后一项被显式覆盖：

```text
shifted = shuffle <8 x i1> predicates [1,2,3,4,5,6,7,poison]
selected = insert shifted, last_predicate, lane 7
result = select selected, ones, fallback
```

x86 lowering 使用了更宽的 AVX-512 掩码寄存器。捕获实际寄存器值后，问题可直接计算：

```text
captured_mask       = 0xff01
valid_low8          = 0x01
(mask >> 1) & 0xff  = 0x80  # 按 16 位右移，bit 8 进入有效 bit 7
(mask & 0xff) >> 1  = 0x00  # 按 8 位右移的正确结果
last_predicate     = 0
```

随后 `kshiftlb` / `korb` 用 OR 插入最后一个谓词，却没有清除已经进入 bit 7 的错误位。插入 0 时，错误的 1 被保留下来。因此此次不是源 C++ 的结果计算顺序错误，也不是只有 activation 标志丢失。

诊断修改仅为：

```asm
kshiftrw $1, %k1, %k0   # 原版，16 位
kshiftrb $1, %k1, %k0   # 诊断修正，8 位
```

原对象 `.text` 中指令起点为 `0x14be`；字节偏移 `0x14c0` 从 `f9` 变成 `79`，其余 `.text` 字节完全相同。该单字节修正让全部 2,864 个独立检查和完整 100k DiffTest 通过。原 LLVM IR、汇编、两侧反汇编与逐字节比较均保留。

## 与历史问题及分区选择的关系

旧 change-reduction fixture 也已用当前编译器重跑：Clang 23 仍在 `from=0, to=172, changed=1, flags=0` 失败；Clang 19 和 Clang 23/no-SLP 均通过 262,144 个转换。旧问题并未消失，但不能代替本次根因定位。

新 assignment 改变了计算分组、存储布局和生成 C++ 的形状，本次触发了错误的向量掩码 lowering。原 seed7 在当前负载通过，不能据此推断 Clang 23 对新分区也安全；`km1` 更低同样不能替代功能验证。本次已经定位到编译错误，不应把该失败直接归因于分区算法的语义错误。

当前不改变默认编译优化，不将混编或机器码诊断补丁作为正式性能构建。旧 seed7 retained 保留；新 seed1 原 binary 仍是功能拒绝产物。后续若继续测量，需要先确定并统一可通过功能门的编译策略，再重新进行正式 AB/BA。本记录的有效性能样本数是 **0**，不从诊断运行耗时作速度结论。

## 产物和验证

- [机器可读报告](../../build/artifacts/repcut-after-clang-diagnosis-20261111/report.json)、[证据校验结果](../../build/artifacts/repcut-after-clang-diagnosis-20261111/verification.json)、[校验脚本](../../build/artifacts/repcut-after-clang-diagnosis-20261111/report.py)。
- [编译对照入口](../../build/artifacts/repcut-after-clang-diagnosis-20261111/diagnose.py)、[对象二分入口](../../build/artifacts/repcut-after-clang-diagnosis-20261111/bisect_objects.py)、[19 次二分记录](../../build/xs/repcut-after-clang-diagnosis-20261111/object-bisect/trials.json)。
- [单对象编译器对照](../../build/xs/repcut-after-clang-diagnosis-20261111/single-object-controls/complete.json)、[原始 LLVM IR](../../build/xs/repcut-after-clang-diagnosis-20261111/single-object-controls/clang23-o3/model.ll)、[原始汇编](../../build/xs/repcut-after-clang-diagnosis-20261111/single-object-controls/clang23-o3/model.s)。
- [掩码捕获](../../build/xs/repcut-after-clang-diagnosis-20261111/mask-capture/result.json)、[机器码逐字节差异](../../build/xs/repcut-after-clang-diagnosis-20261111/mask-width-control/text-differences.json)、[单字节修正运行](../../build/xs/repcut-after-clang-diagnosis-20261111/mask-width-control/result.json)。
- [原指令反汇编](../../build/xs/repcut-after-clang-diagnosis-20261111/mask-width-control/original-disassembly.txt)、[修正指令反汇编](../../build/xs/repcut-after-clang-diagnosis-20261111/mask-width-control/patched-disassembly.txt)、[完整运行日志](../../build/xs/repcut-after-clang-diagnosis-20261111/runs/)。

本轮只新增诊断产物和文档；Python 编译检查、证据一致性检查、相对链接检查及 `git diff --check` 通过。未修改生产代码，也未重跑与本轮无关的整套构建测试。
