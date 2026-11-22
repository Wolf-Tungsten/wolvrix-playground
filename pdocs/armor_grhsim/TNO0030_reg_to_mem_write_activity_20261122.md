# TNO0030　香山 reg-to-mem 的解码门槛与写口活动

降低写解码发现门槛可以找到额外的寄存器数组。香山上门槛取 3、2、1 时分别新增 14、46、105 个真合并组。所有原有 4,782 个组仍得到相同的写口清单和匹配结果，包含 TNO0028 和 TNO0029 分析的热点组。按未转换写口的动态访问次数，`mux_chain` 和 `branch_not_in_update` 合计占 CoreMark 的 88.3% 和 MicroBench 的 89.9%。[门槛扫描与逐负载原始计数](./data/TNO0030_reg_to_mem_activity.json)

## 全设计扫描

从同一份 pre-reg-to-mem 检查点独立重放九次。输入有 311,139 个单写口寄存器，每个写口的更新条件最多分解出 55 个 OR 项。每次启用 intent、真合并、顺序写入和解码写发现，最小行数取 4。扫描参数同时控制进入解码搜索所需的 OR 项数和成功匹配的地址保护项数。较低门槛的行仍须通过连续性、重叠处理和读写合法性检查。[通用 pass 选项](../../wolvrix/docs/transform/reg-to-mem.md)

| 最少解码项 | 通过 OR 项数门槛的寄存器 | 匹配的行 | 连续候选组 | 去重叠后新增候选组 | 新增真合并组 | 新增合并行 | 全图真合并组 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 64（默认） | 0 | 0 | 0 | 0 | 0 | 0 | 696 |
| 32 | 697 | 0 | 0 | 0 | 0 | 0 | 696 |
| 29 | 3,341 | 1,600 | 2 | 0 | 0 | 0 | 696 |
| 16 | 3,994 | 2,712 | 5 | 0 | 0 | 0 | 696 |
| 8 | 23,761 | 11,679 | 14 | 0 | 0 | 0 | 696 |
| 4 | 43,460 | 13,823 | 31 | 0 | 0 | 0 | 696 |
| 3 | 102,685 | 21,503 | 69 | 20 | 14 | 1,230 | 710 |
| 2 | 126,203 | 27,784 | 181 | 57 | 46 | 1,540 | 742 |
| 1 | 311,139 | 83,679 | 401 | 204 | 105 | 2,204 | 801 |

现有 pass 先登记从读端识别的组，再接受其余写端候选。只要一个写端候选与已登记的寄存器有交集，pass 就跳过整个候选，即使读端组后来未能真合并。门槛取 29 和 16 时，形成的连续候选全都在这里被跳过。九份输出逐字节核对，默认组报告完整地出现在每份报告开头。最低门槛新增的 105 个真合并覆盖另外 2,204 个寄存器。这里测得的是结构覆盖，低门槛构建的整机 DiffTest 和耗时仍待验证。[默认组与原始写口 ID](./data/TNO0030_reg_to_mem_groups.jsonl.gz)

## 动态排序

采用 TNO0027 的生成模型及逐站点训练文件，TNO0028 的访问序列以同一份 TNO0027 站点清单为索引。CoreMark 用于训练，MicroBench 留出。两次运行的实际窗口各为 100,001 个 guest cycles。表中一次访问表示一个原始写口使能后进入状态更新判断，一次变化表示该写口的目标值改变。多个锁步写口共用判断时，各自计一次逻辑访问。这个口径衡量端口活动，宿主指令数和时间需另行测量。[逐站点训练](./TNO0027_xiangshan_change_site_pgo.md) · [访问序列与覆盖来源](./TNO0028_xiangshan_value_paths.md)

