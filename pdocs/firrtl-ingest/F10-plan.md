# F10：香山混合输入与正确性推进

状态：实施中。F09.6 已完成，node 合约不再改回 op/work 容量。
有可用 FIRRTL 提示的区域按提示形成 node，剩余区域按 MFFC 形成 node；
supernode 仅按 node 数分组。simplify 不受提示边界约束。

最新执行约束：先跑通整机，不提前开展额外优化探索。FIRRTL 到 C++ 生成
总时长上限为 20 分钟，超时立即终止；不能拆分或恢复阶段来重置总计时。
最近终止的 full34 已在 2026-11-01 08:36:38 UTC 左右由完整 producer 的
20 分钟 SIGKILL 终止，外层 Make 于 08:36:39 UTC 返回 2，内部 Error 137。
converted 单轮 simplify 总耗时 233906 ms，nonsink 分区已完成 108280 ms，
随后 sink 分区未完成即超时；尚无整机 C++、emu 或运行结果。八组状态模型
和 bytes/短名称 CLI 回归已通过；full35 沿用七阶段 raw GRH 和单轮 simplify，
仅选择现有 bytes 成本模型并关闭 readable names。producer 约 08:39:22 UTC
开始，硬截止约 08:59:23 UTC，整机效果待验证；不增加原生优化、不改变
默认 full、不续跑 checkpoint。完整终止记录见
`ptmp/firrtl-ingest/F10/full34-stop-reason.txt`。

## 推进顺序

1. 将显式 mixed sources manifest 接入 `wolvrix_xs_grhsim.py`，复用 GRH
   和 GrhSIM flow，保留现有 SV 入口。记录 FIRRTL、辅助 SV、选项和依赖身份。
2. 增加独立 `xs_firrtl_inputs`、`xs_firrtl_grhsim_emu`、
   `run_xs_firrtl_grhsim_emu`。生成只走 Chisel 的 FIRRTL 输出，构建/运行
   不依赖 `XS_SIM_TOP_V`、`check_xs_aggregate_rtl` 或 firtool。
   FIRRTL 内联/资源黑盒由 native mixed ingest 按可达层次加载，
   不扫描并重新导入整套生成 SV。
3. 先用 RenameTable、ROB 和 memory 代表模块验证两条输入路线，
   检查真实绑定、flatten 后提示及 effects/初始化策略。
4. 整机读取、初始化、短前缀，再固定 CoreMark 100k cycles + NEMU。
   node off/prefer 在同一优化图上比较，逐步启用提示。
5. 记录命令、输入身份、日志和未解释差异。全部退出条件通过后才验收 F10，
   F11 才讨论正式吞吐与构建成本。

## 验收原则

- 模块通过不能替代整机通过；生成脚本单元测试不能替代真实混合输入。
- assert、DPI、invalid/init 和观察配置逐项记录，不沿用旧前端迁移豁免。
- 保留数组并展平 Bundle/struct；通过现有 ABI adapter 绑定辅助 SV。
- 未解释行为差异解决前，不报告性能收益，不将 F10 标记完成。

## 独立生成、冻结输入与 harness 身份

未指定 `XS_FIRRTL_INPUT` 时，输入清单和 harness 快照入口都通过 phony `xs_firrtl_rtl`
委托香山 Makefile 检查原有依赖是否需要更新；已有 `.fir` 不会跳过该检查。
该目标使用 `CHISEL_TARGET=chirrtl RTL_SUFFIX=fir FIRTOOL=`，输出位于
`XS_FIRRTL_RTL_BUILD`。显式设置 `XS_FIRRTL_INPUT` 表示使用冻结文件，
入口只检查其存在，不隐式重新生成；生成新 CHIRRTL 应单独调用
`make xs_firrtl_rtl`，不能据此改写冻结输入的身份。

`XS_FIRRTL_SV_SOURCES` 默认只显式列出 Difftest common 中真实的
`SimJTAG.v`；其余外部实现由冻结 FIRRTL 的 BlackBox annotations 提供。
此清单不扫描 common 或生成 SV 目录，缺少默认辅助源时在创建 manifest
阶段失败。需要自定义辅助源的配置可显式覆盖该变量。

Chisel 的 Difftest C++ 资源仍写入共享 `NOOP_HOME/build/generated-src`。
`make xs_firrtl_harness_inputs` 首次将 `XS_FIRRTL_HARNESS_SOURCE`
（默认 `XS_DIFFTEST_GEN_DIR`）中的全部文件复制到
`XS_FIRRTL_HARNESS_INPUTS/generated-src`（默认当前 flow 的
`harness-inputs/generated-src`），缺少 `difftest-state.h` 时拒绝建立快照。
`snapshot-identity.json` 记录 FIRRTL SHA-256、原资源目录、快照目录及逐文件
身份。后续调用验证快照和 FIRRTL，继续使用已保存资源；共享目录被另一次
生成覆盖不会换掉快照。FIRRTL 或快照内容变化时拒绝复用；显式设置
`XS_FIRRTL_HARNESS_REFRESH=1` 才重新配对，并将旧快照归档至 `snapshots/`。
首次捕获与刷新记录的是当时提供的文件配对，不证明资源来自同一次 elaboration。

`xs_firrtl_grhsim_emu` 先完成快照，再递归生成模型，将快照目录放在 native
include 搜索路径首位，最后构建 emu；递归 build-only 显式固定
`XS_FIRRTL_HARNESS_REFRESH=0`，使一次 refresh 在模型和 harness 阶段使用同一快照。
build-only 入口也校验快照，并将
`GEN_CSRC_DIR` 指向快照。`build-identity.json` 另记当前 Difftest
config/csrc/Makefile、工具与构建选项，历史保存在 `build-identities/`；
同内容保持 mtime，作为 `THIS_MAKEFILE` 前提让 harness 对象在身份变化时
重编。公共 harness 源码变化会记录新构建身份及
`common_harness_matches_capture=false`，不据此宣称与旧模型设计匹配。
生成模型库自身 Makefile 的编译选项追踪没有在本项扩展；本项按 F10 新目录首次构建设计。

构建身份还记录 `NO_DIFF`、PGO、EMU 等 harness 环境选项，以及从 GNU Make
`MAKEFLAGS` 提取并按名称排序的 CLI 变量覆盖。保留值中的空格和引号，忽略
jobs、jobserver 与 output-sync 调度选项；因此改变编译配置会更新构建身份，
仅调整并行度或 CLI 变量顺序则保持身份和 mtime，均不改写 FIRRTL/资源快照。
`harness-make-overrides-tests.log`：经 `make test_xs_firrtl_workflow
SKIP_PY_INSTALL=1 PYTHON=.venv/bin/python` 的 28 项回归全部通过，包含真实
Make CLI 的 `NO_DIFF` 切换、带空格和引号的 flags、身份/mtime 稳定性，
以及生成期间共享资源被覆盖时 refresh 只捕获一次快照的检查。

`full-retry12` 在 ingest 已经运行后才补建 harness 快照，无法追溯证明此前
读取过程使用了该快照。该任务继续使用下文列出的冻结 FIRRTL；独立 Chisel-only
输出是另一份字节身份不同的文件；补建快照不证明两份输入相同，也不证明资源
与冻结输入来自同一次 elaboration。

## 当前实施记录（未验收）

工作目录 `ptmp/firrtl-ingest/F10/`。

