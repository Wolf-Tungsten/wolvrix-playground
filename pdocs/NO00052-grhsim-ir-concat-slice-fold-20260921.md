# NO00052: concat-of-slices 恒等/区间折叠（canonicalize-compute 扩展 + pack 后重跑）

日期：2026-09-21。状态：进行中。

## IDEA

### 假设

`grhsim.pack-bit-registers` 把 2–64 个同控制 1-bit 寄存器打包为 `packed_bits_<id>` word，
并把每个原 `core.state.read` 改写为 `core.compute.sliceStatic(packed, bit, bit)`。
IR 中原本"把 N 个独立 bit 寄存器 gather 成一个字节/字"的 `core.compute.concat` 因此退化为
**同一源值的连续切片拼接**：

```text
concat(sliceStatic(x,w-1,w-1), ..., sliceStatic(x,0,0)) ≡ x            （全覆盖恒等）
concat(sliceStatic(x,hi,..), ..., sliceStatic(x,lo,..)) ≡ sliceStatic(x,lo,hi)  （连续区间）
```

但流水线中 `grhsim.canonicalize-compute` 在 pack-bit-registers **之前**运行
（`scripts/wolvrix_xs_grhsim_ir.py` CPU_PIPELINE），pack 之后只有
bitwise-muxes / mux-chain-fold / used-bits，没有任何 pass 折叠该恒等式。
CPU emitter 只能照字面发射：每个 8 位组 = 8 条 slice（shift+mask+cast+bool 帧存储）
+ 8 层嵌套 concat + trunc，再经 changed 比较写 boundary（实测生成代码
`grhsim_SimTop_task_98.cpp` 中 6 组 × 17 句）。理论上整组可用一条字节拷贝完成。

**机制**：在 `grhsim.canonicalize-compute` 中新增 concat-of-slices 折叠规则
（恒等 → 接引源值；连续区间 → 原 op 就地改写为单个 sliceStatic，op/result id 不变、
继续走 CSE），并在 pack-bit-registers 之后重跑该 pass
（mapping 反正因 pack 失效重跑，无额外 mapping 成本；死切片由后续 used-bits 死锥消除回收）。

### 瓶颈证据与覆盖面（对当前 HEAD checkpoint 的全 IR 普查）

普查对象 `ptmp/cpu_emit_indent_20260921/flow/xiangshan_grhsim_ir.json`
（当前 HEAD `9b90c91`/`59e59e8` 全流水线产物，3,590,106 op）：

| 类别 | 数量 | 折叠结果 |
| --- | --- | --- |
| 恒等 concat（全覆盖、顺序，源宽分布 2–64，8 位 274 个） | 343 | 接引源值 |
| 连续区间 concat | 670 | 单个 sliceStatic |
| 全覆盖纯反转/任意置换 | 10 + 4 | 不折（太少，不值得专用 op） |
| 其他同源非连续/重复 bit | 2029 | 不折 |

涉及 slice op 约 6,727 个（其中 5,214 个 slice 结果另有用户，折叠后保留；
concat 本身必消失）。局部收益目标：消除 ~1,013 个 concat op 及其发射语句、
frame bool 槽与相应 boundary 流量；预计运行收益小（静态 op 占比 ~0.2%），
同时减少生成文本与编译输入。

### 可证伪标准

- 语义：折叠仅在结果类型与折叠后形态完全一致（同 TypeId 或 uN two-state unsigned、
  宽度相等）时触发；100k NEMU 对拍无 mismatch、HDLBits 回归通过。
- 收益（**2026-09-21 用户调整验收门，取代标准 6 次交替统计显著门**）：
  本节点判 ACCEPTED 只需同时满足——① 100k 仿真行为正确（NEMU 对拍无 mismatch、
  instrCnt/cycleCnt/IPC 与 old 一致）；② 性能相对 old 均值下降不超过 3%
  （6 次新旧交替测量照旧执行并完整记录，作为降幅判定依据）；③ 生成代码中
  字节拆分重复模式（同源连续 slice+concat）消失。超出上述三条的统计显著性
  不作本节点要求。

## BASELINE

- 基线 commit：根仓库 `9b90c91` + wolvrix `59e59e8`（NO00051 收尾后唯一新增为
  emit 缩进美化，token 级等价，不影响编译产物语义）。
- old 对照（预注册）：`ptmp/no00049_used_bits_20260920/flow-final`，
  预注册比较值 **70.419333 s**（Host time，100k 配置同 goal 文档）。
- 工作区实验差异：wolvrix `canonicalize_compute.cpp` 增加折叠规则；
  `scripts/wolvrix_xs_grhsim_ir.py` CPU_PIPELINE 在 pack-bit-registers 后插入
  `grhsim.canonicalize-compute`；`scripts/reemit_grhsim_ir.py` 与 Makefile
  增加 reemit 筛选开关；聚焦单元测试。
