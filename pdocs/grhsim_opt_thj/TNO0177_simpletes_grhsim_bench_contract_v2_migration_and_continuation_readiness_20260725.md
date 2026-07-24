# TNO0177 SimpleTES GrhSIM bench contract v2 migration and continuation readiness

## 1. 状态与边界

SimpleTES 的 GrhSIM SimTop 50k bench 已完成 candidate contract v2 的实现和本地回归。该迁移使
bench 能区分“修改 C++ 原生默认路径”和“显式打开实验 option”两类候选，并把候选模式、control
产物身份和 continuation checkpoint 绑定到可验证的证据链。

本记录只归档已经完成的 v2 contract 实现与轻量验证。最终 wolvrix submodule commit、parent
commit、bench pins 更新以及真实 native-control canary 尚未完成；在这些项目完成并另行记录之前，
不能把 bench 写成已经具备最终 pinned continuation 条件。本阶段没有启动 auto research，没有调用
模型，也没有产生新的候选或性能结果。

## 2. schema v2 与三种 candidate mode

candidate canonical JSON 新增必填的 `candidate_mode`，evaluator parser 支持三种严格 shape：

| mode | patch | `enable_options` | 用途与 gate |
| --- | --- | --- | --- |
| `control` | 空 | 空 | 仅用于 pinned initial seed；直接建立 current native-default control |
| `default-path` | 非空 | 空 | 修改 C++ 原生默认路径；patched build 必须使用原生 `options={}`，generated fingerprint 必须区别于 control |
| `explicit-options` | 非空 | 非空 | 新增或改进显式实验功能；必须完成三重静态归因 |

`candidate.schema.json` 是给模型输出使用的 schema，只允许 `default-path` 与
`explicit-options`，不允许模型再次提出 `control`。init program 与 evaluator parser 则继续接受
特殊的 `control` shape，因此初始 control 的 `--validate-only` 和正常初始评估不受影响。这个分离
避免模型用空 patch/空 options 重复提交 control，同时不要求为初始 seed 复制另一套 parser。

`default-path` 不注入任何优化 option。它在 candidate patch 应用后以 `options={}` 构建，直接经过
Python `None`、XS sparse forwarding 到 C++ default；如果 generated C++/header 与 unpatched control
相同，候选会在 runtime 前被拒绝。

`explicit-options` 保留并明确了三重归因：

1. unpatched repository 使用同一组 options 做 emit，得到 same-options reference；
2. patched repository 使用 `options={}` 构建，必须与 current-default control 的 generated
   fingerprint 相同，证明 patch 没有暗改默认路径；
3. patched repository 显式启用 options 后，必须同时区别于 control 和 unpatched same-options
   reference，证明 executable effect 来自 patch 与 option 的组合，而不是已有 knob 或空 patch。

## 3. exact-event 与 gap-pack 的 option 边界

v2 allowlist 新增 `commit_exact_event_policy`，供后续 `explicit-options` candidate 独立控制
exact-event 机制。`active_mask_gap_pack_policy=targeted-direct` 只控制 non-table direct
active-mask gap packing；它不控制、不选择、也不作为 gen24 exact-event closure 的通用开关。

因此候选必须按实际依赖选择 mode：

- 改进已经由 C++ 默认选中的 exact-event 路径时使用 `default-path`，不借用
  `targeted-direct`；
- 研究尚未默认启用的 exact-event 或 gap-pack option 时使用 `explicit-options`，分别显式列出
  自己及真正依赖的 option；
- 两项默认来源和正式 walltime 裁决仍遵守
  [TNO0176](./TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md)
  的独立策略边界。

## 4. candidate proof、control identity 与 runtime-only retry

contract v2 把 `candidate_mode` 纳入 candidate canonical digest、candidate proof、runtime config、
runtime result、evaluation result 和 immutable attempt completion。runtime-only retry 会逐项核对 mode，
不允许用同一 patch/options 文本在 `default-path` 与 `explicit-options` 之间重解释历史 proof。

非 control candidate 的 proof 绑定：

- candidate digest、mode、patch SHA-256 和 canonical options；
- parent/wolvrix pins；
- candidate generated、build-config、toolchain fingerprint；
- candidate binary、image、NEMU 的精确路径和完整 SHA-256；
- candidate/control `env.sh` 路径和 SHA-256；
- control 的完整 generated、build-config、toolchain fingerprint，以及 binary、image、NEMU 的完整
  SHA-256。

完整 evaluator 在 candidate build 前先把 control artifact 与 `env.sh` SHA-256 保存在内存中；在写
proof 和进入 runtime 前重新验证 control marker、pins、generated/build/toolchain 与当前文件，并要求
candidate image/NEMU 与 control 相同。这样 candidate 即使同时改写 control 文件和 marker，也不能
用一个自洽但不同的 control incarnation 通过 gate。