- 已接入 mixed manifest 与独立 Make 入口；SV 入口仍走原有文件清单。
- `chisel-only.log`：`CHISEL_TARGET=chirrtl RTL_SUFFIX=fir` 实际生成
  1.6 GB `SimTop.fir`，生成目录无 `.sv/.v`；Chisel 7.3.0 的 CIRCT stage
  在 CHIRRTL target 下直接返回，不启动 firtool。Wolvrix 自身不链接 CIRCT。
- `workflow-tests.log`：原有 5 项和新的 3 项工作流检查通过。
- `semantic-tests.log`、`compiled-regressions.log`：跨层次 Reset 推导、
  经普通 wire 连接的常量数组复位、已有 state/mixed 编译执行通过。
- `effect-tests.log`：ifelsefatal 格式实参编译执行和精确 stderr 校验通过。
- `width-tests.log`：局部 const wire 的声明外层 when 不参与其初始化条件。
- 独立入口默认显式启用 `Verification.Assert/Assume/Cover`，保存
  unknown init/invalid 策略；不通过关闭层或效果绕过读取问题。
- full16 已完成整机 mixed ingest，后因 flatten 的元数据累计处理成本
  主动中止；批量导入和源图冻结修复后的 full18 已完成读取、flatten 和
  GRH 验证，随后因 checkpoint 导出的内存增长主动中止。代表模块的验证范围见
  下文，完整 emu 和 CoreMark100k/NEMU 尚未通过，F10 仍实施中。

### 2026-11-01 复验

- 新增真实模块比较器、独立 SRAM 记分板和 ROB 活动门槛，覆盖范围与结果见
  [F10-components.md](F10-components.md)。旧模型 10k 重放中，RenameTable
  比较 14,228,608 个跨路线输出位，另比较 19,984 个 native Probe 位；
  SRAM 比较 1,651,308 位，均无差异。ROB trace 前
  512 cycles 没有有效入队/写回，默认窗口改为 10k；不能把空闲前缀算作验收。
  后续完整 ROB 10k 的全部有定义输出一致，越界 indeterminate 策略差异
  已逐记录验证；native off/prefer 全域严格一致。原始逐位比较的失败报告
  保留，完整统计和精确源码证明见组件文档，未修改观察 mask。
- `workflow-tests3.log` 的独立生成与 build/run 路径检查通过，后续加入
  比较器损坏数据拒绝及 trace 活动检查，`compare-workflow-tests2.log`
  共 11 项通过。
- `all-native-tests13.log`：`make test_wolvrix` 全量 79 项通过，包含数组
  边界与常量输出 assign 的新增回归。
  `compiled-regressions11.log`：`make test_firrtl_state test_firrtl_effects
  test_ingest_mixed test_firrtl_comb` 编译执行通过。
  `python-regressions11.log`：ingest 8 项、FIRRTL workflow/compare 11 项、
  原 SV workflow 5 项全部通过。
- `instance-boundary-transform.log`、`instance-boundary-native.log`：局部数组
  范围分析将实例视为边界，flatten 后仍检查真实跨模块环；本地真环和
  flatten 后真环仍拒绝。此项修复 `rob-generate10.log` 中实例所有输入
  保守关联所有输出造成的候选环；真实 ROB 复验见 `rob-generate11.log`。
  该次真实 ROB 已成功完成读取并进入共享优化 flow，尚未完成模型执行比较。
- 复位常量证明支持字段、静态元素和 invalid，索引及证明缓存由同模块
  的所有寄存器共享；四态执行回归检查复位数据由已知值变 X。
- `full-retry10` 在确认需要上述修复后主动中止，未生成 emu。
  `full-retry11` 随后发现真实 `FP_INCVT::subRounder` 在 when 内声明的
  instance 输入被错误判定未初始化；instance 与 wire/reg 一样按声明的
  condition depth 判断驱动。执行回归覆盖完整赋值和缺失内层 else 的拒绝例。
  `fp-incvt-production12.log` 已通过该真实模块的生产 mixed/shared flow、
  C++ emit、JSON roundtrip，`fp-incvt-model-build12.log` 编译通过。
  安装这些修复后的整机任务为 `full-retry12`；该次随后在真实外部
  `Mem1R1WHelper` 绑定处退出 2：FIRRTL 保留 `r[0].enable` 的数组 shape，
  SV 使用 `r_0_enable` 端口，而 adapter 尚未映射 Vector 所在的字段层级。
  该次未生成 emu。日志与输入身份存在
  `ptmp/firrtl-ingest/F10/{full,logs}/`。
- `scalarized-abi-tests13.log`：保留数组的 mixed ABI adapter 已补充精确的
  Vector 字段深度，优先使用整数组端口，必要时仅在外部边界按元素拆接。
  1,536 组执行对照覆盖单元素、多维、flip 和输出拼接位序；漏元素、字段
  位置错误、方向/宽度错误、额外端口与名称碰撞均拒绝；native CTest 和
  14 个生成模型编译执行 fixture 均通过。
  `production-mem1r1w13.log` 使用同一冻结 FIRRTL 中真实 `DifftestMem1R1W`
  及内联 `Mem1R1WHelper`，生产 mixed/shared flow、C++ emit、普通 GRH
  roundtrip 和 SinkSchedule 重建以 exit 0 通过，总计 20.330s。
  保留实际 `RAM_SIZE=8793945538560`、4 组真实 DPI read/write 调用、
  4 个同步读寄存器，以及接口和内部的单元素/嵌套数组 shape；
  `production-mem1r1w-model-build13.log` 通过生成模型现有 Makefile 编译
  静态库。此项未执行完整 harness；随后 `full-retry13` 越过该边界，
  在缺少 `SimJTAG` 实现处退出 2，尚未生成 emu。
- `external-inventory13.log`：冻结输入的 10,008 个模块全部可达，521 个
  extmodule 中 520 个带内联实现 annotation，唯一未附实现的是 SimJTAG。
  默认显式辅助清单补入真实 Difftest `SimJTAG.v`，保留其 JTAG/DPI 行为。
  `external-reset-tests14.log`：adapter 改用全层次推导后的接口签名，
  覆盖同步和异步 Reset 穿过中间模块进入外部接口、无时钟异步触发及
  冲突类型拒绝；原 native mixed 与 14 个模型执行 fixture 均通过。
  直接以冻结 SimJTAG 为 top 缺少抽象 Reset 的父层连接，不能独立完成
  接口推导；保留原 extmodule 声明、`TICK_DELAY=3` 和真实 SimJTAG.v 的
  最小 wrapper 在安装14后通过 mixed/shared flow、C++ emit、普通 GRH
  roundtrip 及 SinkSchedule 重建（`production-simjtag-wrapper14.log`，
  exit 0，74ms）。生成代码保留四个输出指针的实际 `jtag_tick` 调用；
  生成模型 Makefile 编译静态库以 exit 0 通过，记录于
  `production-simjtag-model-build14.log`。此项仍未执行完整 harness。
- 真实 ROB 还暴露 dead-root inventory 在每次删 op 时复制、排序累计
  tombstone 的二次复杂度。GRH DCE、mux fold 和 GrhSIM rewrite 改为按
  pass/graph 显式收集并统一发布，保留既有墓碑和单项 API；
  `dead-root-batch-tests.log` 验证去重、retention census、JSON 和生产 pass
  返回前已发布。修复后的 `rob-generate12.log` 已完成原先未结束的 mux
  清理并继续正常 pipeline；这不是 F11 的正式性能消融或 ROB 执行通过。
