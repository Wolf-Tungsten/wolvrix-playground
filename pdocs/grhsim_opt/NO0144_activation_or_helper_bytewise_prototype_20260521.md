# NO0144: activation OR helper bytewise prototype

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0142 产物中 activation OR helper 调用量仍可见：
  - `grhsim_or_active_u16`: `39018`
  - `grhsim_or_active_u32`: `4696`
  - `grhsim_or_active_u64`: `958`
- 本轮只做 prototype，不修改源码生成器：
  - 复制 NO0142 emit 到 `tmp/no0144_active_or_bytewise_proto/grhsim_emit`。
  - 手工修改 `grhsim_SimTop_runtime.hpp` 中 `grhsim_or_active_u16/u32/u64`，从 `memcpy load/or/store` 改为逐 byte OR。

验证：

- 强制重编 model lib：
  - `make -B -C tmp/no0144_active_or_bytewise_proto/grhsim_emit -j32 CXX=clang++ CXXFLAGS="-std=c++20 -O3"`
  - `real 272.82s`
  - `user 6083.66s`
  - `sys 79.88s`
- 重新链接 difftest emu：
  - `real 0.38s`
- CoreMark 20k：
  - 10k: `host_ms=39481`
  - 20k: `host_ms=135722`
  - `Guest cycle spent=20001`
  - `Host time spent=135731ms`
  - 退出码 `0`，未出现 difftest mismatch。
- CoreMark 50k：
  - 10k: `host_ms=39068`
  - 20k: `host_ms=134883`
  - 30k: `host_ms=233342`
  - 40k: `host_ms=333110`
  - 50k: `host_ms=448233`
  - `Guest cycle spent=50001`
  - `Host time spent=448249ms`
  - 约 `111.5 cycles/s`
  - 退出码 `0`，未出现 difftest mismatch。

判断：

- bytewise activation OR 正确性通过，但 runtime 负向：
  - NO0142 20k：`134819ms`
  - NO0144 20k：`135731ms`
  - NO0142 50k：`444690ms`
  - NO0144 50k：`448249ms`
- 逐 byte OR 没有改善当前热点路径，反而增加指令数和循环/展开压力；不应把该 prototype 落到生成器。
- activation 方向如果继续推进，应优先减少 activation 边数量或 batch 触发次数，而不是替换 u16/u32/u64 OR helper 的内部实现。