runtime-only retry 不 clone、不 emit、不 build，也不在 cache 无效时回退到重建。它重新验证当前
control marker/files、candidate proof、patch、mode、options、环境、candidate artifacts，以及与 proof
SHA-256 绑定的最新完整 retryable immutable attempt。回归已覆盖 proof/attempt 字段篡改、candidate
artifact 漂移，以及 control binary 与 control marker SHA 同时协调更新的情况；这些情况都在运行
50k 前被拒绝。

## 5. launcher continuation 与 TOCTOU 防护

launcher 在启动 SimpleTES 前加载当前 evaluator contract，并验证 initial seed 或 resume checkpoint：

- schema v1 seed/resume 被明确拒绝；
- checkpoint 的 `best_program.*` 必须能由 v2 parser 解析，并在 sibling `nodes.json` 中找到完全相同
  digest 的 node；
- best node 和 checkpoint 中可识别 node 的 parent/wolvrix pin provenance 必须全部等于当前
  evaluator pins，任何 v1 或 pin mismatch 都不能继续；
- symlink seed、symlink checkpoint state 和不唯一的 `best_program.*` 被拒绝。

对 `--resume INSTANCE_OR_STATE`，launcher 只选择一次精确 `db_state_*`，验证该 state 及其中精确的
`best_program.*` 后，把这两个已验证的绝对路径传给 SimpleTES。它不再把 instance directory 交给
main 重新选择一次“latest”，因此验证完成后即使并发出现一个更新的 state，也不能绕过 schema/pin
检查。resume 时无需重复提供 `--init-program`；main 使用的是该 exact state 的 validated best seed。

已经耗尽 proposal budget 的 continuation 仍应以 prior v2 `best_program.*` 启动一个 fresh instance，
而不是修改旧 checkpoint 的 chain budget。只有 schema v2 且 pin provenance 等于最终 bench pins 的
checkpoint 才可直接 resume；历史 v1 checkpoint 不被静默迁移或重新解释。

## 6. 已完成验证

本轮在未启动真实 evaluator/runtime/research 的条件下完成以下绝对结果：

| gate | 绝对结果 |
| --- | ---: |
| SimpleTES 全量 pytest | `138/138 PASS` |
| GrhSIM bench focused pytest | `66/66 PASS` |
| init control `--validate-only` | `PASS`，`candidate_mode=control`、空 files/options |
| launcher `--dry-run` | `PASS`，只生成命令，不调用模型 |
| Python syntax compilation | `PASS` |
| `git diff --check` | `PASS` |

全量 pytest 另有 `17` 条既有 `datetime.utcnow()` deprecation warning，没有 test failure。focused
覆盖 model-output schema 拒绝 control、parser 接受 init control、两类非 control mode shape、
default-path native build、explicit-options 三重归因、proof/control identity、runtime-only retry、
schema/pin mismatch，以及验证后新 state 出现时仍固定使用原 state/seed 的 TOCTOU 回归。

## 7. 最终 continuation readiness：PENDING

以下结果在本文成文时尚不存在，不能记为 PASS：

1. 提交最终 wolvrix 实现，并在 parent commit 中固定该 submodule pointer；
2. 把 `evaluator.py`、bench README/instruction 和 init seed provenance 更新到最终 parent/wolvrix SHA；
3. pins 更新后重新运行 v2 全量/bench/validate-only/dry-run gate；
4. 使用 direct evaluator 对 schema-v2 control seed 执行一次真实 native-control canary，验证 native
   `options={}` build、focused 与 fixed-ASLR 100/10k gate、quiet whole-CCD 50k ABBA、绝对
   `Host time spent`、`personality=00040000`，以及 control artifact marker/immutable attempt；
5. 按 append-only 规则在后续 TNO 中记录最终 SHA、canary 绝对数据和产物身份，然后才允许启动新的
   auto research continuation。

真实 native-control canary 必须直接调用 dataset evaluator，不能通过 launcher/main 进入 LLM 路径。
evaluator CLI 的 shell exit code 不能单独代表评估有效；必须检查结果 JSON 中的
`valid_candidate=1`、`validity=1.0`、`infrastructure_retry=0`、正的 control/candidate absolute
walltime、固定 ABBA sample 顺序、整 CCD gates 和 ASLR audit。control 与自身的配对 walltime 比值
只反映样本噪声，不要求精确等于 `1.0`，也不参与新的默认性能裁决。

截至本文为止，没有启动新的 SimpleTES 实例，没有进行 API/model 调用，也没有把任何 pending pin、
canary 或 continuation 结果写成已经完成。
