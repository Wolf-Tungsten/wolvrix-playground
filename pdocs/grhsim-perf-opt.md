# GrhSIM XiangShan 性能优化 Checklist

更新时间：`2026-04-18`

本文只关注 `grhsim` 在 XiangShan 上的运行时性能，不讨论功能正确性问题。

## 1. 当前判断

- 当前性能瓶颈不在外层 `active-word` 扫描，而在被激活后的 `eval_batch_*` / supernode 本体执行成本。
- `grhsim` 的活动调度外形已经和 `gsim` 同类：
  - `grhsim`：`kSupernodeCount = 84314`，`kActiveFlagWordCount = 10540`，见 `build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp`
  - `gsim`：`131580 superNodes`，`activeFlags[16448]`，见 `tmp/gsim_default_xiangshan/gsim.log` 和 `tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h`
- 但不能把 `grhsim op` 和 `gsim node` 直接对齐比较。
- 当前更可靠的判断方式，是比较两边生成代码的体量、激活传播形态、值访问形态，以及 `grhsim` 自身 supernode body 的静态复杂度。

## 2. 量化对比

### 2.1 生成源码规模

- `grhsim`
  - 源码文件数：`10543`
  - 其中 `sched cpp`：`10540`
  - 源码总大小：`2454130926` bytes，约 `2.45 GB`
  - 源码总行数：`32553560`
- `gsim`
  - 源码文件数：`168`
  - 其中 `cpp`：`167`
  - 源码总大小：`1668022994` bytes，约 `1.67 GB`
  - 源码总行数：`10623792`

结论：

- `grhsim` 文件数约为 `gsim` 的 `62.8x`
- `grhsim` 源码总行数约为 `gsim` 的 `3.06x`
- `grhsim` 源码总大小约为 `gsim` 的 `1.47x`

### 2.2 可直接对齐的调度规模

- `grhsim`
  - supernode 数：`84314`
  - batch / active-word 数：`10540`
- `gsim`
  - supernode 数：`131580`
  - active-word 数：`16448`
  - 数据来源：`tmp/gsim_default_xiangshan/gsim.log` 和 `tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h`

结论：

- `grhsim` supernode 数比 `gsim` 更少，不是“supernode 太多导致调度慢”
- 但这里不能继续推出“`grhsim` 每个 supernode 比 `gsim` 重多少”，因为两边内部基本单元语义不同

### 2.3 不可直接对齐但和性能有关的内部口径

- `grhsim`
  - supernode 内 op 统计：
    - 平均：`64.80`
    - 中位数：`71`
    - 最大：`72`
  - 数据来源：`build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`
- `gsim`
  - `node` 统计来自 `gsim` 自己的图模型
  - 从语义上更接近“值图 / 表达式树中的节点”或一部分 declared-symbol 级工作量
  - 不能直接等同于 `grhsim` 的组合逻辑 `op`

结论：

- `grhsim op` 与 `gsim node` 不能做直接数量对比
- 后续性能分析中，`grhsim` 侧仍可用 `op/supernode` 作为“自身复杂度”指标
- 但不要再用 `gsim node/supernode` 去做横向结论

### 2.4 热路径相关的 emitted 工作量

- `grhsim`
  - `// op _op_` 总数：`5463193`
  - `// Supernode` 总数：`84314`
  - `supernode_active_curr_[...] |= ...` 次数：`2456863`
  - `value_*_slots_[]` 引用次数：`12923765`
  - `state_*_slots_[]` 引用次数：`1454252`
  - `local_value_...` 引用次数：`10818947`
  - `symbol=` 条目数：`892104`
- `gsim`
  - `activeFlags[...] |= ...` 字节级写回：`477064`
  - 宽激活写回：
    - `uint16_t` 打包：`4106`
    - `uint32_t` 打包：`14258`
    - `uint64_t` 打包：`62773`
  - `member` 声明数：`333768`

结论：

- `grhsim` 在热路径里仍然有大量 slot 访问
- `gsim` 会大量使用宽掩码合并激活写回，`grhsim` 目前基本还是单字节 OR
- 这两点已经足以解释一部分运行时差距，不需要依赖 `op`/`node` 的直接对齐

### 2.5 eval 静态读写/激活统计

这一轮专门统计了 `eval` 路径中展开出来的“读 / 写 / 激活”动作次数。

说明：

- 这是静态 emitted cpp 口径，不是运行时采样。
- `grhsim` 与 `gsim` 语义仍不完全一致，因此这里只比较“代码形态上的热路径动作量”。

