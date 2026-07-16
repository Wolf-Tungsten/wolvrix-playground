# GRH 主题导航树

`tree/` 提供面向领域的树状导航，所有条目都必须链接到 `../notes/` 中唯一的正文副本。具体层级和叶索引规则见 [RULES.md](../RULES.md#5-主题导航树)。

首次出现一个稳定一级领域时，在此处追加其目录链接；随后在该领域下按 `topic` 创建二级节点，并使用与正文相同的 `NN/range` 分片。

示例路径：

```text
tree/grh-model/node-origin/01/200-299.md
```

示例叶索引行：

```markdown
| `NO01234` | 2026-07-13 | [Node origin map](../../../../notes/01/200-299/NO01234_node_origin_map_20260713.md) | active |
```

这里不建立全量索引，也不复制记录正文。

- [simulation](./simulation/README.md)
