# TNO0418：恢复 CSR 优化并关闭恒定表提前折叠

日期：2026-11-04。状态：实现和工具重建完成，针对性验证及完整模型生成进行中。

## 用户要求与范围

承接 [TNO0417](./TNO0417_decode_table_csr_ablation_results_20261104.md)，本轮恢复上一轮
撤回的 CSR 对应布尔位图和 Clang/x86 寄存器值约束，再禁用恒定译码表的提前折叠。

关闭范围仅是新加入的“输入仍为动态值时，判定整表输出恒定并消除依赖”的优化。
原有常量输入求值、其他操作的常量传播、CSE、DCE和普通组合优化继续保留。
具体撤回 const_fold.cpp 的动态 kDecodeTable 特例、常量门槛豁免和对应来源标记处理，
不是关闭整个 const-fold pass。constantOutput 的纯分析函数保留作独立语义测试。

当前代码恢复到仅 CSR 优化的 E 状态；没有修改 Chisel 或调用范围，也没有修改默认
SLP和其他生产编译选项。decode-table 默认开关仍为 none。

## 同场对照

- B：旧 intrinsic，无两项后续优化。
- C：常量表提前折叠＋CSR 布尔优化。
- E：只保留 CSR 布尔优化，禁用恒定表提前折叠。

E/B 用来隔离 CSR 优化在原有后端布局上的效果；E/C 用来观察关闭恒定表优化及其
调度布局影响。预期 E/B 的 GRH、调度、存储布局、生成C++主体相同，仅 runtime
header 的 CSR helper 不同，构建完成后严格验证，不直接假定。

B/C 冻结二进制同场复测，E 从相同哈希核验的 RTL 和 DiffTest 生成源码完整重建。
两张真实 fixture 复验：恒零表应恢复 B 的动态依赖／机器码，CSR 应维持 C 的机器码。
native 测试同时确认普通常量输入折叠继续工作，布尔位图边界和动态恒定表保留符合当前状态。

## 性能与功能

先验证 E 两组各 C100000 NEMU/DiffTest 有效轨迹，分别与 B/C 比较。再分别 smoke／
预热，执行八组三版轮换，顺序固定为 BCE、ECB、CBE、EBC、BEC、CEB、BCE、ECB。
每版八次 C100000，共24次。主指标 Host time spent，记录外部 walltime。

专用单模型单线程，node030 CPU96、NUMA node1、CPU288空闲检查；复制并预取
emu、NEMU和依赖库，运行中核验文件页、匿名页及线程亲和性。正式计时不带诊断／轨迹，
所有本实验构建结束后才运行。保留所有样本，不按速度挑选。

## 入口与记录

产物：`build/xs/decode_table_csr_only_20261104_v1`；新模型为 E。
实施证据：`wolvrix/build/artifacts/decode-table-csr-only`，包含变更前源码与精确diff。
入口：`scripts/decode_table_csr_only.py build|measure`；结构检查：
`scripts/decode_table_csr_only_evidence.py`。

```bash
python3 scripts/decode_table_csr_only.py build --source build/xs/decode_table_20261103_v3 --output build/xs/decode_table_csr_only_20261104_v1 --jobs 32
python3 scripts/decode_table_csr_only.py measure --source build/xs/decode_table_20261103_v3 --tuned build/xs/decode_table_tuned_20261103_v1 --output build/xs/decode_table_csr_only_20261104_v1
```

不重复24张表的全部局部计时，本次重点是互补消融和整机证据。验证、结构检查和
完整性能结果继续新建 TNO，历史记录不覆盖。
