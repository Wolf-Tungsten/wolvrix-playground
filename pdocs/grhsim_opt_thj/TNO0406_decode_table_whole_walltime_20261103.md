# TNO0406：译码表 intrinsic 单线程整机 walltime

日期：2026-11-03。完整 8 对正式样本采集完成。

## 结论

A 平均 **99.25475 s**，B 平均 **97.228875 s**。按各对 B/A−1 计算，均值 **-2.0406%**，中位数 **-2.0461%**；B 在 **8/8 对**中更快。
95% 配对 bootstrap 区间为 [-2.1591%, -1.9216%]。这支持本轮同负载约 2% 的稳定改善，不外推到其他配置／负载，也不能据此给每张表分摊整机收益。

## 固定条件

TLConfig、CoreMark 2 iteration；专用 native 单模型单线程，非 N=K=1 的分区流程。A=none，B=decode-table，其余 intrinsic 关闭。两侧完整从同一 Chisel 快照生成，Clang 23.1.2，`-std=c++20 -O3 -march=native`，默认 SLP。RTL／模型／编译／运行 DiffTest 都为 on。

固定 node030 CPU96／NUMA node1；本地私有 binary、NEMU、依赖库预取，并在运行中核验文件页、匿名页、线程和 SMT sibling 288。16 次正式样本检查均通过；没有按速度删样本。每次 `-C 100000`，计时关闭 trace／诊断，采样期间不进行本实验的构建。主指标 Host time spent，外部 walltime 另存。

两组种子各 100,000 周期有效 DiffTest 轨迹逐条相同。comparison-v1 的脚本错误及未成对样本完整保留；comparison-v2 复核相同身份后重新比较既有功能轨迹，重新做 smoke／预热，并采齐以下全部正式样本。

## 全部样本

| 对 | 顺序 | A Host/s | B Host/s | B/A−1 | A 外部/s | B 外部/s |
|---:|---|---:|---:|---:|---:|---:|
| 0 | AB | 99.331 | 97.277 | -2.068% | 99.361 | 97.306 |
| 1 | BA | 99.511 | 97.331 | -2.191% | 99.541 | 97.359 |
| 2 | AB | 99.524 | 97.218 | -2.317% | 99.553 | 97.248 |
| 3 | BA | 99.165 | 97.201 | -1.981% | 99.193 | 97.231 |
| 4 | AB | 99.338 | 97.327 | -2.024% | 99.366 | 97.356 |
| 5 | BA | 98.961 | 97.133 | -1.847% | 98.990 | 97.162 |
| 6 | AB | 98.730 | 97.001 | -1.751% | 98.759 | 97.031 |
| 7 | BA | 99.478 | 97.343 | -2.146% | 99.507 | 97.372 |

## 覆盖与后续局部解释

70 次实际 elaboration 替换、24 张表；优化后完整模型保留 23 张／62 个操作。36 次 PreDecode 的未知宽度回退已具体解释，未在这轮计时中途修改范围。

局部 24 张表的 A/B 测量在整机完成后串行开始，kernel／full、随机／表项命中／密集／单比特变化／99% 保持等每项 8 对；32 位指令表增加未命中，主译码另加真实有效提交槽分布。局部收益仍待全样本收齐后单独汇总。

真实轨迹提取出 233,280 个有效 commit slot、100,000 条 cycle 记录；含 7,052 个融合额外指令计数，未伪造这些额外指令的指令字，因此只能称为有效提交槽分布，不是全部退休指令或前端推测译码流。

## 证据

- `build/xs/decode_table_20261103_v3/comparison-v2/summary.json`、`pairs.json`、`pairs.csv`。
- 同目录 A/B runs 中每次 `.json`、`.log`、`.locality.json`、`.numa`、`.monitor.json`。
- `local-measure-v1/committed-inputs/manifest.json` 和 `instructions.csv`。
- [TNO0404 构建与等价验证](./TNO0404_decode_table_native_build_and_equivalence_20261103.md)。
- [TNO0405 中断原因与验证复用](./TNO0405_decode_table_pair_runner_resume_20261103.md)。
