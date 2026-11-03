# TNO0399：PopCount walltime 的同 binary A/A 控制

日期：2026-11-03。本记录补充 TNO0397/TNO0398 的测量解释，不引入新的优化规则。

使用同一个关闭原语的 native emu binary，在 node030 CPU96 上按同样的 8 对交替流程运行
A/A 控制。两边 binary SHA256 完全相同，Difftest 和 NUMA 检查通过。

| 指标 | A/A 控制 |
| --- | ---: |
| 平均配对差 | -1.342466% |
| 配对中位数 | -0.617670% |
| 固定种子 bootstrap 95% CI | [-3.210549%, +0.074618%] |
| “候选更快”配对数 | 6 / 8 |
| A 侧平均 Host time | 100.30625 s |
| B 侧平均 Host time | 98.80725 s |

同一 binary 的单次运行仍出现明显差异，例如一对为 `116.600 s` 对 `108.136 s`；CPU
亲和、SMT sibling 和页面 locality 检查都通过。这表明当前 CPU96 的频率/系统状态波动
已经大于 PopCount 实验观察到的约 1% 级别差异。

因此当前阶段只保留以下结论：PopCount intrinsic 的功能和生成链路已经验证，但没有测出
可信的稳定 walltime 收益。TNO0397 的全宽替换和 TNO0398 的宽度≥4 替换都不进入默认
配置，也不再继续做更细的模块级收益宣称。后续若重新开展性能比较，应先固定或记录
CPU 频率状态，并重新建立同 binary 控制基线。

## 产物

- [A/A summary](../../build/xs/popcount_ge4_20261103_v1/control-aa-v1/summary.json)
- [A/A pairs](../../build/xs/popcount_ge4_20261103_v1/control-aa-v1/pairs.csv)
