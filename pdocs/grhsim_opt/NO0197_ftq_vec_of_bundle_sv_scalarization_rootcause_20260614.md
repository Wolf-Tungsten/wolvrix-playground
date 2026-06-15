# NO0197 FTQ `metaQueueResolve` 提交爆炸的根因定位：Vec-of-Bundle 在 SV 层已被 firtool 标量化

记录日期：2026-06-14

关联：

- [`NO0196`](./NO0196_two_eval_vs_xiangshan_sink_succ_inconsistency_20260614.md)：定位到 XiangShan 7.93x 的真实大头候选是 ~79 个 array-register 的 per-slot 提交（一个 supernode 4090 条 `kRegisterWritePort` + 12k generic storage 间接），不是 indexed store。
- [`NO0188`](./NO0188_xs_preserve_aggregate_full_grhsim_correctness_progress_20260609.md)：preserve-aggregate 正确性进展。
- 新增单测：`testcase/xs-bugcase/CASE_022`（packed vec 索引写）、`CASE_023`（bundle 拆成 per-field packed vec）。

本文回答 NO0196 留下的问题：**「preserve-aggregate 不是做了吗，为什么对 FTQ 这个模块不起效？是 SV 层就丢了，还是后续处理被展开了？」** 结论：**SV 层就丢了**（firtool 把 Vec-of-Bundle 标量化），grhsim 自身的 lowering 没有问题。

## 1. 两边读的输入不同，这是分水岭

| | 读入 | `entries` 形态 | 提交 |
| --- | --- | --- | --- |
| gsim | **FIRRTL `.fir`**（`Makefile:931` `$(XS_GSIM_BIN) ... --sep-aggr=__DOT__ $(XS_SIM_TOP_FIR)`）| Vec-of-Bundle 作为一等类型保留 → `metaQueueResolve.tage.entries.providerUsefulCtr.value[64][8]` | **indexed store** `value[ftqIdx][i0]=…`，O(1) |
| grhsim | **SV**（`wolf_emit.sv` ← `build/xs-preserve-aggregate/rtl/rtl/Ftq.sv`）| **已被 firtool 标量化**成 9856 个独立 scalar `reg` | per-element 提交（NO0196 的 4090 条/supernode）|

`Ftq.sv` 里这些寄存器长这样（无任何 packed 维度）：

```systemverilog
reg metaQueueResolve_0_mbtb_entries_0_0_rawHit;
reg [4:0] metaQueueResolve_0_mbtb_entries_0_0_position;
...
// entries 的 Vec[N]-of-Bundle 被展开成 entries_0_*, entries_1_*, ... 逐字段逐下标的标量
```

`grep -c "reg .*metaQueueResolve_" Ftq.sv = 9856`。**到 grhsim 手里时已经没有数组可保留了。**

## 2. firtool 保 1-D vec、但标量化 Vec-of-Bundle

同一个 `Ftq.sv` 里**有 512 个 packed-array 寄存器活了下来**，例如：

```systemverilog
reg [7:0][4:0] metaQueueRedirect_0_commonHRMeta_position;   // Vec[8] of UInt[5] -> packed
```

XS 的 firtool 选项（`testcase/xiangshan/Makefile:79`）：

```
--lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none
```

没有 `-preserve-aggregate=all`。现象是：**`Vec[N] of 地面类型`（UInt）能保成 packed array；`Vec[N] of Bundle`（结构体数组）被拆字段并把 vec 维一起摊平**成 `entries_0_field, entries_1_field, …`。FTQ 的 `entries` 正是 Vec-of-Bundle，所以中招；`commonHRMeta_position` 是 Vec-of-UInt，所以活下来。

## 3. 单测证明 grhsim 的 lowering 没问题（锅在 SV 输入）

### CASE_022：packed vec 的索引写 → grhsim 给 indexed memory store

`reg [63:0][1:0] entries_usefulCtr; entries_usefulCtr[write_idx] <= write_ctr;`

