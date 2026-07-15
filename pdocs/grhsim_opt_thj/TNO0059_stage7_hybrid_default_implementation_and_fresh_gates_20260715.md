# TNO0059 Stage 7 hybrid default implementation and fresh gates

日期：2026-07-15

## 1. 实现边界

按 [TNO0058](./TNO0058_stage7_hybrid_xs_default_adoption_plan_20260715.md) 的最小边界，只修改 `scripts/wolvrix_xs_grhsim.py`：

- direct single-writer state-read 的优先级为 XS 高层变量、既有低层变量、默认 `true`；
- pure-event compute-word bypass 的优先级不变，但两层变量均缺失时默认改为 `true`；
- direct 的已解析值在 emit 前规范化写回当前 Python 进程的低层变量，供 native emitter 读取；
- 配置日志新增 `direct_single_writer_state_reads`；
- profile 继续默认 `false`，word packing 继续默认 `off`。

没有修改 `wolvrix` 子模块、全局 emitter 默认或 Python/native API。显式 XS `0` 仍可恢复 NO0300 行为。

## 2. 配置解析 smoke

脚本语法检查和三组配置 smoke 均通过：

| XS direct/bypass | 低层 direct/bypass | 实际解析 |
| --- | --- | --- |
| 未设置 | 未设置 | `true / true` |
| `0 / 0` | `1 / 1` | `false / false` |
| 未设置 | `0 / 0` | `false / false` |

这验证了 XS 高层覆盖、低层兼容入口和新默认三条路径。`python3 -m py_compile scripts/wolvrix_xs_grhsim.py` 与 `git diff --check` 均通过。

## 3. 新默认 fresh identity

从 current-default canonical pre-reg-to-mem checkpoint fresh 生成：

```text
build/xs_activity_stage7_hybrid_default_20260715/grhsim/grhsim_emit
```

无 feature 环境变量时日志确认：

```text
direct_single_writer_state_reads=True
pure_event_compute_word_bypass=True
pure_event_compute_word_profile=False
pure_event_word_pack_policy=off
```

activity-schedule 保持 NO0300 原结构：SN `63726`、compute/commit `63241/485`、DAG `528622`、BAE `1983923`、boundary values `1000463`。stats SHA256 为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

154 个 generated C++/header 与 Stage 6 未采用 packing 的 probe 逐文件 byte-exact，normalized emit stats 也相同。runtime source 形状精确复现：

```text
direct reads             75830 = 40108 canonical + 35722 aliases
pure-event words           107
eligible batches            22
sparse volatile words       20
sparse batches              14
dense direct words          87
```

新默认 stats 不含 `pure_event_word_pack` key，生成日志也没有 pack planner/applied marker，因此 Stage 6 packing 没有被误带入新默认。

## 4. 显式回滚 fresh gate

同一 checkpoint 在 XS direct/bypass 显式 `0/0`、profile `0`、pack `off` 下再次完整生成：

```text
build/xs_activity_stage7_hybrid_rollback_20260715/grhsim/grhsim_emit
```

日志确认实际解析为 `direct=false / bypass=false / profile=false / pack=off`，完整生成 exit `0`。结构 stats 与历史 NO0300 byte-exact，SHA256 仍为 `e3056375...`。

历史 baseline 与 fresh rollback 的 154 个源码文件中有 88 个 raw hash 不同；diff 证实差异来自 checkpoint 重载后重新编号的 `// op`、`// value` 等诊断注释。删除整行纯注释后 154 个文件全部 byte-exact，源码行数也完全相同 `13,911,084`。因此显式 `0/0` 的可执行生成逻辑精确回到 NO0300，raw comment ID 不作为行为 identity。

## 5. Fresh O3 static gate

新默认与显式回滚均独立 O3 构建成功，exit `0`：

| 指标 | rollback NO0300 | hybrid default | 变化 |
| --- | ---: | ---: | ---: |
| all generated source bytes | 1,377,536,436 | 1,356,877,099 | `-1.499731%` |
| all generated source lines | 13,911,084 | 13,684,888 | `-1.626013%` |
| emu bytes | 94,768,184 | 93,694,944 | `-1.132490%` |
| emu `.text` | 94,592,303 | 93,519,380 | `-1.134260%` |

hybrid fresh `.text` 与 Stage 6 probe 逐字节相同。fresh rollback 与 7 月 14 日历史 baseline 的文件大小相同，`.text` 仅差 48 bytes；其可执行源码删除诊断注释后全同，故该 48-byte 差异记录为跨构建时间的 native layout 噪声。正式 runtime 使用本轮 fresh rollback 作为 A 组，避免混入历史构建年代。

O3 emu SHA256：

```text
rollback  cd093aadefee6e84e236d8826558e6bc9beeebaee41f2133bf6dc57c0457fe97
hybrid    ae6b6df7ab5fff8b003414d9b2e3c80937b9ef30e9fe55bb8c670742e35b281e
```

## 6. Fixed-ASLR functional gate

hybrid fresh emu 在 `setarch x86_64 -R` 下依次通过 100/10k/50k：

| Limit | Guest / cycle / instr | PC |
| ---: | --- | --- |
| 100 | `101 / 96 / 0` | `0x0` |
| 10k | `10001 / 9996 / 458` | `0x800027c6` |
| 50k | `50001 / 49996 / 73580` | `0x80001312` |

三档 exit 均为 `0`，mismatch/assert/error/fail/bad-trap 等负向扫描为 0。50k 在并行 rollback emit 负载下只作为功能门禁，`79.960s` host time 不作性能数据。

## 7. Review 与下一步

独立只读 review 未发现 blocker、major 或 minor 行为问题；确认环境优先级、显式回滚、全局默认边界、packing 关闭和文档索引均正确。当前剩余门禁是以 fresh rollback / hybrid / fresh rollback 执行 quiet fixed-ASLR 50k A/B/A。runtime 结果形成独立文档前，不依据静态缩小直接完成默认采用。
