# TNO0282: XiangShan RepCut N=K=32 measurement protocol gate

日期：2026-09-07

状态：`MEASUREMENT IMPLEMENTATION AND 35 UNIT TESTS PASS; RUNNER FROZEN; NO PERFORMANCE CONCLUSION`。

## 1. 范围与依赖

本篇记录 [TNO0280 四阶段计划](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)
所需的独立测量入口；实验构建身份见
[TNO0281 scheduler build gate](./TNO0281_xiangshan_repcut_nk32_scheduler_build_gate_20260907.md)。
本篇不是 runtime speedup gate，不将 unit test 或构建成功当成性能结论。

新工具位于 `build/repcut_nk32_opt_20260907/measurement/`：

- `run_pair.py`：显式配置 A/B，完成 page-local staging、C100 canary、C10000 fixed capture。
- `analyze_pair.py`：重新解析原始 artifacts，核对 AB/BA 身份并汇总全部四条预定性能 launch。
- `test_measurement.py`：35 项本地单元测试，不运行远端仿真。

冻结旧 `run_parallel_pair_v5.py`、`run_n1_pair_v2.py`、底层 protocol、raw proc/stat sampler
均不修改。新 runner 复用 v5 的 workload-bounded audit，继承页面和 CPU 计量逻辑；仅新建
与实验布局对应的线程分类及命令配置。

## 2. A/B 配置与 N=K 约束

本轮使用显式 `A=control`、`B=treatment`，不再把 arm 名称固定为
`baseline/closure-aware`。具体 control/treatment 含义以每组 spec 的 `label`、ELF、manifest
及环境配置为准；例如 stage1 可在同一实验 ELF 上比较 `legacy` 与 `pipeline-workers`，
以控制实验插桩影响。旧 frozen closure-aware ELF 仍可作为独立 control 身份依据。

每个 arm 显式记录：

- `binary` 与 `build_manifest`，要求 manifest schema 1、status pass、binary path/SHA/size 一致。
- `runtime_mode=legacy|pipeline-workers|pipeline-host`。
- `worker_to_part`：`0..31` 的双射；worker CPU 顺序是所选物理 CPU 的升序。
- `part_cpus`：由 worker-to-part 映射反推的每个 partition 实际目标 CPU。
- `update_mode=push|pull`、显式 `WOLVI_REPCUT_*` 环境变量及 `runtime_config_required`。

固定 `N=K=32`、`XS_EMU_THREADS=32`、C100/C10000；要求 32 个不同物理核位于同一 NUMA node，
目标 CPU 加其 SMT siblings 恰好覆盖四个完整 L3/CCD。monitor CPU 及其 L3/SMT 不得进入目标 CCD。
`--expected-host` 防止在错误节点运行。每组 AB/BA 必须具有相同 host、boot、kernel、CPU/NUMA、
代码、工具链、环境、映射、runner 和 protocol 身份。

继承的 `WOLVI_REPCUT_*`、`XS_EMU_*`、`LD_*` 被移除，再使用记录在命令中的显式实验配置。
新 runtime 的 `[runtime-config] {JSON}` 必须与预期 mode、32 lanes、后台线程数、host CPU、
worker CPU、worker-to-part、part CPU 及 update mode 相符。仅精确匹配历史 frozen common SHA
的 legacy、identity mapping、push、无附加 env 配置允许缺少该新增日志。

## 3. 源码 inventory 修正

首次独立 review 发现 wrapper relink manifest 同时包含：

- `package.inventory_path`：冻结原包 inventory；
- `package.source_path`：冻结原包目录；
- `package.staged_path`：实验 common/header/support 文件目录；
- `source_files`：本次实际使用的源码 identities。

不能把冻结 inventory 的 common SHA 拿去验证实验目录的新 common。冻结前已修正：
当 manifest 提供显式 `source_files` 时，inventory 在 `source_path` 核验，记录为 `base/*`
来源；实际 scheduler identity 取非 `base/*` 的 `source_files`，不被旧 inventory 覆盖。
没有显式 `source_files` 的旧 manifest 继续在原 `staged_path` 核验 inventory。

修正后实际读取 `control-v1/build-manifest.json` 与 `runtime-v1/build-manifest.json`，分别
核验 8/11 个源码或 inventory identities 通过。runner 在结束前重新核验 binary、manifest、
source、runner/dependency/spec 身份；analyzer 再核验并拒绝身份变化。

## 4. Host lane 与辅助线程审计

| runtime mode | 后台计算线程 | main mask | Verilator 辅助线程 |
| --- | ---: | --- | ---: |
| legacy / pipeline-workers | 32，分别 singleton 覆盖全部目标 CPU | 全目标 CPU mask | 31，全目标 CPU mask |
| pipeline-host | 31，分别 singleton 覆盖 worker CPU 1..31 | worker CPU 0 singleton | 31，全目标 CPU mask |

pipeline-host 的 host 计算的是 `worker_to_part[0]`，不一定是 `part_0`；所以 host CPU 必须
等于 `worker_cpus[0]`，不能错误要求等于 `part_cpus[0]`。

host pin 之前的全 mask 初始化状态可以作为 partial sample 保留，但不能算 complete coverage。
C10000 至少需要 3 次 complete coverage；额外线程、重复 singleton、未知 mask、越界 mask
仍判失败。Verilator 辅助线程按 pid/tid/start_ticks 聚合 lifetime/delta CPU ticks，保留末尾
未采到的退出 tail 限制；不把它们冒充计算 worker，也不假定观测不到 CPU ticks 就绝对无成本。

