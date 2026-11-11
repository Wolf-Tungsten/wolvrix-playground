# TNO0025 历史标准 RepCut pipeline 复核

## 问题

此前的约 10 秒 anchor 是历史恢复 preset；另有一批确实来自完整标准 pipeline 的结果，记录在旧工作区的 [TNO0368](</nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5/pdocs/grhsim_opt_thj/TNO0368_grhsim_fresh_rtl_full_flow_result_20261028.md>)。本记录把那一批标准 pipeline binary 放入当前 runner，与当前 merge-before 做同条件复测。

## 两条标准 pipeline 身份

| 项目 | 历史标准 pipeline | 当前 merge-before |
| --- | --- | --- |
| pipeline 结果 | seed7，retained initial | seed3，retained candidate |
| 完整图 km1 | 26,547,623 | 27,756,977 |
| migration | 自动拒绝，无迁移 | 自动接受 `piece_594744_p18_to_3`，移动 27 atoms |
| compiler | Clang 23.1.2 | Ubuntu Clang 19.1.1 |
| 记录时的 codepage | THP | auto |

公共 RepCut 参数逐项相同：`SimTop`、32 partitions、8 solver runs、`epsilon=0.05`、同一 KaHyPar revision、同一三个 memory target、`row_limit=2`、`strict_init=false` 和同一组 GRH options。

两侧 reduced HGR 的维度也相同：`296526` vertices、`301184` hyperedges。历史标准 pipeline 的初始 HGR 为 `584259` edges、`301184` atoms；当前 before 也是相同 header。历史标准 pipeline 的 piece 数为 1,320,667，当前 before 为 1,320,646，说明前端/变换存在小幅差异，但不是 12% 级别的规模变化。

生成物身份也已冻结：历史标准 pipeline 的 `partitioned.json` 为 4,107,932,365 B、SHA256 `e29b9f1d2c52f2cf56149182eca126f8d71852b85a772e5eb8a657b91465d596`，binary SHA256 `5ae949fed820d47f3287b27cff87338f1b9110f247d69a77259bcb25c0458d1d`；当前 before initial/candidate 的 `partitioned.json` 分别为 4,355,222,363 B / `045a1e97f552eac9c0a403c0f167a3758a6b424c9056e18871de6049d49f7c20` 和 4,355,233,374 B / `70df1e97d24a1755fd5106710085b2d52ce70fbbab84dc0d4255b11340095ba0`，candidate binary SHA256 为 `8f95d65a4012f52a041948cee8dd6e64c08beb0a212122a831ee26527ce2ec76`。

assignment 才是主要可见差异：历史 seed7 assignment 的最大分区为 part20、26,667 entries（2.745x active-part average）；当前 seed3/candidate 的最大分区为 part1、32,560 entries（3.351x active-part average）。当前 candidate 的 27-atom migration 没有改变主负载形状。

## 当前 runner 复测

历史标准 binary 与当前 before 均使用当前 `grhsim32_pair_compare.py`，只对历史 binary 的旧 runtime metadata 做兼容归一化。运行条件统一为：node030、CPU96–127、NUMA1 strict membind、ASLR disabled、当前 preload/code-page helper、CoreMark、100,000 cycles、完整 DiffTest、8 对 AB/BA。两侧功能和 placement gate 全部通过。

| 版本 | 当前 runner Host 均值 / 中位数 | 当前 runner 外部 walltime 均值 / 中位数 |
| --- | ---: | ---: |
| 历史标准 pipeline seed7 | 11.093 / 11.0525 s | 11.186 / 11.144 s |
| 当前 merge-before | 17.068 / 17.039 s | 17.165 / 17.135 s |

当前 before 相对历史标准 pipeline 的 Host delta 为 **+53.881%**，固定 seed 20261102 的 95% CI 为 **[+52.807%, +54.903%]**，8/8 更慢。外部 walltime delta 为 **+53.471%**，95% CI 为 **[+52.388%, +54.460%]**。因此用户记得的“还有一次标准 pipeline 明显更快”是正确的。

当前 runner 的阶段中位数如下：

| 指标 | 历史标准 pipeline | 当前 merge-before |
| --- | ---: | ---: |
| input load / ms | 459.557 | 422.446 |
| part eval / ms | 8,679.646 | 14,508.144 |
| global update / ms | 1,576.553 | 1,728.388 |
| 分区 eval 平均值之和 / us | 586.110 | 712.396 |
| 最慢分区 eval / us | 34.808 | 43.000 |

差距仍集中在 part eval 和最慢分区，而不是输入加载或运行时 placement。旧 TNO0368 窗口记录的 12.228 s 与本轮历史 binary 的 11.0525 s 不同，属于运行窗口、编译/runtime helper 与计时环境差异；但同一当前 runner 下 53.9% 的相对差距已经排除了“只是旧窗口较快”的解释。

## 结论

当前 merge-before 比历史标准 pipeline 慢，不能归因于一个漏传的 `epsilon` 或 memory 参数。已确认的主要变量是：

1. 历史标准 pipeline 选到了更好的 seed7 assignment，当前标准 pipeline 选到 seed3；
2. 历史 assignment 的最大分区更轻，当前 assignment 的 barrier 临界分区更重；
3. 历史 binary 使用 Clang 23，当前 binary 使用 Clang 19；
4. 两条 pipeline 的 HGR 维度相同但内容和 piece/活动计划有小幅差异。

因此当前 merge-before/after 的对测仍然是同一套新 pipeline 内的有效比较，但不能把当前 before 当作历史标准 pipeline 的性能基线。

原始数据：[当前 runner summary](../../build/xs/repcut-standard-anchor-audit-20261111/summary.json)、[逐对数据](../../build/xs/repcut-standard-anchor-audit-20261111/pairs.json)、[manifest](../../build/xs/repcut-standard-anchor-audit-20261111/manifest.json)、[兼容审计入口](../../build/xs/repcut-standard-anchor-audit-20261111/audit.py)。
