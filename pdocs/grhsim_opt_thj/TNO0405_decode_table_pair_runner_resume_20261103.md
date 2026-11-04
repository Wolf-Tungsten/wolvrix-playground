# TNO0405：配对脚本错误修正与验证复用续测

日期：2026-11-03。

`comparison-v1` 已通过两次 smoke、两组 C100000 DiffTest 逐条验证和预热。
正式配对在 A/pair00 结束后因 Python `KeyError: 'A'` 中断。原因是新增的编译
DiffTest 签名检查位于单次运行循环内，尝试从单次 `row` 中读取 `row['A']` 和
`row['B']`。修正为收集完整 pair 后检查 `pair['A']`／`pair['B']`。

此错误没有修改 binary，也不是功能或 NUMA 错误。未完成的 A/pair00（99.075 s）
及完整日志保留在 v1，不能将其当成完整配对；不按其速度决定是否保留。
修正后的原有 8 项脚本测试通过，正式测量使用新目录 `comparison-v2` 重新开始 8 对。

新增 `--verification-from`，允许复用已完成的功能轨迹；必须核对 A/B binary、
负载、NEMU、DiffTest schema、运行模式、周期数和运行依赖库身份完全一致。
复用时还会重新逐条比较两个种子的现存 trace chunks，写入新目录的比较结果，
不重新执行已经通过的四次诊断 emu。v2 已完成这些检查。文件副本、NUMA 预取、
smoke 和预热则重新进行。

本次命令：

```bash
python3 scripts/grhsim_decode_table_study.py measure \
  --output build/xs/decode_table_20261103_v3 \
  --comparison comparison-v2 \
  --verification-from build/xs/decode_table_20261103_v3/comparison-v1
```

局部基准仍等待整机测量结束再开始。局部循环次数按预先校准的各版本速度，
选择约 150 ms 的整数个输入序列周期；A/B 使用完全相同的输入周期和分布，
报告每次操作 ns，循环次数分别保存。这样可观察进程的 NUMA 页面，同时避免
极慢的门级展开实现被强制运行与软件实现相同的大量重复次数。整机计时依然
固定每次 C100000，没有改变测量周期或样本数。

证据：`whole-measure-v3.log`、`whole-measure-v4.log`、`compare-script-fix-tests.log`，
均在 `wolvrix/build/artifacts/decode-table-study`；v2 的 `reused_runtime_identity_check.json`
确认两侧各 9 个运行时文件与 v1 身份相同。先前因依赖整机结果未生成而退出的局部
队列也保留日志，没有执行任何局部计时。

前序：[TNO0404 构建与两组整机等价检查](./TNO0404_decode_table_native_build_and_equivalence_20261103.md)。
