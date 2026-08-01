# 12 GSim Node 打平（--flatten-nodes）实验设计与实现记录（2026-07-31）


本文记录"gsim node 层次打平"逆向实验的设计、实现与前置验证；参数对齐与
XiangShan coremark 50k 对比结果见 [`13-gsim-node打平coremark50k对比`](13-gsim-node打平coremark50k对比.md)。

## 背景与假设

长期假设：gsim 相对 grhsim 多出的 **node 层次**（Node 是 ENode 的容器，一个
Node 可以挂整棵表达式树）是其 activity 划分效果更好的根本原因。在 wolvrix
grhsim / grhsim-am 中重建该层次成本高且引入不确定性，因此做**逆向实验**：
在 gsim 中把 node 层次打平，让每个 node 至多保留一个具有计算语义的 enode，
观察 activity 划分（超节点结构与运行时激活行为）是否因此退化。

## 实验设计

1. 给 gsim 增加一个处理环节（`--flatten-nodes`），在 `graphPartition` 之前把
   表达式树拆成"三地址码"形态：每个 Node 至多保留一个计算语义 enode，
   ref enode（`nodePtr != nullptr`）与常量叶子保留在原位表达连接关系。
2. 除该新环节外不动任何其他调度/划分流程（coarsen、DP partition、
   replication、stmtTree、insts、emitter、激活机制全部原样）。
3. 打平后节点数变多，超节点数量随之变大；用 `--supernode-max-size` 调参，
   把打平版的最终超节点数对齐回基线水平，再做对比。
4. 对比项：XiangShan coremark 50k 仿真性能（Host time）、图结构
   （超节点数、超节点间 DAG 边数、激活边数）。

## 打平 pass 设计（`graph::flattenNodes()`）

插入位置：`main.cpp` 中最后一次 `removeDeadNodes` 之后、`graphPartition`
之前，仅 `--flatten-nodes` 打开时执行；此时 inferWidth/usedBits/
constantAnalysis/aliasAnalysis/commonExpr 均已完成，图中不再存在
CONSTANT_NODE 成员。

规则：

- **打平目标节点**：`NODE_OTHERS` / `NODE_OUT` / `NODE_REG_DST` 且
  `status == VALID_NODE` 且非数组（`dimension` 为空）。
  跳过 `NODE_REG_SRC`（保持"单棵纯 ref 树"形态）、`NODE_REG_RESET`、
  `NODE_MEMORY` / `NODE_READER` / `NODE_WRITER` / `NODE_READWRITER`
  （`OP_READ_MEM` / `OP_WRITE_MEM` 有属主类型断言）、`NODE_SPECIAL`
  （printf/assert/stop 的 `OP_WHEN(OP_PRINTF)` 形态）、
  `NODE_EXT` / `NODE_EXT_IN` / `NODE_EXT_OUT`（`OP_EXT_FUNC` 单树形态）、
  数组节点（lvalue 下标与 arrayCopy 语义）。
- **叶子**（不抽取）：ref enode（`nodePtr != nullptr`，数组下标子树保持
  不透明）、`OP_INT` / `OP_INVALID` / `OP_EMPTY`。
- **保留原位**（不独占新节点，继续递归其孩子）：
  - `OP_WHEN`：条件赋值骨架属于控制语义；含 null 分支的 when 不是纯值，
    抽离会丢"保持原值"语义；保留后 `mergeWhenNodes`/`when2mux` 行为不变；
  - `OP_GROUP`：聚合 gather 是数组类型值，不能独占标量节点；
  - `OP_INDEX` / `OP_INDEX_INT`：数组下标选择子不是独立值（其 valStr 是
    `[idx]`，单独成节点会生成非法 C++——第一版实现因此在 rocket 上失败）。
- **抽取**：其余计算 enode 被移动到一个新建 `NODE_OTHERS` 节点，新节点的
  assignTree 恰好是该 enode 一棵树；原孩子槽位替换为指向新节点的裸 ref。
  新节点字段：`width/sign/usedBit/isClock/reset` 取自被移动 enode，
  `lineno` 取自原节点，名字为 `原名$flat<N>`（全局唯一计数）。
- **图重建**：每个新节点配一个独立 `SuperNode` 并追加进 `sortedSuper`，
  然后 `reconnectAll()`（清边、`updateConnect`、`connectDep`、
  `reconnectSuper`）+ `resort()` 恢复 dep 拓扑序；最后对全部 assignTree
  `clearInfo()` 清掉 constantAnalysis 残留的 `computeInfo` 缓存
  （`ENode::compute` 会优先复用该缓存，孩子被改写后必须失效）。
- `resetTree`、`regNext` 绑定、多 assignTree 的顺序语义全部不动。

## 代码改动（reference/gsim 子模块内）

- `include/config.h`：`Config::FlattenNodes`。
- `include/graph.h`：`graph::flattenNodes()` 声明。
- `src/main.cpp`：`--flatten-nodes` 选项与 `FlattenNodes` stage 插入。
- `src/flattenNodes.cpp`：打平 pass 实现（新增文件，Makefile 按
  `src/*.cpp` 通配自动纳入）。

