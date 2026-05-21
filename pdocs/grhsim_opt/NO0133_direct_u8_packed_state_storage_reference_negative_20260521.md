# NO0133: direct u8 packed state storage reference negative smoke

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128 最新 20k perf 显示热点继续分散在大量 `eval_commit_batch_*` / `eval_compute_batch_*` 中，不是 `malloc/new` 或单个宽 helper 独占热点。
- 热点 commit batch 中有大量 packed state alias：
  - `auto &... = grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, offset);`
- 实验目标：测试把 bool/u8 packed state storage ref 直接 emit 成 byte pointer indexing，是否能减少 helper/模板引用形态成本。

实现与验证：

- 新增默认关闭 env 开关：
  - `GRHSIM_EMIT_DIRECT_U8_STORAGE_REF`
- 修改路径：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
- 开关打开时，`ValueSlotScalarKind::kBool/kU8` 的 packed scalar storage ref 从：
  - `grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, offset)`
  - 改为 `reinterpret_cast<std::uint8_t *>(state_logic_storage_.data())[offset]`
- 验证：
  - `cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)` 通过。
  - 默认路径 `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，`65.21s`。
  - 开关路径 `GRHSIM_EMIT_DIRECT_U8_STORAGE_REF=1 ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'` 通过，`66.01s`。
  - `python3 -m pip install --no-build-isolation -e wolvrix` 通过。

fresh XiangShan emit/build/runtime：

- fresh emit dir：
  - `tmp/no0133_xs_emit_direct_u8_storage_ref/grhsim_emit`
- schedule 结构保持与 NO0128 对齐：
  - `compute_supernodes=74430`
  - `commit_supernodes=515`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
- emit timing：
  - `activity-schedule=207654ms`
  - `write_grhsim_cpp=43522ms`
  - `total=283325ms`
- 生成代码形态确认：
  - 旧 `grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_`：NO0128 为 `1225870`，NO0133 为 `0`
  - 新 `reinterpret_cast<std::uint8_t *>(state_logic_storage_.data())[offset]`：`1225870`
- model build：
  - `real 284.05s`
  - `user 5800.14s`
  - `sys 63.73s`
  - 成功链接 `tmp/no0133_xs_emit_direct_u8_storage_ref_emu/grhsim-compile/emu`
- CoreMark 20k:
  - 命令包含 `--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
  - 退出码：`0`
  - 未出现 difftest mismatch。
  - 进度：
    - 10k: `host_ms=46048`
    - 20k: `host_ms=148906`
  - `Guest cycle spent`: `20001`
  - `Host time spent`: `148915ms`

判断：

- NO0133 虽然把 `1.22M` 个 u8 packed state storage helper 文本替换为直接 byte reference，但 20k runtime 从 NO0128 的 `109998ms` 退化到 `148915ms`，慢约 `35.4%`。
- 直接 pointer indexing 破坏了编译器对原模板 helper/typed ref 形态的优化，或者增加了 alias 分析压力；不是有效方向。
- 按实验门禁，20k 已明显负向，不继续跑 50k。
- 保留为默认关闭诊断开关，不默认启用；后续不要继续沿 packed u8 storage ref 文本替换投入。

