# grh_notepad 文档索引

`grh_notepad` 用于长期保存 GRH 相关的方案、实验、诊断、决策与验证记录。
它沿用 `pdocs/grhsim_opt` 的 `NO` 稳定编号和增量归档原则，但为约 5 万篇文档采用分片的编号树与主题导航树，避免单目录和单个全局索引持续膨胀。

完整的强制性规则见 [RULES.md](./RULES.md)，新记录从 [模板](./templates/NOTE_TEMPLATE.md) 创建。

## 目录结构

```text
pdocs/grh_notepad/
├── README.md                         # 本入口，不罗列全部文档
├── RULES.md                          # 强制管理规则
├── templates/
│   └── NOTE_TEMPLATE.md               # 新记录模板
├── notes/                             # 唯一的正文规范副本
│   └── 00/000-099/
│       └── NO00001_example_YYYYMMDD.md
└── tree/                              # 主题导航树，只存相对链接
    └── <area>/<topic>/<NN>/<range>.md
```

`notes/` 的路径由编号唯一决定：`NO01234` 位于
`notes/01/200-299/`。每个叶目录最多容纳 100 篇正文；预计 5 万篇记录会分散到约 500 个叶目录中。

`tree/` 是人工可读的主题检索树。一个主题叶索引最多列出同一编号分片中的 100 个链接，例如：
`tree/grh-model/node-origin/01/200-299.md`。它指向 `notes/` 中的正文，不复制正文。

## 日常新增流程

1. 在最新目标分支上确定下一个未占用的五位 `NO` 编号。
2. 按编号规则在 `notes/<NN>/<range>/` 新建正文，并填写 YAML 元数据。
3. 按 `area/topic` 将相对链接追加到对应的 `tree/` 叶索引；缺少的树节点按规则创建。
4. 提交时只包含本记录、必要的主题叶索引和首次出现时的父节点索引；不要重排或重写无关索引。

常用检索方式：

```bash
# 已知编号：先定位稳定正文路径
rg --files pdocs/grh_notepad/notes | rg 'NO01234_'

# 已知主题：沿主题树浏览或筛选
rg --files pdocs/grh_notepad/tree/grh-model/node-origin

# 已知术语：搜索正文和元数据
rg -n -i 'origin map' pdocs/grh_notepad/notes
```

不要在本 README 中维护全量文档表，也不要为同一记录创建第二份 Markdown 正文。
