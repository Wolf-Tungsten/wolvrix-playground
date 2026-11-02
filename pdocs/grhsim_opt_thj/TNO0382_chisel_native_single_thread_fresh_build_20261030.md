# TNO0382：从 Chisel 新生成专用单线程 GrhSIM 基线

日期：2026-10-30。状态：构建/测量进行中。口径承接
[TNO0381](./TNO0381_chisel_native_single_thread_baseline_scope_20261030.md)。

用户授权从当前 Chisel 完整生成并测量 emu walltime：编译可用 node030 任意核，正式
单线程测量必须固定 CPU96。使用 Wolvrix 专用完整模型流程，不运行 Repcut，也不使用
N=K=1 或串行分区包。

## 本次输入与输出约定

- XiangShan TLConfig、guest 单核；本次新执行 Chisel elaboration / firtool。
- 正常 `scripts/wolvrix_xs_grhsim.py` pipeline，关闭旧 GRH checkpoint 恢复。
- 独立构建当前 Wolvrix Python 绑定，依赖解析不使用旧安装的核心库。
- 模型编译 `Clang 23.1.2 / -std=c++20 -O3 -march=native`，harness 为普通 O3。
- 无 PGO、BOLT、波形、逐 batch 或逐拍诊断；Difftest 保留。
- 独立产物：[grhsim_single_fresh_20261030](../../build/xs/grhsim_single_fresh_20261030/)。
- 驱动：[grhsim_single_baseline.py](../../scripts/grhsim_single_baseline.py)。
- 100,000 cycles 为本轮固定窗口；新构建后重复同一 emu 8 次，另列功能/预热运行。
  此为 baseline 自身重复测量，不冒称存在 candidate 的 A/B 性能改善。

## 已核对的环境

node030 有 384 个在线逻辑 CPU；SSH 默认亲和性并非全部 CPU，本驱动显式申请全部
在线 CPU 用于生成和编译，编译并行度先设 64。CPU96 的 SMT sibling 为 CPU288。
测量时模型只能使用 CPU96，监控在其他 CPU；记录实际 TID/亲和性与本核/邻核负载。

Difftest 的 Scala FileControl 固定输出到 `$NOOP_HOME/build/generated-src`，本轮生成
使用独立的 `chisel-home`，防止重新生成时覆盖旧实验的 Difftest 头文件与源码。
后续 harness 显式引用该新目录。

## 启动记录

第一次运行在源码记录阶段发现 node030 的默认 PATH 没有 rg，尚未开始生成；驱动改为
Python 源码遍历后重新启动。失败记录保留在 progress.jsonl，不计为性能样本。

源码、编译器、配置、命令、每阶段日志和进度分别保存为 sources.json、configuration.json、
logs/ 与 progress.jsonl。后续阶段及实测结果以追加记录或新 TNO 归档。

## 进度更新：工具构建完成

node030 默认 PATH 没有 Ninja，第一次独立 CMake 配置尚未编译即退出。失败配置目录和日志
已保留，切换系统 Unix Makefiles 后，当前源码的 wolvrix_python 目标构建通过。
Chisel elaboration 已完成，firtool 1.135.0 正在生成新 RTL；工具构建与 RTL 生成相互独立。

正式测量前先运行 10,000 cycles 功能 smoke 和一次 100,000 cycles 预热，均单独记录，
不混入后面的 8 次基线统计。

## 进度更新：新的 RTL 已完成

Chisel/firtool 阶段成功，elapsed 为 497.538 秒，生成 2,097 个 RTL 文件及 6 个配套
Difftest 文件。内容哈希保存在 rtl_manifest.json 与 difftest_generated_manifest.json。
专用 Wolvrix 前端开始读取这套新 RTL；日志确认 checkpoint 恢复关闭。

## 补充发现：新旧 RTL 内容并非逐文件完全相同

仅用于事后核对，本次新生成 RTL 与 2026-10-28 冻结版本比较：2,095/2,097 文件内容
相同，差异在 Ftq.sv 与 LogPerfEndpoint.sv。可见差异包含 blame 比较项的排列、临时
信号名和性能计数声明/日志顺序；完整 diff 存在本轮目录。这不能仅凭局部差异证明整套
RTL 完全等价，也尚未据此判定生成器非确定性根因。

因此本轮基线将冻结实际新产物；后续重新 elaboration 的 candidate 需同时审查非目标
变化。重复同一个 binary 的 A/A 只衡量运行噪声，不覆盖重新生成/重新链接带来的变化。

## 进度更新：前端主要归一化通过

read_sv 约 114.2 秒，hier-flatten 约 63.1 秒，comb-lane-pack 约 195.5 秒；
组合环检查未检测到环，两轮 simplify 分别约 363.1 秒和 26.9 秒。memory-init-check
通过。约 3.2 GB 的 pre_reg_to_mem.json 是本轮新写出的快照，未作为恢复输入。
随后进入专用流程默认的 reg-to-mem（intent/ordered_writes/decoded_write_storage 开启），
不套用此前分区后的 reg-to-mem 策略。

## 进度更新：完整模型 C++ 发射成功

专用脚本成功退出；前端、变换、活动调度与发射合计进程 walltime 1,449.439 秒。
输出 131 个 C++ 文件，总计 1,264,958,111 字节。未生成 Gpart 或 Repcut runtime 文件。
完整 model_manifest.json 已保存；现在开始用 Clang 23.1.2 编译模型及新 Difftest harness。

## 进度更新：新 emu 链接成功

131 个模型对象已从本轮新生成 C++ 编译完成。启动脚本曾将 clang++ 路径 resolve 成
clang-23，编译 .cpp 正常，但首次链接漏掉 C++ 标准库而失败；已保留失败日志，修正
脚本以 clang++ 驱动重新链接成功，模型与对象未改写。首次编译/链接尝试 56.748 秒，
成功链接另计。完整二进制身份保存在 binary.json。开始 CPU96 功能 smoke 和固定窗口测量。

## 完成更新

成功链接耗时 1.502 秒。功能 smoke、预热及 8 次正式测量全部结束；正式 Host walltime
均值 118.524875 秒、中位数 118.332500 秒。完整序列、波动与复核证据独立归档到
[TNO0383](./TNO0383_native_single_thread_cpu96_walltime_baseline_20261030.md)。
