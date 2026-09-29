# GrhSIM IR 生成的 C++ 模型整体形态（以 Rob 独立仿真为例）

面向优化讨论的宏观导览。读完应能回答：生成的模型长什么样、一次 `eval()` 发生了什么、
时间花在哪些结构上、要改某一类行为应该动哪个文件。

文中所有代码引用均为**项目根相对路径:行号**（如 `ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:43700`），
VSCode 终端可直接点击跳转，或在 Quick Open（Ctrl+P）里粘贴。

- 被剖析对象：`ptmp/xs-components-rob/grhsim-model/`（XiangShan Rob 模块，由 wolvrix emitter 生成）
- 发射器源码：`wolvrix/lib/grhsim/backend/cpu_emit.cpp`（约 7.0k 行，所有生成文本的出处）
- 设计文档（机制语义细节）：`wolvrix/docs/grhsim_ir/backends/cpu.md`
- 性能背景：`pdocs/rob_standalone/rob-trace-replay-bench-20260929.md`（trace 激励下 grhsim 比 gsim 慢 2.25× 的全部数据）
- 待办与已办清单：`pdocs/rob_standalone/TODO.md`（六项 emitter 修改的实施结论）

> 注意：`ptmp/` 下的生成产物可能被清理。重新生成：`make -C testcase/xs-components -f rob.mk rob-grhsim-model`
> （约 40 秒）。文中行号以 2026-09-29 TODO 六项落地后的生成为准；emitter 改动后行号会漂移，
> 以结构名（或生成的 `/* [phase] ... */` 段首注释）为准重新定位。

## 1. 一句话形态

生成的模型是**一个巨大的单体 C++ 类** `GrhSIM_Rob`：公开区是 ~5,800 行逐端口的类型化成员
（host 直接读写），私有区是模拟所需的全部状态与机制。没有对象网络、没有虚函数、没有堆上的
模块层次——整个 Rob 拍平成一个类 + 82 个 `.cpp` 任务/初始化文件，合计约 **148 万行**。

```
ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp            6,229 行   类声明（端口成员 + 存储 + 内联工具）
ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp           63,104 行   静态表 + init/eval/publish/profile
ptmp/xs-components-rob/grhsim-model/grhsim_Rob_init_*.cpp        12 个   init 分块（每块 ≤4096 步，合计 136 行）
ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_*.cpp        70 个   任务函数 cpu_task_1 .. cpu_task_70（合计 142 万行）
```

**2026-09-29 起生成代码自带 `/* [phase] ... */` 段首注释**（TODO-2）：eval 七个阶段、
compute/commit 任务头、commit 任务内各相位都有中文说明，`grep '\[phase\]'` 可全量列出
（主 cpp 1,137 处）。本文 §3/§4 的阶段划分与这些注释一一对应。

## 2. 类的解剖（ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp）

| 区域 | 位置 | 内容 |
|---|---|---|
| 文件头工具 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:5 | `cpu_at<T>`（字节数组+偏移的 typed 访问，:5）；`cpu_word8`（8 字节标志字测试，:8）；`cpu_or8`（8 字节打包 OR，:13）；宽位运算/拼接模板（>64 位值的 `std::array<uint64_t,N>` 助手）在 :19 起 |
| 公开端口成员 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:196 | 类起点；:198–5981 每端口一个类型化成员（`bool`/`uint8_t`/`uint16_t`/`uint64_t`/宽口 `std::array<uint64_t,N>`），host 的 drive/sample 就是直接赋值/读取 |
| 公开方法 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:5988 | `init()`（:5988）、`eval()`（:5989）、runtime profile 开关与转储（:5990 起） |
| 状态存储 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6005 | `cpu_objects`（158,272 B 主状态字节数组，:6005）、`cpu_shadow`（同尺寸写暂存，:6006）、`cpu_boundary`（161,488 B 边界/快照值，:6007）、`cpu_inputs`（2,920 B 上周期输入快照，:6008） |
| 活动调度 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6012 | `cpu_flags`/`cpu_next_arms`（778 B 任务激活位图，:6012）、`cpu_pflags`（267 B 端口武装字节，:6013）、`cpu_dirty`（64,063 B 每状态+每内存行脏位，:6014）、`Pending`（:6015）/`Target`（:6021）结构、`cpu_targets`（30,944 条状态→任务扇出边，:6026）、`cpu_pending`（本 round 待发布写，:6027）、`cpu_memory_readers`（11,909 条内存读→任务边，:6028）、`cpu_read_offsets`（与 readers 平行的单元偏移表，:6029） |
| 写路径 helper | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6037 | `cpu_stage_cell`（:6037）；`cpu_write_cell` 四形态（TODO-5）：通用版（:6046，动态行+部分 mask）、`_f`（:6058，全 mask）、`_c`（:6069，常量行）、`_cf`（:6079，常量行+全 mask，Rob 的 memWrite 全命中此两形）；直写实验组（默认关闭，TODO-6）：`cpu_direct_fanout`（:6088，noinline 读者扇出外调）、`cpu_write_cell_direct`（:6094）/`_f`（:6103）；`cpu_stage`（:6111）/`cpu_write_scalar`（:6119）/`cpu_stage_bytes`（:6128）/`cpu_stage_bytes_overwrite`（:6136） |
| 方法声明 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6143 | `cpu_publish()`（:6143）、12 个 `cpu_init_*`、70 个 `cpu_task_*`（:6156–6225）、`cpu_helper_*`（:6226 起，guard 提升的共享块） |

