# NO0078 GrhSIM / GSim Generated Code Static Sample

> 归档编号：`NO0078`。目录顺序见 [`README.md`](./README.md)。
>
> 本文档承接 [`NO0077`](./NO0077_xs_gsim_grhsim_runtime_profile_coremark_50k_20260509.md)：既然动态 profile 已经说明 `grhsim` 不是因为 total op solves 更多而慢，而是单位 op solve 成本明显更高，本轮进一步从生成 C++ 形态和编译后汇编形态做一次静态采样分析。

## 1. 分析目标

要解释的问题是：

- `grhsim` active supernode 比 `gsim` 多 `1.879x`，这会放大调度成本；
- 但 `grhsim` total op solves 只有 `gsim` total enode solves 的 `0.625x`；
- `grhsim` host ns/op 却是 `gsim` host ns/enode 的 `13.557x`。

因此主要矛盾不是“动态求解量多”，而是“单个 runtime op solve 的机器码成本更高”。

本轮只做静态采样，不声称替代 `perf record` 动态采样。目标是找出足够明确的代码形态差异，为下一轮动态 profiling 定位热点提供方向。

## 2. 样本选择

样本来自 2026-05-09 runtime profile 运行所用的已重建 emu 生成物：

- `gsim`
  - `build/xs/gsim/gsim-compile/model/SimTop320.cpp`
  - `build/xs/gsim/gsim-compile/model/SimTop23.cpp`
  - `build/xs/gsim/gsim-compile/model/SimTop2.cpp`
- `grhsim`
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_308.cpp`
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_0.cpp`
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_925.cpp`

对应函数：

| 类型 | 样本函数 | 选择理由 |
| --- | --- | --- |
| `gsim` | `SSimTop::subStep318()` | 较大的 runtime `subStep` 样本 |
| `gsim` | `SSimTop::subStep21()` | 大 `subStep` 样本 |
| `gsim` | `SSimTop::subStep0()` | 中大型 `subStep` 样本 |
| `grhsim` | `GrhSIM_SimTop::eval_compute_batch_308()` | 之前记录过编译热点的 compute batch，函数较大 |
| `grhsim` | `GrhSIM_SimTop::eval_compute_batch_0()` | 普通 compute batch，能看到高密度 slot 访问 |
| `grhsim` | `GrhSIM_SimTop::eval_commit_batch_925()` | commit batch，对照 compute batch |

## 3. 复现命令

本轮先分析 emu 构建产生的真实 `.o`，再将同一源文件按原编译口径单独重编译到 `/tmp/grhsim_static_sample` 交叉验证。

`grhsim` 样本重编译：

```bash
cd build/xs/grhsim/grhsim_emit
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch \
  -c grhsim_SimTop_sched_308.cpp -o /tmp/grhsim_static_sample/grhsim_SimTop_sched_308.o
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch \
  -c grhsim_SimTop_sched_0.cpp -o /tmp/grhsim_static_sample/grhsim_SimTop_sched_0.o
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch \
  -c grhsim_SimTop_sched_925.cpp -o /tmp/grhsim_static_sample/grhsim_SimTop_sched_925.o
```

`gsim` 样本重编译使用实际构建所需 include / define，核心参数为：

```bash
clang++ build/xs/gsim/gsim-compile/model/SimTop320.cpp \
  -Itestcase/xiangshan/difftest/src/test/csrc/common \
  -Itestcase/xiangshan/difftest/config \
  -DNOOP_HOME=\"/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan\" \
  -Itestcase/xiangshan/build/generated-src \
  -Itestcase/xiangshan/difftest/src/test/csrc/plugin/include \
  -DNUM_CORES=1 \
  -Itestcase/xiangshan/difftest/src/test/csrc/difftest \
  -Ibuild/xs/gsim \
  -Itestcase/xiangshan/difftest/src/test/csrc/plugin/spikedasm \
  -Itestcase/xiangshan/difftest/src/test/csrc/emu \
  -DEMU_THREAD=1 \
  -Itestcase/xiangshan/difftest/src/test/csrc/gsim \
  -Ibuild/xs/gsim/gsim-compile/model \
  -Ireference/gsim/include \
  -DGSIM -O3 -fbracket-depth=2048 -Wno-parentheses-equality \
  -c -o /tmp/grhsim_static_sample/SimTop320.o
