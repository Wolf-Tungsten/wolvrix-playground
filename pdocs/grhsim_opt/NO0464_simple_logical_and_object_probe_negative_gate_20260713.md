# NO0464 Simple logical AND object probe negative gate

日期：2026-07-13

## 1. Scope correction

按 [NO0463](./NO0463_simple_logical_and_object_probe_plan_20260713.md) 对 batches 21/26/36/57/58/65 做 generated-copy
probe。首轮转换检查发现 operand regex 还组合出计划未覆盖的 765 行 `local && local`；这些首轮 objects 在比较前作废。

v2 转换器显式拒绝 `local/local`，重新从原始 NO0357 sources 生成副本。有效转换共 14,182 行：

| shape | transformed lines |
| --- | ---: |
| local/bool-slot | 10,899 |
| bool-slot/bool-slot | 3,010 |
| bool-slot/local | 273 |

14,182/14,182 行的 before 含唯一目标 ` && `、after 含对应 ` & `，`local/local=0`、malformed=0；逐文件 diff
恰为每次转换一条删除加一条新增，没有修改其他 source line。

## 2. Compile identity

6/6 candidate objects 用 NO0357 header/PCH 与 `clang++ -std=c++20 -O3` 编译成功，全部 compile logs 为 0 lines；
编译前后 6 个 production objects SHA 不变。为排除旧 object/toolchain 差异，又用同一命令重编 unchanged NO0357 sources：

- 6/6 rebuilt `.text` SHA 与 production objects 完全一致；
- 6/6 compile logs 为 0 lines；
- whole-object bytes 因非 `.text` metadata 不同，不用于 gate。

因此以下差异由 `&& -> &` candidate 本身产生。

## 3. Whole-object result

| batch | text bytes delta | instructions delta | memory-form delta | jumps delta |
| ---: | ---: | ---: | ---: | ---: |
| 21 | +9,186 | -1,025 | +1,199 | -1,050 |
| 26 | -17,305 | -4,233 | -3,481 | -1,864 |
| 36 | -45,855 | -12,463 | -8,600 | -4,235 |
| 57 | -10,970 | -1,565 | -761 | -148 |
| 58 | -15,646 | -2,459 | -1,446 | -651 |
| 65 | -837 | -58 | +9 | -12 |
| aggregate | -81,427 (`-1.501%`) | -21,803 (`-1.891%`) | -13,080 (`-2.684%`) | -7,960 (`-18.133%`) |

Calls aggregate 为 4,032 -> 4,032。aggregate 三项都显著改善，local/bool-slot 热点 batch 36 与
bool-slot/bool-slot 主导的 batches 57/58 也分别得到净收益。

## 4. Local regression mechanism

batch 21 是明确局部回退：虽然 instructions/jumps 下降，但 text 增 9,186 bytes、memory-form 增 1,199。主要 mnemonic
变化为：

```text
removed: cmpb -2636, setne -1033, jmp -699, jne -520
added:   movzbl +3309, and +897, test +709, or +553, mov +177
```

bitwise `&` 强制求值右侧 slot；Clang 在该 TU 中用更多无条件 byte loads/logic 替换短路 compare/setcc/branch，解释了
“总指令下降但 text/memory 上升”。batch 65 也有 memory-form `+9` 的小幅同向信号。该 tradeoff 依赖 surrounding TU，
不能从 aggregate branch 降幅推断 SimTop runtime 必然改善。

## 5. Decision

NO0463 要求 aggregate memory-form 不增且 6 个对象无明显局部回退；batch 21 以 `+1,199` memory-form 和 `+9,186`
text 明确失败。按预声明硬门禁停止 simple logical-AND 改写：

- 不修改 emitter，不增加默认关闭开关；
- 不做 full SimTop emit/build/runtime；
- 不用 batch allowlist 或只保留表现好的 operand/TU 子集规避 gate；
- 不扩展到 nested/complex logical AND 或未采样的 local/local。

下一步回到 NO0461 约定的 scope-corrected exact `kEq`/`kLogicAnd` residual，重新寻找不依赖强制 slot load 的机制。