关键认知：**所有状态（寄存器、内存、组合中间值）都住在 `cpu_objects` 一个字节数组里**，
通过 `cpu_at<T>(base, offset)` 以编译期常量偏移访问——机器码层面就是 base+offset 直接访存。
这就是议题中"所有位宽混在一个桶里"所指的存储形态。

## 3. 一次 eval() 的生命周期（ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:43700）

bench 每周期调用两次 `eval()`（clock=0 下降沿、clock=1 上升沿）。`eval()` 函数体横跨
ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:43700 至 :63049（~19.3k 行）。
每个阶段现在在生成代码里都有 `/* [phase] */` 段首注释，下列行号与注释一一对得上：

### 3.0 序言：profile 计时设施（43703–43715）

`cpu_profile_clock`/`cpu_profile_tick` lambda 定义；仅当 `set_runtime_profile_enabled(true)`
时才计时，否则全是死代码被编掉。议题一的分相统计（compute/commit/publish）就靠它。

### 3.1 输入暂存：融合的比较-更新-扇出（43716–44100 + 44101–58646）

融合形态（议题四落地）：无扇出行的端口仍走旧式无条件拷贝（43716 注释起，~384 行）；
其余 1,126 个口每口一个融合 if 块——**直接用 `this->io_*` 与 `cpu_inputs` 快照比较，
不等才同时更新快照与 `cpu_objects` 并扇出**（原"拷贝进 cpu_objects 再读出来比"的内存往返已消除）。
每口块首有 `/* [phase] 输入口 <名>：...（activate=N arm=M） */` 注释（如 clock 块 44104–44121）：

```cpp
/* [phase] 输入口 clock：与上周期快照比较，变化才更新快照/对象区并扇出（activate=45 arm=2） */
if(cpu_at<bool>(cpu_inputs.data(),0)!=static_cast<bool>(grhsim_trunc_u64(this->clock,1))){
    cpu_at<bool>(cpu_inputs.data(),0)=...this->clock...;   // 更新快照
    cpu_at<bool>(cpu_objects.get(),0)=...this->clock...;   // 更新状态区
    cpu_chg_mask|=UINT64_C(1)<<0;
    if((...)!=0)cpu_chg_up|=UINT64_C(1)<<0;
    cpu_flags[771] |= 240; ...                             // 扇出（尾部越界时保持字节粒度）
    cpu_flags[0] |= 1; cpu_flags[2] |= 1;                  // commit 域直置（§4.4）
}
```

扇出置位已做 **u64 打包**：连续标志字节的 run 合并为
`cpu_or8(cpu_flags.data(),677,UINT64_C(0xffffffffffffffe0))`（44126 起，helper 定义在
ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:13，memcpy 实现对齐安全）。
打包前 48,947 行字节置位 → 打包后 6,146 个 `cpu_or8` + 单字节兜底（越界 run 保持字节形式，
如 clock 块的 flags[771..777] 尾 run 因 771+8>778 不打包）。

