# TNO0156 SimpleTES auto-research bench and launch gate

记录日期：2026-07-20

状态：已把 current-default GrhSIM SimTop 50k 优化任务实现为 SimpleTES bench；安全隔离、结构化输出、fresh build、fixed-ASLR 功能门禁和动态 CCD runtime 协议均已完成。指定的 `gpt-5.6-sol` / `ultra` / MJY API 真实 schema preflight 最终返回 `0`。本记录尚无 accepted 50k 样本，因此不产生性能或默认采用结论；正式 run 的初始 control 会重新给出当前提交上的绝对 walltime。

相关口径沿用 [TNO0087](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) 的 page-local trusted runtime 与 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) 的 walltime headline。

## 1. Pinned baseline and unchanged production tree

bench 固定以下当前工作树提交：

```text
playground parent  b90d20461d276def682f19a28be1fe65a4387eef
wolvrix submodule f17e90e14c3ad70a3ee93f7c6540e13dae54940a
SimpleTES bench    0589387d3ea2eb9542b29aca9373ad42aa1780bf
```

比较基线始终为这两个 GrhSIM 提交的默认生成配置，不使用历史 rollback 或实验 override。现有 current-default 结构参考绝对值为：supernode `63,709 = 63,241 compute + 468 commit`，compute DAG edge `527,990`，boundary value `1,000,463`，总 BAE `1,983,326 = 1,721,698 compute pairs + 261,628 commit pairs`。这些结构值只用于诊断，不代替 50k walltime。

本阶段没有修改 `wolvrix` 源码或 submodule pointer，也没有保留任何候选优化；所以没有 submodule code commit。后续只有在 current-default control 对照下获得端到端 walltime 正收益的补丁，才允许进入用户工作树、文档和 submodule-first 提交流程。

## 2. Bench contract

新增 bench 位于相邻 SimpleTES 仓库的：

```text
datasets/grhsim/simtop_50k/
```

模型每次只返回一个 JSON candidate，字段为 `schema_version/hypothesis/evidence/patch/enable_options`。Structured Outputs 为兼容服务端 JSON Schema 子集，使用 `enable_options=[{"name": ..., "value": ...}]`；evaluator 随后规范化为闭集字典。

候选边界如下：

- patch 只允许修改 `wolvrix/lib`、`wolvrix/include`、`wolvrix/app/pybind` 下已经存在且被 Git 跟踪的 C/C++ source/header；禁止新增、删除、rename、binary、symlink、test、CMake、pyproject、父仓库脚本和 submodule 修改；
- option 名称使用 pinned optimization allowlist；resume/stats/profile/probe/report/stop/export/instrumentation/measurement 均不可选；
- disabled 候选必须与 current-default generated C++/header fingerprint 完全一致；
- enabled 候选还必须与“unpatched、same-options” fresh emit 不同，防止用 no-op patch 冒领已有 knob 的历史收益；
- evaluator-owned make assignments 最后写入，固定 `resume-from=0`、stats/perf/waveform off、单核和双 emu thread，候选 option 不能覆盖测量配置。

evaluator 不修改用户 checkout，而是在 `/tmp/simpletes-grhsim-simtop-50k` 的单锁 slot 内 clone pinned parent、`wolvrix` 与已经初始化的 XiangShan submodule graph。control cache 只有在 parent/submodule/env/build config/toolchain/generated fingerprint 与 ELF/image/NEMU SHA256 全部一致时才复用。

## 3. Build, function, and runtime gates

每条 target build/runtime 命令先 source 对应 isolated checkout 的 `env.sh`；正式 launcher 本身也先 source 当前 target `env.sh` 再 exec SimpleTES。每个候选依次执行：

1. unpatched same-options fresh emit attribution gate；
2. patched disabled fresh build、focused tests、fixed-ASLR `100/10k` function gate和 default-off identity；
3. patched enabled fresh O3/link、focused tests、fixed-ASLR `100/10k` function gate；
4. fixed-ASLR SimTop `50k` ABBA runtime；若 walltime 初筛正向，再 fresh 执行 BAAB；
5. 唯一功能终点 `guest/cycleCnt/instrCnt/PC = 50001/49996/73580/0x80001312`，且 emu log 只有一个正整数 `Host time spent: Nms`。

