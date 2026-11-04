# F16：node attribute 关闭实验

日期：2026-11-03。按用户要求只跑一轮关闭组，复用已有 F16 开启组三轮中位数。
新开启组已中止，其不完整结果不参与比较；没有继续重复整机实验。

## 对照结果

| 指标 | 开启：旧三轮中位数 | 关闭：本次单轮 | 降幅 |
| --- | ---: | ---: | ---: |
| ingest 墙钟 | 136.207 s | 113.013 s | 17.0% |
| 八个前置 pass 墙钟 | 49.775 s | 23.957 s | 51.9% |
| hier-flatten 墙钟 | 122.404 s | 68.411 s | 44.1% |
| 连续前缀墙钟 | **308.525 s** | **205.778 s** | **33.3%** |
| 阶段合计 CPU | 440.813 s | 311.257 s | 29.4% |
| 全前缀峰值 RSS | 116,848,980 KiB（111.44 GiB） | 96,463,552 KiB（91.99 GiB） | 17.4% |

各阶段的旧中位数独立计算，不能直接相加重建旧连续墙钟中位数。
开启/关闭速度比为 1.499×。关闭后相对 F14 的 76.491 s 仍为 **2.690×**；
node 标注有明显代价，但不能解释全部差距。

## 实验控制与验证

- 两组使用同一个冻结 F16 final 二进制、相同输入、10 个 lowering worker、
  CPU 0–31、mimalloc 默认间隔 1,000,000、完整八个前置 pass 和 flatten。
  不启用 perf、时间戳插桩或大图保存。
- 唯一请求差异为 `firrtl_options.node_annotations: true → false`。
  现有开关从 lowerer 源头停止 node key、operation attributes 和对应元数据的生成，
  无需另编临时 native。外部 FIRRTL annotations、DontTouch、SrcLoc、
  originModules 和功能属性保留。
- 小层次 fixture 的关闭组在 ingest/flatten 均为零 node 字段；开启组分别为
  13/10 个字段。只剥离 node 字段及空属性容器后，两个终点的完整小图相等，
  按序诊断相同。
- 大图比较检查通过：实际库 SHA、manifest 的唯一差异、allocator、affinity、
  输入大小、dependencies、各阶段按序诊断和非 node metadata **key 集合**。
  输入源 SHA 在运行前后相同。`controlled_comparison_passed=true`。
- 关闭组仍执行 `node::requireValid` 等扫描。本次没有关闭全部 node 检查，
  没有证明整机剥离后的图等价，也没有测后端分图或仿真速度。

实际核心库 SHA-256：
`fa8add5b4551148a8e7cf9331daf2122f8a123d447a26729442227fb692b7064`。
binding SHA-256：
`0ebe861759a32e9b94137fac7c2f326fae3e98a1dd9bf156a6da9468fb5ca0b3`。
输入 FIRRTL SHA-256：
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。

## 证据与复现

实验目录为 `ptmp/firrtl-ingest/F16/node-attribute-ablation/`：
[comparison.json](../../ptmp/firrtl-ingest/F16/node-attribute-ablation/comparison.json)、
[controls.json](../../ptmp/firrtl-ingest/F16/node-attribute-ablation/controls.json)、
[小图验证](../../ptmp/firrtl-ingest/F16/node-attribute-ablation/small-verification.json)、
[关闭组 timing](../../ptmp/firrtl-ingest/F16/node-attribute-ablation/off-1/timing.json)。
旧开启组见 [summary-final.json](../../ptmp/firrtl-ingest/F16/summary-final.json)。

```sh
make --no-print-directory -f ptmp/firrtl-ingest/F16/node-attribute-ablation/Makefile verify-small
make --no-print-directory -f ptmp/firrtl-ingest/F16/node-attribute-ablation/Makefile off-1
make --no-print-directory -f ptmp/firrtl-ingest/F16/node-attribute-ablation/Makefile summarize
```

以上命令用于复现；现有单轮已经完成，不需要再次运行。
