# TNO0317: XiangShan perf print current-counter experiment

日期：2026-09-15

状态：`EXPERIMENTAL SOURCE CHANGE; RTL/ASC/RUNTIME NOT REGENERATED`。

## 1. 授权与修改

承接 [TNO0316](./TNO0316_xiangshan_repcut_debug_grouping_memory_bridges_20260914.md)，
用户明确要求先做最简单、允许略微改变打印行为的实验：将 XSPerfPrint 的 next_counter
改为 counter。本轮只修改
[`PerfCounterUtils.scala`](../../testcase/xiangshan/utility/src/main/scala/utility/PerfCounterUtils.scala)
中 XSPerfAccumulate.collect 的第 79 行：

```diff
- XSPerfPrint(curMod)(perfDump, p"$perfName, $next_counter\n")
+ XSPerfPrint(curMod)(perfDump, p"$perfName, $counter\n")
```

修改所在 utility 子仓库 HEAD 为 `1db5122533808bcde35c1f4c8bbc62c99777e292`；
保留为未提交的实验工作树修改。不添加开关，不改分组大小，不叠加此前 selector/write-pack
实验，也不修改另一份 playground 工程。

## 2. 行为差异

- `next_counter := counter + perfCnt` 和 `counter := Mux(perfClean, 0.U, next_counter)`
  保持不变，累计状态和 clean/reset 更新逻辑不变。
- dump 打印改为更新前的寄存器值，不再包含本拍 perfCnt。例如旧值 10、本拍事件 3 时，
  旧打印为 13，新打印为 10；若不 clean，二者下一状态都为 13。
- clean 与 dump 同拍时，新打印仍是更新前值，并非本次 clean 后的 0；下一状态清零。
- 打印格式、触发条件和批量分组保持不变；其他 counter/histogram 实现不变。

预期是让这一类累加器的打印数据依赖在 RegisterRead 截止，而不通过 next_counter 继续
追到本拍事件。计数器 writer 自己仍然依赖本拍事件，其他打印表达式/断言和 memory 路径
也仍存在；不能据源代码改动断言 giant ASC 已拆分。

## 3. 检查与未做事项

通过 `git diff --check`；精确比对 utility HEAD，确认文件差异严格只有上述一次打印参数
替换，其他代码逐字不变。本轮未编译/重新生成 RTL、GRH 或分区，也未运行功能/性能测试。
已有冻结 O/A/B/AB 产物仍是修改前版本，不应用它们报告本候选结果。
后续需要从本修改重新生成产物并重算 ASC，才能验证结构收益。
