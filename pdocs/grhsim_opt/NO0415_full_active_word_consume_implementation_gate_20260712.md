# NO0415 Full active-word consume implementation gate

日期：2026-07-12

## 1. Implementation

承接 [NO0414](./NO0414_local_active_word_consume_machine_gate_20260712.md)，nested `wolvrix`
commit `7ba0cd6` 新增默认关闭的 GrhSIM emitter option：

```text
option: full_active_word_consume
emitter env: WOLVRIX_GRHSIM_FULL_ACTIVE_WORD_CONSUME
XiangShan flow env: WOLVRIX_XS_GRHSIM_FULL_ACTIVE_WORD_CONSUME
```

`scripts/wolvrix_xs_grhsim.py` 会读取 XS flow env、写入 config log，并显式传给 emitter，避免只依赖
进程环境隐式生效。

生成规则严格限定为：

```cpp
model.fullActiveWordConsume &&
batch.phase == ScheduleBatch::Phase::kCompute &&
dispatchMask == UINT8_C(0xff)
```

命中时仍保留：

- global active byte clear；
- per-word nonzero gate；
- 八个 per-supernode bit gates；
- 同 word later-bit local activation。

只省略八个 `activeWordFlags &= ~bit` 和末尾 `global |= activeWordFlags`。partial compute word、全部
commit word 与 option-off 输出保留原协议。该规则不需要预扫描 payload，也不改变 active bitmap 布局、
batch/topo、fixed-point 次序或 commit 语义。

## 2. Directed functional coverage

新增 9 级 8-bit add chain fixture，并强制 activity schedule 把 oversize compute node 按单 op 拆开。
它同时覆盖：

1. 完整 active word 内 changed-value 向 later bit 的 local activation；
2. 完整 word 之后的 partial boundary word；
3. 第二次 `eval()` 只由 input change 激活链头，不能依赖 first-eval 全图 seed；
4. option-off 默认生成仍含 local clear/restore；
5. option-on full word 不含 clear/restore，partial word 仍包含两者。

generated harness 先令 `chain_in=1`，检查 9 级输出为 10；再令 `chain_in=7` 并第二次 eval，检查
输出为 16。第二次检查证明 full word 内传播与跨 partial word 传播都实际生效。

## 3. Build and tests

所有命令均先执行 `source env.sh`：

```text
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
cmake --build wolvrix/build --target emit-grhsim-cpp -j8
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp-memory-fill$' --output-on-failure
```

结果：

| Gate | Result | Time |
| --- | --- | ---: |
| Python syntax | pass | - |
| emitter target build | pass | - |
| `emit-grhsim-cpp` | `1/1` pass | `181.40s` |
| `emit-grhsim-cpp-memory-fill` | `1/1` pass | `5.01s` |

首次 chain fixture 只设置 `maxOpInComputeSupernode=1`，但 compute-node builder 已先把链合成一个
18-op node，因此没有完整 active byte，source-shape assertion 正确失败；没有进入 harness，也不是实现
功能失败。补上 `splitOversizeComputeNodes=true` 与 split max ops 1 后，fixture 形成 full+partial words，
完整测试通过。

## 4. Decision

实现与 synthetic 功能门禁通过，option 继续默认关闭。下一步重装 editable Python binding，复用与
NO0357 相同的 pre-reg checkpoint 做 fresh SimTop emit；先要求 schedule/graph 结构完全一致，并统计
full/partial source 覆盖，再做 O3 build 与 10k/50k difftest。只有功能通过后才在 quiet CPU 上做
fixed-ASLR old/new/old，机器负载不稳时同步重跑 baseline。
