# TNO0409：译码表常量依赖消除与布尔位图 lowering 调整

日期：2026-11-03。状态：实现与 native 测试通过，真实表复验和整机生成进行中。

## 实现

根据 [TNO0408](./TNO0408_decode_table_regression_mechanisms_20261103.md) 的两个退化机制，本轮调整 Wolvrix 的生成流程。

1. `decode::constantOutput` 检查所有行的确定性输出（value & care）与默认输出相同。
   这是对首项优先和约束合并两种模式都成立的充分条件。const-fold 在二态模式中无需
   等输入成为常量即可替换表操作，消除输入依赖，保留原源码位置和变换标记。
   这不是完整的表等价化简算法；默认输出不同、遮蔽项等复杂情况仍保守保留。
2. 1 位输出且完整真值表不超过 64 位时，直接发射寄存器位图。一般性规则由
   “整个函数可放进一个机器字”确定，不按模块名或已测速度选择。
   Clang/x86-64 下，对不足 32 位的标量输入，在提取位图索引前加入非 volatile 的
   空 asm 寄存器值约束。它没有 memory clobber、没有额外内存访问、没有隐藏状态，
   让编译器保留窄输入读取所需的全值。其他编译器／架构使用普通可移植位图表达式。

仅把参数改成 uint8_t 或显式写 shift/bitset，当前 Clang 在真实生成代码中仍会
将 byte load 扩宽，已保存对照汇编；寄存器约束版本生成 movzbl。没有把诊断用的
volatile 内存读取加入生产，也没有改动生产优化选项。

## 验证

新增 native 测试覆盖：动态输入上的常量表、默认值差异拒绝、部分 care、宽输出、
空行表、约束合并、常量来源保持和折叠后活动 mask 为零。布尔 lowering 覆盖
1 位、5 位、6 位（64 项边界）、65 位稀疏输入的位图计算。

native decode-table／CTZ 两项测试通过，10 项 Python／frontend／普通 DPI 相关测试通过。
24 张实际表从前一轮冻结 RTL 重新导入和生成，复用同一组验证向量；当前已确认
恒零 indexedLSUopTable 的 kDecodeTable 从 1 个变为 0 个。局部及整机性能尚无结论。

## 冻结与测量

修改仅在后端；已逐文件核对 XiangShan／utility／DiffTest 源码与上一轮完全一致，
并验证冻结的 RTL 和 DiffTest 生成文件身份。整机复用这些 Chisel 生成结果，从
RTL 重新执行前端、变换、活动调度和 C++ 编译。新工具绑定和共享库单独冻结。

目录：`build/xs/decode_table_tuned_20261103_v1`。
三组版本：A=原硬件实现，B=上一版 intrinsic，C=此次调整后的 intrinsic。
原 A/B binary 冻结，C 重建；同场测量各 8 次 C100000，以成对反转顺序平衡时间趋势。
新 C 用两组固定种子的有效 DiffTest 轨迹与前一轮已验证的 A/B 逐条比较。
重用原轨迹前核对 binary、负载、NEMU、schema、运行依赖库身份。

编译可用 node030 任意核；正式测量固定 CPU96／NUMA node1、单线程、SMT sibling
空闲检查，文件页和匿名页均在运行中核验。正式测量不并行构建。
24 张表的局部新旧 intrinsic 也各输入分布做 8 对，在整机测量后运行。

## 入口

```bash
python3 scripts/decode_table_tune.py build \
  --source build/xs/decode_table_20261103_v3 \
  --output build/xs/decode_table_tuned_20261103_v1 --jobs 32
python3 scripts/decode_table_tune.py measure \
  --source build/xs/decode_table_20261103_v3 \
  --output build/xs/decode_table_tuned_20261103_v1
python3 scripts/decode_table_tune_local.py \
  --cases wolvrix/build/artifacts/decode-table-study/field-layout-v4/cases.json \
  --output wolvrix/build/artifacts/decode-table-tune/local-v1
```

工具构建、native／Python 测试、C++ 表达式汇编试验及局部重建证据在
`wolvrix/build/artifacts/decode-table-tune`。进度继续以独立 TNO 记录追加。