#### GrhSIM 计数口径

统计范围：

- `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_*.cpp`
- `build/xs/grhsim/grhsim_emit/grhsim_SimTop_eval.cpp`

口径：

- `读 slot`
  - 所有 `value_*_slots_[` / `state_*_slots_[` / `state_shadow_*_slots_[` / `state_mem_*_slots_[` / `event_edge_slots_[` 的引用次数
  - 再减去其中作为赋值左值的次数
- `写 slot`
  - 上述 slot 出现在左值赋值 `... =` 的次数
- `激活`
  - `supernode_active_curr_[...] |= ...` 次数

结果：

- 总 slot 引用数：`14378017`
- 读 slot：`12767753`
- 写 slot：`1610264`
- 激活写回：`2456863`

#### GSim 计数口径

统计范围：

- `tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop*.cpp`

口径：

- `gsim` 的 `Node` 语义和 `grhsim op` 不同，emitted cpp 中也没有直接保留 `Node` 类型标记
- 因此这里采用 `node-like name` 代理口径：
  - 统计所有带 `$` 的生成硬件名
  - 排除明显的局部历史临时 `...$old$...`
- `读 node-like`
  - 这些名字的总引用次数减去直接赋值左值次数
- `写 node-like`
  - 直接赋值到这类名字的次数
- `激活`
  - `activeFlags[...] |= ...`
  - 以及 `*(uint16_t/32_t/64_t*)&activeFlags[...] |= ...`

结果：

- 总 node-like 引用数：`13210981`
- 读 node-like：`11147230`
- 写 node-like：`2063751`
- 激活写回：`558201`

#### 结论

- 读量
  - `grhsim`：`12767753`
  - `gsim`：`11147230`
  - `grhsim` 约高 `14.5%`
- 写量
  - `grhsim`：`1610264`
  - `gsim`：`2063751`
  - 这个口径下 `gsim` 更高
  - 这不代表 `gsim` 更慢，因为两边写入对象语义不同
- 激活写回
  - `grhsim`：`2456863`
  - `gsim`：`558201`
  - `grhsim` 约为 `4.40x`

这一轮最重要的结论：

- 当前最显著的差异不是“读得多很多”或“写得多很多”
- 而是 `grhsim` 的激活传播明显更碎，激活写回次数远高于 `gsim`
- 因此后续性能优化中，合并激活写回仍然是第一梯队目标

## 3. 对性能的解释

### 3.1 外层调度不是主矛盾

- `grhsim` 已经使用 `uint8_t` 活动字数组：
  - `std::array<std::uint8_t, kActiveFlagWordCount> supernode_active_curr_{}`
- `gsim` 也是：
  - `uint8_t activeFlags[16448]`
- 所以当前数量级差距不能主要归咎于“外层调度框架不同”

### 3.2 主矛盾是 supernode body 太重

- `grhsim` 的典型模式是：
  - 从 `value_*_slots_[]` / `state_*_slots_[]` 读值
  - 做 `if (old != new)` 检查
  - 对一个或多个 `supernode_active_curr_[word] |= mask`
  - 回写 slot
- `gsim` 的典型模式是：
  - 直接操作 member / `$NEXT` / `$old`
  - 用局部临时拼接组合逻辑
  - 用宽位掩码批量激活后继

结论：

- `grhsim` 每次进入 active supernode 后，CPU 执行的分支、load/store、索引寻址都更多
- 这比“扫多少个 active-word”更影响 `eval()` 延迟

### 3.3 当前 emitter 已经暴露出的三个结构性问题

- supernode 内 materialized op 过多
  - 当前平均 `64.8 op/supernode`
  - 这是 `grhsim` 自身的复杂度指标，不和 `gsim node` 直接比较
- 激活传播太碎
  - `grhsim`：约 `245.7 万` 次字节级 `|=`
  - `gsim`：除了 `47.7 万` 次字节级 `|=`，还有大量 `u16/u32/u64` 合并写回
  - 从静态 `eval` 读写统计看，`grhsim` 激活写回约为 `gsim` 的 `4.40x`
- 值池访问仍然过重
  - `value_*_slots_[]` 引用 `1292 万+`
  - `local_value_...` 虽然很多，但仍未替代大量全局池访问

## 4. 优先级 Checklist

下面按“对单次 `eval` 预期收益”排序。

### P0. 压缩 supernode 内部的 materialized op 数

