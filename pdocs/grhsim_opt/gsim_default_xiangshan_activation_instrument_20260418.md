# GSim Default XiangShan Activation Instrumentation（2026-04-18）

本文记录一次对 `gsim` 的机理级插桩实验，目标是回答 3 个问题：

1. 最终形成了多少个 `supernode`
2. `supernode` 之间有多少条边
3. 运行时每个 `step` 实际激活多少个节点

测例选择 `default-xiangshan`，workload 继续沿用仓库脚本口径使用 `ready-to-run/bin/coremark-NutShell.bin`。

## 口径

- `gsim` 目录：`tmp/gsim`
- 插桩后独立构建目录：`tmp/gsim_default_xiangshan_instrument_20260418`
- workload：`tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- CPU 绑定：`taskset 0x1`
- 运行样本数：`1900000` post-reset `step`

## 插桩点

### 1. 结构统计

在 `tmp/gsim/src/cppEmitter.cpp` 中增加了两个结构统计点：

- `evaluatedMemberCount()`：统一计算一个 emitted `supernode` 对应的有效 member 数
- `emitInstrumentationSummary()`：在 `cppEmitter()` 分配完 `cppId` 后，统计：
  - `sortedSuper.size()`
  - emitted `supernode` 数
  - `next` 边数
  - `depNext` 边数
  - evaluated member 总数

这部分结果会写入：

- `tmp/gsim_default_xiangshan_instrument_20260418/default-xiangshan/model/gsim_instrumentation_summary.txt`

### 2. step 级激活统计

在 `tmp/gsim/src/cppEmitter.cpp` 里给生成出的 `SimTop` 类加入：

- `currentStepActiveSupernodes`
- `currentStepActiveMembers`
- `superMemberNum[]`
- `stepActiveSupernodes`
- `stepActiveMembers`

统计方式是：

- 每次进入一个被执行的 `supernode`，在 `genNodeStepStart()` 中执行：
  - `currentStepActiveSupernodes ++`
  - `currentStepActiveMembers += superMemberNum[cppId]`
- 每个 `step()` 结束后，把本步计数 push 到两个 vector 里

### 3. 排除 reset 预热

在 `tmp/gsim/emu/emu.cpp` 中：

- `dut_reset()` 之后立刻清空 step 统计容器
- 仿真退出前统一打印：
  - `avg`
  - `min`
  - `p50`
  - `p90`
  - `p99`
  - `max`

因此下文的 step 统计都不包含前 10 个 reset cycle。

## 执行命令

```bash
cd tmp/gsim

/usr/bin/time -v make compile \
  dutName=default-xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_instrument_20260418 \
  mainargs=ready-to-run/bin/coremark-NutShell.bin \
  -j16

/usr/bin/time -v make build-emu \
  dutName=default-xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_instrument_20260418 \
  mainargs=ready-to-run/bin/coremark-NutShell.bin \
  -j16

