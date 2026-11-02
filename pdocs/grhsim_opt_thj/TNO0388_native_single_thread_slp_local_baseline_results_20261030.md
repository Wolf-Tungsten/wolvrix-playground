# TNO0388：CPU96 默认 SLP、本地 NUMA 单线程基线结果

日期：2026-10-30。状态：8 次正式测量及独立功能/NUMA/亲和性审计全部完成。
基线标识：`native-single-slp-local-cpu96-20261030`。
准备和测量入口修改见 [TNO0387](./TNO0387_native_single_thread_slp_local_numa_measurement_20261030.md)。

## 本次结果

使用 TNO0386 的同一个原生 GrhSIM 单模型 binary，Clang23 native O3，SLP 保持默认，
没有自动 no-SLP。没有重新编译或重新生成 Chisel/RTL。运行固定 node030 CPU96、
NUMA node1，CoreMark、NEMU、seed=0、C100000。10k smoke 和 100k 预热均排除在统计外。

| 正式样本 | Host time / 秒 | 外部进程 walltime / 秒 |
|---|---:|---:|
| run01 | 98.305 | 98.334338 |
| run02 | 97.633 | 97.664532 |
| run03 | 97.992 | 98.022415 |
| run04 | 98.110 | 98.139337 |
| run05 | 98.005 | 98.033619 |
| run06 | 98.674 | 98.707323 |
| run07 | 99.032 | 99.061115 |
| run08 | 100.879 | 100.906504 |

| 统计量 | Host walltime |
|---|---:|
| 均值 | **98.578750 秒** |
| 中位数 | **98.207500 秒** |
| 最小 / 最大 | 97.633 / 100.879 秒 |
| 样本标准差 | 1.025965 秒 |
| 变异系数 | 1.040757% |

外部进程 walltime 均值 98.608648 秒，中位数
98.236838 秒。主指标仍为 harness 的 `Host time spent`，包含
其计时边界内的初始化、模型仿真、NEMU/Difftest 与收尾，不能当作纯 eval。
复制文件、页面 prefault、CPU 空闲预检查与预热均在正式计时外。

保留了较慢的 run08（100.879 秒），没有按速度删除样本。所有正式样本的功能和页面
检查均通过。CPU 使用 schedutil governor，运行时频率未锁定；节点为共享环境，
未声称整个 CCD/机器隔离。页面本地化没有消除所有系统噪声。

## NUMA 的实际证据

测量前，使用 CPU96/node1 将 emu、NEMU、image 和六个依赖库复制为独立文件实例，
校验 SHA256，逐页 prefault，并检查实际 NUMA 节点。全部九个副本与原文件字节一致。
运行使用这些副本，依赖库通过独立 LD_LIBRARY_PATH 指定；保持原生 ELF loader，
不修改 binary、不使用额外代码重映射或 LD_PRELOAD。

正式运行期间，共独立复核 **161 份 maps/numa_maps 快照**：

| 类别 | 最大已驻留页数 / 4KB 页 | 观测到的远端页 |
|---|---:|---:|
| emu 文件映射 | 17871 | 0 |
| NEMU 文件映射 | 115 | 0 |
| 六个依赖库 | 919 | 0 |
| 匿名状态、堆、栈和模拟 RAM | 6847 | 0 |

这些是快照中已经驻留的物理页，不能把未访问的虚拟地址空间也算作已验证物理内存。
每约 5 秒取一次快照，不宣称观测到了两个快照之间每一瞬间的页面状态。
系统 ELF 装载器单独统计，本次所有正式快照中也只出现在 node1；内核 vdso/vvar
单列，没有伪造其物理节点。观测到的内核页粒度为 4KB。

1575 份线程快照均为一个实际 emu TID，affinity 和 processor 都为 CPU96。
SMT sibling CPU288 整段空闲比例最低 99.857637%。ASLR 每轮都关闭。
没有 NUMA、线程、亲和性或 sibling 门槛拒绝的正式样本。

## 功能与冻结身份

八次均到达同一功能终点，NEMU 无 mismatch，无 PERF 输出：

```text
PC=0x80000c0c
instrCnt=240349
cycleCnt=99996
Guest cycles=100001
emu SHA256=8ca2403cc0eb0ad305a41c30337ce0a647cdb0f4ac4f80f401e9bf4b6771ce65
```

审计再次校验了全部运行副本、原 emu、系统 loader、测量脚本与归档脚本副本的身份。
编译命令及其生成来源保存在 `source_build_validation.json`，不是只根据手写选项推测。
本次有限输入验证不代表 Clang23 已知独立复现错误已修复。

## 与此前数值的关系

TNO0383 的历史记录为 118.524875 秒，但当时模型关闭 SLP，主要代码页在远端。
本次采用默认 SLP，且 emu、NEMU、依赖库和匿名状态都检查了实际本地位置。
因此两轮不能作为只改变一个编译开关的配对 A/B；不能把跨批次差值全算成 SLP 收益。
TNO0385 的 109.7375 秒也只有两个样本，且只对同字节 emu 文件做页面控制。

以后模式改写或编译器候选，应复用这里冻结的 binary 和相同页面准备协议，在当次
环境中与 candidate 做至少 8 对 AB/BA，不把 98.57875 秒当作永远不变的分母。

## 产物与复现

正式产物目录：`build/xs/grhsim_single_slp_local_20261030_v2/`。

- [完整 JSON 结果](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/summary.json)
- [逐次 CSV](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/samples.csv)
- [独立审计结果](../../build/xs/grhsim_single_slp_local_20261030_v2/final_audit.json)
- [实际命令、页面原始快照和日志](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/)
- [节点、内核与频率策略](../../build/xs/grhsim_single_slp_local_20261030_v2/host_info.json)
- [运行副本与九文件身份](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/runtime/manifest.json)
- [测量脚本与独立审计脚本](../../build/xs/grhsim_single_slp_local_20261030_v2/reproduce/)

复现使用 TNO0387 的 `measure --binary` 命令，指定新的输出目录。实际 NUMA 检查
已经进入测量入口；不再只设置 membind 参数或只看第一次启动截图。
