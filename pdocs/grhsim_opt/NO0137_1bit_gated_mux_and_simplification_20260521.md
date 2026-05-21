# NO0137: 1-bit gated mux-and simplification

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0136 runtime profile 显示 hot clock-gate supernode 中存在大量形态：
  - `clock & grhsim_mux_u64(!clock_value, enable, old)`
- 对 1-bit scalar schedule emit 增加 IR 语义化简：
  - `x & mux(x, a, b) -> x & a`
  - `x & mux(!x, a, b) -> x & b`
- 只在可通过 def/use 证明 gate 与 mux condition 同相/反相时启用，不做生成代码字符串后处理。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp -j32`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过，约 `55.99s`。
- `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0137_xs_gated_mux_and/grhsim_emit`
- schedule 结构：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- 静态代码形态：
  - 旧 `clock & grhsim_mux_u64(...)` 模式：NO0136 为 `386`，NO0137 为 `0`
  - `grhsim_mux_u64(` 总数：`300733 -> 300347`
- emit timing：
  - `activity-schedule=188349ms`
  - `write_grhsim_cpp=39565ms`
  - `total=261011ms`
- model build：
  - `real 266.87s`
  - `user 5760.99s`
  - `sys 62.70s`
- emu build：
  - `real 7.57s`
- CoreMark 20k：
  - `Host time spent=97854ms`
  - 约 `204.4 cycles/s`
- CoreMark 50k：
  - `Host time spent=346589ms`
  - 约 `144.3 cycles/s`
  - 50k progress:
    - 10k: `22996ms`
    - 20k: `97578ms`
    - 30k: `175366ms`
    - 40k: `255328ms`
    - 50k: `346577ms`

判断：

- 该优化精确消除了目标 clock-gate mux 形态，正确性和 50k 均通过。
- 50k 结果回到历史 NO0128 最好档位附近，但没有形成新的结构性突破；仍远未达到 5x 目标。
- 后半段 30k-50k 明显变慢，后续应继续针对真实热点而非仅静态 mux 数量优化。

