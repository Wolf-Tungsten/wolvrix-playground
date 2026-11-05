# F19：自包含 SemanticTree 与 JSON 导入导出

日期：2026-11-05。状态：功能、正式性能与体积实验完成，生产默认采用精简导出。

## 1. 目标与既定决策

F18 的 SemanticTree 只在内存中工作，StoreJson/LoadJson 不保存它。F19 同时解决持久化和
当前共享定义树带来的嵌套、复制及序列化复杂度。

已经确定的方案：

1. **每个 Graph 拥有一棵自包含 SemanticTree。** 不引用其他 Graph 或其他 SemanticTree，
   源 Graph 删除、clone、二次 flatten 和 JSON roundtrip 都不涉及外部树生命周期。
2. **名称存入字符数组。** 节点只保存整数偏移和长度，不在每个节点内保存 `std::string`；
   节点数组和名称字节区都可以大块复制。
3. **flatten 深拷贝，不共享定义树。** 来源树的完整节点区间复制到目标树，节点关系按新基址修正，
   不再逐节点分配字符串或连接 `shared_ptr`。
4. **SemanticId 只是当前树内的本地节点编号。** 删除高 32 位实例、低 32 位定义节点的组合，
   删除 `semanticScope/qualifiedSemantic/semanticInstance/semanticLocalId`。复制后统一重新编号。
5. **删除 Instance 节点。** SemanticNodeKind 只保留 Module、Declaration、Expression、Field、Element。
   源 Module 根节点作为普通子树复制，因此来源路径表达 `Top/Child/n.bits` 这样的定义来源；
   实例名由电路层次和 flatten 后 symbol 表达，不在 SemanticTree 中重复保存。
6. **统一 GRH JSON 直接替换为 v4。** writer 只写 v4，loader 只接受 v4；v2、v3、无版本输入
   一律拒绝，不做迁移、双格式输出、旧属性回填或兼容开关。

F19 不改变电路 lowering 和优化语义。它只改变来源树的物理表示、flatten 的来源复制方式及
checkpoint 格式。

## 2. 内存结构

目标结构：

```cpp
using SemanticId = uint32_t;

struct SemanticNode {
    SemanticId parent;
    SemanticNodeKind kind;
    uint32_t nameOffset;
    uint32_t nameSize;
    int64_t index;
};

class SemanticTree {
    std::string sourceUnit_;
    std::string circuit_;
    std::vector<SemanticNode> nodes_;
    std::vector<char> names_;
};
```

约定：

- `nodes_[0]` 不使用，根节点固定为 1；本地 ID 就是 vector 下标。
- 父节点先于子节点出现，`parent < child`，复制时可按数组顺序重建。
- `nameOffset/nameSize` 指向本树 `names_`，名称不需要 NUL 结尾，通过 `string_view` 读取。
- Element 的 `index >= 0` 且允许空名称；其他节点名称非空，索引缺省为 -1。
- Module 可以出现在非根位置：flatten 复制源树时，源 Module 根成为目标 Module 根的子节点。
- Tree 默认拷贝构造就是深拷贝；Graph 用值语义持有树，不再通过 `shared_ptr` 共享定义。
- value/op 继续使用统一 SemanticId 整数数组加行内 Range，但数组里的 ID 全部是本地节点编号。

## 3. flatten 批量复制与重新编号

设目标树已有 `N` 个节点，源树根 ID 为 1。将源树的 `nodes_[1..]` 追加到目标树后：

```text
newSourceRoot = N + 1
newId(sourceId) = newSourceRoot + sourceId - 1
```

复制步骤：

1. 目标节点数组和名称字符数组按需扩容，使用几何增长；容量不足时取“当前容量 1.5 倍”和
   “本次所需容量”的较大值。禁止每次精确 reserve 到本次所需容量，否则连续 append 会反复搬迁整棵树。
