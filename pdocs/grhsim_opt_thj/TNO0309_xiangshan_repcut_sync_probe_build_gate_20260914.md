# TNO0309: XiangShan RepCut sync probe build gate

日期：2026-09-14

状态：`ISOLATED PROBE BUILD AND LOCAL TESTS PASS; DIAGNOSTIC PAIR STARTED; NO PERFORMANCE SELECTION`。

前置：[TNO0308](./TNO0308_xiangshan_repcut_nk32_sync_diagnosis_plan_20260914.md)。

## 1. 实现范围

实验根为 `build/repcut_nk32_opt_20260907/`。新实现位于 `sync_probe_20260914/`，
生成目录 `sync_probe_20260914/generated-v1/`。`generate_probe.py` 对原 runtime/generated-v1
common 源的唯一锚点增加回调前后事件；`sync_probe.h` 内嵌于 common_runtime_support.inc。
只有 common 和该 support 文件变化；类头、runtime_config.h、step_pipeline.h 逐字节不变。
单 simulator、N=K=32、empty early phase 硬检查；不新增调度算法。

每 lane 64-byte 对齐且大小为64的独立事件槽，依赖原 dispatch/completion 的 happens-before
关系发布数据；采样 hook 不取新锁、不增加 atomic、也不查询 registry。host 在原完成同步
返回后复制 buffer，原 finalUpdateEnd 用作 host_return，不把复制时间算入该时间戳。
固定采样步号1、17、33……，最多8192个样本，超限抛错而非丢数据。

实际输出格式与最初草案不同：仅在 worker shutdown 后输出一次 `[sync-probe]` 单行 JSON，
包含 schema_version=1、mode、lanes、sample_stride=16、sample_offset=1、total_steps、
sample_count/expected_sample_count/invalid_samples/valid 和 records 数组。每 record 保存
step、dispatch_begin_ns、host_return_ns，以及32 lane的part、四个事件时间与event_counts。
不在模拟 step 内写日志。精确定义见实现目录 SCHEMA.md。

## 2. 构建与测试

使用冻结 `build_wrapper.py --name syncdiag-v1 --source-package .../generated-v1 --cpu 35`，
在 node029 单核构建，未占 node031 性能资源。只重编 common，原完整 compiler/link argv、
原无额外-O优化级别、1422模型对象、47外层对象和32 archive的身份及编译器marker复核通过。
生成 ELF SHA-256：`9c712a49da635561cf10ab37b397252a9882698c127c3957d475cf26e81bea8a`，
build elapsed12.168秒，manifest 位于 `builds/syncdiag-v1/build-manifest.json`。
collector SHA：`0a64973112b45e477a4220945a175a0aba26cdd06207f45b612e739d0394d681`。

5项生成器/collector测试通过，含C++17 legacy/pipeline-workers/pipeline-host并发mock，
严格事件数量/相位顺序、固定采样步号、映射、输出保护。mock在-O2下用于正确性测试，
不改变实际封装构建选项或作为性能证据。
新增 `measurement/analyze_sync_probe.py` 及5项测试，覆盖缺失/重复lane、错误步号、
反向时间、跨phase发布、事件计数、payload配置/总数及每步关键路径精确闭合。
原47项测量/校准测试仍通过。

## 3. 独立诊断 pair

`specs/stage1_syncdiag_v1.json` 明确两臂同诊断ELF、A legacy/B pipeline-workers，
连续映射和push。node031 CPU96-127、NUMA1、monitor35，完整SMT288-319纳入门禁；
预检三窗口目标及SMT mean/min idle均100%。

```text
pair-id: stage1-syncdiag-20260914-node031-reserved96-pair1
AB tag: stage1-syncdiag-20260914-node031-reserved96-ab1
BA tag: stage1-syncdiag-20260914-node031-reserved96-ba1
```

冻结run_pair.py按原C100/C10000、admission-only retry4次/5秒、timeout600秒依次执行AB/BA。
诊断模式仍保留原page/worker/CPU判定；最终probe analyzer复核所有8条原始事件，未满足
事件完整性不得用残缺样本归因。该ELF的Host受插桩与布局影响，不用于性能选型，也不与
TNO0307无probe数值合并。实际结果另篇归档。