> 历史注：打包前该区间的二进制体积几乎没变小（`eval()` 234,690 B → 231,803 B，本轮实测仍为此值）——
> clang 本来就把连续字节 OR 自动合并成宽操作，且未变化口的扇出体被 cold-block 放置跳过；
> 实测性能收益在噪声级（bench 文档 §4），证实这段不是热点。

### 3.2 边沿分类（58647–58655）

按 `cpu_chg_mask` 是否为单 bit、是否落在时钟集合内、上升/下降，把本次 eval 分为
pos/neg/other 三类，选定 7 个 profile 分桶引用（`cpu_b_evals` 等）。议题一"上升沿 vs 下降沿"
分桶的数据来源。

### 3.3 round 循环（58656–63048，上限 100000 轮，实测恒 2 轮收敛）

每轮依次：

| 行号 | 动作 |
|---|---|
| 58660–58666 | 恒激活组置位 `cpu_flags[771..777]`（每轮必跑的任务） |
| 58667–58671 | profile 开轮计数 |
| 58672–58738 | **compute 分派**：67 个 `if(cpu_flags[i]\|\|…\|\|cpu_flags[i+10])cpu_task_N();`——每轮 ~780 次字节测试，议题二实测全模型最热指令所在 |
| 58739–58745 | **commit 分派**：`cpu_word8(flags,0,8)` 打包测试低 8 字节，再 `flags[0]→task_68/69`、`flags[2]→task_70`（寄存器/内存提交任务，原理见 §4）；tick → `compute_ns`/`commit_ns` 分界 |
| 58748–58751 | `cpu_publish()`（函数体在 ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:43677）+ tick → `publish_ns` |
| 58752–58758 | 域臂回灌：`cpu_next_arms` → `cpu_flags[0]/[2]`（commit 任务的跨轮武装，8 字节桶空预筛） |
| 58759–58760 | `if(!cpu_again)` 静止判定 → 走 3.4 出口；否则继续下一轮 |

### 3.4 静止出口：输出拷回（58760–63047）

`!cpu_again` 时：先 flush `$display` 暂存 `cpu_strobes`，然后
**每个输出端口一行** `this->io_*=cpu_at<T>(cpu_objects.get(),off)`
（58764 `io_enq_canAccept` 起，到 63038 `gatewayIn_packed_20_bore` 止，~4.3k 行），
profile 尾计数，`return`。

### 3.5 不收敛兜底（63049）

round 上限耗尽仍未静止：`throw std::runtime_error("CPU model did not converge")`。

> 注：emitter 还有"下降沿省略快路径"（fp elision，生成在沿分类之后、round 循环之前），
> Rob 不满足资格（`fp_evals=0`），生成代码中无此段。

## 4. commit 任务原理（提交阶段）

### 4.1 两类 op：compute 与 commit 的分工

调度器按 `graph.domain[op]` 把 IR op 划成计算域 / 事件域（wolvrix/lib/grhsim/backend/cpu_schedule.cpp:695）：

- **compute op**：组合求值，任一输入变化就被激活，跑在 round 的 compute 分派段；
- **commit op**：会改状态的 op——`core.state.write`（寄存器）、`core.state.memWrite` / `memWriteSeq` / `memFill`（内存）、`core.state.latchWrite`（守卫恒 true，wolvrix/lib/grhsim/backend/cpu_emit.cpp:4853）——由事件沿（posedge clock）守卫，跑在 commit 分派段。

分工原则：**compute 阶段把每次写的 enable/data/mask 预计算进 `cpu_boundary`（compute 任务直写边界区，仅 task_33 就有 7,520 处），commit 任务只读边界值做"沿检测 + 应用"**。所以 commit 任务体又大又笨：task_68 的 3 万行几乎全是 `if(enable) cpu_write_cell_cf(...)`，没有组合求值。

为什么必须分两相（NBA/寄存器传输语义）：上升沿时刻所有寄存器 RHS 必须用**沿前旧值**求值，且新值对下游的可见性必须原子发生。实现上 commit 写同样走 shadow + pending（§6 写路径），`cpu_publish` 统一回拷并扇出，**下一 round 的 compute 才读到新寄存器值**。这就是 §3.3 的 compute 分派 → commit 分派 → publish 顺序，也是实测恒 2 rounds 收敛的原因：round 0 结算组合 + 提交，round 1 传播新寄存器值。

