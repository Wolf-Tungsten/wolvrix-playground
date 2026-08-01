# TNO0215：原则化 hot-event SimpleTES repin 与 continuation readiness

日期：2026-08-01

## 1. 结论

[TNO0214](./TNO0214_principled_hot_event_landing_and_native_gate_20260801.md) 已将原则化 `TRBS` 作为
Wolvrix 通用默认落地。本阶段把 SimpleTES 的 SimTop 50k bench 从 four-positive 基线迁移到该 executable
snapshot，并完成只验证、不启动 research 的连续性闭环。

新身份为：

| 对象 | commit |
| --- | --- |
| parent executable snapshot | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| Wolvrix native default | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| SimpleTES bench repin | `6a169d4958066c4932240aba5cbe5729d794ad74` |

parent tree 的 `wolvrix` gitlink 已直接核验为 `d3ed9dea...`。新的空 control、evaluator、instruction、README
与 checkpoint pin 验证均使用这一对完整 SHA；旧 `de37459/fd12d83` checkpoint 不能 resume 或直接作为
`best_program.txt` seed。

本阶段没有启动新的 SimpleTES instance，没有调用模型，也没有新增 50k 样本。后续可以从新的空 control
发起 fresh research；若需要沿用旧搜索方向，应先把旧 best patch 重新整理为相对 `d3ed9dea...` 的新候选并重新
评估，不能复用旧 checkpoint 状态。

## 2. 新 native control 的边界

新 instruction 和 init control 把下列内容定义为已落地、不可重复申领的 baseline：

1. R/W/A 与此前 four-positive 四项；
2. 原则化 hot-event 机制：按 final schedule 的 reusable exact-`posedge` demand 选择 input event，将其 remap
   到 typed slot 0，预解码 bool，并在覆盖 batch 内做 local snapshot；
3. residual negedge/general 查询继续保留 enum 路径；
4. 选择器只使用 reusable demand、固定 materialize/clear cost 和稳定结构 tie-break，不读取端口名、SimTop/
   benchmark 身份、ValueId 或 raw event-slot-count 阈值。

因此完整 `HS` 与 `TRBS` 被视为同一热点事件思路的两代实现，不能作为两个独立 feature 再次叠加。只有
`TRBS` 未覆盖的 residual 路径才可能构成新的 hybrid arm，并且仍须独立通过 SimTop 50k walltime 门禁。

candidate contract 保持 schema v2：新 proposal 必须是 `default-path` 或 `explicit-options`，patch 必须相对
`wolvrix@d3ed9dea975bddf01185dde5c548a69241a09de9`。空 patch/空 options 的 `control` 仍只允许作为 init seed。

## 3. 连续性验证

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| parent tree gitlink | `52ba7d9... -> wolvrix d3ed9dea...` | PASS |
| init program validate-only | `valid=true`，`files=0`，`options=0` | PASS |
| new empty-control digest | `2147a1179e1b655288a2368a95dd6fddc619cdd6feaab04179ddf7d4a6b21520` | PASS |
| focused GrhSIM bench pytest | `80/80`，`5.89 s` | PASS |
| SimpleTES full pytest | `251/251`，`11.13 s` | PASS |
| full pytest warnings | `24` 条既有 `datetime.utcnow()` deprecation warning | 无新增失败 |
| git diff --check | 无错误 | PASS |
| GPT launcher dry-run | `gpt-5.6-sol/max`、THJ config/auth、`4 gen/1 eval` 命令完整生成 | PASS |
| dry-run checkpoint path | 不存在 | PASS，未创建 instance |

第一次全量 pytest 调用从 workspace 根目录执行，因 `datasets` 不在 Python import root 而在 collection 阶段
报 `ModuleNotFoundError`；随后从 SimpleTES 仓库根目录按项目入口重跑得到上表 `251/251`。这属于测试启动目录
错误，不是产品或 bench 回归。

dry-run 使用 `~/.codex/config.thj.toml`、`~/.codex/auth.thj.json` 对应路径以及
`gpt-5.6-sol/max` 组装未来命令；它只做本地参数和 pin 检查，没有执行 preflight、API 请求、evaluator 或
research engine。生成命令保留 `source env.sh`、fixed evaluator/instruction/schema、四个 generation worker、
一个串行 evaluation worker与 capacity/transient continuation 设置。

## 4. 性能口径与继承结论

本次 repin 不产生新的性能比较，也不把测试耗时当作优化指标。native default 的正式性能依据仍是前两篇记录：

- [TNO0213](./TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md) 的 `B -> TRBS`：
  `51,562.00 -> 47,632.25 ms`，绝对减少 `3,929.75 ms`，提升 `7.621407%`；
- [TNO0214](./TNO0214_principled_hot_event_landing_and_native_gate_20260801.md) 的旧搜索门禁到原则化门禁：
  `47,567.25 -> 47,597.00 ms`，原则化版本慢 `29.75 ms / 0.062543%`，ABBA/BAAB gap
  `0.072499 pp`，generated fingerprint 相同，判为运行时噪声等价。

因此 SimpleTES 新 control 对应的实际默认结论仍为 KEEP：原则化 `TRBS` 在 Wolvrix C++/Python 通用流程中
默认启用，不由 SimTop wrapper 单独打开，也不借用 `targeted-direct`。

## 5. 继续探索规则

1. 新 research 必须 fresh 使用本次 checked-in 空 control，或者使用同一新 pin namespace 中已评估的
   `best_program.txt`；
2. `de37459/fd12d83`、`d31118b/16a9f49` 与 `fbe4e1c/8f6ba14` 的 checkpoint/resume/seed 全部 fail-closed；
3. 不得重复提出 R/W/A、four-positive、HS/TRBS 等已落地机制，也不得把 residual MemoryRead、physical
   zero-tail 或 MemoryFill F 当成已证明正收益；
4. 后续唯一 headline 仍是关闭 ASLR、whole-CCD quiet、同 CCD ABBA+BAAB 的 SimTop 50k `Host time spent`
   walltime；功能与 attribution gate 必须先通过。

## 6. 文件证据

| 对象 | SHA-256 |
| --- | --- |
| `datasets/grhsim/simtop_50k/evaluator.py` | `59bca6e3ff0921499b2df2bff337c273f5d2997bed2032f92deb2ed371eae160` |
| `datasets/grhsim/simtop_50k/init_program.txt` | `ae8fccc4e13152d328f0b4b90d2710d5ee545a7abebf853d56d3bb1f86d88ed1` |
| `datasets/grhsim/simtop_50k/instruction.txt` | `765b4d0c51efd670f4f798ecf3df913699f252f8105746325d4496454cf61ac7` |
| `datasets/grhsim/simtop_50k/README.md` | `a8eeb8284c528e8bafec73dfd11408cb5989fcad6c614a966812d87dcf9b2810` |
| `tests/test_grhsim_bench.py` | `47a4513599dac0d0a5cac1ac4c6dc994918950257047fb62b73a1490da4e5c7e` |

