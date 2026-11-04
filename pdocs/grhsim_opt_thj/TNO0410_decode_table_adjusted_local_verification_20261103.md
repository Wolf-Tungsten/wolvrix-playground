# TNO0410：调整后 24 张译码表的功能复验与机器码核对

日期：2026-11-03。状态：局部构建、功能复验与结构检查完成；性能测量待整机构建结束后串行进行。

## 固定输入的局部复验

承接 [TNO0409](./TNO0409_decode_table_lowering_adjustments_20261103.md)，本轮重新导入
上一轮每张真实表的 intrinsic RTL，不重新选择表或输入，也不修改任何设计侧调用。
新局部目录为 `wolvrix/build/artifacts/decode-table-tune/local-v1`。

24 张表全部构建成功；每张表的旧 intrinsic 与调整版均通过两组原始验证向量。
小表仍使用输入空间穷举，大表沿用原始固定种子及逐行定向样本；主 DecodeUnit
每组 102,990 个向量。期望值和 care 仍来自原表解释器。原硬件 Verilator 及原
GrhSIM 的验证证据沿用前一轮相同向量的结果，没有将旧、新 intrinsic 相互一致
当成唯一的正确性依据。

本目录的 A/B 分别表示旧 intrinsic 与调整版；与原研究中 A=原硬件、B=intrinsic
的标签含义不同。两组输入的路径、SHA256、日志及模型身份均保存于各案例目录。

## 恒零索引表

`03_indexedLSUopTable` 的动态输入为 4 位，每组穷举 16 个值。调整版中的
`kDecodeTable` 从 1 个变为 0 个，输出为常量，调度不再因输入变化触发表计算。
这是表语义的充分条件检查生效，不是针对 uopIdx=0 的实例名特判。

该案例 ELF `.text`（包括公共计时／验证 harness）从 2,649 字节变为 2,637 字节。
局部源码可直接比较旧目录的 `B/model` 与本轮案例的 `B/model`。

## CSR 权限表

`16_PrivilegePermitModule` 为 5 位输入、1 位输出，每组穷举 32 个值。正式 lowering
发射位图 `0x31f071`，Clang 生成的计算主体为：

```asm
mov    $0x31f071, %ecx
movzbl (%rdi), %eax
bt     %eax, %ecx
setb   0x1b(%rdi)
```

原 intrinsic 中的 `mov (%rdi), %eax` 被字节读取替代。寄存器值约束本身不生成
指令；没有使用诊断模型中的 volatile 内存读取。完整 ELF `.text` 从 2,659 字节
变为 2,660 字节，增加来自窄读指令编码，不能把“代码更大”直接解释成运行更慢。
真正的局部时延留待测量，不使用汇编长度替代运行证据。

## 其余案例与控制范围

全部 24 张表中，22 张的 ELF `.text` 与旧 intrinsic 逐字节一致；只有上面两张改变。
生成的 `.cpp` 逐字节相同者为 13 张，其余一些差别不产生机器码差异。
本轮仍对全部 24 张表做同样的 8 对、多分布、kernel/full 复测，保留波动和退化结果。

结构清单：`wolvrix/build/artifacts/decode-table-tune/local-structure.json`。
各案例 `B/assembly.log`、`B/symbols.log` 与 A/B `text.bin` 保存对应机器码和段身份。
独立 `.text` 比较只说明代码段相同，不是整机状态布局或运行成本等价证明。

整机调整版正在从冻结 RTL 完整重新导入、化简和调度。正式计时继续固定 node030
CPU96、NUMA node1，完成构建后才开始。局部结构改善不预先推断整机收益。