```

`SimTop23.cpp` / `SimTop2.cpp` 同口径替换输入输出文件。

统计方法：

- `nm -C --size-sort` 取函数 text size；
- `objdump -d -C --disassemble=<symbol>` 取汇编；
- 简单解析指令行，统计：
  - 总指令数；
  - `j*` 分支/跳转；
  - `call*`；
  - `ret*`；
  - operand 中带 `(...)` 的 memory-operand 指令。

重编译对象和原 emu 对象统计完全一致，因此下面数据可视为当前 O3 机器码形态。

## 4. C++ 形态差异

### 4.1 `gsim subStep`

`gsim` 的典型结构：

```cpp
if(unlikely(activeFlags[word] != 0)) {
  uint8_t oldFlag = activeFlags[word];
  activeFlags[word] = 0;
  if(unlikely(oldFlag & mask)) {
    // optional runtime profile weight accumulation
    // local SSA-like temporaries
    // direct scalar computation
    // on value changed, update activeFlags[...] directly
  }
}
```

特点：

- active flag 按 byte array 组织；
- 命中一个 supernode 后，多数计算以局部临时变量和对象字段直接表达；
- value changed 时直接更新目标 `activeFlags[...]`；
- 生成代码仍很大，但每个 active 分支内部更接近“直接 RTL 表达式展开”。

### 4.2 `grhsim compute batch`

`grhsim` 的典型 compute supernode 分支：

```cpp
if (unlikely(activeWordFlags & UINT8_C(1))) {
  activeWordFlags &= ~UINT8_C(1);
  if (runtime_profile_enabled_) {
    ++runtime_profile_active_supernodes_;
    ++runtime_profile_compute_supernodes_;
    runtime_profile_compute_nodes_ += 16;
    runtime_profile_compute_ops_ += 25;
  }
  {
    auto &dst = value_bool_slots_[538255];
    const auto next_value = static_cast<bool>(src0 && value_bool_slots_[202254]);
    if (dst != next_value) {
      supernode_active_curr_[5654u] |= UINT8_C(8);
      dst = next_value;
    }
  }
}
```

特点：

- 每个 op 基本都经过 `slot load -> next_value -> compare old/new -> conditional activation store -> value slot store`；
- source / destination 多数是 `value_*_slots_[index]`，编译后更容易保留为内存访问；
- 一个 op 可能写多个 `supernode_active_curr_[] |= mask`；
- compute batch 同时承担 active word 派发、runtime profile 计数、value 更新、activation propagation。

### 4.3 初步判断

`grhsim` 的单位 op 更贵，直观上不是因为单个逻辑表达式更复杂，而是因为每个 op 附带了更多通用 runtime 语义：

- old/new compare；
- value slot load/store；
- activation bitset OR store；
- active word dispatch bookkeeping；
- runtime profile weight accumulation；
- 对宽值还会进入 `std::array<unsigned long, N>` helper。

这解释了为什么 `NO0077` 中 total op solves 较少，host time 仍显著更高。

## 5. 汇编静态采样

对 6 个样本函数的重编译对象做统计：

| kind | sample | text bytes | instructions | branch/jump | calls | ret | mem-operand instr | mem instr / inst |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gsim` | `subStep318` | `562887` | `100215` | `1542` | `92` | `1` | `59770` | `0.596` |
| `gsim` | `subStep21` | `456562` | `82860` | `3698` | `0` | `1` | `53382` | `0.644` |
| `gsim` | `subStep0` | `315759` | `56529` | `2637` | `9` | `1` | `36652` | `0.648` |
| `grhsim` | `compute_batch_308` | `190308` | `37579` | `2989` | `6` | `1` | `22566` | `0.600` |
| `grhsim` | `compute_batch_0` | `76592` | `12663` | `2895` | `20` | `1` | `11572` | `0.914` |
| `grhsim` | `commit_batch_925` | `44016` | `9144` | `785` | `0` | `2` | `5382` | `0.589` |

