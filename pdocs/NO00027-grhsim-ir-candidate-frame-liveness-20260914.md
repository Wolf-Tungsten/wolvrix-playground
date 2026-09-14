# NO00027：按局部值的定义顺序取消 frame 清零

- Node：`frame_liveness_20260914_01`。
- 当前阶段：`ACCEPTED`（caller-owned replicate 候选通过完整门槛和六次交替）。
- 根基线：NO00026，根仓库 `c9955d0`，GrhSIM 子模块 `cafaf61`；开始时工作区干净。

## IDEA：理论假设与证据

100k cycles、单线程、CPU 2、无 waveform/commit/RAM trace 的 phase profile 记录为：

| 指标 | 值 |
|---|---:|
| evals / rounds | 200102 / 402258 |
| eval 总计 | 129.674 s |
| compute | 98.523 s（75.96%） |
| commit | 29.270 s（22.57%） |
| publish | 1.736 s（1.34%） |

当前 emitter 在每个 activity unit 的调用体中生成
`alignas(8) std::byte cpu_local[N]{}`。这会在每次 unit 被激活时把整个局部 frame
清零；frame 中的 slot 对应该 unit 内部 operation 的结果。静态扫描 NO00026
生成模型得到 35,585 个 frame、总声明容量 5,409,107 bytes（最大 5,816 bytes），
并有 5,978,128 个局部值引用。这个成本属于 compute phase，和具体模块名称无关。

候选机制利用现有 IR/分区的拓扑不变量：同一 unit 内的 operation 按 producer→consumer
顺序发射；每个 local value 只有一个 producer，producer 在任何 consumer 读取前写入
完整的 scalar 或 wide slot；boundary、state、input 和 string slot 不在该 local
frame 中，字符串指针仍由现有声明单独初始化。因此 local frame 无需初始字节值。
去掉 `{}` 只改变未被读取的死 slot 的初始内容，不改变任一可观察值、状态提交、
event history 或通知。候选不改 IR、GRH pass、调度或 helper ABI。

局部目标是减少 compute phase 的 stack-store/memset 开销；理论上上界受 frame 清零
在 compute 中的实际占比限制，不能把 5.41 MB 静态容量直接当作动态收益。筛选若
出现 NEMU mismatch、未定义值、崩溃、超时或 Host 回退则否定该机制；只有完整
SV→C++、fresh 编译、100k 等价和六次交替统计通过才可接受。

## BASELINE 与复现配置

用于提出假设的 profile 来自保留的 NO00026 emu，Make 运行配置为
`XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_SIM_MAX_CYCLE=100000`
以及 waveform/commit/RAM trace 全关闭、`EMU_RUNTIME_PROFILE=1`。日志和新增证据
均放在 `ptmp/no00027_profile_20260914_01/`；正式节点仍须为 100k 重新预注册
生成、编译和 `old1/new1/old2/new2/old3/new3`，生成/编译各以 1800 s、仿真以
预选 old 的 1.5 倍为截止线。

后续阶段将记录：聚焦 emitter/IR 测试、完整路径生成与独立 fresh 编译墙钟、模型
checkpoint/输入身份、六次交替 Host/emu 时间、NEMU 终点和秩次统计。任何筛选
和插桩时间都不进入正式性能样本。

## REJECTED：取消局部 frame 清零

该候选只移除 activity unit 中 `std::byte cpu_local[N]{}` 的初始化，保留所有
 IR、布局、调度和 helper ABI。聚焦 `make test_grhsim_cpu_emit`、
 `make test_grhsim_cpu_schedule test_grhsim_cpu_mapping` 均通过；完整 SV→C++
 生成用时 **660.022 s**，独立 fresh C++ 编译用时 **237.85 s**，均低于 1800 s
 门槛，完整路线和 checkpoint round-trip 成功。

正式 100k 交替运行固定为
 `XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_SIM_MAX_CYCLE=100000`，
 waveform、commit trace 和 RAM trace 全部关闭。六次均 exit 0、NEMU PASS，终点
 均为 `instrCnt=240349`、`cycleCnt=99996`、guest cycles `100001`、PC
 `0x80000c0c`。

| 顺序 | old Host ms | new Host ms |
|---|---:|---:|
| 1 | 130804 | 129339 |
| 2 | 130282 | 130390 |
| 3 | 130472 | 127527 |

old 均值为 **130.519 s**，new 均值为 **129.085 s**，均值降低 **1.10%**；但
 `max(new)=130.390 s` 大于 `min(old)=130.282 s`，不满足预注册的全秩分离条件。
因此该候选在本节点内否定，不能作为接受实现；完整样本日志保存在
 `ptmp/no00027_profile_20260914_01/runs/{old1,new1,old2,new2,old3,new3}/`。

## IDEA/IMPLEMENTED：宽值 replicate 写入现有结果槽

当前 100k profile 的平坦热点中，`grhsim_replicate_words` 的 `<2,1>` 和 `<5,1>`
实例合计约 **1.04%** 样本。旧 emitter 将宽 replicate 作为返回值
 `std::array`，即使结果已有 caller-owned local/boundary slot，也先构造临时数组
 再赋值。候选在 CPU emitter 生成 `cpu_replicate_words_changed`，直接把结果写入
 已存在的结果数组，逐写入位合并变化标记并清理结果宽度之外的尾位；标量源和宽源
 都走该 helper。这样避免宽返回值和一次完整结果复制，不改变 IR、分区、调度或
 结果存储布局。helper 使用 caller-provided `std::array`，遵守宽值 runtime helper
 的既有性能约束。