grhsim 生成（`build/xs_bugcase/CASE_022/grhsim/..._sched_1.cpp`）：

```cpp
// op _op_9 [kMemoryWritePort] mem=dut$entries_usefulCtr
state_mem_dut_entries_usefulCtr_2_[ write_idx & 63 ] = next_value;   // O(1) indexed store
```

两个写口 = **2 个 `kMemoryWritePort`**，不是 64 条 per-element。`make run` 对 verilator **PASS**。→ 只要 SV 里是 packed array，grhsim 就正确地走 indexed memory。

### CASE_023：bundle 拆成 per-field packed vec → 仍是 O(1) 写口

把一个 3 字段 bundle 写成 3 个并列 packed vec（共享写下标），grhsim 生成：

| 字段数组 | lowering |
| --- | --- |
| `entries_usefulCtr [63:0][1:0]` | 1 × `kMemoryWritePort`（indexed）|
| `entries_providerTableIdx [63:0][2:0]` | 1 × `kMemoryWritePort`（indexed）|
| `entries_useProvider [63:0]`（1-bit 元素）| 1 × `kRegisterWritePort`（bit-select 进 64-bit 寄存器，仍 O(1)）|

共 **3 个 O(1) 写口**，而不是 3×64=192 条 scalar 提交。`make run` 对 verilator **PASS**。

> 附带结论：packed `struct` 数组**不是**可选路径——wolvrix 的 SV 前端拒绝 `entries[i].field` 这种 struct member-select（CASE_023 初版 read_sv 报 `Unsupported expression kind`）。所以修复目标是 **per-field packed array**，不是 packed struct。

## 4. 结论与修复方向

1. **是 SV 层丢的，不是 grhsim 后续展开的。** firtool 把 FTQ 的 Vec-of-Bundle 标量化成 9856 个 scalar reg，wolvrix 没有数组可保。preserve-aggregate 只能保住「SV 里仍是 packed array」的那些（512 个 `[a:b][c:d]`），保不了「SV 里已经是一堆标量」的。
2. **grhsim 的 lowering 是对的**：给它 packed array 索引写，它就出 indexed memory / bit-select register（CASE_022/023 实证，且对 verilator 数值正确）。
3. **修复路径（按可行性排序）：**
   - (a) **让 SV 保住 vec 维**：调 firtool/MFC，使 Vec-of-Bundle 输出为「每字段一条 packed array」（`entries_usefulCtr[63:0][1:0]` 等），而不是 `entries_0_usefulCtr, …`。这正是 CASE_023 的形态，grhsim 现成支持。需要确认 firtool 是否有对应 `-preserve-aggregate` 档位能对 vec-of-bundle 生效（当前选项里没有，且 `disallowLocalVariables` 等可能干扰）。
   - (b) **wolvrix 端 re-aggregation**：在 ingest 识别 `<name>_<i>_<field>`（连续下标、同构字段）标量族，重建成 per-field memory，恢复 indexed 读写。是启发式，但不依赖改 firtool。
   - (c) 让 grhsim 也读 `.fir`（同 gsim），从源头拿到 Vec-of-Bundle。改动面最大。
4. **与 commit 分离正交**：本问题纯属 aggregate 表示，不涉及 commit 分离语义。

## 5. 复现

```bash
source env.sh
export VERILATOR_ROOT=$(verilator -V | awk -F'= *' '/VERILATOR_ROOT/{print $2}')
make -C testcase/xs-bugcase/CASE_022 run   # packed vec -> indexed memory, PASS
make -C testcase/xs-bugcase/CASE_023 run   # per-field packed vec -> O(1) 写口, PASS
# 对照真实 SV：
grep -c 'reg .*metaQueueResolve_' build/xs-preserve-aggregate/rtl/rtl/Ftq.sv   # 9856 标量
grep -nE 'reg +\[[0-9]+:[0-9]+\] *\[[0-9]+:[0-9]+\]' build/xs-preserve-aggregate/rtl/rtl/Ftq.sv | head  # 幸存的 packed vec
```

