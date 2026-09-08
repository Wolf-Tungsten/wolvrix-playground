# TNO0280: XiangShan RepCut N=K=32 four-stage experiment plan

日期：2026-09-07

状态：`PLAN REGISTERED; IMPLEMENTATION AND RESOURCE CHECK IN PROGRESS`。

## 1. 用户授权与固定范围

用户要求依次测试四项，并按本目录规则记录：

1. 减少阶段派发往返，明确 host 是否参与计算。
2. 优化 partition 到 CCD 的映射。
3. 尝试接收方负责输入更新。
4. 在确定的执行框架下，校准通信成本并修改划分后处理目标。

本轮固定 `N=K=32`，不做 N<K，不拆大 ASC。初始 control 是
[TNO0279](./TNO0279_xiangshan_repcut_n8_n32_communication_runtime_diagnostic_20260907.md)
中的 clean-v4 closure-aware 划分，而不是旧 baseline 划分。实验只改独立实验树，
旧 frozen ELF/package/runner 保留；不据诊断性能自动修改生产默认值。

实验根目录：`build/repcut_nk32_opt_20260907/`。

## 2. 四阶段定义

### 2.1 阶段一：调度与 host 参与

保留 C++17 与既有 model ABI，优先只重编 common 调度封装，复用经过身份检查的
clean-v4 partition objects。先比较 legacy 与 pipeline-workers，再独立比较是否
让 host 执行一个 partition。后一模式为 31 个后台计算线程加 host，共 32 个
计算执行线程，不额外占用第 33 个计算核。

目标执行顺序是一次 step 派发后，worker 计算、全体同步、数据更新、完成同步。
不得在其它 partition 仍计算时发布新输入。实验快路径只在 `N=K=32` 且 early
phase 为空时启用，非法配置硬拒绝，不能静默切换语义。

需要验证功能终点、每个 partition 执行次数、线程归属、启动/取消/析构无死锁，
并在日志显式记录实际模式。旧线程本身已常驻，本阶段不是重复建设线程池。

### 2.2 阶段二：CCD 映射

固定阶段一选择的执行路径与相同 partition model。由 package manifest 的真实
源/目的端点和位宽建立通信图，在四个 CCD、每 CCD 八个物理核的容量约束下，
生成固定的 partition-to-worker/CPU 映射。只比较连续编号映射与候选映射，
不改变图结构、分区数、逻辑拷贝量或 SMT 使用方式。

静态目标和映射在性能运行前冻结，不从本轮 Host 样本反复挑选映射。保留跨 CCD
加权端点规模及各 CCD 通信负载，不把 KM1 proxy 直接称为物理总线字节。

### 2.3 阶段三：接收方更新

保持阶段边界和相同输入/输出值对应关系，比较 source-owned push 与
destination-owned pull。检查所有 unit-to-unit 与 unit-to-top 更新端点的完整性、
唯一性、位宽和发布 phase；不能只验证 C++ 能编译。

per-part update 计时的所有权会从发送方变为接收方，因此跨模式比较优先采用整个
global_update wall 和每 worker 关键计时，不能把同名 part 的 push 数值解释为同一
工作集合。不把假设中的缓存行争用预先写成已确认根因。

### 2.4 阶段四：通信成本与划分后处理

先利用已选执行框架下的端点/计时数据明确通信成本口径，再构造独立后处理候选。
不再以所有次大计算负载更整齐为唯一主要目标，尝试在保护最大计算负载的条件下
减少通信和更新尾部；保留复制总量约束及 giant ASC，不扩大求解空间到拆 ASC。

原始 assignment、候选 assignment、exact closure、复制与通信静态指标均记录身份。
若改变 partition model，必须独立 emit/build 并完成对象编译器与功能检查；不能沿用
前面旧模型对象冒充新划分。映射和通信组织保持与该阶段 control 可比。

## 3. 构建与测量协议

- 复用输入为 clean-v4 closure-aware，ELF SHA-256 为
  `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55`，
  assignment SHA-256 为 `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589`。
- 保持 Clang21.1.5、Verilator5.048、CoreMark image 与 NEMU。任何复用对象逐项记录
  来源/SHA，校验编译器 marker；共 1422 个候选模型对象，不与旧 baseline 的 1386 个混用。
- 独立构建无功能变化的 control，先校验 frozen 行为，避免只改 treatment 的构建方式。
- 仅在用户允许的 node029-node034、node036-node042 中选资源；优先 node030。
  使用同 NUMA 的四个完整 CCD，各取一个 SMT thread，monitor 在目标 CCD 外。
  构建尽量放另一节点，不停止任何其它任务。
- 每臂/每序独立 NUMA-local tmpfs 输入 inode，保留原页面覆盖率、本地率和至少
  3 个有效快照要求。日志、模式、实际 CPU 映射与线程组成分别核验。
- 每个对照先过 C=100，再以 C=10000 做 AB/BA。每个性能臂首次 admission 通过后
  只启动一次；所有 launched 样本保留，不按 Host 或 CPU accounting 残差重抽。
- 延续 [TNO0278](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md)
  的 balanced diagnostic 分类，保留原始 CPU audit verdict、十字段和读取窗口。
  功能、身份或计时产物错误停止该变体；不把已知不闭合差额当成精确外来 CPU 时间。

## 4. 决策与记录

每项实验的实现/验证与性能结果按独立阶段另建递增 TNO，并同步 README。
原记录只追加状态或勘误，不覆盖失败实验。

Host 是首要指标，同时报告 eval/update phase、关键 worker、累计函数计时、
instructions/task-clock/cycles、上下文切换、页面和线程证据。阶段剩余时间仍是混合量，
不是纯 barrier。

只有功能/身份/页面/线程证据完整、AB 与 BA 都缩短 Host，且两序中心改善至少 2% 时，
才暂选为下一阶段的实验 control；这只是探索阶段的预定选择规则，不是统计显著性或
正式生产提升判定。幅度小于 2%、两序反向或资源污染明显时保留前一 control，并记录
候选为不确定/未采用。必要的确认应重跑完整独立 pair，不单独替换不利臂。

四项都要得到实际执行结果或明确的功能/构建/资源阻断证据；不能只凭静态指标宣布
性能优化完成。运行进展将追加于相应阶段记录，最终统一给出各项保留/停止结论。

## 5. 增量更新 2026-09-07：准备完成，性能资源阻断

实现/结构与构建入口记录已形成 TNO0281..TNO0288。完整冻结 assignment 重建的
70 个 package 源文件和 33 个 flat-SV 逐字节复现，并完成双实现指标复核，见
[TNO0287](./TNO0287_xiangshan_repcut_nk32_full_control_reproduction_20260907.md)。

四项 runtime 比较均未完成。全部允许节点双 NUMA 多轮扫描后，四次配对入口共 40 次
admission 均拒绝、实际模型 launch=0，未进入 C100，更无 C10000/BA/性能 summary。
因此没有选择新的 scheduler、mapping、update mode 或 assignment；原控制配置不变。
具体资源证据见 [TNO0286](./TNO0286_xiangshan_repcut_nk32_resource_blocker_20260907.md)，
完整构建入口与续跑边界见 [TNO0288](./TNO0288_xiangshan_repcut_nk32_full_build_entry_gate_20260907.md)。

这次只将工具准备与原模型复现记为通过，不将四项性能实验标成完成。需取得满足原门槛
的持续四 CCD 窗口后，仍按本篇既定顺序从阶段一开始，不放宽阈值或以繁忙数据替代。
