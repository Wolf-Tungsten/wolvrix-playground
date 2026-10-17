# preserve-aggregate 单一路径、默认优化与清理重跑

2026-10-17。标准入口固定保留 aggregate；此次直接从 RTL 重建当前版本，
不做旧版本对照。现有 masked OR 性能证据见
[100k 实测](20261016-cpu-masked-or-coremark100k.md)。

默认配置：

| 环节 | 配置 |
| --- | --- |
| firtool | `--preserve-aggregate=all` |
| GRH 数组恢复 | mux-tree-fold → register-write-normalize → guarded mux-tree-fold，固定开启 |
| GrhSIM | comb-pack 关闭；bit 寄存器打包、state-store 分类、whole/phase simplify 开启 |
| masked OR | 默认开启，`min_terms=16` |
| CPU mapping | shared-boundary cloning，`max_clones=250000`；`target_batch_count=0` |
| CPU emit | 原生宽值、fanout 合写、8-bit 活动位打包、内存 enable bitmap、on-write 激活 |
| 目录 | RTL、checkpoint、模型、emu、日志默认放 `ptmp/xs/` |

删除 XS Python 入口中无效的 `--used-bits` / `--bitwise-predicates`，以及重复的
`--disable-pack-bit-registers`（调试统一用 `--no-pack-bit-registers`）；删除对应
Make 变量和已采纳 GRH pass 的 A/B 环境开关。Make 只传与脚本默认不同的优化选项，
普通 `xs_wolf_grhsim_ir` 默认发射 C++。
默认重跑会替换生成的 C++ 模型；显式禁止覆盖时，在 ingest 前检查非空目录。

随后删除 XS 标量流程入口（wolf SV emit/emu、JSON 对照、repcut 及其运行目标）、
重复的 `_aggregate` targets 和对应目录/模式变量。`xs_rtl` 和 `xs_gsim_rtl`
都固定传入 `PRESERVE_AGGREGATE=all`；显式传入旧模式 `none` 会报错。
生成、构建、重发射及运行入口检查 RTL 的 `time.log`：必须记录精确的
`--preserve-aggregate=all` 和成功退出。现有 scalar RTL 不能通过这项检查。
README 只保留标准 IR 入口，性能脚本的默认端点改为 aggregate 的
`225471,99996,100001,0x800010e2`。

`make clean_xs_retired` 已删除旧 `build/xs/{rtl,grhsim-ir,grhsim,wolf,repcut}`
和 `ptmp/grhsim-ir-active8*`，清除默认 filelist 曾在的 `ptmp/xs/wolf/`；
当前 filelist 统一位于 `ptmp/xs/grhsim-ir/xs_wolf.f`。ROB 提取、写口探针和
Mux1H 普查默认读取 `ptmp/xs/rtl/rtl/`；依赖标量 Rob 端口的旧整机 trace
targets 已删除。masked-OR 覆盖审计需显式指定恢复前的 IR 和对应 report，
避免隐式读取旧 checkpoint。

清理通过新增 Make targets 完成：旧 `build/xs/grhsim-ir-aggr` 和
`build/xs/rtl-aggr` 已删除；新默认目录也在本次生成前清空。不会复用旧 u64
checkpoint。清理日志、完整重跑日志、回归日志和计时位于
[`ptmp/xs-defaults-20261017/`](../../ptmp/xs-defaults-20261017/)。

在已初始化的项目环境中，重跑命令为：

```sh
make clean_xs_wolf_grhsim_ir clean_xs_rtl
make xs_wolf_grhsim_ir_emu run_xs_wolf_grhsim_ir_emu \
  XS_VM_BUILD_JOBS=16 XS_SIM_MAX_CYCLE=100000 RUN_ID=20261017_defaults8
```

`XS_SIM_MAX_CYCLE=100000` 只限制本次验收窗口；标准运行默认仍为执行到结束。
masked OR 单元测试通过（21.84s），HDLBits IR 回归 **162/162** 通过；对应
Make 进程 exit=0，日志为 `tests.log`。

新 RTL 生成 **381.38s**、exit=0，命令确认 `--preserve-aggregate=all`，`Rob.sv`
保留 packed struct 和多维 packed 数组。ingest 45.667s，xmr-resolve 104.971s，
hier-flatten 68.990s。第一轮 mux-tree-fold 恢复 1,149 个写组和 9,429 个 pad
读；register-write-normalize 处理 50,906 个写口、52,383 条保持路径；第二轮
guarded mux-tree-fold 再恢复 83 个写组。统计保存在 `grh-recovery-stats.txt`。

