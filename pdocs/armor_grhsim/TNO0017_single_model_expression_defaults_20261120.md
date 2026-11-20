# TNO0017：XiangShan 单模型默认开启 eager 逻辑求值和 x86 内存条件传送

XiangShan 单模型的 `xs_wolf_grhsim_emit`、`xs_wolf_grhsim_emu` 和 `grhsim_single_baseline.py` 现在默认使用 TNO0016 的 `eager4096cmov` 配置。两次各八轮的 XiangShan CoreMark 对照中，这组配置的 walltime 分别下降 20.26% 和 19.35%。[原始实验](./TNO0016_branch_sources_and_eager_logic_20261120.md)

## 生效位置与关闭方法

| 设置 | 通用 GrhSIM 默认 | XiangShan 单模型默认 | 生效位置 |
| --- | --- | --- | --- |
| `logic_eager_operand_chars` | `0` | `4096` | 生成 C++。二元逻辑 AND/OR 的两个操作数表达式分别不超过阈值时，两侧都求值 |
| `keep_x86_memory_cmov` | 关 | 开 | 生成的模型 Makefile 用实际编译器试编译。支持该选项的 x86 Clang 加 `-mllvm -x86-cmov-converter-force-mem-operand=false` |

两项都可以独立覆盖。下面的命令用旧的两项设置重新生成并编译单模型。阈值和编译策略都在检查点之后选定，已有的 pre-reg-to-mem 检查点可以复用。[生成脚本](../../scripts/wolvrix_xs_grhsim.py) · [编译规则](../../wolvrix/lib/emit/grhsim_compiler_compat.hpp)

```sh
make xs_wolf_grhsim_emu WOLVRIX_GRHSIM_LOGIC_EAGER_OPERAND_CHARS=0 WOLVRIX_GRHSIM_KEEP_X86_MEMORY_CMOV=0
```

直接运行 Python 生成脚本可设同名环境变量。基准脚本会清理外部的 `WOLVRIX_*` 环境变量，可在 `build` 或 `emit` 时传 `--logic-eager-operand-chars 0 --no-keep-x86-memory-cmov`。只想对已生成的模型关闭编译开关时，在模型目录运行 `make -B GRHSIM_COMPILER_FLAGS= CXX=clang++`，随后重新链接使用该模型库的程序。[基准入口](../../scripts/grhsim_single_baseline.py) · [选项说明](../../wolvrix/docs/emit/grhsim-scheduling.md)

## 两个入口原有的区别

XiangShan 脚本从 RTL 或检查点组织变换、调度和生成。直接调用通用 `emit_grhsim_cpp` 时，调用方提供设计和活动调度结果。表中的变换参数取自直接执行对应 pass 时的默认值。这里比较无环境覆盖、单模型、无波形的普通构建。[XiangShan 配置](../../scripts/wolvrix_xs_grhsim.py) · [通用调度](../../wolvrix/include/transform/activity_schedule.hpp) · [通用生成器](../../wolvrix/lib/emit/grhsim_cpp.cpp)

| 项目 | 通用默认 | XiangShan 单模型默认 |
| --- | --- | --- |
| `simplify` 的语义和声明符号 | 四态，保留声明符号 | 两次二态简化，允许移除声明符号 |
| `comb-lane-pack` | 允许声明根，普通打包可处理累加候选 | 排除声明根，为后续成排累加保留候选 |
| `reg-to-mem` 的 `ordered_writes` | 关 | 开 |
| `accumulate-sink -mode=bank` | 由调用方安排变换 | 默认在 `activity-schedule` 前执行。声明信号波形模式走普通寄存器路径 |
| 每个计算 node / supernode 的操作数上限 | 8192 / 128 | 108 / 108 |
| `split_oversize_compute_nodes` | 关 | 开，拆分阈值 108 |
| 调度批次的基础操作数 / 估计行数预算 | 512 / 4096 | 2048 / 8192 |
| 目标批次数 | 0，按基础预算切分 | 64，按计算和提交各自的总规模调整预算 |
| 并行写出 C++ 文件的任务数 | 硬件并发数，获取失败时取 1 | 4 |
| `storage_ref_aliases` | 开 | 关 |