| 合并写口匹配的拒绝原因 | 组 | 写口 | CoreMark 访问/拍 | MicroBench 访问/拍 | CoreMark 变化/拍 | MicroBench 变化/拍 |
|---|---:|---:|---:|---:|---:|---:|
| `mux_chain` | 734 | 11,290 | 1,148.91 | 1,128.63 | 95.80 | 92.06 |
| `branch_not_in_update` | 1,236 | 23,299 | 1,091.51 | 1,024.80 | 132.45 | 120.36 |
| `priority_guard` | 1,909 | 13,764 | 173.42 | 139.30 | 67.11 | 62.53 |
| `family_mismatch` | 200 | 11,859 | 119.57 | 100.78 | 37.72 | 32.89 |
| `reset_negation` | 4 | 640 | 2.75 | 2.52 | 1.38 | 1.26 |
| `reset_family_mismatch` | 3 | 48 | 0.00 | 0.00 | 0.00 | 0.00 |

原因来自 consolidated-write matcher。先按真合并是否成功分组，再对其余组汇总同一拒绝原因的全部子类型。因此 `priority_guard` 包含匹配到其他行的情况，`family_mismatch` 也包含数据或冲突集不同的组。另有 696 个成功组的 39,754 个原写口已在合并时删除，另列在原始数据中。

- 用发射模型的摘要和各分片的站点清单校验 profile，再用操作符号、目标寄存器符号精确关联原始写口和提交代码。在 50,138 个有原生 EAGER 站点的写口中，有 49,661 个在检查点和发射模型中使用不同的数字 ID。
- 用独立的 Clang 行覆盖逐口复核这 50,138 个写口，两种负载的访问与变化计数全部相符。另外 10,762 个写口用同负载行覆盖补齐。解析器识别直接标量提交、锁步提交和宽值写入助手的返回条件。零次访问来自显式覆盖记录。
- 只取原生站点时，四类的访问排序也相同。`mux_chain` 在两个负载分别为 853.05、832.46 次/拍，`branch_not_in_update` 分别为 523.52、475.90 次/拍。补齐覆盖后，两者更接近。若目标是减少使能后的重复求值，优先检查 `mux_chain`。若目标是减少状态变化后的读者通知，`branch_not_in_update` 的实际变化次数最高。写口之前计算数据和使能的成本仍需结合生成代码或 ELF 采样归因。

## 复现

从仓库根目录运行下列命令。输入检查点、站点 profile 和各组报告的 SHA-256 在汇总 JSON 中。示例采用已有工具构建目录和 TNO0026–0028 留存的输入。[重放脚本](../../scripts/armor_xs_gap_diagnostics/replay_reg_to_mem.py) · [动态关联脚本](../../scripts/armor_xs_gap_diagnostics/rank_reg_to_mem.py)

```bash
tools_dir="$PWD/build/armor-dispatch-v1/tools"
export PYTHONPATH="$tools_dir/python" LD_LIBRARY_PATH="$tools_dir"
ulimit -s unlimited
d=build/armor-generic-writeback-v1
mkdir -p "$d"
checkpoint=build/armor-acc-default-v1/xs/model/wolvrix_xs_pre_reg_to_mem.json
for t in 64 32 29 16 8 4 3 2 1; do
  python3 scripts/armor_xs_gap_diagnostics/replay_reg_to_mem.py "$checkpoint" "$d/groups-$t.jsonl" \
    --min-alternatives "$t" > "$d/replay-$t.log" 2>&1 || exit 1
done

prof=build/armor-xs-site-pgo-v1
for wl in coremark microbench; do
  check=()
  if [ "$wl" = coremark ]; then check=(--check-training); fi
  python3 scripts/armor_xs_gap_diagnostics/rank_reg_to_mem.py "$d/groups-64.jsonl" \
    "$prof/native/model" "$prof/train-sites.tsv.gz" --graph SimTop \
    --sequence "build/armor-xs-value-paths-v1/sequence/$wl" "${check[@]}" \
    --lcov "build/armor-xs-gap-current-v1/coverage/gr_pgo/$wl/model.lcov" > "$d/rank-$wl.json" || exit 1
done
```

本轮 C++ 全量构建成功。32 项 transform CTest 和 5 项相关 emitter CTest 共通过 36/37。唯一失败的 `transform-comb-lane-pack` 期待一个打包的 `kAnd`，在冻结的旧工具上复现了相同断言。新增门槛、组报告、站点归因和顶层重命名的测试均通过。[此前的同一测试记录](./TNO0016_branch_sources_and_eager_logic_20261120.md)