## 6. 延续探索：`--preserve-aggregate=all` 目前还不能直接给 grhsim 用

问题：既然 `--preserve-aggregate=1D` 的 grhsim 路线已经跑通，改成 `--preserve-aggregate=all` 能否从源头解决 FTQ 的 Vec-of-Bundle 标量化？

短结论：

1. **形态上有用。** `all` 确实把 `metaQueueResolve` 从 9856 个 scalar reg 重新保成了一个 packed aggregate。
2. **端到端还不能用。** 当前 `all` 生成的 SV 不是 grhsim/wolvrix 的可用输入：先被 SV 关键字字段名卡住；手工绕过关键字后，又会被 packed struct 的 member-select、assignment pattern、partial field write 卡住。
3. **它不是 CASE_023 的理想形态。** CASE_023 证明可用的是「每字段一条 packed array」；`all` 给出的是「巨大匿名 packed struct array」。后者当前前端不支持。

### 6.1 生成命令

基于已有 `SimTop.fir` 重新跑 firtool：

```bash
firtool -O=release \
  --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none \
  --preserve-aggregate=all \
  --split-verilog \
  -o build/xs-preserve-aggregate-all/rtl/rtl \
  build/xs-preserve-aggregate/rtl/rtl/SimTop.fir
```

额外 read args 记录在：

```text
build/xs-preserve-aggregate-all/rtl/read_args.txt
```

内容为：

```text
-I /home/gaoruihao/wksp/wolvrix-playground/build/xs-preserve-aggregate-all/rtl/rtl
-I /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/difftest/src/test/vsrc/common
-I /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
-D DIFFTEST
```

### 6.2 `all` 对 FTQ 形态的影响

对照 `1D` 版本：

```bash
rg -c 'reg .*metaQueueResolve_' build/xs-preserve-aggregate/rtl/rtl/Ftq.sv
# 9856
```

`all` 版本：

```bash
rg -c 'reg .*metaQueueResolve_' build/xs-preserve-aggregate-all/rtl/rtl/Ftq.sv
# 0（rg 无匹配会以非 0 退出）

rg -c 'struct packed' build/xs-preserve-aggregate-all/rtl/rtl/Ftq.sv
# 12186

rg -c 'metaQueueResolve\[' build/xs-preserve-aggregate-all/rtl/rtl/Ftq.sv
# 30849
```

关键声明从标量族变成了：

```systemverilog
struct packed { ... }[63:0]
  metaQueueResolve;
```

并且访问形态是深层 packed struct member-select：

```systemverilog
metaQueueResolve[6'h3F].tage.entries[3'h7].providerUsefulCtr.value
metaQueueResolve[_resolveQueue_io_bpuTrain_bits.ftqIdx.value]
```

所以 `all` 对 NO0197 的「SV 层已经丢掉 Vec-of-Bundle」问题有真实帮助：它没有再把 `metaQueueResolve` 摊成 9856 个 reg。但是它保留的是完整 struct aggregate，不是 grhsim 当前优化过的 per-field packed array。

### 6.3 第一道硬阻塞：firtool 保留了 SV 关键字字段名

`all` 版本的 `NfMappedElemIdx.sv` 里出现：

```systemverilog
output struct packed {struct packed {logic [7:0] from; logic [7:0] until; }[7:0] idxRangeVec; } out
```

`until` 是 SystemVerilog 关键字，Verilator 和 slang 都直接拒绝。Verilator 复现：

```bash
verilator --lint-only --sv build/xs-preserve-aggregate-all/rtl/rtl/NfMappedElemIdx.sv
```

首个错误：

```text
syntax error, unexpected until
```

这说明原始 `--preserve-aggregate=all` 输出在语法层就不是当前工具链可接受的 SV。这个点发生在 wolvrix ingest 之前，暂时不能算 grhsim 后端问题。

