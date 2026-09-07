# NO0537 GrhSIM IR CPU emitter gate

日期：2026-09-06

承接 [NO0536 emitter 计划](./NO0536_grhsim_ir_cpu_emitter_plan_20260906.md)。首版
`cpu.st.emit-cpp` 生产骨架和小型 emitted-code 验证已完成；XiangShan 完整 emitter 与 CoreMark 仍未完成。

## 已验证

- legacy `emit-grhsim-cpp` 与 memory-fill 回归 2/2 通过（约 167 秒）。共享数值运行库已从
  原 emitter 机械抽取，抽取前后 body SHA-256 为 `6a60582bd114180db7ffac43dd6ba7a4391f32f63287a9aff753604dbf9d6562`。
- 新 emitter 直接消费 complete CPU mapping，生成 runtime/header、每个 task 的 C++ 文件及
  standalone Makefile；Emit pass 不修改 model revision，拒绝非空输出目录和不支持类型/初始化。
- 双时钟、派生门控时钟、异步复位、锁存器、两个 masked 写口通过 Verilator 对照，4,104 次采样通过，启用 UBSan。
- 生成模型 Makefile 和 Verilator 编译成功；标量运算覆盖生成路径，包含 `INT64_MIN / -1` 的
  signed overflow corner，定向 CTest 已通过。

## 未完成

fixture 暂去掉 Verilator 不支持的动态 wildcard 比较，生产 emitter 仍不得删除这些 op。

直接加载 XiangShan schedule checkpoint 并运行 emitter 时，入口在首个能力门禁处拒绝：图中
同时存在 4-state 类型以及最大 79,263 位的 2-state 类型。该结果确认了下一阶段必须先实现
四态/宽值表示，再进入 memory、DPI 与 system task 覆盖；尚未生成可运行的 XiangShan C++。

顶层 Makefile 已接入 `XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR`，并通过 `make xs_wolf_grhsim_ir`
实测执行到 emitter；本次 Make 路线在同一能力门禁失败，未绕过项目构建入口。

随后修正类型分类：数组包装类型不再被当作普通四态标量；emitter 增加了按连续 object arena
读取数组元素的 `core.state.memRead` 生成路径，并对数组整体写入保留显式门禁。`wolvrix-lib`
目标已成功重编译，尚未重新运行完整 XiangShan Make emitter。

已进一步接入 `core.state.memWrite`：按现有 `Pending`/轮末 publish 机制复制 array shadow，
再按 `%address/%data/%mask` 更新元素，并保留 event history staging；库目标编译通过。
已补齐 `core.state.memWriteSeq` 的三元组顺序写入；同一 shadow 内按源顺序执行，后写覆盖前写，
并复用事件历史 staging。新增 `core.state.memFill` 的全 array 广播写入；`memAssign`、四态元素
和宽元素仍未覆盖。

Make binding 刷新后，类型门禁已收窄为只检查实际 scalar logic 能力，避免 `core.string` 等类型表
元数据提前终止 emitter；非 logic 对象在真正生成访问时仍显式拒绝。

进一步将位宽检查移到实际 scalar 生成点：类型表中的超宽 logic 不再提前中止整图，使用该类型
时会得到明确的 scalar width/domain 能力错误；这为后续接入宽值运行时保留了正确的诊断边界。

XiangShan 实际包含大量 compute、6,527 DPI call、7,235 system `fwrite`、memory 读写、
832 init.fill 和 random；当前 emitter 尚未覆盖 memory/array、DPI/system task、random/readmem/fill、四态和宽值。
因此尚不能运行完整 XiangShan emitter 或 `xs_wolf_grhsim_emu`。

后续先完成 scalar/vector/memory/call emitted tests，再补 XiangShan runtime ABI、生产 emitter、
HDLBits、多时钟全量差分和 CoreMark 10k/50k。