runtime 从 sysfs L3 sharing 动态枚举完整 CCD，不固定 CPU 编号。一个 group 固定同一 CCD、target CPU、SMT sibling 和 CCD 外 helper CPU；pre-gate 连续 `3 s` 要求 16 logical CPU mean idle `>=98%`、minimum `>=95%`、target/sibling 各 `>=98%`。运行中排除 target 的其余 15 logical CPU 必须 mean `>=98%`、minimum `>=95%`。

命令层级固定为：

```text
taskset -> numactl --physcpubind/--membind -> perf stat -> setarch x86_64 -R -> emu
```

staging 使用目标 NUMA CPU/memory policy 在 `/dev/shm` 复制 fresh inode 并核对 SHA；运行中审计 CPU affinity、`/proc/$pid/personality=00040000`、resolved executable、`numa_maps`、五个 PMU event scheduling、task-clock、context switch rate、zero migration 和功能 signature。外部负载或 placement/audit 污染返回 retryable infrastructure，不消耗 valid-candidate budget。

headline 只用 ABBA/BAAB 中 control 和 candidate 原始 `Host time spent` 的算术均值：

```text
score = control_mean_walltime_ms / candidate_mean_walltime_ms
```

metrics 同时保存 control/candidate 的绝对 milliseconds、绝对差值、相对百分比、每个原始 sample 和 control spread。PMU/结构/source/ELF 只解释 walltime。

## 4. Search budget and credential boundary

正式 launcher 固定：

```text
model/reasoning       gpt-5.6-sol / ultra
selector/chains       rpucg / 4
k/gen/eval concurrency 1 / 1 / 1
reflection            off
valid candidates      8
maximum proposals     16
```

MJY config/auth 的 source path 只由 launcher 传给 backend。backend 从指定 auth JSON 读取 `OPENAI_API_KEY`，不把 auth 文件复制到模型可读的 `CODEX_HOME`；key 只存在于父 Codex 进程环境。模型工具采用 `shell_environment_policy.inherit=none`、private `HOME`、read-only sandbox、network disabled、MCP/notify disabled、approval never、ephemeral session，并拒绝 auth 值出现在 raw 或 JSON-decoded output。stderr 只有完成 auth/token pattern redaction 后才可作为错误诊断。

这一设计来自一次假 key sandbox probe：旧方案中的临时 `auth.json` 实测为 tool-readable，因此在任何正式调用前已删除该方案。没有把真实 key 内容写入 argv、测试、日志、checkpoint 或本文。

## 5. Validation and preflight results

SimpleTES 全套回归绝对结果：

```text
98 passed, 17 warnings, 4.13 s
```

warning 均为既有 `datetime.utcnow()` deprecation。附加 `py_compile`、candidate `--validate-only`、launcher `--dry-run` 与 `git diff --check` 全部通过。

真实 API bring-up 保留以下阶段结果：

1. 首次安全 env-key 方案连接 endpoint，但 provider 未绑定 `OPENAI_API_KEY`，返回 HTTP `401 API_KEY_REQUIRED`；加入 `model_providers.OpenAI.env_key` 且关闭 `requires_openai_auth`；
2. 认证随后通过，服务端拒绝 JSON Schema `propertyNames`（HTTP `400 invalid_json_schema`）；将 option contract 改为 enum name/value array；
3. 最终相同 model/effort/config/auth/repo/schema preflight 返回 `preflight_rc=0`。

本机 runtime smoke 找到 `24` 个完整 16-logical-CPU CCD，`taskset/numactl/perf/setarch/mpstat/cp` 全部存在，ASLR probe 绝对 personality 为 `00040000`。2026-07-20 约 01:40 的单次 3 秒全机 survey 中严格通过 CCD 数为 `0`；当时最佳 CCD mean idle `98.314%`、minimum `92.030%`，因 minimum 低于 `95%` 被正确拒绝。该窗口没有启动 emu，因此 accepted sample 数 `0`、absolute 50k walltime 数 `0`，不能形成相对性能结论。正式 launcher 将继续等待 retryable quiet window，而不会降低门槛。

## 6. Next record boundary

本 TNO 只闭合 bench、API 与 launch gate。正式 SimpleTES 初始 control build、accepted ABBA walltime、候选 proposal/evaluation、任何保留或停止结论应另立后续 TNO，逐项记录绝对 `Host time spent`、相对变化、control spread、artifact path 和提交关系。