2. 整段追加源节点和源名称字节，不逐个构造字符串。
3. 源根节点的 parent 改为调用方给定的目标父节点；其余 parent 按新基址平移。
4. 所有 nameOffset 按目标名称区基址平移。
5. value/op 的 SemanticId 按 `newSourceRoot + sourceId - 1` 批量改写；保持原列表顺序，
   按现有合并规则去重，不引入 scope 或实例映射表。
6. 递归 flatten 时，把复制后的源 Module 根作为下一层复制的父节点。源树若已包含以前复制的
   子树，也只是一次更大的本地数组复制，不发生高低位组合。

该方案的主要成本是复制总量，不是指针处理。实现必须避免逐字符串分配，并记录真实节点数、
名称字节数、复制耗时和峰值 RSS。不能用“bulk”名义掩盖无界的数据膨胀。

## 4. v4 JSON 格式

### 4.1 顶层与 Graph

```json
{
  "formatVersion": 4,
  "graphs": [],
  "aliases": {},
  "declaredSymbols": [],
  "tops": []
}
```

版本位于 Design 根节点。Graph 不再携带 `formatVersion`，`dialects` 仍独立描述操作方言。

有来源信息的 Graph 包含一棵完整 `"semanticTree"` 对象；没有来源信息的普通 GRH/SV 图省略该字段，
不写 null，也不允许非空 SemanticId 列表。

### 4.2 树对象

```json
{
  "sourceUnit": "unit",
  "circuit": "circuit",
  "nodes": [
    {"parent": 0, "kind": "module", "name": "Top"},
    {"parent": 1, "kind": "module", "name": "Child"},
    {"parent": 2, "kind": "declaration", "name": "n"},
    {"parent": 3, "kind": "field", "name": "bits"},
    {"parent": 4, "kind": "element", "name": "", "index": 0}
  ]
}
```

- 节点 ID 为数组下标加 1，不写冗余 ID。
- 根必须是 parent=0 的 Module；其他 parent 必须指向当前树中更早的节点。
- kind 只接受 `module/declaration/expression/field/element`。
- 名称直接写文本；加载时一次性加入该 Graph 自己的字符区，不需要全局字符串表。
- 不保存 nameOffset、nameSize、Range、vector 容量或其他物理布局细节。

### 4.3 value/op 来源列表

非空时写正整数数组：

```json
"semanticIds": [7, 9, 9]
```

列表顺序、数量和重复项原样恢复。确定性来自 Graph 和节点的固定遍历顺序，不能通过排序来源
列表或诊断获得。所有 ID 必须存在于该 Graph 的 SemanticTree 中。

value/op/ports/def/users 仍使用当前 Graph 内的正整数结构 ID，但 v4 只保留这一种解析路径；
旧字符串引用、tmp 标记、旧临时名和旧属性键别名全部删除。

### 4.4 最小示例

```json
{
  "formatVersion": 4,
  "graphs": [{
    "symbol": "Top",
    "semanticTree": {
      "sourceUnit": "unit",
      "circuit": "circuit",
      "nodes": [
        {"parent": 0, "kind": "module", "name": "Top"},
        {"parent": 1, "kind": "module", "name": "Child"},
        {"parent": 2, "kind": "declaration", "name": "n"}
      ]
    },
    "dialects": {"grh": 2},
    "metadata": {},
    "declaredSymbols": [],
    "vals": [{
      "id": 1, "w": 8, "sgn": false, "type": "logic", "domain": "4state",
      "in": false, "out": false, "inout": false,
      "semanticIds": [3]
    }],
    "ports": {"in": [], "out": [], "inout": []},
    "ops": []
  }],
  "aliases": {},
  "declaredSymbols": [],
  "tops": ["Top"]
}
```

## 5. 实施分解

### F19.1 SemanticTree 物理表示与复制

涉及 `semantic_tree.hpp/.cpp`、`grh.hpp/.cpp`、`hier_flatten.cpp` 及核心测试。

- 名称迁入字符数组，SemanticId 改为 uint32_t，删除 Instance 和 scope 组合 API。
- Graph 改为值语义持有 SemanticTree；clone 使用整树深拷贝。
- 实现整树区间追加和本地 ID 平移；inline 与 block 两条 flatten 路径共用同一映射规则。
- 增加三层嵌套、已 flatten 树再次复制、两个相同模块实例、源 Graph 删除后的路径和关联测试。

