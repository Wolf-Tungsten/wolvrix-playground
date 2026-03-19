# Memory ReadPort 地址寄存后移 Pass 草案

## 目标

- 新增一个 pass，检测 `kMemoryReadPort` 前面是否存在“专用于该读口的地址寄存器”。
- 在严格约束下，把这个寄存器从读地址侧移动到读数据侧，形成“先读 memory，再寄存数据”的等价结构。
- 明确给出只在**仿真行为可证明不变**时才改写的规则；不满足条件的候选一律跳过。

## 非目标

- 不在首版处理一个地址寄存器扇出到多个 memory readport 或其它普通逻辑的情况。
- 不在首版处理无法静态求出初值的 memory / register 初始化。
- 不在首版处理多写口、带 mask 写口、跨事件域写口的 memory。
- 不尝试在 `keepDeclaredSymbols=true` 的前提下强行消除用户可见的源级地址寄存器符号。

## 背景

当前 GRH IR 中：

- `kMemoryReadPort` 是**异步读**：
  - `oper[0]` = `addr`
  - `res[0]` = `data`
  - 语义：`data = mem[addr]`
- 同步读通常不是单独的 op，而是通过“地址先打一拍，再异步读 memory”来表达：

```sv
always @(posedge clk)
    addr_q <= addr_d;

assign data = mem[addr_q];
```

这个形态对后续某些优化并不友好。一个更规整的形态是：

```sv
wire data_d = mem[addr_d];

always @(posedge clk)
    data_q <= data_d;

assign data = data_q;
```

但这个变换**并不总是等价**。如果 memory 在周期中间会被写，或者 time 0 初值无法对齐，直接搬运寄存器会改变波形。因此本 pass 必须只覆盖一个语义可证明的安全子集。

## 首版范围：两档安全子集

首版覆盖下面两档可证明等价的场景。

### A. ROM 型读口

- 目标 `kMemory` 没有任何 `kMemoryWritePort`。
- 地址寄存器只服务于这一个 `kMemoryReadPort`。
- memory 初值可以静态物化成“行号 -> 常量值”映射。
- 若地址寄存器初值可以静态求值，则同步推导新数据寄存器的初值；否则允许放弃 time 0 等价，不阻塞改写。

这一档可以把地址侧寄存完全换成数据侧寄存。

### B. 简单 RAM 型读口

- 目标 `kMemory` 恰好只有一个 `kMemoryWritePort`。
- 写口不带 mask，或者 mask 是全 1 常量。
- 地址寄存器写口与 memory 写口拥有同一组 `events + eventEdge`。
- 地址寄存器只服务于这一个 `kMemoryReadPort`。
- 地址寄存器可以没有可静态求值的初值；此时只保证首个相关事件之后的行为。

这一档**不能**把地址状态完全删除；必须保留一个内部 `shadow addr register`，并在写命中当前选中地址时刷新数据寄存器。

两档共同点是：都只在时序和可观察数据可以被显式对齐时改写；否则跳过。

## 术语

- **地址寄存器**：`kMemoryReadPort.oper[0]` 的来源是某个 `kRegisterReadPort.res[0]`，且该 `kRegisterReadPort` 读取的 `kRegister` 满足本草案的专用性约束。
- **专用地址寄存器**：该寄存器的读值只被一个目标 `kMemoryReadPort` 使用，且寄存器只有一个写端口。
- **数据寄存器**：pass 新建的 `kRegister`，用于承接原本在地址侧的那一级时序。

## 变换前后模式

### 变换前

目标子图必须精确匹配下面的 IR 关系。

1. 一个 `kRegister addr_reg`
   - `attrs.width` = 地址位宽
   - `attrs.initValue` 可选，但若存在必须可静态求值

2. 一个 `kRegisterWritePort addr_wp`
   - `attrs.regSymbol = <addr_reg>`
   - `oper[0]` (`updateCond`): 地址更新条件
   - `oper[1]` (`nextValue`): 下一个地址
   - `oper[2]` (`mask`): 必须是全 1 常量，位宽等于地址位宽
   - `oper[3..]` (`events`): 事件列表
   - `attrs.eventEdge`: 与 `events` 一一对应

3. 一个 `kRegisterReadPort addr_rp`
   - `attrs.regSymbol = <addr_reg>`
   - `res[0] = addr_q`