### 4.2 边沿检测：把"电平"还原成"边沿"的记忆机制

**高层问题**：`eval()` 看到的时钟是**电平**——bench 每周期调两次，clock=0 一次、clock=1 一次。
而 commit op 的语义是**边沿**触发（`posedge clock`）。从电平序列还原边沿，必须有一点记忆：
"上次这个时钟是什么电平"。这个记忆就是 **history 状态**：每个事件（时钟）一个字节，
存在 `cpu_objects` 里，记录本域上次运行时该事件的电平。沿守卫
`!history && event`（posedge；emitter `commitEdgeGuard`，wolvrix/lib/grhsim/backend/cpu_emit.cpp:4848，
:4859 拼出 `!history && event`）就是拿记忆和现状对拍。

于是每次 commit 任务被唤醒，只有四种情形：

| history（上次） | event（本次） | 含义 | 该做什么 |
|---|---|---|---|
| 0 | 0 | 无变化 | 什么都不做 |
| 1 | 1 | 无变化 | 什么都不做 |
| 1 | 0 | 下降沿（对 posedge 域是无效沿） | 只把 history 更新成 0 |
| 0 | 1 | **上升沿** | 跑全部写体，再把 history 更新成 1 |

**两级快速出口就是这张表的前三行被压成两次廉价检查**（以 task_68 为例，
ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_68.cpp）：

1. `cpu_stable_history_scan`（:10–:11）覆盖表的前两行：**"有没有任何事件变过电平？"**
   2026-09-29（TODO-1）起按退化程度分级发射：单组单字节 → 纯比较
   `if((cpu_at<bool>(cpu_obj_,14730)==bool(cpu_event_snapshot_0)))return;`（IIFE/memchr 形态已消除）；
   单组连续多字节 → 裸 `!std::memchr(...)`；非连续 offsets 表保留 IIFE 兜底；多组 `&&` 连接；
2. `cpu_inactive_edge_sample`（:12–:16）覆盖第三行：事件当前为低 ⇒ 无效沿，
   只写 history 就返回，**8,192 个写体一条不执行**——议题一实测下降沿 commit 仅
   ~0.17 µs/eval（上升沿 23.3 µs）就是这个出口的效果；
3. 落到第四行才是真沿：算一次共享的 `cpu_edge_snapshot_0`（:17–:18，`uses=8192`），
   一次沿判定服务全任务 8,192 个 commit op。

**历史扫描扫的到底是什么**：扫的是本任务全部事件的 history 字节——即"每个时钟的上次电平"
这几个字节本身（不是写数据、不是标志位）。逐事件拿它的 history 字节和该事件的当前电平比：
全部相等 ⇒ 没有沿 ⇒ 整个任务跳过。
emit 侧按事件分组、组内去重历史字节（`stableCommitHistories`，wolvrix/lib/grhsim/backend/cpu_emit.cpp:6138）。
Rob 里同一时钟的 8,192 个 op 引用**同一个** history 状态对象，去重后只剩 1 字节，所以注释
`histories=8192 groups=1`、命中单组单字节纯比较形态（task_68 obj+14730）；task_70 有两个事件 → 两组
`&&` 连接（obj+26215 / +26216）。history 字节能这么做的资格判定：1 位两态、恰好 1 字节、
仅被本任务私有引用（`privateByteHistories_`，wolvrix/lib/grhsim/backend/cpu_emit.cpp:2856）。

**为什么下降沿也必须跑任务**（哪怕只为更新 history）：不更新的话 history 停在 1，下次
clock 0→1 时 `!history && event` = false，上升沿会被丢掉。所以调度器按"**任何跳变都武装域，
包括反向沿**"挂边（wolvrix/lib/grhsim/backend/cpu_schedule.cpp:726 注释：to sample histories），
无效沿路径上也有专门的采样发射。history 的写本身走 direct-commit（见 4.3 第三种形态），
在任务末行落成 `cpu_at<bool>(cpu_obj_,14730)=...cpu_event_snapshot_0...`（grhsim_Rob_task_68.cpp:29877）。

