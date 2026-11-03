# TNO0401：生成阶段关闭 DiffTest 的 Wolvrix 单线程性能实验

日期：2026-11-03。

本轮在运行时完全停用差分采集和检查的条件下，生成阶段关闭 DiffTest 后，
8 对 AB/BA 的平均配对 Host 耗时下降 **10.410040%**，B 在 **8/8** 对中更快。
固定种子 paired bootstrap 95% 区间为 **[-10.777662%, -10.063447%]**。
此结果支持在当前 CoreMark 负载、CPU96 和 native 单线程流程中存在明确收益。

## 实验口径与实现

| 配置 | Chisel 生成 DiffTest | 运行时采集和检查 |
| --- | --- | --- |
| A | 开启，106 个接口 | 完全关闭 |
| B | 关闭 `EnableDifftest` 和 `AlwaysBasicDiff`，0 个接口 | 完全关闭 |

- 两组均以 `NO_DIFF=1` 编译 harness、`--no-diff` 运行，Wolvrix 读入 RTL 时不定义 `DIFFTEST`。生成模型中没有 `v_difftest_*` 采集回调；运行时没有参考模型文件或 NEMU 映射。
- 新增 `DISABLE_DIFFTEST=1` → `--disable-difftest`，Makefile 不再为该配置追加 `--enable-difftest`。DiffTest 接口集合为空时跳过 Gateway 生成，同时保留兼容头文件以及 RAM、Flash、UART、时钟和复位设施。
- `grhsim_single_baseline.py` 增加独立的 `--rtl-difftest on|off`、`--runtime-difftest on|off`，默认均为 `on`；拒绝硬件关闭但运行时检查开启。比较脚本从冻结配置读取两端生成模式，关闭模式不要求相同 schema，也不生成 difftrace。
- 关闭模式显式记录采集/检查状态与周期上限退出。PC、提交指令数和 DiffTest cycleCnt 均为 `null`，不以零代替。
- 关闭 DiffTest 暴露了 ROB 数据库路径对不存在的 `perfDebugInfo.get` 的访问，已为该路径补上 `backendParams.debugEn` 条件。A/B 均在修复后的同一源码快照重新生成。

`EnableDifftest` 也控制后端 `debugEn` 及相关字段，所以本实验测量整个生成选项的效果，
不能把全部收益归因于某一种采集模块或 DPI 回调。其他配置、断言、日志参数一致，
两组 intrinsic 均为 `none`，没有修改默认开启 DiffTest 的行为。

## 配置与运行检查

使用 TLConfig、1 个 guest core、native 单模型单线程 GrhSIM，运行于 node030 CPU96、
NUMA node 1，固定 ASLR。模型编译使用 Clang 23.1.2、`-std=c++20 -O3 -march=native`，
harness 使用 `-O3`；waveform、runtime profile、PGO/BOLT、ChiselDB 和 Constantin 均关闭。
两端使用同一个冻结 Python binding 与相同的 1,690 项源码清单，Chisel 串行生成。

负载为 `coremark-2-iteration.bin`，每次 `-C 100000`、seed 0；退出记录为 100000 周期，
harness 收尾另执行一个周期，因此 `Guest cycle spent` 为 100001。Host time 包含 harness
工作，不是纯 `eval()` 计时。正式采样期间本任务没有并行构建，没有按耗时剔除样本。

- 15 项针对性测试通过：开关传递、非法组合拒绝、关闭模式日志解析、UART 无换行边界、异常退出和重复/缺失字段拒绝、访存/UART 比较、原有 trace/统计及 NUMA 检查。未运行全量回归。
- 完整 A/B RTL、空接口 B 生成及两端 native 编译通过；`CONFIG_NO_DIFFTEST` harness 额外语法检查通过。
- 两端各一次 10,000 周期 smoke、100,000 周期 footprints 检查和预热通过。
- footprints 均为 14,656 字节（1,832 个首次访问的数据值），SHA256 均为 `10a8932701c8fb78f3128f554f7f00c6be5802d8dcc63c3c5c77d29c4b710f7f`；UART 均输出 `Running CoreMark for 2 iterations`。
- footprints 实现会为默认约 8 TiB 模拟 RAM 预留约 1 TiB 位图，系统拒绝这一预留。因此仅这两次诊断运行使用 `--ram-size 1GB`，正式测量仍使用默认 RAM，且关闭 footprints。首次访问数据与 UART 一致性不等同于完整 ISA 差分验证。
- 16 个正式样本均通过单线程、CPU96 亲和、SMT sibling、NUMA locality、周期数及 UART 检查；二进制、运行时文件、工具和测量脚本哈希均通过最终核对。

## 正式结果

百分比逐对计算 `100 × (B_host / A_host − 1)`，负数表示关闭生成后更快。

