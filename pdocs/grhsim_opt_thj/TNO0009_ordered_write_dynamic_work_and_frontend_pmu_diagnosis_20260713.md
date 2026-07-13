# TNO0009 Ordered-write dynamic work and frontend PMU diagnosis

记录日期：2026-07-13

来源范围：`NO0309..NO0328`，原始记录见 [NO0309](../grhsim_opt/NO0309_no0286_no0300_dynamic_work_plan_20260712.md) 至 [NO0328](../grhsim_opt/NO0328_no0286_no0300_l2_instruction_pmu_gate_20260712.md)。

状态：在当时随机 PIE 基址下完成系统 PMU 排查；结果证明动态 work 下降，表面回退来自非 cache/TLB miss 的 frontend supply/layout。绝对性能方向由 TNO0010 fixed-ASLR 重校准。

## 1. Dynamic-work 闭环

新增 strict TSV compare 和 stable-op/batch profile 工具，完整连接 67,934/63,726 rows。NO0300 相对 NO0286：

```text
fire             -4.91%
operator work    -4.30%
activation work  -7.32%
```

随机基址下 cycles 却上升约 3.85%，归一化 cycles/work 表面回退 `8.52%`。这排除了“ordered-write 做了更多动态工作”。

## 2. PMU 排查链

所有正式 native groups 均要求 100% scheduled；首个 83% multiplex 样本明确作废。随后结果为：

| Domain | Observation | Decision |
| --- | --- | --- |
| frontend/backend/I-cache | empty slots/cycle `+3.00%`，backend 与 I-cache density 改善 | 偏 frontend |
| latency vs bandwidth / ITLB | latency slots `+6.62%`，bandwidth与 ITLB miss density下降 | 非 ITLB |
| branch redirect/resync | 绝对值与 per-cycle 均下降 | 非 redirect 主因 |
| op-cache | miss rate改善、dispatch share提高 | 非 op-cache fallback |
| L2 instruction | fill miss per-cycle/work下降 | 非 fetch miss-count 链 |

cmask6 fixed-period profile 得到 17,434/19,558 samples、0 lost；compute 占 full-empty 增量 84.37%，但最大单 batch 仅占 compute 3.34%，annotate 也没有单指令集中。

## 3. Stable-op density

跨版本不能用同编号 batch 直接对齐。stable-op origin-density 工具筛出 compute39/29/13/4 等候选，但代表 old12→new13 中 text/instructions 已缩小，full-empty density 却增加 44.1%，继续指向函数布局与地址，而不是逻辑工作。

## 4. 阶段结论

在随机 PIE 基址口径下，cache、TLB、redirect 和 op-cache 都无法解释回退；剩余证据指向大 batch 函数的地址/layout 敏感性。该结论直接触发页对齐、object-order 和 fixed-ASLR 实验；旧的 `cycles/work +8.52%` 不再作为最终机制结论。

## 5. 规则审计与关键数据

记录类型：ordered-write runtime 反常的 root-cause 排除链。单一议题边界是“随机基址下 cycles 回退是否由动态 work、cache/TLB 或 redirect 增加造成”。PMU 子实验只用于逐项排除该问题；fixed-ASLR 后其相对性能数字由 [TNO0010](./TNO0010_code_layout_aslr_and_fixed_profile_20260713.md) 取代。

### 5.1 Dynamic-work 50k

strict/ordered 两版都完成 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`，profile TSV 分别有 `67,934/63,726` 行：

| Metric | Strict NO0286 | Ordered NO0300 | Delta |
| --- | ---: | ---: | ---: |
| total fire | 855,899,893 | 813,853,977 | `-4.912%` |
| `work_total` | 87,495,065,123 | 83,730,351,495 | `-4.303%` |
| activation work | 20,193,598,869 | 18,714,440,805 | `-7.325%` |
| profile-instrumented wall | 82,159ms | 78,229ms | `-4.78%`, 不作性能结论 |

无插桩随机基址样本则为 baseline mean `297,550,420,793` host cycles、ordered `309,005,122,520`，即 `+3.85%`；合并后曾得到 cycles/work `+8.52%`。profile walltime 含按 fire 计数开销，不能替代无插桩数据。

### 5.2 PMU 数据边界

- 五事件 corrected runs 均要求 `100%` scheduled；首次 `83%` multiplex 样本明确作废。
- cmask6 fixed-period profile得到 old/new=`17,434/19,558` samples、0 lost；compute 占增量 `84.37%`。
- ITLB、redirect、op-cache 与 L2 instruction miss 的绝对或归一化方向均未随回退恶化。
- 上述 runs 的 PIE base 未固定，所以只保留“排除动态 work/miss-count 根因”的定性价值，不保留 `+8.52%` 为最终单位成本结论。

来源见 [NO0312](../grhsim_opt/NO0312_no0286_no0300_dynamic_work_gate_20260712.md)、[NO0314](../grhsim_opt/NO0314_native_stall_pmu_group_correction_20260712.md)、[NO0323](../grhsim_opt/NO0323_no0286_no0300_frontend_full_empty_profile_20260712.md) 与 [NO0328](../grhsim_opt/NO0328_no0286_no0300_l2_instruction_pmu_gate_20260712.md)。