### 6.4 绕过关键字后，wolvrix 仍不支持 packed struct aggregate

为了确认是否只有 `until` 命名问题，临时把 `NfMappedElemIdx.sv` / `VecExcpDataMergeModule.sv` 中整词 `from`、`until` 改成 `from_`、`until_`，放在：

```text
tmp/no0197_all_keyword_sanitized/
```

然后对 sanitized `NfMappedElemIdx` 单模块跑：

```bash
.venv/bin/python tmp/no0197_all_probe/run_read_sv.py \
  tmp/no0197_all_keyword_sanitized/NfMappedElemIdx.sv \
  NfMappedElemIdx
```

仍然失败。首类错误是 struct port member-select：

```text
Unsupported expression kind
  |     {3'h0, in.eewOH[0], 4'h0} ...
  |            ^
```

后续还有 assignment pattern：

```text
Unsupported expression kind
  |     '{from_: (8'h0), until_: _GEN_0};
  |     ^
```

再用更小的探针复现 FTQ 所需的核心形态：

```systemverilog
struct packed {logic valid; logic [1:0] ctr; }[3:0] entries;

always_ff @(posedge clock) begin
  entries[wr_idx].valid <= data[2];
  entries[wr_idx].ctr <= data[1:0];
end

assign y = entries[rd_idx].ctr;
```

`read_sv` 结果：

```text
Unsupported expression kind
  |     assign y = entries[rd_idx].ctr;
  |                ^
Unsupported memory write slice kind
  |             entries[wr_idx].valid <= data[2];
  |             ^
Unsupported memory write slice kind
  |             entries[wr_idx].ctr <= data[1:0];
  |             ^
```

所以即使把关键字字段名修掉，当前 wolvrix 也不能 ingest `all` 生成的 packed struct array/member-select/field-write 形态。

### 6.5 当前判断

`--preserve-aggregate=all` **不能作为现成 grhsim 方案**。

它解决了 NO0197 的一半：FTQ 的 Vec-of-Bundle 不再在 SV 层被摊成 scalar reg，因此理论上能消掉 per-slot 提交爆炸。但它同时引入了当前前端不支持的更强 aggregate 形态：

- packed struct typed ports；
- 匿名 packed struct array；
- `a.b` / `a[i].b` member-select；
- struct assignment pattern：`'{field: value, ...}`；
- packed struct array 的局部字段写：`entries[idx].field <= ...`。

因此目前可行路径仍按优先级是：

1. **最好：让 firtool 输出 per-field packed array**，即 CASE_023 形态。这能复用现有 grhsim indexed memory / packed-lane 支持。
2. **次选：在 wolvrix ingest 支持 packed struct aggregate**，把 member-select/field-write lowered 到 flattened bit slice 或 per-field memory。这个方向可行但改动面比 CASE_023 大，且要覆盖端口、wire、reg、assignment pattern、实例连接。
3. **不建议直接依赖 raw `all`**，除非同时解决关键字转义/重命名和 packed struct ingest。

所以本文前面的结论需要细化为：**`1D` 已经能处理 grhsim 当前支持的 packed array；`all` 能保住 FTQ aggregate，但当前还不能被 grhsim 端到端处理。**

## 7. NfMappedElemIdx xs-component：非 preserve aggregate 下的性能对比

为了把 `NfMappedElemIdx` 从 XiangShan 大设计里拆出来做稳定回归，新增了一个 xs-component case：

```text
testcase/xs-components/src/main/scala/cases/XsReal100BackendNfmappedelemidxSmall.scala
```

接入点：

```text
testcase/xs-components/src/main/scala/XsComponentsMain.scala
testcase/xs-components/Makefile
testcase/xs-components/cases.json
```

这个 case 保留了原始 `NfMappedElemIdx(128)` 的核心结构：

