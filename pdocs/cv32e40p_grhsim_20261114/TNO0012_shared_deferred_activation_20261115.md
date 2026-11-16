# TNO0012：共享 deferred-activation 变化归约

## 结论

在冻结的 CV32E40P CoreMark 10-iteration 模型上，打开 Wolvrix 的 `shared_deferred_activation` 后，完整总线 trace 与关闭版完全一致；node030 上 8 对 AB/BA 测量的 walltime 平均降低 **0.79%**，仿真循环时间平均降低 **0.83%**。候选/基线比率的 95% bootstrap CI 分别为 **[0.98873, 0.99566]** 和 **[0.98837, 0.99515]**，均排除持平。

这是一个稳定但幅度较小的单模型收益。它只验证共享 deferred-activation 归约对本模型有效，不能解释或消除 GrhSIM 与 Verilator 的主要差距；本实验不改生产默认值。

## 变更范围

`shared_deferred_activation` 对同一个 supernode 中、拥有相同 deferred reader-group 集合的 eligible scalar 值先做一次共享变化归约，再把该结果分发到这些 group。原始逐值变化检测、group 成员关系、激活目标和调度顺序都保留。只有静态估算认为共享后至少减少 4 个 Boolean OR 的 cohort 才采用此 lowering；小 cohort 留在旧路径。

候选生成得到 20 个共享变化归约变量，共 1,738 处声明或引用；只有 5 个 scheduler C++ 文件变化，normalized graph 和模型 header 完全相同。所有 24 个 C++ 文件总量减少 92,892 bytes，候选 binary 比冻结基线小 2,848 bytes（33,861,920 vs. 33,864,768 bytes）。这说明 emitter 确实合并了重复的 group 更新归约，但本轮没有采集该规则的逐 cohort 动态执行计数，不能把静态源码变化等同于每周期实际省下的 OR 数。

## 功能与性能门

两侧都使用 Wolvrix `74d80cfac6855cab6aa4bbd539f45d629e46be58` 的冻结 native tools、Clang 23.1.2 `-O3 -march=native`、同一 normalized graph（SHA `e1ccc2928b055e022eb5a7a6637265af19a762e8fdf964ad26ee5833b5f9191b`）和同一 CoreMark image。实验 baseline binary SHA 为 `9642e07f8a0add9eaf1b0962005f60aadc5e4d6ce8382622de99489cb8860037`；candidate SHA 为 `f91ca9eeb6e211631a54a1585bdded395b52764f11e9f5de4614e1447dbf53c9`。

| 检查项 | 关闭 | 开启 | 结果 |
| --- | ---: | ---: | --- |
| Smoke 完成周期 | 253 | 253 | UART 和总线 trace 完全一致 |
| CoreMark 完成周期 | 3,376,065 | 3,376,065 | exit code、UART/CRC 和总线 trace 完全一致 |
| CoreMark final CRC | `0xfcaf` | `0xfcaf` | 通过 |
| 配对 placement | CPU96 / NUMA1 / ASLR disabled | CPU96 / NUMA1 / ASLR disabled | 8/8 对均通过，无重试 |

| 指标 | 基线均值 | 候选均值 | 候选/基线比率均值 | 95% bootstrap CI |
| --- | ---: | ---: | ---: | ---: |
| 外部 walltime | 4.45899 s | 4.42371 s | 0.99212 | [0.98873, 0.99566] |
| 仿真循环 | 4.42579 s | 4.38889 s | 0.99169 | [0.98837, 0.99515] |
| 初始化 | 7.269 ms | 7.351 ms | 1.01205 | [0.98416, 1.03982] |

Walltime CI 换算为相对改善约 **0.43%–1.13%**；初始化差异不显著。8 对每一对都通过功能签名和 placement/locality 检查。CPU96 固定单线程，ASLR 关闭；每对按 AB/BA 交替，测量前每侧预热一次。

## 复现与产物

所有测量产物在 [`shared-deferred-activation-v1`](../../build/cv32e40p/shared-deferred-activation-v1/)：

- [`report.json`](../../build/cv32e40p/shared-deferred-activation-v1/report.json)：输入身份、功能证据和汇总指标。
- [`pairs.csv`](../../build/cv32e40p/shared-deferred-activation-v1/pairs.csv) 与 [`pairs.json`](../../build/cv32e40p/shared-deferred-activation-v1/pairs.json)：逐对顺序和原始时间。
- [`functional.json`](../../build/cv32e40p/shared-deferred-activation-v1/functional.json)：两侧 smoke/CoreMark 签名、总线 trace SHA 和 placement 检查。
- [`structure.json`](../../build/cv32e40p/shared-deferred-activation-v1/structure.json)：变化源文件和发射统计。

在 node030 复用冻结 native tools 构建并测试：

```sh
python3 scripts/cv32e40p_deferred_activation_compare.py build --output build/cv32e40p/shared-deferred-activation-v1
python3 scripts/cv32e40p_deferred_activation_compare.py verify --output build/cv32e40p/shared-deferred-activation-v1
python3 scripts/cv32e40p_deferred_activation_compare.py measure --output build/cv32e40p/shared-deferred-activation-v1
```

本轮使用的 Wolvrix focused emitter CTest `emit-grhsim-cpp-shared-deferred-activation` 已通过。运行器源码通过 `py_compile`；测量结果中 8 对均使用首轮样本，且无 placement 拒绝文件。
