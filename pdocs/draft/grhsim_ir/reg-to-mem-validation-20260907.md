# reg-to-mem 实施验证记录

状态：pass 已实现，当前源码的 Xiangshan CoreMark 50k 开关对照及回归已通过。
对应 [pass 草案](reg-to-mem-pass-plan-20260907.md)。支持边界与性能证据的限制见下文。

## 22:26 独立复测结果

本次对当前源码与同一对 ELF 重新进行固定 CPU 2、串行关闭/开启/开启/关闭的四次 50k
对照。全部 exit 0、difftest 通过，终点均为 73580 instructions，commit/trap PC 与下表
首轮交付相同。关闭分别 360710/355629 ms，开启分别 283591/282440 ms；中位数
**358169.5 → 283015.5 ms**，耗时下降 **20.98%**，约 **1.266×**。

本次补跑语义测试、8 类 ASan/UBSan 生成模型以及四类 RTL/Verilator 8192 samples 对照，
全部通过；源码与 ELF hash 在性能测试前后均匹配。未重跑此前通过的 162 项 HDLBits。
日志和完整报告见 [复测报告](../../../ptmp/reg_to_mem/recheck_20260907/report.md)，机器可读数据
见 `ptmp/reg_to_mem/recheck_20260907/benchmark/{results,summary}.json`。
两批独立计时共同支持当前实现约 21%–22% 的 50k 耗时改善，不将结果解释为完整 CoreMark 完成。

## 首轮交付结果（20:53）

最终验证目录为 `xs_expanded/`，对应 `expanded_source.sha256`。固定 CPU 2、串行执行
disabled/enabled/enabled/disabled，每次 50000 host/model cycles，四次 exit 0，difftest
均启用且无 mismatch。指令数均为 73580，commit PC `0x800012f8`、trap PC `0x80001312`。
这是 50k cycle-limit 验证，不是完整两次迭代 CoreMark 结束。

| 当前版本运行 | 50k host time (ms) | 首 10k (ms) |
| --- | ---: | ---: |
| disabled_0 | 360081 | 54106 |
| enabled_0 | 283124 | 47834 |
| enabled_1 | 276822 | 46780 |
| disabled_1 | 360401 | 53990 |

50k 耗时中位数：关闭 **360241 ms**、开启 **279973 ms**，下降 **22.3%**，约 **1.29×**。
结果来自 `benchmark_expanded/{results,summary}.json`，session `73154` 已明确 exit 0。
每次完整命令、解析后的 ELF 路径和 SHA-256 均保存在 results.json；没有并行构建/测试。

开启版本 ELF SHA-256：`eaff03003d5c21842b094be7091bd50c6670cf35e58bf6b13c82aebbdef01f64`。
关闭版本 ELF SHA-256：`7e32d923e94d5d9ea6937e3850fc9ef4aa50236057eaf641dab265d1c7c51971`。
后续章节保留各中间版本的试验过程，不能用它们的计数或性能替代上述当前结果。

## 输入与版本

真实模型输入为 `build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json`，复用既有 flat GRH
checkpoint，不调用 legacy reg-to-mem。原 GrhSIM checkpoint 为 `ptmp/xs_ir_gate67.json`，
包含 695,052 个 state、4,981,305 个 op。

以下输出目录对应不同 pass 版本，不能混用运行证据：

| 输出目录（均相对 `ptmp/reg_to_mem/`） | 实现范围 | 验证状态 |
| --- | --- | --- |
| `xs/` | 写合并、fill、同址融合、共享/重复整元素索引读 | 生成、编译、CoreMark 50k 均成功 |
| `xs_windows/` | 额外支持单 bit 表动态窗口和 `sliceStatic(lshr(...))` | 生成、JSON 往返及 emulator 编译成功；未跑 50k |
| `xs_shared/` | 窗口地址表达式及同表同地址读共享 | 生成及 JSON 往返成功 |
| `xs_final/` | 在共享版上修复 `[base,2^64)` 写域检查溢出 | 生成及最新 RTL/CPU 回归成功；emulator 编译成功 |
| `xs_off/` | 同源码、同输入，显式关闭 reg-to-mem | 基线生成与编译成功，用于固定条件开关对照 |
| `xs_expanded/` | 增加成本筛选、统一 preflight、非周期视图、多 bit 元素窗口与拒绝诊断 | 生成、JSON 往返、语义/RTL/HDLBits 回归、emulator 编译及独立两轮 50k 对照通过 |

