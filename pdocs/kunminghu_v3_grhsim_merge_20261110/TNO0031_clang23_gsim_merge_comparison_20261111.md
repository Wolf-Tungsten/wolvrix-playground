# TNO0031 Clang 23 下单核 GSIM merge 前后 8 对结果

## 构建和功能门

按 [TNO0029](./TNO0029_all_clang23_rebuild_protocol_20261111.md)，复用两侧冻结的 GSIM C++ 模型，分别用 Clang 23.1.2 重编译模型及各 revision 的 DiffTest harness。保持原 GSIM 编译参数 `-O3 -fbracket-depth=2048 -Wno-parentheses-equality`，不加 PGO/BOLT、trace 或 runtime profile；没有重新运行 GSIM 生成器。

在 node030、CPU96、NUMA1 strict membind、ASLR disabled 下执行固定 CoreMark、100,000 周期、完整 NEMU DiffTest。两侧均完成 10k smoke、两组 100k trace 验证、预热及 8 对 AB/BA，共 **24 次有效运行，0 次拒绝**。trace 覆盖和实际单线程/CPU96/NUMA1/ASLR 门全部通过。

每个版本的正式签名稳定：before PC=`0x80000b40`、instrCnt=238,550、cycleCnt=99,998；after PC=`0x80000c10`、instrCnt=250,845、cycleCnt=99,997。共同 Guest cycles=100,001，cycle-limit 终止，UART 为 `Running CoreMark for 2 iterations`。两套 DiffTest schema 分别对 NEMU 检查，不做跨 schema 的 trace 字节比较。

## 8 对 AB/BA 结果

正数表示 after 更慢；固定 seed 20261102，10,000 次 paired bootstrap。

| 指标 | before 均值 / 中位数 | after 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI | after 更慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 78.974250 / 79.055000 s | 106.913375 / 107.109000 s | **+35.3776% / +35.4124%** | **[+35.1293%, +35.6154%]** | 8/8 |
| 外部 walltime | 79.000276 / 79.080451 s | 106.945077 / 107.140039 s | **+35.3731% / +35.4085%** | **[+35.1254%, +35.6104%]** | 8/8 |

统一 Clang 23 后，GSIM 的 merge-after 仍明显更慢。该结果比较的是整个 revision/DefaultConfig/DiffTest 的仿真成本，不能归为独立的 GSIM 后端变化。

此前 Clang 19 的 GSIM 对测记录在 [TNO0021](./TNO0021_gsim_paired_walltime_20261111.md)，当时 after 慢约 34.77%。本轮前后差异方向和幅度接近；两轮不是 Clang 19/23 的同窗口配对实验，不能把绝对时间差解释为编译器净收益。

## 归档

- [构建 before](../../build/xs/kunminghu-v3-clang23-retest-20261111/builds/gsim/before/)、[构建 after](../../build/xs/kunminghu-v3-clang23-retest-20261111/builds/gsim/after/)：完整源码 manifest、dry-run 编译命令、二进制哈希。
- [运行 manifest](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/manifest.json)、[summary](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/summary.json)。
- [逐对 CSV](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/pairs.csv)、[逐对 JSON](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/pairs.json)。
- [trace seed0 验证](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/trace-s0.json)、[trace seed1 验证](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/trace-s1.json)、[逐样本原始日志和 locality](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/gsim/)。