| pair | 顺序 | A Host / s | B Host / s | B/A−1 |
| ---: | :---: | ---: | ---: | ---: |
| 0 | AB | 79.984 | 71.499 | -10.608372% |
| 1 | BA | 79.105 | 71.235 | -9.948802% |
| 2 | AB | 80.078 | 71.028 | -11.301481% |
| 3 | BA | 81.259 | 73.311 | -9.781070% |
| 4 | AB | 80.382 | 71.524 | -11.019880% |
| 5 | BA | 79.130 | 71.239 | -9.972198% |
| 6 | AB | 79.938 | 71.427 | -10.647001% |
| 7 | BA | 79.038 | 71.133 | -10.001518% |

| 汇总 | 数值 |
| --- | ---: |
| A 平均 / 中位 Host | 79.864250 / 79.961000 s |
| B 平均 / 中位 Host | 71.549500 / 71.333000 s |
| 配对变化均值 | -10.410040% |
| 配对变化中位数 | -10.304945% |
| 配对 bootstrap 95% 区间 | [-10.777662%, -10.063447%] |
| B 更快 | 8/8 |

bootstrap 沿用现有脚本的固定 seed `20261102`，对配对百分比重采样 10,000 次。
CPU 频率没有锁定；区间反映本轮样本，结论限定于该负载与“运行时完全停用”的口径。
此前微小差异的噪声背景见 [TNO0399](./TNO0399_popcount_walltime_aa_control_20261103.md)。

## 结构变化

| 指标 | A | B | 变化 |
| --- | ---: | ---: | ---: |
| 生成 DiffTest 接口 | 106 | 0 | 全部关闭 |
| RTL 文件数 | 2,097 | 2,025 | -72 |
| RTL 字节数 | 243,606,175 | 187,384,743 | -23.079% |
| reg-to-mem 前 GRH 操作数 | 4,662,310 | 4,502,885 | -3.419% |
| reg-to-mem 前寄存器位数 | 3,964,515 | 3,485,705 | -12.077% |
| reg-to-mem 前 memory 位数 | 185,352,260 | 185,352,260 | 0% |
| 调度阶段计算操作数 | 5,365,403 | 5,130,590 | -4.376% |
| compute supernode 数 | 60,225 | 57,527 | -4.480% |
| commit supernode 数 | 467 | 463 | -4 |
| 生成 C++ 字节数 | 1,186,021,406 | 1,148,312,818 | -3.179% |
| ELF 文件字节数 | 73,454,048 | 71,286,016 | -2.952% |
| ELF `.text` 字节数 | 66,390,139 | 64,277,887 | -3.182% |

即使两端在读入 RTL 时都关闭采集回调，生成阶段开关仍留下可见的寄存器和计算规模差异，
并未被后续优化完全抹平。结构指标与本轮计时方向一致；本实验不继续做模块级归因。

## 产物与复现

- [机器可读完整报告](../../build/xs/difftest_generation_20261103_v2/report.json)
- [walltime summary](../../build/xs/difftest_generation_20261103_v2/comparison-v2/summary.json)、[逐对 CSV](../../build/xs/difftest_generation_20261103_v2/comparison-v2/pairs.csv)
- [运行命令、配置与输入哈希](../../build/xs/difftest_generation_20261103_v2/comparison-v2/manifest.json)
- [结构指标](../../build/xs/difftest_generation_20261103_v2/structure.json)、[结构统计脚本](../../build/xs/difftest_generation_20261103_v2/collect_structure.py)
- [最终核对](../../build/xs/difftest_generation_20261103_v2/final_validation.json)、[footprints 检查](../../build/xs/difftest_generation_20261103_v2/comparison-v2/footprint-check.json)
- 原始日志、进程映射和逐次 locality 记录位于 `comparison-v2/{A,B}/runs/`；生成和编译日志位于 `{A,B}/logs/`。

最初 `difftest_generation_20261103_v1` 的 B 在上述 ROB 调试字段处失败，未进入测量。
修复后本轮两端均重新生成。`comparison-v1` 仅因 smoke 的 UART 无换行导致解析器误报，
修复解析后使用 `comparison-v2` 完整重跑；失败记录保留，没有丢弃正式计时样本。

共享目录中其他任务随后补充了 CoupledL2/HuanCun/openLLC 的 PopCount 导入，均发生在
两端 RTL 生成结束之后，本实验未改动或使用这些新增修改。
时间与哈希证据见 [源码核对](../../build/xs/difftest_generation_20261103_v2/source_audit_after_build.json)。

在 node030、仓库根目录中使用新的输出目录复现：

```bash
cmake --build build/grhsim32-tools --target wolvrix_python -j32
python3 scripts/grhsim_difftest_generation_study.py build \
  --output build/xs/difftest_generation_repro --jobs 32
python3 scripts/grhsim_difftest_generation_study.py measure \
  --output build/xs/difftest_generation_repro
```

正式产物为 `difftest_generation_20261103_v2/comparison-v2`；新目录默认生成 `comparison-v1`。
实验入口仅新增可选配置，现有默认流程仍保持 DiffTest 开启。
