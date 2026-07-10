# NO0237 Assembly spill 归因与 compute supernode size A/B（2026-07-09）

## 1. 背景

`NO0235` 和 `NO0236` 排除了两个看似直接的 codegen 方向：

- `grhsim_slice_words<1>(..., 64*k, 64)[0]` 表层替换在 Clang `-O3` 下是机器码 no-op；
- 朴素把 wide slot producer 后续 scalar slice 挪到 `next_words[i]` 会增大 hot symbol 并变慢。

本轮转向更底层的汇编形态：比较 GrhSIM input-low 所跑的 compute batches 与 GSIM `subStep1()` 的静态机器码，并验证一个直接假设：如果 GrhSIM 慢来自大 supernode 带来的寄存器压力/stack spill，那么降低 compute supernode size 是否会改善性能。

所有命令均先执行：

```bash
source env.sh
set -euo pipefail
```

## 2. GrhSIM compute0-3 vs GSIM subStep1 汇编形态

对象：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/
```

GrhSIM input-low 一轮会调度 compute batch 0-3；GSIM 对照阶段是 `subStep1()`。

| unit | symbol size | instr | mem operands | stack operands | SIMD instr | branches | cmov | setcc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GrhSIM `eval_compute_batch_0()` | `11905` | `2757` | `952` | `261` | `0` | `17` | `5` | `186` |
| GrhSIM `eval_compute_batch_1()` | `7887` | `1738` | `716` | `200` | `0` | `17` | `3` | `66` |
| GrhSIM `eval_compute_batch_2()` | `11072` | `2383` | `1044` | `197` | `108` | `17` | `29` | `623` |
| GrhSIM `eval_compute_batch_3()` | `21723` | `4333` | `2195` | `927` | `450` | `84` | `36` | `32` |
| **GrhSIM compute0-3 total** | `52587` | `11211` | `4907` | `1585` | `558` | `135` | `73` | `907` |
| GSIM `subStep1()` | `12198` | `2788` | `989` | `8` | `128` | `187` | `50` | `84` |

关键观察：

1. GrhSIM compute0-3 静态指令数 `11211 / 2788 = 4.02x` 于 GSIM `subStep1()`；这与 `NO0234` 的 input-low retired instructions ratio `4.57x` 同方向且接近。
2. GrhSIM stack operands `1585`，GSIM `subStep1()` 只有 `8`，说明 GrhSIM 热路径有非常明显的 stack spill / stack temporary 压力。
3. GrhSIM SIMD 指令并不少，尤其 batch3 有 `450` 条 SIMD 相关指令；因此“宽字 helper 没有被向量化”不是主要解释。
4. batch3 是最大热点和最大 spill 来源：`4333` instr、`927` stack operands。

因此当前更准确的解释是：GrhSIM input-low 的 `~4x` 指令差距主要已体现在 compute batch 静态机器码规模与 spill 上，而不是某个没内联 helper 或某个单独 branch miss。

## 3. perf annotate 快照

使用 `NO0234` 的 phase-specific perf data：

```text
tmp/no0234_phase_compare_20260709/perf/grhsim-input-low.data
```

`eval_compute_batch_3()` annotate 中 top sample 分布较散，最高点示例：

```text
2.87% 0x16c08 mov 0x620(%rdi),%rcx
1.23% 0x1b602 mov 0xcc8(%rdi),%rbp
0.84% 0x17ada mov 0xb38(%rdi),%rbp
0.74% 0x17ae1 mov 0xb30(%rdi),%rcx
0.50% 0x1b966 jne 0x1b978
```

该 perf 只有约 `810` 个 batch3 samples，不能做精细行级判断；但它显示 batch3 热点不是单一 helper 调用，而是多个大块内存 load/store/bit-op 分散贡献。

## 4. compute supernode size A/B

实验变量：`GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE`。

baseline 默认是 `128`。本轮重建 `VtypeBuffer` GrhSIM：

- `MAX_OP=64`
- `MAX_OP=32`
- `MAX_OP=256`

复用 baseline 的 SV/GSIM 产物，只重新生成 GrhSIM。

### 4.1 静态指标

| variant | supernodes | compute supernodes | DAG edges | compute batches | symbol size total | instr total | mem operands | stack operands | SIMD instr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `MAX_OP=128` baseline | `39` | `38` | `170` | `4` | `52587` | `11211` | `4907` | `1585` | `558` |
| `MAX_OP=64` | `74` | `73` | `321` | `3` | `54478` | `11613` | `5074` | `1085` | `243` |
| `MAX_OP=32` | `174` | `173` | `769` | `3` | `60922` | `12957` | `5498` | `726` | `271` |
| `MAX_OP=256` | `20` | `19` | `73` | `3` | `52337` | `10952` | `5030` | `1968` | `855` |

解读：

- `MAX_OP=32` 确实把 stack operands 降到 `726`，但 supernodes/DAG edges/总指令明显增加；
- `MAX_OP=256` 总指令略低，但 stack operands 增到 `1968`；
- 默认 `128` 处在两个压力之间的较好折中点。

### 4.2 runtime 结果

200k vectors，`--verify 4096 --repeat 3`：

| variant | GrhSIM min ms | GrhSIM median ms | vs baseline min |
|---|---:|---:|---:|
| `MAX_OP=128` baseline | `399.121` | `399.174` | - |
| `MAX_OP=64` | `412.336` | `412.500` | `+3.31%` |
| `MAX_OP=32` | `428.880` | `429.008` | `+7.46%` |
| `MAX_OP=256` | `413.758` | `413.935` | `+3.67%` |

三组都比 baseline 慢。

## 5. 结论

本轮结论：**简单调 compute supernode size 不是当前突破口**。

更具体地说：

1. GrhSIM input-low 对 GSIM 的指令差距，在静态机器码上已经很明显：compute0-3 指令数约 `4.02x` 于 GSIM `subStep1()`；
2. GrhSIM 的 stack spill 压力很大，但直接减小 supernode 只是在降低 spill 的同时增加 active boundary、DAG edges 和总指令；
3. 增大 supernode 可以减少边界，但会进一步增加 stack pressure；
4. 默认 `MAX_OP=128` 对 `VtypeBuffer` 已经比 `32/64/256` 更好。

这也解释了为什么此前围绕分区/拓扑的粗粒度调参收效有限：它们主要在边界开销与寄存器压力之间移动，没有消除 GrhSIM 相比 GSIM 的通用 slot/ref 和 batch framework 结构性额外工作。

## 6. 下一步

下一步不建议继续盲调 `GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE`。更有希望的方向是：

1. **按 supernode / active bit 动态计数**：确认 input-low 中哪些 supernode 几乎每 cycle 都 active，优先针对这些块优化，而不是整批处理；
2. **减少通用 slot/ref load-store**：当前 compute0-3 有 `4907` 个 memory operands，其中许多来自 `value_u64_slots_` / state storage；应寻找能减少实际内存访问的 typed local 缓存，而不是表层表达式替换；
3. **以 hot symbol size / stack operands 为 gate**：后续任何 codegen A/B 若不能降低 hot symbol size、stack operands 或最终 binary 指令形态，应先视为可疑。