4. 一个 `kMemoryReadPort mem_rp`
   - `attrs.memSymbol = <mem>`
   - `oper[0] = addr_rp.res[0]`
   - `res[0] = data`

5. 一个 `kMemory mem`
   - 没有任何 `kMemoryWritePort` 指向它
   - 初值能被静态物化为完整 ROM 内容

对应的等价 SV 形态如下：

```sv
logic [AW-1:0] addr_q;
logic [DW-1:0] data;

always @(posedge clk)
    if (en)
        addr_q <= addr_d;

assign data = rom[addr_q];
```

### 变换后

对 ROM 型读口，pass 生成下面的结构：

1. 保留原 `kMemory mem`

2. 新建一个 `kMemoryReadPort mem_rp_new`
   - `attrs.memSymbol = <mem>`
   - `oper[0] = addr_wp.oper[1]`
   - `res[0] = data_d`

3. 新建一个 `kRegister data_reg`
   - `attrs.width = mem.width`
   - `attrs.isSigned = mem.isSigned`
   - `attrs.initValue = ROM[addr_reg.initValue]`

4. 新建一个 `kRegisterWritePort data_wp`
   - `attrs.regSymbol = <data_reg>`
   - `oper[0] = addr_wp.oper[0]`
   - `oper[1] = mem_rp_new.res[0]`
   - `oper[2] = 全 1 常量`
   - `oper[3..] = addr_wp.oper[3..]`
   - `attrs.eventEdge = addr_wp.attrs.eventEdge`

5. 新建一个 `kRegisterReadPort data_rp`
   - `attrs.regSymbol = <data_reg>`
   - `res[0]` 替换原 `mem_rp.res[0]` 的所有 use

对应的等价 SV 形态如下：

```sv
logic [DW-1:0] data_q;
wire  [DW-1:0] data_d;

assign data_d = rom[addr_d];

always @(posedge clk)
    if (en)
        data_q <= data_d;

assign data = data_q;
```

### 变换后（简单 RAM 型）

如果 memory 带一个简单写口，单纯把：

```sv
addr_q -> mem[addr_q]
```

改成：

```sv
mem[addr_d] -> data_q
```

是不够的。因为旧结构中，当前输出不仅会在地址更新时变化，也会在“写口命中当前观察地址”时变化。

因此 RAM 型读口的安全改写必须保留一份内部地址状态 `sel_addr_q`，并额外建一个写命中刷新条件。

变换后结构如下：

1. 保留原 `kMemory mem`
2. 保留或重建一个内部地址寄存器 `sel_addr_reg`
   - 其时序语义与原地址寄存器一致
   - 若原地址寄存器是内部临时对象，可直接复用；若原地址寄存器是需要消除的中间节点，可新建内部 shadow
3. 新建一个组合地址：
   - `sel_addr_next = addr_en ? addr_d : sel_addr_q`
4. 新建一个 `kMemoryReadPort mem_rp_new`
   - `oper[0] = sel_addr_next`
   - `res[0] = data_d`
5. 新建一个写命中比较：
   - `write_hit = wen && (waddr == sel_addr_next)`
6. 新建一个读数据选择：
   - `data_refresh = write_hit ? wdata : data_d`
7. 新建一个数据更新条件：
   - `data_en = addr_en || write_hit`
8. 新建一个数据寄存器 `data_reg`
   - 初值为 `ROM/A0` 规则求得的旧结构 time 0 输出
9. 新建一个 `kRegisterWritePort data_wp`
   - `oper[0] = data_en`
   - `oper[1] = data_refresh`
   - `oper[2] = 全 1 常量`
   - `oper[3..]` 与地址寄存器写口 / memory 写口保持同一事件列表
10. 新建一个 `kRegisterReadPort data_rp`
    - 用其结果替换原 `mem_rp.res[0]`

等价 SV 形态如下：

```sv
logic [AW-1:0] sel_addr_q;
logic [DW-1:0] data_q;
wire  [AW-1:0] sel_addr_next;
wire  [DW-1:0] data_d;
wire           write_hit;

assign sel_addr_next = addr_en ? addr_d : sel_addr_q;
assign data_d        = mem[sel_addr_next];
assign write_hit     = wen && (waddr == sel_addr_next);

always @(posedge clk) begin
    if (addr_en)
        sel_addr_q <= sel_addr_next;
    if (addr_en || write_hit)
        data_q <= write_hit ? wdata : data_d;
end

assign data = data_q;
```

