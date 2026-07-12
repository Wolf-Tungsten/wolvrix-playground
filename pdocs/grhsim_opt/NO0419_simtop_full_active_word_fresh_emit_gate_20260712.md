# NO0419 SimTop full active-word fresh emit gate

日期：2026-07-12

## 1. Configuration and completion

在 [NO0417](./NO0417_full_active_word_python_option_correction_20260712.md) 与
[NO0418](./NO0418_full_active_word_native_binding_correction_20260712.md) 补齐 Python/native 参数接线后，
第三次按 [NO0416](./NO0416_full_active_word_consume_fresh_emit_plan_20260712.md) 的原配置执行 fresh emit。
所有命令均先 `source env.sh`，最终日志为：

```text
build/logs/xs/xs_wolf_grhsim_emit_no0416_full_word_consume_final_20260712.log
```

配置日志明确为 `full_active_word_consume=True`，执行 exit 0：

```text
read checkpoint: 50.228 s
reg-to-mem:       159.086 s
activity schedule:129.996 s
C++ emit:          64.826 s
flow total:       404.139 s
wall time:        407.89 s
max RSS:       29,128,412 KiB
```

## 2. Graph and direct-read gates

schedule stats SHA256 精确复现 NO0357：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

核心结构计数保持：

```text
supernodes=63,726 compute=63,241 commit=485
dag_edges=528,622 boundary_values=1,000,463
boundary_activation_edges=1,983,923
compute_compute_value_pairs=1,721,698
compute_commit_value_pairs=262,225
state_read_activation_edges=84,972
```

direct state-read 也精确命中既定上界：

```text
reads=75,830 canonical=40,108 aliases=35,722
groups=40,108 source_groups=40,108
removed_source_heads=37,672 consumer_heads=39,602
```

## 3. Exact source-shape gate

不是只统计字符串。verifier 对 NO0357 baseline 的每个 compute dispatch block 应用唯一允许的转换：

1. 仅当 `dispatchMask == 255` 时删除 8 次 local bit clear 和末尾 1 次 local restore；
2. partial block 不做转换；
3. 再把规范化后的完整文件与 fresh candidate 逐字节比较。

结果为：

```text
compute batches normalized exact: 66/66
compute words:                    7,932
full words transformed:           7,853
partial words retained:              79
full local clears removed:       62,824
full restores removed:            7,853
partial protocol exact:            79/79
commit files byte-exact:           51/51
non-schedule files byte-exact:     40/40
```

partial masks 覆盖稀疏和连续多种形态，不只是末尾低位 mask。所有 partial block 仍满足
`local clears == popcount(mask)` 且恰有一次 restore。commit batch `66..116` 与 NO0357 完全不变。

## 4. Source size

在相同 157 个 generated files 上：

| metric | NO0357 | full-word | delta |
| --- | ---: | ---: | ---: |
| bytes | 1,357,274,501 | 1,348,473,508 | -8,800,993 (-0.648%) |
| lines | 13,684,763 | 13,551,262 | -133,501 (-0.976%) |

该变化完全由 66 个 compute files 中的预期语句删除构成，没有 graph/schedule、commit、state、eval、header
或 Makefile 漂移。

## 5. Conclusion and next gate

NO0416 fresh source gate 通过。下一阶段单独记录标准 Clang/O3 build；build 成功后先做 SimTop 100-cycle
smoke，再做 10k/50k CoreMark/NEMU difftest。未通过功能门禁前不采集性能结论。