几个直接观察：

1. `compute_batch_0` 的 memory-operand 指令占比达到 `0.914`。
   - 这远高于 `gsim` 样本的 `0.596~0.648`；
   - 说明普通 compute batch 中，slot load/store 和 active bitset 更新高度密集。

2. `compute_batch_0` 的 branch/jump 数为 `2895`，但总指令只有 `12663`。
   - 分支密度约 `22.9%`；
   - `gsim subStep318` 分支密度约 `1.5%`，`subStep21` 约 `4.5%`，`subStep0` 约 `4.7%`。

3. `compute_batch_308` 的 mem 指令占比没有异常高，但 branch/jump 数仍有 `2989`。
   - 这类大 batch 更像大块 active-word dispatch + 多个 value update block；
   - 不一定每个样本都表现为高 mem 指令占比，但分支/dispatch 结构仍明显重。

4. commit batch 的单函数规模较小，mem 占比接近 `gsim`，但它对应 `NO0077` 中 `34.35%` 的 supernode 激活和 `28.86%` 的 sink op solves，仍需要动态拆 register/latch/memory write 成本。

## 6. 全量函数尺寸分布

进一步统计所有生成函数：

| group | count | total text bytes | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gsim subStep` | `332` | `55118088` | `166018.3` | `148813.5` | `281457` | `458835` | `633482` |
| `grhsim compute batch` | `862` | `120078436` | `139302.1` | `126464.5` | `212827` | `413669` | `4884002` |
| `grhsim commit batch` | `609` | `17504521` | `28743.1` | `26947.0` | `44008` | `54600` | `67196` |

这里有两个关键点：

- `grhsim compute batch` 总 text bytes 是 `gsim subStep` 的 `2.18x`：
  - `120078436 / 55118088 = 2.18`
- `grhsim compute batch` 有一个极端最大函数 `4884002` bytes：
  - 约 `4.88 MB` 单函数 text；
  - 这会显著增加 i-cache / iTLB / branch target 压力。

这和 `NO0077` 的 runtime profile 可以拼起来看：

- `grhsim` total op solves 更少；
- 但生成机器码总量更大，函数更多；
- 每个 op 周围附带更多 slot 访问、分支、activation propagation；
- 因此单位 op solve 成本高是合理的，不再是一个纯 runtime 计数无法解释的现象。

## 7. 当前结论

本轮静态采样支持以下判断：

1. `grhsim` 单位 op 成本高，主要来自生成代码形态，而不是纯 op 数量。
   - `grhsim` op 不是简单“表达式求值”；
   - 它通常包含 value slot old/new 比较、条件激活、slot 写回和 active bitset 更新。

2. `grhsim compute batch` 的机器码更偏 memory / branch heavy。
   - 典型普通 compute batch 样本 `compute_batch_0` 的 mem-operand 指令占比为 `0.914`；
   - 分支密度也明显高于 gsim 大样本。

3. `grhsim` 的 compute 代码体量明显更大。
   - compute batch 总 text `120 MB`，是 gsim subStep 总 text `55 MB` 的 `2.18x`；
   - 极端大函数 `4.88 MB` 会带来前端取指和分支预测压力。

4. `active supernode` 多 `1.879x` 是放大器，不是唯一主因。
   - 如果每次 active 都进入更 memory-heavy / branch-heavy 的 per-op 更新框架，`1.879x` 激活放大和 `13.557x` 单位 solve 成本可以共同解释 `8.467x` host time。

## 8. 下一步建议

下一步应做动态采样来把静态结论落到真实热点：

- 对 `grhsim-compile/emu` 跑 `perf record`，查看 samples 是否集中在：
  - `GrhSIM_SimTop::eval_compute_batch_*`
  - `value_*_slots_` load/store 附近；
  - `supernode_active_curr_[] |= mask`；
  - 宽值 helper，例如 `grhsim_assign_words` / `grhsim_slice_words` / `grhsim_concat_*`。
- 临时加一个更细 runtime profile：
  - compute batch active 次数分布；
  - commit batch active 次数分布；
  - supernode 内 op count bucket；
  - activation store 次数；
  - value changed / value evaluated 比例。
- 针对 emitter 做两类实验：
  - 对 bool/scalar fast path，尝试把多 op 的 value changed aggregation 合并，减少 per-op branch 和 `supernode_active_curr_` store；
  - 对 compute node 内部局部值，尽量避免所有中间值落入 `value_*_slots_`，让编译器保留寄存器 SSA 形态。

一句话结论：`NO0077` 指出主要矛盾是单位 op 成本；本轮静态采样进一步把它落到代码形态上：`grhsim` 当前每个 op 附带的 value slot 访问、old/new 比较、activation bitset 写入和 batch 调度分支过重，最终机器码呈现更高的分支/访存密度和更大的 compute text footprint。

## 9. 增量更新 2026-05-09：固定随机种子 20 样本复核

上面的 6 个样本只能证明存在具体形态，不能代表整体分布。因此追加一轮固定随机种子的扩展采样：

- 随机种子：`20260509`
- `gsim subStep`：从全部 `332` 个 `SSimTop::subStep*()` 中随机抽 `20` 个
- `grhsim compute batch`：从全部 `862` 个 `eval_compute_batch_*()` 中随机抽 `20` 个
- `grhsim commit batch`：从全部 `609` 个 `eval_commit_batch_*()` 中随机抽 `20` 个
- 统计脚本输出保存到 `/tmp/grhsim_static_sample/random20_stats.json`

统计口径仍为：

- `nm -C --size-sort` 取 text bytes；
- `objdump -d -C --disassemble=<symbol>` 取函数汇编；
- 统计总指令数、分支/跳转数、call 数、memory-operand 指令数；
- `branch_density = branches / instructions`
- `mem_density = memops / instructions`

### 9.1 汇总分布

#### `gsim subStep` 随机 20 个

| metric | mean | median | p90 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| size | `175123.8` | `138926.0` | `281457.0` | `47132.0` | `456562.0` |
| instructions | `34544.7` | `28188.0` | `54070.0` | `10238.0` | `82860.0` |
| branches | `1632.8` | `1481.0` | `3698.0` | `234.0` | `4076.0` |
| branch_density | `0.0440` | `0.0443` | `0.0696` | `0.0106` | `0.0825` |
| memops | `17539.0` | `13456.5` | `29058.0` | `3401.0` | `53382.0` |
| mem_density | `0.4769` | `0.4863` | `0.5719` | `0.3306` | `0.6442` |
| calls | `80.2` | `20.0` | `274.0` | `0.0` | `438.0` |

#### `grhsim compute batch` 随机 20 个

| metric | mean | median | p90 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| size | `128437.7` | `119136.0` | `173835.0` | `50139.0` | `315472.0` |
| instructions | `25024.0` | `23157.5` | `36042.0` | `10676.0` | `44908.0` |
| branches | `2571.4` | `2956.0` | `4345.0` | `87.0` | `5133.0` |
| branch_density | `0.0957` | `0.0882` | `0.1415` | `0.0081` | `0.1958` |
| memops | `15473.3` | `15166.0` | `20825.0` | `3618.0` | `37351.0` |
| mem_density | `0.5959` | `0.6083` | `0.7216` | `0.3389` | `0.8317` |
| calls | `23.4` | `6.0` | `70.0` | `0.0` | `100.0` |

#### `grhsim commit batch` 随机 20 个

| metric | mean | median | p90 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| size | `27494.7` | `25184.0` | `43503.0` | `113.0` | `67196.0` |
| instructions | `5540.4` | `5092.5` | `8847.0` | `27.0` | `14359.0` |
| branches | `799.1` | `725.0` | `1350.0` | `5.0` | `2307.0` |
| branch_density | `0.1412` | `0.1416` | `0.1661` | `0.0825` | `0.1852` |
| memops | `3855.6` | `3589.5` | `6867.0` | `21.0` | `9725.0` |
| mem_density | `0.6984` | `0.6816` | `0.7996` | `0.6033` | `0.8181` |
| calls | `43.3` | `0.0` | `36.0` | `0.0` | `768.0` |

### 9.2 随机样本列表

#### `gsim subStep`

| symbol | text bytes | inst | branches | branch density | memops | mem density |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `SSimTop::subStep98()` | `255701` | `49398` | `4076` | `0.0825` | `27030` | `0.5472` |
| `SSimTop::subStep21()` | `456562` | `82860` | `3698` | `0.0446` | `53382` | `0.6442` |
| `SSimTop::subStep214()` | `154366` | `29689` | `1597` | `0.0538` | `17086` | `0.5755` |
| `SSimTop::subStep115()` | `167131` | `32291` | `1527` | `0.0473` | `17404` | `0.5390` |
| `SSimTop::subStep140()` | `131612` | `25530` | `1125` | `0.0441` | `9377` | `0.3673` |
| `SSimTop::subStep53()` | `98950` | `21324` | `580` | `0.0272` | `8286` | `0.3886` |
| `SSimTop::subStep163()` | `166088` | `32695` | `2346` | `0.0718` | `16845` | `0.5152` |
| `SSimTop::subStep73()` | `121218` | `27564` | `291` | `0.0106` | `9576` | `0.3474` |
| `SSimTop::subStep56()` | `57642` | `13038` | `266` | `0.0204` | `4311` | `0.3306` |
| `SSimTop::subStep176()` | `133786` | `27698` | `408` | `0.0147` | `11873` | `0.4287` |
| `SSimTop::subStep96()` | `281457` | `54070` | `3765` | `0.0696` | `30630` | `0.5665` |
| `SSimTop::subStep179()` | `128539` | `24446` | `931` | `0.0381` | `13419` | `0.5489` |
| `SSimTop::subStep44()` | `47132` | `10238` | `234` | `0.0229` | `3401` | `0.3322` |
| `SSimTop::subStep15()` | `266855` | `50812` | `2360` | `0.0464` | `29058` | `0.5719` |
| `SSimTop::subStep38()` | `207405` | `40461` | `1402` | `0.0347` | `21310` | `0.5267` |
| `SSimTop::subStep120()` | `294086` | `59895` | `2146` | `0.0358` | `27585` | `0.4606` |
| `SSimTop::subStep327()` | `128719` | `27892` | `1634` | `0.0586` | `12298` | `0.4409` |
| `SSimTop::subStep306()` | `136680` | `28484` | `1819` | `0.0639` | `13494` | `0.4737` |
| `SSimTop::subStep241()` | `141172` | `27238` | `1017` | `0.0373` | `11808` | `0.4335` |
| `SSimTop::subStep168()` | `127374` | `25270` | `1435` | `0.0568` | `12607` | `0.4989` |

#### `grhsim compute batch`

| symbol | text bytes | inst | branches | branch density | memops | mem density |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `GrhSIM_SimTop::eval_compute_batch_542()` | `118166` | `20445` | `237` | `0.0116` | `12117` | `0.5927` |
| `GrhSIM_SimTop::eval_compute_batch_326()` | `173835` | `32978` | `4135` | `0.1254` | `19922` | `0.6041` |
| `GrhSIM_SimTop::eval_compute_batch_833()` | `92776` | `22193` | `4345` | `0.1958` | `13051` | `0.5881` |
| `GrhSIM_SimTop::eval_compute_batch_24()` | `124167` | `22868` | `3111` | `0.1360` | `15826` | `0.6921` |
| `GrhSIM_SimTop::eval_compute_batch_629()` | `65320` | `14543` | `852` | `0.0586` | `5673` | `0.3901` |
| `GrhSIM_SimTop::eval_compute_batch_146()` | `76729` | `16114` | `972` | `0.0603` | `6540` | `0.4059` |
| `GrhSIM_SimTop::eval_compute_batch_382()` | `162841` | `36042` | `3007` | `0.0834` | `19687` | `0.5462` |
| `GrhSIM_SimTop::eval_compute_batch_369()` | `137461` | `29098` | `2707` | `0.0930` | `16723` | `0.5747` |
| `GrhSIM_SimTop::eval_compute_batch_390()` | `66439` | `14639` | `698` | `0.0477` | `8965` | `0.6124` |
| `GrhSIM_SimTop::eval_compute_batch_339()` | `205726` | `38645` | `5133` | `0.1328` | `27403` | `0.7091` |
| `GrhSIM_SimTop::eval_compute_batch_802()` | `170533` | `32732` | `4631` | `0.1415` | `20825` | `0.6362` |
| `GrhSIM_SimTop::eval_compute_batch_605()` | `108412` | `21820` | `2924` | `0.1340` | `16344` | `0.7490` |
| `GrhSIM_SimTop::eval_compute_batch_135()` | `135777` | `25920` | `4123` | `0.1591` | `17937` | `0.6920` |
| `GrhSIM_SimTop::eval_compute_batch_676()` | `120106` | `25813` | `2127` | `0.0824` | `12983` | `0.5030` |
| `GrhSIM_SimTop::eval_compute_batch_152()` | `50139` | `10676` | `87` | `0.0081` | `3618` | `0.3389` |
| `GrhSIM_SimTop::eval_compute_batch_684()` | `61234` | `11880` | `624` | `0.0525` | `8573` | `0.7216` |
| `GrhSIM_SimTop::eval_compute_batch_656()` | `110070` | `23447` | `1599` | `0.0682` | `10611` | `0.4526` |
| `GrhSIM_SimTop::eval_compute_batch_531()` | `115794` | `21835` | `2988` | `0.1368` | `14506` | `0.6643` |
| `GrhSIM_SimTop::eval_compute_batch_819()` | `315472` | `44908` | `3289` | `0.0732` | `37351` | `0.8317` |
| `GrhSIM_SimTop::eval_compute_batch_677()` | `157757` | `33884` | `3840` | `0.1133` | `20811` | `0.6142` |

#### `grhsim commit batch`

| symbol | text bytes | inst | branches | branch density | memops | mem density |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `GrhSIM_SimTop::eval_commit_batch_1347()` | `42309` | `8465` | `1540` | `0.1819` | `6925` | `0.8181` |
| `GrhSIM_SimTop::eval_commit_batch_1194()` | `27559` | `5528` | `709` | `0.1283` | `3775` | `0.6829` |
| `GrhSIM_SimTop::eval_commit_batch_1189()` | `26158` | `5392` | `717` | `0.1330` | `3374` | `0.6257` |
| `GrhSIM_SimTop::eval_commit_batch_1408()` | `6108` | `1184` | `161` | `0.1360` | `899` | `0.7593` |
| `GrhSIM_SimTop::eval_commit_batch_1183()` | `10605` | `2178` | `245` | `0.1125` | `1314` | `0.6033` |
| `GrhSIM_SimTop::eval_commit_batch_1376()` | `28614` | `5777` | `809` | `0.1400` | `3896` | `0.6744` |
| `GrhSIM_SimTop::eval_commit_batch_1238()` | `67196` | `14359` | `2307` | `0.1607` | `9725` | `0.6773` |
| `GrhSIM_SimTop::eval_commit_batch_1371()` | `113` | `27` | `5` | `0.1852` | `21` | `0.7778` |
| `GrhSIM_SimTop::eval_commit_batch_902()` | `30136` | `6138` | `940` | `0.1531` | `4040` | `0.6582` |
| `GrhSIM_SimTop::eval_commit_batch_1293()` | `25947` | `5155` | `738` | `0.1432` | `3651` | `0.7082` |
| `GrhSIM_SimTop::eval_commit_batch_911()` | `49651` | `10056` | `1350` | `0.1342` | `6867` | `0.6829` |
| `GrhSIM_SimTop::eval_commit_batch_1141()` | `16013` | `3317` | `372` | `0.1121` | `2030` | `0.6120` |
| `GrhSIM_SimTop::eval_commit_batch_1444()` | `24421` | `4676` | `386` | `0.0825` | `3038` | `0.6497` |
| `GrhSIM_SimTop::eval_commit_batch_945()` | `23499` | `4412` | `733` | `0.1661` | `3528` | `0.7996` |
| `GrhSIM_SimTop::eval_commit_batch_1109()` | `21910` | `4324` | `496` | `0.1147` | `2942` | `0.6804` |
| `GrhSIM_SimTop::eval_commit_batch_1380()` | `43503` | `8847` | `1273` | `0.1439` | `5834` | `0.6594` |
| `GrhSIM_SimTop::eval_commit_batch_1147()` | `39549` | `7709` | `1275` | `0.1654` | `5640` | `0.7316` |
| `GrhSIM_SimTop::eval_commit_batch_1111()` | `24377` | `5030` | `789` | `0.1569` | `3681` | `0.7318` |
| `GrhSIM_SimTop::eval_commit_batch_964()` | `22997` | `4268` | `683` | `0.1600` | `3415` | `0.8001` |
| `GrhSIM_SimTop::eval_commit_batch_1257()` | `19228` | `3967` | `455` | `0.1147` | `2516` | `0.6342` |

### 9.3 对原结论的修正

这轮 20 样本复核后，需要把原先基于 `compute_batch_0` 的表述收敛得更准确：

1. `compute_batch_0` 的 `mem_density=0.914` 是极端样本，不能代表所有 compute batch。
   - 随机 20 个 `grhsim compute batch` 的 `mem_density` 均值是 `0.5959`，中位数 `0.6083`；
   - 这仍高于 `gsim subStep` 随机 20 个的均值 `0.4769`、中位数 `0.4863`，但不是“普遍接近 0.9”。

2. 更稳定的整体差异是分支密度。
   - `gsim subStep` 随机样本 `branch_density` 均值 `0.0440`；
   - `grhsim compute batch` 均值 `0.0957`，约 `2.18x`；
   - `grhsim commit batch` 均值 `0.1412`，约 `3.21x`。

3. `grhsim commit batch` 不能忽略。
   - `NO0077` 中 commit supernode activation 占 `34.35%`；
   - 本轮随机 commit batch 的 `branch_density` / `mem_density` 都高于 compute batch；
   - 后续拆单位成本时，commit 路径需要单独分析 register/latch/memory write 和 difftest/system task。

4. 全量 text footprint 结论仍保留。
   - `grhsim compute batch` 总 text bytes 仍是 `gsim subStep` 的 `2.18x`；
   - 这不是由 6 个样本决定，而是全量函数尺寸统计。

修正后的结论是：

- `grhsim` 的单位 op 成本更高，不应只归因于单个样本中的超高 memory density；
- 更稳的证据链是：
  - `grhsim` compute/commit 代码形态包含 old/new compare、activation store、slot writeback；
  - 随机样本显示 `grhsim compute` 分支密度约为 `gsim` 的 `2.18x`；
  - `grhsim commit` 分支密度约为 `gsim` 的 `3.21x`，且 mem density 也更高；
  - 全量 `grhsim compute` text footprint 是 `gsim subStep` 的 `2.18x`；
  - 这些前端/分支/访存成本叠加 `1.879x` active supernode 放大，才是解释 `NO0077` 中单位 op 成本异常的主要方向。
