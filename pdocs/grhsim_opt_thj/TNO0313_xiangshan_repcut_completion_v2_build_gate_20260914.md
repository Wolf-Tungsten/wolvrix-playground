# TNO0313: XiangShan RepCut completion-v2 build gate

日期：2026-09-14

状态：`CORRECTED CANDIDATE BUILD/MOCK PASS; AB/BA PENDING`。

前置：[TNO0312](./TNO0312_xiangshan_repcut_completion_v1_invalidation_20260914.md)、
[TNO0308](./TNO0308_xiangshan_repcut_nk32_sync_diagnosis_plan_20260914.md)。
本次是同一个 completion-only 候选的正确性修正，不扩展为新的屏障/自旋运行时。

## 1. 修改边界与正确性

从 frozen runtime-v1 生成 `completion_tail_20260914/generated-v2`，仅改 step_pipeline.h：
每个 lane 在 update callback 之后 release fetch_add；Host 用 acquire load 观察全部完成；
最后一个 lane 必须取得 Host wait 的同一 mutex 后 notify_one。其余 eval barrier、
start epoch、callback、分区、push 端点与映射都不变。

最后通知的锁与 Host 谓词检查/入睡转换互斥，堵住 v1 的漏唤醒窗口。所有 update 写入通过
原子 RMW release sequence 向 Host 的 acquire load 发布；下一 step 仍须等待全体完成。
若 Host 先观察全部完成并启动下一 step，迟到的旧通知只引起谓词重检，无剩余旧计数增加。
stop/error 路径仍持锁发布停止状态并通知，shutdown join 后才销毁对象。

completion 代码块的锁次数每步由32降至1；不是整个调度器每步只剩1次锁，worker 返回
start wait 时仍获取共享 mutex。该修改是否省 Host 时间，必须实测，不能仅按锁次数推断。

## 2. 测试和构建证据

所有路径以下列实验根目录为基准：`build/repcut_nk32_opt_20260907/`。

- v2 生成器3项测试通过：最后通知锁、仅一个文件变化、冻结源漂移/已有目录拒绝。
- 新编译 `completion_tail_20260914/test_candidate_v2.cpp` 先包含 v2 header，再复用原 mock
  测试体，同 include guard 保证基线类定义不被重新选入。Clang21.1.5/C++17/pthread/O2、
  `-Wall -Wextra -Werror`；运行通过1/8/32 lanes、worker/host两模式、每组300步串行签名、
  phase/step边界、初始化/eval/update异常、重复shutdown与外部取消。不是复用旧测试二进制。
- 原 measurement/calibration 47项测试重新运行通过。
- `build_wrapper.py --name completion-tail-v2 --source-package completion_tail_20260914/generated-v2
  --wrappers common --cpu 35` 在 node029 用7.385 s完成 common-only 重建。保持原 C++17
  无额外优化 wrapper flags、class ABI、冻结对象顺序与1422个模型对象身份/编译器审计。
- v2 header SHA：`cadaf4e6265401934da8b501482242c54ecdc9cf4842217257709bdb5515bb01`。
- ELF：`builds/completion-tail-v2/emu`，SHA
  `69792905bdee89cbe516e76b3f5236c63f2522810a434b16b2af81de4c1e3739`。
- manifest SHA：`51373ff01474281e74e3e76035088b2e9538cf16b93f7b903cfca5eeb073fe86`。

## 3. 复测冻结配置

A=frozen runtime-v1 legacy，B=completion-tail-v2 pipeline-workers；关闭新增诊断 probe。
N=K=32、identity mapping、push，优先 node031 CPU96-127/NUMA1/SMT288-319/monitor35。
独立 spec `specs/stage1_completion_tail_v2.json`，每序 C100→C10000，完整 AB 后 BA。
沿用冻结 runner/analyzer、每臂本地独占 tmpfs inode、page/worker至少3次快照、原CPU verdict；
只对未launch admission最多4次重试。两序均改善且 pooled Host减少至少2%才暂选；
否则保留 legacy，不将不同轮次原pipeline绝对值用来估计本次修改收益。

完成后独立记录 runtime 结果。本轮不测试 ASC 拆分，也不改生产默认。

## 4. 增量更新 2026-09-14：独立回归复核

独立 reviewer 再次用 `-include generated-v2/step_pipeline.h`、C++17/O0 新编译完整 mock，
测试通过并核验预处理后的类定义确实是v2。另增加 `test_completion_notify.cpp`，以测试专用
private成员访问控制实际 execute_lane 完成路径的交错：Host持锁、检查未完成后放行worker。
v1可以在Host仍持锁时完成通知，随后的50ms wait超时；v2通知者被Host锁阻挡，Host入wait
后收到通知。初次加20次重复均通过，未观察到spurious wakeup。

这是受控重现漏通知机制，不是声称仿真实跑已经挂死，也不是覆盖全部交错的形式证明；
public run()另由完整mock覆盖。未执行TSAN。命令、测试源码/ELF hash和完整限制记录在
`completion_tail_20260914/audit-review-20260914.md`。该回归没有修改生产候选header。

## 5. 增量更新 2026-09-14：复测完成

冻结配置下的AB/BA已完成，结果独立归档于
[TNO0314](./TNO0314_xiangshan_repcut_completion_v2_ab_ba_result_20260914.md)。
两序均慢于legacy，不采用v2；第3节的“待运行”属于启动前状态。v1正确性否决、v2性能不选
的机器可读标记新增于 `completion_tail_20260914/DECISION.json`，历史原始产物不覆盖。
