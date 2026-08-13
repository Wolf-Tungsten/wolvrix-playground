# 010. TRBS：热点 input 选择、slot 重映射与 exact-posedge bool 预解码

这是 TRBS 的第二个机制层。它解决的是：在大量事件边查询中，某个 input event 的
`posedge` 判断远多于其他判断，是否可以提前把这个布尔结果物化，而不让每个
schedule leaf 都重复读取 enum 并比较。[^0211]

schedule 是生成器安排仿真操作执行先后的计划；batch 是其中一组连续执行的计算；
leaf 是具体计算节点；operand 是该节点读取的输入；predicate 是最终用作 guard 的真假
条件。这里的 **exact-posedge** 只指明确要求某输入发生 0→1 上升沿的 predicate，
不泛指 negedge 或任意事件。

## 做了什么

### 1. 选择热点并稳定重映射

emitter 遍历最终 schedule 的每个 batch，按 input event 统计：

* `posedgeUses`：所有 exact-posedge 查询的总次数；
* `coveredBatches`：至少出现一次该 operand 的 batch 数；
* `reusableUses = posedgeUses - coveredBatches`。

选择 `reusableUses` 最大的 input event，平手时再比较 `posedgeUses`，仍相等时保持
input registration order。`reusableUses` 的直观含义是：每个覆盖 batch 至少要读取
一次，扣除这些不可避免的读取后，还有多少次查询能够复用预解码结果。选中后把事件放到
typed array 的内部第一个元素 slot 0；这不改变外部端口编号、绑定顺序或 API。[^0214]

### 2. 在对象中预解码 exact-posedge

每次输入事件分类时，完整 enum 仍被写入 typed event storage；若该事件是选中的
hot input，则同时写入对象成员 `hot_event_posedge_`。之后 exact-posedge leaf
直接使用这个 bool：

```text
hot_event_posedge_ = event_edge_storage_[0] == posedge;
```

其他 input、`negedge`、无指定 edge 和 general event 继续比较完整 enum。这样只
专门化可证明的热点查询，残余路径保持原语义；对象 clear/init 同时清 enum 和 bool。[^source]

## 为什么这样做

如果一个热点事件在同一轮的很多 batch 中被重复查询，反复读取 enum 成员并比较会
形成共同的对象依赖链。将分类结果物化为 bool，即实际分配一个对象字段保存这次比较
结果，让后续查询直接读取该字段，可以减少重复成员读取和 enum 比较。这里不声称每次
enum 比较都会生成 CPU 分支；具体机器码由编译器决定。“热点”由最终 schedule 的
exact-posedge 使用量决定，不使用
SimTop 端口名、ValueId、固定模型大小或 benchmark 字符串。[^0214]

原则化门禁收取启发式固定成本 `2`（概括一次 bool materialize 和一次 clear），只有
`reusableUses > 2` 才启用；因此小模型或机会不足时保持旧路径。SimTop 的诊断值为
`input_events=2`、`event_slots=412`、`selected_input_index=0`、
`posedge_uses=220132`、`covered_batches=76`、`reusable_uses=220056`、
`fixed_cost=2`，远超门槛但没有依赖任何负载名字。这里的 2 是生成器用于比较机会和
成本的静态单位，不表示两条 CPU 指令或两个 cycle。[^0214]

## 收益（SimTop 50k）

为了区分“把热点搬到 slot 0”的布局收益和“真正预解码 bool”的收益，SimpleTES 做了
机械 direct ablation：[^0213]

| 对比 | 新增内容 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `T→TR` | 只保留 typed storage + hot selection/remap | 49,854.50 | 49,859.00 | **−4.50** | **−0.009026%**（中性） | −0.007023% / −0.011029% |
| `TR→TRB` | 增加 object exact-posedge bool 预解码 | 50,024.75 | 48,474.75 | **1,550.00** | **3.098466%** | 3.146157% / 3.050827% |

`T→TR` 的 −0.009026% 说明“选择/重映射”本身不应被宣传为独立性能收益；它的
主要作用是提供稳定、通用的承载位置。真正的边际收益来自 `TR→TRB` 的 bool
预解码。两组 order gap 分别为 `0.004006 pp` 和 `0.095330 pp`，均满足协议。[^0213]

完整组合的 endpoint `B→TRBS` 是 `51,562.00→47,632.25 ms`，减少
`3,929.75 ms`、改善 `7.621407%`；相邻机制有交互，不能将 `2.748192%`、
`3.098466%` 等数字线性相加。[^0213]

PMU 也支持“前端/依赖链改善”解释：endpoint cycles 降 `7.645900%`，frontend
no-dispatch 降 `8.735190%`，但 instructions 增加 `1.025808%`；所以收益不是
简单删除动态指令。[^0213]

## 落地与正确性

* 通用 C++ emitter 默认启用，Python 流程继承；没有 SimTop 专用开关，也没有借用
  `targeted-direct`。[^0214]
* 新增的 direct-hot 专项测试覆盖端口重命名、port-binding 顺序、hot event 非首个
  注册项、平手稳定性、`reusableUses == 2` fail-closed、255/256/257 边界和
  posedge/negedge/general 混用。fresh 结果为 direct-hot `1/1`、主 emitter `1/1`、
  full CTest `51/53`（仅两项既有 expected failure）、pybind `29/29`、XS `32/32`。[^0214]
* 旧 raw slot-count 门禁与原则化门禁在 SimTop 生成相同 fingerprint；同 CCD 50k
  `47,567.25→47,597.00 ms`，新门禁慢 `29.75 ms/0.062543%`，order gap
  `0.072499 pp`，判定为噪声等价并保留。[^0214]

### 数据来源（尾注）

[^0211]: [`TNO0211`：post-four 研究完成](../grhsim_opt_thj/TNO0211_simpletes_post_four_gpt_max_research_completion_20260801.md)，给出搜索路线、候选机制和最终 TRBS 结果。
[^0213]: [`TNO0213`：direct ablation final attribution](../grhsim_opt_thj/TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md)，给出 `T→TR`、`TR→TRB`、endpoint 的绝对 walltime、相对变化、ABBA/BAAB 和 PMU。
[^0214]: [`TNO0214`：原则化 gate landing/native 对比](../grhsim_opt_thj/TNO0214_principled_hot_event_landing_and_native_gate_20260801.md)，给出选择公式、SimTop 计数、测试结果、旧/新 gate 50k 对比和 Wolvrix commit。
[^source]: Wolvrix `lib/emit/grhsim_cpp.cpp`（`d3ed9dea`）的 `selectDirectHotInputEventEdge`（约 4463–4580）、`exactEventExpr`（约 17827–17873）、batch snapshot 使用点（约 22801–22839）、clear/classify（约 20554–20566、30360–30372、30814–30823）。
