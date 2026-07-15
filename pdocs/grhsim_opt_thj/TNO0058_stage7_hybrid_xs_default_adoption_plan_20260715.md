# TNO0058 Stage 7 hybrid XS-default adoption plan

日期：2026-07-15

## 1. 依据与目标

[TNO0057](./TNO0057_stage6_quiet_runtime_and_default_decision_20260715.md) 已把两个因果结论分开：

- 新增 active-word packing 在 CPU11/203 与 CPU84/276 两组有效 quiet A/B/A 中分别回退 `+1.232498%` 与 `+5.159403%` cycles，必须保持关闭；
- 已有 direct single-writer state-read + threshold-2 pure-event bypass 组合，在 current-default/probe/current-default 有效组中相对当前 NO0300 提升 `11.409784%` cycles，control spread `0.157393%`。

Stage 7 的目标是把后一组合采用为 XiangShan GrhSIM 生成脚本的新默认，同时保持全局 emitter 默认和 packing 默认不变。该阶段不把 existing hybrid 重命名为 packing 收益，也不改 activity-schedule 结构。

## 2. 最小配置改动

只修改 `scripts/wolvrix_xs_grhsim.py`：

1. 新增 XS 高层 `WOLVRIX_XS_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS`；优先级为 XS 高层、既有低层 `WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS`、默认 `true`。
2. `WOLVRIX_XS_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS` 继续优先于低层同名配置，但两层均缺失时默认从 `false` 改为 `true`。
3. direct-state 配置在调用 emitter 前写入当前 Python 进程的低层环境变量，因为现有 native binding 尚无该显式参数；XS 高层已经解析出的值必须覆盖该进程内低层值。
4. 日志显式打印 `direct_single_writer_state_reads`，避免默认身份只存在于隐式 emitter stderr。
5. `pure_event_compute_word_profile=false`、`pure_event_word_pack_policy=off` 保持不变。

不修改 `wolvrix/lib/emit/grhsim_cpp.cpp` 的全局默认，不修改 Python/native emitter API，也不修改非 XS 调用方。显式回滚命令为：

```text
WOLVRIX_XS_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=0
WOLVRIX_XS_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=0
```

低层两个 `WOLVRIX_GRHSIM_*` 变量也继续可在没有 XS 高层覆盖时显式设为 0。

## 3. Fresh identity 门禁

从 current-default pre-reg-to-mem checkpoint 生成独立 Stage 7 目录。生成 shell 必须先执行 `source env.sh`，并确认四个相关环境变量没有从调用环境继承。无显式 feature env 的新默认日志必须显示：

```text
direct_single_writer_state_reads=True
pure_event_compute_word_bypass=True
pure_event_compute_word_profile=False
pure_event_word_pack_policy=off
```

新默认必须满足：

- activity-schedule stats 与 current-default NO0300 byte-exact；
- generated C++/headers 与 Stage 6 probe 的 runtime source byte-exact；
- direct read 命中 `75830 = 40108 canonical + 35722 aliases`；
- pure-event marker 为 107 words、22 eligible batches、20 sparse volatile words、14 sparse batches；
- 没有 word-pack planner/applied marker，packing policy 仍为 off；
- source、`.text` 或静态指令若与 probe 不一致，先解释 schema-only stats 或路径产物，不能直接沿用旧 runtime。

显式回滚至少验证配置解析为 direct/bypass false；若 fresh rollback emit 可接受，则与 current-default NO0300 C++/headers 逐文件比较。无论是否做第二次完整 emit，core 已有 default/explicit-off source identity 回归不能退化。

## 4. Build、功能与 runtime

新默认独立 O3 build 后依次通过 fixed-ASLR：

1. 100-cycle smoke；
2. 10k NEMU difftest；
3. 50k CoreMark difftest。

终点必须为 `50001/49996/73580/0x80001312`，负向扫描为 0。随后执行 current-default NO0300 / Stage 7 new-default / current-default NO0300 的 atomic quiet 50k：双 sibling idle `>=99%`、gate-to-run gap `<=5s`、五事件 `100% scheduled`、control cycles spread `<=1%`。

Stage 6 现有 probe binary 的 `-11.409784%` cycles 是采用依据；Stage 7 fresh build 若因 native layout 变化不能复现至少 `max(1%, control spread)` 的正收益，则不改变 XS 默认。direct state-read 历史上有明显 native layout 敏感性，因此必须保留本轮 fresh binary 的独立结果，不能只引用 exact-entry 或旧 probe 数据。

## 5. 提交边界

Stage 7 预期只修改父仓脚本和 TNO 文档，不产生子模块提交。完成 fresh identity、build、功能与 runtime 后，以任务整体提交脚本、TNO0058 及后续实现/门禁文档；生成目录和 perf 日志不提交。
