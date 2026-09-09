# SimpleTES B native baseline handoff

## 已完成的基线交接

接续 [TNO0296](./TNO0296_simpletes_b_native_landing_20260909.md)，
SimpleTES 已提交 `45d0c7a3a2a48ab196c66417e011e0b5ac30ffdf`。
evaluator、空 control seed、README、research instruction 与 bench 测试
同步到实际已存在的 pin：

- parent：`fd54f8deab18d861cd29fa4c3852f1013c3948f1`；
- Wolvrix：`94109bc68e0f0ea76d6083b3c193750be9a7bfae`；
- native emitter SHA-256：`4d1aaff4b647ed3e064335d80762253666572fef2e0c1bebc574c1035768d051`。

parent 的 gitlink 已实际核对等于上述 Wolvrix commit。此 pin 是可执行源码
快照；后续只追加实验文档的 parent commit 不需要再次改变研究 pin。
新命名空间为 post-hot-dispatch-B，明确区分本次 hot-input branch weighting
与早先 typed-state 消融中的同名 B。新 control 使用空 patch、空 option，
B 已在通用 emitter 内默认开启，A/C 没有纳入。

下一轮应新建 checkpoint，由新的 pin pair 建立 control 和 evaluator slot；
原 post-g158 `6e2436e`/`054c6a7` checkpoint 保留历史数据，不能把它的 control
二进制或分数重新解释为新 baseline，也不能直接作为新 pin 的 seed/resume。
已有 pin 校验和缓存隔离机制保持生效，没有修改 runtime 测量协议。

## 离线回归结果

`tests/test_grhsim_bench.py` 与 `tests/test_grhsim_runtime.py` 合计
`161 passed in 8.72s`。包括新旧 pin 的 seed/resume 拒绝测试。
指定 `gpt-5.6-sol`、reasoning effort `max`、thj config/auth 的 launcher
`--dry-run` 通过；没有调用模型 API 或创建新 checkpoint。

空 control `--validate-only` 返回 `valid: true`，candidate digest 为
`98d351d74266c705b0c887d47610f7405ebfa5fdc641583780cac06f6f6a88ba`。
此外实际核对了 source SHA、parent gitlink、新 slot 身份和隔离索引中的
emit include smoke patch 可应用性；没有修改研究源码或历史 checkpoint。
上述检查输出位于本次工具执行记录，未声称存在单独的机器报告文件。

最初额外审计曾错误要求整个新 Wolvrix tree 相对历史 `054c6a7` 只改变两个
文件，因期间已有 RepCut 更新而失败。已将审计范围更正为实际 B commit
`94109bc` 相对其父 `6a895c9`，确认仅 emitter 和对应测试两个文件改变。
性能复测的 base 同样固定当前 pre-B `6a895c9`，不使用旧研究 tree 代替。

本阶段没有启动下一轮 auto research。SimTop fresh build 和性能结果另行归档。

## 说明措辞校正与最终任务提交

复核时发现 SimpleTES 说明将 `clearMask == dispatchMask` 简写成 batch 条件，
现已明确为“non-fullpass compute batch 内逐 dispatch word 比较 clear mask
与 dispatch mask”。这是 README/instruction/seed evidence 的措辞校正，
pin、优化代码、候选选项、runtime 和已有测试行为均不改变。

该校正合并进本次尚未发布的 SimpleTES 任务提交，最终 commit 为
`4ca31aa48497dd17afa1c6626e21d806dcd92d86`，替代上文阶段记录中的
`45d0c7a`。重新执行空 control validate-only 仍有效；因 evidence 文本改变，
最终 candidate digest 为
`a8b734f3e8acef1ecaddebdd14e35aa65e1864be5d045e0a6b3c25a1ce72f6ab`。
工作树与 diff 检查均通过；没有重复运行不受措辞影响的 161 项测试。
