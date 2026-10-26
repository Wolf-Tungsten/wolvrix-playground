# 新版编译速度优化

用户决定停止追旧侧性能基线。当前目标固定为 preserve-aggregate=all 的 XiangShan 原始 SV 到可执行 emu 小于 35 分钟（2100 秒）。旧侧失败记录保留，但不再阻塞新版优化。

## 已定位并修改

- grhsim replaceOperands 原先对每个 op 清空再重建全部 operands，连未变化的时钟/使能也反复删除高扇出 use-list；改为快照输入并只替换不同项，兼容输入 span 引用自身 operands。
- replaceAllUses 原先每次按精确 size reserve 目标 use-list；大量别名归并到同一信号时反复复制整个列表。改为几何增长。
- 可变 GraphBuilder 的 use-list 增加 operand backlink，删除通过末项换位完成，避免线性搜索及整体搬运。freeze 仍按 op/operand 顺序重建规范列表；可变 users 的枚举顺序不属于调度契约。
- simplify 的 CSE 改为局部精确二进制 equality key，保留完整类型、shape、属性类别/长度和 edge 历史归一化；不改变 sink 的持久文本时钟签名。
- 补充各轮 fold/share、mux、state merge、DCE、used-bits、topology 计时；提供 Make 的检查点 benchmark/perf 入口。
- 采样发现 DCE 对高扇出值重复复制并检查 users；新增借用当前 use-list 的 Graph API，先检查是否有 use，全图 scope 无需逐个确认跨 owner，分区后仍检查完整叶 owner。该修改已通过下述公共、重启与生成执行验证。

## 当前证据

所有数字均为新版自身定位，未作旧侧性能对照。检查点耗时不是完整 SV→emu 验收。存在并发后台任务，分阶段降幅也不是受控最终加速比。

| 阶段 | 修改前原始 SV 流程 | 首批 use-list 修订检查点 |
| --- | ---: | ---: |
| 首次 grhsim-simplify | 971.714s（8轮上限） | 598.293s（8轮上限） |
| pack-bit-registers | 57.552s | 23.973s |
| 打包后 simplify | 190.879s | 117.325s |
| recover-masked-or | 136.814s | 102.664s |
| masked-or 后 simplify | 180.993s | 109.421s |
| split-event-and-output | 580.152s | 81.891s |

前者日志：`ptmp/remove-grhsim-ir/xs-assigned-frame-fresh-measured-v1/generation.log`。后者：`r6-compile-speed-xs-use-lists-v2-driver.log` 及同名目录下 `timings.json`。

首次 XS simplify 单轮采样（`r6-compile-speed-xs-profile-v1/perf.txt`）的主要自身热点为 memmove 18.20%、expressionKey 15.38%、replaceAllUsesInternal 11.25%、removeValueUser 8.67%，是上述优化的定位依据。后续 indexed/CSE 候选首轮 192.103s，其中 DCE 77.254s、fold/share 67.746s、used-bits 34.620s；借用 use-list 修订针对这个 DCE 热点。

indexed use-list 公共回归 74/74，103.62s，见 `r6-compile-speed-indexed-users-public.log`。精确 CSE key、owner 和 use-list 别名/增删/重复参数/高扇出/freeze 反例专项已通过，见 `r6-compile-speed-cse-keys-build.log` 和 `r6-compile-speed-owner-view-build.log`。

最新借用 API 候选 v4 的公共回归 74/74（112.93s）、全部 10 个 checkpoint 重启执行、168 记录逐次观测比较通过（18 项显式批准、0 未解决）；resource tools 3/3，见 `r6-compile-speed-v4-regressions.log`。完整 aggregate-all 原始 SV→emu 通过 `measure_remove_grhsim_ir_resources` 的新目标 `build_remove_grhsim_ir_xs_from_sv` 一次连续测量，固定 24 个 C++ 编译 job，目录 `xs-compile-speed-v4-fresh`；该任务仍在途，35 分钟目标尚未宣称达成。

v4 的 `make test_grhsim_cpu_st_cpp` 已完整退出 0，42 个生成模型及七万字段构造用例执行通过，见 `r6-compile-speed-v4-emitter-matrix.log`。覆盖 16/1024 行预算、数组/宽值、DPI 单调用、输出/Event 调度、chunkFrame、FST 与执行计数；没有通过减小 simplify 轮数或关闭现有优化来缩短编译。

## 后续修订与配套版本测量