- `rob-generate12.log` 随后在共享 GRH simplify 中因访问已删除操作退出。
  `redundant-output-repro.log` 用常量驱动两个输出 assign 的小图复现同一
  异常；删除前缓存单用户判断、来源与 node 信息后，
  `redundant-output-fixed.log` 的形状映射 3 项及 simplify 回归通过，
  检查 clone/reparent 和来源信息保留。本次大 ROB 仍未生成模型或执行通过。
- `workflow-regressions12-reference-exit.log`：24 项 FIRRTL 工作流、比较器与
  harness 快照回归通过；包含 reference 子构建失败穿过 `tee` 的退出状态。
  `workflow-regressions12-final.log` 另记录原 SV 工作流 5 项通过。
- `reference/xs_ref_coremark100k.log`：旧预编译 Verilator 参考机（Oct 18）
  在 cycle 10,269 触发 `AheadBtbReplacer.sv:124` 的替换路一致性断言，
  退出 2；NEMU 已启用，但没有完成 100k。此参考机未重新构建，不作为
  当前 native 的通过基线，也不据此豁免 native 断言。
- 当前整机和模块比较明确使用冻结 `ptmp/xs/rtl/rtl/SimTop.fir`
  （1,671,325,062 bytes，SHA-256 `cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`）。
  独立 Chisel-only 输出为另一份输入（1,670,000,014 bytes）；其生成成功
  证明入口无需 SV/firtool，不能把两份输入的字节身份视为相同。

### install14 与整机重试

`all-native-tests14.log` 记录 `make test_wolvrix` 的 79/79 项通过；
`py-install14.log` 的 `make py_install` 退出 0。本次安装同时包含跨层次
external Reset、数组 scalarized ABI 和上述 shared transform 修复。
installed `libwolvrix-lib.so` 的 SHA256 为
`a96819d3d427777310890d30ebbf75188f4c4df6b5225dd47bef5d7a4cf2eca4`。
短 literal 跨 signedness 输出的独立先失败/后通过回归和限制见
[F10-components.md](F10-components.md)；ROB14 native 两模型是 install13
生成，不能据此改写其历史身份。

`full-retry14.log` 使用独立 `full14/` 目录、install14、冻结 FIRRTL 和真实
`SimJTAG.v`，先捕获 harness，再进入 mixed/shared flow。源清单仅两项，
Assert/Assume/Cover 全部启用，init/invalid 均为 unknown。该次保留
`pre-simplify.json` 和 `pre-partition.json` 输出请求，后者用于从同一普通
优化图分叉 off/prefer。该次 ingest 在 1167.517 秒后退出 2，尚未生成
整机 emu：423 个候选环均判为假环，420 个修复，LoadUnit 的三个变体
仍有相同的 74-op 候选环未消除。

`production-loadunit15/driver-exact14.log` 在 install14 上通过生产 Make
入口独立复现 `LoadUnit:7169012:23` 的同一失败；35 行的
`minimal-loadunit-guard.fir` 也产生同类 73-op 假环。模式为先写数组
`[13,21,5]`，再读这三位形成条件，只条件更新不重叠的 `[4]`。
静态 partial connect 原来在拼接后对整数组做 mux，为未写元素添加了
不必要的条件依赖。修复改为只对被写 slice 做 mux，再拼接未写 slice，
保持数组 shape、写优先级和四态合并。此选择也以减少最终 C++ 宽值选择
及复制为目标，生成代码成本对照单独记录，不预先宣称性能收益。

`conditional-array-repro15.log` 的 24-lane 回归先复现失败；修复后直接图、
JSON roundtrip 和 simplify 均与独立位向量预期一致。真实的条件读写同一
lane 仍拒绝。四态检查通过 FourState/Propagate constant fold 验证 unknown
条件的逐位合并；`conditional-array-fourstate15.log` 通过。
`conditional-array-fixed15.log` 的聚合、组合与 memory 检查和生成模型
编译执行通过；`all-native-tests15-final.log` 记录全量 79/79 通过。
`py-install15-venv.log` 安装退出 0；installed `libwolvrix-lib.so` SHA256 为
`d0602e1cdc15e3f40c1a99a225e90c053366f2680245c758c4e475be7634f6cb`。
`production-loadunit-fixed15/generate.log` 的真实 LoadUnit 在 20.220 秒内
完成生产 flow、C++ emit、普通 GRH roundtrip 及 SinkSchedule rebuild；
`build.log` 编译 18 个 TU 并归档模型库，退出 0。原 35 行含真实 array-read
guard 的最小输入也完成生成、roundtrip 和编译，分别见
`minimal-generate.log`、`minimal-build.log`。
`full-retry15.log` 随后以独立 `full15/`、install15 和相同 frozen 输入、
harness 源及验证配置重试整机。该次在同输入机器码成本对照暴露回退后
主动中止，原 session 退出 130，未生成 emu；原因单独保存在
`full15-stop-reason.txt`。

用户明确要求 lowering 以最终 C++ 的指令、分支和访存成本为目标。
`conditional-cost{14,15}/` 固定同一 24-lane 输入及 clang++ `-O3` 配置，
两版均生成、编译成功。虽然仅 guard written-slice 的版本减少源级数组
循环，`pOutput` 的非 padding 静态指令从 281 增为 357，显式带 memory
operand 的指令从 61 增为 71，条件分支均为 0；对象 text 从 4032 增为
4288 bytes。这是该小样例的静态成本回退，不能视为吞吐结论或优化成功。

后续改为连续静态 partial writes 共用 packed accumulator，最终 assign
恢复声明 shape，CHIRRTL memory write data 在叶子边界恢复 shape，避免
每次局部更新都拆装整数组。`packed-native-and-memory16.log` 的 native
79/79 和全部 memory 生成模型编译执行通过；新增 2 元素数组 mport 检查
逐 lane 写 mask、未写 lane 保留及真实编译执行。
`py-install16.log` 安装退出 0，installed `libwolvrix-lib.so` SHA256 为
`7309026c0904199b305bccc2706ad2020b009b1b81e980cc24433f8768b4a9c1`。
`conditional-cost16/` 同输入、同编译选项生成编译退出 0；相对14，
`pOutput` 非 padding 静态指令 281→202、显式 memory operand 指令
61→55、条件分支 0→0，符号大小 918→656 bytes，对象 text
4032→3736 bytes。`pInput` 与 `eval` 指令统计一致。这里只证明该小样例
的静态代码成本下降，实际整机吞吐仍待测量。三版源码、机器码与统计均
保存在对应目录及 `conditional-cost-comparison.md`。
`production-loadunit-fixed16/generate.log` 记录真实 LoadUnit 在 19.652 秒
完成生产 flow、emit 和 roundtrip；原 minimal 也生成、roundtrip 和编译
通过。`full-retry16.log` 在独立 `full16/` 使用 install16、相同 frozen
输入和 harness 源开始整机重试。该次在 1332.641 秒完成整机 mixed ingest，
423 个候选环均证明为假环且全部修复，真实环为 0；随后进入共享 GRH
xmr-resolve/mux-tree-fold。该次后续主动中止，尚未完成模型生成、emu 构建或运行，原因见下文。
install16 的真实模型库编译也已退出 0；
`packed-mixed-boundaries16.log` 另外验证混合语言数组边界的生成模型
编译执行，确认 packed accumulator 没有改变公开 shape/ABI。