## 为什么 writable memory 需要看 `kMemoryWritePort`

即使 pass 的入口是 `kMemoryReadPort`，只要 memory 可写，`kMemoryWritePort` 就会影响 readport 的可观察行为。

如果 memory 可写，下面两个行为会立刻决定“能不能安全改”：

1. 同一个周期内 memory 被写，旧结构会在写后立即反映 `mem[addr_q]` 的新值，新结构中的 `data_q` 不会自动更新。
2. 即使写发生在别的时钟域，只要它发生在两次地址更新之间，旧结构的输出也可能改变，而新结构保持不变。

因此，带写口并不是不能做，而是必须把写口纳入候选判定与重写逻辑。首版只支持“单写口、无 mask、同事件域”这一档最简单场景。

## 等价性条件

设：

- `A_k`：第 `k` 次事件完成后，旧结构中地址寄存器的状态
- `D_k`：第 `k` 次事件完成后，新结构中数据寄存器的状态
- `EN_k`：该次事件上 `updateCond`
- `N_k`：该次事件上 `nextValue`
- `ROM[x]`：只读 memory 在地址 `x` 处的常量值

旧结构：

- `A_{k+1} = EN_k ? N_k : A_k`
- `Y_old_{k+1} = ROM[A_{k+1}]`

新结构：

- `D_{k+1} = EN_k ? ROM[N_k] : D_k`
- `Y_new_{k+1} = D_{k+1}`

只要初值满足：

- `D_0 = ROM[A_0]`

就有：

- 若 `EN_k = 1`，则
  - `Y_old_{k+1} = ROM[N_k]`
  - `Y_new_{k+1} = ROM[N_k]`
- 若 `EN_k = 0`，则
  - `Y_old_{k+1} = ROM[A_k]`
  - `Y_new_{k+1} = D_k = ROM[A_k]`

由归纳法可得，对所有 `k`，`Y_old_k = Y_new_k`。

又因为 ROM 不可写，事件之间：

- 旧结构的 `addr_q` 不变，`rom[addr_q]` 也不变
- 新结构的 `data_q` 不变

因此在整个仿真时间线上，两者的可观察输出一致。

## 简单 RAM 型的等价性条件

设：

- `A_k`：第 `k` 次事件完成后，旧结构中地址寄存器状态
- `S_k`：第 `k` 次事件完成后，新结构中 `sel_addr_q` 状态
- `D_k`：第 `k` 次事件完成后，新结构中 `data_q` 状态
- `ENa_k`：地址寄存器更新条件
- `Na_k`：地址寄存器下一个地址
- `WEN_k`：memory 写使能
- `WA_k` / `WD_k`：写地址 / 写数据
- `M_k[x]`：第 `k` 次事件完成后 memory 在地址 `x` 的值

旧结构：

- `A_{k+1} = ENa_k ? Na_k : A_k`
- `M_{k+1}[x] = (WEN_k && WA_k == x) ? WD_k : M_k[x]`
- `Y_old_{k+1} = M_{k+1}[A_{k+1}]`

新结构：

- `S_{k+1} = ENa_k ? Na_k : S_k`
- `sel_addr_next = ENa_k ? Na_k : S_k`
- `write_hit = WEN_k && (WA_k == sel_addr_next)`
- `D_{k+1} = (ENa_k || write_hit) ? (write_hit ? WD_k : M_{k+1}[sel_addr_next]) : D_k`
- `Y_new_{k+1} = D_{k+1}`

只要初值满足：

- `S_0 = A_0`
- `D_0 = M_0[A_0]`

就有：

- 若 `ENa_k = 1`
  - `sel_addr_next = Na_k`
  - 若同时 `write_hit = 1`，则两边输出都等于 `WD_k`
  - 否则两边输出都等于 `M_{k+1}[Na_k]`
- 若 `ENa_k = 0`
  - `sel_addr_next = S_k = A_k`
  - 若 `write_hit = 1`，则两边输出都等于 `WD_k`
  - 否则两边都保持 `M_k[A_k]`

