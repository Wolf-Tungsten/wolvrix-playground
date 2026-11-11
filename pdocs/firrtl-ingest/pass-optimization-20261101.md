
用户要求保留完整优化与校验，FIRRTL 到 C++ 总时长最多 20 分钟，超时立即
SIGKILL。不再采用历史 full31–35 的 skip、单轮、bringup 配置作为达标方案。
F10 整机仍待验收。

## 实现

- flatten 复用每实例的 dense port/value map；只为不可变 frozen definition
  缓存引用符号集合。逐实例端口/类型/符号校验仍全部执行，builder fallback
  不变。SrcLoc、originModules 和端口符号读取减少拥有对象的中间复制。
- simplify 在完整前验确认 `stage=converted`、所有操作没有 partition 后，
  复用此不变量进行 scope membership 判断；仍检查非法/已删除 ID。其它
  stage 与调用者保持原路径，所有 rewrite、代表选择、迭代和前后验证不变。
- node key 的纯合法性检查改为无分配完整扫描，避免每次构造 Identity 后
  再序列化比较。合法语言与旧 `parseKey` 相同；扫描失败仍调用旧解析器，
  保留非法输入的异常类型、文本和优先级。排序/去重、合并次数、64 个
  association 上限、degraded 计数和所有 write 均不变。
- 第一批 simplify SmallVector/key-move 候选在四组实测中没有收益，已撤回。

## 验证和测量

全部通过 `Makefile` target 执行。`make test_wolvrix py_install` 的 81 项
native 回归通过。新增回归涵盖 frozen 首次修改、非法/删除 ID、partition
边界、24 层 frozen 定义嵌套复用及同 pass 修改源模块后再次运行；node key
使用未改动的旧 `parseKey` 作独立差分 oracle，覆盖全部 256 字节、转义、
非法格式、长 key/path、排序去重、异常优先级和无效写入的 DesignStamp。
`make test_grhsim_flow test_xs_firrtl_workflow test_firrtl_state test_firrtl_memory`
也已退出 0：flow 5 项和 workflow 57 项通过，生成模型、状态模型和内存
读写矩阵均实际编译执行。日志为 `pass-opt/logs/compiled-and-workflow.log`。

Make 入口：`benchmark_firrtl_passes`、`profile_firrtl_passes` 和
`compare_firrtl_pass_benchmarks`。benchmark 默认保留原生 simplify 全部默认
轮次，使用同一 source 路径，使 SrcLoc 也能逐字节比较。baseline/candidate
库均冻结在 `ptmp/firrtl-ingest/F10/pass-opt/`，通过 Python `-S` 避开 editable
import hook；每份 report 记录实际映射库路径与 SHA-256。profile 只在所选
pass 内启用采样，排除 store/Python JSON 解析。

四组逐阶段完整 JSON SHA、operation/value 数、diagnostics 及去除时间的
迭代日志全部相同，均为 3 轮收敛。下表是单次 fixture 测量，不是整机时长
或正式多次性能消融。完整报告为 `pass-opt/final-comparison.json`。

| fixture | flatten 前→后（秒） | simplify 前→后（秒） |
| --- | ---: | ---: |
| 32 instances × 1024 terms，注解 off | 0.507 → 0.455 | 1.546 → 1.551 |
| 同尺寸，注解 on | 1.417 → 1.148 | 27.240 → 10.141 |
| 同尺寸，unique terms，注解 off | 0.450 → 0.449 | 2.177 → 2.092 |
| 64 × 2048，注解 off | 1.990 → 1.917 | 7.527 → 7.631 |

收益主要来自保留注解时的 key 校验；无注解用例变化较小，包含测量波动。
注解 on 的旧 simplify pass-only perf 为约 14K samples，parseKey/key 分别
占 self 4.15%/3.46%，另有大量私有 parser/quote、字符串搬运与分配成本；
注解 off 约 3K samples 中 contains/opAttrs 分别占 self 11.46%/8.64%。
这些百分比仅描述对应 fixture，不能外推整机份额。

## 整机记录

full35 已于 2026-11-01 08:57:33 UTC 主动 SIGINT，退出 130，停于 sink
分区；不是 20 分钟超时。后续 full36 使用完整默认 full pipeline、注解 on、
simplify 默认上限 8 轮、packing/masked-OR/phase/clone、checkpoint、roundtrip
和可读导出，保留原 FIRRTL/full27 harness。外层和 producer 都有 20 分钟
SIGKILL 保护，外层还将 manifest 准备计入总预算。2026-11-01 09:43:49 UTC
启动，10:03:49 UTC 外层按时 SIGKILL，退出 137；未恢复或重置预算。
停止于 flatten 后的 `grh.verify`，尚未进入普通 GRH simplify、backend
simplify 或 C++ emit。未构建/执行 emu，F10 和 20 分钟目标均未达标。

| 已完成阶段 | 秒 |
| --- | ---: |
| FIRRTL/mixed ingest | 516.645 |
| xmr-resolve | 17.820 |
| mux-tree-fold（第一次） | 69.705 |
| register-write-normalize | 33.425 |
| mux-tree-fold（第二次） | 46.696 |
| memory-read-retime | 30.530 |
| multidriven-guard | 0.638 |
| blackbox-guard | 0.639 |
| latch-transparent-read | 9.947 |
| hier-flatten | 396.894 |
| comb-loop-elim | 48.114 |
| 合计 | 1171.053 |

已完成阶段累计 19 分 31.053 秒，预算余量 28.947 秒还需容纳输入清单、
身份捕获、当前 verify 及全部后续生成，因此不足；总目标还差多少无法从
本次未完成流程精确量化。不能将 full35 的 220.380 秒 flatten 与这里直接
作 A/B：full35 关闭注解、采用 bringup，而本次保留完整默认配置。
整机编译器实际加载库 SHA-256 为
`9ac63c5a559340cc75b156ccb2e9e29d043f064b389954dbbabfcc520f29c233`，
与 final-candidate 相同。完整日志、源/库身份和停止记录位于
`ptmp/firrtl-ingest/F10/full36/`。