- v5–v9：used-bits 合并 type/demand 表，首次记忆才复制类型；拓扑遍历使用仅本次有效的 dense index 和借用 use-list；命名 identity assign 的消费者同轮透传；generate group 增加 symbol→group 反向索引，删除 op/value 不再扫全部组。增加 96 层 alias 链及 generate group 重复 membership/load/freeze/clone/重加覆盖。v8 公共 74/74（104.08s），v9 生成执行矩阵通过。
- v10–v11：origin 无新增时不复制目标来源集合；仿真 verifier 的 attr 存在性检查不再深拷贝完整 Operation。
- v12–v13：通用结构 verifier 借用只读 OperationView，错误路径才构造诊断快照；所有入口仍执行 GrhVerifyPass，去除 selectGraph 与它重复的全图检查；虚拟分区 verifier 借用 owner 路径，环检查改为连续邻接表，重复边入度/出度成对计数，保留原图、叶 quotient、超节点 quotient 三重无环检查。公共 74/74（101.37s），见 `r6-compile-speed-v13-public-tests.log`。
- v14：无分区 used-bits 使用本轮局部 value/demand、queued 索引表；叶分区保留稀疏表，避免小叶分配整图大小。专项 3/3，配套候选目录 `compile-v14-python`。

v9 完整链路 277.612s 在 hier-flatten 崩溃，没有 emu。检查实际 loaded_libraries 后发现旧 editable Python binding 可通过 site hook 覆盖 PYTHONPATH，而核心库已改变 Graph 类布局。初次 v11 启动也检测到同样混装，已停止；这些运行不作为配套版本验收。检查点 v5/v7 的数字仅保留诊断，不作为可信加速比。

候选现在成套构建 `_wolvrix.so` 和 `libwolvrix-lib.so`，通过 `python -S` 禁用 site hook，并在资源脚本递归调用 Make 时保留 `-S`。资源工具 4/4。实际生成身份同时记录这两个候选路径；配套 v11 已通过 hier-flatten（79.036s），但这只能说明该次未再复现崩溃，不能单独证明根因。v4 已在 2100 秒前未完成生成，停止；v11 配套运行被 v14 替代，均无完整预算通过结果。

v14 配套 XS flat 检查点诊断：load 44.114s、grh-to-grhsim 12.220s、首次 grhsim-simplify 194.897s，后期 used-bits 约 7–8s/轮；仍触及 8 轮上限（updates=10100），不记作收敛。见 `r6-compile-speed-xs-paired-v14/timings.json`。该测量有并行负载，不是完整 SV→emu，也不据此宣称最终加速比。

v14 配套完整 aggregate-all 原始 SV→emu 已完成：2717.300s（45 分 17 秒），峰值同时 RSS 84,104,420 KiB，exit=0，`within_compile_budget=false`。生成阶段 2126.447s（35 分 26 秒），之后 C++ 编译与链接约 591s；emu 为 222,036,000 bytes。实际结果见 `r6-xs-compile-speed-v14-paired-full-resources/result.json`，不能算作 35 分钟验收通过。

## v15–v20：分区、调度、序列化及 C++ 布局

- v15：全结果可观察的叶跳过无效 used-bits 分析，单 op 叶避免无意义 CSE key；活动度 quotient 的边去重改连续数组排序，保持拓扑和平局策略。公共 74/74，冻结观测 168 条、18 条批准差异、0 未解决；见 `r6-compile-speed-v15-regressions.log`。该日志中的执行矩阵构建已包含部分 v16 emitter 修改，不标作纯 v15 矩阵。
- v16：schedule 依赖查询借用 owner，缓存 fire 的时钟签名；emitter 避免重复验证及反复全图扫，ready/nextSweep 保留原词典序多轮次序，owner 仅本次 analyze 内 intern。专项 3/3、42 模型与七万字段实际执行通过，见 `r6-compile-speed-v16-paired-matrix.log`。
- v17：活动度 segmentation 使用本次调用内稠密 stamp 工作表，缓存边界 rate；借用 owner/use-list/attrs，避免 manifest 深拷贝 Operation。专项 3/3，见 `r6-compile-speed-v17-partition-tests.log`。
- v18：prettyCompact JSON store 直接借用 graph 的只读访问器及 symbol view，避免 Value/Operation 快照；users 仍稳定排序，保留 roundtrip 字节一致检查。公共 74/74（99.05s），见 `r6-compile-speed-v18-public-stage.log`。
- v19：nonsinkDag 以排序 owner、稠密 node、去重边和 CSR 取代每叶 map/set；保留词典序拓扑、effect 顺序及公开 SinkSchedule 的完整叶文本 key。专项 3/3，见 `r6-compile-speed-v19-schedule-stage.log`。
- v20：chunkFrame 中超过 1024 个跨块局部值时，按完整 C++ 类型生成索引数组，显式初始化和 chunk 控制成员保持独立；named store 始终保留语义字段作为直接成员，不能被 `cells_*` 包装。所有访问经各自布局映射，boundary 初始化按 physical field 执行，避免上百万 frame 成员声明与初始化语句。它仅改变发射布局，不增加 IR 或虚拟分区。七万字段命名/索引两种构造、1100 scalar + 1100 memory 的实际状态读写与重复 init、完整生成执行矩阵通过，见 `r6-compile-speed-v20-layout-matrix.log`。