因此，在“单写口、全字写、同事件域”的约束下，新结构可以通过 `shadow addr + write_hit refresh` 与旧结构保持等价。

## 初值策略

首版实现不再强求 time 0 等价。

- 若地址寄存器初值和 memory 初值都能静态求出，则为新 `data_reg` 写入对应 `initValue`。
- 若任一侧无法静态求值，则仍允许改写，只是不为新 `data_reg` 写 `initValue`。

也就是说：

- 本 pass 保证的是事件驱动语义在稳态下可对齐。
- 对于没有显式初始化、且设计又依赖 time 0 可观察值的情况，本 pass 不承担等价性责任。

## 候选筛选规则

对每个 `kMemoryReadPort`，按下面顺序检查：

1. `oper[0]` 必须直接来自 `kRegisterReadPort.res[0]`，中间不能夹任何组合 op。
2. 该 `kRegisterReadPort` 指向的 `kRegister` 必须只有一个 `kRegisterWritePort`。
3. 地址寄存器写口的 `oper[2]` 必须是全 1 常量。
4. 地址寄存器的读值只能被当前这个 `kMemoryReadPort` 使用。
5. 目标 `kMemoryWritePort` 数量只能是：
   - `0`：进入 ROM 路径
   - `1`：继续检查简单 RAM 路径
   - `>1`：跳过
6. 若有一个 `kMemoryWritePort`：
   - `oper[3]`（mask）必须是全 1 常量
   - 写口与地址寄存器写口的 `events + eventEdge` 必须完全相同
7. 若 `keepDeclaredSymbols=true` 且地址寄存器 symbol 位于 `graph.declaredSymbols()`，则跳过。

第 7 条的原因是：

- 原地址寄存器是源级声明对象；
- 新数据寄存器位宽与原地址寄存器不同，不能简单继承原 symbol；
- 在 `keepDeclaredSymbols=true` 下直接删除它会违背当前框架的约束。

## 重写步骤

建议实现顺序如下：

1. 收集一个 graph 内所有 `kMemoryReadPort` 候选。
2. 对每个候选解析：
   - `addr_reg`
   - `addr_wp`
   - `addr_rp`
   - `mem`
   - `mem_rp`
3. 若可能，物化旧结构的 time 0 可观察输出值，写入 `data_reg.initValue`；否则省略该属性。
4. 若 memory 无写口：
   - 创建新的 `kMemoryReadPort mem_rp_new`，地址改为 `addr_wp.oper[1]`
   - 创建新的 `kRegister data_reg` / `kRegisterWritePort data_wp` / `kRegisterReadPort data_rp`
   - 用 `data_rp.res[0]` 替换原 `mem_rp.res[0]`
   - 删除旧 `mem_rp`、`addr_rp`、`addr_wp`、`addr_reg`
5. 若 memory 有一个简单写口：
   - 保留或重建一个内部 `shadow addr register`
   - 创建 `sel_addr_next`
   - 创建新的 `kMemoryReadPort mem_rp_new`
   - 创建 `write_hit = wen && (waddr == sel_addr_next)`
   - 创建 `data_en = addr_en || write_hit`
   - 创建 `data_refresh = write_hit ? wdata : mem_rp_new.res[0]`
   - 创建 `data_reg` / `data_wp` / `data_rp`
   - 用 `data_rp.res[0]` 替换原 `mem_rp.res[0]`
   - 仅在地址寄存器确实成为死节点时删除旧 `addr_rp/addr_wp/addr_reg`
6. 执行一次局部清理，移除变换产生的死常量或无用 value。

## 一个最小例子

### 变换前

```sv
module top(
    input  logic       clk,
    input  logic       en,
    input  logic [3:0] addr_d,
    output logic [7:0] data
);
    logic [3:0] addr_q = 4'h2;
    logic [7:0] rom [0:15];

    initial begin
        rom[0] = 8'h10;
        rom[1] = 8'h11;
        rom[2] = 8'h12;
    end

    always @(posedge clk)
        if (en)
            addr_q <= addr_d;

    assign data = rom[addr_q];
endmodule
```

### 变换后