以上各段在生成代码里的发射顺序固定在任务开头（emitter `taskBody`，
wolvrix/lib/grhsim/backend/cpu_emit.cpp:6361 起：事件快照 → stable scan → inactive sample
→ 共享沿布尔），每段前有 `/* [phase] */` 注释（grhsim_Rob_task_68.cpp:3–:18）。

### 4.3 commit op 的三种发射形态（emitter `commit()`，wolvrix/lib/grhsim/backend/cpu_emit.cpp:5064 起）

1. **寄存器 masked merge**：`(next & ~mask) | (data & mask)` 经 `cpu_stage` 进 shadow；同一状态被重复写时先读 `dirty?shadow:obj` 保持程序序。宽位（>64）走 `grhsim_apply_masked_words_inplace`。
2. **内存写**（memWrite / memWriteSeq / memFill）：`cpu_write_cell` 四形态之一（TODO-5）——Rob 的 commit 体量几乎全是这种。2026-09-29（TODO-3/4）起为**两级嵌套守卫**形态：

   ```cpp
   if(cpu_edge_snapshot_0){ // cpu_mem_guard_hoist ops=6        ← 同沿守卫的连续写段（≥4）合并
       if(cpu_at<bool>(cpu_bnd_,1149)){ // cpu_mem_enable_hoist ops=6   ← 段内同使能连续写（≥2）再嵌套
           cpu_write_cell_cf<std::uint16_t,9>(cpu_obj_,cpu_shadow_,48798,113088,6758,8,true,cpu_at<std::uint16_t>(cpu_bnd_,35652));
           ...
   ```
   （grhsim_Rob_task_68.cpp:34–:38；常量行号已折进 key/offset 字面量，无运行时边界检查——TODO-4。
   task_68/69/70 分别有 guard 块 606/105/4 个、enable 块 607/178/0 个。）
3. **direct-commit 标量**（`directCommitBody`）：能证明"下一 compute 阶段前没有任何 commit 观察者"的单写者状态，跳过 shadow 直写 `cpu_objects` + 内联扇出；history 状态走这种。

另有 64 口一组的 compact walk 发射形态（描述符表 + ctz 遍历武装位），Rob 未命中资格，生成代码 0 处。
另有 **内存写直写**（`cpu_write_cell_direct[_f]` + `planDirectMemories`）：机制已实现但 Rob 实测
净亏损（−5~6%，全配置见 bench 文档 §4 末），**默认关闭**，实验开关 `GRHSIM_DIRECT_MEM=1`。

### 4.4 武装与分派：commit 任务何时跑

- **输入阶段直置**：clock 口变化 `cpu_flags[0]|=1; cpu_flags[2]|=1`（ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:44116–:44118；reset 变化也置 flags[2]，:44131）——round 0 的 commit 分派必跑；
- **round 内分派**：compute 之后先 `cpu_word8` 打包测低 8 字节，再按字节派任务（:58741–:58745），flags[0]→task_68/69、flags[2]→task_70；
- **跨轮武装**：compute/publish 改了事件值或 history → 置 `cpu_next_arms`，轮末回灌 `cpu_flags[0]/[2]`（grhsim_Rob.cpp:58752–:58758）；history 的自武装已被静默化；
- **效果扇出**：commit 改变的状态经 publish 的 `commitStateFanout` 表激活下游——每个 state 读者都挂在这张表上（wolvrix/lib/grhsim/backend/cpu_schedule.cpp:706–:713），寄存器新值 → 下游 compute 任务置位 → `again=true` → 下一 round。

### 4.5 Rob 的三个 commit 任务（67 计算 + 3 提交）

| 任务 | 源行数 | commit op 数 | 事件 | history 位置 |
|---|---:|---:|---|---|
| `cpu_task_68` | 29,878 | 8,192 | 1 个（clock，边界 640） | obj+14730 |
| `cpu_task_69` | 17,709 | 3,901 | 1 个（同 clock） | obj+14733 |
| `cpu_task_70` | 14,680 | 9,308 | 2 个（边界 640 / 760） | obj+26215 / +26216 |

- 68/69 同由 flags[0] 唤醒、70 由 flags[2]：武装/分派的粒度是**事件域**，一个域的分区合成一个任务；
- 合计 21,401 个 commit op（14,748 个 `cpu_write_cell_*` 调用点），但上升沿 commit+publish 只花 ~31 µs（议题一 profile）：大多数写体 enable 为假，`cpu_write_cell_*` 的等值早退再滤一批；实际成本 = 任务内守卫/使能测试（TODO-3 已去重到每行使能一次）+ 命中写走的 helper。

