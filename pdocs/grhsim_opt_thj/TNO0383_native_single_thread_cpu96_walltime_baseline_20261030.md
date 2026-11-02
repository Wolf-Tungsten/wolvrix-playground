# TNO0383：专用单线程 GrhSIM CPU96 walltime 基线

日期：2026-10-30。状态：全流程完成；8 次正式固定窗口运行均通过功能与运行配置检查。
构建过程及中间问题见 [TNO0382](./TNO0382_chisel_native_single_thread_fresh_build_20261030.md)。

## 本次基线

本次从当前 Chisel 重新 elaboration/firtool 生成 RTL，以 Wolvrix 专用单线程脚本处理
完整 SimTop，编译新的 GrhSIM emu。使用普通 `GrhSIM_SimTop`，没有 Repcut 分区包。
本轮冻结身份为 `native-single-cpu96-20261030`。

| 项目 | 值 |
|---|---|
| 机器 / 运行 CPU | node030.bosccluster.com / CPU96 |
| 实际 emu 线程 | 1 |
| 硬件配置 | TLConfig，guest 单核 |
| 输入 | coremark-2-iteration.bin，seed=0，Difftest/NEMU 开启 |
| 窗口 | `-C 100000`，固定周期窗口，不是完整跑完两次 CoreMark |
| 正式样本 | 8 次，同一新构建 binary；所有样本保留 |
| 其他运行 | 10,000 cycles 功能 smoke；100,000 cycles 预热，均不进入正式统计 |
| 模型编译 | Clang 23.1.2，`-std=c++20 -O3 -march=native` |
| harness | 普通 O3，EMU_THREADS=0；专用 GrhSIM 后端 |
| 生成/编译资源 | node030 在线 CPU0–383 可用，编译并行度 64 |
| 运行内存策略 | `numactl --membind=1`；记录实际 numa_maps |
| ASLR | `setarch x86_64 -R`；每次 personality 均为 `00040000` |
| 页面/诊断 | 原生 loader，无额外代码页重映射；系统 THP 为 madvise；waveform/perf/phase timing 关闭 |
| SMT sibling | CPU288；正式样本的整段 `/proc/stat` 差分均显示 100% idle |

编译耗时、环境预检查、smoke 和预热不计入正式 emu walltime。运行监控在 CPU0，
不在 CPU96 上执行。内存策略 bind:1 不意味着所有共享文件页都在 node1；启动快照
确实包含少量位于 node0 的文件映射，未宣称全部代码/库页完全本地。

## Walltime 结果

| 样本 | Host time spent / 秒 | 外部进程 walltime / 秒 |
|---|---:|---:|
| run01 | 118.665 | 118.696 |
| run02 | 118.777 | 118.809 |
| run03 | 118.000 | 118.031 |
| run04 | 117.592 | 117.623 |
| run05 | 117.791 | 117.824 |
| run06 | 120.036 | 120.070 |
| run07 | 121.901 | 121.933 |
| run08 | 115.437 | 115.469 |

| 统计量 | Host walltime |
|---|---:|
| 均值 | **118.524875 秒** |
| 中位数 | **118.332500 秒** |
| 最小 / 最大 | 115.437 / 121.901 秒 |
| 样本标准差 | 1.889226 秒 |
| 变异系数 | 1.593949% |

外部进程 walltime 均值为 118.556701 秒，中位数 118.363440 秒。

主指标是同一 Difftest harness 输出的 `Host time spent`，包含其计时范围内的初始化、
仿真、NEMU/Difftest 及收尾工作，不是纯模型 eval 时间。外部计时从启动进程到进程
退出，由另核的 wait 线程记录；它不含每次运行前的 3 秒 CPU 空闲检查。

本次没有删除第 6/7 次偏慢样本或只取第 8 次最快值。单线程减少了分区/同步等干扰，
但本轮仍观察到波动；未采集足以将其归因到频率、缓存或其他系统活动的证据。
后续候选应与这个固定 binary 在当次环境中交替运行，采用配对比较，不长期使用
118.525 秒作为不变分母。这里也没有做第二次 fresh build，因此没有测量重新生成/链接的波动。

## 功能与身份复核

8 次正式样本全部：

