# TNO0387：默认 SLP 单线程 emu 的本地 NUMA 正式测量

日期：2026-10-30。状态：运行中，10k smoke 通过；预热及 8 次正式样本进行中。
用户要求使用 TNO0386 的新 emu 重测，并强调远端 NUMA 问题不能再次遗漏。

## 冻结输入和运行条件

使用 [TNO0386](./TNO0386_grhsim_generated_makefile_default_slp_20261030.md) 已重编译、
已完成 C100000 功能验证的原生完整 GrhSIM 单模型。没有重做 Chisel elaboration 或
重新编译模型；不使用 RepCut 的 N=K=1，也不修改编译器优化设置。

```text
emu SHA256 8ca2403cc0eb0ad305a41c30337ce0a647cdb0f4ac4f80f401e9bf4b6771ce65
Clang 23.1.2, -std=c++20 -O3 -march=native
```

- node030，emu 固定 CPU96，实际 NUMA 节点由 sysfs 查到为 node1，SMT sibling=CPU288。
- 同一 CoreMark 输入、NEMU、seed=0、C100000、无 PERF/波形/逐拍计时。
- 10k 功能 smoke 和 100k 预热不计入正式统计；随后保留全部 8 次样本。
- ASLR 关闭，原生 loader、4KB 文件页策略，无额外代码 remap/LD_PRELOAD。
- 监控在 CPU0；每次前检查 CPU96/288 空闲，运行中记录 TID/CPU 和 sibling 空闲率。
- 本轮没有同时编译或启动自己的其他性能实验；不声称整台共享节点完全隔离。

## 将页面检查落实到测量入口

修改 [grhsim_single_baseline.py](../../scripts/grhsim_single_baseline.py) 的测量阶段，
新增 `measure --binary`，可在独立目录测量已冻结 binary。
NUMA 准备与解析在 [grhsim_numa.py](../../scripts/grhsim_numa.py)。构建和 Makefile
生成规则未再次修改，也没有加入 no-SLP 覆盖逻辑。

每次新实验在 CPU96/node1 上创建独立文件副本：emu、NEMU、输入 image，以及在运行
节点用 ldd 解析出的六个依赖库。全部副本逐字节 SHA256 校验；预先 mmap 并触碰每个页，
随后读取实际 numa_maps，确保这些文件缓存页全部位于 node1。总共九个文件。
复制、prefault、预检查和预热均在正式计时之外，不清除全机 page cache、不迁移原文件。

运行采用独立的 `LD_LIBRARY_PATH` 加载这些相同字节的库。监控每 0.5 秒检查实际
单线程/CPU96，每约 5 秒关联 maps 与 numa_maps，严格要求以下已驻留页没有远端页：

- emu 的全部文件映射，包括执行、只读和写时复制区；
- NEMU 和已解析依赖库的全部映射；
- 全部匿名映射，包括模型堆、栈和模拟 RAM。

发现远端页、未管理的可执行库、缺少必需映射、CPU/线程异常或 sibling 忙碌时，
保留原始日志和拒绝原因，停止采集，不悄悄跳过坏样本后继续凑够八次。
保存每次 NUMA 检查的原始 maps/numa_maps 及分类后的 JSON。

系统 ELF 动态装载器继续使用 binary 自带 PT_INTERP，单独报告它的页面位置；不修改
binary 的解释器和加载地址策略，也不宣称整个进程地址空间所有页都本地。
内核 vdso/vvar 同样单列，不算入模型页。后续比较必须采用相同准备协议。

## 启动记录

第一次目录 `build/xs/grhsim_single_slp_local_20261030/` 的九文件 prefault 已通过，
但独立 binary 测量入口仍使用构建专属的 `output/emu` 工作目录，启动前失败。
已改为 staged binary 所在目录；该次 emu 没有执行，计时样本为零，原日志完整保留。
实际正式采集使用新的 `build/xs/grhsim_single_slp_local_20261030_v2/`。

v2 smoke 通过：PC=0x800027c6，instrCnt=458，cycleCnt=9996，Guest=10001。
启动快照中 binary 16,927 页、reference 99 页、依赖库 903 页、匿名内存 6,737 页
全部在 node1。后续 100k 运行会随实际访问触及更多页，持续检查而非仅复用启动结论。

NUMA 解析测试覆盖“bind:1 但文件缓存实际在 node0”、远端匿名页、远端 NEMU/库、
未登记的可执行库及独立报告 loader，5 项相关测试通过。

## 复现

在仓库根目录运行，使用一个新的输出目录：

```bash
ssh node030 python3   /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/scripts/grhsim_single_baseline.py measure   --output /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/build/xs/grhsim_single_new_measurement   --binary /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/wolvrix/build/artifacts/grhsim-slp-default_20261030/full_model/emu/grhsim-compile/emu   --cpu 96 --cycles 100000 --repeats 8
```

- [测量输入范围](../../build/xs/grhsim_single_slp_local_20261030_v2/scope.json)
- [实际运行身份与协议](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/environment.json)
- [九文件身份及 prefault 验收](../../build/xs/grhsim_single_slp_local_20261030_v2/runs/runtime/manifest.json)
- [冻结的脚本副本](../../build/xs/grhsim_single_slp_local_20261030_v2/reproduce/)
- [运行日志](../../build/xs/grhsim_single_slp_local_20261030_v2/driver.log)

## 完成更新

8 次正式测量及独立审计全部完成：Host 均值 98.578750 秒，CV 1.040757%。
161 份正式 NUMA 快照中，emu、NEMU、依赖库和匿名页远端计数均为零；系统装载器
单列且本次也只观测到 node1。完整结果见
[TNO0388](./TNO0388_native_single_thread_slp_local_baseline_results_20261030.md)。