`max_op_in_commit_supernode` 两边都是 8192，`sched_batches_per_cpp` 两边都是 1。XiangShan 脚本对部分选项采用显式传参，另一些选项在无覆盖时直接沿用通用默认。例如，Make 的 `XS_WOLF_GRHSIM_SCHED_BATCH_TARGET_COUNT` 经脚本传入 emitter，而提交 supernode 上限仅在显式配置时传入。[Make 参数](../../Makefile) · [打包参数](../../wolvrix/include/transform/comb_lane_pack.hpp) · [寄存器变换参数](../../wolvrix/include/transform/reg_to_mem.hpp) · [简化参数](../../wolvrix/include/transform/simplify.hpp)

## 验证

- 新默认模型运行 XiangShan CoreMark 和 microbench 各 10 万周期。CoreMark 在 `0x80000c1a` 停止，提交 250,838 条指令，99,999 条 DiffTest 记录和 35,063 行期末计数器输出与参考一致。microbench 在 `0x80000446` 停止，提交 138,514 条指令，99,999 条 DiffTest 记录与同版本生成器的显式关闭组逐条一致。[CoreMark 核对](../../build/armor-expression-default-v1/coremark-default/result.json) · [microbench 核对](../../build/armor-expression-default-v1/microbench-default/trace.json)
- 单独在 node030 CPU 96 上复用 TNO0016 的两个冻结可执行文件，换用 microbench 的 10 万周期窗口。关→开的一对为 90.93 s、74.58 s，开启后 walltime 下降 17.98%。开→关的一对为 73.90 s、91.15 s，下降 18.92%。这里仅比较这两对样本。[原始秒数与终点](../../build/armor-expression-default-v1/xs-timing/pairs.json)
- 从 XiangShan 已验证的 pre-reg-to-mem 检查点出发，正式生成脚本未设置两个新环境变量时，139 个 C++ 和头文件与此前显式 `4096` 的同版本生成器产物逐字节相同。编译日志中的 PCH 和模型源文件均带内存条件传送开关。[生成日志](../../build/armor-expression-default-v1/default-emit.log) · [源码核对](../../build/armor-expression-default-v1/xs-emit-comparison.json) · [编译日志](../../build/armor-expression-default-v1/default/logs/compile.log)
- 两组 Python 入口回归共 61 项通过，覆盖默认、显式开启、独立关闭和检查点恢复。`emit-grhsim-eager-logic` 的生成和执行测试通过。`grhsim-compiler-compat` 在本机 Clang 23.1.2 的 native change-reduction 用例失败。用 HEAD 的独立源码和编译参数复现了相同的 `from=0 to=172 changed=1 flags=0`，给该用例单加本次编译开关也产生相同结果。[入口测试](../../build/armor-expression-default-v1/python-tests.log) · [CTest](../../build/armor-expression-default-v1/ctest.log) · [HEAD 对照](../../build/armor-expression-default-v1/compat-head/test.log)
- 对 CV32E40P 的同一份图显式开启和关闭这两项。两个模型的 smoke 总线轨迹逐字节一致，CoreMark 都用 3,376,065 个周期完成，输出和校验值与 Verilator 参考一致。node030 CPU 96 上预热后交替计时八轮，开启相对关闭的 walltime 配对中位数为 **+2.92%**，均值为 **+4.78%**，95% bootstrap 区间 [+2.75%, +8.70%]。八轮均慢，有一轮为 +18.36%。[开启组](../../build/armor-expression-default-v1/cv-on/result.json) · [关闭组](../../build/armor-expression-default-v1/cv-off/result.json) · [计时统计](../../build/armor-expression-default-v1/cv-timing/summary.json)