## 5. 任务函数形态（ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_*.cpp）

以提交任务 ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_68.cpp（29,878 行，函数体起点 :2）
和计算任务 ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_33.cpp 为例：

```cpp
void GrhSIM_Rob::cpu_task_68(){
    /* [phase] commit 任务体：事件快照 → 稳定历史快速出口 → 无效沿快速出口 → 共享沿布尔 →
       内存写端口 walk（同守卫/同使能分组嵌套）→ 武装端口 walk → 事件历史回写。 */
    std::byte *cpu_obj_=cpu_objects.get();      // 本地化三个基址，后续全走寄存器
    std::byte *cpu_bnd_=cpu_boundary.get();
    std::byte *cpu_shadow_=cpu_shadow.get();
    const bool cpu_event_snapshot_0=cpu_at<bool>(cpu_bnd_,640);   // 事件快照 locals（:9）
    /* [phase] 稳定历史快速出口：... */
    if(/* cpu_stable_history_scan histories=8192 groups=1 */ (cpu_at<bool>(cpu_obj_,14730)==bool(cpu_event_snapshot_0)))return;
    /* [phase] 无效沿快速出口：... */
    if(!(false || cpu_event_snapshot_0)){ ...只回写 history... return;}
    /* [phase] 共享沿布尔：... */
    const bool cpu_edge_snapshot_0=(false || (!cpu_at<bool>(cpu_obj_,14730) && cpu_event_snapshot_0)); // uses=8192
    /* [phase] 内存写端口 walk：... */
    if(cpu_edge_snapshot_0 && cpu_at<bool>(cpu_bnd_,1148)){   // 落单行内守卫（短 run 不合并）
        cpu_write_cell_cf<bool,1>(cpu_obj_,cpu_shadow_,59358,148640,8666,360,true,cpu_at<bool>(cpu_bnd_,62581));
    }
    if(cpu_edge_snapshot_0){ // cpu_mem_guard_hoist ops=6      // 同守卫长 run 合并
        if(cpu_at<bool>(cpu_bnd_,1149)){ // cpu_mem_enable_hoist ops=6   // 同使能再嵌套
            cpu_write_cell_cf<std::uint16_t,9>(...);
            ...
```

- 任务 = 一个分区（partition）的直线化组合逻辑，无循环调度内部状态；
- 任务内的 guard 提升块会把共享子表达式提到 `cpu_helper_*`（声明在 ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6226 起）；
- 写内存行走 `cpu_write_cell_<形态>`，写标量走 `cpu_write_scalar`/`cpu_stage*`；
- compute 任务头是 `/* [phase] compute 任务体：... */`，commit 任务头是上图第一行；
  任务体内的 `[phase]` 注释刻意**不含任何数字**（shapeTwinShare/branchShapeShare 文本折叠依赖
  任务文本一致，含数字会破坏 twin 折叠）。

## 6. 写路径与发布语义（性能议题的核心机制）

写不是即时的，而是 **COW + 延迟发布**：

1. 任务里 `cpu_write_cell_cf`（ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6079）：
   读 current（脏则读 shadow 否则读 obj）→ trunc → **等值则直接返回** →
   首次脏时 `cpu_pending.push_back` + 置 dirty → 写 shadow。
   （部分 mask 的动态行写走通用版 :6046；`_f`/`_c` 为全 mask/常量行特化——TODO-5。）
2. round 末尾 `cpu_publish()`（ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:43677）：
   遍历 pending，`memcmp` 确认真有变化 → `memcpy` 提交回 `cpu_objects` →
   按 `cpu_targets`/`cpu_memory_readers` 表扇出置下游任务标志 → 清 dirty。
   返回值的 `again` 决定 round 循环是否继续。

这套机制保证同一 round 内读到的是旧值、写入互不干扰（NBA 语义），同时把"变化→激活下游"
做成查表。TODO-6 的直写实验（跳过 shadow/pending/publish）已实测为净亏损并默认关闭：
publish 的批处理回拷与 gsim 的 `$NEXT` 整组回拷同构，是该结构的优点而非负担（数据见
`pdocs/rob_standalone/rob-trace-replay-bench-20260929.md` §4 末）。