GRH simplify 7 轮收敛，用时 448.671s，随后 GRH 校验、lowering 和 GrhSIM
校验均通过。B7 默认恢复 **4,217** 个 masked OR 区域、**162,574** 个规约项，
删除 337,752 个 op 和 8,450 个数组读；恢复后 semantic seal 校验通过。

CPU mapping 得到 45,583 个超节点、1,090,865 个边界字段、4,209 个 phase
任务；shared-boundary cloning 消除 33,571 个边界值。活动位图两组各 5,698
字节（合计 11,396），生成头文件 `model/grhsim_SimTop.hpp` 明确声明：

```cpp
std::array<std::uint8_t,5698> nonSinkActiveFlag{};     // supernodes=45583
std::array<std::uint8_t,5698> nonSinkActiveFlagNext{}; // supernodes=45583
```

发射 1,207 个 C++ 编译单元，用时 94.569s；`target_batch_count=0`，mem writes
141,847，mem readers 168,036,924。完整 pass 计时和计数在
`ptmp/xs/logs/xs_wolf_grhsim_ir_20261017_defaults8.log`。

SV ingest 到 checkpoint 往返校验共 **1497.867s**，exit=0；新 checkpoint 在
独立会话中加载并重新保存后，JSON 字节完全一致。首轮接续 emu 构建暴露根 Makefile
未导出默认性能宏，子 Make 得到空的 `-DWOLVRIX_GRHSIM_PERF=`。已在根 Makefile
导出默认值 0；通过 `make xs_wolf_grhsim_ir_build_emu run_xs_wolf_grhsim_ir_emu`
继续构建同一份新模型，日志为 `build-run.log`，编译参数确认性能统计关闭。

构建和首次运行合计 699.11s，其中仿真 Host time **362.962s**，构建约
336.15s。当前二进制的独立核查运行 Host time **368.122s**，wall 368.16s，
CPU 99%、exit=0；见 `audit-run.{log,time}`。这两个结果没有证明达到 280 秒，
也不构成新旧版本性能 A/B。

模式保护和路径删除后，最终复测命令为：

```sh
make run_xs_wolf_grhsim_ir_emu \
  XS_SIM_MAX_CYCLE=100000 RUN_ID=20261017_aggregate_only
```

复用本次全量生成并核对过 pass 命中的当前 aggregate 模型，默认 CPU 2、NEMU
difftest 开启，关闭 waveform、commit/RAM trace 和 GrhSIM perf，不重测旧版本。
计时和日志位于 `aggregate-only-run.{log,time}`。

最终 Host time **365.708s**，wall **365.75s**，CPU 99%、exit=0。
NEMU difftest 无失配，周期上限端点为 `instrCnt=225471 / cycleCnt=99996 /
guestCycles=100001 / pc=0x800010e2`。当前 aggregate 路径仍约 366 秒，
未测得 280 多秒。此次是当前版本的单次 100k 周期复测，没有运行旧版本。
标准仿真日志为 `ptmp/xs/logs/xs_wolf_grhsim_20261017_aggregate_only.log`。

选项核对依赖真实生成产物：B7 的 4,217 个 masked-OR 区域、50,906 个规范化
写口及两轮动态写组恢复均有日志命中；`cpu.st.clone-shared-boundaries` 实际
使用 `lossy-compare=1`，克隆 109,651 项。生成头文件的 large-sink
`enabledWords` 有 932 个 u64 字，证明内存 enable bitmap 已发射；头文件
记录 on-write 激活选项，活动位数组明确为 uint8。bit 寄存器打包 pass 也已
运行，但此 aggregate 输入的 `packed_register_bits=0`，与活动位打包无关。
摘录见 `effective-optimizations.txt` 和 `grh-recovery-stats.txt`。

写口和 Mux1H 验证：`make test_grh_register_write test_grhsim_masked_or` 全通过；
masked-OR 测试用时 20.24s。`make test_benchmark_grhsim_ir test_xs_mux1h_census`
共 6 项通过；`make test_xs_workflow` 的 3 项保护测试通过，覆盖旧模式拒绝、
现有 scalar/失败/伪前缀 RTL 记录拒绝、成功 aggregate 记录接受，以及 16 个
旧目标不存在。日志为 `optimization-tests.log`、`workflow-tests.log` 和
`aggregate-workflow-tests.log`。流水线另输出结构化 CPU 配置，显式列出实际
GRH pass、masked-OR、clone、simplify、store 和 emit 选项，便于后续核查。