- 内部 `out.idxRangeVec` 是 `Vec(8, Bundle { from, until })`。
- 仍然有 `dontTouch(out.idxRangeVec)`，因此 FIR 里能看到 `out.idxRangeVec[*].until`。
- 顶层适配 xs-component bench 的固定 `io_in0..io_ctrl` / `io_out0..checksum` 接口，把 8 个 range 打包到 `out0/out1`，再混入输入形成 `out2/out3/flags/checksum`。
- 没有实例化子模块，避免 `--split-verilog` 只把顶层 SV 交给 grhsim ingest 时缺模块定义。

生成命令没有传 `--preserve-aggregate`：

```bash
make -C testcase/xs-components CASE=XsReal100BackendNfmappedelemidxSmall chisel-fir
make -C testcase/xs-components CASE=XsReal100BackendNfmappedelemidxSmall chisel-sv
```

结果形态符合预期：

- FIR 仍保留 aggregate：

```firrtl
wire out : { idxRangeVec : { from : UInt<8>, until : UInt<8>}[8]}
wire rangeTable : { from : UInt<8>, until : UInt<8>}[8][8]
wire shiftedRangeTable : { from : UInt<8>, until : UInt<8>}[8][8]
```

- SV 已经 scalarize；没有裸 `until` 关键字，也没有 `struct packed`：

```systemverilog
wire [7:0] out_idxRangeVec_0_from = 8'h0;
wire [7:0] out_idxRangeVec_0_until = _GEN[_nf_T];
...
wire [7:0] out_idxRangeVec_7_until = _GEN_13[_nf_T];
```

端到端 bench 命令：

```bash
PYTHONPATH=/home/gaoruihao/wksp/wolvrix-playground/wolvrix/build/skbuild/python \
make -C testcase/xs-components CASE=XsReal100BackendNfmappedelemidxSmall one \
  BENCH_VECTORS=1000000 BENCH_VERIFY=4096 BENCH_REPEAT=5
```

验证：

```text
[VERIFY] top=XsReal100BackendNfmappedelemidxSmall vectors=4096 status=pass
```

性能结果取 bench 的 `min_ms`：

| model | vectors | min ms | vectors/s | checksum |
| --- | ---: | ---: | ---: | --- |
| gsim | 1,000,002 | 21.979 | 45,498,035.29 | 0x9f455ca3a99bd905 |
| grhsim | 1,000,002 | 20.563 | 48,631,036.63 | 0x9f455ca3a99bd905 |

这组数据下：

- `bench_ms_grhsim_to_gsim = 0.9356`
- grhsim 比 gsim 快约 `6.9%`
- gsim：`supernodes=1`，`instruction_count=465`，`.text=2030B`
- grhsim：`supernodes=2`，`instruction_count=587`，`.text=2455B`

产物位置：

```text
testcase/xs-components/build/XsReal100BackendNfmappedelemidxSmall/chisel-fir/XsReal100BackendNfmappedelemidxSmall.fir
testcase/xs-components/build/XsReal100BackendNfmappedelemidxSmall/chisel-sv/XsReal100BackendNfmappedelemidxSmall.sv
testcase/xs-components/build/XsReal100BackendNfmappedelemidxSmall/tb/XsReal100BackendNfmappedelemidxSmall_bench.log
testcase/xs-components/build/XsReal100BackendNfmappedelemidxSmall/stats/model_stats.json
```

过程中还修了一个 xs-component bench 兼容性问题：`verify_models` 原先在非模板函数里直接用 `if constexpr (requires(...))` 调用 gsim runtime profile API；当 gsim class 没有 `set_runtime_profile_enabled` 时，clang 仍会在该上下文报错。现在改为调用已有的模板 helper `configure_runtime_profile(model, false)`，让能力探测发生在模板上下文里。

当前结论：**非 preserve aggregate 下，`NfMappedElemIdx` 这个 Vec-of-Bundle 小 case 可以被 gsim 和 grhsim 端到端处理并通过一致性验证；这组 repeat=5 的本机数据里 grhsim 略快于 gsim。**