`full16-configuration-audit.mk` 的独立 Make 审计退出 0，34/34 项通过。
该次只读检查小产物，确认冻结输入/库身份、unknown init/invalid、三个
Verification 层、DIFFTEST、7 份生成资源/116 份公共 harness 文件、
27 个真实 Difftest provider 签名及与成功参考机相同的 CoreMark/NEMU
输入。最终 emit 调用、链接、效果守卫和实际执行仍待核查；完整边界及
检查清单保存在 `full16-configuration-report.md`，不据配置审计宣称运行通过。

### flatten inventory 批量导入与 full17 准备

full16 完成两次 mux-tree-fold、寄存器写归一化、memory-read-retime、
multidriven/blackbox 检查及 latch-transparent-read 后，于
`2026-11-01 03:27:21 +0800` 进入 hier-flatten。超过 41 分钟仍未返回。
静态审查确认每个带 policy 的实例都会复制并排序 target 的累计 node
inventory/eliminated，即使 source 列表为空；`requirePolicy` 的存在性
检查也会隐式复制整个 inventory。冻结输入有 5,476,900 条 node 与
10,271 条 instance 声明，这是一条明确的累计成本路径；本次没有 profiler
测得它占整机耗时的比例，也没有观察到 OOM 或证明死锁。

新增 `InventoryImportBatch` 拥有实例限定后的 keys，flatten 成功释放
source graphs 后统一 merge/sort；普通失败返回也先发布已导入 inventory。
保留旧字段顺序、原 inventory/tombstones 和无 policy 的 no-op 行为；
policy 检查采用只读 metadata view。此修复不改变 lower、操作图或最终
C++ 执行逻辑。`inventory-batch-targeted4.log` 的定向检查和
`inventory-batch-all-native.log` 的全量 79/79 通过，包含多实例/空 source、
源生命周期、JSON/census、成功/失败 flatten 发布，以及 CSE 后两实例
members/roots/origins 的精确合并。

`inventory-cost/README.md` 的 512 实例、每 source 256 keys 小样例，
即时合并用时 8.995031 秒，批量为 0.255116 秒；最终两个向量和快照
SHA 完全一致。基线使用仍按实例即时合并的兼容 API，已包含较快的只读
policy 检查，因此是本例旧路径的保守对照。这里只测元数据，不推算
full16 热点比例或最终 C++ 吞吐。

上述验证通过后，主动中止原 session 3007，实际退出 130，保留
`full16-stop-reason.txt` 和完整旧日志。没有在该进程运行期间替换其
installed native 库。随后 `py-install17.log` 的 `make py_install` 退出 0，
在独立 `full17/` 使用同一冻结输入、harness 内容与语义配置开始重试。
实际加载的 native 库 SHA256 为
`c64b454dab6b36c4d534fb12cb615ea519c28866b519c6d5f72cbc0cb992ff9e`；
它包含 batch API，`_wolvrix.so` SHA 仍为此前的 `60ee7369...6465`。
这是安装产物身份；小规模成本实验和原生测试使用的 build 库为
`e7a4ef4dde551d35a33f1823e44e13e0c49d08c4eb9cc06985d8b74f762d5b5a`，
两者不能混称同一二进制。`full17-vs-full16-identity.json` 保留输入、
flow、lower SHA 和 captured source 差异；整机 emu/运行退出条件仍待完成。

`full-retry17.log` 随后在 1287.458 秒完成整机 mixed ingest，423 个候选环
均证明为假环且全部修复，true=0。`full17-configuration-audit.mk
verify-ingest` 的严格复验退出 0，43/43 项通过，包括真实 ingest 依赖
指向该次冻结宏快照；机器报告状态为 `configuration-verified`。
这些结果仅覆盖读取/配置；当前进入共享 GRH 优化，最终模型、emu 和
CoreMark/NEMU 尚未通过。

full17 后续已完成两轮 mux 清理、寄存器写归一化、memory-read-retime、
多驱动/blackbox 检查和 latch-transparent-read，随后进入 hier-flatten。
`full17-dpi-providers.mk audit` 的 143 项源码检查通过，目录涵盖 27 个
Difftest 及 15 个其他 RTL provider 候选，保留 ordered 参数、返回值、
signedness、指针/const 和真实定义的宏上下文。该目录尚未核对最终模型
调用，不能据此认定 ABI 已通过。`result-audit/` 的 14 项检查及真实
参考日志解析通过；native 日志缺失时明确保持 pending。off 路线的只读
审查确认从第二个 converted checkpoint 恢复，跳过分图前已完成的优化，
复用相同分图/效果排序流程；实际两路产物仍待生成后复验。

full17 的 flatten 在约 23 分钟后仍未返回；主机可用内存降至
2,638,936 KiB，8 GiB swap 仅余 164 KiB。为处理持续增长的源图存储成本，
主动中止原 session 4588，实际退出 130；未观察到 kernel OOM kill，
不把本轮记作 OOM 或死锁。中止后可用内存恢复至 191,496,416 KiB。
这些是主机读数，并非进程峰值 RSS。完整证据为 `full17-stop-reason.txt`；
本轮未写出 checkpoint、模型或 emu。修复在 flatten 保存任何 ID 前冻结
安全的非 top 内联源图，回收 tombstone backing storage。预扫描汇总同一
源图的所有实例和黑盒引用，任一依赖位置端口顺序时整张源图跳过冻结；
结构性 freeze 异常仍回到原内联诊断。源图保留到既有清理阶段，失败路径和
preserve 语义保留，单次汇总记录冻结/跳过/失败数量。

`source-freeze-targeted18-retry.log` 的 4 项定向检查通过，包含两共享实例、
逆字典序端口、dead-slot 重编号、冻结/位置基线完整 JSON 等价、节点身份、
generate groups、黑盒、preserve 和错误诊断回退。第一次定向调用仅被 Make
环境检查拒绝，原日志保留。`source-freeze-all-native-mixed18.log` 的全量
79/79 和 mixed 生成模型编译执行均退出 0。该次 build 库 SHA256 为
`48a2ef42c76fbe871c62c97a6e19f695d05dc63ceac047f161241f6c1165a816`；
installed 身份单独记录。此修复尚无整机峰值/吞吐测量，lower.cpp SHA
仍为 `1784cb64...e08e6`，先前局部 C++ 成本证据不据此扩大结论。

`py-install18.log` 的安装退出 0；实际 installed native SHA256 为
`ec1038c4fdd1d22caa233940dd953a243db771208a53974d9dc799c13e861d42`，
extension 仍为 `60ee7369...6465`。安装发生在 full17 退出之后。
`full-retry18.log` 在独立 `full18/` 以同一冻结 FIRRTL、full17 保存的
harness 内容及相同语义/分图配置启动，已完成 mixed ingest。
`full18-audit-expectations.json` 固定新库和 lower/flatten 源码身份；
实际 DPI ABI、整机 emu 和两路 100k/NEMU 仍待最终结果。

full18 ingest 用时 1290.544 秒，423 个候选环全部为假环且修复，true=0。
随后 xmr-resolve 在 35.505 秒完成，进入第一轮 mux-tree-fold。
`full18-configuration-audit.mk verify-ingest` 的 44/44 检查通过，含真实
依赖与冻结宏快照；provider 目录的 143 项源码检查通过。身份对比 26/26
通过，唯一捕获源码差异为 hier_flatten.cpp，flow/input/harness 内容一致。
最终模型 ABI、flatten 资源表现、emu 与整机运行仍待实际结果。

