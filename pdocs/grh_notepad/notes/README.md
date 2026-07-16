# 正文编号树

`notes/` 保存全部记录的唯一规范正文。目录由 `NOxxxxx` 自动决定，规则见上级 [RULES.md](../RULES.md#2-编号文件名与编号树)。

新正文不直接放在本目录，而是放在：

```text
notes/<NN>/<range>/NOxxxxx_slug_YYYYMMDD.md
```

例如 `NO01234_node_origin_map_20260713.md` 的路径是：

```text
notes/01/200-299/NO01234_node_origin_map_20260713.md
```

`NN` 与 `range` 目录按需创建。不要按主题、日期或状态移动已归档正文。