### F19.2 单一 v4 writer/loader

涉及 `store.cpp`、`load.cpp`、`grh.cpp` 及 JSON 规范。

- 三种排版 writer 都输出根版本 4、Graph 内嵌树和扁平 semanticIds。
- loader 先创建 Graph 根树，再按节点数组顺序追加子树，最后创建 value/op 并恢复来源列表。
- 文本 DOM 和文件懒数组入口共用同一校验与构建逻辑，保留流式文件写出。
- 删除 v2/v3/无版本解析、字符串实体引用、tmp 和兼容属性键；旧输入明确报错。

### F19.3 功能与异常验收

新增 `store-semantic-tree-json` 测试和根 `test_f19_semantic_json` Make 目标，并迁移现有 JSON fixture。

必须覆盖：

- 无树图、六种历史节点形态缩减后的五类节点、字段与数组元素；
- 两个相同模块实例的独立深拷贝、三层嵌套、已 flatten 树再次复制；
- value/op 多来源、顺序和重复项；
- 源 Graph 删除、clone、compact；
- 三种 print mode、文本/文件 loader、Python 公开 API；
- ingest 和生产 hier-flatten 两个终点的 store→load→store；
- 无效父节点、未知 kind、非法下标、重复/悬空/越界 ID、无树非空来源及旧版本拒绝。

诊断只检查内容和严重级别，不比较顺序，不为保序排序或归一化。

### F19.4 真实设计与性能

复用 F18 冻结输入、native 快照、formal CPU 和 `benchmark_xs_firrtl_ingest.py` /
`verify_grh_json_roundtrip.py`。

- 测量 ingest→hier-flatten，和 F18 formal 的 70.64 s、flatten 19.60 s、约 42.3 GiB 对比，
  判断自包含深拷贝的总成本是否可接受；不能把布局优化当成复制量减少。
- 分别保存 ingest 和 flatten 的 v4 checkpoint，删除内存 Design，通过公开 API 读回并再次导出。
- 比较完整文件字节数和 SHA-256，并记录树节点数、名称字节数、非空来源行数和 SemanticId 总数，
  防止空来源造成假通过。
- 记录 store/load/store 墙钟、文件大小和峰值 RSS；大型产物只放在 `ptmp/firrtl-ingest/F19/`。

## 6. 实施结果

### 6.1 复制问题与修复

首版自包含深拷贝在 `F19/prefix-run1` 的 flatten 为 204.039 s。带分解计时的 `F19/prefix-profile`
显示：复制 12,913,430 个节点和 154,978,239 字节名称，`appendTree` 耗时 174.601 s；原因是每次追加都精确
reserve 到本次长度，连续复制反复搬迁已有节点。改为几何增长后的 `F19/prefix-growth` 中，相同节点和名称
数量的复制耗时降至 **0.135 s**，flatten 为 19.378 s，总墙钟为 71.503 s。

### 6.2 正式性能

`F19/final` 使用无采样、fused prefix、CPU 0–31 和三轮重复。allocator、native 库、prefix 实现及重复配置/
诊断检查全部为 true。中位数与 F18 formal 对比如下：

| 指标 | F18 formal | F19 formal | 变化 |
| --- | ---: | ---: | ---: |
| 连续墙钟 | 70.64 s | **70.281 s** | 基本持平 |
| hier-flatten | 19.60 s | **19.522 s** | 基本持平 |
| ingest + 前置 | 51.03 s | **50.921 s** | 基本持平 |
| prefix CPU | 239.65 s | **235.699 s** | 约 -1.6% |
| 峰值 RSS 中位数 | 约 42.3 GiB | **约 41.1 GiB** | 未增加 |