full18 的 hier-flatten 随后在 2735.600 秒完成，进入 flatten 后的
comb-loop-elim；该 pass 已报告 52 个候选环全部为假环且修复，true=0，
并在 459.224 秒完成，随后进入 `grh.verify`。本次主机可用内存曾接近
3 GiB，之后观测到约 56 GiB
匿名内存释放、可用内存回到约 46 GiB；期间未观察到 OOM 计数增长，
少量换页采样不支持严重 thrashing。主机读数不是进程峰值 RSS，当前
也不能拆分 clone、源图清理和 retention census 各自用时。默认日志未打印
source-freeze 的 info 诊断，实际 eligible/frozen 数量没有观测证据。
本轮证明该输入已越过 flatten；旧轮均主动中止，不能据此计算加速比。

真实 LoadUnit 的既有15/16对象也按同口径只读比较。eval 执行函数族的
静态合计指令 68454→62306、条件分支 5454→5405、显式 memory operand
指令 38622→36220，对象 text 总量 991394→957074 bytes。局部代价并非
全部下降：`pOutput` 的 memory operand 指令 11339→11449，writer run
指令 16506→16641；完整逐函数表及身份局限保留在上述成本对照中。
这些合计没有运行频率权重，不代表执行指令总数或实际 memory traffic。

full18 的 `grh.verify` 已在 329.281 秒通过。随后保存
`pre-simplify.json` 时，文件尚未写出，主机可用内存从约 45 GiB 快速降至
约 2.4 GiB，swap 开始减少。默认 PrettyCompact 保存路径会先生成整份
JSON 字符串，再打开输出文件；根会话因此主动中止 session23059，实际
退出 130。停止后可用内存恢复至 191,702,028 KiB，`oom_kill` 计数仍为 9；
没有观察到 OOM kill，主机读数不是进程峰值 RSS。本轮没有 checkpoint、
最终模型或 emu，证据为 `full18-stop-reason.txt`。当前修复 PrettyCompact
文件输出的有界缓冲及写入错误检查，并核查后续 JSON 文件读取的内存峰值。
这些资源修复不改变 lowering 或预期仿真行为，整机重试与退出条件仍待完成。

### JSON 文件存读修复与 full19

PrettyCompact 文件输出改为固定 64 KiB 缓冲，复用原排版逻辑；Graph metadata
只排序属性指针，避免复制 inventory。文件写入、flush、close 均检查成功后
才发布 artifact。文件读取增加 `LoadJson::loadFile`，保留惰性数组区间并逐条
加载 values、ops 和 typed metadata 数组，复用原构图逻辑；Python
`read_json_file` 接入此入口，文本 API 保留。最终 Graph、单条记录和非数组
对象仍需内存，尚不能据小回归保证整机峰值。共享 checkpoint helper 使用同目录
pending 文件，成功后原子替换，保留原文件权限并记录耗时与字节数。

`json-io-targeted19.log` 的存读定向 4/4、`all-native-json-io19.log` 的全量
80/80 均通过；5 份历史新旧格式输出逐字节一致。`py-install19.log` 安装
退出 0；`json-io-python19.log` 的 Session 4 项（含晚期读取错误、截断及缺失
文件不替换旧设计/值）、FIRRTL 工作流 51 项、原 SV 工作流 5 项均通过。
`json-io-flow19.log` 的共享 flow 4 项和各阶段重载生成模型编译执行退出 0。
安装库实际 SHA256 为
`de41d07cdd8176bcad77c1fa8b86dad9d262d92c14721d40d4e2160556b6ef1f`，
extension 为 `5500f4cb9790bfece4fa04f23f6e066bf1f3212c66126c887a0420751dd7f41d`；
原生回归 build 库为 `fe1dac6d2b531305c7448ff52c51ca9d2b74ca7711e6d0fefee5fb6864de9190`，
不是同一构建产物。lower SHA256 仍为 `1784cb64...e08e6`。

`full-retry19.log` 在独立 `full19/` 使用新安装库、相同冻结 FIRRTL、
full18 保存的 harness 内容及相同语义/分图配置开始整机重试，当前进入
共享 GRH 优化：mixed ingest 已在 1289.608 秒完成，423 个候选环全部
为假环且修复，true=0。严格配置审查 44/44、与 full18 的输入/harness/flow
一致性审查 50/50、真实 DPI provider 源码检查 143 项均通过。对比保留
8 个 changed、1 个 added、0 个 removed 源码差异及实际库身份，
不据此声称新旧二进制或模型等价。
随后 `hier-flatten` 在 2727.420 秒完成，当前进入 flatten 后的
`comb-loop-elim`。本轮观察到低内存及换页后主机匿名内存大幅释放，
可用内存回到约 46 GiB，OOM kill 计数未增长；这是主机采样，
不作为进程峰值 RSS 或运行吞吐证据。JSON checkpoint 的实际存读表现、
最终模型和整机运行仍待验证。
`run19.mk generate` 额外启用 `WOLVRIX_JSON_TIMING=1` 记录
存读进度，仿真器波形/profile/timing 配置均保持关闭。最终模型、emu、
两路 100k/NEMU 及实际存读内存表现仍待结果。

full19 的 flatten 后 `comb-loop-elim` 在 487.447 秒完成：52 个候选环均
判为假环并修复，true=0；随后 `grh.verify` 在 326.588 秒通过。
`pre-simplify.json` 已在 159.493 秒成功关闭并原子发布，共
56,437,233,305 bytes，含 39,208,015 个 value 和 39,818,308 个 op。
本轮观察到 pending 文件持续增长，保存期间主机可用内存约 46–57 GiB，
OOM kill 计数未增加；这是主机采样，不是进程峰值 RSS。当前进入普通
GRH simplify；后续 JSON 读取、最终模型、emu 与两路运行仍未验证。

随后用户要求 FIRRTL→C++ 生成不得超过 20 分钟，超时立即杀死。
根会话立即停止正在 simplify 的 full19，原 session16200 实际退出 130；
这不是 OOM 或 simplify 成功。发布的 checkpoint 和日志保留，尚无最终
模型、emu 或运行结果。停止后主机可用内存恢复至 191,602,856 KiB，
OOM kill 计数仍为 9，详见 `full19-stop-reason.txt`。Make 入口已用固定
`timeout --signal=KILL 20m` 包住完整 Python 生成进程，包含 native 调用；
emu 编译在生成成功后单独执行。真实 Make 小型测试验证 native 阻塞及
忽略 SIGTERM 时均强杀，旧模型文件不会使失败生成继续构建；成功和普通
失败状态同样正确。`full19-generation-timeout-tests.log` 的工作流 52/52
通过；未再次启动真实整机生成。

原始 frozen SV 的独立 `-O0` reference 已完成固定 100000 host/model cycles
和 NEMU 的 238535 条指令验证，退出 0；实际停止状态、输入身份及 reset
阶段的日志行为见 [F10-replacer.md](F10-replacer.md)。native FIRRTL
assert/assume 映射的 fatal 直接退出，并不经过 SV harness 的 `xs_assert`
reset gate；未新增 reset 豁免，native 初始化行为仍须实际执行确认。

整机生成成功后先检查初始化和首个活动周期（`XS_SIM_MAX_CYCLE=1`），
再检查 10000 周期前缀和固定 100000 周期，均保留 NEMU。
`XS_SIM_MAX_CYCLE=0` 会省略 `-C` 而无限运行，不用作初始化检查。
若只需恢复 emu 编译，使用 `xs_firrtl_grhsim_build_emu`，避免再次调用
会重新生成模型的 `xs_firrtl_grhsim_emu`。off 模式从分图前 checkpoint
经 `reemit_grhsim` 分叉；完成 sink partition 的最终 checkpoint 不能直接
切换提示模式。两模式整机 100k 用于额外验证透明性；F11 的正式多次计时
仍待正确性全部完成后实施。

