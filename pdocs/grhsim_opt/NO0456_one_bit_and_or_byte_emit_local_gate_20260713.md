# NO0456 One-bit AND/OR byte emit local gate

日期：2026-07-13

## 1. 结论

[NO0455](./NO0455_one_bit_bitwise_byte_emit_implementation_plan_20260713.md) 的第一版完整覆盖
`kAnd/kOr/kXor/kNot/kXnor`，功能正确但未通过 local O3 总指令门槛：default/candidate 均为 38 条。
汇编差异显示 state AND 删除的 2 条 normalization 指令被 XNOR 新增的 2 条指令完全抵消。

因此候选按机器证据收窄为 width-1 `kAnd/kOr`，不再改写 XOR/NOT/XNOR。收窄版保持功能回归通过，并将
fixture 指令数从 38 降到 36（`-5.26%`），memory-form instruction 和 branch 均不增加，允许进入代表
SimTop batch 静态 gate。

## 2. 实现

nested `wolvrix` commit：

```text
0d6c3c1 perf: emit one-bit and or as bytes
```

配置保持为：

```text
EmitOptions attribute: one_bit_bitwise_bytes
Environment:          WOLVRIX_GRHSIM_ONE_BIT_BITWISE_BYTES
Default:              false
```

开关命中需同时满足：

- operation 是 `kAnd` 或 `kOr`；
- result width 为 1；
- 所有 operand 均为 width-1 Logic value。

命中后 operand 以 `std::uint8_t` 读取，并通过 always-inline `grhsim_assume_bit_u8()` 向编译器声明值域
为 0/1；中间 result 也保持 `std::uint8_t`。changed compare、bool slot 写回、activation、schedule 和 state
layout 均不改变。helper 只在开关开启时生成，unset/0 路径不生成 helper。

## 3. 功能 gate

新增 fixture 覆盖 materialized AND/OR、OR feeding AND、state read feeding AND、XOR/XNOR/NOT、
`kLogicAnd`、width-8 AND 和 posedge register update。三种 emit 变体为 unset、attribute=0 和 attribute=1。

source gate：

- unset 与 attribute=0 的完整 combined source byte-exact；
- unset 不含新 helper；
- enabled 的目标 AND/OR 使用 assumed-byte operand/result；
- XOR/XNOR/NOT、`kLogicAnd` 和 width-8 AND 保持原表达式；
- enabled harness 穷举 32 组五输入组合，并检查两次上升沿后的 state AND。

结果：

```text
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
1/1 passed, 186.23 s

ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp-memory-fill$'
1/1 passed, 4.90 s
```

## 4. Local O3 gate

对测试生成的 default/enabled `grhsim_top_sched_0.cpp` 使用相同命令：

```text
clang++ -std=c++20 -O3 -I<variant-dir> -c grhsim_top_sched_0.cpp
```

统计排除 nop：

| variant | instructions | memory-form | branches |
| --- | ---: | ---: | ---: |
| default | 38 | 19 | 1 |
| first broad candidate | 38 | 19 | 1 |
| narrowed AND/OR candidate | 36 | 19 | 1 |

最终 default/candidate 唯一语义汇编差异位于 state AND：

```asm
# default
cmpb   $0x0,0x50(%rdi)
setne  %dl
and    %cl,%dl
mov    %dl,0x48(%rdi)

# candidate
and    0x50(%rdi),%cl
mov    %cl,0x48(%rdi)
```

即 operand normalization 的 `cmpb + setne` 被删除，目标 AND、store、memory count 和 branch count 保持。
采样时机器为 384 logical CPU，load average `7.74/7.43/6.87`，静态编译对照不受高负载干扰。

## 5. 下一步

local gate 只证明表达式机制有效，尚不能说明 SimTop 全局 object 会缩小。下一阶段按 NO0455 约束 fresh emit
current SimTop，只开启该开关，先编译 batch 0/1/29/32/43，并将 NO0454 的 source marker 连接到目标基本块。
至少三个不同 source shape 真正删除 normalization，且代表 objects 的总 `.text`、branch、memory 不恶化，才进入
full build 和功能回归；否则保持开关默认关闭并停止该候选。