三轮连续墙钟为 69.324/70.281/72.238 s，flatten 为 19.522/19.265/20.795 s。F19 的目标是深拷贝结构和
JSON 补缺，不把小幅波动宣称为额外性能收益；正式结果达到 F18 的 ≤75 s 水平。

### 6.3 正确性

- `make test_f19_semantic_json`：6/6 CTest 通过，含三种排版、文本/文件 loader、真实 FIRRTL ingest/flatten
  往返、旧格式与非法树拒绝；语义统计为 1 树、11 节点、29 名称字节、5 个 SemanticId。
- `make test_f19_semantic_json_asan`：3/3 通过，包括几何增长修复后的复验。
- `make test_f19_python_json`：`read_json_file`、`load_json_text` 和二次 `store_json` 均通过，
  字节数/SHA-256 和语义统计一致。
- `make test_wolvrix`：77/84；其余七项为 F18 已排除的旧 node/origin 表示测试，没有新增失败。
- `make test_xs_firrtl_workflow SKIP_PY_INSTALL=1`：66/72；两项旧 node 断言及四项中文 locale
  错误文本断言与 F18 记录相同，没有新增失败。
- flatten 原文件与 roundtrip 已确认 SHA-256 一致（24,002,309,679 字节）；ingest 全量往返及 native
  统计复核尚未完成，已暂停。

### 6.4 def/users 与 loc 体积实验

`F19/size-experiment/summary.json` 记录同一 flatten Graph 的三组实际导出结果，基线为完整 v4 文件
24,002,309,679 字节：

| 变体 | 字节数 | 相对基线 | 节省字节 | 节省比例 |
| --- | ---: | ---: | ---: | ---: |
| 仅移除 `def/users` | 22,376,739,601 | 93.23% | 1,625,570,078 | **6.77%** |
| 仅移除 `loc` | 9,897,441,765 | 41.24% | 14,104,867,914 | **58.76%** |
| 同时移除 | 8,271,871,687 | 34.46% | 15,730,437,992 | **65.54%** |

最精简版本已重新加载，SemanticTree 统计与原文件一致：1 棵树、12,940,224 个节点、155,418,188
名称字节、6,056,621 个 value 来源行、17,040,867 个 op 来源行、23,745,580 个 SemanticId。
原始/精简加载时间分别为 408.02 s 和 174.97 s。小文件三种排版和 Python 变体往返均通过。
生产默认导出已确定为 `emitDefUsers=false`、`emitSourceLocations=false`，Python 对应参数也默认关闭。
调试时仍可显式开启完整字段；省略字段不改变内存中的 SrcLoc 或 SemanticTree，加载后由 operation 边重建拓扑。

## 7. 退出条件

1. Instance、scope 组合和共享定义树完全移除，所有 SemanticId 都是当前树本地编号。
2. v4 是唯一 JSON 路径，旧输入明确拒绝，规范与实现一致。
3. 功能矩阵通过，尤其是多层/二次 flatten、多来源和三种排版两种加载入口。
4. F19 相关 ASAN 用例通过，无悬空名称、越界复制或加载后失效关联。
5. 真实 FIRRTL 两个 checkpoint 的来源计数非零且完整 roundtrip 一致。
6. 给出真实深拷贝性能和 RSS；若完整复制不可接受，必须如实保留未达标结论，再决定是否裁剪
   无引用来源分支，不能擅自缩小语义或宣称完成。

建议验证入口：

```bash
make test_f19_semantic_json
make test_f19_semantic_json_asan
make test_grh_semantic_tree
make test_firrtl_semantic_tree
make test_wolvrix
make test_f19_python_json F19_ROUNDTRIP_NATIVE_DIR=/path/to/v4-native
make verify_f19_semantic_json_roundtrip \
  F19_ROUNDTRIP_INPUT=/path/to/v4-flatten.json \
  F19_ROUNDTRIP_NATIVE_DIR=/path/to/v4-native
git diff --check
```

新工作流必须先加入已有 Makefile 再调用。F18 已确认的旧 node/origin 表示相关失败单独记录，
不借 F19 恢复旧表示，也不把新增失败混入既有排除项。