保存日志的结果审查要求 native 实际 `-s 0` 和终态 `Seed=0` 同时存在；
错误 seed 即使周期和提交端点吻合仍失败，缺少证据保持未完成。
`run19/seed-result-audit-tests-final.log` 的 18 项回归通过，并将真实 frozen
SV reference 重新解析至 `run19/reference-parser-seed-verified.json`，
仍标记 `native_passed=false`。历史 reference 未显式传 `-s`，Difftest
默认 seed 为 0，其独立 parser 复核要求终态 seed 为 0；该历史调用差异
不放宽 native 两路线的显式 seed 要求。

`full19-off-dpi-model.mk` 补充 off 路线独立审查，复用完整 manifest DPI
scanner；原 prefer 审查规则保留。`run19.mk off-generate` 在原 reemit 前
绑定成功 producer 的日志、capture、harness 与 checkpoint bytes/SHA，
明确标记为事后证据绑定，不冒称 producer 原生记录了 parent。
16 项小型 fixture 通过，包含成功标志严格布尔检查及 off requested/resolved
统计类型、唯一性和一致性检查。真实审查仍因缺少最终产物而 pending；不会读取
正在生成的 checkpoint，也不会因此重复运行 ingest。实际两路线身份、
最终 ABI、链接与运行结果仍待验证。

### 20 分钟预算下的 bringup 重试

full26、full27 使用显式 `XS_GRHSIM_PIPELINE_PROFILE=bringup`，mixed ingest
分别为 876.217、875.530 秒，均在 hier-flatten 触发完整 producer 的
20 分钟 SIGKILL。full27 增加递归容量预留，仍未完成 flatten。
full28 增加以 ValueId index 查找的 dense map 和 cloned op 容量预留，
mixed ingest 为 895.472 秒，xmr-resolve 为 32.662 秒，后续三个 guard/read
pass 为 1.243、1.189、18.400 秒，仍在 hier-flatten 触发硬上限，Make 报
Error 137。三轮都没有 flat/final GRH、C++ model、emu 或整机运行结果。
日志及停止原因保留在 `ptmp/firrtl-ingest/F10/`，full28 日志位于
`ptmp/xs/logs/xs_firrtl_grhsim_f10_full28.log`。

full28 的实际安装库 SHA256 为 `baa1fd33840f7ee1844a460710c278170bcbd4d145a9bfe9174fe76e153d258e`。
安装后源码另补 dense map 的 graph/generation 校验，因此该轮不验证这部分
补丁；随后审查也发现共享 child input/inout ValueId 必须保持首次映射，
不能用无条件 set 替代原 emplace。对应修正和前向引用、DPI 去重、错误诊断
回归已在后续构建验证。首次新增 fixture 因未保护顶层端口而在默认重命名后
查找旧名字失败，修正 fixture 后全量 81/81 通过；又补逆序端口名覆盖，最终
81/81 仍通过（5.98 秒）。`make test_firrtl_state test_firrtl_memory` 的生成
模型编译执行退出 0。所有检查和安装均通过项目 Makefile，日志在
`full29/logs/`。

后续改动只处理生成预算的明确额外工作：静态索引保留必要的数组访问，
不生成恒真的运行期 bounds guard；已知 UInt 常量 OOB 读返回配置的 invalid，
写不生成操作；普通 wire connect 不生成未使用的 memory write mask。
flatten 的名称映射只保留 symbol attrs 和 generate groups 真正需要的条目，
节点 key qualification 使用每实例持有不可变路径和 owned strings 的缓存，
保留原 read/write 的全部校验。不据此宣称整机已跑通或生成代码成本已降低。
所有后续重试继续共用 20 分钟硬计时，
不得通过阶段恢复重置总预算。

full29 在独立目录复用原始 frozen FIRRTL 及 full27 harness 内容。
`source-and-library.sha256` 保留这轮的
源码及实际安装库身份，实际库 SHA256 为
`e233b2ae48385da95c54c7724d84ee37a2b5936539034b931f44f2b270fc95e6`。
生成期间保持生产源码和安装不变。mixed ingest 在 588.498 秒完成，比
full28 少 306.974 秒；RenameBuffer 操作数 1,001,646→656,238，Rob 为
10,540,623→5,830,973。xmr-resolve 为 17.344 秒，随后仍在 hier-flatten
触发 20 分钟 SIGKILL，Make 报 Error 137，没有模型/emu/整机运行成果。
该轮日志和原因见 `full29/logs/`、`full29-stop-reason.txt`。

### 先验证无 node 提示的整机功能

按照先跑通整机的优先级，新增显式 `XS_FIRRTL_NODE_ANNOTATIONS=off`
入口，默认仍为 on；功能 annotation、源码位置、unknown 初始化/invalid
策略及断言层不受影响。该轮同时显式设置下游 node CSE/nonsink hints 为
off。bringup profile 仅保留 xmr、guard/read、flatten、comb-loop-elim 和
memory-init-check 七个关键阶段，省略普通 GRH simplify 和前后两次显式
verify；转换 API 自带的完整前后验证继续执行，默认 full profile 保留原序列。
另去掉 mixed 两次全图属性查询的 Operation snapshot、verify 正常值循环的
Value snapshot，以及无环图的重复 comb-loop 分析。已证明 canonical 的
qualified key 跳过重解析方案仍留在 ptmp 草案，未应用。

`full30/logs/native-and-install.log` 的 81/81 和安装通过；shared flow 的
5 项测试、阶段重载模型及 node 注解 on/off 两模型均完成实际编译运行。
两模型各有 4608 次动态数组/状态/优先级/reset scoreboard 检查，输出 trace
逐字节相同；FIRRTL workflow 56 项通过，日志为 `flow-tests-final.log`。
首次测试把波形参数误写为字符串 `"none"`，驱动缺 FST 头文件而失败；修正
为明确 False 后重跑全部通过，保留首次失败日志，不冒称未发生。

full30 使用同一 frozen FIRRTL/full27 harness，在独立目录完成了下列阶段。
安装库 SHA256 为 `ecd725b4548928dbbc420521e44f75d86d1523544394d1111377b4a0279097cf`；
manifest 相对 full27 仅将 `node_annotations` 改为 false，unknown
init/invalid、三个 Verification 层、DPI、SimJTAG 和冻结 harness include
保持原配置。实际 generation identity 与源码/安装库 freeze 一致。

| 已完成阶段 | 耗时（毫秒） |
| --- | ---: |
| mixed ingest | 388057 |
| xmr-resolve | 8845 |
| multidriven-guard | 817 |
| blackbox-guard | 809 |
| latch-transparent-read | 596 |
| hier-flatten | 218300 |
| comb-loop-elim | 37757 |
| memory-init-check | 8163 |
| flat checkpoint 保存 | 97076 |
| grh-to-grhsim | 38041 |

flat checkpoint 已发布，大小为 34,973,290,367 bytes；flatten 后 52 个
假环全部修复，无真环，转换日志为 456,380 operations、202,893 states。
随后首次 `grhsim-simplify` 的第 1–7 轮分别耗时
210807、37946、27730、26281、26088、26443、26491 ms，合计
381786 ms，七轮均 `changed=1`，该 pass 没有完成记录。完整 producer 在
2026-11-01 07:04:29 UTC 到达唯一的 20 分钟硬截止，被 SIGKILL；Make
报 Error 137。尚无 final/sink-partitioned checkpoint、整机 C++、emu
或整机执行结果，不能记作跑通。日志、身份和停止原因分别为
`full30/logs/`、`full30/xiangshan_grhsim.generation-identity.json` 和
`full30-stop-reason.txt`。