## 第一版 CoreMark 50k

命令通过项目 Makefile 执行：

```bash
make --no-print-directory run_xs_wolf_grhsim_ir_emu \
  XS_GRHSIM_IR_BUILD=ptmp/reg_to_mem/xs XS_LOG_DIR=ptmp/reg_to_mem \
  XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=1000 \
  RUN_ID=20260907_reg_to_mem_50k
```

工具 session `15183` 返回 exit code 0。日志 `ptmp/reg_to_mem/coremark50k.log`：

```text
host_cycles=50000 model_cycles=50000 instr=73580
commit_pc=0x800012f8 trap_pc=0x80001312
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Host time spent: 651925ms
```

difftest 使用 `ready-to-run/riscv64-nemu-interpreter-so`，首条指令提交后启用，无 mismatch。
终止原因为到达 50k cycle 上限；不能表述为完整两次迭代 CoreMark 已结束。
历史 gate67 日志的最终指令数、PC、cycleCnt 与本次一致；历史 host time 为 659545 ms。
本次运行期间还有测试及生成任务，且误启动的重复运行在确认后被终止，耗时仅供记录，
不作为有统计意义的加速结论。重复运行 `82746` 已返回 130，原运行未中断。

## 结构与生成

第一版 pass 用时 10857 ms，加载/lower/pass/emit/JSON 往返共 84362 ms，输出
462,916 个 state、4,371,026 个 op。报告 `xs/reg_to_mem.tsv` 包含：

- 1,400 组写合并，覆盖 79,332 个标量元素。
- 2,790 组读恢复，覆盖 37,112 个标量元素。
- PHR 532 行、TAGE 512 行、FTQ 多字段、RenameTable difftest table 均有写族命中。
- PHR 为一个 532 行 array、一个 41-triple sequence、一个 fill。43 个规划分支包含 fill
  分支，不能等同于最终 sequence 长度。

窗口版 pass 用时 11700 ms，完整生成共 90741 ms，输出 462,420 个 state、4,420,477 个 op。
JSON store/load/store 字节一致。PHR 数组有 3,482 个 read op；窗口拆成独立 bit read 后
数量会增加，尚需分析剩余固定行读和重复地址计算成本，不能仅凭读网络变换认定收益。
相关日志：`generation_windows.log`、`phr_windows.log`、`build_windows_emu.log`。

共享版 op 数降至 4,341,582。`xs_final/` 的生成记录在 `generation_final.log`：pass
11739 ms，脚本全流程 92553 ms，包含 Makefile 依赖安装的 wall time 108.01 s，整个命令
峰值 RSS 28,316,948 KiB。来源 hash 记录在 `final_source.sha256`；`build_final_emu.log`
记录编译日志及计时。编译 session `60629` 已返回 exit 0，wall time 15:52.47，
user time 5837.48 s，最大单进程 RSS 905,596 KiB（不代表所有并行 compiler 的内存总量）。
较早的窗口编译 session `10787` 已 exit 0；关闭 pass 的基线编译 session `68194` 也已
返回 exit 0，wall time 15:52.62，user time 5953.32 s，最大单进程 RSS 913,200 KiB。
两次编译存在重叠负载，不能用这些 wall time 宣称编译速度改善。

最终候选与关闭 pass 的 JSON counts：

| 项目 | 关闭 | 开启 |
| --- | ---: | ---: |
| state | 695,052 | 462,420 |
| op | 4,981,305 | 4,341,601 |
| value | 4,677,017 | 4,114,938 |

关闭 pass 的生成脚本耗时 98387 ms，完整 Makefile 命令 wall time 105.97 s，峰值 RSS
28,306,784 KiB。编译期间存在并行任务，生成耗时仅用于记录，不作为严格速度比较。
`final_arrays.tsv` 是输出 checkpoint 的数组访问统计：4,196 个恢复数组、116,946 行，
包含 38,747 个普通 memWrite、251 个 sequence（合计 1,180 个三元组）及 323 个 fill。
通过原 StateId 定位的 PHR `__reg_to_mem_53162` 是 41-triple sequence、1 fill、532 个固定读
和 824 个动态读；另一个 532 行表的 2-triple 数字不能代替 PHR 统计。