/usr/bin/time -v taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_instrument_20260418/default-xiangshan/SSimTop \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin
```

## 结果

### 1. 最终 supernode 数

- `sorted supernodes`：`131584`
- `emitted supernodes`：`131580`

这里：

- `sorted supernodes` 表示图分区完成后的最终 `sortedSuper.size()`
- `emitted supernodes` 表示真正分配了 `cppId`、进入最终 step 调度的 `supernode`

两者只差 `4`，说明 `default-xiangshan` 这个配置下，绝大多数最终 supernode 都进入了可执行模型。

### 2. supernode 间边数

- `sorted supernode adjacent edges`：`612269`
- `sorted supernode dependency edges`：`720235`
- `emitted supernode adjacent edges`：`612269`
- `emitted supernode dependency edges`：`720151`

派生量：

- emitted 邻接出度均值：`4.6532`
- emitted 依赖出度均值：`5.4731`

可直接把：

- `next`
  当作真实调度图上的直接边
- `depNext`
  当作包含依赖约束的更宽口径边集

如果后续要和 `grhsim` 对齐，我建议优先对齐 `next` 边数，再补看 `depNext`。

### 3. emitted member 总量

- `sorted evaluated members`：`1981686`
- `emitted evaluated members`：`1981679`

这个数可以理解成：

- 最终进入 emitted model 的 member 级工作总量

它不是 guest RTL 原始 node 数，也不是 `defined nodes`，而是更贴近最终执行调度面的统计。

### 4. step 级激活统计

- `step_samples`：`1900000`

#### active supernodes per step

- `avg`：`10260.63`
- `min`：`2138`
- `p50`：`10009`
- `p90`：`16437`
- `p99`：`18487`
- `max`：`131580`

折算为 emitted supernode 占比：

- `avg`：`7.7980%`
- `min`：`1.6249%`
- `p50`：`7.6068%`
- `p90`：`12.4920%`
- `p99`：`14.0500%`
- `max`：`100%`

#### active members per step

- `avg`：`401492.61`
- `min`：`43221`
- `p50`：`410494`
- `p90`：`613717`
- `p99`：`701680`
- `max`：`1981679`

折算为 emitted member 占比：

- `avg`：`20.2602%`
- `min`：`2.1810%`
- `p50`：`20.7145%`
- `p90`：`30.9695%`
- `p99`：`35.4084%`
- `max`：`100%`

## 机理层面的解读

### 1. `gsim` 运行时激活前沿是稀疏的

平均每个 `step` 只会激活：

- 约 `7.8%` 的 emitted `supernode`
- 约 `20.3%` 的 emitted member

也就是说，虽然 `gsim` 最终生成出了 `13.16` 万个 emitted `supernode`，但绝大多数 step 实际只跑其中一小部分。

这说明 `gsim` 的性能不只是靠“把图切小”，更重要的是：

- 能在 runtime 把活跃前沿压到一个相对小的子集

### 2. 热区有明显波动，但高分位也没有失控

看高分位：

- `p90` 活跃 supernode 只有 `16437`
- `p99` 活跃 supernode 只有 `18487`

即便在比较重的 step 上，活跃 `supernode` 也大致仍在 `1.8w` 以内，没有接近全图扫描。

这对后续比 `grhsim` 很关键：

- 如果 `grhsim` 的激活前沿明显大于这个量级，那差距的一部分就来自过度激活
- 如果激活前沿接近，但仍明显更慢，那重点应转向“每个活跃节点的 host 侧动态成本”

### 3. 存在少量“全图激活”step

`max = 131580 supernodes` 与 `1981679 members`，刚好等于 emitted 总量。

这说明：

- 至少存在一个 post-reset `step` 会把整个 emitted 图全部打活

这通常出现在：

- 刚进入 workload 的早期收敛阶段
- 某些全局状态变化触发大面积传播

但从 `p99` 仍然只有 `14.05%` / `35.41%` 来看，这种全图激活不是常态，而是极少数尾部事件。

## 对后续 `grhsim` 对齐最有价值的指标

如果接下来继续做机理对比，我建议直接对齐下面这组量：

- emitted `supernode` 数
- emitted `next` 边数
- emitted `depNext` 边数
- emitted member 总数
- `active supernodes per step` 的 `avg/p50/p90/p99`
- `active members per step` 的 `avg/p50/p90/p99`

这组指标能把问题拆成两层：

- 图静态规模是否已经过大
- 即使图规模接近，runtime 激活前沿是否仍然过宽

## 产物位置

- 结构统计文件：
  - `tmp/gsim_default_xiangshan_instrument_20260418/default-xiangshan/model/gsim_instrumentation_summary.txt`
- `compile` 日志：
  - `tmp/gsim_default_xiangshan_instrument_20260418_compile.log`
- `build-emu` 日志：
  - `tmp/gsim_default_xiangshan_instrument_20260418_build_emu.log`
- 运行日志：
  - `tmp/gsim_default_xiangshan_instrument_20260418_run.log`
- 产物文档：
  - `pdocs/grhsim_opt/gsim_default_xiangshan_activation_instrument_20260418.md`

## 附注

- 本次 build 已按你提醒全程使用 `-j16`
- 运行时统计口径为 post-reset step，不包含 `dut_reset()` 的 10 个预热周期
- 这次没有使用 `PERF=1`，避免把 `-O0` 的 debug/perf 统计路径混进来，保持更接近正常 `gsim` runtime 行为