### 跳过 backend 可选优化的 full31（20 分钟终止）

full31 已实施显式关闭 backend 可选优化的功能 bringup：
`XS_GRHSIM_SIMPLIFY=0`、`XS_GRHSIM_PACK_BIT_REGISTERS=0`、
`XS_GRHSIM_MASKED_OR=0`、`XS_GRHSIM_PHASE_SIMPLIFY=0` 和
`XS_GRHSIM_CLONE_SHARED_COMPUTE=0`，保留转换及其结构验证、phase 拆分、
分图/SinkSchedule 和 C++ emit。另设 `XS_GRHSIM_ROUNDTRIP_VERIFY=0`，
只跳过 emit 后额外的 JSON 重载/重建 schedule/重存比较，不关闭转换验证。
GRH 仍显式选择七阶段 bringup，node annotations/CSE/hints 仍全 off；
默认 full 及默认优化配置未改变。

`full31/logs/flow-tests.log` 记录 shared flow 5 项通过、既有阶段重载模型
实际编译执行通过，以及 backend optimized/bringup × node annotations
on/off 四组模型的实际编译运行。四组均使用 GRH 七阶段 bringup；这里的
optimized/bringup 区别是 backend 可选优化开关，不是默认 full GRH 对照。
每组复用 `renameTrace` 完成 4608 次动态数组/状态/写优先级/old-state/OOB/
reset scoreboard，合计 18432 次；三次 `cmp` 通过，四个实际输出文件的
SHA256 均为 `18a9ac1e16c92cffe4c266fbd5d8ecdf782370da11afba6a7d0ab0f84d1f0848`。
FIRRTL workflow 56 项也通过。这些小型回归不替代整机验收。

`full31/run-generation.sh` 于 2026-11-01 07:06:55 UTC 启动独立目录的
完整 producer，继续由同一个 Make 入口执行单次
`timeout --signal=KILL 20m`，预计硬截止约为 07:26:56 UTC。实际 manifest
与 full30 逐字节相同，保留 frozen FIRRTL/full27 harness、unknown
init/invalid、DPI、Verification 层和 include；`resume_from_flat_grh=false`。
本轮只改 Python flow/CLI 配置，实际加载库仍为
`ecd725b4548928dbbc420521e44f75d86d1523544394d1111377b4a0279097cf`。
`source-and-library.sha256` 与 generation identity、当前输入及库哈希均已
独立核对，复核记录为 `full31/independent-review.md`。
本轮 mixed ingest 393005 ms、flatten 235831 ms、comb-loop-elim 39109 ms、
flat store 91928 ms、转换 38446 ms，随后 event/output 拆分 151669 ms、
nonsink/sink 拆分 147814 ms。flat 仍为 34,973,290,367 bytes，52 个假环
全部修复。完整 producer 到时在 nonsink 分区被 SIGKILL，Make 报 Error 137；
外层 07:26:58 UTC 返回 2。没有最终 GRH、整机 C++、emu 或执行结果；
不续跑 checkpoint，也不分阶段重置预算。详见 `full31-stop-reason.txt`。
无提示功能路线不替代最终 full/prefer 验收或性能对照，F10 仍未跑通。

### 后续 bringup：省略可选导出及重复检查

新增默认开启的 `XS_GRHSIM_STORE_GRH_CHECKPOINTS` / CLI
`--[no-]store-grh-checkpoints`，仅控制自动 flat/final JSON。关闭时要求
C++ 输出目录及关闭 JSON roundtrip；显式 dump/checkpoint 请求独立。
producer/model identity、输入哈希、原子 C++ 发布及全部必要验证保留。
另可用既有 `XS_GRHSIM_READABLE_DUMP=0` 省略 `grhsim.txt`，不改变模型行为。

分区拓扑检查原先总验证 leaf 和 supernode 两个 quotient DAG；当不存在
四级 nonsink owner 时，这两个 DAG 完全相同，现只检查一次。存在四级
owner 时仍检查两者，既有独立 supernode 环拒绝回归覆盖该分支。nonsink/
sink 拆分还改用借用接口读取 history 存在、端口标志和 use-list，避免
完整 Operation/Value 快照。未跳过非重复验证，也未改分区语义。
这些改动已通过 `make test_wolvrix` 的 81/81，以及 shared flow 5 项、
FIRRTL workflow 57 项。新增 CLI 用例在关闭自动 checkpoint、整图文本和
可选优化后，保留 generation identity 和显式转换阶段 dump，实际生成、
编译并执行混合 FIRRTL/SV 模型；默认 checkpoint/roundtrip 用例也通过。
四组 rename 模型继续各执行 4608 次，全部输出 trace 一致。

full32 于 2026-11-01 07:33:11 UTC 从同一冻结 FIRRTL/full27 harness
重新启动，硬截止约为 07:53:12 UTC。本轮在 full31 的显式关闭配置上增加
`XS_GRHSIM_STORE_GRH_CHECKPOINTS=0`、`XS_GRHSIM_READABLE_DUMP=0` 和
`XS_GRHSIM_SOURCE_COMMENTS=0`，内部 readable names/frames 保持默认开启。
源码/安装库在启动前重新冻结，日志及命令位于 `full32/`。本轮实际完成：

| 阶段 | 耗时（ms） |
| --- | ---: |
| mixed ingest | 389656 |
| xmr-resolve | 8883 |
| multidriven-guard | 834 |
| blackbox-guard | 823 |
| latch-transparent-read | 608 |
| hier-flatten | 251875 |
| comb-loop-elim | 37792 |
| memory-init-check | 7373 |
| grh-to-grhsim | 39590 |
| grhsim-split-event-and-output | 149841 |
| grhsim-split-nonsink-and-sink | 108937 |

flatten 后的 52 个候选环均为假环且全部修复，无真环。转换报告的
456380 converted operations、202893 states 是转换计数，并非全图 op 数。
`grhsim-partition-nonsink` 到硬截止时已运行约 205 秒以上，仍未完成；
完整 producer 被 SIGKILL，Make 报 Error 137，外层于 07:53:14 UTC 返回 2。
自动 flat/final JSON 和整图文本已关闭，本轮未发布这些输出；也没有
整机 C++、emu 或运行结果。证据见 `full32-stop-reason.txt`；F10 仍未跑通。

### 单次 DCE 的 full33（20 分钟终止）

full33 仅在显式 GRH bringup profile 的 `comb-loop-elim` 后、
`memory-init-check` 前增加一次既有 `dead-code-elim`，保持
`keep_declared_symbols=True`，保留此前 guard 和后续完整转换/分区验证。
它只清理无根锥，不启用普通或 backend 的完整 simplify，不改变默认 full
profile，也不展开模拟器指令数量优化。`full33/logs/flow-tests.log` 记录
包含该顺序的 shared flow 5 项和 FIRRTL workflow 57 项通过；四组 rename
模型各实际执行 4608 次检查，输出 trace 逐字节一致。此次没有原生实现
变更或新安装。生产源码和加载库在启动前已冻结。