筛选生成从 NO00025 冻结 flat GRH 恢复，修正版 emitter 生成 **421** 个
 `cpu_replicate_words_changed` 调用，旧 `grhsim_replicate_words` 调用为 **0**。
宽值 emitter/Verilator 差分、ASan/UBSan 重复稳定调用测试和命名冲突检查均通过；
 `make test_grhsim_cpu_emit` 用时 **67.69 s**，schedule、mapping 和 IR 回归也
 通过。50k 筛选运行均 NEMU PASS、精确终点 `73580/49996/50001/0x80001312`；
 修正版同窗口单对 Host 为 old **56.986 s**、new **56.145 s**，候选较快
 **1.48%**。该单对只用于筛选，不进入正式统计。

修正版筛选二进制的 100k 预检同样通过精确终点 `240349/99996/100001/0x80000c0c`。
交替首对为 old **133.367 s**、new **129.346 s**，候选快 **3.02%**；该结果
仍属于正式 flow 之前的筛选证据，不能替代后续完整生成、fresh 编译和六次正式样本。

筛选早期曾有一个把结果槽先清零再累计变化的实现；它会将稳定的非零结果误报为
 changed。发现后立即中止尚未完成的完整生成，隔离该 flow 和日志，不把其性能或
 代码作为证据。当前工作树已改为保持旧结果、仅对最终覆盖位比较，并新增第二次
 同输入必须返回 unchanged 的测试。修正版筛选 flow 为
 `ptmp/no00027_profile_20260914_01/flow-replicate-screen2/`；该修正版通过 100k
 预检后已完成完整 SV→C++ 和 fresh 编译。

## VALIDATED：完整路线与正式六次交替

修正版完整 SV→C++ 生成 `no00027_replicate_full2_generate` 墙钟 **655.53 s**，
fresh 32-job C++ 编译 `no00027_replicate_full2_build` 墙钟 **235.71 s**；两步
均 exit 0，均低于 1800 s。正式 flow 的 flat GRH 与 NO00025 冻结 flat GRH
逐字节相同，SHA-256 均为
 `518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`。候选 emu
 SHA-256 为 `03f21daf2f9577bcada2d4ab8df51117277617eebeb4cb792e8a0e1886b994e2`。
编译生成的模型仍为 5,595 个 task；宽 replicate 使用新 helper 的调用站点为
 **421**，旧 `grhsim_replicate_words` 调用为 **0**。

正式运行预注册为 `old1/new1/old2/new2/old3/new3`，固定 100k cycles、CPU 2、
单线程、waveform/commit/RAM trace 关闭；仿真截止线为 **196 s**。六次均 Make
 和 emu exit 0，均启用 DIFFTEST/NEMU，且精确到达 `instrCnt=240349`、
 `cycleCnt=99996`、guest cycles `100001`、PC `0x80000c0c`；没有 mismatch、
 assertion、BAD TRAP 或补跑。

| 顺序 | Host s | emu 墙钟 s | 状态 |
|---|---:|---:|---|
| old1 | 133.200 | 133.23 | VALID / NEMU PASS |
| new1 | 131.714 | 131.74 | VALID / NEMU PASS |
| old2 | 134.173 | 134.20 | VALID / NEMU PASS |
| new2 | 129.463 | 129.49 | VALID / NEMU PASS |
| old3 | 134.601 | 134.63 | VALID / NEMU PASS |
| new3 | 129.280 | 129.31 | VALID / NEMU PASS |

| Host 统计量 | old | new |
|---|---:|---:|
| 均值 s | 133.991333 | 130.152333 |
| 样本标准差 s（n−1） | 0.717950 | 1.355535 |
| 最小–最大 s | 133.200–134.601 | 129.280–131.714 |

均值减少 **3.839000 s**，按 `(old_mean-new_mean)/old_mean` 为 **2.865111%**；
合并样本标准差为 1.084649 s，old−new Cohen's d 为 **3.539394**。三次新运行
均快于三次旧运行，`max(new)=131.714 < min(old)=133.200`，间隔 **1.486 s**；
Mann–Whitney `U_new=0`，六个样本标签分配的单侧精确 p 为 **0.05**，满足
预注册的真实性能判据。三对分别节省 1.486、4.710 和 5.321 s；全部样本保留，
没有按最快值筛选。

## ACCEPTED：节点结论

本节点最终保留 CPU emitter 的 caller-owned 宽值 replicate helper，并撤回 frame
清零候选及其未通过的性能结果。聚焦回归、宽值差分、稳定 unchanged 检查、完整
SV→C++、fresh 编译、100k 等价和六次交替统计均已完成；候选相对 NO00026 对照
在同窗口 Host 均值降低 **2.865111%**。因此 NO00027 判定 **ACCEPTED**。
正式日志与生成物均留在 `ptmp/no00027_profile_20260914_01/`，不提交生成物；
节点代码、测试、报告和索引将在节点收尾集中提交。
