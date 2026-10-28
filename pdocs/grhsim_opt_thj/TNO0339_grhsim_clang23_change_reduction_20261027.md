# TNO0339：自动初解暴露的 Clang 23 变化归约错误

日期：2026-10-27。上游流程见 [TNO0338](./TNO0338_grhsim_automatic_rtl_flow_20261027.md)。

## 复现与定位

同一份自动初解在 N=1 和 N=32 都于 cycleCnt=18338、instrCnt=11251 触发相同 NEMU PC mismatch。关闭 input bit activation/dirty tracking，乃至使用后端默认选项，均在同一点失败。因此这些可选优化和线程竞争不能解释该错误。

仅在诊断副本强制普通 compute seed、保留 event/commit 行为后，C30000 通过。自动二分把最小强制范围缩小到一个计算组。随后加入纯组合表达式一致性检查，首次在 step24444 检出：索引由 172 改为 180 后，一个 equality 的保存值已经改变，但下游 AND 未被激活，仍保留旧结果。

生成源码包含正确的 change 累积和 active OR。抽出独立、无分区/信号名称的小程序后，Clang 23.1.2 `-O3 -march=native` 同样失败：`from=0,to=172,changed=1,flags=0`。机器码将一个 scalar bool store 放到了仍需要旧值的 vector load 之前；变化归约因此丢失该项。

## 有效验证

- 独立 fixture 覆盖 512×512=262144 个旧/新索引组合。
- 原始 Clang 23.1.2 native O3/O2 失败；`-fno-slp-vectorize` 通过。
- 只将定位到的诊断对象改为 O0 或 O3/no-SLP，完整 C100000 均通过，PC/提交指令数/周期数与参考匹配：instrCnt=240349、cycleCnt=99996、guest=100001。
- 此单对象替换只用于证明原因，不是最终优化或交付构建方式。

## 通用修正

[`grhsim_compiler_compat.hpp`](../../wolvrix/lib/emit/grhsim_compiler_compat.hpp) 对 Clang 23 的 x86 编译追加 `-fno-slp-vectorize`，保留原有 LLVM21/SSE2 保护。规则只检查编译器和目标架构，不检查分区、信号或 RTL 名称。

新增 [change-reduction fixture](../../wolvrix/tests/emit/data/grhsim_clang_change_reduction.cpp)，兼容测试分别以 GCC、Clang 和实际 native 编译选项执行。自动驱动直接编译对象，因此也必须读取同一兼容规则；新增编译前 fixture 运行及编译器、规则、fixture 的身份记录，避免绕过生成 Makefile 的保护。

本轮完整模型所有对象统一按兼容规则重建；不采用只改一个分区/对象的方式。原无保护 binary/archive 与失败记录保存在 `build/grhsim_auto_flow_20261027_allcores/initial/invalid_compiler_build` 和 `reference_vs_initial_invalid_compiler`。恢复版锚点未覆盖。

关闭 SLP 可能影响运行性能，所以后续与恢复版的比较是完整自动构建路线的比较，不能把全部差异归因于划分。自动迁移前后的两条新线则使用相同编译兼容规则。当前记录不宣称性能收益。