full33 于 2026-11-01 07:54:34 UTC 从同一冻结 FIRRTL/full27 harness 在
新目录启动完整 producer，继续单次 `timeout --signal=KILL 20m`，硬截止
约为 08:14:35 UTC；不恢复 full32 或分段重置预算。除 bringup 增加一次
DCE 外，其余 flags 与 full32 相同，自动 JSON/text、source comments 和
backend 可选优化仍关闭，必要 guard、转换/分区验证继续保留。
命令及身份记录位于 `full33/`。本轮实际完成：

| 阶段 | 耗时（ms） |
| --- | ---: |
| mixed ingest | 389466 |
| xmr-resolve | 9522 |
| multidriven-guard | 836 |
| blackbox-guard | 844 |
| latch-transparent-read | 606 |
| hier-flatten | 224039 |
| comb-loop-elim | 37602 |
| dead-code-elim | 126359 |
| memory-init-check | 24460 |
| grh-to-grhsim | 37413 |
| grhsim-split-event-and-output | 134398 |
| grhsim-split-nonsink-and-sink | 100509 |

52 个 flatten 假环全部修复，无真环。转换报告为 401484 converted
operations、169336 states，不能将转换计数当作全图 op 数。虽然转换计数
和两个拆分时长下降，raw DCE 自身耗时 126359 ms；截至第二个拆分的已完成
阶段计时合计为 1086054 ms，full32 对应值为 996212 ms。本轮仍在
`grhsim-partition-nonsink` 未完成时达到同一个 20 分钟 SIGKILL 硬截止；
内部 Error 137，外层于 08:14:36 UTC 返回 2。没有自动 flat/final/text，
没有整机 C++、emu 或运行结果；详见 `full33-stop-reason.txt`。

### converted 单轮 simplify 的 full34（20 分钟终止）

raw DCE 未改善整机生成进度，因此从显式 bringup 撤回，普通 GRH 恢复原
七阶段。full34 只在 converted 阶段启用既有 `grhsim-simplify` 的
`-max-rounds=1`，其它 backend 可选变换保持关闭，默认 full 配置不变。
`full34/logs/flow-tests.log` 记录 shared flow 5 项和 FIRRTL workflow 57 项
通过，以及 backend default/skip/one-round × annotations on/off 六组状态
模型实际编译执行。各组完成 4608 次 scoreboard，合计 27648 次，五次
trace 比较全部一致。六组共同使用 raw GRH 七阶段 bringup，不是默认
full/prefer 对照；原生库未改变。

full34 于 2026-11-01 08:16:37 UTC 从同一冻结 FIRRTL/full27 harness 在
新目录完整启动，硬截止约为 08:36:38 UTC。实际设置
`XS_GRHSIM_SIMPLIFY=1 XS_GRHSIM_SIMPLIFY_MAX_ROUNDS=1`，raw DCE 已撤回，
pack/recover/phase/clone 保持关闭；其余 flags 同 full33。
继续保留所有必要 guard 和验证，使用单个 `timeout --signal=KILL 20m`，
不恢复 full33 或分段重置预算。本轮实际完成：

| 阶段 | 耗时（ms） |
| --- | ---: |
| mixed ingest | 385066 |
| xmr-resolve | 9212 |
| multidriven-guard | 818 |
| blackbox-guard | 743 |
| latch-transparent-read | 609 |
| hier-flatten | 217892 |
| comb-loop-elim | 37667 |
| memory-init-check | 18687 |
| grh-to-grhsim | 48030 |
| grhsim-simplify | 233906 |
| grhsim-split-event-and-output | 48482 |
| grhsim-split-nonsink-and-sink | 36201 |
| grhsim-partition-nonsink | 108280 |

simplify 仅完成配置的一轮：round 为 213082 ms，其中 fold/share 181695、
mux 1676、state merge 1761、DCE 3889、used bits 16000、topology 2098 ms。
`changed=1`，按限制报告尚未收敛；该 pass 正常结束，总计 233906 ms，
不能只按 round 计时估算整段成本。nonsink 分区报告 1355684 activity
nodes、12608 supernodes。52 个 flatten 假环全部修复，无真环；转换报告
456380 converted operations、202893 states，仍非全图规模。
本轮已完成 nonsink 分区，随后 `grhsim-partition-sink` 未完成即到达同一个
20 分钟 SIGKILL 硬截止；内部 Error 137，外层于 08:36:39 UTC 返回 2。
无自动 flat/final/text、整机 C++、emu 或运行结果，详见
`full34-stop-reason.txt`。必要的默认 full/prefer 验收仍未完成，F10 未跑通。

### bytes 成本模型和关闭 readable names 的 full35（已主动中断，路线撤回）

full35 保留七阶段 raw GRH 及 converted 单轮 simplify，只将既有
`XS_GRHSIM_COST_MODEL=bytes`、`XS_GRHSIM_READABLE_NAMES=0` 显式接入；
其它 flags 同 full34，readable frames 保持原默认，pack/recover/phase/clone
继续关闭，不新增原生优化或改变默认 full，生产原生实现和库均未改变。
`full35/logs/flow-tests.log` 记录 shared flow 5 项、FIRRTL workflow 57 项
通过。backend default/skip/one-round/one-round-bytes × annotations on/off
八组状态模型均实际编译执行，各 4608 次 scoreboard，合计 36864 次；
七次实际输出 trace 比较全部一致。八组共同使用 raw GRH 七阶段 bringup，
不构成默认 full/prefer 对照。bytes/short-names CLI 在无自动 checkpoint
配置下也完成真实生成、编译及 256 个输入值的执行检查。

full35 外层启动记录为 2026-11-01 08:39:21 UTC，producer 约于
08:39:22 UTC 从同一冻结 FIRRTL/full27 harness 在新目录开始。
在用户拒绝减少优化轮次和关闭优化的取舍后，于 08:57:33 UTC 主动发送
SIGINT，外层退出 130；这次不是 20 分钟超时。最后进入 sink 分区，
尚无整机 C++、emu 或执行结果。已完成阶段合计 1089.184 秒，预算只剩
110.816 秒，尚未包括 sink 和 emit。后续保留完整默认 pass、simplify
全部默认轮次、packing/masked-OR/phase/clone 与校验；只能优化实现。
仍从原始 FIRRTL 完整开始，共用一个 20 分钟 SIGKILL 截止，不恢复
checkpoint 或分段重置预算。实现优化和严格 A/B 证据记录在
`ptmp/firrtl-ingest/F10/pass-opt/`，fixture 结果不构成整机验收。

### 保留完整优化的实现加速与 full36

实现与严格 A/B 详见 [pass-optimization-20261101.md](pass-optimization-20261101.md)。
81 项 native、flow 5 项、workflow 57 项及状态/内存模型编译执行均通过；
四组 fixture 的三个阶段完整 JSON 和 simplify 迭代结果逐字节一致。带注解
fixture 的 flatten 为 1.417→1.148 秒，simplify 为 27.240→10.141 秒；
无注解结果变化较小且有波动，不能外推整机收益。

full36 从原始 FIRRTL/full27 harness 保留完整 full pipeline、注解、默认
8 轮上限、packing/masked-OR/phase/clone、checkpoint/roundtrip 和可读导出，
于 09:43:49 UTC 启动，10:03:49 UTC 按总预算 SIGKILL，退出 137。
ingest 516.645 秒、前序变换 209.400 秒、flatten 396.894 秒、comb-loop
48.114 秒，已完成阶段合计 1171.053 秒；最后停在 grh.verify，未进入
simplify 或 emit，无整机 C++/emu。20 分钟目标和 F10 均未通过；不恢复
checkpoint 续跑。分阶段计时及配置差异见上述实现优化记录。