C100 是短功能 canary，不强行要求页面或线程至少出现 3 次稳定采样；C10000 才应用完整
页面及 worker gate。这与既有长/短样本的 gate 分工一致，不是为新模式降低长样本阈值。

## 5. Fixed capture 与 gate 口径

每个 order 的预定顺序为两侧 C100，然后两侧 C10000；AB 与 BA 相反。只有 admission
没有通过、实际 `launched=false` 的 slot 可以在预先配置的次数内重试。任一 C100 canary
失败立即停止，失败记录保留在 attempts。进入性能阶段后，每个 arm 仅 launch 一次，
不依据 `accepted`、CPU audit、page/worker verdict 或性能数值选择性重跑。

长样本所有原始判定均保留：

- 功能、difftest/签名、预期 timing steps、36 条 timing records、perf events、运行配置及输入 stat。
- 页面 identity 按 dev/inode/可执行 VMA 联结；EMU 至少 20,000 base pages、coverage 0.95、
  local fraction 0.999；NEMU 至少 64 pages、coverage 0.90、local fraction 0.95；至少 3 次 qualifying samples。
- worker coverage，以及旧 CPU guard、foreign task、unexplained target busy 等完整原始审计。

`strict_verdict` 不豁免 runtime reason；`diagnostic_verdict` 仅按历史约定排除
`runtime_foreign_task_load`，不豁免 unexplained target busy、页面或 worker 失败。
`captured.json.status=diagnostic_capture_not_formal_acceptance`，不产生 masked accepted。

已知 proc/stat 与 perf task-clock 的计量失真继续按
[TNO0279 证据边界](./TNO0279_xiangshan_repcut_n8_n32_communication_runtime_diagnostic_20260907.md)
处理：保留 raw 十字段端点、snapshot 时间范围、workload wall、原始 strict/diagnostic verdict，
不能因为某条恰好通过就把它挑为代表性样本。

analyzer 要求 attempts 中的全部 launched records 与 captured samples 完全一致，并核验
预定顺序及 admission attempt 编号。两次 order 的 12 个 staged 输入 inode 必须全部不同。
页面/worker失败的样本仍可列出原始指标，但整组标记 `invalid_evidence_retained_without_selection`；
若任一预定性能样本缺少可解析 timing，不以剩余样本构成 pooled 比较。

## 6. 指标与解释限制

Host、step wall 和三个 phase wall 分别汇总；per-part timer 是函数局部墙钟，不是 thread CPU time。
不同 worker 的时间彼此重叠，不能将其 sum 从 phase wall 中相减当作 overhead。

pooled 先对 AB/BA primitive totals 取算术平均，再计算 worker max、sum、mean、阶段份额、
残差、A/B 相对变化及 order effect gap。`phase wall - max(worker mean)` 包含调度、等待、
wrapper 间隙和逐 step 波动，不能叫 pure barrier 或 pure communication。

pipeline scheduler 与 legacy 的 phase 边界实现不同，源码身份明确记录；跨 scheduler 首要
性能端点为 Host 和 total step wall，phase 用于机制分析。

raw timing schema 保留 `update_push_total_ms`。对 pull arm，该字段可能表示目标分区拥有的
incoming copy 加仍由源分区拥有的 top output copy；新汇总统一提供 `update_copy` 别名并标记
arm 的 `update_mode`，不将 pull 的 per-part 指标解释为原来的 source outgoing push。

## 7. 本地验证与冻结身份

执行：

```text
cd build/repcut_nk32_opt_20260907/measurement
python3 -B -m unittest -v test_measurement
Ran 35 tests; OK
```

覆盖 32-background/31+host、host lane 非 part0、缺失/额外辅助线程、重复或越界绑核、
admission-only retry、保留 rejected launch、拒绝替换或遗漏样本、映射与双阶段 maxima、
elapsed/finalization pooling、pull alias、manifest 新 mode/tag、runtime-config、命令/页面/
staging/worker/accepted flag 篡改检测。测试不包含实际远端 C100/C10000 仿真。

| 文件 | SHA-256 |
| --- | --- |
| 新 `run_pair.py`，冻结 | `7b50e6d9d7780ecc1785f0ceeedfbc8edb7d6732b94431a1f5a316ff2dad9c48` |
| 新 `analyze_pair.py`，本篇快照 | `9bbf639f05d5ac99e5418e8e239f785d7032474be77d26384f1bd8e5645c4d47` |
| `test_measurement.py` | `4c240c1aff6caf6ba2df8bca238b667392fd06588a581b8cf3587563806fadf2` |
| 旧 v5 runner | `695f5542ada4acfe3317ef843aefa78096b418a7015881d92799dabf21d95fab` |
| 旧 page-local v2 runner | `2019def21d67ef009041857c686136a686f58a156483bfa978fb5d3baa7f9f0a` |
| 旧 base runner | `3f50e79f1f47fbd81ed3f21d4fd71b27709d3ffd692f3853e0e88ee1fe2db9bd` |
| 旧 raw proc/stat sampler | `fa15d2b6525a6935cd477b080d484cf7d4e0d48d120ca5f64b6518b19882f06d` |
| 旧底层 protocol | `3bd5681185f0b9d0c6acfd783b67001a86c8441644eef66307314360b8a33a70` |

冻结后的 runner 不原地修改；若实际运行暴露协议问题，保留首轮全部产物，在独立新版本中
修正并记录原因。运行及性能结论由后续独立记录承载，不追加到本篇冒充已通过的 runtime gate。