已增加 `benchmark_grhsim_reg_to_mem`，顺序执行两轮关闭/开启 50k，轮间反转顺序，
固定 CPU 2。它逐次要求 exit 0、明确 50k 终点、difftest 已启用、无 mismatch，保存
`results.json` 和最终中位数 `summary.json`；各版本终点指令数/PC 不一致则失败。
两个编译 session 明确成功后，已通过 Makefile 启动对照，session `55550`。
总日志 `benchmark.log`，分次日志位于 `benchmark/`。运行顺序为 disabled_0、enabled_0、
enabled_1、disabled_1；session `55550` 已返回 exit 0，结果见下表。

首轮 disabled_0 已完成：exit 0，50,000 cycles，73,580 instructions，host time
362,802 ms，difftest 启用且无 mismatch。结果由脚本保存于 `benchmark/results.json`；
四次均通过 50k difftest，终点指令数和 PC 一致。

| 固定 CPU 2 的运行 | host time (ms) | 首 10k (ms) |
| --- | ---: | ---: |
| disabled_0 | 362802 | 54033 |
| enabled_0 | 294584 | 48606 |
| enabled_1 | 292471 | 48743 |
| disabled_1 | 356511 | 52481 |

中位数：关闭 359656.5 ms、开启 293527.5 ms；开启/关闭比 0.8161328935，耗时下降
18.4%（约 1.23×）。此结果仅适用于 `xs_final` 对应的冻结实现。四次均为 cycle-limit
终止，并非完整 CoreMark 两次迭代完成。计时期间未启动新编译，只有源码阅读与编辑。

## 小模型验证

通过的项目 Makefile targets：

- `test_grhsim_reg_to_mem`：scalar/array 状态转移对照、幂等、拒绝不变、init、history、mask、
  地址域、全局 else-if、多事件/异步 reset、共享/重复读、部分窗口越界和 UINT64_MAX。
- `test_grhsim_reg_to_mem_generated`：优先级写、整元素读、动态 bit 窗口、移位后静态窗口四种
  生成模型，各与原 scalar trace 比较 4,096 次输入，启用 ASan/UBSan。日志 `window_tests2.log`。
- `test_grhsim_cpu_mapping`、`test_grhsim_cpu_emit`、`test_grhsim_cpu_schedule`：已有基础设施回归。
- `test_grhsim_reg_to_mem_rtl`：显式标量 SV 经 ingest/lower/pass/emit 后与 Verilator 比较
  8,192 次输入，覆盖 PHR 异步 reset/窗口、TAGE 复合 clear、65 位 FTQ、RenameTable 逐行读。
  四类写族均要求报告出现 `merged`。日志 `rtl_test.log`。测试先用低电平 eval 建立一致的
  初始事件采样，再施加 reset；首版 generate-local fixture 的 ingest 失败未被当作 pass 失败。
- `run_all_hdlbits_grhsim_ir_tests`：session `96565` 已返回 exit 0；日志
  `hdlbits_ir.log` 含 DUT 001–162 共 162 个运行入口，Makefile 对任一失败立即返回非零。
  产物目录 `ptmp/hdlbits-grhsim-ir-mm14HK`。
- 补充 `test_grhsim_reg_to_mem` 的 DPI 与拒绝路径回归：有事件的无返回值 DPI 调用读取四行
  旧状态，对照 4,096 次随机输入中的每次调用次数、参数和可见输出；随机初始化及不一致
  事件定义的整组拒绝要求 JSON 字节不变。session `67798` 返回 exit 0，测试耗时 0.62 s，
  日志 `dpi_rejection_tests.log`。这部分修改仅涉及测试，原 pass/source hash 校验仍通过。

## 支持边界与测量限制

当前版 50k 已提供整体性能证据，尚不能把总收益分解为每个表的 staging、publish 或
reader activation 收益。成本估算为静态启发式，活动度与跨不同 packed value 的共享成本
未完整建模；报告对此明确标记 `activity unknown`，并提供关闭成本筛选的开关。
当前扩展版编译成功，独立采集的生成模型编译 wall/RSS 已完成，结果见文末；早期版本的编译计时在本文保留，
存在并行负载，不能拿来宣称新版编译加速。收益结论仅指上表的 50k 运行时间。