目标：

- 让一个 active supernode 进入后，执行的基础动作数量显著下降

现状证据：

- `grhsim` 自身当前为 `5463193 op / 84314 supernode = 64.80 op/supernode`
- 这说明当前一个 active supernode 内部平均要执行的组合逻辑动作仍然很多
- 这里不再使用 `gsim node/supernode` 作为横向证据，因为语义不一致

Checklist：

- [ ] 继续扩大 same-supernode 内局部 SSA 化覆盖面
- [ ] 能不 materialize 到 `value_*_slots_[]` 的中间值尽量不 materialize
- [ ] 优先消灭只被同一 supernode 内后继消费的单次中间值
- [ ] 优先消灭 trivial unary / binary / compare / cast / concat / slice 中的“池化但立刻再读”模式
- [ ] 对宽位拼接、切片、拼位等热点模板，优先做 emitter 级直出优化，而不是增加 helper 层次

判定标准：

- [ ] emitted `// op` 总数明显下降
- [ ] `value_*_slots_[]` 引用次数明显下降
- [ ] `eval_batch_*` 自身耗时下降

### P1. 合并激活传播写回

目标：

- 降低热路径上的 `supernode_active_curr_[...] |= ...` 次数

现状证据：

- `grhsim`：`2456863` 次字节级激活写回
- `gsim`：存在 `u16/u32/u64` 批量 OR

Checklist：

- [ ] 同一 op 触发到同一 active-word 的多个 mask 先在 emitter 侧合并
- [ ] 同一 supernode 内连续对相邻 active-word 的写回，尽量生成宽位 OR
- [ ] 优先对 fanout 高、模板重复强的传播模式做聚合
- [ ] 保证不破坏当前 topo 顺序和本轮激活语义

判定标准：

- [ ] `supernode_active_curr_[...] |= ...` 次数下降
- [ ] 出现 `u16/u32/u64` 级别的批量写回
- [ ] `eval_batch_*` 热点样本中的 store / branch 数下降

### P2. 减少值池访问

目标：

- 降低 `value_*_slots_[]` 和 `state_*_slots_[]` 的索引读写压力

现状证据：

- `value_*_slots_[]` 引用 `12923765`
- `state_*_slots_[]` 引用 `1454252`

Checklist：

- [ ] same-supernode temporary value 默认改为局部变量，不落池
- [ ] 仅对跨 supernode、跨 commit、跨 side-effect 边界的值保留池化
- [ ] 对只读一次的 materialized 值做 late rematerialize
- [ ] 对 state-read 后紧邻使用的模式，尽量变成局部快路径

判定标准：

- [ ] `value_*_slots_[]` 引用次数下降
- [ ] `eval_batch_*` 的 load 指令占比下降

### P3. 让超节点内部更接近 gsim 的“直接 member + old/next”风格

目标：

- 降低池化抽象带来的索引和中转成本

说明：

- 这不是要求完全回退到 `gsim` 的 per-member 存储
- 而是要求在 supernode 本体内部，代码形态尽量像 `gsim`

Checklist：

- [ ] 对 supernode 内部局部依赖链，优先生成本地变量链
- [ ] 对 change-detect 模式，减少多余的中转 slot
- [ ] 对简单 bool/u8/u16/u32/u64 路径，优先生成直读直写模板

### P4. 针对高重复模板做 emitter 专项压缩

目标：

- 不追单个“巨热 batch”，而是优化一整类重复结构

Checklist：

- [ ] 统计最常见的 emitted op 模板
- [ ] 按模板族优化，而不是按某个 batch 编号优化
- [ ] 特别关注 sink-heavy / state-update-heavy 模式
- [ ] 特别关注宽位 concat / slice / pack / compare 模式

## 5. 暂不作为主攻方向的事项

下面这些不是没价值，而是当前不是第一优先级。

- [ ] 继续优化 active-word 外层扫描
  - 原因：当前证据表明外层框架不是主瓶颈
- [ ] 继续压 supernode 数量
  - 原因：`grhsim` supernode 数已经少于 `gsim`
  - 当前问题是每个 supernode 太重
- [ ] 单纯继续拆更多 cpp 文件
  - 原因：这主要改善编译，不直接改善运行时 `eval`
- [ ] 继续堆 runtime helper 封装
  - 原因：之前经验表明热路径 helper 化容易引入额外开销

## 6. 每轮优化后的复测项

每次性能改动后，至少复测以下内容：

