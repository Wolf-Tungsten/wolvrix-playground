# F07 混合 SV/FIRRTL 读取与链接验收

状态：已完成（2026-10-31）。分支：`grh/firrtl-ingest`。
Wolvrix 实现提交：`ad4d9a2`。

## 实施顺序

1. FIRRTL 实例类型、端口 flow、层次 lowering 和依赖遍历。
2. 请求级模块注册表、SV 接口声明与参数 specialization、ABI adapter。
3. Blackbox annotation 源收集、依赖身份与多源诊断。
4. Python 混合读取入口及 session 事务式发布。
5. 交替层次仿真、参数和 ABI 负例、完整回归。

## 验收记录

每项在实现和执行验证后填写命令、结果及产物位置。尚未填写表示未通过，
不能以语法扫描成功代替链接或仿真证据。

| 要求 | 状态 | 证据 |
| --- | --- | --- |
| FIRRTL → SV → FIRRTL 仿真 | 通过 | `test_ingest_mixed.cpp` top；256 组输入核验 `(a+3)^85`，真实接口声明绑定；`cross-source-final.log` |
| SV → FIRRTL → SV 仿真 | 通过 | svtop → top → bridge → leaf；同一独立期望和完整后端执行；`cross-source-final.log` |
| 类型化参数生成不同正确实现 | 通过 | Add3/Add9 分别计算 `a+3` / `a+9`，重复 Add3 去重，仅两个实现；整数保留 width/sign/bits，string/real/raw 参数独立测试 |
| 聚合、flip、嵌套数组、符号和布局适配 | 通过 | ABI driver 核验 underscore/Bundle/struct、flip、signed view、`[1][2]` singleton/nested shape 与交换后的精确位布局；256×4 输入组合 |
| 宏、include、参数派生宽度 | 通过 | macro driver：include 定义宽度，命令行宏定义增量，raw-string、string、real 参数；实际 include 内容进入依赖 |
| 路径、资源和内嵌 SV annotation | 通过 | inline/path/resource 三个真实 SV 编译模型；sidecar 解析、相同记录去重、资源 root、内容依赖；sidecar 错误带自有路径/行列 |
| 显式绑定、DPI/host 效果 | 通过 | renamed port/typed 参数绑定；cross-source FIRRTL 实现绑定并编译仿真；真实 DPI 每上升沿调用一次，重复 eval 不重调 |
| 重复、缺失、递归及端口不匹配诊断 | 通过 | 缺失实现、重复源/真实模块/绑定/参数/端口、错 source unit、位宽/方向/端口名/额外端口、同位宽 shape 冲突、未解析 Reset、交替递归和 public linkModules 递归均无 design 发布 |
| 多 owner、重复读取和失败不变性 | 通过 | C++ clone/result release、稳定 dependency、多个 SourceManager 不混用 ID；transform 自有坐标；Python 8/8，含替换失败后 JSON 不变、源释放后诊断仍可读 |
| 冻结目标代表路径与回归 | 通过 | 原始 MbistClockGateCell → 内嵌 SV ClockGate 的 latch/enable/hold 编译记分板通过，另有 Queue/SRAM/JTAG；全量 CTest 76/76、154个CPU模型顺序回归、输入校验4/4、冻结 10,008 模块及2,146 SV/头文件身份通过 |

工作日志放在 `ptmp/firrtl-ingest/F07/`，生成的测试模型放在
`wolvrix/build/artifacts/`。构建、测试和 Python 工作流仅通过 Makefile。

## 实现与证据

正式 API/ABI/源码收集合约见
[mixed.md](../../wolvrix/docs/ingest/mixed.md)。实现集中在 `lib/ingest/mixed.cpp`；
SV 仍使用 slang，FIRRTL 仍使用自有 lexer/递归下降 parser。没有 CIRCT/firtool
依赖，也没有将 FIRRTL 行为翻译成 SV。小型 SV wrapper 只用于参数 elaboration，
生成的签名声明只用于接口，最终均不成为空行为实现。

混合测试当前生成11个编译模型：hierarchy、cross-source、top、svtop、parameters、
abi、inline、path、resource、macro、dpi。后续阶段的完整 node CSE/nonsink
利用仍分别属于 F08/F09。本阶段保留 root/member 和逐级实例路径。

| 命令 | 已取得的结果 | 日志 |
| --- | --- | --- |
| `make test_ingest_mixed` | 11个模型全部编译/执行通过，C++负例及specialize/link API通过；最终补齐 Reset/shape 负例 | `boundary-final.log` |
| `make test_wolvrix` | 76/76通过 | `regression-last.log` |
| `make py_install` | 最新 C++ editable包构建安装通过 | `python-build-latest.log` |
| `make test_ingest_python SKIP_PY_INSTALL=1` | 最新包8/8通过 | `python-latest.log` |
| `make test_grhsim_flow SKIP_PY_INSTALL=1` | 2/2 Python 流程及全部生成的 checkpoint 重启模型编译执行通过 | `grhsim-flow-final.log` |
| `make test_ingest_mixed test_firrtl_comb test_firrtl_state test_firrtl_memory test_firrtl_effects test_firrtl_target test_firrtl_parser_inputs verify_firrtl_inputs run_grhsim_cpu_st_cpp` | FIRRTL全部专项、原始四个目标和冻结身份通过；最后CPU模型编译发生产物生成/消费重叠，须顺序重跑 | `acceptance-final.log` |
| `make test_grhsim_cpu_st_cpp` | 顺序生成后154个CPU模型编译/执行全部通过，退出0 | `cpu-sequential.log` |

命令使用 `WOLF_ENV_SOURCED=1`；Python 使用仓库 `.venv/bin/python`，
安装的 TMPDIR/CCACHE/PIP cache 全在 F07 工作目录。原始输入及冻结
manifest 没有改变。首次CPU产物冲突来自另一次全量测试重生成目录，该次
不计为通过证据；最终顺序重跑已全部通过。生成器和模型编译不得并发操作
同一产物目录。

## 当前边界

Analog/inout 与未解析 Probe/Reset 外部接口明确拒绝；FIRRTL跨文件引用用
本地 extmodule 声明和显式实现绑定，不引入隐式跨 circuit 名称解析。
Hierarchical DontTouch 暂不支持且会报错；Inline/Dedup/Decode 保存优化来源。
黑盒源按可达 extmodule 收集，未使用记录保留为pending；所有annotation的
schema仍验证，不能静默丢弃未知语义。暂不声明整机香山等价或性能提升。
