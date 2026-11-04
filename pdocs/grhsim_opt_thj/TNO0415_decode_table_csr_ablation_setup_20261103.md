# TNO0415：CSR 布尔 lowering 移除的单项消融

日期：2026-11-03。状态：实现完成，工具已重建，完整模型生成和针对性验证进行中。

## 范围

用户要求移除 CSR 对应优化，观察上一轮整机回退是否来自这一项。承接
[TNO0414](./TNO0414_decode_table_tuned_local_results_and_conclusion_20261103.md)，
本轮撤回 `decode_table.hpp` 中一位输出、至多六个有效输入位的专用布尔位图分支，
包括 Clang/x86 空 asm 寄存器值约束，恢复原结果池＋索引 LUT 发射路径。

常量表 `constantOutput` 判定、动态输入的二态常量折叠、来源保留均不改动。
没有按 CSR 模块名做特判；该通用分支在这组真实表中只改变 CSR 权限表。
设计侧 Chisel、RTL、替换范围及生产编译选项保持原样，默认开关仍为 none。

## 对照定义

- B：原有 decode-table intrinsic，两项后续优化均无。
- C：上一轮组合版，常量依赖消除＋布尔位图／读取约束。
- D：本轮消融版，只有常量依赖消除，CSR 恢复原 lowering。

B/C 冻结 binary 重新同场测量，D 从同一份经身份核验的 RTL 完整导入、变换、调度、
生成与编译。预期 D/C 的 IR、调度和存储布局相同，只改一个 helper 的 lowering；
生成后逐项检查，不能只依据预期认定消融干净。D/B 则还包含常量消除带来的布局变化。

## 验证与测量

native decode-table/CTZ 回归继续执行；布尔表测试保留数值边界与稀疏宽输入，
将预期代码形态改回 LUT。恒零表和 CSR 两张真实 fixture 用原固定向量复验，
分别检查常量依赖仍消除、CSR 机器码恢复旧版。

D 两组各 C100000 运行 NEMU/DiffTest，并分别和已核验身份的 B/C 有效轨迹比较。
三个版本依次 smoke/预热，然后预先固定八轮顺序：BCD、DCB、CBD、DBC、BDC、CDB、BCD、DCB。
每版八次 C100000，合计24次；主指标 Host time spent，记录外部 walltime。

继续使用 Wolvrix 专用单模型单线程流程，node030 CPU96、NUMA node1、CPU288 空闲检查。
本地 emu/NEMU/库副本预取，运行中检查页面归属与线程亲和性；正式计时关闭诊断和轨迹，
所有本实验构建结束后才开始。不会按速度删样或提前终止。

## 入口与产物

```bash
python3 scripts/decode_table_ablation.py build   --source build/xs/decode_table_20261103_v3   --output build/xs/decode_table_ablation_20261103_v1 --jobs 32
python3 scripts/decode_table_ablation.py measure   --source build/xs/decode_table_20261103_v3   --tuned build/xs/decode_table_tuned_20261103_v1   --output build/xs/decode_table_ablation_20261103_v1
```

完整产物位于 `build/xs/decode_table_ablation_20261103_v1`。变更前源码备份、精确diff、
构建／回归／局部模型日志在 `wolvrix/build/artifacts/decode-table-ablation`。
继续以新 TNO 记录构建一致性、有效轨迹与最终 walltime，不覆盖历史结论。
