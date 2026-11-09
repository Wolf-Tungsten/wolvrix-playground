# TNO0440：分组 RAT 接入完整 S3 的实现与局部验收（2026-11-05）

## 本阶段范围

用户在 [TNO0439](./TNO0439_behavior_state_group_local_performance_20261105.md) 局部实验后要求继续。
本阶段接入真实 `CommitRatBehaviorAdapter`，目标保持完整 S3 DiffTest/NEMU 功能。
默认仍为 hardware/ordinary；通过新的独立开关显式启用 grouped。
完整香山验收单独归档，不把局部 16–24% 收益当作整机结论。

## 真实 RAT 路径

- 新入口：`--wolvrix-sim-models commit-rat --wolvrix-behavior-state-lowering grouped`。
- `registerRatWrites` 在 grouped 模式保留原始所有 lane 的 valid/address/data 和顺序，跳过逐行
  `compactRatWrites` last-writer 网络；ordinary 仍保留旧实现。
- adapter 内只对 RAT 建组：integer/FP/vector 各 32 行，v0 一行；vector 两半索引在读取后计算。
  完整配置要求 520×4=2,080 条候选更新，不以 8 路 RAB 替代退休微操作。
- physical RF shadow、架构快照、commit data 和延迟仍走普通状态。新增 model-level lowering
  override，使一个 scope 可以包含普通模型与分组模型；manifest 明确区分二者。
- 保留原观察延迟、coreid/index/valid、skip/flush、其他 DiffTest 事件及 canonical bundle。

## Observer domain

局部模型的顶层输出边界不够描述真实 S3。现在可显式声明整个 debug 模块的 observer domain，
manifest 记录模块名、逐叶端口名/方向/位宽以及是否包含子层次，不使用 Data.toString 绑定。
本次声明 `CommitRatBehaviorAdapter` 与 `GatewayEndpoint`。

导入检查每个实际保留端口都匹配声明；firtool 可以删除未使用端口。为避免通用 `DelayReg`
同时用于 debug/reference/功能层次时被全局放行，observer 内的子层次按 domain 复制，普通实例
继续使用原图。标签只附在 state declarations 和 effects；不依靠名字前缀授权任意状态。

flatten 后，Python 和 native 检查均从 group read 出发，穿过组合依赖、已声明 debug writer
及该状态的所有 read，继续检查所有下游消费者。只允许显式 observer state 与无返回值的
observer DPI/system task；未声明的功能写口、XMR write、带返回数据的 effect 都拒绝。
这样不会在遇到第一拍 debug delay 时就停止检查，遗漏后续的功能反馈。

reg-to-mem 只在组内寄存器的 observer domain 相同时合并，并把 domain 传给新 memory；
不把 observer 状态与功能状态混在一个存储对象中。group backing memory 的独占写入约束不变。

## 已完成局部验证

产物根目录：`wolvrix/build/artifacts/behavior-state-group-s3/`。

- `scala-compile.log`：`xiangshan.test.compile` 通过。
- `adapter-v1/`：同一个真实 adapter transport 的 ordinary/grouped 两种后端，各三个种子、
  每种子 10,000 周期，对照原 Preprocess 和独立 RF/RAT 状态；integer/FP/vector、reset、
  无提交、多写、重复地址、skip、flush、commit 延迟与重复 eval 均通过。
- `adapter-v1/observer-contract.json`：typed port 错误拒绝、共享 DelayReg 隔离、合法 debug
  delay、delay 之后反馈到功能寄存器的 Python/native 拒绝，共五项通过。
- `observer-dpi/`：分组数组、普通 debug delay、void DPI 回调链，100 个上升沿逐拍验证旧值；
  重复 eval 不重复调用。

初次导入因共享 DelayReg 被保守拒绝；增加专用子图后发现部分组合 op 没有 attrs 字段，随后将
ownership 标签限定在有状态/effect op。失败日志保留；最终 `adapter-v3.log` 为通过记录。
本轮未跑全量回归。

## 工具冻结审计修正

审核 ldd 发现，之前冻结目录只复制了 Python 包；`_wolvrix.so` 仍通过 RUNPATH 链接构建目录的
`libwolvrix-lib.so`。因此 TNO0439 中的 e69a... 哈希实际是 Python 扩展哈希，不能称为整个 native
编译器的冻结身份。上一轮生成后模型/binary 没有被改动，原始运行数据保留；此处纠正工具身份表述，
不根据这个哈希补造当时 native 库的身份。

本轮完整 A/B 及后续局部构建同时复制 native 库，并用 LD_LIBRARY_PATH 和 ldd 检查确实从冻结目录加载：

```text
_wolvrix.so       e69a17390dd2f5f2f06a5ed918532f5fcc422b4b3ac47db821f3455f1449ad93
libwolvrix-lib.so c5e80d1b35e3a125fe1a7b7808a20c7c87a5b3c318936650e820901cc4fc4cee
```

旧目录不就地补成新的冻结证据；新构建遇到缺少 native 库的旧快照会要求新输出目录。

## 完整 S3 构建入口

```bash
python3 scripts/behavior_difftest_xs_study.py \
  --behavior-state-lowering grouped \
  --output build/xs/behavior_grouped_rat_20261105_v1
```

A 为原硬件 S3，B 为 grouped commit-rat S3；两组 intrinsic 均关闭，DIFFTEST、NO_DIFF=0 和
NEMU 均保持开启，使用同一源码清单和冻结工具，重新生成 RTL。先串行 B/A Chisel，再 emit/compile。
构建与计时分开；性能仍只在 node030 CPU96–127 与 sibling 空闲后进行。
本记录形成时完整构建已启动，尚无本轮整机正确性或性能结论。

## 增量更新：分文件 RTL 的绑定修正与产物复用

B 的完整 RTL gate 通过：97 个 8-bit RAT 元素、2,080 条有序更新、111 个 DiffTest 接口，
canonical `difftest-state.h` 与 A 的 SHA256 完全相同。
首次导入被正文校验拒绝，原因是 split-Verilog 在文件前添加 firtool 注释，并省略了 `endmodule`
后的末尾换行。模块逻辑、端口和正文内容未改变。

导入器仅对末尾换行做规范化，仍校验完整模块正文哈希。`eof-binding/summary.json` 验证了
无末尾换行可接受、改变 valid 条件仍拒绝。没有放宽位宽或更新顺序检查。

`build/xs/behavior_grouped_rat_20261105_v2/` 复用 v1 的 B RTL/generated headers，并保留 v1 A 的
既有构建。A 使用 ordinary 导入，不执行该 importer；两组 native 库、Python 扩展和全部 Chisel
生成源码未变，源码审计允许的唯一既有文件差异为 `wolvrix/app/pybind/wolvrix/behavior_state.py`。
因此不再宣称两个 source manifest 逐文件完全一致，而是明确记录该不影响 A 的绑定兼容修正。
所有原失败产物保留，v2 `source-audit.json` 记录复用依据。

冻结工具的不可变身份以 Python 源码/扩展与 native 库为准；解释器生成的 `__pycache__` 不作为
编译器输入身份。v2 的 `tool-code-audit.json` 核对了所有非缓存文件；后续新冻结不复制缓存并禁止写 bytecode。

额外验证：`observer-dpi-nested/` 通过复制子层次后的 void DPI 时序检查；
`transform-reg-to-mem`、`emit-grhsim-guard-activity`、`emit-grhsim-cpp-memory-fill` 三项 CTest 全通过。
A emit 用时 1,480.726 秒；此时 B 已通过完整 binding 导入，整机 runtime 验收尚未开始。