- 输入身份：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，
  `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`XS_EMU_CPU=2`、waveform/commit/RAM trace 关闭、
  cycle 上限 100000。
- 计时边界：SV→C++ 生成 Make 启动至 model 完成 <1800 s；C++ 编译 <1800 s
  （VM_BUILD_JOBS=$(nproc)=32，记录实际 job 数）；仿真仅 emu 执行区间，
  超过 old 预注册值 1.5 倍（105.6 s）立即终止记 REGRESSION_KILLED。
- 交替协议（预注册）：顺序 old1/new1/old2/new2/old3/new3，每次运行前
  posix_fadvise 驱逐页缓存（NO00040 修正协议），由 `make benchmark_grhsim_ir`
  执行；任一 INVALID 作废补跑，两组各保 3 次有效。

## IMPLEMENTED

改动（工作区未提交版本 vs 基线 `9b90c91`/`59e59e8`）：

- `wolvrix/lib/grhsim/pass/canonicalize_compute.cpp`：拓扑遍历前新增
  concat-of-slices 折叠。全部 operand 为同一 two-state logic 源值的
  `sliceStatic`、位段 MSB 优先首尾相接且总宽等于结果宽度时：全覆盖且源/结果
  同完整 TypeId → 接回源值（`concat_identity_folds`）；否则结果 unsigned
  two-state → 原 concat op 就地 `replaceOperation` 为单个
  `sliceStatic(x,lo,hi)`（`concat_range_folds`），op/result 标识不变、继续参与
  后续拓扑 CSE。空缺/逆序/跨源/四态源/有符号结果保守保留。诊断键新增
  `concat_identity_folds`、`concat_range_folds`。
- `scripts/wolvrix_xs_grhsim_ir.py`：`CPU_PIPELINE` 在 `grhsim.pack-bit-registers`
  后插入 `grhsim.canonicalize-compute`（mapping 因 pack 失效重跑的既有路径不变）。
- `scripts/reemit_grhsim_ir.py` + `Makefile`：新增
  `GRHSIM_REEMIT_CANONICALIZE_COMPUTE=1` 筛选开关（canonicalize 在 used-bits 前）。
- `wolvrix/tests/grhsim/test_grhsim_ir.cpp`：新增 `runConcatSliceFoldTest`
  （恒等折叠、多用户 slice 保留、区间折叠就地改写 + 与既有相同 slice 的 CSE 合并、
  空缺/逆序/跨源/四态源/有符号五类守卫、幂等、JSON round-trip）。
- 文档：`wolvrix/docs/grhsim_ir/flows/cpu-st.md` 补记折叠规则与 pack 后重跑。

聚焦测试（`make test_grhsim_cpu_mapping/schedule/emit`）：全部通过
（日志 `ptmp/no00052_concat_slice_fold_20260921/test-{mapping,schedule,emit}.log`）。
调试记录：初版测试误用 compaction 前的 ValueId 比较 pass 后结果（compaction 会
重编 value id），改为按端口结构解析；pass 实现本身一次通过。

筛选（reemit 路径，仅冒烟，不作正式证据）：NO00049 final checkpoint
`ptmp/no00049_used_bits_20260920/flow-final/xiangshan_grhsim_ir.json`
→ canonicalize + used-bits + remap + emit（`flow-v1`）。诊断：
`concat_identity_folds=359 concat_range_folds=670`（与全 IR 普查 343+670 一致，
恒等多项略多因普查对象是当前 HEAD checkpoint 而筛选基于 NO00049 checkpoint）；
另有 `identity_assigns_removed=3569 common_expressions_removed=61041`
——这是对**最终** checkpoint 重跑 canonicalize 的附带收益，来自
bitwise-muxes/mux-chain-fold/used-bits 之后暴露的重复；正式管线
（canonicalize 紧随 pack）不含这部分，筛选与正式模型的差异在 VALIDATED 中说明。
生成文本 1116→1056 MB（−5.4%，含附带 CSE 效应）；字节拆分 pattern
（`slice_dynamic_u64(trunc(cpu_cached_state_*,8),i,1)`）3183→1118 处。

筛选编译 fresh 205.00 s（VM_BUILD_JOBS=32）。筛选 pair（old1/new1，页缓存驱逐，
预注册基线 70.419333 s）：old 69.865 / new 70.012（−0.210%，单对噪声范围，
不作证据）；两侧 `instrCnt=240349 cycleCnt=99996 IPC=2.403586` 完全一致、
difftest 无 mismatch——折叠后模型 100k 行为等价（日志
`ptmp/no00052_concat_slice_fold_20260921/screen-v1.log` 及 `screen-v1/`）。

## VALIDATED

### 生成与模式消除（门槛①③的静态证据）

- 完整 SV→C++ 生成（`formal.sh gen`，kill-switch 1800 s）：**735.29 s** 通过
  （日志 `ptmp/no00052_concat_slice_fold_20260921/gen-final.log`；
  曾因后台任务 600 s 默认超时中断一次并清理重跑，与产物无关）。
  管线顺序确认：canonicalize(62.75 s) → pack-bit-registers → canonicalize(3.65 s)
  → bitwise-muxes → mux-chain-fold → used-bits → 第二轮 mapping。
- IR 规模：op 3,590,106→**3,531,463**（−58,643，−1.63%）、value 同步 −58,643、
  state 不变。削减主要来自 pack 后重跑 canonicalize 的折叠与 CSE。
- **模式消除（验收门③）**：对最终 checkpoint 普查"同源连续 slice 喂 concat"——
  恒等 343→**0**、区间 670→**1**（唯一残留为守卫拒折的角落形态）；
  生成 C++ 中字节拆分 slice 站点 3183→1118（剩余为结果被其他逻辑复用的独立 slice，
  不再存在"8 slice+concat 拼回原字节"的组）；task 文件 4636→4540，
  生成文本 1116→1058 MB（−5.2%）。

### 编译、回归与 100k 等价（门槛①②）

- fresh 编译（`formal.sh build`，VM_BUILD_JOBS=32=nproc）：**199.71 s** 通过；
  HDLBits DUT=001 回归通过（`hdlbits-001.log`）。
- 正式 6 次新旧交替（`formal.sh formal`，预注册顺序 old1/new1/old2/new2/old3/new3，
  每次运行前 posix_fadvise 驱逐页缓存，old=`ptmp/no00049_used_bits_20260920/flow-final`，
  预注册基线 70.419333 s，截止 105.629 s，cpu=2、threads=1、100k、trace 关；
  `ptmp/no00052_concat_slice_fold_20260921/formal{,/preregister.json,summary.json}`）：

| run | Host s | run | Host s |
| --- | --- | --- | --- |
| old1 | 70.312 | new1 | 70.550 |
| old2 | 71.568 | new2 | 70.241 |
| old3 | 70.391 | new3 | 70.440 |

  old 均值 **70.757000 s**（SD 0.703456），new 均值 **70.410333 s**（SD 0.156622）；
  new 相对 old **快 0.489940%**（无回退，远低于 3% 降幅门）；new 均值相对预注册
  70.419333 s 为 −0.0128%（持平）。六次全部 `instrCnt=240349 cycleCnt=99996
  IPC=2.403586`、末端 PC `0x80000c0c`、guest cycles 100001、退出码 0、
  DIFFTEST 无 mismatch（验收门①）。
- 参考统计（非验收依据）：U=4、单侧精确 p=0.5、rank gate 未过——交替窗口内
  new/old 秩次交错，差异与噪声不可区分；与用户调整门一致，不作显著性声明。

## 最终判定

**ACCEPTED**（按 2026-09-21 用户调整验收门）：① 100k 行为正确（六次交替全部
NEMU 对拍无 mismatch、计数器/末端 PC 与 old 完全一致）；② new 均值 70.410333 s
相对 old 均值 70.757000 s 快 0.489940%，无回退（≪3% 降幅门）；③ 生成代码中
同源连续 slice+concat 重复模式消失（恒等 343→0、区间 670→1、字节拆分站点
3183→1118、不再存在 8 slice+concat 拼回原字节的组）。生成 735.29 s、编译
199.71 s 均低于 1800 s 门槛；HDLBits DUT=001 通过。

机制回收：`grhsim.canonicalize-compute` 新增 concat-of-slices 折叠
（`concat_identity_folds` / `concat_range_folds` 诊断键），并在
`grhsim.pack-bit-registers` 后重跑；op −58,643（−1.63%）、生成文本 −58 MB
（−5.2%）、task 文件 −96。筛选与正式模型差异说明：筛选构建在 NO00049 最终
checkpoint 上重跑 canonicalize+used-bits（含 bitwise-muxes/mux-chain-fold/
used-bits 后暴露的额外 CSE 3,569 assigns / 61,041 表达式），正式管线
（canonicalize 紧随 pack）不含该部分，两者不做 md5 强一致比较。

移交下一节点：old 对照更新为 `ptmp/no00052_concat_slice_fold_20260921/flow-final`
（建议预注册比较值 **70.410333 s**）；筛选 reemit 在最终 checkpoint 上仍能发现
61k 重复表达式/3.5k 赋值链（bitwise-muxes、mux-chain-fold、used-bits 之后），
"语义管线末端再跑一次 canonicalize"是已定位的候选；同源非连续 bit gather
（2,028 个）与全覆盖置换（14 个）池已定量，不足以支撑专用 op。
