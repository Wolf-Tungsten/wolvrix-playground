# NO0123: fixed 2-word bitwise helper runtime result

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


实验目的：

- 针对 65-128 bit 的 wide bitwise helper，避免走通用 dynamic word loop。
- 通过 `GRHSIM_EMIT_FIXED_2WORD_BITWISE=1` 打开固定 2-word helper emit：
  - `grhsim_and_words_2<Width>`
  - `grhsim_or_words_2<Width>`
  - `grhsim_xor_words_2<Width>`
  - `grhsim_xnor_words_2<Width>`
  - `grhsim_not_words_2<Width>`
- 默认路径不变。

实现与验证：

- 代码改动：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
  - `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
- 局部验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)`：通过。
  - `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`：通过。
  - `python3 -m pip install --no-build-isolation -e wolvrix`：通过。

NO0123 fresh emit：

- 输出目录：`tmp/no0123_xs_emit_fixed_2word_bitwise/grhsim_emit`
- 开关：`GRHSIM_EMIT_FIXED_2WORD_BITWISE=1`
- `activity-schedule`: `625415ms`
- `write_grhsim_cpp`: `41141ms`
- total wall time: `694981ms`
- `compute_supernodes`: `63392`
- `commit_supernodes`: `515`
- `dag_edges`: `975745`
- `boundary_activation_edges`: `2460976`
- 源码目录体积：约 `1.9G`

注意：

- NO0123 的 schedule 形态与 NO0122 一致，而不是 NO0118：
  - NO0118：`compute_supernodes=74430`，`dag_edges=485905`，`BAE=2216514`
  - NO0123：`compute_supernodes=63392`，`dag_edges=975745`，`BAE=2460976`
- 因此 NO0123 不是固定 2-word bitwise 相对 NO0118 的 clean A/B；runtime 结论只能评价“fixed 2-word bitwise + 当前 63392 compute supernode schedule 形态”的组合效果。

生成代码计数：

| helper | count |
| --- | ---: |
| fixed 2-word bitwise total | `8869` |
| `grhsim_and_words_2` | `3986` |
| `grhsim_or_words_2` | `3209` |
| `grhsim_not_words_2` | `1106` |
| `grhsim_xor_words_2` | `568` |
| generic bitwise total still remaining | `19270` |

NO0123 build/runtime：

- model build：
  - `real 194.56s`
  - `user 5217.85s`
  - `sys 60.89s`
- difftest emu build：
  - `real 7.42s`
  - 成功链接 `tmp/no0123_xs_emit_fixed_2word_bitwise_emu/grhsim-compile/emu`
- CoreMark 20k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `144038ms`
  - 折算速度：约 `138.9 cycles/s`
- CoreMark 50k：
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - `Guest cycle spent`: `50001`
  - `Host time spent`: `437317ms`
  - 折算速度：约 `114.3 cycles/s`

NO0123 50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `38137` | `262` |
| `20000` | `131706` | `152` |
| `30000` | `227980` | `132` |
| `40000` | `326014` | `123` |
| `50000` | `437303` | `114` |

对比：

| 指标 | NO0118 | NO0122 | NO0123 |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `191465ms` | `612528ms` | `625415ms` |
| `write_grhsim_cpp` | `40062ms` | `41032ms` | `41141ms` |
| `compute_supernodes` | `74430` | `63392` | `63392` |
| `dag_edges` | `485905` | `975745` | `975745` |
| `boundary_activation_edges` | `2216514` | `2460976` | `2460976` |
| model build real | `255.51s` | `161.77s` | `194.56s` |
| 50k `Host time spent` | `358037ms` | `651563ms` | `437317ms` |
| 50k throughput | `139.7 cycles/s` | `76.7 cycles/s` | `114.3 cycles/s` |

判断：

- fixed 2-word bitwise helper 能覆盖 `8869` 个 65-128 bit bitwise 调用，但当前 NO0123 组合没有带来 runtime 收益。
- 相比 NO0118，50k runtime 从 `358037ms` 退化到 `437317ms`，慢 `79280ms`，约 `22.1%`。
- 相比 NO0122，NO0123 runtime 明显恢复，说明 fixed 2-word bitwise 本身可能抵消了一部分当前 63392-supernode schedule 形态的热路径开销；但它仍没有超过 NO0118。
- 由于 NO0123 不是 clean A/B，不能据此判定 fixed 2-word bitwise helper 本身为负收益。若继续评估，需要先固定回 NO0118 的 schedule 形态，再单独打开 `GRHSIM_EMIT_FIXED_2WORD_BITWISE=1`。
- 当前已测最佳仍是 NO0118：CoreMark 50k 约 `139.7 cycles/s`。

