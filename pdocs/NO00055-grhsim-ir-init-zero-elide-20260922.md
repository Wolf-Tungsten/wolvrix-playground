# NO00055 GrhSIM-IR init 零存储省略（P6）

节点目标（2026-09-22 用户门）：缩减二进制、缓解 ICache 压力，允许 ≤3% 性能回撤。old 对照：`ptmp/no00054_branch_shape_fold_20260921/flow-final2`（预注册比较值 **71.043000 s**，NO00054 正式 new 均值）。

## 机制（一句话）

`init()` 在调用全部 `cpu_init_*` 分块之前已 `std::memset(cpu_objects.get(),0,layout_.objectBytes)` 清零整个对象 arena（`cpu_emit.cpp` driver，memset 先于 chunk 调用），因此**零值初始化写入是对已零字节的重复**——const 标量零存储、全零 const 数组 memcpy、零值 fill 的 memset 全部可以省略；仅当同一 state 此前（按发射序）已有非零写入时零写才承重，此时保留（per-state 保守粒度）。

## 设计要点

- 预分析（emit 期一次，memoize）：按 initRecords 发射序模拟，维护 per-state `dirty`（已有非零写）标志；`core.init.const`（标量零 / 数组全零）与 `core.init.fill`（value 文本为零，含 x/z→0 的两态投影）为零写候选，`readmem`/`random` 数据相关永不省略；`zero && !dirty` → 入省略集，非零写置 dirty。
- 发射端 `initStep` 仅抑制输出，**全部校验原样保留**（标量 value 缺失、数组范围越界、value/random 互斥、字面量解析在 build 阶段已先行触发）；`covered` 覆盖记录不受省略影响，数组覆盖率检查语义不变。
- 省略连块作用域 `{}` 一起去掉；空 chunk 函数合法保留。
- 语义依据链：cpu_init_* 唯一调用点是 `init()`（memset 之后）；标量/数组 state 存储恒在 cpu_objects arena；state 间偏移不重叠由 layout 保证；`cpu_bind_strings` 写 string 槽位与 logic state 不相交。

## 普查数据（flow-final2 model，与 20260921 梳理文档 P6 一致）

- 100 个 init 函数：标量存储行 285,203，其中零值 **283,967（99.6%）**，非零 1,236；零值 fill memset **122,824**；宽标量（>64b）const memcpy 873；const 数组块 0、readmem 块 0（XiangShan 不用这两条路径，机制仍通用覆盖，HDLBits/testInit 夹具覆盖）。
- init .text 基线（clang++ -O3，`size -A *.o` 求和 `^.text` 段）：**2,627,809 B**；model 总 .text 同尺 69,200,409 B。

## 结果

### 单测（2026-09-22）

- `testInitZeroElide` 加入 `test_cpu_emit.cpp`：零标量/全零 const 数组/零 fill（首写）被省略、非零后零 fill 承重保留、混合 const 保留、宽标量零省略/`'1` 保留；`testInit` 原有 ASan/UBSan 实跑夹具（含 x→0、fill0+readmem、fill0+random 三个可省略路径）行为校验通过；`make test_grhsim_cpu_emit` 通过（95.3s）。

### reemit 冒烟（同 checkpoint 快速通道，2026-09-22）

- 命令：`make reemit_grhsim_ir GRHSIM_REEMIT_MODEL=…/flow-final2/xiangshan_grhsim_ir.json GRHSIM_REEMIT_FLOW=…/flow-reemit` + `COMMIT_COMPACT_WALK=1 COMMIT_MEM_WALK=1 SHAPE_TWIN_SHARE=1 BRANCH_SHAPE_SHARE=1 BRANCH_SHAPE_HOTNESS=…/task_hotness.tsv BRANCH_SHAPE_GROWTH_BUDGET=5.0`（与 flow-final2 完全同选项）。
- 发射确定性：除 100 个 `*_init_*.cpp` 外全部生成源文件与 flow-final2 逐字节一致。
- 标量存储行 285,203 → **2,108**（零存储 283,967 → 3）；零 fill memset 122,824 → **0**；宽 memcpy 873 → 4。
- **init .text（clang++ -O3，`size -A` ^.text）：2,627,809 → 43,645 B（−2,584,164 B，−98.3%）**；**model 总 .text 同尺：69,200,409 → 66,616,245 B（−2,584,164 B，−3.74%）**——总缩减恰好等于 init 缩减，无其他发射变化。

### 正式门（flow-final，2026-09-22）→ ACCEPTED

- gen **800.58s**、build **195.30s**（均 <1800，nproc=32）；HDLBits DUT=001 通过；正式模型 init 统计与冒烟逐值一致（2,108 存储行 / 0 memset / 100 chunk）；hpp 含 1,515 个 `cpu_blk_` 声明（与 flow-final2 相同，分支共享发射确定）。残留的 3 处 `UINT64_C(0)` 均为非零宽值（`{1,0,…}`）的高位填充——纯零存储 100% 省略。
- **model .text（clang++ -O3，`size -A` ^.text 尺）：69,200,409 → 66,616,245，−2,584,164 B（−3.74%）**；其中 init 部分 2,627,809 → 43,645（−98.3%），总缩减恰好等于 init 缩减。emu text（Berkeley `size` 尺，含 rodata）：85,181,862 → 82,597,710（−2,584,152 B，−3.03%）。
- **正式 6 次交替（预注册顺序 old1/new1/…，比较基线 71.043000 s，止损 106.56s）：old 71.110/71.203/71.200（均值 71.171000，SD 0.053），new 71.770/71.080/71.079（均值 71.309667，SD 0.399）→ +0.195%（≤3% 预算，统计中性：U=3、p=0.35）**；6/6 make_exit=0、emu_exit=0、endpoint `[240349, 99996, 100001, 0x80000c0c]` 全一致，无 DIFFTEST mismatch。结果：`ptmp/no00055_init_zero_elide_20260922/formal/summary.json`（`rank_gate_pass=false` 对回退场景恒假，按用户调整门以均值差 ≤+3% 判定）。
- 按 2026-09-21 用户调整门（100k 行为正确 + 回退 ≤3% + 二进制减小）判定 **ACCEPTED**。零风险机制如实兑现：init 代码不在热路径（仿真启动一次），+0.195% 在窗口噪声内（同窗 old SD 0.053s vs 差值 0.139s）。

## 后续方向

- 分支体共享预算再上探（5.0→更高；NO00054 实测 +0.74%、NO00055 +0.19%，各自节点预算独立）。
- 常量表跨组去重（branch 65.2 万 + twin 76.9 万槽，省 rodata，不直接缓解 I$）。
- goal.md 尾部候选清单其余项（boundary 写回批量/位打包、commit write_cell 形态、管线末端 canonicalize）。
