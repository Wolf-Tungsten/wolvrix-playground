# NO0079 BigComb Chisel 纯组合 GSim / GrhSIM Benchmark

记录日期：2026-05-09

## 目的

为了把 XiangShan 整机中的状态、commit、外围 runtime 因素先拿掉，本轮新增一个独立 synthetic testcase：

- 用 Chisel 生成一个大规模纯组合模块 `BigComb`；
- 同一份 Chisel 产出 FIR 和 SystemVerilog；
- `gsim` 从 FIR 编译，`grhsim` 从 SV 编译；
- 同一个 C++ benchmark 预生成确定性大激励序列，先比较两边输出，再分别单独计时。

这个 testcase 用来定性回答：即使没有状态提交和 commit supernode，`grhsim` 的组合 compute 代码形态是否仍然比 `gsim` 慢。

## Testcase 形态

新增目录：

```text
testcase/big-comb/
```

主要文件：

```text
testcase/big-comb/src/main/scala/BigComb.scala
testcase/big-comb/tb/big_comb_bench.cpp
testcase/big-comb/scripts/emit_grhsim.py
testcase/big-comb/Makefile
```

`BigComb` 顶层端口：

- 输入：`io_in0..io_in31` 共 32 个 `UInt(64.W)`，另有 `io_ctrl: UInt(64.W)`、`io_sel: UInt(16.W)`；
- 输出：`io_out0..io_out15` 共 16 个 `UInt(64.W)`，另有 `io_flags`、`io_checksum`；
- 无寄存器、无 memory、无状态更新，只有 Chisel `Module` 隐含的 `clock/reset` 端口。

覆盖的组合形态：

- 8/16/32/64-bit slice、concat、pad；
- add/sub、bitwise and/or/xor/not；
- dynamic shift、static shift、rotate；
- signed/unsigned comparison；
- mux tree、`MuxLookup`、`Mux1H`；
- `PopCount`、`PriorityEncoder`、`Reverse`、`Fill`；
- 多轮 lane mixing 和 group reduction。

说明：早期版本包含小位宽乘法，但 `grhsim` 当前 emitter 对 firtool 生成的 `128-bit intermediate -> 64-bit truncate` 路径会生成非法 C++，因此本轮把乘法替换成 shift/add/xor 混合。这个 testcase 当前只用于速度定性，不覆盖宽乘法 helper 正确性。

## 构建口径

Chisel / Mill 缓存固定在 testcase 目录内：

```text
testcase/big-comb/.sandbox-cache/
```

生成命令：

```bash
make -C testcase/big-comb generate
make -C testcase/big-comb gsim
make -C testcase/big-comb grhsim
make -C testcase/big-comb bench BENCH_VECTORS=1000000 BENCH_VERIFY=4096
```

关键参数：

```text
GSIM_FLAGS = --supernode-max-size=8 --cpp-max-size-KB=512
GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE = 8
GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE = 768
GRHSIM_SCHED_BATCH_MAX_OPS = 2048
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES = 8192
GRHSIM_SCHED_BATCH_TARGET_COUNT = 64
CXXFLAGS = -O3
```

## 产物规模

生成源码规模：

```text
BigComb.fir : 172458 lines, 26M
BigComb.sv  :  91132 lines, 5.8M
```

`gsim` final stats：

```text
node_count = 111219
supernode_count = 223
emitted_supernode_count = 221
edge_count = 174616
expnode unique_count = 405023
expnode op_types:
  OP_ADD 43680
  OP_BITS 48196
  OP_MUX 7744
  OP_CAT 3095
  OP_XOR 3426
  OP_DSHL 64
  OP_DSHR 64
  OP_SHL 480
  OP_SHR 1408
```

`grhsim` activity-schedule stats：

```text
supernodes = 996
compute_supernodes = 996
commit_supernodes = 0
compute_nodes = 7565
graph_ops = 240947
compute_node_ops_total = 240798
source_clones_in_compute_nodes = 77689
boundary_values = 5981
boundary_activation_edges = 13612
dag_edges = 8158
ops_per_supernode.mean = 241.77
ops_per_supernode.max = 3147
```

二进制/对象规模：

```text
gsim object files total          1.1M
grhsim libgrhsim_BigComb.a      1.3M
linked benchmark binary         2.1M
```

## Benchmark 结果

Smoke run：

```text
[VERIFY] vectors=1000 status=pass
[BENCH] model=gsim   vectors=1000 ms=13.958 vectors_per_s=71641.74 checksum=0x4b9f36438ed3382f
[BENCH] model=grhsim vectors=1000 ms=44.659 vectors_per_s=22391.80 checksum=0x4b9f36438ed3382f
```

大激励 run：

```text
[VERIFY] vectors=4096 status=pass
[BENCH] model=gsim   vectors=1000000 ms=15556.789 vectors_per_s=64280.62 checksum=0x92cd1159a6bbfc47
[BENCH] model=grhsim vectors=1000000 ms=44223.253 vectors_per_s=22612.54 checksum=0x92cd1159a6bbfc47
```

换算：

```text
grhsim / gsim wall time = 44223.253 / 15556.789 = 2.8427x
gsim / grhsim throughput = 64280.62 / 22612.54 = 2.8427x
```

## 结论

在这个纯组合大图上，`grhsim` 不再有 commit supernode 和状态提交开销，但仍比 `gsim` 慢约 `2.84x`。这说明 XiangShan 上的 `~10x` 差距不能完全归因于“激活更多 supernode”或 commit 侧行为；`grhsim` 的 compute-only 生成代码本身已经有明显单位工作成本劣势。

但这个差距小于 XiangShan runtime profile 中暴露出的单位 op 成本差距，说明整机上还叠加了额外因素：

- `grhsim` 的 compute supernode 数量和 activation fanout 更大，本 testcase 中 `996` vs `223`；
- `grhsim` compute node 内存在 source clone 和 boundary activation 维护；
- XiangShan 还包含 commit supernode、state old/new compare、activation bitset 写入、memory/state slot 访问等本 testcase 刻意剥离的成本。

因此，本轮 testcase 给出的定性边界是：单看纯组合 compute，`grhsim` 生成代码已经约慢 `2.8x`；XiangShan 上剩余到 `~10x` 的部分，需要继续从状态/commit 路径、activation 传播密度和 value slot 访问形态解释。