```sv
module top(
    input  logic       clk,
    input  logic       en,
    input  logic [3:0] addr_d,
    output logic [7:0] data
);
    logic [7:0] data_q = 8'h12;
    logic [7:0] rom [0:15];

    initial begin
        rom[0] = 8'h10;
        rom[1] = 8'h11;
        rom[2] = 8'h12;
    end

    always @(posedge clk)
        if (en)
            data_q <= rom[addr_d];

    assign data = data_q;
endmodule
```

这里 `data_q` 的初值取自 `rom[4'h2] = 8'h12`，因此 time 0 行为也保持不变。

## 必须跳过的场景

- memory 存在多个 `kMemoryWritePort`
- 地址寄存器有多个写口
- 地址寄存器写 mask 不是全 1 常量
- memory 写口 mask 不是全 1 常量
- 地址寄存器读值有多个 use
- `kMemoryReadPort.oper[0]` 不是直接的 `kRegisterReadPort`
- memory 写口与地址寄存器写口不在同一事件域
- memory 初始化无法静态展开
- `keepDeclaredSymbols=true` 且待删除地址寄存器是 declared symbol

## Pass 接口建议

- pass 名称建议：`memory-read-retime`
- 首版不暴露激进开关，默认只做严格安全改写

可选后续参数：

- `-allow-undef-init`
  - 允许跳过 time 0 等价性，只保证首个有效事件之后的行为
  - 不建议首版开放
- `-allow-ram`
  - 允许处理可写 memory
  - 需要配套 read-during-write 语义，首版禁止

## 统计建议

建议输出以下计数：

- `readport_total`
- `readport_candidate`
- `readport_retimed`
- `readport_retimed_rom`
- `readport_retimed_simple_ram`
- `skip_non_register_addr`
- `skip_multiwrite_addr_reg`
- `skip_partial_mask`
- `skip_addr_fanout`
- `skip_multiwrite_memory`
- `skip_writeport_partial_mask`
- `skip_mismatched_event_domain`
- `skip_declared_symbol`

## 验证计划

### 单元级用例

1. `rom_addr_reg_retime_basic`
   - 单时钟、带使能、ROM literal init
   - 验证变换前后逐周期数据完全一致

2. `rom_addr_reg_retime_hold`
   - `updateCond` 周期性拉低
   - 验证地址保持时数据也保持

3. `rom_addr_reg_retime_init`
   - 地址寄存器有显式 `initValue`
   - 验证 time 0 与第一个时钟沿后的输出一致

4. `rom_addr_reg_retime_skip_writeport`
   - memory 存在多个 `kMemoryWritePort`
   - 验证 pass 跳过

5. `ram_addr_reg_retime_basic`
   - 单地址寄存器 + 单写口 + 全字写 + 同事件域
   - 验证地址切换和写命中刷新都与原结构一致

6. `ram_addr_reg_retime_write_hit`
   - 地址保持不变，仅发生写命中当前地址
   - 验证新结构会因为 `write_hit` 刷新 `data_q`

7. `ram_addr_reg_retime_skip_masked_write`
   - memory 写口带变量 mask 或部分 mask
   - 验证 pass 跳过

8. `ram_addr_reg_retime_skip_event_mismatch`
   - 地址寄存器与写口事件列表不同
   - 验证 pass 跳过

9. `rom_addr_reg_retime_skip_fanout`
   - 地址寄存器同时驱动 memory 和其它逻辑
   - 验证 pass 跳过

10. `rom_addr_reg_retime_skip_declared_symbol`
   - `keepDeclaredSymbols=true`
   - 验证 pass 跳过

### 回归验证

- 对每个命中的样例，输出 transform 前后的 SV。
- 使用同一 testbench 逐拍比较输出波形。
- 特别检查：
  - time 0 输出
  - `updateCond=0` 保持周期
  - 连续两拍地址切换

## 后续扩展方向

如果后续需要把这个 pass 扩展到比“单写口、无 mask、同事件域”更宽的 RAM，至少要先回答三个问题：

1. 同拍读写同址时采用 old-data、new-data 还是 no-change 语义？
2. 其它时钟域的写是否允许改变本读口在周期中间的可见值？
3. 当 readport 结果被组合逻辑直接观察时，是否允许它从“周期中间可变”变成“仅事件后更新”？

这三个问题没有在 IR 层定清之前，不应把本 pass 放宽到**超出“单写口、无 mask、同事件域”范围的更一般可写 memory**。