v20 完整测量 `xs-compile-speed-v20-paired-fresh` 已完成：2134.611s（35 分 35 秒），exit=0、`within_compile_budget=false`，峰值同时 RSS 84,357,944 KiB，二进制 218,149,720 bytes。生成含 roundtrip 1935.779s，余下 C++ 编译与链接约 199s，生产 `-O3 -march=native`、24 job。头文件由 1,989,930 行减为 575,929 行（约 56MiB→16MiB），PCH 约 286MiB→112MiB。资源结果见 `r6-xs-compile-speed-v20-paired-full-resources/result.json`；前段与 v14 的 C++ 编译短时重叠，不作受控加速比。v20 公共 74/74（102.83s）、10 个重启模型、168 条冻结观测（18 条批准差异、0 未解决）、资源工具 4/4 全部通过，见 `r6-compile-speed-v20-regressions.log`。它仍超出 2100 秒约 35 秒，35 分钟目标未通过。

## v21–v23：状态访问与叶内 simplify

- v21：`stateLogicalType`/`stateInitSpec` 使用只读 StateView 和属性引用，去除反复深拷贝声明及整套 initializer 数组；返回的类型与 InitSpec 仍拥有自身数据，全部原诊断/验证保留。基础 2/2、调度/分区/变换 3/3，见 `r6-compile-speed-v21-state-stage.log`。
- v22：状态表改为按原声明 index 排序的连续记录，本次调用内建立 declaration/port→state 的索引；不保存跨改图或 freeze 的 ID。死状态引用检查从每状态扫全图改一次集合检查；used-bits 没有窄化时省去无效 operand 重建及刚执行过的 DCE。新增两个无观测反馈状态删除反例，专项 3/3，见 `r6-compile-speed-v22-state-indices-final.log`。
- v23：叶 owner 分组由 map<Owner, vector> 改排序连续成员及 span，保留完整 owner 的词典序与叶内原拓扑顺序；借用稳定分组键和未变成员，避免每阶段重复分配。used-bits 工作表只存原 width/prefix，而非每值复制完整 LogicalType/shape；真正窄化时才取完整类型。公共 74/74（101.02s），见 `r6-compile-speed-v23-public-stage.log`。
- v24：分组只保存代表 op，改写该叶前重新读取并拥有完整 owner，避免同时保存数百万份路径；已排序成员不重复排序。标量 prefix 检查只用图的只读访问器。专项 3/3、完整生成执行矩阵、10 个重启模型、168 条冻结观测（18 条批准差异、0 未解决）及资源工具 4/4 通过，见 `r6-compile-speed-v24-groups-stage.log` 与 `r6-compile-speed-v24-matrix-regressions.log`；公共 74/74（103.41s），见 `r6-compile-speed-v24-public-tooling.log`。tooling 初次因 `python -S` 隐去第三方 numpy 路径失败，显式添加 site-packages 且保持候选路径优先、仍禁用 site hook 后 14/14 通过，见 `r6-compile-speed-v24-tooling-retry.log`。未修改普通 GRH simplify，也未减少优化轮数。

v24 使用本次 aggregate-all 原始 SV 生成的 `xs-compile-speed-v20-paired-fresh/flat.json` 做定位：load 45.356s、转换 10.892s、首次 grhsim-simplify 164.041s；后期 used-bits 4.4–4.5s/轮，state-merge 约 0.75s/轮。仍实际执行 8 轮并触及上限，不记作收敛。见 `r6-compile-speed-xs-paired-v24/timings.json`。它是检查点诊断，有并行负载，不能替代完整 SV→emu 或宣称受控加速比。

最新源码配套候选 `compile-v24-python` 的完整测量已完成：`xs-compile-speed-v24-paired-fresh` / `r6-xs-compile-speed-v24-paired-full-resources`。binding/core 的 loaded_libraries 均确认来自该候选目录。以下只按实际连续 wall time 判定，不拼接检查点数字；前段与前一候选短时重叠，不声称受控加速比。

