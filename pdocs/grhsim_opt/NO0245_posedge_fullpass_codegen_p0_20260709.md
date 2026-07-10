# NO0245 Posedge full-pass specialization P0 codegen A/B

日期：2026-07-09

## 背景

`NO0243` / `NO0244` 已经用 generated C++ 手工 patch 证明：在仅发生 `posedge`、其他输入稳定的 high eval 中，可以先执行 commit batch，再在状态确实变化时对 compute batch 做一次 full-pass settle，从而跳过 commit-activated active propagation。本文记录把该 probe 收敛为默认关闭的 GrhSIM emitter 开关后的 P0 codegen 与 small-load gate。

本轮实现是 `NO0242` 的增量：baseline 为 `input_fullpass_specialization=1, posedge_fullpass_specialization=0`，candidate 为二者同时打开。

## 实现摘要

新增默认关闭开关：

- Python/native emitter option：`posedge_fullpass_specialization`。
- 环境变量：`GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION`。
- `testcase/xs-components` CLI：`--posedge-fullpass-specialization`。
- Makefile 变量：`GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION ?= 0`。

当前 codegen 只在保守条件下生成 fast path：

1. `inputEventValues.size() == 1`；
2. 存在 commit schedule batch；
3. 当前 eval 非 first eval；
4. 唯一 event input 是 `posedge`；
5. 其他 input / inout input 与上一拍缓存值相等。

fast path 形态：

```cpp
if (posedge_fullpass_candidate) {
    pending_eval_round = false;
    supernode_active_curr_.fill(0);
    commit_activated_readers_ = false;
    eval_commit_batch_*();
    const bool state_changed = commit_activated_readers_;
    supernode_active_curr_.fill(0);
    if (state_changed) {
        eval_compute_batch_*_fullpass();
    }
    commit_activated_readers_ = false;
    supernode_active_curr_.fill(0);
    // clear event edges, update prev inputs / first_eval_ / waveform
    return;
}
```

未命中条件时完全回落原 fixed-point eval。当前仍默认关闭，不改变默认 GrhSIM 行为。

## 验证命令

所有命令均在 `source env.sh` 后执行。

```bash
python3 -m py_compile testcase/xs-components/scripts/emit_grhsim.py \
  wolvrix/app/pybind/wolvrix/__init__.py
python3 -m pip install --no-build-isolation -e wolvrix
```

`xs-components` gate 产物：

```text
tmp/no0245_posedge_codegen_gate_20260709/
```

对每个 case 均生成两份 GrhSIM：

- `input_only`：`--input-fullpass-specialization`
- `both`：`--input-fullpass-specialization --posedge-fullpass-specialization`

并运行：

- raw bench：`200000` vectors，`repeat=3`
- phase profile：`200000` vectors
- correctness：`both --verify 200000`

机器负载：`nproc=384`；gate 期间 `uptime` 记录的 1min load 约 `7.39 -> 15.09 -> 11.40`。相对 384 硬件线程不高；同时，本轮所有性能数均为相邻 paired baseline/candidate，因此主要看相对差值。

## 生成代码 gate

三组 `both` 生成物均包含 `posedge_fullpass_candidate` 与 `Posedge-only full-pass fast path`：

```text
XsReal053FtqFtqLarge: eval_commit_batch_6()
XsReal043TageTageLarge: eval_commit_batch_5()
XsReal075RobVtypebufferLarge: eval_commit_batch_4()
```

Makefile dry-run 确认变量会传到 CLI：

```text
--input-fullpass-specialization \
--posedge-fullpass-specialization
```

## Runtime gate 结果

| case | raw min input-only ms | raw min both ms | delta | phase input-only ms | phase both ms | delta | low delta | high delta | checksum | verify |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `XsReal053FtqFtqLarge` | `477.164` | `437.741` | `-8.26%` | `488.004` | `450.461` | `-7.69%` | `-2.63%` | `-11.30%` | match | pass |
| `XsReal043TageTageLarge` | `397.891` | `362.134` | `-8.99%` | `409.411` | `377.342` | `-7.83%` | `-4.87%` | `-10.11%` | match | pass |
| `XsReal075RobVtypebufferLarge` | `373.064` | `331.439` | `-11.16%` | `392.173` | `336.834` | `-14.11%` | `-10.54%` | `-17.14%` | match | pass |

`both --verify 200000` 日志均为：

```text
[VERIFY] ... vectors=200000 status=pass
```

## 结论

1. Posedge full-pass specialization 已经从 generated C++ probe 收敛为默认关闭的 emitter/CLI/env 开关，并通过 3 个较大 xs-component 的 200k correctness gate。
2. 相对已经打开 input full-pass 的 baseline，三组 raw runtime 继续下降 `8.26% ~ 11.16%`；phase high 部分下降 `10.11% ~ 17.14%`，符合该开关主要优化 high eval 的预期。
3. low delta 也出现一定改善，尤其 `VtypeBuffer` 为 `-10.54%`；这可能包含代码布局、phase profile 扰动或 high fast path 改变后续 eval 状态传播成本的二阶影响，暂不作为主结论。
4. 与 `NO0243` 手工 Vtype probe 相比，方向一致；当前 generated P0 的 raw 绝对收益略小，但 high phase delta 接近。后续若要默认开启，还需要补更多多 clock / 多 event / inout case 的 correctness gate。

## 下一步

- 暂不默认开启 `posedge_fullpass_specialization`。
- 基于 `input+posedge full-pass` 的当前 best GrhSIM，重新与 GSIM 做 paired small-load 对比，量化剩余 gap。
- 对照 GSIM generated C++，继续定位 GrhSIM 仍多出来的代码形态：slot/ref 间接、changed check、full-pass batch 内临时值/stack spill，以及 eval 外围框架。