未做任何 git 提交；子模块工作区保持脏状态以便审阅。

## 基线口径

- FIR：`build/xs/rtl/rtl/SimTop.fir`（2026-07-03 生成），
  `sha256 = b107e470ad396814e647846428af6409b8aabaf364c6812b7ec413843eca53e3`。
- gsim 参数（与 `testcase/xiangshan/difftest/gsim.mk` 的 `GSIM_FLAGS` 一致）：
  `--supernode-max-size=15 --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__`。
- 基线 emu：`build/xs/gsim/gsim-compile/emu`；
  构建日志 `build/logs/xs/xs_gsim_build_flatten_baseline_20260730.log`。
- 基线图结构（`build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json`）：
  - PreCoarsen 超节点 `2,708,065`；Coarsen 后 `293,985`；
    InitPartition 后 `84,786`；最终发射 `84,642` 超节点、`488,844` 定义节点；
  - `dag_edges = 645,853`；`activation_edges = 1,379,972`；
    `unique_activation_edges = 719,101`。
- 基线 coremark 50k（`build/logs/xs/xs_gsim_flatten_baseline_20260730.log`）：
  - `instrCnt = 73,584`，`cycleCnt = 49,998`，difftest 通过（与
    [`NO0255`](../../pdocs/grhsim_opt/NO0255_simtop_same_fir_perf_profile_20260710.md) 的
    `73584 / 49998` 完全一致）；
  - Host time spent `22,914 ms`（本机 32 线程；绝对值仅与本次打平版对比，
    不与历史其他机器比较）。

## 构建环境修复记录（本机重建 gsim 流程时遇到的问题）

- 本机缺 `bison` / `flex` / `FlexLexer.h` / `gmp.h` / `zstd.h`：
  用 `apt-get download` 下载 `bison flex libfl2 libfl-dev libgmp-dev
  libzstd-dev zlib1g-dev` 的 deb 包，`dpkg -x` 解到 `build/dependency/root`
  （deb 原件在 `build/dependency/debs`，`build/` 已被 gitignore），
  通过 `PATH` + `BISON_PKGDATADIR` + `CPATH` + `LIBRARY_PATH` 注入，
  不需要 root。注意 `-L` 不能放 `CXXFLAGS`（clang `-Werror` 会把
  unused-argument 当错误），必须用 `LIBRARY_PATH`。
- `make xs_gsim_emu` 的 `xs_gsim_rtl` 依赖要求 `mill`（在
  `/home/gaoruihao/wksp/mill`，不在默认 PATH），且会强制重新生成 RTL；
  本次直接复用 2026-07-03 的 `SimTop.fir`，绕过 `xs_gsim_rtl`，
  直接调 `testcase/xiangshan/difftest` 的 `make emu`（参数与顶层
  `Makefile` 的 `xs_gsim_emu` 目标一致）。
- `testcase/xiangshan/build/generated-src/difftest-extmodule.cpp` 在本机缺失
  （链接时报 27 个 `DiffExt*` 及 `SDCardHelper` / `FlashHelper` /
  `Mem1R1WHelper` 未定义）。该文件正常由 mill 细化和时
  `Difftest.scala::generateCppExtModules` 写出；本次未重跑 mill，改为机械重建：
  - 27 个 `DiffExtXxx`：从生成的 `SimTop.h` 的声明与
    `difftest-dpic.h` 的 `v_difftest_Xxx` 声明对齐得到
    （`DiffExt = enable + [io_valid] + v_difftest 参数`，27 个全部逐参数
    类型对齐验证通过；17 个含 `io_valid`，10 个不含），
    函数体为 `if (_0) v_difftest_Xxx(...)`；
  - `Mem1R1WHelper` / `FlashHelper` / `SDCardHelper`：函数体取自
    `difftest/src/main/scala/common/{Mem,Flash,SDCard}.scala` 的
    `cppExtModule` 模板。
  - 重建产物：`testcase/xiangshan/build/generated-src/difftest-extmodule.cpp`。

## 前置功能验证（rocket）

在打平的 XiangShan 探针之前，先用 `reference/gsim/ready-to-run/
TestHarness-rocket.tar.bz2` 做端到端验证：

- base 与 `--flatten-nodes` 各生成并编译 rocket emu（参数
  `--supernode-max-size=15`）；
- 两边同跑 `ready-to-run/bin/coremark-rocket.bin`，4,200,000 周期，输出逐字节
  一致（仅计时不同）；
- 该验证同时暴露了 `OP_INDEX` 处理 bug（`tmp = [idx];` 非法 C++），
  修复为 `OP_INDEX/OP_INDEX_INT` 保留原位后才通过。

## 后续

参数对齐过程与 XiangShan coremark 50k 的打平前后对比结果见
[`13-gsim-node打平coremark50k对比`](13-gsim-node打平coremark50k对比.md)。
