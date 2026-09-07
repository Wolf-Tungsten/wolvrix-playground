# NO0533 GrhSIM IR CPU data layout gate

日期：2026-09-06

承接 [NO0532 布局计划](./NO0532_grhsim_ir_cpu_layout_plan_20260906.md)。本记录只验收
`cpu.st.layout-data` 的结构和真实 checkpoint 入口，不代表可执行仿真器或 CoreMark 50k 完成。

## 实现与小型门禁

- 独立 CPU dialect/type table；标量、宽整数、四态、real、string 与递归数组物理表示。
- I/O/S object arena、持久 boundary arena、按 supernode 分配的 helper 共享 local frame。
- active word、edge-domain arm、域内 event-edge slot 显式偏移；事件历史复用语义 state。
- canonical verifier 检查完整覆盖及 lifetime；JSON 尾部扩展，旧六阶段形态保持兼容。
- 未触发 DPI 的旧结果持久保存；helper 拆分不缩短 value 生命周期；类型大小、对象偏移和
  arena 对齐使用检查过的 UInt64 算术。
- Python editable package 已离线重建安装；脚本默认 pipeline 已加入第七个 pass。

```bash
cmake --build wolvrix/build --target grhsim-cpu-mapping-tests grhsim-ir-tests -j 8
ctest --test-dir wolvrix/build -R 'grhsim-(ir|cpu-mapping)-tests' --output-on-failure
```

结果：2/2 PASS，0.03 秒。测试涵盖 1/7/8/9/16/17/32/33/64/65/129 位的符号与四态组合、
嵌套数组、函数不占数据对象 slot、helper/local、跨 supernode、DPI、事件槽、空图、JSON 往返、
类型/偏移/owner/覆盖/runtime/frame/stage 损坏、乘法与 arena 加法溢出、前置阶段缺失与失效。
本增量未重跑全部 CTest；此前两项 legacy transform 失败不在本记录中重新判定。

## XiangShan 全图

直接从 NO0531 已验证的 `cpu_xs_partition_20260906.json` 运行新 pass，不重复构造分区：

```bash
wolvrix/build/bin/grhsim-cpu-mapping-tests --layout \
  wolvrix/build/artifacts/grhsim/cpu_xs_partition_20260906.json \
  wolvrix/build/artifacts/grhsim/cpu_xs_layout_20260906.json
```

加载、layout、校验、存储、重新加载及再次存储合计 22.80 秒，峰值 RSS 3,118,476 KiB，exit 0。
日志：`wolvrix/build/artifacts/grhsim/cpu_xs_layout_20260906.log`；统计：同目录
`cpu_xs_layout_20260906_stats.log`。

| 指标 | 数值 |
| --- | ---: |
| CPU types | 405 |
| I/O/S objects | 695,065 |
| Values | 4,677,017 |
| Boundary values | 1,215,208 |
| Object arena bytes | 25,228,032 |
| Boundary arena bytes | 2,741,144 |
| Local frame bytes 合计 | 8,869,090 |
| 最大 local frame bytes | 17,944 |
| Runtime bytes | 6,524 |

运行态含 5,586 active-word bytes、448 edge-domain arms 和 490 域内 event-edge bytes。
local frame 合计不是 runtime 必须同时分配的长期内存；生命周期仍为一次 supernode 调用。
原来的 449 域、44,686 compute supernodes 与 514 函数保持不变。

## 真实 Make 入口

```bash
make --no-print-directory xs_wolf_grhsim_ir \
  WOLF_ENV_SOURCED=1 XS_WOLF_DEPS= PYTHON="$PWD/.venv/bin/python" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_layout_20260906.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=wolvrix/build/artifacts/grhsim/cpu_xs_make_layout_20260906_roundtrip.json \
  RUN_ID=20260906_cpu_layout
```

exit 0，63.47 秒，峰值 RSS 28,329,268 KiB（含 flat GRH）；新 pass 含 verifier 1,129 ms。
这是恢复已有 flat GRH 后的 lowering + 七个 CPU pass，并非重新执行前端九个 pass。
`XS_WOLF_DEPS=` 跳过已完成的 Python 安装，不跳过 CPU pipeline。

- 路线日志：`build/logs/xs/xs_wolf_grhsim_ir_20260906_cpu_layout.log`
- 计时：`wolvrix/build/artifacts/grhsim/cpu_xs_make_layout_20260906.time`
- 四份文件：C++ 输出及 `.roundtrip.json`，Make 输出及 `_roundtrip.json`。
- 四份 SHA-256 全部一致：
  `a87c3280c5d0399467e3629e1563f872f5922a2df2f5b1c79b20813d8ba9ceb6`。

## 后续边界

mapping 仍为 `complete=false`。下一阶段需生成 schedule tasks、三个稀疏 fanout 表及输入影子。
event slot 只定义存储，不代表事件消费/历史采样已实现；仍须处理草案冻结 history 与 core
每次应用 G 更新 history 的冲突，不能靠重复 arm 令寄存器链在同一边沿多次推进。
应按当前 overview 的输出/边沿状态依赖闭包推导 E，不能直接把所有 state readers 当作 E。

emitter、独立仿真 build/run 入口、HDLBits、多时钟 Verilator 差分、CoreMark 10k/50k difftest
和性能 parity 均未通过。不存在本增量的仿真吞吐或性能结论。
