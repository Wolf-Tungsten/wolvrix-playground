# A0076 - r003/t1/s06 mask 缓存与单级 direct

对应 `next` = `step`，轨迹 `t1`，step 6，K=2。Phi 选择节点为 e00071、e00056。
两个候选都在 e00071 的 active-tile sparse 父表型上做局部精修：c1 消除 active tile
覆盖阶段对 selector/tval 指针数组的二次读取，c2 消除 151 条单级链的双指针数组与
通用 level loop。评估严格串行，均显式使用冻结的基础 10 开关加
`--wide-mux-chain-active-tile-sparse`；两份 `result.json.emit_args` 已逐项审计一致。

## 候选与结果

| 候选 | eval / commit | 来源 -> 病灶 -> 改动 -> 可证伪预期 | 量化结果 | 裁决 |
|---|---|---|---|---|
| c1 `compact mask/value cache` | e00075 / `b0624c9` | e00071 -> union 首遍已加载非零 selector mask/tval，overlay 又经 pointer array 重读 -> 按 level 顺序紧凑缓存 mask/value 后直接 scatter，保持后级覆盖语义与 >64 fallback -> 预期较 e00071 至少 -1.5%，低于 0.5% 或回退证伪 | **363.823s**（363.823/363.823/363.822s，CV 0，非 noisy），`compile_s=1982.6s`，loadavg 5.88；17/17 ctest、3 rep difftest 73580/49996 全过；较 e00071 **+7.03%** | 证伪；固定 64 项 mask/value 数组形成 1 KiB 每调用栈框与缓存写流，未胜过避免的二次读取 |
| c2 `single-level direct helper` | e00076 / `be544f9` | e00056/e00071 -> 151/156 条融合链为单级，仍构造两组单元素指针数组并进入通用 level loop；e00060 的 tile/scatter 无正证据 -> 保留逐 word branchless blend，仅直接传 sel/tval -> 预期较 e00071 至少 -1.5%，低于 0.5% 或回退证伪 | **354.543s**（354.557/354.543/354.542s，CV 0，非 noisy），`compile_s=1995.9s`，loadavg 2.53；17/17 ctest、3 rep difftest 73580/49996 全过；较 e00071 **+4.31%** | 机械 winner，已入 `t1/main`；相对父节点仍证伪 |

## 裁决与机制分析

- `finish-step` 按 raw score 选择 e00076；它比 e00075 快 **9.280s / 2.55%**。但
  e00075/e00076 起跑 loadavg 分别为 5.88/2.53，不能把相邻差值完整归因于 direct
  helper。更关键的是 e00076 与 loadavg 1.92 的父节点 e00071 较接近，却仍慢
  **14.633s / 4.31%**，故没有达到预注册收益门。
- c1 把“只缓存非零 level”实现成每次调用都预留两个 64 项数组。虽然只写 active
  项，1 KiB 栈框、额外 mask/value store 和新的控制形态仍是固定成本；在 selector
  机会密度仅 0.0188% 的负载上，二次读取本身不是可单独回收的一阶成本。
- c2 精确命中静态 151 条单级链，但静态链数不代表动态 Host 权重。保留原数据流并
  消除单元素 ABI 仍无收益，结合 e00060 的 tile/scatter 负结果，单级 wide-mux helper
  微结构路线关闭；若未来重开，必须先给出单级链动态 block execs/Host 权重。
- 两候选都只修改显式 grhsim AM emit 规则、文档与测试，不改 GRH IR；两者通过完整
  功能门且 `compile_s < 2000s`，失败属于性能假设证伪，不是功能或预算失败。

## winner 与后续建议

`tes/r003/t1/main` 已机械快移到 `be544f9`。t1 完成 6/8，但历史 t1 best 仍为
e00056 **241.956s**；全局 best 仍为 e00057 **229.429s**。当前 evals 26/32。

对 Phi 的建议：保留 e00071 的 nonzero-level bitmap 原形，不再用固定栈缓存精修其
二次读取，也不再凭静态 151 条覆盖精修单级 helper。wide-mux 邻域若继续，先做动态
active-tile 非零层分布及单/多级调用权重计数，再寻找能减少必需 base 写流或调用次数的
机制。状态机下一 action 是第 6 轮 `round-summary`；本 action 不启动它。
