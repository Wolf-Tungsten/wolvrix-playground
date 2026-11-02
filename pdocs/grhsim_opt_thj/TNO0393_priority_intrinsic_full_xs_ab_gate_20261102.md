# TNO0393：优先编码原语完整香山 A/B 功能与单线程门禁

日期：2026-11-02。整机 A/B 已完成；全位宽微基准正在补齐。

接续 [TNO0392](./TNO0392_priority_intrinsic_when_and_validation_20261102.md)。

## 生成身份

`build/xs/priority_intrinsic_20261102_v4` 由同一份 Chisel 源码分别生成：

| 版本 | 模式 | utility 调用 | RTL 文件 | C++ 模型文件 | emu SHA256 |
|---|---|---:|---:|---:|---|
| A | `none` | 466，全部 intrinsic=false | 2097 | 269 | `c047f19ce95217ec14a9d159429999bc2bcd046ae89e21795ef00257273719a3` |
| B | `priority-encode` | 466，全部 intrinsic=true | 2114 | 267 | `af87828bfb0acf39d28b2b755a13d15e6700a86d2153f65c991d2cc063df8541` |

两份模型使用相同的冻结 Wolvrix Python 扩展和 `libwolvrix-lib.so`，编译命令为
Clang 23.1.2、`-std=c++20 -O3 -march=native`，没有 `-fno-slp-vectorize`、PGO、
BOLT 或诊断插桩。B 的生成 C++ 中出现 426 个 `grhsim_ctz_u64` 调用，A 没有
CTZ 操作调用；helper 声明本身不计入调用数。

## 功能轨迹

在 node030 CPU96、单模型、单线程、本地 NUMA node1 下，A/B 各跑两组固定种子、
每组 C100000。逐字段比较 `DiffTestState`，包括周期、提交记录顺序和有效提交
载荷；C padding 和无效提交载荷不比较。两组各 100000 条记录均通过：

```text
pc           0x80000c0c
instrCnt     240349
cycleCnt     99996
guest cycles 100001
```

每次长运行都观察到 NEMU reference 映射，二进制、私有 loader 库和匿名状态页均在
node1；SMT sibling 288 保持空闲。短 smoke 可能在最终 `/proc` 快照前卸载 NEMU，
因此只要求它的 prefault 副本和 Difftest/trace 证据，不把短时未映射误判为失败。

## 8 对 AB/BA walltime

正式运行关闭 trace 和诊断，预热后固定 CPU96，保留 8 对 AB/BA 样本。历史冻结
binary 在前后各做一次 C100000 anchor，功能签名一致。

| 指标 | 结果 |
|---|---:|
| A 均值 | 113.101750 s |
| B 均值 | 113.597125 s |
| 配对均值变化 `(B/A-1)` | **+0.439982%** |
| 配对中位数 | +0.190868% |
| 固定种子 paired bootstrap 95% CI | [+0.080777%, +0.882435%] |
| B 更快的对数 | 1/8 |

本次整机结果显示原语版本有小幅退化，不能宣称整机加速。该变化与 B 减少的
硬件展开和 426 个字级 CTZ 调用同时出现，但本轮没有把 walltime 差异归因到某个
单独调用；微基准和生成代码统计用于后续拆分“运算节省”和“活动/调度/物化成本”。

活动调度统计提供了一个直接的相关线索：B 的图操作减少 3,455 个、compute
node 操作减少 3,481 个，但 compute nodes 增加 354 个、compute supernodes 增加
62 个，DAG edges 增加 3,002 个；commit supernodes 保持 468。也就是说，原语
减少了局部算术，却改变了调度切分和依赖边形状。这个统计解释了为什么局部
microbench 的收益不能直接外推到整机 walltime，但仍只是相关证据，不是单独的
因果证明。完整差异见 `build/xs/priority_intrinsic_20261102_v4/scheduling-delta.json`。

完整样本、NUMA 快照、轨迹比较和命令在：

```text
build/xs/priority_intrinsic_20261102_v4/comparison-v3/
```

全位宽矩阵仍按固定 31 个宽度和 packed/lanes 两种布局测量；任何失败样本保留在
各自 case 目录，不从统计中静默删除。