## 7. 静态规模一览（Rob，TODO 六项落地后）

| 指标 | 值 |
|---|---|
| 总行数 | ~148 万（70 个 task cpp 142 万 + 主 cpp 6.3 万 + init 136 行 + hpp 6.2k） |
| 状态区 cpu_objects / shadow | 各 158,272 B |
| 边界区 cpu_boundary | 161,488 B |
| 输入快照 cpu_inputs | 2,920 B |
| 脏位 cpu_dirty | 64,063 B（状态数+内存行数） |
| 任务数 / 标志字节 | 70 任务（67 计算 + 3 提交）/ 778 B |
| 扇出表 cpu_targets / memory_readers | 30,944 / 11,909 条 |
| eval() 静态行数 | ~19.3k 行（43700–63049）；编译后函数体 231,803 B（nm 实测，TODO 六项前后不变；对照 gsim `step()` 142 B） |
| `[phase]` 段首注释 | 主 cpp 1,137 处 + 每任务函数头/相位若干（TODO-2） |

## 8. 优化讨论挂接点（已测→待改）

| 现象（实测） | 结构出处 | 状态 |
|---|---|---|
| 每 round 780 次字节标志测试是全模型最热指令 | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:58673 | 待做：dispatch 扫描合并为 u64 字测试 |
| 1 位写 helper 调用开销（原 `cpu_write_cell<bool,1>` 3.84% 周期、78% 是调用约定） | ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6046 | **已部分落地（2026-09-29，TODO-5）**：四形态特化消掉 9 个编译期常量参数；归一化打平。always_inline 全域展开已被实测否决（I-cache 膨胀 −13%） |
| commit 写体守卫重复 + `cpu_men_*` 预读 + 常量行号冗余文本 | grhsim_Rob_task_68.cpp:34 | **已落地（TODO-3/4）**：两级守卫嵌套（guard 715 块 / enable 785 块）、`cpu_men_` 归零、边界检查 14,748→176；性能中性 |
| 边沿历史扫描 IIFE+memchr 1 字节形态 | grhsim_Rob_task_68.cpp:11 | **已落地（TODO-1）**：分级发射，Rob 命中纯比较形态；性能中性（预期内） |
| 生成代码无注释、靠外部文档对照 | 全部生成文件 | **已落地（TODO-2）**：`/* [phase] */` 段首注释 1,100+ 处 |
| commit 内存写直写化（去 shadow/publish/publish 扫描） | grhsim_Rob.hpp:6088–:6109 | **已实测否决（TODO-6）**：全直写 −5~6%、混合 −12%，默认关闭（`GRHSIM_DIRECT_MEM=1` opt-in）；publish 批处理形态是该结构的优点 |
| 输入检测段：拷贝/比较两段式内存往返 + 扇出字节粒度 | 原 grhsim_Rob.cpp:43713/45223 | **已落地（议题四）**：融合比较-更新-扇出 + `cpu_or8` 打包；源码 -41 万行，但收益在噪声级（归一化 +2.6%≈机器波动；二进制几乎不变——clang 本就在合并连续字节 OR，且未变口的扇出体被 cold-block 跳过）。教训：这段不是热点，静态膨胀 ≠ 动态成本 |
| 双 eval × 2 rounds | bench 驱动 + round 循环 ptmp/xs-components-rob/grhsim-model/grhsim_Rob.cpp:58659 | 议题一结论：两相对称，无便宜可占 |

## 9. 复现与再生成

```bash
# 重新生成模型（发射器改完后必做：删目录强制重生成）
source env.sh && make build && make py_install
rm -rf ptmp/xs-components-rob/grhsim-model
make -C testcase/xs-components -f rob.mk rob-grhsim-model

# 功能门槛：verify 全过且 checksum == 0xd27a5e546e6474cc
make -C testcase/xs-components -f rob.mk rob-bench-trace ROB_BENCH_VERIFY=100000 ROB_BENCH_REPEAT=3

# 直写实验（默认关闭；可选读者数上限）
GRHSIM_DIRECT_MEM=1 GRHSIM_DIRECT_MEM_MAX_READERS=8 make -C testcase/xs-components -f rob.mk rob-grhsim-model
```
