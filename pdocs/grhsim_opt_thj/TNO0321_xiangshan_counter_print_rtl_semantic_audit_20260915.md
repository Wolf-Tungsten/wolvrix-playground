# TNO0321: XiangShan counter-print RTL semantic audit

日期：2026-09-15

状态：`BOUNDED RTL AUDIT PASS; PRINT GROUP ORDER NOT EQUIVALENT`。

## 1. 范围与工具

审计 [TNO0320](./TNO0320_xiangshan_counter_print_rtl_build_result_20260915.md) 的完整 RTL
差异，不修改原/new RTL。脚本与结果均在 `build/asc_counter_print_20260915/`：

- `compare_rtl.py` / `rtl_diff_v1/`：全文件集合与 SHA 差异。
- `audit_nonperf_rtl.py` / `nonperf_rtl_audit_v1.json`：非日志文件严格限定的全量归一化检查。
- `verify_log_endpoint.py` / `log_endpoint_verification_v2.json`：日志模块 token/alias 全量核验。

这是针对具体产物的机械检查，不是通用 Verilog 等价求解器或全芯片形式证明。

## 2. LogPerfEndpoint

新版相对旧版消除9,311条 next 值 wire 声明；9,311个对应 fwrite 操作数改为当前寄存器；
9,311处状态更新改为内联同一个加法表达式。声明减少不表示加法更新逻辑被删除。

核验将旧版打印参数替换为对应已声明的64-bit counter、将删除的 alias 在非打印位置展开，
再按完整条件组排序。排序保留每组的条件、全部字符串、打印参数和组内顺序。
归一化后双方2,421,025个 token 完全一致：包括其余 wire、寄存器、reset/clean/update、
打印 enable、未修改的 Max/Histogram 等。仅忽略字符串外空白及注释；字符串本身不改写。
模块没有 __LINE__/__FILE__/xs_assert，忽略注释不会遗漏其行号行为。

v1 审计没有放宽跨组顺序，故失败并保留 `log_endpoint_verification_v1.json`。
失败揭示788个条件组之间的重排；v2 明确按完整组配对后通过。Chisel 的
`tapInfos.groupBy(_.cond).values.foreach` 顺序在重新生成时改变。

因此不能称“所有日志顺序严格相同”：多个条件组同拍成立时，组间日志顺序可能不同。
但每个组内部的组成、条件和依赖未变，重排本身不增加/删除 ASC memory 桥梁。
目标语义变化仍是 dump 打印 C 而非 (C+E) mod 2^64；更新仍为 clean ? 0 : C+E。

## 3. 其余5个不同 RTL

| 文件 | 全量差异归因 |
| --- | --- |
| Ifu | 1个 wire 一一重命名；1处枚举合法性断言4个1-bit比较项重排 |
| PreDecode | 全部36 lane 各1个相同重命名及1处相同断言重排 |
| CommitIDModule | dirty 常量0→1，只进入初始版本打印 |
| NewCSR | gitDirty 常量0→1，wire 无其他使用 |
| SimTop | 开头5行 Git 注释删除，无受影响的文件/行号宏 |

Ifu/PreDecode 按限定替换归一化后整文件字节相同，断言合法集合/条件/打印/callback/行号均
不变；256组四态排列检查和8个故意破坏逻辑的负例通过。源 EnumUInt 使用 Java
getDeclaredMethods 顺序构造 values，assertLegal 将同一集合拼接比较零，解释了重排来源。

## 4. 对 ASC 结论的限制

可以继续比较稳定 memory symbol 的组件归属；非目标差异没有新增/删除 memory 依赖。
但数字 ID、临时名字、微小 node/weight 变化可能受等价重排或元数据常量影响，不能将所有
精确数值差都归因于打印优化。若要做严格单因素数值归因或 runtime，加对称 fresh control
或明确固定元数据/生成顺序；本阶段不声称日志字节流严格等价或 Host 加速。
