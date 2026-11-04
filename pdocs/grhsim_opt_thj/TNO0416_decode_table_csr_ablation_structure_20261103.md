# TNO0416：CSR 消融结构一致性与整机验证进度

日期：2026-11-03。状态：完整构建与结构 gate 通过，smoke 通过，两组有效轨迹检查进行中。

承接 [TNO0415](./TNO0415_decode_table_csr_ablation_setup_20261103.md)。B=旧 intrinsic，C=上一轮组合版，D=只保留常量折叠的消融版。

## 单变量检查

以下所有检查均通过：

- C/D 的 `pre_reg_to_mem.json` 为 3,282,075,811 字节，SHA256 完全一致。
- C/D 的全部 130 个生成 `.cpp` 文件逐字节相同。
- `grhsim_SimTop.hpp` 相同，状态和临时值布局没有变化。
- `activity_schedule_supernode_stats.json` 相同，调度分组及依赖不变。
- `grhsim_SimTop_runtime.hpp` 只有 CSR helper 不同。
- D 的 CSR helper 与 B 完全一致，恢复统一 LUT 发射；没有额外 asm 值约束。

因此 C/D 是干净的发射层消融。B/D 的差异仍包含常量折叠导致的图和调度变化。C++ 编译后的寄存器分配、代码长度和布局可能随着 helper 改变，不能进一步声称只差一条机器指令。

## 小模型与构建

恒零表两组穷举各16个输入通过，D `.text` 与 C 完全相同；CSR 两组穷举各32个输入通过，D `.text` 与 B 完全相同。native decode-table 和 CTZ 两项测试均通过。

整机从同一份经哈希验证的 Chisel 生成 RTL 重新导入、变换、调度和编译。常量折叠实现逐文件哈希核验没有变化。没有修改生成 Makefile 的优化选项，仍为默认 SLP、`-O3 -march=native`。

| 版本 | ELF .text 字节 |
|---|---:|
| B | 70407072 |
| C | 70459629 |
| D | 70477117 |

## 运行进度

B/C/D 的 C10000 smoke 均通过。均固定 node030 CPU96、单线程、NUMA node1，runtime 页面与 sibling 检查通过。D 两组 C100000 轨迹比较继续进行；完成后分别预热并执行既定八轮三版 walltime。

产物：`build/xs/decode_table_ablation_20261103_v1/ablation_structure.json` 保存全部哈希、二进制身份、ELF 段大小和 gate 结果。原始日志在 `wolvrix/build/artifacts/decode-table-ablation`。完整性能结果另行追加，不以 smoke 推断性能收益。