四态、随机初始化、任意稀疏映射、masked sequence 扩展按草案保留原语义；超过 8 段的
读映射与宽于 64 bit 的动态窗口保留原 packed 计算。PHR 的 41 个实际写源未强制压到
历史分析中的 28/15 个；额外融合必须有对应地址/覆盖关系证明。

### 当前源码逐项审查（2026-09-07）

| 草案要求 | 当前证据与差距 |
| --- | --- |
| 选择收益明确的计划 | 新增写/读/组合三种方案，按真正失去用户的 DAG 节点估算收益，计入 guards、映射、fill、固定读；活动度权重与跨不同 packed value 的共享尚需校准 |
| 分析与实施使用相同 preflight | 两条路线共用 `Engine::prepare`，全部候选先规划后修改；重叠读写候选的报告一致性测试通过 |
| 诊断被排除的候选 | 新增 `excluded-state` 聚合行，记录 type/init/unknown-state-user 等拒绝计数和示例；真实 checkpoint 报告已有输出 |
| 非周期/边缘重复读映射 | 最多 8 段连续/重复行的显式映射，保留周期快速路径；语义及 ASan/UBSan 生成代码回归通过 |
| 多 bit packed lane 投影 | 跨元素 bit 窗口先做原 bit 域检查再计算行与行内偏移；2/3/5 bit 元素语义回归及 3/5 bit 生成代码回归通过 |
| 副作用与拒绝保持 | 事件 DPI 调用轨迹、random init/event mismatch、未知方言直接引用状态的拒绝测试均通过；报告失败的 poison 契约测试通过 |

上表分别记录语义支持和启发式的适用范围；50k 不能代替局部等价性测试。
后续若修改 pass，须记录新版本并重新验证受影响的真实模型。

`Engine::prepare` 修改发生在 `xs_final` 已生成、编译并开始对照之后。因此当前对照仍验证
`final_source.sha256` 对应的旧实现，不能直接作为这次 preflight 修改的证据。为了减少计时
干扰，在对照结束后才启动 `test_grhsim_reg_to_mem_generated`（session `60939`，日志
`expanded_tests.log`）。新增映射和默认收益筛选会影响生成结果，需要新的 Xiangshan 输出目录
和对应端到端验证；不能直接把以上 18.4% 归给当前开发版本。

### 扩展版当前进展

- session `60939` 已 exit 0：`test_grhsim_reg_to_mem_generated` 的语义测试通过（0.63 s），
  八类生成模型各 4,096 samples，在 ASan/UBSan 下通过。包括 `edge_window`、`overlap`、
  `multi_bit_window` 和 `multi_bit_shift`。语义测试显式关闭收益过滤来强制覆盖转换；另有
  默认收益选择测试，要求小型昂贵窗口拒绝不变、32 行动态写被接受并保持状态转移。
- session `65739` 已 exit 0：`rewrite_grhsim_reg_to_mem` 在 `ptmp/xs_ir_gate67.json` 上重写后
  verifier 通过；state 695052 → 466444，op 4981305 → 4333573。候选报告
  `expanded_candidates.tsv`：1115 组 merged、712 组 indexed-read、3661 组 cost。
  PHR 532 行选择 writes+reads，TAGE 512 行组命中，RenameTable 32 行选择 writes。
- `make py_install test_grhsim_reg_to_mem_rtl` session `72878` 已结束：绑定安装成功，RTL 流程
  在要求小夹具必须转换的结构断言处失败，因为默认收益选择拒绝了 8 行 PHR/RenameTable。
  这是成本筛选结果，尚未进入仿真对照。测试脚本显式关闭收益过滤后，session `14156`
  exit 0，四类标量表的 8,192 samples 与 Verilator 一致（`expanded_rtl_forced.log`）。
  生产默认收益筛选不变，另由 C++ cost selection 测试及真实模型评估。
- session `54424` 已 exit 0：新增 CPU mapping 失效测试通过，先建立 split-phase mapping，
  再运行 semantic reg-to-mem，检查 mapping 清除、revision 恰好加一及幂等性。
  日志 `expanded_mapping_test.log`，测试耗时 0.64 s。