- Difftest 正常启用，退出成功，无 mismatch/abort/bad trap。
- PC=`0x80000c0c`，instrCnt=`240349`，cycleCnt=`99996`，Guest cycles=`100001`。
- 实际只有一个 emu TID，所有监控样本的 affinity 与 processor 均为 CPU96。
- 二进制 SHA256 与生成模型源文件哈希不变。

独立审计检查了 1,895 份线程/CPU 监控快照及全部正式日志，结果见
[final_audit.json](../../build/xs/grhsim_single_fresh_20261030/final_audit.json)。
日志解析器的正常/拒绝用例测试、Python 编译检查和 git diff 检查通过。

二进制大小为 85,938,224 字节，SHA256：

```text
fe23d64daeb203f9adddff23021c87c998b7a9527513f97223948196d78cffd8
```

## 产物与复现

- [基线 emu](../../build/xs/grhsim_single_fresh_20261030/emu/grhsim-compile/emu)
- [配置和输入身份](../../build/xs/grhsim_single_fresh_20261030/configuration.json)
- [完整 JSON 结果](../../build/xs/grhsim_single_fresh_20261030/runs/summary.json)
- [逐次 CSV](../../build/xs/grhsim_single_fresh_20261030/runs/samples.csv)
- [原始日志与监控](../../build/xs/grhsim_single_fresh_20261030/runs/)
- [复现源文件快照](../../build/xs/grhsim_single_fresh_20261030/reproduce/)

在仓库目录中重新执行全流程时，使用新的输出目录：

```bash
ssh node030 python3 \
  /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/scripts/grhsim_single_baseline.py all \
  --output /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/build/xs/grhsim_single_new_run \
  --jobs 64 --cpu 96 --cycles 100000 --repeats 8
```

独立运行冻结 emu 的核心命令（路径相对仓库根目录；重新运行的结果应另存新日志）：

```bash
taskset -c 96 numactl --membind=1 setarch x86_64 -R \
  build/xs/grhsim_single_fresh_20261030/emu/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -s 0 -C 100000
```

该命令应在 node030 上执行。重新生成候选时还要审查非目标 RTL 的排列/命名变化；本轮
新旧 RTL 内容比较发现的 Ftq/LogPerfEndpoint 差异已在 TNO0382 中保留，不用旧 RTL
冒充本轮新生成的输入。

## 勘误：有效模型编译选项（2026-10-30）

上文“模型编译”及 `configuration.json` 的 `model_flags` 只记录了调用者传入选项，
遗漏生成 Makefile 自动加入的兼容参数。实际全部模型对象使用
`-std=c++20 -O3 -march=native -fno-slp-vectorize` 编译；不是开启默认 SLP 的 native O3。
原始编译证据在 `logs/compile-c-driver-link-failed.log`，随后的成功 relink 使用同一批对象。
这是 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md) 的正确性保护。
此处保留原始配置、日志和二进制，以追加勘误明确有效选项，不回写冻结身份。

历史无 PERF dump 的 100k 单线程约 99 秒，不能仅因旧带 PERF dump 记录约 116–120 秒
就认定本次 118.525 秒正常。结构与同 CPU96 交替复测见
[TNO0384](./TNO0384_native_single_thread_historical_comparison_20261030.md)。

## 勘误：代码页的实际 NUMA 位置（2026-10-30）

进一步按 `/proc/<pid>/maps` 的可执行映射起址关联 `numa_maps`，发现上文“少量位于
node0 的文件映射”的概括不准确。8 次正式运行的启动快照中，emu 可执行代码映射的
已驻留页均为 `N0=18400`，而 CPU96 在 node1。即快照所覆盖的主要代码页全部远端；
这不代表所有尚未触碰的 ELF 页或所有共享库都具有相同分布。

`membind=1` 没有迁移构建阶段已经进入文件缓存的代码页。因此本轮 118.525 秒可作为
这个冻结 binary **及其当时实际页面布局** 的记录，尚不宜直接作为后续候选的公平性能
分母。候选如恰好使用本地代码页，会混入 NUMA 收益。详细对照和同内容文件副本的
局部性控制实验继续记入 [TNO0384](./TNO0384_native_single_thread_historical_comparison_20261030.md)。
