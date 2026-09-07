# NO0535 GrhSIM IR CPU schedule gate

日期：2026-09-06

承接 [NO0534 调度计划](./NO0534_grhsim_ir_cpu_schedule_plan_20260906.md)。第八个 CPU pass
已实现并接入独立 `xs_wolf_grhsim_ir` 路线。本 gate 不是 emitted runtime 或 CoreMark 验收。

## 实现与单元测试

- 单 NUMA/core、函数级三类 task、三个稀疏 fanout 表、精确 E 状态闭包、roundSeeds、input shadows。
- E 含事件历史并穿过所有状态写口；无关状态不会仅因存在 reader 而加入闭包。派生 event 任意
  变化均 arm，包含目标域不触发写入的反向边沿，以采样其历史。
- canonical verifier 检查缺边、错误目标、任务覆盖/顺序/执行条件、E、round seeds 与影子布局。
- JSON 追加 schedule，Schedule stage 标记 mapping.complete=true，仅表示映射结构齐全；
  未实现的 emitter 与仿真运行不会因此被宣称通过。

```bash
cmake --build wolvrix/build --target grhsim-cpu-mapping-tests grhsim-cpu-schedule-tests grhsim-ir-tests -j 8
ctest --test-dir wolvrix/build -R 'grhsim-(ir|cpu-mapping|cpu-schedule)-tests' --output-on-failure
```

结果 3/3 PASS，0.04 秒。测试覆盖：重复输入 read、无用输入、跨 supernode 扇出及去重、混合
input/derived 域、general 域、跨状态及多写口依赖、死状态排除、memory 地址/数据依赖、DPI/task
事件历史、外部 time 源、空图、完整 JSON/clone/revision，以及任务、fanout、E、seed、shadow 损坏。
全量 legacy CTest 未在此增量重跑。

新增 test-only 两态 trace 对照：全图 G 遍历与 schedule 稀疏 dispatch 比较全部 state/output，
覆盖寄存器链只推进一级、下降沿 history 采样、固定主时钟时门控 enable 产生派生边沿，以及
固定 seed 的 256 组输入变化。三项定值断言避免只比较两个同错结果。该测试只支持限定 op
子集，不是 production runtime，也不是 Verilator 差分测试。

## XiangShan 全图与往返

```bash
wolvrix/build/bin/grhsim-cpu-schedule-tests --schedule \
  wolvrix/build/artifacts/grhsim/cpu_xs_layout_20260906.json \
  wolvrix/build/artifacts/grhsim/cpu_xs_schedule_20260906.json
```

从已验证布局 checkpoint 只构造 schedule，再校验/存储/加载/再次存储：exit 0，28.67 秒，
峰值 RSS 3,714,220 KiB。日志：`wolvrix/build/artifacts/grhsim/cpu_xs_schedule_20260906.log`。

| 表 | sources | activate 边 | arm 边 |
| --- | ---: | ---: | ---: |
| inputFanout | 7 | 430 | 6 |
| computeSupernodeFanout | 875,524 | 2,510,273 | 484 |
| commitStateFanout / E | 626,747 | 232,719 | 394,041 |

task=514，roundSeeds=3,819，input shadow arena=32 bytes。分区、布局数据不变；原 449 事件域
全部保留。state-arm 边是历史对应域的稀疏引用，并非 695k x 449 的全域笛卡尔积。
roundSeeds 当前较保守，不能将其 runtime 成本在没有仿真数据时忽略或随意删除。

## 真实 Make 入口

Python editable package 已离线重建安装后执行：

```bash
make --no-print-directory xs_wolf_grhsim_ir \
  WOLF_ENV_SOURCED=1 XS_WOLF_DEPS= PYTHON="$PWD/.venv/bin/python" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_schedule_20260906.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_schedule_20260906_roundtrip.json \
  RUN_ID=20260906_cpu_schedule
```

exit 0，69.32 秒，峰值 RSS 28,328,832 KiB（含 flat GRH），schedule 含 verifier 2,587 ms。
这是恢复 flat GRH 后的 lowering + 八个 CPU pass，不是重新运行前端九个 pass。

- 路线日志：`build/logs/xs/xs_wolf_grhsim_ir_20260906_cpu_schedule.log`
- 计时：`wolvrix/build/artifacts/grhsim/cpu_xs_make_schedule_20260906.time`
- C++ 输出及 `.roundtrip.json`、Make 输出及 `_roundtrip.json` 四份 SHA-256 全部一致：
  `65481844da42a7a04fb5346e8f9354c53ccf7c8a29779af0df477df976b06f68`。

## 未完成项

下一步是 C++ emitter/生产运行态和独立 build/run 入口。必须使用当前 G/history/E 语义，
不能冻结 history 重复消费输入边沿，也不能清掉下一轮 arm；task/DPI history 同样需要轮末
提交和 E 变化检测。多写口、四态、memory 与系统调用仍需 emitted-code 验证。

HDLBits 全量、多时钟 Verilator 差分、CoreMark 10k/50k difftest 和性能 parity/report 均未完成。
本记录没有仿真吞吐结果，完整目标保持 active；不执行提交，也不覆盖用户已有文档修改。