## v24 完整编译验收

**本次 aggregate-all 原始 SV → 链接好的 emu 为 2018.820s（33 分 38.820 秒），exit=0、within_compile_budget=true，低于 2100 秒预算 81.180 秒。** 这是一次实际连续测量，不是检查点恢复或分段耗时相加。

- 输入为冻结 R0 的 2149 个原始 SV；`inputs.json` 绑定 filelist/read_args/manifest 摘要，generation identity 记录 original-sv、resume_from_flat_grh=false。Make 的成功 RTL 生成记录检查确认 preserve-aggregate=all。
- 保持全部生产优化、pack-bit-registers、maskedOr、边界 clone 和叶内 simplify；首 simplify 仍执行 8 轮，不以减少轮数达标。C++ 实际使用 -O3 -march=native、24 job。
- 生成含 GRH JSON roundtrip、SinkSchedule 重建及字节一致校验，共 1828.547s；编译链接与驱动余下约 190.273s。峰值同时 RSS 为 84,126,652 KiB，按资源脚本的进程树采样定义记录。
- 2276 个 TU、356,896 个函数，manifest 最大函数实际行数 1024，等于生产预算；chunk 仍只属于 emitter。二进制 218,149,720 bytes，SHA256 为 7387973185910515ca8b774cbea4a6ac95ec000a775a59a10e1ee6f75f265b0e。

| 完整链路阶段 | v20 单次记录 | v24 单次记录 |
| --- | ---: | ---: |
| 首次 grhsim-simplify | 298.383s | 232.409s |
| partition-nonsink | 92.097s | 78.856s |
| 叶内 simplify | 185.077s | 158.239s |
| partition-sink | 93.005s | 84.597s |
| C++ emit | 194.588s | 157.682s |
| 原始 SV → emu 连续 wall | 2134.611s（未达标） | 2018.820s（达标） |

两次主机并发条件不同，表格用于列出原始观测，不能视为受控优化比值。旧侧性能基线已按用户决定取消。

证据：[完整资源结果](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-paired-full-resources/result.json)、[实际构建日志](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-paired-full-resources/make.log)、[生成阶段](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/generation.log)、[输入身份](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/inputs.json)、[生成身份](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/graph.generation-identity.json)。

链接后的同一 v24 二进制另经 Make 运行 CoreMark/NEMU difftest：5000 周期冒烟退出 0，但仅提交 3 条指令，因此补跑 20000 周期；补充运行退出 0，提交 14,121 条指令，到达 pc=0x80000440，按预设周期上限结束，未报告 mismatch。Host 157.974s 只是该次验证的观测，不作旧侧性能对照。见[运行日志](../../ptmp/remove-grhsim-ir/logs/xs_wolf_grhsim_compile_speed_v24_smoke20000.log)及[Make 驱动日志](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-smoke20000-driver.log)。

## v24 最新 100k CoreMark 整机实测

用户询问当前 100k 时间后，直接使用同一已链接 v24 二进制，未重新生成或编译，通过 `make run_xs_grhsim_emu` 运行。输入仍是 aggregate-all 模型、coremark-2-iteration.bin 与 NEMU reference；seed=0、固定 CPU 2、无波形/commit trace，10000 周期间隔打印进度，不执行旧侧性能对照。

- **100,000 host cycles 的 Host 时间为 1006.031s（16 分 46.031 秒）；完整 Make 命令 wall 为 16:46.07。**
- 退出码 0，Difftest enabled，提交 238,535 条指令，cycleCnt=99,996，Guest cycle spent=100,001，最终 pc=0x80000cde，未报告 mismatch。按 100k 周期上限结束，不代表完整 CoreMark 两次迭代已完成。
- time-v 的最大 RSS 为 194,040 KiB；这是该次运行最大进程 RSS，不是编译资源测量的同时进程树 RSS。
- 运行前二进制 SHA256 为上述 7387973185910515ca8b774cbea4a6ac95ec000a775a59a10e1ee6f75f265b0e；本次为新版自身单次实测，不能据历史不同主机负载下的时间声称受控加速比。

证据：[100k 运行日志](../../ptmp/remove-grhsim-ir/logs/xs_wolf_grhsim_compile_speed_v24_100k.log)、[Make 驱动日志](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-100k-driver.log)、[wall/RSS 与退出状态](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-100k.time)。完整编译预算和最新 XS 100k 已通过，R5/R6 其余动态诊断与收口仍单独跟进，不自动标记整体完成。
