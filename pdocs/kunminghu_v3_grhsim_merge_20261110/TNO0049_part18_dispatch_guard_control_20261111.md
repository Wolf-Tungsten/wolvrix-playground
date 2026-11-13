# TNO0049：part_18 compute 调用前检查的对照

日期：2026-11-11（America/Los_Angeles）。[TNO0048](./TNO0048_part18_remaining_hotspots_20261111.md) 发现 part_18 的 59.26% compute batch 调用入口为空。本篇单独验证跳过这些空调用是否带来整机收益。

## 固定对象与唯一改动

A 为已启用向量掩码优化的冻结 after seed7、Clang 23 binary。B 复用相同 archive 和 harness，只替换 `grhsim_Gpart_18_model_eval.o`，给 335 个 compute 调用增加与 callee 一致的 active-byte mask 检查：

```cpp
if ((supernode_active_curr_[batch_word] & dispatch_mask) != 0) {
    this->eval_compute_batch_N();
}
```

此形态对应 emitter 现有 `compute_batch_dispatch_guard` 选项；本次只对 part_18 的冻结生成 C++ 做控制实验，不修改默认选项、不重新生成图、不引入计数或 perf 插桩。所有 batch 顺序、commit、reset、变化传播保持原实现。每次执行检查时读取当前活动位，保留前面 batch 产生的激活。

逐 archive member 审计共 **9,336 个对象**，仅上述 eval 对象不同；所有模型 header 和其余对象保持相同。两侧编译参数均为 Clang 23.1.2、C++20、`-O3 -march=native -pthread`，保留原对象对齐。

## 功能与运行门

node030、CPU96–127、NUMA1 严格绑定、ASLR disabled，32 个线程各固定一核；相同 performance/code-page/preload/thread-pinning 配置。未做外部 CPU 空闲准入检查。

两侧分别完成 10k smoke、100k 完整 DiffTest、预热，随后串行 8 对 AB/BA。**22 次全部通过**，没有拒绝样本。100k 功能签名与 TNO0048 相同；输入、NEMU、私有 runtime 文件身份、线程集合和 NUMA locality 均检查通过。计时不使用 TNO0048 的插桩版本或 perf 采样版本。

## 结果

负号表示 B 更快。使用固定 seed `20261102` 的 10,000 次配对 bootstrap。

| 指标 | A 均值 | B 均值 | 配对 delta 均值 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 14.282000 s | 14.269875 s | **−0.0308%** | **[−1.9574%, +1.5764%]** | 3/8 |
| 外部 walltime | 14.390997 s | 14.378393 s | **−0.0314%** | **[−2.0134%, +1.6168%]** | 3/8 |

Host 每对 delta 中位数为 +1.0550%。本窗口有波动，不能把不同日期的绝对值与 TNO0043 拼接对比。这里所有样本保留，没有按快慢筛选。

既有 phase timing 的 8 次中位数：

| 累计时间 | A | B |
|---|---:|---:|
| part_eval phase | 12.2300 s | 12.1447 s |
| part_18 eval | 9.2267 s | 9.2420 s |
| part_19 eval | 7.9502 s | 7.8141 s |

没有测出稳定整机收益，part_18 自身也没有显示明确下降。大量空调用本来只执行很短的活动判断，新增外层检查也有成本；仅凭 59.26% 的空调用比例无法判断其时间权重。本实验不排除更好的调度机制，但不支持现在默认开启 part_18 调用前检查。

## 处置与归档

保留控制 binary、原始日志和全部配对数据供复核；生产 emitter、默认配置及 retained binary 不变。下一优化入口回到 TNO0048 已定位的宽 concat/归约和短条件复用。

- [机器可读报告](../../build/artifacts/repcut-part18-20261111/guard-report.json)
- [唯一对象变化审计](../../build/xs/repcut-part18-20261111/guard/archive-audit.json)、[源码与掩码审计](../../build/xs/repcut-part18-20261111/guard/source-audit.json)
- [8 对 summary](../../build/xs/repcut-part18-20261111/measure-guard/summary.json)、[CSV](../../build/xs/repcut-part18-20261111/measure-guard/pairs.csv)、[逐对 JSON](../../build/xs/repcut-part18-20261111/measure-guard/pairs.json)、[功能门](../../build/xs/repcut-part18-20261111/measure-guard/functional.json)
- [构建脚本](../../build/artifacts/repcut-part18-20261111/guard.py)、[配对驱动](../../build/artifacts/repcut-part18-20261111/measure.py)、[核验脚本](../../build/artifacts/repcut-part18-20261111/report.py)

## 最终检查

8 个诊断/归档 Python 脚本编译检查通过，两篇新记录的 27 个相对链接通过，父仓与 Wolvrix 的 `git diff --check` 通过。已有默认掩码规则及相关 dirty 修改保持原状；本轮没有新增生产代码变更。见 [检查结果](../../build/artifacts/repcut-part18-20261111/checks.json) 与 [源码身份](../../build/artifacts/repcut-part18-20261111/provenance.json)。

补充：加入本节的两个归档链接后，最终相对链接检查总数为 29，全部通过。