- 新版本完整生成 session `84291` 已 exit 0，目录 `xs_expanded`、日志
  `generation_expanded.log`，使用同一 flat GRH、默认成本筛选与 CPU target batch count 0。
  `expanded_source.sha256` 记录 pass、model 和 pipeline 源码；本次直接复用刚安装成功的绑定，
  Makefile 参数 `XS_WOLF_DEPS=` 避免无意义的重复安装。
  pass 10479 ms，全流程 86088 ms，CPU emit 与 JSON store/load/store 字节一致检查通过。
- `test_grhsim_cpu_mapping test_grhsim_cpu_schedule` 已返回 exit 0，日志
  `expanded_cpu_tests.log`。
- `xs_wolf_grhsim_ir_build_emu` session `44873` 已 exit 0，日志 `build_expanded_emu.log`。
  输出数组统计 session `46256` 已 exit 0，产物 `expanded_arrays.tsv`。
  `expanded_source.sha256` 全部校验通过，ELF 为 135707528 bytes。
- 新版对照 session `73154` 已 exit 0，固定 CPU 2、每版两次 50k，日志
  `benchmark_expanded.log` 与 `benchmark_expanded/`。使用
  `GRHSIM_REG_TO_MEM_BENCH_ENABLED=ptmp/reg_to_mem/xs_expanded`（实际命令传绝对路径）。
  脚本在计时前记录每个 ELF 的解析路径和 SHA-256，并要求 host/model 均到达 50000；
  每次结果还记录完整命令和 returncode。禁止覆盖此前 `benchmark/` 的旧版本记录。
  首轮 disabled_0 已通过 50000 host/model cycles，73580 instructions，host time 360081 ms；
  enabled_0 同样通过，host time 283124 ms；enabled_1 已通过，host time 276822 ms，
  disabled_1 也已通过（360401 ms）。四次终点 PC/指令数一致，以
  `benchmark_expanded/results.json` 和分次日志为最终数值来源，最终中位数见文首。
- session `95830` exit 0：`opaque_failure_tests.log` 验证自定义 `observer.state.inspect`
  直接引用原状态时 JSON 不变；报告目录不可写作文件时，semantic 修改失败由 manager poison，
  analysis 失败保持未 poison，测试耗时 0.68 s。
- session `22489` exit 0：动态掩码单写（含 1 bit 元素）以及表内独立事件的固定写回退、
  额外整表 packed 输出对照通过；日志 `mask_event_tests.log`，0.75 s。
- session `20268` exit 0：CPU emitter 全套回归通过（67.80 s），日志 `expanded_cpu_emit.log`。
- 当前生成模型数组统计：1827 个恢复数组、113458 行；25093 个固定读、3321 个动态读、
  37124 个普通写、224 个 sequence（1117 个三元组）、130 个 fill。PHR 精确定位
  `__reg_to_mem_53162` 为 532 行、532 固定读、824 动态读、41-triple sequence、1 fill。
  `model/grhsim_SimTop.hpp` 的 `cpu_stage_cell` 按 cell 字节长度 memcpy 到 shadow，重复写
  复用 dirty key；已有 `cpu_memory_readers`/`cpu_read_offsets` 用于按实际读 cell 激活。
  本 pass 没有修改 runtime helper ABI。

相对未优化输入，扩展版 state 数下降 32.9%，op 数下降 13.0%。状态数不是性能验收指标；
其中 532 个 PHR 固定读仍存在，不能表述为整个 PHR 读网络都已消除。
- 新版 HDLBits 全套回归 session `59213` 已 exit 0，162 项均通过（`expanded_hdlbits.log`）；须与此前
  冻结实现的 `hdlbits_ir.log` 区分。
- 同址融合干扰测试：三个逻辑写源依次为地址 a、地址 b、地址 a，穷举使能/地址/数据后
  与 scalar 对照，并要求保留三个三元组。首次 fixture 在各行单独创建相同 XOR value，
  因写族数据 value 不共享而未命中；改为共享逻辑数据源后 session `14817` exit 0，
  `fusion_interference_tests2.log`，全部语义测试 0.81 s。未修改 pass 实现。
