# TNO0419：CSR-only 结构恢复与验证进度

日期：2026-11-04。状态：完整构建和结构检查通过，第一组有效轨迹通过，第二组进行中。

承接 [TNO0418](./TNO0418_decode_table_csr_only_setup_20261104.md)。当前E保留CSR布尔
位图／寄存器值约束，关闭动态输入的恒定表提前折叠，普通常量输入求值不变。

## 图与代码一致性

E/B的pre_reg_to_mem.json均为3,282,110,410字节，SHA256完全一致；62个kDecodeTable
保留，恒零索引表恢复原动态依赖。全部129个生成C++文件、状态声明和活动调度统计
与B逐字节一致。runtime header仅CSR helper变化，E的helper与组合版C相同。

编译后129个对象中128个.text完全相同，仅grhsim_SimTop_sched_17.o改变，
.text由772,127变为772,131字节（+4）。完整ELF.text由70,407,072变为70,407,088字节
（+16，包含链接布局影响）。因此E/B是一项干净的CSR发射消融，不含恒定表消除
造成的图、调度或存储布局变化。E/C仍包含这些变化。

## 正确性

两张真实fixture用原始两组固定输入复验通过：恒零索引表E.text与B一致，CSR
权限表E.text与C一致。native decode-table/CTZ两项测试通过，其中普通常量输入的
折叠、CSE/DCE及布尔边界测试继续生效；动态恒定表则明确要求保留输入依赖。

整机三版smoke均通过，单线程CPU96、NUMA node1、CPU288空闲检查通过。
E的第一组C100000有效DiffTest记录分别与B/C一致，第二组seed1继续运行；随后
分别预热和既定八轮三版正式计时。诊断时间不进入walltime样本。

## 证据

产物根目录：`build/xs/decode_table_csr_only_20261104_v1`。
`ablation_structure.json`、`object_text_comparison.json`、`csr_machinecode.json`
记录结构及汇编；`graph_check.json`记录图哈希。构建和验证日志位于
`wolvrix/build/artifacts/decode-table-csr-only`，正式结果继续独立追加。