- [ ] `grhsim` emitted `// op` 总数
- [ ] `supernode_active_curr_[...] |= ...` 次数
- [ ] `value_*_slots_[]` 引用次数
- [ ] `eval_batch_*` 自身采样占比
- [ ] `commit_state_shadow_chunk_*` 占比
- [ ] `1000` 周期和 `10000` 周期下的平均 host time / eval

建议统一记录格式：

- emit 规模
  - supernode 数
  - emitted op 数
  - 激活写回次数
  - 值池访问次数
- 运行时
  - `ms / eval`
  - `ms / cycle`
  - `perf report` top buckets

## 7. 当前建议路线

建议执行顺序：

- [ ] 第一步：继续做 same-supernode 中间值局部化，压 `materialized op`
- [ ] 第二步：做激活写回聚合，向 `gsim` 的宽 OR 形式靠拢
- [ ] 第三步：按高频模板族继续压 `value_*_slots_[]` 访问
- [ ] 第四步：再做一次 XiangShan `perf`，确认 `eval_batch_*` 是否出现明显回落

一句话总结：

- 当前 `grhsim` 慢，不是因为“调度框架不对”，而是因为“一个被激活的 supernode 里要做的事情太多，而且太碎”。

## 8. 2026-04-18 阶段记录

本阶段完成了一个新的 emitter 级 I-cache 优化，并完成了对应的功能回归排查与性能复测。

### 8.1 本阶段变更

- 在 `wolvrix/lib/emit/grhsim_cpp.cpp` 中，为连续的 scalar state write run 新增了 arithmetic range 压缩：
  - 生成 `scalar_state_write_*_range_desc`
  - 生成 `apply_scalar_state_write_*_range(...)`
  - 对长度至少为 `4` 的等差连续写序列，用一条 range helper 调用替代逐 op 展开
- XiangShan 实际 emitted 代码已命中该优化，例如：
  - `307 ops` 的 `u64` range 写
  - `352 ops` 的 `u8` range 写

### 8.2 本阶段回归与修复

第一次接入后引入了一个功能回归：

- `bool` 类型的 range helper 一度错误写入了
  - `state_shadow_u8_slots_`
  - `state_logic_u8_slots_`
- 但 XiangShan 正常的 `bool` 写路径实际应写入
  - `state_shadow_bool_slots_`
  - `state_logic_bool_slots_`

表现：

- 初始版本会在启动后立即触发 `MSHR_64` / `DataSRAMBank` / `MissEntry` / `DCache` 断言，随后 `pc = 0x0` abort
- 修正这个数组映射错误后，启动路径恢复正常

最终确认：

- `emit-grhsim-cpp` 单测重新通过
- `xs_wolf_grhsim_emu` 已重编成功
- `coremark` 10k 周期运行恢复到之前的正常启动轨迹

### 8.3 本阶段稳定指标

#### 功能稳定性

- 10k 周期普通运行：
  - `pc = 0x800027c6`
  - `instrCnt = 458`
  - `cycleCnt = 9996`
  - `Host time spent = 87627 ms`

#### perf stat

测试命令：

```bash
perf stat -x, -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,L1-dcache-loads,L1-dcache-load-misses,L1-icache-loads,L1-icache-load-misses,LLC-loads,LLC-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 10000
```

结果：

- `pc = 0x800027c6`
- `instrCnt = 458`
- `cycleCnt = 9996`
- `Host time spent = 61855 ms`
- `cycles = 351192334735`
- `instructions = 90717684542`
- `IPC = 0.26`
- `branch-misses = 14.08%`
- `cache-misses = 46.07%`
- `L1-dcache-load-misses = 3.75%`
- `L1-icache-load-misses = 10.58%`
- `dTLB-load-misses = 0.67%`
- `iTLB-load-misses = 61.11%`

### 8.4 本阶段结论

- 这轮 range 压缩确实已经进入 XiangShan 的真实热点 emitted 路径，不是只在单测里生效。
- 本阶段最重要的收益不是单个 counter 的大幅变化，而是验证了：
  - emitter 可以安全做大粒度 state-write run 压缩
  - 代码体量 / I-cache 方向的优化是可落地的
- 当前剩余最突出的前端瓶颈仍然是：
  - `L1I miss = 10.58%`
  - `iTLB miss = 61.11%`

因此下一阶段仍应优先继续压缩 `eval_batch_*` 热路径代码体量，而不是回到 `active-word` 外层扫描。
