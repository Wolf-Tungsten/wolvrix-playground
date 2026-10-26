# ROB 初始化反例与 runtime 补充验证

状态：初始化修复与 ROB checkpoint 全输出验证通过；性能、XS 和剩余 DPI 门禁未通过，R5/R6 不据此验收。2026-10-25 用户已批准[单个原调用语义](20261025-single-call-decision.md)，原始差异继续保留。冻结旧源、旧模型及黄金输出未改动。

## 初始化故障

原候选和超节点修订候选均编译成功，但在 init 的首批 `nonSinkBoundaryStore` 字符串 clear 处 SIGSEGV。独立模型构造/init 程序也失败，排除了 frozen bench/gsim 参与是必要条件。GDB 在 init 入口观察到对应 string 指针已经为零，写观察点在 init 到崩溃之间没有捕获更早覆盖。

- [原回溯](../../ptmp/remove-grhsim-ir/r6-rob-init-backtrace.log)、[入口观察](../../ptmp/remove-grhsim-ir/r6-rob-init-watch.log)、[独立 init](../../ptmp/remove-grhsim-ir/r6-rob-init-probe-o1.log)。
- [原始存储探针](../../ptmp/remove-grhsim-ir/r6-storage-probe.log)：只提取生成头文件的 91,906 个字段，其中 356 个 std::string；不链接仿真库，首个 string.data() 仍为 nullptr。
- [O3 缩减反例](../../ptmp/remove-grhsim-ir/r6-constructor-synthetic-o3.log)、[O0 缩减反例](../../ptmp/remove-grhsim-ir/r6-constructor-synthetic-o0.log)：本机 Clang 22.1.2 下，65,534 个带 `{}` 的 byte 字段加一个 string 正常；65,535 个加一个 string 时后者未正确构造。移除 scalar 的默认成员初始化，保留值初始化，同样字段数正常。这是本机工具链的实测边界，不推断其他版本或全部构造场景。

## 修复

新 emitter 的字段记录保留 type/name，不再先拼声明再解析变量名。named store 使用直接成员布局；chunkFrame 使用独立的跨块局部布局，字段很多时才按完整类型组织索引数组。两者都由 `writeValueStruct` 保留零初值省略、非零初值字段和显式 defaulted 默认构造函数，外部实例统一用 `{}` 值初始化，避免巨型聚合列表在各使用点展开。store、small next 与 chunkFrame 的实例均明确 `{}`，不引入手工 placement-new 或对字符串清零。

- [七万字段执行及原生成矩阵](../../ptmp/remove-grhsim-ir/r6-value-initialized-stores.log)：构造两个大结构，检查前/尾 string、string 数组、首/中/末 scalar 零值与非零默认值；执行赋值、clear、重置和析构。
- [修复后的原存储探针](../../ptmp/remove-grhsim-ir/r6-storage-probe-fixed.log)：同为 91,906 字段，string.data() 有效，退出 0。
- [ROB checkpoint 重发与比较](../../ptmp/remove-grhsim-ir/r6-rob-storefix.log)、[结果](../../ptmp/remove-grhsim-ir/r6-rob-storefix/comparison.json)：4,394,996,424 bytes 逐字节相同，exclusions=0，摘要为 688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1。这次使用零 DMI/值初始化修复，早于显式 defaulted 构造函数补充；是已知原 SV 派生 checkpoint 的诊断，不冒充最新源完整 SV 重生或正式性能 A/B。

## 补充门禁

sink 依赖仍发布完整叶 owner 闭包及其拓扑顺序；只将重复的每 writer 文本 set 遍历改为每 run 一次的稠密下标遍历。新增多 writer 共享长锥用例检查闭包与去重；原 effect 顺序、交错 clock/priority、伪造 schedule 拒绝和生命周期测试继续保留。

新执行矩阵加入 latch 振荡的 round-limit/重复 init、两种预算下 libfst reader 检查真实波形名称/数组/130-bit 值/时间序列，以及 bitmap × on-change/on-write 的取消写与越界写。[最终矩阵](../../ptmp/remove-grhsim-ir/r6-runtime-matrix-final.log)的 28 个生成模型与七万字段结构通过；[最新公共](../../ptmp/remove-grhsim-ir/r6-current-public-and-install.log) 74/74、HDLBits 162/162 和 bugcase 27/27 通过。

[sink 稠密闭包探针](../../ptmp/remove-grhsim-ir/r6-sink-probe-dense.json)在同一 ROB checkpoint 重建 6.075s；不等同于生成性能通过。新侧单次全输出运行 1133.818s，冻结旧重放 49.296s，未控制负载，不能视为正式 A/B，但性能回退必须继续定位。make profile_remove_grhsim_ir_rob 以原 trace 前 2000 周期、原 bench adapter、所有输出校验和及 perf 采样定位；它不替代全输出或 3+3 门禁。

## 连续数组热点与原 SV 重生

[修复前 bounded perf](../../ptmp/remove-grhsim-ir/r6-rob-runtime-profile.log)的 2487 个样本中，59.96% 集中在 pOutput_chunk3：8-bit 叶数组按元素反复移位 10K–32K-bit packed 值。参考旧 SixPhaseEmitter::unpackValue 的缓冲区路径，新 emitter 对无填充的 8/16/32/64/128-bit 叶使用 memcpy，并以 static_assert 检查布局；相同总宽与叶宽的 reshape 直接复制。带填充叶仍走既有路径，不改变原生两态宽值 ABI。

[30 模型执行矩阵](../../ptmp/remove-grhsim-ir/r6-contiguous-array-matrix.log)覆盖两种 chunk 预算、多维 reshape、小于一个机器字的总宽填充、8192-bit image 和三次 init；随后 [公共回归与安装](../../ptmp/remove-grhsim-ir/r6-contiguous-public-and-install.log)通过。

[最新原始 SV 完整重生与编译](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-fresh.log)使用冻结原始输入，生成 304 TU；[全输出](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-fresh/comparison.json)4,394,996,424 bytes 相同，exclusions=0，SHA256 仍为 688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1。单次运行 385.669s；[bounded perf](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-profile.log)前 2000 周期为 4.824s，checksum 与修复前相同。两者均不替代正式 3+3 性能门禁，旧侧单次 49.296s 的差距仍需处理。

XS 在 xs-storefix 从捕获 flat GRH 重启的生成已退出 0，总计 3777.054s。xs-contiguous 编译暴露巨型 concat 左折叠导致本机 Clang parser 栈溢出，已改为平衡表达式树；后续重发暴露 Value::users() 临时对象生命周期问题，也已修复。最新 xs-viewlife 隔离重发/编译仍在执行；1217 操作数表达式及 96 消费者生命周期反例已包含在最新生成模型和公共回归中。

dispatch/fire guard 与 array-view 消除后的 ROB checkpoint 全输出分别为 348.191s、247.164s，均保持原摘要和零排除；array-view 的前 2000 周期为 1.84131s、相同 checksum。359 样本中 writer 约 59.57%、largeCommit 约 15.11%、Output 约 1.10%，后续性能定位应转向 writer/提交。该完整运行早于最新生命周期修复，不替代正在执行的 r6-rob-viewlife-fresh 原 SV 重生，也不替代正式 A/B。

最新公共 74/74（106.02s）、重启 10 个模型、provenance 3 项及原生读者 16 项通过；生成执行矩阵 34 模型和七万字段构造用例通过。单个原调用策略下 dpi_bit_abi 六项已批准，dpi_smoke/TU 各九项仍未解决；XS difftest 和正式 3+3 性能均未完成。