- 编译资源补测 session `99692` 已启动，通过 `measure_grhsim_reg_to_mem_build` 对同一对
  生成 C++ 依次 disabled/enabled 做四并行冷构建，目录 `build_metrics/`、总日志
  `build_metrics.log`。只复制源文件和生成的 Makefile 到新目录，保留已经验证的模型和 ELF。
  `/usr/bin/time -v` 记录各版本 `time.txt`，其 RSS 是最大子进程值而非并行总 RSS；此指标
  只包括生成模型库编译，不包括 GRH lower/emit 或 difftest harness 链接。2026-09-07 复核时，
  总日志已包含两个 `done`，两份 `time.txt` 的 `Exit status` 均为 0，结果见下表。
- 补充改名不影响写族发现、缺少可写 row 0 时外部常量输出不变的测试已通过，session
  `97764` exit 0（0.78 s，`name_zero_tests.log`）；不改变当前 emulator 对应的 pass/source hash。

### 交付验收对应关系

| 草案章节 | 证据 | 当前判定 |
| --- | --- | --- |
| 1–3：core semantic pass、双侧发现、真实 array 所有权 | registry/CMake 接入、XS 与 HDLBits CPU mapping 前调用；真实 checkpoint 写/读报告 | 已实现；legacy pass 保留独立入口 |
| 4：行映射、字段、共享/重复/重叠视图 | PHR/TAGE/FTQ/RenameTable 真实命中，连续偏移与分段视图语义/生成测试 | 有限预算内实现，稀疏/任意多维展平保持后续范围 |
| 5：update+next、顺序写、fill、mask | 全局 else-if、行 blocker、同/异址穷举；动态 mask、异步 reset、RTL 8192 samples | 已验证支持路径；masked sequence 保守拒绝 |
| 6：全部读用户、越界与旧状态 | shared/repeated/partial windows、UINT64_MAX、整表输出、事件 DPI 对照 | 已验证支持路径；复杂映射和宽于 64 bit 的窗口保留 packed 计算 |
| 7：初始化、history、所有权、副作用 | 非均匀 const、不同 history 初值拒绝、random init 拒绝、未知方言引用不变、事件历史与 DPI | 已验证已列测试；随机初始化不转换 |
| 8：rewrite/compact、revision、mapping、失败契约 | compact 悬空引用拒绝、JSON 往返、幂等、mapping 清除、报告失败 poison 测试 | 已验证 |
| 9：收益与后端配合 | 三方案估算、cost 拒绝不变、实际数组访问计数、cell staging 源码检查 | 启发式已实现，当前版 50k 总耗时下降 22.3%；未做逐表活动度归因 |
| 10：生成回归与真实模型门槛 | 8 类 ASan/UBSan、Verilator、162 项 HDLBits、真实模型 verifier/emit/JSON/emulator 编译 | 当前版两轮开关 50k 对照全部通过；编译时间/RSS 限制见上文 |
| 11：实际形态与阈值校准 | PHR 保留实际 41 triples，未凭源码指针不变量强行降到 15；四类实际结构报告 | 同址/回绕专用证明不作为基础恢复前提；阈值仍须当前版测量 |

成本指标是启发式而不是等价性条件。`activity unknown` 明确标记尚未建模的活动度项；
现有后端逐 cell 发布降低整表复制成本，但此源码检查不等同于各目标表 runtime profile。

### 生成模型库编译资源补测结果

本表补全此前已启动的 `build_metrics/` 顺序构建结果，并非新启动的编译。
两版均使用生成 Makefile、`clang++ -std=c++20 -O3`、四个 compiler jobs；目录初始无对象文件。

| 指标 | 关闭 pass | 开启扩展版 | 变化 |
| --- | ---: | ---: | ---: |
| wall time | 1417.89 s | 1344.16 s | 减少 5.20% |
| user + system CPU time | 5584.01 s | 5105.77 s | 减少 8.56% |
| 最大子进程 RSS | 914472 KiB | 920948 KiB | 增加 0.71% |

来源：`ptmp/reg_to_mem/build_metrics/{disabled,enabled}/time.txt` 和 `build_metrics.log`。
每版仅测一次；wall time 受系统负载影响，不能声称有同等幅度的稳定构建加速。
最大子进程 RSS 不是并行构建总内存，也不是 emulator 运行内存。
