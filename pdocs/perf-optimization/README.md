# GrhSIM IR 性能优化记录

新模型（v2 六阶段架构，见 `pdocs/simulation-model-refactor/grhsim-ir-architecture.md`）
性能优化的**唯一记录处**。每项优化一条记录，从 `TEMPLATE.md` 复制填写。

## 记录规则

- 命名：`YYYYMMDD-hhmmss-<短题>.md`（日期时间 = 记录创建时刻，便于跟踪）。
- 先登记基线再动手；结果必须**同口径复测**——标准口径是
  `make benchmark_grhsim_ir`（M0 存档对照、3+3 交替、页缓存逐出、taskset 定核，
  数据落 `ptmp/`）；偏离标准口径必须在记录中说明理由。
- 数字给全：均值、标准差、逐次原始值、日志路径。只有结论没有数据的记录不合格。
- 已完成的记录不删改结论；被后续数据推翻的结论划线标注并链接新记录。
- 编译时间（全量 TU 构建）与运行时间同等记录——以运行时间换编译时间或反之的
  权衡要写明。

## 正确性门槛（任何性能优化提交前必须全绿）

1. `make test_wolvrix`：无新增失败（基线三项 transform-comb-lane-pack、
   transform-repcut、ingest-write-back-slice SEGFAULT）；
2. `make run_all_hdlbits_grhsim_ir_tests`：162/162；
3. `make run_xs_bugcase_grhsim`：25/25；
4. `make check_sim_refactor_baseline`：161/161 逐 eval 与黄金一致；
5. XS 完整 CoreMark + NEMU difftest：`HIT GOOD TRAP`、exit 0，且逐拍轨迹
   instrCnt=663,688 / cycleCnt=297,291 一致（除非本项优化有意改变调度语义，
   此时必须重钉轨迹并说明）。

## 当前基线

`20261004-075148-v3-sixphase-baseline.md`：M0 存档 85.9s vs 当前（V3-M3）223.4s
（100k CoreMark 周期）= 2.60× 回退。**所有后续优化以缩小此差距为目标。**

## 优化候选 backlog（按预期收益排序，2026-10-04 评审）

1. ~~**sink 簇内按使能锥细分**~~：**已实测不采纳（2026-10-04）**。{posedge clock}
   单签名簇 88.5k op 每周期整体点火、逐 op 查 en；A1 细分（同签名按共享 en
   值拆出守卫子簇，调用点 `&& read(enableGuard)`）已实现并全绿，但标准口径
   A/B 实测 **+0.50%（224.54s vs 223.44s）回退**——逐 op en 检查是预测准确的
   热分支近乎免费，而 1,645 个守卫读是大结构散布的随机读 + 扫描路径变长的
   固定成本。机制保留、默认关闭（`XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN`，默认 0）。
   完整数据与成本教训见 `20261004-113053-sink-enable-guard.md`；若重启需粗粒度化
   （数百大组 + 守卫位打包），预期收益 ~1% 量级，优先级低。
2. **小超节点发射器内联 / ThinLTO**：XS 有数万个不超 128 op 的超节点函数，
   调用开销与跨 TU 可优化性受限。曾评审为"比较玄"，需要先做占比测量再立项。
3. **逃逸/时钟簇 en 条件静态化**：把能在编译期求证的 en 条件折叠掉，减少
   每轮逐 op 判断。

已完成（数据见基线记录）：V3-M1 激活旗标位图化（-17.3%）、V3-M2 sink 超节点
TU 拆分（-2.6%，主要为编译时间）、V3-M3 克隆共享计算移入 C 段。
2026-10-04 新增：P_mem 写口 enable 影子位图（memEnableBits，-8.9%，见
`20261004-212805-pmem-enable-bitmap.md`）——同档案还有六阶段 perf 占比解剖
（P_general 83.8% / P_mem 12.4% / P_publish 2.6% / 其余 <1%），是后续
选项的定量依据。
2026-10-05 新增：P_mem act 聚类 + 死 compare-store 删除（-12.1%，见
`20261005-002919-pmem-act-cluster-dead-compare.md`）——边界发布在"无 fanout 无
hook"时退化为无条件 store（23.3% 站点），P_mem 端口按 act 分段共享守卫。
当前对 M0 差距 2.08×。
2026-10-05 新增：变化检测比较次数普查（测量记录，见
`20261005-111210-compare-count-census.md`）——XS CoreMark 100k 精确计数：
grhsim IR 总 325 亿次（非 sink publish 228 亿 + sink 97 亿，附每周期
~3.01 轮 eval 实测），gsim 总 68 亿次；组合侧差距 14.8×，边界发布模型是
最大结构性成本项。
2026-10-05 新增：非 sink 划分方法改进规划（规划记录，见
`20261005-170704-nonsink-semantic-partition-plan.md`）——declaredSymbol
锚定的语义节点（S1）+ 合并放松尺寸限制（S2）+ merge/分段调优（S3）
三主线；前置 S0 溯源覆盖普查，实施顺序打包验证 → S1 → S2 → S3a，
SV→CPP 与 CPP→二进制各 ≤30 min 硬闸。
2026-10-06 新增：S1/S2 探索记录（测量记录，见
`20261006-061729-nonsink-partition-s1s2-exploration.md`）——语义节点+合并
放松的结构收益成立（s1c 边界 -16%、publish 站点 -21.8%），但全形态违反
30 min 编译闸；trace 定位瓶颈为编译器后端 SLPVectorizer（62%）+inliner，
附 gsim vs grhsim-ir 编译基线（5m41s vs 8m58s，-j32）与 PCH 证伪实验
（CPU -5.7%、wall 零变化）。gsim 形态对照：无分支 flag 变化检测 + 零
helper 原生运算符（我们逐值条件存 1816 if/TU + 4198 helper 调用），
且 supernode-max-size 15→1024 编译仅 +28%——**尺寸免疫实锤，爆炸是发射
形状问题**；`-fno-slp-vectorize` 虽运行时中性但作者否决（绕症状非修复）。
2026-10-06 新增：宽值 _BitInt 化（实施记录，见
`20261006-101609-bitint-wide-value.md`）——TwoState >64 位 Logic 从
`std::array<uint64_t,N>` + 手工词 helper 切到 C23 `unsigned _BitInt` + 原生
表达式（对齐 gsim 形状），消除宽值词循环链的 SLP/inliner 编译热点；E-flat
（窄值无分支 publish + helper 文本内联）为其前置，随本项一并提交验证。

## 历史说明

2026-09 旧模型优化记录 NO00001–NO00028 已删除：它们针对 v2 之前的旧架构
（双重门 eventGated 调度），结论不适用于当前模型，保留只会误导方向。
原文在 git 历史可查。
